# Project Description

We redesigned the JSONB expansion pipeline of PostgreSQL Data Manager to achieve a **5× speedup** at 10⁶ source rows (166 s → 33 s) while preserving all integrity guarantees and adding checkpoint-and-resume for failure recovery.

## Approach

Profiling revealed two dominant costs in the baseline: foreign-key trigger validation (47%) and repeated JSONB field parsing (40%). We applied a three-layer optimization:

**Query-level.** A single `jsonb_to_record()` call replaces 384 per-row field traversals. FK constraints and unique indexes are dropped before inserts and rebuilt in bulk. Recipe SQL is automatically rewritten to reference pre-cast typed columns.

**Transaction-level.** The monolithic transaction is split into 250K-row chunks, each committed independently. Extraction happens once; only inserts are chunked. Interrupted operations resume from the last committed chunk.

**Architecture-level.** PostgreSQL server parameters are tuned for the workload (shared_buffers, wal_buffers, max_wal_size).

Five alternative approaches (WAL compression, UNLOGGED tables, PL/pgSQL procedures, COPY loading, parallel SSH) were benchmarked and found slower.

## Results

| Source rows | Baseline | Optimized | Speedup |
|---|---|---|---|
| 100K | 17.3 s | 4.2 s | 4.1× |
| 1M | 165.9 s | 33.4 s | **5.0×** |

- Speedup increases with dataset size
- Peak RAM unchanged (256 MB)
- Temporary storage: 250 MB at 1M rows (proportional to source)
- Checkpoint granularity: 250K rows
- All FK constraints, unique constraints, and version registration preserved
- Row counts verified to match baseline across all six destination tables

## Submission

- **Repository:** [this repo]
- **Commit:** [current HEAD]
- **Paper:** `doc/build/main.pdf`
