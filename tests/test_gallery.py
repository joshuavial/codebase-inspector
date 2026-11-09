"""Tests for CLI review gallery generator."""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

import pytest
import cbi.cli as cli
from cbi.gallery import (
    generate_gallery,
    load_gallery_config,
    main as gallery_main,
    parse_repo_spec,
    render_markdown_to_html,
)
import generate_gallery as legacy_generate_gallery


def _git(root, *args):
    import subprocess
    cmd = ["git", "-C", str(root)] + list(args)
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        raise RuntimeError(f"git command failed: {' '.join(cmd)}\n{res.stderr}")
    return res.stdout.strip()


def test_parse_repo_spec():
    # Simple path
    p1 = parse_repo_spec("/tmp/my-repo")
    assert p1["name"] == "my-repo"
    assert p1["path"] == Path("/tmp/my-repo").resolve()
    assert p1["compare"] is None

    # Named path
    p2 = parse_repo_spec("fastapi=/tmp/fastapi")
    assert p2["name"] == "fastapi"
    assert p2["path"] == Path("/tmp/fastapi").resolve()
    assert p2["compare"] is None

    # Named path with compare range
    p3 = parse_repo_spec("httpx=/tmp/httpx:0.24.0..0.25.0")
    assert p3["name"] == "httpx"
    assert p3["path"] == Path("/tmp/httpx").resolve()
    assert p3["compare"] == "0.24.0..0.25.0"

    # Path with compare range without custom name
    p4 = parse_repo_spec("/tmp/codebase:HEAD~1..HEAD")
    assert p4["name"] == "codebase"
    assert p4["path"] == Path("/tmp/codebase").resolve()
    assert p4["compare"] == "HEAD~1..HEAD"


def test_load_gallery_config(tmp_path):
    config_file = tmp_path / "gallery.json"
    dummy_repo = tmp_path / "sample_repo"
    dummy_repo.mkdir()

    config_data = {
        "title": "Custom Architecture Gallery",
        "description": "Showcase of high-performance libraries",
        "repos": [
            {
                "name": "sample",
                "path": str(dummy_repo),
                "compare": "v1.0..v2.0",
                "description": "A sample repository",
                "tags": ["Python", "Async"],
            },
            str(dummy_repo),
        ],
    }
    config_file.write_text(json.dumps(config_data), encoding="utf-8")

    cfg = load_gallery_config(config_file)
    assert cfg["title"] == "Custom Architecture Gallery"
    assert cfg["description"] == "Showcase of high-performance libraries"
    assert len(cfg["repos"]) == 2
    assert cfg["repos"][0]["name"] == "sample"
    assert cfg["repos"][0]["compare"] == "v1.0..v2.0"
    assert cfg["repos"][0]["tags"] == ["Python", "Async"]


def test_render_markdown_to_html():
    sample_md = """# Title

## Change overview

1 file  +4 -3  symbols 3 changed

- symbol-changed: `pkg/client.py#Client`
- **important**: architecture verified

```mermaid
flowchart LR
  a --> b
```
"""
    html = render_markdown_to_html(sample_md)
    assert "<h1>Title</h1>" in html
    assert "<h2>Change overview</h2>" in html
    assert "<li>symbol-changed: <code>pkg/client.py#Client</code></li>" in html
    assert "<strong>important</strong>" in html
    assert '<pre class="language-mermaid"><code>flowchart LR\n  a --&gt; b</code></pre>' in html


def test_generate_gallery_end_to_end(make_repo, tmp_path):
    # 1. Create synthetic fixture repo with 2 commits
    base_files = {
        "src/__init__.py": "",
        "src/calc.py": (
            "def add(a, b):\n"
            "    '''Add numbers.'''\n"
            "    return a + b\n"
        ),
        "tests/__init__.py": "",
        "tests/test_calc.py": (
            "from src.calc import add\n"
            "def test_add():\n"
            "    assert add(1, 2) == 3\n"
        ),
    }
    repo_root = make_repo(base_files, name="synth-repo")
    base_sha = _git(repo_root, "rev-parse", "HEAD")

    # Second commit with architectural change
    calc_path = repo_root / "src" / "calc.py"
    calc_path.write_text(
        "def add(a, b, c=0):\n"
        "    '''Add three numbers.'''\n"
        "    return a + b + c\n",
        encoding="utf-8",
    )
    _git(repo_root, "add", "src/calc.py")
    _git(repo_root, "-c", "user.name=test", "-c", "user.email=test@test.local", "commit", "-q", "-m", "update add signature")
    head_sha = _git(repo_root, "rev-parse", "HEAD")

    out_gallery = tmp_path / "dist_gallery"

    repos_config = [
        {
            "name": "synth-repo",
            "path": repo_root,
            "compare": f"{base_sha}..{head_sha}",
            "description": "Synthetic testing repository for gallery generation",
            "tags": ["Python", "Math"],
        }
    ]

    res = generate_gallery(repos_config, out_gallery, title="Test Gallery")

    assert res["gallery_dir"] == out_gallery
    assert out_gallery.is_dir()

    # 2. Check main gallery index
    index_html = out_gallery / "index.html"
    assert index_html.is_file()
    index_content = index_html.read_text(encoding="utf-8")
    assert "Test Gallery" in index_content
    assert "synth-repo" in index_content
    assert "Python" in index_content
    assert "Math" in index_content
    assert "./repos/synth-repo/viewer/index.html" in index_content
    assert "./repos/synth-repo/review/index.html" in index_content
    assert "0 SCCs (Clean)" in index_content

    # 3. Check viewer directory
    viewer_index = out_gallery / "repos" / "synth-repo" / "viewer" / "index.html"
    assert viewer_index.is_file()
    assert (out_gallery / "repos" / "synth-repo" / "viewer" / "app.js").is_file()
    assert (out_gallery / "repos" / "synth-repo" / "viewer" / "data" / "tree.js").is_file()

    # 4. Check review directory
    review_index = out_gallery / "repos" / "synth-repo" / "review" / "index.html"
    assert review_index.is_file()
    review_content = review_index.read_text(encoding="utf-8")
    assert "Architecture Review: synth-repo" in review_content
    assert "Back to Architecture Gallery" in review_content
    assert "Explore Concept Map" in review_content
    assert f"{base_sha}..{head_sha}" in review_content
    assert (out_gallery / "repos" / "synth-repo" / "review" / "review.md").is_file()


def test_generate_gallery_without_review(make_repo, tmp_path):
    repo_root = make_repo({"src/app.py": "def run(): return 42\n"}, name="single-commit")

    out_gallery = tmp_path / "dist_no_review"
    repos_config = [
        {
            "name": "single-commit",
            "path": repo_root,
            "compare": None,
            "description": "Repo without review comparison",
            "tags": ["Standalone"],
        }
    ]

    res = generate_gallery(repos_config, out_gallery)
    assert res["index_path"].is_file()
    content = res["index_path"].read_text(encoding="utf-8")
    assert "single-commit" in content
    assert "./repos/single-commit/viewer/index.html" in content
    # Should not have link to PR review
    assert "./repos/single-commit/review/index.html" not in content


def test_main_cli_execution(make_repo, tmp_path, monkeypatch):
    repo_root = make_repo({"src/app.py": "def main(): pass\n"}, name="cli-repo")
    out_gallery = tmp_path / "cli_gallery"

    # Test programmatic main in cbi.gallery
    rc = gallery_main([
        "--repo", f"cli-repo={repo_root}",
        "--out", str(out_gallery),
        "--title", "CLI Generated Gallery",
    ])
    assert rc == 0
    assert (out_gallery / "index.html").is_file()
    assert "CLI Generated Gallery" in (out_gallery / "index.html").read_text(encoding="utf-8")

    # Test legacy entrypoint wrapper delegation
    out_legacy = tmp_path / "legacy_gallery"
    rc_legacy = legacy_generate_gallery.main([
        "--repo", f"cli-repo={repo_root}",
        "--out", str(out_legacy),
        "--title", "Legacy Script Gallery",
    ])
    assert rc_legacy == 0
    assert (out_legacy / "index.html").is_file()
    assert "Legacy Script Gallery" in (out_legacy / "index.html").read_text(encoding="utf-8")


def test_cbi_gallery_cli_subcommand(make_repo, tmp_path):
    repo_root = make_repo({"src/app.py": "def main(): pass\n"}, name="cbi-repo")
    out_gallery = tmp_path / "cbi_gallery_subcmd"

    # Positional repo specification with --out-dir
    rc = cli.main([
        "gallery",
        f"cbi-repo={repo_root}",
        "--out-dir", str(out_gallery),
        "--title", "CBI Gallery Subcommand Showcase",
    ])
    assert rc == 0
    assert (out_gallery / "index.html").is_file()
    assert "CBI Gallery Subcommand Showcase" in (out_gallery / "index.html").read_text(encoding="utf-8")


def test_cbi_gallery_cli_with_repo_flag_and_config(make_repo, tmp_path):
    repo_root = make_repo({"src/app.py": "def main(): pass\n"}, name="flag-repo")
    out_gallery = tmp_path / "cbi_gallery_flags"

    # Using --repo flag and --out
    rc = cli.main([
        "gallery",
        "--repo", f"flag-repo={repo_root}",
        "--out", str(out_gallery),
        "--title", "Flag Generated Gallery",
    ])
    assert rc == 0
    assert (out_gallery / "index.html").is_file()
    assert "Flag Generated Gallery" in (out_gallery / "index.html").read_text(encoding="utf-8")

    # Using --config
    config_file = tmp_path / "gallery.json"
    config_file.write_text(json.dumps({
        "title": "Configured Gallery",
        "repos": [str(repo_root)],
    }), encoding="utf-8")
    out_cfg_gallery = tmp_path / "cbi_gallery_cfg"
    rc = cli.main([
        "gallery",
        "--config", str(config_file),
        "--out-dir", str(out_cfg_gallery),
    ])
    assert rc == 0
    assert (out_cfg_gallery / "index.html").is_file()
    assert "Configured Gallery" in (out_cfg_gallery / "index.html").read_text(encoding="utf-8")


def test_legacy_script_wrapper_exports():
    assert legacy_generate_gallery.generate_gallery is generate_gallery
    assert legacy_generate_gallery.load_gallery_config is load_gallery_config
    assert legacy_generate_gallery.parse_repo_spec is parse_repo_spec
    assert legacy_generate_gallery.render_markdown_to_html is render_markdown_to_html
