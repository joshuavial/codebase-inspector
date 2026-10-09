"""Viewer label placement and the render-image key, exercised in node."""

import subprocess
from pathlib import Path


def test_label_placement_and_render_key():
    root = Path(__file__).resolve().parents[1]
    proc = subprocess.run(
        ["node", str(Path(__file__).parent / "layout_check.js")],
        cwd=root, capture_output=True, text=True,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_drawer_keeps_restored_sections_on_the_same_view():
    root = Path(__file__).resolve().parents[1]
    proc = subprocess.run(
        ["node", str(Path(__file__).parent / "drawer_open_check.js")],
        cwd=root, capture_output=True, text=True,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
