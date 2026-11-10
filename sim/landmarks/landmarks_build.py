r"""Busan landmarks as hand-parameterised 3D models (3D Tiles 1.1 + glb), for the Unreal 'vworld' ground mode.

    python -I sim/landmarks/landmarks_build.py --osm        fetch the OSM footprints used below (Overpass, no account) -> work/osm_buildings.json
    python -I sim/landmarks/landmarks_build.py --build      models -> C:\GyroSimTiles\landmarks\tiles (tileset.json + <key>.glb)
                                                           + C:\GyroSimTiles\landmarks\exclude.json (GIS uids the building tiles must skip)
                                                           + sim/landmarks/exclude_ids.json (tracked copy of the uid list, no geometry)
    python -I sim/landmarks/landmarks_build.py --build --only lct_landmark,bifc [--preview]   (subset; exclude.json is still
                                                           written for ALL specs; --preview = matplotlib shape check in work/)

Method (decided 2026-11-10): procedural / parametric modelling from the real footprint (국토교통부 GIS건물통합정보, else
OpenStreetMap, else digitised from the local V-World photo) + published heights / floors + shapes read off reference photos
(Wikimedia Commons, kept local in C:\GyroSimTiles\landmarks\refs, never in git). Rejected: Sketchfab (download needs an account -
not allowed here), image-to-3D AI (TRELLIS / Hunyuan3D: object-scale, not metric, weak on 300 m glass towers, multi-GB weights +
heavy GPU), photogrammetry from random web photos (no overlap / calibration).
Placement: each landmark has its own local ENU frame (origin = footprint centroid, z 0 = lowest rendered-terrain point on the
footprint - 0.3 m, same rule as sim/buildings_build.py so it stands where the GIS block stood); the glb node matrix maps it to
ECEF (Cesium applies Y-up -> Z-up like for the building tiles).
Look: glTF PBR (baseColor texture x vertex colour + metallicRoughness texture) -> Cesium's default material, so Lumen / sky
reflections light the glass like the facade material of the GIS buildings. Facade textures are drawn here (no photos as textures).
Input data never goes to git (licences: GIS CC BY, OSM ODbL - credited on the on-screen plate / ATTRIBUTION; models are derived works).

Pipeline: --osm / --build -> sim/buildings_build.py --tiles reads exclude.json (skips the replaced GIS boxes) -> Unreal:
Content/Python/landmarks_look.py points the 'CesiumLandmarks' actor (Scripts/add_landmarks_actor.py, run once with the editor
closed) at file:///C:/GyroSimTiles/landmarks/tiles/tileset.json at Play (sim_client._vworld_ground).
Check: bash sim/landmarks/run_shots.sh (offscreen editor on a temporary map copy, shared lock C:/GyroSimTiles/ue_offscreen.lock)
-> C:/GyroSimTiles/shots/landmarks, then python -I sim/landmarks/compare_page.py <dir> = reference photo | before | after.
Reference photos: python -I sim/landmarks/refs_fetch.py <key> "<words>" (Commons search, local only, licence per file).
Known limits: shapes are simplified (no balconies / fins / signage), several heights and roof shapes are estimates (see specs.py
'est'), the server's crash raster still uses the GIS boxes (roof_<name>.npy) for the replaced buildings.
"""
import json, math, os, sys, time, struct, site, zipfile, io, glob
if sys.flags.isolated:
    site.addsitedir(site.getusersitepackages())
HERE = os.path.dirname(os.path.abspath(__file__))
SIM = os.path.dirname(HERE)
sys.path.insert(0, SIM)
sys.path.insert(0, HERE)
import numpy as np                                        # noqa: E402

ROOT = os.environ.get("GYROSIM_LANDMARKS", r"C:\GyroSimTiles\landmarks")
WORK, TILES = os.path.join(ROOT, "work"), os.path.join(ROOT, "tiles")
EXCLUDE = os.path.join(ROOT, "exclude.json")
EXCLUDE_TRACKED = os.path.join(HERE, "exclude_ids.json")
OSM_FILE = os.path.join(WORK, "osm_buildings.json")
ZIP = r"C:\GyroSimTiles\incoming\zips\AL_D010_26_20261009.zip"     # 부산 GIS건물통합정보 (same input as buildings_build.py)
A_WGS, E2 = 6378137.0, 6.69437999014e-3
from specs import SPECS, MATS                            # noqa: E402  (the landmark descriptions, with sources)


# ---------------------------------------------------------------------------------------------------------------- inputs
def osm_fetch():
    """Overpass: buildings around the landmark sites (one query, ~1 MB)."""
    import urllib.request, urllib.parse
    pts = sorted({(round(s["site"][0], 4), round(s["site"][1], 4), s.get("site_r", 300)) for s in SPECS})
    q = "[out:json][timeout:120];(" + "".join('way["building"](around:%d,%f,%f);relation["building"](around:%d,%f,%f);' % (r, a, b, r, a, b)
                                             for a, b, r in pts) + ");out tags geom;"
    req = urllib.request.Request("https://overpass-api.de/api/interpreter", data=urllib.parse.urlencode(dict(data=q)).encode(),
                                 headers={"User-Agent": "GyroSimLandmarks/0.1"})
    d = json.load(urllib.request.urlopen(req, timeout=180))
    rel = [e["id"] for e in d["elements"] if e["type"] == "relation"]
    if rel:                                                          # 'out geom' on the area query gave relations without members
        q2 = "[out:json][timeout:120];relation(id:%s);out geom;" % ",".join(map(str, rel))
        req2 = urllib.request.Request("https://overpass-api.de/api/interpreter", data=urllib.parse.urlencode(dict(data=q2)).encode(),
                                      headers={"User-Agent": "GyroSimLandmarks/0.1"})
        full = {e["id"]: e for e in json.load(urllib.request.urlopen(req2, timeout=180))["elements"]}
        d["elements"] = [full.get(e["id"], e) if e["type"] == "relation" else e for e in d["elements"]]
    d["fetched"] = time.strftime("%Y-%m-%d %H:%M:%S")
    os.makedirs(WORK, exist_ok=True)
    json.dump(d, open(OSM_FILE, "w", encoding="utf-8"), ensure_ascii=False)
    print("osm: %d elements -> %s" % (len(d["elements"]), OSM_FILE))


class Inputs:
    def __init__(self):
        import pyogrio, shapely
        from pyproj import Transformer
        self.shapely = shapely
        t0 = time.time()
        shps = ["/vsizip/%s/%s" % (ZIP.replace("\\", "/"), m) for m in zipfile.ZipFile(ZIP).namelist() if m.lower().endswith(".shp")]
        tf = Transformer.from_crs("EPSG:4326", "EPSG:5186", always_xy=True)
        w, s, e, n = 999, 999, -999, -999
        for sp in SPECS:
            la, lo = sp["site"][:2]
            w, s, e, n = min(w, lo), min(s, la), max(e, lo), max(n, la)
        xs, ys = tf.transform([w - 0.01, e + 0.01], [s - 0.01, n + 0.01])
        import pandas as pd
        parts = [pyogrio.read_dataframe(p, encoding="cp949", columns=["A1", "A16", "A24", "A25"], bbox=(xs[0], ys[0], xs[1], ys[1])) for p in shps]
        self.gis = pd.concat(parts, ignore_index=True)
        self.to_geo = Transformer.from_crs("EPSG:5186", "EPSG:4326", always_xy=True)
        self.to_5186 = tf
        self.g = np.asarray(self.gis.geometry.values)
        self.uid = self.gis.A1.astype(str).values
        print("gis: %d footprints in the landmark box (%.0f s)" % (len(self.g), time.time() - t0), flush=True)
        self.osm = {}
        if os.path.isfile(OSM_FILE):
            for el in json.load(open(OSM_FILE, encoding="utf-8"))["elements"]:
                self.osm[(el["type"], el["id"])] = el

    def gis_poly(self, uid):
        """footprint of one GIS building (EPSG:5186 shapely polygon)."""
        i = np.flatnonzero(self.uid == uid)
        assert len(i) == 1, ("GIS uid not found / not unique", uid, len(i))
        g = self.shapely.make_valid(self.g[i[0]])
        return max(getattr(g, "geoms", [g]), key=lambda p: p.area) if g.geom_type != "Polygon" else g

    def osm_poly(self, kind, oid):
        el = self.osm.get((kind, oid))
        assert el is not None, ("OSM element missing - run --osm", kind, oid)
        rings = []
        if kind == "way":
            rings = [el["geometry"]]
        else:
            rings = join_ways([m["geometry"] for m in el.get("members", []) if m.get("role") == "outer" and m.get("geometry")])
        assert rings, ("OSM element without geometry", kind, oid)
        polys = []
        for r in rings:
            x, y = self.to_5186.transform([p["lon"] for p in r], [p["lat"] for p in r])
            if len(x) >= 4:
                polys.append(self.shapely.make_valid(self.shapely.Polygon(list(zip(x, y)))))
        u = self.shapely.union_all(polys)
        return max(getattr(u, "geoms", [u]), key=lambda p: p.area) if u.geom_type != "Polygon" else u

    def ll_poly(self, pts):
        x, y = self.to_5186.transform([p[1] for p in pts], [p[0] for p in pts])
        return self.shapely.Polygon(list(zip(x, y)))


def join_ways(segs):
    """multipolygon members (open way pieces) -> closed rings, by matching end points."""
    key = lambda p: (round(p["lat"], 7), round(p["lon"], 7))
    segs = [list(s) for s in segs]
    rings = []
    while segs:
        cur = segs.pop(0)
        changed = True
        while key(cur[0]) != key(cur[-1]) and changed:
            changed = False
            for i, s in enumerate(segs):
                if key(s[0]) == key(cur[-1]):
                    cur += s[1:]
                elif key(s[-1]) == key(cur[-1]):
                    cur += s[::-1][1:]
                elif key(s[-1]) == key(cur[0]):
                    cur = s + cur[1:]
                elif key(s[0]) == key(cur[0]):
                    cur = s[::-1] + cur[1:]
                else:
                    continue
                segs.pop(i)
                changed = True
                break
        rings.append(cur)
    return rings


# ------------------------------------------------------------------------------------------------------------ geometry
def ecef(lat, lon, h):
    la, lo = np.radians(lat), np.radians(lon)
    sl, cl = np.sin(la), np.cos(la)
    nn = A_WGS / np.sqrt(1 - E2 * sl * sl)
    return np.stack(((nn + h) * cl * np.cos(lo), (nn + h) * cl * np.sin(lo), (nn * (1 - E2) + h) * sl), axis=-1)


def enu_rot(lat, lon):
    la, lo = math.radians(lat), math.radians(lon)
    e = np.array([-math.sin(lo), math.cos(lo), 0.0])
    nn = np.array([-math.sin(la) * math.cos(lo), -math.sin(la) * math.sin(lo), math.cos(la)])
    u = np.array([math.cos(la) * math.cos(lo), math.cos(la) * math.sin(lo), math.sin(la)])
    return np.stack((e, nn, u), axis=1)


class Mesh:
    """triangles grouped by material name; positions in the landmark's local ENU (m)."""

    def __init__(self):
        self.g = {}

    def _grp(self, mat):
        return self.g.setdefault(mat, dict(P=[], N=[], UV=[], C=[], I=[], n=0))

    def tris(self, mat, P, N, UV, I, C=None):
        G = self._grp(mat)
        P = np.asarray(P, np.float64)
        G["P"].append(P)
        G["N"].append(np.asarray(N, np.float64))
        G["UV"].append(np.asarray(UV, np.float64))
        G["C"].append(np.ones((len(P), 4)) if C is None else np.broadcast_to(np.asarray(C, np.float64), (len(P), 4)))
        G["I"].append(np.asarray(I, np.int64).reshape(-1) + G["n"])
        G["n"] += len(P)

    def ntri(self):
        return sum(sum(len(i) for i in G["I"]) // 3 for G in self.g.values())


def densify(ring, step):
    """closed ring (N x 2, last != first) -> points every <= step m along the edges."""
    out = []
    for i in range(len(ring)):
        a, b = ring[i], ring[(i + 1) % len(ring)]
        k = max(1, int(math.ceil(np.hypot(*(b - a)) / step)))
        for t in range(k):
            out.append(a + (b - a) * t / k)
    return np.asarray(out)


def ring_xy(ring):
    a = np.asarray(ring.coords)[:-1, :2]
    return a


def wall(M, ring, z0, z1, mat, smooth_deg=40.0, u_off=0.0, color=None, both=False):
    """vertical walls along a closed ring (CCW = outward normals). z0 / z1 scalars or per-vertex arrays.
    UV: u = metres along the ring, v = height m (the material scales them to bays / floors)."""
    n = len(ring)
    z0 = np.broadcast_to(np.asarray(z0, np.float64), (n,))
    z1 = np.broadcast_to(np.asarray(z1, np.float64), (n,))
    d = np.roll(ring, -1, axis=0) - ring
    L = np.hypot(d[:, 0], d[:, 1])
    ok = L > 1e-6
    en = np.zeros((n, 2))
    en[ok] = np.stack((d[ok, 1], -d[ok, 0]), axis=1) / L[ok, None]
    # vertex normals: average with the previous edge if the turn is gentle (curved facades read smooth)
    prev = np.roll(en, 1, axis=0)
    cosang = np.sum(prev * en, axis=1)
    smooth = cosang > math.cos(math.radians(smooth_deg))
    vn_a = np.where(smooth[:, None], prev + en, en)                       # normal at the START vertex of edge i
    vn_a /= np.maximum(np.hypot(vn_a[:, 0], vn_a[:, 1]), 1e-9)[:, None]
    nxt = np.roll(vn_a, -1, axis=0)
    smooth_b = np.roll(smooth, -1)
    vn_b = np.where(smooth_b[:, None], nxt, en)                           # normal at the END vertex of edge i
    u = u_off + np.concatenate(([0.0], np.cumsum(L)[:-1]))
    P, N, UV, I = [], [], [], []
    k = 0
    for i in np.flatnonzero(ok):
        j = (i + 1) % n
        a, b = ring[i], ring[j]
        quad = [(a[0], a[1], z0[i]), (b[0], b[1], z0[j]), (b[0], b[1], z1[j]), (a[0], a[1], z1[i])]
        P += quad
        N += [(vn_a[i, 0], vn_a[i, 1], 0), (vn_b[i, 0], vn_b[i, 1], 0), (vn_b[i, 0], vn_b[i, 1], 0), (vn_a[i, 0], vn_a[i, 1], 0)]
        UV += [(u[i], z0[i]), (u[i] + L[i], z0[j]), (u[i] + L[i], z1[j]), (u[i], z1[i])]
        I += [k, k + 1, k + 2, k, k + 2, k + 3]
        k += 4
    if not P:
        return
    M.tris(mat, P, N, UV, I, color)
    if both:                                                             # back side (screens / fins seen from inside)
        P2 = np.asarray(P)
        N2 = -np.asarray(N, np.float64)
        I2 = np.asarray(I).reshape(-1, 3)[:, ::-1]
        M.tris(mat, P2, N2, UV, I2, color)


def cap(M, poly, zf, mat, up=True, uv_scale=1.0, color=None, cell=None):
    """flat or height-field cap over a shapely polygon (holes allowed). zf: scalar or f(x, y) -> z (then the polygon is
    cut into cell x cell pieces so the surface follows the function). Normals from the triangles (flat)."""
    import shapely, mapbox_earcut as earcut
    pieces = [poly]
    if cell and callable(zf):
        x0, y0, x1, y1 = poly.bounds
        pieces = []
        for xa in np.arange(x0, x1, cell):
            for ya in np.arange(y0, y1, cell):
                c = poly.intersection(shapely.box(xa, ya, xa + cell, ya + cell))
                pieces += [p for p in getattr(c, "geoms", [c]) if p.geom_type == "Polygon" and p.area > 0.01]
    for pc in pieces:
        pc = shapely.geometry.polygon.orient(pc, 1.0)
        rings = [np.asarray(pc.exterior.coords)[:-1, :2]] + [np.asarray(r.coords)[:-1, :2] for r in pc.interiors]
        verts = np.concatenate(rings)
        ends = np.cumsum([len(r) for r in rings]).astype(np.uint32)
        try:
            tri = np.asarray(earcut.triangulate_float64(verts, ends), np.int64).reshape(-1, 3)
        except Exception:
            continue
        if not len(tri):
            continue
        z = zf(verts[:, 0], verts[:, 1]) if callable(zf) else np.full(len(verts), float(zf))
        P = np.column_stack((verts, z))
        t = tri if up else tri[:, ::-1]
        v0, v1, v2 = P[t[:, 0]], P[t[:, 1]], P[t[:, 2]]
        fn = np.cross(v1 - v0, v2 - v0)
        flip = fn[:, 2] < 0 if up else fn[:, 2] > 0
        t[flip] = t[flip][:, ::-1]
        fn[flip] *= -1
        fn /= np.maximum(np.linalg.norm(fn, axis=1), 1e-9)[:, None]
        # unshared vertices so each triangle keeps its own (flat) normal
        PP = P[t.reshape(-1)]
        NN = np.repeat(fn, 3, axis=0)
        UV = PP[:, :2] * uv_scale
        M.tris(mat, PP, NN, UV, np.arange(len(PP)), color)


def prism(M, poly, z0, top, wall_mat, roof_mat, step=2.0, parapet=0.0, roof_cell=4.0, color=None):
    """extruded footprint: walls (densified so curved plans and sloped tops stay smooth) + roof. top: scalar or f(x, y)."""
    import shapely
    poly = shapely.geometry.polygon.orient(poly, 1.0)
    for r in [poly.exterior] + list(poly.interiors):
        ring = densify(ring_xy(r), step)
        zt = top(ring[:, 0], ring[:, 1]) if callable(top) else top
        wall(M, ring, z0, np.asarray(zt) + parapet, wall_mat, color=color)
        if parapet > 0:                                              # inner face of the parapet
            inner = ring[::-1]
            zti = zt[::-1] if callable(top) else zt
            wall(M, inner, np.asarray(zti), np.asarray(zti) + parapet, roof_mat, color=color)
    cap(M, poly, top, roof_mat, cell=roof_cell if callable(top) else None, uv_scale=0.25, color=color)


def lathe(M, prof, mat, segs=48, cx=0.0, cy=0.0, color=None, v_scale=1.0):
    """surface of revolution; prof = [(r, z), ...] bottom to top. Smooth normals around, faceted along the profile."""
    prof = np.asarray(prof, np.float64)
    ang = np.linspace(0, 2 * math.pi, segs + 1)
    P, N, UV, I = [], [], [], []
    k = 0
    for i in range(len(prof) - 1):
        (r0, z0), (r1, z1) = prof[i], prof[i + 1]
        dz, dr = z1 - z0, r1 - r0
        ln = math.hypot(dz, dr)
        if ln < 1e-9:
            continue
        nr, nz = dz / ln, -dr / ln                                   # outward profile normal (r, z)
        for j in range(segs):
            a, b = ang[j], ang[j + 1]
            ca, sa, cb, sb = math.cos(a), math.sin(a), math.cos(b), math.sin(b)
            P += [(cx + r0 * ca, cy + r0 * sa, z0), (cx + r0 * cb, cy + r0 * sb, z0), (cx + r1 * cb, cy + r1 * sb, z1), (cx + r1 * ca, cy + r1 * sa, z1)]
            N += [(nr * ca, nr * sa, nz), (nr * cb, nr * sb, nz), (nr * cb, nr * sb, nz), (nr * ca, nr * sa, nz)]
            u0, u1 = a / (2 * math.pi) * 2 * math.pi * max(r0, r1, 1.0), b / (2 * math.pi) * 2 * math.pi * max(r0, r1, 1.0)
            UV += [(u0, z0 * v_scale), (u1, z0 * v_scale), (u1, z1 * v_scale), (u0, z1 * v_scale)]
            I += [k, k + 1, k + 2, k, k + 2, k + 3]
            k += 4
    M.tris(mat, P, N, UV, I, color)


def ellipse(cx, cy, a, b, rot_deg=0.0, n=96):
    t = np.linspace(0, 2 * math.pi, n, endpoint=False)
    x, y = a * np.cos(t), b * np.sin(t)
    r = math.radians(rot_deg)
    return np.column_stack((cx + x * math.cos(r) - y * math.sin(r), cy + x * math.sin(r) + y * math.cos(r)))


def bowl(M, outer, inner, z_in, z_out, mat, rows=6, color=None):
    """sloped stand surface between two rings with the same vertex count (inner low, outer high), stepped in rows."""
    n = len(outer)
    P, N, UV, I = [], [], [], []
    k = 0
    for r in range(rows):
        t0, t1 = r / rows, (r + 1) / rows
        A = inner + (outer - inner) * t0
        B = inner + (outer - inner) * t1
        za, zb = z_in + (z_out - z_in) * t0, z_in + (z_out - z_in) * t1
        for i in range(n):
            j = (i + 1) % n
            q = [(A[i, 0], A[i, 1], za), (A[j, 0], A[j, 1], za), (B[j, 0], B[j, 1], zb), (B[i, 0], B[i, 1], zb)]
            v0, v1, v2 = np.array(q[0]), np.array(q[1]), np.array(q[2])
            fn = np.cross(v1 - v0, v2 - v0)
            if fn[2] < 0:
                order = [0, 2, 1, 0, 3, 2]
                fn = -fn
            else:
                order = [0, 1, 2, 0, 2, 3]
            fn /= max(np.linalg.norm(fn), 1e-9)
            P += q
            N += [tuple(fn)] * 4
            L = np.hypot(*(A[j] - A[i]))
            UV += [(i * L, t0 * 30), ((i + 1) * L, t0 * 30), ((i + 1) * L, t1 * 30), (i * L, t1 * 30)]
            I += [k + o for o in order]
            k += 4
    M.tris(mat, P, N, UV, I, color)


# ------------------------------------------------------------------------------------------------------------- textures
def tex_png(spec, size=256):
    """facade module texture (one image = nb bays x nf floors, repeated by the sampler) -> (base PNG, metallicRoughness PNG).
    spec keys: glass (rgb 0-1), frame (rgb), mull (px, vertical mullion width), band (px, floor spandrel height), band_rgb,
    var (pane brightness jitter), metal / rough for glass and frame, diag (diagrid line every n px), panel (plain wall: no glass)."""
    from PIL import Image
    rng = np.random.default_rng(abs(hash(json.dumps(spec, sort_keys=True))) % (1 << 31))
    nb, nf = spec.get("nb", 4), spec.get("nf", 4)
    H = W = size
    cw, ch = W // nb, H // nf
    glass = np.array(spec.get("glass", (0.4, 0.5, 0.6)))
    frame = np.array(spec.get("frame", (0.85, 0.86, 0.86)))
    band_rgb = np.array(spec.get("band_rgb", spec.get("frame", (0.85, 0.86, 0.86))))
    img = np.zeros((H, W, 3))
    mask = np.zeros((H, W))                                          # 1 = glass
    yy, xx = np.mgrid[0:H, 0:W]
    # glass panes with per-pane jitter + a soft vertical gradient (sky reflection reads lighter at the top of a pane)
    for fy in range(nf):
        for bx in range(nb):
            j = 1.0 + rng.uniform(-spec.get("var", 0.06), spec.get("var", 0.06))
            sl = (slice(fy * ch, (fy + 1) * ch), slice(bx * cw, (bx + 1) * cw))
            g = np.linspace(1.06, 0.94, ch)[:, None, None]
            img[sl] = glass * j * g
            mask[sl] = 1.0
    if spec.get("panel"):
        img[:] = glass * (1 + rng.uniform(-0.03, 0.03, (H, 1, 1)))
        mask[:] = 0
        win = spec.get("win")                                        # punched windows (w frac, h frac, rgb)
        if win:
            for fy in range(nf):
                for bx in range(nb):
                    x0, x1 = int(bx * cw + cw * (1 - win[0]) / 2), int(bx * cw + cw * (1 + win[0]) / 2)
                    y0, y1 = int(fy * ch + ch * 0.18), int(fy * ch + ch * (0.18 + win[1]))
                    img[y0:y1, x0:x1] = np.array(win[2]) * (1 + rng.uniform(-0.08, 0.08))
                    mask[y0:y1, x0:x1] = 1.0
    mw, bh = spec.get("mull", 3), spec.get("band", 6)
    if mw:
        sub = spec.get("sub", 1)                                     # extra thin mullions per bay
        for bx in range(nb * sub):
            x = int(bx * cw / sub)
            w = mw if bx % sub == 0 else max(1, mw // 2)
            img[:, x:x + w] = frame
            mask[:, x:x + w] = 0
    if bh:
        for fy in range(nf):
            y = fy * ch
            img[y:y + bh] = band_rgb
            mask[y:y + bh] = 0
    if spec.get("diag"):                                              # diagrid: two families of diagonal lines
        p, w = spec["diag"], spec.get("diag_w", 4)
        d1 = (xx + yy) % p < w
        d2 = (xx - yy) % p < w
        img[d1 | d2] = frame
        mask[d1 | d2] = 0
    if spec.get("hstripe"):                                           # horizontal bands (balcony slabs) every n px
        p, w = spec["hstripe"]
        s = (yy % p) < w
        img[s] = band_rgb
        mask[s] = 0
    img = np.clip(img, 0, 1)
    # metallicRoughness: G = roughness, B = metalness (glTF)
    mr = np.zeros((H, W, 3))
    mr[..., 1] = np.where(mask > 0.5, spec.get("rough", 0.12), spec.get("frame_rough", 0.55))
    mr[..., 2] = np.where(mask > 0.5, spec.get("metal", 0.5), spec.get("frame_metal", 0.1))
    srgb = np.where(img <= 0.0031308, img * 12.92, 1.055 * np.power(img, 1 / 2.4) - 0.055)   # spec colours are linear
    out = []
    for a in (srgb, mr):
        b = io.BytesIO()
        Image.fromarray(np.clip(np.round(a * 255), 0, 255).astype(np.uint8)).save(b, "PNG", optimize=True)
        out.append(b.getvalue())
    return out


# ------------------------------------------------------------------------------------------------------------- glb out
def glb_bytes(M, origin_ll, h_ell, mats_used):
    """Mesh (ENU at origin, z 0 = h_ell ellipsoidal) -> glb with one node matrix to ECEF (y-up like the building tiles)."""
    S = np.array([[1, 0, 0], [0, 0, 1], [0, -1, 0]], np.float64)               # ENU -> glTF y-up
    Z2Y = S
    R = enu_rot(*origin_ll)
    C0 = ecef(origin_ll[0], origin_ll[1], h_ell)
    Mx = np.eye(4)
    Mx[:3, :3] = Z2Y @ R @ S.T
    Mx[:3, 3] = Z2Y @ C0
    blob = bytearray()
    views, accs, prims, images, textures, materials = [], [], [], [], [], []

    def view(bb, target=None):
        blob.extend(b"\0" * ((-len(blob)) % 4))
        v = dict(buffer=0, byteOffset=len(blob), byteLength=len(bb))
        if target:
            v["target"] = target
        blob.extend(bb)
        views.append(v)
        return len(views) - 1
    texcache = {}
    for name in sorted(M.g):
        G = M.g[name]
        m = MATS[name]
        P = (np.concatenate(G["P"]) @ S.T).astype(np.float32)
        Nn = np.concatenate(G["N"]) @ S.T
        Nn = (Nn / np.maximum(np.linalg.norm(Nn, axis=1), 1e-9)[:, None]).astype(np.float32)
        UV = np.concatenate(G["UV"]).copy()
        UV[:, 0] /= m.get("u_m", 10.0)                              # metres -> texture repeats
        UV[:, 1] = -UV[:, 1] / m.get("v_m", 10.0)                   # v down the image = up the wall
        UV = UV.astype(np.float32)
        C = np.clip(np.round(np.concatenate(G["C"]) * 255), 0, 255).astype(np.uint8)
        I = np.concatenate(G["I"]).astype(np.uint32)
        a = len(accs)
        accs += [dict(bufferView=view(P.tobytes(), 34962), componentType=5126, count=len(P), type="VEC3", min=P.min(0).tolist(), max=P.max(0).tolist()),
                 dict(bufferView=view(Nn.tobytes(), 34962), componentType=5126, count=len(P), type="VEC3"),
                 dict(bufferView=view(C.tobytes(), 34962), componentType=5121, normalized=True, count=len(P), type="VEC4"),
                 dict(bufferView=view(UV.tobytes(), 34962), componentType=5126, count=len(P), type="VEC2"),
                 dict(bufferView=view(I.tobytes(), 34963), componentType=5125, count=len(I), type="SCALAR")]
        if name not in texcache:
            base, mr = tex_png(m["tex"], m.get("size", 256))
            ib = len(images)
            images += [dict(bufferView=view(base), mimeType="image/png"), dict(bufferView=view(mr), mimeType="image/png")]
            textures += [dict(source=ib, sampler=0), dict(source=ib + 1, sampler=0)]
            mi = len(materials)
            mat = dict(name=name, pbrMetallicRoughness=dict(baseColorTexture=dict(index=len(textures) - 2), metallicFactor=1.0, roughnessFactor=1.0,
                                                            metallicRoughnessTexture=dict(index=len(textures) - 1)))
            if m.get("double"):
                mat["doubleSided"] = True
            materials.append(mat)
            texcache[name] = mi
        prims.append(dict(attributes=dict(POSITION=a, NORMAL=a + 1, COLOR_0=a + 2, TEXCOORD_0=a + 3), indices=a + 4, material=texcache[name], mode=4))
        mats_used.add(name)
    blob.extend(b"\0" * ((-len(blob)) % 4))
    gl = dict(asset=dict(version="2.0", generator="gyro-sim-chair sim/landmarks/landmarks_build.py"), scene=0, scenes=[dict(nodes=[0])],
              nodes=[dict(mesh=0, matrix=[float(v) for v in Mx.T.reshape(-1)])], meshes=[dict(primitives=prims)],
              samplers=[dict(magFilter=9729, minFilter=9987, wrapS=10497, wrapT=10497)],
              images=images, textures=textures, materials=materials, accessors=accs, bufferViews=views, buffers=[dict(byteLength=len(blob))])
    js = json.dumps(gl, separators=(",", ":")).encode()
    js += b" " * ((-len(js)) % 4)
    total = 12 + 8 + len(js) + 8 + len(blob)
    return struct.pack("<III", 0x46546C67, 2, total) + struct.pack("<II", len(js), 0x4E4F534A) + js + struct.pack("<II", len(blob), 0x004E4942) + bytes(blob)


# -------------------------------------------------------------------------------------------------------------- preview
def preview(M, path, title):
    """quick shape check without Unreal (matplotlib, flat lambert shading, material base colour): two oblique views."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from mpl_toolkits.mplot3d.art3d import Poly3DCollection
    fig = plt.figure(figsize=(12, 7), dpi=90)
    sun = np.array([0.4, -0.5, 0.75])
    sun /= np.linalg.norm(sun)
    allP = np.concatenate([np.concatenate(G["P"]) for G in M.g.values()])
    lo, hi = allP.min(0), allP.max(0)
    span = (hi - lo).max()
    for k, (el, az) in enumerate(((18, -60), (18, 120))):
        ax = fig.add_subplot(1, 2, k + 1, projection="3d")
        for name, G in M.g.items():
            P = np.concatenate(G["P"])
            I = np.concatenate(G["I"]).reshape(-1, 3)
            T = P[I]
            n = np.cross(T[:, 1] - T[:, 0], T[:, 2] - T[:, 0])
            n /= np.maximum(np.linalg.norm(n, axis=1), 1e-9)[:, None]
            base = np.array(MATS[name]["tex"].get("glass", (0.6, 0.6, 0.6)))
            sh = 0.35 + 0.65 * np.clip(n @ sun, 0, 1)
            col = np.clip(base[None] ** (1 / 2.2) * sh[:, None], 0, 1)
            ax.add_collection3d(Poly3DCollection(T, facecolors=col, edgecolors="none"))
        c = (lo + hi) / 2
        ax.set_xlim(c[0] - span / 2, c[0] + span / 2); ax.set_ylim(c[1] - span / 2, c[1] + span / 2); ax.set_zlim(0, span)
        ax.view_init(el, az)
        ax.set_box_aspect((1, 1, 1))
        ax.set_title("%s  az %d" % (title, az), fontsize=9)
    fig.savefig(path)
    plt.close(fig)


# ---------------------------------------------------------------------------------------------------------------- build
class Ctx:
    """per-landmark helpers handed to the spec's build function: footprints in local metres, the mesh, the heights."""

    def __init__(self, inp, spec):
        import shapely
        self.inp, self.spec, self.shapely = inp, spec, shapely
        self.M = Mesh()
        self.feet = []                                                # 5186 footprints that this model replaces (for exclude)
        src = []
        for f in spec["foot"]:
            src.append(self.src_poly(f))
        u = shapely.union_all(src)
        c = u.centroid
        lo, la = inp.to_geo.transform(c.x, c.y)
        self.origin = (la, lo)
        self.R = enu_rot(la, lo)
        self.C0 = ecef(la, lo, 0.0)
        self.foot5186 = u

    def src_poly(self, f):
        kind, val = f.split(":", 1)
        if kind == "gis":
            return self.inp.gis_poly(val)
        if kind in ("way", "relation"):
            return self.inp.osm_poly(kind, int(val))
        if kind == "ellipse":                                          # digitised from the local V-World photo: lat,lon,a_east,b_north,rot
            la, lo, a, b, rot = (float(v) for v in val.split(","))
            pts = ellipse(0, 0, a, b, rot, 72)
            lat = la + pts[:, 1] / 110950.0
            lon = lo + pts[:, 0] / (111320.0 * math.cos(math.radians(la)))
            return self.inp.ll_poly(list(zip(lat, lon)))
        raise ValueError(f)

    def local(self, p5186):
        """EPSG:5186 polygon -> local ENU shapely polygon (exact via ECEF)."""
        def tr(coords):
            c = np.asarray(coords)
            lo, la = self.inp.to_geo.transform(c[:, 0], c[:, 1])
            X = ecef(np.asarray(la), np.asarray(lo), 0.0) - self.C0
            E = X @ self.R
            return E[:, :2]
        return self.shapely.Polygon(tr(p5186.exterior.coords), [tr(r.coords) for r in p5186.interiors])

    def foot(self, f, simplify=0.3):
        p = self.local(self.src_poly(f))
        return p.simplify(simplify, preserve_topology=True) if simplify else p

    def ll(self, lat, lon):
        X = ecef(np.asarray([lat]), np.asarray([lon]), 0.0) - self.C0
        E = X @ self.R
        return float(E[0, 0]), float(E[0, 1])

    def to_ll(self, x, y):
        """local metres -> lat / lon (for the ground sampling)."""
        X = self.C0 + np.stack((x, y, np.zeros_like(x)), axis=-1) @ self.R.T
        p = np.sqrt(X[..., 0] ** 2 + X[..., 1] ** 2)
        lon = np.degrees(np.arctan2(X[..., 1], X[..., 0]))
        lat = np.degrees(np.arctan2(X[..., 2], p * (1 - E2)))
        return lat, lon


def build(args):
    import shapely
    import buildings_build as BB
    import terrain_dem as T
    only = set(args[args.index("--only") + 1].split(",")) if "--only" in args else None
    inp = Inputs()
    dem = T.Dem()
    os.makedirs(TILES, exist_ok=True)
    children, report, excl = [], [], {}
    t0 = time.time()
    for spec in SPECS:
        key = spec["key"]
        cx = Ctx(inp, spec)
        # replaced GIS buildings: listed ones + every GIS footprint mostly (>= 40 %) inside the model's footprint
        ids = set(spec.get("exclude", [])) | {f[4:] for f in spec["foot"] if f.startswith("gis:")}
        cover = cx.foot5186.buffer(1.0)
        cand = np.flatnonzero(shapely.intersects(inp.g, cover))
        for i in cand:
            gi = shapely.make_valid(inp.g[i])
            if gi.area > 0 and gi.intersection(cover).area >= 0.4 * gi.area:
                ids.add(inp.uid[i])
        for u in ids:
            excl.setdefault(u, key)
        if only and key not in only:
            continue
        spec["build"](cx)                                            # fills cx.M (local metres, z from the ground)
        if "--preview" in args:
            preview(cx.M, os.path.join(WORK, "preview_%s.png" % key), spec["name"])
        # ground: lowest rendered-terrain point on the footprint (same rule as buildings_build.py) - 0.3 m
        fl = cx.local(cx.foot5186)
        ring = densify(ring_xy(fl.exterior), 8.0)
        la, lo = cx.to_ll(ring[:, 0], ring[:, 1])
        cla, clo = cx.origin
        hmesh = BB.mesh_height(dem, np.append(la, cla), np.append(lo, clo))
        base_msl = float(hmesh.min()) - 0.3 + spec.get("base_dz", 0.0)
        geoid = float(dem.geoid_n(np.array([cla]), np.array([clo]))[0])
        h_ell = base_msl + geoid
        used = set()
        glb = glb_bytes(cx.M, cx.origin, h_ell, used)
        fn = "%s.glb" % key
        with open(os.path.join(TILES, fn + ".tmp"), "wb") as f:
            f.write(glb)
        os.replace(os.path.join(TILES, fn + ".tmp"), os.path.join(TILES, fn))
        P = np.concatenate([np.concatenate(G["P"]) for G in cx.M.g.values()])
        r = float(np.hypot(P[:, 0], P[:, 1]).max()) + 5.0
        dlat, dlon = r / 111320.0, r / (111320.0 * math.cos(math.radians(cla)))
        region = [math.radians(clo - dlon), math.radians(cla - dlat), math.radians(clo + dlon), math.radians(cla + dlat),
                  h_ell + float(P[:, 2].min()) - 2.0, h_ell + float(P[:, 2].max()) + 2.0]
        children.append(dict(boundingVolume=dict(region=region), geometricError=0.0, content=dict(uri=fn)))
        report.append(dict(key=key, name=spec["name"], lat=round(cla, 6), lon=round(clo, 6), ground_msl=round(base_msl, 2), geoid=round(geoid, 2),
                           top_m=round(float(P[:, 2].max()), 1), triangles=cx.M.ntri(), glb_kb=round(len(glb) / 1024), mats=sorted(used),
                           method=spec.get("method", "parametric"), foot=spec["foot"], replaced=sorted(u for u, k in excl.items() if k == key)))
        print("%-16s %-28s top %6.1f m  ground %6.1f m  %6d tris  %5d KB  replaces %d GIS" % (key, spec["name"][:28], P[:, 2].max(), base_msl,
              cx.M.ntri(), len(glb) // 1024, len(report[-1]["replaced"])), flush=True)
    # tileset: root (no content) -> one leaf per landmark; ADD so every landmark loads with the root (big geometric error)
    if children:
        w = min(c["boundingVolume"]["region"][0] for c in children)
        s = min(c["boundingVolume"]["region"][1] for c in children)
        e = max(c["boundingVolume"]["region"][2] for c in children)
        n = max(c["boundingVolume"]["region"][3] for c in children)
        lo_ = min(c["boundingVolume"]["region"][4] for c in children)
        hi_ = max(c["boundingVolume"]["region"][5] for c in children)
        prev = {}
        tp = os.path.join(TILES, "tileset.json")
        if only and os.path.isfile(tp):                                # partial build: keep the other leaves
            for c in json.load(open(tp, encoding="utf-8"))["root"].get("children", []):
                prev[c["content"]["uri"]] = c
        for c in children:
            prev[c["content"]["uri"]] = c
        kids = list(prev.values())
        w = min(c["boundingVolume"]["region"][0] for c in kids)
        s = min(c["boundingVolume"]["region"][1] for c in kids)
        e = max(c["boundingVolume"]["region"][2] for c in kids)
        n = max(c["boundingVolume"]["region"][3] for c in kids)
        lo_ = min(c["boundingVolume"]["region"][4] for c in kids)
        hi_ = max(c["boundingVolume"]["region"][5] for c in kids)
        ts = dict(asset=dict(version="1.1", generator="sim/landmarks/landmarks_build.py", built=time.strftime("%Y-%m-%d %H:%M:%S"),
                             copyright="Landmark models: gyro-sim-chair (footprints: 국토교통부 GIS건물통합정보 CC BY / © OpenStreetMap contributors ODbL)"),
                  geometricError=6000.0,
                  root=dict(boundingVolume=dict(region=[w, s, e, n, lo_, hi_]), geometricError=6000.0, refine="ADD", children=kids))
        with open(tp + ".tmp", "w", encoding="utf-8") as f:
            json.dump(ts, f, indent=1)
        os.replace(tp + ".tmp", tp)
        rp = os.path.join(ROOT, "build_report.json")
        old = {}
        if only and os.path.isfile(rp):
            old = {r["key"]: r for r in json.load(open(rp, encoding="utf-8")).get("landmarks", [])}
        for r in report:
            old[r["key"]] = r
        json.dump(dict(built=time.strftime("%Y-%m-%d %H:%M:%S"), inputs=dict(gis=ZIP, osm=OSM_FILE), landmarks=list(old.values())),
                  open(rp, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    # exclude list: written for ALL specs (even with --only), JSON list of GIS uids (field A1)
    ids = sorted(excl)
    meta = dict(note="GIS건물통합정보 uids (field A1) replaced by landmark models; sim/buildings_build.py --tiles skips them",
                built=time.strftime("%Y-%m-%d %H:%M:%S"), count=len(ids),
                by_landmark={k: sorted(u for u, kk in excl.items() if kk == k) for k in sorted(set(excl.values()))}, ids=ids)
    for p in (EXCLUDE, EXCLUDE_TRACKED):
        with open(p + ".tmp", "w", encoding="utf-8") as f:
            json.dump(meta, f, indent=1, ensure_ascii=False)
        os.replace(p + ".tmp", p)
    print("exclude: %d GIS uids -> %s (+ %s); %.0f s" % (len(ids), EXCLUDE, EXCLUDE_TRACKED, time.time() - t0))


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    a = sys.argv[1:]
    if "--osm" in a:
        osm_fetch()
    if "--build" in a:
        build(a)
    if not a:
        print(__doc__)
