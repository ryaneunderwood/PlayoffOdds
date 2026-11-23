#!/usr/bin/env node
"use strict";
// Exact achievable seeds for every team, for the build (run by sports_elo.py
// when Node is available).
//   stdin:  {sport, teams, divisions, schedule:[{home, away, played, winner, dec}],
//            budget (search nodes per query), seconds (overall time limit)}
//   stdout: {seeds: {team: [seed, ...]}, unknown: {team: [seed, ...]}, stats}
// Seeds are 1..NSEED with NSEED+1 = missed the playoffs; "unknown" lists seeds
// left possible only because a search ran out of budget.
const Rules = require("./rules.js");

let raw = "";
process.stdin.on("data", d => { raw += d; });
process.stdin.on("end", () => {
  const inp = JSON.parse(raw);
  const L = Rules.buildLeague({ sport: inp.sport, teams: inp.teams, divisions: inp.divisions,
    games: inp.schedule.map(g => [g.home, g.away]) });
  const dom = Rules.domainsFromSchedule(L, inp.schedule, null);
  const res = Rules.exactSeeds(L, dom, { budget: inp.budget || 300000, randomSeasons: 400,
    deadline: Date.now() + 1000 * (inp.seconds || 100) });
  const seeds = {}, unknown = {};
  for (let t = 0; t < L.n; t++) {
    const r = res.get(t);
    seeds[L.teams[t]] = [...r.seeds].sort((a, b) => a - b);
    unknown[L.teams[t]] = [...r.unknown].sort((a, b) => a - b);
  }
  process.stdout.write(JSON.stringify({ seeds, unknown, stats: res.stats }));
});
