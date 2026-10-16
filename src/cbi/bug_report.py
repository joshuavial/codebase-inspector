"""Public issue drafts. Never inspect the repository or include process arguments."""

import platform
import re
from pathlib import Path
from urllib.parse import urlencode

ISSUE_URL = "https://github.com/joshuavial/codebase-inspector/issues/new"
MAX_URL = 7900
TRIMMED = "\n[trimmed]"


def strip_paths(text):
    """Remove home, POSIX, drive-letter and UNC paths, including quoted spaces."""
    home = str(Path.home())
    text = text.replace(home, "<path>") if home not in ("", "/") else text
    text = re.sub(r'''(["'])(?:[A-Za-z]:[\\/]|/|\\\\|~/)[^\n]*?\1''', "<path>", text)
    return re.sub(r'''(?:<path>|\bfile:/{2,3}|(?<![\w])[A-Za-z]:[\\/]|\\\\|(?<![\w])~/|(?<![\w])/)[^\s<>"'(),;]*''', "<path>", text)


# Free-form engine errors can contain concept names, table names, source or URLs.
# Retain only whole known diagnostics; even ordinary words may be repository data.
DIAGNOSTICS = (
    "[trimmed]", "Layout failed", "no layout", "Cannot read properties of undefined",
    "Cannot read properties of null", "Maximum call stack size exceeded",
    "Permission denied", "No such file or directory", "out of memory",
    "cbi build did not write the viewer.", "Chrome timed out",
)


def safe_error(text):
    text = strip_paths(text)
    pattern = "|".join(re.escape(s) for s in (*DIAGNOSTICS, "<path>"))
    parts = re.split(f"({pattern})", text)
    return "".join(part if part in (*DIAGNOSTICS, "<path>") else
                   (" <detail> " if part.strip(" :\n\t.,") else part)
                   for part in parts).strip()


def _version(value):
    return value if re.fullmatch(r"[0-9][0-9A-Za-z.+-]{0,79}", value) else "unavailable"


def build_url(*, version, title="", message="", app_version=None, view="cbi bug", error=""):
    view = view if view in ("cbi bug", "Help menu", "Map", "Mapping") else "Map"
    environment = [f"cbi: {_version(version)}"]
    if app_version is not None:
        environment.append(f"App: {_version(app_version)}")
    environment.extend((f"OS: {platform.system()} {platform.release()}",
                        f"Architecture: {platform.machine()}",
                        f"Python: {platform.python_version()}", f"Command or view: {view}"))
    fields = {"template": "bug_report.yml", "title": strip_paths(title)[:200],
              "happened": strip_paths(message) if message else safe_error(error),
              "environment": "\n".join(environment)}
    def url():
        return ISSUE_URL + "?" + urlencode(fields)
    # Trim against encoded length, including multibyte Unicode and the marker.
    original = fields["happened"]
    if len(url()) > MAX_URL:
        low, high = 0, len(original)
        while low < high:
            mid = (low + high + 1) // 2
            fields["happened"] = original[:mid] + TRIMMED
            if len(url()) <= MAX_URL:
                low = mid
            else:
                high = mid - 1
        fields["happened"] = original[:low] + TRIMMED
    return url()
