"""Static viewer export: copies the viewer assets and writes the model as script files."""

import json
import shutil
from pathlib import Path

ASSETS = Path(__file__).parent / "viewer"
FIELDS = ("id", "parent_id", "kind", "display_kind", "name", "path", "start_line", "end_line", "loc",
          "signature", "doc", "summary")


def build(conn, out):
    """Write the viewer into out/. Returns the path of index.html."""
    out.mkdir(parents=True, exist_ok=True)
    for name in ("index.html", "app.js", "style.css"):
        shutil.copyfile(ASSETS / name, out / name)
    nodes = [
        {k: v for k, v in zip(FIELDS, row) if v is not None}
        for row in conn.execute(f"SELECT {', '.join(FIELDS)} FROM nodes ORDER BY id")
    ]
    # ponytail: every node in one file; deliverable 8 chunks symbols by group.
    (out / "data").mkdir(exist_ok=True)
    (out / "data" / "tree.js").write_text(f'cbiLoad("tree", {json.dumps({"nodes": nodes})});\n')
    return out / "index.html"
