#!/usr/bin/env python3
"""Benchmark single-pass extraction: all fields from raw_data in one scan."""

from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import paramiko

SSH_HOST = "localhost"
SSH_PORT = 2222
SSH_USER = "challenge"
SSH_PASS = "challenge"
PG_USER = "challenge"
PG_PASS = "challenge"
DATABASE = "kaggle_challenge"

DEST_TABLES = [
    "public.table3", "public.table4", "public.table1",
    "public.table5", "public.table6", "public.table2",
]

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

# Single-pass extraction: ALL fields from raw_data in one scan
SINGLE_PASS_EXTRACT = """
CREATE TEMP TABLE _src ON COMMIT PRESERVE ROWS AS
SELECT
    raw_id,
    -- Base fields (used by table3, table4, table1, table5, table6)
    BTRIM(raw -> 'values' ->> 'text_column_1') AS text_1,
    UPPER(BTRIM(raw -> 'values' ->> 'text_column_2')) AS text_2u,
    UPPER(BTRIM(raw -> 'values' ->> 'text_column_3')) AS text_3u,
    NULLIF(BTRIM(raw -> 'values' ->> 'id_column_1'), '')::integer AS id_1,
    NULLIF(BTRIM(raw -> 'values' ->> 'datetime_column_1'), '')::timestamptz
        AT TIME ZONE 'America/Sao_Paulo' AS dt_1,
    NULLIF(BTRIM(raw -> 'values' ->> 'numeric_column_1'), '')::numeric AS num_1,
    NULLIF(BTRIM(raw -> 'values' ->> 'numeric_column_2'), '')::numeric AS num_2,
    NULLIF(BTRIM(raw -> 'values' ->> 'integer_column_1'), '')::numeric AS speed_num,
    -- Integer columns (used by table1 GREATEST + table2 position matching)
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
    -- Positional type texts (used by table2 LATERAL)
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
    -- Positional numeric texts (used by table2 weight/gap)
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
"""

# _positions now reads from _src only (no raw_data re-scan)
POSITIONS_FROM_SRC = """
CREATE TEMP TABLE _positions ON COMMIT PRESERVE ROWS AS
SELECT
    s.raw_id,
    p.pos,
    ROUND(NULLIF(BTRIM(p.weight_text), '')::numeric * 1000)::integer AS weight_int,
    UPPER(BTRIM(p.type_text)) AS type_upper,
    CASE WHEN NULLIF(BTRIM(p.gap_text), '')::numeric > 0
         THEN ROUND(NULLIF(BTRIM(p.gap_text), '')::numeric * 1000)::integer
         ELSE NULL::integer END AS gap_int
FROM _src AS s
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
WHERE declared_num = p.pos
  AND NULLIF(BTRIM(p.weight_text), '')::numeric >= 0
  AND UPPER(BTRIM(p.type_text)) IN ('X', 'Y', 'Z');
"""

INSERT_RECIPES = """
INSERT INTO _t VALUES (11, clock_timestamp());
-- table3
INSERT INTO public.table3 (text_column_1, text_column_2, numeric_column_1, text_column_3, text_column_4)
SELECT DISTINCT s.text_1, 'SYNTHETIC/REFERENCE', NULL::numeric, LEFT(s.text_2u, 1), RIGHT(s.text_2u, 1)
FROM _src AS s WHERE s.text_1 <> '' AND s.text_2u ~ '^[A-Z]{2}$';

INSERT INTO _t VALUES (21, clock_timestamp());
-- table4
INSERT INTO public.table4 (id_column_1, text_column_1, text_column_2)
SELECT DISTINCT
    ((ASCII(LEFT(s.text_3u, 1)) - ASCII('A')) * 26
     + ASCII(RIGHT(s.text_3u, 1)) - ASCII('A') + 1)::smallint,
    'SYNTHETIC/GENERIC', s.text_3u
FROM _src AS s WHERE s.text_3u ~ '^[A-Z]{2}$';

INSERT INTO _t VALUES (31, clock_timestamp());
-- table1
INSERT INTO public.table1 (
    id_column_2, text_column_1, datetime_column_1, text_column_2,
    integer_column_1, integer_column_2, integer_column_3, text_column_3,
    id_column_3, id_column_4, id_column_5, integer_column_4, integer_column_5,
    id_column_6, integer_column_6, integer_column_7)
SELECT
    s.id_1, NULL::varchar, s.dt_1, NULL::varchar,
    GREATEST(s.int_2,s.int_3,s.int_4,s.int_5,s.int_6,s.int_7,s.int_8,s.int_9,
             s.int_10,s.int_11,s.int_12,s.int_13,s.int_14,s.int_15),
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

INSERT INTO _t VALUES (41, clock_timestamp());
-- table5
INSERT INTO public.table5 (numeric_column_1, numeric_column_2, integer_column_1, integer_column_2, id_column_2, id_column_3)
SELECT ROUND(s.speed_num, 1), NULL::numeric, NULL::integer, NULL::integer, m.id_column_1, NULL::bigint
FROM _src AS s JOIN public.table1 AS m ON m.id_column_3 = s.raw_id
WHERE s.speed_num > 0;

INSERT INTO _t VALUES (51, clock_timestamp());
-- table6
INSERT INTO public.table6 (id_column_2, id_column_3)
SELECT m.id_column_1, r.id_column_1
FROM _src AS s
JOIN public.table1 AS m ON m.id_column_3 = s.raw_id
JOIN public.table4 AS r ON r.text_column_1 = 'SYNTHETIC/GENERIC' AND r.text_column_2 = s.text_3u;

INSERT INTO _t VALUES (61, clock_timestamp());
-- table2 (from pre-computed _positions, no LATERAL)
INSERT INTO public.table2 (
    id_column_2, integer_column_1, integer_column_2, text_column_1,
    integer_column_3, integer_column_4, integer_column_5, integer_column_6)
SELECT m.id_column_1, p.pos, p.weight_int, p.type_upper,
       NULL::integer, NULL::integer, NULL::integer, p.gap_int
FROM _positions AS p
JOIN public.table1 AS m ON m.id_column_3 = p.raw_id;

INSERT INTO _t VALUES (71, clock_timestamp());
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


def build_variant(parallel_workers=2):
    return f"""
SET max_parallel_workers_per_gather = {parallel_workers};

CREATE TEMP TABLE _t (step int, t timestamptz) ON COMMIT PRESERVE ROWS;
INSERT INTO _t VALUES (0, clock_timestamp());

-- Step 1: Single-pass extraction (ALL fields from raw_data, one scan)
INSERT INTO _t VALUES (1, clock_timestamp());
{SINGLE_PASS_EXTRACT}
INSERT INTO _t VALUES (2, clock_timestamp());

-- Step 2: Unpivot positions from _src (no raw_data re-scan)
{POSITIONS_FROM_SRC}
INSERT INTO _t VALUES (3, clock_timestamp());

-- Step 3: ANALYZE
ANALYZE _src;
ANALYZE _positions;
INSERT INTO _t VALUES (4, clock_timestamp());

-- Step 4: Transaction with inserts
BEGIN ISOLATION LEVEL REPEATABLE READ;
INSERT INTO _t VALUES (10, clock_timestamp());

{DROP_FK}
{DROP_IDX}

{INSERT_RECIPES}

{ADD_FK}
{REBUILD_IDX}

INSERT INTO _t VALUES (900, clock_timestamp());
COMMIT;
INSERT INTO _t VALUES (901, clock_timestamp());

SELECT step,
    EXTRACT(EPOCH FROM t - (SELECT t FROM _t WHERE step=0))::numeric(12,4) AS total_s,
    EXTRACT(EPOCH FROM t - lag(t) OVER (ORDER BY step))::numeric(12,4) AS delta_s
FROM _t ORDER BY step;
DROP TABLE _t;
"""


def run_variant(ssh, name, sql):
    clean(ssh)
    print(f"\n{'='*60}")
    print(f"VARIANT: {name}")
    print(f"{'='*60}")
    print("Steps: 0=start, 1=pre-extract, 2=src-done, 3=positions-done, 4=analyzed")
    print("  10=txn, 11=t3, 21=t4, 31=t1, 41=t5, 51=t6, 61=t2, 71=inserts-done")
    print("  900=rebuilt, 901=committed")
    wall_start = time.perf_counter()
    output = run_psql(ssh, sql)
    wall_elapsed = time.perf_counter() - wall_start
    print(output)
    print(f"Wall clock: {wall_elapsed:.3f}s")


def main():
    ssh = ssh_connect()

    # Two-pass (previous best) vs single-pass comparison
    run_variant(ssh, "SINGLE-PASS parallel=0", build_variant(parallel_workers=0))
    run_variant(ssh, "SINGLE-PASS parallel=2", build_variant(parallel_workers=2))
    run_variant(ssh, "SINGLE-PASS parallel=4", build_variant(parallel_workers=4))

    # Run 3 times at best setting for consistency
    for i in range(3):
        run_variant(ssh, f"SINGLE-PASS parallel=4 (run {i+1}/3)", build_variant(parallel_workers=4))

    ssh.close()
    print("\nDone.")


if __name__ == "__main__":
    main()
