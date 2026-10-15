# Six coherent commits

The implementation was committed locally in the six groups below. These commands
record how the history was built; they do not need to be rerun on the completed
branch. When reproducing the sequence, run from the repository root in PowerShell
and inspect each staged diff. Nothing here pushes to GitHub.

Set up once:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
```

Each group's tests depend only on that group and earlier groups. The desktop
entry point arrives in group 5. Later unstaged files stay in your working tree;
use a separate clean checkout to inspect an exact intermediate commit.

## 1. Domain and rules

```powershell
git add .gitignore pyproject.toml src/pokato/__init__.py src/pokato/core tests/test_core.py
.\.venv\Scripts\python.exe -m unittest discover -s tests -p test_core.py -v
git diff --cached
git commit -m "feat(core): add Hold'em rules, evaluator and pot settlement"
```

Includes full/short raises, reopening, payouts and chip-conservation fixtures.
The core imports no vision or desktop modules.

## 2. Rendered simulator

```powershell
git add src/pokato/simulator tests/test_simulator.py
.\.venv\Scripts\python.exe -m unittest discover -s tests -p test_simulator.py -v
git diff --cached
git commit -m "feat(simulator): add practice renderer and opponent policies"
```

Includes the versioned layout and simple opponent styles. Opponents' cards are
excluded from the visible frame, including at showdown in V1.

## 3. Screen reading and reconstruction

```powershell
git add src/pokato/vision tests/test_vision.py
.\.venv\Scripts\python.exe -m unittest discover -s tests -p test_vision.py -v
git diff --cached
git commit -m "feat(vision): read practice pixels and reconstruct validated hands"
```

Includes Windows capture, template recognition, observations, accounting checks
and missed-event handling.

## 4. Opponent history and analysis

```powershell
git add src/pokato/analysis tests/test_analysis.py
.\.venv\Scripts\python.exe -m unittest discover -s tests -p test_analysis.py -v
git diff --cached
git commit -m "feat(analysis): add observed profiles, range equity and EV scenarios"
```

Includes SQLite persistence, opportunity counts, heuristic ranges, sampled equity,
exact heads-up river equity and explicit action-value assumptions.

## 5. Desktop app and HUD

```powershell
git add src/pokato/app.py src/pokato/__main__.py scripts/desktop_smoke.py
.\.venv\Scripts\python.exe scripts/desktop_smoke.py
git diff --cached
git commit -m "feat(desktop): connect window capture to a floating practice HUD"
```

First end-to-end runnable app: manual actions, background calculations,
stale-result invalidation and interactive desktop smoke testing.

## 6. Documentation and CI

```powershell
git add README.md docs scripts/validate.py .github/workflows/test.yml
.\.venv\Scripts\python.exe scripts/validate.py
git diff --cached
git commit -m "docs: add setup, component commit guide and Windows CI"
git status --short
```

The final status should be clean. `.venv`, runtime data and `artifacts/` QA images
are ignored. Review the branch before pushing through your normal workflow.

## Milestone 2 component groups

The saved-review milestone was committed locally in these four groups, in order.
The commands below record how that history was built and do not need to be rerun
on the completed branch. Each group depends only on itself and earlier groups.
The executable under `dist/` stays ignored.

```powershell
git add src/pokato/analysis/ranges.py tests/test_ranges.py
git commit -m "feat(ranges): add explicit weighted combinations and joint sampling"

git add src/pokato/core/pots.py src/pokato/analysis/pot_equity.py src/pokato/analysis/coach.py tests/reference_poker.py tests/test_pots.py tests/test_analysis.py
git commit -m "feat(analysis): calculate contribution-specific pot payouts and call EV"

git add src/pokato/replay tests/test_replay_store.py
git commit -m "feat(replay): archive immutable observations and separate scenarios"

git add src/pokato/ui/replay.py src/pokato/app.py scripts/replay_smoke.py pyproject.toml README.md docs
git commit -m "feat(ui): add saved-hand review, range comparison and corrections"
```

Validation for the groups is `test_ranges.py`, `test_pots.py` plus
`test_analysis.py`, `test_replay_store.py`, and `scripts/replay_smoke.py`
respectively. Use the unit discovery commands above with the corresponding
pattern. `scripts/validate.py` checks the complete project; the existing desktop
and readability smoke checks also apply. The four milestone-2 commits are local;
pushing them to GitHub is a separate step.

## Milestone 3: Bayesian sessions and river search

This milestone is committed in four dependency-ordered groups:

1. `feat(model): add session-scoped Bayesian response adaptation` — response
   posteriors, idempotent session evidence, session-only profiles, versioned
   frozen replay models and isolation/shrinkage tests.
2. `feat(analysis): search heads-up river betting trees over public beliefs` —
   legal river transitions, multi-sizing best response, observed/future response
   range updates, model-aware EV integration and legality/no-clairvoyance tests.
3. `feat(ui): expose session evidence and river response branches` — HUD/replay
   model wiring, evidence/branch explanations, actual-window river diagnostics
   and the packaged river smoke entry point.
4. `test: add paired river benchmarks and milestone documentation` — held-out
   synthetic prediction tests, matched-deal strategy comparisons, version 0.3,
   model assumptions, benchmark results and setup instructions.

The full checks are `scripts/validate.py`, `scripts/river_smoke.py`,
`scripts/replay_smoke.py` and `scripts/readability_smoke.py`. Run
`scripts/benchmark_river.py --pairs 1200 --seed 31` to reproduce the documented
synthetic report. The frozen build supports `--self-test-river <report-path>`.
Executables and runtime reports remain ignored. These commits are local;
pushing is separate.

## Milestone 4: turn analysis and policy sensitivity

Four dependency-ordered commits:

1. `feat(analysis): add public-belief heads-up turn and river search` — exact
   blocker-aware chance transitions, new-street actor order and betting rights,
   shared river continuations, bounded search and independent payout/legality tests.
2. `feat(model): estimate turn EV sensitivity across Bayesian policies` — coherent
   seeded Dirichlet policy draws, bounded range quadrature, anchored action EV bands,
   policy agreement, payout caching and uncertainty/reproducibility checks.
3. `feat(ui): show turn recommendations, policy sensitivity and river cards` —
   coach routing, exact showdown equity, compact agreement, detailed EV bands and
   card graphics, frozen replay, turn smoke and DPI/layout regression checks.
4. `test: document and package milestone 4 turn analysis` — fixed-fixture latency
   and resolution benchmark, regression coverage, model limits, version 0.4 and
   one updated `dist\Pokato.exe` with a packaged turn self-test.

Validation: `scripts/validate.py`, `scripts/turn_smoke.py`,
`scripts/river_smoke.py`, `scripts/replay_smoke.py` and
`scripts/readability_smoke.py`. Reproduce the sensitivity resolution diagnostics
with `scripts/benchmark_turn.py --draws 24 --hands 32 --reference-hands 64 --seed 31`.
The executable supports `--self-test-turn <absolute-report-path>`; no separately
named milestone executable is created. Binary/report artifacts remain ignored.
