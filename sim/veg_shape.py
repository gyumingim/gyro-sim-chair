"""Less-round proxy trees (11-11, docs/trees-shape-busan.md): new prototype shapes for the 3D tree tiles (sim/veg_v2.py),
same budget class (near ~250-450 triangles, far 24-40), same vertex encoding (veg_v2.Proto: tint multiplier, kind, AO).

Why: the v2 crowns read as balls / broccoli from 100-500 m - clumps overlap into one dome and their normals are bent to
the crown envelope (soft 0.55), so the whole crown shades like one sphere. Here:
  - 소나무 (Pinus densiflora): leaning, curved trunk, grey-brown at the foot and ORANGE-brown above (vertex colour), a
    clear bole, 3-5 limbs ending in separate FLAT needle pads with gaps between them; flat-topped / umbrella crown.
  - 어린 소나무 / dense-stand pine: narrow crown of offset tiers, trunk visible between them.
  - 곰솔 (P. thunbergii, coast): dark grey trunk, wind-swept: pads pushed to one side, layered.
  - 참나무류 (broadleaf): short trunk forking into 2-3 stems, 5-7 LOBES (each a big clump + 1-2 bumps) with notches.
  - 관목 (shrub): 3-5 separate low mounds.
  - granite tors: unchanged (veg_v2.proto_rock).
  Clump normals are the clump's own (soft 0.12-0.2, plus an up-bias on pad tops) and the AO is per clump: lit tops, dark
  undersides, darker where a clump sits inside the crown -> each clump reads on its own.
Designed in metres for a reference tree (height H_REF, crown radius R_REF), then scaled to the unit tree veg_v2 instances
(height 1, crown radius 1; normals by the inverse-transpose so they stay right after the instance scale).

    python -I sim/veg_shape.py --stats            triangle counts per prototype
Previews (no Unreal): sim/veg_shape_preview.py.
"""
import math, os, sys, site
if sys.flags.isolated:
    site.addsitedir(site.getusersitepackages())
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import numpy as np                                        # noqa: E402
import veg_build as V                                     # noqa: E402
import veg_v2 as V2                                       # noqa: E402

KIND = V2.KIND
UP = np.array([0.0, 1.0, 0.0])
# reference tree per species (m): the design space; the instance scale brings any tree back to its own size
REF = dict(pine=(12.0, 4.0), ypine=(12.0, 2.8), bpine=(11.0, 4.0), broad=(11.0, 4.4), shrub=(2.5, 1.6))
# bark colour multipliers on veg_v2.TRUNK (linear): foot grey-brown, upper red pine trunk orange-brown
BARK_FOOT = (1.0, 1.0, 1.0)
BARK_ORANGE = (2.1, 1.15, 0.62)
BARK_BPINE = (0.75, 0.74, 0.78)


class MProto(V2.Proto):
    """veg_v2.Proto built in metres; .unit(H, R) rescales to the unit tree (call once, last)."""

    def tube_m(self, pts, rads, cols, sides=6, ao=(0.5, 0.9)):
        pts = np.asarray(pts, np.float64)
        k = len(pts)
        P, Nn, A, C, F = [], [], [], [], []
        for i in range(k):
            d = pts[min(i + 1, k - 1)] - pts[max(i - 1, 0)]
            d /= np.linalg.norm(d)
            a = np.cross(d, [0.0, 0.0, 1.0]) if abs(d[2]) < 0.9 else np.cross(d, [1.0, 0.0, 0.0])
            a /= np.linalg.norm(a)
            b = np.cross(d, a)
            for q in range(sides):
                t = 2 * math.pi * q / sides
                n = math.cos(t) * a + math.sin(t) * b
                P.append(pts[i] + rads[i] * n); Nn.append(n)
                A.append(ao[0] + (ao[1] - ao[0]) * i / max(k - 1, 1))
                C.append(cols[i])
        for i in range(k - 1):
            for q in range(sides):
                a0, b0 = i * sides + q, i * sides + (q + 1) % sides
                F += [(a0, b0 + sides, b0), (a0, a0 + sides, b0 + sides)]
        self._add(np.array(P), np.array(Nn), np.array(C), KIND["bark"], np.array(A), np.array(F))

    def lump(self, c, s, seed, kind, far=False, jit=0.25, flat=0.0, soft=0.15, up_bias=0.0, ao_lo=0.32, inner=1.0):
        """one foliage clump (icosahedron, octahedron far) at c with semi-axes s (m).
        flat: 0..1 squashes the underside (needle pads); up_bias: top normals towards up (flat-topped pads read lit);
        soft: blend towards the crown envelope normal (v2 used 0.55 -> one ball); ao_lo: underside AO; inner: AO x."""
        Vv, F = V2.octa() if far else V.icosa()
        rg = np.random.default_rng(seed)
        Vv = Vv * (1 + rg.uniform(-jit, jit, (len(Vv), 1)))
        Vv = Vv.copy()
        if flat > 0:
            lo = Vv[:, 1] < 0
            Vv[lo, 1] *= (1 - 0.65 * flat)
        c, s = np.asarray(c, np.float64), np.asarray(s, np.float64)
        P = Vv * s + c
        nl = Vv / s
        nl /= np.linalg.norm(nl, axis=1, keepdims=True)
        ec, es = self.env
        ne = (P - ec) / es ** 2
        ne /= np.linalg.norm(ne, axis=1, keepdims=True) + 1e-9
        Nn = (1 - soft) * nl + soft * ne
        if up_bias > 0:
            Nn = Nn + up_bias * UP * np.clip(nl[:, 1:2], 0, 1)
        Nn /= np.linalg.norm(Nn, axis=1, keepdims=True)
        # per-clump AO: top 1, side ~0.75, underside ao_lo; lower in the crown and deeper inside it darker
        top = np.clip(0.5 + 0.5 * nl[:, 1], 0, 1)
        ao = ao_lo + (1 - ao_lo) * top ** 1.3
        hf = np.clip((P[:, 1] - (ec[1] - es[1])) / (2 * es[1]), 0, 1)
        depth = np.linalg.norm((P - ec) / es, axis=1)
        ao *= (0.78 + 0.22 * hf) * (0.72 + 0.28 * np.clip(depth, 0, 1)) * inner
        ao = np.clip(ao * rg.uniform(0.94, 1.06), 0.1, 1.0)
        self._add(P, Nn, np.ones((len(P), 3)), kind, ao, F)

    def unit(self, H, R):
        """metres (y up, base at 0) -> the unit tree: x, z / R, y / H; normals by the inverse transpose."""
        sc = np.array([1.0 / R, 1.0 / H, 1.0 / R])
        self.P = [p * sc for p in self.P]
        nn = []
        for n in self.N:
            q = n / sc
            nn.append(q / (np.linalg.norm(q, axis=1, keepdims=True) + 1e-12))
        self.N = nn
        ec, es = self.env
        self.env = (ec * sc, es * sc)
        return self


def _trunk(H, lean_deg, az, y1, wob, seed, n=6):
    """curved leaning trunk polyline from below the ground to height y1 (m)."""
    rg = np.random.default_rng(seed)
    t = np.linspace(0, 1, n)
    lean = math.tan(math.radians(lean_deg)) * y1
    ph = rg.uniform(0, 2 * math.pi, 2)
    off = lean * t ** 1.4                                     # leans more towards the top (a curved, not straight, stem)
    x = off * math.cos(az) + wob * np.sin(t * 4.0 + ph[0])
    z = off * math.sin(az) + wob * np.sin(t * 3.3 + ph[1])
    y = -0.6 + (y1 + 0.6) * t
    return np.stack((x, y, z), 1)


def _bark_cols(pts, H, foot, upper, y_change):
    w = np.clip((pts[:, 1] - y_change * 0.7) / (y_change * 0.6 + 1e-6), 0, 1)[:, None]
    return np.asarray(foot)[None] * (1 - w) + np.asarray(upper)[None] * w


def pine_umbrella(var, far=False):
    """mature 소나무: var 0 umbrella (5 pads), var 1 lopsided / strongly leaning, 2 tiers."""
    H, R = REF["pine"]
    m = MProto()
    rg = np.random.default_rng(3100 + var)
    az = rg.uniform(0, 2 * math.pi)
    lean = (11.0, 19.0)[var] + rg.uniform(-2, 2)
    y_fork = (0.62, 0.58)[var] * H
    tr = _trunk(H, lean, az, y_fork, 0.12, 3200 + var)
    top = tr[-1]
    m.env = (np.array([top[0], 0.82 * H, top[2]]), np.array([R, 0.2 * H, R]))
    if not far:
        r = np.linspace(0.24, 0.13, len(tr))
        m.tube_m(tr, r, _bark_cols(tr, H, BARK_FOOT, BARK_ORANGE, 0.45 * H), sides=6, ao=(0.55, 0.95))
    # two tiers of separate needle pads: upper 4-5 at 0.86-0.97 H (flat top), lower 2-3 at 0.66-0.76 H between them
    up_n, lo_n = ((5, 3), (4, 2))[var]
    ang0 = az + (0.0 if var == 0 else math.pi * 0.15)
    pads = []
    for q in range(up_n + lo_n):
        upper = q < up_n
        n_, q_ = (up_n, q) if upper else (lo_n, q - up_n)
        a = ang0 + 2 * math.pi * (q_ + (0.0 if upper else 0.5) + rg.uniform(-0.15, 0.15)) / n_
        if var == 1:                                          # lopsided: pads crowd towards the lean side
            a = az + (a - az) * 0.7
        rad = (rg.uniform(0.40, 0.66) if upper else rg.uniform(0.55, 0.78)) * R
        y = (rg.uniform(0.86, 0.95) if upper else rg.uniform(0.66, 0.76)) * H
        base_r = 1.0 if upper else 0.85
        pads.append((np.array([top[0] + rad * math.cos(a), y, top[2] + rad * math.sin(a)]), base_r))
    pads.append((np.array([top[0] + rg.uniform(-0.3, 0.3), 0.93 * H, top[2] + rg.uniform(-0.3, 0.3)]), 0.9))   # crown top
    if far:
        for k, (p, _) in enumerate([pads[0], pads[2], pads[-1]]):
            m.lump(p, (1.8, 0.9, 1.6), 3300 + k, KIND["pine"], far=True, soft=0.1)
        return m.unit(H, R)
    for k, (p, br) in enumerate(pads):
        if k < len(pads) - 1 and k % 2 == 0:                  # limbs to every other pad (others hang off the same limb)
            b0 = tr[-1] - np.array([0, rg.uniform(0.3, 1.2), 0])
            mid = (b0 + p) / 2 + np.array([0, 0.4, 0])
            m.tube_m([b0, mid, p - np.array([0, 0.6, 0])], [0.11, 0.075, 0.05], _bark_cols(np.array([b0, mid, p]), H, BARK_ORANGE, BARK_ORANGE, 1),
                     sides=4, ao=(0.5, 0.7))
        big = rg.uniform(0.85, 1.15) * br
        s0 = np.array([rg.uniform(1.45, 1.85), rg.uniform(0.8, 1.0), rg.uniform(1.3, 1.65)]) * big
        m.lump(p, s0, 3400 + 13 * var + k, KIND["pine"], jit=0.3, flat=0.55, up_bias=0.3, ao_lo=0.28)
        if k % 2 == 1 or k == len(pads) - 1:
            continue
        d = rg.normal(0, 1, 2); d /= np.linalg.norm(d) + 1e-9          # a smaller tuft on the pad's rim (ragged outline)
        q2 = p + np.array([d[0] * s0[0] * 0.8, rg.uniform(-0.2, 0.25), d[1] * s0[2] * 0.8])
        m.lump(q2, s0 * np.array([0.55, 0.75, 0.55]), 3500 + 13 * var + k, KIND["pine"], jit=0.35, flat=0.5, up_bias=0.3, ao_lo=0.3)
    return m.unit(H, R)


def pine_young(far=False):
    """young / dense-stand 소나무: narrow crown of 4 offset tiers of small pads, trunk visible between them."""
    H, R = REF["ypine"]
    m = MProto()
    rg = np.random.default_rng(3700)
    az = rg.uniform(0, 2 * math.pi)
    tr = _trunk(H, 5.0, az, 0.93 * H, 0.06, 3701)
    m.env = (np.array([tr[-1][0] * 0.6, 0.72 * H, tr[-1][2] * 0.6]), np.array([R, 0.27 * H, R]))
    if not far:
        m.tube_m(tr, np.linspace(0.17, 0.06, len(tr)), _bark_cols(tr, H, BARK_FOOT, BARK_ORANGE, 0.5 * H), sides=5, ao=(0.5, 0.95))
    tiers = [(0.52, 1.0, 2), (0.66, 0.9, 2), (0.80, 0.7, 2), (0.94, 0.45, 1)] if not far else [(0.6, 0.95, 1), (0.85, 0.6, 1)]
    k = 0
    for y, rr, n in tiers:
        a0 = az + rg.uniform(0, 2 * math.pi)
        tc = tr[np.argmin(np.abs(tr[:, 1] - y * H))]
        for q in range(n):
            a = a0 + math.pi * q + rg.uniform(-0.5, 0.5)
            off = 0.0 if n == 1 else rr * R * rg.uniform(0.35, 0.55)
            c = np.array([tc[0] + off * math.cos(a), y * H + rg.uniform(-0.25, 0.25), tc[2] + off * math.sin(a)])
            s_ = np.array([rr * R * 0.62, 0.55 if not far else 1.1, rr * R * 0.55])
            m.lump(c, s_, 3710 + k, KIND["pine"], far=far, jit=0.33, flat=0.7, up_bias=0.3, ao_lo=0.3)
            k += 1
    return m.unit(H, R)


def pine_coast(far=False):
    """곰솔: straighter dark trunk, wind-swept layered pads pushed to the lee side."""
    H, R = REF["bpine"]
    m = MProto()
    rg = np.random.default_rng(3900)
    az = rg.uniform(0, 2 * math.pi)
    tr = _trunk(H, 8.0, az, 0.82 * H, 0.08, 3901)
    m.env = (np.array([tr[-1][0], 0.76 * H, tr[-1][2]]), np.array([R, 0.22 * H, R]))
    if not far:
        m.tube_m(tr, np.linspace(0.24, 0.1, len(tr)), np.tile(BARK_BPINE, (len(tr), 1)), sides=6, ao=(0.5, 0.9))
    tiers = [(0.60, 0.95, 2), (0.76, 0.85, 3), (0.92, 0.5, 1)] if not far else [(0.66, 0.95, 1), (0.88, 0.6, 1)]
    k = 0
    for y, rr, n in tiers:
        tc = tr[np.argmin(np.abs(tr[:, 1] - y * H))]
        for q in range(n):
            a = az + (q - (n - 1) / 2) * 1.3 + rg.uniform(-0.3, 0.3)     # fan towards the lean (lee) side
            off = 0.0 if n == 1 else rr * R * rg.uniform(0.4, 0.6)
            c = np.array([tc[0] + off * math.cos(a), y * H + rg.uniform(-0.25, 0.2), tc[2] + off * math.sin(a)])
            s_ = np.array([rr * R * 0.58, 0.6 if not far else 1.0, rr * R * 0.5])
            m.lump(c, s_, 3910 + k, KIND["pine"], far=far, jit=0.3, flat=0.75, up_bias=0.3, ao_lo=0.28)
            k += 1
    return m.unit(H, R)


def broad_lobed(var, far=False):
    """참나무류: short trunk forking into stems, 5-7 lobes (big clump + bumps) on an irregular dome with notches."""
    H, R = REF["broad"]
    m = MProto()
    rg = np.random.default_rng(4100 + var)
    nl_ = (6, 5, 7, 6)[var]
    cy = (0.62, 0.66, 0.60, 0.64)[var] * H
    ey = (0.30, 0.34, 0.27, 0.32)[var] * H
    off = np.array([rg.uniform(-0.5, 0.5), 0, rg.uniform(-0.5, 0.5)]) * (var >= 2)
    m.env = (np.array([0, cy, 0]) + off, np.array([R, ey, R]))
    tr = _trunk(H, 4.0, rg.uniform(0, 6.28), 0.36 * H, 0.06, 4150 + var, n=4)
    if not far:
        m.tube_m(tr, np.linspace(0.28, 0.2, len(tr)), np.tile(BARK_FOOT, (len(tr), 1)), sides=6, ao=(0.45, 0.8))
    if far:
        for k in range(4):
            a = 2 * math.pi * k / 4 + rg.uniform(-0.3, 0.3)
            r_ = 0.0 if k == 0 else 0.5 * R
            c = np.array([r_ * math.cos(a), cy + (0.45 * ey if k == 0 else -0.1 * ey), r_ * math.sin(a)]) + off
            m.lump(c, (0.6 * R, 0.6 * ey, 0.6 * R), 4200 + k, KIND["broad"], far=True, soft=0.1)
        return m.unit(H, R)
    a0 = rg.uniform(0, 2 * math.pi)
    lobes = []
    for k in range(nl_ - 1):                                  # ring of side lobes + one top lobe
        a = a0 + 2 * math.pi * (k + rg.uniform(-0.2, 0.2)) / (nl_ - 1)
        rr = rg.uniform(0.48, 0.62) * R
        y = cy + rg.uniform(-0.25, 0.35) * ey
        lobes.append((np.array([rr * math.cos(a), y, rr * math.sin(a)]) + off, rg.uniform(0.40, 0.52) * R))
    lobes.append((np.array([rg.uniform(-0.3, 0.3), cy + 0.55 * ey, rg.uniform(-0.3, 0.3)]) + off, 0.5 * R))
    j = 0
    for k, (c, rl) in enumerate(lobes):
        if k < 3:                                             # 2-3 stems from the fork to the lower lobes
            b0 = tr[-1]
            m.tube_m([b0, (b0 + c) / 2 + np.array([0, 0.3, 0]), c - np.array([0, 0.5 * rl, 0])], [0.16, 0.11, 0.07],
                     np.tile(BARK_FOOT, (3, 1)), sides=4, ao=(0.4, 0.6))
        s0 = np.array([rl, rl * rg.uniform(0.72, 0.85), rl * rg.uniform(0.9, 1.1)])
        m.lump(c, s0, 4300 + 31 * var + j, KIND["broad"], jit=0.22, soft=0.18, up_bias=0.12, ao_lo=0.32); j += 1
        nb = 1 if k % 2 else 2
        for q in range(nb):                                   # bumps on the lobe's outer / upper surface
            d = c - (np.array([0, cy, 0]) + off)
            d = d / (np.linalg.norm(d) + 1e-9) + rg.normal(0, 0.45, 3) + np.array([0, 0.5, 0])
            d /= np.linalg.norm(d)
            m.lump(c + d * rl * 0.8, s0 * rg.uniform(0.42, 0.55), 4400 + 31 * var + j, KIND["broad"], jit=0.25, soft=0.15,
                   up_bias=0.1, ao_lo=0.38); j += 1
    return m.unit(H, R)


def shrub_mounds(var, far=False):
    H, R = REF["shrub"]
    m = MProto()
    rg = np.random.default_rng(4700 + var)
    m.env = (np.array([0, 0.5 * H, 0]), np.array([R, 0.5 * H, R]))
    n = (5, 4)[var] if not far else 3
    for k in range(n):
        a = 2 * math.pi * k / n + rg.uniform(-0.4, 0.4)
        rr = 0.0 if k == 0 else rg.uniform(0.5, 0.75) * R
        sz = rg.uniform(0.55, 0.85) * (1.2 if k == 0 else 1.0)
        c = np.array([rr * math.cos(a), sz * 0.55 * H * 0.8, rr * math.sin(a)])
        m.lump(c, np.array([0.55 * R * sz, 0.55 * H * sz, 0.5 * R * sz]), 4710 + 13 * var + k, KIND["shrub"], far=far,
               jit=0.28, soft=0.15, ao_lo=0.35)
    return m.unit(H, R)


# same 12 slots / order as veg_v2.PROTOS (pine 0, 1, 3, bpine 2, broad 0-3, shrub 0-1, rock 0-1)
def build_proto(pid, far):
    nm, var = V2.PROTOS[pid]
    if nm == "pine":
        return pine_young(far) if var == 3 else pine_umbrella(var, far)
    if nm == "bpine":
        return pine_coast(far)
    if nm == "broad":
        return broad_lobed(var, far)
    if nm == "shrub":
        return shrub_mounds(var, far)
    return V2.proto_rock(var, far)


if __name__ == "__main__":
    if "--stats" in sys.argv:
        for p in range(len(V2.PROTOS)):
            print(V2.PROTOS[p], "near", build_proto(p, False).ntri, "far", build_proto(p, True).ntri,
                  "| v2 near", V2.build_proto(p, False).ntri, "far", V2.build_proto(p, True).ntri)
