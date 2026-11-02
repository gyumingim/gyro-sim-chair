"""DIY throttle for the gyro sim chair — parametric build123d model.

Run:  python throttle.py      -> stl/*.stl (printable + purchased-part placeholders), parts.json (BOM data)

Coordinates (mm): x = forward (push = more thrust), y = left, z = up. Origin = centre of the base underside.
Pivot axis runs along y at (x=0, z=PIVOT_Z). The lever swings ±SWING degrees about it.
Printer limit assumed 240 × 240 × 240 (largest part here is ~190 mm).
"""
import json, math, os
from datetime import datetime
from build123d import Box, Cylinder, Pos, Rot, export_stl

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "stl")
os.makedirs(OUT, exist_ok=True)

# ---------------- parameters ----------------
BASE_L, BASE_W, BASE_T = 190, 80, 6
PIVOT_Z = 45
WALL_IN, WALL_T = 30, 8              # side walls: inner face at y=±30, 8 thick
WALL_X, WALL_TOP = 45, 80
BRG_OD, BRG_W, BRG_ID = 22.2, 7, 8   # 608ZZ (pocket +0.2)
SHAFT_D, SHAFT_L = 8, 90             # M8 x 90 bolt (sticks out past the left wall for the magnet cup)
HUB_R, HUB_W = 22, 48
ARM_W, ARM_T, ARM_TOP = 16, 12, 165  # lever arm 16 (x) x 12 (y), top at z=165
GRIP = (44, 50, 75)                  # grip box x, y, z
SWING = 30                           # lever travel ±30°
HOLE_M3, HOLE_M6 = 3.2, 6.5

def box(x0, x1, y0, y1, z0, z1):
    return Pos((x0 + x1) / 2, (y0 + y1) / 2, (z0 + z1) / 2) * Box(x1 - x0, y1 - y0, z1 - z0)

def cyl_y(x, z, y0, y1, d):                      # cylinder along y
    return Pos(x, (y0 + y1) / 2, z) * Rot(90, 0, 0) * Cylinder(d / 2, abs(y1 - y0))

def cyl_x(y, z, x0, x1, d):
    return Pos((x0 + x1) / 2, y, z) * Rot(0, 90, 0) * Cylinder(d / 2, abs(x1 - x0))

def cyl_z(x, y, z0, z1, d):
    return Pos(x, y, (z0 + z1) / 2) * Cylinder(d / 2, z1 - z0)

def hex_y(x, z, y0, y1, af):                     # hexagonal prism along y (nut trap), across-flats af
    p = None
    for a in (0, 60, 120):
        b = Pos(x, (y0 + y1) / 2, z) * Rot(0, a, 0) * Box(af, abs(y1 - y0), af * 2)
        p = b if p is None else p & b
    return p

parts = {}   # name -> dict(shape, kind, qty, note)
def part(name, shape, kind="print", qty=1, note="", material="PLA"):
    parts[name] = dict(shape=shape, kind=kind, qty=qty, note=note, material=material)

# ---------------- printed parts ----------------
# base plate: 4 x M6 mount holes (to the throttle plate on the cage), M3 holes for walls / blocks / bay
base = box(-BASE_L / 2, BASE_L / 2, -BASE_W / 2, BASE_W / 2, 0, BASE_T)
for x in (-80, 80):
    for y in (-30, 30):
        base -= cyl_z(x, y, -1, BASE_T + 1, HOLE_M6)
for x in (-30, 30):
    for s in (1, -1):
        base -= cyl_z(x, s * (WALL_IN + WALL_T / 2), -1, BASE_T + 1, HOLE_M3)
part("base", base, note="바닥판, M6 ×4 로 의자 스로틀 받침판에 고정")

def wall(s):
    y0, y1 = sorted((s * WALL_IN, s * (WALL_IN + WALL_T)))
    w = box(-WALL_X, WALL_X, y0, y1, BASE_T, WALL_TOP)
    outer = s * (WALL_IN + WALL_T)
    w -= cyl_y(0, PIVOT_Z, outer - s * BRG_W, outer + s * 1, BRG_OD)      # bearing pocket from the outside
    w -= cyl_y(0, PIVOT_Z, y0 - 1, y1 + 1, BRG_ID + 1.5)                 # shaft clearance
    for x in (-30, 30):
        w -= cyl_z(x, (y0 + y1) / 2, BASE_T - 1, BASE_T + 14, 2.8)       # M3 self-tap into the wall bottom
    return w
part("wall_left", wall(1), note="옆벽 (왼쪽, +y). 608 베어링 자리, 바깥에 센서 받침")
part("wall_right", wall(-1), note="옆벽 (오른쪽, −y). 608 베어링 자리")

# hub + lever arm (one print). M8 nut trapped in the hub so the bolt (shaft) turns with the lever.
hub = cyl_y(0, PIVOT_Z, -HUB_W / 2, HUB_W / 2, HUB_R * 2)
arm = box(-ARM_W / 2, ARM_W / 2, -ARM_T / 2, ARM_T / 2, PIVOT_Z + HUB_R - 4, ARM_TOP)
lever = hub + arm
lever -= cyl_y(0, PIVOT_Z, -HUB_W / 2 - 1, HUB_W / 2 + 1, SHAFT_D + 0.4)
lever -= hex_y(0, PIVOT_Z, HUB_W / 2 - 7, HUB_W / 2 + 1, 13.2)
# afterburner detent notch on the hub rim (ball plunger from the front block clicks in near full forward)
ab = math.radians(SWING - 6)
# the plunger sits at the front (+x, z=PIVOT_Z). Pushing the lever forward turns the front of the hub downward,
# so the notch is the rim point `ab` above the front: it reaches the plunger at lever angle +ab.
nx, nz = HUB_R * math.cos(ab), PIVOT_Z + HUB_R * math.sin(ab)
lever -= cyl_y(nx, nz, -4, 4, 5)
lever -= cyl_z(0, 0, ARM_TOP - 20, ARM_TOP + 1, 3.2)                     # M3 screw for the grip
part("lever", lever, note="허브 + 레버 한 덩어리. M8 너트가 허브에 끼워져 축이 레버와 같이 돔. 출력: 옆으로 눕혀서", material="PETG")

# grip: buttons on the inboard (−y, thumb) side, trigger on the front, hat switch on top-inboard
gx, gy, gz = GRIP
gz0 = ARM_TOP - 25
grip = box(-gx / 2, gx / 2, -gy / 2, gy / 2, gz0, gz0 + gz)
grip -= box(-ARM_W / 2 - 0.3, ARM_W / 2 + 0.3, -ARM_T / 2 - 0.3, ARM_T / 2 + 0.3, gz0 - 1, gz0 + 25)   # arm socket
grip -= box(-gx / 2 + 3, gx / 2 - 3, -gy / 2 + 3, gy / 2 - 3, gz0 + 28, gz0 + gz - 3)                 # hollow for wiring
for z in (gz0 + 40, gz0 + 58):
    grip -= Pos(0, -gy / 2, z) * Rot(90, 0, 0) * Cylinder(6.2, 8)       # 2 thumb buttons (12 mm tact)
grip -= Pos(gx / 2, 0, gz0 + 50) * Rot(0, 90, 0) * Cylinder(6.2, 8)     # trigger (index finger)
grip -= Pos(-6, -10, gz0 + gz) * Cylinder(7.2, 8)                       # 4-way hat switch on top
grip -= cyl_z(0, 0, gz0 - 1, gz0 + 30, 3.2)
part("grip", grip, note="손잡이: 엄지 버튼 2 + 검지 트리거 1 + 4방향 햇 1. 안은 비어 배선 통로")

# front block: M6 ball plunger pointing at the hub rim (afterburner click)
front = box(HUB_R + 3, HUB_R + 21, -12, 12, BASE_T, PIVOT_Z + 12)
front -= cyl_x(0, PIVOT_Z, HUB_R + 2, HUB_R + 22, 5.0)                 # M6 tapping hole
for y in (-7, 7):
    front -= cyl_z(HUB_R + 12, y, BASE_T - 1, BASE_T + 10, 2.8)
part("detent_block", front, note="앞 블록: M6 볼 플런저가 허브 홈에 걸려 애프터버너 '딸깍'")

# rear block: M5 thumb screw pushes a rubber pad on the hub rim (friction = lever stays where you leave it)
rear = box(-HUB_R - 21, -HUB_R - 3, -12, 12, BASE_T, PIVOT_Z + 12)
rear -= cyl_x(0, PIVOT_Z, -HUB_R - 22, -HUB_R - 2, 4.3)
rear -= box(-HUB_R - 6, -HUB_R - 2, -8, 8, PIVOT_Z - 8, PIVOT_Z + 8)   # pocket for the rubber pad
for y in (-7, 7):
    rear -= cyl_z(-HUB_R - 12, y, BASE_T - 1, BASE_T + 10, 2.8)
part("friction_block", rear, note="뒤 블록: M5 손나사가 고무 패드를 허브에 눌러 마찰 조절")

# top cover with the lever slot (keeps fingers out of the hub)
slot_half = (WALL_TOP - PIVOT_Z) * math.tan(math.radians(SWING)) + ARM_W / 2 + 4
cover = box(-WALL_X, WALL_X, -(WALL_IN + WALL_T), WALL_IN + WALL_T, WALL_TOP, WALL_TOP + 4)
cover -= box(-slot_half, slot_half, -ARM_T / 2 - 3, ARM_T / 2 + 3, WALL_TOP - 1, WALL_TOP + 5)
for x in (-38, 38):
    for s in (1, -1):
        cover -= cyl_z(x, s * (WALL_IN + WALL_T / 2), WALL_TOP - 1, WALL_TOP + 5, HOLE_M3)
part("top_cover", cover, note="윗덮개: 레버 홈 (±30°), 손가락 끼임 방지")

# sensor mount on the outside of the left wall: AS5600 board faces the magnet on the shaft end
sy0 = WALL_IN + WALL_T
BOARD_Y = SHAFT_L / 2 + 6                         # AS5600 board inner face: ~2 mm from the magnet face
sensor = box(-22, 22, BOARD_Y + 1.6, BOARD_Y + 4.6, PIVOT_Z - 22, PIVOT_Z + 22)
for x in (-16, 16):
    sensor += cyl_y(x, PIVOT_Z, sy0, BOARD_Y + 1.6, 7)
    sensor -= cyl_y(x, PIVOT_Z, sy0 - 1, BOARD_Y + 5, 3.2)
part("sensor_mount", sensor, note="AS5600 받침 (축 끝 자석과 약 2 mm)")

CAP0 = sy0 + 1                                    # cup starts 1 mm off the wall (clear of the bearing)
magcap = cyl_y(0, PIVOT_Z, CAP0, SHAFT_L / 2 + 4, 14) - cyl_y(0, PIVOT_Z, CAP0 - 1, SHAFT_L / 2 + 0.5, 8.3)
magcap -= cyl_y(0, PIVOT_Z, SHAFT_L / 2 + 1.5, SHAFT_L / 2 + 5, 6.2)
part("magnet_cap", magcap, note="볼트 끝에 끼우는 자석 컵 (6×2.5 mm 직경 방향 자석)")

# electronics bay at the rear: Pro Micro + wiring, USB opening at the back
bay = box(-BASE_L / 2 + 2, -50, -32, 32, BASE_T, 34) - box(-BASE_L / 2 + 4.5, -52.5, -29.5, 29.5, BASE_T + 2, 35)
bay -= box(-BASE_L / 2 + 1, -BASE_L / 2 + 6, -7, 7, BASE_T + 6, BASE_T + 16)                     # USB slot
part("electronics_bay", bay, note="전자부 칸: Pro Micro, USB 구멍 뒤쪽")

# ---------------- purchased parts (placeholders, for the view only) ----------------
for s in (1, -1):
    outer = s * (WALL_IN + WALL_T)
    part(f"bearing_608_{'L' if s > 0 else 'R'}", cyl_y(0, PIVOT_Z, outer - s * BRG_W, outer, 22) - cyl_y(0, PIVOT_Z, outer - s * 8, outer + s, 8),
         kind="buy", note="608ZZ 베어링")
part("shaft_M8x90", cyl_y(0, PIVOT_Z, -SHAFT_L / 2, SHAFT_L / 2, SHAFT_D), kind="buy", note="M8×90 볼트 (축)")
part("as5600", box(-11.5, 11.5, BOARD_Y, BOARD_Y + 1.6, PIVOT_Z - 11.5, PIVOT_Z + 11.5), kind="buy", note="AS5600 홀 센서 보드")
part("pro_micro", box(-85, -55, -9, 9, BASE_T + 2, BASE_T + 4), kind="buy", note="아두이노 Pro Micro (ATmega32U4)")

# ---------------- export ----------------
info = []
for name, p in parts.items():
    fn = os.path.join(OUT, name + ".stl")
    export_stl(p["shape"], fn, tolerance=0.05)
    bb = p["shape"].bounding_box()
    vol = p["shape"].volume / 1000.0  # cm3
    grams = vol * (1.24 if p["material"] == "PLA" else 1.27) * 0.55 if p["kind"] == "print" else None   # ~30% infill + walls
    moving = name in ("lever", "grip", "magnet_cap", "shaft_M8x90")
    info.append(dict(name=name, kind=p["kind"], qty=p["qty"], note=p["note"], material=p["material"] if p["kind"] == "print" else "",
                     size=[round(bb.size.X, 1), round(bb.size.Y, 1), round(bb.size.Z, 1)], volume_cm3=round(vol, 1),
                     grams=round(grams, 1) if grams else None, moving=moving, file=f"stl/{name}.stl"))
meta = dict(created=datetime.now().isoformat(timespec="seconds"), pivot=[0, 0, PIVOT_Z], swing_deg=SWING, printer=[240, 240, 240])
json.dump(dict(meta=meta, parts=info), open(os.path.join(os.path.dirname(OUT), "parts.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
for i in info:
    print(f"{i['name']:16s} {i['kind']:5s} size {i['size']}  vol {i['volume_cm3']} cm3  {i['grams'] or ''} g")

# ---------------- interference check (assembled, lever at 0 / +SWING / -SWING) ----------------
if __name__ == "__main__":
    import itertools
    from build123d import Axis
    def posed(name, deg):
        s = parts[name]["shape"]
        if name in ("lever", "grip", "magnet_cap", "shaft_M8x90") and deg:
            s = s.rotate(Axis((0, 0, PIVOT_Z), (0, 1, 0)), deg)
        return s
    for deg in (0, SWING, -SWING):
        bad = []
        for a, b in itertools.combinations(parts, 2):
            try:
                v = (posed(a, deg) & posed(b, deg)).volume
            except Exception:
                v = 0
            if v > 0.5:
                bad.append(f"{a}×{b} {v:.1f}mm3")
        print(f"lever {deg:+d}°: overlaps {bad if bad else 'none'}")
