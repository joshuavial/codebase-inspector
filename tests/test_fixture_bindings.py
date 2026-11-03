"""Pytest registration is a static path to production, without executing pytest."""

import json
import sqlite3

from cbi.cli import main


def _scan(make_repo, monkeypatch, files):
    root = make_repo(files)
    monkeypatch.chdir(root)
    assert main(["init"]) == 0 and main(["scan"]) == 0
    return sqlite3.connect(root / ".cbi/model.db")


def _targets(conn, case):
    return {dst.rsplit(":", 1)[-1]: (confidence, json.loads(attrs or "{}"))
            for dst, confidence, attrs in conn.execute(
                "SELECT dst, confidence, attrs FROM edges WHERE kind = 'tests' AND src LIKE ?", ("%#" + case,))}


def test_registered_plugin_fixture_dependencies_and_import_alias(make_repo, monkeypatch):
    conn = _scan(make_repo, monkeypatch, {
        "production.py": "def prepare(): return 1\n",
        "support/__init__.py": "",
        "support/plugin.py": "import pytest\nfrom production import prepare\n@pytest.fixture(name='seed')\ndef setup_seed():\n    return prepare()\n",
        "support/wrappers.py": "from pytest import fixture as resource\n@resource\ndef wrapped(seed): return seed\n",
        "tests/conftest.py": "pytest_plugins = ['support.plugin']\nfrom support.wrappers import wrapped as storage\n",
        "tests/test_flow.py": "def test_registered(storage):\n    assert storage\n",
    })
    targets = _targets(conn, "test_registered")
    assert targets["production.py#prepare"][0] == 1.0
    assert targets["production.py#prepare"][1]["via"] == "fixture"
    assert not conn.execute("SELECT 1 FROM diagnostics WHERE kind = 'unmatched_test' AND node_id LIKE '%test_flow.py'").fetchone()


def test_fixture_scope_marks_and_autouse_reads(make_repo, monkeypatch):
    conn = _scan(make_repo, monkeypatch, {
        "production.py": "def root(): return 1\ndef local(): return 2\n",
        "schema.sql": "CREATE TABLE records (id INTEGER);\n",
        "tests/conftest.py": "import pytest\nfrom production import root\n@pytest.fixture\ndef store(): return root()\n@pytest.fixture(autouse=True)\ndef schema_contract():\n    return open('../schema.sql').read()\n",
        "tests/nested/conftest.py": "from pytest import fixture\nfrom production import local\n@fixture\ndef store(): return local()\n",
        "tests/nested/test_flow.py": "import pytest\npytestmark = pytest.mark.usefixtures('store')\ndef test_module_mark(): pass\nclass TestGroup:\n    @pytest.fixture(name='inside')\n    def setup(self, store): return store\n    @pytest.mark.usefixtures('inside')\n    def test_class(self): pass\n",
        "tests/test_root.py": "import pytest\n@pytest.mark.usefixtures('store')\ndef test_root_mark(): pass\n",
    })
    for case in ("test_module_mark", "TestGroup > test_class"):
        targets = _targets(conn, case)
        assert "production.py#local" in targets and "production.py#root" not in targets
        assert "schema.sql" in targets
    targets = _targets(conn, "test_root_mark")
    assert "production.py#root" in targets and "production.py#local" not in targets


def test_empty_and_unregistered_fixtures_do_not_hide_missing_binding(make_repo, monkeypatch):
    conn = _scan(make_repo, monkeypatch, {
        "production.py": "def run(): pass\n",
        "support.py": "import pytest\nfrom production import run\n@pytest.fixture\ndef secret(): return run()\n",
        "tests/conftest.py": "import pytest\n@pytest.fixture\ndef empty(): return 1\n",
        "tests/test_empty.py": "def test_no_code(empty): assert empty\n",
        "tests/test_unregistered.py": "def test_no_registration(secret): assert secret\n",
    })
    assert not _targets(conn, "test_no_code")
    assert not _targets(conn, "test_no_registration")
    paths = {row[0].rsplit(":", 1)[-1] for row in conn.execute("SELECT node_id FROM diagnostics WHERE kind = 'unmatched_test'")}
    assert {"tests/test_empty.py", "tests/test_unregistered.py"} <= paths


def test_explicit_fixture_alias_and_transitive_helper_and_class_mark(make_repo, monkeypatch):
    conn = _scan(make_repo, monkeypatch, {
        "production.py": "def execute(): return 1\n",
        "support/plugin.py": "import pytest\nfrom production import execute\ndef helper(): return execute()\n@pytest.fixture(name='resource')\ndef build(): return helper()\n",
        "support/__init__.py": "",
        "tests/conftest.py": "from support.plugin import build as renamed\n",
        "tests/test_class.py": "import pytest\n@pytest.mark.usefixtures('resource')\nclass TestResources:\n    def test_contract(self): pass\n",
    })
    targets = _targets(conn, "TestResources > test_contract")
    assert "production.py#execute" in targets
    assert targets["production.py#execute"][1]["via"] == "fixture"


def test_literal_request_fixture_and_direct_parameter_shadowing(make_repo, monkeypatch):
    conn = _scan(make_repo, monkeypatch, {
        "production.py": "def run(): return 1\n",
        "tests/conftest.py": "import pytest\nfrom production import run\n@pytest.fixture\ndef store(): return run()\n@pytest.fixture\ndef wrapper(request): return request.getfixturevalue('store')\n",
        "tests/test_request.py": "def test_requested(request):\n    assert request.getfixturevalue('wrapper')\n",
        "tests/test_parameter.py": "import pytest\n@pytest.mark.parametrize('store', [1])\ndef test_direct(store): assert store\n@pytest.mark.parametrize('store', [1], indirect=True)\ndef test_indirect(store): assert store\n",
        "tests/test_module_parameter.py": "import pytest\npytestmark = pytest.mark.parametrize('store', [1])\ndef test_module_direct(store): assert store\n",
        "tests/test_class_parameter.py": "import pytest\n@pytest.mark.parametrize('store', [1])\nclass TestDirect:\n    def test_class_direct(self, store): assert store\n",
    })
    for case in ("test_requested", "test_indirect"):
        assert "production.py#run" in _targets(conn, case)
    for case in ("test_direct", "test_module_direct", "TestDirect > test_class_direct"):
        assert not _targets(conn, case)


def test_fixture_local_paths_and_migration_globs_remain_case_specific(make_repo, monkeypatch):
    conn = _scan(make_repo, monkeypatch, {
        "db/schema.sql": "CREATE TABLE records (id INT);\n",
        "db/migrations/001_table.sql": "CREATE TABLE revisions (id INT);\n",
        "db/unrelated.sql": "SELECT 1;\n",
        "support/__init__.py": "",
        "support/contracts.py": "from pathlib import Path\nimport pytest\n@pytest.fixture\ndef schema():\n    root = Path(__file__).parents[1]\n    path = root / 'db' / 'schema.sql'\n    return path.read_text()\n@pytest.fixture\ndef migrations():\n    root = Path(__file__).parents[1]\n    directory = root / 'db' / 'migrations'\n    return list(directory.glob('*.sql'))\n@pytest.fixture\ndef unused():\n    root = Path(__file__).parents[1]\n    path = root / 'db' / 'unrelated.sql'\n    return path.read_text()\n",
        "tests/conftest.py": "pytest_plugins = ['support.contracts']\n",
        "tests/test_contracts.py": "def test_schema(schema): assert schema\ndef test_migrations(migrations): assert migrations\n",
    })
    assert set(_targets(conn, "test_schema")) == {"db/schema.sql"}
    assert set(_targets(conn, "test_migrations")) == {"db/migrations/001_table.sql"}
    assert _targets(conn, "test_schema")["db/schema.sql"][1]["via"] == "fixture"


def test_non_autouse_overrides_do_not_inherit_autouse_registration(make_repo, monkeypatch):
    conn = _scan(make_repo, monkeypatch, {
        "production.py": "def original(): return 1\ndef replacement(): return 2\n",
        "tests/conftest.py": "import pytest\nfrom production import original\n@pytest.fixture(autouse=True)\ndef db(): return original()\n",
        "tests/test_module.py": "import pytest\nfrom production import replacement\n@pytest.fixture\ndef db(): return replacement()\ndef test_unrequested(): pass\ndef test_requested(db): assert db\n",
        "tests/test_class.py": "import pytest\nfrom production import replacement\nclass TestOverride:\n    @pytest.fixture\n    def db(self): return replacement()\n    def test_class_unrequested(self): pass\n    def test_class_requested(self, db): assert db\n",
        "tests/test_default.py": "def test_still_autouse(): pass\n",
    })
    assert not _targets(conn, "test_unrequested")
    assert not _targets(conn, "TestOverride > test_class_unrequested")
    assert "production.py#replacement" in _targets(conn, "test_requested")
    assert "production.py#replacement" in _targets(conn, "TestOverride > test_class_requested")
    assert "production.py#original" in _targets(conn, "test_still_autouse")
