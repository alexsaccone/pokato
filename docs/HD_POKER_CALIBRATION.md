# HD Poker calibration · 0.5.2

**Version 0.6.0 no longer needs this manual profile to start reading HD Poker.**
Open Pokato and click **Start analysis**. See the [automatic reader](AUTOMATIC_READER.md)
for current behavior and measured results. This document records the optional
manual calibration workflow from 0.5.2.

Version 0.6.1 fixes fanned/shaded hole-card extraction and adds live per-card
corroboration and deal-boundary clearing. The same ten labeled captures now have
20/20 correct hole cards and 19/19 correct board cards without this profile.
Current tracking behavior and its separate sequence tests are documented in the
[automatic reader guide](AUTOMATIC_READER.md#hole-card-extraction-and-tracking).

Real HD Poker 1.9.5 frames were captured locally on 2026-10-16: Windows,
one nine-seat garden table, 250/500 play-money blinds, 3812 × 2138 client pixels.
The reader remains client-independent; all HD Poker positions and examples live
in a local layout rather than recognition code.

## Results and limits

The local held-out set contains ten frames excluded from calibration training.
Of 213 manually labeled card and amount fields, **212 were correct, one was
unknown, and no accepted value was wrong**. Coverage was 99.5% on those labeled
fields. The remaining rejected amount is covered by an animation. **Only three
of ten frames produced a complete table snapshot**: other frames contained
untrained/obstructed bets, changing timer markers, or player/card animations.
Complete-snapshot availability is not an accuracy measurement of every state field.

These frames come from the same session and are correlated. This does not
establish reliability across all 52 cards, table themes, clients, seat layouts,
window sizes, side pots or all-in transitions. More marker and bet examples are
still needed before treating the complete reader as reliable during normal play.
External recommendations and Bayesian updates remain withheld.

HD Poker abbreviates amounts, sometimes using different precision at different
sizes. Pokato marks recognized K/M values with **≈** and records
`approximate: true`. A snapshot containing such values cannot establish an exact
chip ledger or inferred action history. A main-pot number also cannot stand in
for the sum of main and side pots: the optional `single_pot` guard rejects known
unsupported layouts, and a dealt board with a missing collected pot is rejected.

## What changed

- Native window capture returned an old GPU frame while HD Poker continued
  playing. **Visible client area** capture reads fresh desktop pixels and follows
  window moves. It requires unobstructed calibrated regions.
- Selectable **light**, **card**, and **color** filters handle white amounts,
  shaded card symbols and changing timer colors. **Auto** remains available.
- Training and inference now resize wide 4K crops identically. Bold, touching
  amounts can use conservative whole-text templates; unseen amounts still need
  readable digit templates.
- Clipped/missing card ink is rejected. Teaching a recognized positive amount as
  `=0` is rejected. Partial HUD cards are labeled as partial and appear only when
  the table anchor matches.

The local layout uses the small header cards for hero cards, because the larger
cards move when the hero folds. Seat status regions use cards on the felt;
action banners change between calls, checks, timers and folds. Seat 0 is the
hero at the left, followed clockwise by the other eight seats. Bets and collected
pot are calibrated separately (`pot_includes_bets: false`).

## Try the saved calibration on this workstation

The profile and full frames are local, ignored files under `.pokato/hdpoker`.
They are not a distributed preset. From the repository folder:

```powershell
.\dist\Pokato.exe --reader --layout .pokato\hdpoker\garden-3812x2138.json --image .pokato\hdpoker\calibration\screen-001.png
```

This opens a captured, stable turn using the same single executable. Inspect
recognized fields and choose **Show HUD**. Approximate values and incomplete
history remain visibly unverified.

For live testing, keep HD Poker at the same table layout and client size. Choose
**Window…**, select **HD Poker® - v1.9.5**, leave **Visible client area (GPU games)**
selected, and capture it. Press **Start**, minimize the studio, and place the HUD
outside calibrated regions. In a compact studio, these commands are in
**Input / Layout / View**. Switching themes, seat arrangements or aspect ratio
requires checking/recalibrating the regions. Do not lower thresholds to hide
unknown fields; teach correctly labeled examples from stable frames instead.

## Reproduce the field benchmark

```powershell
.\.venv\Scripts\python.exe scripts\benchmark_calibration.py --layout .pokato\hdpoker\garden-3812x2138.json --manifest .pokato\hdpoker\heldout-labels.json --output .pokato\hdpoker\heldout-report.json
```

The report separates correct, unknown and wrong fields, and reports complete
snapshot counts and rejection reasons. Exit status fails on a wrong accepted
value or an empty test set; it does not claim that unknowns are resolved.
Manifest paths are relative to the manifest. Only rows with `split: "test"`
are scored. For another client, use that client's layout and manually labeled
frames in the same format described at the top of the benchmark script.

Full screenshots, local profiles and detailed reports stay out of Git. The
committed regression fixtures contain only small card/amount crops, with no
names, chat, wallet or account details. `scripts/validate.py` runs those tests
alongside the existing engine and recognition checks.

Verification for this build: 93 unit tests passed; all five reader DPI/size
checks passed; source and packaged reader smoke checks passed, including
fresh visible capture after moving/redrawing a window. A separate local UI check
confirmed the captured HD Poker turn's cards, 54,000 displayed total pot, dealer
and actor, plus partial HUD rendering on a rejected animation frame. The one-file
build remains `dist/Pokato.exe`.
