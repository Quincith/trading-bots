/* Bot World: a night trading office drawn as flat 90s pixel art, seen from above like a floor plan.
   Six walled rooms (one per bot) with big wall screens showing the real numbers from the last run,
   the Captain's throne room at the top, the beam room in the middle with a cable from every bot into
   Decision and a gold cable from Decision to the beam, a lounge, and a courier on a scooter.
   Everything is drawn with rectangles on a 640x496 grid and scaled up with crisp pixels. Original art. */
(function(){
'use strict';

const W = 640, MH = 448, H = 496, WALL = 50;

/* ---------- 3x5 pixel font ---------- */
const FONT = {
  A:[2,5,7,5,5],B:[6,5,6,5,6],C:[3,4,4,4,3],D:[6,5,5,5,6],E:[7,4,6,4,7],F:[7,4,6,4,4],G:[3,4,5,5,3],H:[5,5,7,5,5],
  I:[7,2,2,2,7],J:[1,1,1,5,2],K:[5,5,6,5,5],L:[4,4,4,4,7],M:[5,7,7,5,5],N:[6,5,5,5,5],O:[2,5,5,5,2],P:[6,5,6,4,4],
  Q:[2,5,5,6,3],R:[6,5,6,5,5],S:[3,4,2,1,6],T:[7,2,2,2,2],U:[5,5,5,5,7],V:[5,5,5,5,2],W:[5,5,7,7,5],X:[5,5,2,5,5],
  Y:[5,5,2,2,2],Z:[7,1,2,4,7],0:[7,5,5,5,7],1:[2,6,2,2,7],2:[6,1,2,4,7],3:[6,1,2,1,6],4:[5,5,7,1,1],5:[7,4,6,1,6],
  6:[3,4,7,5,7],7:[7,1,2,2,2],8:[7,5,7,5,7],9:[7,5,7,1,6],'.':[0,0,0,0,2],',':[0,0,0,2,4],':':[0,2,0,2,0],
  '%':[5,1,2,4,5],'$':[3,6,2,3,6],'+':[0,2,7,2,0],'-':[0,0,7,0,0],'/':[1,1,2,4,4],'!':[2,2,2,0,2],'?':[6,1,2,0,2],
  '(':[1,2,2,2,1],')':[4,2,2,2,4],'#':[5,7,5,7,5],'>':[4,2,1,2,4],'<':[1,2,4,2,1],'=':[0,7,0,7,0],"'":[2,2,0,0,0],
  '&':[2,5,2,5,3],'*':[5,2,5,0,0],'_':[0,0,0,0,7],'"':[5,5,0,0,0],';':[0,2,0,2,4],'@':[7,5,7,4,7],' ':[0,0,0,0,0]
};
const norm = s => String(s == null ? '' : s).toUpperCase().replace(/[—–]/g, '-').replace(/[·•]/g, '-')
  .replace(/→/g, '>').replace(/[✔✓]/g, '*').replace(/[‘’]/g, "'").replace(/[“”]/g, '"').replace(/…/g, '...');
function txt(c, s, x, y, col, k = 1, max = 999){
  s = norm(s); if(s.length > max) s = s.slice(0, Math.max(0, max - 1)) + '.';
  c.fillStyle = col;
  for(let i = 0; i < s.length; i++){
    const g = FONT[s[i]] || FONT['?'];
    for(let r = 0; r < 5; r++) for(let b = 0; b < 3; b++) if(g[r] & (4 >> b)) c.fillRect(x + (i * 4 + b) * k, y + r * k, k, k);
  }
  return s.length * 4 * k;
}
const tw = (s, k = 1) => norm(s).length * 4 * k - k;
function wrap(s, n){
  const out = []; let line = '';
  for(let w of norm(s).split(/\s+/)){
    while(w.length > n){ if(line){ out.push(line); line = ''; } out.push(w.slice(0, n)); w = w.slice(n); }
    if(!w) continue;
    if((line + ' ' + w).trim().length > n){ out.push(line); line = w; } else line = (line + ' ' + w).trim();
  }
  if(line) out.push(line);
  return out;
}
const fmtP = x => x == null || isNaN(x) ? '?' : x >= 10000 ? (x / 1000).toFixed(1) + 'K' : x >= 100 ? x.toFixed(0) : x >= 1 ? x.toFixed(2) : (+x).toPrecision(2);
const short = s => String(s || '').split('/')[0].replace(/USD$/, '');

/* ---------- palette ---------- */
const P = {
  void: '#04070e', corridor: '#0a0f1c', lane: '#2c2414', tileA: '#0e1628', tileB: '#0c1323',
  wallTop: '#26324f', wallFace: '#141d33', seam: '#0f1729', wallSide: '#1d2742',
  bezel: '#05080f', screen: '#061018', ink: '#d8e2f0', dim: '#5d6b85', gold: '#e8b45a', goldDark: '#9c7433',
  good: '#5fd38d', bad: '#ff5a5a', desk: '#2b3757', deskTop: '#3a4a72', deskFront: '#18203a',
  yellow: '#f7d33b', yellowShade: '#d9b21f', black: '#1b1b1f', silver: '#b8c0cc', white: '#f4f6fa', pupil: '#3a2412'
};
const COL = {scout: '#3ddc84', charts: '#3fd0e0', news: '#4aa3ff', sentiment: '#b06cff', risk: '#ff5a5a',
             decision: '#ffa53a', captain: '#e8b45a', beam: '#36ff7a', lounge: '#e8b45a'};
const ORDER = ['scout', 'charts', 'news', 'sentiment', 'risk', 'decision'];

/* ---------- the floor plan ---------- */
const ROOMS = {
  scout:     {x: 8,   y: 40,  w: 208, h: 120, side: 'E', title: 'OBSERVATORY'},
  charts:    {x: 8,   y: 180, w: 208, h: 120, side: 'E', title: 'TRADING FLOOR'},
  news:      {x: 8,   y: 320, w: 208, h: 120, side: 'E', title: 'NEWSROOM'},
  sentiment: {x: 424, y: 40,  w: 208, h: 120, side: 'W', title: 'LISTENING POST'},
  risk:      {x: 424, y: 180, w: 208, h: 120, side: 'W', title: 'VAULT'},
  lounge:    {x: 424, y: 320, w: 208, h: 120, side: 'W', title: 'LOUNGE'},
  captain:   {x: 240, y: 40,  w: 160, h: 120, side: 'S', title: 'THRONE ROOM'},
  beam:      {x: 240, y: 180, w: 160, h: 120, side: 'WE', title: 'BEAM ROOM'},
  decision:  {x: 240, y: 320, w: 160, h: 120, side: 'WE', title: 'COMMAND'}
};
const XW = 228, XE = 412, HY = [170, 310];
for(const [id, r] of Object.entries(ROOMS)){
  r.id = id; r.cx = r.x + r.w / 2;
  if(r.side === 'E') r.doors = [{x: r.x + r.w, y: r.y + 100, ex: XW, ey: r.y + 100}];
  if(r.side === 'W') r.doors = [{x: r.x, y: r.y + 100, ex: XE, ey: r.y + 100}];
  if(r.side === 'S') r.doors = [{x: r.cx, y: r.y + r.h, ex: r.cx, ey: 170}];
}
ROOMS.decision.doors = [{x: 240, y: 420, ex: XW, ey: 420}, {x: 400, y: 420, ex: XE, ey: 420}];
ROOMS.beam.doors = [{x: 240, y: 280, ex: XW, ey: 280}, {x: 400, y: 280, ex: XE, ey: 280}];
// where each bot stands and where the courier stops to hand over the message
for(const id of ORDER){
  const r = ROOMS[id];
  r.bx = id === 'decision' ? r.x + 72 : r.cx; r.by = r.y + 80;
  r.stop = id === 'decision' ? {x: r.x + 30, y: r.y + 104} : {x: r.bx + (r.side === 'E' ? 36 : -36), y: r.y + 104};
}
ROOMS.captain.stop = {x: 268, y: 150};
ROOMS.lounge.stop = {x: 470, y: 412};
const HUB = {x: 346, y: 386}, EMIT = {x: 320, y: 254};

/* ---------- small drawing helpers ---------- */
const rect = (c, x, y, w, h, col) => { c.fillStyle = col; c.fillRect(x, y, w, h); };
function circle(c, cx, cy, r, col, fill){
  c.fillStyle = col;
  if(fill){ for(let y = -r; y <= r; y++){ const w = Math.round(Math.sqrt(r * r - y * y)); c.fillRect(cx - w, cy + y, w * 2 + 1, 1); } return; }
  const n = Math.max(12, Math.round(r * 7));
  for(let i = 0; i < n; i++){ const a = i / n * Math.PI * 2; c.fillRect(Math.round(cx + Math.cos(a) * r), Math.round(cy + Math.sin(a) * r), 1, 1); }
}
function hexA(hex, a){ const n = parseInt(hex.slice(1), 16); return `rgba(${n >> 16},${n >> 8 & 255},${n & 255},${a})`; }
function screen(c, x, y, w, h, col, title){
  rect(c, x - 1, y - 1, w + 2, h + 2, P.bezel); rect(c, x, y, w, h, P.screen);
  rect(c, x - 1, y - 1, w + 2, 1, hexA(col, .55));
  for(let yy = y + 1; yy < y + h; yy += 2) rect(c, x, yy, w, 1, 'rgba(255,255,255,.018)');   // scanlines
  if(title){ txt(c, title, x + 3, y + 2, col); rect(c, x + 3, y + 8, w - 6, 1, hexA(col, .3)); }
  return {x: x + 3, y: y + 11, w: w - 6, h: h - 13};
}
function lines(c, arr, x, y, w, col, max = 6){
  const n = Math.floor((w + 1) / 4);
  arr.slice(0, max).forEach((s, i) => txt(c, s, x, y + i * 6, typeof col === 'function' ? col(i, s) : col, 1, n));
}
function plant(c, x, y){
  rect(c, x - 4, y - 6, 8, 6, '#3b2a20'); rect(c, x - 4, y - 6, 8, 1, '#5a4030');
  const L = '#2f9a47', D = '#1f6e32';
  for(const [dx, dy, w, h, col] of [[-6,-12,4,3,L],[2,-13,5,3,L],[-3,-16,3,4,D],[1,-18,3,5,L],[-7,-9,3,2,D],[4,-9,4,2,D],[-1,-11,2,5,D]]) rect(c, x + dx, y + dy, w, h, col);
}

/* ---------- characters ---------- */
// glasses: one big goggle or two, with different frames per bot (Quincy's pick)
const LOOK = {
  scout:     {eyes: 1, frame: P.silver, hair: true},
  charts:    {eyes: 2, frame: '#111318', square: true, hair: true},
  news:      {eyes: 2, frame: P.silver, hair: true, visor: true},
  sentiment: {eyes: 1, frame: P.gold, phones: true},
  risk:      {eyes: 2, frame: '#c45b12', shades: true, hat: true},
  decision:  {eyes: 1, frame: '#111318', gold: true, hair: true},
  courier:   {eyes: 2, frame: '#7a4a24', cap: true}
};
// draws a minion-like helper, feet at (x, y). opts: back, mood (happy|sad|cheer|talk), frame, outfit
function minion(c, x, y, id, outfit, o = {}){
  const k = o.k || 2, L = LOOK[id] || LOOK.scout, ox = Math.round(x - 6 * k), oy = Math.round(y - 18 * k - (o.lift || 0));
  const px = (a, b, w, h, col) => { c.fillStyle = col; c.fillRect(ox + a * k, oy + b * k, w * k, h * k); };
  const cloth = outfit.cloth, pocket = outfit.pocket, stitch = outfit.stitch;
  // feet
  const step = o.walk ? (Math.floor(o.walk * 8) % 2) : 0;
  px(3, 16 - step, 2, 2, P.black); px(7, 16 - (1 - step) * (o.walk ? 1 : 0), 2, 2, P.black);
  // body
  px(2, 0, 8, 1, P.yellow); px(1, 1, 10, 14, P.yellow); px(2, 15, 8, 1, P.yellow); px(10, 2, 1, 12, P.yellowShade);
  // overalls
  px(1, 12, 10, 3, cloth); px(2, 15, 8, 1, cloth);
  if(!o.back){ px(3, 10, 6, 2, cloth); px(4, 10, 4, 1, pocket); px(1, 9, 1, 1, cloth); px(2, 10, 1, 1, cloth); px(10, 9, 1, 1, cloth); px(9, 10, 1, 1, cloth); }
  else { px(3, 9, 1, 3, cloth); px(8, 9, 1, 3, cloth); px(4, 11, 4, 1, cloth); }
  for(let i = 2; i < 10; i += 2) px(i, 13, 1, 1, stitch);
  px(5, 14, 2, 1, pocket);
  // arms
  if(o.mood === 'cheer'){ px(0, 4, 1, 5, P.yellow); px(11, 4, 1, 5, P.yellow); px(0, 3, 1, 1, P.black); px(11, 3, 1, 1, P.black); }
  else { px(0, 9, 1, 3, P.yellow); px(11, 9, 1, 3, P.yellow); px(0, 12, 1, 1, P.black); px(11, 12, 1, 1, P.black); }
  // head gear
  if(L.hair && !L.cap) { px(4, -1, 1, 1, P.black); px(6, -2, 1, 2, P.black); px(8, -1, 1, 1, P.black); }
  if(L.hat){ px(1, -1, 10, 2, '#ff8a1f'); px(3, -2, 6, 1, '#ff9c40'); px(0, 1, 12, 1, '#d96d10'); }
  if(L.cap){ px(2, -1, 8, 2, '#c0262d'); px(o.back ? 2 : 6, 1, 5, 1, '#8e1a20'); }
  if(L.phones){ px(1, -1, 10, 1, P.black); px(0, 3, 2, 4, COL.sentiment); px(10, 3, 2, 4, COL.sentiment); }
  // goggles and strap
  px(1, 4, 10, 2, P.black);
  if(o.back) return;
  const blink = o.blink;
  if(L.eyes === 1){
    px(3, 2, 6, 6, L.frame); if(L.gold){ px(3, 2, 6, 1, P.gold); px(3, 7, 6, 1, P.gold); }
    if(L.shades) px(4, 3, 4, 4, '#ffb347');
    else { px(4, 3, 4, 4, blink ? P.yellow : P.white); if(!blink){ px(5, 4, 2, 2, P.pupil); px(6, 4, 1, 1, '#000'); } }
  } else {
    const sq = L.square;
    for(const ex of [1, 6]){
      px(ex, 3, 5, sq ? 4 : 4, L.frame); if(!sq){ px(ex, 3, 1, 1, P.yellow); px(ex + 4, 3, 1, 1, P.yellow); px(ex, 6, 1, 1, P.yellow); px(ex + 4, 6, 1, 1, P.yellow); }
      if(L.shades){ px(ex + 1, 4, 3, 2, '#ffb347'); continue; }
      px(ex + 1, 4, 3, 2, blink ? P.yellow : P.white); if(!blink) px(ex + 2, 4, 1, 2, P.pupil);
    }
    if(L.visor) px(1, 2, 10, 1, '#4aa3ff');
  }
  // mouth
  const m = o.mood;
  if(m === 'sad'){ px(4, 9, 1, 1, P.pupil); px(5, 8, 2, 1, P.pupil); px(7, 9, 1, 1, P.pupil); }
  else if(m === 'cheer' || (m === 'talk' && o.t % .3 < .15)){ px(4, 8, 4, 2, '#3a1a10'); px(5, 9, 2, 1, '#ff7a7a'); }
  else { px(4, 8, 1, 1, P.pupil); px(5, 9, 2, 1, P.pupil); px(7, 8, 1, 1, P.pupil); }
  if(o.splat){ px(2, 2, 3, 2, '#d3241b'); px(6, 1, 2, 3, '#c8261c'); px(4, 5, 4, 1, '#e0321f'); px(8, 3, 2, 2, '#d3241b'); }
}
function scooter(c, x, y, dir){
  // deck, two wheels, stem and handlebar; dir 1 = moving right
  rect(c, x - 13, y - 3, 26, 3, '#9aa3b5'); rect(c, x - 13, y - 3, 26, 1, '#d6dce6');
  rect(c, x - 14, y, 6, 4, '#111'); rect(c, x + 8, y, 6, 4, '#111'); rect(c, x - 12, y + 1, 2, 2, '#777'); rect(c, x + 10, y + 1, 2, 2, '#777');
  const sx = x + dir * 12; rect(c, sx - 1, y - 30, 2, 28, '#c0262d'); rect(c, sx - 5, y - 31, 10, 2, '#111');
  rect(c, sx + dir * 2 - 1, y - 27, 2, 2, '#fff6c8');
}
// the Captain: an original chrome titan with black armor and red trim, seated on a black and red throne
function titan(c, x, y, s){
  const k = 2, px = (a, b, w, h, col) => { c.fillStyle = col; c.fillRect(x + a * k, y + b * k, w * k, h * k); };
  const C = '#c9d1dc', CL = '#f2f5f9', CM = '#8d97a6', CD = '#5a6270', B = '#18161c', R = '#c0262d', G = P.gold;
  const eye = s.glare ? '#ff7a7a' : s.flash ? '#ffd38a' : '#ff3b3b';
  // throne
  px(-17, -46, 34, 34, '#141018'); px(-17, -46, 34, 1, R); px(-17, -46, 1, 34, R); px(16, -46, 1, 34, R);
  for(const sx of [-15, -7, 1, 9]) { px(sx + 2, -50, 2, 4, G); px(sx + 2, -52, 2, 2, '#ffd98f'); }
  px(-3, -44, 6, 3, R); px(-1, -45, 2, 1, G);
  px(-15, -12, 30, 6, '#1d1822'); px(-15, -12, 30, 1, '#3a2b38');
  px(-19, -18, 6, 12, '#141018'); px(13, -18, 6, 12, '#141018'); px(-19, -18, 6, 1, R); px(13, -18, 6, 1, R);
  // aura when he glares
  if(s.glare){ c.fillStyle = 'rgba(255,40,40,.18)'; c.fillRect(x - 20 * k, y - 46 * k, 40 * k, 40 * k); }
  // legs
  px(-9, -12, 7, 6, C); px(2, -12, 7, 6, C); px(-9, -12, 7, 1, CL); px(2, -12, 7, 1, CL);
  px(-9, -6, 6, 6, CD); px(3, -6, 6, 6, CD); px(-8, -6, 1, 6, CM); px(4, -6, 1, 6, CM);
  px(-10, 0, 7, 2, B); px(3, 0, 7, 2, B); px(-10, 0, 1, 2, R); px(9, 0, 1, 2, R);
  // pelvis and torso
  px(-7, -14, 14, 3, B); px(-1, -14, 2, 2, G);
  px(-8, -28, 16, 14, C); px(-8, -28, 16, 2, CL); px(6, -26, 2, 12, CM);
  px(-3, -27, 6, 11, B); px(-1, -23, 2, 2, s.flash ? '#ffd38a' : '#ff3b3b'); px(-2, -18, 4, 1, R); px(-2, -16, 4, 1, R);
  // shoulders (black pauldrons with red trim and chrome spikes)
  px(-15, -30, 8, 6, B); px(7, -30, 8, 6, B); px(-15, -25, 8, 1, R); px(7, -25, 8, 1, R);
  px(-13, -33, 2, 3, CL); px(11, -33, 2, 3, CL); px(-10, -32, 2, 2, C); px(8, -32, 2, 2, C);
  // arms resting on the throne
  const up = s.cheer ? 1 : 0;
  px(-15, -24, 5, 8, C); px(10, -24, 5, 8, C); px(-15, -24, 1, 8, CL);
  px(-16, -17, 6, 4, CD); px(10, -17 - up * 4, 6, 4, CD); px(-16, -14, 6, 2, B); px(10, -14 - up * 4, 6, 2, B);
  // head (nods down by one step)
  const hy = -38 + (s.nod || 0) + (s.shake ? 0 : 0), hx = s.shake || 0;
  px(-5 + hx, hy, 10, 9, C); px(-5 + hx, hy, 10, 1, CL); px(4 + hx, hy + 1, 1, 8, CM);
  px(-4 + hx, hy + 3, 8, 5, B); px(-3 + hx, hy + 4, 2, 1, eye); px(1 + hx, hy + 4, 2, 1, eye);
  if(s.glare || s.flash){ c.fillStyle = hexA(s.flash ? '#ffd38a' : '#ff3b3b', .35); c.fillRect(x + (-4 + hx) * k, y + (hy + 3) * k, 8 * k, 3 * k); }
  px(-2 + hx, hy + 7, 4, 1, R);
  px(-7 + hx, hy - 2, 2, 5, B); px(5 + hx, hy - 2, 2, 5, B); px(-8 + hx, hy - 4, 1, 3, R); px(7 + hx, hy - 4, 1, 3, R);
  px(-1 + hx, hy - 3, 2, 3, G);
  if(s.splat){ px(-3 + hx, hy + 1, 3, 2, '#d3241b'); px(1 + hx, hy - 1, 3, 3, '#c8261c'); }
}

/* ---------- routes along the corridors ---------- */
function exitOf(r, toward){
  if(r.doors.length === 1) return r.doors[0];
  return r.doors.reduce((a, b) => Math.abs(b.ex - toward) < Math.abs(a.ex - toward) ? b : a);
}
function route(fromId, toId){
  const A = ROOMS[fromId], B = ROOMS[toId];
  const da = exitOf(A, exitOf(B, 320).ex), db = exitOf(B, da.ex);
  const pts = [{...A.stop}];
  const inside = (r, d, p) => r.id === 'captain' ? [{x: d.x, y: p.y}, {x: d.x, y: d.y}] : [{x: p.x, y: d.y}, {x: d.x, y: d.y}];
  pts.push(...inside(A, da, A.stop), {x: da.ex, y: da.ey});
  if(da.ex !== db.ex){
    const hy = (fromId === 'captain' || toId === 'captain') ? 170 : HY.reduce((a, b) => Math.abs(b - (da.ey + db.ey) / 2) < Math.abs(a - (da.ey + db.ey) / 2) ? b : a);
    pts.push({x: da.ex, y: hy}, {x: db.ex, y: hy});
  }
  pts.push({x: db.ex, y: db.ey}, ...inside(B, db, B.stop).reverse(), {...B.stop});
  return pts.filter((p, i) => !i || p.x !== pts[i - 1].x || p.y !== pts[i - 1].y);
}
// cables: each bot's room to the hub in Decision, in parallel lanes
const CABLES = (() => {
  const out = [];
  const lane = {scout: -5, charts: 0, news: 5, sentiment: -5, risk: 0};
  for(const id of ['scout', 'charts', 'news', 'sentiment', 'risk']){
    const r = ROOMS[id], d = r.doors[0], o = lane[id], west = r.x < 320, cx = west ? XW + o : XE + o, ly = 424 + o;
    out.push({id, col: COL[id], pts: [{x: r.bx + (west ? 26 : -26), y: r.y + 86}, {x: r.bx + (west ? 26 : -26), y: d.y + o}, {x: cx, y: d.y + o},
      {x: cx, y: ly}, {x: west ? 280 : 380, y: ly}, {x: west ? 280 : 380, y: HUB.y + 6}, {x: HUB.x + (west ? -6 : 6), y: HUB.y + 6}]});
  }
  out.push({id: 'beam', col: P.gold, w: 3, pts: [{x: HUB.x, y: HUB.y}, {x: HUB.x, y: 296}, {x: HUB.x, y: EMIT.y}, {x: EMIT.x + 18, y: EMIT.y}]});
  for(const cb of out){ cb.len = 0; cb.seg = []; for(let i = 1; i < cb.pts.length; i++){ const a = cb.pts[i - 1], b = cb.pts[i], l = Math.abs(b.x - a.x) + Math.abs(b.y - a.y); cb.seg.push({a, b, l}); cb.len += l; } }
  return out;
})();
function along(cb, d){
  d = ((d % cb.len) + cb.len) % cb.len;
  for(const s of cb.seg){ if(d <= s.l){ const f = s.l ? d / s.l : 0; return {x: s.a.x + (s.b.x - s.a.x) * f, y: s.a.y + (s.b.y - s.a.y) * f}; } d -= s.l; }
  return cb.pts[cb.pts.length - 1];
}

/* ---------- the static layer: floor, walls, furniture, wall screens with the run's real numbers ---------- */
function drawStatic(c, S, data){
  rect(c, 0, 0, W, H, P.void);
  rect(c, 0, 36, W, MH - 36, P.corridor);
  // corridor guide lanes for the scooter
  for(let y = 44; y < 440; y += 8){ rect(c, XW, y, 1, 4, P.lane); rect(c, XE, y, 1, 4, P.lane); }
  for(let x = 12; x < 630; x += 8) for(const hy of HY) rect(c, x, hy, 4, 1, P.lane);
  // back wall of the building with tall windows onto the night city
  rect(c, 0, 0, W, 36, '#0b1122'); rect(c, 0, 34, W, 2, '#1d2742');
  skyline(c);
  rect(c, 0, 36, 8, MH - 36, P.wallSide); rect(c, W - 8, 36, 8, MH - 36, P.wallSide); rect(c, 0, MH - 8, W, 8, P.wallSide);
  for(const r of Object.values(ROOMS)) room(c, r);
  // floor cables (drawn before the furniture so desks sit on top)
  for(const cb of CABLES) if(cb.id !== 'beam') cable(c, cb, hexA(cb.col, .55), 1);
  cable(c, CABLES[CABLES.length - 1], '#8a6a2c', 3); cable(c, CABLES[CABLES.length - 1], P.gold, 1);
  const st = S.stations, L = S.latest;
  for(const id of ORDER){ walls(c, id, S, data); desk(c, ROOMS[id], id); }
  throneRoom(c, S); beamRoom(c, S); lounge(c, S); decisionExtras(c, S);
}
function skyline(c){
  let seed = 7; const rnd = () => (seed = (seed * 9301 + 49297) % 233280) / 233280;
  for(let i = 0; i < 7; i++){
    const wx = 14 + i * 88, ww = 80;
    rect(c, wx - 2, 3, ww + 4, 30, '#1d2742');
    rect(c, wx, 5, ww, 26, '#0a1430'); rect(c, wx, 5, ww, 8, '#0d1a3c');
    for(let s = 0; s < 6; s++) rect(c, wx + Math.floor(rnd() * ww), 6 + Math.floor(rnd() * 8), 1, 1, '#c9d6ff');
    let bx = wx;
    while(bx < wx + ww){
      const bw = 6 + Math.floor(rnd() * 12), bh = 8 + Math.floor(rnd() * 16);
      rect(c, bx, 31 - bh, Math.min(bw, wx + ww - bx), bh, rnd() < .5 ? '#121a33' : '#0f162b');
      for(let yy = 33 - bh; yy < 29; yy += 3) for(let xx = bx + 1; xx < Math.min(bx + bw, wx + ww) - 1; xx += 2) if(rnd() < .28) rect(c, xx, yy, 1, 1, rnd() < .8 ? '#ffd27a' : '#7fe0ff');
      bx += bw + 1;
    }
    rect(c, wx + ww / 2 - 1, 5, 2, 26, '#1d2742');
  }
  rect(c, 560, 8, 6, 6, '#f2efd8'); rect(c, 562, 8, 4, 2, '#0d1a3c');
}
function cable(c, cb, col, w){
  c.fillStyle = col;
  for(const s of cb.seg){ const x = Math.min(s.a.x, s.b.x), y = Math.min(s.a.y, s.b.y);
    c.fillRect(Math.round(x - (w >> 1)), Math.round(y - (w >> 1)), Math.round(Math.abs(s.b.x - s.a.x)) + w, Math.round(Math.abs(s.b.y - s.a.y)) + w); }
}
function room(c, r){
  const col = COL[r.id];
  for(let y = r.y; y < r.y + r.h; y += 8) for(let x = r.x; x < r.x + r.w; x += 8) rect(c, x, y, 8, 8, ((x + y) / 8) % 2 ? P.tileA : P.tileB);
  c.fillStyle = hexA(col, .045); c.fillRect(r.x, r.y, r.w, r.h);
  // north wall face with seams and a neon baseboard in the room's color
  rect(c, r.x, r.y, r.w, WALL, P.wallFace);
  for(let x = r.x + 26; x < r.x + r.w; x += 26) rect(c, x, r.y + 4, 1, WALL - 7, P.seam);
  rect(c, r.x, r.y, r.w, 4, P.wallTop); rect(c, r.x, r.y + 3, r.w, 1, '#33416a');
  rect(c, r.x, r.y + WALL - 3, r.w, 2, col); c.fillStyle = hexA(col, .22); c.fillRect(r.x, r.y + WALL - 1, r.w, 4);
  // side and front walls
  rect(c, r.x, r.y, 4, r.h, P.wallTop); rect(c, r.x + r.w - 4, r.y, 4, r.h, P.wallTop); rect(c, r.x, r.y + r.h - 4, r.w, 4, P.wallTop);
  rect(c, r.x + 4, r.y + r.h - 5, r.w - 8, 1, '#0a0f1c');
  for(const d of r.doors){
    if(d.y === r.y + r.h){ rect(c, d.x - 12, d.y - 4, 24, 4, P.corridor); rect(c, d.x - 13, d.y - 4, 1, 4, col); rect(c, d.x + 12, d.y - 4, 1, 4, col); }
    else { const wx = d.x === r.x ? r.x : r.x + r.w - 4; rect(c, wx, d.y - 10, 4, 20, P.tileB); rect(c, wx, d.y - 11, 4, 1, col); rect(c, wx, d.y + 10, 4, 1, col); }
  }
  // name plate
  if(ORDER.includes(r.id)){
    const n = ORDER.indexOf(r.id) + 1;
    rect(c, r.x + 6, r.y + r.h - 14, tw('0' + n + ' ' + r.id) + 7, 9, '#070b16'); rect(c, r.x + 6, r.y + r.h - 14, 1, 9, col);
    txt(c, '0' + n + ' ' + r.id, r.x + 10, r.y + r.h - 12, col);
  } else {
    rect(c, r.x + 6, r.y + r.h - 14, tw(r.title) + 7, 9, '#070b16'); txt(c, r.title, r.x + 10, r.y + r.h - 12, col);
  }
}
function desk(c, r, id){
  const x = r.bx, y = r.y + 76;
  rect(c, x - 26, y, 52, 9, P.desk); rect(c, x - 26, y, 52, 2, P.deskTop); rect(c, x - 26, y + 9, 52, 6, P.deskFront);
  rect(c, x - 24, y + 15, 3, 3, '#0b0f1a'); rect(c, x + 21, y + 15, 3, 3, '#0b0f1a');
  // backs of the desk monitors, glowing in the room's color
  for(const mx of [-24, 13]){ rect(c, x + mx, y - 7, 11, 8, '#0b0f1a'); rect(c, x + mx, y - 8, 11, 1, hexA(COL[id], .8)); rect(c, x + mx + 4, y, 3, 1, '#0b0f1a'); }
  rect(c, x - 8, y + 2, 16, 3, '#11182c'); for(let i = 0; i < 7; i++) rect(c, x - 7 + i * 2, y + 3, 1, 1, '#3a4a72');
  rect(c, x + 10, y + 1, 3, 3, '#e9e4d8');   // mug
}

/* the big wall screens, room by room */
function walls(c, id, S, data){
  const r = ROOMS[id], col = COL[id], st = S.stations[id] || {say: '', detail: []}, L = S.latest, cands = L ? L.candidates : [];
  const c0 = cands[0], isCopy = S.name === 'copycat', f = L && L.filings || {};
  const say = wrap(st.say, 13);
  const three = (t1, t2) => [screen(c, r.x + 7, r.y + 6, 62, 40, col, t1), screen(c, r.x + 73, r.y + 6, 62, 40, col, t2), screen(c, r.x + 139, r.y + 6, 62, 40, col, 'STATUS')];
  if(id === 'decision') return;
  let A, B, Cc;
  if(id === 'scout'){
    [A, B, Cc] = three(isCopy ? 'FILINGS' : 'SCANNER', 'RADAR');
    if(isCopy){
      const top = f.top || [];
      lines(c, top.length ? top.map(t => `${t.ticker} $${fmtP(t.usd)}`) : [`READ ${f.read || 0}`, `WATCH ${f.watchlist || 0}`, 'NO BIG BUYS'], A.x, A.y, A.w, P.ink, 4);
    } else {
      const scan = L ? Object.entries(L.scan || {}).sort((a, b) => b[1].volume_ratio - a[1].volume_ratio) : [];
      lines(c, scan.length ? scan.map(([s, m]) => `${short(s).padEnd(4)}${(m.volume_ratio.toFixed(1) + 'X').padStart(5)}${m.move_pct >= 0 ? '+' : ''}${m.move_pct.toFixed(0)}`) : ['NO SCAN', 'THIS RUN'],
        A.x, A.y, A.w, (i, s) => scan[i] && scan[i][1].passed ? col : P.ink, 4);
    }
    r.radar = {x: B.x + B.w / 2, y: B.y + B.h / 2 - 1, r: 11};
  } else if(id === 'charts'){
    [A, B, Cc] = three(c0 && c0.entry ? short(c0.symbol) + ' PLAN' : 'ACCOUNT', 'LEVELS');
    if(c0 && c0.entry) candles(c, A, c0); else spark(c, A, (S.equity || []).map(e => e[1]), col);
    lines(c, c0 && c0.entry ? [`GOAL ${fmtP(c0.target)}`, `BUY  ${fmtP(c0.entry)}`, `EXIT ${fmtP(c0.stop)}`, c0.reward_risk ? `R:R  ${c0.reward_risk}` : ''] : ['NO SETUP', 'THIS RUN'],
      B.x, B.y, B.w, (i) => c0 && c0.entry ? [P.good, P.ink, P.bad, P.dim][i] : P.dim, 4);
  } else if(id === 'news'){
    [A, B, Cc] = three('HEADLINES', 'SCORE');
    lines(c, wrap(c0 ? (c0.news || 'NO RECENT NEWS') : (isCopy && f.top && f.top[0] ? f.top[0].note : 'NO HEADLINES TO READ'), 13), A.x, A.y, A.w, P.ink, 4);
    const sc = c0 && c0.news_score != null ? c0.news_score : null;
    meter(c, B, sc, col, sc == null ? 'NONE' : (sc >= 0 ? '+' : '') + sc.toFixed(2));
    r.ticker = {x: r.x + 7, y: r.y + 47, w: r.w - 14, text: (cands.map(x => short(x.symbol) + ': ' + (x.news || '')).join('   ') || st.say) + '   '};
  } else if(id === 'sentiment'){
    [A, B, Cc] = three('MOOD', 'CHATTER');
    const sc = c0 && c0.sentiment_score != null ? c0.sentiment_score : null;
    r.gauge = {x: A.x + A.w / 2, y: A.y + 21, v: sc};
    txt(c, 'FEAR', A.x, A.y + 18, P.bad); txt(c, 'GREED', A.x + A.w - tw('GREED'), A.y + 18, P.good);
    r.bars = {x: B.x + 2, y: B.y + 22, w: B.w - 4, hype: c0 ? (c0.hype || 0) : 0, on: !!c0};
  } else if(id === 'risk'){
    [A, B, Cc] = three('LIMITS', 'REVIEW');
    const lim = S.limits, today = L && L.day_start_equity ? (L.equity - L.day_start_equity) / L.day_start_equity * 100 : 0;
    const perf = S.performance || {}, tot = perf.net_deposits ? Math.min(0, perf.profit) / perf.net_deposits * 100 : 0;
    bar(c, A.x, A.y, A.w, 'DAY', Math.max(0, -today) / lim.max_daily_loss_pct, col);
    bar(c, A.x, A.y + 9, A.w, 'TOTAL', Math.max(0, -tot) / lim.max_total_loss_pct, col);
    bar(c, A.x, A.y + 18, A.w, 'HELD', L ? Math.min(1, L.positions.length / 4) : 0, col);
    const verdict = c0 ? (c0.risk === 'REJECT' ? 2 : /RED|SHR|SIZE/.test(c0.risk || '') ? 1 : 0) : -1;
    ['APPROVE', 'REDUCE', 'REJECT'].forEach((w, i) => { const on = i === verdict, cc = [P.good, P.gold, P.bad][i];
      rect(c, B.x, B.y + i * 8, B.w, 7, on ? hexA(cc, .25) : '#0a1420'); rect(c, B.x, B.y + i * 8, 1, 7, on ? cc : P.dim); txt(c, w, B.x + 4, B.y + 1 + i * 8, on ? cc : P.dim); });
  }
  lines(c, say, Cc.x, Cc.y, Cc.w, P.ink, 5);
  // room-specific floor props
  const fx = r.x, fy = r.y;
  if(id === 'scout'){ dish(c, fx + 26, fy + 92); plant(c, fx + 190, fy + 112); }
  if(id === 'charts'){ shelf(c, fx + 12, fy + 58, ['PRICE', 'TREND', 'LEVELS'], col); plant(c, fx + 190, fy + 112); }
  if(id === 'news'){ press(c, fx + 14, fy + 60); papers(c, fx + 168, fy + 96); }
  if(id === 'sentiment'){ speaker(c, fx + 168, fy + 60); speaker(c, fx + 186, fy + 60); plant(c, fx + 18, fy + 112); }
  if(id === 'risk'){ vault(c, fx + 184, fy + 78); rect(c, fx + 10, fy + 60, 18, 14, '#20283f'); rect(c, fx + 13, fy + 63, 12, 3, '#c0262d'); txt(c, 'STOP', fx + 11, fy + 68, P.ink); }
}
function candles(c, A, c0){
  const lo = Math.min(c0.stop, c0.support || c0.stop) * .997, hi = Math.max(c0.target, c0.resistance || c0.target) * 1.003;
  const Y = v => Math.round(A.y + A.h - 2 - (v - lo) / (hi - lo) * (A.h - 4));
  // levels first, then candles that climb (or slide) into the entry price; the levels are the real ones
  for(const [val, cc] of [[c0.target, P.good], [c0.entry, P.ink], [c0.stop, P.bad]]) for(let x = A.x; x < A.x + A.w; x += 3) rect(c, x, Y(val), 2, 1, hexA(cc, .8));
  const n = Math.floor(A.w / 3) - 1, down = c0.trend === 'down';
  let v = down ? c0.entry + (hi - c0.entry) * .7 : c0.stop + (c0.entry - c0.stop) * .2, seed = 5;
  const rnd = () => (seed = (seed * 9301 + 49297) % 233280) / 233280;
  for(let i = 0; i < n; i++){
    const goal = c0.stop + (c0.entry - c0.stop) * .2 + (c0.entry - (c0.stop + (c0.entry - c0.stop) * .2)) * (i / (n - 1));
    const o = v, cl = (down ? v - (v - c0.entry) / (n - i) : goal) + (rnd() - .5) * (hi - lo) * .1; v = Math.max(lo, Math.min(hi, cl));
    const x = A.x + 1 + i * 3, t = Math.min(Y(o), Y(v)), h = Math.max(1, Math.abs(Y(o) - Y(v)));
    rect(c, x, t - 1, 1, h + 2, '#56607a'); rect(c, x, t, 2, h, v >= o ? P.good : P.bad);
  }
}
function spark(c, A, vals, col){
  if(vals.length < 2){ txt(c, 'FILLS IN', A.x, A.y + 4, P.dim); txt(c, 'AS IT RUNS', A.x, A.y + 10, P.dim); return; }
  const lo = Math.min(...vals), hi = Math.max(...vals) || 1, n = vals.length;
  for(let i = 0; i < A.w; i++){ const v = vals[Math.floor(i / A.w * (n - 1))]; const y = A.y + A.h - 2 - (hi - lo ? (v - lo) / (hi - lo) : .5) * (A.h - 4);
    rect(c, A.x + i, Math.round(y), 1, 1, col); c.fillStyle = hexA(col, .12); c.fillRect(A.x + i, Math.round(y) + 1, 1, A.y + A.h - Math.round(y) - 1); }
}
function meter(c, B, v, col, label){
  rect(c, B.x, B.y + 6, B.w, 5, '#0a1420'); rect(c, B.x + B.w / 2, B.y + 4, 1, 9, P.dim);
  if(v != null){ const w = Math.round(Math.min(1, Math.abs(v)) * B.w / 2); rect(c, v >= 0 ? B.x + B.w / 2 : B.x + B.w / 2 - w, B.y + 7, w, 3, v >= 0 ? P.good : P.bad); }
  txt(c, label, B.x + (B.w - tw(label)) / 2, B.y + 16, v == null ? P.dim : col);
}
function bar(c, x, y, w, label, f, col){
  txt(c, label, x, y, P.dim); const bx = x + 22, bw = w - 22;
  rect(c, bx, y, bw, 5, '#0a1420'); const fw = Math.round(Math.min(1, f) * bw);
  rect(c, bx, y, Math.max(1, fw), 5, f > .75 ? P.bad : f > .4 ? P.gold : P.good);
}
function dish(c, x, y){ circle(c, x, y - 8, 7, '#c5ccd8', true); circle(c, x, y - 8, 5, '#9aa3b5', true); rect(c, x - 1, y - 8, 2, 8, '#5d6b85'); rect(c, x - 4, y, 8, 2, '#3a4a72'); rect(c, x - 1, y - 10, 2, 2, COL.scout); }
function shelf(c, x, y, names, col){
  rect(c, x, y, 26, 30, '#2a2030'); rect(c, x, y, 26, 2, '#3e3046');
  names.forEach((n, i) => { rect(c, x + 2, y + 4 + i * 8, 22, 6, ['#3a5a8a', '#6a3a5a', '#3a6a4a'][i]); rect(c, x + 3, y + 6 + i * 8, 10, 1, '#d8e2f0'); });
}
function press(c, x, y){ rect(c, x, y, 30, 22, '#3a4258'); rect(c, x, y, 30, 3, '#566080'); rect(c, x + 4, y + 6, 22, 4, '#1a1f2e'); rect(c, x + 6, y + 22, 18, 10, '#ece7dc'); for(let i = 0; i < 4; i++) rect(c, x + 8, y + 24 + i * 2, 12, 1, '#9a9384'); }
function papers(c, x, y){ for(let i = 0; i < 4; i++){ rect(c, x + i, y - i * 3, 22, 3, i % 2 ? '#d8d2c4' : '#ece7dc'); rect(c, x + i + 2, y - i * 3 + 1, 12, 1, '#7a7466'); } }
function speaker(c, x, y){ rect(c, x, y, 14, 22, '#171b26'); circle(c, x + 7, y + 7, 3, '#3a4258', true); circle(c, x + 7, y + 16, 4, '#3a4258', true); rect(c, x + 6, y + 15, 2, 2, COL.sentiment); }
function vault(c, x, y){ circle(c, x, y, 14, '#2a3045', true); circle(c, x, y, 14, '#5d6b85'); circle(c, x, y, 10, '#3a4258'); rect(c, x - 1, y - 7, 2, 14, '#8d97a6'); rect(c, x - 7, y - 1, 14, 2, '#8d97a6'); circle(c, x, y, 2, P.gold, true); }

function throneRoom(c, S){
  const r = ROOMS.captain, col = P.gold;
  // red carpet from the door to the throne
  rect(c, r.cx - 10, r.y + 92, 20, 24, '#6a141a'); rect(c, r.cx - 10, r.y + 92, 2, 24, P.gold); rect(c, r.cx + 8, r.y + 92, 2, 24, P.gold);
  // banners
  for(const bx of [r.x + 4, r.x + r.w - 18]){ rect(c, bx, r.y + 6, 14, 30, '#1a0f14'); rect(c, bx, r.y + 6, 14, 2, P.gold); rect(c, bx + 4, r.y + 14, 6, 6, '#c0262d'); rect(c, bx + 6, r.y + 16, 2, 2, P.gold); rect(c, bx, r.y + 36, 7, 3, '#1a0f14'); }
  const L = S.latest, perf = S.performance || {};
  const A = screen(c, r.x + 21, r.y + 7, 26, 30, col), B = screen(c, r.x + r.w - 47, r.y + 7, 26, 30, col);
  txt(c, 'P/L', A.x, A.y - 8, col);
  const pl = perf.profit || 0;
  txt(c, (pl >= 0 ? '+' : '-') + '$' + Math.abs(pl).toFixed(2), A.x, A.y, pl >= 0 ? P.good : P.bad, 1, 6);
  txt(c, 'HELD', B.x, B.y - 8, col); txt(c, L ? String(L.positions.length) : '0', B.x + 8, B.y + 2, P.ink, 2);
}
function beamRoom(c, S){
  const r = ROOMS.beam, perf = S.performance || {}, L = S.latest;
  const A = screen(c, r.x + 7, r.y + 7, r.w - 14, 38, P.gold, 'ACCOUNT VALUE');
  const v = perf.equity != null ? perf.equity : (L ? L.equity : 0);
  txt(c, '$' + (+v).toFixed(2), A.x + (A.w - tw('$' + (+v).toFixed(2), 2)) / 2, A.y + 1, P.ink, 2);
  const pl = perf.profit || 0, s = (pl >= 0 ? '+' : '-') + '$' + Math.abs(pl).toFixed(2) + ' SINCE START';
  txt(c, s, A.x + (A.w - tw(s)) / 2, A.y + 14, pl >= 0 ? P.good : P.bad);
  // hazard ring and the emitter base
  for(let i = 0; i < 40; i++){ const a = i / 40 * Math.PI * 2; rect(c, Math.round(EMIT.x + Math.cos(a) * 24) - 1, Math.round(EMIT.y + Math.sin(a) * 16) - 1, 3, 2, i % 2 ? P.gold : '#111'); }
  circle(c, EMIT.x, EMIT.y, 14, '#1b2440', true); circle(c, EMIT.x, EMIT.y, 10, '#2a3658', true); circle(c, EMIT.x, EMIT.y, 14, '#4a5a86');
}
function decisionExtras(c, S){
  const r = ROOMS.decision, L = S.latest, cands = L ? L.candidates : [];
  const buys = cands.filter(x => x.decision === 'BUY'), best = buys[0] || cands.slice().sort((a, b) => b.confidence - a.confidence)[0];
  const on = best ? best.decision : null;
  [['BUY', 4, 44, P.good], ['WAIT', 52, 44, P.gold], ['SKIP', 114, 42, P.bad]].forEach(([w, ox, ww, cc]) => {
    const lit = on === w, x = r.x + ox, y = r.y + 7;
    rect(c, x - 1, y - 1, ww + 2, 40, lit ? cc : P.bezel); rect(c, x, y, ww, 38, P.screen); if(lit) rect(c, x, y, ww, 38, hexA(cc, .18));
    txt(c, w, x + (ww - tw(w, 2)) / 2, y + 8, lit ? cc : '#2c3850', 2);
    if(lit && best) txt(c, Math.round(best.confidence * 100) + '%', x + (ww - tw(Math.round(best.confidence * 100) + '%')) / 2, y + 26, cc);
  });
  // conduit up the wall for the gold beam cable, and the cable hub on the floor
  rect(c, HUB.x - 3, r.y, 6, WALL, '#0b0f1a'); rect(c, HUB.x - 1, r.y, 2, WALL, '#8a6a2c');
  rect(c, HUB.x - 6, HUB.y - 5, 12, 11, '#20283f'); rect(c, HUB.x - 6, HUB.y - 5, 12, 2, P.gold); rect(c, HUB.x - 2, HUB.y, 4, 3, '#36ff7a');
  // the big red button on its pedestal
  rect(c, r.x + 120, r.y + 92, 16, 10, '#2a3045'); rect(c, r.x + 118, r.y + 100, 20, 3, '#1a2034');
  for(let i = 0; i < 20; i += 4) rect(c, r.x + 118 + i, r.y + 100, 2, 3, P.gold);
}
function lounge(c, S){
  const r = ROOMS.lounge;
  const A = screen(c, r.x + 60, r.y + 7, 88, 38, P.gold, 'TODAY');
  const L = S.latest, t = L && L.day_start_equity ? (L.equity - L.day_start_equity) / L.day_start_equity * 100 : 0;
  txt(c, (t >= 0 ? '+' : '') + t.toFixed(2) + '%', A.x, A.y + 1, t >= 0 ? P.good : P.bad, 2);
  spark(c, {x: A.x + 44, y: A.y, w: A.w - 44, h: A.h}, (S.equity || []).slice(-40).map(e => e[1]), P.gold);
  // server racks along the wall
  for(const sx of [r.x + 8, r.x + 30, r.x + 160, r.x + 182]){ rect(c, sx, r.y + 6, 18, 42, '#0b0f1a'); rect(c, sx, r.y + 6, 18, 2, '#26324f'); }
  // sofa, table, coffee machine, plants
  rect(c, r.x + 70, r.y + 70, 70, 10, '#2a3350'); rect(c, r.x + 66, r.y + 70, 6, 22, '#222a44'); rect(c, r.x + 138, r.y + 70, 6, 22, '#222a44'); rect(c, r.x + 72, r.y + 80, 66, 10, '#33406a');
  rect(c, r.x + 86, r.y + 98, 38, 8, '#20283f'); rect(c, r.x + 86, r.y + 98, 38, 2, '#2e3a5c'); rect(c, r.x + 100, r.y + 99, 4, 3, '#e9e4d8');
  rect(c, r.x + 14, r.y + 60, 14, 20, '#3a4258'); rect(c, r.x + 16, r.y + 64, 10, 5, '#11182c'); rect(c, r.x + 19, r.y + 72, 4, 4, '#e9e4d8');
  plant(c, r.x + 56, r.y + 66); plant(c, r.x + 156, r.y + 66); plant(c, r.x + 190, r.y + 112);
}

/* ---------- crew bar: 01 to 06, lights up as the courier visits ---------- */
function drawBar(c, S, active, outfit, t){
  rect(c, 0, MH, W, H - MH, '#050912'); rect(c, 0, MH, W, 1, '#1d2742');
  ORDER.forEach((id, i) => {
    const x = 4 + i * 106, y = MH + 5, w = 102, h = 38, on = id === active, st = (S.stations[id] || {}).status, col = COL[id];
    rect(c, x, y, w, h, on ? '#141d33' : '#0a1020');
    const edge = on ? P.gold : '#1d2742'; rect(c, x, y, w, 1, edge); rect(c, x, y + h - 1, w, 1, edge); rect(c, x, y, 1, h, edge); rect(c, x + w - 1, y, 1, h, edge);
    txt(c, '0' + (i + 1), x + 5, y + 5, on ? P.gold : P.dim); txt(c, id, x + 17, y + 5, col);
    const led = {found: col, buy: P.gold, working: P.good, blocked: P.bad}[st] || '#3a4560';
    rect(c, x + w - 8, y + 5, 4, 4, (st === 'blocked' && t % 1 < .5) ? '#5a1a1a' : led);
    minion(c, x + w / 2, y + h - 3, id, outfit, {k: 1, mood: on ? 'talk' : 'happy', t});
  });
}

/* ---------- the world ---------- */
function init(o){
  const stage = o.stage, canvas = o.canvas, ctx = canvas.getContext('2d');
  const map = document.createElement('canvas'); map.width = W; map.height = H; const mc = map.getContext('2d');
  const base = document.createElement('canvas'); base.width = W; base.height = H; const bc = base.getContext('2d');
  let S = o.strategy, outfit = o.outfits[S.name] || o.outfits.aggressive;
  const reduced = !!o.reduced, sfx = o.sfx || {};
  const bots = {}; ORDER.forEach(id => bots[id] = {facing: 'front', until: 2 + Math.random() * 6, mood: null, moodUntil: 0, jump: 0, splat: 0});
  const cap = {nod: 0, nodUntil: 0, glare: 0, flash: 0, splat: 0, shake: 0};
  const courier = {x: ROOMS.lounge.stop.x, y: ROOMS.lounge.stop.y, path: [], dir: 1, at: 'lounge', moving: 0};
  let fx = [], parts = [], active = null, token = 0, time = 0, beamCharge = 0, buyPulse = 0, laser = 0, flash = 0, alarm = 0;
  const say = document.createElement('div'); say.className = 'lbl'; say.innerHTML = '<div class="lbl-say"></div>'; say.style.display = 'none';
  o.labels.appendChild(say);
  let sayAt = null;

  function rebuild(){ drawStatic(bc, S, o.data); }
  rebuild();

  /* view: fit the whole map, or zoom into one room */
  const view = {x: 0, y: 0, k: 1}, goal = {x: 0, y: 0, k: 1}; let zoomed = null, cssW = 1, cssH = 1, dpr = 1;
  function fit(){ goal.k = cssW / W; goal.x = 0; goal.y = 0; zoomed = null; }
  function zoomTo(id){
    const r = ROOMS[id]; zoomed = id; const pad = 6;
    goal.k = Math.min(cssW / (r.w + pad * 2), cssH / (r.h + pad * 2));
    goal.x = r.x + r.w / 2 - cssW / goal.k / 2; goal.y = r.y + r.h / 2 - cssH / goal.k / 2;
  }
  function resize(){
    cssW = stage.clientWidth || 640; cssH = Math.round(cssW * H / W); stage.style.height = cssH + 'px'; dpr = Math.min(2, window.devicePixelRatio || 1);
    canvas.width = Math.round(cssW * dpr); canvas.height = Math.round(cssH * dpr);
    if(zoomed) zoomTo(zoomed); else fit(); Object.assign(view, goal);
  }
  new ResizeObserver(resize).observe(stage); resize();

  canvas.addEventListener('click', e => {
    const b = canvas.getBoundingClientRect(), mx = (e.clientX - b.left) / view.k + view.x, my = (e.clientY - b.top) / view.k + view.y;
    if(my >= MH){ const i = Math.floor((mx - 4) / 106); if(ORDER[i]){ o.onSelect && o.onSelect(ORDER[i]); zoomTo(ORDER[i]); } return; }
    const hit = Object.values(ROOMS).find(r => mx >= r.x && mx < r.x + r.w && my >= r.y && my < r.y + r.h);
    if(!hit || hit.id === zoomed){ fit(); return; }
    zoomTo(hit.id);
    if(ORDER.includes(hit.id) || hit.id === 'captain') o.onSelect && o.onSelect(hit.id);
  });
  canvas.style.cursor = 'pointer';

  /* courier */
  function goTo(id, tok){
    return new Promise(res => {
      const from = courier.at || 'lounge';
      courier.path = route(from, id); courier.at = null; courier.moving = 1;
      courier.done = () => { courier.at = id; courier.moving = 0; res(tok === token); };
    });
  }
  const wait = s => new Promise(r => setTimeout(r, s * 1000));
  function bubble(id, text){
    sayAt = id; say.querySelector('.lbl-say').textContent = text; say.style.display = text ? '' : 'none';
  }
  async function replay(){
    const tok = ++token; bubble(null, '');
    if(courier.at !== 'lounge'){ courier.at = courier.at || 'lounge'; }
    for(const id of ORDER){
      if(!(await goTo(id, tok))) return;
      active = id; bots[id].facing = 'front'; bots[id].until = time + 3; bots[id].talk = time + 2.2;
      o.onVisit && o.onVisit(id); sfx.beep && sfx.beep();
      bubble(id, (S.stations[id] || {}).say || '');
      await wait(2.4); if(tok !== token) return;
    }
    if(!(await goTo('captain', tok))) return;
    active = null; o.onVisit && o.onVisit('captain'); bubble('captain', S.captain || ''); cap.nodUntil = time + 1.6;
    await wait(2.6); if(tok !== token) return;
    bubble(null, '');
    if(S.event && !reduced) play(S.event.kind);
    await wait(1.5); if(tok !== token) return;
    goTo('lounge', tok);
  }

  /* effects */
  function play(kind){
    if(kind === 'win') win(); else if(kind === 'loss') loss(); else if(kind === 'buy') buy();
  }
  function crew(mood, secs){ for(const id of ORDER){ const b = bots[id]; b.mood = mood; b.moodUntil = time + secs; b.facing = 'front'; b.until = time + secs; } }
  function win(){
    beamCharge = time; sfx.laser && setTimeout(() => sfx.laser(), 450);
    setTimeout(() => { laser = time; flash = time; crew('cheer', 4); cap.flash = time + 3; cap.nodUntil = time + 3.6; sfx.cheer && sfx.cheer();
      for(let i = 0; i < 160; i++) parts.push({x: Math.random() * W, y: -Math.random() * 120, vx: (Math.random() - .5) * 30, vy: 30 + Math.random() * 50,
        c: ['#36ff7a', P.gold, '#4aa3ff', '#ff5a5a', '#b06cff', '#f7d33b', '#fff'][i % 7], life: 6}); }, 700);
  }
  function loss(){
    sfx.womp && sfx.womp(); crew('sad', 5); cap.glare = time + 4;
    const targets = ORDER.map(id => ({x: ROOMS[id].bx, y: ROOMS[id].by - 28, id})).concat([{x: 320, y: ROOMS.captain.y + 112 - 70, id: 'captain'}]);
    targets.forEach((tg, i) => setTimeout(() => {
      const sx = tg.x + (Math.random() - .5) * 120, sy = MH + 10;
      fx.push({t: 0, dur: .8, sx, sy, tg, update(dt){ this.t += dt; if(this.t >= this.dur){ splat(tg); return false; } return true; },
        draw(c){ const f = this.t / this.dur, x = this.sx + (tg.x - this.sx) * f, y = this.sy + (tg.y - this.sy) * f - Math.sin(f * Math.PI) * 70;
          circle(c, Math.round(x), Math.round(y), 3, '#d3241b', true); rect(c, Math.round(x) - 1, Math.round(y) - 4, 3, 2, '#2f8a3a'); }});
    }, i * 220));
  }
  function splat(tg){
    sfx.splat && sfx.splat();
    if(tg.id === 'captain') cap.splat = time + 4; else bots[tg.id].splat = time + 4;
    for(let i = 0; i < 14; i++){ const a = Math.random() * Math.PI * 2, v = 20 + Math.random() * 40;
      parts.push({x: tg.x, y: tg.y, vx: Math.cos(a) * v, vy: Math.sin(a) * v - 20, c: i % 3 ? '#d3241b' : '#ff6a4a', life: .8}); }
    if(tg.id === 'risk') alarm = time + 4;
  }
  function buy(){ buyPulse = time; crew('cheer', 2); sfx.cheer && sfx.cheer(); }

  /* frame */
  let last = performance.now(), visible = true;
  new IntersectionObserver(es => { visible = es[0].isIntersecting; }).observe(stage);
  function frame(now){
    requestAnimationFrame(frame);
    const dt = Math.min(.1, (now - last) / 1000); last = now;
    if(!visible || document.hidden) return;
    time += dt;
    // view easing
    const e = Math.min(1, dt * 7); view.x += (goal.x - view.x) * e; view.y += (goal.y - view.y) * e; view.k += (goal.k - view.k) * e;
    // courier
    if(courier.path.length){
      const p = courier.path[0], dx = p.x - courier.x, dy = p.y - courier.y, d = Math.hypot(dx, dy), step = 95 * dt;
      if(Math.abs(dx) > .5) courier.dir = dx > 0 ? 1 : -1;
      if(d <= step){ courier.x = p.x; courier.y = p.y; courier.path.shift(); if(!courier.path.length && courier.done){ const f = courier.done; courier.done = null; f(); } }
      else { courier.x += dx / d * step; courier.y += dy / d * step; }
    }
    // bots look up at their big screens now and then
    for(const id of ORDER){ const b = bots[id];
      if(time > b.until && !reduced){ b.facing = b.facing === 'front' ? 'back' : 'front'; b.until = time + (b.facing === 'back' ? 1.6 + Math.random() * 1.6 : 4 + Math.random() * 7); }
      if(b.mood && time > b.moodUntil) b.mood = null; }
    fx = fx.filter(f => f.update(dt));
    parts = parts.filter(p => { p.life -= dt; p.vy += 60 * dt; p.x += p.vx * dt; p.y += p.vy * dt; return p.life > 0 && p.y < H; });

    draw();
    ctx.setTransform(1, 0, 0, 1, 0, 0); ctx.imageSmoothingEnabled = false;
    ctx.fillStyle = P.void; ctx.fillRect(0, 0, canvas.width, canvas.height);
    const k = view.k * dpr; ctx.setTransform(k, 0, 0, k, -view.x * k, -view.y * k);
    ctx.drawImage(map, 0, 0);
    // speech bubble follows its bot
    if(sayAt && say.style.display !== 'none'){
      const r = ROOMS[sayAt], bx = sayAt === 'captain' ? 320 : r.bx, by = sayAt === 'captain' ? r.y + 34 : r.by - 38;
      say.style.transform = `translate(${(bx - view.x) * view.k}px, ${(by - view.y) * view.k}px) translate(-50%, -100%)`;
    }
  }
  function draw(){
    const c = mc; c.drawImage(base, 0, 0);
    const t = time;
    // clock in the back wall, live
    const d = new Date(), clock = String(d.getUTCHours()).padStart(2, '0') + (t % 1 < .5 ? ':' : ' ') + String(d.getUTCMinutes()).padStart(2, '0');
    rect(c, 290, 8, 60, 20, '#060b16'); rect(c, 290, 8, 60, 1, P.goldDark); txt(c, clock, 296, 11, '#36ff7a', 2); txt(c, 'UTC', 336, 21, P.dim);
    // radar sweep in Scout
    const rr = ROOMS.scout.radar; if(rr){ circle(c, rr.x, rr.y, rr.r, hexA(COL.scout, .35)); circle(c, rr.x, rr.y, rr.r / 2, hexA(COL.scout, .2));
      const a = t * 2.4; for(let i = 0; i < rr.r; i++) rect(c, Math.round(rr.x + Math.cos(a) * i), Math.round(rr.y + Math.sin(a) * i), 1, 1, COL.scout);
      const L = S.latest, syms = L ? Object.entries(L.scan || {}) : [];
      syms.forEach(([s, m], i) => { const ang = (s.charCodeAt(0) * 37 + i * 91) % 360 / 57.3, dist = 4 + (i * 3) % (rr.r - 4);
        const glow = ((a - ang) % 6.283 + 6.283) % 6.283 < 1.2; rect(c, Math.round(rr.x + Math.cos(ang) * dist), Math.round(rr.y + Math.sin(ang) * dist), 2, 2, m.passed ? P.gold : glow ? COL.scout : hexA(COL.scout, .4)); }); }
    // News ticker
    const tk = ROOMS.news.ticker; if(tk){ rect(c, tk.x, tk.y - 1, tk.w, 7, '#050912'); c.save(); c.beginPath(); c.rect(tk.x, tk.y - 1, tk.w, 7); c.clip();
      const wdt = tw(tk.text) + 4, off = (t * 22) % wdt; txt(c, tk.text, tk.x - off, tk.y, COL.news); txt(c, tk.text, tk.x - off + wdt, tk.y, COL.news); c.restore(); }
    // Sentiment gauge and chatter bars
    const g = ROOMS.sentiment.gauge; if(g){ for(let i = 0; i <= 12; i++){ const a = Math.PI + i / 12 * Math.PI; rect(c, Math.round(g.x + Math.cos(a) * 12), Math.round(g.y + Math.sin(a) * 12), 1, 1, i < 4 ? P.bad : i > 8 ? P.good : P.gold); }
      const v = g.v == null ? Math.sin(t * .8) * .1 : g.v, a = Math.PI * 1.5 + Math.max(-1, Math.min(1, v)) * Math.PI / 2;
      for(let i = 0; i < 10; i++) rect(c, Math.round(g.x + Math.cos(a) * i), Math.round(g.y + Math.sin(a) * i), 1, 1, P.ink); rect(c, g.x - 1, g.y - 1, 3, 3, P.gold); }
    const br = ROOMS.sentiment.bars; if(br){ for(let i = 0; i < 9; i++){ const h = br.on ? Math.max(2, Math.round((Math.sin(t * 3 + i * 1.7) * .5 + .5) * (6 + br.hype * 8))) : 1;
      rect(c, br.x + i * 6, br.y - h, 4, h, COL.sentiment); } }
    // Risk alarm light, blinks red when blocked
    const rk = ROOMS.risk, blocked = (S.stations.risk || {}).status === 'blocked' || alarm > t;
    rect(c, rk.x + 100, rk.y + 2, 8, 3, blocked && t % .6 < .3 ? '#ff3b3b' : blocked ? '#5a1a1a' : P.good);
    // server LEDs in the lounge
    for(const sx of [ROOMS.lounge.x + 8, ROOMS.lounge.x + 30, ROOMS.lounge.x + 160, ROOMS.lounge.x + 182])
      for(let j = 0; j < 6; j++) for(let i = 0; i < 3; i++) rect(c, sx + 3 + i * 5, ROOMS.lounge.y + 12 + j * 6, 2, 1, Math.sin(t * 4 + i * 7 + j * 3 + sx) > .2 ? '#36ff7a' : '#0f3a20');
    // pulses along the cables into Decision, then the gold one to the beam
    const charging = beamCharge && t - beamCharge < 1.2, buying = buyPulse && t - buyPulse < 1.6;
    for(const cb of CABLES){
      const n = cb.id === 'beam' ? 4 : 3, sp = charging ? 140 : buying ? 90 : 30;
      for(let i = 0; i < n; i++){ const p = along(cb, t * sp + i * cb.len / n);
        rect(c, Math.round(p.x) - 1, Math.round(p.y) - 1, cb.id === 'beam' ? 3 : 2, cb.id === 'beam' ? 3 : 2, charging ? '#36ff7a' : buying && cb.id === 'beam' ? '#fff3c4' : cb.col); }
    }
    // beam emitter idles with a soft pulse
    const pulse = .5 + .5 * Math.sin(t * 2), hot = charging || (laser && t - laser < 3);
    circle(c, EMIT.x, EMIT.y, 6, hot ? '#d9ffe6' : hexA('#36ff7a', .35 + pulse * .4), true);
    circle(c, EMIT.x, EMIT.y, 8 + Math.round(pulse * 2), hexA('#36ff7a', .5));
    // the bots and their desks: draw each bot, then its desk in front of it
    const sorted = ORDER.slice();
    for(const id of sorted){
      const r = ROOMS[id], b = bots[id], cheer = b.mood === 'cheer';
      const lift = cheer ? Math.abs(Math.sin(t * 9)) * 4 : 0;
      minion(c, r.bx, r.by, id, outfit, {back: b.facing === 'back' && !b.mood && !(b.talk > t), mood: b.mood || (b.talk > t ? 'talk' : 'happy'), t, lift,
        blink: t % 4 < .12, splat: b.splat > t});
      desk(c, r, id);
      if(id === 'decision'){ const pressed = buyPulse && t - buyPulse < .5; rect(c, r.x + 122, r.y + 88 + (pressed ? 2 : 0), 12, 5, '#a11'); rect(c, r.x + 122, r.y + 87 + (pressed ? 2 : 0), 12, 2, '#ff3b3b'); }
    }
    // the laser goes up behind the throne, out through the windows into the night sky
    if(laser && t - laser < 3.2){
      const f = t - laser, w = f < .2 ? f / .2 : f > 2.6 ? Math.max(0, (3.2 - f) / .6) : 1, fl = (Math.floor(t * 20) % 2);
      c.fillStyle = hexA('#36ff7a', .18 * w); c.fillRect(EMIT.x - 14, 0, 28, EMIT.y);
      c.fillStyle = hexA('#36ff7a', .9 * w); c.fillRect(EMIT.x - 5 - fl, 0, 10 + fl * 2, EMIT.y);
      c.fillStyle = hexA('#eafff0', w); c.fillRect(EMIT.x - 2, 0, 4, EMIT.y);
      circle(c, EMIT.x, EMIT.y, 10 + Math.round(f * 20) % 16, hexA('#36ff7a', .7 * w));
    }
    // the Captain nods slowly like a boss
    const nodding = cap.nodUntil > t; const nod = nodding ? (Math.sin((cap.nodUntil - t) * 2.6) > 0 ? 1 : 0) : 0;
    const shake = cap.glare > t ? (Math.sin(t * 14) > 0 ? 1 : -1) * (cap.glare - t > 3 ? 1 : 0) : 0;
    titan(c, 320, ROOMS.captain.y + 112, {nod, glare: cap.glare > t, flash: cap.flash > t && t % .5 < .3, splat: cap.splat > t, shake, cheer: cap.flash > t});
    // courier on the scooter
    const moving = courier.path.length > 0;
    scooter(c, Math.round(courier.x), Math.round(courier.y), courier.dir);
    minion(c, Math.round(courier.x) - courier.dir * 2, Math.round(courier.y) - 3, 'courier', outfit, {mood: 'happy', t, blink: t % 5 < .12});
    if(moving || courier.at && courier.at !== 'lounge'){ rect(c, Math.round(courier.x) - courier.dir * 2 + 6, Math.round(courier.y) - 22, 9, 6, P.gold); rect(c, Math.round(courier.x) - courier.dir * 2 + 7, Math.round(courier.y) - 21, 7, 1, '#7a5a1f'); }
    // win: charge, then a green laser straight up out of the beam room
    if(charging){ const f = (t - beamCharge) / 1.2; for(let i = 0; i < 3; i++) circle(c, EMIT.x, EMIT.y, Math.round(26 - ((f * 3 + i / 3) % 1) * 18), hexA('#36ff7a', .8)); }
    if(flash > 0 && t - flash < .6){ c.fillStyle = hexA('#36ff7a', .22 * (1 - (t - flash) / .6)); c.fillRect(0, 0, W, MH); }
    for(const f of fx) f.draw(c);
    for(const p of parts){ c.fillStyle = p.c; c.fillRect(Math.round(p.x), Math.round(p.y), 2, 2); }
    if(buyPulse && t - buyPulse < 1.4){ const f = (t - buyPulse) / 1.4, r = ROOMS.decision; circle(c, r.x + 128, r.y + 92, Math.round(4 + f * 40), hexA(P.gold, 1 - f)); }
    drawBar(c, S, active, outfit, t);
  }
  requestAnimationFrame(frame);
  if(!reduced) setTimeout(replay, 800);

  return {
    setStrategy(s){ S = s; outfit = o.outfits[S.name] || o.outfits.aggressive; for(const id of ORDER) delete ROOMS[id].radar, delete ROOMS[id].ticker; rebuild(); },
    replay, play
  };
}

// a single helper sprite as a picture, for the crew cards under the map
function sprite(id, outfit, scale = 4){
  const cv = document.createElement('canvas'); cv.width = 14 * scale; cv.height = 22 * scale;
  const c = cv.getContext('2d'); minion(c, 7 * scale, 21 * scale, id, outfit, {k: scale, mood: 'happy'});
  return cv.toDataURL();
}

window.PixelWorld = {init, sprite};
})();
