"""Coastal building spikes in the Copernicus DEM (a surface model) along the Busan shore - and the terrain tiles over them.

Problem (11-10, Marine City seen from the sea): GLO-30 is a DSM, so towers standing right at the sea wall left 15-28 m
'hills' in the first one or two land cells next to the 0 m sea (e.g. 35.1542 N 129.1450 E: 28 m between 4-6 m promenade
cells). Elsewhere the building tiles hide such DSM bumps, but at the shore the mesh rises from the sea to 20+ m within one
30 m cell and the V-World photo of the sea wall / tetrapods / roofs is stretched over that slope: a white hump on the
waterline.

Fix: land cells <= 2.5 cells from the sea, at least DROP_M above the median of their 7 x 7 land neighbourhood, and with
a GIS building footprint (AL_D010 Busan) within FOOT_M of the cell centre are set to that median (natural cliffs -
Igidae, Oryukdo, Taejongdae - have no buildings and stay). Changed cells -> proc/coastfix.json; the original cell array is
kept once as proc/dem_<cell>.pre_coastfix.npy; terrain_build.prep() re-applies coastfix.json, so a later --prep keeps it.

    python -I sim/terrain_coastfix.py --find      list the cells (nothing written)
    python -I sim/terrain_coastfix.py --apply     write the cells into proc/*.npy + coastfix.json, rebuild the terrain
                                                  tiles that cover them (all levels, same encoder as terrain_build)
Server (JSBSim terrain) and building / tree / road builders read the same proc grid: they see the fix on their next start
/ build. Buildings near the fixed cells stand on the lowest mesh around their footprint (unchanged cells), so they stay
on the ground.
"""
import json, math, os, sys, time, zipfile, site
if sys.flags.isolated:
    site.addsitedir(site.getusersitepackages())
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import numpy as np                                        # noqa: E402
import terrain_dem as T                                   # noqa: E402

BOX = (128.75, 34.96, 129.33, 35.40)                      # w s e n (terrain_dem.HIRES busan)
ZIP = os.path.join(r"C:\GyroSimTiles\incoming\zips", "AL_D010_26_20261009.zip")    # GIS buildings, Busan
DROP_M, DIST_CELLS, FOOT_M, WIN = 6.0, 2.5, 8.0, 7
FIX_JSON = os.path.join(T.PROC, "coastfix.json")


def _cells():
    out = []
    for lat0 in range(int(math.floor(BOX[1])), int(math.ceil(BOX[3]))):
        for lon0 in range(int(math.floor(BOX[0])), int(math.ceil(BOX[2]))):
            p = os.path.join(T.PROC, "dem_%s.npy" % T.cell_name(lat0, lon0))
            if os.path.exists(p) and not p.endswith(".pre_coastfix.npy"):
                out.append((lat0, lon0, p))
    return out


def find():
    from scipy import ndimage as nd
    cands = []
    for lat0, lon0, p in _cells():
        bak = p[:-4] + ".pre_coastfix.npy"                  # re-runs start from the unfixed grid
        a = np.load(bak if os.path.exists(bak) else p).astype(np.float32) * 0.1
        lat = lat0 + 1 - np.arange(T.PX) / T.PX
        lon = lon0 + np.arange(T.PX) / T.PX
        r0, r1 = np.searchsorted(-lat, -BOX[3]), np.searchsorted(-lat, -BOX[1])
        c0, c1 = np.searchsorted(lon, BOX[0]), np.searchsorted(lon, BOX[2])
        pad = WIN
        R0, R1, C0, C1 = max(0, r0 - pad), min(T.PX, r1 + pad), max(0, c0 - pad), min(T.PX, c1 + pad)
        s = a[R0:R1, C0:C1]
        sea = s == 0
        land = ~sea
        dsea = nd.distance_transform_edt(~sea)
        cnt = nd.uniform_filter(land.astype(np.float32), WIN) * WIN * WIN
        near = land & (dsea <= DIST_CELLS) & (cnt >= 15)
        ys, xs = np.nonzero(near & (s > DROP_M))
        h = WIN // 2
        for y, x in zip(ys, xs):
            win = s[max(0, y - h):y + h + 1, max(0, x - h):x + h + 1]
            med = float(np.median(win[win != 0]))
            if s[y, x] >= med + DROP_M:
                cands.append(dict(cell=T.cell_name(lat0, lon0), r=int(R0 + y), c=int(C0 + x), lat=float(lat[R0 + y]),
                                  lon=float(lon[C0 + x]), old=round(float(s[y, x]), 1), new=round(med, 1), sea_cells=round(float(dsea[y, x]), 1)))
    if not cands:
        return []
    import pyogrio, shapely
    from pyproj import Transformer
    tf = Transformer.from_crs("EPSG:4326", "EPSG:5186", always_xy=True)
    xs, ys = tf.transform([c["lon"] for c in cands], [c["lat"] for c in cands])
    bb = (min(xs) - 100, min(ys) - 100, max(xs) + 100, max(ys) + 100)
    shps = ["/vsizip/%s/%s" % (ZIP.replace("\\", "/"), m) for m in zipfile.ZipFile(ZIP).namelist() if m.lower().endswith(".shp")]
    geoms = []
    for sp in shps:
        df = pyogrio.read_dataframe(sp, encoding="cp949", columns=["A1"], bbox=bb)
        geoms += list(df.geometry.values)
    tree = shapely.STRtree(geoms)
    out = []
    for c, x, y in zip(cands, xs, ys):
        d = tree.query_nearest(shapely.Point(x, y), max_distance=FOOT_M, return_distance=True)
        c["building_m"] = round(float(d[1][0]), 1) if len(d[0]) else None
        if c["building_m"] is not None:
            out.append(c)
    # the 30 m DSM smears a tower over its neighbour cells: candidates touching an accepted cell are the same blob
    acc = {(c["cell"], c["r"], c["c"]) for c in out}
    grow = True
    while grow:
        grow = False
        for c in cands:
            k = (c["cell"], c["r"], c["c"])
            if k not in acc and any((c["cell"], c["r"] + i, c["c"] + j) in acc for i in (-1, 0, 1) for j in (-1, 0, 1)):
                c["adjacent"] = True
                acc.add(k)
                out.append(c)
                grow = True
    print("candidates %d, with a GIS building within %.0f m (or touching such a cell): %d" % (len(cands), FOOT_M, len(out)))
    return out


def apply_saved(q, lat0, lon0):
    """terrain_build.prep hook: the saved fix on a freshly processed int16 cell array."""
    if not os.path.exists(FIX_JSON):
        return q
    name = T.cell_name(lat0, lon0)
    for c in json.load(open(FIX_JSON, encoding="utf-8"))["cells"]:
        if c["cell"] == name:
            q[c["r"], c["c"]] = int(round(c["new"] * 10))
    return q


def rebuild_tiles(fix):
    import terrain_build as B
    w = min(c["lon"] for c in fix) - 2.0 / T.PX
    e = max(c["lon"] for c in fix) + 2.0 / T.PX
    s = min(c["lat"] for c in fix) - 2.0 / T.PX
    n = max(c["lat"] for c in fix) + 2.0 / T.PX
    pts = [(c["lat"], c["lon"]) for c in fix]
    plan = B.plan_tiles()
    jobs = []
    for L, lst in plan.items():
        if L < 10:                                        # levels < 10 sample the 4" / 16" overviews (unchanged, sub-cell bumps)
            continue
        for x, y, nv in lst:
            tw, ts, te, tn = B.tile_rect(L, x, y)
            if te < w or tw > e or tn < s or ts > n:
                continue
            m = 2.0 / T.PX
            if any(ts - m <= la <= tn + m and tw - m <= lo <= te + m for la, lo in pts):
                jobs.append((L, x, y, nv))
    dem = T.Dem()
    for c in fix:                                        # patched copies in the Dem cache (the proc file may be held
        key = (int(c["cell"][1:3]), int(c["cell"][4:7]))   # memory-mapped by a running server -> not rewritable now)
        if not isinstance(dem._mm.get(key), np.ndarray) or dem._mm[key].flags.writeable is False:
            dem._mm[key] = np.array(np.load(dem.cells[key]))
        dem._mm[key][c["r"], c["c"]] = int(round(c["new"] * 10))
    for L, x, y, nv in jobs:
        data, _, _ = B.encode_tile(dem, L, x, y, nv)
        p = os.path.join(T.TILES, str(L), str(x), "%d.terrain" % y)
        if os.path.exists(p) and not os.path.exists(p + ".pre_coastfix"):
            os.replace(p, p + ".pre_coastfix")
        with open(p, "wb") as f:
            f.write(data)
    print("rebuilt %d terrain tiles (levels %s)" % (len(jobs), sorted({j[0] for j in jobs})))
    return jobs


def apply():
    fix = find()
    by = {}
    for c in fix:
        by.setdefault(c["cell"], []).append(c)
    pending = []
    for name, lst in by.items():
        p = os.path.join(T.PROC, "dem_%s.npy" % name)
        bak = p[:-4] + ".pre_coastfix.npy"
        if not os.path.exists(bak):
            np.save(bak, np.load(p))
        q = np.load(p)
        for c in lst:
            q[c["r"], c["c"]] = int(round(c["new"] * 10))
        try:
            np.save(p, q)
        except OSError as e:                              # held open (memory-mapped) by the running sim server
            pending.append(name)
            print("proc %s not written now (%s): the terrain tiles get the fix, the server's height grid after a"
                  " re-run of --apply with the server stopped" % (name, e.strerror))
    jobs = rebuild_tiles(fix) if fix else []
    with open(FIX_JSON, "w", encoding="utf-8") as f:
        json.dump(dict(made=time.strftime("%Y-%m-%d %H:%M:%S"), rule=dict(drop_m=DROP_M, dist_cells=DIST_CELLS, foot_m=FOOT_M, win=WIN, box=BOX),
                       buildings=os.path.basename(ZIP), proc_pending=pending, cells=fix, tiles=[list(j) for j in jobs]), f, indent=1)
    print("coastfix: %d cells -> %s" % (len(fix), FIX_JSON))


if __name__ == "__main__":
    if "--apply" in sys.argv:
        apply()
    elif "--find" in sys.argv:
        for c in find():
            print(c)
    else:
        print(__doc__)
