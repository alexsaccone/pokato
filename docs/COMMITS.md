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
