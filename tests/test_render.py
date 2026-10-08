"""Headless concept-map images: Chrome discovery, the skip path, and one real capture."""

import json
import sqlite3
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from cbi import render, store
from cbi.cli import main

APP = "c:app"
UI = "c:ui"


def _box(cid, name):
    return {"id": cid, "name": name, "summary": "", "role": "core", "symbols": [], "children": []}


def _payload():
    return {
        "workspace": "fixture",
        "summary": "",
        "concepts": [_box(APP, "App"), _box(UI, "UI")],
        "externals": [],
        "relationships": [],
        "screens": [],
    }


def _added_ui():
    return {
        "grouping": "concept",
        "groups": [{
            "id": UI,
            "name": "UI",
            "kind": "concept",
            "changes": [{
                "kind": "concept-added",
                "summary": "UI added",
                "before": None,
                "after": {"id": UI},
                "code": None,
            }],
        }],
    }


def _exe(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("#!/bin/sh\n")
    path.chmod(0o755)
    return path


def _ready_dom():
    return (
        "<html><head><title>cbi-render-ready</title></head><body>"
        '<script type="text/plain" id="svg-out">'
        "<svg><text>App &amp; UI</text><\\/script></svg>"
        "</script></body></html>"
    )


def _model(make_repo, monkeypatch, tmp_path):
    repo = make_repo({"a.py": "x = 1\n"})
    monkeypatch.chdir(repo)
    out = tmp_path / "model"
    assert main(["init", "--out", str(out)]) == 0
    store.open_db(out / "model.db").close()
    return repo, out


def test_find_chrome_prefers_applications_then_path(tmp_path):
    path_dir = tmp_path / "bin"
    chromium = _exe(path_dir / "chromium")
    assert render.find_chrome(env={"PATH": str(path_dir)}, applications=[]) == chromium

    apps = tmp_path / "Applications"
    chrome = _exe(apps / "Google Chrome.app/Contents/MacOS/Google Chrome")
    _exe(path_dir / "google-chrome")
    found = render.find_chrome(env={"PATH": str(path_dir)}, applications=[apps])
    assert found == chrome


def test_find_chrome_on_windows_uses_program_files_then_path(tmp_path):
    root = tmp_path / "pf"
    chrome = _exe(root / "Google" / "Chrome" / "Application" / "chrome.exe")
    found = render.find_chrome(env={"PATH": ""}, applications=[root], platform="win32")
    assert found == chrome
    path_dir = tmp_path / "bin"
    exe = _exe(path_dir / "chrome.exe")
    found = render.find_chrome(env={"PATH": str(path_dir)}, applications=[], platform="win32")
    assert found == exe


def test_chrome_process_flags_on_windows(monkeypatch):
    monkeypatch.setattr(render.sys, "platform", "win32")
    flags = render._popen_kwargs()
    assert flags["creationflags"] & 0x00000200
    assert "start_new_session" not in flags

    class Proc:
        def __init__(self):
            self.killed = 0

        def kill(self):
            self.killed += 1

        def wait(self, timeout=None):
            return 0

    proc = Proc()
    render._kill_group(proc)
    assert proc.killed == 1


@pytest.mark.skipif(sys.platform == "win32", reason="Windows reports every existing file as executable")
def test_find_chrome_ignores_files_that_are_not_executable(tmp_path):
    apps = tmp_path / "Applications"
    binary = apps / "Google Chrome.app/Contents/MacOS/Google Chrome"
    binary.parent.mkdir(parents=True)
    binary.write_text("nope")
    path_dir = tmp_path / "bin"
    path_dir.mkdir()
    (path_dir / "chrome").write_text("nope")
    assert render.find_chrome(env={"PATH": str(path_dir)}, applications=[apps]) is None


def test_render_images_skips_when_path_has_no_chrome(tmp_path, monkeypatch):
    monkeypatch.setattr(render, "application_dirs", lambda: [])
    empty = tmp_path / "path"
    empty.mkdir()
    monkeypatch.setenv("PATH", str(empty))
    out = tmp_path / "images"
    result = render.render_images({"base": _payload(), "head": _payload()}, None, out)
    assert result == {"skipped": render.SKIPPED}
    assert not out.exists()


def test_svg_from_dom_keeps_escapes():
    title, body = render.svg_from_dom(_ready_dom())
    assert title == "cbi-render-ready"
    assert body == "<svg><text>App &amp; UI</text></script></svg>"


def test_split_compare_and_unknown_concept():
    assert render.split_compare("a..b") == ("a", "b")
    with pytest.raises(render.RenderError) as bad:
        render.split_compare("only-one")
    assert bad.value.code == 2
    with pytest.raises(render.RenderError):
        render.split_compare("a..b..c")
    assert render.concept_focus(_payload(), "top") is None
    assert render.concept_focus(_payload(), APP) == APP
    with pytest.raises(render.RenderError) as missing:
        render.concept_focus(_payload(), "nope")
    assert missing.value.code == 1


def test_chrome_argv_has_its_own_profile_and_no_time_budget(tmp_path):
    url = "file:///tmp/render.html"
    argv = render._chrome_argv("/Applications/Google Chrome", tmp_path / "profile", url)
    assert isinstance(argv, list)
    assert argv[0] == "/Applications/Google Chrome"
    assert "--headless" in argv and "--disable-gpu" in argv
    assert "--window-size=1600,1000" in argv
    assert "--remote-debugging-port=0" in argv
    assert not any(part.startswith("--virtual-time-budget") for part in argv)
    profile = next(part for part in argv if part.startswith("--user-data-dir=")).split("=", 1)[1]
    assert Path(profile) == (tmp_path / "profile").resolve()
    assert argv[-1] == url
    other = render._chrome_argv("/bin/chrome", tmp_path / "other", url)
    assert other[0] == "/bin/chrome"
    assert profile not in other


def test_render_view_publishes_when_the_page_is_ready(tmp_path, monkeypatch):
    monkeypatch.setattr(render, "find_chrome", lambda: Path("/bin/chrome"))

    def fake(chrome, page, timeout=120):
        assert chrome == Path("/bin/chrome")
        assert page.name == "render.html"
        assert timeout == 120
        return b"\x89PNG\r\n\x1a\nfake", render.READY, "<svg><text>App &amp; UI</text><\\/script></svg>"

    monkeypatch.setattr(render, "_capture", fake)
    png, svg = tmp_path / "map.png", tmp_path / "map.svg"
    render.render_view(_payload(), None, "top", "head", png, svg)
    assert png.read_bytes().startswith(b"\x89PNG")
    assert "&amp;" in svg.read_text()
    assert "</script>" in svg.read_text()


def test_page_not_ready_and_chrome_failure_write_nothing(tmp_path, monkeypatch):
    monkeypatch.setattr(render, "find_chrome", lambda: Path("/bin/chrome"))

    def not_ready(chrome, page, timeout=120):
        return b"\x89PNG\r\n\x1a\nfake", render.FAILED, "Layout failed"

    monkeypatch.setattr(render, "_capture", not_ready)
    png, svg = tmp_path / "a.png", tmp_path / "a.svg"
    with pytest.raises(render.RenderError) as err:
        render.render_view(_payload(), None, "top", "head", png, svg)
    assert err.value.code == 1
    assert "Layout failed" in str(err.value)
    assert not png.exists() and not svg.exists()

    def crashed(chrome, page, timeout=120):
        raise render.RenderError("Chrome failed: Chrome crashed")

    monkeypatch.setattr(render, "_capture", crashed)
    with pytest.raises(render.RenderError, match="Chrome crashed"):
        render.render_view(_payload(), None, "top", "head", png, svg)
    assert not png.exists() and not svg.exists()


def test_unknown_view_does_not_launch_chrome(tmp_path, monkeypatch):
    def fail(*_a, **_k):
        raise AssertionError("chrome was used")

    monkeypatch.setattr(render, "find_chrome", fail)
    monkeypatch.setattr(render.subprocess, "run", fail)
    png, svg = tmp_path / "a.png", tmp_path / "a.svg"
    with pytest.raises(render.RenderError) as err:
        render.render_view(_payload(), None, "missing", "head", png, svg)
    assert err.value.code == 1
    assert not png.exists() and not svg.exists()


def test_render_view_without_chrome_writes_nothing(tmp_path, monkeypatch):
    monkeypatch.setattr(render, "find_chrome", lambda: None)
    png, svg = tmp_path / "a.png", tmp_path / "a.svg"
    with pytest.raises(render.RenderError) as err:
        render.render_view(_payload(), None, "top", "head", png, svg)
    assert err.value.code == 3
    assert render.SKIPPED in str(err.value)
    assert not png.exists() and not svg.exists()


def test_render_images_writes_four_and_drops_partials(tmp_path, monkeypatch):
    monkeypatch.setattr(render, "find_chrome", lambda: Path("/bin/chrome"))
    seen = []

    def fake(model, change_list, view, side, png, svg, root=None):
        seen.append(side)
        assert view == "top"
        Path(png).write_bytes(b"png")
        Path(svg).write_text("<svg></svg>")

    monkeypatch.setattr(render, "render_view", fake)
    out = tmp_path / "images"
    result = render.render_images({"base": "base-model", "head": "head-model"}, {"groups": []}, out)
    assert set(result) == {"before.png", "before.svg", "after.png", "after.svg"}
    assert seen == ["base", "head"]
    assert all(path.is_file() for path in result.values())

    def fail_second(model, change_list, view, side, png, svg, root=None):
        if side == "head":
            raise render.RenderError("boom")
        Path(png).write_bytes(b"png")
        Path(svg).write_text("<svg></svg>")

    monkeypatch.setattr(render, "render_view", fail_second)
    again = tmp_path / "again"
    with pytest.raises(render.RenderError, match="boom"):
        render.render_images({"base": "b", "head": "h"}, None, again)
    assert list(again.iterdir()) == []


def test_render_images_rejects_a_single_model(tmp_path, monkeypatch):
    monkeypatch.setattr(render, "find_chrome", lambda: Path("/bin/chrome"))
    out = tmp_path / "images"
    with pytest.raises(render.RenderError, match="base and head"):
        render.render_images({"concepts": []}, None, out)
    assert not out.exists()


def test_render_help_names_the_capture(capsys):
    with pytest.raises(SystemExit) as exit_info:
        main(["render", "--help"])
    assert exit_info.value.code == 0
    out = capsys.readouterr().out
    assert "--view" in out and "--png" in out and "--svg" in out
    assert "--compare" in out and "--side" in out
    assert "cbi-render-ready" in out
    assert "temporary" in out
    assert "3 Chrome" in out


def test_cli_missing_model_exits_before_chrome(make_repo, monkeypatch, capsys, tmp_path):
    repo = make_repo({"a.py": "x = 1\n"})
    monkeypatch.chdir(repo)

    def fail(*_a, **_k):
        raise AssertionError("chrome was used")

    monkeypatch.setattr(render, "find_chrome", fail)
    png, svg = tmp_path / "a.png", tmp_path / "a.svg"
    code = main(["render", "--view", "top", "--png", str(png), "--svg", str(svg), "--out", str(tmp_path / "missing")])
    assert code == 1
    assert "no model" in capsys.readouterr().err
    assert not png.exists() and not svg.exists()


def test_cli_skips_without_chrome(make_repo, monkeypatch, capsys, tmp_path):
    _repo, out = _model(make_repo, monkeypatch, tmp_path)
    monkeypatch.setattr(render, "find_chrome", lambda: None)
    png, svg = tmp_path / "a.png", tmp_path / "a.svg"
    code = main(["render", "--view", "top", "--png", str(png), "--svg", str(svg), "--out", str(out)])
    assert code == 3
    assert render.SKIPPED in capsys.readouterr().err
    assert not png.exists() and not svg.exists()


def test_cli_unknown_concept_exits_before_chrome(make_repo, monkeypatch, capsys, tmp_path):
    _repo, out = _model(make_repo, monkeypatch, tmp_path)

    def fail(*_a, **_k):
        raise AssertionError("chrome was used")

    monkeypatch.setattr(render, "find_chrome", fail)
    png, svg = tmp_path / "a.png", tmp_path / "a.svg"
    code = main(["render", "--view", "nope", "--png", str(png), "--svg", str(svg), "--out", str(out)])
    assert code == 1
    assert "no concept nope" in capsys.readouterr().err
    assert not png.exists() and not svg.exists()


def test_cli_bad_compare_exits_2(make_repo, monkeypatch, capsys, tmp_path):
    repo = make_repo({"a.py": "x = 1\n"})
    monkeypatch.chdir(repo)
    png, svg = tmp_path / "a.png", tmp_path / "a.svg"
    code = main(["render", "--view", "top", "--compare", "nope", "--png", str(png), "--svg", str(svg)])
    assert code == 2
    assert "BASE..HEAD" in capsys.readouterr().err
    assert not png.exists() and not svg.exists()


def test_cli_compare_draws_the_chosen_side(make_repo, monkeypatch, capsys, tmp_path):
    repo = make_repo({"a.py": "x = 1\n"})
    monkeypatch.chdir(repo)
    base, head = sqlite3.connect(":memory:"), sqlite3.connect(":memory:")
    monkeypatch.setattr("cbi.diff.models_for_refs", lambda *_a, **_k: (base, head))
    monkeypatch.setattr("cbi.diff.compare", lambda _b, _h: {"groups": [{"id": "x"}]})
    seen = {}

    def fake(model, change_list, view, side, png, svg, root=None):
        seen.update(model=model, changes=change_list, view=view, side=side, root=root)
        Path(png).write_bytes(b"png")
        Path(svg).write_text("<svg/>")

    monkeypatch.setattr(render, "render_view", fake)
    png, svg = tmp_path / "out.png", tmp_path / "out.svg"
    code = main(["render", "--view", "top", "--compare", "base-ref..head-ref", "--side", "base",
                 "--png", str(png), "--svg", str(svg)])
    assert code == 0
    assert seen == {
        "model": base, "changes": {"groups": [{"id": "x"}]}, "view": "top", "side": "base", "root": repo,
    }
    out = capsys.readouterr().out
    assert str(png.resolve()) in out and str(svg.resolve()) in out


def test_stage_feeds_the_viewer_diff(tmp_path):
    page = render._stage(tmp_path / "page", _payload(), _added_ui(), None, "base")
    html = page.read_text(encoding="utf-8")
    assert html.index("data/view.js") < html.index("data/diff.js") < html.index("data/model.js")
    assert 'id="compare"' in html and 'id="chg-toggle"' in html and 'id="changes"' in html
    diff_js = (tmp_path / "page" / "data" / "diff.js").read_text(encoding="utf-8")
    assert '"kind":"concept-added"' in diff_js
    assert (tmp_path / "page" / "data" / "model.js").read_text(encoding="utf-8").startswith('cbiLoad("concepts",')
    render._stage(tmp_path / "plain", _payload(), None, UI, "head")
    assert (tmp_path / "plain" / "data" / "diff.js").read_text(encoding="utf-8") == 'cbiLoad("diff", null);\n'
    view = (tmp_path / "plain" / "data" / "view.js").read_text(encoding="utf-8")
    assert '"focus":"c:ui"' in view and '"side":"head"' in view


def _script(path, body):
    path.write_text(body)
    path.chmod(0o755)
    return path


def test_kill_group_reaps_the_leader_and_its_child(tmp_path):
    script = _script(tmp_path / "run.sh", "#!/bin/sh\nsleep 30 &\nwait\n")
    proc = subprocess.Popen([str(script)], start_new_session=True)
    time.sleep(0.2)
    render._kill_group(proc)
    assert proc.wait(timeout=2) is not None
    left = subprocess.run(["ps", "-o", "pid=", "-g", str(proc.pid)], capture_output=True, text=True)
    assert left.stdout.strip() == ""


def test_capture_kills_a_browser_that_never_becomes_ready(tmp_path):
    script = _script(tmp_path / "chrome", "#!/bin/sh\nsleep 30\n")
    page = tmp_path / "render.html"
    page.write_text("<html></html>")
    started = time.monotonic()
    with pytest.raises(render.RenderError, match="timed out"):
        render._capture(script, page, timeout=0.4)
    assert time.monotonic() - started < 5
    left = subprocess.run(["pgrep", "-f", str(script)], capture_output=True, text=True)
    assert left.stdout.strip() == ""


def test_capture_reports_a_browser_that_exits(tmp_path):
    script = _script(tmp_path / "chrome", "#!/bin/sh\necho 'Chrome crashed' >&2\nexit 1\n")
    page = tmp_path / "render.html"
    page.write_text("<html></html>")
    with pytest.raises(render.RenderError, match="Chrome crashed") as err:
        render._capture(script, page, timeout=5)
    assert err.value.code == 1


class _Pages(BaseHTTPRequestHandler):
    titles = ("cbi render", render.READY)

    def do_GET(self):
        title = self.titles[min(self.server.hits, len(self.titles) - 1)]
        self.server.hits += 1
        body = json.dumps([{
            "type": "page",
            "url": "file:///tmp/render.html",
            "title": title,
            "webSocketDebuggerUrl": "ws://127.0.0.1:9/devtools/page/abc",
        }]).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_args):
        return


def test_wait_ready_polls_until_the_title_is_set():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Pages)
    server.hits = 0
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        class _Alive:
            def poll(self):
                return None

        title, ws_url = render._wait_ready(server.server_address[1], _Alive(), [], time.monotonic() + 2)
    finally:
        server.shutdown()
    assert title == render.READY
    assert ws_url.endswith("/devtools/page/abc")
    assert server.hits >= 2


def test_render_fixture_when_chrome_is_installed(tmp_path):
    if render.find_chrome() is None:
        pytest.skip("no system Chrome or Chromium")
    png, svg = tmp_path / "map.png", tmp_path / "map.svg"
    render.render_view(_payload(), _added_ui(), "top", "head", png, svg)
    text = svg.read_text(encoding="utf-8")
    assert ">App</text>" in text and ">UI</text>" in text
    assert ' chg-added"' in text
    assert ">Added</text>" in text
    raw = png.read_bytes()
    assert raw.startswith(b"\x89PNG\r\n\x1a\n") and len(raw) > 0


def test_parallel_renders_finish_together(tmp_path):
    if render.find_chrome() is None:
        pytest.skip("no system Chrome or Chromium")

    def once(i):
        png, svg = tmp_path / f"{i}.png", tmp_path / f"{i}.svg"
        render.render_view(_payload(), _added_ui(), "top", "head", png, svg)
        return svg.read_text(encoding="utf-8")

    with ThreadPoolExecutor(max_workers=4) as pool:
        texts = list(pool.map(once, range(4)))
    assert len(texts) == 4
    for text in texts:
        assert ">App</text>" in text and ">UI</text>" in text
