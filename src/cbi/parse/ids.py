"""Symbol node ID generation from qualified names and signatures."""

import hashlib
from collections import Counter


def symbol_ids(file_node_id, defs):
    """IDs for (qualified name, signature) pairs in source order.

    A qualified name used once gives `<file>#<name>`. Repeated names get a suffix
    of the first 8 hex characters of the signature's sha1; repeats with identical
    signatures add `~2`, `~3` by source order after that.
    """
    names = Counter(q for q, _ in defs)
    seen = Counter()
    out = []
    for qualname, signature in defs:
        key = qualname
        if names[qualname] > 1:
            key = f"{qualname}~{hashlib.sha1(signature.encode()).hexdigest()[:8]}"
            seen[key] += 1
            if seen[key] > 1:
                key = f"{key}~{seen[key]}"
        out.append(f"{file_node_id}#{key}")
    return out
