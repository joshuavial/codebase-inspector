"""Control flow and lexical blocks cannot turn uncertain URLs into concrete calls."""

import json
import sqlite3

import pytest

from cbi.cli import main


ROUTES = '''from fastapi import FastAPI
app = FastAPI()
@app.get("/admin/books")
def books(): pass
@app.get("/admin/films")
def films(): pass
@app.get("/v1/items")
def first(): pass
@app.get("/v2/items")
def second(): pass
'''


def _scan(make_repo, monkeypatch, tmp_path, path, source):
    root = make_repo({"api.py": ROUTES, path: source})
    monkeypatch.chdir(root)
    monkeypatch.setenv("CBI_CACHE_DIR", str(tmp_path / "cache"))
    assert main(["init"]) == 0 and main(["scan"]) == 0
    with sqlite3.connect(root / ".cbi/model.db") as conn:
        facts = json.loads(conn.execute("SELECT f.data FROM facts f JOIN nodes n ON n.id=f.file_id WHERE n.path=?", (path,)).fetchone()[0])
        paths = {(caller.rsplit("#", 1)[-1] if caller else "module", route)
                 for caller, _, route in facts["http_calls"]}
        unresolved = {(caller.rsplit("#", 1)[-1] if caller else "module", line)
                      for caller, _, line in facts["http_unresolved_calls"]}
        links = {(src, dst) for src, dst in conn.execute("SELECT s.name,d.name FROM edges e "
                 "JOIN nodes s ON s.id=e.src JOIN nodes d ON d.id=e.dst WHERE e.kind='http_calls'")}
    return paths, unresolved, links


def test_python_conditional_arms_use_incoming_values(make_repo, monkeypatch, tmp_path):
    paths, unresolved, links = _scan(make_repo, monkeypatch, tmp_path, "client.py", '''import requests

def load(flag):
    resource = "books"
    if flag:
        resource = "films"
    else:
        requests.get(f"/admin/{resource}")
    requests.get(f"/admin/{resource}")
''')
    assert paths == {("load", "/admin/books")}
    assert ("load", 9) in unresolved
    assert links == {("load", "books")}


def test_conditional_module_configuration_is_not_a_literal_prefix(make_repo, monkeypatch, tmp_path):
    paths, unresolved, links = _scan(make_repo, monkeypatch, tmp_path, "client.py", '''import requests
API_BASE = "/v1"
if configured():
    API_BASE = "/v2"

def load():
    return requests.get(f"{API_BASE}/items")
''')
    assert not paths and not links
    assert ("load", 7) in unresolved


def test_typescript_branches_and_lexical_blocks_keep_outer_values(make_repo, monkeypatch, tmp_path):
    paths, unresolved, links = _scan(make_repo, monkeypatch, tmp_path, "client.ts", '''const API_BASE = "/v1";
if (configured()) { const API_BASE = "/v2"; }
export function configuredItems() { return fetch(`${API_BASE}/items`); }
export function conditional(flag: boolean) {
  let resource = "books";
  if (flag) { resource = "films"; }
  else { fetch(`/admin/${resource}`); }
  fetch(`/admin/${resource}`);
}
export function blocks() {
  const resource = "books";
  { const resource = "films"; fetch(`/admin/${resource}`); }
  { let resource = "films"; resource = "books"; }
  return fetch(`/admin/${resource}`);
}
''')
    assert paths == {("configuredItems", "/v1/items"), ("conditional", "/admin/books"),
                     ("blocks", "/admin/books"), ("blocks", "/admin/films")}
    assert ("conditional", 8) in unresolved
    assert ("configuredItems", "second") not in links
    assert ("conditional", "films") not in links


def test_loop_and_try_arms_do_not_reuse_sibling_assignments(make_repo, monkeypatch, tmp_path):
    paths, unresolved, links = _scan(make_repo, monkeypatch, tmp_path, "client.py", '''import requests

def loop(values):
    resource = "books"
    for value in values:
        requests.get(f"/admin/{resource}")
        resource = "films"
    requests.get(f"/admin/{resource}")

def attempt():
    resource = "books"
    try:
        resource = "films"
        operation()
    except Exception:
        requests.get(f"/admin/{resource}")
    finally:
        requests.get(f"/admin/{resource}")
    requests.get(f"/admin/{resource}")
''')
    assert not paths and not links
    assert {line for _, line in unresolved} == {6, 8, 16, 18, 19}


def test_typescript_loop_try_and_module_writes_remain_uncertain(make_repo, monkeypatch, tmp_path):
    paths, unresolved, links = _scan(make_repo, monkeypatch, tmp_path, "client.ts", '''let API_BASE = "/v1";
if (configured()) { API_BASE = "/v2"; }
export function configuredItems() { return fetch(`${API_BASE}/items`); }
export function loop(values: string[]) {
  let resource = "books";
  for (const value of values) { fetch(`/admin/${resource}`); resource = "films"; }
  fetch(`/admin/${resource}`);
}
export function attempt() {
  let resource = "books";
  try { resource = "films"; operation(); }
  catch (error) { fetch(`/admin/${resource}`); }
  finally { fetch(`/admin/${resource}`); }
  fetch(`/admin/${resource}`);
}
''')
    assert not paths and not links
    assert {name for name, _ in unresolved} == {"configuredItems", "loop", "attempt"}


def test_typescript_loop_and_catch_bindings_are_scoped(make_repo, monkeypatch, tmp_path):
    paths, unresolved, links = _scan(make_repo, monkeypatch, tmp_path, "client.ts", '''const resource = "books";
export function scopedLoop() {
  for (let resource = 0; resource < 1; resource++) {}
  return fetch(`/admin/${resource}`);
}
export function scopedCatch() {
  try { operation(); }
  catch (resource) { fetch(`/admin/${resource}`); }
  return fetch(`/admin/${resource}`);
}
''')
    assert paths == {("scopedLoop", "/admin/books"), ("scopedCatch", "/admin/books")}
    assert ("scopedCatch", 8) in unresolved
    assert links == {("scopedLoop", "books"), ("scopedCatch", "books")}


def test_python_except_alias_and_condition_writes_are_unknown(make_repo, monkeypatch, tmp_path):
    paths, unresolved, links = _scan(make_repo, monkeypatch, tmp_path, "client.py", '''import requests

def condition():
    resource = "books"
    if (resource := configured()):
        requests.get(f"/admin/{resource}")
    else:
        requests.get(f"/admin/{resource}")

def handler():
    resource = "books"
    try:
        operation()
    except Exception as resource:
        requests.get(f"/admin/{resource}")
    requests.get(f"/admin/{resource}")
''')
    assert not paths and not links
    assert {line for _, line in unresolved} == {6, 8, 15, 16}


def test_typescript_hoisted_vars_and_nested_blocks_do_not_borrow_globals(make_repo, monkeypatch, tmp_path):
    paths, unresolved, links = _scan(make_repo, monkeypatch, tmp_path, "client.ts", '''const API_BASE = "/v1";
export function hoisted() {
  fetch(`${API_BASE}/items`);
  var API_BASE = "/v2";
  return fetch(`${API_BASE}/items`);
}
{
  const API_BASE = "/v2";
  function nested() { return fetch(`${API_BASE}/items`); }
}
export function globalBase() { return fetch(`${API_BASE}/items`); }
export function hoistedLoop(values: string[]) {
  fetch(`${API_BASE}/items`);
  for (var API_BASE of values) {}
}
''')
    assert paths == {("hoisted", "/v2/items"), ("globalBase", "/v1/items")}
    assert ("hoisted", 3) in unresolved
    assert ("nested", "/v1/items") not in paths
    assert ("nested", "first") not in links


def test_python_nested_local_binding_does_not_borrow_a_global(make_repo, monkeypatch, tmp_path):
    paths, unresolved, links = _scan(make_repo, monkeypatch, tmp_path, "client.py", '''import requests
API_BASE = "/v1"

def load():
    API_BASE = configured()
    def nested():
        return requests.get(f"{API_BASE}/items")
    return nested()
''')
    assert not paths and not links
    assert unresolved


def test_request_wrapper_keeps_every_bounded_branch_prefix(make_repo, monkeypatch, tmp_path):
    paths, unresolved, links = _scan(make_repo, monkeypatch, tmp_path, "client.ts", '''const FIRST = "/v1";
const SECOND = "/v2";
function request(path) {
  if (configured()) { return fetch(`${FIRST}${path}`); }
  else { return fetch(`${SECOND}${path}`); }
}
export function load() { return request("/items"); }
''')
    assert paths == {("load", "/v1/items"), ("load", "/v2/items")}
    assert links == {("load", "first"), ("load", "second")}
    assert not unresolved


@pytest.mark.parametrize(("path", "source"), [
    ("client.py", '''import requests
def load():
    resource = "books"
    resource, extra = configured()
    return requests.get(f"/admin/{resource}")
'''),
    ("client.ts", '''export function load() {
  let resource = "books";
  ({resource} = configured());
  return fetch(`/admin/${resource}`);
}
'''),
])
def test_assignment_patterns_do_not_keep_previous_literals(make_repo, monkeypatch, tmp_path, path, source):
    paths, unresolved, links = _scan(make_repo, monkeypatch, tmp_path, path, source)
    assert not paths and not links
    assert unresolved


@pytest.mark.parametrize("declaration", ["def API_BASE(): pass", "class API_BASE: pass"], ids=["function", "class"])
def test_python_local_declarations_shadow_module_literals(make_repo, monkeypatch, tmp_path, declaration):
    source = f'''import requests
API_BASE = "/v1"
def load():
    requests.get(f"{{API_BASE}}/items")
    {declaration}
    requests.get(f"{{API_BASE}}/items")
def replaced():
    API_BASE = "/v2"
    {declaration}
    requests.get(f"{{API_BASE}}/items")
def genuine():
    return requests.get(f"{{API_BASE}}/items")
'''
    paths, unresolved, links = _scan(make_repo, monkeypatch, tmp_path, "client.py", source)
    assert paths == {("genuine", "/v1/items")}
    assert links == {("genuine", "first")}
    assert {name for name, _ in unresolved} == {"load", "replaced"}


@pytest.mark.parametrize("declaration", ["function API_BASE() {}", "class API_BASE {}"], ids=["function", "class"])
def test_typescript_local_declarations_shadow_module_literals(make_repo, monkeypatch, tmp_path, declaration):
    source = '''const API_BASE = "/v1";
export function load() {
  fetch(`${API_BASE}/items`);
  DECLARATION
  return fetch(`${API_BASE}/items`);
}
export function genuine() { return fetch(`${API_BASE}/items`); }
'''.replace("DECLARATION", declaration)
    paths, unresolved, links = _scan(make_repo, monkeypatch, tmp_path, "client.ts", source)
    assert paths == {("genuine", "/v1/items")}
    assert links == {("genuine", "first")}
    assert {name for name, _ in unresolved} == {"load"}


@pytest.mark.parametrize("expression", [
    'function API_BASE() { return fetch(`${API_BASE}/items`); }',
    'class API_BASE { load() { return fetch(`${API_BASE}/items`); } }',
], ids=["function", "class"])
def test_typescript_named_expression_does_not_borrow_a_global(make_repo, monkeypatch, tmp_path, expression):
    source = '''const API_BASE = "/v1";
const holder = EXPRESSION;
export function genuine() { return fetch(`${API_BASE}/items`); }
'''.replace("EXPRESSION", expression)
    paths, unresolved, links = _scan(make_repo, monkeypatch, tmp_path, "client.ts", source)
    assert paths == {("genuine", "/v1/items")}
    assert links == {("genuine", "first")}
    assert unresolved
