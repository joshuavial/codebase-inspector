"""Update check: cached GitHub release, with a fake fetch and one local server."""

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from cbi import update_check
from cbi.cli import main

LINE = "A newer cbi (0.2.0) is available: https://github.com/joshuavial/codebase-inspector/releases/tag/v0.2.0"
DAY = update_check.DAY


def _enable(monkeypatch):
    monkeypatch.delenv("CBI_NO_UPDATE_CHECK", raising=False)
    monkeypatch.delenv("CI", raising=False)


def _body(tag="v0.2.0", **extra):
    payload = {
        "tag_name": tag,
        "html_url": f"https://github.com/joshuavial/codebase-inspector/releases/tag/{tag}",
        "draft": False,
        "prerelease": False,
    }
    payload.update(extra)
    return payload


def _fetch(payload, status=200, etag='"abc"', conditional=False):
    calls = []

    def fetch(url, got_etag, timeout):
        calls.append({"url": url, "etag": got_etag, "timeout": timeout})
        if conditional and got_etag:
            return 304, got_etag, None
        return status, etag, payload

    return fetch, calls


def test_newer_release_is_cached_for_a_day(monkeypatch):
    _enable(monkeypatch)
    fetch, calls = _fetch(_body())
    assert update_check.notice(fetch=fetch, now=1_000, current="0.1.0") == LINE
    assert update_check.notice(fetch=fetch, now=1_000 + DAY - 1, current="0.1.0") == LINE
    assert len(calls) == 1
    assert calls[0]["url"] == update_check.RELEASES_URL
    assert calls[0]["timeout"] == 2
    assert calls[0]["etag"] is None
    saved = json.loads(update_check.cache_file().read_text(encoding="utf-8"))
    assert saved["latest"]["version"] == "0.2.0"
    assert saved["etag"] == '"abc"'


def test_same_and_older_releases_say_nothing(monkeypatch):
    _enable(monkeypatch)
    fetch, _calls = _fetch(_body("v0.1.0"))
    assert update_check.notice(fetch=fetch, now=1_000, current="0.1.0") is None
    fetch, _calls = _fetch(_body("v0.0.9"))
    assert update_check.notice(fetch=fetch, now=2_000 + DAY, current="0.1.0") is None


def test_numeric_semver_orders_double_digits(monkeypatch):
    _enable(monkeypatch)
    fetch, _calls = _fetch(_body("v0.10.0"))
    line = update_check.notice(fetch=fetch, now=1_000, current="0.9.0")
    assert line == (
        "A newer cbi (0.10.0) is available: "
        "https://github.com/joshuavial/codebase-inspector/releases/tag/v0.10.0"
    )


def test_prerelease_and_draft_are_ignored(monkeypatch):
    _enable(monkeypatch)
    for index, flag in enumerate(("prerelease", "draft")):
        fetch, calls = _fetch(_body("v9.0.0", **{flag: True}))
        assert update_check.notice(fetch=fetch, now=5_000 + index * DAY, current="0.1.0") is None
        assert len(calls) == 1
        saved = json.loads(update_check.cache_file().read_text(encoding="utf-8"))
        assert saved["latest"] is None


def test_offline_is_cached_and_does_not_raise(monkeypatch):
    _enable(monkeypatch)
    calls = []

    def fetch(url, etag, timeout):
        calls.append(url)
        raise OSError("offline")

    assert update_check.notice(fetch=fetch, now=1_000, current="0.1.0") is None
    assert update_check.notice(fetch=fetch, now=1_500, current="0.1.0") is None
    assert calls == [update_check.RELEASES_URL]


def test_etag_304_reuses_the_cached_release(monkeypatch):
    _enable(monkeypatch)
    fetch, calls = _fetch(_body(), conditional=True)
    assert update_check.notice(fetch=fetch, now=1_000, current="0.1.0") == LINE
    assert update_check.notice(fetch=fetch, now=1_000 + DAY, current="0.1.0") == LINE
    assert [call["etag"] for call in calls] == [None, '"abc"']


def test_a_failed_refresh_still_prints_the_cached_release(monkeypatch):
    _enable(monkeypatch)
    fetch, _calls = _fetch(_body())
    assert update_check.notice(fetch=fetch, now=1_000, current="0.1.0") == LINE

    def fail(url, etag, timeout):
        raise TimeoutError("slow")

    assert update_check.notice(fetch=fail, now=1_000 + DAY, current="0.1.0") == LINE


def test_ci_and_the_env_opt_out_skip_the_check(monkeypatch):
    calls = []

    def fetch(url, etag, timeout):
        calls.append(url)
        return 200, None, _body()

    monkeypatch.delenv("CBI_NO_UPDATE_CHECK", raising=False)
    monkeypatch.setenv("CI", "true")
    assert update_check.notice(fetch=fetch, now=1_000, current="0.1.0") is None
    monkeypatch.setenv("CI", "false")
    monkeypatch.setenv("CBI_NO_UPDATE_CHECK", "1")
    assert update_check.notice(fetch=fetch, now=1_000, current="0.1.0") is None
    update_check.cache_file().parent.mkdir(parents=True, exist_ok=True)
    update_check.cache_file().write_text(json.dumps({
        "checked_at": 1_000, "etag": None,
        "latest": {"version": "0.2.0", "url": "https://github.com/joshuavial/codebase-inspector/releases/tag/v0.2.0"},
    }), encoding="utf-8")
    assert update_check.notice(fetch=fetch, now=1_100, current="0.1.0") is None
    assert calls == []


def test_a_hung_fetch_does_not_block_past_the_timeout(monkeypatch):
    _enable(monkeypatch)

    def fetch(url, etag, timeout):
        time.sleep(5)
        return 200, None, _body()

    started = time.monotonic()
    assert update_check.notice(fetch=fetch, now=1_000, current="0.1.0", timeout=0.2) is None
    assert time.monotonic() - started < 2


def test_cache_file_follows_cbi_cache_dir_or_the_platform_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("CBI_CACHE_DIR", str(tmp_path))
    assert update_check.cache_file() == tmp_path / "update-check.json"
    monkeypatch.delenv("CBI_CACHE_DIR")
    monkeypatch.setattr(update_check.Path, "home", lambda: update_check.Path("/Users/example"))
    monkeypatch.setattr(update_check.sys, "platform", "darwin")
    assert update_check.cache_file() == update_check.Path(
        "/Users/example/Library/Caches/codebase-inspector/update-check.json")
    monkeypatch.setattr(update_check.sys, "platform", "linux")
    monkeypatch.delenv("XDG_CACHE_HOME", raising=False)
    assert update_check.cache_file() == update_check.Path("/Users/example/.cache/codebase-inspector/update-check.json")
    monkeypatch.setenv("XDG_CACHE_HOME", "/tmp/xdg")
    assert update_check.cache_file() == update_check.Path("/tmp/xdg/codebase-inspector/update-check.json")
    monkeypatch.setattr(update_check.sys, "platform", "win32")
    monkeypatch.setenv("LOCALAPPDATA", "/Users/example/AppData/Local")
    assert update_check.cache_file() == update_check.Path(
        "/Users/example/AppData/Local/codebase-inspector/update-check.json")


def test_fetch_release_sends_a_user_agent_and_honours_etag():
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.server.agents.append(self.headers.get("User-Agent"))
            self.server.auth.append(self.headers.get("Authorization"))
            match = self.headers.get("If-None-Match")
            self.server.etags.append(match)
            if match == '"abc"':
                self.send_response(304)
                self.send_header("ETag", '"abc"')
                self.end_headers()
                return
            raw = json.dumps(_body()).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("ETag", '"abc"')
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def log_message(self, fmt, *args):
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.agents = []
    server.auth = []
    server.etags = []
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        url = f"http://127.0.0.1:{server.server_address[1]}/latest"
        status, etag, payload = update_check.fetch_release(url, None, 2)
        assert status == 200 and etag == '"abc"' and payload["tag_name"] == "v0.2.0"
        status, etag, payload = update_check.fetch_release(url, '"abc"', 2)
        assert status == 304 and payload is None and etag == '"abc"'
        assert server.etags == [None, '"abc"']
        assert server.auth == [None, None]
        assert all(agent and agent.startswith("codebase-inspector/") for agent in server.agents)
    finally:
        server.shutdown()
        server.server_close()


def test_version_flag_prints_the_version(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["--version"])
    assert exc.value.code == 0
    assert capsys.readouterr().out.strip() == f"cbi {update_check.current_version()}"


def test_prime_and_status_print_the_notice(make_repo, monkeypatch, capsys):
    _enable(monkeypatch)
    monkeypatch.setattr(update_check, "current_version", lambda: "0.1.0")
    fetch, _calls = _fetch(_body())
    monkeypatch.setattr(update_check, "fetch_release", fetch)
    repo = make_repo({"a.ts": "export {};\n"})
    monkeypatch.chdir(repo)
    assert main(["prime"]) == 0
    assert capsys.readouterr().out.endswith(LINE + "\n")
    assert main(["init"]) == 0
    assert main(["scan"]) == 0
    capsys.readouterr()
    assert main(["status"]) == 0
    text = capsys.readouterr().out
    assert text.startswith("last scan:")
    assert text.rstrip().endswith(LINE)
    assert main(["status", "--json"]) == 0
    raw = capsys.readouterr().out
    json.loads(raw)
    assert "newer cbi" not in raw
