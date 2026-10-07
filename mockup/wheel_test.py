"""Check that horizontal wheel input pans the concept map, in Chromium and Firefox.

usage: uv run --no-project --with playwright==1.56.0 python -I mockup/wheel_test.py "$PWD/mockup/index.html"
Uses the system Chrome and an already-cached Playwright Firefox build; downloads nothing.
"""
import sys, glob, os
from playwright.sync_api import sync_playwright

URL = "file://" + sys.argv[1] + "#c=service&debug"

def viewbox(page):
    return [float(x) for x in page.get_attribute("#diagram", "viewBox").split()]

def check(page, name):
    page.goto(URL)
    page.wait_for_function("document.querySelector('#diagram g') !== null")
    page.wait_for_timeout(400)
    page.mouse.move(500, 450)
    x0, y0, w0, _ = viewbox(page)
    page.mouse.wheel(120, 0)  # real input path: horizontal wheel
    page.wait_for_timeout(200)
    x1, y1, w1, _ = viewbox(page)
    assert x1 > x0 and abs(y1 - y0) < 1e-6 and w1 == w0, (name, "mouse.wheel dx", x0, x1, y0, y1)
    # synthetic event over the legend (empty canvas corner) must also be caught
    moved = page.evaluate("""() => {
      const before = document.getElementById('diagram').getAttribute('viewBox');
      const ev = new WheelEvent('wheel', { deltaX: -80, deltaY: 0, bubbles: true, cancelable: true });
      document.getElementById('legend').dispatchEvent(ev);
      return [before !== document.getElementById('diagram').getAttribute('viewBox'), ev.defaultPrevented];
    }""")
    assert moved == [True, True], (name, "synthetic over legend", moved)
    readout = page.text_content("#debug")
    assert "deltaX" in readout, (name, readout)
    # pinch arrives as ctrl+wheel: zooms, does not pan
    page.keyboard.down("Control"); page.mouse.wheel(0, -100); page.keyboard.up("Control")
    page.wait_for_timeout(200)
    assert viewbox(page)[2] < w1, (name, "ctrl+wheel zoom")
    print(name, "ok:", readout)

with sync_playwright() as p:
    b = p.chromium.launch(executable_path="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
    check(b.new_page(viewport={"width": 1400, "height": 900}), "chrome")
    b.close()
    ff = sorted(glob.glob(os.path.expanduser("~/Library/Caches/ms-playwright/firefox-*/firefox/Nightly.app/Contents/MacOS/firefox")))
    b = p.firefox.launch(executable_path=ff[-1]) if ff else p.firefox.launch()
    check(b.new_page(viewport={"width": 1400, "height": 900}), "firefox")
    b.close()
