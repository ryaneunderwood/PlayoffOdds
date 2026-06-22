#!/usr/bin/env python3
"""NFL tiebreakers and conference seeding.

Given the outcome of every regular-season game (which team won each game), this
module determines the playoff seeding for a conference using the real NFL
tiebreaking procedure:

  Division ties:   head-to-head, division record, common games, conference
                   record, strength of victory, strength of schedule.
  Wild-card ties:  reduce to one club per division first, then head-to-head
                   sweep, conference record, common games (min 4), strength of
                   victory, strength of schedule.

Steps that need point totals (rankings in points for/against, net points) and
the final coin toss are replaced by a deterministic-per-call random draw, since
the simulator models wins/losses only. Those steps are reached vanishingly
rarely, so the approximation is immaterial to the probabilities.

The engine is built once from the static schedule (`build_league`) and then
evaluated per simulated season from a `winners` array (`compute_records` +
`seed_conference`), which keeps the per-simulation work cheap.
"""

from __future__ import annotations

from typing import Dict, List

import numpy as np


class League:
    """Static, schedule-derived structure shared across all simulations."""

    def __init__(self, teams, team_conf, team_div, reg_games):
        # reg_games: list of (home_idx, away_idx) over the full regular season.
        self.teams = teams
        self.n = len(teams)
        self.team_conf = team_conf          # idx -> conf label
        self.team_div = team_div            # idx -> division label
        self.confs = sorted({team_conf[i] for i in range(self.n)})
        self.conf_idx = {c: [i for i in range(self.n) if team_conf[i] == c]
                         for c in self.confs}
        self.div_teams = {}
        for i in range(self.n):
            self.div_teams.setdefault(team_div[i], []).append(i)

        self.games = reg_games
        self.home = np.array([g[0] for g in reg_games], dtype=np.int32)
        self.away = np.array([g[1] for g in reg_games], dtype=np.int32)
        self.is_div = np.array([team_div[h] == team_div[a]
                                for h, a in reg_games], dtype=bool)
        self.is_conf = np.array([team_conf[h] == team_conf[a]
                                 for h, a in reg_games], dtype=bool)

        # Per-team lookups.
        self.team_games = [[] for _ in range(self.n)]   # (game_idx, opp_idx)
        self.div_games = [[] for _ in range(self.n)]    # game indices
        self.conf_games = [[] for _ in range(self.n)]
        self.opp_set = [set() for _ in range(self.n)]
        self.total_games = [0] * self.n
        self.pair_games = {}                            # (a,b)->[game idx], a<b
        for gi, (h, a) in enumerate(reg_games):
            self.team_games[h].append((gi, a))
            self.team_games[a].append((gi, h))
            self.opp_set[h].add(a); self.opp_set[a].add(h)
            self.total_games[h] += 1; self.total_games[a] += 1
            if self.is_div[gi]:
                self.div_games[h].append(gi); self.div_games[a].append(gi)
            if self.is_conf[gi]:
                self.conf_games[h].append(gi); self.conf_games[a].append(gi)
            key = (h, a) if h < a else (a, h)
            self.pair_games.setdefault(key, []).append(gi)

    def pair(self, a, b):
        return self.pair_games.get((a, b) if a < b else (b, a), ())


def compute_records(L: League, winners):
    """From a winners array (team idx per game) -> (W, dW, cW) totals."""
    W = np.zeros(L.n); dW = np.zeros(L.n); cW = np.zeros(L.n)
    for gi in range(len(winners)):
        w = winners[gi]
        W[w] += 1
        if L.is_div[gi]:
            dW[w] += 1
        if L.is_conf[gi]:
            cW[w] += 1
    return W, dW, cW


# ---------------------------------------------------------------------------
# Tiebreaker criteria (each returns a value to MAXIMIZE; None = not applicable)
# ---------------------------------------------------------------------------
def _h2h_best(L, winners, t, group):
    """Win pct vs the other group members (division-tie style)."""
    w = g = 0
    for opp in group:
        if opp == t:
            continue
        for gi in L.pair(t, opp):
            g += 1
            if winners[gi] == t:
                w += 1
    return (w / g) if g else None


def _h2h_sweep(L, winners, t, group):
    """Sweep rule (wild-card style): 1.0 if t beat every other member it
    played and played them all; 0.0 if it lost every such game; else None."""
    total = wins = 0
    for opp in group:
        if opp == t:
            continue
        played = L.pair(t, opp)
        if not played:
            return None  # sweep only applies if it played all others
        for gi in played:
            total += 1
            if winners[gi] == t:
                wins += 1
    if total == 0:
        return None
    if wins == total:
        return 1.0
    if wins == 0:
        return 0.0
    return None


def _div_pct(L, winners, dW, t):
    g = len(L.div_games[t])
    return (dW[t] / g) if g else 0.0


def _conf_pct(L, winners, cW, t):
    g = len(L.conf_games[t])
    return (cW[t] / g) if g else 0.0


def _common_pct(L, winners, group, t, min_games):
    common = set.intersection(*[L.opp_set[x] for x in group])
    if not common:
        return None
    w = g = 0
    for gi, opp in L.team_games[t]:
        if opp in common:
            g += 1
            if winners[gi] == t:
                w += 1
    if g < min_games or g == 0:
        return None
    return w / g


def _sov(L, winners, W, t):
    tw = tg = 0
    for gi, opp in L.team_games[t]:
        if winners[gi] == t:
            tw += W[opp]; tg += L.total_games[opp]
    return (tw / tg) if tg else 0.0


def _sos(L, winners, W, t):
    tw = tg = 0
    for gi, opp in L.team_games[t]:
        tw += W[opp]; tg += L.total_games[opp]
    return (tw / tg) if tg else 0.0


def _filter_max(group, valfn):
    """Keep group members tied for the max non-None value. If every value is
    None the criterion does not apply and the group is unchanged."""
    vals = {t: valfn(t) for t in group}
    present = [v for v in vals.values() if v is not None]
    if not present:
        return group
    mx = max(present)
    keep = [t for t in group if vals[t] is not None and vals[t] == mx]
    return keep if keep else group


def _pick_top_division(L, winners, dW, cW, W, group, rng):
    """Select the single top team from a same-record division tie group."""
    cur = list(group)
    ladder = [
        lambda t: _h2h_best(L, winners, t, cur),
        lambda t: _div_pct(L, winners, dW, t),
        lambda t: _common_pct(L, winners, cur, t, 0),
        lambda t: _conf_pct(L, winners, cW, t),
        lambda t: _sov(L, winners, W, t),
        lambda t: _sos(L, winners, W, t),
    ]
    for crit in ladder:
        cur = _filter_max(cur, crit)
        if len(cur) == 1:
            return cur[0]
    return cur[rng.integers(len(cur))]


def _pick_top_wildcard(L, winners, dW, cW, W, group, rng):
    """Select the single top team from a same-record wild-card tie group,
    reducing multiple same-division clubs to their best first."""
    cur = list(group)
    if len(cur) > 2:
        by_div: Dict[str, List[int]] = {}
        for t in cur:
            by_div.setdefault(L.team_div[t], []).append(t)
        reduced = []
        for d, members in by_div.items():
            if len(members) == 1:
                reduced.append(members[0])
            else:
                reduced.append(_pick_top_division(L, winners, dW, cW, W, members, rng))
        cur = reduced
        if len(cur) == 1:
            return cur[0]

    ladder = [
        lambda t: _h2h_sweep(L, winners, t, cur) if len(cur) > 2
                  else _h2h_best(L, winners, t, cur),
        lambda t: _conf_pct(L, winners, cW, t),
        lambda t: _common_pct(L, winners, cur, t, 4),
        lambda t: _sov(L, winners, W, t),
        lambda t: _sos(L, winners, W, t),
    ]
    for crit in ladder:
        cur = _filter_max(cur, crit)
        if len(cur) == 1:
            return cur[0]
    return cur[rng.integers(len(cur))]


def _order_by_record(L, W, teams, pick_top, rng):
    """Full ordering of `teams`: by wins, ties broken by pick_top repeatedly."""
    remaining = list(teams)
    out = []
    while remaining:
        best = max(W[t] for t in remaining)
        tied = [t for t in remaining if W[t] == best]
        if len(tied) == 1:
            out.append(tied[0]); remaining.remove(tied[0]); continue
        winner = pick_top(tied)
        out.append(winner); remaining.remove(winner)
    return out


def seed_conference(L: League, conf, winners, W, dW, cW, rng):
    """Return {team_idx: seed 1..7} for one conference (others omitted)."""
    def pdiv(group):
        return _pick_top_division(L, winners, dW, cW, W, group, rng)

    def pwc(group):
        return _pick_top_wildcard(L, winners, dW, cW, W, group, rng)

    # 1. Division winners.
    div_winners = []
    for d in [dd for dd in L.div_teams if dd.split()[0] == conf]:
        members = L.div_teams[d]
        best = max(W[t] for t in members)
        tied = [t for t in members if W[t] == best]
        div_winners.append(tied[0] if len(tied) == 1 else pdiv(tied))

    # 2. Seeds 1-4: rank the division winners (cross-division -> wild-card order).
    ranked = _order_by_record(L, W, div_winners, pwc, rng)
    seeds = {t: i + 1 for i, t in enumerate(ranked)}

    # 3. Seeds 5-7: best non-division-winners.
    dwset = set(div_winners)
    nonwin = [t for t in L.conf_idx[conf] if t not in dwset]
    wc_ranked = _order_by_record(L, W, nonwin, pwc, rng)
    for i in range(3):
        seeds[wc_ranked[i]] = 5 + i
    return seeds


# ---------------------------------------------------------------------------
# Mathematical feasibility (clinch / elimination) with real tiebreakers
# ---------------------------------------------------------------------------
# Seeds are encoded 1..7; MISS = 8 means "missed the playoffs". A team's
# achievable-seed set determines the X / ^ markers. We compute the best and
# worst seed the team can reach by:
#   * pruning to the teams that can actually affect the cut (within 2 wins of
#     the 7-seed line, plus the team's own division rivals);
#   * fixing all other remaining games to the most/least favorable result;
#   * EXHAUSTIVELY searching the remaining games *between two contenders* (the
#     coupled games -- beating the #7 seed necessarily lifts whoever beats it);
#   * applying the real NFL tiebreakers to seed each resulting season.
# When too many coupled games remain to enumerate (early season, nothing is
# decided anyway) we report the team as fully live -- never a false X/^.
MISS = 8
SEARCH_CAP = 14  # max coupled games to enumerate (2**14 = 16384 seasons)


def _seed_of(L, conf, winners, W, dW, cW, ti, rng):
    seeds = seed_conference(L, conf, winners, W, dW, cW, rng)
    return seeds.get(ti, MISS)


def _records_skipping(L, winners, skip):
    W = np.zeros(L.n); dW = np.zeros(L.n); cW = np.zeros(L.n)
    for gi in range(len(winners)):
        if gi in skip:
            continue
        w = winners[gi]
        W[w] += 1
        if L.is_div[gi]:
            dW[w] += 1
        if L.is_conf[gi]:
            cW[w] += 1
    return W, dW, cW


def _search_extreme(L, base, ti, conf, open_idx, contenders, team_wins_out,
                    want_min, rng):
    """Best (want_min) or worst seed `ti` can reach. `base` has -1 for open
    games; open games are fixed favorably/unfavorably except games between two
    contenders, which are enumerated exhaustively."""
    cset = set(contenders)
    winners = base.copy()
    mutual = []
    for gi in open_idx:
        h, a = L.home[gi], L.away[gi]
        if h == ti or a == ti:
            winners[gi] = ti if team_wins_out else (a if h == ti else h)
        elif h in cset and a in cset:
            mutual.append(gi)            # coupled -> search
        else:
            # one contender vs a non-contender (or two non-contenders).
            c_side = h if h in cset else (a if a in cset else None)
            o_side = a if c_side == h else h
            if c_side is None:
                winners[gi] = h          # irrelevant
            else:
                # best case for ti suppresses the contender; worst case lifts it
                winners[gi] = o_side if want_min else c_side

    m = len(mutual)
    if m > SEARCH_CAP:
        return None  # too many coupled games -> caller treats as live

    W0, dW0, cW0 = _records_skipping(L, winners, set(mutual))
    mg = [(gi, int(L.home[gi]), int(L.away[gi]),
           bool(L.is_div[gi]), bool(L.is_conf[gi])) for gi in mutual]

    extreme = None
    for bits in range(1 << m):
        W = W0.copy(); dW = dW0.copy(); cW = cW0.copy()
        for k, (gi, h, a, isd, isc) in enumerate(mg):
            w = h if (bits >> k) & 1 else a
            winners[gi] = w
            W[w] += 1
            if isd: dW[w] += 1
            if isc: cW[w] += 1
        sd = _seed_of(L, conf, winners, W, dW, cW, ti, rng)
        if extreme is None or (sd < extreme if want_min else sd > extreme):
            extreme = sd
        if want_min and extreme == 1:
            break
        if not want_min and extreme == MISS:
            break
    return extreme


def achievable_seeds(L, base_winners, ti, rng, mc_seeds=frozenset()):
    """Return the sorted set of seeds (1..7, 8=miss) team `ti` can still reach,
    unioned with the seeds it reached in the Monte Carlo (mc_seeds)."""
    conf = L.team_conf[ti]
    confteams = L.conf_idx[conf]
    open_idx = [gi for gi in range(len(base_winners)) if base_winners[gi] < 0]

    # current wins (decided games only) and remaining games per conf team
    cw = {t: 0 for t in confteams}
    for gi in range(len(base_winners)):
        w = base_winners[gi]
        if w >= 0 and w in cw:
            cw[w] += 1
    line = sorted((cw[t] for t in confteams), reverse=True)[6]  # 7th seed line
    my_div = L.team_div[ti]
    contenders = [t for t in confteams if t != ti and
                  (abs(cw[t] - line) <= 2 or L.team_div[t] == my_div)]

    best = _search_extreme(L, base_winners, ti, conf, open_idx, contenders,
                           team_wins_out=True, want_min=True, rng=rng)
    worst = _search_extreme(L, base_winners, ti, conf, open_idx, contenders,
                            team_wins_out=False, want_min=False, rng=rng)
    if best is None or worst is None:        # too coupled to enumerate -> live
        ach = set(range(1, MISS + 1))
    else:
        ach = set(range(best, worst + 1))
    return sorted(ach | set(mc_seeds))
