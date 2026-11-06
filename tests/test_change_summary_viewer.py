"""Agent summaries render as text in the comparison viewer."""

import subprocess
from pathlib import Path


def test_change_summary_viewer():
    script = Path(__file__).with_name("change_summary_check.js")
    result = subprocess.run(["node", str(script)], capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
