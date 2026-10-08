"""PNG and SVG of the concept map, captured with headless system Chrome.

The page is the concept viewer. data/diff.js feeds its comparison marks, and
render.js adds the compact key.
`cbi review` calls `render_images` for the before/after pair.
"""

import base64
import json
import os
import re
import shutil
import signal
import socket
import sqlite3
import struct
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

from cbi import build, diff

HELP = """\
Write a PNG and an SVG of one concept-map view.

--view top draws the top level. --view ID draws that concept. --png and
--svg are the files to write. --out is the model directory (default .cbi/).

--compare BASE..HEAD loads those two versions (same as `cbi diff`) and
highlights the change list. --side base writes the base map (removed and
changed). --side head (default) writes the head map (added and changed).

The page is the concept viewer, laid out with elkjs and captured with
headless system Chrome or Chromium. Each capture uses its own temporary
profile and debugging port, waits until the page sets the title
cbi-render-ready, then reads the screenshot and the SVG. The browser
is killed when the capture finishes.

Exit codes: 0 the files were written, 1 no model, unknown concept, or
Chrome failed, 2 bad arguments, 3 Chrome or Chromium is not installed
(nothing is written)."""

SKIPPED = "no system Chrome or Chromium found; images skipped"
READY = "cbi-render-ready"
FAILED = "cbi-render-failed"

# Shared flags. The profile directory and the debugging port are per capture,
# so two worktrees do not share a profile lock or a port.
_CHROME_FLAGS = (
    "--headless",
    "--disable-gpu",
    "--window-size=1600,1000",
    "--no-first-run",
    "--no-default-browser-check",
    "--disable-extensions",
    "--disable-sync",
    "--disable-background-networking",
)
_APP_BINARIES = (
    "Google Chrome.app/Contents/MacOS/Google Chrome",
    "Chromium.app/Contents/MacOS/Chromium",
    "Google Chrome Canary.app/Contents/MacOS/Google Chrome Canary",
)
_PATH_NAMES = ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser", "chrome")
_WIN_BINARIES = (
    "Google/Chrome/Application/chrome.exe",
    "Google/Chrome Beta/Application/chrome.exe",
    "Chromium/Application/chrome.exe",
)
_WIN_PATH_NAMES = ("chrome.exe", "chrome", "chromium.exe", "chromium")
_SIDES = (("base", "before.png", "before.svg"), ("head", "after.png", "after.svg"))
_ASSETS = Path(__file__).parent / "viewer"
_TIMEOUT = 120


class RenderError(Exception):
    def __init__(self, message, code=1):
        super().__init__(message)
        self.code = code


def _windows_chrome_roots():
    """Program Files and the per-user local app dir. Empty entries are skipped."""
    roots = []
    for key in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA"):
        value = os.environ.get(key)
        if value:
            roots.append(Path(value))
    return roots


def application_dirs():
    """Where system Chrome lives. Tests replace this with a zero-arg function."""
    if sys.platform == "win32":
        return _windows_chrome_roots()
    root = Path("/Applications")
    return [root] if root.is_dir() else []


def find_chrome(env=None, applications=None, platform=None):
    """The first system Chrome or Chromium, or None.

    macOS looks in application directories first, then the usual names on PATH.
    Windows looks under Program Files, then `chrome.exe` on PATH.
    Linux is PATH only. `env` defaults to the process environment. A file that
    is not executable does not count. `application_dirs` is called with no
    arguments so a test can replace it with a zero-arg function.
    """
    if env is None:
        env = os.environ
    plat = sys.platform if platform is None else platform
    roots = application_dirs() if applications is None else applications
    if plat == "win32":
        # App-bundle paths stay in the list so a caller can pass either layout.
        rels = _WIN_BINARIES + _APP_BINARIES
        names = _WIN_PATH_NAMES + _PATH_NAMES
    else:
        rels = _APP_BINARIES
        names = _PATH_NAMES
    for root in roots:
        root = Path(root)
        for rel in rels:
            candidate = root / rel
            if _can_run(candidate):
                return candidate
    sep = os.pathsep if platform is None else (";" if plat == "win32" else ":")
    for directory in env.get("PATH", "").split(sep):
        if not directory:
            continue
        for name in names:
            candidate = Path(directory) / name
            if _can_run(candidate):
                return candidate
    return None


def split_compare(spec):
    """BASE..HEAD. One separator, both sides non-empty."""
    base, sep, head = spec.partition("..")
    if not sep or not base or not head or ".." in head:
        raise RenderError("--compare needs BASE..HEAD", code=2)
    return base, head


def concept_focus(payload, view):
    """None for the top level, or the concept id. Unknown ids raise."""
    if view == "top":
        return None
    if not view or not _contains(payload.get("concepts") or [], view):
        raise RenderError(f"no concept {view}")
    return view


def render_images(model, change_list, out_dir):
    """Write before.png, before.svg, after.png and after.svg of the top level.

    `model` is {"base": side, "head": side}. A side is a sqlite connection,
    a path to model.db or the directory that contains it, or a concept-view
    dict. `change_list` is the object from `diff.compare`, or None.

    Returns those four names mapped to Paths. When Chrome or Chromium is
    not installed, returns {"skipped": reason} and writes nothing. Other
    failures raise RenderError; image files from this call are removed.
    """
    if find_chrome() is None:
        return {"skipped": SKIPPED}
    if not isinstance(model, dict) or "base" not in model or "head" not in model:
        raise RenderError("render_images model needs base and head")
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    written = []
    try:
        for side, png_name, svg_name in _SIDES:
            png = out_dir / png_name
            svg = out_dir / svg_name
            render_view(model[side], change_list, "top", side, png, svg)
            written.extend((png, svg))
    except Exception:
        for path in written:
            path.unlink(missing_ok=True)
        raise
    return {path.name: path for path in written}


def render_view(model, change_list, view, side, png, svg, root=None):
    """Write one PNG and one SVG. Raises RenderError and leaves no file on failure.

    The model and the concept id are checked before Chrome, so a missing
    model or an unknown concept fails even when Chrome is not installed.
    """
    if side not in ("base", "head"):
        raise RenderError("--side must be base or head", code=2)
    payload = _payload(model, root)
    focus = concept_focus(payload, view)
    chrome = find_chrome()
    if chrome is None:
        raise RenderError(SKIPPED, code=3)
    png, svg = Path(png), Path(svg)
    with tempfile.TemporaryDirectory(prefix="cbi-render-") as tmp:
        page = _stage(Path(tmp), payload, change_list, focus, side)
        png_bytes, title, markup = _capture(chrome, page)
        markup = markup.replace("<\\/script", "</script")
        if title != READY:
            detail = _failure_text(markup) or f"render page did not finish (title {title or 'missing'})"
            raise RenderError(detail)
        if "<svg" not in markup:
            raise RenderError("render page produced no SVG")
        if not png_bytes.startswith(b"\x89PNG\r\n\x1a\n"):
            raise RenderError("Chrome wrote an empty screenshot")
        _publish(png, svg, png_bytes, markup)


def svg_from_dom(html):
    """(title, svg markup) from a dump-dom document. The SVG is not unescaped."""
    title = ""
    match = re.search(r"<title>(.*?)</title>", html, re.DOTALL | re.IGNORECASE)
    if match:
        title = match.group(1).strip()
    body = _script_body(html, "svg-out")
    return title, body.replace("<\\/script", "</script")


def _script_body(html, script_id):
    for match in re.finditer(r"<script\b([^>]*)>", html, re.IGNORECASE):
        if re.search(rf'\bid="{re.escape(script_id)}"', match.group(1)):
            start = match.end()
            end = html.lower().find("</script>", start)
            if end < 0:
                return ""
            return html[start:end].strip()
    return ""


def _failure_text(markup):
    text = re.sub(r"<[^>]+>", " ", markup or "")
    text = re.sub(r"\s+", " ", text).strip()
    if "Layout failed" in text or text:
        return text[:300]
    return ""


def _publish(png, svg, shot, markup):
    png.parent.mkdir(parents=True, exist_ok=True)
    svg.parent.mkdir(parents=True, exist_ok=True)
    tmp_png = png.with_name(png.name + ".partial")
    tmp_svg = svg.with_name(svg.name + ".partial")
    try:
        tmp_png.write_bytes(shot)
        tmp_svg.write_text(markup, encoding="utf-8")
        os.replace(tmp_png, png)
        try:
            os.replace(tmp_svg, svg)
        except Exception:
            png.unlink(missing_ok=True)
            raise
    finally:
        tmp_png.unlink(missing_ok=True)
        tmp_svg.unlink(missing_ok=True)


def _payload(model, root):
    if isinstance(model, dict):
        if "concepts" not in model:
            raise RenderError("model has no concepts")
        return model
    opened = None
    conn = model
    if isinstance(model, (str, Path)):
        opened = diff.open_model(model)
        conn = opened
    elif not isinstance(model, sqlite3.Connection):
        raise RenderError("model must be a connection, a path, or a concept view")
    try:
        return build.concept_view(conn, root)
    finally:
        if opened:
            opened.close()


def _contains(nodes, cid):
    for node in nodes:
        if node.get("id") == cid:
            return True
        if _contains(node.get("children") or [], cid):
            return True
    return False


def _stage(dest, payload, change_list, focus, side):
    dest.mkdir(parents=True, exist_ok=True)
    vendor = dest / "vendor"
    vendor.mkdir()
    shutil.copyfile(_ASSETS / "app.js", dest / "app.js")
    shutil.copyfile(_ASSETS / "render.js", dest / "render.js")
    shutil.copyfile(_ASSETS / "vendor" / "elk.bundled.js", vendor / "elk.bundled.js")
    css = (_ASSETS / "style.css").read_text(encoding="utf-8").replace("</style", "<\\/style")
    html = (_ASSETS / "render.html").read_text(encoding="utf-8").replace("/*__VIEWER_CSS__*/", css)
    (dest / "render.html").write_text(html, encoding="utf-8")
    data = dest / "data"
    data.mkdir()
    (data / "view.js").write_text(_js("view", {"focus": focus, "side": side}), encoding="utf-8")
    (data / "diff.js").write_text(_js("diff", _diff_payload(change_list)), encoding="utf-8")
    (data / "model.js").write_text(_js("concepts", payload), encoding="utf-8")
    return dest / "render.html"


def _diff_payload(change_list):
    """The viewer's data/diff.js shape for one side's model.

    removed stays empty: the model passed in is already that side, so the
    page does not graft the other side's concepts back on.
    """
    if not change_list:
        return None
    return {
        "base": "",
        "head": "",
        "changes": change_list,
        "removed": {"concepts": [], "relationships": [], "externals": []},
        "provisional": [],
    }


def _js(name, data):
    body = json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("<", "\\u003c")
    return f'cbiLoad("{name}", {body});\n'


def _chrome_argv(chrome, profile, url):
    """Argv for one capture. The profile path is absolute: a relative one hangs."""
    profile = Path(profile).resolve()
    return [
        str(chrome),
        *_CHROME_FLAGS,
        f"--user-data-dir={profile}",
        "--remote-debugging-port=0",
        url,
    ]


def _capture(chrome, page, timeout=_TIMEOUT):
    """PNG bytes, page title and SVG text. The browser is killed before return.

    `--virtual-time-budget` made headless Chrome shut itself down, and on macOS
    that shutdown intermittently never finishes. The teardown watchdog then
    exits non-zero, which failed the capture even after the page had drawn.
    Waiting for the ready title and killing the process group skips that path.
    """
    profile = (Path(page).parent / "profile").resolve()
    profile.mkdir(parents=True, exist_ok=True)
    proc = subprocess.Popen(
        _chrome_argv(chrome, profile, Path(page).resolve().as_uri()),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        **_popen_kwargs(),
    )
    chunks = []
    reader = threading.Thread(target=_drain, args=(proc.stderr, chunks), daemon=True)
    reader.start()
    deadline = time.monotonic() + timeout
    try:
        port = _wait_port(proc, profile, chunks, deadline)
        title, ws_url = _wait_ready(port, proc, chunks, deadline)
        markup, png_bytes = _read_page(ws_url)
        return png_bytes, title, markup
    finally:
        _kill_group(proc)
        reader.join(timeout=2)


def _popen_kwargs():
    """Detach Chrome. Windows has no process session to kill with killpg."""
    if sys.platform == "win32":
        flags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200)
        flags |= getattr(subprocess, "DETACHED_PROCESS", 0x00000008)
        return {"creationflags": flags}
    return {"start_new_session": True}


def _kill_group(proc):
    """Stop Chrome, then wait so a helper cannot keep the profile.

    On Windows the process is killed directly. Elsewhere the session is killed.
    """
    if sys.platform == "win32":
        try:
            proc.kill()
        except OSError:
            pass
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)
        return
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except OSError:
        pass
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=5)


def _drain(stream, chunks):
    try:
        while True:
            block = stream.read(65536)
            if not block:
                return
            chunks.append(block)
    except OSError:
        return


def _stderr_text(chunks):
    return b"".join(chunks).decode(errors="replace")


def _died(proc, chunks):
    lines = [line for line in _stderr_text(chunks).splitlines() if line.strip()]
    detail = lines[-1] if lines else f"exit {proc.returncode}"
    return RenderError(f"Chrome failed: {detail}")


def _wait_port(proc, profile, chunks, deadline):
    while time.monotonic() < deadline:
        port = _port_file(profile) or _devtools_port(_stderr_text(chunks))
        if port:
            return port
        if proc.poll() is not None:
            raise _died(proc, chunks)
        time.sleep(0.05)
    raise RenderError("Chrome timed out")


def _port_file(profile):
    try:
        line = (Path(profile) / "DevToolsActivePort").read_text(encoding="utf-8").splitlines()[0].strip()
    except (OSError, IndexError):
        return None
    return int(line) if line.isdigit() else None


def _devtools_port(text):
    match = re.search(r"ws://127\.0\.0\.1:(\d+)/", text)
    return int(match.group(1)) if match else None


def _wait_ready(port, proc, chunks, deadline):
    """(title, websocket url) once the render page has finished or failed."""
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            raise _died(proc, chunks)
        try:
            pages = _json_list(port)
        except (OSError, ValueError):
            time.sleep(0.05)
            continue
        for item in pages:
            url = str(item.get("url") or "")
            if item.get("type") != "page" or "render.html" not in url:
                continue
            title = (item.get("title") or "").strip()
            if title in (READY, FAILED):
                ws_url = item.get("webSocketDebuggerUrl")
                if not ws_url:
                    raise RenderError("Chrome devtools URL was missing")
                return title, ws_url
        time.sleep(0.05)
    raise RenderError("Chrome timed out")


def _json_list(port):
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/list", timeout=1) as resp:
            data = json.loads(resp.read().decode())
    except urllib.error.URLError as err:
        raise OSError(str(err)) from err
    if not isinstance(data, list):
        raise OSError("devtools list was not a list")
    return data


def _read_page(ws_url):
    """SVG text from #svg-out, then the PNG, over the page's debugging socket."""
    sock, pending = _ws_open(ws_url)
    try:
        evaluated = _cdp(sock, pending, 1, "Runtime.evaluate", {
            "expression": (
                "document.getElementById('svg-out')"
                " ? document.getElementById('svg-out').textContent : ''"
            ),
            "returnByValue": True,
        })
        pending = evaluated[1]
        value = (evaluated[0].get("result") or {}).get("value")
        shot = _cdp(sock, pending, 2, "Page.captureScreenshot", {"format": "png"})
        data = shot[0].get("data") or ""
        return "" if value is None else str(value), base64.b64decode(data)
    finally:
        sock.close()


def _ws_open(url):
    host, port, path = _split_ws(url)
    sock = socket.create_connection((host, port), timeout=5)
    key = base64.b64encode(os.urandom(16)).decode()
    request = (
        f"GET {path} HTTP/1.1\r\n"
        f"Host: {host}:{port}\r\n"
        "Upgrade: websocket\r\n"
        "Connection: Upgrade\r\n"
        f"Sec-WebSocket-Key: {key}\r\n"
        "Sec-WebSocket-Version: 13\r\n"
        "\r\n"
    )
    sock.sendall(request.encode())
    data = b""
    sock.settimeout(10)
    while b"\r\n\r\n" not in data:
        try:
            chunk = sock.recv(4096)
        except TimeoutError as err:
            sock.close()
            raise RenderError("Chrome timed out") from err
        if not chunk:
            sock.close()
            raise RenderError("Chrome devtools closed")
        data += chunk
    head, pending = data.split(b"\r\n\r\n", 1)
    status = head.split(b"\r\n", 1)[0]
    if b" 101 " not in status:
        sock.close()
        raise RenderError(f"Chrome devtools refused the connection: {status.decode(errors='replace')}")
    return sock, bytearray(pending)


def _split_ws(url):
    if not url.startswith("ws://"):
        raise RenderError("Chrome devtools URL was missing")
    hostport, sep, path = url[len("ws://"):].partition("/")
    if not sep or not hostport:
        raise RenderError("Chrome devtools URL was missing")
    if hostport.startswith("["):
        host, _, port = hostport[1:].rpartition("]:")
    else:
        host, _, port = hostport.rpartition(":")
    if not port.isdigit():
        raise RenderError("Chrome devtools URL was missing")
    return host, int(port), "/" + path


def _cdp(sock, pending, msg_id, method, params):
    sock.sendall(_ws_frame(0x1, json.dumps({"id": msg_id, "method": method, "params": params}).encode()))
    buf = pending
    parts = []
    while True:
        fin, opcode, payload, buf = _ws_recv(sock, buf)
        if opcode == 0x9:
            sock.sendall(_ws_frame(0xA, payload))
            continue
        if opcode == 0x8:
            raise RenderError("Chrome devtools closed")
        if opcode not in (0x0, 0x1):
            continue
        parts.append(payload)
        if not fin:
            continue
        message = json.loads(b"".join(parts).decode())
        parts = []
        if message.get("id") != msg_id:
            continue
        if "error" in message:
            detail = message["error"].get("message", message["error"])
            raise RenderError(f"Chrome failed: {detail}")
        return message.get("result") or {}, buf


def _ws_frame(opcode, payload):
    mask = os.urandom(4)
    length = len(payload)
    header = bytearray([0x80 | opcode])
    if length < 126:
        header.append(0x80 | length)
    elif length < 65536:
        header.append(0x80 | 126)
        header += struct.pack("!H", length)
    else:
        header.append(0x80 | 127)
        header += struct.pack("!Q", length)
    masked = bytes(byte ^ mask[i % 4] for i, byte in enumerate(payload))
    return bytes(header) + mask + masked


def _ws_recv(sock, buf):
    def take(n):
        while len(buf) < n:
            chunk = sock.recv(65536)
            if not chunk:
                raise RenderError("Chrome devtools closed")
            buf.extend(chunk)
        out = bytes(buf[:n])
        del buf[:n]
        return out

    try:
        first, second = take(2)
        length = second & 0x7F
        if length == 126:
            length = struct.unpack("!H", take(2))[0]
        elif length == 127:
            length = struct.unpack("!Q", take(8))[0]
        if second & 0x80:
            mask = take(4)
            raw = take(length)
            payload = bytes(byte ^ mask[i % 4] for i, byte in enumerate(raw))
        else:
            payload = take(length)
    except TimeoutError as err:
        raise RenderError("Chrome timed out") from err
    return bool(first & 0x80), first & 0x0F, payload, buf


def _can_run(path):
    return path.is_file() and os.access(path, os.X_OK)
