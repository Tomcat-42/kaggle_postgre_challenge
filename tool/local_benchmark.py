#!/usr/bin/env python3
"""Definitive local benchmark with cold-cache protocol.

Baseline: original code + stock PG config (128MB shared_buffers)
Optimized: optimized code + tuned PG config (2GB shared_buffers)
Cold cache: restart container + drop host page cache between runs.
"""

import json, os, socket, subprocess, sys, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from pgdm.services.postgres_service import PostgresAdminService

ASSET_DIR = Path(__file__).resolve().parents[1] / "asset" / "sql"
RESULTS_DIR = Path(__file__).resolve().parents[1] / "results" / "local"
RECIPES = [
    ("01_table3.sql", "public.table3"), ("02_table4.sql", "public.table4"),
    ("03_table1.sql", "public.table1"), ("04_table5.sql", "public.table5"),
    ("05_table6.sql", "public.table6"), ("06_table2.sql", "public.table2"),
]
TABLES = [t for _, t in RECIPES]
DB = "kaggle_challenge"

CONTAINER = "container_db_1"
SSH_HOST, SSH_PORT = "localhost", 2222
SSH_USER = SSH_PASS = PG_USER = PG_PASS = "challenge"
PG_PORT = 5432

STOCK_CONF = """shared_buffers = '128MB'
work_mem = '4MB'
maintenance_work_mem = '64MB'
wal_buffers = '4MB'
max_wal_size = '1GB'
effective_cache_size = '4GB'
"""

TUNED_CONF = """shared_buffers = '2GB'
work_mem = '256MB'
maintenance_work_mem = '256MB'
wal_buffers = '64MB'
max_wal_size = '4GB'
effective_cache_size = '4GB'
max_parallel_workers_per_gather = 4
"""

RUNS = 3
SCALES = [100_000, 1_000_000]


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def set_pg_config(conf_text):
    subprocess.run(
        ["podman", "exec", CONTAINER, "sh", "-c",
         f"echo '{conf_text}' > /var/lib/postgresql/data/postgresql.auto.conf"],
        check=True, capture_output=True)


def cold_restart():
    subprocess.run(["podman", "restart", CONTAINER], check=True, capture_output=True)
    subprocess.run(["sync"], check=True)
    try:
        subprocess.run(["sudo", "-n", "sh", "-c", "echo 3 > /proc/sys/vm/drop_caches"],
                       check=True, capture_output=True)
    except Exception:
        pass
    time.sleep(5)


def connect():
    svc = PostgresAdminService()
    svc.connect(SSH_HOST, SSH_PORT, SSH_USER, SSH_PASS, PG_PORT, PG_USER, PG_PASS)
    return svc


def clean(svc):
    svc.run_remote_command(
        f"psql -h localhost -U {PG_USER} -d {DB} "
        f"-X -q -v ON_ERROR_STOP=1 -c \"TRUNCATE {','.join(TABLES)} CASCADE;\"")
    try:
        svc.run_remote_command(
            f"psql -h localhost -U {PG_USER} -d postgres_data_manager "
            f"-X -q -c \"DELETE FROM app_control.table_version_dependencies; "
            f"DELETE FROM app_control.table_versions "
            f"WHERE operation_kind = 'cross_table_expand_v1';\"")
    except Exception:
        pass


def verify_fks(svc):
    out = svc.run_remote_command(
        f"psql -h localhost -U {PG_USER} -d {DB} -qAt "
        f"-c \"SELECT count(*) FROM pg_constraint WHERE contype='f' "
        f"AND conrelid::regclass::text IN ('table1','table2','table5','table6');\"")
    n = int(out.strip())
    if n < 6:
        raise RuntimeError(f"FK check failed: {n} constraints (need 6)")
    return n


def run_expansion(svc, method, timing):
    dests = [{"table_name": t, "version_title": "Benchmark",
              "sql": (ASSET_DIR / f).read_text()} for f, t in RECIPES]

    if method == "baseline":
        return svc.execute_cross_table_expansion(
            database_name=DB, source_full_table_name="public.raw_data",
            raw_schemas=["group001"], destinations=dests, timing_report=timing)
    else:
        return svc.execute_optimized_cross_table_expansion(
            database_name=DB, source_full_table_name="public.raw_data",
            raw_schemas=["group001"], destinations=dests, timing_report=timing)


def measured_total(timing):
    return sum(max(float(i.get("seconds") or 0), 0)
               for i in (timing.get("items") or []) if i.get("include_in_total", True))


def main():
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    results = []

    log(f"Definitive benchmark: {len(SCALES)} scales × 2 methods × {RUNS} runs")

    for rows in SCALES:
        log(f"━━━ {rows:,} rows ━━━")

        # Generate dataset (with stock config so FKs are created)
        set_pg_config(STOCK_CONF)
        cold_restart()

        svc = connect()
        log(f"  Generating dataset...")
        svc.run_remote_command(
            f"psql -h localhost -U {PG_USER} -d postgres -qAt "
            f"-c \"ALTER ROLE {PG_USER} WITH SUPERUSER;\"")
        svc.close()

        os.environ["PG_KAGGLE_CHALLENGE_PASS"] = PG_PASS
        subprocess.run(
            [sys.executable, str(Path(__file__).parent / "generate_database.py"),
             "--rows", str(rows), "--replace",
             "--host", "localhost", "--postgres_port", str(PG_PORT),
             "--user", PG_USER, "--admin_database", "postgres"],
            check=True, capture_output=True)
        log(f"  Dataset ready")

        for method in ["baseline", "optimized"]:
            conf = STOCK_CONF if method == "baseline" else TUNED_CONF
            conf_name = "stock 128MB" if method == "baseline" else "tuned 2GB"
            log(f"  {method} ({conf_name})")

            # Set config and regenerate DB to guarantee FKs
            set_pg_config(conf)
            cold_restart()

            svc = connect()
            svc.run_remote_command(
                f"psql -h localhost -U {PG_USER} -d postgres -qAt "
                f"-c \"ALTER ROLE {PG_USER} WITH SUPERUSER;\"")

            # Regenerate to guarantee FKs
            svc.close()
            subprocess.run(
                [sys.executable, str(Path(__file__).parent / "generate_database.py"),
                 "--rows", str(rows), "--replace",
                 "--host", "localhost", "--postgres_port", str(PG_PORT),
                 "--user", PG_USER, "--admin_database", "postgres"],
                check=True, capture_output=True)

            # Warmup (cold restart + run + discard)
            cold_restart()
            svc = connect()
            clean(svc)
            fks = verify_fks(svc)
            timing = svc.create_cross_table_expansion_timing_report(
                DB, "public.raw_data", ["group001"], [t for _, t in RECIPES])
            svc.ensure_admin_schema()
            try:
                run_expansion(svc, method, timing)
            except Exception as e:
                log(f"    warmup failed: {e}")
            svc.close()

            # Measured runs
            for run in range(1, RUNS + 1):
                cold_restart()
                svc = connect()
                clean(svc)
                fks = verify_fks(svc)

                timing = svc.create_cross_table_expansion_timing_report(
                    DB, "public.raw_data", ["group001"], [t for _, t in RECIPES])
                svc.ensure_admin_schema()

                wall_start = time.perf_counter()
                result = run_expansion(svc, method, timing)
                svc.register_cross_table_expansion_versions(
                    expansion_result=result, requested_by="local_benchmark",
                    workstation_name=socket.gethostname(), timing_report=timing)
                wall = time.perf_counter() - wall_start

                m = measured_total(timing)
                inserted = timing.get("total_rows_inserted", 0)
                r = {"method": method, "rows": rows, "run": run,
                     "measured_s": round(m, 3), "wall_s": round(wall, 3),
                     "inserted": inserted, "config": conf_name, "fks": fks}
                results.append(r)
                log(f"    run {run}: {m:.1f}s (wall {wall:.1f}s) inserted={inserted:,} fks={fks}")
                svc.close()

    # Summary
    log("SUMMARY")
    from collections import defaultdict
    import statistics
    data = defaultdict(list)
    for r in results:
        data[(r["method"], r["rows"])].append(r["measured_s"])

    print(f"\n{'Method':<11} {'Rows':>10} {'Median':>9} {'Min':>9} {'Max':>9}")
    print("-" * 50)
    for (m, r), times in sorted(data.items(), key=lambda x: (x[0][1], x[0][0])):
        med = statistics.median(times)
        print(f"{m:<11} {r:>10,} {med:>8.1f}s {min(times):>8.1f}s {max(times):>8.1f}s")

    bl = {r: statistics.median(t) for (m, r), t in data.items() if m == "baseline"}
    op = {r: statistics.median(t) for (m, r), t in data.items() if m == "optimized"}
    print(f"\n{'Rows':>10} {'Baseline':>12} {'Optimized':>12} {'Speedup':>8}")
    print(f"{'':>10} {'(stock)':>12} {'(tuned)':>12}")
    print("-" * 50)
    for r in sorted(bl):
        if r in op:
            print(f"{r:>10,} {bl[r]:>11.1f}s {op[r]:>11.1f}s {bl[r]/op[r]:>7.2f}x")

    out_path = RESULTS_DIR / "definitive_benchmark.json"
    out_path.write_text(json.dumps(results, indent=2))
    log(f"Results saved to {out_path}")


if __name__ == "__main__":
    main()
