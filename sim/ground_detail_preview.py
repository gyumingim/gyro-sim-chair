"""Offline preview of the render-time ground sharpening (unreal/GyroSim/Scripts/ground_detail.hlsl), developer use.

Why render-time: the V-World open API terms forbid changing the served content and storing changed copies without the
operator's prior consent (이용약관 13조 10항, 19조 4항; docs/vworld-integration.md). So the cached tiles are never
upscaled / rewritten. Instead the shader (1) reconstructs the photo with a Catmull-Rom (bicubic) filter instead of
bilinear when the camera is close enough that one photo texel covers several screen pixels, and (2) adds a faint,
distance / pixel-footprint faded procedural micro-texture (luminance only, mean 1.0) on land. Nothing is written back.

This script emulates the same math in numpy on views of the cached z19 tiles ("what a low pass at N m would show") and
writes a local comparison page (bilinear = today vs Catmull-Rom vs Catmull-Rom + micro detail) with a sharpness number.
The page and its crops are derived from V-World imagery -> local only, outside git (default: a temp folder).

    python sim/ground_detail_preview.py --out <folder>           # needs the z19 cache (C:/GyroSimTiles/vworld)
"""
import argparse, html, json, math, os, time
import numpy as np
from PIL import Image

CACHE = os.environ.get("GYROSIM_VWORLD_CACHE", r"C:\GyroSimTiles\vworld")
Z = 19
# (name, Korean label, lat, lon)
SITES = [("haeundae", "해운대 고층·아파트", 35.1630, 129.1600), ("marine_city", "마린시티 고층", 35.1565, 129.1435),
         ("seomyeon", "서면 도심 밀집", 35.1578, 129.0597), ("nampo", "남포동 구도심", 35.0985, 129.0300),
         ("north_port", "북항 컨테이너 부두", 35.1150, 129.0480), ("apartments", "좌동 아파트 단지", 35.1700, 129.1760),
         ("gwangan_bridge", "광안대교·바다", 35.1460, 129.1300), ("sea", "먼 바다", 35.1300, 129.1900),
         ("geumjeong", "금정산 숲", 35.2700, 129.0550), ("hwangryeong", "황령산 숲·도로", 35.1570, 129.0820),
         ("interchange", "도로·교차로 (사상)", 35.1640, 128.9850), ("gimhae", "김해공항 활주로", 35.1720, 128.9430),
         ("nakdong", "낙동강 하구", 35.1050, 128.9500), ("yeongdo", "영도 주택가·해안", 35.0800, 129.0500)]


def tile_xy(lat, lon):
    n = 2 ** Z
    x = (lon + 180.0) / 360.0 * n
    r = math.radians(lat)
    y = (1.0 - math.log(math.tan(r) + 1.0 / math.cos(r)) / math.pi) / 2.0 * n
    return x, y


def load_block(lat, lon, half=1):
    """(2*half+1)^2 z19 tiles around the point, float RGB 0..1 (sRGB), or None when a tile is missing."""
    fx, fy = tile_xy(lat, lon)
    cx, cy = int(fx), int(fy)
    rows = []
    for ty in range(cy - half, cy + half + 1):
        row = []
        for tx in range(cx - half, cx + half + 1):
            p = os.path.join(CACHE, "Satellite", str(Z), str(ty), "%d.jpg" % tx)
            if not os.path.isfile(p):
                return None, None
            row.append(np.asarray(Image.open(p).convert("RGB"), np.float32) / 255.0)
        rows.append(np.concatenate(row, 1))
    blk = np.concatenate(rows, 0)
    ox = ((fx - (cx - half)) * 256.0, (fy - (cy - half)) * 256.0)          # point in block pixels
    return blk, ox


# ---- texture filters (same as the HLSL) ------------------------------------------------------------------------------
def _fetch(img, ix, iy):
    h, w, _ = img.shape
    return img[np.clip(iy, 0, h - 1), np.clip(ix, 0, w - 1)]


def sample_bilinear(img, u, v):
    """u, v in texel units (texel centres at i + 0.5), like a GPU bilinear sample."""
    x, y = u - 0.5, v - 0.5
    x0, y0 = np.floor(x).astype(int), np.floor(y).astype(int)
    fx, fy = (x - x0)[..., None], (y - y0)[..., None]
    a, b = _fetch(img, x0, y0), _fetch(img, x0 + 1, y0)
    c, d = _fetch(img, x0, y0 + 1), _fetch(img, x0 + 1, y0 + 1)
    return (a * (1 - fx) + b * fx) * (1 - fy) + (c * (1 - fx) + d * fx) * fy


def sample_catmull_rom(img, u, v):
    """5-tap bilinear Catmull-Rom (the HLSL version; corner taps dropped, as is usual), clamped to the 4 centre texels'
    range so it cannot ring past the photo's own values."""
    x, y = u - 0.5, v - 0.5
    x1, y1 = np.floor(x), np.floor(y)
    f = np.stack([x - x1, y - y1], -1)
    w0 = f * (-0.5 + f * (1.0 - 0.5 * f))
    w1 = 1.0 + f * f * (-2.5 + 1.5 * f)
    w2 = f * (0.5 + f * (2.0 - 1.5 * f))
    w3 = f * f * (-0.5 + 0.5 * f)
    w12 = w1 + w2
    o12 = w2 / w12
    t0, t3 = (np.stack([x1, y1], -1) - 1.0 + 0.5), (np.stack([x1, y1], -1) + 2.0 + 0.5)
    t12 = np.stack([x1, y1], -1) + 0.5 + o12
    S = lambda tx, ty: sample_bilinear(img, tx, ty)
    r = (S(t12[..., 0], t0[..., 1]) * (w12[..., 0] * w0[..., 1])[..., None]
         + S(t0[..., 0], t12[..., 1]) * (w0[..., 0] * w12[..., 1])[..., None]
         + S(t12[..., 0], t12[..., 1]) * (w12[..., 0] * w12[..., 1])[..., None]
         + S(t3[..., 0], t12[..., 1]) * (w3[..., 0] * w12[..., 1])[..., None]
         + S(t12[..., 0], t3[..., 1]) * (w12[..., 0] * w3[..., 1])[..., None])
    norm = (w12[..., 0] * w0[..., 1] + w0[..., 0] * w12[..., 1] + w12[..., 0] * w12[..., 1]
            + w3[..., 0] * w12[..., 1] + w12[..., 0] * w3[..., 1])[..., None]
    r = r / norm
    x0i, y0i = x1.astype(int), y1.astype(int)
    q = [_fetch(img, x0i + i, y0i + j) for i in (0, 1) for j in (0, 1)]
    lo, hi = np.minimum.reduce(q), np.maximum.reduce(q)
    return np.clip(r, lo, hi)


# ---- micro detail (same as the HLSL) ---------------------------------------------------------------------------------
def _hash2(ix, iy):
    """integer lattice hash -> 0..1 (uint32 wrap-around, the same as the HLSL uint version)."""
    with np.errstate(over="ignore"):
        n = ix.astype(np.int64).astype(np.uint32) * np.uint32(374761393) + iy.astype(np.int64).astype(np.uint32) * np.uint32(668265263)
        n = (n ^ (n >> np.uint32(13))) * np.uint32(1274126177)
        n = n ^ (n >> np.uint32(16))
    return n.astype(np.float64) / 4294967296.0


def value_noise(x, y):
    """smooth value noise -1..1 on a unit lattice (world metres / wavelength)."""
    ix, iy = np.floor(x), np.floor(y)
    fx, fy = x - ix, y - iy
    ux, uy = fx * fx * (3 - 2 * fx), fy * fy * (3 - 2 * fy)
    a, b = _hash2(ix, iy), _hash2(ix + 1, iy)
    c, d = _hash2(ix, iy + 1), _hash2(ix + 1, iy + 1)
    return ((a * (1 - ux) + b * ux) * (1 - uy) + (c * (1 - ux) + d * ux) * uy) * 2.0 - 1.0


P = dict(DetailAmp=0.07, DetailL1=0.13, DetailL2=0.37, DetailVeg=1.0, DetailGrey=0.55, DetailBright=0.25,
         DetailNear=150.0, DetailFar=700.0, SharpTexels=1.2)


def detail_factor(col, wx, wy, dist, foot, sea):
    """col = linear-ish photo colour (here sRGB 0..1 is fine for the class mask), wx / wy world metres, dist m from the
    camera, foot = metres per screen pixel. Returns a multiplier around 1.0 (luminance only)."""
    r, g, b = col[..., 0], col[..., 1], col[..., 2]
    lum = 0.2126 * r + 0.7152 * g + 0.0722 * b
    mx, mn = np.maximum(np.maximum(r, g), b), np.minimum(np.minimum(r, g), b)
    sat = (mx - mn) / np.maximum(mx, 1e-4)
    veg = np.clip((g - np.maximum(r, b)) * 12.0, 0, 1) * np.clip(sat * 4.0, 0, 1)
    bright = np.clip((lum - 0.55) * 4.0, 0, 1)
    cls = P["DetailVeg"] * veg + P["DetailGrey"] * (1 - veg) * (1 - bright) + P["DetailBright"] * bright * (1 - veg)
    n = 0.0
    for lam, wgt in ((P["DetailL1"], 0.6), (P["DetailL2"], 0.4)):
        aa = np.clip(1.0 - (foot / (0.5 * lam) - 0.5), 0, 1)              # fade an octave out before it aliases
        n = n + wgt * aa * value_noise(wx / lam, wy / lam)
    fade = 1.0 - np.clip((dist - P["DetailNear"]) / (P["DetailFar"] - P["DetailNear"]), 0, 1)
    return 1.0 + P["DetailAmp"] * cls * fade * (1 - sea) * n


def render(blk, origin, alt_m, lat, mode, out_px=384, view_m=None):
    """nadir view from alt_m (no perspective; screen pixel = a fixed ground size like the screen centre of a 75 deg fov
    1920 px view). view_m = ground width shown."""
    gsd = 156543.03392 * math.cos(math.radians(lat)) / 2 ** Z                 # m per z19 texel
    foot = 2.0 * alt_m * math.tan(math.radians(37.5)) / 1920.0               # m per screen pixel at the centre
    if view_m is None:
        view_m = foot * out_px
    s = (np.arange(out_px) + 0.5) / out_px - 0.5
    gx, gy = np.meshgrid(s * view_m, s * view_m)
    u, v = origin[0] + gx / gsd, origin[1] + gy / gsd
    if mode == "bilinear":
        col = sample_bilinear(blk, u, v)
    else:
        mag = gsd / foot                                                       # screen pixels per texel
        k = np.clip((mag - 1.0) / max(P["SharpTexels"] - 1.0, 1e-3), 0, 1)
        col = sample_bilinear(blk, u, v) * (1 - k) + sample_catmull_rom(blk, u, v) * k
        if mode == "detail":
            lum = col @ np.array([0.2126, 0.7152, 0.0722], np.float32)
            sea = (lum < 0.16).astype(np.float32) * (col[..., 2] > col[..., 0]).astype(np.float32)  # rough: the
            # engine uses the DEM 0 m sea mask, here dark-blue pixels stand in for it
            col = col * detail_factor(col, gx, gy, alt_m, foot, sea)[..., None]
    return np.clip(col, 0, 1), gsd, foot


def sharp_metric(img):
    """mean |Laplacian| of luminance x 1000 (higher = more fine contrast)."""
    l = img @ np.array([0.2126, 0.7152, 0.0722], np.float32)
    lap = 4 * l[1:-1, 1:-1] - l[:-2, 1:-1] - l[2:, 1:-1] - l[1:-1, :-2] - l[1:-1, 2:]
    return float(np.abs(lap).mean() * 1000.0)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--alts", default="60,150,400")
    a = ap.parse_args()
    os.makedirs(os.path.join(a.out, "img"), exist_ok=True)
    alts = [float(x) for x in a.alts.split(",")]
    res, t0 = [], time.time()
    for name, label, lat, lon in SITES:
        blk, org = load_block(lat, lon)
        if blk is None:
            print("skip (not cached)", name)
            continue
        site = dict(name=name, label=label, lat=lat, lon=lon, alts=[])
        for alt in alts:
            row = dict(alt=alt)
            for mode in ("bilinear", "catmull", "detail"):
                img, gsd, foot = render(blk, org, alt, lat, mode)
                fn = "img/%s_%d_%s.png" % (name, alt, mode)
                Image.fromarray((img * 255 + 0.5).astype(np.uint8)).save(os.path.join(a.out, fn))
                row[mode] = dict(file=fn, sharp=round(sharp_metric(img), 2))
                row["gsd"], row["foot"] = round(gsd, 3), round(foot, 3)
            site["alts"].append(row)
        res.append(site)
        print(name, [(r["alt"], r["bilinear"]["sharp"], r["catmull"]["sharp"], r["detail"]["sharp"]) for r in site["alts"]],
              flush=True)
    meta = dict(made=time.strftime("%Y-%m-%d %H:%M:%S"), cache=CACHE, zoom=Z, params=P, sites=res,
                note="emulation of ground_detail.hlsl (nadir, screen-centre pixel size of a 1920 px 75 deg view)",
                runtime_s=round(time.time() - t0, 1))
    json.dump(meta, open(os.path.join(a.out, "results.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("wrote", os.path.join(a.out, "results.json"))


if __name__ == "__main__":
    main()
