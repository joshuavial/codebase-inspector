# Change view validation

The comparison UI contract is [PRD-08](prd-08-change-overview.md#current-comparison-reading-contract). This record describes the generic visual fixture used for the changed-view overhaul.

The fixture is an isolated two-commit Git repository. Application contains Task claiming and Notifications; Delivery is added and Legacy archive is removed. It includes a signature/body edit, a test edit, a moved function, nested concepts and an unchanged entry-point caller. Two answers are checked and submitted through the ordinary summary task protocol: one for the comparison and one for Task claiming. The task cache is isolated under `/tmp`.

The accepted concept answer reads:

> Task claiming adds an optional priority argument and raises the claim cap from one to two, extending what callers can request. Its static test changes with the new call, but broader caller compatibility and runtime safety remain unknown.

The answer cites `src/tasks.py`. It demonstrates the distinction between observed code changes and unknown behavioural safety.

Evidence stays outside the public source tree in `.workmux/evidence/changed-ui-overhaul/` at the main checkout. `demo-fixture.py` reproduces the generic fixture; `sample-summary.json` records the accepted answers. `capture-receipt.json` records the asset revisions, viewports and capture method. The before assets are pinned to main commit `fc4cda6802d8d7cbfac1786388e33d5ce5e83d6e`; both viewers consume the same comparison data.

Headless Browserplex captures the overview and selected concept at desktop width 1440px and narrow width 390px. The `demo-before-*` and `demo-after-*` PNGs preserve matching states. Narrow full-page captures include the complete reading column, diagram and code drawer. The initial viewport captures separately show what is visible before scrolling.

Checks cover visible overall/selected narratives, explicit concept states, a closed Evidence disclosure, review signals with an evidence target, no horizontal overflow, a folded legend and a readable initial diagram centred on selected changed code when full fit is too small, with a visible notice and one-click full Fit. Unknown line counts remain unavailable and count labels use the correct singular/plural form. Additional interaction checks cover symbol inspection retaining the concept summary, file-only evidence and source commands, nested concept navigation and unavailable summary states. Source commands identify the comparison revision; removed files use Base.

Regression tests cover hierarchy and state projection, split/merge/reparent participants, ownership moves, human symbol verbs, test-file separation, summary rendering as text, source navigation, empty changed scopes, keyboard semantics and the comparison fit minimum. Full Python and desktop-shell unit suites remain the release gate; no visible desktop application is needed for these checks.
