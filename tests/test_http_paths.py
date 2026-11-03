"""Bounded client paths retain configured prefixes and finite alternatives."""

import json
import sqlite3

from cbi.cli import main
from cbi.parse import typescript


def test_finite_client_paths_bind_concrete_routes(make_repo, monkeypatch):
    root = make_repo({
        "api.py": '''from fastapi import FastAPI
app = FastAPI()
@app.get("/v2/admin/books/{item_id}/revisions")
def books(): pass
@app.get("/v2/admin/films/{item_id}/revisions")
def films(): pass
@app.get("/v1/admin/books/{item_id}/revisions")
def legacy(): pass
''',
        "client.ts": '''const API_BASE = "https://api.example.test/v2";
type Resource = "books" | "films";
export function revisions(resource: Resource, id: string) {
  const action = "revisions";
  return fetch(`${API_BASE}/admin/${resource}/${id}/${action}`);
}
export function dynamic(resource: string, id: string) {
  return fetch(`${API_BASE}/admin/${resource}/${id}/revisions`);
}
''',
    })
    monkeypatch.chdir(root)
    assert main(["init"]) == 0
    assert main(["scan"]) == 0
    with sqlite3.connect(root / ".cbi/model.db") as conn:
        links = list(conn.execute("SELECT s.name, d.name, e.attrs FROM edges e "
                                  "JOIN nodes s ON s.id=e.src JOIN nodes d ON d.id=e.dst "
                                  "WHERE e.kind='http_calls'"))
        assert {(src, dst) for src, dst, _ in links} == {("revisions", "books"), ("revisions", "films")}
        assert {json.loads(attrs)["path"] for _, _, attrs in links} == {
            "/v2/admin/books/{item_id}/revisions", "/v2/admin/films/{item_id}/revisions"}
        assert conn.execute("SELECT detail FROM diagnostics WHERE kind='unmatched_http_call' "
                            "AND node_id LIKE '%#dynamic'").fetchone()


def test_literal_composition_and_finite_inline_alternatives():
    source = b'''const BASE = "/v3";
export function load(id: string, archive: boolean) {
  const resource = archive ? "archives" : "items";
  const path = BASE + `/admin/${resource}/${id}`;
  return fetch(path);
}
'''
    _, facts, error = typescript.parse(source, "typescript", False)
    assert not error
    assert {row[2] for row in facts["http_calls"]} == {
        "/v3/admin/archives/{param}", "/v3/admin/items/{param}"}


def test_configured_prefix_propagates_through_request_wrapper():
    source = b'''const API_BASE = "https://api.example.test/v4";
function request(method, path) {
  return fetch(`${API_BASE}${path}`, {method});
}
export function revisions(resource: "books" | "films", id: string) {
  return request("GET", `/admin/${resource}/${id}/revisions`);
}
'''
    _, facts, error = typescript.parse(source, "typescript", False)
    assert not error
    assert {row[2] for row in facts["http_calls"]} == {
        "/v4/admin/books/{param}/revisions", "/v4/admin/films/{param}/revisions"}


def test_unbounded_and_shadowed_resources_remain_unresolved():
    source = b'''const resource = "books";
export function shadowed(resource: string, id: string) {
  return fetch(`/admin/${resource}/${id}/revisions`);
}
export function widened(resource: "books" | string, id: string) {
  return fetch(`/admin/${resource}/${id}/revisions`);
}
'''
    _, facts, error = typescript.parse(source, "typescript", False)
    assert not error
    assert {row[2] for row in facts["http_calls"]} == {"/admin/{param}/{param}/revisions"}


def test_reassigned_resource_is_not_bound_to_its_previous_literal():
    source = b'''export function load(value: string, id: string) {
  let resource = "books";
  resource = value;
  return fetch(`/admin/${resource}/${id}`);
}
'''
    _, facts, error = typescript.parse(source, "typescript", False)
    assert not error
    assert {row[2] for row in facts["http_calls"]} == {"/admin/{param}/{param}"}


def test_purely_dynamic_http_calls_remain_visible_without_wrapper_duplication(make_repo, monkeypatch):
    root = make_repo({
        "client.ts": '''const url = configuredUrl();
fetch(url);
function request(path) { return fetch(path); }
export function send(url) { return request(url); }
''',
        "client.vue": "<script setup>\nconst target = configuredUrl();\nfetch(target);\n</script>\n",
        "client.py": '''import requests

def load(url):
    return requests.get(url)
''',
    })
    monkeypatch.chdir(root)
    assert main(["init"]) == 0 and main(["scan"]) == 0
    with sqlite3.connect(root / ".cbi/model.db") as conn:
        rows = list(conn.execute("SELECT node_id,detail FROM diagnostics WHERE kind='unmatched_http_call'"))
        assert len(rows) == 4
        assert {node.split("#")[-1] for node, _ in rows if "#" in node} == {"send", "load"}
        assert all("resolution=dynamic_client" in detail and "dynamic URL" in detail for _, detail in rows)
        assert all("client.ts:2" in detail or "client.ts:4" in detail or "client.py:4" in detail or "client.vue:3" in detail for _, detail in rows)
        assert not conn.execute("SELECT 1 FROM edges WHERE kind='http_calls'").fetchone()


def test_literal_absolute_api_base_keeps_only_its_path_prefix():
    source = b'''const BASE = "https://api.example.test/v2";
export function load(id: string) {
  return fetch(`${BASE}/items/${id}`);
}
'''
    _, facts, error = typescript.parse(source, "typescript", False)
    assert not error
    assert {row[2] for row in facts["http_calls"]} == {"/v2/items/{param}"}
