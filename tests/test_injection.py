"""Type-only imports and constructor-injected calls in TypeScript and Python."""

import json
import sqlite3

import pytest

from cbi import concepts
from cbi.cli import main

INJECT = {"via": "injection"}


def scan(make_repo, monkeypatch, files, name):
    root = make_repo(files, name=name)
    monkeypatch.chdir(root)
    assert main(["init"]) == 0
    assert main(["scan"]) == 0
    return root, sqlite3.connect(root / ".cbi" / "model.db")


def run(capsys, *argv):
    capsys.readouterr()
    code = main(list(argv))
    out = capsys.readouterr()
    return code, out.out, out.err


def calls(conn):
    """(src qualname, dst qualname) -> (confidence, weight, attrs)."""
    found = {}
    for src, dst, conf, weight, attrs in conn.execute(
            "SELECT s.id, d.id, e.confidence, e.weight, e.attrs FROM edges e "
            "JOIN nodes s ON s.id = e.src JOIN nodes d ON d.id = e.dst WHERE e.kind = 'calls'"):
        found[(src.split("#", 1)[-1], dst.split("#", 1)[-1])] = (
            conf, weight, json.loads(attrs) if attrs else None)
    return found


def imports(conn):
    """(src path, dst path) -> attrs."""
    found = {}
    for src, dst, attrs in conn.execute(
            "SELECT s.id, d.id, e.attrs FROM edges e "
            "JOIN nodes s ON s.id = e.src JOIN nodes d ON d.id = e.dst WHERE e.kind = 'imports'"):
        found[(src.split(":")[-1], dst.split(":")[-1])] = json.loads(attrs) if attrs else None
    return found


def unresolved(conn):
    return sorted(conn.execute(
        "SELECT n.path, d.detail FROM diagnostics d JOIN nodes n ON n.id = d.node_id "
        "WHERE d.kind = 'unresolved_injection'").fetchall())


def assert_inject(found, src, dst, confidence, weight=1):
    assert (src, dst) in found, found
    got_conf, got_weight, attrs = found[(src, dst)]
    assert got_conf == pytest.approx(confidence)
    assert got_weight == weight and attrs == INJECT


# --- TypeScript -----------------------------------------------------------------


def test_ts_type_only_imports(make_repo, monkeypatch, capsys):
    root, conn = scan(make_repo, monkeypatch, {
        "types.ts": "export interface Only { n(): void }\nexport class Value { n(): void {} }\n",
        "type-user.ts": 'import type { Only } from "./types";\n',
        "inline-user.ts": 'import { type Only } from "./types";\n',
        "mixed-user.ts": 'import { Value, type Only } from "./types";\n',
        "value-user.ts": 'import { Value } from "./types";\n',
        "barrel.ts": 'export type { Only } from "./types";\n',
    }, "ts-types")
    got = imports(conn)
    assert got[("type-user.ts", "types.ts")] == {"type_only": True}
    assert got[("inline-user.ts", "types.ts")] == {"type_only": True}
    assert got[("barrel.ts", "types.ts")] == {"type_only": True}
    assert got[("mixed-user.ts", "types.ts")] is None
    assert got[("value-user.ts", "types.ts")] is None
    code, out, err = run(capsys, "show", "type-user.ts")
    assert code == 0, err
    assert "imports types from" in out
    code, out, _ = run(capsys, "show", "type-user.ts", "--json")
    shown = json.loads(out)
    assert next(e for e in shown["outgoing"] if e["kind"] == "imports")["attrs"] == {"type_only": True}
    conn.close()
    assert root.name == "ts-types"


def test_ts_structural_fields_and_plain_this_call(make_repo, monkeypatch):
    _, conn = scan(make_repo, monkeypatch, {
        "a.ts": "export class A { go(): void {} }\n",
        "b.ts": "export class B { go(): void {} }\n",
        "c.ts": """\
interface P { go(): void }
export class Prop {
  constructor(private readonly p: P) {}
  run() { this.own(); this.p.go(); }
  own() {}
}
export class Assigned {
  private p: P;
  constructor(p: P) { this.p = p; }
  run() { this.p?.go(); }
}
""",
    }, "ts-struct")
    found = calls(conn)
    assert_inject(found, "Prop.run", "A.go", 0.2)
    assert_inject(found, "Prop.run", "B.go", 0.2)
    assert_inject(found, "Assigned.run", "A.go", 0.2)
    assert_inject(found, "Assigned.run", "B.go", 0.2)
    conf, weight, attrs = found[("Prop.run", "Prop.own")]
    assert conf == pytest.approx(0.6) and weight == 1 and attrs is None
    assert unresolved(conn) == []
    conn.close()


def test_ts_known_type_remote_interface_and_constructor(make_repo, monkeypatch):
    _, conn = scan(make_repo, monkeypatch, {
        "store.ts": "export class Store { save(): void {} }\n",
        "saver.ts": "export class Saver { save(): void {} }\n",
        "extra.ts": "export class Extra { save(): void {} }\n",
        "known.ts": """\
import { Store } from "./store";
export class Known {
  constructor(private readonly store: Store | null) {}
  run() { this.store.save(); }
}
export class Generic {
  constructor(private readonly store: Store<string>) {}
  run() { this.store.save(); }
}
export class Wrapped {
  constructor(private readonly store: Promise<Store>) {}
  run() { this.store.save(); }
}
export class LocalStore { keep(): void {} }
export class LocalOther { keep(): void {} }
export class LocalUser {
  constructor(private readonly store: LocalStore) {}
  run() { this.store.keep(); }
}
""",
        "port.ts": "export interface Port { flush(): void }\n",
        "sink.ts": "export class Sink { flush(): void {} }\n",
        "remote.ts": """\
import type { Port } from "./port";
export class Remote {
  constructor(private readonly port: Port) {}
  run() { this.port.flush(); }
}
""",
        "built.ts": """\
import { Store } from "./store";
interface Port { save(): void }
export class Built {
  constructor(private readonly port: Port) {}
  run() { this.port.save(); }
}
export function boot() { return new Built(new Store()); }
export class Shadowed {
  constructor(private readonly port: Port) {}
  run() { this.port.save(); }
}
export function hidden() {
  const port = new Store();
  for (const port of items) { new Shadowed(port); }
}
export class ForOk {
  constructor(private readonly port: Port) {}
  run() { this.port.save(); }
}
export function counted() {
  const port = new Store();
  for (let i = 0; i < 1; i++) { new ForOk(port); }
}
export class Caught {
  constructor(private readonly port: Port) {}
  run() { this.port.save(); }
}
export function viaCatch() {
  const port = new Store();
  try { port; } catch (port) { new Caught(port); }
}
export class Union {
  constructor(private readonly port: Store | Saver) {}
  run() { this.port.save(); }
}
""",
    }, "ts-known")
    found = calls(conn)
    assert_inject(found, "Known.run", "Store.save", 0.6)
    assert_inject(found, "Generic.run", "Store.save", 0.6)
    assert ("Wrapped.run", "Store.save") not in found
    assert_inject(found, "LocalUser.run", "LocalStore.keep", 0.6)
    assert ("LocalUser.run", "LocalOther.keep") not in found
    assert_inject(found, "Remote.run", "Port.flush", 0.6)
    assert ("Remote.run", "Sink.flush") not in found
    assert imports(conn)[("remote.ts", "port.ts")] == {"type_only": True}
    # Store, Saver and Extra all provide save. Construction of Built picks Store.
    assert_inject(found, "Built.run", "Store.save", 0.7)
    assert_inject(found, "Built.run", "Saver.save", 0.4 / 3)
    assert_inject(found, "Built.run", "Extra.save", 0.4 / 3)
    # The loop and catch variables hide the outer `new Store()`, so they add no construction.
    assert_inject(found, "Shadowed.run", "Store.save", 0.4 / 3)
    assert_inject(found, "Caught.run", "Store.save", 0.4 / 3)
    # `for (let i ...)` does not hide port.
    assert_inject(found, "ForOk.run", "Store.save", 0.7)
    assert ("Union.run", "Store.save") not in found
    assert [path for path, _ in unresolved(conn)] == []
    conn.close()


def test_ts_unresolved_injection(make_repo, monkeypatch):
    _, conn = scan(make_repo, monkeypatch, {
        "gap.ts": """\
interface P { missing(): void }
export class Gap {
  constructor(private readonly p: P) {}
  run() { this.p.missing(); }
}
""",
    }, "ts-gap")
    assert calls(conn) == {}
    assert unresolved(conn) == [("gap.ts", "1 injected calls with no candidate")]
    conn.close()


def test_ts_production_skips_test_doubles(make_repo, monkeypatch):
    _, conn = scan(make_repo, monkeypatch, {
        "log.ts": """\
export class Journal {
  append(): void {}
  save(): void {}
}
""",
        "admin.ts": """\
interface NoteWriter { append(): void }
export class Clerk {
  constructor(private readonly audit: NoteWriter) {}
  createRecord() { this.audit.append(); }
}
interface Store { save(): void }
export class Loader {
  constructor(private readonly store: Store) {}
  run() { this.store.save(); }
}
interface Missing { gone(): void }
export class Gap {
  constructor(private readonly dep: Missing) {}
  run() { this.dep.gone(); }
}
""",
        "admin.test.ts": """\
import { Clerk, Loader, Gap } from "./admin";
import { Journal } from "./log";
class MemoryJournal { append(): void {} }
class FakeStore { save(): void {} }
class FakeMissing { gone(): void {} }
export function setup() {
  new Clerk(new MemoryJournal());
  new Clerk(new Journal());
  new Loader(new FakeStore());
  new Gap(new FakeMissing());
}
""",
    }, "ts-doubles")
    found = calls(conn)
    assert_inject(found, "Clerk.createRecord", "Journal.append", 0.7)
    assert ("Clerk.createRecord", "MemoryJournal.append") not in found
    assert_inject(found, "Loader.run", "Journal.save", 0.4)
    assert ("Loader.run", "FakeStore.save") not in found
    assert ("Gap.run", "FakeMissing.gone") not in found
    assert unresolved(conn) == [("admin.ts", "1 injected calls with no candidate")]
    conn.close()


# --- Python ---------------------------------------------------------------------


def test_py_type_checking_imports(make_repo, monkeypatch, capsys):
    _, conn = scan(make_repo, monkeypatch, {
        "store.py": "class Store:\n    def save(self) -> None:\n        return None\n",
        "user.py": """\
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from store import Store

class User:
    def __init__(self, store: Store | None) -> None:
        self.store = store
    def run(self) -> None:
        self.store.save()

class Annotated:
    def __init__(self, store) -> None:
        self.store: Store = store
    def run(self) -> None:
        self.store.save()

class Quoted:
    def __init__(self, store: "Store") -> None:
        self.store = store
    def run(self) -> None:
        self.store.save()
""",
        "paren.py": """\
import typing
if (typing.TYPE_CHECKING):
    from store import Store as S
""",
        "elif_user.py": """\
from typing import TYPE_CHECKING
if False:
    pass
elif TYPE_CHECKING:
    from store import Store
""",
    }, "py-types")
    got = imports(conn)
    assert got[("user.py", "store.py")] == {"type_only": True}
    assert got[("paren.py", "store.py")] == {"type_only": True}
    assert got[("elif_user.py", "store.py")] is None
    found = calls(conn)
    assert_inject(found, "User.run", "Store.save", 0.6)
    assert_inject(found, "Annotated.run", "Store.save", 0.6)
    assert ("Quoted.run", "Store.save") not in found
    code, out, err = run(capsys, "show", "user.py")
    assert code == 0 and "imports types from" in out, err
    conn.close()


def test_py_protocol_structural_and_constructor(make_repo, monkeypatch):
    _, conn = scan(make_repo, monkeypatch, {
        "box.py": """\
from typing import Protocol

class Port(Protocol):
    def save(self) -> None: ...

class Store:
    def save(self) -> None:
        return None

class Other:
    def save(self) -> None:
        return None

class Box:
    def __init__(self, port: Port) -> None:
        self.port = port
    def run(self) -> None:
        self.port.save()

class Keyword:
    def __init__(self, port: Port) -> None:
        self.port = port
    def run(self) -> None:
        self.port.save()

def boot() -> Keyword:
    return Keyword(port=Store())

class Positional:
    def __init__(self, port: Port) -> None:
        self.port = port
    def run(self) -> None:
        self.port.save()

def lined():
    port = Store()
    return Positional(port)

class Explicit:
    def __init__(self, port: Port) -> None:
        self.port = port
    def run(self) -> None:
        self.port.save()

def misleading():
    return Explicit(Store(), port=items)

class Shadowed:
    def __init__(self, port: Port) -> None:
        self.port = port
    def run(self) -> None:
        self.port.save()

def hidden():
    port = Store()
    for port in items:
        Shadowed(port)

class Lam:
    def __init__(self, port: Port) -> None:
        self.port = port
    def run(self) -> None:
        self.port.save()

def via_lambda():
    port = Store()
    return (lambda port: Lam(port))(port)

class Comp:
    def __init__(self, port: Port) -> None:
        self.port = port
    def run(self) -> None:
        self.port.save()

def via_comp():
    port = Store()
    return [Comp(port) for port in items]

class Late:
    def set(self, port: Port) -> None:
        self.port = port
    def run(self) -> None:
        self.port.save()
""",
    }, "py-port")
    found = calls(conn)
    assert_inject(found, "Box.run", "Store.save", 0.2)
    assert_inject(found, "Box.run", "Other.save", 0.2)
    assert ("Box.run", "Port.save") not in found
    assert_inject(found, "Keyword.run", "Store.save", 0.7)
    assert_inject(found, "Keyword.run", "Other.save", 0.2)
    assert_inject(found, "Positional.run", "Store.save", 0.7)
    assert_inject(found, "Explicit.run", "Store.save", 0.2)
    assert_inject(found, "Shadowed.run", "Store.save", 0.2)
    assert_inject(found, "Lam.run", "Store.save", 0.2)
    assert_inject(found, "Comp.run", "Store.save", 0.2)
    assert ("Late.run", "Store.save") not in found
    assert unresolved(conn) == []
    conn.close()


def test_py_unresolved_and_unannotated(make_repo, monkeypatch):
    _, conn = scan(make_repo, monkeypatch, {
        "gap.py": """\
import typing

class Port(typing.Protocol):
    def missing(self) -> None: ...

class Gap:
    def __init__(self, port: Port) -> None:
        self.port = port
    def run(self) -> None:
        self.port.missing()

class Bare:
    def __init__(self, store) -> None:
        self.store = store
    def run(self) -> None:
        self.store.save()
""",
    }, "py-gap")
    assert calls(conn) == {}
    assert unresolved(conn) == [("gap.py", "1 injected calls with no candidate")]
    conn.close()


def test_py_production_skips_test_doubles(make_repo, monkeypatch):
    _, conn = scan(make_repo, monkeypatch, {
        "log.py": """\
class Journal:
    def append(self) -> None:
        return None
    def save(self) -> None:
        return None
""",
        "admin.py": """\
from typing import Protocol

class NoteWriter(Protocol):
    def append(self) -> None: ...

class Clerk:
    def __init__(self, audit: NoteWriter) -> None:
        self.audit = audit
    def create_record(self) -> None:
        self.audit.append()

class Store(Protocol):
    def save(self) -> None: ...

class Loader:
    def __init__(self, store: Store) -> None:
        self.store = store
    def run(self) -> None:
        self.store.save()

class Missing(Protocol):
    def gone(self) -> None: ...

class Gap:
    def __init__(self, dep: Missing) -> None:
        self.dep = dep
    def run(self) -> None:
        self.dep.gone()
""",
        "test_admin.py": """\
from admin import Clerk, Loader, Gap
from log import Journal

class MemoryJournal:
    def append(self) -> None:
        return None

class FakeStore:
    def save(self) -> None:
        return None

class FakeMissing:
    def gone(self) -> None:
        return None

def setup():
    Clerk(MemoryJournal())
    Clerk(Journal())
    Loader(FakeStore())
    Gap(FakeMissing())
""",
    }, "py-doubles")
    found = calls(conn)
    assert_inject(found, "Clerk.create_record", "Journal.append", 0.7)
    assert ("Clerk.create_record", "MemoryJournal.append") not in found
    assert_inject(found, "Loader.run", "Journal.save", 0.4)
    assert ("Loader.run", "FakeStore.save") not in found
    assert ("Gap.run", "FakeMissing.gone") not in found
    assert unresolved(conn) == [("admin.py", "1 injected calls with no candidate")]
    conn.close()


def test_define_concepts_counts_injection_only_at_0_6(make_repo, monkeypatch):
    root, conn = scan(make_repo, monkeypatch, {
        "store.ts": "export class Store { save(): void {} }\n",
        "saver.ts": "export class Saver { save(): void {} }\n",
        "weak.ts": """\
interface Port { save(): void }
export class Weak {
  constructor(private readonly port: Port) {}
  run() { this.port.save(); }
}
""",
        "known.ts": """\
import { Store } from "./store";
export class Known {
  constructor(private readonly store: Store) {}
  run() { this.store.save(); }
}
""",
        "built.ts": """\
import { Store } from "./store";
interface Port { save(): void }
export class Built {
  constructor(private readonly port: Port) {}
  run() { this.port.save(); }
}
export function boot(store: Store) { return new Built(store); }
""",
        "types.ts": "export interface Only { n(): void }\n",
        "type-user.ts": 'import type { Only } from "./types";\n',
    }, "coverage")
    found_calls = calls(conn)
    assert_inject(found_calls, "Known.run", "Store.save", 0.6)
    assert_inject(found_calls, "Built.run", "Store.save", 0.7)
    assert_inject(found_calls, "Weak.run", "Store.save", 0.2)
    assert_inject(found_calls, "Weak.run", "Saver.save", 0.2)
    assert_inject(found_calls, "Built.run", "Saver.save", 0.2)
    pairs = {(p["from"], p["to"], p["kind"]) for p in concepts._pairs(conn, concepts._code_files(conn))}
    assert ("known.ts", "store.ts", "calls") in pairs
    assert ("known.ts", "store.ts", "imports") in pairs
    assert ("built.ts", "store.ts", "calls") in pairs
    assert ("built.ts", "store.ts", "imports") in pairs
    assert ("type-user.ts", "types.ts", "imports") in pairs
    assert ("weak.ts", "store.ts", "calls") not in pairs
    assert ("weak.ts", "saver.ts", "calls") not in pairs
    assert ("built.ts", "saver.ts", "calls") not in pairs
    answer = {
        "summary": "Callers and stores.",
        "concepts": [
            {"id": "data", "name": "Data", "summary": "The stores.", "role": "data",
             "files": ["store.ts", "saver.ts", "types.ts"]},
            {"id": "app", "name": "App", "summary": "The callers.", "role": "app",
             "files": ["weak.ts", "known.ts", "built.ts", "type-user.ts"]},
        ],
        "externals": [],
        "relationships": [],
    }
    found, warnings = concepts.problems(conn, answer)
    assert warnings == []
    assert found == [
        "$.relationships: no relationship covers calls app -> data: built.ts -> store.ts, known.ts -> store.ts",
        "$.relationships: no relationship covers imports app -> data: "
        "built.ts -> store.ts, known.ts -> store.ts, type-user.ts -> types.ts",
    ]
    answer["relationships"] = [{"from": "app", "to": "data", "label": "uses", "basis": "imports"}]
    assert concepts.problems(conn, answer) == ([], [])
    conn.close()
    assert (root / ".cbi" / "model.db").exists()
