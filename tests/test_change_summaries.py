"""Grounded per-concept judgement and content-keyed reuse across comparisons."""

import json

import pytest

from cbi import change_summaries, diff, review, store, tasks
from test_diff import _concept, _concepts, commit_tree, scan_into


@pytest.fixture
def comparison(make_repo, monkeypatch, capsys, tmp_path):
    files = {
        "src/caller.ts": 'import { compute } from "./engine";\nexport function caller() { return compute(); }\n',
        "src/engine.ts": "export function compute() { return 1; }\n",
        "tools/config.json": '{"retries": 1}\n',
        "other/untouched.ts": "export function untouched() { return 10; }\n",
    }
    root = make_repo(files, name="summaries")
    monkeypatch.chdir(root)
    document = _concepts([
        _concept("engine", "Billing core", ["src/engine.ts"]),
        _concept("callers", "Callers", ["src/caller.ts"]),
        _concept("tooling", "Shared tooling", ["tools/config.json"]),
        _concept("other", "Unrelated", ["other/untouched.ts"]),
    ], [], [])
    scan_into(capsys, tmp_path / "base", document)
    commit_tree(root, {**files,
                       "src/engine.ts": files["src/engine.ts"].replace("return 1", "return 2"),
                       "tools/config.json": '{"retries": 2}\n'})
    scan_into(capsys, tmp_path / "head", document)
    base = store.open_db(tmp_path / "base" / "model.db")
    head = store.open_db(tmp_path / "head" / "model.db")
    tasks.attach_cache(head)
    try:
        yield base, head, diff.compare(base, head), root
    finally:
        base.close()
        head.close()


def _answer(head, entry):
    brief = tasks.brief(head, entry["task_id"])
    return {"input_hash": brief["input_hash"],
            "narrative": "The engine computation changed, affecting its caller; the model alone does not establish intent or runtime safety.",
            "citations": [next(c for c in brief["citations"] if "engine.ts" in c)]}


def test_one_task_per_changed_concept_and_whole_diff(comparison):
    base, head, result, _root = comparison
    change_summaries.enrich(base, head, result)
    summaries = result["summaries"]
    # Configuration-only changes have no changed function, but still need a paragraph.
    assert set(summaries["concepts"]) == {item["id"] for item in result["overview"]["items"]}
    assert {"engine", "tooling"} <= set(summaries["concepts"])
    assert "other" not in summaries["concepts"]
    entries = [summaries["overall"], *summaries["concepts"].values()]
    assert all(entry["state"] == "pending" for entry in entries)
    assert len({entry["task_id"] for entry in entries}) == len(entries)
    for entry in entries:
        brief = tasks.brief(head, entry["task_id"])
        assert brief["kind"] == "summarise-architecture-change"
        assert brief["changes"]["overview"]
        assert brief["citations"]
        assert "other/untouched.ts" not in brief["citations"]


def test_grounding_rejects_unknown_citations_in_check_and_submit(comparison):
    base, head, result, _root = comparison
    change_summaries.enrich(base, head, result)
    entry = result["summaries"]["concepts"]["engine"]
    answer = _answer(head, entry)
    assert tasks.check(head, entry["task_id"], json.dumps(answer)) == []
    for citation in ("invented/payment.ts#charge", "other/untouched.ts", "engine"):
        answer["citations"] = [citation]
        for validate in (tasks.check, tasks.submit):
            with pytest.raises(tasks.AnswerError, match="citation"):
                validate(head, entry["task_id"], json.dumps(answer))
    assert tasks._task(head, entry["task_id"])["state"] == "open"


def test_missing_citations_are_rejected(comparison):
    base, head, result, _root = comparison
    change_summaries.enrich(base, head, result)
    entry = result["summaries"]["concepts"]["engine"]
    answer = _answer(head, entry)
    for citations in ([], None):
        candidate = {**answer, "citations": citations}
        with pytest.raises(tasks.AnswerError, match="citations"):
            tasks.check(head, entry["task_id"], json.dumps(candidate))


def test_answers_survive_task_rebuild_and_render_in_payload(comparison):
    base, head, result, _root = comparison
    change_summaries.enrich(base, head, result)
    entry = result["summaries"]["concepts"]["engine"]
    answer = _answer(head, entry)
    tasks.submit(head, entry["task_id"], json.dumps(answer))
    # Rebuilding derived task rows does not discard shared judgement.
    head.execute("DELETE FROM tasks WHERE kind = 'summarise-architecture-change'")
    head.commit()
    again = diff.compare(base, head)
    change_summaries.enrich(base, head, again)
    restored = again["summaries"]["concepts"]["engine"]
    assert restored["state"] == "answered"
    assert restored["task_id"] == entry["task_id"]
    assert restored["narrative"] == answer["narrative"]
    assert restored["citations"] == answer["citations"]
    assert answer["narrative"] in diff.render(again, "json")
    assert answer["narrative"] in diff.render(again, "markdown", concept="engine")
    assert "Summary pending: run cbi tasks" in diff.render(again)
    diagram = review.build_diagram(again, base, head)
    text = review.render_review(
        _root, "a" * 40, "b" * 40, {}, again, diagram,
        review.render_mermaid(diagram), None, None, None,
    )
    assert answer["narrative"] in text and answer["citations"][0] in text


@pytest.mark.parametrize("side", ["base", "head"])
def test_either_model_content_change_invalidates_answer(comparison, side):
    base, head, result, _root = comparison
    change_summaries.enrich(base, head, result)
    entry = result["summaries"]["concepts"]["engine"]
    tasks.submit(head, entry["task_id"], json.dumps(_answer(head, entry)))
    changed = base if side == "base" else head
    changed.execute("UPDATE nodes SET content_hash = 'new-content' WHERE path = 'src/engine.ts'")
    changed.commit()
    again = diff.compare(base, head)
    change_summaries.enrich(base, head, again)
    fresh = again["summaries"]["concepts"]["engine"]
    assert fresh["state"] == "pending" and fresh["task_id"] != entry["task_id"]


def test_edge_change_invalidates_but_task_state_and_scan_time_do_not(comparison):
    base, head, result, _root = comparison
    before = change_summaries.model_hash(head)
    head.execute("UPDATE tasks SET state = 'done'")
    head.execute("UPDATE nodes SET summary = 'Accepted agent summary', summary_source = 'agent'")
    store.set_meta(head, "last_scan", "tomorrow")
    head.commit()
    assert change_summaries.model_hash(head) == before
    head.execute("UPDATE edges SET weight = weight + 1 WHERE kind = 'calls'")
    head.commit()
    assert change_summaries.model_hash(head) != before


@pytest.mark.parametrize("sibling_changed", [False, True])
def test_nested_configuration_only_leaf_gets_its_own_task(make_repo, monkeypatch, capsys, tmp_path, sibling_changed):
    files = {"tools/config.json": '{"retries": 1}\n',
             "other/config.json": '{"enabled": true}\n'}
    root = make_repo(files, name="nested-summaries")
    monkeypatch.chdir(root)
    document = _concepts([{
        "id": "platform", "name": "Platform", "summary": "Platform.", "role": "core",
        "children": [{
            "id": "tooling", "name": "Tooling", "summary": "Tooling.", "role": "core",
            "children": [_concept("configuration", "Configuration", ["tools/config.json"])],
        }, _concept("other", "Other", ["other/config.json"])],
    }], [], [])
    scan_into(capsys, tmp_path / "nested-base", document)
    head_files = {**files, "tools/config.json": '{"retries": 2}\n'}
    if sibling_changed:
        head_files["other/config.json"] = '{"enabled": false}\n'
    commit_tree(root, head_files)
    scan_into(capsys, tmp_path / "nested-head", document)
    base = store.open_db(tmp_path / "nested-base" / "model.db")
    head = store.open_db(tmp_path / "nested-head" / "model.db")
    try:
        result = diff.compare(base, head)
        assert not result["groups"]  # There is no symbol or structural change to discover the leaf.
        change_summaries.enrich(base, head, result)
        assert {"platform", "tooling", "configuration"} <= set(result["summaries"]["concepts"])
        assert ("other" in result["summaries"]["concepts"]) is sibling_changed
        leaf_entry = result["summaries"]["concepts"]["configuration"]
        brief = tasks.brief(head, leaf_entry["task_id"])
        assert "tools/config.json" in brief["citations"]
        assert not any("other/config.json" in citation for citation in brief["citations"])
        with pytest.raises(tasks.AnswerError, match="citation"):
            tasks.check(head, leaf_entry["task_id"], json.dumps({
                "input_hash": brief["input_hash"], "narrative": "Unrelated sibling changed.",
                "citations": ["other/config.json"],
            }))
    finally:
        base.close()
        head.close()


def test_fresh_init_then_diff_exposes_default_task_inbox(make_repo, monkeypatch, capsys, tmp_path):
    from cbi.cli import main
    from test_change_overview import sha
    from test_diff import run

    root = make_repo({"a.ts": "export function a() { return 1; }\n"}, name="fresh-inbox")
    monkeypatch.chdir(root)
    base = sha(root)
    commit_tree(root, {"a.ts": "export function a() { return 2; }\n"})
    head = sha(root)
    assert main(["init"]) == 0
    code, output, err = run(capsys, "diff", base, head, "--format", "json")
    assert code == 0, err
    result = json.loads(output)
    entry = result["summaries"]["overall"]
    code, output, err = run(capsys, "tasks", "--kind", change_summaries.KIND, "--json")
    assert code == 0, err
    assert entry["task_id"] in {task["id"] for task in json.loads(output)}
    code, output, err = run(capsys, "task", entry["task_id"], "--json")
    assert code == 0, err
    brief = json.loads(output)
    answer = tmp_path / "fresh-answer.json"
    answer.write_text(json.dumps({"input_hash": brief["input_hash"],
                                  "narrative": "The function body changed; intent and runtime impact are unknown.",
                                  "citations": ["a.ts"]}))
    code, output, err = run(capsys, "submit", entry["task_id"], str(answer))
    assert code == 0, err
    code, output, err = run(capsys, "diff", base, head, "--format", "json")
    assert code == 0, err
    assert json.loads(output)["summaries"]["overall"]["state"] == "answered"


def _branch(cid, children):
    return {"id": cid, "name": cid.title(), "summary": cid.title(), "role": "core", "children": children}


def _structural_pair(make_repo, monkeypatch, capsys, tmp_path, before, after):
    # Only judgement changes: every source file and its body stays byte-for-byte identical.
    root = make_repo({"a.ts": "export function a() { return 1; }\n",
                      "b.ts": "export function b() { return 2; }\n",
                      "c.ts": "export function c() { return 3; }\n"}, name="structural")
    monkeypatch.chdir(root)
    scan_into(capsys, tmp_path / "structural-base", _concepts(before, [], []))
    scan_into(capsys, tmp_path / "structural-head", _concepts(after, [], []))
    return (store.open_db(tmp_path / "structural-base" / "model.db"),
            store.open_db(tmp_path / "structural-head" / "model.db"))


def _brief_changes(brief):
    return [change for group in brief["changes"]["groups"] for change in group["changes"]]


@pytest.mark.parametrize("operation", ["split", "merged"])
def test_unchanged_source_split_merge_tasks_cover_every_participant(
        make_repo, monkeypatch, capsys, tmp_path, operation):
    whole = [_concept("whole", "Whole", ["a.ts", "b.ts", "c.ts"])]
    parts = [_concept("first", "First", ["a.ts"]),
             _concept("second", "Second", ["b.ts", "c.ts"])]
    before, after = (whole, parts) if operation == "split" else (parts, whole)
    base, head = _structural_pair(make_repo, monkeypatch, capsys, tmp_path, before, after)
    try:
        result = diff.compare(base, head)
        expected_kind = "concept-" + operation
        assert any(change["kind"] == expected_kind for group in result["groups"] for change in group["changes"])
        assert not any(module["files"] for item in result["overview"]["items"] for module in item["modules"])
        change_summaries.enrich(base, head, result)
        assert {"whole", "first", "second"} <= set(result["summaries"]["concepts"])
        for cid in ("whole", "first", "second"):
            brief = tasks.brief(head, result["summaries"]["concepts"][cid]["task_id"])
            changes = _brief_changes(brief)
            assert any(change["kind"] == expected_kind for change in changes), cid
            assert brief["citations"], cid
    finally:
        base.close()
        head.close()


@pytest.mark.parametrize("operation", ["renamed", "added", "removed"])
def test_nested_structural_change_rolls_up_to_all_ancestors_without_source_churn(
        make_repo, monkeypatch, capsys, tmp_path, operation):
    if operation == "renamed":
        before_leaves = [_concept("target", "Old label", ["a.ts", "b.ts", "c.ts"])]
        after_leaves = [_concept("target", "New label", ["a.ts", "b.ts", "c.ts"])]
    else:
        single = [_concept("stable", "Stable", ["a.ts", "b.ts", "c.ts"])]
        expanded = [_concept("stable", "Stable", ["a.ts", "b.ts"]),
                    _concept("target", "Target", ["c.ts"])]
        before_leaves, after_leaves = (single, expanded) if operation == "added" else (expanded, single)
    before = [_branch("outer", [_branch("middle", before_leaves)])]
    after = [_branch("outer", [_branch("middle", after_leaves)])]
    base, head = _structural_pair(make_repo, monkeypatch, capsys, tmp_path, before, after)
    try:
        result = diff.compare(base, head)
        kind = "concept-" + operation
        assert any(change["kind"] == kind for group in result["groups"] for change in group["changes"])
        change_summaries.enrich(base, head, result)
        for cid in ("target", "middle", "outer"):
            assert cid in result["summaries"]["concepts"]
            brief = tasks.brief(head, result["summaries"]["concepts"][cid]["task_id"])
            assert any(change["kind"] == kind for change in _brief_changes(brief)), cid
    finally:
        base.close()
        head.close()


def test_rename_and_reparent_preserves_both_ancestor_chains(
        make_repo, monkeypatch, capsys, tmp_path):
    before = [_branch("outer", [
        _branch("earlier", [_concept("left", "Left", ["a.ts"]),
                            _concept("target", "Old label", ["c.ts"])]),
        _branch("later", [_concept("right", "Right", ["b.ts"])]),
    ])]
    after = [_branch("outer", [
        _branch("earlier", [_concept("left", "Left", ["a.ts"])]),
        _branch("later", [_concept("right", "Right", ["b.ts"]),
                          _concept("target", "New label", ["c.ts"])]),
    ])]
    base, head = _structural_pair(make_repo, monkeypatch, capsys, tmp_path, before, after)
    try:
        result = diff.compare(base, head)
        change_summaries.enrich(base, head, result)
        for cid in ("target", "earlier", "later", "outer"):
            assert cid in result["summaries"]["concepts"]
            brief = tasks.brief(head, result["summaries"]["concepts"][cid]["task_id"])
            assert any(change["kind"] == "concept-renamed" for change in _brief_changes(brief)), cid
    finally:
        base.close()
        head.close()


def test_ancestor_evidence_does_not_combine_paths_from_different_models(
        make_repo, monkeypatch, capsys, tmp_path):
    before = [_branch("outer", [
        _branch("earlier", [_branch("moving", [_concept("keeper", "Keeper", ["a.ts"]),
                                               _concept("target", "Old label", ["c.ts"])])]),
        _branch("destination", [_concept("stable", "Stable", ["b.ts"])]),
    ])]
    after = [_branch("outer", [
        _branch("later", [_branch("moving", [_concept("keeper", "Keeper", ["a.ts"])])]),
        _branch("destination", [_concept("stable", "Stable", ["b.ts"]),
                                 _concept("target", "New label", ["c.ts"])]),
    ])]
    base, head = _structural_pair(make_repo, monkeypatch, capsys, tmp_path, before, after)
    try:
        result = diff.compare(base, head)
        change_summaries.enrich(base, head, result)
        # Target was below moving only on the base; moving is below later only
        # on the head. Neither model puts target below later.
        entry = result["summaries"]["concepts"]["later"]
        brief = tasks.brief(head, entry["task_id"])
        assert not any(change["kind"] == "concept-renamed" for change in _brief_changes(brief))
        for cid in ("moving", "earlier", "destination", "outer"):
            entry = result["summaries"]["concepts"][cid]
            brief = tasks.brief(head, entry["task_id"])
            assert any(change["kind"] == "concept-renamed" for change in _brief_changes(brief))
    finally:
        base.close()
        head.close()


def test_summary_cache_respects_line_count_availability(comparison):
    base, head, _result, _root = comparison
    measured = diff.compare(base, head, {})
    change_summaries.enrich(base, head, measured)
    entry = measured["summaries"]["concepts"]["engine"]
    tasks.submit(head, entry["task_id"], json.dumps(_answer(head, entry)))
    unknown = diff.compare(base, head)
    change_summaries.enrich(base, head, unknown)
    other = unknown["summaries"]["concepts"]["engine"]
    assert other["task_id"] != entry["task_id"]
    assert other["state"] == "pending", "measured zero claims must not be reused for unknown counts"
    repeated = diff.compare(base, head, {})
    change_summaries.enrich(base, head, repeated)
    assert repeated["summaries"]["concepts"]["engine"]["state"] == "answered"
