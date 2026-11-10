"""3D trees on Busan's hills and parks for the Unreal 'vworld' ground mode (near the aircraft only; far away the V-World
photo stays). Output = 3D Tiles 1.1 (glb with EXT_mesh_gpu_instancing), loaded at Play by
unreal/GyroSim/Content/Python/trees_look.py from file:///C:/GyroSimTiles/veg/tiles/tileset.json (the map's 'CesiumTrees'
tileset actor, Scripts/add_trees_actor.py).

    python -I sim/veg_build.py --fetch     ESA WorldCover + Meta canopy height + OSM roads / water (one Overpass request)
    python -I sim/veg_build.py --prep      tree tops per 1.8 km block -> C:\\GyroSimTiles\\veg\\work\\*.npz  (~10 min, 12 processes)
    python -I sim/veg_build.py --tiles     -> C:\\GyroSimTiles\\veg\\tiles\\tileset.json + b/*.glb (far) + c/*.glb (near), build.json
    python -I sim/veg_build.py --attrib    on-screen credit plate sim/vworld_trees_attribution.png

Where the trees are (all data outside git, C:\\GyroSimTiles\\veg\\raw):
  - HOW TALL + WHERE THERE IS CANOPY: Meta / WRI High Resolution Canopy Height Map v1 (CC BY 4.0, AWS open data, quadkey tile
    132112131 = Busan; https://registry.opendata.aws/dataforgood-fb-forests/), Web Mercator 1.194 m = V-World z17 pixels.
    Trees only where the smoothed canopy height is >= 3 m; tree height = 3 x 3 max of it, +-12 %. The CHM is too smooth here to
    show single crowns (11-10: 4-6 local maxima / ha), so:
  - WHERE EACH TREE STANDS: crowns in the V-World z17 photo = local maxima (5 px = 6 m window) of the blurred luminance
    (sunlit crown tops bright, gaps dark), ~100-180 / ha on the hills. Where the photo is not cached: a jittered 7 m grid.
  - WHAT LAND: ESA WorldCover 2021 v200 (10 m, CC BY 4.0, https://esa-worldcover.org). Trees only on tree cover (10), shrub (20),
    grass (30), wetland (90), mangrove (95); cropland (40) only if the canopy is >= 6 m (orchards / tree lines); never on
    built-up (50), bare (60), water (80).
  - NEVER ON: OSM roads (half width by class + 1 m), railways, natural=water (ODbL, Overpass), the 국토교통부 GIS건물통합정보
    footprints (+2 m, C:\\GyroSimTiles\\buildings\\work\\buildings_busan.npz) and the sea (DEM <= 0.5 m MSL).
  - SPECIES + COLOUR: the V-World z17 photo (local cache, never in git) under each crown: in each block the darker, bluer
    crowns are pines (소나무 / 곰솔 look), the lighter yellow-green ones broadleaf (참나무류) - a photo heuristic (가정), not a
    forest-type map (산림청 임상도 needs an account). The crown colour is the photo mean (x GAIN, 6 colour bins per species).
  - CROWN WIDTH: 0.6 x the mean spacing of tree tops within 12 m (closed canopy stays closed), clamped by height.
  - BASE: the rendered Cesium terrain mesh (buildings_build.mesh_height) - 1.0 m (trunks go into the ground a little).

Tiles (REPLACE refinement): root -> A (1.8 km, empty: nothing drawn beyond ~3 km) -> B (same block, far trees: one 20-triangle
crown each) -> C (450 m, near trees: trunk + 2-5 crown lumps, 46-110 triangles). Geometric errors are chosen for the default
maximum screen space error 16 at ~1080 px / 70 deg: A refines at ~2.6 km, B at ~1 km from the tile (VR: similar - Cesium
scales with the viewport height and fov).
Prototype meshes are made here (no third-party assets); one glTF node per (prototype, colour bin) with instance
TRANSLATION / ROTATION / SCALE (Cesium for Unreal 2.31 makes instanced static mesh components).
Run with `python -I` (inputs are downloads): user site-packages are added back below.
"""
import json, math, os, sys, time, struct, site
if sys.flags.isolated:
    site.addsitedir(site.getusersitepackages())
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import numpy as np                                        # noqa: E402

ROOT = os.environ.get("GYROSIM_VEG", r"C:\GyroSimTiles\veg")
RAW, WORK = os.path.join(ROOT, "raw"), os.path.join(ROOT, "work")
TILES = os.environ.get("GYROSIM_VEG_TILES", os.path.join(ROOT, "tiles"))
SAT17 = os.path.join(os.environ.get("GYROSIM_TILES", r"C:\GyroSimTiles"), "vworld", "Satellite", "17")
BLD = os.path.join(os.environ.get("GYROSIM_TILES", r"C:\GyroSimTiles"), "buildings", "work", "buildings_busan.npz")
BOX = (34.96, 128.75, 35.40, 129.33)                      # S W N E = terrain_dem.HIRES busan box
CHM_KEY = "132112131"                                     # Bing quadkey (z9) of the Meta CHM tile that holds Busan
CHM = os.path.join(RAW, "meta_chm_%s.tif" % CHM_KEY)
CHM_URL = "https://dataforgood-fb-data.s3.amazonaws.com/forests/v1/alsgedi_global_v6_float/chm/%s.tif" % CHM_KEY
WC = {126: "ESA_WorldCover_10m_2021_v200_N33E126_Map.tif", 129: "ESA_WorldCover_10m_2021_v200_N33E129_Map.tif"}
WC_URL = "https://esa-worldcover.s3.eu-central-1.amazonaws.com/v200/2021/map/"
OSM = os.path.join(RAW, "osm_busan_excl.json")
OVERPASS = "https://overpass-api.de/api/interpreter"
UA = "gyro-sim-chair veg_build.py (personal flight sim; one request per manual run)"
ATTRIB_PNG = os.path.join(HERE, "vworld_trees_attribution.png")

DLA, DLO = 0.016, 0.02                                    # B block (~1.8 x 1.8 km); C = 4 x 4 per block (~450 m)
SUB = 4
GE = dict(root=20000.0, a=30.0, b=12.0, c=0.0)
R_MERC = 6378137.0
RES17 = 2 * math.pi * R_MERC / (256 * 2 ** 17)            # 1.19433 m: V-World z17 pixel = Meta CHM pixel
ORIG = math.pi * R_MERC
H_MIN = 3.0
LANDCOVER_OK = (10, 20, 30, 90, 95)
ROAD_HALF = dict(motorway=12.0, trunk=10.0, primary=9.0, secondary=7.0, tertiary=5.5, unclassified=3.5, residential=3.5,
                 service=2.5, living_street=3.0, pedestrian=3.0, motorway_link=5.0, trunk_link=5.0, primary_link=5.0,
                 secondary_link=4.0, tertiary_link=4.0, rail=4.0, subway=4.0, light_rail=4.0)
SINK = 1.0
GAIN = float(os.environ.get("GYROSIM_VEG_GAIN", "1.9"))   # photo colour -> albedo (self-shadowed crowns read darker)
NBIN = 6


# ---- small helpers -------------------------------------------------------------------------------------------------------
def merc(lat, lon):
    lat, lon = np.asarray(lat, np.float64), np.asarray(lon, np.float64)
    return R_MERC * np.radians(lon), R_MERC * np.log(np.tan(np.pi / 4 + np.radians(lat) / 2))


def unmerc(x, y):
    return np.degrees(2 * np.arctan(np.exp(np.asarray(y) / R_MERC)) - np.pi / 2), np.degrees(np.asarray(x) / R_MERC)


def srgb_to_lin(c):
    c = np.asarray(c, np.float64) / 255.0
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)


# ---- fetch ---------------------------------------------------------------------------------------------------------------
def fetch():
    import urllib.request, urllib.parse
    os.makedirs(RAW, exist_ok=True)
    jobs = [(CHM_URL, CHM)] + [(WC_URL + f, os.path.join(RAW, f)) for f in WC.values()]
    for url, path in jobs:
        if os.path.isfile(path):
            print("have", path); continue
        print("get", url, flush=True)
        urllib.request.urlretrieve(url, path + ".part")
        os.replace(path + ".part", path)
    if not os.path.isfile(OSM):
        s, w, n, e = BOX
        bb = "(%g,%g,%g,%g)" % (s, w, n, e)
        q = ('[out:json][timeout:300];(way["highway"~"^(%s)$"]%s;way["railway"~"^(rail|subway|light_rail)$"]["tunnel"!="yes"]%s;'
             'way["leisure"~"^(pitch|stadium)$"]%s;way["natural"="water"]%s;);out geom tags;'
             % ("|".join(k for k in ROAD_HALF if k not in ("rail", "subway", "light_rail")), bb, bb, bb, bb))
        req = urllib.request.Request(OVERPASS, data=urllib.parse.urlencode(dict(data=q)).encode(), headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=400) as r:
            data = r.read()
        with open(OSM + ".part", "wb") as f:
            f.write(data)
        os.replace(OSM + ".part", OSM)
    json.dump(dict(made=time.strftime("%Y-%m-%d %H:%M:%S"), chm=CHM_URL, worldcover=[WC_URL + f for f in WC.values()], osm=OVERPASS),
              open(os.path.join(RAW, "manifest.json"), "w"), indent=1)


def osm_prep():
    """OSM -> exclusion lines (Mercator x, y pairs + half width) and water / pitch polygons, cached as npz."""
    out = os.path.join(WORK, "osm_excl.npz")
    if os.path.isfile(out) and os.path.getmtime(out) > os.path.getmtime(OSM):
        return out
    d = json.load(open(OSM, encoding="utf-8"))
    segs, polys, pid = [], [], []
    for el in d["elements"]:
        g, t = el.get("geometry"), el.get("tags", {})
        if not g or len(g) < 2:
            continue
        la = np.array([p["lat"] for p in g]); lo = np.array([p["lon"] for p in g])
        x, y = merc(la, lo)
        k = t.get("highway") or t.get("railway")
        if k in ROAD_HALF and t.get("tunnel") not in ("yes", "building_passage"):
            hw = ROAD_HALF[k] + 1.0
            if t.get("width"):
                try:
                    hw = max(hw, float(t["width"].split()[0]) / 2 + 1.0)
                except ValueError:
                    pass
            for i in range(len(x) - 1):
                segs.append((x[i], y[i], x[i + 1], y[i + 1], hw))
        elif (t.get("natural") == "water" or t.get("leisure") in ("pitch", "stadium")) and len(x) >= 3:
            polys.append(np.stack((x, y), 1)); pid.append(len(polys) - 1)
    P = np.concatenate(polys) if polys else np.zeros((0, 2))
    n = np.array([len(p) for p in polys], np.int64)
    np.savez(out, segs=np.array(segs, np.float64), pxy=P, pn=n)
    print("osm: %d road / rail segments, %d water / pitch polygons" % (len(segs), len(polys)), flush=True)
    return out


def bld_prep():
    """building footprints -> Mercator rings + per-ring bbox (npz cache)."""
    out = os.path.join(WORK, "bld_rings.npz")
    if os.path.isfile(out):
        return out
    z = np.load(BLD)
    x, y = merc(z["lat"], z["lon"])
    n = z["nring"].astype(np.int64)
    st = np.concatenate(([0], np.cumsum(n)[:-1]))
    bx0 = np.minimum.reduceat(x, st); bx1 = np.maximum.reduceat(x, st)
    by0 = np.minimum.reduceat(y, st); by1 = np.maximum.reduceat(y, st)
    np.savez(out, x=x, y=y, st=st, n=n, bb=np.stack((bx0, by0, bx1, by1), 1))
    print("buildings: %d rings" % len(n), flush=True)
    return out


# ---- prep: tree tops per B block ----------------------------------------------------------------------------------------
def blocks():
    s, w, n, e = BOX
    out = []
    for i in range(int(math.floor(s / DLA)), int(math.ceil(n / DLA))):
        for j in range(int(math.floor(w / DLO)), int(math.ceil(e / DLO))):
            out.append((i, j))
    return out


_G = {}


def _init():
    import rasterio
    import terrain_dem as T
    _G["chm"] = rasterio.open(CHM)
    _G["wc"] = {k: rasterio.open(os.path.join(RAW, f)) for k, f in WC.items()}
    _G["dem"] = T.Dem()
    o = np.load(os.path.join(WORK, "osm_excl.npz"))
    _G["segs"], _G["pxy"], _G["pn"] = o["segs"], o["pxy"], o["pn"]
    _G["pst"] = np.concatenate(([0], np.cumsum(_G["pn"])[:-1])) if len(_G["pn"]) else np.zeros(0, np.int64)
    b = np.load(os.path.join(WORK, "bld_rings.npz"))
    _G["bld"] = {k: b[k] for k in b.files}


def photo_window(X0, Y0, W, H):
    """V-World z17 mosaic (sRGB uint8, H x W x 3) for global z17 pixels X0..X0+W, Y0..Y0+H; ok mask = cached pixels."""
    from PIL import Image
    img = np.zeros((H, W, 3), np.uint8)
    ok = np.zeros((H, W), bool)
    for ty in range(Y0 // 256, (Y0 + H - 1) // 256 + 1):
        for tx in range(X0 // 256, (X0 + W - 1) // 256 + 1):
            p = os.path.join(SAT17, str(ty), "%d.jpg" % tx)
            if not os.path.isfile(p):
                continue
            try:
                a = np.asarray(Image.open(p).convert("RGB"))
            except Exception:
                continue
            gx0, gy0 = tx * 256, ty * 256
            x0, y0 = max(gx0, X0), max(gy0, Y0)
            x1, y1 = min(gx0 + 256, X0 + W), min(gy0 + 256, Y0 + H)
            img[y0 - Y0:y1 - Y0, x0 - X0:x1 - X0] = a[y0 - gy0:y1 - gy0, x0 - gx0:x1 - gx0]
            ok[y0 - Y0:y1 - Y0, x0 - X0:x1 - X0] = True
    return img, ok


def prep_block(ij):
    import cv2
    from scipy import ndimage
    from scipy.spatial import cKDTree
    import buildings_build as B
    from rasterio.windows import Window
    i, j = ij
    s, w = i * DLA, j * DLO
    n, e = s + DLA, w + DLO
    out = os.path.join(WORK, "b_%d_%d.npz" % (i, j))
    chm = _G["chm"]
    PAD = 12
    xw, ys = merc(s, w); xe, yn = merc(n, e)
    left, top = chm.transform.c, chm.transform.f
    res = chm.transform.a
    c0 = int(math.floor((float(xw) - left) / res)) - PAD
    r0 = int(math.floor((top - float(yn)) / res)) - PAD
    c1 = int(math.ceil((float(xe) - left) / res)) + PAD
    r1 = int(math.ceil((top - float(ys)) / res)) + PAD
    c0, r0 = max(c0, 0), max(r0, 0)
    c1, r1 = min(c1, chm.width), min(r1, chm.height)
    H, W = r1 - r0, c1 - c0
    a = chm.read(1, window=Window(c0, r0, W, H)).astype(np.float32)
    stat = dict(block=[i, j])
    if a.max() < H_MIN:
        np.savez(out, n=0); return dict(stat, trees=0)
    # pixel centre coordinates
    px = left + (np.arange(c0, c1) + 0.5) * res
    py = top - (np.arange(r0, r1) + 0.5) * res
    # tree tops = crowns in the photo: local maxima (5 px = 6 m window) of the blurred z17 luminance (sunlit crown tops are
    # bright, gaps dark), where the canopy height is >= 3 m. The Meta CHM here is too smooth to show single crowns (11-10 check:
    # 4-6 tops / ha). Where the photo is not cached: a jittered 7 m grid.
    rng = np.random.default_rng(i * 100003 + j)
    GX0 = int(round((px[0] + ORIG) / RES17 - 0.5))
    GY0 = int(round((ORIG - py[0]) / RES17 - 0.5))
    img, ok = photo_window(GX0, GY0, W, H)
    lum = img.astype(np.float32) @ np.array([0.3, 0.59, 0.11], np.float32)
    lum = ndimage.gaussian_filter(lum, 1.0) + rng.random(lum.shape, dtype=np.float32) * 0.01
    chs = ndimage.gaussian_filter(a, 1.0)
    top_m = (lum >= ndimage.maximum_filter(lum, size=5)) & ok & (chs >= H_MIN)
    g = np.zeros_like(top_m)
    step = 6
    g[step // 2::step, step // 2::step] = True
    jr = np.clip(np.arange(H)[:, None] + rng.integers(-2, 3, (H, W)), 0, H - 1)
    jc = np.clip(np.arange(W)[None, :] + rng.integers(-2, 3, (H, W)), 0, W - 1)
    gr, gc = np.nonzero(g & ~ok & (chs >= H_MIN))
    gr, gc = jr[gr, gc], jc[gr, gc]
    rr, cc = np.nonzero(top_m)
    rr, cc = np.concatenate((rr, gr)), np.concatenate((cc, gc))
    # height: canopy height (3 x 3 max of the smoothed CHM) with +-12 % tree-to-tree spread
    h = ndimage.maximum_filter(chs, size=3)[rr, cc] * rng.uniform(0.88, 1.12, len(rr)).astype(np.float32)
    keep = h >= H_MIN
    rr, cc, h = rr[keep], cc[keep], h[keep]
    X, Y = px[cc], py[rr]
    lat, lon = unmerc(X, Y)
    inb = (lat >= s) & (lat < n) & (lon >= w) & (lon < e)
    stat["tops"] = int(inb.sum())
    # ---- exclusion raster on the CHM grid -----------------------------------------------------------------------------
    ex = np.zeros((H, W), np.uint8)
    toP = lambda x, y: np.stack(((np.asarray(x) - left) / res - c0, (top - np.asarray(y)) / res - r0), -1)
    SH = 4                                                 # cv2 sub-pixel bits
    segs = _G["segs"]
    if len(segs):
        bx0, bx1 = px[0] - 60, px[-1] + 60
        by0, by1 = py[-1] - 60, py[0] + 60
        sel = (np.maximum(segs[:, 0], segs[:, 2]) > bx0) & (np.minimum(segs[:, 0], segs[:, 2]) < bx1) & \
              (np.maximum(segs[:, 1], segs[:, 3]) > by0) & (np.minimum(segs[:, 1], segs[:, 3]) < by1)
        for x0_, y0_, x1_, y1_, hw in segs[sel]:
            p = toP([x0_, x1_], [y0_, y1_])
            th = max(1, int(round(2 * hw / res)))
            cv2.line(ex, tuple(np.round(p[0] * (1 << SH)).astype(int)), tuple(np.round(p[1] * (1 << SH)).astype(int)), 1, th, cv2.LINE_8, SH)
    pxy, pn, pst = _G["pxy"], _G["pn"], _G["pst"]
    for k in range(len(pn)):
        P = pxy[pst[k]:pst[k] + pn[k]]
        if P[:, 0].max() < px[0] or P[:, 0].min() > px[-1] or P[:, 1].max() < py[-1] or P[:, 1].min() > py[0]:
            continue
        cv2.fillPoly(ex, [np.round(toP(P[:, 0], P[:, 1]) * (1 << SH)).astype(np.int32)], 1, cv2.LINE_8, SH)
    bl = _G["bld"]
    bb = bl["bb"]
    selb = np.nonzero((bb[:, 2] > px[0]) & (bb[:, 0] < px[-1]) & (bb[:, 3] > py[-1]) & (bb[:, 1] < py[0]))[0]
    bex = np.zeros((H, W), np.uint8)
    if len(selb):
        rings = [np.round(toP(bl["x"][bl["st"][k]:bl["st"][k] + bl["n"][k]], bl["y"][bl["st"][k]:bl["st"][k] + bl["n"][k]]) * (1 << SH)).astype(np.int32)
                 for k in selb]
        for ring in rings:                                 # one by one: a list is filled even-odd (overlaps came out empty)
            cv2.fillPoly(bex, [ring], 1, cv2.LINE_8, SH)
        bex = cv2.dilate(bex, np.ones((5, 5), np.uint8))   # +2 m
    ex_ok = (ex[rr, cc] == 0) & (bex[rr, cc] == 0)
    stat["ex_road_water"] = int((inb & (ex[rr, cc] > 0)).sum())
    stat["ex_building"] = int((inb & (bex[rr, cc] > 0)).sum())
    # ---- land cover ---------------------------------------------------------------------------------------------------
    lc = np.zeros(len(lat), np.uint8)
    for k, ds in _G["wc"].items():
        m = (lon >= k) & (lon < k + 3)
        if not m.any():
            continue
        tr = ds.transform
        cw = ((lon[m] - tr.c) / tr.a).astype(np.int64)
        rw = ((lat[m] - tr.f) / tr.e).astype(np.int64)
        rmin, rmax, cmin, cmax = rw.min(), rw.max(), cw.min(), cw.max()
        blk = ds.read(1, window=Window(int(cmin), int(rmin), int(cmax - cmin + 1), int(rmax - rmin + 1)))
        lc[m] = blk[rw - rmin, cw - cmin]
    lc_ok = np.isin(lc, LANDCOVER_OK) | ((lc == 40) & (h >= 6.0))
    stat["ex_landcover"] = int((inb & ex_ok & ~lc_ok).sum())
    # ---- ground ---------------------------------------------------------------------------------------------------------
    dem = _G["dem"]
    msl = dem.msl(lat, lon)
    sea_ok = msl > 0.5
    stat["ex_sea"] = int((inb & ex_ok & lc_ok & ~sea_ok).sum())
    k = inb & ex_ok & lc_ok & sea_ok
    lat, lon, h, X, Y, lc = lat[k], lon[k], h[k], X[k], Y[k], lc[k]
    nt = len(lat)
    stat["trees"] = nt
    if nt == 0:
        np.savez(out, n=0); return stat
    # crown radius from the local density (tops within 12 m, incl. the pad so block edges match): r = 0.6 x mean spacing
    # -> crowns just overlap where the canopy is closed (nearest-neighbour radii left ~30 % gaps, 11-10 shots), +-15 %
    allX, allY = px[cc], py[rr]
    tree = cKDTree(np.stack((allX, allY), 1))
    sc = np.cos(np.radians(lat))                           # Mercator metres -> ground metres
    RQ = 12.0
    cnt = np.array([len(q) for q in tree.query_ball_point(np.stack((X, Y), 1), RQ / sc.mean())], np.float64)
    spacing = np.sqrt(math.pi * RQ * RQ / np.maximum(cnt, 1.0))
    r = np.clip(0.6 * spacing * rng.uniform(0.85, 1.15, nt), 1.2, np.minimum(1.5 + 0.3 * h, 7.5))
    # ---- photo colour -----------------------------------------------------------------------------------------------------
    blur = cv2.blur(img, (3, 3)).astype(np.float32)
    pc = np.clip(np.round((X + ORIG) / RES17 - 0.5).astype(np.int64) - GX0, 0, W - 1)
    pr = np.clip(np.round((ORIG - Y) / RES17 - 0.5).astype(np.int64) - GY0, 0, H - 1)
    rgb = blur[pr, pc]
    has = ok[pr, pc]
    stat["photo_frac"] = round(float(has.mean()), 3)
    # species: darker + bluer (relative to this block's trees) = pine
    lin = srgb_to_lin(rgb)
    L = 0.2126 * lin[:, 0] + 0.7152 * lin[:, 1] + 0.0722 * lin[:, 2] + 1e-4
    yel = (lin[:, 0] + lin[:, 1]) / (2 * lin[:, 2] + 1e-4)
    if has.sum() > 50:
        lL, ly = np.log(L), np.log(yel)
        score = (lL - np.median(lL[has])) / (np.std(lL[has]) + 1e-6) + 0.6 * (ly - np.median(ly[has])) / (np.std(ly[has]) + 1e-6)
        score += rng.normal(0, 0.35, nt)
        sp = np.where(has, (score >= 0).astype(np.int8), (rng.random(nt) < 0.5).astype(np.int8))
    else:
        sp = (rng.random(nt) < 0.5).astype(np.int8)
    rgb = np.where(has[:, None], rgb, np.array([[46, 62, 38]], np.float32)).astype(np.uint8)
    mh = B.mesh_height(dem, lat, lon)
    base = mh - SINK + dem.geoid_n(lat, lon)              # ellipsoid height (Cesium)
    np.savez(out, n=nt, lat=lat, lon=lon, h=h.astype(np.float32), r=r.astype(np.float32), sp=sp, rgb=rgb, base=base.astype(np.float32),
             lc=lc, var=rng.integers(0, 2, nt).astype(np.int8), yaw=rng.random(nt).astype(np.float32))
    stat["pine_frac"] = round(float((sp == 0).mean()), 3)
    stat["h_mean"] = round(float(h.mean()), 2)
    stat["r_mean"] = round(float(r.mean()), 2)
    return stat


def prep(args):
    from multiprocessing import Pool
    os.makedirs(WORK, exist_ok=True)
    osm_prep(); bld_prep()
    bl = blocks()
    if "--only" in args:
        lat, lon = map(float, args[args.index("--only") + 1].split(","))
        bl = [(int(math.floor(lat / DLA)), int(math.floor(lon / DLO)))]
    t0 = time.time()
    stats = []
    with Pool(int(os.environ.get("GYROSIM_VEG_PROCS", "12")), initializer=_init) as pool:
        for k, st in enumerate(pool.imap_unordered(prep_block, bl)):
            stats.append(st)
            if k % 50 == 0:
                print("%d / %d blocks, %d trees, %.0f s" % (k + 1, len(bl), sum(x.get("trees", 0) for x in stats), time.time() - t0), flush=True)
    tot = {k: sum(x.get(k, 0) for x in stats) for k in ("tops", "trees", "ex_road_water", "ex_building", "ex_landcover", "ex_sea")}
    res = dict(made=time.strftime("%Y-%m-%d %H:%M:%S"), seconds=round(time.time() - t0), blocks=len(bl), totals=tot,
               inputs=dict(chm=CHM, worldcover=list(WC.values()), osm=OSM, buildings=BLD, photo=SAT17), blocks_stat=stats)
    json.dump(res, open(os.path.join(WORK, "prep.json" if "--only" not in args else "prep_only.json"), "w"), indent=0)
    print("prep done:", json.dumps(tot), "%.0f s" % (time.time() - t0), flush=True)


# ---- prototype meshes (glTF y-up, unit height 1, crown radius 1) -------------------------------------------------------
def icosa():
    t = (1 + 5 ** 0.5) / 2
    V = np.array([[-1, t, 0], [1, t, 0], [-1, -t, 0], [1, -t, 0], [0, -1, t], [0, 1, t], [0, -1, -t], [0, 1, -t],
                  [t, 0, -1], [t, 0, 1], [-t, 0, -1], [-t, 0, 1]], np.float64)
    V /= np.linalg.norm(V, axis=1, keepdims=True)
    F = np.array([[0, 11, 5], [0, 5, 1], [0, 1, 7], [0, 7, 10], [0, 10, 11], [1, 5, 9], [5, 11, 4], [11, 10, 2], [10, 7, 6], [7, 1, 8],
                  [3, 9, 4], [3, 4, 2], [3, 2, 6], [3, 6, 8], [3, 8, 9], [4, 9, 5], [2, 4, 11], [6, 2, 10], [8, 6, 7], [9, 8, 1]])
    return V, F


class Mesh:
    def __init__(self):
        self.P, self.N, self.C, self.I = [], [], [], []
        self.nv = 0

    def blob(self, c, s, seed, shade=(0.72, 1.0), col=1.0):
        V, F = icosa()
        rg = np.random.default_rng(seed)
        V = V * (1 + rg.uniform(-0.18, 0.18, (len(V), 1)))
        P = V * np.array(s) + np.array(c)
        Nn = V / np.array(s)                                # ellipsoid normal
        Nn /= np.linalg.norm(Nn, axis=1, keepdims=True)
        Nn = 0.6 * Nn + 0.4 * V / np.linalg.norm(V, axis=1, keepdims=True)   # softer (foliage scatters)
        Nn /= np.linalg.norm(Nn, axis=1, keepdims=True)
        t = (V[:, 1] + 1) / 2                               # bottom dark -> top light (AO)
        g = (shade[0] + (shade[1] - shade[0]) * t) * col
        self._add(P, Nn, np.stack((g, g, g, np.ones_like(g)), 1), F, foliage=1.0)

    def trunk(self, y0, y1, r0, r1, bend, col, sides=5):
        P, Nn, C, F = [], [], [], []
        for k, (y, r) in enumerate(((y0, r0), (y1, r1))):
            dx = bend * ((y - y0) / (y1 - y0)) ** 2
            for q in range(sides):
                a = 2 * math.pi * q / sides
                P.append((dx + r * math.cos(a), y, r * math.sin(a))); Nn.append((math.cos(a), 0, math.sin(a)))
                C.append(col + (0.0,))
        for q in range(sides):
            a, b = q, (q + 1) % sides
            F += [(a, b + sides, b), (a, a + sides, b + sides)]
        self._add(np.array(P), np.array(Nn), np.array(C), np.array(F), foliage=0.0)

    def _add(self, P, Nn, C, F, foliage):
        C = np.array(C, np.float64)
        C[:, 3] = foliage                                   # alpha channel = foliage mask (1 = tint with the colour bin)
        self.P.append(P); self.N.append(Nn); self.C.append(C); self.I.append(np.asarray(F) + self.nv)
        self.nv += len(P)

    def arrays(self, tint, trunk_col):
        P = np.concatenate(self.P).astype(np.float32); Nn = np.concatenate(self.N).astype(np.float32)
        C = np.concatenate(self.C)
        fol = C[:, 3:4]
        rgb = np.where(fol > 0.5, C[:, :3] * np.array(tint)[None, :], C[:, :3])
        Cu = np.concatenate((np.clip(np.round(rgb * 255), 0, 255), np.full((len(C), 1), 255)), 1).astype(np.uint8)
        I = np.concatenate(self.I).astype(np.uint32).reshape(-1)
        return P, Nn, Cu, I


TRUNK_PINE = (0.16, 0.085, 0.055)                         # linear: red-brown upper pine bark
TRUNK_BROAD = (0.11, 0.10, 0.085)                         # grey-brown oak


def proto(kind, var):
    """kind: 'pine' / 'broad' near, 'pine_far' / 'broad_far'. Unit: height 1 (y), crown radius 1 (x, z)."""
    m = Mesh()
    if kind == "pine":
        if var == 0:                                       # mature 소나무: umbrella of flat lumps, bent trunk
            m.trunk(-0.08, 0.84, 0.075, 0.035, 0.10, TRUNK_PINE)
            m.blob((0.05, 0.86, 0.0), (0.78, 0.13, 0.70), 11)
            m.blob((-0.38, 0.73, 0.28), (0.52, 0.12, 0.50), 12, col=0.92)
            m.blob((0.36, 0.68, -0.30), (0.50, 0.11, 0.48), 13, col=0.95)
        else:                                              # younger / 곰솔: taller crown, stacked lumps
            m.trunk(-0.08, 0.80, 0.07, 0.03, 0.04, TRUNK_PINE)
            m.blob((0.0, 0.54, 0.0), (0.95, 0.15, 0.90), 21, col=0.88)
            m.blob((0.05, 0.72, 0.03), (0.72, 0.15, 0.70), 22)
            m.blob((0.0, 0.90, 0.0), (0.42, 0.11, 0.42), 23, shade=(0.7, 1.0))
    elif kind == "broad":
        if var == 0:                                       # 참나무: dome of lumps
            m.trunk(-0.08, 0.55, 0.07, 0.045, 0.03, TRUNK_BROAD)
            m.blob((0.0, 0.66, 0.0), (0.82, 0.30, 0.82), 31)
            for q, a in enumerate((0.3, 2.2, 4.1)):
                m.blob((0.48 * math.cos(a), 0.56, 0.48 * math.sin(a)), (0.52, 0.24, 0.52), 32 + q, col=0.93)
            m.blob((0.05, 0.86, -0.05), (0.50, 0.16, 0.50), 36, shade=(0.7, 1.0))
        else:
            m.trunk(-0.08, 0.50, 0.07, 0.04, -0.06, TRUNK_BROAD)
            m.blob((-0.1, 0.62, 0.05), (0.85, 0.34, 0.80), 41)
            m.blob((0.45, 0.55, -0.25), (0.55, 0.26, 0.55), 42, col=0.94)
            m.blob((0.05, 0.84, 0.0), (0.55, 0.18, 0.55), 43, shade=(0.7, 1.0))
    elif kind == "pine_far":
        m.blob((0.0, 0.76, 0.0), (1.0, 0.22, 1.0), 51)
    else:
        m.blob((0.0, 0.66, 0.0), (1.0, 0.33, 1.0), 61)
    return m


# ---- glTF ---------------------------------------------------------------------------------------------------------------
def glb_instanced(protos, groups, Mx):
    """protos: list of (P, N, C, I); groups: list of (proto index, T (n,3), R (n,4), S (n,3)) in node-local glTF coords."""
    blob = bytearray()
    views, accs = [], []

    def view(bb, target=None):
        blob.extend(b"\0" * ((-len(blob)) % 4))
        v = dict(buffer=0, byteOffset=len(blob), byteLength=len(bb))
        if target:
            v["target"] = target
        blob.extend(bb)
        views.append(v)
        return len(views) - 1

    def acc(arr, typ, ct=5126, target=None, norm=False, mm=False):
        a = dict(bufferView=view(arr.tobytes(), target), componentType=ct, count=len(arr), type=typ)
        if norm:
            a["normalized"] = True
        if mm:
            a["min"], a["max"] = arr.min(0).tolist(), arr.max(0).tolist()
        accs.append(a)
        return len(accs) - 1
    meshes, pm = [], {}
    used = sorted({g[0] for g in groups})
    for k in used:
        P, Nn, C, I = protos[k]
        pa = acc(P, "VEC3", target=34962, mm=True)
        na = acc(Nn, "VEC3", target=34962)
        ca = acc(C, "VEC4", ct=5121, target=34962, norm=True)
        ia = acc(I, "SCALAR", ct=5125, target=34963)
        pm[k] = len(meshes)
        meshes.append(dict(primitives=[dict(attributes=dict(POSITION=pa, NORMAL=na, COLOR_0=ca), indices=ia, material=0, mode=4)]))
    nodes = [dict(matrix=[float(v) for v in Mx.T.reshape(-1)], children=[])]
    for k, T_, R_, S_ in groups:
        ext = dict(EXT_mesh_gpu_instancing=dict(attributes=dict(TRANSLATION=acc(T_.astype(np.float32), "VEC3"),
                                                                ROTATION=acc(R_.astype(np.float32), "VEC4"),
                                                                SCALE=acc(S_.astype(np.float32), "VEC3"))))
        nodes[0]["children"].append(len(nodes))
        nodes.append(dict(mesh=pm[k], extensions=ext))
    blob.extend(b"\0" * ((-len(blob)) % 4))
    gl = dict(asset=dict(version="2.0", generator="gyro-sim-chair veg_build.py"), extensionsUsed=["EXT_mesh_gpu_instancing"],
              extensionsRequired=["EXT_mesh_gpu_instancing"], scene=0, scenes=[dict(nodes=[0])], nodes=nodes, meshes=meshes,
              materials=[dict(name="foliage", pbrMetallicRoughness=dict(baseColorFactor=[1, 1, 1, 1], metallicFactor=0.0, roughnessFactor=0.9))],
              accessors=accs, bufferViews=views, buffers=[dict(byteLength=len(blob))])
    js = json.dumps(gl, separators=(",", ":")).encode()
    js += b" " * ((-len(js)) % 4)
    total = 12 + 8 + len(js) + 8 + len(blob)
    return struct.pack("<III", 0x46546C67, 2, total) + struct.pack("<II", len(js), 0x4E4F534A) + js + struct.pack("<II", len(blob), 0x004E4942) + bytes(blob)


def palette(rgb_lin, k, seed=1):
    import cv2
    data = rgb_lin.astype(np.float32)
    if len(data) > 400000:
        data = data[np.random.default_rng(seed).choice(len(data), 400000, replace=False)]
    crit = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 30, 1e-4)
    cv2.setRNGSeed(seed)
    _, _, cen = cv2.kmeans(data, k, None, crit, 3, cv2.KMEANS_PP_CENTERS)
    return cen[np.argsort(cen.sum(1))]


def tile_glb(D, idx, center, near, pal, protos_idx):
    import buildings_build as B
    R = B.enu_rot(*center)
    C0 = B.ecef(np.array(center[0]), np.array(center[1]), np.array(0.0)).reshape(3)
    lat, lon, base, h, r = D["lat"][idx], D["lon"][idx], D["base"][idx].astype(np.float64), D["h"][idx].astype(np.float64), D["r"][idx].astype(np.float64)
    E = (B.ecef(lat, lon, base) - C0) @ R                 # ENU m
    S = np.array([[1, 0, 0], [0, 0, 1], [0, -1, 0]], np.float64)
    Tl = E @ S.T                                           # glTF local (x = east, y = up, z = -north)
    yaw = D["yaw"][idx].astype(np.float64) * 2 * math.pi
    Rq = np.stack((np.zeros_like(yaw), np.sin(yaw / 2), np.zeros_like(yaw), np.cos(yaw / 2)), 1)
    hh = h + SINK
    Sc = np.stack((r, hh, r), 1)
    sp, var, bins = D["sp"][idx], D["var"][idx], D["bin"][idx]
    groups = []
    for s_ in (0, 1):
        for v_ in ((0, 1) if near else (0,)):
            for b_ in range(NBIN):
                m = (sp == s_) & (bins == b_) & ((var == v_) if near else True)
                if m.any():
                    groups.append((protos_idx[(s_, v_ if near else -1, b_)], Tl[m], Rq[m], Sc[m]))
    Z2Y = np.array([[1, 0, 0], [0, 0, 1], [0, -1, 0]], np.float64)
    Mx = np.eye(4)
    Mx[:3, :3] = Z2Y @ R @ S.T
    Mx[:3, 3] = Z2Y @ C0
    glb = glb_instanced(pal, groups, Mx)
    region = [math.radians(float(lon.min()) - 1e-5), math.radians(float(lat.min()) - 1e-5), math.radians(float(lon.max()) + 1e-5),
              math.radians(float(lat.max()) + 1e-5), float(base.min()), float((base + hh).max())]
    return glb, region


def tiles(args):
    import glob, shutil
    t0 = time.time()
    fs = sorted(glob.glob(os.path.join(WORK, "b_*.npz")))
    parts = {k: [] for k in ("lat", "lon", "h", "r", "sp", "rgb", "base", "var", "yaw", "lc")}
    for f in fs:
        z = np.load(f)
        if int(z["n"]) == 0:
            continue
        for k in parts:
            parts[k].append(z[k])
    D = {k: np.concatenate(v) for k, v in parts.items()}
    nt = len(D["lat"])
    print("trees: %d (%.0f s)" % (nt, time.time() - t0), flush=True)
    lin = srgb_to_lin(D["rgb"]) * GAIN
    lin = np.minimum(lin, 0.9)
    D["bin"] = np.zeros(nt, np.int8)
    pals = {}
    for s_ in (0, 1):
        m = D["sp"] == s_
        cen = palette(lin[m], NBIN, seed=7 + s_)
        d = ((lin[m][:, None, :] - cen[None]) ** 2).sum(-1)
        D["bin"][m] = d.argmin(1)
        pals[s_] = cen
    # prototypes: (species, var | -1 far, bin)
    protos, pidx = [], {}
    for s_, nm in ((0, "pine"), (1, "broad")):
        for b_ in range(NBIN):
            tint = pals[s_][b_]
            for v_ in (0, 1):
                pidx[(s_, v_, b_)] = len(protos)
                protos.append(proto(nm, v_).arrays(tint, None))
            pidx[(s_, -1, b_)] = len(protos)
            protos.append(proto(nm + "_far", 0).arrays(tint, None))
    tmp = TILES + "_tmp"
    if os.path.isdir(tmp):
        shutil.rmtree(tmp)
    os.makedirs(os.path.join(tmp, "b")); os.makedirs(os.path.join(tmp, "c"))
    bi = np.floor(D["lat"] / DLA).astype(np.int64); bj = np.floor(D["lon"] / DLO).astype(np.int64)
    ci = np.floor(D["lat"] / (DLA / SUB)).astype(np.int64); cj = np.floor(D["lon"] / (DLO / SUB)).astype(np.int64)
    order = np.lexsort((cj, ci, bj, bi))
    keyB = bi[order] * 100000 + bj[order]
    cuts = np.nonzero(np.diff(keyB))[0] + 1
    nodes_a, sizes, ntris = [], {}, dict(near=0, far=0)
    tri = [len(p[3]) // 3 for p in protos]

    def union(a, b):
        return [min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3]), min(a[4], b[4]), max(a[5], b[5])]
    for grp in np.split(order, cuts):
        i, j = int(bi[grp[0]]), int(bj[grp[0]])
        center = ((i + 0.5) * DLA, (j + 0.5) * DLO)
        glb, regB = tile_glb(D, grp, center, False, protos, pidx)
        fn = "b/%d_%d.glb" % (i, j)
        open(os.path.join(tmp, fn), "wb").write(glb)
        sizes[fn] = len(glb)
        ntris["far"] += int(sum(tri[pidx[(int(s), -1, int(b))]] for s, b in zip(D["sp"][grp], D["bin"][grp])))
        kids = []
        kc = ci[grp] * 100000 + cj[grp]
        o2 = np.argsort(kc, kind="stable")
        g2 = grp[o2]
        for sub in np.split(g2, np.nonzero(np.diff(kc[o2]))[0] + 1):
            a, b = int(ci[sub[0]]), int(cj[sub[0]])
            cc = ((a + 0.5) * DLA / SUB, (b + 0.5) * DLO / SUB)
            glb, reg = tile_glb(D, sub, cc, True, protos, pidx)
            fn = "c/%d_%d.glb" % (a, b)
            open(os.path.join(tmp, fn), "wb").write(glb)
            sizes[fn] = len(glb)
            ntris["near"] += int(sum(tri[pidx[(int(s), int(v), int(bb))]] for s, v, bb in zip(D["sp"][sub], D["var"][sub], D["bin"][sub])))
            kids.append(dict(boundingVolume=dict(region=reg), geometricError=GE["c"], content=dict(uri=fn)))
            regB = union(regB, reg)
        nodeB = dict(boundingVolume=dict(region=regB), geometricError=GE["b"], refine="REPLACE", content=dict(uri="b/%d_%d.glb" % (i, j)), children=kids)
        nodes_a.append(dict(boundingVolume=dict(region=regB), geometricError=GE["a"], refine="REPLACE", children=[nodeB],
                            extras=dict(trees=int(len(grp)))))
    reg = nodes_a[0]["boundingVolume"]["region"]
    for nd in nodes_a[1:]:
        reg = union(reg, nd["boundingVolume"]["region"])
    ts = dict(asset=dict(version="1.1", tilesetVersion=time.strftime("%Y%m%d%H%M%S"), generator="gyro-sim-chair sim/veg_build.py",
                         copyright="Meta/WRI canopy height (CC BY 4.0); ESA WorldCover 2021 (CC BY 4.0); © OpenStreetMap contributors (ODbL)"),
              geometricError=GE["root"] * 2, root=dict(boundingVolume=dict(region=reg), geometricError=GE["root"], refine="REPLACE", children=nodes_a))
    json.dump(ts, open(os.path.join(tmp, "tileset.json"), "w", encoding="utf-8"))
    out = dict(made=time.strftime("%Y-%m-%d %H:%M:%S"), seconds=round(time.time() - t0), trees=int(nt),
               pine=int((D["sp"] == 0).sum()), broad=int((D["sp"] == 1).sum()), h_mean=round(float(D["h"].mean()), 2),
               h_p90=round(float(np.percentile(D["h"], 90)), 1), r_mean=round(float(D["r"].mean()), 2),
               blocks=len(nodes_a), content_tiles=len(sizes), bytes=int(sum(sizes.values())), largest_tile=int(max(sizes.values())),
               triangles=ntris, gain=GAIN, palettes={("pine", "broad")[k]: v.round(4).tolist() for k, v in pals.items()},
               prototype_triangles=tri, ge=GE, inputs=dict(work=WORK))
    json.dump(out, open(os.path.join(tmp, "build.json"), "w"), indent=1)
    if os.path.isdir(TILES):
        shutil.rmtree(TILES)
    os.replace(tmp, TILES)
    print("done:", json.dumps({k: v for k, v in out.items() if k not in ("palettes",)}), flush=True)


def attrib():
    """the roads plate (V-World + building + OSM + Copernicus credits) + two tree-data lines in the same style."""
    from PIL import Image, ImageDraw, ImageFont
    src = os.path.join(HERE, "vworld_roads_attribution.png")
    if not os.path.isfile(src):
        src = os.path.join(HERE, "vworld_buildings_attribution.png")
    im = Image.open(src).convert("RGBA")
    W, H = im.size
    A = np.asarray(im)
    row = A[H // 2]
    x0 = int(np.nonzero(row[:, 3] > 128)[0].min())        # left edge of the dark plate (left of it is transparent)
    bg = tuple(int(v) for v in A[H // 2, W - 3])
    fs = max(11, H // 11)
    try:
        font = ImageFont.truetype(r"C:\Windows\Fonts\malgun.ttf", fs)
    except OSError:
        font = ImageFont.load_default()
    lines = ["나무: Meta/WRI 수관고 지도 (CC BY 4.0) · © OpenStreetMap contributors",
             "© ESA WorldCover project 2021 / Contains modified Copernicus Sentinel data (2021) processed by ESA WorldCover consortium"]
    dr = ImageDraw.Draw(im)
    tw = max(int(dr.textlength(t, font=font)) for t in lines) + 24
    x0 = min(x0, W - tw)
    lh = int(fs * 1.45)
    out = Image.new("RGBA", (W, H + 2 * lh + 6), (0, 0, 0, 0))
    ImageDraw.Draw(out).rectangle((x0, 0, W, H + 2 * lh + 6), fill=bg)
    out.alpha_composite(im)
    d = ImageDraw.Draw(out)
    cx = (x0 + W) / 2
    for k, t in enumerate(lines):
        w_ = d.textlength(t, font=font)
        d.text((cx - w_ / 2, H + k * lh - 4), t, font=font, fill=(235, 235, 235, 255))
    out.save(ATTRIB_PNG)
    print("plate", ATTRIB_PNG, out.size)


if __name__ == "__main__":
    a = sys.argv[1:]
    if "--fetch" in a:
        fetch()
    if "--prep" in a:
        prep(a)
    if "--tiles" in a:
        tiles(a)
    if "--attrib" in a:
        attrib()
