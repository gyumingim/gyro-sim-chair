"""Ergonomic grips for the gyro-chair centre stick (right hand) and throttle (left hand), sizes S / M / L.

Run:   python grips.py            -> all sizes      python grips.py M     -> one size
Out:   stl/<size>/*.stl, parts.json (all sizes), section/strength numbers printed + stored in parts.json

Grip frame (mm): origin = centre of the grip bottom face (= socket mouth), z up along the mounting tube,
x forward, y left (same as stick.py / throttle.py). Both grips mount on the same interface (see INTERFACE.md):
Ø20 aluminium tube, 40 mm inside the grip, M4 cross bolt along y at z = 25 (15 mm below the tube top end),
anti-rotation key = rib at the rear of the socket top that sits in a 4 x 6 mm notch sawn into the tube end.

Shape: lofted closed-spline cross-sections along a spine that is vertical in the neck and cants forward above the
pinky flange. Sections carry a palm swell (rear, palm side), shallow finger ridges (front, finger side) and a thumb rest.
Sizes scale the hand part by hand length (circumference ~ 64 % of hand length, see docs/grips.html for sources);
the mounting interface and the switch pockets do not scale.
Shells split on the y = 0 plane -> left / right halves, printed flat on the split face. Cavity roof is a 45 deg gable
(no support inside). Halves join with M3 x 12 socket screws (from the left) into M3 heat-set inserts (right half).
"""
import json, math, os, sys
from datetime import datetime
import numpy as np
from scipy.interpolate import PchipInterpolator
from OCP.BRepOffsetAPI import BRepOffsetAPI_ThruSections
from OCP.Approx import Approx_ParametrizationType
from build123d import (Box, Cylinder, Pos, Rot, Plane, Edge, Wire, Solid, Face, Vector, Location, export_stl, Axis,
                       Compound, extrude)

HERE = os.path.dirname(os.path.abspath(__file__))

# ---------------- hand data (mm) ----------------
# hand length (wrist crease -> middle fingertip) / hand breadth (at metacarpals).
# Korean 18-39 y means (KATS 2008 hand survey, via Kee 2010): male 184.7 / 85.2, female 170.6 / 76.3.
SIZES = {
    "S": dict(HL=168, HB=78, who="여성 평균 전후 · 작은 손 (손 길이 ≲ 176)"),
    "M": dict(HL=182, HB=85, who="남성 평균 전후 (손 길이 176~190)"),
    "L": dict(HL=196, HB=91, who="큰 손 (손 길이 ≳ 190, 남성 약 90~95 백분위 추정)"),
}

# ---------------- fixed interface ----------------
TUBE_D, TUBE_ID, TUBE_IN = 20.0, 16.0, 40.0
SOCKET_D = 20.4
BOLT_Z, BOLT_D, BOLT_HEAD_D, NUT_AF = 25.0, 4.4, 8.6, 7.3     # M4 x 30 button head + M4 nut
BOLT_SEAT = 13.0                                                # head seat at y=+13, nut seat at y=-13
KEY_W, KEY_H = 3.8, 6.0                                        # rib at the rear of the socket top
WALL = 3.0                                                      # section offset; >= 2.2 normal wall incl. ridge grooves
M3_CLR, M3_CB, INSERT_D, INSERT_L = 3.4, 6.4, 4.0, 6.5          # M3 x 12 SHCS, insert M3 x 5.7 (OD ~4.6)
SCREW_SEAT = 7.0                                                # M3 x 12: head seat y=+7 -> tip y=-5
NECK_TOP, FLANGE = 40.0, 42.0                                   # neck (tube inside) ends at 40
NECK_LOFT = 30.0                                                # straight prism below; seam above the M4 bolt/nut seats (z <= 29.3)
SEAM = math.radians(4)                                          # spline seam just off the y = 0 split plane (split along a seam fails)
CAV0 = 46.5                                                     # cavity floor: above the waist over the pinky shelf (2 mm wall)


def loft(wires):
    """smooth loft through closed sections. Centripetal parametrisation: the default (uniform) one makes the
    interpolating B-spline surface overshoot by metres between unevenly sized sections (old bug: 3 solids)."""
    b = BRepOffsetAPI_ThruSections(True, False, 1e-6)
    b.CheckCompatibility(False)
    b.SetParType(Approx_ParametrizationType.Approx_Centripetal)
    for w in wires: b.AddWire(w.wrapped)
    b.Build()
    return Solid(b.Shape())


def bop(kind, a, tools, fuzzy=1e-3):
    """OCCT boolean (cut/fuse/common) with a fuzzy value: near-tangent switch pockets on the curved skin
    otherwise make the plain boolean return an inside-out solid (volume grows on a cut)."""
    from OCP.BRepAlgoAPI import BRepAlgoAPI_Cut, BRepAlgoAPI_Fuse, BRepAlgoAPI_Common
    from OCP.TopTools import TopTools_ListOfShape
    op = dict(cut=BRepAlgoAPI_Cut, fuse=BRepAlgoAPI_Fuse, common=BRepAlgoAPI_Common)[kind]()
    la, lt = TopTools_ListOfShape(), TopTools_ListOfShape()
    la.Append(a.wrapped)
    for t in tools: lt.Append(t.wrapped)
    op.SetArguments(la); op.SetTools(lt); op.SetFuzzyValue(fuzzy); op.SetRunParallel(True)
    op.Build()
    if not op.IsDone(): raise RuntimeError(kind + " failed")
    sh = Compound(op.Shape())
    ss = sh.solids()
    return ss[0] if len(ss) == 1 else sh


def stl_check(path):
    """closed-mesh check of an exported STL: (volume mm3, open edges, non-manifold edges)."""
    import struct
    with open(path, "rb") as f:
        data = f.read()
    if data[:5].lower() == b"solid" and b"facet" in data[:400]:
        v = [tuple(map(float, l.split()[1:4])) for l in data.decode(errors="ignore").splitlines() if l.strip().startswith("vertex")]
        T = np.array(v).reshape(-1, 3, 3)
    else:
        n = struct.unpack("<I", data[80:84])[0]
        T = np.frombuffer(data[84:84 + n * 50], dtype=np.dtype([("n", "<3f4"), ("v", "<9f4"), ("a", "<u2")]))["v"].reshape(-1, 3, 3).astype(float)
    vol = float(np.einsum("ij,ij->i", T[:, 0], np.cross(T[:, 1], T[:, 2])).sum() / 6)
    key = T.reshape(-1, 3)                              # float32 vertices: shared ones are bit-identical
    _, idx = np.unique(key, axis=0, return_inverse=True)
    idx = idx.reshape(-1, 3)
    e = np.sort(np.concatenate([idx[:, [0, 1]], idx[:, [1, 2]], idx[:, [2, 0]]]), axis=1)
    _, cnt = np.unique(e, axis=0, return_counts=True)
    return vol, int((cnt == 1).sum()), int((cnt > 2).sum())


def smooth(t):
    t = min(max(t, 0.0), 1.0)
    return t * t * (3 - 2 * t)


class Grip:
    """One grip (kind 'stick' or 'throttle') for one size. hand = +1 right hand, -1 left hand (mirror in y)."""

    def __init__(self, kind, size):
        self.kind, self.size = kind, size
        hs = SIZES[size]
        self.HL, self.HB = hs["HL"], hs["HB"]
        self.k = self.HL / 182.0
        self.p = self.HB / 4.4                       # finger pitch along the grip
        # geometry is always built right-handed (thumb on +y) and the throttle is mirrored at the end: lofting the
        # mirrored (clockwise) sections gave inside-out pieces in the booleans
        self.hand = 1
        self.mirror = kind == "throttle"
        self.cant = 12.0 if kind == "stick" else 8.0
        k, p = self.k, self.p
        if kind == "stick":
            mid = (19.0 * k, 20.0 * k, 16.0 * k, 16.5 * k)    # af, ar, b_thumb(finger tips) side, b_palm side
            head = (22.5 * k, 21.0 * k, 18.5 * k, 18.0 * k)
            self.head_len = 28 * k
        else:
            mid = (19.5 * k, 21.5 * k, 16.5 * k, 18.0 * k)
            head = (23.5 * k, 22.5 * k, 19.5 * k, 20.0 * k)
            self.head_len = 30 * k
        self.s_hand0 = FLANGE                               # top of pinky flange
        self.s_head = FLANGE + 4 * p
        self.s_top = self.s_head + self.head_len
        self.s_trig = FLANGE + 3.5 * p
        f = tuple(v + 4.5 for v in mid)
        tab = [(0, 16.5, 16.5, 17.0, 17.0), (30, 16.5, 16.5, 17.0, 17.0),
               (35.5, f[0] - 1.5, f[1] - 1.5, f[2] - 1.5, f[3] - 1.5), (38.5, *f), (41.5, f[0] - 1.2, f[1] - 1.2, f[2] - 1.2, f[3] - 1.2),
               (45.5, mid[0] - 0.4, mid[1] - 0.5, mid[2] - 0.4, mid[3] - 0.5),
               (FLANGE + 2 * p, *mid),
               (FLANGE + 3.3 * p, mid[0] + 0.3, mid[1] - 0.3, mid[2] + 0.2, mid[3]),
               (self.s_head, (mid[0] + head[0]) / 2 + 0.6, (mid[1] + head[1]) / 2, (mid[2] + head[2]) / 2, (mid[3] + head[3]) / 2),
               (self.s_head + 10 * k, *head),
               (self.s_top - 9 * k, head[0] - 1.0, head[1] - 3.5, head[2] - 1.2, head[3] - 1.5)]
        self.tab = np.array(tab)
        self.pchip = [PchipInterpolator(self.tab[:, 0], self.tab[:, c]) for c in range(1, 5)]
        # dome: super-elliptic cap above s_dome (rear falls faster -> top slopes back to the thumb)
        self.s_dome, self.h_dome = self.s_top - 9 * k, 9 * k
        self.q_dome = (2.0, 1.5, 2.0, 1.8)
        self.phi_end = math.radians(80)                 # last section: small flat (~7 x 5) well inside the hat recess

    # ---------- spine ----------
    def tilt(self, s):                      # forward cant (deg) of the section plane
        return self.cant * smooth((s - 44) / 26)

    def frame(self, s):
        """spine point and axes at arc length s: origin, xdir (forward in section), zdir (tangent)."""
        n = max(int(s / 1.0), 1)
        x = z = 0.0
        ds = s / n
        for i in range(n):
            t = math.radians(self.tilt((i + 0.5) * ds))
            x += ds * math.sin(t); z += ds * math.cos(t)
        t = math.radians(self.tilt(s))
        return Vector(x, 0, z), Vector(math.cos(t), 0, -math.sin(t)), Vector(math.sin(t), 0, math.cos(t))

    def loc(self, u, v, s):                 # local (u fore-aft, v side, s along spine) -> Plane
        o, xd, zd = self.frame(s)
        return Plane(o + xd * u + Vector(0, v, 0), x_dir=xd, z_dir=zd)

    def pt(self, u, v, s):
        o, xd, zd = self.frame(s)
        return o + xd * u + Vector(0, v, 0)

    # ---------- section shape ----------
    def semi(self, s):
        if s <= self.s_dome:
            return [float(f(s)) for f in self.pchip]
        t = min((s - self.s_dome) / self.h_dome, 1.0)
        base = [float(f(self.s_dome)) for f in self.pchip]
        return [b * max(1 - t ** q, 0.0) ** (1 / q) for b, q in zip(base, self.q_dome)]

    def bumps(self, s, th):
        """radial offset (mm) at section s, angle th (rad, 0 = forward, + toward the finger-tip side)."""
        k, p = self.k, self.p
        def g(a, a0, w):
            d = math.atan2(math.sin(a - a0), math.cos(a - a0))
            return math.exp(-(d / w) ** 2)
        r = 0.0
        # palm swell: rear, palm side (-135 deg), peak at ~1.8 p above the flange
        amp = (2.6 if self.kind == "stick" else 2.2) * k
        r += amp * math.exp(-((s - (FLANGE + 1.8 * p)) / (1.0 * p)) ** 2) * g(th, math.radians(-140), math.radians(50))
        # finger ridges: front / finger-tip side, crests between fingers (1.5 mm crest-to-groove), faded at ends
        a0, a1 = FLANGE + 0.55 * p, FLANGE + 3.15 * p
        if a0 < s < a1:
            win = smooth((s - a0) / (0.35 * p)) * smooth((a1 - s) / (0.35 * p))
            amp_r = 0.75 if self.kind == "stick" else 0.55
            r += amp_r * math.cos(2 * math.pi * (s - (FLANGE + p)) / p) * win * g(th, math.radians(25), math.radians(65))
        # thumb rest: ledge on the thumb side just below the head
        r += 2.8 * k * math.exp(-((s - (self.s_head - 0.25 * p)) / 4.0) ** 2) * g(th, math.radians(100), math.radians(32))
        return r

    def sec_pts(self, s, inner=False, n=24):
        af, ar, bt, bp = self.semi(s)
        if inner:
            af, ar, bt, bp = (max(v - WALL, 3.0) for v in (af, ar, bt, bp))
        pts = []
        u0 = (af - ar) / 2
        R = 0.97 * math.hypot((af + ar) / 2, max(bt, bp))
        for i in range(n):
            th = SEAM + 2 * math.pi * i / n                # spline seam off the y = 0 split plane
            c, sn = math.cos(th), math.sin(th)
            x = c * (af if c >= 0 else ar)
            y = sn * (bt if sn >= 0 else bp)
            if not inner:
                rr = math.hypot(x, y)
                d = self.bumps(s, th)
                x, y = x * (rr + d) / rr, y * (rr + d) / rr
            else:
                lim = R - abs(x - u0)                       # 45 deg gable roof -> printable without support
                if abs(y) > lim:
                    y = math.copysign(max(lim, 0.5), y)
            pts.append((x, y * self.hand))
        return pts

    def wire(self, s, inner=False, scale=1.0):
        o, xd, zd = self.frame(s)
        P = [o + xd * (x * scale) + Vector(0, y * scale, 0) for x, y in self.sec_pts(s, inner)]
        return Wire([Edge.make_spline(P, periodic=True)])

    def stations(self, step=3.0):
        """even stations (~3 mm, ~6 per finger pitch) up to the dome, then equal meridian-angle steps over the cap."""
        st = [NECK_LOFT, 31.0, 32.0, 33.0, 34.0, 35.5, 37.0, 38.5, 40.0, 41.5, 43.5, 45.5]   # pinky flange: dense, on the table rows
        n = int(round((self.s_dome - 48.0) / step))
        st += [float(v) for v in np.linspace(48.0, self.s_dome, n + 1)]
        st += [self.s_dome + self.h_dome * math.sin(f) for f in np.linspace(0, self.phi_end, 7)[1:]]
        self.s_end = st[-1]
        return st

    # ---------- features ----------
    def surface_hit(self, solid, a, d):
        """point on the outer surface along ray a + t d (a inside)."""
        d = d.normalized(); lo, hi = 0.0, 80.0
        for _ in range(40):
            m = (lo + hi) / 2
            if solid.is_inside(a + d * m): lo = m
            else: hi = m
        return a + d * lo

    def build(self):
        k, p, h = self.k, self.p, self.hand
        st = self.stations()
        # straight neck = prism (a loft through identical sections ripples by mm). It is 0.05 mm smaller than the
        # loft's first section and reaches 3 mm into it, so the fuse has no coincident faces (exact touch failed).
        w0 = self.wire(0.0, scale=1 - 0.05 / 17)
        neck = extrude(Face(w0), NECK_LOFT + 3, dir=(0, 0, 1))
        outer = bop("fuse", loft([self.wire(s) for s in st]), [neck]).clean()
        st0 = [0.0] + st                                # sanity: loft volume vs. section areas (catches overshoot)
        ar = [Face(self.wire(s)).area for s in st0]
        est = sum((ar[i] + ar[i + 1]) / 2 * (st0[i + 1] - st0[i]) for i in range(len(st0) - 1))
        if abs(outer.volume / est - 1) > 0.01 or outer.bounding_box().min.Z < -0.05 or len(outer.solids()) != 1:
            raise RuntimeError(f"outer loft off: {outer.volume:.0f} vs {est:.0f} mm3")
        s_in1 = self.s_dome - 2.0                       # cavity ends under the dome: dome stays solid (>= 2.5 mm wall)
        ist = [float(v) for v in np.linspace(CAV0, s_in1, int(round((s_in1 - CAV0) / 3.0)) + 1)]
        inner = loft([self.wire(s, inner=True) for s in ist])
        from OCP.BRepExtrema import BRepExtrema_DistShapeShape
        dd = BRepExtrema_DistShapeShape(Compound(outer.faces()).wrapped, Compound(inner.faces()).wrapped)
        self.min_wall = round(dd.Value(), 2)
        print(f"   outer {outer.volume / 1000:.1f} cm3, inner {inner.volume / 1000:.1f} cm3, min wall {self.min_wall} mm", flush=True)
        if (inner - outer).volume > 1.0 or self.min_wall < 2.0: raise RuntimeError("cavity breaks the skin")
        self.outer = outer
        add, cut, buy, labels = [], [], {}, []

        # --- socket, key, cable hole, M4 cross bolt
        cut.append(Pos(0, 0, TUBE_IN / 2 - 0.5) * Cylinder(SOCKET_D / 2, TUBE_IN + 1))
        cut.append(Pos(0, 0, (TUBE_IN + CAV0 + 1) / 2) * Cylinder(6.5, CAV0 + 1 - TUBE_IN))     # cable hole into the cavity
        key = Pos(-(SOCKET_D / 2 + 0.25) + 1.6, 0, TUBE_IN - KEY_H / 2) * Box(3.2, KEY_W, KEY_H)
        bolt = Pos(0, 0, BOLT_Z) * Rot(90, 0, 0) * Cylinder(BOLT_D / 2, 60)
        cut.append(bolt)
        cut.append(Pos(0, BOLT_SEAT + 10, BOLT_Z) * Rot(90, 0, 0) * Cylinder(BOLT_HEAD_D / 2, 20))
        nut = None
        for a in (0, 60, 120):
            b = Pos(0, -(BOLT_SEAT + 10), BOLT_Z) * Rot(0, a, 0) * Box(NUT_AF, 20, NUT_AF * 2)
            nut = b if nut is None else nut & b
        cut.append(nut)
        buy["tube"] = Pos(0, 0, (TUBE_IN - 70) / 2) * (Cylinder(TUBE_D / 2, TUBE_IN + 70) - Cylinder(TUBE_ID / 2, TUBE_IN + 72)) \
            - (Pos(-9, 0, TUBE_IN - KEY_H / 2 + 0.01) * Box(4, KEY_W + 0.2, KEY_H))
        buy["m4_bolt"] = Pos(0, 0, BOLT_Z) * Rot(90, 0, 0) * Cylinder(2, 30) + Pos(0, BOLT_SEAT + 1.1, BOLT_Z) * Rot(90, 0, 0) * Cylinder(3.8, 2.2)

        # --- M3 joining screws (local u, s); screw from the left (+y) half, insert in the right half
        o_, xd_, zd_ = self.frame(FLANGE)
        bosses = [(17.0 * (1 if True else 0), 37.0), (-17.5, 37.0)]
        uF = self.semi(FLANGE + 2.3 * p)[0]
        uR = self.semi(self.s_head + 2)[1]
        bosses_cav = [(uF - 5.8, FLANGE + 2.3 * p), (-(uR - 6.2), self.s_head + 2)]
        self.screws = []
        for u, s in bosses + bosses_cav:
            pl = self.loc(u, 0, s)
            if (u, s) in bosses_cav:
                add.append(pl.location * Pos(0, 0, 0) * Rot(90, 0, 0) * Cylinder(4.2, 60))   # boss across (clipped)
            self.screws.append((u, s))
        self.boss_clip = [self.loc(u, 0, s).location * Rot(90, 0, 0) * Cylinder(4.2, 60) for u, s in bosses_cav]
        screw_cuts = []
        for u, s in bosses + bosses_cav:
            L = self.loc(u, 0, s).location
            screw_cuts.append(L * Pos(0, SCREW_SEAT / 2, 0) * Rot(90, 0, 0) * Cylinder(M3_CLR / 2, SCREW_SEAT + 0.02))
            screw_cuts.append(L * Pos(0, SCREW_SEAT + 15, 0) * Rot(90, 0, 0) * Cylinder(M3_CB / 2, 30))
            screw_cuts.append(L * Pos(0, -INSERT_L / 2, 0) * Rot(90, 0, 0) * Cylinder(INSERT_D / 2, INSERT_L))
            screw_cuts.append(L * Pos(0, -INSERT_L - 1.5, 0) * Rot(90, 0, 0) * Cylinder(1.4, 3))

        # --- PCF8574 module (placeholder 40 x 20 x 7, PCB plane = side plane, against the rear)
        s_pcb = FLANGE + 0.9 * p + 8                    # board bottom; +8 clears the pinky switch body (was 25 mm3 overlap)
        af, ar, bt, bp = self.semi(s_pcb + 20)
        u0 = ((af - WALL) - (ar - WALL)) / 2
        R = 0.97 * math.hypot(((af + ar) / 2 - WALL), max(bt, bp) - WALL)
        u_hi = u0 - (R - 10.6) + 7                      # inner gable leaves 2 x 10.6 width over the board depth
        buy["pcf8574"] = self.loc(u_hi - 2.4, 0, s_pcb + 20).location * Box(7, 20, 40)

        # --- switches
        sw = []
        if self.kind == "stick":
            # trigger lever (index finger) with a 12 mm tact behind it
            self.trigger(add, cut, buy, labels)
            sw.append(dict(name="hat_trim", type="hat", aim=(-2 * k, 3 * k * h, self.s_top - 10 * k), d=(-0.22, 0.2 * h, 1),
                           label="트림 햇 (엄지)", pin="P4-P7"))
            sw.append(dict(name="btn_pickle", type="tact", aim=(9 * k if k >= 1 else 9 + (1 - k) * 25, 2 * k * h,   # S: forward, clear of the hat
                            self.s_top - 12 * k), d=(0.6, 0.35 * h, 1),
                           label="엄지 버튼 1 (무장 발사)", pin="P1"))
            sw.append(dict(name="btn_thumb2", type="tact", aim=(-1 * k, 2 * h, self.s_top - 22 * k), d=(-0.15, 1 * h, 0.35),
                           label="엄지 버튼 2 (시점/기타)", pin="P2"))
            sw.append(dict(name="btn_pinky", type="tact", aim=(4, 2 * h, FLANGE + 0.62 * p + 4), d=(1, 0.65 * h, -0.05),
                           label="새끼 버튼 (자동조종 해제/시점)", pin="P3"))
        else:
            sw.append(dict(name="hat_cursor", type="hat", aim=(-2 * k, 3 * k * h, self.s_top - 10 * k), d=(-0.22, 0.2 * h, 1),
                           label="커서 햇 (엄지)", pin="P4-P7"))
            sw.append(dict(name="btn_talk", type="tact", aim=(9 * k if k >= 1 else 9 + (1 - k) * 25, 2 * k * h, self.s_top - 12 * k), d=(0.6, 0.35 * h, 1),
                           label="무전 버튼 (엄지)", pin="P3"))
            sw.append(dict(name="sw_speedbrake", type="toggle", aim=(0, 2 * h, self.s_top - 23 * k), d=(-0.1, 1 * h, 0.3),
                           label="스피드 브레이크 (엄지, 앞=펼침/뒤=접음)", pin="P1/P2"))
            sw.append(dict(name="btn_index", type="tact", aim=(4, -1 * h, self.s_trig), d=(1, -0.35 * h, 0.0),
                           label="검지 버튼 (언케이지/기타)", pin="P0"))
        for w in sw:
            self.switch(w, add, cut, buy, labels)

        import time
        t0 = time.time()
        DBG = os.environ.get("GRIP_DBG")
        def ok(sh, ref, lo=None, hi=None):
            try:
                v = sh.volume
                good = sh.is_valid and len(sh.solids()) == 1 and v > 0.5 * ref
                return good and (lo is None or v >= lo - 0.5) and (hi is None or v <= hi + 0.5)
            except Exception:
                return False
        def rep(tag):
            if DBG:
                bb = shell.bounding_box()
                print(f"   [{tag}] solids {len(shell.solids())} vol {shell.volume:.0f} y {bb.min.Y:.1f}..{bb.max.Y:.1f} z {bb.max.Z:.1f}", flush=True)
        TRIES = [(0.0, None), (1e-4, None), (1e-3, None), (0.0, (0.013, 0.011, 0.017)), (1e-3, (0.021, -0.017, 0.013)),
                 (1e-2, (-0.031, 0.023, -0.019))]
        def robust(kind, base, tools, tag):
            """boolean that must keep ONE valid solid; a cut may not add volume, a fuse may not lose any.
            Retries with fuzzy values / a few-micron tool shift (spline-skin booleans are touchy)."""
            v0 = base.volume
            lo, hi = (None, v0) if kind == "cut" else (v0, None)
            for fz, mv in TRIES:
                tl = tools if mv is None else [Pos(*mv) * t for t in tools]
                try:
                    r = bop(kind, base, tl, fuzzy=fz)
                except Exception:
                    continue
                if ok(r, v0, lo, hi):
                    if (fz, mv) != TRIES[0]: print(f"     {tag}: ok with fuzzy {fz} shift {mv}", flush=True)
                    return r
            return None
        # bosses / housings: subtract them from the cavity, then hollow the outer once. (Fusing skin-clipped bosses
        # into the shell puts coincident spline faces into the boolean and fails at random.)
        cav = None
        for fz, mv in TRIES[:3]:
            try:
                c = bop("cut", inner, add, fuzzy=fz)
                if c.is_valid and c.volume <= inner.volume + 0.5 and c.volume > 0.3 * inner.volume:
                    cav = c; break
            except Exception:
                pass
        if cav is None: raise RuntimeError("cavity - bosses failed")
        r = robust("cut", outer, [cav], "hollow")
        if r is None: raise RuntimeError("hollow failed")
        shell = r
        rep("added")
        t1 = time.time()
        cuts = cut + screw_cuts
        r = robust("cut", shell, cuts, "fused cut")
        if r is not None:
            shell = r
        else:
            print("     fused cut failed -> one by one", flush=True)
            for i, c in enumerate(cuts):
                r = robust("cut", shell, [c], f"cut {i}")
                if r is None: raise RuntimeError(f"cut {i} failed")
                shell = r
                rep(f"cut{i}")
        shell = robust("fuse", shell, [bop("common", key, [outer])], "key") or shell + (key & outer)
        if not ok(shell, 1): raise RuntimeError(f"shell is {len(shell.solids())} solids / invalid")
        if isinstance(shell, Compound) or not hasattr(shell, "solids"):
            pass
        print(f"   booleans {t1 - t0:.0f}+{time.time() - t1:.0f} s, solids {len(shell.solids())}")
        self.shell, self.buy, self.labels = shell, buy, labels
        big = 400
        for fz, dy in ((0.0, 0.0), (1e-4, 0.0), (1e-3, 0.0), (0.0, 0.003), (1e-3, -0.003)):
            try:
                L_ = bop("common", shell, [Pos(0, big / 2 + dy, big / 2 - 50) * Box(big, big, big)], fuzzy=fz)
                R_ = bop("common", shell, [Pos(0, -big / 2 + dy, big / 2 - 50) * Box(big, big, big)], fuzzy=fz)
                vl, vr = L_.volume, R_.volume
                nl, nr = len(L_.solids()), len(R_.solids())
            except Exception:
                continue
            print(f"   halves: left {nl} solid {vl / 1000:.1f} cm3, right {nr} solid {vr / 1000:.1f} cm3, sum/shell {(vl + vr) / shell.volume:.4f}", flush=True)
            if nl == 1 and nr == 1 and L_.is_valid and R_.is_valid and 0.95 < (vl + vr) / shell.volume < 1.05:
                break             # each half is checked again as a closed mesh after export
        else:
            raise RuntimeError("bad halves")
        self.left, self.right = L_, R_
        if self.mirror:
            M = lambda s: s.mirror(Plane.XZ)
            self.shell, self.outer = M(self.shell), M(self.outer)
            self.left, self.right = M(R_), M(L_)
            self.buy = {n: M(s) for n, s in self.buy.items()}
            self.hat_cap = M(self.hat_cap)
            for L in self.labels:
                L["pos"][1] = -L["pos"][1]; L["normal"][1] = -L["normal"][1]
        return self

    def switch(self, w, add, cut, buy, labels):
        a = self.pt(*w["aim"])
        o, xd, zd = self.frame(w["aim"][2])
        dv = Vector(*w["d"])
        d = (xd * dv.X + Vector(0, dv.Y, 0) + zd * dv.Z).normalized()
        S = self.surface_hit(self.outer, a, d)
        pl = Plane(S, x_dir=(Vector(0, 0, 1).cross(d) if abs(d.Z) < 0.9 else Vector(1, 0, 0)), z_dir=-d)   # z = inward
        L = pl.location
        t = w["type"]
        if t == "tact":                     # 12 x 12 x 7.3 tact + round cap, inserted from outside, legs through the backstop
            D = 9.6
            add.append(L * Pos(0, 0, 6.5) * Cylinder(10.0, 13))
            cut.append(L * Pos(0, 0, D / 2 - 3) * Box(12.4, 12.4, D + 6))
            for x in (-6.25, 6.25):
                cut.append(L * Pos(x, 0, D + 2) * Box(1.9, 8.0, 4.2))
            buy[w["name"]] = L * (Pos(0, 0, D - 1.9) * Box(12, 12, 3.8) + Pos(0, 0, D - 3.8 - 3.0) * Cylinder(5.75, 6.0))
        elif t == "hat":                    # 10 x 10 THT 5-way switch, printed cap in an Ø17 recess
            D = 9.0
            add.append(L * Pos(0, 0, 6) * Cylinder(9.5, 12))
            cut.append(L * Pos(0, 0, -1) * Cylinder(8.6, 6.0))           # cap recess (2 mm deep)
            cut.append(L * Pos(0, 0, D / 2 - 1) * Box(10.4, 10.4, D + 2))
            cut.append(L * Pos(0, 0, D + 2) * Box(8.0, 8.0, 4.2))
            buy[w["name"]] = L * Pos(0, 0, D - 2.5) * Box(10, 10, 5)
            cap = L * (Pos(0, 0, -0.6) * Cylinder(7.3, 3.2) - Pos(0, 0, 0.6) * Cylinder(1.8, 3.0))
            for ang in range(0, 360, 90):
                cap = cap + L * Rot(0, 0, ang) * Pos(4.6, 0, -2.6) * Rot(0, 0, 45) * Box(2.6, 2.6, 1.6)
            self.hat_cap = cap
        elif t == "toggle":                 # MTS-123 mini toggle (ON)-OFF-(ON), M6 bushing through a flat 2.5 mm wall
            add.append(L * Pos(0, 0, 3) * Cylinder(9.0, 6))
            cut.append(L * Pos(0, 0, -2.5) * Cylinder(7.2, 6))           # flat spot face, 0.5 below the surface
            cut.append(L * Pos(0, 0, 2) * Cylinder(3.15, 6))
            cut.append(L * Pos(0, 0, 4.5 + 5.5) * Box(9.6, 13.8, 11))     # room for the 8 x 13 body (from 4.5 deep: no knife edge on the skin)
            buy[w["name"]] = L * (Pos(0, 0, 9.8) * Box(8, 13, 10) + Pos(0, 0, 0.5) * Cylinder(3, 7) + Pos(0, 0, -6) * Cylinder(1.3, 10))
        labels.append(dict(name=w["name"], label=w["label"], pin=w["pin"], pos=[round(S.X, 1), round(S.Y, 1), round(S.Z, 1)],
                           normal=[round(d.X, 3), round(d.Y, 3), round(d.Z, 3)]))

    def rect_loft(self, uc, wu, wy, ss):
        """ruled loft of wu x wy rectangles centred at local u = uc, at spine stations ss (y symmetric)."""
        ws = []
        for s in ss:
            P = [self.pt(uc + du, dy, s) for du, dy in ((-wu / 2, -wy / 2), (wu / 2, -wy / 2), (wu / 2, wy / 2), (-wu / 2, wy / 2))]
            ws.append(Wire.make_polygon(P, close=True))
        return Solid.make_loft(ws, ruled=True)

    def trigger(self, add, cut, buy, labels):
        """lever pivoting on an M3 x 20 screw (along y) in a front slot; presses a 12 mm tact on the slot back wall."""
        k, p, st = self.k, self.p, self.s_trig
        af = self.semi(st)[0]
        uF = af                                         # front surface u at the trigger height (approx.)
        # housing (solid block in the cavity) and the lever slot: one ruled loft of rectangles each along the canted
        # spine (stacked boxes left stair steps with edge-touching corners -> non-manifold mesh)
        add.append(self.rect_loft(uF - 9, 18, 22, np.linspace(st - 22, st + 17, 9)))
        cut.append(self.rect_loft(uF - 13 + 15, 30, 13.0, np.linspace(st - 17.6, st + 12.6, 9)))
        ub = uF - 13                                    # slot back wall
        sw_s = st - 3
        cut.append(self.loc(ub - 1.9 + 0.01, 0, sw_s).location * Rot(0, 90, 0) * Box(12.4, 12.4, 3.8))   # switch body pocket
        for y in (-6.25, 6.25):
            cut.append(self.loc(ub - 3.8 - 1.6, y, sw_s).location * Box(4.0, 1.9, 8.0))
        cut.append(self.loc(ub - 3.8 - 1.6, 0, sw_s).location * Box(4.0, 6, 6))
        buy["trigger_switch"] = self.loc(ub - 1.9, 0, sw_s).location * Box(3.8, 12, 12) + \
            self.loc(ub + 1.75, 0, sw_s).location * Rot(0, 90, 0) * Cylinder(1.8, 3.5)
        # pivot
        pv_u, pv_s = uF - 5.0, st + 7.0
        Lp = self.loc(pv_u, 0, pv_s).location
        cut.append(Lp * Rot(90, 0, 0) * Pos(0, 0, -(6.5 + 2.6) / 2 - 0.01) * Cylinder(M3_CLR / 2, 6.5 + 2.6 + 0.1))   # left wall clearance
        cut.append(Lp * Pos(0, 9.0 + 10, 0) * Rot(90, 0, 0) * Cylinder(M3_CB / 2, 20))                              # head counterbore
        cut.append(Lp * Pos(0, -6.5 - 3.25, 0) * Rot(90, 0, 0) * Cylinder(INSERT_D / 2, 6.5))                       # insert (right wall)
        # lever profile in (u, s) relative to the pivot, extruded 12 mm in y
        stem_u = ub + 3.5 + 0.1 - pv_u               # switch stem top, relative to pivot
        prof = [(-5.0 + 1, 3.2), (0.0, 5.0), (4.2, 3.0), (6.5, -4), (8.0, -10.5), (8.8, -15.0), (7.5, -19.0), (4.5, -21.0),
                (1.5, -20.5), (stem_u + 1.2, -17.0), (stem_u, -12.0), (stem_u, -7.5), (-4.6, -1.5)]
        P = [Vector(u, -6.0, s) for u, s in prof]
        f = Face(Wire([Edge.make_spline(P, periodic=True)]))
        lev = extrude(f, 12.0, dir=(0, 1, 0))
        lev = lev - Pos(0, 0, 0) * Rot(90, 0, 0) * Cylinder(1.75, 20)
        self.trigger_lever = Lp * lev
        buy["trigger_pivot"] = Lp * Rot(90, 0, 0) * Cylinder(1.5, 20)
        o = self.pt(uF + 4, 0, st - 6)
        labels.append(dict(name="trigger", label="트리거 (검지)", pin="P0", pos=[round(o.X, 1), round(o.Y, 1), round(o.Z, 1)],
                           normal=[1, 0, 0]))
        self.pivot = (pv_u, pv_s)


def section_props(shape, pl, t=1.0):
    """area, I about the section x / y axes (through the centroid), extreme fibre distances, of the cut of the solid by
    plane pl -- from a 1 mm slab (volume / t)."""
    from OCP.GProp import GProp_GProps
    from OCP.BRepGProp import BRepGProp
    slab = None
    for fz in (0.0, 1e-4, 1e-3):
        try:
            slab = bop("common", shape, [pl.location * Box(400, 400, t)], fuzzy=fz)
            if slab is not None and slab.volume > 1: break
        except Exception:
            slab = None
    g = GProp_GProps(); BRepGProp.VolumeProperties_s(slab.wrapped, g)
    A = g.Mass() / t
    c = g.CentreOfMass(); C = Vector(c.X(), c.Y(), c.Z())
    M = g.MatrixOfInertia()
    J = np.array([[M.Value(i, j) for j in (1, 2, 3)] for i in (1, 2, 3)])
    rr = 0.5 * np.trace(J) * np.eye(3) - J                       # int r r^T dV about the centroid
    xd = pl.x_dir; yd = pl.z_dir.cross(pl.x_dir)
    e1 = np.array([xd.X, xd.Y, xd.Z]); e2 = np.array([yd.X, yd.Y, yd.Z])
    I1, I2 = e1 @ rr @ e1 / t, e2 @ rr @ e2 / t                  # I for bending with fibres along x (fore-aft) / y (side)
    # extreme fibres: sample the slab edges (spline faces have almost no vertices)
    P = [e.position_at(t) for e in slab.edges() for t in np.linspace(0, 1, 41)]
    ext1 = max(abs((q - C).dot(xd)) for q in P)
    ext2 = max(abs((q - C).dot(yd)) for q in P)
    return A, I1, I2, ext1, ext2


def run_one(size, kind, quick=False):
    if True:
        g = Grip(kind, size).build()
        od = os.path.join(HERE, "stl", size); os.makedirs(od, exist_ok=True)
        prints = {f"{kind}_left": g.left, f"{kind}_right": g.right, f"{kind}_hatcap": g.hat_cap}
        if kind == "stick":
            prints["stick_trigger"] = g.trigger_lever
        info = []
        for n, sh in prints.items():
            export_stl(sh, os.path.join(od, n + ".stl"), tolerance=0.03, angular_tolerance=0.15)
            mv, op_, nm_ = stl_check(os.path.join(od, n + ".stl"))
            print(f"    mesh {n}: {mv / 1000:.2f} cm3 (brep {sh.volume / 1000:.2f}), open edges {op_}, non-manifold {nm_}", flush=True)
            if op_ or nm_: raise RuntimeError(f"bad mesh {n}")
            if abs(mv / sh.volume - 1) > 0.01:             # BRepGProp is approximate on trimmed spline faces
                print(f"    note {n}: mesh and B-rep volume differ {100 * (mv / sh.volume - 1):+.1f} %", flush=True)
            bb = sh.bounding_box(); vol = sh.volume / 1000
            grams = round(vol * 1.24 * 0.85, 1)            # thin walls: mostly perimeters (~85 % of solid)
            nsol = len(sh.solids())
            if nsol != 1: print(f"   !! {n}: {nsol} solids", [round(x.volume) for x in sh.solids()])
            info.append(dict(name=n, kind="print", material="PLA", solids=nsol, size=[round(bb.size.X, 1), round(bb.size.Y, 1), round(bb.size.Z, 1)],
                             volume_cm3=round(vol, 1), grams=grams, print_h=round(grams / 11 + 0.25, 1), file=f"stl/{size}/{n}.stl"))
        for n, sh in g.buy.items():
            export_stl(sh, os.path.join(od, f"{kind}_{n}.stl"), tolerance=0.05)
            info.append(dict(name=f"{kind}_{n}", kind="buy", file=f"stl/{size}/{kind}_{n}.stl"))
        # interference: bought parts vs shell (should be ~0) and vs each other
        clash = []
        names = list(g.buy)
        for n in names:
            if n in ("tube", "m4_bolt", "trigger_pivot"): continue
            v = (g.buy[n] & g.shell).volume
            if v > 1.0: clash.append(f"{n}×shell {v:.0f}")
        for i in range(len(names)):
            for j in range(i + 1, len(names)):
                a, b = names[i], names[j]
                if {a, b} & {"tube", "m4_bolt"} and {a, b} <= {"tube", "m4_bolt"}: continue
                if {a, b} == {"trigger_pivot", "trigger_switch"}: pass
                v = (g.buy[a] & g.buy[b]).volume
                if v > 1.0: clash.append(f"{a}×{b} {v:.0f}")
        if kind == "stick":
            v = (g.trigger_lever & g.shell).volume
            if v > 1.0: clash.append(f"trigger_lever×shell {v:.0f}")
        # strength: section just above the tube top (shell only), 200 N at the grip top
        strength = []
        for s in (() if quick else (NECK_TOP + 3.5, NECK_TOP + 15, FLANGE + 2 * g.p)):
            o, xd, zd = g.frame(s)
            pl = Plane(o, x_dir=xd, z_dir=zd)
            A, Iu, Iv, cu, cv = section_props(g.shell, pl)
            top = g.pt(0, 0, g.s_top)
            arm = (top - o).dot(zd)
            M = 200 * arm                                     # N mm
            strength.append(dict(s=round(s, 1), area=round(A), I_fore_aft=round(Iu), I_side=round(Iv), arm=round(arm),
                                 sigma_fore_aft=round(float(M * cu / Iu), 1), sigma_side=round(float(M * cv / Iv), 1)))
        top = g.shell.bounding_box().max
        res = dict(created=datetime.now().isoformat(timespec="seconds"), size=size, HL=g.HL, HB=g.HB, who=SIZES[size]["who"], height=round(top.Z, 1), cant=g.cant,
                         min_wall=g.min_wall, dims=dims(g), labels=g.labels, screws=[[round(u, 1), round(s, 1)] for u, s in g.screws],
                         parts=info, clash=clash, strength=strength)
        print(size, kind, "height", round(top.Z, 1), "clash", clash or "none")
        for x in strength: print("   ", x)
        for x in info:
            if x["kind"] == "print": print("   ", x["name"], x["size"], x["grams"], "g", x["print_h"], "h")
    return res


def dims(g):
    """grip-size numbers at the mid handle: depth, width, perimeter, equivalent diameter."""
    s = FLANGE + 2 * g.p
    P = g.sec_pts(s)
    per = sum(math.dist(P[i], P[(i + 1) % len(P)]) for i in range(len(P)))
    xs = [q[0] for q in P]; ys = [q[1] for q in P]
    return dict(mid_s=round(s, 1), depth=round(max(xs) - min(xs), 1), width=round(max(ys) - min(ys), 1),
                perimeter=round(per, 1), d_equiv=round(per / math.pi, 1), finger_pitch=round(g.p, 1),
                head_s=round(g.s_head, 1), trigger_s=round(g.s_trig, 1))


if __name__ == "__main__":
    QUICK = "--quick" in sys.argv
    kinds = [a for a in sys.argv[1:] if a in ("stick", "throttle")] or ["stick", "throttle"]
    sizes = [a for a in sys.argv[1:] if a in SIZES] or ([] if "--merge" in sys.argv else list(SIZES))
    for sz in sizes:
        for kind in kinds:
            res = run_one(sz, kind, QUICK)
            od = os.path.join(HERE, "stl", sz)
            json.dump(res, open(os.path.join(od, f"{kind}_info.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    allp = {}
    for sz in SIZES:
        for kind in ("stick", "throttle"):
            f = os.path.join(HERE, "stl", sz, f"{kind}_info.json")
            if os.path.exists(f): allp.setdefault(sz, {})[kind] = json.load(open(f, encoding="utf-8"))
    meta = dict(created=datetime.now().isoformat(timespec="seconds"), script="hardware/grips/grips.py",
                interface=dict(tube_d=TUBE_D, tube_wall=2.0, insertion=TUBE_IN, bolt="M4x30 button head + nut", bolt_z=BOLT_Z,
                               key="rib 3.8 wide x 6 at the rear (-x) of the socket top; tube notch 4 x 6"),
                frame="grip frame: origin socket mouth centre, z up the tube, x forward, y left")
    json.dump(dict(meta=meta, sizes=allp), open(os.path.join(HERE, "parts.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
