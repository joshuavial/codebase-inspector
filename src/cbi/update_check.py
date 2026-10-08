"""Look up the latest GitHub release and report when it is newer than this cbi.

The check is cached for a day. It never raises into a command: a timeout, an
offline machine or a bad response leaves the command's own result alone.

macOS builds are unsigned, so this check never downloads or installs an update.
It only prints a line. The desktop app opens the release in a browser for the
same reason.
"""

import json
import os
import re
import sys
import threading
import time
import urllib.error
import urllib.request
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

DAY = 24 * 60 * 60
TIMEOUT = 2
RELEASES_URL = "https://api.github.com/repos/joshuavial/codebase-inspector/releases/latest"
_SEMVER = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)$")


def current_version():
    """Installed distribution version, or 0.0.0 when metadata is missing."""
    try:
        return version("codebase-inspector")
    except PackageNotFoundError:
        return "0.0.0"


def platform_cache_dir(home=None):
    """The OS cache directory, before the codebase-inspector folder is added."""
    root = Path(home) if home is not None else Path.home()
    if sys.platform == "darwin":
        return root / "Library" / "Caches"
    if sys.platform == "win32":
        local = os.environ.get("LOCALAPPDATA")
        return Path(local) if local else root / "AppData" / "Local"
    xdg = os.environ.get("XDG_CACHE_HOME")
    return Path(xdg) if xdg else root / ".cache"


def cache_dir():
    """Where the update check remembers its last answer.

    `CBI_CACHE_DIR` moves it with the rest of cbi's cache. Otherwise it lives
    in the platform cache directory.
    """
    override = os.environ.get("CBI_CACHE_DIR")
    if override:
        return Path(override)
    return platform_cache_dir() / "codebase-inspector"


def cache_file():
    return cache_dir() / "update-check.json"


def _disabled():
    if os.environ.get("CBI_NO_UPDATE_CHECK") == "1":
        return True
    return os.environ.get("CI") == "true"


def _parts(text):
    match = _SEMVER.match(str(text).strip())
    if not match:
        return None
    return tuple(int(part) for part in match.groups())


def _version_text(text):
    parts = _parts(text)
    if not parts:
        return None
    return ".".join(str(part) for part in parts)


def _is_newer(latest, current):
    got = _parts(latest)
    have = _parts(current)
    if not got or not have:
        return False
    return got > have


def _line(latest, current):
    if not isinstance(latest, dict):
        return None
    found = latest.get("version")
    url = latest.get("url")
    if not isinstance(found, str) or not isinstance(url, str) or not url:
        return None
    if not _is_newer(found, current):
        return None
    return f"A newer cbi ({found}) is available: {url}"


def _parse(payload):
    """A stable release, 'ignore' for a draft or prerelease, or None when unusable."""
    if not isinstance(payload, dict):
        return None
    if payload.get("draft") is True or payload.get("prerelease") is True:
        return "ignore"
    found = _version_text(payload.get("tag_name") or "")
    if not found:
        return None
    url = payload.get("html_url")
    if not isinstance(url, str) or not url.startswith("https://"):
        url = f"https://github.com/joshuavial/codebase-inspector/releases/tag/v{found}"
    return {"version": found, "url": url}


def _valid_latest(latest):
    return isinstance(latest, dict) and _parts(latest.get("version") or "") and isinstance(latest.get("url"), str)


def _read_cache(path):
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict) or not isinstance(data.get("checked_at"), (int, float)):
        return None
    latest = data.get("latest")
    if not _valid_latest(latest):
        latest = None
    etag = data.get("etag") if isinstance(data.get("etag"), str) else None
    return {"checked_at": float(data["checked_at"]), "etag": etag, "latest": latest}


def _write_cache(path, data):
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data, sort_keys=True) + "\n", encoding="utf-8")
        tmp.replace(path)
    except OSError:
        return


def fetch_release(url, etag, timeout):
    """GET one release URL. Returns (status, etag, payload). 304 has no payload.

    Raises on network errors and on HTTP statuses other than 304.
    """
    headers = {
        "User-Agent": f"codebase-inspector/{current_version()}",
        "Accept": "application/vnd.github+json",
    }
    if etag:
        headers["If-None-Match"] = etag
    request = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
            return response.status, response.headers.get("ETag"), payload
    except urllib.error.HTTPError as err:
        if err.code == 304:
            return 304, err.headers.get("ETag") or etag, None
        raise


def _call(fetch, etag, timeout):
    """Run `fetch` and give up after `timeout` seconds. None means it did not finish."""
    box = {}

    def run():
        try:
            box["value"] = fetch(RELEASES_URL, etag, timeout)
        except Exception as err:
            box["error"] = err

    worker = threading.Thread(target=run, daemon=True)
    worker.start()
    worker.join(timeout)
    if worker.is_alive():
        return None
    if "error" in box:
        raise box["error"]
    value = box.get("value")
    if not isinstance(value, tuple) or len(value) != 3:
        raise TypeError("update check returned an unexpected response")
    return value


def _remember(path, now, etag, latest):
    _write_cache(path, {"checked_at": now, "etag": etag, "latest": latest})


def _notice(fetch, now, current, timeout):
    path = cache_file()
    cached = _read_cache(path) or {"checked_at": 0, "etag": None, "latest": None}
    if cached["checked_at"] and now - cached["checked_at"] < DAY:
        return _line(cached["latest"], current)
    try:
        fetched = _call(fetch, cached["etag"], timeout)
    except Exception:
        _remember(path, now, cached["etag"], cached["latest"])
        return _line(cached["latest"], current)
    if fetched is None:
        _remember(path, now, cached["etag"], cached["latest"])
        return _line(cached["latest"], current)
    status, etag, payload = fetched
    kept = etag or cached["etag"]
    if status == 304:
        _remember(path, now, kept, cached["latest"])
        return _line(cached["latest"], current)
    if status == 404:
        _remember(path, now, kept, None)
        return None
    parsed = _parse(payload) if status == 200 else None
    if parsed == "ignore":
        # A draft or prerelease is not a release. Keep the last stable one.
        _remember(path, now, kept, cached["latest"])
        return _line(cached["latest"], current)
    if status != 200 or parsed is None:
        _remember(path, now, cached["etag"], cached["latest"])
        return _line(cached["latest"], current)
    _remember(path, now, kept, parsed)
    return _line(parsed, current)


def notice(*, fetch=None, now=None, current=None, timeout=TIMEOUT):
    """One line when a newer stable release is known, else None. Never raises."""
    if _disabled():
        return None
    try:
        return _notice(
            fetch or fetch_release,
            time.time() if now is None else now,
            current or current_version(),
            timeout,
        )
    except Exception:
        return None
