#!/bin/bash
#SBATCH --job-name=pgdm-bench
#SBATCH --nodes=1
#SBATCH --exclusive
#SBATCH --time=24:00:00
#SBATCH --output=benchmark_%j.out
#SBATCH --error=benchmark_%j.err

# Reproducible expansion benchmark.
#
# Protocol:
#   - Baseline: original code + stock PG config (128MB shared_buffers)
#   - Optimized: optimized code + tuned PG config (25% RAM shared_buffers)
#   - Database regenerated before EACH method (guarantees FK constraints exist)
#   - PG restarted with correct config + OS page cache dropped before each run
#   - 1 warmup (discarded) + 3 measured runs per (method × scale)
#
# Usage:
#   sbatch -p lunaris tool/slurm_benchmark.sh                      # 10K-10M
#   sbatch -p grace   tool/slurm_benchmark.sh 10K 50K ... 300M     # custom scales
#   sbatch -p lunaris --time=00:30:00 tool/slurm_benchmark.sh 10K  # quick test

set -euo pipefail

REPO_DIR="${SLURM_SUBMIT_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
RESULTS_DIR="${REPO_DIR}/results/run_${SLURM_JOB_ID:-$(date +%s)}"
PG_PORT=15432
PG_USER="challenge"
PG_PASS="challenge"
RUNS=3

# Parse scales from args or use defaults
if [ $# -gt 0 ]; then
    SCALES=()
    for arg in "$@"; do
        case "${arg}" in
            10K|10k)     SCALES+=(10000) ;;
            50K|50k)     SCALES+=(50000) ;;
            100K|100k)   SCALES+=(100000) ;;
            250K|250k)   SCALES+=(250000) ;;
            500K|500k)   SCALES+=(500000) ;;
            1M|1m)       SCALES+=(1000000) ;;
            5M|5m)       SCALES+=(5000000) ;;
            10M|10m)     SCALES+=(10000000) ;;
            50M|50m)     SCALES+=(50000000) ;;
            100M|100m)   SCALES+=(100000000) ;;
            300M|300m)   SCALES+=(300000000) ;;
            *)           SCALES+=("${arg}") ;;
        esac
    done
else
    SCALES=(10000 50000 100000 250000 500000 1000000 5000000 10000000)
fi

# Local storage (NVMe/SSD preferred over NFS)
for d in "/ssd/${USER}" "/scratch/${USER}" "/tmp"; do
    if [ -d "$(dirname "${d}")" ]; then
        mkdir -p "${d}" 2>/dev/null && LOCAL_DIR="${d}/pgdm_${SLURM_JOB_ID:-$$}" && break
    fi
done
mkdir -p "${LOCAL_DIR}" "${RESULTS_DIR}"
PG_DATA="${LOCAL_DIR}/pgdata"

log() { echo "[$(date '+%H:%M:%S')] $*" | tee -a "${RESULTS_DIR}/benchmark.log"; }

# ── Environment ──
log "ENVIRONMENT"
{
    echo "Date: $(date -Iseconds)"
    echo "Host: $(hostname -f)"
    echo "Job: ${SLURM_JOB_ID:-local} / ${SLURM_JOB_PARTITION:-local} / ${SLURM_NODELIST:-$(hostname)}"
    echo "Scales: ${SCALES[*]}"
    echo "Runs: ${RUNS}"
    uname -a
    lscpu | grep -E 'Model name|CPU\(s\)|Thread|Core|Socket|cache'
    free -h | head -2
    echo "Local storage: $(df -Th "${LOCAL_DIR}" | tail -1)"
} > "${RESULTS_DIR}/environment.txt" 2>&1
cat "${RESULTS_DIR}/environment.txt"

# ── PostgreSQL ──
log "POSTGRESQL"
PG_LOCAL="${HOME}/.local/pgsql"
PG_BIN_DIR=""
for c in "${PG_LOCAL}/bin" "$(command -v initdb 2>/dev/null | xargs dirname 2>/dev/null)"; do
    [ -n "${c}" ] && [ -x "${c}/initdb" ] && PG_BIN_DIR="${c}" && break
done
[ -z "${PG_BIN_DIR}" ] && {
    log "Building PostgreSQL 17.2 from source..."
    T=$(mktemp -d)
    curl -fsSL "https://ftp.postgresql.org/pub/source/v17.2/postgresql-17.2.tar.bz2" -o "${T}/pg.tar.bz2" 2>/dev/null || \
    wget -q "https://ftp.postgresql.org/pub/source/v17.2/postgresql-17.2.tar.bz2" -O "${T}/pg.tar.bz2"
    tar xjf "${T}/pg.tar.bz2" -C "${T}"
    (cd "${T}/postgresql-17.2" && ./configure --prefix="${PG_LOCAL}" --without-readline --without-zlib >/dev/null 2>&1 && make -j$(nproc) >/dev/null 2>&1 && make install >/dev/null 2>&1)
    rm -rf "${T}"
    PG_BIN_DIR="${PG_LOCAL}/bin"
}
export LD_LIBRARY_PATH="${PG_LOCAL}/lib:${LD_LIBRARY_PATH:-}"
export PATH="${PG_BIN_DIR}:${PATH}"
log "$("${PG_BIN_DIR}/postgres" --version)"

# Compute tuned config
TOTAL_RAM_KB=$(grep MemTotal /proc/meminfo | awk '{print $2}')
TUNED_SHARED_BUF_MB=$(( TOTAL_RAM_KB / 4 / 1024 ))
[ ${TUNED_SHARED_BUF_MB} -gt 65536 ] && TUNED_SHARED_BUF_MB=65536
[ ${TUNED_SHARED_BUF_MB} -lt 2048 ] && TUNED_SHARED_BUF_MB=2048
TUNED_EFF_CACHE_MB=$(( TOTAL_RAM_KB * 3 / 4 / 1024 ))

# Init PG cluster (once)
"${PG_BIN_DIR}/initdb" -D "${PG_DATA}" --auth=trust --username="${PG_USER}" -E UTF8 >/dev/null 2>&1
echo -e "local all all trust\nhost all all 127.0.0.1/32 trust" > "${PG_DATA}/pg_hba.conf"

write_config() {
    cat > "${PG_DATA}/postgresql.auto.conf" << EOF
# Config: $1
EOF
    if [ "$1" = "stock" ]; then
        cat >> "${PG_DATA}/postgresql.auto.conf" << EOF
shared_buffers = '128MB'
work_mem = '4MB'
maintenance_work_mem = '64MB'
wal_buffers = '4MB'
max_wal_size = '1GB'
effective_cache_size = '4GB'
max_parallel_workers_per_gather = 2
EOF
    else
        cat >> "${PG_DATA}/postgresql.auto.conf" << EOF
shared_buffers = '${TUNED_SHARED_BUF_MB}MB'
work_mem = '256MB'
maintenance_work_mem = '1GB'
wal_buffers = '64MB'
max_wal_size = '8GB'
effective_cache_size = '${TUNED_EFF_CACHE_MB}MB'
max_parallel_workers_per_gather = 4
max_parallel_workers = 8
max_worker_processes = 16
max_parallel_maintenance_workers = 4
checkpoint_completion_target = 0.9
random_page_cost = 1.1
effective_io_concurrency = 200
huge_pages = try
synchronous_commit = off
full_page_writes = off
EOF
    fi
}

# Append port to main conf (only once)
grep -q "^port = ${PG_PORT}" "${PG_DATA}/postgresql.conf" || \
    echo -e "\nport = ${PG_PORT}\nlisten_addresses = 'localhost'\nlogging_collector = off\njit = on" >> "${PG_DATA}/postgresql.conf"

start_pg() { "${PG_BIN_DIR}/pg_ctl" -D "${PG_DATA}" -l "${LOCAL_DIR}/pg.log" -o "-p ${PG_PORT}" start -w >/dev/null 2>&1; }
stop_pg()  { "${PG_BIN_DIR}/pg_ctl" -D "${PG_DATA}" stop -m fast -w >/dev/null 2>&1 || true; }
drop_page_cache() {
    sync
    if sudo -n sh -c 'echo 3 > /proc/sys/vm/drop_caches' 2>/dev/null; then
        return
    fi
    # Fallback: evict PG data files from page cache via posix_fadvise
    ${PYTHON} "${REPO_DIR}/tool/drop_cache.py" "${LOCAL_DIR}" 2>/dev/null || true
}

cold_start() {
    local cfg=$1
    stop_pg
    drop_page_cache
    write_config "${cfg}"
    start_pg
    sleep 1
}

generate_db() {
    local rows=$1
    export PGHOST=localhost PGPORT=${PG_PORT} PGUSER=${PG_USER} PGPASSWORD=${PG_PASS} PG_KAGGLE_CHALLENGE_PASS=${PG_PASS}
    ${PYTHON} "${REPO_DIR}/tool/generate_database.py" \
        --rows "${rows}" --replace \
        --host localhost --postgres_port "${PG_PORT}" \
        --user "${PG_USER}" --user_pass "${PG_PASS}" \
        --admin_database postgres 2>&1 | tail -2
}

# ── Python ──
log "PYTHON"
export PATH="${HOME}/.local/bin:${PATH}"
command -v uv &>/dev/null || { curl -LsSf https://astral.sh/uv/install.sh | sh 2>/dev/null; export PATH="${HOME}/.local/bin:${PATH}"; }
VENV="${REPO_DIR}/.venv"
[ ! -d "${VENV}" ] && (cd "${REPO_DIR}" && uv sync 2>&1 | tail -3)
PYTHON="${VENV}/bin/python"
log "$(${PYTHON} --version 2>&1)"

# ── Benchmark runner ──
cat > "${RESULTS_DIR}/run_one.py" << 'PYEOF'
import json, os, socket, sys, time, threading
from pathlib import Path

sys.path.insert(0, str(Path(os.environ["REPO_DIR"]) / "src"))
from pgdm.services.postgres_service import PostgresAdminService

def measured_total(report):
    return sum(max(float(i.get("seconds") or 0), 0)
               for i in (report.get("items") or []) if i.get("include_in_total", True))

ASSET = Path(os.environ["REPO_DIR"]) / "asset" / "sql"
RECIPES = [("01_table3.sql","public.table3"),("02_table4.sql","public.table4"),
    ("03_table1.sql","public.table1"),("04_table5.sql","public.table5"),
    ("05_table6.sql","public.table6"),("06_table2.sql","public.table2")]
DB = "kaggle_challenge"
TABLES = [t for _,t in RECIPES]
PORT = int(os.environ["PG_PORT"])
USER = os.environ["PG_USER"]
PASS = os.environ["PG_PASS"]
METHOD = os.environ["BENCH_METHOD"]
RUN_ID = os.environ["BENCH_RUN_ID"]
OUT = os.environ["BENCH_OUT_DIR"]
PG_BIN = os.environ.get("PG_BIN_DIR", os.path.expanduser("~/.local/pgsql/bin"))

import paramiko
svc = PostgresAdminService()
ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
for p in [22, 2222]:
    try: ssh.connect("localhost", p, os.environ["USER"], look_for_keys=True, allow_agent=True, timeout=5); break
    except: continue
svc.ssh_client = ssh
svc.sql_username = USER
svc.sql_password = PASS
svc.postgres_port = PORT
_orig = svc.run_remote_command
svc.run_remote_command = lambda cmd, **kw: _orig(f"export PATH={PG_BIN}:$PATH; {cmd}", **kw)

# Clean destinations (FKs are guaranteed by fresh generate_database)
svc.run_remote_command(f"psql -h localhost -p {PORT} -U {USER} -d {DB} -X -q -v ON_ERROR_STOP=1 "
    f"-c \"TRUNCATE {','.join(TABLES)} CASCADE;\"")
try: svc.run_remote_command(f"psql -h localhost -p {PORT} -U {USER} -d postgres_data_manager "
    f"-X -q -c \"DELETE FROM app_control.table_version_dependencies; "
    f"DELETE FROM app_control.table_versions WHERE operation_kind = 'cross_table_expand_v1';\"")
except: pass

# Verify FK constraints exist (safety check)
fk_out = svc.run_remote_command(f"psql -h localhost -p {PORT} -U {USER} -d {DB} -qAt "
    f"-c \"SELECT count(*) FROM pg_constraint WHERE contype='f' AND conrelid::regclass::text IN ('table1','table2','table5','table6');\"")
fk_count = int(fk_out.strip())
if fk_count < 6:
    sys.stderr.write(f"FK CHECK FAILED: only {fk_count} FKs found (need 6). Aborting.\n")
    sys.exit(1)

# Measure peak RSS
def pg_rss_mb():
    try:
        return sum(int(open(f"/proc/{p.split()[0]}/status").read().split("VmRSS:")[1].split()[0])
                   for p in os.popen(f"pgrep -af 'postgres.*-p {PORT}'").readlines()
                   if os.path.exists(f"/proc/{p.split()[0]}/status")) // 1024
    except: return 0

def db_size_mb():
    try: return int(svc.run_remote_command(
        f"psql -h localhost -p {PORT} -U {USER} -d {DB} -qAt -c \"SELECT pg_database_size('{DB}');\"").strip()) // (1024*1024)
    except: return 0

db_before = db_size_mb()
peak_rss = [pg_rss_mb()]
stop = threading.Event()
def sample():
    while not stop.is_set():
        r = pg_rss_mb()
        if r > peak_rss[0]: peak_rss[0] = r
        stop.wait(1.0)
threading.Thread(target=sample, daemon=True).start()

# Run expansion
dests = [{"table_name":t,"version_title":"Benchmark","sql":(ASSET/f).read_text()} for f,t in RECIPES]
timing = svc.create_cross_table_expansion_timing_report(DB,"public.raw_data",["group001"],[t for _,t in RECIPES])
svc.ensure_admin_schema()

wall_start = time.perf_counter()
if METHOD == "baseline":
    result = svc.execute_cross_table_expansion(
        database_name=DB, source_full_table_name="public.raw_data",
        raw_schemas=["group001"], destinations=dests, timing_report=timing)
else:
    result = svc.execute_optimized_cross_table_expansion(
        database_name=DB, source_full_table_name="public.raw_data",
        raw_schemas=["group001"], destinations=dests, timing_report=timing)

svc.register_cross_table_expansion_versions(
    expansion_result=result, requested_by="benchmark",
    workstation_name=socket.gethostname(), timing_report=timing)
wall = time.perf_counter() - wall_start
stop.set()

measured = measured_total(timing)
inserted = timing.get("total_rows_inserted", 0)
rows = timing.get("source_rows", 0)
temp_mb = max(0, db_size_mb() - db_before)

# Verify correctness
counts = {}
for t in TABLES:
    counts[t] = int(svc.run_remote_command(
        f"psql -h localhost -p {PORT} -U {USER} -d {DB} -qAt -c \"SELECT count(*) FROM {t};\"").strip())
correct = sum(counts.values()) == inserted if inserted > 0 else True

Path(f"{OUT}/{RUN_ID}_timing.json").write_text(json.dumps(timing, indent=2, default=str))
print(f"{METHOD},{rows},{os.environ.get('BENCH_RUN_NUM','0')},{measured:.3f},{wall:.3f},{inserted},{peak_rss[0]},{temp_mb},{1 if correct else 0}")
if not correct:
    sys.stderr.write(f"WRONG: inserted={inserted} verified={sum(counts.values())}\n")
svc.close()
PYEOF

# ── Main loop ──
log "BENCHMARK: ${#SCALES[@]} scales × 2 methods × ${RUNS} runs"
echo "method,rows,run,measured_s,wall_s,inserted,peak_rss_mb,temp_storage_mb,correct" > "${RESULTS_DIR}/all_results.csv"

for ROWS in "${SCALES[@]}"; do
    # Check disk space
    AVAIL_GB=$(df -BG "${LOCAL_DIR}" | tail -1 | awk '{print $4}' | tr -d 'G')
    # ~4GB per 1M rows (raw_data + destinations + temp + WAL)
    NEEDED_GB=$(( ROWS / 250000 + 10 ))
    if [ "${AVAIL_GB}" -lt "${NEEDED_GB}" ]; then
        log "━━━ ${ROWS} SKIP: need ~${NEEDED_GB}GB, only ${AVAIL_GB}GB free ━━━"
        continue
    fi

    log "━━━ ${ROWS} rows ━━━"

    # For large scales, reduce runs
    if [ "${ROWS}" -ge 100000000 ]; then R=1; else R=${RUNS}; fi

    for METHOD in baseline optimized; do
        if [ "${METHOD}" = "baseline" ]; then CFG="stock"; else CFG="tuned"; fi

        log "  ${METHOD} (${CFG} config, ${R} runs)"

        # CRITICAL: regenerate database before each method
        # This guarantees FK constraints exist for baseline
        cold_start "${CFG}"
        "${PG_BIN_DIR}/psql" -h localhost -p ${PG_PORT} -U ${PG_USER} -d postgres -qAt \
            -c "ALTER ROLE ${PG_USER} WITH SUPERUSER;" 2>/dev/null || true
        generate_db "${ROWS}"

        export REPO_DIR PG_PORT PG_USER PG_PASS PG_BIN_DIR
        export BENCH_METHOD=${METHOD} BENCH_OUT_DIR="${RESULTS_DIR}"

        # Warmup
        cold_start "${CFG}"
        BENCH_RUN_ID="warmup_${METHOD}_${ROWS}" BENCH_RUN_NUM=0 \
            ${PYTHON} "${RESULTS_DIR}/run_one.py" >"${RESULTS_DIR}/warmup_${METHOD}_${ROWS}.out" 2>&1 || {
            log "    WARMUP FAILED"
            tail -5 "${RESULTS_DIR}/warmup_${METHOD}_${ROWS}.out" >> "${RESULTS_DIR}/benchmark.log"
            continue
        }

        # Measured runs
        for RUN in $(seq 1 ${R}); do
            cold_start "${CFG}"
            RESULT=$(BENCH_RUN_ID="${METHOD}_${ROWS}_run${RUN}" BENCH_RUN_NUM=${RUN} \
                ${PYTHON} "${RESULTS_DIR}/run_one.py" 2>"${RESULTS_DIR}/${METHOD}_${ROWS}_run${RUN}.err") || {
                log "    run${RUN} FAILED"
                tail -3 "${RESULTS_DIR}/${METHOD}_${ROWS}_run${RUN}.err" >> "${RESULTS_DIR}/benchmark.log"
                continue
            }
            echo "${RESULT}" >> "${RESULTS_DIR}/all_results.csv"
            log "    ${RESULT}"
        done
    done
done

# ── Summary ──
log "SUMMARY"
export RESULTS_DIR
${PYTHON} - << 'SUMEOF'
import csv, os, statistics, json
from collections import defaultdict
rd = os.environ["RESULTS_DIR"]
data = defaultdict(lambda: {"t":[],"rss":[],"tmp":[]})
with open(f"{rd}/all_results.csv") as f:
    for r in csv.DictReader(f):
        k = (r["method"], int(r["rows"]))
        data[k]["t"].append(float(r["measured_s"]))
        data[k]["rss"].append(int(r["peak_rss_mb"]))
        data[k]["tmp"].append(int(r["temp_storage_mb"]))

print(f"{'Method':<11} {'Rows':>12} {'Median':>10} {'Min':>10} {'Max':>10} {'RSS':>6} {'Temp':>6}")
print("-" * 65)
summary = []
for (m,r),d in sorted(data.items(), key=lambda x:(x[0][1],x[0][0])):
    med = statistics.median(d["t"])
    summary.append({"method":m,"rows":r,"median":med,"min":min(d["t"]),"max":max(d["t"]),
                     "rss_mb":max(d["rss"]),"temp_mb":max(d["tmp"]),"runs":len(d["t"])})
    print(f"{m:<11} {r:>12,} {med:>9.1f}s {min(d['t']):>9.1f}s {max(d['t']):>9.1f}s {max(d['rss']):>5}M {max(d['tmp']):>5}M")

bl = {s["rows"]:s["median"] for s in summary if s["method"]=="baseline"}
op = {s["rows"]:s["median"] for s in summary if s["method"]=="optimized"}
print(f"\n{'Rows':>12} {'Baseline':>12} {'Optimized':>12} {'Speedup':>8}")
print(f"{'':>12} {'(stock)':>12} {'(tuned)':>12}")
print("-" * 50)
for r in sorted(bl):
    if r in op: print(f"{r:>12,} {bl[r]:>11.1f}s {op[r]:>11.1f}s {bl[r]/op[r]:>7.2f}x")

with open(f"{rd}/summary.json","w") as f: json.dump(summary,f,indent=2)
SUMEOF

stop_pg
rm -rf "${LOCAL_DIR}"
log "DONE. Results: ${RESULTS_DIR}/"
