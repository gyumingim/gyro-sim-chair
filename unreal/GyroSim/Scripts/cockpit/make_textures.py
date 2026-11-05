"""Generates the cockpit textures (our own, procedural) into unreal/GyroSim/Art/Cockpit/tex/:
  T_CkPanels.png  4096^2 RGBA atlas: panel faces (RGB) + backlit legend mask (A); regions -> atlas.json
  T_CkDials.png   2048^2 RGBA: instrument faces (4 x 4 tiles of 512), markings mask in A
  T_CkADI.png     1024 x 512 ADI ball (equirectangular, front = centre)
  T_CkGrunge.png  1024^2 grey, tiling: roughness variation / smudges / fine scratches
  T_CkFabricN.png 512^2 tiling normal map (seat cushion weave)
Run with CPython 3 + Pillow + numpy:  python make_textures.py
Fonts: Windows Bahnschrift (DIN-like) if present, else Arial Narrow / DejaVu. Only rendered glyph images end up in the
textures (no font files are distributed).
"""
import json, math, os, sys
import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.normpath(os.path.join(HERE, "..", "..", "Content", "Python")))
import layout as L            # noqa: E402
import cockpit_gauges as G    # noqa: E402

OUT = os.path.normpath(os.path.join(HERE, "..", "..", "Art", "Cockpit", "tex"))
os.makedirs(OUT, exist_ok=True)
RNG = np.random.default_rng(7)

# ---- fonts ----------------------------------------------------------------------------------------------------------
_FONT_CACHE = {}


def font(px, weight="SemiBold Condensed"):
    key = (int(px), weight)
    if key in _FONT_CACHE:
        return _FONT_CACHE[key]
    f = None
    for path in ("C:/Windows/Fonts/bahnschrift.ttf",):
        if os.path.exists(path):
            f = ImageFont.truetype(path, max(6, int(px)))
            try:
                f.set_variation_by_name(weight)
            except Exception:
                pass
            break
    if f is None:
        for path in ("C:/Windows/Fonts/ARIALNB.TTF", "/usr/share/fonts/truetype/dejavu/DejaVuSansCondensed-Bold.ttf"):
            if os.path.exists(path):
                f = ImageFont.truetype(path, max(6, int(px)))
                break
    f = f or ImageFont.load_default()
    _FONT_CACHE[key] = f
    return f


# ---- colours (sRGB 0..255) --------------------------------------------------------------------------------------------
PANEL = (36, 37, 39)          # panel face paint (matte black FS 37038, kept above the PBR albedo floor; was (27, 28, 30))
CONSOLE = (96, 102, 100)      # console / wall paint (FS 36231 dark gull grey, realism pass 11-05: was (52, 55, 58))
LEGEND = (226, 228, 222)      # legend paint (white), backlit through the alpha mask
DIALF = (12, 12, 13)


class Canvas:
    """RGB + emissive mask, drawn at `ss` x supersampling then reduced (clean anti-aliased legends)."""
    def __init__(self, w, h, bg, ss=2, tscale=1.0):
        self.ss = ss
        self.tscale = tscale
        self.rgb = Image.new("RGB", (w * ss, h * ss), bg)
        self.msk = Image.new("L", (w * ss, h * ss), 0)
        self.d = ImageDraw.Draw(self.rgb)
        self.m = ImageDraw.Draw(self.msk)

    def S(self, *v):
        return [x * self.ss for x in v]

    def text(self, x, y, s, px, col=LEGEND, glow=True, anchor="mm", weight="SemiBold Condensed"):
        f = font(px * self.ss * self.tscale, weight)
        self.d.text((x * self.ss, y * self.ss), s, font=f, fill=col, anchor=anchor)
        if glow:
            self.m.text((x * self.ss, y * self.ss), s, font=f, fill=255, anchor=anchor)

    def line(self, pts, w, col=LEGEND, glow=True):
        p = [(a * self.ss, b * self.ss) for a, b in pts]
        self.d.line(p, fill=col, width=max(1, int(w * self.ss)))
        if glow:
            self.m.line(p, fill=255, width=max(1, int(w * self.ss)))

    def rect(self, x0, y0, x1, y1, fill=None, outline=None, w=1, glow=False, radius=0):
        b = self.S(x0, y0, x1, y1)
        self.d.rounded_rectangle(b, radius=radius * self.ss, fill=fill, outline=outline, width=max(1, int(w * self.ss)))
        if glow and outline:
            self.m.rounded_rectangle(b, radius=radius * self.ss, outline=255, width=max(1, int(w * self.ss)))

    def circle(self, x, y, r, fill=None, outline=None, w=1, glow=False):
        b = self.S(x - r, y - r, x + r, y + r)
        self.d.ellipse(b, fill=fill, outline=outline, width=max(1, int(w * self.ss)))
        if glow and outline:
            self.m.ellipse(b, outline=255, width=max(1, int(w * self.ss)))
        if glow and fill and not outline:
            self.m.ellipse(b, fill=255)

    def done(self):
        w, h = self.rgb.size[0] // self.ss, self.rgb.size[1] // self.ss
        return self.rgb.resize((w, h), Image.LANCZOS), self.msk.resize((w, h), Image.LANCZOS)


def noise(w, h, scale, amp, seed=0):
    """smooth value noise in [-amp, amp]."""
    r = np.random.default_rng(seed)
    gw, gh = max(2, int(w / scale) + 2), max(2, int(h / scale) + 2)
    g = Image.fromarray((r.random((gh, gw)) * 255).astype(np.uint8)).resize((w, h), Image.BICUBIC)
    return (np.asarray(g, np.float32) / 255.0 - 0.5) * 2 * amp


def paint_base(w, h, col, seed):
    a = np.zeros((h, w, 3), np.float32) + np.array(col, np.float32)
    n = noise(w, h, 140, 1.4, seed) + noise(w, h, 9, 0.8, seed + 1) + (RNG.random((h, w)) - 0.5) * 1.6
    return Image.fromarray(np.clip(a + n[..., None], 0, 255).astype(np.uint8))


def dzus(c, x, y, r):
    """quarter-turn fastener: dark ring, lighter head, slot."""
    c.circle(x, y, r, fill=(14, 14, 15))
    c.circle(x, y, r * 0.78, fill=(70, 72, 74))
    a = math.radians(35)
    c.line([(x - r * 0.62 * math.cos(a), y - r * 0.62 * math.sin(a)), (x + r * 0.62 * math.cos(a), y + r * 0.62 * math.sin(a))], max(1, r * 0.22),
           col=(20, 20, 21), glow=False)


# =====================================================================================================================
# panel atlas
class Packer:
    def __init__(self, size):
        self.size, self.x, self.y, self.row = size, 0, 0, 0
        self.pad = 6

    def add(self, w, h):
        if self.x + w + self.pad > self.size:
            self.x, self.y, self.row = 0, self.y + self.row + self.pad, 0
        if self.y + h > self.size:
            raise RuntimeError("atlas full")
        r = (self.x, self.y, w, h)
        self.x += w + self.pad
        self.row = max(self.row, h)
        return r


def draw_toggle_marks(c, x, y, px, opts):
    pos = opts.get("pos", ("ON", "", "OFF"))
    if pos[0]:
        c.text(x, y - 1.25 * px, pos[0], 0.30 * px)
    if len(pos) > 1 and pos[1]:
        c.text(x + 1.05 * px, y, pos[1], 0.26 * px, anchor="lm")
    if len(pos) > 2 and pos[2]:
        c.text(x, y + 1.25 * px, pos[2], 0.30 * px)


def draw_knob_marks(c, x, y, px, opts, r=1.25):
    ticks = opts.get("ticks")
    if ticks:
        n = len(ticks)
        for i, t in enumerate(ticks):
            a = math.radians(-135 + 270 * i / max(1, n - 1))
            sx, sy = math.sin(a), -math.cos(a)
            c.line([(x + sx * r * px, y + sy * r * px), (x + sx * (r + 0.28) * px, y + sy * (r + 0.28) * px)], 0.08 * px)
            if t:
                c.text(x + sx * (r + 0.75) * px, y + sy * (r + 0.62) * px, t, 0.24 * px)
    else:
        for i in range(11):
            a = math.radians(-135 + 27 * i)
            sx, sy = math.sin(a), -math.cos(a)
            l = 0.32 if i % 5 == 0 else 0.18
            c.line([(x + sx * r * px, y + sy * r * px), (x + sx * (r + l) * px, y + sy * (r + l) * px)], 0.07 * px)
        c.text(x - 1.0 * px, y + 1.25 * px, "OFF", 0.22 * px)
        c.text(x + 1.05 * px, y + 1.25 * px, "BRT", 0.22 * px)


def draw_element(c, kind, x, y, label, opts, px):
    """x, y in pixels inside the canvas; px = pixels per cm."""
    small = opts.get("small")
    if kind in ("toggle", "guard"):
        c.circle(x, y, 0.62 * px, fill=(16, 16, 17))
        draw_toggle_marks(c, x, y, px, opts)
        c.text(x, y - 2.05 * px, label, 0.34 * px)
    elif kind == "knob":
        r = 0.85 if small else 1.25
        if not small:
            draw_knob_marks(c, x, y, px, opts, r)
        c.text(x, y - (r + 1.0) * px, label, 0.34 * px)
    elif kind == "button":
        if opts.get("ring") == "stripe":
            for k in range(16):
                a0 = k * 22.5
                c.d.pieslice(c.S(x - 1.0 * px, y - 1.0 * px, x + 1.0 * px, y + 1.0 * px), a0, a0 + 11.25, fill=(214, 170, 30))
        c.circle(x, y, 0.62 * px, fill=(16, 16, 17))
        c.text(x, y - 1.55 * px, label, 0.32 * px)
    elif kind == "light":
        c.text(x, y - 1.3 * px, label, 0.32 * px)
    elif kind == "display":
        w, h = opts.get("w", 6) * px, opts.get("h", 2) * px
        c.rect(x - w / 2 - 0.2 * px, y - h / 2 - 0.2 * px, x + w / 2 + 0.2 * px, y + h / 2 + 0.2 * px, fill=(10, 10, 10))
        c.rect(x - w / 2, y - h / 2, x + w / 2, y + h / 2, fill=(8, 22, 12))
        c.text(x, y, label, 0.95 * h / px * px * 0.55, col=(120, 255, 150))
        c.text(x, y - h / 2 - 0.45 * px, "DISPLAY", 0.26 * px)
    elif kind == "gauge":
        c.text(x, y - (opts.get("d", 4) / 2 + 0.55) * px, label, 0.30 * px)


def console_panel(name, u0, u1, v0, v1, title, elems, px=L.PX_CONSOLE):
    w, h = int(round((u1 - u0) * px)), int(round((v1 - v0) * px))
    c = Canvas(w, h, PANEL, tscale=1.45)
    c.rgb.paste(paint_base(w * c.ss, h * c.ss, PANEL, sum(map(ord, name))))
    X = lambda u: (u - u0) * px
    Y = lambda v: (v1 - v) * px
    # edge highlight + fasteners
    c.rect(1, 1, w - 2, h - 2, outline=(45, 46, 49), w=1.5)
    for fx, fy in ((0.55, 0.55), (w / px - 0.55, 0.55), (0.55, h / px - 0.55), (w / px - 0.55, h / px - 0.55)):
        dzus(c, fx * px, fy * px, 0.33 * px)
    # title bar (backlit) at the forward edge
    if title:                       # (an empty title used to leave a lone backlit line = the "white line" on the consoles)
        c.text(w / 2, 0.75 * px, title, 0.44 * px)
        c.line([(1.3 * px, 1.3 * px), (w - 1.3 * px, 1.3 * px)], 0.06 * px)
    for kind, u, v, label, opts in elems:
        draw_element(c, kind, X(u), Y(v), label, opts, px)
    if not elems:
        ghost_detail(c, w, h, px, sum(map(ord, name)))
    return c.done()


def ghost_detail(c, w, h, px, seed):
    """faint, NON-readable detail for empty panels (user decision 11-05: no fake switches): sub-panel seams with
    fasteners, illegible placard blocks (word-shaped bars, no letters), blanking plugs. Low contrast, never backlit."""
    r = np.random.default_rng(seed)
    dark, lite, ink = (13, 13, 14), (40, 41, 44), (46, 47, 50)
    # split into 1-3 sub-panels along the long side
    n = 1 + int(r.integers(0, 3)) if h > 10 * px else 1
    cuts = sorted(r.uniform(0.3, 0.7, n - 1)) if n > 1 else []
    edges = [0.0] + [k * h for k in cuts] + [float(h)]
    for k in range(len(edges) - 1):
        y0, y1 = edges[k] + 0.35 * px, edges[k + 1] - 0.35 * px
        x0, x1 = 0.9 * px, w - 0.9 * px
        if y1 - y0 < 3 * px:
            continue
        c.rect(x0, y0, x1, y1, outline=dark, w=0.1 * px)
        c.rect(x0 + 0.1 * px, y0 + 0.1 * px, x1 - 0.1 * px, y1 - 0.1 * px, outline=lite, w=0.05 * px)
        for fx, fy in ((x0 + 0.5 * px, y0 + 0.5 * px), (x1 - 0.5 * px, y0 + 0.5 * px), (x0 + 0.5 * px, y1 - 0.5 * px), (x1 - 0.5 * px, y1 - 0.5 * px)):
            dzus(c, fx, fy, 0.26 * px)
        # placard: a few rows of word-shaped bars (looks like small print from a distance, nothing to read)
        if r.random() < 0.8:
            pw = min(x1 - x0 - 1.6 * px, (4.0 + r.random() * 4.0) * px)
            px0 = x0 + 0.8 * px + r.random() * max(0.0, x1 - x0 - 1.6 * px - pw)
            py0 = y0 + 1.0 * px + r.random() * max(0.0, (y1 - y0) - 4.0 * px)
            rows = 2 + int(r.integers(0, 4))
            for j in range(rows):
                xx = px0
                yy = py0 + j * 0.55 * px
                while xx < px0 + pw * (0.6 + 0.4 * r.random()):
                    wl = (0.25 + r.random() * 0.9) * px
                    c.rect(xx, yy, min(xx + wl, px0 + pw), yy + 0.2 * px, fill=ink, radius=0.05 * px)
                    xx += wl + 0.18 * px
        # blanking plugs / unused holes
        for _ in range(int(r.integers(0, 3))):
            bx, by = r.uniform(x0 + 1.5 * px, x1 - 1.5 * px), r.uniform(y0 + 1.5 * px, y1 - 1.5 * px)
            c.circle(bx, by, 0.45 * px, fill=(18, 18, 19), outline=lite, w=0.05 * px)


def thr_housing(px=L.PX_CONSOLE):
    T = L.THR_HOUSING
    u0, u1, v0, v1 = T["u0"], T["u1"], T["v0"], T["v1"]
    w, h = int(round((u1 - u0) * px)), int(round((v1 - v0) * px))
    c = Canvas(w, h, PANEL, tscale=1.3)
    c.rgb.paste(paint_base(w * c.ss, h * c.ss, PANEL, 31))
    X = lambda u: (u - u0) * px
    Y = lambda v: (v1 - v) * px
    xs = X(L.THR_PIVOT[1])
    # slot (dark, the lever runs in it) and the detent scale beside it (inboard = +u side)
    c.rect(xs - 0.9 * px, Y(L.THR_PIVOT[0] + 13.0), xs + 0.9 * px, Y(L.THR_PIVOT[0] - 13.0), fill=(6, 6, 6), radius=0.9 * px)
    for frac, lab in ((0.0, "OFF"), (0.08, "IDLE"), (0.78, "MIL"), (1.0, "AB")):
        a = math.radians(-L.THR_SWING + 2 * L.THR_SWING * frac)
        v = L.THR_PIVOT[0] + 4.9 * math.tan(a) * 2.2
        yy = Y(v)
        c.line([(xs + 1.3 * px, yy), (xs + 2.3 * px, yy)], 0.08 * px)
        c.text(xs + 2.6 * px, yy, lab, 0.36 * px, anchor="lm")
    c.text(xs - 2.9 * px, Y(L.THR_PIVOT[0]), "THROTTLE", 0.38 * px)
    for fx, fy in ((0.5, 0.5), (w / px - 0.5, 0.5), (0.5, h / px - 0.5), (w / px - 0.5, h / px - 0.5)):
        dzus(c, fx * px, fy * px, 0.3 * px)
    return c.done()


def main_panel(px=L.PX_MAIN):
    u0, u1, v0, v1 = L.MAIN_U0, L.MAIN_U1, L.MAIN_V0, L.MAIN_V1
    w, h = int((u1 - u0) * px), int((v1 - v0) * px)
    c = Canvas(w, h, PANEL, tscale=1.45)
    c.rgb.paste(paint_base(w * c.ss, h * c.ss, PANEL, 5))
    X = lambda u: (u - u0) * px
    Y = lambda v: (v1 - v) * px
    # sub-panel seams + fasteners
    subs = [(-25.0, -12.0, 12.5, 37.5), (12.0, 25.0, 12.5, 37.5), (-12.0, 12.0, 12.5, 25.4), (-46.0, -32.0, 39.5, 53.0)]
    for a, b, cc, d in subs:
        c.rect(X(a), Y(d), X(b), Y(cc), outline=(12, 12, 13), w=0.12 * px)
        c.rect(X(a) + 0.12 * px, Y(d) + 0.12 * px, X(b) - 0.12 * px, Y(cc) - 0.12 * px, outline=(44, 45, 48), w=0.06 * px)
        for fx, fy in ((a + 0.6, cc + 0.6), (b - 0.6, cc + 0.6), (a + 0.6, d - 0.6), (b - 0.6, d - 0.6)):
            dzus(c, X(fx), Y(fy), 0.3 * px)
    # instrument legends
    lab = {"ADI": "STBY ATT", "ASI": "AIRSPEED", "ALT": "ALTITUDE", "VSI": "VERT VEL", "CLOCK": "CLOCK", "RPM": "RPM", "FTIT": "FTIT", "FUEL": "FUEL"}
    for n, (u, v, d, dial) in L.GAUGES.items():
        if n in ("ADI",):
            continue
        c.text(X(u), Y(v - d / 2 - 0.5), lab.get(n, n), 0.36 * px)
    for kind, u, v, label, opts in L.MAIN_ELEMENTS:
        draw_element(c, kind, X(u), Y(v), label, opts, px)
    # gear handle placard + lights legend
    g = L.GEAR_HANDLE
    c.text(X(g["u"]), Y(g["v"] + 4.3), "LG", 0.5 * px)
    c.text(X(g["u"] - 3.5), Y(g["v"] + 2.0), "UP", 0.36 * px)
    c.text(X(g["u"] - 3.5), Y(g["v"] - 2.0), "DN", 0.36 * px)
    c.text(X(-19.0), Y(36.3), "WHEELS", 0.36 * px)
    # stripes around the gear handle well (white / red, like real gear handles' bezel)
    c.rect(X(g["u"] - 1.3), Y(g["v"] + 2.6), X(g["u"] + 1.3), Y(g["v"] - 2.6), fill=(10, 10, 10), radius=0.5 * px)
    return c.done()


def ufcp(px=L.PX_SMALL):
    U = L.UFCP
    w, h = int(U["w"] * px), int(U["h"] * px)
    c = Canvas(w, h, PANEL)
    c.rgb.paste(paint_base(w * c.ss, h * c.ss, PANEL, 77))
    cx = w / 2
    # two display windows (green), keypad legends, function key legends
    for k, txt in enumerate(("COM1  251.00   CH 04", "NAV  RKTU 06R  3.2")):
        y0 = (1.3 + k * 2.35) * px
        c.rect(1.6 * px, y0, w - 1.6 * px, y0 + 1.95 * px, fill=(6, 18, 9), outline=(30, 30, 32), w=0.1 * px)
        c.text(cx, y0 + 0.98 * px, txt, 1.05 * px, col=(110, 255, 140), weight="Regular")
    keys = ufcp_keys()
    for k in keys:
        x, y = (k["u"] + U["w"] / 2) * px, (U["h"] / 2 - k["v"]) * px
        bw, bh = k["w"] * px, k["h"] * px
        c.rect(x - bw / 2, y - bh / 2, x + bw / 2, y + bh / 2, fill=(36, 37, 40), outline=(14, 14, 15), w=0.08 * px, radius=0.18 * px)
        c.text(x, y, k["label"], k.get("ts", 0.5) * px)
    c.text(cx, h - 0.6 * px, "UP FRONT CONTROLS", 0.34 * px)
    return c.done()


def ufcp_keys():
    """UFCP buttons in UFCP-local cm (u right, v up, origin = UFCP centre)."""
    U = L.UFCP
    keys = []
    labels = ["1", "2", "3", "4", "5", "6", "7", "8", "9", "CLR", "0", "ENT"]
    for i, lab in enumerate(labels):
        r, cidx = i // 3, i % 3
        keys.append(dict(u=-2.3 + cidx * 2.3, v=1.3 - r * 1.85, w=2.0, h=1.5, label=lab, ts=0.62 if len(lab) == 1 else 0.42))
    for i, lab in enumerate(("COM1", "COM2", "IFF", "LIST")):
        keys.append(dict(u=-7.0, v=1.3 - i * 1.85, w=2.6, h=1.5, label=lab, ts=0.42))
    for i, lab in enumerate(("A-A", "A-G", "NAV", "AP")):
        keys.append(dict(u=7.0, v=1.3 - i * 1.85, w=2.6, h=1.5, label=lab, ts=0.42))
    return keys


def mfd_bezel(px=L.PX_SMALL):
    B, S = L.MFD_BEZEL, L.MFD_SCREEN
    w = int(B * px)
    c = Canvas(w, w, (24, 25, 27))
    c.rgb.paste(paint_base(w * c.ss, w * c.ss, (24, 25, 27), 99))
    # OSB legends: labels are on the screen pages; on the bezel only the numbers
    for k in range(5):
        p = (B / 2 - S / 2 + S * (k + 0.5) / 5) * px
        for x, y, n in ((p, 0.55 * px, k + 1), (w - 0.55 * px, p, k + 6), (w - p, w - 0.55 * px, k + 11), (0.55 * px, w - p, k + 16)):
            c.text(x, y, str(n), 0.3 * px, col=(150, 152, 150), glow=False)
    for x, y, t in ((1.0, 1.0, "GAIN"), (B - 1.0, 1.0, "SYM"), (1.0, B - 1.0, "BRT"), (B - 1.0, B - 1.0, "CON")):
        c.text(x * px, y * px, t, 0.32 * px)
    return c.done()


def eyebrow(name, px=L.PX_SMALL):
    u, v, labels, cols = L.EYEBROWS[name]
    w, h = int(11.0 * px), int(5.0 * px)
    c = Canvas(w, h, PANEL)
    for k, (lab, col) in enumerate(zip(labels, cols)):
        x0 = (0.5 + k * 5.25) * px
        tint = {"amber": (60, 40, 8), "red": (60, 12, 10), "green": (10, 45, 15)}[col]
        c.rect(x0, 0.6 * px, x0 + 4.75 * px, h - 0.6 * px, fill=tint, outline=(8, 8, 8), w=0.12 * px, radius=0.2 * px)
        for i, part in enumerate(lab.split(" ")):
            n = len(lab.split(" "))
            c.text(x0 + 2.37 * px, h / 2 + (i - (n - 1) / 2) * 0.95 * px, part, 0.72 * px,
                   col={"amber": (255, 190, 60), "red": (255, 80, 60), "green": (90, 255, 120)}[col], glow=False)
    return c.done()


def light_lens(w_cm, h_cm, col, legend, px=L.PX_SMALL):
    """annunciator lens: dark tinted when off; the lit overlay (same UV, emissive material) makes it glow."""
    w, h = int(w_cm * px), int(h_cm * px)
    tint = {"amber": (70, 46, 8), "red": (70, 14, 10), "green": (12, 52, 20)}[col]
    txt = {"amber": (255, 196, 70), "red": (255, 90, 70), "green": (110, 255, 140)}[col]
    c = Canvas(w, h, tint)
    c.rect(1, 1, w - 2, h - 2, outline=(0, 0, 0), w=0.1 * px, radius=0.15 * px)
    words = legend.split(" ")
    size = min(0.85, (h_cm - 0.5) / max(1, len(words)) * 0.75)
    for i, wd in enumerate(words):
        c.text(w / 2, h / 2 + (i - (len(words) - 1) / 2) * size * 1.15 * px, wd, size * px, col=txt, glow=False, weight="Bold Condensed")
    return c.done()


def wall_tile(px=12):
    """side wall trim panel (60 x 30 cm tile, UV 0..1): seams, fastener rows, small structural ribs."""
    w, h = 60 * px, 30 * px
    c = Canvas(w, h, CONSOLE)
    c.rgb.paste(paint_base(w * c.ss, h * c.ss, CONSOLE, 57))
    for x0 in (0.0, 30.0):
        c.rect(x0 * px + 2, 2, (x0 + 30) * px - 2, h - 2, outline=(30, 32, 34), w=2)
        c.rect(x0 * px + 4, 4, (x0 + 30) * px - 4, h - 4, outline=(70, 73, 77), w=1)
        for k in range(6):
            xx = (x0 + 2.5 + k * 5.0) * px
            for yy in (1.4 * px, h - 1.4 * px):
                dzus(c, xx, yy, 0.3 * px)
    # our own stencils (realism pass 11-05): yellow / black hazard stripe placard + a small white stencil block of
    # word-shaped bars (reads as a maintenance placard, nothing to read) on the first panel; a red-bordered plate on the second
    sx0, sy0, sw, sh = 3.0 * px, 20.5 * px, 7.0 * px, 1.6 * px
    c.rect(sx0, sy0, sx0 + sw, sy0 + sh, fill=(18, 18, 18))
    k = 0
    while k * 0.8 * px < sw + sh:
        x = sx0 + k * 0.8 * px
        poly = [(x, sy0), (x + 0.4 * px, sy0), (x + 0.4 * px - sh, sy0 + sh), (x - sh, sy0 + sh)]
        c.d.polygon([(max(sx0, min(sx0 + sw, a)) * c.ss, b * c.ss) for a, b in poly], fill=(170, 130, 20))
        k += 1
    r = np.random.default_rng(77)
    for j in range(3):
        xx = 3.0 * px
        while xx < 10.0 * px:
            wl = (0.3 + r.random() * 0.8) * px
            c.rect(xx, (23.0 + j * 0.6) * px, min(xx + wl, 10.0 * px), (23.25 + j * 0.6) * px, fill=(150, 152, 150), radius=0.05 * px)
            xx += wl + 0.2 * px
    c.rect(36.0 * px, 6.0 * px, 43.0 * px, 10.0 * px, fill=(40, 42, 44), outline=(120, 30, 26), w=0.25 * px)
    for j in range(3):
        c.rect(37.0 * px, (7.0 + j * 0.8) * px, (41.0 + (j % 2)) * px, (7.35 + j * 0.8) * px, fill=(140, 140, 138), radius=0.05 * px)
    return c.done()


def build_atlas():
    P = Packer(L.ATLAS)
    regions, items = {}, []

    def put(name, img_msk, meta):
        img, msk = img_msk
        r = P.add(*img.size)
        regions[name] = dict(px=list(r), **meta)
        items.append((r, img, msk))

    put("main", main_panel(), dict(u0=L.MAIN_U0, u1=L.MAIN_U1, v0=L.MAIN_V0, v1=L.MAIN_V1))
    for name, u0, u1, v0, v1, title, elems in L.CONSOLE_PANELS:
        put(name, console_panel(name, u0, u1, v0, v1, title, elems), dict(u0=u0, u1=u1, v0=v0, v1=v1))
    T = L.THR_HOUSING
    put("thr", thr_housing(), dict(u0=T["u0"], u1=T["u1"], v0=T["v0"], v1=T["v1"]))
    if L.UFCP:
        U = L.UFCP
        put("ufcp", ufcp(), dict(u0=-U["w"] / 2, u1=U["w"] / 2, v0=-U["h"] / 2, v1=U["h"] / 2))
    for n in L.EYEBROWS:
        put(n, eyebrow(n), dict(u0=-5.5, u1=5.5, v0=-2.5, v1=2.5))
    for n, (u, v, w, h, col, legend) in L.LIGHTS.items():          # live light lenses: legend on a tinted lens
        put("LT_" + n, light_lens(w, h, col, legend), dict(u0=-w / 2, u1=w / 2, v0=-h / 2, v1=h / 2))
    put("wall", wall_tile(), dict(u0=0, u1=1, v0=0, v1=1))
    # plain swatches (UV islands for unlabelled faces)
    for n, col in (("sw_panel", PANEL), ("sw_console", CONSOLE), ("sw_white", (200, 200, 196)), ("sw_red", (150, 20, 18)),
                   ("sw_black", (12, 12, 13)), ("sw_frame", (60, 63, 66))):
        put(n, (paint_base(64, 64, col, 3), Image.new("L", (64, 64), 0)), dict(u0=0, u1=1, v0=0, v1=1))
    atlas = Image.new("RGBA", (L.ATLAS, L.ATLAS), PANEL + (0,))
    for (x, y, w, h), img, msk in items:
        rgba = img.convert("RGBA")
        rgba.putalpha(msk)
        atlas.paste(rgba, (x, y))
        # bleed 3 px around each region (mip / filtering)
        for k in range(1, 4):
            atlas.paste(rgba.crop((0, 0, w, 1)).resize((w, 1)), (x, y - k))
            atlas.paste(rgba.crop((0, h - 1, w, h)), (x, y + h - 1 + k))
            atlas.paste(rgba.crop((0, 0, 1, h)), (x - k, y))
            atlas.paste(rgba.crop((w - 1, 0, w, h)), (x + w - 1 + k, y))
    atlas.save(os.path.join(OUT, "T_CkPanels.png"), optimize=True)
    json.dump(dict(size=L.ATLAS, regions=regions, ufcp_keys=ufcp_keys()), open(os.path.join(OUT, "atlas.json"), "w"), indent=1)
    print("panel atlas used rows to y =", P.y + P.row, "of", L.ATLAS)


# =====================================================================================================================
# dials
def dial_canvas():
    S = L.DIAL_TILE
    c = Canvas(S, S, DIALF, ss=3)
    c.circle(S / 2, S / 2, S / 2 - 2, fill=(16, 16, 17))
    c.circle(S / 2, S / 2, S / 2 - 14, fill=DIALF)
    return c


def ticks(c, a0, a1, n, r0, r1, w, every=None):
    S = L.DIAL_TILE / 2
    for i in range(n + 1):
        a = math.radians(a0 + (a1 - a0) * i / max(1, n))
        sx, sy = math.sin(a), -math.cos(a)
        c.line([(S + sx * r0, S + sy * r0), (S + sx * r1, S + sy * r1)], w)


def num_at(c, a, r, s, px):
    S = L.DIAL_TILE / 2
    a = math.radians(a)
    c.text(S + math.sin(a) * r, S - math.cos(a) * r, s, px, weight="Bold Condensed")


def dial_asi():
    c = dial_canvas()
    R = 240
    for k in range(0, 801, 10):
        a = G.asi_deg(k)
        l, w = (34, 7) if k % 100 == 0 else ((22, 4) if k % 50 == 0 else (12, 3))
        ticks(c, a, a, 0, R - l, R, w)
    for k in range(0, 9):
        num_at(c, G.asi_deg(k * 100), R - 72, str(k), 56)
    c.text(256, 330, "KNOTS", 30)
    c.text(256, 362, "x100", 26)
    return c.done()


def dial_alt():
    c = dial_canvas()
    R = 240
    for k in range(50):
        a = k * 7.2
        l, w = (34, 7) if k % 5 == 0 else (16, 3)
        ticks(c, a, a, 0, R - l, R, w)
    for k in range(10):
        num_at(c, k * 36, R - 70, str(k), 58)
    c.rect(256 - 70, 316, 256 + 70, 360, fill=(4, 4, 4), outline=(80, 80, 80), w=2)
    c.text(256, 338, "29.92", 34, weight="Regular")
    c.text(256, 180, "ALT", 34)
    c.text(256, 212, "100 FEET", 22)
    return c.done()


def dial_vsi():
    c = dial_canvas()
    R = 240
    for sgn in (1, -1):
        for v in list(range(0, 1001, 100)) + list(range(1500, 6001, 500)):
            a = G.vsi_deg(sgn * v)
            major = v in (0, 500, 1000, 2000, 4000, 6000)
            ticks(c, a, a, 0, R - (32 if major else 15), R, 7 if major else 3)
        for v, s in ((500, ".5"), (1000, "1"), (2000, "2"), (4000, "4"), (6000, "6")):
            num_at(c, G.vsi_deg(sgn * v), R - 66, s, 46)
    num_at(c, G.vsi_deg(0), R - 66, "0", 50)
    c.text(150, 180, "UP", 30)
    c.text(150, 332, "DN", 30)
    c.text(256, 256 + 60, "VERT VEL", 26)
    c.text(256, 256 + 88, "x1000 FT/MIN", 20)
    return c.done()


def dial_adi_face():
    """ADI face plate (a ring around the ball window): bank scale, index at the top."""
    c = dial_canvas()
    S = 256
    c.circle(S, S, 176, fill=(0, 0, 0))     # window (the mesh is a ring, the centre is not used)
    for a in (-90, -60, -45, -30, -20, -10, 10, 20, 30, 45, 60, 90):
        l, w = (40, 8) if abs(a) in (30, 60, 90) else (24, 6)
        ticks(c, a, a, 0, 184, 184 + l, w)
    c.d.polygon([(c.ss * x, c.ss * y) for x, y in ((S, 186), (S - 14, 222), (S + 14, 222))], fill=LEGEND)
    c.m.polygon([(c.ss * x, c.ss * y) for x, y in ((S, 186), (S - 14, 222), (S + 14, 222))], fill=255)
    c.text(S, 480, "PULL TO CAGE", 20)
    return c.done()


def dial_generic(lo, hi, step, label, unit, sweep=300.0, numbers=None, redline=None):
    c = dial_canvas()
    R = 240
    a0 = -sweep / 2
    n = int(round((hi - lo) / step))
    for i in range(n * 2 + 1):
        a = a0 + sweep * i / (2 * n)
        ticks(c, a, a, 0, R - (34 if i % 2 == 0 else 16), R, 7 if i % 2 == 0 else 3)
    for i in range(n + 1):
        val = lo + i * step
        num_at(c, a0 + sweep * i / n, R - 72, (numbers[i] if numbers else ("%g" % val)), 50)
    if redline is not None:
        a = math.radians(a0 + sweep * (redline - lo) / (hi - lo))
        c.line([(256 + math.sin(a) * (R - 40), 256 - math.cos(a) * (R - 40)), (256 + math.sin(a) * R, 256 - math.cos(a) * R)], 12, col=(220, 40, 30))
    c.text(256, 330, label, 34)
    c.text(256, 366, unit, 22)
    return c.done()


def dial_clock():
    c = dial_canvas()
    R = 240
    for k in range(60):
        ticks(c, k * 6, k * 6, 0, R - (30 if k % 5 == 0 else 12), R, 7 if k % 5 == 0 else 3)
    for k in range(1, 13):
        num_at(c, k * 30, R - 66, str(k), 52)
    return c.done()


def stripe_tile():
    S = L.DIAL_TILE
    img = Image.new("RGB", (S, S), (20, 18, 12))
    d = ImageDraw.Draw(img)
    for k in range(-S, 2 * S, 64):
        d.polygon([(k, 0), (k + 32, 0), (k + 32 - S, S), (k - S, S)], fill=(222, 176, 26))
    img = img.filter(ImageFilter.GaussianBlur(0.8))
    return img, Image.new("L", (S, S), 0)


def build_dials():
    S = L.DIAL_TILE
    tiles = dict(asi=dial_asi(), alt=dial_alt(), vsi=dial_vsi(), adi=dial_adi_face(), clock=dial_clock(),
                 rpm=dial_generic(0, 100, 10, "RPM", "% x 10", numbers=["0", "", "2", "", "4", "", "6", "", "8", "", "10"], redline=103.0 * 0 + 100),
                 ftit=dial_generic(2, 12, 1, "FTIT", "x100 C", redline=10.8),
                 fuel=dial_generic(0, 8, 1, "FUEL", "x1000 LB"),
                 oil=dial_generic(0, 100, 20, "OIL", "PSI"),
                 o2=dial_generic(0, 5, 1, "O2", "LITERS"),
                 stripe=stripe_tile())
    atlas = Image.new("RGBA", (4 * S, 4 * S), (12, 12, 13, 0))
    for name, (img, msk) in tiles.items():
        u0, v0, u1, v1 = L.dial_tile(name)
        x, y = int(u0 * 4 * S), int(v0 * 4 * S)
        rgba = img.convert("RGBA")
        rgba.putalpha(msk)
        atlas.paste(rgba, (x, y))
    atlas.save(os.path.join(OUT, "T_CkDials.png"), optimize=True)


# =====================================================================================================================
def build_adi():
    W, H = 1024, 512
    c = Canvas(W, H, (0, 0, 0), ss=2)
    sky, gnd = (112, 122, 134), (34, 27, 22)
    c.rect(0, 0, W, H / 2, fill=sky)
    c.rect(0, H / 2, W, H, fill=gnd)
    Y = lambda lat: (90 - lat) / 180 * H
    X = lambda lon: (lon + 180) / 360 * W
    for front in (0, 180, -180):
        c.line([(0, Y(0)), (W, Y(0))], 5, col=(235, 235, 230), glow=False)
        for p in range(-85, 90, 5):
            if p == 0:
                continue
            half = 9 if p % 10 == 0 else 4.5
            col = (240, 240, 236) if p > 0 else (230, 230, 226)
            if p > 0:
                col = (25, 25, 28)
            c.line([(X(front - half), Y(p)), (X(front + half), Y(p))], 3 if p % 10 == 0 else 2, col=col, glow=False)
            if p % 10 == 0:
                for sx in (-1, 1):
                    c.text(X(front + sx * (half + 4.5)), Y(p), str(abs(p)), 15, col=col, glow=False, weight="Bold Condensed")
    img, _ = c.done()
    img.save(os.path.join(OUT, "T_CkADI.png"), optimize=True)


def build_grunge():
    S = 1024
    n = noise(S, S, 220, 0.5, 11) + noise(S, S, 60, 0.3, 12) + noise(S, S, 14, 0.18, 13)
    a = 0.5 + n * 0.5
    # fine scratches
    img = Image.fromarray(np.clip(a * 255, 0, 255).astype(np.uint8))
    d = ImageDraw.Draw(img)
    r = np.random.default_rng(4)
    for _ in range(260):
        x, y = r.random(2) * S
        ang = r.random() * math.pi
        l = 8 + r.random() * 60
        v = int(150 + r.random() * 90)
        d.line([(x, y), (x + math.cos(ang) * l, y + math.sin(ang) * l)], fill=v, width=1)
    # make it tile: blend with an offset copy across the seams
    arr = np.asarray(img, np.float32)
    sh = np.roll(np.roll(arr, S // 2, 0), S // 2, 1)
    wx = np.abs(np.linspace(-1, 1, S))[None, :]
    wy = np.abs(np.linspace(-1, 1, S))[:, None]
    wgt = np.clip(np.maximum(wx, wy) * 1.6 - 0.6, 0, 1)
    arr = arr * (1 - wgt) + sh * wgt
    Image.fromarray(arr.astype(np.uint8)).save(os.path.join(OUT, "T_CkGrunge.png"), optimize=True)


def build_fabric_normal():
    S = 512
    y, x = np.mgrid[0:S, 0:S].astype(np.float32)
    k = 2 * math.pi / 8.0           # weave period 8 px
    h = 0.5 * np.sin(x * k) * np.sign(np.sin(y * k / 2)) + 0.5 * np.sin(y * k) * np.sign(np.sin(x * k / 2))
    h += noise(S, S, 40, 0.25, 21)
    gx = np.roll(h, -1, 1) - np.roll(h, 1, 1)
    gy = np.roll(h, -1, 0) - np.roll(h, 1, 0)
    s = 1.6
    nx, ny, nz = -gx * s, gy * s, np.ones_like(h)
    ln = np.sqrt(nx * nx + ny * ny + nz * nz)
    rgb = np.stack([nx / ln, ny / ln, nz / ln], -1) * 0.5 + 0.5
    Image.fromarray((rgb * 255).astype(np.uint8)).save(os.path.join(OUT, "T_CkFabricN.png"), optimize=True)


def tile_blend(arr):
    """make a non-tiling array tile: cross-fade with a half-offset copy near the borders (as in build_grunge)."""
    S0, S1 = arr.shape[:2]
    sh = np.roll(np.roll(arr, S0 // 2, 0), S1 // 2, 1)
    wx = np.abs(np.linspace(-1, 1, S1))[None, :]
    wy = np.abs(np.linspace(-1, 1, S0))[:, None]
    wgt = np.clip(np.maximum(wx, wy) * 1.6 - 0.6, 0, 1)
    return arr * (1 - wgt) + sh * wgt


def build_paint_normal():
    """T_CkPaintN: hard-surface detail normal (tiles every ~6 cm): faint orange peel + fine scratches / scuffs."""
    S = 1024
    h = noise(S, S, 18, 0.5, 31) + noise(S, S, 6, 0.25, 32)
    img = Image.new("L", (S, S), 0)
    d = ImageDraw.Draw(img)
    r = np.random.default_rng(33)
    for _ in range(420):
        x, y = r.random(2) * S
        ang = r.normal(0.0, 0.35) + (math.pi / 2 if r.random() < 0.3 else 0.0)
        l = 10 + r.random() * 90
        d.line([(x, y), (x + math.cos(ang) * l, y + math.sin(ang) * l)], fill=int(120 + r.random() * 135), width=1)
    sc = np.asarray(img, np.float32) / 255.0
    h = tile_blend(h - sc * 1.2)
    gx = np.roll(h, -1, 1) - np.roll(h, 1, 1)
    gy = np.roll(h, -1, 0) - np.roll(h, 1, 0)
    s_ = 0.9
    nx, ny, nz = -gx * s_, gy * s_, np.ones_like(h)
    ln = np.sqrt(nx * nx + ny * ny + nz * nz)
    rgb = np.stack([nx / ln, ny / ln, nz / ln], -1) * 0.5 + 0.5
    Image.fromarray((rgb * 255).astype(np.uint8)).save(os.path.join(OUT, "T_CkPaintN.png"), optimize=True)


def build_canopy_scratch():
    """T_CkCanopyScratch (mapped by view angle from the eye, see ue_cockpit.ck_canopy): R = fine circular polishing
    marks (arcs around several centres, like real canopy glass in the sun, photos d09 / v2), G = smudges / dust."""
    S = 1024
    img = Image.new("L", (S, S), 0)
    d = ImageDraw.Draw(img)
    r = np.random.default_rng(41)
    for _ in range(9):                                    # polishing centres, each leaves a family of arcs
        cx, cy = r.random(2) * S
        for _ in range(int(r.integers(12, 30))):
            rad = r.uniform(20, 420)
            a0 = r.uniform(0, 360)
            span = r.uniform(15, 80)
            v = int(r.uniform(40, 200))
            for ox in (-S, 0, S):                         # wrap so the texture tiles
                for oy in (-S, 0, S):
                    b = (cx + ox - rad, cy + oy - rad, cx + ox + rad, cy + oy + rad)
                    d.arc(b, a0, a0 + span, fill=v, width=1)
    for _ in range(220):                                  # short random hairline scratches
        x, y = r.random(2) * S
        ang = r.random() * math.pi
        l = 4 + r.random() * 30
        d.line([(x, y), (x + math.cos(ang) * l, y + math.sin(ang) * l)], fill=int(r.uniform(40, 160)), width=1)
    sc = np.asarray(img, np.float32)
    sm = np.clip((noise(S, S, 90, 0.5, 42) + noise(S, S, 25, 0.35, 43) + 0.05) * 1.4, 0, 1) * 255
    sm = tile_blend(sm)
    rgb = np.stack([sc, sm, np.zeros_like(sc)], -1)
    Image.fromarray(np.clip(rgb, 0, 255).astype(np.uint8)).save(os.path.join(OUT, "T_CkCanopyScratch.png"), optimize=True)


if __name__ == "__main__":
    build_atlas()
    build_dials()
    build_adi()
    build_grunge()
    build_fabric_normal()
    build_paint_normal()
    build_canopy_scratch()
    for f in sorted(os.listdir(OUT)):
        print(f, os.path.getsize(os.path.join(OUT, f)) // 1024, "KB")
