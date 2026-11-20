# Season Roguelike — design note

Status: idea, not built. Captured 2026-11-18. Build on top of `pitch.py`.

## The pitch in one line

Ten matchdays. Each week you pick an XI under a changing budget, play a simulated
match, and survive. A losing streak ends the run, and afterwards the solver tells
you what the best XI would have been.

The roguelike hook is not the football, it is the **regret machine**: you make a
choice under uncertainty, the game resolves it, then an exact optimiser shows you
the best choice you could have made with the information you had. That is a much
stronger loop than "pick the best team", which is a solved problem and therefore
boring.

## Front-end: TUI first

Recommendation: **terminal UI now, web later**, with the game logic kept free of
both.

Reasons for TUI first:

* The solver, the player model and the pitch renderer already exist in Python and
  are terminal-native. A TUI is a thin layer over working code.
* No accounts, no persistence infrastructure, no deployment, no mobile layout.
  A roguelike is a state machine plus a renderer, and a state machine is free in
  a local process.
* The loop is 10 short turns. Keyboard-driven screens suit that far better than
  page loads and confirm buttons.
* If the loop is not fun, the TUI costs 2-3 evenings to discover it. A web build
  costs 1-2 weeks to discover the same thing.

Reasons a site is worth doing *second*:

* The pitch graphic is the shareable artefact. "Here is my run" as an image or a
  link is what makes a roguelike spread; a terminal screenshot travels less well.
* A daily seeded run shared by everyone is the natural web-native feature — same
  seed, compare scores. That needs a server or at least a shared seed.

### Rule that makes both possible

Keep three layers apart, with no cross-imports upward:

```
core/       pure logic: squad state, injuries, market, match sim, run state machine
render/     draws a given state: terminal today, HTML/React later
cli|web/    input, persistence, seeding, scoreboard
```

`core` must never print, never read files, never know about terminals or HTTP.
Feed it a seed and a list of decisions, get back an event log. Then a web version
is a second renderer plus thin endpoints, and a replay is just the event log.

## Loop

```
new run (seed) → budget 120m, squad of 16 randomised players
  ↓
week N (1..10)
  1. event phase   — the week's twist is revealed
  2. market phase  — buy/sell within budget, pick XI with an exact solver assist
  3. match phase   — your XI vs the opponent XI, simulated
  4. consequence   — rating swings, injuries, suspensions, budget moves
  ↓
run ends on: 10 weeks survived, 3 straight losses, or budget insolvency
```

Between weeks the squad persists, so decisions compound — that is what separates
a roguelike from ten independent puzzles.

## Rules draft

* **Weeks:** 10. Difficulty ramps: opponent strength rises roughly linearly, and
  weeks 8-10 are the wall.
* **Losing streak:** 3 consecutive losses ends the run. Two draws do not count as
  a loss, so the streak is about form, not noise.
* **Budget:** starts at 120m. Win: +12m. Draw: +4m. Loss: +1m. A small trickle on
  losses keeps a bad run recoverable instead of a dead man walking.
* **Squad size:** 16 (11 + 5 bench) so injuries force real choices. Selling a
  player returns a fraction of price — 80% is a good starting number, and the
  haircut is the tension.
* **Form:** each player gets a form multiplier in ±12% applied to score, drifting
  week to week. Warns in the UI one week ahead, so it is information, not a
  coin flip.
* **Injuries:** 0-2 per week. Injured players are unavailable for 1-3 weeks.
* **Suspensions:** triggered by a red card in the match sim (low probability).
* **Events:** a deck of weekly twists drawn from a seeded shuffle. Examples:
  transfer window inflates striker prices 30%; a youth prospect appears at a
  discount; your best defender is suspended; the board demands a top-half finish.
  These are what make a run feel different from the last one.

## Match simulation

Deterministic given the seed, so replays and daily runs work.

```
attack  = weighted mean of XI attacking scores, with form multipliers
defence = weighted mean of XI defensive scores, with form multipliers
expected goals for     = base * (attack / opponent_defence) ** k
expected goals against = base * (opponent_attack / defence) ** k
goals ~ Poisson(expected)
```

Start with `base = 1.35`, `k = 1.0`, clamp expected goals to 0.2..4.0. Poisson
sampling from a seeded `random.Random` is enough; no scipy needed (inverse-CDF
sampling or Knuth's method).

Opponent XI is generated per week from the rising strength curve, so it is fair
by construction and never needs hand-authored teams.

Result: win / draw / loss by goal comparison. Cards drawn from a small per-match
probability weighted by physical and low discipline ratings.

## The solver as the "what should I have done" replay

This is the feature that makes the game worth playing. After each matchday, show:

* points earned vs the expected points of the XI you actually fielded,
* the XI the solver would have picked from your available players,
* the single best swap you did not make, and its projected delta.

Important honesty rule: the replay uses **only information you had at decision
time** — no hindsight ratings. A replay that cheats by knowing the injury roll is
just an insult. The solver call is `pitch.solve(players, counts, budget)` with the
squad as it stood before the match.

## Score for the leaderboard

```
score = weeks survived * 100 + points * 25 + goal_difference * 10 + budget_left
```

Tune later; the point is one number that rewards survival, then quality, then
economy.

## MVP scope for 2-3 evenings

Evening 1:

* `core/` state machine: squad, budget, week advance, injury/form rolls
* match sim with Poisson, seeded
* headless run loop, text log only, no pretty UI

Evening 2:

* market phase and budget arithmetic, sell haircut
* solver-assisted XI picking, reuse `pitch.solve`
* `render/` terminal screens: squad table, market, pitch (reuse the pitch
  renderer with form-adjusted stats)

Evening 3:

* weekly events deck, ~10 cards
* end-of-run screen with the regret replay
* seeded runs, `--seed`, `--daily`, run history log

Explicitly **not** in the MVP: persistence across process restarts, async or
multiplayer, accounts, sound, animations, real player data, leagues or cups.

## Open questions

1. Is 10 weeks the right length? 10 might be too short for decisions to compound;
   15 with a mid-run difficulty spike may be better. Playtest.
2. Should the solver be available *before* you commit, or is picking the XI by
   hand the actual game? If the solver always picks, the player's only decision is
   the market — which may be enough, but it changes what the game is.
3. Injuries need to be punishing but not run-ending. A rule like "cannot field 11"
   should force a cheap emergency signing rather than an automatic loss.
4. Does form drift need to be visible? Hidden drift is cruelty; visible drift is a
   puzzle. Recommend visible, one week ahead.
5. Web port trigger: if the TUI runs are fun for ~10 runs, port. If not, kill it.

## Rough effort

| Piece | TUI | Web |
| --- | --- | --- |
| core logic + sim | 2 evenings | same, shared |
| terminal render | 1 evening | — |
| market/events content | 1 evening | same, shared |
| persistence/seeding | 1 hour | +1 evening |
| front-end | — | 3-5 evenings |
| deploy + share cards | — | 1-2 evenings |

TUI lands in about 3 evenings; the web version adds roughly a week on top, and
only the core is shared work.
