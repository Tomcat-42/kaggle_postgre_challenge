#!/usr/bin/env python3
"""Benchmark scaling: baseline vs best Layer 1 at multiple row counts.

Tests at 10K, 50K, 100K, 250K, 500K, 1M rows using raw_id filtering.
"""

from __future__ import annotations
import sys, time, json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import paramiko

ASSET_DIR = Path(__file__).resolve().parents[1] / "asset" / "sql"

SSH_HOST, SSH_PORT = "localhost", 2222
SSH_USER = SSH_PASS = PG_USER = PG_PASS = "challenge"
DATABASE = "kaggle_challenge"
DEST_TABLES = ["public.table3","public.table4","public.table1",
               "public.table5","public.table6","public.table2"]

RECIPE_FILES = [
    ("01_table3.sql", "public.table3"),
    ("02_table4.sql", "public.table4"),
    ("03_table1.sql", "public.table1"),
    ("04_table5.sql", "public.table5"),
    ("05_table6.sql", "public.table6"),
    ("06_table2.sql", "public.table2"),
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
CREATE UNIQUE INDEX table5_id_column_3_not_null_key ON public.table5 (id_column_3) WHERE id_column_3 IS NOT NULL;
CREATE UNIQUE INDEX table5_id_column_2_when_id_column_3_null_key ON public.table5 (id_column_2) WHERE id_column_3 IS NULL;
"""

JSONB_TO_RECORD_COLS = """
    id_column_1 text, text_column_1 text, datetime_column_1 text,
    integer_column_1 text, text_column_2 text, numeric_column_1 text,
    text_column_3 text, numeric_column_2 text,
    integer_column_2 text, integer_column_3 text, integer_column_4 text,
    integer_column_5 text, integer_column_6 text, integer_column_7 text,
    integer_column_8 text, integer_column_9 text, integer_column_10 text,
    integer_column_11 text, integer_column_12 text, integer_column_13 text,
    integer_column_14 text, integer_column_15 text,
    text_column_4 text, text_column_5 text, text_column_6 text,
    text_column_7 text, text_column_8 text, text_column_9 text,
    text_column_10 text, text_column_11 text, text_column_12 text,
    text_column_13 text, text_column_14 text, text_column_15 text,
    text_column_16 text, text_column_17 text,
    numeric_column_3 text, numeric_column_4 text, numeric_column_5 text,
    numeric_column_6 text, numeric_column_7 text, numeric_column_8 text,
    numeric_column_9 text, numeric_column_10 text, numeric_column_11 text,
    numeric_column_12 text, numeric_column_13 text, numeric_column_14 text,
    numeric_column_15 text, numeric_column_16 text, numeric_column_17 text,
    numeric_column_18 text, numeric_column_19 text, numeric_column_20 text,
    numeric_column_21 text, numeric_column_22 text, numeric_column_23 text,
    numeric_column_24 text, numeric_column_25 text, numeric_column_26 text,
    numeric_column_27 text, numeric_column_28 text, numeric_column_29 text,
    numeric_column_30 text
"""


def ssh_connect():
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(SSH_HOST, SSH_PORT, SSH_USER, SSH_PASS,
                   look_for_keys=False, allow_agent=False)
    return client


def run_psql(ssh, sql):
    cmd = (f"export PGPASSWORD={PG_PASS}; "
           f"psql -h localhost -U {PG_USER} -d {DATABASE} "
           f"-X -qAt -v ON_ERROR_STOP=1 -f -")
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
    run_psql(ssh, f"TRUNCATE {','.join(DEST_TABLES)} CASCADE;")


def build_baseline(n_rows):
    source = f"(SELECT * FROM public.raw_data WHERE raw_schema IN ('group001') AND raw_id <= {n_rows})"
    recipes = []
    for filename, _ in RECIPE_FILES:
        sql = (ASSET_DIR / filename).read_text(encoding="utf-8").strip()
        sql = sql.replace("{{source}}", source)
        recipes.append(sql)

    parts = [
        "CREATE TEMP TABLE _t (step int, t timestamptz) ON COMMIT PRESERVE ROWS;",
        "BEGIN ISOLATION LEVEL REPEATABLE READ;",
        "INSERT INTO _t VALUES (0, clock_timestamp());",
    ]
    for i, r in enumerate(recipes, 1):
        parts.append(r + ";")
    parts.extend([
        "INSERT INTO _t VALUES (900, clock_timestamp());",
        "COMMIT;",
        "INSERT INTO _t VALUES (901, clock_timestamp());",
        "SELECT EXTRACT(EPOCH FROM "
        "(SELECT t FROM _t WHERE step=901) - (SELECT t FROM _t WHERE step=0)"
        ")::numeric(12,4);",
        "DROP TABLE _t;",
    ])
    return "\n".join(parts)


def build_optimized(n_rows):
    scope = f"raw_schema IN ('group001') AND raw_id <= {n_rows}"
    return f"""
SET max_parallel_workers_per_gather = 4;
CREATE TEMP TABLE _t (step int, t timestamptz) ON COMMIT PRESERVE ROWS;
INSERT INTO _t VALUES (0, clock_timestamp());

CREATE TEMP TABLE _src ON COMMIT PRESERVE ROWS AS
SELECT raw_id,
    BTRIM(v.text_column_1) AS text_1,
    UPPER(BTRIM(v.text_column_2)) AS text_2u,
    UPPER(BTRIM(v.text_column_3)) AS text_3u,
    NULLIF(BTRIM(v.id_column_1), '')::integer AS id_1,
    NULLIF(BTRIM(v.datetime_column_1), '')::timestamptz AT TIME ZONE 'America/Sao_Paulo' AS dt_1,
    NULLIF(BTRIM(v.numeric_column_1), '')::numeric AS num_1,
    NULLIF(BTRIM(v.numeric_column_2), '')::numeric AS num_2,
    NULLIF(BTRIM(v.integer_column_1), '')::numeric AS speed_num,
    NULLIF(BTRIM(v.integer_column_2), '')::smallint AS int_2,
    NULLIF(BTRIM(v.integer_column_3), '')::smallint AS int_3,
    NULLIF(BTRIM(v.integer_column_4), '')::smallint AS int_4,
    NULLIF(BTRIM(v.integer_column_5), '')::smallint AS int_5,
    NULLIF(BTRIM(v.integer_column_6), '')::smallint AS int_6,
    NULLIF(BTRIM(v.integer_column_7), '')::smallint AS int_7,
    NULLIF(BTRIM(v.integer_column_8), '')::smallint AS int_8,
    NULLIF(BTRIM(v.integer_column_9), '')::smallint AS int_9,
    NULLIF(BTRIM(v.integer_column_10), '')::smallint AS int_10,
    NULLIF(BTRIM(v.integer_column_11), '')::smallint AS int_11,
    NULLIF(BTRIM(v.integer_column_12), '')::smallint AS int_12,
    NULLIF(BTRIM(v.integer_column_13), '')::smallint AS int_13,
    NULLIF(BTRIM(v.integer_column_14), '')::smallint AS int_14,
    NULLIF(BTRIM(v.integer_column_15), '')::smallint AS int_15,
    v.text_column_4 AS txt_4, v.text_column_5 AS txt_5, v.text_column_6 AS txt_6,
    v.text_column_7 AS txt_7, v.text_column_8 AS txt_8, v.text_column_9 AS txt_9,
    v.text_column_10 AS txt_10, v.text_column_11 AS txt_11, v.text_column_12 AS txt_12,
    v.text_column_13 AS txt_13, v.text_column_14 AS txt_14, v.text_column_15 AS txt_15,
    v.text_column_16 AS txt_16, v.text_column_17 AS txt_17,
    v.numeric_column_3 AS rn_3, v.numeric_column_4 AS rn_4, v.numeric_column_5 AS rn_5,
    v.numeric_column_6 AS rn_6, v.numeric_column_7 AS rn_7, v.numeric_column_8 AS rn_8,
    v.numeric_column_9 AS rn_9, v.numeric_column_10 AS rn_10, v.numeric_column_11 AS rn_11,
    v.numeric_column_12 AS rn_12, v.numeric_column_13 AS rn_13, v.numeric_column_14 AS rn_14,
    v.numeric_column_15 AS rn_15, v.numeric_column_16 AS rn_16, v.numeric_column_17 AS rn_17,
    v.numeric_column_18 AS rn_18, v.numeric_column_19 AS rn_19, v.numeric_column_20 AS rn_20,
    v.numeric_column_21 AS rn_21, v.numeric_column_22 AS rn_22, v.numeric_column_23 AS rn_23,
    v.numeric_column_24 AS rn_24, v.numeric_column_25 AS rn_25, v.numeric_column_26 AS rn_26,
    v.numeric_column_27 AS rn_27, v.numeric_column_28 AS rn_28, v.numeric_column_29 AS rn_29,
    v.numeric_column_30 AS rn_30
FROM public.raw_data,
jsonb_to_record(raw -> 'values') AS v({JSONB_TO_RECORD_COLS})
WHERE {scope};

CREATE TEMP TABLE _positions ON COMMIT PRESERVE ROWS AS
SELECT s.raw_id, p.pos,
    ROUND(NULLIF(BTRIM(p.wt), '')::numeric * 1000)::integer AS weight_int,
    UPPER(BTRIM(p.tt)) AS type_upper,
    CASE WHEN NULLIF(BTRIM(p.gt), '')::numeric > 0
         THEN ROUND(NULLIF(BTRIM(p.gt), '')::numeric * 1000)::integer ELSE NULL::integer END AS gap_int
FROM _src AS s
CROSS JOIN LATERAL (VALUES
    (1::smallint,s.int_2,s.txt_4,s.rn_3,s.rn_4),(2::smallint,s.int_3,s.txt_5,s.rn_5,s.rn_6),
    (3::smallint,s.int_4,s.txt_6,s.rn_7,s.rn_8),(4::smallint,s.int_5,s.txt_7,s.rn_9,s.rn_10),
    (5::smallint,s.int_6,s.txt_8,s.rn_11,s.rn_12),(6::smallint,s.int_7,s.txt_9,s.rn_13,s.rn_14),
    (7::smallint,s.int_8,s.txt_10,s.rn_15,s.rn_16),(8::smallint,s.int_9,s.txt_11,s.rn_17,s.rn_18),
    (9::smallint,s.int_10,s.txt_12,s.rn_19,s.rn_20),(10::smallint,s.int_11,s.txt_13,s.rn_21,s.rn_22),
    (11::smallint,s.int_12,s.txt_14,s.rn_23,s.rn_24),(12::smallint,s.int_13,s.txt_15,s.rn_25,s.rn_26),
    (13::smallint,s.int_14,s.txt_16,s.rn_27,s.rn_28),(14::smallint,s.int_15,s.txt_17,s.rn_29,s.rn_30)
) AS p(pos,dn,tt,wt,gt)
WHERE dn = p.pos AND NULLIF(BTRIM(p.wt),'')::numeric >= 0 AND UPPER(BTRIM(p.tt)) IN ('X','Y','Z');

ANALYZE _src; ANALYZE _positions;

BEGIN ISOLATION LEVEL REPEATABLE READ;
{DROP_FK}
{DROP_IDX}

INSERT INTO public.table3 (text_column_1,text_column_2,numeric_column_1,text_column_3,text_column_4)
SELECT DISTINCT s.text_1,'SYNTHETIC/REFERENCE',NULL::numeric,LEFT(s.text_2u,1),RIGHT(s.text_2u,1)
FROM _src s WHERE s.text_1<>'' AND s.text_2u ~ '^[A-Z]{{2}}$';

INSERT INTO public.table4 (id_column_1,text_column_1,text_column_2)
SELECT DISTINCT ((ASCII(LEFT(s.text_3u,1))-ASCII('A'))*26+ASCII(RIGHT(s.text_3u,1))-ASCII('A')+1)::smallint,'SYNTHETIC/GENERIC',s.text_3u
FROM _src s WHERE s.text_3u ~ '^[A-Z]{{2}}$';

INSERT INTO public.table1 (id_column_2,text_column_1,datetime_column_1,text_column_2,integer_column_1,integer_column_2,integer_column_3,text_column_3,id_column_3,id_column_4,id_column_5,integer_column_4,integer_column_5,id_column_6,integer_column_6,integer_column_7)
SELECT s.id_1,NULL::varchar,s.dt_1,NULL::varchar,GREATEST(s.int_2,s.int_3,s.int_4,s.int_5,s.int_6,s.int_7,s.int_8,s.int_9,s.int_10,s.int_11,s.int_12,s.int_13,s.int_14,s.int_15),NULL::smallint,CASE WHEN s.num_2>0 THEN ROUND(s.num_2*1000)::integer ELSE NULL END,NULL::varchar,s.raw_id,d.id_column_1,NULL::bigint,NULL::integer,NULL::integer,NULL::integer,NULL::integer,CASE WHEN s.num_1>0 THEN ROUND(s.num_1*1000)::integer ELSE NULL END
FROM _src s JOIN public.table3 d ON d.text_column_1=s.text_1 AND d.text_column_2='SYNTHETIC/REFERENCE' AND d.numeric_column_1 IS NULL AND d.text_column_3=LEFT(s.text_2u,1) AND d.text_column_4=RIGHT(s.text_2u,1);

INSERT INTO public.table5 (numeric_column_1,numeric_column_2,integer_column_1,integer_column_2,id_column_2,id_column_3)
SELECT ROUND(s.speed_num,1),NULL::numeric,NULL::integer,NULL::integer,m.id_column_1,NULL::bigint FROM _src s JOIN public.table1 m ON m.id_column_3=s.raw_id WHERE s.speed_num>0;

INSERT INTO public.table6 (id_column_2,id_column_3)
SELECT m.id_column_1,r.id_column_1 FROM _src s JOIN public.table1 m ON m.id_column_3=s.raw_id JOIN public.table4 r ON r.text_column_1='SYNTHETIC/GENERIC' AND r.text_column_2=s.text_3u;

INSERT INTO public.table2 (id_column_2,integer_column_1,integer_column_2,text_column_1,integer_column_3,integer_column_4,integer_column_5,integer_column_6)
SELECT m.id_column_1,p.pos,p.weight_int,p.type_upper,NULL::integer,NULL::integer,NULL::integer,p.gap_int FROM _positions p JOIN public.table1 m ON m.id_column_3=p.raw_id;

{ADD_FK}
{REBUILD_IDX}
INSERT INTO _t VALUES (900, clock_timestamp());
COMMIT;
INSERT INTO _t VALUES (901, clock_timestamp());

SELECT EXTRACT(EPOCH FROM (SELECT t FROM _t WHERE step=901) - (SELECT t FROM _t WHERE step=0))::numeric(12,4);
DROP TABLE _t;
"""


def run_at_scale(ssh, variant_name, build_fn, n_rows):
    clean(ssh)
    sql = build_fn(n_rows)
    wall_start = time.perf_counter()
    out = run_psql(ssh, sql)
    wall = time.perf_counter() - wall_start
    pg_time = float(out.strip())
    print(f"  {variant_name:12s} | {n_rows:>8,} rows | PG: {pg_time:8.3f}s | Wall: {wall:8.3f}s")
    return {"variant": variant_name, "rows": n_rows, "pg_time": pg_time, "wall_time": wall}


def main():
    ssh = ssh_connect()
    scales = [10_000, 50_000, 100_000, 250_000, 500_000, 1_000_000]
    results = []

    print(f"{'Variant':12s} | {'Rows':>12s} | {'PG time':>10s} | {'Wall time':>10s}")
    print("-" * 55)

    for n in scales:
        r1 = run_at_scale(ssh, "baseline", build_baseline, n)
        r2 = run_at_scale(ssh, "optimized", build_optimized, n)
        results.extend([r1, r2])
        speedup = r1["pg_time"] / r2["pg_time"] if r2["pg_time"] > 0 else 0
        print(f"  {'SPEEDUP':12s} | {n:>8,} rows | {speedup:7.2f}×")
        print()

    # Save results
    out_path = Path(__file__).parent / "scaling_results.json"
    out_path.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(f"\nResults saved to {out_path}")

    # Print summary table
    print(f"\n{'='*65}")
    print("SCALING SUMMARY")
    print(f"{'='*65}")
    print(f"{'Rows':>10s} | {'Baseline':>10s} | {'Optimized':>10s} | {'Speedup':>8s} | {'ms/row B':>9s} | {'ms/row O':>9s}")
    print("-" * 65)
    for i in range(0, len(results), 2):
        b, o = results[i], results[i+1]
        n = b["rows"]
        sp = b["pg_time"] / o["pg_time"] if o["pg_time"] > 0 else 0
        bpr = b["pg_time"] / n * 1000
        opr = o["pg_time"] / n * 1000
        print(f"{n:>10,} | {b['pg_time']:>9.3f}s | {o['pg_time']:>9.3f}s | {sp:>7.2f}× | {bpr:>8.4f} | {opr:>8.4f}")

    ssh.close()


if __name__ == "__main__":
    main()
