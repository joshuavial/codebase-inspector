"""Shared, read-only Python syntax for supplemental static test mechanisms."""
import ast


def python_modules(model):
    """Parse tracked Python source once per resolve; never import target modules."""
    if hasattr(model, '_test_python_modules'):
        return model._test_python_modules
    found = {}
    for fid, (wid, path, _role) in model.files.items():
        if not path.endswith('.py') or fid in model.symlinks:
            continue
        source = model.ws_dir[wid] / path
        try:
            found[fid] = ast.parse(source.read_bytes(), filename=path)
        except (OSError, SyntaxError, ValueError):
            continue
    model._test_python_modules = found
    return found


def owner(model, fid, node):
    """Innermost existing symbol/test containing a syntax node, otherwise its file."""
    line = getattr(node, 'lineno', 0)
    if not hasattr(model, '_test_spans_by_file'):
        model._test_spans_by_file = {}
        for nid, (start, end) in model.node_spans.items():
            model._test_spans_by_file.setdefault(model.nodes[nid][3], []).append((start, end, nid))
    candidates = [(end - start, nid) for start, end, nid in model._test_spans_by_file.get(fid, ())
                  if start <= line <= end]
    return min(candidates)[1] if candidates else fid
