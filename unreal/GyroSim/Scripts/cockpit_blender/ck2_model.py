"""Cockpit v2 geometry (Blender 4.5, headless only):
  blender -b --factory-startup --python Scripts/cockpit_blender/ck2_model.py -- [--no-bake] [--render] [--out DIR]
Builds an original F-16 Block 50/52 style interior from ck2_layout (UE body cm), maps textured faces into the
ck2_textures atlas, bakes AO / edge / cavity masks onto UV1 (Cycles CPU, low samples) and exports FBX parts + manifest:
  ck2_shell.fbx        static interior (panel, glare shield, HUD hardware, consoles, walls, sill + canopy frame, seat)
  ck2_glass.fbx        instrument glass + HUD combiner glass (translucent slots)
  ck2_stick.fbx        sidestick, origin = StickPivot          ck2_throttle.fbx   origin = ThrottlePivot
  ck2_gearhandle.fbx   origin = GearHandle pivot               ck2_gearlights.fbx / ck2_lt_<NAME>.fbx lit overlays (absolute)
  ck2_kneeboard.fbx    kneeboard frame (MFD_C training display sits on it)
  manifest.json        pivots / needles / screens / lights / callouts in UE body cm (read by Content/Python/cockpit_v2.py)
Output default C:/GyroSimTiles/assets/cockpit/export (outside git). Coordinates: UE (x, y, z) cm -> Blender (x, -y, z) / 100.
"""
import json
import math
import os
import sys
import time

import bmesh
import bpy
from mathutils import Matrix, Vector

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import ck2_layout as L          # noqa: E402

ARGV = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
OUT = ARGV[ARGV.index("--out") + 1] if "--out" in ARGV else r"C:\GyroSimTiles\assets\cockpit\export"
TEX = r"C:\GyroSimTiles\assets\cockpit\tex"
os.makedirs(OUT, exist_ok=True)
PLATES = {p["name"]: p for p in L.pack()}
T0 = time.time()
V = Vector
SW = L.swatch_uv()
STRIPE = L.STRIPE_SW


def log(*a):
    print("[ck2] " + " ".join(str(x) for x in a), flush=True)


# =====================================================================================================================
class Part:
    def __init__(self, name):
        self.name, self.V, self.F, self.UV, self.M, self.slots = name, [], [], [], [], []

    def slot(self, m):
        if m not in self.slots:
            self.slots.append(m)
        return self.slots.index(m)

    def add(self, verts, faces, mat, uvf=None):
        """verts: UE cm points; faces: index lists; uvf(face_index, vertex_point) -> uv or None (swatch)"""
        base = len(self.V)
        self.V.extend(tuple(v) for v in verts)
        si = self.slot(mat)
        for fi, f in enumerate(faces):
            self.F.append([base + i for i in f])
            self.M.append(si)
            self.UV.append([(uvf(fi, verts[i]) if uvf else None) or SW for i in f])


PARTS = {}


def part(n):
    if n not in PARTS:
        PARTS[n] = Part(n)
    return PARTS[n]


def frame_pt(o, ex, ey, n, a, b, c=0.0):
    return (o[0] + ex[0] * a + ey[0] * b + n[0] * c, o[1] + ex[1] * a + ey[1] * b + n[1] * c, o[2] + ex[2] * a + ey[2] * b + n[2] * c)


def norm(v):
    l = math.sqrt(sum(c * c for c in v)) or 1.0
    return tuple(c / l for c in v)


def cross(a, b):
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def sub(a, b):
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def lerp3(a, b, t):
    return tuple(a[i] + (b[i] - a[i]) * t for i in range(3))


# ---- primitives in a local frame (o, ex, ey, n) ----------------------------------------------------------------------
def prism(P, mat, fr, poly, c0, c1, top_uv=None, side_mat=None, cap_bottom=False):
    """extrude a 2D polygon (local a, b; CCW seen from +n) from c0 to c1 along n. top_uv(a, b) maps the top face."""
    o, ex, ey, n = fr
    k = len(poly)
    vs = [frame_pt(o, ex, ey, n, a, b, c0) for a, b in poly] + [frame_pt(o, ex, ey, n, a, b, c1) for a, b in poly]
    faces = [list(range(k, 2 * k))]
    P.add(vs, _fl(fr, faces), mat, (lambda fi, p: top_uv(*_ab(fr, p))) if top_uv else None)
    sides = [[i, (i + 1) % k, k + (i + 1) % k, k + i] for i in range(k)]
    if cap_bottom:
        sides.append(list(range(k))[::-1])
    P.add(vs, _fl(fr, sides), side_mat or mat)


def _lh(fr):
    """True when (ex, ey, n) is left-handed: faces built for a right-handed frame must be reversed"""
    o, ex, ey, n = fr
    c = cross(ex, ey)
    return c[0] * n[0] + c[1] * n[1] + c[2] * n[2] < 0


def _fl(fr, faces):
    return [f[::-1] for f in faces] if _lh(fr) else faces


def _ab(fr, p):
    o, ex, ey, n = fr
    d = sub(p, o)
    return (sum(d[i] * ex[i] for i in range(3)), sum(d[i] * ey[i] for i in range(3)))


def rect(a0, b0, a1, b1, ch=0.0):
    """rectangle polygon with optional chamfered corners"""
    if ch <= 0:
        return [(a0, b0), (a1, b0), (a1, b1), (a0, b1)]
    return [(a0 + ch, b0), (a1 - ch, b0), (a1, b0 + ch), (a1, b1 - ch), (a1 - ch, b1), (a0 + ch, b1), (a0, b1 - ch), (a0, b0 + ch)]


def slab(P, mat, fr, a0, b0, a1, b1, c0, c1, top_uv=None, side_mat=None, bevel=0.0):
    """box with a bevelled top: top face inset by `bevel` and raised; bevel ring faces between"""
    if bevel <= 0:
        prism(P, mat, fr, rect(a0, b0, a1, b1), c0, c1, top_uv, side_mat)
        return
    prism(P, side_mat or mat, fr, rect(a0, b0, a1, b1), c0, c1 - bevel, None)
    o, ex, ey, n = fr
    outer = [(a0, b0), (a1, b0), (a1, b1), (a0, b1)]
    inner = [(a0 + bevel, b0 + bevel), (a1 - bevel, b0 + bevel), (a1 - bevel, b1 - bevel), (a0 + bevel, b1 - bevel)]
    vs = [frame_pt(o, ex, ey, n, a, b, c1 - bevel) for a, b in outer] + [frame_pt(o, ex, ey, n, a, b, c1) for a, b in inner]
    P.add(vs, _fl(fr, [[i, (i + 1) % 4, 4 + (i + 1) % 4, 4 + i] for i in range(4)]), mat, (lambda fi, p: top_uv(*_ab(fr, p))) if top_uv else None)
    P.add(vs, _fl(fr, [[4, 5, 6, 7]]), mat, (lambda fi, p: top_uv(*_ab(fr, p))) if top_uv else None)


def lathe(P, mat, fr, prof, seg=24, uvf=None, knurl=None, phase=0.0, caps=True):
    """revolve profile [(r, c), ...] about the frame's n axis at (0, 0). knurl = (r_amp) alternates radii (grip ribs)."""
    o, ex, ey, n = fr
    rings = []
    for j, (r, c) in enumerate(prof):
        ring = []
        for i in range(seg):
            t = 2 * math.pi * i / seg + phase
            rr = r + (knurl if (knurl and 0 < j < len(prof) - 1 and i % 2) else 0.0)
            ring.append(frame_pt(o, ex, ey, n, rr * math.cos(t), rr * math.sin(t), c))
        rings.append(ring)
    vs = [p for ring in rings for p in ring]
    faces = []
    for j in range(len(prof) - 1):
        for i in range(seg):
            a, b = j * seg + i, j * seg + (i + 1) % seg
            faces.append([a, b, b + seg, a + seg])
    if caps and prof[-1][0] > 1e-4:
        faces.append([(len(prof) - 1) * seg + i for i in range(seg)])
    if caps and prof[0][0] > 1e-4:
        faces.append([i for i in range(seg)][::-1])
    P.add(vs, _fl(fr, faces), mat, uvf)


def tube(P, mat, path, r, seg=10, closed=False, uv_len=None, rscale=None):
    """sweep a circle along a polyline (UE points)"""
    m = len(path)
    rings = []
    acc = [0.0]
    for i in range(1, m):
        acc.append(acc[-1] + math.dist(path[i], path[i - 1]))
    prev_side = None
    for i in range(m):
        t = sub(path[min(i + 1, m - 1)], path[max(i - 1, 0)]) if not closed else sub(path[(i + 1) % m], path[(i - 1) % m])
        t = norm(t)
        ref = (0.0, 0.0, 1.0) if abs(t[2]) < 0.9 else (1.0, 0.0, 0.0)
        s1 = norm(cross(t, ref)) if prev_side is None else norm(cross(cross(t, prev_side), t))
        prev_side = s1
        s2 = cross(t, s1)
        rr = r * (rscale[i] if rscale else 1.0)
        rings.append([tuple(path[i][k] + (s1[k] * math.cos(2 * math.pi * j / seg) + s2[k] * math.sin(2 * math.pi * j / seg)) * rr for k in range(3))
                      for j in range(seg)])
    vs = [p for ring in rings for p in ring]
    faces = []
    for i in range(m - 1 + (1 if closed else 0)):
        i2 = (i + 1) % m
        for j in range(seg):
            faces.append([i * seg + j, i * seg + (j + 1) % seg, i2 * seg + (j + 1) % seg, i2 * seg + j])
    if not closed:
        faces.append(list(range(seg))[::-1])
        faces.append([(m - 1) * seg + j for j in range(seg)])
    uvf = None
    if uv_len:
        x0, y0, w, h = STRIPE

        def uvf(fi, p):
            return None
        # per-face u along the path: assign by ring index (stripe swatch, repeats inside its 128 px)
        uvs = []
        for i in range(m):
            u = (acc[i] / uv_len) % 1.0
            uvs.append(((x0 + 4 + u * (w - 8)) / L.ATLAS, 1.0 - (y0 + h / 2) / L.ATLAS))
        base = len(P.V)
        P.add(vs, faces, mat)
        for k, f in enumerate(P.F[len(P.F) - len(faces):]):
            P.UV[len(P.F) - len(faces) + k] = [uvs[(vi - base) // seg] for vi in f]
        return
    P.add(vs, faces, mat, uvf)


def grid(P, mat, fn, nu, nv, uvf=None, flip=False):
    """surface from fn(s, t) -> UE point, s, t in 0..1"""
    vs = [fn(i / nu, j / nv) for j in range(nv + 1) for i in range(nu + 1)]
    faces = []
    for j in range(nv):
        for i in range(nu):
            a = j * (nu + 1) + i
            f = [a, a + 1, a + nu + 2, a + nu + 1]
            faces.append(f[::-1] if flip else f)
    P.add(vs, faces, mat, uvf)


def box(P, mat, c, size, ex=(1, 0, 0), ey=(0, 1, 0), n=(0, 0, 1)):
    sx, sy, sz = size
    o = frame_pt(c, ex, ey, n, -sx / 2, -sy / 2, 0.0)
    prism(P, mat, (o, ex, ey, n), rect(0, 0, sx, sy), -sz / 2, sz / 2, cap_bottom=True)


# =====================================================================================================================
SH = "ck2_shell"


def plate_frame(p):
    """plate frame with the normal toward the pilot's eye (frames may be left-handed; builders reverse faces then)"""
    ex, ey = p["ex"], p["ey"]
    n = norm(cross(ex, ey))
    d = sub(L.EYE, p["origin"])
    if n[0] * d[0] + n[1] * d[1] + n[2] * d[2] < 0:
        n = tuple(-c for c in n)
    return (p["origin"], ex, ey, n)


def plate_uv(p):
    return lambda a, b: L.plate_uv(p, min(max(a, 0.0), p["w"]), min(max(b, 0.0), p["h"]))


def build_plate(p):
    """the plate slab + its items"""
    P = part(SH)
    fr = plate_frame(p)
    o, ex, ey, n = fr
    uvp = plate_uv(p)
    if p["kind"] in ("icp", "mfd"):
        depth = L.ICP["depth"] if p["kind"] == "icp" else L.MFD_DEPTH
        if p["kind"] == "mfd":       # bezel with the screen window
            s, b = p["screen"], p["w"]
            m0, m1 = (b - s) / 2, (b + s) / 2
            for poly in (rect(0, 0, b, m0), rect(0, m1, b, b), rect(0, m0, m0, m1), rect(m1, m0, b, m1)):
                prism(P, "CK2_Plate", fr, poly, -depth, 0.0, uvp, "CK2_Bezel")
            scr = "CK2_Screen_L" if p["name"].startswith("MFD_L") else "CK2_Screen_R"
            prism(P, scr, fr, rect(m0, m0, m1, m1), -depth, -0.55, None, "CK2_Bezel")
        else:
            prism(P, "CK2_Plate", fr, rect(0, 0, p["w"], p["h"], 0.25), -depth, 0.0, uvp, "CK2_Bezel")
        top = 0.0
    else:
        top = p["raise_"]
        slab(P, "CK2_Plate", fr, 0, 0, p["w"], p["h"], -0.3, top, uvp, "CK2_PlateSide", bevel=min(0.12, top * 0.4))
    for it in p["items"]:
        build_item(p, fr, it, top)


def build_item(p, fr, it, top):
    P = part(SH)
    o, ex, ey, n = fr
    k = it[0]
    uvp = plate_uv(p)

    def at(a, b):
        return (frame_pt(o, ex, ey, n, a, b, top), ex, ey, n)
    if k == "toggle":
        a, b = it[1], it[2]
        f = at(a, b)
        lathe(P, "CK2_Metal", f, [(0.5, 0.0), (0.5, 0.18), (0.42, 0.3), (0.0, 0.3)], seg=6)
        # lever tilted toward +b (ON) 18 deg
        tilt = math.radians(18.0)
        d = norm(tuple(n[i] * math.cos(tilt) + ey[i] * math.sin(tilt) for i in range(3)))
        b0 = frame_pt(f[0], ex, ey, n, 0, 0, 0.3)
        b1 = tuple(b0[i] + d[i] * 1.5 for i in range(3))
        tube(P, "CK2_Chrome", [b0, b1], 0.12, seg=8, rscale=[1.0, 0.75])
        lathe(P, "CK2_Chrome", (b1, ex, ey, n), [(0.0, -0.17), (0.12, -0.12), (0.17, 0.0), (0.12, 0.12), (0.0, 0.17)], seg=8)
    elif k == "knob":
        a, b, d = it[1], it[2], it[3]
        r = d / 2.0
        f = at(a, b)
        lathe(P, "CK2_Knob", f, [(r * 0.95, 0.0), (r * 0.95, 0.22), (r * 0.62, 0.3), (r * 0.6, 1.1), (r * 0.52, 1.25), (0.0, 1.25)], seg=20, knurl=r * 0.04)
        box(P, "CK2_White", frame_pt(f[0], ex, ey, n, 0.0, r * 0.3, 1.26), (0.12, r * 0.6, 0.03), ex, ey, n)
    elif k == "button":
        a, b, w, h = it[1], it[2], it[3], it[4]
        slab(P, "CK2_Plate", fr, a - w / 2, b - h / 2, a + w / 2, b + h / 2, top - 0.1, top + 0.45, uvp, "CK2_Knob", bevel=0.07)
    elif k == "rocker":
        a, b, w, h = it[1], it[2], it[3], it[4]
        slab(P, "CK2_Knob", fr, a - w / 2, b - h / 2, a + w / 2, b + h / 2, top - 0.1, top + 0.4, None, None, bevel=0.08)
    elif k == "wheel_s":
        a, b, d = it[1], it[2], it[3]
        c = frame_pt(o, ex, ey, n, a, b, top + 0.1)
        lathe(P, "CK2_Knob", (frame_pt(c, ex, ey, n, -d / 2, 0, 0), ey, n, ex), [(0.45, 0.0), (0.45, d)], seg=16, knurl=0.04)
    elif k == "dial":
        a, b, d = it[1], it[2], it[3]
        r = d / 2.0
        f = at(a, b)
        lathe(P, "CK2_Bezel", f, [(r + 0.05, -0.05), (r + 0.5, 0.0), (r + 0.5, 0.35), (r + 0.3, 0.6), (r + 0.02, 0.6), (r + 0.02, 0.2)], seg=40, caps=False)
        lathe(part("ck2_glass"), "CK2_Glass", (frame_pt(f[0], ex, ey, n, 0, 0, 0.5), ex, ey, n), [(r + 0.05, 0.0), (0.0, 0.0)], seg=32)
    elif k == "lamp":
        a, b, w, h = it[1], it[2], it[3], it[4]
        slab(P, "CK2_Lens", fr, a - w / 2, b - h / 2, a + w / 2, b + h / 2, top - 0.1, top + 0.3, uvp, "CK2_Bezel", bevel=0.05)
    elif k == "guard":
        a, b = it[1], it[2]
        g = "CK2_Red"
        for s in (-1, 1):
            prism(P, g, fr, rect(a + s * 1.0 - 0.1, b - 1.3, a + s * 1.0 + 0.1, b + 1.3), top, top + 1.3)
        prism(P, g, fr, rect(a - 1.1, b - 1.3, a + 1.1, b + 1.3), top + 1.3, top + 1.45)
    elif k in ("display", "rwr"):
        if k == "display":
            a, b, w, h = it[1], it[2], it[3], it[4]
        else:
            a, b, w = it[1], it[2], it[3]
            h = w
        prism(P, "CK2_Lit", fr, rect(a - w / 2, b - h / 2, a + w / 2, b + h / 2), top - 0.2, top + 0.02, uvp, "CK2_Bezel")
        prism(part("ck2_glass"), "CK2_Glass", fr, rect(a - w / 2, b - h / 2, a + w / 2, b + h / 2), top + 0.25, top + 0.25)
    elif k == "wheel":
        a, b = it[1], it[2]
        f = at(a, b)
        lathe(P, "CK2_Bezel", f, [(1.9, 0.0), (1.9, 0.3), (1.5, 0.3), (1.5, 0.05)], seg=24, caps=False)


# =====================================================================================================================
def build_panel_structure():
    P = part(SH)
    PN, PU = L.PANEL_N, L.PANEL_UP
    fr = (L.panel_pt(0, 0), (0.0, 1.0, 0.0), PU, PN)
    paint = "CK2_Paint"
    # upper panel face behind the MFDs (u -WING_U..WING_U, v WELL_V1..lip) - up to the glare shield soffit
    def upper(s, t):
        u = -L.WING_U + 2 * L.WING_U * s
        v0 = L.WELL_V1
        v1 = L.lip_z(u) - 0.5
        return L.panel_pt(u, v0 + (v1 - v0) * t)
    grid(P, paint, upper, 24, 4)
    # column face (|u| < COL_HALF + 0.6) from COL_V0 to WELL_V1
    ch = L.COL_HALF + 0.6
    grid(P, paint, lambda s, t: L.panel_pt(-ch + 2 * ch * s, L.COL_V0 + (L.WELL_V1 - L.COL_V0) * t), 2, 4)
    # aux panels faces (|u| AUX_U0..AUX_U1, v 18..41) and the leg wells
    for sd in (-1, 1):
        a0, a1 = sorted((sd * L.AUX_U0, sd * L.AUX_U1))
        grid(P, paint, lambda s, t, a0=a0, a1=a1: L.panel_pt(a0 + (a1 - a0) * s, 18.0 + (L.WELL_V1 - 18.0) * t), 2, 2)
        # well: back wall (WELL_DEPTH forward), walls
        u0, u1 = sorted((sd * ch, sd * L.AUX_U0))
        D = L.WELL_DEPTH
        bk = lambda u, v: L.add(L.panel_pt(u, v), (D, 0.0, 0.0))
        grid(P, "CK2_Well", lambda s, t: bk(u0 + (u1 - u0) * s, 6.0 + (L.WELL_V1 - 6.0) * t), 3, 4)
        for uu in (u0, u1):         # side walls (column side and aux side)
            grid(P, "CK2_Well", lambda s, t, uu=uu: L.add(L.panel_pt(uu, 6.0 + (L.WELL_V1 - 6.0) * t), (D * s, 0.0, 0.0)), 2, 4, flip=(uu == u0) == (sd > 0))
        grid(P, "CK2_Well", lambda s, t: L.add(L.panel_pt(u0 + (u1 - u0) * s, L.WELL_V1), (D * t, 0.0, 0.0)), 3, 2, flip=sd < 0)
    # aux panel bottoms + column bottom: lower kick panels going forward to the footwell
    for a0, a1, v in ((-L.AUX_U1, -L.AUX_U0, 18.0), (L.AUX_U0, L.AUX_U1, 18.0), (-ch, ch, L.COL_V0)):
        grid(P, "CK2_Well", lambda s, t, a0=a0, a1=a1, v=v: L.add(L.panel_pt(a0 + (a1 - a0) * s, v - (v + 10.0) * t), (6.0 * t, 0.0, 0.0)), 2, 3)
    # wing structure (angled faces) and the sides that close the gap to the MFD surround
    for sd in (-1, 1):
        ex, ey, n = L.wing_frame(sd)
        grid(P, paint, lambda s, t, sd=sd: L.wing_pt(sd, L.WING_W * s, L.WING_V0 - 1.0 + (L.WING_V1 + 1.0 - L.WING_V0) * t), 3, 3, flip=sd < 0)
        # top cap of the wing
        grid(P, paint, lambda s, t, sd=sd: L.add(L.wing_pt(sd, L.WING_W * s, L.WING_V1 + 1.0), (6.0 * t, 0.0, 0.0)), 3, 1, flip=sd > 0)
    # plates
    for p in PLATES.values():
        if p["kind"] in ("panel", "wing", "well", "icp", "mfd"):
            build_plate(p)
    # ICP / DED box sides: built in build_plate (icp). MFD screens behind the windows handled there too.


def build_glareshield():
    P = part(SH)
    nx, nu = 14, 26

    def lim(x, z):
        return min(L.skin_half_width(x, z), L.glass_bottom(x)[0] + 3.0 if x < 535 else L.skin_half_width(x, z)) - 1.5

    def top(s, t):
        u = -1.0 + 2.0 * s
        x = (L.panel_x(L.LIP_ZC) - L.LIP_OVER) + (L.GLARE_X1 - (L.panel_x(L.LIP_ZC) - L.LIP_OVER)) * t
        uu = u * L.LIP_HALF
        z = L.lip_z(uu) + 0.4
        w = min(L.LIP_HALF, lim(x, z))
        uu = u * w
        z = min(L.lip_z(uu) + 0.4, L.glass_top(x) - 3.0) if x > 520 else L.lip_z(uu) + 0.4
        return (x - (L.lip_z(0) - L.lip_z(uu)) * 0.25 * (1 - t), uu, z)
    grid(P, "CK2_Glare", top, nu, nx, flip=True)
    # rubber lip (front edge toward the pilot) and soffit back to the panel
    def lip(s, t):
        x, y, z = top(s, 0.0)
        return (x, y, z - 1.8 * t)
    grid(P, "CK2_Rubber", lip, nu, 1)
    def soffit(s, t):
        x, y, z = top(s, 0.0)
        z -= 1.8
        return (x + (L.panel_x(z) - x) * t, y, z)
    grid(P, "CK2_Glare", soffit, nu, 2, flip=True)
    # HUD housing: tapered box on the glare shield, combiner frame, side posts
    hb = L.HUD_BODY
    w0, w1 = hb["w"] / 2, hb["w"] / 2 - 2.0
    pts = [(hb["x0"], -w0, hb["z0"]), (hb["x1"], -w1, hb["z0"]), (hb["x1"], w1, hb["z0"]), (hb["x0"], w0, hb["z0"]),
           (hb["x0"] + 1.5, -w0 + 0.8, hb["z1"]), (hb["x1"], -w1 + 1.5, hb["z1"] - 1.5), (hb["x1"], w1 - 1.5, hb["z1"] - 1.5), (hb["x0"] + 1.5, w0 - 0.8, hb["z1"])]
    P.add(pts, [[0, 3, 2, 1], [4, 5, 6, 7], [0, 1, 5, 4], [1, 2, 6, 5], [2, 3, 7, 6], [3, 0, 4, 7]], "CK2_HUDBody")
    # HUD control strip on the housing back face (small knobs)
    for i in range(3):
        c = (hb["x0"] + 0.4, -6.0 + 6.0 * i, hb["z0"] + 3.0)
        lathe(P, "CK2_Knob", (c, (0, 1, 0), (0, 0, 1), (-1, 0, 0)), [(0.6, 0.0), (0.55, 0.9), (0.0, 0.9)], seg=14, knurl=0.03)
    # combiner: glass octagon + thin metal rim + two posts
    H = L.HUD
    base, fw, up = H["base"], H["fwd"], H["up"]
    right = (0.0, 1.0, 0.0)

    def cpt(a, b, c=0.0):
        return tuple(base[i] + right[i] * a + up[i] * b + fw[i] * c for i in range(3))
    poly = H["poly"]
    G = part("ck2_glass")
    G.add([cpt(a, b) for a, b in poly], [list(range(len(poly)))[::-1]], "CK2_HUDGlass")
    # thin metal edge strip only on the sides and the foot (the real combiner is frameless at the top)
    rim = [cpt(a, b, 0.05) for a, b in poly]
    tube(P, "CK2_HUDFrame", [rim[6], rim[7], rim[0], rim[1], rim[2], rim[3]], 0.12, seg=6)
    for s in (-1, 1):                    # side posts from the housing to the glass foot corners
        a = s * (H["poly"][2][0] + 0.2)
        tube(P, "CK2_HUDFrame", [cpt(a * 0.9, -0.5, 1.2), cpt(a, 11.4, 0.15)], 0.28, seg=8)
    box(P, "CK2_HUDFrame", cpt(0.0, 3.6, 0.5), (2 * H["poly"][1][0] + 1.0, 1.2, 1.0), right, up, fw)


def build_consoles():
    P = part(SH)
    z = L.CONSOLE_Z
    for sd in (-1, 1):
        yi, yo = sd * L.CONSOLE_IN, sd * L.CONSOLE_OUT
        ya, yb = sorted((yi, yo))
        # console top base under the plates, inner side wall down to the floor, aft end
        grid(P, "CK2_Plate0", lambda s, t: (L.CONSOLE_X0 + (L.CONSOLE_X1 - L.CONSOLE_X0) * t, ya + (yb - ya) * s, z - 0.3), 2, 6, flip=True)
        grid(P, "CK2_Paint", lambda s, t: (L.CONSOLE_X0 + (L.CONSOLE_X1 + 6.0 - L.CONSOLE_X0) * s, yi, z - 0.3 - (z + 10.0) * t), 8, 3, flip=sd > 0)
        grid(P, "CK2_Paint", lambda s, t: (L.CONSOLE_X0, ya + (yb - ya) * s, z - 0.3 - (z + 10.0) * t), 2, 2, flip=sd < 0)
        # sloped side wall from the console outer edge up to the sill, then the sill top out to the skin
        def wall(s, t):
            x = L.CONSOLE_X0 - 4.0 + (L.CONSOLE_X1 + 4.0 - L.CONSOLE_X0) * s
            gy, gz = L.glass_bottom(max(392.0, x))
            zz = z + (gz - 2.0 - z) * t
            y0 = L.CONSOLE_OUT
            y1 = min(L.wall_y(x, zz), gy - 0.5)
            yy = y0 + (y1 - y0) * (t ** 0.7)
            return (x, sd * yy, zz)
        grid(P, "CK2_Wall", wall, 16, 6, flip=sd > 0)
        # canopy sill rail / frame (black, along the glass bottom edge) with rivet heads
        rail_in, rail_top = [], []
        xs = [376.0 + 4.0 * i for i in range(40)]
        xs = [x for x in xs if x <= 532.0]
        for x in xs:
            gy, gz = L.glass_bottom(max(392.0, x))
            rail_in.append((x, sd * (gy - 2.6), gz - 2.0))
        for i in range(len(xs) - 1):
            pass
        def rail(s, t):
            x = xs[0] + (xs[-1] - xs[0]) * s
            gy, gz = L.glass_bottom(max(392.0, x))
            # section: inner face (gy - 2.6, gz - 2 .. gz + 3.2), top out to the glass (gy + 0.4, gz + 3.2)
            if t < 0.5:
                tt = t / 0.5
                return (x, sd * (gy - 2.6), gz - 2.0 + 5.2 * tt)
            tt = (t - 0.5) / 0.5
            return (x, sd * (gy - 2.6 + 3.0 * tt), gz + 3.2)
        grid(P, "CK2_Frame", rail, 24, 2, flip=sd < 0)
        for x in xs[1:-1]:
            gy, gz = L.glass_bottom(max(392.0, x))
            c = (x + 2.0, sd * (gy - 2.62), gz + 0.6)
            lathe(P, "CK2_Metal", (c, (1, 0, 0), (0, 0, 1), (0, -sd, 0)), [(0.32, 0.0), (0.25, 0.12), (0.0, 0.16)], seg=6)
    # console plates
    for p in PLATES.values():
        if p["kind"] in ("console", "placard"):
            build_plate(p)
    # throttle quadrant housing (left), slot strip
    x0, x1 = 424.0, 470.0
    box(P, "CK2_Paint", ((x0 + x1) / 2, -41.5, z + 2.2), (x1 - x0, 9.5, 4.4))
    box(P, "CK2_Paint", ((x0 + x1) / 2, -27.6, z + 1.5), (x1 - x0, 5.0, 3.0))
    box(P, "CK2_Rubber", ((x0 + x1) / 2, -33.4, z + 0.4), (x1 - x0 - 2.0, 6.0, 0.6))
    # sidestick base area: black round base plate + vent grille frame
    s = L.STICK_SIDE["pivot"]
    lathe(P, "CK2_Knob", ((s[0], s[1], z), (1, 0, 0), (0, 1, 0), (0, 0, 1)), [(4.6, 0.0), (4.6, 0.6), (4.0, 1.2), (3.0, 1.4), (0.0, 1.4)], seg=32)
    # forearm rest, outboard of the stick (swing-up pad)
    box(P, "CK2_Rubber", (446.0, 44.0, z + 3.0), (22.0, 5.5, 3.0))


def build_tub():
    P = part(SH)
    # floor, footwell, rear bulkhead
    grid(P, "CK2_Well", lambda s, t: (395.0 + 140.0 * t, -L.CONSOLE_IN + 2 * L.CONSOLE_IN * s, -10.0), 2, 4, flip=True)
    grid(P, "CK2_Well", lambda s, t: (530.0, -L.CONSOLE_IN + 2 * L.CONSOLE_IN * s, -10.0 + 35.0 * t), 2, 2)
    grid(P, "CK2_Paint", lambda s, t: (378.0, -50.0 + 100.0 * s, -10.0 + 80.0 * t), 4, 4, flip=True)
    # rear canopy arch frame (behind the seat): rectangular section swept along the glass arch
    arch = [(30.8, 92.0)] + [(w - 1.0, z - 1.5) for w, z in L.OLD.GLASS_ARCH_372]
    pts = [(L.OLD.REAR_ARCH_X + 4.0, -w, z) for w, z in arch] + [(L.OLD.REAR_ARCH_X + 4.0, w, z) for w, z in reversed(arch[:-1])]
    tube(P, "CK2_Frame", pts, 2.2, seg=8)
    tube(P, "CK2_Frame", [(p[0] - 3.0, p[1], p[2]) for p in pts], 2.6, seg=8)


def build_seat():
    P = part(SH)
    rec = math.radians(15.0)
    bx, bz = 408.0, 26.0                          # backrest bottom (physical rig, Scripts/cockpit/layout.py)

    def back(zz, off=0.0):
        return bx - (zz - bz) * math.tan(rec) + off

    # bucket sides (grey-green painted) following the back
    for sd in (-1, 1):
        y = sd * 23.0
        prof = [(458.0, 17.0), (458.0, 31.0), (444.0, 34.0), (back(60.0, 6.0), 60.0), (back(95.0, 4.0), 95.0), (back(95.0, -6.0), 95.0), (back(17.0, -6.0), 17.0)]
        k = len(prof)
        vs = [(x, y - sd * 1.2, zz) for x, zz in prof] + [(x, y + sd * 1.2, zz) for x, zz in prof]
        f = [list(range(k)), list(range(k, 2 * k))[::-1]] + [[i, (i + 1) % k, k + (i + 1) % k, k + i] for i in range(k)]
        P.add(vs, f if sd > 0 else [ff[::-1] for ff in f], "CK2_SeatPaint")
        # side handles / rails (black)
        tube(P, "CK2_Knob", [(back(70.0, 2.0), sd * 24.6, 70.0), (back(110.0, 2.0), sd * 15.0, 110.0)], 1.0, seg=8)
    # seat pan cushion (sheepskin) and back cushion
    grid(P, "CK2_Fleece", lambda s, t: (back(28.0, 3.0) + (457.0 - back(28.0, 3.0)) * t, -21.0 + 42.0 * s, 27.5 + 2.0 * math.sin(math.pi * s) ** 0.5 + 2.0 * t), 12, 10, flip=True)
    grid(P, "CK2_Fleece", lambda s, t: (back(28.0 + 62.0 * t, 4.0 + 1.5 * math.sin(math.pi * s) ** 0.5), -20.0 + 40.0 * s, 28.0 + 62.0 * t), 12, 10)
    # headrest box (ACES II: tall, forward of the back), cloth cover tone
    hz0, hz1 = 92.0, 117.0
    c = (back((hz0 + hz1) / 2, 4.0), 0.0, (hz0 + hz1) / 2)
    ex = (math.sin(rec) * 0, 1.0, 0.0)
    up = (-math.sin(rec), 0.0, math.cos(rec))
    fw = (math.cos(rec), 0.0, math.sin(rec))
    for dx, sz, m in ((4.0, (27.0, hz1 - hz0, 8.0), "CK2_Headrest"), (-2.0, (30.0, hz1 - hz0 + 4.0, 8.0), "CK2_SeatPaint")):
        box(P, m, tuple(c[i] + fw[i] * dx for i in range(3)), sz, ex, up, fw)
    # ejection loop: yellow / black striped D-handle at the seat front
    ej = L.EJECT
    path = []
    for i in range(17):
        t = math.pi * i / 16
        path.append((457.5 + 6.0 * math.sin(t), -ej["w"] / 2 * math.cos(t), ej["z"] + 1.5 * math.sin(t)))
    tube(P, "CK2_Plate", path, 0.65, seg=10, uv_len=5.0)
    for sd in (-1, 1):
        box(P, "CK2_Metal", (456.0, sd * ej["w"] / 2, ej["z"] - 0.5), (3.0, 1.6, 2.0))


# ---- moving / live parts -------------------------------------------------------------------------------------------
def build_stick():
    P = part("ck2_stick")
    s = L.STICK_SIDE["pivot"]
    z0 = s[2]
    # bellows boot (grey rubber, ribs)
    prof = [(2.7, z0 - 2.0)]
    for i in range(9):
        prof.append((2.6 - 0.09 * i + (0.25 if i % 2 else 0.0), z0 - 1.6 + 0.62 * i))
    prof += [(1.7, z0 + 4.2), (1.5, z0 + 4.4)]
    lathe(P, "CK2_Boot", ((s[0], s[1], 0.0), (1, 0, 0), (0, 1, 0), (0, 0, 1)), prof, seg=24)
    # collar
    lathe(P, "CK2_Grip", ((s[0], s[1], z0 + 4.4), (1, 0, 0), (0, 1, 0), (0, 0, 1)), [(1.9, 0.0), (1.9, 0.7), (1.4, 0.9), (0.0, 0.9)], seg=20)
    # grip: sections swept along a forward-leaning curve
    lean = math.radians(L.STICK_SIDE["lean"])
    path, rs = [], []
    for i in range(11):
        t = i / 10.0
        h = 11.0 * t
        x = s[0] + math.sin(lean) * h + 0.8 * math.sin(math.pi * t)
        path.append((x, s[1] - 0.4 * t, z0 + 5.2 + math.cos(lean) * h))
        rs.append(1.0 + 0.18 * math.sin(math.pi * t * 0.9) + (0.25 if t > 0.75 else 0.0))
    tube(P, "CK2_Grip", path, 1.55, seg=14, rscale=rs)
    # head: rounded box with the trim hat, red button, trigger
    top = path[-1]
    fw = (math.cos(lean), 0.0, -math.sin(lean))
    up = (math.sin(lean), 0.0, math.cos(lean))
    box(P, "CK2_Grip", tuple(top[i] + up[i] * 0.8 + fw[i] * 0.6 for i in range(3)), (4.6, 3.6, 2.6), fw, (0, 1, 0), up)
    lathe(P, "CK2_Knob", (tuple(top[i] + up[i] * 2.1 + fw[i] * 0.2 for i in range(3)), fw, (0, 1, 0), up), [(0.55, 0.0), (0.5, 0.5), (0.0, 0.6)], seg=10)
    lathe(P, "CK2_Red", (tuple(top[i] + up[i] * 2.1 + fw[i] * 1.6 for i in range(3)), fw, (0, 1, 0), up), [(0.45, 0.0), (0.42, 0.35), (0.0, 0.4)], seg=10)
    lathe(P, "CK2_Chrome", (tuple(top[i] + up[i] * 1.6 - fw[i] * 1.5 + (0, -1.6, 0)[i] for i in range(3)), (0, -1, 0), fw, up), [(0.5, 0.0), (0.45, 0.4), (0.0, 0.5)], seg=10)
    box(P, "CK2_Red", tuple(top[i] - up[i] * 1.6 + fw[i] * 2.0 for i in range(3)), (0.8, 1.4, 2.4), fw, (0, 1, 0), up)     # trigger
    box(P, "CK2_Knob", tuple(path[3][i] + (0, -1.5, 0)[i] for i in range(3)), (1.0, 0.6, 1.0))                      # pinky switch
    return s


def build_throttle():
    P = part("ck2_throttle")
    pv = L.THR["pivot"]
    # arm from the pivot up through the slot
    tube(P, "CK2_Metal", [pv, (pv[0] + 0.5, pv[1] - 1.4, pv[2] + 6.0)], 0.9, seg=10)
    # grip body: chunky box shaped to the left hand + thumb shelf
    c = (pv[0] + 1.0, pv[1] - 2.0, pv[2] + 10.0)
    fw, rt, up = (1, 0, 0), (0, 1, 0), (0, 0, 1)
    box(P, "CK2_Grip", c, (10.5, 5.6, 6.5), fw, rt, up)
    box(P, "CK2_Grip", (c[0] + 0.5, c[1] + 1.2, c[2] + 3.6), (9.0, 4.6, 1.4), fw, rt, up)
    box(P, "CK2_Grip", (c[0] - 4.2, c[1] - 0.2, c[2] - 2.6), (3.0, 6.0, 3.6), fw, rt, up)
    # switches on the inboard face and top: speed brake slider, antenna knob, cursor
    lathe(P, "CK2_Knob", ((c[0] + 3.0, c[1] + 2.85, c[2] + 1.5), (1, 0, 0), (0, 0, 1), (0, 1, 0)), [(0.55, 0.0), (0.55, 0.5), (0.0, 0.6)], seg=10)
    box(P, "CK2_Knob", (c[0] - 1.0, c[1] + 2.9, c[2] + 2.4), (2.2, 0.5, 0.9))
    lathe(P, "CK2_Chrome", ((c[0] + 0.5, c[1] + 2.85, c[2] - 0.6), (1, 0, 0), (0, 0, 1), (0, 1, 0)), [(0.4, 0.0), (0.35, 0.45), (0.0, 0.5)], seg=8)
    box(P, "CK2_Red", (c[0] + 4.5, c[1] - 1.0, c[2] + 3.4), (0.9, 1.2, 0.5))
    return pv


def plate_point(pname, a, b, off=0.0):
    p = PLATES[pname]
    o, ex, ey, n = plate_frame(p)
    return frame_pt(o, ex, ey, n, a, b, p["raise_"] + off), n


def build_gearhandle():
    P = part("ck2_gearhandle")
    pv, n = plate_point(L.GEAR["plate"], L.GEAR["a"], L.GEAR["b"], 0.3)
    end = L.add(pv, n, 7.0)
    tube(P, "CK2_Metal", [pv, end], 0.45, seg=10)
    # wheel-shaped knob (torus, axis spanwise) with spokes
    ring = []
    for i in range(24):
        t = 2 * math.pi * i / 24
        ring.append(L.add(L.add(end, (1, 0, 0), 1.7 * math.cos(t)), n, 1.7 * math.sin(t)))
    tube(P, "CK2_GearKnob", ring, 0.42, seg=8, closed=True)
    for t in (0.0, 2.1, 4.2):
        tube(P, "CK2_GearKnob", [end, L.add(L.add(end, (1, 0, 0), 1.6 * math.cos(t)), n, 1.6 * math.sin(t))], 0.2, seg=6)
    lathe(P, "CK2_Red", (end, (1, 0, 0), n, (0, 1, 0)), [(0.55, -0.6), (0.55, 0.6), (0.0, 0.7)], seg=12)
    return pv


def build_lit():
    """lit overlays (shown by the sim when the condition is true): absolute positions"""
    out = {}
    for name, (pname, a, b, w, h, colr, legend) in L.LIGHTS.items():
        P = part("ck2_lt_" + name)
        p = PLATES[pname]
        prism(P, "CK2_LampOn_" + colr, plate_frame(p), rect(a - w / 2, b - h / 2, a + w / 2, b + h / 2), p["raise_"] + 0.32, p["raise_"] + 0.36, plate_uv(p))
        out[name] = dict(part="ck2_lt_" + name, color=colr, legend=legend.replace("|", " "))
    P = part("ck2_gearlights")
    p = PLATES[L.GEAR["plate"]]
    for a, b in L.GEAR_LIGHTS:
        prism(P, "CK2_LampOn_green", plate_frame(p), rect(a - 0.75, b - 0.75, a + 0.75, b + 0.75), p["raise_"] + 0.32, p["raise_"] + 0.36, plate_uv(p))
    return out


KNEE = dict(center=(457.0, -12.5, 46.5), size=(20.0, 12.5))


def build_kneeboard():
    P = part(SH)                     # kneeboard rides in the shell (no extra actor at Play)
    c = KNEE["center"]
    n = norm(sub(L.EYE, c))
    ex = norm(cross((0, 0, 1), n))          # right on the board as seen by the pilot
    ex = (ex[0], ex[1], ex[2])
    if ex[1] < 0:
        ex = tuple(-x for x in ex)
    ey = cross(n, ex)
    w, h = KNEE["size"]
    o = frame_pt(c, ex, ey, n, -w / 2 - 1.2, -h / 2 - 1.5, 0.0)
    slab(P, "CK2_Kneeboard", (o, ex, ey, n), 0, 0, w + 2.4, h + 3.6, -0.9, -0.15, None, None, bevel=0.1)
    box(P, "CK2_Metal", frame_pt(c, ex, ey, n, 0.0, h / 2 + 1.2, 0.0), (6.0, 1.0, 0.5), ex, ey, n)
    for sd in (-1, 1):                      # leg strap
        box(P, "CK2_Strap", frame_pt(c, ex, ey, n, sd * (w / 2 + 1.6), 0.0, -1.2), (1.2, 3.6, 2.6), ex, ey, n)
    return dict(center=c, normal=n, up=ey, right=ex, size=list(KNEE["size"]))


# =====================================================================================================================
def to_blender(Pt, origin=(0.0, 0.0, 0.0)):
    me = bpy.data.meshes.new(Pt.name)
    vs = [((x - origin[0]) / 100.0, -(y - origin[1]) / 100.0, (z - origin[2]) / 100.0) for x, y, z in Pt.V]
    faces = [f[::-1] for f in Pt.F]                                # mirror y -> keep outward winding
    me.from_pydata(vs, [], faces)
    uv = me.uv_layers.new(name="UV0")
    k = 0
    for fi, poly in enumerate(me.polygons):
        uvs = Pt.UV[fi][::-1]
        for j, li in enumerate(poly.loop_indices):
            uv.data[li].uv = uvs[j]
        k += 1
    for sl in Pt.slots:
        m = bpy.data.materials.get(sl) or bpy.data.materials.new(sl)
        me.materials.append(m)
    for fi, poly in enumerate(me.polygons):
        poly.material_index = Pt.M[fi]
    me.validate(clean_customdata=False)
    me.update()
    ob = bpy.data.objects.new(Pt.name, me)
    bpy.context.scene.collection.objects.link(ob)
    # smooth shading by angle (keeps hard panel edges)
    for p in me.polygons:
        p.use_smooth = True
    try:
        me.set_sharp_from_angle(angle=math.radians(35.0))
    except Exception:
        pass
    return ob


def tri_count(ob):
    return sum(len(p.vertices) - 2 for p in ob.data.polygons)


PREVIEW = dict(CK2_Plate=None, CK2_Plate0=(0.03, 0.032, 0.034, 0.6), CK2_PlateSide=(0.02, 0.021, 0.022, 0.6), CK2_Paint=(0.055, 0.06, 0.063, 0.55),
               CK2_Well=(0.06, 0.066, 0.07, 0.65), CK2_Wall=(0.085, 0.09, 0.088, 0.6), CK2_Glare=(0.01, 0.01, 0.011, 0.9), CK2_Rubber=(0.012, 0.012, 0.012, 0.8),
               CK2_HUDBody=(0.02, 0.021, 0.022, 0.6), CK2_HUDFrame=(0.03, 0.03, 0.032, 0.4), CK2_Frame=(0.012, 0.012, 0.013, 0.45),
               CK2_Metal=(0.3, 0.3, 0.31, 0.4), CK2_Chrome=(0.7, 0.7, 0.7, 0.18), CK2_Knob=(0.015, 0.015, 0.016, 0.45), CK2_White=(0.8, 0.8, 0.8, 0.5),
               CK2_Bezel=(0.018, 0.018, 0.019, 0.5), CK2_Red=(0.45, 0.03, 0.02, 0.4), CK2_Lens=None, CK2_Lit=None,
               CK2_Screen_L=(0.003, 0.004, 0.005, 0.1), CK2_Screen_R=(0.003, 0.004, 0.005, 0.1), CK2_SeatPaint=(0.09, 0.1, 0.08, 0.6),
               CK2_Fleece=(0.012, 0.012, 0.012, 0.95), CK2_Headrest=(0.12, 0.13, 0.11, 0.9), CK2_Boot=(0.2, 0.21, 0.21, 0.7),
               CK2_Grip=(0.018, 0.018, 0.019, 0.65), CK2_GearKnob=(0.75, 0.75, 0.72, 0.4), CK2_Glass=(0.9, 0.9, 0.9, 0.05),
               CK2_HUDGlass=(0.7, 0.85, 0.75, 0.05), CK2_Kneeboard=(0.04, 0.04, 0.042, 0.6), CK2_Strap=(0.08, 0.09, 0.06, 0.9))


def preview_materials():
    atlas = bpy.data.images.load(os.path.join(TEX, "T_Ck2Atlas.png"), check_existing=True)
    nimg = bpy.data.images.load(os.path.join(TEX, "T_Ck2Normal.png"), check_existing=True)
    nimg.colorspace_settings.name = "Non-Color"
    for m in bpy.data.materials:
        m.use_nodes = True
        nt = m.node_tree
        b = nt.nodes.get("Principled BSDF")
        if b is None:
            continue
        v = PREVIEW.get(m.name, (0.05, 0.05, 0.05, 0.6))
        if m.name.startswith("CK2_LampOn_"):
            col = {"amber": (1.0, 0.5, 0.05), "red": (1.0, 0.08, 0.04), "green": (0.2, 1.0, 0.3)}[m.name.split("_")[-1]]
            b.inputs["Emission Color"].default_value = col + (1.0,)
            b.inputs["Emission Strength"].default_value = 3.0
            continue
        if v is None or m.name in ("CK2_Plate", "CK2_Lens", "CK2_Lit"):
            t = nt.nodes.new("ShaderNodeTexImage")
            t.image = atlas
            nt.links.new(t.outputs["Color"], b.inputs["Base Color"])
            b.inputs["Roughness"].default_value = 0.55 if m.name == "CK2_Plate" else 0.2
            if m.name == "CK2_Lit":
                nt.links.new(t.outputs["Color"], b.inputs["Emission Color"])
                b.inputs["Emission Strength"].default_value = 1.5
            tn = nt.nodes.new("ShaderNodeTexImage")
            tn.image = nimg
            nm = nt.nodes.new("ShaderNodeNormalMap")
            sep = nt.nodes.new("ShaderNodeSeparateColor")
            comb = nt.nodes.new("ShaderNodeCombineColor")
            inv = nt.nodes.new("ShaderNodeMath")
            inv.operation = "SUBTRACT"
            inv.inputs[0].default_value = 1.0
            nt.links.new(tn.outputs["Color"], sep.inputs[0])
            nt.links.new(sep.outputs[1], inv.inputs[1])
            nt.links.new(sep.outputs[0], comb.inputs[0])
            nt.links.new(inv.outputs[0], comb.inputs[1])
            nt.links.new(sep.outputs[2], comb.inputs[2])
            nt.links.new(comb.outputs[0], nm.inputs["Color"])
            nt.links.new(nm.outputs[0], b.inputs["Normal"])
            continue
        b.inputs["Base Color"].default_value = v[:3] + (1.0,)
        b.inputs["Roughness"].default_value = v[3]
        if m.name in ("CK2_Metal", "CK2_Chrome", "CK2_HUDFrame"):
            b.inputs["Metallic"].default_value = 1.0
        if m.name in ("CK2_Glass", "CK2_HUDGlass"):
            b.inputs["Alpha"].default_value = 0.0
            m.surface_render_method = "BLENDED" if hasattr(m, "surface_render_method") else m.blend_method


def bake_masks(ob, res=2048):
    """UV1 = lightmap pack; Cycles CPU bake of an emission shader: R = AO (8 cm), G = convex edge (bevel normal), B = wide
    cavity (AO 30 cm) -> T_Ck2Masks.png"""
    t0 = time.time()
    me = ob.data
    uv1 = me.uv_layers.new(name="UV1")
    me.uv_layers.active = uv1
    bpy.context.view_layer.objects.active = ob
    for o in bpy.context.scene.objects:
        o.select_set(o == ob)
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="SELECT")
    bpy.ops.uv.smart_project(angle_limit=math.radians(60.0), island_margin=0.004, area_weight=0.0, scale_to_bounds=False)
    bpy.ops.uv.pack_islands(margin=0.003, rotate=True)
    bpy.ops.object.mode_set(mode="OBJECT")
    img = bpy.data.images.new("T_Ck2Masks", res, res, alpha=False, float_buffer=False)
    img.colorspace_settings.name = "Non-Color"
    bm = bpy.data.materials.new("CK2_BAKE")
    bm.use_nodes = True
    nt = bm.node_tree
    for n in list(nt.nodes):
        nt.nodes.remove(n)
    outn = nt.nodes.new("ShaderNodeOutputMaterial")
    em = nt.nodes.new("ShaderNodeEmission")
    ao = nt.nodes.new("ShaderNodeAmbientOcclusion")
    ao.samples = 16
    ao.inputs["Distance"].default_value = 0.08
    ao2 = nt.nodes.new("ShaderNodeAmbientOcclusion")
    ao2.samples = 16
    ao2.inputs["Distance"].default_value = 0.30
    bev = nt.nodes.new("ShaderNodeBevel")
    bev.samples = 8
    bev.inputs["Radius"].default_value = 0.004
    geo = nt.nodes.new("ShaderNodeNewGeometry")
    dot = nt.nodes.new("ShaderNodeVectorMath")
    dot.operation = "DOT_PRODUCT"
    edge = nt.nodes.new("ShaderNodeMath")
    edge.operation = "MULTIPLY"
    edge.inputs[1].default_value = 6.0
    one = nt.nodes.new("ShaderNodeMath")
    one.operation = "SUBTRACT"
    one.inputs[0].default_value = 1.0
    comb = nt.nodes.new("ShaderNodeCombineColor")
    tex = nt.nodes.new("ShaderNodeTexImage")
    tex.image = img
    nt.links.new(bev.outputs[0], dot.inputs[0])
    nt.links.new(geo.outputs["Normal"], dot.inputs[1])
    nt.links.new(dot.outputs["Value"], one.inputs[1])
    nt.links.new(one.outputs[0], edge.inputs[0])
    nt.links.new(ao.outputs["AO"], comb.inputs[0])
    nt.links.new(edge.outputs[0], comb.inputs[1])
    nt.links.new(ao2.outputs["AO"], comb.inputs[2])
    nt.links.new(comb.outputs[0], em.inputs[0])
    nt.links.new(em.outputs[0], outn.inputs["Surface"])
    orig = list(me.materials)
    for i in range(len(me.materials)):
        me.materials[i] = bm
    nt.nodes.active = tex
    sc = bpy.context.scene
    sc.render.engine = "CYCLES"
    sc.cycles.device = "CPU"
    sc.cycles.samples = 24
    sc.render.bake.margin = 6
    bpy.ops.object.bake(type="EMIT", uv_layer="UV1")
    for i, m in enumerate(orig):
        me.materials[i] = m
    img.filepath_raw = os.path.join(OUT, "T_Ck2Masks.png")
    img.file_format = "PNG"
    img.save()
    me.uv_layers.active = me.uv_layers["UV0"]
    me.uv_layers["UV0"].active_render = True
    log("masks baked %.1f s" % (time.time() - t0))
    return round(time.time() - t0, 1)


def export(ob, path):
    bpy.ops.object.select_all(action="DESELECT")
    ob.select_set(True)
    bpy.context.view_layer.objects.active = ob
    bpy.ops.export_scene.fbx(filepath=path, use_selection=True, axis_forward="X", axis_up="Z", apply_unit_scale=True, global_scale=1.0,
                             apply_scale_options="FBX_SCALE_NONE", bake_space_transform=True, mesh_smooth_type="FACE", use_mesh_modifiers=True,
                             use_tspace=True, add_leaf_bones=False, object_types={"MESH"}, path_mode="STRIP")


def render_previews(objs):
    """EEVEE stills from the eye point (Blender only, a quick look before Unreal)"""
    sc = bpy.context.scene
    sc.render.engine = "BLENDER_EEVEE_NEXT" if "BLENDER_EEVEE_NEXT" in [e.identifier for e in bpy.types.RenderSettings.bl_rna.properties["engine"].enum_items] else "BLENDER_EEVEE"
    sc.render.resolution_x, sc.render.resolution_y = 1600, 900
    w = bpy.data.worlds.new("w")
    w.use_nodes = True
    w.node_tree.nodes["Background"].inputs[0].default_value = (0.6, 0.7, 0.85, 1.0)
    w.node_tree.nodes["Background"].inputs[1].default_value = 1.0
    sc.world = w
    sun = bpy.data.objects.new("sun", bpy.data.lights.new("sun", "SUN"))
    sun.data.energy = 4.0
    sun.rotation_euler = (math.radians(40), math.radians(-25), math.radians(200))
    sc.collection.objects.link(sun)
    cam = bpy.data.objects.new("cam", bpy.data.cameras.new("cam"))
    sc.collection.objects.link(cam)
    sc.camera = cam
    shots = {"eye": ((430, 0, 100), (520, 0, 52), 75), "panel": ((452, 0, 82), (510, 0, 47), 55), "left": ((440, -8, 92), (450, -36, 40), 70),
             "right": ((440, 8, 92), (450, 36, 40), 70)}
    for k, (e, t, fov) in shots.items():
        eb = V((e[0] / 100, -e[1] / 100, e[2] / 100))
        tb = V((t[0] / 100, -t[1] / 100, t[2] / 100))
        cam.location = eb
        cam.rotation_euler = (tb - eb).to_track_quat("-Z", "Y").to_euler()
        cam.data.angle = math.radians(fov)
        cam.data.clip_start = 0.01
        sc.render.filepath = os.path.join(r"C:\GyroSimTiles\assets\cockpit\preview", "bl_%s.png" % k)
        bpy.ops.render.render(write_still=True)
    log("previews rendered")


# =====================================================================================================================
def main():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    build_panel_structure()
    build_glareshield()
    build_consoles()
    build_tub()
    build_seat()
    spv = build_stick()
    tpv = build_throttle()
    gpv = build_gearhandle()
    lights = build_lit()
    knee = build_kneeboard()
    origins = {"ck2_stick": spv, "ck2_throttle": tpv, "ck2_gearhandle": gpv}
    obs, tris = {}, {}
    for n, P in PARTS.items():
        ob = to_blender(P, origins.get(n, (0.0, 0.0, 0.0)))
        obs[n] = ob
        tris[n] = tri_count(ob)
    log("tris", tris, "total", sum(tris.values()))
    bake_s = None
    if "--no-bake" not in ARGV:
        bake_s = bake_masks(obs[SH])
    preview_materials()
    for n, ob in obs.items():
        export(ob, os.path.join(OUT, n + ".fbx"))
    for n, o in origins.items():            # previews / .blend: pivoted parts back in place
        obs[n].location = (o[0] / 100.0, -o[1] / 100.0, o[2] / 100.0)
    obs["ck2_glass"].hide_render = True
    bpy.ops.wm.save_as_mainfile(filepath=r"C:\GyroSimTiles\assets\cockpit\blend\cockpit_v2.blend")
    # manifest (UE body cm)
    PN, PU = L.PANEL_N, L.PANEL_UP
    needles = {}
    for nm, g in (("asi", "ASI"), ("alt", "ALT")):
        u, v, d = L.GAUGES[g][:3]
        needles[nm] = dict(center=L.panel_pt(u, v, PLATES["C_TOP"]["raise_"] + 0.42), x_axis=PN, z_axis=PU, scale=round(d / 7.2, 3))
    needles["alt10k"] = dict(needles["alt"], center=L.panel_pt(L.GAUGES["ALT"][0], L.GAUGES["ALT"][1], PLATES["C_TOP"]["raise_"] + 0.5))
    u, v, d = L.VVI_ROUND
    needles["vsi"] = dict(center=L.panel_pt(u, v, PLATES["C_MID"]["raise_"] + 0.42), x_axis=PN, z_axis=PU, scale=round(d / 7.2, 3))
    screens = {}
    for s, tag in ((-1, "MFD_L"), (1, "MFD_R")):
        screens[tag] = dict(center=L.panel_pt(s * L.MFD_U, L.MFD_V, L.MFD_DEPTH - 0.55 + 0.06), normal=PN, up=PU, size=[L.MFD_SCREEN, L.MFD_SCREEN], px=[1024, 1024])
    screens["MFD_C"] = dict(center=L.add(knee["center"], knee["normal"], 0.05), normal=knee["normal"], up=knee["up"], size=knee["size"], px=[1280, 800],
                            where="kneeboard")
    cal = {"adi": L.panel_pt(0.0, 33.9, 1.0), "asi": L.panel_pt(-5.6, 52.7, 1.0), "alt": L.panel_pt(5.6, 52.7, 1.0), "vsi": L.panel_pt(8.6, 34.6, 1.0),
           "gear": plate_point("AUX_L", 14.0, 13.0, 1.0)[0], "wheels": plate_point("AUX_L", 19.5, 15.8, 1.0)[0], "lights": plate_point("AUX_L", 5.6, 7.4, 1.0)[0]}
    man = dict(made=time.strftime("%Y-%m-%d %H:%M:%S"), frame="UE body cm, X fwd, Y right, Z up; eye (430, 0, 100)", version="cockpit v2 (F-16 Block 50/52 style)",
               parts={n: dict(fbx=n + ".fbx", tris=tris[n], origin=list(origins.get(n, (0, 0, 0))), slots=PARTS[n].slots) for n in PARTS},
               pivots=dict(StickPivot=list(spv), ThrottlePivot=list(tpv), GearHandle=list(gpv),
                           ADIBall=dict(center=L.panel_pt(0.0, 38.6, -0.6), x_axis=[-1.0, 0.0, 0.0], z_axis=[0.0, 0.0, 1.0])),
               needles=needles, screens=screens, lights=lights, gearlights="ck2_gearlights",
               callouts={k: dict(center=v, normal=(PN if k not in ("gear", "wheels", "lights") else (0.0, 0.0, 1.0))) for k, v in cal.items()}, hud_combiner=L.HUD, kneeboard=knee,
               tris_total=sum(tris.values()), bake_seconds=bake_s,
               inputs=dict(layout="Scripts/cockpit_blender/ck2_layout.py", atlas=os.path.join(TEX, "T_Ck2Atlas.png"), refs=r"C:\GyroSimTiles\refs\f16_cockpit"))
    json.dump(man, open(os.path.join(OUT, "manifest.json"), "w"), indent=1, default=list)
    log("exported", sorted(obs), "->", OUT, "%.1f s" % (time.time() - T0))
    if "--render" in ARGV:
        render_previews(obs)


main()
