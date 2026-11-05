"""Throttle v2 for the gyro sim chair (left hand, left rail) — build123d.

Run:  python throttle.py   -> stl/*.stl, parts.json (BOM, detent map), interference check over the lever range

Coordinates (mm): x = forward (push = more thrust), y = left, z = up. Origin = centre of the base underside.
Pivot axis along y at (0, PZ). Lever = the Ø20 aluminium grip tube itself: it slides 8 mm along its own axis in two
plain bushings in the hub. A spring pulls it down (rest). Its lower end carries a cross pin that runs past a fixed gate
plate below the hub. Gate teeth block the pin at IDLE -> CUTOFF and MIL -> AB: LIFT the grip 8 mm to pass (F-16 style
lift-over, research notes). Friction: brake shoe (cork) pressed on the hub by a knob screw through a wave spring.
Sensor: AS5600 at the +y stub shaft end. Split stub shafts so the tube can pass through the hub centre.
"""
import math, os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from build123d import Axis, Pos, Rot, Box, Cylinder
from ctl_lib import box, cx, cy, cz, tube, bearing, export_parts, check_pairs

HERE = os.path.dirname(os.path.abspath(__file__))

PZ = 95                      # pivot height
L_HAND = 170                 # pivot -> palm centre
TUBE_TOP = L_HAND - 55 + 40  # grip socket mouth = TUBE_TOP - 40
RHO = 60                     # gate pin radius below the pivot at rest
LIFT = 8                     # lift to pass a gate
HUB_R, HUB_W = 30, 56
WY0, WY1 = 30, 38            # side walls |y|
DET = dict(cutoff=-33, idle=-25, mil=18, max=30)    # lever angles (deg, + = forward). 63 deg total, ~187 mm arc at the hand (추정 F-16 급)
GP = (13, 19)                # gate plate y range (+y side of the tube)
PIN_Y = (8, 21)

parts = {}
def part(name, shape, group, kind="print", note="", material="PLA", orient="", fill=0.55):
    parts[name] = dict(shape=shape, group=group, kind=kind, note=note, material=material, orient=orient, fill=fill)

def arc_xz(r0, r1, a0, a1, y0, y1, step=2.0):
    """annular sector in the x-z plane around the pivot; angles = lever angle convention of the LOWER end
    (lever angle th -> lower end at x = -r sin th, z = PZ - r cos th)."""
    s = None
    n = max(1, int(abs(a1 - a0) / step))
    for i in range(n):
        t0 = a0 + (a1 - a0) * i / n; t1 = a0 + (a1 - a0) * (i + 1) / n; tm = math.radians((t0 + t1) / 2)
        w = (r0 + r1) / 2 * math.radians(abs(t1 - t0)) + 0.15
        rm = (r0 + r1) / 2
        b = Pos(-rm * math.sin(tm), (y0 + y1) / 2, PZ - rm * math.cos(tm)) * Rot(0, math.degrees(tm), 0) * Box(w, y1 - y0, r1 - r0)
        s = b if s is None else s + b
    return s

# ---------------- fixed ----------------
base = box(-75, 95, -45, 45, 0, 6)
for x in (-60, 80):
    for y in (-32, 32):
        base -= cz(x, y, -1, 7, 6.5)
for x in (-35, 35):
    for s in (1, -1):
        base -= cz(x, s * (WY0 + WY1) / 2, -1, 7, 3.4)
part("base_plate", base, "fixed", note="바닥판 170×90: M6 ×4 로 의자 왼쪽 스로틀 선반에", orient="그대로")
def wall(s):
    y0, y1 = sorted((s * WY0, s * WY1)); o = s * WY1
    w = box(-55, 55, y0, y1, 6, PZ + 22)
    w -= cy(0, PZ, o - s * 7, o + s, 22.2)
    w -= cy(0, PZ, y0 - 1, y1 + 1, 10)
    for x in (-35, 35):
        w -= cz(x, (y0 + y1) / 2, 5, 20, 2.8)
    return w
part("wall_L", wall(1), "fixed", note="옆벽 (왼쪽, +y): 608 베어링, 바깥에 AS5600", orient="옆면을 바닥에", fill=0.6)
part("wall_R", wall(-1), "fixed", note="옆벽 (오른쪽, −y): 608 베어링", orient="옆면을 바닥에", fill=0.6)
for s, nm in ((1, "L"), (-1, "R")):
    part(f"bearing_{nm}", bearing("y", (0, PZ), s * (WY1 - 7), s * WY1), "fixed", kind="buy", material="steel", note="608-2RS")

# gate plate: arc r 40..64 under the hub, teeth at idle/cutoff and mil/ab, end walls = lever stops
th_pin = math.degrees(math.asin(2.6 / RHO))        # pin half-angle at RHO (Ø5 pin)
gp = arc_xz(38, 46, DET["cutoff"] - 8, DET["max"] + 8, *GP)
for a0, a1 in ((DET["cutoff"] - 8, DET["cutoff"] - th_pin - 0.7), (DET["max"] + th_pin + 0.7, DET["max"] + 8)):
    gp += arc_xz(46, 70, a0, a1, *GP, step=1)                          # end stops (no lift past them)
for a0, a1 in (((DET["cutoff"] + DET["idle"]) / 2 - 1, (DET["cutoff"] + DET["idle"]) / 2 + 1), (DET["mil"] + th_pin + 1.5, DET["mil"] + th_pin + 3.5)):
    gp += arc_xz(55, 70, a0, a1, *GP, step=0.5)                        # lift-over teeth
for sx in (1, -1):                                                     # legs down to the foot, outside the swept cone
    gp += box(sx * 42, sx * 54, GP[0], GP[1], 6, PZ - 30)
gp += box(-54, 54, GP[0], GP[1], 6, 14)
gp -= cy(-48, 10, GP[0] - 1, GP[1] + 1, 3.4); gp -= cy(48, 10, GP[0] - 1, GP[1] + 1, 3.4)
part("gate_plate", gp, "fixed", material="PETG", note="게이트판: 이빨 2 개 = 아이들→컷오프, MIL→AB 는 손잡이를 8 mm 들어야 넘어감. 양 끝 = 멈춤. 바꿔 끼워 위치 조절", orient="옆면을 바닥에, 채움 100 %", fill=1.0)

# friction block (rear): knob screw -> wave spring -> cork shoe on the hub
fb = box(-HUB_R - 32, -HUB_R - 10, -12, 12, 6, PZ + 16) + box(-HUB_R - 10, -HUB_R - 1, -12, 12, PZ - 14, PZ + 14)
fb -= cx(0, PZ, -HUB_R - 33, -HUB_R, 6.4)
fb -= box(-HUB_R - 9, -HUB_R - 0.5, -10.5, 10.5, PZ - 11.5, PZ + 11.5)      # shoe pocket
for y in (-7, 7):
    fb -= cz(-HUB_R - 21, y, 5, 20, 2.8)                        # M3 from the base
part("friction_block", fb, "fixed", note="마찰 블록: 손잡이 나사 → 웨이브 스프링 → 코르크 패드가 허브를 누름 (레버가 놓은 자리에 머묾)", orient="바닥면을 바닥에", fill=0.8)
part("friction_shoe", box(-HUB_R - 8, -HUB_R - 0.5, -10, 10, PZ - 11, PZ + 11) - cy(0, PZ, -14, 14, 2 * HUB_R + 1), "fixed", material="PETG",
     note="마찰 패드 받침 (앞면에 코르크 2 mm 접착)", fill=1.0)
part("friction_knob", cx(0, PZ, -HUB_R - 62, -HUB_R - 8, 6) + cx(0, PZ, -HUB_R - 66, -HUB_R - 54, 26), "fixed", kind="buy", material="steel",
     note="M6 손잡이 나사 (별 손잡이) + 웨이브 스프링")
# sensor
sm = box(-20, 20, WY1 + 12, WY1 + 15, PZ - 20, PZ + 20) + box(-20, -14, WY1, WY1 + 15, PZ - 20, PZ + 20) + box(14, 20, WY1, WY1 + 15, PZ - 20, PZ + 20)
part("sensor_mount", sm, "fixed", note="AS5600 받침 (왼쪽 벽 바깥)")
part("as5600", box(-11.5, 11.5, WY1 + 10.4, WY1 + 12, PZ - 11.5, PZ + 11.5), "fixed", kind="buy", material="PCB", note="AS5600 (스로틀 각도 → 컷오프 / 아이들 / MIL / AB 는 각도로 판별)")
bay = box(58, 93, -40, 40, 6, 46) - box(60, 91, -38, 38, 8, 47)
part("electronics_bay", bay, "fixed", note="전자 상자: Pro Micro + TCA9548A (모든 조종기 센서가 여기로), USB 1 개", orient="바닥을 바닥에")
part("bay_lid", box(58, 93, -40, 40, 46, 49), "fixed", note="전자 상자 뚜껑")

# ---------------- lever group ----------------
hub = cy(0, PZ, -HUB_W / 2, HUB_W / 2, 2 * HUB_R)
hub -= cz(0, 0, PZ - HUB_R - 1, PZ + HUB_R + 1, 23.2)          # bushing bore (2 x igus JFM-2023-15)
for s in (1, -1):
    hub -= cy(0, PZ, s * 18, s * (HUB_W / 2 + 1), 8.1)         # stub shaft seats
    hub -= cx(s * 23, PZ + 14, -6, 6, 3.4)                    # M4 pinch screws onto the stubs
hub -= cy(0, PZ, -HUB_W / 2 - 1, -HUB_W / 2 + 0.01, 1)
part("hub", hub, "lever", material="PETG", note="허브 Ø60: 플라스틱 부싱 2 개로 Ø20 관이 위아래로 8 mm 미끄러짐, 양옆 Ø8 짧은 축", orient="축 방향으로 세워, 채움 100 %", fill=1.0)
for s, nm in ((1, "L"), (-1, "R")):
    part(f"stub_{nm}", cy(0, PZ, s * 18, s * (WY1 + (9 if s > 0 else 1)), 8), "lever", kind="buy", material="steel", note="Ø8 h6 짧은 축 (M4 조임)")
part("bushings", tube("z", (0, 0), PZ - HUB_R, PZ + HUB_R, 23, 20.05), "lever", kind="buy", material="igus", note="igus JFM-2023-15 플랜지 부싱 ×2 (또는 LM20UU 짧은 것)")
part("magnet", cy(0, PZ, WY1 + 6, WY1 + 9.5, 8), "lever", kind="buy", material="NdFeB", note="자석 Ø6×2.5 직경 방향")

# sliding group (moves with the lever + LIFT along the tube axis)
part("lever_tube", tube("z", (0, 0), PZ - RHO - 6, PZ + TUBE_TOP, 20, 16), "slide", kind="buy", material="AL6061",
     note=f"알루미늄 관 Ø20×2t, {TUBE_TOP + RHO + 6} mm = 레버. 위 40 mm 가 손잡이 속 (M4 가로볼트 + 뒤 4×6 홈), 아래 끝에 게이트 핀")
part("rest_collar", tube("z", (0, 0), PZ + HUB_R, PZ + HUB_R + 10, 32, 20.2), "slide", material="PETG", note="멈춤 고리 (허브 위에 얹혀 내려가는 끝), M4 무두볼트", fill=1.0)
part("lift_spring", tube("z", (0, 0), PZ - 50, PZ - HUB_R, 25, 21), "slide", kind="buy", material="steel", note="압축 스프링 ID 21 · OD 25 · 자유길이 25 (들어 올리는 힘 약 15~25 N, 추정)")
part("spring_collar", tube("z", (0, 0), PZ - 56, PZ - 50, 26, 20.2), "slide", material="PETG", note="스프링 받침 고리 (관 아래 끝)", fill=1.0)
part("gate_pin", cy(0, PZ - RHO, PIN_Y[0], PIN_Y[1], 5), "slide", kind="buy", material="steel", note="게이트 핀 M5 (관을 가로질러, +y 로 튀어나옴)")

def posed(name, ang, lift=0):
    s = parts[name]["shape"]; g = parts[name]["group"]
    if g == "slide" and lift: s = Pos(0, 0, lift) * s
    if g in ("lever", "slide") and ang: s = s.rotate(Axis((0, 0, PZ), (0, 1, 0)), ang)   # + = top forward
    return s

MATES = [("hub", "stub_L"), ("hub", "stub_R"), ("stub_L", "bearing_L"), ("stub_R", "bearing_R"), ("bearing_L", "wall_L"), ("bearing_R", "wall_R"),
         ("stub_L", "wall_L"), ("stub_R", "wall_R"), ("stub_L", "magnet"), ("hub", "bushings"), ("lever_tube", "bushings"), ("lever_tube", "rest_collar"),
         ("lever_tube", "spring_collar"), ("lever_tube", "gate_pin"), ("lever_tube", "lift_spring"), ("lift_spring", "spring_collar"), ("lift_spring", "hub"),
         ("rest_collar", "hub"), ("friction_shoe", "friction_block"), ("friction_knob", "friction_block"), ("friction_shoe", "friction_knob"),
         ("friction_shoe", "hub"), ("bay_lid", "electronics_bay"), ("magnet", "sensor_mount"), ("lift_spring", "bushings"), ("rest_collar", "bushings"), ("spring_collar", "lift_spring")]
ALLOW = {frozenset(p) for p in MATES}

if __name__ == "__main__":
    # lever range without lift: free between idle and mil, blocked by the teeth outside
    res = check_pairs(parts, posed, [(a, 0) for a in (DET["idle"], 0, DET["mil"])], ALLOW)
    res += check_pairs(parts, posed, [(a, LIFT) for a in (DET["cutoff"], DET["idle"] - 3, DET["mil"] + 3, DET["max"])], ALLOW)
    # gate behaviour: pin vs gate plate, lifted / not lifted, sweep 1 deg
    sweep = []
    for a in range(DET["cutoff"] - 2, DET["max"] + 3):
        hit0 = (posed("gate_pin", a, 0) & parts["gate_plate"]["shape"]).volume > 0.05
        hitL = (posed("gate_pin", a, LIFT) & parts["gate_plate"]["shape"]).volume > 0.05
        sweep.append((a, hit0, hitL))
    print("gate sweep (angle, blocked at rest, blocked lifted):")
    print(" ".join(f"{a}:{'X' if h0 else '.'}{'X' if hl else '.'}" for a, h0, hl in sweep))
    info = export_parts(parts, HERE, dict(pivot=[0, 0, PZ], detents_deg=DET, lift_mm=LIFT, l_hand=L_HAND, tube_top=TUBE_TOP, printer=[240, 240, 240],
                                          arc_mm=round(L_HAND * math.radians(DET["max"] - DET["cutoff"]))),
                        extra=dict(check=[dict(pose=p, hits=b) for p, b in res], gate_sweep=[dict(a=a, rest=h0, lifted=hl) for a, h0, hl in sweep]))
    for i in info: print(f"{i['name']:16s} {i['group']:6s} {i['kind']:5s} {i['size']} {i['grams'] or ''}")
    for p, b in res: print("pose", p, b if b else "none")
