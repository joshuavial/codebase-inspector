"""Tests for the unified local smoke verification harness."""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

import pytest
from smoke_all import (
    build_synthetic_fixture,
    main,
    run_all_smoke_checks,
    smoke_composite_action_simulation,
    smoke_core_cli,
    smoke_gallery_generator,
    smoke_mcp_server,
)


def test_build_synthetic_fixture(tmp_path):
    repo_dir, base_sha, head_sha = build_synthetic_fixture(tmp_path / "fixture_repo")

    assert repo_dir.is_dir()
    assert (repo_dir / ".git").is_dir()
    assert (repo_dir / "src" / "calc.py").is_file()
    assert (repo_dir / "tests" / "test_calc.py").is_file()
    assert (repo_dir / ".cbi" / "concepts.json").is_file()
    assert len(base_sha) == 40
    assert len(head_sha) == 40
    assert base_sha != head_sha


def test_smoke_core_cli_workflow(tmp_path):
    repo_dir, base_sha, head_sha = build_synthetic_fixture(tmp_path / "cli_test_repo")
    results = smoke_core_cli(repo_dir, base_sha, head_sha)

    step_names = [r.name for r in results]
    assert "cli.init" in step_names
    assert "cli.scan" in step_names
    assert "cli.check" in step_names
    assert "cli.cycles" in step_names
    assert "cli.tests_for" in step_names
    assert "cli.diff" in step_names
    assert "cli.review" in step_names
    assert "cli.build" in step_names

    for r in results:
        assert r.passed, f"Step {r.name} failed: {r.error}"


def test_smoke_mcp_server_workflow(tmp_path):
    repo_dir, base_sha, head_sha = build_synthetic_fixture(tmp_path / "mcp_test_repo")
    # Initialize and scan first so model exists
    smoke_core_cli(repo_dir, base_sha, head_sha)

    mcp_results = smoke_mcp_server(repo_dir)
    assert len(mcp_results) >= 4
    step_names = [r.name for r in mcp_results]
    assert "mcp.initialize" in step_names
    assert "mcp.tools_list" in step_names
    assert "mcp.tools_call_context" in step_names
    assert "mcp.prompts_list" in step_names

    for r in mcp_results:
        assert r.passed, f"MCP step {r.name} failed: {r.error}"


def test_smoke_composite_action_simulation(tmp_path):
    repo_dir, base_sha, head_sha = build_synthetic_fixture(tmp_path / "action_test_repo")
    smoke_core_cli(repo_dir, base_sha, head_sha)

    action_results = smoke_composite_action_simulation(repo_dir, base_sha)
    step_names = [r.name for r in action_results]
    assert "action.spec_check" in step_names
    assert "action.step_scan" in step_names
    assert "action.step_check" in step_names
    assert "action.step_review" in step_names
    assert "action.outputs_contract" in step_names

    for r in action_results:
        assert r.passed, f"Action step {r.name} failed: {r.error}"


def test_smoke_gallery_generator_step(tmp_path):
    repo_dir, base_sha, head_sha = build_synthetic_fixture(tmp_path / "gallery_test_repo")
    smoke_core_cli(repo_dir, base_sha, head_sha)

    gallery_results = smoke_gallery_generator(repo_dir, base_sha, head_sha)
    assert len(gallery_results) == 1
    assert gallery_results[0].passed, f"Gallery step failed: {gallery_results[0].error}"


def test_smoke_cli_main_json_output(capsys):
    rc = main(["--json"])
    assert rc == 0
    captured = capsys.readouterr()
    report = json.loads(captured.out)
    assert report["success"] is True
    assert report["total_checks"] == 21
    assert report["failed_checks"] == 0
    assert report["passed_checks"] == 21
    assert "results" in report
    assert report["duration_ms"] > 0
