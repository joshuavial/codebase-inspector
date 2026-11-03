"""Named build sources follow the same inclusion and judgement policy."""

from cbi import check, concepts, files, store
from cbi.cli import main
from test_concepts import concept_brief, confirm_structure


BUILD_FILES = {
    "build/CMakeLists.txt": "project(sample)\n",
    "build/Makefile": "all:\n\t@echo ready\n",
    "build/GNUmakefile": "all:\n\t@echo ready\n",
    "build/Dockerfile": "FROM scratch\n",
    "build/Containerfile": "FROM scratch\n",
    "build/justfile": "build:\n    echo ready\n",
    "build/Makefile.preview": "all:\n\t@echo ready\n",
    "build/GNUmakefile.preview": "all:\n\t@echo ready\n",
    "build/Dockerfile.preview.txt": "FROM scratch\n",
    "build/Containerfile.preview": "FROM scratch\n",
    "build/justfile.preview.md": "build:\n    echo ready\n",
    "tests/Makefile": "all:\n\t@echo ready\n",
}


def test_named_build_sources_require_summaries_and_owners(make_repo, monkeypatch, capsys, tmp_path):
    root = make_repo(BUILD_FILES)
    monkeypatch.chdir(root)
    assert main(["init"]) == 0
    assert main(["scan"]) == 0
    confirm_structure(capsys, tmp_path)
    brief = concept_brief(capsys)
    assert {f["path"] for f in brief["files"]} == BUILD_FILES.keys()
    assert next(f for f in brief["files"] if f["path"] == "tests/Makefile")["role"] == "test"
    assert all(files.source_like(path) for path in BUILD_FILES)
    conn = store.open_db(root / ".cbi" / "model.db")
    try:
        findings = check._file_findings(conn, BUILD_FILES)
        assert {f["file"] for f in findings if f["kind"] == "summary"} == BUILD_FILES.keys()
        errors, _ = concepts.problems(conn, {
            "summary": "Build a utility.", "concepts": [], "externals": [], "relationships": [],
        })
        assert all(any(path in error for error in errors) for path in BUILD_FILES)
    finally:
        conn.close()


def test_classification_policy_change_refreshes_existing_models(make_repo, monkeypatch):
    root = make_repo({"Makefile": "all:\n\t@echo ready\n"})
    monkeypatch.chdir(root)
    current = files.named_source_language
    with monkeypatch.context() as old_policy:
        old_policy.setattr(files, "CLASSIFICATION_VERSION", 0)
        old_policy.setattr(files, "named_source_language", lambda path: None)
        assert main(["init"]) == 0
        assert main(["scan"]) == 0
    assert files.named_source_language is current
    assert main(["scan"]) == 0
    conn = store.open_db(root / ".cbi" / "model.db")
    try:
        assert {f["path"] for f in concepts._code_files(conn)} == {"Makefile"}
    finally:
        conn.close()


def test_classification_policy_change_refreshes_existing_ref_models(make_repo, monkeypatch, capsys):
    from test_refs import scan_ref

    root = make_repo({"Makefile": "all:\n\t@echo ready\n"})
    monkeypatch.chdir(root)
    with monkeypatch.context() as old_policy:
        old_policy.setattr(files, "CLASSIFICATION_VERSION", 0)
        old_policy.setattr(files, "named_source_language", lambda path: None)
        assert main(["init"]) == 0
        sha, _ = scan_ref(capsys, "HEAD")
    db = root / ".cbi" / "refs" / sha / "model.db"
    conn = store.open_db(db)
    try:
        assert not concepts._code_files(conn)
    finally:
        conn.close()

    for stored_version in ("0", None):
        conn = store.open_db(db)
        try:
            with conn:
                # Both pre-version models and explicitly older versions must rebuild.
                if stored_version is None:
                    conn.execute("DELETE FROM meta WHERE key = 'classification_version'")
                else:
                    store.set_meta(conn, "classification_version", stored_version)
        finally:
            conn.close()
        _, output = scan_ref(capsys, "HEAD")
        assert "scanned" in output and "reused" not in output
        conn = store.open_db(db)
        try:
            assert {f["path"] for f in concepts._code_files(conn)} == {"Makefile"}
            assert store.get_meta(conn, "classification_version") == str(files.CLASSIFICATION_VERSION)
        finally:
            conn.close()
        assert "reused" in scan_ref(capsys, "HEAD")[1]
