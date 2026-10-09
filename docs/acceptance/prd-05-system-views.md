# PRD-05 system views acceptance

Checked on 10 October 2026 against the read-only sample-apps and sample-saas repositories. Each run used this worktree's package through `uv run --project`, with `cbi init --out`, `cbi scan --out` and `cbi build --out` writing to a fresh temporary directory outside the source repository.

## Results

| Repository | Scan | Tables | Foreign keys | Reads | Writes | Endpoints | Endpoints with callers | Endpoints with tables |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| sample-apps | 10.1 s | 22 | 28 | 132 | 108 | 40 | 6 | 18 |
| sample-saas | 29.7 s | 92 | 118 | 1,396 | 1,151 | 466 | 204 | 228 |

The sample-apps check found two conventions that needed focused support. Next.js app-router endpoints are exported HTTP verb functions in `app/**/route.ts`, with the URL derived from the file path. Supabase table calls use `.from("table")` followed by select or mutation methods. Both now have fixture tests. The endpoint list includes routes inside an initialised content submodule because those files are part of the mapped workspace.

The two source repositories each had 23 pre-existing `git status --short` lines before the run and the same 23 lines afterwards. The mapper created no source-repository files.

## Visual check

Four 1600 by 1000 PNGs were captured through `cbi.render.viewer_png`, which uses the same isolated system Chrome path as `cbi render`:

- sample-apps Database overview, with 22 readable table cards, key labels and routed foreign-key lines.
- sample-apps API endpoint list, with method, path, note and the three top-level tabs visible.
- sample-saas Database overview, with all 92 tables fit into the canvas and pan and zoom controls visible.
- sample-saas API endpoint list, with notes from existing summaries and the method filter visible.

All four images were inspected. Focused browser tests separately select a table and an endpoint, check their drawers, exercise pan, zoom, fit, filtering, code and table jumps, the return chip and Esc.

## Verification

- Focused schema, HTTP, projection and browser tests: 28 passed after the target-repository findings were added.
- Full Python suite: 445 passed, 1 skipped.
- Desktop suite: 153 passed.
