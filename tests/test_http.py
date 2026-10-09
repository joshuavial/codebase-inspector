"""HTTP routes, client calls, and the edges that join them."""

import json
import sqlite3

from cbi import build
from cbi.cli import main
from cbi.http import from_pieces, score
from cbi.parse import csharp, python, symbol_nodes, typescript

WS = "local:repo"

FILES = {
    "app/pyproject.toml": '[project]\nname = "api"\nversion = "0.0.0"\n',
    "app/api/__init__.py": "",
    "app/api/public.py": '''\
from fastapi import APIRouter

router = APIRouter()

@router.get("/ping")
def ping():
    return {}
''',
    "app/api/server.py": '''\
from fastapi import FastAPI, APIRouter
from api.admin import items
from api import public

app = FastAPI()
v1 = APIRouter(prefix="/v1")
v1.include_router(items.router)
v1.include_router(public.router, prefix="/public")
app.include_router(v1)

@app.get("/health")
def health():
    return {}
''',
    "app/api/admin/__init__.py": "",
    "app/api/admin/items.py": '''\
from fastapi import APIRouter

router = APIRouter(prefix="/admin/items")

@router.get("/mine")
def list_mine():
    return []

@router.get("/{item_id}")
def get_item(item_id: str):
    return {}

@router.post("/")
def create_item():
    return {}

def meta(row):
    return row.get("name")
''',
    "cli/api.ts": '''\
class FsClient {
  request(method, path) {
    return fetch(path, { method });
  }
  listMine(qs) {
    const suffix = qs ? `?${qs}` : "";
    return this.request("GET", `/admin/items/mine${suffix}`);
  }
  missing() {
    return this.request("GET", "/no/such");
  }
  byFetch() {
    return fetch("/health");
  }
  byAxios(id) {
    return axios.get(`/users/${id}`);
  }
}

function load(path) {
  return fetch(path);
}

export function loaded() {
  return load("/health");
}

export function ready() {
  return fetch("/ready");
}
''',
    "cli/api.test.ts": '''\
export function ignored() {
  return fetch("/should-not-match");
}
''',
    "web/server.js": '''\
const express = require("express");
const app = express();

function listUsers(req, res) {}

app.get("/users/:id", listUsers);
''',
    "web/client.ts": '''\
function request(method, path) {
  return fetch(path, { method });
}

export function leases() {
  return request("GET", "/api/leases");
}

export function lease(id) {
  return request("GET", `/api/leases/${id}`);
}

export function flags() {
  return request("POST", "/api/flags");
}

export function ping() {
  return fetch("/public/ping");
}
''',
    "api/LeasesController.cs": '''\
namespace Api;

[Route("api/leases")]
public class LeasesController
{
    [HttpGet]
    public object List() => null;

    [HttpGet("{id:int}")]
    public object Get(int id) => null;

    [HttpPost("{id:int}/reviews")]
    public object Review(int id) => null;
}
''',
    "api/Program.cs": '''\
var app = WebApplication.CreateBuilder(args).Build();
app.MapGet("/ready", () => "ok");
var api = app.MapGroup("/api");
api.MapPost("/flags", GetFlags);

void GetFlags() {}
''',
}


def test_path_pieces_and_scores():
    assert from_pieces(["/admin/proposed-edits/mine", None]) == "/admin/proposed-edits/mine"
    assert from_pieces(["/admin/fs/", None, "/revisions", None]) == "/admin/fs/{param}/revisions"
    assert from_pieces([None, "/admin/", None, "/x", None]) == "/admin/{param}/x"
    assert from_pieces(["/admin/proposed-edits/amendments?", None]) == "/admin/proposed-edits/amendments"
    assert from_pieces(["/api/invoices?leaseId=", None]) == "/api/invoices"
    assert from_pieces(["/users/", None]) == "/users/{param}"
    assert score("/mine", "/{edit_id}") is None
    assert score("/admin/items/mine", "/v1/admin/items/mine") == (3, 3, 1)
    assert score("/users/{param}", "/users/{id}") == (2, 1, 0)
    assert score("/health", "/health") == (1, 1, 0)


def test_template_and_fstring_calls():
    ts = '''\
export function add(id, extra) {
  const path = extra ? `/admin/items/${id}` : "/admin/items/mine";
  return request("POST", path);
}
function request(method, path) {
  return fetch(path, { method });
}
'''
    defs, facts, err = typescript.parse(ts.encode(), "typescript", False)
    assert not err
    calls = _named(defs, facts["http_calls"])
    assert ("add", "POST", "/admin/items/{param}") in calls
    assert ("add", "POST", "/admin/items/mine") in calls
    assert all(name != "request" for name, _method, _path in calls)

    py = '''\
def load(uid, qs):
    return httpx.get(f"/admin/fs/{uid}/revisions{qs}")
'''
    defs, facts, err = python.parse(py.encode(), "python", False)
    assert not err
    assert _named(defs, facts["http_calls"]) == [("load", "GET", "/admin/fs/{param}/revisions")]


def test_next_app_route_files_define_endpoints_from_exported_verbs():
    source = b'''\
export async function GET() { return Response.json([]); }
export async function DELETE() { return new Response(null); }
function POST() { return new Response(null); }
'''
    nodes, facts, err = symbol_nodes(
        "file:route", WS, "teacher/app/(secure)/api/courses/[id]/route.ts", "typescript", source, False)
    assert not err
    names = {node["id"]: node["name"] for node in nodes}
    assert {(names[handler], method, path) for handler, method, path, _router, _name in facts["http_routes"]} == {
        ("DELETE", "DELETE", "/api/courses/{id}"),
        ("GET", "GET", "/api/courses/{id}"),
    }


def test_factory_router_prefixes_and_testclient_only_apps(make_repo, monkeypatch, capsys):
    root = make_repo({
        "api.py": '''\
from fastapi import APIRouter

def routes():
    router = APIRouter(prefix="/v1/operations")

    @router.post("/consume")
    def consume():
        return {}

    return router
''',
        "diagnose.py": '''\
from fastapi import FastAPI
from fastapi.testclient import TestClient

app = FastAPI()

@app.get("/")
def diagnostic():
    return {}

client = TestClient(app)
''',
        "tests/helpers.py": '''\
from fastapi import FastAPI
helper_app = FastAPI()
@helper_app.get("/fixture-only")
def fixture_only():
    return {}
''',
        "integration/fake_engine.py": '''\
from fastapi import FastAPI
fake_app = FastAPI()
@fake_app.post("/fake-only")
def fake_only():
    return {}
''',
        "server.ts": '''\
const app = express();
const router = express.Router();
router.get("/items", listItems);
app.use("/api", router);
function listItems() {}
''',
    })
    monkeypatch.chdir(root)
    assert main(["init"]) == 0 and main(["scan"]) == 0
    capsys.readouterr()
    conn = sqlite3.connect(root / ".cbi" / "model.db")
    routes = {(method, path) for method, path in conn.execute(
        "SELECT json_extract(route.value, '$.method'), json_extract(route.value, '$.path') "
        "FROM nodes n, json_each(n.attrs, '$.http_routes') route")}
    assert ("POST", "/v1/operations/consume") in routes
    assert ("GET", "/api/items") in routes
    assert ("GET", "/") not in routes
    assert ("GET", "/fixture-only") not in routes
    assert ("POST", "/fake-only") not in routes


def test_csharp_attributes_and_minimal_apis():
    source = FILES["api/LeasesController.cs"] + "\n" + FILES["api/Program.cs"]
    _defs, facts, err = csharp.parse(source.encode(), "csharp", False)
    assert not err
    routes = {(method, path) for _handler, method, path, _router, _name in facts["http_routes"]}
    assert ("GET", "/api/leases") in routes
    assert ("GET", "/api/leases/{id}") in routes
    assert ("POST", "/api/leases/{id}/reviews") in routes
    assert ("GET", "/ready") in routes
    assert ("POST", "/api/flags") in routes


def test_scan_links_clients_to_routes(make_repo, monkeypatch, capsys):
    root = make_repo(FILES)
    monkeypatch.chdir(root)
    assert main(["init"]) == 0
    assert main(["scan"]) == 0
    capsys.readouterr()
    conn = sqlite3.connect(root / ".cbi" / "model.db")
    found = {
        (src, dst, method, path, conf, weight)
        for src, dst, method, path, conf, weight in (
            (row[0], row[1], attrs["method"], attrs["path"], row[2], row[3])
            for row in conn.execute(
                "SELECT s.name, d.name, e.confidence, e.weight, e.attrs "
                "FROM edges e JOIN nodes s ON s.id = e.src JOIN nodes d ON d.id = e.dst "
                "WHERE e.kind = 'http_calls'")
            for attrs in [json.loads(row[4])]
        )
    }
    assert ("listMine", "list_mine", "GET", "/v1/admin/items/mine", 0.8, 1) in found
    assert ("byFetch", "health", "GET", "/health", 1.0, 1) in found
    assert ("byAxios", "listUsers", "GET", "/users/{id}", 0.9, 1) in found
    assert ("loaded", "health", "GET", "/health", 1.0, 1) in found
    assert ("ready", "Program.cs", "GET", "/ready", 1.0, 1) in found
    assert ("leases", "List", "GET", "/api/leases", 1.0, 1) in found
    assert ("lease", "Get", "GET", "/api/leases/{id}", 0.9, 1) in found
    assert ("flags", "GetFlags", "POST", "/api/flags", 1.0, 1) in found
    assert ("ping", "ping", "GET", "/v1/public/ping", 0.8, 1) in found
    paths = {path for _src, _dst, _method, path, _conf, _weight in found}
    assert "/should-not-match" not in paths
    assert "/name" not in paths

    details = [row[0] for row in conn.execute(
        "SELECT detail FROM diagnostics WHERE kind = 'unmatched_http_call' ORDER BY detail")]
    assert "GET /no/such: no route" in details
    assert "GET /v1/admin/items/{item_id}: no client call" in details
    assert "POST /v1/admin/items: no client call" in details
    assert "POST /api/leases/{id}/reviews: no client call" in details
    assert not any("should-not-match" in detail for detail in details)

    assert main(["show", "listMine"]) == 0
    shown = capsys.readouterr().out
    assert "calls endpoints" in shown
    assert "GET /v1/admin/items/mine" in shown
    assert main(["show", "list_mine"]) == 0
    shown = capsys.readouterr().out
    assert "called by clients" in shown
    assert "GET /v1/admin/items/mine" in shown
    assert main(["search", "/v1/admin/items/mine"]) == 0
    assert "list_mine" in capsys.readouterr().out

    ws = conn.execute("SELECT id FROM nodes WHERE kind = 'workspace'").fetchone()[0]
    cli = f"{ws}:concept:cli"
    api = f"{ws}:concept:api"
    conn.execute(
        "INSERT INTO nodes (id, parent_id, kind, display_kind, name, workspace_id, summary, attrs) "
        "VALUES (?, ?, 'concept', 'App or process', 'CLI', ?, 'The client.', ?)",
        (cli, ws, ws, json.dumps({"role": "app", "order": 0})),
    )
    conn.execute(
        "INSERT INTO nodes (id, parent_id, kind, display_kind, name, workspace_id, summary, attrs) "
        "VALUES (?, ?, 'concept', 'service', 'API', ?, 'The server.', ?)",
        (api, ws, ws, json.dumps({"role": "service", "order": 1})),
    )
    for concept, path in (
        (cli, "cli/api.ts"), (cli, "web/client.ts"),
        (api, "app/api/server.py"), (api, "app/api/admin/items.py"), (api, "app/api/public.py"),
        (api, "web/server.js"), (api, "api/LeasesController.cs"), (api, "api/Program.cs"),
    ):
        fid = conn.execute("SELECT id FROM nodes WHERE kind = 'file' AND path = ?", (path,)).fetchone()[0]
        conn.execute(
            "INSERT INTO edges (src, dst, kind, source, confidence, weight, attrs) VALUES (?, ?, 'owns', 'judgement', 1, 1, NULL)",
            (concept, fid),
        )
    conn.execute(
        "INSERT INTO edges (src, dst, kind, source, confidence, weight, attrs) VALUES (?, ?, 'relates', 'judgement', 1, 1, ?)",
        (cli, api, json.dumps({"label": "calls"})),
    )
    conn.commit()
    # show opens the model immutable, which does not read the WAL.
    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")

    assert main(["show", cli, "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    relates = [edge for edge in payload["outgoing"] if edge["kind"] == "relates"]
    assert relates and relates[0]["endpoints"]
    paths = {(ep["method"], ep["path"]) for ep in relates[0]["endpoints"]}
    assert ("GET", "/v1/admin/items/mine") in paths
    assert ("GET", "/api/leases") in paths
    assert ("POST", "/api/flags") in paths

    view = build.concept_view(conn)
    rel = next(item for item in view["relationships"] if item["from"] == cli and item["to"] == api)
    assert ("GET", "/v1/public/ping") in {(ep["method"], ep["path"]) for ep in rel["endpoints"]}
    symbols = _symbols(view["concepts"])
    client = next(sym for sym in symbols if sym["name"] == "FsClient")
    assert any(row["method"] == "GET" and row["path"] == "/v1/admin/items/mine" for row in client["httpOut"])
    handler = next(sym for sym in symbols if sym["name"] == "list_mine")
    assert any(row["name"] == "listMine" for row in handler["httpIn"])


OBJECT_API = '''\
async function request<T>(method: string, path: string): Promise<T> {
  const response = await fetch(path, { method });
  return response.json();
}

export const api = {
  async raiseInvoice(id: number) {
    return request("POST", `/api/leases/${id}/invoices`);
  },
  ping: () => request("GET", "/api/ping"),
  plain: 1,
  nested: { inner() { return request("GET", "/api/inner"); } },
};

const hidden = {
  no() { return request("GET", "/api/hidden"); },
};

const local = {
  go() { return request("POST", "/api/go"); },
};
export { local };

export const config = { base: "/api" };

export const wrapped = {
  ready() { return request("GET", "/api/ready"); },
} as const;
'''

PAGE = '''\
import { api } from "./api";

export async function raiseInvoice(id: number) {
  await api.raiseInvoice(id);
}
'''

JSX_PAGE = '''\
export function Page() {
  return <a href="/api/accounting/connect">Connect</a>;
}
export function Other() {
  return <a href={"/api/foo"} />;
}
export function T(id: number) {
  return <a href={`/api/leases/${id}/invoices`}>Invoice</a>;
}
export function Home() {
  return <a href="/leases">Home</a>;
}
export function NotAnAnchor() {
  return <Link href="/api/nope">No</Link>;
}
'''

OBJECT_FILES = {
    "web/api.ts": OBJECT_API,
    "web/page.ts": PAGE,
    "web/Settings.vue": '''\
<template>
  <a href="/api/accounting/connect">Connect</a>
  <a href="/leases">Leases</a>
  <a href="https://example.com/api/x">Out</a>
</template>
<script setup lang="ts"></script>
''',
    "api/Controllers.cs": '''\
namespace Api;

public class InvoicesController
{
    [HttpPost("api/leases/{leaseId:int}/invoices")]
    public object Raise(int leaseId) => null;
}

public class AccountingController
{
    [HttpGet("api/accounting/connect")]
    public object Connect() => null;
}
''',
}


def test_exported_object_methods_are_symbols_and_call_routes():
    defs, facts, err = typescript.parse(OBJECT_API.encode(), "typescript", False)
    assert not err
    by = {d["qualname"]: d["display_kind"] for d in defs}
    assert by["api"] == "object"
    assert by["api.raiseInvoice"] == "method"
    assert by["api.ping"] == "method"
    assert by["local"] == "object"
    assert by["local.go"] == "method"
    assert by["wrapped"] == "object"
    assert by["wrapped.ready"] == "method"
    assert "hidden" not in by and "hidden.no" not in by
    assert "config" not in by and "api.plain" not in by and "api.nested" not in by and "api.nested.inner" not in by
    calls = set(_named(defs, facts["http_calls"]))
    assert ("api.raiseInvoice", "POST", "/api/leases/{param}/invoices") in calls
    assert ("api.ping", "GET", "/api/ping") in calls
    assert ("local.go", "POST", "/api/go") in calls
    assert ("wrapped.ready", "GET", "/api/ready") in calls
    assert (None, "GET", "/api/hidden") in calls
    assert not any(path == "/api/inner" and name and name.startswith("api.nested") for name, _method, path in calls)

    js = '''\
export const api = {
  ping: () => request("GET", "/api/ping"),
};
function request(method, path) { return fetch(path, { method }); }
'''
    defs, facts, err = typescript.parse(js.encode(), "javascript", False)
    assert not err
    assert {d["qualname"] for d in defs} >= {"api", "api.ping", "request"}
    assert ("api.ping", "GET", "/api/ping") in _named(defs, facts["http_calls"])

    defs, facts, err = typescript.parse(JSX_PAGE.encode(), "tsx", False)
    assert not err
    calls = set(_named(defs, facts["http_calls"]))
    assert ("Page", "GET", "/api/accounting/connect") in calls
    assert ("Other", "GET", "/api/foo") in calls
    assert ("T", "GET", "/api/leases/{param}/invoices") in calls
    assert not any(path in ("/leases", "/api/nope") for _name, _method, path in calls)

    defs, facts, err = typescript.parse(JSX_PAGE.encode(), "tsx", True)
    assert facts["http_calls"] == []


def test_object_method_calls_resolve_to_the_handler(make_repo, monkeypatch, capsys):
    root = make_repo(OBJECT_FILES, name="objects")
    monkeypatch.chdir(root)
    assert main(["init"]) == 0
    assert main(["scan"]) == 0
    capsys.readouterr()
    conn = sqlite3.connect(root / ".cbi" / "model.db")

    def qual(nid):
        return nid.split(":", 2)[-1]

    calls = {
        (qual(s), qual(d))
        for s, d in conn.execute("SELECT src, dst FROM edges WHERE kind = 'calls'")
    }
    assert ("web/page.ts#raiseInvoice", "web/api.ts#api.raiseInvoice") in calls
    http = {
        (qual(src), qual(dst), attrs["method"], attrs["path"])
        for src, dst, raw in conn.execute(
            "SELECT src, dst, attrs FROM edges WHERE kind = 'http_calls'")
        for attrs in [json.loads(raw)]
    }
    short = http
    assert ("web/api.ts#api.raiseInvoice", "api/Controllers.cs#Api.InvoicesController.Raise",
            "POST", "/api/leases/{leaseId}/invoices") in short
    assert ("web/Settings.vue#Settings", "api/Controllers.cs#Api.AccountingController.Connect",
            "GET", "/api/accounting/connect") in short
    assert not any(path == "/leases" for _s, _d, _m, path in short)

    assert main(["show", "web/page.ts#raiseInvoice"]) == 0
    shown = capsys.readouterr().out
    assert "method" in shown and "raiseInvoice" in shown
    assert main(["show", "web/api.ts#api.raiseInvoice"]) == 0
    shown = capsys.readouterr().out
    assert "calls endpoints" in shown
    assert "POST /api/leases/{leaseId}/invoices" in shown
    assert "Raise" in shown


def _named(defs, calls):
    named = []
    for caller, method, path in calls:
        name = None if caller is None else defs[caller]["qualname"]
        named.append((name, method, path))
    return named


def _symbols(concepts):
    found = []
    for concept in concepts:
        found.extend(concept.get("symbols") or [])
        found.extend(_symbols(concept.get("children") or []))
    return found
