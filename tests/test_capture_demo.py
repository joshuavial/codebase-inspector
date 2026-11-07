"""Tests for demo capture script helpers, verifying authentic parsing of review.md."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from capture_demo import extract_review_excerpt


SAMPLE_REVIEW_MD = """\
cbi://open?repo=/Users/jv/projects/synthetic-cli-repo&compare=e43af73000f5aaa0873bd517646b5e555fb6af95..728ce96ec8a33873eb268cec9a3d732bdfb1cbfe

<!-- cbi-review -->

# Review synthetic-cli-repo e43af73000f5..728ce96ec8a3

## Architecture summary: Whole diff

Summary pending: run cbi tasks

## Architecture summary: pkg

Summary pending: run cbi tasks

## Change overview

e43af73000f5 -> 728ce96ec8a3

1 file  +4 -3  symbols 3 changed  1 group

### 1. pkg `local:synthetic-cli-repo:pkg/`  changed

1 file  +4 -3  symbols 3 changed

Why: 7 changed lines

Drill down with `cbi diff e43af73000f5 728ce96ec8a3 --concept ID`, or `--detail` for every structural change.

Narrative task: `sc-f953334c` (open).

## Diagram

```mermaid
flowchart LR
  classDef added fill:#d8f3dc,stroke:#1b7f3a
  classDef removed fill:#fde2e1,stroke:#b42318
  classDef changed fill:#fff3c4,stroke:#b54708
  local_synthetic_cli_repo_pkg_["pkg"]:::changed
```

Not drawn: 1 folders.

## Details

### Structural counts

- 3 symbol-changed

### Deployables, packages and folders

#### pkg `local:synthetic-cli-repo:pkg/` (changed)

- symbol-changed  body  pkg/client.py#Client
  - pkg/client.py  Client
- symbol-changed  body  pkg/client.py#Client.request
  - pkg/client.py  request
- symbol-changed  signature+body  pkg/client.py#Client.__init__
  - pkg/client.py  __init__

### Untested changes

None.

### Changed integration points

None.

## Images

- before.png
- before.svg
- after.png
- after.svg
"""


def test_extract_review_excerpt_derives_truthful_summary_from_review_md():
    """Verify that change summary is parsed from review.md and strictly not the old hardcoded string."""
    data = extract_review_excerpt(SAMPLE_REVIEW_MD)

    # 1. Must equal the exact line under ## Change overview
    assert data["change_summary"] == "1 file  +4 -3  symbols 3 changed  1 group"

    # 2. Must NOT match the old hardcoded count from 9104be6
    old_hardcoded_string = "1 file  +3 -2  symbols 3 changed"
    assert data["change_summary"] != old_hardcoded_string
    assert "+4 -3" in data["change_summary"]
    assert "+3 -2" not in data["change_summary"]

    # 3. Verify compact Mermaid diagram has explicit omission indicator
    mermaid = data["mermaid_diagram"]
    assert "```mermaid" in mermaid
    assert "flowchart LR" in mermaid
    assert "... [3 classDef styling lines omitted for demo] ..." in mermaid
    assert 'local_synthetic_cli_repo_pkg_["pkg"]:::changed' in mermaid

    # 4. Verify changed symbols extracted
    symbols = data["changed_symbols"]
    assert "pkg/client.py#Client" in symbols
    assert "pkg/client.py#Client.request" in symbols
    assert "pkg/client.py#Client.__init__" in symbols


def test_extract_review_excerpt_raises_on_missing_overview():
    """Ensure parser fails gracefully when review.md lacks ## Change overview."""
    import pytest
    with pytest.raises(ValueError, match="Failed to find change summary line"):
        extract_review_excerpt("# Review\n\nNo overview section here.")
