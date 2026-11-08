#!/bin/bash
#SBATCH --job-name=pgdm-bench
#SBATCH --partition=lunaris
#SBATCH --nodes=1
#SBATCH --exclusive
#SBATCH --time=08:00:00
#SBATCH --output=benchmark_%j.out
#SBATCH --error=benchmark_%j.err

# Usage (from login node, no local computation):
#   sbatch tool/slurm_benchmark.sh              # full: 3 runs × 6 scales (~6h)
#   sbatch --time=00:30:00 tool/slurm_benchmark.sh --quick  # pipeline test (~5min)

set -euo pipefail

REPO_DIR="${SLURM_SUBMIT_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
RESULTS_DIR="${REPO_DIR}/results/run_${SLURM_JOB_ID:-$(date +%s)}"
PG_PORT=15432
PG_USER="challenge"
PG_PASS="challenge"

# Use local disk for PG data (NFS is too slow for database I/O)
# Prefer /scratch (persists across jobs), fall back to /tmp
if [ -d "/scratch/${USER}" ]; then
    LOCAL_DIR="/scratch/${USER}/pgdm_bench_${SLURM_JOB_ID:-$$}"
else
    LOCAL_DIR="/tmp/pgdm_bench_${SLURM_JOB_ID:-$$}"
fi
mkdir -p "${LOCAL_DIR}"
PG_DATA="${LOCAL_DIR}/pgdata"
PG_LOG="${LOCAL_DIR}/pg.log"
VENV="${REPO_DIR}/.venv"

if [[ "${1:-}" == "--quick" ]]; then
    RUNS=1; SCALES=(10000); METHODS=(baseline optimized)
    log_prefix="[QUICK] "
else
    RUNS=3; SCALES=(10000 50000 100000 250000 500000 1000000)
    METHODS=(baseline optimized); log_prefix=""
fi

mkdir -p "${RESULTS_DIR}"
log() { echo "${log_prefix}[$(date '+%H:%M:%S')] $*" | tee -a "${RESULTS_DIR}/benchmark.log"; }

# === Environment ===
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

# === PostgreSQL ===
log "POSTGRESQL SETUP"
PG_LOCAL="${HOME}/.local/pgsql"
PG_BIN_DIR=""
for c in "${PG_LOCAL}/bin" \
         "$(command -v initdb 2>/dev/null | xargs dirname 2>/dev/null)" \
         "/usr/pgsql-17/bin" "/usr/lib/postgresql/17/bin" "/usr/local/pgsql/bin"; do
    [ -n "${c}" ] && [ -x "${c}/initdb" ] && PG_BIN_DIR="${c}" && break
done
[ -z "${PG_BIN_DIR}" ] && command -v conda &>/dev/null && {
    conda install -y -c conda-forge postgresql 2>&1 | tail -3; PG_BIN_DIR="$(dirname "$(command -v initdb)")"; }
[ -z "${PG_BIN_DIR}" ] && command -v module &>/dev/null && {
    module load postgresql 2>/dev/null || true; PG_BIN_DIR="$(dirname "$(command -v initdb 2>/dev/null)")" || true; }
[ -z "${PG_BIN_DIR}" ] && {
    log "PostgreSQL not found. Installing locally to ${PG_LOCAL}..."
    PG_SRC_VER="17.2"
    PG_TAR="postgresql-${PG_SRC_VER}-linux-x86_64-binaries.tar.gz"
    PG_URL="https://get.enterprisedb.com/postgresql/${PG_TAR}"
    TMPDIR_PG=$(mktemp -d)
    if curl -fsSL -o "${TMPDIR_PG}/${PG_TAR}" "${PG_URL}" 2>/dev/null; then
        mkdir -p "${PG_LOCAL}"
        tar xzf "${TMPDIR_PG}/${PG_TAR}" -C "${PG_LOCAL}" --strip-components=1
        PG_BIN_DIR="${PG_LOCAL}/bin"
        log "Installed PostgreSQL ${PG_SRC_VER} to ${PG_LOCAL}"
    else
        log "Binary download failed. Building from source..."
        PG_SRC_URL="https://ftp.postgresql.org/pub/source/v${PG_SRC_VER}/postgresql-${PG_SRC_VER}.tar.bz2"
        curl -fsSL -o "${TMPDIR_PG}/pg.tar.bz2" "${PG_SRC_URL}"
        tar xjf "${TMPDIR_PG}/pg.tar.bz2" -C "${TMPDIR_PG}"
        cd "${TMPDIR_PG}/postgresql-${PG_SRC_VER}"
        ./configure --prefix="${PG_LOCAL}" --without-readline --without-zlib 2>&1 | tail -3
        make -j$(nproc) 2>&1 | tail -3
        make install 2>&1 | tail -3
        cd "${REPO_DIR}"
        PG_BIN_DIR="${PG_LOCAL}/bin"
        log "Built PostgreSQL ${PG_SRC_VER} from source"
    fi
    rm -rf "${TMPDIR_PG}"
}
export LD_LIBRARY_PATH="${PG_LOCAL}/lib:${LD_LIBRARY_PATH:-}"
export PATH="${PG_BIN_DIR:-${PG_LOCAL}/bin}:${PATH}"
[ -z "${PG_BIN_DIR}" ] && { log "ERROR: PostgreSQL installation failed"; exit 1; }
log "$("${PG_BIN_DIR}/postgres" --version)"

TOTAL_RAM_KB=$(grep MemTotal /proc/meminfo | awk '{print $2}')
SHARED_BUF_MB=$(( TOTAL_RAM_KB / 4 / 1024 ))
[ ${SHARED_BUF_MB} -gt 65536 ] && SHARED_BUF_MB=65536
[ ${SHARED_BUF_MB} -lt 2048 ] && SHARED_BUF_MB=2048
EFFECTIVE_CACHE_MB=$(( TOTAL_RAM_KB * 3 / 4 / 1024 ))
log "shared_buffers=${SHARED_BUF_MB}MB effective_cache=${EFFECTIVE_CACHE_MB}MB"

"${PG_BIN_DIR}/initdb" -D "${PG_DATA}" --auth=trust --username="${PG_USER}" -E UTF8 >/dev/null 2>&1
cat >> "${PG_DATA}/postgresql.conf" << PGCONF
port = ${PG_PORT}
listen_addresses = 'localhost'
shared_buffers = '${SHARED_BUF_MB}MB'
work_mem = '256MB'
maintenance_work_mem = '1GB'
wal_buffers = '64MB'
max_wal_size = '8GB'
effective_cache_size = '${EFFECTIVE_CACHE_MB}MB'
max_parallel_workers_per_gather = 4
max_parallel_workers = 8
max_worker_processes = 16
max_parallel_maintenance_workers = 4
checkpoint_completion_target = 0.9
random_page_cost = 1.1
effective_io_concurrency = 200
jit = on
huge_pages = try
logging_collector = off
PGCONF
echo -e "local all all trust\nhost all all 127.0.0.1/32 trust" > "${PG_DATA}/pg_hba.conf"
echo "shared_buffers=${SHARED_BUF_MB}MB effective_cache=${EFFECTIVE_CACHE_MB}MB" >> "${RESULTS_DIR}/environment.txt"

start_pg() { "${PG_BIN_DIR}/pg_ctl" -D "${PG_DATA}" -l "${PG_LOG}" -o "-p ${PG_PORT}" start -w >/dev/null 2>&1; }
stop_pg()  { "${PG_BIN_DIR}/pg_ctl" -D "${PG_DATA}" stop -m fast -w >/dev/null 2>&1 || true; }
cold_restart() { stop_pg; sync; sudo -n sh -c 'echo 3 > /proc/sys/vm/drop_caches' 2>/dev/null || true; start_pg; sleep 1; }

# === Python ===
log "PYTHON SETUP"
if ! command -v uv &>/dev/null; then
    log "Installing uv..."
    curl -LsSf https://astral.sh/uv/install.sh | sh 2>/dev/null
    export PATH="${HOME}/.local/bin:${PATH}"
fi
if [ ! -d "${VENV}" ]; then
    if command -v uv &>/dev/null && [ -f "${REPO_DIR}/pyproject.toml" ]; then
        (cd "${REPO_DIR}" && uv sync 2>&1 | tail -3)
    else
        python3 -m venv "${VENV}"
        "${VENV}/bin/pip" install -q paramiko customtkinter openpyxl pandas reportlab xlrd python-dotenv 2>/dev/null || true
    fi
fi
PYTHON="${VENV}/bin/python"
log "$(${PYTHON} --version 2>&1)"

# === Benchmark runner (measures time + RAM + disk) ===
cat > "${RESULTS_DIR}/run_single.py" << 'PYEOF'
import json, os, socket, sys, time, threading, resource
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

# Connect via SSH to localhost
import paramiko

# Wrap run_remote_command to inject PATH for psql
PG_BIN = os.environ.get("PG_BIN_DIR", os.path.expanduser("~/.local/pgsql/bin"))

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
    patched = f"export PATH={PG_BIN}:$PATH; {command}"
    return _orig_run(patched, **kw)
service.run_remote_command = _patched_run

# Clean
service.run_remote_command(
    f"psql -h localhost -p {PG_PORT} -U {PG_USER} -d {DATABASE} "
    f"-X -q -v ON_ERROR_STOP=1 -c \"TRUNCATE {','.join(TABLES)} CASCADE;\"")
try:
    service.run_remote_command(
        f"psql -h localhost -p {PG_PORT} -U {PG_USER} -d postgres_data_manager "
        f"-X -q -c \"DELETE FROM app_control.table_version_dependencies; "
        f"DELETE FROM app_control.table_versions WHERE operation_kind = 'cross_table_expand_v1';\"")
except Exception: pass

# Measure PostgreSQL RSS before
def pg_rss_mb():
    try:
        pids = [l.split()[0] for l in os.popen(f"pgrep -f 'postgres.*-p {PG_PORT}'").readlines()]
        return sum(int(open(f"/proc/{p}/status").read().split("VmRSS:")[1].split()[0])
                   for p in pids if os.path.exists(f"/proc/{p}/status")) // 1024
    except Exception: return 0

# Measure DB size before
def db_size():
    try:
        out = service.run_remote_command(
            f"psql -h localhost -p {PG_PORT} -U {PG_USER} -d {DATABASE} -qAt "
            f"-c \"SELECT pg_database_size('{DATABASE}');\"")
        return int(out.strip()) // (1024*1024)
    except Exception: return 0

rss_before = pg_rss_mb()
db_before = db_size()

# Sample peak RSS during expansion
peak_rss = [rss_before]
stop_sampling = threading.Event()
def sample_rss():
    while not stop_sampling.is_set():
        r = pg_rss_mb()
        if r > peak_rss[0]: peak_rss[0] = r
        stop_sampling.wait(0.5)
sampler = threading.Thread(target=sample_rss, daemon=True)
sampler.start()

# Run expansion
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

stop_sampling.set()
sampler.join(timeout=2)

# Collect metrics
measured = measured_total_seconds(timing)
inserted = timing.get("total_rows_inserted", 0)
rows = timing.get("source_rows", 0)
db_after = db_size()
temp_storage_mb = max(0, db_after - db_before)

# Save reports
Path(f"{OUT_DIR}/{RUN_ID}_report.txt").write_text(build_report_lines(timing), encoding="utf-8")
Path(f"{OUT_DIR}/{RUN_ID}_timing.json").write_text(
    json.dumps(timing, indent=2, default=str), encoding="utf-8")

# Verify row counts
counts = {}
for t in TABLES:
    out = service.run_remote_command(
        f"psql -h localhost -p {PG_PORT} -U {PG_USER} -d {DATABASE} -qAt -c \"SELECT count(*) FROM {t};\"")
    counts[t] = int(out.strip())
total_verified = sum(counts.values())
correct = total_verified == inserted if inserted > 0 else True

print(f"{METHOD},{rows},{os.environ.get('BENCH_RUN_NUM','0')},{measured:.3f},{wall:.3f},{inserted},{peak_rss[0]},{temp_storage_mb},{1 if correct else 0}")
if not correct:
    sys.stderr.write(f"CORRECTNESS FAIL: inserted={inserted} verified={total_verified} counts={counts}\n")
service.close()
PYEOF

# === Main loop ===
log "BENCHMARK START (${#SCALES[@]} scales × ${#METHODS[@]} methods × ${RUNS} runs)"
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

    # Alternate method order per scale to avoid ordering bias
    if (( ROWS % 2 == 0 )); then
        RUN_ORDER=(baseline optimized)
    else
        RUN_ORDER=(optimized baseline)
    fi

    for METHOD in "${RUN_ORDER[@]}"; do
        log "  ${METHOD}"
        export REPO_DIR PG_PORT PG_USER PG_PASS PG_BIN_DIR BENCH_METHOD=${METHOD} BENCH_OUT_DIR="${RESULTS_DIR}"

        # Warmup (fail = abort this method, not silently skip)
        cold_restart
        if ! BENCH_RUN_ID="warmup_${METHOD}_${ROWS}" BENCH_RUN_NUM=0 \
            ${PYTHON} "${RESULTS_DIR}/run_single.py" > "${RESULTS_DIR}/warmup_${METHOD}_${ROWS}.out" 2>&1; then
            log "    WARMUP FAILED — skipping ${METHOD} @ ${ROWS}"
            cat "${RESULTS_DIR}/warmup_${METHOD}_${ROWS}.out" | tail -5 >> "${RESULTS_DIR}/benchmark.log"
            continue
        fi

        for RUN in $(seq 1 ${RUNS}); do
            cold_restart
            RESULT=$(BENCH_RUN_ID="${METHOD}_${ROWS}_run${RUN}" BENCH_RUN_NUM=${RUN} \
                ${PYTHON} "${RESULTS_DIR}/run_single.py" 2>"${RESULTS_DIR}/${METHOD}_${ROWS}_run${RUN}.err") || {
                log "    run${RUN} FAILED"; cat "${RESULTS_DIR}/${METHOD}_${ROWS}_run${RUN}.err" | tail -3 >> "${RESULTS_DIR}/benchmark.log"; continue; }
            echo "${RESULT}" >> "${RESULTS_DIR}/all_results.csv"
            log "    ${RESULT}"
        done
    done
done

# === Summary ===
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

print(f"{'Method':<11} {'Rows':>8} {'Median':>8} {'Min':>8} {'Max':>8} {'RSS':>6} {'Temp':>6}")
print("-" * 60)
summary = []
for (m, r), d in sorted(data.items(), key=lambda x: (x[0][1], x[0][0])):
    med = statistics.median(d["times"])
    rss = max(d["rss"])
    tmp = max(d["temp"])
    print(f"{m:<11} {r:>8,} {med:>7.1f}s {min(d['times']):>7.1f}s {max(d['times']):>7.1f}s {rss:>5}M {tmp:>5}M")
    summary.append({"method":m, "rows":r, "median":med, "min":min(d["times"]),
                     "max":max(d["times"]), "peak_rss_mb":rss, "temp_storage_mb":tmp})

bl = {s["rows"]: s for s in summary if s["method"]=="baseline"}
op = {s["rows"]: s for s in summary if s["method"]=="optimized"}
print(f"\n{'Rows':>8} {'Baseline':>9} {'Optimized':>9} {'Speedup':>8} {'RSS_B':>6} {'RSS_O':>6} {'Temp_O':>6}")
print("-" * 58)
for r in sorted(bl):
    if r in op:
        print(f"{r:>8,} {bl[r]['median']:>8.1f}s {op[r]['median']:>8.1f}s {bl[r]['median']/op[r]['median']:>7.2f}x "
              f"{bl[r]['peak_rss_mb']:>5}M {op[r]['peak_rss_mb']:>5}M {op[r]['temp_storage_mb']:>5}M")

with open(f"{rd}/summary.json", "w") as f:
    json.dump(summary, f, indent=2)
SUMEOF

stop_pg
rm -rf "${LOCAL_DIR}"
log "DONE. Results: ${RESULTS_DIR}/"
