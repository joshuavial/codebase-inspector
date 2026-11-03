"""Unknown pytest registration and selection remain visible static boundaries."""
import sqlite3

from cbi.cli import main


def test_dynamic_pytest_registration_and_selection_are_explicit(make_repo, monkeypatch):
    root = make_repo({
        'tests/conftest.py': '''import pytest
pytest_plugins = choose_plugins()
generated = pytest.fixture(make_resource())
@pytest.fixture(name=choose_name())
def resource(): return 1
''',
        'tests/test_selection.py': '''def test_selection(request, resource_name):
    assert request.getfixturevalue(resource_name)
''',
    })
    monkeypatch.chdir(root)
    assert main(['init']) == 0 and main(['scan']) == 0
    with sqlite3.connect(root / '.cbi/model.db') as conn:
        rows = [d for (d,) in conn.execute("SELECT detail FROM diagnostics WHERE kind='unsupported_test_mechanism'")]
        assert any('dynamic_fixture_selection' in d and 'test_selection.py:2' in d for d in rows)
        assert any('dynamic_plugin_registration' in d and 'conftest.py:2' in d for d in rows)
        assert any('fixture_factory' in d and 'conftest.py:3' in d for d in rows)
        assert any('dynamic_fixture_name' in d and 'conftest.py:4' in d for d in rows)
        assert not conn.execute("SELECT 1 FROM edges WHERE kind='tests'").fetchone()
