"""In-process HTTP calls bind only to their selected application's routes."""

import sqlite3

from cbi.cli import main


def _links(root):
    with sqlite3.connect(root / ".cbi/model.db") as conn:
        return {(src, dst) for src, dst in conn.execute(
            "SELECT s.name,d.name FROM edges e JOIN nodes s ON s.id=e.src "
            "JOIN nodes d ON d.id=e.dst WHERE e.kind='tests' AND d.kind='symbol'")}


def test_testclient_calls_select_the_application_and_mounted_router(make_repo, monkeypatch):
    root = make_repo({
        "routes.py": '''from fastapi import APIRouter
router = APIRouter(prefix="/items")
@router.get("/{item_id}")
def read_item(item_id): return {}
@router.post("/")
def create_item(): return {}
''',
        "server.py": '''from fastapi import FastAPI
from routes import router
app = FastAPI()
app.include_router(router, prefix="/v1")
other = FastAPI()
@other.get("/v1/items/{item_id}")
def unrelated(item_id): return {}
''',
        "tests/test_requests.py": '''from fastapi.testclient import TestClient as Client
from server import app

def test_read():
    with Client(app) as client:
        assert client.get("/v1/items/42").status_code == 200

def test_remote():
    import requests
    requests.get("https://example.com/v1/items/42")
''',
    })
    monkeypatch.chdir(root)
    assert main(["init"]) == 0 and main(["scan"]) == 0
    assert ("test_read", "read_item") in _links(root)
    assert ("test_read", "unrelated") not in _links(root)
    assert ("test_remote", "read_item") not in _links(root)


def test_fixture_client_uses_selected_app_and_rejects_mock_apps(make_repo, monkeypatch):
    root = make_repo({
        "server.py": '''from fastapi import FastAPI
app = FastAPI()
@app.get("/ready")
def ready(): return {}
''',
        "tests/conftest.py": '''import pytest
from fastapi.testclient import TestClient
from server import app

@pytest.fixture(name="api_client")
def client_fixture():
    with TestClient(app) as instance:
        yield instance
''',
        "tests/test_requests.py": '''from fastapi import FastAPI
from fastapi.testclient import TestClient

def test_ready(api_client):
    api_client.get("/ready")

def test_mock():
    app = FastAPI()
    client = TestClient(app)
    client.get("/ready")
''',
    })
    monkeypatch.chdir(root)
    assert main(["init"]) == 0 and main(["scan"]) == 0
    assert ("test_ready", "ready") in _links(root)
    assert ("test_mock", "ready") not in _links(root)


def test_dynamic_inprocess_boundaries_are_explicit(make_repo, monkeypatch):
    root = make_repo({
        "server.py": '''from fastapi import FastAPI
app = FastAPI()
@app.get("/ready")
def ready(): return {}
''',
        "tests/test_requests.py": '''from fastapi.testclient import TestClient
from server import app

def test_dynamic_url(path):
    client = TestClient(app)
    client.get(path)

def test_dynamic_app(factory):
    client = TestClient(factory())
    client.get("/ready")
''',
    })
    monkeypatch.chdir(root)
    assert main(["init"]) == 0 and main(["scan"]) == 0
    with sqlite3.connect(root / ".cbi/model.db") as conn:
        details = [row[0] for row in conn.execute(
            "SELECT detail FROM diagnostics WHERE kind='unsupported_test_mechanism'")]
    assert any("test_requests.py:6" in detail and "resolution=dynamic_url" in detail for detail in details)
    assert any("test_requests.py:9" in detail and "resolution=dynamic_app" in detail for detail in details)
    assert not _links(root)


def test_parameters_and_local_clients_do_not_reuse_global_apps(make_repo, monkeypatch):
    root = make_repo({
        "server.py": '''from fastapi import FastAPI
app = FastAPI()
@app.get("/ready")
def ready(): return {}
''',
        "tests/test_requests.py": '''import pytest
from fastapi.testclient import TestClient
from server import app

application = app
client = TestClient(application)

class FakeClient:
    def get(self, path): return {}

@pytest.mark.parametrize("client", [FakeClient()])
def test_parameter_client(client):
    client.get("/ready")

@pytest.mark.parametrize("application", [object()])
def test_parameter_app(application):
    TestClient(application).get("/ready")

def test_local_client():
    client = FakeClient()
    client.get("/ready")

def test_before_local_assignment():
    client.get("/ready")
    client = FakeClient()

def test_conditional_client(flag):
    client = TestClient(application)
    if flag:
        client = FakeClient()
    client.get("/ready")

def test_conditional_app(flag):
    selected = application
    if flag:
        selected = object()
    TestClient(selected).get("/ready")

def test_actual_global():
    client.get("/ready")
''',
    })
    monkeypatch.chdir(root)
    assert main(["init"]) == 0 and main(["scan"]) == 0
    links = _links(root)
    assert ("test_actual_global", "ready") in links
    assert ("test_parameter_client", "ready") not in links
    assert ("test_parameter_app", "ready") not in links
    assert ("test_local_client", "ready") not in links
    assert ("test_before_local_assignment", "ready") not in links
    assert ("test_conditional_client", "ready") not in links
    assert ("test_conditional_app", "ready") not in links


def test_unused_nested_definitions_do_not_replace_test_or_fixture_bodies(make_repo, monkeypatch):
    root = make_repo({
        "server.py": '''from fastapi import FastAPI
app = FastAPI()
@app.get("/ready")
def ready(): return {}
other = FastAPI()
@other.get("/admin")
def admin(): return {}
''',
        "tests/conftest.py": '''import pytest
from fastapi.testclient import TestClient
from server import app, other

@pytest.fixture
def api_client():
    def unused_fixture_helper():
        TestClient(other).get("/admin")
    return TestClient(app)
''',
        "tests/test_requests.py": '''import pytest
from fastapi.testclient import TestClient
from server import other

def test_actual_request(api_client):
    api_client.get("/ready")
    def unused_test_helper():
        TestClient(other).get("/admin")

@pytest.mark.usefixtures("api_client")
def test_fixture_request(api_client):
    api_client.get("/ready")
''',
    })
    monkeypatch.chdir(root)
    assert main(["init"]) == 0 and main(["scan"]) == 0
    links = _links(root)
    assert ("test_actual_request", "ready") in links
    assert ("test_fixture_request", "ready") in links
    assert ("test_actual_request", "admin") not in links
    assert ("test_fixture_request", "admin") not in links
