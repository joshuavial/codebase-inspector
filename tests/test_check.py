"""cbi check: changed files, JSON checks, stale answers, secrets, warn mode."""

import json
import sqlite3
from pathlib import Path

import pytest

from cbi import check, team
from cbi.cli import main

from test_team import MAP, answer_all, answer_files, concepts_answer, git, judgement_paths, run, run_json, submit

README = Path(__file__).resolve().parents[1] / "README.md"


def commit(root, message):
    git(root, "add", "--", *judgement_paths(root))
    git(root, "commit", "-m", message)


def prepared(make_repo, monkeypatch, capsys, tmp_path, name="repo"):
    root = make_repo(MAP, name=name)
    monkeypatch.chdir(root)
    assert main(["init"]) == 0
    assert main(["scan"]) == 0
    answer_all(capsys, tmp_path)
    assert main(["team", "init"]) == 0
    commit(root, "map")
    return root


def test_secret_patterns_skip_hex_and_prose():
    assert check.secret_kind("Uses ghp_" + "a" * 36 + " in one call.") == "github token"
    assert check.secret_kind("-----BEGIN RSA PRIVATE KEY-----\nMII") == "private key"
    assert check.secret_kind("AKIAIOSFODNN7EXAMPLE") == "aws access key"
    assert check.secret_kind("About a.ts.") is None
    assert check.secret_kind("ab" * 30) is None
    assert check.secret_kind("supercalifragilisticexpialidocious") is None
    assert check.secret_kind("0123456789abcdef" * 4) is None
    # Measured Shannon entropy is about 4.48, under a 4.5 cut.
    token = "j0vjAGU6dUCjING2F4oerFrsbhQzh9eW"
    assert check.secret_kind(f"kept {token} locally") == "high-entropy token"
    assert check.secret_kind("20250314_add_unique_workspace_member_fkey") == "high-entropy token"
    assert check.secret_kind("db/migrations/20250314_add_unique_workspace_member_fkey") is None
    assert check.secret_kind("20250314_add_unique_workspace_member_fkey", {
        "20250314_add_unique_workspace_member_fkey",
    }) is None


def test_screen_region_ids_are_not_secrets_but_real_tokens_are():
    region_id = "panel_20260827_selected_membership"
    answer = {
        "screens": [{
            "id": "main", "name": "Main", "device": "desktop",
            "root": {"id": region_id, "layout": "column", "children": []},
        }],
    }
    assert check._answer_secret(answer, check._region_ids(answer)) is None
    answer["screens"][0]["root"]["text"] = "j0vjAGU6dUCjING2F4oerFrsbhQzh9eW"
    assert check._answer_secret(answer, check._region_ids(answer)) == "high-entropy token"


def test_not_a_repo_and_not_initialised(make_repo, monkeypatch, capsys, tmp_path):
    monkeypatch.chdir(tmp_path)
    code, _out, err = run(capsys, "check")
    assert code == 1 and "not inside a git repository" in err
    root = make_repo({"a.ts": "export const a = 1\n"}, name="bare")
    monkeypatch.chdir(root)
    code, _out, err = run(capsys, "check")
    assert code == 1 and "not initialised" in err
    assert main(["init"]) == 0
    code, _out, err = run(capsys, "check", "--base", "no-such")
    assert code == 1 and "unknown ref" in err


def test_uncommitted_code_needs_a_summary_and_a_doc_does_not(make_repo, monkeypatch, capsys):
    root = make_repo({"a.ts": "export const a = 1\n", "README.md": "# Demo\n"}, name="plain")
    monkeypatch.chdir(root)
    main(["init"])
    main(["scan"])
    code, out, err = run(capsys, "check")
    assert code == 0, err
    assert "passed" in out
    (root / "README.md").write_text("# Demo\n\nMore.\n")
    code, out, err = run(capsys, "check")
    assert code == 0, err
    (root / "a.ts").write_text("export const a = 2\n")
    code, out, err = run(capsys, "check")
    assert code == 1
    assert "a.ts: changed code file has no summary" in out
    assert "no concept owns" not in out
    assert "Fix with: cbi prime" in out


def test_branch_file_fails_until_the_tasks_are_answered(make_repo, monkeypatch, capsys, tmp_path):
    root = prepared(make_repo, monkeypatch, capsys, tmp_path, name="branch")
    code, out, err = run(capsys, "check")
    assert code == 0, out + err
    answers = (root / ".cbi" / "answers.jsonl").read_bytes()
    concepts = (root / ".cbi" / "concepts.json").read_bytes()
    git(root, "checkout", "-b", "add-c")
    (root / "c.ts").write_text("export function c() { return 1 }\n")
    git(root, "add", "--", "c.ts")
    git(root, "commit", "-m", "add c")
    code, out, err = run(capsys, "check", "--base", "main")
    assert code == 1, out + err
    assert "c.ts: changed code file has no summary" in out
    assert "c.ts: no concept owns this changed file" in out
    assert ".cbi/concepts.json" in out
    assert (root / ".cbi" / "answers.jsonl").read_bytes() == answers
    assert (root / ".cbi" / "concepts.json").read_bytes() == concepts

    answer_files(capsys, tmp_path)
    [task] = run_json(capsys, "tasks", "--kind", "define-concepts")
    brief = run_json(capsys, "task", task["id"])
    body = concepts_answer(brief)
    next(concept["files"] for concept in body["concepts"] if concept["id"] == "app").append("c.ts")
    code, _text, err = submit(capsys, tmp_path, task["id"], body)
    assert code == 0, err
    code, out, err = run(capsys, "check")
    assert code == 0, out + err
    assert "passed" in out
    diff = git(root, "diff", "main", "--", ".cbi/answers.jsonl", ".cbi/concepts.json").stdout
    assert "About c.ts." in diff
    assert "c.ts" in (root / ".cbi" / "concepts.json").read_text()
    added = [line[1:] for line in diff.splitlines() if line.startswith("+") and not line.startswith("+++")]
    assert any("About c.ts." in line for line in added)


def test_changed_test_keeps_its_owner(make_repo, monkeypatch, capsys, tmp_path):
    root = prepared(make_repo, monkeypatch, capsys, tmp_path, name="tests")
    git(root, "checkout", "-b", "edit-test")
    (root / "b.test.ts").write_text('import { b } from "./b";\ntest("b again", () => { b(); });\n')
    git(root, "add", "--", "b.test.ts")
    git(root, "commit", "-m", "edit test")
    code, out, err = run(capsys, "check")
    assert code == 1, out + err
    assert "b.test.ts: changed test file has no summary" in out
    assert "no concept owns" not in out


def test_stale_answers_and_a_secret_are_refused(make_repo, monkeypatch, capsys, tmp_path):
    root = prepared(make_repo, monkeypatch, capsys, tmp_path, name="stale")
    path = root / ".cbi" / "answers.jsonl"
    rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    kept = [row for row in rows if row["answer"] != "About a.ts."]
    path.write_text("".join(json.dumps(row, sort_keys=True) + "\n" for row in kept))
    code, out, err = run(capsys, "check")
    assert code == 1, out + err
    assert "missing accepted answer summarise-files" in out
    assert "cbi team init" in out

    token = "ghp_" + "b" * 36
    rows[0]["answer"] = f"Calls the API with {token}."
    path.write_text("".join(json.dumps(row, sort_keys=True) + "\n" for row in rows))
    code, out, err = run(capsys, "check", "--format", "github")
    assert code == 1, out + err
    assert "answer looks like a github token" in out
    assert token not in out and token not in err
    assert "::error file=.cbi/answers.jsonl,line=" in out
    assert "title=secret::" in out
    assert path.read_text().count(token) == 1


def test_warn_mode_exits_zero_and_uses_warning_annotations(make_repo, monkeypatch, capsys, tmp_path):
    root = prepared(make_repo, monkeypatch, capsys, tmp_path, name="warn")
    (root / ".cbi" / "team.toml").write_text('check = "warn"\nbrief_budget = 153600\n')
    (root / "a.ts").write_text("export function a() { return 2 }\n")
    code, out, err = run(capsys, "check", "--format", "github")
    assert code == 0, err
    assert "::warning file=a.ts,title=missing summary::" in out
    assert 'check = "warn"' in out
    code, out, err = run(capsys, "check")
    assert code == 0, err
    assert out.startswith("cbi check: ")
    assert "warning" in out.splitlines()[0]


def test_team_check_reports_the_rule_that_hides_judgement(make_repo, monkeypatch, capsys, tmp_path):
    root = prepared(make_repo, monkeypatch, capsys, tmp_path, name="ignored-check")
    (root / ".gitignore").write_text("notes/\n/.cbi/\n")
    code, out, err = run(capsys, "check", "--format", "github")
    assert code == 1, out + err
    assert "::error file=.gitignore,line=2,title=ignored judgement::" in out
    assert ".cbi/concepts.json is ignored by line 2 ('/.cbi/'); remove that rule" in out
    assert "Remove the reported ignore rule" in out


def test_json_files_that_fail_their_checks(make_repo, monkeypatch, capsys, tmp_path):
    root = prepared(make_repo, monkeypatch, capsys, tmp_path, name="json")
    (root / ".cbi" / "concepts.json").write_text("{")
    code, out, err = run(capsys, "check")
    assert code == 1, out + err
    assert ".cbi/concepts.json: not valid JSON" in out
    assert (root / ".cbi" / "concepts.json").read_text() == "{"
    (root / ".cbi" / "concepts.json").write_text(concepts_text(root))
    (root / ".cbi" / "structure.json").write_text('{"packages": "nope"}\n')
    code, out, err = run(capsys, "check")
    assert code == 1
    assert ".cbi/structure.json:" in out
    assert "packages" in out


def concepts_text(root):
    """The concepts document from before a test overwrote it is not kept. Rebuild from git."""
    return git(root, "show", "HEAD:.cbi/concepts.json").stdout


def test_team_brief_budget_overrides_the_environment(make_repo, monkeypatch, capsys, tmp_path):
    root = make_repo(MAP, name="budget")
    monkeypatch.chdir(root)
    main(["init"])
    main(["scan"])
    [task] = run_json(capsys, "tasks", "--kind", "confirm-structure")
    brief = run_json(capsys, "task", task["id"])
    code, _text, err = submit(capsys, tmp_path, task["id"], {
        "input_hash": brief["input_hash"], "deployables": [], "packages": [],
    })
    assert code == 0, err
    (root / ".cbi" / "team.toml").write_text('check = "fail"\nbrief_budget = 200\n')
    monkeypatch.setenv("CBI_BRIEF_BUDGET", "99999999")
    [task] = run_json(capsys, "tasks", "--kind", "define-concepts")
    code, out, err = run(capsys, "task", task["id"], "--parts", "--json")
    # The team budget wins: 200 bytes cannot hold even the schema/envelope.
    assert code == 2 and out == ""
    assert "brief_budget is too small" in err


def test_readme_has_the_team_init_snippet():
    text = README.read_text()
    for line in team.CI_SNIPPET.splitlines():
        assert line.strip() in text


def test_check_rejects_concept_projection_drift(make_repo, monkeypatch, capsys, tmp_path):
    from cbi import store
    from cbi.cli import scan

    root = prepared(make_repo, monkeypatch, capsys, tmp_path, name="projection-drift")
    out = root / ".cbi"

    def incomplete_scan(root, out):
        scan(root, out)
        conn = store.open_db(out / "model.db")
        with conn:
            conn.execute("DELETE FROM nodes WHERE id = 'core'")
        conn.close()

    assert check.run(root, out, None, "text", incomplete_scan) == 1
    assert "concepts.json does not match the model" in capsys.readouterr().out


def test_check_validates_original_concepts_after_scan(make_repo, monkeypatch, capsys, tmp_path):
    from cbi.cli import scan

    root = prepared(make_repo, monkeypatch, capsys, tmp_path, name="rewritten-map")
    out = root / ".cbi"
    original = (out / "concepts.json").read_text()

    def rewriting_scan(root, out):
        data = json.loads(original)
        data["concepts"][0]["summary"] = "A different summary."
        (out / "concepts.json").write_text(json.dumps(data))
        scan(root, out)

    assert check.run(root, out, None, "text", rewriting_scan) == 1
    assert (out / "concepts.json").read_text() == original
    assert "concepts.json does not match the model" in capsys.readouterr().out


def test_check_rejects_a_missing_cached_concepts_document(make_repo, monkeypatch, capsys, tmp_path):
    from cbi import store

    root = prepared(make_repo, monkeypatch, capsys, tmp_path, name="missing-map")
    out = root / ".cbi"
    before_answers = (out / "answers.jsonl").read_bytes()
    (out / "concepts.json").unlink()

    code, output, error = run(capsys, "check")

    assert code == 1, output + error
    assert ".cbi/concepts.json: concepts.json is missing but the model contains its projection" in output
    assert not (out / "concepts.json").exists()
    assert (out / "answers.jsonl").read_bytes() == before_answers
    conn = store.open_db(out / "model.db")
    try:
        assert conn.execute("SELECT count(*) FROM nodes WHERE kind = 'concept'").fetchone()[0] == 2
    finally:
        conn.close()


@pytest.mark.parametrize("historical_input", [False, True])
def test_concurrent_same_input_answers_fail_check_until_explicitly_resolved(make_repo, monkeypatch, capsys, tmp_path, historical_input):
    from cbi import store, tasks

    root = prepared(make_repo, monkeypatch, capsys, tmp_path, name="concurrent-review")
    out = root / ".cbi"
    path = out / "answers.jsonl"
    baseline = path.read_text()
    document = json.loads((out / "concepts.json").read_text())
    conn = store.open_db(out / "model.db")
    task_id, key = conn.execute("SELECT id, input_hash FROM tasks WHERE kind = 'define-concepts'").fetchone()
    conn.close()
    conflict_key = "historical-input" if historical_input else key
    branches = []
    for index in range(2):
        branch = tmp_path / f"answer-branch-{index}"
        branch.mkdir()
        (branch / "team.toml").write_text(team.TEMPLATE)
        (branch / "answers.jsonl").write_text(baseline)
        conn = store.open_db(branch / "model.db")
        tasks.attach_cache(conn)
        body = {**document, "summary": f"The map reviewed on branch {index}."}
        with conn:
            conn.execute("INSERT OR REPLACE INTO cache.summary_answers (input_hash, answer) VALUES (?, ?)",
                         (conflict_key, json.dumps(body)))
            team.supersede(conn, branch, "define-concepts", conflict_key)
        conn.close()
        branches.append((branch / "answers.jsonl").read_text())
    path.write_text("".join(branches))
    code, output, err = run(capsys, "check")
    assert code == 1, output + err
    assert f"conflicting accepted answers for define-concepts {conflict_key}" in output
    [task] = run_json(capsys, "tasks", "--kind", "define-concepts")
    brief = run_json(capsys, "task", task["id"])
    assert len(brief["conflicting_acceptances"]) == 2
    code, text, err = run(capsys, "task", task["id"])
    assert code == 0, err
    assert "Concurrent accepted answers" in text and "answers.jsonl" in text
    resolved = concepts_answer(brief)
    resolved["summary"] = "The explicitly resolved application map."
    assert submit(capsys, tmp_path, task_id, resolved)[0] == 0
    code, output, err = run(capsys, "check")
    assert code == 0, output + err


def test_resolved_stale_conflict_payloads_are_checked_for_secrets(make_repo, monkeypatch, capsys, tmp_path):
    root = prepared(make_repo, monkeypatch, capsys, tmp_path, name="conflict-payload")
    out = root / ".cbi"
    path = out / "answers.jsonl"
    rows = team._parse(path.read_text())
    accepted = next(row for row in rows.values() if row["kind"] == "define-concepts" and not row.get("superseded_by"))
    key = (accepted["kind"], accepted["key"])
    metadata_id = "ghp_" + "b" * 36
    candidates = [{**team._canon(*key, accepted["protocol"], {**accepted["answer"], "summary": f"Old map {index}."}),
                   "acceptance_id": identity, "generation": accepted["generation"] + 1}
                  for index, identity in enumerate((metadata_id, "other-acceptance"))]
    stale = {**team._canon(*key, accepted["protocol"], candidates[0]["answer"]),
             "conflicts": candidates, "generation": accepted["generation"] + 1,
             "retired_acceptances": accepted.get("retired_acceptances", []) + [accepted["acceptance_id"]]}
    rows[key] = stale
    path.write_text(team._dump(rows))
    conn = sqlite3.connect(out / "model.db")
    task_id = conn.execute("SELECT id FROM tasks WHERE kind = 'define-concepts'").fetchone()[0]
    conn.close()
    brief = run_json(capsys, "task", task_id)
    resolved = concepts_answer(brief)
    resolved["summary"] = "The safe reviewed map."
    assert submit(capsys, tmp_path, task_id, resolved)[0] == 0
    current = path.read_text()
    path.write_text(current + json.dumps(stale) + "\n")
    assert not team.answer_conflicts(out, *key)
    code, output, err = run(capsys, "check")
    assert code == 0, output + err  # acceptance identities are metadata, not answer text
    stale["conflicts"][1]["answer"]["summary"] = "ghp_" + "a" * 36
    path.write_text(current + json.dumps(stale) + "\n")
    assert not team.answer_conflicts(out, *key)
    code, output, err = run(capsys, "check")
    assert code == 1, output + err
    assert "answer looks like a github token" in output
    assert "conflicting accepted answers" not in output


@pytest.mark.parametrize("fresh_model", [False, True])
def test_stale_concept_document_disagrees_with_committed_answer(
    make_repo, monkeypatch, capsys, tmp_path, fresh_model,
):
    root = prepared(make_repo, monkeypatch, capsys, tmp_path)
    path = root / ".cbi" / "concepts.json"
    stale = json.loads(path.read_text(encoding="utf-8"))
    stale["summary"] = "An older description of the app."
    path.write_text(json.dumps(stale), encoding="utf-8")
    commit(root, "keep stale document")
    if fresh_model:
        (root / ".cbi" / "model.db").unlink()
        monkeypatch.setenv("CBI_CACHE_DIR", str(tmp_path / "empty-cache"))
    before = check.snapshot(root / ".cbi")
    code, out, err = run(capsys, "check")
    assert code == 1, out + err
    assert "concepts.json does not match the committed define-concepts answer" in out
    assert check.snapshot(root / ".cbi") == before


def test_check_json_format_and_alias(make_repo, monkeypatch, capsys, tmp_path):
    root = make_repo({"a.ts": "export const a = 1\n", "README.md": "# Demo\n"}, name="check-json")
    monkeypatch.chdir(root)
    assert main(["init"]) == 0
    assert main(["scan"]) == 0

    # 1. Clean pass in JSON format via --json and --format json
    code, out, err = run(capsys, "check", "--json")
    assert code == 0, err
    data = json.loads(out)
    assert data == {"passed": True, "problems": []}

    code, out, err = run(capsys, "check", "--format", "json")
    assert code == 0, err
    assert json.loads(out) == {"passed": True, "problems": []}

    # 2. Problem detection when code file changes
    (root / "a.ts").write_text("export const a = 2\n")

    code, out, err = run(capsys, "check", "--json")
    assert code == 1
    data = json.loads(out)
    assert data["passed"] is False
    assert len(data["problems"]) == 1
    assert "a.ts: changed code file has no summary" in data["problems"][0]

    code, out, err = run(capsys, "check", "--format", "json")
    assert code == 1
    assert json.loads(out) == data

    # 3. Kind filtering in JSON output
    code, out, err = run(capsys, "check", "--kind", "secret", "--json")
    assert code == 0
    assert json.loads(out) == {"passed": True, "problems": []}

    code, out, err = run(capsys, "check", "--kind", "summary", "--json")
    assert code == 1
    data_summary = json.loads(out)
    assert data_summary["passed"] is False
    assert len(data_summary["problems"]) == 1

    # 4. Warn mode in JSON output exits 0 with passed=True
    (root / ".cbi" / "team.toml").write_text('check = "warn"\n')
    code, out, err = run(capsys, "check", "--json")
    assert code == 0
    data_warn = json.loads(out)
    assert data_warn["passed"] is True
    assert any("a.ts: changed code file has no summary" in p for p in data_warn["problems"])

