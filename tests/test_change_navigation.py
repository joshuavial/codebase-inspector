"""Comparison navigation keeps the snapshot, scope and explanation in sync."""

import subprocess
from pathlib import Path


def test_change_navigation():
    result = subprocess.run(["node", str(Path(__file__).with_name("change_navigation_check.js"))],
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
