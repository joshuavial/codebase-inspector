"""cbi check: changed files, JSON checks, stale answers, secrets, warn mode."""

import json
from pathlib import Path

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
    spec = run_json(capsys, "task", task["id"], "--parts")
    assert spec["budget"] == 200
    assert spec["brief_bytes"] > 200
    assert spec["split"] is True


def test_readme_has_the_team_init_snippet():
    text = README.read_text()
    for line in team.CI_SNIPPET.splitlines():
        assert line.strip() in text
