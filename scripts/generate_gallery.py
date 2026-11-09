#!/usr/bin/env python3
"""CLI Review Gallery Generator for Codebase Inspector.

Backward-compatible entrypoint that delegates to `cbi.gallery`.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from cbi.gallery import (  # noqa: F401
    build_repo_review,
    build_repo_viewer,
    cmd_gallery,
    ensure_repo_scanned,
    extract_repo_metrics,
    extract_review_metadata,
    generate_gallery,
    load_gallery_config,
    main,
    parse_repo_spec,
    render_gallery_index,
    render_markdown_to_html,
    run_cbi,
)

if __name__ == "__main__":
    sys.exit(main())
