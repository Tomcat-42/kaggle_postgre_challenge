#!/usr/bin/env python3
"""Layer 2 benchmark: chunked expansion with checkpoint/resume.

Measures: execution time, RAM, temp storage, WAL, failure recovery.
Tests chunk sizes: 10K, 50K, 100K, 250K rows.
Compares monolithic L1 vs chunked at 1M rows.
"""

from __future__ import annotations
import sys, time, json, threading, subprocess
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import paramiko

SSH_HOST, SSH_PORT = "localhost", 2222
SSH_USER = SSH_PASS = PG_USER = PG_PASS = "challenge"
DATABASE = "kaggle_challenge"
DEST_TABLES = ["public.table3","public.table4","public.table1",
               "public.table5","public.table6","public.table2"]

JSONB_TO_RECORD_COLS = """id_column_1 text,text_column_1 text,datetime_column_1 text,integer_column_1 text,text_column_2 text,numeric_column_1 text,text_column_3 text,numeric_column_2 text,integer_column_2 text,integer_column_3 text,integer_column_4 text,integer_column_5 text,integer_column_6 text,integer_column_7 text,integer_column_8 text,integer_column_9 text,integer_column_10 text,integer_column_11 text,integer_column_12 text,integer_column_13 text,integer_column_14 text,integer_column_15 text,text_column_4 text,text_column_5 text,text_column_6 text,text_column_7 text,text_column_8 text,text_column_9 text,text_column_10 text,text_column_11 text,text_column_12 text,text_column_13 text,text_column_14 text,text_column_15 text,text_column_16 text,text_column_17 text,numeric_column_3 text,numeric_column_4 text,numeric_column_5 text,numeric_column_6 text,numeric_column_7 text,numeric_column_8 text,numeric_column_9 text,numeric_column_10 text,numeric_column_11 text,numeric_column_12 text,numeric_column_13 text,numeric_column_14 text,numeric_column_15 text,numeric_column_16 text,numeric_column_17 text,numeric_column_18 text,numeric_column_19 text,numeric_column_20 text,numeric_column_21 text,numeric_column_22 text,numeric_column_23 text,numeric_column_24 text,numeric_column_25 text,numeric_column_26 text,numeric_column_27 text,numeric_column_28 text,numeric_column_29 text,numeric_column_30 text"""

DROP_FK = "ALTER TABLE public.table1 DROP CONSTRAINT IF EXISTS table1_id_column_3_fkey;ALTER TABLE public.table1 DROP CONSTRAINT IF EXISTS table1_id_column_4_fkey;ALTER TABLE public.table2 DROP CONSTRAINT IF EXISTS table2_id_column_2_fkey;ALTER TABLE public.table5 DROP CONSTRAINT IF EXISTS table5_id_column_2_fkey;ALTER TABLE public.table6 DROP CONSTRAINT IF EXISTS table6_id_column_2_fkey;ALTER TABLE public.table6 DROP CONSTRAINT IF EXISTS table6_id_column_3_fkey;"
ADD_FK = "ALTER TABLE public.table1 ADD CONSTRAINT table1_id_column_3_fkey FOREIGN KEY (id_column_3) REFERENCES public.raw_data(raw_id) ON UPDATE CASCADE ON DELETE CASCADE;ALTER TABLE public.table1 ADD CONSTRAINT table1_id_column_4_fkey FOREIGN KEY (id_column_4) REFERENCES public.table3(id_column_1) ON UPDATE CASCADE ON DELETE CASCADE;ALTER TABLE public.table2 ADD CONSTRAINT table2_id_column_2_fkey FOREIGN KEY (id_column_2) REFERENCES public.table1(id_column_1) ON UPDATE CASCADE ON DELETE CASCADE;ALTER TABLE public.table5 ADD CONSTRAINT table5_id_column_2_fkey FOREIGN KEY (id_column_2) REFERENCES public.table1(id_column_1) ON UPDATE CASCADE ON DELETE CASCADE;ALTER TABLE public.table6 ADD CONSTRAINT table6_id_column_2_fkey FOREIGN KEY (id_column_2) REFERENCES public.table1(id_column_1) ON UPDATE CASCADE ON DELETE CASCADE;ALTER TABLE public.table6 ADD CONSTRAINT table6_id_column_3_fkey FOREIGN KEY (id_column_3) REFERENCES public.table4(id_column_1) ON UPDATE CASCADE ON DELETE CASCADE;"
DROP_IDX = "ALTER TABLE public.table1 DROP CONSTRAINT IF EXISTS table1_id_column_3_key;ALTER TABLE public.table2 DROP CONSTRAINT IF EXISTS table2_id_column_2_integer_column_1_key;ALTER TABLE public.table6 DROP CONSTRAINT IF EXISTS table6_id_column_2_id_column_3_key;DROP INDEX IF EXISTS table5_id_column_3_not_null_key;DROP INDEX IF EXISTS table5_id_column_2_when_id_column_3_null_key;"
REBUILD_IDX = "ALTER TABLE public.table1 ADD CONSTRAINT table1_id_column_3_key UNIQUE (id_column_3);ALTER TABLE public.table2 ADD CONSTRAINT table2_id_column_2_integer_column_1_key UNIQUE (id_column_2, integer_column_1);ALTER TABLE public.table6 ADD CONSTRAINT table6_id_column_2_id_column_3_key UNIQUE (id_column_2, id_column_3);CREATE UNIQUE INDEX table5_id_column_3_not_null_key ON public.table5 (id_column_3) WHERE id_column_3 IS NOT NULL;CREATE UNIQUE INDEX table5_id_column_2_when_id_column_3_null_key ON public.table5 (id_column_2) WHERE id_column_3 IS NULL;"

SRC_EXTRACT_COLS = """raw_id,
    BTRIM(v.text_column_1) AS text_1,UPPER(BTRIM(v.text_column_2)) AS text_2u,UPPER(BTRIM(v.text_column_3)) AS text_3u,
    NULLIF(BTRIM(v.id_column_1),'')::integer AS id_1,
    NULLIF(BTRIM(v.datetime_column_1),'')::timestamptz AT TIME ZONE 'America/Sao_Paulo' AS dt_1,
    NULLIF(BTRIM(v.numeric_column_1),'')::numeric AS num_1,NULLIF(BTRIM(v.numeric_column_2),'')::numeric AS num_2,
    NULLIF(BTRIM(v.integer_column_1),'')::numeric AS speed_num,
    NULLIF(BTRIM(v.integer_column_2),'')::smallint AS int_2,NULLIF(BTRIM(v.integer_column_3),'')::smallint AS int_3,
    NULLIF(BTRIM(v.integer_column_4),'')::smallint AS int_4,NULLIF(BTRIM(v.integer_column_5),'')::smallint AS int_5,
    NULLIF(BTRIM(v.integer_column_6),'')::smallint AS int_6,NULLIF(BTRIM(v.integer_column_7),'')::smallint AS int_7,
    NULLIF(BTRIM(v.integer_column_8),'')::smallint AS int_8,NULLIF(BTRIM(v.integer_column_9),'')::smallint AS int_9,
    NULLIF(BTRIM(v.integer_column_10),'')::smallint AS int_10,NULLIF(BTRIM(v.integer_column_11),'')::smallint AS int_11,
    NULLIF(BTRIM(v.integer_column_12),'')::smallint AS int_12,NULLIF(BTRIM(v.integer_column_13),'')::smallint AS int_13,
    NULLIF(BTRIM(v.integer_column_14),'')::smallint AS int_14,NULLIF(BTRIM(v.integer_column_15),'')::smallint AS int_15,
    v.text_column_4 AS txt_4,v.text_column_5 AS txt_5,v.text_column_6 AS txt_6,
    v.text_column_7 AS txt_7,v.text_column_8 AS txt_8,v.text_column_9 AS txt_9,
    v.text_column_10 AS txt_10,v.text_column_11 AS txt_11,v.text_column_12 AS txt_12,
    v.text_column_13 AS txt_13,v.text_column_14 AS txt_14,v.text_column_15 AS txt_15,
    v.text_column_16 AS txt_16,v.text_column_17 AS txt_17,
    v.numeric_column_3 AS rn_3,v.numeric_column_4 AS rn_4,v.numeric_column_5 AS rn_5,
    v.numeric_column_6 AS rn_6,v.numeric_column_7 AS rn_7,v.numeric_column_8 AS rn_8,
    v.numeric_column_9 AS rn_9,v.numeric_column_10 AS rn_10,v.numeric_column_11 AS rn_11,
    v.numeric_column_12 AS rn_12,v.numeric_column_13 AS rn_13,v.numeric_column_14 AS rn_14,
    v.numeric_column_15 AS rn_15,v.numeric_column_16 AS rn_16,v.numeric_column_17 AS rn_17,
    v.numeric_column_18 AS rn_18,v.numeric_column_19 AS rn_19,v.numeric_column_20 AS rn_20,
    v.numeric_column_21 AS rn_21,v.numeric_column_22 AS rn_22,v.numeric_column_23 AS rn_23,
    v.numeric_column_24 AS rn_24,v.numeric_column_25 AS rn_25,v.numeric_column_26 AS rn_26,
    v.numeric_column_27 AS rn_27,v.numeric_column_28 AS rn_28,v.numeric_column_29 AS rn_29,
    v.numeric_column_30 AS rn_30"""


def ssh_connect():
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(SSH_HOST, SSH_PORT, SSH_USER, SSH_PASS, look_for_keys=False, allow_agent=False)
    return c


def run_psql(ssh, sql):
    cmd = f"export PGPASSWORD={PG_PASS}; psql -h localhost -U {PG_USER} -d {DATABASE} -X -qAt -v ON_ERROR_STOP=1 -f -"
    sin, sout, serr = ssh.exec_command(cmd)
    sin.write(sql.encode()); sin.channel.shutdown_write()
    out = sout.read().decode(); err = serr.read().decode()
    if sout.channel.recv_exit_status() != 0:
        raise RuntimeError(f"psql: {err.strip()}")
    return out.strip()


def clean(ssh):
    run_psql(ssh, f"TRUNCATE {','.join(DEST_TABLES)} CASCADE;")


def get_wal_bytes(ssh):
    out = run_psql(ssh, "SELECT pg_wal_lsn_diff(pg_current_wal_lsn(), '0/0')::bigint;")
    return int(out)


def get_db_size(ssh):
    out = run_psql(ssh, f"SELECT pg_database_size('{DATABASE}');")
    return int(out)


def get_container_mem():
    """Get container RSS in bytes via podman."""
    try:
        r = subprocess.run(
            ["podman", "stats", "--no-stream", "--format", "{{.MemUsage}}",
             "container_db_1"],
            capture_output=True, text=True, timeout=10)
        usage = r.stdout.strip().split("/")[0].strip()
        for suffix, mult in [("GiB", 1024**3), ("GB", 1e9), ("MiB", 1024**2),
                              ("MB", 1e6), ("KiB", 1024), ("kB", 1e3), ("B", 1)]:
            if suffix in usage:
                return float(usage.replace(suffix, "").strip()) * mult
        return 0
    except Exception:
        return 0


def build_chunked_expansion(total_rows, chunk_size):
    """Build SQL for chunked expansion with checkpoint tracking."""
    chunks = []
    start = 1
    while start <= total_rows:
        end = min(start + chunk_size - 1, total_rows)
        chunks.append((start, end))
        start = end + 1

    parts = [
        "SET max_parallel_workers_per_gather = 4;",
        "CREATE TEMP TABLE _t (step text, t timestamptz) ON COMMIT PRESERVE ROWS;",
        "INSERT INTO _t VALUES ('start', clock_timestamp());",
        "",
        "-- Phase 1: Populate dimensions from full dataset",
        f"{DROP_FK}",
        f"{DROP_IDX}",
        "",
        f"""CREATE TEMP TABLE _dim_src ON COMMIT PRESERVE ROWS AS
SELECT BTRIM(v.text_column_1) AS text_1,
       UPPER(BTRIM(v.text_column_2)) AS text_2u,
       UPPER(BTRIM(v.text_column_3)) AS text_3u
FROM public.raw_data, jsonb_to_record(raw -> 'values') AS v(
    text_column_1 text, text_column_2 text, text_column_3 text)
WHERE raw_schema IN ('group001') AND raw_id <= {total_rows};""",
        "",
        """INSERT INTO public.table3 (text_column_1,text_column_2,numeric_column_1,text_column_3,text_column_4)
SELECT DISTINCT text_1,'SYNTHETIC/REFERENCE',NULL::numeric,LEFT(text_2u,1),RIGHT(text_2u,1)
FROM _dim_src WHERE text_1<>'' AND text_2u ~ '^[A-Z]{2}$';""",
        "",
        """INSERT INTO public.table4 (id_column_1,text_column_1,text_column_2)
SELECT DISTINCT ((ASCII(LEFT(text_3u,1))-ASCII('A'))*26+ASCII(RIGHT(text_3u,1))-ASCII('A')+1)::smallint,'SYNTHETIC/GENERIC',text_3u
FROM _dim_src WHERE text_3u ~ '^[A-Z]{2}$';""",
        "",
        "DROP TABLE _dim_src;",
        "INSERT INTO _t VALUES ('dims_done', clock_timestamp());",
        "",
        "-- Create checkpoint tracking table",
        """CREATE TEMP TABLE _checkpoint (
    chunk_num int PRIMARY KEY,
    raw_id_start bigint, raw_id_end bigint,
    committed_at timestamptz
) ON COMMIT PRESERVE ROWS;""",
    ]

    for i, (start, end) in enumerate(chunks, 1):
        scope = f"raw_schema IN ('group001') AND raw_id BETWEEN {start} AND {end}"
        parts.append(f"""
-- Chunk {i}/{len(chunks)}: raw_id {start}-{end}
INSERT INTO _t VALUES ('chunk{i}_start', clock_timestamp());

CREATE TEMP TABLE _src AS
SELECT {SRC_EXTRACT_COLS}
FROM public.raw_data, jsonb_to_record(raw -> 'values') AS v({JSONB_TO_RECORD_COLS})
WHERE {scope};

CREATE TEMP TABLE _pos AS
SELECT s.raw_id,p.pos,
    ROUND(NULLIF(BTRIM(p.wt),'')::numeric*1000)::integer AS weight_int,
    UPPER(BTRIM(p.tt)) AS type_upper,
    CASE WHEN NULLIF(BTRIM(p.gt),'')::numeric>0 THEN ROUND(NULLIF(BTRIM(p.gt),'')::numeric*1000)::integer ELSE NULL::integer END AS gap_int
FROM _src s CROSS JOIN LATERAL (VALUES
    (1::smallint,s.int_2,s.txt_4,s.rn_3,s.rn_4),(2::smallint,s.int_3,s.txt_5,s.rn_5,s.rn_6),
    (3::smallint,s.int_4,s.txt_6,s.rn_7,s.rn_8),(4::smallint,s.int_5,s.txt_7,s.rn_9,s.rn_10),
    (5::smallint,s.int_6,s.txt_8,s.rn_11,s.rn_12),(6::smallint,s.int_7,s.txt_9,s.rn_13,s.rn_14),
    (7::smallint,s.int_8,s.txt_10,s.rn_15,s.rn_16),(8::smallint,s.int_9,s.txt_11,s.rn_17,s.rn_18),
    (9::smallint,s.int_10,s.txt_12,s.rn_19,s.rn_20),(10::smallint,s.int_11,s.txt_13,s.rn_21,s.rn_22),
    (11::smallint,s.int_12,s.txt_14,s.rn_23,s.rn_24),(12::smallint,s.int_13,s.txt_15,s.rn_25,s.rn_26),
    (13::smallint,s.int_14,s.txt_16,s.rn_27,s.rn_28),(14::smallint,s.int_15,s.txt_17,s.rn_29,s.rn_30)
) AS p(pos,dn,tt,wt,gt)
WHERE dn=p.pos AND NULLIF(BTRIM(p.wt),'')::numeric>=0 AND UPPER(BTRIM(p.tt)) IN ('X','Y','Z');

BEGIN;

INSERT INTO public.table1 (id_column_2,text_column_1,datetime_column_1,text_column_2,integer_column_1,integer_column_2,integer_column_3,text_column_3,id_column_3,id_column_4,id_column_5,integer_column_4,integer_column_5,id_column_6,integer_column_6,integer_column_7)
SELECT s.id_1,NULL::varchar,s.dt_1,NULL::varchar,GREATEST(s.int_2,s.int_3,s.int_4,s.int_5,s.int_6,s.int_7,s.int_8,s.int_9,s.int_10,s.int_11,s.int_12,s.int_13,s.int_14,s.int_15),NULL::smallint,CASE WHEN s.num_2>0 THEN ROUND(s.num_2*1000)::integer ELSE NULL END,NULL::varchar,s.raw_id,d.id_column_1,NULL::bigint,NULL::integer,NULL::integer,NULL::integer,NULL::integer,CASE WHEN s.num_1>0 THEN ROUND(s.num_1*1000)::integer ELSE NULL END
FROM _src s JOIN public.table3 d ON d.text_column_1=s.text_1 AND d.text_column_2='SYNTHETIC/REFERENCE' AND d.numeric_column_1 IS NULL AND d.text_column_3=LEFT(s.text_2u,1) AND d.text_column_4=RIGHT(s.text_2u,1);

INSERT INTO public.table5 (numeric_column_1,numeric_column_2,integer_column_1,integer_column_2,id_column_2,id_column_3)
SELECT ROUND(s.speed_num,1),NULL::numeric,NULL::integer,NULL::integer,m.id_column_1,NULL::bigint FROM _src s JOIN public.table1 m ON m.id_column_3=s.raw_id WHERE s.speed_num>0;

INSERT INTO public.table6 (id_column_2,id_column_3)
SELECT m.id_column_1,r.id_column_1 FROM _src s JOIN public.table1 m ON m.id_column_3=s.raw_id JOIN public.table4 r ON r.text_column_1='SYNTHETIC/GENERIC' AND r.text_column_2=s.text_3u;

INSERT INTO public.table2 (id_column_2,integer_column_1,integer_column_2,text_column_1,integer_column_3,integer_column_4,integer_column_5,integer_column_6)
SELECT m.id_column_1,p.pos,p.weight_int,p.type_upper,NULL::integer,NULL::integer,NULL::integer,p.gap_int FROM _pos p JOIN public.table1 m ON m.id_column_3=p.raw_id;

INSERT INTO _checkpoint VALUES ({i},{start},{end},clock_timestamp());

COMMIT;
DROP TABLE IF EXISTS _src;
DROP TABLE IF EXISTS _pos;
INSERT INTO _t VALUES ('chunk{i}_done', clock_timestamp());
""")

    parts.append(f"""
-- Phase 3: Rebuild constraints and indexes
INSERT INTO _t VALUES ('rebuild_start', clock_timestamp());
{ADD_FK}
{REBUILD_IDX}
INSERT INTO _t VALUES ('rebuild_done', clock_timestamp());

-- Report
SELECT step,
    EXTRACT(EPOCH FROM t - (SELECT t FROM _t WHERE step='start'))::numeric(12,4) AS total_s,
    EXTRACT(EPOCH FROM t - lag(t) OVER (ORDER BY t))::numeric(12,4) AS delta_s
FROM _t ORDER BY t;

SELECT 'CHECKPOINT', chunk_num, raw_id_start, raw_id_end,
    EXTRACT(EPOCH FROM committed_at - (SELECT t FROM _t WHERE step='start'))::numeric(12,4) AS at_s
FROM _checkpoint ORDER BY chunk_num;

DROP TABLE _t;
DROP TABLE _checkpoint;
""")
    return "\n".join(parts)


def run_variant(ssh, name, sql):
    clean(ssh)
    mem_before = get_container_mem()
    wal_before = get_wal_bytes(ssh)
    db_before = get_db_size(ssh)

    print(f"\n{'='*60}")
    print(f"VARIANT: {name}")
    print(f"{'='*60}")

    # Sample memory during execution
    peak_mem = [mem_before]
    stop_event = threading.Event()
    def sample_mem():
        while not stop_event.is_set():
            m = get_container_mem()
            if m > 0:
                peak_mem.append(m)
            stop_event.wait(1.0)
    mem_thread = threading.Thread(target=sample_mem, daemon=True)
    mem_thread.start()

    wall_start = time.perf_counter()
    try:
        output = run_psql(ssh, sql)
        wall = time.perf_counter() - wall_start
        print(output)
    except Exception as e:
        wall = time.perf_counter() - wall_start
        print(f"FAILED: {e}")
    finally:
        stop_event.set()
        mem_thread.join(timeout=2)

    wal_after = get_wal_bytes(ssh)
    db_after = get_db_size(ssh)

    wal_generated = wal_after - wal_before
    db_growth = db_after - db_before
    mem_peak = max(peak_mem)

    print(f"Wall clock: {wall:.3f}s")
    print(f"Peak container RAM: {mem_peak/1024**2:.1f} MiB")
    print(f"WAL generated: {wal_generated/1024**2:.1f} MiB")
    print(f"DB size growth: {db_growth/1024**2:.1f} MiB")

    return {"name": name, "wall": wall, "peak_mem_mb": mem_peak/1024**2,
            "wal_mb": wal_generated/1024**2, "db_growth_mb": db_growth/1024**2}


def main():
    ssh = ssh_connect()
    total_rows = 1_000_000
    results = []

    # Monolithic L1 (for comparison)
    from benchmark_scaling import build_optimized
    r = run_variant(ssh, f"MONOLITHIC L1 ({total_rows:,} rows)",
                    build_optimized(total_rows))
    results.append(r)

    # Chunked variants
    for chunk_size in [50_000, 100_000, 250_000]:
        n_chunks = (total_rows + chunk_size - 1) // chunk_size
        sql = build_chunked_expansion(total_rows, chunk_size)
        r = run_variant(ssh, f"CHUNKED {chunk_size//1000}K ({n_chunks} chunks)",
                        sql)
        results.append(r)

    # Summary
    print(f"\n{'='*70}")
    print("LAYER 2 SUMMARY")
    print(f"{'='*70}")
    print(f"{'Variant':<30s} | {'Wall':>8s} | {'RAM':>8s} | {'WAL':>8s} | {'DB+':>8s}")
    print("-" * 70)
    for r in results:
        print(f"{r['name']:<30s} | {r['wall']:>7.1f}s | {r['peak_mem_mb']:>6.0f}MB | "
              f"{r['wal_mb']:>6.0f}MB | {r['db_growth_mb']:>6.0f}MB")

    Path(__file__).parent.joinpath("layer2_results.json").write_text(
        json.dumps(results, indent=2), encoding="utf-8")

    ssh.close()
    print("\nDone.")


if __name__ == "__main__":
    main()
