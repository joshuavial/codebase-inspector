"""Viewer editor URLs, including a Windows drive letter. No browser."""

import json
import subprocess
from pathlib import Path

SCRIPT = Path(__file__).parents[1] / "src" / "cbi" / "viewer" / "open-editor.js"

DRIVER = r"""
const fs = require("fs");
const vm = require("vm");
const sandbox = {
  location: { protocol: "file:", pathname: "" },
  document: {
    getElementById() { return null; },
    createElement() { return { style: {}, setAttribute() {}, select() {}, remove() {} }; },
    body: { append() {} },
    execCommand() { return false; },
  },
};
sandbox.window = sandbox;
vm.createContext(sandbox);
vm.runInContext(fs.readFileSync(process.argv[1], "utf8"), sandbox);
const spec = JSON.parse(process.argv[2]);
sandbox.location.pathname = spec.pathname || "";
sandbox.location.protocol = "file:";
sandbox.cbiSetEditor({ editor: spec.editor || "vscode", root: spec.root || "" });
process.stdout.write(sandbox.cbiEditorHref(spec.file, spec.line));
"""


def href(**spec):
    result = subprocess.run(
        ["node", "-e", DRIVER, str(SCRIPT), json.dumps(spec)],
        check=True, capture_output=True, text=True,
    )
    return result.stdout


def test_unix_editor_href_keeps_the_leading_slash():
    assert href(root="/Users/me/repo", file="src/a.ts", line=1) == (
        "vscode://file/Users/me/repo/src/a.ts:1"
    )


def test_windows_drive_letter_is_not_encoded():
    assert href(root="C:\\repo", file="src\\a.ts", line=4) == "vscode://file/C:/repo/src/a.ts:4"
    assert href(root="C:/repo", file="my file.ts", line=2) == "vscode://file/C:/repo/my%20file.ts:2"


def test_windows_file_url_pathname_drops_the_extra_slash():
    got = href(root="", file="src/a.ts", line=1, pathname="/C:/repo/.cbi/viewer/index.html")
    assert got == "vscode://file/C:/repo/src/a.ts:1"
