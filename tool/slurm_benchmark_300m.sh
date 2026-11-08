#!/bin/bash
#SBATCH --job-name=pgdm-300m
#SBATCH --partition=grace
#SBATCH --nodes=1
#SBATCH --exclusive
#SBATCH --time=24:00:00
#SBATCH --output=benchmark_300m_%j.out
#SBATCH --error=benchmark_300m_%j.err

# 300M benchmark on grace nodes (4.4T NVMe, 480GB RAM)
# Runs: generation + optimized (3 runs) + baseline (1 run)

set -euo pipefail

REPO_DIR="${SLURM_SUBMIT_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
RESULTS_DIR="${REPO_DIR}/results/run_300m_${SLURM_JOB_ID:-$(date +%s)}"
PG_PORT=15432
PG_USER="challenge"
PG_PASS="challenge"

if [ -d "/scratch/${USER}" ]; then
    LOCAL_DIR="/scratch/${USER}/pgdm_300m_${SLURM_JOB_ID:-$$}"
else
    LOCAL_DIR="/tmp/pgdm_300m_${SLURM_JOB_ID:-$$}"
fi
mkdir -p "${LOCAL_DIR}" "${RESULTS_DIR}"
PG_DATA="${LOCAL_DIR}/pgdata"
PG_LOG="${LOCAL_DIR}/pg.log"
VENV="${REPO_DIR}/.venv"

RUNS=3
SCALES=(1000000 10000000 50000000 100000000 300000000)
METHODS=(optimized baseline)

log() { echo "[$(date '+%H:%M:%S')] $*" | tee -a "${RESULTS_DIR}/benchmark.log"; }

# Environment
log "ENVIRONMENT"
{
    echo "Date: $(date -Iseconds)"
    echo "Host: $(hostname -f)"
    echo "Job: ${SLURM_JOB_ID:-local} / ${SLURM_JOB_PARTITION:-local} / ${SLURM_NODELIST:-$(hostname)}"
    uname -a
    lscpu | grep -E 'Model name|CPU\(s\)|Thread|Core|Socket|cache'
    free -h | head -2
    echo "Results (NFS): $(df -Th "${RESULTS_DIR}" | tail -1)"
    echo "PG data (local): $(df -Th "${LOCAL_DIR}" | tail -1)"
} > "${RESULTS_DIR}/environment.txt" 2>&1
cat "${RESULTS_DIR}/environment.txt"

# PostgreSQL
log "POSTGRESQL"
PG_LOCAL="${HOME}/.local/pgsql"
PG_BIN_DIR=""
for c in "${PG_LOCAL}/bin" \
         "$(command -v initdb 2>/dev/null | xargs dirname 2>/dev/null)" \
         "/usr/pgsql-17/bin" "/usr/lib/postgresql/17/bin"; do
    [ -n "${c}" ] && [ -x "${c}/initdb" ] && PG_BIN_DIR="${c}" && break
done
[ -z "${PG_BIN_DIR}" ] && {
    log "Building PostgreSQL from source..."
    PG_SRC_VER="17.2"
    TMPDIR_PG=$(mktemp -d)
    curl -fsSL -o "${TMPDIR_PG}/pg.tar.bz2" \
        "https://ftp.postgresql.org/pub/source/v${PG_SRC_VER}/postgresql-${PG_SRC_VER}.tar.bz2" 2>/dev/null || \
    wget -q -O "${TMPDIR_PG}/pg.tar.bz2" \
        "https://ftp.postgresql.org/pub/source/v${PG_SRC_VER}/postgresql-${PG_SRC_VER}.tar.bz2"
    tar xjf "${TMPDIR_PG}/pg.tar.bz2" -C "${TMPDIR_PG}"
    cd "${TMPDIR_PG}/postgresql-${PG_SRC_VER}"
    ./configure --prefix="${PG_LOCAL}" --without-readline --without-zlib 2>&1 | tail -1
    make -j$(nproc) 2>&1 | tail -1
    make install 2>&1 | tail -1
    cd "${REPO_DIR}"
    rm -rf "${TMPDIR_PG}"
    PG_BIN_DIR="${PG_LOCAL}/bin"
}
export LD_LIBRARY_PATH="${PG_LOCAL}/lib:${LD_LIBRARY_PATH:-}"
export PATH="${PG_BIN_DIR}:${PATH}"
log "$("${PG_BIN_DIR}/postgres" --version)"

# Tune for 300M: aggressive memory settings
TOTAL_RAM_KB=$(grep MemTotal /proc/meminfo | awk '{print $2}')
SHARED_BUF_MB=$(( TOTAL_RAM_KB / 4 / 1024 ))
[ ${SHARED_BUF_MB} -gt 131072 ] && SHARED_BUF_MB=131072
[ ${SHARED_BUF_MB} -lt 8192 ] && SHARED_BUF_MB=8192
EFFECTIVE_CACHE_MB=$(( TOTAL_RAM_KB * 3 / 4 / 1024 ))
log "shared_buffers=${SHARED_BUF_MB}MB effective_cache=${EFFECTIVE_CACHE_MB}MB"

"${PG_BIN_DIR}/initdb" -D "${PG_DATA}" --auth=trust --username="${PG_USER}" -E UTF8 >/dev/null 2>&1
cat >> "${PG_DATA}/postgresql.conf" << PGCONF
port = ${PG_PORT}
listen_addresses = 'localhost'
shared_buffers = '${SHARED_BUF_MB}MB'
work_mem = '1GB'
maintenance_work_mem = '4GB'
wal_buffers = '256MB'
max_wal_size = '16GB'
min_wal_size = '4GB'
effective_cache_size = '${EFFECTIVE_CACHE_MB}MB'
max_parallel_workers_per_gather = 8
max_parallel_workers = 16
max_worker_processes = 32
max_parallel_maintenance_workers = 8
checkpoint_completion_target = 0.9
random_page_cost = 1.1
effective_io_concurrency = 200
jit = on
huge_pages = try
logging_collector = off
PGCONF
echo -e "local all all trust\nhost all all 127.0.0.1/32 trust" > "${PG_DATA}/pg_hba.conf"

start_pg() { "${PG_BIN_DIR}/pg_ctl" -D "${PG_DATA}" -l "${PG_LOG}" -o "-p ${PG_PORT}" start -w >/dev/null 2>&1; }
stop_pg()  { "${PG_BIN_DIR}/pg_ctl" -D "${PG_DATA}" stop -m fast -w >/dev/null 2>&1 || true; }
cold_restart() { stop_pg; sync; sudo -n sh -c 'echo 3 > /proc/sys/vm/drop_caches' 2>/dev/null || true; start_pg; sleep 2; }

# Python
log "PYTHON"
export PATH="${HOME}/.local/bin:${PATH}"
if ! command -v uv &>/dev/null; then
    curl -LsSf https://astral.sh/uv/install.sh | sh 2>/dev/null
fi
[ ! -d "${VENV}" ] && (cd "${REPO_DIR}" && uv sync 2>&1 | tail -3)
PYTHON="${VENV}/bin/python"
log "$(${PYTHON} --version 2>&1)"

# Benchmark runner (same as main script)
cat > "${RESULTS_DIR}/run_single.py" << 'PYEOF'
import json, os, socket, sys, time, threading
from pathlib import Path

sys.path.insert(0, str(Path(os.environ["REPO_DIR"]) / "src"))
from pgdm.services.postgres_service import PostgresAdminService

def measured_total_seconds(report):
    return sum(max(float(i.get("seconds") or 0), 0)
               for i in (report.get("items") or []) if i.get("include_in_total", True))

def build_report_lines(report):
    lines = [f"Source rows: {report.get('source_rows', 0):,}",
             f"Inserted: {report.get('total_rows_inserted', 0):,}",
             f"Measured total: {measured_total_seconds(report):.3f}s", ""]
    for item in report.get("items") or []:
        if item.get("seconds", 0) > 0.01:
            lines.append(f"  {item['seconds']:8.3f}s | {str(item.get('rows','')):>10} | {item.get('name','')[:60]}")
    return "\n".join(lines)

ASSET_DIR = Path(os.environ["REPO_DIR"]) / "asset" / "sql"
RECIPE_FILES = [
    ("01_table3.sql", "public.table3"), ("02_table4.sql", "public.table4"),
    ("03_table1.sql", "public.table1"), ("04_table5.sql", "public.table5"),
    ("05_table6.sql", "public.table6"), ("06_table2.sql", "public.table2"),
]
DATABASE = "kaggle_challenge"
TABLES = [t for _, t in RECIPE_FILES]
PG_PORT = int(os.environ["PG_PORT"])
PG_USER, PG_PASS = os.environ["PG_USER"], os.environ["PG_PASS"]
METHOD = os.environ["BENCH_METHOD"]
RUN_ID = os.environ["BENCH_RUN_ID"]
OUT_DIR = os.environ["BENCH_OUT_DIR"]
PG_BIN = os.environ.get("PG_BIN_DIR", os.path.expanduser("~/.local/pgsql/bin"))

import paramiko
service = PostgresAdminService()
ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
for p in [22, 2222]:
    try: ssh.connect("localhost", p, os.environ["USER"], look_for_keys=True, allow_agent=True, timeout=5); break
    except Exception: continue
service.ssh_client = ssh
service.sql_username = PG_USER
service.sql_password = PG_PASS
service.postgres_port = PG_PORT
_orig_run = service.run_remote_command
def _patched_run(command, **kw):
    return _orig_run(f"export PATH={PG_BIN}:$PATH; {command}", **kw)
service.run_remote_command = _patched_run

service.run_remote_command(
    f"psql -h localhost -p {PG_PORT} -U {PG_USER} -d {DATABASE} "
    f"-X -q -v ON_ERROR_STOP=1 -c \"TRUNCATE {','.join(TABLES)} CASCADE;\"")
try:
    service.run_remote_command(
        f"psql -h localhost -p {PG_PORT} -U {PG_USER} -d postgres_data_manager "
        f"-X -q -c \"DELETE FROM app_control.table_version_dependencies; "
        f"DELETE FROM app_control.table_versions WHERE operation_kind = 'cross_table_expand_v1';\"")
except Exception: pass

def pg_rss_mb():
    try:
        pids = [l.split()[0] for l in os.popen(f"pgrep -f 'postgres.*-p {PG_PORT}'").readlines()]
        return sum(int(open(f"/proc/{p}/status").read().split("VmRSS:")[1].split()[0])
                   for p in pids if os.path.exists(f"/proc/{p}/status")) // 1024
    except Exception: return 0

def db_size():
    try:
        out = service.run_remote_command(
            f"psql -h localhost -p {PG_PORT} -U {PG_USER} -d {DATABASE} -qAt "
            f"-c \"SELECT pg_database_size('{DATABASE}');\"")
        return int(out.strip()) // (1024*1024)
    except Exception: return 0

db_before = db_size()
peak_rss = [pg_rss_mb()]
stop_sampling = threading.Event()
def sample_rss():
    while not stop_sampling.is_set():
        r = pg_rss_mb()
        if r > peak_rss[0]: peak_rss[0] = r
        stop_sampling.wait(1.0)
sampler = threading.Thread(target=sample_rss, daemon=True)
sampler.start()

dests = [{"table_name": t, "version_title": "Benchmark", "sql": (ASSET_DIR / f).read_text()}
         for f, t in RECIPE_FILES]
timing = service.create_cross_table_expansion_timing_report(
    DATABASE, "public.raw_data", ["group001"], [t for _, t in RECIPE_FILES])
service.ensure_admin_schema()

wall_start = time.perf_counter()
if METHOD == "baseline":
    result = service.execute_cross_table_expansion(
        database_name=DATABASE, source_full_table_name="public.raw_data",
        raw_schemas=["group001"], destinations=dests, timing_report=timing)
else:
    result = service.execute_optimized_cross_table_expansion(
        database_name=DATABASE, source_full_table_name="public.raw_data",
        raw_schemas=["group001"], destinations=dests, timing_report=timing)

service.register_cross_table_expansion_versions(
    expansion_result=result, requested_by="slurm_benchmark",
    workstation_name=socket.gethostname(), timing_report=timing)
wall = time.perf_counter() - wall_start
timing["completed_at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
stop_sampling.set(); sampler.join(timeout=2)

measured = measured_total_seconds(timing)
inserted = timing.get("total_rows_inserted", 0)
rows = timing.get("source_rows", 0)
db_after = db_size()
temp_storage_mb = max(0, db_after - db_before)

Path(f"{OUT_DIR}/{RUN_ID}_report.txt").write_text(build_report_lines(timing), encoding="utf-8")
Path(f"{OUT_DIR}/{RUN_ID}_timing.json").write_text(
    json.dumps(timing, indent=2, default=str), encoding="utf-8")

counts = {}
for t in TABLES:
    out = service.run_remote_command(
        f"psql -h localhost -p {PG_PORT} -U {PG_USER} -d {DATABASE} -qAt -c \"SELECT count(*) FROM {t};\"")
    counts[t] = int(out.strip())
correct = sum(counts.values()) == inserted if inserted > 0 else True

print(f"{METHOD},{rows},{os.environ.get('BENCH_RUN_NUM','0')},{measured:.3f},{wall:.3f},{inserted},{peak_rss[0]},{temp_storage_mb},{1 if correct else 0}")
if not correct:
    sys.stderr.write(f"CORRECTNESS FAIL: inserted={inserted} verified={sum(counts.values())} counts={counts}\n")
service.close()
PYEOF

# Main loop
log "BENCHMARK START"
start_pg
"${PG_BIN_DIR}/psql" -h localhost -p ${PG_PORT} -U ${PG_USER} -d postgres -qAt \
    -c "ALTER ROLE ${PG_USER} WITH SUPERUSER;" 2>/dev/null || true

echo "method,rows,run,measured_s,wall_s,inserted,peak_rss_mb,temp_storage_mb,correct" > "${RESULTS_DIR}/all_results.csv"

for ROWS in "${SCALES[@]}"; do
    log "━━━ ${ROWS} rows ━━━"

    # Check disk space before generation
    AVAIL_GB=$(df -BG "${LOCAL_DIR}" | tail -1 | awk '{print $4}' | tr -d 'G')
    NEEDED_GB=$(( ROWS / 500000 + 10 ))
    if [ "${AVAIL_GB}" -lt "${NEEDED_GB}" ]; then
        log "  SKIP: need ~${NEEDED_GB}GB, only ${AVAIL_GB}GB available"
        continue
    fi

    export PGHOST=localhost PGPORT=${PG_PORT} PGUSER=${PG_USER} PGPASSWORD=${PG_PASS} PG_KAGGLE_CHALLENGE_PASS=${PG_PASS}

    GEN_START=$(date +%s)
    ${PYTHON} "${REPO_DIR}/tool/generate_database.py" \
        --rows "${ROWS}" --replace \
        --host localhost --postgres_port "${PG_PORT}" \
        --user "${PG_USER}" --user_pass "${PG_PASS}" \
        --admin_database postgres 2>&1 | tail -3
    GEN_ELAPSED=$(( $(date +%s) - GEN_START ))
    log "  Generated in ${GEN_ELAPSED}s"

    # For 300M: only 1 run of baseline (too slow for 3), 3 runs of optimized
    if [ "${ROWS}" -ge 100000000 ]; then
        LOCAL_RUNS_BASELINE=1
        LOCAL_RUNS_OPTIMIZED=1
    elif [ "${ROWS}" -ge 10000000 ]; then
        LOCAL_RUNS_BASELINE=1
        LOCAL_RUNS_OPTIMIZED=3
    else
        LOCAL_RUNS_BASELINE=${RUNS}
        LOCAL_RUNS_OPTIMIZED=${RUNS}
    fi

    for METHOD in "${METHODS[@]}"; do
        if [ "${METHOD}" = "baseline" ]; then
            N_RUNS=${LOCAL_RUNS_BASELINE}
        else
            N_RUNS=${LOCAL_RUNS_OPTIMIZED}
        fi

        log "  ${METHOD} (${N_RUNS} runs)"
        export REPO_DIR PG_PORT PG_USER PG_PASS PG_BIN_DIR BENCH_METHOD=${METHOD} BENCH_OUT_DIR="${RESULTS_DIR}"

        cold_restart
        BENCH_RUN_ID="warmup_${METHOD}_${ROWS}" BENCH_RUN_NUM=0 \
            ${PYTHON} "${RESULTS_DIR}/run_single.py" > "${RESULTS_DIR}/warmup_${METHOD}_${ROWS}.out" 2>&1 || {
            log "    WARMUP FAILED"; cat "${RESULTS_DIR}/warmup_${METHOD}_${ROWS}.out" | tail -3 >> "${RESULTS_DIR}/benchmark.log"; continue; }

        for RUN in $(seq 1 ${N_RUNS}); do
            cold_restart
            RESULT=$(BENCH_RUN_ID="${METHOD}_${ROWS}_run${RUN}" BENCH_RUN_NUM=${RUN} \
                ${PYTHON} "${RESULTS_DIR}/run_single.py" 2>"${RESULTS_DIR}/${METHOD}_${ROWS}_run${RUN}.err") || {
                log "    run${RUN} FAILED"; continue; }
            echo "${RESULT}" >> "${RESULTS_DIR}/all_results.csv"
            log "    ${RESULT}"
        done
    done
done

# Summary
log "SUMMARY"
export RESULTS_DIR
${PYTHON} - << 'SUMEOF'
import csv, os, statistics, json
from collections import defaultdict

rd = os.environ.get("RESULTS_DIR", ".")
data = defaultdict(lambda: {"times": [], "rss": [], "temp": []})
with open(f"{rd}/all_results.csv") as f:
    for r in csv.DictReader(f):
        k = (r["method"], int(r["rows"]))
        data[k]["times"].append(float(r["measured_s"]))
        data[k]["rss"].append(int(r["peak_rss_mb"]))
        data[k]["temp"].append(int(r["temp_storage_mb"]))

print(f"{'Method':<11} {'Rows':>12} {'Median':>10} {'Min':>10} {'Max':>10} {'RSS':>6} {'Temp':>6}")
print("-" * 70)
summary = []
for (m, r), d in sorted(data.items(), key=lambda x: (x[0][1], x[0][0])):
    med = statistics.median(d["times"])
    rss = max(d["rss"])
    tmp = max(d["temp"])
    print(f"{m:<11} {r:>12,} {med:>9.1f}s {min(d['times']):>9.1f}s {max(d['times']):>9.1f}s {rss:>5}M {tmp:>5}M")
    summary.append({"method":m, "rows":r, "median":med, "min":min(d["times"]),
                     "max":max(d["times"]), "peak_rss_mb":rss, "temp_storage_mb":tmp})

bl = {s["rows"]: s for s in summary if s["method"]=="baseline"}
op = {s["rows"]: s for s in summary if s["method"]=="optimized"}
print(f"\n{'Rows':>12} {'Baseline':>10} {'Optimized':>10} {'Speedup':>8}")
print("-" * 50)
for r in sorted(bl):
    if r in op:
        print(f"{r:>12,} {bl[r]['median']:>9.1f}s {op[r]['median']:>9.1f}s {bl[r]['median']/op[r]['median']:>7.2f}x")

with open(f"{rd}/summary.json", "w") as f:
    json.dump(summary, f, indent=2)
SUMEOF

stop_pg
rm -rf "${LOCAL_DIR}"
log "DONE. Results: ${RESULTS_DIR}/"
