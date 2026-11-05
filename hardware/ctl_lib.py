"""Shared helpers for the v2 controls (stick, throttle, pedals): primitives, cam profiles, cam torque model, export.

Units mm, N. Coordinates per device script (x forward, y left, z up).
The centring mechanism used on all three devices (v2):
  cam fixed to the moving axis  +  two roller followers (608 bearings) on two levers  +  ONE tension spring across the
  lever tips (the same spring pulls both rollers into the cam, so both sides always get the same force and the radial
  forces on the axis cancel). Preload = eye bolt + knurled nut on one spring end. Cam profile = rounded V
  r = r0 + a * (sqrt(d^2 + c^2) - c) around each follower: no notch, a crisp centre (width set by c), then a steady
  gradient. Same idea as VKB / Virpil cam + roller bases (see docs/controls-v2 research notes).
"""
import json, math, os
from datetime import datetime
from build123d import Box, Cylinder, Pos, Rot, Axis, Plane, Polyline, make_face, extrude, export_stl

PLA, PETG = 1.24, 1.27


def box(x0, x1, y0, y1, z0, z1):
    x0, x1 = sorted((x0, x1)); y0, y1 = sorted((y0, y1)); z0, z1 = sorted((z0, z1))
    return Pos((x0 + x1) / 2, (y0 + y1) / 2, (z0 + z1) / 2) * Box(x1 - x0, y1 - y0, z1 - z0)
def cx(y, z, x0, x1, d): return Pos((x0 + x1) / 2, y, z) * Rot(0, 90, 0) * Cylinder(d / 2, abs(x1 - x0))
def cy(x, z, y0, y1, d): return Pos(x, (y0 + y1) / 2, z) * Rot(90, 0, 0) * Cylinder(d / 2, abs(y1 - y0))
def cz(x, y, z0, z1, d): return Pos(x, y, (z0 + z1) / 2) * Cylinder(d / 2, abs(z1 - z0))
def tube(axis, c, a0, a1, d, di):
    f = {"x": cx, "y": cy, "z": cz}[axis]
    return f(*c, a0, a1, d) - f(*c, a0 - 1, a1 + 1, di)
def ring(axis, c, a0, a1, d, di): return tube(axis, c, a0, a1, d, di)


def bearing(axis, c, a0, a1):          # 608ZZ placeholder 22/8 x 7
    return tube(axis, c, a0, a1, 22, 8)


def cam_r(theta, followers, r0, a, c, dmax, r_hub):
    """cam radius at polar angle theta (rad). followers = list of follower angles (rad, cam frame at centre)."""
    d = min(abs((theta - f + math.pi) % (2 * math.pi) - math.pi) for f in followers)
    if d <= dmax:
        return r0 + a * (math.sqrt(d * d + c * c) - c)
    r_top = r0 + a * (math.sqrt(dmax * dmax + c * c) - c)
    t = min(1.0, (d - dmax) / math.radians(10))             # 10 deg ramp down to the hub radius
    return r_top + (r_hub - r_top) * (0.5 - 0.5 * math.cos(math.pi * t))


def cam_points(followers, r0, a, c, dmax, r_hub, n=720):
    pts = []
    for i in range(n):
        th = 2 * math.pi * i / n
        r = cam_r(th, followers, r0, a, c, dmax, r_hub)
        pts.append((r * math.cos(th), r * math.sin(th)))
    return pts


def cam_solid(plane, pts, thick, bore=8.2, bolts=()):
    """plane: build123d Plane whose local xy is the cam plane; extrudes +thick along its normal."""
    f = make_face(Polyline(*pts, close=True))
    s = extrude(plane * f, amount=thick)
    s -= extrude(plane * make_face(Polyline(*[(bore / 2 * math.cos(t), bore / 2 * math.sin(t)) for t in [i * math.pi / 24 for i in range(48)]], close=True)), amount=thick)
    for (u, v, d) in bolts:
        s -= extrude(plane * make_face(Polyline(*[(u + d / 2 * math.cos(t), v + d / 2 * math.sin(t)) for t in [i * math.pi / 12 for i in range(24)]], close=True)), amount=thick)
    return s


def write_dxf(path, loops):
    """Minimal R12 DXF with closed polylines (mm). loops = list of point lists."""
    L = ["0", "SECTION", "2", "ENTITIES"]
    for pts in loops:
        L += ["0", "POLYLINE", "8", "CUT", "66", "1", "70", "1"]
        for (x, y) in pts:
            L += ["0", "VERTEX", "8", "CUT", "10", f"{x:.3f}", "20", f"{y:.3f}"]
        L += ["0", "SEQEND"]
    L += ["0", "ENDSEC", "0", "EOF"]
    open(path, "w").write("\n".join(L))


def circle_pts(u, v, d, n=48):
    return [(u + d / 2 * math.cos(2 * math.pi * i / n), v + d / 2 * math.sin(2 * math.pi * i / n)) for i in range(n)]


def roller_centre_dist(pts, phi, R):
    """distance from the axis to the centre of a roller (radius R) touching the cam, roller on the radial line at
    angle phi in the cam frame (exact for a radial follower: max over the cam boundary of the contact condition)."""
    best = 0.0
    cp, sp = math.cos(phi), math.sin(phi)
    for (x, y) in pts:
        along = x * cp + y * sp
        perp = -x * sp + y * cp
        if abs(perp) < R:
            best = max(best, along + math.sqrt(R * R - perp * perp))
    return best


def cam_torque_curve(pts, followers, R, k, pre, ratio, angles_deg):
    """Torque (N*mm) vs axis angle for 2 radial roller followers on levers (lever ratio = spring arm / roller arm)
    and ONE tension spring (rate k N/mm, preload pre mm) across the lever tips. Each lever tip moves ratio x roller
    lift, both tips separate -> spring stretch = ratio x (lift1 + lift2). Energy method, central differences."""
    d0 = [roller_centre_dist(pts, f, R) for f in followers]
    def U(th):
        lift = sum(roller_centre_dist(pts, f - th, R) - d for f, d in zip(followers, d0))
        x = pre + ratio * lift
        return 0.5 * k * x * x
    out = []
    h = math.radians(0.25)
    for a in angles_deg:
        t = math.radians(a)
        out.append((U(t + h) - U(t - h)) / (2 * h))
    return out, d0


def export_parts(parts, here, meta, extra=None):
    out = os.path.join(here, "stl"); os.makedirs(out, exist_ok=True)
    for f in os.listdir(out):
        if f.endswith(".stl"): os.remove(os.path.join(out, f))
    info = []
    for name, p in parts.items():
        export_stl(p["shape"], os.path.join(out, name + ".stl"), tolerance=0.05, angular_tolerance=0.2)
        bb = p["shape"].bounding_box(); vol = p["shape"].volume / 1000
        dens = {"PLA": PLA, "PETG": PETG, "TPU": 1.21}.get(p["material"], PLA)
        grams = round(vol * dens * p.get("fill", 0.55), 1) if p["kind"] == "print" else None
        info.append(dict(name=name, group=p["group"], kind=p["kind"], note=p["note"], material=p["material"],
                         size=[round(bb.size.X, 1), round(bb.size.Y, 1), round(bb.size.Z, 1)], volume_cm3=round(vol, 1),
                         grams=grams, orient=p.get("orient", ""), file=f"stl/{name}.stl"))
    data = dict(meta=dict(created=datetime.now().isoformat(timespec="seconds"), **meta), parts=info)
    if extra: data.update(extra)
    json.dump(data, open(os.path.join(here, "parts.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    return info


def check_pairs(parts, posed, poses, allow, groups_moving=None):
    import itertools
    res = []
    names = list(parts)
    for pose in poses:
        shapes = {n: posed(n, *pose) for n in names}
        bad = []
        for a, b in itertools.combinations(names, 2):
            if frozenset((a, b)) in allow: continue
            if groups_moving and parts[a]["group"] == parts[b]["group"]: continue
            A, B = shapes[a], shapes[b]
            ba, bb = A.bounding_box(), B.bounding_box()
            if (ba.min.X > bb.max.X or bb.min.X > ba.max.X or ba.min.Y > bb.max.Y or bb.min.Y > ba.max.Y
                    or ba.min.Z > bb.max.Z or bb.min.Z > ba.max.Z):
                continue
            try: v = (A & B).volume
            except Exception: v = 0
            if v > 0.5: bad.append(f"{a}x{b} {v:.0f}")
        res.append((pose, bad))
    return res


# ---------------- v3 strength helpers (all-PLA controls; every value here is an estimate = 추정) ----------------
# Printed PLA (0.4 nozzle, 0.2 layers, 3-4 perimeters): in-layer tensile ~50 MPa, across layers (interlayer) ~20 MPa
# (conservative; well-tuned prints reach 25-35), compressive ~60 MPa, E ~3.5 GPa, nu 0.36.
# Sustained (creep) guideline used here: keep long-term stress in a printed PLA part below ~10 MPa at room temperature,
# and below ~5 MPa if the room / car can exceed 35-40 C (PLA softens from ~55 C). Rule of thumb, not a datasheet value.
PLA_MECH = dict(xy=50.0, z=20.0, comp=60.0, E=3500.0, nu=0.36, creep=10.0, creep_hot=5.0)
C0_608, C0_6000 = 1370.0, 2360.0          # static load rating N (NSK / SKF catalogue values, 608 / 6000)


def hertz_line(F, L, R1, R2=float("inf"), E1=PLA_MECH["E"], nu1=PLA_MECH["nu"], E2=200000.0, nu2=0.3):
    """peak contact pressure (MPa) for a cylinder (roller R1) on a cylinder/flat (R2, inf = flat), line length L."""
    Es = 1.0 / ((1 - nu1 ** 2) / E1 + (1 - nu2 ** 2) / E2)
    Rs = 1.0 / (1.0 / R1 + (0 if R2 == float("inf") else 1.0 / R2))
    return math.sqrt(F * Es / (math.pi * L * Rs))


def sf(name, load, limit, unit="MPa", note=""):
    return dict(name=name, load=round(load, 2), limit=round(limit, 1), unit=unit, sf=round(limit / max(load, 1e-9), 2), note=note)


def auto_fill(shape, infill=0.2, shell=1.2):
    """mass fraction of a printed part: shell (perimeters + top/bottom, ~1.2 mm from every surface) solid + infill inside."""
    V = shape.volume; A = shape.area
    sh = min(V, A * shell)
    return round((sh + infill * (V - sh)) / V, 3)


def shim_pressure(F, b, t, Es=193000.0, Ef=PLA_MECH["E"]):
    """steel strip (thickness t, width b) glued on a PLA cam, point load F from the roller: beam on elastic foundation
    (foundation modulus ~ Ef). Returns (peak PLA pressure MPa, strip bending stress MPa). 추정."""
    I = b * t ** 3 / 12
    beta = (Ef / (4 * Es * I)) ** 0.25
    return F * beta / (2 * b), (F / (4 * beta)) / (b * t * t / 6)
