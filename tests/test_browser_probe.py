"""Unit tests for the shared Playwright browser availability probe and fallback."""

import subprocess
from unittest.mock import MagicMock

import pytest

from conftest import (
    _PROBE_CODE,
    check_playwright_proc,
    find_playwright_runner,
    require_playwright,
)


def test_find_playwright_runner_detects_available_browser(monkeypatch):
    monkeypatch.delenv("CBI_TEST_NO_BROWSER", raising=False)
    runner, reason = find_playwright_runner(use_cache=True)
    if runner is not None:
        assert isinstance(runner, list)
        assert len(runner) >= 1
        assert reason is None
    else:
        assert "not installed" in reason or "unavailable" in reason


def test_find_playwright_runner_skips_when_browser_binaries_absent(monkeypatch):
    monkeypatch.delenv("CBI_TEST_NO_BROWSER", raising=False)
    def fake_run(argv, *args, **kwargs):
        return subprocess.CompletedProcess(
            args=argv,
            returncode=2,
            stdout="LAUNCH_ERROR: default: Executable doesn't exist; chrome: channel chrome not found",
            stderr="",
        )

    monkeypatch.setattr("conftest._REAL_RUN", fake_run)
    runner, reason = find_playwright_runner(use_cache=False)
    assert runner is None
    assert "Playwright browser binaries are not installed" in reason
    assert "chromium_headless_shell and system Chrome unavailable" in reason


def test_find_playwright_runner_skips_when_playwright_not_installed(monkeypatch):
    monkeypatch.delenv("CBI_TEST_NO_BROWSER", raising=False)
    def fake_run(argv, *args, **kwargs):
        return subprocess.CompletedProcess(
            args=argv,
            returncode=1,
            stdout="IMPORT_ERROR: No module named 'playwright'",
            stderr="",
        )

    monkeypatch.setattr("conftest._REAL_RUN", fake_run)
    runner, reason = find_playwright_runner(use_cache=False)
    assert runner is None
    assert "playwright is not installed" in reason


def test_require_playwright_calls_skip_when_unavailable(monkeypatch):
    monkeypatch.setattr("conftest.find_playwright_runner", lambda use_cache=True: (None, "no browser available"))
    with pytest.raises(pytest.skip.Exception, match="no browser available"):
        require_playwright()


def test_check_playwright_proc_skips_on_missing_executable():
    proc = subprocess.CompletedProcess(
        args=["python", "test.py"],
        returncode=1,
        stdout="",
        stderr="playwright._impl._errors.Error: BrowserType.launch: Executable doesn't exist at /path/to/shell",
    )
    with pytest.raises(pytest.skip.Exception, match="Playwright browser launch failed"):
        check_playwright_proc(proc)


def test_check_playwright_proc_skips_on_missing_chrome_channel():
    proc = subprocess.CompletedProcess(
        args=["python", "test.py"],
        returncode=1,
        stdout="",
        stderr="playwright._impl._errors.Error: channel \"chrome\" is not found",
    )
    with pytest.raises(pytest.skip.Exception, match="Playwright browser launch failed"):
        check_playwright_proc(proc)


def test_check_playwright_proc_asserts_on_actual_test_failure():
    proc = subprocess.CompletedProcess(
        args=["python", "test.py"],
        returncode=1,
        stdout="assert 1 == 0",
        stderr="AssertionError: expected value mismatch",
    )
    with pytest.raises(AssertionError):
        check_playwright_proc(proc)


def test_check_playwright_proc_passes_on_success():
    proc = subprocess.CompletedProcess(
        args=["python", "test.py"],
        returncode=0,
        stdout="ok",
        stderr="",
    )
    check_playwright_proc(proc)
