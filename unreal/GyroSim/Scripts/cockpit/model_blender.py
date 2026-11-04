"""GyroSim cockpit - procedural model, run inside Blender 4.5 (background):
    blender -b --factory-startup -P model_blender.py -- [--no-preview]
(build_cockpit.py runs make_textures.py first, then this.)

Builds our own fighter-trainer cockpit (geometry 100 % generated here, see layout.py for every dimension) and writes
unreal/GyroSim/Art/Cockpit/:
  ck_shell.fbx      static opaque interior (tub, consoles, panels, switches, seat, HUD frame, canopy frame ...)
  ck_glass.fbx      static translucent (instrument glass, HUD combiner)
  ck_<part>.fbx     moving parts, mesh origin = pivot: stick, throttle, pedal_l, pedal_r, gearhandle, gearlights,
                    needle_asi, needle_alt, needle_alt10k, needle_vsi, adi_ball
  manifest.json     pivots / instrument frames / MFD screen rectangles (UE body cm) for build_level.py
  preview/*.png     Eevee renders from the eye (layout check)

Construction space = Unreal body coordinates (cm, X fwd, Y right, Z up) treated as an ordinary right-handed space.
At the end every vertex is mapped to Blender (x, -y, z) / 100 and every face reversed (mirror), which the FBX export
(axis forward X, up Z) + Unreal import turn back into exactly these coordinates (checked with a marker test).
"""
import bpy, bmesh, json, math, os, sys
from mathutils import Vector, Matrix

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.normpath(os.path.join(HERE, "..", "..", "Content", "Python")))
import layout as L            # noqa: E402
import cockpit_gauges as G    # noqa: E402

ART = os.path.normpath(os.path.join(HERE, "..", "..", "Art", "Cockpit"))
TEX = os.path.join(ART, "tex")
ATL = json.load(open(os.path.join(TEX, "atlas.json")))
ARGS = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
V = Vector
D2R = math.radians


# =====================================================================================================================
# mesh accumulation
class Part:
    def __init__(self, name):
        self.name, self.V, self.F, self.UV0, self.UV1, self.M, self.slots = name, [], [], [], [], [], []

    def slot(self, mat):
        if mat not in self.slots:
            self.slots.append(mat)
        return self.slots.index(mat)

    def add(self, bm, mat, uv0=None, swatch="sw_black", frame=None, flip=False, recalc=None):
        """append a temporary bmesh (local coords if frame=(o, X, Y, Z) given, else construction space).
        recalc: closed mesh -> outward normals recomputed after the transform (default: auto for closed meshes)."""
        if frame is not None:
            o, X, Y, Z = frame
            M = Matrix(((X[0], Y[0], Z[0]), (X[1], Y[1], Z[1]), (X[2], Y[2], Z[2])))
            if M.determinant() < 0:
                flip = not flip
            for v in bm.verts:
                v.co = V(o) + M @ v.co
        if recalc is None:
            recalc = len(bm.edges) > 0 and all(e.is_manifold for e in bm.edges)
        if recalc:
            bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
            flip = False
        bm.normal_update()
        base = len(self.V)
        idx = {}
        for i, v in enumerate(bm.verts):
            idx[v] = base + i
            self.V.append(tuple(v.co))
        si = self.slot(mat)
        sw = swatch_uv(swatch)
        for f in bm.faces:
            loops = list(f.loops)
            n = -f.normal if flip else f.normal
            if flip:
                loops = loops[::-1]
            self.F.append([idx[l.vert] for l in loops])
            self.M.append(si)
            for l in loops:
                p = l.vert.co
                u = uv0(p, n) if uv0 else None
                self.UV0.append(u if u is not None else sw)
                self.UV1.append(boxuv(p, n))
        bm.free()


PARTS = {}


def part(name):
    if name not in PARTS:
        PARTS[name] = Part(name)
    return PARTS[name]


def boxuv(p, n, s=40.0):
    ax = max(range(3), key=lambda i: abs(n[i]))
    if ax == 0:
        return (p[1] / s, p[2] / s)
    if ax == 1:
        return (p[0] / s, p[2] / s)
    return (p[0] / s, p[1] / s)


def region_uv(name, us, vs):
    r = ATL["regions"][name]
    x0, y0, w, h = r["px"]
    ix = x0 + (us - r["u0"]) / (r["u1"] - r["u0"]) * w
    iy = y0 + (r["v1"] - vs) / (r["v1"] - r["v0"]) * h
    return (ix / ATL["size"], 1.0 - iy / ATL["size"])


def swatch_uv(name):
    return region_uv(name, 0.5, 0.5)


def dial_uv(dial, du, dv, rad):
    """polar dial mapping: (du, dv) cm from the centre, rad = cm at the dial edge -> dial atlas UV (Blender v up)."""
    u0, v0, u1, v1 = L.dial_tile(dial)
    k = 0.485 / rad
    x = (u0 + u1) / 2 + du * k * (u1 - u0)
    y = (v0 + v1) / 2 - dv * k * (v1 - v0)
    return (x, 1.0 - y)


# =====================================================================================================================
# primitives (temporary bmesh in local coordinates)
def bm_box(sx, sy, sz, bevel=0.0, seg=2, c=(0, 0, 0)):
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1.0)
    for v in bm.verts:
        v.co = V((c[0] + v.co.x * sx, c[1] + v.co.y * sy, c[2] + v.co.z * sz))
    if bevel > 0:
        bmesh.ops.bevel(bm, geom=list(bm.edges), offset=min(bevel, 0.45 * min(sx, sy, sz)), offset_type='OFFSET', segments=seg,
                        profile=0.5, affect='EDGES', clamp_overlap=True)
    return bm


def bm_prism(poly, h, bevel=0.0, seg=2, z0=0.0, top_bevel_only=False):
    """polygon [(x, y)] (CCW) extruded along +z from z0 to z0 + h."""
    bm = bmesh.new()
    vs0 = [bm.verts.new((x, y, z0)) for x, y in poly]
    vs1 = [bm.verts.new((x, y, z0 + h)) for x, y in poly]
    n = len(poly)
    bm.faces.new(vs0[::-1])
    bm.faces.new(vs1)
    for i in range(n):
        j = (i + 1) % n
        bm.faces.new((vs0[i], vs0[j], vs1[j], vs1[i]))
    if bevel > 0:
        if top_bevel_only:
            es = [e for e in bm.edges if all(abs(v.co.z - (z0 + h)) < 1e-6 for v in e.verts)]
        else:
            es = list(bm.edges)
        bmesh.ops.bevel(bm, geom=es, offset=bevel, offset_type='OFFSET', segments=seg, profile=0.5, affect='EDGES', clamp_overlap=True)
    return bm


def bm_lathe(prof, n=40, a0=0.0, a1=360.0):
    """profile [(r, z)] revolved about +z. r == 0 points collapse to the axis."""
    bm = bmesh.new()
    full = abs(a1 - a0) >= 359.99
    steps = n if full else n + 1
    rings = []
    for k in range(steps):
        a = -D2R(a0 + (a1 - a0) * k / n)
        ca, sa = math.cos(a), math.sin(a)
        ring = []
        for r, z in prof:
            ring.append(bm.verts.new((r * ca, r * sa, z)))
        rings.append(ring)
    for k in range(n):
        A, Bn = rings[k], rings[(k + 1) % steps] if full else rings[k + 1]
        for i in range(len(prof) - 1):
            q = [A[i], Bn[i], Bn[i + 1], A[i + 1]]
            uq = []
            for v in q:
                if v not in uq:
                    uq.append(v)
            if len(uq) >= 3 and not (prof[i][0] == 0 and prof[i + 1][0] == 0):
                try:
                    bm.faces.new(uq)
                except ValueError:
                    pass
    bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=1e-5)
    return bm


def bm_cyl(r, h, n=24, bevel=0.0, r2=None, z0=0.0):
    r2 = r if r2 is None else r2
    b = min(bevel, 0.4 * r, 0.4 * h) if bevel else 0
    if b:
        prof = [(0, z0), (r - b, z0), (r - b * 0.3, z0 + b * 0.3), (r, z0 + b), (r2, z0 + h - b), (r2 - b * 0.3, z0 + h - b * 0.3),
                (r2 - b, z0 + h), (0, z0 + h)]
    else:
        prof = [(0, z0), (r, z0), (r2, z0 + h), (0, z0 + h)]
    return bm_lathe(prof, n)


def bm_loft(sections, closed=False, cap0=False, cap1=False):
    """sections: list of point lists (same length). Quads between consecutive sections."""
    bm = bmesh.new()
    rows = [[bm.verts.new(p) for p in s] for s in sections]
    m = len(sections[0])
    for k in range(len(rows) - 1):
        A, Bn = rows[k], rows[k + 1]
        for i in range(m if closed else m - 1):
            j = (i + 1) % m
            bm.faces.new((A[i], A[j], Bn[j], Bn[i]))
    if cap0:
        bm.faces.new(rows[0][::-1])
    if cap1:
        bm.faces.new(rows[-1])
    return bm


def bm_sweep(path, section, side_hint=(1, 0, 0), closed_section=True, caps=True):
    """sweep a 2D section [(a, b)] along a 3D path; a along `side` (normal to the path, closest to side_hint), b along
    the remaining axis."""
    secs = []
    for i, p in enumerate(path):
        p = V(p)
        t = (V(path[min(i + 1, len(path) - 1)]) - V(path[max(i - 1, 0)])).normalized()
        s = V(side_hint) - t * t.dot(V(side_hint))
        s = s.normalized() if s.length > 1e-6 else t.orthogonal().normalized()
        b = t.cross(s).normalized()
        secs.append([tuple(p + s * a + b * c) for a, c in section])
    return bm_loft(secs, closed=closed_section, cap0=caps, cap1=caps)


def rrect(w, h, r, n=3):
    """rounded rectangle (CCW), centred."""
    pts = []
    for cx, cy, a0 in ((w / 2 - r, h / 2 - r, 0), (-w / 2 + r, h / 2 - r, 90), (-w / 2 + r, -h / 2 + r, 180), (w / 2 - r, -h / 2 + r, 270)):
        for k in range(n + 1):
            a = D2R(a0 + 90 * k / n)
            pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))
    return pts


def subsurf(bm, levels=2):
    me = bpy.data.meshes.new("_ss")
    bm.to_mesh(me)
    bm.free()
    ob = bpy.data.objects.new("_ss", me)
    bpy.context.scene.collection.objects.link(ob)
    m = ob.modifiers.new("ss", 'SUBSURF')
    m.levels = levels
    m.render_levels = levels
    dg = bpy.context.evaluated_depsgraph_get()
    eo = ob.evaluated_get(dg)
    me2 = eo.to_mesh()
    out = bmesh.new()
    out.from_mesh(me2)
    eo.to_mesh_clear()
    bpy.data.objects.remove(ob)
    bpy.data.meshes.remove(me)
    return out


# ---- frames -----------------------------------------------------------------------------------------------------------
def panel_frame(u, v, off=0.0):
    """local x = right (+Y), y = panel up, z = toward the pilot."""
    return (L.panel_pt(u, v, off), (0, 1, 0), L.PANEL_UP, L.PANEL_N)


def console_frame(u, v, z):
    """local x = right (+Y), y = forward (+X), z = up."""
    return ((v, u, z), (0, 1, 0), (1, 0, 0), (0, 0, 1))


def world_frame(o=(0, 0, 0)):
    return (o, (1, 0, 0), (0, 1, 0), (0, 0, 1))


# =====================================================================================================================
# switch-gear (local frame: x right, y "up" on the panel, z out of the panel)
def toggle(P, fr, state=0, guard=None):
    """bat-handle toggle. state 0 = up, 1 = centre, 2 = down."""
    P.add(bm_cyl(0.52, 0.18, 16, 0.05), "CK_Black", frame=fr)                   # bezel washer
    b = bm_lathe([(0, 0.18), (0.36, 0.18), (0.36, 0.42), (0.3, 0.5), (0, 0.5)], 6)   # hex nut
    P.add(b, "CK_Metal", frame=fr)
    tilt = {0: 22, 1: 0, 2: -22}[state]
    o, X, Y, Z = fr
    t = D2R(tilt)
    Zt = tuple(V(Z) * math.cos(t) + V(Y) * math.sin(t))
    Yt = tuple(V(Y) * math.cos(t) - V(Z) * math.sin(t))
    lever = bm_lathe([(0, 0.4), (0.14, 0.4), (0.12, 1.7), (0.2, 1.75), (0.22, 1.9), (0.17, 2.05), (0, 2.08)], 12)
    P.add(lever, "CK_Chrome", frame=(o, X, Yt, Zt))
    if guard:
        g = bm_box(1.25, 2.3, 0.08, 0.03, 1, c=(0, 0.25, 1.35))
        P.add(g, "CK_Red" if guard == "red" else "CK_RedGuard", frame=fr)
        for sx in (-1, 1):
            P.add(bm_box(0.08, 2.3, 1.3, 0.02, 1, c=(sx * 0.6, 0.25, 0.7)), "CK_Red" if guard == "red" else "CK_RedGuard", frame=fr)


def knob(P, fr, small=False, pointer=True):
    r = 0.62 if small else 0.88
    P.add(bm_cyl(r * 1.25, 0.14, 24, 0.04), "CK_Black", frame=fr)               # skirt
    prof = [(0, 0.14), (r, 0.14), (r, 0.9 if not small else 0.7), (r * 0.86, 1.02 if not small else 0.8), (0, 1.04 if not small else 0.82)]
    bm = bm_lathe(prof, 20)
    # flutes: push every other ring vertex inward (knurled grip)
    for v in bm.verts:
        rr = math.hypot(v.co.x, v.co.y)
        if rr > r * 0.95 and 0.2 < v.co.z < (0.85 if not small else 0.66):
            a = math.atan2(v.co.y, v.co.x)
            k = 0.9 if int(round(a / (2 * math.pi / 20))) % 2 else 1.0
            v.co.x *= k
            v.co.y *= k
    P.add(bm, "CK_Knob", frame=fr)
    if pointer:
        h = 1.05 if not small else 0.83
        P.add(bm_box(0.12, r * 0.9, 0.04, c=(0, r * 0.45, h)), "CK_White", frame=fr)


def button(P, fr, w=1.15, h=1.15, ring=None):
    if ring == "stripe":
        bm = bm_lathe([(0.7, 0.25), (1.05, 0.25), (1.05, 0.0), (0.7, 0.0)], 32)
        P.add(bm, "CK_Dial", uv0=lambda p, n: stripe_uv(p), frame=fr)
    P.add(bm_box(w, h, 0.5, 0.12, 2, c=(0, 0, 0.25)), "CK_Black", frame=fr)
    P.add(bm_box(w * 0.78, h * 0.78, 0.25, 0.1, 2, c=(0, 0, 0.6)), "CK_Rubber", frame=fr)


def stripe_uv(p):
    u0, v0, u1, v1 = L.dial_tile("stripe")
    s = 0.1
    return ((u0 + u1) / 2 + ((p[0] + p[2]) * s % 1.0 - 0.5) * (u1 - u0) * 0.9, 1.0 - ((v0 + v1) / 2 + ((p[1]) * s % 1.0 - 0.5) * (v1 - v0) * 0.9))


def light(P, fr, w, h, color):
    P.add(bm_box(w + 0.3, h + 0.3, 0.35, 0.08, 2, c=(0, 0, 0.17)), "CK_Black", frame=fr)
    P.add(bm_box(w, h, 0.2, 0.05, 1, c=(0, 0, 0.42)), {"green": "CK_LensG", "amber": "CK_LensA", "red": "CK_LensR"}[color], frame=fr)


def display(P, fr, w, h):
    P.add(bm_box(w + 0.4, h + 0.4, 0.3, 0.08, 2, c=(0, 0, 0.15)), "CK_Black", frame=fr)


def element(P, kind, fr, opts):
    if kind == "toggle":
        toggle(P, fr, opts.get("state", 0))
    elif kind == "guard":
        toggle(P, fr, opts.get("state", 1), guard=opts.get("color", "redguard"))
    elif kind == "knob":
        knob(P, fr, small=opts.get("small", False))
    elif kind == "button":
        button(P, fr, ring=opts.get("ring"))
    elif kind == "light":
        light(P, fr, opts.get("w", 2), opts.get("h", 1), opts.get("color", "green"))
    elif kind == "display":
        display(P, fr, opts.get("w", 6), opts.get("h", 2))
    elif kind == "gauge":
        d = opts.get("d", 4.6)
        gauge(P, fr, d, opts.get("dial", "o2"), needle_deg=120)


# ---- instruments (local frame: z = toward the pilot) ---------------------------------------------------------------
def needle_bm(length, w0=0.2, w1=0.06, tail=0.25, z=0.0, t=0.06):
    poly = [(-w0 * 0.6, -length * tail), (w0 * 0.6, -length * tail), (w0 / 2, 0), (w1 / 2, length * 0.92), (0, length), (-w1 / 2, length * 0.92),
            (-w0 / 2, 0)]
    poly = [(x, y) for x, y in poly]
    # CCW check
    a = sum(poly[i][0] * poly[(i + 1) % len(poly)][1] - poly[(i + 1) % len(poly)][0] * poly[i][1] for i in range(len(poly)))
    if a < 0:
        poly = poly[::-1]
    return bm_prism(poly, t, z0=z)


def gauge(P, fr, d, dial, needle_deg=None, glass=True, knob_pos=None):
    """bezel ring + dial face + glass; optional fixed needle (static gauges)."""
    R = d / 2.0
    rd = R * 0.8
    prof = [(rd, 0.25), (rd, 0.8), (rd + 0.12, 0.95), (R - 0.14, 1.0), (R, 0.86), (R, 0.0)]
    P.add(bm_lathe(prof, 48), "CK_Black", frame=fr)
    disc = bm_lathe([(0, 0.25), (rd, 0.25)], 48)
    disc.normal_update()
    o, X, Y, Z = fr
    P.add(disc, "CK_Dial", uv0=lambda p, n: dial_uv(dial, (V(p) - V(o)).dot(V(X)), (V(p) - V(o)).dot(V(Y)), rd), frame=fr)
    if glass:
        part("ck_glass").add(bm_lathe([(0, 0.82), (rd + 0.05, 0.82)], 40), "CK_Glass", frame=fr)
    if needle_deg is not None:
        a = D2R(needle_deg)
        Yn = tuple(V(Y) * math.cos(a) + V(X) * math.sin(a))
        Xn = tuple(V(X) * math.cos(a) - V(Y) * math.sin(a))
        P.add(needle_bm(rd * 0.82, z=0.32), "CK_Needle", frame=(o, Xn, Yn, Z))
        P.add(bm_cyl(0.28, 0.2, 16, 0.05, z0=0.36), "CK_Black", frame=fr)
    if knob_pos:
        a = D2R(knob_pos)
        c = (math.sin(a) * (R + 0.15), math.cos(a) * (R + 0.15))
        bm = bm_cyl(0.55, 0.9, 20, 0.12)
        for v in bm.verts:
            v.co.x += c[0]
            v.co.y += c[1]
        P.add(bm, "CK_Knob", frame=fr)


# =====================================================================================================================
# 1. tub: loft of cross-sections from the aft bulkhead to the foot well front
def fillet_poly(pts, r, n=3, skip=()):
    """round every interior corner of an open polyline with radius r (approx)."""
    out = [pts[0]]
    for i in range(1, len(pts) - 1):
        if i in skip:
            out.append(pts[i])
            continue
        p0, p1, p2 = V((0,) + tuple(pts[i - 1])), V((0,) + tuple(pts[i])), V((0,) + tuple(pts[i + 1]))
        a, b = (p0 - p1), (p2 - p1)
        la, lb = a.length, b.length
        if la < 1e-6 or lb < 1e-6:
            continue
        rr = min(r, la * 0.45, lb * 0.45)
        s, e = p1 + a.normalized() * rr, p1 + b.normalized() * rr
        for k in range(n + 1):
            t = k / n
            q = (1 - t) ** 2 * s + 2 * (1 - t) * t * p1 + t * t * e
            out.append((q.y, q.z))
    out.append(pts[-1])
    return out


def tub_section(x):
    gy, gz = L.glass_bottom(max(390.0, x))
    pts = [(gy - 1.6, gz - 1.8)]
    ztop = gz - 1.8
    for k in range(1, 7):
        z = ztop + (L.CONSOLE_Z + 1.0 - ztop) * k / 6
        pts.append((min(pts[-1][0] + 4, L.skin_half_width(x, z) - L.SKIN_GAP), z))
    wout = L.skin_half_width(x, L.CONSOLE_Z) - L.SKIN_GAP
    pts.append((wout, L.CONSOLE_Z))
    pts.append((L.CONSOLE_IN, L.CONSOLE_Z))
    pts.append((L.CONSOLE_IN, 2.0))
    fz = L.floor_z(x)
    pts.append((L.CONSOLE_IN - 7.0, fz + 2.5))
    pts.append((11.0, fz))
    pts.append((0.0, fz))
    half = fillet_poly(pts, 1.2, 3, skip=range(1, 7))
    full = half + [(-y, z) for y, z in half[::-1][1:]]
    return full


def build_tub():
    P = part("ck_shell")
    xs = [L.TUB_X0] + list(range(380, 511, 5)) + [L.TUB_X1]
    secs = [[(x, y, z) for y, z in tub_section(x)] for x in xs]
    bm = bm_loft(secs, cap0=False, cap1=False)
    bm.normal_update()
    # interior must face the cockpit: floor centre normal +Z
    fl = min(bm.faces, key=lambda f: (f.calc_center_median() - V((440, 0, -9))).length)
    flip = fl.normal.z < 0
    P.add(bm, "CK_Paint", flip=flip)
    # bulkheads: aft (faces +X) and front (faces -X), as triangulated caps
    for x, facing in ((L.TUB_X0, 1), (L.TUB_X1, -1)):
        sec = tub_section(x)
        bm = bmesh.new()
        vs = [bm.verts.new((x, y, z)) for y, z in sec]
        f = bm.faces.new(vs)
        bmesh.ops.triangulate(bm, faces=[f])
        bm.normal_update()
        fl = any(fc.normal.x * facing < 0 for fc in bm.faces)
        P.add(bm, "CK_Paint", flip=fl)
    # frames (ribs) on the side walls between console and sill
    for x in (392.0, 414.0, 436.0, 458.0, 480.0):
        sec = tub_section(x)
        i_con = next(i for i, (y, z) in enumerate(sec) if abs(z - L.CONSOLE_Z) < 1e-6)
        for sgn in (1, -1):
            path = [(x, sgn * (y - 0.4), z) for y, z in sec[1:i_con + 1]]
            sec = [(-0.7, -0.2 * sgn), (0.7, -0.2 * sgn), (0.7, 1.1 * sgn), (-0.7, 1.1 * sgn)]
            P.add(bm_sweep(path, sec, side_hint=(1, 0, 0)), "CK_Paint")


def build_canopy_frame():
    P = part("ck_shell")
    xs = list(range(372, 509, 4))
    for sgn in (1, -1):
        secs = []
        for x in xs:
            gy, gz = L.glass_bottom(max(390.0, x)) if x >= 390 else (L.glass_bottom(390)[0], L.glass_bottom(390)[1] + (390 - x) * 0.06)
            cy, cz = gy - 1.2, gz - 0.6
            secs.append([(x, sgn * (cy + a), cz + b) for a, b in rrect(2.6, 2.3, 0.5, 2)])
        bm = bm_loft(secs, closed=True, cap0=True, cap1=True)
        bm.normal_update()
        flip = sgn < 0
        P.add(bm, "CK_Frame", flip=flip)
    # windscreen bow at BOW_X following the glass arch (inset), and the rear arch behind the seat
    arches = [(L.REAR_ARCH_X, [(33.2, 76.0), (32.4, 88.0)] + L.GLASS_ARCH_372, (4.0, 3.0), 1.6)]
    if L.BOW_X:
        arches.insert(0, (L.BOW_X, L.GLASS_ARCH_468, (2.4, 2.0), 1.4))
    for x, arch, sec, inset in arches:
        half = [(y, z) for y, z in arch]
        pts = half + [(-y, z) for y, z in half[::-1][1:]]
        cz = 60.0
        path = []
        for y, z in pts:
            d = V((0, y, z - cz)).normalized()
            path.append((x, y - d.y * inset, z - d.z * inset))
        bm = bm_sweep(path, rrect(sec[0], sec[1], 0.5, 2), side_hint=(1, 0, 0))
        bm.normal_update()
        P.add(bm, "CK_Frame")
    # rear-view mirrors: small, on short stalks from the canopy sill rails, angled back toward the pilot
    for x, sgn in L.MIRRORS:
        gy, gz = L.glass_bottom(x)
        base = V((x, sgn * (gy - 2.0), gz + 0.6))
        top = base + V((0.0, -sgn * 1.2, 4.2))
        P.add(bm_sweep([tuple(base), tuple(top)], [(0.35 * math.cos(D2R(a)), 0.35 * math.sin(D2R(a))) for a in range(0, 360, 45)], side_hint=(1, 0, 0)),
              "CK_Black")
        yaw = D2R(sgn * 28)
        Xm = (math.cos(yaw), -math.sin(yaw), 0.0)
        fr = (tuple(top + V((0, 0, 1.0))), Xm, (math.sin(yaw), math.cos(yaw), 0.0), (0, 0, 1))
        P.add(bm_box(0.8, 4.4, 2.0, 0.3, 2), "CK_Black", frame=fr)
        P.add(bm_box(0.12, 4.0, 1.6, 0.04, 1, c=(-0.42, 0, 0)), "CK_Mirror", frame=fr)


# =====================================================================================================================
# 2. glare shield + HUD
def glare_section(x):
    gy, gz = L.glass_bottom(min(540.0, x))
    ys = min(L.LIP_Y + 0.5, gy - 1.3)
    zs = L.LIP_Z0 - 0.4 - max(0.0, x - 500) * 0.06
    zt = min(L.LIP_ZC + 0.6 - max(0.0, x - 500) * 0.11, L.glass_top(x) - 2.6)
    pts = []
    for k in range(25):
        t = D2R(-90 + 180 * k / 24)
        pts.append((ys * math.sin(t), zs + (zt - zs) * math.cos(t)))
    return pts


def build_glareshield():
    P = part("ck_shell")
    xs = [498.0, 500.0, 505.0, 512.0, 520.0, 530.0, 540.0, L.GLARE_X1]
    secs = [[(x, y, z) for y, z in glare_section(x)] for x in xs]
    bm = bm_loft(secs)
    bm.normal_update()
    top = max(bm.faces, key=lambda f: f.calc_center_median().z)
    P.add(bm, "CK_AntiGlare", flip=top.normal.z < 0)
    # rounded lip (rubber bumper) along the front edge
    path = [(498.6, y, z - 0.2) for y, z in glare_section(498.0)]
    bm = bm_sweep(path, [(1.1 * math.cos(D2R(a)), 1.1 * math.sin(D2R(a))) for a in range(0, 360, 30)], side_hint=(1, 0, 0))
    bm.normal_update()
    P.add(bm, "CK_Rubber")
    # HUD: projector cap on the glare shield + combiner frame + glass
    cap = bm_box(12.0, L.HUD_W + 4.5, 2.2, 0.6, 3, c=(506.0, 0, L.HUD_Z0 - 0.2))
    P.add(cap, "CK_Black")
    P.add(bm_box(7.0, L.HUD_W, 0.3, 0.1, 1, c=(506.5, 0, L.HUD_Z0 + 0.95)), "CK_HUDExit")
    t = D2R(L.HUD_TILT)
    up = V((-math.sin(t), 0, math.cos(t)))
    fwd = V((math.cos(t), 0, math.sin(t)))
    base = V((L.HUD_X, 0, L.HUD_Z0 + 0.6))
    hh = (L.HUD_Z1 - base.z) / math.cos(t)
    W = L.HUD_W + 1.6
    for sgn in (1, -1):
        o = base + V((0, sgn * W / 2, 0))
        P.add(bm_box(0.9, 0.55, hh, 0.2, 2, c=(0, 0, hh / 2)), "CK_HUDFrame", frame=(tuple(o), tuple(fwd), (0, 1, 0), tuple(up)))
        P.add(bm_box(2.4, 1.6, 1.6, 0.4, 2, c=(0.2, -sgn * 0.0, 0.8)), "CK_HUDFrame", frame=(tuple(o), tuple(fwd), (0, 1, 0), tuple(up)))
    gl = bm_box(0.5, W - 0.8, hh - 1.0, 0.25, 2, c=(-0.2, 0, (hh - 1.0) / 2 + 0.9))
    part("ck_glass").add(gl, "CK_HUDGlass", frame=(tuple(base), tuple(fwd), (0, 1, 0), tuple(up)))


# =====================================================================================================================
# 3. main instrument panel
def panel_outline():
    """(u, v) outline of the panel face, CCW seen from the pilot side (u right, v up)."""
    right = []
    for k in range(13):                                   # lip, top centre -> right
        u = L.LIP_Y * k / 12
        right.append((u, L.lip_z(u) - 0.4))
    v = L.LIP_Z0 - 0.4
    while v > L.CONSOLE_Z + 0.5:
        v -= 2.5
        vv = max(v, L.CONSOLE_Z)
        right.append((L.skin_half_width(L.panel_x(vv), vv) - L.SKIN_GAP - 0.6, vv))
    right.append((L.CONSOLE_IN, L.CONSOLE_Z))
    right.append((L.CONSOLE_IN, L.PANEL_Z0))
    right.append((0.0, L.PANEL_Z0))
    # right goes clockwise (top -> down the right side). Full CCW (seen from the pilot, u to the right):
    left = [(-u, v) for u, v in right[1:-1]]
    pts = right[::-1] + left           # bottom centre -> up right side -> top centre -> down left side
    out = []
    for p in pts:
        if not out or (abs(out[-1][0] - p[0]) > 1e-4 or abs(out[-1][1] - p[1]) > 1e-4):
            out.append(p)
    if abs(out[0][0] - out[-1][0]) < 1e-4 and abs(out[0][1] - out[-1][1]) < 1e-4:
        out.pop()
    return out


def build_panel():
    P = part("ck_shell")
    poly = panel_outline()
    # the slab: polygon in panel (u, v) coords, extruded 2 cm away from the pilot (local z negative)
    bm = bmesh.new()
    pf = [bm.verts.new((u, v, 0.0)) for u, v in poly]
    pb = [bm.verts.new((u, v, -2.0)) for u, v in poly]
    n = len(poly)
    area = sum(poly[i][0] * poly[(i + 1) % n][1] - poly[(i + 1) % n][0] * poly[i][1] for i in range(n))
    fr = bm.faces.new(pf if area > 0 else pf[::-1])
    bm.faces.new(pb[::-1] if area > 0 else pb)
    for i in range(n):
        j = (i + 1) % n
        q = (pf[i], pb[i], pb[j], pf[j]) if area > 0 else (pf[j], pb[j], pb[i], pf[i])
        bm.faces.new(q)
    front_edges = [e for e in bm.edges if all(abs(v.co.z) < 1e-6 for v in e.verts)]
    bmesh.ops.bevel(bm, geom=front_edges, offset=0.35, offset_type='OFFSET', segments=2, profile=0.5, affect='EDGES', clamp_overlap=True)
    bmesh.ops.triangulate(bm, faces=[f for f in bm.faces if len(f.verts) > 4])
    # map local (u, v, h) -> panel frame; local z = toward the pilot
    for v_ in bm.verts:
        u, vv, h = v_.co
        v_.co = V(L.panel_pt(u, vv, h))
    bm.normal_update()
    big = max(bm.faces, key=lambda f: f.calc_area())
    P.add(bm, "CK_Panel", flip=big.normal.x > 0, recalc=False, uv0=lambda p, nn: region_uv("main", p[1], p[2]) if nn[0] < -0.8 else None, swatch="sw_panel")

    # glass displays (screens are Unreal render-target planes at the recess, see manifest): bevelled bezel, recess,
    # anti-glare glass pane in front (ck_glass), a thin bright frame line around the glass
    for tag, (u, v, BW, BH, SW, SH, pw, ph) in L.DISPLAYS.items():
        fr = panel_frame(u, v)
        o, X, Y, Z = fr
        bm = bm_box(BW, BH, 1.8, 0.6, 4, c=(0, 0, 0.9))
        front = [f for f in bm.faces if f.normal.z > 0.99]
        tx, ty = (BW - SW) / 2 - 0.35, (BH - SH) / 2 - 0.35
        bmesh.ops.inset_region(bm, faces=front, thickness=min(tx, ty), depth=0.0)
        bmesh.ops.inset_region(bm, faces=front, thickness=0.2, depth=-0.7)
        P.add(bm, "CK_Bezel", swatch="sw_black", frame=fr)
        part("ck_glass").add(bm_box(SW + 0.3, SH + 0.3, 0.08, 0.02, 1, c=(0, 0, 1.8 - 0.7 + 0.25)), "CK_DispGlass", frame=fr)
        MANIFEST["screens"][tag] = dict(center=list(L.panel_pt(u, v, 1.8 - 0.7 + 0.03)), normal=list(L.PANEL_N), up=list(L.PANEL_UP),
                                        size=[SW, SH], px=[pw, ph])

    # live lights: bezel + tinted lens (legend from the atlas) in the shell; lit overlay = own part (world coords)
    for name, (u, v, w, h, col, legend) in L.LIGHTS.items():
        fr = panel_frame(u, v)
        o, X, Y, Z = fr
        P.add(bm_box(w + 0.7, h + 0.7, 0.9, 0.25, 2, c=(0, 0, 0.45)), "CK_Black", frame=fr)
        uvf = lambda p, nn, o=o, name=name: region_uv("LT_" + name, (V(p) - V(o)).dot(V(X)), (V(p) - V(o)).dot(V(Y))) if V(nn).dot(V(Z)) > 0.9 else None
        P.add(bm_box(w, h, 0.25, 0.08, 1, c=(0, 0, 0.95)), "CK_Panel", uv0=uvf, swatch="sw_black", frame=fr)
        part("ck_lt_" + name).add(bm_box(w, h, 0.05, 0.02, 1, c=(0, 0, 1.11)), "CK_LightLit", uv0=uvf, swatch="sw_black", frame=fr)
        MANIFEST.setdefault("lights", {})[name] = dict(part="ck_lt_" + name, color=col, legend=legend)

    # instruments
    for name, (u, v, d, dial) in L.GAUGES.items():
        if name == "ADI":
            build_adi(u, v, d)
            continue
        fr = panel_frame(u, v)
        live = name in L.LIVE_NEEDLES
        fixed = {"CLOCK": None, "RPM": 205.0, "FTIT": 160.0, "FUEL": 95.0}.get(name)
        gauge(P, fr, d, dial, needle_deg=None if (live or name == "CLOCK") else fixed, knob_pos=225 if name in ("ALT", "ASI") else None)
        if name == "CLOCK":
            o, X, Y, Z = fr
            for ang, ln in ((300.0, 0.55), (60.0, 0.78)):
                a = D2R(ang)
                Yn = tuple(V(Y) * math.cos(a) + V(X) * math.sin(a))
                Xn = tuple(V(X) * math.cos(a) - V(Y) * math.sin(a))
                P.add(needle_bm(d / 2 * 0.8 * ln, 0.22, 0.1, 0.15, z=0.3), "CK_Needle", frame=(o, Xn, Yn, Z))
        if live:
            R = d / 2 * 0.8
            for nd in L.LIVE_NEEDLES[name]:
                long = nd != "alt10k"
                z = 0.42 if long else 0.34
                Pn = part("ck_needle_" + nd)
                if long:
                    Pn.add(needle_bm(R * 0.86, 0.2, 0.07, 0.22, z=0.0, t=0.07), "CK_Needle", frame=needle_local())
                    Pn.add(bm_cyl(0.3, 0.16, 16, 0.05, z0=0.07), "CK_Black", frame=needle_local())
                else:
                    Pn.add(needle_bm(R * 0.55, 0.42, 0.16, 0.12, z=0.0, t=0.07), "CK_Needle", frame=needle_local())
                MANIFEST["needles"][nd] = dict(center=list(L.panel_pt(u, v, z)), x_axis=list(L.PANEL_N), z_axis=list(L.PANEL_UP))

    # gear handle well + lights
    g = L.GEAR_HANDLE
    fr = panel_frame(g["u"], g["v"])
    P.add(bm_box(2.6, 5.4, 0.5, 0.2, 2, c=(0, 0, 0.25)), "CK_Black", frame=fr)
    P.add(bm_box(1.0, 4.6, 0.2, 0.05, 1, c=(0, 0, 0.55)), "CK_Hole", frame=fr)
    pv = L.panel_pt(g["u"], g["v"], 0.6)
    MANIFEST["pivots"]["GearHandle"] = list(pv)
    Pg = part("ck_gearhandle")
    Pg.add(bm_cyl(0.42, g["arm"], 16, 0.1), "CK_Chrome", frame=((0, 0, 0), (0, 1, 0), (0, 0, 1), (-1, 0, 0)))
    wheel = bm_lathe([(0.0, -0.75), (1.3, -0.75), (g["knob"] / 2, -0.45), (g["knob"] / 2, 0.45), (1.3, 0.75), (0.0, 0.75)], 32)
    Pg.add(wheel, "CK_GearKnob", frame=((-g["arm"] - g["knob"] / 2 + 0.4, 0, 0), (1, 0, 0), (0, 0, 1), (0, -1, 0)))
    for (u, v) in L.GEAR_LIGHTS:
        fr = panel_frame(u, v)
        P.add(bm_cyl(0.85, 0.35, 20, 0.08), "CK_Black", frame=fr)
        P.add(bm_lathe([(0, 0.55), (0.52, 0.5), (0.6, 0.35)], 16), "CK_LensG", frame=fr)
        Pl = part("ck_gearlights")
        o = L.panel_pt(u, v, 0.0)
        Pl.add(bm_lathe([(0, 0.6), (0.54, 0.55), (0.62, 0.38)], 16), "CK_LightG",
               frame=(tuple(V(o) - V(pv)), (0, 1, 0), L.PANEL_UP, L.PANEL_N))
    for kind, u, v, label, opts in L.MAIN_ELEMENTS:
        element(P, kind, panel_frame(u, v), opts)


def needle_local():
    """canonical needle frame: x = right, y = up, z = toward the viewer -> local axes of the pivot actor
    (actor X = toward the pilot, Z = dial up, Y = pilot's left): local (x, y, z) -> actor (z, -x, y)."""
    return ((0, 0, 0), (0, -1, 0), (0, 0, 1), (1, 0, 0))


def build_adi(u, v, d):
    P = part("ck_shell")
    fr = panel_frame(u, v)
    o, X, Y, Z = fr
    R = d / 2
    rf = R * 0.8
    rw = rf * 176.0 / 248.0                               # window radius (dial texture: window 176 px of 248)
    hf = 2.05
    prof = [(rw, 0.0), (rw, hf - 0.05), (rf, hf), (rf, hf + 0.35), (rf + 0.15, hf + 0.5), (R - 0.18, hf + 0.55), (R, hf + 0.4), (R, 0.0)]
    P.add(bm_lathe(prof, 48), "CK_Black", frame=fr)
    ring = bm_lathe([(rw, hf), (rf, hf)], 48)
    P.add(ring, "CK_Dial", uv0=lambda p, n: dial_uv("adi", (V(p) - V(o)).dot(V(X)), (V(p) - V(o)).dot(V(Y)), rf), frame=fr)
    part("ck_glass").add(bm_lathe([(0, hf + 0.4), (rf + 0.05, hf + 0.4)], 40), "CK_Glass", frame=fr)
    # fixed aircraft symbol (orange W) in front of the ball
    for sx in (-1, 1):
        P.add(bm_box(rw * 0.55, 0.22, 0.12, 0.04, 1, c=(sx * rw * 0.42, 0, hf - 0.15)), "CK_Orange", frame=fr)
    P.add(bm_box(0.36, 0.36, 0.14, 0.05, 1, c=(0, 0, hf - 0.15)), "CK_Orange", frame=fr)
    P.add(bm_box(0.12, rw * 0.3, 0.12, 0.03, 1, c=(0, -rw * 0.15 - 0.15, hf - 0.15)), "CK_Orange", frame=fr)
    # knob
    gauge_knob = bm_cyl(0.6, 1.0, 20, 0.12)
    a = D2R(225)
    for v_ in gauge_knob.verts:
        v_.co.x += math.sin(a) * (R + 0.2)
        v_.co.y += math.cos(a) * (R + 0.2)
    P.add(gauge_knob, "CK_Knob", frame=fr)
    # the ball (moving part): sphere, equirectangular UV, front (+x local = toward the pilot) = lon 0
    rb = rw * 1.12
    centre_h = hf - 0.06 - rb
    bm = bmesh.new()
    nlat, nlon = 24, 48
    verts = []
    for i in range(nlat + 1):
        lat = -90 + 180 * i / nlat
        row = []
        for j in range(nlon + 1):
            lon = -180 + 360 * j / nlon
            cl = math.cos(D2R(lat))
            # actor frame: X toward the pilot (front), Y = pilot's left, Z up. lon grows to the pilot's right (-Y)
            row.append(bm.verts.new((rb * cl * math.cos(D2R(lon)), -rb * cl * math.sin(D2R(lon)), rb * math.sin(D2R(lat)))))
        verts.append(row)
    for i in range(nlat):
        for j in range(nlon):
            bm.faces.new([verts[i][j], verts[i + 1][j], verts[i + 1][j + 1], verts[i][j + 1]])
    bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=1e-5)
    bm.normal_update()
    out = sum(f.normal.dot(f.calc_center_median()) for f in bm.faces) > 0
    Pb = part("ck_adi_ball")

    def ball_uv(p, n):
        # equirect from the position (seam handled by the face normal side)
        x, y, z = p
        lat = math.degrees(math.asin(max(-1, min(1, z / rb))))
        lon = math.degrees(math.atan2(-y, x))
        nx, ny, nz = n
        nlon_ = math.degrees(math.atan2(-ny, nx))
        if abs(lon - nlon_) > 180:
            lon += 360 if nlon_ > lon else -360
        if abs(lat) > 89.9:
            lon = nlon_
        return ((lon + 180) / 360, (lat + 90) / 180)
    Pb.add(bm, "CK_ADI", uv0=ball_uv, flip=not out, recalc=False)
    MANIFEST["pivots"]["ADIBall"] = dict(center=list(L.panel_pt(u, v, centre_h)), x_axis=[-1.0, 0.0, 0.0], z_axis=[0.0, 0.0, 1.0])


# =====================================================================================================================
# 4. consoles
def build_consoles():
    P = part("ck_shell")
    z = L.CONSOLE_Z
    for name, u0, u1, v0, v1, title, elems in L.CONSOLE_PANELS:
        bm = bm_box(u1 - u0 - 0.2, v1 - v0 - 0.2, 0.5, 0.18, 2, c=((u0 + u1) / 2, (v0 + v1) / 2, z + 0.25))
        fr = ((0, 0, 0), (0, 1, 0), (1, 0, 0), (0, 0, 1))
        P.add(bm, "CK_Panel", uv0=lambda p, nn, name=name: region_uv(name, p[1], p[0]) if nn[2] > 0.9 else None, swatch="sw_panel", frame=fr)
        for kind, u, v, label, opts in elems:
            element(P, kind, console_frame(u, v, z + 0.5), opts)
    # throttle quadrant housing
    T = L.THR_HOUSING
    bm = bm_box(T["u1"] - T["u0"], T["v1"] - T["v0"], T["h"], 0.6, 3, c=((T["u0"] + T["u1"]) / 2, (T["v0"] + T["v1"]) / 2, z + T["h"] / 2))
    P.add(bm, "CK_Panel", uv0=lambda p, nn: region_uv("thr", p[1], p[0]) if nn[2] > 0.9 else None, swatch="sw_panel",
          frame=((0, 0, 0), (0, 1, 0), (1, 0, 0), (0, 0, 1)))
    # side wall trim plates between the frames (riveted panels from the atlas "wall" tile), slightly inside the tub wall
    for x0, x1 in ((393.5, 412.5), (415.5, 434.5), (437.5, 456.5), (459.5, 478.5), (481.5, 496.0)):
        for sgn in (1, -1):
            secs = []
            for x in (x0, x1):
                sec = tub_section(x)
                i_con = next(i for i, (y, z) in enumerate(sec) if abs(z - L.CONSOLE_Z) < 1e-6)
                wall = [(y, z) for y, z in sec[1:i_con] if z > L.CONSOLE_Z + 2.5]
                secs.append([(x, sgn * (y - 0.45), z) for y, z in wall])
            n = min(len(a_) for a_ in secs)
            secs = [sc[:n] for sc in secs]
            if n < 2:
                continue
            bm = bm_loft(secs)
            bm.normal_update()
            f0 = bm.faces[0] if hasattr(bm.faces, "__getitem__") and (bm.faces.ensure_lookup_table() or True) else None
            flip = f0.normal.y * sgn > 0                       # must face the cockpit centre
            zb = min(p[2] for sc in secs for p in sc)
            P.add(bm, "CK_Wall", flip=flip, recalc=False,
                  uv0=lambda p, nn, x0=x0, zb=zb: region_uv("wall", min(1.0, (p[0] - x0) / 60.0), min(1.0, (p[2] - zb) / 30.0)), swatch="sw_console")
    # side wall details: canopy jettison T-handle (left), map case (right), utility lights
    o = V((418.0, -(L.skin_half_width(418, 56) - L.SKIN_GAP - 0.4), 56.0))
    P.add(bm_box(5.0, 1.2, 3.0, 0.4, 2, c=(0, 0.6, 0)), "CK_Black", frame=(tuple(o), (1, 0, 0), (0, 1, 0), (0, 0, 1)))
    P.add(bm_cyl(0.45, 3.0, 12, 0.1), "CK_Dial", uv0=lambda p, n: stripe_uv(p), frame=(tuple(o + V((-1.5, 2.6, 0))), (0, 0, 1), (1, 0, 0), (0, 1, 0)))
    P.add(bm_box(6.0, 1.2, 1.2, 0.5, 2, c=(0, 3.9, 0)), "CK_Dial", uv0=lambda p, n: stripe_uv(p), frame=(tuple(o), (1, 0, 0), (0, 1, 0), (0, 0, 1)))
    for xx, sgn, r in ((440.0, -1, 1.6), (446.0, 1, 1.3), (452.0, 1, 0.9)):
        P.add(bm_cyl(r, 1.6, 20, 0.25), "CK_Metal", frame=((xx, sgn * L.CONSOLE_IN, 28.0), (1, 0, 0), (0, 0, 1), (0, -sgn, 0)))
        P.add(bm_cyl(r * 0.6, 1.9, 16, 0.15), "CK_Black", frame=((xx, sgn * L.CONSOLE_IN, 28.0), (1, 0, 0), (0, 0, 1), (0, -sgn, 0)))
    xr = 400.0
    o = V((xr, L.skin_half_width(xr, 48) - L.SKIN_GAP - 1.6, 48.0))
    P.add(bm_box(16.0, 3.0, 12.0, 0.6, 3), "CK_Paint2", frame=(tuple(o), (1, 0, 0), (0, 1, 0), (0, 0, 1)))
    P.add(bm_box(15.0, 0.4, 3.0, 0.15, 1, c=(0, -1.6, 4.0)), "CK_Black", frame=(tuple(o), (1, 0, 0), (0, 1, 0), (0, 0, 1)))
    for xx, sgn in ((395.0, -1), (470.0, 1), (470.0, -1)):
        y = sgn * (L.skin_half_width(xx, 62) - L.SKIN_GAP - 1.0)
        bm = bm_cyl(1.1, 2.4, 16, 0.3)
        P.add(bm, "CK_Black", frame=((xx, y, 62.0), (1, 0, 0), (0, -0.6, sgn * 0.8), (0, -sgn * 0.8, -0.6)))


# =====================================================================================================================
# 5. hand / foot controls (moving parts, mesh origin = pivot)
def build_stick():
    px, py, pz = L.STICK_PIVOT
    S = part("ck_shell")
    # fixed: column from the floor between the knees + cup around the boot
    fz = L.floor_z(px)
    S.add(bm_box(5.0, 5.0, (pz - 3.5) - fz, 0.8, 3, c=(px, py, (fz + pz - 3.5) / 2)), "CK_Paint2")
    S.add(bm_lathe([(2.8, pz - 3.0), (3.6, pz - 2.2), (4.2, pz - 2.4), (4.4, pz - 3.6), (4.1, pz - 4.4), (2.6, pz - 4.5)], 32), "CK_Black",
          frame=((px, py, 0), (1, 0, 0), (0, 1, 0), (0, 0, 1)))
    P = part("ck_stick")
    # boot: bellows
    prof = [(0, -2.5)]
    for k in range(9):
        z = -2.4 + k * 0.85
        r = 3.6 - k * 0.27
        prof.append((r + (0.35 if k % 2 == 0 else 0.0), z))
    prof += [(1.15, 5.4), (0, 5.4)]
    P.add(bm_lathe(prof, 32), "CK_Rubber")
    g0, g1 = L.STICK_GRIP_Z0 - pz, L.STICK_GRIP_Z1 - pz
    P.add(bm_cyl(0.95, g0 - 3.0, 24, 0.1, z0=3.5), "CK_Chrome")
    P.add(bm_cyl(1.35, 1.2, 24, 0.3, z0=g0 - 1.0), "CK_Black")       # collar
    # grip: subdivided cage, ergonomic (front = +x, pilot's palm wraps from behind)
    H = g1 - g0
    cage = bmesh.new()
    rings = []
    shape = [(0.00, 1.85, 2.05, 0.0), (0.18, 2.05, 2.15, 0.2), (0.45, 2.15, 2.05, 0.0), (0.68, 2.0, 1.95, -0.2), (0.82, 2.25, 2.1, 0.6),
             (0.94, 2.4, 2.1, 1.2), (1.0, 2.0, 1.8, 1.4)]
    for t, ax, ay, dx in shape:
        z = g0 + t * H
        ring = []
        for a in range(0, 360, 45):
            c, s = math.cos(D2R(a)), math.sin(D2R(a))
            ring.append(cage.verts.new((dx + ax * c, ay * s, z)))
        rings.append(ring)
    for k in range(len(rings) - 1):
        for i in range(8):
            j = (i + 1) % 8
            cage.faces.new((rings[k][i], rings[k][j], rings[k + 1][j], rings[k + 1][i]))
    cage.faces.new(rings[0][::-1])
    cage.faces.new(rings[-1])
    grip = subsurf(cage, 2)
    P.add(grip, "CK_Grip")
    # trigger + guard (front, index finger), pinky paddle (lower front), hats + weapon release (top)
    P.add(bm_box(1.0, 1.1, 2.4, 0.35, 2, c=(2.6, 0, g0 + 0.66 * H)), "CK_Chrome")
    P.add(bm_box(1.2, 1.0, 3.6, 0.3, 2, c=(3.4, 0, g0 + 0.6 * H)), "CK_Grip")
    P.add(bm_box(0.8, 3.0, 1.4, 0.3, 2, c=(2.3, 0, g0 + 0.18 * H)), "CK_Chrome")
    top = g0 + H + 0.2
    for cx, cy, r in ((1.6, 0.0, 0.62), (0.2, -0.95, 0.5)):
        P.add(bm_cyl(r, 0.35, 16, 0.08, z0=top - 0.35), "CK_Black", frame=((cx, cy, 0), (1, 0, 0), (0, 1, 0), (0, 0, 1)))
        P.add(bm_lathe([(0, top + 0.5), (0.3, top + 0.45), (0.38, top + 0.1), (0.3, top), (0, top)], 12), "CK_Chrome",
              frame=((cx, cy, 0), (1, 0, 0), (0, 1, 0), (0, 0, 1)))
    P.add(bm_cyl(0.5, 0.4, 16, 0.1, z0=top - 0.45), "CK_Red", frame=((0.6, 1.1, 0), (1, 0, 0), (0, 1, 0), (0, 0, 1)))
    P.add(bm_box(0.9, 0.5, 0.8, 0.2, 2, c=(-0.4, -2.2, g0 + 0.82 * H)), "CK_Black")              # thumb button (left side)
    MANIFEST["pivots"]["StickPivot"] = [px, py, pz]


def build_throttle():
    px, py, pz = L.THR_PIVOT
    P = part("ck_throttle")
    g0, g1 = L.THR_GRIP_Z0 - pz, L.THR_GRIP_Z1 - pz
    P.add(bm_cyl(1.9, 3.6, 28, 0.3, z0=-1.8), "CK_Black", frame=((0, 0, 0), (1, 0, 0), (0, 0, 1), (0, -1, 0)))     # hub (axis y)
    P.add(bm_box(1.6, 1.2, g0 + 0.6, 0.25, 2, c=(0, 0, (g0 + 0.6) / 2)), "CK_Chrome")
    H = g1 - g0
    cage = bmesh.new()
    rings = []
    shape = [(0.0, 2.0, 2.2, 0.0, 0.0), (0.25, 2.25, 2.5, 0.1, 0.0), (0.55, 2.4, 2.6, 0.3, 0.1), (0.8, 2.5, 2.55, 0.6, 0.2), (0.95, 2.6, 2.3, 0.9, 0.2),
             (1.0, 2.1, 1.9, 1.0, 0.2)]
    for t, ax, ay, dx, dy in shape:
        z = g0 + t * H
        ring = []
        for a in range(0, 360, 45):
            c, s = math.cos(D2R(a)), math.sin(D2R(a))
            ring.append(cage.verts.new((dx + ax * c, dy + ay * s, z)))
        rings.append(ring)
    for k in range(len(rings) - 1):
        for i in range(8):
            j = (i + 1) % 8
            cage.faces.new((rings[k][i], rings[k][j], rings[k + 1][j], rings[k + 1][i]))
    cage.faces.new(rings[0][::-1])
    cage.faces.new(rings[-1])
    P.add(subsurf(cage, 2), "CK_Grip")
    # inboard (+y, right side = thumb of the left hand): hat, slew, speedbrake slider; front: finger lift + switch
    sy = 2.75
    for cz, kind in ((g0 + 0.78 * H, "hat"), (g0 + 0.55 * H, "slew"), (g0 + 0.3 * H, "slider")):
        fr = ((0.4, sy, cz), (1, 0, 0), (0, 0, 1), (0, 1, 0))
        if kind == "hat":
            P.add(bm_cyl(0.6, 0.35, 16, 0.08), "CK_Black", frame=fr)
            P.add(bm_lathe([(0, 0.85), (0.32, 0.8), (0.4, 0.4), (0.3, 0.3), (0, 0.3)], 12), "CK_Chrome", frame=fr)
        elif kind == "slew":
            P.add(bm_box(1.1, 1.1, 0.5, 0.2, 2, c=(0, 0, 0.25)), "CK_Black", frame=fr)
            P.add(bm_cyl(0.35, 0.3, 12, 0.08, z0=0.45), "CK_Rubber", frame=fr)
        else:
            P.add(bm_box(2.2, 0.8, 0.3, 0.12, 1, c=(0, 0, 0.15)), "CK_Black", frame=fr)
            P.add(bm_box(0.7, 0.9, 0.6, 0.2, 2, c=(0.5, 0, 0.45)), "CK_Chrome", frame=fr)
    P.add(bm_box(0.9, 2.6, 0.9, 0.3, 2, c=(2.75, 0.1, g0 + 0.62 * H)), "CK_Chrome")          # finger lift / cutoff
    P.add(bm_cyl(0.42, 0.4, 14, 0.08), "CK_Red", frame=((2.4, 0.6, g0 + 0.9 * H), (0, 1, 0), (0, 0, 1), (1, 0, 0)))
    MANIFEST["pivots"]["ThrottlePivot"] = [px, py, pz]


def build_pedals():
    for tag, sgn in (("PedalL", -1), ("PedalR", 1)):
        P = part("ck_pedal_l" if sgn < 0 else "ck_pedal_r")
        lean = D2R(L.PEDAL_LEAN)
        up = (math.sin(lean), 0, math.cos(lean))
        fwd = (math.cos(lean), 0, -math.sin(lean))
        fr = ((0, 0, 0), fwd, (0, 1, 0), up)
        # plate (local x = thickness toward the front, z = up the pedal)
        P.add(bm_box(1.0, L.PEDAL_W, L.PEDAL_H, 0.3, 2, c=(0.5, 0, L.PEDAL_H / 2 + 0.4)), "CK_Metal", frame=fr)
        for k in range(9):                                                  # rubber tread
            P.add(bm_box(0.35, L.PEDAL_W - 1.4, 0.8, 0.12, 1, c=(-0.12, 0, 4.0 + k * 1.95)), "CK_Rubber", frame=fr)
        for s in (-1, 1):                                                   # side flanges
            P.add(bm_box(1.8, 0.5, L.PEDAL_H - 2, 0.15, 1, c=(-0.3, s * (L.PEDAL_W / 2 - 0.1), L.PEDAL_H / 2 + 0.6)), "CK_Metal", frame=fr)
        P.add(bm_box(3.2, L.PEDAL_W, 0.8, 0.3, 2, c=(-1.4, 0, 0.8)), "CK_Metal", frame=fr)              # heel lip
        P.add(bm_cyl(0.7, L.PEDAL_W + 1.0, 16, 0.1, z0=-(L.PEDAL_W + 1.0) / 2), "CK_Chrome", frame=((0, 0, 0), (1, 0, 0), (0, 0, 1), (0, -1, 0)))
        P.add(bm_box(2.0, 1.4, 5.0, 0.3, 2, c=(0.4, -sgn * 2.0, -2.2)), "CK_Paint2")                    # arm down to the rudder bar
        MANIFEST["pivots"][tag] = [L.PEDAL_HINGE_X, sgn * L.PEDAL_Y, L.PEDAL_HINGE_Z]
    S = part("ck_shell")
    fz = L.floor_z(L.PEDAL_HINGE_X)
    S.add(bm_box(7.0, 34.0, 3.0, 0.6, 2, c=(L.PEDAL_HINGE_X + 1.0, 0, L.PEDAL_HINGE_Z - 4.0)), "CK_Paint2")    # rudder bar housing
    S.add(bm_box(16.0, 34.0, 0.8, 0.3, 2, c=(L.PEDAL_HINGE_X - 18.0, 0, fz + 0.4)), "CK_Rubber")             # heel plate


# =====================================================================================================================
# 6. ejection seat + harness
def build_seat():
    P = part("ck_shell")
    zs = L.SEAT_Z
    x0, x1 = L.SEAT_BACK_X + 1.0, L.SEAT_FRONT_X
    fz = L.floor_z(430)
    # bucket base
    P.add(bm_box(x1 - x0, 46.0, zs - 4 - fz, 1.2, 3, c=((x0 + x1) / 2, 0, (zs - 4 + fz) / 2)), "CK_Seat")
    for s in (-1, 1):
        poly = [(x0, zs - 6), (x1, zs - 6), (x1, zs + 1.5), (x1 - 8, zs + 4.5), (x0, zs + 6.5)]
        bm = bm_prism([(x, z) for x, z in poly], 2.4, bevel=0.5, seg=2)
        P.add(bm, "CK_Seat", frame=((0, s * 22.8 + 1.2, 0), (1, 0, 0), (0, 0, 1), (0, -1, 0)))
    # cushion (soft): subdivided cage
    cage = bm_box(x1 - x0 - 2.0, 40.0, 4.6, 1.6, 1, c=((x0 + x1) / 2 + 0.5, 0, zs - 2.2))
    P.add(subsurf(cage, 2), "CK_Fabric")
    # backrest (reclined) + cushion + headrest
    t = D2R(L.SEAT_RECLINE)
    up = V((-math.sin(t), 0, math.cos(t)))
    fwd = V((math.cos(t), 0, math.sin(t)))
    o = V((L.SEAT_BACK_X - 2.0, 0, zs - 2.0))
    fr = (tuple(o), tuple(fwd), (0, 1, 0), tuple(up))
    P.add(bm_box(4.0, 46.0, 72.0, 1.2, 3, c=(-2.0, 0, 36.0)), "CK_Seat", frame=fr)
    for s in (-1, 1):
        P.add(bm_box(7.0, 3.0, 44.0, 0.8, 2, c=(1.5, s * 21.5, 22.0)), "CK_Seat", frame=fr)                 # side bolsters
        P.add(bm_box(3.0, 2.2, 74.0, 0.5, 2, c=(-5.0, s * 17.0, 37.0)), "CK_Metal", frame=fr)                # catapult rails
    cage = bm_box(5.0, 38.0, 46.0, 1.5, 1, c=(2.5, 0, 25.0))
    P.add(subsurf(cage, 2), "CK_Fabric", frame=fr)
    P.add(bm_box(11.0, 28.0, 25.0, 2.0, 3, c=(1.5, 0, 82.0)), "CK_Seat", frame=fr)                         # headrest box
    cage = bm_box(4.0, 22.0, 15.0, 1.4, 1, c=(8.6, 0, 82.0))
    P.add(subsurf(cage, 2), "CK_Fabric", frame=fr)                                                         # headrest pad
    for s in (-1, 1):                                                                                     # canopy breakers
        P.add(bm_lathe([(0, 94.0), (0.9, 94.0), (0.7, 97.0), (0.15, 99.2), (0, 99.3)], 12), "CK_Metal",
              frame=(tuple(o + V((0, s * 9.0, 0))), tuple(fwd), (0, 1, 0), tuple(up)))
    P.add(bm_box(8.0, 30.0, 6.0, 1.0, 2, c=(-1.0, 0, 67.0)), "CK_Seat", frame=fr)                          # shoulder harness reel
    # ejection handle (yellow / black loop) at the seat front between the knees
    path = []
    for k in range(13):
        a = D2R(-90 + 180 * k / 12)
        path.append((x1 + 0.8 + 2.4 * math.cos(a), 6.5 * math.sin(a), zs - 4.0 - 2.0 * math.cos(a)))
    bm = bm_sweep(path, [(0.7 * math.cos(D2R(a)), 0.7 * math.sin(D2R(a))) for a in range(0, 360, 45)], side_hint=(0, 0, 1))
    P.add(bm, "CK_Dial", uv0=lambda p, n: stripe_uv(p))
    # harness: shoulder straps down the backrest cushion onto the pan, lap belts, buckle
    Wb = part("ck_shell")
    for s in (-1, 1):
        base = o + fwd * 5.6
        p0 = base + up * 66.0 + V((0, s * 8.5, 0))
        p1 = base + up * 30.0 + V((0, s * 9.5, 0))
        p2 = base + up * 6.0 + V((0.8, s * 8.0, 0))
        p3 = V((x0 + 18.0, s * 4.0, zs + 0.5))
        p4 = V((x0 + 27.0, s * 1.2, zs + 0.6))
        pts = [p0, p1, p2, p3, p4]
        Wb.add(bm_sweep([tuple(p) for p in pts], [(-2.3, 0), (2.3, 0), (2.3, 0.28), (-2.3, 0.28)], side_hint=(0, 1, 0)), "CK_Webbing")
        lp = [V((x0 + 6.0, s * 22.0, zs + 3.0)), V((x0 + 14.0, s * 18.0, zs + 0.6)), V((x0 + 24.0, s * 7.0, zs + 0.5)), V((x0 + 27.5, s * 2.0, zs + 0.6))]
        Wb.add(bm_sweep([tuple(p) for p in lp], [(-2.4, 0), (2.4, 0), (2.4, 0.3), (-2.4, 0.3)], side_hint=(1, 0, 0)), "CK_Webbing")
    neg = [V((x1 - 1.0, 0, zs - 1.0)), V((x1 - 6.0, 0, zs + 0.5)), V((x0 + 30.0, 0, zs + 0.6))]
    Wb.add(bm_sweep([tuple(p) for p in neg], [(-2.0, 0), (2.0, 0), (2.0, 0.28), (-2.0, 0.28)], side_hint=(0, 1, 0)), "CK_Webbing")
    P.add(bm_cyl(3.0, 1.0, 28, 0.35, z0=zs + 0.5), "CK_Chrome", frame=((x0 + 28.0, 0, 0), (1, 0, 0), (0, 1, 0), (0, 0, 1)))
    P.add(bm_cyl(1.6, 0.4, 20, 0.1, z0=zs + 1.4), "CK_Black", frame=((x0 + 28.0, 0, 0), (1, 0, 0), (0, 1, 0), (0, 0, 1)))


# =====================================================================================================================
# export
MANIFEST = dict(made=None, frame="UE body cm, X fwd, Y right, Z up; eye (430, 0, 100)", pivots={}, needles={}, screens={}, parts={})
TRAVEL = dict(stick_deg=L.STICK_TRAVEL, throttle_swing_deg=L.THR_SWING, pedal_cm=L.PEDAL_TRAVEL_CM, toe_brake_deg=L.TOE_BRAKE_DEG,
              gear_handle_deg=L.GEAR_HANDLE["travel"])


def to_object(P):
    me = bpy.data.meshes.new(P.name)
    verts = [(x / 100.0, -y / 100.0, z / 100.0) for x, y, z in P.V]
    faces = [f[::-1] for f in P.F]
    uv0 = []
    uv1 = []
    k = 0
    for f in P.F:
        n = len(f)
        uv0.extend(P.UV0[k:k + n][::-1])
        uv1.extend(P.UV1[k:k + n][::-1])
        k += n
    me.from_pydata(verts, [], faces)
    l0, l1 = me.uv_layers.new(name="UV0"), me.uv_layers.new(name="UV1")
    if len(me.loops) == len(uv0):
        l0.data.foreach_set("uv", [c for uv in uv0 for c in uv])
        l1.data.foreach_set("uv", [c for uv in uv1 for c in uv])
    else:
        print("[cockpit] WARNING uv count mismatch", P.name, len(me.loops), len(uv0))
    me.polygons.foreach_set("material_index", P.M[:len(me.polygons)])
    for mname in P.slots:
        mat = bpy.data.materials.get(mname) or bpy.data.materials.new(mname)
        me.materials.append(mat)
    me.shade_smooth()
    try:
        me.set_sharp_from_angle(angle=D2R(38))
    except Exception as e:
        print("[cockpit] sharp from angle", e)
    # edge wear / cavity mask -> vertex colour R (convex edges bright), G = 0.5 flat
    bm = bmesh.new()
    bm.from_mesh(me)
    bm.normal_update()
    vals = []
    for v in bm.verts:
        s, c = 0.0, 0
        for e in v.link_edges:
            d = e.other_vert(v).co - v.co
            if d.length > 1e-9:
                s += d.normalized().dot(v.normal)
                c += 1
        vals.append(s / c if c else 0.0)
    # per face corner: large flat faces stay neutral (otherwise the edge value is interpolated across the whole face
    # and the wear mask smears into cloudy patches); small faces (bevels, edges, details) carry the vertex value.
    # Blender byte colour -> FBX -> Unreal ends up sRGB-encoded twice (flat 0.5 arrived as 0.886, checked in UE), so
    # pre-decode twice: Unreal's VertexColor then reads w (0.5 flat, > 0.5 convex edges, < 0.5 cavities)
    lin = lambda c: c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
    enc = lambda w: lin(lin(max(0.0, min(1.0, w))))
    big = [f.calc_area() > 6e-4 for f in bm.faces]          # > 6 cm^2
    loopvals = [0.0] * len(me.loops)
    for f, isbig in zip(bm.faces, big):
        for l in f.loops:
            loopvals[l.index] = enc(0.5 if isbig else 0.5 - vals[l.vert.index] * 2.2)
    bm.free()
    col = me.color_attributes.new("Col", 'BYTE_COLOR', 'CORNER')
    for i, w in enumerate(loopvals):
        col.data[i].color = (w, w, w, 1.0)
    ob = bpy.data.objects.new(P.name, me)
    bpy.context.scene.collection.objects.link(ob)
    m = ob.modifiers.new("wn", 'WEIGHTED_NORMAL')
    m.keep_sharp = True
    m.weight = 50
    return ob


def export(ob, path):
    bpy.ops.object.select_all(action='DESELECT')
    ob.select_set(True)
    bpy.context.view_layer.objects.active = ob
    bpy.ops.export_scene.fbx(filepath=path, use_selection=True, axis_forward='X', axis_up='Z', apply_unit_scale=True, global_scale=1.0,
                             apply_scale_options='FBX_SCALE_NONE', bake_space_transform=True, mesh_smooth_type='OFF', use_mesh_modifiers=True,
                             use_tspace=False, colors_type='LINEAR', add_leaf_bones=False, object_types={'MESH'}, path_mode='STRIP')


def preview_materials():
    """simple look for the Blender preview renders only (Unreal has its own materials)."""
    def img(n):
        p = os.path.join(TEX, n)
        return bpy.data.images.load(p, check_existing=True)
    flat = dict(CK_Paint=(0.06, 0.065, 0.07, 0.6, 0), CK_Paint2=(0.04, 0.042, 0.045, 0.6, 0), CK_Black=(0.012, 0.012, 0.013, 0.5, 0),
                CK_AntiGlare=(0.008, 0.008, 0.009, 0.95, 0), CK_Metal=(0.35, 0.36, 0.37, 0.4, 1), CK_Chrome=(0.7, 0.7, 0.7, 0.2, 1),
                CK_Frame=(0.05, 0.053, 0.056, 0.45, 0), CK_Rubber=(0.02, 0.02, 0.02, 0.8, 0), CK_Grip=(0.025, 0.025, 0.026, 0.7, 0),
                CK_Fabric=(0.06, 0.07, 0.045, 0.95, 0), CK_Webbing=(0.11, 0.12, 0.07, 0.85, 0), CK_Seat=(0.02, 0.021, 0.023, 0.55, 0),
                CK_Red=(0.5, 0.02, 0.02, 0.4, 0), CK_RedGuard=(0.45, 0.03, 0.02, 0.4, 0), CK_White=(0.8, 0.8, 0.8, 0.5, 0),
                CK_Knob=(0.015, 0.015, 0.016, 0.45, 0), CK_Needle=(0.9, 0.9, 0.88, 0.5, 0), CK_Orange=(0.9, 0.3, 0.02, 0.5, 0),
                CK_LensG=(0.02, 0.15, 0.04, 0.1, 0), CK_LensA=(0.3, 0.15, 0.01, 0.1, 0), CK_LensR=(0.3, 0.02, 0.01, 0.1, 0),
                CK_LightG=(0.1, 1.0, 0.25, 0.1, 0), CK_Hole=(0.0, 0.0, 0.0, 0.9, 0), CK_GearKnob=(0.85, 0.85, 0.82, 0.35, 0),
                CK_HUDFrame=(0.03, 0.03, 0.032, 0.4, 1), CK_HUDExit=(0.0, 0.02, 0.01, 0.1, 0), CK_Mirror=(0.9, 0.9, 0.9, 0.02, 1),
                CK_Glass=(0.8, 0.85, 0.9, 0.02, 0), CK_HUDGlass=(0.6, 0.8, 0.7, 0.02, 0))
    for m in bpy.data.materials:
        m.use_nodes = True
        nt = m.node_tree
        bsdf = nt.nodes.get("Principled BSDF")
        if bsdf is None:
            continue
        if m.name in ("CK_Panel", "CK_Dial", "CK_ADI"):
            t = nt.nodes.new("ShaderNodeTexImage")
            t.image = img({"CK_Panel": "T_CkPanels.png", "CK_Dial": "T_CkDials.png", "CK_ADI": "T_CkADI.png"}[m.name])
            uvn = nt.nodes.new("ShaderNodeUVMap")
            uvn.uv_map = "UV0"
            nt.links.new(uvn.outputs[0], t.inputs[0])
            nt.links.new(t.outputs["Color"], bsdf.inputs["Base Color"])
            if m.name != "CK_ADI":
                mul = nt.nodes.new("ShaderNodeMixRGB")
                mul.blend_type = 'MULTIPLY'
                mul.inputs[0].default_value = 1.0
                nt.links.new(t.outputs["Color"], mul.inputs[1])
                nt.links.new(t.outputs["Alpha"], mul.inputs[2])
                nt.links.new(mul.outputs[0], bsdf.inputs["Emission Color"])
                bsdf.inputs["Emission Strength"].default_value = 0.6
            bsdf.inputs["Roughness"].default_value = 0.55
        elif m.name in flat:
            r, g, b, ro, me = flat[m.name]
            bsdf.inputs["Base Color"].default_value = (r, g, b, 1)
            bsdf.inputs["Roughness"].default_value = ro
            bsdf.inputs["Metallic"].default_value = me
            if m.name in ("CK_Glass", "CK_HUDGlass"):
                bsdf.inputs["Alpha"].default_value = 0.12
                m.blend_method = 'BLEND' if hasattr(m, "blend_method") else None
            if m.name in ("CK_LightG", "CK_Needle"):
                bsdf.inputs["Emission Color"].default_value = (r, g, b, 1)
                bsdf.inputs["Emission Strength"].default_value = 2.0 if m.name == "CK_LightG" else 0.3


def preview_render(objs, outdir):
    os.makedirs(outdir, exist_ok=True)
    sc = bpy.context.scene
    try:
        sc.render.engine = 'BLENDER_EEVEE_NEXT'
    except Exception:
        sc.render.engine = 'BLENDER_EEVEE'
    sc.render.resolution_x, sc.render.resolution_y = 1280, 720
    w = bpy.data.worlds.new("w")
    w.use_nodes = True
    w.node_tree.nodes["Background"].inputs[0].default_value = (0.45, 0.6, 0.85, 1)
    w.node_tree.nodes["Background"].inputs[1].default_value = 1.0
    sc.world = w
    sun = bpy.data.lights.new("sun", 'SUN')
    sun.energy = 4.0
    so = bpy.data.objects.new("sun", sun)
    so.rotation_euler = (D2R(40), 0, D2R(-140))
    sc.collection.objects.link(so)
    cam = bpy.data.cameras.new("cam")
    cam.sensor_fit = 'HORIZONTAL'
    cam.angle = D2R(75)
    cam.clip_start = 0.02
    co = bpy.data.objects.new("cam", cam)
    sc.collection.objects.link(co)
    sc.camera = co
    try:
        sc.view_settings.view_transform = 'AgX'
    except Exception:
        pass
    ex, ey, ez = L.EYE
    for name, pitch, yaw in (("fwd", -12, 0), ("down", -42, 0), ("left", -38, 58), ("right", -38, -58)):
        co.location = (ex / 100, -ey / 100, ez / 100)
        # blender camera looks down -Z; rotate: x = 90 + pitch, z = -90 + yaw (looking along +X)
        co.rotation_euler = (D2R(90 + pitch), 0, D2R(-90 + yaw))
        sc.render.filepath = os.path.join(outdir, name + ".png")
        bpy.ops.render.render(write_still=True)
    # outside 3/4 view
    co.location = (6.6, 1.2, 2.2)
    co.rotation_euler = (D2R(62), 0, D2R(108))
    sc.render.filepath = os.path.join(outdir, "outside.png")
    bpy.ops.render.render(write_still=True)


def main():
    import time
    bpy.ops.wm.read_factory_settings(use_empty=True)
    t0 = time.time()
    build_tub()
    build_canopy_frame()
    build_glareshield()
    build_panel()
    build_consoles()
    build_stick()
    build_throttle()
    build_pedals()
    build_seat()
    objs = {}
    for name, P in PARTS.items():
        ob = to_object(P)
        objs[name] = ob
        path = os.path.join(ART, name + ".fbx")
        export(ob, path)
        MANIFEST["parts"][name] = dict(fbx=name + ".fbx", slots=list(P.slots), tris=sum(len(f) - 2 for f in P.F))
        print("[cockpit] exported", name, "verts", len(P.V), "faces", len(P.F), "slots", P.slots)
    MANIFEST["made"] = time.strftime("%Y-%m-%d %H:%M:%S")
    MANIFEST["travel"] = TRAVEL
    MANIFEST["inputs"] = dict(layout="Scripts/cockpit/layout.py", rig_eye_mm=list(L.RIG_EYE), eye=list(L.EYE))
    json.dump(MANIFEST, open(os.path.join(ART, "manifest.json"), "w"), indent=1)
    print("[cockpit] built in %.1f s, total tris %d" % (time.time() - t0, sum(p["tris"] for p in MANIFEST["parts"].values())))
    if "--no-preview" not in ARGS:
        preview_materials()
        # pose the moving parts at their pivots for the preview
        for name, ob in objs.items():
            pv = None
            if name == "ck_stick":
                pv = MANIFEST["pivots"]["StickPivot"]
            elif name == "ck_throttle":
                pv = MANIFEST["pivots"]["ThrottlePivot"]
            elif name == "ck_pedal_l":
                pv = MANIFEST["pivots"]["PedalL"]
            elif name == "ck_pedal_r":
                pv = MANIFEST["pivots"]["PedalR"]
            elif name in ("ck_gearhandle", "ck_gearlights"):
                pv = MANIFEST["pivots"]["GearHandle"]
            elif name == "ck_adi_ball":
                c = MANIFEST["pivots"]["ADIBall"]["center"]
                ob.location = (c[0] / 100, -c[1] / 100, c[2] / 100)
                ob.rotation_euler = (0, 0, D2R(180))
            elif name.startswith("ck_needle_"):
                nd = MANIFEST["needles"][name[len("ck_needle_"):]]
                c = nd["center"]
                ob.location = (c[0] / 100, -c[1] / 100, c[2] / 100)
                x = V((nd["x_axis"][0], -nd["x_axis"][1], nd["x_axis"][2]))
                z = V((nd["z_axis"][0], -nd["z_axis"][1], nd["z_axis"][2]))
                y = z.cross(x)
                ob.matrix_world = Matrix.Translation(ob.location) @ Matrix((x, y, z)).transposed().to_4x4()
            if pv:
                ob.location = (pv[0] / 100, -pv[1] / 100, pv[2] / 100)
        preview_render(objs, os.path.join(ART, "preview"))


main()
