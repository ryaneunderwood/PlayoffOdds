#!/usr/bin/env python3
"""Backtest the Elo model against Vegas moneylines from the 2023 season on.

Walk-forward (no lookahead): build Elo from 2018-2022, then for every game in
2023-2025 in chronological order, record the model's pre-game win probability,
the closing Vegas moneyline, and the result -- updating the ratings only after
the game. Then evaluate four flat-$100 betting strategies.
"""
import numpy as np
import nfl_data_py as nfl

import sports_elo as S

STAKE = 100.0
sport = S.NFL


def moneyline_profit(ml, stake=STAKE):
    """Profit on a winning `stake` bet at American odds `ml`."""
    return stake * (ml / 100.0) if ml > 0 else stake * (100.0 / -ml)


def load_games(year):
    """Per-game rows with result, moneylines, and neutral-site flag."""
    s = nfl.import_schedules([year])
    s = s[s["game_type"].isin(["REG", "WC", "DIV", "CON", "SB"])]
    s = s.dropna(subset=["home_score", "away_score", "home_moneyline",
                         "away_moneyline", "week"])
    rows = []
    for r in s.itertuples(index=False):
        rows.append({
            "week": int(r.week),
            "home": sport.canon(r.home_team), "away": sport.canon(r.away_team),
            "hs": float(r.home_score), "as": float(r.away_score),
            "home_ml": float(r.home_moneyline), "away_ml": float(r.away_moneyline),
            "neutral": str(r.location).lower() == "neutral",
        })
    return rows


def run():
    # Ratings through the end of 2022 (already regressed for the 2023 preseason).
    ratings, _ = S.build_ratings(sport, 2018, 2022)

    records = []
    for year in (2023, 2024, 2025):
        games = load_games(year)
        for wk in sorted({g["week"] for g in games}):
            wkgames = [g for g in games if g["week"] == wk]
            # Predict every game in the week with start-of-week ratings...
            for g in wkgames:
                H = 0.0 if g["neutral"] else sport.home_field
                p_home = S.elo_expected(ratings.get(g["home"], sport.mean),
                                        ratings.get(g["away"], sport.mean), H)
                records.append({**g, "year": year, "p_home": p_home})
            # ...then update ratings with the actual results.
            upd = [(g["home"], g["away"], g["hs"], g["as"], g["neutral"])
                   for g in wkgames]
            ratings = S.apply_week(sport, ratings, upd)
        ratings = S.preseason_regress(ratings, mean=sport.mean, rho=sport.rho)

    return records


def opp(side):
    return "away" if side == "home" else "home"


def annotate(records):
    for g in records:
        g["tie"] = g["hs"] == g["as"]
        g["home_won"] = g["hs"] > g["as"]
        g["model_fav"] = "home" if g["p_home"] > 0.5 else ("away" if g["p_home"] < 0.5 else None)
        if g["home_ml"] < g["away_ml"]:
            g["vegas_fav"] = "home"
        elif g["away_ml"] < g["home_ml"]:
            g["vegas_fav"] = "away"
        else:
            g["vegas_fav"] = None
        g["disagree"] = (g["model_fav"] is not None and g["vegas_fav"] is not None
                         and g["model_fav"] != g["vegas_fav"])


def bet_side(g, side):
    """Settle a $100 bet on `side`. Returns profit (push -> 0)."""
    if g["tie"]:
        return 0.0
    ml = g["home_ml"] if side == "home" else g["away_ml"]
    won = g["home_won"] if side == "home" else (not g["home_won"])
    return moneyline_profit(ml) if won else -STAKE


def strat_bets(records, key):
    """(game, side) pairs for strategy a/b/c/d over `records`."""
    if key == "a":  # model pick, disagreements only
        return [(g, g["model_fav"]) for g in records if g["disagree"]]
    if key == "b":  # model favorite, every game
        return [(g, g["model_fav"]) for g in records if g["model_fav"]]
    if key == "c":  # against model, disagreements only
        return [(g, opp(g["model_fav"])) for g in records if g["disagree"]]
    if key == "d":  # against model, every game
        return [(g, opp(g["model_fav"])) for g in records if g["model_fav"]]
    if key == "e":  # agreed favorite, only when model & Vegas agree
        return [(g, g["model_fav"]) for g in records
                if g["model_fav"] and g["vegas_fav"] and g["model_fav"] == g["vegas_fav"]]


def tally(bets):
    """-> (n, win%, net, roi%) for a list of (game, side) bets."""
    settled = [(g, s) for (g, s) in bets if not g["tie"]]
    net = sum(bet_side(g, s) for (g, s) in bets)
    wins = sum(1 for (g, s) in settled
               if (g["home_won"] if s == "home" else not g["home_won"]))
    staked = STAKE * len(settled)
    winpct = (wins / len(settled) * 100) if settled else 0.0
    roi = (net / staked * 100) if staked else 0.0
    return len(bets), winpct, net, roi


def acc(records, fav_key):
    sub = [g for g in records if g[fav_key] and not g["tie"]]
    if not sub:
        return float("nan")
    return 100 * np.mean([(g[fav_key] == "home") == g["home_won"] for g in sub])


def evaluate(records):
    annotate(records)
    print(f"\nWalk-forward backtest 2023-2025  |  {len(records)} games "
          f"(incl. playoffs), Elo built from 2018\n" + "=" * 78)
    print(f"Model straight-up accuracy: {acc(records,'model_fav'):5.1f}%   "
          f"Vegas favorite accuracy: {acc(records,'vegas_fav'):5.1f}%")
    ndis = sum(g["disagree"] for g in records)
    print(f"Disagreements on the favorite: {ndis} of {len(records)} "
          f"({ndis/len(records)*100:.1f}%)\n")
    print(f"{'strategy':56} {'bets':>4} {'win%':>6} {'P/L $':>10} {'ROI':>7}")
    print("-" * 88)
    names = {
        "a": "a) $100 on model pick, only when model & Vegas disagree",
        "b": "b) $100 on model's favorite, every game",
        "c": "c) $100 against model (= Vegas pick), only on disagreements",
        "d": "d) $100 against model's favorite, every game",
        "e": "e) $100 on the agreed favorite, only when model & Vegas agree",
    }
    for k in "abcde":
        n, wp, net, roi = tally(strat_bets(records, k))
        print(f"{names[k]:56} {n:>4} {wp:>5.1f}% {net:>+10.0f} {roi:>+6.1f}%")


def by_season(records):
    print("\n\nBY SEASON  (ROI per strategy; e = bet agreed favorite on agreements)\n"
          + "=" * 84)
    print(f"{'season':7} {'games':>5} {'mdlAcc':>7} {'vegAcc':>7} "
          f"{'a ROI':>7} {'b ROI':>7} {'c ROI':>7} {'d ROI':>7} {'e ROI':>7} {'e P/L':>9}")
    print("-" * 84)
    for yr in (2023, 2024, 2025, None):
        sub = records if yr is None else [g for g in records if g["year"] == yr]
        r = {k: tally(strat_bets(sub, k)) for k in "abcde"}
        label = "ALL" if yr is None else str(yr)
        print(f"{label:7} {len(sub):>5} {acc(sub,'model_fav'):>6.1f}% "
              f"{acc(sub,'vegas_fav'):>6.1f}% "
              f"{r['a'][3]:>+6.1f}% {r['b'][3]:>+6.1f}% {r['c'][3]:>+6.1f}% "
              f"{r['d'][3]:>+6.1f}% {r['e'][3]:>+6.1f}% {r['e'][2]:>+9.0f}")


def by_team(records):
    print("\n\nBY TEAM  (games involving the team; bet the model's favorite each one)\n"
          + "=" * 78)
    teams = sorted({t for g in records for t in (g["home"], g["away"])})
    rows = []
    for t in teams:
        sub = [g for g in records if g["home"] == t or g["away"] == t]
        n, wp, net, roi = tally(strat_bets(sub, "b"))
        _, _, dnet, _ = tally(strat_bets(sub, "a"))      # disagreement subset
        nag, _, enet, eroi = tally(strat_bets(sub, "e")) # agreement subset
        ndis = sum(g["disagree"] for g in sub)
        rows.append((t, n, wp, net, roi, ndis, dnet, nag, enet, eroi))
    rows.sort(key=lambda r: -r[3])  # by net P/L of strategy b
    print(f"{'team':4} {'G':>3} {'win%':>6} {'bet-model P/L':>13} {'ROI':>7}   "
          f"{'agree':>5} {'agree P/L':>9}  {'disagr':>6} {'disagr P/L':>10}")
    print("-" * 84)
    for t, n, wp, net, roi, ndis, dnet, nag, enet, eroi in rows:
        flag = "  <==" if net > 0 else ""
        print(f"{t:4} {n:>3} {wp:>5.1f}% {net:>+13.0f} {roi:>+6.1f}%   "
              f"{nag:>5} {enet:>+9.0f}  {ndis:>6} {dnet:>+10.0f}{flag}")
    nprof = sum(1 for r in rows if r[3] > 0)
    print("-" * 78)
    print(f"{nprof} of {len(rows)} teams profitable for 'bet the model's favorite'. "
          f"~{len(records)*2//len(rows)} bets/team -> small samples, expect noise.")


if __name__ == "__main__":
    recs = run()
    evaluate(recs)
    by_season(recs)
    by_team(recs)
