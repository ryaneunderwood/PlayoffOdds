#!/usr/bin/env python3
"""NFL tiebreakers and conference seeding.

Given the outcome of every regular-season game, this module seeds a conference
with the real NFL tiebreaking procedure (two-club and three-or-more-club
division and wild-card formats, including the one-club-per-division reduction
and the restart to the two-club format), mirroring rules.js:

  Division ties:   head-to-head, division record, common games, conference
                   record, strength of victory, strength of schedule.
  Wild-card ties:  head-to-head (sweep for 3+), conference record, common
                   games (min 4), strength of victory, strength of schedule.

Steps that need point totals (rankings in points for/against, net points) and
the final coin toss are a random draw, since the simulator models results
only.

The exact clinch/elimination search lives in rules.js; this module keeps a
cheaper sound fallback (`bound_seeds`) for builds without Node.
"""

from __future__ import annotations

from typing import Dict, List

from itertools import combinations

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


# ---------------------------------------------------------------------------
# Standings and tiebreakers
# ---------------------------------------------------------------------------
# This mirrors the procedure in rules.js (which also does the exact
# clinch/elimination search) so simulated seeds follow the same rules.
# `winners[gi]` is the winning team index, or -1 for a tie (half a win each).
# Standings are by points = 2*wins + ties, which orders teams exactly like win
# percentage since every club plays the same number of games.
# Steps the model cannot evaluate (points scored/allowed, net points, coin
# toss) are a uniform random draw among the clubs still tied; where the rules
# leave a reading open (three or more clubs reduced to three or more), either
# reading may apply and one is chosen at random.

def compute_points(L: League, winners):
    """Standings points (2 per win, 1 per tie) from a winners array."""
    P = np.zeros(L.n)
    for gi in range(len(winners)):
        w = winners[gi]
        if w >= 0:
            P[w] += 2
        else:
            P[L.home[gi]] += 1; P[L.away[gi]] += 1
    return P


def _gp(winners, gi, t):
    w = winners[gi]
    return 2 if w == t else (1 if w < 0 else 0)


def _cmp(a, b):
    return a[0] * b[1] - b[0] * a[1]


class _Ctx:
    def __init__(self, L, winners, pts):
        self.L, self.w, self.pts = L, winners, pts


def _h2h(c, t, group):
    p = g = 0
    for o in group:
        if o != t:
            for gi in c.L.pair(t, o):
                g += 1; p += _gp(c.w, gi, t)
    return (p, 2 * g) if g else None


def _pct(c, t, games):
    return (sum(_gp(c.w, gi, t) for gi in games), 2 * len(games) or 1)


def _common(c, group, min_g):
    L = c.L
    inter = set.intersection(*[L.opp_set[x] for x in group])
    if not inter:
        return None
    vals = []
    for t in group:
        p = g = 0
        for gi, o in L.team_games[t]:
            if o in inter:
                g += 1; p += _gp(c.w, gi, t)
        if g < max(min_g, 1):
            return None
        vals.append((p, 2 * g))
    return vals


def _strength(c, t, won_only):
    L = c.L
    num = den = 0
    for gi, o in L.team_games[t]:
        if won_only and c.w[gi] != t:
            continue
        num += c.pts[o]; den += 2 * L.total_games[o]
    return (num, den) if den else (0, 1)


def _step_vals(c, step, group):
    if step == "h2h":
        v = [_h2h(c, t, group) for t in group]
        return None if any(x is None for x in v) else v
    if step == "div":
        return [_pct(c, t, c.L.div_games[t]) for t in group]
    if step == "conf":
        return [_pct(c, t, c.L.conf_games[t]) for t in group]
    if step == "common0":
        return _common(c, group, 0)
    if step == "common4":
        return _common(c, group, 4)
    if step == "sov":
        return [_strength(c, t, True) for t in group]
    if step == "sos":
        return [_strength(c, t, False) for t in group]
    return None


def _filter_max(group, vals):
    best = vals[0]
    for v in vals:
        if _cmp(v, best) > 0:
            best = v
    return [t for t, v in zip(group, vals) if _cmp(v, best) == 0]


def _sweep(c, cur):
    """One club beat each of the others -> it advances; one lost to each of
    the others -> it is eliminated. Every pair must have played."""
    L = c.L
    allw, alll = [], []
    for t in cur:
        aw = al = True
        for o in cur:
            if o == t:
                continue
            gs = L.pair(t, o)
            if not gs:
                aw = al = False
                break
            for gi in gs:
                p = _gp(c.w, gi, t)
                aw = aw and p == 2
                al = al and p == 0
        allw.append(aw); alll.append(al)
    w = [t for t, x in zip(cur, allw) if x]
    if len(w) == 1:
        return w
    keep = [t for t, x in zip(cur, alll) if not x]
    return keep or cur


def _ladder(c, cur, k, steps, two, again):
    """Set of clubs that may come out on top."""
    if len(cur) == 1:
        return set(cur)
    while k < len(steps):
        st = steps[k]
        if st == "sweep":
            new = _sweep(c, cur)
        else:
            vals = _step_vals(c, st, cur)
            if vals is None:
                k += 1
                continue
            new = _filter_max(cur, vals)
        if len(new) < len(cur):
            if len(new) == 1:
                return set(new)
            if len(new) == 2:
                return two(new)
            return _ladder(c, new, k + 1, steps, two, again) | again(new)
        k += 1
    return set(cur)


DIV_STEPS = ("h2h", "div", "common0", "conf", "sov", "sos")
WC2_STEPS = ("h2h", "conf", "common4", "sov", "sos")
WCM_STEPS = ("sweep", "conf", "common4", "sov", "sos")


def div_top(c, group, steps=DIV_STEPS):
    if len(group) == 1:
        return set(group)
    again = lambda g: _ladder(c, g, 0, steps, again, again)
    return again(list(group))


def _wc2(c, g):
    if c.L.team_div[g[0]] == c.L.team_div[g[1]]:
        return div_top(c, g)
    two = lambda x: _wc2(c, x)
    return _ladder(c, list(g), 0, WC2_STEPS, two, two)


def wc_top(c, group, div_rank):
    L = c.L
    if len(group) == 1:
        return set(group)
    if len({L.team_div[t] for t in group}) == 1:
        return div_top(c, group)
    if len(group) == 2:
        return _wc2(c, group)
    best = {}
    for t in group:
        d = L.team_div[t]
        if d not in best or div_rank[t] < div_rank[best[d]]:
            best[d] = t
    red = list(best.values())
    if len(red) == 2:
        return _wc2(c, red)
    two = lambda x: _wc2(c, x)
    again = lambda x: _ladder(c, x, 0, WCM_STEPS, two, again)
    return again(red)


def _order(c, teams, top_fn, rng):
    """Teams best-first by points; each tie resolved by repeatedly taking a
    (random) club from the set that may come out on top."""
    pts = c.pts
    out = []
    rest = sorted(teams, key=lambda t: -pts[t])
    i = 0
    while i < len(rest):
        j = i
        while j + 1 < len(rest) and pts[rest[j + 1]] == pts[rest[i]]:
            j += 1
        grp = rest[i:j + 1]
        while grp:
            if len(grp) == 1:
                out.append(grp[0]); break
            tops = sorted(top_fn(grp))
            t = tops[rng.integers(len(tops))]
            out.append(t); grp = [x for x in grp if x != t]
        i = j + 1
    return out


def seed_conference(L: League, conf, winners, pts, rng):
    """Return {team_idx: seed 1..7} for one conference (others omitted)."""
    c = _Ctx(L, winners, pts)
    div_rank, winners_ = {}, []
    for d in [dd for dd in L.div_teams if dd.split()[0] == conf]:
        order = _order(c, L.div_teams[d], lambda g: div_top(c, g), rng)
        for i, t in enumerate(order):
            div_rank[t] = i
        winners_.append(order[0])
    wc = lambda g: wc_top(c, g, div_rank)
    seeds = {t: i + 1 for i, t in enumerate(_order(c, winners_, wc, rng))}
    wset = set(winners_)
    pool = _order(c, [t for t in L.conf_idx[conf] if t not in wset], wc, rng)
    for i in range(3):
        seeds[pool[i]] = 5 + i
    return seeds


# ---------------------------------------------------------------------------
# Fallback elimination bounds (used only when Node is unavailable to run the
# exact search in rules.js; the page then refines them in the browser)
# ---------------------------------------------------------------------------
MISS = 8


# --- Sound elimination bounds (always run, even when the search is capped) --
# Everything below proves a seed IMPOSSIBLE; whenever it cannot (search budget
# spent, a tie that only SOV/SOS could break, ...) it leaves the seed live.
# In every bound the team wins out: that only adds to its own record and takes
# wins away from opponents, so it is the best case for every seed it can reach.
DIV_NODE_BUDGET = 200_000
WC_COMBO_BUDGET = 20_000


def _flow_feasible(caps, games):
    """Can every game in `games` (pairs of constrained teams) hand its win to
    one of its two teams without anyone exceeding caps[t]? Bipartite
    b-matching by augmenting paths; the graphs here are tiny."""
    if any(c < 0 for c in caps.values()):
        return False
    load = {t: [] for t in caps}            # team -> games assigned to it
    owner = [None] * len(games)

    def augment(g, seen):
        for t in games[g]:
            if t in seen:
                continue
            seen.add(t)
            if len(load[t]) < caps[t]:
                load[t].append(g); owner[g] = t
                return True
            for g2 in list(load[t]):
                if augment(g2, seen):
                    load[t].remove(g2); load[t].append(g); owner[g] = t
                    return True
        return False

    for g in range(len(games)):
        if not augment(g, set()):
            return False
    return True


def _hold_feasible(L, open_idx, ti, cur, mx, constrained):
    """Can every team in `constrained` finish with at most mx wins (ties with
    ti allowed -- optimistic) while ti wins out? Games against ti or against
    an unconstrained team are given to the other side for free."""
    caps = {t: mx - cur[t] for t in constrained}
    games = []
    for gi in open_idx:
        h, a = int(L.home[gi]), int(L.away[gi])
        if h == ti or a == ti:
            continue
        if h in caps and a in caps:
            games.append((h, a))
    return _flow_feasible(caps, games)


def _can_win_division(L, base_winners, open_idx, ti, cur, mx):
    """Exhaustive search over the open games involving ti's division rivals
    (ti wins out; their other opponents are free). A rival finishing above mx
    ends the branch; rivals level with ti go through the division tiebreakers
    that the rivals' and ti's own games decide (head-to-head, division record,
    common games, conference record). If ti survives those it counts as
    possible, since SOV/SOS depend on games outside this search.
    Returns True / False, or None if the node budget ran out."""
    rivals = [t for t in L.div_teams[L.team_div[ti]] if t != ti]
    if any(cur[t] > mx for t in rivals):
        return False
    winners = np.array(base_winners, copy=True)
    rset = set(rivals)
    todo = []
    for gi in open_idx:
        h, a = int(L.home[gi]), int(L.away[gi])
        if h == ti or a == ti:
            winners[gi] = ti
        elif h in rset or a in rset:
            todo.append(gi)
    W = {t: cur[t] for t in rivals}
    nodes = [0]

    def leaf():
        group = [ti] + [t for t in rivals if W[t] == mx]
        if len(group) == 1:
            return True
        c = _Ctx(L, winners, None)
        # record-based steps only: SOV/SOS depend on games outside this search
        return ti in div_top(c, group, ("h2h", "div", "common0", "conf"))

    def dfs(k):
        nodes[0] += 1
        if nodes[0] > DIV_NODE_BUDGET:
            raise TimeoutError
        if k == len(todo):
            return leaf()
        gi = todo[k]
        h, a = int(L.home[gi]), int(L.away[gi])
        # try the result that keeps a rival down first: finds witnesses fast
        opts = [a, h] if h in rset and a not in rset else [h, a] if a in rset and h not in rset else [h, a]
        for w in opts:
            if w in rset and W[w] + 1 > mx:
                continue
            winners[gi] = w
            if w in rset:
                W[w] += 1
            ok = dfs(k + 1)
            if w in rset:
                W[w] -= 1
            if ok:
                return True
        winners[gi] = -1
        return False

    try:
        return dfs(0)
    except TimeoutError:
        return None


def bound_seeds(L, base_winners, ti):
    """Seeds (1..7, 8 = miss) team `ti` is not provably shut out of.

    * Division seeds: ti must be able to win the division (exact search with
      the record-based division tiebreakers, `_can_win_division`), and to be
      seed s it needs ndiv-s other divisions whose every team stays at or
      below its max wins at the same time (`_hold_feasible`, a flow problem,
      so a leader's losses count as wins for whoever it plays).
    * Wild-card seed s: at most s-5 non-division-winners may finish above ti.
      Each division may let one team (its winner) through for free plus s-5
      extra teams overall; every choice of those teams is tried, and ti is
      shut out if none lets the rest stay at or below its max.
    Ties at ti's max count in ti's favour except in the division search, where
    the record-based tiebreakers are applied."""
    conf = L.team_conf[ti]
    confteams = L.conf_idx[conf]
    open_idx = [gi for gi in range(len(base_winners)) if base_winners[gi] < 0]
    cur = {t: 0 for t in confteams}
    emax = {t: 0 for t in confteams}        # max wins, given ti wins out
    for gi in range(len(base_winners)):
        w = base_winners[gi]
        if w >= 0:
            if w in cur:
                cur[w] += 1
        else:
            h, a = int(L.home[gi]), int(L.away[gi])
            for t, o in ((h, a), (a, h)):
                if t in emax and o != ti:
                    emax[t] += 1
    for t in confteams:
        emax[t] += cur[t]
    mx = emax[ti]
    divs = [d for d in L.div_teams if d.split()[0] == conf]
    my_div = L.team_div[ti]
    others = [d for d in divs if d != my_div]
    ndiv = len(divs)
    ok = {MISS}

    # --- division seeds -----------------------------------------------------
    if _can_win_division(L, base_winners, open_idx, ti, cur, mx) is not False:
        rivals = [t for t in L.div_teams[my_div] if t != ti]
        for s in range(1, ndiv + 1):
            need = ndiv - s                 # other divisions held below ti
            if any(_hold_feasible(L, open_idx, ti, cur, mx,
                                  rivals + [t for d in held for t in L.div_teams[d]])
                   for held in combinations(others, need)):
                ok.update(range(s, ndiv + 1))
                break

    # --- wild-card seeds ----------------------------------------------------
    risky = {d: [t for t in L.div_teams[d] if t != ti and emax[t] > mx] for d in divs}
    forced = {d: [t for t in risky[d] if cur[t] > mx] for d in divs}
    nwc = MISS - 1 - ndiv
    combos = [0]

    def wc_feasible(budget):
        """Some free set (one team per division + `budget` extras) works?"""
        choices = []                        # per division: list of free subsets
        for d in divs:
            opts = []
            r, f = risky[d], forced[d]
            if not r:
                opts.append(())
            else:
                rest = [t for t in r if t not in f]
                for k in range(max(1, len(f)), min(len(r), 1 + budget) + 1):
                    for extra in combinations(rest, k - len(f)):
                        opts.append(tuple(f) + extra)
            choices.append(opts)

        def rec(i, used, free):
            if used > budget:
                return False
            if i == len(divs):
                combos[0] += 1
                if combos[0] > WC_COMBO_BUDGET:
                    raise TimeoutError
                cons = [t for t in confteams if t != ti and t not in free]
                return _hold_feasible(L, open_idx, ti, cur, mx, cons)
            for opt in choices[i]:
                if rec(i + 1, used + max(0, len(opt) - 1), free | set(opt)):
                    return True
            return False

        return rec(0, 0, frozenset())

    try:
        for s in range(ndiv + 1, ndiv + nwc + 1):
            if wc_feasible(s - ndiv - 1):
                ok.update(range(s, ndiv + nwc + 1))
                break
    except TimeoutError:
        ok.update(range(ndiv + 1, ndiv + nwc + 1))
    return ok


def achievable_seeds(L, base_winners, ti, mc_seeds=frozenset()):
    """Fallback: seeds `ti` is not provably shut out of by `bound_seeds`,
    unioned with the seeds reached in the Monte Carlo."""
    return sorted(bound_seeds(L, base_winners, ti) | set(mc_seeds))
