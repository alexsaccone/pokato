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

## Component boundaries

`app.py` operates the simulator controls and composes the observation pipeline.
The coach receives only immutable observations, observed actions and profile
snapshots. Vision/analysis never receive the simulator deck or opponents' cards.
Smoke tests compare observations against privileged simulator truth only for QA.

| Component | Responsibility |
| --- | --- |
| `core` | Best-five hand ranks, betting legality, turn order, chip accounting and settlement |
| `simulator` | Fixed visible skin, ordinary readable text fields and simple opponents |
| `vision` | Capture, glyph recognition, immutable observations and reconstructed event ledger |
| `analysis` | SQLite statistics, range weights, equity and action scenarios |
| `app.py` / `ui` | Custom frameless controls, responsive HUD, background analysis and result freshness |

## Recognition and freshness

The renderer and recognizer share layout/font calibration, not game state.
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
Nearest-neighbor enlargement allows captured pixels to normalize to the original
reference without changing glyphs. The window has a readable minimum size.
Minimization, invalid pixels, distortion or inconsistent state invalidates advice.
Capture runs approximately every 200 ms; opponents act every 1.4 seconds.
Tk runs on the main thread; numerical work runs on one worker thread. A
hand/street/actor/event-count key prevents obsolete results from being displayed.
Local actions clear advice immediately, before capture catches up.

Both windows have custom draggable headers, edge/corner resize targets and
maximize/restore controls. The HUD is 94% opaque by default, adjustable to 88%
or 100%; its content reflows into two columns when widened. Native Windows calls
are scoped to the app's own windows for minimize, taskbar presence, and monitor
work-area bounds. There is no standard title bar or native scrollbar.

## Opponent modeling

SQLite keys `(session UUID, hand, sequence)` deduplicate repeated captures and
avoid restart collisions. Seat IDs refer only to fixed simulator characters.
VPIP uses a Beta(2,3) smoothing prior; facing-bet fold rate uses Beta(3,3).
Raw counts accompany estimates. Current-hand observations are included in these
statistics; this prototype does not fit calibrated historical population models.

Ranges weight starting combinations using smoothed VPIP. Observed calls/raises
multiply positive heuristic likelihoods using the board visible on that action's
street. Weak combinations retain positive weight. The simulator's bot profiles
are not supplied to the coach.

## Numerical limits

Equity includes ties. Heads-up river equity enumerates all available hole-card
combinations. Other states use seeded weighted Monte Carlo. Multiway opponents
are sampled sequentially with shuffled sampling order and card removal, which
approximates rather than exactly computes their joint posterior. Folded players'
hidden-card distributions are omitted.

EV is relative to folding now (zero); prior contributions are sunk. Check/call
assumes immediate showdown. Raise scenarios consider one legal half-pot-ish
sizing with strength-conditioned folds/calls and a runout. Sampled folded cards
remain unavailable. Reraises, future bets, rake and calibrated response
probabilities are not modeled. Sampling intervals exclude model uncertainty.

The game settles all-ins and side pots. The coach withholds action EV and
per-pot odds in these states until per-pot analysis is implemented.

## Future work

1. Per-pot analysis, richer transition validation, range editing and replay.
2. Calibrated opponent likelihoods and held-out policy benchmarks.
3. Better baseline strategies and continuation betting models.
4. Authorized video files and independently calibrated skins.
5. External adapters after platform-specific permission and policy review.

No external-client connection, account access, external automated actions,
process discovery, or network service is included.
