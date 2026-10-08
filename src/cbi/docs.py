"""Doc nodes: titles, searchable text and `mentions` edges.

Runs after the search index is rebuilt on every scan the no-change shortcut does
not stop. It rereads every markdown file, because a mention can start resolving
when the code it names appears, not only when the doc changes.
"""

import json
import posixpath
import re
from collections import defaultdict

SEARCH_TEXT_LIMIT = 20_000  # characters of title and body indexed per doc
PATH_CONFIDENCE = 1.0  # a path or path#name, in backticks or a link target
NAME_CONFIDENCE = 0.8  # a qualified name that only one symbol has

FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,}).*?^ {0,3}\1[`~]*[ \t]*$", re.M | re.S)
HEADING = re.compile(r"^ {0,3}#{1,6}[ \t]+(.+?)(?:[ \t]+#+)?[ \t]*$", re.M)
FRONT_TITLE = re.compile(r"^title:[ \t]*(.+?)[ \t]*$", re.M)
CODE_SPAN = re.compile(r"(`+)([^`\n]+?)\1")
LINK = re.compile(r"\]\(\s*<?([^)\s>]+)>?(?:\s+[\"'][^)]*)?\)")


def front_matter(text):
    """(front matter, body): the YAML block between leading `---` lines, if any."""
    if text.startswith("---\n"):
        end = re.search(r"^(?:---|\.\.\.)[ \t]*$", text[4:], re.M)
        if end:
            return text[4 : 4 + end.start()], text[4 + end.end():]
    return "", text


def title(text):
    """Front matter `title`, else the first heading outside code fences, else None."""
    meta, body = front_matter(text)
    found = FRONT_TITLE.search(meta)
    if found and (value := found.group(1).strip("'\"").strip()):
        return value
    found = HEADING.search(FENCE.sub("", body))
    return found.group(1).strip() if found else None


def references(text):
    """(code spans, link targets) outside fenced code blocks."""
    body = FENCE.sub("", front_matter(text)[1])
    spans = [m.group(2).strip() for m in CODE_SPAN.finditer(body)]
    links = [m.group(1) for m in LINK.finditer(CODE_SPAN.sub("", body))]
    return spans, links


class _Targets:
    """Lookup of nodes by path from the top repo and by symbol qualified name."""

    def __init__(self, conn):
        self.ws_root = {
            wid: json.loads(attrs or "{}").get("root") or ""
            for wid, attrs in conn.execute("SELECT id, attrs FROM nodes WHERE kind = 'workspace'")
        }
        self.by_path = {}
        for nid, wid, path in conn.execute(
                "SELECT id, workspace_id, path FROM nodes WHERE kind IN ('file', 'doc', 'group')"):
            self.by_path[self.top(wid, path)] = nid
        self.ids = set(self.by_path.values())
        self.by_name = defaultdict(list)
        for (nid,) in conn.execute("SELECT id FROM nodes WHERE kind IN ('symbol', 'test')"):
            self.ids.add(nid)
            self.by_name[nid.split("#", 1)[1]].append(nid)

    def top(self, wid, path):
        root = self.ws_root.get(wid, "")
        return f"{root}/{path}" if root and path else root or path

    def path(self, top_path, name=""):
        """The node at a top path, or the symbol name inside the file there."""
        nid = self.by_path.get(posixpath.normpath(top_path) if top_path else top_path)
        if nid and name:
            nid = f"{nid}#{name}"
        return nid if nid in self.ids else None


def _clean(ref):
    ref = ref.strip().removeprefix("./")
    ref = re.sub(r":\d+(?:-\d+)?$", "", ref)  # path:12 or path:12-30
    return ref.removesuffix("()").rstrip("/")


def mentions(targets, doc_top, ws_root, text):
    """{target id: confidence} for the paths and names a doc's text refers to."""
    found = {}
    spans, links = references(text)
    for span in spans:
        ref = _clean(span)
        if not ref or " " in ref:
            continue
        path, _, name = ref.partition("#")
        hit = (ws_root and targets.path(f"{ws_root}/{path}", name)) or targets.path(path, name)
        if hit:
            found[hit] = PATH_CONFIDENCE
            continue
        named = targets.by_name.get(ref, [])
        if len(named) == 1:
            found.setdefault(named[0], NAME_CONFIDENCE)
    for link in links:
        if re.match(r"^[a-z][a-z0-9+.-]*:", link, re.I):  # http:, mailto:, vscode: ...
            continue
        path, _, anchor = link.partition("#")
        path = _clean(path.split("?")[0])
        if not path:
            continue
        base = ws_root if path.startswith("/") else posixpath.dirname(doc_top)
        full = posixpath.join(base, path.lstrip("/"))
        hit = (anchor and targets.path(full, anchor)) or targets.path(full)  # else a heading anchor
        if hit:
            found[hit] = PATH_CONFIDENCE
    return found


def index(conn, root):
    """Set doc titles, put title and body into the search index, and replace `mentions` edges."""
    targets = _Targets(conn)
    titles, search, edges = [], [], []
    for nid, wid, path, name in conn.execute(
            "SELECT id, workspace_id, path, name FROM nodes WHERE kind = 'doc'").fetchall():
        top = targets.top(wid, path)
        try:
            text = (root / top).read_text(errors="replace")
        except OSError:
            continue
        heading = title(text)
        titles.append((heading, nid))
        body = front_matter(text)[1]
        # ponytail: body is cut at a fixed size; index more if long docs miss hits.
        search.append((f"{name} {heading or ''}".strip(), body[:SEARCH_TEXT_LIMIT], nid))
        ws_root = targets.ws_root.get(wid, "")
        for dst, confidence in mentions(targets, top, ws_root, text).items():
            if dst != nid:
                edges.append((nid, dst, confidence))
    # The title is the doc node's `doc` column; the body lives only in its search row.
    conn.executemany("UPDATE nodes SET doc = ? WHERE id = ?", titles)
    # The id column is UNINDEXED, so look rows up by rowid instead of scanning per doc.
    rowids = dict(conn.execute("SELECT id, rowid FROM search"))
    conn.executemany("UPDATE search SET name = ?, doc = ? WHERE rowid = ?",
                     [(name, body, rowids[nid]) for name, body, nid in search if nid in rowids])
    conn.execute("DELETE FROM edges WHERE kind = 'mentions' AND source = 'markdown'")
    conn.executemany(
        "INSERT INTO edges (src, dst, kind, source, confidence) VALUES (?, ?, 'mentions', 'markdown', ?)", edges)
