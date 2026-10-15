# Heads-up turn decisions and Bayesian policy sensitivity

## Decision model

The turn engine receives only observed hero cards, four board cards, visible
stacks/contributions, button position, action history and frozen session evidence.
It requires a hero decision with exactly two live players and heads-up play
throughout the current betting round. A round that began multiway falls back
even if only two players remain, preserving safety around raise reopening.
Preflop, flop and
multiway decisions retain explicitly labeled frozen-contribution scenarios.
Inconsistent corrected histories, unavailable raise bounds or an exhausted search
budget also fall back explicitly. Failure of the sensitivity subsearch preserves
the point calculation and reports sensitivity as unavailable.

Automatic ranges retain earlier-street heuristics, then condition on observed
turn actions using the session response model and public-board rank percentile.
Explicit ranges describe the current range and bypass that observed-turn update.
Future modeled actions always update the hand weights before a hero continuation.
The model never reads the simulator's opponent cards or deck.

At the current decision, the legal menu contains check or fold/call plus
one-third-pot, two-thirds-pot and all-in sizes, clipped to legal bounds and
deduplicated. The model allows **one additional turn bet/raise and one river
bet/raise**, then fold/call only. This cap resets on the new street and excludes
already observed aggression. It substantially restricts future reraises and must
not be interpreted as a complete no-limit strategy tree. A 20,000 decision-node
budget bounds each point/sensitivity search. The standalone river engine retains
its separate three-additional-bet/raise cap.

For each opponent hand there are 44 possible river cards: 52 minus two hero
cards, four board cards and two opponent cards. Hero can see 46 candidate cards,
but their marginal probabilities need not be equal:

```text
P(river card c) = sum(weight(h) for compatible h not containing c) / 44
P(h | c)       = weight(h) / compatible hand mass
```

Zero-mass cards are skipped. The chance probabilities sum to one. After a
non-fold turn ending, river bets/acted flags reset and the first live seat
clockwise after the button acts. If fewer than two players have chips, river
betting is skipped. The existing river engine searches each continuation over
the card-conditioned hand distribution. Hero optimizes expected EV over that
whole belief, never separately for the actual hidden hand.

EV remains relative to folding at the original turn decision. All spending on
both streets is deducted from the original hero stack. Dead money, contribution
tiers, short calls, refunds and clockwise odd chips use the shared payout engine.
Point EV integrates all retained combinations, all compatible river cards and
all modeled action branches exactly within this bounded response model.

## Equity and card graphics

Showdown equity holds contributions fixed after the current check/call. Weighted
win/tie/loss masses from exact card enumeration produce per-pot integer payouts,
including refunds and odd chips; no deal-sampling interval is needed. This is
distinct from the EV of a strategy involving future betting. Exact arithmetic
does not eliminate uncertainty about the opponent range or behavior model.

Details shows the three highest and three lowest **current-range showdown
equities by river card**, with their current probabilities. These are not the
chances of winning an entire betting strategy or the values after a future
opponent action. Replay lists every positive-probability card.

## Posterior-policy sensitivity

The response priors, evidence borrowing and board-strength tilt are unchanged
from [milestone 3](RIVER.md). One seeded policy draw samples Dirichlet rates using
independent gamma variables for each street/price context. That context's rates
are reused across the entire tree, including all possible river cards. Different
contexts are sampled independently despite their borrowed evidence; this is an
approximate policy ensemble, not a fitted joint posterior over all contexts.

By default, 24 policies are evaluated with at most 32 prior hands, selected by
deterministic systematic weighted stratification. All legal river cards and all
modeled action branches are still integrated for that reduced range. Narrower
ranges retain every hand exactly. Automatic ranges are reconditioned on observed
turn actions separately under each sampled policy. No user range is inferred from
future observations. Saved replay uses frozen counts and a hand/event seed.

To align sensitivity with the full-range point EV, each sampled action value is:

```text
anchored EV = full-range mean-policy EV
            + reduced-range sampled-policy EV
            - reduced-range mean-policy EV
```

The display shows interpolated 10th/90th percentiles as **approximate central 80%
policy sensitivity bands**. Continuations are refit within each sampled policy;
this measures strategy sensitivity, not the posterior performance of a single
fixed policy. Agreement is the fraction of sampled policies preferring an action,
splitting ties equally. At least 80% agreement is described as “Stable in draws”;
otherwise “Action varies.” Neither phrase establishes a correct recommendation.

Details/replay report the draw count, retained hands and maximum absolute
mean-policy EV shift from range compression. That shift is a diagnostic, **not an
error bound**. Bands are noisy with 24 draws and can change at finer resolution.
They exclude uncertainty in earlier-street range priors, strength-tilt heuristics,
bet-size policies, betting-depth truncation and model misspecification. They are
neither credible intervals for true poker EV nor intervals for realized winnings.
No neural network, external player dataset or measured population prior is used.

## Validation and diagnostics

```powershell
.\.venv\Scripts\python.exe scripts/validate.py
.\.venv\Scripts\python.exe scripts/turn_smoke.py
.\.venv\Scripts\python.exe scripts/benchmark_turn.py --draws 24 --hands 32 --reference-hands 64 --seed 31
powershell -ExecutionPolicy Bypass -File scripts/build_windows.ps1
```

Unit tests independently enumerate five-card ranks and compare complete turn/
river paths with the simulator game engine. They cover blockers, chance mass,
new-street actor order, all-ins/refunds, mixed-belief versus clairvoyant choices,
context adaptation, coherent/reproducible draws, narrowing with matching abundant
evidence, zero response-policy spread for terminal explicit-range all-ins, legacy
replay and explicit fallbacks.

The actual-window smoke reads a heads-up turn from pixels, verifies EV/evidence/
card probabilities, checks deterministic frozen replay, and confirms that a hero
action clears advice and card graphics immediately. The same single app supports
`--self-test-turn <absolute-report-path>`; older self-test modes remain available.
The visual fixture uses an opaque HUD beside the practice table and captures it
before opening replay, avoiding layered-window/restore capture artifacts. Normal
operation retains the adjustable 94% default opacity.

The fixed-fixture benchmark reports point/sensitivity latency, node counts,
chance mass, actions and a 32-versus-64-hand sensitivity resolution comparison.
Timings depend on CPU load and cache state. These diagnostics establish arithmetic
and expose approximation sensitivity; they do not establish human performance,
exploitability, GTO accuracy or online winnings. Reports and QA screenshots are
written under ignored `artifacts/`.

One local seed-31 run (24 policies, 32 prior hands, 64-hand resolution check):

| Fixture | Point time | Sensitivity time | Nodes | Point recommendation |
| --- | ---: | ---: | ---: | --- |
| Broad automatic range | 9.14 s | 10.09 s | 1,663 | Check |
| Explicit drawing range | 2.50 s | 1.42 s | 462 | Raise to 117 |
| Short all-in call | 3.19 s | 0.04 s | 0 | Call |

The broad fixture's maximum band-endpoint change at 64 hands was 1.86 chips;
sampled policy agreement was unchanged. Mean-policy quadrature shifts were
24.68 chips at 32 hands and 31.66 at 64, demonstrating that refinement need not
improve every finite quadrature. Anchoring removes that center shift, but does
not prove that the sensitivity spread is accurate. Narrow fixtures retained all
hands. Timings above exclude the extra 64-hand reference evaluation.
