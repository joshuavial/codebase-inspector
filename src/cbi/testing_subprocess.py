"""Bind literal subprocess programs without executing a child or target code."""
import ast
import posixpath

from cbi.testing_static import owner, python_modules

OPERATIONS = {'run', 'Popen', 'call', 'check_call', 'check_output'}
INTERPRETERS = {'python', 'python3', 'node', 'bash', 'sh'}


def _name(node):
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = _name(node.value)
        return f'{base}.{node.attr}' if base else None
    return None


def _literal(node):
    return node.value if isinstance(node, ast.Constant) and isinstance(node.value, str) else None


def _scope_imports(node, line=None):
    aliases = {}
    pending = list(node.body)
    while pending:
        statement = pending.pop(0)
        if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
            continue
        if line is not None and getattr(statement, 'lineno', 0) > line:
            continue
        if isinstance(statement, ast.Import):
            for alias in statement.names:
                if alias.name in ('subprocess', 'sys'):
                    aliases[alias.asname or alias.name] = alias.name
        elif isinstance(statement, ast.ImportFrom) and statement.module in ('subprocess', 'sys'):
            for alias in statement.names:
                aliases[alias.asname or alias.name] = statement.module + '.' + alias.name
        elif isinstance(statement, (ast.Assign, ast.AnnAssign, ast.AugAssign, ast.NamedExpr)):
            targets = statement.targets if isinstance(statement, ast.Assign) else [statement.target]
            for target in targets:
                for part in ast.walk(target):
                    if isinstance(part, ast.Name):
                        aliases.pop(part.id, None)
        else:
            pending[0:0] = list(ast.iter_child_nodes(statement))
    return aliases


def _local_names(scope):
    found = set()
    pending = list(scope.body)
    while pending:
        child = pending.pop()
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            found.add(child.name)
            continue
        if isinstance(child, ast.Name) and isinstance(child.ctx, ast.Store):
            found.add(child.id)
        if not isinstance(child, ast.Lambda):
            pending.extend(ast.iter_child_nodes(child))
    return found


def link(model, edges, add):
    diagnostics = []
    for fid, tree in python_modules(model).items():
        if model.files[fid][2] != 'test':
            continue
        aliases = _scope_imports(tree)
        parents = {child: node for node in ast.walk(tree) for child in ast.iter_child_nodes(node)}
        for call in ast.walk(tree):
            if not isinstance(call, ast.Call):
                continue
            name = _name(call.func) or ''
            first, dot, rest = name.partition('.')
            local_aliases = dict(aliases)
            scopes = []
            ancestor = parents.get(call)
            while ancestor is not None:
                if isinstance(ancestor, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    scopes.append(ancestor)
                ancestor = parents.get(ancestor)
            for scope in reversed(scopes):
                arguments = [*scope.args.posonlyargs, *scope.args.args, *scope.args.kwonlyargs]
                arguments += [a for a in (scope.args.vararg, scope.args.kwarg) if a]
                for local in _local_names(scope) | {argument.arg for argument in arguments}:
                    local_aliases.pop(local, None)
                local_aliases.update(_scope_imports(scope, call.lineno))
            if first not in local_aliases:
                continue
            ancestor = parents.get(call)
            shadowed = False
            while ancestor is not None:
                if isinstance(ancestor, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
                    parameters = [*ancestor.args.posonlyargs, *ancestor.args.args, *ancestor.args.kwonlyargs]
                    parameters += [a for a in (ancestor.args.vararg, ancestor.args.kwarg) if a]
                    if any(a.arg == first for a in parameters):
                        shadowed = True
                        break
                ancestor = parents.get(ancestor)
            if shadowed:
                continue
            name = local_aliases.get(first, first) + (dot + rest if dot else '')
            if name not in {'subprocess.' + operation for operation in OPERATIONS}:
                continue
            args = call.args[0] if call.args else next((k.value for k in call.keywords if k.arg == 'args'), None)
            src = model.test_owner(owner(model, fid, call))
            targets = set()
            argv = list(args.elts) if isinstance(args, (ast.List, ast.Tuple)) else []
            shell = any(k.arg == 'shell' and not (isinstance(k.value, ast.Constant) and k.value.value is False)
                        for k in call.keywords)
            supported = False
            if argv and not shell:
                head = _name(argv[0]) or ''
                first, dot, rest = head.partition('.')
                head = local_aliases.get(first, first) + (dot + rest if dot else '')
                executable = _literal(argv[0])
                python = head == 'sys.executable' or (executable and posixpath.basename(executable) in {'python', 'python3'})
                offset = 1 if head == 'sys.executable' or (executable and posixpath.basename(executable) in INTERPRETERS) else 0
                program = _literal(argv[offset]) if len(argv) > offset else None
                if python and program == '-m' and len(argv) > offset + 1:
                    module = _literal(argv[offset + 1])
                    dst = model.spec(fid, module) if module else None
                    if dst:
                        targets.add(dst)
                    supported = bool(dst)
                elif python and program == '-c' and len(argv) > offset + 1:
                    source = _literal(argv[offset + 1])
                    try:
                        child = ast.parse(source) if source is not None else None
                    except SyntaxError:
                        child = None
                    if child:
                        for statement in ast.walk(child):
                            modules = [a.name for a in statement.names] if isinstance(statement, ast.Import) else (
                                [statement.module] if isinstance(statement, ast.ImportFrom) and statement.level == 0 else [])
                            for module in modules:
                                dst = model.spec(fid, module) if module else None
                                if dst:
                                    targets.add(dst)
                    # Inline code may use runtime paths/imports: visible imports are only partial evidence.
                    supported = False
                elif program and not program.startswith('-'):
                    dst = model.read_target(fid, program)
                    if dst:
                        targets.add(dst)
                    supported = bool(dst)
            for dst in sorted(targets):
                if dst != fid:
                    add(src, dst, 'tests', 'treesitter', 0.8, {'via': 'subprocess'})
            if not supported:
                path = model.files[fid][1]
                diagnostics.append((fid, 'unsupported_test_mechanism',
                                    f'{path}:{call.lineno}: subprocess execution boundary; '
                                    'only literal tracked programs/modules and visible inline imports can be linked; '
                                    'runtime child behavior remains unresolved'))
    return diagnostics
