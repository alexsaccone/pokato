# Bayesian session adaptation and heads-up river analysis

## Evidence and cold starts

Each app startup creates a new session UUID. Profiles and response estimates for
live play query only that session. Practice characters have fixed seat identities;
future external adapters must use stable player keys or reset evidence when a
player is replaced. No old player's data is automatically assigned to a newcomer.
No neural network, outside dataset, hidden opponent cards or online training
service is used.

`response_events` is an additive SQLite table keyed by session/hand/sequence.
Repeated captures are deduplicated. Observed prefixes provide street, nominal
price to call, pot before acting, and fold/call/raise/check outcome. Forced blinds
are excluded. Contexts distinguish open action versus facing a bet, and nominal
price/current-pot buckets <=.25, <=.5 and >.5. Short-call legality clips the actual
payment separately; the response context consistently uses the nominal price.

Facing-bet priors are Dirichlet(10,11,3) for fold/call/raise. Open-action priors
are Dirichlet(18,6) for check/bet. These 24-pseudo-observation baselines are
conservative design choices, not measured population statistics. Context counts
have full weight; other price buckets on the same street contribute .25 each,
and other streets contribute .1 each. Open and facing contexts do not mix.
This weighted likelihood borrowing assumes some transferable player tendencies.
One direct observation contributes just 1/25 of a previously empty estimate.

The displayed data weight is weighted evidence / (prior + weighted evidence).
Deterministic Beta draws give sampled 90% marginal posterior intervals. These
intervals concern the context's marginal action rates; they are not intervals
for card strength, conditional branch probabilities or action EV.

The general separation of hand uncertainty and opponent-strategy uncertainty is
inspired by [Bayes' Bluff](https://arxiv.org/abs/1207.1411). This implementation
uses a smaller context model with its own explicit priors and heuristics, rather
than reproducing that poker agent.

## River tree

The initial state reconstructs river bets, prior checks, pending actors, last
full raise and reopening rights from observed actions. Legal sizing candidates
are one-third-pot, two-thirds-pot and all-in, clipped to min/max bounds with
duplicates removed. Up to three **additional** bets/raises are allowed from the
current decision; only fold/call remains at the cap. A 5,000-node budget bounds
search. Inconsistent edited histories or unavailable corrected raise bounds
produce an explicit fallback to the existing scenarios.

At opponent nodes, posterior-mean response rates receive a heuristic tilt based
on the hypothetical opponent hand's rank percentile against public-board hands.
It never tests that hand against the actual hero cards to decide a response.
Raise sizes are uniformly weighted conditional on raising. These assumptions
are intentionally visible and are not empirically calibrated policies.

After a modeled opponent action, combination weights update by Bayes' rule.
Automatic current ranges also condition on the opponent's already observed
river actions using the adapted likelihoods. Thus a bet from a frequently
aggressive player can imply a different range and call EV than the same bet
from a passive player. Earlier-street range updates retain the existing heuristic.
An explicit user range describes the final current range and bypasses observed-
river reweighting, avoiding double application of the user's assumptions.
Every later hero node chooses the highest expected EV across that updated
range. It never chooses separately for each actual hidden hand. All combination
and branch integration is exact within this finite model. The engine uses a
posterior-mean response policy; it does not integrate all possible response
policies through the strategy tree or compute GTO.

Transitions conserve chips and account for checks closing the round, all-ins,
short calls, full/short raises and turn order. Terminal payouts include dead
money, side-pot eligibility, uncalled refunds and clockwise odd chips. EV is
measured against folding now; matched prior contributions are sunk, and existing
guaranteed refunds are excluded from incremental EV. Tests compare random legal
tree paths and dealt payouts with the game engine. A mixed-range fixture detects
clairvoyant continuation choice.

The compact HUD shows the top three actions. Details and replay show all root
actions, first-opponent response probabilities, conditional branch EVs, hero
continuations and model evidence. Pot equity remains immediate showdown equity;
it is not the chance that the entire betting strategy wins. Behavioral/range
uncertainty is not represented by zero-width EV confidence intervals.

## Replay and session isolation

New version-2 snapshot payloads freeze both session profiles and response counts
at capture time. Later observations cannot change saved model evidence. Older
version-1/2 snapshots without response counts remain readable and use baseline
responses, with an explicit explanation. Their original profile snapshots remain
intact. Scenario edits do not alter original observations or evidence.

## Reproducible validation

```powershell
.\.venv\Scripts\python.exe scripts/validate.py
.\.venv\Scripts\python.exe scripts/river_smoke.py
.\.venv\Scripts\python.exe scripts/benchmark_river.py --pairs 1200 --seed 31
```

The river smoke advances a local table through actual window capture to a
heads-up river. It verifies session evidence, tree EV/branches, frozen snapshots
and replay display. It is also included in the frozen executable via
`--self-test-river <absolute-report-path>`.

The synthetic benchmark trains response counts with 80 observations per context
and evaluates unseen decisions, reporting Brier-score improvement. It also uses
matched opponent hands and random streams to compare baseline/adapted policies
on three fixed river fixtures: marginal pair, nuts, and facing a bet. Approximate
95% paired chip intervals measure that narrow comparison, not general poker skill.

Seed 31, 1,200 pairs per synthetic opponent:

| Opponent | Brier improvement | Adapted minus baseline chips | Approximate paired 95% interval |
| --- | ---: | ---: | --- |
| Folder | +0.227 | -0.52 | [-1.19, +0.16] |
| Station | +0.307 | +10.25 | [+6.83, +13.67] |
| Aggressive | +0.201 | +8.45 | [+3.96, +12.93] |

The folder result is inconclusive. These synthetic policies and tiny fixed ranges
do not establish human performance, general exploitability or online winnings.
Milestone 4 adds [heads-up turn continuation values and approximate posterior-policy
sensitivity](TURN.md). Future work includes calibrated population priors, richer
bet-size/context likelihoods, finer uncertainty integration and flop/multiway play.
