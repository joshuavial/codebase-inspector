import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest

# A git or gh call that waits on a credential prompt must fail the test, not the job.
SUBPROCESS_TIMEOUT = 120


def _python_standin(name):
    """`name.py` on PATH ahead of a real `name.exe`. None when the real program comes first."""
    if not name or any(sep in name for sep in ("/", "\\")):
        return None
    for directory in os.environ.get("PATH", "").split(os.pathsep):
        if not directory:
            continue
        base = Path(directory)
        script = base / f"{name}.py"
        if script.is_file():
            return str(script)
        for ext in (".exe", ".com", ".bat", ".cmd"):
            if (base / f"{name}{ext}").is_file():
                return None
        if (base / name).is_file():
            return None
    return None


def _rewrite_argv(argv):
    """Run a Windows test stand-in. CreateProcess ignores a shebang and PATHEXT skips `name.py`."""
    if sys.platform != "win32" or isinstance(argv, (str, bytes)) or not argv:
        return argv
    try:
        prog = os.fspath(argv[0])
    except TypeError:
        return argv
    if not isinstance(prog, str):
        return argv
    rest = list(argv[1:])
    if prog.lower().endswith(".py"):
        return [sys.executable, prog, *rest]
    script = _python_standin(prog)
    if script:
        return [sys.executable, script, *rest]
    return argv


_REAL_RUN = subprocess.run
_REAL_POPEN = subprocess.Popen


def _run_with_timeout(argv, *args, **kwargs):
    argv = _rewrite_argv(argv)
    if kwargs.get("timeout") is None:
        kwargs["timeout"] = SUBPROCESS_TIMEOUT
    return _REAL_RUN(argv, *args, **kwargs)


def _popen_rewritten(argv, *args, **kwargs):
    return _REAL_POPEN(_rewrite_argv(argv), *args, **kwargs)


def write_standin(directory, name, body):
    """A `name` on PATH. POSIX runs the shebang; Windows runs `name.py` via sys.executable."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    if not body.startswith("#!"):
        body = "#!/usr/bin/env python3\n" + body
    if sys.platform == "win32":
        path = directory / f"{name}.py"
        path.write_text(body, encoding="utf-8", newline="\n")
        return path
    path = directory / name
    path.write_text(body, encoding="utf-8", newline="\n")
    path.chmod(path.stat().st_mode | stat.S_IEXEC)
    return path


def _git(cwd, *args):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


@pytest.fixture(autouse=True)
def subprocess_defaults(monkeypatch):
    """Bound every subprocess.run in a test, and let Windows stand-ins be real programs."""
    monkeypatch.setattr(subprocess, "run", _run_with_timeout)
    monkeypatch.setattr(subprocess, "Popen", _popen_rewritten)


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
        # Working-tree hashes are raw bytes. Keep LF so they match the goldens.
        _git(root, "config", "core.autocrlf", "false")
        for rel, content in files.items():
            path = root / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8", newline="\n")
        _git(root, "add", "-A")
        _git(
            root,
            "-c", "user.name=test", "-c", "user.email=test@example.com",
            "-c", "commit.gpgsign=false",
            "commit", "-q", "-m", "fixture",
        )
        return root

    return make
