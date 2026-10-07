import subprocess

import pytest


def _git(cwd, *args):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


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
