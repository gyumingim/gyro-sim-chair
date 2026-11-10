#!/usr/bin/env python3
"""airframe_tex.py - paint / detail textures for the airframe pass, made from the FlightGear F-16 skin (tex_f16.png in
ThirdParty/f16_airframe, GPL-2.0 -> the outputs are GPL derived files and stay outside git next to it).

  tex_f16_paint.png  the skin with the brand / slogan text on the tyre sidewalls painted out (plain rubber)
  tex_f16_n.png      tangent-space normal map: panel lines and rivet rows as shallow recesses (from the skin's line art)
  tex_f16_m.png      masks: R = panel line / rivet (0..1), G = grime (soft dirt around lines, more on the lower half of
                     each UV island), B = paint roughness variation (low-frequency noise, 0.5 = neutral)
Run: python Scripts/aircraft/airframe_tex.py   (numpy, Pillow, scipy)
"""
from pathlib import Path

import numpy as np
from PIL import Image
from scipy.ndimage import binary_dilation, binary_opening, distance_transform_edt, gaussian_filter

DIR = Path(__file__).resolve().parents[2] / "ThirdParty" / "f16_airframe"
SRC = DIR / "tex_f16.png"


def blur(a, r):
    return gaussian_filter(a.astype(np.float32), r, mode="nearest")


def main():
    im = Image.open(SRC).convert("RGB")
    W, H = im.size
    a = np.asarray(im, np.float32) / 255.0
    s = W / 2048.0
    # --- tyre sidewall text: the tyre picture sits in the lower-left (x 8..267, y 1497..1760 at 2048 px)
    x0, y0, x1, y1 = [int(round(v * s)) for v in (8, 1497, 267, 1760)]
    cx, cy, R = (x0 + x1) / 2, (y0 + y1) / 2, min(x1 - x0, y1 - y0) / 2
    yy, xx = np.mgrid[0:H, 0:W]
    r = np.hypot(xx - cx, yy - cy) / R
    side = (r > 0.62) & (r < 0.99)
    rng = np.random.default_rng(7)
    rubber = np.array([0.075, 0.075, 0.08], np.float32)
    n = rng.normal(0, 0.012, (H, W, 1)).astype(np.float32)
    ring = 0.02 * np.cos(r * 60.0)[..., None]                      # moulded sidewall rings, no lettering
    a = np.where(side[..., None], np.clip(rubber + n + ring, 0, 1), a)
    # white background between the UV islands: some parts (the fin) are mapped onto it, i.e. they are meant to be the
    # plain light paint -> the light grey of the skin (189, 190, 195), not white (no white seams in the mips either)
    bg = (a.min(-1) > 0.985)
    bg = binary_opening(bg, iterations=2)
    a[bg] = np.array([189, 190, 195], np.float32) / 255.0
    Image.fromarray(np.clip(a * 255 + 0.5, 0, 255).astype(np.uint8)).save(DIR / "tex_f16_paint.png", optimize=True)
    near_edge = binary_dilation(bg, iterations=max(2, int(6 * s)))

    # --- panel lines: thin features that differ from their surroundings (dark lines, light seam lines, rivet dots)
    L = (a @ np.array([0.299, 0.587, 0.114], np.float32))
    hp = L - blur(L, 2.5 * s)
    line = np.clip(np.abs(hp) * 9.0, 0, 1)
    line = np.where(hp < 0, line, line * 0.6)                      # dark art lines = recess; light seams weaker
    line[side | near_edge] = 0.0
    # height: recessed lines (soft profile) -> normal map
    h = 1.0 - blur(line, 0.8 * s)
    gx = np.zeros_like(h); gy = np.zeros_like(h)
    gx[:, 1:-1] = (h[:, 2:] - h[:, :-2]) * 0.5
    gy[1:-1, :] = (h[2:, :] - h[:-2, :]) * 0.5
    k = 3.0
    nx, ny, nz = -gx * k, gy * k, np.ones_like(h)                 # +G = up in the image (UE expects DirectX: flip G)
    ny = -ny
    ln = np.sqrt(nx * nx + ny * ny + nz * nz)
    N = np.stack([nx / ln, ny / ln, nz / ln], -1) * 0.5 + 0.5
    Image.fromarray(np.clip(N * 255 + 0.5, 0, 255).astype(np.uint8)).save(DIR / "tex_f16_n.png", optimize=True)

    # --- masks
    grime = np.clip(blur(line, 6 * s) * 2.2, 0, 1)                 # dirt collects around panel edges / fasteners
    low = blur((rng.random((H // 32 + 1, W // 32 + 1)) - 0.5).repeat(32, 0).repeat(32, 1)[:H, :W].astype(np.float32), 24 * s)
    grime = np.clip(grime + np.clip(low * 1.5, 0, 1) * 0.5, 0, 1)
    rough = np.clip(0.5 + blur((rng.random((H // 16 + 1, W // 16 + 1)) - 0.5).repeat(16, 0).repeat(16, 1)[:H, :W].astype(np.float32), 10 * s) * 2.5, 0, 1)
    grime[bg] = 0.0
    M = np.stack([line, grime, rough], -1)
    Image.fromarray(np.clip(M * 255 + 0.5, 0, 255).astype(np.uint8)).save(DIR / "tex_f16_m.png", optimize=True)
    print("line mean %.3f grime mean %.3f rough mean %.3f -> %s" % (line.mean(), grime.mean(), rough.mean(), DIR))


if __name__ == "__main__":
    main()
