from cbi.files import Ignore, classify, cs_test_roots, doc_collections


def test_ignore_follows_gitignore_rules():
    ignore = Ignore("# comment\nfixtures/\ndist*/\n/data/\n*.min.js\ndocs/**/draft.md\n!keep.min.js\n")
    assert ignore("a/fixtures/x.ts")
    assert ignore("dist-electron/main.js")
    assert ignore("data/1.json")
    assert not ignore("src/data/1.json")  # anchored to the root
    assert ignore("lib/x.min.js")
    assert not ignore("keep.min.js")  # negation
    assert ignore("docs/a/b/draft.md") and ignore("docs/draft.md")
    assert not ignore("fixtures")  # dir-only rule does not match a file of that name
    assert ignore("fixtures", is_dir=True)
    assert not Ignore("")("anything")


def test_classify():
    assert classify("src/app.ts") == ("code", "typescript")
    assert classify("src/app.test.tsx") == ("test", "tsx")
    assert classify("src/__tests__/x.js") == ("test", "javascript")
    assert classify("tests/test_util.py") == ("test", "python")
    assert classify("tests/conftest.py") == ("code", "python")
    assert classify("README.md") == ("doc", "markdown")
    assert classify("logo.png") == ("other", None)
    assert classify("src/App.cs") == ("code", "csharp")
    assert classify("src/App.vue") == ("code", "vue")
    assert classify("tests/WidgetTests.cs") == ("test", "csharp")
    assert classify("src/Greatest.cs") == ("code", "csharp")
    assert classify("src/contest.cs") == ("code", "csharp")
    assert classify("src/Widget.cs", ["src"]) == ("test", "csharp")
    assert classify("src/__tests__/A.vue") == ("test", "vue")
    assert classify("e2e/cypress/e2e/invoices.cy.ts") == ("test", "typescript")
    assert classify("cypress/e2e/smoke.cy.js") == ("test", "javascript")
    assert classify("cypress/e2e/plain.ts") == ("test", "typescript")
    assert classify("cypress/support/commands.ts") == ("code", "typescript")
    assert classify("cypress/e2e.ts") == ("code", "typescript")


def test_cs_test_roots_are_test_project_directories():
    assert cs_test_roots([
        "App.Tests/App.Tests.csproj", "Tests.csproj", "lib/demo.tests.csproj", "App/App.csproj",
        "Support.Testing/Support.Testing.csproj",
        "tests/App.IntegrationTests/App.IntegrationTests.csproj",
        "tests/App.UnitTests/App.UnitTests.csproj",
    ]) == [
        "tests/App.IntegrationTests", "tests/App.UnitTests", "Support.Testing", "App.Tests", "lib",
    ]
    roots = cs_test_roots(["tests/App.IntegrationTests/App.IntegrationTests.csproj"])
    assert classify("tests/App.IntegrationTests/ApiFactory.cs", roots) == ("test", "csharp")
    assert classify("src/Program.cs", roots) == ("code", "csharp")


def test_doc_collection_is_over_100_files_mostly_markdown_and_little_code():
    notes = [f"docs/notes/n{i}.md" for i in range(101)]
    assert doc_collections(notes + ["src/a.py"]) == {"docs"}
    assert doc_collections(notes[:100]) == set()
    assert doc_collections(notes + [f"docs/x{i}.py" for i in range(12)]) == {"docs/notes"}
    # research artefacts that are not code do not stop the collapse
    assert doc_collections(notes + [f"docs/notes/r{i}.log" for i in range(30)]) == {"docs"}
    assert doc_collections([f"img/{i}.png" for i in range(150)]) == set()
