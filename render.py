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
  .seedmini{display:flex;gap:3px;margin:10px 0 4px;height:22px}
  .seedmini .sc{flex:1;border-radius:4px;display:flex;align-items:center;
    justify-content:center;font-size:10px;font-weight:700;color:#cdd7ee;
    background:#1a2440}
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
  .calc{color:var(--accent);font-size:12px;font-weight:600}
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
      h += `<td class="team clickable" data-team="${r.team}">${tname(r.team)}</td>`;
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
    h += `<div class="conf-h"><h2>${c}</h2><span class="note">probability (%) of finishing in each playoff seed &middot; <b>click a team</b> to explore its schedule</span></div>`;
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

// Games: fixed (played) contribute to base wins; open games get simulated.
const BASEWINS = new Float64Array(NT);
DATA.schedule.forEach(g=>{
  if(!g.played) return;
  if(g.winner==="home") BASEWINS[TIDX[g.home]]+=1;
  else if(g.winner==="away") BASEWINS[TIDX[g.away]]+=1;
  else { BASEWINS[TIDX[g.home]]+=0.5; BASEWINS[TIDX[g.away]]+=0.5; }
});
const OPEN = DATA.schedule.filter(g=>!g.played)
  .map(g=>({id:g.id, hi:TIDX[g.home], ai:TIDX[g.away], p:g.p_home}));

function winProbElo(ta, tb, homeForA){
  const ra = RAT[ta]!=null?RAT[ta]:MEAN, rb = RAT[tb]!=null?RAT[tb]:MEAN;
  const H = homeForA?HF:0;
  return 1/(1+Math.pow(10, -((ra-rb+H)/400)));
}

// forced: {gameId: 'home'|'away'} -> returns {team: oddsObj}
function simulate(nSims, forced){
  forced = forced || {};
  const seedHits = []; for(let i=0;i<NT;i++) seedHits.push(new Float64Array(NSEED+1));
  const makeP=new Float64Array(NT), winDiv=new Float64Array(NT);
  const confCh=new Float64Array(NT), title=new Float64Array(NT);
  const wins=new Float64Array(NT), score=new Float64Array(NT);
  const finalSeed=new Int8Array(NT);

  for(let s=0;s<nSims;s++){
    for(let i=0;i<NT;i++) wins[i]=BASEWINS[i];
    for(let k=0;k<OPEN.length;k++){
      const g=OPEN[k], f=forced[g.id];
      const homeWin = f==="home" ? true : f==="away" ? false : (Math.random()<g.p);
      if(homeWin) wins[g.hi]++; else wins[g.ai]++;
    }
    for(let i=0;i<NT;i++){ finalSeed[i]=0; score[i]=wins[i]+Math.random()*1e-3; }

    const confSeedTeam={};
    for(let ci=0; ci<CONFS.length; ci++){
      const c=CONFS[ci], divs=CONF_DIVS[c];
      const dw=[];
      for(let d=0; d<divs.length; d++){
        let best=divs[d][0];
        for(let j=1;j<divs[d].length;j++) if(score[divs[d][j]]>score[best]) best=divs[d][j];
        dw.push(best);
      }
      const dwset=new Set(dw);
      dw.sort((a,b)=>score[b]-score[a]);
      const cst={};
      for(let r=0;r<dw.length;r++){ finalSeed[dw[r]]=r+1; cst[r+1]=dw[r]; }
      const pool=CONF_IDX[c].filter(ti=>!dwset.has(ti)).sort((a,b)=>score[b]-score[a]);
      for(let w=0;w<WCS;w++){ const ti=pool[w]; finalSeed[ti]=DWS+w+1; cst[DWS+w+1]=ti; }
      confSeedTeam[c]=cst;
    }

    for(let i=0;i<NT;i++){
      const sd=finalSeed[i];
      if(sd>=1){ seedHits[i][sd-1]++; makeP[i]++; if(sd<=DWS) winDiv[i]++; }
      else seedHits[i][NSEED]++;
    }

    // playoff bracket (reseeding, top BYES seeds idle round 1)
    const confWinners=[];
    for(let ci=0;ci<CONFS.length;ci++){
      const st=confSeedTeam[CONFS[ci]];
      if(Object.keys(st).length<NSEED) continue;
      let alive=[]; for(let sd=1;sd<=NSEED;sd++) alive.push(sd);
      let byes=BYES;
      while(alive.length>1){
        alive.sort((a,b)=>a-b);
        const playing = alive.length>byes?alive.slice(byes):alive.slice();
        const next = alive.length>byes?alive.slice(0,byes):[];
        let lo=0, hi=playing.length-1;
        while(lo<hi){
          const sa=playing[lo], sb=playing[hi];
          const win = Math.random()<winProbElo(TEAMS[st[sa]],TEAMS[st[sb]],true) ? sa : sb;
          next.push(win); lo++; hi--;
        }
        if(lo===hi) next.push(playing[lo]);
        alive=next; byes=0;
      }
      confWinners.push(st[alive[0]]); confCh[st[alive[0]]]++;
    }
    if(confWinners.length===CONFS.length){
      const a=confWinners[0], b=confWinners[1];
      if(Math.random()<winProbElo(TEAMS[a],TEAMS[b],false)) title[a]++; else title[b]++;
    }
  }

  const res={};
  for(let i=0;i<NT;i++){
    const sp=[]; for(let sd=0;sd<NSEED;sd++) sp.push(100*seedHits[i][sd]/nSims);
    res[TEAMS[i]]={
      seed_probs:sp, miss:100*seedHits[i][NSEED]/nSims,
      make_playoffs:100*makeP[i]/nSims, win_div:100*winDiv[i]/nSims,
      win_conf:100*confCh[i]/nSims, win_title:100*title[i]/nSims,
    };
  }
  return res;
}

/* ----------------------- team detail modal ----------------------- */
const PANEL_SIMS = 8000;
let activeTeam=null, forced={}, baseOdds=null;

function teamSchedule(team){
  return DATA.schedule.filter(g=>g.home===team||g.away===team)
                      .sort((a,b)=>a.week-b.week);
}
function nForced(){ return Object.keys(forced).length; }

function openTeam(team){
  activeTeam=team; forced={};
  baseOdds = simulate(PANEL_SIMS, {})[team];   // live no-toggle baseline
  renderModal(baseOdds);
  document.getElementById("modal").style.display="flex";
}
function closeModal(){
  document.getElementById("modal").style.display="none";
  activeTeam=null; forced={};
}
function resetToggles(){ forced={}; renderModal(baseOdds); }

function setToggle(gid, choice){
  const g = DATA.schedule.find(x=>x.id===gid);
  const isHome = g.home===activeTeam;
  if(choice==="auto") delete forced[gid];
  else if(choice==="win") forced[gid] = isHome?"home":"away";
  else forced[gid] = isHome?"away":"home";
  // recompute under current forcing and re-render
  const cur = nForced() ? simulate(PANEL_SIMS, forced)[activeTeam] : baseOdds;
  renderModal(cur);
}

function delta(cur, base){
  const d = cur-base;
  if(Math.abs(d)<0.1) return `<span class="delta zero">±0</span>`;
  const cls = d>0?"up":"down";
  return `<span class="delta ${cls}">${d>0?"+":""}${d.toFixed(1)}</span>`;
}
function oddsCard(lab, cur, base, showDelta){
  return `<div class="odds-card"><div class="lab">${lab}</div>
    <div class="val">${cur<0.05?"0":cur.toFixed(cur<10?1:0)}%${showDelta?delta(cur,base):""}</div></div>`;
}

function renderModal(cur){
  const team=activeTeam, base=baseOdds, show=nForced()>0;
  let h = `<div class="modal-h">
      <h2>${tname(team)} <span class="dim" style="font-weight:400;font-size:13px">&middot; ${DATA.season} ${teamDivName(team)}</span></h2>
      <button class="x" onclick="closeModal()">&times;</button>
    </div><div class="modal-b">`;

  // headline odds
  h += `<div class="odds-grid">
    ${oddsCard("Make Playoffs", cur.make_playoffs, base.make_playoffs, show)}
    ${oddsCard("Win Division", cur.win_div, base.win_div, show)}
    ${oddsCard("Win Conference", cur.win_conf, base.win_conf, show)}
    ${oddsCard("Win Title", cur.win_title, base.win_title, show)}
  </div>`;

  // seed distribution mini-bar
  h += `<div class="dim" style="font-size:12px;margin-top:10px">Seed probability (#1&ndash;#${NSEED}, then Miss)</div>`;
  h += `<div class="seedmini">`;
  for(let s=0;s<NSEED;s++){
    const p=cur.seed_probs[s];
    h += `<div class="sc" title="Seed ${s+1}: ${p.toFixed(1)}%" style="background:${heat(p)}">${p>=4?("#"+(s+1)):""}</div>`;
  }
  h += `<div class="sc" title="Miss: ${cur.miss.toFixed(1)}%" style="background:#2a3450">${cur.miss>=6?"Miss":""}</div></div>`;

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
      h += `<div class="schrow played">
        <div class="wk">Wk ${g.week}</div>
        <div class="opp">${ha} ${tname(opp)}</div>
        <div class="wp">${wp.toFixed(0)}%</div>
        <div class="resultpill">${g.winner==="tie"?"TIE":(won?"WON":"LOST")}</div>
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
  document.getElementById("subtitle").innerHTML =
    `Elo Monte Carlo &middot; ${DATA.sims.toLocaleString()} simulated seasons &middot; ratings built from ${DATA.start_year}&ndash;${DATA.last_completed} game results`;
  const tabs = [["seeds","Playoff Seeds"],["games","Upcoming Games"]];
  document.getElementById("tabs").innerHTML = tabs.map(([k,l])=>
    `<div class="tab ${tab===k?'active':''}" data-k="${k}">${l}</div>`).join("");
  document.querySelectorAll(".tab").forEach(el=>el.onclick=()=>{tab=el.dataset.k;render();});
  document.getElementById("view").innerHTML = tab==="seeds" ? seedsView() : gamesView();
  document.querySelectorAll("td.team.clickable").forEach(el=>
    el.onclick=()=>openTeam(el.dataset.team));
  document.getElementById("foot").innerHTML =
    `Seeds 1&ndash;${DATA.seeds_per_conf} per conference (top ${DATA.seeds_per_conf-3} are division winners). `+
    `Win probabilities come from historical Elo ratings (K-factor with margin-of-victory scaling, home-field edge, and preseason regression toward the mean). `+
    `Each simulated season plays out every remaining game, applies the league seeding rules, then runs the playoff bracket. `+
    `Click any team to open its schedule and toggle remaining games to Win/Loss &mdash; the page re-runs a live ${PANEL_SIMS.toLocaleString()}-season simulation in your browser and shows how the odds shift. `+
    `Generated by <code>sports_elo.py</code>.`;
}
render();
</script>
</body>
</html>
"""
