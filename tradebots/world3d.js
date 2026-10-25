/* Bot World in 3D: the crew aboard their ship, built with three.js.
   Every character is an original design made from simple shapes.
   window.World3D.init(opts) -> { setStrategy(S), replay(), play(kind) } or null when WebGL isn't available. */
(function(){
'use strict';
const T = window.THREE;

function init(o){
  if(!T) return null;
  let renderer;
  try { renderer = new T.WebGLRenderer({canvas: o.canvas, antialias: true, powerPreference: 'high-performance'}); }
  catch(e){ return null; }
  if(!renderer.getContext()) return null;
  const reduced = o.reduced;
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
  renderer.shadowMap.enabled = true;
  renderer.shadowMap.type = T.PCFSoftShadowMap;
  renderer.outputColorSpace = T.SRGBColorSpace;
  renderer.toneMapping = T.ACESFilmicToneMapping;
  renderer.toneMappingExposure = 1.0;

  const scene = new T.Scene();
  scene.background = new T.Color(0x030406);
  scene.fog = new T.Fog(0x030406, 40, 140);
  const camera = new T.PerspectiveCamera(40, 1, .1, 600);

  /* ---------- helpers ---------- */
  const std = (color, extra) => new T.MeshStandardMaterial(Object.assign({color, roughness: .6, metalness: .1}, extra || {}));
  const glow = color => new T.MeshBasicMaterial({color});
  function mesh(geo, mat, parent, x = 0, y = 0, z = 0, shadow = true){
    const m = new T.Mesh(geo, mat); m.position.set(x, y, z);
    if(shadow){ m.castShadow = true; m.receiveShadow = true; }
    if(parent) parent.add(m);
    return m;
  }
  const AMBER = 0xe8b45a;

  /* ---------- light ---------- */
  scene.add(new T.HemisphereLight(0xc9d2ff, 0x2a1c0a, 1.1));
  const key = new T.DirectionalLight(0xffe6c0, 1.6);
  key.position.set(8, 18, 10); key.castShadow = true;
  key.shadow.mapSize.set(1024, 1024);
  Object.assign(key.shadow.camera, {left: -18, right: 18, top: 18, bottom: -18, near: 1, far: 60});
  key.shadow.bias = -.0005;
  scene.add(key);
  const rim = new T.DirectionalLight(AMBER, 1.4); rim.position.set(-10, 8, -16); scene.add(rim);
  const core = new T.PointLight(AMBER, 40, 16, 2); core.position.set(0, 3.2, 0); scene.add(core);

  /* ---------- the ship ---------- */
  const floorMat = std(0x12151c, {metalness: .2, roughness: .85});
  mesh(new T.CylinderGeometry(27, 27, .4, 96), floorMat, scene, 0, -.2, 0).castShadow = false;
  const lineMat = glow(0x6b5229);
  for(const r of [3.2, 6.6, 11.6, 15.6, 22]){
    const ring = mesh(new T.TorusGeometry(r, r === 6.6 ? .05 : .03, 6, 160), r === 6.6 ? glow(AMBER) : lineMat, scene, 0, .01, 0, false);
    ring.rotation.x = -Math.PI / 2;
  }
  for(let i = 0; i < 24; i++){
    const a = i / 24 * Math.PI * 2, len = 4;
    const b = mesh(new T.BoxGeometry(.03, .01, len), lineMat, scene, Math.sin(a) * 13.6, .01, Math.cos(a) * 13.6, false);
    b.rotation.y = a;
  }
  // monumental pillars with amber light strips
  const pillarMat = std(0x0c0e13, {metalness: .4, roughness: .7});
  for(let i = 0; i < 18; i++){
    const a = (i + .5) / 18 * Math.PI * 2, r = 25.5;
    const p = new T.Group(); p.position.set(Math.sin(a) * r, 0, Math.cos(a) * r); p.rotation.y = a; scene.add(p);
    mesh(new T.BoxGeometry(1.6, 22, 2), pillarMat, p, 0, 11, 0, false);
    mesh(new T.BoxGeometry(.08, 18, .06), glow(i % 3 === 0 ? AMBER : 0x8a6630), p, 0, 10, -1.02, false);
  }
  const crown = mesh(new T.TorusGeometry(25.5, .7, 8, 90), pillarMat, scene, 0, 22, 0, false); crown.rotation.x = Math.PI / 2;

  // the view outside: stars, a planet's amber edge, distant ships
  const starGeo = new T.BufferGeometry(), sp = [];
  for(let i = 0; i < 2200; i++){
    const u = Math.random() * 2 - 1, th = Math.random() * Math.PI * 2, r = 260;
    const s = Math.sqrt(1 - u * u); sp.push(r * s * Math.cos(th), Math.abs(r * u) * .9 + 10, r * s * Math.sin(th));
  }
  starGeo.setAttribute('position', new T.Float32BufferAttribute(sp, 3));
  scene.add(new T.Points(starGeo, new T.PointsMaterial({color: 0xffffff, size: 1.1, sizeAttenuation: true, fog: false})));
  const planet = mesh(new T.SphereGeometry(150, 64, 32), new T.MeshBasicMaterial({color: 0x0b0805, fog: false}), scene, 0, -120, -230, false);
  const atmo = new T.Mesh(new T.SphereGeometry(156, 64, 32), new T.ShaderMaterial({
    side: T.BackSide, transparent: true, blending: T.AdditiveBlending, depthWrite: false, fog: false,
    uniforms: {c: {value: new T.Color(0xffb85a)}},
    vertexShader: 'varying vec3 vN; varying vec3 vV; void main(){ vec4 mv = modelViewMatrix * vec4(position,1.); vN = normalize(normalMatrix * normal); vV = normalize(-mv.xyz); gl_Position = projectionMatrix * mv; }',
    fragmentShader: 'uniform vec3 c; varying vec3 vN; varying vec3 vV; void main(){ float f = pow(max(0., .62 - dot(vN, vV)), 2.2); gl_FragColor = vec4(c * f * 2.4, f); }'
  }));
  atmo.position.copy(planet.position); scene.add(atmo);
  const farShips = [];
  for(const [x, y, z, s] of [[-120, 40, -200, 1], [140, 60, -180, .7], [60, 25, -260, .5]]){
    const g = new T.Group(); g.position.set(x, y, z); g.scale.setScalar(s); scene.add(g);
    mesh(new T.BoxGeometry(40, 2.2, 6), new T.MeshBasicMaterial({color: 0x14161c, fog: false}), g, 0, 0, 0, false);
    mesh(new T.BoxGeometry(26, .3, 6.2), new T.MeshBasicMaterial({color: AMBER, fog: false}), g, 2, 0, 0, false);
    farShips.push(g);
  }

  /* ---------- canvas text for screens ---------- */
  function textCanvas(w, h){
    const c = document.createElement('canvas'); c.width = w; c.height = h;
    const tex = new T.CanvasTexture(c); tex.colorSpace = T.SRGBColorSpace; tex.anisotropy = 4;
    return {c, ctx: c.getContext('2d'), tex};
  }
  function wrap(ctx, text, x, y, maxW, lh, maxLines){
    const words = String(text).split(/\s+/); let line = '', n = 0;
    for(let i = 0; i < words.length; i++){
      const test = line ? line + ' ' + words[i] : words[i];
      if(ctx.measureText(test).width > maxW && line){
        if(n === maxLines - 1){ ctx.fillText(line + ' …', x, y + n * lh); return; }
        ctx.fillText(line, x, y + n * lh); n++; line = words[i];
      } else line = test;
    }
    if(line) ctx.fillText(line, x, y + n * lh);
  }
  const FONT = 'system-ui,-apple-system,"Segoe UI",Roboto,sans-serif';
  const CHIP = {found: 'SIGNAL', buy: 'BUY', working: 'ACTIVE', blocked: 'BLOCKED', resting: 'STANDBY', idle: 'STANDBY'};
  function drawScreen(sc, num, name, st, active){
    const {c, ctx} = sc, w = c.width, h = c.height;
    ctx.fillStyle = active ? '#1d1708' : '#0a0c11'; ctx.fillRect(0, 0, w, h);
    ctx.strokeStyle = active ? '#e8b45a' : '#5a4422'; ctx.lineWidth = 6; ctx.strokeRect(3, 3, w - 6, h - 6);
    ctx.fillStyle = '#e8b45a'; ctx.font = `700 30px ${FONT}`; ctx.fillText(num, 26, 52);
    ctx.fillStyle = '#ece7dc'; ctx.font = `600 34px ${FONT}`; ctx.fillText(name.toUpperCase().split('').join(String.fromCharCode(8202)), 76, 52);
    const chip = CHIP[st.status] || 'STANDBY', hot = st.status === 'found' || st.status === 'buy';
    ctx.font = `700 22px ${FONT}`; const cw = ctx.measureText(chip).width + 24;
    ctx.fillStyle = hot ? '#e8b45a' : st.status === 'blocked' ? '#3a1714' : '#1a1a14';
    ctx.fillRect(w - cw - 24, 26, cw, 34);
    ctx.fillStyle = hot ? '#1a1206' : st.status === 'blocked' ? '#ff7466' : '#e8b45a'; ctx.fillText(chip, w - cw - 12, 51);
    ctx.fillStyle = '#d8d2c4'; ctx.font = `400 28px ${FONT}`;
    wrap(ctx, st.say, 26, 112, w - 52, 38, 4);
    sc.tex.needsUpdate = true;
  }

  /* ---------- characters ---------- */
  const yellow = std(0xf7d33b, {roughness: .45});
  const denim = std(0x8db8e3, {roughness: .95});
  const pocket = std(0x74a2d2, {roughness: .95});
  const black = std(0x1b1b1b, {roughness: .5});
  const metal = std(0xb8c0cc, {metalness: .85, roughness: .25});
  const white = std(0xffffff, {roughness: .2});
  const iris = std(0x5a3a1a), pupil = std(0x0a0a0a, {roughness: .1});
  const gold = std(0xd9ac5c, {metalness: .7, roughness: .3});

  function goggle(parent, x, r){
    const ring = mesh(new T.TorusGeometry(r, r * .32, 12, 28), metal, parent, x, 0, .4);
    const eye = mesh(new T.SphereGeometry(r * .92, 20, 14), white, parent, x, 0, .37); eye.scale.z = .55;
    const ir = mesh(new T.SphereGeometry(r * .42, 14, 10), iris, parent, x + r * .08, -r * .05, .43); ir.scale.z = .4;
    const pu = mesh(new T.SphereGeometry(r * .22, 10, 8), pupil, parent, x + r * .08, -r * .05, .455); pu.scale.z = .4;
    return [eye, ir, pu];
  }
  function helper(kind){
    const g = new T.Group(), body = new T.Group(); g.add(body);
    const torso = mesh(new T.CapsuleGeometry(.42, .62, 8, 20), yellow, body, 0, .98, 0);
    mesh(new T.CylinderGeometry(.435, .435, .25, 28), denim, body, 0, .79, 0);
    const seat = mesh(new T.SphereGeometry(.435, 28, 14, 0, Math.PI * 2, Math.PI / 2, Math.PI / 2), denim, body, 0, .67, 0);
    mesh(new T.BoxGeometry(.44, .3, .08), denim, body, 0, 1.0, .39);
    mesh(new T.BoxGeometry(.22, .12, .03), pocket, body, 0, .98, .44);
    for(const s of [-1, 1]){
      const strap = mesh(new T.BoxGeometry(.07, .42, .05), denim, body, s * .2, 1.27, .33); strap.rotation.x = -.35;
      mesh(new T.SphereGeometry(.035, 8, 6), gold, body, s * .17, 1.12, .43);
    }
    const band = mesh(new T.TorusGeometry(.425, .055, 8, 40), black, body, 0, 1.3, 0); band.rotation.x = Math.PI / 2;
    const face = new T.Group(); face.position.y = 1.3; body.add(face);
    const two = kind === 'charts' || kind === 'news' || kind === 'risk' || kind === 'decision';
    const eyes = two ? goggle(face, -.15, .13).concat(goggle(face, .15, .13)) : goggle(face, 0, .19);
    const mouth = mesh(new T.TorusGeometry(.1, .018, 6, 18, Math.PI), std(0x4a2a12), body, 0, 1.06, .41, false);
    mouth.rotation.z = Math.PI;
    if(kind !== 'risk' && kind !== 'sentiment'){
      for(const [x, rz] of [[-.06, .35], [0, 0], [.07, -.3]]){
        const h = mesh(new T.CylinderGeometry(.01, .01, .16, 4), black, body, x, 1.85, 0, false); h.rotation.z = rz;
      }
    }
    if(kind === 'risk'){
      const hat = std(0xff8a1f, {roughness: .4});
      mesh(new T.SphereGeometry(.45, 24, 12, 0, Math.PI * 2, 0, Math.PI / 2), hat, body, 0, 1.58, 0);
      mesh(new T.CylinderGeometry(.56, .56, .04, 28), hat, body, 0, 1.6, .04);
    }
    if(kind === 'sentiment'){
      const hp = mesh(new T.TorusGeometry(.47, .04, 8, 24, Math.PI), black, body, 0, 1.55, 0); hp.rotation.y = Math.PI / 2;
      for(const s of [-1, 1]) mesh(new T.CylinderGeometry(.13, .13, .12, 16), gold, body, s * .46, 1.55, 0).rotation.z = Math.PI / 2;
    }
    const arms = [];
    for(const s of [-1, 1]){
      const pivot = new T.Group(); pivot.position.set(s * .43, 1.06, 0); body.add(pivot);
      mesh(new T.CylinderGeometry(.05, .05, .4, 8), yellow, pivot, 0, -.2, 0);
      mesh(new T.SphereGeometry(.085, 12, 8), black, pivot, 0, -.42, 0);
      pivot.rotation.z = s * .18; arms.push(pivot);
    }
    const legs = [];
    for(const s of [-1, 1]){
      const pivot = new T.Group(); pivot.position.set(s * .16, .32, 0); g.add(pivot);
      mesh(new T.CylinderGeometry(.08, .08, .22, 10), denim, pivot, 0, -.1, 0);
      mesh(new T.BoxGeometry(.17, .08, .26), black, pivot, 0, -.25, .04);
      legs.push(pivot);
    }
    let carry = null;
    if(kind === 'courier'){
      carry = new T.Group(); carry.position.set(0, .82, .52); body.add(carry);
      mesh(new T.BoxGeometry(.42, .28, .06), std(AMBER, {emissive: AMBER, emissiveIntensity: .35}), carry);
      mesh(new T.BoxGeometry(.43, .02, .065), std(0x7a5a1f), carry, 0, .05, 0);
    }
    return {g, body, arms, legs, mouth, eyes, carry, kind, height: 1.95};
  }
  function captainModel(){
    const g = new T.Group(), body = new T.Group(); g.add(body);
    const suit = std(0xf2f4f8, {roughness: .35}), green = std(0x39b54a, {roughness: .4}), purple = std(0x6a4fb3, {roughness: .5});
    const skin = std(0xc8946a, {roughness: .7});
    const legs = [];
    for(const s of [-1, 1]){
      const pivot = new T.Group(); pivot.position.set(s * .22, .9, 0); g.add(pivot);
      mesh(new T.CylinderGeometry(.16, .14, .7, 12), suit, pivot, 0, -.38, 0);
      mesh(new T.CylinderGeometry(.17, .19, .22, 12), purple, pivot, 0, -.8, .02);
      legs.push(pivot);
    }
    mesh(new T.CapsuleGeometry(.5, .55, 8, 20), suit, body, 0, 1.45, 0);
    mesh(new T.BoxGeometry(.66, .5, .2), green, body, 0, 1.6, .38);
    mesh(new T.BoxGeometry(.3, .2, .06), std(0x2a2f45), body, 0, 1.6, .5);
    [[0xee3333, -.08], [0x33cc66, 0], [0x3399ff, .08]].forEach(([c, x]) => mesh(new T.SphereGeometry(.03, 8, 6), glow(c), body, x, 1.64, .53, false));
    const belt = mesh(new T.TorusGeometry(.5, .07, 8, 30), purple, body, 0, 1.08, 0); belt.rotation.x = Math.PI / 2;
    for(const s of [-1, 1]){
      const wing = mesh(new T.BoxGeometry(.9, .45, .05), suit, body, s * .62, 1.75, -.45); wing.rotation.z = s * -.35; wing.rotation.y = s * .3;
      mesh(new T.BoxGeometry(.7, .05, .06), std(0xd6413a), wing, 0, .05, 0, false);
    }
    const head = new T.Group(); head.position.y = 2.32; body.add(head);
    mesh(new T.SphereGeometry(.42, 24, 16), purple, head, 0, .02, -.04);
    const face = mesh(new T.SphereGeometry(.34, 24, 16), skin, head, 0, -.04, .12); face.scale.set(1, 1.08, .9);
    mesh(new T.BoxGeometry(.3, .14, .2), skin, head, 0, -.26, .2);   // strong chin
    for(const s of [-1, 1]){
      mesh(new T.SphereGeometry(.045, 10, 8), std(0x2a4a7a), head, s * .12, .02, .43, false);
      const brow = mesh(new T.BoxGeometry(.13, .03, .03), std(0x2a1a10), head, s * .12, .11, .43, false); brow.rotation.z = s * -.18;
    }
    const smile = mesh(new T.TorusGeometry(.08, .014, 6, 16, Math.PI), std(0x4a2414), head, 0, -.15, .41, false); smile.rotation.z = Math.PI;
    const helmet = mesh(new T.SphereGeometry(.56, 28, 18), new T.MeshPhysicalMaterial({color: 0xd8ecff, transparent: true, opacity: .14, roughness: .05, metalness: 0, clearcoat: 1}), head, 0, .02, .02, false);
    helmet.renderOrder = 2;
    const ring = mesh(new T.TorusGeometry(.5, .04, 8, 30), purple, head, 0, -.38, 0); ring.rotation.x = Math.PI / 2;
    const arms = [];
    for(const s of [-1, 1]){
      const pivot = new T.Group(); pivot.position.set(s * .58, 1.78, 0); body.add(pivot);
      mesh(new T.CylinderGeometry(.13, .11, .7, 12), suit, pivot, 0, -.35, 0);
      mesh(new T.SphereGeometry(.14, 12, 10), green, pivot, 0, -.74, 0);
      pivot.rotation.z = s * .25; arms.push(pivot);
    }
    return {g, body, arms, legs, head, mouth: smile, height: 3.0};
  }

  /* ---------- stations ---------- */
  const CREW = o.data.crew;
  const R = 9.2, stations = {};
  CREW.forEach((c, i) => {
    const a = (-128 + i * 51.2) * Math.PI / 180;            // fan around the room, opening toward the camera
    const pos = new T.Vector3(Math.sin(a) * R, 0, -Math.cos(a) * R + 1.2);
    const st = new T.Group(); st.position.copy(pos); st.rotation.y = Math.atan2(-pos.x, 1.2 - pos.z); scene.add(st);
    st.updateMatrixWorld(true);
    // console: sits outward of the work spot, screen faces the room
    const con = new T.Group(); con.position.set(0, 0, -1.1); st.add(con);
    mesh(new T.BoxGeometry(2.0, .95, .8), std(0x1a1d26, {metalness: .5, roughness: .5}), con, 0, .475, 0);
    const top = mesh(new T.BoxGeometry(2.0, .08, .95), std(0x232836, {metalness: .5}), con, 0, 1.0, .08); top.rotation.x = .45;
    for(let k = 0; k < 6; k++) mesh(new T.BoxGeometry(.14, .03, .1), glow([AMBER, 0x5fd38d, 0xff7466][k % 3]), top, -.6 + k * .24, .05, 0, false);
    mesh(new T.BoxGeometry(.12, 1.6, .12), std(0x1a1d26, {metalness: .6}), con, 0, 1.7, -.3);
    const sc = textCanvas(640, 300);
    const screen = mesh(new T.PlaneGeometry(2.5, 1.17), new T.MeshBasicMaterial({map: sc.tex, toneMapped: false}), con, 0, 2.55, -.22, false);
    mesh(new T.BoxGeometry(2.62, 1.29, .06), std(0x0d0f14, {metalness: .6}), con, 0, 2.55, -.27);
    const light = new T.PointLight(AMBER, 6, 5, 2); light.position.set(0, 2.2, .8); con.add(light);
    // a prop per job
    const prop = new T.Group(); prop.position.set(1.45, 0, -.5); st.add(prop);
    const dark = std(0x2a2e38, {metalness: .6, roughness: .4});
    let spin = null;
    if(c.id === 'scout'){
      for(const r of [0, 2.1, 4.2]){ const l = mesh(new T.CylinderGeometry(.03, .03, 1.3, 6), dark, prop, Math.sin(r) * .25, .6, Math.cos(r) * .25); l.rotation.set(Math.cos(r) * .3, 0, -Math.sin(r) * .3); }
      spin = new T.Group(); spin.position.y = 1.25; prop.add(spin);
      const tube = mesh(new T.CylinderGeometry(.1, .17, 1.2, 14), gold, spin, 0, 0, 0); tube.rotation.x = Math.PI / 2 - .5;
    } else if(c.id === 'charts'){
      const cc = textCanvas(256, 160), x = cc.ctx;
      x.fillStyle = '#0a0c11'; x.fillRect(0, 0, 256, 160); x.strokeStyle = '#5fd38d'; x.lineWidth = 5; x.beginPath();
      [[16, 130], [60, 100], [100, 112], [150, 70], [200, 80], [240, 30]].forEach(([a, b], k) => k ? x.lineTo(a, b) : x.moveTo(a, b)); x.stroke();
      cc.tex.needsUpdate = true;
      mesh(new T.BoxGeometry(.08, 1.4, .08), dark, prop, 0, .7, 0);
      mesh(new T.PlaneGeometry(1.1, .7), new T.MeshBasicMaterial({map: cc.tex, toneMapped: false, side: T.DoubleSide}), prop, 0, 1.6, 0, false);
    } else if(c.id === 'news'){
      mesh(new T.CylinderGeometry(.35, .45, .9, 16), dark, prop, 0, .45, 0);
      spin = new T.Group(); spin.position.y = 1.35; prop.add(spin);
      for(let k = 0; k < 5; k++){ const p = mesh(new T.PlaneGeometry(.34, .22), new T.MeshBasicMaterial({color: 0xece7dc, side: T.DoubleSide}), spin, Math.sin(k * 1.256) * .5, (k % 2) * .12, Math.cos(k * 1.256) * .5, false); p.rotation.y = k * 1.256; }
    } else if(c.id === 'sentiment'){
      mesh(new T.CylinderGeometry(.05, .07, 1.5, 8), dark, prop, 0, .75, 0);
      spin = new T.Group(); spin.position.y = 1.55; prop.add(spin);
      const dish = mesh(new T.SphereGeometry(.55, 24, 10, 0, Math.PI * 2, 0, Math.PI / 3.2), std(0xd8d2c4, {side: T.DoubleSide, metalness: .4}), spin, 0, 0, 0); dish.rotation.x = -1.1;
      mesh(new T.SphereGeometry(.06, 8, 6), glow(AMBER), spin, 0, .2, .35, false);
    } else if(c.id === 'risk'){
      mesh(new T.BoxGeometry(.08, 1.1, .08), dark, prop, 0, .55, 0);
      spin = new T.Group(); spin.position.y = 1.55; prop.add(spin);
      mesh(new T.CylinderGeometry(.55, .55, .1, 6), std(0x2a2e38, {metalness: .6, emissive: 0x3a2a0c}), spin, 0, 0, 0).rotation.x = Math.PI / 2;
      mesh(new T.TorusGeometry(.48, .03, 6, 6), glow(AMBER), spin, 0, 0, .06, false);
    } else if(c.id === 'decision'){
      mesh(new T.CylinderGeometry(.35, .45, 1.0, 16), dark, prop, 0, .5, 0);
      spin = mesh(new T.CylinderGeometry(.26, .26, .14, 20), std(0xdd2222, {emissive: 0x550000, roughness: .3}), prop, 0, 1.07, 0);
    }
    const sideGlow = mesh(new T.BoxGeometry(2.4, .02, .04), glow(0x6b5229), st, 0, .01, .4, false);
    stations[c.id] = {id: c.id, name: c.name, num: '0' + (i + 1), group: st, sc, screen, light, spin, sideGlow,
      work: st.localToWorld(new T.Vector3(0, 0, 0)).clone(),
      handoff: st.localToWorld(new T.Vector3(.85, 0, .6)).clone(),
      faceConsole: st.rotation.y + Math.PI};
  });

  // center: holo table showing the account value
  const table = new T.Group(); scene.add(table); table.position.set(0, 0, 1.2);
  mesh(new T.CylinderGeometry(1.5, 1.8, .9, 40), std(0x1a1d26, {metalness: .6, roughness: .4}), table, 0, .45, 0);
  mesh(new T.CylinderGeometry(1.45, 1.45, .04, 40), new T.MeshBasicMaterial({color: 0x3a2a10}), table, 0, .92, 0, false);
  const holo = new T.Group(); holo.position.y = 2.1; table.add(holo);
  const ico = new T.Mesh(new T.IcosahedronGeometry(.55, 1), new T.MeshBasicMaterial({color: AMBER, wireframe: true, transparent: true, opacity: .55}));
  ico.position.y = -.55; holo.add(ico);
  const beamCone = new T.Mesh(new T.CylinderGeometry(.6, 1.3, 1.1, 32, 1, true), new T.MeshBasicMaterial({color: AMBER, transparent: true, opacity: .07, side: T.DoubleSide, depthWrite: false}));
  beamCone.position.y = -.65; holo.add(beamCone);
  const hc = textCanvas(512, 200);
  const holoPanel = new T.Mesh(new T.PlaneGeometry(2.4, .94), new T.MeshBasicMaterial({map: hc.tex, transparent: true, toneMapped: false, depthWrite: false, side: T.DoubleSide}));
  holoPanel.position.y = .55; holo.add(holoPanel);
  function drawHolo(S){
    const x = hc.ctx; x.clearRect(0, 0, 512, 200);
    x.fillStyle = 'rgba(232,180,90,.10)'; x.fillRect(0, 0, 512, 200);
    x.strokeStyle = 'rgba(232,180,90,.6)'; x.lineWidth = 3; x.strokeRect(2, 2, 508, 196);
    x.textAlign = 'center';
    x.fillStyle = '#e8b45a'; x.font = `600 26px ${FONT}`; x.fillText(S.name.toUpperCase() + ' · ACCOUNT VALUE', 256, 46);
    x.fillStyle = '#fff3dc'; x.font = `700 72px ${FONT}`; x.fillText(o.money(S.performance.equity), 256, 124);
    const p = S.performance.profit;
    x.fillStyle = p > .005 ? '#5fd38d' : p < -.005 ? '#ff7466' : '#b3ad9f'; x.font = `600 30px ${FONT}`;
    x.fillText((p > .005 ? '+' : '') + o.money(p) + ' since start', 256, 172);
    hc.tex.needsUpdate = true;
  }

  // the captain's raised dais at the back
  const dais = new T.Group(); dais.position.set(0, 0, -11.5); scene.add(dais);
  mesh(new T.CylinderGeometry(2.6, 3.2, 1.6, 40), std(0x14171e, {metalness: .6, roughness: .45}), dais, 0, .8, 0);
  const daisRing = mesh(new T.TorusGeometry(2.62, .04, 6, 80), glow(AMBER), dais, 0, 1.6, 0, false); daisRing.rotation.x = Math.PI / 2;
  for(let k = 0; k < 3; k++) mesh(new T.BoxGeometry(2.2, .4, .6), std(0x1a1d26, {metalness: .5}), dais, 0, .2 + k * .4, 3.2 - k * .5);
  const captain = captainModel(); captain.g.position.set(0, 1.6, -11.2); scene.add(captain.g);
  captain.g.scale.setScalar(1.05);

  /* ---------- crew ---------- */
  function walker(model, home, faceAngle){
    model.g.position.copy(home); model.g.rotation.y = faceAngle;
    scene.add(model.g);
    return {m: model, home: home.clone(), face: faceAngle, path: [], speed: 1.9, mode: 'work', phase: Math.random() * 10,
      until: 0, next: 3 + Math.random() * 8, mood: null, moodUntil: 0, splats: []};
  }
  const bots = {};
  CREW.forEach(c => { const s = stations[c.id]; bots[c.id] = walker(helper(c.id), s.work, s.faceConsole); });
  const courier = walker(helper('courier'), stations.scout.handoff, 0); courier.speed = 2.3;
  const capW = {m: captain, mood: null, moodUntil: 0, splats: []};
  const everyone = () => Object.values(bots).concat([courier, capW]);

  // walking paths go around the room on a ring so nobody walks through the table
  const RING = 6.3;
  function ringPath(from, to){
    const a0 = Math.atan2(from.x, from.z - 1.2), a1 = Math.atan2(to.x, to.z - 1.2);
    let d = a1 - a0; while(d > Math.PI) d -= Math.PI * 2; while(d < -Math.PI) d += Math.PI * 2;
    const steps = Math.max(1, Math.ceil(Math.abs(d) / .25)), pts = [];
    for(let k = 0; k <= steps; k++){ const a = a0 + d * k / steps; pts.push(new T.Vector3(Math.sin(a) * RING, 0, Math.cos(a) * RING + 1.2)); }
    pts.push(to.clone());
    return pts;
  }
  function walkTo(w, pts, then){ w.path = pts.slice(); w.then = then || null; w.mode = 'walk'; }

  function animate(w, dt, t){
    const m = w.m, g = m.g, b = m.body;
    const moodOn = w.mood && t < w.moodUntil;
    if(!moodOn) w.mood = null;
    // movement
    if(w.path && w.path.length){
      const tgt = w.path[0], dx = tgt.x - g.position.x, dz = tgt.z - g.position.z, dist = Math.hypot(dx, dz);
      if(dist < .08){ w.path.shift(); if(!w.path.length){ w.mode = 'arrived'; const fn = w.then; w.then = null; fn && fn(); } }
      else {
        const step = Math.min(dist, w.speed * dt * (w.mood === 'sad' ? .6 : 1));
        g.position.x += dx / dist * step; g.position.z += dz / dist * step;
        turn(g, Math.atan2(dx, dz), dt * 8);
      }
    }
    const walking = w.path && w.path.length;
    const ph = t * 9 + w.phase;
    if(m.legs){
      m.legs[0].rotation.x = walking ? Math.sin(ph) * .6 : 0;
      m.legs[1].rotation.x = walking ? -Math.sin(ph) * .6 : 0;
    }
    let bob = walking ? Math.abs(Math.sin(ph)) * .06 : Math.sin(t * 2 + w.phase) * .015;
    let armL = 0, armR = 0, armZ = .18, lean = 0;
    if(walking){ armL = -Math.sin(ph) * .5; armR = Math.sin(ph) * .5; }
    else if(w.mode === 'work'){ armL = -1.05 + Math.sin(t * 13 + w.phase) * .18; armR = -1.05 + Math.sin(t * 13 + w.phase + 1.7) * .18; lean = .08; }
    else if(w.mode === 'handoff'){ armR = -1.3; armL = -.2; }
    if(w.mood === 'cheer'){ bob = Math.abs(Math.sin(t * 9 + w.phase)) * .55; armZ = 2.5 + Math.sin(t * 14 + w.phase) * .3; armL = armR = 0; }
    if(w.mood === 'sad'){ lean = .32; armL = armR = .1; armZ = .05; bob = 0; }
    b.position.y = bob; b.rotation.x = lean;
    if(m.arms){
      m.arms[0].rotation.x = armL; m.arms[1].rotation.x = armR;
      m.arms[0].rotation.z = -armZ; m.arms[1].rotation.z = armZ;
    }
    if(m.mouth){ m.mouth.rotation.z = w.mood === 'sad' ? 0 : Math.PI; }
  }
  function turn(g, target, k){
    let d = target - g.rotation.y; while(d > Math.PI) d -= Math.PI * 2; while(d < -Math.PI) d += Math.PI * 2;
    g.rotation.y += d * Math.min(1, k);
  }

  // station crew: work at the console, now and then stretch their legs nearby
  function crewBrain(w, st, t){
    if(w.mode === 'walk' || w.mode === 'handoff' || w.mood) return;
    if(w.mode === 'arrived'){ w.mode = w.returning ? 'work' : 'look'; w.until = t + 1.5 + Math.random() * 2; if(w.returning){ w.returning = false; } }
    if(w.mode === 'work'){
      turn(w.m.g, st.faceConsole, .08);
      if(t > w.next){
        const a = Math.random() * Math.PI * 2, r = .9 + Math.random() * .9;
        walkTo(w, [w.home.clone().add(new T.Vector3(Math.cos(a) * r, 0, Math.sin(a) * r))]);
        w.next = t + 7 + Math.random() * 10;
      }
    } else if(w.mode === 'look' && t > w.until){
      w.returning = true; walkTo(w, [w.home.clone()]);
    }
  }

  /* ---------- courier: carries each bot's work to the next ---------- */
  const ORDER = CREW.map(c => c.id);
  const CAPTAIN_SPOT = new T.Vector3(0, 0, -8.2);
  let route = 0, pendingEvent = true, trip = 0;
  function arrive(id){
    const myTrip = trip;
    courier.mode = 'handoff';
    if(id === 'captain'){
      courier.m.g.rotation.y = Math.PI;
      say('captain', S.captain, 3.2);
      if(pendingEvent){ pendingEvent = false; setTimeout(() => play(S.event && S.event.kind), 400); }
    } else {
      const bw = bots[id];
      courier.m.g.lookAt(bw.m.g.position.x, 0, bw.m.g.position.z);
      if(bw.mode !== 'walk'){ bw.mode = 'handoff'; bw.m.g.lookAt(courier.m.g.position.x, 0, courier.m.g.position.z); }
      active = id; drawStation(id, true); o.onVisit && o.onVisit(id);
      say(id, S.stations[id].say, 3.2); o.sfx.beep();
      setTimeout(() => { if(bw.mode === 'handoff') bw.mode = 'work'; drawStation(id, false); if(active === id){ active = null; o.onVisit && o.onVisit(null); } }, 3000);
    }
    setTimeout(() => {
      if(myTrip !== trip) return;     // a replay started meanwhile
      route = (route + 1) % (ORDER.length + 1);
      const next = route === ORDER.length ? 'captain' : ORDER[route];
      walkTo(courier, ringPath(courier.m.g.position, next === 'captain' ? CAPTAIN_SPOT : stations[next].handoff), () => arrive(next));
    }, reduced ? 2000 : 3200);
  }

  /* ---------- labels and speech bubbles (HTML on top of the canvas) ---------- */
  const labels = {};
  function addLabel(id, name, w){
    const el = document.createElement('div'); el.className = 'lbl'; el.dataset.id = id;
    el.innerHTML = `<span class="lbl-name"></span><span class="lbl-say" hidden></span>`;
    el.querySelector('.lbl-name').textContent = name;
    el.onclick = () => o.onSelect && o.onSelect(id);
    o.labels.appendChild(el); labels[id] = {el, w, until: 0};
  }
  CREW.forEach(c => addLabel(c.id, c.name, bots[c.id]));
  addLabel('captain', 'Captain', capW);
  addLabel('courier', 'Courier', courier);
  function say(id, text, secs){
    const l = labels[id]; if(!l) return;
    const s = l.el.querySelector('.lbl-say'); s.textContent = text; s.hidden = false;
    l.until = clock.elapsedTime + secs; l.el.classList.add('talking');
  }
  const v3 = new T.Vector3();
  function placeLabels(t){
    const w = o.stage.clientWidth, h = o.stage.clientHeight;
    for(const id in labels){
      const l = labels[id], g = l.w.m.g;
      v3.set(0, l.w.m.height * g.scale.y + .15, 0); g.localToWorld(v3); v3.project(camera);
      const vis = v3.z < 1 && Math.abs(v3.x) < 1.1 && Math.abs(v3.y) < 1.1;
      l.el.style.display = vis ? '' : 'none';
      if(!vis) continue;
      l.el.style.transform = `translate(${(v3.x * .5 + .5) * w}px, ${(-v3.y * .5 + .5) * h}px) translate(-50%, -100%)`;
      l.el.style.zIndex = String(1000 - Math.round(v3.z * 1000));
      if(l.until && t > l.until){ l.until = 0; l.el.querySelector('.lbl-say').hidden = true; l.el.classList.remove('talking'); }
    }
  }

  /* ---------- effects ---------- */
  const fx = [];   // {update(dt, t) -> false when done}
  const gl = new T.PointLight(0x36ff7a, 0, 30, 1.6); scene.add(gl);   // the laser's glow
  function play(kind){
    if(!kind) return;
    if(kind === 'win') win(); else if(kind === 'loss') loss(); else if(kind === 'buy') buy();
  }
  function moodAll(m, secs){ const t = clock.elapsedTime; everyone().forEach(w => { w.mood = m; w.moodUntil = t + secs; }); }
  function win(){
    const st = stations.decision, base = st.group.localToWorld(new T.Vector3(1.45, 1.2, -.5));
    const beam = (r, color, opacity) => {
      const geo = new T.CylinderGeometry(r, r, 1, 20, 1, true); geo.translate(0, .5, 0);
      const m = new T.Mesh(geo, new T.MeshBasicMaterial({color, transparent: true, opacity, blending: T.AdditiveBlending, depthWrite: false, fog: false, side: T.DoubleSide}));
      m.position.copy(base); m.frustumCulled = false; scene.add(m); return m;
    };
    const beams = [beam(.16, 0xd9ffe6, 1), beam(.5, 0x36ff7a, .45), beam(1.2, 0x36ff7a, .12)];
    gl.position.copy(base).setY(2);
    const ring = new T.Mesh(new T.RingGeometry(.4, .7, 48), new T.MeshBasicMaterial({color: 0x36ff7a, transparent: true, side: T.DoubleSide, blending: T.AdditiveBlending, depthWrite: false}));
    ring.rotation.x = -Math.PI / 2; ring.position.copy(base).setY(.04); scene.add(ring);
    o.sfx.laser();
    let k = 0; const bg = scene.background.clone();
    fx.push({update(dt, t){
      k += dt; const rise = Math.min(1, k / .35), fade = k > 2.2 ? Math.max(0, 1 - (k - 2.2) / .8) : 1;
      const wob = fade * (1 + Math.sin(t * 40) * .06);
      beams.forEach(b => b.scale.set(wob, Math.max(.001, rise * 300), wob));
      ring.scale.setScalar(1 + k * 8); ring.material.opacity = Math.max(0, .9 - k * .6);
      gl.intensity = 220 * fade * rise;
      scene.background.copy(bg).lerp(new T.Color(0x06281a), .55 * fade * rise);
      if(k > 3){ scene.remove(...beams, ring); gl.intensity = 0; scene.background.copy(bg); return false; }
      return true;
    }});
    setTimeout(() => { o.sfx.cheer(); moodAll('cheer', 4); confetti(); }, 420);
  }
  function confetti(){
    const n = 420, geo = new T.PlaneGeometry(.16, .26);
    const mat = new T.MeshBasicMaterial({side: T.DoubleSide, toneMapped: false});
    const inst = new T.InstancedMesh(geo, mat, n); scene.add(inst);
    const cols = [0xe8b45a, 0x36ff7a, 0xf7d33b, 0x8db8e3, 0xff7466, 0xece7dc].map(c => new T.Color(c));
    const P = [];
    for(let i = 0; i < n; i++){
      const a = Math.random() * Math.PI * 2, r = Math.random() * 13;
      P.push({p: new T.Vector3(Math.sin(a) * r, 10 + Math.random() * 10, Math.cos(a) * r), v: new T.Vector3((Math.random() - .5) * 1.2, -1.6 - Math.random() * 1.8, (Math.random() - .5) * 1.2),
        r: new T.Euler(Math.random() * 6, Math.random() * 6, 0), s: new T.Vector3((Math.random() - .5) * 8, (Math.random() - .5) * 8, 0)});
      inst.setColorAt(i, cols[i % cols.length]);
    }
    const d = new T.Object3D(); let k = 0;
    fx.push({update(dt, t){
      for(let i = 0; i < n; i++){
        const q = P[i]; q.p.addScaledVector(q.v, dt); q.p.x += Math.sin(t * 2 + i) * dt * .6;
        if(q.p.y < .05){ q.p.y = .05; q.v.set(0, 0, 0); q.s.set(0, 0, 0); q.r.x = -Math.PI / 2; }
        q.r.x += q.s.x * dt; q.r.y += q.s.y * dt;
        d.position.copy(q.p); d.rotation.copy(q.r); d.updateMatrix(); inst.setMatrixAt(i, d.matrix);
      }
      inst.instanceMatrix.needsUpdate = true;
      k += dt;
      if(k > 9){ mat.transparent = true; mat.opacity = Math.max(0, 1 - (k - 9) / 2); }
      if(k > 11){ scene.remove(inst); geo.dispose(); mat.dispose(); return false; }
      return true;
    }});
  }
  const tomatoMat = std(0xd3241b, {roughness: .35}), stemMat = std(0x2f8a3a);
  function loss(){
    o.sfx.womp(); moodAll('sad', 5);
    everyone().forEach((w, i) => setTimeout(() => throwTomato(w), 250 + i * 230));
  }
  function throwTomato(w){
    const tom = new T.Group(); mesh(new T.SphereGeometry(.2, 16, 12), tomatoMat, tom);
    mesh(new T.ConeGeometry(.08, .1, 5), stemMat, tom, 0, .2, 0);
    scene.add(tom);
    const side = new T.Vector3().subVectors(w.m.g.position, camera.position).cross(new T.Vector3(0, 1, 0)).normalize();
    const start = camera.position.clone().addScaledVector(side, (Math.random() < .5 ? -1 : 1) * 6).add(new T.Vector3(0, -2, 0));
    let e = 0; const dur = .85;
    fx.push({update(dt, t){
      e += dt; const k = Math.min(1, e / dur);
      const end = new T.Vector3(0, w.m.height * (w.m.g.scale.y || 1) * .72, .25); w.m.g.localToWorld(end);
      tom.position.lerpVectors(start, end, k); tom.position.y += Math.sin(k * Math.PI) * 3;
      tom.rotation.x += dt * 12; tom.rotation.z += dt * 9;
      if(k >= 1){ scene.remove(tom); splat(w); return false; }
      return true;
    }});
  }
  function splat(w){
    o.sfx.splat();
    const body = w.m.body, sp = new T.Group();
    const mat = new T.MeshStandardMaterial({color: 0xc8261c, roughness: .3, transparent: true});
    const h = w.m === captain ? 2.25 : 1.2;
    mesh(new T.SphereGeometry(.26, 14, 10), mat, sp).scale.set(1, .85, .3);
    for(let k = 0; k < 6; k++){ const a = k / 6 * Math.PI * 2; mesh(new T.SphereGeometry(.07, 8, 6), mat, sp, Math.cos(a) * .3, Math.sin(a) * .26, 0).scale.z = .4; }
    for(let k = 0; k < 3; k++) mesh(new T.SphereGeometry(.05, 8, 6), mat, sp, -.12 + k * .12, -.3 - k * .06, .02).scale.set(.7, 1.6, .4);
    sp.position.set(0, h, w.m === captain ? .55 : .45); body.add(sp);
    let k = 0;
    fx.push({update(dt, t){
      k += dt; sp.scale.setScalar(Math.min(1, k * 8));
      if(k > 4){ mat.opacity = Math.max(0, 1 - (k - 4) / 1.2); }
      if(k > 5.2){ body.remove(sp); return false; }
      return true;
    }});
  }
  function buy(){
    o.sfx.cheer(); moodAll('cheer', 2.2);
    const st = stations.decision; if(st.spin){ const s = st.spin, y = s.position.y; let k = 0;
      fx.push({update(dt, t){ k += dt; s.position.y = y - (k < .3 ? .06 : 0); return k < .6 || (s.position.y = y, false); }}); }
    const ring = new T.Mesh(new T.RingGeometry(.3, .45, 48), new T.MeshBasicMaterial({color: AMBER, transparent: true, side: T.DoubleSide, depthWrite: false}));
    ring.rotation.x = -Math.PI / 2; ring.position.copy(st.work).setY(.03); scene.add(ring);
    let k = 0;
    fx.push({update(dt, t){ k += dt; ring.scale.setScalar(1 + k * 10); ring.material.opacity = Math.max(0, 1 - k / 1.4); if(k > 1.4){ scene.remove(ring); return false; } return true; }});
  }

  /* ---------- camera: slow drift, drag to look around, scroll/pinch to zoom ---------- */
  const target = new T.Vector3(0, 1.0, -1.2);
  const cam = {theta: 0, phi: 1.08, r: 24, auto: true, resumeAt: 0};
  let drag = null;
  o.canvas.addEventListener('pointerdown', e => { drag = {x: e.clientX, y: e.clientY, th: cam.theta, ph: cam.phi, moved: false}; o.canvas.setPointerCapture(e.pointerId); });
  o.canvas.addEventListener('pointermove', e => {
    if(!drag) return;
    const dx = e.clientX - drag.x, dy = e.clientY - drag.y;
    if(Math.abs(dx) + Math.abs(dy) > 4) drag.moved = true;
    cam.theta = drag.th - dx * .006; cam.phi = Math.min(1.42, Math.max(.45, drag.ph - dy * .004));
    cam.auto = false; cam.resumeAt = clock.elapsedTime + 10;
  });
  o.canvas.addEventListener('pointerup', e => {
    if(drag && !drag.moved) pick(e);
    drag = null;
  });
  o.canvas.addEventListener('wheel', e => { e.preventDefault(); cam.r = Math.min(40, Math.max(11, cam.r * (1 + Math.sign(e.deltaY) * .08))); cam.auto = false; cam.resumeAt = clock.elapsedTime + 10; }, {passive: false});
  const ray = new T.Raycaster(), ndc = new T.Vector2();
  function pick(e){
    const r = o.canvas.getBoundingClientRect();
    ndc.set((e.clientX - r.left) / r.width * 2 - 1, -(e.clientY - r.top) / r.height * 2 + 1);
    ray.setFromCamera(ndc, camera);
    const cands = Object.entries(bots).map(([id, w]) => [id, w.m.g]).concat([['captain', captain.g]]);
    for(const [id, g] of cands) if(ray.intersectObject(g, true).length){ o.onSelect && o.onSelect(id); return; }
    for(const id in stations) if(ray.intersectObject(stations[id].group, true).length){ o.onSelect && o.onSelect(id); return; }
  }

  /* ---------- account switch ---------- */
  let S = null, active = null;
  function drawStation(id, on){ const st = stations[id]; drawScreen(st.sc, st.num, st.name, S.stations[id], on); st.light.intensity = on ? 14 : 6; st.sideGlow.material.color.set(on ? AMBER : 0x6b5229); }
  function setStrategy(next){
    S = next;
    const o2 = o.outfits[S.name] || o.outfits.aggressive;
    denim.color.set(o2.cloth); pocket.color.set(o2.pocket);
    for(const id in stations) drawStation(id, false);
    drawHolo(S);
  }
  function replay(){
    pendingEvent = true; route = 0; trip++;
    courier.m.g.position.copy(stations.scout.handoff).add(new T.Vector3(1.5, 0, 1.5));
    walkTo(courier, [stations.scout.handoff.clone()], () => arrive('scout'));
  }

  /* ---------- loop ---------- */
  const clock = new T.Clock();
  let visible = true;
  new IntersectionObserver(es => { visible = es[0].isIntersecting; }).observe(o.stage);
  function resize(){
    const w = o.stage.clientWidth, h = o.stage.clientHeight;
    renderer.setSize(w, h, false); camera.aspect = w / h;
    const tall = w / h < 1; camera.fov = tall ? 62 : 40; cam.r = tall ? 27 : 27; cam.phi = tall ? .78 : 1.08;
    camera.updateProjectionMatrix();
  }
  new ResizeObserver(resize).observe(o.stage); resize();

  function frame(){
    requestAnimationFrame(frame);
    if(!visible || document.hidden){ clock.getDelta(); return; }
    const dt = Math.min(.05, clock.getDelta()), t = clock.elapsedTime;
    if(!cam.auto && t > cam.resumeAt) cam.auto = true;
    if(cam.auto && !reduced) cam.theta += (Math.sin(t * .05) * .38 - cam.theta) * .01;
    camera.position.set(target.x + cam.r * Math.sin(cam.phi) * Math.sin(cam.theta), target.y + cam.r * Math.cos(cam.phi), target.z + cam.r * Math.sin(cam.phi) * Math.cos(cam.theta));
    camera.lookAt(target);
    for(const id in bots) crewBrain(bots[id], stations[id], t);
    everyone().forEach(w => w.m !== captain ? animate(w, dt, t) : null);
    animateCaptain(dt, t);
    for(const id in stations){ const sp = stations[id].spin; if(sp && id !== 'decision') sp.rotation.y += dt * (id === 'news' ? .8 : .4); }
    ico.rotation.y += dt * .5; ico.rotation.x += dt * .2;
    holoPanel.lookAt(camera.position.x, holoPanel.getWorldPosition(v3).y, camera.position.z);
    farShips.forEach((g, i) => { g.position.x += dt * (i ? -.6 : .4); });
    for(let i = fx.length - 1; i >= 0; i--) if(fx[i].update(dt, t) === false) fx.splice(i, 1);
    renderer.render(scene, camera);
    placeLabels(t);
  }
  function animateCaptain(dt, t){
    const c = captain, moodOn = capW.mood && t < capW.moodUntil;
    if(!moodOn) capW.mood = null;
    c.body.position.y = capW.mood === 'cheer' ? Math.abs(Math.sin(t * 8)) * .45 : Math.sin(t * 1.6) * .02;
    c.body.rotation.x = capW.mood === 'sad' ? .25 : 0;
    c.head.rotation.y = capW.mood ? 0 : Math.sin(t * .45) * .5;
    const up = capW.mood === 'cheer';
    c.arms[0].rotation.z = up ? -2.6 : -.25; c.arms[1].rotation.z = up ? 2.6 + Math.sin(t * 12) * .3 : .25 + Math.max(0, Math.sin(t * .3)) * .0;
    c.arms[1].rotation.x = up ? 0 : -.2 + Math.sin(t * .7) * .05;
    c.mouth.rotation.z = capW.mood === 'sad' ? 0 : Math.PI;
  }

  setStrategy(o.strategy);
  replay();
  frame();
  return {setStrategy, replay, play};
}
window.World3D = {init};
})();
