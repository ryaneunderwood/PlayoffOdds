#!/usr/bin/env python3
"""NHL support: schedule loader, standings/seeding rules, bracket, feasibility.

Everything here mirrors the NFL pieces in sports_elo.py / seeding.py, adapted
to hockey:

* **Data** comes from the NHL stats API (one request per season, covering the
  regular season and playoffs). Each played game records how it ended --
  regulation, overtime or shootout -- because that decides the standings.
* **Points.** A win is worth 2, an overtime/shootout loss 1, a regulation loss
  0. Open games are simulated from the Elo win probability, and a fixed share
  of them go past regulation (`OT_RATE`, `SO_SHARE`, measured from recent
  seasons), which hands the loser a point.
* **Seeding** per conference: the top three in each division (seeds "Div 1"
  .. "Div 3"), then the two best remaining teams as wild cards ("WC1",
  "WC2"). Ties are broken by the real NHL order -- regulation wins,
  regulation + overtime wins, total wins, points in head-to-head games -- and
  then by a random draw standing in for goal differential (the model does not
  simulate goals).
* **Bracket.** The division winner with the better record plays WC2, the
  other plays WC1; 2 v 3 within each division; the bracket is fixed (no
  reseeding). Every round is a best-of-seven with 2-2-1-1-1 home ice to the
  team with the better regular-season record.
* **Clinch / elimination** use exact points bounds (current points to current
  points + 2 per remaining game), so an X or ^ is only ever shown when it is
  mathematically certain. Ties at the bound are treated as going against the
  team, which keeps the test sound at the cost of flagging some clinches a
  game or two late.
"""

from __future__ import annotations

import json
import time
import urllib.request
from typing import Dict

import numpy as np

# ----------------------------------------------------------------------------
# League structure
# ----------------------------------------------------------------------------
# Division labels start with the conference token, which is how the generic
# engine derives each team's conference.
NHL_DIVISIONS = {
    "East Atlantic":     ["BOS", "BUF", "DET", "FLA", "MTL", "OTT", "TBL", "TOR"],
    "East Metropolitan": ["CAR", "CBJ", "NJD", "NYI", "NYR", "PHI", "PIT", "WSH"],
    "West Central":      ["CHI", "COL", "DAL", "MIN", "NSH", "STL", "UTA", "WPG"],
    "West Pacific":      ["ANA", "CGY", "EDM", "LAK", "SEA", "SJS", "VAN", "VGK"],
}

# Relocations that kept the roster: Elo carries across the move.
NHL_ALIASES = {
    "ARI": "UTA",   # Arizona Coyotes -> Utah (2024; the hockey operations moved)
    "PHX": "UTA",   # Phoenix Coyotes code
    "ATL": "WPG",   # Atlanta Thrashers -> Winnipeg Jets (2011)
}

SEED_LABELS = ["Div 1", "Div 2", "Div 3", "WC1", "WC2"]
NSEED = len(SEED_LABELS)
MISS = NSEED + 1

# Share of regular-season games decided past regulation, and the share of those
# that reach a shootout (2022-23 .. 2024-25: 21.6% to OT, 28% of those to a
# shootout). Only used to hand out the loser's point in simulated games.
OT_RATE = 0.22
SO_SHARE = 0.28

# ----------------------------------------------------------------------------
# Data loader (NHL stats API)
# ----------------------------------------------------------------------------
STATS_API = "https://api.nhle.com/stats/rest/en"
_TEAM_CODES = None
_SEASON_CACHE: Dict[int, list] = {}


def _get_json(url, tries=4):
    req = urllib.request.Request(url, headers={"User-Agent": "PlayoffOdds/1.0"})
    for i in range(tries):
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.load(r)
        except Exception:
            if i == tries - 1:
                raise
            time.sleep(2 * (i + 1))


def _team_codes():
    """NHL team id -> tri-code (e.g. 10 -> TOR)."""
    global _TEAM_CODES
    if _TEAM_CODES is None:
        _TEAM_CODES = {t["id"]: t["triCode"] for t in _get_json(f"{STATS_API}/team")["data"]}
    return _TEAM_CODES


def nhl_games(season: int):
    """Every regular-season and playoff game of the season that starts in
    `season` (2026 -> 2026-27), fetched once per process."""
    if season not in _SEASON_CACHE:
        sid = f"{season}{season + 1}"
        url = (f"{STATS_API}/game?cayenneExp=season={sid}"
               "%20and%20gameType%3E=2%20and%20gameType%3C=3")
        _SEASON_CACHE[season] = _get_json(url)["data"]
    return _SEASON_CACHE[season]


def _decision(g):
    """How a finished game ended: REG, OT or SO (None if not final)."""
    if g.get("gameStateId") not in (6, 7):
        return None
    per = g.get("period") or 3
    if per <= 3:
        return "REG"
    if g.get("gameType") == 2 and per >= 5:
        return "SO"          # regular-season period 5 is the shootout
    return "OT"              # playoff period 5+ is just more overtime


def load_nhl_schedule(season: int, include_playoffs: bool = True):
    """Return {yyyymmdd: [(home, away, home_score|None, away_score|None,
    neutral, decision)]}. Keys are calendar dates so Elo is walked forward a
    day at a time. Scores are None for games not yet final."""
    codes = _team_codes()
    out: Dict[int, list] = {}
    for g in nhl_games(season):
        if g["gameType"] == 3 and not include_playoffs:
            continue
        dec = _decision(g)
        if g["gameType"] == 3 and dec is None:
            continue          # unplayed "if necessary" playoff slots
        home = codes.get(g["homeTeamId"])
        away = codes.get(g["visitingTeamId"])
        if not home or not away:
            continue
        key = int(g["gameDate"].replace("-", ""))
        hs = float(g["homeScore"]) if dec else None
        as_ = float(g["visitingScore"]) if dec else None
        out.setdefault(key, []).append((home, away, hs, as_, False, dec))
    return out


def load_nhl_meta(season: int):
    """Puck-drop time (Eastern) per (date, home, away), for the games view."""
    codes = _team_codes()
    meta = {}
    for g in nhl_games(season):
        if g["gameType"] != 2:
            continue
        h = NHL_ALIASES.get(codes.get(g["homeTeamId"]), codes.get(g["homeTeamId"]))
        a = NHL_ALIASES.get(codes.get(g["visitingTeamId"]), codes.get(g["visitingTeamId"]))
        st = g.get("easternStartTime") or ""
        meta[(int(g["gameDate"].replace("-", "")), h, a)] = {
            "gametime": st[11:16] if len(st) >= 16 else None,
        }
    return meta


def current_season() -> int:
    """NHL seasons are labelled by the year they start; the schedule for the
    next one is out by July, and the previous one is over by June."""
    from datetime import date
    today = date.today()
    return today.year if today.month >= 7 else today.year - 1


# ----------------------------------------------------------------------------
# Static league structure for the simulator
# ----------------------------------------------------------------------------
class NHLLeague:
    def __init__(self, sport, schedule):
        self.teams = sport.teams
        self.n = len(self.teams)
        self.idx = {t: i for i, t in enumerate(self.teams)}
        self.confs = sport.conferences
        self.team_conf = [sport.team_conf[t] for t in self.teams]
        self.team_div = [sport.team_division[t] for t in self.teams]
        self.conf_idx = {c: [i for i in range(self.n) if self.team_conf[i] == c]
                         for c in self.confs}
        self.conf_divs = {c: [d for d in sport.divisions if d.split()[0] == c]
                          for c in self.confs}
        self.div_idx = {d: [self.idx[t] for t in ts] for d, ts in sport.divisions.items()}

        self.home = np.array([self.idx[g["home"]] for g in schedule], dtype=np.int64)
        self.away = np.array([self.idx[g["away"]] for g in schedule], dtype=np.int64)
        self.p_home = np.array([g["p_home"] for g in schedule])
        # fixed winner idx (-1 open) and decision code (0 REG, 1 OT, 2 SO)
        self.fixed = np.full(len(schedule), -1, dtype=np.int64)
        self.fixed_dec = np.zeros(len(schedule), dtype=np.int64)
        for gi, g in enumerate(schedule):
            if g["played"] and g["winner"] in ("home", "away"):
                self.fixed[gi] = self.home[gi] if g["winner"] == "home" else self.away[gi]
                self.fixed_dec[gi] = {"REG": 0, "OT": 1, "SO": 2}.get(g.get("dec"), 0)
        self.pair_games = {}
        for gi in range(len(schedule)):
            h, a = int(self.home[gi]), int(self.away[gi])
            self.pair_games.setdefault((min(h, a), max(h, a)), []).append(gi)

    def pair(self, a, b):
        return self.pair_games.get((min(a, b), max(a, b)), ())


def standings_key(P, RW, ROW, W):
    """One sortable integer per team: points, then regulation wins, then
    regulation + OT wins, then total wins (the NHL tiebreak order)."""
    return ((P * 200 + RW) * 200 + ROW) * 200 + W


def _h2h_pct(L, winners, dec, group, t):
    """Share of the available points `t` took in games among `group`."""
    got = avail = 0
    for o in group:
        if o == t:
            continue
        for gi in L.pair(t, o):
            avail += 2
            if winners[gi] == t:
                got += 2
            elif dec[gi] > 0:
                got += 1          # OT / SO loss point
    return got / avail if avail else 0.5


def order_conference(L, conf, key, winners, dec, rng):
    """Conference teams best-first: by standings key, then head-to-head points
    among teams still tied, then a random draw (goal differential)."""
    teams = sorted(L.conf_idx[conf], key=lambda t: -key[t])
    out, i = [], 0
    while i < len(teams):
        j = i
        while j + 1 < len(teams) and key[teams[j + 1]] == key[teams[i]]:
            j += 1
        grp = teams[i:j + 1]
        if len(grp) > 1:
            h2h = {t: _h2h_pct(L, winners, dec, grp, t) for t in grp}
            rnd = {t: rng.random() for t in grp}
            grp = sorted(grp, key=lambda t: (-h2h[t], rnd[t]))
        out.extend(grp)
        i = j + 1
    return out


def seed_conference(L, conf, key, winners, dec, rng):
    """{team_idx: seed} with seeds 1..3 = place in division, 4/5 = WC1/WC2.
    Also returns the conference order (for home ice in the bracket)."""
    order = order_conference(L, conf, key, winners, dec, rng)
    seeds, rank = {}, {t: r for r, t in enumerate(order)}
    for d in L.conf_divs[conf]:
        for place, t in enumerate(sorted(L.div_idx[d], key=lambda t: rank[t])[:3]):
            seeds[t] = place + 1
    wc = [t for t in order if t not in seeds][:2]
    for k, t in enumerate(wc):
        seeds[t] = 4 + k
    return seeds, rank


# ----------------------------------------------------------------------------
# Regular-season Monte Carlo
# ----------------------------------------------------------------------------
def _tally(sims, n, rows, idx_mat, mask=None):
    """Per-sim counts of `idx_mat` team indices (optionally masked)."""
    flat = (rows * n + idx_mat)
    if mask is not None:
        flat = flat[mask]
    return np.bincount(flat.ravel(), minlength=sims * n).reshape(sims, n)


def simulate_season(sport, ratings, schedule, sims, rng):
    L = NHLLeague(sport, schedule)
    n, ng = L.n, len(schedule)
    open_mask = L.fixed < 0
    no = int(open_mask.sum())

    winners = np.empty((sims, ng), dtype=np.int64)
    dec = np.empty((sims, ng), dtype=np.int64)
    winners[:, ~open_mask] = L.fixed[~open_mask]
    dec[:, ~open_mask] = L.fixed_dec[~open_mask]
    if no:
        u = rng.random((sims, no))
        winners[:, open_mask] = np.where(u < L.p_home[open_mask],
                                         L.home[open_mask], L.away[open_mask])
        v = rng.random((sims, no))
        dec[:, open_mask] = np.where(v < OT_RATE * (1 - SO_SHARE), 1,
                                     np.where(v < OT_RATE, 2, 0))
    losers = np.where(winners == L.home, L.away, L.home)

    rows = np.arange(sims)[:, None]
    W = _tally(sims, n, rows, winners)
    RW = _tally(sims, n, rows, winners, dec == 0)
    ROW = _tally(sims, n, rows, winners, dec < 2)
    OTL = _tally(sims, n, rows, losers, dec > 0)
    P = 2 * W + OTL
    KEY = standings_key(P, RW, ROW, W)

    final_seed = np.zeros((sims, n), dtype=np.int64)
    conf_rank = np.zeros((sims, n), dtype=np.int64)
    for s in range(sims):
        for c in L.confs:
            seeds, rank = seed_conference(L, c, KEY[s], winners[s], dec[s], rng)
            for t, sd in seeds.items():
                final_seed[s, t] = sd
            for t, r in rank.items():
                conf_rank[s, t] = r

    seed_counts, div_winner, make_playoffs = {}, {}, {}
    for t in sport.teams:
        fs = final_seed[:, L.idx[t]]
        sc = np.zeros(NSEED + 1)
        for sd in range(1, NSEED + 1):
            sc[sd - 1] = np.sum(fs == sd)
        sc[NSEED] = np.sum(fs == 0)
        seed_counts[t] = sc
        make_playoffs[t] = int(np.sum(fs > 0))
        div_winner[t] = int(np.sum(fs == 1))

    return {
        "sims": sims, "idx": L.idx, "league": L,
        "final_seed": final_seed, "conf_rank": conf_rank, "key": KEY,
        "seed_counts": seed_counts, "div_winner": div_winner,
        "make_playoffs": make_playoffs,
        "win_dist": {t: W[:, L.idx[t]] for t in sport.teams},
        "pts_dist": {t: P[:, L.idx[t]] for t in sport.teams},
    }


# ----------------------------------------------------------------------------
# Playoff bracket (best-of-seven series)
# ----------------------------------------------------------------------------
def series_prob(p_home_game, p_away_game):
    """P(the team with home ice wins a best-of-7), 2-2-1-1-1 format, given
    its single-game win probability at home and on the road."""
    home_games = (True, True, False, False, True, False, True)
    # dist[w] over (wins of A, wins of B) states; stop at 4.
    states = {(0, 0): 1.0}
    win = 0.0
    for g in range(7):
        p = p_home_game if home_games[g] else p_away_game
        nxt = {}
        for (a, b), pr in states.items():
            for (da, db, q) in ((1, 0, p), (0, 1, 1 - p)):
                na, nb = a + da, b + db
                if na == 4:
                    win += pr * q
                elif nb < 4:
                    nxt[(na, nb)] = nxt.get((na, nb), 0.0) + pr * q
        states = nxt
    return win


def simulate_bracket(sport, ratings, season_res, rng, elo_expected):
    L = season_res["league"]
    final_seed, conf_rank, KEY = (season_res["final_seed"], season_res["conf_rank"],
                                  season_res["key"])
    sims = season_res["sims"]
    teams = sport.teams
    R = [ratings.get(t, sport.mean) for t in teams]
    H = sport.home_field
    memo = {}

    def series(a, b, key_row):
        """Winner of a series between team idx a and b; home ice to the
        better regular-season record."""
        hi, lo = (a, b) if key_row[a] > key_row[b] or (
            key_row[a] == key_row[b] and a < b) else (b, a)
        k = (hi, lo)
        if k not in memo:
            memo[k] = series_prob(elo_expected(R[hi], R[lo], H),
                                  elo_expected(R[hi], R[lo], -H))
        return hi if rng.random() < memo[k] else lo

    conf_champ = np.zeros(L.n, dtype=np.int64)
    title = np.zeros(L.n, dtype=np.int64)
    for s in range(sims):
        fs, kr, cr = final_seed[s], KEY[s], conf_rank[s]
        champs = []
        for c in L.confs:
            divs = L.conf_divs[c]
            by_div = {d: {int(fs[t]): t for t in L.div_idx[d] if 1 <= fs[t] <= 3}
                      for d in divs}
            wc1 = next(t for t in L.conf_idx[c] if fs[t] == 4)
            wc2 = next(t for t in L.conf_idx[c] if fs[t] == 5)
            # the better division winner draws WC2
            d_top = min(divs, key=lambda d: cr[by_div[d][1]])
            side = []
            for d in divs:
                wc = wc2 if d == d_top else wc1
                w1 = series(by_div[d][1], wc, kr)
                w2 = series(by_div[d][2], by_div[d][3], kr)
                side.append(series(w1, w2, kr))
            cw = series(side[0], side[1], kr)
            conf_champ[cw] += 1
            champs.append(cw)
        title[series(champs[0], champs[1], kr)] += 1

    return {"conf_champ": {t: int(conf_champ[i]) for i, t in enumerate(teams)},
            "title": {t: int(title[i]) for i, t in enumerate(teams)}}


# ----------------------------------------------------------------------------
# Clinch / elimination from exact points bounds
# ----------------------------------------------------------------------------
def achievable_seeds(L, bounds, ti, mc_seeds=frozenset()):
    """Seeds (1..5, 6 = miss) team `ti` can still reach. `bounds` is
    (lo, hi, key, done) from `points_bounds`: every team's guaranteed and
    best-possible final points, its standings key from the games played, and
    whether its schedule is finished. Only seeds that are provably impossible
    are dropped, so the result is never too small; the Monte Carlo hits are
    unioned in."""
    lo, hi, key, done = bounds
    conf = L.team_conf[ti]
    rivals = [t for t in L.div_idx[L.team_div[ti]] if t != ti]
    others = [t for t in L.conf_idx[conf] if L.team_div[t] != L.team_div[ti]]

    def settled(t):      # both finished level on points: the tiebreak key decides
        return done[t] and done[ti] and lo[t] == lo[ti] and key[t] != key[ti]

    def surely_ahead(t):
        return lo[t] > hi[ti] or (settled(t) and key[t] > key[ti])

    def maybe_ahead(t):
        return hi[t] >= lo[ti] and not (settled(t) and key[t] < key[ti])

    a = sum(map(surely_ahead, rivals)); b = sum(map(maybe_ahead, rivals))
    a2 = sum(map(surely_ahead, others)); b2 = sum(map(maybe_ahead, others))

    ach = set()
    for s in (1, 2, 3):                       # place in the division: a+1 .. b+1
        if a + 1 <= s <= b + 1:
            ach.add(s)
    if b >= 3:                                # could finish 4th+ in the division
        ahead_wc = max(0, a - 3) + max(0, a2 - 3)   # wild-card rivals surely ahead
        worst_wc = max(0, b - 3) + max(0, b2 - 3)   # wild-card rivals possibly ahead
        if ahead_wc == 0:
            ach.add(4)
        if ahead_wc <= 1 and worst_wc >= 1:
            ach.add(5)
        if worst_wc >= 2:
            ach.add(MISS)
    if not ach:
        ach = set(range(1, MISS + 1))
    return sorted(ach | set(mc_seeds))


def points_bounds(L, schedule):
    """(lo, hi, key, done) per team index from the games played so far: the
    points already banked, the most still reachable (2 per remaining game),
    the standings key of the banked results, and whether the team is done."""
    lo = np.zeros(L.n, dtype=np.int64)
    rem = np.zeros(L.n, dtype=np.int64)
    W = np.zeros(L.n, dtype=np.int64); RW = W.copy(); ROW = W.copy()
    for gi in range(len(schedule)):
        h, a = L.home[gi], L.away[gi]
        if L.fixed[gi] >= 0:
            w, d = L.fixed[gi], L.fixed_dec[gi]
            lo[w] += 2; W[w] += 1
            RW[w] += d == 0; ROW[w] += d < 2
            if d > 0:
                lo[a if w == h else h] += 1
        else:
            rem[h] += 1; rem[a] += 1
    return lo, lo + 2 * rem, standings_key(lo, RW, ROW, W), rem == 0
