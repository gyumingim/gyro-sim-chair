"""Adapter: public pedal models on our brakes v4 toe-brake pedals (all PLA) — build123d.

Run:  python pedal_overlay_adapter.py   -> stl_overlay_adapter/*.stl + parts.json (our parts + placement matrices of the public parts)

The pedal *look* comes from public models that are NOT in this repo (both CC BY-NC-SA -> local use only, never committed):
  cadet (default): "CadetPedals" by Vince_Prints, https://www.thingiverse.com/thing:4655002
      L_Pedal.stl (hex-lattice plate + ribbed tube, 167 x 120 x 90) -> toe brake plate, bolted on our toe_plate
        (right pedal = L_Pedal mirrored, so both sides use one placement rule)
      F_Platform.stl + F_F_Grip.stl (100 x 100 plate + grip strip), turned grip-up -> heel pad, bolted on our pedal_base
      Frame as downloaded: tube axis = y at x = z = 0, plate along +x, foot side +z, plate centre y = -11, flat back face z = -22.
  a320 (toggle): "Airbus A320 Rudder Pedals" by Mark Ayton [MANTOGA], https://www.printables.com/model/511723
      RudderPedalsBottom.stl -> heel shell, RudderPedalsTop.stl -> toe shell. Frame: x across, y along (joint y = 0), +z foot side.

Our parts (per side), nothing in v3 / brakes v4 changes:
  * riser_heel_<mode> : 14 mm spacer on the pedal_base foot face (clears the carriage hinge ears, n -16 at s 6, and the Ø18 heel boss).
  * riser_toe_<mode>  : spacer on the toe_plate foot face (cadet 7 mm: clears the AS5600 cap, n -9; a320 14 mm).
  * toe_plate_ovl     : brakes v4 toe plate WITHOUT the toe lip (the public toe part replaces it) + 4 M3 inserts.
  Fastening: M3 countersunk screws from the foot side through the public part (drill Ø3.4) and the riser into inserts in our plate.
Why the joint gap: our toe hinge (s = S_T, n = 3) lies 13..35 mm behind the public parts, so the toe part swings ~0.3 x that
toward the heel when it lifts 18 deg. The heel part must end that much lower -> a gap of ~13-16 mm shows when the brake is pressed.
Only a hinge on the foot face (e.g. the Cadet tube as the hinge) removes it - that is a brakes v4 change, not done here.
"""
import json, math, os, sys
from datetime import datetime
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import brakes_v4 as B                                     # also imports pedals.py (v3)
from build123d import Plane, mirror, export_stl
from ctl_lib import auto_fill

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "stl_overlay_adapter")
S_T, L, PY, BT = B.S_T, B.L, B.PY, B.BT
MODES = {
    # placement in plate coords (s up the plate from the heel pin, n behind the plate; our foot face = n -3)
    "cadet": dict(r_heel=14.0, r_toe=7.0, s_axis=S_T + 10, n_axis=-3 - 7.0 - 22, s_pad=55.0,      # pad s 5..105: 2.3 mm to the tube at rest (measured)
                  heel_riser=(14, 100), toe_riser=(S_T + 8, S_T + 85), src="thingiverse.com/thing:4655002 CadetPedals by Vince_Prints (CC BY-NC-SA)"),
    "a320": dict(r_heel=14.0, r_toe=14.0, gap=16.5, heel_riser=(12, S_T - 16.5 - 6), toe_riser=(S_T + 8, L - 2),
                 src="printables.com/model/511723 A320 pedals by MANTOGA (CC BY-NC-SA)"),
}
HEEL_SCREWS = [(20, 40), (20, -40), (80, 0)]
TOE_SCREWS = [(150, 32), (150, -32), (200, 32), (200, -32)]

def heel_riser_left(m):
    y, nb = PY, -3 - m["r_heel"]; s0, s1 = m["heel_riser"]
    r = B.pbox(s0, s1, nb, -3, y - 45, y + 45)
    r -= B.pbox(s0 + 15, s1 - 15, nb - 1, -2, y - 23, y + 23)                   # window (mass)
    for s_, dy in HEEL_SCREWS:
        if s0 + 4 < s_ < s1 - 4: r -= B.pcyl_n(s_, y + dy, nb - 1, -2, 3.4)
    return r

def toe_riser_left(m):
    y, nb = PY, -3 - m["r_toe"]; s0, s1 = m["toe_riser"]
    r = B.pbox(s0, s1, nb, -3, y - 40, y + 40)
    r -= B.pbox(s0 + 22, s0 + 47, nb - 1, -2, y - 22, y + 22)                  # window (mass), clear of the spring pocket
    for s_, dy in TOE_SCREWS:
        if s0 + 4 < s_ < s1 - 4: r -= B.pcyl_n(s_, y + dy, nb - 1, -2, 3.4)
    return r.rotate(B.Axis((B.AX[0], 0, B.AX[1]), (0, 1, 0)), -BT)             # at rest, like the brakes v4 toe parts

def toe_plate_ovl_left():
    t = B.toe_left(rest=False)
    t -= B.pbox(L - 12, L + 1, -16, -3.0, PY - B.TW2 - 1, PY + B.TW2 + 1)      # no toe lip
    for s_, dy in TOE_SCREWS:
        t -= B.pcyl_n(s_, PY + dy, -3.1, 2.5, 4.0)                            # M3 insert Ø4 x 5.5
    return t.rotate(B.Axis((B.AX[0], 0, B.AX[1]), (0, 1, 0)), -BT)

def plate_matrix(cols, origin, toe):
    """Source part coords -> our world (x fwd, y left, z up). cols = images of source x, y, z as plate (ds, dy, dn);
    origin = plate (s, y, n). toe=True -> rest pose (rotated -BT about the toe axis, right hand about world +y)."""
    U, N = B.U, B.N
    w = lambda d: (U[0] * d[0] + N[0] * d[2], d[1], U[1] * d[0] + N[1] * d[2])
    ex, ey, ez = (w(c) for c in cols); o = B.X(origin[0], origin[2])
    M = [[ex[0], ey[0], ez[0], o[0]], [ex[1], ey[1], ez[1], origin[1]], [ex[2], ey[2], ez[2], o[1]], [0, 0, 0, 1]]
    if toe:
        a = math.radians(-BT); c, s_ = math.cos(a), math.sin(a); ax, az = B.AX
        Rm = [[c, 0, s_, ax - c * ax - s_ * az], [0, 1, 0, 0], [-s_, 0, c, az + s_ * ax - c * az], [0, 0, 0, 1]]
        M = [[sum(Rm[i][k] * M[k][j] for k in range(4)) for j in range(4)] for i in range(4)]
    return [[round(v, 6) for v in r] for r in M]

def placements():
    out = {}
    for sg, nm in ((1, "L"), (-1, "R")):
        m = MODES["a320"]
        out[f"a320_heel_{nm}"] = plate_matrix([(0, -1, 0), (1, 0, 0), (0, 0, -1)], (S_T - m["gap"], sg * PY, -3 - m["r_heel"]), False)
        out[f"a320_toe_{nm}"] = plate_matrix([(0, -1, 0), (1, 0, 0), (0, 0, -1)], (S_T, sg * PY, -3 - m["r_toe"]), True)
        m = MODES["cadet"]
        out[f"cadet_pedal_{nm}"] = plate_matrix([(1, 0, 0), (0, sg, 0), (0, 0, -1)], (m["s_axis"], sg * (PY + 11), m["n_axis"]), True)
        # heel pad: F_Platform turned grip-up (file z -50 grip .. -37 back) -> n = 20 + z (back face on the 14 mm riser at n -17)
        out[f"cadet_pad_{nm}"] = plate_matrix([(1, 0, 0), (0, -1, 0), (0, 0, 1)], (m["s_pad"], sg * PY, 20.0), False)
        out[f"cadet_grip2_{nm}"] = plate_matrix([(1, 0, 0), (0, 1, 0), (0, 0, 1)], (m["s_pad"], sg * PY, 20.0), False)  # mirrored 2nd strip
    return out

parts = {}
def part(name, shape, group, kind="print", note="", material="PLA", orient="", fill=0.25):
    if kind == "print": fill = auto_fill(shape, fill)
    parts[name] = dict(shape=shape, group=group, kind=kind, note=note, material=material, orient=orient, fill=fill)

def mirror_y(s): return mirror(s, Plane.XZ)

shapes_L = dict(tp=toe_plate_ovl_left())
for md, m in MODES.items():
    shapes_L["rh_" + md] = heel_riser_left(m); shapes_L["rt_" + md] = toe_riser_left(m)
for sgn, nm in ((1, "L"), (-1, "R")):
    f = (lambda s: s) if sgn > 0 else mirror_y
    for md, m in MODES.items():
        part(f"riser_heel_{md}_{nm}", f(shapes_L["rh_" + md]), f"car{nm}", note=f"[{md}] 뒤꿈치 쪽 받침 {m['r_heel']:.0f} mm (pedal_base 발 면 위)", orient="납작하게", fill=0.3)
        part(f"riser_toe_{md}_{nm}", f(shapes_L["rt_" + md]), f"toe{nm}", note=f"[{md}] 발끝 쪽 받침 {m['r_toe']:.0f} mm (toe_plate 위, M3)", orient="납작하게", fill=0.3)
    part(f"toe_plate_ovl_{nm}", f(shapes_L["tp"]), f"toe{nm}", note="brakes v4 발끝 판에서 발끝 턱만 뺌 + M3 인서트 4 (공개 발끝 부품이 턱 역할)", orient="발 닿는 면을 바닥에", fill=0.3)

if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    for f_ in os.listdir(OUT):
        if f_.endswith(".stl"): os.remove(os.path.join(OUT, f_))
    info = []
    for name, p in parts.items():
        export_stl(p["shape"], os.path.join(OUT, name + ".stl"), tolerance=0.05, angular_tolerance=0.2)
        bb = p["shape"].bounding_box(); vol = p["shape"].volume / 1000
        info.append(dict(name=name, group=p["group"], kind=p["kind"], note=p["note"], material=p["material"],
                         size=[round(bb.size.X, 1), round(bb.size.Y, 1), round(bb.size.Z, 1)], volume_cm3=round(vol, 1),
                         grams=round(vol * 1.24 * p["fill"], 1), orient=p["orient"], file=f"{name}.stl"))
    data = dict(meta=dict(created=datetime.now().isoformat(timespec="seconds"), version="overlay adapter v2 (cadet + a320, on brakes v4)",
                          inputs="brakes_v4.py (S_T, AX, BT, plate frame), pedals.py v3", modes=MODES,
                          toe_axis_xz=[round(B.AX[0], 3), round(B.AX[1], 3)], brake_deg=BT,
                          note="shells: row-major 4x4, public file coords -> world; *_toe_* and cadet_pedal_* at rest (lifted BT); "
                               "rotate about toe_axis (world y) by +b to brake b deg"),
                parts=info, shells=placements())
    json.dump(data, open(os.path.join(OUT, "parts.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    for i in info: print(f"{i['name']:22s} {i['size']} {i['grams']} g")
