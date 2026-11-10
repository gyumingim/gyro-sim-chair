"""Busan coastline, piers / breakwaters and the sea photo mask, from OpenStreetMap (ODbL), for the Unreal 'vworld' mode.

The Copernicus DEM (30 m DSM) melts the shore into a soft one-cell ramp, piers / breakwaters are only painted on the
V-World sea photo, and the photo has the big bridges + their shadows baked onto the sea. This builds:

  --fetch    Overpass API, one request -> C:\\GyroSimTiles\\osm\\busan_coast.json (+ _manifest.json): natural=coastline,
             man_made=pier|breakwater|groyne|quay, natural=beach|cliff|bare_rock, port / industrial land, railway bridges.
             (Road bridges come from the roads cache busan_roads.json, roads_build.py.)
  --mask     C:\\GyroSimTiles\\coast\\coast_mask.png (8192 x 8192 RGBA, equirectangular over the Busan box) + coast_mask.json:
               R = signed distance to the OSM coastline (land +), +-MASK_D m      -> crisp sea / land edge in the material
               G = signed distance to the buffered bridge footprints (inside +)  -> sea photo replaced under the bridges
               B = distance from the shore over the sea, 0..FAR_D m              -> procedural sea far from shore (no seams)
               A = coast class near the shore: 0 natural (rock / cliff), 0.5 beach, 1 man-made (sea wall / quay)
             Render-time data only: the V-World photo is never modified or stored (terms: no modified copies).
             Imported as /Game/Materials/Ground/T_GyroCoast by unreal/GyroSim/Scripts/ground_material.py.
  --terrain  coast-aware terrain tiles (levels 13-16 over the Busan box) into a NEW folder C:\\GyroSimTiles\\terrain\\tiles_coast
             (a copy of tiles/ with those tiles re-encoded): sea vertices (OSM) = 0 m MSL, man-made shore = sea wall top
             WALL_H m right to the waterline, beaches = gentle BEACH_SLOPE slope, natural shore = the DEM (cliffs kept);
             level-16 tiles on the shore get 129 x 129 vertices (~2 m) so a sea wall is a near-vertical step.
             --swap afterwards (only while no UnrealEditor runs): tiles -> tiles_prev, tiles_coast -> tiles.
  --piers    3D Tiles (glb) C:\\GyroSimTiles\\piers\\tiles\\tileset.json: piers / breakwaters / groynes extruded (concrete deck,
             tetrapod-grey rubble slopes on breakwaters), vertical quay faces on the man-made port shore.
             Loaded at Play by unreal/GyroSim/Content/Python/piers_look.py (GYROSIM_PIERS=0 = off).

Run with `python -I` (the inputs are downloads). Heights not in OSM are 추정 (WALL_H, PIER_H, BREAKWATER_H).
"""
import json, math, os, sys, time, site
if sys.flags.isolated:
    site.addsitedir(site.getusersitepackages())
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import numpy as np                                        # noqa: E402

OSM_DIR = os.environ.get("GYROSIM_OSM", r"C:\GyroSimTiles\osm")
OSM_FILE = os.path.join(OSM_DIR, "busan_coast.json")
ROADS_OSM = os.path.join(OSM_DIR, "busan_roads.json")
ROOT = os.environ.get("GYROSIM_COAST", r"C:\GyroSimTiles\coast")
PIERS = os.environ.get("GYROSIM_PIERS_TILES", r"C:\GyroSimTiles\piers\tiles")
BOX = (34.96, 128.75, 35.40, 129.33)                      # S W N E = terrain_dem.HIRES busan
OVERPASS = "https://overpass-api.de/api/interpreter"
UA = "gyro-sim-chair coast_build.py (personal flight sim; one request per manual run)"
ATTRIB = "해안선·방파제: © OpenStreetMap contributors (ODbL)"

MASK_N = 8192
MASK_D, BRIDGE_D, FAR_D = 40.0, 40.0, 1000.0              # m, encoding ranges of R / G / B
WALL_H = 2.8                                              # m MSL, sea wall / quay crown (추정: Busan quays ~ +3.0..4.0 m DL, MSL ~ +0.6..0.8 m DL)
BEACH_SLOPE, BEACH_TOE, BEACH_MAX, BEACH_BAND = 0.045, 0.3, 3.5, 150.0   # beach face 4.5 % from 0.3 m at the waterline, up to 3.5 m (추정)
ISLET_SD, ISLET_H = 20.0, 3.0                             # m: sea vertices kept as DEM (islets missing in OSM), see coast_msl
SHORE_BAND = 60.0                                         # m inland where the shore rule acts (blend to the DEM over the last 30 m)


# ---- fetch ----------------------------------------------------------------------------------------------------------
def query():
    s, w, n, e = BOX
    bb = "(%g,%g,%g,%g)" % (s, w, n, e)
    parts = ['way["natural"="coastline"]', 'way["man_made"~"^(pier|breakwater|groyne|quay)$"]',
             'relation["man_made"~"^(pier|breakwater|groyne|quay)$"]', 'way["natural"~"^(beach|cliff|bare_rock|sand)$"]',
             'relation["natural"~"^(beach|bare_rock|sand)$"]', 'way["landuse"~"^(industrial|port|harbour)$"]',
             'relation["landuse"~"^(industrial|port|harbour)$"]', 'way["railway"]["bridge"]["bridge"!="no"]']
    return "[out:json][timeout:300];\n(\n" + "".join(" %s%s;\n" % (p, bb) for p in parts) + ");\nout geom;\n"


def fetch():
    import urllib.request, urllib.parse
    os.makedirs(OSM_DIR, exist_ok=True)
    q = query()
    t0 = time.time()
    req = urllib.request.Request(OVERPASS, data=urllib.parse.urlencode({"data": q}).encode(), headers={"User-Agent": UA})
    b = urllib.request.urlopen(req, timeout=400).read()
    d = json.loads(b)
    tmp = OSM_FILE + ".part"
    with open(tmp, "wb") as f:
        f.write(b)
    os.replace(tmp, OSM_FILE)
    man = dict(made=time.strftime("%Y-%m-%d %H:%M:%S"), url=OVERPASS, query=q, bytes=len(b), seconds=round(time.time() - t0, 1),
               osm_base=d.get("osm3s", {}).get("timestamp_osm_base"), licence="ODbL, © OpenStreetMap contributors", elements=len(d["elements"]))
    with open(OSM_FILE[:-5] + "_manifest.json", "w", encoding="utf-8") as f:
        json.dump(man, f, indent=1, ensure_ascii=False)
    print("fetched %d elements, %.1f MB, %.0f s -> %s" % (man["elements"], len(b) / 1e6, man["seconds"], OSM_FILE))


# ---- geometry (planar metres = roads_build.xy: equirectangular at 35.15 N, 129.05 E) ----------------------------------
def _xy(lat, lon):
    import roads_build as R
    return R.xy(lat, lon)


def _pts(e):
    g = e.get("geometry") or []
    if not g or any(p is None for p in g):
        return None
    x, y = _xy(np.array([p["lat"] for p in g]), np.array([p["lon"] for p in g]))
    return np.stack((x, y), 1)


def _rel_polys(e):
    """multipolygon relation (out geom) -> shapely polygons (outer rings, holes ignored)."""
    import shapely
    from shapely.ops import linemerge, polygonize
    lines = []
    for m in e.get("members", []):
        if m.get("type") == "way" and m.get("role", "outer") in ("outer", "") and m.get("geometry"):
            g = m["geometry"]
            if any(p is None for p in g):
                continue
            x, y = _xy(np.array([p["lat"] for p in g]), np.array([p["lon"] for p in g]))
            if len(x) >= 2:
                lines.append(shapely.LineString(np.stack((x, y), 1)))
    if not lines:
        return []
    return [p for p in polygonize(linemerge(lines)) if p.area > 1.0]


def load():
    """-> dict of shapely geometries in planar metres + osm_base."""
    import shapely
    d = json.load(open(OSM_FILE, encoding="utf-8"))
    out = dict(coast=[], beach=[], natural=[], port=[], piers=[], railbridges=[])
    for e in d["elements"]:
        t = e.get("tags", {})
        if e["type"] == "relation":
            polys = _rel_polys(e)
            if t.get("natural") in ("beach", "sand"):
                out["beach"] += polys
            elif t.get("natural") == "bare_rock":
                out["natural"] += polys
            elif t.get("landuse") in ("industrial", "port", "harbour"):
                out["port"] += polys
            elif t.get("man_made") in ("pier", "breakwater", "groyne", "quay"):
                for p in polys:
                    out["piers"].append(dict(kind=t["man_made"], geom=p, area=True, tags=t, id=e["id"]))
            continue
        P = _pts(e)
        if P is None or len(P) < 2:
            continue
        closed = len(P) >= 4 and np.allclose(P[0], P[-1])
        if t.get("natural") == "coastline":
            out["coast"].append(shapely.LineString(P))
        elif t.get("natural") in ("beach", "sand") and closed:
            out["beach"].append(shapely.Polygon(P).buffer(0))
        elif t.get("natural") in ("cliff", "bare_rock"):
            out["natural"].append(shapely.Polygon(P).buffer(0) if closed and t["natural"] == "bare_rock" else shapely.LineString(P))
        elif t.get("landuse") in ("industrial", "port", "harbour") and closed:
            out["port"].append(shapely.Polygon(P).buffer(0))
        elif t.get("man_made") in ("pier", "breakwater", "groyne", "quay"):
            area = closed and t.get("area", "yes" if t["man_made"] in ("pier", "breakwater") else "no") != "no"
            out["piers"].append(dict(kind=t["man_made"], geom=shapely.Polygon(P).buffer(0) if area else shapely.LineString(P),
                                     area=area, tags=t, id=e["id"]))
        elif t.get("railway") and t.get("bridge", "no") != "no" and t["railway"] not in ("abandoned", "construction", "proposed"):
            out["railbridges"].append(shapely.LineString(P))
    return out, d.get("osm3s", {}).get("timestamp_osm_base")


def box_poly():
    import shapely
    s, w, n, e = BOX
    x0, y0 = _xy(s, w)
    x1, y1 = _xy(n, e)
    return shapely.box(float(x0), float(y0), float(x1), float(y1))


def land_polygons(coast):
    """OSM coastline ways (land on the left) -> land (multi)polygon clipped to the Busan box. The ways are noded with the
    box outline and polygonized; every face votes land / sea by which side of the coastline segments on its border it is."""
    import shapely
    from shapely.ops import polygonize, unary_union
    B = box_poly()
    lines = [l for l in coast if l.intersects(B)]
    noded = unary_union(lines + [B.exterior])
    faces = [f for f in polygonize(noded) if B.contains(f.representative_point())]
    tree = shapely.STRtree(faces)
    votes = np.zeros((len(faces), 2))
    for l in lines:
        c = np.asarray(l.coords)
        a, b = c[:-1], c[1:]
        d = b - a
        L = np.hypot(d[:, 0], d[:, 1])
        ok = L > 0.5
        a, d, L = a[ok], d[ok], L[ok]
        mid = a + d * 0.5
        nrm = np.stack((-d[:, 1], d[:, 0]), 1) / L[:, None]         # left normal
        eps = np.minimum(0.25 * L, 0.5)[:, None]
        for side, sgn in ((0, 1.0), (1, -1.0)):
            pts = shapely.points(mid + sgn * eps * nrm)
            ip, iface = tree.query(pts, predicate="within")
            np.add.at(votes[:, side], iface, L[ip])
    land = [f for f, v in zip(faces, votes) if v[0] > v[1]]
    nov = sum(1 for v in votes if v.sum() == 0)
    print("coastline: %d ways, %d faces, %d land, %d without votes (sea)" % (len(lines), len(faces), len(land), nov), flush=True)
    return unary_union(land)


def grid():
    """mask grid: MASK_N x MASK_N pixel centres over the box (row 0 = north), planar metres."""
    s, w, n, e = BOX
    lon = w + (np.arange(MASK_N) + 0.5) * (e - w) / MASK_N
    lat = n - (np.arange(MASK_N) + 0.5) * (n - s) / MASK_N
    x, _ = _xy(lat[0], lon)
    _, y = _xy(lat, lon[0])
    return lat, lon, np.asarray(x, np.float64), np.asarray(y, np.float64)


def _raster(geoms, x, y):
    """polygons -> bool raster (pixel centres) on the grid x (cols), y (rows, north first)."""
    import rasterio.features, rasterio.transform
    dx, dy = x[1] - x[0], y[0] - y[1]
    tr = rasterio.transform.from_origin(x[0] - dx / 2, y[0] + dy / 2, dx, dy)
    shapes = [(g, 1) for g in (geoms if isinstance(geoms, list) else [geoms]) if not g.is_empty]
    if not shapes:
        return np.zeros((len(y), len(x)), bool)
    return rasterio.features.rasterize(shapes, out_shape=(len(y), len(x)), transform=tr, dtype=np.uint8, all_touched=False).astype(bool)


def _segments(geoms):
    """all straight segments of the boundaries / lines -> (a, b) arrays + owner index."""
    import shapely
    A, Bs, own = [], [], []
    for k, g in enumerate(geoms):
        for part in shapely.get_parts(g):
            rings = [part.exterior] + list(part.interiors) if part.geom_type == "Polygon" else [part]
            for r in rings:
                c = np.asarray(r.coords)
                if len(c) >= 2:
                    A.append(c[:-1]); Bs.append(c[1:]); own.append(np.full(len(c) - 1, k))
    return np.concatenate(A), np.concatenate(Bs), np.concatenate(own)


def _exact_dist(a, b, P):
    """distance of points P (n, 2) to the nearest segment (a, b), via an STRtree of the segments."""
    import shapely
    segs = shapely.linestrings(np.stack((a, b), 1))
    tree = shapely.STRtree(segs)
    out = np.empty(len(P))
    idx = np.empty(len(P), np.int64)
    CH = 400000
    for i in range(0, len(P), CH):
        pts = shapely.points(P[i:i + CH])
        ip, ig = tree.query_nearest(pts, all_matches=False)
        o = np.argsort(ip)
        ip, ig = ip[o], ig[o]
        q = P[i:i + CH][ip]
        aa, bb = a[ig], b[ig]
        d = bb - aa
        t = np.clip(((q - aa) * d).sum(1) / np.maximum((d * d).sum(1), 1e-12), 0, 1)
        out[i + ip] = np.hypot(*(q - (aa + d * t[:, None])).T)
        idx[i + ip] = ig
    return out, idx


def signed_field(inside, geoms, x, y, band):
    """signed distance (inside +) on the grid: exact (to the segments) within `band` m of the edge, EDT beyond."""
    from scipy import ndimage as nd
    dx, dy = x[1] - x[0], y[0] - y[1]
    din = nd.distance_transform_edt(inside, sampling=(dy, dx))
    dout = nd.distance_transform_edt(~inside, sampling=(dy, dx))
    sd = np.where(inside, din, -dout).astype(np.float32)
    near = np.abs(sd) <= band
    r, c = np.nonzero(near)
    seg_owner = None
    if len(r):
        a, b, own = _segments(geoms)
        dist, ig = _exact_dist(a, b, np.stack((x[c], y[r]), 1))
        sd[r, c] = np.where(inside[r, c], dist, -dist)
        seg_owner = (r, c, ig, a, b, own)
    return sd, seg_owner


def coast_class(land, data, a, b):
    """class per coastline segment: 0 natural (rock / cliff / wild shore: DEM kept), 0.5 beach, 1 man-made (sea wall / quay).
    Man-made = within 30 m of port / industrial land or a pier / quay, or a GIS building within 40 m inland; beach = within
    25 m of natural=beach|sand; natural = within 30 m of natural=cliff|bare_rock, else no man-made sign (DEM kept)."""
    import shapely
    mid = (a + b) / 2
    d = b - a
    L = np.maximum(np.hypot(d[:, 0], d[:, 1]), 1e-6)
    nrm = np.stack((-d[:, 1], d[:, 0]), 1) / L[:, None]
    inland = shapely.points(mid + 20.0 * nrm)                         # left = land side of the coastline
    pm = shapely.points(mid)

    def near(geoms, pts, r):
        if not geoms:
            return np.zeros(len(pts), bool)
        t = shapely.STRtree(geoms)
        ip, _ = t.query(pts, predicate="dwithin", distance=r)
        m = np.zeros(len(pts), bool)
        m[ip] = True
        return m
    beach = near(data["beach"], pm, 25.0)
    rock = near(data["natural"], pm, 30.0)
    port = near(data["port"], pm, 30.0) | near([p["geom"] for p in data["piers"]], pm, 30.0)
    bld = near(gis_buildings(mid), inland, 80.0)
    import terrain_dem as T
    import roads_build as R
    dem = T.Dem()
    hs = []
    for r in (30.0, 70.0):
        la, lo = R.latlon(*(mid + r * nrm).T)
        hs.append(np.asarray(dem.msl(la, lo), float))
    steep = (hs[0] > 9.0) | (hs[1] > 12.0)                          # cliff / hill right behind the shore (DSM: no buildings near)
    cls = np.where(beach, 0.5, np.where(rock & ~port, 0.0, np.where(port | bld | ~steep, 1.0, 0.0)))
    print("coast segments: %d, beach %.0f km, man-made %.0f km, natural %.0f km" % (
        len(a), L[cls == 0.5].sum() / 1e3, L[cls == 1].sum() / 1e3, L[cls == 0].sum() / 1e3), flush=True)
    return cls


def gis_buildings(pts):
    """GIS building footprints (AL_D010 Busan, terrain_coastfix.ZIP) near the given planar points, as planar polygons."""
    import zipfile, pyogrio, shapely
    from pyproj import Transformer
    import terrain_coastfix as CF
    import roads_build as R
    la, lo = R.latlon(pts[:, 0], pts[:, 1])
    tf = Transformer.from_crs("EPSG:4326", "EPSG:5186", always_xy=True)
    X, Y = tf.transform(lo, la)
    bb = (float(np.min(X)) - 200, float(np.min(Y)) - 200, float(np.max(X)) + 200, float(np.max(Y)) + 200)
    shps = ["/vsizip/%s/%s" % (CF.ZIP.replace("\\", "/"), m) for m in zipfile.ZipFile(CF.ZIP).namelist() if m.lower().endswith(".shp")]
    geoms = []
    back = Transformer.from_crs("EPSG:5186", "EPSG:4326", always_xy=True)
    for sp in shps:
        df = pyogrio.read_dataframe(sp, encoding="cp949", columns=["A1"], bbox=bb)
        for g in df.geometry.values:
            if g is None:
                continue
            c = g.centroid
            lo2, la2 = back.transform(c.x, c.y)
            x, y = R.xy(la2, lo2)
            r = math.sqrt(max(g.area, 1.0) / math.pi)
            geoms.append(shapely.Point(float(x), float(y)).buffer(r, 6))
    # only the ones near the coast matter: keep those within 100 m of a query point
    t = shapely.STRtree(geoms)
    ip, ig = t.query(shapely.points(pts), predicate="dwithin", distance=100.0)
    keep = sorted(set(ig.tolist()))
    print("GIS buildings near the coast: %d (of %d in the box)" % (len(keep), len(geoms)), flush=True)
    return [geoms[i] for i in keep]


BIG_DECK = {"광안대교": 46.0, "부산항대교": 65.0, "남항대교": 30.0}       # m, for the shadow reach (roads_build.BIG, 추정)


def _swept(line, r, shift):
    """line buffered by r, swept north by `shift` m (union of shifted copies every <= 8 m)."""
    import shapely
    from shapely.ops import unary_union
    g = line.buffer(r, cap_style="flat")
    k = max(1, int(math.ceil(shift / 8.0)))
    return unary_union([shapely.affinity.translate(g, 0.0, shift * i / k) for i in range(k + 1)]).buffer(0)


def bridge_polys(data):
    """road (roads cache) + railway bridges over the sea -> footprints buffered by half the width + 18 m (orthophoto
    lean / blur), unioned with a copy shifted toward the photo's shadow side (north, 0.9 x deck height; the V-World photos
    are shot around midday) -> polygons to mask out of the sea photo."""
    import shapely
    import roads_build as R
    from shapely.ops import unary_union
    nodes, elev, _, _ = R.load()
    out = []
    for w in elev:
        t = w.get("tags", {})
        if t.get("bridge", "no") == "no":
            continue
        P = np.array([R.xy(*nodes[n]) for n in w["nodes"]], float)
        if len(P) < 2:
            continue
        line = shapely.LineString(P)
        if line.length < 60:
            continue
        wd, _ = R.way_width(t)
        name = (t.get("bridge:name") or t.get("name") or "")
        deck = next((v for k, v in BIG_DECK.items() if k in name), 18.0 if line.length > 300 else 10.0)
        out.append(_swept(line, wd / 2 + 18.0, 0.9 * deck))
    for l in data["railbridges"]:
        if l.length >= 60:
            out.append(_swept(l, 6.0 + 18.0, 12.0))
    return [g for g in out if not g.is_empty]


def mask():
    import shapely
    from shapely.ops import unary_union
    from PIL import Image
    from scipy import ndimage as nd
    t0 = time.time()
    os.makedirs(ROOT, exist_ok=True)
    data, osm_base = load()
    land = land_polygons(data["coast"])
    bp = bridge_polys(data)
    # small islets inside the bridge masks = the bridge piers / tower footings painted in the photo (white rectangles under
    # the 광안대교): sea in the mask (the 3D bridge has its own piers), not land
    from shapely.ops import unary_union
    bu = unary_union(bp)
    parts = list(shapely.get_parts(land))
    drop = [p for p in parts if p.area < 20000.0 and p.intersection(bu).area > 0.5 * p.area]
    land = shapely.orient_polygons(unary_union([p for p in parts if not any(p is q for q in drop)]), exterior_cw=False)
    # (counter-clockwise exteriors, clockwise holes: the land is LEFT of every boundary segment - coast_class relies on it)
    print("islets inside bridge masks -> sea: %d (%.0f m2)" % (len(drop), sum(p.area for p in drop)), flush=True)
    lat, lon, x, y = grid()
    print("grid %d px: %.2f x %.2f m" % (MASK_N, x[1] - x[0], y[0] - y[1]), flush=True)
    inside = _raster(land, x, y)
    sd, own = signed_field(inside, [land], x, y, 64.0)
    print("coast field %.0f s, land %.1f %%" % (time.time() - t0, 100 * inside.mean()), flush=True)
    # class per coastline segment, spread to every pixel near the shore (the nearest segment's class)
    r, c, ig, a, b, _ = own
    cls_seg = coast_class(land, data, a, b)
    cls = np.zeros(sd.shape, np.float32)
    cls[r, c] = cls_seg[ig]
    # beyond the exact band: nearest band pixel's class (EDT index trick)
    band = np.zeros(sd.shape, bool)
    band[r, c] = True
    _, (ri, ci) = nd.distance_transform_edt(~band, return_indices=True)
    cls = cls[ri, ci]
    del ri, ci
    # bridges
    binside = _raster(bp, x, y)
    bsd, _ = signed_field(binside, bp, x, y, 48.0) if binside.any() else (np.full(sd.shape, -1e3, np.float32), None)
    print("bridge mask: %d footprints, %.2f km2" % (len(bp), binside.sum() * (x[1] - x[0]) * (y[0] - y[1]) / 1e6), flush=True)
    far = np.where(inside, 0.0, -sd).astype(np.float32)
    enc = lambda v, D: np.clip(np.round((v / (2 * D) + 0.5) * 255), 0, 255).astype(np.uint8)
    img = np.stack((enc(sd, MASK_D), enc(bsd, BRIDGE_D), np.clip(np.round(far / FAR_D * 255), 0, 255).astype(np.uint8),
                    np.clip(np.round(cls * 255), 0, 255).astype(np.uint8)), -1)
    Image.fromarray(img, "RGBA").save(os.path.join(ROOT, "coast_mask.png"), optimize=False)
    np.savez_compressed(os.path.join(ROOT, "coast_field.npz"), sd=sd, cls=cls.astype(np.float16), lat=lat, lon=lon, seg_a=a, seg_b=b, seg_cls=cls_seg)
    # world-independent description: the material maps world -> (lon, lat) -> UV with an affine fit at Play (coast_look.py)
    info = dict(made=time.strftime("%Y-%m-%d %H:%M:%S"), seconds=round(time.time() - t0), input=dict(osm=OSM_FILE, osm_base=osm_base, roads=ROADS_OSM,
                buildings=os.path.basename(__import__("terrain_coastfix").ZIP)), box_swne=list(BOX), size=MASK_N,
                encoding=dict(R="signed distance to the coastline (land +), v = d / (2 x %g) + 0.5" % MASK_D,
                              G="signed distance to the bridge masks (inside +), v = d / (2 x %g) + 0.5" % BRIDGE_D,
                              B="sea distance from the shore, v = d / %g" % FAR_D, A="coast class 0 natural, 0.5 beach, 1 man-made"),
                mask_d=MASK_D, bridge_d=BRIDGE_D, far_d=FAR_D, land_frac=float(inside.mean()), bridges=len(bp),
                pixel_m=[float(x[1] - x[0]), float(y[0] - y[1])], licence="© OpenStreetMap contributors (ODbL)")
    with open(os.path.join(ROOT, "coast_mask.json"), "w", encoding="utf-8") as f:
        json.dump(info, f, indent=1, ensure_ascii=False)
    with open(os.path.join(ROOT, "land.wkb"), "wb") as f:
        f.write(shapely.to_wkb(land))
    print("mask done %.0f s -> %s" % (time.time() - t0, ROOT), flush=True)


# ---- coast-aware terrain tiles ------------------------------------------------------------------------------------------
NEW_TILES = os.environ.get("GYROSIM_COAST_TILES", r"C:\GyroSimTiles\terrain\tiles_coast_new")
COAST_LEVELS = (13, 14, 15, 16)
FINE_N = 129                                              # level-16 tiles that hold a coastline: ~2 m vertex spacing
_F = {}


def _field():
    """(sd float32 [N, N] memory-mapped, cls float16 [N, N]) of --mask, saved as .npy beside the npz on first use."""
    if "sd" not in _F:
        p_sd, p_cl = os.path.join(ROOT, "coast_sd.npy"), os.path.join(ROOT, "coast_cls.npy")
        npz = os.path.join(ROOT, "coast_field.npz")
        if not os.path.exists(p_sd) or os.path.getmtime(p_sd) < os.path.getmtime(npz):
            z = np.load(npz)
            np.save(p_sd, z["sd"].astype(np.float32))
            np.save(p_cl, z["cls"].astype(np.float16))
        _F["sd"] = np.load(p_sd, mmap_mode="r")
        _F["cls"] = np.load(p_cl, mmap_mode="r")
    return _F["sd"], _F["cls"]


def field_at(lat, lon):
    """signed coast distance (m, land +; bilinear) and class (nearest) at lat / lon; outside the box: (+1e4, 1)."""
    sd, cls = _field()
    s, w, n, e = BOX
    fr = (n - lat) / (n - s) * MASK_N - 0.5
    fc = (lon - w) / (e - w) * MASK_N - 0.5
    ok = (fr >= 0) & (fr < MASK_N - 1) & (fc >= 0) & (fc < MASK_N - 1)
    r0 = np.clip(np.floor(fr).astype(np.int64), 0, MASK_N - 2)
    c0 = np.clip(np.floor(fc).astype(np.int64), 0, MASK_N - 2)
    tr, tc = np.clip(fr - r0, 0, 1), np.clip(fc - c0, 0, 1)
    v = ((sd[r0, c0] * (1 - tc) + sd[r0, c0 + 1] * tc) * (1 - tr) + (sd[r0 + 1, c0] * (1 - tc) + sd[r0 + 1, c0 + 1] * tc) * tr)
    k = np.asarray(cls[np.clip(np.round(fr).astype(np.int64), 0, MASK_N - 1), np.clip(np.round(fc).astype(np.int64), 0, MASK_N - 1)], np.float32)
    return np.where(ok, v, 1e4), np.where(ok, k, 1.0)


def coast_msl(msl, sd, k):
    """the shore rule on DEM heights (m MSL): sea (OSM) = 0; land within SHORE_BAND of the coastline: man-made = at least the
    sea wall top WALL_H, beach = at least BEACH_TOE + BEACH_SLOPE x distance (<= BEACH_MAX, band BEACH_BAND), natural = the
    DEM, at least 1 m; blended back to the DEM over the last 30 m of the band."""
    band = np.where((k > 0.25) & (k < 0.75), BEACH_BAND, SHORE_BAND)
    w = np.where(sd < band - 30.0, 1.0, 0.5 + 0.5 * np.cos(np.pi * np.clip((sd - band + 30.0) / 30.0, 0, 1)))
    wall = np.maximum(msl, WALL_H)
    # the DSM has many beaches flattened to the 0 m sea for tens of metres inland: the beach line rises from the toe,
    # the DEM wins where it is higher (promenade, dunes)
    beach = np.maximum(msl, np.minimum(BEACH_TOE + BEACH_SLOPE * np.maximum(sd, 0.0), BEACH_MAX))
    nat = np.maximum(msl, 1.0)
    tgt = np.where(k > 0.75, wall, np.where(k > 0.25, beach, nat))
    land = msl + w * (tgt - msl)
    # OSM sea = 0 m (the DSM smear of the shore, ships, painted piers), except DEM land more than ISLET_SD m out at sea and
    # higher than ISLET_H m: an islet / rock OSM has no coastline for (e.g. 생도 off 태종대, 40 m) - kept as the DEM
    islet = (sd < -ISLET_SD) & (msl > ISLET_H)
    return np.where(sd < 0.0, np.where(islet, msl, 0.0), land)


def rendered_msl(dem, lat, lon):
    """for the bakers (trees / buildings / roads / ships / traffic): the coast rule applied to DEM heights at lat / lon, i.e. the
    MSL height of the swapped-in coast-aware terrain (levels 13-16) up to its own mesh interpolation (~2 m vertices on the
    level-16 shore tiles). Outside the Busan box = dem.msl."""
    lat, lon = np.asarray(lat, np.float64), np.asarray(lon, np.float64)
    msl = np.asarray(dem.msl(lat, lon), np.float64)
    sd, k = field_at(lat, lon)
    s, w, n, e = BOX
    inb = (lat >= s) & (lat <= n) & (lon >= w) & (lon <= e)
    return np.where(inb, coast_msl(msl, sd, k), msl)


def _coast_tile_heights(dem, L, x, y, n):
    import terrain_build as B
    LA, LO, h = _ORIG_TH(dem, L, x, y, n)
    s, w_, nn, e = BOX
    inb = (LA >= s) & (LA <= nn) & (LO >= w_) & (LO <= e)
    if not inb.any():
        return LA, LO, h
    msl = dem.msl(LA, LO)
    sd, k = field_at(LA, LO)
    new = np.where(inb, coast_msl(msl, sd, k), msl)
    return LA, LO, h + (new - msl)


_ORIG_TH = None


def _coast_job(job):
    import terrain_build as B
    global _ORIG_TH
    if _ORIG_TH is None:
        _ORIG_TH = B.tile_heights
        B.tile_heights = _coast_tile_heights
    import terrain_dem as T
    dem = _F.get("dem") or _F.setdefault("dem", T.Dem())
    L, x, y, n = job
    w, s, e, nn = B.tile_rect(L, x, y)
    # does the rule change this tile? (probe on its own vertex grid, the n of the plan)
    LA, LO, h0 = _ORIG_TH(dem, L, x, y, n)
    msl = dem.msl(LA, LO)
    sd, k = field_at(LA, LO)
    s_, w_, n_, e_ = BOX
    inb = (LA >= s_) & (LA <= n_) & (LO >= w_) & (LO <= e_)
    if not inb.any():
        return None
    dh = np.abs(np.where(inb, coast_msl(msl, sd, k), msl) - msl)
    if dh.max() < 0.05:
        return None
    nf = FINE_N if (L == 16 and (sd[inb] < 0).any() and (sd[inb] > 0).any()) else n
    data, hmin, hmax = B.encode_tile(dem, L, x, y, nf)
    p = os.path.join(NEW_TILES, str(L), str(x), "%d.terrain" % y)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "wb") as f:
        f.write(data)
    return L, x, y, nf, round(float(dh.max()), 2), len(data)


def terrain():
    import multiprocessing as mp
    import terrain_build as B
    t0 = time.time()
    _field()
    plan = B.plan_tiles()
    s, w, n, e = BOX
    jobs = []
    for L in COAST_LEVELS:
        for x, y, nv in plan.get(L, []):
            tw, ts, te, tn = B.tile_rect(L, x, y)
            if te < w or tw > e or tn < s or ts > n:
                continue
            jobs.append((L, x, y, nv))
    if os.path.isdir(NEW_TILES):
        import shutil
        shutil.rmtree(NEW_TILES)
    os.makedirs(NEW_TILES)
    print("coast terrain: %d candidate tiles (levels %s)" % (len(jobs), COAST_LEVELS), flush=True)
    done = []
    with mp.Pool(max(1, min(10, (os.cpu_count() or 4) - 2))) as pool:
        for i, r in enumerate(pool.imap_unordered(_coast_job, jobs, chunksize=32)):
            if r:
                done.append(r)
            if (i + 1) % 5000 == 0:
                print("  %d / %d checked, %d re-encoded, %.0f s" % (i + 1, len(jobs), len(done), time.time() - t0), flush=True)
    by = {}
    for L, x, y, nf, dh, nb in done:
        b = by.setdefault(L, dict(tiles=0, fine=0, bytes=0))
        b["tiles"] += 1; b["fine"] += nf == FINE_N; b["bytes"] += nb
    info = dict(made=time.strftime("%Y-%m-%d %H:%M:%S"), seconds=round(time.time() - t0), levels=list(COAST_LEVELS), per_level=by,
                rule=dict(wall_h=WALL_H, beach_slope=BEACH_SLOPE, beach_toe=BEACH_TOE, beach_max=BEACH_MAX, beach_band=BEACH_BAND, shore_band=SHORE_BAND, fine_n=FINE_N, islet_sd=ISLET_SD, islet_h=ISLET_H),
                input=dict(mask=json.load(open(os.path.join(ROOT, "coast_mask.json"), encoding="utf-8"))["made"], proc=__import__("terrain_dem").PROC),
                tiles=[list(r[:4]) for r in done])
    with open(os.path.join(NEW_TILES, "coast_tiles.json"), "w", encoding="utf-8") as f:
        json.dump(info, f)
    print("coast terrain done: %s, %.0f s -> %s" % (by, time.time() - t0, NEW_TILES), flush=True)


# ---- piers / breakwaters / quay faces (3D Tiles) -----------------------------------------------------------------------
# heights m MSL (추정, not in OSM): deck / crown tops; sides go down to SIDE_Z (under the 0 m sea surface)
TOP = dict(pier=2.5, breakwater=4.5, groyne=2.2, quay=2.8)
WIDTH = dict(pier=6.0, breakwater=10.0, groyne=5.0)       # m, line ways without a width tag (가정)
SIDE_Z = -1.5
C_DECK = (0.66, 0.65, 0.62)                               # weathered concrete
C_SIDE = (0.55, 0.55, 0.53)
C_WET = (0.30, 0.31, 0.29)                                # wet / algae band at the waterline
C_TETRA = (0.60, 0.60, 0.58)                              # tetrapod armour (grey-white concrete, mottled per quad)
WET_TOP = 0.5


def _tris(poly):
    import shapely
    t = shapely.constrained_delaunay_triangles(poly)
    return [np.asarray(g.exterior.coords)[:3] for g in shapely.get_parts(t)]


def _extrude(M, poly, z0, z1, col_top, col_side, rng, mottle=0.0, wet=True):
    """vertical prism of a planar polygon: sides z0..z1 (wet band at the bottom), triangulated top."""
    import shapely
    for part in shapely.get_parts(poly):
        if part.is_empty or part.area < 2.0:
            continue
        part = shapely.orient_polygons(part, exterior_cw=False)
        rings = [np.asarray(part.exterior.coords)] + [np.asarray(r.coords) for r in part.interiors]
        for c in rings:
            for (x0, y0), (x1, y1) in zip(c[:-1], c[1:]):
                L = math.hypot(x1 - x0, y1 - y0)
                if L < 0.05:
                    continue
                out = (y1 - y0, -(x1 - x0), 0.0)               # right of a CCW exterior = outside
                bands = ((z0, WET_TOP, C_WET), (WET_TOP, z1, col_side)) if wet and z1 > WET_TOP + 0.2 else ((z0, z1, col_side),)
                for za, zb, col in bands:
                    f = 1.0 + mottle * rng.standard_normal()
                    M.quad(1, [(x0, y0, za), (x1, y1, za), (x1, y1, zb), (x0, y0, zb)], tuple(np.clip(np.array(col) * f, 0, 1)),
                           [(0, za / 4), (L / 4, za / 4), (L / 4, zb / 4), (0, zb / 4)], out)
        for t in _tris(part):
            f = 1.0 + mottle * rng.standard_normal()
            P = [(t[0][0], t[0][1], z1), (t[1][0], t[1][1], z1), (t[2][0], t[2][1], z1), (t[2][0], t[2][1], z1)]
            M.quad(1, P, tuple(np.clip(np.array(col_top) * f, 0, 1)), [(p[0] / 4, p[1] / 4) for p in P], (0, 0, 1))


def piers():
    import shapely
    from shapely.ops import unary_union
    import roads_build as R
    import terrain_dem as T
    t0 = time.time()
    data, osm_base = load()
    land = shapely.from_wkb(open(os.path.join(ROOT, "land.wkb"), "rb").read())
    land_in = land.buffer(-3.0)
    shapely.prepare(land)
    rng = np.random.default_rng(11)
    dem = T.Dem()
    items, stat = [], dict(pier=0, breakwater=0, groyne=0, quay=0, skipped_on_land=0, quay_faces_km=0.0)
    for p in data["piers"]:
        k, g, t = p["kind"], p["geom"], p["tags"]
        if g.geom_type == "LineString":
            if k == "quay":
                continue                                   # quay lines = the coastline edge: quay faces below
            wd = R._float(t.get("width")) or WIDTH[k]
            fl = t.get("floating") == "yes"
            fp = g.buffer(max(1.5, min(wd, 40.0)) / 2, cap_style="flat" if k != "breakwater" else "round", join_style="mitre", mitre_limit=3)
        else:
            fl = t.get("floating") == "yes"
            fp = g
        if fp.is_empty:
            continue
        inl = fp.intersection(land).area / max(fp.area, 1e-6)
        if inl > 0.7:
            stat["skipped_on_land"] += 1
            continue
        fp = fp.difference(land_in).buffer(0)
        if fp.is_empty or fp.area < 4:
            continue
        top = 0.6 if fl else TOP[k]
        M = R.Mesh()
        if k == "breakwater":                               # crown wall on a wider tetrapod apron
            apron = fp.buffer(3.5, join_style="mitre", mitre_limit=2).difference(land_in).buffer(0)
            _extrude(M, apron, SIDE_Z, 1.6, C_TETRA, C_TETRA, rng, mottle=0.12, wet=False)
            _extrude(M, fp, SIDE_Z, top, C_DECK, C_SIDE, rng, mottle=0.03)
        else:
            _extrude(M, fp, -0.4 if fl else SIDE_Z, top, C_DECK, C_SIDE, rng, mottle=0.03, wet=not fl)
        c = fp.centroid
        items.append((c.x, c.y, M))
        stat[k] += 1
    # quay faces: man-made coast segments in / next to port land (vertical concrete face on the coastline, coping on top)
    z = np.load(os.path.join(ROOT, "coast_field.npz"))
    a, b, cls = z["seg_a"], z["seg_b"], z["seg_cls"]
    port = data["port"] + [p["geom"] for p in data["piers"] if p["kind"] == "quay"]
    tree = shapely.STRtree(port)
    mid = (a + b) / 2
    ip, _ = tree.query(shapely.points(mid), predicate="dwithin", distance=30.0)
    inport = np.zeros(len(a), bool)
    inport[ip] = True
    sel = np.nonzero((cls > 0.75) & inport)[0]
    d = b - a
    L = np.hypot(d[:, 0], d[:, 1])
    nrm = np.stack((-d[:, 1], d[:, 0]), 1) / np.maximum(L, 1e-6)[:, None]       # left = land
    la, lo = R.latlon(*(mid + 3.0 * nrm).T)
    msl = np.asarray(dem.msl(la, lo), float)
    topz = np.minimum(np.maximum(msl, WALL_H), 8.0) + 0.2
    bins = {}
    for i in sel:
        if L[i] < 0.5:
            continue
        (x0, y0), (x1, y1) = a[i], b[i]
        n = nrm[i]
        M = bins.setdefault((int(mid[i][0] // 2000), int(mid[i][1] // 2000)), R.Mesh())
        zt = float(topz[i])
        out = (-n[0], -n[1], 0.0)
        for za, zb, col in ((SIDE_Z, WET_TOP, C_WET), (WET_TOP, zt, C_SIDE)):
            M.quad(1, [(x0, y0, za), (x1, y1, za), (x1, y1, zb), (x0, y0, zb)], col,
                   [(0, za / 4), (L[i] / 4, za / 4), (L[i] / 4, zb / 4), (0, zb / 4)], out)
        cw = 1.2
        M.quad(1, [(x0, y0, zt), (x1, y1, zt), (x1 + n[0] * cw, y1 + n[1] * cw, zt), (x0 + n[0] * cw, y0 + n[1] * cw, zt)], C_DECK,
               [(0, 0), (L[i] / 4, 0), (L[i] / 4, cw / 4), (0, cw / 4)], (0, 0, 1))
        stat["quay_faces_km"] += L[i] / 1000
    for (bi, bj), M in bins.items():
        items.append(((bi + 0.5) * 2000, (bj + 0.5) * 2000, M))
    stat["quay_faces_km"] = round(stat["quay_faces_km"], 1)
    # tiles: 2 km bins, one level under the root (additive)
    imgs = R.textures()
    groups = {}
    for x, y, M in items:
        groups.setdefault((int(x // 2000), int(y // 2000)), []).append(M)
    tmp = PIERS + "_tmp"
    import shutil
    if os.path.isdir(tmp):
        shutil.rmtree(tmp)
    os.makedirs(tmp)
    kids, sizes, verts = [], {}, 0
    for (i, j), Ms in sorted(groups.items()):
        cla, clo = R.latlon((i + 0.5) * 2000, (j + 0.5) * 2000)
        glb, reg, nv = R.mesh_glb(Ms, (float(cla), float(clo)), dem, imgs)
        fn = "p_%d_%d.glb" % (i, j)
        with open(os.path.join(tmp, fn), "wb") as f:
            f.write(glb)
        kids.append(dict(boundingVolume=dict(region=reg), geometricError=0.0, content=dict(uri=fn)))
        sizes[fn] = len(glb)
        verts += nv
    reg = kids[0]["boundingVolume"]["region"][:]
    for c in kids[1:]:
        r = c["boundingVolume"]["region"]
        reg = [min(reg[0], r[0]), min(reg[1], r[1]), max(reg[2], r[2]), max(reg[3], r[3]), min(reg[4], r[4]), max(reg[5], r[5])]
    ts = dict(asset=dict(version="1.1", tilesetVersion=time.strftime("%Y%m%d%H%M%S"), generator="gyro-sim-chair sim/coast_build.py",
                         copyright="© OpenStreetMap contributors (ODbL)", extras=dict(osm_base=osm_base, input=OSM_FILE)),
              geometricError=400.0, root=dict(boundingVolume=dict(region=reg), geometricError=200.0, refine="ADD", children=kids))
    with open(os.path.join(tmp, "tileset.json"), "w", encoding="utf-8") as f:
        json.dump(ts, f, ensure_ascii=False)
    info = dict(made=time.strftime("%Y-%m-%d %H:%M:%S"), seconds=round(time.time() - t0), input=dict(osm=OSM_FILE, osm_base=osm_base,
                mask=os.path.join(ROOT, "coast_field.npz")), tiles=len(sizes), bytes=sum(sizes.values()), verts=int(verts), **stat,
                heights=dict(top=TOP, side_z=SIDE_Z, wall_h=WALL_H, note="추정 (not in OSM)"), widths=WIDTH)
    with open(os.path.join(tmp, "build.json"), "w", encoding="utf-8") as f:
        json.dump(info, f, indent=1, ensure_ascii=False)
    if os.path.isdir(PIERS):
        if os.path.isdir(PIERS + "_prev"):
            shutil.rmtree(PIERS + "_prev")
        os.replace(PIERS, PIERS + "_prev")
    os.replace(tmp, PIERS)
    print("piers: %s, %d tiles %.1f MB, %d verts, %.0f s -> %s" % (stat, len(sizes), sum(sizes.values()) / 1e6, verts, time.time() - t0, PIERS), flush=True)


def unreal_running():
    import subprocess
    out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq UnrealEditor*", "/FO", "CSV", "/NH"], capture_output=True, text=True).stdout
    return "UnrealEditor" in out


def swap(back=False):
    """tiles_coast_new/* -> tiles/ (originals -> tiles_coast_prev/), or back (--unswap). Only while no UnrealEditor runs."""
    import terrain_dem as T
    if unreal_running():
        print("an UnrealEditor is running: swap not done (it may be reading the tiles)")
        return False
    prev = T.TILES + "_coast_prev"
    info = json.load(open(os.path.join(NEW_TILES if not back else prev, "coast_tiles.json"), encoding="utf-8"))
    nmov = 0
    for L, x, y, _ in info["tiles"]:
        rel = os.path.join(str(L), str(x), "%d.terrain" % y)
        live, new, old = os.path.join(T.TILES, rel), os.path.join(NEW_TILES, rel), os.path.join(prev, rel)
        if not back:
            os.makedirs(os.path.dirname(old), exist_ok=True)
            if os.path.exists(live) and not os.path.exists(old):
                os.replace(live, old)
            os.replace(new, live) if os.path.exists(new) else None
        else:
            if os.path.exists(old):
                os.makedirs(os.path.dirname(new), exist_ok=True)
                if os.path.exists(live):
                    os.replace(live, new)
                os.replace(old, live)
        nmov += 1
    if not back:
        import shutil
        shutil.copy(os.path.join(NEW_TILES, "coast_tiles.json"), os.path.join(prev, "coast_tiles.json"))
    with open(os.path.join(T.TILES, "coast_swap.json"), "w", encoding="utf-8") as f:
        json.dump(dict(made=time.strftime("%Y-%m-%d %H:%M:%S"), state="coast" if not back else "original", tiles=nmov, prev=prev), f)
    print("swapped %d tiles %s (prev copies in %s)" % (nmov, "in" if not back else "back", prev))
    return True


if __name__ == "__main__":
    a = sys.argv[1:]
    if "--fetch" in a:
        fetch()
    if "--mask" in a:
        mask()
    if "--terrain" in a:
        terrain()
    if "--piers" in a:
        piers()
    if "--swap" in a:
        swap()
    if "--unswap" in a:
        swap(back=True)
    if not a:
        print(__doc__)
