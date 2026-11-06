"""Normalise HTTP paths and extract path segments."""


def segments(path):
    return [part for part in (path or "").split("/") if part]


def is_param(segment):
    return len(segment) >= 2 and segment[0] == "{" and segment[-1] == "}"


def has_literal(path):
    """True when the path has a segment that is not a parameter."""
    return any(not is_param(part) for part in segments(path))


def is_api_href(path):
    """True when a normalised path is `/api` or `/api/...`, so an anchor may call it."""
    return bool(path) and has_literal(path) and (path == "/api" or path.startswith("/api/"))


def _norm_seg(segment):
    if segment.startswith(":") and segment[1:].replace("_", "").isalnum() and segment[1:2].isalpha():
        return "{" + segment[1:] + "}"
    if segment.startswith("{") and segment.endswith("}"):
        body = segment[1:-1]
        if body.startswith("*"):
            body = body[1:]
        name, _, _rest = body.partition(":")
        if name and name.replace("_", "").isalnum() and name[0].isalpha():
            return "{" + name + "}"
    return segment


def normalise(path):
    """Drop the query and fragment, keep parameter names, strip a trailing slash."""
    if path is None:
        return None
    text = str(path).split("?", 1)[0].split("#", 1)[0].strip()
    if not text:
        return None
    if not text.startswith("/"):
        text = "/" + text
    parts = [_norm_seg(part) for part in text.split("/") if part]
    if not parts:
        return "/"
    return "/" + "/".join(parts)


def join_path(*parts):
    """Join prefix pieces. `""` and `"/"` add no segment, so a bare slash is not a segment."""
    segs = []
    for part in parts:
        if part is None:
            continue
        text = str(part).strip()
        if not text or text == "/":
            continue
        for seg in text.split("/"):
            if seg:
                segs.append(_norm_seg(seg))
    if not segs:
        return "/"
    return "/" + "/".join(segs)


def from_pieces(pieces):
    """Build a path from literal pieces and template holes (`None`).

    A leading hole followed by `/` is a base URL and is dropped. A hole that is
    a whole segment becomes `{param}`. A hole glued to a literal, or only
    followed by the end or a query, is dropped (`mine${suffix}`, `revisions${qs}`).
    The query string and the fragment are dropped.
    """
    parts = list(pieces or [])
    if parts and parts[0] is None:
        rest = "".join(part for part in parts[1:] if isinstance(part, str))
        if rest.startswith("/"):
            while parts and parts[0] is None:
                parts.pop(0)
    out = ""
    index = 0
    count = len(parts)
    while index < count:
        part = parts[index]
        if isinstance(part, str):
            stop = len(part)
            for mark in "?#":
                at = part.find(mark)
                if at != -1:
                    stop = min(stop, at)
            out += part[:stop]
            if stop < len(part):
                break
            index += 1
            continue
        nxt = index + 1
        while nxt < count and parts[nxt] is None:
            nxt += 1
        following = parts[nxt] if nxt < count else ""
        boundary = out == "" or out.endswith("/")
        if following[:1] in "?#":
            if boundary:
                out += "{param}"
            break
        if following.startswith("/"):
            if out and not boundary:
                out += "/"
            out += "{param}"
            index = nxt
            continue
        if following == "" and boundary:
            out += "{param}"
            break
        index += 1
    return normalise(out)
