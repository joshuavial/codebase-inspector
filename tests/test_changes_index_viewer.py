"""Concept navigation and collapsed evidence in the comparison reading column."""
import subprocess
from pathlib import Path


def test_changes_index_viewer():
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run(["node", "tests/changes_index_check.js"], cwd=root, capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
