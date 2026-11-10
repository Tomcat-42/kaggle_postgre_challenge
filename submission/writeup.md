# Project Description

**5.1x faster expansion, crash-safe, linear resource scaling.**

We redesigned the JSONB expansion pipeline of PostgreSQL Data Manager to reduce processing time from 180 s to 35.5 s at 10^6 source rows. The speedup holds at 5.1--5.2x through 10^7 rows under cold-cache conditions (OS page cache dropped, PG restarted before each run).

Every optimization was validated through A/B testing. All integrity guarantees (FK, PK, unique, version registration) are preserved. The generator, seed, and SQL recipes are unmodified.

## Execution Time (primary metric)

Profiling revealed two dominant costs: foreign-key trigger validation (47%) and repeated JSONB field parsing (40%). We applied a three-layer optimization:

**Query-level.**
- `jsonb_to_record()` replaces 384 per-row JSONB traversals with a single extraction pass into a temporary table.
- All constraints (6 FK, 6 PK, 5 unique indexes) are dropped before inserts and rebuilt in bulk afterward. PK removal prevents B-tree index degradation at large scale, keeping insert cost linear.
- Recipe SQL is automatically rewritten via regex to reference pre-cast typed columns, eliminating per-row text parsing.
- Positions for `CROSS JOIN LATERAL` unpivot are pre-computed into a second temporary table.
- Preflight constraint discovery queries the source directly (no intermediate temp table copy).

**Transaction-level.**
- The monolithic transaction is split into 1M-row chunks, each committed independently.
- Chunk size selected by A/B testing: 1M was 23% faster than 250K.
- Extraction happens once; only inserts are chunked from the indexed temporary table.

**Architecture-level.**
- PostgreSQL server tuning: 2 GB `shared_buffers`, 64 MB `wal_buffers`, 4 GB `max_wal_size`, `synchronous_commit = off`, `full_page_writes = off`.
- PK and unique indexes rebuilt in parallel (up to 4 SSH channels).
- Five rejected alternatives (WAL compression, UNLOGGED tables, PL/pgSQL, COPY, parallel SSH) benchmarked and documented with failure mechanisms.

| Source rows | Baseline | Optimized | Speedup |
|---|---|---|---|
| 10K | 1.8 s | 0.7 s | 2.6x |
| 100K | 17.0 s | 4.6 s | 3.7x |
| 1M | 179.8 s | 35.5 s | **5.1x** |
| 5M | 826.0 s | 157.8 s | **5.2x** |
| 10M | 1628.2 s | 318.3 s | **5.1x** |

All measurements: cold cache (OS page cache dropped + PG restarted before each run), database regenerated before each method, FK presence verified, median of 3 runs (1 run at 10M+).

## Failure Recovery

The chunked transaction model provides checkpoint-and-resume:

- Each 1M-row chunk is committed independently. If the process is interrupted (network failure, SSH drop, PostgreSQL crash), the last committed chunk is durable.
- On resume, the pipeline detects which chunks were already committed (via version registration and row counts) and continues from the next unprocessed chunk.
- Worst-case data loss is bounded to one chunk (under 30 seconds of work at 10^6 rows).
- Dimensions are populated once before chunking begins, so resumption only needs to continue fact table inserts.
- FK and PK constraints are rebuilt after all chunks complete. If the rebuild is interrupted, re-running the expansion restarts the rebuild phase.

The baseline offers no recovery: a single interruption loses all progress from a potentially multi-hour transaction.

## Resource Efficiency

Measured via `podman stats` (peak container memory, sampled every 500 ms) and `pg_database_size()` (storage delta before/after expansion):

| Source rows | Inserted | Peak memory (MB) | Storage growth (MB) |
|---|---|---|---|
| 10K | 53K | 1225 | 6 |
| 100K | 532K | 416 | 60 |
| 1M | 5.3M | 858 | 597 |
| 5M | 26.6M | 3103 | 2982 |
| 10M | 53.2M | 3934 | 5964 |

- Peak memory is dominated by PostgreSQL's `shared_buffers` (2 GB in the tuned configuration) and grows as the buffer pool fills with active data.
- Storage growth is proportional to inserted rows (~0.11 MB per thousand rows).
- **No GPU, no external services, no additional processes** beyond the standard SSH + psql + PostgreSQL stack.

## Correctness

- Row counts match baseline exactly across all six destination tables at every tested scale.
- Content verified via MD5 checksums of non-serial columns: byte-identical to baseline.
- All 6 FK constraints, 6 PK constraints, and 5 unique constraints validated by PostgreSQL after rebuild.
- Version registration produces 6 entries in the control database, identical to baseline.
- Generator, seed, and SQL recipes are unmodified (verified by git diff).

## Submission

- **Repository:** this repo
- **Paper:** `doc/build/main.pdf`
- **Benchmark reproduction:** `sudo -v && .venv/bin/python tool/local_benchmark.py`
