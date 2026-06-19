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
    python sports_elo.py --sport nfl --season 2026 --start 2018 --sims 20000

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
                 division_winner_seeds=4, wildcard_seeds=3, byes=1):
        self.key = key
        self.name = name
        # divisions: {division_label: [canonical team codes]}
        self.divisions = divisions
        self.aliases = aliases
        self.schedule_loader = schedule_loader  # fn(season) -> list of games
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


def load_nfl_schedule(season: int, include_playoffs: bool = True):
    """Return {week: [(home, away, home_score|None, away_score|None, neutral)]}.

    Scores are None for games that have not been played yet.
    """
    import nfl_data_py as nfl
    sched = nfl.import_schedules([season])

    if include_playoffs:
        sched = sched[sched["game_type"].isin(["REG", "WC", "DIV", "CON", "SB"])]
    else:
        sched = sched[sched["game_type"] == "REG"]

    sched = sched.dropna(subset=["week"]).copy()
    sched["week"] = sched["week"].astype(int)

    cols = ["home_team", "away_team", "home_score", "away_score", "week"]
    has_loc = "location" in sched.columns
    weekly: Dict[int, list] = {}
    for row in sched[cols + (["location"] if has_loc else [])].to_numpy():
        h, a, hs, as_, wk = row[0], row[1], row[2], row[3], int(row[4])
        neutral = bool(has_loc and str(row[5]).lower() == "neutral")
        hs = None if hs is None or (isinstance(hs, float) and np.isnan(hs)) else float(hs)
        as_ = None if as_ is None or (isinstance(as_, float) and np.isnan(as_)) else float(as_)
        weekly.setdefault(wk, []).append((h, a, hs, as_, neutral))
    return weekly


NFL = SportConfig(
    key="nfl",
    name="NFL Football",
    divisions=NFL_DIVISIONS,
    aliases=NFL_ALIASES,
    schedule_loader=load_nfl_schedule,
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
def simulate_season(sport: SportConfig, ratings: Dict[str, float],
                    weekly_schedule, sims: int = 20000):
    """Monte-Carlo the upcoming regular season.

    Returns a dict with per-team seed/division/playoff probabilities and the
    win-total distribution, plus the per-sim final seeds for the bracket sim.
    """
    teams = sport.teams
    idx = {t: i for i, t in enumerate(teams)}
    n = len(teams)

    # Flatten all (unplayed) regular-season games into arrays.
    home_i, away_i, p_home = [], [], []
    base_wins = np.zeros(n)  # already-played games contribute fixed wins
    for wk in sorted(weekly_schedule):
        for home, away, hs, as_, neutral in weekly_schedule[wk]:
            h, a = sport.canon(home), sport.canon(away)
            if h not in idx or a not in idx:
                continue
            if hs is not None and as_ is not None:
                # Game already played -> fixed result.
                if hs > as_:
                    base_wins[idx[h]] += 1
                elif hs < as_:
                    base_wins[idx[a]] += 1
                else:
                    base_wins[idx[h]] += 0.5
                    base_wins[idx[a]] += 0.5
                continue
            H = 0.0 if neutral else sport.home_field
            p = elo_expected(ratings.get(h, sport.mean),
                             ratings.get(a, sport.mean), H)
            home_i.append(idx[h]); away_i.append(idx[a]); p_home.append(p)

    home_i = np.array(home_i, dtype=int)
    away_i = np.array(away_i, dtype=int)
    p_home = np.array(p_home, dtype=float)
    g = len(p_home)

    # Vectorized game outcomes: (sims x games) boolean home-win matrix.
    wins = np.tile(base_wins, (sims, 1)).astype(float)
    if g:
        draws = rng.random((sims, g))
        home_win = draws < p_home  # True -> home team wins
        # Accumulate wins per team using bincount per column would be slow;
        # use np.add.at on flattened indices.
        winners = np.where(home_win, home_i, away_i)  # (sims x games) team idx
        # Tally winners per sim.
        for sgames in (winners,):
            np.add.at(wins, (np.arange(sims)[:, None], sgames), 1.0)

    # Tiebreak noise: small, consistent within a sim, unbiased.
    score = wins + rng.random((sims, n)) * 1e-3

    # Seed assignment per conference.
    seed_counts = {t: np.zeros(sport.seeds_per_conf + 1) for t in teams}  # +1 = miss
    div_winner = {t: 0 for t in teams}
    make_playoffs = {t: 0 for t in teams}
    # final_seed[sim, team] -> seed number (1..seeds_per_conf) or 0 if missed
    final_seed = np.zeros((sims, n), dtype=int)

    for conf in sport.conferences:
        conf_divs = [d for d in sport.divisions if d.split()[0] == conf]
        conf_team_idx = [idx[t] for d in conf_divs for t in sport.divisions[d]]

        # Division winners: best score within each division.
        winner_idx_per_div = []
        for d in conf_divs:
            dteam_idx = np.array([idx[t] for t in sport.divisions[d]])
            best = dteam_idx[np.argmax(score[:, dteam_idx], axis=1)]  # (sims,)
            winner_idx_per_div.append(best)
        div_winners = np.stack(winner_idx_per_div, axis=1)  # (sims x ndiv)

        # Seeds 1..division_winner_seeds: rank division winners by score.
        dw_scores = np.take_along_axis(
            score[:, :], div_winners, axis=1)  # (sims x ndiv) scores of winners
        order = np.argsort(-dw_scores, axis=1)  # high score first
        ranked_div_winners = np.take_along_axis(div_winners, order, axis=1)

        # Wild cards: non-division-winners in the conference, top `wildcard_seeds`.
        conf_idx_arr = np.array(conf_team_idx)
        for s in range(sims):
            dwset = set(div_winners[s].tolist())
            # Division-winner seeds.
            for seed_pos in range(sport.division_winner_seeds):
                ti = ranked_div_winners[s, seed_pos]
                final_seed[s, ti] = seed_pos + 1
            # Wild-card pool.
            pool = [(score[s, ti], ti) for ti in conf_idx_arr if ti not in dwset]
            pool.sort(reverse=True)
            for w in range(sport.wildcard_seeds):
                ti = pool[w][1]
                final_seed[s, ti] = sport.division_winner_seeds + w + 1

    # Tally.
    for t in teams:
        ti = idx[t]
        seeds = final_seed[:, ti]
        for seed in range(1, sport.seeds_per_conf + 1):
            seed_counts[t][seed - 1] = np.sum(seeds == seed)
        seed_counts[t][sport.seeds_per_conf] = np.sum(seeds == 0)  # miss
        make_playoffs[t] = int(np.sum(seeds > 0))
        # Division winner == earned one of the top `division_winner_seeds` seeds.
        div_winner[t] = int(np.sum((seeds >= 1) &
                                   (seeds <= sport.division_winner_seeds)))

    win_dist = {t: wins[:, idx[t]] for t in teams}

    return {
        "sims": sims,
        "idx": idx,
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
# Mathematical feasibility (clinch / elimination)
# ----------------------------------------------------------------------------
# A team's seed is encoded 1..seeds_per_conf, with `seeds_per_conf + 1` meaning
# "missed the playoffs". We determine which seeds are *achievable* by combining
# (a) every seed actually reached across the Monte Carlo trials with (b) two
# deterministic contrived scenarios (maximally favorable / unfavorable) for the
# remaining games. A seed shown as X was reached by neither -- i.e. there is no
# scenario, contrived or simulated, that produces it. A cell shown as ^ is the
# team's only achievable outcome.
def _score_from_wins(sport, ratings, wins, favor=None, favor_high=True):
    """Deterministic standings score. Wins dominate; a small favor term breaks
    ties for/against `favor`; Elo breaks any remaining ties reproducibly."""
    out = {}
    for t in sport.teams:
        fav = (0.5 if favor_high else -0.5) if (favor is not None and t == favor) else 0.0
        out[t] = wins.get(t, 0.0) + fav + ratings.get(t, sport.mean) * 1e-6
    return out


def _seeds_from_score(sport, score):
    """Apply seeding rules to a deterministic score map -> {team: seed or 0}."""
    final = {t: 0 for t in sport.teams}
    for conf in sport.conferences:
        conf_divs = [d for d in sport.divisions if d.split()[0] == conf]
        dw = [max(sport.divisions[d], key=lambda t: score[t]) for d in conf_divs]
        dwset = set(dw)
        for r, t in enumerate(sorted(dw, key=lambda t: -score[t])):
            final[t] = r + 1
        pool = sorted([t for d in conf_divs for t in sport.divisions[d]
                       if t not in dwset], key=lambda t: -score[t])
        for w in range(sport.wildcard_seeds):
            final[pool[w]] = sport.division_winner_seeds + w + 1
    return final


def seed_bounds(sport, ratings, base_wins, open_games, team, forced):
    """Best (lowest) and worst (highest, miss = seeds_per_conf+1) seed `team`
    can reach over the remaining games, given any user-`forced` results."""
    miss = sport.seeds_per_conf + 1

    def strength(t):
        return (base_wins.get(t, 0.0), ratings.get(t, sport.mean))

    # Favorable scenario: team wins its open games; in every other open game the
    # weaker side wins (suppresses would-be rivals).
    wb = dict(base_wins)
    for gid, h, a in open_games:
        f = forced.get(gid)
        if f == "home": w = h
        elif f == "away": w = a
        elif team in (h, a): w = team
        else: w = h if strength(h) <= strength(a) else a
        wb[w] = wb.get(w, 0.0) + 1
    sb = _seeds_from_score(sport, _score_from_wins(sport, ratings, wb,
                                                   favor=team, favor_high=True))
    best = sb[team] if sb[team] >= 1 else miss

    # Unfavorable scenario: team loses its open games; the stronger side wins
    # elsewhere (piles up rivals above the team).
    ww = dict(base_wins)
    for gid, h, a in open_games:
        f = forced.get(gid)
        if f == "home": w = h
        elif f == "away": w = a
        elif team == h: w = a
        elif team == a: w = h
        else: w = h if strength(h) >= strength(a) else a
        ww[w] = ww.get(w, 0.0) + 1
    sw = _seeds_from_score(sport, _score_from_wins(sport, ratings, ww,
                                                   favor=team, favor_high=False))
    worst = sw[team] if sw[team] >= 1 else miss
    return best, worst


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
    """Flat per-game list for the in-browser simulator.

    Each game carries its home-win probability so the client can re-simulate
    the season under user-forced outcomes without re-deriving Elo.
    """
    out = []
    gid = 0
    for wk in sorted(weekly_schedule):
        for home, away, hs, as_, neutral in weekly_schedule[wk]:
            h, a = sport.canon(home), sport.canon(away)
            if h not in sport.team_conf or a not in sport.team_conf:
                continue
            H = 0.0 if neutral else sport.home_field
            p = elo_expected(ratings.get(h, sport.mean),
                             ratings.get(a, sport.mean), H)
            played = hs is not None and as_ is not None
            winner = None
            if played:
                winner = "home" if hs > as_ else ("away" if hs < as_ else "tie")
            out.append({
                "id": gid, "week": wk, "home": h, "away": a,
                "neutral": neutral, "played": played, "winner": winner,
                "p_home": round(p, 4),
            })
            gid += 1
    return out


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

    print(f"[{sport.name}] simulating regular season ({sims} sims) ...")
    season_res = simulate_season(sport, ratings, weekly, sims=sims)

    print(f"[{sport.name}] simulating playoff brackets ...")
    bracket = simulate_bracket(sport, ratings, season_res)

    games = upcoming_games(sport, ratings, weekly)
    schedule = build_schedule(sport, ratings, weekly)

    data = assemble_payload(sport, season, start_year, ratings, last_completed,
                            season_res, bracket, games, schedule)
    return sport, data


def assemble_payload(sport, season, start_year, ratings, last_completed,
                     season_res, bracket, games, schedule):
    sims = season_res["sims"]
    teams = sport.teams
    miss_seed = sport.seeds_per_conf + 1

    # Base wins from already-played games and the list of still-open games, used
    # for the deterministic clinch/elimination scenarios.
    base_wins = {t: 0.0 for t in teams}
    open_games = []
    for g in schedule:
        if g["played"]:
            if g["winner"] == "home": base_wins[g["home"]] += 1
            elif g["winner"] == "away": base_wins[g["away"]] += 1
            elif g["winner"] == "tie":
                base_wins[g["home"]] += 0.5; base_wins[g["away"]] += 0.5
        else:
            open_games.append((g["id"], g["home"], g["away"]))

    idx = season_res["idx"]
    final_seed = season_res["final_seed"]

    rows = []
    for t in teams:
        sc = season_res["seed_counts"][t]
        seed_probs = [round(100 * sc[i] / sims, 1) for i in range(sport.seeds_per_conf)]
        miss = round(100 * sc[sport.seeds_per_conf] / sims, 1)

        # Achievable seeds = those hit in any MC trial, unioned with the
        # contiguous best..worst range from the contrived scenarios.
        fs = final_seed[:, idx[t]]
        mc_hit = {int(x) if x >= 1 else miss_seed for x in np.unique(fs)}
        best, worst = seed_bounds(sport, ratings, base_wins, open_games, t, {})
        ach = sorted(set(range(best, worst + 1)) | mc_hit)

        rows.append({
            "team": t,
            "conf": sport.team_conf[t],
            "div": sport.team_division[t],
            "elo": round(ratings.get(t, sport.mean)),
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
        "rows": rows,
        "upcoming": games,
        "schedule": schedule,
    }


def main():
    ap = argparse.ArgumentParser(description="playoffstatus-style odds via Elo Monte Carlo")
    ap.add_argument("--sport", default="nfl", choices=list(SPORTS))
    ap.add_argument("--season", type=int, default=2026, help="upcoming season year")
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
