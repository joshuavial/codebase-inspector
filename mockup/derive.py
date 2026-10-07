"""Join the agent's concept answer with a cbi model and write the mockup's data file.

usage: uv run python mockup/derive.py <model.db> <repo root>
Reads mockup/orchestra-concepts.json, writes mockup/orchestra-concepts.js.
Fails if a TS/TSX file is owned by no leaf or by two, a relationship names an unknown concept,
an integration point's file is not owned by its internal end, or a screen region names a missing component.
Prints leaf-level import pairs that have no labelled relationship.
"""

import json
import re
import sqlite3
import sys
from pathlib import Path

HERE = Path(__file__).parent
SHOWN = ("class", "function", "component")
ENV = re.compile(r"""(?:process\.env|import\.meta\.env)(?:\.([A-Z_][A-Z0-9_]*)|\[["']([A-Z_][A-Z0-9_]*)["']\])(?:\s*(?:\?\?|\|\|)\s*["'`]([^"'`]*)["'`])?""")
SPREAD = re.compile(r"\.\.\.process\.env\b")
ARRAY = {"length", "map", "filter", "some", "every", "at", "find", "slice", "join", "toFixed"}


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


def main(db_path, root):
    lines = {}
    source = lambda f: lines.setdefault(f, (Path(root) / f).read_text().splitlines())
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
        if "at" in r:
            inner = r["to"] if r["from"].startswith("x.") else r["from"]
            file = r["at"].split(":")[0]
            assert owner.get(file, "").startswith(inner), f"{r['at']} is not owned by {inner}"

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
    for sid, parent, kind, name, path, sig, line, end in q(
        "select id, parent_id, display_kind, name, path, signature, start_line, end_line from nodes where kind='symbol'"
    ):
        if path not in owner or path in tests_files:
            continue
        top[sid] = sid if parent.endswith(path) else parent.split("#")[0] + "#" + sid.split("#")[1].split(".")[0]
        if kind in SHOWN and parent.endswith(path):
            syms[sid] = {"id": sid, "name": name, "kind": kind, "sig": sig, "file": path, "line": line,
                         "end": end, "concept": owner[path], "tests": []}
    for src, dst, case in q("""select e.src, e.dst, s.name from edges e join nodes s on s.id=e.src
                                where e.kind='tests' and e.confidence >= 0.6"""):
        t = top.get(dst)
        if t in syms and case not in syms[t]["tests"]:
            syms[t]["tests"].append(case)
    # JSX elements already arrive as calls from the TypeScript parser; component to component reads as "renders".
    calls = set()
    for src, dst in q("select src, dst from edges where kind='calls'"):
        a, b = top.get(src), top.get(dst)
        if a in syms and b in syms and a != b:
            calls.add((a, b))
    verb = lambda a, b: "renders" if syms[a]["kind"] == syms[b]["kind"] == "component" else "calls"

    # Components: props from the signature, data reads from the body text.
    for sym in syms.values():
        if sym["kind"] != "component":
            continue
        m = re.search(r"\(\{([^}]*)\}", sym["sig"] or "")
        props = [x.strip().split("=")[0].strip() for x in m.group(1).split(",")] if m else []
        sym["props"] = [x for x in props if x and x != "children"]
        body = "\n".join(source(sym["file"])[sym["line"] - 1:sym["end"]])
        reads = []
        for prop in sym["props"]:
            fields = set(re.findall(rf"(?<![.\w?]){re.escape(prop)}\??\.(\w+)", body)) - ARRAY
            reads += sorted(f"{prop}.{f}" for f in fields)
        reads += sorted({"window.orchestra." + x for x in re.findall(r"window\.orchestra\??\.([\w?.]+?)\(", body)})
        reads += sorted({h for h in re.findall(r"\b(use[A-Z]\w*)\(", body)})
        sym["reads"] = [r.replace("?", "") for r in reads][:10]

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
        mine = [(a, b) for a, b in calls if a in ids or b in ids]
        c["calls"] = sorted([a, b, verb(a, b)] for a, b in mine)
        # Foreign symbols this leaf calls or is called by, drawn as ghosts grouped by their concept.
        c["ghosts"] = {x: {"name": syms[x]["name"], "kind": syms[x]["kind"], "concept": syms[x]["concept"]}
                       for a, b in mine for x in (a, b) if x not in ids}

    for c in answer["concepts"]:
        enrich(c)

    # Env vars: process.env.X / import.meta.env.X in source (never a .env file), with any ?? or || default.
    for leaf in leaves(answer["concepts"]):
        found = {}
        for f in leaf["files"]:
            for n, text in enumerate(source(f), 1):
                hits = [(m.group(1) or m.group(2), m.group(3)) for m in ENV.finditer(text)]
                hits += [("*", None)] * len(SPREAD.findall(text))
                for name, default in hits:
                    sym = next((x for x in leaf["symbols"] if x["file"] == f and x["line"] <= n <= x["end"]), None)
                    e = found.setdefault(name, {"name": name, "default": None, "symbols": []})
                    e["default"] = e["default"] or default
                    if sym and sym["id"] not in e["symbols"]:
                        e["symbols"].append(sym["id"])
                        sym.setdefault("env", []).append(name)
        leaf["env"] = sorted(found.values(), key=lambda e: e["name"])
    for sym in syms.values():
        del sym["end"]

    # Screen sketches: every region's component must be a component symbol in the model.
    by_ref = {f"{s['file']}#{s['name']}": s["id"] for s in syms.values() if s["kind"] == "component"}
    def check(region):
        if "component" in region:
            assert region["component"] in by_ref, f"screen region names unknown component {region['component']}"
            region["component"] = by_ref[region["component"]]
        for k in region.get("children", []):
            check(k)
    for screen in answer.get("screens", []):
        check(screen["root"])
    (HERE / "orchestra-concepts.js").write_text("loadConcepts(" + json.dumps(answer, indent=1) + ");\n")
    n = sum(len(l["symbols"]) for l in leaves(answer["concepts"]))
    print(f"ok: {len(owner)} files owned, {n} symbols, {len(calls)} calls, {len(pairs)} import pairs")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
