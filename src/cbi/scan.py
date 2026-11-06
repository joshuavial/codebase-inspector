"""Scan and mapping pipeline for codebase-inspector.

Dispatches repository initialisation, file enumeration, hashing, incremental
AST parsing, symbol resolution, judgement projection, and ref scanning.
"""

import json
import subprocess
import sys
import time
from pathlib import Path

from cbi import concepts, data, docs, files, manifests, parse, progress, resolve, screens, store, tasks, team
from cbi.ids import file_id


def init_repo(root, out=None, team_mode=False):
    root = Path(root).resolve()
    out = (out or (root / ".cbi")).resolve()
    if team_mode:
        return team.cmd_init(root, out)
    out.mkdir(parents=True, exist_ok=True)
    # Team mode rewrote this file. Putting `*` back would hide the committed judgement.
    if (out / "team.toml").is_file():
        if not (out / ".gitignore").exists():
            (out / ".gitignore").write_text(team.DERIVED_GITIGNORE, encoding="utf-8")
    else:
        (out / ".gitignore").write_text("*\n", encoding="utf-8")
    ignore = out / "ignore"
    if ignore.exists():
        print(f"{out} already initialised; kept {ignore}")
    else:
        ignore.write_text(files.default_ignore(root), encoding="utf-8")
        print(f"Created {out} and wrote {ignore}. Edit it to skip more paths, then run `cbi scan`.")
    files.report_excluded_source(root, ignore.read_text(encoding="utf-8"))
    return 0


def _read(path):
    return path.read_text(encoding="utf-8") if path.exists() else None


def _scan_fingerprint(workspaces, ignore_text, out, structure_text, concepts_text, screens_text):
    """The no-change fingerprint. Team mode also hashes answers.jsonl."""
    directory = team.team_dir(out)
    answers = _read(directory / "answers.jsonl") if directory else None
    return files.fingerprint(
        workspaces, ignore_text, structure_text, concepts_text, screens_text,
        answers_text=answers, team=directory is not None,
    )


def _ref_judgement(out):
    return store.ref_judgement(_read(out / "structure.json"), _read(out / "team.toml"),
                               _read(out / "answers.jsonl"))


def _map(root, out, ignore_text, workspaces, tracked, states, commit=None, parsed=None, reporter=None):
    """Run the scan pipeline over an already enumerated tree. root supplies file bytes.
    parsed is the shared parse store a ref scan reads and fills."""
    reporter = reporter or progress.Progress()
    concepts_text = _read(out / "concepts.json")
    screens_text = _read(out / "screens.json")
    fp = _scan_fingerprint(
        workspaces, ignore_text, out, _read(out / "structure.json"), concepts_text, screens_text)
    mechanical_fp = files.fingerprint(workspaces, ignore_text, _read(out / "structure.json"))
    conn = store.open_db(out / "model.db")
    try:
        with reporter.phase("open answer cache"):
            tasks.attach_cache(conn)
        with conn:
            # Reserve the writer before reading the snapshot used by this scan.
            # A deferred read transaction cannot wait when another writer commits.
            with reporter.phase("waiting for model writer"):
                conn.execute("BEGIN IMMEDIATE")
            old = store.file_states(conn)
            same_files = {p: s[2] for p, s in states.items()} == {p: s[2] for p, s in old.items()}
            shortcut = (same_files and store.get_meta(conn, "fingerprint") == fp
                        and store.get_meta(conn, "mechanical_fingerprint") == mechanical_fp
                        and (not commit or store.get_meta(conn, "ref_judgement") == _ref_judgement(out)))
            store.replace_file_states(conn, {p: s[:4] for p, s in states.items()})
            store.set_meta(conn, "scanned_at", time.strftime("%Y-%m-%dT%H:%M:%S%z"))
            store.set_meta(conn, "parser_version", str(files.PARSER_VERSION))
            store.set_meta(conn, "classification_version", str(files.CLASSIFICATION_VERSION))
            store.set_meta(conn, "ignore", files.ignore_token(ignore_text))
            # content_hash is the git blob id. A model written before that misses this key,
            # so the next scan rehashes instead of reusing the old digest from mtime.
            store.set_meta(conn, "content_id", "blob")
            if commit:
                store.set_meta(conn, "commit", commit)
            if not shortcut:
                previous_concepts = store.get_meta(conn, "concepts_json")
                mechanical = not same_files or store.get_meta(conn, "mechanical_fingerprint") != mechanical_fp
                if mechanical:
                    with reporter.phase("enumerated nodes"):
                        known = {r[0] for r in conn.execute("SELECT id FROM nodes WHERE kind = 'file'")}
                        store.replace_enumerated_nodes(conn, files.build_nodes(workspaces, tracked, states, root))
                    with reporter.phase("parse"):
                        _parse_changed(conn, root, tracked, states, old, known, parsed, reporter)
                        store.drop_orphan_symbols(conn)
                    with reporter.phase("resolve"):
                        resolve.resolve(conn, root, reporter=reporter)
                    with reporter.phase("data"):
                        data.apply(conn, root)
                    with reporter.phase("manifests"):
                        manifests.apply(conn, root, _read(out / "structure.json"))
                else:
                    reporter.emit("reusing unchanged mechanical relationships")
                with reporter.phase("judgement"):
                    concepts.apply(conn, concepts_text)
                    screens.apply(conn, screens_text, root)
                    tasks.refresh(conn, root, out, previous_concepts=previous_concepts)
                # ponytail: full search rebuild per scan; index only changed nodes if it gets slow.
                with reporter.phase("search and docs"):
                    store.reindex(conn)
                    docs.index(conn, root)
                # refresh may have written structure.json or concepts.json from the answer cache
                fp = _scan_fingerprint(
                    workspaces, ignore_text, out, _read(out / "structure.json"),
                    _read(out / "concepts.json"), _read(out / "screens.json"))
                store.set_meta(conn, "fingerprint", fp)
                # Accepted structure changes rebuild their relationships during refresh.
                store.set_meta(conn, "mechanical_fingerprint", files.fingerprint(
                    workspaces, ignore_text, _read(out / "structure.json")))
            if commit:
                store.set_meta(conn, "ref_judgement", _ref_judgement(out))
        return shortcut, store.counts_by_display_kind(conn), tasks.task_counts(conn)
    finally:
        conn.close()


def scan(root, out):
    """Run the scan pipeline on the working tree. Returns (shortcut hit, counts, (open, blocked))."""
    reporter = progress.Progress()
    ignore_text = _read(out / "ignore")
    with reporter.phase("enumerate"):
        workspaces, tracked = files.enumerate_repo(root, files.Ignore(ignore_text or ""))
    conn = store.open_db(out / "model.db")
    try:
        tasks.attach_cache(conn)
        old = store.file_states(conn) if store.get_meta(conn, "content_id") == "blob" else {}
    finally:
        conn.close()
    with reporter.phase("hash"):
        states = files.hash_files(root, tracked, old, reporter=reporter)
    return _map(root, out, ignore_text, workspaces, tracked, states, reporter=reporter)


def scan_ref(root, out, ref, *, force=False, restore_judgement=True):
    """Map one commit from git objects into out/refs/<sha>/model.db.

    Returns (sha, reused, counts, (open, blocked)). A stored model is reused when
    the schema, parser and classification versions, and ignore file still match.
    """
    ignore_text = _read(out / "ignore")
    reporter = progress.Progress()
    reporter.emit("enumerate ref")
    sha = files.resolve_commit(root, ref)
    home = out / "refs" / sha
    db = home / "model.db"
    # Ref judgement comes from that commit, never from the current worktree.
    # Keep locally answered ref tasks when no committed projection exists.
    if restore_judgement:
        for name in ("structure.json", "concepts.json", "screens.json", "team.toml", "answers.jsonl"):
            result = subprocess.run(
                ["git", "cat-file", "blob", f"{sha}:.cbi/{name}"], cwd=root, capture_output=True)
            if result.returncode == 0:
                home.mkdir(parents=True, exist_ok=True)
                path = home / name
                if not path.exists() or path.read_bytes() != result.stdout:
                    path.write_bytes(result.stdout)
    if not force and store.ref_reusable(
            db, files.ignore_token(ignore_text), files.PARSER_VERSION,
            _read(home / "concepts.json"), _read(home / "screens.json"),
            classification_version=files.CLASSIFICATION_VERSION,
            structure_text=_read(home / "structure.json"), team_text=_read(home / "team.toml"),
            answers_text=_read(home / "answers.jsonl")):
        conn = store.read_only(db)
        try:
            return sha, True, store.counts_by_display_kind(conn), tasks.task_counts(conn)
        finally:
            conn.close()
    home.mkdir(parents=True, exist_ok=True)
    with reporter.phase("enumerate ref files"):
        tree = files.CommitTree(root, sha, files.Ignore(ignore_text or ""))
    parsed = store.open_parse_store(out / "refs" / "parse.db")
    try:
        _shortcut, counts, task_counts = _map(
            tree, home, ignore_text, tree.workspaces, tree.tracked, tree.file_states(), sha, parsed, reporter)
    finally:
        parsed.commit()  # parse results are pure, so keep them even when the scan failed later
        parsed.close()
        tree.close()
    return sha, False, counts, task_counts


def _parse_changed(conn, root, tracked, states, old, known, parsed=None, reporter=None):
    """Parse code files whose content or parser version changed, or that are new to the model.
    With a shared parse store, a file version parsed for another ref is read from it instead."""
    by_ws = {}
    for _top, ws, rel in tracked:
        by_ws.setdefault(ws["id"], []).append(rel)
    roots = {wid: files.cs_test_roots(paths) for wid, paths in by_ws.items()}
    for index, (top, ws, rel) in enumerate(tracked, 1):
        if reporter:
            reporter.file("parse", index, len(tracked), top)
        state = states.get(top)
        if not state or state[4]:  # gone from disk, or a symlink
            continue
        role, lang = files.classify(rel, roots.get(ws["id"], ()))
        fid = file_id(ws["id"], rel)
        prev = old.get(top)
        if lang not in parse.LANGS or (prev and prev[2:4] == state[2:4] and fid in known):
            continue
        key = (fid, state[2], lang, int(role == "test"), str(files.PARSER_VERSION))
        row = parsed.execute(
            "SELECT loc, nodes, facts, has_error FROM parsed "
            "WHERE file_id = ? AND blob = ? AND lang = ? AND test = ? AND parser = ?", key,
        ).fetchone() if parsed else None
        if row:
            loc, nodes, facts, has_error = row[0], json.loads(row[1]), json.loads(row[2]), bool(row[3])
        else:
            source = (root / top).read_bytes()
            nodes, facts, has_error = parse.symbol_nodes(fid, ws["id"], rel, lang, source, role == "test")
            loc = len(source.splitlines())
            if parsed:
                parsed.execute("INSERT OR REPLACE INTO parsed VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                               (*key, loc, json.dumps(nodes), json.dumps(facts), int(has_error)))
        store.replace_file_symbols(conn, ws["id"], rel, loc, nodes, fid, facts)
        if any(n["kind"] == "test" for n in nodes):
            conn.execute(
                "UPDATE nodes SET display_kind = 'test file', attrs = json_set(attrs, '$.role', 'test') "
                "WHERE id = ? AND json_extract(attrs, '$.role') != 'test'",
                (fid,),
            )
        store.set_diagnostic(conn, fid, "parse_error", "tree-sitter reported syntax errors" if has_error else None)
