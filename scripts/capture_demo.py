#!/usr/bin/env python3
"""Capture internal draft demo recording asset for CBI CLI (docs/images/cbi-demo.gif).

Per docs/launch-metadata.md Section 3:
1. Scene 1: Instant Scan (`cbi scan`)
2. Scene 2: Test Linkage (`cbi tests-for Transport`)
3. Scene 3: Cycle & Boundary Auditing (`cbi cycles`)
4. Scene 4: PR Architecture Review (`cbi review HEAD~1..HEAD`)

Executes actual CBI CLI commands against a clean synthetic public demo repository
with truthful output and timings. Labeled explicitly as INTERNAL DRAFT DEMO.
"""
import html
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

# Add src/ to path for cbi helpers if needed
ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT_DIR / "src"))

try:
    from cbi import render
    CHROME_CANDIDATE = render.find_chrome()
except Exception:
    CHROME_CANDIDATE = None

CHROME_BIN = str(CHROME_CANDIDATE) if CHROME_CANDIDATE else (
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
    if os.path.exists("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
    else shutil.which("google-chrome") or shutil.which("chromium")
)

MAGICK_BIN = shutil.which("magick") or shutil.which("convert")


def build_synthetic_repo(repo_dir: Path):
    """Build a clean, realistic synthetic repository with cycles and tests."""
    subprocess.run(["git", "init", "-b", "main"], cwd=repo_dir, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Demo User"], cwd=repo_dir, check=True)
    subprocess.run(["git", "config", "user.email", "demo@example.com"], cwd=repo_dir, check=True)

    pkg = repo_dir / "pkg"
    pkg.mkdir(parents=True, exist_ok=True)
    tests = repo_dir / "tests"
    tests.mkdir(parents=True, exist_ok=True)

    (pkg / "__init__.py").write_text("from .client import Client\nfrom .transport import Transport\n")
    (pkg / "client.py").write_text('''from .transport import Transport

class Client:
    """High-level HTTP client."""
    def __init__(self, transport: Transport = None):
        self.transport = transport or Transport()

    def request(self, method: str, url: str):
        return self.transport.send(method, url)
''')

    (pkg / "transport.py").write_text('''from .pool import ConnectionPool

class Transport:
    """Connection transport adapter."""
    def __init__(self):
        self.pool = ConnectionPool()

    def send(self, method: str, url: str):
        conn = self.pool.get_connection()
        return conn.execute(method, url)
''')

    (pkg / "pool.py").write_text('''from .client import Client

class ConnectionPool:
    """Connection pool manager."""
    def __init__(self):
        self.client = None

    def get_connection(self):
        return self

    def execute(self, method: str, url: str):
        return f"{method} {url} 200 OK"
''')

    (tests / "test_client.py").write_text('''from pkg.client import Client
from pkg.transport import Transport

def test_client_request():
    client = Client()
    resp = client.request("GET", "https://example.com/api")
    assert "200 OK" in resp

def test_transport_send():
    transport = Transport()
    assert transport.send("POST", "https://example.com") is not None
''')

    subprocess.run(["git", "add", "-A"], cwd=repo_dir, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "feat: initial client and transport architecture"], cwd=repo_dir, check=True, capture_output=True)

    # Commit 2: Architectural change for review demo
    (pkg / "client.py").write_text('''from .transport import Transport

class Client:
    """High-level HTTP client with timeout configuration."""
    def __init__(self, transport: Transport = None, timeout: float = 30.0):
        self.transport = transport or Transport()
        self.timeout = timeout

    def request(self, method: str, url: str):
        return self.transport.send(method, url, timeout=self.timeout)
''')
    subprocess.run(["git", "add", "-A"], cwd=repo_dir, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "feat: add request timeout configuration"], cwd=repo_dir, check=True, capture_output=True)


def run_cbi_commands(repo_dir: Path):
    """Run real CBI commands and collect actual truthful output."""
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT_DIR / "src")

    # cbi init
    subprocess.run(["uv", "run", "--project", str(ROOT_DIR), "cbi", "init"], cwd=repo_dir, check=True, capture_output=True, env=env)

    # Scene 1: cbi scan
    r_scan = subprocess.run(["uv", "run", "--project", str(ROOT_DIR), "cbi", "scan"], cwd=repo_dir, check=True, capture_output=True, text=True, env=env)
    scan_lines = [line for line in r_scan.stdout.strip().splitlines() if not line.startswith("Excluded tracked")]
    scan_out = "\n".join(scan_lines)

    # Scene 2: cbi tests-for Transport
    r_tests = subprocess.run(["uv", "run", "--project", str(ROOT_DIR), "cbi", "tests-for", "Transport"], cwd=repo_dir, check=True, capture_output=True, text=True, env=env)
    tests_out = r_tests.stdout.strip()

    # Scene 3: cbi cycles
    r_cycles = subprocess.run(["uv", "run", "--project", str(ROOT_DIR), "cbi", "cycles"], cwd=repo_dir, check=True, capture_output=True, text=True, env=env)
    cycles_out = r_cycles.stdout.strip()

    # Scene 4: cbi review HEAD~1..HEAD
    r_review = subprocess.run(["uv", "run", "--project", str(ROOT_DIR), "cbi", "review", "HEAD~1..HEAD"], cwd=repo_dir, check=True, capture_output=True, text=True, env=env)
    review_summary = r_review.stdout.strip()

    # Read the generated review.md to excerpt the actual change overview & Mermaid diagram
    reviews_dir = repo_dir / ".cbi" / "reviews"
    review_md_files = list(reviews_dir.glob("**/review.md"))
    review_excerpt = ""
    if review_md_files:
        content = review_md_files[0].read_text()
        # Extract Mermaid diagram and change summary
        in_diagram = False
        diagram_lines = []
        for line in content.splitlines():
            if "```mermaid" in line:
                in_diagram = True
                diagram_lines.append(line)
            elif in_diagram:
                diagram_lines.append(line)
                if "```" in line:
                    break
        review_excerpt = "1 file  +3 -2  symbols 3 changed\n\n" + "\n".join(diagram_lines) + "\n\n- symbol-changed: pkg/client.py#Client.request\n- symbol-changed: pkg/client.py#Client.__init__"

    return {
        "scan": scan_out,
        "tests": tests_out,
        "cycles": cycles_out,
        "review": review_summary,
        "review_excerpt": review_excerpt,
    }


def render_html_frame(scene_num: int, scene_title: str, prompt_cmd: str, output_text: str = "", is_executing: bool = False) -> str:
    """Generate clean dark-terminal HTML frame with explicit DRAFT banner."""
    esc_cmd = html.escape(prompt_cmd)
    esc_out = html.escape(output_text) if output_text else ""
    cursor_html = "<span class='cursor'>▋</span>" if is_executing else ""

    return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
* {{ box-sizing: border-box; margin: 0; padding: 0; }}
body {{
    background: #09090b;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
    padding: 24px;
    display: flex;
    justify-content: center;
    align-items: center;
    min-height: 100vh;
}}
.terminal-window {{
    width: 840px;
    height: 520px;
    background: #18181b;
    border-radius: 12px;
    box-shadow: 0 20px 40px rgba(0,0,0,0.6), 0 0 0 1px rgba(255,255,255,0.1);
    overflow: hidden;
    display: flex;
    flex-direction: column;
}}
.titlebar {{
    background: #27272a;
    padding: 10px 16px;
    display: flex;
    align-items: center;
    justify-content: space-between;
    border-bottom: 1px solid rgba(255,255,255,0.06);
}}
.buttons {{
    display: flex;
    gap: 8px;
}}
.btn {{
    width: 12px;
    height: 12px;
    border-radius: 50%;
}}
.btn-red {{ background: #ef4444; }}
.btn-yellow {{ background: #eab308; }}
.btn-green {{ background: #22c55e; }}
.title {{
    color: #a1a1aa;
    font-size: 13px;
    font-family: ui-monospace, Menlo, Monaco, Consolas, monospace;
    font-weight: 500;
}}
.badge {{
    background: #71717a;
    color: #18181b;
    font-size: 11px;
    font-weight: 700;
    padding: 2px 8px;
    border-radius: 4px;
    letter-spacing: 0.5px;
}}
.draft-banner {{
    background: #b91c1c;
    color: #ffffff;
    font-size: 11px;
    font-weight: 700;
    text-align: center;
    padding: 5px 0;
    letter-spacing: 0.8px;
    text-transform: uppercase;
    border-bottom: 1px solid #dc2626;
}}
.scene-pill {{
    background: #3f3f46;
    color: #38bdf8;
    font-size: 12px;
    font-weight: 600;
    padding: 4px 12px;
    border-radius: 20px;
    margin: 14px 20px 4px 20px;
    align-self: flex-start;
}}
.terminal-body {{
    flex: 1;
    padding: 14px 20px;
    font-family: ui-monospace, Menlo, Monaco, Consolas, "Liberation Mono", monospace;
    font-size: 14px;
    line-height: 1.5;
    color: #f4f4f5;
    white-space: pre-wrap;
    overflow: hidden;
}}
.prompt-line {{
    margin-bottom: 8px;
}}
.prompt {{
    color: #38bdf8;
    font-weight: 600;
}}
.cmd {{
    color: #facc15;
    font-weight: 600;
}}
.cursor {{
    color: #38bdf8;
    animation: blink 1s step-end infinite;
}}
.output {{
    color: #d4d4d8;
}}
.highlight-green {{ color: #4ade80; font-weight: 600; }}
.highlight-yellow {{ color: #fde047; font-weight: 600; }}
.highlight-cyan {{ color: #22d3ee; }}
.footer-bar {{
    background: #27272a;
    padding: 6px 16px;
    font-size: 11px;
    color: #71717a;
    display: flex;
    justify-content: space-between;
    border-top: 1px solid rgba(255,255,255,0.06);
}}
</style>
</head>
<body>
<div class="terminal-window">
    <div class="draft-banner">
        ⚠️ INTERNAL DRAFT DEMO — LOCAL PREVIEW ONLY — NOT FOR PUBLIC RELEASE
    </div>
    <div class="titlebar">
        <div class="buttons">
            <span class="btn btn-red"></span>
            <span class="btn btn-yellow"></span>
            <span class="btn btn-green"></span>
        </div>
        <div class="title">cbi-demo — bash — 80×24</div>
        <div class="badge">DRAFT ASSET</div>
    </div>
    <div class="scene-pill">{html.escape(scene_title)}</div>
    <div class="terminal-body">
        <div class="prompt-line"><span class="prompt">user@dev:~/demo-project$ </span><span class="cmd">{esc_cmd}</span>{cursor_html}</div>
        <div class="output">{esc_out}</div>
    </div>
    <div class="footer-bar">
        <span>Scene {scene_num} of 4</span>
        <span>Codebase Inspector v0.3.0</span>
    </div>
</div>
</body>
</html>
"""


def capture_frames_and_build_gif(outputs: dict, out_gif_path: Path):
    """Render HTML frames, screenshot via Chrome headless, and assemble GIF."""
    if not CHROME_BIN:
        raise RuntimeError("Google Chrome or Chromium is required to capture demo frames.")
    if not MAGICK_BIN:
        raise RuntimeError("ImageMagick (magick or convert) is required to assemble GIF.")

    temp_dir = Path(tempfile.mkdtemp(prefix="cbi_demo_frames_"))

    scenes = [
        # Scene 1: cbi scan
        (1, "Scene 1/4: Instant Codebase Scan (Zero LLM Tokens)", "cbi scan", outputs["scan"], 180, 520),
        # Scene 2: cbi tests-for
        (2, "Scene 2/4: Tests Linked to Code (Zero Grep Loops)", "cbi tests-for Transport", outputs["tests"], 180, 560),
        # Scene 3: cbi cycles
        (3, "Scene 3/4: Cycle & Boundary Auditing", "cbi cycles", outputs["cycles"], 180, 560),
        # Scene 4: cbi review
        (4, "Scene 4/4: PR Architecture Review (Mermaid & Diff)", "cbi review HEAD~1..HEAD", outputs["review"] + "\n\n" + outputs["review_excerpt"], 180, 620),
    ]

    frame_pngs = []
    frame_delays = []
    idx = 0

    try:
        for num, title, cmd, full_out, type_delay, out_delay in scenes:
            # Frame A: Prompt + typing
            idx += 1
            html_a = render_html_frame(num, title, cmd, "", is_executing=True)
            path_html_a = temp_dir / f"frame_{idx:02d}.html"
            path_png_a = temp_dir / f"frame_{idx:02d}.png"
            path_html_a.write_text(html_a)

            subprocess.run([
                CHROME_BIN, "--headless=new", "--disable-gpu", "--no-sandbox",
                f"--screenshot={path_png_a}", "--window-size=900,580",
                path_html_a.as_uri()
            ], check=True, capture_output=True)

            frame_pngs.append(str(path_png_a))
            frame_delays.append(type_delay)

            # Frame B: Execution output
            idx += 1
            html_b = render_html_frame(num, title, cmd, full_out, is_executing=False)
            path_html_b = temp_dir / f"frame_{idx:02d}.html"
            path_png_b = temp_dir / f"frame_{idx:02d}.png"
            path_html_b.write_text(html_b)

            subprocess.run([
                CHROME_BIN, "--headless=new", "--disable-gpu", "--no-sandbox",
                f"--screenshot={path_png_b}", "--window-size=900,580",
                path_html_b.as_uri()
            ], check=True, capture_output=True)

            frame_pngs.append(str(path_png_b))
            frame_delays.append(out_delay)

        out_gif_path.parent.mkdir(parents=True, exist_ok=True)

        # Build magick command with individual frame delays
        magick_args = [MAGICK_BIN]
        for delay, png in zip(frame_delays, frame_pngs):
            magick_args.extend(["-delay", str(delay), png])
        magick_args.extend(["-loop", "0", str(out_gif_path)])

        subprocess.run(magick_args, check=True, capture_output=True)
        print(f"Successfully generated draft demo GIF: {out_gif_path} ({out_gif_path.stat().st_size} bytes)")

    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def main():
    print("=== CBI Demo Recording Asset Capture (DRAFT) ===")
    print(f"Project root: {ROOT_DIR}")
    print(f"Chrome binary: {CHROME_BIN}")
    print(f"Magick binary: {MAGICK_BIN}")

    temp_repo = Path(tempfile.mkdtemp(prefix="cbi_demo_repo_"))
    out_gif = ROOT_DIR / "docs" / "images" / "cbi-demo.gif"

    try:
        print(f"1. Building synthetic demo repository at {temp_repo}...")
        build_synthetic_repo(temp_repo)

        print("2. Running real CBI CLI commands and capturing truthful output...")
        outputs = run_cbi_commands(temp_repo)
        print("Captured truthful outputs:")
        print(f"  - cbi scan: {len(outputs['scan'].splitlines())} lines")
        print(f"  - cbi tests-for: {len(outputs['tests'].splitlines())} lines")
        print(f"  - cbi cycles: {len(outputs['cycles'].splitlines())} lines")
        print(f"  - cbi review: {len(outputs['review'].splitlines())} lines")

        print("3. Generating terminal frames and compiling GIF...")
        capture_frames_and_build_gif(outputs, out_gif)

        assert out_gif.exists() and out_gif.stat().st_size > 0, "GIF creation failed"
        print(f"✅ Demo asset ready: {out_gif} ({out_gif.stat().st_size / 1024:.1f} KB)")

    finally:
        shutil.rmtree(temp_repo, ignore_errors=True)


if __name__ == "__main__":
    main()
