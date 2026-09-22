import os
import subprocess
import sys
from pathlib import Path

DEFAULTS = [
    "--host", "localhost",
    "--postgres_port", "5432",
    "--user", "challenge",
    "--admin_database", "postgres",
]


def main():
    generator = Path(__file__).resolve().parent / "generate_database.py"

    env = os.environ.copy()
    env.setdefault("PG_KAGGLE_CHALLENGE_PASS", "challenge")

    args = sys.argv[1:] if sys.argv[1:] else ["--rows", "100000"]
    subprocess.run([sys.executable, str(generator)] + DEFAULTS + args, env=env)
