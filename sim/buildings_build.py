"""3D buildings for the Unreal 'vworld' ground mode: 국토교통부 GIS건물통합정보 (building footprints + heights, SHP) ->
extruded LoD1 blocks as 3D Tiles 1.1 (glb content), served by sim/vworld_proxy.py at /buildings/tileset.json.

    python -I sim/buildings_build.py --all                 prep + tiles + ground for the default region (Cheongju, 30 km around RKTU)
    python -I sim/buildings_build.py --prep [--region cheongju | --bbox W S E N | --center LAT LON --radius-km R | --whole]
                                            [--shp a.shp ... | --zip x.zip ... | --province 43[,44]] [--name NAME]
    python -I sim/buildings_build.py --tiles  [--only a,b]  all work/buildings_*.npz -> tiles/tileset.json + tiles/{a,b,c}/*.glb
    python -I sim/buildings_build.py --ground [--only a,b]  each work file -> ground/roof_<name>.npy (server crash raster)
    python -I sim/buildings_build.py --stats                print work/stats_*.json
  Nationwide: one --prep --whole --province <code> --name p<code> per zip (11 12 26 27 28 30 31 36 41 43 44 47 48 50 51 52),
  then --tiles and --ground once (the tile grid is global, so buildings on both sides of a border share tiles).
  Delete work/buildings_cheongju.npz first, or it is built twice (overlaps p43).
Data (never in git - licence is attribution only, but the repo stays code-only): input SHP in
C:\\GyroSimTiles\\incoming\\bldg_<sido>\\AL_D010_<sido>_<date>.shp, output C:\\GyroSimTiles\\buildings (GYROSIM_BUILDINGS moves it):
  work/buildings_<name>.npz  footprints (lon/lat rings), height, base, source of the height + stats_<name>.json
  work/_merged/       all work files concatenated (.npy, memory-mapped by the tile workers)
  tiles/              tileset.json + glb (the proxy serves this folder)
  ground/roof_<name>.npy  int16 decimetres MSL roof heights on a 1/3" grid (+ .json bounds), read by terrain_dem.Roofs

Fields (checked on the 충북 file 2026-10-09, docs/vworld-integration.md section 6): A16 height m (건축물대장), A26 floors above
ground, A27 floors below ground, A9 main use (주용도), A11 structure, A12 building area m2, A24 / A25 building / block name.
Height rule: A16 if sane, else floors -> 1.5 + 2.9 m per floor (fit to the buildings that have both), else a default
from the footprint area (가정). Base = the lowest point of the rendered terrain (level-13 quantized-mesh triangles of
terrain_build.py) on the footprint, so blocks never float; walls start 1 m below that. (The Copernicus DEM is a surface
model, but over Cheongju's tall blocks it is only 1-7 m above the surrounding ground, so no extra lowering is done.)

Textures (sim/buildings_tex.py, cached V-World tiles only, no API call): roofs = the photo of that spot (per-tile JPEG
atlas), walls = window modules per use class (A8), one row per floor, tinted by a colour derived from the roof photo.
GYROSIM_BUILDINGS_PLAIN=1 builds without the photo (palette colours). Preview without Unreal: sim/buildings_lookdev.py.

Tiling (additive refinement, so distant views only load the big / tall blocks): root (region) -> 8 km tiles with
class A (>= 25 m or >= 2500 m2) -> 2 km tiles with class B (>= 10 m or >= 300 m2) -> 1 km tiles with the rest.
Tile grid is anchored at 0 deg so rebuilt / larger regions keep the same tile names.
Run with `python -I` (the input is a download): user site-packages are added back below; no code is read from the data folder.
"""
import json, math, os, sys, time, struct, site, hashlib
if sys.flags.isolated:                                    # python -I: keep isolation but use the user's installed packages
    site.addsitedir(site.getusersitepackages())
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import numpy as np                                        # noqa: E402
import terrain_dem as T                                   # noqa: E402

ROOT = os.environ.get("GYROSIM_BUILDINGS", r"C:\GyroSimTiles\buildings")
WORK, TILES, GROUND = (os.path.join(ROOT, d) for d in ("work", "tiles", "ground"))
TILES = os.environ.get("GYROSIM_BUILDINGS_TILES", TILES)  # build somewhere else (e.g. tiles_new), then swap folders: the proxy keeps serving
EXCLUDE = os.environ.get("GYROSIM_LANDMARK_EXCLUDE", r"C:\GyroSimTiles\landmarks\exclude.json")  # landmark rids left out of the tiles (no file = none)
INCOMING = r"C:\GyroSimTiles\incoming"
DEFAULT_SHP = [os.path.join(INCOMING, "bldg_43", "AL_D010_43_20261009.shp")]
RKTU = (36.7166, 127.4993)
REGIONS = {"cheongju": dict(center=RKTU, radius_km=30.0)}       # Busan: --prep --province 26 --whole --name busan
SRC_CRS = "EPSG:5186"                                     # read from the .prj (checked: Korea 2000 Central Belt 2010)
ATTRIB = "건물: 국토교통부 GIS건물통합정보 (CC BY)"

# height rule ----------------------------------------------------------------------------------------------------------
H_MIN, H_MAX = 2.0, 600.0                                 # A16 outside this = no height (outliers up to 25,275 m seen)
H_TALL = 300.0                                            # A16 above this only with a floor count that agrees (Busan LCT 411 m, 101 F)
FLOOR_BASE, FLOOR_M = 1.5, 2.9                            # floors -> m (median of A16 vs A26 where both exist, see stats)
# no height, no floors (가정, 56.6 % of 충북): small = sheds / houses, large = warehouses / factories
AREA_DEFAULTS = ((40.0, 3.0), (150.0, 4.5), (600.0, 6.0), (3000.0, 8.0), (1e12, 10.0))
MIN_AREA = 8.0                                            # m2, smaller polygons are dropped
SIMPLIFY_M = 0.3
WALL_SINK = 1.0                                           # m, walls start this far below the base (no gaps on slopes)
MESH_LEVEL, MESH_N = 13, 65                               # = terrain_build.MAX_LEVEL and its vertices per tile edge
MESH_DROP = 0.3                                           # m, base under the lowest mesh point (triangle edges in between)

# tiling ----------------------------------------------------------------------------------------------------------------
STEP_A = (0.072, 0.09)                                    # deg lat / lon of class-A tiles (~8.0 x 8.0 km at 36.7 N)
SUB_B, SUB_C = 4, 2                                       # A tile -> 4 x 4 B tiles (~2 km) -> 2 x 2 C tiles (~1 km)
GE = dict(root=500.0, a=130.0, b=50.0, c=0.0)             # geometricError: SSE 16 at 1080p ~ refine when d < ~60 x GE


def is_a(h, area):
    return (h >= 25.0) | (area >= 2500.0)


def is_b(h, area):
    return (h >= 10.0) | (area >= 300.0)


# ---- step 1: prep ------------------------------------------------------------------------------------------------------
def region_box(args):
    """(w, s, e, n, center, radius_m or None, name)."""
    if "--whole" in args:
        return None, None, None, None, None, None, "whole"
    if "--bbox" in args:
        i = args.index("--bbox")
        w, s, e, n = (float(v) for v in args[i + 1:i + 5])
        return w, s, e, n, None, None, "bbox"
    name = args[args.index("--region") + 1] if "--region" in args else "cheongju"
    if "--center" in args:
        i = args.index("--center")
        c = (float(args[i + 1]), float(args[i + 2]))
        r = float(args[args.index("--radius-km") + 1]) if "--radius-km" in args else 30.0
        name = "center"
    else:
        c, r = REGIONS[name]["center"], REGIONS[name]["radius_km"]
    dl, dn = r * 1000 / T.M_LAT, r * 1000 / (111320.0 * math.cos(math.radians(c[0])))
    return c[1] - dn, c[0] - dl, c[1] + dn, c[0] + dl, c, r * 1000.0, name


def floors_height(f):
    return FLOOR_BASE + FLOOR_M * f


def area_default(a):
    out = np.full(a.shape, AREA_DEFAULTS[-1][1])
    for lim, h in reversed(AREA_DEFAULTS):
        out = np.where(a < lim, h, out)
    return out


def height_rule(h16, fl, area):
    """-> height m, source code (1 = A16, 2 = floors, 3 = area default), 'outlier' mask (A16 rejected)."""
    h16, fl = np.nan_to_num(h16), np.nan_to_num(fl)
    ok16 = (h16 >= H_MIN) & (h16 <= H_MAX) & ((h16 <= H_TALL) | (fl >= 3))
    # A16 that disagrees badly with the floor count (>= 3 floors) is a typo in one of them: trust the floors
    per = np.where(fl > 0, h16 / np.maximum(fl, 1), 0)
    bad_ratio = (fl >= 3) & ok16 & ((per < 2.0) | (per > 8.0))
    use16 = ok16 & ~bad_ratio
    usefl = ~use16 & (fl > 0)
    h = np.where(use16, h16, np.where(usefl, floors_height(fl), area_default(area)))
    src = np.where(use16, 1, np.where(usefl, 2, 3)).astype(np.int8)
    outlier = (h16 > 0) & ~use16
    return np.clip(h, H_MIN, H_MAX), src, outlier


# use class (for the wall textures, sim/buildings_tex.py) from A8 = 건축물 주용도 코드 (checked on the 충북 file: 01000
# 단독주택, 02000 공동주택, 03000/04000 제1/2종 근린생활, 07000 판매, 14000 업무, 17000 공장, 18000 창고, 21000 동·식물 관련 ...)
USE_NAMES = ("plain", "house", "apartment", "shop", "office", "factory")
PLAIN, HOUSE, APT, SHOP, OFFICE, FACTORY = range(6)
USE_CODES = {"01": HOUSE, "02": APT, "03": SHOP, "04": SHOP, "07": SHOP, "08": SHOP, "15": SHOP, "16": SHOP, "27": SHOP,
             "05": OFFICE, "06": OFFICE, "09": OFFICE, "10": OFFICE, "11": OFFICE, "12": OFFICE, "13": OFFICE, "14": OFFICE,
             "23": OFFICE, "24": OFFICE, "29": OFFICE, "17": FACTORY, "18": FACTORY, "19": FACTORY, "20": FACTORY, "25": FACTORY,
             "21": PLAIN, "22": PLAIN, "26": PLAIN}


def use_class(a8, area, h, src):
    """int8 class per building. Unknown code: by size (가정) - tiny = shed, < 250 m2 house, large and low = warehouse."""
    out = np.full(len(area), -1, np.int8)
    for i, c in enumerate(a8):
        c = str(c or "").strip()
        if c[:1] == "Z":                                  # Z3000 근생, Z5000 문화, Z6000 판매, Z8000 / Z9000 (old codes)
            out[i] = SHOP if c[1:2] in ("3", "6") else OFFICE
        elif c[:2] in USE_CODES:
            out[i] = USE_CODES[c[:2]]
    unk = out < 0
    guess = np.where(area < 40, PLAIN, np.where(area < 250, HOUSE, np.where((area >= 600) & (h <= 12), FACTORY, SHOP)))
    out[unk] = guess[unk]
    out[(area < 25) & (h <= 3.5)] = PLAIN                 # sheds: no windows whatever the code says
    return out


def dem_window(dem, w, s, e, n, pad=0.01):
    """1" DEM block covering the box (+pad deg): (array MSL m [rows from north], north, west)."""
    r0, r1 = int(math.floor((T.BOX_N - (n + pad)) * T.PX)), int(math.ceil((T.BOX_N - (s - pad)) * T.PX)) + 1
    c0, c1 = int(math.floor((w - pad - T.BOX_W) * T.PX)), int(math.ceil((e + pad - T.BOX_W) * T.PX)) + 1
    R, C = np.meshgrid(np.arange(r0, r1), np.arange(c0, c1), indexing="ij")
    return dem._px(R, C).astype(np.float32), T.BOX_N - r0 / T.PX, T.BOX_W + c0 / T.PX


def bilinear(a, north, west, lat, lon):
    fr, fc = (north - lat) * T.PX, (lon - west) * T.PX
    r0, c0 = np.clip(np.floor(fr).astype(np.int64), 0, a.shape[0] - 2), np.clip(np.floor(fc).astype(np.int64), 0, a.shape[1] - 2)
    tr, tc = np.clip(fr - r0, 0, 1), np.clip(fc - c0, 0, 1)
    return (a[r0, c0] * (1 - tc) + a[r0, c0 + 1] * tc) * (1 - tr) + (a[r0 + 1, c0] * (1 - tc) + a[r0 + 1, c0 + 1] * tc) * tr


def _mesh_height(dem, lat, lon, level, nv):
    d = 180.0 / (1 << level) / (nv - 1)
    fy, fx = (np.asarray(lat) + 90.0) / d, (np.asarray(lon) + 180.0) / d
    j, i = np.floor(fy), np.floor(fx)
    v, u = fy - j, fx - i
    la0, lo0 = j * d - 90.0, i * d - 180.0
    ha, hb = dem.msl(la0, lo0), dem.msl(la0, lo0 + d)
    hc, hd = dem.msl(la0 + d, lo0), dem.msl(la0 + d, lo0 + d)
    return np.where(u >= v, ha + u * (hb - ha) + v * (hd - hb), ha + v * (hc - ha) + u * (hd - hc))


def mesh_height(dem, lat, lon):
    """MSL height of the finest Cesium terrain mesh (terrain_build: level 13 tiles, 65 x 65 vertices sampled bilinear
    from the 1" DEM, triangles a-b-d / a-d-c with the diagonal south-west -> north-east) at lat / lon. Inside a
    terrain_dem.HIRES box (Busan) the finest mesh is that box's deeper level (16, 33 x 33) - its lowest point wins, so
    a block stands on whichever of the two meshes is drawn."""
    lat, lon = np.asarray(lat, dtype=np.float64), np.asarray(lon, dtype=np.float64)
    h = _mesh_height(dem, lat, lon, MESH_LEVEL, MESH_N)
    for b in T.HIRES:
        w, s, e, n = b["box"]
        m = (lat >= s) & (lat < n) & (lon >= w) & (lon < e)
        if np.any(m):
            h = np.where(m, np.minimum(h, _mesh_height(dem, lat, lon, b["max_level"], b["n"])), h)
    return h


ZIPS = os.path.join(INCOMING, "zips")                    # AL_D010_{sido code}_{date}.zip, all 16 zips (11 서울 ... 52 전북)


def sources(args):
    """input shapefiles: --shp a.shp, --zip x.zip, --province 43 (incoming/zips/AL_D010_43_*.zip). A zip may hold the
    province in 2-3 split shapefiles (the first part caps at 1,000,000 records): every .shp inside is read, straight
    from the zip (GDAL /vsizip/, nothing extracted)."""
    import glob, zipfile
    shps = [args[i + 1] for i, a in enumerate(args) if a == "--shp"]
    zips = [args[i + 1] for i, a in enumerate(args) if a == "--zip"]
    for i, a in enumerate(args):
        if a == "--province":
            for code in args[i + 1].split(","):
                found = sorted(glob.glob(os.path.join(ZIPS, "AL_D010_%s_*.zip" % code)))
                assert found, ("no zip for province", code, ZIPS)
                zips.append(found[-1])                    # newest date
    for z in zips:
        with zipfile.ZipFile(z) as zf:
            for m in sorted(zf.namelist()):
                if m.lower().endswith(".shp"):
                    shps.append("/vsizip/%s/%s" % (z.replace(chr(92), "/"), m))
    if not shps:
        shps = [p for p in DEFAULT_SHP if os.path.exists(p)] or sources(["--province", "43"])
    return shps


def work_name(args, region):
    return args[args.index("--name") + 1] if "--name" in args else region


def prep(args):
    import pyogrio, shapely
    from pyproj import Transformer
    t0 = time.time()
    shps = sources(args)
    w, s, e, n, center, radius, name = region_box(args)
    name = work_name(args, name)
    to_src = Transformer.from_crs("EPSG:4326", SRC_CRS, always_xy=True)
    to_geo = Transformer.from_crs(SRC_CRS, "EPSG:4326", always_xy=True)
    parts, inputs = [], []
    for shp in shps:
        info = pyogrio.read_info(shp)
        assert "5186" in str(info["crs"]), ("unexpected CRS", info["crs"], shp)
        bbox = None
        if w is not None:
            xs, ys = to_src.transform([w, e, w, e], [s, s, n, n])
            bbox = (min(xs), min(ys), max(xs), max(ys))
        df = pyogrio.read_dataframe(shp, encoding="cp949", columns=["A0", "A1", "A8", "A9", "A12", "A16", "A26", "A27", "A24"], bbox=bbox)
        df["src_file"] = os.path.basename(shp)
        parts.append(df)
        st = os.stat(shp.split("/vsizip/")[-1].split(".zip/")[0] + ".zip" if shp.startswith("/vsizip/") else shp)
        inputs.append(dict(file=shp, features=int(info["features"]), size=st.st_size, mtime=time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(st.st_mtime))))
        print("read %s: %d of %d features in the box (%.0f s)" % (os.path.basename(shp), len(df), info["features"], time.time() - t0), flush=True)
    import pandas as pd
    df = pd.concat(parts, ignore_index=True)
    g = np.asarray(df.geometry.values)
    n_in = len(g)
    g = shapely.make_valid(g)
    # make_valid can return multipolygons / collections: keep polygon parts, one record per polygon
    parts_g, idx = shapely.get_parts(g, return_index=True)
    keep = shapely.get_type_id(parts_g) == 3
    parts_g, idx = parts_g[keep], idx[keep]
    poly_extra = shapely.get_type_id(g) != 3
    parts_g = shapely.simplify(parts_g, SIMPLIFY_M, preserve_topology=True)
    parts_g = shapely.orient_polygons(parts_g, exterior_cw=False) if hasattr(shapely, "orient_polygons") else np.array([shapely.geometry.polygon.orient(p, 1.0) for p in parts_g])
    area = shapely.area(parts_g)
    cen = shapely.centroid(parts_g)
    cx, cy = shapely.get_x(cen), shapely.get_y(cen)
    clon, clat = to_geo.transform(cx, cy)
    clon, clat = np.asarray(clon), np.asarray(clat)
    sel = area >= MIN_AREA
    n_small = int((~sel).sum())
    if radius is not None:
        dn_, de_ = (clat - center[0]) * T.M_LAT, (clon - center[1]) * 111320.0 * np.cos(np.radians(center[0]))
        sel &= np.hypot(dn_, de_) <= radius
    elif w is not None:
        sel &= (clon >= w) & (clon < e) & (clat >= s) & (clat < n)
    # nothing on the sim's own airfield: the runway mesh / flattened DEM area (military base, not in the data anyway)
    on_field = T.airfield_weight(clat, clon) >= 1.0
    sel &= ~on_field
    parts_g, idx, area, clon, clat = parts_g[sel], idx[sel], area[sel], clon[sel], clat[sel]
    rec = df.iloc[idx].reset_index(drop=True)
    h, src, outlier = height_rule(rec.A16.values.astype(float), rec.A26.values.astype(float), area)
    # coordinates: rings -> lon/lat (exterior first, then holes, polygon by polygon)
    rings, ring_of_poly = shapely.get_rings(parts_g, return_index=True)
    coords = shapely.get_coordinates(rings)
    nring = shapely.get_num_coordinates(rings)                # closed rings (first point repeated)
    lon, lat = to_geo.transform(coords[:, 0], coords[:, 1])
    lon, lat = np.asarray(lon), np.asarray(lat)
    # base height: lowest point of the rendered terrain (the level-13 quantized-mesh triangles of terrain_build.py, which
    # sample the 1" DEM) on the footprint vertices / centroid, minus MESH_DROP: blocks never float above the visible ground
    dem = T.Dem()
    v_mesh = mesh_height(dem, lat, lon)
    c_mesh = mesh_height(dem, clat, clon)
    ring_start = np.concatenate(([0], np.cumsum(nring)[:-1]))
    first_ring = np.concatenate(([0], np.flatnonzero(np.diff(ring_of_poly)) + 1))
    pr = ring_start[first_ring]                           # first vertex of each polygon
    if os.environ.get("GYROSIM_BLDG_COAST", "1") != "0":
        # 11-10: the rendered terrain inside the Busan box follows sim/coast_build.py's coast rule (sea walls 2.8 m, beaches,
        # sea = 0 m) - mesh_height does not know it, so a block stands on the lower of the two (never floats over a beach)
        try:
            import coast_build as CB
            v_mesh = np.minimum(v_mesh, CB.rendered_msl(dem, lat, lon))
            c_mesh = np.minimum(c_mesh, CB.rendered_msl(dem, clat, clon))
            print("coast rule applied to the base (sim/coast_build.rendered_msl)", flush=True)
        except Exception as e:
            print("coast rule not applied: %r" % (e,), flush=True)
    base = np.minimum(np.minimum.reduceat(v_mesh, pr), c_mesh) - MESH_DROP
    dsm_max = np.maximum.reduceat(v_mesh, pr)             # highest visible ground on the footprint (slope)
    dsm_c = dem.msl(clat, clon)
    geoid = dem.geoid_n(clat, clon)
    rid = rec.A0.values.astype(np.int64)
    use = use_class(rec.A8.values, area, h, src)
    os.makedirs(WORK, exist_ok=True)
    np.savez(os.path.join(WORK, "buildings_%s.npz" % name), lon=lon, lat=lat, nring=nring.astype(np.int32), ring_of_poly=ring_of_poly.astype(np.int32),
             h=h.astype(np.float32), src=src, base=base.astype(np.float32), geoid=geoid.astype(np.float32), area=area.astype(np.float32),
             clat=clat, clon=clon, rid=rid, dsm_max=dsm_max.astype(np.float32), dsm_c=dsm_c.astype(np.float32),
             floors=np.nan_to_num(rec.A26.values.astype(float)).astype(np.int16), use=use, uid=rec.A1.fillna("").values.astype("U32"), a16=np.nan_to_num(rec.A16.values.astype(float)).astype(np.float32))
    roof = base + h
    nb = len(h)
    stats = dict(made=time.strftime("%Y-%m-%d %H:%M:%S"), region=dict(name=name, bbox=[w, s, e, n], center=center, radius_m=radius),
                 inputs=inputs, features_in_box=n_in, polygons=int(len(keep)), made_valid_multi=int(poly_extra.sum()), buildings=nb,
                 dropped_small=n_small, on_field_dropped=int(on_field.sum()),
                 height_source={"A16": int((src == 1).sum()), "floors": int((src == 2).sum()), "area_default": int((src == 3).sum())},
                 height_source_pct={"A16": round(100 * (src == 1).mean(), 1), "floors": round(100 * (src == 2).mean(), 1), "area_default": round(100 * (src == 3).mean(), 1)},
                 use_class={nm: int((use == k).sum()) for k, nm in enumerate(USE_NAMES)},
                 a16_rejected=int(outlier.sum()), height_m=dict(median=round(float(np.median(h)), 1), p90=round(float(np.percentile(h, 90)), 1),
                 p99=round(float(np.percentile(h, 99)), 1), max=round(float(h.max()), 1)),
                 classes=dict(A=int(is_a(h, area).sum()), B=int((is_b(h, area) & ~is_a(h, area)).sum()), C=int((~is_b(h, area)).sum())),
                 dsm_vs_base=dict(note="DEM (DSM) at the centroid minus the base (slope + mesh smoothing)",
                                  median=round(float(np.median(dsm_c - base)), 1), p90=round(float(np.percentile(dsm_c - base, 90)), 1)),
                 buried=dict(note="highest rendered-terrain point on the footprint vs the roof: roof below it = block hidden on that side",
                             roof_below_dsm=int((roof < dsm_max).sum()), roof_below_dsm_pct=round(100 * float((roof < dsm_max).mean()), 1),
                             half_below_pct=round(100 * float((base + 0.5 * h < dsm_max).mean()), 1)),
                 vertices=int(len(lon)), rule=dict(h_min=H_MIN, h_max=H_MAX, floor_base=FLOOR_BASE, floor_m=FLOOR_M, area_defaults=AREA_DEFAULTS,
                 min_area=MIN_AREA, simplify_m=SIMPLIFY_M, base="min level-%d mesh - %.1f m" % (MESH_LEVEL, MESH_DROP)), seconds=round(time.time() - t0))
    tall = np.argsort(-h)[:12]
    stats["tallest"] = [dict(name=str(rec.A24.values[i]) if rec.A24.values[i] is not None else "", h=round(float(h[i]), 1), src=int(src[i]),
                             floors=int(np.nan_to_num(rec.A26.values[i])), lat=round(float(clat[i]), 5), lon=round(float(clon[i]), 5)) for i in tall]
    with open(os.path.join(WORK, "stats_%s.json" % name), "w", encoding="utf-8") as f:
        json.dump(stats, f, indent=1, ensure_ascii=False, default=str)
    print(json.dumps({k: stats[k] for k in ("buildings", "height_source_pct", "a16_rejected", "height_m", "classes", "dsm_vs_base", "buried", "seconds")}, ensure_ascii=False), flush=True)
    return stats


# ---- step 2: 3D Tiles --------------------------------------------------------------------------------------------------
A_WGS, E2 = 6378137.0, 6.69437999014e-3


def ecef(lat, lon, h):
    la, lo = np.radians(lat), np.radians(lon)
    sl, cl = np.sin(la), np.cos(la)
    nn = A_WGS / np.sqrt(1 - E2 * sl * sl)
    return np.stack(((nn + h) * cl * np.cos(lo), (nn + h) * cl * np.sin(lo), (nn * (1 - E2) + h) * sl), axis=-1)


def enu_rot(lat, lon):
    """columns = east, north, up unit vectors in ECEF."""
    la, lo = math.radians(lat), math.radians(lon)
    e = np.array([-math.sin(lo), math.cos(lo), 0.0])
    nn = np.array([-math.sin(la) * math.cos(lo), -math.sin(la) * math.sin(lo), math.cos(la)])
    u = np.array([math.cos(la) * math.cos(lo), math.cos(la) * math.sin(lo), math.sin(la)])
    return np.stack((e, nn, u), axis=1)


# walls ~10 % darker than plain concrete: next to the V-World photo, lighter walls read as white blocks (11-05 shots)
WALLS = np.array([[0.53, 0.52, 0.49], [0.58, 0.56, 0.52], [0.48, 0.48, 0.48], [0.55, 0.51, 0.45], [0.62, 0.61, 0.58], [0.45, 0.43, 0.40]])
ROOFS = np.array([[0.46, 0.46, 0.45], [0.36, 0.37, 0.38], [0.55, 0.55, 0.53], [0.33, 0.45, 0.37], [0.32, 0.40, 0.50],
                  [0.48, 0.33, 0.27], [0.27, 0.28, 0.30], [0.42, 0.40, 0.36]])
ROOF_P = np.array([0.22, 0.18, 0.12, 0.16, 0.12, 0.08, 0.06, 0.06])


def colors(rid):
    hsh = (rid.astype(np.uint64) * np.uint64(2654435761)) % np.uint64(1 << 32)
    u1 = (hsh & np.uint64(0xFFFF)).astype(np.float64) / 65536.0
    u2 = (hsh >> np.uint64(16)).astype(np.float64) / 65536.0
    wall = WALLS[(u1 * len(WALLS)).astype(int) % len(WALLS)]
    roof = ROOFS[np.searchsorted(np.cumsum(ROOF_P), u2 * ROOF_P.sum()).clip(0, len(ROOFS) - 1)]
    return wall, roof


def _sat():
    """per-process reader of the cached V-World tiles (None: GYROSIM_BUILDINGS_PLAIN=1 or no cache)."""
    if "sat" not in _W:
        import buildings_tex as BT
        _W["sat"] = None if os.environ.get("GYROSIM_BUILDINGS_PLAIN") == "1" or not os.path.isdir(BT.SAT) else BT.Sat()
    return _W["sat"]


def building_floors(h, floors, cls):
    """number of window rows: the data's floor count when it fits the height, else height / typical floor height."""
    import buildings_tex as BT
    if cls == BT.PLAIN:
        return 1
    if floors > 0 and 1.9 <= h / floors <= 8.0:
        return int(min(floors, 80))
    fh = BT.FLOOR_H[cls]
    if fh <= 0:                                           # factory: one tall module, more when very tall
        return 1 if h <= 12 else int(round(h / 7.0))
    return int(max(1, min(80, round(h / fh))))




def build_glb(D, sel, center):
    """glb for the buildings `sel` around center (lat, lon): primitive 0 = roofs (per-tile JPEG atlas of the cached
    V-World photo, white vertex colour; no photo -> a white atlas patch x a palette colour), primitive 1 = walls (shared
    window atlas, vertex colour = wall tint derived from the photo, quads split per floor). -> (glb, (P, hmin, stats))."""
    import mapbox_earcut as earcut
    import buildings_tex as BT
    sat = _sat()
    R = enu_rot(*center)
    C0 = ecef(np.array(center[0]), np.array(center[1]), np.array(0.0)).reshape(3)
    _, roof_pal = colors(D["rid"][sel])
    rid = D["rid"][sel].astype(np.uint64)
    jit = ((rid * np.uint64(40503)) % np.uint64(65536)).astype(np.float64) / 32768.0 - 1.0
    upal = ((rid * np.uint64(2246822519)) % np.uint64(1 << 20)).astype(np.float64) / float(1 << 20)
    has_use, has_fl = "use" in D, "floors" in D
    st = dict(buildings=0, roof_photo={}, color_photo=0, palette=0, floors_data=0, styles={})
    # pass 1: rings, photo samples, wall colours
    blds = []
    for k, b in enumerate(sel):
        r0, r1 = D["poly_ring"][b], D["poly_ring"][b + 1]
        rings = []
        for r in range(r0, r1):
            v0, v1 = D["ring_v"][r], D["ring_v"][r + 1] - 1          # drop the closing point
            if v1 - v0 >= 3:
                rings.append((np.asarray(D["lat"][v0:v1], np.float64), np.asarray(D["lon"][v0:v1], np.float64)))
        if not rings:
            continue
        cls = int(D["use"][b]) if has_use else BT.HOUSE
        smp = BT.roof_sample(sat, rings) if sat is not None else None
        photo = smp is not None and smp["npx"] >= BT.ROOF_MIN_PX
        if smp is not None and smp["color"] is not None:
            wall = BT.wall_from_roof(smp["color"], cls, jit[k])
            st["color_photo"] += 1
        else:
            wall = BT.palette_wall(cls, upal[k])
            st["palette"] += 1
        if photo:
            st["roof_photo"][smp["z"]] = st["roof_photo"].get(smp["z"], 0) + 1
        blds.append((k, b, rings, cls, smp if photo else None, wall))
    if not blds:
        return None, None
    st["buildings"] = len(blds)
    jpg, AW, AH, place, white = BT.roof_atlas([x[4]["img"] for x in blds if x[4] is not None])
    st["atlas"] = [AW, AH]
    # pass 2: geometry
    RF = dict(P=[], N=[], C=[], UV=[], I=[], n=0)
    WL = {}                                               # wall texture id -> geometry (one primitive each)

    def quads(t, A0, A1, D0, D1, fa, fb, u0, u1, va, vb, n2, wl):
        """one quad per edge between height fractions fa..fb (of bot..top), v = va (bottom) .. vb (top)."""
        G = WL.setdefault(t, dict(P=[], N=[], C=[], UV=[], I=[], n=0))
        q = len(A0)
        G["P"].append(np.stack((A0 + fa * D0, A1 + fa * D1, A1 + fb * D1, A0 + fb * D0), axis=1).reshape(-1, 3))
        G["N"].append(np.repeat(n2, 4, axis=0))
        G["UV"].append(np.stack((np.stack((u0, np.full(q, va)), 1), np.stack((u1, np.full(q, va)), 1),
                                 np.stack((u1, np.full(q, vb)), 1), np.stack((u0, np.full(q, vb)), 1)), axis=1).reshape(-1, 2))
        G["C"].append(np.repeat(wl, 4, axis=0))                         # per edge RGBA (alpha = seed / end-wall flag)
        bi = G["n"] + 4 * np.arange(q)
        G["I"].append(np.stack((bi, bi + 1, bi + 2, bi, bi + 2, bi + 3), axis=1).reshape(-1))
        G["n"] += 4 * q
    def roof_core(WL, Pt, area, hgt, wl, seed, k=1.0, z0=None):
        """box (stair / lift core) on the roof, along the longest edge, centred on the ring's vertex mean; only if all
        four corners are inside the footprint. Plain-wall style (no windows); top face = same primitive."""
        P2 = Pt[:, :2]
        d = np.roll(P2, -1, axis=0) - P2
        ln = np.hypot(d[:, 0], d[:, 1])
        if ln.max() < 1e-3:
            return False
        ax = d[int(np.argmax(ln))] / ln.max()
        ay = np.array([-ax[1], ax[0]])
        c = P2.mean(0)
        L, W = np.clip(0.30 * k * math.sqrt(area), 3.0, 9.0 * k), np.clip(0.18 * k * math.sqrt(area), 2.5, 6.0 * k)
        cs = np.array([c - L / 2 * ax - W / 2 * ay, c + L / 2 * ax - W / 2 * ay, c + L / 2 * ax + W / 2 * ay, c - L / 2 * ax + W / 2 * ay])
        x, y = P2[:, 0], P2[:, 1]
        x1, y1 = np.roll(x, -1), np.roll(y, -1)
        for px, py in cs:                                  # even-odd point in polygon
            cr = ((y > py) != (y1 > py)) & (px < (x1 - x) * (py - y) / np.where(y1 != y, y1 - y, 1e-12) + x)
            if cr.sum() % 2 == 0:
                return False
        z0 = float(Pt[:, 2].min()) if z0 is None else z0
        G = WL.setdefault(BT.ST_PLAIN, dict(P=[], N=[], C=[], UV=[], I=[], n=0))
        col = np.append(wl * 0.92, (128 + seed) / 255.0)
        quadsP, ns, uvs = [], [], []
        for i in range(4):
            a, b_ = cs[i], cs[(i + 1) % 4]
            e = b_ - a
            el = float(np.hypot(*e))
            quadsP.append([[a[0], a[1], z0], [b_[0], b_[1], z0], [b_[0], b_[1], z0 + hgt], [a[0], a[1], z0 + hgt]])
            ns.append([e[1] / el, -e[0] / el, 0.0])
            uvs.append([[0, 1], [el / 4.0, 1], [el / 4.0, 0], [0, 0]])
        quadsP.append([[p[0], p[1], z0 + hgt] for p in cs])
        ns.append([0.0, 0.0, 1.0])
        uvs.append([[0, 0]] * 4)
        q = len(quadsP)
        G["P"].append(np.asarray(quadsP, np.float64).reshape(-1, 3))
        G["N"].append(np.repeat(np.asarray(ns, np.float64), 4, axis=0))
        G["UV"].append(np.asarray(uvs, np.float64).reshape(-1, 2))
        G["C"].append(np.repeat(col[None], 4 * q, axis=0))
        bi = G["n"] + 4 * np.arange(q)
        G["I"].append(np.stack((bi, bi + 1, bi + 2, bi, bi + 2, bi + 3), axis=1).reshape(-1))
        G["n"] += 4 * q
        return z0 + hgt

    def box(cs, z0, hgt, style, rgba, top=True):
        """v3 rooftop prop: 4 walls (+ top) of a box, corners cs (4 x 2, counter-clockwise) from z0 up hgt. UV in metres:
        walls u along the perimeter / v down from the top edge, top face u, v = local metres (the material tells them
        apart by the normal). Vertex colour = prop colour, alpha = 128 + 16 x kind + seed (0..15)."""
        G = WL.setdefault(style, dict(P=[], N=[], C=[], UV=[], I=[], n=0))
        qp, ns, uvs, u = [], [], [], 0.0
        for i in range(4):
            a, b_ = cs[i], cs[(i + 1) % 4]
            e = b_ - a
            el = max(float(np.hypot(*e)), 1e-6)
            qp.append([[a[0], a[1], z0], [b_[0], b_[1], z0], [b_[0], b_[1], z0 + hgt], [a[0], a[1], z0 + hgt]])
            ns.append([e[1] / el, -e[0] / el, 0.0])
            uvs.append([[u, hgt], [u + el, hgt], [u + el, 0.0], [u, 0.0]])
            u += el
        if top:
            qp.append([[p_[0], p_[1], z0 + hgt] for p_ in cs])
            ns.append([0.0, 0.0, 1.0])
            uvs.append([[p_[0] - cs[0][0], p_[1] - cs[0][1]] for p_ in cs])
        q = len(qp)
        G["P"].append(np.asarray(qp, np.float64).reshape(-1, 3))
        G["N"].append(np.repeat(np.asarray(ns, np.float64), 4, axis=0))
        G["UV"].append(np.asarray(uvs, np.float64).reshape(-1, 2))
        G["C"].append(np.repeat(np.asarray(rgba, np.float64)[None], 4 * q, axis=0))
        bi = G["n"] + 4 * np.arange(q)
        G["I"].append(np.stack((bi, bi + 1, bi + 2, bi, bi + 2, bi + 3), axis=1).reshape(-1))
        G["n"] += 4 * q

    def inside(P2, pts):
        x, y = P2[:, 0], P2[:, 1]
        x1, y1 = np.roll(x, -1), np.roll(y, -1)
        for px, py in pts:
            cr = ((y > py) != (y1 > py)) & (px < (x1 - x) * (py - y) / np.where(y1 != y, y1 - y, 1e-12) + x)
            if cr.sum() % 2 == 0:
                return False
        return True

    def rect(c, ax, L, W):
        ay = np.array([-ax[1], ax[0]])
        return np.array([c - L / 2 * ax - W / 2 * ay, c + L / 2 * ax - W / 2 * ay, c + L / 2 * ax + W / 2 * ay, c - L / 2 * ax + W / 2 * ay])

    def spot(P2, ax, L, W, hv, margin=0.6):
        """a rect L x W (long side along ax) inside the footprint: toward a corner picked by hv (0..1), else the middle."""
        c = P2.mean(0)
        order = np.roll(np.arange(len(P2)), int(hv * len(P2)))
        for i in order:
            for t in (0.62, 0.45):
                cc = c + t * (P2[i] - c)
                if inside(P2, rect(cc, ax, L + 2 * margin, W + 2 * margin)):
                    return rect(cc, ax, L, W)
        return rect(c, ax, L, W) if inside(P2, rect(c, ax, L + 2 * margin, W + 2 * margin)) else None

    def prop_rgba(rgb, kind, seed_):
        return np.append(np.asarray(rgb, np.float64), (128 + 16 * kind + (seed_ % 16)) / 255.0)

    def obb(P2):
        """long axis (unit), long / short extent and the centre of the minimum-area box over the ring's edge directions."""
        best = None
        d = np.roll(P2, -1, axis=0) - P2
        for e in d:
            l_ = math.hypot(e[0], e[1])
            if l_ < 0.5:
                continue
            ax = e / l_
            ay = np.array([-ax[1], ax[0]])
            px, py = P2 @ ax, P2 @ ay
            a_ = (px.max() - px.min()) * (py.max() - py.min())
            if best is None or a_ < best[0]:
                best = (a_, ax, ay, px, py)
        if best is None:
            return None
        _, ax, ay, px, py = best
        Lx, Ly = px.max() - px.min(), py.max() - py.min()
        c = ax * (px.max() + px.min()) / 2 + ay * (py.max() + py.min()) / 2
        if Ly > Lx:
            ax, Lx, Ly = ay, Ly, Lx
        return ax, Lx, Ly, c
    V3 = BT.V3
    TANK_FRP = ((0.55, 0.68, 0.78), (0.80, 0.83, 0.84), (0.36, 0.55, 0.76), (0.62, 0.74, 0.70))
    ci = 0
    for k, b, rings, cls, smp, wall in blds:
        base = float(D["base"][b] + D["geoid"][b])
        bot, top = base - WALL_SINK, base + float(D["h"][b])
        fl = int(D["floors"][b]) if has_fl else 0
        nf = building_floors(float(D["h"][b]), fl, cls)
        if fl > 0 and nf == fl:
            st["floors_data"] += 1
        fh = (top - base) / nf
        wl = BT.srgb_to_lin(wall)
        seed = (int(rid[k]) * 2654435761 >> 7) % 64
        # v = floors down from the roof line (texture top = ceiling of a floor); shops: ground floor band = shop window.
        # Band ids = facade styles (buildings_tex.STYLE_NAMES, one primitive each)
        upper = BT.wall_style(cls, nf)
        st["styles"][upper] = st["styles"].get(upper, 0) + 1
        hb = [(((int(rid[k]) * 2246822519 + 7919 * i_) >> 9) % 1000) / 1000.0 for i_ in range(6)]   # per-building dice
        ground = None                                     # ground-floor band style (v3: a few shops, pilotis / lobbies)
        if cls == BT.SHOP and upper == BT.ST_PUNCHED:
            ground = BT.ST_SHOP
        elif V3 and nf >= 2:
            if upper == BT.ST_APT and nf >= 6:
                ground = BT.ST_PILOTI                     # apartment lobby / pilotis floor
            elif upper == BT.ST_VILLA and hb[0] < 0.7:
                ground = BT.ST_PILOTI                     # 빌라: pilotis parking under the flats
            elif cls == BT.OFFICE and upper in (BT.ST_RIBBON, BT.ST_PUNCHED) and hb[0] < 0.6:
                ground = BT.ST_SHOP
            elif cls == BT.HOUSE and upper == BT.ST_HOUSE and hb[0] < 0.22:
                ground = BT.ST_SHOP                       # 상가주택: shop on the ground floor
        if ground is not None:
            fg = (base + fh - bot) / (top - bot)
            bands = [(ground, 0.0, fg, nf - 1 + (base + fh - bot) / fh, nf - 1.0)] + ([(upper, fg, 1.0, nf - 1.0, 0.0)] if nf > 1 else [])
            st["ground_bands"] = st.get("ground_bands", 0) + 1
        else:
            bands = [(upper, 0.0, 1.0, (top - bot) / fh, 0.0)]
        tops = []
        area_b = float(D["area"][b])
        # rooftop relief (real geometry, small): parapet on multi-storey blocks, a stair / lift core box on taller ones
        ph = (0.9 if cls == BT.HOUSE else 1.1) if (cls in (BT.APT, BT.OFFICE, BT.SHOP, BT.HOUSE) and nf >= 3 and area_b >= 100) else 0.0
        if V3 and ph == 0.0 and cls in (BT.HOUSE, BT.APT, BT.SHOP) and nf >= 2 and area_b >= 80:
            ph = 0.9                                      # v3: flat-roofed 2-storey houses have a parapet too (roof edge reads)
        # v3 gable walls: only the two ends of a slab block (min-area box long / short >= 1.7), not every shorter edge -
        # 11-10 the old rule (edge < 0.5 x longest) made whole faces of stepped / faceted blocks into blank gables (Seomyeon)
        gab = None
        if V3 and upper == BT.ST_APT:
            P2e = ((ecef(rings[0][0], rings[0][1], np.full(len(rings[0][0]), top)) - C0) @ R)[:, :2]
            ob = obb(P2e)
            if ob is not None and ob[1] >= 1.7 * ob[2]:
                gab = ob
        for la, lo in rings:
            Pb = (ecef(la, lo, np.full(len(la), bot)) - C0) @ R          # local ENU
            Pt = (ecef(la, lo, np.full(len(la), top)) - C0) @ R
            tops.append((Pt, la, lo))
            m = len(Pb)
            j = np.arange(m)
            j1 = (j + 1) % m
            d = Pb[j1, :2] - Pb[j, :2]
            ln = np.hypot(d[:, 0], d[:, 1])
            ok = ln > 1e-3
            if not ok.any():
                continue
            per = float(ln[ok].sum())
            nb = max(1, int(round(per / BT.BAY[cls])))                   # whole bays around the ring (continuous u)
            s = np.concatenate(([0.0], np.cumsum(np.where(ok, ln, 0.0))))[:-1] * nb / per
            u0 = s[ok]
            u1 = u0 + ln[ok] * nb / per
            j, j1, d, ln = j[ok], j1[ok], d[ok], ln[ok]
            n2 = np.stack((d[:, 1] / ln, -d[:, 0] / ln, np.zeros(len(j))), axis=1)    # outward = right of the edge
            A0, A1 = Pb[j], Pb[j1]
            # alpha: 128 + 64 x end wall (apartments: edges much shorter than the longest = gable walls) + seed
            if V3:
                endw = np.zeros(len(ln), bool)
                if gab is not None and la is rings[0][0]:
                    ax_, Lx_, Ly_, c_ = gab
                    mid = (A0[:, :2] + A1[:, :2]) / 2 - c_
                    endw = (np.abs((d / ln[:, None]) @ ax_) < 0.5) & (np.abs(mid @ ax_) >= Lx_ / 2 - 0.15 * Lx_) & (ln >= 5.0)
                if endw.any():
                    # gable u = 8192 + 64 x bays of this edge + bays along the edge (0 at its start): the material centres
                    # the painted dong number on it
                    nbE = np.clip(np.round(ln / BT.BAY[cls]), 1, 63)
                    u0 = np.where(endw, 8192.0 + 64.0 * nbE, u0)
                    u1 = np.where(endw, 8192.0 + 65.0 * nbE, u1)
            else:
                endw = (ln < BT.END_WALL_K * ln.max()) & (ln >= 5.0) if cls == BT.APT else np.zeros(len(ln), bool)
            wla = np.concatenate((np.repeat(wl[None], len(ln), axis=0), ((128 + 64 * endw + seed) / 255.0)[:, None]), axis=1)
            if ph > 0:
                # parapet: the top wall band runs on up to top + ph (v < 0 there = parapet, the material draws plain wall),
                # plus one inner face; no extra outer quads
                Pp = (ecef(la, lo, np.full(len(la), top + ph)) - C0) @ R
                vp = ph / fh
                k_ = (top - bot) / (top + ph - bot)
                for t, fa, fb, va, vb in bands:
                    quads(t, A0, A1, Pp[j] - A0, Pp[j1] - A1, fa * k_, 1.0 if fb >= 1.0 else fb * k_, u0, u1, va, -vp if fb >= 1.0 else vb, n2, wla)
                quads(BT.ST_PLAIN, Pt[j1], Pt[j], Pp[j1] - Pt[j1], Pp[j] - Pt[j], 0.0, 1.0, u1, u0, 0.0, -vp, -n2, wla)
            else:
                for t, fa, fb, va, vb in bands:
                    quads(t, A0, A1, Pt[j] - A0, Pt[j1] - A1, fa, fb, u0, u1, va, vb, n2, wla)
        if ph > 0:
            st["parapets"] = st.get("parapets", 0) + 1
        if cls in (BT.APT, BT.OFFICE, BT.SHOP) and nf >= 5 and area_b >= 150 and tops and not V3:
            # footprint and height stay the GIS values (no invented setbacks); only rooftop plant / stair-lift cores
            if roof_core(WL, tops[0][0], area_b, 4.5 if cls == BT.APT else 3.5, wl, seed):
                st["cores"] = st.get("cores", 0) + 1
        elif V3 and tops:
            # v3 rooftop props (footprint / height stay GIS; things ON the roof only): lift machine room + water tank on
            # apartments / offices, a water tank and a laundry rack on low houses / villas
            P2 = tops[0][0][:, :2]
            z0 = float(tops[0][0][:, 2].min())
            dd = np.roll(P2, -1, axis=0) - P2
            ll = np.hypot(dd[:, 0], dd[:, 1])
            ax = dd[int(np.argmax(ll))] / max(ll.max(), 1e-6)
            if cls in (BT.APT, BT.OFFICE, BT.SHOP) and nf >= 5 and area_b >= 150 and upper != BT.ST_VILLA:
                L, W = np.clip(0.30 * math.sqrt(area_b), 3.0, 9.0), np.clip(0.18 * math.sqrt(area_b), 2.5, 6.0)
                hc = 4.5 if cls == BT.APT else 3.5
                n_core = 2 if (gab is not None and gab[1] > 45.0) else 1   # long slabs: a core per stair group
                for ic in range(n_core):
                    axc = ax if n_core == 1 else gab[0]
                    cc = P2.mean(0) if n_core == 1 else gab[3] + gab[0] * gab[1] * (-0.25 if ic == 0 else 0.25)
                    cs = rect(cc, axc, L, W)
                    if not inside(P2, cs):
                        continue
                    box(cs, z0, hc, BT.ST_PROP, prop_rgba(BT.srgb_to_lin(wall) * 0.92, BT.PROP_ROOM, seed))
                    st["cores"] = st.get("cores", 0) + 1
                    if cls == BT.APT or hb[1] < 0.5:     # water tank on the machine room (FRP panels; offices: steel)
                        steel = cls != BT.APT
                        col = (0.62, 0.63, 0.64) if steel else TANK_FRP[int(hb[2] * len(TANK_FRP)) % len(TANK_FRP)]
                        tl, tw = min(L * 0.6, 6.0), min(W * 0.75, 3.5)
                        box(rect(cs.mean(0), axc, tl, tw), z0 + hc, 2.0, BT.ST_PROP,
                            prop_rgba(BT.srgb_to_lin(col), BT.PROP_TANK_STEEL if steel else BT.PROP_TANK, seed))
                        st["tanks"] = st.get("tanks", 0) + 1
            elif (cls == BT.HOUSE or upper == BT.ST_VILLA) and nf <= 5 and area_b >= 40:
                zr = z0
                if hb[3] < 0.45:                          # water tank: blue FRP / stainless box
                    steel = hb[4] < 0.35
                    col = (0.66, 0.68, 0.70) if steel else ((0.27, 0.43, 0.64) if hb[5] < 0.6 else (0.78, 0.81, 0.82))
                    cs = spot(P2, ax, 1.6, 1.1, hb[2])
                    if cs is not None:
                        box(cs, zr, 1.3, BT.ST_PROP, prop_rgba(BT.srgb_to_lin(col), BT.PROP_TANK_STEEL if steel else BT.PROP_TANK, seed))
                        st["tanks"] = st.get("tanks", 0) + 1
                if hb[4] > 0.75 and area_b >= 60:         # laundry rack (thin double-faced panel, hanging clothes)
                    cs = spot(P2, np.array([-ax[1], ax[0]]), 2.4, 0.08, 1.0 - hb[2], margin=0.8)
                    if cs is not None:
                        box(cs, zr + 0.35, 1.0, BT.ST_PROP, prop_rgba((0.6, 0.6, 0.6), BT.PROP_LAUNDRY, seed))
                        st["laundry"] = st.get("laundry", 0) + 1
        # roof: earcut on the top ring points (exterior first, then holes)
        verts = np.concatenate([t[0] for t in tops])
        ends = np.cumsum([len(t[0]) for t in tops]).astype(np.uint32)
        tri = np.asarray(earcut.triangulate_float64(verts[:, :2], ends), dtype=np.int64).reshape(-1, 3)
        if len(tri):
            p0, p1, p2 = verts[tri[:, 0], :2], verts[tri[:, 1], :2], verts[tri[:, 2], :2]
            cw = ((p1[:, 0] - p0[:, 0]) * (p2[:, 1] - p0[:, 1]) - (p1[:, 1] - p0[:, 1]) * (p2[:, 0] - p0[:, 0])) < 0
            tri[cw] = tri[cw][:, ::-1]
            if smp is not None:
                ox, oy, f = place[ci]
                la = np.concatenate([t[1] for t in tops])
                lo = np.concatenate([t[2] for t in tops])
                X, Y = BT.Sat.px(smp["z"], la, lo)
                uv = np.stack((((X - smp["x0"]) * f + ox) / AW, ((Y - smp["y0"]) * f + oy) / AH), axis=1)
                col = np.ones(3)
            else:
                uv = np.tile(white, (len(verts), 1))
                col = roof_pal[k]
            RF["P"].append(verts)
            RF["N"].append(np.tile([0.0, 0.0, 1.0], (len(verts), 1)))
            RF["C"].append(np.repeat(np.append(np.asarray(col, np.float64), 1.0)[None], len(verts), axis=0))
            RF["UV"].append(uv)
            RF["I"].append(tri.reshape(-1) + RF["n"])
            RF["n"] += len(verts)
        if smp is not None:
            ci += 1
    S = np.array([[1, 0, 0], [0, 0, 1], [0, -1, 0]], np.float64)            # ENU -> glTF (y-up): (E, N, U) -> (E, U, -N)
    prims, allP = [], []
    wall_imgs = BT.wall_pngs()
    images, mats = [("image/jpeg", jpg, 0)], [("roof", 0, 0.95)]
    groups = [(RF, 0)]
    png_img = {}
    for t in sorted(WL):                                  # t = facade style; roughnessFactor carries it to the material
        pi = BT.STYLE_PNG[t]
        if pi not in png_img:
            images.append(("image/png", wall_imgs[pi], 1))
            png_img[pi] = len(images) - 1
        mats.append(("facade_" + BT.STYLE_NAMES[t], png_img[pi], BT.style_roughness(t)))
        groups.append((WL[t], len(mats) - 1))
    for G, mat in groups:
        if not G["P"]:
            continue
        P, Nn, Cc, UV, I = (np.concatenate(G[x]) for x in ("P", "N", "C", "UV", "I"))
        allP.append(P)
        Cg = np.clip(np.round(Cc * 255), 0, 255).astype(np.uint8)
        prims.append(dict(P=(P @ S.T).astype(np.float32), N=(Nn @ S.T).astype(np.float32), C=Cg, UV=UV.astype(np.float32),
                          I=I.astype(np.uint32), material=mat))
    Z2Y = np.array([[1, 0, 0], [0, 0, 1], [0, -1, 0]], np.float64)          # Cesium applies Y_UP_TO_Z_UP = inverse of this
    M = np.eye(4)
    M[:3, :3] = Z2Y @ R @ S.T
    M[:3, 3] = Z2Y @ C0
    P = np.concatenate(allP)
    hmin = float((P @ np.array([0, 0, 1.0])).min())
    st["verts"] = int(len(P))
    st["roof_jpg"] = len(jpg)
    st["primitives"] = len(prims)
    return glb_bytes(prims, images, mats, M), (P, hmin, st)


def glb_bytes(prims, images, mats, M):
    """prims: dicts P, N, C, UV, I, material index; images: (mime, bytes, sampler 0 = clamp | 1 = repeat);
    mats: (name, texture = image index, roughness). Base colour = texture x vertex colour (COLOR_0)."""
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
    mp = []
    for p in prims:
        nv, a = len(p["P"]), len(accs)
        accs += [dict(bufferView=view(p["P"].tobytes(), 34962), componentType=5126, count=nv, type="VEC3", min=p["P"].min(0).tolist(), max=p["P"].max(0).tolist()),
                 dict(bufferView=view(p["N"].tobytes(), 34962), componentType=5126, count=nv, type="VEC3"),
                 dict(bufferView=view(p["C"].tobytes(), 34962), componentType=5121, normalized=True, count=nv, type="VEC4"),
                 dict(bufferView=view(p["UV"].tobytes(), 34962), componentType=5126, count=nv, type="VEC2"),
                 dict(bufferView=view(p["I"].tobytes(), 34963), componentType=5125, count=len(p["I"]), type="SCALAR")]
        mp.append(dict(attributes=dict(POSITION=a, NORMAL=a + 1, COLOR_0=a + 2, TEXCOORD_0=a + 3), indices=a + 4, material=p["material"], mode=4))
    imgs = [dict(bufferView=view(data), mimeType=mt) for mt, data, _ in images]
    blob.extend(b"\0" * ((-len(blob)) % 4))
    gl = dict(asset=dict(version="2.0", generator="gyro-sim-chair buildings_build.py"), scene=0, scenes=[dict(nodes=[0])],
              nodes=[dict(mesh=0, matrix=[float(v) for v in M.T.reshape(-1)])], meshes=[dict(primitives=mp)],
              # 33071 CLAMP_TO_EDGE, 10497 REPEAT, 9729 LINEAR, 9987 LINEAR_MIPMAP_LINEAR (Cesium makes the mip maps)
              samplers=[dict(magFilter=9729, minFilter=9987, wrapS=33071, wrapT=33071), dict(magFilter=9729, minFilter=9987, wrapS=10497, wrapT=10497)],
              images=imgs, textures=[dict(source=i, sampler=sm) for i, (_, _, sm) in enumerate(images)],
              materials=[dict(name=nm, pbrMetallicRoughness=dict(baseColorTexture=dict(index=ti), metallicFactor=0.0, roughnessFactor=r))
                         for nm, ti, r in mats],
              accessors=accs, bufferViews=views, buffers=[dict(byteLength=len(blob))])
    js = json.dumps(gl, separators=(",", ":")).encode()
    js += b" " * ((-len(js)) % 4)
    total = 12 + 8 + len(js) + 8 + len(blob)
    return struct.pack("<III", 0x46546C67, 2, total) + struct.pack("<II", len(js), 0x4E4F534A) + js + struct.pack("<II", len(blob), 0x004E4942) + bytes(blob)


def work_files(args=()):
    """work/buildings_<name>.npz to use: --only a,b or all of them (one per prep run: region or province)."""
    import glob
    fs = sorted(glob.glob(os.path.join(WORK, "buildings_*.npz")))
    if "--only" in args:
        keep = set(args[args.index("--only") + 1].split(","))
        fs = [f for f in fs if os.path.basename(f)[10:-4] in keep]
    assert fs, ("no work files - run --prep first", WORK)
    return fs


def stats_file(work):
    return os.path.join(os.path.dirname(work), "stats_%s.json" % os.path.basename(work)[10:-4])


MERGED = os.path.join(WORK, "_merged")
KEYS = ("lon", "lat", "nring", "ring_of_poly", "h", "src", "base", "geoid", "area", "clat", "clon", "rid", "floors", "use")
# uid = SHP field A1 (unique per building record: 472,581 values in 472,608 Busan records; A0 = rid repeats, 63,720 values)
OPT_KEYS = ("uid",)


def merge_work(files):
    """concatenate the work files (polygon indices shifted) into MERGED/*.npy, read memory-mapped by the tile
    workers (a nationwide build is ~14 M footprints: one copy on disk instead of one per process)."""
    os.makedirs(MERGED, exist_ok=True)
    out = {k: [] for k in KEYS}
    npoly = 0
    for f in files:
        z = np.load(f)
        assert "use" in z.files, ("work file from before the textures (no use class) - run --prep again", f)
        for k in KEYS:
            v = z[k]
            out[k].append(v + npoly if k == "ring_of_poly" else v)
        npoly += len(z["h"])
    for k in KEYS:
        np.save(os.path.join(MERGED, k + ".npy"), np.concatenate(out[k]))
    for k in OPT_KEYS:                                    # only when every work file has it (older preps: --prep again)
        zs = [np.load(f) for f in files]
        p_ = os.path.join(MERGED, k + ".npy")
        if all(k in z.files for z in zs):
            np.save(p_, np.concatenate([z[k] for z in zs]))
        elif os.path.exists(p_):
            os.remove(p_)
    with open(os.path.join(MERGED, "inputs.json"), "w") as fo:
        json.dump(dict(made=time.strftime("%Y-%m-%d %H:%M:%S"), files=files, buildings=npoly), fo, indent=1)


def load_work(path=None):
    """one work file (path) or the merged set (MERGED, memory-mapped)."""
    if path:
        z = np.load(path)
        D = {k: z[k] for k in KEYS}
    else:
        D = {k: np.load(os.path.join(MERGED, k + ".npy"), mmap_mode="r") for k in KEYS}
        for k in OPT_KEYS:
            if os.path.exists(os.path.join(MERGED, k + ".npy")):
                D[k] = np.load(os.path.join(MERGED, k + ".npy"), mmap_mode="r")
    nring = D["nring"].astype(np.int64)
    D["ring_v"] = np.concatenate(([0], np.cumsum(nring)))
    rp = D["ring_of_poly"].astype(np.int64)
    npoly = len(D["h"])
    cnt = np.bincount(rp, minlength=npoly)
    D["poly_ring"] = np.concatenate(([0], np.cumsum(cnt)))
    return D


_W = {}


def _tile_job(job):
    key, sel, center, path = job
    D = _W.get("D")
    if D is None:
        D = _W["D"] = load_work()
    data, info = build_glb(D, np.asarray(sel), center)
    if data is None:
        return key, None, None
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(data)
    return key, len(data), info[2]


def tiles(args):
    import multiprocessing as mp
    t0 = time.time()
    files = work_files(args)
    merge_work(files)
    D = load_work()
    h, area, lat, lon = D["h"], D["area"], D["clat"], D["clon"]
    roof_e = D["base"] + h + D["geoid"] + 5.0                 # + parapet / rooftop core (build_glb)
    bot_e = D["base"] + D["geoid"] - WALL_SINK
    cls = np.where(is_a(h, area), 0, np.where(is_b(h, area), 1, 2))
    dla, dlo = STEP_A
    ia, ja = np.floor(lat / dla).astype(np.int64), np.floor(lon / dlo).astype(np.int64)
    ib, jb = np.floor(lat / (dla / SUB_B)).astype(np.int64), np.floor(lon / (dlo / SUB_B)).astype(np.int64)
    ic, jc = np.floor(lat / (dla / SUB_B / SUB_C)).astype(np.int64), np.floor(lon / (dlo / SUB_B / SUB_C)).astype(np.int64)
    # tile extents from the actual vertices (a footprint may poke out of its tile: the bounding volume must hold it)
    pmin_lat = np.minimum.reduceat(D["lat"], D["ring_v"][D["poly_ring"][:-1]])
    pmax_lat = np.maximum.reduceat(D["lat"], D["ring_v"][D["poly_ring"][:-1]])
    pmin_lon = np.minimum.reduceat(D["lon"], D["ring_v"][D["poly_ring"][:-1]])
    pmax_lon = np.maximum.reduceat(D["lon"], D["ring_v"][D["poly_ring"][:-1]])
    # landmarks replaced by real 3D models (other tool): C:/GyroSimTiles/landmarks/exclude.json = list of uid
    # (= the SHP field A1, a 28-digit string, work npz "uid"; NOT A0 / rid, which repeats); left out of the tiles.
    # No file = nothing skipped.
    skip = np.zeros(len(h), bool)
    if os.path.isfile(EXCLUDE):
        with open(EXCLUDE, encoding="utf-8") as f:
            ex = json.load(f)
        ids = ex.get("ids", ex.get("rid", [])) if isinstance(ex, dict) else ex
        assert "uid" in D, "work files without uid (A1): run --prep again before using " + EXCLUDE
        skip = np.isin(np.asarray(D["uid"]), np.asarray([str(x).strip() for x in ids]))
        print("landmarks: %d ids in %s, %d buildings left out" % (len(ids), EXCLUDE, int(skip.sum())), flush=True)
    groups = {}
    for b in range(len(h)):
        if skip[b]:
            continue
        c = int(cls[b])
        key = ("a", int(ia[b]), int(ja[b])) if c == 0 else ("b", int(ib[b]), int(jb[b])) if c == 1 else ("c", int(ic[b]), int(jc[b]))
        groups.setdefault(key, []).append(b)
    jobs = []
    for key, sel in groups.items():
        lvl, i, j = key
        step = {"a": 1, "b": SUB_B, "c": SUB_B * SUB_C}[lvl]
        center = ((i + 0.5) * dla / step, (j + 0.5) * dlo / step)
        jobs.append((key, sel, center, os.path.join(TILES, lvl, "%d_%d.glb" % (i, j))))
    jobs.sort(key=lambda j: -len(j[1]))
    print("tiles: %d content tiles (a %d, b %d, c %d), %d buildings" % (len(jobs), sum(1 for j in jobs if j[0][0] == "a"), sum(1 for j in jobs if j[0][0] == "b"),
          sum(1 for j in jobs if j[0][0] == "c"), len(h)), flush=True)
    if os.path.isdir(TILES):                                  # stale glb from an older build would be served by name
        import shutil
        shutil.rmtree(TILES)
    os.makedirs(TILES, exist_ok=True)
    sizes = {}
    tex = dict(buildings=0, roof_photo={}, color_photo=0, palette=0, floors_data=0, verts=0, roof_jpg_bytes=0, atlas_px=0, styles={})
    import buildings_tex as BT
    BT_STYLE = BT.STYLE_NAMES
    with mp.Pool(max(1, (os.cpu_count() or 4) - 2)) as pool:
        for n_done, (key, nb, ts_) in enumerate(pool.imap_unordered(_tile_job, jobs, chunksize=1), 1):
            if nb:
                sizes[key] = nb
                for k_ in ("buildings", "color_photo", "palette", "floors_data", "verts", "parapets", "cores", "tanks", "laundry", "ground_bands"):
                    tex[k_] = tex.get(k_, 0) + ts_.get(k_, 0)
                for s_, c_ in ts_["styles"].items():
                    tex["styles"][BT_STYLE[s_]] = tex["styles"].get(BT_STYLE[s_], 0) + c_
                for z_, c_ in ts_["roof_photo"].items():
                    tex["roof_photo"][str(z_)] = tex["roof_photo"].get(str(z_), 0) + c_
                tex["roof_jpg_bytes"] += ts_["roof_jpg"]
                tex["atlas_px"] += ts_["atlas"][0] * ts_["atlas"][1]
            if n_done % 200 == 0 or n_done == len(jobs):
                print("  %d / %d  %.0f s  %.0f MB" % (n_done, len(jobs), time.time() - t0, sum(sizes.values()) / 1e6), flush=True)

    # tile tree: root -> a (8 km) -> b (2 km) -> c (1 km); bounding regions from the footprints inside (incl. children)
    def bv(sel):
        sel = np.asarray(sel)
        return [math.radians(float(pmin_lon[sel].min())), math.radians(float(pmin_lat[sel].min())), math.radians(float(pmax_lon[sel].max())),
                math.radians(float(pmax_lat[sel].max())), float(bot_e[sel].min()), float(roof_e[sel].max())]

    def union(a, b):
        return [min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3]), min(a[4], b[4]), max(a[5], b[5])]
    tree = {}
    for b in range(len(h)):
        tree.setdefault((int(ia[b]), int(ja[b])), {}).setdefault((int(ib[b]), int(jb[b])), {}).setdefault((int(ic[b]), int(jc[b])), None)
    nodes_a = []
    for (i, j), bs in sorted(tree.items()):
        kids_b = []
        for (bi, bj), cs in sorted(bs.items()):
            kids_c = []
            for (ci, cj) in sorted(cs):
                k = ("c", ci, cj)
                if k in sizes:
                    kids_c.append(dict(boundingVolume=dict(region=bv(groups[k])), geometricError=GE["c"], content=dict(uri="c/%d_%d.glb" % (ci, cj))))
            k = ("b", bi, bj)
            node = dict(geometricError=GE["b"], children=kids_c) if kids_c else dict(geometricError=GE["b"])
            reg = None
            for ch in kids_c:
                reg = ch["boundingVolume"]["region"] if reg is None else union(reg, ch["boundingVolume"]["region"])
            if k in sizes:
                node["content"] = dict(uri="b/%d_%d.glb" % (bi, bj))
                r = bv(groups[k])
                reg = r if reg is None else union(reg, r)
            if reg is None:
                continue
            if not kids_c:
                node["geometricError"] = 0.0
            node["boundingVolume"] = dict(region=reg)
            kids_b.append(node)
        k = ("a", i, j)
        node = dict(geometricError=GE["a"], children=kids_b)
        reg = None
        for ch in kids_b:
            reg = ch["boundingVolume"]["region"] if reg is None else union(reg, ch["boundingVolume"]["region"])
        if k in sizes:
            node["content"] = dict(uri="a/%d_%d.glb" % (i, j))
            r = bv(groups[k])
            reg = r if reg is None else union(reg, r)
        if reg is None:
            continue
        if not kids_b:
            node.pop("children")
            node["geometricError"] = 0.0
        node["boundingVolume"] = dict(region=reg)
        nodes_a.append(node)
    reg = None
    for ch in nodes_a:
        reg = ch["boundingVolume"]["region"] if reg is None else union(reg, ch["boundingVolume"]["region"])
    sts = [json.load(open(stats_file(f), encoding="utf-8")) for f in files]
    ts = dict(asset=dict(version="1.1", tilesetVersion=time.strftime("%Y%m%d%H%M%S"), generator="gyro-sim-chair sim/buildings_build.py",
                         copyright=ATTRIB, extras=dict(source="국토교통부 GIS건물통합정보", inputs=sorted({i["file"] for st in sts for i in st["inputs"]}))),
              geometricError=GE["root"] * 2, root=dict(boundingVolume=dict(region=reg), geometricError=GE["root"], refine="ADD", children=nodes_a))
    with open(os.path.join(TILES, "tileset.json"), "w", encoding="utf-8") as f:
        json.dump(ts, f, ensure_ascii=False)
    out = dict(made=time.strftime("%Y-%m-%d %H:%M:%S"), seconds=round(time.time() - t0), content_tiles=len(sizes), bytes=sum(sizes.values()),
               bytes_by_level={l: sum(v for k, v in sizes.items() if k[0] == l) for l in "abc"}, largest_tile=max(sizes.values()) if sizes else 0,
               input=dict(work=files, prep=[st["made"] for st in sts]), buildings=int(len(h)), textures=tex,
               satellite_cache=dict(dir=_sat().root, tiles_by_zoom=_sat().tiles_count()) if _sat() else None, geometric_error=GE, step_a=STEP_A, sub=[SUB_B, SUB_C])
    with open(os.path.join(TILES, "build.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, indent=1)
    print("done: %d tiles, %.0f MB (a %.0f, b %.0f, c %.0f MB), largest %.1f MB, %.0f s -> %s" % (
        len(sizes), out["bytes"] / 1e6, out["bytes_by_level"]["a"] / 1e6, out["bytes_by_level"]["b"] / 1e6, out["bytes_by_level"]["c"] / 1e6,
        out["largest_tile"] / 1e6, out["seconds"], TILES), flush=True)


# ---- step 3: ground raster (server crash check) ------------------------------------------------------------------------
GROUND_PX = 3 * T.PX                                      # 1/3 arc-second (~10 x 8 m)


def ground(args):
    for f in work_files(args):
        ground_one(f)


def ground_one(path):
    import shapely
    from rasterio import features
    from rasterio.transform import Affine
    t0 = time.time()
    name = os.path.basename(path)[10:-4]
    D = load_work(path)
    h = D["h"]
    roof = D["base"] + h                                  # MSL (JSBSim / terrain_dem heights are MSL)
    w = math.floor(float(D["lon"].min()) * 3600) / 3600 - 1 / 3600
    e = math.ceil(float(D["lon"].max()) * 3600) / 3600 + 1 / 3600
    s = math.floor(float(D["lat"].min()) * 3600) / 3600 - 1 / 3600
    n = math.ceil(float(D["lat"].max()) * 3600) / 3600 + 1 / 3600
    W, H = int(round((e - w) * GROUND_PX)), int(round((n - s) * GROUND_PX))
    tr = Affine(1.0 / GROUND_PX, 0, w, 0, -1.0 / GROUND_PX, n)
    order = np.argsort(roof)                               # later shapes overwrite: highest roof wins
    rings_v, poly_ring = D["ring_v"], D["poly_ring"]

    def shapes():
        for b in order:
            rs = []
            for r in range(poly_ring[b], poly_ring[b + 1]):
                v0, v1 = rings_v[r], rings_v[r + 1]
                rs.append(np.stack((D["lon"][v0:v1], D["lat"][v0:v1]), axis=1))
            yield shapely.Polygon(rs[0], rs[1:]), int(round(float(roof[b]) * 10))
    a = features.rasterize(shapes(), out_shape=(H, W), transform=tr, fill=-32768, all_touched=True, dtype="int16")
    os.makedirs(GROUND, exist_ok=True)
    np.save(os.path.join(GROUND, "roof_%s.npy" % name), a)
    meta = dict(made=time.strftime("%Y-%m-%d %H:%M:%S"), west=w, north=n, px_per_deg=GROUND_PX, shape=[H, W], units="int16 decimetres MSL roof, -32768 = no building",
                buildings=int(len(h)), cells_with_building=int((a > -32768).sum()), input=dict(work=path), seconds=round(time.time() - t0))
    with open(os.path.join(GROUND, "roof_%s.json" % name), "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=1)
    print("ground raster %d x %d, %d cells with buildings, %.0f s -> %s" % (W, H, meta["cells_with_building"], meta["seconds"], GROUND), flush=True)


if __name__ == "__main__":
    a = sys.argv[1:]
    if "--prep" in a or "--all" in a:
        prep(a)
    if "--tiles" in a or "--all" in a:
        tiles(a)
    if "--ground" in a or "--all" in a:
        ground(a)
    if "--stats" in a:
        for f in work_files(a):
            print(open(stats_file(f), encoding="utf-8").read())
    if not a:
        print(__doc__)
