/* Bot World HQ: a space station drawn as flat 90s pixel art, seen from above like a floor plan.
   The Trading Wing holds one office per paper account (Aggressive, Medium, Copycat) side by side. Each office
   has six walled rooms, one per bot, with big wall screens showing the real numbers from that account's last run.
   The whole station shares one Captain's throne room and one beam room. The Forex Wing (top left) holds two
   smaller offices for the currency accounts (Forex and Copycat FX), three rooms each. One more wing sits dark,
   waiting for a future business. Bots walk between their desk and their screens, couriers on scooters carry the work from
   room to room, and the camera can be dragged, zoomed and flown from room to room. Original art. */
(function(){
'use strict';

const W = 1800, H = 1200, WALL = 52;

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
const usd = v => (v < 0 ? '-$' : '$') + Math.abs(+v || 0).toFixed(2);
const signed = v => (v >= 0 ? '+' : '-') + '$' + Math.abs(+v || 0).toFixed(2);
const clamp = (v, a, b) => Math.max(a, Math.min(b, v));
function clock(secs){
  secs = Math.max(0, Math.floor(secs));
  const h = Math.floor(secs / 3600), m = Math.floor(secs / 60) % 60, s = String(secs % 60).padStart(2, '0');
  return h ? `${h}:${String(m).padStart(2, '0')}:${s}` : `${m}:${s}`;
}

/* ---------- palette: deep navy and teal hull, gold trim, warm lights ---------- */
const P = {
  space: '#060918', plate: '#22345c', plateHi: '#3b5488', plateLo: '#121c33', rivet: '#5a74a8',
  hallA: '#10283a', hallB: '#0e2434', lane: '#3a2f17',
  tileA: '#0e1628', tileB: '#0c1323', wallTop: '#26324f', wallFace: '#141d33', seam: '#0f1729',
  bezel: '#05080f', screen: '#061018', ink: '#d8e2f0', dim: '#5d6b85', gold: '#e8b45a', goldDark: '#9c7433',
  good: '#5fd38d', bad: '#ff5a5a', desk: '#2b3757', deskTop: '#3a4a72', deskFront: '#18203a',
  yellow: '#f7d33b', yellowShade: '#d9b21f', black: '#1b1b1f', silver: '#b8c0cc', white: '#f4f6fa', pupil: '#3a2412',
  glass: '#4fb6e8'
};
const COL = {scout: '#3ddc84', charts: '#3fd0e0', news: '#4aa3ff', sentiment: '#b06cff', risk: '#ff5a5a',
             decision: '#ffa53a', captain: '#e8b45a', beam: '#36ff7a'};
const ORDER = ['scout', 'charts', 'news', 'sentiment', 'risk', 'decision'];
const NAMES = {scout: 'Scout', charts: 'Charts', news: 'News', sentiment: 'Sentiment', risk: 'Risk', decision: 'Decision'};
// office accents and carpets, one per account (light denim, dark denim, black denim)
const ACCENT = ['#8db8e3', '#4a7fd8', '#e8b45a', '#5fe0b0', '#c48cff'];
const CARPET = [['#16304f', '#142c49'], ['#141f3d', '#121c37'], ['#1d1d26', '#1a1a22'], ['#12302a', '#102b26'], ['#24183a', '#201535']];
const FX_ORDER = ['scout', 'risk', 'decision'];   // a Forex wing office: spotter, Risk, Decision
const WORKING = {found: 1, buy: 1, working: 1, blocked: 1};

/* ---------- the station plan ---------- */
const MOD = {
  forex:   {x: 100, y: 70, w: 600, h: 400},
  throne:  {x: 760, y: 70, w: 280, h: 180},
  futureB: {x: 1100, y: 70, w: 600, h: 400},
  beam:    {x: 800, y: 300, w: 200, h: 170},
  hall:    {x: 40, y: 520, w: 1720, h: 430},
  lounge:  {x: 760, y: 1000, w: 280, h: 160}
};
const EMIT = {x: 900, y: 396}, CAPTAIN = {x: 900, y: 200}, CAPSTOP = {x: 900, y: 236}, LANE = 550;
const RW = 156, RH = 130;
function officeGeo(i){
  const ox = 80 + i * 560, oy = 580, g = {i, x: ox, y: oy, w: 520, h: 340, rooms: {}, ids: ORDER};
  g.home = {x: ox + 260, y: oy + 12};
  ORDER.forEach((id, n) => {
    const row = n < 3 ? 0 : 1, j = n % 3, rx = ox + 18 + j * 164, ry = oy + 26 + row * 154;
    g.rooms[id] = {id, x: rx, y: ry, w: RW, h: RH, row, j, doorX: rx + 134, corrY: row ? oy + 325 : oy + 168,
      seat: {x: rx + 60, y: ry + 84}, looks: [{x: rx + 20, y: ry + 70}, {x: rx + 112, y: ry + 70}],
      greet: {x: rx + 106, y: ry + 108}, stop: {x: rx + 134, y: ry + 112}, hub: {x: rx + 142, y: ry + 72}};
  });
  return g;
}
// Forex wing offices: one row of three rooms, stacked in the wing above the Trading Wing's left side
const SPINE = 680, FXDOOR = 160;
function fxGeo(i, n){
  const ox = 140, oy = 96 + n * 192, g = {i, x: ox, y: oy, w: 520, h: 180, rooms: {}, ids: FX_ORDER, fx: true};
  g.home = {x: ox + 260, y: oy + 12};
  FX_ORDER.forEach((id, j) => {
    const rx = ox + 18 + j * 164, ry = oy + 26;
    g.rooms[id] = {id, x: rx, y: ry, w: RW, h: RH, row: 0, j, doorX: rx + 134, corrY: oy + 168,
      seat: {x: rx + 60, y: ry + 84}, looks: [{x: rx + 20, y: ry + 70}, {x: rx + 112, y: ry + 70}],
      greet: {x: rx + 106, y: ry + 108}, stop: {x: rx + 134, y: ry + 112}, hub: {x: rx + 142, y: ry + 72}};
  });
  return g;
}
const OFFICES = [0, 1, 2].map(officeGeo).concat([fxGeo(3, 0), fxGeo(4, 1)]);

/* ---------- corridors as a little graph, so couriers and cables find their way ---------- */
const GR = new Map();
const key = p => p.x + ',' + p.y;
function chain(...pts){
  for(let i = 1; i < pts.length; i++){
    const a = pts[i - 1], b = pts[i], ka = key(a), kb = key(b);
    if(!GR.has(ka)) GR.set(ka, {p: a, n: []}); if(!GR.has(kb)) GR.set(kb, {p: b, n: []});
    const d = Math.abs(a.x - b.x) + Math.abs(a.y - b.y);
    GR.get(ka).n.push([kb, d]); GR.get(kb).n.push([ka, d]);
  }
}
const pt = (x, y) => ({x, y});
for(const g of OFFICES){
  const ox = g.x, oy = g.y, hy = oy + 12, y1 = oy + 168, y2 = oy + 325, lx = ox + 9, rx = ox + 511;
  if(g.fx){
    // one corridor under the rooms; the office door is on the east side, onto the wing's spine
    chain(pt(lx, hy), pt(ox + 260, hy), pt(rx, hy), pt(SPINE, hy));
    chain(pt(lx, hy), pt(lx, y1)); chain(pt(rx, hy), pt(rx, y1));
    const rooms = FX_ORDER.map(id => g.rooms[id]);
    chain(pt(lx, y1), ...rooms.map(r => pt(r.doorX, y1)), pt(rx, y1));
    for(const r of rooms) chain(pt(r.doorX, r.corrY), r.stop);
    continue;
  }
  chain(pt(lx, hy), pt(ox + 260, hy), pt(rx, hy));
  chain(pt(lx, hy), pt(lx, y1), pt(lx, y2));
  chain(pt(rx, hy), pt(rx, y1), pt(rx, y2));
  const rooms = ORDER.map(id => g.rooms[id]);
  chain(pt(lx, y1), ...rooms.filter(r => !r.row).map(r => pt(r.doorX, y1)), pt(rx, y1));
  chain(pt(lx, y2), ...rooms.filter(r => r.row).map(r => pt(r.doorX, y2)), pt(rx, y2));
  for(const r of rooms) chain(pt(r.doorX, r.corrY), r.stop);
  chain(pt(ox + 260, hy), pt(ox + 260, oy), pt(ox + 260, LANE));
}
chain(pt(340, LANE), pt(900, LANE), pt(1460, LANE));
// the Forex wing's spine runs past both offices to the open door into the throne room
chain(pt(SPINE, OFFICES[3].y + 12), pt(SPINE, FXDOOR), pt(SPINE, OFFICES[4].y + 12));
chain(pt(SPINE, FXDOOR), pt(780, FXDOOR), pt(780, 236), CAPSTOP);
chain(pt(900, LANE), pt(900, 470), pt(900, 458), pt(836, 458), pt(836, 362), pt(900, 362), pt(900, 300), pt(900, 250), CAPSTOP);
function route(a, b){
  const start = key(a), goal = key(b), dist = new Map([[start, 0]]), prev = new Map(), todo = new Set([start]);
  while(todo.size){
    let u = null; for(const k of todo) if(u == null || dist.get(k) < dist.get(u)) u = k;
    todo.delete(u); if(u === goal) break;
    for(const [v, d] of (GR.get(u) || {n: []}).n){ const nd = dist.get(u) + d; if(!dist.has(v) || nd < dist.get(v)){ dist.set(v, nd); prev.set(v, u); todo.add(v); } }
  }
  if(!dist.has(goal)) return [b];
  const out = []; for(let k = goal; k; k = prev.get(k)){ out.unshift(GR.get(k).p); if(k === start) break; }
  return out;
}
// turn any polyline into straight horizontal/vertical runs, and measure it for the moving pulses
function manhattan(pts){
  const out = [pts[0]];
  for(let i = 1; i < pts.length; i++){ const a = out[out.length - 1], b = pts[i];
    if(a.x !== b.x && a.y !== b.y) out.push({x: b.x, y: a.y});
    if(a.x !== b.x || a.y !== b.y) out.push(b); }
  return out;
}
function measure(cb){
  cb.len = 0; cb.seg = [];
  for(let i = 1; i < cb.pts.length; i++){ const a = cb.pts[i - 1], b = cb.pts[i], l = Math.abs(b.x - a.x) + Math.abs(b.y - a.y); cb.seg.push({a, b, l}); cb.len += l; }
  return cb;
}
function along(cb, d){
  d = ((d % cb.len) + cb.len) % cb.len;
  for(const s of cb.seg){ if(d <= s.l){ const f = s.l ? d / s.l : 0; return {x: s.a.x + (s.b.x - s.a.x) * f, y: s.a.y + (s.b.y - s.a.y) * f}; } d -= s.l; }
  return cb.pts[cb.pts.length - 1];
}
// cables: every room to its office's Decision room, and a gold cable from each Decision to the shared beam
const LANES = {scout: -6, charts: -3, news: 0, sentiment: 3, risk: 6};
for(const g of OFFICES){
  const dec = g.rooms.decision, shift = (pts, o) => pts.map(p => ({x: p.x + o, y: p.y + o}));
  g.cables = g.ids.filter(id => id !== 'decision').map(id => {
    const r = g.rooms[id], o = LANES[id], mid = shift(route(r.stop, dec.stop), o);
    return measure({id, col: COL[id], pts: manhattan([{x: r.x + 92, y: r.y + 82}, {x: r.x + 92 + o, y: r.y + 118 + o}, ...mid, {x: dec.hub.x + o, y: dec.y + 118 + o}, {x: dec.hub.x + o, y: dec.hub.y + 4}])});
  });
  const o = (g.i - 1) * 6;
  if(g.fx){   // from the Forex wing, through the throne room and into the beam room from the top
    const mid = shift(route(dec.stop, pt(900, 300)), o);
    g.gold = measure({id: 'beam', col: P.gold, pts: manhattan([dec.hub, {x: dec.hub.x, y: dec.y + 118 + o}, ...mid.slice(1), {x: 900 + o, y: EMIT.y - 18}])});
    continue;
  }
  const mid = shift(route(dec.stop, pt(900, 470)), o);
  g.gold = measure({id: 'beam', col: P.gold, pts: manhattan([dec.hub, {x: dec.hub.x, y: dec.y + 118 + o}, ...mid.slice(1), {x: 900 + o, y: EMIT.y + 18}])});
}

/* ---------- small drawing helpers ---------- */
const rect = (c, x, y, w, h, col) => { c.fillStyle = col; c.fillRect(x, y, w, h); };
function circle(c, cx, cy, r, col, fill){
  c.fillStyle = col;
  if(fill){ for(let y = -r; y <= r; y++){ const w = Math.round(Math.sqrt(r * r - y * y)); c.fillRect(cx - w, cy + y, w * 2 + 1, 1); } return; }
  const n = Math.max(12, Math.round(r * 7));
  for(let i = 0; i < n; i++){ const a = i / n * Math.PI * 2; c.fillRect(Math.round(cx + Math.cos(a) * r), Math.round(cy + Math.sin(a) * r), 1, 1); }
}
function hexA(hex, a){ const n = parseInt(hex.slice(1), 16); return `rgba(${n >> 16},${n >> 8 & 255},${n & 255},${a})`; }
function frame(c, x, y, w, h, col){ rect(c, x, y, w, 1, col); rect(c, x, y + h - 1, w, 1, col); rect(c, x, y, 1, h, col); rect(c, x + w - 1, y, 1, h, col); }
function screen(c, x, y, w, h, col, title){
  rect(c, x - 1, y - 1, w + 2, h + 2, P.bezel); rect(c, x, y, w, h, P.screen);
  rect(c, x - 1, y - 1, w + 2, 1, hexA(col, .55));
  for(let yy = y + 1; yy < y + h; yy += 2) rect(c, x, yy, w, 1, 'rgba(255,255,255,.018)');   // scanlines
  if(title){ txt(c, title, x + 3, y + 2, col, 1, Math.floor((w - 4) / 4)); rect(c, x + 3, y + 8, w - 6, 1, hexA(col, .3)); }
  return {x: x + 3, y: y + 11, w: w - 6, h: h - 13};
}
function lines(c, arr, x, y, w, col, max = 6){
  const n = Math.floor((w + 1) / 4);
  arr.slice(0, max).forEach((s, i) => txt(c, s, x, y + i * 6, typeof col === 'function' ? col(i, s) : col, 1, n));
}
function seeded(seed){ return () => (seed = (seed * 9301 + 49297) % 233280) / 233280; }
function plant(c, x, y){
  rect(c, x - 4, y - 6, 8, 6, '#3b2a20'); rect(c, x - 4, y - 6, 8, 1, '#5a4030');
  const L = '#2f9a47', D = '#1f6e32';
  for(const [dx, dy, w, h, col] of [[-6,-12,4,3,L],[2,-13,5,3,L],[-3,-16,3,4,D],[1,-18,3,5,L],[-7,-9,3,2,D],[4,-9,4,2,D],[-1,-11,2,5,D]]) rect(c, x + dx, y + dy, w, h, col);
}
function crate(c, x, y, w, h){
  rect(c, x, y, w, h, '#5a3e24'); rect(c, x, y, w, 2, '#7a5634'); rect(c, x, y + h - 2, w, 2, '#3d2a18');
  rect(c, x + 1, y + 2, 1, h - 4, '#3d2a18'); rect(c, x + w - 2, y + 2, 1, h - 4, '#3d2a18');
  rect(c, x + Math.floor(w / 2) - 1, y, 3, h, '#a8875a');   // packing tape
  for(let i = 2; i < Math.min(w, h) - 2; i++){ rect(c, x + i, y + i, 1, 1, '#3d2a18'); }
}
function cobweb(c, x, y, sx, sy, n = 14){
  c.fillStyle = 'rgba(210,220,235,.32)';
  for(let i = 0; i < 4; i++){ const a = i / 3 * Math.PI / 2; for(let d = 0; d < n; d++) c.fillRect(Math.round(x + Math.cos(a) * d * sx), Math.round(y + Math.sin(a) * d * sy), 1, 1); }
  for(const d of [4, 8, 12]) if(d < n) for(let i = 0; i <= d; i++){ const a = i / d * Math.PI / 2; c.fillRect(Math.round(x + Math.cos(a) * d * sx), Math.round(y + Math.sin(a) * d * sy), 1, 1); }
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
// a minion-like helper with little legs, feet at (x, y). opts: back, mood (happy|sad|cheer|talk|sleep), walk (phase), splat
function minion(c, x, y, id, outfit, o = {}){
  const k = o.k || 2, L = LOOK[id] || LOOK.scout, ox = Math.round(x - 6 * k), oy = Math.round(y - 20 * k - (o.lift || 0));
  const walking = o.walk != null, step = walking ? Math.floor(o.walk * 7) % 2 : 0, bob = walking && step ? -1 : 0;
  const leg = (a, b, w, h, col) => { c.fillStyle = col; c.fillRect(ox + a * k, oy + b * k, w * k, h * k); };
  const px = (a, b, w, h, col) => { c.fillStyle = col; c.fillRect(ox + a * k, oy + (b + bob) * k, w * k, h * k); };
  const cloth = outfit.cloth, pocket = outfit.pocket, stitch = outfit.stitch;
  // legs in denim and black shoes; one foot lifts on each step
  const lu = walking && step ? 1 : 0, ru = walking && !step ? 1 : 0;
  leg(3, 16, 2, 2 - lu, cloth); leg(7, 16, 2, 2 - ru, cloth);
  leg(2, 18 - lu, 3, 2, P.black); leg(7, 18 - ru, 3, 2, P.black);
  // body
  px(2, 0, 8, 1, P.yellow); px(1, 1, 10, 14, P.yellow); px(2, 15, 8, 1, P.yellow); px(10, 2, 1, 12, P.yellowShade);
  // overalls
  px(1, 12, 10, 3, cloth); px(2, 15, 8, 1, cloth);
  if(!o.back){ px(3, 10, 6, 2, cloth); px(4, 10, 4, 1, pocket); px(1, 9, 1, 1, cloth); px(2, 10, 1, 1, cloth); px(10, 9, 1, 1, cloth); px(9, 10, 1, 1, cloth); }
  else { px(3, 9, 1, 3, cloth); px(8, 9, 1, 3, cloth); px(4, 11, 4, 1, cloth); }
  for(let i = 2; i < 10; i += 2) px(i, 13, 1, 1, stitch);
  px(5, 14, 2, 1, pocket);
  // arms swing while walking
  if(o.mood === 'cheer'){ px(0, 4, 1, 5, P.yellow); px(11, 4, 1, 5, P.yellow); px(0, 3, 1, 1, P.black); px(11, 3, 1, 1, P.black); }
  else { const sw = walking ? (step ? 1 : -1) : 0;
    px(0, 9 + sw, 1, 3, P.yellow); px(11, 9 - sw, 1, 3, P.yellow); px(0, 12 + sw, 1, 1, P.black); px(11, 12 - sw, 1, 1, P.black); }
  // head gear
  if(L.hair && !L.cap) { px(4, -1, 1, 1, P.black); px(6, -2, 1, 2, P.black); px(8, -1, 1, 1, P.black); }
  if(L.hat){ px(1, -1, 10, 2, '#ff8a1f'); px(3, -2, 6, 1, '#ff9c40'); px(0, 1, 12, 1, '#d96d10'); }
  if(L.cap){ px(2, -1, 8, 2, '#c0262d'); px(o.back ? 2 : 6, 1, 5, 1, '#8e1a20'); }
  if(L.phones){ px(1, -1, 10, 1, P.black); px(0, 3, 2, 4, COL.sentiment); px(10, 3, 2, 4, COL.sentiment); }
  // goggles and strap
  px(1, 4, 10, 2, P.black);
  if(o.back) return;
  const blink = o.blink || o.mood === 'sleep';
  if(L.eyes === 1){
    px(3, 2, 6, 6, L.frame); if(L.gold){ px(3, 2, 6, 1, P.gold); px(3, 7, 6, 1, P.gold); }
    if(L.shades) px(4, 3, 4, 4, '#ffb347');
    else { px(4, 3, 4, 4, blink ? P.yellow : P.white); if(!blink){ px(5, 4, 2, 2, P.pupil); px(6, 4, 1, 1, '#000'); } }
  } else {
    const sq = L.square;
    for(const ex of [1, 6]){
      px(ex, 3, 5, 4, L.frame); if(!sq){ px(ex, 3, 1, 1, P.yellow); px(ex + 4, 3, 1, 1, P.yellow); px(ex, 6, 1, 1, P.yellow); px(ex + 4, 6, 1, 1, P.yellow); }
      if(L.shades){ px(ex + 1, 4, 3, 2, '#ffb347'); continue; }
      px(ex + 1, 4, 3, 2, blink ? P.yellow : P.white); if(!blink) px(ex + 2, 4, 1, 2, P.pupil);
    }
    if(L.visor) px(1, 2, 10, 1, '#4aa3ff');
  }
  // mouth
  const m = o.mood;
  if(m === 'sad'){ px(4, 9, 1, 1, P.pupil); px(5, 8, 2, 1, P.pupil); px(7, 9, 1, 1, P.pupil); }
  else if(m === 'cheer' || (m === 'talk' && o.t % .3 < .15)){ px(4, 8, 4, 2, '#3a1a10'); px(5, 9, 2, 1, '#ff7a7a'); }
  else if(m === 'sleep'){ px(5, 9, 2, 1, P.pupil); }
  else { px(4, 8, 1, 1, P.pupil); px(5, 9, 2, 1, P.pupil); px(7, 8, 1, 1, P.pupil); }
  if(o.splat){ px(2, 2, 3, 2, '#d3241b'); px(6, 1, 2, 3, '#c8261c'); px(4, 5, 4, 1, '#e0321f'); px(8, 3, 2, 2, '#d3241b'); }
}
function scooter(c, x, y, dir){
  // deck, two wheels, stem and handlebar; dir 1 = moving right
  rect(c, x - 13, y - 3, 26, 3, '#9aa3b5'); rect(c, x - 13, y - 3, 26, 1, '#d6dce6');
  rect(c, x - 14, y, 6, 4, '#111'); rect(c, x + 8, y, 6, 4, '#111'); rect(c, x - 12, y + 1, 2, 2, '#777'); rect(c, x + 10, y + 1, 2, 2, '#777');
  const sx = x + dir * 12; rect(c, sx - 1, y - 34, 2, 32, '#c0262d'); rect(c, sx - 5, y - 35, 10, 2, '#111');
  rect(c, sx + dir * 2 - 1, y - 31, 2, 2, '#fff6c8');
}
function desk(c, x, y, col){
  rect(c, x - 26, y, 52, 9, P.desk); rect(c, x - 26, y, 52, 2, P.deskTop); rect(c, x - 26, y + 9, 52, 6, P.deskFront);
  rect(c, x - 24, y + 15, 3, 3, '#0b0f1a'); rect(c, x + 21, y + 15, 3, 3, '#0b0f1a');
  // backs of the desk monitors, glowing in the room's color
  for(const mx of [-24, 13]){ rect(c, x + mx, y - 7, 11, 8, '#0b0f1a'); rect(c, x + mx, y - 8, 11, 1, hexA(col, .8)); rect(c, x + mx + 4, y, 3, 1, '#0b0f1a'); }
  rect(c, x - 8, y + 2, 16, 3, '#11182c'); for(let i = 0; i < 7; i++) rect(c, x - 7 + i * 2, y + 3, 1, 1, '#3a4a72');
  rect(c, x + 10, y + 1, 3, 3, '#e9e4d8');   // mug
}
// the Captain: an original chrome titan with black armor and red trim, seated on a black and red throne
function titan(c, x, y, s){
  const k = s.k || 2, px = (a, b, w, h, col) => { c.fillStyle = col; c.fillRect(x + a * k, y + b * k, w * k, h * k); };
  const C = '#c9d1dc', CL = '#f2f5f9', CM = '#8d97a6', CD = '#5a6270', B = '#18161c', R = '#c0262d', G = P.gold;
  const eye = s.glare ? '#ff7a7a' : s.flash ? '#ffd38a' : '#ff3b3b';
  // throne
  px(-17, -46, 34, 34, '#141018'); px(-17, -46, 34, 1, R); px(-17, -46, 1, 34, R); px(16, -46, 1, 34, R);
  for(const sx of [-15, -7, 1, 9]) { px(sx + 2, -50, 2, 4, G); px(sx + 2, -52, 2, 2, '#ffd98f'); }
  px(-3, -44, 6, 3, R); px(-1, -45, 2, 1, G);
  px(-15, -12, 30, 6, '#1d1822'); px(-15, -12, 30, 1, '#3a2b38');
  px(-19, -18, 6, 12, '#141018'); px(13, -18, 6, 12, '#141018'); px(-19, -18, 6, 1, R); px(13, -18, 6, 1, R);
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
  const hy = -38 + (s.nod || 0), hx = s.shake || 0;
  px(-5 + hx, hy, 10, 9, C); px(-5 + hx, hy, 10, 1, CL); px(4 + hx, hy + 1, 1, 8, CM);
  px(-4 + hx, hy + 3, 8, 5, B); px(-3 + hx, hy + 4, 2, 1, eye); px(1 + hx, hy + 4, 2, 1, eye);
  if(s.glare || s.flash){ c.fillStyle = hexA(s.flash ? '#ffd38a' : '#ff3b3b', .35); c.fillRect(x + (-4 + hx) * k, y + (hy + 3) * k, 8 * k, 3 * k); }
  px(-2 + hx, hy + 7, 4, 1, R);
  px(-7 + hx, hy - 2, 2, 5, B); px(5 + hx, hy - 2, 2, 5, B); px(-8 + hx, hy - 4, 1, 3, R); px(7 + hx, hy - 4, 1, 3, R);
  px(-1 + hx, hy - 3, 2, 3, G);
  if(s.splat){ px(-3 + hx, hy + 1, 3, 2, '#d3241b'); px(1 + hx, hy - 1, 3, 3, '#c8261c'); }
}

/* ---------- space, hull plating, tubes and windows ---------- */
const STARS = (() => { const r = seeded(11), out = []; for(let i = 0; i < 1300; i++){ const b = r();
  out.push({x: Math.floor(r() * W), y: Math.floor(r() * H), c: b < .7 ? '#8fa3d6' : b < .92 ? '#ffffff' : '#ffd98f', s: r() < .07 ? 2 : 1, tw: r() < .06}); } return out; })();
function space(c){
  rect(c, 0, 0, W, H, P.space);
  // soft pixel nebulae in purple and teal
  for(const [cx, cy, R, col] of [[260, 1080, 340, '#5a2a8a'], [1520, 1000, 320, '#1f6a7e'], [1640, 60, 260, '#6a2a72'], [80, 300, 240, '#1f4a7e'], [900, 1200, 260, '#3a2a7a']])
    for(let i = 0; i < 8; i++) circle(c, cx, cy, Math.round(R * (1 - i / 9)), hexA(col, .045), true);
  for(const s of STARS) rect(c, s.x, s.y, s.s, s.s, s.c);
  // a ringed planet and a small moon
  const px = 1560, py = 1092, pr = 78, bands = ['#c76a3a', '#e08a4a', '#b55a34', '#f0a868', '#9a4a2e', '#d97a44'];
  const ring = back => { for(let i = 0; i < 260; i++){ const a = i / 260 * Math.PI * 2, y = Math.sin(a); if((y < 0) !== back) continue;
    for(const [rx, col] of [[132, '#e8c48a'], [124, '#b8946a'], [116, '#e8c48a']]) rect(c, Math.round(px + Math.cos(a) * rx), Math.round(py + y * 22), 2, 1, col); } };
  ring(true);
  for(let y = -pr; y <= pr; y++){ const w = Math.round(Math.sqrt(pr * pr - y * y)); rect(c, px - w, py + y, w * 2 + 1, 1, bands[Math.floor((y + pr) / 13) % bands.length]);
    rect(c, px + Math.round(w * .45), py + y, Math.round(w * .55) + 1, 1, 'rgba(10,6,20,.35)'); }
  ring(false);
  circle(c, 250, 1110, 26, '#8a8fa0', true); circle(c, 258, 1104, 26, '#a9adbb', true);
  for(const [x, y, r] of [[244, 1102, 5], [262, 1116, 4], [270, 1098, 3]]) circle(c, x, y, r, '#7a7f90', true);
}
function hull(c, m, pad = 8){
  const x = m.x - pad, y = m.y - pad, w = m.w + pad * 2, h = m.h + pad * 2;
  rect(c, x - 2, y - 2, w + 4, h + 4, '#0a1122');
  rect(c, x, y, w, h, P.plate); rect(c, x, y, w, 2, P.plateHi); rect(c, x, y, 2, h, P.plateHi); rect(c, x, y + h - 2, w, 2, P.plateLo); rect(c, x + w - 2, y, 2, h, P.plateLo);
  frame(c, m.x - 3, m.y - 3, m.w + 6, m.h + 6, P.gold);
  for(let i = x + 10; i < x + w - 6; i += 24){ rect(c, i, y + 2, 2, 2, P.rivet); rect(c, i, y + h - 4, 2, 2, P.rivet); }
  for(let i = y + 10; i < y + h - 6; i += 24){ rect(c, x + 2, i, 2, 2, P.rivet); rect(c, x + w - 4, i, 2, 2, P.rivet); }
}
function tube(c, x, y, w, h){
  rect(c, x, y, w, h, P.plate);
  const vert = h > w;
  if(vert){ rect(c, x + 6, y, w - 12, h, '#16243c'); rect(c, x + 5, y, 1, h, P.gold); rect(c, x + w - 6, y, 1, h, P.gold); for(let i = y + 4; i < y + h; i += 10) rect(c, x + 2, i, 2, 4, P.rivet); }
  else { rect(c, x, y + 6, w, h - 12, '#16243c'); rect(c, x, y + 5, w, 1, P.gold); rect(c, x, y + h - 6, w, 1, P.gold); for(let i = x + 4; i < x + w; i += 10) rect(c, i, y + 2, 4, 2, P.rivet); }
}
function windowH(c, x, y, w, dim){
  rect(c, x, y, w, 5, '#0a1530'); rect(c, x, y + 1, w, 3, dim ? '#13213d' : hexA(P.glass, .55));
  if(!dim) for(let i = x + 3; i < x + w - 4; i += 17){ rect(c, i, y + 1, 2, 1, '#d6f2ff'); rect(c, i + 2, y + 2, 1, 1, '#d6f2ff'); }
}
function windowV(c, x, y, h, dim){
  rect(c, x, y, 5, h, '#0a1530'); rect(c, x + 1, y, 3, h, dim ? '#13213d' : hexA(P.glass, .55));
  if(!dim) for(let i = y + 3; i < y + h - 4; i += 17) rect(c, x + 1, i, 1, 2, '#d6f2ff');
}
function floor(c, x, y, w, h, a, b, s = 8){
  for(let yy = y; yy < y + h; yy += s) for(let xx = x; xx < x + w; xx += s) rect(c, xx, yy, Math.min(s, x + w - xx), Math.min(s, y + h - yy), ((xx - x + yy - y) / s) % 2 ? a : b);
}
// a walled room: tiled floor, a tall north wall for the big screens, a neon baseboard, a south door
function room(c, r, col, doors = []){
  floor(c, r.x, r.y, r.w, r.h, P.tileA, P.tileB);
  c.fillStyle = hexA(col, .05); c.fillRect(r.x, r.y, r.w, r.h);
  rect(c, r.x, r.y, r.w, WALL, P.wallFace);
  for(let x = r.x + 26; x < r.x + r.w; x += 26) rect(c, x, r.y + 4, 1, WALL - 7, P.seam);
  rect(c, r.x, r.y, r.w, 4, P.wallTop); rect(c, r.x, r.y + 3, r.w, 1, '#33416a');
  rect(c, r.x, r.y + WALL - 3, r.w, 2, col); c.fillStyle = hexA(col, .22); c.fillRect(r.x, r.y + WALL - 1, r.w, 4);
  rect(c, r.x, r.y, 4, r.h, P.wallTop); rect(c, r.x + r.w - 4, r.y, 4, r.h, P.wallTop); rect(c, r.x, r.y + r.h - 4, r.w, 4, P.wallTop);
  for(const d of doors){
    if(d.side === 'S'){ rect(c, d.x - 12, r.y + r.h - 4, 24, 4, P.tileB); rect(c, d.x - 13, r.y + r.h - 4, 1, 4, col); rect(c, d.x + 12, r.y + r.h - 4, 1, 4, col); }
    if(d.side === 'N'){ rect(c, d.x - 12, r.y, 24, WALL - 3, '#0c1424'); rect(c, d.x - 13, r.y, 1, WALL - 3, col); rect(c, d.x + 12, r.y, 1, WALL - 3, col); }
    if(d.side === 'W' || d.side === 'E'){ const wx = d.side === 'W' ? r.x : r.x + r.w - 4; rect(c, wx, d.y - 12, 4, 24, P.tileB); rect(c, wx, d.y - 13, 4, 1, col); rect(c, wx, d.y + 12, 4, 1, col); }
  }
}

/* ---------- each office: six rooms, wall screens with the run's real numbers ---------- */
function officeStatic(c, g, S){
  const acc = ACCENT[g.i], [ca, cb] = CARPET[g.i], ox = g.x, oy = g.y;
  floor(c, ox, oy, g.w, g.h, ca, cb, 10);
  // corridors inside the office are a little lighter, with gold guide dashes for the couriers
  const halls = g.fx ? [oy + 156] : [oy + 156, oy + 310], dashes = g.fx ? [oy + 168] : [oy + 168, oy + 325];
  for(const y of halls) rect(c, ox, y, g.w, y === oy + 156 ? 24 : 30, '#1a2442');
  rect(c, ox, oy, g.w, 26, '#1a2442'); rect(c, ox, oy, 18, g.h, '#1a2442'); rect(c, ox + g.w - 18, oy, 18, g.h, '#1a2442');
  for(let x = ox + 12; x < ox + g.w - 12; x += 8) for(const y of dashes) rect(c, x, y, 4, 1, P.lane);
  for(let y = oy + 16; y < oy + g.h - 8; y += 8) for(const x of [ox + 9, ox + 511]) rect(c, x, y, 1, 4, P.lane);
  // outer walls with the account's accent light and a door to the wing hall
  rect(c, ox - 4, oy - 4, g.w + 8, 4, P.wallTop); rect(c, ox - 4, oy + g.h, g.w + 8, 4, P.wallTop);
  rect(c, ox - 4, oy - 4, 4, g.h + 8, P.wallTop); rect(c, ox + g.w, oy - 4, 4, g.h + 8, P.wallTop);
  rect(c, ox, oy, g.w, 1, acc); rect(c, ox, oy + g.h - 1, g.w, 1, hexA(acc, .6));
  if(g.fx){ rect(c, ox + g.w - 1, oy, 6, 24, '#1a2442'); rect(c, ox + g.w - 1, oy - 1, 6, 1, acc); rect(c, ox + g.w - 1, oy + 24, 6, 1, acc); }
  else { rect(c, ox + 248, oy - 4, 24, 5, '#1a2442'); rect(c, ox + 247, oy - 4, 1, 5, acc); rect(c, ox + 272, oy - 4, 1, 5, acc); }
  // sign and account value
  const name = (S.title || S.name || ['aggressive', 'medium', 'copycat', 'forex', 'copycat fx'][g.i]) + ' office';
  txt(c, name, ox + 24, oy + 8, acc, 2);
  const perf = S.performance || {}, v = perf.equity != null ? perf.equity : (S.latest ? S.latest.equity : 0), pl = perf.profit || 0;
  const vs = usd(v); txt(c, vs, ox + g.w - 26 - tw(vs, 2), oy + 8, P.ink, 2);
  const ps = signed(pl); txt(c, ps, ox + g.w - 26 - tw(vs, 2) - tw(ps) - 8, oy + 12, pl >= 0 ? P.good : P.bad);
  for(const id of g.ids){
    const r = g.rooms[id];
    room(c, r, COL[id], [{side: 'S', x: r.doorX}]);
  }
  // floor cables, drawn before the furniture so desks sit on top
  for(const cb of g.cables) cable(c, cb, hexA(cb.col, .5), 1);
  cable(c, g.gold, '#8a6a2c', 3); cable(c, g.gold, P.gold, 1);
  for(const id of g.ids) roleStatic(c, g, g.rooms[id], id, S);
}
function cable(c, cb, col, w){
  c.fillStyle = col;
  for(const s of cb.seg){ const x = Math.min(s.a.x, s.b.x), y = Math.min(s.a.y, s.b.y);
    c.fillRect(Math.round(x - (w >> 1)), Math.round(y - (w >> 1)), Math.round(Math.abs(s.b.x - s.a.x)) + w, Math.round(Math.abs(s.b.y - s.a.y)) + w); }
}
function roleStatic(c, g, r, id, S){
  const col = COL[id], st = (S.stations || {})[id] || {say: 'Waiting for the first run.', status: 'idle'}, L = S.latest, cands = L ? (L.candidates || []) : [];
  const c0 = cands[0], isCopy = S.name === 'copycat', f = L && L.filings || {};
  if(S.wing === 'forex') return fxRoleStatic(c, g, r, id, S, st);
  const titles = {scout: isCopy ? 'FILINGS' : 'SCANNER', charts: c0 && c0.entry ? short(c0.symbol) + ' PLAN' : 'ACCOUNT', news: 'HEADLINES',
                  sentiment: 'MOOD    HYPE', risk: 'LIMITS', decision: 'THE CALL'};
  const A = screen(c, r.x + 6, r.y + 6, 72, 42, col, titles[id]), C = screen(c, r.x + 82, r.y + 6, 68, 42, col, 'STATUS');
  r.dyn = {};
  if(id === 'scout'){
    if(isCopy){
      const top = f.top || [];
      lines(c, top.length ? top.map(t => `${t.ticker} $${fmtP(t.usd)}`) : [`READ ${f.read || 0}`, `WATCH ${f.watchlist || 0}`, 'NO BIG BUYS'], A.x, A.y, A.w, P.ink, 4);
    } else {
      const scan = L ? Object.entries(L.scan || {}).sort((a, b) => b[1].volume_ratio - a[1].volume_ratio) : [];
      lines(c, scan.length ? scan.map(([s, m]) => `${short(s).padEnd(4)}${(m.volume_ratio.toFixed(1) + 'X').padStart(4)}`) : ['NO SCAN', 'THIS RUN'],
        A.x, A.y, 36, (i) => scan[i] && scan[i][1].passed ? col : P.ink, 4);
      r.dyn.radar = {x: A.x + 53, y: A.y + 14, r: 11, syms: scan};
    }
  } else if(id === 'charts'){
    if(c0 && c0.entry){
      candles(c, {x: A.x, y: A.y, w: 38, h: A.h}, c0);
      [[fmtP(c0.target), P.good], [fmtP(c0.entry), P.ink], [fmtP(c0.stop), P.bad]].forEach(([s, cc], i) => txt(c, s, A.x + 42, A.y + i * 8, cc, 1, 6));
      if(c0.reward_risk) txt(c, 'RR ' + c0.reward_risk, A.x + 42, A.y + 24, P.dim, 1, 6);
    } else spark(c, A, (S.equity || []).map(e => e[1]), col);
  } else if(id === 'news'){
    lines(c, wrap(c0 ? (c0.news || 'NO RECENT NEWS') : (isCopy && f.top && f.top[0] ? f.top[0].note : 'NO HEADLINES TO READ'), 16), A.x, A.y, A.w, P.ink, 3);
    const sc = c0 && c0.news_score != null ? c0.news_score : null;
    rect(c, A.x, A.y + 22, 40, 5, '#0a1420'); rect(c, A.x + 20, A.y + 20, 1, 9, P.dim);
    if(sc != null){ const w = Math.round(Math.min(1, Math.abs(sc)) * 20); rect(c, sc >= 0 ? A.x + 20 : A.x + 20 - w, A.y + 23, w, 3, sc >= 0 ? P.good : P.bad); }
    txt(c, sc == null ? 'NONE' : (sc >= 0 ? '+' : '') + sc.toFixed(2), A.x + 44, A.y + 22, sc == null ? P.dim : col);
    r.dyn.ticker = {x: r.x + 6, y: r.y + 47, w: r.w - 12, text: (cands.map(x => short(x.symbol) + ': ' + (x.news || '')).join('   ') || st.say) + '   '};
  } else if(id === 'sentiment'){
    const sc = c0 && c0.sentiment_score != null ? c0.sentiment_score : null;
    r.dyn.gauge = {x: A.x + 15, y: A.y + 20, v: sc};
    r.dyn.bars = {x: A.x + 34, y: A.y + 28, hype: c0 ? (c0.hype || 0) : 0, on: !!c0};
  } else if(id === 'risk'){
    const lim = S.limits || {max_daily_loss_pct: 1, max_total_loss_pct: 1};
    const today = L && L.day_start_equity ? (L.equity - L.day_start_equity) / L.day_start_equity * 100 : 0;
    const perf = S.performance || {}, tot = perf.net_deposits ? Math.min(0, perf.profit) / perf.net_deposits * 100 : 0;
    bar(c, A.x, A.y, A.w, 'DAY', Math.max(0, -today) / lim.max_daily_loss_pct);
    bar(c, A.x, A.y + 7, A.w, 'TOTAL', Math.max(0, -tot) / lim.max_total_loss_pct);
    bar(c, A.x, A.y + 14, A.w, 'HELD', L ? Math.min(1, (L.positions || []).length / 4) : 0);
    const v = c0 ? (c0.risk === 'REJECT' ? ['REJECT', P.bad] : /RED|SHR|SIZE/.test(c0.risk || '') ? ['REDUCE', P.gold] : ['APPROVE', P.good]) : ['NO TRADE', P.dim];
    txt(c, v[0], A.x, A.y + 23, v[1]);
    r.dyn.alarm = {x: r.x + 74, y: r.y + 1};
  } else if(id === 'decision'){
    const buys = cands.filter(x => x.decision === 'BUY'), best = buys[0] || cands.slice().sort((a, b) => b.confidence - a.confidence)[0];
    const on = best ? best.decision : null;
    [['BUY', P.good], ['WAIT', P.gold], ['SKIP', P.bad]].forEach(([w, cc], i) => {
      const x = A.x + i * 22, y = A.y + 1, lit = on === w;
      rect(c, x, y, 20, 14, lit ? hexA(cc, .25) : '#0a1420'); frame(c, x, y, 20, 14, lit ? cc : '#1d2a40');
      txt(c, w, x + Math.round((20 - tw(w)) / 2), y + 5, lit ? cc : '#2c3850');
      if(lit && best){ const p = Math.round(best.confidence * 100) + '%'; txt(c, p, x + Math.round((20 - tw(p)) / 2), A.y + 18, cc); }
    });
    if(S.min_confidence) txt(c, 'NEEDS ' + Math.round(S.min_confidence * 100) + '%', A.x, A.y + 24, P.dim);
    // the cable hub and the big red button
    rect(c, r.hub.x - 6, r.hub.y - 5, 12, 11, '#20283f'); rect(c, r.hub.x - 6, r.hub.y - 5, 12, 2, P.gold); rect(c, r.hub.x - 2, r.hub.y, 4, 3, '#36ff7a');
    rect(c, r.x + 8, r.y + 80, 18, 10, '#2a3045'); for(let i = 0; i < 18; i += 4) rect(c, r.x + 8 + i, r.y + 88, 2, 2, P.gold);
  }
  lines(c, wrap(st.say, 15), C.x, C.y, C.w, P.ink, 5);
  // floor props: a plant in the corner and one prop for the job
  plant(c, r.x + 13, r.y + 124);
  const px = r.x + 142, py = r.y + 56;
  if(id === 'scout'){ circle(c, px, py + 12, 7, '#c5ccd8', true); circle(c, px, py + 12, 5, '#9aa3b5', true); rect(c, px - 1, py + 12, 2, 9, '#5d6b85'); rect(c, px - 4, py + 21, 8, 2, '#3a4a72'); rect(c, px - 1, py + 10, 2, 2, col); }
  if(id === 'charts'){ rect(c, px - 7, py, 14, 28, '#2a2030'); for(let i = 0; i < 3; i++){ rect(c, px - 5, py + 3 + i * 8, 10, 6, ['#3a5a8a', '#6a3a5a', '#3a6a4a'][i]); rect(c, px - 4, py + 5 + i * 8, 6, 1, '#d8e2f0'); } }
  if(id === 'news'){ for(let i = 0; i < 5; i++){ rect(c, px - 8 + (i % 2), py + 26 - i * 4, 16, 4, i % 2 ? '#d8d2c4' : '#ece7dc'); rect(c, px - 6 + (i % 2), py + 27 - i * 4, 9, 1, '#7a7466'); } }
  if(id === 'sentiment'){ rect(c, px - 7, py, 14, 24, '#171b26'); circle(c, px, py + 7, 3, '#3a4258', true); circle(c, px, py + 17, 4, '#3a4258', true); rect(c, px - 1, py + 16, 2, 2, col); }
  if(id === 'risk'){ circle(c, px - 1, py + 14, 9, '#2a3045', true); circle(c, px - 1, py + 14, 9, '#5d6b85'); rect(c, px - 2, py + 8, 2, 12, '#8d97a6'); rect(c, px - 7, py + 13, 12, 2, '#8d97a6'); circle(c, px - 1, py + 14, 2, P.gold, true); }
  namePlate(c, r, id, S);
}
function namePlate(c, r, id, S){
  const col = COL[id];
  // the name plate below the desk; the level is static, the run timer is drawn live
  rect(c, r.x + 22, r.y + 95, 76, 16, '#070b16'); rect(c, r.x + 22, r.y + 95, 76, 1, P.goldDark); rect(c, r.x + 22, r.y + 95, 1, 16, col);
  const lv = (S.levels || {})[id] || 1;
  txt(c, `${NAMES[id]} LV ${lv}`, r.x + 26, r.y + 98, P.gold, 1, 17);
}
// Forex wing rooms: the spotter's board of pairs (or the hedge funds' bets), Risk's limits, and the call
function fxRoleStatic(c, g, r, id, S, st){
  const col = COL[id], L = S.latest, fx = L && L.forex || {}, pairs = Object.entries(fx.pairs || {}), cot = fx.style === 'cot';
  const A = screen(c, r.x + 6, r.y + 6, 72, 42, col, id === 'scout' ? (cot ? 'FUNDS BET' : 'PAIRS') : id === 'risk' ? 'LIMITS' : 'THE CALL');
  const C = screen(c, r.x + 82, r.y + 6, 68, 42, col, 'STATUS');
  r.dyn = {};
  if(id === 'scout'){
    if(!pairs.length) lines(c, ['WAITING FOR', 'THE DAY TO', 'END: 5PM NY'], A.x, A.y, A.w, P.dim, 3);
    else if(cot){ const bets = pairs.filter(([, x]) => x.net != null).sort((a, b) => Math.abs(b[1].net) - Math.abs(a[1].net));
      lines(c, bets.map(([, x]) => `${x.ccy} ${(x.net >= 0 ? '+' : '') + x.net.toFixed(0)}%`), A.x, A.y, A.w, (i) => bets[i] && bets[i][1].direction ? col : P.ink, 4); }
    else lines(c, pairs.map(([p, x]) => `${p.replace('_', '').slice(0, 6)} ${x.direction > 0 ? 'UP' : x.direction < 0 ? 'DN' : '--'}`), A.x, A.y, A.w,
      (i) => pairs[i] && pairs[i][1].direction ? col : P.ink, 4);
  } else if(id === 'risk'){
    const lim = S.limits || {max_daily_loss_pct: 1, max_total_loss_pct: 1};
    const today = L && L.day_start_equity ? (L.equity - L.day_start_equity) / L.day_start_equity * 100 : 0;
    const perf = S.performance || {}, tot = perf.net_deposits ? Math.min(0, perf.profit) / perf.net_deposits * 100 : 0;
    bar(c, A.x, A.y, A.w, 'DAY', Math.max(0, -today) / lim.max_daily_loss_pct);
    bar(c, A.x, A.y + 7, A.w, 'TOTAL', Math.max(0, -tot) / lim.max_total_loss_pct);
    bar(c, A.x, A.y + 14, A.w, 'HELD', L ? Math.min(1, (L.positions || []).length / 4) : 0);
    txt(c, 'MAX 3:1', A.x, A.y + 23, P.dim);
    r.dyn.alarm = {x: r.x + 74, y: r.y + 1};
  } else {
    const calls = pairs.map(([, x]) => x.decision), on = calls.includes('BUY') ? 'BUY' : calls.includes('SELL') ? 'SELL' : 'WAIT';
    [['BUY', P.good], ['SELL', P.bad], ['WAIT', P.gold]].forEach(([w, cc], i) => {
      const x = A.x + i * 22, y = A.y + 1, lit = on === w;
      rect(c, x, y, 20, 14, lit ? hexA(cc, .25) : '#0a1420'); frame(c, x, y, 20, 14, lit ? cc : '#1d2a40');
      txt(c, w, x + Math.round((20 - tw(w)) / 2), y + 5, lit ? cc : '#2c3850');
    });
    const n = L ? (L.positions || []).length : 0; txt(c, `${n} OPEN`, A.x, A.y + 20, P.dim);
    rect(c, r.hub.x - 6, r.hub.y - 5, 12, 11, '#20283f'); rect(c, r.hub.x - 6, r.hub.y - 5, 12, 2, P.gold); rect(c, r.hub.x - 2, r.hub.y, 4, 3, '#36ff7a');
    rect(c, r.x + 8, r.y + 80, 18, 10, '#2a3045'); for(let i = 0; i < 18; i += 4) rect(c, r.x + 8 + i, r.y + 88, 2, 2, P.gold);
  }
  lines(c, wrap(st.say, 15), C.x, C.y, C.w, P.ink, 5);
  plant(c, r.x + 13, r.y + 124);
  const px = r.x + 142, py = r.y + 56;
  if(id === 'scout'){   // a little globe: currencies trade around the clock, around the world
    circle(c, px, py + 12, 8, '#1f5a8a', true); rect(c, px - 5, py + 8, 4, 3, '#3a9a5a'); rect(c, px + 1, py + 13, 5, 4, '#3a9a5a'); circle(c, px, py + 12, 8, '#9aa3b5');
    rect(c, px - 1, py + 20, 2, 3, '#5d6b85'); rect(c, px - 5, py + 23, 10, 2, '#3a4a72'); }
  if(id === 'risk'){ circle(c, px - 1, py + 14, 9, '#2a3045', true); circle(c, px - 1, py + 14, 9, '#5d6b85'); rect(c, px - 2, py + 8, 2, 12, '#8d97a6'); rect(c, px - 7, py + 13, 12, 2, '#8d97a6'); circle(c, px - 1, py + 14, 2, P.gold, true); }
  namePlate(c, r, id, S);
}
function candles(c, A, c0){
  const lo = Math.min(c0.stop, c0.support || c0.stop) * .997, hi = Math.max(c0.target, c0.resistance || c0.target) * 1.003;
  const Y = v => Math.round(A.y + A.h - 2 - (v - lo) / (hi - lo) * (A.h - 4));
  // levels first, then candles that climb (or slide) into the entry price; the levels are the real ones
  for(const [val, cc] of [[c0.target, P.good], [c0.entry, P.ink], [c0.stop, P.bad]]) for(let x = A.x; x < A.x + A.w; x += 3) rect(c, x, Y(val), 2, 1, hexA(cc, .8));
  const n = Math.floor(A.w / 3) - 1, down = c0.trend === 'down';
  let v = down ? c0.entry + (hi - c0.entry) * .7 : c0.stop + (c0.entry - c0.stop) * .2;
  const rnd = seeded(5);
  for(let i = 0; i < n; i++){
    const base = c0.stop + (c0.entry - c0.stop) * .2, goal = base + (c0.entry - base) * (i / (n - 1));
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
function bar(c, x, y, w, label, f){
  txt(c, label, x, y, P.dim); const bx = x + 22, bw = w - 22;
  rect(c, bx, y, bw, 5, '#0a1420'); const fw = Math.round(Math.min(1, f) * bw);
  rect(c, bx, y, Math.max(1, fw), 5, f > .75 ? P.bad : f > .4 ? P.gold : P.good);
}

/* ---------- the shared rooms ---------- */
function throneStatic(c, D, names){
  const T = MOD.throne;
  room(c, T, P.gold, [{side: 'S', x: 900}, {side: 'W', y: 160}, {side: 'E', y: 160}]);
  c.fillStyle = 'rgba(120,20,30,.12)'; c.fillRect(T.x + 4, T.y + WALL, T.w - 8, T.h - WALL - 4);
  // a big window onto space behind the throne
  const wx = T.x + 70, ww = 140, wy = T.y + 6, wh = 40;
  rect(c, wx - 2, wy - 2, ww + 4, wh + 4, P.goldDark); rect(c, wx, wy, ww, wh, '#070c22');
  const r = seeded(3); for(let i = 0; i < 40; i++) rect(c, wx + Math.floor(r() * ww), wy + Math.floor(r() * wh), 1, 1, r() < .8 ? '#c9d6ff' : '#ffd98f');
  for(let y = 0; y < 14; y++){ const w = Math.round(Math.sqrt(30 * 30 - (y - 14) * (y - 14)) * 1.6); rect(c, wx + 104 - w / 2, wy + wh - 14 + y, w, 1, y < 2 ? '#7fd8ff' : '#14305a'); }
  for(let x = wx + 34; x < wx + ww; x += 35) rect(c, x, wy, 2, wh, P.goldDark);
  // banners and the red carpet
  for(const bx of [T.x + 10, T.x + T.w - 24]){ rect(c, bx, T.y + 6, 14, 34, '#1a0f14'); rect(c, bx, T.y + 6, 14, 2, P.gold); rect(c, bx + 4, T.y + 16, 6, 6, '#c0262d'); rect(c, bx + 6, T.y + 18, 2, 2, P.gold); rect(c, bx, T.y + 40, 7, 3, '#1a0f14'); }
  rect(c, 890, CAPTAIN.y - 4, 20, T.y + T.h - CAPTAIN.y, '#6a141a'); rect(c, 890, CAPTAIN.y - 4, 2, T.y + T.h - CAPTAIN.y, P.gold); rect(c, 908, CAPTAIN.y - 4, 2, T.y + T.h - CAPTAIN.y, P.gold);
  // wing totals on two screens
  let pl = 0, held = 0, runs = 0;
  for(const n of names){ const S = D.strategies[n]; pl += (S.performance || {}).profit || 0; held += S.latest ? (S.latest.positions || []).length : 0; runs += S.runs || 0; }
  const A = screen(c, T.x + 14, T.y + 64, 50, 32, P.gold, 'HQ P/L'), B = screen(c, T.x + T.w - 64, T.y + 64, 50, 32, P.gold, 'HELD');
  txt(c, signed(pl), A.x, A.y + 4, pl >= 0 ? P.good : P.bad, 1, 11);
  txt(c, String(held), B.x + Math.round((B.w - tw(String(held), 2)) / 2), B.y + 2, P.ink, 2);
  rect(c, T.x + 14, T.y + 150, 70, 16, '#070b16'); rect(c, T.x + 14, T.y + 150, 70, 1, P.goldDark);
  txt(c, `CAPTAIN LV ${1 + Math.floor(runs / 10)}`, T.x + 18, T.y + 153, P.gold);
  txt(c, 'THRONE ROOM', T.x + T.w - 14 - tw('THRONE ROOM'), T.y + T.h - 14, P.goldDark);
}
function beamStatic(c, D, names){
  const B = MOD.beam;
  room(c, B, '#36ff7a', [{side: 'N', x: 900}, {side: 'S', x: 900}]);
  let total = 0;
  const A = screen(c, B.x + 6, B.y + 6, 80, 44, P.gold, 'HQ VALUE'), R = screen(c, B.x + 114, B.y + 6, 80, 44, P.gold, 'OFFICES');
  names.forEach((n, i) => { const S = D.strategies[n], perf = S.performance || {}, v = perf.equity != null ? perf.equity : (S.latest ? S.latest.equity : 0); total += +v || 0;
    txt(c, (n === 'fxcopy' ? 'fxc' : n.slice(0, 3)) + ' ' + usd(v), R.x, R.y + i * 6, ACCENT[i], 1, 18); });
  const s = usd(total); txt(c, s, A.x + Math.max(0, Math.round((A.w - tw(s, 2)) / 2)), A.y + 6, P.ink, 2);
  for(let i = 0; i < 44; i++){ const a = i / 44 * Math.PI * 2; rect(c, Math.round(EMIT.x + Math.cos(a) * 26) - 1, Math.round(EMIT.y + Math.sin(a) * 17) - 1, 3, 2, i % 2 ? P.gold : '#111'); }
  circle(c, EMIT.x, EMIT.y, 14, '#1b2440', true); circle(c, EMIT.x, EMIT.y, 10, '#2a3658', true); circle(c, EMIT.x, EMIT.y, 14, '#4a5a86');
  txt(c, 'BEAM ROOM', B.x + 10, B.y + B.h - 14, '#2f9a5a');
}
function loungeStatic(c, D, names){
  const L = MOD.lounge;
  room(c, L, P.gold, [{side: 'N', x: 900}]);
  // today's change for each office
  const A = screen(c, L.x + 8, L.y + 6, 106, 44, P.gold, 'TODAY');
  names.forEach((n, i) => { const R = D.strategies[n].latest, t = R && R.day_start_equity ? (R.equity - R.day_start_equity) / R.day_start_equity * 100 : 0;
    txt(c, D.strategies[n].title || n, A.x, A.y + i * 6, ACCENT[i], 1, 11); const s = (t >= 0 ? '+' : '') + t.toFixed(2) + '%'; txt(c, s, A.x + A.w - tw(s), A.y + i * 6, t >= 0 ? P.good : P.bad); });
  // two arcade cabinets and a row of servers
  for(const ax of [L.x + 190, L.x + 222]){ rect(c, ax, L.y + 10, 24, 40, '#2a1640'); rect(c, ax, L.y + 10, 24, 3, '#b06cff'); rect(c, ax + 4, L.y + 16, 16, 12, '#061018');
    rect(c, ax + 6, L.y + 34, 3, 3, '#ff5a5a'); rect(c, ax + 14, L.y + 34, 3, 3, '#3ddc84'); rect(c, ax + 2, L.y + 42, 20, 2, '#e8b45a'); }
  for(let i = 0; i < 4; i++){ const sx = L.x + 124 + i * 15; rect(c, sx, L.y + 8, 12, 40, '#0b0f1a'); rect(c, sx, L.y + 8, 12, 2, '#26324f'); }
  // sofa, table, coffee machine, plants
  rect(c, L.x + 90, L.y + 90, 100, 10, '#3a2a58'); rect(c, L.x + 84, L.y + 90, 8, 30, '#2e2248'); rect(c, L.x + 188, L.y + 90, 8, 30, '#2e2248'); rect(c, L.x + 92, L.y + 100, 96, 14, '#4a3670');
  rect(c, L.x + 112, L.y + 124, 56, 10, '#20283f'); rect(c, L.x + 112, L.y + 124, 56, 2, '#2e3a5c'); rect(c, L.x + 132, L.y + 125, 4, 3, '#e9e4d8'); rect(c, L.x + 146, L.y + 125, 4, 3, '#e9e4d8');
  rect(c, L.x + 14, L.y + 64, 16, 22, '#3a4258'); rect(c, L.x + 16, L.y + 68, 12, 6, '#11182c'); rect(c, L.x + 20, L.y + 78, 4, 4, '#e9e4d8');
  plant(c, L.x + 60, L.y + 86); plant(c, L.x + 230, L.y + 86); plant(c, L.x + 260, L.y + 150); plant(c, L.x + 16, L.y + 150);
  txt(c, 'BREAK ROOM', L.x + 40, L.y + L.h - 14, P.goldDark);
}
function futureStatic(c, m, label, flip){
  floor(c, m.x, m.y, m.w, m.h, '#0d1422', '#0b111d', 10);
  // empty offices waiting for a new business: walls, sheet-covered desks, crates and cobwebs
  const rooms = [{x: m.x + 16, y: m.y + 60, w: 180, h: 150}, {x: m.x + 210, y: m.y + 60, w: 180, h: 150}, {x: m.x + 404, y: m.y + 60, w: 180, h: 150},
                 {x: m.x + 16, y: m.y + 236, w: 280, h: 150}, {x: m.x + 304, y: m.y + 236, w: 280, h: 150}];
  for(const r of rooms){
    floor(c, r.x, r.y, r.w, r.h, '#111a2c', '#0f1726');
    rect(c, r.x, r.y, r.w, 34, '#121a2c'); rect(c, r.x, r.y, r.w, 4, '#1f2940');
    rect(c, r.x, r.y, 4, r.h, '#1f2940'); rect(c, r.x + r.w - 4, r.y, 4, r.h, '#1f2940'); rect(c, r.x, r.y + r.h - 4, r.w, 4, '#1f2940');
    rect(c, r.x + r.w / 2 - 12, r.y + r.h - 4, 24, 4, '#0f1726');
    for(let x = r.x + 10; x < r.x + r.w - 40; x += 46){ rect(c, x, r.y + 8, 36, 22, '#05080f'); rect(c, x + 1, r.y + 9, 34, 20, '#0a0f18'); }   // dark screens
    cobweb(c, r.x + 4, r.y + 34, 1, 1, 16); cobweb(c, r.x + r.w - 5, r.y + 34, -1, 1, 13);
  }
  const rnd = seeded(flip ? 41 : 17);
  // dust sheets over the furniture
  for(const r of rooms){ const n = r.w > 200 ? 2 : 1;
    for(let i = 0; i < n; i++){ const x = r.x + 30 + i * 120 + Math.floor(rnd() * 20), y = r.y + 60 + Math.floor(rnd() * 20);
      rect(c, x, y, 50, 18, '#5a6170'); rect(c, x + 2, y - 2, 46, 3, '#6a7182'); rect(c, x, y + 18, 50, 3, '#454b58'); for(let j = 6; j < 48; j += 9) rect(c, x + j, y + 18, 3, 4, '#454b58'); } }
  // stacks of moving boxes
  for(let i = 0; i < 14; i++){ const r = rooms[i % rooms.length], w = 16 + Math.floor(rnd() * 10), h = 12 + Math.floor(rnd() * 6);
    const x = r.x + 10 + Math.floor(rnd() * (r.w - 40)), y = r.y + r.h - 24 - Math.floor(rnd() * 40); crate(c, x, y, w, h); if(rnd() < .5) crate(c, x + 3, y - h + 3, w - 6, h - 2); }
  for(let i = 0; i < 6; i++) crate(c, m.x + 30 + i * 22 + (i > 2 ? 300 : 0), m.y + 20, 18, 14);
  // dust and a big stencil on the corridor floor
  for(let i = 0; i < 160; i++) rect(c, m.x + Math.floor(rnd() * m.w), m.y + Math.floor(rnd() * m.h), 1, 1, 'rgba(160,170,190,.18)');
  c.fillStyle = 'rgba(0,3,10,.5)'; c.fillRect(m.x, m.y, m.w, m.h);
  txt(c, 'FUTURE BUSINESS', m.x + 220, m.y + 26, '#2c3850', 2);
  txt(c, label, m.x + m.w / 2 - tw(label, 3) / 2, m.y + 216, '#273148', 3);
  cobweb(c, m.x, m.y, 1, 1, 22); cobweb(c, m.x + m.w - 1, m.y, -1, 1, 22); cobweb(c, m.x, m.y + m.h - 1, 1, -1, 18);
  // locked door toward the throne room
  const dx = flip ? m.x : m.x + m.w - 4;
  rect(c, dx, 148, 4, 24, '#5a1a1a'); rect(c, dx, 158, 4, 4, '#ff3b3b');
  txt(c, 'LOCKED', flip ? m.x + 8 : m.x + m.w - 8 - tw('LOCKED'), 157, '#a33a3a');
}
function forexWingStatic(c, m){
  floor(c, m.x, m.y, m.w, m.h, P.hallA, P.hallB, 16);
  // the spine corridor to the throne room, with gold guide dashes, and an open, lit door
  rect(c, SPINE - 16, m.y + 26, 32, m.h - 30, '#14283c');
  for(let y = m.y + 34; y < m.y + m.h - 8; y += 10) rect(c, SPINE, y, 1, 5, P.lane);
  for(let x = SPINE; x < m.x + m.w; x += 10) rect(c, x, FXDOOR, 5, 1, P.lane);
  const dx = m.x + m.w - 4; rect(c, dx, FXDOOR - 12, 4, 24, P.hallB); rect(c, dx, FXDOOR - 13, 4, 1, '#5fe0b0'); rect(c, dx, FXDOOR + 12, 4, 1, '#5fe0b0');
  txt(c, 'FOREX WING', m.x + 40, m.y + 8, P.gold, 2);
  // three world clocks: forex trades around the clock, from Tokyo to London to New York
  for(const [i, city] of [[0, 'TOKYO'], [1, 'LONDON'], [2, 'NEW YORK']]){ const x = m.x + 250 + i * 104;
    rect(c, x, m.y + 4, 96, 18, P.bezel); rect(c, x + 1, m.y + 5, 94, 16, P.screen); txt(c, city, x + 4, m.y + 8, P.dim); }
  for(const y of [m.y + 120, m.y + 300]) plant(c, SPINE + 8, y);
}
function hallStatic(c){
  const h = MOD.hall;
  floor(c, h.x, h.y, h.w, h.h, P.hallA, P.hallB, 16);
  // warm light pools and gold guide lines along the hall
  for(let x = h.x + 100; x < h.x + h.w; x += 220) for(let i = 0; i < 4; i++) circle(c, x, LANE, 46 - i * 10, 'rgba(255,190,110,.025)', true);
  for(let x = h.x + 10; x < h.x + h.w - 10; x += 10){ rect(c, x, LANE, 5, 1, P.lane); rect(c, x, 935, 5, 1, P.lane); }
  for(const x of [620, 1180]) for(let y = 590; y < 920; y += 10) rect(c, x, y, 1, 5, P.lane);
  txt(c, 'TRADING WING', h.x + 40, h.y + 18, P.gold, 3);
  txt(c, 'TRADING WING', h.x + h.w - 40 - tw('TRADING WING', 3), h.y + 18, P.gold, 3);
  for(const x of [h.x + 20, h.x + h.w - 20]) for(const y of [h.y + 70, h.y + 250, h.y + 410]) plant(c, x, y);
  for(const x of [620, 1180]){ plant(c, x, 600); plant(c, x, 912); rect(c, x - 8, 740, 16, 28, '#2a3350'); rect(c, x - 8, 740, 16, 3, '#3a4a72'); }
}
function drawStatic(c, D, names){
  space(c);
  // solar wings and an antenna on the outside of the station
  for(const [x, y] of [[14, 130], [1716, 130]]){ rect(c, x + 30, y + 100, 56, 6, '#3a4560');
    for(let i = 0; i < 2; i++){ const py = y + i * 124; rect(c, x, py, 70, 116, '#0c1a3a'); frame(c, x, py, 70, 116, '#6a7ca8');
      for(let yy = py + 4; yy < py + 112; yy += 12) for(let xx = x + 4; xx < x + 66; xx += 16) rect(c, xx, yy, 14, 10, '#1a3a7a'); } }
  rect(c, 899, 18, 2, 44, '#8d97a6'); rect(c, 893, 30, 14, 2, '#8d97a6'); rect(c, 889, 44, 22, 2, '#8d97a6');
  for(const m of Object.values(MOD)) hull(c, m, m === MOD.hall ? 10 : 8);
  tube(c, 700, 146, 60, 28); tube(c, 1040, 146, 60, 28);
  tube(c, 886, 250, 28, 50); tube(c, 886, 470, 28, 50); tube(c, 886, 950, 28, 50);
  // windows in the outer hull
  for(let x = MOD.hall.x + 20; x < MOD.hall.x + MOD.hall.w - 60; x += 70) if(Math.abs(x + 20 - 900) > 70){ windowH(c, x, MOD.hall.y - 8, 40); windowH(c, x, MOD.hall.y + MOD.hall.h + 3, 40); }
  for(let y = MOD.hall.y + 30; y < MOD.hall.y + MOD.hall.h - 40; y += 70){ windowV(c, MOD.hall.x - 8, y, 40); windowV(c, MOD.hall.x + MOD.hall.w + 3, y, 40); }
  for(let x = MOD.forex.x + 30; x < MOD.forex.x + MOD.forex.w - 40; x += 80) windowH(c, x, MOD.forex.y - 7, 40);
  for(let x = MOD.futureB.x + 30; x < MOD.futureB.x + MOD.futureB.w - 40; x += 80) windowH(c, x, MOD.futureB.y - 7, 40, true);
  for(const m of [MOD.beam, MOD.lounge]){ windowV(c, m.x - 7, m.y + 60, 50); windowV(c, m.x + m.w + 2, m.y + 60, 50); }
  forexWingStatic(c, MOD.forex);
  futureStatic(c, MOD.futureB, 'COMING SOON', true);
  hallStatic(c);
  OFFICES.forEach((g, i) => officeStatic(c, g, D.strategies[names[i]] || {name: ['aggressive', 'medium', 'copycat', 'forex', 'fxcopy'][i],
    wing: g.fx ? 'forex' : null, stations: {}}));
  throneStatic(c, D, names); beamStatic(c, D, names); loungeStatic(c, D, names);
}

/* ---------- the world ---------- */
function init(o){
  const stage = o.stage, canvas = o.canvas, ctx = canvas.getContext('2d'), D = o.data;
  const names = Object.keys(D.strategies).slice(0, OFFICES.length);   // one office per account: 3 trading, 2 forex
  const map = document.createElement('canvas'); map.width = W; map.height = H; const mc = map.getContext('2d');
  const base = document.createElement('canvas'); base.width = W; base.height = H; const bc = base.getContext('2d');
  const reduced = !!o.reduced, sfx = o.sfx || {};
  let cur = Math.max(0, names.indexOf(o.current));
  const outfit = i => o.outfits[names[i]] || o.outfits.aggressive;
  const strat = i => D.strategies[names[i]] || {stations: {}};
  drawStatic(bc, D, names);

  /* bots: every office has six, each with a desk, two screen spots and a spot by the door */
  let time = 0;
  const offices = OFFICES.map((g, i) => {
    const S = strat(i), bots = {};
    for(const id of g.ids){ const r = g.rooms[id], st = (S.stations || {})[id] || {};
      bots[id] = {id, r, x: r.seat.x, y: r.seat.y, path: [], at: 'seat', next: null, until: 1 + Math.random() * 6, face: 'front', walk: 0,
        working: !!WORKING[st.status], talk: 0, mood: null, moodUntil: 0, splat: 0}; }
    return {g, i, bots, courier: {x: g.home.x, y: g.home.y, at: g.home, path: [], dir: 1, done: null}};
  });
  const cap = {nodUntil: 0, glare: 0, flash: 0, splat: 0};
  const spots = b => ({seat: b.r.seat, look0: b.r.looks[0], look1: b.r.looks[1], greet: b.r.greet});
  function walkTo(b, where, stay){
    const r = b.r, aisle = r.x + 98, from = b.path.length ? b.path[b.path.length - 1] : {x: b.x, y: b.y}, to = spots(b)[where], pts = [];
    // in-room paths go around the desk: along the seat row, and down the aisle beside the desk to the door
    if(from.y > r.seat.y + 4){ pts.push({x: aisle, y: from.y}, {x: aisle, y: r.seat.y}); }
    else if(from.y < r.seat.y - 4){ pts.push({x: from.x, y: r.seat.y}); }
    if(where === 'greet'){ pts.push({x: aisle, y: r.seat.y}, {x: aisle, y: to.y}, to); }
    else if(where === 'seat'){ pts.push(to); }
    else { pts.push({x: to.x, y: r.seat.y}, to); }
    b.path = b.path.concat(pts.filter((p, i, a) => !i || p.x !== a[i - 1].x || p.y !== a[i - 1].y)); b.next = where; b.stay = stay; b.at = null;
  }
  function updateBot(b, dt){
    if(b.mood && time > b.moodUntil) b.mood = null;
    if(b.path.length){
      const p = b.path[0], dx = p.x - b.x, dy = p.y - b.y, d = Math.hypot(dx, dy), step = 34 * dt;
      b.face = dy < -.5 ? 'back' : 'front'; b.walk += dt;
      if(d <= step){ b.x = p.x; b.y = p.y; b.path.shift(); if(!b.path.length){ b.at = b.next; b.until = time + (b.stay || 3); b.face = b.at.startsWith('look') ? 'back' : 'front'; } }
      else { b.x += dx / d * step; b.y += dy / d * step; }
      return;
    }
    if(time < b.until) return;
    if(b.at !== 'seat') return walkTo(b, 'seat', 4 + Math.random() * 6);
    if(b.working && !reduced) return walkTo(b, Math.random() < .5 ? 'look0' : 'look1', 2.5 + Math.random() * 2.5);
    b.until = time + 6;
  }

  /* camera: drag to move, scroll or pinch to zoom, click to fly to a room */
  let cssW = 1, cssH = 1, dpr = 1;
  const view = {x: W / 2, y: H / 2, k: .4}, goal = {x: W / 2, y: H / 2, k: .4};
  const fitK = () => Math.min(cssW / W, cssH / H) * .98;
  function clampGoal(){ goal.k = clamp(goal.k, fitK() * .9, 4); goal.x = clamp(goal.x, 0, W); goal.y = clamp(goal.y, 0, H); }
  function fly(r, pad = 8){ fitted = false; goal.k = Math.min(cssW / (r.w + pad * 2), cssH / (r.h + pad * 2)); goal.x = r.x + r.w / 2; goal.y = r.y + r.h / 2; clampGoal(); if(reduced) Object.assign(view, goal); }
  function fit(){ fly({x: 0, y: 0, w: W, h: H}, 0); goal.k = fitK(); focus = null; fitted = true; if(reduced) Object.assign(view, goal); }
  function zoomAt(sx, sy, k){
    const wx = goal.x + (sx - cssW / 2) / goal.k, wy = goal.y + (sy - cssH / 2) / goal.k;
    fitted = false; goal.k = clamp(k, fitK() * .9, 4); goal.x = wx - (sx - cssW / 2) / goal.k; goal.y = wy - (sy - cssH / 2) / goal.k; clampGoal(); focus = null;
  }
  let first = true, focus = null, fitted = true;
  function resize(){
    cssW = stage.clientWidth || 640; cssH = stage.clientHeight || 480; dpr = Math.min(2, window.devicePixelRatio || 1);
    canvas.width = Math.round(cssW * dpr); canvas.height = Math.round(cssH * dpr);
    if(first || fitted){ fit(); if(first) Object.assign(view, goal); first = false; } else clampGoal();
  }
  new ResizeObserver(resize).observe(stage); resize();
  const toWorld = (sx, sy) => ({x: view.x + (sx - cssW / 2) / view.k, y: view.y + (sy - cssH / 2) / view.k});
  const inside = (p, r) => p.x >= r.x && p.x < r.x + r.w && p.y >= r.y && p.y < r.y + r.h;
  function click(sx, sy){
    const p = toWorld(sx, sy);
    for(const ofc of offices) for(const b of Object.values(ofc.bots))
      if(Math.abs(p.x - b.x) < 14 && p.y > b.y - 42 && p.y < b.y + 2) return pick(ofc.i, b.id);
    if(inside(p, {x: 840, y: 90, w: 120, h: 130})) return pick(cur, 'captain');
    for(const ofc of offices){
      for(const id of ofc.g.ids){ const r = ofc.g.rooms[id]; if(inside(p, r)){ if(focus === ofc.i + id) return flyOffice(ofc.i); return pick(ofc.i, id); } }
      if(inside(p, ofc.g)){ if(focus === 'o' + ofc.i){ fit(); return; } return flyOffice(ofc.i, true); }
    }
    for(const [k, m] of Object.entries(MOD)) if(inside(p, m)){ if(focus === k || k === 'hall'){ fit(); return; } if(k === 'throne') return pick(cur, 'captain'); focus = k; return fly(m, 12); }
    fit();
  }
  function flyOffice(i, select){ fly(OFFICES[i], 12); focus = 'o' + i; if(select && i !== cur) o.onSelect && o.onSelect(null, names[i]); }
  function pick(i, id){
    if(id === 'captain'){ fly(MOD.throne, 6); focus = 'throne'; }
    else { fly(OFFICES[i].rooms[id], 4); focus = i + id; }
    o.onSelect && o.onSelect(id, names[i]);
  }
  canvas.style.touchAction = 'none'; canvas.style.cursor = 'grab';
  const ptrs = new Map(); let drag = null;
  canvas.addEventListener('pointerdown', e => { canvas.setPointerCapture(e.pointerId); ptrs.set(e.pointerId, {x: e.offsetX, y: e.offsetY});
    drag = {x: e.offsetX, y: e.offsetY, moved: false, multi: ptrs.size > 1, d: null}; canvas.style.cursor = 'grabbing'; });
  canvas.addEventListener('pointermove', e => {
    if(!ptrs.has(e.pointerId) || !drag) return;
    const prev = ptrs.get(e.pointerId), now = {x: e.offsetX, y: e.offsetY}; ptrs.set(e.pointerId, now);
    if(ptrs.size === 2){
      const [a, b] = [...ptrs.values()], d = Math.hypot(a.x - b.x, a.y - b.y), mx = (a.x + b.x) / 2, my = (a.y + b.y) / 2;
      if(drag.d){ zoomAt(mx, my, goal.k * d / drag.d); goal.x -= (mx - drag.mx) / goal.k; goal.y -= (my - drag.my) / goal.k; clampGoal(); Object.assign(view, goal); }
      drag.d = d; drag.mx = mx; drag.my = my; drag.moved = drag.multi = true; return;
    }
    if(Math.hypot(now.x - drag.x, now.y - drag.y) > 5) drag.moved = true;
    if(drag.moved){ fitted = false; goal.x -= (now.x - prev.x) / goal.k; goal.y -= (now.y - prev.y) / goal.k; clampGoal(); view.x = goal.x; view.y = goal.y; view.k = goal.k; focus = null; }
  });
  const up = e => { if(!ptrs.has(e.pointerId)) return; ptrs.delete(e.pointerId);
    if(!ptrs.size){ if(drag && !drag.moved && !drag.multi && e.type === 'pointerup') click(e.offsetX, e.offsetY); drag = null; canvas.style.cursor = 'grab'; }
    else if(drag) drag.d = null; };
  canvas.addEventListener('pointerup', up); canvas.addEventListener('pointercancel', up);
  canvas.addEventListener('wheel', e => { e.preventDefault(); zoomAt(e.offsetX, e.offsetY, goal.k * Math.exp(-clamp(e.deltaY, -120, 120) * .0022)); }, {passive: false});
  canvas.addEventListener('keydown', e => {
    const s = 60 / goal.k, k = {ArrowLeft: [-s, 0], ArrowRight: [s, 0], ArrowUp: [0, -s], ArrowDown: [0, s]}[e.key];
    if(k){ goal.x += k[0]; goal.y += k[1]; clampGoal(); e.preventDefault(); }
    else if(e.key === '+' || e.key === '='){ zoomAt(cssW / 2, cssH / 2, goal.k * 1.4); e.preventDefault(); }
    else if(e.key === '-'){ zoomAt(cssW / 2, cssH / 2, goal.k / 1.4); e.preventDefault(); }
    else if(e.key === '0' || e.key === 'Escape') fit();
  });

  /* the crew list on the left */
  const panel = o.panel, rows = [];
  const lastRun = i => { const L = strat(i).latest; return L && L.time ? new Date(L.time).getTime() : null; };
  function buildPanel(){
    if(!panel) return;
    rows.length = 0;
    const esc = s => String(s == null ? '' : s).replace(/[&<>"']/g, ch => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[ch]));
    let work = 0, idle = 0, h = '';
    const S0 = strat(cur), runs = names.reduce((a, n) => a + (D.strategies[n].runs || 0), 0);
    h += `<button type="button" class="crew-row cap" data-i="${cur}" data-id="captain"><img alt="" src="${capPic}"><span class="cr-main"><span class="cr-name">Captain <i>Lv ${1 + Math.floor(runs / 10)}</i></span><span class="cr-say">${esc(S0.captain || '')}</span></span><span class="cr-side"><span class="cr-chip on">Watching</span></span></button>`;
    offices.forEach(ofc => {
      const S = strat(ofc.i), perf = S.performance || {}, v = perf.equity != null ? perf.equity : (S.latest ? S.latest.equity : 0);
      h += `<div class="crew-grp${ofc.i === cur ? ' sel' : ''}"><button type="button" class="crew-office" data-i="${ofc.i}"><span>${esc(S.title || names[ofc.i] || '')} office</span><b>${usd(v)}</b></button>`;
      for(const id of ofc.g.ids){
        const st = (S.stations || {})[id] || {}, on = !!WORKING[st.status]; on ? work++ : idle++;
        h += `<button type="button" class="crew-row" data-i="${ofc.i}" data-id="${id}"><img alt="" src="${sprite(id, outfit(ofc.i), 2)}"><span class="cr-main"><span class="cr-name">${NAMES[id]} <i>Lv ${(S.levels || {})[id] || 1}</i></span><span class="cr-say">${esc(st.say || '')}</span></span><span class="cr-side"><span class="cr-chip ${on ? 'work' : 'idle'}">${on ? 'Working' : 'Idle'}</span><span class="cr-time" data-t="${ofc.i}"></span></span></button>`;
      }
      h += '</div>';
    });
    panel.innerHTML = `<div class="crew-top"><span class="crew-title">Crew</span><span><b class="up">${work}</b> working · <b>${idle}</b> idle</span><span class="crew-next" id="crew-next"></span></div><div class="crew-list">${h}</div>`;
    panel.querySelectorAll('.crew-row').forEach(b => b.onclick = () => pick(+b.dataset.i, b.dataset.id));
    panel.querySelectorAll('.crew-office').forEach(b => b.onclick = () => { flyOffice(+b.dataset.i); if(+b.dataset.i !== cur) o.onSelect && o.onSelect(null, names[+b.dataset.i]); });
    tick();
  }
  function tick(){
    if(!panel) return;
    const now = Date.now();
    panel.querySelectorAll('.cr-time').forEach(el => { const t = lastRun(+el.dataset.t); el.textContent = t ? clock((now - t) / 1000) : '-'; });
    const t = lastRun(cur), nx = panel.querySelector('#crew-next');
    if(nx) nx.textContent = !t ? 'Waiting for the first run' : (t + 30 * 60e3 > now ? `Next run in about ${clock((t + 30 * 60e3 - now) / 1000)}` : 'Next run any minute');
  }
  const capPic = (() => { const cv = document.createElement('canvas'); cv.width = 44; cv.height = 56; const c = cv.getContext('2d'); titan(c, 22, 54, {k: 1}); return cv.toDataURL(); })();
  buildPanel(); setInterval(tick, 1000);

  /* speech bubble for the office you're looking at */
  const say = document.createElement('div'); say.className = 'lbl'; say.innerHTML = '<div class="lbl-say"></div>'; say.style.display = 'none';
  o.labels.appendChild(say);
  let sayAt = null;
  function bubble(at, text){ sayAt = at; say.querySelector('.lbl-say').textContent = text || ''; say.style.display = text ? '' : 'none'; }

  /* couriers: one per office, they carry the run from room to room, and the one you're watching reports to the Captain */
  let token = 0;
  const wait = s => new Promise(r => setTimeout(r, s * 1000));
  function goTo(cr, to, tok){
    return new Promise(res => {
      const start = cr.path.length ? cr.path[0] : cr.at || {x: cr.x, y: cr.y};
      cr.path = route(start, to); cr.at = null;
      cr.done = () => { cr.at = to; res(tok === token); };
    });
  }
  async function round(ofc, tok){
    const main = ofc.i === cur, S = strat(ofc.i), cr = ofc.courier;
    for(const id of ofc.g.ids){
      if(!(await goTo(cr, ofc.g.rooms[id].stop, tok))) return;
      const b = ofc.bots[id]; walkTo(b, 'greet', main ? 3.4 : 2.2); b.talk = time + (main ? 3.2 : 2);
      if(main){ o.onVisit && o.onVisit(id); sfx.beep && sfx.beep(); bubble(b, ((S.stations || {})[id] || {}).say || ''); }
      await wait(main ? 2.8 : 1.6); if(tok !== token) return;
    }
    if(main){
      if(!(await goTo(cr, CAPSTOP, tok))) return;
      o.onVisit && o.onVisit('captain'); bubble('captain', S.captain || ''); cap.nodUntil = time + 1.6;
      await wait(2.8); if(tok !== token) return;
      bubble(null, '');
      if(S.event && !reduced) play(S.event.kind);
      await wait(1.5); if(tok !== token) return;
    }
    goTo(cr, ofc.g.home, tok);
  }
  function replay(){ const tok = ++token; bubble(null, ''); offices.forEach(ofc => round(ofc, tok)); }

  /* effects for the office you're watching */
  let clocks = [];
  let fx = [], parts = [], beamCharge = 0, buyPulse = 0, laser = 0, flash = 0, alarm = 0, fxOffice = cur;
  function play(kind){ fxOffice = cur; if(kind !== 'win' && fitted) flyOffice(cur); if(kind === 'win') win(); else if(kind === 'loss') loss(); else if(kind === 'buy') buy(); }
  function crew(mood, secs){ for(const b of Object.values(offices[cur].bots)){ b.mood = mood; b.moodUntil = time + secs; } }
  function win(){
    beamCharge = time; sfx.laser && setTimeout(() => sfx.laser(), 450);
    setTimeout(() => { laser = time; flash = time; crew('cheer', 4); cap.flash = time + 3; cap.nodUntil = time + 3.6; sfx.cheer && sfx.cheer();
      const g = OFFICES[cur];
      for(let i = 0; i < 220; i++){ const inOffice = i % 3; parts.push({x: inOffice ? g.x + Math.random() * g.w : 760 + Math.random() * 280, y: (inOffice ? g.y - 60 : 60) - Math.random() * 120,
        vx: (Math.random() - .5) * 30, vy: 30 + Math.random() * 50, c: ['#36ff7a', P.gold, '#4aa3ff', '#ff5a5a', '#b06cff', '#f7d33b', '#fff'][i % 7], life: 6}); } }, 900);
  }
  function loss(){
    sfx.womp && sfx.womp(); crew('sad', 5); cap.glare = time + 4;
    const ofc = offices[cur], targets = ofc.g.ids.map(id => ({b: ofc.bots[id], id})).concat([{id: 'captain', x: CAPTAIN.x, y: CAPTAIN.y - 70}]);
    targets.forEach((tg, i) => setTimeout(() => {
      const end = () => tg.b ? {x: tg.b.x, y: tg.b.y - 30} : tg, s = end(), sx = s.x + (Math.random() - .5) * 120, sy = tg.b ? OFFICES[cur].y + OFFICES[cur].h + 20 : MOD.beam.y + 60;
      fx.push({t: 0, dur: .8, update(dt){ this.t += dt; if(this.t >= this.dur){ splat(tg, end()); return false; } return true; },
        draw(c){ const e = end(), f = this.t / this.dur, x = sx + (e.x - sx) * f, y = sy + (e.y - sy) * f - Math.sin(f * Math.PI) * 70;
          circle(c, Math.round(x), Math.round(y), 3, '#d3241b', true); rect(c, Math.round(x) - 1, Math.round(y) - 4, 3, 2, '#2f8a3a'); }});
    }, i * 220));
  }
  function splat(tg, at){
    sfx.splat && sfx.splat();
    if(tg.id === 'captain') cap.splat = time + 4; else tg.b.splat = time + 4;
    for(let i = 0; i < 14; i++){ const a = Math.random() * Math.PI * 2, v = 20 + Math.random() * 40;
      parts.push({x: at.x, y: at.y, vx: Math.cos(a) * v, vy: Math.sin(a) * v - 20, c: i % 3 ? '#d3241b' : '#ff6a4a', life: .8}); }
    if(tg.id === 'risk') alarm = time + 4;
  }
  function buy(){ buyPulse = time; crew('cheer', 2); sfx.cheer && sfx.cheer(); }

  /* frame */
  let last = performance.now(), visible = true, acc = 0;
  new IntersectionObserver(es => { visible = es[0].isIntersecting; }).observe(stage);
  function loop(now){
    requestAnimationFrame(loop);
    const dt = Math.min(.1, (now - last) / 1000); last = now;
    if(!visible || document.hidden) return;
    acc += dt; if(acc < 1 / 32) return;   // about 30 frames a second is plenty for pixel art
    const step = Math.min(.1, acc); acc = 0; time += step;
    const e = reduced ? 1 : Math.min(1, step * 6); view.x += (goal.x - view.x) * e; view.y += (goal.y - view.y) * e; view.k += (goal.k - view.k) * e;
    for(const ofc of offices){
      for(const b of Object.values(ofc.bots)) updateBot(b, step);
      const cr = ofc.courier;
      if(cr.path.length){
        const p = cr.path[0], dx = p.x - cr.x, dy = p.y - cr.y, d = Math.hypot(dx, dy), sp = 120 * step;
        if(Math.abs(dx) > .5) cr.dir = dx > 0 ? 1 : -1;
        if(d <= sp){ cr.x = p.x; cr.y = p.y; cr.path.shift(); if(!cr.path.length && cr.done){ const f = cr.done; cr.done = null; f(); } }
        else { cr.x += dx / d * sp; cr.y += dy / d * sp; }
      }
    }
    fx = fx.filter(f => f.update(step));
    parts = parts.filter(p => { p.life -= step; p.vy += 60 * step; p.x += p.vx * step; p.y += p.vy * step; return p.life > 0 && p.y < H; });
    draw();
    ctx.setTransform(1, 0, 0, 1, 0, 0); ctx.fillStyle = P.space; ctx.fillRect(0, 0, canvas.width, canvas.height);
    const k = view.k * dpr; ctx.imageSmoothingEnabled = view.k < 1; ctx.imageSmoothingQuality = 'high';
    ctx.setTransform(k, 0, 0, k, (cssW / 2 - view.x * view.k) * dpr, (cssH / 2 - view.y * view.k) * dpr);
    ctx.drawImage(map, 0, 0);
    if(sayAt && say.style.display !== 'none'){
      const at = sayAt === 'captain' ? {x: CAPTAIN.x, y: CAPTAIN.y - 100} : {x: sayAt.x, y: sayAt.y - 42};
      say.style.transform = `translate(${(at.x - view.x) * view.k + cssW / 2}px, ${(at.y - view.y) * view.k + cssH / 2}px) translate(-50%, -100%)`;
    }
  }
  function draw(){
    const c = mc, t = time; c.drawImage(base, 0, 0);
    // twinkling stars, blinking hull lights and a little shuttle passing by
    for(const s of STARS) if(s.tw && Math.sin(t * 2 + s.x) > .6) rect(c, s.x - 1, s.y, 3, 1, hexA('#ffffff', .6));
    const blink = t % 1.6 < .3;
    for(const [x, y, col] of [[32, 512, '#ff3b3b'], [1768, 512, '#36ff7a'], [32, 958, '#ff3b3b'], [1768, 958, '#36ff7a'], [900, 18, '#ff3b3b']]) rect(c, x - 1, y - 1, 3, 3, blink ? col : hexA(col, .3));
    const sx = ((t * 38) % 2600) - 400; rect(c, sx, 1174, 22, 7, '#9aa3b5'); rect(c, sx + 4, 1176, 14, 2, P.gold); rect(c, sx + 22, 1175, 4, 5, '#d6f2ff'); rect(c, sx - 5 - (Math.floor(t * 10) % 2) * 2, 1176, 5, 3, '#4aa3ff');
    // a light that flickers in each dark wing
    for(const [m, ph] of [[MOD.futureB, 2.1]]){ const on = Math.sin(t * 13 + ph) + Math.sin(t * 7.3 + ph * 3) > 1.2;
      if(on){ for(let i = 0; i < 4; i++) circle(c, m.x + 300, m.y + 150, 70 - i * 15, 'rgba(255,230,170,.04)', true); } rect(c, m.x + 296, m.y + 147, 8, 3, on ? '#ffe6aa' : '#3a3424'); }
    // the Forex wing's world clocks (forex trades 24 hours a day, 5 days a week)
    if(Math.floor(t * 2) % 2 === 0 || !clocks.length){ const d = new Date();
      clocks = ['Asia/Tokyo', 'Europe/London', 'America/New_York'].map(z => { try { return d.toLocaleTimeString('en-GB', {timeZone: z, hour: '2-digit', minute: '2-digit'}); } catch(e){ return '--:--'; } }); }
    clocks.forEach((s, i) => txt(c, s, MOD.forex.x + 250 + i * 104 + 92 - tw(s), MOD.forex.y + 8, '#5fe0b0'));
    // the office you're watching glows gold at the edges
    const sg = OFFICES[cur], pulse = .45 + .35 * Math.sin(t * 2.4); frame(c, sg.x - 6, sg.y - 6, sg.w + 12, sg.h + 12, hexA(P.gold, pulse)); frame(c, sg.x - 7, sg.y - 7, sg.w + 14, sg.h + 14, hexA(P.gold, pulse * .4));
    const charging = beamCharge && t - beamCharge < 1.2, buying = buyPulse && t - buyPulse < 1.6, hot = charging || (laser && t - laser < 3);
    for(const ofc of offices){
      const S = strat(ofc.i), g = ofc.g, me = ofc.i === fxOffice;
      for(const id of g.ids){
        const d = g.rooms[id].dyn || {}, col = COL[id];
        if(d.radar){ const rr = d.radar; circle(c, rr.x, rr.y, rr.r, hexA(col, .35)); circle(c, rr.x, rr.y, rr.r / 2, hexA(col, .2));
          const a = t * 2.4 + ofc.i; for(let i = 0; i < rr.r; i++) rect(c, Math.round(rr.x + Math.cos(a) * i), Math.round(rr.y + Math.sin(a) * i), 1, 1, col);
          rr.syms.forEach(([s, m], i) => { const ang = (s.charCodeAt(0) * 37 + i * 91) % 360 / 57.3, dist = 4 + (i * 3) % (rr.r - 4);
            const glow = ((a - ang) % 6.283 + 6.283) % 6.283 < 1.2; rect(c, Math.round(rr.x + Math.cos(ang) * dist), Math.round(rr.y + Math.sin(ang) * dist), 2, 2, m.passed ? P.gold : glow ? col : hexA(col, .4)); }); }
        if(d.ticker){ const tk = d.ticker; rect(c, tk.x, tk.y - 1, tk.w, 7, '#050912'); c.save(); c.beginPath(); c.rect(tk.x, tk.y - 1, tk.w, 7); c.clip();
          const wdt = tw(tk.text) + 4, off = (t * 20) % wdt; txt(c, tk.text, tk.x - off, tk.y, col); txt(c, tk.text, tk.x - off + wdt, tk.y, col); c.restore(); }
        if(d.gauge){ const gg = d.gauge; for(let i = 0; i <= 12; i++){ const a = Math.PI + i / 12 * Math.PI; rect(c, Math.round(gg.x + Math.cos(a) * 12), Math.round(gg.y + Math.sin(a) * 12), 1, 1, i < 4 ? P.bad : i > 8 ? P.good : P.gold); }
          const v = gg.v == null ? Math.sin(t * .8 + ofc.i) * .1 : gg.v, a = Math.PI * 1.5 + clamp(v, -1, 1) * Math.PI / 2;
          for(let i = 0; i < 10; i++) rect(c, Math.round(gg.x + Math.cos(a) * i), Math.round(gg.y + Math.sin(a) * i), 1, 1, P.ink); rect(c, gg.x - 1, gg.y - 1, 3, 3, P.gold); }
        if(d.bars){ const br = d.bars; for(let i = 0; i < 6; i++){ const hh = br.on ? Math.max(2, Math.round((Math.sin(t * 3 + i * 1.7) * .5 + .5) * (6 + br.hype * 8))) : 1; rect(c, br.x + i * 5, br.y - Math.min(16, hh), 4, Math.min(16, hh), col); } }
        if(d.alarm){ const blocked = ((S.stations || {}).risk || {}).status === 'blocked' || (me && alarm > t); rect(c, d.alarm.x, d.alarm.y, 8, 3, blocked && t % .6 < .3 ? '#ff3b3b' : blocked ? '#5a1a1a' : P.good); }
      }
      // pulses along the cables into Decision, then the gold one to the beam
      for(const cb of g.cables.concat([g.gold])){
        const isGold = cb.id === 'beam', n = isGold ? 5 : 3, fast = me && (charging || buying), sp = fast ? (charging ? 160 : 100) : 26;
        for(let i = 0; i < n; i++){ const p = along(cb, t * sp + i * cb.len / n + ofc.i * 40);
          rect(c, Math.round(p.x) - 1, Math.round(p.y) - 1, isGold ? 3 : 2, isGold ? 3 : 2, me && charging ? '#36ff7a' : me && buying && isGold ? '#fff3c4' : cb.col); }
      }
      // name plate timers: how long since this crew's last run
      const lr = lastRun(ofc.i), secs = lr ? (Date.now() - lr) / 1000 : null;
      for(const id of g.ids){ const r = g.rooms[id], b = ofc.bots[id];
        txt(c, secs == null ? 'NO RUNS YET' : (b.working ? 'RUN ' : 'IDLE ') + clock(secs), r.x + 26, r.y + 104, b.working ? '#36ff7a' : P.dim); }
      // bots and desks: a bot behind its desk is drawn first, a bot in front of it after
      for(const id of g.ids){
        const b = ofc.bots[id], r = b.r, cheer = b.mood === 'cheer', behind = b.y < r.y + 90;
        const sleeping = !b.working && b.at === 'seat' && !b.mood && b.talk < t;
        const drawBot = () => minion(c, Math.round(b.x), Math.round(b.y), id, outfit(ofc.i), {back: b.face === 'back' && !b.mood && b.talk < t,
          mood: b.mood || (b.talk > t ? 'talk' : sleeping ? 'sleep' : 'happy'), t, lift: cheer ? Math.abs(Math.sin(t * 9)) * 4 : 0,
          walk: b.path.length ? b.walk : null, blink: t % 4 < .12, splat: b.splat > t});
        if(behind) drawBot();
        desk(c, r.seat.x, r.y + 72, COL[id]);
        if(!behind) drawBot();
        if(sleeping){ const z = (t * .8 + ORDER.indexOf(id) * .3) % 1.5; if(z < 1.2) txt(c, z < .6 ? 'z' : 'Z', Math.round(b.x + 10 + z * 6), Math.round(b.y - 44 - z * 10), '#9fb0d8'); }
        if(id === 'decision'){ const pressed = me && buyPulse && t - buyPulse < .5; rect(c, r.x + 11, r.y + 76 + (pressed ? 2 : 0), 12, 5, '#a11'); rect(c, r.x + 11, r.y + 75 + (pressed ? 2 : 0), 12, 2, '#ff3b3b'); }
      }
    }
    // server LEDs in the break room and the arcade screens
    const Lg = MOD.lounge;
    for(let i = 0; i < 4; i++) for(let j = 0; j < 6; j++){ const sx = Lg.x + 124 + i * 15; rect(c, sx + 3, Lg.y + 14 + j * 6, 2, 1, Math.sin(t * 4 + i * 7 + j * 3) > .2 ? '#36ff7a' : '#0f3a20'); rect(c, sx + 7, Lg.y + 14 + j * 6, 2, 1, Math.sin(t * 3 + i * 5 + j) > .4 ? P.gold : '#3a2a10'); }
    for(const [n, ax] of [[0, Lg.x + 190], [1, Lg.x + 222]]){ const f = Math.floor(t * 4 + n * 3); rect(c, ax + 5 + (f % 12), Lg.y + 20 + (f % 3) * 2, 2, 2, n ? '#ff5a5a' : '#f7d33b'); rect(c, ax + 6, Lg.y + 26, 12, 1, '#3ddc84'); }
    // beam emitter idles with a soft pulse
    const pz = .5 + .5 * Math.sin(t * 2);
    circle(c, EMIT.x, EMIT.y, 6, hot ? '#d9ffe6' : hexA('#36ff7a', .35 + pz * .4), true);
    circle(c, EMIT.x, EMIT.y, 8 + Math.round(pz * 2), hexA('#36ff7a', .5));
    if(charging){ const f = (t - beamCharge) / 1.2; for(let i = 0; i < 3; i++) circle(c, EMIT.x, EMIT.y, Math.round(28 - ((f * 3 + i / 3) % 1) * 20), hexA('#36ff7a', .8)); }
    // the laser goes up behind the throne, out through the window into space
    if(laser && t - laser < 3.2){
      const f = t - laser, w = f < .2 ? f / .2 : f > 2.6 ? Math.max(0, (3.2 - f) / .6) : 1, fl = (Math.floor(t * 20) % 2);
      c.fillStyle = hexA('#36ff7a', .18 * w); c.fillRect(EMIT.x - 14, 0, 28, EMIT.y);
      c.fillStyle = hexA('#36ff7a', .9 * w); c.fillRect(EMIT.x - 5 - fl, 0, 10 + fl * 2, EMIT.y);
      c.fillStyle = hexA('#eafff0', w); c.fillRect(EMIT.x - 2, 0, 4, EMIT.y);
      circle(c, EMIT.x, EMIT.y, 10 + Math.round(f * 20) % 16, hexA('#36ff7a', .7 * w));
    }
    // the Captain nods slowly like a boss
    const nod = cap.nodUntil > t ? (Math.sin((cap.nodUntil - t) * 2.6) > 0 ? 1 : 0) : 0;
    const shake = cap.glare > t && cap.glare - t > 3 ? (Math.sin(t * 14) > 0 ? 1 : -1) : 0;
    titan(c, CAPTAIN.x, CAPTAIN.y, {nod, glare: cap.glare > t, flash: cap.flash > t && t % .5 < .3, splat: cap.splat > t, shake, cheer: cap.flash > t});
    // couriers on scooters, carrying a gold envelope while they work
    for(const ofc of offices){ const cr = ofc.courier, x = Math.round(cr.x), y = Math.round(cr.y), home = cr.at === ofc.g.home;
      scooter(c, x, y, cr.dir); minion(c, x - cr.dir * 2, y - 3, 'courier', outfit(ofc.i), {mood: 'happy', t, blink: t % 5 < .12});
      if(!home){ rect(c, x - cr.dir * 2 + 6, y - 26, 9, 6, P.gold); rect(c, x - cr.dir * 2 + 7, y - 25, 7, 1, '#7a5a1f'); } }
    if(flash > 0 && t - flash < .6){ c.fillStyle = hexA('#36ff7a', .2 * (1 - (t - flash) / .6)); c.fillRect(0, 0, W, H); }
    for(const f of fx) f.draw(c);
    for(const p of parts){ c.fillStyle = p.c; c.fillRect(Math.round(p.x), Math.round(p.y), 2, 2); }
    if(buyPulse && t - buyPulse < 1.4){ const f = (t - buyPulse) / 1.4, r = OFFICES[fxOffice].rooms.decision; circle(c, r.x + 17, r.y + 78, Math.round(4 + f * 40), hexA(P.gold, 1 - f)); }
  }
  requestAnimationFrame(loop);
  if(!reduced) setTimeout(replay, 900);

  return {
    setStrategy(name){ const i = names.indexOf(typeof name === 'string' ? name : name && name.name); if(i < 0 || i === cur) return; cur = i; fxOffice = i; buildPanel(); },
    focusOffice(name){ const i = names.indexOf(name); if(i >= 0) flyOffice(i); },
    replay, play, fit,
    zoomIn(){ zoomAt(cssW / 2, cssH / 2, goal.k * 1.5); },
    zoomOut(){ zoomAt(cssW / 2, cssH / 2, goal.k / 1.5); }
  };
}

// a single helper sprite as a picture, for the crew list
function sprite(id, outfit, scale = 4){
  const cv = document.createElement('canvas'); cv.width = 14 * scale; cv.height = 22 * scale;
  const c = cv.getContext('2d'); minion(c, 7 * scale, 21 * scale, id, outfit, {k: scale, mood: 'happy'});
  return cv.toDataURL();
}

window.PixelWorld = {init, sprite};
})();
