"""Build the South Korea terrain for Cesium for Unreal (quantized-mesh-1.0 + layer.json) from the Copernicus DEM.

    python sim/terrain_fetch.py              1. download (C:\\GyroSimTiles\\terrain\\raw)
    python sim/terrain_build.py --prep       2. raw COG -> proc/*.npy (int16 dm MSL, airfield flattened) + overviews
    python sim/terrain_build.py --check      3. sanity table: summits / sea / airfields (raw and processed) -> proc/check.json
    python sim/terrain_build.py --tiles      4. proc -> tiles/ (layer.json + {z}/{x}/{y}.terrain), all cores
    python sim/terrain_build.py --all        2 + 3 + 4
Served by sim/vworld_proxy.py at http://127.0.0.1:8790/terrain/layer.json (the Unreal 'vworld' ground mode).

Tiles: geographic tiling (EPSG:4326, TMS rows from the south, level 0 = 2 tiles), regular grid meshes, ellipsoid
heights h = H_msl + N_egm2008 (terrain_dem.py), oct-encoded vertex normals (extension 'octvertexnormals'), gzip.
  - levels 0-4 : whole globe (heights = geoid only outside the data, 33 x 33 vertices)
  - levels 5-9 : every tile touching the geoid window 120-136 E, 29-43 N (sea around Korea, no big chord sag)
  - levels 10-13: only tiles with land in the DEM box (65 x 65 vertices; level 13 ~ 38 x 31 m spacing = the DEM)
Height source per level: 1" grid (<= 8" vertex spacing), 4" mean (<= 32"), 16" mean (coarser) - no aliasing.
"""
import gzip, json, math, os, struct, sys, time
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import terrain_dem as T                                   # noqa: E402
import terrain_fetch as F                                 # noqa: E402

A_WGS, B_WGS = 6378137.0, 6356752.3142451793
E2 = 6.69437999014e-3
MAX_LEVEL = 13
GLOBAL_MAX, REGION_MAX = 4, 9
REGION = F.GEOID_BOX                                      # (w, s, e, n)
ATTRIB = ("Terrain: Copernicus DEM GLO-30 © DLR e.V. 2010-2014 and © Airbus Defence and Space GmbH 2014-2018 provided "
          "under COPERNICUS by the European Union and ESA; all rights reserved")


# ---- step 2: prep ----------------------------------------------------------------------------------------------------
def prep():
    import rasterio
    os.makedirs(T.PROC, exist_ok=True)
    k4, k16 = T.PX // 4, T.PX // 16
    ov4 = np.zeros((T.NROW // 4, T.NCOL // 4), np.float32)
    ov16 = np.zeros((T.NROW // 16, T.NCOL // 16), np.float32)
    land4 = np.zeros((T.NROW // 4, T.NCOL // 4), np.uint8)
    info = {}
    for lat0, lon0, what in F.TILES:
        p = F.tile_path(lat0, lon0)
        if not os.path.exists(p):
            print("missing raw tile", p, flush=True)
            continue
        with rasterio.open(p) as ds:
            assert ds.shape == (T.PX, T.PX), ds.shape
            t = ds.transform                               # GDAL corner = half a pixel NW of the first point
            assert abs(t.c + 0.5 / T.PX - lon0) < 1e-9 and abs(t.f - 0.5 / T.PX - (lat0 + 1)) < 1e-9, t
            a = ds.read(1).astype(np.float64)
        a[~np.isfinite(a)] = 0.0
        raw_min, raw_max = float(a.min()), float(a.max())
        lat = lat0 + 1 - np.arange(T.PX) / T.PX
        lon = lon0 + np.arange(T.PX) / T.PX
        flat = 0
        if T.airfield_weight(T.RWY["lat"], T.RWY["lon"]) > 0 and lat0 <= T.RWY["lat"] < lat0 + 1 and lon0 <= T.RWY["lon"] < lon0 + 1:
            LA, LO = np.meshgrid(lat, lon, indexing="ij")
            w = T.airfield_weight(LA, LO)
            a = w * T.FIELD_M + (1 - w) * a
            flat = int((w > 0).sum())
        q = np.clip(np.round(a * 10.0), -32768, 32767).astype(np.int16)
        np.save(os.path.join(T.PROC, "dem_%s.npy" % T.cell_name(lat0, lon0)), q)
        r0, c0 = (T.BOX_N - (lat0 + 1)) * T.PX, (lon0 - T.BOX_W) * T.PX
        h = q.astype(np.float32) * 0.1
        ov4[r0 // 4:r0 // 4 + k4, c0 // 4:c0 // 4 + k4] = h.reshape(k4, 4, k4, 4).mean(axis=(1, 3))
        ov16[r0 // 16:r0 // 16 + k16, c0 // 16:c0 // 16 + k16] = h.reshape(k16, 16, k16, 16).mean(axis=(1, 3))
        land4[r0 // 4:r0 // 4 + k4, c0 // 4:c0 // 4 + k4] = (np.abs(h) > 0.2).reshape(k4, 4, k4, 4).any(axis=(1, 3))
        info[T.cell_name(lat0, lon0)] = dict(raw=os.path.basename(p), min=round(raw_min, 1), max=round(raw_max, 1),
                                             land_frac=round(float((np.abs(h) > 0.2).mean()), 3), flattened_px=flat)
        print("prep %s  %7.1f .. %7.1f m  land %.0f%%  %s" % (T.cell_name(lat0, lon0), raw_min, raw_max, 100 * info[T.cell_name(lat0, lon0)]["land_frac"], what), flush=True)
    np.save(os.path.join(T.PROC, "ov4.npy"), ov4)
    np.save(os.path.join(T.PROC, "ov16.npy"), ov16)
    np.save(os.path.join(T.PROC, "land4.npy"), land4)
    with open(os.path.join(T.PROC, "prep.json"), "w", encoding="utf-8") as f:
        json.dump(dict(made=time.strftime("%Y-%m-%d %H:%M:%S"), box=[T.BOX_W, T.BOX_S, T.BOX_E, T.BOX_N], cells=info,
                       units="int16 decimetres MSL (EGM2008)", airfield=dict(field_m=T.FIELD_M, flat_x=T.FLAT_X, flat_y=T.FLAT_Y,
                       blend_m=T.BLEND_M)), f, indent=1)


# ---- step 3: sanity check ----------------------------------------------------------------------------------------------
# reference values: summits = official heights (Korea Forest Service / NGII); airfields = AIP / OurAirports field
# elevation at the airport reference point (DSM: buildings / trees on top are possible)
CHECKS = [
    ("한라산 (Hallasan, 백록담 rim)", 33.3617, 126.5292, 1947.0, "summit"),
    ("설악산 대청봉 (Seoraksan)", 38.1192, 128.4653, 1708.0, "summit"),
    ("지리산 천왕봉 (Jirisan)", 35.3370, 127.7306, 1915.0, "summit"),
    ("북한산 백운대 (Bukhansan)", 37.6587, 126.9779, 836.0, "summit"),
    ("속리산 천왕봉 (Songnisan)", 36.5428, 127.8701, 1058.0, "summit"),
    ("서해 바다 (Yellow Sea)", 35.5000, 125.5000, 0.0, "sea"),
    ("동해 바다 (East Sea)", 37.0000, 129.8000, 0.0, "sea"),
    ("청주 RKTU 06R/24L 가운데", 36.71540, 127.49964, 58.2, "airfield"),
    ("김포 RKSS ARP", 37.5583, 126.7906, 18.0, "airfield"),
    ("인천 RKSI ARP", 37.4691, 126.4505, 7.0, "airfield"),
    ("제주 RKPC ARP", 33.5113, 126.4930, 36.0, "airfield"),
    ("김해 RKPK ARP", 35.1795, 128.9382, 2.0, "airfield"),
]


def raw_sample(lat, lon):
    """bilinear from the raw COG (before flattening)."""
    import rasterio
    lat0, lon0 = int(math.ceil(lat)) - 1, int(math.floor(lon))     # integer latitude = row 0 of the cell below it
    p = F.tile_path(lat0, lon0)
    if not os.path.exists(p):
        return None
    with rasterio.open(p) as ds:
        fr, fc = (lat0 + 1 - lat) * T.PX, (lon - lon0) * T.PX
        r, c = int(fr), int(fc)
        a = ds.read(1, window=((r, min(r + 2, T.PX)), (c, min(c + 2, T.PX)))).astype(np.float64)
        if a.shape != (2, 2):
            return float(a[0, 0])
        tr, tc = fr - r, fc - c
        return float((a[0, 0] * (1 - tc) + a[0, 1] * tc) * (1 - tr) + (a[1, 0] * (1 - tc) + a[1, 1] * tc) * tr)


def local_max(dem, lat, lon, r_m=300.0):
    """highest processed DEM value within r_m (summit coordinates are only good to ~100 m)."""
    k = 1.0 / T.PX
    dl, dn = r_m / 111000.0, r_m / (111000.0 * math.cos(math.radians(lat)))
    LA, LO = np.meshgrid(np.arange(lat - dl, lat + dl, k), np.arange(lon - dn, lon + dn, k), indexing="ij")
    h = dem.msl(LA, LO)
    i = np.unravel_index(np.argmax(h), h.shape)
    return float(h[i]), float(LA[i]), float(LO[i])


def check():
    dem = T.Dem()
    rows = []
    for name, lat, lon, ref, kind in CHECKS:
        raw = raw_sample(lat, lon)
        h = float(dem.msl(lat, lon))
        n = float(dem.geoid_n(lat, lon, flatten=False))
        r = dict(name=name, lat=lat, lon=lon, kind=kind, ref_m=ref, raw_m=None if raw is None else round(raw, 1), dem_m=round(h, 1),
                 geoid_n=round(n, 2), ellipsoid_m=round(h + float(dem.geoid_n(lat, lon)), 1))
        if kind == "summit":
            mx, la, lo = local_max(dem, lat, lon)
            r.update(max300_m=round(mx, 1), err_m=round(mx - ref, 1), max_at=[round(la, 5), round(lo, 5)])
        else:
            r.update(err_m=round(h - ref, 1))
        rows.append(r)
        print("%-28s ref %7.1f  raw %7s  dem %7.1f  %s err %+6.1f  N %.2f" % (name, ref, r["raw_m"], h,
              ("max300 %7.1f" % r["max300_m"]) if kind == "summit" else " " * 13, r["err_m"], n), flush=True)
    g = float(dem.geoid_n(T.RWY["lat"], T.RWY["lon"], flatten=False))
    res = dict(made=time.strftime("%Y-%m-%d %H:%M:%S"), rows=rows,
               geoid_at_rktu=dict(egm2008_grid=round(g, 3), geographiclib=T.GEOID_N, diff=round(g - T.GEOID_N, 3)))
    print("geoid N at RKTU: grid %.3f vs GeographicLib %.2f (diff %+.3f m)" % (g, T.GEOID_N, g - T.GEOID_N), flush=True)
    with open(os.path.join(T.PROC, "check.json"), "w", encoding="utf-8") as f:
        json.dump(res, f, indent=1, ensure_ascii=False)
    return res


# ---- step 4: tiles ------------------------------------------------------------------------------------------------------
def ecef(lat, lon, h):
    la, lo = np.radians(lat), np.radians(lon)
    sl, cl = np.sin(la), np.cos(la)
    n = A_WGS / np.sqrt(1 - E2 * sl * sl)
    return np.stack(((n + h) * cl * np.cos(lo), (n + h) * cl * np.sin(lo), (n * (1 - E2) + h) * sl), axis=-1)


def tile_rect(L, x, y):
    w = 180.0 / (1 << L)
    return -180.0 + x * w, -90.0 + y * w, -180.0 + (x + 1) * w, -90.0 + (y + 1) * w


def zigzag_delta(v):
    v = v.astype(np.int64)
    d = np.diff(np.concatenate(([0], v)))
    return ((d << 1) ^ (d >> 63)).astype(np.uint16)


def oct_encode(nrm):
    s = np.abs(nrm).sum(axis=1, keepdims=True)
    p = nrm[:, :2] / s
    neg = nrm[:, 2] < 0
    sgn = np.where(p >= 0, 1.0, -1.0)
    q = (1.0 - np.abs(p[:, ::-1])) * sgn
    p = np.where(neg[:, None], q, p)
    return np.round((np.clip(p, -1, 1) * 0.5 + 0.5) * 255.0).astype(np.uint8)


def horizon_point(center, pts):
    """Cesium EllipsoidalOccluder.computeHorizonCullingPoint (ellipsoid-scaled space)."""
    inv = np.array([1 / A_WGS, 1 / A_WGS, 1 / B_WGS])
    d = center * inv
    d /= np.linalg.norm(d)
    sp = pts * inv
    mag2 = (sp ** 2).sum(axis=1)
    mag = np.sqrt(mag2)
    dirn = sp / mag[:, None]
    mag2, mag = np.maximum(mag2, 1.0), np.maximum(mag, 1.0)
    cos_a = dirn @ d
    sin_a = np.linalg.norm(np.cross(dirn, d), axis=1)
    cos_b = 1.0 / mag
    sin_b = np.sqrt(mag2 - 1.0) * cos_b
    den = cos_a * cos_b - sin_a * sin_b
    if np.any(den <= 0):
        return d                                          # tile too big for a horizon point (low levels)
    return d * (1.0 / den).max()


_GRID = {}


def grid_topology(n):
    """vertex order (first use in the triangle list), triangles, edge lists for an n x n grid."""
    if n in _GRID:
        return _GRID[n]
    idx = np.arange(n * n).reshape(n, n)                  # [j (north), i (east)]
    a, b, c, d = idx[:-1, :-1], idx[:-1, 1:], idx[1:, :-1], idx[1:, 1:]
    tris = np.stack((a, b, d, a, d, c), axis=-1).reshape(-1, 3)   # counter-clockwise seen from above
    flat = tris.ravel()
    _, first = np.unique(flat, return_index=True)
    order = np.argsort(first)                             # old vertex ids in order of first use
    remap = np.empty(n * n, np.int64)
    remap[order] = np.arange(n * n)
    tris2 = remap[tris].astype(np.uint16)
    edges = [remap[idx[:, 0]], remap[idx[0, :]], remap[idx[:, -1]], remap[idx[-1, :]]]   # west, south, east, north
    hw = np.empty(tris2.size, np.int64)
    highest = 0
    for k, v in enumerate(tris2.ravel().tolist()):         # high-water-mark encoding
        hw[k] = highest - v
        if v == highest:
            highest += 1
    _GRID[n] = (order, hw.astype(np.uint16), tris2.shape[0], [e.astype(np.uint16) for e in edges])
    return _GRID[n]


def tile_heights(dem, L, x, y, n):
    w, s, e, nn = tile_rect(L, x, y)
    lat = s + (nn - s) * np.arange(n) / (n - 1)
    lon = w + (e - w) * np.arange(n) / (n - 1)
    LA, LO = np.meshgrid(lat, lon, indexing="ij")
    spacing = (e - w) / (n - 1) * 3600.0
    inbox = (LA >= T.BOX_S) & (LA <= T.BOX_N) & (LO >= T.BOX_W) & (LO <= T.BOX_E)
    msl = np.zeros_like(LA)
    if inbox.any():
        if spacing <= 8.0:
            msl[inbox] = dem.msl(LA[inbox], LO[inbox])
        else:
            msl[inbox] = dem.msl_ov(LA[inbox], LO[inbox], 4 if spacing <= 32.0 else 16)
    h = msl + dem.geoid_n(LA, LO)
    wfl = T.airfield_weight(LA, LO)
    if wfl.any():
        h = h - T.MESH_DROP_M * wfl
    return LA, LO, h


def encode_tile(dem, L, x, y, n):
    LA, LO, h = tile_heights(dem, L, x, y, n)
    P = ecef(LA, LO, h)                                   # [j, i, 3]
    de = np.gradient(P, axis=1)
    dn = np.gradient(P, axis=0)
    nrm = np.cross(de, dn)
    ln = np.linalg.norm(nrm, axis=-1, keepdims=True)
    up = ecef(LA, LO, 0.0)
    up /= np.linalg.norm(up, axis=-1, keepdims=True)
    nrm = np.where(ln > 0, nrm / np.where(ln > 0, ln, 1), up)     # poles: degenerate rows
    order, hw, ntri, edges = grid_topology(n)
    hmin, hmax = float(h.min()), float(h.max())
    if hmax - hmin < 0.01:
        hmax = hmin + 0.01
    ii, jj = np.meshgrid(np.arange(n), np.arange(n))
    u = np.round(ii.ravel() * 32767.0 / (n - 1))[order]
    v = np.round(jj.ravel() * 32767.0 / (n - 1))[order]
    hq = np.round((h.ravel() - hmin) / (hmax - hmin) * 32767.0)[order]
    pts = P.reshape(-1, 3)
    w, s, e, nn = tile_rect(L, x, y)
    c = ecef(np.array((s + nn) / 2), np.array((w + e) / 2), np.array((hmin + hmax) / 2)).reshape(3)
    rad = float(np.linalg.norm(pts - c, axis=1).max())
    hz = horizon_point(c, pts)
    out = [struct.pack("<3d2f4d3d", c[0], c[1], c[2], hmin, hmax, c[0], c[1], c[2], rad, hz[0], hz[1], hz[2])]
    out.append(struct.pack("<I", n * n))
    out += [zigzag_delta(u).tobytes(), zigzag_delta(v).tobytes(), zigzag_delta(hq).tobytes()]
    out.append(struct.pack("<I", ntri))                   # 88 + 4 + 6 nv bytes: already 2-byte aligned
    out.append(hw.tobytes())
    for ed in edges:
        out.append(struct.pack("<I", ed.size))
        out.append(ed.tobytes())
    oct_ = oct_encode(nrm.reshape(-1, 3)[order])
    out.append(struct.pack("<BI", 1, oct_.size))          # extension 1 = oct-encoded vertex normals
    out.append(oct_.tobytes())
    return gzip.compress(b"".join(out), 6), hmin, hmax


def plan_tiles():
    """{level: [(x, y, n), ...]} with the rules in the module docstring."""
    land = np.load(os.path.join(T.PROC, "land4.npy")).astype(np.int64)
    cs = np.zeros((land.shape[0] + 1, land.shape[1] + 1), np.int64)
    cs[1:, 1:] = land.cumsum(0).cumsum(1)

    def has_land(w, s, e, n):
        if e <= T.BOX_W or w >= T.BOX_E or n <= T.BOX_S or s >= T.BOX_N:
            return False
        r0 = int(math.floor((T.BOX_N - min(n, T.BOX_N)) * T.PX / 4))
        r1 = int(math.ceil((T.BOX_N - max(s, T.BOX_S)) * T.PX / 4))
        c0 = int(math.floor((max(w, T.BOX_W) - T.BOX_W) * T.PX / 4))
        c1 = int(math.ceil((min(e, T.BOX_E) - T.BOX_W) * T.PX / 4))
        return cs[r1, c1] - cs[r0, c1] - cs[r1, c0] + cs[r0, c0] > 0

    plan = {}
    for L in range(MAX_LEVEL + 1):
        wdeg = 180.0 / (1 << L)
        if L <= GLOBAL_MAX:
            xs, ys = range(2 << L), range(1 << L)
        else:
            rw, rs, re_, rn = REGION if L <= REGION_MAX else (T.BOX_W, T.BOX_S, T.BOX_E, T.BOX_N)
            xs = range(int((rw + 180) // wdeg), int(math.ceil((re_ + 180) / wdeg)))
            ys = range(int((rs + 90) // wdeg), int(math.ceil((rn + 90) / wdeg)))
        lst = []
        for y in ys:
            for x in xs:
                r = tile_rect(L, x, y)
                lnd = has_land(*r)
                if L > REGION_MAX and not lnd:
                    continue
                lst.append((x, y, 65 if lnd else 33))
        plan[L] = lst
    return plan


def rects(xy):
    """tile set -> availability rectangles (row runs merged downwards)."""
    rows = {}
    for x, y in xy:
        rows.setdefault(y, []).append(x)
    runs = []
    for y in sorted(rows):
        xs = sorted(rows[y])
        s = p = xs[0]
        for x in xs[1:] + [None]:
            if x is not None and x == p + 1:
                p = x
                continue
            runs.append([s, y, p, y])
            if x is not None:
                s = p = x
    merged = []
    open_ = {}
    for r in runs:                                        # extend a rectangle when the same x run continues on y + 1
        k = (r[0], r[2])
        if k in open_ and open_[k][3] == r[1] - 1:
            open_[k][3] = r[1]
        else:
            open_[k] = list(r)
            merged.append(open_[k])
    return [dict(startX=a, startY=b, endX=c, endY=d) for a, b, c, d in merged]


_W = {}


def _work(job):
    L, x, y, n = job
    dem = _W.get("dem")
    if dem is None:
        dem = _W["dem"] = T.Dem()
    data, hmin, hmax = encode_tile(dem, L, x, y, n)
    p = os.path.join(T.TILES, str(L), str(x), "%d.terrain" % y)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "wb") as f:
        f.write(data)
    return L, len(data), hmin, hmax


def tiles():
    import multiprocessing as mp
    plan = plan_tiles()
    jobs = [(L, x, y, n) for L, lst in plan.items() for x, y, n in lst]
    print("tiles to build:", {L: len(v) for L, v in plan.items()}, "total", len(jobs), flush=True)
    os.makedirs(T.TILES, exist_ok=True)
    t0, done, size = time.time(), 0, {}
    with mp.Pool(max(1, (os.cpu_count() or 4) - 2)) as pool:
        for L, nb, _, _ in pool.imap_unordered(_work, jobs, chunksize=16):
            done += 1
            size[L] = size.get(L, 0) + nb
            if done % 2000 == 0 or done == len(jobs):
                el = time.time() - t0
                print("  %d / %d  %.0f s  (eta %.0f s)  %.0f MB" % (done, len(jobs), el, el / done * (len(jobs) - done), sum(size.values()) / 1e6), flush=True)
    layer = dict(tilejson="2.1.0", name="GyroSim South Korea (Copernicus GLO-30)", description="ellipsoid heights = Copernicus GLO-30 (EGM2008 MSL) + EGM2008 N",
                 version="1.0.0", format="quantized-mesh-1.0", scheme="tms", projection="EPSG:4326", bounds=[-180, -90, 180, 90],
                 minzoom=0, maxzoom=MAX_LEVEL, tiles=["{z}/{x}/{y}.terrain?v={version}"], extensions=["octvertexnormals"],
                 attribution=ATTRIB, available=[rects([(x, y) for x, y, _ in plan[L]]) for L in range(MAX_LEVEL + 1)])
    with open(os.path.join(T.TILES, "layer.json"), "w", encoding="utf-8") as f:
        json.dump(layer, f)
    stats = dict(made=time.strftime("%Y-%m-%d %H:%M:%S"), seconds=round(time.time() - t0), tiles={L: len(v) for L, v in plan.items()},
                 bytes_per_level=size, total_bytes=sum(size.values()), input=dict(proc=T.PROC, prep=json.load(open(os.path.join(T.PROC, "prep.json")))["made"]))
    with open(os.path.join(T.TILES, "build.json"), "w", encoding="utf-8") as f:
        json.dump(stats, f, indent=1)
    print("done: %d tiles, %.0f MB, %.0f s -> %s" % (len(jobs), stats["total_bytes"] / 1e6, stats["seconds"], T.TILES), flush=True)


if __name__ == "__main__":
    a = sys.argv[1:]
    if "--prep" in a or "--all" in a:
        prep()
    if "--check" in a or "--all" in a:
        check()
    if "--tiles" in a or "--all" in a:
        tiles()
    if not a:
        print(__doc__)
