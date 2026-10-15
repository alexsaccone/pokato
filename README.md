# Pokato

A Windows desktop Texas Hold'em practice table with a screen-reading coach.
Play one six-seat table against five simulated opponents. A floating HUD reads
the table's **actual rendered pixels**, reconstructs actions, tracks observed
opponent behavior, and displays range equity, pot odds and estimated action EV.

This milestone runs entirely locally. ClubWPT Gold and HD Poker adapters are
not included.

![Practice table](docs/table-preview.png)

[Preview the floating coach](docs/hud-preview.png).

## Run on Windows

For the standalone build, double-click **`dist\Pokato.exe`**. It includes Python,
Tk, Pillow, and the application; no installation or console window is required.
You can move that single file to another folder. Statistics still live under
your user profile, so the executable's folder does not need to be writable.
The current compact-HUD build is **`dist\Pokato-Compact.exe`**, created alongside
the original executable because Windows prevents replacing a running program.

To run from source:

Requires Python **3.10+** with Tk. On this workstation, plain `python` selects
3.8, so select 3.12 explicitly:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
.\.venv\Scripts\python.exe -m pokato
```

No API key, server, account, or GPU is required. Pillow is the only third-party
runtime dependency. The standard Windows Python installer includes Tk.

```powershell
.\.venv\Scripts\python.exe -m pokato --seed 42 --samples 800 --database .pokato\practice.sqlite3
```

- **Fold / Check / Call / Raise:** act when the gold outline reaches YOU.
- **Raise to:** total contribution on this street, not additional chips.
- **Deal next hand:** available after the hand completes.
- **Pause bots:** pauses opponents while observation continues.
- **H:** reopen the HUD after closing it.
- Close the practice-table window to exit both windows.

Both windows use a custom borderless frame. Drag the header to move; drag any
edge or the bottom-right grip to resize. Click the square button or double-click
the header to maximize/restore. The minus minimizes; the cross closes the coach
or exits the table. **Show coach** reopens a hidden or minimized HUD.

The coach starts at 94% opacity. Click **94%** in its footer to cycle between
88%, 100%, and 94%.

The default HUD targets **7% of the monitor's usable area**: roughly **960 × 640**
on a 3840 × 2400 laptop after allowing for the taskbar. Cards and board, position,
pot, call cost, equity, break-even pot odds, recommendation, and action EVs are
visible together without scrolling. Smaller screens use a readable minimum.
Click **Details** for opponent history, numerical uncertainty, and calculation
assumptions; only this optional region scrolls. **Less** returns to the compact
overlay. Widening the details view gives its supporting panels two columns.

### Readable text on laptops and high-DPI monitors

HUD typography balances display DPI with the compact screen-area budget. The
4K default uses approximately 30-pixel body text, larger cards and recommendation
text, and compact spacing. Ordinary 100% displays start with 16-pixel body text.
Window defaults fit the monitor's usable area. Real font measurements keep the
crucial widgets visible; larger manual zoom can expand the window when necessary.

Use **A− / A+** in the coach's footer to adjust text from 80% to 200% of the
automatic size. **Reset** restores the display-aware default. Keyboard shortcuts
are **Ctrl + / Ctrl − / Ctrl 0**, and **Ctrl + mouse wheel** also adjusts text.
The setting is saved in `%USERPROFILE%\.pokato\settings.json` and remains relative
to display DPI, so moving the HUD to another monitor updates its physical size.

Blinds are 5/10 chips, stacks start at 1,000, and rake is zero. The button rotates
and busted players automatically rebuy. Betting rules include short all-ins,
reopening, uncalled refunds, split pots, and side pots.

The optical reference is **980 × 800 physical pixels**. The table scales to its
viewport while preserving its aspect ratio; the reader calibrates compact
glyphs at scales down to 50% and normalizes enlargement to the reference.
Controls wrap on smaller screens. Screen text scaling is independent of optical
recognition, and window defaults stay within the monitor's work area.
Windows capture targets only the practice widget's HWND;
covering it with another app does not turn that app into input. Minimizing the
practice window withholds advice.

## Understanding the coach

| Display | Meaning |
| --- | --- |
| Range equity | Expected showdown share against heuristic weighted ranges, including ties and sampled future cards |
| Exact river | Enumerates every available opponent combination heads-up; range assumptions remain uncertain |
| Break-even equity | Call cost / (current pot + call cost), for supported single-pot decisions without rake |
| Check/call EV | Assumes no future betting; a closing heads-up river call is terminal |
| Raise EV | One sizing with strength-conditioned folds/calls, then showdown; no reraises or future bets |
| ± intervals | Approximate 95% Monte Carlo sampling intervals, excluding model uncertainty |
| Sampling tie | The estimated ranking is unclear at the current sample count |
| All-in / side pot | Equity shown; action EV and per-pot odds withheld pending per-pot analysis |

Recommendations rank supported modeled scenarios. They are not GTO solutions or
evidence of a winning strategy. Multiway ranges use sequential card-removal
sampling; folded players' hidden-card distributions are omitted.
See [architecture and limitations](docs/ARCHITECTURE.md).

Opponent statistics persist in `%USERPROFILE%\.pokato\practice.sqlite3`, unless
`--database` is supplied. Identities refer to fixed practice characters. VPIP/PFR
denominators count hands with an observed preflop decision; fold-versus-bet
counts actual facing-bet decisions. Raw counts are shown, with smoothed rates
used internally. The normal app retains no screenshots or video. Delete the
database while the app is closed to reset statistics.

## Verify

```powershell
.\.venv\Scripts\python.exe scripts/validate.py
.\.venv\Scripts\python.exe scripts/desktop_smoke.py
.\.venv\Scripts\python.exe scripts/window_smoke.py
.\.venv\Scripts\python.exe scripts/readability_smoke.py
```

Unit tests need no display. The smoke check opens and closes the local UI,
captures its Windows pixels, verifies the hand and HUD, and checks immediate
advice invalidation after an action. It writes ignored QA images/JSON under
`artifacts/` and requires an interactive desktop. GitHub Actions is configured
for unit tests on Windows with Python 3.10, 3.12, and 3.14.
The window smoke check exercises custom drag/resize gestures, maximize/restore,
minimize, transparency controls, HUD reflow, and recognition after table resizing.
The readability check opens real widgets with simulated 768p/1080p work areas
at 100% and 150%, plus a 4K work area at 250%. It checks auto-fit, font sizes,
saved zoom controls, optional details and pixel recognition without changing OS
settings. A full-board fixture verifies that all essential widgets fit without
clipping or scrolling, and the 4K overlay stays close to the 7% area target.

## Build the executable

On Windows, from the repository root:

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[build]"
powershell -ExecutionPolicy Bypass -File scripts\build_windows.ps1
```

To build alongside an executable that is currently running, supply a new name:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\build_windows.ps1 -ExecutableName Pokato-Compact
```

The single-file GUI build is written to `dist\Pokato.exe`; generated build files
and the executable are ignored by Git. The Windows manifest enables per-monitor
DPI support and runs with ordinary user privileges. To verify the packaged
capture, analysis, resizing, and HUD pipeline:

```powershell
$smokeReport = Join-Path $PWD 'artifacts\packaged-smoke.json'
Start-Process -FilePath .\dist\Pokato.exe -ArgumentList '--self-test', ('"' + $smokeReport + '"') -Wait
Get-Content artifacts\packaged-smoke.json
```

The self-test briefly opens its own practice UI and closes automatically. Its
report includes whether it ran from the frozen executable and the checks passed.

## Commit component by component

The implementation is organized into [six component commits](docs/COMMITS.md).
The guide records their staging commands, validation commands, and commit
messages. The commits are local; pushing to GitHub is a separate step.

## External platforms

ClubWPT Gold's [prohibited-tools policy](https://support.clubwptgold.com/portal/en/kb/articles/prohibitedsoftware)
prohibits live advice, HUDs, automatic notes, scraping, and equity tools while its
client is open. HD Poker's [house rules](https://www.hdpoker.com/terms.html)
require approval for third-party analysis of opponents' histories or habits.
External adapters and data workflows need platform-specific permission and
review before implementation. Free play is not an exemption.
