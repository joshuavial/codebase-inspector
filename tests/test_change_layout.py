"""Comparison diagram state and accessible layout regression checks."""

import subprocess
from pathlib import Path


def test_change_layout():
    script = Path(__file__).with_name("change_layout_check.js")
    result = subprocess.run(["node", str(script)], capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
