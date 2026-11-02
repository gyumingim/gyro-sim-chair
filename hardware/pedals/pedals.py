"""DIY rudder pedals (rough v0) — build123d.

Rudder: a bar turns about a vertical axis at the centre (left foot forward = right foot back), AS5600 under the pivot.
Toe brakes: each pedal plate hinges at its bottom on the bar end and tips forward when the toes press, AS5600 on each hinge.
x = forward, y = left, z = up, mm. Origin = centre of the base underside.
Run: python pedals.py -> stl/*.stl, parts.json, interference check
"""
import json, math, os
from datetime import datetime
from build123d import Box, Cylinder, Pos, Rot, Axis, export_stl

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "stl"); os.makedirs(OUT, exist_ok=True)

RUD = 20          # rudder ±deg about z
BRK = 15          # toe brake 0..deg about the hinge
BAR_Z = 40        # rudder bar centre height
PY = 135          # pedal centre |y|
HX, HZ = 30, 30   # hinge axis (x, z) relative to the bar centre line (x=0, z=BAR_Z)
LEAN = 20         # pedal plate leans forward from vertical (deg)

def box(x0, x1, y0, y1, z0, z1):
    return Pos((x0 + x1) / 2, (y0 + y1) / 2, (z0 + z1) / 2) * Box(x1 - x0, y1 - y0, z1 - z0)
def cy(x, z, y0, y1, d): return Pos(x, (y0 + y1) / 2, z) * Rot(90, 0, 0) * Cylinder(d / 2, abs(y1 - y0))
def cz(x, y, z0, z1, d): return Pos(x, y, (z0 + z1) / 2) * Cylinder(d / 2, z1 - z0)

parts = {}
def part(name, shape, group, kind="print", note="", material="PLA"):
    parts[name] = dict(shape=shape, group=group, kind=kind, note=note, material=material)

# fixed
part("base_board", box(-170, 150, -200, 200, 0, 18), "fixed", kind="cut", note="바닥 합판 18 mm (320×400) — 출력 안 함, 재단", material="합판")
post = cz(0, 0, 18, BAR_Z - 11, 60) - cz(0, 0, BAR_Z - 18, BAR_Z - 10, 22.2) - cz(0, 0, 17, BAR_Z, 9)
part("pivot_post", post, "fixed", note="가운데 축 받침: 608 베어링 (세로), 아래에 AS5600", material="PETG")
for s in (1, -1):
    part(f"spring_post_{'L' if s > 0 else 'R'}", cz(-80, s * 90, 18, 70, 16), "fixed", note="가운데로 돌아오는 스프링 고정 기둥")
part("heel_rest", box(-170, -110, -200, 200, 18, 28), "fixed", kind="cut", note="발뒤꿈치 받침 — 400 mm 라 출력 안 함, 나무 각재 재단 + 고무", material="각재")

# rudder group (turns about z)
part("rudder_bar", box(-15, 15, -170, 170, BAR_Z - 10, BAR_Z + 10), "rudder", kind="buy", note="알루미늄 프로파일 20×30, 340 mm (러더 바)")
part("bar_hub", cz(0, 0, BAR_Z - 12, BAR_Z - 10, 40) + cz(0, 0, BAR_Z - 30, BAR_Z - 10, 8), "rudder", kind="buy", note="M8 축 + 와셔 (바를 베어링에)")
for s, nm in ((1, "L"), (-1, "R")):
    y0, y1 = sorted((s * (PY - 55), s * (PY + 55)))
    brk = box(10, 40, y0, y0 + 10, BAR_Z - 10, BAR_Z + HZ + 10) + box(10, 40, y1 - 10, y1, BAR_Z - 10, BAR_Z + HZ + 10)
    brk -= cy(HX, BAR_Z + HZ, y0 - 1, y1 + 1, 6.4)
    part(f"hinge_bracket_{nm}", brk, "rudder", note="페달 경첩 받침 (바 끝)", material="PETG")
    # pedal plate: leans forward LEAN deg, hinged at the bottom
    t = math.radians(LEAN)
    plate = Pos(HX, s * PY, BAR_Z + HZ) * Rot(0, LEAN, 0) * Pos(0, 0, 110) * Box(10, 84, 220)
    plate += cy(HX, BAR_Z + HZ, s * PY - 42, s * PY + 42, 16)          # hinge barrel
    plate -= cy(HX, BAR_Z + HZ, s * PY - 50, s * PY + 50, 6.4)
    part(f"pedal_{nm}", plate, f"brake{nm}", note="페달 판 (발끝으로 누르면 앞으로 꺾임 = 브레이크)", material="PETG")
    part(f"hinge_pin_{nm}", cy(HX, BAR_Z + HZ, y0 - 2, y1 + 1, 6) if s > 0 else cy(HX, BAR_Z + HZ, y0 - 1, y1 + 2, 6), "rudder", kind="buy", note="M6 볼트 (경첩 축)")
    sen = box(10, 40, y1 + (2 if s > 0 else -12), y1 + (12 if s > 0 else -2), BAR_Z, BAR_Z + HZ + 20) if False else \
          box(14, 46, (y1 + 3) if s > 0 else (y0 - 13), (y1 + 13) if s > 0 else (y0 - 3), BAR_Z + HZ - 16, BAR_Z + HZ + 16)
    part(f"brake_sensor_{nm}", sen, "rudder", note="브레이크 AS5600 받침 (경첩 축 끝)")

# pose + check
def posed(name, rud=0, bl=0, br=0):
    p = parts[name]; s = p["shape"]; g = p["group"]
    if g == "brakeL" and bl: s = s.rotate(Axis((HX, 0, BAR_Z + HZ), (0, 1, 0)), bl)
    if g == "brakeR" and br: s = s.rotate(Axis((HX, 0, BAR_Z + HZ), (0, 1, 0)), br)
    if g in ("rudder", "brakeL", "brakeR") and rud: s = s.rotate(Axis((0, 0, 0), (0, 0, 1)), rud)
    return s

if __name__ == "__main__":
    info = []
    for name, p in parts.items():
        export_stl(p["shape"], os.path.join(OUT, name + ".stl"), tolerance=0.05)
        bb = p["shape"].bounding_box(); vol = p["shape"].volume / 1000
        grams = round(vol * 1.27 * 0.55, 1) if p["kind"] == "print" else None
        info.append(dict(name=name, group=p["group"], kind=p["kind"], note=p["note"], material=p["material"] if p["kind"] != "buy" else "",
                         size=[round(bb.size.X, 1), round(bb.size.Y, 1), round(bb.size.Z, 1)], grams=grams, file=f"stl/{name}.stl"))
    meta = dict(created=datetime.now().isoformat(timespec="seconds"), rudder_deg=RUD, brake_deg=BRK, hinge=[HX, BAR_Z + HZ])
    json.dump(dict(meta=meta, parts=info), open(os.path.join(HERE, "parts.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    for i in info: print(f"{i['name']:18s} {i['group']:7s} {i['kind']:5s} {i['size']} {i['grams'] or ''}")
    import itertools
    allow = {frozenset(p) for p in [("pedal_L", "hinge_pin_L"), ("pedal_R", "hinge_pin_R"), ("hinge_bracket_L", "hinge_pin_L"), ("hinge_bracket_R", "hinge_pin_R"),
             ("rudder_bar", "hinge_bracket_L"), ("rudder_bar", "hinge_bracket_R"), ("bar_hub", "rudder_bar"), ("bar_hub", "pivot_post"),
             ("base_board", "pivot_post"), ("base_board", "bar_hub"), ("base_board", "spring_post_L"), ("base_board", "spring_post_R"), ("base_board", "heel_rest"),
             ("hinge_bracket_L", "brake_sensor_L"), ("hinge_bracket_R", "brake_sensor_R")]}
    for rud, bl, br in [(0, 0, 0), (RUD, 0, 0), (-RUD, 0, 0), (0, BRK, BRK), (RUD, BRK, BRK), (-RUD, BRK, BRK)]:
        bad = []
        for a, b in itertools.combinations(parts, 2):
            if frozenset((a, b)) in allow: continue
            try: v = (posed(a, rud, bl, br) & posed(b, rud, bl, br)).volume
            except Exception: v = 0
            if v > 0.5: bad.append(f"{a}×{b} {v:.0f}")
        print(f"rudder {rud:+d} brake {bl}/{br}: {bad if bad else 'none'}")
