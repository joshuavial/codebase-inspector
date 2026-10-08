"""Cypress specs, Vue and React route records, and the typeof-import parse workaround."""

import json
import sqlite3

from cbi.cli import main
from cbi.parse import typescript

VUE = '<script lang="ts">\nexport default function {name}() {{ return 1 }}\n</script>\n'

ROUTER = """\
import { createRouter } from "vue-router";
import SignIn from "./pages/SignIn.vue";
import Notes from "./pages/Notes.vue";
import Note from "./pages/Note.vue";
import Flags from "./pages/Flags.vue";
import Child from "./pages/Child.vue";

export const router = createRouter({
  routes: [
    { path: "/", redirect: "/notes" },
    { path: "/sign-in", component: SignIn, meta: { public: true } },
    { path: "/notes", component: Notes },
    { path: "/notes/:id", component: Note },
    { path: "/flags", component: Flags, meta: { flag: "flag-view" } },
    { path: "/lazy", component: () => import("./pages/Lazy.vue") },
    {
      path: "/nested",
      children: [{ path: "child", component: Child, beforeEnter(to, from, next) { next("/login"); } }],
    },
  ],
});

router.beforeEach(async (to) => {
  if (to.meta.public) return true;
  if (!(await loadCurrentUser())) return "/sign-in";
  if (typeof to.meta.flag === "string" && !isOn(to.meta.flag)) return "/notes";
  return true;
});
"""

ROUTES = """\
import { Route, Navigate, createBrowserRouter } from "react-router-dom";
import App from "./App";
import Home from "./Home";
import AccountPage from "./AccountPage";
import Detail from "./Detail";

export function RouteGuard(props: { children: unknown }) {
  return props.children;
}

export const routes = (
  <Route element={<App />}>
    <Route index element={<Home />} />
    <Route path="/add-org" element={<Navigate to="/onboarding?new=true" replace />} />
    <Route path="/account" element={<RouteGuard><AccountPage /></RouteGuard>} />
  </Route>
);

createBrowserRouter([
  { path: "/items", element: <Detail />, children: [{ path: ":id", Component: Detail }] },
]);
"""

PAGE = "export default function {name}() {{ return <div /> }}\n"

COMMANDS = """\
Cypress.Commands.add("signIn", (role: string) => {
  cy.request("POST", "/api/auth/sign-in", { role });
});
"""

SPEC = """\
describe("notes", () => {
  it("opens a note", () => {
    cy.signIn("manager");
    cy.visit("/notes");
    cy.visit(`/notes/${noteId}`);
  });
  context("home", () => {
    specify("root", () => {
      cy.visit("/");
    });
  });
});
"""

LEASE_FORM = """\
import { describe, it, vi } from "vitest";

vi.mock("../api", async importOriginal => {
  const actual = await importOriginal<typeof import("../api")>();
  return { ...actual };
});

describe("NoteForm", () => {
  it("lists", () => {});
});
"""

FILES = {
    "src/pages/SignIn.vue": VUE.format(name="SignIn"),
    "src/pages/Notes.vue": VUE.format(name="Notes"),
    "src/pages/Note.vue": VUE.format(name="Note"),
    "src/pages/Flags.vue": VUE.format(name="Flags"),
    "src/pages/Lazy.vue": VUE.format(name="Lazy"),
    "src/pages/Child.vue": VUE.format(name="Child"),
    "src/router.ts": ROUTER,
    "src/App.tsx": PAGE.format(name="App"),
    "src/Home.tsx": PAGE.format(name="Home"),
    "src/AccountPage.tsx": PAGE.format(name="AccountPage"),
    "src/Detail.tsx": PAGE.format(name="Detail"),
    "src/routes.tsx": ROUTES,
    "src/api.ts": "export function api() { return 1 }\n",
    "src/NoteForm.spec.ts": LEASE_FORM,
    "cypress/support/commands.ts": COMMANDS,
    "cypress/support/e2e.ts": "import \"./commands\";\n",
    "cypress/e2e/notes.cy.ts": SPEC,
}


def test_typeof_import_call_parses():
    defs, _facts, err = typescript.parse(LEASE_FORM.encode(), "typescript", True)
    assert not err
    assert {d["name"] for d in defs if d["kind"] == "test"} >= {"NoteForm", "lists"}


def test_object_methods_are_not_routes():
    defs, facts, err = typescript.parse(b"export const api = { saveItem() { return 1 } }\n", "typescript", False)
    assert not err
    assert [d["display_kind"] for d in defs if d["display_kind"] == "route"] == []
    assert "routes" not in facts


def test_routes_cypress_and_orphans(make_repo, monkeypatch, capsys):
    root = make_repo(FILES, name="routes")
    monkeypatch.chdir(root)
    assert main(["init"]) == 0 and main(["scan"]) == 0
    capsys.readouterr()
    conn = sqlite3.connect(root / ".cbi" / "model.db")

    cy = conn.execute(
        "SELECT display_kind, attrs FROM nodes WHERE kind = 'file' AND path = 'cypress/e2e/notes.cy.ts'"
    ).fetchone()
    assert cy[0] == "test file"
    assert json.loads(cy[1])["role"] == "test"
    support = json.loads(conn.execute(
        "SELECT attrs FROM nodes WHERE kind = 'file' AND path = 'cypress/support/commands.ts'"
    ).fetchone()[0])
    assert support["role"] == "code"

    tests = {(kind, name) for kind, name in conn.execute(
        "SELECT display_kind, name FROM nodes WHERE path = 'cypress/e2e/notes.cy.ts' AND kind = 'test'")}
    assert tests == {
        ("test suite", "notes"), ("test case", "opens a note"),
        ("test suite", "home"), ("test case", "root"),
    }
    lease_form = {name for (name,) in conn.execute(
        "SELECT name FROM nodes WHERE path = 'src/NoteForm.spec.ts' AND kind = 'test'")}
    assert {"NoteForm", "lists"} <= lease_form
    assert conn.execute(
        "SELECT 1 FROM diagnostics d JOIN nodes n ON n.id = d.node_id "
        "WHERE d.kind = 'parse_error' AND n.path = 'src/NoteForm.spec.ts'"
    ).fetchone() is None

    routes = {
        name: json.loads(attrs) if attrs else {}
        for name, attrs in conn.execute(
            "SELECT name, attrs FROM nodes WHERE display_kind = 'route' AND path = 'src/router.ts'")
    }
    assert routes["/sign-in"]["path"] == "/sign-in"
    assert "guard" not in routes["/sign-in"]
    assert routes["/"]["redirect"] == "/notes"
    assert routes["/notes"]["guard"] == ["/sign-in"]
    assert routes["/flags"]["guard"] == ["/sign-in", "/notes"]
    assert routes["/lazy"]["path"] == "/lazy"
    assert routes["/nested/child"]["guard"] == ["/login", "/sign-in"]
    parents = {parent for (parent,) in conn.execute(
        "SELECT parent_id FROM nodes WHERE display_kind = 'route' AND path = 'src/router.ts'")}
    assert parents == {"local:routes:src/router.ts"}

    react = {
        name: json.loads(attrs) if attrs else {}
        for name, attrs in conn.execute(
            "SELECT name, attrs FROM nodes WHERE display_kind = 'route' AND path = 'src/routes.tsx'")
    }
    assert react["layout:App"] == {}
    assert react["/"]["path"] == "/"
    assert react["/add-org"]["redirect"] == "/onboarding"
    assert react["/account"]["path"] == "/account"
    assert react["/items"]["path"] == "/items"
    assert react["/items/:id"]["path"] == "/items/:id"

    def renders(src):
        return {dst.split("#", 1)[1] for (dst,) in conn.execute(
            "SELECT dst FROM edges WHERE kind = 'calls' AND src = ? AND attrs = '{\"via\": \"jsx\"}'", (src,))}

    file_id = "local:routes:src/router.ts"
    assert "Notes" in renders(f"{file_id}#/notes")
    assert "Lazy" in renders(f"{file_id}#/lazy")
    assert conn.execute(
        "SELECT 1 FROM edges WHERE kind = 'imports' AND src = ? AND dst = ?",
        (file_id, "local:routes:src/pages/Lazy.vue"),
    ).fetchone()
    react_id = "local:routes:src/routes.tsx"
    assert "App" in renders(f"{react_id}#layout:App")
    assert "Home" in renders(f"{react_id}#/")
    assert {"RouteGuard", "AccountPage"} <= renders(f"{react_id}#/account")
    assert "Detail" in renders(f"{react_id}#/items")
    assert "Detail" in renders(f"{react_id}#/items/:id")

    def tested(case):
        return {name for (name,) in conn.execute(
            "SELECT dst.name FROM edges e "
            "JOIN nodes src ON src.id = e.src JOIN nodes dst ON dst.id = e.dst "
            "WHERE e.kind = 'tests' AND src.path = ? AND src.name = ?",
            ("cypress/e2e/notes.cy.ts", case))}

    assert "Notes" in tested("opens a note")
    assert "Note" in tested("opens a note")
    assert "Notes" in tested("root")
    assert conn.execute(
        "SELECT 1 FROM edges e JOIN nodes src ON src.id = e.src JOIN nodes dst ON dst.id = e.dst "
        "WHERE e.kind = 'calls' AND src.name = 'opens a note' AND dst.name = 'signIn' "
        "AND dst.path = 'cypress/support/commands.ts'"
    ).fetchone()

    capsys.readouterr()
    assert main(["show", f"{file_id}#/flags"]) == 0
    shown = capsys.readouterr().out
    assert "guard: /sign-in, /notes" in shown
    assert main(["show", f"{file_id}#/"]) == 0
    assert "redirect: /notes" in capsys.readouterr().out

    code = main(["orphans", "--json"])
    orphans = json.loads(capsys.readouterr().out)
    assert code == 0
    assert "cypress/e2e/notes.cy.ts" not in {row["path"] for row in orphans["unreferenced"]}
    code = main(["hotspots", "--json", "--limit", "50"])
    spots = json.loads(capsys.readouterr().out)
    assert code == 0
    assert "cypress/e2e/notes.cy.ts" not in {row["path"] for row in spots["files"]}
    cypress = next(row for row in spots["folders"] if row["path"] == "cypress")
    assert cypress["test_files"] >= 1
