"""Pilot flight-suit / glove detail textures (11-20, cockpit round 6). Plain CPython + numpy + Pillow (+ scipy for the
leather cells), no Unreal:

    python Scripts/pilot/suit_textures.py [--out DIR] [--no-preview]

Writes tileable PNGs to MANNY_DIR/tex6 (C:/GyroSimParts/thirdparty/manny/tex6, outside git) for the master material
M_PilotCloth (Scripts/pilot/ue_manny.py materials6()). All three are PACKED LINEAR textures (not sRGB, not BC5 normal
maps), so one sample gives normal + roughness + cavity:

    T_PM6_Weave.png    1024  R,G = normal x,y   B = roughness variation (0.5 = none)   A = cavity (mean 0.5; high = thread top)
                             2/1 twill, 72 threads per tile, ripstop rib every 12 threads. Meant to tile every ~8 cm.
    T_PM6_Leather.png  1024  same layout: pebble grain (cells ~1.3 mm at a 7 cm tile) + crease lines + pores
    T_PM6_Wrinkle.png   512  R,G = normal x,y   B = fold cavity (mean 0.5; low = bottom of a fold)
                             A = slow mottling (0.5 = none). Folds run ALONG U (= round the limb: the body UVs are
                             u = round the segment, v = along it) with a weaker diagonal set. Meant to tile every 15-30 cm.

Normal convention = the other generators here (ck2_textures.py): x = -dh/dcolumn, y = +dh/drow (DirectX, green down);
z is rebuilt in the material. Deterministic (fixed seeds). preview_*.jpg: numpy-lit views to judge the relief.
"""
import argparse
import json
import math
import os
import time

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

MANNY_DIR = os.environ.get("GYROSIM_MANNY_DIR", "C:/GyroSimParts/thirdparty/manny")
OUT = os.path.join(MANNY_DIR, "tex6")


# ---- tileable helpers -----------------------------------------------------------------------------------------------
def fft_noise(S, rng, lobes):
    """periodic noise: white noise filtered in the frequency domain. lobes = [(fx, fy, sx, sy, amp)] gaussian lobes in
    cycles per tile (fx along columns, fy along rows); mirrored lobes are added automatically. Unit variance."""
    w = rng.normal(0, 1, (S, S))
    F = np.fft.fft2(w)
    fy = np.fft.fftfreq(S) * S
    fx = np.fft.fftfreq(S) * S
    FX, FY = np.meshgrid(fx, fy)
    H = np.zeros((S, S))
    for cx, cy, sx, sy, amp in lobes:
        for sg in (1, -1):
            H += amp * np.exp(-0.5 * (((FX - sg * cx) / sx) ** 2 + ((FY - sg * cy) / sy) ** 2))
    H[0, 0] = 0.0
    n = np.real(np.fft.ifft2(F * H))
    return n / (n.std() + 1e-9)


def blur_wrap(a, sigma):
    """gaussian blur with wrap-around (FFT)."""
    S0, S1 = a.shape
    fy = np.fft.fftfreq(S0)[:, None]
    fx = np.fft.fftfreq(S1)[None, :]
    H = np.exp(-2.0 * (math.pi * sigma) ** 2 * (fx * fx + fy * fy))
    return np.real(np.fft.ifft2(np.fft.fft2(a) * H))


def warp_wrap(a, dx, dy):
    """bilinear lookup a[y + dy, x + dx] with wrap (dx, dy in pixels)."""
    S0, S1 = a.shape
    yy, xx = np.mgrid[0:S0, 0:S1].astype(np.float64)
    x, y = (xx + dx) % S1, (yy + dy) % S0
    x0, y0 = np.floor(x).astype(int), np.floor(y).astype(int)
    tx, ty = x - x0, y - y0
    x1, y1 = (x0 + 1) % S1, (y0 + 1) % S0
    return (a[y0, x0] * (1 - tx) + a[y0, x1] * tx) * (1 - ty) + (a[y1, x0] * (1 - tx) + a[y1, x1] * tx) * ty


def normal_xy(h, rms):
    """height -> (nx, ny) of the unit normal, gradients with wrap, scaled so the RMS slope is `rms`."""
    gx = (np.roll(h, -1, 1) - np.roll(h, 1, 1)) * 0.5
    gy = (np.roll(h, -1, 0) - np.roll(h, 1, 0)) * 0.5
    k = rms / (math.sqrt(float((gx * gx + gy * gy).mean())) + 1e-9)
    nx, ny = -gx * k, gy * k
    ln = np.sqrt(nx * nx + ny * ny + 1.0)
    return nx / ln, ny / ln


def norm01(a, lo=0.5, hi=99.5):
    p0, p1 = np.percentile(a, lo), np.percentile(a, hi)
    return np.clip((a - p0) / (p1 - p0 + 1e-9), 0.0, 1.0)


def neutral(c):
    """cavity -> same map rescaled to mean 0.5, so the material's 1 + (c x 2 - 1) x Amount never changes the mean albedo."""
    return np.clip(0.5 * c / c.mean(), 0.0, 1.0)


def pack(nx, ny, b, a):
    """-> RGBA uint8 image. A is kept >= 8 (Unreal's PNG importer rewrites RGB where alpha is 0)."""
    ch = [nx * 0.5 + 0.5, ny * 0.5 + 0.5, b, np.maximum(a, 8.0 / 255.0)]
    return Image.fromarray((np.stack(ch, -1) * 255.0 + 0.5).clip(0, 255).astype(np.uint8), "RGBA")


# ---- (a) weave --------------------------------------------------------------------------------------------------------
def build_weave(S=1024, N=72, rib=12, seed=11):
    """2/1 twill (warp over two, under one -> the diagonal wale) with a ripstop rib every `rib` threads."""
    rng = np.random.default_rng(seed)
    yy, xx = np.mgrid[0:S, 0:S].astype(np.float64)
    # slight periodic yarn wander so the threads are not ruler straight
    wob = fft_noise(S, rng, [(2.0, 2.0, 2.0, 2.0, 1.0)]) * 0.9
    wob2 = fft_noise(S, rng, [(2.0, -2.0, 2.0, 2.0, 1.0)]) * 0.9
    u = (xx + wob) * N / S
    v = (yy + wob2) * N / S
    i, j = np.floor(u).astype(int) % N, np.floor(v).astype(int) % N
    a, b = u - np.floor(u) - 0.5, v - np.floor(v) - 0.5          # -0.5 .. 0.5 across the warp / weft thread
    tw = 1.0 + rng.normal(0, 0.10, N)                              # per-thread thickness
    tf = 1.0 + rng.normal(0, 0.10, N)
    ribw = (np.arange(N) % rib == 0)
    tw = tw + ribw * 0.55
    tf = tf + ribw * 0.55
    warp_up = ((i + j) % 3) != 0
    # a rib thread always floats on top (that is what makes the ripstop grid read)
    warp_up = np.where(ribw[i], True, np.where(ribw[j], False, warp_up))
    cross_w = np.cos(math.pi * a) ** 0.8                           # round across its width
    cross_f = np.cos(math.pi * b) ** 0.8
    hw = tw[i] * cross_w * (0.55 + 0.45 * np.cos(math.pi * b) ** 2)   # crown where it passes over
    hf = tf[j] * cross_f * (0.55 + 0.45 * np.cos(math.pi * a) ** 2)
    under_w = tw[i] * cross_w * 0.35
    under_f = tf[j] * cross_f * 0.35
    h = np.where(warp_up, np.maximum(hw, under_f), np.maximum(hf, under_w))
    # fibres: fine streaks along each thread's own direction
    fib_w = fft_noise(S, rng, [(160.0, 0.0, 60.0, 14.0, 1.0)])     # varies across x fast, along y slowly = warp fibres
    fib_f = fft_noise(S, rng, [(0.0, 160.0, 14.0, 60.0, 1.0)])
    h = h + 0.05 * np.where(warp_up, fib_w, fib_f)
    h = blur_wrap(h, 0.9)
    # slow thickness variation (slubs / wear)
    slow = fft_noise(S, rng, [(0.0, 0.0, 5.0, 5.0, 1.0)])
    h = h * (1.0 + 0.06 * slow)
    hn = norm01(h)
    nx, ny = normal_xy(h, 0.42)
    fuzz = fft_noise(S, rng, [(0.0, 0.0, 90.0, 90.0, 1.0)])
    rough = 0.5 + 0.30 * (0.5 - hn) + 0.10 * slow + 0.05 * fuzz    # gaps rougher, crowns a little smoother
    cav = 0.35 + 0.65 * hn ** 0.8
    return pack(nx, ny, np.clip(rough, 0, 1), neutral(np.clip(cav, 0, 1))), hn


# ---- (b) wrinkles -----------------------------------------------------------------------------------------------------
def build_wrinkle(S=512, seed=23):
    """soft compression folds along U (image rows) + a weaker diagonal set, calm areas in between."""
    rng = np.random.default_rng(seed)
    main = fft_noise(S, rng, [(0.6, 4.0, 1.3, 1.2, 1.0), (1.2, 7.0, 1.6, 1.6, 0.45)])
    diag = fft_noise(S, rng, [(3.0, 4.0, 1.0, 1.0, 1.0), (-2.0, 5.0, 1.0, 1.0, 0.8)])
    wx = fft_noise(S, rng, [(0.0, 0.0, 2.2, 2.2, 1.0)]) * S * 0.030
    wy = fft_noise(S, rng, [(0.0, 0.0, 2.2, 2.2, 1.0)]) * S * 0.022
    main, diag = warp_wrap(main, wx, wy), warp_wrap(diag, wy, wx)
    calm = norm01(fft_noise(S, rng, [(0.0, 0.0, 1.8, 1.8, 1.0)]), 2, 98)          # 0 = flat cloth, 1 = bunched
    calm = 0.25 + 0.75 * calm ** 1.3
    f = main + 0.45 * diag
    # fold profile: rounded ridges, pinched valleys (soft abs keeps the valley line from being a hard crease)
    ridge = np.sqrt(f * f + 0.10) - math.sqrt(0.10)
    h = (0.75 * ridge + 0.35 * f) * calm
    h = h + 0.25 * fft_noise(S, rng, [(0.0, 0.0, 1.6, 1.6, 1.0)])                   # broad puff
    h = blur_wrap(h, 1.6)
    nx, ny = normal_xy(h, 0.26)
    valley = 1.0 - norm01(blur_wrap(h, 3.0), 1, 99)
    cav = 1.0 - 0.75 * np.clip((valley - 0.45) / 0.55, 0, 1) ** 1.5
    mot = fft_noise(S, rng, [(0.0, 0.0, 3.0, 3.0, 1.0), (0.0, 0.0, 12.0, 12.0, 0.25)])
    mot = np.clip(0.5 + 0.18 * mot, 0, 1)
    return pack(nx, ny, neutral(np.clip(cav, 0, 1)), mot), norm01(h)


# ---- (c) leather ------------------------------------------------------------------------------------------------------
def build_leather(S=1024, cells=54, seed=37):
    """pebble grain: jittered-grid Worley cells (F2 - F1 = groove distance), crease lines, pores."""
    from scipy.spatial import cKDTree
    rng = np.random.default_rng(seed)
    g = (np.stack(np.meshgrid(np.arange(cells), np.arange(cells)), -1).reshape(-1, 2) + rng.random((cells * cells, 2)) * 0.95) / cells
    pts = np.concatenate([g + np.array([ox, oy]) for ox in (-1, 0, 1) for oy in (-1, 0, 1)])
    yy, xx = np.mgrid[0:S, 0:S].astype(np.float64)
    # stretch the lookup a little with slow noise: pebbles get elongated / different sizes across the tile
    sx = fft_noise(S, rng, [(0.0, 0.0, 2.5, 2.5, 1.0)]) * 0.012
    sy = fft_noise(S, rng, [(0.0, 0.0, 2.5, 2.5, 1.0)]) * 0.012
    q = np.stack([((xx + 0.5) / S + sx) % 1.0, ((yy + 0.5) / S + sy) % 1.0], -1).reshape(-1, 2)
    d, idx = cKDTree(pts).query(q, k=2)
    f1, f2 = d[:, 0].reshape(S, S) * cells, d[:, 1].reshape(S, S) * cells
    groove = np.clip((f2 - f1) / 0.42, 0, 1)                       # 0 in the groove, 1 on the pebble
    peb = groove ** 0.6
    cell_h = (rng.random(len(pts))[idx[:, 0] % (cells * cells)]).reshape(S, S)       # same value in all 9 copies -> tiles
    h = peb * (0.75 + 0.25 * cell_h)
    # crease lines: long, gently curved, wrapped by drawing at the 9 tile offsets
    img = Image.new("L", (S, S), 0)
    dr = ImageDraw.Draw(img)
    for _ in range(26):
        x, y = rng.random(2) * S
        ang = rng.normal(0.0, 0.5) + (math.pi / 2 if rng.random() < 0.25 else 0.0)
        ln, bend, wd = 120 + rng.random() * 520, rng.normal(0, 0.0016), 2 + int(rng.random() * 3)
        p = []
        for k in range(40):
            p.append((x, y))
            x, y = x + math.cos(ang) * ln / 40, y + math.sin(ang) * ln / 40
            ang += bend * ln / 40 + rng.normal(0, 0.03)
        val = int(110 + rng.random() * 145)
        for ox in (-S, 0, S):
            for oy in (-S, 0, S):
                dr.line([(a + ox, b + oy) for a, b in p], fill=val, width=wd)
    pad = np.pad(np.asarray(img, np.float64) / 255.0, 16, mode="wrap")
    crease = np.asarray(Image.fromarray((pad * 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(1.8)), np.float64)[16:-16, 16:-16] / 255.0
    pores = fft_noise(S, rng, [(0.0, 0.0, 150.0, 150.0, 1.0)])
    slow = fft_noise(S, rng, [(0.0, 0.0, 4.0, 4.0, 1.0)])
    h = h - 1.1 * crease + 0.04 * pores + 0.10 * slow
    h = blur_wrap(h, 1.1)
    nx, ny = normal_xy(h, 0.36)
    rough = 0.5 + 0.28 * (0.6 - peb) + 0.25 * crease + 0.12 * slow          # worn pebble tops shine, grooves stay matte
    cav = np.clip((0.45 + 0.55 * peb) * (1.0 - 0.55 * crease), 0, 1)
    return pack(nx, ny, np.clip(rough, 0, 1), neutral(cav)), norm01(h)


# ---- previews ---------------------------------------------------------------------------------------------------------
def _sample(img, u, v):
    """bilinear, wrapped sample of a float array (H, W, C) at uv (tile units)."""
    H, W = img.shape[:2]
    x, y = (u % 1.0) * W - 0.5, (v % 1.0) * H - 0.5
    x0, y0 = np.floor(x).astype(int), np.floor(y).astype(int)
    tx, ty = (x - x0)[..., None], (y - y0)[..., None]
    x0, y0, x1, y1 = x0 % W, y0 % H, (x0 + 1) % W, (y0 + 1) % H
    return (img[y0, x0] * (1 - tx) + img[y0, x1] * tx) * (1 - ty) + (img[y1, x0] * (1 - tx) + img[y1, x1] * tx) * ty


def shade_cylinder(detail, wrinkle, tint, radius_cm, length_cm, px_per_cm=24, ss=3, detail_tile=12.5, detail_amt=1.0,
                   wrinkle_tile=5.0, wrinkle_amt=1.0, macro_tile=1.7, macro_amt=0.5, rough=0.85, spec=0.35, wr_ao=0.5, det_ao=0.5,
                   light=(0.55, -0.35, 0.76), exposure=9.0):
    """what M_PilotCloth does, on a limb-sized cylinder (axis = image vertical), body UVs as in manny_fbx.py
    (u = angle x 0.08 m, v = metres along), one directional light + a weak ambient, orthographic view.
    ss = supersampling (stands in for the mip chain). px_per_cm 24 ~ a 1080p monitor view from ~40 cm."""
    D = np.asarray(detail, np.float64) / 255.0
    Wr = np.asarray(wrinkle, np.float64) / 255.0
    W, H = int(2 * radius_cm * px_per_cm * ss), int(length_cm * px_per_cm * ss)
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float64)
    x = (xx + 0.5) / W * 2 - 1                                      # -1 .. 1 across
    x = np.clip(x, -0.999, 0.999)
    th = np.arcsin(x)
    u, v = th * 0.08, (yy + 0.5) / (px_per_cm * ss) / 100.0
    d = _sample(D, u * detail_tile, v * detail_tile)
    w = _sample(Wr, u * wrinkle_tile, v * wrinkle_tile)
    m = _sample(Wr, u * macro_tile + 0.37, v * macro_tile + 0.61)
    nxy = (d[..., :2] * 2 - 1) * detail_amt + (w[..., :2] * 2 - 1) * wrinkle_amt + (m[..., :2] * 2 - 1) * macro_amt
    n = np.concatenate([nxy, np.ones_like(nxy[..., :1])], -1)
    n /= np.linalg.norm(n, axis=-1, keepdims=True)
    # tangent frame of the cylinder: T (u, round) = (cos th, 0, -sin th), B (v, down the image) = (0, 1, 0), N = (sin th, 0, cos th)
    ct, st = np.cos(th), np.sin(th)
    wn = np.stack([n[..., 0] * ct + n[..., 2] * st, -n[..., 1], -n[..., 0] * st + n[..., 2] * ct], -1)
    L = np.array(light) / np.linalg.norm(light)
    V = np.array([0.0, 0.0, 1.0])
    Hh = (L + V) / np.linalg.norm(L + V)
    ndl = np.clip(wn @ L, 0, 1)
    ndh = np.clip(wn @ Hh, 0, 1)
    ndv = np.clip(wn[..., 2], 0, 1)
    r = np.clip(rough + (d[..., 2] - 0.5) * 0.3, 0.2, 1.0)
    a2 = (r * r) ** 2
    ggx = a2 / (math.pi * ((ndh * ndh) * (a2 - 1) + 1) ** 2)
    alb = np.array(tint)[None, None, :] * (1 + det_ao * (d[..., 3:4] * 2 - 1)) * (1 + wr_ao * (w[..., 2:3] * 2 - 1)) * (1 + (m[..., 3:4] - 0.5) * 0.6)
    fuzz = (1 - ndv) ** 3
    col = alb * (1 + 1.0 * fuzz[..., None]) * (ndl[..., None] * 3.0 + 0.25) / math.pi + (0.04 * spec / 0.5 * 2 * d[..., 3] * ggx * ndl * 3.0 * 0.25)[..., None]
    img = (1 - np.exp(-col * exposure)) ** (1 / 2.2)
    img = Image.fromarray((img * 255).clip(0, 255).astype(np.uint8))
    return img.resize((W // ss, H // ss), Image.LANCZOS)


def previews(out, tex):
    """side-by-side limbs: sleeve / thigh with no wrinkles, default, strong; glove; flat close-ups of each map."""
    suit, glove = (0.011, 0.013, 0.0078), (0.006, 0.006, 0.006)
    cols = [("weave only", dict(wrinkle_amt=0.0, macro_amt=0.0, wr_ao=0.0)), ("default", dict()), ("wrinkle 1.8", dict(wrinkle_amt=1.8, macro_amt=0.8, wr_ao=0.8))]
    ims = [shade_cylinder(tex["weave"], tex["wrinkle"], suit, 5.0, 26.0, **kw) for _, kw in cols]
    ims.append(shade_cylinder(tex["weave"], tex["wrinkle"], suit, 8.5, 26.0))                          # thigh
    ims.append(shade_cylinder(tex["leather"], tex["wrinkle"], glove, 4.5, 26.0, detail_tile=14.0, wrinkle_tile=9.0, wrinkle_amt=0.6,
                              macro_amt=0.3, rough=0.6, spec=0.5, exposure=14.0))
    W = sum(i.width for i in ims) + 10 * (len(ims) + 1)
    sheet = Image.new("RGB", (W, ims[0].height + 20), (18, 18, 20))
    x = 10
    for i in ims:
        sheet.paste(i, (x, 10))
        x += i.width + 10
    sheet.save(os.path.join(out, "preview_limbs.jpg"), quality=90)
    # flat lit close-ups (one tile each, light from the upper left): relief check of the raw maps
    fl = []
    for k in ("weave", "leather", "wrinkle"):
        a = np.asarray(tex[k], np.float64) / 255.0
        nx, ny = a[..., 0] * 2 - 1, a[..., 1] * 2 - 1
        nz = np.sqrt(np.clip(1 - nx * nx - ny * ny, 0, 1))
        L = np.array([-0.5, -0.5, 0.7]) / np.linalg.norm([-0.5, -0.5, 0.7])
        s = np.clip(nx * L[0] - ny * L[1] + nz * L[2], 0, 1) * np.clip(0.4 + 1.2 * (a[..., 3] if k != "wrinkle" else a[..., 2]), 0, 1)
        fl.append(Image.fromarray((s ** (1 / 2.2) * 255).astype(np.uint8)).resize((512, 512), Image.LANCZOS))
        if k != "wrinkle":
            c = a.shape[0] // 8
            fl.append(Image.fromarray((s[:c * 2, :c * 2] ** (1 / 2.2) * 255).astype(np.uint8)).resize((512, 512), Image.LANCZOS))
    sheet = Image.new("L", (512 * len(fl), 512))
    for n, i in enumerate(fl):
        sheet.paste(i, (512 * n, 0))
    sheet.save(os.path.join(out, "preview_maps.jpg"), quality=90)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=OUT)
    ap.add_argument("--no-preview", action="store_true")
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    t0 = time.time()
    tex = {}
    for name, fn in (("weave", build_weave), ("wrinkle", build_wrinkle), ("leather", build_leather)):
        img, _ = fn()
        img.save(os.path.join(a.out, "T_PM6_%s.png" % name.capitalize()))
        tex[name] = img
        px = np.asarray(img, np.float64) / 255.0
        print("[suit_textures] %-8s %s  mean RGBA %s" % (name, img.size, np.round(px.reshape(-1, 4).mean(0), 3)))
    json.dump(dict(made=time.strftime("%Y-%m-%d %H:%M:%S"), script="Scripts/pilot/suit_textures.py", inputs="none (procedural, fixed seeds 11 / 23 / 37)",
                   layout="RG normal xy (DirectX), B roughness variation (weave, leather) or fold cavity (wrinkle), A cavity (weave, leather) or mottling (wrinkle); every data channel is neutral at 0.5"),
              open(os.path.join(a.out, "tex6.json"), "w"), indent=1)
    if not a.no_preview:
        previews(a.out, tex)
    print("[suit_textures] %.1f s -> %s" % (time.time() - t0, a.out))


if __name__ == "__main__":
    main()
