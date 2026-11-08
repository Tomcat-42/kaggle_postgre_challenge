#!/usr/bin/env python3
"""Benchmark Layer 1 (SQL-level) optimizations directly via psql.

Bypasses the app framework to test SQL changes in isolation.
Each variant: clean destinations → run variant → report timing.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import paramiko

ASSET_DIR = Path(__file__).resolve().parents[1] / "asset" / "sql"

SSH_HOST = "localhost"
SSH_PORT = 2222
SSH_USER = "challenge"
SSH_PASS = "challenge"
PG_USER = "challenge"
PG_PASS = "challenge"
DATABASE = "kaggle_challenge"

SOURCE_SUBQUERY = (
    "(SELECT * FROM public.raw_data WHERE raw_schema IN ('group001'))"
)

RECIPE_FILES = [
    ("01_table3.sql", "public.table3"),
    ("02_table4.sql", "public.table4"),
    ("03_table1.sql", "public.table1"),
    ("04_table5.sql", "public.table5"),
    ("05_table6.sql", "public.table6"),
    ("06_table2.sql", "public.table2"),
]

DEST_TABLES = [t for _, t in RECIPE_FILES]

ALL_FK_CONSTRAINTS = [
    ("public.table1", "table1_id_column_3_fkey"),
    ("public.table1", "table1_id_column_4_fkey"),
    ("public.table2", "table2_id_column_2_fkey"),
    ("public.table5", "table5_id_column_2_fkey"),
    ("public.table6", "table6_id_column_2_fkey"),
    ("public.table6", "table6_id_column_3_fkey"),
]

# Unique constraints (must use ALTER TABLE DROP/ADD CONSTRAINT)
ALL_UNIQUE_CONSTRAINTS = [
    ("public.table1", "table1_id_column_3_key",
     "ALTER TABLE public.table1 ADD CONSTRAINT table1_id_column_3_key UNIQUE (id_column_3)"),
    ("public.table2", "table2_id_column_2_integer_column_1_key",
     "ALTER TABLE public.table2 ADD CONSTRAINT table2_id_column_2_integer_column_1_key UNIQUE (id_column_2, integer_column_1)"),
    ("public.table6", "table6_id_column_2_id_column_3_key",
     "ALTER TABLE public.table6 ADD CONSTRAINT table6_id_column_2_id_column_3_key UNIQUE (id_column_2, id_column_3)"),
]

# Plain indexes (can use DROP/CREATE INDEX)
ALL_PLAIN_INDEXES = [
    ("public.table5", "table5_id_column_3_not_null_key",
     "CREATE UNIQUE INDEX table5_id_column_3_not_null_key ON public.table5 USING btree (id_column_3) WHERE (id_column_3 IS NOT NULL)"),
    ("public.table5", "table5_id_column_2_when_id_column_3_null_key",
     "CREATE UNIQUE INDEX table5_id_column_2_when_id_column_3_null_key ON public.table5 USING btree (id_column_2) WHERE (id_column_3 IS NULL)"),
]

# Fields extracted from jsonb by the 6 recipes (union of all used keys)
EXTRACTED_FIELDS = """
    raw_id,
    BTRIM(raw -> 'values' ->> 'text_column_1') AS v_text_1,
    UPPER(BTRIM(raw -> 'values' ->> 'text_column_2')) AS v_text_2_upper,
    UPPER(BTRIM(raw -> 'values' ->> 'text_column_3')) AS v_text_3_upper,
    NULLIF(BTRIM(raw -> 'values' ->> 'id_column_1'), '')::integer AS v_id_1,
    NULLIF(BTRIM(raw -> 'values' ->> 'datetime_column_1'), '')::timestamptz
        AT TIME ZONE 'America/Sao_Paulo' AS v_datetime_1,
    NULLIF(BTRIM(raw -> 'values' ->> 'integer_column_1'), '')::smallint AS v_integer_1,
    NULLIF(BTRIM(raw -> 'values' ->> 'numeric_column_1'), '')::numeric AS v_numeric_1,
    NULLIF(BTRIM(raw -> 'values' ->> 'numeric_column_2'), '')::numeric AS v_numeric_2,
    NULLIF(BTRIM(raw -> 'values' ->> 'integer_column_2'), '')::smallint AS v_int_2,
    NULLIF(BTRIM(raw -> 'values' ->> 'integer_column_3'), '')::smallint AS v_int_3,
    NULLIF(BTRIM(raw -> 'values' ->> 'integer_column_4'), '')::smallint AS v_int_4,
    NULLIF(BTRIM(raw -> 'values' ->> 'integer_column_5'), '')::smallint AS v_int_5,
    NULLIF(BTRIM(raw -> 'values' ->> 'integer_column_6'), '')::smallint AS v_int_6,
    NULLIF(BTRIM(raw -> 'values' ->> 'integer_column_7'), '')::smallint AS v_int_7,
    NULLIF(BTRIM(raw -> 'values' ->> 'integer_column_8'), '')::smallint AS v_int_8,
    NULLIF(BTRIM(raw -> 'values' ->> 'integer_column_9'), '')::smallint AS v_int_9,
    NULLIF(BTRIM(raw -> 'values' ->> 'integer_column_10'), '')::smallint AS v_int_10,
    NULLIF(BTRIM(raw -> 'values' ->> 'integer_column_11'), '')::smallint AS v_int_11,
    NULLIF(BTRIM(raw -> 'values' ->> 'integer_column_12'), '')::smallint AS v_int_12,
    NULLIF(BTRIM(raw -> 'values' ->> 'integer_column_13'), '')::smallint AS v_int_13,
    NULLIF(BTRIM(raw -> 'values' ->> 'integer_column_14'), '')::smallint AS v_int_14,
    NULLIF(BTRIM(raw -> 'values' ->> 'integer_column_15'), '')::smallint AS v_int_15,
    raw -> 'values' ->> 'text_column_4' AS v_text_4,
    raw -> 'values' ->> 'text_column_5' AS v_text_5,
    raw -> 'values' ->> 'text_column_6' AS v_text_6,
    raw -> 'values' ->> 'text_column_7' AS v_text_7,
    raw -> 'values' ->> 'text_column_8' AS v_text_8,
    raw -> 'values' ->> 'text_column_9' AS v_text_9,
    raw -> 'values' ->> 'text_column_10' AS v_text_10,
    raw -> 'values' ->> 'text_column_11' AS v_text_11,
    raw -> 'values' ->> 'text_column_12' AS v_text_12,
    raw -> 'values' ->> 'text_column_13' AS v_text_13,
    raw -> 'values' ->> 'text_column_14' AS v_text_14,
    raw -> 'values' ->> 'text_column_15' AS v_text_15,
    raw -> 'values' ->> 'text_column_16' AS v_text_16,
    raw -> 'values' ->> 'text_column_17' AS v_text_17,
    raw -> 'values' ->> 'numeric_column_3' AS v_num_3,
    raw -> 'values' ->> 'numeric_column_4' AS v_num_4,
    raw -> 'values' ->> 'numeric_column_5' AS v_num_5,
    raw -> 'values' ->> 'numeric_column_6' AS v_num_6,
    raw -> 'values' ->> 'numeric_column_7' AS v_num_7,
    raw -> 'values' ->> 'numeric_column_8' AS v_num_8,
    raw -> 'values' ->> 'numeric_column_9' AS v_num_9,
    raw -> 'values' ->> 'numeric_column_10' AS v_num_10,
    raw -> 'values' ->> 'numeric_column_11' AS v_num_11,
    raw -> 'values' ->> 'numeric_column_12' AS v_num_12,
    raw -> 'values' ->> 'numeric_column_13' AS v_num_13,
    raw -> 'values' ->> 'numeric_column_14' AS v_num_14,
    raw -> 'values' ->> 'numeric_column_15' AS v_num_15,
    raw -> 'values' ->> 'numeric_column_16' AS v_num_16,
    raw -> 'values' ->> 'numeric_column_17' AS v_num_17,
    raw -> 'values' ->> 'numeric_column_18' AS v_num_18,
    raw -> 'values' ->> 'numeric_column_19' AS v_num_19,
    raw -> 'values' ->> 'numeric_column_20' AS v_num_20,
    raw -> 'values' ->> 'numeric_column_21' AS v_num_21,
    raw -> 'values' ->> 'numeric_column_22' AS v_num_22,
    raw -> 'values' ->> 'numeric_column_23' AS v_num_23,
    raw -> 'values' ->> 'numeric_column_24' AS v_num_24,
    raw -> 'values' ->> 'numeric_column_25' AS v_num_25,
    raw -> 'values' ->> 'numeric_column_26' AS v_num_26,
    raw -> 'values' ->> 'numeric_column_27' AS v_num_27,
    raw -> 'values' ->> 'numeric_column_28' AS v_num_28,
    raw -> 'values' ->> 'numeric_column_29' AS v_num_29,
    raw -> 'values' ->> 'numeric_column_30' AS v_num_30
"""


def ssh_connect():
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(SSH_HOST, SSH_PORT, SSH_USER, SSH_PASS,
                   look_for_keys=False, allow_agent=False)
    return client


def run_psql(ssh, sql: str, database: str = DATABASE) -> str:
    cmd = (
        f"export PGPASSWORD={PG_PASS}; "
        f"psql -h localhost -U {PG_USER} -d {database} "
        f"-X -qAt -v ON_ERROR_STOP=1 -f -"
    )
    stdin, stdout, stderr = ssh.exec_command(cmd)
    stdin.write(sql.encode())
    stdin.channel.shutdown_write()
    out = stdout.read().decode()
    err = stderr.read().decode()
    status = stdout.channel.recv_exit_status()
    if status != 0:
        raise RuntimeError(f"psql failed ({status}): {err.strip()}")
    return out.strip()


def clean(ssh):
    table_list = ", ".join(DEST_TABLES)
    run_psql(ssh, f"TRUNCATE {table_list} CASCADE;")


def load_recipes() -> list[str]:
    recipes = []
    for filename, _ in RECIPE_FILES:
        sql = (ASSET_DIR / filename).read_text(encoding="utf-8").strip()
        sql = sql.replace("{{source}}", SOURCE_SUBQUERY)
        recipes.append(sql)
    return recipes


def build_timed_batch(recipes: list[str], preamble: str = "",
                      postamble: str = "") -> str:
    parts = [
        "CREATE TEMP TABLE _bench_timing (step int, t timestamptz) ON COMMIT PRESERVE ROWS;",
        "",
        "BEGIN ISOLATION LEVEL REPEATABLE READ;",
        "INSERT INTO _bench_timing VALUES (0, clock_timestamp());",
    ]
    if preamble:
        parts.append(preamble)

    for i, recipe in enumerate(recipes, 1):
        parts.append(f"INSERT INTO _bench_timing VALUES ({i}0, clock_timestamp());")
        parts.append(recipe + ";")
        parts.append(f"INSERT INTO _bench_timing VALUES ({i}1, clock_timestamp());")

    if postamble:
        parts.append(postamble)

    parts.append("INSERT INTO _bench_timing VALUES (900, clock_timestamp());")
    parts.append("COMMIT;")
    parts.append("INSERT INTO _bench_timing VALUES (901, clock_timestamp());")
    parts.append("")
    parts.append(
        "SELECT step, "
        "EXTRACT(EPOCH FROM t - (SELECT t FROM _bench_timing WHERE step=0))::numeric(12,4) AS elapsed_s "
        "FROM _bench_timing ORDER BY step;"
    )
    parts.append("DROP TABLE _bench_timing;")
    return "\n".join(parts)


def run_variant(ssh, name: str, recipes: list[str],
                preamble: str = "", postamble: str = "",
                session_setup: str = ""):
    clean(ssh)
    sql = build_timed_batch(recipes, preamble, postamble)
    if session_setup:
        sql = session_setup + "\n" + sql
    print(f"\n{'='*60}")
    print(f"VARIANT: {name}")
    print(f"{'='*60}")
    wall_start = time.perf_counter()
    output = run_psql(ssh, sql)
    wall_elapsed = time.perf_counter() - wall_start
    print(output)
    print(f"Wall clock: {wall_elapsed:.3f}s")
    return output


def main():
    ssh = ssh_connect()
    recipes = load_recipes()

    # ── Variant 0: Baseline ──
    run_variant(ssh, "BASELINE", recipes)

    # ── Variant 1: PG config tuning ──
    pg_tune = "\n".join([
        "SET work_mem = '256MB';",
        "SET maintenance_work_mem = '256MB';",
    ])
    run_variant(ssh, "PG CONFIG TUNING (work_mem only)", recipes,
                session_setup=pg_tune)

    # ── Variant 2: Drop/re-add FK constraints ──
    drop_fk = "\n".join(
        f"ALTER TABLE {table} DROP CONSTRAINT IF EXISTS {cname};"
        for table, cname in ALL_FK_CONSTRAINTS
    )
    add_fk_lines = []
    fk_defs = [
        ("public.table1", "table1_id_column_3_fkey", "id_column_3",
         "public.raw_data", "raw_id"),
        ("public.table1", "table1_id_column_4_fkey", "id_column_4",
         "public.table3", "id_column_1"),
        ("public.table2", "table2_id_column_2_fkey", "id_column_2",
         "public.table1", "id_column_1"),
        ("public.table5", "table5_id_column_2_fkey", "id_column_2",
         "public.table1", "id_column_1"),
        ("public.table6", "table6_id_column_2_fkey", "id_column_2",
         "public.table1", "id_column_1"),
        ("public.table6", "table6_id_column_3_fkey", "id_column_3",
         "public.table4", "id_column_1"),
    ]
    for table, cname, col, ref_table, ref_col in fk_defs:
        add_fk_lines.append(
            f"ALTER TABLE {table} ADD CONSTRAINT {cname} "
            f"FOREIGN KEY ({col}) REFERENCES {ref_table}({ref_col}) "
            f"ON UPDATE CASCADE ON DELETE CASCADE;"
        )
    add_fk = "\n".join(add_fk_lines)
    run_variant(ssh, "DROP/ADD FK CONSTRAINTS", recipes,
                preamble=drop_fk, postamble=add_fk)

    # ── Variant 3: Drop/rebuild non-PK indexes + unique constraints ──
    drop_idx = "\n".join(
        [f"ALTER TABLE {table} DROP CONSTRAINT IF EXISTS {cname};"
         for table, cname, _ in ALL_UNIQUE_CONSTRAINTS]
        + [f"DROP INDEX IF EXISTS {idx_name};"
           for _, idx_name, _ in ALL_PLAIN_INDEXES]
    )
    rebuild_idx = "\n".join(
        [f"{create_sql};"
         for _, _, create_sql in ALL_UNIQUE_CONSTRAINTS]
        + [f"{create_sql};"
           for _, _, create_sql in ALL_PLAIN_INDEXES]
    )
    run_variant(ssh, "DROP/REBUILD INDEXES+CONSTRAINTS", recipes,
                preamble=drop_idx, postamble=rebuild_idx)

    # ── Variant 4: Drop FK + Drop indexes combined ──
    run_variant(ssh, "DROP FK + DROP INDEXES", recipes,
                preamble=drop_fk + "\n" + drop_idx,
                postamble=add_fk + "\n" + rebuild_idx)

    # ── Variant 5: All Layer 1 combined ──
    run_variant(ssh, "ALL LAYER 1 COMBINED", recipes,
                preamble=drop_fk + "\n" + drop_idx,
                postamble=add_fk + "\n" + rebuild_idx,
                session_setup=pg_tune)

    # ── Variant 6: JSONB pre-extraction into temp table ──
    materialize_sql = """
CREATE TEMP TABLE _src ON COMMIT PRESERVE ROWS AS
SELECT
    raw_id,
    BTRIM(raw -> 'values' ->> 'text_column_1') AS text_1,
    UPPER(BTRIM(raw -> 'values' ->> 'text_column_2')) AS text_2u,
    UPPER(BTRIM(raw -> 'values' ->> 'text_column_3')) AS text_3u,
    NULLIF(BTRIM(raw -> 'values' ->> 'id_column_1'), '')::integer AS id_1,
    NULLIF(BTRIM(raw -> 'values' ->> 'datetime_column_1'), '')::timestamptz
        AT TIME ZONE 'America/Sao_Paulo' AS dt_1,
    NULLIF(BTRIM(raw -> 'values' ->> 'numeric_column_1'), '')::numeric AS num_1,
    NULLIF(BTRIM(raw -> 'values' ->> 'numeric_column_2'), '')::numeric AS num_2,
    NULLIF(BTRIM(raw -> 'values' ->> 'integer_column_2'), '')::smallint AS int_2,
    NULLIF(BTRIM(raw -> 'values' ->> 'integer_column_3'), '')::smallint AS int_3,
    NULLIF(BTRIM(raw -> 'values' ->> 'integer_column_4'), '')::smallint AS int_4,
    NULLIF(BTRIM(raw -> 'values' ->> 'integer_column_5'), '')::smallint AS int_5,
    NULLIF(BTRIM(raw -> 'values' ->> 'integer_column_6'), '')::smallint AS int_6,
    NULLIF(BTRIM(raw -> 'values' ->> 'integer_column_7'), '')::smallint AS int_7,
    NULLIF(BTRIM(raw -> 'values' ->> 'integer_column_8'), '')::smallint AS int_8,
    NULLIF(BTRIM(raw -> 'values' ->> 'integer_column_9'), '')::smallint AS int_9,
    NULLIF(BTRIM(raw -> 'values' ->> 'integer_column_10'), '')::smallint AS int_10,
    NULLIF(BTRIM(raw -> 'values' ->> 'integer_column_11'), '')::smallint AS int_11,
    NULLIF(BTRIM(raw -> 'values' ->> 'integer_column_12'), '')::smallint AS int_12,
    NULLIF(BTRIM(raw -> 'values' ->> 'integer_column_13'), '')::smallint AS int_13,
    NULLIF(BTRIM(raw -> 'values' ->> 'integer_column_14'), '')::smallint AS int_14,
    NULLIF(BTRIM(raw -> 'values' ->> 'integer_column_15'), '')::smallint AS int_15,
    NULLIF(BTRIM(raw -> 'values' ->> 'integer_column_1'), '')::numeric AS speed_num,
    raw -> 'values' ->> 'text_column_4' AS txt_4,
    raw -> 'values' ->> 'text_column_5' AS txt_5,
    raw -> 'values' ->> 'text_column_6' AS txt_6,
    raw -> 'values' ->> 'text_column_7' AS txt_7,
    raw -> 'values' ->> 'text_column_8' AS txt_8,
    raw -> 'values' ->> 'text_column_9' AS txt_9,
    raw -> 'values' ->> 'text_column_10' AS txt_10,
    raw -> 'values' ->> 'text_column_11' AS txt_11,
    raw -> 'values' ->> 'text_column_12' AS txt_12,
    raw -> 'values' ->> 'text_column_13' AS txt_13,
    raw -> 'values' ->> 'text_column_14' AS txt_14,
    raw -> 'values' ->> 'text_column_15' AS txt_15,
    raw -> 'values' ->> 'text_column_16' AS txt_16,
    raw -> 'values' ->> 'text_column_17' AS txt_17,
    raw -> 'values' ->> 'numeric_column_3' AS rn_3,
    raw -> 'values' ->> 'numeric_column_4' AS rn_4,
    raw -> 'values' ->> 'numeric_column_5' AS rn_5,
    raw -> 'values' ->> 'numeric_column_6' AS rn_6,
    raw -> 'values' ->> 'numeric_column_7' AS rn_7,
    raw -> 'values' ->> 'numeric_column_8' AS rn_8,
    raw -> 'values' ->> 'numeric_column_9' AS rn_9,
    raw -> 'values' ->> 'numeric_column_10' AS rn_10,
    raw -> 'values' ->> 'numeric_column_11' AS rn_11,
    raw -> 'values' ->> 'numeric_column_12' AS rn_12,
    raw -> 'values' ->> 'numeric_column_13' AS rn_13,
    raw -> 'values' ->> 'numeric_column_14' AS rn_14,
    raw -> 'values' ->> 'numeric_column_15' AS rn_15,
    raw -> 'values' ->> 'numeric_column_16' AS rn_16,
    raw -> 'values' ->> 'numeric_column_17' AS rn_17,
    raw -> 'values' ->> 'numeric_column_18' AS rn_18,
    raw -> 'values' ->> 'numeric_column_19' AS rn_19,
    raw -> 'values' ->> 'numeric_column_20' AS rn_20,
    raw -> 'values' ->> 'numeric_column_21' AS rn_21,
    raw -> 'values' ->> 'numeric_column_22' AS rn_22,
    raw -> 'values' ->> 'numeric_column_23' AS rn_23,
    raw -> 'values' ->> 'numeric_column_24' AS rn_24,
    raw -> 'values' ->> 'numeric_column_25' AS rn_25,
    raw -> 'values' ->> 'numeric_column_26' AS rn_26,
    raw -> 'values' ->> 'numeric_column_27' AS rn_27,
    raw -> 'values' ->> 'numeric_column_28' AS rn_28,
    raw -> 'values' ->> 'numeric_column_29' AS rn_29,
    raw -> 'values' ->> 'numeric_column_30' AS rn_30
FROM public.raw_data
WHERE raw_schema IN ('group001');

ANALYZE _src;
"""

    mat_recipes = [
        # 01_table3
        """INSERT INTO public.table3 (text_column_1, text_column_2, numeric_column_1, text_column_3, text_column_4)
SELECT DISTINCT s.text_1, 'SYNTHETIC/REFERENCE', NULL::numeric, LEFT(s.text_2u, 1), RIGHT(s.text_2u, 1)
FROM pg_temp._src AS s
WHERE s.text_1 <> '' AND s.text_2u ~ '^[A-Z]{2}$'""",

        # 02_table4
        """INSERT INTO public.table4 (id_column_1, text_column_1, text_column_2)
SELECT DISTINCT
    ((ASCII(LEFT(s.text_3u, 1)) - ASCII('A')) * 26
     + ASCII(RIGHT(s.text_3u, 1)) - ASCII('A') + 1)::smallint,
    'SYNTHETIC/GENERIC',
    s.text_3u
FROM pg_temp._src AS s
WHERE s.text_3u ~ '^[A-Z]{2}$'""",

        # 03_table1
        """INSERT INTO public.table1 (
    id_column_2, text_column_1, datetime_column_1, text_column_2,
    integer_column_1, integer_column_2, integer_column_3, text_column_3,
    id_column_3, id_column_4, id_column_5, integer_column_4, integer_column_5,
    id_column_6, integer_column_6, integer_column_7)
SELECT
    s.id_1, NULL::varchar, s.dt_1, NULL::varchar,
    GREATEST(s.int_2, s.int_3, s.int_4, s.int_5, s.int_6, s.int_7,
             s.int_8, s.int_9, s.int_10, s.int_11, s.int_12, s.int_13,
             s.int_14, s.int_15),
    NULL::smallint,
    CASE WHEN s.num_2 > 0 THEN ROUND(s.num_2 * 1000)::integer ELSE NULL END,
    NULL::varchar,
    s.raw_id,
    d.id_column_1,
    NULL::bigint, NULL::integer, NULL::integer, NULL::integer, NULL::integer,
    CASE WHEN s.num_1 > 0 THEN ROUND(s.num_1 * 1000)::integer ELSE NULL END
FROM pg_temp._src AS s
JOIN public.table3 AS d
  ON d.text_column_1 = s.text_1
 AND d.text_column_2 = 'SYNTHETIC/REFERENCE'
 AND d.numeric_column_1 IS NULL
 AND d.text_column_3 = LEFT(s.text_2u, 1)
 AND d.text_column_4 = RIGHT(s.text_2u, 1)""",

        # 04_table5
        """INSERT INTO public.table5 (numeric_column_1, numeric_column_2, integer_column_1, integer_column_2, id_column_2, id_column_3)
SELECT ROUND(s.speed_num, 1), NULL::numeric, NULL::integer, NULL::integer, m.id_column_1, NULL::bigint
FROM pg_temp._src AS s
JOIN public.table1 AS m ON m.id_column_3 = s.raw_id
WHERE s.speed_num > 0""",

        # 05_table6
        """INSERT INTO public.table6 (id_column_2, id_column_3)
SELECT m.id_column_1, r.id_column_1
FROM pg_temp._src AS s
JOIN public.table1 AS m ON m.id_column_3 = s.raw_id
JOIN public.table4 AS r ON r.text_column_1 = 'SYNTHETIC/GENERIC' AND r.text_column_2 = s.text_3u""",

        # 06_table2
        """INSERT INTO public.table2 (
    id_column_2, integer_column_1, integer_column_2, text_column_1,
    integer_column_3, integer_column_4, integer_column_5, integer_column_6)
SELECT
    m.id_column_1,
    p.pos,
    ROUND(NULLIF(BTRIM(p.weight_text), '')::numeric * 1000)::integer,
    UPPER(BTRIM(p.type_text)),
    NULL::integer, NULL::integer, NULL::integer,
    CASE WHEN NULLIF(BTRIM(p.gap_text), '')::numeric > 0
         THEN ROUND(NULLIF(BTRIM(p.gap_text), '')::numeric * 1000)::integer
         ELSE NULL END
FROM pg_temp._src AS s
CROSS JOIN LATERAL (VALUES
    (1::smallint, s.int_2, s.txt_4, s.rn_3, s.rn_4),
    (2::smallint, s.int_3, s.txt_5, s.rn_5, s.rn_6),
    (3::smallint, s.int_4, s.txt_6, s.rn_7, s.rn_8),
    (4::smallint, s.int_5, s.txt_7, s.rn_9, s.rn_10),
    (5::smallint, s.int_6, s.txt_8, s.rn_11, s.rn_12),
    (6::smallint, s.int_7, s.txt_9, s.rn_13, s.rn_14),
    (7::smallint, s.int_8, s.txt_10, s.rn_15, s.rn_16),
    (8::smallint, s.int_9, s.txt_11, s.rn_17, s.rn_18),
    (9::smallint, s.int_10, s.txt_12, s.rn_19, s.rn_20),
    (10::smallint, s.int_11, s.txt_13, s.rn_21, s.rn_22),
    (11::smallint, s.int_12, s.txt_14, s.rn_23, s.rn_24),
    (12::smallint, s.int_13, s.txt_15, s.rn_25, s.rn_26),
    (13::smallint, s.int_14, s.txt_16, s.rn_27, s.rn_28),
    (14::smallint, s.int_15, s.txt_17, s.rn_29, s.rn_30)
) AS p(pos, declared_num, type_text, weight_text, gap_text)
JOIN public.table1 AS m ON m.id_column_3 = s.raw_id
WHERE declared_num = p.pos
  AND NULLIF(BTRIM(p.weight_text), '')::numeric >= 0
  AND UPPER(BTRIM(p.type_text)) IN ('X', 'Y', 'Z')""",
    ]

    run_variant(ssh, "JSONB PRE-EXTRACTION (temp table)", mat_recipes,
                preamble=materialize_sql)

    # ── Variant 7: Everything combined ──
    run_variant(ssh, "ALL LAYER 1 + PRE-EXTRACTION", mat_recipes,
                preamble=materialize_sql + "\n" + drop_fk + "\n" + drop_idx,
                postamble=add_fk + "\n" + rebuild_idx,
                session_setup=pg_tune)

    ssh.close()
    print("\nDone.")


if __name__ == "__main__":
    main()
