"""Env var reads, defaults, spreads and declarations. A real .env file is never opened."""

import json
import os
import sqlite3
from pathlib import Path

import pytest

from cbi.cli import main
from cbi.env import compose_vars, example_vars, wrangler_vars
from cbi.files import is_private_env

WS = "local:repo"
FILES = {
    "src/reads.ts": """\
export function configured(): string {
  const a = process.env.FOO;
  const b = process.env["BAR"];
  const c = process.env['BAZ'] ?? "baz-default";
  const d = import.meta.env.QUX || "qux-default";
  const e = import.meta.env["QUUX"] ?? "";
  const f = process.env.NUM ?? 1;
  const g = (process.env.PAREN as string) ?? "p";
  const h = process.env.BANG! || "b";
  process.env.WRITTEN = "no";
  const chain = process.env.CHAIN_A ?? process.env.CHAIN_B ?? "z";
  const shared = process.env.SHARED ?? "ts";
  return a + b + c + d + e + String(f) + g + h + chain + shared;
}

export function twice(): string {
  const first = process.env.TWICE ?? "first";
  return (process.env.TWICE || "second") + first;
}

export function outer(): string {
  function inner() { return process.env.FROM_INNER; }
  return inner();
}

export class Box {
  load(): string { return process.env.FROM_METHOD ?? "m"; }
}

export const pass = () => process.env.FROM_ARROW ?? "arrow";

export const top = process.env.TOP_LEVEL;

export function spread(): object {
  return { ...process.env };
}
const forwarded = { ...process.env };
function hiddenSpread(process: { env: Record<string, string> }) {
  return { ...process.env, HIDDEN: process.env.HIDDEN };
}

export const wrangler = process.env.WRANGLER_VAR;
""",
    "src/plain.js": """\
export function fromJs() {
  return process.env.FROM_JS || "js";
}
export function fromJsBracket() {
  return process.env["FROM_JS_BRACKET"];
}
""",
    "src/reads.test.ts": """\
import test from "node:test";

test("reads env", () => {
  process.env.FROM_TEST ?? "t";
});
""",
    "src/app.py": """\
import os
import os as operating_system
from os import environ as env
from os import getenv

os.environ["PY_TOP"]

def read():
    os.environ["FOO"]
    os.environ.get("PY_GET", "bar-default")
    os.getenv("PY_GETENV", "c")
    operating_system.environ["PY_ALIAS_ENV"]
    operating_system.getenv("PY_ALIAS_GET", "q")
    env["PY_ENV_ALIAS"]
    env.get("PY_ENV_GET", "g")
    getenv("PY_GETENV_IMPORTED", "p")
    os.environ.get("PY_INT", 1)
    os.environ.get("PY_KW", default="kw")
    os.environ["PY_WRITTEN"] = "no"
    del os.environ["PY_DELETED"]
    os.environ["lower"]
    name = "PY_DYNAMIC"
    os.environ[name]
    os.environ.get("SHARED", "py")

def shadowed(os):
    os.environ["HIDDEN_OS"]
    os.getenv("HIDDEN_GET")
""",
    "src/direct.py": """\
from os import environ, getenv

def load():
    environ["DIRECT"]
    environ.get("DIRECT_GET", "dg")
    getenv("DIRECT_GETENV", "g2")

def shadowed(environ, getenv):
    environ["HIDDEN_ENV"]
    getenv("HIDDEN_GETENV")
""",
    ".env.example": """\
# comment
FOO=from-example
BAZ=
export UNREAD_EXAMPLE=only-declared
QUOTED="a b"
TAIL="a b" # c
COMMENTED=value # note
SINGLE='x y'
EQUALS=a=b
SPACED=a b
lower=no
NOT A LINE
""",
    ".env.sample": "FOO=from-sample\nSAMPLE_ONLY=s\n",
    ".env": "SECRET=real-secret\nFOO=should-not-appear\n",
    ".env.local": "LOCAL_SECRET=local-secret\n",
    ".env.production": "PROD_SECRET=prod-secret\n",
    ".env.example.local": "EXAMPLE_LOCAL_SECRET=example-local-secret\n",
    "compose.yaml": """\
services:
  api:
    image: app
    environment:
      FOO: from-compose
      COMPOSE_MAP: mapped
  worker:
    image: app
    environment:
      - COMPOSE_LIST=1
      - COMPOSE_BARE
      - lower=no
  flow:
    image: app
    environment: {FLOW_MAP: x}
  flowlist:
    image: app
    environment: [FLOW_LIST=1]
""",
    "edge/wrangler.toml": """\
name = "edge"
main = "src/reads.ts"

[vars]
WRANGLER_VAR = "w"
UNREAD_WRANGLER = "u"
lower = "no"

[env.production.vars]
PROD_ONLY = "p"
""",
}

EXAMPLE = (
    ".env.example",
    {"declared_in": [".env.example"], "example": None},
)
ATTRS = {
    "FOO": {"declared_in": [".env.example", ".env.sample", "compose.yaml"], "example": "from-example"},
    "BAZ": {"declared_in": [".env.example"], "example": ""},
    "WRANGLER_VAR": {"declared_in": ["edge/wrangler.toml"]},
    "UNREAD_EXAMPLE": {"declared_in": [".env.example"], "example": "only-declared"},
    "QUOTED": {"declared_in": [".env.example"], "example": "a b"},
    "TAIL": {"declared_in": [".env.example"], "example": "a b"},
    "COMMENTED": {"declared_in": [".env.example"], "example": "value"},
    "SINGLE": {"declared_in": [".env.example"], "example": "x y"},
    "EQUALS": {"declared_in": [".env.example"], "example": "a=b"},
    "SPACED": {"declared_in": [".env.example"], "example": "a b"},
    "SAMPLE_ONLY": {"declared_in": [".env.sample"], "example": "s"},
    "COMPOSE_MAP": {"declared_in": ["compose.yaml"]},
    "COMPOSE_LIST": {"declared_in": ["compose.yaml"]},
    "COMPOSE_BARE": {"declared_in": ["compose.yaml"]},
    "FLOW_MAP": {"declared_in": ["compose.yaml"]},
    "FLOW_LIST": {"declared_in": ["compose.yaml"]},
    "UNREAD_WRANGLER": {"declared_in": ["edge/wrangler.toml"]},
}
EDGES = {
    "FOO": [("src/app.py#read", 1, None), ("src/reads.ts#configured", 1, None)],
    "BAR": [("src/reads.ts#configured", 1, None)],
    "BAZ": [("src/reads.ts#configured", 1, "baz-default")],
    "QUX": [("src/reads.ts#configured", 1, "qux-default")],
    "QUUX": [("src/reads.ts#configured", 1, "")],
    "NUM": [("src/reads.ts#configured", 1, None)],
    "PAREN": [("src/reads.ts#configured", 1, "p")],
    "BANG": [("src/reads.ts#configured", 1, "b")],
    "CHAIN_A": [("src/reads.ts#configured", 1, None)],
    "CHAIN_B": [("src/reads.ts#configured", 1, None)],
    "SHARED": [("src/app.py#read", 1, "py"), ("src/reads.ts#configured", 1, "ts")],
    "TWICE": [("src/reads.ts#twice", 2, "first")],
    "FROM_INNER": [("src/reads.ts#outer", 1, None)],
    "FROM_METHOD": [("src/reads.ts#Box.load", 1, "m")],
    "FROM_ARROW": [("src/reads.ts#pass", 1, "arrow")],
    "TOP_LEVEL": [("src/reads.ts", 1, None)],
    "WRANGLER_VAR": [("src/reads.ts", 1, None)],
    "FROM_JS": [("src/plain.js#fromJs", 1, "js")],
    "FROM_JS_BRACKET": [("src/plain.js#fromJsBracket", 1, None)],
    "FROM_TEST": [("src/reads.test.ts#reads env", 1, "t")],
    "PY_TOP": [("src/app.py", 1, None)],
    "PY_GET": [("src/app.py#read", 1, "bar-default")],
    "PY_GETENV": [("src/app.py#read", 1, "c")],
    "PY_ALIAS_ENV": [("src/app.py#read", 1, None)],
    "PY_ALIAS_GET": [("src/app.py#read", 1, "q")],
    "PY_ENV_ALIAS": [("src/app.py#read", 1, None)],
    "PY_ENV_GET": [("src/app.py#read", 1, "g")],
    "PY_GETENV_IMPORTED": [("src/app.py#read", 1, "p")],
    "PY_INT": [("src/app.py#read", 1, None)],
    "PY_KW": [("src/app.py#read", 1, "kw")],
    "DIRECT": [("src/direct.py#load", 1, None)],
    "DIRECT_GET": [("src/direct.py#load", 1, "dg")],
    "DIRECT_GETENV": [("src/direct.py#load", 1, "g2")],
}
SECRETS = (b"real-secret", b"local-secret", b"prod-secret", b"example-local-secret", b"dev-secret", b"should-not-appear")


def model(root):
    conn = sqlite3.connect(root / ".cbi" / "model.db")
    nodes = {}
    for nid, name, parent, attrs in conn.execute("SELECT id, name, parent_id, attrs FROM nodes WHERE kind = 'env'"):
        nodes[name] = {"id": nid, "parent": parent, "attrs": json.loads(attrs) if attrs else None}
    edges = {}
    for src, dst, weight, attrs in conn.execute("SELECT src, dst, weight, attrs FROM edges WHERE kind = 'reads_env'"):
        name = dst.split(":env:", 1)[1]
        default = json.loads(attrs)["default"] if attrs else None
        edges.setdefault(name, []).append((src.removeprefix(WS + ":"), weight, default))
    for found in edges.values():
        found.sort()
    meta = conn.execute("SELECT DISTINCT source, confidence FROM edges WHERE kind = 'reads_env'").fetchall()
    return nodes, edges, meta


def run(capsys, *argv):
    capsys.readouterr()
    code = main(list(argv))
    out = capsys.readouterr()
    return code, out.out, out.err


def run_json(capsys, *argv):
    code, out, err = run(capsys, *argv, "--json")
    assert code == 0, err
    return json.loads(out)


@pytest.fixture
def scanned(make_repo, monkeypatch):
    root = make_repo(FILES, name="repo")
    (root / ".env.development").write_text("DEV_SECRET=dev-secret\n")
    opened = []
    real = open

    def spy(file, *args, **kwargs):
        try:
            opened.append(os.fspath(file))
        except TypeError:
            pass
        return real(file, *args, **kwargs)

    monkeypatch.setattr("builtins.open", spy)
    monkeypatch.chdir(root)
    assert main(["init"]) == 0
    assert main(["scan"]) == 0
    return root, opened


@pytest.mark.parametrize("path, private", [
    (".env", True), (".env.local", True), ("app/.env.production", True), (".env.example.local", True),
    (".env.example", False), ("a/.env.sample", False), ("env.ts", False), (".environment", False),
])
def test_private_env_names(path, private):
    assert is_private_env(path) is private


def test_declaration_text():
    assert example_vars(FILES[".env.example"]) == {
        "FOO": "from-example", "BAZ": "", "UNREAD_EXAMPLE": "only-declared", "QUOTED": "a b", "TAIL": "a b",
        "COMMENTED": "value", "SINGLE": "x y", "EQUALS": "a=b", "SPACED": "a b",
    }
    assert compose_vars(FILES["compose.yaml"]) == [
        "FOO", "COMPOSE_MAP", "COMPOSE_LIST", "COMPOSE_BARE", "FLOW_MAP", "FLOW_LIST"]
    assert wrangler_vars(FILES["edge/wrangler.toml"]) == ["WRANGLER_VAR", "UNREAD_WRANGLER"]


def test_reads_defaults_spreads_and_declarations(scanned):
    root, _ = scanned
    nodes, edges, meta = model(root)
    assert meta == [("treesitter", 1.0)]
    assert edges == EDGES
    assert set(nodes) == set(EDGES) | set(ATTRS)
    for name, node in nodes.items():
        assert node["id"] == f"{WS}:env:{name}" and node["parent"] is None
        assert node["attrs"] == ATTRS.get(name)
    absent = {"WRITTEN", "HIDDEN", "HIDDEN_OS", "HIDDEN_GET", "HIDDEN_ENV", "HIDDEN_GETENV",
              "PY_WRITTEN", "PY_DELETED", "PY_DYNAMIC", "PROD_ONLY", "lower", "SECRET"}
    assert absent.isdisjoint(nodes)


def test_private_env_files_are_never_opened(scanned):
    root, opened = scanned
    bad = []
    for raw in opened:
        try:
            rel = Path(raw).resolve().relative_to(root.resolve())
        except (ValueError, OSError):
            continue
        if is_private_env(rel.as_posix()):
            bad.append(rel.as_posix())
    assert bad == []
    assert any(Path(raw).name == ".env.example" for raw in opened)
    blob = (root / ".cbi" / "model.db").read_bytes()
    for secret in SECRETS:
        assert secret not in blob
    paths = {row[0] for row in sqlite3.connect(root / ".cbi" / "model.db").execute("SELECT path FROM nodes")}
    assert ".env" not in paths and ".env.local" not in paths and ".env.production" not in paths
    assert ".env.example" in paths and ".env.sample" in paths


def test_show_and_search(scanned, capsys):
    shown = run_json(capsys, "show", "FOO")
    assert shown["kind"] == "env" and shown["display_kind"] == "env var"
    assert shown["attrs"]["example"] == "from-example"
    assert shown["attrs"]["declared_in"] == [".env.example", ".env.sample", "compose.yaml"]
    assert sorted(e["id"].removeprefix(WS + ":") for e in shown["incoming"] if e["kind"] == "reads_env") == [
        "src/app.py#read", "src/reads.ts#configured"]
    code, out, _ = run(capsys, "show", "FOO")
    assert code == 0 and "FOO (env var)" in out
    assert "declared in: .env.example, .env.sample, compose.yaml" in out and "example: from-example" in out
    assert "src/app.py" in out and "src/reads.ts" in out

    code, out, _ = run(capsys, "show", "BAZ")
    assert "  example: \n" in out
    configured = run_json(capsys, "show", "src/reads.ts#configured")
    by_name = {e["name"]: e for e in configured["outgoing"] if e["kind"] == "reads_env"}
    assert by_name["BAZ"]["attrs"] == {"default": "baz-default"}
    assert by_name["QUUX"]["attrs"] == {"default": ""}
    assert by_name["NUM"]["attrs"] is None
    assert "WRITTEN" not in by_name and "lower" not in by_name
    code, out, _ = run(capsys, "show", "src/reads.ts#configured")
    assert "default='baz-default'" in out

    whole = run_json(capsys, "show", "src/reads.ts")
    passed = {e["name"]: e for e in whole["outgoing"] if e["kind"] == "reads_env"}
    assert "*" not in passed and "TOP_LEVEL" in passed and "FOO" not in passed
    assert [d for d in whole["diagnostics"] if d["kind"] == "env_passthrough"] == [
        {"kind": "env_passthrough", "detail": "passes whole environment"}]
    code, out, _ = run(capsys, "show", "src/reads.ts")
    assert "passes whole environment" in out and "TOP_LEVEL" in out and "*" not in out
    assert "env_passthrough" not in out
    code, out, err = run(capsys, "show", "*")
    assert code == 1 and out == "" and "no node matches" in err

    hits = run_json(capsys, "search", "UNREAD_EXAMPLE")
    assert [h["id"] for h in hits if h["kind"] == "env"] == [f"{WS}:env:UNREAD_EXAMPLE"]
    assert run_json(capsys, "search", "SAMPLE_ONLY", "--kind", "env var")[0]["display_kind"] == "env var"


def test_rescan_drops_stale_env_nodes(scanned, capsys):
    root, opened = scanned
    source = root / "src" / "reads.ts"
    source.write_text(source.read_text().replace("export const top = process.env.TOP_LEVEL;\n", ""))
    example = root / ".env.example"
    example.write_text(example.read_text().replace("export UNREAD_EXAMPLE=only-declared\n", ""))
    assert main(["scan"]) == 0
    nodes, edges, _ = model(root)
    assert "TOP_LEVEL" not in nodes and "UNREAD_EXAMPLE" not in nodes and "FOO" in nodes
    assert "TOP_LEVEL" not in edges and "*" not in nodes and "*" not in edges
    detail = sqlite3.connect(root / ".cbi" / "model.db").execute(
        "SELECT detail FROM diagnostics WHERE kind = 'env_passthrough'").fetchall()
    assert detail == [("passes whole environment",)]
    bad = [raw for raw in opened if Path(raw).name in {".env", ".env.local", ".env.production", ".env.development", ".env.example.local"}]
    assert bad == []
