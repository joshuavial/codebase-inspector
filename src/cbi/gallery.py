#!/usr/bin/env python3
"""CLI Review Gallery Generator for Codebase Inspector.

Generates an offline, static multi-repository architecture showcase.
For each configured repository:
1. Builds the interactive concept map viewer (`repos/<name>/viewer/`).
2. Runs PR architecture review to produce structural diffs and Mermaid diagrams (`repos/<name>/review/`).
3. Extracts architecture vitals (files, symbols, test counts, cycle health).
4. Generates a responsive, dark-themed index page (`index.html`) with repository cards and direct navigation.

100% offline, uses relative paths suitable for static hosting and local exploration.
"""

import argparse
import html
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from cbi import build, diff, files, graph, render, review, store


def parse_repo_spec(spec_str: str) -> Dict[str, Any]:
    """Parse a repo specification string into a repo definition dict.

    Supported formats:
    - /path/to/repo
    - name=/path/to/repo
    - name=/path/to/repo:base..head
    - /path/to/repo:base..head
    """
    name: Optional[str] = None
    path_and_compare = spec_str

    if "=" in spec_str and not spec_str.startswith("="):
        first_eq = spec_str.index("=")
        # Ensure '=' is before any ':'
        first_colon = spec_str.find(":")
        if first_colon == -1 or first_eq < first_colon:
            name = spec_str[:first_eq].strip()
            path_and_compare = spec_str[first_eq + 1:].strip()

    compare: Optional[str] = None
    if ":" in path_and_compare:
        parts = path_and_compare.split(":", 1)
        repo_path_str = parts[0].strip()
        compare = parts[1].strip() or None
    else:
        repo_path_str = path_and_compare.strip()

    repo_path = Path(repo_path_str).resolve()
    if not name:
        name = repo_path.name

    return {
        "name": name,
        "path": repo_path,
        "compare": compare,
        "description": f"Repository {name}",
        "tags": [],
    }


def load_gallery_config(config_path: Path) -> Dict[str, Any]:
    """Load gallery configuration from a JSON file."""
    content = config_path.read_text(encoding="utf-8")
    data = json.loads(content)
    repos_raw = data.get("repos", [])
    parsed_repos = []
    base_dir = config_path.parent

    for item in repos_raw:
        if isinstance(item, str):
            parsed = parse_repo_spec(item)
            # resolve relative paths relative to config file
            if not parsed["path"].is_absolute():
                parsed["path"] = (base_dir / parsed["path"]).resolve()
            parsed_repos.append(parsed)
        elif isinstance(item, dict):
            repo_path = Path(item["path"])
            if not repo_path.is_absolute():
                repo_path = (base_dir / repo_path).resolve()
            parsed_repos.append({
                "name": item.get("name") or repo_path.name,
                "path": repo_path,
                "compare": item.get("compare"),
                "description": item.get("description", f"Repository {repo_path.name}"),
                "tags": item.get("tags", []),
            })

    return {
        "title": data.get("title", "Codebase Inspector Architecture Gallery"),
        "description": data.get(
            "description",
            "Deterministic architecture reviews and interactive concept maps for modern codebases.",
        ),
        "repos": parsed_repos,
    }


def run_cbi(args: List[str], cwd: Path) -> str:
    """Run CBI CLI command in a repository with current Python environment."""
    env = os.environ.copy()
    pkg_parent = str(Path(__file__).resolve().parents[1])
    if pkg_parent not in env.get("PYTHONPATH", ""):
        env["PYTHONPATH"] = pkg_parent + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    env["CBI_NO_UPDATE_CHECK"] = "1"

    cmd = [sys.executable, "-m", "cbi.cli"] + args
    res = subprocess.run(
        cmd,
        cwd=str(cwd),
        capture_output=True,
        text=True,
        env=env,
    )
    if res.returncode != 0:
        raise RuntimeError(
            f"cbi {' '.join(args)} failed in {cwd} (code {res.returncode}):\n{res.stderr}\n{res.stdout}"
        )
    return res.stdout


def ensure_repo_scanned(repo_path: Path) -> None:
    """Ensure repository has a valid .cbi/model.db database."""
    cbi_dir = repo_path / ".cbi"
    model_db = cbi_dir / "model.db"
    if not model_db.is_file():
        if not (cbi_dir / "ignore").is_file():
            run_cbi(["init"], repo_path)
        run_cbi(["scan"], repo_path)


def extract_repo_metrics(repo_path: Path) -> Dict[str, Any]:
    """Extract architectural statistics and cycle status from .cbi/model.db."""
    model_db = repo_path / ".cbi" / "model.db"
    if not model_db.is_file():
        ensure_repo_scanned(repo_path)

    conn = sqlite3.connect(f"file:{model_db}?mode=ro", uri=True)
    try:
        cur = conn.cursor()

        # Counts by display_kind
        cur.execute("SELECT display_kind, count(*) FROM nodes GROUP BY display_kind;")
        display_counts = dict(cur.fetchall())

        # Counts by general kind
        cur.execute("SELECT kind, count(*) FROM nodes GROUP BY kind;")
        kind_counts = dict(cur.fetchall())

        source_files = display_counts.get("source file", 0)
        test_files = display_counts.get("test file", 0)
        total_files = kind_counts.get("file", source_files + test_files)

        classes = display_counts.get("class", 0)
        functions = display_counts.get("function", 0)
        methods = display_counts.get("method", 0)
        test_cases = display_counts.get("test case", 0)

        deployables = kind_counts.get("deployable", 0)
        packages = kind_counts.get("package", 0)
        concepts = kind_counts.get("concept", 0)

        # Cycle detection
        cycles_data = graph.collect_cycles(conn)
        file_sccs = len(cycles_data.get("files", []))
        folder_sccs = len(cycles_data.get("folders", []))
        package_sccs = len(cycles_data.get("packages", []))
        total_sccs = file_sccs + folder_sccs + package_sccs

        return {
            "total_files": total_files,
            "source_files": source_files,
            "test_files": test_files,
            "classes": classes,
            "functions": functions,
            "methods": methods,
            "symbols_total": classes + functions + methods,
            "test_cases": test_cases,
            "deployables": deployables,
            "packages": packages,
            "concepts": concepts,
            "cycles_scc_count": total_sccs,
            "cycles_status": "0 SCCs (Clean)" if total_sccs == 0 else f"{total_sccs} SCCs",
        }
    finally:
        conn.close()


def build_repo_viewer(repo_path: Path, out_dir: Path) -> Path:
    """Build the static interactive concept map viewer into out_dir."""
    ensure_repo_scanned(repo_path)
    model_db = repo_path / ".cbi" / "model.db"
    conn = sqlite3.connect(f"file:{model_db}?mode=ro", uri=True)
    try:
        index_path = build.build(conn, out_dir, root=repo_path)
        return Path(index_path)
    finally:
        conn.close()


def extract_review_metadata(content: str) -> Dict[str, Any]:
    """Parse review.md to extract change summary, Mermaid diagram, and changed symbols."""
    lines = content.splitlines()

    change_summary = ""
    in_overview = False
    for line in lines:
        if line.startswith("## Change overview"):
            in_overview = True
            continue
        if in_overview:
            if "file" in line and "changed" in line:
                change_summary = line.strip()
                break
            if line.startswith("## "):
                break

    mermaid_lines = []
    in_mermaid = False
    for line in lines:
        if "```mermaid" in line:
            in_mermaid = True
            mermaid_lines.append(line)
            continue
        if in_mermaid:
            mermaid_lines.append(line)
            if line.startswith("```"):
                in_mermaid = False
                break

    changed_symbols = []
    for line in lines:
        if "symbol-changed" in line and "#" in line:
            parts = line.strip().split()
            syms = [p for p in parts if "#" in p]
            if syms and syms[0] not in changed_symbols:
                changed_symbols.append(syms[0])

    return {
        "change_summary": change_summary or "Architecture changes detected",
        "mermaid_raw": "\n".join(mermaid_lines),
        "changed_symbols": changed_symbols,
    }


def render_markdown_to_html(md_text: str) -> str:
    """Lightweight deterministic markdown to HTML renderer for review bodies."""
    lines = md_text.splitlines()
    html_lines = []
    in_code_block = False
    code_block_lang = ""
    code_lines = []
    in_list = False

    for line in lines:
        # Strip internal comments
        if line.strip().startswith("<!--") and line.strip().endswith("-->"):
            continue

        if line.startswith("```"):
            if in_code_block:
                in_code_block = False
                escaped = html.escape("\n".join(code_lines))
                cls = f"language-{code_block_lang}" if code_block_lang else ""
                html_lines.append(f'<pre class="{cls}"><code>{escaped}</code></pre>')
                code_lines = []
                code_block_lang = ""
            else:
                if in_list:
                    html_lines.append("</ul>")
                    in_list = False
                in_code_block = True
                code_block_lang = line.strip()[3:].strip()
            continue

        if in_code_block:
            code_lines.append(line)
            continue

        stripped = line.strip()
        if not stripped:
            if in_list:
                html_lines.append("</ul>")
                in_list = False
            continue

        # Headings
        if stripped.startswith("#### "):
            if in_list:
                html_lines.append("</ul>")
                in_list = False
            html_lines.append(f"<h4>{html.escape(stripped[5:])}</h4>")
        elif stripped.startswith("### "):
            if in_list:
                html_lines.append("</ul>")
                in_list = False
            html_lines.append(f"<h3>{html.escape(stripped[4:])}</h3>")
        elif stripped.startswith("## "):
            if in_list:
                html_lines.append("</ul>")
                in_list = False
            html_lines.append(f"<h2>{html.escape(stripped[3:])}</h2>")
        elif stripped.startswith("# "):
            if in_list:
                html_lines.append("</ul>")
                in_list = False
            html_lines.append(f"<h1>{html.escape(stripped[2:])}</h1>")
        elif stripped.startswith("- ") or stripped.startswith("* "):
            if not in_list:
                html_lines.append("<ul>")
                in_list = True
            content = html.escape(stripped[2:])
            # format bold and backticks
            content = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", content)
            content = re.sub(r"`([^`]+)`", r"<code>\1</code>", content)
            html_lines.append(f"<li>{content}</li>")
        else:
            if in_list:
                html_lines.append("</ul>")
                in_list = False
            content = html.escape(stripped)
            content = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", content)
            content = re.sub(r"`([^`]+)`", r"<code>\1</code>", content)
            html_lines.append(f"<p>{content}</p>")

    if in_list:
        html_lines.append("</ul>")
    if in_code_block:
        escaped = html.escape("\n".join(code_lines))
        html_lines.append(f"<pre><code>{escaped}</code></pre>")

    return "\n".join(html_lines)


def build_repo_review(repo_path: Path, compare_range: str, out_dir: Path, repo_name: str) -> Dict[str, Any]:
    """Execute cbi review and generate standalone dark-themed review HTML."""
    out_dir.mkdir(parents=True, exist_ok=True)
    ensure_repo_scanned(repo_path)

    # Execute review
    review.review(repo_path, compare_range, out_dir=out_dir)

    review_md_path = out_dir / "review.md"
    if not review_md_path.is_file():
        raise RuntimeError(f"Expected review.md at {review_md_path} was not created.")

    raw_md = review_md_path.read_text(encoding="utf-8")
    meta = extract_review_metadata(raw_md)

    # Check for generated SVGs
    has_after_svg = (out_dir / "after.svg").is_file()
    has_before_svg = (out_dir / "before.svg").is_file()

    rendered_body = render_markdown_to_html(raw_md)

    mermaid_code_clean = meta["mermaid_raw"].replace("```mermaid", "").replace("```", "").strip()

    review_html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Architecture PR Review — {html.escape(repo_name)} ({html.escape(compare_range)})</title>
  <style>
    :root {{
      --bg: #090b10;
      --card-bg: #12151e;
      --border: #232838;
      --text: #f3f4f6;
      --text-muted: #94a3b8;
      --accent-blue: #38bdf8;
      --accent-green: #10b981;
      --accent-amber: #f59e0b;
      --code-bg: #0f121a;
    }}
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{
      background: var(--bg);
      color: var(--text);
      font-family: ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
      line-height: 1.6;
      padding: 32px 20px;
    }}
    .container {{
      max-width: 980px;
      margin: 0 auto;
    }}
    .nav-bar {{
      display: flex;
      justify-content: space-between;
      align-items: center;
      margin-bottom: 28px;
      padding-bottom: 16px;
      border-bottom: 1px solid var(--border);
    }}
    .nav-link {{
      color: var(--accent-blue);
      text-decoration: none;
      font-weight: 500;
      font-size: 14px;
      display: inline-flex;
      align-items: center;
      gap: 6px;
    }}
    .nav-link:hover {{ text-decoration: underline; }}
    .header-card {{
      background: var(--card-bg);
      border: 1px solid var(--border);
      border-radius: 12px;
      padding: 24px;
      margin-bottom: 24px;
    }}
    .badge-bar {{
      display: flex;
      gap: 10px;
      flex-wrap: wrap;
      margin-top: 12px;
    }}
    .badge {{
      display: inline-block;
      padding: 4px 10px;
      border-radius: 6px;
      font-size: 12px;
      font-family: ui-monospace, monospace;
      font-weight: 600;
      background: #1e293b;
      color: var(--text);
    }}
    .badge.compare {{ background: #0284c7; color: #fff; }}
    .badge.summary {{ background: #065f46; color: #34d399; }}
    .card {{
      background: var(--card-bg);
      border: 1px solid var(--border);
      border-radius: 12px;
      padding: 24px;
      margin-bottom: 24px;
    }}
    h1 {{ font-size: 26px; font-weight: 700; color: #fff; }}
    h2 {{ font-size: 20px; font-weight: 600; margin: 24px 0 12px 0; color: #fff; border-bottom: 1px solid var(--border); padding-bottom: 6px; }}
    h3 {{ font-size: 16px; font-weight: 600; margin: 18px 0 8px 0; color: #e2e8f0; }}
    h4 {{ font-size: 14px; font-weight: 600; margin: 12px 0 6px 0; color: #cbd5e1; }}
    p {{ margin-bottom: 12px; color: #d1d5db; }}
    ul {{ margin: 8px 0 16px 20px; color: #d1d5db; }}
    li {{ margin-bottom: 4px; }}
    code {{
      font-family: ui-monospace, Menlo, Monaco, Consolas, monospace;
      font-size: 13px;
      background: var(--code-bg);
      padding: 2px 6px;
      border-radius: 4px;
      color: #38bdf8;
    }}
    pre {{
      background: var(--code-bg);
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 16px;
      overflow-x: auto;
      margin: 14px 0;
    }}
    pre code {{
      background: transparent;
      padding: 0;
      color: #e2e8f0;
      font-size: 13px;
    }}
    .diagram-panel {{
      margin: 20px 0;
      text-align: center;
    }}
    .diagram-svg {{
      max-width: 100%;
      height: auto;
      border-radius: 8px;
      background: #0f121a;
      border: 1px solid var(--border);
      padding: 12px;
    }}
    .mermaid-box {{
      background: var(--code-bg);
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 16px;
      position: relative;
    }}
    .mermaid-box-header {{
      display: flex;
      justify-content: space-between;
      align-items: center;
      margin-bottom: 8px;
      font-size: 12px;
      color: var(--text-muted);
      text-transform: uppercase;
      letter-spacing: 0.05em;
    }}
    .btn-action {{
      display: inline-flex;
      align-items: center;
      gap: 6px;
      background: #2563eb;
      color: #fff;
      padding: 8px 16px;
      border-radius: 6px;
      text-decoration: none;
      font-weight: 500;
      font-size: 14px;
    }}
    .btn-action:hover {{ background: #1d4ed8; }}
    footer {{
      margin-top: 40px;
      padding-top: 20px;
      border-top: 1px solid var(--border);
      font-size: 13px;
      color: var(--text-muted);
      text-align: center;
    }}
  </style>
  <script type="module">
    import mermaid from 'https://cdn.jsdelivr.net/npm/mermaid@10/dist/mermaid.esm.min.mjs';
    try {{
      mermaid.initialize({{ startOnLoad: true, theme: 'dark', securityLevel: 'loose' }});
    }} catch (e) {{
      // Offline fallback: raw pre block displayed
    }}
  </script>
</head>
<body>
  <div class="container">
    <nav class="nav-bar">
      <a href="../../index.html" class="nav-link">&larr; Back to Architecture Gallery</a>
      <a href="../viewer/index.html" class="nav-link">🗺️ Explore Concept Map &rarr;</a>
    </nav>

    <header class="header-card">
      <h1>Architecture Review: {html.escape(repo_name)}</h1>
      <div class="badge-bar">
        <span class="badge compare">{html.escape(compare_range)}</span>
        <span class="badge summary">{html.escape(meta["change_summary"])}</span>
      </div>
    </header>

    <main class="card">
      <h2>Architectural Change Visualisation</h2>
      <div class="mermaid-box">
        <div class="mermaid-box-header">
          <span>Mermaid Diagram (flowchart)</span>
        </div>
        <div class="mermaid">
{html.escape(mermaid_code_clean)}
        </div>
      </div>

      {"<div class='diagram-panel'><h3>Generated SVG Graph</h3><img src='after.svg' alt='Architecture graph' class='diagram-svg' /></div>" if has_after_svg else ""}

      <div style="margin-top: 32px;">
        {rendered_body}
      </div>
    </main>

    <div style="text-align: center; margin-top: 24px;">
      <a href="../viewer/index.html" class="btn-action">Explore Full Interactive Concept Map</a>
    </div>

    <footer>
      Generated deterministically by Codebase Inspector (cbi). 100% local, zero LLM tokens.
    </footer>
  </div>
</body>
</html>"""

    (out_dir / "index.html").write_text(review_html, encoding="utf-8")
    return {
        "change_summary": meta["change_summary"],
        "changed_symbols": meta["changed_symbols"],
        "has_review": True,
        "compare": compare_range,
        "review_path": out_dir / "index.html",
    }


def render_gallery_index(
    gallery_meta: Dict[str, Any],
    repos_data: List[Dict[str, Any]],
    out_dir: Path,
) -> Path:
    """Generate the root index.html landing page for the architecture gallery."""
    title = gallery_meta.get("title", "Codebase Inspector Architecture Gallery")
    description = gallery_meta.get(
        "description",
        "Deterministic architecture reviews and interactive concept maps for modern codebases.",
    )

    total_repos = len(repos_data)
    total_symbols = sum(r["metrics"]["symbols_total"] for r in repos_data)
    total_files = sum(r["metrics"]["total_files"] for r in repos_data)

    cards_html = []
    for repo in repos_data:
        name = html.escape(repo["name"])
        desc = html.escape(repo.get("description", ""))
        slug = repo["slug"]
        m = repo["metrics"]

        # Tag pills
        tags_markup = "".join(
            f'<span class="tag">{html.escape(t)}</span>' for t in repo.get("tags", [])
        )

        # Cycles badge
        cycles_clean = m["cycles_scc_count"] == 0
        cycles_cls = "badge-clean" if cycles_clean else "badge-warning"
        cycles_label = "0 SCCs (Clean)" if cycles_clean else f"{m['cycles_scc_count']} SCCs"

        # Review block
        review_data = repo.get("review")
        if review_data and review_data.get("has_review"):
            rev_badge = f'<span class="badge-pill pill-compare">{html.escape(review_data["compare"])}</span>'
            rev_summary = html.escape(review_data["change_summary"])
            rev_block = f"""
            <div class="review-preview">
              <div class="review-title">PR Architecture Review:</div>
              <div style="margin-top: 4px;">{rev_badge} <span class="review-summary-text">{rev_summary}</span></div>
            </div>
            """
            review_btn = f'<a href="./repos/{slug}/review/index.html" class="btn btn-secondary">📋 View PR Review</a>'
        else:
            rev_block = """
            <div class="review-preview review-empty">
              <span class="review-summary-text">No comparison range configured</span>
            </div>
            """
            review_btn = ""

        card = f"""
        <div class="repo-card">
          <div class="repo-card-header">
            <div>
              <h2 class="repo-name">{name}</h2>
              <p class="repo-desc">{desc}</p>
            </div>
            <div class="tags-wrapper">{tags_markup}</div>
          </div>

          <div class="stats-grid">
            <div class="stat-item">
              <div class="stat-label">Files</div>
              <div class="stat-val">{m['source_files']} <span class="stat-sub">src</span> / {m['test_files']} <span class="stat-sub">test</span></div>
            </div>
            <div class="stat-item">
              <div class="stat-label">Symbols</div>
              <div class="stat-val">{m['symbols_total']} <span class="stat-sub">nodes</span></div>
            </div>
            <div class="stat-item">
              <div class="stat-label">Tests</div>
              <div class="stat-val">{m['test_cases']} <span class="stat-sub">cases</span></div>
            </div>
            <div class="stat-item">
              <div class="stat-label">Cycle Health</div>
              <div class="stat-val"><span class="badge-cycle {cycles_cls}">{cycles_label}</span></div>
            </div>
          </div>

          {rev_block}

          <div class="card-actions">
            <a href="./repos/{slug}/viewer/index.html" class="btn btn-primary">🗺️ Explore Concept Map</a>
            {review_btn}
          </div>
        </div>
        """
        cards_html.append(card)

    cards_joined = "\n".join(cards_html)

    html_page = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{html.escape(title)}</title>
  <style>
    :root {{
      --bg: #0b0d14;
      --card-bg: #131722;
      --card-hover: #171d2b;
      --border: #232a3d;
      --border-light: #2e374f;
      --text: #f8fafc;
      --text-muted: #94a3b8;
      --accent-primary: #3b82f6;
      --accent-primary-hover: #2563eb;
      --accent-emerald: #10b981;
      --accent-amber: #f59e0b;
      --tag-bg: #1e293b;
    }}
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{
      background: var(--bg);
      color: var(--text);
      font-family: ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
      line-height: 1.5;
      padding: 48px 24px;
    }}
    .container {{
      max-width: 1160px;
      margin: 0 auto;
    }}
    header.hero {{
      text-align: center;
      margin-bottom: 48px;
    }}
    .brand-badge {{
      display: inline-flex;
      align-items: center;
      gap: 6px;
      background: #1e293b;
      color: #38bdf8;
      font-size: 13px;
      font-weight: 600;
      padding: 6px 14px;
      border-radius: 20px;
      border: 1px solid #334155;
      margin-bottom: 16px;
      letter-spacing: 0.02em;
    }}
    h1.hero-title {{
      font-size: 38px;
      font-weight: 800;
      letter-spacing: -0.02em;
      color: #ffffff;
      margin-bottom: 12px;
    }}
    p.hero-desc {{
      font-size: 18px;
      color: var(--text-muted);
      max-width: 680px;
      margin: 0 auto 28px auto;
    }}
    .summary-strip {{
      display: inline-flex;
      gap: 24px;
      background: var(--card-bg);
      border: 1px solid var(--border);
      border-radius: 12px;
      padding: 12px 28px;
      margin-top: 8px;
    }}
    .summary-item {{
      display: flex;
      flex-direction: column;
      align-items: center;
    }}
    .summary-val {{
      font-size: 22px;
      font-weight: 700;
      color: #ffffff;
    }}
    .summary-lbl {{
      font-size: 12px;
      color: var(--text-muted);
      text-transform: uppercase;
      letter-spacing: 0.05em;
    }}
    .gallery-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(520px, 1fr));
      gap: 28px;
      margin-bottom: 64px;
    }}
    @media (max-width: 768px) {{
      .gallery-grid {{
        grid-template-columns: 1fr;
      }}
      .summary-strip {{
        flex-direction: column;
        gap: 12px;
      }}
    }}
    .repo-card {{
      background: var(--card-bg);
      border: 1px solid var(--border);
      border-radius: 14px;
      padding: 24px;
      display: flex;
      flex-direction: column;
      justify-content: space-between;
      transition: transform 0.15s ease, border-color 0.15s ease;
    }}
    .repo-card:hover {{
      border-color: var(--border-light);
      background: var(--card-hover);
    }}
    .repo-card-header {{
      display: flex;
      justify-content: space-between;
      align-items: flex-start;
      margin-bottom: 16px;
    }}
    .repo-name {{
      font-size: 22px;
      font-weight: 700;
      color: #fff;
    }}
    .repo-desc {{
      font-size: 14px;
      color: var(--text-muted);
      margin-top: 4px;
    }}
    .tags-wrapper {{
      display: flex;
      gap: 6px;
      flex-wrap: wrap;
    }}
    .tag {{
      background: var(--tag-bg);
      color: #cbd5e1;
      font-size: 11px;
      font-weight: 600;
      padding: 3px 8px;
      border-radius: 4px;
      border: 1px solid #334155;
    }}
    .stats-grid {{
      display: grid;
      grid-template-columns: repeat(4, 1fr);
      gap: 10px;
      background: #0d1017;
      border: 1px solid var(--border);
      border-radius: 10px;
      padding: 12px;
      margin: 16px 0;
    }}
    .stat-item {{
      display: flex;
      flex-direction: column;
    }}
    .stat-label {{
      font-size: 11px;
      color: var(--text-muted);
      text-transform: uppercase;
      letter-spacing: 0.04em;
    }}
    .stat-val {{
      font-size: 15px;
      font-weight: 600;
      color: #ffffff;
      margin-top: 2px;
    }}
    .stat-sub {{
      font-size: 11px;
      color: var(--text-muted);
      font-weight: 400;
    }}
    .badge-cycle {{
      display: inline-block;
      padding: 2px 6px;
      border-radius: 4px;
      font-size: 11px;
      font-weight: 600;
    }}
    .badge-clean {{
      background: rgba(16, 185, 129, 0.15);
      color: var(--accent-emerald);
      border: 1px solid rgba(16, 185, 129, 0.3);
    }}
    .badge-warning {{
      background: rgba(245, 158, 11, 0.15);
      color: var(--accent-amber);
      border: 1px solid rgba(245, 158, 11, 0.3);
    }}
    .review-preview {{
      background: #0f131c;
      border-left: 3px solid #38bdf8;
      border-radius: 0 8px 8px 0;
      padding: 10px 14px;
      margin-bottom: 20px;
    }}
    .review-empty {{
      border-left-color: #475569;
    }}
    .review-title {{
      font-size: 11px;
      color: var(--text-muted);
      text-transform: uppercase;
      font-weight: 600;
      letter-spacing: 0.05em;
    }}
    .review-summary-text {{
      font-size: 13px;
      color: #e2e8f0;
      font-family: ui-monospace, monospace;
    }}
    .badge-pill {{
      display: inline-block;
      padding: 2px 6px;
      border-radius: 4px;
      font-size: 11px;
      font-family: ui-monospace, monospace;
      font-weight: 600;
    }}
    .pill-compare {{
      background: #0369a1;
      color: #fff;
    }}
    .card-actions {{
      display: flex;
      gap: 10px;
      margin-top: auto;
    }}
    .btn {{
      flex: 1;
      display: inline-flex;
      justify-content: center;
      align-items: center;
      gap: 6px;
      padding: 10px 16px;
      border-radius: 8px;
      text-decoration: none;
      font-weight: 600;
      font-size: 13px;
      transition: background 0.15s ease;
      text-align: center;
    }}
    .btn-primary {{
      background: var(--accent-primary);
      color: #ffffff;
    }}
    .btn-primary:hover {{
      background: var(--accent-primary-hover);
    }}
    .btn-secondary {{
      background: #1e293b;
      color: #e2e8f0;
      border: 1px solid #334155;
    }}
    .btn-secondary:hover {{
      background: #334155;
    }}
    footer {{
      border-top: 1px solid var(--border);
      padding-top: 24px;
      text-align: center;
      font-size: 13px;
      color: var(--text-muted);
    }}
    footer a {{
      color: var(--accent-primary);
      text-decoration: none;
    }}
    footer a:hover {{
      text-decoration: underline;
    }}
  </style>
</head>
<body>
  <div class="container">
    <header class="hero">
      <div class="brand-badge">Codebase Inspector &bull; Architecture Gallery</div>
      <h1 class="hero-title">{html.escape(title)}</h1>
      <p class="hero-desc">{html.escape(description)}</p>

      <div class="summary-strip">
        <div class="summary-item">
          <div class="summary-val">{total_repos}</div>
          <div class="summary-lbl">Repositories</div>
        </div>
        <div class="summary-item">
          <div class="summary-val">{total_files}</div>
          <div class="summary-lbl">Total Files</div>
        </div>
        <div class="summary-item">
          <div class="summary-val">{total_symbols}</div>
          <div class="summary-lbl">Symbols Tracked</div>
        </div>
        <div class="summary-item">
          <div class="summary-val" style="color: #34d399;">100%</div>
          <div class="summary-lbl">Deterministic</div>
        </div>
      </div>
    </header>

    <div class="gallery-grid">
      {cards_joined}
    </div>

    <footer>
      Built with <strong>Codebase Inspector (cbi)</strong> &bull; 100% local, zero LLM tokens, MIT licensed.<br>
      <span style="font-size: 12px; margin-top: 4px; display: inline-block;">All maps and PR reviews generated offline without external network calls.</span>
    </footer>
  </div>
</body>
</html>"""

    out_file = out_dir / "index.html"
    out_file.write_text(html_page, encoding="utf-8")
    return out_file


def generate_gallery(
    repos: List[Dict[str, Any]],
    out_dir: Path,
    title: str = "Codebase Inspector Architecture Gallery",
    description: str = "Deterministic architecture reviews and interactive concept maps for modern codebases.",
) -> Dict[str, Any]:
    """Generate the full multi-repository showcase site."""
    out_dir = Path(out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    repos_base = out_dir / "repos"
    repos_base.mkdir(parents=True, exist_ok=True)

    processed_repos = []

    for item in repos:
        repo_name = item["name"]
        repo_path = Path(item["path"]).resolve()
        compare_range = item.get("compare")
        slug = re.sub(r"[^a-zA-Z0-9_\-]", "_", repo_name).lower()

        repo_dest = repos_base / slug
        viewer_dest = repo_dest / "viewer"
        review_dest = repo_dest / "review"

        # 1. Ensure scanned & extract metrics
        ensure_repo_scanned(repo_path)
        metrics = extract_repo_metrics(repo_path)

        # 2. Build concept map viewer
        viewer_index = build_repo_viewer(repo_path, viewer_dest)

        # 3. Build review if requested
        review_info = None
        if compare_range:
            try:
                review_info = build_repo_review(repo_path, compare_range, review_dest, repo_name)
            except Exception as err:
                print(f"Warning: review failed for {repo_name} ({compare_range}): {err}", file=sys.stderr)
                review_info = {"has_review": False, "error": str(err)}

        processed_repos.append({
            "name": repo_name,
            "slug": slug,
            "path": repo_path,
            "description": item.get("description", f"Repository {repo_name}"),
            "tags": item.get("tags", []),
            "metrics": metrics,
            "viewer_index": viewer_index,
            "review": review_info,
        })

    # 4. Generate root index.html
    gallery_meta = {
        "title": title,
        "description": description,
    }
    index_path = render_gallery_index(gallery_meta, processed_repos, out_dir)

    return {
        "gallery_dir": out_dir,
        "index_path": index_path,
        "repos": processed_repos,
    }


def cmd_gallery(args: argparse.Namespace) -> int:
    """CLI subcommand handler for `cbi gallery`."""
    repo_specs: List[Dict[str, Any]] = []
    title = getattr(args, "title", "Codebase Inspector Architecture Gallery")
    description = getattr(
        args,
        "description",
        "Deterministic architecture reviews and interactive concept maps for modern codebases.",
    )

    if getattr(args, "config", None):
        try:
            cfg = load_gallery_config(args.config)
            repo_specs.extend(cfg["repos"])
            if not title or title == "Codebase Inspector Architecture Gallery":
                title = cfg.get("title", title)
            if not description or description.startswith("Deterministic architecture"):
                description = cfg.get("description", description)
        except Exception as err:
            print(f"cbi gallery: cannot load config: {err}", file=sys.stderr)
            return 1

    repo_inputs = (getattr(args, "repos", []) or []) + (getattr(args, "repo_flags", []) or [])
    for spec_str in repo_inputs:
        repo_specs.append(parse_repo_spec(spec_str))

    if not repo_specs:
        try:
            cwd_root = files.repo_root(Path.cwd())
            repo_specs.append(parse_repo_spec(str(cwd_root)))
        except files.NotARepo:
            print("cbi gallery: at least one repository or a valid --config must be provided", file=sys.stderr)
            return 2

    out_dir = getattr(args, "out_dir", None) or getattr(args, "out", None) or Path("dist/gallery")
    print(f"Generating architecture gallery for {len(repo_specs)} repositories in {out_dir}...")
    try:
        res = generate_gallery(repo_specs, out_dir, title=title, description=description)
        print(f"✓ Gallery generated successfully: {res['index_path']}")
        return 0
    except Exception as err:
        print(f"cbi gallery: failed to generate gallery: {err}", file=sys.stderr)
        return 1


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="cbi gallery",
        description="Generate an offline static multi-repository architecture showcase.",
    )
    parser.add_argument(
        "repos",
        nargs="*",
        metavar="REPO",
        help="Repository specifier: /path/to/repo, name=/path/to/repo, or name=/path/to/repo:base..head",
    )
    parser.add_argument(
        "--repo",
        action="append",
        dest="repo_flags",
        default=[],
        help="Repository specifier: /path/to/repo, name=/path/to/repo, or name=/path/to/repo:base..head",
    )
    parser.add_argument(
        "--config",
        type=Path,
        help="Path to JSON configuration file describing repositories and metadata",
    )
    parser.add_argument(
        "--out",
        "--out-dir",
        dest="out_dir",
        type=Path,
        default=Path("dist/gallery"),
        help="Destination directory for the gallery site (default: dist/gallery)",
    )
    parser.add_argument(
        "--title",
        default="Codebase Inspector Architecture Gallery",
        help="Gallery title",
    )
    parser.add_argument(
        "--description",
        default="Deterministic architecture reviews and interactive concept maps for modern codebases.",
        help="Gallery subtitle/description",
    )

    args = parser.parse_args(argv)
    return cmd_gallery(args)


if __name__ == "__main__":
    sys.exit(main())
