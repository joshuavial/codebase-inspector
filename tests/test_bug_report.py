"""Public drafts contain only user text and a small runtime environment."""
from urllib.parse import parse_qs, urlparse

import pytest

from cbi import bug_report, cli, open_link


def fields(url):
    return parse_qs(urlparse(url).query, keep_blank_values=True)


def test_fields_and_encoding():
    url = bug_report.build_url(version="0.1.0", title="Broken & slow?", message="α + β\n#help = yes")
    data = fields(url)
    assert url.startswith(bug_report.ISSUE_URL + "?")
    assert data["template"] == ["bug_report.yml"]
    assert data["title"] == ["Broken & slow?"]
    assert data["happened"] == ["α + β\n#help = yes"]
    assert set(data) == {"template", "title", "happened", "environment"}
    env = data["environment"][0].splitlines()
    assert len(env) == 5
    assert env[0] == "cbi: 0.1.0"
    assert env[-1] == "Command or view: cbi bug"
    assert all(line.split(":", 1)[0] in {"cbi", "OS", "Architecture", "Python", "Command or view"} for line in env)


@pytest.mark.parametrize("text", [
    "failed /Users/fake/private-repo/source.py and /srv/repos/secret/db.sql",
    'failed "/Users/fake/my repo/source.py"',
    r"failed C:\Users\fake\repo\secret.ts and \\server\share\repo.sql",
    "failed ~/repo/model.json",
    "failed file:///fake/repo/source.html",
])
def test_paths(text):
    clean = bug_report.strip_paths(text)
    assert "<path>" in clean
    assert not any(word in clean for word in ("fake", "secret", "source", "model", "repo", "server"))


def test_real_home_and_error_are_private():
    text = f"Layout failed: {bug_report.Path.home()}/secret-repo/main.py /tmp/repo/db.sql"
    clean = fields(bug_report.build_url(version="0.1.0", error=text))["happened"][0]
    assert "Layout failed" in clean
    assert "<path>" in clean
    assert "repo" not in clean and "main.py" not in clean


def test_automatic_error_cannot_copy_repository_content():
    text = "Layout failed: concept SecretBilling table invoices API_KEY=secret https://private.example code()"
    clean = bug_report.safe_error(text)
    assert "Layout failed" in clean
    for private in ("SecretBilling", "invoices", "API_KEY", "secret", "private.example", "code()"):
        assert private not in clean
    assert "<detail>" in clean


@pytest.mark.parametrize("message", ["x" * 20000, "🦄 &+?\n" * 3000], ids=["ascii", "emoji"])
def test_encoded_length_cap(message):
    url = bug_report.build_url(version="0.1.0", title="🦄" * 300, message=message)
    assert len(url) <= bug_report.MAX_URL
    assert fields(url)["happened"][0].endswith(bug_report.TRIMMED)
    assert fields(url)["environment"][0].endswith("Command or view: cbi bug")


def test_app_environment():
    env = fields(bug_report.build_url(version="0.1.0", app_version="0.2.0", view="Map"))["environment"][0]
    assert "App: 0.2.0\n" in env
    assert env.endswith("Command or view: Map")


def test_cli_print_does_not_open_or_need_repository(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(open_link, "open_url", lambda _: pytest.fail("opened browser"))
    assert cli.main(["bug", "--print", "--title", "Oops", "--message", "It broke"]) == 0
    data = fields(capsys.readouterr().out.strip())
    assert data["title"] == ["Oops"]
    assert data["happened"] == ["It broke"]


def test_cli_opens_with_existing_opener(monkeypatch):
    opened = []
    monkeypatch.setattr(open_link, "open_url", lambda url: (opened.append(url) or 0, ""))
    assert cli.main(["bug"]) == 0
    assert len(opened) == 1
    assert fields(opened[0])["template"] == ["bug_report.yml"]


def test_cli_open_failure(monkeypatch, capsys):
    monkeypatch.setattr(open_link, "open_url", lambda _: (1, "private error"))
    assert cli.main(["bug"]) == 1
    assert "--print" in capsys.readouterr().err


def test_cli_missing_browser_command(monkeypatch, capsys):
    def missing(_):
        raise FileNotFoundError("private path")
    monkeypatch.setattr(open_link, "open_url", missing)
    assert cli.main(["bug"]) == 1
    assert "--print" in capsys.readouterr().err


def test_metadata_cannot_inject_repository_data_or_break_length_cap():
    url = bug_report.build_url(version="0.1.0", app_version="/private/repo\n" * 2000,
                               view="secret concept", error="Layout failed " * 2000)
    assert len(url) <= bug_report.MAX_URL
    data = fields(url)
    assert "private" not in data["environment"][0]
    assert "secret" not in data["environment"][0]
    assert "App: unavailable" in data["environment"][0]
    assert data["happened"][0].endswith(bug_report.TRIMMED)


def test_app_trimming_marker_survives_sanitising():
    assert bug_report.safe_error("Layout failed: private details\n[trimmed]").endswith("[trimmed]")
