"""Bare function values create lower-confidence call edges in each resolved language."""

import json
import sqlite3

import pytest

from cbi.cli import main


FILES = {
    "callbacks.py": '''\
def dispatch_job(payload):
    return payload


def accept_client(reader, writer):
    return reader, writer


class NotACallback:
    pass


ROUTES = {"job": dispatch_job}
TYPES = [NotACallback]


def boot(server):
    choices = [dispatch_job]
    pair = (dispatch_job,)
    return server(accept_client), choices, pair
''',
    "test_callbacks.py": '''\
from callbacks import accept_client, dispatch_job


def test_callbacks_are_callable():
    assert dispatch_job("work") == "work"
    assert accept_client("reader", "writer") == ("reader", "writer")
''',
    "callbacks.ts": '''\
export function dispatchTask(value: string) { return value; }
export function receiveClient(value: string) { return value; }
export class NotACallback {}
export const routes = { task: dispatchTask };
export const types = [NotACallback];
export function boot(server: (cb: Function) => void) {
  const choices = [dispatchTask];
  server(receiveClient);
  return choices;
}
''',
    "Callbacks.cs": '''\
using System;
using System.Collections.Generic;

class Callbacks {
    class NotACallback {}
    void DispatchTask() {}
    void ReceiveClient() {}
    void Boot(Action<Action> server) {
        var routes = new Dictionary<string, Action> { ["task"] = DispatchTask };
        var choices = new Action[] { DispatchTask };
        var types = new[] { NotACallback };
        server(ReceiveClient);
    }
}
''',
}


@pytest.fixture
def repo(make_repo, monkeypatch, capsys):
    root = make_repo(FILES, name="function-values")
    monkeypatch.chdir(root)
    assert main(["init"]) == 0
    assert main(["scan"]) == 0
    capsys.readouterr()
    return root


def _references(root):
    conn = sqlite3.connect(root / ".cbi" / "model.db")
    return conn.execute(
        "SELECT s.path, s.name, d.name, e.confidence, e.attrs "
        "FROM edges e JOIN nodes s ON s.id = e.src JOIN nodes d ON d.id = e.dst "
        "WHERE e.kind = 'calls' AND json_extract(e.attrs, '$.via') = 'reference' "
        "ORDER BY s.path, s.name, d.name"
    ).fetchall()


def test_function_values_resolve_in_each_language(repo):
    rows = _references(repo)
    assert {(path, target) for path, _source, target, _confidence, _attrs in rows} == {
        ("callbacks.py", "dispatch_job"),
        ("callbacks.py", "accept_client"),
        ("callbacks.ts", "dispatchTask"),
        ("callbacks.ts", "receiveClient"),
        ("Callbacks.cs", "DispatchTask"),
        ("Callbacks.cs", "ReceiveClient"),
    }
    assert all(confidence <= 0.7 for _path, _source, _target, confidence, _attrs in rows)
    assert all(confidence > 0 for _path, _source, _target, confidence, _attrs in rows)
    assert all(target != "NotACallback" for _path, _source, target, _confidence, _attrs in rows)


def test_python_references_remove_orphans_and_show_the_caller(repo, capsys):
    assert main(["orphans", "--json"]) == 0
    orphaned = json.loads(capsys.readouterr().out)
    names = {row["name"] for row in orphaned["test_only_symbols"]}
    assert not {"dispatch_job", "accept_client"} & names

    assert main(["show", "callbacks.py#accept_client", "--json"]) == 0
    shown = json.loads(capsys.readouterr().out)
    caller = next(edge for edge in shown["incoming"] if edge["name"] == "boot")
    assert caller["kind"] == "calls"
    assert caller["confidence"] == pytest.approx(0.7)
    assert caller["attrs"] == {"via": "reference"}
