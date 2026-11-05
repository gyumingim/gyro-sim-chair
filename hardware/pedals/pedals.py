"""Rudder pedals v3 (cheap, all printed PLA) for the gyro sim chair — parallel sliding pedals on Ø12 rods + LM12UU, rocker +
cam centring + adjustable felt friction, build123d.

Run:  python pedals.py   -> stl/*.stl, cam DXF (optional metal cam), parts.json (BOM, force curve, strength), interference check

v3 (2026-11-05) vs v2: no MGN12 rails (36k), no plywood, no 2020 rails, no oil damper, no aluminium cam. Every printed part PLA.
  * each pedal carriage slides on 2 Ø12 h6 rods with 4 LM12UU ball bushings (no stiction, takes the tipping moment of the foot;
    a carriage rolling on 608s on top of a 4040 was rejected: the foot force pitches the carriage and the rear rollers lift).
  * rods are held by a printed front frame (bolted to the rocker tower) and a printed rear block per side. Front frame L / R +
    tower = one rigid front unit; the rods tie it to the rear blocks -> the whole unit slides as one.
  * reach: front frames + rear blocks clamp onto the chair's two 4040 floor rails (y = +-100) with M6 T-nuts + hand knobs, one
    Ø6 index pin into holes every 25 mm in the left rail top (+-100 mm, rider 160-190 cm).
  * travel stops +-40 mm: the bushing housing hits rubber pads on the front frame / rear block (straight load path to the rails).
  * damping: felt pad on a PLA flexure (part of the tower lid) pressed on the rocker hub by an M6 hand screw (0 = free).
  * centring: same cam + 2 roller levers + 1 tension spring as the stick (ctl_lib.py), cam printed PLA (swap: 2 bolts).
  * toe brakes as v2 (heel hinge, compression spring, AS5600) + 2 printed stop posts under the plate ribs at 15 deg (panic load).

Coordinates (mm): x = forward, y = left, z = up. Origin = top face of the 4040 rails, centre between them (x = 0 at the v2 origin).
"""
import math, os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from build123d import Axis, Plane, Pos, Rot, Box, Cylinder
from ctl_lib import (box, cx, cy, cz, tube, bearing, cam_points, cam_solid, write_dxf, circle_pts, roller_centre_dist,
                     cam_torque_curve, export_parts, check_pairs, auto_fill, shim_pressure)

HERE = os.path.dirname(os.path.abspath(__file__))
YR = 100                      # chair 4040 rail centre |y| (rail top = z 0)
PY = 115                      # pedal centre |y| (= rocker arm length, links run along x)
TRAVEL = 40                   # pedal travel +-mm along x
PHI = math.degrees(math.asin(TRAVEL / PY))   # rocker angle at full travel
ROD_Z, ROD_D, ROD_DY = 15, 12, 35            # rods: centre height, Ø, |y - PY|
HOUS = (-110, 60)             # bushing housing x range on the carriage (LM12UU at both ends, centres 140 apart)
LMUU = (21, 30)               # LM12UU OD, length
CAR_Z = 37                    # carriage plate top (plate 29.5..37)
HX, HZ = -45, CAR_Z + 20      # toe-brake hinge (heel) axis, x / z (along y)
LEAN = 65                     # pedal plate angle from horizontal at rest
BRK = 15                      # toe brake travel deg (hard stop = posts)
RIB = 22                      # rib depth behind the pedal plate
PT = 6                        # pedal plate thickness (ribs run from the plate back face to PT/2 + RIB behind its mid plane)
FB = (HOUS[1] + TRAVEL + 2, HOUS[1] + TRAVEL + 22)      # front rod block x range (2 mm rubber pad in front of it)
RB = (HOUS[0] - TRAVEL - 22, HOUS[0] - TRAVEL - 2)      # rear rod block x range
XR = 180                      # rocker shaft x
TW = (XR - 70, XR + 70, 65)   # tower x0, x1, half width (walls 6)
FLOOR = 6                     # tower floor thickness (10 under the bearing boss)
CAM = dict(r0=34, a=22, c=math.radians(3.0), dmax=math.radians(32), r_hub=24, z0=20, t=8)
LEVZ = (CAM["z0"] + CAM["t"] + 2, CAM["z0"] + CAM["t"] + 9)   # lever plates above the cam
PIVY, SPRY = -30, 32
SPRING = dict(k=4.0, pre=6.0)
ARMZ = (54, 62)               # rocker bar z
TOPZ = 70                     # tower lid bottom (lid 10 t)
LINKZ = (ARMZ[0] + ARMZ[1]) / 2
EAR = (64, 78)                # link ear x range on the carriage

parts = {}
def part(name, shape, group, kind="print", note="", material="PLA", orient="", fill=0.2):
    if kind == "print": fill = auto_fill(shape, fill)        # fill given = infill; saved = mass fraction incl. 1.2 mm shell
    parts[name] = dict(shape=shape, group=group, kind=kind, note=note, material=material, orient=orient, fill=fill)
def b6000(c, z0, z1): return tube("z", c, z0, z1, 26, 10)      # 6000ZZ 10 x 26 x 8

# ---------------- chair rails (not printed) ----------------
for s, nm in ((1, "L"), (-1, "R")):
    part(f"rail_{nm}", box(-220, 300, s * YR - 20, s * YR + 20, -40, 0), "fixed", kind="buy", material="alu",
         note="의자 바닥 4040 레일 (y ±100). 페달 받침이 T너트로 물리고 앞뒤 ±100 mm 미끄러짐. 왼쪽 레일 윗면에 Ø6 구멍 25 mm 간격 9 개 (인덱스 핀)")

# ---------------- rocker tower (fixed) ----------------
cam_pts = cam_points([0, math.pi], CAM["r0"], CAM["a"], CAM["c"], CAM["dmax"], CAM["r_hub"])
SHIM = 0.5                    # stainless strip 0.5 x 8 glued on the 4 roller flanks; printed profile 0.5 mm inside
cam_pr = cam_points([0, math.pi], CAM["r0"] - SHIM, CAM["a"], CAM["c"], CAM["dmax"], CAM["r_hub"] - SHIM)
RX = roller_centre_dist(cam_pts, 0, 11)
X0, X1, HW = TW
tw = box(X0, X1, -HW, HW, 0, TOPZ) - box(X0 + 5, X1 - 5, -HW + 4, HW - 4, FLOOR, TOPZ + 1)
tw += cz(XR, 0, FLOOR - 0.5, 10, 40)
tw -= cz(XR, 0, 2, 10.5, 26.2); tw -= cz(XR, 0, -1, 3, 14)              # 6000 pocket from the top, shoulder below
for sx in (1, -1):
    tw -= box(XR + sx * 20, XR + sx * 38, -46, 46, -1, FLOOR + 1)             # floor windows, clear of the bearing, lever posts and columns
    tw -= box(XR - 14, XR + 14, 18, 46, -1, FLOOR + 1); tw -= box(XR - 14, XR + 14, -46, -18, -1, FLOOR + 1)

for sx in (1, -1):
    tw += cz(XR + sx * RX, PIVY, FLOOR - 0.5, LEVZ[0] - 0.5, 12)
    tw -= cz(XR + sx * RX, PIVY, 2, LEVZ[0], 5.0)                            # M6 tap: lever pivots
for sx in (1, -1):
    for sy in (1, -1):
        cxx, cyy = XR + sx * (70 - 12), sy * (HW - 12)
        tw += box(cxx - 6, cxx + 6, cyy - 6, cyy + 6, FLOOR - 0.5, TOPZ)    # corner columns
        tw -= cz(cxx, cyy, TOPZ - 10, TOPZ + 1, 5.6)                         # M4 inserts for the lid
w_ = HW * math.sin(math.radians(PHI + 1.5)) + 15 * math.cos(math.radians(PHI + 1.5)) + 2
for sy in (1, -1):
    tw -= box(XR - w_, XR + w_, sy * (HW - 7), sy * (HW + 1), ARMZ[0] - 2, ARMZ[1] + 2)   # rocker bar slots (no contact)
    for x in (XR - 50, XR + 40):
        for z in (14, 40):
            tw -= cy(x, z, sy * (HW - 7), sy * (HW + 1), 5.5)                  # M5: front frames bolt to the side walls
tw -= cx(0, ARMZ[1] + 4, X0 - 1, X0 + 7, 5.0)                                # M6 tap: friction screw (back wall)
part("tower", tw, "fixed", note="러더 축 상자 (PLA 한 덩어리 = 바닥 + 앞뒤 벽 5 t / 옆벽 4 t): 아래 6000 베어링, 레버 축 기둥, 러더 바 창 (닿지 않음), 옆벽에 앞틀 M5 ×4",
     orient="바닥을 바닥에, 벽 4 줄 + 채움 25 %", fill=0.25)
top = box(X0, X1, -HW, HW, TOPZ, TOPZ + 6) + cz(XR, 0, TOPZ + 5.5, TOPZ + 10, 40)
top = top - cz(XR, 0, TOPZ - 1, TOPZ + 8, 26.2) - cz(XR, 0, TOPZ + 7, TOPZ + 11, 14)
for sx in (1, -1):
    for sy in (1, -1):
        top -= cz(XR + sx * 58, sy * (HW - 12), TOPZ - 1, TOPZ + 11, 4.5)
top -= box(XR - 40, XR + 40, 25, HW - 8, TOPZ - 1, TOPZ + 11)               # spring / preload access
PAD = (X0 + 26, XR - 22)                                                     # friction pad block x range (felt 2 mm in front)
top += box(PAD[0], PAD[0] + 2, -10, 10, ARMZ[1] + 1.5, TOPZ)                 # flexure leaf (2 t) hanging from the lid
top += box(PAD[0], PAD[1], -10, 10, ARMZ[1] + 1.5, TOPZ - 1)                 # pad block
part("tower_top", top, "fixed", note="러더 축 뚜껑 (위 6000) + 마찰 패드 판스프링 (뚜껑과 한 몸, M6 손나사가 밀면 펠트가 허브를 누름)", orient="뚜껑 윗면을 바닥에", fill=0.25)
part("bearing_rock_lo", b6000((XR, 0), 2, 10), "fixed", kind="buy", material="steel", note="6000ZZ (러더 축 Ø10, 아래)")
part("bearing_rock_hi", b6000((XR, 0), TOPZ, TOPZ + 8), "fixed", kind="buy", material="steel", note="6000ZZ (러더 축 Ø10, 위)")
part("damper_felt", box(PAD[1], PAD[1] + 2, -10, 10, ARMZ[1] + 1.5, ARMZ[1] + 5.5), "fixed", kind="buy", material="felt",
     note="펠트 패드 2 t (붙임) = 마찰 댐퍼. 스틱션이 생기므로 약하게만 (계산: 패드 힘 약 400 N 아래면 가운데로 돌아옴, 추정)")
part("damper_screw", cx(0, ARMZ[1] + 4, X0 - 14, PAD[0], 6) + cx(0, ARMZ[1] + 4, X0 - 14, X0 - 8, 18), "fixed", kind="buy", material="steel",
     note="M6 볼트 + 출력 손잡이 (뒤벽 나사 구멍) = 마찰 세기 조절 (0 = 풀어 둠)")
for sx, nm in ((1, "F"), (-1, "B")):
    x = XR + sx * RX
    lv = box(x - 7, x + 7, PIVY - 8, SPRY + 8, *LEVZ) - cz(x, PIVY, LEVZ[0] - 1, LEVZ[1] + 1, 6.3) - cz(x, 0, LEVZ[0] - 1, LEVZ[1] + 1, 8.2)
    lv -= cz(x, SPRY, LEVZ[0] - 1, LEVZ[1] + 1, 4.5)
    part(f"lever_{nm}", lv, "fixed", note="센터링 롤러 레버 (PLA, 지렛대 2:1)", orient="눕혀서, 채움 100 %", fill=0.5)
    part(f"roller_{nm}", bearing("z", (x, 0), CAM["z0"] + 0.5, CAM["z0"] + 7.5), "fixed", kind="buy", material="steel", note="608ZZ 롤러")
SZ_ = (LEVZ[0] + LEVZ[1]) / 2 + 9
part("rock_spring", cx(SPRY, SZ_, XR - RX + 8, XR + RX - 22, 10), "fixed", kind="buy", material="steel",
     note=f"인장 스프링 (기본 k ≈ {SPRING['k']} N/mm, 추정) — 바꿔 끼워 페달 무게감 조절")
part("rock_eyebolt", cx(SPRY, SZ_, XR + RX - 24, XR + RX + 14, 5) + cx(SPRY, SZ_, XR + RX + 7, XR + RX + 13, 14),
     "fixed", kind="buy", material="steel", note="M5 볼트 + 출력 손잡이 너트 = 가운데 힘 (예압) 조절. 안 쓸 때 풀어 둠 (PLA 캠 눌림 방지)")
part("as5600_rudder", box(XR - 11.5, XR + 11.5, -11.5, 11.5, TOPZ + 18.4, TOPZ + 20), "fixed", kind="buy", material="PCB", note="AS5600 (러더)")
sm = box(XR - 20, XR + 20, -20, 20, TOPZ + 20, TOPZ + 23) + box(XR - 20, XR - 14, -20, 20, TOPZ + 6, TOPZ + 23) + box(XR + 14, XR + 20, -20, 20, TOPZ + 6, TOPZ + 23)
sm -= cz(XR, 0, TOPZ + 5, TOPZ + 10.2, 40.4)
part("sensor_mount_rudder", sm, "fixed", note="러더 AS5600 받침 (뚜껑 위)")

# ---------------- front frames + rear blocks (fixed, clamp on the rails) ----------------
for s, nm in ((1, "L"), (-1, "R")):
    y = s * PY
    ylo, yhi = sorted((y - s * 50, y + s * 50))
    ff = box(FB[0], FB[1], ylo, yhi, 0, 28)
    ff += box(FB[1] - 0.5, FB[1] + 30, s * YR - 15, s * YR + 15, 0, 12)          # tab over the rail in front of the carriage reach: T-nut knob + index pin
    yi = sorted((s * HW, s * (HW + 15)))
    ff += box(FB[1] - 0.5, XR + 30, yi[0], yi[1], 0, 28) + box(FB[1] - 0.5, XR + 60, yi[0], yi[1], 0, 50)  # arm along the tower side
    ff -= box(FB[1] - 1, XR + 61, yi[0] - 1, yi[1] + 1, 50, 60)
    for dy in (-ROD_DY, ROD_DY):
        ff -= cx(y + dy, ROD_Z, FB[0] - 1, FB[1] + 1, ROD_D + 0.1)
        ff -= cz((FB[0] + FB[1]) / 2, y + dy, ROD_Z, 29, 3.4)                  # M4 pinch on the rod
    ff -= cz(FB[1] + 9, s * YR, -1, 13, 6.5)                                  # M6 T-nut bolt (hand knob), free of the carriage
    if s > 0: ff -= cz(FB[1] + 22, s * YR, -1, 13, 6.2)                      # Ø6 index pin (left only)
    for x in (XR - 50, XR + 40):
        for z in (14, 40):
            ff -= cy(x, z, yi[0] - 1, yi[1] + 1, 5.5)
    part(f"front_frame_{nm}", ff, "fixed", note="앞틀 (PLA): 봉 2 개 앞 끝 + 러더 상자 옆에 M5 ×4 + 4040 T너트 1 + (왼쪽) 인덱스 핀", orient="바닥을 바닥에", fill=0.25)
    rb = box(RB[0], RB[1], ylo, yhi, 0, 28)
    for dy in (-ROD_DY, ROD_DY):
        rb -= cx(y + dy, ROD_Z, RB[0] - 1, RB[1] + 1, ROD_D + 0.1)
        rb -= cz((RB[0] + RB[1]) / 2, y + dy, ROD_Z, 29, 3.4)
    rb -= cz((RB[0] + RB[1]) / 2, s * YR, -1, 29, 6.5)
    part(f"rear_block_{nm}", rb, "fixed", note="뒤 봉 받침 (PLA): 봉 2 개 뒤 끝 + 4040 T너트 1", orient="바닥을 바닥에", fill=0.25)
    for dy in (-ROD_DY, ROD_DY):
        part(f"rod_{nm}{'o' if dy * s > 0 else 'i'}", cx(y + dy, ROD_Z, RB[0], FB[1], ROD_D), "fixed", kind="buy", material="steel",
             note=f"Ø12 h6 연마봉 {FB[1] - RB[0]:.0f} mm (LM12UU 가 미끄러짐)")
    for e, x0, x1 in (("f", FB[0] - 2, FB[0]), ("b", RB[1], RB[1] + 2)):
        pd = box(x0, x1, ylo, yhi, 1, 28)
        for dy in (-ROD_DY, ROD_DY): pd -= cx(y + dy, ROD_Z, x0 - 1, x1 + 1, ROD_D + 1)
        part(f"bumper_{nm}{e}", pd, "fixed", kind="buy", material="rubber", note="고무 패드 2 t (붙임) = 페달 ±40 mm 멈춤 (부싱 상자가 닿음)")
part("index_pin", cz(FB[1] + 22, YR, -10, 30, 6) + cz(FB[1] + 22, YR, 24, 30, 16), "fixed", kind="buy", material="steel", note="Ø6 인덱스 핀 (다리 길이 25 mm 단위)")

# ---------------- rocker group (turns about z at (XR, 0)) ----------------
plane_c = Plane(origin=(XR, 0, CAM["z0"]), x_dir=(1, 0, 0), z_dir=(0, 0, 1))
part("cam_rudder", cam_solid(plane_c, cam_pr, CAM["t"], bore=10.2, bolts=[(0, 14, 3.4), (0, -14, 3.4)]), "rocker",
     note="러더 캠 (PLA 출력, 바꿔 끼움, 0.12 mm 층, 벽 6 줄). 롤러 면 4 곳에 스테인리스 띠 0.5×8 에폭시", orient="눕혀서", fill=0.5)
part("rock_shaft", cz(XR, 0, 2, TOPZ + 15, 10), "rocker", kind="buy", material="steel", note="Ø10 h6 연마봉 83 mm, D컷")
part("rock_hub", cz(XR, 0, ARMZ[0] - 6, ARMZ[1] + 6, 40) - cz(XR, 0, ARMZ[0] - 7, ARMZ[1] + 7, 10.1) - box(XR - 16, XR + 16, -21, 21, ARMZ[0], ARMZ[1]),
     "rocker", note="러더 바 허브 (PLA): 알루미늄 바를 위아래로 물고 M4 ×4, 축은 D컷 + 무두볼트. 윗 테두리 = 마찰 패드 면", fill=0.5)
bar = box(XR - 15, XR + 15, -PY - 14, PY + 14, *ARMZ)
for s in (1, -1):
    bar -= cz(XR, s * PY, ARMZ[0] - 1, ARMZ[1] + 1, 6.5)
    bar -= cz(XR, s * 88, ARMZ[0] - 1, ARMZ[1] + 1, 3.4)
bar -= cz(XR, 0, ARMZ[0] - 1, ARMZ[1] + 1, 10.2)
part("rock_bar", bar, "rocker", kind="buy", material="AL6061", note=f"알루미늄 평철 30×8, {2 * PY + 28} mm (러더 바), 끝 M6 구멍 = 연결봉")
part("magnet_rudder", cz(XR, 0, TOPZ + 15, TOPZ + 18, 8), "rocker", kind="buy", material="NdFeB", note="자석 Ø6×2.5 직경 방향 (축 위 끝)")

# ---------------- pedal carriages (slide along x) + plates (toe brake) ----------------
HORN = 45
TL = math.radians(LEAN); U = (math.cos(TL), math.sin(TL)); N = (math.sin(TL), -math.cos(TL))   # up the plate / behind it
def plate_shape(s):
    y = s * PY
    L, W = 230, 100
    c = (HX + U[0] * L / 2, HZ + U[1] * L / 2)
    p = Pos(c[0], y, c[1]) * Rot(0, -LEAN, 0) * Box(L, W, PT)
    for dy in (-30, 30):
        p += Pos(c[0] + N[0] * (PT / 2 + RIB / 2 - 0.25), y + dy, c[1] + N[1] * (PT / 2 + RIB / 2 - 0.25)) * Rot(0, -LEAN, 0) * Box(L - 30, 6, RIB + 0.5)   # ribs behind
    p += Pos(HX + U[0] * (L - 6) - N[0] * 9, y, HZ + U[1] * (L - 6) - N[1] * 9) * Rot(0, -LEAN, 0) * Box(12, W, 16)   # toe lip
    for k in range(4):                                                                                     # open grate: windows between / outside the ribs
        sk = 50 + 42 * k
        p -= Pos(HX + U[0] * sk, y, HZ + U[1] * sk) * Rot(0, -LEAN, 0) * Box(30, 46, 40)
        for dy in (-40, 40):
            p -= Pos(HX + U[0] * sk, y + dy, HZ + U[1] * sk) * Rot(0, -LEAN, 0) * Box(30, 12, 40)
    p -= box(HX - 30, HX + 30, y - 51, y - 37, HZ - 20, HZ + 40); p -= box(HX - 30, HX + 30, y + 37, y + 51, HZ - 20, HZ + 40)
    p += cy(HX, HZ, y - 36, y + 36, 18)
    p += box(HX - HORN, HX, y - 10, y + 10, HZ - 6, HZ + 6)
    p -= cy(HX, HZ, y - 52, y + 52, 8.2)
    return p
# brake stop posts: rib back face point at S_STOP up the plate, at full brake (plate leans LEAN - BRK)
S_STOP = 120
tb_ = math.radians(LEAN - BRK)
STOP_X = HX + math.cos(tb_) * S_STOP + math.sin(tb_) * (PT / 2 + RIB)
STOP_Z = HZ + math.sin(tb_) * S_STOP - math.cos(tb_) * (PT / 2 + RIB)
for s, nm in ((1, "L"), (-1, "R")):
    y = s * PY
    cb = box(-110, EAR[1], y - 50, y + 50, 29.5, CAR_Z) - box(-62, 34, y - 22, y + 22, 29, CAR_Z + 1)   # window under the plate
    for dy in (-ROD_DY, ROD_DY):
        for (a0, a1) in ((HOUS[0], HOUS[0] + LMUU[1] + 4), (HOUS[1] - LMUU[1] - 4, HOUS[1])):           # 2 bushing seats per rod
            cb += tube("x", (y + dy, ROD_Z), a0, a1, 29, 0.1) + box(a0, a1, y + dy - 8, y + dy + 8, ROD_Z, 29.6)
    for dy in (-43, 43):
        cb += box(HX - 12, HX + 12, y + dy - 4, y + dy + 4, CAR_Z - 1, HZ + 12) - cy(HX, HZ, y + dy - 5, y + dy + 5, 8.2)
    cb += box(EAR[0], EAR[1], y - 9, y + 9, CAR_Z - 1, ARMZ[1] + 4)                                # link ear (front)
    cb -= cx(y, LINKZ, EAR[0] - 1, EAR[1] + 1, 6.5)
    tb2 = math.radians(LEAN - BRK); Nb = (math.sin(tb2), -math.cos(tb2))
    for dy in (-30, 30):
        po = box(STOP_X - 10, STOP_X + 10, y + dy - 10, y + dy + 10, CAR_Z - 1, STOP_Z + 14)          # toe-brake stop posts (20 x 20), top cut on the rib plane
        po -= Pos(STOP_X - Nb[0] * 50.3, y + dy, STOP_Z - Nb[1] * 50.3) * Rot(0, -(LEAN - BRK), 0) * Box(200, 40, 100)
        cb += po
    bx = HX - HORN + 8
    cb += box(bx - 26, bx - 12, y - 16, y + 16, CAR_Z - 1, HZ + 36) + box(bx - 26, bx + 12, y - 16, y + 16, HZ + 28, HZ + 36)
    cb -= cz(bx, y, HZ + 27, HZ + 37, 5.0)
    for dy in (-ROD_DY, ROD_DY):
        cb -= cx(y + dy, ROD_Z, HOUS[0] - 1, HOUS[1] + 1, LMUU[0])                              # LM12UU bore (press fit both ends)
    part(f"carriage_{nm}", cb, f"car{nm}", note="페달 캐리지 (PLA): 아래 = LM12UU 4 개 상자 (봉 2), 가운데 = 발뒤꿈치 경첩 귀, 앞 = 연결봉 귀 + 브레이크 멈춤 기둥 2, 뒤 = 브레이크 스프링 다리",
         orient="윗면을 바닥에 (부싱 구멍 위로), 채움 30 %", fill=0.25)
    for dy in (-ROD_DY, ROD_DY):
        for (x0, x1) in ((HOUS[0], HOUS[0] + LMUU[1]), (HOUS[1] - LMUU[1], HOUS[1])):
            part(f"lmuu_{nm}{'o' if dy * s > 0 else 'i'}{'b' if x0 == HOUS[0] else 'f'}", tube("x", (y + dy, ROD_Z), x0, x1, LMUU[0], ROD_D), f"car{nm}",
                 kind="buy", material="steel", note="LM12UU 볼 부싱")
    part(f"pedal_{nm}", plate_shape(s), f"brk{nm}", note="페달 판 230×100 (PLA, 뒤 갈비 2 × 22 깊이, 발끝 턱). 발끝으로 누르면 경첩 중심으로 앞으로 15° = 토 브레이크, 끝에서 갈비가 멈춤 기둥에 닿음",
         orient="뒷면 (갈비) 을 위로", fill=0.45)
    part(f"hinge_pin_{nm}", cy(HX, HZ, y - 54, y + 54, 8), f"brk{nm}", kind="buy", material="steel", note="Ø8 h6 핀 108 mm (페달에 고정, 귀에서 돎, 끝에 자석)")
    part(f"brake_spring_{nm}", cz(HX - HORN + 8, y, HZ + 6, HZ + 27, 14), f"car{nm}", kind="buy", material="steel", note="토 브레이크 압축 스프링 OD 14 × 25 (k ≈ 10 N/mm, 추정): 뿔을 위에서 누름, M6 나사로 예압")
    so = s * (PY + 58)
    part(f"as5600_brake_{nm}", box(HX - 11.5, HX + 11.5, so - 0.8, so + 0.8, HZ - 11.5, HZ + 11.5), f"car{nm}", kind="buy", material="PCB", note=f"AS5600 (토 브레이크 {'왼' if s > 0 else '오른'})")
    smb = box(HX - 14, HX + 14, so + s * 0.8, so + s * 3.8, HZ - 14, HZ + 14) + box(HX - 14, HX + 14, min(y + s * 31, so), max(y + s * 31, so), CAR_Z, CAR_Z + 5)
    part(f"sensor_mount_{nm}", smb, f"car{nm}", note="브레이크 AS5600 받침 (경첩 바깥 끝)")

def car_dx(s, phi):
    return -s * PY * math.sin(math.radians(phi))      # rocker +phi: left (+y) end moves back
def link_shape(s, phi):
    y = s * PY
    p0 = ((EAR[0] + EAR[1]) / 2 + car_dx(s, phi), y, LINKZ)
    ph = math.radians(phi)
    p1 = (XR - s * PY * math.sin(ph), s * PY * math.cos(ph), LINKZ + 12)
    L = math.dist(p0, p1)
    mid = [(p0[i] + p1[i]) / 2 for i in range(3)]
    ang = math.degrees(math.atan2(p1[2] - p0[2], math.hypot(p1[0] - p0[0], p1[1] - p0[1])))
    yaw = math.degrees(math.atan2(p1[1] - p0[1], p1[0] - p0[0]))
    return Pos(*mid) * Rot(0, 0, yaw) * Rot(0, -ang, 0) * Rot(0, 90, 0) * Cylinder(3, L - 24)
for s, nm in ((1, "L"), (-1, "R")):
    part(f"link_{nm}", link_shape(s, 0), "link", kind="buy", material="steel", note="연결봉: M6 나사봉 + 로드엔드 (길이 조절 = 페달 가운데 맞춤)")

def posed(name, phi, bl=0, br=0):
    s = parts[name]["shape"]; g = parts[name]["group"]
    if g == "rocker" and phi: s = s.rotate(Axis((XR, 0, 0), (0, 0, 1)), phi)
    if g == "link":
        return link_shape(1 if name.endswith("L") else -1, phi)
    for side, sg, b in (("L", 1, bl), ("R", -1, br)):
        if g == f"brk{side}" and b: s = s.rotate(Axis((HX, 0, HZ), (0, 1, 0)), b)
        if g in (f"car{side}", f"brk{side}"): s = Pos(car_dx(sg, phi), 0, 0) * s
    return s

MATES = [("rock_shaft", "cam_rudder"), ("rock_shaft", "rock_hub"), ("rock_shaft", "rock_bar"), ("rock_shaft", "bearing_rock_lo"), ("rock_shaft", "bearing_rock_hi"),
         ("bearing_rock_lo", "tower"), ("bearing_rock_hi", "tower_top"), ("rock_shaft", "tower"), ("rock_shaft", "tower_top"), ("rock_hub", "rock_bar"),
         ("rock_shaft", "magnet_rudder"), ("rock_spring", "rock_eyebolt"), ("tower_top", "sensor_mount_rudder"), ("tower", "tower_top"),
         ("damper_felt", "tower_top"), ("damper_felt", "rock_hub"), ("damper_screw", "tower"), ("damper_screw", "tower_top"),
         ("index_pin", "front_frame_L"), ("index_pin", "rail_L"), ("as5600_rudder", "sensor_mount_rudder")]
for nm in ("F", "B"):
    MATES += [(f"roller_{nm}", f"lever_{nm}"), (f"roller_{nm}", "cam_rudder"), (f"lever_{nm}", "tower"), ("rock_spring", f"lever_{nm}"), ("rock_eyebolt", f"lever_{nm}")]
for nm in ("L", "R"):
    MATES += [(f"front_frame_{nm}", "tower"), (f"front_frame_{nm}", f"rail_{nm}"), (f"rear_block_{nm}", f"rail_{nm}"),
              (f"hinge_pin_{nm}", f"carriage_{nm}"), (f"hinge_pin_{nm}", f"pedal_{nm}"), (f"brake_spring_{nm}", f"carriage_{nm}"), (f"brake_spring_{nm}", f"pedal_{nm}"),
              (f"link_{nm}", f"carriage_{nm}"), (f"link_{nm}", "rock_bar"), (f"sensor_mount_{nm}", f"carriage_{nm}"), (f"as5600_brake_{nm}", f"sensor_mount_{nm}"),
              (f"bumper_{nm}f", f"front_frame_{nm}"), (f"bumper_{nm}b", f"rear_block_{nm}"), (f"pedal_{nm}", f"carriage_{nm}")]
    for r in ("o", "i"):
        MATES += [(f"rod_{nm}{r}", f"front_frame_{nm}"), (f"rod_{nm}{r}", f"rear_block_{nm}"), (f"rod_{nm}{r}", f"bumper_{nm}f"), (f"rod_{nm}{r}", f"bumper_{nm}b")]
        for e in ("f", "b"):
            MATES += [(f"lmuu_{nm}{r}{e}", f"carriage_{nm}"), (f"lmuu_{nm}{r}{e}", f"rod_{nm}{r}")]
        MATES += [(f"rod_{nm}{r}", f"carriage_{nm}")]
    for e in ("f", "b"):
        MATES += [(f"bumper_{nm}{e}", f"carriage_{nm}")]
ALLOW = {frozenset(p) for p in MATES}

def forces():
    angs = [round(PHI * i / 20, 2) for i in range(21)]
    var = {}
    for nm, kf, pf in (("light", 0.5, 0.5), ("default", 1, 1), ("heavy", 2, 1.5)):
        t, _ = cam_torque_curve(cam_pts, [0, math.pi], 11, SPRING["k"] * kf, SPRING["pre"] * pf, (SPRY - PIVY) / (-PIVY), angs)
        var[nm] = dict(k=SPRING["k"] * kf, pedal_N=[round(tt / (PY * math.cos(math.radians(a))), 1) for tt, a in zip(t, angs)])
    return dict(variants=var, travel_mm=[round(PY * math.sin(math.radians(a)), 1) for a in angs], rocker_deg=angs,
                note="한쪽 페달에서 필요한 힘 N (부싱 · 로드엔드 마찰과 펠트 마찰 제외, 추정)")

def strength(fc):
    """Panic 1000 N on one pedal plate (normal to the plate, ball of the foot 170 mm up from the heel hinge, toe brake bottomed
    on the stop posts) and the both-feet brace case (2 x 906 N forward at the pedal centre, rocker not on a stop). 추정."""
    from ctl_lib import PLA_MECH as M, C0_6000, hertz_line, sf
    F = 1000.0; sp = 170.0
    Fh, Fv = F * N[0], -F * N[1]                       # forward / down components
    Rpost = F * sp / S_STOP; Mplate = F * (sp - S_STOP)
    # plate + 2 ribs section (about the plate's own bending axis)
    A1, y1, I1 = 100 * PT, 0.0, 100 * PT ** 3 / 12
    A2, y2, I2 = 2 * 6 * RIB, PT / 2 + RIB / 2, 2 * 6 * RIB ** 3 / 12
    yc = (A1 * y1 + A2 * y2) / (A1 + A2); I = I1 + A1 * (y1 - yc) ** 2 + I2 + A2 * (y2 - yc) ** 2
    Zp = I / max(PT / 2 + RIB - yc, yc + PT / 2)
    rows = [sf("페달 판 굽힘 (멈춤 기둥 위, 판 + 갈비 2)", Mplate / Zp, M["xy"], note="판을 눕혀 출력 → 굽힘 응력은 층 안")]
    Lp = STOP_Z - CAR_Z; Ip = 20 ** 4 / 12
    Ip = (20 ** 4 - 17.6 ** 4) / 12                  # shell only (1.2 mm walls), infill ignored
    rows.append(sf("멈춤 기둥 좌굴 (20×20 껍데기만, 2 개)", Rpost / 2, math.pi ** 2 * M["E"] * Ip / (2 * Lp) ** 2, unit="N"))
    rows.append(sf("멈춤 기둥 압축", Rpost / 2 / 400, M["comp"]))
    # carriage on the bushings: forward force reacted by the stop at rod height -> pitching couple over the bushing spacing
    zf = HZ + U[1] * sp; sB = (HOUS[1] - HOUS[0]) - LMUU[1]
    Fb = (Fh * (zf - ROD_Z) / sB) / 2 + Fv / 4
    rows.append(sf("LM12UU 정격 (앞 부싱 1 개, 기울임 짝힘 + 아래 힘)", Fb, 784, unit="N", note="LM12UU C0 784 N (영구 눌림 시작, 깨짐 아님). LM12LUU 로 바꾸면 C0 1570"))
    span = FB[1] - RB[0] - 20; a = (HOUS[1] - LMUU[1] / 2) - (RB[0] + 10); b = span - a
    rows.append(sf("Ø12 봉 굽힘 (부싱 힘이 앞쪽에)", Fb * a * b / span / (math.pi * 12 ** 3 / 32), 500, note="연마봉 항복 약 500 MPa (추정)"))
    rows.append(sf("고무 멈춤 → 앞틀 눌림 (부싱 상자 2 면)", Fh / (2 * math.pi * (14.5 ** 2 - 7 ** 2)), M["comp"]))
    # brace: both feet forward, rocker balanced -> 2 x Fh into the rocker shaft
    Fs = 2 * Fh; zb = (2 + 10) / 2; zt = TOPZ + 4; a2 = LINKZ - zb; b2 = zt - LINKZ; L2 = zt - zb
    rows.append(sf("러더 축 Ø10 굽힘 (두 발 버팀)", Fs * a2 * b2 / L2 / (math.pi * 10 ** 3 / 32), 500))
    rows.append(sf("위 6000 정격 (두 발 버팀)", Fs * a2 / L2, C0_6000, unit="N"))
    rows.append(sf("러더 바 30×8 굽힘 (허브 끝)", Fh * (PY - 15) / (8 * 30 ** 2 / 6), 170, note="6063 항복 약 170 (추정)"))
    rows.append(sf("상자 ↔ 앞틀 M5 4 개 눌림 (PLA 구멍)", Fs / 8 / (5 * 6), M["comp"]))
    rows.append(sf("T너트 4 개 마찰 (M6 약 5 kN 조임, μ 0.2)", Fs, 4 * 5000 * 0.2, unit="N"))
    # sustained
    ratio = (SPRY - PIVY) / (-PIVY)
    Fr = SPRING["k"] * SPRING["pre"] * ratio
    Mlev = SPRING["k"] * SPRING["pre"] * SPRY
    creep = [sf("캠 접촉압 (가운데, 예압만 = 계속)", hertz_line(Fr, 7, 11), 3.3 * M["creep"], note="국부 접촉 허용 ~33 MPa 로 봄 (추정)"),
             sf("캠 접촉압 (페달 끝, 순간)", hertz_line(SPRING["k"] * (SPRING["pre"] + ratio * 2 * (roller_centre_dist(cam_pts, -math.radians(PHI), 11) - RX)) * ratio, 7, 11), M["comp"]),
             sf("레버 굽힘 (예압, 계속)", Mlev / (7 * 14 ** 2 / 6), M["creep"])]
    Fend = SPRING["k"] * (SPRING["pre"] + ratio * 2 * (roller_centre_dist(cam_pts, -math.radians(PHI), 11) - RX)) * ratio
    pf, ss = shim_pressure(Fend, 8, SHIM)
    creep.append(sf("캠 + 띠 0.5×8: PLA 받침 압력 (페달 끝)", pf, M["comp"], note=f"띠 굽힘 {ss:.0f} MPa (스테인리스 반경질 ~1000, 추정)"))
    creep.append(sf("캠 + 띠: PLA 받침 압력 (가운데, 계속)", shim_pressure(Fr, 8, SHIM)[0], M["creep"]))
    T0 = fc["variants"]["default"]["pedal_N"][1] * PY
    return dict(F_panic=F, shim_mm=SHIM, rows=rows, creep=creep, post_force=round(Rpost), brace_shaft_force=round(Fs),
                friction=dict(max_pad_N=round(T0 / (0.3 * 20)), note="펠트 μ 0.3, 허브 반지름 20 mm. 이보다 세게 누르면 발을 떼도 가운데로 안 돌아옴 (추정)"),
                note="한 발 1000 N (판에 수직, 발볼 = 경첩에서 170 mm, 브레이크 끝까지 눌림) / 두 발 버팀 2 × 906 N. PLA 층 안 50 / 층 사이 20 / 압축 60 MPa (추정)")

if __name__ == "__main__":
    write_dxf(os.path.join(HERE, "cam_rudder.dxf"), [cam_pts, circle_pts(0, 0, 10.2), circle_pts(0, 14, 3.4), circle_pts(0, -14, 3.4)])
    poses = [(0, 0, 0), (PHI, 0, 0), (-PHI, 0, 0), (0, BRK, BRK), (PHI, BRK, BRK), (-PHI, BRK, BRK)]
    res = check_pairs(parts, posed, poses, ALLOW)
    # brake stop: does the rib reach the stop post exactly at BRK (touch within 1 deg)?
    def brake_stop():
        for b10 in range(0, 200):
            b = b10 / 10
            try: v = (posed("pedal_L", 0, b, 0) & posed("carriage_L", 0)).volume
            except Exception: v = 0
            if v > 0.05: return b
        return None
    f = forces()
    stg = strength(f)
    stg["brake_stop_deg"] = brake_stop()
    info = export_parts(parts, HERE, dict(travel_mm=TRAVEL, rocker_deg=round(PHI, 2), pedal_y=PY, rocker_x=XR, hinge=[HX, HZ], lean_deg=LEAN, brake_deg=BRK,
                                          roller_x=round(RX, 2), spring=SPRING, reach_adjust_mm=100, rail_y=YR, printer=[240, 240, 240], origin="4040 rail top"),
                        extra=dict(forces=f, strength=stg, check=[dict(pose=p, hits=b) for p, b in res]))
    for i in info: print(f"{i['name']:20s} {i['group']:6s} {i['kind']:5s} {i['size']} {i['grams'] or ''}")
    for p, b in res: print("pose", p, b if b else "none")
    print("PHI", round(PHI, 1), "RX", round(RX, 1), "pedal N", f["variants"]["default"]["pedal_N"][::5], "brake stop", stg["brake_stop_deg"])
    for r in stg["rows"] + stg["creep"]: print(f"SF {r['sf']:6.2f}  {r['load']:8.2f}/{r['limit']} {r['unit']}  {r['name']}")
    print("friction", stg["friction"], "grams", round(sum(i["grams"] or 0 for i in info)))
