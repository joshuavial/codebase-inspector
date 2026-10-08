"""The release job pastes one changelog section into the draft."""

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]


def _notes():
    path = ROOT / ".github" / "changelog_notes.py"
    spec = importlib.util.spec_from_file_location("changelog_notes", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_section_is_one_version():
    text = """
# Changelog

## [Unreleased]

- later

## [0.1.0] - 2026-10-09

First public release.

## [0.0.1] - 2026-01-01

- old
"""
    body = _notes().section(text, "v0.1.0")
    assert body.startswith("## [0.1.0] - 2026-10-09")
    assert "First public release." in body
    assert "0.0.1" not in body
    assert "Unreleased" not in body


def test_missing_section_exits():
    with pytest.raises(SystemExit, match="no section for 9.9.9"):
        _notes().section("## [0.1.0] - 2026-10-09\n\nHi\n", "9.9.9")


def test_repo_changelog_has_the_release_notes():
    body = _notes().section((ROOT / "CHANGELOG.md").read_text(), "0.1.0")
    assert "cbi scan" in body
    assert "unsigned" in body
    assert "Python" in body
