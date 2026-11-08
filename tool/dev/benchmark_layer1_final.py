#!/usr/bin/env python3
"""Final Layer 1 benchmark: test every remaining hypothesis with data.

Tests:
  1. Parallel extraction (max_parallel_workers_per_gather = 0,2,4)
  2. Autovacuum disabled on destinations during expansion
  3. JIT on vs off for the extraction phase specifically
  4. synchronous_commit off for the full pipeline
  5. Full best variant (all winners combined)
  6. Baseline for comparison

Each variant: clean → run → report per-step timings.
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

SOURCE_SUBQUERY = "(SELECT * FROM public.raw_data WHERE raw_schema IN ('group001'))"

RECIPE_FILES = [
    ("01_table3.sql", "public.table3"),
    ("02_table4.sql", "public.table4"),
    ("03_table1.sql", "public.table1"),
    ("04_table5.sql", "public.table5"),
    ("05_table6.sql", "public.table6"),
    ("06_table2.sql", "public.table2"),
]

DEST_TABLES = [t for _, t in RECIPE_FILES]

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

DISABLE_AUTOVAC = "\n".join(
    f"ALTER TABLE {t} SET (autovacuum_enabled = false);"
    for t in DEST_TABLES
)

ENABLE_AUTOVAC = "\n".join(
    f"ALTER TABLE {t} SET (autovacuum_enabled = true);"
    for t in DEST_TABLES
)

EXTRACT_SRC = """
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
"""

EXTRACT_POSITIONS = """
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
"""

INSERT_RECIPES = """
-- table3
INSERT INTO public.table3 (text_column_1, text_column_2, numeric_column_1, text_column_3, text_column_4)
SELECT DISTINCT s.text_1, 'SYNTHETIC/REFERENCE', NULL::numeric, LEFT(s.text_2u, 1), RIGHT(s.text_2u, 1)
FROM _src AS s WHERE s.text_1 <> '' AND s.text_2u ~ '^[A-Z]{2}$';

INSERT INTO _t VALUES (11, clock_timestamp());

-- table4
INSERT INTO public.table4 (id_column_1, text_column_1, text_column_2)
SELECT DISTINCT
    ((ASCII(LEFT(s.text_3u, 1)) - ASCII('A')) * 26
     + ASCII(RIGHT(s.text_3u, 1)) - ASCII('A') + 1)::smallint,
    'SYNTHETIC/GENERIC', s.text_3u
FROM _src AS s WHERE s.text_3u ~ '^[A-Z]{2}$';

INSERT INTO _t VALUES (21, clock_timestamp());

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

INSERT INTO _t VALUES (31, clock_timestamp());

-- table5
INSERT INTO public.table5 (numeric_column_1, numeric_column_2, integer_column_1, integer_column_2, id_column_2, id_column_3)
SELECT ROUND(s.speed_num, 1), NULL::numeric, NULL::integer, NULL::integer, m.id_column_1, NULL::bigint
FROM _src AS s JOIN public.table1 AS m ON m.id_column_3 = s.raw_id
WHERE s.speed_num > 0;

INSERT INTO _t VALUES (41, clock_timestamp());

-- table6
INSERT INTO public.table6 (id_column_2, id_column_3)
SELECT m.id_column_1, r.id_column_1
FROM _src AS s
JOIN public.table1 AS m ON m.id_column_3 = s.raw_id
JOIN public.table4 AS r ON r.text_column_1 = 'SYNTHETIC/GENERIC' AND r.text_column_2 = s.text_3u;

INSERT INTO _t VALUES (51, clock_timestamp());

-- table2 (pre-computed positions)
INSERT INTO public.table2 (
    id_column_2, integer_column_1, integer_column_2, text_column_1,
    integer_column_3, integer_column_4, integer_column_5, integer_column_6)
SELECT m.id_column_1, p.pos, p.weight_int, p.type_upper,
       NULL::integer, NULL::integer, NULL::integer, p.gap_int
FROM _positions AS p
JOIN public.table1 AS m ON m.id_column_3 = p.raw_id;

INSERT INTO _t VALUES (61, clock_timestamp());
"""


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
    run_psql(ssh, f"TRUNCATE {', '.join(DEST_TABLES)} CASCADE;")


def build_full_variant(parallel_workers=None, jit=None, sync_commit=None,
                       autovac_off=False, drop_fk=True, drop_idx=True,
                       temp_buffers=None):
    """Build complete SQL with all options and fine-grained timing."""
    parts = []

    # Session settings
    if parallel_workers is not None:
        parts.append(f"SET max_parallel_workers_per_gather = {parallel_workers};")
    if jit is not None:
        parts.append(f"SET jit = {'on' if jit else 'off'};")
    if sync_commit is not None:
        parts.append(f"SET synchronous_commit = {'on' if sync_commit else 'off'};")
    if temp_buffers:
        parts.append(f"SET temp_buffers = '{temp_buffers}';")

    parts.append("CREATE TEMP TABLE _t (step int, t timestamptz) ON COMMIT PRESERVE ROWS;")
    parts.append("INSERT INTO _t VALUES (0, clock_timestamp());")

    # Autovacuum
    if autovac_off:
        parts.append(DISABLE_AUTOVAC)

    # Extraction
    parts.append("INSERT INTO _t VALUES (1, clock_timestamp());")
    parts.append(EXTRACT_SRC)
    parts.append("INSERT INTO _t VALUES (2, clock_timestamp());")
    parts.append(EXTRACT_POSITIONS)
    parts.append("INSERT INTO _t VALUES (3, clock_timestamp());")
    parts.append("ANALYZE _src;")
    parts.append("ANALYZE _positions;")
    parts.append("INSERT INTO _t VALUES (4, clock_timestamp());")

    # Transaction
    parts.append("BEGIN ISOLATION LEVEL REPEATABLE READ;")
    parts.append("INSERT INTO _t VALUES (10, clock_timestamp());")

    if drop_fk:
        parts.append(DROP_FK)
    if drop_idx:
        parts.append(DROP_IDX)

    parts.append(INSERT_RECIPES)

    if drop_fk:
        parts.append(ADD_FK)
    if drop_idx:
        parts.append(REBUILD_IDX)

    parts.append("INSERT INTO _t VALUES (900, clock_timestamp());")
    parts.append("COMMIT;")
    parts.append("INSERT INTO _t VALUES (901, clock_timestamp());")

    if autovac_off:
        parts.append(ENABLE_AUTOVAC)

    parts.append("""
SELECT step,
    EXTRACT(EPOCH FROM t - (SELECT t FROM _t WHERE step=0))::numeric(12,4) AS total_s,
    EXTRACT(EPOCH FROM t - lag(t) OVER (ORDER BY step))::numeric(12,4) AS delta_s
FROM _t ORDER BY step;
""")
    parts.append("DROP TABLE _t;")
    return "\n".join(parts)


def run_variant(ssh, name, sql):
    clean(ssh)
    print(f"\n{'='*60}")
    print(f"VARIANT: {name}")
    print(f"{'='*60}")
    wall_start = time.perf_counter()
    try:
        output = run_psql(ssh, sql)
        wall_elapsed = time.perf_counter() - wall_start
        print(output)
        print(f"Wall clock: {wall_elapsed:.3f}s")
    except Exception as e:
        wall_elapsed = time.perf_counter() - wall_start
        print(f"FAILED after {wall_elapsed:.3f}s: {e}")


# Step legend:
# 0=start, 1=pre-extract-start, 2=src-done, 3=positions-done, 4=analyze-done
# 10=txn-start, 11=table3-done, 21=table4-done, 31=table1-done
# 41=table5-done, 51=table6-done, 61=table2-done
# 900=pre-commit, 901=committed

def main():
    ssh = ssh_connect()

    print("Step legend:")
    print("  0=start, 1=extract-begin, 2=_src done, 3=_positions done, 4=analyze done")
    print("  10=txn+drops, 11=table3, 21=table4, 31=table1, 41=table5, 51=table6, 61=table2")
    print("  900=pre-commit(+rebuild), 901=committed")

    # ── 1. Baseline: original recipes, no optimizations ──
    baseline_recipes = []
    for filename, _ in RECIPE_FILES:
        sql = (ASSET_DIR / filename).read_text(encoding="utf-8").strip()
        sql = sql.replace("{{source}}", SOURCE_SUBQUERY)
        baseline_recipes.append(sql)

    baseline_sql = [
        "CREATE TEMP TABLE _t (step int, t timestamptz) ON COMMIT PRESERVE ROWS;",
        "BEGIN ISOLATION LEVEL REPEATABLE READ;",
        "INSERT INTO _t VALUES (0, clock_timestamp());",
    ]
    for i, r in enumerate(baseline_recipes, 1):
        baseline_sql.append(f"INSERT INTO _t VALUES ({i}0, clock_timestamp());")
        baseline_sql.append(r + ";")
        baseline_sql.append(f"INSERT INTO _t VALUES ({i}1, clock_timestamp());")
    baseline_sql.extend([
        "INSERT INTO _t VALUES (900, clock_timestamp());",
        "COMMIT;",
        "INSERT INTO _t VALUES (901, clock_timestamp());",
        "SELECT step, EXTRACT(EPOCH FROM t - (SELECT t FROM _t WHERE step=0))::numeric(12,4) AS total_s, "
        "EXTRACT(EPOCH FROM t - lag(t) OVER (ORDER BY step))::numeric(12,4) AS delta_s FROM _t ORDER BY step;",
        "DROP TABLE _t;",
    ])
    run_variant(ssh, "BASELINE", "\n".join(baseline_sql))

    # ── 2. Parallel workers = 0 (disable parallel for extraction) ──
    run_variant(ssh, "PARALLEL=0", build_full_variant(parallel_workers=0))

    # ── 3. Parallel workers = 2 (default) ──
    run_variant(ssh, "PARALLEL=2 (default)", build_full_variant(parallel_workers=2))

    # ── 4. Parallel workers = 4 ──
    run_variant(ssh, "PARALLEL=4", build_full_variant(parallel_workers=4))

    # ── 5. Autovacuum off ──
    run_variant(ssh, "AUTOVAC OFF", build_full_variant(autovac_off=True))

    # ── 6. Autovacuum off + default parallel ──
    run_variant(ssh, "AUTOVAC OFF + default", build_full_variant(autovac_off=True))

    # ── 7. JIT off for extraction ──
    run_variant(ssh, "JIT OFF", build_full_variant(jit=False))

    # ── 8. JIT on explicit ──
    run_variant(ssh, "JIT ON (explicit)", build_full_variant(jit=True))

    # ── 9. synchronous_commit off ──
    run_variant(ssh, "SYNC COMMIT OFF", build_full_variant(sync_commit=False))

    # ── 10. temp_buffers=256MB ──
    run_variant(ssh, "TEMP BUFFERS 256MB", build_full_variant(temp_buffers="256MB"))

    # ── 11. BEST: all winners combined ──
    # (will determine best parallel, best jit, etc. from above results)
    run_variant(ssh, "ALL COMBINED (parallel=4, autovac=off, temp=256MB)",
                build_full_variant(parallel_workers=4, autovac_off=True,
                                   temp_buffers="256MB"))

    ssh.close()
    print("\nDone.")


if __name__ == "__main__":
    main()
