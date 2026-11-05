// Shared 3D viewer for the v2 controls (stick / throttle / pedals). three.js r128 (global THREE), z-up mm models.
// cfg = {base, groups:{name:{parent, pivot:[x,y,z], axis:'x'|'y'|'z', ang:(st)=>deg, move:(st)=>[dx,dy,dz] (local, after rotation)}},
//        color:(part)=>hex, explode:{name:[dx,dy,dz]}, target:[x,y,z], camDir:[x,y,z], dist, sliders:[{id,label,min,max,step,val,fmt}],
//        dyn:(st,THREE,add)=>void (dynamic meshes rebuilt each update), onData:(data)=>void}
window.CtlViewer = function (cfg) {
  const $ = id => document.getElementById(id);
  const view = $("view");
  const R = new THREE.WebGLRenderer({ antialias: true, alpha: false, preserveDrawingBuffer: true });
  R.setPixelRatio(Math.min(2, devicePixelRatio)); R.outputEncoding = THREE.sRGBEncoding; R.toneMapping = THREE.ACESFilmicToneMapping; R.toneMappingExposure = 1.05;
  R.shadowMap.enabled = true; R.shadowMap.type = THREE.PCFSoftShadowMap;
  view.appendChild(R.domElement);
  const scene = new THREE.Scene();
  const dark = matchMedia("(prefers-color-scheme: dark)").matches && document.documentElement.dataset.theme !== "light";
  scene.background = new THREE.Color(dark ? 0x1b1d21 : 0xe9ecef);
  const cam = new THREE.PerspectiveCamera(32, 1, 2, 20000);
  const ctl = new THREE.OrbitControls(cam, R.domElement); ctl.enableDamping = true;
  scene.add(new THREE.HemisphereLight(0xffffff, 0x50555c, 0.75));
  const key = new THREE.DirectionalLight(0xffffff, 1.25); key.position.set(600, 1100, 700); key.castShadow = true;
  key.shadow.mapSize.set(2048, 2048); const sc = key.shadow.camera; sc.left = sc.bottom = -700; sc.right = sc.top = 700; sc.near = 10; sc.far = 4000; key.shadow.bias = -0.0004;
  scene.add(key);
  const fill = new THREE.DirectionalLight(0xdde6ff, 0.45); fill.position.set(-700, 300, -500); scene.add(fill);
  const rim = new THREE.DirectionalLight(0xffffff, 0.35); rim.position.set(-200, 500, 900); scene.add(rim);
  const ground = new THREE.Mesh(new THREE.PlaneGeometry(6000, 6000), new THREE.ShadowMaterial({ opacity: dark ? 0.45 : 0.18 }));
  ground.rotation.x = -Math.PI / 2; ground.position.y = -0.5; ground.receiveShadow = true; scene.add(ground);
  const grid = new THREE.GridHelper(1200, 24, dark ? 0x3a3f47 : 0xb9c0c8, dark ? 0x2a2e34 : 0xd3d8de); grid.position.y = -0.4; scene.add(grid);
  const world = new THREE.Group(); world.rotation.x = -Math.PI / 2; scene.add(world);
  const G = { fixed: world }, meshes = {};
  const st = {}; let parts = [], data = null;
  // parse hash: #k=v&k=v
  const H = new URLSearchParams(location.hash.slice(1));
  for (const s of cfg.sliders) { st[s.id] = H.has(s.id) ? +H.get(s.id) : s.val; }
  st.e = H.has("e") ? +H.get("e") : 0; st.xray = H.has("xray");
  const hide = (H.get("hide") || "").split(",").filter(Boolean);
  // groups
  function mkGroups() {
    const order = Object.keys(cfg.groups);
    for (const n of order) {
      const g = cfg.groups[n], piv = new THREE.Group(), inner = new THREE.Group();
      const parent = G[g.parent || "fixed"];
      piv.position.set(g.pivot[0], g.pivot[1], g.pivot[2]);        // parent inner frame = model coordinates
      piv.add(inner); inner.position.set(-g.pivot[0], -g.pivot[1], -g.pivot[2]);
      parent === world ? world.add(piv) : parent.userData.inner.add(piv);
      piv.userData.inner = inner; G[n] = piv;
    }
  }
  function holderOf(gname) { return gname === "fixed" || !G[gname] ? world : G[gname].userData.inner; }
  const matCache = {};
  function material(p) {
    const c = cfg.color(p), metal = /steel|AL6061|alu|NdFeB|igus|PTFE/.test(p.material) || p.kind === "cut";
    const k = c + ":" + metal;
    if (!matCache[k]) matCache[k] = new THREE.MeshStandardMaterial({ color: new THREE.Color(c).convertSRGBToLinear(), metalness: metal ? 0.45 : 0.04, roughness: metal ? 0.3 : 0.6, envMapIntensity: 1 });
    return matCache[k];
  }
  function fit() {
    const t = cfg.target, d = cfg.dist, v = new THREE.Vector3(...cfg.camDir).normalize();
    const T = new THREE.Vector3(t[0], t[2], -t[1]);
    ctl.target.copy(T); cam.position.copy(T).add(new THREE.Vector3(v.x, v.z, -v.y).multiplyScalar(d)); ctl.update();
  }
  function resize() { const w = view.clientWidth, h = view.clientHeight; R.setSize(w, h); cam.aspect = w / h; cam.updateProjectionMatrix(); }
  addEventListener("resize", resize); resize();
  mkGroups(); fit();
  if (H.has("cam")) { const c = H.get("cam").split(",").map(Number); cfg.camDir = [c[0], c[1], c[2]]; if (c[3]) cfg.dist = c[3]; fit(); }
  let pending = 0;
  fetch(cfg.base + "parts.json").then(r => r.json()).then(d => {
    data = d; parts = d.parts; const loader = new THREE.STLLoader();
    if (cfg.onData) cfg.onData(d);
    for (const p of parts) {
      if (cfg.skip && cfg.skip(p)) continue;
      pending++;
      loader.load(cfg.base + p.file + "?v=" + (d.meta.created || ""), g => {
        g.computeVertexNormals();
        const m = new THREE.Mesh(g, material(p).clone()); m.castShadow = true; m.receiveShadow = true; m.userData = p;
        const h = new THREE.Group(); h.add(m); m.userData.holder = h; holderOf(p.group).add(h); meshes[p.name] = m;
        if (hide.some(x => p.name.startsWith(x))) m.visible = false;
        if (--pending === 0) { update(); document.body.dataset.ready = "1"; }
      });
    }
  });
  const dynG = new THREE.Group(); world.add(dynG);
  function update() {
    for (const s of cfg.sliders) { const el = $(s.id); if (el) { st[s.id] = +el.value; const o = $(s.id + "v"); if (o) o.textContent = s.fmt ? s.fmt(st[s.id]) : st[s.id]; } }
    const ee = $("exp"); if (ee) st.e = +ee.value / 100;
    const xr = $("xray"); if (xr) st.xray = xr.checked;
    for (const n in cfg.groups) {
      const g = cfg.groups[n], piv = G[n]; piv.rotation.set(0, 0, 0);
      const a = (g.ang ? g.ang(st) : 0) * Math.PI / 180;
      if (g.axis === "x") piv.rotation.x = a; else if (g.axis === "y") piv.rotation.y = a; else if (g.axis === "z") piv.rotation.z = a;
      const mv = g.move ? g.move(st) : [0, 0, 0];
      piv.userData.inner.position.set(-g.pivot[0] + mv[0], -g.pivot[1] + mv[1], -g.pivot[2] + mv[2]);
    }
    for (const n in meshes) {
      const m = meshes[n], v = (cfg.explode && cfg.explode(m.userData)) || [0, 0, 0];
      m.userData.holder.position.set(v[0] * st.e, v[1] * st.e, v[2] * st.e);
      const ghost = st.xray && cfg.xray && cfg.xray(m.userData);
      if (ghost && !m.userData.ghostMat) { m.userData.ghostMat = m.material.clone(); m.userData.ghostMat.transparent = true; m.userData.ghostMat.opacity = 0.16; m.userData.ghostMat.depthWrite = false; m.userData.solidMat = m.material; }
      m.material = ghost ? m.userData.ghostMat : (m.userData.solidMat || m.material);
      m.castShadow = !ghost;
    }
    while (dynG.children.length) { const c = dynG.children.pop(); c.geometry.dispose(); }
    if (cfg.dyn) cfg.dyn(st, (a, b, r, color) => {
      const A = new THREE.Vector3(...a), B = new THREE.Vector3(...b), L = A.distanceTo(B);
      const m = new THREE.Mesh(new THREE.CylinderGeometry(r, r, L, 24), material({ material: "steel", kind: "buy", name: "dyn", color }));
      m.position.copy(A).add(B).multiplyScalar(0.5); m.quaternion.setFromUnitVectors(new THREE.Vector3(0, 1, 0), B.clone().sub(A).normalize());
      m.castShadow = true; dynG.add(m);
    });
    if (cfg.onUpdate) cfg.onUpdate(st);
  }
  for (const s of cfg.sliders) { const el = $(s.id); if (el) { el.value = st[s.id]; el.oninput = update; } }
  if ($("exp")) { $("exp").value = st.e * 100; $("exp").oninput = update; }
  if ($("xray")) { $("xray").checked = st.xray; $("xray").onchange = update; }
  // picking
  const ray = new THREE.Raycaster(), mp = new THREE.Vector2(); let down = null, selN = null;
  R.domElement.addEventListener("pointerdown", e => down = [e.clientX, e.clientY]);
  R.domElement.addEventListener("pointerup", e => {
    if (!down || Math.hypot(e.clientX - down[0], e.clientY - down[1]) > 5) return;
    const r = R.domElement.getBoundingClientRect(); mp.set((e.clientX - r.left) / r.width * 2 - 1, -(e.clientY - r.top) / r.height * 2 + 1);
    ray.setFromCamera(mp, cam); const h = ray.intersectObjects(Object.values(meshes).filter(m => m.visible))[0]; if (h) select(h.object.userData.name);
  });
  function select(n) {
    for (const k in meshes) { const m = meshes[k], sm = m.userData.solidMat || m.material; if (sm.emissive) sm.emissive.setHex(k === n ? 0x553300 : 0); }
    const m = meshes[n]; if (!m) return; selN = n;
    const p = m.userData, inf = $("info");
    if (inf) inf.innerHTML = `<b>${p.name}</b> — ${p.note}<br><span class="muted">${p.kind === "print" ? "출력 · " + p.material + " · 약 " + p.grams + " g · " + (p.orient || "") : p.kind === "cut" ? "레이저 절단 (알루미늄)" : "구매 부품"} · ${p.size.join("×")} mm</span>`;
    document.querySelectorAll("tr[data-n]").forEach(r => r.classList.toggle("sel", r.dataset.n === n));
  }
  (function loop() { ctl.update(); R.render(scene, cam); requestAnimationFrame(loop); })();
  return { select, update, st, get data() { return data; } };
};

// force chart (inline SVG): series = [{name, color, pts:[[x,y],...]}]
window.ctlChart = function (el, series, xl, yl) {
  const W = 420, H = 210, m = { l: 40, r: 10, t: 16, b: 30 };
  const xs = series.flatMap(s => s.pts.map(p => p[0])), ys = series.flatMap(s => s.pts.map(p => p[1]));
  const x0 = Math.min(0, ...xs), x1 = Math.max(...xs), y1 = Math.ceil(Math.max(...ys) / 20) * 20 || 1;
  const X = x => m.l + (x - x0) / (x1 - x0) * (W - m.l - m.r), Y = y => H - m.b - y / y1 * (H - m.t - m.b);
  let s = `<svg viewBox="0 0 ${W} ${H}" width="100%" role="img" aria-label="${yl}">`;
  for (let i = 0; i <= 4; i++) { const y = y1 * i / 4; s += `<line x1="${m.l}" x2="${W - m.r}" y1="${Y(y)}" y2="${Y(y)}" stroke="var(--line)"/><text x="${m.l - 5}" y="${Y(y) + 4}" text-anchor="end" font-size="10" fill="var(--sub)">${Math.round(y)}</text>`; }
  for (let i = 0; i <= 4; i++) { const x = x0 + (x1 - x0) * i / 4; s += `<text x="${X(x)}" y="${H - m.b + 14}" text-anchor="middle" font-size="10" fill="var(--sub)">${Math.round(x)}</text>`; }
  s += `<text x="${(W + m.l) / 2}" y="${H - 3}" text-anchor="middle" font-size="10" fill="var(--sub)">${xl}</text><text x="${m.l + 6}" y="${m.t + 8}" font-size="10" fill="var(--sub)">${yl}</text>`;
  for (const se of series) s += `<polyline fill="none" stroke="${se.color}" stroke-width="${se.w || 2}" ${se.dash ? 'stroke-dasharray="4 3"' : ""} points="${se.pts.map(p => X(p[0]).toFixed(1) + "," + Y(p[1]).toFixed(1)).join(" ")}"/>`;
  s += `</svg><div class="legend">${series.map(se => `<span><i style="background:${se.color}"></i>${se.name}</span>`).join("")}</div>`;
  el.innerHTML = s;
};
