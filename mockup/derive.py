"""Join the agent's concept answer with a cbi model and write the mockup's data file.

usage: uv run python mockup/derive.py <model.db> <repo root>
Reads mockup/orchestra-concepts.json, writes mockup/orchestra-concepts.js.
Fails if a TS/TSX file is owned by no leaf or by two, a relationship names an unknown concept,
an integration point's file is not owned by its internal end, or a screen region names a missing component.
Prints leaf-level import pairs that have no labelled relationship.
"""

import json
import os
import re
import sqlite3
import sys
from pathlib import Path

HERE = Path(__file__).parent
SHOWN = ("class", "function", "component")
ENV = re.compile(r"""(?:process\.env|import\.meta\.env)(?:\.([A-Z_][A-Z0-9_]*)|\[["']([A-Z_][A-Z0-9_]*)["']\])(?:\s*(?:\?\?|\|\|)\s*["'`]([^"'`]*)["'`])?""")
SPREAD = re.compile(r"\.\.\.process\.env\b")
REEXPORT = re.compile(r"""export\s+(?!type\b)(\*|\{([^}]*)\})\s+from\s+["']([^"']+)["']""")
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
    file_imports = set()  # (src file, dst file) across concepts, code only
    for s, d in q("""select s.path, d.path from edges e join nodes s on s.id=e.src join nodes d on d.id=e.dst
                     where e.kind='imports'"""):
        if s in tests_files or s not in owner or d not in owner or owner[s] == owner[d]:
            continue
        pairs.add((owner[s], owner[d]))
        file_imports.add((s, d))
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
        # Import edges between concepts, so a concept used only through imports still shows who uses it.
        def grouped(pairs_, key, files):
            out = {}
            for src, dst in pairs_:
                out.setdefault(owner[key(src, dst)], set()).add(files(src, dst))
            return [{"concept": k, "files": sorted(v)} for k, v in sorted(out.items())]
        mine_files = set(c["files"])
        c["importsIn"] = grouped([p for p in file_imports if p[1] in mine_files], lambda a, b: a, lambda a, b: b)
        c["importsOut"] = grouped([p for p in file_imports if p[0] in mine_files], lambda a, b: b, lambda a, b: b)
        # Re-exports: what this concept passes through, and the function that defines each one.
        c["reexports"] = []
        for f in c["files"]:
            for m in REEXPORT.finditer("\n".join(source(f))):
                base = os.path.normpath(os.path.join(os.path.dirname(f), m.group(3)))
                target = next((t for t in (base, base + ".ts", base + ".tsx", base + "/index.ts") if t in owner), None)
                if not target:
                    continue
                names = ["*"] if m.group(1) == "*" else [x.strip() for x in m.group(2).split(",") if x.strip() and not x.strip().startswith("type ")]
                for name in names:
                    src_name, _, as_name = name.partition(" as ")
                    d = next((x for x in syms.values() if x["file"] == target and x["name"] == src_name.strip()), None)
                    c["reexports"].append({"name": (as_name or src_name).strip(), "concept": owner[target], "def": d and d["id"]})
                    if d and d["id"] not in ids:
                        c["ghosts"][d["id"]] = {"name": d["name"], "kind": d["kind"], "concept": d["concept"]}

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
    evidence(answer, owner, syms, calls, file_imports, source)
    entries(answer, owner, root)
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


IMPORT = re.compile(r"""import\s+(type\s+)?(?:\{([^}]*)\}|\*\s+as\s+\w+|\w+)[^;'"]*from\s+["']([^"']+)["']""")
INJECTED = re.compile(r"(?:private|public|protected)\s+(?:readonly\s+)?(\w+)\s*:\s*(\w+)")


def entry_files(root, owner):
    """Deployable entry points from the manifests: package.json main, `node <file>` start scripts and
    the module scripts of HTML pages. Built paths (dist-*/x.js) map back to their source files.
    The scan on this branch has no deployable nodes yet, so the manifests are read directly."""
    rootp = Path(root)
    def source_of(path):
        path = re.sub(r"^\./", "", path)
        path = re.sub(r"^dist[^/]*/", "", path)
        stem = re.sub(r"\.(m|c)?js$", "", path)
        return next((c for c in (path, stem + ".ts", stem + ".tsx") if c in owner), None)
    found = set()
    pkg = rootp / "package.json"
    if pkg.exists():
        meta = json.loads(pkg.read_text())
        for path in [meta.get("main") or ""] + re.findall(r"\bnode\s+(\S+\.(?:m|c)?js)", " ".join((meta.get("scripts") or {}).values())):
            if path and (f := source_of(path)):
                found.add(f)
    for html in rootp.glob("**/*.html"):
        rel = html.relative_to(rootp).as_posix()
        if re.match(r"(node_modules|dist|\.)", rel) or "/dist" in rel:
            continue
        for src in re.findall(r"""<script[^>]+src=["']([^"']+)["']""", html.read_text()):
            path = src.lstrip("/") if src.startswith("/") else os.path.normpath(os.path.join(os.path.dirname(rel), src))
            if f := source_of(path):
                found.add(f)
    return found


def entries(answer, owner, root):
    """Mark entry concepts: a leaf owning an entry file, and every concept above it. An explicit
    "entry" in the concept answer wins. The entry files are listed on the leaf for the drawer."""
    files = entry_files(root, owner)
    marked = {}
    def walk(c):
        kids = c.get("children") or []
        own = [f for f in c.get("files", []) + [t["file"] for t in c.get("tests", [])] if f in files]
        hit = any([walk(k) for k in kids]) or bool(own)
        if own:
            c["entryFiles"] = sorted(own)
        if "entry" not in c:
            c["entry"] = hit
        return hit
    for c in answer["concepts"]:
        walk(c)


def evidence(answer, owner, syms, calls, file_imports, source):
    """Say what backs each relationship: resolved calls, value imports, or only the concept map ("stated").

    For stated ones, collect what the code does show: type-only imports, and calls through a
    constructor-injected field whose type is a local interface (this.audit.append()).
    """
    leaves_of = {}
    def collect(c):
        kids = c.get("children") or []
        leaves_of[c["id"]] = [c["id"]] if not kids else [l for k in kids for l in collect(k)]
        return leaves_of[c["id"]]
    for c in answer["concepts"]:
        collect(c)

    def resolve(f, spec):
        base = os.path.normpath(os.path.join(os.path.dirname(f), spec))
        return next((t for t in (base, base + ".ts", base + ".tsx", base + "/index.ts") if t in owner), None)

    type_imports = []  # (src file, dst file, names, line)
    for f in owner:
        if re.search(r"\.test\.tsx?$", f):  # tests are not evidence of how the code is wired
            continue
        text = "\n".join(source(f))
        for m in IMPORT.finditer(text):
            dst = resolve(f, m.group(3))
            if dst and m.group(1):
                names = [n.strip() for n in (m.group(2) or "").split(",") if n.strip()]
                type_imports.append((f, dst, names, text.count("\n", 0, m.start()) + 1))
    type_only = {(a, b) for a, b, _, _ in type_imports}

    def enclosing(f, line):
        best = None
        for x in syms.values():
            if x["file"] == f and x["line"] <= line <= x["end"]:
                best = x
        return best and best["id"]

    for r in answer["relationships"]:
        if r["from"].startswith("x.") or r["to"].startswith("x."):
            continue
        if r.get("kind") == "hosts":  # one runs the other (a window, a process): no call to resolve
            r["backing"] = "hosts"
            continue
        lf, lt = set(leaves_of.get(r["from"], [])), set(leaves_of.get(r["to"], []))
        if any(syms[a]["concept"] in lf and syms[b]["concept"] in lt for a, b in calls):
            r["backing"] = "calls"
            continue
        if any(owner[a] in lf and owner[b] in lt and (a, b) not in type_only for a, b in file_imports):
            r["backing"] = "imports"
            continue
        r["backing"] = "stated"
        ev = []
        for a, b, names, line in type_imports:
            if owner[a] in lf and owner[b] in lt:
                ev.append({"kind": "type import", "names": names, "file": a, "line": line, "symbol": None})
                # Injected fields typed by a local interface that mentions one of those imported types.
                lines = source(a)
                text = "\n".join(lines)
                for m in INJECTED.finditer(text):
                    field, typ = m.groups()
                    body = re.search(rf"interface\s+{typ}\s*\{{([^}}]*)\}}", text)
                    if not body or not any(n in body.group(1) for n in names):
                        continue
                    found = 0
                    for n, src_line in enumerate(lines, 1):
                        if found == 3:  # a few call sites are enough to show the pattern
                            break
                        for c in re.finditer(rf"this\.{field}\.(\w+)\(", src_line):
                            found += 1
                            ev.append({"kind": "injected", "field": field, "type": typ, "method": c.group(1),
                                       "file": a, "line": n, "symbol": enclosing(a, n)})
                            break
        r["evidence"] = ev


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
