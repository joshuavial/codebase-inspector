"""Vue, server template, Razor and plain HTML screen detection and answers."""

import json
import sqlite3

import pytest

from cbi import build
from cbi.cli import main


VUE_FILES = {
    "src/router.ts": (
        'import { createRouter } from "vue-router";\n'
        'import Settings from "./Settings.vue";\n'
        'export const router = createRouter({ routes: [{ path: "/settings", component: Settings }] });\n'
    ),
    "src/Settings.vue": (
        '<template>\n'
        '  <div class="dashboard">\n'
        '    <header><h1>Operations</h1><button>Refresh</button></header>\n'
        '    <nav><button>Overview</button><button>Alerts</button></nav>\n'
        '    <StatusBanner v-if="offline" message="Connection lost" />\n'
        '    <main><MetricCard title="Open incidents" /><ActivityList /></main>\n'
        '    <aside><h2>Details</h2><button>Close</button></aside>\n'
        '  </div>\n'
        '</template>\n'
        '<script setup lang="ts">\n'
        'import StatusBanner from "./StatusBanner.vue";\n'
        'import MetricCard from "./MetricCard.vue";\n'
        'import ActivityList from "./ActivityList.vue";\n'
        '</script>\n'
    ),
    "src/StatusBanner.vue": '<template><p>Connection lost</p></template>\n',
    "src/MetricCard.vue": '<template><section><h2>Open incidents</h2><strong>12</strong></section></template>\n',
    "src/ActivityList.vue": '<template><section><h2>Recent activity</h2><ol /></section></template>\n',
}

DJANGO_FILES = {
    "views.py": (
        'from django.shortcuts import render\n\n'
        'def dashboard(request):\n    return render(request, "dashboard.html", {})\n'
    ),
    "urls.py": 'from django.urls import path\nfrom . import views\nurlpatterns = [path("dashboard/", views.dashboard)]\n',
    "templates/dashboard.html": '{% extends "base.html" %}{% include "_nav.html" %}<h1>Dashboard</h1>\n',
    "templates/base.html": '<html><body>{% block content %}{% endblock %}</body></html>\n',
    "templates/_nav.html": '<nav>Home</nav>\n',
}

RAZOR_FILES = {
    "Program.cs": "var app = WebApplication.CreateBuilder(args).Build();\napp.Run();\n",
    "Pages/Reports.cshtml": '@page "/reports"\n<partial name="_Nav" /><h1>Reports</h1>\n',
    "Pages/Shared/_Nav.cshtml": '<nav>Home</nav>\n',
}

HTML_FILES = {
    "package.json": '{"name":"desktop","main":"main.js"}\n',
    "main.js": 'window.loadFile("app/src/index.html");\n',
    "app/src/index.html": (
        '<!doctype html><html><head><link href="theme.css" rel="stylesheet"></head>'
        '<body><h1>Inspector</h1><script src="renderer.js"></script></body></html>\n'
    ),
    "app/src/renderer.js": 'document.body.dataset.ready = "yes";\n',
    "app/src/theme.css": "body { color: black; }\n",
    "tests/decoy.test.js": 'window.loadFile("app/src/index.html");\n',
    "src/render.html": '<html><body><script type="text/plain" id="svg-out"></script></body></html>\n',
}


def run(capsys, *argv):
    capsys.readouterr()
    code = main(list(argv))
    out = capsys.readouterr()
    return code, out.out, out.err


def run_json(capsys, *argv):
    code, out, err = run(capsys, *argv, "--json")
    assert code == 0, err
    return json.loads(out)


def submit(capsys, tmp_path, task_id, answer):
    path = tmp_path / f"{task_id}.json"
    path.write_text(json.dumps(answer))
    code, out, err = run(capsys, "submit", task_id, str(path))
    assert code == 0, err
    return out


def prepare(make_repo, monkeypatch, capsys, tmp_path, files, extra_owned=()):
    root = make_repo(files)
    monkeypatch.chdir(root)
    assert main(["init"]) == 0 and main(["scan"]) == 0
    [task] = run_json(capsys, "tasks", "--kind", "confirm-structure")
    brief = run_json(capsys, "task", task["id"])
    submit(capsys, tmp_path, task["id"], {
        "input_hash": brief["input_hash"], "deployables": [], "packages": [],
    })
    [task] = run_json(capsys, "tasks", "--kind", "define-concepts")
    brief = run_json(capsys, "task", task["id"])
    owned = [item["path"] for item in brief["files"]]
    owned.extend(path for path in extra_owned if path not in owned)
    submit(capsys, tmp_path, task["id"], {
        "input_hash": brief["input_hash"], "summary": "A user interface.",
        "concepts": [{
            "id": "ui", "name": "UI", "summary": "The screens.", "role": "ui", "files": owned,
        }],
        "externals": [], "relationships": [],
    })
    [task] = run_json(capsys, "tasks", "--kind", "sketch-screens")
    return root, run_json(capsys, "task", task["id"])


def accept_one(capsys, tmp_path, brief, target, name):
    answer = {
        "input_hash": brief["input_hash"],
        "screens": [{
            "id": name.lower(), "name": name, "device": "desktop",
            "root": {"id": "root", "layout": "column", "component": target, "text": name},
        }],
    }
    other = [item["ref"] for item in brief["components"] if item["ref"] != target]
    other += [item["ref"] for item in brief["templates"] if item["ref"] != target]
    if other:
        answer["unsketched"] = [{"component": ref, "reason": "nested in the main page"} for ref in other]
    submit(capsys, tmp_path, brief["id"], answer)


def test_vue_route_template_brief_and_answer(make_repo, monkeypatch, capsys, tmp_path):
    root, brief = prepare(make_repo, monkeypatch, capsys, tmp_path, VUE_FILES)
    settings = next(item for item in brief["components"] if item["ref"] == "src/Settings.vue#Settings")
    assert settings["template_file"] == "src/Settings.vue"
    assert "<h1>Operations</h1>" in settings["template"]
    assert "Connection lost" in settings["template"] and "Open incidents" in settings["template"]
    assert settings["routes"] == ["/settings"]
    assert settings["renders"] == [
        "src/ActivityList.vue#ActivityList",
        "src/MetricCard.vue#MetricCard",
        "src/StatusBanner.vue#StatusBanner",
    ]
    assert any(item["component"] == settings["ref"] and item["route"] == "/settings" for item in brief["entries"])
    submit(capsys, tmp_path, brief["id"], {
        "input_hash": brief["input_hash"],
        "screens": [{
            "id": "settings", "name": "Operations", "device": "desktop",
            "root": {
                "id": "dashboard", "layout": "column", "component": settings["ref"],
                "children": [
                    {"id": "topbar", "layout": "row", "children": [
                        {"id": "title", "layout": "column", "style": ["heading"], "text": "Operations"},
                        {"id": "refresh", "layout": "row", "style": ["button"], "text": "Refresh"},
                    ]},
                    {"id": "tabs", "layout": "row", "style": ["tabs"], "text": "Overview  Alerts"},
                    {"id": "offline", "layout": "row", "component": "src/StatusBanner.vue#StatusBanner",
                     "style": ["banner"], "when": "offline", "text": "Connection lost"},
                    {"id": "content", "layout": "grid", "cols": 2, "children": [
                        {"id": "metric", "layout": "column", "component": "src/MetricCard.vue#MetricCard",
                         "style": ["card"], "text": "Open incidents\n12"},
                        {"id": "activity", "layout": "column", "component": "src/ActivityList.vue#ActivityList",
                         "style": ["list"], "text": "Recent activity\nDeployment finished\nAlert assigned"},
                    ]},
                    {"id": "drawer", "layout": "column", "style": ["panel"], "children": [
                        {"id": "drawer-title", "layout": "row", "style": ["heading"], "text": "Details"},
                        {"id": "close", "layout": "row", "style": ["button"], "text": "Close"},
                    ]},
                ],
            },
        }],
    })
    conn = sqlite3.connect(root / ".cbi" / "model.db")
    try:
        payload = build.concept_view(conn, root)
    finally:
        conn.close()
    assert payload["screens"][0]["root"]["component"] == settings["id"]


@pytest.mark.parametrize(
    ("files", "owned", "target", "kind", "route", "included", "renderer"),
    [
        (DJANGO_FILES, ("templates/dashboard.html",), "templates/dashboard.html", "Jinja/Django",
         "/dashboard/", "_nav.html", "views.py"),
        (RAZOR_FILES, ("Pages/Reports.cshtml",), "Pages/Reports.cshtml", "Razor",
         "/reports", "_Nav", None),
        (HTML_FILES, ("app/src/index.html",), "app/src/index.html", "HTML",
         "/", "renderer.js", "main.js"),
    ],
    ids=("django", "razor", "electron-html"),
)
def test_template_detection_brief_answer_and_viewer(
        make_repo, monkeypatch, capsys, tmp_path, files, owned, target, kind, route, included, renderer):
    root, brief = prepare(make_repo, monkeypatch, capsys, tmp_path, files, owned)
    page = next(item for item in brief["templates"] if item["ref"] == target)
    assert page["template_kind"] == kind and route in page["routes"]
    assert included in page["includes"]
    if renderer:
        assert renderer in page["rendered_by"]
    assert "tests/decoy.test.js" not in page["rendered_by"]
    assert all(item["ref"] != "src/render.html" for item in brief["templates"])
    assert all(not item["ref"].endswith(("_nav.html", "_Nav.cshtml", "base.html")) for item in brief["templates"])
    assert any(item["component"] == target and item.get("route") == route for item in brief["entries"])
    if kind == "HTML":
        submit(capsys, tmp_path, brief["id"], {
            "input_hash": brief["input_hash"],
            "screens": [{
                "id": "desktop", "name": "HTML", "device": "desktop",
                "root": {"id": "window", "layout": "column", "component": target, "children": [
                    {"id": "topbar", "layout": "row", "text": "Projects  Compare", "style": ["card"]},
                    {"id": "banner", "layout": "row", "text": "Judgement tasks waiting", "style": ["banner"]},
                    {"id": "workspace", "layout": "row", "children": [
                        {"id": "map", "layout": "column", "text": "Architecture map", "style": ["panel"]},
                        {"id": "drawer", "layout": "column", "text": "Details", "style": ["panel"]},
                    ]},
                ]},
            }],
        })
    else:
        accept_one(capsys, tmp_path, brief, target, kind)

    conn = sqlite3.connect(root / ".cbi" / "model.db")
    try:
        payload = build.concept_view(conn, root)
    finally:
        conn.close()
    screen = next(item for item in payload["screens"] if item["name"] == kind)
    assert screen["root"]["component"].endswith(":" + target)
    if kind == "HTML":
        assert [item["id"] for item in screen["root"]["children"]] == ["topbar", "banner", "workspace"]
        assert [item["id"] for item in screen["root"]["children"][2]["children"]] == ["map", "drawer"]
    leaf = payload["concepts"][0]
    virtual = next(item for item in leaf["symbols"] if item["id"] == screen["root"]["component"])
    assert virtual["kind"] == "component" and virtual["template"] is True


def test_detected_template_must_be_sketch_or_explained(make_repo, monkeypatch, capsys, tmp_path):
    _root, brief = prepare(
        make_repo, monkeypatch, capsys, tmp_path, HTML_FILES, ("app/src/index.html",),
    )
    path = tmp_path / "missing-template.json"
    path.write_text(json.dumps({"input_hash": brief["input_hash"], "screens": []}))
    code, _out, err = run(capsys, "submit", brief["id"], str(path))
    assert code == 2
    assert "screen templates not sketched or listed in unsketched: app/src/index.html" in err
