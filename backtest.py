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


def evaluate(records):
    # Per game derive model favorite, vegas favorite, and outcome.
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
        """Settle a $100 bet on `side` ('home'/'away'). Returns profit (push=0)."""
        if g["tie"]:
            return 0.0
        ml = g["home_ml"] if side == "home" else g["away_ml"]
        won = g["home_won"] if side == "home" else (not g["home_won"])
        return moneyline_profit(ml) if won else -STAKE

    def opp(side):
        return "away" if side == "home" else "home"

    strategies = {
        "a) $100 on model pick, only when model & Vegas disagree":
            [(g, g["model_fav"]) for g in records if g["disagree"]],
        "b) $100 on model's favorite, every game":
            [(g, g["model_fav"]) for g in records if g["model_fav"]],
        "c) $100 against model (= Vegas pick), only on disagreements":
            [(g, opp(g["model_fav"])) for g in records if g["disagree"]],
        "d) $100 against model's favorite, every game":
            [(g, opp(g["model_fav"])) for g in records if g["model_fav"]],
    }

    print(f"\nWalk-forward backtest 2023-2025  |  {len(records)} games "
          f"(incl. playoffs), Elo built from 2018\n" + "=" * 78)

    # Reference accuracy.
    mf = [g for g in records if g["model_fav"] and not g["tie"]]
    macc = np.mean([(g["model_fav"] == "home") == g["home_won"] for g in mf])
    vf = [g for g in records if g["vegas_fav"] and not g["tie"]]
    vacc = np.mean([(g["vegas_fav"] == "home") == g["home_won"] for g in vf])
    ndis = sum(g["disagree"] for g in records)
    print(f"Model straight-up accuracy: {macc*100:5.1f}%   "
          f"Vegas favorite accuracy: {vacc*100:5.1f}%")
    print(f"Games where model & Vegas disagree on the favorite: {ndis} "
          f"of {len(records)} ({ndis/len(records)*100:.1f}%)\n")

    print(f"{'strategy':56} {'bets':>4} {'win%':>6} {'P/L $':>10} {'ROI':>7}")
    print("-" * 88)
    for name, bets in strategies.items():
        settled = [(g, s) for (g, s) in bets if not g["tie"]]
        profits = [bet_side(g, s) for (g, s) in bets]
        wins = sum(1 for (g, s) in settled
                   if (g["home_won"] if s == "home" else not g["home_won"]))
        n = len(bets)
        staked = STAKE * len(settled)  # pushes refunded, not staked
        net = sum(profits)
        winpct = (wins / len(settled) * 100) if settled else 0.0
        roi = (net / staked * 100) if staked else 0.0
        print(f"{name:56} {n:>4} {winpct:>5.1f}% {net:>+10.0f} {roi:>+6.1f}%")
    print("-" * 88)
    print("ROI = net profit / total staked. (a)&(c) are opposite sides of the same\n"
          "disagreement games; (b)&(d) are opposite sides of every game.")


if __name__ == "__main__":
    evaluate(run())
