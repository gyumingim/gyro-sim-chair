"""Cockpit v2 texture atlas (system Python + PIL + numpy; no Blender).
  python Scripts/cockpit_blender/ck2_textures.py [--out C:/GyroSimTiles/assets/cockpit/tex]
Writes:
  T_Ck2Atlas.png   RGBA 4096: sRGB paint + white legends + dial faces + key legends; A = backlight mask (edge-lit legends)
  T_Ck2Normal.png  RGB 4096 (DirectX / Unreal convention): plate edge chamfers, screw heads, engraved legends, grille slots
  T_Ck2Height.png  height (debug), atlas.json (plate pixel rectangles, made time, inputs)
Everything is drawn here from ck2_layout (generic legends, no logos / manufacturer marks).
"""
import json
import math
import os
import sys
import time

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import ck2_layout as L          # noqa: E402

sys.path.insert(0, os.path.join(HERE, "..", "..", "Content", "Python"))
import cockpit_gauges as G      # noqa: E402   (needle scales shared with the sim)

ARGS = sys.argv[1:]
OUT = ARGS[ARGS.index("--out") + 1] if "--out" in ARGS else r"C:\GyroSimTiles\assets\cockpit\tex"
os.makedirs(OUT, exist_ok=True)
FD = r"C:\Windows\Fonts"
_fc = {}


def font(px, kind="narrow"):
    f = {"narrow": "ARIALNB.TTF", "bold": "arialbd.ttf", "mono": "consola.ttf", "reg": "arial.ttf"}[kind]
    k = (f, int(px))
    if k not in _fc:
        _fc[k] = ImageFont.truetype(os.path.join(FD, f), max(4, int(px)))
    return _fc[k]


S = L.ATLAS
alb = Image.new("RGB", (S, S), (40, 40, 40))
blm = Image.new("L", (S, S), 0)             # backlight mask
hgt = Image.new("L", (S, S), 128)           # height (128 = plate surface)
dA, dB, dH = ImageDraw.Draw(alb), ImageDraw.Draw(blm), ImageDraw.Draw(hgt)
rng = np.random.default_rng(7)


class PlateCanvas:
    """plate cm -> atlas px helpers"""

    def __init__(self, p):
        self.p = p
        self.x0, self.y0, self.w, self.h = p["px"]
        self.k = p["ppc"]

    def pt(self, a, b):
        return (self.x0 + a * self.k, self.y0 + (self.p["h"] - b) * self.k)

    def r(self, cm):
        return cm * self.k

    def text(self, a, b, txt, size_cm, col=L.COL["legend"], kind="narrow", lit=True, engrave=True, anchor="mm"):
        lines = txt.replace("\n", "|").split("|")
        px = max(5, self.r(size_cm) * 1.35)
        f = font(px, kind)
        x, y = self.pt(a, b)
        n = len(lines)
        for i, ln in enumerate(lines):
            yy = y + (i - (n - 1) / 2.0) * px * 0.95
            dA.text((x, yy), ln, fill=col, font=f, anchor=anchor)
            if lit:
                dB.text((x, yy), ln, fill=255, font=f, anchor=anchor)
            if engrave:
                dH.text((x, yy), ln, fill=120, font=f, anchor=anchor)

    def circle(self, a, b, rad_cm, fill=None, outline=None, width=1, img=None, h=None):
        x, y = self.pt(a, b)
        r = self.r(rad_cm)
        (img or dA).ellipse((x - r, y - r, x + r, y + r), fill=fill, outline=outline, width=width)
        if h is not None:
            dH.ellipse((x - r, y - r, x + r, y + r), fill=h)

    def rect(self, a0, b0, a1, b1, fill=None, outline=None, width=1, h=None, lit=None):
        x0, y1 = self.pt(a0, b0)
        x1, y0 = self.pt(a1, b1)
        box = (min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1))
        dA.rectangle(box, fill=fill, outline=outline, width=width)
        if h is not None:
            dH.rectangle(box, fill=h)
        if lit is not None:
            dB.rectangle(box, fill=lit)


def screw(c, a, b, d=0.55):
    """Phillips-style flush screw: dark ring, mid grey head, cross slot, domed height"""
    x, y = c.pt(a, b)
    r = c.r(d / 2)
    dA.ellipse((x - r - 1, y - r - 1, x + r + 1, y + r + 1), fill=(20, 20, 21))
    dA.ellipse((x - r, y - r, x + r, y + r), fill=(70, 72, 74))
    for k in range(int(r), 0, -1):
        dH.ellipse((x - k, y - k, x + k, y + k), fill=int(128 + 22 * math.sqrt(max(0.0, 1 - (k / r) ** 2))))
    w = max(1, int(r * 0.22))
    for ang in (0.6, 0.6 + math.pi / 2):
        dx, dy = math.cos(ang) * r * 0.75, math.sin(ang) * r * 0.75
        dA.line((x - dx, y - dy, x + dx, y + dy), fill=(25, 25, 26), width=w)
        dH.line((x - dx, y - dy, x + dx, y + dy), fill=110, width=w)


def ticks(c, a, b, r0, r1, a_from, a_to, n, width=2, col=(235, 235, 230)):
    x, y = c.pt(a, b)
    for i in range(n):
        t = math.radians(a_from + (a_to - a_from) * i / max(1, n - 1))
        dA.line((x + math.sin(t) * c.r(r0), y - math.cos(t) * c.r(r0), x + math.sin(t) * c.r(r1), y - math.cos(t) * c.r(r1)), fill=col, width=width)


def num_at(c, a, b, rad, ang, txt, size, col=(235, 235, 230)):
    t = math.radians(ang)
    x, y = c.pt(a, b)
    f = font(c.r(size) * 1.3, "bold")
    dA.text((x + math.sin(t) * c.r(rad), y - math.cos(t) * c.r(rad)), txt, fill=col, font=f, anchor="mm")


def needle(c, a, b, ang, length, col=(240, 240, 235), width=0.16):
    x, y = c.pt(a, b)
    t = math.radians(ang)
    dA.line((x - math.sin(t) * c.r(length * 0.2), y + math.cos(t) * c.r(length * 0.2), x + math.sin(t) * c.r(length), y - math.cos(t) * c.r(length)),
            fill=col, width=max(2, int(c.r(width))))
    c.circle(a, b, width * 1.6, fill=(30, 30, 30))


def dial(c, a, b, d, face):
    """instrument face (black, white scale). Sim-driven faces (asi / alt / vvi) follow cockpit_gauges exactly; others get a
    static needle."""
    R = d / 2.0
    c.circle(a, b, R + 0.25, fill=(10, 10, 10), h=118)      # recess ring
    c.circle(a, b, R, fill=L.COL["dial"])
    W = (236, 236, 230)
    lw = max(2, int(c.r(0.05)))
    if face == "asi":
        for kt in range(0, 801, 50):
            ang = G.asi_deg(kt)
            ticks(c, a, b, R * (0.80 if kt % 100 else 0.72), R * 0.93, ang, ang, 1, lw)
            if kt % 100 == 0:
                num_at(c, a, b, R * 0.56, ang, str(kt // 100), R * 0.17)
        c.text(a, b + R * 0.32, "KNOTS", R * 0.08, col=W, kind="bold", engrave=False)
        c.text(a, b - R * 0.32, "x100", R * 0.08, col=W, kind="bold", engrave=False)
    elif face == "alt":
        for i in range(50):
            ang = i * 7.2
            ticks(c, a, b, R * (0.72 if i % 5 == 0 else 0.82), R * 0.93, ang, ang, 1, lw)
        for i in range(10):
            num_at(c, a, b, R * 0.58, i * 36.0, str(i), R * 0.19)
        c.text(a, b + R * 0.3, "ALT", R * 0.1, col=W, kind="bold", engrave=False)
        c.rect(a - R * 0.42, b - R * 0.42, a + R * 0.42, b - R * 0.18, fill=(5, 5, 5))
        c.text(a, b - R * 0.30, "1 2 5 0 0", R * 0.1, col=W, kind="mono", engrave=False)
    elif face == "vvi":
        for v in (-6000, -4000, -2000, -1000, -500, 0, 500, 1000, 2000, 4000, 6000):
            ang = G.vsi_deg(v)
            ticks(c, a, b, R * 0.72, R * 0.93, ang, ang, 1, lw)
            if abs(v) in (0, 1000, 2000, 6000):
                num_at(c, a, b, R * 0.5, ang, str(abs(v) // 1000), R * 0.2)
        c.text(a + R * 0.2, b + R * 0.35, "UP", R * 0.1, col=W, engrave=False)
        c.text(a + R * 0.2, b - R * 0.35, "DN", R * 0.1, col=W, engrave=False)
    elif face == "adi":
        for ang in (-60, -30, -20, -10, 0, 10, 20, 30, 60):
            ticks(c, a, b, R * 0.84, R * 0.97, ang, ang, 1, lw * 2 if ang in (0, 30, -30) else lw)
        c.circle(a, b, R * 0.80, fill=(6, 6, 6), h=100)      # ball opening (the sim's ball sits behind)
    elif face == "hsi":
        for i in range(72):
            ang = i * 5.0
            ticks(c, a, b, R * (0.70 if i % 2 == 0 else 0.78), R * 0.86, ang, ang, 1, lw)
        for i, t in enumerate(("N", "3", "6", "E", "12", "15", "S", "21", "24", "W", "30", "33")):
            num_at(c, a, b, R * 0.56, i * 30.0, t, R * 0.13)
        needle(c, a, b, 20.0, R * 0.55, col=(240, 200, 30), width=0.14)
        c.rect(a - R * 0.62, b + R * 0.72, a - R * 0.22, b + R * 0.92, fill=(4, 4, 4))
        c.text(a - R * 0.42, b + R * 0.82, "012", R * 0.08, col=W, kind="mono", engrave=False)
        c.rect(a + R * 0.22, b + R * 0.72, a + R * 0.62, b + R * 0.92, fill=(4, 4, 4))
        c.text(a + R * 0.42, b + R * 0.82, "337", R * 0.08, col=W, kind="mono", engrave=False)
    else:
        spec = {"rpm": (0, 110, 11, 70.0), "ftit": (2, 12, 11, 60.0), "noz": (0, 100, 6, 10.0), "oil": (0, 100, 6, 40.0), "fuel": (0, 4, 5, 2.6),
                "hyd": (0, 40, 5, 30.0), "oxy": (0, 5, 6, 3.0), "epu": (0, 100, 6, 95.0), "clock": (0, 12, 13, 4.3), "compass": (0, 33, 12, 12.0)}.get(face)
        lo, hi, n, val = spec
        span = 300.0 if face not in ("clock", "compass") else 360.0
        a0 = -150.0 if span < 360 else 0.0
        for i in range(n if span < 360 else n - 1):
            ang = a0 + span * i / (n - 1)
            ticks(c, a, b, R * 0.70, R * 0.92, ang, ang, 1, lw)
            lab = lo + (hi - lo) * i / (n - 1)
            if face == "clock":
                lab = 12 if i == 0 else i
            num_at(c, a, b, R * 0.50, ang, "%d" % round(lab), R * 0.17)
        c.text(a, b - R * 0.32, {"rpm": "RPM %", "ftit": "FTIT", "noz": "NOZ POS", "oil": "OIL", "fuel": "FUEL", "hyd": "HYD", "oxy": "LIQUID OXY",
                                 "epu": "EPU", "clock": "", "compass": ""}[face], R * 0.1, col=W, kind="bold", engrave=False)
        needle(c, a, b, a0 + span * (val - lo) / (hi - lo), R * 0.82, width=max(0.08, R * 0.05))
        if face == "clock":
            needle(c, a, b, 300.0, R * 0.55, width=max(0.08, R * 0.06))
    c.circle(a, b, d * 0.05, fill=(20, 20, 20))


def tape(c, a, b, w, h, label):
    c.rect(a - w / 2 - 0.2, b - h / 2 - 0.2, a + w / 2 + 0.2, b + h / 2 + 0.2, fill=(12, 12, 12), h=116)
    c.rect(a - w / 4, b - h / 2, a + w / 4, b + h / 2, fill=(30, 30, 30))
    for i in range(-3, 4):
        yy = b + i * h / 7.0
        c.rect(a - w / 4, yy - 0.04, a, yy + 0.04, fill=(230, 230, 225))
        c.text(a + w * 0.12, yy, "%d" % (15 + i * 5), 0.32, kind="bold", lit=False, engrave=False)
    c.rect(a - w / 2, b - 0.06, a + w / 2, b + 0.06, fill=(240, 120, 20))
    c.text(a, b - h / 2 - 0.55, label, 0.4)


def lamp(c, a, b, w, h, colr, txt):
    base = {"amber": (70, 46, 8), "red": (70, 12, 10), "green": (14, 50, 22)}[colr]
    leg = {"amber": (150, 105, 30), "red": (150, 45, 40), "green": (60, 130, 70)}[colr]
    c.rect(a - w / 2 - 0.15, b - h / 2 - 0.15, a + w / 2 + 0.15, b + h / 2 + 0.15, fill=(8, 8, 8), h=118)
    c.rect(a - w / 2, b - h / 2, a + w / 2, b + h / 2, fill=base)
    if txt:
        c.text(a, b, txt, min(h * 0.22, 0.38), col=leg, kind="bold", lit=False, engrave=False)


def plate_base(c):
    p = c.p
    col = {"well": L.COL["well"], "placard": (18, 18, 18), "icp": (34, 35, 36), "mfd": (32, 33, 34), "pod": (20, 20, 21)}.get(p["kind"], L.COL["panel"])
    c.rect(0, 0, p["w"], p["h"], fill=col)
    # subtle mottling (paint), stronger on wells / structure
    x0, y0, w, h = p["px"]
    n = rng.normal(0, 1, (max(1, h // 16 + 2), max(1, w // 16 + 2))).astype(np.float32)
    big = np.array(Image.fromarray(((n * 20) + 128).clip(0, 255).astype(np.uint8)).resize((w, h), Image.BICUBIC)).astype(np.float32) - 128
    reg = np.array(alb.crop((x0, y0, x0 + w, y0 + h))).astype(np.float32)
    reg *= (1.0 + big[..., None] / 128.0 * 0.07)
    alb.paste(Image.fromarray(reg.clip(0, 255).astype(np.uint8)), (x0, y0))
    # chamfer: height ramps down over 0.3 cm at the plate edge
    e = max(2, int(c.r(0.3)))
    for i in range(e):
        v = int(128 - 40 * (1 - i / e) ** 1.5)
        dH.rectangle((x0 + i, y0 + i, x0 + w - 1 - i, y0 + h - 1 - i), outline=v)
    # painted edge highlight / dark outline
    dA.rectangle((x0, y0, x0 + w - 1, y0 + h - 1), outline=(18, 18, 19), width=max(1, int(c.r(0.06))))
    if p["kind"] in ("console", "panel", "wing", "well"):
        m = 0.55
        for a, b in ((m, m), (p["w"] - m, m), (m, p["h"] - m), (p["w"] - m, p["h"] - m)):
            screw(c, a, b)
        if p["kind"] in ("console", "well") and p["h"] > 14:
            screw(c, m, p["h"] / 2)
            screw(c, p["w"] - m, p["h"] / 2)


def draw_plate(p):
    c = PlateCanvas(p)
    plate_base(c)
    labels = list(L.TOGGLE_LABELS.get(p["name"], []))
    li = 0
    if p.get("title"):
        c.text(p["w"] / 2, p["h"] - 1.0, p["title"], 0.66)
        c.rect(1.4, p["h"] - 1.75, p["w"] - 1.4, p["h"] - 1.69, fill=L.COL["legend"], lit=255)
    for it in p["items"]:
        k = it[0]
        if k == "label":
            c.text(it[1], it[2], it[3], it[4])
        elif k == "toggle":
            a, b = it[1], it[2]
            c.circle(a, b, 0.55, fill=(22, 22, 23), h=140)
            c.circle(a, b, 0.32, fill=(120, 122, 125))
            if p["kind"] not in ("icp", "wing", "panel"):
                c.text(a - 1.2, b + 1.05, "ON", 0.34)
                c.text(a - 1.2, b - 1.05, "OFF", 0.34)
                if li < len(labels) and labels[li]:
                    c.text(a, b + 1.9, labels[li], 0.5)
            li += 1
        elif k == "knob":
            a, b, d = it[1], it[2], it[3]
            ticks(c, a, b, d * 0.62, d * 0.78, -135, 135, 7, max(1, int(c.r(0.06))))
            c.text(a - d * 0.75, b - d * 0.62, "OFF", 0.32)
            name = it[4] if len(it) > 4 else (labels[li] if li < len(labels) else "")
            if name:
                c.text(a, b + d * 0.95, name, 0.48)
            li += 1
        elif k == "button":
            a, b, w, h = it[1], it[2], it[3], it[4]
            txt = it[5] if len(it) > 5 else ""
            c.rect(a - w / 2 - 0.12, b - h / 2 - 0.12, a + w / 2 + 0.12, b + h / 2 + 0.12, fill=(10, 10, 10), h=112)
            c.rect(a - w / 2, b - h / 2, a + w / 2, b + h / 2, fill=(28, 28, 29))     # key top (the raised key maps here)
            if txt:
                c.text(a, b, txt, min(0.34, h * 0.24), kind="bold", engrave=False)
            elif p["kind"] != "mfd" and li < len(labels):
                c.text(a, b + h / 2 + 0.55, labels[li], 0.42)
            li += 1 if p["kind"] == "console" else 0
        elif k == "rocker":
            a, b, w, h, t = it[1], it[2], it[3], it[4], it[5]
            c.rect(a - w / 2, b - h / 2, a + w / 2, b + h / 2, fill=(14, 14, 14), h=112)
            if t:
                c.text(a + (1.4 if a < p["w"] / 2 else -1.4), b, t, 0.28)
        elif k == "wheel_s":
            a, b, d, t = it[1], it[2], it[3], it[4]
            c.rect(a - d / 2, b - 0.35, a + d / 2, b + 0.35, fill=(8, 8, 8), h=110)
            c.text(a, b - 0.75, t, 0.26)
        elif k == "dial":
            dial(c, it[1], it[2], it[3], it[4])
        elif k == "tape":
            tape(c, it[1], it[2], it[3], it[4], it[5])
        elif k == "lamp":
            lamp(c, *it[1:])
        elif k == "grille":
            a0, b0, a1, b1 = it[1:5]
            yy = b0
            while yy < b1:
                c.rect(a0, yy, a1, yy + 0.45, fill=(6, 6, 6), h=70)
                yy += 0.9
        elif k == "display":
            a, b, w, h, lines = it[1:6]
            c.rect(a - w / 2 - 0.3, b - h / 2 - 0.3, a + w / 2 + 0.3, b + h / 2 + 0.3, fill=(6, 7, 6), h=110)
            c.rect(a - w / 2, b - h / 2, a + w / 2, b + h / 2, fill=(2, 6, 3))
            f = font(c.r(h / 5.2), "mono")
            x, y = c.pt(a - w / 2 + 0.3, b + h / 2 - 0.25)
            for i, ln in enumerate(lines):
                dA.text((x, y + i * c.r(h / 4.4)), ln, fill=(70, 255, 110), font=f)
        elif k == "rwr":
            a, b, sz = it[1], it[2], it[3]
            c.rect(a - sz / 2 - 0.3, b - sz / 2 - 0.3, a + sz / 2 + 0.3, b + sz / 2 + 0.3, fill=(8, 8, 8), h=110)
            c.rect(a - sz / 2, b - sz / 2, a + sz / 2, b + sz / 2, fill=(2, 8, 4))
            for rr in (0.15, 0.3, 0.45):
                c.circle(a, b, sz * rr, outline=(40, 160, 70), width=max(1, int(c.r(0.03))))
            ticks(c, a, b, sz * 0.42, sz * 0.47, 0, 330, 12, max(1, int(c.r(0.03))), col=(40, 160, 70))
            for t, ang, rr in (("S", 40, 0.32), ("U", 200, 0.22)):
                num_at(c, a, b, sz * rr, ang, t, sz * 0.06, col=(80, 230, 110))
        elif k == "guard":
            a, b = it[1], it[2]
            c.rect(a - 1.0, b - 1.3, a + 1.0, b + 1.3, fill=(150, 25, 20), h=135)
            for i in range(-3, 4):
                c.rect(a - 1.0, b + i * 0.36 - 0.05, a + 1.0, b + i * 0.36 + 0.05, fill=(110, 18, 15))
        elif k == "stripes":
            a0, b0, a1, b1 = it[1:5]
            c.rect(a0, b0, a1, b1, fill=(220, 175, 20))
            x0, y1 = c.pt(a0, b0)
            x1, y0 = c.pt(a1, b1)
            st = c.r(0.5)
            for i in range(-30, 60):
                yy = y0 + i * st * 2
                dA.polygon([(x0, yy), (x1, yy - (x1 - x0)), (x1, yy - (x1 - x0) + st), (x0, yy + st)], fill=(15, 15, 15))
            dA.rectangle((x1 + 1, y0 - 200, x1 + 200, y1 + 200), fill=None)
        elif k == "wheel":
            a, b = it[1], it[2]
            c.circle(a, b, 1.8, fill=(20, 20, 20), h=118)
            c.text(a + 2.5, b + 1.0, "UP", 0.32)
            c.text(a + 2.5, b - 1.6, "DN", 0.32)
    # restore pixels outside the plate (stripes overdraw): re-crop is not needed, stripes are clipped by drawing order
    return c


t0 = time.time()
plates = L.pack()
# draw plates in packing order; the stripes polygon may spill, so draw each plate then re-paste its own crop
crops = {}
for p in plates:
    draw_plate(p)
    x0, y0, w, h = p["px"]
    crops[p["name"]] = (alb.crop((x0, y0, x0 + w, y0 + h)), (x0, y0))
for p in plates:                                       # spill guard: every plate's pixels from its own pass
    im, pos = crops[p["name"]]
    alb.paste(im, pos)
# swatches: white (flat normal) and hazard stripes (ejection loop)
sx, sy, sw, sh = L.SWATCH
dA.rectangle((sx, sy, sx + sw, sy + sh), fill=(255, 255, 255))
dH.rectangle((sx, sy, sx + sw, sy + sh), fill=128)
sx, sy, sw, sh = L.STRIPE_SW
dA.rectangle((sx, sy, sx + sw - 1, sy + sh - 1), fill=(225, 180, 25))
for i in range(-4, 8):
    x = sx + i * 32
    dA.polygon([(x, sy + sh), (x + 16, sy + sh), (x + 16 + sh, sy), (x + sh, sy)], fill=(14, 14, 14))
dA.rectangle((sx + sw, sy, S, sy + sh), fill=(255, 255, 255))
dA.rectangle((sx - 80, sy, sx - 1, sy + sh), fill=(40, 40, 40))

# knurl (diamond cross-hatch) and rubber grain regions: height only (albedo white, the slot tint colours them)
for (x0, y0, w, h), kind in ((L.KNURL_SW, "knurl"), (L.RUBBER_SW, "rubber")):
    dA.rectangle((x0, y0, x0 + w - 1, y0 + h - 1), fill=(255, 255, 255))
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    if kind == "knurl":
        k = 2 * np.pi * 16 / w
        hh = 0.5 + 0.25 * (np.abs(np.sin(k * (xx + yy) / 2)) + np.abs(np.sin(k * (xx - yy) / 2)))
        hh = 1.0 - hh
    else:
        sm = rng.random((h // 4, w // 4)).astype(np.float32)
        hh = np.array(Image.fromarray((sm * 255).astype(np.uint8)).resize((w, h), Image.BICUBIC)).astype(np.float32) / 255.0
    hgt.paste(Image.fromarray((90 + hh * 76).clip(0, 255).astype(np.uint8)), (x0, y0))

# normal map from height (DirectX convention for Unreal: G = -dh/drow ... green points down the image)
h = np.array(hgt.filter(ImageFilter.GaussianBlur(1.2))).astype(np.float32) / 255.0
gx = np.zeros_like(h)
gy = np.zeros_like(h)
gx[:, 1:-1] = (h[:, 2:] - h[:, :-2]) * 0.5
gy[1:-1, :] = (h[2:, :] - h[:-2, :]) * 0.5
st = 9.0
nx, ny, nz = -gx * st, gy * st, np.ones_like(h)
ln = np.sqrt(nx * nx + ny * ny + nz * nz)
nrm = np.stack([nx / ln, ny / ln, nz / ln], -1)
Image.fromarray(((nrm * 0.5 + 0.5) * 255).clip(0, 255).astype(np.uint8)).save(os.path.join(OUT, "T_Ck2Normal.png"))
rgba = alb.copy()
rgba.putalpha(blm)
rgba.save(os.path.join(OUT, "T_Ck2Atlas.png"))
hgt.save(os.path.join(OUT, "T_Ck2Height.png"))
json.dump(dict(made=time.strftime("%Y-%m-%d %H:%M:%S"), size=S, inputs="Scripts/cockpit_blender/ck2_layout.py + Content/Python/cockpit_gauges.py",
               plates={p["name"]: p["px"] for p in plates}), open(os.path.join(OUT, "atlas.json"), "w"), indent=1)
# tiling grunge (UV1 in the material): multi-octave value noise, wraps
g = np.zeros((1024, 1024), np.float32)
for oc, amp in ((8, 1.0), (16, 0.6), (32, 0.4), (64, 0.25), (128, 0.15), (256, 0.1)):
    small = rng.random((oc, oc)).astype(np.float32)
    big = np.array(Image.fromarray((small * 255).astype(np.uint8)).resize((1024 + 1024 // oc, 1024 + 1024 // oc), Image.BICUBIC)).astype(np.float32)
    g += amp * big[:1024, :1024] / 255.0
g = (g - g.min()) / (g.max() - g.min())
Image.fromarray((g * 255).astype(np.uint8)).save(os.path.join(OUT, "T_Ck2Grunge.png"))
alb.resize((1024, 1024), Image.LANCZOS).save(os.path.join(OUT, "atlas_preview.jpg"), quality=88)
print("[ck2tex] %d plates, %.1f s -> %s" % (len(plates), time.time() - t0, OUT))
