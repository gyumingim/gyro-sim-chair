"""Rudder pedals v2 for the gyro sim chair — parallel sliding pedals (MFG Crosswind style) + rocker + cam centring, build123d.

Run:  python pedals.py   -> stl/*.stl, cam DXF, parts.json (BOM, force curve), interference check over the pedal range

Coordinates (mm): x = forward, y = left, z = up. Origin = centre of the plywood base underside.
Each pedal carriage slides along x on its own MGN12H linear rail. Both carriages are tied by M6 rod-end links to a rocker
that turns about a vertical shaft at (XR, 0): left pedal forward = right pedal back. Rocker shaft carries the same cam +
2 roller levers + 1 tension spring centring module as the stick (ctl_lib.py), an RC-car oil shock (spring removed) gives
viscous damping (no stiction), AS5600 at the top shaft end. Toe brakes: each pedal plate hinges at the heel on its
carriage and tips forward up to BRK deg against a compression spring, AS5600 on each hinge. Reach: the whole base slides
on two 2020 profiles on the cage floor, index pin every 25 mm, +-100 mm (rider 160-190 cm).
"""
import math, os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from build123d import Axis, Plane, Pos, Rot, Box, Cylinder
from ctl_lib import (box, cx, cy, cz, tube, bearing, cam_points, cam_solid, write_dxf, circle_pts, roller_centre_dist,
                     cam_torque_curve, export_parts, check_pairs)

HERE = os.path.dirname(os.path.abspath(__file__))
PLY = 18                      # plywood base thickness
PY = 115                      # pedal centre |y| (= rocker arm length, links run along x)
TRAVEL = 40                   # pedal travel +-mm along x (F/A-18 +-1 in, mechanical trainers more; 추정 sim middle ground)
PHI = math.degrees(math.asin(TRAVEL / PY))   # rocker angle at full travel
XR = 175                      # rocker shaft x
RAIL_Z = PLY                  # MGN12 rail bottom
CAR_Z = PLY + 13              # MGN12H carriage top
HX, HZ = -45, CAR_Z + 20      # toe-brake hinge (heel) axis, x / z (along y)
LEAN = 65                     # pedal plate angle from horizontal at rest
BRK = 15                      # toe brake travel deg
CAM = dict(r0=34, a=22, c=math.radians(3.0), dmax=math.radians(32), r_hub=24, z0=PLY + 12, t=8)
LEVZ = (CAM["z0"] + CAM["t"] + 2, CAM["z0"] + CAM["t"] + 9)   # lever plates above the cam
PIVY, SPRY = -30, 32
SPRING = dict(k=4.0, pre=6.0)
ARMZ = (PLY + 46, PLY + 54)   # rocker bar z
TOPZ = PLY + 64               # top bridge bottom

parts = {}
def part(name, shape, group, kind="print", note="", material="PLA", orient="", fill=0.55):
    parts[name] = dict(shape=shape, group=group, kind=kind, note=note, material=material, orient=orient, fill=fill)

# ---------------- base ----------------
part("plywood", box(-150, 300, -200, 200, 0, PLY) - cz(XR, 0, -1, PLY + 1, 30), "fixed", kind="buy", material="plywood",
     note="자작나무 합판 18 t, 450×400 (재단 주문). 아래에 2020 프로파일 2 줄 레일 클램프")
for s in (1, -1):
    part(f"rail_{'L' if s > 0 else 'R'}", box(-110, 110, s * PY - 6, s * PY + 6, RAIL_Z, RAIL_Z + 8), "fixed", kind="buy", material="steel",
         note="MGN12 리니어 레일 220 mm")
    for x in (-(20 + TRAVEL + 6), 20 + TRAVEL + 6):
        st = box(x - 6, x + 6, s * PY - 14, s * PY + 14, PLY, PLY + 11) - box(x - 7, x + 7, s * PY - 6.5, s * PY + 6.5, PLY - 1, RAIL_Z + 8.5)
        st -= cx(s * PY, PLY + 8, x - 7, x + 7, 3.4)
        part(f"stop_{'L' if s > 0 else 'R'}{'f' if x > 0 else 'b'}", st, "fixed", note="레일 위 멈춤 (캐리지 블록이 닿음, 고무 2 mm 붙임) = 페달 ±40 mm", fill=1.0)
cam_pts = cam_points([0, math.pi], CAM["r0"], CAM["a"], CAM["c"], CAM["dmax"], CAM["r_hub"])
RX = roller_centre_dist(cam_pts, 0, 11)
# rocker tower: bottom plate (bearing + lever pivot posts), 4 pillars, top bridge (bearing)
tb = box(XR - 70, XR + 70, -70, 70, PLY, PLY + 8)
tb -= cz(XR, 0, PLY + 1, PLY + 9, 22.2); tb -= cz(XR, 0, PLY - 1, PLY + 9, 10)
for sx in (1, -1):
    tb += cz(XR + sx * RX, PIVY, PLY + 8, LEVZ[0] - 0.5, 12)
    tb -= cz(XR + sx * RX, PIVY, PLY + 2, LEVZ[0], 5.0)
for sx in (1, -1):
    for sy in (1, -1):
        tb += cz(XR + sx * 60, sy * 60, PLY + 8, TOPZ, 16)
        tb -= cz(XR + sx * 60, sy * 60, PLY - 1, TOPZ + 1, 5.5)
for (x, y) in ((XR - 62, 0), (XR + 62, 0), (XR, -62)):
    tb -= cz(x, y, PLY - 1, PLY + 9, 4.5)
part("tower_base", tb, "fixed", material="PETG", note="러더 축 받침 (아래 608 + 레버 축 기둥 + 기둥 4)", orient="바닥을 바닥에, 채움 60 %", fill=0.65)
top = box(XR - 70, XR + 70, -70, 70, TOPZ, TOPZ + 8) - cz(XR, 0, TOPZ - 1, TOPZ + 9, 10) - cz(XR, 0, TOPZ + 1, TOPZ + 9, 22.2)
for sx in (1, -1):
    for sy in (1, -1):
        top -= cz(XR + sx * 60, sy * 60, TOPZ - 1, TOPZ + 9, 5.5)
top -= box(XR - 40, XR + 40, 25, 71, TOPZ - 1, TOPZ + 9)        # spring / preload access
part("tower_top", top, "fixed", material="PETG", note="러더 축 윗판 (위 608), M5 긴 볼트 4 개로 기둥과 같이 조임", orient="그대로", fill=0.6)
part("bearing_rock_lo", bearing("z", (XR, 0), PLY + 1, PLY + 8), "fixed", kind="buy", material="steel", note="608-2RS")
part("bearing_rock_hi", bearing("z", (XR, 0), TOPZ + 1, TOPZ + 8), "fixed", kind="buy", material="steel", note="608-2RS")
# centring levers (fixed group, pivot on the posts)
for sx, nm in ((1, "F"), (-1, "B")):
    x = XR + sx * RX
    lv = box(x - 7, x + 7, PIVY - 8, SPRY + 8, *LEVZ) - cz(x, PIVY, LEVZ[0] - 1, LEVZ[1] + 1, 6.3) - cz(x, 0, LEVZ[0] - 1, LEVZ[1] + 1, 8.2)
    lv -= cz(x, SPRY, LEVZ[0] - 1, LEVZ[1] + 1, 4.5)                       # spring hook
    part(f"lever_{nm}", lv, "fixed", material="PETG", note="센터링 롤러 레버 (지렛대 2:1)", orient="눕혀서, 채움 100 %", fill=1.0)
    part(f"roller_{nm}", bearing("z", (x, 0), CAM["z0"] + 0.5, CAM["z0"] + 7.5), "fixed", kind="buy", material="steel", note="608ZZ 롤러")
part("rock_spring", cx(SPRY, (LEVZ[0] + LEVZ[1]) / 2 + 9, XR - RX + 8, XR + RX - 22, 10), "fixed", kind="buy", material="steel",
     note=f"인장 스프링 (기본 k ≈ {SPRING['k']} N/mm, 추정) — 바꿔 끼워 페달 무게감 조절")
part("rock_eyebolt", cx(SPRY, (LEVZ[0] + LEVZ[1]) / 2 + 9, XR + RX - 24, XR + RX + 14, 5) + cx(SPRY, (LEVZ[0] + LEVZ[1]) / 2 + 9, XR + RX + 7, XR + RX + 13, 14),
     "fixed", kind="buy", material="steel", note="M5 아이볼트 + 손잡이 너트 = 가운데 힘 (예압) 조절")
part("as5600_rudder", box(XR - 11.5, XR + 11.5, -11.5, 11.5, TOPZ + 18.4, TOPZ + 20), "fixed", kind="buy", material="PCB", note="AS5600 (러더)")
sm = box(XR - 20, XR + 20, -20, 20, TOPZ + 20, TOPZ + 23) + box(XR - 20, XR - 14, -20, 20, TOPZ + 8, TOPZ + 23) + box(XR + 14, XR + 20, -20, 20, TOPZ + 8, TOPZ + 23)
part("sensor_mount_rudder", sm, "fixed", note="러더 AS5600 받침 (윗판 위)")
# damper anchor (RC oil shock from the rocker bar to the base)
da = box(XR + 96, XR + 116, 28, 52, PLY, ARMZ[1] + 4) - cx(40, (ARMZ[0] + ARMZ[1]) / 2, XR + 95, XR + 117, 3.4)
part("damper_anchor", da, "fixed", note="오일 댐퍼 아래 고정점", fill=1.0)

# ---------------- rocker group (turns about z at (XR, 0)) ----------------
plane_c = Plane(origin=(XR, 0, CAM["z0"]), x_dir=(1, 0, 0), z_dir=(0, 0, 1))
part("cam_rudder", cam_solid(plane_c, cam_pts, CAM["t"], bolts=[(0, 14, 3.4), (0, -14, 3.4)]), "rocker", kind="cut", material="AL6061",
     note="러더 캠: 알루미늄 8 t 레이저 절단 (cam_rudder.dxf)")
part("rock_shaft", cz(XR, 0, PLY - 2, TOPZ + 15, 8), "rocker", kind="buy", material="steel", note="Ø8 h6 연마봉 100 mm, D컷")
part("rock_hub", cz(XR, 0, ARMZ[0] - 6, ARMZ[1] + 6, 40) - cz(XR, 0, ARMZ[0] - 7, ARMZ[1] + 7, 8.1) - box(XR - 16, XR + 16, -21, 21, ARMZ[0], ARMZ[1]),
     "rocker", material="PETG", note="러더 바 허브 (알루미늄 바를 위아래로 물고 M4 ×4, 축은 D컷 + 무두볼트)", fill=1.0)
bar = box(XR - 15, XR + 15, -PY - 14, PY + 14, *ARMZ)
for s in (1, -1):
    bar -= cz(XR, s * PY, ARMZ[0] - 1, ARMZ[1] + 1, 6.5)
    bar -= cz(XR, s * 88, ARMZ[0] - 1, ARMZ[1] + 1, 3.4)
bar -= cz(XR, 40, ARMZ[0] - 1, ARMZ[1] + 1, 3.4)                    # damper eye
bar -= cz(XR, 0, ARMZ[0] - 1, ARMZ[1] + 1, 8.2)
part("rock_bar", bar, "rocker", kind="buy", material="AL6061", note=f"알루미늄 평철 30×8, {2 * PY + 28} mm (러더 바), 끝 M6 구멍 = 연결봉")
part("magnet_rudder", cz(XR, 0, TOPZ + 15, TOPZ + 18, 8), "rocker", kind="buy", material="NdFeB", note="자석 Ø6×2.5 직경 방향 (축 위 끝)")

# ---------------- pedal carriages (slide along x) + plates (toe brake) ----------------
HORN = 45
def plate_shape(s):
    """pedal plate: hinge axis along y at (HX, HZ); plate leans LEAN deg from horizontal toward +x; brake horn behind the hinge."""
    y = s * PY
    t = math.radians(LEAN)
    L, W = 230, 100
    u = (math.cos(t), math.sin(t))          # up the plate (x, z)
    n = (math.sin(t), -math.cos(t))         # behind the plate
    c = (HX + u[0] * L / 2, HZ + u[1] * L / 2)
    p = Pos(c[0], y, c[1]) * Rot(0, -LEAN, 0) * Box(L, W, 8)
    for dy in (-30, 30):
        p += Pos(c[0] + n[0] * 8, y + dy, c[1] + n[1] * 8) * Rot(0, -LEAN, 0) * Box(L - 30, 6, 12)   # ribs behind
    p += Pos(HX + u[0] * (L - 8) - n[0] * 14, y, HZ + u[1] * (L - 8) - n[1] * 14) * Rot(0, -LEAN, 0) * Box(16, W, 22)   # toe lip
    p -= box(HX - 30, HX + 30, y - 51, y - 37, HZ - 20, HZ + 40); p -= box(HX - 30, HX + 30, y + 37, y + 51, HZ - 20, HZ + 40)   # room for the ears
    p += cy(HX, HZ, y - 36, y + 36, 18)                                                    # hinge barrel
    p += box(HX - HORN, HX, y - 10, y + 10, HZ - 6, HZ + 6)                                # brake horn (rises when the toes push)
    p -= cy(HX, HZ, y - 52, y + 52, 8.2)
    return p
for s, nm in ((1, "L"), (-1, "R")):
    y = s * PY
    part(f"carriage_blk_{nm}", box(-20, 20, y - 13.5, y + 13.5, CAR_Z - 10, CAR_Z), f"car{nm}", kind="buy", material="steel", note="MGN12H 캐리지")
    cb = box(-HORN - 70, 55, y - 30, y + 30, CAR_Z, CAR_Z + 10)
    for dy in (-43, 43):
        cb += box(HX - 12, HX + 12, y + dy - 4, y + dy + 4, CAR_Z, HZ + 12) - cy(HX, HZ, y + dy - 5, y + dy + 5, 8.2)   # hinge ears (bushings)
    cb += box(40, 55, y - 9, y + 9, CAR_Z, ARMZ[1] + 4)                                     # link ear (front)
    cb -= cx(y, (ARMZ[0] + ARMZ[1]) / 2, 39, 56, 6.5)
    bx = HX - HORN + 8
    cb += box(bx - 26, bx - 12, y - 16, y + 16, CAR_Z, HZ + 36) + box(bx - 26, bx + 12, y - 16, y + 16, HZ + 28, HZ + 36)   # brake spring bridge
    cb -= cz(bx, y, HZ + 27, HZ + 37, 5.0)                                                  # M6: brake preload screw
    for x in (-10, 10):
        for dy in (-10, 10):
            cb -= cz(x, y + dy, CAR_Z - 1, CAR_Z + 11, 3.4)
    part(f"carriage_{nm}", cb, f"car{nm}", material="PETG", note="페달 캐리지 (MGN12H 위, M3 ×4): 가운데 = 발뒤꿈치 경첩 귀, 앞 = 연결봉 귀, 뒤 = 브레이크 스프링 다리", orient="바닥을 바닥에, 채움 60 %", fill=0.65)
    part(f"pedal_{nm}", plate_shape(s), f"brk{nm}", material="PETG", note="페달 판 230×100 (뒤 갈비 2, 발끝 턱). 발끝으로 누르면 경첩을 중심으로 앞으로 15° = 토 브레이크", orient="뒷면 (갈비) 을 위로", fill=0.5)
    part(f"hinge_pin_{nm}", cy(HX, HZ, y - 54, y + 54, 8), f"brk{nm}", kind="buy", material="steel", note="Ø8 h6 핀 108 mm (페달에 고정, 귀의 부싱에서 돎, 끝에 자석)")
    part(f"brake_spring_{nm}", cz(HX - HORN + 8, y, HZ + 6, HZ + 27, 14), f"car{nm}", kind="buy", material="steel", note="토 브레이크 압축 스프링 OD 14 × 25 (k ≈ 10 N/mm, 추정): 뿔을 위에서 누름, M6 나사로 예압")
    so = s * (PY + 58)
    part(f"as5600_brake_{nm}", box(HX - 11.5, HX + 11.5, so - 0.8, so + 0.8, HZ - 11.5, HZ + 11.5), f"car{nm}", kind="buy", material="PCB", note=f"AS5600 (토 브레이크 {'왼' if s > 0 else '오른'})")
    smb = box(HX - 14, HX + 14, so + s * 0.8, so + s * 3.8, HZ - 14, HZ + 14) + box(HX - 14, HX + 14, min(y + s * 31, so), max(y + s * 31, so), CAR_Z, CAR_Z + 5)
    part(f"sensor_mount_{nm}", smb, f"car{nm}", note="브레이크 AS5600 받침 (경첩 바깥 끝)")

def link_shape(s, phi):
    y = s * PY
    d = car_dx(s, phi)
    p0 = (47.5 + d, y, (ARMZ[0] + ARMZ[1]) / 2)
    ph = math.radians(phi)
    p1 = (XR - s * PY * math.sin(ph), s * PY * math.cos(ph), (ARMZ[0] + ARMZ[1]) / 2 + 12)
    L = math.dist(p0, p1)
    mid = [(p0[i] + p1[i]) / 2 for i in range(3)]
    ang = math.degrees(math.atan2(p1[2] - p0[2], p1[0] - p0[0]))
    yaw = math.degrees(math.atan2(p1[1] - p0[1], p1[0] - p0[0]))
    return Pos(*mid) * Rot(0, 0, yaw) * Rot(0, -ang, 0) * Rot(0, 90, 0) * Cylinder(3, L - 24)
def car_dx(s, phi):
    ph = math.radians(phi)
    return -s * PY * math.sin(ph)                     # rocker +phi: left (+y) end moves back
for s, nm in ((1, "L"), (-1, "R")):
    part(f"link_{nm}", link_shape(s, 0), "link", kind="buy", material="steel", note="연결봉: M6 나사봉 + 로드엔드 2 (길이 조절 = 페달 가운데 맞춤)")
part("damper", cx(40, (ARMZ[0] + ARMZ[1]) / 2, XR + 12, XR + 104, 14), "link", kind="buy", material="alu",
     note="RC 카 오일 쇼크 (1/8 버기, 스프링 뺌) = 점성 댐퍼. 오일 점도로 조절 (스틱션 없음)")

def posed(name, phi, bl=0, br=0):
    s = parts[name]["shape"]; g = parts[name]["group"]
    if g == "rocker" and phi: s = s.rotate(Axis((XR, 0, 0), (0, 0, 1)), phi)
    if g == "link":
        if name.startswith("link_"):
            return link_shape(1 if name.endswith("L") else -1, phi)
        return s
    for side, sg, b in (("L", 1, bl), ("R", -1, br)):
        if g == f"brk{side}" and b: s = s.rotate(Axis((HX, 0, HZ), (0, 1, 0)), b)       # toes push forward (+ about y = top to +x)
        if g in (f"car{side}", f"brk{side}"): s = Pos(car_dx(sg, phi), 0, 0) * s
    return s

MATES = [("rock_shaft", "cam_rudder"), ("rock_shaft", "rock_hub"), ("rock_shaft", "rock_bar"), ("rock_shaft", "bearing_rock_lo"), ("rock_shaft", "bearing_rock_hi"),
         ("bearing_rock_lo", "tower_base"), ("bearing_rock_hi", "tower_top"), ("rock_shaft", "tower_base"), ("rock_shaft", "tower_top"), ("rock_hub", "rock_bar"),
         ("rock_shaft", "magnet_rudder"), ("rock_shaft", "plywood"), ("tower_base", "plywood"), ("rock_spring", "rock_eyebolt"), ("tower_top", "sensor_mount_rudder"),
         ("damper", "damper_anchor"), ("damper", "rock_bar")]
for nm in ("F", "B"):
    MATES += [(f"roller_{nm}", f"lever_{nm}"), (f"roller_{nm}", "cam_rudder"), (f"lever_{nm}", "tower_base"), ("rock_spring", f"lever_{nm}"), ("rock_eyebolt", f"lever_{nm}")]
for nm in ("L", "R"):
    MATES += [(f"carriage_blk_{nm}", f"rail_{nm}"), (f"carriage_blk_{nm}", f"carriage_{nm}"), (f"hinge_pin_{nm}", f"carriage_{nm}"), (f"hinge_pin_{nm}", f"pedal_{nm}"),
              (f"brake_spring_{nm}", f"carriage_{nm}"), (f"brake_spring_{nm}", f"pedal_{nm}"), (f"link_{nm}", f"carriage_{nm}"), (f"link_{nm}", "rock_bar"),
              (f"sensor_mount_{nm}", f"carriage_{nm}"), (f"as5600_brake_{nm}", f"sensor_mount_{nm}"), (f"rail_{nm}", "plywood")]
    for e in ("f", "b"):
        MATES += [(f"stop_{nm}{e}", f"rail_{nm}"), (f"stop_{nm}{e}", "plywood")]
ALLOW = {frozenset(p) for p in MATES}

def forces():
    angs = [round(PHI * i / 20, 2) for i in range(21)]
    var = {}
    for nm, kf, pf in (("light", 0.5, 0.5), ("default", 1, 1), ("heavy", 2, 1.5)):
        t, _ = cam_torque_curve(cam_pts, [0, math.pi], 11, SPRING["k"] * kf, SPRING["pre"] * pf, (SPRY - PIVY) / (-PIVY), angs)
        var[nm] = dict(k=SPRING["k"] * kf, pedal_N=[round(tt / (PY * math.cos(math.radians(a))), 1) for tt, a in zip(t, angs)])
    return dict(variants=var, travel_mm=[round(PY * math.sin(math.radians(a)), 1) for a in angs], rocker_deg=angs,
                note="한쪽 페달에서 필요한 힘 N (연결봉 · 레일 마찰 · 댐퍼 제외, 추정)")

if __name__ == "__main__":
    write_dxf(os.path.join(HERE, "cam_rudder.dxf"), [cam_pts, circle_pts(0, 0, 8.2), circle_pts(0, 14, 3.4), circle_pts(0, -14, 3.4)])
    poses = [(0, 0, 0), (PHI, 0, 0), (-PHI, 0, 0), (0, BRK, BRK), (PHI, BRK, BRK), (-PHI, BRK, BRK)]
    res = check_pairs(parts, posed, poses, ALLOW)
    f = forces()
    info = export_parts(parts, HERE, dict(travel_mm=TRAVEL, rocker_deg=round(PHI, 2), pedal_y=PY, rocker_x=XR, hinge=[HX, HZ], lean_deg=LEAN, brake_deg=BRK,
                                          roller_x=round(RX, 2), spring=SPRING, reach_adjust_mm=100, printer=[240, 240, 240]),
                        extra=dict(forces=f, check=[dict(pose=p, hits=b) for p, b in res]))
    for i in info: print(f"{i['name']:20s} {i['group']:6s} {i['kind']:5s} {i['size']} {i['grams'] or ''}")
    for p, b in res: print("pose", p, b if b else "none")
    print("PHI", round(PHI, 1), "RX", round(RX, 1), "pedal N", f["variants"]["default"]["pedal_N"][::5])
