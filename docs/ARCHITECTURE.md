# Architecture

```text
core.Game -> simulator.render -> Tk practice window
                                      |
                               Windows HWND capture
                                      | pixels only
                                 vision.Reader
                                      | Observation
                                 vision.Tracker
                                      | verified history
                           analysis.History (SQLite)
                                      | profiles
                         analysis.equity / analysis.coach
                                      | Advice
                                  floating HUD
```

Milestone 5 adds a second pixel pipeline inside the same app:

```text
local images / video / selected HWND / selected screen region
                           |
                        Frame
                           | normalized regions + taught examples (Layout)
                   CalibratedReader
                           | fields, similarity, issues, TableSnapshot
                      TableHistory
                           | inferred events, reconciliation quality
                 calibration studio / recognition HUD / JSON export
```

This pipeline is isolated from practice analysis and Bayesian evidence. A
reconciled six-seat sequence can export `Observation`; external recommendations
remain withheld. See [reader calibration and limitations](READER.md).

## Component boundaries

`app.py` operates the simulator controls and composes the observation pipeline.
The coach receives only immutable observations, observed actions and profile
snapshots. Production recognizers/analysis never receive the simulator deck or opponents' cards.
Smoke tests compare observations against privileged simulator truth only for QA.

| Component | Responsibility |
| --- | --- |
| `core` | Best-five hand ranks, betting legality, turn order, chip accounting and settlement |
| `simulator` | Fixed visible skin, ordinary readable text fields and simple opponents |
| `vision` | Capture, glyph recognition, immutable observations and reconstructed event ledger |
| `vision/sources.py`, `layouts.py` | Generic local inputs and portable normalized regions/labeled PNG examples |
| `vision/calibrated.py`, `table_history.py` | Visual templates, amount OCR, validated snapshots and conservative action inference |
| `ui/table_reader.py` | Calibration, inspection, background reads, recognition HUD and explicit export |
| `analysis` | Session Bayesian statistics, weighted ranges, pot equity, turn/river trees and policy sensitivity |
| `replay` | Append-only observed snapshots, saved scenarios and public-state rendering |
| `ui/replay.py` | Timeline browsing, range sensitivity, corrections and per-pot results |
| `app.py` / `ui` | Custom frameless controls, responsive HUD, background analysis and result freshness |

## Recognition and freshness

The practice renderer and practice recognizer share layout/font calibration, not game state.
Visible text is read from pixels; there are no encoded pixels, metadata, or
hidden-state API shortcuts. This is deliberately fixed-layout template
recognition, not general OCR suitable for arbitrary poker clients.

Reader validation includes card uniqueness, board/street agreement, actor,
amounts, contribution totals, call costs, raise bounds and event-tape continuity.
The tracker reconciles its paid-chip/fold ledger against observed seats and
checks invariant hole cards and button position. The tape displays eight events.
An unrecoverable gap withholds advice for that hand; the next hand resynchronizes.
Template confidence is not a calibrated probability of whole-hand correctness.

Pillow `ImageGrab.grab(window=...)` captures the local practice widget on Windows.
The table image scales with its viewport, preserving the optical aspect ratio.
Nearest-neighbor enlargement normalizes to the optical reference. At compact
scales (50–100%), glyph templates use the identical resampling map and field-
specific character sets; ambiguous matches are rejected. Numeric/card text is
still extracted from captured pixels. Controls wrap to preserve screen space.
Minimization, invalid pixels, distortion or inconsistent state invalidates advice.
Capture runs approximately every 200 ms; opponents act every 1.4 seconds.
Tk runs on the main thread; numerical work runs on one worker thread. A
hand/street/actor/event-count key prevents obsolete results from being displayed.
Local actions clear advice immediately, before capture catches up.

Both practice windows have custom draggable headers, edge/corner resize targets and
maximize/restore controls. The HUD is 94% opaque by default, adjustable to 88%
or 100%; its content reflows into two columns when widened. UI control Windows calls
are scoped to the app's own windows for minimize, taskbar presence, and monitor
work-area bounds. There is no standard title bar or native scrollbar.

`ui/sizing.py` separates UI typography from optical calibration. The default
overlay targets 7% of the usable work area with readable minimum dimensions;
its font scale balances DPI against that compact budget. `ui/coach.py` builds
the non-scrolling essentials and optional expandable details. Actual widget/font
measurements set the minimum size so cards, metrics, recommendation and EVs fit.
Only optional history/assumptions scroll. Manual text zoom is saved under the
user profile and can expand the window when necessary; Reset restores the
compact footprint. Screen-size checks cover 768p, 1080p and 4K, including full
river boards and three candidate EVs, without changing OS DPI settings.

The generic reader shares no font/layout renderer with its recognition engine.
`vision/fixtures.py` provides two explicitly synthetic QA/demo skins; Game truth
creates public fixture pixels and compares expected results only. The engine
receives only pixels, calibrated regions and labeled crops. Numeric zero aliases
are explicitly taught per field. Unknown values are never defaulted to zero.
Capture/recognition runs on one worker; Tk owns display and action history. Deep
copied profiles plus generation tokens reject jobs after source/calibration edits.
Decoder release queues behind pending reads. Profiles are bounded, versioned JSON
with image data; full source images remain separate. Export is explicit.

`ui/reader_style.py` scopes pixel fonts/styles to the reader instead of changing
Tk's global scaling or default fonts. The studio follows display DPI; the HUD
uses the existing compact display scale. Reader zoom persists independently in
the shared preferences JSON, preserving coach settings. Controls wrap and move
to compact menus on short windows; narrow views choose one panel at a time.
Scrollable content and dialogs keep large text reachable. Zoom changes preview
geometry only, leaving source pixels, calibrated regions and action history intact.

## Opponent modeling

Milestone 3 adds [session-only Bayesian adaptation and a heads-up river tree](RIVER.md).
The response model and river engine are in `analysis/bayes.py` and
`analysis/river.py`; `analysis/benchmark.py` supplies a synthetic paired evaluation.
Milestone 4 adds [turn search and approximate policy sensitivity](TURN.md) in
`analysis/turn.py` and `analysis/uncertainty.py`. River-card solvers reuse immutable
rank tables and chip-tier payouts, but keep separate card-conditioned beliefs.

SQLite keys `(session UUID, hand, sequence)` deduplicate repeated captures and
avoid restart collisions. Seat IDs refer only to fixed simulator characters.
Live profile queries are now restricted to the current session. Earlier sessions
remain archived for review and do not seed unfamiliar players' live estimates.
VPIP uses a Beta(2,3) smoothing prior; facing-bet fold rate uses Beta(3,3).
Raw counts accompany estimates. Current-hand observations are included in these
statistics; this prototype does not fit calibrated historical population models.

Ranges weight starting combinations using smoothed VPIP. Observed calls/raises
multiply positive heuristic likelihoods using the board visible on that action's
street. Weak combinations retain positive weight. The simulator's bot profiles
are not supplied to the coach.

## Numerical limits

The coaching engine computes integer-chip payouts for each contribution tier.
Folded contributions remain in pots; eligibility excludes folded players. Sole
contributors receive uncalled refunds. Odd chips go clockwise from the button.
Equity includes ties and weights payout share over pots the hero can contest,
excluding refunds. Overall payout standard error retains covariance across pots.

River deals are enumerated exactly when the product of range sizes is at most
20,000. Supported heads-up turn trees also enumerate every hand/river-card pair
and compute exact frozen-contribution showdown payouts. Other states use seeded Monte Carlo. Whole-deal rejection conditions the
product of weighted opponent ranges on card compatibility. Fully blocked or
overly conflicting ranges fail explicitly. Folded players' hidden distributions
are omitted. Exact enumeration removes sampling uncertainty, not range uncertainty.

EV is relative to folding now (zero); prior matched contributions are sunk.
Supported heads-up river and turn decisions use the bounded trees documented in
[RIVER.md](RIVER.md) and [TURN.md](TURN.md). Turn strategy sensitivity uses a
deterministic posterior-policy ensemble with reduced-range quadrature; its
approximate bands are separate from deal-sampling error and true-EV uncertainty.
The following frozen-contribution limits apply to other states.
Existing guaranteed hero refunds are excluded from incremental EV. Check/call
freezes contributions after the hero acts, then runs to showdown. It omits
remaining decisions, which may include calls/folds still owed on this street.
Raise scenarios consider one legal half-pot-ish
sizing with strength-conditioned folds/calls and a runout. Sampled folded cards
remain unavailable. Reraises, future bets, rake and calibrated response
probabilities are not modeled. Sampling intervals exclude model uncertainty.

Call/check EV supports all-ins, short calls and side pots. One scalar pot-odds
threshold is shown only for a single contestable pot. Raise scenarios remain
disabled when an existing player is all-in. This is conditional scenario analysis,
not a full betting-tree solver. Independent test-only five-card enumeration and
chip-level payouts validate the arithmetic using different algorithms.

## Saved replay and scenarios

Three additive SQLite tables store hand summaries, versioned original snapshots,
and separate user scenarios. Snapshot keys are session/hand/event-count. Identical
captures are ignored. Originals contain only validated observations, full observed
event prefixes and profile snapshots from that moment; there are no hidden cards
or future observations. New version-2 payloads also freeze session-response model
counts. Older payloads without them use baseline response models.
Existing event-only history remains intact but cannot
provide retroactive replays. Completion flags distinguish complete/partial hands.

The replay viewer renders observations directly, independently of `Game`. Its
own background worker compares original and edited scenarios using saved profile
evidence and deterministic seeds. A revision token discards results after edits
or timeline navigation. SQLite reads/writes remain on the Tk thread. Scenarios
persist only after successful calculation. Reset deletes only the scenario.
Manual state corrections preserve board length/actor and disable stale raise
bounds. Bot pause state is restored when review closes.

## Future work

1. Richer transition validation, multi-sizing side-pot raises and replay export.
2. Calibrated opponent likelihoods and held-out policy benchmarks.
3. Calibrated population priors, richer size policies, flop/multiway continuation models and finer policy sensitivity.
4. Held-out recognition datasets and calibration presets for actual client skins.
5. Complete-hand external replay/model integration, robust settlement, seat changes,
   rake/ante conventions and data-quality gating.

No external-client account connection, external automated actions, process-memory
inspection or network service is included. Capture lists visible window titles
and reads only the user's selected window or desktop rectangle.
