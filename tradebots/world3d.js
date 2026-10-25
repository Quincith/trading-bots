/* Bot World in 3D: the crew aboard their ship, built with three.js.
   Each worker has a room built around its job, the Captain (an original chrome robot titan) sits in a
   throne room, the laser beam has its own chamber in the middle, and a courier scoots between rooms.
   Nothing stands between the camera and the ship: there are no columns or ceilings.
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
  scene.fog = new T.Fog(0x030406, 80, 220);
  const camera = new T.PerspectiveCamera(40, 1, .1, 800);

  /* ---------- helpers ---------- */
  const std = (color, extra) => new T.MeshStandardMaterial(Object.assign({color, roughness: .6, metalness: .1}, extra || {}));
  const glow = color => new T.MeshBasicMaterial({color});
  function mesh(geo, mat, parent, x = 0, y = 0, z = 0, shadow = true){
    const m = new T.Mesh(geo, mat); m.position.set(x, y, z);
    if(shadow){ m.castShadow = true; m.receiveShadow = true; }
    if(parent) parent.add(m);
    return m;
  }
  const AMBER = 0xe8b45a, GREEN = 0x36ff7a;
  const polar = (a, r) => new T.Vector3(Math.sin(a) * r, 0, -Math.cos(a) * r);   // a = 0 is the back of the ship
  const angleOf = v => Math.atan2(v.x, -v.z);
  const deg = d => d * Math.PI / 180;

  // a small reflection map so chrome looks like chrome
  const pmrem = new T.PMREMGenerator(renderer);
  const envScene = new T.Scene();
  envScene.add(new T.Mesh(new T.SphereGeometry(50, 32, 16), new T.ShaderMaterial({side: T.BackSide,
    vertexShader: 'varying vec3 p; void main(){ p = normalize(position); gl_Position = projectionMatrix * modelViewMatrix * vec4(position,1.); }',
    fragmentShader: 'varying vec3 p; void main(){ float y = p.y; vec3 c = mix(vec3(.08,.09,.12), vec3(.42,.46,.55), smoothstep(-.3,.9,y)); c += vec3(1.,.8,.55) * smoothstep(.06,.0,abs(y-.02)) * 1.4; c += vec3(.9,.95,1.) * smoothstep(.04,.0,abs(y-.45)) * .9; gl_FragColor = vec4(c,1.); }'})));
  // studio strip lights: hard bright bars on a dark room give chrome its mirror look
  for(const [x, y, z, w, h, c] of [[24, 8, 0, 1, 14, 0xffffff], [-24, 10, 6, 1, 16, 0xdfe8ff], [0, 26, -10, 22, 1.4, 0xffffff], [8, 6, -24, 6, 10, 0xffd08a], [-10, 18, 22, 10, 2, 0x9fd8ff], [0, -6, 26, 18, 1, 0xe8b45a]]){
    const p = new T.Mesh(new T.BoxGeometry(w, h, Math.min(w, h)), new T.MeshBasicMaterial({color: c})); p.position.set(x, y, z); p.lookAt(0, 0, 0); envScene.add(p);
  }
  const envMap = pmrem.fromScene(envScene, .02).texture;
  const chrome = std(0xe8edf3, {metalness: 1, roughness: .07, envMap, envMapIntensity: 1.6});
  const darkChrome = std(0x4a505c, {metalness: 1, roughness: .18, envMap, envMapIntensity: 1.3});
  const goldChrome = std(0xe8b45a, {metalness: 1, roughness: .15, envMap, envMapIntensity: 1.4});

  /* ---------- light ---------- */
  scene.add(new T.HemisphereLight(0xc9d2ff, 0x2a1c0a, 1.0));
  const key = new T.DirectionalLight(0xffe6c0, 1.6);
  key.position.set(14, 30, 18); key.castShadow = true;
  key.shadow.mapSize.set(2048, 2048);
  Object.assign(key.shadow.camera, {left: -26, right: 26, top: 26, bottom: -26, near: 1, far: 90});
  key.shadow.bias = -.0005;
  scene.add(key);
  const rim = new T.DirectionalLight(AMBER, 1.0); rim.position.set(-16, 12, -24); scene.add(rim);
  const gl = new T.PointLight(GREEN, 0, 40, 1.6); scene.add(gl);   // the laser's glow; made up front so it never forces a shader rebuild

  /* ---------- the view outside: stars, a planet's amber edge, distant ships ---------- */
  const starGeo = new T.BufferGeometry(), sp = [];
  for(let i = 0; i < 2600; i++){
    const u = Math.random() * 2 - 1, th = Math.random() * Math.PI * 2, r = 380, s = Math.sqrt(1 - u * u);
    sp.push(r * s * Math.cos(th), r * u, r * s * Math.sin(th));
  }
  starGeo.setAttribute('position', new T.Float32BufferAttribute(sp, 3));
  scene.add(new T.Points(starGeo, new T.PointsMaterial({color: 0xffffff, size: 1.3, sizeAttenuation: true, fog: false})));
  const planet = mesh(new T.SphereGeometry(200, 64, 32), new T.MeshBasicMaterial({color: 0x0b0805, fog: false}), scene, 60, -260, -330, false);
  const atmo = new T.Mesh(new T.SphereGeometry(208, 64, 32), new T.ShaderMaterial({
    side: T.BackSide, transparent: true, blending: T.AdditiveBlending, depthWrite: false, fog: false,
    uniforms: {c: {value: new T.Color(0xffb85a)}},
    vertexShader: 'varying vec3 vN; varying vec3 vV; void main(){ vec4 mv = modelViewMatrix * vec4(position,1.); vN = normalize(normalMatrix * normal); vV = normalize(-mv.xyz); gl_Position = projectionMatrix * mv; }',
    fragmentShader: 'uniform vec3 c; varying vec3 vN; varying vec3 vV; void main(){ float f = pow(max(0., .62 - dot(vN, vV)), 2.2); gl_FragColor = vec4(c * f * 2.4, f); }'
  }));
  atmo.position.copy(planet.position); scene.add(atmo);
  const farShips = [];
  for(const [x, y, z, s] of [[-180, 30, -260, 1], [200, 50, -240, .7], [80, -20, -320, .5]]){
    const g = new T.Group(); g.position.set(x, y, z); g.scale.setScalar(s); scene.add(g);
    mesh(new T.BoxGeometry(50, 2.6, 7), new T.MeshBasicMaterial({color: 0x14161c, fog: false}), g, 0, 0, 0, false);
    mesh(new T.BoxGeometry(32, .35, 7.2), new T.MeshBasicMaterial({color: AMBER, fog: false}), g, 3, 0, 0, false);
    farShips.push(g);
  }

  /* ---------- the deck: open to the sky, no columns ---------- */
  const deckMat = std(0x12151c, {metalness: .25, roughness: .85});
  mesh(new T.CylinderGeometry(25, 25.6, .6, 96), deckMat, scene, 0, -.3, 0).castShadow = false;
  const rimRing = mesh(new T.TorusGeometry(25.3, .12, 8, 160), glow(0x8a6630), scene, 0, 0, 0, false); rimRing.rotation.x = Math.PI / 2;
  // corridor ring that links every room
  const RING = 7.6;
  const corridor = mesh(new T.RingGeometry(RING - 1.1, RING + 1.1, 96), std(0x1c2029, {metalness: .4, roughness: .6}), scene, 0, .02, 0, false);
  corridor.rotation.x = -Math.PI / 2; corridor.receiveShadow = true;
  for(let i = 0; i < 48; i++){
    const a = i / 48 * Math.PI * 2;
    for(const r of [RING - 1.05, RING + 1.05]){ const p = polar(a, r); mesh(new T.BoxGeometry(.12, .03, .12), glow(i % 2 ? 0x6b5229 : AMBER), scene, p.x, .04, p.z, false); }
  }

  /* ---------- canvas text ---------- */
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
  function drawScreen(sc, num, name, room, st, active){
    const {c, ctx} = sc, w = c.width, h = c.height;
    ctx.clearRect(0, 0, w, h);
    ctx.fillStyle = active ? 'rgba(40,30,10,.92)' : 'rgba(8,10,14,.86)'; ctx.fillRect(0, 0, w, h);
    ctx.strokeStyle = active ? '#e8b45a' : '#5a4422'; ctx.lineWidth = 6; ctx.strokeRect(3, 3, w - 6, h - 6);
    ctx.fillStyle = '#e8b45a'; ctx.font = `700 28px ${FONT}`; ctx.fillText(num, 24, 48);
    ctx.fillStyle = '#ece7dc'; ctx.font = `600 32px ${FONT}`; ctx.fillText(name.toUpperCase(), 70, 48);
    ctx.fillStyle = '#9c9480'; ctx.font = `500 20px ${FONT}`; ctx.fillText(room.toUpperCase(), 70, 76);
    const chip = CHIP[st.status] || 'STANDBY', hot = st.status === 'found' || st.status === 'buy';
    ctx.font = `700 22px ${FONT}`; const cw = ctx.measureText(chip).width + 24;
    ctx.fillStyle = hot ? '#e8b45a' : st.status === 'blocked' ? '#3a1714' : '#1a1a14';
    ctx.fillRect(w - cw - 22, 24, cw, 34);
    ctx.fillStyle = hot ? '#1a1206' : st.status === 'blocked' ? '#ff7466' : '#e8b45a'; ctx.fillText(chip, w - cw - 10, 49);
    ctx.fillStyle = '#d8d2c4'; ctx.font = `400 27px ${FONT}`;
    wrap(ctx, st.say, 24, 124, w - 48, 36, 4);
    sc.tex.needsUpdate = true;
  }

  /* ---------- the helpers (original designs) ---------- */
  const yellow = std(0xf7d33b, {roughness: .45});
  const denim = std(0x8db8e3, {roughness: .95});
  const pocket = std(0x74a2d2, {roughness: .95});
  const black = std(0x1b1b1b, {roughness: .5});
  const metal = std(0xb8c0cc, {metalness: .85, roughness: .25, envMap});
  const white = std(0xffffff, {roughness: .2});
  const iris = std(0x5a3a1a), pupil = std(0x0a0a0a, {roughness: .1});
  const gold = std(0xd9ac5c, {metalness: .7, roughness: .3});

  function goggle(parent, x, r){
    mesh(new T.TorusGeometry(r, r * .32, 12, 28), metal, parent, x, 0, .4);
    const eye = mesh(new T.SphereGeometry(r * .92, 20, 14), white, parent, x, 0, .37); eye.scale.z = .55;
    const ir = mesh(new T.SphereGeometry(r * .42, 14, 10), iris, parent, x + r * .08, -r * .05, .43); ir.scale.z = .4;
    const pu = mesh(new T.SphereGeometry(r * .22, 10, 8), pupil, parent, x + r * .08, -r * .05, .455); pu.scale.z = .4;
  }
  function helper(kind){
    const g = new T.Group(), body = new T.Group(); g.add(body);
    mesh(new T.CapsuleGeometry(.42, .62, 8, 20), yellow, body, 0, .98, 0);
    mesh(new T.CylinderGeometry(.435, .435, .25, 28), denim, body, 0, .79, 0);
    mesh(new T.SphereGeometry(.435, 28, 14, 0, Math.PI * 2, Math.PI / 2, Math.PI / 2), denim, body, 0, .67, 0);
    mesh(new T.BoxGeometry(.44, .3, .08), denim, body, 0, 1.0, .39);
    mesh(new T.BoxGeometry(.22, .12, .03), pocket, body, 0, .98, .44);
    for(const s of [-1, 1]){
      const strap = mesh(new T.BoxGeometry(.07, .42, .05), denim, body, s * .2, 1.27, .33); strap.rotation.x = -.35;
      mesh(new T.SphereGeometry(.035, 8, 6), gold, body, s * .17, 1.12, .43);
    }
    const band = mesh(new T.TorusGeometry(.425, .055, 8, 40), black, body, 0, 1.3, 0); band.rotation.x = Math.PI / 2;
    const face = new T.Group(); face.position.y = 1.3; body.add(face);
    const two = kind === 'charts' || kind === 'news' || kind === 'risk' || kind === 'decision';
    if(two){ goggle(face, -.15, .13); goggle(face, .15, .13); } else goggle(face, 0, .19);
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
    return {g, body, arms, legs, mouth, kind, height: 1.95};
  }

  // the courier rides a scooter and carries a glowing envelope
  function courierModel(){
    const m = helper('courier');
    const ride = new T.Group(); m.g.add(ride);
    // lift the helper onto the deck of the scooter
    m.body.position.y = 0; m.ride = ride; m.lift = .2;
    m.legs.forEach(l => { l.position.y += m.lift; });
    const deckM = std(0x2a2e38, {metalness: .6, roughness: .35});
    mesh(new T.BoxGeometry(.42, .06, 1.05), deckM, ride, 0, .14, 0);
    mesh(new T.BoxGeometry(.44, .02, .9), glow(AMBER), ride, 0, .11, 0, false);
    m.wheels = [];
    for(const z of [-.45, .45]){
      const w = mesh(new T.CylinderGeometry(.13, .13, .1, 18), black, ride, 0, .13, z); w.rotation.z = Math.PI / 2;
      mesh(new T.CylinderGeometry(.06, .06, .11, 12), metal, w, 0, 0, 0, false);
      m.wheels.push(w);
    }
    const stem = mesh(new T.CylinderGeometry(.035, .035, 1.15, 8), metal, ride, 0, .7, .5); stem.rotation.x = -.18;
    const bar = mesh(new T.CylinderGeometry(.03, .03, .62, 8), metal, ride, 0, 1.25, .6); bar.rotation.z = Math.PI / 2;
    for(const s of [-1, 1]) mesh(new T.CylinderGeometry(.04, .04, .1, 8), black, ride, s * .3, 1.25, .6).rotation.z = Math.PI / 2;
    mesh(new T.SphereGeometry(.06, 10, 8), glow(0xfff1c8), ride, 0, 1.0, .62, false);   // headlight
    const env = new T.Group(); env.position.set(0, .95, .46); m.body.add(env);
    mesh(new T.BoxGeometry(.4, .26, .06), std(AMBER, {emissive: AMBER, emissiveIntensity: .4}), env);
    m.carry = env;
    m.g.children.forEach(ch => { if(ch === m.body) ch.position.y = m.lift; });
    return m;
  }

  /* ---------- the Captain: an original chrome robot titan ---------- */
  function titanModel(){
    const g = new T.Group(), body = new T.Group(); g.add(body);
    const eyeMat = new T.MeshBasicMaterial({color: 0x7fd8ff, toneMapped: false});
    const coreMat = new T.MeshBasicMaterial({color: AMBER, toneMapped: false});
    // seated: thighs forward, shins down
    for(const s of [-1, 1]){
      mesh(new T.CylinderGeometry(.48, .4, 2.1, 10), chrome, body, s * .75, 1.95, .9).rotation.x = Math.PI / 2; // thigh
      mesh(new T.BoxGeometry(.95, .3, .5), goldChrome, body, s * .75, 2.4, 1.7);       // knee guard
      mesh(new T.CylinderGeometry(.42, .34, 1.9, 8), darkChrome, body, s * .75, 1.05, 1.95);    // shin
      mesh(new T.BoxGeometry(.95, .14, 1.2), chrome, body, s * .75, 1.55, 2.4).rotation.x = .25; // shin plate
      mesh(new T.BoxGeometry(1.0, .35, 1.45), chrome, body, s * .75, .18, 2.2);         // foot
    }
    mesh(new T.BoxGeometry(2.3, .7, 1.4), darkChrome, body, 0, 2.15, -.1);              // pelvis
    mesh(new T.CylinderGeometry(.7, .95, 1.2, 12), darkChrome, body, 0, 2.95, -.1);     // waist
    mesh(new T.TorusGeometry(.82, .07, 8, 24), goldChrome, body, 0, 2.45, -.1, false).rotation.x = Math.PI / 2; // belt
    for(let k = 0; k < 4; k++) mesh(new T.BoxGeometry(1.3 - k * .05, .1, .1), goldChrome, body, 0, 2.55 + k * .22, .62, false); // abdomen ribs
    const chest = new T.Group(); chest.position.set(0, 4.25, -.1); body.add(chest);
    const torso = mesh(new T.CylinderGeometry(1.75, 1.05, 1.9, 6), chrome, chest); torso.scale.z = .55; torso.rotation.y = Math.PI / 6; // V-shaped chest
    mesh(new T.CylinderGeometry(.9, .55, .5, 6), darkChrome, chest, 0, 1.05, 0).scale.z = .7; // collar
    for(const s of [-1, 1]){ const p = mesh(new T.BoxGeometry(1.25, 1.3, .2), chrome, chest, s * .74, .1, .9); p.rotation.y = s * -.25; }
    const core = mesh(new T.OctahedronGeometry(.32), coreMat, chest, 0, .05, 1.0, false); core.scale.set(1, 1.3, .6);
    mesh(new T.TorusGeometry(.42, .05, 8, 24), goldChrome, chest, 0, .05, .98, false);
    // shoulders, layered like armor
    const arms = [];
    for(const s of [-1, 1]){
      const sh = new T.Group(); sh.position.set(s * 2.0, 4.85, -.1); body.add(sh);
      const pad = mesh(new T.SphereGeometry(.85, 20, 12, 0, Math.PI * 2, 0, Math.PI / 2), chrome, sh, s * .1, .2, 0); pad.scale.set(1.15, .9, 1); pad.rotation.z = s * -.3;
      mesh(new T.BoxGeometry(1.1, .4, 1.4), goldChrome, sh, s * .2, .05, 0).rotation.z = s * -.35;
      mesh(new T.BoxGeometry(.25, 1.4, .25), chrome, sh, s * .45, .85, -.2).rotation.z = s * -.2;    // fin
      const arm = new T.Group(); sh.add(arm);
      mesh(new T.CylinderGeometry(.36, .3, 1.6, 10), darkChrome, arm, 0, -.9, 0);                // upper arm
      mesh(new T.SphereGeometry(.38, 12, 10), chrome, arm, 0, -1.7, 0);                     // elbow
      const fore = new T.Group(); fore.position.set(0, -1.7, 0); arm.add(fore);
      mesh(new T.CylinderGeometry(.46, .36, 1.9, 8), chrome, fore, 0, -.2, .7).rotation.x = Math.PI / 2; // forearm resting forward on the throne arm
      mesh(new T.BoxGeometry(.85, .25, 1.2), goldChrome, fore, 0, .25, .55);
      const hand = mesh(new T.BoxGeometry(.7, .55, .6), darkChrome, fore, 0, -.25, 1.85);
      arm.userData.fore = fore; arms.push(arm);
    }
    // head: crest, face plate, glowing visor
    const head = new T.Group(); head.position.set(0, 5.8, -.05); head.scale.setScalar(1.3); body.add(head);
    const skull = mesh(new T.CylinderGeometry(.5, .42, 1.1, 8), chrome, head, 0, .2, 0); skull.rotation.y = Math.PI / 8;
    for(const s of [-1, 1]) mesh(new T.BoxGeometry(.12, .7, .55), goldChrome, head, s * .52, .15, .1); // cheek guards
    mesh(new T.BoxGeometry(.75, .45, .2), darkChrome, head, 0, -.15, .52);               // jaw plate
    const visor = mesh(new T.BoxGeometry(.85, .16, .1), eyeMat, head, 0, .32, .55, false);
    const crest = mesh(new T.ConeGeometry(.22, 1.1, 4), goldChrome, head, 0, 1.15, .05); crest.rotation.y = Math.PI / 4;
    for(const s of [-1, 1]){ const h = mesh(new T.ConeGeometry(.12, .9, 4), chrome, head, s * .55, .95, -.05); h.rotation.z = s * -.5; }
    mesh(new T.BoxGeometry(1.2, .14, .14), goldChrome, head, 0, .72, .48, false);           // brow
    // halo behind the head
    const halo = mesh(new T.TorusGeometry(1.6, .06, 8, 64), coreMat, body, 0, 6.0, -1.1, false);
    const halo2 = mesh(new T.TorusGeometry(1.9, .025, 6, 64), new T.MeshBasicMaterial({color: 0x8a6630}), body, 0, 6.0, -1.15, false);
    const light = new T.PointLight(0x7fd8ff, 6, 6, 2); light.position.set(0, 6, 1.5); body.add(light);
    return {g, body, head, arms, visor, eyeMat, core, coreMat, halo, halo2, height: 7.4};
  }

  /* ---------- rooms ---------- */
  const CREW = o.data.crew;
  const ROOM_NAMES = {scout: 'Observatory', charts: 'Trading floor', news: 'Newsroom', sentiment: 'Listening post', risk: 'Vault', decision: 'Command room'};
  const ROOM_TINT = {scout: 0x161c2a, charts: 0x14201a, news: 0x201c16, sentiment: 0x1e1626, risk: 0x221615, decision: 0x241d10};
  const ROOM_ANGLE = {scout: -58, charts: -108, news: -156, sentiment: 156, risk: 108, decision: 58};
  const RR = 14, RW = 7.4, RD = 6.2;
  const wallMat = std(0x1b1f28, {metalness: .55, roughness: .45});
  const trimMat = glow(0x8a6630);
  const rooms = {}, props = {}, spinners = [];
  const dark = std(0x2a2e38, {metalness: .6, roughness: .4});

  function walls(parent, w, d, hBack, hFront, door){
    mesh(new T.BoxGeometry(w, hBack, .2), wallMat, parent, 0, hBack / 2, -d / 2);
    mesh(new T.BoxGeometry(w, .05, .24), trimMat, parent, 0, hBack, -d / 2, false);
    for(const s of [-1, 1]){
      mesh(new T.BoxGeometry(.2, hBack, d), wallMat, parent, s * w / 2, hBack / 2, 0);
      mesh(new T.BoxGeometry(.24, .05, d), trimMat, parent, s * w / 2, hBack, 0, false);
      const seg = (w - door) / 2;
      mesh(new T.BoxGeometry(seg, hFront, .2), wallMat, parent, s * (door / 2 + seg / 2), hFront / 2, d / 2);
      mesh(new T.BoxGeometry(seg, .05, .24), glow(AMBER), parent, s * (door / 2 + seg / 2), hFront, d / 2, false);
    }
  }
  function screenCanvas(parent, w, h, draw, x, y, z, ry){
    const cc = textCanvas(w, h); draw(cc.ctx, w, h); cc.tex.needsUpdate = true;
    const p = mesh(new T.PlaneGeometry(w / 220, h / 220), new T.MeshBasicMaterial({map: cc.tex, toneMapped: false}), parent, x, y, z, false);
    p.rotation.y = ry || 0; return {p, cc};
  }
  const candles = (x, w, h) => { x.fillStyle = '#07090d'; x.fillRect(0, 0, w, h); let v = h * .6;
    for(let i = 0; i < 18; i++){ const o2 = v, c = v + (Math.random() - .45) * h * .18; v = Math.min(h * .9, Math.max(h * .1, c));
      x.fillStyle = c < o2 ? '#5fd38d' : '#ff7466'; x.fillRect(10 + i * (w - 20) / 18, Math.min(o2, c), (w - 20) / 18 - 4, Math.max(3, Math.abs(c - o2))); } };

  function buildRoom(c, i){
    const a = deg(ROOM_ANGLE[c.id]), pos = polar(a, RR);
    const r = new T.Group(); r.position.copy(pos); r.rotation.y = Math.atan2(-pos.x, -pos.z); scene.add(r);
    r.updateMatrixWorld(true);
    mesh(new T.BoxGeometry(RW, .1, RD), std(ROOM_TINT[c.id], {metalness: .3, roughness: .7}), r, 0, .05, 0).castShadow = false;
    walls(r, RW, RD, 1.1, .45, 2.2);
    // floor sign at the door
    const sign = textCanvas(512, 96), sx = sign.ctx;
    sx.fillStyle = 'rgba(0,0,0,0)'; sx.clearRect(0, 0, 512, 96);
    sx.fillStyle = '#e8b45a'; sx.font = `700 40px ${FONT}`; sx.textAlign = 'center';
    sx.fillText(`0${i + 1}  ${ROOM_NAMES[c.id].toUpperCase()}`, 256, 62); sign.tex.needsUpdate = true;
    const sg = mesh(new T.PlaneGeometry(3.4, .64), new T.MeshBasicMaterial({map: sign.tex, transparent: true, toneMapped: false, depthWrite: false}), r, 0, .12, 2.45, false);
    sg.rotation.x = -Math.PI / 2;
    const light = new T.PointLight(AMBER, 10, 9, 2); light.position.set(0, 3, 0); r.add(light);
    const P = new T.Group(); r.add(P);   // props
    let work = new T.Vector3(0, 0, .2), face = Math.PI;      // where the worker stands, which way it faces (local)
    const desk = (x, z, ry) => { const d = new T.Group(); d.position.set(x, 0, z); d.rotation.y = ry || 0; P.add(d);
      mesh(new T.BoxGeometry(1.6, .85, .7), dark, d, 0, .42, 0);
      const top = mesh(new T.BoxGeometry(1.6, .06, .8), std(0x232836, {metalness: .5}), d, 0, .88, .05); top.rotation.x = .35;
      for(let k = 0; k < 5; k++) mesh(new T.BoxGeometry(.14, .03, .1), glow([AMBER, 0x5fd38d, 0xff7466][k % 3]), top, -.5 + k * .25, .05, 0, false);
      return d; };
    if(c.id === 'scout'){
      // observatory: a big telescope on a turning mount, a radar sweep on the floor, a star globe
      desk(0, -1.2); work.set(0, 0, -.4); face = Math.PI;
      const mount = new T.Group(); mount.position.set(2.2, 0, -1.7); P.add(mount);
      mesh(new T.CylinderGeometry(.55, .7, .5, 16), dark, mount, 0, .25, 0);
      const yaw = new T.Group(); yaw.position.y = .5; mount.add(yaw);
      mesh(new T.BoxGeometry(.25, 1.0, .25), darkChrome, yaw, 0, .5, 0);
      const tube = mesh(new T.CylinderGeometry(.22, .34, 2.4, 20), goldChrome, yaw, 0, 1.2, .3); tube.rotation.x = -.9;
      mesh(new T.CylinderGeometry(.36, .36, .1, 20), metal, tube, 0, -1.2, 0);
      spinners.push({o: yaw, axis: 'y', speed: .25});
      const radar = textCanvas(256, 256), rx = radar.ctx;
      rx.fillStyle = '#05140c'; rx.beginPath(); rx.arc(128, 128, 126, 0, 7); rx.fill();
      rx.strokeStyle = '#2f8a50'; rx.lineWidth = 2; for(const rr of [40, 80, 120]){ rx.beginPath(); rx.arc(128, 128, rr, 0, 7); rx.stroke(); }
      for(let k = 0; k < 7; k++){ rx.fillStyle = '#5fd38d'; rx.beginPath(); rx.arc(40 + Math.random() * 176, 40 + Math.random() * 176, 4, 0, 7); rx.fill(); }
      radar.tex.needsUpdate = true;
      const disc = mesh(new T.CircleGeometry(1.15, 48), new T.MeshBasicMaterial({map: radar.tex, toneMapped: false}), P, -2.1, .12, -1.6, false); disc.rotation.x = -Math.PI / 2;
      const sweep = mesh(new T.CircleGeometry(1.15, 32, 0, .7), new T.MeshBasicMaterial({color: 0x5fd38d, transparent: true, opacity: .35, depthWrite: false}), P, -2.1, .14, -1.6, false); sweep.rotation.x = -Math.PI / 2;
      spinners.push({o: sweep, axis: 'z', speed: 1.6});
      const globe = mesh(new T.IcosahedronGeometry(.55, 1), new T.MeshBasicMaterial({color: 0x7fd8ff, wireframe: true}), P, -2.3, 1.5, 1.6, false);
      mesh(new T.CylinderGeometry(.06, .2, .9, 8), dark, P, -2.3, .45, 1.6);
      spinners.push({o: globe, axis: 'y', speed: .5});
    } else if(c.id === 'charts'){
      // trading floor: a wall of price charts and a drafting table
      for(let k = -1; k <= 1; k++){
        const s = screenCanvas(P, 330, 200, candles, k * 2.1, 1.25, -2.95, 0);
        mesh(new T.BoxGeometry(1.6, 1.0, .08), dark, P, k * 2.1, 1.25, -3.0);
        s.p.position.z = -2.94;
      }
      desk(0, -1.0); work.set(0, 0, -.2); face = Math.PI;
      const table = new T.Group(); table.position.set(2.2, 0, 1.2); P.add(table);
      mesh(new T.BoxGeometry(1.5, .1, 1.1), std(0x6b4a2a), table, 0, .95, 0).rotation.x = -.3;
      for(const [x, z] of [[-.6, -.4], [.6, -.4], [-.6, .4], [.6, .4]]) mesh(new T.BoxGeometry(.08, .9, .08), dark, table, x, .45, z);
      const paper = screenCanvas(table, 300, 210, (x, w, h) => { x.fillStyle = '#f2efe6'; x.fillRect(0, 0, w, h); x.strokeStyle = '#1c7c4a'; x.lineWidth = 5; x.beginPath();
        [[10, 180], [70, 140], [120, 160], [180, 90], [240, 110], [290, 30]].forEach(([a2, b], k) => k ? x.lineTo(a2, b) : x.moveTo(a2, b)); x.stroke(); }, 0, 1.02, 0, 0);
      paper.p.rotation.x = -Math.PI / 2 - .3;
      const ticker = mesh(new T.TorusGeometry(.5, .04, 6, 32), glow(0x5fd38d), P, -2.4, 1.8, 1.2, false);
      spinners.push({o: ticker, axis: 'y', speed: 1});
    } else if(c.id === 'news'){
      // newsroom: a printing press with turning rollers, stacks of papers, a headline ticker
      const press = new T.Group(); press.position.set(1.9, 0, -1.6); P.add(press);
      mesh(new T.BoxGeometry(2.2, 1.0, 1.2), std(0x3a3226, {metalness: .5}), press, 0, .5, 0);
      for(let k = 0; k < 3; k++){
        const rl = mesh(new T.CylinderGeometry(.22, .22, 1.3, 16), metal, press, -.7 + k * .7, 1.2, 0); rl.rotation.x = Math.PI / 2;
        spinners.push({o: rl, axis: 'y', speed: 4});
      }
      const sheet = mesh(new T.PlaneGeometry(2.0, .9), new T.MeshStandardMaterial({color: 0xf2efe6, side: T.DoubleSide}), press, 0, 1.25, .66, false);
      for(let k = 0; k < 4; k++) mesh(new T.BoxGeometry(.6, .1 + Math.random() * .3, .45), std(0xe9e4d6), P, -2.6 + (k % 2) * .7, .1, 1.5 - Math.floor(k / 2) * .6);
      desk(-1.2, -1.2); work.set(-1.2, 0, -.4); face = Math.PI;
      const tk = textCanvas(1024, 80); const tick = mesh(new T.PlaneGeometry(5.6, .44), new T.MeshBasicMaterial({map: tk.tex, toneMapped: false}), P, 0, 1.25, -2.95, false);
      props.ticker = {cc: tk, x: 0};
    } else if(c.id === 'sentiment'){
      // listening post: a big dish, speaker towers, and a mood gauge
      const dishBase = new T.Group(); dishBase.position.set(2.1, 0, -1.7); P.add(dishBase);
      mesh(new T.CylinderGeometry(.12, .2, 1.4, 10), dark, dishBase, 0, .7, 0);
      const head = new T.Group(); head.position.y = 1.5; dishBase.add(head);
      const dish = mesh(new T.SphereGeometry(1.0, 28, 12, 0, Math.PI * 2, 0, Math.PI / 3.4), std(0xd8d2c4, {side: T.DoubleSide, metalness: .5, roughness: .3, envMap}), head, 0, 0, 0);
      dish.rotation.x = -1.0;
      mesh(new T.CylinderGeometry(.02, .02, .9, 6), metal, head, 0, .25, .35).rotation.x = -1.0;
      mesh(new T.SphereGeometry(.07, 8, 6), glow(AMBER), head, 0, .55, .72, false);
      spinners.push({o: head, axis: 'y', speed: .35});
      for(const x of [-2.9, -1.9]){ mesh(new T.BoxGeometry(.6, 1.5, .5), std(0x15151a), P, x, .75, -2.6); for(const y of [.45, 1.05]) mesh(new T.CylinderGeometry(.18, .18, .05, 18), std(0x3a3a44), P, x, y, -2.33).rotation.x = Math.PI / 2; }
      const g2 = screenCanvas(P, 300, 170, (x, w, h) => { x.fillStyle = '#07090d'; x.fillRect(0, 0, w, h);
        const grad = x.createLinearGradient(30, 0, w - 30, 0); grad.addColorStop(0, '#ff7466'); grad.addColorStop(.5, '#e8b45a'); grad.addColorStop(1, '#5fd38d');
        x.strokeStyle = grad; x.lineWidth = 18; x.beginPath(); x.arc(w / 2, h - 20, 110, Math.PI, 0); x.stroke();
        x.fillStyle = '#b3ad9f'; x.font = `600 18px ${FONT}`; x.textAlign = 'center'; x.fillText('FEAR  ·  MOOD  ·  GREED', w / 2, h - 4); }, 0, 1.2, -2.95, 0);
      mesh(new T.BoxGeometry(1.5, .9, .06), dark, P, 0, 1.2, -3.0);
      const needle = new T.Group(); needle.position.set(0, .82, -2.9); P.add(needle);
      mesh(new T.BoxGeometry(.03, .48, .02), glow(0xffffff), needle, 0, .24, 0, false);
      props.needle = needle;
      desk(0, -1.0); work.set(0, 0, -.2); face = Math.PI;
    } else if(c.id === 'risk'){
      // vault: a round vault door with a turning wheel, a floating shield, warning lights, lockers
      const door = new T.Group(); door.position.set(0, 1.35, -2.85); P.add(door);
      mesh(new T.CylinderGeometry(1.25, 1.25, .3, 40), chrome, door, 0, 0, 0).rotation.x = Math.PI / 2;
      mesh(new T.TorusGeometry(1.25, .1, 10, 40), goldChrome, door, 0, 0, .12, false);
      const wheel = new T.Group(); wheel.position.z = .3; door.add(wheel);
      mesh(new T.TorusGeometry(.5, .05, 8, 24), darkChrome, wheel, 0, 0, 0, false);
      for(let k = 0; k < 3; k++) mesh(new T.BoxGeometry(1.1, .07, .07), darkChrome, wheel, 0, 0, 0, false).rotation.z = k * Math.PI / 3;
      spinners.push({o: wheel, axis: 'z', speed: .4});
      const sh = new T.Group(); sh.position.set(2.3, 1.6, -1.2); P.add(sh);
      mesh(new T.CylinderGeometry(.7, .7, .08, 6), std(0x2a2e38, {metalness: .7, emissive: 0x3a2a0c}), sh, 0, 0, 0).rotation.x = Math.PI / 2;
      mesh(new T.TorusGeometry(.62, .035, 6, 6), glow(AMBER), sh, 0, 0, .05, false);
      mesh(new T.CylinderGeometry(.08, .14, 1.2, 8), dark, P, 2.3, .6, -1.2);
      spinners.push({o: sh, axis: 'y', speed: .8});
      for(let k = 0; k < 4; k++) mesh(new T.BoxGeometry(.6, 1.6, .5), std(0x3a4150, {metalness: .6}), P, -3.2 + .01, .8, -1.9 + k * .65).rotation.y = Math.PI / 2;
      props.alarm = [mesh(new T.SphereGeometry(.13, 12, 8), new T.MeshBasicMaterial({color: 0x5fd38d}), P, -1.6, 1.15, -2.9, false),
                      mesh(new T.SphereGeometry(.13, 12, 8), new T.MeshBasicMaterial({color: 0x5fd38d}), P, 1.6, 1.15, -2.9, false)];
      desk(-1.0, -.6, .3); work.set(-.8, 0, .25); face = Math.PI + .3;
    } else if(c.id === 'decision'){
      // command room: a raised podium with the big red button, a high bench, and the cable port to the beam
      mesh(new T.CylinderGeometry(1.5, 1.7, .3, 32), dark, P, 0, .15, -1.2);
      mesh(new T.CylinderGeometry(1.5, 1.5, .03, 32), glow(0x6b5229), P, 0, .31, -1.2, false);
      mesh(new T.CylinderGeometry(.35, .45, 1.0, 16), dark, P, 0, .8, -1.9);
      const btn = mesh(new T.CylinderGeometry(.28, .28, .14, 24), std(0xdd2222, {emissive: 0x550000, roughness: .3}), P, 0, 1.37, -1.9);
      props.button = btn;
      mesh(new T.BoxGeometry(4.2, 1.5, .6), std(0x2a2218, {metalness: .3}), P, 0, .75, -2.7);
      mesh(new T.BoxGeometry(4.3, .08, .7), goldChrome, P, 0, 1.52, -2.7);
      mesh(new T.BoxGeometry(.9, .7, .6), dark, P, -2.6, .35, 1.9);      // cable port by the door
      mesh(new T.CylinderGeometry(.22, .22, .2, 16), glow(AMBER), P, -2.6, .75, 1.9, false);
      work.set(0, .3, -1.05); face = Math.PI;
    }
    const scr = textCanvas(640, 280);
    const panel = mesh(new T.PlaneGeometry(3.7, 1.62), new T.MeshBasicMaterial({map: scr.tex, transparent: true, toneMapped: false, depthWrite: false}), scene, 0, 0, 0, false);
    // the status panel floats on whichever side of the room is farther from the camera, so it never hides the room
    const back = r.localToWorld(new T.Vector3(0, 2.6, -RD / 2 - .3)), front = r.localToWorld(new T.Vector3(0, 2.6, RD / 2 + .3));
    panel.position.copy(back.z < front.z ? back : front);
    const workW = r.localToWorld(work.clone()); workW.y = work.y;
    rooms[c.id] = {id: c.id, name: c.name, num: '0' + (i + 1), room: ROOM_NAMES[c.id], group: r, sc: scr, panel, light,
      work: workW, face: r.rotation.y + face,
      door: r.localToWorld(new T.Vector3(0, 0, RD / 2 + .8)), inside: r.localToWorld(new T.Vector3(.9, 0, 1.6)),
      port: c.id === 'decision' ? r.localToWorld(new T.Vector3(-2.6, .75, 1.9)) : null,
      local: (x, z) => r.localToWorld(new T.Vector3(x, 0, z))};
  }
  CREW.forEach(buildRoom);

  /* ---------- the beam room in the middle ---------- */
  const beamRoom = new T.Group(); scene.add(beamRoom);
  mesh(new T.CylinderGeometry(4.2, 4.2, .12, 64), std(0x0f1a14, {metalness: .4, roughness: .6}), beamRoom, 0, .06, 0).castShadow = false;
  for(let k = 0; k < 10; k++){   // low curved wall with gaps
    const a0 = k / 10 * Math.PI * 2;
    if(k % 5 === 0) continue;
    const seg = mesh(new T.CylinderGeometry(4.2, 4.2, .8, 16, 1, true, a0, Math.PI * 2 / 10 - .08), new T.MeshStandardMaterial({color: 0x1b1f28, metalness: .55, roughness: .45, side: T.DoubleSide}), beamRoom, 0, .4, 0);
    const tr = mesh(new T.TorusGeometry(4.2, .03, 4, 16, Math.PI * 2 / 10 - .08), glow(GREEN), beamRoom, 0, .8, 0, false);
    tr.rotation.x = Math.PI / 2; tr.rotation.z = -(a0 - Math.PI / 2);
  }
  const ringFloor = mesh(new T.RingGeometry(1.7, 2.0, 64), new T.MeshBasicMaterial({color: GREEN, transparent: true, opacity: .5}), beamRoom, 0, .14, 0, false);
  ringFloor.rotation.x = -Math.PI / 2;
  mesh(new T.CylinderGeometry(1.4, 1.7, .7, 32), darkChrome, beamRoom, 0, .45, 0);
  mesh(new T.CylinderGeometry(.5, .6, 2.2, 24), chrome, beamRoom, 0, 1.9, 0);
  const emitRings = [];
  for(let k = 0; k < 3; k++){ const rr = mesh(new T.TorusGeometry(.9 - k * .12, .07, 8, 40), goldChrome, beamRoom, 0, 1.3 + k * .6, 0); rr.rotation.x = Math.PI / 2; emitRings.push(rr); }
  const lens = mesh(new T.SphereGeometry(.42, 24, 16), new T.MeshBasicMaterial({color: 0x9dffc0, toneMapped: false}), beamRoom, 0, 3.15, 0, false);
  const BEAM_TOP = new T.Vector3(0, 3.15, 0);
  const beamLight = new T.PointLight(GREEN, 6, 8, 2); beamLight.position.set(0, 2.5, 0); beamRoom.add(beamLight);
  // account value hologram above the beam room
  const hc = textCanvas(512, 200);
  const holoPanel = new T.Mesh(new T.PlaneGeometry(3.6, 1.4), new T.MeshBasicMaterial({map: hc.tex, transparent: true, toneMapped: false, depthWrite: false, side: T.DoubleSide}));
  holoPanel.position.set(0, 5.0, 0); scene.add(holoPanel);
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

  // the cable from the Decision worker's room to the beam, with pulses running along it
  const port = rooms.decision.port, pa = angleOf(port);
  const cablePts = [port.clone(), port.clone().setY(.12),
    polar(pa + .05, RING + .5).setY(.12), polar(pa - .05, RING - 1.4).setY(.12), polar(pa - .1, 4.6).setY(.12),
    polar(pa - .1, 4.2).setY(.9), polar(pa - .12, 2.6).setY(.5), polar(pa - .14, 1.75).setY(.6)];
  const cableCurve = new T.CatmullRomCurve3(cablePts, false, 'catmullrom', .2);
  mesh(new T.TubeGeometry(cableCurve, 160, .12, 10, false), std(0x15171c, {metalness: .6, roughness: .35}), scene, 0, 0, 0, false).castShadow = true;
  const pulses = [];
  for(let k = 0; k < 7; k++) pulses.push({m: mesh(new T.SphereGeometry(.15, 10, 8), new T.MeshBasicMaterial({color: AMBER, toneMapped: false}), scene, 0, 0, 0, false), u: k / 7});
  let pulseSpeed = .12, pulseUntil = 0;

  /* ---------- the throne room at the back ---------- */
  const throne = new T.Group(); const tpos = polar(0, 19); throne.position.copy(tpos); scene.add(throne);
  const TW = 13, TD = 9;
  mesh(new T.BoxGeometry(TW, .14, TD), std(0x15120c, {metalness: .5, roughness: .35}), throne, 0, .07, 0).castShadow = false;
  for(const x of [-4.5, -1.5, 1.5, 4.5]) mesh(new T.BoxGeometry(.06, .02, TD - .4), glow(0x6b5229), throne, x, .15, 0, false);
  // low side and back walls only, so the view stays clear
  mesh(new T.BoxGeometry(TW, 1.4, .3), wallMat, throne, 0, .7, -TD / 2);
  mesh(new T.BoxGeometry(TW, .06, .34), glow(AMBER), throne, 0, 1.4, -TD / 2, false);
  for(const s of [-1, 1]){ mesh(new T.BoxGeometry(.3, 1.0, TD), wallMat, throne, s * TW / 2, .5, 0); mesh(new T.BoxGeometry(.34, .06, TD), glow(AMBER), throne, s * TW / 2, 1.0, 0, false); }
  // stepped dais and the throne
  for(let k = 0; k < 3; k++) mesh(new T.BoxGeometry(7 - k * 1.2, .35, 5 - k * .9), std(0x1f1a12, {metalness: .6, roughness: .3}), throne, 0, .3 + k * .35, -1.6 - k * .2);
  const seat = new T.Group(); seat.position.set(0, 1.2, -2.4); throne.add(seat);
  mesh(new T.BoxGeometry(4.2, 1.1, 3.0), darkChrome, seat, 0, .55, .3);
  mesh(new T.BoxGeometry(4.6, 6.5, .7), darkChrome, seat, 0, 3.2, -1.1);
  mesh(new T.BoxGeometry(.18, 6.3, .1), glow(AMBER), seat, 0, 3.2, -.72, false);
  for(let k = -2; k <= 2; k++){ const sp2 = mesh(new T.ConeGeometry(.28, 1.6 - Math.abs(k) * .3, 4), goldChrome, seat, k * .95, 7.0 - Math.abs(k) * .25, -1.1); sp2.rotation.y = Math.PI / 4; }
  for(const s of [-1, 1]){ mesh(new T.BoxGeometry(.8, 1.0, 3.0), darkChrome, seat, s * 2.4, 1.55, .3); mesh(new T.BoxGeometry(.9, .14, 3.1), goldChrome, seat, s * 2.4, 2.1, .3); }
  const titan = titanModel(); titan.g.position.set(0, 1.2, -2.5); throne.add(titan.g);
  const tLight = new T.PointLight(0xdfe8ff, 14, 16, 2); tLight.position.set(0, 7, 2); throne.add(tLight);
  const throneDoor = throne.localToWorld(new T.Vector3(0, 0, TD / 2 + .9)), throneSpot = throne.localToWorld(new T.Vector3(0, 0, 1.6));

  /* ---------- crew ---------- */
  function walker(model, home, faceAngle){
    model.g.position.copy(home).setY(home.y || 0); model.g.rotation.y = faceAngle;
    scene.add(model.g);
    return {m: model, home: home.clone(), face: faceAngle, path: [], speed: 1.9, mode: 'work', phase: Math.random() * 10,
      until: 0, next: 3 + Math.random() * 8, mood: null, moodUntil: 0};
  }
  const bots = {};
  CREW.forEach(c => { const rm = rooms[c.id]; bots[c.id] = walker(helper(c.id), rm.work, rm.face); });
  const courierM = courierModel();
  const courier = walker(courierM, rooms.scout.inside, 0); courier.speed = 3.4; courier.at = 'scout';
  const capW = {m: titan, mood: null, moodUntil: 0};
  const everyone = () => Object.values(bots).concat([courier, capW]);

  function walkTo(w, pts, then){ w.path = pts.slice(); w.then = then || null; w.mode = 'walk'; }
  function turn(g, target, k){
    let d = target - g.rotation.y; while(d > Math.PI) d -= Math.PI * 2; while(d < -Math.PI) d += Math.PI * 2;
    g.rotation.y += d * Math.min(1, k);
    return d;
  }
  // corridor route: out the door, around the ring, in the next door
  function arc(a0, a1, r){
    let d = a1 - a0; while(d > Math.PI) d -= Math.PI * 2; while(d < -Math.PI) d += Math.PI * 2;
    const n = Math.max(1, Math.ceil(Math.abs(d) / .18)), pts = [];
    for(let k = 1; k <= n; k++) pts.push(polar(a0 + d * k / n, r));
    return pts;
  }
  function route(fromId, toId){
    const from = fromId === 'captain' ? {door: throneDoor} : rooms[fromId];
    const to = toId === 'captain' ? {door: throneDoor, inside: throneSpot} : rooms[toId];
    return [from.door.clone(), ...arc(angleOf(from.door), angleOf(to.door), RING), to.door.clone(), to.inside.clone()];
  }

  function animate(w, dt, t){
    const m = w.m, g = m.g, b = m.body;
    if(!(w.mood && t < w.moodUntil)) w.mood = null;
    let moving = false, steer = 0;
    if(w.path && w.path.length){
      const tgt = w.path[0], dx = tgt.x - g.position.x, dz = tgt.z - g.position.z, dist = Math.hypot(dx, dz);
      if(dist < .1){ w.path.shift(); if(!w.path.length){ w.mode = 'arrived'; const fn = w.then; w.then = null; fn && fn(); } }
      else {
        const step = Math.min(dist, w.speed * dt * (w.mood === 'sad' ? .6 : 1));
        g.position.x += dx / dist * step; g.position.z += dz / dist * step;
        steer = turn(g, Math.atan2(dx, dz), dt * 7); moving = true;
      }
    }
    if(m.ride){   // scooter: wheels turn, rider leans into curves, legs stay put
      m.wheels.forEach(wh => { wh.rotation.x += (moving ? w.speed : 0) * dt / .13; });
      m.ride.rotation.z = m.body.rotation.z = moving ? Math.max(-.25, Math.min(.25, -steer * .6)) : 0;
      b.position.y = m.lift + (moving ? Math.sin(t * 20) * .01 : 0);
      if(m.arms){ m.arms.forEach(a => { a.rotation.x = -1.25; a.rotation.z = (a.position.x < 0 ? -1 : 1) * .05; }); }
      if(w.mood === 'cheer'){ b.position.y = m.lift + Math.abs(Math.sin(t * 9)) * .35; m.arms.forEach((a, i) => { a.rotation.x = 0; a.rotation.z = (i ? 1 : -1) * 2.5; }); }
      if(w.mood === 'sad'){ b.rotation.x = .3; }
      else b.rotation.x = 0;
      if(m.mouth) m.mouth.rotation.z = w.mood === 'sad' ? 0 : Math.PI;
      return;
    }
    const ph = t * 9 + w.phase;
    if(m.legs){ m.legs[0].rotation.x = moving ? Math.sin(ph) * .6 : 0; m.legs[1].rotation.x = moving ? -Math.sin(ph) * .6 : 0; }
    let bob = moving ? Math.abs(Math.sin(ph)) * .06 : Math.sin(t * 2 + w.phase) * .015;
    let armL = 0, armR = 0, armZ = .18, lean = 0;
    if(moving){ armL = -Math.sin(ph) * .5; armR = Math.sin(ph) * .5; }
    else if(w.mode === 'work'){ armL = -1.05 + Math.sin(t * 13 + w.phase) * .18; armR = -1.05 + Math.sin(t * 13 + w.phase + 1.7) * .18; lean = .08; }
    else if(w.mode === 'handoff'){ armR = -1.3; armL = -.2; }
    if(w.mood === 'cheer'){ bob = Math.abs(Math.sin(t * 9 + w.phase)) * .55; armZ = 2.5 + Math.sin(t * 14 + w.phase) * .3; armL = armR = 0; }
    if(w.mood === 'sad'){ lean = .32; armL = armR = .1; armZ = .05; bob = 0; }
    b.position.y = bob; b.rotation.x = lean;
    if(m.arms){ m.arms[0].rotation.x = armL; m.arms[1].rotation.x = armR; m.arms[0].rotation.z = -armZ; m.arms[1].rotation.z = armZ; }
    if(m.mouth) m.mouth.rotation.z = w.mood === 'sad' ? 0 : Math.PI;
  }

  // workers: busy at their station, now and then wander around their own room
  function crewBrain(id, w, t){
    if(w.mode === 'walk' || w.mode === 'handoff' || w.mood) return;
    const rm = rooms[id];
    if(w.mode === 'arrived'){ w.mode = w.returning ? 'work' : 'look'; w.until = t + 1.5 + Math.random() * 2.5; w.returning = false; }
    if(w.mode === 'work'){
      turn(w.m.g, rm.face, .08);
      if(t > w.next){
        const p = rm.local(-RW / 2 + 1 + Math.random() * (RW - 2), -RD / 2 + 1.2 + Math.random() * (RD - 2.2));
        walkTo(w, [p]); w.next = t + 7 + Math.random() * 10;
      }
    } else if(w.mode === 'look' && t > w.until){
      w.returning = true; walkTo(w, [w.home.clone()]);
    }
  }

  /* ---------- courier: scoots each bot's findings to the next room, then to the Captain ---------- */
  const ORDER = CREW.map(c => c.id).concat(['captain']);
  let leg = 0, pendingEvent = true, trip = 0, S = null;
  function arrive(id){
    const myTrip = trip;
    courier.mode = 'handoff'; courier.at = id;
    if(id === 'captain'){
      courier.m.g.lookAt(titan.g.getWorldPosition(new T.Vector3()).setY(0));
      say('captain', S.captain, 3.4);
      if(pendingEvent){ pendingEvent = false; setTimeout(() => play(S.event && S.event.kind), 500); }
    } else {
      const bw = bots[id];
      courier.m.g.lookAt(bw.m.g.position.x, 0, bw.m.g.position.z);
      if(bw.mode !== 'walk'){ bw.mode = 'handoff'; bw.m.g.lookAt(courier.m.g.position.x, bw.m.g.position.y, courier.m.g.position.z); }
      drawRoom(id, true); o.onVisit && o.onVisit(id);
      say(id, S.stations[id].say, 3.2); o.sfx.beep();
      if(id === 'decision'){ pulseSpeed = .6; pulseUntil = clock.elapsedTime + 3; }
      setTimeout(() => { if(bw.mode === 'handoff') bw.mode = 'work'; drawRoom(id, false); o.onVisit && o.onVisit(null); }, 3000);
    }
    setTimeout(() => {
      if(myTrip !== trip) return;
      const next = ORDER[(ORDER.indexOf(id) + 1) % ORDER.length];
      walkTo(courier, route(id, next), () => arrive(next));
    }, reduced ? 2000 : 3000);
  }

  /* ---------- labels and speech bubbles (HTML on top of the canvas) ---------- */
  const labels = {};
  function addLabel(id, name, w){
    const el = document.createElement('div'); el.className = 'lbl'; el.dataset.id = id;
    el.innerHTML = `<span class="lbl-say" hidden></span><span class="lbl-name"></span>`;
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
      v3.set(0, l.w.m.height + .2, 0); g.localToWorld(v3); v3.project(camera);
      const vis = v3.z < 1 && Math.abs(v3.x) < 1.1 && Math.abs(v3.y) < 1.1;
      l.el.style.display = vis ? '' : 'none';
      if(!vis) continue;
      l.el.style.transform = `translate(${(v3.x * .5 + .5) * w}px, ${(-v3.y * .5 + .5) * h}px) translate(-50%, -100%)`;
      l.el.style.zIndex = l.until ? '2000' : String(1000 - Math.round(v3.z * 1000));
      if(l.until && t > l.until){ l.until = 0; l.el.querySelector('.lbl-say').hidden = true; l.el.classList.remove('talking'); }
    }
  }

  /* ---------- effects ---------- */
  const fx = [];   // {update(dt, t) -> false when done}; each effect keeps its own clock so a slow frame never skips it
  function play(kind){ if(kind === 'win') win(); else if(kind === 'loss') loss(); else if(kind === 'buy') buy(); }
  function moodAll(m, secs){ const t = clock.elapsedTime; everyone().forEach(w => { w.mood = m; w.moodUntil = t + secs; }); }
  function win(){
    pulseSpeed = 1.6; pulseUntil = clock.elapsedTime + 3.5;
    pulses.forEach(p => p.m.material.color.set(GREEN));
    const beam = (r, color, opacity) => {
      const geo = new T.CylinderGeometry(r, r, 1, 20, 1, true); geo.translate(0, .5, 0);
      const m = new T.Mesh(geo, new T.MeshBasicMaterial({color, transparent: true, opacity, blending: T.AdditiveBlending, depthWrite: false, fog: false, side: T.DoubleSide}));
      m.position.copy(BEAM_TOP); m.frustumCulled = false; scene.add(m); return m;
    };
    let beams = null, k = 0;
    const ring = new T.Mesh(new T.RingGeometry(.5, .9, 48), new T.MeshBasicMaterial({color: GREEN, transparent: true, side: T.DoubleSide, blending: T.AdditiveBlending, depthWrite: false}));
    ring.rotation.x = -Math.PI / 2; ring.position.set(0, .2, 0);
    gl.position.set(0, 4, 0);
    const bg = scene.background.clone();
    o.sfx.laser();
    fx.push({update(dt){
      k += dt;
      const charge = Math.min(1, k / .6);                 // the pulses race down the cable first
      lens.scale.setScalar(1 + charge * .5); emitRings.forEach((r, i) => { r.rotation.z += dt * (4 + i * 3) * charge; });
      if(k < .6) return true;
      if(!beams){ beams = [beam(.2, 0xd9ffe6, 1), beam(.6, GREEN, .45), beam(1.4, GREEN, .12)]; scene.add(ring); holoPanel.visible = false; }
      const kk = k - .6, rise = Math.min(1, kk / .35), fade = kk > 2.4 ? Math.max(0, 1 - (kk - 2.4) / .8) : 1;
      const wob = fade * (1 + Math.sin(kk * 40) * .06);
      beams.forEach(b => b.scale.set(wob, Math.max(.001, rise * 400), wob));
      ring.scale.setScalar(1 + kk * 10); ring.material.opacity = Math.max(0, .9 - kk * .5);
      gl.intensity = 260 * fade * rise;
      scene.background.copy(bg).lerp(new T.Color(0x06281a), .55 * fade * rise);
      if(kk > 3.2){ scene.remove(...beams, ring); gl.intensity = 0; scene.background.copy(bg); lens.scale.setScalar(1); holoPanel.visible = true;
        pulses.forEach(p => p.m.material.color.set(AMBER)); return false; }
      return true;
    }});
    setTimeout(() => { o.sfx.cheer(); moodAll('cheer', 4); confetti(); }, 1000);
  }
  function confetti(){
    const n = 600, geo = new T.PlaneGeometry(.22, .34);
    const mat = new T.MeshBasicMaterial({side: T.DoubleSide, toneMapped: false});
    const inst = new T.InstancedMesh(geo, mat, n); inst.frustumCulled = false; scene.add(inst);
    const cols = [0xe8b45a, GREEN, 0xf7d33b, 0x8db8e3, 0xff7466, 0xece7dc].map(c => new T.Color(c));
    const P = [];
    for(let i = 0; i < n; i++){
      const a = Math.random() * Math.PI * 2, r = Math.sqrt(Math.random()) * 22;
      P.push({p: new T.Vector3(Math.sin(a) * r, 12 + Math.random() * 14, Math.cos(a) * r), v: new T.Vector3((Math.random() - .5) * 1.4, -2 - Math.random() * 2.2, (Math.random() - .5) * 1.4),
        r: new T.Euler(Math.random() * 6, Math.random() * 6, 0), s: new T.Vector3((Math.random() - .5) * 8, (Math.random() - .5) * 8, 0)});
      inst.setColorAt(i, cols[i % cols.length]);
    }
    const d = new T.Object3D(); let k = 0;
    fx.push({update(dt, t){
      k += dt;
      for(let i = 0; i < n; i++){
        const q = P[i]; q.p.addScaledVector(q.v, dt); q.p.x += Math.sin(t * 2 + i) * dt * .6;
        if(q.p.y < .2){ q.p.y = .2; q.v.set(0, 0, 0); q.s.set(0, 0, 0); q.r.x = -Math.PI / 2; }
        q.r.x += q.s.x * dt; q.r.y += q.s.y * dt;
        d.position.copy(q.p); d.rotation.copy(q.r); d.updateMatrix(); inst.setMatrixAt(i, d.matrix);
      }
      inst.instanceMatrix.needsUpdate = true;
      if(k > 9){ mat.transparent = true; mat.opacity = Math.max(0, 1 - (k - 9) / 2); }
      if(k > 11){ scene.remove(inst); geo.dispose(); mat.dispose(); return false; }
      return true;
    }});
  }
  const tomatoMat = std(0xd3241b, {roughness: .35}), stemMat = std(0x2f8a3a);
  function loss(){
    o.sfx.womp(); moodAll('sad', 5);
    everyone().forEach((w, i) => setTimeout(() => throwTomato(w), 250 + i * 230));
    if(props.alarm) props.alarm.forEach(a => a.material.color.set(0xff3322));
    setTimeout(() => props.alarm && props.alarm.forEach(a => a.material.color.set(S.stations.risk.status === 'blocked' ? 0xff3322 : 0x5fd38d)), 5000);
  }
  function headPoint(w){
    const p = w.m === titan ? new T.Vector3(0, 6.1, .6) : new T.Vector3(0, 1.25, .3);
    return w.m === titan ? titan.body.localToWorld(p) : w.m.g.localToWorld(p);
  }
  function throwTomato(w){
    const big = w.m === titan, tom = new T.Group();
    mesh(new T.SphereGeometry(big ? .45 : .22, 16, 12), tomatoMat, tom);
    mesh(new T.ConeGeometry(.08, .1, 5), stemMat, tom, 0, big ? .45 : .22, 0);
    scene.add(tom);
    const side = new T.Vector3().subVectors(w.m.g.getWorldPosition(new T.Vector3()), camera.position).cross(new T.Vector3(0, 1, 0)).normalize();
    const start = camera.position.clone().lerp(w.m.g.getWorldPosition(new T.Vector3()), .3).addScaledVector(side, (Math.random() < .5 ? -1 : 1) * 8);
    let e = 0; const dur = .9;
    fx.push({update(dt){
      e += dt; const k = Math.min(1, e / dur), end = headPoint(w);
      tom.position.lerpVectors(start, end, k); tom.position.y += Math.sin(k * Math.PI) * 4;
      tom.rotation.x += dt * 12; tom.rotation.z += dt * 9;
      if(k >= 1){ scene.remove(tom); splat(w); return false; }
      return true;
    }});
  }
  function splat(w){
    o.sfx.splat();
    const big = w.m === titan, parent = big ? titan.head : w.m.body, sp = new T.Group();
    const mat = new T.MeshStandardMaterial({color: 0xc8261c, roughness: .3, transparent: true});
    mesh(new T.SphereGeometry(.26, 14, 10), mat, sp).scale.set(1, .85, .3);
    for(let k = 0; k < 6; k++){ const a = k / 6 * Math.PI * 2; mesh(new T.SphereGeometry(.07, 8, 6), mat, sp, Math.cos(a) * .3, Math.sin(a) * .26, 0).scale.z = .4; }
    for(let k = 0; k < 3; k++) mesh(new T.SphereGeometry(.05, 8, 6), mat, sp, -.12 + k * .12, -.3 - k * .06, .02).scale.set(.7, 1.6, .4);
    if(big){ sp.scale.setScalar(1.8); sp.position.set(0, .25, .6); } else sp.position.set(0, 1.2, .45);
    parent.add(sp);
    let k = 0; const s0 = sp.scale.x;
    fx.push({update(dt){
      k += dt; sp.scale.setScalar(s0 * Math.min(1, k * 8));
      if(k > 4) mat.opacity = Math.max(0, 1 - (k - 4) / 1.2);
      if(k > 5.2){ parent.remove(sp); return false; }
      return true;
    }});
  }
  function buy(){
    o.sfx.cheer(); moodAll('cheer', 2.2);
    pulseSpeed = 1.0; pulseUntil = clock.elapsedTime + 2.5;
    const b = props.button; if(b){ const y = b.position.y; let k = 0;
      fx.push({update(dt){ k += dt; b.position.y = y - (k < .3 ? .07 : 0); if(k > .6){ b.position.y = y; return false; } return true; }}); }
    const ring = new T.Mesh(new T.RingGeometry(.3, .45, 48), new T.MeshBasicMaterial({color: AMBER, transparent: true, side: T.DoubleSide, depthWrite: false}));
    ring.rotation.x = -Math.PI / 2; ring.position.copy(rooms.decision.work).setY(.4); scene.add(ring);
    let k = 0;
    fx.push({update(dt){ k += dt; ring.scale.setScalar(1 + k * 10); ring.material.opacity = Math.max(0, 1 - k / 1.4); if(k > 1.4){ scene.remove(ring); return false; } return true; }});
  }

  /* ---------- camera: high, clear view; drag to look around, scroll to zoom ---------- */
  const target = new T.Vector3(0, 0, -2.2);
  const cam = {theta: 0, phi: .72, r: 54, auto: true, resumeAt: 0, base: 54};
  let drag = null;
  o.canvas.addEventListener('pointerdown', e => { drag = {x: e.clientX, y: e.clientY, th: cam.theta, ph: cam.phi, moved: false}; o.canvas.setPointerCapture(e.pointerId); });
  o.canvas.addEventListener('pointermove', e => {
    if(!drag) return;
    const dx = e.clientX - drag.x, dy = e.clientY - drag.y;
    if(Math.abs(dx) + Math.abs(dy) > 4) drag.moved = true;
    cam.theta = drag.th - dx * .006; cam.phi = Math.min(1.3, Math.max(.25, drag.ph - dy * .004));
    cam.auto = false; cam.resumeAt = clock.elapsedTime + 12;
  });
  o.canvas.addEventListener('pointerup', e => { if(drag && !drag.moved) pick(e); drag = null; });
  o.canvas.addEventListener('wheel', e => { e.preventDefault(); cam.r = Math.min(90, Math.max(14, cam.r * (1 + Math.sign(e.deltaY) * .08))); cam.auto = false; cam.resumeAt = clock.elapsedTime + 12; }, {passive: false});
  const ray = new T.Raycaster(), ndc = new T.Vector2();
  function pick(e){
    const r = o.canvas.getBoundingClientRect();
    ndc.set((e.clientX - r.left) / r.width * 2 - 1, -(e.clientY - r.top) / r.height * 2 + 1);
    ray.setFromCamera(ndc, camera);
    for(const [id, w] of Object.entries(bots)) if(ray.intersectObject(w.m.g, true).length) return o.onSelect && o.onSelect(id);
    if(ray.intersectObject(throne, true).length) return o.onSelect && o.onSelect('captain');
    for(const id in rooms) if(ray.intersectObject(rooms[id].group, true).length) return o.onSelect && o.onSelect(id);
  }

  /* ---------- account switch ---------- */
  function drawRoom(id, on){
    const rm = rooms[id]; drawScreen(rm.sc, rm.num, rm.name, rm.room, S.stations[id], on);
    rm.light.intensity = on ? 22 : 10;
  }
  function setStrategy(next){
    S = next;
    const o2 = o.outfits[S.name] || o.outfits.aggressive;
    denim.color.set(o2.cloth); pocket.color.set(o2.pocket);
    for(const id in rooms) if(rooms[id].sc) drawRoom(id, false);
    drawHolo(S);
    if(props.alarm) props.alarm.forEach(a => a.material.color.set(S.stations.risk.status === 'blocked' ? 0xff3322 : 0x5fd38d));
    const c0 = S.latest && S.latest.candidates && S.latest.candidates[0];
    if(props.needle) props.needle.rotation.z = -(c0 ? Math.max(-1, Math.min(1, c0.sentiment_score)) : 0) * 1.3;
    const heads = S.latest && S.latest.candidates.length ? S.latest.candidates.map(c => `${c.symbol.split('/')[0]}: ${c.news || ''}`).join('   •   ') : 'NO MAJOR HEADLINES ON THE WATCHLIST   •   SCANNING THE WIRES';
    props.ticker.text = heads.toUpperCase() + '   •   ';
  }
  function replay(){
    pendingEvent = true; trip++;
    courier.path = []; courier.at = 'scout';
    courier.m.g.position.copy(rooms.scout.door);
    walkTo(courier, [rooms.scout.inside.clone()], () => arrive('scout'));
  }

  /* ---------- loop ---------- */
  const clock = new T.Clock();
  let visible = true;
  new IntersectionObserver(es => { visible = es[0].isIntersecting; }).observe(o.stage);
  function resize(){
    const w = o.stage.clientWidth, h = o.stage.clientHeight;
    if(!w || !h) return;
    renderer.setSize(w, h, false); camera.aspect = w / h;
    const tall = w / h < 1;
    camera.fov = tall ? 60 : 40; cam.base = tall ? 56 : 54; cam.r = cam.base; cam.phi = tall ? .6 : .72;
    camera.updateProjectionMatrix();
  }
  new ResizeObserver(resize).observe(o.stage); resize();

  function frame(){
    requestAnimationFrame(frame);
    if(!visible || document.hidden){ clock.getDelta(); return; }
    const dt = Math.min(.05, clock.getDelta()), t = clock.elapsedTime;
    if(!cam.auto && t > cam.resumeAt) cam.auto = true;
    if(cam.auto && !reduced) cam.theta += (Math.sin(t * .04) * .45 - cam.theta) * .01;
    camera.position.set(target.x + cam.r * Math.sin(cam.phi) * Math.sin(cam.theta), target.y + cam.r * Math.cos(cam.phi), target.z + cam.r * Math.sin(cam.phi) * Math.cos(cam.theta));
    camera.lookAt(target);
    for(const id in bots) crewBrain(id, bots[id], t);
    everyone().forEach(w => { if(w !== capW) animate(w, dt, t); });
    animateTitan(dt, t);
    spinners.forEach(s => { s.o.rotation[s.axis] += dt * s.speed; });
    emitRings.forEach((r, i) => { r.rotation.z += dt * (.4 + i * .3); });
    ringFloor.material.opacity = .35 + Math.sin(t * 2) * .15;
    lens.material.color.setHSL(.38, 1, .62 + Math.sin(t * 3) * .08);
    if(t > pulseUntil) pulseSpeed = .12;
    pulses.forEach(p => { p.u = (p.u + dt * pulseSpeed) % 1; p.m.position.copy(cableCurve.getPointAt(p.u)); });
    if(props.ticker && props.ticker.text){
      const tk = props.ticker, x = tk.cc.ctx; tk.x -= dt * 120;
      x.fillStyle = '#0a0806'; x.fillRect(0, 0, 1024, 80); x.fillStyle = '#e8b45a'; x.font = `600 40px ${FONT}`;
      const wdt = x.measureText(tk.text).width; if(tk.x < -wdt) tk.x += wdt;
      x.fillText(tk.text + tk.text, tk.x, 54); tk.cc.tex.needsUpdate = true;
    }
    for(const id in rooms){ const rm = rooms[id]; if(rm.panel) rm.panel.quaternion.copy(camera.quaternion); }
    holoPanel.quaternion.copy(camera.quaternion);
    farShips.forEach((g, i) => { g.position.x += dt * (i ? -.6 : .4); });
    for(let i = fx.length - 1; i >= 0; i--) if(fx[i].update(dt, t) === false) fx.splice(i, 1);
    renderer.render(scene, camera);
    placeLabels(t);
  }
  function animateTitan(dt, t){
    const c = titan;
    if(!(capW.mood && t < capW.moodUntil)) capW.mood = null;
    const cheer = capW.mood === 'cheer', sad = capW.mood === 'sad';
    // head follows the courier when it is in the throne room, otherwise surveys the ship
    let look = Math.sin(t * .35) * .45;
    if(courier.at === 'captain' || (courier.path.length && courier.path[courier.path.length - 1].distanceTo(throneSpot) < .5)){
      const p = courier.m.g.position, tp = throne.localToWorld(new T.Vector3(0, 0, -2.5));
      look = Math.atan2(p.x - tp.x, p.z - tp.z);
    }
    c.head.rotation.y += (Math.max(-.8, Math.min(.8, look)) - c.head.rotation.y) * .05;
    c.head.rotation.x += ((sad ? .45 : cheer ? -.25 : 0) - c.head.rotation.x) * .08;
    const armR = c.arms[1];
    armR.rotation.x += ((cheer ? -2.6 : 0) - armR.rotation.x) * .1;
    c.arms[0].rotation.x += ((cheer ? -.6 : 0) - c.arms[0].rotation.x) * .1;
    c.body.position.y = cheer ? Math.abs(Math.sin(t * 5)) * .25 : Math.sin(t * 1.2) * .03;
    c.eyeMat.color.set(sad ? 0xff3322 : cheer ? GREEN : 0x7fd8ff);
    c.eyeMat.color.multiplyScalar(sad ? .6 : .8 + Math.sin(t * 3) * .2);
    c.core.rotation.y += dt * (cheer ? 6 : 1.2);
    c.halo.rotation.z += dt * (cheer ? 3 : .3); c.halo2.rotation.z -= dt * .15;
    c.coreMat.color.set(sad ? 0x8a2a1a : cheer ? GREEN : AMBER);
  }

  setStrategy(o.strategy);
  replay();
  frame();
  return {setStrategy, replay, play};
}
window.World3D = {init};
})();
