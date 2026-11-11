"""Leaf-card trees (11-11, docs/research/tree-generators.md recommendation #1): crowns made of alpha-masked cards instead of
closed vertex-coloured shells, so the silhouette is ragged and the crown has see-through gaps.

  - 소나무 (Pinus densiflora) x10: leaning / curved trunk, grey foot -> orange-brown upper bark, 3-6 limbs ending in FLAT
    needle pads (umbrella crown); var 8-9 = narrow dense-stand pines (tiers). Each pad = 3-5 clumps x 3-5 cards.
  - 참나무류 (oak) x5: short trunk forking into 2-3 stems, 5-7 lobes, each lobe = clumps of 3-5 cards, more random facing.
  - cards: per vertex normal = clump-sphere normal + crown-sphere normal + up bias + per-card noise (so a clump shades as a
    small lit dome, not as one big ball and not as flat paper).
  - texture: one 1024x1024 RGBA atlas drawn here in Python (2 needle-pad cells, 2 oak-leaf cells; no third-party images).
  - every card is emitted twice (front + back, same normals, single-sided material): renderers that flip the normal on
    back faces of a two-sided material would otherwise invert the custom normals.
  - glTF: material 0 = foliage (atlas, alphaMode MASK, cutoff 0.5), material 1 = bark (vertex colour only). COLOR_0 =
    linear rgb tint x AO. y-up, metres, tree base at the origin.

    python -I sim/veg_cards.py OUTDIR              -> OUTDIR/atlas.png, pine_00..09.glb, oak_00..04.glb, cards.json
    python -I sim/veg_cards.py OUTDIR --baseline   also baseline_pine.glb / baseline_oak.glb (current veg_shape protos)
Preview renders (headless Blender): sim/veg_cards_render.py.
"""
import io, json, math, os, struct, sys, time, site
if sys.flags.isolated:
    site.addsitedir(site.getusersitepackages())
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import numpy as np                                        # noqa: E402

UP = np.array([0.0, 1.0, 0.0])
ATLAS = 1024
CELL = {"pineA": (0, 0), "pineB": (1, 0), "oakA": (0, 1), "oakB": (1, 1)}   # (col, row) of 512 cells, uv origin top-left


# ---------------------------------------------------------------- texture atlas -------------------------------------------
def _srgb(c):
    return tuple(int(max(0, min(255, round(v)))) for v in c)


def _draw_pine_cell(draw, ox, oy, S, rg):
    """needle pad seen from above: 8-12 twigs from the centre, needle pairs along them, dense tufts at the tips."""
    cx, cy = ox + S / 2, oy + S / 2
    n_tw = rg.integers(8, 13)
    a0 = rg.uniform(0, 2 * math.pi)
    twigs = []
    for k in range(n_tw):
        a = a0 + 2 * math.pi * k / n_tw + rg.uniform(-0.25, 0.25)
        L = S * 0.5 * rg.uniform(0.55, 0.92)
        bend = rg.uniform(-0.35, 0.35)
        twigs.append((a, L, bend))
    # twigs (thin brown) first, then needles: inner (dark) to outer (lighter) for a self-shadowed look
    pts_all = []
    for a, L, bend in twigs:
        pts = []
        for i in range(12):
            t = i / 11
            aa = a + bend * t
            pts.append((cx + math.cos(aa) * L * t, cy + math.sin(aa) * L * t))
        pts_all.append(pts)
        draw.line(pts, fill=_srgb((70, 48, 30)) + (255,), width=int(S * 0.012))
    for pass_ in range(2):
        for (a, L, bend), pts in zip(twigs, pts_all):
            for i in range(2, 12):
                t = i / 11
                if pass_ == 0 and t > 0.6 or pass_ == 1 and t <= 0.6:
                    continue
                x, y = pts[i]
                aa = a + bend * t
                nb = 9 if t < 0.85 else 15                         # tip tuft denser
                for j in range(nb):
                    side = 1 if j % 2 == 0 else -1
                    ang = aa + side * rg.uniform(0.25, 0.95) * (0.7 if t > 0.85 else 1.0)
                    ln = S * rg.uniform(0.07, 0.12) * (0.75 + 0.35 * t)
                    shade = 0.62 + 0.55 * t + rg.uniform(-0.12, 0.12)
                    col = np.array([30, 54, 38]) * shade + rg.uniform(-5, 5, 3)
                    col[2] += 4                                    # blue-green
                    draw.line([(x, y), (x + math.cos(ang) * ln, y + math.sin(ang) * ln)],
                              fill=_srgb(col) + (255,), width=max(2, int(S * 0.011)))


def _leaf_poly(x, y, ang, L, W, rg, lobes):
    pts = []
    for i in range(24):
        t = 2 * math.pi * i / 24
        r_l = 1.0 + (0.18 * math.sin(t * lobes) if lobes else 0.0)
        px, py = math.cos(t) * L / 2 * r_l, math.sin(t) * W / 2 * r_l
        ca, sa = math.cos(ang), math.sin(ang)
        pts.append((x + L / 2 * ca + px * ca - py * sa, y + L / 2 * sa + px * sa + py * ca))
    return pts


def _draw_oak_cell(draw, ox, oy, S, rg):
    """oak leaf cluster: twigs from the bottom-centre region, ~70 lobed leaves, darker inside / lighter at the rim."""
    cx, cy = ox + S / 2, oy + S / 2
    n_tw = rg.integers(6, 9)
    leaves = []
    for k in range(n_tw):
        a = 2 * math.pi * k / n_tw + rg.uniform(-0.3, 0.3)
        L = S * 0.5 * rg.uniform(0.45, 0.68)
        ex, ey = cx + math.cos(a) * L, cy + math.sin(a) * L
        draw.line([(cx, cy), (ex, ey)], fill=_srgb((66, 52, 36)) + (255,), width=int(S * 0.012))
        for i in range(rg.integers(12, 18)):
            t = rg.uniform(0.15, 1.0)
            x, y = cx + (ex - cx) * t, cy + (ey - cy) * t
            ang = a + rg.uniform(-1.2, 1.2)
            leaves.append((t, x, y, ang))
    leaves.sort(key=lambda q: q[0])
    for t, x, y, ang in leaves:
        L = S * rg.uniform(0.11, 0.16)
        W = L * rg.uniform(0.42, 0.55)
        shade = 0.6 + 0.5 * t + rg.uniform(-0.12, 0.12)
        col = np.array([58, 84, 34]) * shade + rg.uniform(-6, 6, 3)
        draw.polygon(_leaf_poly(x, y, ang, L, W, rg, 5), fill=_srgb(col) + (255,))
        cm = col * 0.8
        draw.line([(x, y), (x + math.cos(ang) * L * 0.9, y + math.sin(ang) * L * 0.9)], fill=_srgb(cm) + (255,), width=2)


def make_atlas(seed=7):
    from PIL import Image, ImageDraw, ImageFilter
    SS = 2                                                    # supersample
    big = Image.new("RGBA", (ATLAS * SS, ATLAS * SS), (0, 0, 0, 0))
    d = ImageDraw.Draw(big)
    S = ATLAS // 2 * SS
    rg = np.random.default_rng(seed)
    for name, (cx, cy) in CELL.items():
        pad = int(S * 0.03)
        (_draw_pine_cell if name.startswith("pine") else _draw_oak_cell)(d, cx * S + pad, cy * S + pad, S - 2 * pad, rg)
    img = big.resize((ATLAS, ATLAS), Image.LANCZOS)
    a = np.asarray(img).astype(np.float32)
    # bleed colour into transparent texels (no dark halo when filtered / mip-mapped)
    rgb, al = a[..., :3], a[..., 3:] / 255.0
    acc = Image.fromarray(np.clip(rgb * al, 0, 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(10))
    wgt = Image.fromarray(np.clip(al[..., 0] * 255, 0, 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(10))
    accn = np.asarray(acc).astype(np.float32) / np.maximum(np.asarray(wgt).astype(np.float32)[..., None] / 255.0, 1e-3)
    out = np.where(al > 0.02, rgb, np.clip(accn, 0, 255))          # PIL resizes RGBA premultiplied: rgb is straight
    res = np.concatenate((np.clip(out, 0, 255), al * 255), -1).astype(np.uint8)
    return Image.fromarray(res, "RGBA")


# ---------------------------------------------------------------- geometry -------------------------------------------------
class Tree:
    def __init__(self):
        self.fol = dict(P=[], N=[], UV=[], C=[])              # cards (triangle list, 4 verts / quad)
        self.bark = dict(P=[], N=[], C=[], I=[])
        self.nb = 0

    # trunk / limb tube
    def tube(self, pts, rads, cols, sides):
        pts = np.asarray(pts, np.float64)
        k = len(pts)
        P, Nn, C = [], [], []
        for i in range(k):
            d = pts[min(i + 1, k - 1)] - pts[max(i - 1, 0)]
            d /= np.linalg.norm(d)
            a = np.cross(d, [0.0, 0.0, 1.0]) if abs(d[2]) < 0.9 else np.cross(d, [1.0, 0.0, 0.0])
            a /= np.linalg.norm(a)
            b = np.cross(d, a)
            for q in range(sides):
                t = 2 * math.pi * q / sides
                n = math.cos(t) * a + math.sin(t) * b
                P.append(pts[i] + rads[i] * n); Nn.append(n); C.append(cols[i])
        F = []
        for i in range(k - 1):
            for q in range(sides):
                a0, b0 = i * sides + q, i * sides + (q + 1) % sides
                F += [(a0, b0 + sides, b0), (a0, a0 + sides, b0 + sides)]
        self.bark["P"].append(np.array(P)); self.bark["N"].append(np.array(Nn)); self.bark["C"].append(np.array(C))
        self.bark["I"].append(np.array(F) + self.nb)
        self.nb += len(P)

    def card(self, c, size, facing, spin, cell, flip, clump_c, crown_c, rg, tint, ao, upw, crown_w):
        """square card centred at c, normal ~facing, rotated by spin around it; uv = atlas cell; emitted front + back."""
        f = facing / np.linalg.norm(facing)
        a = np.cross(f, UP if abs(f[1]) < 0.95 else np.array([1.0, 0, 0])); a /= np.linalg.norm(a)
        b = np.cross(f, a)
        ca, sa = math.cos(spin), math.sin(spin)
        a, b = ca * a + sa * b, -sa * a + ca * b
        h = size / 2
        corners = [c - a * h - b * h, c + a * h - b * h, c + a * h + b * h, c - a * h + b * h]
        u0, v0 = CELL[cell][0] * 0.5, CELL[cell][1] * 0.5
        uv = [(0, 1), (1, 1), (1, 0), (0, 0)]
        if flip:
            uv = [(1 - u, v) for u, v in uv]
        uv = [(u0 + 0.5 * u, v0 + 0.5 * v) for u, v in uv]
        cn = rg.normal(0, 1, 3) * 0.18                       # per-card noise
        Ns = []
        for p in corners:
            n1 = p - clump_c; n1 /= np.linalg.norm(n1) + 1e-9
            n2 = p - crown_c; n2 /= np.linalg.norm(n2) + 1e-9
            n = 0.55 * n1 + crown_w * n2 + upw * UP + cn
            Ns.append(n / np.linalg.norm(n))
        cols = [np.asarray(tint) * ao] * 4
        back = [p - f * 0.004 for p in corners]              # back copy 4 mm behind (no coplanar pair)
        for k, tri in enumerate(((0, 1, 2), (0, 2, 3), (0, 2, 1), (0, 3, 2))):    # front + back
            for i in tri:
                self.fol["P"].append(corners[i] if k < 2 else back[i]); self.fol["N"].append(Ns[i]); self.fol["UV"].append(uv[i]); self.fol["C"].append(cols[i])

    @property
    def ntri(self):
        return len(self.fol["P"]) // 3 + sum(len(f) for f in self.bark["I"])

    @property
    def ncards(self):
        return len(self.fol["P"]) // 12


BARK_FOOT = np.array([0.105, 0.090, 0.075])                 # linear grey-brown
BARK_ORANGE = np.array([0.30, 0.135, 0.06])                  # linear orange-brown (upper red pine trunk)
BARK_OAK = np.array([0.10, 0.095, 0.085])


def _trunk_line(y1, lean_deg, az, wob, rg, n=6):
    t = np.linspace(0, 1, n)
    lean = math.tan(math.radians(lean_deg)) * y1
    ph = rg.uniform(0, 2 * math.pi, 2)
    off = lean * t ** 1.5
    x = off * math.cos(az) + wob * np.sin(t * 4.0 + ph[0])
    z = off * math.sin(az) + wob * np.sin(t * 3.3 + ph[1])
    y = -0.4 + (y1 + 0.4) * t
    return np.stack((x, y, z), 1)


def _clump_cards(T, cc, size, n_cards, cells, rg, crown_c, tint, ao, flat, upw, crown_w):
    """n_cards around a clump centre; flat in [0, 1]: 1 = cards near-horizontal (pine pads), 0 = random facing (oak)."""
    for j in range(n_cards):
        if j == 0 or rg.uniform() < flat:
            tilt = rg.uniform(0, 0.45 if j == 0 else 0.8)            # rad from up
        else:
            tilt = rg.uniform(0.6, 1.5)
        yaw = rg.uniform(0, 2 * math.pi)
        facing = np.array([math.sin(tilt) * math.cos(yaw), math.cos(tilt), math.sin(tilt) * math.sin(yaw)])
        off = rg.normal(0, 1, 3) * size * np.array([0.18, 0.08 + 0.12 * (1 - flat), 0.18])
        T.card(cc + off, size * rg.uniform(1.25, 1.6), facing, rg.uniform(0, 2 * math.pi), cells[rg.integers(len(cells))],
               bool(rg.integers(2)), cc, crown_c, rg, tint * rg.uniform(0.88, 1.12), ao * rg.uniform(0.9, 1.05), upw, crown_w)


PINE_TINT = np.array([1.0, 1.0, 1.0])
OAK_TINT = np.array([1.0, 1.0, 1.0])


def pine(var):
    rg = np.random.default_rng(5100 + var)
    T = Tree()
    narrow = var >= 8
    H = rg.uniform(10.5, 14.0) if not narrow else rg.uniform(12, 15)
    R = (rg.uniform(3.2, 4.6) if not narrow else rg.uniform(1.9, 2.5))
    az = rg.uniform(0, 2 * math.pi)
    lean = rg.uniform(4, 18) if not narrow else rg.uniform(2, 7)
    y_top = (rg.uniform(0.78, 0.86) if not narrow else 0.93) * H
    tr = _trunk_line(y_top, lean, az, 0.10, rg)
    w = np.clip((tr[:, 1] - 0.3 * H) / (0.25 * H), 0, 1)[:, None]
    T.tube(tr, np.linspace(0.24 if not narrow else 0.19, 0.07, len(tr)), BARK_FOOT * (1 - w) + BARK_ORANGE * w, sides=6)
    top = tr[-1]
    crown_c = np.array([top[0], (0.80 if not narrow else 0.72) * H, top[2]])
    pads = []
    if not narrow:
        n_up, n_lo = rg.integers(3, 5), rg.integers(1, 3)
        a0 = rg.uniform(0, 2 * math.pi)
        for q in range(n_up + n_lo):
            up = q < n_up
            n_, q_ = (n_up, q) if up else (n_lo, q - n_up)
            a = a0 + 2 * math.pi * (q_ + (0 if up else 0.5) + rg.uniform(-0.18, 0.18)) / n_
            if var in (1, 4, 7):                                   # lopsided towards the lean
                a = az + (a - az) * 0.6
            rad = (rg.uniform(0.40, 0.68) if up else rg.uniform(0.55, 0.85)) * R
            y = (rg.uniform(0.86, 0.96) if up else rg.uniform(0.66, 0.78)) * H
            pads.append((np.array([top[0] + rad * math.cos(a), y, top[2] + rad * math.sin(a)]), rg.uniform(1.6, 2.3)))
        pads.append((np.array([top[0], 0.95 * H, top[2]]) + rg.uniform(-0.3, 0.3, 3) * [1, 0, 1], rg.uniform(1.4, 1.8)))
    else:
        for q in range(5):
            y = (0.55 + 0.09 * q) * H
            a = rg.uniform(0, 2 * math.pi)
            rad = R * (0.75 - 0.1 * q) * rg.uniform(0.6, 1.0)
            pc = tr[np.argmin(abs(tr[:, 1] - y))]
            pads.append((np.array([pc[0] + rad * math.cos(a), y, pc[2] + rad * math.sin(a)]), rg.uniform(1.0, 1.4) * (1 - 0.08 * q)))
        pads.append((top + [0, 0.5, 0], 0.9))
    # limbs: from the trunk to every pad except the top one
    for p, pr in pads[:-1]:
        y0 = min(p[1] - rg.uniform(0.8, 2.0), top[1] - 0.2)
        b0 = tr[np.argmin(abs(tr[:, 1] - y0))].copy(); b0[1] = y0
        mid = (b0 + p) / 2 + [0, 0.5, 0]
        T.tube([b0, mid, p - [0, 0.35 * pr, 0]], [0.10, 0.07, 0.04], [BARK_ORANGE] * 3, sides=4)
    for k, (p, pr) in enumerate(pads):
        n_cl = rg.integers(3, 5) if not narrow else rg.integers(2, 4)
        for i in range(n_cl):
            ang = rg.uniform(0, 2 * math.pi)
            rr = 0 if i == 0 else pr * rg.uniform(0.45, 0.85)
            cc = p + [rr * math.cos(ang), rg.uniform(-0.15, 0.25) * pr, rr * math.sin(ang)]
            depth = np.linalg.norm((cc - crown_c) / [R, 0.25 * H, R])
            hf = np.clip((cc[1] - 0.6 * H) / (0.4 * H), 0, 1)
            ao = np.clip((0.55 + 0.45 * min(depth, 1.0)) * (0.72 + 0.28 * hf), 0.3, 1.0)
            _clump_cards(T, cc, pr * rg.uniform(0.8, 1.05), rg.integers(3, 6), ["pineA", "pineB"], rg, crown_c,
                         PINE_TINT, ao, flat=0.6 if not narrow else 0.45, upw=0.45, crown_w=0.3)
    return T, dict(H=round(H, 2), R=round(R, 2), lean=round(lean, 1), kind="narrow" if narrow else "umbrella")


def oak(var):
    rg = np.random.default_rng(6100 + var)
    T = Tree()
    H = rg.uniform(8.5, 12.5)
    R = rg.uniform(0.34, 0.44) * H
    az = rg.uniform(0, 2 * math.pi)
    y_f = rg.uniform(0.28, 0.4) * H
    tr = _trunk_line(y_f, rg.uniform(2, 8), az, 0.06, rg, n=4)
    T.tube(tr, np.linspace(0.26, 0.17, len(tr)), [BARK_OAK] * len(tr), sides=6)
    crown_c = np.array([tr[-1][0], 0.64 * H, tr[-1][2]])
    n_st = rg.integers(2, 4)
    n_lobe = rg.integers(5, 8)
    a0 = rg.uniform(0, 2 * math.pi)
    lobes = []
    for q in range(n_lobe):
        a = a0 + 2 * math.pi * q / n_lobe + rg.uniform(-0.3, 0.3)
        if q == n_lobe - 1:
            lc = crown_c + [rg.uniform(-0.5, 0.5), 0.26 * H, rg.uniform(-0.5, 0.5)]
        else:
            el = rg.uniform(-0.25, 0.55)
            lc = crown_c + np.array([math.cos(a) * math.cos(el) * R * 0.62, math.sin(el) * 0.3 * H, math.sin(a) * math.cos(el) * R * 0.62])
        lobes.append((lc, rg.uniform(1.4, 2.0)))
    for s in range(n_st):                                          # stems from the fork towards lobes
        tgt = lobes[s * len(lobes) // n_st][0]
        b0 = tr[-1]
        mid = b0 + (tgt - b0) * 0.5 + [0, 0.8, 0]
        T.tube([b0, mid, tgt - (tgt - b0) * 0.15], [0.15, 0.10, 0.06], [BARK_OAK] * 3, sides=5)
    for k, (lc, lr) in enumerate(lobes):
        n_cl = rg.integers(3, 5)
        for i in range(n_cl):
            d = rg.normal(0, 1, 3); d /= np.linalg.norm(d)
            cc = lc + d * lr * (0 if i == 0 else rg.uniform(0.5, 0.9)) * [1, 0.7, 1]
            q = (cc - crown_c) / [R, 0.32 * H, R]
            depth = np.linalg.norm(q)
            down = max(0.0, -(cc - lc)[1] / lr)
            ao = np.clip((0.5 + 0.5 * min(depth, 1.0)) * (1 - 0.25 * down), 0.3, 1.0)
            _clump_cards(T, cc, lr * rg.uniform(0.75, 0.95), rg.integers(3, 6), ["oakA", "oakB"], rg, crown_c, OAK_TINT, ao,
                         flat=0.25, upw=0.25, crown_w=0.4)
    return T, dict(H=round(H, 2), R=round(R, 2), kind="oak")


# ---------------------------------------------------------------- glTF -----------------------------------------------------
def _lin8(c):
    return np.clip(np.round(np.asarray(c) * 255), 0, 255).astype(np.uint8)


def write_glb(path, T, atlas_png, name):
    open(path, "wb").write(glb_bytes([(name, T, None)], atlas_png))


def glb_bytes(items, atlas_png, root_matrix=None):
    """items: [(name, Tree, inst)], inst None = one node at the origin, else (T (n,3), R quat (n,4), S (n,3)) for
    EXT_mesh_gpu_instancing (the 3D-tile form). root_matrix: 4x4 of the parent node (tile local -> ECEF)."""
    blob = bytearray(); views, accs = [], []

    def view(bb, target=None):
        blob.extend(b"\0" * ((-len(blob)) % 4))
        v = dict(buffer=0, byteOffset=len(blob), byteLength=len(bb))
        if target:
            v["target"] = target
        blob.extend(bb); views.append(v)
        return len(views) - 1

    def acc(arr, typ, ct=5126, target=34962, norm=False, mm=False):
        a = dict(bufferView=view(arr.tobytes(), target), componentType=ct, count=len(arr), type=typ)
        if norm:
            a["normalized"] = True
        if mm:
            a["min"], a["max"] = arr.min(0).tolist(), arr.max(0).tolist()
        accs.append(a)
        return len(accs) - 1
    meshes, nodes = [], [dict(children=[])]
    if root_matrix is not None:
        nodes[0]["matrix"] = [float(v) for v in np.asarray(root_matrix).T.reshape(-1)]
    inst_used = False
    for name, T, inst in items:
        prims = []
        if T.fol["P"]:
            P = np.array(T.fol["P"], np.float32); Nn = np.array(T.fol["N"], np.float32)
            UV = np.array(T.fol["UV"], np.float32); C = np.concatenate((_lin8(T.fol["C"]), np.full((len(P), 1), 255, np.uint8)), 1)
            prims.append(dict(attributes=dict(POSITION=acc(P, "VEC3", mm=True), NORMAL=acc(Nn, "VEC3"), TEXCOORD_0=acc(UV, "VEC2"),
                                              COLOR_0=acc(C, "VEC4", ct=5121, norm=True)),
                              indices=acc(np.arange(len(P), dtype=np.uint32), "SCALAR", ct=5125, target=34963), material=0, mode=4))
        if T.bark["P"]:
            P = np.concatenate(T.bark["P"]).astype(np.float32); Nn = np.concatenate(T.bark["N"]).astype(np.float32)
            C = np.concatenate((_lin8(np.concatenate(T.bark["C"])), np.full((len(P), 1), 255, np.uint8)), 1)
            I = np.concatenate(T.bark["I"]).astype(np.uint32).reshape(-1)
            prims.append(dict(attributes=dict(POSITION=acc(P, "VEC3", mm=True), NORMAL=acc(Nn, "VEC3"), COLOR_0=acc(C, "VEC4", ct=5121, norm=True)),
                              indices=acc(I, "SCALAR", ct=5125, target=34963), material=1, mode=4))
        meshes.append(dict(name=name, primitives=prims))
        nd = dict(mesh=len(meshes) - 1, name=name)
        if inst is not None:
            Ti, Ri, Si = inst
            nd["extensions"] = dict(EXT_mesh_gpu_instancing=dict(attributes=dict(
                TRANSLATION=acc(np.asarray(Ti, np.float32), "VEC3", target=None), ROTATION=acc(np.asarray(Ri, np.float32), "VEC4", target=None),
                SCALE=acc(np.asarray(Si, np.float32), "VEC3", target=None))))
            inst_used = True
        nodes[0]["children"].append(len(nodes)); nodes.append(nd)
    img_view = view(atlas_png)
    blob.extend(b"\0" * ((-len(blob)) % 4))
    gl = dict(asset=dict(version="2.0", generator="gyro-sim-chair veg_cards.py"), scene=0, scenes=[dict(nodes=[0])],
              nodes=nodes, meshes=meshes,
              materials=[dict(name="foliage_cards", alphaMode="MASK", alphaCutoff=0.5, doubleSided=False,
                              pbrMetallicRoughness=dict(baseColorTexture=dict(index=0), baseColorFactor=[1, 1, 1, 1], metallicFactor=0.0, roughnessFactor=0.85)),
                         dict(name="bark", pbrMetallicRoughness=dict(baseColorFactor=[1, 1, 1, 1], metallicFactor=0.0, roughnessFactor=0.95))],
              textures=[dict(source=0, sampler=0)], images=[dict(bufferView=img_view, mimeType="image/png")],
              samplers=[dict(magFilter=9729, minFilter=9987, wrapS=33071, wrapT=33071)],
              accessors=accs, bufferViews=views, buffers=[dict(byteLength=len(blob))])
    if inst_used:
        gl["extensionsUsed"] = gl["extensionsRequired"] = ["EXT_mesh_gpu_instancing"]
    js = json.dumps(gl, separators=(",", ":")).encode(); js += b" " * ((-len(js)) % 4)
    total = 12 + 8 + len(js) + 8 + len(blob)
    return (struct.pack("<III", 0x46546C67, 2, total) + struct.pack("<II", len(js), 0x4E4F534A) + js
            + struct.pack("<II", len(blob), 0x004E4942) + bytes(blob))


def baseline_tree(pid, H, R):
    """current game proxy (veg_shape prototype) as a vertex-coloured Tree, colour = tint x AO (M_GyroTree2 approx)."""
    import veg_shape_preview as SP
    P, Nn, col, kind, ao, I, ntri = SP.proto_arrays(pid, False, True)
    T = Tree()
    P = P * [R, H, R]
    q = Nn / [R, H, R]; Nn = q / np.linalg.norm(q, axis=1, keepdims=True)
    c = col * (0.3 + 0.7 * ao)[:, None]
    T.bark["P"].append(P); T.bark["N"].append(Nn); T.bark["C"].append(np.clip(c, 0, 1)); T.bark["I"].append(I)
    T.nb = len(P)
    return T, ntri


def main(out, baseline=False):
    os.makedirs(out, exist_ok=True)
    img = make_atlas()
    img.save(os.path.join(out, "atlas.png"))
    bb = io.BytesIO(); img.save(bb, "PNG"); png = bb.getvalue()
    meta = dict(made=time.strftime("%Y-%m-%dT%H:%M:%S"), script="sim/veg_cards.py", atlas=[ATLAS, ATLAS], trees=[])
    for sp, fn, n in (("pine", pine, 10), ("oak", oak, 5)):
        for v in range(n):
            T, info = fn(v)
            name = "%s_%02d" % (sp, v)
            write_glb(os.path.join(out, name + ".glb"), T, png, name)
            meta["trees"].append(dict(name=name, species=sp, tris=T.ntri, cards=T.ncards,
                                      card_tris=len(T.fol["P"]) // 3, bark_tris=T.ntri - len(T.fol["P"]) // 3, **info))
    if baseline:
        import veg_v2 as V2
        for nm, pid, H, R in (("baseline_pine", 0, 12.0, 4.0), ("baseline_oak", 4, 11.0, 4.4)):
            T, ntri = baseline_tree(pid, H, R)
            write_glb(os.path.join(out, nm + ".glb"), T, png, nm)
            meta.setdefault("baseline", []).append(dict(name=nm, proto=list(V2.PROTOS[pid]), tris=ntri, H=H, R=R))
    json.dump(meta, open(os.path.join(out, "cards.json"), "w"), indent=1)
    for t in meta["trees"]:
        print(t["name"], t["tris"], "tris", t["cards"], "cards", t["kind"], "H", t["H"])
    for t in meta.get("baseline", []):
        print(t["name"], t["tris"])
    return meta


if __name__ == "__main__":
    main(sys.argv[1], "--baseline" in sys.argv)
