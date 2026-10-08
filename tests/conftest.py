import subprocess

import pytest


def _git(cwd, *args):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


@pytest.fixture(autouse=True)
def answer_cache(tmp_path, monkeypatch):
    """Keep every test's answer cache in its own temp dir, never the user's."""
    path = tmp_path / "answer-cache"
    monkeypatch.setenv("CBI_CACHE_DIR", str(path))
    monkeypatch.setenv("CBI_SNAPSHOT_DIR", str(tmp_path / "snapshots"))
    # prime and status look for a newer release. Tests opt out so they stay offline.
    monkeypatch.setenv("CBI_NO_UPDATE_CHECK", "1")
    return path


@pytest.fixture
def make_repo(tmp_path):
    """Build a git repo from {relative path: content} and commit it. Returns its path."""

    def make(files, name="repo"):
        root = tmp_path / name
        root.mkdir()
        _git(root, "init", "-q", "-b", "main")
        for rel, content in files.items():
            path = root / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content)
        _git(root, "add", "-A")
        _git(
            root,
            "-c", "user.name=test", "-c", "user.email=test@example.com",
            "-c", "commit.gpgsign=false",
            "commit", "-q", "-m", "fixture",
        )
        return root

    return make
