# PRD-08: Change overview

Amends PRD-04 (`docs/prd-04-change-review.md`). The diff engine, comparison picker, review folder and base/head comparison remain. This increment changes how their results are presented.

## Problem

The comparison view has the facts but not the overview. It marks every changed concept on the full concept map and puts every structural change in one long panel. A reviewer must read the panel or inspect boxes one by one to discover the shape of the change. Relationships that did not change compete with the change itself.

A real comparison of codebase-inspector from `92c987d` to `494bacd` makes the problem visible. The range changes 22 files with 2,043 additions and 94 deletions. `cbi diff` groups 136 structural items under six concepts, led by 86 items in Release check. The top-level image does show Release check as added, but unchanged concepts and all of their outside relationships still take most of the canvas. The image does not say that the change adds one release-check capability across the CLI and desktop app, where most of the work is, or that the new HTTP boundary is the main integration to inspect.

The current outputs have related limits:

- `cbi diff` and `review.md` repeat each symbol and test. They are complete but slow to scan.
- The viewer's Changes panel repeats that inventory beside the whole map.
- Every changed container gets the same visual weight. A two-line edit and a new subsystem look alike.
- A relationship is either part of the whole map or a row in the inventory. It is not shown as local context for the selected change.
- The desktop Compare picker chooses the two versions well, but the result opens on the existing map rather than an overview of the change.

The first comparison screen should answer three questions in a few seconds:

1. Which concepts or modules changed?
2. How much did each one change?
3. Why does each change deserve attention?

The reviewer should then move from concept to module to file to function to changed lines without losing their place.

## Patterns from other tools

- [GitHub pull request review](https://docs.github.com/en/pull-requests/how-tos/review-pull-requests/reviewing-proposed-changes-in-a-pull-request) pairs purpose and summary with a file tree, filters, per-file diffs and viewed progress. It is strong from file to line, but its default hierarchy is the repository path rather than the system's concepts.
- [GitHub Copilot pull request summaries](https://docs.github.com/en/copilot/tutorials/explore-pull-requests) put a prose overview and linked key changes before inspection. The useful pattern is summary first and evidence links second. CBI keeps the factual overview deterministic and uses the existing optional `summarise-change` answer for authored intent.
- [Graphite review](https://graphite.com/docs/review-pull-requests) keeps timeline or file-tree context in a side tray, supplies direct jumps into a diff, and provides keyboard shortcuts and a focus mode. Its stack view also makes the current change's place in a larger sequence visible.
- [Reviewable's file matrix](https://docs.reviewable.io/files.html) compresses file history, churn, review state and direct diff navigation into one overview. It hides completed state until needed and keeps revision bounds explicit.
- [Gerrit's review UI](https://gerrit-review.googlesource.com/Documentation/user-review-ui.html) shows status and changed-line counts in the file list, expands a file in place, and keeps the compared patch sets visible.
- [CodeSee Review Maps](https://docs.codesee.io/docs/user-guide) show added, removed and modified files with their dependencies and unchanged impacted neighbours. The useful rule is to include unchanged nodes only when they give context to a changed node.
- Treemaps encode a hierarchy and a quantity in one compact surface. Research on [dynamic treemaps for software evolution](https://pure.rug.nl/ws/files/181266980/Quantitative_Comparison_of_Dynamic_Treemaps_for_Software_Evolution_Visualization.pdf) also shows the tradeoff: an unstable layout can move cells even when the underlying change is small. A change view must preserve a stable order or layout across base and head.

## Outcome

Comparison mode opens on a changed-first overview. It ranks the affected concepts, shows the relative size of their change, and gives a short factual reason to inspect each one. Selecting an item shows only relationships that touch that item. Opening it moves down one level, from concept to module to file to function to lines.

The same overview is used by the static viewer, desktop app, `cbi diff` and `cbi review`. The existing full concept map remains available as a secondary view.

Success signals:

- On the update-check comparison above, a reviewer identifies Release check as the main change, sees that it spans the CLI and desktop shell, and notices the new GitHub Releases HTTP integration without reading the full change list.
- A reviewer reaches any changed line in at most four drill actions from a concept card.
- At every level, unchanged items appear only when they are a parent, a direct caller or callee, a test, or the other end of a relationship touching the selected item.
- A large comparison remains useful when it changes dozens of concepts and hundreds of files.

## Overview options

### Option A: changed-concepts map

Show only changed concepts. Size each box by churn and colour it by change state. Add direct neighbours after a concept is selected.

```
Change: 22 files  +2,043 -94                    [List] [Map]

  +---------------------------+       +------------------+
  | Release check       added |------>| GitHub Releases  |
  | 5 files  +1,372 -0        | HTTP  | unchanged context|
  +---------------------------+       +------------------+
          | used by
    +-----------+  +---------------+
    | CLI       |  | Desktop shell |
    | +15 -3    |  | +220 -6       |
    +-----------+  +---------------+
```

Pros:

- Preserves the product's conceptual identity.
- Makes new or removed connections easy to notice.
- Reuses the current layout, marks and local drill behaviour.

Cons:

- Box area is hard to compare precisely.
- Labels and arrows crowd the view as the number of changed concepts grows.
- A map still needs text beside it to explain why a change matters.

### Option B: churn treemap

Pack concepts, modules and files into nested rectangles. Area is additions plus deletions. Colour shows added, removed or modified, with risk markers for integrations and untested code.

```
+----------------------------------------------------------------+
| Release check  +1,372                                          |
| +-----------------------+ +------------------+ +--------------+ |
| | desktop update-check  | | CLI update check | | tests        | |
| | +890                  | | +482             | | included     | |
| +-----------------------+ +------------------+ +--------------+ |
+-------------------------------+--------------------------------+
| Desktop shell +220 -6         | Static viewer +396 -81         |
+-------------------------------+--------------------------------+
```

Pros:

- Gives the fastest view of relative magnitude.
- Uses the full canvas and scales to many files.
- Nesting naturally exposes concept, module and file contribution.

Cons:

- Relationships have no natural place and become an overlay.
- Small but important integration or test changes can disappear.
- Layout movement between comparisons can imply change where there is none.
- Thin cells and labels become difficult to use at file and function levels.

### Option C: ranked change list with local maps

Rank concept cards by attention, then churn. Each card has a change bar, key facts and a small map containing the concept and only its direct context.

```
22 files  +2,043 -94   6 concepts   1 new integration   7 untested

1  Release check                                      added
   +1,372 -0  5 files  54 functions  26 tests
   New capability used by CLI and Desktop shell.
   HTTP -> GitHub Releases.  No changed function lacks a test.
   [CLI] ----uses----> [Release check] ----HTTP----> [GitHub Releases]

2  Desktop shell                                     changed
   +220 -6  6 files  9 functions  4 untested
   Adds the banner, update settings and download handoff.       [Open]
```

Pros:

- Answers what, how much and why in one scan.
- Sort order remains stable and useful for small or very large changes.
- Text, bars and counts work in the CLI, Markdown and viewer.
- Local maps retain relationship context without drawing the whole system.

Cons:

- Gives less immediate sense of the whole architecture than a large map.
- Cards take more vertical space than a treemap.
- Attention ordering needs a clear, deterministic rule.

## Recommendation

Use option C as the default overview, with option A as a Map toggle. Do not make the treemap a primary view.

The ranked overview answers the reviewer's first questions directly and transfers to every CBI output. Its inline local maps keep the part of CodeSee's approach that helps: changed nodes, their direct context and no unrelated graph. The changed-concepts map remains useful when a reviewer wants spatial orientation. A treemap can be reconsidered after the hierarchy and churn data have been used, but it does not solve the need to explain why a change matters and it makes relationships secondary.

## What the user sees

### Level 0: change overview

The header gives the range, totals and optional narrative. The body contains one card per changed top-level concept. A concept added inside another concept appears under that parent unless it is itself a top-level concept. Cards are sorted by attention order, then churn, then name.

```
codebase-inspector   92c987d -> 494bacd       [Head|Base] [List|Map]
22 files  +2,043 -94   6 concepts   1 integration   7 untested

Adds release checking to the CLI and desktop app.        agent summary

> Release check     added    +1,372 -0   5 files   26 tests
  Static viewer     changed    +396 -81  2 files
  Desktop shell     changed    +220 -6   6 files    4 untested
  Command line      changed     +15 -3   1 file

Context for Release check
[Command line] ---> [Release check] ---> [GitHub Releases]
[Desktop shell] --/

Enter open   N/P next change   Esc back   / find
```

The factual line under a card uses existing concept summaries and diff facts. It names added or removed responsibility, changed integration points, relationship changes and untested production code. The optional `summarise-change` narrative sits once above the cards and is labelled as an agent summary.

### Level 1: concept

The concept view shows changed modules inside that concept. It keeps the selected concept's incoming and outgoing relationships at the edge. Unchanged modules are hidden unless they contain a changed file or provide a direct relationship endpoint.

```
Change / Release check                       +1,372 -0   5 files

Used by                  Changed modules                  Uses
[Desktop shell] ---> +----------------------+ ---> [GitHub Releases]
[Command line] ----> | Desktop update check |      HTTP
                     | +890  3 files         |
                     +----------------------+
                     +----------------------+
                     | CLI update check     |
                     | +482  2 files         |
                     +----------------------+

Risks: new HTTP integration   Tests: 26 added   Untested: 0
```

### Level 2: module

A module is a presentation grouping, not a new stored node. Use the deepest package that owns the files when one exists. Otherwise use their nearest meaningful group, collapsing chains with one changed child. Files from different folders can stay together when the concept owns them and the package is the same.

```
Change / Release check / Desktop update check          +890 -0

File                                      Churn   Symbols   Tests
> app/src/update-check.ts               +367 -0     +31       13
  app/src/update-check.test.ts           +275 -0      +8       13
  app/test/update-smoke.mjs              +248 -0       -        -

Context for app/src/update-check.ts
Desktop shell calls 4 functions   GitHub Releases via fetchRelease()
```

### Level 3: file

The file view ranks changed functions by source order and shows additions, deletions, signature state, tests and direct cross-file context. Imports that do not touch a changed function stay collapsed under Other file changes.

```
... / app/src/update-check.ts                         +367 -0

> runCheck()              added   +54 -0   tests 6   calls fetchRelease()
  fetchRelease()          added   +41 -0   tests 2   HTTP GitHub Releases
  releaseFromApi()        added   +36 -0   tests 3
  28 more changed functions

Other file changes: imports +6, top-level state +12
Used by: app/src/main.ts#checkForUpdatesOnce
```

### Level 4: function

The function view combines the local call context with the function's diff. Only callers, callees, renders, endpoints, tests and env vars that touch this function appear.

```
... / update-check.ts / fetchRelease()              added   +41 -0

Called by: runCheck()                     Calls: requestOnce()
Integration: GET GitHub Releases API      Tests: 2

@@ function fetchRelease(...)
+ const response = await requestOnce(...)
+ if (response.status === 304) ...
  ...

[Open file] [Base] [Head]
```

### Level 5: lines

The line view is the existing unified code diff with enough unchanged context to understand the edit. It adds a changed-hunk rail and keeps the function, file, module and concept breadcrumb visible.

```
... / fetchRelease() / hunk 2 of 4                 [Unified|Split]

  118  const headers = { "User-Agent": userAgent }
- 119  const body = await get(url)
+ 119  const response = await requestOnce(url, headers, etag)
+ 120  if (response.status === 304) return cached
  121  return releaseFromApi(response.body)

P previous hunk   N next hunk   Esc function   E open in editor
```

## Measures and attention order

Churn is additions plus deletions from `git diff --numstat` for tracked files. The UI always shows additions and deletions separately as well as the total bar. Binary files show `binary` and count as one changed file, not zero churn. A moved file with unchanged content shows `moved` and zero churn.

Counts roll up through file, module and concept ownership:

- files added, modified, removed and moved;
- lines added and deleted;
- functions and classes added, changed, removed and moved;
- tests added or removed, plus changed production functions without a linked test;
- relationships and integration points added, removed or changed;
- provisional ownership.

Default attention order is lexicographic, not a hidden score:

1. changed or added integration points;
2. changed production functions without linked tests;
3. concept splits, merges, additions, removals and ownership moves;
4. changed relationships;
5. remaining items by churn;
6. name as the stable tie-breaker.

The user can switch the overview sort to churn or name. The chosen sort is stored in the URL hash with the rest of the view state.

"Why it matters" is factual:

- responsibility comes from the concept or module summary;
- impact comes from changed relationships, direct dependants and integration points;
- review risk comes from untested changes, provisional ownership and removed tests;
- intent comes only from an accepted `summarise-change` answer and is labelled as an agent summary.

The deterministic UI does not invent intent from file names or commit messages.

## Relationship context

Every level has one focus. It may draw or list only:

- relationships whose source or destination is the focus;
- direct callers and callees of the focused file or function;
- tests linked to the focus;
- unchanged nodes at the other end of those relationships;
- a parent needed to explain containment.

Changed relationships use the existing added, removed, volume and mechanism marks. Unchanged context is grey. Unrelated relationships and their endpoints are absent. Selecting a relationship lists the code edges behind it and both ends. Moving to either end creates a sideways navigation entry with a visible Back to chip.

At the overview, the focus is the selected concept card. In Map mode, all changed concepts may be present, but unchanged nodes appear only as direct neighbours of the selected concept. This is different from the current comparison image, which draws every top-level concept and all outside relationships at once.

## Interaction

The PRD-02 V0 two-way navigation rule applies at every level.

- Click a card, row or box to select it and update its local context.
- Click its name or press Enter to open the next level.
- Esc or Left goes to the parent level and restores selection, scroll and zoom.
- Browser Back, Backspace and the Back to chip return from a sideways jump, search result or relationship endpoint and restore the prior view.
- N and P move to the next or previous changed sibling. At line level they move between changed hunks.
- Up and Down move selection in lists. Tab reaches every control. `/` opens search.
- Head and Base retain the same focus when that item exists on both sides. When it exists on one side only, the other side shows the item's last known parent and an explicit absent state.
- Map and List retain the same selected concept. Fit, pan and zoom work as in PRD-02.
- Double-click on a file, function, method, component or test keeps PRD-02 V13 behaviour and opens the editor. It never serves as the drill action.

The viewer hash stores the range, side, level, focus, selection, sort and List or Map mode. The desktop shell continues to preserve the hash per comparison. Opening Compare in the desktop app lands on level 0. The picker itself does not change.

## Shared output

One build-time projection produces the hierarchy and measures for all outputs. It extends the existing diff payload rather than creating a second diff engine.

`cbi diff`:

- Text and Markdown print the range totals, optional narrative, ranked concept rows and attention facts first.
- `--concept`, `--module`, `--file` and `--symbol` select a drill level.
- `--detail` prints the current exhaustive structural list.
- JSON keeps the existing `groups` and adds an `overview` object so callers do not have to reconstruct churn and hierarchy.

`cbi review`:

- `review.md` starts with the same ranked overview and attention facts.
- The Mermaid diagram contains changed concepts and the direct context of the highest-attention concept. Other concept cards link to their sections.
- The exhaustive structural list moves under a Details heading.
- The headless render path captures the level 0 overview for `after.png` and the corresponding base state for `before.png`. The concept-map SVG remains available as an additional map export.

Viewer and desktop app:

- `cbi build --compare` opens at level 0 in List mode.
- The existing Changes panel is replaced by the level navigation. It does not coexist with another exhaustive list.
- Copy for agent includes the selected level's compact overview and the exact drill command.
- The current full concept comparison remains under Map, with the contextual filtering above.

## Requirements

### Data

- O1. Extend the diff output with additions and deletions per file, rolled up to module and concept, without reading or executing target code.
- O2. Build one deterministic hierarchy from changed concepts, presentation modules, files, symbols and line hunks. The existing stable node IDs remain the keys.
- O3. Record direct context endpoints and attention facts at each level. Do not copy the whole relationship graph into each item.
- O4. Keep the existing change kinds and exhaustive `groups` output. The overview is a projection over those facts and git line counts.
- O5. Use the current concepts on both sides under the PRD-04 provisional ownership rules. A comparison without concepts starts at deployable or package, then module, file, function and lines.

### Viewer

- O6. Open comparisons on the ranked level 0 overview with List and Map modes.
- O7. Support every drill level and sketch above with local relationship context only.
- O8. Support click, keyboard, URL history, side switching and two-way navigation as specified above.
- O9. Preserve test, coverage and result overlays. At overview levels they colour the test measure, not the churn measure.
- O10. Keep first paint under two seconds on the sample-monorepo target. Load line diffs only when a file or function opens.
- O11. Render from `file://` with the existing plain JavaScript and vendored elkjs. Add no runtime dependency for the ranked view or churn bars.

### CLI, review and app

- O12. Use the shared overview in `cbi diff`, `cbi review`, the static viewer and desktop app.
- O13. Keep the existing exhaustive text behind `--detail` and the existing JSON fields for compatibility.
- O14. Change the desktop app only so a completed comparison opens at level 0. Compare selection and ref safety remain PRD-03 and PRD-04 behaviour.
- O15. Let `cbi render --compare` capture `--view overview` as PNG and SVG-compatible HTML, and retain concept capture for callers that name a concept.

## Acceptance criteria

- E1. On codebase-inspector `92c987d..494bacd`, level 0 puts Release check first and shows 22 files, +2,043, -94, the CLI and Desktop shell as users, and GitHub Releases as a new HTTP integration. The reviewer can reach `fetchRelease()` and its changed lines from that card.
- E2. On a fixture with one two-line integration change and one 500-line internal refactor, attention order puts the integration first while the churn bars still make the refactor visibly larger.
- E3. On a fixture with changed concepts A and B plus unchanged concepts C through H, selecting A shows only A, its changed peers and A's direct neighbours. No relationship between C through H is drawn or listed.
- E4. On a fixture with a package, nested single-child folders and files owned by one concept, the module level uses the package and collapses the folder chain. Every changed file appears exactly once.
- E5. At every level, Enter drills, Esc returns to the parent, a sideways relationship jump gets a Back to chip, and browser back restores selection and camera state.
- E6. Switching Base and Head preserves the focused item where possible and shows a clear absent state for an addition or removal.
- E7. `cbi diff`, `review.md`, viewer data and overview rendering agree on totals and ordering from one golden change fixture.
- E8. Existing PRD-04 diff JSON fields and `--detail` text match their current golden outputs.
- E9. A synthetic comparison with 50 concepts, 1,000 changed files and 10,000 changed symbols opens level 0 under the existing two-second viewer budget. Symbol and line payloads load on drill, not first paint.
- E10. `uv run pytest` and `npm test` in `app/` pass. Viewer tests use the headless Chrome render path. Electron smoke scripts do not run on a development Mac.

## Delivery shape

1. Overview projection and golden tests: churn, modules, attention facts, ordering and JSON compatibility.
2. Text and Markdown overview for `cbi diff` and `cbi review`, with `--detail` retaining the current output.
3. Viewer level 0 and concept drill, including List and contextual Map modes.
4. Module, file, function and line levels with lazy source loading.
5. Keyboard, two-way navigation, base/head state and desktop landing state.
6. Headless overview render and the PRD-04 review images.

Each slice is useful and testable on the update-check comparison before the next slice starts.

## Non-goals

- Code correctness, style or security review.
- Comments, approvals or viewed-file state.
- An agent-generated narrative by default.
- Comparing more than two versions.
- Replacing the normal, non-comparison concept map.
- A treemap in this increment.

## Assumptions and risks

- Git line counts can be large for generated or vendored files. CBI's existing tracked-file and ignore rules apply, and binary files are labelled rather than assigned a guessed size.
- Concept summaries may not explain the intent of a specific change. The overview states deterministic impact facts and leaves intent to the optional narrative.
- A concept can own files in several packages. The module level groups by deepest package first and then by collapsed folder, so it remains a presentation hierarchy rather than changing ownership.
- Changed-first filtering can hide an important unchanged dependant. Direct neighbours of the current focus remain visible, and the card states how many additional direct neighbours are collapsed.
- Attention ordering may not match every reviewer. Its rules are visible, and churn and name sorts are one action away.

## Open questions

- Whether review progress belongs in a later increment. Default: leave it out. This PRD improves comprehension, not review workflow state.
- Whether the Map toggle should remember its last mode across comparisons. Default: remember it per project, but always open shared `cbi://` comparison links in List mode unless the link names a mode.
