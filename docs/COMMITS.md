# Component commit history

Milestone 1 was committed locally in the six groups below. These commands
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

## Milestone 5: client-independent table reading

Four dependency-ordered local commits:

1. `9aa13b3 feat(ingest): add client-independent frame sources and saved layouts`
   — image/animated image/video/window/region inputs, bounded RGB conversion,
   normalized regions, portable JSON profiles and source/roundtrip checks.
2. `6c682eb feat(vision): recognize calibrated fields and reconcile visible actions`
   — taught card/number/marker templates, unknown/ambiguous-field rejection,
   immutable snapshots, action/chip-ledger inference and independent synthetic skins.
3. `6151f39 feat(ui): add table calibration studio and recognition HUD`
   — one-app mode switching, ROI editor, example training, explicit per-field zero
   states, crop inspector, floating HUD, input freshness, provenance/export and
   actual-window diagnostics with a packaged reader self-test.
4. `test: validate and package milestone 5 table reading`
   — held-out synthetic benchmark, heads-up/raise/stabilization validation,
   calibration error handling, version 0.5, reader guide and one updated executable
   bundling image/video dependencies and their metadata/license notices.

Validation: `scripts/validate.py`, `scripts/reader_smoke.py`,
`scripts/readability_smoke.py`, and the packaged reader/turn self-tests.
`scripts/benchmark_reader.py --frames 12 --seed 31` reproduces the synthetic
accuracy/rejection and latency report. `docs/READER.md` distinguishes arbitrary
image ingestion from per-skin calibrated recognition and documents unsupported
history conventions. External recommendations remain withheld.

The app remains `dist\Pokato.exe`. Binaries, profiles and QA reports under ignored
artifact directories stay outside these commits. No push to GitHub is performed.

## Readability follow-up: version 0.5.1

`fix(ui): scale table reader and dialogs for high-DPI displays` adds scoped pixel
fonts, display-sized windows, scaled inspector rows/dropdowns, independent saved
reader zoom, compact command menus and scrollable calibration/readings/dialogs.
Zoom preserves source pixels, calibration, history and unsaved editor values.
The existing practice-coach font settings and optical scaling stay independent.

Validation: 85 unit tests, five reader readability cases including 4K/250% and
200% text zoom, five practice readability cases, actual settings-dialog pixels,
and the packaged reader/capture/export self-test. The same `dist\Pokato.exe`
is rebuilt; README previews show the larger UI.

## Automatic detection and HUD-only startup: version 0.6.0

Three dependency-ordered local commits:

1. `b249b68 feat(vision): read poker screens automatically with local OCR`
   — offline pretrained text recognition, card geometry and suit recognition,
   automatic board/hand grouping, conservative hero anchoring, pot/stack reading,
   full-desktop capture, independent client fixtures and model/runtime notices.
   ONNX Runtime requires Python 3.11+, reflected in project metadata and CI.
2. `ddbfb99 feat(ui): launch a single HUD with one-click screen analysis`
   — default HUD-only launch, Start/Stop, capture exclusion, background inference,
   stale-session rejection, readable zoom/scrolling and optional practice/manual
   tools behind the menu. Explicit `--practice` retains the simulator launch.
3. `test: package and document automatic screen analysis`
   — actual-desktop Start/Stop/restart diagnostics, frozen offline OCR validation,
   five display/DPI cases, reusable local labeled-image benchmark, bundled models,
   notices, diagnostic fixture and updated single `dist\Pokato.exe`.

Validation: 102 unit tests; source and frozen automatic desktop smoke; five HUD
readability cases; packaged manual-reader regression. The automatic benchmark
read all 19 board cards in ten local HD Poker captures, with 14 correct and six
withheld hole cards, and no incorrect accepted cards. Two independent fictional
clients cover different fonts, card positions and four-color decks. These small
corpora do not establish universal skin support. External action reconstruction
and recommendation integration remain outstanding in the automatic pipeline.

Binary files and private captures/reports remain ignored. Commits are local.

## Hole-card reliability: version 0.6.1

Three dependency-ordered local commits:

1. `77f71d8 fix(vision): extract fanned and shaded hole cards correctly`
   — preserve card geometry, separate upper-left ranks from larger suits, recover
   clipped faces, adapt to shaded backgrounds, isolate banner fragments, prefer
   complete views, and expose normalized glyph evidence. Independent fixtures
   cover every card in both clear and shaded fanned hands.
2. `a8f5ff2 fix(hud): track corroborated hole cards within visible deals`
   — per-slot corroboration, independent duplicate-view evidence, explicit held
   provenance, bounded age, glyph/position continuity, and whole-pair clearing on
   deal evidence. Includes 18 sequence tests and a desktop diagnostic that checks
   alternating controlled rejections and actual between-deal/new-deal pixels.
3. `test: validate and package hole-card tracking fixes`
   — reusable resized/padded replay benchmark, held-state readability checks,
   updated behavior/limits, version 0.6.1 and the rebuilt single `dist\Pokato.exe`.

Validation commands are `scripts/validate.py`, `scripts/automatic_smoke.py`,
`scripts/automatic_readability_smoke.py`, and the executable's `--self-test-auto`
mode. `scripts/benchmark_hole_stability.py --manifest <local-labels.json>` checks
raw card pixels at four sizes/layouts and controlled tracking failures. Raw
screens, labels, QA reports and binaries remain outside Git.

Final checks: 123 unit tests; five display/DPI cases with held provenance; frozen
offline Start/Stop/restart and actual between-deal/new-deal capture. Forty HD
capture variants produced 80/80 correct hole cards and 76/76 correct board cards.
Controlled tracking rejections produced no incorrect retained cards; initial
confirmation withheld three card observations. These are correlated replay
fixtures and do not establish general live-play accuracy.
