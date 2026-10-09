"""The installer is not run here. These checks lock its contract."""

import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "install-app.sh"


def _bash():
    """Git bash. `bash` on PATH is the system32 stub, which strips backslashes out of the script path."""
    if sys.platform == "win32":
        for env_name in ("ProgramFiles", "ProgramFiles(x86)"):
            root = os.environ.get(env_name)
            if not root:
                continue
            candidate = Path(root) / "Git" / "bin" / "bash.exe"
            if candidate.is_file():
                return str(candidate)
        return None
    return shutil.which("bash")


def _bash_script(path):
    text = str(path)
    if sys.platform == "win32" and len(text) > 2 and text[1] == ":":
        return "/" + text[0].lower() + text[2:].replace("\\", "/")
    return text


def _code(text):
    lines = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        lines.append(stripped)
    return "\n".join(lines)


def test_install_script_contract():
    text = SCRIPT.read_text()
    code = _code(text)
    assert text.startswith("#!/usr/bin/env bash\n")
    assert "set -euo pipefail\n" in text
    assert os.access(SCRIPT, os.X_OK)
    assert "sudo" not in code
    assert "eval " not in code
    assert "$1" not in code
    assert "[[ $# -ne 0 ]]" in code
    assert "uv tool install --force --editable" in code
    assert "npm run package" in code
    assert 'dest="/Applications/Codebase Inspector.app"' in code
    assert 'ditto "$src" "$dest.new"' in code
    assert 'mv "$dest" "$dest.prev"' in code
    assert 'mv "$dest.new" "$dest"' in code
    assert 'open -g "$dest"' in code
    assert 'rm -rf "$dest"' in code
    assert 'mv "$dest.prev" "$dest"' in code
    assert "CFBundleShortVersionString" in code
    assert 'quit app "Codebase Inspector"' in code
    bash = _bash()
    assert bash, "bash is required to syntax-check scripts/install-app.sh"
    env = os.environ.copy()
    if sys.platform == "win32":
        env["MSYS_NO_PATHCONV"] = "1"
    subprocess.run([bash, "-n", _bash_script(SCRIPT)], check=True, env=env)
