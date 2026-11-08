#!/bin/bash
#SBATCH --job-name=pgdm-stock
#SBATCH --partition=lunaris
#SBATCH --nodes=1
#SBATCH --exclusive
#SBATCH --time=14:00:00
#SBATCH --output=benchmark_stock_%j.out
#SBATCH --error=benchmark_stock_%j.err

# Same benchmark as slurm_benchmark.sh but with STOCK PostgreSQL config
# (128MB shared_buffers) to match the judges' likely environment.

set -euo pipefail

REPO_DIR="${SLURM_SUBMIT_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
RESULTS_DIR="${REPO_DIR}/results/run_stock_${SLURM_JOB_ID:-$(date +%s)}"
PG_PORT=15432
PG_USER="challenge"
PG_PASS="challenge"

if [ -d "/scratch/${USER}" ]; then
    LOCAL_DIR="/scratch/${USER}/pgdm_stock_${SLURM_JOB_ID:-$$}"
else
    LOCAL_DIR="/tmp/pgdm_stock_${SLURM_JOB_ID:-$$}"
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
METHODS=(baseline optimized)

log() { echo "[$(date '+%H:%M:%S')] $*" | tee -a "${RESULTS_DIR}/benchmark.log"; }

log "ENVIRONMENT (STOCK CONFIG)"
{
    echo "Date: $(date -Iseconds)"
    echo "Host: $(hostname -f)"
    echo "Job: ${SLURM_JOB_ID:-local} / ${SLURM_NODELIST:-$(hostname)}"
    echo "CONFIG: STOCK (128MB shared_buffers)"
    uname -a
    lscpu | grep -E 'Model name|CPU\(s\)|Thread|Core|Socket|cache'
    free -h | head -2
    echo "PG data (local): $(df -Th "${LOCAL_DIR}" | tail -1)"
} > "${RESULTS_DIR}/environment.txt" 2>&1
cat "${RESULTS_DIR}/environment.txt"

log "POSTGRESQL"
PG_LOCAL="${HOME}/.local/pgsql"
PG_BIN_DIR="${PG_LOCAL}/bin"
[ ! -x "${PG_BIN_DIR}/initdb" ] && { log "ERROR: PostgreSQL not found at ${PG_BIN_DIR}. Run tuned benchmark first."; exit 1; }
export LD_LIBRARY_PATH="${PG_LOCAL}/lib:${LD_LIBRARY_PATH:-}"
export PATH="${PG_BIN_DIR}:${PATH}"
log "$("${PG_BIN_DIR}/postgres" --version)"

# STOCK CONFIG: minimal tuning, matches default Alpine/Debian install
"${PG_BIN_DIR}/initdb" -D "${PG_DATA}" --auth=trust --username="${PG_USER}" -E UTF8 >/dev/null 2>&1
cat >> "${PG_DATA}/postgresql.conf" << PGCONF
port = ${PG_PORT}
listen_addresses = 'localhost'
shared_buffers = '128MB'
work_mem = '4MB'
maintenance_work_mem = '64MB'
wal_buffers = '4MB'
max_wal_size = '1GB'
effective_cache_size = '4GB'
max_parallel_workers_per_gather = 2
jit = on
logging_collector = off
PGCONF
echo -e "local all all trust\nhost all all 127.0.0.1/32 trust" > "${PG_DATA}/pg_hba.conf"
log "shared_buffers=128MB (STOCK)"

start_pg() { "${PG_BIN_DIR}/pg_ctl" -D "${PG_DATA}" -l "${PG_LOG}" -o "-p ${PG_PORT}" start -w >/dev/null 2>&1; }
stop_pg()  { "${PG_BIN_DIR}/pg_ctl" -D "${PG_DATA}" stop -m fast -w >/dev/null 2>&1 || true; }
cold_restart() { stop_pg; sync; sudo -n sh -c 'echo 3 > /proc/sys/vm/drop_caches' 2>/dev/null || true; start_pg; sleep 1; }

log "PYTHON"
export PATH="${HOME}/.local/bin:${PATH}"
[ ! -d "${VENV}" ] && (cd "${REPO_DIR}" && uv sync 2>&1 | tail -3)
PYTHON="${VENV}/bin/python"

# Copy the runner script from the tuned run (or generate fresh)
TUNED_RUN=$(ls -d "${REPO_DIR}/results/run_835643" "${REPO_DIR}/results/run_${SLURM_JOB_ID}" 2>/dev/null | head -1)
if [ -f "${TUNED_RUN}/run_single.py" ]; then
    cp "${TUNED_RUN}/run_single.py" "${RESULTS_DIR}/run_single.py"
else
    # Inline the runner (same as tuned benchmark)
    cp "${REPO_DIR}/results/run_835643/run_single.py" "${RESULTS_DIR}/run_single.py" 2>/dev/null || {
        log "ERROR: No run_single.py found. Run tuned benchmark first."; exit 1; }
fi

log "BENCHMARK START (STOCK CONFIG)"
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

    if (( ROWS % 2 == 0 )); then RUN_ORDER=(baseline optimized); else RUN_ORDER=(optimized baseline); fi

    for METHOD in "${RUN_ORDER[@]}"; do
        log "  ${METHOD}"
        export REPO_DIR PG_PORT PG_USER PG_PASS PG_BIN_DIR BENCH_METHOD=${METHOD} BENCH_OUT_DIR="${RESULTS_DIR}"

        cold_restart
        if ! BENCH_RUN_ID="warmup_${METHOD}_${ROWS}" BENCH_RUN_NUM=0 \
            ${PYTHON} "${RESULTS_DIR}/run_single.py" > "${RESULTS_DIR}/warmup_${METHOD}_${ROWS}.out" 2>&1; then
            log "    WARMUP FAILED"; continue
        fi

        for RUN in $(seq 1 ${RUNS}); do
            cold_restart
            RESULT=$(BENCH_RUN_ID="${METHOD}_${ROWS}_run${RUN}" BENCH_RUN_NUM=${RUN} \
                ${PYTHON} "${RESULTS_DIR}/run_single.py" 2>"${RESULTS_DIR}/${METHOD}_${ROWS}_run${RUN}.err") || {
                log "    run${RUN} FAILED"; continue; }
            echo "${RESULT}" >> "${RESULTS_DIR}/all_results.csv"
            log "    ${RESULT}"
        done
    done
done

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

print(f"{'Method':<11} {'Rows':>10} {'Median':>9} {'Min':>9} {'Max':>9}")
print("-" * 50)
summary = []
for (m, r), d in sorted(data.items(), key=lambda x: (x[0][1], x[0][0])):
    med = statistics.median(d["times"])
    summary.append({"method":m, "rows":r, "median":med, "min":min(d["times"]), "max":max(d["times"]),
                     "peak_rss_mb":max(d["rss"]), "temp_storage_mb":max(d["temp"]), "config":"stock"})
    print(f"{m:<11} {r:>10,} {med:>8.1f}s {min(d['times']):>8.1f}s {max(d['times']):>8.1f}s")
bl = {s["rows"]: s["median"] for s in summary if s["method"]=="baseline"}
op = {s["rows"]: s["median"] for s in summary if s["method"]=="optimized"}
print(f"\n{'Rows':>10} {'Baseline':>10} {'Optimized':>10} {'Speedup':>8}")
print("-" * 45)
for r in sorted(bl):
    if r in op: print(f"{r:>10,} {bl[r]:>9.1f}s {op[r]:>9.1f}s {bl[r]/op[r]:>7.2f}x")
with open(f"{rd}/summary.json", "w") as f: json.dump(summary, f, indent=2)
SUMEOF

stop_pg
rm -rf "${LOCAL_DIR}"
log "DONE. Results: ${RESULTS_DIR}/"
