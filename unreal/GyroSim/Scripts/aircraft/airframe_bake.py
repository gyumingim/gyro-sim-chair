#!/usr/bin/env python3
"""airframe_bake.py - 4K skin texture set for the airframe v2 (no paid tools: numpy / scipy / Pillow).

Input: ThirdParty/f16_airframe/bake_input.npz (airframe_split.py: every part's triangles in absolute UE body cm with
UVs / normals) and tex_f16.png (the FG skin, GPL). Output (GPL derived, outside git) in the same folder:
  tex_af2_base.png  4096^2 sRGB  two-tone F-16 grey (light sides / underside, darker grey on the upper surfaces with a
                    soft, noise-warped boundary), crisp panel lines and rivet rows, soft airflow streaks, exhaust soot
                    on the aft fuselage, gun-port soot (approximate position), baked AO (half strength in the colour)
  tex_af2_n.png     4096^2 tangent normal: panel lines as recesses, rivet heads as tiny domes
  tex_af2_orm.png   4096^2 linear: R = AO (full), G = roughness, B = metallic (0)
Steps: rasterise the UV layout (1024^2) into position / normal maps -> tone, soot, streaks and AO (voxel ray march,
4 cm voxels, 24 rays, 1.4 m) at 1K, upsampled; panel lines from the FG line art, upsampled to 4K and sharpened;
rivets = dots on a 10 px grid in a band beside each line. No markings, no stencil text.
Run: python Scripts/aircraft/airframe_bake.py   (~1-3 min)
"""
import time
from pathlib import Path

import numpy as np
from PIL import Image
from scipy.ndimage import binary_dilation, distance_transform_edt, gaussian_filter, map_coordinates, zoom

DIR = Path(__file__).resolve().parents[2] / "ThirdParty" / "f16_airframe"
R = 1024                      # raster / AO resolution
OUT = 4096
# round 3 (customer / critic): neutral, darker - FS 36270 on the sides / underside / nose ~ sRGB 132/137/140
# (linear ~0.23), FS 36118 on the upper surfaces ~ sRGB 78/83/89 (linear ~0.08)
LIGHT = (np.array([132, 137, 140]) / 255.0) ** 2.2
UNDER = (np.array([158, 163, 167]) / 255.0) ** 2.2   # round 4: belly FS 36375-like (lighter)
RADOME = (np.array([150, 154, 156]) / 255.0) ** 2.2  # lighter grey radome
DARK = (np.array([78, 83, 89]) / 255.0) ** 2.2
FIN_RECT = (0.52, 0.865, 0.74, 0.995)            # = airframe_split.FIN_RECT (fin sides planar-mapped here)
MISSILE_RECT = (0.45, 0.968, 0.50, 0.992)        # = airframe_split.MISSILE_RECT
STENCIL = (np.array([40, 42, 44]) / 255.0) ** 2.2
GUN = np.array([215.0, -78.0, 48.0])           # gun port, approx. (left LERX root; not from the FG model)
rng = np.random.default_rng(16)


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


def noise3(P, scale, octaves=3):
    """value noise at points P (n,3) cm, feature size 'scale' cm, fractal."""
    out = np.zeros(len(P))
    amp, tot = 1.0, 0.0
    for o in range(octaves):
        s = scale / (2 ** o)
        g = rng.random((64, 64, 64))
        c = (P / s) % 63.0
        out += amp * map_coordinates(g, c.T, order=1, mode="wrap")
        tot += amp
        amp *= 0.5
    return out / tot


def raster(parts):
    """UV raster at R x R: position, normal, coverage."""
    pos = np.zeros((R, R, 3)); nrm = np.zeros((R, R, 3)); cov = np.zeros((R, R), bool)
    for V, T, UV, N in parts:
        for t in range(len(T)):
            uv = UV[t].copy()
            uv -= np.floor(uv.min(0))
            px = np.stack([uv[:, 0] * R, (1 - uv[:, 1]) * R], 1)
            x0, y0 = np.floor(px.min(0)).astype(int); x1, y1 = np.ceil(px.max(0)).astype(int)
            x0, y0 = max(x0, 0), max(y0, 0); x1, y1 = min(x1, R - 1), min(y1, R - 1)
            if x1 < x0 or y1 < y0:
                continue
            xs, ys = np.meshgrid(np.arange(x0, x1 + 1) + 0.5, np.arange(y0, y1 + 1) + 0.5)
            a, b, c = px
            d = (b[1] - c[1]) * (a[0] - c[0]) + (c[0] - b[0]) * (a[1] - c[1])
            if abs(d) < 1e-12:
                continue
            l0 = ((b[1] - c[1]) * (xs - c[0]) + (c[0] - b[0]) * (ys - c[1])) / d
            l1 = ((c[1] - a[1]) * (xs - c[0]) + (a[0] - c[0]) * (ys - c[1])) / d
            l2 = 1 - l0 - l1
            ins = (l0 >= -0.02) & (l1 >= -0.02) & (l2 >= -0.02)
            if not ins.any():
                continue
            L = np.stack([l0[ins], l1[ins], l2[ins]], 1)
            P3 = L @ V[T[t]]
            N3 = L @ N[t]
            yi, xi = (ys[ins] - 0.5).astype(int), (xs[ins] - 0.5).astype(int)
            pos[yi, xi] = P3; nrm[yi, xi] = N3; cov[yi, xi] = True
    n = np.linalg.norm(nrm, axis=2, keepdims=True)
    nrm = np.where(n > 1e-9, nrm / np.maximum(n, 1e-9), 0)
    return pos, nrm, cov


def voxels(parts, vs=4.0):
    allv = np.concatenate([V for V, *_ in parts])
    lo = allv.min(0) - 10; hi = allv.max(0) + 10
    shape = np.ceil((hi - lo) / vs).astype(int) + 1
    occ = np.zeros(shape, bool)
    for V, T, UV, N in parts:
        P = V[T]
        area = np.linalg.norm(np.cross(P[:, 1] - P[:, 0], P[:, 2] - P[:, 0]), axis=1) / 2
        k = np.clip((area / (vs * vs) * 4).astype(int) + 3, 3, 400)
        for kk in np.unique(k):
            sel = k == kk
            r = rng.random((sel.sum(), kk, 2))
            flip = r.sum(2) > 1
            r[flip] = 1 - r[flip]
            Q = P[sel][:, None, 0] + r[..., :1] * (P[sel][:, None, 1] - P[sel][:, None, 0]) + r[..., 1:] * (P[sel][:, None, 2] - P[sel][:, None, 0])
            idx = np.floor((Q.reshape(-1, 3) - lo) / vs).astype(int)
            occ[idx[:, 0], idx[:, 1], idx[:, 2]] = True
        for c in range(3):
            idx = np.floor((V - lo) / vs).astype(int)
            occ[idx[:, 0], idx[:, 1], idx[:, 2]] = True
    return occ, lo, vs


def ao_bake(pos, nrm, cov, occ, lo, vs, nray=24, steps=(6, 9, 13, 18, 24, 32, 42)):     # round 4: ~0.4 m radius (the 1.4 m one blobbed the spine)
    yi, xi = np.nonzero(cov)
    P, N = pos[yi, xi], nrm[yi, xi]
    # cosine-ish hemisphere directions (fixed set, rotated into each normal's frame)
    k = np.arange(nray) + 0.5
    phi = k * np.pi * (3 - np.sqrt(5))
    cz = np.sqrt(1 - k / nray)                       # cosine weighted elevation
    sz = np.sqrt(1 - cz * cz)
    D = np.stack([np.cos(phi) * sz, np.sin(phi) * sz, cz], 1)
    up = np.where(np.abs(N[:, 2:3]) < 0.9, np.array([[0, 0, 1.0]]), np.array([[1.0, 0, 0]]))
    Tg = np.cross(up, N); Tg /= np.linalg.norm(Tg, axis=1, keepdims=True)
    Bt = np.cross(N, Tg)
    ao = np.zeros(len(P))
    shp = np.array(occ.shape) - 1
    for i in range(0, len(P), 20000):
        p, t, b, n = P[i:i + 20000], Tg[i:i + 20000], Bt[i:i + 20000], N[i:i + 20000]
        dirs = D[None, :, 0:1] * t[:, None] + D[None, :, 1:2] * b[:, None] + D[None, :, 2:3] * n[:, None]   # (m, nray, 3)
        hit = np.zeros(dirs.shape[:2], bool)
        start = p[:, None] + n[:, None] * 5.0
        for s in steps:
            q = start + dirs * s
            idx = np.clip(np.floor((q - lo) / vs).astype(int), 0, shp)
            hit |= occ[idx[..., 0], idx[..., 1], idx[..., 2]]
        ao[i:i + 20000] = 1.0 - hit.mean(1)
    out = np.ones(cov.shape)
    out[yi, xi] = ao
    return out


def fill(img, cov):
    """push island values into the uncovered texels (no seams in the mips)."""
    _, (iy, ix) = distance_transform_edt(~cov, return_indices=True)
    return img[iy, ix]


def up(img, n=OUT, order=1):
    f = n / img.shape[0]
    if img.ndim == 3:
        return np.stack([zoom(img[..., c], f, order=order) for c in range(img.shape[2])], -1)
    return zoom(img, f, order=order)


def lum1k_lines(r):
    """the FG skin's panel-line art at r x r (0..1), for the streak sources."""
    src = np.asarray(Image.open(DIR / "tex_f16.png").convert("L"), np.float32) / 255.0
    hp = src - gaussian_filter(src, 2.5)
    ln = np.clip(-hp * 10.0, 0, 1)
    ln[binary_dilation(src > 0.985, iterations=6)] = 0
    return np.clip(zoom(gaussian_filter(ln, 1.0), r / ln.shape[0], order=1) * 2.0, 0, 1)


def flow_streaks(posf, cov, lines, steps=28, step_px=1.3):
    """streaks that run AFT from panel lines and fasteners (fluid / dirt carried by the airflow): for each texel, look
    upstream (toward +x, the local UV direction of increasing body x) and collect the line mask with a decay; break the
    streaks up with a little noise across the flow. Returns 0..1 at the raster resolution."""
    r = posf.shape[0]
    gx_v, gx_u = np.gradient(gaussian_filter(posf[..., 0], 1.0))   # d x / d row, d x / d col (cm per px)
    n = np.hypot(gx_u, gx_v) + 1e-6
    du, dv = gx_u / n, gx_v / n                                        # unit direction of +x in pixel space
    yy, xx = np.mgrid[0:r, 0:r].astype(np.float32)
    acc = np.zeros((r, r), np.float32)
    for k in range(1, steps + 1):
        s = map_coordinates(lines, [yy + dv * k * step_px, xx + du * k * step_px], order=1, mode="nearest")
        acc = np.maximum(acc, s * (0.93 ** k))
    acc *= cov
    brk = gaussian_filter(rng.random((r, r)).astype(np.float32), [0.8, 3.0])     # break-up: smooth, not speckle
    brk = (brk - brk.mean()) / (brk.std() + 1e-6)
    acc *= np.clip(0.7 + brk * 0.25, 0, 1)
    return np.clip(acc, 0, 1)


def nozzle_bake(z, names):
    """round 4 nozzle set from its own triangles (FG nozzle-GE geometry, its texture's UVs): burnished titanium petals with
    a heat gradient toward the exit (straw -> blued), a dark inner liner (faces whose normal points to the axis), petal
    ribs in the normal map from the angle around the axis. Out: tex_af2_noz_base / _n / _orm.png (1024 x 256)."""
    global R
    texkeys = z["texkeys"]
    tris = []
    for nm in names:
        V, T, UV, N, MK = (z[f"{nm}__{k}"] for k in ("V", "T", "UV", "N", "MK"))
        s = np.array(["nozzle-GE" in texkeys[m] for m in MK])
        if s.any():
            tris.append((V, T[s], UV[s], N[s]))
    if not tris:
        log("no nozzle tris"); return
    W, H = 1024, 256
    keep = R
    R = W                                                    # raster() is square: rasterise at W x W, keep the top H rows
    pos, nrm, cov = raster([(V, T, UV * np.array([1.0, H / W]) + np.array([0.0, 1 - H / W]), N) for V, T, UV, N in tris])
    R = keep
    pos, nrm, cov = pos[:H], nrm[:H], cov[:H]
    allV = np.concatenate([V[T].reshape(-1, 3) for V, T, _, _ in tris])
    cy, cz = np.median(allV[:, 1]), np.median(allV[:, 2])
    x0, x1 = allV[:, 0].min(), allV[:, 0].max()
    posf, nrmf = fill(pos, cov), fill(nrm, cov)
    t_ = np.clip((x1 - posf[..., 0]) / max(1.0, x1 - x0), 0, 1)       # 0 at the front, 1 at the exit
    radial = np.stack([np.zeros_like(t_), posf[..., 1] - cy, posf[..., 2] - cz], -1)
    radial /= np.linalg.norm(radial, axis=-1, keepdims=True) + 1e-6
    inner = np.clip(-(radial * nrmf).sum(-1) * 3.0, 0, 1)            # facing the axis = liner
    ti = (np.array([150, 146, 140]) / 255.0) ** 2.2                    # titanium grey
    straw = (np.array([152, 138, 112]) / 255.0) ** 2.2
    blued = (np.array([96, 98, 116]) / 255.0) ** 2.2
    g = t_[..., None]
    col = ti * (1 - g) + straw * np.clip(g * 2 - 0.4, 0, 1) * 0.0 + ti * 0
    col = np.where(g < 0.55, ti * (1 - g / 0.55) + straw * (g / 0.55), straw * (1 - (g - 0.55) / 0.45) + blued * ((g - 0.55) / 0.45))
    ang = np.arctan2(posf[..., 2] - cz, posf[..., 1] - cy)
    rib = 0.5 + 0.5 * np.cos(ang * 15.0)                              # 15 petals
    streak = gaussian_filter(rng.random((H, W)).astype(np.float32), [0.6, 8.0])
    streak = (streak - streak.mean()) / (streak.std() + 1e-6)
    col = col * (0.85 + 0.1 * rib[..., None]) * (1 + 0.06 * streak[..., None])
    liner = (np.array([28, 26, 24]) / 255.0) ** 2.2
    col = col * (1 - inner[..., None]) + liner * inner[..., None]
    Image.fromarray(np.clip(col ** (1 / 2.2) * 255 + 0.5, 0, 255).astype(np.uint8)).save(DIR / "tex_af2_noz_base.png")
    h = gaussian_filter(rib * (1 - inner), 1.0)
    gy, gx = np.gradient(h)
    n3 = np.stack([-gx * 4, -gy * 4, np.ones_like(h)], -1)
    n3 /= np.linalg.norm(n3, axis=-1, keepdims=True)
    Image.fromarray(np.clip((n3 * 0.5 + 0.5) * 255 + 0.5, 0, 255).astype(np.uint8)).save(DIR / "tex_af2_noz_n.png")
    orm = np.stack([np.ones_like(t_) * (1 - 0.4 * inner), 0.35 + 0.1 * inner + 0.03 * streak, 1.0 - 0.7 * inner], -1)
    Image.fromarray(np.clip(orm * 255 + 0.5, 0, 255).astype(np.uint8)).save(DIR / "tex_af2_noz_orm.png")
    log("nozzle set", int(cov.sum()), "texels; axis y %.1f z %.1f, x %.0f..%.0f" % (cy, cz, x0, x1))


def uvpx(u, v):
    return u * OUT, (1 - v) * OUT


def decals(base, rough, ln, z, names, posf, nrmf, cov):
    """round 3 'toy-clean' fixes, all generic (no real unit): gear bays painted as closed doors, fin sides in the fin grey
    with a generic code 'GS 01', missiles light grey, walkway outlines and NO STEP text on the wing tops (placed from
    the 3D position of each texel), small rescue / warning style stencils without real wording."""
    from PIL import ImageDraw, ImageFont
    mn, texkeys = z["mnames"], z["texkeys"]
    # gear bays: every triangle of the FG 'gearwell' materials -> closed-door paint with a door outline
    well = Image.new("L", (OUT, OUT), 0)
    dw = ImageDraw.Draw(well)
    for nm in names:
        UV, MK = z[f"{nm}__UV"], z[f"{nm}__MK"]
        sel = np.array(["gearwell" in mn[m].lower() and "f16.png" in texkeys[m] for m in MK])
        for tri in UV[sel]:
            tri = tri - np.floor(tri.min(0))
            dw.polygon([uvpx(*p) for p in tri], fill=255)
    wm = np.asarray(well, np.float32) / 255.0
    base[:] = base * (1 - wm[..., None]) + LIGHT * wm[..., None]
    edge = gaussian_filter(wm, 1.2); edge = np.clip((edge - 0.25) * 4, 0, 1) * np.clip((0.75 - edge) * 4, 0, 1)
    base[:] = base * (1 - 0.5 * edge[..., None])
    log("gear-bay texels", int((wm > 0.5).sum()))
    try:
        font = ImageFont.truetype("C:/Windows/Fonts/bahnschrift.ttf", 150)
        small = ImageFont.truetype("C:/Windows/Fonts/bahnschrift.ttf", 26)
    except OSError:
        font = small = ImageFont.load_default()
    # fin rect: fin grey + generic tail code
    u0, v0, u1, v1 = FIN_RECT
    x0, y1 = uvpx(u0, v0); x1, y0 = uvpx(u1, v1)
    x0, x1, y0, y1 = int(x0), int(x1), int(y0), int(y1)
    finc = LIGHT * 1.0
    base[y0:y1, x0:x1] = finc
    txt = Image.new("L", (x1 - x0, y1 - y0), 0)
    dt = ImageDraw.Draw(txt)
    dt.text(((x1 - x0) * 0.38, (y1 - y0) * 0.30), "GS", font=font, fill=255)
    dt.text(((x1 - x0) * 0.38, (y1 - y0) * 0.60), "26-801", font=ImageFont.truetype("C:/Windows/Fonts/bahnschrift.ttf", 46) if font is not small else font, fill=255)
    tm = gaussian_filter(np.asarray(txt, np.float32) / 255.0, 0.6)
    base[y0:y1, x0:x1] = base[y0:y1, x0:x1] * (1 - tm[..., None]) + STENCIL * tm[..., None]
    # fin cap: fictional unit colours, blue / white checker in the top ~12 % of the fin (z > ~312 cm)
    cap_h = int((y1 - y0) * 0.12)
    cy = np.arange(cap_h)[:, None] // max(1, cap_h // 2)
    cx = np.arange(x1 - x0)[None, :] // max(1, cap_h // 2)
    chk = ((cy + cx) % 2).astype(bool)
    blue, white = (np.array([22, 58, 128]) / 255.0) ** 2.2, (np.array([226, 228, 230]) / 255.0) ** 2.2
    base[y0:y0 + cap_h, x0:x1] = np.where(chk[..., None], blue, white)
    rough[y0:y1, x0:x1] = 0.55
    # walkway outlines / NO STEP on the wing tops: texel 3D position at 4K (bilinear from the 1K maps)
    P4 = np.stack([zoom(posf[..., c].astype(np.float32), OUT / posf.shape[0], order=1) for c in range(3)], -1)
    nz4 = zoom(nrmf[..., 2].astype(np.float32), OUT / nrmf.shape[0], order=1)
    top = nz4 > 0.75
    ay, x = np.abs(P4[..., 1]), P4[..., 0]
    inwing = (x > -260) & (x < -40)
    walk = top & inwing & ((np.abs(ay - 120) < 1.6) | (np.abs(ay - 205) < 1.6))
    walk |= top & (ay > 120) & (ay < 205) & ((np.abs(x + 45) < 1.6) | (np.abs(x + 255) < 1.6))
    wk = gaussian_filter(walk.astype(np.float32), 0.6)
    base[:] = base * (1 - 0.8 * wk[..., None]) + STENCIL * 0.8 * wk[..., None]
    # NO STEP: find the texel nearest to a wing-top point, write the text there (UV-aligned, small)
    for yy in (-265.0, 265.0):
        d = np.where(top, np.hypot(P4[..., 0] + 150.0, P4[..., 1] - yy), 1e9)
        iy, ix = np.unravel_index(np.argmin(d), d.shape)
        if d[iy, ix] > 20:
            continue
        stamp = Image.new("L", (190, 40), 0)
        ImageDraw.Draw(stamp).text((4, 4), "NO STEP", font=small, fill=255)
        sm = np.asarray(stamp, np.float32) / 255.0
        ys, xs = slice(max(iy - 20, 0), iy + 20), slice(max(ix - 95, 0), ix + 95)
        h, w = base[ys, xs].shape[:2]
        base[ys, xs] = base[ys, xs] * (1 - 0.85 * sm[:h, :w, None]) + STENCIL * 0.85 * sm[:h, :w, None]
    log("walkway texels", int(walk.sum()))
    # national insignia: a generic taegeuk-style roundel (no unit art) on the intake sides and the wing tops,
    # RESCUE arrow under the canopy rail - placed at the texel nearest to a 3D point with a matching normal
    cov4 = zoom(cov.astype(np.float32), OUT / cov.shape[0], order=0) > 0.5
    side4 = (np.abs(zoom(nrmf[..., 1].astype(np.float32), OUT / nrmf.shape[0], order=1)) > 0.75) & cov4
    top = top & cov4

    def nearest(pt, mask):
        d = np.where(mask, np.sqrt(((P4 - np.array(pt)) ** 2).sum(-1)), 1e9)
        iy, ix = np.unravel_index(np.argmin(d), d.shape)
        return (iy, ix) if d[iy, ix] < 60 else None

    def stamp(rgba, at):
        if at is None:
            return False
        iy, ix = at
        h, w = rgba.shape[:2]
        y0_, x0_ = max(iy - h // 2, 0), max(ix - w // 2, 0)
        reg = base[y0_:y0_ + h, x0_:x0_ + w]
        a_ = rgba[:reg.shape[0], :reg.shape[1], 3:4]
        reg[:] = reg * (1 - a_) + rgba[:reg.shape[0], :reg.shape[1], :3] * a_
        return True

    def roundel(px):
        im = Image.new("RGBA", (px, px), (0, 0, 0, 0))
        d = ImageDraw.Draw(im)
        d.ellipse([0, 0, px - 1, px - 1], fill=(235, 236, 238, 255))                     # white disc
        m = px * 0.16
        d.pieslice([m, m, px - m, px - m], 180, 360, fill=(178, 34, 40, 255))              # red upper half
        d.pieslice([m, m, px - m, px - m], 0, 180, fill=(28, 52, 120, 255))                # blue lower half
        q = (px - 2 * m) / 4
        d.ellipse([m, px / 2 - q, m + 2 * q, px / 2 + q], fill=(178, 34, 40, 255))         # taegeuk swirl (simplified)
        d.ellipse([px - m - 2 * q, px / 2 - q, px - m, px / 2 + q], fill=(28, 52, 120, 255))
        a = np.asarray(im, np.float32) / 255.0
        a[..., :3] = a[..., :3] ** 2.2 * 0.85                                                # paint, a bit muted
        return a

    hits = [stamp(roundel(150), nearest(pt, msk)) for pt, msk in
            (((-250.0, -75.0, 0.0), side4), ((-250.0, 75.0, 0.0), side4), ((-150.0, -300.0, 20.0), top), ((-150.0, 300.0, 20.0), top))]
    res = Image.new("RGBA", (220, 60), (0, 0, 0, 0))
    dr = ImageDraw.Draw(res)
    dr.polygon([(4, 30), (40, 6), (40, 18), (90, 18), (90, 42), (40, 42), (40, 54)], fill=(214, 160, 30, 255))
    dr.text((98, 14), "RESCUE", font=small, fill=(30, 30, 30, 255))
    ra = np.asarray(res, np.float32) / 255.0
    ra[..., :3] = ra[..., :3] ** 2.2
    hits += [stamp(ra, nearest((390.0, s * 62.0, 55.0), side4)) for s in (-1, 1)]
    log("insignia / rescue stamps placed", hits)
    # missiles
    u0, v0, u1, v1 = MISSILE_RECT
    mx0, my1 = uvpx(u0, v0); mx1, my0 = uvpx(u1, v1)
    base[int(my0):int(my1), int(mx0):int(mx1)] = (np.array([206, 208, 210]) / 255.0) ** 2.2
    rough[int(my0):int(my1), int(mx0):int(mx1)] = 0.38



def main():
    t0 = time.time()
    z = np.load(DIR / "bake_input.npz")
    texkeys = z["texkeys"]
    names = sorted({k.split("__")[0] for k in z.files if "__" in k})
    parts, skin = [], []
    for nm in names:
        V, T, UV, N, MK = (z[f"{nm}__{k}"] for k in ("V", "T", "UV", "N", "MK"))
        parts.append((V, T, UV, N))
        s = np.array(["f16.png" in texkeys[m] for m in MK])
        skin.append((V, T[s], UV[s], N[s]))
    log("parts", names, "skin tris", sum(len(s[1]) for s in skin))
    pos, nrm, cov = raster(skin)
    log("raster", cov.mean().round(3))
    occ, lo, vs = voxels(parts)
    log("voxels", occ.shape, occ.mean().round(4))
    ao = ao_bake(pos, nrm, cov, occ, lo, vs)
    log("ao mean", ao[cov].mean().round(3))
    posf, nrmf = fill(pos, cov), fill(nrm, cov)
    aof = np.clip(gaussian_filter(fill(ao, cov), 2.0), 0.5, 1.0)      # (blind review: AO holes read as dirty smears)
    # ---- tone at 1K: the FG skin's own two-tone areas (dark islands) give the dark upper regions; underside lighter
    src = np.asarray(Image.open(DIR / "tex_f16.png").convert("RGB"), np.float32) / 255.0
    lum = src @ np.array([0.299, 0.587, 0.114], np.float32)
    lum1k = zoom(gaussian_filter(lum, 3.0), R / lum.shape[0], order=1)
    dark = np.clip((0.70 - lum1k) / 0.16, 0, 1)                        # 189 -> 0, 123 -> 1
    P = posf.reshape(-1, 3); Nn = nrmf.reshape(-1, 3)
    warp = (noise3(P, 90.0) - 0.5).reshape(R, R)
    dark = np.clip(gaussian_filter(dark, 6.0) + warp * 0.6, 0, 1)
    dark = dark * dark * (3 - 2 * dark)                                 # soft boundary
    under = np.clip((-Nn[:, 2] - 0.2) / 0.5, 0, 1).reshape(R, R)
    dark = dark * np.clip((Nn[:, 2].reshape(R, R) + 0.15) / 0.3, 0, 1)     # two-tone dark only on upper surfaces (mirrored UVs)
    col = LIGHT[None, None] * (1 - under[..., None]) + UNDER[None, None] * under[..., None]
    col = col * (1 - dark[..., None]) + DARK[None, None] * dark[..., None]
    # streaks along the airflow (long in x, narrow in y / z), soot behind the nozzle area and the gun port
    Pst = P * np.array([0.08, 1.0, 1.0])
    streak = np.zeros((R, R))                              # (round 4: noise streaks removed - see flow_streaks)
    x = posf[..., 0]
    soot = np.clip((-x - 430.0) / 140.0, 0, 1) ** 1.5 * (0.55 + 0.45 * np.clip(-nrmf[..., 2] + 0.3, 0, 1))
    g = posf - GUN
    gun = np.exp(-((np.clip(-g[..., 0], 0, None) / 90.0) ** 2 + (g[..., 1] / 14.0) ** 2 + (g[..., 2] / 14.0) ** 2)) * (g[..., 0] < 8)
    soot = np.clip(soot + gun * 0.9, 0, 1)
    sootc = np.array([0.012, 0.011, 0.010])
    fl = flow_streaks(posf, cov, lum1k_lines(R))
    col = col * (1 - 0.4 * fl[..., None])                  # ~40-50 % contrast fluid / soot streaks running aft of panel lines
    nose = np.clip((posf[..., 0] - 690.0) / 40.0, 0, 1)    # radome lighter grey
    col = col * (1 - nose[..., None]) + RADOME * nose[..., None]
    col = col * (1 - soot[..., None] * 0.65) + sootc * soot[..., None] * 0.65
    rough1k = 0.5 + fl * 0.08 + soot * 0.15
    # ---- 4K: upsample tone / AO, crisp panel lines + rivets from the FG line art
    col4, ao4, rough4 = up(col), up(aof), up(rough1k)
    hp = lum - gaussian_filter(lum, 2.5)
    line2 = np.clip(-hp * 10.0, 0, 1)                                   # dark art lines
    seam2 = np.clip(hp * 6.0, 0, 1) * (lum < 0.98)                      # light seam lines (weaker)
    bg2 = src.min(-1) > 0.985
    line2[binary_dilation(bg2, iterations=6)] = 0; seam2[binary_dilation(bg2, iterations=6)] = 0
    line4 = np.clip((up(line2, order=3) - 0.18) / 0.35, 0, 1)            # sharpened: ~2 px crisp lines
    seam4 = np.clip((up(seam2, order=3) - 0.2) / 0.4, 0, 1) * 0.5
    ln = np.maximum(line4, seam4)
    band = binary_dilation(ln > 0.5, iterations=5) & ~binary_dilation(ln > 0.5, iterations=3)
    yy, xx = np.mgrid[0:OUT, 0:OUT]
    dots = ((np.sin(xx * np.pi / 5.0) ** 2) * (np.sin(yy * np.pi / 5.0) ** 2)) > 0.85
    rivet = gaussian_filter((band & dots).astype(np.float32), 0.7) * 2.0
    rivet = np.clip(rivet, 0, 1) * 0.6
    # only the painted skin gets the new paint; tyres, wheel hubs, engine faces, intake / exhaust art keep the FG
    # colours (from tex_f16_paint.png: tyre lettering removed) - paint = the skin's two greys (+ its line art, closed)
    near = lambda c: np.abs(src * 255 - np.array(c)).max(-1) < 14                       # noqa: E731
    pm = near((189, 190, 195)) | near((123, 127, 137)) | bg2
    pm = binary_dilation(pm, iterations=3)
    pm = ~binary_dilation(~pm, iterations=3)
    pm4 = np.clip(up(gaussian_filter(pm.astype(np.float32), 1.0), order=1), 0, 1)[..., None]
    orig = np.asarray(Image.open(DIR / "tex_f16_paint.png").convert("RGB"), np.float32) / 255.0
    orig4 = np.clip(up(orig ** 2.2, order=1), 0, 1)
    paint = col4 * (1 - 0.28 * ln[..., None]) * (1 - 0.08 * rivet[..., None])
    base = (paint * pm4 + orig4 * (1 - pm4)) * (0.85 + 0.15 * ao4[..., None])
    ln = ln * pm4[..., 0]; rivet = rivet * pm4[..., 0]
    rough4 = rough4.copy()
    decals(base, rough4, ln, z, names, posf, nrmf, cov)
    Image.fromarray(np.clip(base ** (1 / 2.2) * 255 + 0.5, 0, 255).astype(np.uint8)).save(DIR / "tex_af2_base.png")
    # normal: lines recessed, rivets domed
    h = gaussian_filter(-ln * 1.0 + rivet * 0.6, 1.0)
    gy, gx = np.gradient(h)
    k = 2.5
    n3 = np.stack([-gx * k, gy * k, np.ones_like(h)], -1)
    n3[..., 1] = -n3[..., 1]                                            # DirectX green (UE)
    n3 /= np.linalg.norm(n3, axis=2, keepdims=True)
    Image.fromarray(np.clip((n3 * 0.5 + 0.5) * 255 + 0.5, 0, 255).astype(np.uint8)).save(DIR / "tex_af2_n.png")
    orm = np.stack([ao4, np.clip(rough4 + ln * 0.1, 0, 1), np.zeros_like(ao4)], -1)
    Image.fromarray(np.clip(orm * 255 + 0.5, 0, 255).astype(np.uint8)).save(DIR / "tex_af2_orm.png")
    # small preview for the page / checks
    Image.fromarray(np.clip(base ** (1 / 2.2) * 255, 0, 255).astype(np.uint8)).resize((1024, 1024), Image.LANCZOS).save(DIR / "preview_af2_base.png")
    Image.fromarray((np.clip(aof, 0, 1) * 255).astype(np.uint8)).save(DIR / "preview_af2_ao.png")
    nozzle_bake(z, names)
    log("done in %.0f s" % (time.time() - t0))


if __name__ == "__main__":
    main()
