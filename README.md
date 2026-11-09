# PostgreSQL Data Pipeline Optimization

Optimized expansion pipeline for [PostgreSQL Data Manager](https://github.com/igorsiecz/kaggle_postgre_challenge).
Reduces the measured processing time of the JSONB-to-relational expansion by up to 5× through query redesign, transaction chunking, and server tuning.

Paper: [`doc/build/main.pdf`](doc/build/main.pdf)

## Requirements

- Python 3.10+
- PostgreSQL 17 with `psql`, `pg_dump`, `pg_restore`
- SSH server on the PostgreSQL host
- [uv](https://docs.astral.sh/uv/) (recommended) or pip

## Quick start

```bash
# 1. Start PostgreSQL + SSH (container)
podman-compose -f container/compose.yaml up -d

# 2. Install dependencies
uv sync

# 3. Generate the dataset (100K rows)
export PG_KAGGLE_CHALLENGE_PASS=challenge
.venv/bin/python tool/generate_database.py \
    --rows 100000 --host localhost --postgres_port 5432 \
    --user challenge --admin_database postgres

# 4. Run the expansion
.venv/bin/python -m pgdm
```

Connect to `localhost:2222` (SSH) / `localhost:5432` (PostgreSQL) with user `challenge`, password `challenge`.
Open `kaggle_challenge` → `raw_data` → Expand.

## Reproduce the benchmark

### Local (with container)

```bash
.venv/bin/python tool/local_benchmark.py
```

Runs baseline (stock config) and optimized (tuned config) at 100K and 1M rows.
Drops OS page cache and restarts PostgreSQL between runs.
Reports median of 3 measured runs after 1 warmup.

Results are saved to `results/local/definitive_benchmark.json`.

### Cluster (Slurm)

```bash
sbatch -p <partition> tool/slurm_benchmark.sh 10K 100K 1M 10M
```

Accepts scale arguments: `10K`, `50K`, `100K`, `250K`, `500K`, `1M`, `5M`, `10M`, `50M`, `100M`, `300M`.
Installs PostgreSQL from source if not available.
Auto-tunes `shared_buffers` to 25% of RAM.
Uses local NVMe (`/ssd` or `/scratch`) for database storage.

Results are saved to `results/run_<jobid>/`.

## Tests

```bash
.venv/bin/python -m pytest test/ -v
```

## Build the paper

```bash
cd doc && make all    # Output: doc/build/main.pdf
```

## Repository structure

```
src/pgdm/
  services/postgres_service.py    Core expansion logic (baseline + optimized)
  app.py                          GUI application
asset/sql/                        Six expansion recipes (unchanged)
tool/
  generate_database.py            Deterministic dataset generator (unchanged)
  local_benchmark.py              Local benchmark with cold-cache protocol
  slurm_benchmark.sh              Cluster benchmark (Slurm)
container/                        PostgreSQL 17 + SSH container
doc/src/                          Paper source (LaTeX)
results/local/                    Benchmark data
test/                             Test suite (6 tests)
```

## License

[Apache License 2.0](LICENSE)
