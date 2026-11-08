#!/usr/bin/env python3
"""Run the expansion pipeline headlessly and print the full timing report.

Usage:
    .venv/bin/python tool/profile_expansion.py [--rows N] [--clean]

Connects to the container's SSH+PostgreSQL, runs the six-destination expansion
on kaggle_challenge.public.raw_data, registers versions, and prints the
timing report that the GUI would normally display.

--clean   Truncate all destination tables before running (for re-runs).
--rows N  Just informational label; does not change the database.
"""

from __future__ import annotations

import argparse
import json
import socket
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from pgdm.services.postgres_service import PostgresAdminService
from pgdm.ui.dialogs import ExpansionTimingReportDialog


ASSET_DIR = Path(__file__).resolve().parents[1] / "asset" / "sql"

RECIPE_FILES = [
    ("01_table3.sql", "public.table3"),
    ("02_table4.sql", "public.table4"),
    ("03_table1.sql", "public.table1"),
    ("04_table5.sql", "public.table5"),
    ("05_table6.sql", "public.table6"),
    ("06_table2.sql", "public.table2"),
]

DATABASE = "kaggle_challenge"
SOURCE_TABLE = "public.raw_data"
RAW_SCHEMAS = ["group001"]

SSH_HOST = "localhost"
SSH_PORT = 2222
SSH_USER = "challenge"
SSH_PASS = "challenge"
PG_PORT = 5432
PG_USER = "challenge"
PG_PASS = "challenge"


def clean_destinations(service: PostgresAdminService) -> None:
    """Truncate all destination tables so expansion can re-run."""
    tables = [table_name for _, table_name in RECIPE_FILES]
    table_list = ", ".join(tables)
    command = (
        f"psql -h localhost -U {PG_USER} -d {DATABASE} "
        f"-X -q -v ON_ERROR_STOP=1 -c "
        f"\"TRUNCATE {table_list} CASCADE;\""
    )
    service.run_remote_command(command)
    print(f"Truncated: {table_list}")

    for _, table_name in RECIPE_FILES:
        schema, table = table_name.split(".")
        reset_sql = (
            f"UPDATE app_data.row_counts "
            f"SET row_count = 0, updated_at = clock_timestamp() "
            f"WHERE schema_name = '{schema}' AND table_name = '{table}';"
        )
        try:
            service.run_remote_command(
                f"psql -h localhost -U {PG_USER} -d {DATABASE} "
                f"-X -q -v ON_ERROR_STOP=1 -c \"{reset_sql}\""
            )
        except Exception:
            pass


def reset_versions(service: PostgresAdminService) -> None:
    """Remove expansion versions, keeping only version 0000."""
    sql = (
        "DELETE FROM app_control.table_version_dependencies; "
        "DELETE FROM app_control.table_versions "
        "WHERE operation_kind = 'cross_table_expansion';"
    )
    try:
        service.run_remote_command(
            f"psql -h localhost -U {PG_USER} -d postgres_data_manager "
            f"-X -q -v ON_ERROR_STOP=1 -c \"{sql}\""
        )
        print("Removed previous expansion versions.")
    except Exception as e:
        print(f"Version cleanup note: {e}")


def build_destinations() -> list[dict]:
    destinations = []
    for filename, table_name in RECIPE_FILES:
        sql = (ASSET_DIR / filename).read_text(encoding="utf-8")
        destinations.append({
            "table_name": table_name,
            "version_title": "Baseline profiling run",
            "sql": sql,
        })
    return destinations


def run_expansion(service: PostgresAdminService) -> dict:
    timing_report = service.create_cross_table_expansion_timing_report(
        DATABASE,
        SOURCE_TABLE,
        RAW_SCHEMAS,
        [table_name for _, table_name in RECIPE_FILES],
    )

    with service.expansion_timing_scope(
        timing_report, "prepare", "Ensure control database metadata"
    ):
        service.ensure_admin_schema()

    result = service.execute_optimized_cross_table_expansion(
        database_name=DATABASE,
        source_full_table_name=SOURCE_TABLE,
        raw_schemas=RAW_SCHEMAS,
        destinations=build_destinations(),
        timing_report=timing_report,
    )

    registered = service.register_cross_table_expansion_versions(
        expansion_result=result,
        requested_by="profiling_script",
        workstation_name=socket.gethostname(),
        timing_report=timing_report,
    )

    timing_report["completed_at"] = (
        time.strftime("%Y-%m-%dT%H:%M:%S%z")
    )

    return timing_report


def main():
    parser = argparse.ArgumentParser(description="Profile the expansion pipeline")
    parser.add_argument("--clean", action="store_true",
                        help="Truncate destinations before running")
    parser.add_argument("--rows", type=int, default=0,
                        help="Informational label for row count")
    args = parser.parse_args()

    service = PostgresAdminService()

    print(f"Connecting to {SSH_HOST}:{SSH_PORT}...")
    service.connect(
        host=SSH_HOST,
        ssh_port=SSH_PORT,
        ssh_username=SSH_USER,
        ssh_password=SSH_PASS,
        postgres_port=PG_PORT,
        sql_username=PG_USER,
        sql_password=PG_PASS,
    )
    print("Connected.")

    try:
        if args.clean:
            clean_destinations(service)
            reset_versions(service)

        print(f"Running expansion on {DATABASE}.{SOURCE_TABLE}...")
        wall_start = time.perf_counter()
        timing_report = run_expansion(service)
        wall_elapsed = time.perf_counter() - wall_start

        report_text = ExpansionTimingReportDialog.build_report_text(timing_report)
        measured_total = ExpansionTimingReportDialog.measured_total_seconds(timing_report)

        print()
        print(report_text)
        print(f"WALL CLOCK TIME: {wall_elapsed:.3f} s")
        print(f"MEASURED PROCESSING TOTAL: {measured_total:.3f} s")
        print()

        # Also dump raw JSON for analysis
        report_path = Path(__file__).parent / "last_timing_report.json"
        report_path.write_text(
            json.dumps(timing_report, indent=2, default=str),
            encoding="utf-8",
        )
        print(f"Raw timing data saved to: {report_path}")

    finally:
        service.close()


if __name__ == "__main__":
    main()
