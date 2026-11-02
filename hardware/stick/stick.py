"""DIY centre stick for the gyro sim chair — 2-axis gimbal, parametric build123d model.

Run:  python stick.py   -> stl/*.stl, parts.json, interference check over roll/pitch ±TRAVEL

Coordinates (mm): x = forward, y = left, z = up. Origin = centre of the base underside.
Gimbal centre at (0, 0, PZ). Roll axis = x (stick left/right), pitch axis = y (stick forward/back).
Outer yoke turns about x on two 608 bearings in the housing; the inner block (with the stick) turns about y
on two 608 bearings in the yoke. Centring: V-cam on each axis + spring ball plunger. Angles: AS5600 on each axis.
"""
import json, math, os
from datetime import datetime
from build123d import Box, Cylinder, Pos, Rot, Axis, export_stl

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "stl"); os.makedirs(OUT, exist_ok=True)

PZ = 60                       # gimbal centre height
TRAVEL = 20                   # ±deg each axis
BRG_OD, BRG_W = 22.2, 7       # 608ZZ pocket
M3, M6 = 3.2, 6.5

def box(x0, x1, y0, y1, z0, z1):
    return Pos((x0 + x1) / 2, (y0 + y1) / 2, (z0 + z1) / 2) * Box(x1 - x0, y1 - y0, z1 - z0)
def cx(y, z, x0, x1, d): return Pos((x0 + x1) / 2, y, z) * Rot(0, 90, 0) * Cylinder(d / 2, abs(x1 - x0))
def cy(x, z, y0, y1, d): return Pos(x, (y0 + y1) / 2, z) * Rot(90, 0, 0) * Cylinder(d / 2, abs(y1 - y0))
def cz(x, y, z0, z1, d): return Pos(x, y, (z0 + z1) / 2) * Cylinder(d / 2, z1 - z0)
def hex_axis(c, a0, a1, af, axis):            # hexagonal prism (nut trap) along x or y
    p = None
    for ang in (0, 60, 120):
        if axis == "y":
            b = Pos(c[0], (a0 + a1) / 2, c[1]) * Rot(0, ang, 0) * Box(af, abs(a1 - a0), af * 2)
        else:
            b = Pos((a0 + a1) / 2, c[0], c[1]) * Rot(ang, 0, 0) * Box(abs(a1 - a0), af, af * 2)
        p = b if p is None else p & b
    return p

parts = {}
def part(name, shape, group, kind="print", note="", material="PLA"):
    parts[name] = dict(shape=shape, group=group, kind=kind, note=note, material=material)

# ---------------- housing (fixed) ----------------
base = box(-70, 70, -70, 70, 0, 6)
for x in (-55, 55):
    for y in (-55, 55):
        base -= cz(x, y, -1, 7, M6)
for x in (-54, 54):
    for y in (-20, 20):
        base -= cz(x, y, -1, 7, M3)
part("base", base, "fixed", note="바닥판: M6 ×4 로 접이식 스틱 받침 위에")

WX0, WX1 = 50, 58             # front/back walls (normal x), roll bearings
def wall(s):
    x0, x1 = sorted((s * WX0, s * WX1))
    w = box(x0, x1, -30, 30, 6, 100)
    outer = s * WX1
    w -= cx(0, PZ, outer - s * BRG_W, outer + s, BRG_OD)
    w -= cx(0, PZ, x0 - 1, x1 + 1, 9.5)
    for y in (-20, 20):
        w -= cz((x0 + x1) / 2, y, 5, 20, 2.8)
    return w
part("wall_front", wall(1), "fixed", note="앞벽: roll 축 608 베어링")
part("wall_back", wall(-1), "fixed", note="뒤벽: roll 축 608 베어링")

# roll centring: V-cam on the front stub, ball plunger block on the front wall top
plunger_front = box(WX0, 70, -9, 9, 100, 106) + box(60, 70, -9, 9, 106, 118)      # flange on the wall top + tower over the cam
plunger_front -= cz(65, 0, 99, 119, 8.5)                      # M10 ball plunger tapping hole (8.5), tip reaches the cam top (z≈86)
plunger_front -= cz(54, 0, 99, 107, M3)
part("plunger_block_roll", plunger_front, "fixed", note="roll 가운데 맞춤: M10 볼 플런저가 캠 V 홈을 누름")

# roll sensor bracket behind the back wall (AS5600 faces the magnet on the back stub)
sens_r = box(-84, -80, -20, 20, PZ - 20, PZ + 20) + box(-84, -58, -20, -14, 30, PZ + 20) + box(-84, -58, 14, 20, 30, PZ + 20)
part("sensor_mount_roll", sens_r, "fixed", note="roll AS5600 받침 (뒤벽)")

# ---------------- yoke (turns about x) ----------------
YI, YO = 27, 35               # yoke side plates y 27..35 (pitch bearings)
yoke = box(-48, 48, YI, YO, PZ - 22, PZ + 18) + box(-48, 48, -YO, -YI, PZ - 22, PZ + 18) \
     + box(40, 48, -YO, YO, PZ - 22, PZ - 6) + box(-48, -40, -YO, YO, PZ - 22, PZ - 6)
for s in (1, -1):
    outer = s * YO
    yoke -= cy(0, PZ, outer - s * BRG_W, outer + s, BRG_OD)
    yoke -= cy(0, PZ, s * YI - s, outer + s, 9.5)
# roll stubs: M8 bolts screwed into nut traps in the end blocks -> raise end blocks to the axis
for s in (1, -1):
    blk = box(min(s * 40, s * 48), max(s * 40, s * 48), -10, 10, PZ - 22, PZ + 8)
    yoke += blk
    yoke -= cx(0, PZ, s * 39, s * 49, 8.4)
    yoke -= hex_axis((0, PZ), s * 40, s * 46, 13.2, "x")
part("yoke", yoke, "roll", note="바깥 요크: roll 로 돎, 안쪽 블록의 pitch 베어링을 잡음", material="PETG")

# pitch centring: plunger block on the -y yoke side, cam on the -y pitch shaft end
plunger_pitch = box(-9, 9, -YO, -YI, PZ + 18, PZ + 24) + box(-9, 9, -YO - 12, -YI, PZ + 24, PZ + 34)   # sits on the yoke side top, arm over the cam
plunger_pitch -= cz(0, -YO - 6, PZ + 17, PZ + 35, 8.5)
part("plunger_block_pitch", plunger_pitch, "roll", note="pitch 가운데 맞춤: M10 볼 플런저 (요크에 붙음)")
# pitch sensor bracket on the +y yoke side
sens_p = box(-20, 20, YO + 13, YO + 16, PZ - 20, PZ + 20) + box(-20, -14, YO, YO + 16, PZ - 20, PZ - 14) + box(14, 20, YO, YO + 16, PZ - 20, PZ - 14)
part("sensor_mount_pitch", sens_p, "roll", note="pitch AS5600 받침 (요크 +y 쪽, 같이 돎)")

# ---------------- inner block + stick (turns about y inside the yoke) ----------------
block = box(-16, 16, -24, 24, PZ - 16, PZ + 16)
block -= cy(0, PZ, -25, 25, 8.4)
block -= hex_axis((0, PZ), 18, 25, 13.2, "y")
block -= cz(0, 0, PZ + 4, PZ + 17, 20.4)                        # socket for the Ø20 stick tube
part("inner_block", block, "pitch", note="안쪽 블록: pitch 로 돎, Ø20 스틱 관이 꽂힘", material="PETG")

TUBE_TOP = PZ + 16 + 120
part("stick_tube", cz(0, 0, PZ + 4, TUBE_TOP, 20) - cz(0, 0, PZ + 3, TUBE_TOP + 1, 16), "pitch", kind="buy", note="알루미늄 관 Ø20×2t, 길이 130")

# grip (right hand): trigger front, thumb hat + 2 buttons on the top/left, pinky button low on the right
G0 = TUBE_TOP - 25
grip = box(-24, 24, -20, 20, G0, G0 + 110) + Pos(4, 0, G0 + 110) * Rot(0, -15, 0) * Box(40, 40, 24)
grip -= cz(0, 0, G0 - 1, G0 + 26, 20.4)
grip -= box(-20, 20, -16, 16, G0 + 30, G0 + 104)                # hollow for wires
grip -= Pos(24, 0, G0 + 85) * Rot(0, 90, 0) * Cylinder(6.2, 10)  # trigger
grip -= Pos(0, 6, G0 + 122) * Cylinder(7.2, 14)                  # 4-way hat (thumb)
for x in (-12, 14):
    grip -= Pos(x, 12, G0 + 116) * Cylinder(6.2, 14)             # 2 thumb buttons
grip -= Pos(0, -20, G0 + 40) * Rot(90, 0, 0) * Cylinder(6.2, 10) # pinky button (right side)
part("grip", grip, "pitch", note="손잡이 (오른손): 트리거, 엄지 햇, 엄지 버튼 2, 새끼 버튼 1. 안은 배선 통로")

# ---------------- shafts, cams, magnets, bearings (purchased or tiny prints) ----------------
part("roll_stub_front", cx(0, PZ, 40, 72, 8), "roll", kind="buy", note="M8×35 볼트 (roll 앞)")
part("roll_stub_back", cx(0, PZ, -66, -40, 8), "roll", kind="buy", note="M8×30 볼트 (roll 뒤)")
part("pitch_shaft", cy(0, PZ, -44, 42, 8), "pitch", kind="buy", note="M8×90 볼트 (pitch 축)")
cam_r = cx(0, PZ, 60, 66, 52) - cx(0, PZ, 59, 67, 8.4)
cam_r -= Pos(63, 0, PZ + 26) * Rot(45, 0, 0) * Box(8, 9, 9)                    # V notch on top
part("cam_roll", cam_r, "roll", note="roll V 캠 (볼 플런저가 홈에 걸려 가운데로)", material="PETG")
cam_p = cy(0, PZ, -YO - 9, -YO - 3, 44) - cy(0, PZ, -YO - 10, -YO - 2, 8.4)
cam_p -= Pos(0, -YO - 6, PZ + 22) * Rot(0, 45, 0) * Box(9, 8, 9)
part("cam_pitch", cam_p, "pitch", note="pitch V 캠", material="PETG")
part("magcap_roll", cx(0, PZ, -74, -67, 14) - cx(0, PZ, -75, -71, 8.3) - cx(0, PZ, -74.5, -72, 6.2), "roll", note="roll 자석 컵")
part("magcap_pitch", cy(0, PZ, YO + 2, YO + 10, 14) - cy(0, PZ, YO + 1, YO + 7.5, 8.3) - cy(0, PZ, YO + 8, YO + 10.5, 6.2), "pitch", note="pitch 자석 컵")
part("as5600_roll", box(-79.6, -78, -11.5, 11.5, PZ - 11.5, PZ + 11.5), "fixed", kind="buy", note="AS5600 (roll)")
part("as5600_pitch", box(-11.5, 11.5, YO + 11.4, YO + 13, PZ - 11.5, PZ + 11.5), "roll", kind="buy", note="AS5600 (pitch)")
for s, nm in ((1, "front"), (-1, "back")):
    o = s * WX1
    part(f"bearing_roll_{nm}", cx(0, PZ, o - s * BRG_W, o, 22) - cx(0, PZ, o - s * 8, o + s, 8), "fixed", kind="buy", note="608ZZ")
for s, nm in ((1, "L"), (-1, "R")):
    o = s * YO
    part(f"bearing_pitch_{nm}", cy(0, PZ, o - s * BRG_W, o, 22) - cy(0, PZ, o - s * 8, o + s, 8), "roll", kind="buy", note="608ZZ")

# ---------------- pose + interference check ----------------
def posed(name, roll, pitch):
    s = parts[name]["shape"]; g = parts[name]["group"]
    if g == "pitch" and pitch: s = s.rotate(Axis((0, 0, PZ), (0, 1, 0)), pitch)
    if g in ("pitch", "roll") and roll: s = s.rotate(Axis((0, 0, PZ), (1, 0, 0)), roll)
    return s

if __name__ == "__main__":
    info = []
    for name, p in parts.items():
        export_stl(p["shape"], os.path.join(OUT, name + ".stl"), tolerance=0.05)
        bb = p["shape"].bounding_box(); vol = p["shape"].volume / 1000
        grams = round(vol * (1.24 if p["material"] == "PLA" else 1.27) * 0.55, 1) if p["kind"] == "print" else None
        info.append(dict(name=name, group=p["group"], kind=p["kind"], note=p["note"], material=p["material"] if p["kind"] == "print" else "",
                         size=[round(bb.size.X, 1), round(bb.size.Y, 1), round(bb.size.Z, 1)], volume_cm3=round(vol, 1), grams=grams, file=f"stl/{name}.stl"))
    json.dump(dict(meta=dict(created=datetime.now().isoformat(timespec="seconds"), pivot=[0, 0, PZ], travel_deg=TRAVEL, printer=[240, 240, 240]), parts=info),
              open(os.path.join(HERE, "parts.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    for i in info:
        print(f"{i['name']:20s} {i['group']:5s} {i['kind']:5s} {i['size']}  {i['grams'] or ''}")
    import itertools
    allow = {frozenset(p) for p in [("pitch_shaft", "inner_block"), ("pitch_shaft", "cam_pitch"), ("pitch_shaft", "magcap_pitch"),
             ("roll_stub_front", "yoke"), ("roll_stub_back", "yoke"), ("roll_stub_front", "cam_roll"), ("roll_stub_back", "magcap_roll"),
             ("stick_tube", "inner_block"), ("stick_tube", "grip")]}
    for r, p in [(0, 0), (TRAVEL, 0), (-TRAVEL, 0), (0, TRAVEL), (0, -TRAVEL), (TRAVEL, TRAVEL), (TRAVEL, -TRAVEL), (-TRAVEL, TRAVEL), (-TRAVEL, -TRAVEL)]:
        bad = []
        for a, b in itertools.combinations(parts, 2):
            if frozenset((a, b)) in allow: continue
            try: v = (posed(a, r, p) & posed(b, r, p)).volume
            except Exception: v = 0
            if v > 0.5: bad.append(f"{a}×{b} {v:.0f}")
        print(f"roll {r:+d} pitch {p:+d}: {bad if bad else 'none'}")
