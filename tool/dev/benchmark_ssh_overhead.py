#!/usr/bin/env python3
"""Benchmark SSH overhead reduction strategies at 1M rows.

Compares:
  A. Current: SSH exec_command → psql -f - (text protocol, many round-trips)
  B. SSH tunnel + psycopg3 (binary protocol, single connection)
  C. Batched preflight (one SQL call instead of ~20)
  D. All combined

Only measures WALL CLOCK — the scored metric (MEASURED PROCESSING TOTAL)
excludes SSH transport by design.
"""

from __future__ import annotations
import sys, time, json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import paramiko
import psycopg
from sshtunnel import SSHTunnelForwarder

SSH_HOST, SSH_PORT = "localhost", 2222
SSH_USER = SSH_PASS = PG_USER = PG_PASS = "challenge"
PG_PORT = 5432
DATABASE = "kaggle_challenge"
DEST_TABLES = ["public.table3","public.table4","public.table1",
               "public.table5","public.table6","public.table2"]


# The full optimized SQL batch (smart chunked 250K, all L1+L2+L3)
def load_full_sql():
    """Load the best variant SQL from benchmark_smart_chunking."""
    # Import and generate
    sys.path.insert(0, str(Path(__file__).parent))
    from benchmark_smart_chunking import build_smart_chunked
    return build_smart_chunked(1_000_000, 250_000)


def ssh_connect():
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(SSH_HOST, SSH_PORT, SSH_USER, SSH_PASS,
              look_for_keys=False, allow_agent=False)
    return c


def run_psql(ssh, sql):
    cmd = f"export PGPASSWORD={PG_PASS}; psql -h localhost -U {PG_USER} -d {DATABASE} -X -qAt -v ON_ERROR_STOP=1 -f -"
    sin, sout, serr = ssh.exec_command(cmd)
    sin.write(sql.encode()); sin.channel.shutdown_write()
    out = sout.read().decode(); err = serr.read().decode()
    if sout.channel.recv_exit_status() != 0:
        raise RuntimeError(f"psql: {err.strip()[:300]}")
    return out.strip()


def clean_psql(ssh):
    run_psql(ssh, f"TRUNCATE {','.join(DEST_TABLES)} CASCADE;")


def clean_psycopg(conn):
    with conn.cursor() as cur:
        cur.execute(f"TRUNCATE {','.join(DEST_TABLES)} CASCADE")
    conn.commit()


def variant_a_psql(ssh, sql):
    """Current approach: SSH exec → psql."""
    clean_psql(ssh)
    wall_start = time.perf_counter()
    out = run_psql(ssh, sql)
    wall = time.perf_counter() - wall_start
    return wall, out


def variant_b_psycopg(sql):
    """SSH tunnel + psycopg3 binary protocol."""
    # Create SSH tunnel
    tunnel = SSHTunnelForwarder(
        (SSH_HOST, SSH_PORT),
        ssh_username=SSH_USER,
        ssh_password=SSH_PASS,
        remote_bind_address=("localhost", PG_PORT),
    )
    tunnel.start()

    try:
        conn = psycopg.connect(
            host="localhost",
            port=tunnel.local_bind_port,
            user=PG_USER,
            password=PG_PASS,
            dbname=DATABASE,
            autocommit=True,
        )
        clean_psycopg(conn)

        # psycopg3 can execute multi-statement scripts
        wall_start = time.perf_counter()
        with conn.cursor() as cur:
            # Split on statement boundaries and execute
            # Actually, psycopg can't execute multi-statement strings directly
            # We need to split or use conn.execute with a single-statement approach
            # For fair comparison, pipe the same SQL
            cur.execute(sql)
            # Fetch any results
            try:
                rows = cur.fetchall()
                out = "\n".join("|".join(str(c) for c in row) for row in rows)
            except psycopg.ProgrammingError:
                out = ""
        wall = time.perf_counter() - wall_start
        conn.close()
    finally:
        tunnel.stop()

    return wall, out


def main():
    ssh = ssh_connect()
    sql = load_full_sql()
    results = []

    # ── A: Current psql approach (3 runs) ──
    print("VARIANT A: SSH exec → psql")
    for i in range(3):
        wall, out = variant_a_psql(ssh, sql)
        print(f"  Run {i+1}: {wall:.3f}s")
        results.append({"variant": "psql", "run": i+1, "wall": wall})

    # ── B: SSH tunnel + psycopg3 ──
    # psycopg3 can't run multi-statement SQL the same way psql does
    # Instead, test the overhead of connection setup + simple queries
    print("\nVARIANT B: SSH tunnel + psycopg3 (connection overhead test)")
    try:
        tunnel = SSHTunnelForwarder(
            (SSH_HOST, SSH_PORT),
            ssh_username=SSH_USER,
            ssh_password=SSH_PASS,
            remote_bind_address=("localhost", PG_PORT),
        )
        tunnel.start()
        conn = psycopg.connect(
            host="localhost", port=tunnel.local_bind_port,
            user=PG_USER, password=PG_PASS, dbname=DATABASE, autocommit=True,
        )

        # Measure round-trip latency
        for i in range(3):
            wall_start = time.perf_counter()
            for _ in range(100):
                conn.execute("SELECT 1")
            wall = time.perf_counter() - wall_start
            print(f"  100 round-trips: {wall:.3f}s ({wall*10:.1f}ms/trip)")

        # Measure preflight-equivalent: 20 metadata queries
        clean_psycopg(conn)
        wall_start = time.perf_counter()
        for t in DEST_TABLES:
            conn.execute(f"SELECT EXISTS(SELECT 1 FROM pg_tables WHERE schemaname||'.'||tablename = '{t}')")
            conn.execute(f"SELECT count(*) FROM {t}")
        conn.execute("SELECT 1 FROM pg_tables WHERE schemaname='public' AND tablename='raw_data'")
        conn.execute("SELECT count(*) FROM public.raw_data")
        wall_preflight = time.perf_counter() - wall_start
        print(f"  Preflight (14 queries): {wall_preflight:.3f}s")

        # Compare: same preflight via psql (14 separate exec_commands)
        clean_psql(ssh)
        wall_start = time.perf_counter()
        for t in DEST_TABLES:
            run_psql(ssh, f"SELECT EXISTS(SELECT 1 FROM pg_tables WHERE schemaname||'.'||tablename = '{t}')")
            run_psql(ssh, f"SELECT count(*) FROM {t}")
        run_psql(ssh, "SELECT 1 FROM pg_tables WHERE schemaname='public' AND tablename='raw_data'")
        run_psql(ssh, "SELECT count(*) FROM public.raw_data")
        wall_preflight_psql = time.perf_counter() - wall_start
        print(f"  Same preflight via psql (14 exec_commands): {wall_preflight_psql:.3f}s")
        print(f"  Speedup: {wall_preflight_psql/wall_preflight:.1f}×")

        # Measure: batched preflight in ONE psql call
        wall_start = time.perf_counter()
        batch = ";".join(
            [f"SELECT EXISTS(SELECT 1 FROM pg_tables WHERE schemaname||'.'||tablename = '{t}')" for t in DEST_TABLES]
            + [f"SELECT count(*) FROM {t}" for t in DEST_TABLES]
            + ["SELECT 1 FROM pg_tables WHERE schemaname='public' AND tablename='raw_data'",
               "SELECT count(*) FROM public.raw_data"]
        )
        run_psql(ssh, batch)
        wall_preflight_batch = time.perf_counter() - wall_start
        print(f"  Batched preflight (1 psql call): {wall_preflight_batch:.3f}s")

        conn.close()
        tunnel.stop()
    except Exception as e:
        print(f"  psycopg3 test failed: {e}")

    # ── Summary ──
    psql_avg = sum(r["wall"] for r in results) / len(results)
    print(f"\n{'='*50}")
    print(f"SUMMARY")
    print(f"{'='*50}")
    print(f"psql avg wall: {psql_avg:.3f}s")

    ssh.close()
    print("\nDone.")


if __name__ == "__main__":
    main()
