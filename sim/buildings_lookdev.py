"""Offline look-dev of the building tiles (no Unreal): a three.js page rendered by headless Chrome (no window) shows the
built glb tiles (sim/buildings_build.py) on a ground mesh (terrain mesh heights + the cached V-World photo) from the
same views as Scripts/vworld_buildings_check.py.

    python -I sim/buildings_lookdev.py [--views downtown_chase,apartments_orbit] [--tiles-dir tiles] [--out DIR] [--tag new]

Writes the scenes and the ground photo to C:\\GyroSimTiles\\lookdev (V-World derived: never in git), serves C:\\GyroSimTiles
on 127.0.0.1 only for the render, screenshots -> <out>/<view>_<tag>.png. Only cached tiles are read (no API call).
three.js comes from unpkg (pinned 0.160.0). Lighting is a plain sun + sky, not Unreal's: judge layout / textures /
colours here, brightness only in Unreal.
"""
import json, math, os, sys, site, subprocess, threading, time, functools
if sys.flags.isolated:
    site.addsitedir(site.getusersitepackages())
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import numpy as np                                        # noqa: E402
import buildings_build as B                               # noqa: E402
import buildings_tex as BT                                # noqa: E402
import terrain_dem as T                                   # noqa: E402

GT = r"C:\GyroSimTiles"
LD = os.path.join(GT, "lookdev")
CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
JIWELL, DOWNTOWN = (36.6445, 127.4250), (36.6330, 127.4950)


def off(p, brg, km):
    return (p[0] + km * math.cos(math.radians(brg)) / 110.95, p[1] + km * math.sin(math.radians(brg)) / (111.32 * math.cos(math.radians(p[0]))))


APT = off(JIWELL, 90, 1.2)
# camera: (lat, lon, alt m MSL, heading deg, pitch deg, hfov deg); roughly the Unreal check views (chase = 15 m behind /
# 4 m above the jet, orbit = 600 m at yaw 200 / el 6 around it)
VIEWS = {
    "downtown_chase": (*off(DOWNTOWN, 95, 0.02), 234.0, 275.0, -6.0, 90.0),
    "downtown_cockpit": (*DOWNTOWN, 230.0, 275.0, -3.0, 90.0),
    "apartments_orbit": (*off(APT, 20, 0.6), 260.0 + 600 * math.sin(math.radians(6)), 200.0, -6.0, 90.0),
    "apartments_chase": (*off(APT, 90, 0.02), 264.0, 270.0, -6.0, 90.0),
    "apartments_close": (*off(JIWELL, 120, 0.45), 120.0, 300.0, -8.0, 75.0),
    "downtown_street": (*off(DOWNTOWN, 270, 1.2), 95.0, 275.0, -6.0, 75.0),
}


def ground_mesh(lat, lon, half_m, n=96):
    """grid around the view: positions ENU (from the level-13 terrain mesh height + geoid), uv into a photo mosaic."""
    dem = T.Dem()
    dl, dn = half_m / T.M_LAT, half_m / (111320.0 * math.cos(math.radians(lat)))
    la = np.linspace(lat - dl, lat + dl, n)
    lo = np.linspace(lon - dn, lon + dn, n)
    LA, LO = np.meshgrid(la, lo, indexing="ij")
    h = B.mesh_height(dem, LA, LO) + dem.geoid_n(LA, LO)
    R = B.enu_rot(lat, lon)
    C0 = B.ecef(np.array(lat), np.array(lon), np.array(0.0)).reshape(3)
    P = (B.ecef(LA, LO, h) - C0) @ R
    sat = BT.Sat()
    img, z = None, None
    for z in (16, 15, 14, 13):
        X, Y = sat.px(z, LA, LO)
        x0, y0, x1, y1 = int(X.min()) - 1, int(Y.min()) - 1, int(X.max()) + 2, int(Y.max()) + 2
        if (x1 - x0) <= 4096 and sat.covered(z, x0, y0, x1, y1):
            img = sat.crop(z, x0, y0, x1, y1)
            break
    if img is None:                                        # partial cover: fill the missing tiles grey
        z = 15
        X, Y = sat.px(z, LA, LO)
        x0, y0, x1, y1 = int(X.min()) - 1, int(Y.min()) - 1, int(X.max()) + 2, int(Y.max()) + 2
        img = np.full((y1 - y0, x1 - x0, 3), 110, np.uint8)
        for ty in range(y0 // 256, (y1 - 1) // 256 + 1):
            for tx in range(x0 // 256, (x1 - 1) // 256 + 1):
                if (ty, tx) in sat.have.get(z, ()):
                    t = sat.tile(z, ty, tx)
                    ax0, ay0, ax1, ay1 = max(x0, tx * 256), max(y0, ty * 256), min(x1, tx * 256 + 256), min(y1, ty * 256 + 256)
                    img[ay0 - y0:ay1 - y0, ax0 - x0:ax1 - x0] = t[ay0 - ty * 256:ay1 - ty * 256, ax0 - tx * 256:ax1 - tx * 256]
    uv = np.stack(((X - x0) / img.shape[1], (Y - y0) / img.shape[0]), -1)
    return P, uv, img, z


def frame_matrix(lat, lon):
    """4x4 (column-major list) mapping the tiles' glTF root frame (Z2Y-ECEF, metres) to y-up ENU at (lat, lon)."""
    R = B.enu_rot(lat, lon)
    C0 = B.ecef(np.array(lat), np.array(lon), np.array(0.0)).reshape(3)
    S = np.array([[1, 0, 0], [0, 0, 1], [0, -1, 0]], np.float64)       # ENU -> y-up
    Z2Y = S
    # x_zy (Z2Y-ECEF) -> ecef = Z2Y^T x -> enu = R^T (ecef - C0) -> yup = S enu
    A = S @ R.T @ Z2Y.T
    t = -(S @ R.T @ C0)
    M = np.eye(4)
    M[:3, :3], M[:3, 3] = A, t
    return [float(v) for v in M.T.reshape(-1)]


def tiles_near(ts, lat, lon, rad_m):
    out = []
    la, lo = math.radians(lat), math.radians(lon)
    dla, dlo = rad_m / 6371000.0, rad_m / (6371000.0 * math.cos(la))

    def walk(n):
        w, s, e, nn = n["boundingVolume"]["region"][:4]
        if e < lo - dlo or w > lo + dlo or nn < la - dla or s > la + dla:
            return
        if "content" in n:
            out.append(n["content"]["uri"])
        for c in n.get("children", []):
            walk(c)
    walk(ts["root"])
    return out


def build_scene(name, tiles_dir):
    from PIL import Image
    lat, lon, alt, hdg, pitch, fov = VIEWS[name]
    dem = T.Dem()
    geo = float(dem.geoid_n(np.array([lat]), np.array([lon]))[0])
    ts = json.load(open(os.path.join(GT, "buildings", tiles_dir, "tileset.json"), encoding="utf-8"))
    uris = tiles_near(ts, lat, lon, 2500.0)
    P, uv, img, z = ground_mesh(lat, lon, 2600.0)
    os.makedirs(LD, exist_ok=True)
    gname = "ground_%s.jpg" % name
    Image.fromarray(img).save(os.path.join(LD, gname), quality=88)
    n = P.shape[0]
    idx = []
    for i in range(n - 1):
        for j in range(n - 1):
            a = i * n + j
            idx += [a, a + n, a + 1, a + 1, a + n, a + n + 1]
    yup = np.stack((P[..., 0], P[..., 2], -P[..., 1]), -1).reshape(-1, 3)
    sc = dict(name=name, made=time.strftime("%Y-%m-%d %H:%M:%S"), tiles=["/buildings/%s/%s" % (tiles_dir, u) for u in uris],
              frame=frame_matrix(lat, lon), cam=dict(h=alt + geo, hdg=hdg, pitch=pitch, fov=fov),
              ground=dict(pos=np.round(yup, 2).reshape(-1).tolist(), uv=np.round(uv.reshape(-1, 2), 5).reshape(-1).tolist(), idx=idx,
                          img="/lookdev/" + gname, zoom=z))
    with open(os.path.join(LD, "scene_%s.json" % name), "w") as f:
        json.dump(sc, f)
    return len(uris)


PAGE = r"""<!doctype html><html><head><meta charset="utf-8"><style>html,body{margin:0;background:#9fb6cc;overflow:hidden}</style>
<script type="importmap">{"imports":{"three":"https://unpkg.com/three@0.160.0/build/three.module.js","three/addons/":"https://unpkg.com/three@0.160.0/examples/jsm/"}}</script>
</head><body><script type="module">
import * as THREE from 'three';
import {GLTFLoader} from 'three/addons/loaders/GLTFLoader.js';
const q = new URLSearchParams(location.search);
const sc = await (await fetch('/lookdev/scene_' + q.get('v') + '.json')).json();
const W = 1600, H = 900;
const r = new THREE.WebGLRenderer({antialias: true, preserveDrawingBuffer: true});
r.setSize(W, H); r.outputColorSpace = THREE.SRGBColorSpace; r.toneMapping = THREE.ACESFilmicToneMapping; r.toneMappingExposure = 1.0;
document.body.appendChild(r.domElement);
const s = new THREE.Scene(); s.background = new THREE.Color(0x9fb6cc); s.fog = new THREE.Fog(0x9fb6cc, 2500, 9000);
s.add(new THREE.HemisphereLight(0xcfe0ff, 0x6b6450, 1.2));
const sun = new THREE.DirectionalLight(0xfff4e0, 2.6); sun.position.set(-0.45, 0.75, 0.5); s.add(sun);
const c = sc.cam, vf = 2 * Math.atan(Math.tan(c.fov * Math.PI / 360) * H / W) * 180 / Math.PI;
const cam = new THREE.PerspectiveCamera(vf, W / H, 1, 20000);
cam.position.set(0, c.h, 0);
const hd = c.hdg * Math.PI / 180, pt = c.pitch * Math.PI / 180;
cam.lookAt(Math.sin(hd) * Math.cos(pt) * 100, c.h + Math.sin(pt) * 100, -Math.cos(hd) * Math.cos(pt) * 100);
const g = new THREE.BufferGeometry();
g.setAttribute('position', new THREE.Float32BufferAttribute(sc.ground.pos, 3));
g.setAttribute('uv', new THREE.Float32BufferAttribute(sc.ground.uv, 2));
g.setIndex(sc.ground.idx); g.computeVertexNormals();
const gt = await new THREE.TextureLoader().loadAsync(sc.ground.img); gt.colorSpace = THREE.SRGBColorSpace; gt.flipY = false;
gt.anisotropy = 8;
s.add(new THREE.Mesh(g, new THREE.MeshStandardMaterial({map: gt, roughness: 1, side: THREE.DoubleSide})));
const grp = new THREE.Group(); grp.matrixAutoUpdate = false; grp.matrix.fromArray(sc.frame); s.add(grp);
const L = new GLTFLoader(); let n = 0;
await Promise.all(sc.tiles.map(u => L.loadAsync(u).then(gl => {
  gl.scene.traverse(o => { if (o.isMesh) { o.material.side = THREE.FrontSide; const m = o.material.map; if (m) m.anisotropy = 8; } });
  grp.add(gl.scene); n++; }).catch(e => console.log('ERR ' + u + ' ' + e))));
r.render(s, cam);
document.title = 'DONE ' + n;
console.log('DONE tiles ' + n + ' of ' + sc.tiles.length);
</script></body></html>"""


def serve(port):
    import http.server

    class Q(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *a):
            pass
    h = functools.partial(Q, directory=GT)
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", port), h)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def main(a):
    views = a[a.index("--views") + 1].split(",") if "--views" in a else ["downtown_chase", "apartments_orbit", "downtown_cockpit"]
    tdir = a[a.index("--tiles-dir") + 1] if "--tiles-dir" in a else "tiles"
    out = a[a.index("--out") + 1] if "--out" in a else os.path.join(LD, "shots")
    tag = a[a.index("--tag") + 1] if "--tag" in a else tdir
    os.makedirs(out, exist_ok=True)
    with open(os.path.join(LD, "view.html"), "w", encoding="utf-8") as f:
        f.write(PAGE)
    port = 8797
    srv = serve(port)
    prof = os.path.join(LD, "chrome_profile")
    for v in views:
        nt = build_scene(v, tdir)
        png = os.path.join(out, "%s_%s.png" % (v, tag))
        t0 = time.time()
        # headless (no window), software GL; the virtual time budget lets the page load every tile before the shot
        cmd = [CHROME, "--headless=new", "--enable-unsafe-swiftshader", "--use-angle=swiftshader", "--no-first-run",
               "--user-data-dir=" + prof, "--window-size=1600,900", "--hide-scrollbars", "--virtual-time-budget=240000",
               "--screenshot=" + png, "http://127.0.0.1:%d/lookdev/view.html?v=%s" % (port, v)]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        print("%s: %d tiles -> %s (%.0f s, exit %d)" % (v, nt, png, time.time() - t0, r.returncode), flush=True)
    srv.shutdown()


if __name__ == "__main__":
    main(sys.argv[1:])
