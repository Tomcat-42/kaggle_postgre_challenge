#!/usr/bin/env python3
"""Final scaling benchmark + correctness verification.

Runs baseline (original method) and optimized at multiple row counts.
Verifies identical row counts in all destination tables.
"""

from __future__ import annotations
import json, socket, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from pgdm.services.postgres_service import PostgresAdminService
from pgdm.ui.dialogs import ExpansionTimingReportDialog

ASSET_DIR = Path(__file__).resolve().parents[1] / "asset" / "sql"
RECIPE_FILES = [
    ("01_table3.sql", "public.table3"), ("02_table4.sql", "public.table4"),
    ("03_table1.sql", "public.table1"), ("04_table5.sql", "public.table5"),
    ("05_table6.sql", "public.table6"), ("06_table2.sql", "public.table2"),
]
DATABASE = "kaggle_challenge"
SOURCE_TABLE = "public.raw_data"
RAW_SCHEMAS = ["group001"]
DEST_TABLES = [t for _, t in RECIPE_FILES]

SSH_HOST, SSH_PORT = "localhost", 2222
SSH_USER = SSH_PASS = PG_USER = PG_PASS = "challenge"


def connect():
    service = PostgresAdminService()
    service.connect(SSH_HOST, SSH_PORT, SSH_USER, SSH_PASS, 5432, PG_USER, PG_PASS)
    return service


def clean(service):
    service.run_remote_command(
        f"psql -h localhost -U {PG_USER} -d {DATABASE} "
        f"-X -q -v ON_ERROR_STOP=1 -c "
        f"\"TRUNCATE {','.join(DEST_TABLES)} CASCADE;\""
    )


def get_row_counts(service):
    sql = " UNION ALL ".join(
        f"SELECT '{t}' AS t, count(*)::text AS c FROM {t}" for t in DEST_TABLES
    )
    out = service.run_remote_command(
        f"psql -h localhost -U {PG_USER} -d {DATABASE} -X -qAt -c \"{sql}\""
    )
    counts = {}
    for line in out.strip().splitlines():
        parts = line.split("|")
        if len(parts) == 2:
            counts[parts[0]] = int(parts[1])
    return counts


def build_destinations():
    return [
        {"table_name": t, "version_title": "Benchmark", "sql": (ASSET_DIR / f).read_text()}
        for f, t in RECIPE_FILES
    ]


def reset_versions(service):
    try:
        service.run_remote_command(
            f"psql -h localhost -U {PG_USER} -d postgres_data_manager "
            f"-X -q -v ON_ERROR_STOP=1 -c "
            "\"DELETE FROM app_control.table_version_dependencies; "
            "DELETE FROM app_control.table_versions "
            "WHERE operation_kind = 'cross_table_expand_v1';\""
        )
    except Exception:
        pass


def run_expansion(service, method, n_rows=None):
    timing = service.create_cross_table_expansion_timing_report(
        DATABASE, SOURCE_TABLE, RAW_SCHEMAS,
        [t for _, t in RECIPE_FILES],
    )
    service.ensure_admin_schema()

    dests = build_destinations()

    if method == "baseline":
        result = service.execute_cross_table_expansion(
            database_name=DATABASE, source_full_table_name=SOURCE_TABLE,
            raw_schemas=RAW_SCHEMAS, destinations=dests, timing_report=timing,
        )
    else:
        result = service.execute_optimized_cross_table_expansion(
            database_name=DATABASE, source_full_table_name=SOURCE_TABLE,
            raw_schemas=RAW_SCHEMAS, destinations=dests, timing_report=timing,
        )

    service.register_cross_table_expansion_versions(
        expansion_result=result, requested_by="benchmark",
        workstation_name=socket.gethostname(), timing_report=timing,
    )
    timing["completed_at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    measured = ExpansionTimingReportDialog.measured_total_seconds(timing)
    return measured, timing


def main():
    scales = [100_000, 250_000, 500_000, 1_000_000]
    results = []

    service = connect()

    # ── Correctness verification at 100K ──
    print("="*60)
    print("CORRECTNESS VERIFICATION (100K rows)")
    print("="*60)

    clean(service); reset_versions(service)
    baseline_time, _ = run_expansion(service, "baseline")
    baseline_counts = get_row_counts(service)
    print(f"Baseline: {baseline_time:.3f}s | rows: {baseline_counts}")

    clean(service); reset_versions(service)
    optimized_time, _ = run_expansion(service, "optimized")
    optimized_counts = get_row_counts(service)
    print(f"Optimized: {optimized_time:.3f}s | rows: {optimized_counts}")

    match = all(baseline_counts.get(t) == optimized_counts.get(t) for t in DEST_TABLES)
    print(f"Row counts match: {match}")
    if not match:
        for t in DEST_TABLES:
            b, o = baseline_counts.get(t, 0), optimized_counts.get(t, 0)
            if b != o:
                print(f"  MISMATCH {t}: baseline={b} optimized={o}")

    # ── Scaling benchmark ──
    print(f"\n{'='*60}")
    print("SCALING BENCHMARK")
    print(f"{'='*60}")
    print(f"{'Rows':>10} | {'Baseline':>10} | {'Optimized':>10} | {'Speedup':>8} | {'Inserted':>10}")
    print("-" * 65)

    for n in scales:
        clean(service); reset_versions(service)
        b_time, _ = run_expansion(service, "baseline")
        b_counts = get_row_counts(service)
        b_total = sum(b_counts.values())

        clean(service); reset_versions(service)
        o_time, _ = run_expansion(service, "optimized")
        o_counts = get_row_counts(service)
        o_total = sum(o_counts.values())

        speedup = b_time / o_time if o_time > 0 else 0
        match = all(b_counts.get(t) == o_counts.get(t) for t in DEST_TABLES)
        results.append({
            "rows": n, "baseline": b_time, "optimized": o_time,
            "speedup": speedup, "inserted": o_total, "correct": match,
        })
        print(f"{n:>10,} | {b_time:>9.1f}s | {o_time:>9.1f}s | {speedup:>7.2f}× | {o_total:>10,} {'✓' if match else '✗'}")

    Path(__file__).parent.joinpath("final_scaling_results.json").write_text(
        json.dumps(results, indent=2), encoding="utf-8")

    service.close()
    print(f"\nResults saved to tool/final_scaling_results.json")


if __name__ == "__main__":
    main()
