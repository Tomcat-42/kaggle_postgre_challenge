#!/usr/bin/env python3
"""Test Layer 1 optimizations we might have missed."""

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


def ssh_connect():
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(SSH_HOST, SSH_PORT, SSH_USER, SSH_PASS,
                   look_for_keys=False, allow_agent=False)
    return client


def run_psql(ssh, sql, database=DATABASE):
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


def run_timed(ssh, name, sql, setup=""):
    clean(ssh)
    full = setup + "\n" + sql if setup else sql
    print(f"\n{'='*60}")
    print(f"VARIANT: {name}")
    print(f"{'='*60}")
    wall_start = time.perf_counter()
    output = run_psql(ssh, full)
    wall_elapsed = time.perf_counter() - wall_start
    print(output)
    print(f"Wall clock: {wall_elapsed:.3f}s")


# Pre-extraction SQL with positions pre-unpivoted for table2
MATERIALIZE_WITH_POSITIONS = """
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
    NULLIF(BTRIM(raw -> 'values' ->> 'integer_column_1'), '')::numeric AS speed_num
FROM public.raw_data
WHERE raw_schema IN ('group001');

-- Pre-unpivot positions for table2 (avoids LATERAL in insert)
CREATE TEMP TABLE _positions ON COMMIT PRESERVE ROWS AS
SELECT
    s.raw_id,
    p.pos,
    ROUND(NULLIF(BTRIM(p.weight_text), '')::numeric * 1000)::integer AS weight_int,
    UPPER(BTRIM(p.type_text)) AS type_upper,
    CASE WHEN NULLIF(BTRIM(p.gap_text), '')::numeric > 0
         THEN ROUND(NULLIF(BTRIM(p.gap_text), '')::numeric * 1000)::integer
         ELSE NULL::integer END AS gap_int
FROM public.raw_data AS r
JOIN _src AS s ON s.raw_id = r.raw_id
CROSS JOIN LATERAL (VALUES
    (1::smallint, r.raw -> 'values' ->> 'integer_column_2', r.raw -> 'values' ->> 'text_column_4', r.raw -> 'values' ->> 'numeric_column_3', r.raw -> 'values' ->> 'numeric_column_4'),
    (2::smallint, r.raw -> 'values' ->> 'integer_column_3', r.raw -> 'values' ->> 'text_column_5', r.raw -> 'values' ->> 'numeric_column_5', r.raw -> 'values' ->> 'numeric_column_6'),
    (3::smallint, r.raw -> 'values' ->> 'integer_column_4', r.raw -> 'values' ->> 'text_column_6', r.raw -> 'values' ->> 'numeric_column_7', r.raw -> 'values' ->> 'numeric_column_8'),
    (4::smallint, r.raw -> 'values' ->> 'integer_column_5', r.raw -> 'values' ->> 'text_column_7', r.raw -> 'values' ->> 'numeric_column_9', r.raw -> 'values' ->> 'numeric_column_10'),
    (5::smallint, r.raw -> 'values' ->> 'integer_column_6', r.raw -> 'values' ->> 'text_column_8', r.raw -> 'values' ->> 'numeric_column_11', r.raw -> 'values' ->> 'numeric_column_12'),
    (6::smallint, r.raw -> 'values' ->> 'integer_column_7', r.raw -> 'values' ->> 'text_column_9', r.raw -> 'values' ->> 'numeric_column_13', r.raw -> 'values' ->> 'numeric_column_14'),
    (7::smallint, r.raw -> 'values' ->> 'integer_column_8', r.raw -> 'values' ->> 'text_column_10', r.raw -> 'values' ->> 'numeric_column_15', r.raw -> 'values' ->> 'numeric_column_16'),
    (8::smallint, r.raw -> 'values' ->> 'integer_column_9', r.raw -> 'values' ->> 'text_column_11', r.raw -> 'values' ->> 'numeric_column_17', r.raw -> 'values' ->> 'numeric_column_18'),
    (9::smallint, r.raw -> 'values' ->> 'integer_column_10', r.raw -> 'values' ->> 'text_column_12', r.raw -> 'values' ->> 'numeric_column_19', r.raw -> 'values' ->> 'numeric_column_20'),
    (10::smallint, r.raw -> 'values' ->> 'integer_column_11', r.raw -> 'values' ->> 'text_column_13', r.raw -> 'values' ->> 'numeric_column_21', r.raw -> 'values' ->> 'numeric_column_22'),
    (11::smallint, r.raw -> 'values' ->> 'integer_column_12', r.raw -> 'values' ->> 'text_column_14', r.raw -> 'values' ->> 'numeric_column_23', r.raw -> 'values' ->> 'numeric_column_24'),
    (12::smallint, r.raw -> 'values' ->> 'integer_column_13', r.raw -> 'values' ->> 'text_column_15', r.raw -> 'values' ->> 'numeric_column_25', r.raw -> 'values' ->> 'numeric_column_26'),
    (13::smallint, r.raw -> 'values' ->> 'integer_column_14', r.raw -> 'values' ->> 'text_column_16', r.raw -> 'values' ->> 'numeric_column_27', r.raw -> 'values' ->> 'numeric_column_28'),
    (14::smallint, r.raw -> 'values' ->> 'integer_column_15', r.raw -> 'values' ->> 'text_column_17', r.raw -> 'values' ->> 'numeric_column_29', r.raw -> 'values' ->> 'numeric_column_30')
) AS p(pos, declared_num_text, type_text, weight_text, gap_text)
WHERE NULLIF(BTRIM(p.declared_num_text), '')::smallint = p.pos
  AND NULLIF(BTRIM(p.weight_text), '')::numeric >= 0
  AND UPPER(BTRIM(p.type_text)) IN ('X', 'Y', 'Z');

ANALYZE _src;
ANALYZE _positions;
"""

DROP_FK = """
ALTER TABLE public.table1 DROP CONSTRAINT IF EXISTS table1_id_column_3_fkey;
ALTER TABLE public.table1 DROP CONSTRAINT IF EXISTS table1_id_column_4_fkey;
ALTER TABLE public.table2 DROP CONSTRAINT IF EXISTS table2_id_column_2_fkey;
ALTER TABLE public.table5 DROP CONSTRAINT IF EXISTS table5_id_column_2_fkey;
ALTER TABLE public.table6 DROP CONSTRAINT IF EXISTS table6_id_column_2_fkey;
ALTER TABLE public.table6 DROP CONSTRAINT IF EXISTS table6_id_column_3_fkey;
"""

ADD_FK = """
ALTER TABLE public.table1 ADD CONSTRAINT table1_id_column_3_fkey FOREIGN KEY (id_column_3) REFERENCES public.raw_data(raw_id) ON UPDATE CASCADE ON DELETE CASCADE;
ALTER TABLE public.table1 ADD CONSTRAINT table1_id_column_4_fkey FOREIGN KEY (id_column_4) REFERENCES public.table3(id_column_1) ON UPDATE CASCADE ON DELETE CASCADE;
ALTER TABLE public.table2 ADD CONSTRAINT table2_id_column_2_fkey FOREIGN KEY (id_column_2) REFERENCES public.table1(id_column_1) ON UPDATE CASCADE ON DELETE CASCADE;
ALTER TABLE public.table5 ADD CONSTRAINT table5_id_column_2_fkey FOREIGN KEY (id_column_2) REFERENCES public.table1(id_column_1) ON UPDATE CASCADE ON DELETE CASCADE;
ALTER TABLE public.table6 ADD CONSTRAINT table6_id_column_2_fkey FOREIGN KEY (id_column_2) REFERENCES public.table1(id_column_1) ON UPDATE CASCADE ON DELETE CASCADE;
ALTER TABLE public.table6 ADD CONSTRAINT table6_id_column_3_fkey FOREIGN KEY (id_column_3) REFERENCES public.table4(id_column_1) ON UPDATE CASCADE ON DELETE CASCADE;
"""

DROP_IDX = """
ALTER TABLE public.table1 DROP CONSTRAINT IF EXISTS table1_id_column_3_key;
ALTER TABLE public.table2 DROP CONSTRAINT IF EXISTS table2_id_column_2_integer_column_1_key;
ALTER TABLE public.table6 DROP CONSTRAINT IF EXISTS table6_id_column_2_id_column_3_key;
DROP INDEX IF EXISTS table5_id_column_3_not_null_key;
DROP INDEX IF EXISTS table5_id_column_2_when_id_column_3_null_key;
"""

REBUILD_IDX = """
ALTER TABLE public.table1 ADD CONSTRAINT table1_id_column_3_key UNIQUE (id_column_3);
ALTER TABLE public.table2 ADD CONSTRAINT table2_id_column_2_integer_column_1_key UNIQUE (id_column_2, integer_column_1);
ALTER TABLE public.table6 ADD CONSTRAINT table6_id_column_2_id_column_3_key UNIQUE (id_column_2, id_column_3);
CREATE UNIQUE INDEX table5_id_column_3_not_null_key ON public.table5 USING btree (id_column_3) WHERE (id_column_3 IS NOT NULL);
CREATE UNIQUE INDEX table5_id_column_2_when_id_column_3_null_key ON public.table5 USING btree (id_column_2) WHERE (id_column_3 IS NULL);
"""


def build_best_variant_with_precomputed_positions():
    """All L1 optimizations + pre-extracted temp table + pre-unpivoted positions."""
    return f"""
CREATE TEMP TABLE _bench_timing (step int, t timestamptz) ON COMMIT PRESERVE ROWS;

{MATERIALIZE_WITH_POSITIONS}

INSERT INTO _bench_timing VALUES (0, clock_timestamp());

BEGIN ISOLATION LEVEL REPEATABLE READ;

{DROP_FK}
{DROP_IDX}

INSERT INTO _bench_timing VALUES (10, clock_timestamp());

-- table3
INSERT INTO public.table3 (text_column_1, text_column_2, numeric_column_1, text_column_3, text_column_4)
SELECT DISTINCT s.text_1, 'SYNTHETIC/REFERENCE', NULL::numeric, LEFT(s.text_2u, 1), RIGHT(s.text_2u, 1)
FROM _src AS s WHERE s.text_1 <> '' AND s.text_2u ~ '^[A-Z]{{2}}$';

INSERT INTO _bench_timing VALUES (11, clock_timestamp());

-- table4
INSERT INTO public.table4 (id_column_1, text_column_1, text_column_2)
SELECT DISTINCT
    ((ASCII(LEFT(s.text_3u, 1)) - ASCII('A')) * 26
     + ASCII(RIGHT(s.text_3u, 1)) - ASCII('A') + 1)::smallint,
    'SYNTHETIC/GENERIC', s.text_3u
FROM _src AS s WHERE s.text_3u ~ '^[A-Z]{{2}}$';

INSERT INTO _bench_timing VALUES (21, clock_timestamp());

-- table1
INSERT INTO public.table1 (
    id_column_2, text_column_1, datetime_column_1, text_column_2,
    integer_column_1, integer_column_2, integer_column_3, text_column_3,
    id_column_3, id_column_4, id_column_5, integer_column_4, integer_column_5,
    id_column_6, integer_column_6, integer_column_7)
SELECT
    s.id_1, NULL::varchar, s.dt_1, NULL::varchar,
    GREATEST(s.int_2,s.int_3,s.int_4,s.int_5,s.int_6,s.int_7,s.int_8,s.int_9,s.int_10,s.int_11,s.int_12,s.int_13,s.int_14,s.int_15),
    NULL::smallint,
    CASE WHEN s.num_2 > 0 THEN ROUND(s.num_2 * 1000)::integer ELSE NULL END,
    NULL::varchar, s.raw_id, d.id_column_1,
    NULL::bigint, NULL::integer, NULL::integer, NULL::integer, NULL::integer,
    CASE WHEN s.num_1 > 0 THEN ROUND(s.num_1 * 1000)::integer ELSE NULL END
FROM _src AS s
JOIN public.table3 AS d
  ON d.text_column_1 = s.text_1 AND d.text_column_2 = 'SYNTHETIC/REFERENCE'
 AND d.numeric_column_1 IS NULL
 AND d.text_column_3 = LEFT(s.text_2u, 1) AND d.text_column_4 = RIGHT(s.text_2u, 1);

INSERT INTO _bench_timing VALUES (31, clock_timestamp());

-- table5
INSERT INTO public.table5 (numeric_column_1, numeric_column_2, integer_column_1, integer_column_2, id_column_2, id_column_3)
SELECT ROUND(s.speed_num, 1), NULL::numeric, NULL::integer, NULL::integer, m.id_column_1, NULL::bigint
FROM _src AS s JOIN public.table1 AS m ON m.id_column_3 = s.raw_id
WHERE s.speed_num > 0;

INSERT INTO _bench_timing VALUES (41, clock_timestamp());

-- table6
INSERT INTO public.table6 (id_column_2, id_column_3)
SELECT m.id_column_1, r.id_column_1
FROM _src AS s
JOIN public.table1 AS m ON m.id_column_3 = s.raw_id
JOIN public.table4 AS r ON r.text_column_1 = 'SYNTHETIC/GENERIC' AND r.text_column_2 = s.text_3u;

INSERT INTO _bench_timing VALUES (51, clock_timestamp());

-- table2: uses pre-computed _positions (no LATERAL needed!)
INSERT INTO public.table2 (
    id_column_2, integer_column_1, integer_column_2, text_column_1,
    integer_column_3, integer_column_4, integer_column_5, integer_column_6)
SELECT m.id_column_1, p.pos, p.weight_int, p.type_upper,
       NULL::integer, NULL::integer, NULL::integer, p.gap_int
FROM _positions AS p
JOIN public.table1 AS m ON m.id_column_3 = p.raw_id;

INSERT INTO _bench_timing VALUES (61, clock_timestamp());

{ADD_FK}
{REBUILD_IDX}

INSERT INTO _bench_timing VALUES (900, clock_timestamp());
COMMIT;
INSERT INTO _bench_timing VALUES (901, clock_timestamp());

SELECT step,
    EXTRACT(EPOCH FROM t - (SELECT t FROM _bench_timing WHERE step=0))::numeric(12,4) AS elapsed_s
FROM _bench_timing ORDER BY step;
DROP TABLE _bench_timing;
"""


def build_jit_off_only():
    """Test JIT off in isolation without other changes."""
    recipes = []
    for filename, _ in RECIPE_FILES:
        sql = (ASSET_DIR / filename).read_text(encoding="utf-8").strip()
        sql = sql.replace("{{source}}", SOURCE_SUBQUERY)
        recipes.append(sql)

    parts = [
        "CREATE TEMP TABLE _bench_timing (step int, t timestamptz) ON COMMIT PRESERVE ROWS;",
        "BEGIN ISOLATION LEVEL REPEATABLE READ;",
        "INSERT INTO _bench_timing VALUES (0, clock_timestamp());",
    ]
    for i, r in enumerate(recipes, 1):
        parts.append(f"INSERT INTO _bench_timing VALUES ({i}0, clock_timestamp());")
        parts.append(r + ";")
        parts.append(f"INSERT INTO _bench_timing VALUES ({i}1, clock_timestamp());")
    parts.extend([
        "INSERT INTO _bench_timing VALUES (900, clock_timestamp());",
        "COMMIT;",
        "INSERT INTO _bench_timing VALUES (901, clock_timestamp());",
        "SELECT step, EXTRACT(EPOCH FROM t - (SELECT t FROM _bench_timing WHERE step=0))::numeric(12,4) AS elapsed_s FROM _bench_timing ORDER BY step;",
        "DROP TABLE _bench_timing;",
    ])
    return "\n".join(parts)


def build_unlogged_variant():
    """Test UNLOGGED destination tables during insert."""
    recipes = []
    for filename, _ in RECIPE_FILES:
        sql = (ASSET_DIR / filename).read_text(encoding="utf-8").strip()
        sql = sql.replace("{{source}}", SOURCE_SUBQUERY)
        recipes.append(sql)

    set_unlogged = "\n".join(f"ALTER TABLE {t} SET UNLOGGED;" for t in DEST_TABLES)
    set_logged = "\n".join(f"ALTER TABLE {t} SET LOGGED;" for t in DEST_TABLES)

    parts = [
        "CREATE TEMP TABLE _bench_timing (step int, t timestamptz) ON COMMIT PRESERVE ROWS;",
        set_unlogged,
        "INSERT INTO _bench_timing VALUES (0, clock_timestamp());",
        "BEGIN ISOLATION LEVEL REPEATABLE READ;",
    ]
    for i, r in enumerate(recipes, 1):
        parts.append(f"INSERT INTO _bench_timing VALUES ({i}0, clock_timestamp());")
        parts.append(r + ";")
        parts.append(f"INSERT INTO _bench_timing VALUES ({i}1, clock_timestamp());")
    parts.extend([
        "INSERT INTO _bench_timing VALUES (900, clock_timestamp());",
        "COMMIT;",
        "INSERT INTO _bench_timing VALUES (901, clock_timestamp());",
        set_logged,
        "INSERT INTO _bench_timing VALUES (902, clock_timestamp());",
        "SELECT step, EXTRACT(EPOCH FROM t - (SELECT t FROM _bench_timing WHERE step=0))::numeric(12,4) AS elapsed_s FROM _bench_timing ORDER BY step;",
        "DROP TABLE _bench_timing;",
    ])
    return "\n".join(parts)


def main():
    ssh = ssh_connect()

    # ── Test 1: JIT off in isolation ──
    run_timed(ssh, "JIT OFF ONLY", build_jit_off_only(), setup="SET jit = off;")

    # ── Test 2: UNLOGGED — skipped, requires FK drop first (circular deps) ──

    # ── Test 3: Best L1 + pre-computed positions for table2 ──
    run_timed(ssh, "BEST L1 + PRE-COMPUTED POSITIONS",
              build_best_variant_with_precomputed_positions())

    # ── Test 4: temp_buffers increase ──
    run_timed(ssh, "BEST L1 + PRE-COMPUTED + temp_buffers=256MB",
              build_best_variant_with_precomputed_positions(),
              setup="SET temp_buffers = '256MB';")

    ssh.close()
    print("\nDone.")


if __name__ == "__main__":
    main()
