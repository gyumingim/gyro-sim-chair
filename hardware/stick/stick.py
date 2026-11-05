"""Centre stick base v2 for the gyro sim chair — cam + roller + spring gimbal (VKB / Virpil style), build123d.

Run:  python stick.py   -> stl/*.stl, cam DXFs (laser-cut aluminium), parts.json (BOM, force curves), interference + stop check

Coordinates (mm): x = forward, y = left, z = up. Origin = centre of the base plate underside. Gimbal centre (0, 0, PZ).
Roll axis = x (outer cradle on 608 bearings in the front/back walls). Pitch axis = y (inner block on 608s in the cradle).
Centring per axis (see ctl_lib.py): aluminium cam on the axis + 2 roller levers + 1 tension spring across the lever tips,
preload by eye bolt + knurled nut. Stops: swappable gate plate (top cover) + TPU collar on the stick tube.
Damping: dry clutch (PTFE + friction washer + wave spring + nut) on the roll shaft behind the back wall and on the
pitch shaft between cradle and pitch cam. Sensors: AS5600 + diametric magnet at the back roll shaft end and the -y pitch
shaft end. FFB provision: roll shaft sticks out of the front wall (pulley seat + 4 x M4 motor pad), and the inner block has
a stub below the pivot with an M5 cross hole for push rods from fixed motors (both axes, like Brunner-style FFB bases).
"""
import math, os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from build123d import Axis, Plane, Pos, Rot, Cylinder, Box
from ctl_lib import (box, cx, cy, cz, tube, bearing, cam_points, cam_solid, write_dxf, circle_pts, roller_centre_dist,
                     cam_torque_curve, export_parts, check_pairs)

HERE = os.path.dirname(os.path.abspath(__file__))

# ---------------- parameters ----------------
PZ = 88                       # gimbal centre height above the base underside
TRAVEL = 20                   # mechanism capability (deg, each axis, gate removed)
GATE = dict(roll=15, fwd=16, aft=20)   # default gate (deg): F-5E gear-down roll ~ +-4.0 in at the grip (see docs/stick.html)
TUBE_TOP = 415                # stick tube top above the pivot (grip socket mouth = TUBE_TOP - 40). set for chair v6
L_HAND = TUBE_TOP - 40 + 55   # pivot -> centre of the hand on the grip (grip frame: palm centre ~55 above the mouth, 추정)
BASE_X, BASE_Y = 94, 96       # base plate half sizes
WF0, WF1 = 82, 94             # front wall x range (back wall mirrored)
SW0, SW1 = 88, 96             # side walls |y| range
GZ = PZ + 76                  # gate plate bottom (6 thick)
COLLAR = (PZ + 70, PZ + 100, 30)  # TPU stop collar z0, z1, OD (reaches above the gate top at full tilt)
# roll centring
R_CAM = dict(r0=48, a=28, c=math.radians(2.5), dmax=math.radians(32), r_hub=30, x0=60, t=10)
R_ROLL_X = 65                 # roller (608) centre plane
R_LEV = (72, 78)              # roll lever plate x range
R_PIV, R_SPR = 40, 40         # pivot below / spring above the roller line (lever ratio 2)
R_SPRING = dict(k=2.4, pre=8.0)        # N/mm, mm (default) -> see force table
# pitch centring
P_CAM = dict(r0=34, a=22, c=math.radians(2.5), dmax=math.radians(32), r_hub=24, y1=49, t=8)
P_ROLL_Y = 45
P_LEV = (51, 58)
P_PIV, P_SPR = 30, 32         # pivot at x = -30, spring at x = +32 (ratio ~2)
P_SPRING = dict(k=5.3, pre=6.0)

parts = {}
def part(name, shape, group, kind="print", note="", material="PLA", orient="", fill=0.55):
    parts[name] = dict(shape=shape, group=group, kind=kind, note=note, material=material, orient=orient, fill=fill)

# ---------------- cams (laser-cut 6061 aluminium; DXF written below) ----------------
rc_pts = cam_points([0, math.pi], R_CAM["r0"], R_CAM["a"], R_CAM["c"], R_CAM["dmax"], R_CAM["r_hub"])
pc_pts = cam_points([math.pi / 2, -math.pi / 2], P_CAM["r0"], P_CAM["a"], P_CAM["c"], P_CAM["dmax"], P_CAM["r_hub"])
RY = roller_centre_dist(rc_pts, 0, 11)          # roll roller centre |y|
PRZ = roller_centre_dist(pc_pts, math.pi / 2, 11)   # pitch roller centre |z| (rel. PZ)
plane_r = Plane(origin=(R_CAM["x0"], 0, PZ), x_dir=(0, 1, 0), z_dir=(1, 0, 0))      # local (u, v) = (y, z)
plane_p = Plane(origin=(0, P_CAM["y1"], PZ), x_dir=(1, 0, 0), z_dir=(0, -1, 0))     # local (u, v) = (x, z)
cam_r = cam_solid(plane_r, rc_pts, R_CAM["t"], bolts=[(0, 18, 4.4), (0, -18, 4.4)])
cam_p = cam_solid(plane_p, pc_pts, P_CAM["t"], bolts=[(14, 0, 3.4), (-14, 0, 3.4)])
part("cam_roll", cam_r, "roll", kind="cut", material="AL6061", note="roll 캠: 알루미늄 10 t 레이저 절단 (cam_roll.dxf). 둥근 V 모양 = 가운데 걸림 없이 또렷한 중심")
part("cam_pitch", cam_p, "pitch", kind="cut", material="AL6061", note="pitch 캠: 알루미늄 8 t 레이저 절단 (cam_pitch.dxf), D컷 축에 M3 무두볼트")

# ---------------- housing (fixed) ----------------
base = box(-BASE_X, BASE_X, -BASE_Y, BASE_Y, 0, 8)
for x in (-70, 70):
    for y in (-70, 70):
        base -= cz(x, y, -1, 9, 6.5)                           # M6 x4 to the fold-down column top plate
for x in (-60, 0, 60):
    for s in (1, -1):
        base -= cz(x, s * (SW0 + SW1) / 2, -1, 9, 3.4)          # side walls
for s in (1, -1):
    for y in (-60, 0, 60):
        base -= cz(s * (WF0 + WF1) / 2, y, -1, 9, 3.4)          # front / back walls
base -= box(-40, 40, -40, 40, -1, 9)                           # cable / FFB push-rod opening
part("base_plate", base, "fixed", note="바닥판 188×192: M6 ×4 로 접이식 스틱 기둥 윗판에", orient="그대로 (바닥면 아래)")

def end_wall(s):
    x0, x1 = sorted((s * WF0, s * WF1)); outer = s * WF1
    w = box(x0, x1, -SW1, SW1, 8, GZ)
    w -= cx(0, PZ, outer - s * 7, outer + s, 22.2)            # 608 pocket from outside
    w -= cx(0, PZ, x0 - 1, x1 + 1, 10)
    w -= box(x0 - 1, x1 + 1, -30, 30, PZ + 40, GZ - 10)       # window above (spring access / weight)
    for y in (-60, 0, 60):
        w -= cz((x0 + x1) / 2, y, 7, 22, 2.8)                 # M3 self-tap from the base
    for y in (-70, 70):
        w -= cz((x0 + x1) / 2, y, GZ - 15, GZ + 1, 2.8)       # gate plate screws
    if s > 0:
        for y in (-RY, RY):
            w -= cx(y, PZ - R_PIV, x0 - 1, x1 + 1, 5.0)        # M6 tap: roll lever pivots
        for y in (-25, 25):
            for z in (PZ - 25, PZ + 25):
                w -= cx(y, z, x1 - 10, x1 + 1, 3.4)            # FFB motor pad 50 x 50, M4 inserts
    return w
part("wall_front", end_wall(1), "fixed", note="앞벽: roll 608 베어링 + roll 레버 축 2 + FFB 모터 자리 (M4 ×4)", orient="앞면을 바닥에", fill=0.6)
part("wall_back", end_wall(-1), "fixed", note="뒤벽: roll 608 베어링, 뒤에 마찰 클러치와 roll 센서", orient="뒷면을 바닥에", fill=0.6)

def side_wall(s):
    y0, y1 = sorted((s * SW0, s * SW1))
    w = box(-WF0, WF0, y0, y1, 8, GZ)
    w -= box(-55, 55, y0 - 1, y1 + 1, 22, GZ - 14)            # big window: pitch spring adjust (nut at the bottom lever)
    w -= box(66, WF0 + 1, y0 - 1, y1 + 1, PZ + 26, PZ + 58)    # slot: roll lever tip swing + roll preload knob reachable from the side
    for x in (-60, 0, 60):
        w -= cz(x, (y0 + y1) / 2, 7, 22, 2.8)
    return w
part("wall_side_L", side_wall(1), "fixed", note="옆벽 (왼쪽): 큰 창 = pitch 스프링 조절 너트 손이 닿게", orient="옆면을 바닥에")
part("wall_side_R", side_wall(-1), "fixed", note="옆벽 (오른쪽)", orient="옆면을 바닥에")

def gate_opening(roll, fwd, aft, z_top):
    h = z_top - PZ
    w = lambda a: h * math.tan(math.radians(a)) + COLLAR[2] / 2 / math.cos(math.radians(a))
    return w(aft), w(fwd), w(roll)
GA, GF, GR = gate_opening(GATE["roll"], GATE["fwd"], GATE["aft"], GZ + 6)
gate = box(-WF1, WF1, -SW1, SW1, GZ, GZ + 6)
op = box(-GA + 10, GF - 10, -GR, GR, GZ - 1, GZ + 7) + box(-GA, GF, -GR + 10, GR - 10, GZ - 1, GZ + 7)
for x in (-GA + 10, GF - 10):
    for y in (-GR + 10, GR - 10):
        op += cz(x, y, GZ - 1, GZ + 7, 20)
gate -= op
for x in (-(WF0 + WF1) / 2, (WF0 + WF1) / 2):
    for y in (-70, 70):
        gate -= cz(x, y, GZ - 1, GZ + 7, 3.4)
part("gate_plate", gate, "fixed", material="PETG", note=f"윗판 = 멈춤 게이트 (바꿔 끼움): roll ±{GATE['roll']}°, 앞 {GATE['fwd']}° / 뒤 {GATE['aft']}°. 고무 부츠를 위에 씌움", orient="그대로", fill=0.6)

# roll levers + spring (fixed group: pivots on the front wall)
for s, nm in ((1, "L"), (-1, "R")):
    y = s * RY
    lv = box(R_LEV[0], R_LEV[1], y - 7, y + 7, PZ - R_PIV - 8, PZ + R_SPR + 8)
    lv -= cx(y, PZ - R_PIV, R_LEV[0] - 1, R_LEV[1] + 1, 6.3)
    lv -= cx(y, PZ, R_LEV[0] - 1, R_LEV[1] + 1, 8.2)
    lv -= cy((R_LEV[0] + R_LEV[1]) / 2, PZ + R_SPR, y - 8, y + 8, 5.5)
    part(f"roll_lever_{nm}", lv, "fixed", material="PETG", note="roll 롤러 레버: 아래 = 축 (M6 어깨볼트), 가운데 = 608 롤러, 위 = 스프링 (지렛대 2:1)", orient="옆으로 눕혀 (구멍이 위로)", fill=1.0)
    part(f"roll_roller_{nm}", bearing("x", (y, PZ), R_ROLL_X - 3.5, R_ROLL_X + 3.5), "fixed", kind="buy", material="steel", note="608ZZ 롤러 (캠을 누름)")
    part(f"roll_pivot_{nm}", cx(y, PZ - R_PIV, R_LEV[0] - 2, WF0 + 10, 6), "fixed", kind="buy", material="steel", note="M6 어깨볼트 (레버 축)")
xs = (R_LEV[0] + R_LEV[1]) / 2
part("roll_spring", cy(xs, PZ + R_SPR, -RY + 8, RY - 22, 8), "fixed", kind="buy", material="steel",
     note=f"roll 인장 스프링 (기본 k ≈ {R_SPRING['k']} N/mm, OD 8, 추정). 바꿔 끼워 무게감 조절")
part("roll_eyebolt", cy(xs, PZ + R_SPR, RY - 24, RY + 14, 5) + cy(xs, PZ + R_SPR, RY + 7, RY + 13, 14), "fixed", kind="buy", material="steel",
     note="M5 아이볼트 + 손잡이 너트 = roll 예압 (가운데 힘) 조절")

# back: dry clutch + roll sensor
part("roll_clutch", tube("x", (0, PZ), -WF1 - 7, -WF1, 26, 8.2), "roll", kind="buy", material="PTFE",
     note="roll 마찰 클러치: PTFE 와셔 + 마찰 와셔 + 웨이브 스프링 + 나일록 너트 (조이면 묵직)")
sm = box(-WF1 - 18, -WF1 - 14, -22, 22, PZ - 22, PZ + 22) + box(-WF1 - 18, -WF1, -22, -16, PZ - 22, PZ + 22) + box(-WF1 - 18, -WF1, 16, 22, PZ - 22, PZ + 22)
sm -= cx(0, PZ, -WF1 - 19, -WF1 - 13, 6)
part("sensor_mount_roll", sm, "fixed", note="roll AS5600 받침 (뒤벽 뒤, 자석과 1~2 mm)", orient="뒷면을 바닥에")
part("as5600_roll", box(-WF1 - 13.6, -WF1 - 12, -11.5, 11.5, PZ - 11.5, PZ + 11.5), "fixed", kind="buy", material="PCB", note="AS5600 (roll)")
part("magnet_roll", cx(0, PZ, -WF1 - 11.5, -WF1 - 8, 8), "roll", kind="buy", material="NdFeB", note="자석 Ø6×2.5 직경 방향 + 축 끝 컵")

# ---------------- cradle (roll group) ----------------
cr = box(-52, 52, -35, 35, PZ - 30, PZ + 14) - box(-40, 40, -25, 25, PZ - 31, PZ + 15)
for s in (1, -1):
    cr -= cy(0, PZ, s * 28 - 0.01 * s, s * 36, 22.2)           # 608 pockets from outside
    cr -= cy(0, PZ, s * 24, s * 36, 10)
    cr -= cx(0, PZ, s * 38, s * 53, 8.1)                       # roll shaft seats (Ø8 h6, M4 pinch)
    cr -= cz(s * 46, 0, PZ + 2, PZ + 15, 3.4)
for (x, z) in ((-46, PZ - 18), (-46, PZ + 18), (46, PZ)):
    cr -= cy(x, z, 26, 36, 2.8)                                # pitch bracket screws (+y side plate)
for (x, z) in ((-19, PZ - 19), (19, PZ - 19)):
    cr -= cy(x, z, -36, -26, 2.8)                              # pitch sensor mount screws (-y)
cr -= cx(18, PZ, 50, 53, 3.6); cr -= cx(-18, PZ, 50, 53, 3.6)  # roll cam bolts (M4) via the spacer hub
part("cradle", cr, "roll", material="PETG", note="바깥 요람 (roll 로 돎): 앞뒤 Ø8 축 + pitch 608 베어링 2. 위가 뚫려 스틱이 지나감", orient="바닥 쪽을 바닥에, 채움 60 % + 벽 5 줄", fill=0.65)
part("cam_hub_roll", tube("x", (0, PZ), 52, R_CAM["x0"], 30, 8.2) - cx(18, PZ, 51, 61, 4.4) - cx(-18, PZ, 51, 61, 4.4), "roll", material="PETG",
     note="roll 캠 받침 (요람 앞면 ↔ 캠, M4 ×2 로 같이 조임 → 캠이 축이 아니라 요람에 고정)", fill=1.0)
for s, nm in ((1, "front"), (-1, "back")):
    o = s * WF1
    part(f"bearing_roll_{nm}", bearing("x", (0, PZ), o - s * 7, o), "fixed", kind="buy", material="steel", note="608-2RS (roll 축)")
part("roll_shaft_front", cx(0, PZ, 40, WF1 + 18, 8), "roll", kind="buy", material="steel", note="Ø8 h6 연마봉 70 mm (앞, 끝 18 mm = FFB 풀리 자리)")
part("roll_shaft_back", cx(0, PZ, -WF1 - 8, -40, 8), "roll", kind="buy", material="steel", note="Ø8 h6 연마봉 62 mm (뒤, 끝에 자석)")
for s, nm in ((1, "L"), (-1, "R")):
    part(f"bearing_pitch_{nm}", bearing("y", (0, PZ), s * 28, s * 35), "roll", kind="buy", material="steel", note="608-2RS (pitch 축)")

# pitch centring module (rides on the cradle, +y side)
pb = box(-50, 50, 60, 66, PZ - 50, PZ + 50)
for (x, z) in ((-46, PZ - 18), (-46, PZ + 18), (46, PZ)):
    pb += cy(x, z, 35, 60, 12)
    pb -= cy(x, z, 34, 67, 3.4)
for z in (PZ - PRZ, PZ + PRZ):
    pb += cy(-P_PIV, z, 58, 60, 14)
    pb -= cy(-P_PIV, z, 57, 67, 5.0)                           # M6 tap for the lever pivots
pb -= box(-20, 20, 59, 67, PZ - 20, PZ + 20)                   # window
part("pitch_bracket", pb, "roll", material="PETG", note="pitch 센터링 받침 (요람 옆에 M3 ×3, 같이 roll 로 돎)", orient="큰 면을 바닥에", fill=0.7)
for sz, nm in ((1, "T"), (-1, "B")):
    z = PZ + sz * PRZ
    lv = box(-P_PIV - 8, P_SPR + 8, P_LEV[0], P_LEV[1], z - 7, z + 7)
    lv -= cy(-P_PIV, z, P_LEV[0] - 1, P_LEV[1] + 1, 6.3)
    lv -= cy(0, z, P_LEV[0] - 1, P_LEV[1] + 1, 8.2)
    lv -= cz(P_SPR, (P_LEV[0] + P_LEV[1]) / 2, z - 8, z + 8, 5.5)
    part(f"pitch_lever_{nm}", lv, "roll", material="PETG", note="pitch 롤러 레버 (지렛대 2:1)", orient="옆으로 눕혀", fill=1.0)
    part(f"pitch_roller_{nm}", bearing("y", (0, z), P_ROLL_Y - 3.5, P_ROLL_Y + 3.5), "roll", kind="buy", material="steel", note="608ZZ 롤러")
    part(f"pitch_pivot_{nm}", cy(-P_PIV, z, P_LEV[0] - 2, 62, 6), "roll", kind="buy", material="steel", note="M6 어깨볼트")
ys_ = (P_LEV[0] + P_LEV[1]) / 2
part("pitch_spring", cz(P_SPR, ys_, PZ - PRZ + 22, PZ + PRZ - 8, 10), "roll", kind="buy", material="steel",
     note=f"pitch 인장 스프링 (기본 k ≈ {P_SPRING['k']} N/mm, OD 10, 추정)")
part("pitch_eyebolt", cz(P_SPR, ys_, PZ - PRZ - 14, PZ - PRZ + 24, 5) + cz(P_SPR, ys_, PZ - PRZ - 13, PZ - PRZ - 7, 14), "roll", kind="buy", material="steel",
     note="M5 아이볼트 + 손잡이 너트 (아래 레버) = pitch 예압 조절, 옆창으로 손이 닿음")
part("pitch_clutch", tube("y", (0, PZ), 36, 40.5, 24, 8.2), "pitch", kind="buy", material="PTFE", note="pitch 마찰 클러치 (요람 ↔ 캠 사이 와셔 묶음)")
# pitch sensor (-y)
ps = box(-22, 22, -52, -49, PZ - 22, PZ + 22) + box(-22, -16, -52, -35, PZ - 22, PZ - 16) + box(16, 22, -52, -35, PZ - 22, PZ - 16)
ps -= cy(0, PZ, -53, -48, 6)
part("sensor_mount_pitch", ps, "roll", note="pitch AS5600 받침 (요람 −y 옆)")
part("as5600_pitch", box(-11.5, 11.5, -48.6, -47, PZ - 11.5, PZ + 11.5), "roll", kind="buy", material="PCB", note="AS5600 (pitch)")
part("magnet_pitch", cy(0, PZ, -46, -42.5, 8), "pitch", kind="buy", material="NdFeB", note="자석 Ø6×2.5 + 축 끝 컵")

# ---------------- inner block + tube (pitch group) ----------------
ib = box(-16, 16, -24, 24, PZ - 22, PZ + 22) + cz(0, 0, PZ + 10, PZ + 60, 34)
ib += box(-28, -14, -9, 9, PZ + 28, PZ + 58)                   # clamp ears
ib += cz(0, 0, PZ - 50, PZ - 20, 16)                           # FFB / damper stub below the pivot
ib -= cy(0, PZ, -25, 25, 8.1)
for x in (-8, 8):
    ib -= cz(x, 10, PZ, PZ + 23, 3.3)                          # M4 set screws onto the D-flat
ib -= cz(0, 0, PZ + 6, PZ + 61, 20.2)                          # tube socket 55 deep
ib -= box(-29, -8, -1, 1, PZ + 24, PZ + 61)                    # clamp slit
for z in (PZ + 36, PZ + 51):
    ib -= cy(-22, z, -10, 10, 5.5)
ib -= cz(0, 0, PZ - 51, PZ - 22, 6)                            # cable from the grip goes down the tube and out here
ib -= cy(0, PZ - 43, -9, 9, 5.5)                               # M5 cross hole (push-rod eye)
part("inner_block", ib, "pitch", material="PETG", note="안쪽 블록 (pitch 로 돎): Ø20 관 소켓 55 mm + M5 클램프 2, 아래 = FFB 막대 고리 / 배선 출구", orient="소켓을 위로, 채움 100 %", fill=1.0)
part("pitch_shaft", cy(0, PZ, -46, P_CAM["y1"] + 1, 8), "pitch", kind="buy", material="steel", note="Ø8 h6 연마봉 96 mm, D컷 (블록 + 캠 고정)")
part("stick_tube", tube("z", (0, 0), PZ + 6, PZ + TUBE_TOP, 20, 16), "pitch", kind="buy", material="AL6061",
     note=f"알루미늄 관 Ø20×2t, 길이 {TUBE_TOP - 6} mm. 위 40 mm 가 손잡이 속 (M4 가로볼트, 뒤쪽 4×6 홈)")
part("stop_collar", tube("z", (0, 0), COLLAR[0], COLLAR[1], COLLAR[2], 20.2), "pitch", material="TPU",
     note="TPU 멈춤 링 (게이트에 닿아 부드럽게 멈춤), M3 무두볼트 고정", orient="그대로", fill=1.0)

# ---------------- pose + checks ----------------
def posed(name, roll, pitch):
    s = parts[name]["shape"]; g = parts[name]["group"]
    if g == "pitch" and pitch: s = s.rotate(Axis((0, 0, PZ), (0, 1, 0)), pitch)   # + = top moves forward
    if g in ("pitch", "roll") and roll: s = s.rotate(Axis((0, 0, PZ), (1, 0, 0)), roll)
    return s

MATES = [("pitch_shaft", "inner_block"), ("pitch_shaft", "cam_pitch"), ("pitch_shaft", "magnet_pitch"), ("pitch_shaft", "pitch_clutch"),
         ("pitch_shaft", "bearing_pitch_L"), ("pitch_shaft", "bearing_pitch_R"), ("bearing_pitch_L", "cradle"), ("bearing_pitch_R", "cradle"),
         ("roll_shaft_front", "cradle"), ("roll_shaft_back", "cradle"), ("roll_shaft_front", "cam_roll"), ("roll_shaft_front", "cam_hub_roll"),
         ("roll_shaft_front", "bearing_roll_front"), ("roll_shaft_back", "bearing_roll_back"), ("roll_shaft_back", "roll_clutch"),
         ("roll_shaft_back", "magnet_roll"), ("bearing_roll_front", "wall_front"), ("bearing_roll_back", "wall_back"),
         ("roll_shaft_front", "wall_front"), ("roll_shaft_back", "wall_back"), ("stick_tube", "inner_block"), ("stick_tube", "stop_collar"),
         ("cam_hub_roll", "cam_roll"), ("cam_hub_roll", "cradle"), ("pitch_clutch", "cam_pitch"), ("pitch_clutch", "cradle"),
         ("pitch_bracket", "cradle"), ("pitch_shaft", "cradle"), ("magnet_roll", "roll_clutch"), ("roll_clutch", "wall_back"), ("roll_clutch", "sensor_mount_roll"),
         ("roll_spring", "roll_eyebolt")]
for nm in ("L", "R"):
    MATES += [(f"roll_roller_{nm}", f"roll_lever_{nm}"), (f"roll_pivot_{nm}", f"roll_lever_{nm}"), (f"roll_pivot_{nm}", "wall_front"),
              (f"roll_roller_{nm}", "cam_roll"), ("roll_eyebolt", f"roll_lever_{nm}"), ("roll_spring", f"roll_lever_{nm}")]
for nm in ("T", "B"):
    MATES += [(f"pitch_roller_{nm}", f"pitch_lever_{nm}"), (f"pitch_pivot_{nm}", f"pitch_lever_{nm}"), (f"pitch_pivot_{nm}", "pitch_bracket"),
              (f"pitch_roller_{nm}", "cam_pitch"), ("pitch_spring", f"pitch_lever_{nm}"), ("pitch_eyebolt", f"pitch_lever_{nm}")]
MATES += [("pitch_eyebolt", "pitch_spring")]
ALLOW = {frozenset(p) for p in MATES}

def forces():
    angs = list(range(0, TRAVEL + 1))
    tr, _ = cam_torque_curve(rc_pts, [0, math.pi], 11, R_SPRING["k"], R_SPRING["pre"], (R_PIV + R_SPR) / R_PIV, angs)
    tp, _ = cam_torque_curve(pc_pts, [math.pi / 2, -math.pi / 2], 11, P_SPRING["k"], P_SPRING["pre"], (P_PIV + P_SPR) / P_PIV, angs)
    var = {}
    for nm, kf, pf in (("light", 0.5, 0.5), ("default", 1, 1), ("heavy", 2, 1.5)):
        a_, _ = cam_torque_curve(rc_pts, [0, math.pi], 11, R_SPRING["k"] * kf, R_SPRING["pre"] * pf, (R_PIV + R_SPR) / R_PIV, angs)
        b_, _ = cam_torque_curve(pc_pts, [math.pi / 2, -math.pi / 2], 11, P_SPRING["k"] * kf, P_SPRING["pre"] * pf, (P_PIV + P_SPR) / P_PIV, angs)
        var[nm] = dict(k_roll=round(R_SPRING["k"] * kf, 2), k_pitch=round(P_SPRING["k"] * kf, 2), roll_N=[round(t / L_HAND, 1) for t in a_], pitch_N=[round(t / L_HAND, 1) for t in b_])
    return dict(variants=var, angles=angs, roll_N=[round(t / L_HAND, 1) for t in tr], pitch_N=[round(t / L_HAND, 1) for t in tp],
                roll_Nm=[round(t / 1000, 2) for t in tr], pitch_Nm=[round(t / 1000, 2) for t in tp], l_hand=L_HAND,
                note="손 위치 (축에서 L_HAND mm) 에서 필요한 힘 N. 반경 방향 롤러 + 에너지 법 계산 (마찰 · 클러치 제외, 추정)")

if __name__ == "__main__":
    f = forces()
    write_dxf(os.path.join(HERE, "cam_roll.dxf"), [rc_pts, circle_pts(0, 0, 8.2), circle_pts(0, 18, 4.4), circle_pts(0, -18, 4.4)])
    write_dxf(os.path.join(HERE, "cam_pitch.dxf"), [pc_pts, circle_pts(0, 0, 8.2), circle_pts(14, 0, 3.4), circle_pts(-14, 0, 3.4)])
    T = TRAVEL
    poses = [(0, 0), (T, 0), (-T, 0), (0, T), (0, -T), (T, T), (T, -T), (-T, T), (-T, -T)]
    gate = parts.pop("gate_plate")
    res = check_pairs(parts, posed, poses, ALLOW)
    parts["gate_plate"] = gate
    # stop angles: first angle (0.25 deg steps) where the TPU collar touches the gate
    def stop(axis, sg):
        a = 0.0
        while a < 30:
            a += 0.25
            r, p = (sg * a, 0) if axis == "roll" else (0, sg * a)
            try: v = (posed("stop_collar", r, p) & parts["gate_plate"]["shape"]).volume
            except Exception: v = 0
            if v > 0.05: return a
        return None
    stops = dict(roll_L=stop("roll", 1), roll_R=stop("roll", -1), fwd=stop("pitch", 1), aft=stop("pitch", -1))
    # with the gate fitted: anything else touching at the gate stops?
    res_g = check_pairs(parts, posed, [(stops["roll_L"] - 0.5, 0), (0, stops["fwd"] - 0.5), (0, -stops["aft"] + 0.5)], ALLOW | {frozenset(("stop_collar", "gate_plate"))})
    info = export_parts(parts, HERE, dict(pivot=[0, 0, PZ], travel_deg=TRAVEL, gate_deg=GATE, stops_deg=stops, tube_top=TUBE_TOP, l_hand=L_HAND,
                                          printer=[240, 240, 240], roll_roller_y=round(RY, 2), pitch_roller_z=round(PRZ, 2),
                                          springs=dict(roll=R_SPRING, pitch=P_SPRING), lever_ratio=dict(roll=(R_PIV + R_SPR) / R_PIV, pitch=(P_PIV + P_SPR) / P_PIV)),
                        extra=dict(forces=f, check=[dict(pose=p, hits=b) for p, b in res], check_gate=[dict(pose=p, hits=b) for p, b in res_g]))
    for i in info:
        print(f"{i['name']:20s} {i['group']:5s} {i['kind']:5s} {i['size']}  {i['grams'] or ''}")
    for p, b in res: print("pose", p, b if b else "none")
    for p, b in res_g: print("gate pose", p, b if b else "none")
    print("stops", stops, "RY", round(RY, 1), "PRZ", round(PRZ, 1))
    print("roll N", f["roll_N"][::5], "pitch N", f["pitch_N"][::5], "L_HAND", L_HAND)
