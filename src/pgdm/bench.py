"""Entry point for `uv run bench`."""
import runpy
import sys
from pathlib import Path


def main():
    script = Path(__file__).resolve().parents[2].parent / "tool" / "local_benchmark.py"
    sys.argv[0] = str(script)
    runpy.run_path(str(script), run_name="__main__")
