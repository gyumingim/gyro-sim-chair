"""South Korea terrain heights for the sim (Copernicus DEM GLO-30 + EGM2008 geoid), shared by
  - sim/server.py   : JSBSim terrain elevation under the aircraft (vworld ground mode) -> real mountains crash
  - sim/terrain_build.py : the Cesium quantized-mesh terrain tiles (served by sim/vworld_proxy.py at /terrain/)

Data (never in git): C:\\GyroSimTiles\\terrain (GYROSIM_TERRAIN env var moves it)
  raw/   Copernicus COG tiles + EGM2008 window (sim/terrain_fetch.py)
  proc/  dem_N37E127.npy ...  int16 decimetres MSL, 3600 x 3600, airfield flattened (terrain_build.py --prep)
         ov4.npy / ov16.npy   float32 MSL means over 4 x 4 / 16 x 16 arc-seconds for the whole box (coarse tiles)
         land4.npy            uint8, 1 = some land in that 4 x 4 arc-second block
  tiles/ layer.json + {z}/{x}/{y}.terrain (gzip quantized-mesh-1.0, ellipsoid heights)

Grid: Copernicus pixel-is-point, pixel (r, c) of the cell with south-west corner (lat0, lon0) is at
lat0 + 1 - r / 3600, lon0 + c / 3600 (checked: GDAL corner 125.99986 / 34.00014 for N33 E126 = half a pixel out).
The whole box is one global 1" grid: row R from BOX_N downwards, column C from BOX_W eastwards.

Heights: Copernicus = orthometric (EGM2008, "MSL"). JSBSim altitudes in this project are MSL (airfield.py), so the
server uses H directly. Cesium wants WGS84 ellipsoid heights: h = H + N, N = EGM2008 undulation (bilinear on the
2.5' grid). At every airfield in airfield.AIRFIELDS (RKTU, RKPK) the DEM is flattened to its published field elevation
and N to its geoid_n, so the sim's own runway mesh, JSBSim's runway and the Cesium terrain agree exactly there (whichever
airfield the sim starts at - the terrain tiles are the same for all).
"""
import json, math, os
import numpy as np
import airfield as AFL
from airfield import FIELD_M, GEOID_N, RWY, M_LAT, M_LON      # selected start (server); flattening uses all airfields

ROOT = os.environ.get("GYROSIM_TERRAIN", r"C:\GyroSimTiles\terrain")
RAW, PROC, TILES = (os.path.join(ROOT, d) for d in ("raw", "proc", "tiles"))
BOX_W, BOX_S, BOX_E, BOX_N = 124, 33, 132, 39            # covers every downloaded 1-degree cell (terrain_fetch.TILES)
PX = 3600                                                 # samples per degree (1 arc-second)
NCOL, NROW = (BOX_E - BOX_W) * PX, (BOX_N - BOX_S) * PX

# airfield flattening, every airfield in airfield.AIRFIELDS (runway axes of its start runway: x = m past the threshold,
# y = m right of the centre line; box = its flat_x / flat_y): core = exactly its field elevation, then a cosine blend to
# the real DEM over BLEND_M
FLAT_X, FLAT_Y = AFL.AIRFIELDS["rktu"]["flat_x"], AFL.AIRFIELDS["rktu"]["flat_y"]     # (old names, RKTU)
BLEND_M = 400.0
MESH_DROP_M = 0.3                                         # Cesium terrain 30 cm under the runway mesh (no z-fighting), like the grid
FIELDS = [dict(id=a["id"], lat=a["rwy"]["lat"], lon=a["rwy"]["lon"], hdg=a["rwy"]["hdg"], mlon=111320.0 * math.cos(math.radians(a["rwy"]["lat"])),
               fx=a["flat_x"], fy=a["flat_y"], field_m=a["field_ft"] * 0.3048, geoid_n=a["geoid_n"]) for a in AFL.AIRFIELDS.values()]
# 1-arc-second cells deeper than level 13 (quantized-mesh levels 14..max_level, 33 x 33 vertices): where V-World z19 photos
# are cached, so Cesium asks the photo overlay for zoom 17-19 there (the raster zoom follows the terrain tile level:
# about z16 on level-13 tiles). Busan = the V-World z19 fill region (vworld_fill.py, bounds 128.77-129.31 E, 34.98-35.39 N).
HIRES = [dict(name="busan", box=(128.75, 34.96, 129.33, 35.40), max_level=16, n=33)]


def cell_name(lat, lon):
    return "N%02dE%03d" % (lat, lon)


def _field_w(f, lat, lon):
    n, e = (lat - f["lat"]) * M_LAT, (lon - f["lon"]) * f["mlon"]
    h = math.radians(f["hdg"])
    x, y = n * math.cos(h) + e * math.sin(h), -n * math.sin(h) + e * math.cos(h)
    dx = np.maximum(np.maximum(f["fx"][0] - x, x - f["fx"][1]), 0.0)
    dy = np.maximum(np.maximum(f["fy"][0] - y, y - f["fy"][1]), 0.0)
    d = np.hypot(dx, dy)
    return np.where(d >= BLEND_M, 0.0, 0.5 + 0.5 * np.cos(np.pi * np.minimum(d, BLEND_M) / BLEND_M))


def field_weights(lat, lon):
    """[(field dict, weight array)] for the airfields near lat / lon (weight 1 inside the core, 0 outside the blend)."""
    lat, lon = np.asarray(lat, dtype=np.float64), np.asarray(lon, dtype=np.float64)
    out = []
    for f in FIELDS:
        if np.ndim(lat) == 0 and abs(float(lat) - f["lat"]) > 0.1:      # scalar fast path (server, 60 Hz)
            continue
        w = _field_w(f, lat, lon)
        if np.any(w > 0):
            out.append((f, w))
    return out


def airfield_weight(lat, lon):
    """1 inside a flattened airfield core, 0 outside every blend; numpy arrays or scalars."""
    lat, lon = np.asarray(lat, dtype=np.float64), np.asarray(lon, dtype=np.float64)
    w = np.zeros(np.broadcast(lat, lon).shape)
    for f, wf in field_weights(lat, lon):
        w = np.maximum(w, wf)
    return w


def flatten(a, lat, lon, key):
    """a (MSL heights or geoid N) blended to each airfield's field_m / geoid_n (key) by its weight."""
    for f, w in field_weights(lat, lon):
        a = w * f[key] + (1 - w) * a
    return a


class Dem:
    """MSL heights (m) of the processed grid, bilinear. Sea / no data = 0. Memory-mapped: cheap to open."""
    def __init__(self, proc=PROC):
        self.proc = proc
        self.cells = {}
        for fn in os.listdir(proc) if os.path.isdir(proc) else ():
            if fn.startswith("dem_N") and fn.endswith(".npy"):
                k = fn[4:-4]
                self.cells[(int(k[1:3]), int(k[4:7]))] = os.path.join(proc, fn)
        self._mm = {}
        g = os.path.join(RAW, "egm2008_25_korea.npy")
        self.geoid = np.load(g) if os.path.exists(g) else None
        if self.geoid is not None:
            m = json.load(open(os.path.join(RAW, "egm2008_25_korea.json"), encoding="utf-8"))
            self.g_w, self.g_n, self.g_dx, self.g_dy = m["west"], m["north"], m["dx"], m["dy"]
        self.ov = {}
        for k in (4, 16):
            p = os.path.join(proc, "ov%d.npy" % k)
            if os.path.exists(p):
                self.ov[k] = np.load(p, mmap_mode="r")

    @property
    def ok(self):
        return bool(self.cells) and self.geoid is not None

    def _cell(self, key):
        a = self._mm.get(key)
        if a is None and key in self.cells:
            a = self._mm[key] = np.load(self.cells[key], mmap_mode="r")
        return a

    # ---- 1" grid -------------------------------------------------------------------------------------------------
    def _px(self, R, C):
        """int arrays of global rows / cols -> MSL m (0 outside the box / missing cells)."""
        R, C = np.asarray(R), np.asarray(C)
        out = np.zeros(R.shape, dtype=np.float64)
        inside = (R >= 0) & (R < NROW) & (C >= 0) & (C < NCOL)
        # pixel row r of cell lat0 is at lat0 + 1 - r/3600; global row R is at BOX_N - R/3600 -> cell north edge
        # = BOX_N - R//PX (R % PX == 0 lands on row 0 of the cell whose north edge it is)
        cl = np.where(inside, BOX_N - (R // PX) - 1, -1)
        rr = R % PX
        co = np.where(inside, BOX_W + C // PX, -1)
        cc = C % PX
        for key in set(zip(cl[inside].ravel().tolist(), co[inside].ravel().tolist())):
            a = self._cell(key)
            if a is None:
                continue
            m = inside & (cl == key[0]) & (co == key[1])
            out[m] = a[rr[m], cc[m]] * 0.1
        return out

    def msl(self, lat, lon):
        """bilinear MSL height (m) at lat/lon (arrays or scalars), from the 1" grid."""
        lat, lon = np.asarray(lat, dtype=np.float64), np.asarray(lon, dtype=np.float64)
        fr, fc = (BOX_N - lat) * PX, (lon - BOX_W) * PX
        r0, c0 = np.floor(fr).astype(np.int64), np.floor(fc).astype(np.int64)
        tr, tc = fr - r0, fc - c0
        h00, h01 = self._px(r0, c0), self._px(r0, c0 + 1)
        h10, h11 = self._px(r0 + 1, c0), self._px(r0 + 1, c0 + 1)
        return (h00 * (1 - tc) + h01 * tc) * (1 - tr) + (h10 * (1 - tc) + h11 * tc) * tr

    def msl_ov(self, lat, lon, k):
        """bilinear MSL from the k x k arc-second mean overview (k = 4 or 16): block (r, c) centre at
        BOX_N - (k r + (k-1)/2) / 3600, BOX_W + (k c + (k-1)/2) / 3600."""
        a = self.ov[k]
        lat, lon = np.asarray(lat, dtype=np.float64), np.asarray(lon, dtype=np.float64)
        fr = ((BOX_N - lat) * PX - (k - 1) / 2.0) / k
        fc = ((lon - BOX_W) * PX - (k - 1) / 2.0) / k
        r0, c0 = np.floor(fr).astype(np.int64), np.floor(fc).astype(np.int64)
        tr, tc = fr - r0, fc - c0
        H, W = a.shape

        def g(r, c):
            ok = (r >= 0) & (r < H) & (c >= 0) & (c < W)
            v = np.zeros(r.shape)
            v[ok] = a[r[ok], c[ok]]
            return v
        return (g(r0, c0) * (1 - tc) + g(r0, c0 + 1) * tc) * (1 - tr) + (g(r0 + 1, c0) * (1 - tc) + g(r0 + 1, c0 + 1) * tc) * tr

    def geoid_n(self, lat, lon, flatten=True):
        """EGM2008 undulation N (m), bilinear between 2.5' cell centres; 0 outside the window. At the airfield
        blended to that airfield's geoid_n (the value its runway mesh / Unreal origin use)."""
        lat, lon = np.asarray(lat, dtype=np.float64), np.asarray(lon, dtype=np.float64)
        a = self.geoid
        fr = (lat - self.g_n) / self.g_dy - 0.5
        fc = (lon - self.g_w) / self.g_dx - 0.5
        r0 = np.clip(np.floor(fr).astype(np.int64), 0, a.shape[0] - 2)
        c0 = np.clip(np.floor(fc).astype(np.int64), 0, a.shape[1] - 2)
        tr, tc = np.clip(fr - r0, 0, 1), np.clip(fc - c0, 0, 1)
        n = (a[r0, c0] * (1 - tc) + a[r0, c0 + 1] * tc) * (1 - tr) + (a[r0 + 1, c0] * (1 - tc) + a[r0 + 1, c0 + 1] * tc) * tr
        inside = (fr >= -0.5) & (fr <= a.shape[0] - 0.5) & (fc >= -0.5) & (fc <= a.shape[1] - 0.5)
        n = np.where(inside, n, 0.0)
        if flatten:
            n = globals()["flatten"](n, lat, lon, "geoid_n")
        return n

    def in_box(self, lat, lon):
        return BOX_S <= lat < BOX_N and BOX_W <= lon < BOX_E

    # ---- scalar fast path for the server (60 Hz) -------------------------------------------------------------------
    def height_msl(self, lat, lon):
        """MSL terrain height (m) under lat/lon; 0 at sea or outside the data. ~20 us."""
        if not (BOX_S <= lat < BOX_N and BOX_W <= lon < BOX_E):
            return 0.0
        fr, fc = (BOX_N - lat) * PX, (lon - BOX_W) * PX
        r0, c0 = int(fr), int(fc)
        tr, tc = fr - r0, fc - c0
        v = []
        for R, C in ((r0, c0), (r0, c0 + 1), (r0 + 1, c0), (r0 + 1, c0 + 1)):
            if R >= NROW or C >= NCOL:
                v.append(0.0)
                continue
            a = self._cell((BOX_N - R // PX - 1, BOX_W + C // PX))
            v.append(0.0 if a is None else float(a[R % PX, C % PX]) * 0.1)
        return (v[0] * (1 - tc) + v[1] * tc) * (1 - tr) + (v[2] * (1 - tc) + v[3] * tc) * tr

    def geoid_here(self, lat, lon):
        return float(self.geoid_n(lat, lon)) if self.geoid is not None else GEOID_N


BUILDINGS_ROOT = os.environ.get("GYROSIM_BUILDINGS", r"C:\GyroSimTiles\buildings")


class Roofs:
    """Building roof heights (MSL m) on the 1/3" grids made by sim/buildings_build.py --ground (ground/roof_<name>.npy,
    one per region / province, int16 dm, -32768 = no building; all_touched rasterising = footprints grown by up to one
    cell, ~10 m). Nearest cell; the highest roof if two rasters overlap. ~1 us per raster."""
    def __init__(self, root=BUILDINGS_ROOT):
        self.parts, made = [], []
        g = os.path.join(root, "ground")
        for fn in sorted(os.listdir(g)) if os.path.isdir(g) else ():
            if fn.startswith("roof") and fn.endswith(".npy") and os.path.exists(os.path.join(g, fn[:-4] + ".json")):
                m = json.load(open(os.path.join(g, fn[:-4] + ".json"), encoding="utf-8"))
                a = np.load(os.path.join(g, fn), mmap_mode="r")
                self.parts.append((a, m["west"], m["north"], m["px_per_deg"], a.shape[0], a.shape[1]))
                made.append(m.get("made"))
        self.made = max(made) if made else None

    @property
    def ok(self):
        return bool(self.parts)

    def roof_msl(self, lat, lon):
        """roof height (MSL m) of the building under lat / lon, or None."""
        best = None
        for a, w, n, k, H, W in self.parts:
            r, c = int((n - lat) * k), int((lon - w) * k)
            if 0 <= r < H and 0 <= c < W:
                v = int(a[r, c])
                if v != -32768 and (best is None or v * 0.1 > best):
                    best = v * 0.1
        return best


_DEM = None
_ROOFS = None


def roofs():
    """shared Roofs (None if no building raster was built)."""
    global _ROOFS
    if _ROOFS is None:
        r = Roofs()
        _ROOFS = r if r.ok else False
    return _ROOFS or None


def get():
    """shared Dem (None if the processed data is missing)."""
    global _DEM
    if _DEM is None:
        d = Dem()
        _DEM = d if d.ok else False
    return _DEM or None
