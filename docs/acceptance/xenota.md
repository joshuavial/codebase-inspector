# xenota acceptance

## Deliverable 2: enumeration timing probe

Run on 2026-10-07 on JV's Mac against `~/projects/xenota` (read-only), with the model outside the repo:

```
cd ~/projects/xenota
uv run --project <codebase-inspector> cbi init --out "$OUT"
uv run --project <codebase-inspector> cbi scan --out "$OUT"   # cold
uv run --project <codebase-inspector> cbi scan --out "$OUT"   # no change
```

| Run | Time reported by `cbi scan` | Wall time incl. `uv run` |
|---|---|---|
| Cold (empty model, every file hashed) | 3.9 s | about 4.0 s |
| No change (shortcut hit) | 0.3 s | about 0.4 s |

The OS file cache was warm from earlier runs. `git status --porcelain` in xenota was the same before and after.

Tracked paths: 13,416 in xenota, 2,394 in xenon, 737 in handbook; books is not initialised. 447 tracked files were left out by `.cbi/ignore`, which `init` wrote with the fixed patterns plus one minified file (`design-system/_ds_bundle.js`) and no data dirs.

Counts by display kind:

| Display kind | Count |
|---|---|
| workspace | 4 (xenota, xenon with drift, handbook, books uninitialised) |
| folder | 1,058 |
| doc collection | 7 (`docs/` and `_ai/` and `.etude/` in xenota, `docs/` and `_ai/` in handbook, `docs/` and `.etude/` in xenon) |
| doc | 12,461 |
| source file | 654 |
| test file | 769 |
| file | 2,213 |
| symlink | 3 (`.agent/skills`, `.agents/skills`, `.claude/skills/retro`, not followed) |

`docs/research` sits inside the `docs/` doc collection, which is 97% research.
