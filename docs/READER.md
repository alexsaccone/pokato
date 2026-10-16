# Table reader · milestone 5

The existing `Pokato.exe` now ingests local images, recordings, a selected Windows
window or a selected desktop rectangle. No client identifier, fixed card position,
simulator event tape, account integration or network request is needed. Recognition
needs a saved profile for the actual visual skin. ClubWPT Gold has not been
validated; the demo is a synthetic table.
External recommendations and Bayesian updates remain withheld in this milestone.

HD Poker 1.9.5 has now been tested with real captures on this workstation. The
local garden-table calibration, measured results and exact launch instructions
are in [HD Poker calibration](HD_POKER_CALIBRATION.md). It remains a partial
calibration, with unknown fields during animations and unsupported states.

## Readable text and window sizing

Version 0.5.1 sizes the studio, inspector rows, dropdowns, HUD and calibration
dialogs for display DPI. On a 4K display at 250%, studio body text defaults to
40 physical pixels; the compact HUD uses approximately 30-pixel body text.
The default studio window also grows to suit the display. Optical input pixels
and saved region coordinates stay unchanged when UI text sizes change.

Use **A− / A+ / Reset** in the studio or HUD, **Ctrl + / Ctrl − / Ctrl 0**, or
**Ctrl + mouse wheel** for 80–200% text zoom. `reader_zoom` is saved separately
from the coach's `hud_zoom` in `%USERPROFILE%\.pokato\settings.json`.
Moving the studio/HUD between monitors updates its display scale.

Short windows and large zoom use **Input / Layout / View** menus in place of the
full command bars. Input contains Images/Video/Window/Screen region/Demo;
Layout contains calibration/settings/save/export commands; View contains
Next frame/Show HUD and the calibration/readings page choices. Wide windows show
calibration and readings side by side; narrower windows show one page at a time.
The panels and settings dialogs scroll vertically so large controls stay reachable.

## Calibrate a table

1. Open **Read table** from the practice controls. Practice coaching/bots pause.
   **Demo** loads an independent skin with examples already labeled. **Next frame**
   steps through decisions; **Start / Pause** advances inputs; **Show HUD** opens
   the recognition overlay. Closing the studio returns to practice.
2. Open **Images…** or **Video…**. Select images in chronological order; numbered
   filenames help. Animated image pages are read in order too. Recordings decode
   sequentially, independently of real-time playback speed.
3. Click **New layout**, then **Settings…**. Set seats, chip unit, blinds and pot
   convention. Reference dimensions come from the current frame.
4. Choose a field from the dropdown, drag a rectangle, and click **Set region**.
   Include background padding around complete text/graphics. Keep neighboring
   labels, borders and symbols out of rank, suit and amount regions.
5. Enter the visible label and click **Teach example**. Repeat on other frames
   until the relevant ranks, suits, digits and marker states have examples.
   Choose **Ink** before setting the region: **auto** for the original background
   estimator; **light** for white amount text; **card** for dark/red ranks and suits
   on shaded card faces; **color** for saturated markers such as a turn timer.
   Card mode removes edge-connected background and small detached symbols, so
   include padding around the entire glyph. Changing ink modes requires new examples.
   Touching amount characters are saved as a strict whole-text template. These
   recognize taught strings; unseen strings still need separable digit examples.
6. **Save layout…** saves portable JSON containing settings, normalized regions
   and labeled PNG crops. **Load layout…** restores it; **Examples…** removes
   bad examples. Save explicitly after edits.

Start with static images. Once they read correctly, **Window…** explicitly selects
a visible window. **Screen region…** hides Pokato for rectangle selection, then
captures the first frame before restoring the studio; Escape cancels. Move or
minimize the studio and keep the HUD outside that rectangle before streaming:
screen capture sees overlapping windows. Window capture targets the chosen HWND
and stops if it closes, hides or minimizes. Some GPU/browser surfaces return blank
window captures; use a screen region or recording instead.

In **Window…**, **Visible client area (GPU games)** reads desktop pixels inside the
chosen window and follows its moves. This is the working mode for HD Poker;
native capture returned a stale game frame in testing. Keep the studio minimized
and the HUD outside calibrated regions. Other windows over those regions obscure
the input. The visible mode stops on closed/hidden/minimized windows; it does not
switch capture sources automatically. Native capture remains available in the picker.

## Required fields

Seat 0 is the hero. Number other seats clockwise, independently of their screen
coordinates. Profiles support 2–10 seats. Change profiles for a different seat
arrangement. Empty seats use status F; amounts still require calibration.

| Field | Region and labels |
| --- | --- |
| `anchor` | Stable, distinctive graphic; label `match`. Avoid clocks, changing text or large plain areas. |
| `hole0/1.rank` | Rank only: `2`–`9`, `T` or `10`, `J`, `Q`, `K`, `A`, `empty`. |
| `hole0/1.suit` | Suit only: `♣ ♦ ♥ ♠`, or `empty`. |
| `board0`–`board4` | Separate rank/suit regions with the same rules. Teach blank-card appearances. |
| `pot` | Amount only; label the visible text, e.g. `$12.50`. |
| `single_pot` | Optional guard: `yes` for supported single-pot placement, `no` for side pots or unsupported placement. Unknown/false guards withhold the snapshot. |
| `seatN.stack`, `seatN.bet` | Amount text; teach digits/currency/punctuation. Explicit `=0` examples map this field's blank-zero or ALL IN appearance to zero. |
| `seatN.status` | Appearance labeled `A` = in hand, `F` = folded/empty, `I` = all-in. Card backs or seat markers work; no fixed text is required. |
| `seatN.dealer`, `seatN.actor` | Marker appearances labeled `yes` and `no`; teach both per region. |
| `seatN.identity` | Optional name region; visual fingerprint, not name OCR. A change invalidates this hand's history. |

All fields except identity and the optional pot-layout guard are required for a complete snapshot. Partial layouts
still show individual readings. The inspector shows the crop, raw result,
similarity, runner-up separation and issue. Amber rectangles flag unreadable
fields; yellow marks the selected region. Double-click a field for a **provisional
correction** using its normal label syntax. Corrections are recorded as manual
and cannot establish automatic history. Teaching examples improves recognition.

Rank, suit and numeric glyph templates share their kind's group by default, so
digits learned from stacks can recognize unseen pot amounts. Set a distinct
**Template group** before setting a region when fonts/styles differ between fields.
Markers/status are per field by default. Zero-state examples are always per field:
a blank bet example cannot make blank pots or other stacks silently zero. If the
same blank appearance can mean unavailable, leave it unknown rather than teaching
it as zero. Touching numeric characters cannot be segmented reliably.

## Amounts and coordinates

Internal amounts are integer multiples of **chip unit**. On dollar tables, use
`0.01` for cents: `$1.50` becomes 150 units. Enter blinds in those units, e.g.
50/100 for $0.50/$1.00. Select `.` or `,` as decimal separator; thousands grouping
must be unambiguous. Currency and K/M suffixes work when their characters have
examples. Negative amounts and fractional chip units are rejected.

For amounts displayed in big blinds, **Amount ×** converts to currency before
normalization. At a $2 big blind with chip unit `0.01`, set it to `2`: `12BB`
becomes 2,400 units. Teach B characters too. Do not mix absolute/BB units in one
region without changing the multiplier/profile.

Check **Displayed pot includes current bets** when the central pot already counts
wagers. Uncheck it when bets are separate: visible bets are added for reconciliation.
Wrong blinds, units or pot convention prevent synchronization.

Coordinates scale proportionally; recognition normalizes to the reference pixel
size. Aspect changes beyond 2.5% are rejected. Browser chrome, cropping, seat
rotation, font, theme or arrangement changes may require a new profile. Arbitrary
aspect ratios can be calibrated initially. Profiles are bounded JSON data with
PNG crops, not executable plugins. Full input images are limited to 40 megapixels.

## Recognition and history quality

Cards use normalized foreground templates. Amount OCR segments separated character
columns; markers/status/anchor use appearance templates. Defaults require 0.94
similarity and 0.025 separation from the next distinct label. These are heuristic
image scores, **not probabilities of correctness**. Lowering thresholds can accept
wrong values; check crop padding, contrast, template groups and examples first.

Overlaps, animations, tiny text, unseen glyphs, complex backgrounds or obscured
seats can remain unreadable. The reader cannot infer hidden values. It validates
unique cards, complete boards, unique dealer/actor markers, player status and
pot/bet consistency. The anchor checks alignment; it is not automatic detection
or a guarantee that every region is correct.

| Quality | Meaning |
| --- | --- |
| `waiting` | Live input needs two consecutive matching snapshots with distinct frame indices. |
| `unreadable` | Missing, ambiguous or invalid fields; no assembled state. |
| `unverified` | Readable, but an initial blind-only deal/actor order was not observed. |
| `reconciled` | Captured frames support a consistent action sequence and chip ledger. |
| `gap` | Missed/multiple actions, identity changes, inconsistent chips, illegal order or manual corrections invalidate inference until a fresh blind-only deal. |
| `ended` | Hero cards disappeared/between hands; settlement is not inferred. |

The tracker starts before the first voluntary preflop action, infers one action
at a time, and checks street transitions, reopening rights and chip conservation.
It never invents skipped checks or contributions. Ante/straddle starts, rebuys,
rake deductions, settlement and dynamic seat changes are not reconstructed. Hero
folding may hide cards and end observation before the other players finish.

**Reconciled is not proof that every action was seen.** Recognition mode therefore
does not feed the Bayesian model or EV coach. Source/profile/region/example changes
reset inferred history and export records. Revision tokens discard obsolete worker
results. Failed/closed/delayed inputs clear current HUD state. Paused or finished
inputs identify the last frame. Practice coaching resumes separately on closing.

## Files and export

Normal reading keeps the current full frame and last 1,000 structured readings in
memory. Nothing uploads. **Save frame…** explicitly writes PNG. **Save layout…**
embeds labeled crops, including any text inside them. **Export readings…** saves
JSON with values, similarity, issues, manual provenance, events and history quality.
Reconciled six-seat sequences include the existing `Observation` schema; other seat
counts retain snapshots/events without that legacy export. External readings do not
enter practice SQLite or seed player profiles. Image timestamps are nominal
0.25-second steps, not wall-clock observations. Video timestamps use frame index
and reported FPS; variable-rate presentation timing is not reconstructed.

## Validation and the single executable

```powershell
.\.venv\Scripts\python.exe scripts/validate.py
.\.venv\Scripts\python.exe scripts/reader_smoke.py
.\.venv\Scripts\python.exe scripts/benchmark_reader.py --frames 12 --seed 31
powershell -ExecutionPolicy Bypass -File scripts\build_windows.ps1
$readerReport = Join-Path $PWD 'artifacts\packaged-reader-smoke.json'
Start-Process -FilePath .\dist\Pokato.exe -ArgumentList '--self-test-reader', ('"' + $readerReport + '"') -WindowStyle Hidden -Wait
Get-Content $readerReport
```

The desktop check captures only its own test window/rectangle and closes its UI
automatically. It tests inputs, calibration edits, manual provenance, slow source
switches, stale-state clearing, export and practice restoration. Ignored screenshots,
fixtures and reports go under `artifacts/`.

Seed 31 uses twelve held-out states per skin at 1×, 1.5× and 2×. All 72 valid
frames matched cards, seats, amounts, dealer and actor; all 48 corrupted-anchor/
blank-pot frames were rejected. Local median/p95 recognition was 225.5/377.6 ms
for the wide skin and 158.0/230.3 ms for the tall skin while another UI check ran.
This tests two synthetic calibrated fonts/layouts and unseen values, not real-client
accuracy, unseen-font generalization or strategic performance. Real-client support
needs separate calibration and held-out captures from that actual client.

The one-file build includes headless
[OpenCV 4.13.0.92](https://pypi.org/project/opencv-python-headless/4.13.0.92/), NumPy
and Pillow. Available codecs follow the installed OpenCV/FFmpeg build; unsupported
recordings stop with an error. These dependencies increase size/extraction time.
The build copies OpenCV/NumPy distribution metadata and third-party license notices
into the bundle. All features remain in the same `dist\Pokato.exe`.

Version 0.5.1 adds actual-widget readability checks at 768p, 1080p and 4K with
100%, 150% and 250% display scaling. They check row/font metrics, dropdown and
dialog text, wrapped controls, scrolling at 200% zoom, saved independent zoom,
unchanged input/calibration/history and provisional corrections through the UI.
Run `scripts/reader_readability_smoke.py`, or add `--case 4k-250` for that display.
