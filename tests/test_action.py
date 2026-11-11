"""Tests for GitHub Action composite contract and base-ref resolution (cbi-ekw)."""

import os
import subprocess
from pathlib import Path

import pytest

from conftest import run_command

ROOT = Path(__file__).resolve().parents[1]
ACTION_YML = ROOT / "action.yml"
CBI_CHECK_ACTION_YML = ROOT / ".github" / "actions" / "cbi-check" / "action.yml"


def test_action_yml_definitions_match():
    """Verify action.yml at repo root matches .github/actions/cbi-check/action.yml."""
    assert ACTION_YML.is_file(), "action.yml missing at repository root"
    assert CBI_CHECK_ACTION_YML.is_file(), "action.yml missing in .github/actions/cbi-check"
    assert (
        ACTION_YML.read_text(encoding="utf-8")
        == CBI_CHECK_ACTION_YML.read_text(encoding="utf-8")
    ), "action.yml and .github/actions/cbi-check/action.yml are out of sync"


def extract_step_resolution(action_path: Path, step_id: str) -> str:
    """Extract bash resolution lines from a specific step in action.yml."""
    lines = action_path.read_text(encoding="utf-8").splitlines()
    capturing = False
    in_run_block = False
    script_lines = []
    for line in lines:
        if f"id: {step_id}" in line:
            capturing = True
            continue
        if capturing:
            if not in_run_block:
                if line.strip().startswith("run: |"):
                    in_run_block = True
                continue
            if line.strip().startswith("- name:"):
                break
            if line.strip().startswith("echo \"Running cbi check") or line.strip().startswith(
                "echo \"Generating architectural review"
            ):
                break
            if line.startswith("        "):
                script_lines.append(line[8:])
            elif line.startswith("      "):
                script_lines.append(line[6:])
            else:
                script_lines.append(line)
    return "\n".join(script_lines)


def run_action_script(
    repo_dir: Path, script: str, input_base_ref: str = "main"
) -> subprocess.CompletedProcess:
    """Run extracted action script in a git repo with substituted template input."""
    substituted = script.replace("${{ inputs.base-ref }}", input_base_ref)
    full_script = (
        f"set -e\n"
        f"{substituted}\n"
        f"echo \"OUTPUT_RESOLVED_BASE_REF=$RESOLVED_BASE_REF\"\n"
    )
    return run_command(
        ["bash", "-c", full_script],
        cwd=repo_dir,
        capture_output=True,
        text=True,
    )


def _init_git_repo(repo_dir: Path) -> Path:
    repo_dir.mkdir(parents=True, exist_ok=True)
    run_command(["git", "init", "-b", "main"], cwd=repo_dir, check=True, capture_output=True)
    run_command(["git", "config", "user.name", "Tester"], cwd=repo_dir, check=True)
    run_command(["git", "config", "user.email", "test@example.com"], cwd=repo_dir, check=True)
    return repo_dir


def test_check_step_resolution_push_event_identical_sha(tmp_path):
    """When pushing to main, BASE_REF resolves to HEAD; fallback to HEAD~1 with log message."""
    repo = _init_git_repo(tmp_path / "push_repo")
    (repo / "file.txt").write_text("v1\n")
    run_command(["git", "add", "."], cwd=repo, check=True)
    run_command(["git", "commit", "-m", "initial commit"], cwd=repo, check=True)

    (repo / "file.txt").write_text("v2\n")
    run_command(["git", "add", "."], cwd=repo, check=True)
    run_command(["git", "commit", "-m", "second commit"], cwd=repo, check=True)

    head_sha = run_command(
        ["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True, check=True
    ).stdout.strip()

    script = extract_step_resolution(CBI_CHECK_ACTION_YML, "check-step")
    res = run_action_script(repo, script, input_base_ref="main")

    assert res.returncode == 0, f"Script failed: {res.stderr}\n{res.stdout}"
    assert "OUTPUT_RESOLVED_BASE_REF=HEAD~1" in res.stdout
    assert (
        f"Base ref 'main' matches HEAD ({head_sha}); falling back to parent commit 'HEAD~1' for push event verification."
        in res.stdout
    )


def test_check_step_resolution_default_empty_input(tmp_path):
    """When inputs.base-ref is empty, it defaults to main and falls back to HEAD~1 on push."""
    repo = _init_git_repo(tmp_path / "empty_input_repo")
    (repo / "file.txt").write_text("v1\n")
    run_command(["git", "add", "."], cwd=repo, check=True)
    run_command(["git", "commit", "-m", "initial commit"], cwd=repo, check=True)

    (repo / "file.txt").write_text("v2\n")
    run_command(["git", "add", "."], cwd=repo, check=True)
    run_command(["git", "commit", "-m", "second commit"], cwd=repo, check=True)

    head_sha = run_command(
        ["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True, check=True
    ).stdout.strip()

    script = extract_step_resolution(CBI_CHECK_ACTION_YML, "check-step")
    res = run_action_script(repo, script, input_base_ref="")

    assert res.returncode == 0, f"Script failed: {res.stderr}\n{res.stdout}"
    assert "OUTPUT_RESOLVED_BASE_REF=HEAD~1" in res.stdout
    assert (
        f"Base ref 'main' matches HEAD ({head_sha}); falling back to parent commit 'HEAD~1' for push event verification."
        in res.stdout
    )


def test_check_step_resolution_pr_event_different_branch(tmp_path):
    """For PR events, HEAD differs from BASE_REF, so RESOLVED_BASE_REF remains main."""
    repo = _init_git_repo(tmp_path / "pr_repo")
    (repo / "file.txt").write_text("v1\n")
    run_command(["git", "add", "."], cwd=repo, check=True)
    run_command(["git", "commit", "-m", "main commit"], cwd=repo, check=True)

    run_command(["git", "checkout", "-b", "feat/my-change"], cwd=repo, check=True)
    (repo / "file.txt").write_text("v2-feature\n")
    run_command(["git", "add", "."], cwd=repo, check=True)
    run_command(["git", "commit", "-m", "feature commit"], cwd=repo, check=True)

    script = extract_step_resolution(CBI_CHECK_ACTION_YML, "check-step")
    res = run_action_script(repo, script, input_base_ref="main")

    assert res.returncode == 0, f"Script failed: {res.stderr}\n{res.stdout}"
    assert "OUTPUT_RESOLVED_BASE_REF=main" in res.stdout
    assert "falling back to parent commit 'HEAD~1'" not in res.stdout


def test_check_step_resolution_root_commit_graceful(tmp_path):
    """When HEAD is the root commit (no parent HEAD~1), the action handles it gracefully."""
    repo = _init_git_repo(tmp_path / "root_commit_repo")
    (repo / "file.txt").write_text("root\n")
    run_command(["git", "add", "."], cwd=repo, check=True)
    run_command(["git", "commit", "-m", "initial root commit"], cwd=repo, check=True)

    head_sha = run_command(
        ["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True, check=True
    ).stdout.strip()

    script = extract_step_resolution(CBI_CHECK_ACTION_YML, "check-step")
    res = run_action_script(repo, script, input_base_ref="main")

    assert res.returncode == 0, f"Script failed on root commit: {res.stderr}\n{res.stdout}"
    assert "OUTPUT_RESOLVED_BASE_REF=main" in res.stdout
    assert (
        f"Notice: Base ref 'main' matches HEAD ({head_sha}) and HEAD has no parent commit (root commit). Evaluating root commit."
        in res.stdout
    )


def test_check_step_resolution_shallow_checkout_fails(tmp_path):
    """If repository checkout is shallow on push event, fail with helpful fetch-depth advice."""
    origin = _init_git_repo(tmp_path / "origin_repo")
    (origin / "file.txt").write_text("v1\n")
    run_command(["git", "add", "."], cwd=origin, check=True)
    run_command(["git", "commit", "-m", "c1"], cwd=origin, check=True)
    (origin / "file.txt").write_text("v2\n")
    run_command(["git", "add", "."], cwd=origin, check=True)
    run_command(["git", "commit", "-m", "c2"], cwd=origin, check=True)

    clone_dir = tmp_path / "shallow_clone"
    run_command(
        ["git", "clone", "--depth", "1", f"file://{origin}", str(clone_dir)],
        check=True,
        capture_output=True,
    )

    script = extract_step_resolution(CBI_CHECK_ACTION_YML, "check-step")
    res = run_action_script(clone_dir, script, input_base_ref="main")

    assert res.returncode != 0, f"Expected non-zero exit for shallow repo, got 0:\n{res.stdout}"
    assert "fetch-depth: 0" in res.stdout
    assert "repository checkout is shallow" in res.stdout


def test_review_step_resolution_push_event(tmp_path):
    """Review step falls back to HEAD~1 when BASE_REF matches HEAD."""
    repo = _init_git_repo(tmp_path / "review_push_repo")
    (repo / "file.txt").write_text("v1\n")
    run_command(["git", "add", "."], cwd=repo, check=True)
    run_command(["git", "commit", "-m", "c1"], cwd=repo, check=True)
    (repo / "file.txt").write_text("v2\n")
    run_command(["git", "add", "."], cwd=repo, check=True)
    run_command(["git", "commit", "-m", "c2"], cwd=repo, check=True)

    head_sha = run_command(
        ["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True, check=True
    ).stdout.strip()

    script = extract_step_resolution(CBI_CHECK_ACTION_YML, "review-step")
    res = run_action_script(repo, script, input_base_ref="main")

    assert res.returncode == 0, f"Script failed: {res.stderr}\n{res.stdout}"
    assert "OUTPUT_RESOLVED_BASE_REF=HEAD~1" in res.stdout
    assert (
        f"Base ref 'main' matches HEAD ({head_sha}); falling back to parent commit 'HEAD~1' for push event verification."
        in res.stdout
    )


def test_review_step_resolution_root_commit(tmp_path):
    """Review step handles root commit gracefully when BASE_REF matches HEAD."""
    repo = _init_git_repo(tmp_path / "review_root_repo")
    (repo / "file.txt").write_text("root\n")
    run_command(["git", "add", "."], cwd=repo, check=True)
    run_command(["git", "commit", "-m", "initial root commit"], cwd=repo, check=True)

    head_sha = run_command(
        ["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True, check=True
    ).stdout.strip()

    script = extract_step_resolution(CBI_CHECK_ACTION_YML, "review-step")
    res = run_action_script(repo, script, input_base_ref="main")

    assert res.returncode == 0, f"Script failed: {res.stderr}\n{res.stdout}"
    assert "OUTPUT_RESOLVED_BASE_REF=main" in res.stdout
    assert (
        f"Notice: Base ref 'main' matches HEAD ({head_sha}) and HEAD has no parent commit (root commit)."
        in res.stdout
    )


def test_review_step_resolution_pr_event(tmp_path):
    """Review step preserves base ref on PR events where HEAD differs from BASE_REF."""
    repo = _init_git_repo(tmp_path / "review_pr_repo")
    (repo / "file.txt").write_text("v1\n")
    run_command(["git", "add", "."], cwd=repo, check=True)
    run_command(["git", "commit", "-m", "c1"], cwd=repo, check=True)
    run_command(["git", "checkout", "-b", "feat/my-branch"], cwd=repo, check=True)
    (repo / "file.txt").write_text("v2\n")
    run_command(["git", "add", "."], cwd=repo, check=True)
    run_command(["git", "commit", "-m", "c2"], cwd=repo, check=True)

    script = extract_step_resolution(CBI_CHECK_ACTION_YML, "review-step")
    res = run_action_script(repo, script, input_base_ref="main")

    assert res.returncode == 0, f"Script failed: {res.stderr}\n{res.stdout}"
    assert "OUTPUT_RESOLVED_BASE_REF=main" in res.stdout
    assert "falling back to parent commit 'HEAD~1'" not in res.stdout


def extract_action_inputs(action_path: Path) -> dict[str, dict[str, str]]:
    """Parse inputs section from action.yml into a dictionary."""
    lines = action_path.read_text(encoding="utf-8").splitlines()
    inputs = {}
    in_inputs = False
    current_input = None
    for line in lines:
        if line.strip() == "inputs:":
            in_inputs = True
            continue
        if in_inputs:
            if line and not line.startswith(" ") and not line.startswith("\t"):
                break
            if line.startswith("  ") and not line.startswith("    ") and line.strip().endswith(":"):
                current_input = line.strip()[:-1]
                inputs[current_input] = {}
            elif current_input and line.startswith("    ") and ":" in line:
                key, val = line.strip().split(":", 1)
                val = val.strip().strip('"').strip("'")
                inputs[current_input][key] = val
    return inputs


def extract_step_definition(action_path: Path, step_id: str) -> dict[str, str]:
    """Extract step metadata and full run script for a step by step_id."""
    lines = action_path.read_text(encoding="utf-8").splitlines()
    step_info = {"id": step_id, "run": ""}
    capturing = False
    in_run_block = False
    script_lines = []

    for i, line in enumerate(lines):
        if f"id: {step_id}" in line:
            capturing = True
            for back in range(max(0, i - 4), i):
                prev = lines[back].strip()
                if prev.startswith("- name:"):
                    step_info["name"] = prev.split(":", 1)[1].strip().strip('"').strip("'")
                elif prev.startswith("if:"):
                    step_info["if"] = prev.split(":", 1)[1].strip()
            continue

        if capturing:
            stripped = line.strip()
            if not in_run_block:
                if stripped.startswith("if:"):
                    step_info["if"] = stripped.split(":", 1)[1].strip()
                elif stripped.startswith("shell:"):
                    step_info["shell"] = stripped.split(":", 1)[1].strip()
                elif stripped.startswith("run: |"):
                    in_run_block = True
                continue

            if stripped.startswith("- name:"):
                break
            if line.startswith("        "):
                script_lines.append(line[8:])
            elif line.startswith("      "):
                script_lines.append(line[6:])
            else:
                script_lines.append(line)

    step_info["run"] = "\n".join(script_lines)
    return step_info


def test_action_verification_inputs_contract():
    """Verify fail-on-cycles, fail-on-orphans, forbid, and level inputs are defined."""
    for path in (ACTION_YML, CBI_CHECK_ACTION_YML):
        inputs = extract_action_inputs(path)
        assert "fail-on-cycles" in inputs
        assert inputs["fail-on-cycles"]["default"] == "false"
        assert inputs["fail-on-cycles"]["required"] == "false"
        assert "circular dependencies" in inputs["fail-on-cycles"]["description"].lower()

        assert "fail-on-orphans" in inputs
        assert inputs["fail-on-orphans"]["default"] == "false"
        assert inputs["fail-on-orphans"]["required"] == "false"
        assert "unreferenced production code" in inputs["fail-on-orphans"]["description"].lower()

        assert "forbid" in inputs
        assert inputs["forbid"]["default"] == ""
        assert inputs["forbid"]["required"] == "false"
        assert "forbidden dependency rules" in inputs["forbid"]["description"].lower()

        assert "level" in inputs
        assert inputs["level"]["default"] == "package"
        assert inputs["level"]["required"] == "false"
        assert "container level" in inputs["level"]["description"].lower()


def test_action_verification_steps_contract():
    """Verify cycles, orphans, and forbid steps exist with expected conditions and commands."""
    for path in (ACTION_YML, CBI_CHECK_ACTION_YML):
        cycles = extract_step_definition(path, "cycles-step")
        assert cycles.get("if") == "inputs.fail-on-cycles == 'true'"
        assert "cbi cycles --fail" in cycles["run"]

        orphans = extract_step_definition(path, "orphans-step")
        assert orphans.get("if") == "inputs.fail-on-orphans == 'true'"
        assert "cbi orphans --fail" in orphans["run"]

        forbid = extract_step_definition(path, "forbid-step")
        assert forbid.get("if") == "inputs.forbid != ''"
        assert "cbi deps --level" in forbid["run"]


def test_forbid_step_script_execution(tmp_path):
    """Verify forbid-step bash script parses single, newline, and comma-separated rules."""
    step = extract_step_definition(CBI_CHECK_ACTION_YML, "forbid-step")
    raw_script = step["run"]

    # Create a mock bin dir with mock 'cbi' recording its arguments
    bin_dir = tmp_path / "mock_bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    cbi_mock = bin_dir / "cbi"
    cbi_log = tmp_path / "cbi_log.txt"
    cbi_mock.write_text(f"""#!/bin/bash
echo "$@" >> "{cbi_log}"
exit 0
""")
    cbi_mock.chmod(0o755)

    env = dict(os.environ)
    env["PATH"] = f"{bin_dir}:{env.get('PATH', '')}"

    def run_forbid_script(forbid_val: str, level_val: str = "package") -> subprocess.CompletedProcess:
        cbi_log.unlink(missing_ok=True)
        substituted = raw_script.replace("${{ inputs.forbid }}", forbid_val)
        substituted = substituted.replace("${{ inputs.level }}", level_val)
        full_script = f"set -e\n{substituted}\n"
        return run_command(
            ["bash", "-c", full_script],
            cwd=tmp_path,
            capture_output=True,
            text=True,
            env=env,
        )

    # 1. Single rule
    res1 = run_forbid_script("codebase-inspector:codebase-inspector-app", "package")
    assert res1.returncode == 0
    assert cbi_log.is_file()
    assert (
        cbi_log.read_text().strip()
        == "deps --level package --forbid codebase-inspector:codebase-inspector-app"
    )

    # 2. Comma-separated rules
    res2 = run_forbid_script("pkgA:pkgB, pkgC->pkgD", "package")
    assert res2.returncode == 0
    assert (
        cbi_log.read_text().strip()
        == "deps --level package --forbid pkgA:pkgB --forbid pkgC->pkgD"
    )

    # 3. Newline-separated rules with custom level
    newline_rules = "pkg1:pkg2\n  pkg3->pkg4\n"
    res3 = run_forbid_script(newline_rules, "folder")
    assert res3.returncode == 0
    assert (
        cbi_log.read_text().strip()
        == "deps --level folder --forbid pkg1:pkg2 --forbid pkg3->pkg4"
    )

    # 4. Empty rules (should not invoke cbi deps)
    res4 = run_forbid_script("", "package")
    assert res4.returncode == 0
    assert not cbi_log.is_file()


def test_cycles_and_orphans_step_script_execution(tmp_path):
    """Verify cycles-step and orphans-step scripts execute cbi with --fail."""
    cycles_step = extract_step_definition(CBI_CHECK_ACTION_YML, "cycles-step")
    orphans_step = extract_step_definition(CBI_CHECK_ACTION_YML, "orphans-step")

    bin_dir = tmp_path / "mock_bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    cbi_mock = bin_dir / "cbi"
    cbi_log = tmp_path / "cbi_log.txt"
    cbi_mock.write_text(f"""#!/bin/bash
echo "$@" >> "{cbi_log}"
exit 0
""")
    cbi_mock.chmod(0o755)

    env = dict(os.environ)
    env["PATH"] = f"{bin_dir}:{env.get('PATH', '')}"

    # Cycles
    cbi_log.unlink(missing_ok=True)
    res_cycles = run_command(
        ["bash", "-c", f"set -e\n{cycles_step['run']}\n"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        env=env,
    )
    assert res_cycles.returncode == 0
    assert cbi_log.is_file()
    assert cbi_log.read_text().strip() == "cycles --fail"

    # Orphans
    cbi_log.unlink(missing_ok=True)
    res_orphans = run_command(
        ["bash", "-c", f"set -e\n{orphans_step['run']}\n"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        env=env,
    )
    assert res_orphans.returncode == 0
    assert cbi_log.is_file()
    assert cbi_log.read_text().strip() == "orphans --fail"

