"""Join the agent's concept answer with a cbi model and write the mockup's data file.

usage: uv run python mockup/derive.py <model.db>
Reads mockup/orchestra-concepts.json, writes mockup/orchestra-concepts.js.
Fails if a TS/TSX file is owned by no leaf or by two, or a relationship names an unknown concept.
Prints leaf-level import pairs that have no labelled relationship.
"""

import json
import sqlite3
import sys
from pathlib import Path

HERE = Path(__file__).parent
SHOWN = ("class", "function", "component")


def leaves(concepts):
    for c in concepts:
        if c.get("children"):
            yield from leaves(c["children"])
        else:
            yield c


def all_ids(concepts):
    for c in concepts:
        yield c["id"]
        yield from all_ids(c.get("children", []))


def main(db_path):
    answer = json.loads((HERE / "orchestra-concepts.json").read_text())
    db = sqlite3.connect(db_path)
    q = lambda sql, *a: db.execute(sql, a).fetchall()

    # Coverage: every TS/TSX file owned by exactly one leaf.
    ts = {p for (p,) in q("select path from nodes where kind='file' and (path like '%.ts' or path like '%.tsx')")}
    owner = {}
    for leaf in leaves(answer["concepts"]):
        for f in leaf["files"]:
            assert f not in owner, f"{f} owned by {owner[f]} and {leaf['id']}"
            assert f in ts, f"{f} ({leaf['id']}) is not a TS file in the model"
            owner[f] = leaf["id"]
    missing = sorted(ts - owner.keys())
    assert not missing, f"unowned files: {missing}"

    known = set(all_ids(answer["concepts"])) | {x["id"] for x in answer["externals"]}
    for r in answer["relationships"]:
        assert r["from"] in known and r["to"] in known, f"unknown concept in {r}"

    tests_files = {p for (p,) in q("select path from nodes where display_kind='test file'")}

    # Leaf-level import pairs from code (not tests), to check labels are complete.
    labelled = {(r["from"], r["to"]) for r in answer["relationships"]}
    pairs = set()
    for s, d in q("""select s.path, d.path from edges e join nodes s on s.id=e.src join nodes d on d.id=e.dst
                     where e.kind='imports'"""):
        if s in tests_files or s not in owner or d not in owner or owner[s] == owner[d]:
            continue
        pairs.add((owner[s], owner[d]))
    for p in sorted(pairs - labelled):
        print("unlabelled import pair:", *p)

    # Symbols: top-level class/function/component per file; methods roll up to their class.
    top = {}  # any symbol id -> its top-level symbol id
    syms = {}
    for sid, parent, kind, name, path, sig, line in q(
        "select id, parent_id, display_kind, name, path, signature, start_line from nodes where kind='symbol'"
    ):
        if path not in owner or path in tests_files:
            continue
        top[sid] = sid if parent.endswith(path) else parent.split("#")[0] + "#" + sid.split("#")[1].split(".")[0]
        if kind in SHOWN and parent.endswith(path):
            syms[sid] = {"id": sid, "name": name, "kind": kind, "sig": sig, "file": path, "line": line,
                         "concept": owner[path], "tests": []}
    for src, dst, case in q("""select e.src, e.dst, s.name from edges e join nodes s on s.id=e.src
                                where e.kind='tests' and e.confidence >= 0.6"""):
        t = top.get(dst)
        if t in syms and case not in syms[t]["tests"]:
            syms[t]["tests"].append(case)
    calls = set()
    for src, dst in q("select src, dst from edges where kind='calls'"):
        a, b = top.get(src), top.get(dst)
        if a in syms and b in syms and a != b:
            calls.add((a, b))

    case_count = dict(q("""select f.path, count(*) from nodes t join nodes f on f.id=t.parent_id
                           where t.display_kind='test case' group by f.path"""))

    def enrich(c):
        if c.get("children"):
            for k in c["children"]:
                enrich(k)
            return
        c["tests"] = [{"file": f, "cases": case_count.get(f, 0)} for f in c["files"] if f in tests_files]
        c["files"] = [f for f in c["files"] if f not in tests_files]
        c["symbols"] = sorted((s for s in syms.values() if s["concept"] == c["id"]), key=lambda s: (s["file"], s["line"]))
        ids = {s["id"] for s in c["symbols"]}
        c["calls"] = sorted([a, b] for a, b in calls if a in ids and b in ids)
        c["callsOut"] = sorted({syms[b]["concept"] for a, b in calls if a in ids and b not in ids})

    for c in answer["concepts"]:
        enrich(c)
    (HERE / "orchestra-concepts.js").write_text("loadConcepts(" + json.dumps(answer, indent=1) + ");\n")
    n = sum(len(l["symbols"]) for l in leaves(answer["concepts"]))
    print(f"ok: {len(owner)} files owned, {n} symbols, {len(calls)} calls, {len(pairs)} import pairs")


if __name__ == "__main__":
    main(sys.argv[1])
