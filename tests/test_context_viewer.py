"""The viewer's Copy for agent button copies the precomputed block."""

import importlib.util
import json
from pathlib import Path

import pytest

from cbi import build, context

_spec = importlib.util.spec_from_file_location(
    "context_fixture_viewer", Path(__file__).with_name("test_viewer.py"))
_viewer = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_viewer)
FN, WS, concept_model = _viewer.FN, _viewer.WS, _viewer.concept_model


def test_copy_button_copies_the_node_and_a_command(tmp_path):
    pytest.importorskip("playwright.sync_api")
    from playwright.sync_api import sync_playwright

    conn = concept_model(tmp_path)
    place = context.Place(repo=tmp_path, model_root=tmp_path / ".cbi", branch="main")
    viewer = tmp_path / "viewer"
    index = build.build(conn, viewer, place=place)
    conn.close()
    raw = (viewer / "data" / "context.js").read_text()
    written = json.loads(raw.removeprefix('cbiLoad("context", ').removesuffix(");\n"))
    expected = written["blocks"][FN]
    assert FN in expected and "cbi show" in expected

    with sync_playwright() as p:
        try:
            browser = p.chromium.launch(channel="chrome", headless=True)
        except Exception as err:
            pytest.skip(f"system Chrome is not launchable: {err}")
        page = browser.new_page(viewport={"width": 1280, "height": 800})
        page.add_init_script("""
          window.__copied = "";
          const clip = { writeText(text) { window.__copied = String(text); return Promise.resolve(); } };
          try {
            Object.defineProperty(navigator, "clipboard", { configurable: true, get() { return clip; } });
          } catch (e) {}
        """)
        errors = []
        page.on("pageerror", lambda exc: errors.append(str(exc)))
        page.goto(index.resolve().as_uri())
        page.wait_for_selector("#drawer button.copy-agent", timeout=20000)
        page.evaluate("""() => {
          window.__copied = "";
          const clip = { writeText(text) { window.__copied = String(text); return Promise.resolve(); } };
          try {
            Object.defineProperty(navigator, "clipboard", { configurable: true, get() { return clip; } });
          } catch (e) {}
        }""")

        page.click("#drawer button.copy-agent")
        page.wait_for_function("() => window.__copied.includes('cbi show')", timeout=5000)
        top = page.evaluate("() => window.__copied")
        assert WS in top and "cbi show" in top
        assert page.locator("#toast").inner_text() == "Copied"
        assert errors == []

        page.fill("#q", "verify")
        page.press("#q", "Enter")
        page.wait_for_function(
            "(id) => new URLSearchParams(location.hash.slice(1)).get('s') === id",
            arg=FN, timeout=10000,
        )
        before = page.evaluate("() => location.hash")
        page.evaluate("() => { window.__copied = ''; }")
        page.click("#drawer button.copy-agent")
        page.wait_for_function("() => window.__copied.length > 0", timeout=5000)
        copied = page.evaluate("() => window.__copied")
        assert copied == expected
        assert FN in copied and "cbi show" in copied
        assert page.evaluate("() => location.hash") == before
        assert page.locator("#toast").inner_text() == "Copied"

        page.evaluate("""() => {
          window.__copied = "";
          if (document.activeElement && document.activeElement.blur) document.activeElement.blur();
          window.getSelection().removeAllRanges();
          document.body.dispatchEvent(new KeyboardEvent("keydown", {
            key: "C", shiftKey: true, metaKey: true, bubbles: true, cancelable: true,
          }));
        }""")
        page.wait_for_function("() => window.__copied.length > 0", timeout=5000)
        assert page.evaluate("() => window.__copied") == expected
        assert page.evaluate("() => location.hash") == before

        for modifier in ("metaKey", "ctrlKey"):
            page.evaluate("""(modifier) => {
              window.__copied = "";
              if (document.activeElement && document.activeElement.blur) document.activeElement.blur();
              window.getSelection().removeAllRanges();
              const ev = new KeyboardEvent("keydown", {
                key: "c", bubbles: true, cancelable: true, [modifier]: true,
              });
              document.body.dispatchEvent(ev);
              window.__plain = { copied: window.__copied, prevented: ev.defaultPrevented };
            }""", modifier)
            page.wait_for_function("() => window.__plain && window.__plain.copied.length > 0", timeout=5000)
            plain = page.evaluate("() => window.__plain")
            assert plain["copied"] == expected and plain["prevented"] is True
            assert page.locator("#toast").inner_text() == "Copied"
            assert page.evaluate("() => location.hash") == before

        selected = page.evaluate("""() => {
          window.__copied = "";
          const node = document.querySelector("#drawer h2") || document.querySelector("#drawer p");
          const range = document.createRange();
          range.selectNodeContents(node);
          const sel = window.getSelection();
          sel.removeAllRanges();
          sel.addRange(range);
          const ev = new KeyboardEvent("keydown", {
            key: "c", metaKey: true, bubbles: true, cancelable: true,
          });
          document.body.dispatchEvent(ev);
          return { selected: String(sel), copied: window.__copied, prevented: ev.defaultPrevented };
        }""")
        assert selected["selected"]
        assert selected["copied"] == ""
        assert selected["prevented"] is False

        field = page.evaluate("""() => {
          window.__copied = "";
          window.getSelection().removeAllRanges();
          const input = document.getElementById("q");
          input.focus();
          const ev = new KeyboardEvent("keydown", {
            key: "c", ctrlKey: true, bubbles: true, cancelable: true,
          });
          input.dispatchEvent(ev);
          return { copied: window.__copied, prevented: ev.defaultPrevented };
        }""")
        assert field["copied"] == "" and field["prevented"] is False
        browser.close()
