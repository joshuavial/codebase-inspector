"""Database schema and table-use facts derived without executing target code.

Tables and columns are ordinary model nodes. Foreign keys and code uses are
edges with source ``data``. This module stores semantic facts and source
evidence only; diagram layout belongs to the viewer.
"""

import json
import re
from collections import defaultdict


LAYOUT_KEYS = {"x", "y", "width", "height", "position", "route", "points"}

_IDENT = r'(?:"(?:[^"]|"")+"|`[^`]+`|\[[^]]+\]|[A-Za-z_][\w$]*)'
_QUALIFIED = rf"{_IDENT}(?:\s*\.\s*{_IDENT})?"
_CREATE = re.compile(rf"\bCREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?(?P<name>{_QUALIFIED})\s*\(", re.I)
_ALTER_FK = re.compile(
    rf"\bALTER\s+TABLE\s+(?:ONLY\s+)?(?P<table>{_QUALIFIED}).*?"
    rf"FOREIGN\s+KEY\s*\((?P<cols>[^)]+)\)\s*REFERENCES\s+"
    rf"(?P<target>{_QUALIFIED})\s*\((?P<targets>[^)]+)\)", re.I | re.S)
_CONSTRAINT = re.compile(r"^(?:CONSTRAINT\s+\S+\s+)?(PRIMARY\s+KEY|FOREIGN\s+KEY|UNIQUE|CHECK)\b", re.I)
_STOP_TYPE = re.compile(
    r"\s+(?:CONSTRAINT|PRIMARY\s+KEY|NOT\s+NULL|NULL|UNIQUE|DEFAULT|REFERENCES|CHECK|COLLATE|GENERATED)\b",
    re.I)
_PY_CLASS = re.compile(r"^class\s+(\w+)\s*\(([^)]*)\)\s*:", re.M)
_CS_CLASS = re.compile(r"(?:\[Table\(\"([^\"]+)\"\)\]\s*)?(?:public\s+)?class\s+(\w+)[^{]*\{", re.M)
_TS_ENTITY = re.compile(r"@Entity\s*\(\s*(?:[\"']([^\"']+)[\"'])?[^)]*\)\s*(?:export\s+)?class\s+(\w+)\s*\{", re.M)


def _unquote(value):
    value = value.strip()
    if len(value) >= 2 and (value[0], value[-1]) in (("\"", "\""), ("`", "`"), ("[", "]")):
        value = value[1:-1]
    return value.replace('""', '"')


def _name(value):
    return ".".join(_unquote(part) for part in re.split(r"\s*\.\s*", value.strip()))


def _id_name(value):
    return re.sub(r"[^a-z0-9_.-]+", "_", value.lower()).strip("_")


def table_id(workspace_id, name):
    return f"{workspace_id}:table:{_id_name(name)}"


def column_id(workspace_id, table, column):
    return f"{table_id(workspace_id, table)}#{_id_name(column)}"


def _comments(text):
    text = re.sub(r"/\*.*?\*/", lambda m: "\n" * m.group(0).count("\n"), text, flags=re.S)
    return re.sub(r"--[^\n]*", "", text)


def _balanced(text, opening):
    depth = 1
    quote = None
    index = opening + 1
    while index < len(text):
        char = text[index]
        if quote:
            if char == quote:
                if index + 1 < len(text) and text[index + 1] == quote:
                    index += 2
                    continue
                quote = None
        elif char in ("'", '"', "`"):
            quote = char
        elif char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0:
                return text[opening + 1:index], index
        index += 1
    return text[opening + 1:], len(text)


def _split(value):
    out = []
    start = depth = 0
    quote = None
    for index, char in enumerate(value):
        if quote:
            if char == quote:
                quote = None
        elif char in ("'", '"', "`"):
            quote = char
        elif char == "(":
            depth += 1
        elif char == ")":
            depth = max(0, depth - 1)
        elif char == "," and depth == 0:
            out.append(value[start:index].strip())
            start = index + 1
    tail = value[start:].strip()
    if tail:
        out.append(tail)
    return out


def _names(value):
    return [_name(part) for part in _split(value) if part.strip()]


def _constraint(item):
    head = re.sub(r"^CONSTRAINT\s+\S+\s+", "", item.strip(), flags=re.I)
    primary = re.match(r"PRIMARY\s+KEY\s*\(([^)]+)\)", head, re.I | re.S)
    if primary:
        return {"kind": "primary", "columns": _names(primary.group(1))}
    unique = re.match(r"UNIQUE\s*\(([^)]+)\)", head, re.I | re.S)
    if unique:
        return {"kind": "unique", "columns": _names(unique.group(1))}
    foreign = re.match(
        rf"FOREIGN\s+KEY\s*\(([^)]+)\)\s*REFERENCES\s+({_QUALIFIED})\s*\(([^)]+)\)",
        head, re.I | re.S)
    if foreign:
        return {"kind": "foreign", "columns": _names(foreign.group(1)),
                "table": _name(foreign.group(2)), "targets": _names(foreign.group(3))}
    return None


def _column(item):
    match = re.match(rf"\s*(?P<name>{_IDENT})\s+(?P<rest>.+)$", item, re.S)
    if not match:
        return None
    rest = match.group("rest").strip()
    stop = _STOP_TYPE.search(" " + rest)
    type_name = rest[:max(0, stop.start() - 1)].strip() if stop else rest
    if not type_name:
        return None
    default = re.search(
        r"\bDEFAULT\s+(.+?)(?=\s+(?:CONSTRAINT|PRIMARY|NOT\s+NULL|NULL|UNIQUE|REFERENCES|CHECK)\b|$)",
        rest, re.I | re.S)
    ref = re.search(rf"\bREFERENCES\s+({_QUALIFIED})\s*\(([^)]+)\)", rest, re.I | re.S)
    return {
        "name": _unquote(match.group("name")), "type": re.sub(r"\s+", " ", type_name),
        "nullable": not bool(re.search(r"\bNOT\s+NULL\b|\bPRIMARY\s+KEY\b", rest, re.I)),
        "default": default.group(1).strip() if default else None,
        "primary_key": bool(re.search(r"\bPRIMARY\s+KEY\b", rest, re.I)),
        "unique": bool(re.search(r"\bUNIQUE\b", rest, re.I)),
        "reference": (_name(ref.group(1)), _names(ref.group(2))[0]) if ref else None,
    }


def parse_sql(text, path):
    """Return table declarations from one SQL file."""
    clean = _comments(text)
    tables = []
    for match in _CREATE.finditer(clean):
        body, _end = _balanced(clean, match.end() - 1)
        table = {"name": _name(match.group("name")), "path": path,
                 "line": clean.count("\n", 0, match.start()) + 1, "columns": [], "constraints": []}
        for item in _split(body):
            if _CONSTRAINT.match(item):
                constraint = _constraint(item)
                if constraint:
                    table["constraints"].append(constraint)
            else:
                column = _column(item)
                if column:
                    table["columns"].append(column)
        tables.append(table)
    for match in _ALTER_FK.finditer(clean):
        tables.append({
            "name": _name(match.group("table")), "path": path,
            "line": clean.count("\n", 0, match.start()) + 1, "columns": [],
            "constraints": [{"kind": "foreign", "columns": _names(match.group("cols")),
                             "table": _name(match.group("target")),
                             "targets": _names(match.group("targets"))}],
        })
    return tables


def _block(text, start, indent=None):
    """A brace block, or a Python indentation block after ``start``."""
    if indent is None:
        opening = start if text[start:start + 1] == "{" else start - 1 if text[start - 1:start] == "{" else text.find("{", start)
        if opening < 0:
            return "", start
        body, end = _balanced(text, opening)
        return body, end
    lines = text[start:].splitlines(True)
    kept = []
    offset = start
    for line in lines:
        if line.strip() and len(line) - len(line.lstrip()) <= indent:
            break
        kept.append(line)
        offset += len(line)
    return "".join(kept), offset


def _decl(name, path, line, framework, model=None):
    return {"name": name, "path": path, "line": line, "framework": framework,
            "model": model, "columns": [], "constraints": []}


def _orm_column(name, type_name, *, nullable=True, primary=False, unique=False, reference=None):
    return {"name": name, "type": type_name, "nullable": nullable, "default": None,
            "primary_key": primary, "unique": unique, "reference": reference}


def parse_sqlalchemy(text, path):
    found = []
    for match in _PY_CLASS.finditer(text):
        if not any(base.strip().endswith(("Base", "DeclarativeBase")) for base in match.group(2).split(",")):
            continue
        indent = len(text[text.rfind("\n", 0, match.start()) + 1:match.start()])
        body, _end = _block(text, match.end(), indent)
        named = re.search(r"^\s*__tablename__\s*=\s*[\"']([^\"']+)[\"']", body, re.M)
        table = _decl(named.group(1) if named else match.group(1).lower(), path,
                      text.count("\n", 0, match.start()) + 1, "sqlalchemy", match.group(1))
        for row in re.finditer(r"^\s*(\w+)\s*(?::[^=\n]+)?=\s*(?:Column|mapped_column)\s*\(([^\n]*)", body, re.M):
            args = row.group(2)
            type_match = re.match(r"\s*([\w.]+(?:\([^)]*\))?)", args)
            type_name = type_match.group(1) if type_match and not type_match.group(1).startswith("ForeignKey") else ""
            foreign = re.search(r"ForeignKey\s*\(\s*[\"']([^\"']+)\.([^\"']+)[\"']", args)
            table["columns"].append(_orm_column(
                row.group(1), type_name,
                nullable=not bool(re.search(r"nullable\s*=\s*False|primary_key\s*=\s*True", args)),
                primary=bool(re.search(r"primary_key\s*=\s*True", args)),
                unique=bool(re.search(r"unique\s*=\s*True", args)),
                reference=(foreign.group(1), foreign.group(2)) if foreign else None))
        found.append(table)
    return found


def parse_django(text, path):
    found = []
    models = {}
    for match in _PY_CLASS.finditer(text):
        if "models.Model" not in match.group(2) and match.group(2).strip() != "Model":
            continue
        indent = len(text[text.rfind("\n", 0, match.start()) + 1:match.start()])
        body, _end = _block(text, match.end(), indent)
        named = re.search(r"^\s*db_table\s*=\s*[\"']([^\"']+)[\"']", body, re.M)
        name = named.group(1) if named else match.group(1).lower()
        models[match.group(1)] = name
        table = _decl(name, path, text.count("\n", 0, match.start()) + 1, "django", match.group(1))
        for row in re.finditer(r"^\s*(\w+)\s*=\s*models\.(\w+)\s*\(([^\n]*)", body, re.M):
            field, kind, args = row.groups()
            primary = "primary_key=True" in args.replace(" ", "")
            unique = "unique=True" in args.replace(" ", "")
            nullable = "null=True" in args.replace(" ", "") and not primary
            reference = None
            column = field
            if kind in ("ForeignKey", "OneToOneField"):
                target = re.match(r"\s*(?:[\"']([^\"']+)[\"']|(\w+))", args)
                if target:
                    target_model = (target.group(1) or target.group(2)).rsplit(".", 1)[-1]
                    reference = (target_model.lower(), "id")
                db_column = re.search(r"db_column\s*=\s*[\"']([^\"']+)[\"']", args)
                column = db_column.group(1) if db_column else field + "_id"
            table["columns"].append(_orm_column(
                column, kind.removesuffix("Field"), nullable=nullable,
                primary=primary, unique=unique or kind == "OneToOneField", reference=reference))
        if not any(column["primary_key"] for column in table["columns"]):
            table["columns"].insert(0, _orm_column("id", "Auto", nullable=False, primary=True))
        found.append(table)
    for table in found:
        for column in table["columns"]:
            ref = column.get("reference")
            if ref and ref[0] in {name.lower(): db for name, db in models.items()}:
                column["reference"] = ({name.lower(): db for name, db in models.items()}[ref[0]], ref[1])
    return found


def parse_prisma(text, path):
    found = []
    models = {match.group(1): (re.search(r'@@map\(\s*"([^"]+)"\s*\)', match.group(2)) or [None, match.group(1)])[1]
              for match in re.finditer(r"\bmodel\s+(\w+)\s*\{(.*?)\}", text, re.S)}
    for match in re.finditer(r"\bmodel\s+(\w+)\s*\{(.*?)\}", text, re.S):
        model, body = match.groups()
        table = _decl(models[model], path, text.count("\n", 0, match.start()) + 1, "prisma", model)
        relations = []
        field_names = {}
        for line in body.splitlines():
            line = line.split("//", 1)[0].strip()
            row = re.match(r"(\w+)\s+([\w\[\]]+)([?]?)\s*(.*)", line)
            if not row or row.group(1).startswith("@@"):
                continue
            field, type_name, optional, attrs = row.groups()
            relation = re.search(r"@relation\s*\(.*?fields\s*:\s*\[([^]]+)\].*?references\s*:\s*\[([^]]+)\]", attrs)
            if relation and type_name.rstrip("[]") in models:
                relations.append((_names(relation.group(1)), models[type_name.rstrip("[]")], _names(relation.group(2))))
                continue
            if type_name.rstrip("[]") in models:
                continue
            mapped = re.search(r'@map\(\s*"([^"]+)"\s*\)', attrs)
            column_name = mapped.group(1) if mapped else field
            field_names[field] = column_name
            table["columns"].append(_orm_column(
                column_name, type_name, nullable=bool(optional),
                primary="@id" in attrs, unique="@unique" in attrs))
        for locals_, target, targets in relations:
            table["constraints"].append({"kind": "foreign", "columns": [field_names.get(name, name) for name in locals_],
                                         "table": target, "targets": targets})
        found.append(table)
    return found


def parse_typeorm(text, path):
    found = []
    classes = {match.group(2): match.group(1) or match.group(2).lower() for match in _TS_ENTITY.finditer(text)}
    for match in _TS_ENTITY.finditer(text):
        body, _end = _block(text, match.end())
        model = match.group(2)
        table = _decl(classes[model], path, text.count("\n", 0, match.start()) + 1, "typeorm", model)
        decorators = []
        for line in body.splitlines():
            stripped = line.strip()
            if stripped.startswith("@"):
                decorators.append(stripped)
                continue
            prop = re.match(r"(?:public\s+)?(\w+)[!?]?\s*:\s*([^;=]+)", stripped)
            if not prop:
                continue
            joined = " ".join(decorators)
            decorators = []
            field, type_name = prop.group(1), prop.group(2).strip()
            rel = re.search(r"@(?:ManyToOne|OneToOne)\s*\(\s*\(\)\s*=>\s*(\w+)", joined)
            if rel:
                join = re.search(r"@JoinColumn\s*\(\s*\{[^}]*name\s*:\s*[\"']([^\"']+)", joined)
                target = classes.get(rel.group(1), rel.group(1).lower())
                table["columns"].append(_orm_column(join.group(1) if join else field + "Id", "relation",
                                                     reference=(target, "id")))
                continue
            if not re.search(r"@(Column|PrimaryColumn|PrimaryGeneratedColumn)\b", joined):
                continue
            named = re.search(r"@(?!JoinColumn)\w*Column\s*\(\s*[\"']([^\"']+)[\"']", joined)
            table["columns"].append(_orm_column(
                named.group(1) if named else field, type_name,
                nullable=bool(re.search(r"nullable\s*:\s*true", joined)),
                primary=bool(re.search(r"@Primary(?:Generated)?Column", joined)),
                unique=bool(re.search(r"unique\s*:\s*true", joined))))
        found.append(table)
    return found


def parse_ef_core(text, path):
    sets = {typ: name for typ, name in re.findall(r"DbSet\s*<\s*(\w+)\s*>\s+(\w+)", text)}
    classes = {}
    matches = list(_CS_CLASS.finditer(text))
    for match in matches:
        if match.group(2).endswith("Context"):
            continue
        classes[match.group(2)] = match.group(1) or sets.get(match.group(2)) or match.group(2)
    found = []
    for match in matches:
        model = match.group(2)
        if model not in classes:
            continue
        body, _end = _block(text, match.end())
        table = _decl(classes[model], path, text.count("\n", 0, match.start()) + 1, "ef-core", model)
        props = list(re.finditer(r"(?:(\[Key\])\s*)?public\s+([\w?<>]+)\s+(\w+)\s*\{\s*get;\s*set;\s*\}", body))
        for row in props:
            keyed, type_name, field = row.groups()
            if type_name.rstrip("?") in classes:
                continue
            primary = bool(keyed) or field in ("Id", model + "Id")
            ref_model = field[:-2] if field.endswith("Id") and field[:-2] in classes else None
            table["columns"].append(_orm_column(
                field, type_name.rstrip("?"), nullable=type_name.endswith("?") and not primary,
                primary=primary, reference=(classes[ref_model], "Id") if ref_model else None))
        found.append(table)
    return found


def parse_orm(text, path):
    """Return ORM schema declarations recognised in one tracked file."""
    lower = text.lower()
    out = []
    if path.endswith(".prisma"):
        out.extend(parse_prisma(text, path))
    elif path.endswith(".py"):
        if "column(" in lower or "mapped_column(" in lower:
            out.extend(parse_sqlalchemy(text, path))
        if "models.model" in lower:
            out.extend(parse_django(text, path))
    elif path.endswith((".ts", ".tsx", ".js", ".jsx")) and "@entity" in lower:
        out.extend(parse_typeorm(text, path))
    elif path.endswith(".cs") and ("dbset<" in lower or "[table(" in lower):
        out.extend(parse_ef_core(text, path))
    return out


def _string_literals(text):
    """Yield (literal contents, one-based line) while skipping source comments."""
    index = 0
    line = 1
    while index < len(text):
        if text.startswith("//", index) or text[index] == "#":
            end = text.find("\n", index)
            if end < 0:
                return
            index = end
            continue
        if text.startswith("/*", index):
            end = text.find("*/", index + 2)
            end = len(text) if end < 0 else end + 2
            line += text.count("\n", index, end)
            index = end
            continue
        quote = text[index]
        if quote not in ("'", '"', "`"):
            if quote == "\n":
                line += 1
            index += 1
            continue
        start_line = line
        triple = quote != "`" and text.startswith(quote * 3, index)
        mark = quote * 3 if triple else quote
        index += len(mark)
        out = []
        while index < len(text):
            if text.startswith(mark, index):
                index += len(mark)
                break
            char = text[index]
            if char == "\\" and quote != "`" and index + 1 < len(text):
                out.extend((char, text[index + 1]))
                index += 2
                continue
            out.append(char)
            if char == "\n":
                line += 1
            index += 1
        yield "".join(out), start_line


def _without_comments(text):
    """Mask comments while retaining line offsets and string contents."""
    chars = list(text)
    index = 0
    quote = None
    while index < len(chars):
        if quote:
            if chars[index] == "\\" and quote != "`":
                index += 2
                continue
            if chars[index] == quote:
                quote = None
            index += 1
            continue
        if chars[index] in ("'", '"', "`"):
            quote = chars[index]
            index += 1
            continue
        if text.startswith("//", index) or chars[index] == "#":
            end = text.find("\n", index)
            end = len(text) if end < 0 else end
            for pos in range(index, end):
                chars[pos] = " "
            index = end
            continue
        if text.startswith("/*", index):
            end = text.find("*/", index + 2)
            end = len(text) if end < 0 else end + 2
            for pos in range(index, end):
                if chars[pos] != "\n":
                    chars[pos] = " "
            index = end
            continue
        index += 1
    return "".join(chars)


def _table_lookup(tables):
    lookup = {}
    for key, table in tables.items():
        names = {key, table["name"].lower(), table["name"].rsplit(".", 1)[-1].lower()}
        for model in table.get("models", []):
            names.update((model.lower(), model[:1].lower() + model[1:]))
        for name in list(names):
            if name.endswith("s"):
                names.add(name[:-1])
            else:
                names.add(name + "s")
        for name in names:
            lookup.setdefault(name.lower(), table)
    return lookup


def _sql_uses(text, lookup):
    found = []
    for literal, line in _string_literals(text):
        for match in re.finditer(rf"\b(?:FROM|JOIN)\s+({_QUALIFIED})", literal, re.I):
            table = lookup.get(_name(match.group(1)).lower())
            if table:
                found.append(("reads_table", table, line + literal.count("\n", 0, match.start()), "sql"))
        for pattern in (rf"\bINSERT\s+INTO\s+({_QUALIFIED})", rf"\bUPDATE\s+({_QUALIFIED})",
                        rf"\bDELETE\s+FROM\s+({_QUALIFIED})"):
            for match in re.finditer(pattern, literal, re.I):
                table = lookup.get(_name(match.group(1)).lower())
                if table:
                    found.append(("writes_table", table, line + literal.count("\n", 0, match.start()), "sql"))
    return found


def _orm_uses(text, lookup):
    clean = _without_comments(text)
    found = []

    def add(pattern, kind, via, flags=0, table_group=1):
        for match in re.finditer(pattern, clean, flags):
            table = lookup.get(match.group(table_group).lower())
            if table:
                found.append((kind, table, clean.count("\n", 0, match.start()) + 1, via))

    name = r"([A-Za-z_]\w*)"
    add(rf"\b(?:select|query)\s*\(\s*{name}\b", "reads_table", "orm", re.I)
    add(rf"\b{name}\.objects\.(?:all|filter|get|exclude|values|values_list|select_related|prefetch_related|count|exists)\b",
        "reads_table", "django", re.I)
    add(rf"\b{name}\.query\.(?:all|filter|get|first|one|count)\b", "reads_table", "sqlalchemy", re.I)
    add(rf"\b{name}\.objects\.(?:create|bulk_create|update|get_or_create|update_or_create)\b",
        "writes_table", "django", re.I)
    add(rf"\b(?:session|db)\.(?:add|merge|delete)\s*\(\s*{name}\b", "writes_table", "sqlalchemy", re.I)
    add(rf"\b(?:prisma|client|db)\.{name}\.(?:find\w*|count|aggregate|groupBy)\b",
        "reads_table", "prisma", re.I)
    add(rf"\b(?:prisma|client|db)\.{name}\.(?:create\w*|update\w*|delete\w*|upsert)\b",
        "writes_table", "prisma", re.I)
    add(rf"\bgetRepository\s*\(\s*{name}\s*\)\.(?:find\w*|count|exist)\b",
        "reads_table", "typeorm", re.I)
    add(rf"\bgetRepository\s*\(\s*{name}\s*\)\.(?:save|insert|update|delete|remove|upsert)\b",
        "writes_table", "typeorm", re.I)
    repositories = {var: model for var, model in re.findall(
        r"\b(\w+)\s*=\s*(?:\w+\.)?getRepository\s*\(\s*(\w+)\s*\)", clean)}
    for var, method in re.findall(r"\b(\w+)\.(find\w*|count|exist|save|insert|update|delete|remove|upsert)\s*\(", clean, re.I):
        model = repositories.get(var)
        table = lookup.get(model.lower()) if model else None
        if table:
            kind = "reads_table" if method.lower().startswith(("find", "count", "exist")) else "writes_table"
            at = re.search(rf"\b{re.escape(var)}\.{re.escape(method)}\s*\(", clean, re.I)
            found.append((kind, table, clean.count("\n", 0, at.start()) + 1, "typeorm"))
    add(rf"\b(?:_?context|db)\.{name}\.(?:Where|Select|Find|First|Single|Any|Count|ToList|AsNoTracking)\b",
        "reads_table", "ef-core")
    add(rf"\b(?:_?context|db)\.{name}\.(?:Add|AddRange|Update|Remove|RemoveRange)\b",
        "writes_table", "ef-core")
    supabase = list(re.finditer(r"\.from\s*\(\s*(['\"])([^'\"]+)\1\s*\)", clean))
    for index, match in enumerate(supabase):
        table = lookup.get(match.group(2).lower())
        if not table:
            continue
        end = supabase[index + 1].start() if index + 1 < len(supabase) else len(clean)
        semicolon = clean.find(";", match.end(), end)
        chain = clean[match.end():semicolon if semicolon >= 0 else min(end, match.end() + 2000)]
        if re.search(r"\.(?:insert|update|upsert|delete)\s*\(", chain, re.I):
            kind = "writes_table"
        elif re.search(r"\.(?:select|single|maybeSingle|limit|range|order|eq|neq|in)\s*\(", chain, re.I):
            kind = "reads_table"
        else:
            continue
        found.append((kind, table, clean.count("\n", 0, match.start()) + 1, "supabase"))
    return found


def parse_uses(text, tables):
    """Return (edge kind, table record, line, extraction form) for one code file."""
    lookup = _table_lookup(tables)
    return _sql_uses(text, lookup) + _orm_uses(text, lookup)


def _source(root, workspace_root, path):
    try:
        rel = "/".join(part for part in (workspace_root, path) if part)
        return (root / rel).read_text(errors="replace")
    except OSError:
        return None


def _merge(declarations):
    tables = {}
    for item in declarations:
        table = tables.setdefault(item["name"].lower(), {
            "name": item["name"], "sources": [], "models": [], "columns": {}, "foreign": []})
        source = {"path": item["path"], "line": item["line"],
                  "kind": item.get("framework") or "sql"}
        if source not in table["sources"]:
            table["sources"].append(source)
        if item.get("model") and item["model"] not in table["models"]:
            table["models"].append(item["model"])
        for raw in item["columns"]:
            column = table["columns"].setdefault(raw["name"].lower(), dict(raw, sources=[]))
            for key in ("type", "default", "reference"):
                if not column.get(key) and raw.get(key):
                    column[key] = raw[key]
            column["nullable"] = column.get("nullable", True) and raw.get("nullable", True)
            column["primary_key"] = column.get("primary_key", False) or raw.get("primary_key", False)
            column["unique"] = column.get("unique", False) or raw.get("unique", False)
            if source not in column["sources"]:
                column["sources"].append(source)
            if raw.get("reference"):
                table["foreign"].append((raw["name"], *raw["reference"], source))
        for constraint in item["constraints"]:
            for name in constraint.get("columns", []):
                column = table["columns"].setdefault(name.lower(), {
                    "name": name, "type": "", "nullable": True, "default": None,
                    "primary_key": False, "unique": False, "reference": None, "sources": [source]})
                if constraint["kind"] == "primary":
                    column["primary_key"], column["nullable"] = True, False
                elif constraint["kind"] == "unique":
                    column["unique"] = True
            if constraint["kind"] == "foreign":
                for local, target in zip(constraint["columns"], constraint["targets"]):
                    table["foreign"].append((local, constraint["table"], target, source))
    return tables


def _clean_attrs(attrs):
    assert not (LAYOUT_KEYS & set(attrs)), "database model contains viewer layout"
    return json.dumps(attrs, sort_keys=True)


def _owner(conn, workspace_id, path, line, file_id):
    rows = conn.execute(
        "SELECT id, start_line, end_line FROM nodes WHERE workspace_id = ? AND path = ? "
        "AND kind = 'symbol' AND start_line <= ? AND end_line >= ?",
        (workspace_id, path, line, line)).fetchall()
    if not rows:
        return file_id
    return min(rows, key=lambda row: ((row[2] or line) - (row[1] or line), row[0]))[0]


def apply(conn, root):
    """Replace derived SQL schema nodes and edges in ``conn``."""
    workspace_roots = {
        wid: (json.loads(attrs or "{}").get("root") or "")
        for wid, attrs in conn.execute("SELECT id, attrs FROM nodes WHERE kind = 'workspace'")}
    by_workspace = defaultdict(list)
    code_sources = defaultdict(list)
    for fid, wid, path in conn.execute(
            "SELECT id, workspace_id, path FROM nodes WHERE kind = 'file' ORDER BY id"):
        text = _source(root, workspace_roots.get(wid, ""), path)
        if text is not None:
            if path.lower().endswith(".sql"):
                by_workspace[wid].extend(parse_sql(text, path))
            if path.lower().endswith((".py", ".prisma", ".ts", ".tsx", ".js", ".jsx", ".cs")):
                by_workspace[wid].extend(parse_orm(text, path))
            if path.lower().endswith((".py", ".ts", ".tsx", ".js", ".jsx", ".cs")):
                code_sources[wid].append((fid, path, text))

    conn.execute("DELETE FROM edges WHERE source = 'data'")
    conn.execute("DELETE FROM nodes WHERE kind IN ('table', 'column')")
    for wid, raw in sorted(by_workspace.items()):
        tables = _merge(raw)
        for table in list(tables.values()):
            for _local, target_name, target_col, source in table["foreign"]:
                target = tables.setdefault(target_name.lower(), {
                    "name": target_name, "sources": [], "models": [], "columns": {}, "foreign": []})
                target["columns"].setdefault(target_col.lower(), {
                    "name": target_col, "type": "", "nullable": True, "default": None,
                    "primary_key": False, "unique": False, "reference": None, "sources": [source]})
        for table in sorted(tables.values(), key=lambda row: row["name"].lower()):
            tid = table_id(wid, table["name"])
            first = min(table["sources"], key=lambda row: (row["path"], row["line"])) if table["sources"] else {}
            attrs = {"sources": sorted(table["sources"], key=lambda row: (row["path"], row["line"]))}
            if table["models"]:
                attrs["models"] = sorted(table["models"])
            conn.execute(
                "INSERT INTO nodes (id, parent_id, kind, display_kind, name, workspace_id, path, start_line, attrs) "
                "VALUES (?, ?, 'table', 'table', ?, ?, ?, ?, ?)",
                (tid, wid, table["name"], wid, first.get("path"), first.get("line"), _clean_attrs(attrs)))
            for column in sorted(table["columns"].values(), key=lambda row: row["name"].lower()):
                cid = column_id(wid, table["name"], column["name"])
                sources = sorted(column["sources"], key=lambda row: (row["path"], row["line"]))
                cattrs = {key: value for key, value in column.items()
                          if key not in ("name", "sources") and value is not None}
                cattrs["sources"] = sources
                conn.execute(
                    "INSERT INTO nodes (id, parent_id, kind, display_kind, name, workspace_id, path, start_line, attrs) "
                    "VALUES (?, ?, 'column', 'column', ?, ?, ?, ?, ?)",
                    (cid, tid, column["name"], wid, first.get("path"), first.get("line"), _clean_attrs(cattrs)))
        ordinal = defaultdict(int)
        for table in sorted(tables.values(), key=lambda row: row["name"].lower()):
            for local, target_table, target_column, source in table["foreign"]:
                src = column_id(wid, table["name"], local)
                dst = column_id(wid, tables[target_table.lower()]["name"], target_column)
                slot = ordinal[(src, dst)]
                ordinal[(src, dst)] += 1
                conn.execute(
                    "INSERT INTO edges (src, dst, kind, source, confidence, weight, attrs, ordinal) "
                    "VALUES (?, ?, 'foreign_key', 'data', 1, 1, ?, ?)",
                    (src, dst, _clean_attrs({"source": source}), slot))
        uses = {}
        for fid, path, text in code_sources.get(wid, []):
            for kind, table, line, via in parse_uses(text, tables):
                src = _owner(conn, wid, path, line, fid)
                dst = table_id(wid, table["name"])
                key = (src, dst, kind)
                use = uses.setdefault(key, {"weight": 0, "locations": []})
                use["weight"] += 1
                location = {"path": path, "line": line, "via": via}
                if location not in use["locations"]:
                    use["locations"].append(location)
        for (src, dst, kind), use in sorted(uses.items()):
            conn.execute(
                "INSERT INTO edges (src, dst, kind, source, confidence, weight, attrs) "
                "VALUES (?, ?, ?, 'data', 1, ?, ?)",
                (src, dst, kind, use["weight"], _clean_attrs({
                    "locations": sorted(use["locations"], key=lambda row: (row["path"], row["line"], row["via"]))})))
