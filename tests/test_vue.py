"""Vue single-file components: script blocks as TypeScript, template tags as renders."""

import json
import os
import sqlite3
from pathlib import Path

from cbi.cli import main
from cbi.parse import vue

GOLDEN = Path(__file__).parent / "golden" / "vue.txt"

HELLO = """\
<script lang="ts">
import UserCard from "./user-card.vue";

/** A hello. */
export default function Hello() {
  return 1;
}
</script>
<template>
  <UserCard />
  <user-card />
  <span>no</span>
  <NotImported />
</template>
"""

USER_CARD = """\
<template>
  <span />
</template>
<script setup lang="ts">
export function label() {
  return "x";
}
</script>
"""

SPEC = """\
import { test } from "vitest";
import Hello from "./Hello.vue";

test("renders", () => {
  Hello();
});
"""

FILES = {
    "components/Hello.vue": HELLO,
    "components/user-card.vue": USER_CARD,
    "components/Hello.spec.ts": SPEC,
}


SETTINGS = """\
<template>
  <a href="/api/partner/connect">Connect</a>
  <a href="/api/notes?x=1">Notes</a>
  <a href="/notes">Page</a>
  <a href="https://example.com/api/x">Out</a>
  <a href="#top">Top</a>
</template>
<script setup lang="ts">
export function saveItem() {
  return 1;
}
</script>
"""


def test_vue_api_href_is_a_get_on_the_component():
    defs, facts, err = vue.parse(SETTINGS.encode(), "vue", False, "pages/SettingsPage.vue")
    assert not err
    component = next(i for i, d in enumerate(defs) if d["display_kind"] == "component")
    assert defs[component]["qualname"] == "SettingsPage"
    calls = [(None if caller is None else defs[caller]["qualname"], method, path)
             for caller, method, path in facts["http_calls"]]
    assert calls == [
        ("SettingsPage", "GET", "/api/partner/connect"),
        ("SettingsPage", "GET", "/api/notes"),
    ]
    defs, facts, err = vue.parse(SETTINGS.encode(), "vue", True, "pages/SettingsPage.spec.vue")
    assert facts["http_calls"] == []


def test_vue_script_becomes_a_component():
    defs, facts, err = vue.parse(HELLO.encode(), "vue", False, "components/Hello.vue")
    assert not err
    hello = next(d for d in defs if d["name"] == "Hello")
    assert hello["display_kind"] == "component"
    assert hello["qualname"] == "Hello"
    assert hello["doc"] == "A hello."
    assert hello["start_line"] == HELLO.splitlines().index("export default function Hello() {") + 1
    assert facts["exports"]["default"] == "Hello"
    jsx = [call for call in facts["calls"] if call[-1] == "jsx"]
    assert len(jsx) == 2
    assert {call[3] for call in jsx} == {"UserCard"}
    assert all(call[0] == defs.index(hello) for call in jsx)
    assert not any(call[3] == "span" or call[3] == "NotImported" for call in facts["calls"])


def test_vue_script_setup_offsets_lines_and_names_the_file():
    defs, facts, err = vue.parse(USER_CARD.encode(), "vue", False, "components/user-card.vue")
    assert not err
    label = next(d for d in defs if d["name"] == "label")
    component = next(d for d in defs if d["name"] == "user-card")
    assert label["display_kind"] == "function"
    assert label["start_line"] == USER_CARD.splitlines().index("export function label() {") + 1
    assert component["display_kind"] == "component"
    assert component["signature"] == "component user-card"
    assert component["start_line"] == 1
    assert component["end_line"] == len(USER_CARD.splitlines())
    assert facts["exports"]["default"] == "user-card"
    assert facts["calls"] == []

    routed = "<template><div /></template>\n<script lang=\"ts\">\nconst routes = [{ path: \"/home\", component: Home }]\n</script>\n"
    defs, facts, err = vue.parse(routed.encode(), "vue", False, "App.vue")
    assert not err
    route = next(d for d in defs if d["display_kind"] == "route")
    assert route["name"] == "/home" and route["start_line"] == routed.splitlines().index("const routes = [{ path: \"/home\", component: Home }]") + 1
    assert facts["routes"][0]["path"] == "/home" and facts["routes"][0]["def"] == defs.index(route)

    plain = "<script>\nexport default function Bar() { return 1; }\n</script>\n"
    defs, facts, err = vue.parse(plain.encode(), "vue", False, "Bar.vue")
    assert not err
    assert [d["name"] for d in defs] == ["Bar"]
    assert defs[0]["display_kind"] == "component"
    assert defs[0]["start_line"] == 2


def dump(root):
    conn = sqlite3.connect(root / ".cbi" / "model.db")
    lines = [json.dumps(["node", *r]) for r in conn.execute(
        "SELECT id, parent_id, kind, display_kind, start_line, end_line, signature, doc "
        "FROM nodes WHERE kind IN ('symbol', 'test') ORDER BY id")]
    lines += [json.dumps(["edge", *r]) for r in conn.execute(
        "SELECT kind, source, src, dst, confidence, weight FROM edges ORDER BY kind, source, src, dst")]
    lines += [json.dumps(["diagnostic", *r]) for r in conn.execute(
        "SELECT kind, node_id, detail FROM diagnostics ORDER BY kind, node_id")]
    return "".join(line + "\n" for line in lines)


def test_vue_resolution(make_repo, monkeypatch, capsys):
    root = make_repo(FILES)
    monkeypatch.chdir(root)
    assert main(["init"]) == 0
    assert main(["scan"]) == 0
    capsys.readouterr()
    conn = sqlite3.connect(root / ".cbi" / "model.db")
    nodes = {r[0].split("#", 1)[-1]: (r[1], r[2], r[3]) for r in conn.execute(
        "SELECT id, kind, display_kind, doc FROM nodes WHERE kind IN ('symbol', 'test')")}
    assert nodes["Hello"] == ("symbol", "component", "A hello.")
    assert nodes["user-card"][1] == "component"
    assert nodes["label"] == ("symbol", "function", None)
    assert nodes["renders"][0] == "test"

    calls = {}
    for src, dst, conf, weight, attrs in conn.execute(
            "SELECT s.id, d.id, e.confidence, e.weight, e.attrs FROM edges e "
            "JOIN nodes s ON s.id = e.src JOIN nodes d ON d.id = e.dst WHERE e.kind = 'calls'"):
        calls[(src.split("#", 1)[-1], dst.split("#", 1)[-1])] = (
            conf, weight, json.loads(attrs) if attrs else None)
    assert calls[("Hello", "user-card")] == (1.0, 2, {"via": "jsx"})
    assert ("renders", "Hello") in calls

    linked = {(s.split("#", 1)[-1], d.split("#", 1)[-1]) for s, d in conn.execute(
        "SELECT src, dst FROM edges WHERE kind = 'tests'")}
    assert ("renders", "Hello") in linked
    file_tests = {(s.split(":")[-1], d.split(":")[-1]) for s, d, source in conn.execute(
        "SELECT src, dst, source FROM edges WHERE kind = 'tests' AND source = 'naming'")}
    assert ("components/Hello.spec.ts", "components/Hello.vue") in file_tests
    unmatched = conn.execute("SELECT count(*) FROM diagnostics WHERE kind = 'unmatched_test'").fetchone()[0]
    assert unmatched == 0


def test_golden_vue(make_repo, monkeypatch, capsys):
    root = make_repo(FILES)
    monkeypatch.chdir(root)
    assert main(["init"]) == 0
    assert main(["scan"]) == 0
    capsys.readouterr()
    text = dump(root)
    if os.environ.get("CBI_UPDATE_GOLDEN"):
        GOLDEN.write_text(text)
    assert text == GOLDEN.read_text()
