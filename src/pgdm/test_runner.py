"""Entry point for `uv run test`."""
import sys
import pytest


def main():
    sys.exit(pytest.main(["-v"]))
