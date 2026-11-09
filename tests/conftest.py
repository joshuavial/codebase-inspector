import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path

import pytest

_TESTS_DIR = Path(__file__).resolve().parent
if str(_TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(_TESTS_DIR))

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


def _interpreter():
    """The real interpreter. A venv python.exe only launches it, so killing the venv leaves the script alive."""
    return getattr(sys, "_base_executable", None) or sys.executable


def _git_argv(argv, prog):
    """Windows Git checks out CRLF unless this invocation says otherwise. A new clone does not copy the repo config."""
    if Path(prog).name.lower() not in ("git", "git.exe"):
        return argv
    rest = list(argv[1:])
    if rest[:2] == ["-c", "core.autocrlf=false"]:
        return argv
    return [prog, "-c", "core.autocrlf=false", *rest]


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
    argv = _git_argv(argv, prog)
    prog = os.fspath(argv[0])
    rest = list(argv[1:])
    python = _interpreter()
    if prog.lower().endswith(".py"):
        return [python, prog, *rest]
    script = _python_standin(prog)
    if script:
        return [python, script, *rest]
    return argv


_REAL_RUN = subprocess.run
_REAL_POPEN = subprocess.Popen
_REAL_WRITE_TEXT = Path.write_text


def _write_text_lf(self, data, encoding=None, errors=None, newline=None):
    """Working-tree hashes are raw bytes. Windows text mode would store CRLF and miss the goldens."""
    if newline is None:
        newline = "\n"
    return _REAL_WRITE_TEXT(self, data, encoding=encoding, errors=errors, newline=newline)


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
    if sys.platform == "win32":
        monkeypatch.setattr(Path, "write_text", _write_text_lf)


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


# Shared probe for Playwright browser availability across viewer tests.
_PLAYWRIGHT_RUNNER_CACHE = None

_PROBE_CODE = (
    "import sys\n"
    "try:\n"
    "    from playwright.sync_api import sync_playwright\n"
    "except Exception as exc:\n"
    "    print(f'IMPORT_ERROR: {exc}')\n"
    "    sys.exit(1)\n"
    "try:\n"
    "    with sync_playwright() as p:\n"
    "        try:\n"
    "            b = p.chromium.launch(headless=True)\n"
    "            b.close()\n"
    "            print('OK:chromium')\n"
    "            sys.exit(0)\n"
    "        except Exception as err_default:\n"
    "            try:\n"
    "                b = p.chromium.launch(channel='chrome', headless=True)\n"
    "                b.close()\n"
    "                print('OK:chrome')\n"
    "                sys.exit(0)\n"
    "            except Exception as err_chrome:\n"
    "                print(f'LAUNCH_ERROR: default: {err_default}; chrome: {err_chrome}')\n"
    "                sys.exit(2)\n"
    "except Exception as exc:\n"
    "    print(f'PLAYWRIGHT_ERROR: {exc}')\n"
    "    sys.exit(3)\n"
)


def find_playwright_runner(use_cache=True):
    """Find a command prefix capable of launching a headless browser via Playwright.

    Returns (runner_argv, skip_reason).
    runner_argv is a list of str (e.g. ['/path/to/python'] or ['uvx', '--from', 'playwright', 'python']).
    skip_reason is an informative string if no working runner was found, else None.
    """
    global _PLAYWRIGHT_RUNNER_CACHE
    if os.environ.get("CBI_TEST_NO_BROWSER") == "1":
        return (None, "Playwright browser binaries are not installed (chromium_headless_shell and system Chrome unavailable)")
    if use_cache and _PLAYWRIGHT_RUNNER_CACHE is not None:
        return _PLAYWRIGHT_RUNNER_CACHE

    seen = set()
    candidates = []

    # 1. Candidate python interpreters
    for candidate in (
        sys.executable,
        "/opt/homebrew/bin/python3",
        "/usr/local/bin/python3",
        "/usr/bin/python3",
        shutil.which("python3"),
        shutil.which("python"),
    ):
        if not candidate or candidate in seen:
            continue
        p = Path(candidate)
        if p.is_file():
            seen.add(candidate)
            candidates.append([candidate])

    # 2. uvx candidate
    uvx = shutil.which("uvx")
    if uvx:
        candidates.append([uvx, "--from", "playwright", "python"])

    launch_error = None
    has_playwright_import = False

    for cmd in candidates:
        try:
            proc = _REAL_RUN(
                _rewrite_argv(cmd + ["-c", _PROBE_CODE]),
                capture_output=True,
                text=True,
                timeout=15,
            )
            if proc.returncode == 0:
                _PLAYWRIGHT_RUNNER_CACHE = (cmd, None)
                return _PLAYWRIGHT_RUNNER_CACHE
            elif proc.returncode == 2:
                has_playwright_import = True
                launch_error = proc.stdout.strip() or proc.stderr.strip()
            elif proc.returncode != 1:
                out = (proc.stdout + proc.stderr).strip()
                if any(m in out for m in ("LAUNCH_ERROR", "BrowserType.launch", "Executable doesn't exist")):
                    has_playwright_import = True
                    launch_error = out
        except Exception:
            continue

    if has_playwright_import:
        reason = (
            "Playwright browser binaries are not installed (chromium_headless_shell and system Chrome unavailable)"
        )
        if launch_error:
            reason += f": {launch_error}"
    else:
        reason = "playwright is not installed (no Python interpreter with playwright or uvx found)"

    _PLAYWRIGHT_RUNNER_CACHE = (None, reason)
    return _PLAYWRIGHT_RUNNER_CACHE


def require_playwright():
    """Return runner argv prefix or skip the current test."""
    runner, reason = find_playwright_runner()
    if runner is None:
        pytest.skip(reason)
    return runner


def check_playwright_proc(proc):
    """Check a completed subprocess that ran a Playwright script.

    Gracefully skips if browser launch failed due to missing browser binaries.
    """
    if proc.returncode != 0:
        err = (proc.stderr or "") + (proc.stdout or "")
        markers = (
            "BrowserType.launch",
            "Executable doesn't exist",
            "playwright install",
            'channel "chrome" is not found',
            "browserType.launch: Executable doesn't exist",
            "LAUNCH_ERROR",
        )
        if any(marker in err for marker in markers):
            pytest.skip(f"Playwright browser launch failed: {err.strip()}")
        assert proc.returncode == 0, proc.stdout + proc.stderr


@pytest.fixture
def playwright_runner():
    """Pytest fixture returning the command prefix to run Playwright with a headless browser."""
    return require_playwright()


@pytest.fixture
def check_playwright():
    """Pytest fixture providing check_playwright_proc."""
    return check_playwright_proc

