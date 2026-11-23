"use strict";
/* PlayoffOdds rules engine: NFL / NHL standings, the real tiebreaking
 * procedures, conference seeding, and an exact search for which seeds each
 * team can still reach.
 *
 * Pure JavaScript with no DOM access, so it runs on the page's main thread and
 * in a Web Worker.
 *
 * ---------------------------------------------------------------------------
 * Outcome codes (one small integer per game)
 *   NFL: 0 home win, 1 away win, 2 tie
 *   NHL: 0 home REG, 1 home OT, 2 home SO, 3 away REG, 4 away OT, 5 away SO
 * A game's *domain* is a bitmask of the outcomes still possible (a played game
 * has exactly one bit set). Points per outcome: NFL 2/1/0 (so standings
 * points = 2W + T, which orders teams exactly like win percentage); NHL 2 for
 * a win and 1 for an OT/SO loss.
 *
 * Tiebreakers
 *   Every step the model cannot evaluate (points scored/allowed, net points,
 *   goal differential, coin toss) is treated as "could go either way", and
 *   wherever the written rules are ambiguous both readings are kept. So a seed
 *   is only ever ruled out when no reading of the rules allows it.
 *
 * Feasibility search (exactSeeds)
 *   For team ti and seed s, ti's final points P are tried one value at a time.
 *   Level 1 assigns every other conference team a class relative to P (ABOVE
 *   = more points, TIE = exactly P, BELOW = fewer), pruned by
 *     - a count test: which seeds the per-division numbers of teams above ti
 *       still allow, and
 *     - a max-flow test that every team can land in its class at the same
 *       time (each remaining game's points go to one of its two teams, so a
 *       leader losing out really does hand its opponents those wins).
 *   For the NFL, where a game's two points may split 2-0, 1-1 or 0-2, the flow
 *   test is exact. For the NHL a split flow solution is turned into real game
 *   results by a small search. With no team tied with ti the seed follows
 *   from the counts alone. Otherwise level 2 enumerates the games of the tied
 *   teams and applies the real tiebreakers; where those depend on strength of
 *   victory/schedule that is still open, it branches on the opponents' games
 *   until the comparison is settled.
 *   Every "possible" answer is backed by a complete season that is replayed
 *   through the full seeding procedure, and every "impossible" answer comes
 *   from an exhausted search. If a search runs out of budget the seed is left
 *   possible and flagged, so an X is never shown without a proof.
 */
(function (root) {

const NFL_PTS = [[2, 0], [0, 2], [1, 1]];
const NHL_PTS = [[2, 0], [2, 1], [2, 1], [0, 2], [1, 2], [1, 2]];
const BELOW = 0, TIE = 1, ABOVE = 2;

/* ------------------------------------------------------------------ league */
// spec: {sport:'nfl'|'nhl', teams:[code], divisions:{name:[code]},
//        games:[[home, away], ...] in chronological order (codes or indices)}
function buildLeague(spec) {
  const sport = spec.sport, teams = spec.teams, n = teams.length, idx = {};
  teams.forEach((t, i) => { idx[t] = i; });
  const div = new Array(n), conf = new Array(n);
  const divTeams = {}, confTeams = {}, confDivs = {};
  for (const d of Object.keys(spec.divisions)) {
    const c = d.split(" ")[0];
    divTeams[d] = spec.divisions[d].map(t => idx[t]);
    (confDivs[c] = confDivs[c] || []).push(d);
    confTeams[c] = confTeams[c] || [];
    for (const t of divTeams[d]) { div[t] = d; conf[t] = c; confTeams[c].push(t); }
  }
  const ng = spec.games.length;
  const H = new Int32Array(ng), A = new Int32Array(ng);
  const isDiv = new Uint8Array(ng), isConf = new Uint8Array(ng);
  const teamGames = [], divGames = [], confGames = [], opp = [];
  for (let i = 0; i < n; i++) { teamGames.push([]); divGames.push([]); confGames.push([]); opp.push(new Set()); }
  const pairs = new Map();
  spec.games.forEach((g, gi) => {
    const h = typeof g[0] === "number" ? g[0] : idx[g[0]];
    const a = typeof g[1] === "number" ? g[1] : idx[g[1]];
    H[gi] = h; A[gi] = a;
    isDiv[gi] = div[h] === div[a] ? 1 : 0;
    isConf[gi] = conf[h] === conf[a] ? 1 : 0;
    teamGames[h].push(gi); teamGames[a].push(gi);
    if (isDiv[gi]) { divGames[h].push(gi); divGames[a].push(gi); }
    if (isConf[gi]) { confGames[h].push(gi); confGames[a].push(gi); }
    opp[h].add(a); opp[a].add(h);
    const k = h < a ? h * n + a : a * n + h;
    if (!pairs.has(k)) pairs.set(k, []);
    pairs.get(k).push(gi);
  });
  const nfl = sport === "nfl";
  const PTS = nfl ? NFL_PTS : NHL_PTS, NOUT = PTS.length;
  const NSEED = nfl ? 7 : 5, MISS = NSEED + 1;
  // per-domain-mask side ranges: [minH, maxH, minA, maxA, minSum, maxSum]
  const MASKINFO = [];
  for (let m = 0; m < (1 << NOUT); m++) {
    let mnH = 9, mxH = -1, mnA = 9, mxA = -1, mnS = 9, mxS = -1;
    for (let o = 0; o < NOUT; o++) if (m >> o & 1) {
      const [ph, pa] = PTS[o];
      mnH = Math.min(mnH, ph); mxH = Math.max(mxH, ph);
      mnA = Math.min(mnA, pa); mxA = Math.max(mxA, pa);
      mnS = Math.min(mnS, ph + pa); mxS = Math.max(mxS, ph + pa);
    }
    const info = [mnH, mxH, mnA, mxA, mnS, mxS];
    if (!nfl) {
      // per side: [rwLo, rwHi, rowLo, rowHi, wLo, wHi] over the allowed results
      for (const sh of [0, 3]) {
        const st = [9, -1, 9, -1, 9, -1];
        for (let o = 0; o < NOUT; o++) if (m >> o & 1) {
          const mine = o >= sh && o < sh + 3, d = o % 3;
          const v = [mine && d === 0 ? 1 : 0, mine && d <= 1 ? 1 : 0, mine ? 1 : 0];
          for (let k = 0; k < 3; k++) { st[2 * k] = Math.min(st[2 * k], v[k]); st[2 * k + 1] = Math.max(st[2 * k + 1], v[k]); }
        }
        info.push(...st);
      }
    }
    MASKINFO.push(info);
  }
  return {
    sport, nfl, teams, n, idx, div, conf, divTeams, confTeams, confDivs,
    confs: Object.keys(confDivs), ng, H, A, isDiv, isConf, teamGames, divGames,
    confGames, opp, pairs, PTS, NOUT, NSEED, MISS, FULL: (1 << NOUT) - 1, MASKINFO,
  };
}
function pairGames(L, a, b) { return L.pairs.get(a < b ? a * L.n + b : b * L.n + a) || []; }
function ptsOf(L, o, gi, t) { return L.PTS[o][L.H[gi] === t ? 0 : 1]; }
function oppOf(L, gi, t) { return L.H[gi] === t ? L.A[gi] : L.H[gi]; }
function popcount(m) { let c = 0; while (m) { m &= m - 1; c++; } return c; }
function single(m) { return m && !(m & (m - 1)); }
function bitIndex(m) { return 31 - Math.clz32(m); }

/* ----------------------------------------------------------- rationals */
// Values are intervals {lo:[num,den], hi:[num,den]} so the same code serves
// complete seasons (lo == hi) and partial ones (strength of victory/schedule
// still open). null = the step does not apply.
function cmpQ(a, b) { return a[0] * b[1] - b[0] * a[1]; }
function exactV(num, den) { const q = [num, den]; return { lo: q, hi: q }; }
function isExact(v) { return cmpQ(v.lo, v.hi) === 0; }

// Keep the members tied for the best value. Returns {set, unc}: unc means
// the outcome depends on games not yet decided (set = every team that could
// still be best).
function filterMax(group, vals) {
  for (const v of vals) if (v === null) return { set: group, unc: false };
  let best = vals[0].lo;
  for (const v of vals) if (cmpQ(v.lo, best) > 0) best = v.lo;
  const set = [];
  let unc = false;
  for (let i = 0; i < group.length; i++) if (cmpQ(vals[i].hi, best) >= 0) set.push(group[i]);
  if (set.length > 1) {
    const ref = vals[group.indexOf(set[0])];
    for (const t of set) {
      const v = vals[group.indexOf(t)];
      if (!isExact(v) || cmpQ(v.lo, ref.lo) !== 0) { unc = true; break; }
    }
  } else {
    const v = vals[group.indexOf(set[0])];
    // a sole leader is certain only if it beats every other team's best case
    for (let i = 0; i < group.length; i++) if (group[i] !== set[0] && cmpQ(vals[i].hi, v.lo) >= 0) unc = true;
  }
  return { set, unc };
}

/* ----------------------------------------------------- evaluation context */
// ctx: {L, dom (per-game outcome masks), plo, phi (final-points bounds per
// team, used only for strength of victory / schedule)}. Every criterion is an
// interval over the outcomes still allowed, exact once the games are decided.
// Per-game point range for team t under the current domains.
function pr(ctx, gi, t) { const mi = ctx.L.MASKINFO[ctx.dom[gi]]; return ctx.L.H[gi] === t ? [mi[0], mi[1]] : [mi[2], mi[3]]; }
// A team whose final total is pinned (ctx.fixed: t -> [P, totalLo, totalHi])
// can only take P minus what its other games give, which tightens any subset.
function tighten(ctx, t, lo, hi) {
  const f = ctx.fixed && ctx.fixed.get(t);
  if (!f) return [lo, hi];
  return [Math.max(lo, f[0] - (f[2] - hi)), Math.min(hi, f[0] - (f[1] - lo))];
}
function sumPts(ctx, t, games) { let lo = 0, hi = 0; for (const gi of games) { const r = pr(ctx, gi, t); lo += r[0]; hi += r[1]; } return tighten(ctx, t, lo, hi); }
function rangeV(lo, hi, den) { return { lo: [lo, den], hi: [hi, den] }; }

/* --------------------------------------------------- NFL tiebreak steps */
function nflH2H(ctx, t, group) {
  let lo = 0, hi = 0, g = 0;
  for (const o of group) if (o !== t) for (const gi of pairGames(ctx.L, t, o)) { g++; const r = pr(ctx, gi, t); lo += r[0]; hi += r[1]; }
  [lo, hi] = tighten(ctx, t, lo, hi);
  return g ? rangeV(lo, hi, 2 * g) : null;
}
function nflDivPct(ctx, t) { const gs = ctx.L.divGames[t], r = sumPts(ctx, t, gs); return rangeV(r[0], r[1], 2 * gs.length || 1); }
function nflConfPct(ctx, t) { const gs = ctx.L.confGames[t], r = sumPts(ctx, t, gs); return rangeV(r[0], r[1], 2 * gs.length || 1); }
function commonVals(ctx, group, minG) {
  const L = ctx.L;
  let inter = null;
  for (const x of group) inter = inter === null ? new Set(L.opp[x]) : new Set([...inter].filter(y => L.opp[x].has(y)));
  if (!inter.size) return null;
  const vals = [];
  for (const t of group) {
    let lo = 0, hi = 0, g = 0;
    for (const gi of L.teamGames[t]) if (inter.has(oppOf(L, gi, t))) { g++; const r = pr(ctx, gi, t); lo += r[0]; hi += r[1]; }
    if (g < Math.max(minG, 1)) return null;
    [lo, hi] = tighten(ctx, t, lo, hi);
    vals.push(rangeV(lo, hi, 2 * g));
  }
  return vals;
}
// Strength of victory (wonOnly) / schedule: opponents' combined final points
// over their games, from the bounds ctx.plo / ctx.phi.
function nflStrength(ctx, t, wonOnly) {
  const L = ctx.L;
  let lo = 0, hi = 0, den = 0;
  for (const gi of L.teamGames[t]) {
    if (wonOnly) { const r = pr(ctx, gi, t); if (r[1] < 2) continue; if (r[0] < 2) return { lo: [0, 1], hi: [1, 1] }; }
    const o = oppOf(L, gi, t);
    if (!ctx.plo) ctx.lazyBounds();
    lo += ctx.plo[o]; hi += ctx.phi[o]; den += 2 * L.teamGames[o].length;
  }
  if (!den) return exactV(0, 1);
  return { lo: [lo, den], hi: [hi, den] };
}
function nflStepVals(ctx, step, group) {
  switch (step) {
    case "h2h": { const v = group.map(t => nflH2H(ctx, t, group)); return v.some(x => x === null) ? null : v; }
    case "div": return group.map(t => nflDivPct(ctx, t));
    case "conf": return group.map(t => nflConfPct(ctx, t));
    case "common0": return commonVals(ctx, group, 0);
    case "common4": return commonVals(ctx, group, 4);
    case "sov": return group.map(t => nflStrength(ctx, t, true));
    case "sos": return group.map(t => nflStrength(ctx, t, false));
  }
  return null;
}
function union(a, b) {
  const s = new Set(a.tops);
  for (const t of b.tops) s.add(t);
  return { tops: [...s], unc: a.unc || b.unc };
}
// Generic ladder: survivors shrinking to two restart the two-club ladder;
// shrinking but staying >= 3 either continues or restarts (both kept).
function ladder(ctx, cur, k, steps, two, again) {
  if (cur.length === 1) return { tops: cur, unc: false };
  for (; k < steps.length; k++) {
    let r;
    if (steps[k] === "sweep") r = sweep(ctx, cur);
    else {
      const vals = nflStepVals(ctx, steps[k], cur);
      if (vals === null) continue;
      r = filterMax(cur, vals);
    }
    if (r.unc) return { tops: r.set, unc: true };
    if (r.set.length < cur.length) {
      if (r.set.length === 1) return { tops: r.set, unc: false };
      if (r.set.length === 2) return two(r.set);
      return union(ladder(ctx, r.set, k + 1, steps, two, again), again(r.set));
    }
  }
  return { tops: cur, unc: false };   // points / coin toss: any of them
}
const DIV_STEPS = ["h2h", "div", "common0", "conf", "sov", "sos"];
function nflDivTop(ctx, group) {
  if (group.length === 1) return { tops: group, unc: false };
  const again = g => ladder(ctx, g, 0, DIV_STEPS, again, again);
  return again(group);
}
function sweep(ctx, cur) {
  // Applies only if one club beat each of the others (it advances) or lost to
  // each of the others (it is eliminated); every pair must have played.
  const L = ctx.L;
  let undecided = false;
  const res = t => {
    let allW = true, allL = true;
    for (const o of cur) if (o !== t) {
      const gs = pairGames(L, t, o);
      if (!gs.length) return [false, false];
      for (const gi of gs) {
        const r = pr(ctx, gi, t);
        if (r[0] !== r[1]) undecided = true;
        if (r[0] !== 2) allW = false;
        if (r[1] !== 0) allL = false;
      }
    }
    return [allW, allL];
  };
  const rs = cur.map(res);
  if (undecided) return { set: cur, unc: true };
  const w = cur.filter((t, i) => rs[i][0]);
  if (w.length === 1) return { set: w, unc: false };
  const keep = cur.filter((t, i) => !rs[i][1]);
  return { set: keep.length ? keep : cur, unc: false };
}
const WC2_STEPS = ["h2h", "conf", "common4", "sov", "sos"];
const WCM_STEPS = ["sweep", "conf", "common4", "sov", "sos"];
function nflWc2(ctx, g) {
  if (ctx.L.div[g[0]] === ctx.L.div[g[1]]) return nflDivTop(ctx, g);
  const two = x => nflWc2(ctx, x);
  return ladder(ctx, g, 0, WC2_STEPS, two, two);
}
// divRank: Map team -> rank inside its division (for the "best club per
// division first" reduction).
function nflWcTop(ctx, group, divRank) {
  const L = ctx.L;
  if (group.length === 1) return { tops: group, unc: false };
  const ds = new Set(group.map(t => L.div[t]));
  if (ds.size === 1) return nflDivTop(ctx, group);
  if (group.length === 2) return nflWc2(ctx, group);
  const best = {};
  for (const t of group) { const d = L.div[t]; if (!(d in best) || divRank.get(t) < divRank.get(best[d])) best[d] = t; }
  const red = Object.values(best);
  if (red.length === 2) return nflWc2(ctx, red);
  const two = x => nflWc2(ctx, x);
  const again = x => ladder(ctx, x, 0, WCM_STEPS, two, again);
  return again(red);
}

/* --------------------------------------------------- NHL tiebreak steps */
// RW, ROW, total wins, then points in head-to-head games (odd games in the
// city with the extra home game dropped, as a percentage for 3+ clubs); goal
// differential and beyond are unmodeled.
function nhlStatRanges(ctx, t) {
  const L = ctx.L, a = [0, 0, 0, 0, 0, 0];
  for (const gi of L.teamGames[t]) {
    const mi = L.MASKINFO[ctx.dom[gi]], off = L.H[gi] === t ? 6 : 12;
    for (let k = 0; k < 6; k++) a[k] += mi[off + k];
  }
  return a;   // [rwLo, rwHi, rowLo, rowHi, wLo, wHi]
}
function nhlH2H(ctx, t, group) {
  const L = ctx.L;
  let lo = 0, hi = 0, av = 0;
  for (const o of group) if (o !== t) {
    const gs = pairGames(L, t, o);
    let ht = 0, ho = 0;
    for (const gi of gs) { if (L.H[gi] === t) ht++; else ho++; }
    // drop the first |ht-ho| games in the city with the extra home games
    let drop = Math.abs(ht - ho);
    const extraHome = ht > ho ? t : o;
    for (const gi of gs) {
      if (drop && L.H[gi] === extraHome) { drop--; continue; }
      av += 2; const r = pr(ctx, gi, t); lo += r[0]; hi += r[1];
    }
  }
  [lo, hi] = tighten(ctx, t, lo, hi);
  return av ? rangeV(lo, hi, av) : null;
}
function nhlTop(ctx, group) {
  if (group.length === 1) return { tops: group, unc: false };
  let cur = group;
  const st = new Map(cur.map(t => [t, nhlStatRanges(ctx, t)]));
  for (let k = 0; k < 3 && cur.length > 1; k++) {
    const r = filterMax(cur, cur.map(t => { const a = st.get(t); return rangeV(a[2 * k], a[2 * k + 1], 1); }));
    if (r.unc) return { tops: r.set, unc: true };
    cur = r.set;
  }
  if (cur.length > 1) {
    const vals = cur.map(t => nhlH2H(ctx, t, cur));
    if (!vals.some(v => v === null)) {
      const r = filterMax(cur, vals);
      if (r.unc) return { tops: r.set, unc: true };
      cur = r.set;
    }
  }
  return { tops: cur, unc: false };
}
// Alternative reading for 3+ clubs: rank once by the criteria computed over
// the whole group instead of re-running the procedure after each pick.
function nhlSortOnce(ctx, group) {
  const st = new Map(group.map(t => [t, nhlStatRanges(ctx, t)]));
  const h2h = new Map(group.map(t => [t, nhlH2H(ctx, t, group)]));
  for (const t of group) { const a = st.get(t), h = h2h.get(t); if (a[0] !== a[1] || a[2] !== a[3] || a[4] !== a[5] || (h && !isExact(h))) return []; }
  const key = t => { const s = st.get(t), h = h2h.get(t); return [s[0], s[2], s[4], h ? h.lo[0] / h.lo[1] : 0]; };
  const cmp = (a, b) => { const x = key(a), y = key(b); for (let i = 0; i < 4; i++) if (x[i] !== y[i]) return y[i] - x[i]; return 0; };
  const sorted = group.slice().sort(cmp);
  let orders = [[]];
  for (let i = 0; i < sorted.length;) {
    let j = i; while (j + 1 < sorted.length && cmp(sorted[i], sorted[j + 1]) === 0) j++;
    const run = sorted.slice(i, j + 1), perms = permutations(run), next = [];
    for (const o of orders) for (const p of perms) next.push(o.concat(p));
    orders = next.slice(0, 720);
    i = j + 1;
  }
  return orders;
}
function permutations(a) {
  if (a.length <= 1) return [a.slice()];
  const out = [];
  a.forEach((x, i) => { for (const p of permutations(a.slice(0, i).concat(a.slice(i + 1)))) out.push([x].concat(p)); });
  return out;
}

/* ------------------------------------------------------------- ranking */
// All possible orderings of a same-points group (or one random ordering when
// rand is given). Returns {orders, unc}.
function rankGroup(ctx, group, topFn, rand) {
  if (group.length <= 1) return { orders: [group.slice()], unc: false };
  const r = topFn(group);
  if (rand) {
    const t = r.tops[Math.floor(rand() * r.tops.length)];
    const sub = rankGroup(ctx, group.filter(x => x !== t), topFn, rand);
    return { orders: [[t].concat(sub.orders[0])], unc: r.unc };
  }
  const orders = [];
  let unc = r.unc;
  for (const t of r.tops) {
    const sub = rankGroup(ctx, group.filter(x => x !== t), topFn, null);
    unc = unc || sub.unc;
    for (const o of sub.orders) { orders.push([t].concat(o)); if (orders.length > 5000) break; }
  }
  return { orders, unc };
}
function nhlRank(ctx, group, rand) {
  const r = rankGroup(ctx, group, g => nhlTop(ctx, g), rand);
  if (rand || group.length < 3) return r;
  const seen = new Set(r.orders.map(o => o.join(",")));
  for (const o of nhlSortOnce(ctx, group)) { const k = o.join(","); if (!seen.has(k)) { seen.add(k); r.orders.push(o); } }
  return r;
}
function levels(teams, pts) {
  const s = teams.slice().sort((a, b) => pts[b] - pts[a]);
  const out = [];
  for (let i = 0; i < s.length;) { let j = i; while (j + 1 < s.length && pts[s[j + 1]] === pts[s[i]]) j++; out.push(s.slice(i, j + 1)); i = j + 1; }
  return out;
}
// Cartesian product of per-part alternatives, calling emit(choice array).
function product(parts, emit, limit) {
  const pick = new Array(parts.length);
  let count = 0;
  (function rec(i) {
    if (count >= limit) return;
    if (i === parts.length) { count++; emit(pick.slice()); return; }
    for (const p of parts[i]) { pick[i] = p; rec(i + 1); if (count >= limit) return; }
  })(0);
}
function orderAlts(ctx, teams, pts, topRank, rand) {
  // all orderings of `teams` by points, ties broken via topRank(group) -> orders
  const lv = levels(teams, pts);
  const parts = lv.map(g => topRank(g));
  const out = [];
  product(parts, ch => out.push([].concat(...ch)), rand ? 1 : 2000);
  return out;
}

/* ------------------------------------------------------- full seeding */
// Seeds for one conference of a complete season. rand: null -> every possible
// seeding (returned as a per-team Set of seeds); a function -> one random
// seeding (returned as {seed: Map, rank: [...]}, rank = conference order).
function seedConference(L, out, c, rand) {
  const pts = new Int32Array(L.n), dom = new Uint8Array(L.ng);
  for (let gi = 0; gi < L.ng; gi++) { const o = out[gi]; dom[gi] = 1 << o; pts[L.H[gi]] += L.PTS[o][0]; pts[L.A[gi]] += L.PTS[o][1]; }
  const ctx = { L, dom, plo: pts, phi: pts };
  const divs = L.confDivs[c];
  const possible = new Map(L.confTeams[c].map(t => [t, new Set()]));
  let last = null;
  if (L.nfl) {
    const divTop = g => rankGroup(ctx, g, x => nflDivTop(ctx, x), rand).orders;
    const divAlts = divs.map(d => orderAlts(ctx, L.divTeams[d], pts, divTop, rand));
    product(divAlts, divOrders => {
      const divRank = new Map();
      divOrders.forEach(o => o.forEach((t, i) => divRank.set(t, i)));
      const winners = divOrders.map(o => o[0]);
      const wcTop = g => rankGroup(ctx, g, x => nflWcTop(ctx, x, divRank), rand).orders;
      const wset = new Set(winners);
      const pool = L.confTeams[c].filter(t => !wset.has(t));
      const wAlts = orderAlts(ctx, winners, pts, wcTop, rand);
      const pAlts = orderAlts(ctx, pool, pts, wcTop, rand);
      for (const wo of wAlts) for (const po of pAlts) {
        const seed = new Map();
        wo.forEach((t, i) => seed.set(t, i + 1));
        po.forEach((t, i) => seed.set(t, i < 3 ? 5 + i : L.MISS));
        for (const [t, s] of seed) possible.get(t).add(s);
        last = { seed, rank: wo.concat(po) };
      }
    }, rand ? 1 : 2000);
  } else {
    const rk = g => nhlRank(ctx, g, rand).orders;
    const divAlts = divs.map(d => orderAlts(ctx, L.divTeams[d], pts, rk, rand));
    product(divAlts, divOrders => {
      const top = new Set();
      const seed = new Map();
      divOrders.forEach(o => o.slice(0, 3).forEach((t, i) => { seed.set(t, i + 1); top.add(t); }));
      const pool = L.confTeams[c].filter(t => !top.has(t));
      for (const po of orderAlts(ctx, pool, pts, rk, rand)) {
        const s2 = new Map(seed);
        po.forEach((t, i) => s2.set(t, i < 2 ? 4 + i : L.MISS));
        for (const [t, s] of s2) possible.get(t).add(s);
        last = { seed: s2, rank: null };
      }
    }, rand ? 1 : 2000);
    if (rand) last.rank = orderAlts(ctx, L.confTeams[c], pts, rk, rand)[0];
  }
  return rand ? last : possible;
}

/* ------------------------------------------------------------ max flow */
class Dinic {
  constructor() { this.n = 0; this.head = []; this.to = []; this.cap = []; this.nxt = []; }
  reset(n) { this.n = n; this.head = new Int32Array(n).fill(-1); this.to.length = 0; this.cap.length = 0; this.nxt.length = 0; }
  add(u, v, c) {
    const e = this.to.length;
    this.to.push(v, u); this.cap.push(c, 0); this.nxt.push(this.head[u], this.head[v]);
    this.head[u] = e; this.head[v] = e + 1;
    return e;
  }
  maxflow(s, t) {
    let flow = 0;
    const n = this.n, level = new Int32Array(n), it = new Int32Array(n), q = new Int32Array(n);
    const to = this.to, cap = this.cap, nxt = this.nxt, head = this.head;
    for (;;) {
      level.fill(-1); level[s] = 0;
      let qh = 0, qt = 0; q[qt++] = s;
      while (qh < qt) { const u = q[qh++]; for (let e = head[u]; e !== -1; e = nxt[e]) if (cap[e] > 0 && level[to[e]] < 0) { level[to[e]] = level[u] + 1; q[qt++] = to[e]; } }
      if (level[t] < 0) return flow;
      for (let i = 0; i < n; i++) it[i] = head[i];
      const dfs = (u, f) => {
        if (u === t) return f;
        for (; it[u] !== -1; it[u] = nxt[it[u]]) {
          const e = it[u], v = to[e];
          if (cap[e] > 0 && level[v] === level[u] + 1) {
            const d = dfs(v, Math.min(f, cap[e]));
            if (d > 0) { cap[e] -= d; cap[e ^ 1] += d; return d; }
          }
        }
        return 0;
      };
      let f;
      while ((f = dfs(s, 1e9)) > 0) flow += f;
    }
  }
}
const FLOW = new Dinic();

// Can every team t in `bounds` (Map t -> [lb, ub] on final points) land in its
// range at once, given game domains `dom`? Exact for the NFL; for the NHL a
// game's 2 points may split 1-1 here (fixed later by `realize`). With
// want=true also returns per-game extra points for each side.
function flowCheck(L, dom, bounds, want) {
  const base = new Map(), slack = new Map(), coupled = [];
  if (!L._stamp) { L._stamp = new Int32Array(L.ng); L._st = 0; }
  const stamp = L._stamp, st = ++L._st;
  for (const t of bounds.keys()) {
    let b = 0, sl = 0;
    for (const gi of L.teamGames[t]) {
      const mi = L.MASKINFO[dom[gi]], home = L.H[gi] === t, o = home ? L.A[gi] : L.H[gi];
      b += home ? mi[0] : mi[2];
      if (mi[1] === mi[0] && mi[3] === mi[2]) continue;  // decided
      if (bounds.has(o)) { if (stamp[gi] !== st) { stamp[gi] = st; coupled.push(gi); } }
      else sl += home ? mi[1] - mi[0] : mi[3] - mi[2];
    }
    base.set(t, b); slack.set(t, sl);
  }
  // nodes: 0 S, 1 T, 2 SS, 3 TT, games, teams
  const teams = [...bounds.keys()], tnode = new Map();
  const nG = coupled.length, N = 4 + nG + teams.length;
  teams.forEach((t, i) => tnode.set(t, 4 + nG + i));
  const lo = new Map(), hi = new Map();
  for (const t of teams) {
    const [lb, ub] = bounds.get(t), b = base.get(t), s = slack.get(t);
    const l = Math.max(0, lb - b - s), u = ub - b;
    if (u < 0 || l > u) return want ? null : false;
    lo.set(t, l); hi.set(t, u);
  }
  FLOW.reset(N);
  const excess = new Float64Array(N);
  const gEdges = [];
  coupled.forEach((gi, k) => {
    const mi = L.MASKINFO[dom[gi]], g = 4 + k;
    const fmin = mi[4] - mi[0] - mi[2], fmax = mi[5] - mi[0] - mi[2];
    if (fmax - fmin > 0) FLOW.add(0, g, fmax - fmin);
    excess[g] += fmin; excess[0] -= fmin;
    const eh = FLOW.add(g, tnode.get(L.H[gi]), mi[1] - mi[0]);
    const ea = FLOW.add(g, tnode.get(L.A[gi]), mi[3] - mi[2]);
    gEdges.push([eh, ea, mi[1] - mi[0], mi[3] - mi[2]]);
  });
  for (const t of teams) {
    const v = tnode.get(t), l = lo.get(t), u = hi.get(t);
    if (u - l > 0) FLOW.add(v, 1, u - l);
    excess[1] += l; excess[v] -= l;
  }
  FLOW.add(1, 0, 1e9);
  let need = 0;
  for (let v = 0; v < N; v++) {
    if (excess[v] > 0) { FLOW.add(2, v, excess[v]); need += excess[v]; }
    else if (excess[v] < 0) FLOW.add(v, 3, -excess[v]);
  }
  const ok = FLOW.maxflow(2, 3) === need;
  if (!want) return ok;
  if (!ok) return null;
  const sol = new Map();
  coupled.forEach((gi, k) => {
    const [eh, ea, ch, ca] = gEdges[k];
    sol.set(gi, [ch - FLOW.cap[eh], ca - FLOW.cap[ea]]);
  });
  return { sol, base, slack };
}

/* ------------------------------------------------------------- engine */
function naturalBounds(L, dom) {
  const lo = new Int32Array(L.n), hi = new Int32Array(L.n);
  for (let gi = 0; gi < L.ng; gi++) {
    const mi = L.MASKINFO[dom[gi]];
    lo[L.H[gi]] += mi[0]; hi[L.H[gi]] += mi[1];
    lo[L.A[gi]] += mi[2]; hi[L.A[gi]] += mi[3];
  }
  return [lo, hi];
}

// Seeds ti can get given how many teams finish above it in each division
// (k: Map div -> count, ti's division excludes ti).
function seedFromCounts(L, c, own, k) {
  const divs = L.confDivs[c];
  if (L.nfl) {
    if (k.get(own) === 0) { let a = 0; for (const d of divs) if (d !== own && k.get(d) > 0) a++; return 1 + a; }
    let na = 0; for (const d of divs) na += Math.max(0, k.get(d) - 1);
    return na <= 2 ? 5 + na : L.MISS;
  }
  const ko = k.get(own);
  if (ko <= 2) return ko + 1;
  let na = 0; for (const d of divs) na += Math.max(0, k.get(d) - 3);
  return na <= 1 ? 4 + na : L.MISS;
}
// Which per-division counts (within [kmin, kmax]) give seed s?
// Returns null if none, else Map div -> [minAllowed, maxAllowed].
function allowedCounts(L, c, own, kmin, kmax, s) {
  const divs = L.confDivs[c], k = new Map(), lo = new Map(), hi = new Map();
  let any = false;
  (function rec(i) {
    if (i === divs.length) {
      if (seedFromCounts(L, c, own, k) === s) {
        any = true;
        for (const d of divs) { const v = k.get(d); if (!lo.has(d) || v < lo.get(d)) lo.set(d, v); if (!hi.has(d) || v > hi.get(d)) hi.set(d, v); }
      }
      return;
    }
    const d = divs[i];
    for (let v = kmin.get(d); v <= kmax.get(d); v++) { k.set(d, v); rec(i + 1); }
  })(0);
  if (!any) return null;
  const res = new Map();
  for (const d of divs) res.set(d, [lo.get(d), hi.get(d)]);
  return res;
}

function Engine(L, dom0, opts) {
  this.L = L; this.dom0 = dom0; this.opts = opts || {};
  this.budget = this.opts.budget || 400000;
  this.stats = { queries: 0, nodes: 0, unknown: 0, mismatch: 0 };
}

// Build a complete season from domains + a flow solution for the bounded
// teams; returns Int8Array outcomes or null (NHL split that can't be made
// real is handled by the caller via `realize`).
function complete(L, dom, bounds, fl, rand) {
  const out = new Int8Array(L.ng).fill(-1);
  const extra = new Map();
  for (const t of bounds.keys()) {
    const [lb] = bounds.get(t);
    let x = fl.base.get(t);
    extra.set(t, 0);
    for (const [gi, [eh, ea]] of fl.sol) { if (L.H[gi] === t) x += eh; else if (L.A[gi] === t) x += ea; }
    extra.set(t, Math.max(0, lb - x));
  }
  for (let gi = 0; gi < L.ng; gi++) {
    const m = dom[gi];
    if (single(m)) { out[gi] = bitIndex(m); continue; }
    const h = L.H[gi], a = L.A[gi], mi = L.MASKINFO[m];
    let wantH = null, wantA = null;
    if (fl.sol.has(gi)) { const [eh, ea] = fl.sol.get(gi); wantH = mi[0] + eh; wantA = mi[2] + ea; }
    else if (bounds.has(h)) { const e = Math.min(extra.get(h), mi[1] - mi[0]); extra.set(h, extra.get(h) - e); wantH = mi[0] + e; }
    else if (bounds.has(a)) { const e = Math.min(extra.get(a), mi[3] - mi[2]); extra.set(a, extra.get(a) - e); wantA = mi[2] + e; }
    let pick = -1;
    const opts = [];
    for (let o = 0; o < L.NOUT; o++) if (m >> o & 1) {
      const [ph, pa] = L.PTS[o];
      if ((wantH === null || ph === wantH) && (wantA === null || pa === wantA)) opts.push(o);
    }
    if (!opts.length) return null;
    pick = rand ? opts[Math.floor(rand() * opts.length)] : opts[0];
    out[gi] = pick;
  }
  return out;
}

// Turn bounds into a real season: flow, then (NHL) branch on any game the
// flow split 1-1. Returns outcomes or null.
Engine.prototype.realize = function (dom, bounds, depth) {
  const L = this.L;
  const fl = flowCheck(L, dom, bounds, true);
  if (!fl) return null;
  const out = complete(L, dom, bounds, fl, null);
  if (out) return out;
  // find a coupled game whose split is not a real result and branch on it
  for (const [gi, [eh, ea]] of fl.sol) {
    const m = dom[gi], mi = L.MASKINFO[m];
    let real = false;
    for (let o = 0; o < L.NOUT; o++) if (m >> o & 1 && L.PTS[o][0] === mi[0] + eh && L.PTS[o][1] === mi[2] + ea) real = true;
    if (real) continue;
    for (let o = 0; o < L.NOUT; o++) if (m >> o & 1) {
      if (++this.nodes > this.budget) throw "budget";
      const d2 = dom.slice(); d2[gi] = 1 << o;
      const r = this.realize(d2, bounds, depth + 1);
      if (r) return r;
    }
    return null;
  }
  return null;
};

// Full replay of a candidate season: does ti really get seed s?
Engine.prototype.verify = function (out, c, ti, s) {
  const poss = seedConference(this.L, out, c, null);
  if (this.onSeason) this.onSeason(out);
  return poss.get(ti).has(s);
};

Engine.prototype.query = function (ti, s, known) {
  const L = this.L, c = L.conf[ti], own = L.div[ti];
  this.nodes = 0;
  const [lo, hi] = naturalBounds(L, this.dom0);
  const order = [];
  for (let P = lo[ti]; P <= hi[ti]; P++) order.push(P);
  // likely totals first: a seed better than any seen so far needs a big
  // finish, a worse one a poor finish; otherwise start mid-range
  const ks = known ? [...known] : [];
  const better = ks.length ? s < Math.min(...ks) : s <= Math.ceil(L.NSEED / 2);
  const worse = ks.length ? s > Math.max(...ks) : !better;
  if (better) order.reverse();
  else if (!worse && s <= Math.ceil(L.NSEED / 2)) order.reverse();
  try {
    for (const P of order) if (this.level1(ti, s, P, lo, hi)) return true;
    return false;
  } catch (e) {
    if (e === "budget") { this.stats.unknown++; return null; }
    throw e;
  }
};

Engine.prototype.level1 = function (ti, s, P, lo, hi) {
  const L = this.L, c = L.conf[ti], own = L.div[ti], divs = L.confDivs[c];
  const others = L.confTeams[c].filter(t => t !== ti);
  const poss = new Map(), cls = new Map();
  for (const t of others) {
    let m = 0;
    if (lo[t] <= P - 1) m |= 1 << BELOW;
    if (lo[t] <= P && P <= hi[t]) m |= 1 << TIE;
    if (hi[t] >= P + 1) m |= 1 << ABOVE;
    poss.set(t, m);
    if (single(m)) cls.set(t, bitIndex(m));
  }
  const free = others.filter(t => !cls.has(t));
  // own division first, then the rest, closest to P first
  free.sort((a, b) => ((L.div[a] === own ? 0 : 1) - (L.div[b] === own ? 0 : 1)) ||
    (Math.abs(lo[a] + hi[a] - 2 * P) - Math.abs(lo[b] + hi[b] - 2 * P)));
  const self = this;

  function analyse() {
    const kmin = new Map(), kmax = new Map();
    for (const d of divs) { kmin.set(d, 0); kmax.set(d, 0); }
    for (const t of others) {
      const d = L.div[t], k = cls.has(t) ? cls.get(t) : -1;
      if (k === ABOVE) { kmin.set(d, kmin.get(d) + 1); kmax.set(d, kmax.get(d) + 1); }
      else if (k === TIE || (k === -1 && (poss.get(t) & (1 << TIE | 1 << ABOVE)))) kmax.set(d, kmax.get(d) + 1);
    }
    return [kmin, kmax, allowedCounts(L, c, own, kmin, kmax, s)];
  }
  function boundsFor(allowed, kmin, kmax) {
    const b = new Map();
    b.set(ti, [P, P]);
    for (const t of others) {
      const k = cls.has(t) ? cls.get(t) : -1;
      let lb = lo[t], ub = hi[t];
      if (k === ABOVE) lb = Math.max(lb, P + 1);
      else if (k === TIE) { lb = P; ub = P; }
      else if (k === BELOW) ub = Math.min(ub, P - 1);
      else {
        const [mn, mx] = allowed.get(L.div[t]);
        if (mx === kmin.get(L.div[t])) ub = Math.min(ub, P);     // nobody else may pass ti
        if (mn === kmax.get(L.div[t])) lb = Math.max(lb, P);     // everyone left must reach ti
      }
      if (lb > lo[t] || ub < hi[t]) b.set(t, [lb, ub]);
    }
    return b;
  }
  function dfs(i) {
    if (++self.nodes > self.budget) throw "budget";
    self.cnt.l1++;
    const [kmin, kmax, allowed] = analyse();
    if (!allowed) return false;
    const b = boundsFor(allowed, kmin, kmax);
    if (!flowCheck(L, self.dom0, b, false)) return false;
    if (i === free.length) return self.leaf(ti, s, P, cls, b);
    const t = free[i], d = L.div[t], m = poss.get(t);
    const [mn, mx] = allowed.get(d);
    let pref;
    if (mx === kmin.get(d)) pref = [BELOW, TIE, ABOVE];
    else if (mn === kmax.get(d)) pref = [ABOVE, TIE, BELOW];
    else pref = (lo[t] + hi[t] >= 2 * P) ? [ABOVE, BELOW, TIE] : [BELOW, ABOVE, TIE];
    for (const k of pref) if (m >> k & 1) {
      cls.set(t, k);
      if (dfs(i + 1)) return true;
    }
    cls.delete(t);
    return false;
  }
  return dfs(0);
};

// All classes assigned: with nobody tied the counts decide; otherwise run
// the tiebreakers over the tied teams' games.
Engine.prototype.leaf = function (ti, s, P, cls, b) {
  const L = this.L, c = L.conf[ti], own = L.div[ti];
  const tied = [...cls.keys()].filter(t => cls.get(t) === TIE);
  const bounds = new Map(b);
  for (const t of cls.keys()) {
    const k = cls.get(t);
    if (k === TIE) bounds.set(t, [P, P]);
  }
  if (!tied.length) {
    const k = new Map(L.confDivs[c].map(d => [d, 0]));
    for (const [t, x] of cls) if (x === ABOVE) k.set(L.div[t], k.get(L.div[t]) + 1);
    if (seedFromCounts(L, c, own, k) !== s) return false;
    const out = this.realize(this.dom0, bounds, 0);
    if (!out) return false;
    if (!this.verify(out, c, ti, s)) { this.stats.mismatch++; return true; }
    return true;
  }
  this.cnt.leaves2++;
  return this.level2(ti, s, P, cls, bounds, [ti].concat(tied));
};

// Ways to split a domain when branching: NFL single results; NHL first by
// points (regulation win / OT-or-SO win per side), then OT vs SO.
function splitDomain(L, m) {
  if (L.nfl) { const r = []; for (let o = 0; o < 3; o++) if (m >> o & 1) r.push(1 << o); return r; }
  const parts = [m & 1, m & 6, m & 8, m & 48].filter(x => x);
  if (parts.length > 1) return parts;
  const r = []; for (let o = 0; o < 6; o++) if (m >> o & 1) r.push(1 << o); return r;
}

// Level 2: ti and the teams tied with it all finish on P. Branch on games
// (the tied teams' own first, then -- for strength of victory/schedule --
// their opponents'), evaluating the tiebreakers on intervals at every node:
// prune when seed s is out of reach even in the best case, and stop with a
// replayed season as soon as it is guaranteed.
Engine.prototype.level2 = function (ti, s, P, cls, bounds, G) {
  const L = this.L, gset = new Set(G);
  const dom = this.dom0.slice();
  const self = this;
  const oppsOfG = new Set();
  for (const t of G) for (const o of L.opp[t]) oppsOfG.add(o);
  const pickGame = () => {
    let best = -1, bestScore = -1;
    for (const t of G) for (const gi of L.teamGames[t]) {
      if (single(dom[gi])) continue;
      const mi = L.MASKINFO[dom[gi]];
      if (mi[0] === mi[1] && mi[2] === mi[3] && L.nfl) continue;
      const o = oppOf(L, gi, t);
      const sc = (gset.has(o) ? 4 : 0) + (t === ti ? 2 : 0) + (L.isDiv[gi] ? 1 : 0);
      if (sc > bestScore) { bestScore = sc; best = gi; }
    }
    if (best >= 0) return best;
    if (!L.nfl) return -1;
    for (const o of oppsOfG) for (const gi of L.teamGames[o]) if (!single(dom[gi])) return gi;
    return -1;
  };
  let sovNodes = 0;
  const rec = () => {
    if (++self.nodes > self.budget) throw "budget";
    self.cnt.l2++;
    if (!flowCheck(L, dom, bounds, false)) return false;
    const fixed = new Map();
    for (const t of G) {
      let a = 0, b = 0;
      for (const gi of L.teamGames[t]) { const r = pr({ L, dom }, gi, t); a += r[0]; b += r[1]; }
      fixed.set(t, [P, a, b]);
    }
    const ctx = { L, dom, plo: null, phi: null, fixed, lazyBounds() {
      const [lo, hi] = naturalBounds(L, dom);
      for (let t = 0; t < L.n; t++) if (bounds.has(t)) { const b = bounds.get(t); lo[t] = Math.max(lo[t], b[0]); hi[t] = Math.min(hi[t], b[1]); }
      this.plo = lo; this.phi = hi;
    } };
    const r = L.nfl ? self.nflTieSeeds(ti, cls, G, ctx) : self.nhlTieSeeds(ti, cls, G, ctx);
    if (!r.maybe.has(s)) return false;
    if (r.sure.has(s)) {
      const full = self.realize(dom, bounds, 0);
      if (full) {
        if (!self.verify(full, L.conf[ti], ti, s)) self.stats.mismatch++;
        return true;
      }
    }
    const gi = pickGame();
    if (gi < 0) return false;
    if (!G.some(t => L.teamGames[t].includes(gi))) {
      // only strength of victory/schedule is left open: branching over the
      // opponents' games is costly, so cap it and leave the seed possible
      self.cnt.sov++;
      if (++sovNodes > (self.opts.sovBudget || 3000)) throw "budget";
    }
    const m = dom[gi];
    for (const part of splitDomain(L, m)) {
      dom[gi] = part;
      if (rec()) return true;
    }
    dom[gi] = m;
    return false;
  };
  return rec();
};

// Positions ti can take when `group` is ranked by repeatedly taking one of
// the clubs topFn says may come out on top. Memoised over the set of clubs
// still unplaced, so it is 2^n at worst instead of n!. sure = reachable with
// every comparison settled.
function tiPositions(group, topFn, ti) {
  const idx = new Map(group.map((t, i) => [t, i])), memo = new Map();
  const rec = mask => {
    if (memo.has(mask)) return memo.get(mask);
    const rem = group.filter((t, i) => mask >> i & 1);
    const res = { sure: new Set(), maybe: new Set() };
    if (rem.length === 1) { res.sure.add(0); res.maybe.add(0); }
    else {
      const r = topFn(rem);
      for (const t of r.tops) {
        if (t === ti) { res.maybe.add(0); if (!r.unc) res.sure.add(0); continue; }
        const sub = rec(mask & ~(1 << idx.get(t)));
        for (const p of sub.maybe) res.maybe.add(p + 1);
        if (!r.unc) for (const p of sub.sure) res.sure.add(p + 1);
      }
    }
    memo.set(mask, res);
    return res;
  };
  return rec((1 << group.length) - 1);
}
// Sets of clubs that can fill the first k places: Map bitmask -> sure?
function topKSets(group, topFn, k) {
  const out = new Map(), seen = new Map();
  const full = (1 << group.length) - 1;
  const rec = (mask, depth, sure) => {
    const key = mask * 2 + (sure ? 1 : 0);
    if (seen.has(key)) return;
    seen.set(key, 1);
    if (depth === k) { const taken = full & ~mask; out.set(taken, (out.get(taken) || false) || sure); return; }
    const rem = group.filter((t, i) => mask >> i & 1);
    if (!rem.length) return;
    const r = rem.length === 1 ? { tops: rem, unc: false } : topFn(rem);
    for (const t of r.tops) rec(mask & ~(1 << group.indexOf(t)), depth + 1, sure && !r.unc);
  };
  rec(full, 0, true);
  return out;
}
const TIE_CAP = 400;

// NHL seeds for ti with the tied group G at ti's points.
Engine.prototype.nhlTieSeeds = function (ti, cls, G, ctx) {
  const L = this.L, c = L.conf[ti], own = L.div[ti], divs = L.confDivs[c];
  const above = new Map(divs.map(d => [d, 0])), grp = new Map(divs.map(d => [d, []]));
  for (const [t, k] of cls) { if (k === ABOVE) above.set(L.div[t], above.get(L.div[t]) + 1); }
  for (const t of G) grp.get(L.div[t]).push(t);
  const sure = new Set(), maybe = new Set();
  const add = (sd, ok) => { maybe.add(sd); if (ok) sure.add(sd); };
  const top = g => nhlTop(ctx, g);
  // the "rank once over the whole group" reading, as fixed orders
  const onceOrders = g => g.length >= 3 ? nhlSortOnce(ctx, g) : [];
  const positions = g => {
    const r = tiPositions(g, top, ti);
    for (const o of onceOrders(g)) { const p = o.indexOf(ti); r.maybe.add(p); r.sure.add(p); }
    return r;
  };
  const topSets = (g, k) => {
    const r = topKSets(g, top, k);
    for (const o of onceOrders(g)) { let m = 0; o.slice(0, k).forEach(t => { m |= 1 << g.indexOf(t); }); r.set(m, true); }
    return r;
  };
  const O = grp.get(own), aOwn = above.get(own);
  const po = positions(O);
  let beyond = false;
  for (const p of po.maybe) {
    const place = aOwn + p + 1;
    if (place <= 3) add(place, po.sure.has(p)); else beyond = true;
  }
  if (!beyond) return { sure, maybe };
  let na = 0;
  for (const d of divs) na += Math.max(0, above.get(d) - 3);
  // which tied clubs take the remaining top-three spots in each division
  const choices = [];
  let total = 1;
  for (const d of divs) {
    const g = grp.get(d), k = Math.min(g.length, Math.max(0, 3 - above.get(d)));
    let sets = topSets(g, k);
    if (d === own) { const ti_i = 1 << g.indexOf(ti); sets = new Map([...sets].filter(([m]) => !(m & ti_i))); }
    const list = [...sets].map(([m, ok]) => [g.filter((t, i) => !(m >> i & 1)), ok]);
    choices.push(list);
    total *= list.length;
  }
  if (total > TIE_CAP) {   // too many shapes: over-approximate (prunes less)
    const n = G.length;
    for (let p = 0; p < n; p++) { const sd = 4 + na + p; maybe.add(sd <= 5 ? sd : L.MISS); }
    return { sure, maybe };
  }
  product(choices, picks => {
    const pool = [].concat(...picks.map(x => x[0]));
    const ok = picks.every(x => x[1]);
    const r = positions(pool);
    for (const p of r.maybe) { const sd = 4 + na + p; add(sd <= 5 ? sd : L.MISS, ok && r.sure.has(p)); }
  }, TIE_CAP);
  return { sure, maybe };
};

// NFL seeds for ti with tied group G (all at ti's points). Returns
// {sure: seeds reached with every comparison settled, maybe: all reachable}.
Engine.prototype.nflTieSeeds = function (ti, cls, G, ctx) {
  const L = this.L, c = L.conf[ti], own = L.div[ti], divs = L.confDivs[c];
  const above = new Map(divs.map(d => [d, 0])), grp = new Map(divs.map(d => [d, []]));
  for (const [t, k] of cls) if (k === ABOVE) above.set(L.div[t], above.get(L.div[t]) + 1);
  for (const t of G) grp.get(L.div[t]).push(t);
  const sure = new Set(), maybe = new Set();
  const add = (sd, ok) => { maybe.add(sd); if (ok) sure.add(sd); };
  let aw = 0, na = 0;
  for (const d of divs) if (above.get(d) > 0) { aw++; na += above.get(d) - 1; }
  let total = 1;
  const altsU = divs.map(d => {
    if (!grp.get(d).length) return [[[], false]];
    const r = rankGroup(ctx, grp.get(d), x => nflDivTop(ctx, x), null);
    total *= r.orders.length;
    return r.orders.map(o => [o, r.unc]);
  });
  if (total > TIE_CAP) {     // too many division orders: over-approximate
    if (above.get(own) === 0) { let nw = 0; for (const d of divs) if (above.get(d) === 0 && grp.get(d).length) nw++; for (let p = 0; p < nw; p++) maybe.add(1 + aw + p); }
    for (let p = 0; p < G.length; p++) { const sd = 5 + na + p; maybe.add(sd <= 7 ? sd : L.MISS); }
    return { sure, maybe };
  }
  product(altsU, picks => {
    const unc = picks.some(p => p[1]);
    const od = new Map(divs.map((d, i) => [d, picks[i][0]]));
    const divRank = new Map();
    for (const o of od.values()) o.forEach((t, i) => divRank.set(t, i));
    const winAtP = new Map();
    for (const d of divs) if (above.get(d) === 0 && od.get(d).length) winAtP.set(d, od.get(d)[0]);
    const wc = x => nflWcTop(ctx, x, divRank);
    if (above.get(own) === 0 && winAtP.get(own) === ti) {
      const r = tiPositions([...winAtP.values()], wc, ti);
      for (const p of r.maybe) add(1 + aw + p, !unc && r.sure.has(p));
    } else {
      const pool = [];
      for (const d of divs) for (const t of od.get(d)) if (winAtP.get(d) !== t) pool.push(t);
      const r = tiPositions(pool, wc, ti);
      for (const p of r.maybe) { const sd = 5 + na + p; add(sd <= 7 ? sd : L.MISS, !unc && r.sure.has(p)); }
    }
  }, TIE_CAP);
  return { sure, maybe };
};

/* ------------------------------------------------------- public driver */
function mulberry32(a) {
  return function () { a |= 0; a = a + 0x6D2B79F5 | 0; let t = Math.imul(a ^ a >>> 15, 1 | a); t = t + Math.imul(t ^ t >>> 7, 61 | t) ^ t; return ((t ^ t >>> 14) >>> 0) / 4294967296; };
}
// Random complete season inside the domains, with random team strengths so
// lopsided finishes get sampled too.
function randomSeason(L, dom, rand) {
  const str = new Float64Array(L.n), sd = [0.3, 1, 3, 8][Math.floor(rand() * 4)];
  for (let t = 0; t < L.n; t++) { let u = 0; for (let k = 0; k < 6; k++) u += rand(); str[t] = (u - 3) * sd; }
  const out = new Int8Array(L.ng);
  for (let gi = 0; gi < L.ng; gi++) {
    const m = dom[gi];
    if (single(m)) { out[gi] = bitIndex(m); continue; }
    const p = 1 / (1 + Math.exp(str[L.A[gi]] - str[L.H[gi]]));
    const hw = rand() < p;
    const opts = [];
    for (let o = 0; o < L.NOUT; o++) if (m >> o & 1) {
      const isH = L.nfl ? o === 0 : o <= 2, isA = L.nfl ? o === 1 : o >= 3;
      if ((hw && isH) || (!hw && isA)) opts.push(o);
    }
    if (!opts.length) for (let o = 0; o < L.NOUT; o++) if (m >> o & 1) opts.push(o);
    if (L.nfl && (m & 4) && rand() < 0.01) { out[gi] = 2; continue; }
    out[gi] = opts[Math.floor(rand() * opts.length)];
  }
  return out;
}

// Exact achievable seeds. dom: per-game domain masks. teamsWanted: team
// indices to solve (default all). known: Map team -> Set of seeds already
// shown possible (e.g. by simulation). Returns Map team -> {seeds:Set,
// unknown:Set (left possible only because the search budget ran out)}.
function exactSeeds(L, dom, opts) {
  opts = opts || {};
  const want = opts.teams || [...Array(L.n).keys()];
  const res = new Map();
  for (let t = 0; t < L.n; t++) res.set(t, { seeds: new Set(opts.known && opts.known.get(t) || []), unknown: new Set() });
  const harvest = out => {
    for (const c of L.confs) {
      const poss = seedConference(L, out, c, null);
      for (const [t, ss] of poss) for (const s of ss) res.get(t).seeds.add(s);
    }
  };
  const rand = mulberry32(opts.seed || 12345);
  const nr = opts.randomSeasons == null ? 200 : opts.randomSeasons;
  for (let i = 0; i < nr; i++) harvest(randomSeason(L, dom, rand));
  const E = new Engine(L, dom, opts);
  E.onSeason = harvest;
  // deadline (ms since epoch): queries not reached in time stay possible
  const deadline = opts.deadline || Infinity;
  // Gate: a team whose best finish clears every rival's current total, and
  // whose worst finish stays under every rival's best, by more than `margin`
  // points (default 2 wins), is left fully open without searching. This is a
  // judgement, not a proof -- with that much room nothing is realistically
  // decided -- and it keeps the search to the part of the season that matters.
  const margin = opts.margin == null ? 4 : opts.margin;
  const [nlo, nhi] = naturalBounds(L, dom);
  const gated = ti => {
    if (margin < 0) return false;
    const others = L.confTeams[L.conf[ti]].filter(t => t !== ti);
    const maxCur = Math.max(...others.map(t => nlo[t])), minMax = Math.min(...others.map(t => nhi[t]));
    return nhi[ti] > maxCur + margin && nlo[ti] < minMax - margin;
  };
  for (const ti of want) {
    if (gated(ti)) { for (let s = 1; s <= L.MISS; s++) res.get(ti).seeds.add(s); E.stats.gated = (E.stats.gated || 0) + 1; continue; }
    for (let s = 1; s <= L.MISS; s++) {
      const r = res.get(ti);
      if (r.seeds.has(s)) continue;
      if (Date.now() > deadline) { r.seeds.add(s); r.unknown.add(s); E.stats.unknown++; E.stats.late = (E.stats.late || 0) + 1; continue; }
      E.stats.queries++;
      const tq = Date.now(); E.cnt = { l1: 0, l2: 0, sov: 0, leaves2: 0 };
      const q = E.query(ti, s, r.seeds);
      if (opts.trace) opts.trace(L.teams[ti], s, q, Date.now() - tq, E.nodes, JSON.stringify(E.cnt));
      if (q === true || q === null) { r.seeds.add(s); if (q === null) r.unknown.add(s); }
    }
  }
  res.stats = E.stats;
  return res;
}

// Helpers for callers that speak in schedule terms.
// games: [{home, away, played, winner:'home'|'away'|'tie', dec:'REG'|'OT'|'SO'}]
// forced: optional Map gameIndex -> 'home'|'away' (winner fixed, rest open).
function domainsFromSchedule(L, games, forced) {
  const dom = new Uint8Array(L.ng);
  games.forEach((g, gi) => {
    let m = L.FULL;
    if (g.played && g.winner) {
      if (L.nfl) m = g.winner === "home" ? 1 : g.winner === "away" ? 2 : 4;
      else { const d = { REG: 0, OT: 1, SO: 2 }[g.dec || "REG"]; m = 1 << ((g.winner === "home" ? 0 : 3) + d); }
    } else if (forced && forced.has(gi)) {
      const w = forced.get(gi);
      m = L.nfl ? (w === "home" ? 1 : 2) : (w === "home" ? 7 : 56);
    }
    dom[gi] = m;
  });
  return dom;
}

const api = { buildLeague, seedConference, exactSeeds, domainsFromSchedule, randomSeason, mulberry32, flowCheck, naturalBounds, single, bitIndex };
if (typeof module !== "undefined" && module.exports) module.exports = api;
root.Rules = api;
})(typeof self !== "undefined" ? self : this);
