"""Centre stick base v3 (cheap, all printed PLA) for the gyro sim chair — cam + roller + spring gimbal (VKB / Virpil style), build123d.

Run:  python stick.py   -> stl/*.stl, cam DXFs (optional metal cams), parts.json (BOM, force curves, strength), interference + stop check

v3 (2026-11-05) vs v2: every printed part PLA (user: no PETG / TPU). Cams printed PLA (2 bolts, swap in 2 min, spares cost
~1000 won), housing = ONE printed box (base + 4 walls) instead of 5 screwed plates (stiffer, the gate loads go wall to wall),
gate plate keyed into the end walls (lips + keys, no load on screws), thrust rings on the roll shaft and a 0.5 mm block-to-
cradle gap so panic loads go into printed faces and not axially through the 608s, TPU stop collar -> PLA sleeve + bought rubber
hose ring, shoulder bolts -> plain M6 bolts (unthreaded shank), eye bolts -> M5 bolt + printed knob, QR seat-post clamp -> printed
cam lever, clutches = felt + spring washer, no rubber boot. Mount: 4 x M6 T-nuts into two 4040 cross bars at x = +-70.

Coordinates (mm): x = forward, y = left, z = up. Origin = centre of the base plate underside. Gimbal centre (0, 0, PZ).
Roll axis = x (outer cradle on 608 bearings in the front/back walls). Pitch axis = y (inner block on 608s in the cradle).
Centring per axis (see ctl_lib.py): printed PLA cam on the axis + 2 roller levers + 1 tension spring across the lever tips,
preload by M5 bolt + printed knurled nut. Stops: swappable gate plate (top cover) + PLA collar with a rubber hose ring on the stick tube.
Damping: dry friction (felt washer + spring washer + nut) on the roll shaft behind the back wall and on the
pitch shaft between cradle and pitch cam. Sensors: AS5600 + diametric magnet at the back roll shaft end and the -y pitch
shaft end. FFB provision: roll shaft sticks out of the front wall (pulley seat + 4 x M4 motor pad), and the inner block has
a stub below the pivot with an M5 cross hole for push rods from fixed motors (both axes, like Brunner-style FFB bases).
"""
import math, os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from build123d import Axis, Plane, Pos, Rot, Cylinder, Box
from ctl_lib import (box, cx, cy, cz, tube, bearing, cam_points, cam_solid, write_dxf, circle_pts, roller_centre_dist,
                     cam_torque_curve, export_parts, check_pairs, auto_fill, shim_pressure)

HERE = os.path.dirname(os.path.abspath(__file__))

# ---------------- parameters ----------------
PZ = 88                       # gimbal centre height above the base underside
TRAVEL = 20                   # mechanism capability (deg, each axis, gate removed)
GATE = dict(roll=10, fwd=10, aft=13)   # default gate (deg): at L_HAND 662 -> roll +-115 mm (F-5E gear-down +-4.0 in), fwd 115 / aft 149 mm
TUBE_TOP = 647                # stick top above the pivot. Base sits ON the cage floor behind the shins (chair v7): long stick like a real fighter
L_HAND = TUBE_TOP - 40 + 55   # pivot -> centre of the hand on the grip (grip frame: palm centre ~55 above the mouth, 추정)
BASE_X, BASE_Y = 94, 96       # base plate half sizes
BASE_T = 6                    # base plate thickness (one printed box with the walls)
WF0, WF1 = 84, 94             # front wall x range (back wall mirrored), 10 thick
SW0, SW1 = 91, 96             # side walls |y| range, 5 thick
GZ = PZ + 76                  # gate plate bottom
GT = 4                        # gate plate thickness (+ 6 mm lips / keys below into the walls)
COLLAR = (PZ + 70, PZ + 100, 36)  # stop collar z0, z1, rubber OD (reaches above the gate top at full tilt)
# roll centring
R_CAM = dict(r0=48, a=28, c=math.radians(2.5), dmax=math.radians(32), r_hub=30, x0=60, t=10)
R_ROLL_X = 65                 # roller (608) centre plane
R_LEV = (72, 78)              # roll lever plate x range
R_PIV, R_SPR = 40, 40         # pivot below / spring above the roller line (lever ratio 2)
R_SPRING = dict(k=5.0, pre=5.0)        # N/mm, mm (default) -> see force table
# pitch centring
P_CAM = dict(r0=34, a=22, c=math.radians(2.5), dmax=math.radians(32), r_hub=24, y1=49, t=8)
P_ROLL_Y = 45
P_LEV = (51, 58)
P_PIV, P_SPR = 30, 32         # pivot at x = -30, spring at x = +32 (ratio ~2)
P_SPRING = dict(k=9.0, pre=4.0)

parts = {}
def part(name, shape, group, kind="print", note="", material="PLA", orient="", fill=0.25):
    """fill = infill fraction; the saved mass fraction adds a 1.2 mm solid shell (ctl_lib.auto_fill)"""
    if kind == "print": fill = auto_fill(shape, fill)
    parts[name] = dict(shape=shape, group=group, kind=kind, note=note, material=material, orient=orient, fill=fill)

# ---------------- cams (laser-cut 6061 aluminium; DXF written below) ----------------
rc_pts = cam_points([0, math.pi], R_CAM["r0"], R_CAM["a"], R_CAM["c"], R_CAM["dmax"], R_CAM["r_hub"])
pc_pts = cam_points([math.pi / 2, -math.pi / 2], P_CAM["r0"], P_CAM["a"], P_CAM["c"], P_CAM["dmax"], P_CAM["r_hub"])
SHIM = 0.5                    # stainless strip 0.5 x 10 glued on each cam flank (4 per cam): printed profile sits SHIM inside the steel surface
rc_pr = cam_points([0, math.pi], R_CAM["r0"] - SHIM, R_CAM["a"], R_CAM["c"], R_CAM["dmax"], R_CAM["r_hub"] - SHIM)
pc_pr = cam_points([math.pi / 2, -math.pi / 2], P_CAM["r0"] - SHIM, P_CAM["a"], P_CAM["c"], P_CAM["dmax"], P_CAM["r_hub"] - SHIM)
RY = roller_centre_dist(rc_pts, 0, 11)          # roll roller centre |y|
PRZ = roller_centre_dist(pc_pts, math.pi / 2, 11)   # pitch roller centre |z| (rel. PZ)
plane_r = Plane(origin=(R_CAM["x0"], 0, PZ), x_dir=(0, 1, 0), z_dir=(1, 0, 0))      # local (u, v) = (y, z)
plane_p = Plane(origin=(0, P_CAM["y1"], PZ), x_dir=(1, 0, 0), z_dir=(0, -1, 0))     # local (u, v) = (x, z)
cam_r = cam_solid(plane_r, rc_pr, R_CAM["t"], bolts=[(0, 18, 4.4), (0, -18, 4.4)] + [(18 * math.cos(a), 18 * math.sin(a), 9) for a in (0.785, 2.356, 3.927, 5.498)])
cam_p = cam_solid(plane_p, pc_pr, P_CAM["t"], bolts=[(14, 0, 3.4), (-14, 0, 3.4)])
part("cam_roll", cam_r, "roll", note="roll 캠 (PLA 출력, 바꿔 끼움): 둥근 V 모양 = 가운데 걸림 없이 또렷한 중심. 0.12 mm 층, 벽 6 줄. M4 ×2 만 풀면 교체. 롤러 닿는 면 4 곳에 스테인리스 띠 0.5×10 을 에폭시로 붙임 (프로필은 0.5 mm 안쪽으로 출력)", orient="눕혀서 (캠 면이 바닥), 층 0.12", fill=0.5)
part("cam_pitch", cam_p, "pitch", note="pitch 캠 (PLA 출력, 바꿔 끼움): D컷 축에 M3 무두볼트 + M3 ×2. 롤러 면 4 곳에 스테인리스 띠 0.5×8", orient="눕혀서, 층 0.12", fill=0.6)

# ---------------- housing (fixed): ONE printed box = base + front / back walls (10 t) + side walls (5 t) ----------------
base = box(-BASE_X, BASE_X, -BASE_Y, BASE_Y, 0, BASE_T)
for x in (-70, 70):
    for y in (-70, 70):
        base -= cz(x, y, -1, BASE_T + 1, 6.5)                  # M6 x4 -> T-nuts in two 4040 cross bars (x = +-70)
base -= box(-40, 40, -40, 40, -1, BASE_T + 1)                  # cable / FFB push-rod opening
for (x, y) in ((-40, 70), (40, 70), (-40, -70), (40, -70)):
    base -= box(x - 18, x + 18, y - 12, y + 12, -1, BASE_T + 1)   # lightening windows between the bolt pads

KEYS = (-46, 46)                                               # gate keys in the end-wall tops (y centres, 12 wide)
def end_wall(s):
    x0, x1 = sorted((s * WF0, s * WF1)); outer = s * WF1
    w = box(x0, x1, -SW1, SW1, BASE_T - 0.5, GZ)
    w -= cx(0, PZ, outer - s * 7.5, outer + s, 22.2)          # 608 pocket from outside (7.5 deep: 0.5 mm axial float -> thrust goes to the ring)
    w -= cx(0, PZ, x0 - 1, x1 + 1, 10)
    w -= box(x0 - 1, x1 + 1, -30, 30, PZ + 40, GZ - 10)       # window above (spring access / weight)
    for y in (-70, 70):
        w -= cz((x0 + x1) / 2, y, GZ - 12, GZ + 1, 5.6)       # M4 heat-set inserts for the gate plate
    for y in KEYS:
        w -= box(x0 - 1, x1 + 1, y - 6, y + 6, GZ - 6, GZ + 1)   # key notches (gate keys bear here sideways = roll stop load)
    if s > 0:
        for y in (-RY, RY):
            w -= cx(y, PZ - R_PIV, x0 - 1, x1 + 1, 5.0)        # M6 tap: roll lever pivots
        for y in (-25, 25):
            for z in (PZ - 25, PZ + 25):
                w -= cx(y, z, x1 - 10, x1 + 1, 3.4)            # FFB motor pad 50 x 50, M4 inserts
    return w

def side_wall(s):
    y0, y1 = sorted((s * SW0, s * SW1))
    w = box(-WF0 - 0.5, WF0 + 0.5, y0, y1, BASE_T - 0.5, GZ)
    w -= box(-55, 55, y0 - 1, y1 + 1, 22, GZ - 14)            # big window: pitch spring adjust (nut at the bottom lever)
    w -= box(66, WF0 + 1, y0 - 1, y1 + 1, PZ + 26, PZ + 58)    # slot: roll lever tip swing + roll preload knob reachable from the side
    return w
housing = base + end_wall(1) + end_wall(-1) + side_wall(1) + side_wall(-1)
part("housing", housing, "fixed", note="짐벌 상자 (PLA 한 덩어리 = 바닥 + 앞뒤 벽 10 t + 옆벽 5 t): 앞뒤 608 2, roll 레버 축, FFB 모터 자리, 아래 M6 ×4 → 4040 T너트",
     orient="바닥을 바닥에 (베어링 구멍은 가로 = 서포트 없이 브리지), 벽 4 줄 + 채움 20 %", fill=0.2)

def gate_opening(roll, fwd, aft, z_top):
    h = z_top - PZ
    w = lambda a: h * math.tan(math.radians(a)) + COLLAR[2] / 2 / math.cos(math.radians(a))
    return w(aft), w(fwd), w(roll)
GA, GF, GR = gate_opening(GATE["roll"], GATE["fwd"], GATE["aft"], GZ + GT)
gate = box(-WF1, WF1, -SW1, SW1, GZ, GZ + GT)
for sx in (1, -1):
    gate += box(sx * (WF0 - 5), sx * (WF0 - 0.2), -60, 60, GZ - 6, GZ)             # lips inside the end walls (pitch stop load -> wall faces)
    for y in KEYS:
        gate += box(sx * WF0 + sx * 0.2, sx * WF1, y - 5.8, y + 5.8, GZ - 6, GZ)  # keys in the end-wall notches (roll stop load)
GCR = 25                      # gate corner radius: diagonal (roll + aft) a bit less than the full corner -> thigh clearance
op = box(-GA + GCR, GF - GCR, -GR, GR, GZ - 1, GZ + 7) + box(-GA, GF, -GR + GCR, GR - GCR, GZ - 1, GZ + 7)
for x in (-GA + GCR, GF - GCR):
    for y in (-GR + GCR, GR - GCR):
        op += cz(x, y, GZ - 1, GZ + 7, 2 * GCR)
gate -= op
for x in (-(WF0 + WF1) / 2, (WF0 + WF1) / 2):
    for y in (-70, 70):
        gate -= cz(x, y, GZ - 1, GZ + 7, 4.5)
part("gate_plate", gate, "fixed", note=f"윗판 = 멈춤 게이트 (PLA, 바꿔 끼움): roll ±{GATE['roll']}°, 앞 {GATE['fwd']}° / 뒤 {GATE['aft']}°. 아래 턱 + 키가 벽에 끼워져 멈춤 힘을 나사가 아니라 벽이 받음", orient="윗면을 바닥에", fill=0.5)

# roll levers + spring (fixed group: pivots on the front wall)
for s, nm in ((1, "L"), (-1, "R")):
    y = s * RY
    lv = box(R_LEV[0], R_LEV[1], y - 7, y + 7, PZ - R_PIV - 8, PZ + R_SPR + 8)
    lv -= cx(y, PZ - R_PIV, R_LEV[0] - 1, R_LEV[1] + 1, 6.3)
    lv -= cx(y, PZ, R_LEV[0] - 1, R_LEV[1] + 1, 8.2)
    lv -= cy((R_LEV[0] + R_LEV[1]) / 2, PZ + R_SPR, y - 8, y + 8, 5.5)
    part(f"roll_lever_{nm}", lv, "fixed", note="roll 롤러 레버: 아래 = 축 (M6 어깨볼트), 가운데 = 608 롤러, 위 = 스프링 (지렛대 2:1)", orient="옆으로 눕혀 (구멍이 위로)", fill=0.6)
    part(f"roll_roller_{nm}", bearing("x", (y, PZ), R_ROLL_X - 3.5, R_ROLL_X + 3.5), "fixed", kind="buy", material="steel", note="608ZZ 롤러 (캠을 누름)")
    part(f"roll_pivot_{nm}", cx(y, PZ - R_PIV, R_LEV[0] - 2, WF0 + 10, 6), "fixed", kind="buy", material="steel", note="M6 볼트 (나사산 없는 목 부분 = 레버 축)")
xs = (R_LEV[0] + R_LEV[1]) / 2
part("roll_spring", cy(xs, PZ + R_SPR, -RY + 8, RY - 22, 8), "fixed", kind="buy", material="steel",
     note=f"roll 인장 스프링 (기본 k ≈ {R_SPRING['k']} N/mm, OD 8, 추정). 바꿔 끼워 무게감 조절")
part("roll_eyebolt", cy(xs, PZ + R_SPR, RY - 24, RY + 14, 5) + cy(xs, PZ + R_SPR, RY + 7, RY + 13, 14), "fixed", kind="buy", material="steel",
     note="M5 볼트 (출력 고리) + 출력 손잡이 너트 = roll 예압 (가운데 힘) 조절. 안 쓸 때는 풀어 둠 (PLA 캠 눌림 방지)")

# back: dry clutch + roll sensor
part("roll_clutch", tube("x", (0, PZ), -WF1 - 7, -WF1, 26, 8.2), "roll", kind="buy", material="felt",
     note="roll 마찰: 펠트 와셔 + 스프링 와셔 + 나일록 너트 (조이면 묵직, 약하게만)")
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
part("cradle", cr, "roll", note="바깥 요람 (roll 로 돎): 앞뒤 Ø8 축 + pitch 608 베어링 2. 위가 뚫려 스틱이 지나감", orient="바닥 쪽을 바닥에, 채움 60 % + 벽 5 줄", fill=0.3)
part("cam_hub_roll", tube("x", (0, PZ), 52, R_CAM["x0"], 30, 8.2) - cx(18, PZ, 51, 61, 4.4) - cx(-18, PZ, 51, 61, 4.4), "roll",
     note="roll 캠 받침 (요람 앞면 ↔ 캠, M4 ×2 로 같이 조임 → 캠이 축이 아니라 요람에 고정)", fill=0.6)
for s, nm in ((1, "front"), (-1, "back")):
    o = s * WF1
    part(f"bearing_roll_{nm}", bearing("x", (0, PZ), o - s * 7, o), "fixed", kind="buy", material="steel", note="608-2RS (roll 축)")
part("roll_shaft_front", cx(0, PZ, 40, WF1 + 18, 8), "roll", kind="buy", material="steel", note="Ø8 h6 연마봉 70 mm (앞, 끝 18 mm = FFB 풀리 자리)")
part("roll_shaft_back", cx(0, PZ, -WF1 - 8, -40, 8), "roll", kind="buy", material="steel", note="Ø8 h6 연마봉 62 mm (뒤, 끝에 자석)")
part("thrust_front", tube("x", (0, PZ), R_CAM["x0"] + R_CAM["t"] + 0.3, WF0 - 0.3, 40, 8.3), "roll", fill=1.0,
     note="앞 밀림 받침 링 Ø40 (PLA): 평소 0.3 mm 떠 있고, 손으로 세게 밀면 벽 면에 닿아 힘을 벽이 받음 (608 축방향 보호)", orient="눕혀서")
part("thrust_back", tube("x", (0, PZ), -WF0 + 0.3, -WF0 + 4, 40, 8.3) + tube("x", (0, PZ), -WF0 + 3, -52.3, 16, 8.3), "roll", fill=0.4,
     note="뒤 밀림 받침 링 Ø40 (PLA): 요람 뒤면 ↔ 뒤벽 사이 0.3 mm", orient="세워서")
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
part("pitch_bracket", pb, "roll", note="pitch 센터링 받침 (요람 옆에 M3 ×3, 같이 roll 로 돎)", orient="큰 면을 바닥에", fill=0.35)
for sz, nm in ((1, "T"), (-1, "B")):
    z = PZ + sz * PRZ
    lv = box(-P_PIV - 8, P_SPR + 8, P_LEV[0], P_LEV[1], z - 7, z + 7)
    lv -= cy(-P_PIV, z, P_LEV[0] - 1, P_LEV[1] + 1, 6.3)
    lv -= cy(0, z, P_LEV[0] - 1, P_LEV[1] + 1, 8.2)
    lv -= cz(P_SPR, (P_LEV[0] + P_LEV[1]) / 2, z - 8, z + 8, 5.5)
    part(f"pitch_lever_{nm}", lv, "roll", note="pitch 롤러 레버 (지렛대 2:1)", orient="옆으로 눕혀", fill=0.6)
    part(f"pitch_roller_{nm}", bearing("y", (0, z), P_ROLL_Y - 3.5, P_ROLL_Y + 3.5), "roll", kind="buy", material="steel", note="608ZZ 롤러")
    part(f"pitch_pivot_{nm}", cy(-P_PIV, z, P_LEV[0] - 2, 62, 6), "roll", kind="buy", material="steel", note="M6 어깨볼트")
ys_ = (P_LEV[0] + P_LEV[1]) / 2
part("pitch_spring", cz(P_SPR, ys_, PZ - PRZ + 22, PZ + PRZ - 8, 10), "roll", kind="buy", material="steel",
     note=f"pitch 인장 스프링 (기본 k ≈ {P_SPRING['k']} N/mm, OD 10, 추정)")
part("pitch_eyebolt", cz(P_SPR, ys_, PZ - PRZ - 14, PZ - PRZ + 24, 5) + cz(P_SPR, ys_, PZ - PRZ - 13, PZ - PRZ - 7, 14), "roll", kind="buy", material="steel",
     note="M5 볼트 + 출력 손잡이 너트 (아래 레버) = pitch 예압 조절, 옆창으로 손이 닿음. 안 쓸 때 풀어 둠")
part("pitch_clutch", tube("y", (0, PZ), 36, 40.5, 24, 8.2), "pitch", kind="buy", material="felt", note="pitch 마찰 (요람 ↔ 캠 사이 펠트 + 스프링 와셔)")
# pitch sensor (-y)
ps = box(-22, 22, -52, -49, PZ - 22, PZ + 22) + box(-22, -16, -52, -35, PZ - 22, PZ - 16) + box(16, 22, -52, -35, PZ - 22, PZ - 16)
ps -= cy(0, PZ, -53, -48, 6)
part("sensor_mount_pitch", ps, "roll", note="pitch AS5600 받침 (요람 −y 옆)")
part("as5600_pitch", box(-11.5, 11.5, -48.6, -47, PZ - 11.5, PZ + 11.5), "roll", kind="buy", material="PCB", note="AS5600 (pitch)")
part("magnet_pitch", cy(0, PZ, -46, -42.5, 8), "pitch", kind="buy", material="NdFeB", note="자석 Ø6×2.5 + 축 끝 컵")

# ---------------- inner block + tube (pitch group) ----------------
ib = box(-16, 16, -24.5, 24.5, PZ - 22, PZ + 22) + cz(0, 0, PZ + 10, PZ + 60, 40)   # 0.5 mm to the cradle: roll panic load -> cradle face, not the 608s
ib += box(-32, -18, -9, 9, PZ + 28, PZ + 58)                   # clamp ears
ib += cz(0, 0, PZ - 50, PZ - 20, 16)                           # FFB / damper stub below the pivot
ib -= cy(0, PZ, -25, 25, 8.1)
for x in (-8, 8):
    ib -= cz(x, 10, PZ, PZ + 23, 3.3)                          # M4 set screws onto the D-flat
ib -= cz(0, 0, PZ + 6, PZ + 61, 25.2)                          # Ø25 tube socket 55 deep
ib -= box(-33, -10, -1, 1, PZ + 24, PZ + 61)                    # clamp slit
for z in (PZ + 36, PZ + 51):
    ib -= cy(-26, z, -10, 10, 5.5)
ib -= cz(0, 0, PZ - 51, PZ - 22, 6)                            # cable from the grip goes down the tube and out here
ib -= cy(0, PZ - 43, -9, 9, 5.5)                               # M5 cross hole (push-rod eye)
part("inner_block", ib, "pitch", note="안쪽 블록 (pitch 로 돎): Ø25 관 소켓 55 mm + 퀵릴리즈 클램프 (M5 + 출력 캠 레버), 아래 = FFB 막대 고리 / 배선 출구", orient="소켓을 위로, 채움 100 %", fill=0.5)
ql = box(-40, -20, 9.5, 13.5, PZ + 34, PZ + 58) - cy(-26, PZ + 36, 9, 14, 5.5) - cy(-26, PZ + 51, 9, 14, 5.5)
part("qr_lever", ql, "pitch", note="퀵릴리즈 캠 레버 (PLA): M5 볼트 2 개를 한 번에 조이는 판 + 레버 → 관 뽑고 탈 때", orient="눕혀서", fill=0.6)
part("pitch_shaft", cy(0, PZ, -46, P_CAM["y1"] + 1, 8), "pitch", kind="buy", material="steel", note="Ø8 h6 연마봉 96 mm, D컷 (블록 + 캠 고정)")
part("stick_tube", tube("z", (0, 0), PZ + 6, PZ + TUBE_TOP - 80, 25, 20), "pitch", kind="buy", material="AL6061",
     note=f"아래 관: 알루미늄 Ø25×2.5t (속 Ø20), 길이 {TUBE_TOP - 86} mm. 퀵릴리즈 클램프로 소켓에 → 탈 때 뽑음. 100 N 에 끝 처짐 약 12 mm (Ø20 하나면 30 mm)")
part("grip_tube", tube("z", (0, 0), PZ + TUBE_TOP - 140, PZ + TUBE_TOP, 20, 16), "pitch", kind="buy", material="AL6061",
     note="위 관 (손잡이 규격): Ø20×2t, 140 mm. 아래 60 mm 가 Ø25 관 속 (M5 가로볼트), 위 40 mm 가 손잡이 속 (M4 가로볼트, 뒤쪽 4×6 홈)")
sc_ = tube("z", (0, 0), COLLAR[0], COLLAR[1], 30, 25.2) + tube("z", (0, 0), COLLAR[0], COLLAR[0] + 2, 34, 25.2) + tube("z", (0, 0), COLLAR[1] - 2, COLLAR[1], 34, 25.2)
part("stop_collar", sc_, "pitch", note="멈춤 링 속 (PLA): 고무 호스 토막을 끼우는 테 + M3 무두볼트로 관에 고정", orient="그대로", fill=0.6)
part("stop_rubber", tube("z", (0, 0), COLLAR[0] + 2, COLLAR[1] - 2, COLLAR[2], 30), "pitch", kind="buy", material="rubber",
     note="고무 호스 토막 내경 30 외경 36 × 26 (산 부품) = TPU 대신 완충. 게이트에 닿아 부드럽게 멈춤")

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
         ("roll_shaft_back", "magnet_roll"), ("bearing_roll_front", "housing"), ("bearing_roll_back", "housing"),
         ("roll_shaft_front", "housing"), ("roll_shaft_back", "housing"), ("stick_tube", "inner_block"), ("stick_tube", "stop_collar"), ("stick_tube", "grip_tube"), ("stop_collar", "stop_rubber"),
         ("qr_lever", "inner_block"), ("thrust_front", "roll_shaft_front"), ("thrust_back", "roll_shaft_back"),
         ("cam_hub_roll", "cam_roll"), ("cam_hub_roll", "cradle"), ("pitch_clutch", "cam_pitch"), ("pitch_clutch", "cradle"),
         ("pitch_bracket", "cradle"), ("pitch_shaft", "cradle"), ("magnet_roll", "roll_clutch"), ("roll_clutch", "housing"), ("roll_clutch", "sensor_mount_roll"), ("sensor_mount_roll", "housing"),
         ("roll_spring", "roll_eyebolt")]
for nm in ("L", "R"):
    MATES += [(f"roll_roller_{nm}", f"roll_lever_{nm}"), (f"roll_pivot_{nm}", f"roll_lever_{nm}"), (f"roll_pivot_{nm}", "housing"),
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

def strength():
    """Panic load 200 N at the hand with the stick on the gate (pitch or roll), plus sustained (creep) loads from the spring
    preload. Hand calcs, conservative, every number 추정."""
    from ctl_lib import PLA_MECH as M, C0_608, hertz_line, sf
    F = 200.0
    hc = GZ + GT / 2 - PZ                                  # collar contact height above the pivot (mid gate plate)
    Fg = F * L_HAND / hc; Rp = Fg - F                 # gate force on the collar, pivot reaction
    out = dict(F_hand=F, gate_force=round(Fg), pivot_force=round(Rp))
    rows = []
    rows.append(sf("게이트 가장자리 눌림 (고무 링 접촉 20 mm × 판 4 t)", Fg / (20 * GT), M["comp"], note="판을 눕혀 출력 → 층 방향 안"))
    rows.append(sf("게이트 키 4 개 옆 눌림 (roll, 6×11.6 mm²)", Fg / (4 * 6 * 11.6), M["comp"]))
    a = 78.0; r0 = 20.0; t = WF1 - WF0                # end wall ~ clamped plate radius a, load ring r0 (thrust ring)
    sw = 3 * Rp * (1 + M["nu"]) / (2 * math.pi * t * t) * math.log(a / r0)
    rows.append(sf("앞/뒤벽 판 굽힘 (밀림 링 Ø40 → 10 t 벽, 4 변 고정 판)", sw, M["z"], note="벽이 세워 출력 → 층 사이 강도 20 MPa 로 봄"))
    I_box = 2 * (2 * SW1) * t * (WF0 + t / 2) ** 2 + 2 * (SW1 - SW0) * (2 * WF0) ** 3 / 12
    rows.append(sf("상자 뿌리 굽힘 (바닥 ↔ 벽 이음, 상자 단면)", F * L_HAND / (I_box / WF1), M["z"]))
    rows.append(sf("608 정격 (pivot 힘 / 2 개)", Rp / 2, C0_608, unit="N", note="정적 정격 C0 = 영구 눌림 시작 (깨짐 아님)"))
    Zs = math.pi * 8 ** 3 / 32; Ms = Rp * (2 * 63 - 49) / 8
    rows.append(sf("pitch 축 Ø8 굽힘 (블록 폭에 고른 하중)", Ms / Zs, 500, note="연마봉 항복 약 500 MPa (추정)"))
    Mc = Rp * (2 * 92 - 49) / 8; Zc = 44 * 10 ** 2 / 6
    rows.append(sf("요람 옆판 굽힘 (roll, 블록이 면으로 밂)", Mc / Zc, M["xy"], note="요람 바닥을 바닥에 출력 → 굽힘 응력은 층 안"))
    Mb = F * (L_HAND - 22) - Fg * (hc - 22); Zb = math.pi * (40 ** 4 - 25.2 ** 4) / (32 * 40)
    rows.append(sf("안쪽 블록 소켓 뿌리 굽힘 (관 몫 무시)", Mb / Zb, M["z"], note="소켓을 위로 출력 → 층 사이"))
    Zt = math.pi * (25 ** 4 - 20 ** 4) / (32 * 25)
    rows.append(sf("알루미늄 관 Ø25×2.5 굽힘 (멈춤 링 위)", F * (L_HAND - hc) / Zt, 170, note="6063-T5 항복 약 170 (6061-T6 이면 240)"))
    rows.append(sf("M6 T너트 볼트 인장 (상자 → 4040)", F * L_HAND / 140 / 2 / 1000, 11.6, unit="kN", note="8.8 볼트 보증 하중"))
    def lift_force(pts, fol, k, pre, ratio, a):
        lift = sum(roller_centre_dist(pts, f_ - math.radians(a), 11) - roller_centre_dist(pts, f_, 11) for f_ in fol)
        return k * (pre + ratio * lift) * ratio
    rr, pr = (R_PIV + R_SPR) / R_PIV, (P_PIV + P_SPR) / P_PIV
    Fr_roll = R_SPRING["k"] * R_SPRING["pre"] * rr
    Fr_pitch = P_SPRING["k"] * P_SPRING["pre"] * pr
    Fr_roll_g = lift_force(rc_pts, [0, math.pi], R_SPRING["k"], R_SPRING["pre"], rr, GATE["roll"])
    Fr_pitch_g = lift_force(pc_pts, [math.pi / 2, -math.pi / 2], P_SPRING["k"], P_SPRING["pre"], pr, GATE["aft"])
    climit = 3.3 * M["creep"]
    creep = [sf("roll 캠 접촉압 (가운데, 예압만 = 계속)", hertz_line(Fr_roll, 7, 11), climit, note="국부 접촉 허용 ~33 MPa 로 봄 (추정). 넘으면 롤러 자리 눌림 → 가운데 홈"),
             sf("pitch 캠 접촉압 (가운데, 예압만 = 계속)", hertz_line(Fr_pitch, 7, 11), climit),
             sf("roll 캠 접촉압 (게이트 끝, 순간)", hertz_line(Fr_roll_g, 7, 11), M["comp"]),
             sf("pitch 캠 접촉압 (뒤 게이트 끝, 순간)", hertz_line(Fr_pitch_g, 7, 11), M["comp"]),
             sf("roll 레버 굽힘 (예압, 계속)", R_SPRING["k"] * R_SPRING["pre"] * R_SPR / (6 * 14 ** 2 / 6), M["creep"]),
             sf("pitch 레버 굽힘 (예압, 계속)", P_SPRING["k"] * P_SPRING["pre"] * P_SPR / (7 * 14 ** 2 / 6), M["creep"])]
    for nm_, Fx, b_ in (("roll 캠 + 띠 0.5×10: PLA 받침 압력 (게이트 끝)", Fr_roll_g, 10), ("pitch 캠 + 띠 0.5×8: PLA 받침 압력 (뒤 게이트 끝)", Fr_pitch_g, 8)):
        pf, ss = shim_pressure(Fx, b_, SHIM)
        creep.append(sf(nm_, pf, M["comp"], note=f"띠 굽힘 {ss:.0f} MPa (스테인리스 301/304 반경질 항복 ~1000, 추정)"))
    for nm_, Fx, b_ in (("roll 캠 + 띠: PLA 받침 압력 (가운데, 계속)", Fr_roll, 10), ("pitch 캠 + 띠: PLA 받침 압력 (가운데, 계속)", Fr_pitch, 8)):
        creep.append(sf(nm_, shim_pressure(Fx, b_, SHIM)[0], M["creep"]))
    out.update(rows=rows, creep=creep, roller_force=dict(roll=round(Fr_roll), pitch=round(Fr_pitch), roll_gate=round(Fr_roll_g), pitch_gate=round(Fr_pitch_g)),
               shim_mm=SHIM, note="캠 접촉 위 4 줄 = 띠 없는 PLA 캠 (참고). 손 200 N 을 게이트에 댄 채 (pitch 또는 roll). PLA 층 안 50 / 층 사이 20 / 압축 60 MPa, 계속 하중 10 MPa 이하 (추정). 캠 접촉은 롤러 1 줄이 다 받는다고 봄 (실제는 V 양쪽 2 줄 → 더 낮음)")
    return out

if __name__ == "__main__":
    f = forces()
    stg = strength()
    write_dxf(os.path.join(HERE, "cam_roll.dxf"), [rc_pts, circle_pts(0, 0, 8.2), circle_pts(0, 18, 4.4), circle_pts(0, -18, 4.4)])
    write_dxf(os.path.join(HERE, "cam_pitch.dxf"), [pc_pts, circle_pts(0, 0, 8.2), circle_pts(14, 0, 3.4), circle_pts(-14, 0, 3.4)])
    T = TRAVEL
    poses = [(0, 0), (T, 0), (-T, 0), (0, T), (0, -T), (T, T), (T, -T), (-T, T), (-T, -T)]
    gate = parts.pop("gate_plate")
    res = check_pairs(parts, posed, poses, ALLOW)
    parts["gate_plate"] = gate
    # stop angles: first angle (0.25 deg steps) where the rubber ring touches the gate
    def stop(axis, sg):
        a = 0.0
        while a < 30:
            a += 0.25
            r, p = (sg * a, 0) if axis == "roll" else (0, sg * a)
            try: v = (posed("stop_rubber", r, p) & parts["gate_plate"]["shape"]).volume
            except Exception: v = 0
            if v > 0.05: return a
        return None
    stops = dict(roll_L=stop("roll", 1), roll_R=stop("roll", -1), fwd=stop("pitch", 1), aft=stop("pitch", -1))
    # with the gate fitted: anything else touching at the gate stops?
    res_g = check_pairs(parts, posed, [(stops["roll_L"] - 0.5, 0), (0, stops["fwd"] - 0.5), (0, -stops["aft"] + 0.5)], ALLOW | {frozenset(("stop_rubber", "gate_plate"))})
    info = export_parts(parts, HERE, dict(pivot=[0, 0, PZ], travel_deg=TRAVEL, gate_deg=GATE, stops_deg=stops, tube_top=TUBE_TOP, l_hand=L_HAND,
                                          printer=[240, 240, 240], roll_roller_y=round(RY, 2), pitch_roller_z=round(PRZ, 2),
                                          springs=dict(roll=R_SPRING, pitch=P_SPRING), lever_ratio=dict(roll=(R_PIV + R_SPR) / R_PIV, pitch=(P_PIV + P_SPR) / P_PIV)),
                        extra=dict(forces=f, strength=stg, check=[dict(pose=p, hits=b) for p, b in res], check_gate=[dict(pose=p, hits=b) for p, b in res_g]))
    for i in info:
        print(f"{i['name']:20s} {i['group']:5s} {i['kind']:5s} {i['size']}  {i['grams'] or ''}")
    for p, b in res: print("pose", p, b if b else "none")
    for p, b in res_g: print("gate pose", p, b if b else "none")
    print("stops", stops, "RY", round(RY, 1), "PRZ", round(PRZ, 1))
    print("roll N", f["roll_N"][::5], "pitch N", f["pitch_N"][::5], "L_HAND", L_HAND)
    for r in stg["rows"] + stg["creep"]: print(f"SF {r['sf']:6.2f}  {r['load']:8.2f}/{r['limit']} {r['unit']}  {r['name']}")
    print("grams", round(sum(i["grams"] or 0 for i in info)), stg["roller_force"])
