"""Toe brakes v4 (simple add-on for the v3 pedals, all PLA) — build123d.

Run:  python brakes_v4.py   -> stl_brakes_v4/*.stl, brakes_v4.json (BOM, spring, strength), interference check

Per side 3 printed parts: pedal_base (fixed), toe_plate (hinged), toe_sensor_cap.
  * pedal_base replaces the v3 pedal plate: same heel pin in the same carriage ears, same 65 deg lean, but it is FIXED:
    two feet under the ribs sit on the carriage's existing brake stop posts (+ one M4 screw each). No horn / brake spring leg.
  * toe_plate: upper 105 mm of the pedal, hinged at the ball of the foot (Ø6 SUS pin, glued in the toe plate barrel and turning
    in 2 base knuckles). Rest = tilted 18 deg toward the rider by ONE compression spring; full brake = the toe plate lies flat on
    the base back plate (hard stop over the whole plate area -> panic stomp goes straight into the base).
  * sensor: AS5600 (analog OUT -> STM32 ADC, FreeJoy) on the outboard end of the toe pin, magnet glued in the pin end.
The v3 carriage, rails, rocker and pins are unchanged (imported from pedals.py).
Plate coordinates: s = up the plate from the heel pin, n = behind the plate (forward/down), y.
"""
import json, math, os, sys
from datetime import datetime
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import pedals as P                                   # v3 geometry (carriage, stop posts, hinge)
from build123d import Axis, Pos, Rot, Box, Cylinder, Plane, mirror, export_stl
from ctl_lib import box, cz, auto_fill, PLA_MECH, sf

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "stl_brakes_v4")
HX, HZ, LEAN, PY = P.HX, P.HZ, P.LEAN, P.PY
U, N = P.U, P.N
S_T = 125            # toe hinge distance up the plate from the heel pin
BT = 18.0            # toe brake travel deg (AS5600 minimum programmable range is 18 deg)
SP = 165             # spring position s
L = 230              # plate length (as v3)
W2 = 50              # half width (as v3)
TW2 = 43             # toe plate half width (inside the base side walls)
PIN_D = 6
SPRING = dict(od=12, free=26, solid_max=11, k=6.0)

def X(s, n): return (HX + U[0] * s + N[0] * n, HZ + U[1] * s + N[1] * n)
def pbox(s0, s1, n0, n1, y0, y1):
    """box in plate coordinates (left pedal frame, y absolute)"""
    c = X((s0 + s1) / 2, (n0 + n1) / 2)
    return Pos(c[0], (y0 + y1) / 2, c[1]) * Rot(0, -LEAN, 0) * Box(s1 - s0, y1 - y0, n1 - n0)
def pcyl_y(s, n, y0, y1, d):
    c = X(s, n)
    return Pos(c[0], (y0 + y1) / 2, c[1]) * Rot(90, 0, 0) * Cylinder(d / 2, y1 - y0)
def pcyl_n(s, dy_y, n0, n1, d):
    c = X(s, (n0 + n1) / 2)
    return Pos(c[0], dy_y, c[1]) * Rot(0, -LEAN, 0) * Cylinder(d / 2, n1 - n0)
AX = X(S_T, 3)                                       # toe hinge axis (x, z)

def base_left():
    y = PY
    b = pbox(0, S_T - 2, -3, 3, y - W2, y + W2)                                   # lower plate (heel + ball of the foot)
    b -= pbox(S_T - 8, S_T, -4, 4, y - 31.5, y + 31.5)                            # notch for the toe barrel
    for k in range(2):                                                            # 2 windows in the lower plate (mass)
        sk = 45 + 42 * k
        b -= pbox(sk - 15, sk + 15, -4, 4, y - 23, y + 23)
    b += pbox(S_T + 7, L - 2, 3, 9, y - W2, y + W2)                               # back plate (toe plate lands on it)
    for dy in (-30, 30):
        b += pbox(10, S_T - 8, 3, 3 + P.RIB, y + dy - 3, y + dy + 3)              # ribs (as v3), split at the toe barrel
        b += pbox(S_T + 7, L - 10, 3, 3 + P.RIB, y + dy - 3, y + dy + 3)
    for sg in (1, -1):
        y0, y1 = sorted((y + sg * (TW2 + 0.8), y + sg * W2))
        b += pbox(S_T - 10, L - 2, -3, 9, y0, y1)                                 # side walls (toe plate sits between them)
        b += pbox(60, L - 10, 3, 3 + P.RIB, y0, y1)                               # wall ribs behind (deep section over the feet)
        k0, k1 = sorted((y + sg * 32, y + sg * W2))
        b += pcyl_y(S_T, 3, k0, k1, 12)                                           # knuckles
    b -= pcyl_y(S_T, 3, y - W2 - 1, y + W2 + 1, PIN_D + 0.3)                      # toe pin (free)
    b += pcyl_n(SP, y, 3, 13, 18)                                                 # spring boss
    b -= pcyl_n(SP, y, 2.9, 11, 12.6)                                             # spring pocket 8 deep
    # heel: hinge boss on the v3 pin, notches for the carriage ears (as v3)
    c = (HX, HZ)
    b -= box(HX - 30, HX + 30, y - 51, y - 37, HZ - 20, HZ + 40); b -= box(HX - 30, HX + 30, y + 37, y + 51, HZ - 20, HZ + 40)
    b += Pos(HX, y, HZ) * Rot(90, 0, 0) * Cylinder(9, 72)
    b -= Pos(HX, y, HZ) * Rot(90, 0, 0) * Cylinder(4.1, 104)
    # feet on the v3 stop posts (top plane of the post = rib plane at LEAN - BRK through STOP)
    tb = math.radians(LEAN - P.BRK); Nb = (math.sin(tb), -math.cos(tb))
    for dy in (-30, 30):
        col = box(P.STOP_X - 10, P.STOP_X + 10, y + dy - 10, y + dy + 10, P.STOP_Z - 40, P.STOP_Z + 120)
        col -= Pos(P.STOP_X + Nb[0] * 99.4, y + dy, P.STOP_Z + Nb[1] * 99.4) * Rot(0, -(LEAN - P.BRK), 0) * Box(400, 40, 200)   # below the post top
        col &= pbox(-50, L + 50, 2.5, 200, y + dy - 10, y + dy + 10)              # only behind the plate back face
        col -= cz(P.STOP_X, y + dy, P.STOP_Z - 41, P.STOP_Z + 121, 4.5)           # M4 into the post (drill Ø3.3 in the post)
        col -= cz(P.STOP_X, y + dy, P.STOP_Z + 18, P.STOP_Z + 121, 8.5)           # counterbore from above
        b += col
        b -= cz(P.STOP_X, y + dy, P.STOP_Z + 18, P.STOP_Z + 121, 8.5)             # (through the plate for the screwdriver)
    # sensor cap screws (outboard wall, +y on the left pedal)
    for ds in (-15, 15):
        c2 = X(S_T + ds, 3)
        b -= Pos(c2[0], y + W2 - 3, c2[1]) * Rot(90, 0, 0) * Cylinder(1.4, 8)
    return b

def toe_left(rest=True):
    y = PY
    t = pbox(S_T + 1, L, -3, 3, y - TW2, y + TW2)
    for sg in (1, -1):
        y0, y1 = sorted((y + sg * 31, y + sg * (TW2 + 1)))
        t -= pbox(S_T, S_T + 7.5, -4, 4, y0, y1)                                  # clear the knuckles
    t += pcyl_y(S_T, 3, y - 30.5, y + 30.5, 12)                                   # barrel
    t += pbox(L - 10, L, -15, -2.9, y - TW2, y + TW2)                             # toe lip
    t -= pcyl_y(S_T, 3, y - 31, y + 31, PIN_D - 0.1)                              # pin (glued)
    t -= pcyl_n(SP, y, -1, 3.1, 12.6)                                             # spring pocket 4 deep
    for k in range(2):
        sk = S_T + 30 + 40 * k                                                    # grip grooves on the foot face
        for j in range(3):
            t -= pbox(sk + j * 8, sk + j * 8 + 3, -3.1, -2.2, y - TW2 + 6, y + TW2 - 6)
    if rest: t = t.rotate(Axis((AX[0], 0, AX[1]), (0, 1, 0)), -BT)
    return t

def cap_left():
    y = PY
    yb = y + W2 + 4.0                                       # board inner face (pin end y + W2 + 1.5, magnet 1.5 -> 1 mm gap)
    c = X(S_T, 3)
    cap = pbox(S_T - 19, S_T + 19, -9, 15, yb, yb + 6) - pbox(S_T - 12, S_T + 12, -8.5, 14.5, yb - 0.1, yb + 1.7)
    for ds in (-15, 15):
        cap += pbox(S_T + ds - 4, S_T + ds + 4, -1, 7, y + W2, yb)
        c2 = X(S_T + ds, 3)
        cap -= Pos(c2[0], yb, c2[1]) * Rot(90, 0, 0) * Cylinder(1.7, 30)
    cap -= pbox(S_T - 9, S_T + 9, -6, 12, y + W2 - 0.1, yb + 0.1)             # chip / magnet clearance
    cap -= pbox(S_T + 6, S_T + 19.5, 1, 5, yb + 1, yb + 3)                     # wire exit
    return cap

def mirror_y(s): return mirror(s, Plane.XZ)

parts = {}
def part(name, shape, group, kind="print", note="", material="PLA", orient="", fill=0.25):
    if kind == "print": fill = auto_fill(shape, fill)
    parts[name] = dict(shape=shape, group=group, kind=kind, note=note, material=material, orient=orient, fill=fill)

shapes_L = dict(base=base_left(), toe=toe_left(), cap=cap_left())
for sgn, nm in ((1, "L"), (-1, "R")):
    f = (lambda s: s) if sgn > 0 else mirror_y
    y = sgn * PY
    part(f"pedal_base_{nm}", f(shapes_L["base"]), f"car{nm}", note="페달 바탕 (고정): v3 페달 판 자리. 뒤꿈치 Ø8 핀 + 발 2 개가 v3 멈춤 기둥 위 (M4 1 개씩). 위쪽 = 발끝 판이 눕는 뒤판 + 옆벽",
         orient="뒤판/갈비를 위로 (발 닿는 면을 바닥에), 채움 25 %, 벽 4 겹", fill=0.25)
    part(f"toe_plate_{nm}", f(shapes_L["toe"]), f"toe{nm}", note=f"발끝 판 86×105 (경첩 = 발볼, 쉴 때 {BT:.0f}° 들림, 끝까지 누르면 바탕 뒤판에 납작하게 닿음 = 멈춤)",
         orient="발 닿는 면을 바닥에, 채움 30 %", fill=0.3)
    part(f"toe_sensor_cap_{nm}", f(shapes_L["cap"]), f"car{nm}", note="AS5600 덮개 (바깥 옆벽, M3 2 개)", orient="바깥면을 바닥에")
    pin = pcyl_y(S_T, 3, PY - W2 + 1, PY + W2 + 1.5, PIN_D)
    part(f"toe_pin_{nm}", f(pin), f"toe{nm}", kind="buy", material="steel",
         note="Ø6 SUS304 (비자성) 핀 99 mm: 발끝 판 통에 접착, 바탕 귀에서 돎, 바깥 끝에 자석")
    mg = pcyl_y(S_T, 3, PY + W2 + 1.5, PY + W2 + 3, 6)
    part(f"toe_magnet_{nm}", f(mg), f"toe{nm}", kind="buy", material="NdFeB", note="자석 Ø6×2.5 직경 방향 (핀 끝 접착)")
    part(f"toe_spring_{nm}", f(pcyl_n(SP, PY, 3, 3 + (SP - S_T) * math.sin(math.radians(BT)), SPRING["od"])), f"car{nm}", kind="buy", material="steel",
         note=f"압축 스프링 OD {SPRING['od']} × 자유 {SPRING['free']} (밀착 ≤ {SPRING['solid_max']}, k ≈ {SPRING['k']} N/mm, 추정)")
    c = X(S_T, 3)
    yb = PY + W2 + 4.0
    part(f"as5600_toe_{nm}", f(pbox(S_T - 11.5, S_T + 11.5, -8.5, 14.5, yb, yb + 1.6)), f"car{nm}", kind="buy", material="PCB", note="AS5600 (발끝 브레이크)")

def posed(name, b=0.0):
    s = parts[name]["shape"]
    if parts[name]["group"].startswith("toe") and b: s = s.rotate(Axis((AX[0], 0, AX[1]), (0, 1, 0)), b)
    return s

def spring_force():
    lift = lambda b: (SP - S_T) * math.sin(math.radians(BT - b))                 # gap at the spring vs brake angle b
    pockets = 8 + 4
    out = []
    for b in [0, BT / 4, BT / 2, 3 * BT / 4, BT]:
        Lsp = pockets + lift(b); Fs = SPRING["k"] * max(0, SPRING["free"] - Lsp)
        out.append(dict(brake_deg=round(b, 1), spring_len=round(Lsp, 1), spring_N=round(Fs, 1), toe_N_at_s200=round(Fs * (SP - S_T) / (200 - S_T), 1)))
    return out

def strength():
    """Stomp 1000 N on the toe plate (normal, at s = 200), toe bottomed on the base back plate. 추정."""
    M = PLA_MECH; F = 1000.0; sF = 200.0
    # where does the foot (post) support the base, in plate s?
    sx = (P.STOP_X - HX) * U[0] + (P.STOP_Z - HZ) * U[1]
    R = F * sF / sx                                                        # both feet together; heel pin takes R - F the other way
    Mb = F * (sF - sx)
    # base section at the feet: back plate 100x6 (n 3..9) + 2 ribs 6x22 (n 3..25) + 2 walls 6.5x12 (n -3..9)
    secs = [(100 * 6, 6, 100 * 6 ** 3 / 12), (2 * 6 * P.RIB, 3 + P.RIB / 2, 2 * 6 * P.RIB ** 3 / 12), (2 * 6.2 * (P.RIB + 6), (P.RIB) / 2, 2 * 6.2 * (P.RIB + 6) ** 3 / 12)]
    A = sum(a for a, _, _ in secs); yc = sum(a * c for a, c, _ in secs) / A
    I = sum(i + a * (c - yc) ** 2 for a, c, i in secs); Z = I / max(3 + P.RIB - yc, yc + 3)
    Lp = P.STOP_Z - P.CAR_Z; Ip = (20 ** 4 - 17.6 ** 4) / 12
    rows = [sf("바탕 굽힘 (발 위, 뒤판 + 갈비 2 + 옆벽 2 (깊이 28))", Mb / Z, M["xy"], note="눕혀 출력 → 굽힘은 층 안"),
            sf("발끝 판 → 뒤판 눌림 (86×100 전면)", F / (86 * 100), M["comp"]),
            sf("발 (20×20, 2 개) 눌림", R / 2 / 400, M["comp"]),
            sf("v3 멈춤 기둥 좌굴 (20×20 껍데기만, 2 개)", R / 2, math.pi ** 2 * M["E"] * Ip / (2 * Lp) ** 2, unit="N", note="v3 와 같은 기둥 · 같은 식"),
            sf("뒤꿈치 Ø8 핀 굽힘 (귀 사이 86, 가운데 힘)", abs(R - F) * 86 / 4 / (math.pi * 8 ** 3 / 32), 500, note="연마봉 항복 약 500 MPa (추정)"),
            sf("발끝 Ø6 핀 (쉴 때 밟음: 스프링이 눌리는 동안 힘은 스프링 + 경첩, 경첩 몫 ≤ 1000 N 로 봄) 전단", F / 2 / (math.pi * PIN_D ** 2 / 4), 0.6 * 200,
               note="SUS304 항복 200 의 0.6 (추정). 실제는 판이 곧 뒤판에 닿아 훨씬 작음"),
            sf("귀 (바탕) 구멍 눌림 Ø6 × 귀 길이 18 × 2", F / 2 / (PIN_D * 18), M["comp"])]
    return dict(F=F, s_load=sF, s_feet=round(sx, 1), feet_force_N=round(R), rows=rows,
                note="발끝을 끝까지 밟은 1000 N (판에 수직, 경첩에서 75 mm 위). 발끝 판이 바탕 뒤판에 닿아 있으므로 힘은 바탕 → 발 → v3 멈춤 기둥 / 뒤꿈치 핀으로. PLA 층 안 50 / 층 사이 20 / 압축 60 MPa (추정)")

BUY = [  # both pedals, KRW (추정)
    ("Ø6 SUS304 봉 100 mm", 2, 3000, "발끝 경첩 핀 (비자성)"), ("자석 Ø6×2.5 직경 방향", 2, 1000, ""), ("AS5600 모듈", 2, 6000, "아날로그 OUT"),
    ("압축 스프링 OD 12 × 26 (k 약 6 N/mm, 밀착 ≤ 11)", 2, 2000, "세기는 스프링 교체로"), ("M3 · M4 나사", 1, 2000, "M4×40 ×4 (발 → 기둥), M3 ×4"),
    ("3심 차폐 케이블 1.5 m", 2, 3000, "3.3 V · GND · OUT"),
]

if __name__ == "__main__":
    import itertools
    # interference: new parts vs each other and vs the v3 carriage (same side), at rest / half / full brake
    car = {nm: P.parts[f"carriage_{nm}"]["shape"] for nm in ("L", "R")}
    allow = set()
    for nm in ("L", "R"):
        allow |= {frozenset(p) for p in [(f"pedal_base_{nm}", f"toe_pin_{nm}"), (f"toe_plate_{nm}", f"toe_pin_{nm}"), (f"toe_pin_{nm}", f"toe_magnet_{nm}"),
                                         (f"pedal_base_{nm}", f"toe_spring_{nm}"), (f"toe_plate_{nm}", f"toe_spring_{nm}"), (f"pedal_base_{nm}", f"toe_sensor_cap_{nm}"),
                                         (f"toe_sensor_cap_{nm}", f"as5600_toe_{nm}"), (f"toe_sensor_cap_{nm}", f"toe_magnet_{nm}")]}
    checks = []
    for b in (0, BT / 2, BT - 1):
        hits = []
        for a, c in itertools.combinations(parts, 2):
            if frozenset((a, c)) in allow: continue
            try: v = (posed(a, b) & posed(c, b)).volume
            except Exception: v = 0
            if v > 0.5: hits.append(f"{a}x{c} {v:.0f}")
        for nm in ("L", "R"):
            for n2 in (f"pedal_base_{nm}", f"toe_plate_{nm}", f"toe_sensor_cap_{nm}"):
                try: v = (posed(n2, b) & car[nm]).volume
                except Exception: v = 0
                if v > 0.5: hits.append(f"{n2}xcarriage_{nm}(v3) {v:.0f}")
        checks.append(dict(brake_deg=round(b, 1), hits=hits))
    def stop_at():
        for k in range(0, 40):
            b = BT - 1 + k * 0.1
            if (posed("toe_plate_L", b) & parts["pedal_base_L"]["shape"]).volume > 0.3: return round(b, 2)  # first contact
        return None
    stop = stop_at()
    os.makedirs(OUT, exist_ok=True)
    for f_ in os.listdir(OUT):
        if f_.endswith(".stl"): os.remove(os.path.join(OUT, f_))
    info = []
    for name, p in parts.items():
        export_stl(p["shape"], os.path.join(OUT, name + ".stl"), tolerance=0.05, angular_tolerance=0.2)
        bb = p["shape"].bounding_box(); vol = p["shape"].volume / 1000
        info.append(dict(name=name, group=p["group"], kind=p["kind"], note=p["note"], material=p["material"],
                         size=[round(bb.size.X, 1), round(bb.size.Y, 1), round(bb.size.Z, 1)], volume_cm3=round(vol, 1),
                         grams=round(vol * 1.24 * p["fill"], 1) if p["kind"] == "print" else None, orient=p.get("orient", ""), file=f"{name}.stl"))
    stg = strength()
    data = dict(meta=dict(created=datetime.now().isoformat(timespec="seconds"), version="brakes v4", inputs="pedals.py v3 (carriage, HX/HZ, LEAN, STOP posts)",
                          toe_hinge_s=S_T, brake_deg=BT, spring_s=SP, spring=SPRING, hinge_axis_xz=[round(AX[0], 2), round(AX[1], 2)],
                          sensor="AS5600 analog OUT -> STM32F103 ADC (FreeJoy)"),
                parts=info, buy=[dict(name=a, qty=b, krw=c, note=d) for a, b, c, d in BUY], spring_curve=spring_force(), strength=stg, check=checks, stop_hit_deg=stop)
    json.dump(data, open(os.path.join(OUT, "parts.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    for i in info: print(f"{i['name']:20s} {i['kind']:5s} {i['size']} {i['grams'] or ''}")
    for c in checks: print("brake", c["brake_deg"], c["hits"] or "none")
    print("toe stop at", stop, "feet s", stg["s_feet"], "feet N", stg["feet_force_N"])
    for r in stg["rows"]: print(f"SF {r['sf']:6.2f}  {r['load']:8.2f}/{r['limit']} {r['unit']}  {r['name']}")
    for r in spring_force(): print(r)
