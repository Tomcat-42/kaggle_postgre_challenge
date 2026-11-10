# PostgreSQL Data Pipeline Optimization

5.1x faster JSONB expansion, holding from 10^6 through 10^7 source rows.

Based on [PostgreSQL Data Manager](https://github.com/igorsiecz/kaggle_postgre_challenge) (see upstream repo for application details, usage, and the original codebase).

Paper: [`doc/build/main.pdf`](doc/build/main.pdf) | Writeup: [`submission/writeup.md`](submission/writeup.md)

## Reproducing

Requires: [Podman](https://podman.io/) (or Docker) and [uv](https://docs.astral.sh/uv/).

```bash
# 1. Start PostgreSQL + SSH container
podman compose -f container/compose.yaml up -d
# (or: docker compose -f container/compose.yaml up -d)

# 2. Install Python dependencies
uv sync

# 3. Run the benchmark
sudo -v && .venv/bin/python tool/local_benchmark.py
```

The benchmark generates datasets from 10K to 50M rows, runs both baseline and optimized expansions under cold-cache conditions (page cache dropped, PG restarted before each run), and reports the median of 3 measured runs. Requires `sudo` for page cache eviction. Results are saved to `results/local/`.

Container credentials: user `challenge`, password `challenge`, SSH port 2222, PG port 5432.

## What changed

**No changes** to the dataset generator, its fixed seed, or the six SQL recipe files.

**Application code** (`src/pgdm/services/postgres_service.py`, `src/pgdm/app.py`): the Expand operation calls a new optimized method that extracts JSONB fields once via `jsonb_to_record()`, drops all constraints (FK, PK, unique) before inserts, inserts in 1M-row chunks, and rebuilds constraints in parallel afterward.

**PostgreSQL server**: the benchmark's tuned configuration sets `shared_buffers = 2GB`, `work_mem = 256MB`, `wal_buffers = 64MB`, `max_wal_size = 4GB`, `synchronous_commit = off`, `full_page_writes = off`. However, the optimization works on stock PG config too (28.9 s at 1M vs 35.5 s tuned). The speedup comes from the SQL redesign, not from server tuning.

## Results

| Source rows | Baseline | Optimized | Speedup |
|---|---|---|---|
| 10K | 1.8 s | 0.7 s | 2.6x |
| 100K | 17.0 s | 4.6 s | 3.7x |
| 1M | 179.8 s | 35.5 s | **5.1x** |
| 5M | 826.0 s | 157.8 s | **5.2x** |
| 10M | 1628.2 s | 318.3 s | **5.1x** |

## Tests

```bash
.venv/bin/python -m pytest test/ -v
```

## Build the paper

```bash
cd doc && make all
```

## License

[Apache License 2.0](LICENSE)
