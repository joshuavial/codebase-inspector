#!/usr/bin/env python3
"""Smoke the concept viewer from file:// with Playwright.

Run from the repo (installs nothing into the project):

    uvx --from playwright python scripts/smoke_viewer.py

Chromium has to be present for that Playwright. If launch fails:

    uvx --from playwright playwright install chromium

The fixture model is built with this worktree's cbi, via `uv run`, so the
uvx environment does not need the package. Screenshots land in /tmp/cbi-p19-smoke.
"""

import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = Path("/tmp/cbi-p19-smoke")

BUILD = r"""
import sys
from pathlib import Path
from tests.test_viewer import concept_model
from cbi import build
dest = Path(sys.argv[1])
dest.mkdir(parents=True, exist_ok=True)
conn = concept_model(dest)
print(build.build(conn, dest / "viewer"))
"""


def viewbox(page):
    raw = page.locator("#diagram").get_attribute("viewBox")
    return [float(part) for part in raw.split()]


def wait_drawn(page, text, timeout=20000):
    page.wait_for_function(
        """(needle) => [...document.querySelectorAll('#diagram .name')].some((n) => n.textContent === needle)""",
        arg=text,
        timeout=timeout,
    )


def shot(page, path):
    page.wait_for_timeout(400)
    page.screenshot(path=str(path))


def open_viewer(page, index):
    errors = []
    page.on("pageerror", lambda err: errors.append(str(err)))
    page.goto(index.resolve().as_uri())
    page.wait_for_function(
        "() => document.querySelectorAll('#diagram .node').length > 0",
        timeout=30000,
    )
    if errors:
        raise SystemExit("page error on load:\n" + "\n".join(errors))
    return errors


def check(name, ok, detail=""):
    print(f"{'PASS' if ok else 'FAIL'} {name}" + (f" — {detail}" if detail else ""))
    if not ok:
        raise SystemExit(1)


def smoke_fixture(page, index):
    errors = open_viewer(page, index)
    wait_drawn(page, "App")
    shot(page, OUT / "fixture-top.png")

    before = viewbox(page)
    box = page.locator("#diagram").bounding_box()
    page.mouse.move(box["x"] + box["width"] * 0.72, box["y"] + 30)
    page.mouse.wheel(480, 0)
    page.wait_for_timeout(50)
    panned = viewbox(page)
    check("horizontal scroll pans", panned[0] > before[0] + 1, f"x {before[0]:.1f} -> {panned[0]:.1f}")

    page.keyboard.down("Meta")
    page.mouse.wheel(0, -200)
    page.keyboard.up("Meta")
    page.wait_for_timeout(50)
    zoomed = viewbox(page)
    how = "playwright Meta+wheel"
    if abs(zoomed[2] - panned[2]) < 1:
        page.evaluate(
            """() => {
              const svg = document.getElementById('diagram');
              const r = svg.getBoundingClientRect();
              svg.dispatchEvent(new WheelEvent('wheel', {
                deltaY: -200, metaKey: true, bubbles: true, cancelable: true,
                clientX: r.left + r.width / 2, clientY: r.top + 40,
              }));
            }"""
        )
        page.wait_for_timeout(50)
        zoomed = viewbox(page)
        how = "WheelEvent metaKey (Playwright wheel did not carry Meta)"
    check("Cmd+scroll zooms", zoomed[2] < panned[2] - 1, f"w {panned[2]:.1f} -> {zoomed[2]:.1f} via {how}")

    page.locator("#zfit").click()
    page.wait_for_timeout(400)
    wait_drawn(page, "App")
    page.locator("#diagram g.node").filter(has_text="App").first.click()
    page.wait_for_function("() => location.hash.includes('concept') && location.hash.includes('app')")
    wait_drawn(page, "API")
    check("drill in", "concept" in page.evaluate("() => location.hash"), page.evaluate("() => location.hash"))

    page.keyboard.press("Escape")
    page.wait_for_function("() => !new URLSearchParams(location.hash.slice(1)).get('c')")
    wait_drawn(page, "App")
    check("Esc up one level", page.evaluate("() => !new URLSearchParams(location.hash.slice(1)).get('c')"))

    top_hash = page.evaluate("() => location.hash")
    top_box = viewbox(page)
    page.locator("#diagram g.node").filter(has_text="App").first.click()
    page.wait_for_function("() => location.hash.includes('concept') && location.hash.includes('app')")
    wait_drawn(page, "API")
    page.keyboard.press("Backspace")
    page.wait_for_function("(h) => location.hash === h", arg=top_hash)
    wait_drawn(page, "App")
    back_box = viewbox(page)
    check(
        "Backspace after a drill restores the view",
        abs(back_box[0] - top_box[0]) < 2 and abs(back_box[2] - top_box[2]) < 2,
        f"hash {page.evaluate('() => location.hash')} view {back_box[2]:.1f} vs {top_box[2]:.1f}",
    )

    page.locator("#diagram g.node").filter(has_text="App").first.click()
    page.wait_for_function("() => location.hash.includes('app')")
    wait_drawn(page, "API")
    page.locator("#diagram g.node").filter(has_text="API").first.click()
    page.wait_for_function("() => location.hash.includes('api')")
    wait_drawn(page, "verify")
    page.locator("#diagram .sym.ghost").filter(has_text="Store").first.click()
    page.wait_for_function("() => location.hash.includes('Store') && document.querySelector('#diagram .edge.hot')")
    selected = page.evaluate("() => location.hash")
    check("grey node selects before it navigates", "api" in selected and "Store" in selected, selected)
    check("grey node shows its link", page.locator("#diagram .edge.hot").count() > 0)
    drawer_now = page.locator("#drawer").inner_text()
    check("grey node explains the way across", "Go to" in drawer_now, drawer_now.split("\n")[0])
    page.locator("#drawer button.action").click()
    page.wait_for_function("() => location.hash.includes('core')")
    chip = page.locator("#crumbs .back").inner_text()
    check("jump from a grey node leaves a Back chip", chip.startswith("← Back to"), chip)
    page.keyboard.press("Backspace")
    page.wait_for_function(
        """(h) => location.hash === h && document.querySelector('#drawer') && document.querySelector('#drawer').textContent.includes('Go to')""",
        arg=selected,
    )
    check("Backspace returns to the grey node", "Go to" in page.locator("#drawer").inner_text())

    page.locator("#q").fill("verify")
    page.locator("#hits li").first.wait_for()
    hit = page.locator("#hits li").first.inner_text()
    check("search lists a symbol", "verify" in hit.lower(), hit.replace("\n", " "))
    page.locator("#hits li").first.dispatch_event("mousedown")
    page.wait_for_function("() => location.hash.includes('verify')")
    check("search opens the symbol", "verify" in page.evaluate("() => decodeURIComponent(location.hash)"))

    page.locator("#q").fill("API_TOKEN")
    page.locator("#hits li").filter(has_text="API_TOKEN").first.wait_for()
    env_hit = page.locator("#hits li").filter(has_text="API_TOKEN").first.inner_text()
    check("search lists an env var", "API_TOKEN" in env_hit, env_hit.replace("\n", " "))
    page.locator("#hits li").filter(has_text="API_TOKEN").first.dispatch_event("mousedown")
    page.wait_for_function("() => location.hash.includes('api')")
    wait_drawn(page, "verify")
    drawer = page.locator("#drawer").inner_text()
    check("search opens the env var's concept", "API_TOKEN" in drawer, page.evaluate("() => location.hash"))
    shot(page, OUT / "fixture-leaf.png")
    if errors:
        raise SystemExit("page error during smoke:\n" + "\n".join(errors))


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    fixture = OUT / "fixture"
    if fixture.exists():
        shutil.rmtree(fixture)
    subprocess.check_call(["uv", "run", "--project", str(ROOT), "python", "-c", BUILD, str(fixture)], cwd=ROOT)
    index = fixture / "viewer" / "index.html"
    if not index.is_file():
        raise SystemExit(f"viewer was not written: {index}")

    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1400, "height": 900}, device_scale_factor=1)
        smoke_fixture(page, index)
        browser.close()
    print(f"screenshots in {OUT}")


if __name__ == "__main__":
    sys.exit(main())
