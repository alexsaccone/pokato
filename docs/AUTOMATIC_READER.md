# Automatic screen reader · 0.6.0

Open **`dist\Pokato.exe`**, keep one poker table visible, and click **Start analysis**.
Only the HUD opens. There is no window picker, region drawing, profile selection,
example teaching or simulator to start first. Click **Stop analysis** to stop
capture and clear all displayed readings. Move the HUD by dragging its header;
**A− / A+** changes text size. The **⋯** menu holds optional tools.

The same executable contains the OCR models. First analysis initializes them;
subsequent frames reuse them. Initialization and inference run off the UI thread.
On the development machine, the tested HD Poker screenshots took roughly 3–7
seconds per analysis. This is sampled screen capture, not frame-by-frame video
inference. The timestamp shows how old the latest reading is.

## What happens automatically

- Capture the visible desktop, including multiple monitors, without selecting a client.
- Locate bright card faces, rectify their geometry and read ranks with pretrained OCR.
- Recognize suit shapes, including ordinary two-color and four-color decks.
- Group adjacent cards into a board and a visible two-card hand, using relative
  geometry rather than client-specific screen positions.
- Read labeled pot amounts and nearby player-name/stack pairs with OCR.
- Confirm the hand's owner when repeated account/seat text or duplicate header
  cards supply an anchor. Otherwise display **VISIBLE HAND** and the uncertainty.
- Re-detect on every frame, including after moving or resizing the poker window.

The production reader does not load HD Poker profiles or any training screenshots.
RapidOCR/PP-OCRv6 provides pretrained text detection and recognition; OpenCV handles
card geometry, grouping and suit topology. No account connection, cloud OCR,
upload or runtime model download is involved. Normal operation saves neither
screenshots nor video. Text-size preferences are saved under
`%USERPROFILE%\.pokato\settings.json`.

Windows 10 version 2004 and later can exclude the HUD from capture, allowing it
to overlay the table without reading itself. When exclusion is unavailable,
Pokato masks its own rectangle; move it away from cards in that case. Minimized
tables, other windows covering cards and protected/blank capture surfaces cannot
be recovered from desktop pixels.

## Partial readings and current limits

Automatic detection removes the old setup requirement; it is not a guarantee
for every arbitrary poker skin. Current card detection expects separated,
roughly upright, light card faces with a readable corner rank and suit. Tiny,
dark, faded, heavily rotated, overlapping or unusually styled cards can remain
unknown. English poker labels and decimal-point amounts are supported; ambiguous
number formats are withheld. Abbreviations such as `36K` remain explicitly
approximate. Side pots are displayed separately, not summed into an invented total.

Missing internal board slots become unknown cards. Conflicting duplicate cards,
multiple boards and ambiguous exposed showdown hands are withheld. Readings are
cleared on Stop, rejected after a capture-session change and cleared when stale.
The HUD reports matching consecutive card readings, but that does not prove
their accuracy or that every intervening action was observed.

The automatic HUD currently displays optical state. Dealer/button, active actor,
betting sequence, legal action bounds and Bayesian opponent updates are not yet
reconstructed by this pipeline. External strategy recommendations remain withheld
until those inputs are verified. The existing practice coach and optional manual
reader are accessible under **⋯**; their previous analysis features remain available.

## Validation

`scripts/validate.py` includes real, offline OCR inference against two independent
fictional clients with different fonts, colors, card locations and hand positions.
Their renderer does not use the recognition implementation. Tests also cover
missing board slots, exposed-hand ambiguity, multiple boards, chat text falsely
resembling pots, amount parsing and desktop-capture lifecycle.

Ten previously labeled HD Poker captures were evaluated with no profile loaded:
all **19 board cards** were correct. Seven of ten complete hand pairs were read
correctly and anchored to the hero; the remaining three faded/folded hand pairs
were withheld. No incorrect accepted cards occurred in this small corpus. This
does not establish accuracy across all clients, themes or game states. The local
captures and labels stay outside Git.

To evaluate another labeled corpus, run `scripts/benchmark_automatic.py --manifest
<labels.json> --output artifacts/automatic-benchmark.json`. The manifest has a
`frames` array; each entry supplies an image path relative to the manifest and
`fields` such as `board0.rank`, `board0.suit`, `hole0.rank`, `hole0.suit`.
Use `empty` for absent slots. Only entries with `split: "test"` (or no split) are
evaluated. The report separates correct, withheld and incorrect accepted cards;
it exits unsuccessfully if any annotated card is incorrectly accepted. This
checks cards, not player identities, amount accuracy or strategic validity.

The desktop smoke test clicks the actual Start button, reads captured pixels
from an independent fixture, stops/restarts while OCR is running, rejects stale
results and verifies immediate clearing. All network requests are blocked during
that test. The fixture PNG is packaged only for diagnostics; it is not a model or
a production lookup table.

```powershell
.\.venv\Scripts\python.exe scripts/validate.py
.\.venv\Scripts\python.exe scripts/automatic_smoke.py
.\.venv\Scripts\python.exe scripts/automatic_readability_smoke.py
$automaticReport = Join-Path $PWD 'artifacts\packaged-automatic.json'
Start-Process .\dist\Pokato.exe -ArgumentList '--self-test-auto', ('"' + $automaticReport + '"') -WindowStyle Hidden -Wait
Get-Content $automaticReport
```

GUI smoke checks require an interactive Windows desktop and should run
sequentially. They write ignored reports/images under `artifacts`. The readability
test covers five work-area/DPI combinations, font sizes, visible Start controls,
card clipping, scrolling at 200% zoom and independent saved text preferences.

See [third-party notices](THIRD_PARTY.md) for OCR code, model and runtime licenses.
