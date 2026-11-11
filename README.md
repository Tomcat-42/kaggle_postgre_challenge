# PostgreSQL Data Pipeline Optimization

5.1x faster JSONB expansion, holding from 10^6 through 10^7 source rows.

Based on [PostgreSQL Data Manager](https://github.com/igorsiecz/kaggle_postgre_challenge) (see upstream for application details and original codebase).

Paper: [`doc/build/main.pdf`](doc/build/main.pdf) | Writeup: [`submission/writeup.md`](submission/writeup.md)

## Quick start

Requires [Podman](https://podman.io/) (or Docker) and [uv](https://docs.astral.sh/uv/).

```bash
podman compose -f container/compose.yaml up -d   # 1. start PostgreSQL + SSH
uv sync                                           # 2. install dependencies
sudo -v && uv run bench                           # 3. run benchmark
```

Container: user `challenge`, password `challenge`, SSH port 2222, PG port 5432.

## Results

| Source rows | Baseline | Optimized | Speedup |
|---|---|---|---|
| 10K | 1.8 s | 0.7 s | 2.6x |
| 100K | 17.0 s | 4.6 s | 3.7x |
| 1M | 179.8 s | 35.5 s | **5.1x** |
| 5M | 826.0 s | 157.8 s | **5.2x** |
| 10M | 1628.2 s | 318.3 s | **5.1x** |

Cold cache (page cache dropped + PG restarted before each run), median of 3 runs.

## Commands

| Command | Description |
|---|---|
| `uv run pgdm` | Launch the GUI |
| `uv run bench` | Run the full benchmark |
| `uv run test` | Run the test suite |
| `cd doc && make all` | Build the paper |

## License

[Apache License 2.0](LICENSE)
