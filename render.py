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
  table{border-collapse:collapse;width:100%;background:var(--panel);
        border:1px solid var(--line);border-radius:10px;overflow:hidden}
  th,td{padding:7px 8px;text-align:center;font-variant-numeric:tabular-nums;
        border-bottom:1px solid var(--line)}
  th{background:#10182a;color:var(--muted);font-weight:600;font-size:12px;
     position:sticky;top:0}
  td.team{text-align:left;font-weight:700;white-space:nowrap}
  td.lbl{text-align:left;color:var(--muted)}
  tr.divrow td{background:#0d1322;color:var(--muted);text-align:left;
               font-weight:700;font-size:12px;letter-spacing:.4px}
  .pct{font-weight:600}
  .dim{color:#5d6680}
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
  .bar{height:8px;border-radius:5px;background:#2a3450;overflow:hidden;display:flex}
  .bar>i{display:block;height:100%}
  .bar>i.away{background:#7c89a8}
  .bar>i.home{background:var(--accent)}
  .foot{color:var(--muted);font-size:12px;margin-top:30px;line-height:1.6}
  code{background:#0d1322;padding:1px 5px;border-radius:4px;color:#cdd7ee}
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

// blue heatmap: 0% -> transparent, 100% -> strong accent
function heat(p){
  if(p<=0) return "transparent";
  const a = Math.min(1, 0.08 + p/100*0.92);
  return `rgba(91,140,255,${a.toFixed(3)})`;
}
function fmt(p){ return p<0.05 ? "·" : (p>=99.95 ? "100" : p.toFixed(p<10?1:0)); }
function pcell(p, extra){
  const cls = (p<0.05 ? "dim" : "pct") + (extra ? " "+extra : "");
  return `<td class="${cls}" style="background:${heat(p)}">${fmt(p)}</td>`;
}

const rowsByTeam = {};
DATA.rows.forEach(r=>rowsByTeam[r.team]=r);

function seedTable(conf){
  const S = DATA.seeds_per_conf;
  let h = "<table><thead><tr>";
  h += "<th class='team' style='text-align:left'>Team</th><th>Elo</th><th>Proj W</th>";
  for(let s=1;s<=S;s++) h += `<th${s===1?" class='sep'":""}>#${s}</th>`;
  h += "<th class='sep'>Miss</th>";
  h += "<th class='sep'>Playoffs</th><th>Win Div</th><th>Win Conf</th><th>Title</th>";
  h += "</tr></thead><tbody>";

  // divisions in this conference, ordered
  const divs = Object.keys(DATA.divisions).filter(d=>d.split(" ")[0]===conf);
  divs.forEach(d=>{
    h += `<tr class="divrow"><td colspan="${S+7}">${d}</td></tr>`;
    // teams in this division, sorted by make-playoffs desc
    const ts = DATA.divisions[d].map(t=>rowsByTeam[t])
                 .sort((a,b)=>b.make_playoffs-a.make_playoffs||b.proj_wins-a.proj_wins);
    ts.forEach(r=>{
      h += "<tr>";
      h += `<td class="team">${tname(r.team)}</td>`;
      h += `<td class="dim">${r.elo}</td>`;
      h += `<td>${r.proj_wins.toFixed(1)}</td>`;
      r.seed_probs.forEach((p,i)=> h += pcell(p, i===0?"sep":"") );
      h += pcell(r.miss, "sep");
      h += pcell(r.make_playoffs, "sep");
      h += pcell(r.win_div);
      h += pcell(r.win_conf);
      h += pcell(r.win_title);
      h += "</tr>";
    });
  });
  h += "</tbody></table>";
  return h;
}

function seedsView(){
  let h = "";
  DATA.conferences.forEach(c=>{
    h += `<div class="conf-h"><h2>${c}</h2><span class="note">probability (%) of finishing in each playoff seed</span></div>`;
    h += seedTable(c);
  });
  h += `<div style="margin-top:10px"><span class="swatch" style="background:${heat(8)}"></span>low &nbsp; <span class="swatch" style="background:${heat(45)}"></span>mid &nbsp; <span class="swatch" style="background:${heat(90)}"></span>high</div>`;
  return h;
}

function gamesView(){
  if(!DATA.upcoming.length) return "<p>No upcoming games.</p>";
  let h = "";
  DATA.upcoming.forEach(w=>{
    h += `<div class="wk"><h3>Week ${w.week}</h3>`;
    w.games.forEach(g=>{
      const hp = g.home_wp, ap = g.away_wp;
      const favHome = hp>=ap;
      h += `<div class="game">
        <div class="away">${tname(g.away)}</div>
        <div class="p" style="text-align:right;color:${!favHome?'#fff':'var(--muted)'}">${ap.toFixed(0)}%</div>
        <div class="bar"><i class="away" style="width:${ap}%"></i><i class="home" style="width:${hp}%"></i></div>
        <div class="p" style="color:${favHome?'#fff':'var(--muted)'}">${hp.toFixed(0)}%</div>
        <div class="home">${tname(g.home)}${g.neutral?' <span class="dim">(N)</span>':''} <span class="dim">(H)</span></div>
      </div>`;
    });
    h += "</div>";
  });
  return h;
}

let tab = "seeds";
function render(){
  document.getElementById("title").textContent = `${DATA.season} ${DATA.sport} Playoff Odds`;
  document.getElementById("subtitle").innerHTML =
    `Elo Monte Carlo &middot; ${DATA.sims.toLocaleString()} simulated seasons &middot; ratings built from ${DATA.start_year}&ndash;${DATA.last_completed} game results`;
  const tabs = [["seeds","Playoff Seeds"],["games","Upcoming Games"]];
  document.getElementById("tabs").innerHTML = tabs.map(([k,l])=>
    `<div class="tab ${tab===k?'active':''}" data-k="${k}">${l}</div>`).join("");
  document.querySelectorAll(".tab").forEach(el=>el.onclick=()=>{tab=el.dataset.k;render();});
  document.getElementById("view").innerHTML = tab==="seeds" ? seedsView() : gamesView();
  document.getElementById("foot").innerHTML =
    `Seeds 1&ndash;${DATA.seeds_per_conf} per conference (top ${DATA.seeds_per_conf-3} are division winners). `+
    `Win probabilities come from historical Elo ratings (K-factor with margin-of-victory scaling, home-field edge, and preseason regression toward the mean). `+
    `Each simulated season plays out every remaining game, applies the league seeding rules, then runs the playoff bracket. `+
    `Generated by <code>sports_elo.py</code>.`;
}
render();
</script>
</body>
</html>
"""
