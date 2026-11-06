"""Missing static consumers describe resolution boundaries, not dead routes."""
import json
import sqlite3

from cbi.cli import main


def test_route_resolution_boundaries(make_repo, monkeypatch, capsys):
    root = make_repo({
        'server.py': '''from fastapi import FastAPI
app = FastAPI()
@app.post("/webhooks/events")
def callback(): pass
@app.get("/admin/books/{id}/revisions")
def revisions(id): pass
@app.get("/quiet")
def quiet(): pass
''',
        'client.ts': '''export function revisions(resource, id) {
 return fetch(`/admin/${resource}/${id}/revisions`);
}
''',
    })
    monkeypatch.chdir(root)
    assert main(['init']) == 0
    assert main(['scan']) == 0
    capsys.readouterr()
    with sqlite3.connect(root / '.cbi/model.db') as conn:
        details = [r[0] for r in conn.execute("SELECT detail FROM diagnostics WHERE kind='unmatched_http_call'")]
    assert any('external_callback_candidate' in d and '/webhooks/events' in d for d in details)
    assert any('dynamic_client' in d and '/admin/books/' in d for d in details)
    assert any('static_unresolved' in d and '/quiet' in d for d in details)
    assert all('no client call' not in d for d in details)
    assert main(['status', '--json']) == 0
    result = json.loads(capsys.readouterr().out)
    assert result['diagnostics']['unmatched_http_call']['resolution_boundaries'] == {
        'dynamic_client': 2, 'external_callback_candidate': 1, 'static_unresolved': 1,
    }
