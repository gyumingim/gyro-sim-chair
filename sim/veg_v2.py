"""Trees v2 (11-10 second pass): real-forest look for the 3D trees of the Unreal 'vworld' mode. Same tree positions /
heights / crown widths as sim/veg_build.py (its --prep output C:\\GyroSimTiles\\veg\\work\\b_*.npz), new everything else:

    python -I sim/veg_v2.py --tiles           -> C:\\GyroSimTiles\\veg\\tiles_v2\\tileset.json + b/*.glb (far) + c/*.glb (near)
    python -I sim/veg_v2.py --preview DIR     prototype pictures (software render, no Unreal) for checking shapes

Played by unreal/GyroSim/Content/Python/trees_look.py with /Game/Trees/M_GyroTree2 (Scripts/trees_material.py v2 +
Scripts/trees_foliage2.hlsl). GYROSIM_TREES_V2=0 there = the v1 tiles + M_GyroTree (the look before).

What changed against v1 (all procedural, made here; no third-party assets, see docs/vworld-integration.md 6-6):
  - SHAPES: v1 crowns were 1-5 smooth ellipsoids on a stick ("lollipops"). v2 prototypes are built from a branch skeleton:
      소나무 (Pinus densiflora): bent orange-red trunk, clear bole, 3-5 limbs ending in flat needle pads -> irregular,
        flat-topped, see-through umbrella crowns (2 variants);
      곰솔 / young pine: straighter trunk, irregular stacked pads (1 variant, coast and young stands);
      참나무류 (Quercus) / other broadleaf: short trunk, 3 limbs, 12-16 leaf clumps on an irregular dome (3 variants);
      관목 (shrub): 6 clumps from the ground (WorldCover shrubland, canopy < 4.5 m).
    Every clump is a 20-triangle jittered icosahedron; near trees 150-330 triangles. Far trees (1-2.6 km): the same tree
    as 3-4 octahedron clumps (24-32 triangles) - no single ball.
  - SELF-SHADOWING: per-vertex ambient occlusion from the depth inside the crown and the height in it (inner / lower
    clumps darker); clump normals bent towards the crown envelope (foliage reads as one canopy, not as beads).
  - SPECIES MIX (가정 - no forest-type map, 산림청 임상도 needs an account): logistic score per tree from the terrain
    (Copernicus 30 m DEM: ridge / valley = height minus the ~480 m mean, south-west facing steep dry slopes, < 300 m from
    the sea = 곰솔 coast, > 450 m slightly more oak) and the v1 photo score (darker / bluer crown = pine). Pines dominate
    ridges and the rocky coast, broadleaf the valleys and lower slopes. WorldCover shrubland / low canopy -> shrubs.
  - COLOUR: physical leaf albedo per species (linear, summer), only the brightness follows the photo under the crown
    (sqrt, clamped 0.75-1.3, so sunny / shady photo slopes are not baked twice). v1 used photo colour x 1.9, which made
    crowns cyan and, on bright rock / path pixels, WHITE trees (v1 broadleaf palette bins 0.46 / 0.87 linear grey).
    Per-tree variation is added in the material (PerInstanceRandom, value / hue), season parameter (0 = summer).
  - ROCK OUTCROPS: no tree where the photo under the crown is bright and grey (granite tops of 금정산, 이기대 / 태종대
    cliffs) - the V-World photo of the rock shows through.
  - CLOSED CANOPY: crown radius 0.7 x the local mean spacing (v1 0.6): clumpy crowns cover less than a solid ellipsoid.
Vertex colour: RGB = species tint (sRGB-encoded bytes - linear 8-bit bands in the dark greens), A = 64 x kind + AO (6
bits): kind 0 bark, 1 pine, 2 broadleaf, 3 shrub (Cesium copies the bytes unchanged; the material decodes them).
Drop-in prototypes: GYROSIM_TREES_PROTOS = a folder with pine*.glb / broad*.glb / shrub*.glb (one mesh each, y-up,
any size: normalised to height 1 / crown radius 1; vertex colours or the base colour factor; textures are not used - see
docs/fab-trees.md); far trees (1-2.6 km) keep the built-in far shapes.
"""
import json, math, os, sys, time, glob, struct, site, zlib
if sys.flags.isolated:
    site.addsitedir(site.getusersitepackages())
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import numpy as np                                        # noqa: E402
import veg_build as V                                     # noqa: E402

TILES2 = os.environ.get("GYROSIM_VEG_TILES2", os.path.join(V.ROOT, "tiles_v2"))
# downloaded-model clump proxies (sim/veg_proxy.py; Fab Megascans English oak + black alder, 11-10) are used when present;
# GYROSIM_TREES_PROTOS=none = procedural broadleaf only
_PD = os.environ.get("GYROSIM_TREES_PROTOS", os.path.join(V.ROOT, "protos_fab"))
PROTOS_DIR = "" if _PD.lower() in ("", "none", "0") or not os.path.isdir(_PD) else _PD
# round 2: A refines at ~3.9 km (v1 / first v2: 2.6 km) - the far trees reach further, the tree line edge moves into the haze
GE2 = dict(root=20000.0, a=float(os.environ.get("GYROSIM_VEG2_GEA", "45.0")), b=float(os.environ.get("GYROSIM_VEG2_GEB", "12.0")), c=0.0)
NBIN = 2                                                  # colour bins per shape (+ per-instance variation in the material)
R_FAC = 0.78
KIND = dict(bark=0, pine=1, broad=2, shrub=3)
# linear summer albedo of the sunlit crown (before the per-vertex AO); 소나무 dark olive-green, 곰솔 darker / bluer,
# 참나무 brighter yellow-green, shrubs in between. Starting values from leaf / canopy albedo (~0.04-0.12 green), tuned
# against the real Busan photos (11-10 after1: forest pixels (71, 90, 45) sRGB vs 금정산 photo (67, 82, 51) -> bluer, darker).
# round 2 (customer: pine darker blue-green, oak rounder yellow-green): two clearly different species colours
TINT = dict(pine=(0.037, 0.064, 0.047), bpine=(0.032, 0.058, 0.046), broad=(0.062, 0.100, 0.040), shrub=(0.056, 0.090, 0.044),
            rock=(0.28, 0.28, 0.27))                     # rock = warm-grey weathered granite (never white); round 3 lighter (c247)
TRUNK = dict(pine=(0.13, 0.095, 0.07), broad=(0.11, 0.10, 0.085), shrub=(0.10, 0.09, 0.075))  # linear grey-brown bark (round 2)


def lin_to_srgb8(c):
    c = np.clip(np.asarray(c, np.float64), 0, 1)
    s = np.where(c <= 0.0031308, c * 12.92, 1.055 * c ** (1 / 2.4) - 0.055)
    return np.clip(np.round(s * 255), 0, 255)


# ---- prototype geometry (glTF y-up, unit height 1 = the tree height, unit crown radius 1) -------------------------------
def octa():
    V_ = np.array([[1, 0, 0], [-1, 0, 0], [0, 1, 0], [0, -1, 0], [0, 0, 1], [0, 0, -1]], np.float64)
    F = np.array([[2, 4, 0], [2, 1, 4], [2, 5, 1], [2, 0, 5], [3, 0, 4], [3, 4, 1], [3, 1, 5], [3, 5, 0]])
    return V_, F


class Proto:
    """triangles with per-vertex position / normal / tint (linear rgb) / kind / ao."""
    def __init__(self):
        self.P, self.N, self.C, self.K, self.A, self.I = [], [], [], [], [], []
        self.nv = 0
        self.env = (np.array([0.0, 0.7, 0.0]), np.array([1.0, 0.3, 1.0]))     # crown envelope centre / semi-axes

    def _add(self, P, Nn, col, kind, ao, F):
        n = len(P)
        self.P.append(np.asarray(P, np.float64)); self.N.append(np.asarray(Nn, np.float64))
        self.C.append(np.broadcast_to(np.asarray(col, np.float64), (n, 3)).copy())
        self.K.append(np.full(n, kind, np.int64)); self.A.append(np.broadcast_to(np.asarray(ao, np.float64), (n,)).copy())
        self.I.append(np.asarray(F) + self.nv)
        self.nv += n

    def clump(self, c, s, seed, kind, col, far=False, jit=0.2, soft=0.55, ao_mul=1.0):
        V_, F = octa() if far else V.icosa()
        rg = np.random.default_rng(seed)
        V_ = V_ * (1 + rg.uniform(-jit, jit, (len(V_), 1)))
        c, s = np.asarray(c, np.float64), np.asarray(s, np.float64)
        P = V_ * s + c
        nl = V_ / s
        nl /= np.linalg.norm(nl, axis=1, keepdims=True)
        ec, es = self.env
        q = (P - ec) / es
        ne = q / es
        ne /= np.linalg.norm(ne, axis=1, keepdims=True) + 1e-9
        Nn = (1 - soft) * nl + soft * ne
        Nn /= np.linalg.norm(Nn, axis=1, keepdims=True)
        depth = np.linalg.norm(q, axis=1)                                  # 1 = on the envelope, 0 = centre
        hf = np.clip((P[:, 1] - (ec[1] - es[1])) / (2 * es[1]), 0, 1)       # 0 = crown bottom, 1 = top
        down = np.clip(-nl[:, 1], 0, 1)                                     # clump underside
        ao = (0.42 + 0.58 * np.clip((depth - 0.35) / 0.7, 0, 1)) * (0.70 + 0.30 * hf) * (1 - 0.28 * down)
        ao = np.clip(ao * ao_mul * rg.uniform(0.92, 1.08), 0.12, 1.0)
        self._add(P, Nn, col, kind, ao, F)

    def tube(self, pts, rads, col, sides=5, ao=(0.55, 0.9)):
        """trunk / limb along a polyline (pts (k,3), rads (k,))."""
        pts = np.asarray(pts, np.float64)
        P, Nn, A, F = [], [], [], []
        k = len(pts)
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
        for i in range(k - 1):
            for q in range(sides):
                a0, b0 = i * sides + q, i * sides + (q + 1) % sides
                F += [(a0, b0 + sides, b0), (a0, a0 + sides, b0 + sides)]
        self._add(np.array(P), np.array(Nn), col, KIND["bark"], np.array(A), np.array(F))

    def arrays(self, tint, trunk_tint):
        """-> P, N (float32), COLOR_0 (uint8 rgba: sRGB tint, A = 64 kind + 63 ao), I (uint32)."""
        P = np.concatenate(self.P).astype(np.float32); Nn = np.concatenate(self.N).astype(np.float32)
        K = np.concatenate(self.K); A = np.concatenate(self.A); C = np.concatenate(self.C)
        rgb = np.where((K == 0)[:, None], C * np.asarray(trunk_tint)[None], C * np.asarray(tint)[None])
        a = K * 64 + np.clip(np.round(A * 63), 0, 63)
        Cu = np.concatenate((lin_to_srgb8(rgb), a[:, None]), 1).astype(np.uint8)
        I = np.concatenate(self.I).astype(np.uint32).reshape(-1)
        return P, Nn, Cu, I

    @property
    def ntri(self):
        return int(sum(len(f) for f in self.I))


def _bend(y0, y1, n, lean, seed, wob=0.03):
    rg = np.random.default_rng(seed)
    t = np.linspace(0, 1, n)
    ph = rg.uniform(0, 2 * math.pi, 2)
    x = lean[0] * t ** 1.6 + wob * np.sin(t * 5.0 + ph[0])
    z = lean[1] * t ** 1.6 + wob * np.sin(t * 4.0 + ph[1])
    return np.stack((x, y0 + (y1 - y0) * t, z), 1)


ONE = (1.0, 1.0, 1.0)


def proto_pine(var, far=False):
    """소나무: var 0, 1 mature umbrella (irregular flat needle tufts on bent limbs), var 3 young / dense stand (tufts all down
    the stem); 곰솔 var 2 (stacked pads). Round 2: crowns start lower (trunks hidden under a closed canopy), more and
    smaller ragged tufts instead of a few big pads."""
    m = Proto()
    rg = np.random.default_rng(100 + var)
    if var in (0, 1):
        lean = rg.uniform(-0.16, 0.16, 2)
        top = 0.62 if var == 0 else 0.56
        tr = _bend(-0.08, top, 5, lean, 7 + var, 0.035)
        m.env = (np.array([lean[0] * 0.8, 0.76 if var == 0 else 0.70, lean[1] * 0.8]), np.array([0.98, 0.24 if var == 0 else 0.30, 0.98]))
        if not far:
            m.tube(tr, np.linspace(0.045, 0.02, len(tr)), ONE)
        nlimb = 5 if var == 0 else 6
        ang0 = rg.uniform(0, 2 * math.pi)
        tufts = []
        for q in range(nlimb):
            a = ang0 + 2 * math.pi * q / nlimb + rg.uniform(-0.4, 0.4)
            rad = rg.uniform(0.42, 0.74)
            y_s = top - rg.uniform(0.04, 0.22)
            y_t = (0.74 if var == 0 else 0.60 + 0.20 * (q % 2)) + rg.uniform(-0.08, 0.10)
            b0 = tr[np.argmin(np.abs(tr[:, 1] - y_s))]
            tip = np.array([b0[0] + rad * math.cos(a), y_t, b0[2] + rad * math.sin(a)])
            mid = (b0 + tip) / 2 + np.array([0, 0.04, 0])
            if not far:
                m.tube([b0, mid, tip], [0.02, 0.014, 0.009], ONE, sides=4, ao=(0.45, 0.65))
            tufts.append(tip)
            if not far:
                tufts.append(tip + np.array([rg.uniform(-0.15, 0.15), rg.uniform(-0.06, 0.04), rg.uniform(-0.15, 0.15)]))
        tufts.append(np.array([tr[-1][0], tr[-1][1] + 0.18 + (0.05 if var == 0 else 0.09), tr[-1][2]]))
        if far:
            for k, p in enumerate(tufts[:2] + tufts[-1:]):
                m.clump(p * np.array([0.85, 1, 0.85]), (0.55, 0.15, 0.50), 300 + k, KIND["pine"], ONE, far=True)
        else:
            for k, p in enumerate(tufts):
                sz = rg.uniform(0.62, 1.0)
                s_ = np.array([rg.uniform(0.26, 0.36), rg.uniform(0.08, 0.12), rg.uniform(0.22, 0.32)]) * sz
                m.clump(p, s_, 200 + 17 * var + k, KIND["pine"], ONE, jit=0.38)       # ragged flat needle tufts
    elif var == 3:                                              # young / dense-stand pine: tufts down the stem, narrow
        lean = rg.uniform(-0.06, 0.06, 2)
        tr = _bend(-0.08, 0.9, 5, lean, 29, 0.02)
        m.env = (np.array([lean[0] * 0.6, 0.62, lean[1] * 0.6]), np.array([0.8, 0.38, 0.8]))
        if not far:
            m.tube(tr, np.linspace(0.04, 0.016, len(tr)), ONE)
        n = 12 if not far else 3
        for k in range(n):
            y = 0.30 + 0.68 * (k + rg.uniform(0, 1)) / n
            rad = 0.75 * (1.05 - y) + 0.12
            a = rg.uniform(0, 2 * math.pi)
            off = 0.0 if far else rad * rg.uniform(0.25, 0.7)
            c = np.array([lean[0] * y + off * math.cos(a), y, lean[1] * y + off * math.sin(a)])
            s_ = np.array([rad * 0.7, 0.10 if not far else 0.16, rad * 0.65]) * (1.0 if not far else 1.3)
            m.clump(c, s_, 450 + k, KIND["pine"], ONE, far=far, jit=0.35)
    else:                                                       # 곰솔 / coast: irregular stacked pads, straighter trunk
        lean = rg.uniform(-0.08, 0.08, 2)
        tr = _bend(-0.08, 0.86, 5, lean, 17, 0.02)
        m.env = (np.array([lean[0] * 0.6, 0.64, lean[1] * 0.6]), np.array([0.85, 0.36, 0.85]))
        if not far:
            m.tube(tr, np.linspace(0.045, 0.016, len(tr)), ONE)
        lv = [(0.36, 0.80, 3), (0.54, 0.66, 3), (0.70, 0.52, 3), (0.86, 0.34, 2)] if not far else [(0.48, 0.75, 1), (0.72, 0.5, 1), (0.9, 0.3, 1)]
        k = 0
        for y, rad, n in lv:
            a0 = rg.uniform(0, 2 * math.pi)
            for q in range(n):
                a = a0 + 2 * math.pi * q / n
                off = 0.0 if n == 1 else rad * rg.uniform(0.45, 0.7)
                c = np.array([lean[0] * y + off * math.cos(a), y + rg.uniform(-0.04, 0.04), lean[1] * y + off * math.sin(a)])
                s_ = (np.array([rad * 0.6, 0.11, rad * 0.56]) if n > 1 else np.array([rad, 0.13, rad * 0.95]))
                m.clump(c, s_, 400 + k, KIND["pine"], ONE, far=far, jit=0.3)
                k += 1
    return m


def proto_broad(var, far=False):
    """참나무류 / broadleaf: short trunk + limbs, leaf clumps on an irregular dome (var 0 round, 1 tall, 2 wide / lopsided)."""
    m = Proto()
    rg = np.random.default_rng(500 + var)
    ex, ey, cy = [(0.86, 0.34, 0.64), (0.74, 0.42, 0.60), (0.95, 0.28, 0.66)][var]
    off = np.array([0.12, 0.0, -0.08]) if var == 2 else np.zeros(3)
    m.env = (np.array([0.0, cy, 0.0]) + off, np.array([ex, ey, ex]))
    tr = _bend(-0.08, cy - 0.12, 4, rg.uniform(-0.06, 0.06, 2), 23 + var, 0.02)
    if not far:
        m.tube(tr, np.linspace(0.06, 0.035, len(tr)), ONE)
        for q in range(3):
            a = 2 * math.pi * q / 3 + rg.uniform(-0.4, 0.4)
            b = tr[-2]
            t = np.array([0.45 * ex * math.cos(a), cy + 0.05, 0.45 * ex * math.sin(a)]) + off
            m.tube([b, (b + t) / 2 + np.array([0, 0.06, 0]), t], [0.03, 0.022, 0.014], ONE, sides=4, ao=(0.45, 0.6))
    if far:
        dirs = [(0.0, 1.0), (0.0, 0.25), (2.1, 0.25), (4.2, 0.25)]
        for k, (a, up) in enumerate(dirs):
            r_ = 0.0 if up > 0.9 else 0.5 * ex
            c = np.array([r_ * math.cos(a), cy + (0.45 * ey if up > 0.9 else -0.05), r_ * math.sin(a)]) + off
            m.clump(c, (0.55 * ex + 0.1, 0.55 * ey + 0.05, 0.55 * ex + 0.1), 600 + k, KIND["broad"], ONE, far=True)
        return m
    n = 14 if var != 2 else 16
    gold = math.pi * (3 - math.sqrt(5))
    for k in range(n):
        yy = 1 - 1.3 * (k + 0.5) / n                              # upper ~2/3 of a sphere, Fibonacci spread
        rr = math.sqrt(max(0.0, 1 - yy * yy))
        a = gold * k + rg.uniform(-0.3, 0.3)
        d = np.array([rr * math.cos(a), yy, rr * math.sin(a)])
        sh = rg.uniform(0.62, 0.80)
        c = np.array([0.0, cy, 0.0]) + off + d * np.array([ex, ey, ex]) * sh
        rad = rg.uniform(0.27, 0.38) * (ex / 0.86) ** 0.5
        m.clump(c, (rad, rad * rg.uniform(0.62, 0.80), rad * rg.uniform(0.9, 1.1)), 700 + 20 * var + k, KIND["broad"], ONE, jit=0.22)
    return m


def proto_shrub(far=False, var=0):
    m = Proto()
    rg = np.random.default_rng(900 + var)
    m.env = (np.array([0.0, 0.48, 0.0]), np.array([0.95, 0.52, 0.95]))
    n = (7 if var == 0 else 6) if not far else 3
    for k in range(n):
        a = 2 * math.pi * k / n + rg.uniform(-0.3, 0.3)
        rr = 0.0 if k == 0 else rg.uniform(0.35, 0.65)
        c = np.array([rr * math.cos(a), (0.45 if var == 0 else 0.36) + (0.2 if k == 0 else rg.uniform(-0.12, 0.05)), rr * math.sin(a)])
        s_ = ((0.45, 0.40, 0.45) if var == 0 else (0.5, 0.32, 0.42)) if not far else (0.7, 0.5, 0.7)
        m.clump(c, np.array(s_) * rg.uniform(0.8, 1.15), 950 + 13 * var + k, KIND["shrub"], ONE, far=far, jit=0.25)
    return m


def proto_rock(var, far=False):
    """granite (round 5): a group of angular slabs / blocks (faceted octahedra = flat and near-vertical faces), tilted,
    tight together and partly buried. kind 0 (no foliage shading); colour = the rock tint (neutral grey)."""
    m = Proto()
    m.env = (np.array([0.0, 0.4, 0.0]), np.array([1.0, 0.6, 1.0]))
    rg = np.random.default_rng(1700 + var)
    if var == 0:      # tor: stacked blocks
        parts = [((0.0, 0.2, 0.0), (0.9, 0.45, 0.75)), ((0.1, 0.62, -0.05), (0.62, 0.32, 0.5)), ((-0.05, 0.92, 0.08), (0.36, 0.2, 0.3)),
                 ((-0.55, 0.15, 0.4), (0.45, 0.3, 0.32)), ((0.6, 0.1, 0.35), (0.4, 0.24, 0.36))]
    else:             # slab outcrop: tilted plates
        parts = [((-0.3, 0.25, -0.1), (0.75, 0.3, 0.55)), ((0.4, 0.2, 0.25), (0.6, 0.28, 0.5)), ((0.0, 0.45, 0.5), (0.5, 0.22, 0.35)),
                 ((0.25, 0.5, -0.4), (0.45, 0.25, 0.4))]
    if far:
        parts = parts[:2]
    for k, (c, s_) in enumerate(parts):
        tilt = rg.uniform(-0.3, 0.3, 2); yaw = rg.uniform(0, math.pi)
        cy, sy, cx, sx, cz, sz = math.cos(yaw), math.sin(yaw), math.cos(tilt[0]), math.sin(tilt[0]), math.cos(tilt[1]), math.sin(tilt[1])
        Rm = np.array([[cy, 0, sy], [0, 1, 0], [-sy, 0, cy]]) @ np.array([[1, 0, 0], [0, cx, -sx], [0, sx, cx]]) @ np.array([[cz, -sz, 0], [sz, cz, 0], [0, 0, 1]])
        corner = np.array([[x, y, z] for x in (-1, 1) for y in (-1, 1) for z in (-1, 1)], np.float64)
        corner = corner * (1 + rg.uniform(-0.18, 0.12, (8, 3))) * np.array(s_)     # jittered block = slab with flat faces
        quads = [(0, 1, 3, 2), (4, 6, 7, 5), (0, 4, 5, 1), (2, 3, 7, 6), (0, 2, 6, 4), (1, 5, 7, 3)]
        P, Nn, A, F = [], [], [], []
        for q in quads:
            v = corner[list(q)] @ Rm.T + np.array(c)
            nrm = np.cross(v[1] - v[0], v[2] - v[0]); nrm /= np.linalg.norm(nrm) + 1e-9
            if np.dot(nrm, v.mean(0) - np.array(c)) < 0:
                nrm = -nrm; v = v[::-1]
            b = len(P)
            P += list(v); Nn += [nrm] * 4
            A += list(np.clip(0.35 + 0.65 * (v[:, 1] - (c[1] - s_[1])) / (2 * s_[1] + 1e-6), 0.25, 1.0) * (0.75 if nrm[1] < -0.3 else 1.0))
            F += [(b, b + 1, b + 2), (b, b + 2, b + 3)]
        m._add(np.array(P), np.array(Nn), ONE, KIND["bark"], np.array(A), np.array(F))
    return m


# (name, kind for tint, variant) - index = prototype id stored per tree
PROTOS = [("pine", 0), ("pine", 1), ("pine", 3), ("bpine", 2), ("broad", 0), ("broad", 1), ("broad", 2), ("broad", 3),
          ("shrub", 0), ("shrub", 1), ("rock", 0), ("rock", 1)]
SPECIES_OF = np.array([0, 0, 0, 1, 2, 2, 2, 2, 3, 3, 4, 4])    # palette group per prototype: pine, bpine, broad, shrub, rock
GROUPS = ("pine", "bpine", "broad", "shrub", "rock")
P_PINE, P_BPINE, P_BROAD, P_SHRUB, P_ROCK = (0, 1, 2), 3, (4, 5, 6, 7), (8, 9), (10, 11)


PROXY_PICK = [int(x) for x in os.environ.get("GYROSIM_TREES_PROTO_PICK", "1,2,5,6").split(",")]   # broad_<k>.npz per broad variant


def proxy_files(group):
    if not PROTOS_DIR or not os.path.isdir(PROTOS_DIR):
        return []
    return sorted(glob.glob(os.path.join(PROTOS_DIR, group + "_*.npz")), key=lambda f: int(f.rsplit("_", 1)[1][:-4]))


def proto_from_proxy(f, far, kind):
    """prototype from a sim/veg_proxy.py clump proxy (real crown shape of a downloaded model)."""
    z = np.load(f)
    m = Proto()
    c, s = z[("far" if far else "near") + "_c"].astype(np.float64), z[("far" if far else "near") + "_s"].astype(np.float64)
    lo, hi = (c - s).min(0), (c + s).max(0)
    m.env = ((lo + hi) / 2, np.maximum((hi - lo) / 2, 0.05))
    if not far:
        tr, tr_r = z["trunk"].astype(np.float64), z["trunk_r"].astype(np.float64)
        k = np.unique(np.linspace(0, len(tr) - 1, min(len(tr), 5)).round().astype(int))
        pts = tr[k]
        pts[0, 1] = min(pts[0, 1], 0.0) - 0.08
        m.tube(pts, np.clip(tr_r[k] * 0.9, 0.012, 0.08), ONE)
    for j in range(len(c)):
        m.clump(c[j], s[j] * (1.0 if far else 0.92), 1200 + 37 * j + (5 if far else 0), KIND[kind], ONE, far=far, jit=0.22)
    return m


def build_proto(pid, far):
    nm, var = PROTOS[pid]
    if nm == "broad":
        fs = proxy_files("broad")
        if fs:
            return proto_from_proxy(fs[PROXY_PICK[var % len(PROXY_PICK)] % len(fs)], far, "broad")
    if nm in ("pine", "bpine"):
        fs = proxy_files("pine")
        if fs:
            return proto_from_proxy(fs[var % len(fs)], far, "pine")
    if nm in ("pine", "bpine"):
        return proto_pine(var, far)
    if nm == "broad":
        return proto_broad(var % 3, far)
    if nm == "rock":
        return proto_rock(var, far)
    return proto_shrub(far, var)


# ---- drop-in prototypes (GYROSIM_TREES_PROTOS) ------------------------------------------------------------------------
def read_glb_mesh(path):
    """one glb -> (P, N, rgb-or-None, I) of all triangle primitives, y-up, normalised: base y = 0, height 1, radius 1."""
    b = open(path, "rb").read()
    jl = struct.unpack_from("<I", b, 12)[0]
    gl = json.loads(b[20:20 + jl])
    bin_ = b[20 + jl + 8:]
    CT = {5126: ("f", 4), 5121: ("B", 1), 5123: ("H", 2), 5125: ("I", 4)}
    NC = dict(SCALAR=1, VEC2=2, VEC3=3, VEC4=4)

    def acc(i):
        a = gl["accessors"][i]; v = gl["bufferViews"][a["bufferView"]]
        f, sz = CT[a["componentType"]]; nc = NC[a["type"]]
        off = v.get("byteOffset", 0) + a.get("byteOffset", 0)
        stride = v.get("byteStride", sz * nc)
        arr = np.ndarray((a["count"], nc), dtype=np.dtype(f).newbyteorder("<"), buffer=bin_, offset=off, strides=(stride, sz)).astype(np.float64)
        if a.get("normalized"):
            arr /= float(np.iinfo(np.dtype(f)).max)
        return arr
    Ps, Ns, Cs, Is, nv = [], [], [], [], 0
    for me in gl.get("meshes", []):
        for pr in me["primitives"]:
            if pr.get("mode", 4) != 4:
                continue
            at = pr["attributes"]
            P = acc(at["POSITION"])
            Nn = acc(at["NORMAL"]) if "NORMAL" in at else np.tile([0.0, 1.0, 0.0], (len(P), 1))
            if "COLOR_0" in at:
                C = acc(at["COLOR_0"])[:, :3]
            else:
                f = gl.get("materials", [{}])[pr.get("material", 0)].get("pbrMetallicRoughness", {}).get("baseColorFactor", [0.08, 0.12, 0.05, 1])
                C = np.tile(f[:3], (len(P), 1))
            I = acc(pr["indices"]).reshape(-1).astype(np.int64) if "indices" in pr else np.arange(len(P))
            Ps.append(P); Ns.append(Nn); Cs.append(C); Is.append(I.reshape(-1, 3) + nv); nv += len(P)
    P, Nn, C, I = np.concatenate(Ps), np.concatenate(Ns), np.concatenate(Cs), np.concatenate(Is)
    y0, y1 = P[:, 1].min(), P[:, 1].max()
    rad = np.sqrt(P[:, 0] ** 2 + P[:, 2] ** 2).max()
    P = (P - [0, y0, 0]) / [rad, y1 - y0, rad]
    return P, Nn, C, I


def dropin_protos():
    """{group: [Proto-like arrays]} from GYROSIM_TREES_PROTOS (pine*.glb, bpine*.glb, broad*.glb, shrub*.glb)."""
    out = {}
    if not PROTOS_DIR or not os.path.isdir(PROTOS_DIR):
        return out
    for g in GROUPS:
        for f in sorted(glob.glob(os.path.join(PROTOS_DIR, g + "*.glb"))):
            if g == "pine" and os.path.basename(f).startswith("bpine"):
                continue
            out.setdefault(g, []).append(read_glb_mesh(f))
    return out


def dropin_arrays(mesh, group):
    P, Nn, C, I = mesh
    lum = C @ np.array([0.2126, 0.7152, 0.0722])
    green = (C[:, 1] > C[:, 0] * 1.05) & (C[:, 1] > C[:, 2])
    kind = np.where(green, KIND["shrub" if group == "shrub" else ("broad" if group == "broad" else "pine")], KIND["bark"])
    ao = np.clip(lum / max(np.percentile(lum, 90), 1e-4), 0.15, 1.0)
    rgb = np.where(green[:, None], np.asarray(TINT[group])[None] / max(np.mean(TINT[group]), 1e-4) * np.mean(C, 1, keepdims=True), C)
    a = kind * 64 + np.clip(np.round(ao * 63), 0, 63)
    Cu = np.concatenate((lin_to_srgb8(rgb), a[:, None]), 1).astype(np.uint8)
    return P.astype(np.float32), Nn.astype(np.float32), Cu, I.astype(np.uint32).reshape(-1)


# ---- per-tree attributes: terrain, rock, species, tint -----------------------------------------------------------------
_D = {}


def _init2():
    import terrain_dem as T
    import rasterio
    _D["dem"] = T.Dem()
    _D["wc"] = {k: rasterio.open(os.path.join(V.RAW, f)) for k, f in V.WC.items()}


def _vnoise(lat, lon, cell_m, seed):
    """smooth value noise 0..1 on a cell_m metre grid (world-fixed: same value across block edges)."""
    X = np.asarray(lon) * 111320.0 * math.cos(math.radians(35.2)) / cell_m
    Y = np.asarray(lat) * 111320.0 / cell_m
    xi, yi = np.floor(X), np.floor(Y)
    fx, fy = X - xi, Y - yi
    fx, fy = fx * fx * (3 - 2 * fx), fy * fy * (3 - 2 * fy)
    H = lambda a, b: np.modf(np.sin(a * 127.1 + b * 311.7 + seed * 74.7) * 43758.5453)[0] % 1.0
    return (H(xi, yi) * (1 - fx) + H(xi + 1, yi) * fx) * (1 - fy) + (H(xi, yi + 1) * (1 - fx) + H(xi + 1, yi + 1) * fx) * fy


def _landcover(lat, lon):
    from rasterio.windows import Window
    lc = np.zeros(len(lat), np.uint8)
    for k, ds in _D["wc"].items():
        m = (lon >= k) & (lon < k + 3)
        if not m.any():
            continue
        tr = ds.transform
        cw = ((lon[m] - tr.c) / tr.a).astype(np.int64)
        rw = ((lat[m] - tr.f) / tr.e).astype(np.int64)
        blk = ds.read(1, window=Window(int(cw.min()), int(rw.min()), int(cw.max() - cw.min() + 1), int(rw.max() - rw.min() + 1)))
        lc[m] = blk[rw - rw.min(), cw - cw.min()]
    return lc


def _photo_rgb(lat, lon):
    """V-World z17 photo colour (sRGB, 3 x 3 px mean) at points; grey 0 where not cached."""
    from PIL import Image
    x, y = V.merc(lat, lon)
    gx = ((x + V.ORIG) / V.RES17).astype(np.int64)
    gy = ((V.ORIG - y) / V.RES17).astype(np.int64)
    out = np.zeros((len(lat), 3))
    cache = {}
    for t in set(zip((gx // 256).tolist(), (gy // 256).tolist())):
        pth = os.path.join(V.SAT17, str(t[1]), "%d.jpg" % t[0])
        try:
            cache[t] = np.asarray(Image.open(pth).convert("RGB"), np.float64) if os.path.isfile(pth) else None
        except Exception:
            cache[t] = None
    for i in range(len(lat)):
        a = cache.get((int(gx[i] // 256), int(gy[i] // 256)))
        if a is not None:
            px, py = int(gx[i] % 256), int(gy[i] % 256)
            out[i] = a[max(py - 1, 0):py + 2, max(px - 1, 0):px + 2].reshape(-1, 3).mean(0)
    return out


def ridge_tors(f, dem, tree_lat, tree_lon, rng):
    """round 3: granite tors clustered on treeless / sparse ridge and summit cells of this block (12 m candidate grid):
    ~480 m TPI > 20 m or a local summit (120 m TPI > 6 m), slope > 10 deg, WorldCover tree / shrub / grass / bare, > 7 m
    from any tree top. Seeds (3 %) carry 2-5 tors within 14 m; tor half-width 2.5-6 m, height 2-5 m (35 %: 5-12 m)."""
    import buildings_build as B
    from scipy.spatial import cKDTree
    i, j = (int(x) for x in os.path.basename(f)[2:-4].split("_"))
    s_, w_ = i * V.DLA, j * V.DLO
    dla, dlo = 12.0 / 111320.0, 12.0 / (111320.0 * math.cos(math.radians(s_ + V.DLA / 2)))
    LA, LO = np.meshgrid(np.arange(s_ + dla / 2, s_ + V.DLA, dla), np.arange(w_ + dlo / 2, w_ + V.DLO, dlo), indexing="ij")
    LA, LO = LA.ravel(), LO.ravel()
    h0 = dem.msl(LA, LO)
    ok = h0 > 40.0
    if not ok.any():
        return None
    LA, LO, h0 = LA[ok], LO[ok], h0[ok]
    t16 = h0 - dem.msl_ov(LA, LO, 16)
    t4 = h0 - dem.msl_ov(LA, LO, 4)
    d = 12.0
    gx = (dem.msl(LA, LO + dlo) - dem.msl(LA, LO - dlo)) / (2 * d)
    gy = (dem.msl(LA + dla, LO) - dem.msl(LA - dla, LO)) / (2 * d)
    slope = np.degrees(np.arctan(np.hypot(gx, gy)))
    cand = ((t16 > 20) | ((t4 > 6) & (t16 > 8))) & (slope > 10)
    if len(tree_lat):
        kd = cKDTree(np.stack(((tree_lon - w_) * 111320.0 * math.cos(math.radians(s_)), (tree_lat - s_) * 111320.0), 1))
        dd, _ = kd.query(np.stack(((LO - w_) * 111320.0 * math.cos(math.radians(s_)), (LA - s_) * 111320.0), 1))
        cand &= dd > 7.0
    if not cand.any():
        return None
    LA, LO, slope = LA[cand], LO[cand], slope[cand]
    lc = _landcover(LA, LO)
    rgb = _photo_rgb(LA, LO)                                     # round 4: bare beige summit ground in the photo -> rock
    mx, mn = rgb.max(1), rgb.min(1)
    beige = (rgb.mean(1) > 105) & (rgb[:, 1] - np.maximum(rgb[:, 0], rgb[:, 2]) < 4) & ((mx - mn) / np.maximum(mx, 1) < 0.35)
    k = np.isin(lc, (10, 20, 30, 60)) & (rng.random(len(LA)) < np.where(beige, 0.06, 0.003))
    if not k.any():
        return None
    sl, so, ss = LA[k], LO[k], slope[k]
    out_la, out_lo, out_sl = [], [], []
    for a, b, c in zip(sl, so, ss):
        for _ in range(int(rng.integers(3, 7))):                       # round 5: grouped
            ang, rr = rng.uniform(0, 2 * math.pi), rng.uniform(0, 7.0)
            out_la.append(a + rr * math.sin(ang) / 111320.0)
            out_lo.append(b + rr * math.cos(ang) / (111320.0 * math.cos(math.radians(a))))
            out_sl.append(c)
    la, lo, sl_ = np.array(out_la), np.array(out_lo), np.array(out_sl)
    n = len(la)
    big = rng.random(n) < 0.45                                         # round 4: fewer, bigger
    hh = np.where(big, rng.uniform(6.0, 13.0, n), rng.uniform(3.0, 6.0, n))
    r = np.maximum(rng.uniform(4.0, 9.0, n), hh * 0.55)
    mh = B.mesh_height(dem, la, lo)
    try:
        import coast_build as CB
        mh = mh + (CB.rendered_msl(dem, la, lo) - dem.msl(la, lo))
    except Exception:
        pass
    sink = np.minimum(4.0, r * np.tan(np.radians(np.minimum(sl_, 40.0))) * 0.6 + 0.25 * hh)   # partly embedded
    base = mh - V.SINK - sink + dem.geoid_n(la, lo)
    return dict(lat=la, lon=lo, base=base.astype(np.float32), h=(hh + sink).astype(np.float32), r=r.astype(np.float32),
                pid=np.array(P_ROCK, np.int8)[rng.integers(0, 2, n)], tint=(np.asarray(TINT["rock"])[None] * rng.uniform(0.85, 1.12, (n, 1))).astype(np.float32),
                yaw=rng.random(n).astype(np.float32))


def block_attrs(f):
    z = np.load(f)
    if int(z["n"]) == 0:
        return None
    dem = _D["dem"]
    lat, lon = z["lat"], z["lon"]
    n = len(lat)
    rng = np.random.default_rng(zlib.crc32(os.path.basename(f).encode()))
    h0 = dem.msl(lat, lon)
    tpi = h0 - dem.msl_ov(lat, lon, 16)                                  # + ridge / - valley (m, vs ~480 m mean)
    dl = 25.0 / 111320.0
    dn = 25.0 / (111320.0 * np.cos(np.radians(lat)))
    gx = (dem.msl(lat, lon + dn) - dem.msl(lat, lon - dn)) / 50.0       # east slope
    gy = (dem.msl(lat + dl, lon) - dem.msl(lat - dl, lon)) / 50.0       # north slope
    slope = np.degrees(np.arctan(np.hypot(gx, gy)))
    aspect = (np.degrees(np.arctan2(-gx, -gy)) + 360) % 360             # downhill direction, 0 = north, 180 = south
    sw = np.cos(np.radians(aspect - 210.0))                               # +1 = SSW-facing (sunny, dry)
    coast = np.zeros(n, bool)
    for dist in (120.0, 300.0):
        for a in range(0, 360, 45):
            la = lat + dist * math.cos(math.radians(a)) / 111320.0
            lo = lon + dist * math.sin(math.radians(a)) / (111320.0 * np.cos(np.radians(lat)))
            coast |= dem.msl(la, lo) <= 0.5
    # rock outcrop: bright, grey photo under the crown (relative to this block's trees)
    rgb = z["rgb"].astype(np.float64)
    L = rgb.mean(1)
    sat = (rgb.max(1) - rgb.min(1)) / np.maximum(rgb.max(1), 1.0)
    Lm = np.median(L)
    rock = ((L > max(125.0, 1.9 * Lm)) & (sat < 0.30)) | (L > max(165.0, 2.4 * Lm))
    # photo score (v1): darker + bluer than the block's median -> pine
    lin = V.srgb_to_lin(rgb)
    Y = 0.2126 * lin[:, 0] + 0.7152 * lin[:, 1] + 0.0722 * lin[:, 2] + 1e-4
    yel = (lin[:, 0] + lin[:, 1]) / (2 * lin[:, 2] + 1e-4)
    lY, ly = np.log(Y), np.log(yel)
    ph = -((lY - np.median(lY)) / (np.std(lY) + 1e-6) + 0.6 * (ly - np.median(ly)) / (np.std(ly) + 1e-6))   # + = pine-like
    # round 3: finer-grained mix (no single-colour carpet): ~120 m micro-ridges / gullies and 70 m stand patches drive the
    # species as much as the ~480 m ridge / valley; per-tree noise smaller so patches stay coherent
    tpi4 = h0 - dem.msl_ov(lat, lon, 4)
    patch = _vnoise(lat, lon, 70.0, 3) * 2 - 1
    # round 4: pine dominant on ridges, upper slopes and south / west aspects (the lime carpet at Geumjeong / Molundae),
    # oak kept to valleys and gullies
    swt = np.cos(np.radians(aspect - 225.0))                              # +1 = SW, south and west both positive
    up = np.clip((h0 - 120.0) / 300.0, 0, 1)                              # upper slopes
    logit = (0.35 + 0.035 * np.clip(tpi, -30, 30) + 0.08 * np.clip(tpi4, -12, 12) + 0.7 * swt * (slope > 8) + 0.6 * up
             + 1.2 * coast - 1.0 * (tpi < -15) + 0.2 * np.clip(ph, -2.5, 2.5) + 1.0 * patch + rng.normal(0, 0.35, n))
    pine = logit > 0
    h = z["h"].astype(np.float64).copy()
    shrub = ((z["lc"] == 20) & (h < 7.0)) | ((h < 4.5) & (rng.random(n) < 0.6))
    # round 2: 4 crown shapes per species (no clones), rocks + low scrub on ridges / coastal cliffs / photo rock
    pine_pid = np.array(P_PINE)[rng.choice(3, n, p=[0.4, 0.35, 0.25])]
    pid = np.where(pine, np.where(coast | (rng.random(n) < 0.18), P_BPINE, pine_pid), np.array(P_BROAD)[rng.integers(0, 4, n)])
    pid = np.where(shrub, np.array(P_SHRUB)[rng.integers(0, 2, n)], pid)
    ridge = (tpi > 18) & (slope > 16) & ~coast
    cliff = coast & (slope > 22)
    u = rng.random(n)
    tor = rock | (ridge & (u < 0.015)) | (cliff & (u < 0.04))
    scrub = ~tor & ridge & (u > 0.05) & (u < 0.15)
    pid = np.where(scrub, np.array(P_SHRUB)[rng.integers(0, 2, n)], pid)
    pid = np.where(tor, np.array(P_ROCK)[rng.integers(0, 2, n)], pid).astype(np.int8)
    h = np.where(scrub, np.minimum(h * 0.3, 2.5) + 0.8, h)
    h = np.where(tor, rng.uniform(2.0, 6.0, n), h)
    # colour: two species palettes, by aspect (sunny SW slopes warmer / lighter, N slopes bluer / darker) and elevation,
    # +-8 % per tree; the photo only nudges the brightness (^0.25, clamped)
    grp = SPECIES_OF[pid]
    base = np.array([TINT[g] for g in GROUPS])[grp]
    swk = np.clip(sw * np.clip(slope / 20.0, 0, 1), -1, 1)
    asp = np.stack((1 + 0.06 * swk, 1 + 0.04 * swk, 1 - 0.06 * swk), 1)
    elev = (1.0 - 0.06 * np.clip((h0 - 300.0) / 400.0, 0, 1))[:, None]
    jit = rng.uniform(0.92, 1.08, (n, 1)) * rng.uniform(0.97, 1.03, (n, 3))
    Ym = np.median(Y)
    bri = np.clip((Y / Ym) ** 0.25, 0.88, 1.12)[:, None]
    isrock = (grp == 4)[:, None]
    # round 5: colours blend across the pine / oak patch edges (logit near 0 -> in-between colour)
    mixw = (1.0 / (1.0 + np.exp(np.clip(logit, -20, 20) * 1.2)))[:, None]            # 1 = oak side, 0 = pine side
    tp, tb = np.asarray(TINT["pine"]), np.asarray(TINT["broad"])
    blend = np.where(np.isin(pid, P_PINE + (P_BPINE,))[:, None], base + (tb - tp) * 0.4 * mixw,
                     np.where(np.isin(pid, P_BROAD)[:, None], base + (tp - tb) * 0.4 * (1 - mixw), base))
    tint = np.where(isrock, base * rng.uniform(0.9, 1.08, (n, 1)), blend * asp * elev * jit * bri)
    # coast-aware rendered terrain (sim/coast_build.py, frozen 11-10 21:29): the shore tiles carry rendered_msl - msl on top
    # of the DEM mesh the prep stood the trees on -> same delta here; trees on the OSM sea side (signed distance < 0) dropped
    basez = z["base"].astype(np.float64)
    seaside = np.zeros(n, bool)
    CB = None
    try:
        import coast_build as CB
        sd, _k = CB.field_at(lat, lon)
        rend = CB.rendered_msl(dem, lat, lon)
        basez = basez + (rend - h0)
        seaside = np.asarray(sd) < 0
        # within 80 m of the coast the rendered shore tiles are ~2 m meshes = rendered_msl itself (the prep's old 33 x 33 mesh
        # height left 5,341 trees > 2 m under the 2.8 m sea walls and 44 floating; coast agent check 11-11)
        nearc = np.abs(np.asarray(sd)) < 80.0
        basez = np.where(nearc, rend + dem.geoid_n(lat, lon) - V.SINK, basez)
    except Exception as e:                                                  # no coast field -> prep heights as they are
        print("coast delta skipped", repr(e)[:100])
    keep = ~seaside
    r0 = np.asarray(z["r"], np.float64)
    r = r0 * (R_FAC / 0.6) * rng.uniform(0.6, 1.4, n)                     # crown size 0.6-1.4 x, overlapping
    r = np.minimum(r, np.maximum(1.2, 1.5 + 0.3 * h) * 1.25)
    r = np.where(tor, np.clip(r0 * 1.2, 2.5, 6.0), r)
    r = np.where(scrub, np.clip(r0 * 0.7, 1.0, 2.5), r)
    yaw = z["yaw"].astype(np.float64)
    # clumped infill: inside closed broadleaf / pine forest (WorldCover tree, >= 3 tops within 7 m) 35 % of the trees get a
    # smaller neighbour 0.5-1.0 crown radius away (same species, other shape) -> groups and no lawn between crowns
    from scipy.spatial import cKDTree
    x_m = (lon - lon.mean()) * 111320.0 * np.cos(np.radians(lat.mean()))
    y_m = (lat - lat.mean()) * 111320.0
    cnt = np.array([len(q) for q in cKDTree(np.stack((x_m, y_m), 1)).query_ball_point(np.stack((x_m, y_m), 1), 7.0)])
    inner = keep & (z["lc"] == 10) & ~coast & ~tor & ~scrub & ~shrub & (cnt >= 4) & (rng.random(n) < 0.35)
    ii = np.nonzero(inner)[0]
    ang = rng.uniform(0, 2 * math.pi, len(ii))
    dd = r[ii] * rng.uniform(0.5, 1.0, len(ii))
    slat = lat[ii] + dd * np.sin(ang) / 111320.0
    slon = lon[ii] + dd * np.cos(ang) / (111320.0 * np.cos(np.radians(lat[ii])))
    sh0 = dem.msl(slat, slon)
    sbase = basez[ii] + (sh0 - h0[ii])
    if CB is not None:
        try:
            sbase = sbase + (CB.rendered_msl(dem, slat, slon) - sh0) - (CB.rendered_msl(dem, lat[ii], lon[ii]) - h0[ii])
        except Exception:
            pass
    spid = pid[ii].copy()
    sp_pine = np.isin(spid, P_PINE)
    spid = np.where(sp_pine, np.array(P_PINE)[rng.integers(0, 3, len(ii))], np.where(np.isin(spid, P_BROAD), np.array(P_BROAD)[rng.integers(0, 4, len(ii))], spid)).astype(np.int8)
    out = dict(lat=np.concatenate((lat[keep], slat)), lon=np.concatenate((lon[keep], slon)),
               base=np.concatenate((basez[keep], sbase)).astype(np.float32),
               h=np.concatenate((h[keep], h[ii] * rng.uniform(0.6, 0.85, len(ii)))).astype(np.float32),
               r=np.concatenate((r[keep], r[ii] * rng.uniform(0.55, 0.85, len(ii)))).astype(np.float32),
               pid=np.concatenate((pid[keep], spid)).astype(np.int8),
               tint=np.concatenate((tint[keep], tint[ii] * rng.uniform(0.93, 1.07, (len(ii), 1)))).astype(np.float32),
               yaw=np.concatenate((yaw[keep], rng.random(len(ii)))).astype(np.float32))
    rt = ridge_tors(f, dem, lat[keep], lon[keep], rng)
    if rt is not None:
        for kk in out:
            out[kk] = np.concatenate((out[kk], rt[kk].astype(out[kk].dtype)))
    st = dict(n=n, ridge_tors=0 if rt is None else int(len(rt["lat"])), rock_photo=int(rock.sum()), tor=int((tor & keep).sum()), scrub=int((scrub & keep).sum()), infill=int(len(ii)),
              seaside=int(seaside.sum()), pine=int((pine & keep & ~shrub & ~tor & ~scrub).sum()), shrub=int((shrub & keep).sum()),
              coast=int(coast[keep].sum()), ridge=int((tpi[keep] > 10).sum()), valley=int((tpi[keep] < -10).sum()),
              pine_ridge=int((pine & keep & ~shrub & (tpi > 10)).sum()), pine_valley=int((pine & keep & ~shrub & (tpi < -10)).sum()))
    return out, st


# ---- tiles ---------------------------------------------------------------------------------------------------------------
def tile_glb2(D, idx, center, near, pal, pidx):
    import buildings_build as B
    R = B.enu_rot(*center)
    C0 = B.ecef(np.array(center[0]), np.array(center[1]), np.array(0.0)).reshape(3)
    lat, lon = D["lat"][idx], D["lon"][idx]
    base, h, r = D["base"][idx].astype(np.float64), D["h"][idx].astype(np.float64), D["r"][idx].astype(np.float64)
    E = (B.ecef(lat, lon, base) - C0) @ R
    S = np.array([[1, 0, 0], [0, 0, 1], [0, -1, 0]], np.float64)
    Tl = E @ S.T
    yaw = D["yaw"][idx].astype(np.float64) * 2 * math.pi
    Rq = np.stack((np.zeros_like(yaw), np.sin(yaw / 2), np.zeros_like(yaw), np.cos(yaw / 2)), 1)
    hh = h + V.SINK
    Sc = np.stack((r, hh, r), 1)
    pid, bins = D["pid"][idx], D["bin"][idx]
    groups = []
    for p_ in np.unique(pid):
        for b_ in range(NBIN):
            m = (pid == p_) & (bins == b_)
            if m.any():
                groups.append((pidx[(int(p_), near, b_)], Tl[m], Rq[m], Sc[m]))
    Mx = np.eye(4)
    Mx[:3, :3] = S @ R @ S.T
    Mx[:3, 3] = S @ C0
    glb = V.glb_instanced(pal, groups, Mx)
    region = [math.radians(float(lon.min()) - 1e-5), math.radians(float(lat.min()) - 1e-5), math.radians(float(lon.max()) + 1e-5),
              math.radians(float(lat.max()) + 1e-5), float(base.min()), float((base + hh).max())]
    return glb, region


def tiles2(args):
    import shutil
    from multiprocessing import Pool
    t0 = time.time()
    fs = sorted(glob.glob(os.path.join(V.WORK, "b_*.npz")))
    parts, stats = {}, []
    with Pool(int(os.environ.get("GYROSIM_VEG_PROCS", "12")), initializer=_init2) as pool:
        for res in pool.imap(block_attrs, fs, chunksize=4):
            if res is None:
                continue
            o, st = res
            stats.append(st)
            for k, v in o.items():
                parts.setdefault(k, []).append(v)
    D = {k: np.concatenate(v) for k, v in parts.items()}
    nt = len(D["lat"])
    tot = {k: int(sum(s[k] for s in stats)) for k in stats[0]}
    print("trees %d (%.0f s) %s" % (nt, time.time() - t0, json.dumps(tot)), flush=True)
    # colour bins per prototype group (k-means on the tint)
    grp = SPECIES_OF[D["pid"]]
    D["bin"] = np.zeros(nt, np.int8)
    pals = {}
    for g in range(len(GROUPS)):
        m = grp == g
        if m.sum() < NBIN * 10:
            pals[g] = np.tile(np.asarray(TINT[GROUPS[g]], np.float32), (NBIN, 1)); continue
        cen = V.palette(D["tint"][m], NBIN, seed=11 + g)
        D["bin"][m] = ((D["tint"][m][:, None, :] - cen[None]) ** 2).sum(-1).argmin(1)
        pals[g] = cen
    drop = dropin_protos()
    protos, pidx, tri = [], {}, []
    for p_ in range(len(PROTOS)):
        g = GROUPS[SPECIES_OF[p_]]
        nm = PROTOS[p_][0]
        trunk = TRUNK["pine" if nm in ("pine", "bpine") else ("broad" if nm == "broad" else "shrub")]
        for near in (True, False):
            dm = drop.get(nm) if (near and not proxy_files(nm)) else None
            for b_ in range(NBIN):
                tint = pals[SPECIES_OF[p_]][b_]
                if dm:
                    arr = dropin_arrays(dm[PROTOS[p_][1] % len(dm)], nm)
                    arr = (arr[0], arr[1], np.concatenate((lin_to_srgb8(V.srgb_to_lin(arr[2][:, :3].astype(np.float64)) / np.mean(TINT[nm]) * np.mean(tint)), arr[2][:, 3:]), 1).astype(np.uint8), arr[3])
                else:
                    arr = build_proto(p_, not near).arrays(tint, tint if nm == "rock" else trunk)
                pidx[(p_, near, b_)] = len(protos)
                protos.append(arr)
                tri.append(len(arr[3]) // 3)
    tmp = TILES2 + "_tmp"
    if os.path.isdir(tmp):
        shutil.rmtree(tmp)
    os.makedirs(os.path.join(tmp, "b")); os.makedirs(os.path.join(tmp, "c"))
    bi = np.floor(D["lat"] / V.DLA).astype(np.int64); bj = np.floor(D["lon"] / V.DLO).astype(np.int64)
    ci = np.floor(D["lat"] / (V.DLA / V.SUB)).astype(np.int64); cj = np.floor(D["lon"] / (V.DLO / V.SUB)).astype(np.int64)
    order = np.lexsort((cj, ci, bj, bi))
    keyB = bi[order] * 100000 + bj[order]
    cuts = np.nonzero(np.diff(keyB))[0] + 1
    nodes_a, sizes, ntris, nodes_per = [], {}, dict(near=0, far=0), dict(near=[], far=[])
    tri_of = lambda near, ids, bins: int(sum(tri[pidx[(int(p), near, int(b))]] for p, b in zip(ids, bins)))

    def union(a, b):
        return [min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3]), min(a[4], b[4]), max(a[5], b[5])]
    for grp_ in np.split(order, cuts):
        i, j = int(bi[grp_[0]]), int(bj[grp_[0]])
        glb, regB = tile_glb2(D, grp_, ((i + 0.5) * V.DLA, (j + 0.5) * V.DLO), False, protos, pidx)
        fn = "b/%d_%d.glb" % (i, j)
        open(os.path.join(tmp, fn), "wb").write(glb)
        sizes[fn] = len(glb)
        ntris["far"] += tri_of(False, D["pid"][grp_], D["bin"][grp_])
        nodes_per["far"].append(len(np.unique(D["pid"][grp_].astype(np.int64) * 10 + D["bin"][grp_])))
        kids = []
        kc = ci[grp_] * 100000 + cj[grp_]
        o2 = np.argsort(kc, kind="stable")
        g2 = grp_[o2]
        for sub in np.split(g2, np.nonzero(np.diff(kc[o2]))[0] + 1):
            a, b = int(ci[sub[0]]), int(cj[sub[0]])
            glb, reg = tile_glb2(D, sub, ((a + 0.5) * V.DLA / V.SUB, (b + 0.5) * V.DLO / V.SUB), True, protos, pidx)
            fn = "c/%d_%d.glb" % (a, b)
            open(os.path.join(tmp, fn), "wb").write(glb)
            sizes[fn] = len(glb)
            ntris["near"] += tri_of(True, D["pid"][sub], D["bin"][sub])
            nodes_per["near"].append(len(np.unique(D["pid"][sub].astype(np.int64) * 10 + D["bin"][sub])))
            kids.append(dict(boundingVolume=dict(region=reg), geometricError=GE2["c"], content=dict(uri=fn)))
            regB = union(regB, reg)
        nodeB = dict(boundingVolume=dict(region=regB), geometricError=GE2["b"], refine="REPLACE", content=dict(uri="b/%d_%d.glb" % (i, j)), children=kids)
        nodes_a.append(dict(boundingVolume=dict(region=regB), geometricError=GE2["a"], refine="REPLACE", children=[nodeB],
                            extras=dict(trees=int(len(grp_)))))
    reg = nodes_a[0]["boundingVolume"]["region"]
    for nd in nodes_a[1:]:
        reg = union(reg, nd["boundingVolume"]["region"])
    ts = dict(asset=dict(version="1.1", tilesetVersion=time.strftime("%Y%m%d%H%M%S"), generator="gyro-sim-chair sim/veg_v2.py",
                         copyright="Meta/WRI canopy height (CC BY 4.0); ESA WorldCover 2021 (CC BY 4.0); © OpenStreetMap contributors (ODbL)"),
              geometricError=GE2["root"] * 2, root=dict(boundingVolume=dict(region=reg), geometricError=GE2["root"], refine="REPLACE", children=nodes_a))
    json.dump(ts, open(os.path.join(tmp, "tileset.json"), "w", encoding="utf-8"))
    pc = np.bincount(D["pid"], minlength=len(PROTOS))
    out = dict(made=time.strftime("%Y-%m-%d %H:%M:%S"), seconds=round(time.time() - t0), trees=int(nt), totals=tot,
               per_prototype={"%s%d" % PROTOS[k]: int(pc[k]) for k in range(len(PROTOS))},
               h_mean=round(float(D["h"].mean()), 2), r_mean=round(float(D["r"].mean()), 2),
               blocks=len(nodes_a), content_tiles=len(sizes), bytes=int(sum(sizes.values())), largest_tile=int(max(sizes.values())),
               triangles=ntris, nodes_per_tile=dict(near_mean=round(float(np.mean(nodes_per["near"])), 1), near_max=int(max(nodes_per["near"])),
                                                    far_mean=round(float(np.mean(nodes_per["far"])), 1)),
               prototype_triangles=dict(near=[tri[pidx[(p, True, 0)]] for p in range(len(PROTOS))], far=[tri[pidx[(p, False, 0)]] for p in range(len(PROTOS))]),
               palettes={GROUPS[k]: np.asarray(v).round(4).tolist() for k, v in pals.items()}, tint=TINT, r_fac=R_FAC, ge=GE2,
               dropin=dict(dir=PROTOS_DIR, glb={k: len(v) for k, v in drop.items()}, proxies={g: [os.path.basename(f) for f in proxy_files(g)] for g in ("pine", "broad")},
                           pick=PROXY_PICK), inputs=dict(work=V.WORK))
    json.dump(out, open(os.path.join(tmp, "build.json"), "w"), indent=1)
    if os.environ.get("GYROSIM_VEG_SWAP_ANY", "0") != "1":     # never swap tiles under a running editor (it streams them)
        import subprocess
        tl = subprocess.run(["tasklist", "/fo", "csv", "/nh"], capture_output=True, text=True).stdout.lower()
        if "unrealeditor" in tl:
            print("an UnrealEditor is running: new tiles left in", tmp, "- swap later (no editor) or GYROSIM_VEG_SWAP_ANY=1")
            return
    if os.path.isdir(TILES2):
        prev = TILES2 + "_prev"
        if os.path.isdir(prev):
            shutil.rmtree(prev)
        os.replace(TILES2, prev)
    os.replace(tmp, TILES2)
    print("done:", json.dumps({k: v for k, v in out.items() if k not in ("palettes",)}), flush=True)


# ---- preview (software render of the prototypes, for checking shapes without Unreal) ------------------------------------
def preview(outdir):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from mpl_toolkits.mplot3d.art3d import Poly3DCollection
    os.makedirs(outdir, exist_ok=True)
    sun = np.array([0.5, 0.75, 0.35]); sun /= np.linalg.norm(sun)
    fig = plt.figure(figsize=(len(PROTOS) * 2.6, 6.2), dpi=110)
    for row, near in enumerate((True, False)):
        for p_ in range(len(PROTOS)):
            g = GROUPS[SPECIES_OF[p_]]
            nm = PROTOS[p_][0]
            trunk = TRUNK["pine" if nm in ("pine", "bpine") else ("broad" if nm == "broad" else "shrub")]
            P, Nn, Cu, I = build_proto(p_, not near).arrays(TINT[g], TINT[g] if nm == "rock" else trunk)
            col = V.srgb_to_lin(Cu[:, :3].astype(np.float64))
            ao = (Cu[:, 3] % 64) / 63.0
            sh = (0.25 + 0.9 * np.clip(Nn @ sun, 0, 1))[:, None] * col * (0.4 + 0.6 * ao[:, None]) * 6
            tri = I.reshape(-1, 3)
            ax = fig.add_subplot(2, len(PROTOS), row * len(PROTOS) + p_ + 1, projection="3d")
            Pd = P[:, [0, 2, 1]] * np.array([3.6, 3.6, 12.0])        # a 12 m tree, crown radius 3.6 m (z up)
            fc = np.clip(sh[tri].mean(1), 0, 1) ** (1 / 2.2)
            pc = Poly3DCollection(Pd[tri], facecolors=fc, edgecolors="none")
            ax.add_collection3d(pc)
            ax.set_xlim(-6, 6); ax.set_ylim(-6, 6); ax.set_zlim(0, 12.5)
            ax.view_init(elev=18 if row == 0 else 35, azim=-60)
            ax.set_box_aspect((12, 12, 12.5))
            ax.set_axis_off()
            ax.set_title("%s%d %s %d tri" % (nm, PROTOS[p_][1], "near" if near else "far", len(tri)), fontsize=8)
    fig.tight_layout()
    fn = os.path.join(outdir, "protos_v2%s.png" % ("_fab" if PROTOS_DIR else ""))
    fig.savefig(fn)
    print("preview", fn)


def swap():
    """move a finished tiles_v2_tmp (left by --tiles while an editor ran) into place, keeping tiles_v2_prev."""
    import shutil, subprocess
    tmp = TILES2 + "_tmp"
    if not os.path.isfile(os.path.join(tmp, "build.json")):
        print("nothing to swap"); return
    if "unrealeditor" in subprocess.run(["tasklist", "/fo", "csv", "/nh"], capture_output=True, text=True).stdout.lower():
        print("an UnrealEditor is running - not swapping"); return
    if os.path.isdir(TILES2):
        prev = TILES2 + "_prev"
        if os.path.isdir(prev):
            shutil.rmtree(prev)
        os.replace(TILES2, prev)
    os.replace(tmp, TILES2)
    print("swapped", TILES2)


if __name__ == "__main__":
    a = sys.argv[1:]
    if "--swap" in a:
        swap()
    if "--preview" in a:
        preview(a[a.index("--preview") + 1])
    if "--tiles" in a:
        tiles2(a)
