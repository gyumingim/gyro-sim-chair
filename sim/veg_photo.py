"""Photo colour under the trees (11-15, owner: tree colours stand out, hard tree-area edges, colours the aerial photo does not have).

The 11-10 prep (sim/veg_build.py --prep) sampled the z17 photo at each tree top, but z17 was cached for only ~24 % of the
trees then (the rest carry the default (46, 62, 38)). This reads the local V-World photo cache
C:/GyroSimTiles/vworld/Satellite/<z>/<y>/<x>.jpg at build time, finest zoom first (17 .. 12; z12 ~30 m px = the area colour), and returns one averaged
colour per tree: a Gaussian-weighted mean over ~SIGMA_M metres around the tree (normalised convolution, so missing tiles do not
darken the edge of the cached area). Nothing derived from the photo is written by this module; the tile build turns the
per-tree colours into per-tile prototype colours (sim/veg_v2.py PHOTO) inside C:/GyroSimTiles only.

    photo_lin(lat, lon) -> (rgb linear float32 (n, 3), zoom used (n,) int8, 0 = no photo)
"""
import math, os
import numpy as np

SAT = os.path.join(os.environ.get("GYROSIM_TILES", r"C:\GyroSimTiles"), "vworld", "Satellite")
SIGMA_M = float(os.environ.get("GYROSIM_VEG_PHOTO_SIGMA", "3.0"))    # ground metres (a crown is ~4 m in radius)
ZOOMS = (17, 16, 15, 14, 13, 12)                     # the cache holds what Cesium streamed: z17 is patchy, z13 / z12 cover all
R_MERC = 6378137.0


def _srgb_to_lin(c):
    c = np.asarray(c, np.float32) / 255.0
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4).astype(np.float32)


def _pix(lat, lon, z):
    """global pixel coordinates (256 px tiles, XYZ / Google scheme) at zoom z."""
    n = 256.0 * (1 << z)
    x = (np.asarray(lon, np.float64) + 180.0) / 360.0 * n
    s = np.sin(np.radians(np.asarray(lat, np.float64)))
    y = (0.5 - np.log((1 + s) / (1 - s)) / (4 * math.pi)) * n
    return x, y


def _mosaic(z, tx0, ty0, tx1, ty1):
    import cv2
    W, H = (tx1 - tx0 + 1) * 256, (ty1 - ty0 + 1) * 256
    img = np.zeros((H, W, 3), np.float32)
    ok = np.zeros((H, W), np.float32)
    for ty in range(ty0, ty1 + 1):
        for tx in range(tx0, tx1 + 1):
            p = os.path.join(SAT, str(z), str(ty), "%d.jpg" % tx)
            if not os.path.isfile(p):
                continue
            a = cv2.imread(p, cv2.IMREAD_COLOR)
            if a is None or a.shape[:2] != (256, 256):
                continue
            r, c = (ty - ty0) * 256, (tx - tx0) * 256
            img[r:r + 256, c:c + 256] = _srgb_to_lin(a[:, :, ::-1])
            ok[r:r + 256, c:c + 256] = 1.0
    return img, ok


def photo_lin(lat, lon, sigma_m=None):
    import cv2
    lat = np.asarray(lat, np.float64); lon = np.asarray(lon, np.float64)
    n = len(lat)
    out = np.zeros((n, 3), np.float32)
    zused = np.zeros(n, np.int8)
    if n == 0:
        return out, zused
    sig = SIGMA_M if sigma_m is None else sigma_m
    for z in ZOOMS:
        todo = np.nonzero(zused == 0)[0]
        if len(todo) == 0:
            break
        x, y = _pix(lat[todo], lon[todo], z)
        tx0, tx1 = int(x.min() // 256), int(x.max() // 256)
        ty0, ty1 = int(y.min() // 256), int(y.max() // 256)
        if (tx1 - tx0 + 1) * (ty1 - ty0 + 1) > 400:          # a block spans ~8 x 8 z17 tiles; never mosaic huge areas
            continue
        img, ok = _mosaic(z, tx0, ty0, tx1, ty1)
        if not ok.any():
            continue
        gm = 2 * math.pi * R_MERC * math.cos(math.radians(float(lat.mean()))) / (256.0 * (1 << z))   # ground m / px
        s = max(sig / gm, 0.5)
        k = int(math.ceil(3 * s)) * 2 + 1
        num = cv2.GaussianBlur(img * ok[..., None], (k, k), s)
        den = cv2.GaussianBlur(ok, (k, k), s)
        c = np.clip(np.floor(x).astype(np.int64) - tx0 * 256, 0, img.shape[1] - 1)
        r = np.clip(np.floor(y).astype(np.int64) - ty0 * 256, 0, img.shape[0] - 1)
        d = den[r, c]
        good = (d > 0.5) & (ok[r, c] > 0)
        out[todo[good]] = num[r[good], c[good]] / d[good, None]
        zused[todo[good]] = z
    return out, zused
