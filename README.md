# PostgreSQL Data Pipeline Optimization

5.1x faster JSONB expansion for [PostgreSQL Data Manager](https://github.com/igorsiecz/kaggle_postgre_challenge), holding from 10^6 through 10^7 source rows.

Paper: [`doc/build/main.pdf`](doc/build/main.pdf)

## Reproduce (3 commands)

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
cd doc && make all    # Output: doc/build/main.pdf
```

## Repository structure

```
src/pgdm/services/postgres_service.py  Expansion logic (baseline + optimized)
src/pgdm/app.py                        GUI application
asset/sql/                             Six expansion recipes (unchanged)
tool/generate_database.py              Dataset generator (unchanged)
tool/local_benchmark.py                Benchmark with cold-cache protocol
container/                             PostgreSQL 17 + SSH container
doc/src/                               Paper source (LaTeX)
results/                               Benchmark data
submission/                            Paper PDF, writeup, figures
test/                                  Test suite
```

## License

[Apache License 2.0](LICENSE)
