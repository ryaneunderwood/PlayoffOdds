#!/usr/bin/env python3
"""
sports_elo.py -- a playoffstatus.com-style playoff-odds engine driven by
historical-Elo Monte Carlo simulation.

Originally derived from the "Sports Monte Carlo" notebook. The Elo model and
playoff-bracket simulation are generalized behind a per-sport configuration so
new leagues can be added later. Currently only football (NFL) is implemented.

Pipeline (per sport):
  1. Build Elo ratings from `start_year` through the end of the most recent
     completed season (regular season + playoffs).
  2. Apply a preseason regression toward the mean to get the upcoming season's
     starting ratings.
  3. Monte-Carlo simulate the upcoming regular season game-by-game using Elo
     win probabilities, then apply the league's seeding rules.
  4. Tally, for every team, the probability of each playoff seed, winning its
     division, making the playoffs, and (via a bracket sim) winning the
     conference / championship.
  5. Emit a self-contained index.html that loads directly from disk.

Usage:
    python sports_elo.py                    # current season, 20k sims
    python sports_elo.py --season 2026 --start 2018 --sims 20000

Re-run it whenever games have been played: the schedule/results come straight
from the nflverse games table, which is updated within hours of each kickoff,
and the Elo ratings are walked forward through every completed game before
the remaining season is simulated.

Franchise continuity (relocations / renames that keep the same players) is
handled by canonicalizing every team code to a single franchise key, so Elo
carries across a move (e.g. Oakland -> Las Vegas Raiders).
"""

from __future__ import annotations

import argparse
import json
from math import log
from typing import Dict, List, Optional, Tuple

import numpy as np

import seeding

rng = np.random.default_rng()


# ----------------------------------------------------------------------------
# Elo model (generic across sports)
# ----------------------------------------------------------------------------
def elo_expected(ra: float, rb: float, H: float = 0.0) -> float:
    """Expected score for A vs B with home-field offset H (+ favors A)."""
    return 1.0 / (1.0 + 10 ** (-(ra - rb + H) / 400.0))


def elo_update(ra: float, rb: float, score_a: float,
               K: float = 20.0, H: float = 0.0,
               margin: Optional[float] = None) -> Tuple[float, float]:
    """One-game Elo update for A vs B. score_a: 1 win / 0.5 tie / 0 loss."""
    ea = elo_expected(ra, rb, H)
    eb = 1.0 - ea
    mov_mult = 1.0
    if margin is not None:
        mov_mult = log(abs(margin) + 1.0) * (2.2 / (0.001 * abs(ra - rb) + 2.2))
    ke = K * mov_mult
    ra_new = ra + ke * (score_a - ea)
    rb_new = rb + ke * ((1.0 - score_a) - eb)
    return ra_new, rb_new


def preseason_regress(ratings: Dict[str, float],
                      mean: float = 1500.0, rho: float = 0.65) -> Dict[str, float]:
    """Shrink ratings toward the league mean at season start."""
    return {t: mean + rho * (r - mean) for t, r in ratings.items()}


def win_prob(team_a: str, team_b: str, ratings: Dict[str, float],
             home_for_a: bool = True, home_field: float = 55.0) -> float:
    """Pre-game win probability for A over B."""
    ra = ratings.get(team_a, 1500.0)
    rb = ratings.get(team_b, 1500.0)
    H = home_field if home_for_a else 0.0
    return elo_expected(ra, rb, H)


# ----------------------------------------------------------------------------
# Sport configuration
# ----------------------------------------------------------------------------
class SportConfig:
    """Everything league-specific lives here so the engine stays generic."""

    def __init__(self, key, name, divisions, aliases, schedule_loader,
                 k=20.0, home_field=55.0, mean=1500.0, rho=0.65,
                 division_winner_seeds=4, wildcard_seeds=3, byes=1,
                 meta_loader=None):
        self.key = key
        self.name = name
        # divisions: {division_label: [canonical team codes]}
        self.divisions = divisions
        self.aliases = aliases
        self.schedule_loader = schedule_loader  # fn(season) -> list of games
        # optional fn(season) -> {(week, home, away): {weekday, gameday,
        # home_ml, away_ml}} used to enrich the upcoming-games view
        self.meta_loader = meta_loader
        self.k = k
        self.home_field = home_field
        self.mean = mean
        self.rho = rho
        self.division_winner_seeds = division_winner_seeds  # seeds 1..n are div winners
        self.wildcard_seeds = wildcard_seeds                # seeds n+1.. are wild cards
        self.byes = byes  # number of top seeds with a first-round bye

        # Derived lookups
        self.teams = [t for tlist in divisions.values() for t in tlist]
        self.team_division = {t: d for d, tlist in divisions.items()
                              for t in tlist}
        # Conference = first token of the division label ("AFC East" -> "AFC")
        self.team_conf = {t: d.split()[0] for d, tlist in divisions.items()
                          for t in tlist}
        self.conferences = sorted(set(self.team_conf.values()))
        self.seeds_per_conf = division_winner_seeds + wildcard_seeds

    def canon(self, t: str) -> str:
        return self.aliases.get(t, t)


# ----------------------------------------------------------------------------
# NFL configuration + schedule loader
# ----------------------------------------------------------------------------
NFL_DIVISIONS = {
    "AFC East":  ["BUF", "MIA", "NE", "NYJ"],
    "AFC North": ["BAL", "CIN", "CLE", "PIT"],
    "AFC South": ["HOU", "IND", "JAX", "TEN"],
    "AFC West":  ["DEN", "KC", "LAC", "LV"],
    "NFC East":  ["DAL", "NYG", "PHI", "WAS"],
    "NFC North": ["CHI", "DET", "GB", "MIN"],
    "NFC South": ["ATL", "CAR", "NO", "TB"],
    "NFC West":  ["ARI", "LA", "SF", "SEA"],
}

# Relocation / rename aliases. The right-hand side is the canonical franchise
# key, so Elo carries across the move even though the players stayed the same.
NFL_ALIASES = {
    "OAK": "LV",    # Oakland -> Las Vegas Raiders (2020)
    "SD":  "LAC",   # San Diego -> Los Angeles Chargers (2017)
    "STL": "LA",    # St. Louis -> Los Angeles Rams (2016)
    "LAR": "LA",    # Rams sometimes coded LAR
    "JAC": "JAX",   # Jacksonville code variant
    "WSH": "WAS",   # Washington code variant
}


# The nflverse games table (Lee Sharpe's games.csv) is the source of truth
# for schedules, scores and closing lines. It is updated within hours of every
# kickoff, so re-running the pipeline is all it takes to fold in new results.
# `nfl_data_py` is just a thin wrapper around this same file (and pins
# numpy<2), so we read it directly with pandas.
NFLVERSE_GAMES_URL = "https://github.com/nflverse/nfldata/raw/master/data/games.csv"
_GAMES_DF = None


def nfl_games_df(season: int | None = None):
    """The full nflverse games table (all seasons), fetched once per process.

    Override the source with the ``NFLVERSE_GAMES_CSV`` environment variable
    (a local path or URL) to work offline or pin a snapshot. Pass ``season``
    to get just that season's rows."""
    global _GAMES_DF
    if _GAMES_DF is None:
        import os
        import pandas as pd
        src = os.environ.get("NFLVERSE_GAMES_CSV", NFLVERSE_GAMES_URL)
        df = pd.read_csv(src, low_memory=False)
        df = df.dropna(subset=["season", "week"]).copy()
        df["season"] = df["season"].astype(int)
        df["week"] = df["week"].astype(int)
        _GAMES_DF = df
    if season is None:
        return _GAMES_DF
    return _GAMES_DF[_GAMES_DF["season"] == int(season)]


def _num(x):
    return None if x is None or x != x else float(x)


def _txt(x):
    return None if x is None or x != x else str(x)


def load_nfl_schedule(season: int, include_playoffs: bool = True):
    """Return {week: [(home, away, home_score|None, away_score|None, neutral)]}.

    Scores are None for games that have not been played yet.
    """
    sched = nfl_games_df(season)
    if include_playoffs:
        sched = sched[sched["game_type"].isin(["REG", "WC", "DIV", "CON", "SB"])]
    else:
        sched = sched[sched["game_type"] == "REG"]

    has_loc = "location" in sched.columns
    weekly: Dict[int, list] = {}
    for r in sched.itertuples(index=False):
        neutral = bool(has_loc and str(r.location).lower() == "neutral")
        weekly.setdefault(int(r.week), []).append(
            (r.home_team, r.away_team, _num(r.home_score), _num(r.away_score), neutral))
    return weekly


def load_nfl_meta(season: int):
    """Per-game kickoff day/time + closing moneylines keyed by (week, home,
    away) canonical codes. Used only to enrich the games views; any missing
    field comes back as None and the renderer simply omits it."""
    sched = nfl_games_df(season)
    cols = set(sched.columns)
    get = lambda r, c, f: f(getattr(r, c, None)) if c in cols else None

    meta = {}
    for r in sched.itertuples(index=False):
        h, a = NFL.canon(r.home_team), NFL.canon(r.away_team)
        meta[(int(r.week), h, a)] = {
            "weekday": get(r, "weekday", _txt),
            "gameday": get(r, "gameday", _txt),
            "gametime": get(r, "gametime", _txt),
            "home_ml": get(r, "home_moneyline", _num),
            "away_ml": get(r, "away_moneyline", _num),
            "spread_line": get(r, "spread_line", _num),
        }
    return meta


NFL = SportConfig(
    key="nfl",
    name="NFL Football",
    divisions=NFL_DIVISIONS,
    aliases=NFL_ALIASES,
    schedule_loader=load_nfl_schedule,
    meta_loader=load_nfl_meta,
    k=20.0,
    home_field=55.0,
    division_winner_seeds=4,
    wildcard_seeds=3,
    byes=1,
)

SPORTS = {"nfl": NFL}


# ----------------------------------------------------------------------------
# Build historical Elo ratings
# ----------------------------------------------------------------------------
def apply_week(sport: SportConfig, ratings: Dict[str, float], games) -> Dict[str, float]:
    """Update ratings for one week of *played* games (scores not None)."""
    new_r = ratings.copy()
    for home, away, hs, as_, neutral in games:
        if hs is None or as_ is None:
            continue
        home, away = sport.canon(home), sport.canon(away)
        ra = new_r.get(home, sport.mean)
        rb = new_r.get(away, sport.mean)
        if hs > as_:
            sh = 1.0
        elif hs == as_:
            sh = 0.5
        else:
            sh = 0.0
        H = 0.0 if neutral else sport.home_field
        ra2, rb2 = elo_update(ra, rb, sh, K=sport.k, H=H, margin=abs(hs - as_))
        new_r[home], new_r[away] = ra2, rb2
    return new_r


def build_ratings(sport: SportConfig, start_year: int, end_year: int):
    """Run Elo from start_year through end_year (inclusive), regressing between
    seasons. Returns (ratings_after_last_played_season, last_completed_year)."""
    ratings = {t: sport.mean for t in sport.teams}
    last_completed = None
    for year in range(start_year, end_year + 1):
        weekly = sport.schedule_loader(year, include_playoffs=True)
        played_any = False
        for wk in sorted(weekly):
            if any(g[2] is not None and g[3] is not None for g in weekly[wk]):
                ratings = apply_week(sport, ratings, weekly[wk])
                played_any = True
        if played_any:
            last_completed = year
            # Regress toward the mean before the next season starts.
            ratings = preseason_regress(ratings, mean=sport.mean, rho=sport.rho)
    return ratings, last_completed


# ----------------------------------------------------------------------------
# Regular-season Monte Carlo + seeding
# ----------------------------------------------------------------------------
def build_game_arrays(sport, ratings, schedule):
    """From the flat schedule list, return arrays aligned by game index:
    (home_idx, away_idx, p_home, fixed_winner) plus the League. fixed_winner is
    the team index for a played game, or -1 if the game is still open."""
    idx = {t: i for i, t in enumerate(sport.teams)}
    games, p_home, fixed = [], [], []
    for g in schedule:
        h, a = idx[g["home"]], idx[g["away"]]
        games.append((h, a))
        p_home.append(g["p_home"])
        if g["played"] and g["winner"] in ("home", "away"):
            fixed.append(h if g["winner"] == "home" else a)
        else:
            fixed.append(-1)
    team_conf = {idx[t]: sport.team_conf[t] for t in sport.teams}
    team_div = {idx[t]: sport.team_division[t] for t in sport.teams}
    league = seeding.League(sport.teams, team_conf, team_div, games)
    return (idx, league, np.array(p_home), np.array(fixed, dtype=int))


def simulate_season(sport: SportConfig, ratings: Dict[str, float],
                    schedule, sims: int = 20000):
    """Monte-Carlo the upcoming regular season, seeding each simulated season
    with the real NFL tiebreaker engine (seeding.py).

    Returns per-team seed/division/playoff probabilities, the win-total
    distribution, and the per-sim final seeds for the bracket sim.
    """
    teams = sport.teams
    idx, league, p_home, fixed = build_game_arrays(sport, ratings, schedule)
    n = len(teams)
    ng = len(p_home)

    # Per-game winners for every sim: played games are fixed, open games drawn.
    open_mask = fixed < 0
    home_idx = league.home.astype(np.int64)
    away_idx = league.away.astype(np.int64)
    winners = np.empty((sims, ng), dtype=np.int32)
    winners[:, ~open_mask] = fixed[~open_mask]
    if open_mask.any():
        draws = rng.random((sims, int(open_mask.sum())))
        hp = p_home[open_mask]
        oh = home_idx[open_mask]; oa = away_idx[open_mask]
        winners[:, open_mask] = np.where(draws < hp, oh, oa).astype(np.int32)

    # Vectorized win / division-win / conference-win totals per sim.
    rows = np.arange(sims)[:, None]
    W = np.zeros((sims, n)); dW = np.zeros((sims, n)); cW = np.zeros((sims, n))
    np.add.at(W, (rows, winners), 1.0)
    div_cols = winners[:, league.is_div]
    np.add.at(dW, (rows, div_cols), 1.0)
    conf_cols = winners[:, league.is_conf]
    np.add.at(cW, (rows, conf_cols), 1.0)

    seed_counts = {t: np.zeros(sport.seeds_per_conf + 1) for t in teams}
    div_winner = {t: 0 for t in teams}
    make_playoffs = {t: 0 for t in teams}
    final_seed = np.zeros((sims, n), dtype=int)

    for s in range(sims):
        ws = winners[s]
        Ws, dWs, cWs = W[s], dW[s], cW[s]
        for conf in sport.conferences:
            seeds = seeding.seed_conference(league, conf, ws, Ws, dWs, cWs, rng)
            for ti, sd in seeds.items():
                final_seed[s, ti] = sd

    for t in teams:
        ti = idx[t]
        seeds = final_seed[:, ti]
        for seed in range(1, sport.seeds_per_conf + 1):
            seed_counts[t][seed - 1] = np.sum(seeds == seed)
        seed_counts[t][sport.seeds_per_conf] = np.sum(seeds == 0)  # miss
        make_playoffs[t] = int(np.sum(seeds > 0))
        div_winner[t] = int(np.sum((seeds >= 1) &
                                   (seeds <= sport.division_winner_seeds)))

    win_dist = {t: W[:, idx[t]] for t in teams}

    return {
        "sims": sims,
        "idx": idx,
        "league": league,
        "final_seed": final_seed,
        "seed_counts": seed_counts,
        "div_winner": div_winner,
        "make_playoffs": make_playoffs,
        "win_dist": win_dist,
    }


# ----------------------------------------------------------------------------
# Playoff bracket Monte Carlo (conference + championship odds)
# ----------------------------------------------------------------------------
def simulate_bracket(sport: SportConfig, ratings: Dict[str, float], season_res):
    """Given per-sim final seeds, simulate the playoff bracket to get
    conference-championship and title odds per team."""
    teams = sport.teams
    idx = season_res["idx"]
    final_seed = season_res["final_seed"]
    sims = season_res["sims"]
    inv_idx = {i: t for t, i in idx.items()}

    conf_champ = {t: 0 for t in teams}
    title = {t: 0 for t in teams}

    nseed = sport.seeds_per_conf
    confs = sport.conferences

    for s in range(sims):
        seeds_this = final_seed[s]
        # seed_team[conf][seed] = team code
        conf_seed_team = {c: {} for c in confs}
        for ti in range(len(teams)):
            sd = seeds_this[ti]
            if sd >= 1:
                t = inv_idx[ti]
                conf_seed_team[sport.team_conf[t]][sd] = t

        conf_winners = {}
        for c in confs:
            st = conf_seed_team[c]
            if len(st) < nseed:
                continue
            # Reseeding single-elimination with `byes` top seeds idle round 1.
            alive = list(range(1, nseed + 1))  # seed numbers still alive
            byes = sport.byes
            while len(alive) > 1:
                alive.sort()
                playing = alive[byes:] if len(alive) > byes else alive
                idle = alive[:byes] if len(alive) > byes else []
                # Pair highest vs lowest among `playing`.
                next_round = list(idle)
                lo, hi = 0, len(playing) - 1
                winners_round = []
                while lo < hi:
                    sa, sb = playing[lo], playing[hi]
                    ta, tb = st[sa], st[sb]
                    # Higher seed (sa) hosts.
                    if rng.random() < win_prob(ta, tb, ratings,
                                               home_for_a=True,
                                               home_field=sport.home_field):
                        winners_round.append(sa)
                    else:
                        winners_round.append(sb)
                    lo += 1; hi -= 1
                if lo == hi:  # odd one out advances
                    winners_round.append(playing[lo])
                next_round.extend(winners_round)
                alive = next_round
                byes = 0  # byes only apply to the first round
            conf_winners[c] = st[alive[0]]
            conf_champ[st[alive[0]]] += 1

        # Championship game (neutral site).
        if len(conf_winners) == len(confs):
            cw = list(conf_winners.values())
            ta, tb = cw[0], cw[1]
            if rng.random() < win_prob(ta, tb, ratings, home_for_a=False,
                                       home_field=sport.home_field):
                title[ta] += 1
            else:
                title[tb] += 1

    return {"conf_champ": conf_champ, "title": title}


# ----------------------------------------------------------------------------
# Upcoming-game probabilities
# ----------------------------------------------------------------------------
def upcoming_games(sport: SportConfig, ratings: Dict[str, float], weekly_schedule):
    """Per-week list of unplayed games with home win probability."""
    out = []
    for wk in sorted(weekly_schedule):
        games = []
        for home, away, hs, as_, neutral in weekly_schedule[wk]:
            if hs is not None and as_ is not None:
                continue
            h, a = sport.canon(home), sport.canon(away)
            H = 0.0 if neutral else sport.home_field
            p = elo_expected(ratings.get(h, sport.mean),
                             ratings.get(a, sport.mean), H)
            games.append({
                "home": h, "away": a, "neutral": neutral,
                "home_wp": round(100 * p, 1), "away_wp": round(100 * (1 - p), 1),
            })
        if games:
            out.append({"week": wk, "games": games})
    return out


def build_schedule(sport: SportConfig, ratings: Dict[str, float], weekly_schedule):
    """Flat per-game list for the in-browser simulator, plus the ratings after
    folding in every game of this season that has already been played.

    Ratings are walked forward week by week, so a played game carries the
    win probability the model would have quoted *before* kickoff, while every
    remaining game is priced off the current (post-results) ratings -- that is
    what the Monte Carlo and the client-side what-if simulator use.
    """
    weeks = sorted(weekly_schedule)
    # First pass: ratings entering each week, and the current ratings.
    entering = {}
    cur = dict(ratings)
    for wk in weeks:
        entering[wk] = cur
        cur = apply_week(sport, cur, weekly_schedule[wk])
    ratings_now = cur

    out = []
    gid = 0
    for wk in weeks:
        for home, away, hs, as_, neutral in weekly_schedule[wk]:
            h, a = sport.canon(home), sport.canon(away)
            if h not in sport.team_conf or a not in sport.team_conf:
                continue
            played = hs is not None and as_ is not None
            r = entering[wk] if played else ratings_now
            H = 0.0 if neutral else sport.home_field
            p = elo_expected(r.get(h, sport.mean), r.get(a, sport.mean), H)
            winner = None
            if played:
                winner = "home" if hs > as_ else ("away" if hs < as_ else "tie")
            g = {
                "id": gid, "week": wk, "home": h, "away": a,
                "neutral": neutral, "played": played, "winner": winner,
                "p_home": round(p, 4),
            }
            if played:
                g["home_score"] = int(hs)
                g["away_score"] = int(as_)
            out.append(g)
            gid += 1
    return out, ratings_now


def season_progress(weekly_schedule):
    """How far the season has progressed: games played/total, the latest week
    with a result, and whether that week is finished."""
    total = sum(len(v) for v in weekly_schedule.values())
    played = sum(1 for v in weekly_schedule.values()
                 for g in v if g[2] is not None and g[3] is not None)
    through = 0
    for wk in sorted(weekly_schedule):
        if any(g[2] is not None and g[3] is not None for g in weekly_schedule[wk]):
            through = wk
    wk_games = weekly_schedule.get(through, [])
    wk_played = sum(1 for g in wk_games if g[2] is not None and g[3] is not None)
    return {
        "games_played": played, "games_total": total,
        "through_week": through,
        "week_games_played": wk_played, "week_games_total": len(wk_games),
        "week_complete": bool(wk_games) and wk_played == len(wk_games),
    }


def team_records(sport: SportConfig, schedule):
    """Current W-L-T per team from the played games."""
    rec = {t: [0, 0, 0] for t in sport.teams}
    for g in schedule:
        if not g["played"]:
            continue
        if g["winner"] == "home":
            rec[g["home"]][0] += 1; rec[g["away"]][1] += 1
        elif g["winner"] == "away":
            rec[g["away"]][0] += 1; rec[g["home"]][1] += 1
        else:
            rec[g["home"]][2] += 1; rec[g["away"]][2] += 1
    return rec


# ----------------------------------------------------------------------------
# Orchestration
# ----------------------------------------------------------------------------
def run(sport_key: str, season: int, start_year: int, sims: int):
    sport = SPORTS[sport_key]
    print(f"[{sport.name}] building Elo {start_year}..{season - 1} ...")
    ratings, last_completed = build_ratings(sport, start_year, season - 1)
    print(f"  last completed season: {last_completed}")

    # `ratings` already has the upcoming-season preseason regression applied
    # (build_ratings regresses after each played season).
    print(f"[{sport.name}] loading {season} schedule ...")
    weekly = sport.schedule_loader(season, include_playoffs=False)
    n_games = sum(len(v) for v in weekly.values())
    print(f"  {n_games} games across {len(weekly)} weeks")

    progress = season_progress(weekly)
    preseason = ratings
    schedule, ratings = build_schedule(sport, preseason, weekly)
    if progress["games_played"]:
        wk = progress["through_week"]
        state = ("complete" if progress["week_complete"] else
                 f'{progress["week_games_played"]}/{progress["week_games_total"]} played')
        print(f'  {progress["games_played"]} of {progress["games_total"]} games played; '
              f"through week {wk} ({state}); Elo updated with results to date")
    else:
        print("  no games played yet; using preseason ratings")
    games = upcoming_games(sport, ratings, weekly)

    # Enrich the upcoming-games view with kickoff day + moneylines when the
    # sport provides a metadata loader (graceful: any missing field is omitted).
    if sport.meta_loader is not None:
        try:
            meta = sport.meta_loader(season)
            for wk in games:
                for g in wk["games"]:
                    m = meta.get((wk["week"], g["home"], g["away"]))
                    if m:
                        g.update({k: v for k, v in m.items() if v is not None})
            print(f"  enriched {sum(len(w['games']) for w in games)} games with kickoff/line metadata")
        except Exception as e:  # never let metadata break the core pipeline
            print(f"  (metadata enrichment skipped: {e})")

    print(f"[{sport.name}] simulating regular season ({sims} sims, NFL tiebreakers) ...")
    season_res = simulate_season(sport, ratings, schedule, sims=sims)

    print(f"[{sport.name}] simulating playoff brackets ...")
    bracket = simulate_bracket(sport, ratings, season_res)

    data = assemble_payload(sport, season, start_year, ratings, preseason,
                            last_completed, season_res, bracket, games,
                            schedule, progress)
    return sport, data


def assemble_payload(sport, season, start_year, ratings, preseason,
                     last_completed, season_res, bracket, games, schedule,
                     progress):
    from datetime import datetime, timezone
    records = team_records(sport, schedule)
    sims = season_res["sims"]
    teams = sport.teams
    miss_seed = sport.seeds_per_conf + 1
    idx = season_res["idx"]
    league = season_res["league"]
    final_seed = season_res["final_seed"]

    # Current results as a per-game winners array (-1 = still open), aligned to
    # league.games / schedule order, for the feasibility (clinch/elimination)
    # solver.
    base_winners = np.full(len(schedule), -1, dtype=int)
    for gi, g in enumerate(schedule):
        if g["played"] and g["winner"] in ("home", "away"):
            base_winners[gi] = idx[g["home"] if g["winner"] == "home" else g["away"]]

    rows = []
    for t in teams:
        sc = season_res["seed_counts"][t]
        seed_probs = [round(100 * sc[i] / sims, 1) for i in range(sport.seeds_per_conf)]
        miss = round(100 * sc[sport.seeds_per_conf] / sims, 1)

        # Achievable seeds via the pruned, tiebreaker-aware feasibility search,
        # unioned with every seed actually reached across the MC trials.
        fs = final_seed[:, idx[t]]
        mc_hit = {int(x) if x >= 1 else miss_seed for x in np.unique(fs)}
        ach = seeding.achievable_seeds(league, base_winners, idx[t], rng, mc_hit)

        rows.append({
            "team": t,
            "conf": sport.team_conf[t],
            "div": sport.team_division[t],
            "elo": round(ratings.get(t, sport.mean)),
            "elo_pre": round(preseason.get(t, sport.mean)),
            "wins": records[t][0], "losses": records[t][1], "ties": records[t][2],
            "proj_wins": round(float(np.mean(season_res["win_dist"][t])), 1),
            "seed_probs": seed_probs,
            "miss": miss,
            "ach": ach,
            "make_playoffs": round(100 * season_res["make_playoffs"][t] / sims, 1),
            "win_div": round(100 * season_res["div_winner"][t] / sims, 1),
            "win_conf": round(100 * bracket["conf_champ"][t] / sims, 1),
            "win_title": round(100 * bracket["title"][t] / sims, 1),
        })
    rows.sort(key=lambda r: (-r["make_playoffs"], -r["proj_wins"]))

    return {
        "sport": sport.name,
        "sport_key": sport.key,
        "season": season,
        "start_year": start_year,
        "last_completed": last_completed,
        "sims": sims,
        "seeds_per_conf": sport.seeds_per_conf,
        "division_winner_seeds": sport.division_winner_seeds,
        "wildcard_seeds": sport.wildcard_seeds,
        "byes": sport.byes,
        "home_field": sport.home_field,
        "mean": sport.mean,
        "conferences": sport.conferences,
        "divisions": {d: tlist for d, tlist in sport.divisions.items()},
        "teams": sport.teams,
        "ratings": {t: round(ratings.get(t, sport.mean), 1) for t in sport.teams},
        "ratings_pre": {t: round(preseason.get(t, sport.mean), 1) for t in sport.teams},
        "progress": progress,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "rows": rows,
        "upcoming": games,
        "schedule": schedule,
    }


def current_season() -> int:
    """The NFL season in progress or next up: a season is labelled by the year
    it kicks off, and the previous one is over by mid-February."""
    from datetime import date
    today = date.today()
    return today.year if today.month >= 3 else today.year - 1


def main():
    ap = argparse.ArgumentParser(description="playoffstatus-style odds via Elo Monte Carlo")
    ap.add_argument("--sport", default="nfl", choices=list(SPORTS))
    ap.add_argument("--season", type=int, default=current_season(),
                    help="season to project (default: the current/upcoming one)")
    ap.add_argument("--start", type=int, default=2018, help="Elo history start year")
    ap.add_argument("--sims", type=int, default=20000)
    ap.add_argument("--out", default="index.html")
    ap.add_argument("--json", default="data.json")
    args = ap.parse_args()

    sport, data = run(args.sport, args.season, args.start, args.sims)

    with open(args.json, "w") as f:
        json.dump(data, f, indent=2)
    print(f"  wrote {args.json}")

    from render import render_html
    html = render_html(data)
    with open(args.out, "w") as f:
        f.write(html)
    print(f"  wrote {args.out}")


if __name__ == "__main__":
    main()
