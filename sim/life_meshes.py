"""Low-poly vehicle / ship / wake meshes of the Busan 'life' layer, drawn here in code (original, no third-party asset).
Writes glb files that Scripts/life_assets.py imports as /Game/Life/SM_Life*.

    python -I sim/life_meshes.py          -> C:\\GyroSimTiles\\life\\meshes\\*.glb (+ meshes.json: sizes, vertex counts)

Frame while drawing: Unreal's (X forward = bow, Y right = starboard, Z up), metres, pivot = midship on the waterline
(vehicles: centre of the footprint on the road). to_gltf() turns it into glTF (right-handed, Y up); the importer turns
it back (checked on import: life_assets.py logs each mesh's bounds against meshes.json).
Real sizes: container ship 300 x 48 m (a 13-14k TEU class), feeder 170 x 27, Busan-Japan ferry 165 x 26 (New Camellia
170 m, 성희 162 m class), bulk carrier 225 x 32, tug 30 x 10, fishing boat 24 x 6, small boat 13 x 3.8.
Vertex data: COLOR_0 = base colour (linear), TEXCOORD_0.x = paint flag (0 fixed colour, 1 hull paint, 2 trim paint:
the material swaps in a per-ship colour), wake: COLOR_0 = (along 0..1, across 0..1, part, 1).
Vehicles = ONE mesh of three unit boxes (body / cabin / shadow plate, TEXCOORD_0.x = part * 10 + paint): the material
sizes them per vehicle kind (sedan, SUV, 1-ton truck, bus, cargo truck) - 52 vertices for every kind.
"""
import json, math, os, struct, sys, site
if sys.flags.isolated:
    site.addsitedir(site.getusersitepackages())
import numpy as np  # noqa: E402

OUT = os.path.join(os.environ.get("GYROSIM_LIFE", r"C:\GyroSimTiles\life"), "meshes")


class Mesh:
    def __init__(self):
        self.P, self.N, self.C, self.U, self.I = [], [], [], [], []

    def quad(self, a, b, c, d, col, u=0.0, normal=None):
        """quad a b c d (any winding; faces `normal` if given, else its own normal)."""
        a, b, c, d = (np.asarray(p, float) for p in (a, b, c, d))
        n = np.cross(b - a, d - a) + np.cross(d - c, b - c)
        if np.linalg.norm(n) < 1e-12:
            return
        n /= np.linalg.norm(n)
        if normal is not None and np.dot(n, normal) < 0:
            a, b, c, d = a, d, c, b
            n = -n
        k = len(self.P)
        self.P += [a, b, c, d]
        self.N += [n] * 4
        self.C += [col] * 4
        self.U += [u] * 4
        self.I += [(k, k + 1, k + 2), (k, k + 2, k + 3)]

    def tri(self, a, b, c, col, u=0.0, normal=None):
        a, b, c = (np.asarray(p, float) for p in (a, b, c))
        n = np.cross(b - a, c - a)
        if np.linalg.norm(n) < 1e-12:
            return
        n /= np.linalg.norm(n)
        if normal is not None and np.dot(n, normal) < 0:
            b, c = c, b
            n = -n
        k = len(self.P)
        self.P += [a, b, c]
        self.N += [n] * 3
        self.C += [col] * 3
        self.U += [u] * 3
        self.I += [(k, k + 1, k + 2)]

    def box(self, x0, x1, y0, y1, z0, z1, col, u=0.0, bottom=False, top_col=None, top_u=None):
        X, Y, Z = (x0, x1), (y0, y1), (z0, z1)
        p = lambda i, j, k: (X[i], Y[j], Z[k])
        self.quad(p(0, 0, 1), p(1, 0, 1), p(1, 1, 1), p(0, 1, 1), top_col or col, u if top_u is None else top_u, normal=(0, 0, 1))
        self.quad(p(1, 0, 0), p(1, 1, 0), p(1, 1, 1), p(1, 0, 1), col, u, normal=(1, 0, 0))
        self.quad(p(0, 0, 0), p(0, 1, 0), p(0, 1, 1), p(0, 0, 1), col, u, normal=(-1, 0, 0))
        self.quad(p(0, 1, 0), p(1, 1, 0), p(1, 1, 1), p(0, 1, 1), col, u, normal=(0, 1, 0))
        self.quad(p(0, 0, 0), p(1, 0, 0), p(1, 0, 1), p(0, 0, 1), col, u, normal=(0, -1, 0))
        if bottom:
            self.quad(p(0, 0, 0), p(1, 0, 0), p(1, 1, 0), p(0, 1, 0), col, u, normal=(0, 0, -1))

    def hull(self, L, B, zbot, zmid, ztop, bow, col_lo, col_hi, deck, u_lo=0.0, u_hi=1.0, stern_r=0.12, bow_pow=1.6, n_bow=8):
        """ship hull: plan outline (flat stern with rounded corners, parallel body, pointed bow over `bow` m), sides in two
        bands (zbot..zmid boot-top / antifouling, zmid..ztop topsides), flat deck."""
        hb = B / 2.0
        xs = L / 2.0
        r = stern_r * hb
        pts = [(-xs, -hb + r), (-xs + r * 0.3, -hb + r * 0.3), (-xs + r, -hb)]
        x_b = xs - bow
        pts.append((x_b, -hb))
        for t in np.linspace(0, 1, n_bow + 1)[1:]:
            x = x_b + bow * t
            y = -hb * (1 - t ** bow_pow) ** 0.8
            pts.append((x, y))
        pts[-1] = (xs, 0.0)
        right = [(x, -y) for x, y in reversed(pts[:-1])]
        ring = pts + right                                          # port stern -> bow -> starboard stern (closed implicitly)
        ring = [np.array(p) for p in ring]
        c = np.mean(ring, axis=0)
        for i in range(len(ring)):
            a, b = ring[i], ring[(i + 1) % len(ring)]
            mid = (a + b) / 2 - c
            nrm = np.array((mid[0], mid[1], 0.0))
            for z0, z1, col, u in ((zbot, zmid, col_lo, u_lo), (zmid, ztop, col_hi, u_hi)):
                self.quad((a[0], a[1], z0), (b[0], b[1], z0), (b[0], b[1], z1), (a[0], a[1], z1), col, u, normal=nrm)
            self.tri((c[0], c[1], ztop), (a[0], a[1], ztop), (b[0], b[1], ztop), deck, 0.0, normal=(0, 0, 1))
        return ring

    def arrays(self):
        return (np.array(self.P, np.float32), np.array(self.N, np.float32), np.array(self.C, np.float32),
                np.array(self.U, np.float32), np.array(self.I, np.uint32).reshape(-1))


def to_gltf(v):
    """Unreal (X fwd, Y right, Z up) metres -> glTF (right-handed, Y up): (x, z, y) - the importer's inverse."""
    v = np.asarray(v)
    return np.stack((v[:, 0], v[:, 2], v[:, 1]), 1)


def glb(mesh, path):
    P, N, C, U, I = mesh.arrays()
    Pg, Ng = to_gltf(P).astype(np.float32), to_gltf(N).astype(np.float32)
    # the axis swap mirrors the mesh: flip every triangle so it stays front-facing
    I = I.reshape(-1, 3)[:, [0, 2, 1]].reshape(-1).astype(np.uint32)
    Cb = np.clip(np.round(np.concatenate((C[:, :3], np.ones((len(C), 1))), 1) * 255), 0, 255).astype(np.uint8)
    UV = np.stack((U, np.zeros_like(U)), 1).astype(np.float32)
    blobs, views, accs = [], [], []
    off = 0

    def add(arr, target, comp, typ, count, mn=None, mx=None, norm=False):
        nonlocal off
        b = arr.tobytes()
        pad = (-len(b)) % 4
        blobs.append(b + b"\0" * pad)
        views.append(dict(buffer=0, byteOffset=off, byteLength=len(b), **({"target": target} if target else {})))
        a = dict(bufferView=len(views) - 1, componentType=comp, count=count, type=typ)
        if mn is not None:
            a["min"], a["max"] = mn, mx
        if norm:
            a["normalized"] = True
        accs.append(a)
        off += len(b) + pad
        return len(accs) - 1
    ip = add(Pg, 34962, 5126, "VEC3", len(Pg), Pg.min(0).tolist(), Pg.max(0).tolist())
    inn = add(Ng, 34962, 5126, "VEC3", len(Ng))
    ic = add(Cb, 34962, 5121, "VEC4", len(Cb), norm=True)
    iu = add(UV, 34962, 5126, "VEC2", len(UV))
    ii = add(I, 34963, 5125, "SCALAR", len(I))
    name = os.path.splitext(os.path.basename(path))[0]
    js = dict(asset=dict(version="2.0", generator="gyro-sim-chair sim/life_meshes.py"), scene=0, scenes=[dict(nodes=[0])],
              nodes=[dict(mesh=0, name=name)],
              meshes=[dict(name=name, primitives=[dict(attributes=dict(POSITION=ip, NORMAL=inn, COLOR_0=ic, TEXCOORD_0=iu), indices=ii, material=0)])],
              materials=[dict(name="M_" + name, pbrMetallicRoughness=dict(baseColorFactor=[1, 1, 1, 1], metallicFactor=0.0, roughnessFactor=0.6))],
              accessors=accs, bufferViews=views, buffers=[dict(byteLength=off)])
    j = json.dumps(js, separators=(",", ":")).encode()
    j += b" " * ((-len(j)) % 4)
    bin_ = b"".join(blobs)
    with open(path, "wb") as f:
        f.write(struct.pack("<III", 0x46546C67, 2, 12 + 8 + len(j) + 8 + len(bin_)))
        f.write(struct.pack("<II", len(j), 0x4E4F534A) + j)
        f.write(struct.pack("<II", len(bin_), 0x004E4942) + bin_)
    return dict(verts=int(len(P)), tris=int(len(I) // 3), min=P.min(0).round(2).tolist(), max=P.max(0).round(2).tolist())


def srgb(r, g, b):
    f = lambda c: (c / 255.0) ** 2.2
    return (f(r), f(g), f(b))


WHITE, GREYW = srgb(232, 234, 236), srgb(200, 202, 205)
DARK, GLASS = srgb(40, 42, 46), srgb(25, 32, 40)
DECK_RED, DECK_GREEN, DECK_GREY = srgb(120, 55, 45), srgb(70, 95, 80), srgb(120, 120, 118)
ANTIFOUL, BOOT = srgb(140, 40, 32), srgb(35, 35, 38)
CONT = [srgb(*c) for c in ((60, 130, 190), (200, 60, 45), (230, 170, 40), (40, 110, 70), (210, 210, 210), (120, 120, 125),
                           (170, 70, 40), (90, 60, 140), (210, 90, 150), (30, 60, 120), (225, 120, 40), (150, 40, 40))]


def vehicle():
    """three unit boxes centred at the origin (-0.5..0.5): part 0 body, 1 cabin, 2 shadow plate; U = part * 10 + paint."""
    m = Mesh()
    # body: paint sides + top
    m.box(-0.5, 0.5, -0.5, 0.5, -0.5, 0.5, WHITE, 1.0)
    # cabin: glass sides, paint roof
    m.box(-0.5, 0.5, -0.5, 0.5, -0.5, 0.5, GLASS, 10.0, top_col=WHITE, top_u=11.0)
    # shadow plate (top face only)
    m.quad((-0.5, -0.5, 0.0), (0.5, -0.5, 0.0), (0.5, 0.5, 0.0), (-0.5, 0.5, 0.0), DARK, 20.0, normal=(0, 0, 1))
    return m


def containers(m, rng, x0, x1, B, z0, tiers=(4, 8), bay=13.0, blocks=4, gap=0.6):
    x = x0
    while x + bay <= x1 + 0.01:
        hb = B / 2.0
        w = B / blocks
        for k in range(blocks):
            t = int(rng.integers(tiers[0], tiers[1] + 1))
            col = CONT[int(rng.integers(0, len(CONT)))]
            m.box(x + gap / 2, x + bay - gap / 2, -hb + k * w + 0.15, -hb + (k + 1) * w - 0.15, z0, z0 + t * 2.6, col)
        x += bay


def container_ship(L=300.0, B=48.0, seed=1):
    m = Mesh()
    rng = np.random.default_rng(seed)
    fb = 0.04 * L                                              # freeboard 12 m (300 m)
    m.hull(L, B, -1.0, 0.012 * L, fb, 0.17 * L, BOOT, DARK, DECK_RED, 0.0, 1.0)
    xs = L / 2
    # superstructure (accommodation + bridge) at ~ 1/3 from the stern on big ships, aft on feeders
    hx = -xs + (0.33 * L if L > 250 else 0.12 * L)
    hl, hh = 0.045 * L, 0.11 * L
    m.box(hx - hl / 2, hx + hl / 2, -0.30 * B, 0.30 * B, fb, fb + hh, WHITE)
    m.box(hx + hl / 2 - 0.012 * L, hx + hl / 2, -0.5 * B, 0.5 * B, fb + hh - 0.012 * L, fb + hh - 0.004 * L, WHITE)   # bridge wings
    m.box(hx + hl / 2 - 0.006 * L, hx + hl / 2 + 0.0005 * L, -0.28 * B, 0.28 * B, fb + hh - 0.012 * L, fb + hh - 0.006 * L, GLASS)
    fx = -xs + 0.06 * L                                         # funnel / engine casing aft
    m.box(fx - 0.02 * L, fx + 0.02 * L, -0.12 * B, 0.12 * B, fb, fb + 0.07 * L, DARK, 2.0)
    containers(m, rng, hx + hl / 2 + 1.0, xs - 0.16 * L, B - 2.0, fb, bay=13.0 if L > 250 else 12.5)
    containers(m, rng, fx + 0.03 * L, hx - hl / 2 - 1.0, B - 2.0, fb, tiers=(3, 6))
    m.box(xs - 0.16 * L, xs - 0.14 * L, -0.4 * B, 0.4 * B, fb, fb + 3.0, WHITE)   # breakwater
    return m


def ferry(L=165.0, B=26.0):
    m = Mesh()
    fb = 9.0
    m.hull(L, B, -1.0, 2.5, fb, 0.22 * L, BOOT, WHITE, DECK_GREEN, 0.0, 0.0)
    xs = L / 2
    m.box(-xs + 4, xs - 0.22 * L, -B / 2 - 0.05, B / 2 + 0.05, 4.0, 5.6, WHITE, 2.0)              # trim stripe (paint)
    decks = [(-xs + 10, xs - 0.20 * L - 4, 0.48 * B), (-xs + 14, xs - 0.24 * L - 4, 0.46 * B),
             (-xs + 20, xs - 0.27 * L - 4, 0.44 * B), (-xs + 30, xs - 0.30 * L - 4, 0.40 * B), (-xs + 45, xs - 0.32 * L - 4, 0.34 * B)]
    z = fb
    for i, (a, b, hw) in enumerate(decks):
        m.box(a, b, -hw, hw, z, z + 2.8, WHITE)
        m.box(a + 2, b - 1, -hw - 0.06, hw + 0.06, z + 1.0, z + 2.1, GLASS)                      # window band
        z += 2.8
    m.box(xs - 0.32 * L - 6, xs - 0.32 * L - 4, -0.36 * B, 0.36 * B, z - 2.2, z - 0.6, GLASS)  # bridge windows
    m.box(-xs + 22, -xs + 34, -3.0, 3.0, z, z + 8.0, WHITE, 2.0)                                  # funnel
    m.box(-xs + 22, -xs + 34, -3.05, 3.05, z + 6.0, z + 8.0, DARK)
    return m


def bulk(L=225.0, B=32.0):
    m = Mesh()
    fb = 13.0                                                  # in ballast at anchor: high freeboard, red bottom shows
    m.hull(L, B, -1.0, 6.0, fb, 0.12 * L, ANTIFOUL, DARK, DECK_RED, 0.0, 1.0, bow_pow=1.3)
    xs = L / 2
    for k in range(7):                                         # hatch covers
        x = -xs + 0.17 * L + k * 0.105 * L
        m.box(x, x + 0.08 * L, -0.38 * B, 0.38 * B, fb, fb + 2.2, DECK_GREY, 2.0)
    for k in range(4):                                         # deck cranes
        x = -xs + 0.22 * L + k * 0.21 * L
        m.box(x - 1.5, x + 1.5, -1.5, 1.5, fb, fb + 22.0, srgb(200, 170, 50))
        m.box(x - 1.0, x + 22.0, -0.7, 0.7, fb + 20.0, fb + 21.4, srgb(200, 170, 50))
    m.box(-xs + 6, -xs + 0.12 * L, -0.42 * B, 0.42 * B, fb, fb + 15.0, WHITE)
    m.box(-xs + 0.12 * L - 3, -xs + 0.12 * L - 0.5, -0.5 * B, 0.5 * B, fb + 13.0, fb + 15.0, WHITE)
    m.box(-xs + 0.12 * L - 0.6, -xs + 0.12 * L - 0.4, -0.40 * B, 0.40 * B, fb + 12.8, fb + 14.6, GLASS)
    m.box(-xs + 8, -xs + 16, -3.5, 3.5, fb + 15.0, fb + 23.0, DARK, 2.0)
    return m


def tug(L=30.0, B=10.0):
    m = Mesh()
    fb = 2.6
    m.hull(L, B, -0.6, 0.6, fb, 0.35 * L, BOOT, DARK, DECK_GREY, 0.0, 1.0, bow_pow=2.2, stern_r=0.45)
    m.box(-2.0, 6.0, -3.6, 3.6, fb, fb + 2.8, WHITE)
    m.box(-0.5, 5.0, -3.0, 3.0, fb + 2.8, fb + 5.4, WHITE)
    m.box(4.9, 5.1, -2.8, 2.8, fb + 3.6, fb + 5.0, GLASS)
    m.box(-5.0, -3.0, -1.6, 1.6, fb, fb + 6.0, DARK, 2.0)
    m.box(-L / 2 + 0.5, L / 2 - 2.0, -B / 2 - 0.4, B / 2 + 0.4, fb - 0.6, fb - 0.1, DARK)        # fender
    return m


def fishing(L=24.0, B=6.0):
    m = Mesh()
    fb = 2.0
    m.hull(L, B, -0.5, 0.4, fb, 0.32 * L, ANTIFOUL, WHITE, DECK_GREY, 0.0, 1.0, bow_pow=2.0, stern_r=0.3)
    m.box(1.0, 6.0, -2.0, 2.0, fb, fb + 2.6, WHITE)
    m.box(5.9, 6.05, -1.8, 1.8, fb + 1.4, fb + 2.4, GLASS)
    m.box(3.2, 3.5, -0.15, 0.15, fb + 2.6, fb + 8.0, DARK)                      # mast
    m.box(-L / 2 + 1.0, -3.0, -2.2, 2.2, fb, fb + 0.9, srgb(60, 110, 160), 2.0)  # gear / nets
    m.box(-6.0, -5.7, -0.12, 0.12, fb, fb + 5.0, DARK)
    return m


def boat(L=13.0, B=3.8):
    m = Mesh()
    fb = 1.2
    m.hull(L, B, -0.3, 0.25, fb, 0.40 * L, BOOT, WHITE, srgb(190, 170, 140), 0.0, 1.0, bow_pow=2.0, stern_r=0.2)
    m.box(-2.5, 2.0, -1.4, 1.4, fb, fb + 1.6, WHITE)
    m.box(1.0, 2.05, -1.3, 1.3, fb + 0.5, fb + 1.5, GLASS)
    m.box(-2.6, -2.4, -1.45, 1.45, fb + 0.4, fb + 1.4, GLASS)
    return m


def wake():
    """foam for a 100 m ship (instance scale = length / 100): stern trail, two Kelvin arms (19.5 deg), bow waves.
    COLOR_0 = (along 0..1, across 0..1, part 0 trail / 0.5 arm / 1 bow)."""
    m = Mesh()
    up = (0, 0, 1)
    n = 16
    us = np.linspace(0, 1, n + 1)
    # stern trail
    for a, b in zip(us, us[1:]):
        xa, xb = -50 - 400 * a, -50 - 400 * b
        wa, wb = 6 + 30 * a ** 0.7, 6 + 30 * b ** 0.7
        for s0, s1 in ((-1, 0), (0, 1)):
            m.quad((xa, s0 * wa, 0), (xb, s0 * wb, 0), (xb, s1 * wb, 0), (xa, s1 * wa, 0), (a, (s0 + 1) / 2, 0.0), 0.0, normal=up)
            # colour per vertex is set below (quad uses one colour) - fixed after
    # Kelvin arms
    t = math.tan(math.radians(19.5))
    for side in (-1, 1):
        for a, b in zip(us, us[1:]):
            xa, xb = 45 - 495 * a, 45 - 495 * b
            ya, yb = side * (8 + (45 - xa) * t), side * (8 + (45 - xb) * t)
            wa, wb = 2 + 10 * a, 2 + 10 * b
            m.quad((xa, ya - wa, 0), (xb, yb - wb, 0), (xb, yb + wb, 0), (xa, ya + wa, 0), (a, 0.5, 0.5), 0.0, normal=up)
    # bow waves along the hull sides
    for side in (-1, 1):
        xs = np.linspace(50, -15, 9)
        for xa, xb in zip(xs, xs[1:]):
            hw = lambda x: 7.5 * min(1.0, max(0.0, (50 - x) / 17.0)) ** 0.6
            m.quad((xa, side * (hw(xa) + 0.3), 0), (xb, side * (hw(xb) + 0.3), 0), (xb, side * (hw(xb) + 4.5), 0),
                   (xa, side * (hw(xa) + 2.5), 0), ((50 - xa) / 65, 0.5, 1.0), 0.0, normal=up)
    # per-vertex along / across from the position (the quads above carry only a part id)
    P = np.array(m.P)
    C = np.array(m.C, float)
    part = C[:, 2]
    along = np.where(part < 0.25, (-50 - P[:, 0]) / 400, np.where(part < 0.75, (45 - P[:, 0]) / 495, (50 - P[:, 0]) / 65))
    across = np.where(part < 0.25, P[:, 1] / np.maximum(6 + 30 * np.clip(along, 0, 1) ** 0.7, 1e-3) * 0.5 + 0.5, 0.5)
    arm_c = np.sign(P[:, 1]) * (8 + (45 - P[:, 0]) * t)
    arm_w = 2 + 10 * np.clip(along, 0, 1)
    across = np.where((part >= 0.25) & (part < 0.75), (P[:, 1] - arm_c) / arm_w * 0.5 + 0.5, across)
    across = np.where(part >= 0.75, np.clip((np.abs(P[:, 1]) - 7.5 * np.clip((50 - P[:, 0]) / 17, 0, 1) ** 0.6) / 4.5, 0, 1), across)
    m.C = [tuple(x) for x in np.stack((np.clip(along, 0, 1), np.clip(across, 0, 1), part), 1)]
    return m


MODELS = dict(SM_LifeVehicle=vehicle, SM_LifeContainer=lambda: container_ship(300.0, 48.0, 1), SM_LifeFeeder=lambda: container_ship(170.0, 27.0, 2),
              SM_LifeFerry=ferry, SM_LifeBulk=bulk, SM_LifeTug=tug, SM_LifeFishing=fishing, SM_LifeBoat=boat, SM_LifeWake=wake)


def main():
    os.makedirs(OUT, exist_ok=True)
    info = {}
    for name, fn in MODELS.items():
        info[name] = glb(fn(), os.path.join(OUT, name + ".glb"))
        print("%-18s %5d verts %5d tris  min %s max %s" % (name, info[name]["verts"], info[name]["tris"], info[name]["min"], info[name]["max"]))
    import time
    with open(os.path.join(OUT, "meshes.json"), "w", encoding="utf-8") as f:
        json.dump(dict(made=time.strftime("%Y-%m-%d %H:%M:%S"), frame="UE X fwd Y right Z up, m", meshes=info), f, indent=1)


if __name__ == "__main__":
    main()
