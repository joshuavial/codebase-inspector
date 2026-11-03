"""Visible pytest mechanisms whose runtime registration cannot be inferred."""
import ast

from cbi.testing_paths import contexts, dotted
from cbi.testing_static import python_modules


def _literal_plugins(node):
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return True
    return isinstance(node, (ast.List, ast.Tuple)) and all(_literal_plugins(item) for item in node.elts)


def link(model):
    diagnostics = set()

    def record(fid, node, mechanism):
        diagnostics.add((fid, 'unsupported_test_mechanism',
                            f'{model.files[fid][1]}:{node.lineno}: {mechanism}; '
                            'runtime fixture registration/selection remains unresolved'))

    for fid, tree in python_modules(model).items():
        if model.files[fid][2] != 'test':
            continue
        aliases = {}
        for statement in tree.body:
            if isinstance(statement, ast.Import):
                aliases.update({a.asname or a.name: a.name for a in statement.names})
            elif isinstance(statement, ast.ImportFrom) and statement.module == 'pytest':
                aliases.update({a.asname or a.name: 'pytest.' + a.name for a in statement.names})
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and dotted(node.func, aliases) == 'pytest.fixture':
                if any(kw.arg == 'name' and not (isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, str))
                       for kw in node.keywords):
                    record(fid, node, 'dynamic_fixture_name')
            if isinstance(node, (ast.Assign, ast.AnnAssign)):
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                if any(isinstance(target, ast.Name) and target.id == 'pytest_plugins' for target in targets):
                    if not _literal_plugins(node.value):
                        record(fid, node, 'dynamic_plugin_registration')
    for context in contexts(model):
        call, name = context.call, context.name()
        if isinstance(call.func, ast.Attribute) and call.func.attr == 'getfixturevalue':
            # Only pytest's conventional request parameter is recognized. Other
            # objects may expose the same method without being pytest requests.
            if isinstance(call.func.value, ast.Name) and call.func.value.id == 'request':
                value = context.value(call.args[0]) if call.args else None
                if not isinstance(value, str):
                    record(context.fid, call, 'dynamic_fixture_selection')
        if name == 'pytest.fixture':
            if call.args:
                record(context.fid, call, 'fixture_factory')
            if any(kw.arg == 'name' and not isinstance(context.value(kw.value), str) for kw in call.keywords):
                record(context.fid, call, 'dynamic_fixture_name')
    return sorted(diagnostics)
