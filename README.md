# PlayoffOdds

A [playoffstatus.com](https://playoffstatus.com)-style playoff-odds site, with
win probabilities driven by a **historical-Elo Monte Carlo** model (adapted from
the `Sports Monte Carlo` notebook in this repo).

It builds Elo ratings from real game results, simulates the upcoming season tens
of thousands of times, and reports — for every team — the probability of landing
in each playoff seed, winning its division, making the playoffs, and winning the
conference / title. It also lists every upcoming game with a win probability.

Currently only **football (NFL)** is supported. The engine is written behind a
per-sport config (`SportConfig`) so other leagues can be added later.

## Quick start

```bash
pip install -r requirements.txt
python sports_elo.py --sport nfl --season 2026 --start 2018 --sims 20000
```

Then open **`index.html`** in any browser — it is fully self-contained (the odds
are embedded inline, so it loads straight from disk with no web server).

### Options

| flag | default | meaning |
|------|---------|---------|
| `--sport` | `nfl` | which league (only `nfl` for now) |
| `--season` | `2026` | the upcoming season to project |
| `--start` | `2018` | first year of game results used to seed Elo |
| `--sims` | `20000` | number of simulated seasons |
| `--out` | `index.html` | output web page |
| `--json` | `data.json` | raw odds output |

## How it works

1. **Build Elo** from `--start` through the last completed season (regular
   season **and** playoffs), regressing every team toward the league mean
   between seasons (`preseason_regress`). Win probabilities use a logistic Elo
   curve with a home-field edge and margin-of-victory scaling of the K-factor.
2. **Project the upcoming season.** Every remaining game is simulated from the
   starting ratings; already-played games count as fixed results.
3. **Seed the field** with the league's rules — division winners take the top
   seeds, the best remaining teams take the wild cards (ties broken randomly and
   unbiased within each simulation).
4. **Run the bracket** each simulation for conference- and title-win odds.
5. **Render** a self-contained `index.html`.

## Franchise continuity

Relocations and renames that keep the same roster are mapped to a single
canonical franchise key (`NFL_ALIASES`), so a team's Elo carries across a move —
e.g. **Oakland → Las Vegas Raiders** (2020), San Diego → LA Chargers, St. Louis →
LA Rams. Add new cases to that dict.

## Adding a sport

Create a new `SportConfig` with its divisions, alias map, and a schedule loader
returning `{week: [(home, away, home_score|None, away_score|None, neutral)]}`,
then register it in `SPORTS`. The Elo engine, season simulation, seeding, bracket
sim, and renderer are all sport-agnostic.

## Files

- `sports_elo.py` — Elo engine, sport config, Monte Carlo, CLI.
- `render.py` — self-contained HTML renderer.
- `Sports Monte Carlo.ipynb` — the original notebook this was derived from.
