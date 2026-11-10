"""3D bridges and elevated roads over Busan for the Unreal 'vworld' ground mode, from OpenStreetMap (ODbL).
The V-World photo paints every road flat on the terrain; this builds the structures that stand above it: bridge /
viaduct decks with parapets, piers down to the ground or the sea bed, and towers + cables of the big cable bridges
(광안대교 suspension, 부산항대교 / 거가대교 / 대동화명대교 / 낙동강대교 cable-stayed). Output = 3D Tiles 1.1 (glb), loaded at
Play by unreal/GyroSim/Content/Python/roads_look.py from file:///C:/GyroSimTiles/roads/tiles/tileset.json.

    python -I sim/roads_build.py --fetch      Overpass API, one request (~40 s, ~11 MB) -> C:\\GyroSimTiles\\osm\\busan_roads.json
    python -I sim/roads_build.py --tiles      -> C:\\GyroSimTiles\\roads\\tiles\\tileset.json + a|b\\*.glb, build.json, groups.json
    python -I sim/roads_build.py --attrib     on-screen credit plate sim/vworld_roads_attribution.png (+ © OpenStreetMap contributors)

Data: OSM ways with highway=* in the Busan box and (bridge=* | layer>=1 | tunnel=*), plus every highway way that shares a
node with them (= where a bridge meets the ground). Cached outside git (C:\\GyroSimTiles\\osm, manifest json: time, query, URL).
Overpass usage policy: one request per run, only with --fetch; the tiles step reads the cache.

Heights (no deck heights in OSM here; Copernicus DEM has the sea flattened to 0 and is only a 30 m surface model):
  - ground anchors: bridge nodes shared with a non-bridge road or a tunnel, and dangling ends = the rendered terrain mesh
    (buildings_build.mesh_height) + 0.15 m.
  - wanted height = lowest mesh around the node + clearance (layer x 6.5 m; over water and longer than 100 m >= 11 m), or the
    deck height of a named big bridge (BIG table, 추정 from public figures).
  - grades: the deck can not rise / fall faster than 5 % from an anchor (cone up), and must stay within 4.5 % of a big-bridge
    deck (cone down); wanted height clamped to both, then smoothed along the road graph (anchors fixed).
Width: lanes x 3.5 m + shoulders (motorway / trunk 3 m, others 1 m), 'width' tag if present, class defaults (가정) otherwise.
Piers: every 30 m (40 m major roads, 60 m long water crossings), where the deck bottom is > 1.5 m above the ground; down to
the mesh - 2 m on land, -15 m MSL in water. None inside the cable-supported spans (towers there).
Run with `python -I` (the input is a download): user site-packages are added back below; no code is read from the data folder.
"""
import json, math, os, sys, time, heapq, io, site
if sys.flags.isolated:
    site.addsitedir(site.getusersitepackages())
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import numpy as np                                        # noqa: E402

OSM_DIR = os.environ.get("GYROSIM_OSM", r"C:\GyroSimTiles\osm")
OSM_FILE = os.path.join(OSM_DIR, "busan_roads.json")
ROOT = os.environ.get("GYROSIM_ROADS", r"C:\GyroSimTiles\roads")
TILES = os.environ.get("GYROSIM_ROADS_TILES", os.path.join(ROOT, "tiles"))
BOX = (34.96, 128.75, 35.40, 129.33)                      # S W N E = terrain_dem.HIRES busan box
ATTRIB = "도로·다리: © OpenStreetMap contributors (ODbL)"
ATTRIB_PNG = os.path.join(HERE, "vworld_roads_attribution.png")
OVERPASS = "https://overpass-api.de/api/interpreter"
UA = "gyro-sim-chair roads_build.py (personal flight sim; one request per manual run)"

MOTOR = {"motorway", "trunk", "primary", "secondary", "tertiary", "unclassified", "residential", "service", "living_street",
         "road", "busway", "motorway_link", "trunk_link", "primary_link", "secondary_link", "tertiary_link"}
MAJOR = {"motorway", "trunk", "primary", "motorway_link", "trunk_link", "primary_link"}
LAYER_ONLY = {"motorway", "trunk", "primary", "secondary", "tertiary", "motorway_link", "trunk_link", "primary_link", "secondary_link", "tertiary_link"}
BRIDGE_OK = {"yes", "viaduct", "cantilever", "trestle", "suspension", "movable", "beam", "arch", "cable-stayed"}
# lanes per way when the tag is missing (가정): (oneway, two-way)
LANES_DEF = dict(motorway=(2, 4), trunk=(2, 4), primary=(2, 4), secondary=(2, 2), tertiary=(1, 2), motorway_link=(1, 2),
                 trunk_link=(1, 2), primary_link=(1, 2), secondary_link=(1, 2), tertiary_link=(1, 2))
LANE_M = 3.5
GRADE, GRADE_BIG = 0.05, 0.045
CLEAR_LAYER, CLEAR_WATER = 6.5, 11.0
STEP = 20.0                                               # m, densified graph spacing
PARAPET_H, PARAPET_T = 1.0, 0.35
# big bridges (추정 from public figures, see docs/vworld-integration.md 6-4): deck top m MSL (by layer), cable type, tower
# positions as fractions of the longest tagged cable segment, tower top m MSL (None = deck + 0.25 x main span)
BIG = {
    "광안대교": dict(deck={2: 46.0, 1: 39.0}, kind="suspension", towers=(0.2195, 0.7805), top=116.0, color=(0.62, 0.62, 0.60)),
    "부산항대교접속고가교": dict(deck={None: 65.0}, kind="cable-stayed", towers=(0.235, 0.765), top=190.0, color=(0.74, 0.74, 0.72)),
    "거가대교": dict(deck={None: 45.0}, kind="cable-stayed", towers=(0.18, 0.82), top=None, color=(0.70, 0.70, 0.68)),
    "대동화명대교": dict(deck={None: 25.0}, kind="cable-stayed", towers=(0.25, 0.75), top=None, color=(0.72, 0.72, 0.70)),
    "낙동강대교": dict(deck={None: 25.0}, kind="cable-stayed", towers=(0.25, 0.75), top=None, color=(0.72, 0.72, 0.70)),
}
# colours (glTF COLOR_0 is linear)
C_CONC = (0.40, 0.40, 0.385)
C_PARA = (0.50, 0.50, 0.485)
C_PIER = (0.36, 0.36, 0.35)
C_CABLE = (0.30, 0.31, 0.32)
LAT0, LON0 = 35.15, 129.05
KX, KY = 111320.0 * math.cos(math.radians(LAT0)), 110574.0
STEP_A = (0.072, 0.09)                                    # = buildings_build tiles (8 km), B = 1/4 (2 km)
GE = dict(root=1000.0, a=40.0, b=0.0)


def xy(lat, lon):
    return (np.asarray(lon) - LON0) * KX, (np.asarray(lat) - LAT0) * KY


def latlon(x, y):
    return LAT0 + np.asarray(y) / KY, LON0 + np.asarray(x) / KX


# ---- fetch ----------------------------------------------------------------------------------------------------------
def query():
    s, w, n, e = BOX
    bb = "(%g,%g,%g,%g)" % (s, w, n, e)
    return ("[out:json][timeout:300];\n(\n way[\"highway\"][\"bridge\"][\"bridge\"!=\"no\"]%s;\n way[\"highway\"][\"layer\"~\"^[1-9]\"]%s;\n"
            " way[\"highway\"][\"tunnel\"][\"tunnel\"!=\"no\"]%s;\n)->.br;\nnode(w.br)->.n;\nway(bn.n)[\"highway\"]->.adj;\n(.br;.adj;);\n"
            "out body;\n>;\nout skel qt;\n") % (bb, bb, bb)


def fetch():
    import urllib.request, urllib.parse
    os.makedirs(OSM_DIR, exist_ok=True)
    q = query()
    t0 = time.time()
    req = urllib.request.Request(OVERPASS, data=urllib.parse.urlencode({"data": q}).encode(), headers={"User-Agent": UA})
    b = urllib.request.urlopen(req, timeout=400).read()
    d = json.loads(b)                                     # must parse before it replaces the cache
    tmp = OSM_FILE + ".part"
    with open(tmp, "wb") as f:
        f.write(b)
    os.replace(tmp, OSM_FILE)
    man = dict(made=time.strftime("%Y-%m-%d %H:%M:%S"), url=OVERPASS, query=q, bytes=len(b), seconds=round(time.time() - t0, 1),
               osm_base=d.get("osm3s", {}).get("timestamp_osm_base"), licence="ODbL, © OpenStreetMap contributors", elements=len(d["elements"]))
    with open(OSM_FILE[:-5] + "_manifest.json", "w", encoding="utf-8") as f:
        json.dump(man, f, indent=1, ensure_ascii=False)
    print("fetched %d elements, %.1f MB, %.0f s -> %s" % (man["elements"], len(b) / 1e6, man["seconds"], OSM_FILE))


# ---- parse ----------------------------------------------------------------------------------------------------------
def _int(v, d=None):
    try:
        return int(str(v).split(";")[0].strip())
    except (TypeError, ValueError):
        return d


def _float(v):
    try:
        return float(str(v).replace("m", "").split(";")[0].strip())
    except (TypeError, ValueError):
        return None


def load():
    d = json.load(open(OSM_FILE, encoding="utf-8"))
    nodes = {e["id"]: (e["lat"], e["lon"]) for e in d["elements"] if e["type"] == "node"}
    ways = [e for e in d["elements"] if e["type"] == "way" and len(e.get("nodes", ())) >= 2]
    elev, ground = [], []
    for w in ways:
        t = w.get("tags", {})
        hw = t.get("highway", "")
        if any(n not in nodes for n in w["nodes"]):
            continue
        tunnel = t.get("tunnel", "no") not in ("no", "")
        br = t.get("bridge", "no")
        lay = _int(t.get("layer"), 0)
        name = t.get("bridge:name") or t.get("name") or ""
        if hw in MOTOR and not tunnel and "예정" not in name and t.get("construction") is None and (
                br in BRIDGE_OK or (br == "no" and lay >= 1 and hw in LAYER_ONLY and t.get("covered", "no") == "no" and t.get("indoor", "no") == "no")):
            elev.append(w)
        elif hw in MOTOR or tunnel:
            ground.append(w)
    return nodes, elev, ground, d.get("osm3s", {}).get("timestamp_osm_base")


def way_width(t):
    hw = t.get("highway", "")
    wd = _float(t.get("width"))
    if wd and 3.0 <= wd <= 40.0:
        return wd + 2 * PARAPET_T, None
    oneway = t.get("oneway", "no") in ("yes", "1", "-1") or hw in ("motorway", "motorway_link")
    lanes = _int(t.get("lanes"))
    if lanes is None or not 1 <= lanes <= 10:
        lanes = LANES_DEF.get(hw, (1, 2))[0 if oneway else 1]
        if hw in ("residential", "service", "unclassified", "living_street", "road", "busway") and not oneway:
            return 2 * 3.0 + 1.0 + 2 * PARAPET_T, 2
    sh = 3.0 if hw in ("motorway", "trunk") else 1.0
    return lanes * LANE_M + sh + 2 * PARAPET_T, lanes


def big_key(t):
    """the BIG entry of a cable-supported segment (bridge:structure suspension / cable-stayed) by its name, else None."""
    if t.get("bridge:structure") not in ("suspension", "cable-stayed"):
        return None
    nm = t.get("bridge:name") or t.get("name") or ""
    return nm if nm in BIG else None


# ---- heights ----------------------------------------------------------------------------------------------------------
class Graph:
    """densified bridge graph: point i = (x, y), ways = lists of point indices."""

    def __init__(self, nodes, elev, ground):
        self.pid, self.px, self.py, self.osm = {}, [], [], []
        self.ways = []
        gnodes = set()
        for w in ground:
            gnodes.update(w["nodes"])
        self.gnodes = gnodes

        def pt(key, x, y):
            if key in self.pid:
                return self.pid[key]
            self.pid[key] = len(self.px)
            self.px.append(x)
            self.py.append(y)
            self.osm.append(key if isinstance(key, int) else None)
            return self.pid[key]
        for w in elev:
            la = np.array([nodes[n][0] for n in w["nodes"]])
            lo = np.array([nodes[n][1] for n in w["nodes"]])
            X, Y = xy(la, lo)
            idx = [pt(w["nodes"][0], X[0], Y[0])]
            for k in range(1, len(X)):
                L = math.hypot(X[k] - X[k - 1], Y[k] - Y[k - 1])
                m = max(1, int(math.ceil(L / STEP)))
                for j in range(1, m):
                    f = j / m
                    a, b = w["nodes"][k - 1], w["nodes"][k]
                    key = ("s", min(a, b), max(a, b), j if a < b else m - j, m)
                    idx.append(pt(key, X[k - 1] + (X[k] - X[k - 1]) * f, Y[k - 1] + (Y[k] - Y[k - 1]) * f))
                idx.append(pt(w["nodes"][k], X[k], Y[k]))
            self.ways.append(dict(w=w, idx=idx))
        self.px, self.py = np.array(self.px), np.array(self.py)
        n = len(self.px)
        self.adj = [[] for _ in range(n)]
        for wd in self.ways:
            ii = wd["idx"]
            for a, b in zip(ii, ii[1:]):
                if a != b:
                    L = math.hypot(self.px[a] - self.px[b], self.py[a] - self.py[b])
                    self.adj[a].append((b, L))
                    self.adj[b].append((a, L))


def cone(G, src, grade, up=True):
    """min over sources of (h_s + grade d) (up) or max of (h_s - grade d), d = graph distance."""
    n = len(G.px)
    best = np.full(n, np.inf)
    hq = []
    for i, h in src.items():
        v = h if up else -h
        if v < best[i]:
            best[i] = v
            heapq.heappush(hq, (v, i))
    while hq:
        v, i = heapq.heappop(hq)
        if v > best[i]:
            continue
        for j, L in G.adj[i]:
            nv = v + grade * L
            if nv < best[j]:
                best[j] = nv
                heapq.heappush(hq, (nv, j))
    return best if up else -best


def solve_heights(G, dem, mesh_height):
    n = len(G.px)
    lat, lon = latlon(G.px, G.py)
    mesh = mesh_height(dem, lat, lon)
    # lowest mesh in a +-12 m cross around the point (DSM bumps from the viaduct itself / buildings)
    low = mesh.copy()
    for dx, dy in ((12, 0), (-12, 0), (0, 12), (0, -12), (8, 8), (-8, -8), (8, -8), (-8, 8)):
        la2, lo2 = latlon(G.px + dx, G.py + dy)
        low = np.minimum(low, mesh_height(dem, la2, lo2))
    water = mesh <= 0.3
    want = np.full(n, -np.inf)
    bigdeck = {}
    deg = np.array([len(a) for a in G.adj])
    for wd in G.ways:
        t = wd["w"].get("tags", {})
        ii = np.array(wd["idx"])
        L = float(np.hypot(np.diff(G.px[ii]), np.diff(G.py[ii])).sum())
        lay = max(1, _int(t.get("layer"), 1))
        c = CLEAR_LAYER * lay
        if L > 100 and water[ii].mean() > 0.3:
            c = max(c, CLEAR_WATER + CLEAR_LAYER * (lay - 1))
        want[ii] = np.maximum(want[ii], low[ii] + c)
        k = big_key(t)
        wd["big"] = k
        if k and k in BIG:
            dk = BIG[k]["deck"]
            h = dk.get(lay, dk.get(None, max(dk.values())))
            for i in ii:
                bigdeck[int(i)] = h
    anchors = {}
    for i in range(n):
        o = G.osm[i]
        if (o is not None and o in G.gnodes) or deg[i] == 1:
            anchors[i] = float(mesh[i]) + 0.15
    for i in list(anchors):
        if i in bigdeck:                                  # a big-bridge node is never pinned to the ground
            anchors.pop(i)
    up = cone(G, anchors, GRADE, True) if anchors else np.full(n, np.inf)
    dn = cone(G, bigdeck, GRADE_BIG, False) if bigdeck else np.full(n, -np.inf)
    for i, h in bigdeck.items():
        want[i] = h
    h = np.minimum(want, up)
    h = np.maximum(h, dn)
    h = np.where(np.isfinite(h), h, mesh + 6.5)
    fixed = np.zeros(n, bool)
    for i in anchors:
        h[i] = anchors[i]
        fixed[i] = True
    # smoothing (Jacobi, neighbours weighted equally), anchors fixed, cones kept
    nb_i = np.concatenate([[i] * len(a) for i, a in enumerate(G.adj)]).astype(np.int64) if n else np.zeros(0, np.int64)
    nb_j = np.concatenate([[j for j, _ in a] for a in G.adj]).astype(np.int64) if n else np.zeros(0, np.int64)
    cnt = np.bincount(nb_i, minlength=n).astype(float)
    for _ in range(60):
        s = np.bincount(nb_i, weights=h[nb_j], minlength=n)
        avg = np.where(cnt > 0, s / np.maximum(cnt, 1), h)
        hn = 0.5 * h + 0.5 * avg
        hn = np.maximum(np.minimum(hn, up), dn)
        h = np.where(fixed, h, hn)
    h = np.maximum(h, mesh + 0.15)
    return h, mesh, low, water, anchors


# ---- mesh building ----------------------------------------------------------------------------------------------------
class Mesh:
    """quads in the planar frame (x, y m, z m MSL), per material: 0 asphalt, 1 concrete."""

    def __init__(self):
        self.q = {0: [], 1: []}

    def quad(self, mat, P, color, uv, hint):
        P = np.asarray(P, float)
        nrm = np.cross(P[1] - P[0], P[2] - P[0])
        if np.dot(nrm, hint) < 0:
            P = P[[0, 3, 2, 1]]
            uv = [uv[0], uv[3], uv[2], uv[1]]
        self.q[mat].append((P, color, np.asarray(uv, float)))

    def box(self, c, ax_u, ax_v, hu, hv, z0, z1, color, faces="all"):
        """vertical box: centre (x, y), unit horizontal axes u, v, half sizes, z range."""
        c, u, v = np.asarray(c, float), np.asarray(ax_u, float), np.asarray(ax_v, float)
        corners = [c + su * hu * u + sv * hv * v for su, sv in ((-1, -1), (1, -1), (1, 1), (-1, 1))]
        for k in range(4):
            a, b = corners[k], corners[(k + 1) % 4]
            out = (a + b) / 2 - c
            L = float(np.hypot(*(b - a)))
            P = [(a[0], a[1], z0), (b[0], b[1], z0), (b[0], b[1], z1), (a[0], a[1], z1)]
            self.quad(1, P, color, [(0, z0 / 4), (L / 4, z0 / 4), (L / 4, z1 / 4), (0, z1 / 4)], (out[0], out[1], 0))
        if faces == "all":
            for z, s in ((z1, 1), (z0, -1)):
                P = [(p[0], p[1], z) for p in corners]
                self.quad(1, P, color, [(0, 0), (hu / 2, 0), (hu / 2, hv / 2), (0, hv / 2)], (0, 0, s))

    def beam(self, p0, p1, s, color):
        """square beam (cable, stay, hanger) between two 3D points, side s."""
        p0, p1 = np.asarray(p0, float), np.asarray(p1, float)
        d = p1 - p0
        L = float(np.linalg.norm(d))
        if L < 0.05:
            return
        d /= L
        a = np.cross(d, (0, 0, 1.0))
        if np.linalg.norm(a) < 1e-3:
            a = np.array([1.0, 0, 0])
        a /= np.linalg.norm(a)
        b = np.cross(a, d)
        h = s / 2
        ring = [h * a + h * b, -h * a + h * b, -h * a - h * b, h * a - h * b]
        for k in range(4):
            r0, r1 = ring[k], ring[(k + 1) % 4]
            out = (r0 + r1) / 2
            self.quad(1, [p0 + r0, p0 + r1, p1 + r1, p1 + r0], color, [(0, 0), (s, 0), (s, L / 4), (0, L / 4)], out)


def sweep(M, X, Y, Z, w, depth, lanes, girder):
    """deck + parapets along a polyline: cross-section polygon swept between stations."""
    n = len(X)
    P = np.stack((X, Y), 1)
    tng = np.zeros((n, 2))
    tng[1:] += P[1:] - P[:-1]
    tng[:-1] += P[1:] - P[:-1]
    tng /= np.maximum(np.linalg.norm(tng, axis=1, keepdims=True), 1e-9)
    nrm = np.stack((-tng[:, 1], tng[:, 0]), 1)                   # left
    # miter scale (limited)
    seg = P[1:] - P[:-1]
    segn = seg / np.maximum(np.linalg.norm(seg, axis=1, keepdims=True), 1e-9)
    sc = np.ones(n)
    for k in range(1, n - 1):
        cs = float(np.dot(nrm[k], np.array((-segn[k][1], segn[k][0]))))
        sc[k] = 1.0 / max(cs, 0.6)
    W = w / 2
    p, ph = PARAPET_T, PARAPET_H
    # profile: (lateral, dz, material, edge id); closed polygon order
    if girder:
        prof = [(-W + p, 0), (W - p, 0), (W - p, ph), (W, ph), (W, -0.7), (0.62 * W, -depth), (-0.62 * W, -depth), (-W, -0.7), (-W, ph), (-W + p, ph)]
    else:
        prof = [(-W + p, 0), (W - p, 0), (W - p, ph), (W, ph), (W, -depth), (-W, -depth), (-W, ph), (-W + p, ph)]
    prof = np.array(prof, float)
    cen = prof.mean(0)
    dist = np.concatenate(([0.0], np.cumsum(np.linalg.norm(seg, axis=1))))
    road_w = lanes * LANE_M if lanes else 2 * (W - p) - 1.0
    secs = []
    for k in range(n):
        secs.append([(X[k] + nrm[k][0] * t * sc[k], Y[k] + nrm[k][1] * t * sc[k], Z[k] + dz) for t, dz in prof])
    m = len(prof)
    plen = np.concatenate(([0.0], np.cumsum(np.linalg.norm(np.diff(np.vstack((prof, prof[:1])), axis=0), axis=1))))
    for k in range(n - 1):
        for e in range(m):
            e2 = (e + 1) % m
            a0, a1, b0, b1 = secs[k][e], secs[k][e2], secs[k + 1][e], secs[k + 1][e2]
            mid_t = (prof[e][0] + prof[e2][0]) / 2 - cen[0]
            mid_z = (prof[e][1] + prof[e2][1]) / 2 - cen[1]
            # outward = lateral normal * mid_t + up * mid_z; inner parapet faces point inward (towards the road)
            if e == 0:
                hint = (0, 0, 1.0)
            elif e == 2 or e == m - 1:                    # parapet inner faces
                s_ = -1.0 if e == 2 else 1.0
                hint = (nrm[k][0] * s_, nrm[k][1] * s_, 0.0)
            else:
                hint = (nrm[k][0] * mid_t, nrm[k][1] * mid_t, mid_z)
            if e == 0:
                u0 = (prof[e][0] + road_w / 2) / LANE_M
                u1 = (prof[e2][0] + road_w / 2) / LANE_M
                v0, v1 = dist[k] / 12.0, dist[k + 1] / 12.0
                M.quad(0, [a0, a1, b1, b0], (1, 1, 1), [(u0, v0), (u1, v0), (u1, v1), (u0, v1)], hint)
            else:
                col = C_PARA if e in (2, 3, m - 2, m - 1) else C_CONC
                M.quad(1, [a0, a1, b1, b0], col, [(plen[e] / 4, dist[k] / 4), (plen[e + 1] / 4, dist[k] / 4),
                                                   (plen[e + 1] / 4, dist[k + 1] / 4), (plen[e] / 4, dist[k + 1] / 4)], hint)


# ---- textures --------------------------------------------------------------------------------------------------------
def textures():
    from PIL import Image
    rng = np.random.default_rng(7)
    W, H = 128, 512                                       # one lane (3.5 m) x 12 m
    a = 0.20 + 0.035 * rng.standard_normal((H, W))
    a += 0.02 * np.repeat(np.repeat(rng.standard_normal((H // 8, W // 8)), 8, 0), 8, 1)
    # tyre tracks: slightly darker bands
    u = (np.arange(W) + 0.5) / W
    a -= 0.03 * (np.exp(-((u - 0.28) / 0.07) ** 2) + np.exp(-((u - 0.72) / 0.07) ** 2))[None, :]
    img = np.clip(np.stack([a, a, a * 1.02], -1), 0, 1)
    lw = max(2, int(round(0.15 / LANE_M * W)))
    dash = slice(0, H // 2)                               # 6 m painted / 6 m gap
    img[dash, :lw // 2 + 1] = 0.82
    img[dash, W - lw // 2:] = 0.82
    asphalt = Image.fromarray((img ** (1 / 2.2) * 255).astype(np.uint8))
    c = 0.72 + 0.05 * rng.standard_normal((64, 64))
    c += 0.04 * np.repeat(np.repeat(rng.standard_normal((8, 8)), 8, 0), 8, 1)
    conc = Image.fromarray((np.clip(np.stack([c, c, c * 0.98], -1), 0, 1) * 255).astype(np.uint8))
    out = []
    for im in (asphalt, conc):
        b = io.BytesIO()
        im.save(b, "PNG", optimize=True)
        out.append(b.getvalue())
    return out


# ---- structures --------------------------------------------------------------------------------------------------------
def build(G, h, mesh, water, dem, mesh_height):
    """-> list of (tile key, Mesh) parts: ("a" | "b", way midpoint lat, lon)."""
    parts = []
    stat = dict(ways=0, km=0.0, piers=0, towers=0, cables_km=0.0, big={}, by_class={})
    groups = {}
    for wd in G.ways:
        w = wd["w"]
        t = w.get("tags", {})
        ii = np.array(wd["idx"])
        X, Y, Z = G.px[ii], G.py[ii], h[ii]
        L = float(np.hypot(np.diff(X), np.diff(Y)).sum())
        if L < 1.0:
            continue
        width, lanes = way_width(t)
        hw = t.get("highway", "")
        major = hw in MAJOR or L > 300
        depth = 2.4 if (hw in MAJOR or width > 12) else 1.4
        if wd.get("big") == "광안대교":
            depth = 3.0
        M = Mesh()
        sweep(M, X, Y, Z, width, depth, lanes, girder=depth > 2.0)
        # piers
        dist = np.concatenate(([0.0], np.cumsum(np.hypot(np.diff(X), np.diff(Y)))))
        wfrac = float(water[ii].mean())
        spacing = 60.0 if (wfrac > 0.3 and L > 500) else 40.0 if major else 30.0
        cable = wd.get("big") is not None
        if not cable:
            npier = int(L // spacing)
            off = (L - npier * spacing) / 2 if npier else L / 2
            for k in range(max(npier, 1) + (1 if npier else 0)):
                s = off + k * spacing
                if s <= 3.0 or s >= L - 3.0:
                    continue
                j = int(np.searchsorted(dist, s)) - 1
                j = min(max(j, 0), len(X) - 2)
                f = (s - dist[j]) / max(dist[j + 1] - dist[j], 1e-9)
                px, py = X[j] + (X[j + 1] - X[j]) * f, Y[j] + (Y[j + 1] - Y[j]) * f
                pz = Z[j] + (Z[j + 1] - Z[j]) * f
                la, lo = latlon(px, py)
                g = float(mesh_height(dem, np.array([la]), np.array([lo]))[0])
                bot_deck = pz - depth
                if bot_deck - g < 1.5:
                    continue
                d = np.array((X[j + 1] - X[j], Y[j + 1] - Y[j]))
                d /= max(np.linalg.norm(d), 1e-9)
                v = np.array((-d[1], d[0]))
                gz = -15.0 if g <= 0.3 else g - 2.0
                capw = width / 2 * 0.92
                M.box((px, py), d, v, 1.2, capw, bot_deck - 1.6, bot_deck, C_PIER)      # cap beam
                if width <= 13:
                    M.box((px, py), d, v, 1.0, min(width * 0.18, 2.4), gz, bot_deck - 1.6, C_PIER, faces="sides")
                else:
                    for sgn in (-1, 1):
                        c = np.array((px, py)) + v * sgn * width * 0.3
                        M.box(c, d, v, 1.0, 1.0, gz, bot_deck - 1.6, C_PIER, faces="sides")
                stat["piers"] += 1
        mid = len(X) // 2
        la, lo = latlon(X[mid], Y[mid])
        parts.append((("a" if major else "b"), float(la), float(lo), M))
        stat["ways"] += 1
        stat["km"] += L / 1000
        stat["by_class"][hw] = round(stat["by_class"].get(hw, 0) + L / 1000, 2)
        nm = t.get("bridge:name") or t.get("name") or "(이름 없음)"
        g_ = groups.setdefault(nm, dict(km=0.0, ways=0, hmin=1e9, hmax=-1e9, ground_min=1e9, water=0.0))
        g_["km"] += L / 1000
        g_["ways"] += 1
        g_["hmin"], g_["hmax"] = min(g_["hmin"], float(Z.min())), max(g_["hmax"], float(Z.max()))
        g_["ground_min"] = min(g_["ground_min"], float(mesh[ii].min()))
        if wd.get("big"):
            groups[nm]["big"] = wd["big"]
    # cable bridges: towers + cables once per big bridge (all tagged cable segments of that name)
    for key, spec in BIG.items():
        if not spec.get("kind"):
            continue
        segs = [wd for wd in G.ways if wd.get("big") == key and wd["w"].get("tags", {}).get("bridge:structure") in ("suspension", "cable-stayed")]
        if not segs:
            continue
        # pair segments that run side by side (two carriageways): one structure per pair, axis = the longest
        segs.sort(key=lambda wd: -len(wd["idx"]))
        used = set()
        for ax in segs:
            if id(ax) in used:
                continue
            ii = np.array(ax["idx"])
            X, Y = G.px[ii], G.py[ii]
            dist = np.concatenate(([0.0], np.cumsum(np.hypot(np.diff(X), np.diff(Y)))))
            L = dist[-1]
            if L < 300:
                used.add(id(ax))
                continue
            d = np.array((X[-1] - X[0], Y[-1] - Y[0])) / L
            v = np.array((-d[1], d[0]))
            offs = [(0.0, way_width(ax["w"]["tags"])[0], ax)]
            for o in segs:
                if id(o) in used or o is ax:
                    continue
                jj = np.array(o["idx"])
                rel = np.stack((G.px[jj] - X[0], G.py[jj] - Y[0]), 1)
                along, lat_ = rel @ d, rel @ v
                if abs(np.median(lat_)) < 60 and along.min() < L * 0.3 and along.max() > L * 0.7:
                    offs.append((float(np.median(lat_)), way_width(o["w"]["tags"])[0], o))
            for _, _, o in offs:
                used.add(id(o))
            lo_ = min(o - w_ / 2 for o, w_, _ in offs) - 2.0
            hi_ = max(o + w_ / 2 for o, w_, _ in offs) + 2.0
            Zax = h[ii]
            fr = spec["towers"]
            st = [fr[0] * L, fr[1] * L]
            main = st[1] - st[0]
            M = Mesh()
            col = spec.get("color", C_CONC)
            tops = []
            deck_z = []
            for s in st:
                j = min(int(np.searchsorted(dist, s)), len(X) - 1)
                c = np.array((X[0], Y[0])) + d * s
                dz = float(Zax[j])
                deck_z.append(dz)
                top = spec["top"] if spec.get("top") else dz + 0.25 * main
                tops.append(top)
                leg = 2.5 if top > 120 else 2.0
                for lat_off in (lo_ - leg, hi_ + leg):
                    M.box(c + v * lat_off, d, v, 3.0, leg, -15.0, top, col)
                cw = (hi_ - lo_) / 2 + 2 * leg
                cc = c + v * (lo_ + hi_) / 2
                beams = [(dz - 4.5, 3.5), (top - 4.0, 4.0)] + ([((dz + top) / 2, 3.0)] if top - dz > 60 else [])
                for zc, th in beams:
                    M.box(cc, d, v, 2.5, cw, zc - th / 2, zc + th / 2, col)
                stat["towers"] += 1
            cab = 0.0
            if spec["kind"] == "suspension":
                for lat_off in (lo_ + 1.7, hi_ - 1.7):
                    zt = [tp - 3.0 for tp in tops]
                    zmid = min(deck_z) + 4.0
                    pts = []
                    for s in np.linspace(0, L, int(L / 15) + 1):
                        if s <= st[0]:                                       # side span: anchorage (deck + 1) -> tower, slight sag
                            f = s / st[0]
                            z = (Zax[0] + 1.0) + (zt[0] - Zax[0] - 1.0) * f - 6.0 * 4 * f * (1 - f)
                        elif s >= st[1]:
                            f = (s - st[1]) / (L - st[1])
                            z = zt[1] + (Zax[-1] + 1.0 - zt[1]) * f - 6.0 * 4 * f * (1 - f)
                        else:
                            f = (s - st[0]) / main * 2 - 1
                            z = zmid + ((zt[0] + zt[1]) / 2 - zmid) * f * f
                        pts.append((np.array((X[0], Y[0])) + d * s + v * lat_off, z, s))
                    for (p0, z0, s0), (p1, z1, s1) in zip(pts, pts[1:]):
                        M.beam((p0[0], p0[1], z0), (p1[0], p1[1], z1), 0.9, C_CABLE)
                        cab += math.hypot(15.0, z1 - z0)
                    for p0, z0, s0 in pts[1:-1]:                              # hangers down to the deck edge
                        j = min(int(np.searchsorted(dist, s0)), len(X) - 1)
                        if z0 - Zax[j] > 2.5 and all(abs(s0 - s_) > 8 for s_ in st):
                            M.beam((p0[0], p0[1], z0), (p0[0], p0[1], Zax[j] + 1.0), 0.3, C_CABLE)
            else:                                                            # cable-stayed: fans, 2 planes, 12 stays a side
                for k, s in enumerate(st):
                    reach = min(main / 2, s if k == 0 else L - s) * 0.92
                    for lat_off in (lo_ + 1.7, hi_ - 1.7):
                        c = np.array((X[0], Y[0])) + d * s + v * lat_off
                        for side in (-1, 1):
                            if side == -1 and k == 0:
                                reach_s = min(reach, s * 0.95)
                            elif side == 1 and k == 1:
                                reach_s = min(reach, (L - s) * 0.95)
                            else:
                                reach_s = reach
                            for m in range(1, 13):
                                sa = s + side * reach_s * m / 12
                                j = min(int(np.searchsorted(dist, sa)), len(X) - 1)
                                za = tops[k] - 6.0 - (12 - m) * min(2.5, (tops[k] - deck_z[k]) * 0.4 / 12)
                                pa = np.array((X[0], Y[0])) + d * sa + v * lat_off
                                M.beam((c[0], c[1], za), (pa[0], pa[1], Zax[j] + 0.8), 0.35, C_CABLE)
                                cab += math.hypot(abs(sa - s), za - Zax[j])
            stat["cables_km"] += cab / 1000
            la, lo = latlon(X[0] + d[0] * L / 2, Y[0] + d[1] * L / 2)
            parts.append(("a", float(la), float(lo), M))
            stat["big"][key] = dict(span_m=round(L), towers_at_m=[round(s) for s in st], main_m=round(main), deck_m=[round(z, 1) for z in deck_z],
                                    tower_top_m=[round(z, 1) for z in tops], carriageways=len(offs))
    stat["km"] = round(stat["km"], 2)
    stat["cables_km"] = round(stat["cables_km"], 2)
    return parts, stat, groups


# ---- tiles -------------------------------------------------------------------------------------------------------------
def mesh_glb(Ms, center, dem, imgs):
    import buildings_build as B
    R = B.enu_rot(*center)
    C0 = B.ecef(np.array(center[0]), np.array(center[1]), np.array(0.0)).reshape(3)
    prims, allE = [], []
    for mat in (0, 1):
        qs = [q for M in Ms for q in M.q[mat]]
        if not qs:
            continue
        P = np.concatenate([q[0] for q in qs])                         # (4n, 3) planar x, y, z MSL
        col = np.repeat(np.array([q[1] for q in qs], float), 4, axis=0)
        UV = np.concatenate([q[2] for q in qs])
        la, lo = latlon(P[:, 0], P[:, 1])
        he = P[:, 2] + dem.geoid_n(la, lo)
        E = (B.ecef(la, lo, he) - C0) @ R                              # local ENU
        allE.append((E, la, lo, he))
        nq = len(qs)
        E4 = E.reshape(nq, 4, 3)
        nn = np.cross(E4[:, 1] - E4[:, 0], E4[:, 2] - E4[:, 0])
        nn2 = np.cross(E4[:, 2] - E4[:, 0], E4[:, 3] - E4[:, 0])
        nn = nn + nn2
        nn /= np.maximum(np.linalg.norm(nn, axis=1, keepdims=True), 1e-12)
        N = np.repeat(nn, 4, axis=0)
        base = np.arange(nq, dtype=np.uint32) * 4
        I = np.stack((base, base + 1, base + 2, base, base + 2, base + 3), 1).reshape(-1)
        S = np.array([[1, 0, 0], [0, 0, 1], [0, -1, 0]], np.float64)
        Cg = np.concatenate((np.clip(np.round(col * 255), 0, 255), np.full((len(col), 1), 255)), 1).astype(np.uint8)
        prims.append(dict(P=(E @ S.T).astype(np.float32), N=(N @ S.T).astype(np.float32), C=Cg, UV=UV.astype(np.float32), I=I.astype(np.uint32), material=mat))
    Z2Y = np.array([[1, 0, 0], [0, 0, 1], [0, -1, 0]], np.float64)
    S = np.array([[1, 0, 0], [0, 0, 1], [0, -1, 0]], np.float64)
    Mx = np.eye(4)
    Mx[:3, :3] = Z2Y @ R @ S.T
    Mx[:3, 3] = Z2Y @ C0
    images = [("image/png", imgs[0], 1), ("image/png", imgs[1], 1)]
    mats = [("asphalt", 0, 0.9), ("concrete", 1, 0.85)]
    glb = B.glb_bytes(prims, images, mats, Mx)
    la = np.concatenate([a[1] for a in allE])
    lo = np.concatenate([a[2] for a in allE])
    he = np.concatenate([a[3] for a in allE])
    region = [math.radians(float(lo.min())), math.radians(float(la.min())), math.radians(float(lo.max())), math.radians(float(la.max())),
              float(he.min()), float(he.max())]
    return glb, region, sum(len(p["P"]) for p in prims)


def tiles():
    import terrain_dem as T
    import buildings_build as B
    t0 = time.time()
    nodes, elev, ground, osm_base = load()
    print("osm: %d bridge / elevated ways, %d ground ways (base %s)" % (len(elev), len(ground), osm_base), flush=True)
    dem = T.Dem()
    G = Graph(nodes, elev, ground)
    h, mesh, low, water, anchors = solve_heights(G, dem, B.mesh_height)
    print("graph %d points, %d anchors, heights %.0f s" % (len(G.px), len(anchors), time.time() - t0), flush=True)
    parts, stat, groups = build(G, h, mesh, water, dem, B.mesh_height)
    imgs = textures()
    dla, dlo = STEP_A
    bins = {}
    for lvl, la, lo, M in parts:
        sub = 1 if lvl == "a" else 4
        i, j = int(math.floor(la / (dla / sub))), int(math.floor(lo / (dlo / sub)))
        bins.setdefault((lvl, i, j), []).append(M)
    tmp = TILES + "_tmp"
    if os.path.isdir(tmp):
        import shutil
        shutil.rmtree(tmp)
    os.makedirs(os.path.join(tmp, "a"))
    os.makedirs(os.path.join(tmp, "b"))
    content, sizes, verts = {}, {}, 0
    for (lvl, i, j), Ms in sorted(bins.items()):
        sub = 1 if lvl == "a" else 4
        center = ((i + 0.5) * dla / sub, (j + 0.5) * dlo / sub)
        glb, reg, nv = mesh_glb(Ms, center, dem, imgs)
        fn = "%s/%d_%d.glb" % (lvl, i, j)
        with open(os.path.join(tmp, fn), "wb") as f:
            f.write(glb)
        content[(lvl, i, j)] = (fn, reg)
        sizes[fn] = len(glb)
        verts += nv

    def union(a, b):
        return [min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3]), min(a[4], b[4]), max(a[5], b[5])]
    # tree: root -> A (8 km: major roads, cable bridges) -> B (2 km: the rest), additive
    kids = {}
    for (lvl, i, j) in content:
        if lvl == "b":
            kids.setdefault((i // 4, j // 4), []).append((i, j))
    a_keys = sorted({(i, j) for (lvl, i, j) in content if lvl == "a"} | set(kids))
    nodes_a = []
    for (i, j) in a_keys:
        ch = []
        for (bi, bj) in sorted(kids.get((i, j), [])):
            fn, reg = content[("b", bi, bj)]
            ch.append(dict(boundingVolume=dict(region=reg), geometricError=GE["b"], content=dict(uri=fn)))
        reg = None
        for c in ch:
            reg = c["boundingVolume"]["region"] if reg is None else union(reg, c["boundingVolume"]["region"])
        node = dict(geometricError=GE["a"])
        if ("a", i, j) in content:
            fn, r = content[("a", i, j)]
            node["content"] = dict(uri=fn)
            reg = r if reg is None else union(reg, r)
        if ch:
            node["children"] = ch
        else:
            node["geometricError"] = 0.0
        node["boundingVolume"] = dict(region=reg)
        nodes_a.append(node)
    reg = None
    for c in nodes_a:
        reg = c["boundingVolume"]["region"] if reg is None else union(reg, c["boundingVolume"]["region"])
    ts = dict(asset=dict(version="1.1", tilesetVersion=time.strftime("%Y%m%d%H%M%S"), generator="gyro-sim-chair sim/roads_build.py",
                         copyright="© OpenStreetMap contributors (ODbL)", extras=dict(osm_base=osm_base, input=OSM_FILE)),
              geometricError=GE["root"] * 2, root=dict(boundingVolume=dict(region=reg), geometricError=GE["root"], refine="ADD", children=nodes_a))
    with open(os.path.join(tmp, "tileset.json"), "w", encoding="utf-8") as f:
        json.dump(ts, f, ensure_ascii=False)
    grp = {k: dict(v, km=round(v["km"], 3), hmin=round(v["hmin"], 1), hmax=round(v["hmax"], 1), ground_min=round(v["ground_min"], 1))
           for k, v in sorted(groups.items(), key=lambda kv: -kv[1]["km"])}
    named = {k: v for k, v in grp.items() if k != "(이름 없음)"}
    out = dict(made=time.strftime("%Y-%m-%d %H:%M:%S"), seconds=round(time.time() - t0), input=dict(osm=OSM_FILE, osm_base=osm_base),
               content_tiles=len(sizes), bytes=sum(sizes.values()), largest_tile=max(sizes.values()), verts=int(verts),
               graph_points=int(len(G.px)), anchors=len(anchors), named_structures=len(named), **stat,
               rules=dict(grade=GRADE, grade_big=GRADE_BIG, clear_layer=CLEAR_LAYER, clear_water=CLEAR_WATER, big=BIG, ge=GE))
    with open(os.path.join(tmp, "build.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, indent=1, ensure_ascii=False)
    with open(os.path.join(tmp, "groups.json"), "w", encoding="utf-8") as f:
        json.dump(grp, f, indent=1, ensure_ascii=False)
    if os.path.isdir(TILES):                              # swap only after a complete build
        import shutil
        shutil.rmtree(TILES)
    os.replace(tmp, TILES)
    print("done: %d ways, %.1f km, %d named, %d piers, %d towers, %.1f km cables, %d tiles %.1f MB (largest %.1f MB), %d verts, %.0f s -> %s" % (
        stat["ways"], stat["km"], len(named), stat["piers"], stat["towers"], stat["cables_km"], len(sizes), out["bytes"] / 1e6,
        out["largest_tile"] / 1e6, verts, out["seconds"], TILES), flush=True)


def attrib():
    """the buildings plate (V-World + building + Copernicus credits) + the OSM line, for the vworld mode with roads on."""
    from PIL import Image, ImageDraw, ImageFont
    import vworld_proxy as VP
    W, H = 1600, 294
    im = Image.new("RGB", (W, H), (10, 12, 14))
    g = ImageDraw.Draw(im)
    g.text((W / 2, 48), VP.ATTRIB_TEXT, font=ImageFont.truetype(r"C:\Windows\Fonts\malgunbd.ttf", 54), fill=(235, 238, 240), anchor="mm")
    f = ImageFont.truetype(r"C:\Windows\Fonts\malgun.ttf", 30)
    for i, t in enumerate((VP.BLDG_ATTRIB_LINE, ATTRIB) + VP.TERRAIN_ATTRIB_LINES):
        g.text((W / 2, 116 + 44 * i), t, font=f, fill=(215, 220, 224), anchor="mm")
    im.save(ATTRIB_PNG)
    print("->", ATTRIB_PNG)


if __name__ == "__main__":
    a = sys.argv[1:]
    if "--fetch" in a:
        fetch()
    if "--tiles" in a:
        tiles()
    if "--attrib" in a:
        attrib()
    if not a:
        print(__doc__)
