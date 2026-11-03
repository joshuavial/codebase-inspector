"""pyproject, Dockerfile, compose and wrangler rules, and skills and repertoires as packages."""

import json
import os
import sqlite3
import subprocess

import pytest

from cbi import manifests
from cbi.cli import main

FILES = {
    "pyproject.toml": '[project]\nname = "tool"\n[project.scripts]\ntool = "tool.cli:main"\n'
                      '[tool.uv.sources]\nlib = { path = "libs/lib" }\nrequests = { index = "pypi" }\n',
    "src/tool/__init__.py": "",
    "src/tool/cli.py": "def main():\n    pass\n",
    "libs/lib/pyproject.toml": '[project]\nname = "lib"\n[project.scripts]\nlibcmd = "lib.missing:main"\n',
    "libs/lib/src/lib/__init__.py": "",
    "libs/lib/Containerfile": 'FROM nginx\nCMD ["nginx", "-g", "daemon off;"]\n',
    # a project script named in exec form, so the same entry as the `tool` script
    "Dockerfile": 'FROM python:3.12\nCOPY . /app\nCMD ["uv", "run", "tool"]\n',
    # shell form with a continuation, a container path and a later stage overriding CMD
    "worker/Dockerfile.worker": "FROM python AS base\nCMD echo no\nFROM base\n"
                                "ENTRYPOINT python \\\n  /app/worker/run.py --fast\n",
    "worker/run.py": "print(1)\n",
    "Dockerfile.tmpl": "FROM {{ base }}\n",
    "fixtures/Dockerfile": "FROM scratch\n",  # kept even though adjacent files are saved data
    "fixtures/a.json": "{}\n",
    "fixtures/b.json": "{}\n",
    "compose.yaml": """\
# services for local dev
services:
  api:
    build: .
    depends_on:
      db:
        condition: service_healthy
    command: |
      run --this
        and: that
  worker:
    build: {context: worker, dockerfile: Dockerfile.worker}
    depends_on: [api, db]
    environment:
      - MODE=1
  db:
    image: "postgres:16"   # pinned
    ports:
      - "5432:5432"
  override-only:
    environment: [X=1]
""",
    "compose.yaml.tmpl": "services:\n  decoy:\n    image: busybox\n",
    "edge/wrangler.toml": 'name = "edge"\nmain = "src/index.ts"\n',
    "edge/src/index.ts": "export default {};\n",
    "site/wrangler.toml": 'name = "site"\npages_build_output_dir = "dist"\n',
    ".claude/skills/demo/SKILL.md": "# demo\n",
    ".claude/skills/demo/scripts/run.py": "print(1)\n",
    "repertoires/core/README.md": "# core\n",
}


@pytest.fixture
def repo(make_repo, monkeypatch):
    root = make_repo(FILES, name="acme")
    (root / ".agents").mkdir()
    os.symlink("../.claude/skills", root / ".agents" / "skills")
    subprocess.run(["git", "add", ".agents/skills"], cwd=root, check=True)
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@e", "-c", "commit.gpgsign=false",
                    "commit", "-q", "-m", "link"], cwd=root, check=True)
    monkeypatch.chdir(root)
    assert main(["init"]) == 0
    assert main(["scan"]) == 0
    return root


def _db(root):
    return sqlite3.connect(root / ".cbi" / "model.db")


def _nodes(conn, kind):
    return {r[0].removeprefix("local:acme:"): (r[1], json.loads(r[2])) for r in conn.execute(
        "SELECT id, display_kind, attrs FROM nodes WHERE kind = ?", (kind,))}


def test_deployables(repo):
    found = {k: (v[0], v[1]["entry_points"]) for k, v in _nodes(_db(repo), "deployable").items()}
    assert found == {
        "deployable:tool": ("cli", ["src/tool/cli.py"]),
        "deployable:libcmd": ("cli", []),
        "deployable:acme-image": ("container image", ["src/tool/cli.py"]),
        "deployable:worker-worker-image": ("container image", ["worker/run.py"]),
        "deployable:lib-image": ("container image", []),
        "deployable:fixtures-image": ("container image", []),
        "deployable:api": ("service", []),
        "deployable:worker": ("service", []),
        "deployable:edge": ("worker", ["edge/src/index.ts"]),
    }


def test_unresolved_entries(repo):
    rows = _db(repo).execute("SELECT node_id, detail FROM diagnostics WHERE kind = 'unresolved_entry' "
                             "ORDER BY node_id").fetchall()
    assert rows == [
        ("local:acme:deployable:fixtures-image", "Dockerfile: no CMD or ENTRYPOINT maps to no tracked source file"),
        ("local:acme:deployable:lib-image", "Dockerfile: nginx -g daemon off; maps to no tracked source file"),
        ("local:acme:deployable:libcmd", "pyproject.toml scripts: lib.missing:main maps to no tracked source file"),
    ]


def test_packages_skills_and_externals(repo):
    conn = _db(repo)
    packages = {k: (v[0], v[1]["directory"], v[1]["members"]) for k, v in _nodes(conn, "package").items()}
    # the symlinked .agents/skills adds nothing: the demo skill is counted once
    assert packages == {
        "package:tool": ("package", "", packages["package:tool"][2]),
        "package:lib": ("package", "libs/lib", 3),
        "package:demo": ("skill", ".claude/skills/demo", 2),
        "package:core": ("repertoire", "repertoires/core", 1),
    }
    assert _nodes(conn, "external") == {"service:db": ("service", {
        "evidence": "compose.yaml service db", "image": "postgres:16"})}


def test_depends_on_links(repo):
    edges = {(s.removeprefix("local:acme:"), d.removeprefix("local:acme:")) for s, d in _db(repo).execute(
        "SELECT src, dst FROM edges WHERE kind = 'depends_on'")}
    assert edges == {
        ("package:tool", "package:lib"),
        ("deployable:api", "service:db"),
        ("deployable:api", "deployable:acme-image"),
        ("deployable:worker", "deployable:api"),
        ("deployable:worker", "service:db"),
        ("deployable:worker", "deployable:worker-worker-image"),
    }


def test_rescan_drops_removed_externals(repo):
    (repo / "compose.yaml").write_text("services:\n  cache:\n    image: redis\n")
    assert main(["scan"]) == 0
    assert set(_nodes(_db(repo), "external")) == {"service:cache"}


def test_yaml_reader():
    text = """\
x-common: &common
  restart: always
services:
  a:
    <<: *common
    build:
      context: ./a
      args:
        - K=v
    depends_on:
    - b
    - c
  b:
    image: 'redis'
    healthcheck:
      test: ["CMD", "ping"]
    volumes:
      - type: bind
        source: ./x
  c: {image: nginx}
"""
    services = manifests._yaml(text)["services"]
    assert services["a"]["build"] == {"context": "./a", "args": ["K=v"]}
    assert services["a"]["depends_on"] == ["b", "c"]
    assert services["b"]["image"] == "redis"
    assert services["b"]["healthcheck"]["test"] == ["CMD", "ping"]
    assert services["b"]["volumes"] == [{"type": "bind", "source": "./x"}]
    assert services["c"] == {"image": "nginx"}


def test_block_scalars():
    text = """\
services:
  api:
    command: >
      poetry run uvicorn app.api.server:app
      --host 0.0.0.0
  job:
    command: |
      python -m app.worker
      --once
"""
    services = manifests._yaml(text)["services"]
    assert services["api"]["command"] == "poetry run uvicorn app.api.server:app --host 0.0.0.0"
    assert services["job"]["command"] == "python -m app.worker\n--once"


def test_compose_command_and_poetry(make_repo, monkeypatch):
    root = make_repo({
        "pyproject.toml": '[tool.poetry]\nname = "toolbox"\n'
                          '[tool.poetry.scripts]\nrun = "toolbox.main:main"\n',
        "toolbox/main.py": "def main():\n    pass\n",
        "app/worker.py": "def run():\n    pass\n",
        "app/api/server.py": "def app():\n    pass\n",
        "Dockerfile": 'FROM python\nCMD ["tail", "-f", "/dev/null"]\n',
        "compose.yaml": """\
services:
  api:
    build: .
    command: >
      poetry run uvicorn app.api.server:app --host 0.0.0.0
  worker:
    build: .
    command: poetry run python -m app.worker
  worker-b:
    build: .
    command: poetry run python -m app.worker
  redis:
    image: redis:7-alpine
""",
        "app-only/pyproject.toml": '[tool.poetry]\nname = "extras"\npackage-mode = false\n'
                                   '[tool.poetry.scripts]\nsync = "sync_job:main"\n',
        "app-only/sync_job.py": "def main():\n    pass\n",
    }, name="acme")
    monkeypatch.chdir(root)
    assert main(["init"]) == 0
    assert main(["scan"]) == 0
    found = {k: (v[0], v[1]["entry_points"]) for k, v in _nodes(_db(root), "deployable").items()}
    assert found["deployable:api"] == ("service", ["app/api/server.py"])
    assert found["deployable:worker"] == ("service", ["app/worker.py"])
    assert found["deployable:worker-b"] == ("service", ["app/worker.py"])
    assert found["deployable:run"] == ("cli", ["toolbox/main.py"])
    assert found["deployable:sync"] == ("cli", ["app-only/sync_job.py"])
    assert found["deployable:acme-image"] == ("container image", [])
    packages = {k: v[1]["directory"] for k, v in _nodes(_db(root), "package").items()}
    assert packages == {"package:toolbox": ""}
    edges = {(s.removeprefix("local:acme:"), d.removeprefix("local:acme:")) for s, d in _db(root).execute(
        "SELECT src, dst FROM edges WHERE kind = 'depends_on'")}
    assert ("deployable:api", "deployable:acme-image") in edges
    assert ("deployable:worker", "deployable:acme-image") in edges
    assert ("deployable:worker-b", "deployable:acme-image") in edges
    assert _nodes(_db(root), "external")["service:redis"][1]["image"] == "redis:7-alpine"


@pytest.mark.parametrize(('instruction', 'entry'), [
    ('COPY scripts/start.sh /usr/local/bin/serve', '["/usr/local/bin/serve"]'),
    ('ADD ["scripts/start.sh", "/usr/local/bin/serve"]', '["sh", "/usr/local/bin/serve"]'),
    ('COPY --chmod=755 scripts/ /opt/bin/', '["sh", "/opt/bin/start.sh"]'),
])
def test_image_copy_destinations(make_repo, instruction, entry):
    root = make_repo({
        'service/scripts/start.sh': '#!/bin/sh\necho ready\n',
        'service/deploy/Dockerfile': f'FROM alpine\n{instruction}\nENTRYPOINT {entry}\n',
        'compose.yaml': 'services:\n  worker:\n    build:\n      context: service\n      dockerfile: deploy/Dockerfile\n',
    })
    ws = manifests._Workspace('local:repo', 'repo', root, {'service/scripts/start.sh', 'service/deploy/Dockerfile', 'compose.yaml'})
    image = manifests.dockerfile(ws)[0][0]
    assert image['entries'][0][1] == 'service/scripts/start.sh'


def test_image_state_ignores_untracked_dockerfile(make_repo):
    root = make_repo({'start.py': 'print(1)\n'})
    (root / 'Dockerfile').write_text('FROM python\nCOPY start.py /serve\nCMD ["/serve"]\n')
    ws = manifests._Workspace('local:repo', 'repo', root, {'start.py'})
    state = manifests._docker_state(ws, 'Dockerfile', '')
    assert state['files'] == {}
    assert state['commands'] == {}


def test_external_stage_copy_does_not_reuse_local_mapping(make_repo):
    files = {
        'Dockerfile': 'FROM python\nCOPY start.py /usr/bin/serve\n'
                      'COPY --from=external /generated/serve /usr/bin/serve\n'
                      'ENTRYPOINT ["python", "/usr/bin/serve"]\n',
        'start.py': 'print(1)\n',
    }
    root = make_repo(files)
    ws = manifests._Workspace('local:repo', 'repo', root, set(files))
    assert manifests.dockerfile(ws)[0][0]['entries'][0][1] is None


def test_image_stage_copy_boundaries(make_repo):
    root = make_repo({
        'scripts/start.py': 'print(1)\n',
        'Dockerfile': 'FROM python AS builder\nCOPY scripts/start.py /built/serve\n'
                      'CMD ["python", "/built/serve"]\nFROM alpine AS clean\n'
                      'FROM clean\nCOPY --from=builder /built/serve /usr/bin/runner\n'
                      'ENTRYPOINT ["python", "/usr/bin/runner"]\n',
    })
    ws = manifests._Workspace('local:repo', 'repo', root, {'Dockerfile', 'scripts/start.py'})
    assert manifests.dockerfile(ws)[0][0]['entries'][0][1] == 'scripts/start.py'
    (root / 'Dockerfile').write_text('FROM python AS builder\nCOPY scripts/start.py /built/serve\n'
                                    'CMD ["python", "/built/serve"]\nFROM alpine\n')
    assert manifests.dockerfile(ws)[0][0]['entries'] == [('no CMD or ENTRYPOINT', None)]
    (root / 'Dockerfile').write_text('FROM python AS builder\nCOPY scripts/start.py /built/serve\n'
                                    'FROM builder\nENTRYPOINT ["/built/serve"]\n')
    assert manifests.dockerfile(ws)[0][0]['entries'][0][1] == 'scripts/start.py'


@pytest.mark.parametrize('override', [
    'command: [uvicorn, api:app]',
    'entrypoint: [uvicorn, api:app]',
    'command: sh -c "exec uvicorn api:app --host 0.0.0.0"',
    'entrypoint: /usr/local/bin/boot',
])
def test_compose_build_context_and_overrides(make_repo, monkeypatch, capsys, override):
    root = make_repo({
        'services/api.py': 'def app():\n    pass\n',
        'services/boot.sh': '#!/bin/sh\nif [ "$MODE" = "web" ]; then\n  exec uvicorn api:app\nfi\n',
        'services/Dockerfile': 'FROM python\nWORKDIR /srv\nCOPY . .\nCOPY boot.sh /usr/local/bin/boot\n',
        'compose.yaml': f'services:\n  api:\n    build: services\n    {override}\n',
    }, name='acme')
    monkeypatch.chdir(root)
    assert main(['init']) == 0
    assert main(['scan']) == 0
    conn = _db(root)
    found = _nodes(conn, 'deployable')
    assert 'services/api.py' in found['deployable:api'][1]['entry_points']
    assert 'services/api.py' in found['deployable:services-image'][1]['entry_points']
    assert not conn.execute("SELECT detail FROM diagnostics WHERE kind = 'unresolved_entry'").fetchall()
    capsys.readouterr()
    assert main(['orphans', '--json']) == 0
    assert 'services/api.py' not in capsys.readouterr().out


def test_compose_override_replaces_default_command(make_repo):
    files = {
        'Dockerfile': 'FROM python\nWORKDIR /app\nCOPY . .\nCMD ["old.py"]\nENTRYPOINT ["python"]\n',
        'old.py': 'print(1)\n',
        'new.py': 'print(2)\n',
    }
    root = make_repo(files)
    ws = manifests._Workspace('local:repo', 'repo', root, set(files))
    entries = manifests._service_entries(ws, {'command': ['new.py']}, 'Dockerfile', '')
    assert {path for _, path in entries} == {'new.py'}
    entries = manifests._service_entries(ws, {'entrypoint': ['python', 'new.py']}, 'Dockerfile', '')
    assert {path for _, path in entries} == {'new.py'}

    entries = manifests._service_entries(ws, {'command': None}, 'Dockerfile', '')
    assert {path for _, path in entries} == {'old.py'}


@pytest.mark.parametrize('script,extra', [
    ('vite --host 0.0.0.0', {'site/vite.config.ts': 'export default {}'}),
    ('vite --host 0.0.0.0', {}),
    ('npm run web', {'site/vite.config.ts': 'export default {}'}),
    ('node src/main.ts', {}),
])
def test_image_npm_scripts(make_repo, monkeypatch, script, extra):
    root = make_repo({
        'site/package.json': json.dumps({'scripts': {'dev': script, 'web': 'vite'}}),
        'site/index.html': '<script type="module" src="/src/main.ts"></script>',
        'site/src/main.ts': 'console.log(1);',
        'site/Dockerfile': 'FROM node\nWORKDIR /app\nCOPY . .\nCMD ["npm", "run", "dev"]\n',
        **extra,
    }, name='acme')
    monkeypatch.chdir(root)
    assert main(['init']) == 0
    assert main(['scan']) == 0
    conn = _db(root)
    assert _nodes(conn, 'deployable')['deployable:site-image'][1]['entry_points'] == ['site/src/main.ts']
    assert not conn.execute("SELECT detail FROM diagnostics WHERE kind = 'unresolved_entry'").fetchall()


def test_image_npm_script_cycle_stays_unresolved(make_repo):
    files = {
        'Dockerfile': 'FROM node\nWORKDIR /app\nCOPY . .\nCMD ["npm", "run", "dev"]\n',
        'package.json': '{"scripts":{"dev":"npm run other","other":"npm run dev"}}',
        'sibling/package.json': '{"scripts":{"dev":"node main.js"}}',
        'sibling/main.js': 'console.log(1);',
    }
    root = make_repo(files)
    ws = manifests._Workspace('local:repo', 'repo', root, set(files))
    assert manifests.dockerfile(ws)[0][0]['entries'] == [('npm run dev', None)]


@pytest.mark.parametrize('command', [
    'CMD ["tail", "-f", "/dev/null"]',
    'CMD ["sleep", "infinity"]',
    'ENTRYPOINT ["sleep"]\nCMD ["infinity"]',
    'CMD ["sh", "-c", "exec tail -f /dev/null"]',
])
def test_idle_image_is_an_artifact(make_repo, monkeypatch, command):
    root = make_repo({'Dockerfile': f'FROM alpine\n{command}\n'}, name='acme')
    monkeypatch.chdir(root)
    assert main(['init']) == 0
    assert main(['scan']) == 0
    conn = _db(root)
    image = _nodes(conn, 'deployable')['deployable:acme-image']
    assert image[0] == 'container image'
    assert image[1]['entry_points'] == []
    assert image[1]['artifact_command']
    assert not conn.execute("SELECT detail FROM diagnostics WHERE kind = 'unresolved_entry'").fetchall()


def test_unknown_image_command_stays_unresolved(make_repo):
    files = {'Dockerfile': 'FROM alpine\nCMD ["sleep", "missing.py"]\n'}
    root = make_repo(files)
    ws = manifests._Workspace('local:repo', 'repo', root, set(files))
    assert manifests.dockerfile(ws)[0][0]['entries'] == [('sleep missing.py', None)]


@pytest.mark.parametrize('replacement', [
    'COPY --from=builder /serve /serve',
    'COPY scripts/*.py /serve',
])
def test_unknown_copy_invalidates_previous_source(make_repo, replacement):
    files = {
        'Dockerfile': 'FROM alpine AS builder\nRUN generate /serve\nFROM python\n'
                      f'COPY start.py /serve\n{replacement}\nCMD ["python", "/serve"]\n',
        'start.py': 'print(1)\n',
        'scripts/other.py': 'print(2)\n',
    }
    root = make_repo(files)
    ws = manifests._Workspace('local:repo', 'repo', root, set(files))
    assert manifests.dockerfile(ws)[0][0]['entries'] == [('python /serve', None)]


def test_compose_working_directory_alone_selects_runtime_entry(make_repo, monkeypatch):
    root = make_repo({
        'Dockerfile': 'FROM python\nCOPY one /one\nCOPY two /two\nWORKDIR /one\nCMD ["python", "start.py"]\n',
        'one/start.py': 'print(1)\n',
        'two/start.py': 'print(2)\n',
        'compose.yaml': 'services:\n  worker:\n    build: .\n    working_dir: /two\n',
    }, name='acme')
    monkeypatch.chdir(root)
    assert main(['init']) == 0
    assert main(['scan']) == 0
    found = _nodes(_db(root), 'deployable')
    assert found['deployable:acme-image'][1]['entry_points'] == ['one/start.py']
    assert found['deployable:worker'][1]['entry_points'] == ['two/start.py']


@pytest.mark.parametrize('command', [
    'exec echo "python -m api"',
    '["echo", "python", "-m", "api"]',
    'uvicorn api${SUFFIX}:app',
    '["uvicorn", "api${SUFFIX}:app"]',
    'python -m api${SUFFIX}',
    '["sh", "-c", "echo uvicorn api:app"]',
    '["sh", "--unknown", "-c", "python -m api"]',
])
def test_non_executable_or_dynamic_modules_stay_unresolved(make_repo, command):
    files = {
        'Dockerfile': f'FROM python\nWORKDIR /app\nCOPY . .\nCMD {command}\n',
        'api.py': 'def app():\n    pass\n',
    }
    root = make_repo(files)
    ws = manifests._Workspace('local:repo', 'repo', root, set(files))
    assert not any(path for _, path in manifests.dockerfile(ws)[0][0]['entries'])


def test_echoed_modules_in_shell_wrapper_are_not_roots(make_repo):
    files = {
        'Dockerfile': 'FROM python\nWORKDIR /app\nCOPY . .\nCMD ["sh", "boot.sh"]\n',
        'boot.sh': '#!/bin/sh\nexec echo "python -m api"\n',
        'api.py': 'def app():\n    pass\n',
    }
    root = make_repo(files)
    ws = manifests._Workspace('local:repo', 'repo', root, set(files))
    assert {path for _, path in manifests.dockerfile(ws)[0][0]['entries']} == {'boot.sh'}


@pytest.mark.parametrize('created', ['/app', '/app/nested'])
@pytest.mark.parametrize('inherit', ['', 'FROM base\n'])
def test_copy_respects_directories_created_by_earlier_workdir(make_repo, created, inherit):
    files = {
        'Dockerfile': f'FROM python AS base\nWORKDIR {created}\n{inherit}WORKDIR /other\n'
                      'COPY start.py /app\nCMD ["python", "/app/start.py"]\n',
        'start.py': 'print(1)\n',
    }
    root = make_repo(files)
    ws = manifests._Workspace('local:repo', 'repo', root, set(files))
    assert manifests.dockerfile(ws)[0][0]['entries'] == [('python /app/start.py', 'start.py')]


@pytest.mark.parametrize('copy', ['COPY\tstart.py /serve', 'COPY\t--chmod=755\tstart.py\t/serve'])
def test_dockerfile_instructions_accept_tab_separators(make_repo, copy):
    files = {
        'Dockerfile': f'FROM\tpython\nWORKDIR\t/app\n{copy}\nCMD\t["python", "/serve"]\n',
        'start.py': 'print(1)\n',
    }
    root = make_repo(files)
    ws = manifests._Workspace('local:repo', 'repo', root, set(files))
    assert manifests.dockerfile(ws)[0][0]['entries'] == [('python /serve', 'start.py')]


@pytest.mark.parametrize('reader', ['_docker_builds', '_compose_image_entries'])
def test_image_compose_readers_ignore_non_mapping_document(make_repo, reader):
    files = {'Dockerfile': 'FROM python\n', 'compose.yaml': '- invalid\n'}
    root = make_repo(files)
    ws = manifests._Workspace('local:repo', 'repo', root, set(files))
    read = getattr(manifests, reader)
    assert not (read(ws, 'Dockerfile') if reader == '_compose_image_entries' else read(ws))


def test_non_mapping_compose_document_does_not_abort_scan(make_repo, monkeypatch):
    root = make_repo({'Dockerfile': 'FROM python\n', 'compose.yaml': '- invalid\n'}, name='acme')
    monkeypatch.chdir(root)
    assert main(['init']) == 0
    assert main(['scan']) == 0
    assert set(_nodes(_db(root), 'deployable')) == {'deployable:acme-image'}


@pytest.mark.parametrize('replacement', [
    'ADD https://example.org/config.json /app/',
    'ADD https://example.org/config.json?version=2 /app/',
    'COPY configs/*.json /app/',
    'COPY configs/[ab].json /app/',
])
def test_unknown_copy_preserves_unaffected_directory_siblings(make_repo, replacement):
    files = {
        'Dockerfile': f'FROM python\nCOPY start.py /app/\n{replacement}\nCMD ["python", "/app/start.py"]\n',
        'start.py': 'print(1)\n',
    }
    root = make_repo(files)
    ws = manifests._Workspace('local:repo', 'repo', root, set(files))
    assert manifests.dockerfile(ws)[0][0]['entries'] == [('python /app/start.py', 'start.py')]


@pytest.mark.parametrize('replacement', [
    'ADD https://example.org/start.py /app/',
    'COPY configs/*.py /app/',
    'COPY configs/[s]tart.py /app/',
])
def test_unknown_copy_still_invalidates_matching_directory_child(make_repo, replacement):
    files = {
        'Dockerfile': f'FROM python\nCOPY start.py /app/\n{replacement}\nCMD ["python", "/app/start.py"]\n',
        'start.py': 'print(1)\n',
    }
    root = make_repo(files)
    ws = manifests._Workspace('local:repo', 'repo', root, set(files))
    assert manifests.dockerfile(ws)[0][0]['entries'] == [('python /app/start.py', None)]


def test_copy_glob_matching_directory_invalidates_merged_children(make_repo):
    files = {
        'Dockerfile': 'FROM python\nCOPY start.py /app/\nCOPY configs/*.json /app/\nCMD ["python", "/app/start.py"]\n',
        'start.py': 'print(1)\n',
        'configs/payload.json/start.py': 'print(2)\n',
    }
    root = make_repo(files)
    ws = manifests._Workspace('local:repo', 'repo', root, set(files))
    assert manifests.dockerfile(ws)[0][0]['entries'] == [('python /app/start.py', None)]


@pytest.mark.parametrize('command,entry', [
    ('["sh", "-e", "/boot.sh"]', 'boot.sh'),
    ('["sh", "-eu", "/boot.sh"]', 'boot.sh'),
    ('["sh", "-ec", "python -m api"]', 'api.py'),
    ('["sh", "-x", "-c", "python -m api"]', 'api.py'),
    ('["bash", "-o", "pipefail", "-ec", "python -m api"]', 'api.py'),
    ('["sh", "--", "/boot.sh"]', 'boot.sh'),
])
def test_shell_options_keep_script_and_command_entries(make_repo, command, entry):
    files = {
        'Dockerfile': f'FROM python\nWORKDIR /app\nCOPY api.py .\nCOPY boot.sh /boot.sh\nCMD {command}\n',
        'api.py': 'def app():\n    pass\n',
        'boot.sh': '#!/bin/sh\necho ready\n',
    }
    root = make_repo(files)
    ws = manifests._Workspace('local:repo', 'repo', root, set(files))
    assert manifests.dockerfile(ws)[0][0]['entries'][0][1] == entry


@pytest.mark.parametrize('command', [
    '["python", "/start.py", "--pattern", "foo|bar"]',
    '["python", "/start.py", "--pattern", "|"]',
    '["python", "/start.py", "--pattern", "`"]',
    'python /start.py --pattern "foo|bar"',
    "python /start.py --pattern ';'",
    r'python /start.py --pattern foo\|bar',
    '["sh", "-ec", "python /start.py --pattern \'foo|bar\'"]',
])
def test_literal_argument_punctuation_does_not_hide_image_entry(make_repo, command):
    files = {
        'Dockerfile': f'FROM python\nCOPY start.py /start.py\nCMD {command}\n',
        'start.py': 'print(1)\n',
    }
    root = make_repo(files)
    ws = manifests._Workspace('local:repo', 'repo', root, set(files))
    assert manifests.dockerfile(ws)[0][0]['entries'][0][1] == 'start.py'


@pytest.mark.parametrize('command', [
    'python /start.py | echo ready',
    'python /start.py; echo ready',
    'python /start.py --pattern foo|bar',
    'python /start.py > output',
    'echo "python /start.py --pattern foo|bar"',
])
def test_shell_syntax_is_not_treated_as_literal_exec_argv(make_repo, command):
    files = {'Dockerfile': f'FROM python\nCOPY start.py /start.py\nCMD {command}\n',
             'start.py': 'print(1)\n'}
    root = make_repo(files)
    ws = manifests._Workspace('local:repo', 'repo', root, set(files))
    assert manifests.dockerfile(ws)[0][0]['entries'][0][1] is None


@pytest.mark.parametrize('command', [
    '["python", "/start.py", "--pattern", "foo|bar"]',
    "python /start.py --pattern 'foo|bar'",
])
def test_compose_literal_argument_operators_remain_data(make_repo, command):
    files = {
        'Dockerfile': 'FROM python\nCOPY start.py /start.py\n',
        'start.py': 'print(1)\n',
        'compose.yaml': f'services:\n  api:\n    build: .\n    command: {command}\n',
    }
    root = make_repo(files)
    ws = manifests._Workspace('local:repo', 'repo', root, set(files))
    assert manifests.compose(ws)[0][0]['entries'][0][1] == 'start.py'
    assert manifests.dockerfile(ws)[0][0]['entries'][0][1] == 'start.py'


def test_exec_entrypoint_keeps_literal_command_argument_operators(make_repo):
    files = {
        'Dockerfile': 'FROM python\nCOPY start.py /start.py\nENTRYPOINT ["python"]\n'
                      'CMD ["/start.py", "--pattern", "foo|bar"]\n',
        'start.py': 'print(1)\n',
    }
    root = make_repo(files)
    ws = manifests._Workspace('local:repo', 'repo', root, set(files))
    assert manifests.dockerfile(ws)[0][0]['entries'][0][1] == 'start.py'


@pytest.mark.parametrize('filename', ['${FILE}', '$FILE'])
def test_dynamic_remote_filename_invalidates_destination_provenance(make_repo, filename):
    files = {
        'Dockerfile': 'FROM python\nARG FILE=start.py\nCOPY start.py /app/\n'
                      f'ADD https://example.org/{filename} /app/\nCMD ["python", "/app/start.py"]\n',
        'start.py': 'print(1)\n',
    }
    root = make_repo(files)
    ws = manifests._Workspace('local:repo', 'repo', root, set(files))
    assert manifests.dockerfile(ws)[0][0]['entries'] == [('python /app/start.py', None)]
