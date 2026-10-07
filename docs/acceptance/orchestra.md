# orchestra acceptance

## Deliverable 4: test detection and linking

Run on 2026-10-07 on JV's Mac against `~/projects/orchestra` at `4684b75` (read-only), with the model outside the repo:

```
cd ~/projects/orchestra
uv run --project <codebase-inspector> cbi init --out "$OUT"
uv run --project <codebase-inspector> cbi scan --out "$OUT"   # cold
uv run --project <codebase-inspector> cbi scan --out "$OUT"   # no change
```

| Run | Time reported by `cbi scan` |
|---|---|
| Cold (enumerate, parse 100 TS/TSX files, resolve) | 0.4 s |
| No change (shortcut hit) | 0.0 s |

Test files detected: 32, as expected (9 in `electron/`, 12 in `service/`, 11 in `src/`), with 378 test cases.

| | Test files |
|---|---|
| Linked | 31 |
| Unmatched (`unmatched_test`) | 1 |

How the 31 are linked (a file can have several kinds):

| Link | Test files |
|---|---|
| Calls or literal reads (confidence 0.6 or more) | 28 |
| Imports a tracked code file (0.5) | 31 |
| File name match (0.8) | 25 |

The three linked only by imports and names are `src/components/LeadCard.test.ts`, `LeadSummary.test.ts` and `QuotaBar.test.ts`: they render components with `createElement(MissionView, ...)`, which passes the component as a value rather than calling it.

Unmatched:

- `src/styles.test.ts`: it imports only `node:assert/strict`, `node:fs` and `node:test` and reads `src/styles.css`, but `cbi init` put `src/styles.css` in `.cbi/ignore` as minified-looking, because five of its lines are over 1,000 characters (the longest is 3,005). Removing that line from `.cbi/ignore` links the test through the read.

Edges: 295 imports, 1,782 calls, 540 tests from the syntax tree and 25 from naming. No `ambiguous_call` diagnostics.

cbi wrote nothing in orchestra: `git status --porcelain` there lists only its own untracked `.worktrees/`, which predates these runs.
