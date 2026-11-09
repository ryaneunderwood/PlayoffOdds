# PlayoffOdds

A [playoffstatus.com](https://playoffstatus.com)-style playoff-odds site, with
win probabilities driven by a **historical-Elo Monte Carlo** model (adapted from
the `Sports Monte Carlo` notebook in this repo).

It builds Elo ratings from real game results, simulates the rest of the season
tens of thousands of times, and reports — for every team — the probability of
landing in each playoff seed, winning its division, making the playoffs, and
winning the conference / title. It also lists every upcoming game with a win
probability and every completed game with its score and the pre-kickoff odds.

Two leagues are supported, each on its own page with an **NFL / NHL** switch at
the top: **football (NFL)** at `index.html` and **hockey (NHL)** at `nhl.html`
(see [NHL](#nhl) for how hockey differs). The engine is written behind a
per-sport config (`SportConfig`) so other leagues can be added later.

## Quick start

```bash
pip install -r requirements.txt
python sports_elo.py
```

Then open **`index.html`** (NFL) or **`nhl.html`** (NHL) in any browser. Each is
fully self-contained (the odds are embedded inline, so it loads straight from
disk with no web server).

## Keeping it current

**Live page: https://ryaneunderwood.github.io/PlayoffOdds/** — a GitHub Action
(`.github/workflows/update.yml`) regenerates the odds every 5 minutes, and on every
push, and publishes them to GitHub Pages. Nothing is committed back, so the
`index.html` in the repo is only as fresh as the last manual run; use the live
page, or regenerate locally as below. (GitHub pauses scheduled workflows after
60 days without a commit; re-enable it from the Actions tab if that happens.)

Survivor picks reach the live page by committing `survivor.json` and pushing.

**Re-run `python sports_elo.py` after each week's games** (or any time — it is
safe to run mid-week). Nothing else is needed:

- Schedules, scores and closing lines come straight from the
  [nflverse games table](https://github.com/nflverse/nfldata/blob/master/data/games.csv),
  which is updated within hours of every kickoff. There is no local cache, so
  each run picks up whatever has been played.
- Elo ratings are **walked forward through every completed game** of the
  current season before the remainder is simulated, so ratings, win
  probabilities and the odds all reflect results to date. Played games keep
  the probability the model quoted *before* kickoff.
- The header shows exactly what the page knows: *Through Week N (x of y
  played)*, games in the books, and the generation timestamp. Records and each
  team's Elo movement since preseason appear in the seed table; the
  **Results** tab lists completed games by week with scores and upsets.
- `--season` defaults to the season in progress (the calendar year from March
  on, else the previous year), so the same command works all year.

To work offline or pin a snapshot, point `NFLVERSE_GAMES_CSV` at a local copy
(or any URL) of `games.csv`. A weekly cron entry such as
`0 6 * * 2 cd /path/to/PlayoffOdds && python sports_elo.py` keeps the page
fresh every Tuesday morning after Monday Night Football.

### Options

| flag | default | meaning |
|------|---------|---------|
| `--sport` | `all` | `nfl`, `nhl`, or `all` (one page each) |
| `--season` | each league's current season | the season to project |
| `--start` | `2018` NFL, `2015` NHL | first year of game results used to seed Elo |
| `--sims` | `20000` | number of simulated seasons |
| `--outdir` | `.` | where to write `index.html` + `data.json` (NFL) and `nhl.html` + `nhl.json` (NHL) |

## Interactive what-if

Click any team in the seed grid to open its detail panel: its playoff/division/
conference/title odds, a seed-probability strip, and its full schedule. Every
remaining game has a **Win / Loss / Auto** toggle. Forcing an outcome re-runs a
live Monte Carlo simulation **in your browser** (the Elo ratings and schedule are
embedded in the page) and shows how each odd shifts versus the un-forced
baseline. No server or rebuild needed — it all runs client-side from the single
HTML file.

## Survivor pool planner

The **Upcoming Games** tab opens with a survivor-pool plan: one team per week,
no repeats, ordered to maximise the chance of surviving the whole season (the
product of the picks' win probabilities). That is an assignment problem over
weeks x teams, solved exactly with the Hungarian method rather than greedily,
so a big favourite is held back for a week where nothing else is safe. The
panel shows the next pick, every later pick with the cumulative survival odds,
and each week's best alternatives (flagged if the plan needs them later).

Picks live in `survivor.json`. After you lock a pick, record it so the planner
stops reusing that team:

```bash
python sports_elo.py --pick 2:LAC     # records the pick, then regenerates
```

Completed picks show as survived / eliminated, and a completed week with no
recorded pick is flagged. The order is re-optimised on every run, so it tracks
the latest ratings and results. A tie is treated as a loss.

## How it works

1. **Build Elo** from `--start` through the last completed season (regular
   season **and** playoffs), regressing every team toward the league mean
   between seasons (`preseason_regress`). Win probabilities use a logistic Elo
   curve with a home-field edge and margin-of-victory scaling of the K-factor.
2. **Fold in the current season.** Completed games update the ratings week by
   week (each played game is stored with its pre-kickoff win probability), and
   their results are fixed in every simulation.
3. **Project the rest of the season.** Every remaining game is simulated from
   the current ratings.
4. **Seed the field** with the **real NFL tiebreakers** (`seeding.py`): division
   winners then wild cards, breaking ties by head-to-head, division record,
   common games (min 4 for wild cards), conference record, strength of victory
   and strength of schedule. (The points-based steps and the final coin toss a
   win/loss model can't compute are replaced by a random draw; they're reached
   essentially never.)
5. **Run the bracket** each simulation for conference- and title-win odds.
6. **Render** a self-contained `index.html`.

### Clinch / elimination (the `X` and `^` markers)

`X` (mathematically eliminated) and `^` (clinched) come from a **pruned,
tiebreaker-aware feasibility search**, not from the simulation count. For each
team it limits attention to the contenders within two wins of the cut, fixes the
other games favorably/unfavorably, and then **exhaustively enumerates the games
between two contenders** — the *coupled* games — applying the real tiebreakers to
each. This captures interactions like: a bubble team can pass the current #7 seed
by record, yet still be eliminated because the games that knock the #7 down
necessarily lift whoever beats them. When too many coupled games remain to
enumerate (early season), the team is reported as fully live — never a false
`X`/`^`.

## NHL

`nhl.py` holds the hockey-specific pieces; everything else (Elo, the
in-season walk-forward, the pages and the in-browser what-if) is shared.

- **Data** comes from the [NHL stats API](https://api.nhle.com/stats/rest/en/game),
  one request per season, refreshed on every run. Elo is walked forward a day
  at a time, and history starts in 2015-16. K = 8, home ice = 25 Elo and
  offseason regression 0.65 were tuned on 2021-22 to 2025-26 results.
- **Points.** Win 2, overtime/shootout loss 1. In simulated games, 22% go past
  regulation (28% of those to a shootout), matching recent seasons, so the
  loser picks up a point. Standings show W-L-OT and points; the table projects
  final points.
- **Seeding** per conference: top three in each division (**Div 1-3**) plus two
  wild cards (**WC1**, **WC2**). Ties go to regulation wins, then regulation +
  overtime wins, total wins and head-to-head points. Goal differential (not
  simulated) is a random draw. This reproduces the 2025-26 final standings
  exactly.
- **Bracket**: fixed, no reseeding. The better division winner plays WC2, the
  other WC1, and 2 plays 3 in each division. Every round is a best-of-seven
  (2-2-1-1-1) with home ice to the better record. "Title" is the Stanley Cup.
- **X / ^** come from exact points bounds: current points to current points
  plus 2 per game left. They never fire falsely, but they ignore that
  contenders take points off each other, so they can show up a day or two
  after the league declares a clinch or elimination.
- The **Upcoming Games** tab lists the next seven game days. The survivor
  pool is NFL-only.

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

- `sports_elo.py` — nflverse data loader, Elo engine, sport config, Monte
  Carlo, feasibility, CLI.
- `nhl.py` — NHL stats-API loader, points/OT model, NHL tiebreakers and
  seeding, best-of-seven bracket, clinch/elimination bounds.
- `seeding.py` — NFL tiebreaker + conference-seeding engine and the
  clinch/elimination feasibility search.
- `render.py` — self-contained HTML renderer; the in-browser engine is a faithful
  JS port of `seeding.py` (validated by cross-check against the Python).
- `Sports Monte Carlo.ipynb` — the original notebook this was derived from.
