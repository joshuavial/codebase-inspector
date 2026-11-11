"""Change overview: modules, relationships in context and the drill levels (PRD-08)."""

import json
import subprocess

import pytest

from cbi import change_overview, diff
from cbi.files import resolve_commit
from test_diff import _concept, _concepts, commit_tree, git, run, scan_into

CALLER = 'import { helper } from "./helper";\nexport function runA() {\n  return helper(1);\n}\n'
HELPER = "export function helper(n: number) {\n  return n + 1;\n}\n"


def chain(name, nxt):
    if not nxt:
        return f"export function {name}() {{\n  return 1;\n}}\n"
    return f'import {{ {nxt} }} from "../{nxt}/{nxt}";\nexport function {name}() {{\n  return {nxt}();\n}}\n'


def sha(root):
    return resolve_commit(root, "HEAD")


def test_context_modules_and_levels(make_repo, monkeypatch, tmp_path, capsys):
    # A and B change; C to H stay the same and relate only to each other, apart from A -> C and B -> E.
    files = {
        "pkg/package.json": json.dumps({"name": "pkg"}),
        "pkg/src/deep/a.ts": CALLER,
        "pkg/src/deep/helper.ts": HELPER,
        "b/b.ts": chain("b", ""),
    }
    pairs = {"c": "d", "d": "", "e": "f", "f": "", "g": "h", "h": ""}
    for name, nxt in pairs.items():
        files[f"{name}/{name}.ts"] = chain(name, nxt)
    root = make_repo(files, name="context")
    monkeypatch.chdir(root)
    concepts = [_concept("a", "A", ["pkg/src/deep/a.ts", "pkg/src/deep/helper.ts"]),
                _concept("b", "B", ["b/b.ts"])]
    concepts += [_concept(n, n.upper(), [f"{n}/{n}.ts"]) for n in [*pairs, "n"]]
    rels = [{"from": "a", "to": "c", "label": "uses"}, {"from": "b", "to": "e", "label": "uses"},
            {"from": "a", "to": "ext.api", "label": "posts", "via": "HTTP", "at": "pkg/src/deep/a.ts:runA"},
            {"from": "c", "to": "d", "label": "uses"}, {"from": "e", "to": "f", "label": "uses"},
            {"from": "g", "to": "h", "label": "uses"}]
    doc = _concepts(concepts, [{"id": "ext.api", "name": "API", "summary": "Remote.", "kind": "saas"}], rels)
    base_sha = sha(root)
    scan_into(capsys, tmp_path / "base", doc)
    commit_tree(root, {
        **files,
        "pkg/src/deep/a.ts": CALLER.replace("helper(1)", "helper(2)"),
        "pkg/src/deep/helper.ts": HELPER.replace("n + 1", "n + 2"),
        "b/b.ts": chain("b", "e"),
        "n/n.ts": chain("n", ""),
    })
    head_sha = sha(root)
    scan_into(capsys, tmp_path / "head", doc)
    base, head = diff.open_model(tmp_path / "base"), diff.open_model(tmp_path / "head")
    try:
        result = diff.compare(base, head, change_overview.git_line_stats(root, base_sha, head_sha))
    finally:
        base.close()
        head.close()
    overview = result["overview"]
    items = {item["id"]: item for item in overview["items"]}
    # A ranks first: its unchanged HTTP integration is evidenced at runA, which changed.
    assert [item["id"] for item in overview["items"]] == ["a", "b", "n"]
    assert items["a"]["attention"]["integrations"] == [
        "A -> API  posts  via HTTP  at pkg/src/deep/a.ts:runA (changed)"]
    assert items["n"]["state"] == "added" and items["b"]["state"] == "changed"
    assert overview["totals"]["files"] == {"changed": 3, "added": 1, "total": 4}

    # E3: only relationships that touch the focus, with unchanged ends kept as context.
    rel_a = items["a"]["relationships"]
    assert [(r["from"], r["to"], r["state"]) for r in rel_a] == [("a", "c", "unchanged"), ("a", "ext.api", "unchanged")]
    # B -> E gained a call, so the diff's volume change marks the context row.
    assert [(r["to"], r["state"]) for r in items["b"]["relationships"]] == [("e", "changed")]
    listed = {(r["from"], r["to"]) for item in items.values() for r in item["relationships"]}
    assert not listed & {("c", "d"), ("e", "f"), ("g", "h")}

    # E4: the package is the module, the folder chain is not, and each changed file appears once.
    [module] = items["a"]["modules"]
    assert module["kind"] == "package" and module["name"] == "pkg"
    paths = [f["path"] for item in items.values() for m in item["modules"] for f in m["files"]]
    assert sorted(paths) == ["b/b.ts", "n/n.ts", "pkg/src/deep/a.ts", "pkg/src/deep/helper.ts"]
    assert module["measures"]["files"]["total"] == 2 and module["measures"]["churn"] == 4
    # runA -> helper stays inside the module but crosses between its files.
    assert not any(r["to_name"] == "helper" for r in module["relationships"])

    # A function sees its own caller and callee, not the C -> D call.
    a_file = next(f for f in module["files"] if f["path"].endswith("/a.ts"))
    [run_a] = a_file["symbols"]
    assert run_a["name"] == "runA" and run_a["measures"]["additions"] == 1
    assert any(r["to_name"] == "helper" for r in a_file["relationships"])
    calls = {(r["from_name"], r["to_name"], r["kind"]) for r in run_a["relationships"]}
    assert ("runA", "helper", "calls") in calls
    assert all("runA" in (r["from_name"], r["to_name"]) for r in run_a["relationships"])

    # Each level renders, as text and Markdown, and the CLI flags select it.
    text = diff.render(result)
    assert text.startswith("Change overview\n") and "1. A `a`" in text and "--concept ID" in text
    md = diff.render(result, "markdown")
    assert md.startswith("# Change overview\n") and "## 1. A `a`" in md
    concept = diff.render(result, concept="a")
    assert concept.startswith("Concept: A `a`") and "- A -> C  uses  unchanged" in concept and "--module ID" in concept
    assert "- pkg `" in concept and "C -> D" not in concept
    mod = diff.render(result, "markdown", module=module["id"])
    assert mod.startswith("# Module: pkg") and "- pkg/src/deep/a.ts `" in mod
    file_text = diff.render(result, file="pkg/src/deep/a.ts")
    assert file_text.startswith("File: pkg/src/deep/a.ts") and "- runA `" in file_text
    sym = diff.render(result, symbol=run_a["id"])
    assert sym.startswith("Symbol: runA") and "runA -> helper  calls" in sym
    assert diff.render(result, file="nope.ts") == "no changed item matches nope.ts\n"
    selection = json.loads(diff.render(result, "json", file="pkg/src/deep/a.ts"))["selection"]
    assert selection["level"] == "file" and selection["item"]["path"] == "pkg/src/deep/a.ts"
    detail = diff.render(result, detail=True)
    assert "symbol-changed" in detail and "Change overview" not in detail

    code, out, err = run(capsys, "diff", "--base-model", str(tmp_path / "base"),
                         "--head-model", str(tmp_path / "head"), "--symbol", "runA")
    assert code == 0, err
    assert out.startswith("Symbol: runA")


def test_binary_counts_as_one_changed_file(make_repo, tmp_path):
    root = make_repo({"a.ts": "export const a = 1\n"}, name="binary")
    base = sha(root)
    (root / "logo.bin").write_bytes(b"\x00\x01")
    git(root, "add", "logo.bin")
    git(root, "commit", "-q", "-m", "binary")
    stats = change_overview.git_line_stats(root, base, sha(root))
    measure = change_overview._measure(binary=1 if stats["logo.bin"]["binary"] else 0)
    assert measure["churn"] == 1 and change_overview._measure_line(measure).endswith("1 binary file")


def test_git_line_stats_diff_hunk_with_dashes_and_pluses(make_repo):
    base_doc = (
        "---\n"
        "title: Old Doc\n"
        "---\n"
        "-- old option\n"
        "---x;\n"
        "keep this\n"
        "old footer\n"
    )
    head_doc = (
        "---\n"
        "title: New Doc\n"
        "---\n"
        "++ new option\n"
        "+++y;\n"
        "keep this\n"
        "new footer\n"
    )
    base_front = (
        "# Simple\n"
        "No frontmatter\n"
        "-- comment\n"
        "keep\n"
    )
    head_front = (
        "---\n"
        "title: Added frontmatter\n"
        "---\n"
        "# Simple\n"
        "No frontmatter\n"
        "++ comment\n"
        "keep\n"
    )
    root = make_repo({
        "doc.md": base_doc,
        "front.md": base_front,
        "app.ts": "export const x = 1;\n",
    }, name="diff-hunk-parse")
    base_sha = sha(root)
    commit_tree(root, {
        "doc.md": head_doc,
        "front.md": head_front,
        "app.ts": "export const x = 2;\n",
    })
    head_sha = sha(root)
    stats = change_overview.git_line_stats(root, base_sha, head_sha)
    assert stats["doc.md"]["old_path"] == "doc.md"
    assert stats["doc.md"]["path"] == "doc.md"
    assert stats["doc.md"]["additions"] == 4
    assert stats["doc.md"]["deletions"] == 4
    assert stats["doc.md"]["added_lines"] == [2, 4, 5, 7]
    assert stats["doc.md"]["deleted_lines"] == [2, 4, 5, 7]

    assert stats["front.md"]["additions"] == 4
    assert stats["front.md"]["deletions"] == 1
    assert stats["front.md"]["added_lines"] == [1, 2, 3, 6]
    assert stats["front.md"]["deleted_lines"] == [3]

    assert stats["app.ts"]["additions"] == 1
    assert stats["app.ts"]["deletions"] == 1
    assert stats["app.ts"]["added_lines"] == [1]
    assert stats["app.ts"]["deleted_lines"] == [1]


def test_git_line_stats_prevents_option_injection(make_repo, tmp_path):
    root = make_repo({"a.ts": "export const a = 1\n"}, name="injection")
    target = tmp_path / "injected.txt"
    head = sha(root)
    with pytest.raises(subprocess.CalledProcessError):
        change_overview.git_line_stats(root, f"--output={target}", head)
    assert not target.exists()


def test_nested_index_distinguishes_rollups_and_preserves_evidence_verbs(
        make_repo, monkeypatch, tmp_path, capsys):
    files = {
        "src/engine.ts": "export function compute() { return 1; }\n",
        "src/engine.test.ts": 'import { compute } from "./engine";\ntest("computes", () => compute());\n',
        "src/stable.ts": "export const stable = 1;\n",
    }
    root = make_repo(files, name="nested-index")
    monkeypatch.chdir(root)
    leaf = _concept("engine", "Computation", ["src/engine.ts", "src/engine.test.ts", "src/stable.ts"])
    document = _concepts([{"id": "platform", "name": "Platform", "summary": "Contains services.",
                           "role": "core", "children": [leaf]}], [], [])
    scan_into(capsys, tmp_path / "base", document)
    commit_tree(root, {**files, "src/engine.ts": files["src/engine.ts"].replace("return 1", "return 2"),
                       "src/engine.test.ts": files["src/engine.test.ts"].replace('"computes"', '"computes again"')})
    scan_into(capsys, tmp_path / "head", document)
    base, head = diff.open_model(tmp_path / "base"), diff.open_model(tmp_path / "head")
    try:
        [parent] = diff.compare(base, head)["overview"]["items"]
    finally:
        base.close()
        head.close()
    assert parent["state_label"] == "Changes inside"
    assert parent["change_scope"] == "descendants"
    assert parent["own_modules"] == []
    [child] = parent["children"]
    assert child["id"] == "engine" and child["state_label"] == "Changed here"
    assert child["change_scope"] == "direct"
    files = [file for module in child["own_modules"] for file in module["files"]]
    assert {f["path"] for f in files} == {"src/engine.ts", "src/engine.test.ts"}
    assert {f["owner_id"] for f in files} == {"engine"}
    assert next(f for f in files if f["path"].endswith("test.ts"))["is_test"]
    [symbol] = next(f for f in files if f["path"] == "src/engine.ts")["symbols"]
    assert symbol["verb"] == "Body changed"
    assert len([f for module in parent["modules"] for f in module["files"]]) == 2


def test_added_file_does_not_make_existing_concept_added(make_repo, monkeypatch, tmp_path, capsys):
    files = {"src/stable.ts": "export function stable() { return 1; }\n"}
    root = make_repo(files, name="existing-concept")
    monkeypatch.chdir(root)
    before = _concepts([_concept("engine", "Computation", ["src/stable.ts"])], [], [])
    after = _concepts([_concept("engine", "Computation", ["src/stable.ts", "src/new.ts"])], [], [])
    scan_into(capsys, tmp_path / "base", before)
    commit_tree(root, {**files, "src/new.ts": "export function fresh() { return 2; }\n"})
    scan_into(capsys, tmp_path / "head", after)
    base, head = diff.open_model(tmp_path / "base"), diff.open_model(tmp_path / "head")
    try:
        [item] = diff.compare(base, head)["overview"]["items"]
    finally:
        base.close()
        head.close()
    assert item["state"] == "changed"
    assert item["state_label"] == "Changed here"


def test_ownership_move_is_one_reference_reachable_from_both_concepts(
        make_repo, monkeypatch, tmp_path, capsys):
    files = {f"src/{name}.ts": f"export function {name}() {{ return {number}; }}\n"
             for number, name in enumerate(("left", "right", "transfer"), 1)}
    root = make_repo(files, name="ownership-move")
    monkeypatch.chdir(root)
    before = _concepts([_concept("left", "Producer", ["src/left.ts", "src/transfer.ts"]),
                        _concept("right", "Consumer", ["src/right.ts"])], [], [])
    after = _concepts([_concept("left", "Producer", ["src/left.ts"]),
                       _concept("right", "Consumer", ["src/right.ts", "src/transfer.ts"])], [], [])
    scan_into(capsys, tmp_path / "base", before)
    scan_into(capsys, tmp_path / "head", after)
    base, head = diff.open_model(tmp_path / "base"), diff.open_model(tmp_path / "head")
    try:
        items = diff.compare(base, head)["overview"]["items"]
    finally:
        base.close()
        head.close()
    assert {item["id"] for item in items} == {"left", "right"}
    assert all(item["state_label"] == "Moved" for item in items)
    assert all(item["modules"] == [] for item in items)
    [first], [second] = [item["moves"] for item in items]
    assert first == second
    assert first["from_name"] == "Producer" and first["to_name"] == "Consumer"
    assert first["path"] == "src/transfer.ts" and first["target_id"].endswith(":src/transfer.ts")


@pytest.mark.parametrize("operation", ["split", "merged"])
def test_split_merge_with_unchanged_source_lists_every_concept_participant(
        make_repo, monkeypatch, tmp_path, capsys, operation):
    files = {f"src/{name}.ts": f"export function {name}() {{ return {number}; }}\n"
             for number, name in enumerate(("first", "second"), 1)}
    root = make_repo(files, name="split-index")
    monkeypatch.chdir(root)
    before = _concepts([_concept("whole", "Whole", list(files))], [], [])
    after = _concepts([_concept("first", "First part", ["src/first.ts"]),
                       _concept("second", "Second part", ["src/second.ts"])], [], [])
    if operation == "merged":
        before, after = after, before
    scan_into(capsys, tmp_path / "base", before)
    scan_into(capsys, tmp_path / "head", after)
    base, head = diff.open_model(tmp_path / "base"), diff.open_model(tmp_path / "head")
    try:
        items = {item["id"]: item for item in diff.compare(base, head)["overview"]["items"]}
    finally:
        base.close()
        head.close()
    assert set(items) == {"whole", "first", "second"}
    assert items["whole"]["state_label"] == ("Removed" if operation == "split" else "Added")
    assert items["first"]["state_label"] == items["second"]["state_label"] == ("Added" if operation == "split" else "Removed")
    assert all(item["modules"] == [] for item in items.values())


def test_reparented_change_retains_both_ancestor_rollups(make_repo, monkeypatch, tmp_path, capsys):
    root = make_repo({"src/engine.ts": "export function compute() { return 1; }\n"}, name="reparent-index")
    monkeypatch.chdir(root)
    def branch(cid, children):
        return {"id": cid, "name": cid.title(), "summary": "Groups responsibilities.",
                "role": "core", "children": children}
    def document(previous):
        leaf = _concept("engine", "Earlier label" if previous else "Current label", ["src/engine.ts"])
        return _concepts([branch("root", [branch("earlier", [leaf] if previous else []),
                                           branch("later", [] if previous else [leaf])])], [], [])
    scan_into(capsys, tmp_path / "base", document(True))
    scan_into(capsys, tmp_path / "head", document(False))
    base, head = diff.open_model(tmp_path / "base"), diff.open_model(tmp_path / "head")
    try:
        [item] = diff.compare(base, head)["overview"]["items"]
    finally:
        base.close()
        head.close()
    assert {child["id"] for child in item["children"]} == {"earlier", "later"}
    assert all(child["state_label"] == "Changes inside" for child in item["children"])
    assert next(child for child in item["children"] if child["id"] == "earlier")["children"] == []
    assert next(child for child in item["children"] if child["id"] == "later")["children"][0]["id"] == "engine"


def test_line_count_availability_propagates_without_turning_unknown_into_zero(
        make_repo, monkeypatch, tmp_path, capsys):
    files = {"src/first.ts": "export function first() { return 1; }\n",
             "src/second.ts": "export function second() { return 2; }\n"}
    root = make_repo(files, name="line-availability")
    monkeypatch.chdir(root)
    document = _concepts([{"id": "parent", "name": "Parent", "summary": "Groups computation.", "role": "core",
                           "children": [_concept("engine", "Computation", list(files))]}], [], [])
    base_sha = sha(root)
    scan_into(capsys, tmp_path / "base", document)
    commit_tree(root, {path: body.replace("return ", "return 10 + ") for path, body in files.items()})
    scan_into(capsys, tmp_path / "head", document)
    stats = change_overview.git_line_stats(root, base_sha, sha(root))
    base, head = diff.open_model(tmp_path / "base"), diff.open_model(tmp_path / "head")
    try:
        unknown = diff.compare(base, head)
        measured = diff.compare(base, head, stats)
        zero = diff.compare(base, head, {})
        partial = diff.compare(base, head, {"src/first.ts": stats["src/first.ts"]})
    finally:
        base.close()
        head.close()

    def measures(result):
        found = [result["overview"]["totals"]]
        def visit(items):
            for item in items:
                found.append(item["measures"])
                for module in [*item["modules"], *item["own_modules"]]:
                    found.append(module["measures"])
                    for file in module["files"]:
                        found.append(file["measures"])
                        found.extend(symbol["measures"] for symbol in file["symbols"])
                visit(item["children"])
        visit(result["overview"]["items"])
        return found

    assert all(m["lines_known"] is False for m in measures(unknown))
    assert all(m["lines_known"] is True for m in measures(measured))
    assert all(m["lines_known"] is True for m in measures(zero))
    assert measured["overview"]["totals"]["additions"] == 2
    assert zero["overview"]["totals"]["additions"] == zero["overview"]["totals"]["deletions"] == 0
    assert "+0 -0" in diff.render(zero)
    assert "Line counts unavailable" in diff.render(unknown)
    assert "+0 -0" not in diff.render(unknown)
    assert "0 changed lines" not in diff.render(unknown)
    assert partial["overview"]["totals"]["lines_known"] is False
    [parent] = partial["overview"]["items"]
    [child] = parent["children"]
    [module] = child["own_modules"]
    assert parent["measures"]["lines_known"] is False
    assert child["measures"]["lines_known"] is False
    assert module["measures"]["lines_known"] is False
    by_path = {file["path"]: file for file in module["files"]}
    assert by_path["src/first.ts"]["measures"]["lines_known"] is True
    assert by_path["src/second.ts"]["measures"]["lines_known"] is False
    assert by_path["src/second.ts"]["symbols"][0]["measures"]["lines_known"] is False


def test_structural_zero_and_binary_line_availability(make_repo, monkeypatch, tmp_path, capsys):
    root = make_repo({"src/engine.ts": "export function compute() { return 1; }\n",
                      "image.dat": "first"}, name="structural-lines")
    monkeypatch.chdir(root)
    before = _concepts([_concept("engine", "Earlier label", ["src/engine.ts", "image.dat"])], [], [])
    after = _concepts([_concept("engine", "Current label", ["src/engine.ts", "image.dat"])], [], [])
    base_sha = sha(root)
    scan_into(capsys, tmp_path / "base", before)
    scan_into(capsys, tmp_path / "head", after)
    base, head = diff.open_model(tmp_path / "base"), diff.open_model(tmp_path / "head")
    try:
        unknown = diff.compare(base, head)
        zero = diff.compare(base, head, {})
    finally:
        base.close()
        head.close()
    assert unknown["overview"]["totals"]["lines_known"] is False
    assert unknown["overview"]["items"][0]["measures"]["lines_known"] is False
    assert zero["overview"]["totals"]["lines_known"] is True
    assert zero["overview"]["items"][0]["measures"]["lines_known"] is True
    assert "+0 -0" not in diff.render(unknown)
    assert "+0 -0" in diff.render(zero)
    (root / "image.dat").write_bytes(b"\x00\x01")
    git(root, "add", "image.dat")
    git(root, "commit", "-qm", "binary")
    scan_into(capsys, tmp_path / "binary-head", after)
    base, head = diff.open_model(tmp_path / "base"), diff.open_model(tmp_path / "binary-head")
    try:
        binary = diff.compare(base, head, change_overview.git_line_stats(root, base_sha, sha(root)))
    finally:
        base.close()
        head.close()
    assert binary["overview"]["totals"]["lines_known"] is False
    assert binary["overview"]["totals"]["binary"] == 1
    assert "Line counts unavailable" in diff.render(binary)
    assert "1 binary" in diff.render(binary)
    assert "+0 -0" not in diff.render(binary)


@pytest.mark.parametrize("count", [1, 2])
def test_line_and_measure_count_labels_agree_with_quantity(count):
    measure = change_overview._measure(additions=count, binary=count)
    measure["files"].update({"total": count})
    measure["symbols"].update({"changed": count})
    measure["tests"].update({"added": count})
    measure.update({"integrations": count, "env_vars": count})
    text = change_overview._measure_line(measure)
    suffix = "" if count == 1 else "s"
    assert f"{count} file{suffix}" in text
    assert f"{count} binary file{suffix}" in text
    assert f"symbol{suffix} {count} changed" in text
    assert f"test{suffix} +{count} -0" in text
    assert f"{count} integration{suffix}" in text
    assert f"{count} env var{suffix}" in text
    item = {"attention": {"provisional": False}, "measures": change_overview._measure(additions=count), "relationships": []}
    change_overview._attention(item, [], {})
    assert item["reasons"] == [f"{count} changed line{suffix}"]


def test_relocated_file_and_ownership_and_symbol_share_one_move_evidence(
        make_repo, monkeypatch, tmp_path, capsys):
    files = {"src/producer.ts": "export function produce() { return 1; }\n",
             "src/consumer.ts": "export function consume() { return 2; }\n",
             "src/archive.ts": "export function archive() { return 41; }\n"}
    root = make_repo(files, name="relocation-evidence")
    monkeypatch.chdir(root)
    before = _concepts([_concept("producer", "Producer", ["src/producer.ts", "src/archive.ts"]),
                        _concept("delivery", "Delivery", ["src/consumer.ts"])], [], [])
    after = _concepts([_concept("producer", "Producer", ["src/producer.ts"]),
                       _concept("delivery", "Delivery", ["src/consumer.ts", "delivery/archive.ts"])], [], [])
    scan_into(capsys, tmp_path / "base", before)
    head_files = {path: body for path, body in files.items() if path != "src/archive.ts"}
    head_files["delivery/archive.ts"] = files["src/archive.ts"]
    commit_tree(root, head_files)
    scan_into(capsys, tmp_path / "head", after)
    base, head = diff.open_model(tmp_path / "base"), diff.open_model(tmp_path / "head")
    try:
        result = diff.compare(base, head)
    finally:
        base.close()
        head.close()
    items = {item["id"]: item for item in result["overview"]["items"]}
    raw_kinds = {change["kind"] for group in result["groups"] for change in group["changes"]}
    expected = {"file-moved-concept", "file-moved", "symbol-moved"}
    assert expected <= raw_kinds
    assert len(items["producer"]["moves"]) == len(items["delivery"]["moves"]) == 1
    [move] = items["delivery"]["moves"]
    assert move == items["producer"]["moves"][0]
    assert set(move["kinds"]) == expected
    assert move["from"] == "producer" and move["to"] == "delivery"
    assert move["path"] == "delivery/archive.ts"
    assert move["target_id"].endswith(":delivery/archive.ts")


def test_attention_ranking_for_concept_renamed_and_integration_removed():
    def make_item(cid, name, churn=0):
        return {
            "id": cid,
            "name": name,
            "attention": {
                "integrations": [], "untested": 0, "structure": [], "relationships": [],
                "env_vars": [], "removed_tests": 0, "provisional": False,
            },
            "measures": change_overview._measure(additions=churn),
            "relationships": [],
        }

    # concept-renamed is in STRUCTURE_KINDS and populates attention["structure"]
    item_renamed = make_item("c1", "RenamedConcept", churn=10)
    change_overview._attention(item_renamed, [{"kind": "concept-renamed", "summary": "Old -> New"}], {})
    assert item_renamed["attention"]["structure"] == ["Old -> New"]
    assert "1 structural change" in item_renamed["reasons"]
    why_renamed = change_overview._why(item_renamed)
    assert "- Old -> New" in why_renamed

    # integration-removed is in INTEGRATION_ATTENTION, populates attention["integrations"],
    # and counts toward measures["integrations"]
    item_removed_int = make_item("c2", "IntRemovedConcept", churn=10)
    change_overview._attention(
        item_removed_int,
        [{"kind": "integration-removed", "summary": "c2 -> ext.api  calls  via HTTP"}],
        {},
    )
    assert item_removed_int["attention"]["integrations"] == ["c2 -> ext.api  calls  via HTTP"]
    assert item_removed_int["measures"]["integrations"] == 1
    assert any("integration point" in r for r in item_removed_int["reasons"])
    why_int = change_overview._why(item_removed_int)
    assert "- c2 -> ext.api  calls  via HTTP" in why_int

    # Relative attention ranking check:
    # 1. Integrations (c2) > 2. Untested (c0) > 3. Structure (c1) > 4. Relationships (c4) > 5. Churn (c3)
    item_untested = make_item("c0", "UntestedConcept", churn=10)
    item_untested["measures"]["untested"] = 1
    change_overview._attention(item_untested, [], {})

    item_churn = make_item("c3", "ChurnConcept", churn=100)
    change_overview._attention(item_churn, [], {})

    item_rel = make_item("c4", "RelConcept", churn=50)
    change_overview._attention(item_rel, [{"kind": "relationship-added", "summary": "c4 -> c1"}], {})

    ranked = sorted([item_churn, item_rel, item_renamed, item_untested, item_removed_int], key=change_overview._attention_key)
    assert [it["id"] for it in ranked] == ["c2", "c0", "c1", "c4", "c3"]

