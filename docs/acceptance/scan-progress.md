# Scan refresh and progress measurements

Measured locally on 3 November 2026, on the same generated fixture: six packages,
1,500 Python modules, 1,506 tracked files, two functions per module and one import
of the next module in the package. The model and answer cache started empty for
each run. Source refresh appended one comment to one module; judgement refresh
added an unused historical answer row without changing source. Cold scans ran
under cProfile; subsequent timings did not. These are observations on a loaded
Mac, not a universal benchmark.

| Scan | Before (seconds) | After (seconds) |
| --- | ---: | ---: |
| Cold, profiled | 3.600 | 3.951 |
| One source edit | 1.030 | 0.503 |
| Historical answer edit | 1.335 | 0.365 |

The final cold profiles show parsing and resolution remain the main mechanical
work (see the retained profiles for cumulative times). An earlier same-fixture
pair measured cold scans of 3.782s before and 24.689s after; the latter spent
18.854s hashing, including 17.666s in buffered file reads. This variation is why
these runs do not demonstrate a cold-scan speedup or establish an isolated speed
ratio. The change targets unnecessary mechanical work during judgement refresh
and provides visible progress during full scans.

To repeat with identical generated source and fresh model/cache directories, run
`uv run python scripts/profile-scan.py --output /absolute/path/to/results` on each
revision. The script uses the test `make_repo` builder and leaves its disposable
fixture under the system temporary directory. It writes timings, a cold cProfile
and the top 35 cumulative profile entries. Compare runs on the same machine and
retain load caveats; do not interpret a single pair as an isolated speed ratio.

Regression tests in `tests/test_scan_refresh.py` verify that an active answer
refresh updates summaries/search without calling the resolver or changing its
edges, and that progress goes to stderr. Existing source/ignore/workspace scan
regressions continue to cover invalidation of mechanical inputs.
