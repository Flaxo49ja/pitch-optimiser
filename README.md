# pitch

Pick the best XI under a transfer budget and draw it on the terminal.

```
 ╭──────────────────────────────────────────────────────────────────────────╮
 │      ╭──────────╮             ╭──────────╮             ╭──────────╮      │
 │      │85 LW     │             │82 RW     │             │81 ST     │      │
 │      │Z. Fofana │             │A. Bankole│             │S. Mulli… │      │
 │      │£72m      │             │£38m      │             │£32m      │      │
 │      ╰──────────╯             ╰──────────╯             ╰──────────╯      │
 │                                                                          │
 │      ╭──────────╮             ╭──────────╮             ╭──────────╮      │
 │      │83 CAM    │             │82 CM     │             │80 RM     │      │
 │      │I. Lindq… │             │F. Hallo… │             │E. Vance  │      │
 │      │£52m      │             │£40m      │             │£24m      │      │
 │      ╰──────────╯             ╰──────────╯             ╰──────────╯      │
 │                              ···· ·· ·· ····                             │
 │··········································································│
 │                              ···· ·· ·· ····                             │
 │   ╭──────────╮       ╭──────────╮      ╭──────────╮       ╭──────────╮   │
 │   │84 CB     │       │82 CB     │      │80 CB     │       │83 LB     │   │
 │   │O. Prewitt│       │J. Kleiber│      │R. Amoedo │       │J. Amank… │   │
 │   │£62m      │       │£44m      │      │£30m      │       │£58m      │   │
 │   ╰──────────╯       ╰──────────╯      ╰──────────╯       ╰──────────╯   │
 │                               ╭──────────╮                               │
 │                               │84 GK     │                               │
 │                               │Tomas Vlk │                               │
 │                               │£48m      │                               │
 │                               ╰──────────╯                               │
 ╰──────────────────────────────────────────────────────────────────────────╯

  4-3-3   score 10,747   spend 500m of 500m   ████████████████████████████
```

Cards are coloured by rating: gold for 87+, silver for 81+, bronze below that.

## Why the answer is actually the best XI

This is not a greedy pick. Selection is a 0/1 knapsack solved by dynamic
programming over (players chosen, money spent): for each position group it builds
the table of best scores for *exactly* `k` players at *exactly* `c` units, then a
max-plus convolution across groups finds the best legal XI within the budget.
It runs in well under a second for a few hundred players.

The tests check the solver against exhaustive brute force on randomised small
squads, so "optimal" means optimal rather than "looks about right".

## Install

Needs Python 3.10+ and NumPy. Nothing else.

```sh
cd pitch-optimiser
./pitch.py            # the bundled fictional squad
```

## Usage

```sh
./pitch.py                                   # 4-3-3, £500m budget, sample squad
./pitch.py --formation 3-5-2 --budget 120
./pitch.py --csv my-squad.csv --budget 60
./pitch.py --budget 0                        # ignore money, take the best XI
./pitch.py --list-formations
./pitch.py --no-color
```

| Flag | Meaning |
| --- | --- |
| `--csv PATH` | player file to read (default: bundled `data/sample-squad.csv`) |
| `--formation F` | any `DEF-MID-FWD` shape that sums to 10, or a named one |
| `--budget M` | millions to spend; `0` means no limit (default `500`) |
| `--no-color` | plain text, for logs and diffs |
| `--color` | force colour even when piped |
| `--list-formations` | print known formations |

Named formations: `4-3-3`, `4-4-2`, `4-5-1`, `4-2-3-1`, `4-1-4-1`, `3-5-2`,
`3-4-3`, `3-6-1`, `5-3-2`, `5-2-3`, `5-4-1`.

## Player file

A CSV with this header (order does not matter, extra columns are ignored):

```csv
name,pos,club,rating,pace,shooting,passing,dribbling,defending,physical,price
Fabio Mancuso,ST,Riverton Athletic,92,90,93,72,86,38,84,220
```

* `pos` — one of `GK CB LB RB LWB RWB CDM CM CAM LM RM LW RW ST CF`.
  It decides which group the player fills (`DEF`, `MID`, `FWD`) and how their
  attributes are weighted.
* `rating` — 1-100, the headline number.
* `pace … physical` — optional, default 60 when the column or cell is blank.
* `price` — millions, decimals allowed.

`name` and `pos` and `rating` and `price` are required; everything else optional.

## How players are scored

```
score = rating * 10 + role_fit * 2
```

`role_fit` is the average of the six attributes weighted by the player's
position — a centre-back is judged mostly on defending and physical, a striker on
shooting and pace, a keeper almost entirely on defending and physical. The
multiplier means rating dominates and attributes break ties between similarly
rated players, so a 84 with perfect attributes still loses to an 86.

Weights live in `POS_WEIGHTS` at the top of `pitch.py` and are easy to change.

## Limitations

* Money and score only. No squad-size limits, home-grown quotas, club caps,
  wage structure, chemistry or injury history.
* One player per row, one squad per file. There is no notion of a player being
  only able to play one slot, so a squad of eight centre-backs is legal — the
  formation constrains *groups*, not individual slots.
* The bundled squad is entirely fictional. Ratings are invented for testing the
  optimiser, not a claim about any real player.
* Bench and rotation are out of scope; this picks a starting XI.

## Tests

```sh
make check      # or: python3 -m unittest discover -s tests
```

Covers brute-force optimality, budget and formation constraints, no
double-selection, unlimited budget, input validation, and that `--no-color`
emits no escape codes.

## License

MIT — see [LICENSE](LICENSE).
