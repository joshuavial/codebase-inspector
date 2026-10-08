"""Print one Keep a Changelog section.

Usage: changelog_notes.py v0.1.0 CHANGELOG.md
"""

import sys
from pathlib import Path


def section(text, version):
    """The `## [version]` block, up to the next `## ` heading."""
    ver = version[1:] if str(version).startswith("v") else str(version)
    lines = text.splitlines()
    start = None
    for index, line in enumerate(lines):
        if line.startswith(f"## [{ver}]"):
            start = index
            break
    if start is None:
        raise SystemExit(f"CHANGELOG has no section for {ver}")
    end = len(lines)
    for index in range(start + 1, len(lines)):
        if lines[index].startswith("## "):
            end = index
            break
    return "\n".join(lines[start:end]).strip() + "\n"


def main(argv):
    if len(argv) != 3:
        raise SystemExit("usage: changelog_notes.py VERSION CHANGELOG")
    sys.stdout.write(section(Path(argv[2]).read_text(), argv[1]))


if __name__ == "__main__":
    main(sys.argv)
