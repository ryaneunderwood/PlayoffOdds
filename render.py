#!/usr/bin/env python3
"""Render the odds payload into a single self-contained index.html.

The data is embedded inline as JSON so the page loads straight from disk
(file://) with no web server or CORS issues.
"""

import json


def render_html(data: dict) -> str:
    payload = json.dumps(data)
    # The JS/CSS below is a static template; only the JSON payload changes.
    return TEMPLATE.replace("__PAYLOAD__", payload)


TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Playoff Odds</title>
<style>
  :root{
    --bg:#0f1420; --panel:#161d2e; --line:#26304a; --txt:#e7ecf5;
    --muted:#8a97b1; --accent:#5b8cff;
  }
  *{box-sizing:border-box}
  body{margin:0;background:var(--bg);color:var(--txt);
       font:14px/1.45 -apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif}
  header{padding:22px 20px 8px;max-width:1180px;margin:0 auto}
  h1{margin:0;font-size:24px;letter-spacing:.2px}
  .sub{color:var(--muted);margin-top:4px;font-size:13px}
  .wrap{max-width:1180px;margin:0 auto;padding:0 20px 60px}
  .tabs{display:flex;gap:8px;margin:16px 0 6px;flex-wrap:wrap}
  .tab{padding:7px 14px;border:1px solid var(--line);border-radius:999px;
       background:var(--panel);color:var(--muted);cursor:pointer;font-weight:600}
  .tab.active{color:#fff;border-color:var(--accent);
              box-shadow:0 0 0 1px var(--accent) inset}
  h2{font-size:16px;margin:26px 0 8px;color:var(--txt)}
  .conf-h{display:flex;align-items:baseline;gap:10px}
  .conf-h .note{color:var(--muted);font-size:12px;font-weight:400}
  .tablewrap{overflow-x:auto;border-radius:10px;border:1px solid var(--line)}
  table{border-collapse:collapse;width:100%;background:var(--panel)}
  th,td{padding:7px 8px;text-align:center;font-variant-numeric:tabular-nums;
        border-bottom:1px solid var(--line)}
  th{background:#10182a;color:var(--muted);font-weight:600;font-size:12px;
     position:sticky;top:0;z-index:1}
  th.sortable{cursor:pointer;user-select:none;white-space:nowrap}
  th.sortable:hover{color:var(--txt)}
  th .caret{font-size:9px;opacity:.35;margin-left:1px}
  th.sorted{color:#fff}
  th.sorted .caret{opacity:1;color:var(--accent)}
  td.team{text-align:left;font-weight:700;white-space:nowrap}
  /* keep the team column visible while the wide seed grid scrolls */
  th.teamh,td.team{position:sticky;left:0;z-index:2;background:var(--panel)}
  th.teamh{z-index:6;background:#10182a;text-align:left}
  td.team .dtag{color:var(--muted);font-weight:600;font-size:11px;margin-left:6px}
  td.lbl{text-align:left;color:var(--muted)}
  td.rec{font-weight:700;white-space:nowrap}
  td.rec.zero{color:var(--muted);font-weight:400}
  .elod{font-size:10px;font-weight:700;margin-left:3px}
  .elod.up{color:#4ade80}.elod.down{color:#f87171}
  .sub .live{color:#4ade80;font-weight:700}
  .sub .stamp{color:var(--muted);opacity:.8}
  /* survivor pool */
  .surv{background:var(--panel);border:1px solid var(--line);border-radius:10px;
        margin:0 0 22px;overflow:hidden}
  .surv-h{display:flex;flex-wrap:wrap;align-items:baseline;gap:6px 14px;
          padding:10px 14px;background:#10182a;border-bottom:1px solid var(--line)}
  .surv-h b{font-size:14px;color:#fff}
  .surv-h .st{font-size:12px;color:var(--muted)}
  .surv-h .st .ok{color:#4ade80;font-weight:700}
  .surv-h .st .bad{color:#f87171;font-weight:700}
  .surv-h .st .num{color:#fff;font-weight:700}
  .surv table{border-radius:0}
  .surv th{position:static}
  .surv td{text-align:left;padding:6px 10px}
  .surv th{text-align:left;padding:6px 10px}
  .surv td.n{text-align:right;font-weight:700;white-space:nowrap}
  .surv th.n{text-align:right}
  .surv tr.next td{background:#16243f}
  .surv tr.done td{color:var(--muted)}
  .surv tr.done td.pick{color:var(--txt)}
  .surv td.pick{font-weight:800;white-space:nowrap}
  .surv .badge{display:inline-block;font-size:10px;font-weight:800;border-radius:5px;
               padding:1px 5px;margin-left:6px;vertical-align:middle;letter-spacing:.3px}
  .surv .badge.next{background:var(--accent);color:#fff}
  .surv .badge.ok{color:#4ade80;border:1px solid #1f7a4d}
  .surv .badge.bad{color:#f87171;border:1px solid #9b3030}
  .surv .badge.warn{color:#ffd16b;border:1px solid #5a4a1e}
  .surv .alt{display:inline-block;font-size:11px;color:var(--muted);margin-right:9px;
             white-space:nowrap}
  .surv .alt.free{color:var(--txt)}
  .surv .alt i{font-style:normal;opacity:.6;font-size:10px}
  .surv .note{padding:8px 14px;color:var(--muted);font-size:11px;border-top:1px solid var(--line)}
  .surv .note code{background:#0d1322;padding:1px 5px;border-radius:4px}
  .sflag{display:inline-block;font-size:10px;font-weight:800;color:#fff;background:var(--accent);
         border-radius:5px;padding:0 5px;margin-left:6px;vertical-align:middle}
  @media (max-width:640px){ .surv .alts{display:none} }
  /* results */
  .res{display:grid;grid-template-columns:1fr 60px 40px 60px 1fr 74px;align-items:center;
       gap:10px;padding:7px 12px;border-bottom:1px solid var(--line)}
  .res:last-child{border-bottom:none}
  .res .away{text-align:right}.res .home{text-align:left}
  .res .w{font-weight:800;color:#fff}.res .l{color:var(--muted)}
  .res .sc{font-weight:800;font-variant-numeric:tabular-nums;text-align:center}
  .res .sc.l{font-weight:600}
  .res .pre{font-size:11px;color:var(--muted);font-variant-numeric:tabular-nums}
  .res .tag{font-size:10px;font-weight:800;text-align:center;border-radius:5px;padding:2px 4px}
  .res .tag.upset{color:#ffd16b;border:1px solid #5a4a1e;background:#2a2410}
  .res .tag.chalk{color:var(--muted);border:1px solid var(--line)}
  .reswk{background:var(--panel);border:1px solid var(--line);border-radius:10px;
         overflow:hidden;margin-bottom:14px}
  .reswk h3{margin:0;padding:8px 12px;font-size:13px;color:var(--muted);
            background:#10182a;border-bottom:1px solid var(--line);
            display:flex;justify-content:space-between}
  .reswk h3 .n{font-weight:400}
  @media (max-width:640px){ .res{grid-template-columns:1fr 44px 28px 44px 1fr;gap:6px} .res .tag{display:none} }
  tr.divrow td{background:#0d1322;color:var(--muted);text-align:left;
               font-weight:700;font-size:12px;letter-spacing:.4px}
  .pct{font-weight:600}
  .dim{color:#5d6680}
  td.elim{color:#6b7488;font-weight:700}
  td.clinch{color:#dce9ff;font-weight:800}
  .big-sym{font-size:24px}
  .sep{border-left:2px solid var(--line)}
  .swatch{display:inline-block;width:10px;height:10px;border-radius:2px;
          margin-right:6px;vertical-align:middle}
  /* upcoming games */
  .wk{margin:18px 0}
  .wk h3{margin:0 0 8px;font-size:14px;color:var(--muted)}
  .game{display:grid;grid-template-columns:1fr 56px 90px 56px 1fr;
        align-items:center;gap:10px;padding:6px 10px;border:1px solid var(--line);
        border-radius:8px;background:var(--panel);margin-bottom:6px}
  .game .away{text-align:right;font-weight:700}
  .game .home{text-align:left;font-weight:700}
  .game .p{font-weight:700}
  .game .mid{display:flex;flex-direction:column;gap:3px}
  .spread{font-size:10px;color:var(--muted);text-align:center;
          font-variant-numeric:tabular-nums;letter-spacing:.2px}
  .vflag{display:inline-block;font-size:10px;font-weight:800;color:#ffd16b;
         border:1px solid #5a4a1e;background:#2a2410;border-radius:5px;
         padding:0 4px;margin-left:6px;vertical-align:middle}
  .daygrp{color:var(--muted);font-size:12px;font-weight:700;margin:12px 0 5px;
          text-transform:uppercase;letter-spacing:.5px}
  .bar{height:8px;border-radius:5px;background:#2a3450;overflow:hidden;display:flex}
  .bar>i{display:block;height:100%}
  .bar>i.away{background:#7c89a8}
  .bar>i.home{background:var(--accent)}
  .foot{color:var(--muted);font-size:12px;margin-top:30px;line-height:1.6}
  code{background:#0d1322;padding:1px 5px;border-radius:4px;color:#cdd7ee}
  td.team.clickable{cursor:pointer}
  td.team.clickable:hover{color:var(--accent);text-decoration:underline}
  /* modal */
  .modal-back{position:fixed;inset:0;background:rgba(5,8,16,.72);display:flex;
    align-items:flex-start;justify-content:center;padding:30px 14px;z-index:50;
    overflow:auto}
  .modal{background:var(--panel);border:1px solid var(--line);border-radius:14px;
    width:min(720px,100%);box-shadow:0 24px 60px rgba(0,0,0,.5)}
  .modal-h{display:flex;align-items:center;justify-content:space-between;
    padding:16px 18px;border-bottom:1px solid var(--line)}
  .modal-h h2{margin:0;font-size:18px}
  .modal-h .x{cursor:pointer;color:var(--muted);font-size:22px;line-height:1;
    border:none;background:none;padding:4px 8px}
  .modal-h .x:hover{color:#fff}
  .modal-b{padding:16px 18px}
  .odds-grid{display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin-bottom:6px}
  .odds-card{background:#0d1322;border:1px solid var(--line);border-radius:9px;
    padding:10px 12px;text-align:center}
  .odds-card .lab{color:var(--muted);font-size:11px;text-transform:uppercase;
    letter-spacing:.4px}
  .odds-card .val{font-size:22px;font-weight:800;margin-top:3px}
  .delta{font-size:12px;font-weight:700;margin-left:5px}
  .delta.up{color:#4ade80}.delta.down{color:#f87171}.delta.zero{color:var(--muted)}
  .seedgrid{display:flex;gap:4px;margin:8px 0 4px}
  .seedgrid .sc{flex:1;border:1px solid var(--line);border-radius:6px;
    padding:6px 2px 5px;text-align:center;min-width:0}
  .seedgrid .sc .sd{font-size:10px;color:var(--muted);font-weight:700;
    letter-spacing:.3px}
  .seedgrid .sc .sv{font-size:13px;font-weight:800;color:#fff;margin-top:2px}
  .ctrlbar{display:flex;align-items:center;justify-content:space-between;
    margin:14px 0 8px;color:var(--muted);font-size:12px}
  .ctrlbar button{background:#23304d;border:1px solid var(--line);color:var(--txt);
    border-radius:7px;padding:5px 10px;cursor:pointer;font-weight:600}
  .ctrlbar button:hover{border-color:var(--accent)}
  .schrow{display:grid;grid-template-columns:46px 1fr 64px 150px;align-items:center;
    gap:10px;padding:6px 8px;border:1px solid var(--line);border-radius:8px;
    margin-bottom:5px;background:#0f1626}
  .schrow .wk{color:var(--muted);font-size:12px;margin:0}
  .schrow .opp{font-weight:700}
  .schrow .opp .ha{color:var(--muted);font-weight:400}
  .schrow .wp{text-align:right;color:var(--muted);font-variant-numeric:tabular-nums}
  .schrow.played{opacity:.65}
  .toggle{display:flex;gap:0;border:1px solid var(--line);border-radius:7px;overflow:hidden}
  .toggle button{flex:1;border:none;background:#16203a;color:var(--muted);
    padding:5px 0;cursor:pointer;font-size:11px;font-weight:700}
  .toggle button:not(:last-child){border-right:1px solid var(--line)}
  .toggle button.on-win{background:#1f7a4d;color:#fff}
  .toggle button.on-loss{background:#9b3030;color:#fff}
  .toggle button.on-auto{background:#33406a;color:#fff}
  .resultpill{font-size:11px;font-weight:700;text-align:center;border-radius:6px;
    padding:5px 0;background:#16203a;color:var(--muted)}
  .calc{color:var(--accent);font-size:13px;font-weight:600;padding:24px 0;text-align:center}
  #calcbadge{position:absolute;top:14px;right:52px;background:var(--accent);color:#fff;
    font-size:11px;font-weight:700;padding:4px 9px;border-radius:999px;opacity:.92}
  .modal{position:relative}
</style>
</head>
<body>
<header>
  <h1 id="title">Playoff Odds</h1>
  <div class="sub" id="subtitle"></div>
</header>
<div class="wrap">
  <div class="tabs" id="tabs"></div>
  <div id="view"></div>
  <div class="foot" id="foot"></div>
</div>

<div id="modal" class="modal-back" style="display:none">
  <div class="modal"><div id="modal-body"></div></div>
</div>

<script>
const DATA = __PAYLOAD__;

const NAMES = {
  ARI:"Cardinals",ATL:"Falcons",BAL:"Ravens",BUF:"Bills",CAR:"Panthers",
  CHI:"Bears",CIN:"Bengals",CLE:"Browns",DAL:"Cowboys",DEN:"Broncos",
  DET:"Lions",GB:"Packers",HOU:"Texans",IND:"Colts",JAX:"Jaguars",
  KC:"Chiefs",LAC:"Chargers",LA:"Rams",LV:"Raiders",MIA:"Dolphins",
  MIN:"Vikings",NE:"Patriots",NO:"Saints",NYG:"Giants",NYJ:"Jets",
  PHI:"Eagles",PIT:"Steelers",SF:"49ers",SEA:"Seahawks",TB:"Buccaneers",
  TEN:"Titans",WAS:"Commanders"
};
function tname(t){return NAMES[t] ? t+" "+NAMES[t] : t;}

// Perceptual heat scale. The old linear-alpha blue made 5% and 30% look
// nearly identical (both faint); this expands the low/mid range and shifts hue
// from a muted blue (long shot) toward bright teal/green (locked in) with a
// visible floor, so a cell's odds read at a glance without reading the number.
function heat(p){
  if(p<=0) return "transparent";
  const t = Math.min(1, Math.max(0, p/100));
  const e = Math.pow(t, 0.6);          // expand the low end
  const hue = 222 - 70*e;              // 222 (blue) -> 152 (green)
  const light = 27 + 26*e;             // 27% -> 53%
  const alpha = 0.34 + 0.62*e;         // visible floor so 1% still tints
  return `hsla(${hue.toFixed(0)},72%,${light.toFixed(0)}%,${alpha.toFixed(3)})`;
}
// Display token honoring mathematical feasibility:
//   X      -> impossible (no scenario, simulated or contrived, achieves it)
//   ^      -> mathematically guaranteed (the only achievable outcome)
//   <0.1   -> possible but never came up in the trials (sub-0.1%)
//   >99.9  -> all-but-certain in trials, yet not mathematically clinched
//   else   -> the rounded probability, never rounded to the 0/100 extremes
function token(prob, st){
  if(!st.poss) return "X";
  if(st.guar)  return "^";
  if(prob < 0.1)  return "<0.1";
  if(prob > 99.9) return ">99.9";
  return prob.toFixed((prob<10 || prob>99) ? 1 : 0);
}
function statusSet(ach){
  const set = new Set(ach), arr = ach;
  const MISS = DATA.seeds_per_conf + 1, DWS = DATA.division_winner_seeds;
  return {
    seed:  s => ({poss:set.has(s), guar:set.size===1 && set.has(s)}),
    miss:  {poss:set.has(MISS), guar:set.size===1 && set.has(MISS)},
    make:  {poss:arr.some(s=>s<=DATA.seeds_per_conf), guar:!set.has(MISS)},
    div:   {poss:arr.some(s=>s<=DWS), guar:Math.max(...arr)<=DWS},
    brkt:  {poss:arr.some(s=>s<=DATA.seeds_per_conf), guar:false},
  };
}
function pcell(prob, st, extra){
  const tk = token(prob, st);
  let bg, cls;
  if(tk==="X"){ bg="transparent"; cls="elim"; }
  else if(tk==="^"){ bg=heat(100); cls="clinch"; }
  else if(tk==="<0.1"){ bg=heat(0.4); cls="dim"; }
  else if(tk===">99.9"){ bg=heat(99.9); cls="pct"; }
  else { bg=heat(prob); cls = prob<0.05 ? "dim" : "pct"; }
  return `<td class="${cls}${extra?" "+extra:""}" style="background:${bg}">${tk}</td>`;
}

const rowsByTeam = {};
DATA.rows.forEach(r=>rowsByTeam[r.team]=r);

// null => grouped by division (default); else flat-sorted by {key,dir}.
let sortState = null;
function sortVal(r,key){
  if(key==="elo") return r.elo;
  if(key==="rec") { const g=r.wins+r.losses+r.ties; return g ? (r.wins+0.5*r.ties)/g + r.wins*1e-4 : -1; }
  if(key==="pw")  return r.proj_wins;
  if(key==="miss")return r.miss;
  if(key==="mk")  return r.make_playoffs;
  if(key==="wd")  return r.win_div;
  if(key==="wc")  return r.win_conf;
  if(key==="ti")  return r.win_title;
  if(key[0]==="s")return r.seed_probs[(+key.slice(1))-1];
  return 0;
}

function recStr(r){ return `${r.wins}-${r.losses}${r.ties?"-"+r.ties:""}`; }
// Elo movement since the preseason (results to date), shown next to the rating.
function eloDelta(r){
  const d = r.elo - (r.elo_pre==null ? r.elo : r.elo_pre);
  if(!d) return "";
  return `<span class="elod ${d>0?"up":"down"}" title="vs preseason ${r.elo_pre}">${d>0?"▲":"▼"}${Math.abs(d)}</span>`;
}
function teamRow(r, withTag){
  const S = statusSet(r.ach);
  const tag = withTag ? `<span class="dtag">${r.div.split(" ")[1]||r.div}</span>` : "";
  let h = "<tr>";
  h += `<td class="team clickable" data-team="${r.team}">${tname(r.team)}${tag}</td>`;
  h += `<td class="rec${(r.wins+r.losses+r.ties)?"":" zero"}">${recStr(r)}</td>`;
  h += `<td class="dim">${r.elo}${eloDelta(r)}</td>`;
  h += `<td>${r.proj_wins.toFixed(1)}</td>`;
  r.seed_probs.forEach((p,i)=> h += pcell(p, S.seed(i+1), i===0?"sep":"") );
  h += pcell(r.miss, S.miss, "sep");
  h += pcell(r.make_playoffs, S.make, "sep");
  h += pcell(r.win_div, S.div);
  h += pcell(r.win_conf, S.brkt);
  h += pcell(r.win_title, S.brkt);
  return h + "</tr>";
}

function seedTable(conf){
  const S = DATA.seeds_per_conf;
  const car = k => `<span class="caret">${sortState&&sortState.key===k?(sortState.dir<0?"▼":"▲"):"▾"}</span>`;
  const scl = k => "sortable"+(sortState&&sortState.key===k?" sorted":"");
  const th  = (k,l,extra)=>`<th class="${scl(k)}${extra?" "+extra:""}" data-sk="${k}">${l}${car(k)}</th>`;

  let h = "<table><thead><tr>";
  h += `<th class="teamh sortable${sortState?"":" sorted"}" data-sk="grouped">Team</th>`;
  h += th("rec","W-L") + th("elo","Elo") + th("pw","Proj W");
  for(let s=1;s<=S;s++) h += th("s"+s, "#"+s, s===1?"sep":"");
  h += th("miss","Miss","sep") + th("mk","Playoffs","sep");
  h += th("wd","Win Div") + th("wc","Win Conf") + th("ti","Title");
  h += "</tr></thead><tbody>";

  if(sortState){
    // flat: every team in the conference, sorted by the chosen column
    const ts = DATA.rows.filter(r=>r.conf===conf)
                 .sort((a,b)=>(sortVal(b,sortState.key)-sortVal(a,sortState.key))*-sortState.dir
                              || b.proj_wins-a.proj_wins);
    ts.forEach(r=> h += teamRow(r, true));
  } else {
    // grouped by division; teams within a division by make-playoffs then wins
    Object.keys(DATA.divisions).filter(d=>d.split(" ")[0]===conf).forEach(d=>{
      h += `<tr class="divrow"><td colspan="${S+9}">${d}</td></tr>`;
      DATA.divisions[d].map(t=>rowsByTeam[t])
        .sort((a,b)=>b.make_playoffs-a.make_playoffs||b.proj_wins-a.proj_wins)
        .forEach(r=> h += teamRow(r, false));
    });
  }
  h += "</tbody></table>";
  return `<div class="tablewrap">${h}</div>`;
}

function seedsView(){
  let h = "";
  DATA.conferences.forEach(c=>{
    h += `<div class="conf-h"><h2>${c}</h2><span class="note">probability (%) of each playoff seed &middot; <b>click a team</b> to explore its schedule &middot; <b>click a column header</b> to sort (click <b>Team</b> to regroup by division)</span></div>`;
    h += seedTable(c);
  });
  h += `<div style="margin-top:10px;color:var(--muted);font-size:12px">
    <span class="swatch" style="background:${heat(8)}"></span>low
    <span class="swatch" style="background:${heat(45)};margin-left:10px"></span>mid
    <span class="swatch" style="background:${heat(90)};margin-left:10px"></span>high
    &nbsp;&middot;&nbsp; <b>^</b> clinched &nbsp; <b>X</b> eliminated &nbsp;
    <b>&lt;0.1</b> possible but &lt;0.1% &nbsp; <b>&gt;99.9</b> near-certain, not clinched</div>`;
  return h;
}

// Implied point spread from the Elo edge (~25 Elo per point, the standard
// conversion). Returns the favorite's line, e.g. "KC −6.5" (or "PK" pick'em).
function impliedSpread(g){
  const eh = DATA.ratings[g.home], ea = DATA.ratings[g.away];
  if(eh==null || ea==null) return "";
  const H = g.neutral ? 0 : DATA.home_field;
  const homeMargin = (eh - ea + H) / 25;
  const num = Math.abs(homeMargin);
  if(num < 0.25) return "PK";
  const fav = homeMargin >= 0 ? g.home : g.away;
  return `${fav} −${(Math.round(num*2)/2).toFixed(1)}`;
}
// Vegas disagreement: present only if the payload carried moneylines (future
// seasons have none until books post lines, so this stays dormant until then).
function vegasFlag(g){
  if(g.home_ml==null || g.away_ml==null) return "";
  const vegasFav = g.home_ml < g.away_ml ? "home" : (g.away_ml < g.home_ml ? "away" : null);
  const modelFav = g.home_wp >= g.away_wp ? "home" : "away";
  return (vegasFav && vegasFav!==modelFav) ? ` <span class="vflag" title="model disagrees with the Vegas favorite">⚡ UPSET</span>` : "";
}
function gameRow(g){
  const hp = g.home_wp, ap = g.away_wp, favHome = hp>=ap;
  const sp = impliedSpread(g);
  const sflag = t => SURV_PICK[g.week]===t ? ` <span class="sflag" title="survivor pick this week">★ SURVIVOR</span>` : "";
  return `<div class="game">
    <div class="away">${sflag(g.away)}${tname(g.away)}</div>
    <div class="p" style="text-align:right;color:${!favHome?'#fff':'var(--muted)'}">${ap.toFixed(0)}%</div>
    <div class="mid"><div class="bar"><i class="away" style="width:${ap}%"></i><i class="home" style="width:${hp}%"></i></div>
      ${sp?`<div class="spread">${sp}</div>`:""}</div>
    <div class="p" style="color:${favHome?'#fff':'var(--muted)'}">${hp.toFixed(0)}%</div>
    <div class="home">${tname(g.home)}${g.neutral?' <span class="dim">(N)</span>':''} <span class="dim">(H)</span>${vegasFlag(g)}${sflag(g.home)}</div>
  </div>`;
}
// Survivor pool: picks made so far, then the optimal order for the remaining
// weeks (computed server-side as an assignment problem, re-solved on every
// regeneration so it tracks the latest ratings and results).
const SURV = DATA.survivor || null;
const SURV_PICK = {};   // week -> planned/made pick, for badging the game list
if(SURV){
  SURV.history.forEach(e=>{ if(e.team) SURV_PICK[e.week]=e.team; });
  SURV.plan.forEach(e=> SURV_PICK[e.week]=e.team);
}
function survivorPanel(){
  if(!SURV) return "";
  const vs = e => e.neutral ? "vs" : (e.home ? "vs" : "@");
  const badge = (cls, txt) => `<span class="badge ${cls}">${txt}</span>`;
  const status = {survived:["ok","SURVIVED"], eliminated:["bad","ELIMINATED"], tie:["bad","TIE"],
                  pending:["warn","IN PLAY"], missing:["warn","NO PICK RECORDED"], invalid:["bad","ON BYE"]};
  let rows = "";
  SURV.history.forEach(e=>{
    const [c,t] = status[e.status] || ["warn", e.status.toUpperCase()];
    rows += `<tr class="done"><td class="n">Wk ${e.week}</td>
      <td class="pick">${e.team ? tname(e.team) : "&mdash;"}${badge(c,t)}</td>
      <td>${e.opp ? vs(e)+" "+tname(e.opp) : ""}</td>
      <td class="n">${e.p!=null ? e.p.toFixed(0)+"%" : ""}</td><td class="n"></td><td class="alts"></td></tr>`;
  });
  SURV.plan.forEach((e,i)=>{
    const alts = e.alts.map(a=>`<span class="alt${a.planned?"":" free"}" title="${a.planned?"needed later in the plan":"not used elsewhere in the plan"}">${a.team} ${a.p.toFixed(0)}%${a.planned?" <i>(wk later)</i>":""}</span>`).join("");
    rows += `<tr class="${i===0?"next":""}"><td class="n">Wk ${e.week}</td>
      <td class="pick">${tname(e.team)}${i===0?badge("next","NEXT PICK"):""}</td>
      <td>${vs(e)} ${tname(e.opp)}</td>
      <td class="n">${e.p.toFixed(0)}%</td>
      <td class="n" title="probability of surviving through this week">${e.cum.toFixed(1)}%</td>
      <td class="alts">${alts}</td></tr>`;
  });
  const made = SURV.history.filter(e=>e.status==="survived").length;
  const state = SURV.alive
    ? `<span class="ok">Alive</span>${made?" through Week "+SURV.history[SURV.history.length-1].week:""}`
    : `<span class="bad">Eliminated</span>`;
  const lift = SURV.p_greedy>0 ? (SURV.p_season/SURV.p_greedy).toFixed(1)+"&times;" : "";
  return `<div class="surv">
    <div class="surv-h"><b>Survivor pool</b>
      <span class="st">${state} &middot; ${SURV.weeks_left} weeks to go &middot;
        survive the season: <span class="num">${SURV.p_season.toFixed(1)}%</span> with this order
        (vs ${SURV.p_greedy.toFixed(1)}% taking each week's biggest favorite${lift?", "+lift+" better":""})</span>
    </div>
    <div class="tablewrap" style="border:none;border-radius:0"><table><thead><tr>
      <th class="n">Week</th><th>Pick</th><th>Opponent</th><th class="n">Win</th><th class="n">Survive thru</th><th class="alts">Other options this week</th>
    </tr></thead><tbody>${rows}</tbody></table></div>
    <div class="note">Order maximizes the product of the picks' win probabilities with no team reused (solved exactly, not greedily), and is re-optimized every time the page is regenerated.
      After you lock a pick, record it so the plan stops reusing that team: <code>python sports_elo.py --pick ${SURV.next?SURV.next.week+":"+SURV.next.team:"WEEK:TEAM"}</code> (or edit <code>survivor.json</code>).</div>
  </div>`;
}
function gamesView(){
  if(!DATA.upcoming.length) return survivorPanel() + "<p>No upcoming games.</p>";
  let h = survivorPanel();
  DATA.upcoming.forEach(w=>{
    h += `<div class="wk"><h3>Week ${w.week}</h3>`;
    // group by kickoff day when the payload carries it; otherwise one flat list
    const hasDay = w.games.some(g=>g.weekday || g.gameday);
    if(hasDay){
      const order = ["Thursday","Friday","Saturday","Sunday","Monday","Tuesday","Wednesday"];
      const groups = {};
      w.games.forEach(g=>{ const k=g.weekday||g.gameday||"TBD"; (groups[k]=groups[k]||[]).push(g); });
      Object.keys(groups).sort((a,b)=>{
        const ia=order.indexOf(a), ib=order.indexOf(b);
        return (ia<0?99:ia)-(ib<0?99:ib);
      }).forEach(day=>{
        h += `<div class="daygrp">${day}</div>`;
        groups[day].forEach(g=> h += gameRow(g));
      });
    } else {
      w.games.forEach(g=> h += gameRow(g));
    }
    h += "</div>";
  });
  return h;
}

// Completed games by week (latest first), with the model's pre-kickoff
// win probability and whether the favorite held. Derived from the schedule
// payload so it always matches what the Elo engine actually consumed.
function resultsView(){
  const played = DATA.schedule.filter(g=>g.played);
  if(!played.length) return "<p>No games have been played yet.</p>";
  const byWk = {};
  played.forEach(g=>(byWk[g.week]=byWk[g.week]||[]).push(g));
  let h = "";
  Object.keys(byWk).map(Number).sort((a,b)=>b-a).forEach(wk=>{
    const gs = byWk[wk];
    const total = DATA.schedule.filter(g=>g.week===wk).length;
    let favHits=0, favTot=0;
    gs.forEach(g=>{ if(g.winner!=="tie"){ favTot++; if((g.p_home>=0.5)===(g.winner==="home")) favHits++; } });
    h += `<div class="reswk"><h3><span>Week ${wk}</span><span class="n">${gs.length}${gs.length<total?" of "+total:""} played &middot; model favorite won ${favHits}/${favTot}</span></h3>`;
    gs.forEach(g=>{
      const hw = g.winner==="home", aw = g.winner==="away", tie = g.winner==="tie";
      const favHome = g.p_home>=0.5;
      const upset = !tie && (favHome!==hw);
      const hp = Math.round(g.p_home*100), ap = 100-hp;
      h += `<div class="res">
        <div class="away ${aw?"w":"l"}">${tname(g.away)}<div class="pre">${ap}%</div></div>
        <div class="sc ${aw?"w":"l"}">${g.away_score}</div>
        <div class="pre" style="text-align:center">${tie?"T":"@"}</div>
        <div class="sc ${hw?"w":"l"}">${g.home_score}</div>
        <div class="home ${hw?"w":"l"}">${tname(g.home)}${g.neutral?' <span class="dim">(N)</span>':''}<div class="pre">${hp}%</div></div>
        <div class="tag ${upset?"upset":"chalk"}">${tie?"TIE":(upset?"UPSET":"FAVORITE")}</div>
      </div>`;
    });
    h += "</div>";
  });
  return h;
}

/* ===================================================================== *
 *  In-browser Monte Carlo engine (ports sports_elo.py to JS so toggling
 *  a game re-simulates the season live, with no server).
 * ===================================================================== */
const TEAMS = DATA.teams;
const TIDX = {}; TEAMS.forEach((t,i)=>TIDX[t]=i);
const NT = TEAMS.length;
const RAT = DATA.ratings, HF = DATA.home_field, MEAN = DATA.mean;
const DWS = DATA.division_winner_seeds, WCS = DATA.wildcard_seeds;
const NSEED = DATA.seeds_per_conf, BYES = DATA.byes;
const CONFS = DATA.conferences;
const TEAM_CONF = {};
Object.keys(DATA.divisions).forEach(d=>DATA.divisions[d].forEach(t=>TEAM_CONF[t]=d.split(" ")[0]));

// Per-conference structure as team indices.
const CONF_DIVS = {}, CONF_IDX = {};
CONFS.forEach(c=>{
  CONF_DIVS[c]=[]; CONF_IDX[c]=[];
  Object.keys(DATA.divisions).filter(d=>d.split(" ")[0]===c).forEach(d=>{
    const arr = DATA.divisions[d].map(t=>TIDX[t]);
    CONF_DIVS[c].push(arr); CONF_IDX[c].push(...arr);
  });
});

// ---- static league structure (mirrors seeding.py League) ----
const TEAMDIV=[], TEAMCONFI=[], DIV_TEAMS={}, CONF_DIV_LABELS={};
TEAMS.forEach((t,i)=>{ for(const d in DATA.divisions){ if(DATA.divisions[d].includes(t)){ TEAMDIV[i]=d; TEAMCONFI[i]=d.split(" ")[0]; } } });
for(const d in DATA.divisions){ DIV_TEAMS[d]=DATA.divisions[d].map(t=>TIDX[t]); const c=d.split(" ")[0]; (CONF_DIV_LABELS[c]=CONF_DIV_LABELS[c]||[]).push(d); }

const NG=DATA.schedule.length;
const GAMES=DATA.schedule.map(g=>{ const hi=TIDX[g.home], ai=TIDX[g.away];
  return { id:g.id, hi, ai, p:g.p_home, played:g.played,
    fixed: g.played&&g.winner==="home"?hi : g.played&&g.winner==="away"?ai : -1,
    isDiv: TEAMDIV[hi]===TEAMDIV[ai], isConf: TEAMCONFI[hi]===TEAMCONFI[ai] }; });
const OPENG=[]; GAMES.forEach((g,gi)=>{ if(g.fixed<0) OPENG.push(gi); });

const TEAMGAMES=[], DIVGAMES=[], CONFGAMES=[], OPPSET=[], TOTG=new Int32Array(NT), PAIRMAP=new Map();
for(let i=0;i<NT;i++){ TEAMGAMES.push([]); DIVGAMES.push([]); CONFGAMES.push([]); OPPSET.push(new Set()); }
GAMES.forEach((g,gi)=>{ const h=g.hi,a=g.ai;
  TEAMGAMES[h].push([gi,a]); TEAMGAMES[a].push([gi,h]);
  OPPSET[h].add(a); OPPSET[a].add(h); TOTG[h]++; TOTG[a]++;
  if(g.isDiv){ DIVGAMES[h].push(gi); DIVGAMES[a].push(gi); }
  if(g.isConf){ CONFGAMES[h].push(gi); CONFGAMES[a].push(gi); }
  const k=h<a?h*NT+a:a*NT+h; if(!PAIRMAP.has(k)) PAIRMAP.set(k,[]); PAIRMAP.get(k).push(gi); });
function PAIR(a,b){ return PAIRMAP.get(a<b?a*NT+b:b*NT+a)||[]; }

// ---- NFL tiebreaker criteria (mirror seeding.py; null = not applicable) ----
function h2hBest(winners,t,group){ let w=0,g=0; for(const o of group){ if(o===t) continue; for(const gi of PAIR(t,o)){ g++; if(winners[gi]===t) w++; } } return g?w/g:null; }
function h2hSweep(winners,t,group){ let tot=0,wins=0; for(const o of group){ if(o===t) continue; const pl=PAIR(t,o); if(!pl.length) return null; for(const gi of pl){ tot++; if(winners[gi]===t) wins++; } } if(!tot) return null; if(wins===tot) return 1; if(wins===0) return 0; return null; }
function divPct(dW,t){ const g=DIVGAMES[t].length; return g?dW[t]/g:0; }
function confPct(cW,t){ const g=CONFGAMES[t].length; return g?cW[t]/g:0; }
function commonPct(winners,group,t,minG){ let inter=null; for(const x of group){ if(inter===null) inter=new Set(OPPSET[x]); else { const s=OPPSET[x]; inter=new Set([...inter].filter(y=>s.has(y))); } } if(!inter||!inter.size) return null; let w=0,g=0; for(const [gi,o] of TEAMGAMES[t]){ if(inter.has(o)){ g++; if(winners[gi]===t) w++; } } if(g<minG||g===0) return null; return w/g; }
function sov(winners,W,t){ let tw=0,tg=0; for(const [gi,o] of TEAMGAMES[t]){ if(winners[gi]===t){ tw+=W[o]; tg+=TOTG[o]; } } return tg?tw/tg:0; }
function sos(winners,W,t){ let tw=0,tg=0; for(const [gi,o] of TEAMGAMES[t]){ tw+=W[o]; tg+=TOTG[o]; } return tg?tw/tg:0; }
function filterMax(group,fn){ const v=group.map(fn); let mx=-Infinity,any=false; for(const x of v){ if(x!=null){ any=true; if(x>mx) mx=x; } } if(!any) return group; const keep=group.filter((t,i)=>v[i]!=null&&v[i]===mx); return keep.length?keep:group; }
function pickTopDivision(winners,dW,cW,W,group){ let cur=group.slice(); const L=[t=>h2hBest(winners,t,cur),t=>divPct(dW,t),t=>commonPct(winners,cur,t,0),t=>confPct(cW,t),t=>sov(winners,W,t),t=>sos(winners,W,t)]; for(const c of L){ cur=filterMax(cur,c); if(cur.length===1) return cur[0]; } return cur[(Math.random()*cur.length)|0]; }
function pickTopWildcard(winners,dW,cW,W,group){ let cur=group.slice();
  if(cur.length>2){ const bd={}; cur.forEach(t=>{ (bd[TEAMDIV[t]]=bd[TEAMDIV[t]]||[]).push(t); }); const red=[]; for(const d in bd){ const m=bd[d]; red.push(m.length===1?m[0]:pickTopDivision(winners,dW,cW,W,m)); } cur=red; if(cur.length===1) return cur[0]; }
  const L=[t=> cur.length>2?h2hSweep(winners,t,cur):h2hBest(winners,t,cur),t=>confPct(cW,t),t=>commonPct(winners,cur,t,4),t=>sov(winners,W,t),t=>sos(winners,W,t)]; for(const c of L){ cur=filterMax(cur,c); if(cur.length===1) return cur[0]; } return cur[(Math.random()*cur.length)|0]; }
function orderByRecord(W,teams,pickTop){ const rem=teams.slice(),out=[]; while(rem.length){ let best=-Infinity; for(const t of rem) if(W[t]>best) best=W[t]; const tied=rem.filter(t=>W[t]===best); const win=tied.length===1?tied[0]:pickTop(tied); out.push(win); rem.splice(rem.indexOf(win),1); } return out; }
function seedConference(conf,winners,W,dW,cW){ const pwc=g=>pickTopWildcard(winners,dW,cW,W,g);
  const divW=[]; for(const d of CONF_DIV_LABELS[conf]){ const mem=DIV_TEAMS[d]; let best=-Infinity; for(const t of mem) if(W[t]>best) best=W[t]; const tied=mem.filter(t=>W[t]===best); divW.push(tied.length===1?tied[0]:pickTopDivision(winners,dW,cW,W,tied)); }
  const ranked=orderByRecord(W,divW,pwc); const seeds={}; ranked.forEach((t,i)=>seeds[t]=i+1);
  const dwset=new Set(divW); const nonwin=CONF_IDX[conf].filter(t=>!dwset.has(t)); const wc=orderByRecord(W,nonwin,pwc);
  for(let i=0;i<WCS;i++) seeds[wc[i]]=DWS+1+i; return seeds; }
function recordsFrom(winners){ const W=new Float64Array(NT),dW=new Float64Array(NT),cW=new Float64Array(NT); for(let gi=0;gi<NG;gi++){ const w=winners[gi]; W[w]++; if(GAMES[gi].isDiv) dW[w]++; if(GAMES[gi].isConf) cW[w]++; } return [W,dW,cW]; }

function winProbElo(ta, tb, homeForA){
  const ra = RAT[ta]!=null?RAT[ta]:MEAN, rb = RAT[tb]!=null?RAT[tb]:MEAN;
  const H = homeForA?HF:0;
  return 1/(1+Math.pow(10, -((ra-rb+H)/400)));
}

// forced: {gameId: 'home'|'away'} -> returns {team: oddsObj}
// Each simulated season is seeded with the real NFL tiebreakers (seedConference).
function simulate(nSims, forced){
  forced = forced || {};
  const seedHits=[]; for(let i=0;i<NT;i++) seedHits.push(new Float64Array(NSEED+1));
  const makeP=new Float64Array(NT), winDiv=new Float64Array(NT);
  const confCh=new Float64Array(NT), title=new Float64Array(NT);
  const winners=new Int32Array(NG);
  for(let gi=0;gi<NG;gi++) if(GAMES[gi].fixed>=0) winners[gi]=GAMES[gi].fixed;

  for(let s=0;s<nSims;s++){
    for(let k=0;k<OPENG.length;k++){ const gi=OPENG[k], g=GAMES[gi], f=forced[g.id];
      winners[gi] = f==="home"?g.hi : f==="away"?g.ai : (Math.random()<g.p?g.hi:g.ai); }
    const [W,dW,cW]=recordsFrom(winners);
    const finalSeed=new Int8Array(NT), confSeedTeam={};
    for(let ci=0;ci<CONFS.length;ci++){ const c=CONFS[ci]; const seeds=seedConference(c,winners,W,dW,cW);
      const st={}; for(const ti in seeds){ const k=+ti, sd=seeds[ti]; finalSeed[k]=sd; st[sd]=k; } confSeedTeam[c]=st; }

    for(let i=0;i<NT;i++){ const sd=finalSeed[i];
      if(sd>=1){ seedHits[i][sd-1]++; makeP[i]++; if(sd<=DWS) winDiv[i]++; } else seedHits[i][NSEED]++; }

    // playoff bracket (reseeding, top BYES seeds idle round 1)
    const confWinners=[];
    for(let ci=0;ci<CONFS.length;ci++){
      const st=confSeedTeam[CONFS[ci]]; if(Object.keys(st).length<NSEED) continue;
      let alive=[]; for(let sd=1;sd<=NSEED;sd++) alive.push(sd); let byes=BYES;
      while(alive.length>1){
        alive.sort((a,b)=>a-b);
        const playing = alive.length>byes?alive.slice(byes):alive.slice();
        const next = alive.length>byes?alive.slice(0,byes):[];
        let lo=0, hi=playing.length-1;
        while(lo<hi){ const sa=playing[lo], sb=playing[hi];
          const win = Math.random()<winProbElo(TEAMS[st[sa]],TEAMS[st[sb]],true) ? sa : sb;
          next.push(win); lo++; hi--; }
        if(lo===hi) next.push(playing[lo]);
        alive=next; byes=0;
      }
      confWinners.push(st[alive[0]]); confCh[st[alive[0]]]++;
    }
    if(confWinners.length===CONFS.length){ const a=confWinners[0], b=confWinners[1];
      if(Math.random()<winProbElo(TEAMS[a],TEAMS[b],false)) title[a]++; else title[b]++; }
  }

  const res={};
  for(let i=0;i<NT;i++){ const sp=[]; for(let sd=0;sd<NSEED;sd++) sp.push(100*seedHits[i][sd]/nSims);
    res[TEAMS[i]]={ seed_probs:sp, miss:100*seedHits[i][NSEED]/nSims,
      make_playoffs:100*makeP[i]/nSims, win_div:100*winDiv[i]/nSims,
      win_conf:100*confCh[i]/nSims, win_title:100*title[i]/nSims }; }
  return res;
}

/* --------- clinch / elimination with real tiebreakers (mirrors seeding.py) --- */
const MISS = NSEED + 1, SEARCH_CAP = 14;

function seedOf(conf,winners,W,dW,cW,ti){ const s=seedConference(conf,winners,W,dW,cW); return (ti in s)?s[ti]:MISS; }
function recordsSkip(winners,skip){ const W=new Float64Array(NT),dW=new Float64Array(NT),cW=new Float64Array(NT);
  for(let gi=0;gi<NG;gi++){ if(skip.has(gi)) continue; const w=winners[gi]; if(w<0) continue; W[w]++; if(GAMES[gi].isDiv) dW[w]++; if(GAMES[gi].isConf) cW[w]++; } return [W,dW,cW]; }

// Best (wantMin) or worst seed `ti` can reach. Games vs ti are fixed win/lose;
// games between two contenders are enumerated; others fixed favorably/not.
function searchExtreme(base, ti, conf, openIdx, cset, teamWinsOut, wantMin){
  const winners=base.slice(), mutual=[];
  for(const gi of openIdx){ const g=GAMES[gi], h=g.hi, a=g.ai;
    if(h===ti||a===ti){ winners[gi]= teamWinsOut?ti:(h===ti?a:h); }
    else if(cset.has(h)&&cset.has(a)){ mutual.push(gi); }
    else { const cs= cset.has(h)?h:(cset.has(a)?a:-1), os= cs===h?a:h; winners[gi]= cs<0?h:(wantMin?os:cs); } }
  const m=mutual.length; if(m>SEARCH_CAP) return null;
  const skip=new Set(mutual); const [W0,dW0,cW0]=recordsSkip(winners,skip);
  const mg=mutual.map(gi=>[gi,GAMES[gi].hi,GAMES[gi].ai,GAMES[gi].isDiv,GAMES[gi].isConf]);
  let extreme=null;
  for(let bits=0; bits<(1<<m); bits++){
    const W=W0.slice(),dW=dW0.slice(),cW=cW0.slice();
    for(let k=0;k<m;k++){ const e=mg[k], w=((bits>>k)&1)?e[1]:e[2]; winners[e[0]]=w; W[w]++; if(e[3]) dW[w]++; if(e[4]) cW[w]++; }
    const sd=seedOf(conf,winners,W,dW,cW,ti);
    if(extreme===null || (wantMin? sd<extreme : sd>extreme)) extreme=sd;
    if(wantMin && extreme===1) break;
    if(!wantMin && extreme===MISS) break;
  }
  return extreme;
}
function achievableSeeds(base, ti, mcSeeds){
  const conf=TEAMCONFI[ti], confteams=CONF_IDX[conf];
  const openIdx=[]; for(let gi=0;gi<NG;gi++) if(base[gi]<0) openIdx.push(gi);
  const cw={}; confteams.forEach(t=>cw[t]=0);
  for(let gi=0;gi<NG;gi++){ const w=base[gi]; if(w>=0 && (w in cw)) cw[w]++; }
  const line=confteams.map(t=>cw[t]).sort((a,b)=>b-a)[6];
  const myDiv=TEAMDIV[ti];
  const cset=new Set(confteams.filter(t=>t!==ti && (Math.abs(cw[t]-line)<=2 || TEAMDIV[t]===myDiv)));
  const best=searchExtreme(base,ti,conf,openIdx,cset,true,true);
  const worst=searchExtreme(base,ti,conf,openIdx,cset,false,false);
  const set=new Set(mcSeeds);
  if(best===null||worst===null){ for(let s=1;s<=MISS;s++) set.add(s); }
  else { for(let s=best;s<=worst;s++) set.add(s); }
  return [...set].sort((a,b)=>a-b);
}
// achievable seed set for the focal team given played + user-forced results
function achievableFor(team, forced, odds){
  const base=new Int32Array(NG).fill(-1);
  for(let gi=0;gi<NG;gi++){ if(GAMES[gi].fixed>=0) base[gi]=GAMES[gi].fixed;
    const f=forced[GAMES[gi].id]; if(f) base[gi]= f==="home"?GAMES[gi].hi:GAMES[gi].ai; }
  const mc=[]; for(let s=0;s<NSEED;s++) if(odds.seed_probs[s]>0) mc.push(s+1); if(odds.miss>0) mc.push(MISS);
  return achievableSeeds(base, TIDX[team], mc);
}

/* ----------------------- team detail modal ----------------------- */
const PANEL_SIMS = 5000;
let activeTeam=null, forced={}, baseOdds=null;

function teamSchedule(team){
  return DATA.schedule.filter(g=>g.home===team||g.away===team)
                      .sort((a,b)=>a.week-b.week);
}
function nForced(){ return Object.keys(forced).length; }

// Heavy sims block the main thread, so paint a "simulating" state first and
// defer the work one tick so the spinner is visible.
function calcBadge(on){
  let b=document.getElementById("calcbadge");
  if(on){ if(!b){ b=document.createElement("div"); b.id="calcbadge";
    b.textContent="simulating "+PANEL_SIMS.toLocaleString()+" seasons…";
    (document.querySelector(".modal")||document.body).appendChild(b); } }
  else if(b) b.remove();
}
function deferCompute(fn){ calcBadge(true); setTimeout(()=>{ try{ fn(); } finally { calcBadge(false); } }, 16); }

function openTeam(team){
  activeTeam=team; forced={};
  document.getElementById("modal-body").innerHTML =
    `<div class="modal-h"><h2>${tname(team)}</h2><button class="x" onclick="closeModal()">&times;</button></div>`+
    `<div class="modal-b"><div class="calc">simulating ${PANEL_SIMS.toLocaleString()} seasons…</div></div>`;
  document.getElementById("modal").style.display="flex";
  deferCompute(()=>{ baseOdds = simulate(PANEL_SIMS, {})[team]; renderModal(baseOdds); });
}
function closeModal(){
  document.getElementById("modal").style.display="none";
  calcBadge(false); activeTeam=null; forced={};
}
function resetToggles(){ forced={}; renderModal(baseOdds); }

function setToggle(gid, choice){
  const g = DATA.schedule.find(x=>x.id===gid);
  const isHome = g.home===activeTeam;
  if(choice==="auto") delete forced[gid];
  else if(choice==="win") forced[gid] = isHome?"home":"away";
  else forced[gid] = isHome?"away":"home";
  renderModal(baseOdds);   // instant repaint so the toggle state shows immediately
  if(nForced()) deferCompute(()=>{ renderModal(simulate(PANEL_SIMS, forced)[activeTeam]); });
}

function delta(cur, base){
  const d = cur-base;
  if(Math.abs(d)<0.1) return `<span class="delta zero">±0</span>`;
  const cls = d>0?"up":"down";
  return `<span class="delta ${cls}">${d>0?"+":""}${d.toFixed(1)}</span>`;
}
function oddsCard(lab, cur, base, st, showDelta){
  const tk = token(cur, st);
  const val = (tk==="X"||tk==="^") ? `<span class="big-sym">${tk}</span>`
            : (tk==="<0.1"||tk===">99.9") ? tk+"%" : tk+"%";
  const dShow = showDelta && tk!=="X" && tk!=="^";
  return `<div class="odds-card"><div class="lab">${lab}</div>
    <div class="val">${val}${dShow?delta(cur,base):""}</div></div>`;
}

function renderModal(cur){
  const team=activeTeam, base=baseOdds, show=nForced()>0;
  const ach = achievableFor(team, forced, cur);
  const S = statusSet(ach);
  let h = `<div class="modal-h">
      <h2>${tname(team)} <span class="dim" style="font-weight:400;font-size:13px">&middot; ${recStr(rowsByTeam[team])} &middot; ${DATA.season} ${teamDivName(team)}</span></h2>
      <button class="x" onclick="closeModal()">&times;</button>
    </div><div class="modal-b">`;

  // headline odds
  h += `<div class="odds-grid">
    ${oddsCard("Make Playoffs", cur.make_playoffs, base.make_playoffs, S.make, show)}
    ${oddsCard("Win Division", cur.win_div, base.win_div, S.div, show)}
    ${oddsCard("Win Conference", cur.win_conf, base.win_conf, S.brkt, show)}
    ${oddsCard("Win Title", cur.win_title, base.win_title, S.brkt, show)}
  </div>`;

  // per-seed probability (each cell shows the seed and its odds; X / ^ markers)
  const seedfmt = tk => (tk==="X"||tk==="^") ? tk : tk+"%";
  h += `<div class="dim" style="font-size:12px;margin-top:10px">Chance of each playoff seed</div>`;
  h += `<div class="seedgrid">`;
  for(let s=0;s<NSEED;s++){
    const p=cur.seed_probs[s], tk=token(p, S.seed(s+1));
    const bg = tk==="X" ? "#141c30" : tk==="^" ? heat(100) : heat(p);
    h += `<div class="sc" style="background:${bg}"><div class="sd">#${s+1}</div>`+
         `<div class="sv">${seedfmt(tk)}</div></div>`;
  }
  const mt=token(cur.miss, S.miss);
  h += `<div class="sc" style="background:${mt==='X'?'#141c30':'#2a3450'}">`+
       `<div class="sd">Miss</div><div class="sv">${seedfmt(mt)}</div></div></div>`;

  // controls
  h += `<div class="ctrlbar">
    <span>${show?("Forcing "+nForced()+" game"+(nForced()>1?"s":"")+" &middot; live "+PANEL_SIMS.toLocaleString()+"-run sim"):("Toggle a remaining game to see the impact &middot; live "+PANEL_SIMS.toLocaleString()+"-run sim")}</span>
    <button onclick="resetToggles()" ${show?"":"disabled style=opacity:.4"}>Reset</button>
  </div>`;

  // schedule
  teamSchedule(team).forEach(g=>{
    const isHome = g.home===team;
    const opp = isHome?g.away:g.home;
    const ha = isHome?"vs":"@";
    const wp = isHome? g.p_home*100 : (1-g.p_home)*100;
    if(g.played){
      const won = g.winner===(isHome?"home":"away");
      const my = isHome?g.home_score:g.away_score, their = isHome?g.away_score:g.home_score;
      const score = (my==null||their==null) ? "" : ` ${my}&ndash;${their}`;
      h += `<div class="schrow played">
        <div class="wk">Wk ${g.week}</div>
        <div class="opp">${ha} ${tname(opp)}</div>
        <div class="wp" title="pre-game win probability">${wp.toFixed(0)}%</div>
        <div class="resultpill" style="color:${g.winner==="tie"?"var(--muted)":(won?"#4ade80":"#f87171")}">${g.winner==="tie"?"TIE":(won?"WON":"LOST")}${score}</div>
      </div>`;
    } else {
      const f = forced[g.id];
      const state = f===undefined ? "auto" : (f===(isHome?"home":"away")?"win":"loss");
      h += `<div class="schrow">
        <div class="wk">Wk ${g.week}</div>
        <div class="opp">${ha} ${tname(opp)} ${g.neutral?'<span class="ha">(N)</span>':''}</div>
        <div class="wp">${wp.toFixed(0)}%</div>
        <div class="toggle">
          <button class="${state==='win'?'on-win':''}" onclick="setToggle(${g.id},'win')">Win</button>
          <button class="${state==='loss'?'on-loss':''}" onclick="setToggle(${g.id},'loss')">Loss</button>
          <button class="${state==='auto'?'on-auto':''}" onclick="setToggle(${g.id},'auto')">Auto</button>
        </div>
      </div>`;
    }
  });

  h += `</div>`;
  document.getElementById("modal-body").innerHTML = h;
}

function teamDivName(team){
  for(const d in DATA.divisions) if(DATA.divisions[d].includes(team)) return d;
  return "";
}

// close modal on backdrop click / Esc
document.getElementById("modal").addEventListener("click",e=>{
  if(e.target.id==="modal") closeModal();
});
document.addEventListener("keydown",e=>{ if(e.key==="Escape") closeModal(); });

let tab = "seeds";
function render(){
  document.getElementById("title").textContent = `${DATA.season} ${DATA.sport} Playoff Odds`;
  const P = DATA.progress || {games_played:0};
  let status;
  if(!P.games_played){
    status = `<span class="live">Preseason</span> &middot; no ${DATA.season} games played yet`;
  } else {
    const wkState = P.week_complete ? "complete" : `${P.week_games_played} of ${P.week_games_total} played`;
    status = `<span class="live">Through Week ${P.through_week}</span> (${wkState}) &middot; ${P.games_played} of ${P.games_total} games in the books`;
  }
  document.getElementById("subtitle").innerHTML =
    `${status} &middot; Elo from ${DATA.start_year}&ndash;${DATA.last_completed} + ${DATA.season} results to date &middot; ${DATA.sims.toLocaleString()} simulated seasons`+
    (DATA.generated_at ? ` <span class="stamp">&middot; updated ${DATA.generated_at}</span>` : "");
  const tabs = [["seeds","Playoff Seeds"],["games","Upcoming Games"],["results","Results"]];
  document.getElementById("tabs").innerHTML = tabs.map(([k,l])=>
    `<div class="tab ${tab===k?'active':''}" data-k="${k}">${l}</div>`).join("");
  document.querySelectorAll(".tab").forEach(el=>el.onclick=()=>{tab=el.dataset.k;render();});
  document.getElementById("view").innerHTML = tab==="seeds" ? seedsView() : tab==="results" ? resultsView() : gamesView();
  document.querySelectorAll("td.team.clickable").forEach(el=>
    el.onclick=()=>openTeam(el.dataset.team));
  document.querySelectorAll("th[data-sk]").forEach(el=>el.onclick=()=>{
    const k=el.dataset.sk;
    if(k==="grouped") sortState=null;
    else if(sortState && sortState.key===k) sortState.dir*=-1;
    else sortState={key:k, dir:-1};
    render();
  });
  document.getElementById("foot").innerHTML =
    `Seeds 1&ndash;${DATA.seeds_per_conf} per conference (top ${DATA.seeds_per_conf-3} are division winners). `+
    `Win probabilities come from historical Elo ratings (K-factor with margin-of-victory scaling, home-field edge, and preseason regression toward the mean). `+
    `Each simulated season plays out every remaining game and is seeded with the real NFL tiebreakers (head-to-head, division, common games, conference record, strength of victory/schedule), then runs the playoff bracket. `+
    `<b>X</b>/<b>^</b> use a tiebreaker-aware feasibility search that accounts for how games interact &mdash; e.g. knocking out the current #7 seed lifts whoever beats them. `+
    `Click any team to open its schedule and toggle remaining games to Win/Loss &mdash; the page re-runs a live ${PANEL_SIMS.toLocaleString()}-season simulation in your browser (with the same tiebreakers) and shows how the odds shift. `+
    `Generated by <code>sports_elo.py</code>.`;
}
render();
</script>
</body>
</html>
"""
