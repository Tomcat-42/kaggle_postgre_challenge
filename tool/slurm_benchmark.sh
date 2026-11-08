#!/bin/bash
#SBATCH --job-name=pgdm-bench
#SBATCH --partition=lunaris
#SBATCH --nodes=1
#SBATCH --exclusive
#SBATCH --time=14:00:00
#SBATCH --output=benchmark_%j.out
#SBATCH --error=benchmark_%j.err

# Usage:
#   sbatch tool/slurm_benchmark.sh              # full: 3 runs × 8 scales (~12h)
#   sbatch --time=00:30:00 tool/slurm_benchmark.sh --quick  # pipeline test
#
# Protocol:
#   - Baseline runs with STOCK PostgreSQL config (128MB shared_buffers)
#   - Optimized runs with TUNED config (25% RAM shared_buffers)
#   - PG restarted with the correct config before each method
#   - OS page cache dropped between every run

set -euo pipefail

REPO_DIR="${SLURM_SUBMIT_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
RESULTS_DIR="${REPO_DIR}/results/run_${SLURM_JOB_ID:-$(date +%s)}"
PG_PORT=15432
PG_USER="challenge"
PG_PASS="challenge"

if [ -d "/scratch/${USER}" ]; then
    LOCAL_DIR="/scratch/${USER}/pgdm_bench_${SLURM_JOB_ID:-$$}"
else
    LOCAL_DIR="/tmp/pgdm_bench_${SLURM_JOB_ID:-$$}"
fi
mkdir -p "${LOCAL_DIR}" "${RESULTS_DIR}"
PG_DATA="${LOCAL_DIR}/pgdata"
PG_LOG="${LOCAL_DIR}/pg.log"
VENV="${REPO_DIR}/.venv"

if [[ "${1:-}" == "--quick" ]]; then
    RUNS=1; SCALES=(10000)
else
    RUNS=3; SCALES=(10000 50000 100000 250000 500000 1000000 5000000 10000000)
fi

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
    echo "PG data: $(df -Th "${LOCAL_DIR}" | tail -1)"
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

# Compute tuned config values
TOTAL_RAM_KB=$(grep MemTotal /proc/meminfo | awk '{print $2}')
TUNED_SHARED_BUF_MB=$(( TOTAL_RAM_KB / 4 / 1024 ))
[ ${TUNED_SHARED_BUF_MB} -gt 65536 ] && TUNED_SHARED_BUF_MB=65536
[ ${TUNED_SHARED_BUF_MB} -lt 2048 ] && TUNED_SHARED_BUF_MB=2048
TUNED_EFFECTIVE_CACHE_MB=$(( TOTAL_RAM_KB * 3 / 4 / 1024 ))

write_pg_config() {
    local CONFIG_TYPE=$1
    cat > "${PG_DATA}/postgresql.conf" << PGBASE
port = ${PG_PORT}
listen_addresses = 'localhost'
jit = on
logging_collector = off
PGBASE
    if [ "${CONFIG_TYPE}" = "stock" ]; then
        cat >> "${PG_DATA}/postgresql.conf" << PGSTOCK
shared_buffers = '128MB'
work_mem = '4MB'
maintenance_work_mem = '64MB'
wal_buffers = '4MB'
max_wal_size = '1GB'
effective_cache_size = '4GB'
max_parallel_workers_per_gather = 2
PGSTOCK
    else
        cat >> "${PG_DATA}/postgresql.conf" << PGTUNED
shared_buffers = '${TUNED_SHARED_BUF_MB}MB'
work_mem = '256MB'
maintenance_work_mem = '1GB'
wal_buffers = '64MB'
max_wal_size = '8GB'
effective_cache_size = '${TUNED_EFFECTIVE_CACHE_MB}MB'
max_parallel_workers_per_gather = 4
max_parallel_workers = 8
max_worker_processes = 16
max_parallel_maintenance_workers = 4
checkpoint_completion_target = 0.9
random_page_cost = 1.1
effective_io_concurrency = 200
huge_pages = try
PGTUNED
    fi
}

# Initialize PG cluster
"${PG_BIN_DIR}/initdb" -D "${PG_DATA}" --auth=trust --username="${PG_USER}" -E UTF8 >/dev/null 2>&1
echo -e "local all all trust\nhost all all 127.0.0.1/32 trust" > "${PG_DATA}/pg_hba.conf"

start_pg() { "${PG_BIN_DIR}/pg_ctl" -D "${PG_DATA}" -l "${PG_LOG}" -o "-p ${PG_PORT}" start -w >/dev/null 2>&1; }
stop_pg()  { "${PG_BIN_DIR}/pg_ctl" -D "${PG_DATA}" stop -m fast -w >/dev/null 2>&1 || true; }
cold_restart_with_config() {
    local CONFIG=$1
    stop_pg
    sync
    sudo -n sh -c 'echo 3 > /proc/sys/vm/drop_caches' 2>/dev/null || true
    write_pg_config "${CONFIG}"
    start_pg
    sleep 1
}

# Python
log "PYTHON"
export PATH="${HOME}/.local/bin:${PATH}"
command -v uv &>/dev/null || curl -LsSf https://astral.sh/uv/install.sh | sh 2>/dev/null
[ ! -d "${VENV}" ] && (cd "${REPO_DIR}" && uv sync 2>&1 | tail -3)
PYTHON="${VENV}/bin/python"
log "$(${PYTHON} --version 2>&1)"

# Benchmark runner
cat > "${RESULTS_DIR}/run_single.py" << 'PYEOF'
import json, os, socket, sys, time, threading
from pathlib import Path

sys.path.insert(0, str(Path(os.environ["REPO_DIR"]) / "src"))
from pgdm.services.postgres_service import PostgresAdminService

def measured_total_seconds(report):
    return sum(max(float(i.get("seconds") or 0), 0)
               for i in (report.get("items") or []) if i.get("include_in_total", True))

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

Path(f"{OUT_DIR}/{RUN_ID}_report.txt").write_text(
    "\n".join(f"  {i['seconds']:8.3f}s | {str(i.get('rows','')):>10} | {i.get('name','')[:60]}"
              for i in timing.get("items",[]) if i.get("seconds",0)>0.01), encoding="utf-8")
Path(f"{OUT_DIR}/{RUN_ID}_timing.json").write_text(
    json.dumps(timing, indent=2, default=str), encoding="utf-8")

counts = {}
for t in TABLES:
    out = service.run_remote_command(
        f"psql -h localhost -p {PG_PORT} -U {PG_USER} -d {DATABASE} -qAt -c \"SELECT count(*) FROM {t};\"")
    counts[t] = int(out.strip())
correct = sum(counts.values()) == inserted if inserted > 0 else True

print(f"{METHOD},{rows},{os.environ.get('BENCH_RUN_NUM','0')},{measured:.3f},{wall:.3f},{inserted},{peak_rss[0]},{temp_storage_mb},{1 if correct else 0}")
service.close()
PYEOF

# Main loop
log "BENCHMARK START"
# Baseline = stock config, Optimized = tuned config
write_pg_config "stock"
start_pg
"${PG_BIN_DIR}/psql" -h localhost -p ${PG_PORT} -U ${PG_USER} -d postgres -qAt \
    -c "ALTER ROLE ${PG_USER} WITH SUPERUSER;" 2>/dev/null || true

echo "method,rows,run,measured_s,wall_s,inserted,peak_rss_mb,temp_storage_mb,correct" > "${RESULTS_DIR}/all_results.csv"

for ROWS in "${SCALES[@]}"; do
    log "━━━ ${ROWS} rows ━━━"
    export PGHOST=localhost PGPORT=${PG_PORT} PGUSER=${PG_USER} PGPASSWORD=${PG_PASS} PG_KAGGLE_CHALLENGE_PASS=${PG_PASS}
    ${PYTHON} "${REPO_DIR}/tool/generate_database.py" \
        --rows "${ROWS}" --replace \
        --host localhost --postgres_port "${PG_PORT}" \
        --user "${PG_USER}" --user_pass "${PG_PASS}" \
        --admin_database postgres 2>&1 | tail -3

    # Baseline: stock PG config + original code
    log "  baseline (stock config)"
    export REPO_DIR PG_PORT PG_USER PG_PASS PG_BIN_DIR BENCH_METHOD=baseline BENCH_OUT_DIR="${RESULTS_DIR}"

    cold_restart_with_config "stock"
    BENCH_RUN_ID="warmup_baseline_${ROWS}" BENCH_RUN_NUM=0 \
        ${PYTHON} "${RESULTS_DIR}/run_single.py" > "${RESULTS_DIR}/warmup_baseline_${ROWS}.out" 2>&1 || {
        log "    WARMUP FAILED"; cat "${RESULTS_DIR}/warmup_baseline_${ROWS}.out" | tail -3; continue; }

    for RUN in $(seq 1 ${RUNS}); do
        cold_restart_with_config "stock"
        RESULT=$(BENCH_RUN_ID="baseline_${ROWS}_run${RUN}" BENCH_RUN_NUM=${RUN} \
            ${PYTHON} "${RESULTS_DIR}/run_single.py" 2>"${RESULTS_DIR}/baseline_${ROWS}_run${RUN}.err") || {
            log "    run${RUN} FAILED"; continue; }
        echo "${RESULT}" >> "${RESULTS_DIR}/all_results.csv"
        log "    ${RESULT}"
    done

    # Optimized: tuned PG config + optimized code
    log "  optimized (tuned config: ${TUNED_SHARED_BUF_MB}MB shared_buffers)"
    export BENCH_METHOD=optimized

    cold_restart_with_config "tuned"
    BENCH_RUN_ID="warmup_optimized_${ROWS}" BENCH_RUN_NUM=0 \
        ${PYTHON} "${RESULTS_DIR}/run_single.py" > "${RESULTS_DIR}/warmup_optimized_${ROWS}.out" 2>&1 || {
        log "    WARMUP FAILED"; continue; }

    for RUN in $(seq 1 ${RUNS}); do
        cold_restart_with_config "tuned"
        RESULT=$(BENCH_RUN_ID="optimized_${ROWS}_run${RUN}" BENCH_RUN_NUM=${RUN} \
            ${PYTHON} "${RESULTS_DIR}/run_single.py" 2>"${RESULTS_DIR}/optimized_${ROWS}_run${RUN}.err") || {
            log "    run${RUN} FAILED"; continue; }
        echo "${RESULT}" >> "${RESULTS_DIR}/all_results.csv"
        log "    ${RESULT}"
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

print(f"{'Method':<11} {'Rows':>10} {'Median':>9} {'Min':>9} {'Max':>9} {'RSS':>6} {'Temp':>6}")
print("-" * 60)
summary = []
for (m, r), d in sorted(data.items(), key=lambda x: (x[0][1], x[0][0])):
    med = statistics.median(d["times"])
    summary.append({"method":m, "rows":r, "median":med, "min":min(d["times"]),
                     "max":max(d["times"]), "peak_rss_mb":max(d["rss"]),
                     "temp_storage_mb":max(d["temp"]), "runs":len(d["times"])})
    print(f"{m:<11} {r:>10,} {med:>8.1f}s {min(d['times']):>8.1f}s {max(d['times']):>8.1f}s {max(d['rss']):>5}M {max(d['temp']):>5}M")

bl = {s["rows"]: s for s in summary if s["method"]=="baseline"}
op = {s["rows"]: s for s in summary if s["method"]=="optimized"}
print(f"\n{'Rows':>10} {'Baseline':>12} {'Optimized':>12} {'Speedup':>8}")
print(f"{'':>10} {'(stock cfg)':>12} {'(tuned cfg)':>12}")
print("-" * 50)
for r in sorted(bl):
    if r in op:
        print(f"{r:>10,} {bl[r]['median']:>11.1f}s {op[r]['median']:>11.1f}s {bl[r]['median']/op[r]['median']:>7.2f}x")

with open(f"{rd}/summary.json", "w") as f: json.dump(summary, f, indent=2)
SUMEOF

stop_pg
rm -rf "${LOCAL_DIR}"
log "DONE. Results: ${RESULTS_DIR}/"
