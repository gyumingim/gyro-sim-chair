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
2.5' grid). At the airfield (RKTU) the DEM is flattened to the published field elevation and N to airfield.GEOID_N, so
the sim's own runway mesh, JSBSim's runway and the Cesium terrain agree exactly there.
"""
import json, math, os
import numpy as np
from airfield import FIELD_M, GEOID_N, RWY, M_LAT, M_LON

ROOT = os.environ.get("GYROSIM_TERRAIN", r"C:\GyroSimTiles\terrain")
RAW, PROC, TILES = (os.path.join(ROOT, d) for d in ("raw", "proc", "tiles"))
BOX_W, BOX_S, BOX_E, BOX_N = 124, 33, 132, 39            # covers every downloaded 1-degree cell (terrain_fetch.TILES)
PX = 3600                                                 # samples per degree (1 arc-second)
NCOL, NROW = (BOX_E - BOX_W) * PX, (BOX_N - BOX_S) * PX

# airfield flattening (runway axes of 06R: x = m past the 06R threshold, y = m right of the centre line; 06L is 228 m
# left): core = exactly FIELD_M, then a cosine blend to the real DEM over BLEND_M
FLAT_X, FLAT_Y, BLEND_M = (-500.0, 3250.0), (-480.0, 260.0), 400.0
MESH_DROP_M = 0.3                                         # Cesium terrain 30 cm under the runway mesh (no z-fighting), like the grid


def cell_name(lat, lon):
    return "N%02dE%03d" % (lat, lon)


def airfield_weight(lat, lon):
    """1 inside the flattened airfield core, 0 outside the blend; numpy arrays or scalars."""
    lat, lon = np.asarray(lat, dtype=np.float64), np.asarray(lon, dtype=np.float64)
    n, e = (lat - RWY["lat"]) * M_LAT, (lon - RWY["lon"]) * M_LON
    h = math.radians(RWY["hdg"])
    x, y = n * math.cos(h) + e * math.sin(h), -n * math.sin(h) + e * math.cos(h)
    dx = np.maximum(np.maximum(FLAT_X[0] - x, x - FLAT_X[1]), 0.0)
    dy = np.maximum(np.maximum(FLAT_Y[0] - y, y - FLAT_Y[1]), 0.0)
    d = np.hypot(dx, dy)
    return np.where(d >= BLEND_M, 0.0, 0.5 + 0.5 * np.cos(np.pi * np.minimum(d, BLEND_M) / BLEND_M))


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
        blended to airfield.GEOID_N (the value the runway mesh / Unreal origin use)."""
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
            w = airfield_weight(lat, lon)
            n = w * GEOID_N + (1 - w) * n
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


_DEM = None


def get():
    """shared Dem (None if the processed data is missing)."""
    global _DEM
    if _DEM is None:
        d = Dem()
        _DEM = d if d.ok else False
    return _DEM or None
