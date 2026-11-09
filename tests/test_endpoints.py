"""Unit and CLI tests for Starlette/FastAPI Route extraction and Flask add_url_rule."""

import json

from cbi.cli import main
from cbi.parse import python


def test_starlette_route_parsing():
    code = """\
from starlette.routing import Route

def test_handler():
    return {"status": "ok"}

routes = [
    Route("/api/test", test_handler, methods=["GET", "POST"]),
]
"""
    defs, facts, err = python.parse(code.encode(), "python", False)
    assert not err
    routes = facts["http_routes"]
    assert len(routes) == 2
    assert routes[0][1] == "GET" and routes[0][2] == "/api/test"
    assert routes[1][1] == "POST" and routes[1][2] == "/api/test"
    assert routes[0][0] == 0  # defs index of test_handler
    assert routes[1][0] == 0
    assert routes[0][4] == "test_handler"
    assert routes[1][4] == "test_handler"


def test_starlette_route_default_get():
    code = """\
from starlette.routing import Route

def healthz():
    return "ok"

routes = [
    Route("/healthz", healthz),
]
"""
    defs, facts, err = python.parse(code.encode(), "python", False)
    assert not err
    routes = facts["http_routes"]
    assert len(routes) == 1
    assert routes[0][1] == "GET"
    assert routes[0][2] == "/healthz"
    assert routes[0][0] == 0  # defs index of healthz
    assert routes[0][4] == "healthz"


def test_websocket_route():
    code = """\
from starlette.routing import WebSocketRoute

async def ws_endpoint(websocket):
    await websocket.accept()

routes = [
    WebSocketRoute("/ws", ws_endpoint),
]
"""
    defs, facts, err = python.parse(code.encode(), "python", False)
    assert not err
    routes = facts["http_routes"]
    assert len(routes) == 1
    assert routes[0][1] == "WEBSOCKET"
    assert routes[0][2] == "/ws"
    assert routes[0][0] == 0  # defs index of ws_endpoint
    assert routes[0][4] == "ws_endpoint"


def test_starlette_route_kwargs_and_variations():
    code = """\
import starlette.routing
from fastapi.routing import APIRoute
from starlette.routing import Route, WebSocketRoute

def custom_handler():
    return {}

def items_handler():
    return []

def chat_endpoint(ws):
    pass

def ns_handler():
    return {}

def v2_handler():
    return {}

routes = [
    Route(path="/api/custom", endpoint=custom_handler, methods=["PUT", "DELETE"]),
    Route("/items", endpoint=items_handler),
    WebSocketRoute(path="/ws/chat", endpoint=chat_endpoint),
    starlette.routing.Route("/namespaced", ns_handler),
    APIRoute("/api/v2", v2_handler, methods=["POST"]),
]
"""
    defs, facts, err = python.parse(code.encode(), "python", False)
    assert not err
    routes = facts["http_routes"]
    route_tuples = [(r[1], r[2], r[4]) for r in routes]
    assert ("PUT", "/api/custom", "custom_handler") in route_tuples
    assert ("DELETE", "/api/custom", "custom_handler") in route_tuples
    assert ("GET", "/items", "items_handler") in route_tuples
    assert ("WEBSOCKET", "/ws/chat", "chat_endpoint") in route_tuples
    assert ("GET", "/namespaced", "ns_handler") in route_tuples
    assert ("POST", "/api/v2", "v2_handler") in route_tuples


def test_flask_add_url_rule():
    code = """\
from flask import Flask

app = Flask(__name__)

def users_list():
    return []

def orders_view():
    return []

def health_view():
    return "ok"

app.add_url_rule("/users", "users_list", users_list)
app.add_url_rule("/orders", view_func=orders_view, methods=["GET", "POST"])
app.add_url_rule("/health", view_func=health_view)
app.add_url_rule("/ping", endpoint="ping_endpoint")
"""
    defs, facts, err = python.parse(code.encode(), "python", False)
    assert not err
    routes = facts["http_routes"]
    route_tuples = [(r[1], r[2], r[3], r[4]) for r in routes]
    assert ("GET", "/users", "app", "users_list") in route_tuples
    assert ("GET", "/orders", "app", "orders_view") in route_tuples
    assert ("POST", "/orders", "app", "orders_view") in route_tuples
    assert ("GET", "/health", "app", "health_view") in route_tuples
    assert ("GET", "/ping", "app", "ping_endpoint") in route_tuples


def test_cli_endpoints_starlette_markdown_and_json(make_repo, monkeypatch, capsys):
    files = {
        "app.py": '''\
from starlette.applications import Starlette
from starlette.routing import Route, WebSocketRoute

def test_handler():
    """Handle test API requests."""
    return {"message": "ok"}

def healthz():
    """Health check endpoint."""
    return {"status": "healthy"}

def ws_endpoint(websocket):
    """WebSocket communication endpoint."""
    pass

routes = [
    Route("/api/test", test_handler, methods=["GET", "POST"]),
    Route("/healthz", healthz),
    WebSocketRoute("/ws", ws_endpoint),
]

app = Starlette(routes=routes)
''',
    }
    root = make_repo(files, name="starlette-repo")
    monkeypatch.chdir(root)
    assert main(["init"]) == 0
    assert main(["scan"]) == 0
    capsys.readouterr()

    # Markdown format
    assert main(["endpoints", "--format", "markdown"]) == 0
    md = capsys.readouterr().out
    assert "| Method | Route | Handler | Callers | Tables |" in md
    assert "| GET | /api/test | test_handler (app.py:4) | - | - |" in md
    assert "| POST | /api/test | test_handler (app.py:4) | - | - |" in md
    assert "| GET | /healthz | healthz (app.py:8) | - | - |" in md
    assert "| WEBSOCKET | /ws | ws_endpoint (app.py:12) | - | - |" in md

    # JSON format
    assert main(["endpoints", "--format", "json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert "endpoints" in data
    assert len(data["endpoints"]) == 4

    endpoints_map = {(ep["method"], ep["path"]): ep for ep in data["endpoints"]}
    assert ("GET", "/api/test") in endpoints_map
    assert ("POST", "/api/test") in endpoints_map
    assert ("GET", "/healthz") in endpoints_map
    assert ("WEBSOCKET", "/ws") in endpoints_map

    assert endpoints_map[("GET", "/api/test")]["handler"]["name"] == "test_handler"
    assert endpoints_map[("POST", "/api/test")]["handler"]["name"] == "test_handler"
    assert endpoints_map[("GET", "/healthz")]["handler"]["name"] == "healthz"
    assert endpoints_map[("WEBSOCKET", "/ws")]["handler"]["name"] == "ws_endpoint"

    # Text format
    assert main(["endpoints", "--format", "text"]) == 0
    text_out = capsys.readouterr().out
    assert "GET    /api/test" in text_out
    assert "POST   /api/test" in text_out
    assert "GET    /healthz" in text_out
    assert "WEBSOCKET /ws" in text_out

    # Filter by method
    assert main(["endpoints", "--method", "WEBSOCKET", "--json"]) == 0
    ws_data = json.loads(capsys.readouterr().out)
    assert len(ws_data["endpoints"]) == 1
    assert ws_data["endpoints"][0]["method"] == "WEBSOCKET"
    assert ws_data["endpoints"][0]["path"] == "/ws"


def test_starlette_methods_tuple_set_and_lambda():
    code = """\
from starlette.routing import Route, WebSocketRoute

routes = [
    Route("/tuple", lambda: None, methods=("GET", "POST")),
    Route("/set", lambda: None, methods={"DELETE"}),
    Route("/anon", lambda: None),
]
"""
    defs, facts, err = python.parse(code.encode(), "python", False)
    assert not err
    routes = facts["http_routes"]
    tuples = [(r[1], r[2]) for r in routes]
    assert ("GET", "/tuple") in tuples
    assert ("POST", "/tuple") in tuples
    assert ("DELETE", "/set") in tuples
    assert ("GET", "/anon") in tuples


def test_starlette_class_and_attribute_binding():
    code = """\
from starlette.routing import Route
import views

class Controller:
    def handle_req(self):
        return {}

    def get_routes(self):
        return [
            Route("/ctrl", self.handle_req),
            Route("/external", views.external_func),
        ]
"""
    defs, facts, err = python.parse(code.encode(), "python", False)
    assert not err
    routes = facts["http_routes"]
    # Controller.handle_req is in defs
    ctrl_route = next(r for r in routes if r[2] == "/ctrl")
    assert ctrl_route[0] is not None
    assert defs[ctrl_route[0]]["name"] == "handle_req"
    assert ctrl_route[4] == "self.handle_req"

    ext_route = next(r for r in routes if r[2] == "/external")
    assert ext_route[0] is None
    assert ext_route[4] == "views.external_func"

