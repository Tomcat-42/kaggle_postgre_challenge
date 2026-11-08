# Submission: PostgreSQL Data Pipeline Optimization Challenge

**Author:** Pablo Alessandro Santos Hugen, UFRGS
**Base repository:** [igorsiecz/kaggle_postgre_challenge](https://github.com/igorsiecz/kaggle_postgre_challenge)
**Paper:** `doc/build/main.pdf`

## Result

| Source rows | Baseline | Optimized | Speedup |
|---|---|---|---|
| 10K | 0.95 s | 1.04 s | 0.9x |
| 100K | 8.1 s | 4.5 s | 1.8x |
| 1M | 175 s | 35 s | 5.0x |

Speedup grows with scale. All integrity guarantees preserved. Checkpoint-and-resume enabled.

## Setup

Requirements: Python 3.10+, PostgreSQL 17, SSH server, `psql` in PATH.

### Option A: Container (local development)

```bash
git clone https://github.com/igorsiecz/kaggle_postgre_challenge.git
cd kaggle_postgre_challenge

# Start PostgreSQL + SSH container
podman-compose -f container/compose.yaml up -d

# Install Python dependencies
uv sync   # or: pip install -e .
```

### Option B: Slurm cluster (benchmark reproduction)

```bash
# On the login node
git clone <this-repo> ~/kaggle_postgre_challenge
cd ~/kaggle_postgre_challenge

# PostgreSQL is built from source automatically by the benchmark script.
# Python dependencies are installed via uv (auto-installed if missing).
```

## Generate the dataset

```bash
export PG_KAGGLE_CHALLENGE_PASS=challenge

# Container (port 5432, SSH port 2222)
.venv/bin/python tool/generate_database.py \
    --rows 100000 --host localhost --ssh_port 2222 --ssh_user challenge \
    --postgres_port 5432 --user challenge --admin_database postgres

# Cluster (direct, no SSH tunnel needed)
.venv/bin/python tool/generate_database.py \
    --rows 100000 --host localhost --postgres_port 15432 \
    --user challenge --user_pass challenge --admin_database postgres
```

Replace `--rows` with the desired dataset size. The generator is deterministic.

## Run the expansion

```bash
# Headless profiling (prints full timing report)
.venv/bin/python tool/profile_expansion.py --clean
```

## Run benchmarks

### Local (single scale)

```bash
.venv/bin/python tool/profile_expansion.py --clean
```

### Cluster (full benchmark, reproducible)

```bash
# Quick pipeline test (~5 min)
sbatch --time=00:30:00 tool/slurm_benchmark.sh --quick

# Full benchmark: 3 runs x 8 scales, 10K to 10M (~12 hours)
sbatch tool/slurm_benchmark.sh
```

The Slurm script:
- Allocates an exclusive node
- Installs PostgreSQL from source (cached after first run)
- Auto-tunes `shared_buffers` to 25% of available RAM
- Drops OS page cache and restarts PostgreSQL between runs
- Reports median, min, max across 3 measured runs per configuration
- Verifies row-count correctness after every run

Results are saved to `results/run_<jobid>/`.

## Run tests

```bash
.venv/bin/python -m pytest test/ -v
```

## Build the paper

```bash
cd doc && make all
# Output: doc/build/main.pdf
```
