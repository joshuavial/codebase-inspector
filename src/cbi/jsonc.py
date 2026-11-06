"""JSON with comments and trailing comma support."""

import json
import re


def jsonc_loads(text: str):
    """Parse tsconfig-style JSON: comments and trailing commas allowed."""
    strings_or_comments = r'"(?:\\.|[^"\\])*"|//[^\n]*|/\*.*?\*/'
    text = re.sub(strings_or_comments, lambda m: m.group(0) if m.group(0)[0] == '"' else "", text, flags=re.S)
    text = re.sub(r'"(?:\\.|[^"\\])*"|,(\s*[}\]])', lambda m: m.group(1) if m.group(1) is not None else m.group(0), text)
    return json.loads(text)


_jsonc = jsonc_loads
parse_jsonc = jsonc_loads
