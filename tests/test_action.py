"""Tests for GitHub Action composite contract and base-ref resolution (cbi-ekw)."""

import os
import subprocess
from pathlib import Path

import pytest

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
    return subprocess.run(
        ["bash", "-c", full_script],
        cwd=repo_dir,
        capture_output=True,
        text=True,
    )


def _init_git_repo(repo_dir: Path) -> Path:
    repo_dir.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-b", "main"], cwd=repo_dir, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Tester"], cwd=repo_dir, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo_dir, check=True)
    return repo_dir


def test_check_step_resolution_push_event_identical_sha(tmp_path):
    """When pushing to main, BASE_REF resolves to HEAD; fallback to HEAD~1 with log message."""
    repo = _init_git_repo(tmp_path / "push_repo")
    (repo / "file.txt").write_text("v1\n")
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "initial commit"], cwd=repo, check=True)

    (repo / "file.txt").write_text("v2\n")
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "second commit"], cwd=repo, check=True)

    head_sha = subprocess.run(
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
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "initial commit"], cwd=repo, check=True)

    (repo / "file.txt").write_text("v2\n")
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "second commit"], cwd=repo, check=True)

    head_sha = subprocess.run(
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
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "main commit"], cwd=repo, check=True)

    subprocess.run(["git", "checkout", "-b", "feat/my-change"], cwd=repo, check=True)
    (repo / "file.txt").write_text("v2-feature\n")
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "feature commit"], cwd=repo, check=True)

    script = extract_step_resolution(CBI_CHECK_ACTION_YML, "check-step")
    res = run_action_script(repo, script, input_base_ref="main")

    assert res.returncode == 0, f"Script failed: {res.stderr}\n{res.stdout}"
    assert "OUTPUT_RESOLVED_BASE_REF=main" in res.stdout
    assert "falling back to parent commit 'HEAD~1'" not in res.stdout


def test_check_step_resolution_root_commit_graceful(tmp_path):
    """When HEAD is the root commit (no parent HEAD~1), the action handles it gracefully."""
    repo = _init_git_repo(tmp_path / "root_commit_repo")
    (repo / "file.txt").write_text("root\n")
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "initial root commit"], cwd=repo, check=True)

    head_sha = subprocess.run(
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
    subprocess.run(["git", "add", "."], cwd=origin, check=True)
    subprocess.run(["git", "commit", "-m", "c1"], cwd=origin, check=True)
    (origin / "file.txt").write_text("v2\n")
    subprocess.run(["git", "add", "."], cwd=origin, check=True)
    subprocess.run(["git", "commit", "-m", "c2"], cwd=origin, check=True)

    clone_dir = tmp_path / "shallow_clone"
    subprocess.run(
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
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "c1"], cwd=repo, check=True)
    (repo / "file.txt").write_text("v2\n")
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "c2"], cwd=repo, check=True)

    head_sha = subprocess.run(
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
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "initial root commit"], cwd=repo, check=True)

    head_sha = subprocess.run(
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
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "c1"], cwd=repo, check=True)
    subprocess.run(["git", "checkout", "-b", "feat/my-branch"], cwd=repo, check=True)
    (repo / "file.txt").write_text("v2\n")
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "c2"], cwd=repo, check=True)

    script = extract_step_resolution(CBI_CHECK_ACTION_YML, "review-step")
    res = run_action_script(repo, script, input_base_ref="main")

    assert res.returncode == 0, f"Script failed: {res.stderr}\n{res.stdout}"
    assert "OUTPUT_RESOLVED_BASE_REF=main" in res.stdout
    assert "falling back to parent commit 'HEAD~1'" not in res.stdout
