"""Throttle v4 (simple, all PLA) for the gyro sim chair — left hand, on the existing left throttle shelf. build123d.

Run:  python throttle_v4.py   -> stl/*.stl, parts.json (BOM, button map, strength), interference check over the lever range

Idea (based on public DIY F-16 throttles, see README.md for attribution; no third-party geometry is copied):
  * ONE lever on a Ø8 stainless shaft in 2 x 608 bearings (one in each cheek of a one-piece printed frame).
  * mechanical stops = a lug under the hub hits 2 stop blocks that are part of the frame (no gate, no lift-over).
  * friction = felt pad on a printed shoe pressed on the hub by an M6 thumb screw (+ small spring) from behind.
  * sensor = AS5600 on the shaft end (+y side), diametric magnet glued in the end of the NON-magnetic shaft.
    FreeJoy reads only ONE AS5600 over I2C -> every AS5600 here is used in ANALOG mode (OUT pin -> STM32 ADC).
  * grip = our own simplified F-16-like grip, 2 halves split at y = 0, 10 inputs read by 2 x 74HC165 in the grip.

Coordinates (mm): x = forward (push = more thrust), y = left, z = up. Origin = centre of the frame underside.
Printed parts (6): frame, lever, grip_L, grip_R, friction_shoe, sensor_cap.
"""
import math, os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from build123d import Axis, Pos, Rot, Box, Plane, Polyline, make_face, extrude, fillet
from ctl_lib import box, cx, cy, cz, tube, bearing, export_parts, check_pairs, auto_fill, PLA_MECH, C0_608, sf

HERE = os.path.dirname(os.path.abspath(__file__))
PZ = 60                     # pivot height above the frame underside
HUB_R, HUB_W = 20, 40       # hub radius, width (|y| <= 20)
CH = (21, 31)               # cheek |y| range (10 thick, 608 seat 7 deep from outside)
ARM = (14, 10, 110)         # arm half-x, half-y, top above the pivot
TRAVEL = (-30, 30)          # lever angle range deg (+ = forward = more thrust)
GAP = 0.4                   # arm -> stop bar gap at the end of travel (rubber pad 0.4..1 mm optional)
GRIP_Z0 = PZ + ARM[2] - 34  # grip underside (socket 34 deep over the arm top)
L_HAND = GRIP_Z0 + 55 - PZ  # pivot -> palm centre
FL = (-75, 95, -45, 45, 6)  # floor x0, x1, y0, y1, thickness (= v3 base plate, same 4 x M6 shelf holes)

parts = {}
def part(name, shape, group, kind="print", note="", material="PLA", orient="", fill=0.25):
    if kind == "print": fill = auto_fill(shape, fill)
    parts[name] = dict(shape=shape, group=group, kind=kind, note=note, material=material, orient=orient, fill=fill)

def rot_y(shape, ang, c=(0, 0, PZ)):
    return shape.rotate(Axis(c, (0, 1, 0)), ang) if ang else shape

# ---------------- frame (one print) ----------------
x0, x1, y0, y1, ft = FL
fr = box(x0, x1, y0, y1, 0, ft)
for x in (-60, 80):
    for y in (-32, 32):
        fr -= cz(x, y, -1, ft + 1, 6.5)                                  # M6 to the shelf (same holes as v3)
for s in (1, -1):
    yi, yo = sorted((s * CH[0], s * CH[1]))
    ch = box(-34, 34, yi, yo, 0, PZ + 14) + cy(0, PZ, yi, yo, 68)
    ch -= box(-40, 40, yi - 1, yo + 1, PZ + 22, PZ + 60)
    ch -= cy(0, PZ, yi - 1, yo + 1, 10.5)                                # shaft clearance
    ch -= cy(0, PZ, s * (CH[1] - 7), s * CH[1] + s, 22.1)                # 608 seat from outside (press fit, check 22.0..22.2)
    fr += ch
    fr += box(-44, -34, yi, yo, 0, 26)                                   # rear gusset
    fr += box(34, 44, yi, yo, 0, 26)                                     # front gusset
# stop bars: two cross bars (fused through both cheeks) just beside the ARM at r 36..56 above the pivot, rotated to the travel
# ends -> the arm face lands flat on the bar. Stop force is opposite to the hand force, so the shaft only sees the difference.
STOP_R = (36, 56)
def stop_bar(side):                     # side +1 = front bar (forward stop), -1 = rear bar (back stop)
    a = TRAVEL[1] if side > 0 else TRAVEL[0]
    xa, xb = (ARM[0] + GAP, ARM[0] + GAP + 12) if side > 0 else (-ARM[0] - GAP - 12, -ARM[0] - GAP)
    b = rot_y(box(xa, xb, -CH[1], CH[1], PZ + STOP_R[0], PZ + STOP_R[1]), a)
    bb = b.bounding_box()
    for s_ in (1, -1):                  # cheek web under the bar (cheek y band only, outside every moving part)
        yi, yo = sorted((s_ * CH[0], s_ * CH[1]))
        b += box(bb.min.X, bb.max.X, yi, yo, 0, (bb.min.Z + bb.max.Z) / 2)
    return b
for side in (-1, 1):
    fr += stop_bar(side)
# friction boss (rear, +y band): M6 thumb screw along x, square shoe channel 12 (z) x 10 (y)
FY = (12.0, 20.5)
boss = box(-HUB_R - 24, -HUB_R - 1, ARM[1] + 0.6, CH[0] + 0.5, PZ - 10, PZ + 10)
boss += box(-HUB_R - 24, -HUB_R - 14, ARM[1] + 0.6, CH[0] + 0.5, ft - 0.5, PZ - 9)          # post down to the floor
boss -= box(-HUB_R - 15, -HUB_R - 0.9, FY[0] - 0.2, FY[1] + 0.2, PZ - 6.2, PZ + 6.2)        # shoe channel
boss -= cx((FY[0] + FY[1]) / 2, PZ, -HUB_R - 25, -HUB_R - 10, 5.0)                       # M6 thread (tap) / or M6 nut in the slot below
boss -= box(-HUB_R - 21, -HUB_R - 15.5, (FY[0] + FY[1]) / 2 - 5.6, (FY[0] + FY[1]) / 2 + 5.6, PZ - 5.6, PZ + 20)  # M6 nut slot from the top
fr += boss
for z in (PZ - 8, PZ + 8):                                               # sensor cap screws (M3 into heat inserts / self-tap)
    fr -= cy(-24, z, CH[1] - 8, CH[1] + 1, 2.8)
fr -= box(-30, 30, -3, 3, -1, 2)                                         # cable groove under the frame (to the board)
part("frame", fr, "fixed", note="틀 (한 덩어리): 바닥 170×90 (v3 와 같은 M6 구멍 4 개) + 양 볼 (608 자리) + 앞뒤 멈춤 막대 2 (팔이 닿음) + 마찰 보스",
     orient="바닥면을 바닥에, 채움 30 %, 벽 4 겹", fill=0.3)
for s, nm in ((1, "L"), (-1, "R")):
    part(f"bearing_{nm}", bearing("y", (0, PZ), s * (CH[1] - 7), s * CH[1]), "fixed", kind="buy", material="steel", note="608-2RS")

# friction shoe + felt + thumb screw
FXC = -HUB_R - 0.5
shoe = box(FXC - 12, FXC - 3, FY[0] + 0.1, FY[1] - 0.1, PZ - 6, PZ + 6) - cy(0, PZ, FY[0] - 1, FY[1] + 1, 2 * HUB_R + 6)
part("friction_shoe", shoe, "fixed", note="마찰 신발 (앞면에 펠트 3 mm 접착): 나사가 뒤에서 밀어 허브 원통면을 누름", orient="옆면을 바닥에, 채움 100 %", fill=1.0)
part("felt_pad", box(FXC - 3, FXC, FY[0] + 0.5, FY[1] - 0.5, PZ - 5.5, PZ + 5.5) - cy(0, PZ, FY[0], FY[1], 2 * HUB_R + 0.4), "fixed", kind="buy", material="felt",
     note="펠트 3 mm 조각 10×11 (양면테이프)")
part("friction_screw", cx((FY[0] + FY[1]) / 2, PZ, -HUB_R - 46, -HUB_R - 12, 6) + cx((FY[0] + FY[1]) / 2, PZ, -HUB_R - 56, -HUB_R - 46, 22), "fixed",
     kind="buy", material="steel", note="M6×40 별 손잡이 나사 + 너트 + 작은 압축 스프링 (조임 감 부드럽게)")

# sensor cap (+y side): AS5600 board 23 x 23 pocket, chip 2 mm from the magnet
SY = CH[1] + 3.5                                                         # board inner face
cap = box(-30, 14, SY, SY + 7, PZ - 15, PZ + 15) - box(-12, 12, SY - 0.1, SY + 1.7, PZ - 12, PZ + 12)   # board pocket 1.6 + slack
cap += box(-30, -18, CH[1], SY, PZ - 15, PZ + 15)                         # standoff to the cheek
cap -= box(-11, 11, SY - 4, SY + 0.1, PZ - 6, PZ + 6)                     # chip / magnet clearance
for z in (PZ - 8, PZ + 8):
    cap -= cy(-24, z, CH[1] - 1, SY + 8, 3.4)
cap -= box(4, 15, SY + 1, SY + 3, PZ - 4, PZ + 4)                         # wire exit
part("sensor_cap", cap, "fixed", note="AS5600 덮개/받침 (+y 볼 바깥, M3 2 개): 칩이 자석에서 약 2 mm", orient="바깥면을 바닥에")
part("as5600", box(-11.5, 11.5, SY, SY + 1.6, PZ - 11.5, PZ + 11.5), "fixed", kind="buy", material="PCB", note="AS5600 보드 (아날로그 OUT → STM32 ADC, 3.3 V 전원)")

# ---------------- lever (one print) ----------------
lev = cy(0, PZ, -HUB_W / 2, HUB_W / 2, 2 * HUB_R)
lev += box(-ARM[0], ARM[0], -ARM[1], ARM[1], PZ, PZ + ARM[2])
lev -= cy(0, PZ, -HUB_W / 2 - 1, HUB_W / 2 + 1, 8.15)                    # shaft
lev -= cz(0, -10, PZ - 1, PZ + HUB_R + 1, 2.8)                            # M3 grub on the shaft (shaft has a flat), from the top
lev -= box(-3.1, 25, -12.6, -7.4, PZ + 9, PZ + 11.6)                      # M3 nut slot, inserted from +x
lev -= cy(0, PZ + ARM[2] - 12, -ARM[1] - 1, ARM[1] + 1, 4.3)              # M4 cross bolt (grip)
lev -= cy(0, PZ + ARM[2] - 28, -ARM[1] - 1, ARM[1] + 1, 4.3)
lev -= box(-3.5, 3.5, -ARM[1] - 1, -ARM[1] + 4, PZ + 4, PZ + ARM[2] + 1)  # cable groove along the arm (-y face)
part("lever", lev, "lever", note="레버 (한 덩어리): 허브 Ø40×40 + 팔 28×20 (팔 옆면이 멈춤 막대에 닿음). Ø8 축에 M3 무두나사",
     orient="옆면 (y) 을 바닥에 눕혀 (팔 굽힘이 층 안), 채움 40 %, 벽 4 겹", fill=0.4)
part("shaft", cy(0, PZ, -CH[1] - 1, CH[1] + 1.5, 8), "lever", kind="buy", material="steel", note="Ø8 스테인리스 (SUS304, 비자성) 봉 64 mm, 한쪽 끝 Ø6×2.5 자석 홈, 무두나사 자리 평면")
part("magnet", cy(0, PZ, CH[1] + 1.5, CH[1] + 3.0, 6), "lever", kind="buy", material="NdFeB", note="자석 Ø6×2.5 직경 방향 (축 끝에 접착, 축 끝면에서 1.5 mm 튀어나옴)")

# ---------------- grip (our own simplified F-16-like grip, 2 halves) ----------------
# side profile in x-z (grip frame, z from the grip underside): front face leans forward, top slopes down to the rear
PROF = [(-42, 0), (36, 0), (48, 40), (50, 70), (40, 92), (10, 100), (-26, 92), (-44, 70), (-50, 40)]
GW = 54                                                     # width (y)
def grip_body():
    f = make_face(Polyline(*[(x, z) for x, z in PROF], close=True))
    b = extrude(Plane.XZ * f, amount=GW / 2, both=True)     # Plane.XZ: local x = X, local y = Z, normal -Y
    try:
        b = fillet(b.edges(), 6)
    except Exception:
        pass
    return Pos(0, 0, GRIP_Z0) * b
body = grip_body()
inner = Pos(0, 0, GRIP_Z0) * extrude(Plane.XZ * make_face(Polyline(*[(x * 0.86 + 1, z * 0.86 + 8) for x, z in PROF], close=True)), amount=GW / 2 - 3.2, both=True)
g = body - inner
g -= box(-ARM[0] - 0.3, ARM[0] + 0.3, -ARM[1] - 0.3, ARM[1] + 0.3, GRIP_Z0 - 1, GRIP_Z0 + 35)   # socket over the arm
g += (box(-ARM[0] - 4, ARM[0] + 4, -ARM[1] - 4, ARM[1] + 4, GRIP_Z0, GRIP_Z0 + 38)
      - box(-ARM[0] - 0.3, ARM[0] + 0.3, -ARM[1] - 0.3, ARM[1] + 0.3, GRIP_Z0 - 1, GRIP_Z0 + 34.3))     # socket walls
g -= cz(0, -8, GRIP_Z0 + 33, GRIP_Z0 + 41, 7)                           # cable hole into the cavity (above the arm groove)
for zc in (PZ + ARM[2] - 12, PZ + ARM[2] - 28):
    g -= cy(0, zc, -GW, GW, 4.3)                                       # M4 cross bolts (through grip + arm)
# button holes  (inboard = -y = thumb side on a LEFT-hand throttle)
HOLES = {
    "comms_hat": ("z", (22, -8), 14, "5방향 택트 (4방향 햇 + 누름) — 통신 스위치, 엄지 앞쪽 위"),
    "uncage_btn": ("z", (-8, -10), 12.2, "12 mm 누름 버튼 — 미사일 언케이지 / 커서 클릭, 위 뒤쪽"),
    "dogfight_sw": ("y-", (30, 62), 6.2, "MTS-103 3단 토글 (on-off-on) — 도그파이트 / 미사일 오버라이드, 안쪽 면 앞"),
    "speedbrake_sw": ("y-", (-20, 58), 6.2, "MTS-123 3단 (on)-off-on — 스피드브레이크 (뒤 = 펴기 순간, 앞 = 접기 유지), 안쪽 면 뒤"),
    "index_btn": ("x+", (12, 66), 12.2, "12 mm 누름 버튼 — 검지 (커서 사용/IFF 등 아무 기능), 앞면"),
}
for k, (ax, (u, v), d, _) in HOLES.items():
    if ax == "z":
        g -= cz(u, v, GRIP_Z0 + 60, GRIP_Z0 + 110, d)
    elif ax == "y-":
        g -= cy(u, GRIP_Z0 + v, -GW / 2 - 2, -GW / 2 + 6, d)
    elif ax == "x+":
        g -= cx(-10, GRIP_Z0 + v, 30, 60, d)
g -= box(22 - 7.2, 22 + 7.2, -8 - 7.2, -8 + 7.2, GRIP_Z0 + 60, GRIP_Z0 + 110)   # square 14.4 for the 5-way module cap
# clamshell screws: 3 x M3 through (+y half: head counterbore, -y half: nut trap)
CS = [(-30, 30), (32, 30), (5, 82)]
for (u, v) in CS:
    g += cy(u, GRIP_Z0 + v, -GW / 2 + 1, GW / 2 - 1, 9)               # bosses across the cavity
    g -= cy(u, GRIP_Z0 + v, -GW, GW, 3.4)
    g -= cy(u, GRIP_Z0 + v, GW / 2 - 4, GW, 6.2)                         # head counterbore (+y)
    g -= cy(u, GRIP_Z0 + v, -GW, -GW / 2 + 3.5, 6.6)                     # nut trap (-y, round approx of M3 hex 5.5 AF)
gL = g & box(-80, 80, 0, 60, 0, 400)
gR = g & box(-80, 80, -60, 0, 0, 400)
part("grip_L", gL, "lever", note="손잡이 바깥 반쪽 (+y, 손바닥 쪽): M3 3 개로 안쪽 반쪽과 조임, 팔에 M4 2 개", orient="자른 면 (y = 0) 을 바닥에, 서포트 조금", fill=0.25)
part("grip_R", gR, "lever", note="손잡이 안쪽 반쪽 (−y, 엄지 쪽): 버튼 구멍 5 곳, 너트 홈 3", orient="자른 면 (y = 0) 을 바닥에, 서포트 조금", fill=0.25)
part("buttons", cz(22, -8, GRIP_Z0 + 96, GRIP_Z0 + 106, 12) + cz(-8, -10, GRIP_Z0 + 88, GRIP_Z0 + 98, 11) + cx(-10, GRIP_Z0 + 66, 46, 54, 11)
     + cy(30, GRIP_Z0 + 62, -GW / 2 - 9, -GW / 2 + 2, 5) + cy(-20, GRIP_Z0 + 58, -GW / 2 - 9, -GW / 2 + 2, 5), "lever", kind="buy", material="steel",
     note="버튼 · 스위치 (보기용 자리만): 5방향 택트 1, 12 mm 누름 2, 미니 토글 2")

# ---------------- checks ----------------
def posed(name, ang):
    s = parts[name]["shape"]
    return rot_y(s, ang) if parts[name]["group"] == "lever" else s

MATES = [("frame", "bearing_L"), ("frame", "bearing_R"), ("shaft", "bearing_L"), ("shaft", "bearing_R"), ("shaft", "lever"), ("shaft", "magnet"),
         ("frame", "friction_shoe"), ("friction_shoe", "felt_pad"), ("felt_pad", "lever"), ("frame", "friction_screw"), ("friction_screw", "friction_shoe"),
         ("frame", "sensor_cap"), ("sensor_cap", "as5600"), ("lever", "grip_L"), ("lever", "grip_R"), ("grip_L", "grip_R"), ("buttons", "grip_R"),
         ("buttons", "grip_L"), ("frame", "felt_pad"), ("shaft", "frame"), ("magnet", "sensor_cap")]
ALLOW = {frozenset(p) for p in MATES}

def strength():
    """Panic: 300 N horizontal on the grip (hand slam, 추정), lever at a stop. Friction: shoe force. 추정 = all values."""
    M = PLA_MECH; F = 300.0; Lh = L_HAND
    T = F * Lh                                                   # N*mm about the pivot
    rs = (STOP_R[0] + STOP_R[1]) / 2
    Fs = T / rs                                                  # stop bar force on the arm (opposite to the hand)
    Fsh = Fs - F                                                 # net force on the shaft
    span = 2 * (CH[1] - 3.5); a = (span - HUB_W) / 2             # bearing centres, hub load spread over its width
    Msh = Fsh / 2 * (span / 2) - Fsh / 2 * (HUB_W / 4)
    Zarm = 2 * ARM[1] * (2 * ARM[0]) ** 2 / 6
    rows = [sf("레버 팔 굽힘 (멈춤 막대 자리, 28×20, 눕혀 출력 → 층 안)", F * (Lh - rs) / Zarm, M["xy"]),
            sf("레버 팔 굽힘 (허브 위 뿌리)", abs(F * (Lh - HUB_R) - Fs * (rs - HUB_R)) / Zarm, M["xy"]),
            sf("멈춤 막대 눌림 (팔 옆면 20×20)", Fs / (2 * ARM[1] * (STOP_R[1] - STOP_R[0])), M["comp"]),
            sf("멈춤 막대 굽힘 (볼 사이 42 mm, 12×20 단면, 층 안)", Fs * 2 * CH[0] / 8 / (20 * 12 ** 2 / 6), M["xy"], note="양 끝이 볼에 묶인 보 (단순지지로 봄 = 보수적)"),
            sf("볼 → 바닥 뿌리 굽힘 (막대 힘 × 높이, 볼 2 개)", Fs * (PZ + rs * 0.87) / 2 / (10 * 68 ** 2 / 6), M["z"], note="볼 판 (68×10) 이 x 방향으로 굽음, 굽힘 응력은 층 사이"),
            sf("608 정격 (한 쪽)", Fsh / 2, C0_608, unit="N"),
            sf("Ø8 SUS 축 굽힘 (베어링 사이, 허브 폭에 분포)", Msh / (math.pi * 8 ** 3 / 32), 200, note="SUS304 항복 약 200 MPa (추정)"),
            sf("손잡이 M4 2 개 전단", F / 4 / (math.pi * 3.3 ** 2 / 4), 0.6 * 400, note="4.8 볼트 0.6×400"),
            sf("M4 구멍 눌림 (팔 PLA, 20 mm × Ø4)", F * (Lh - (ARM[2] - 20)) / 16 / (20 * 4), M["comp"], note="손 힘이 위쪽 볼트에 지렛대로 걸림")]
    # friction: holding torque needed vs shoe normal force (μ felt-PLA ~0.3, 추정)
    Fn = 25.0; mu = 0.3
    creep = [sf("마찰 신발 압력 (25 N / 10×11, 계속)", Fn / 110, M["creep"])]
    return dict(panic_N=F, l_hand=round(Lh), stop_force_N=round(Fs), rows=rows, creep=creep,
                friction=dict(shoe_N=Fn, mu=mu, torque_Nm=round(Fn * mu * HUB_R / 1000, 3), hand_N=round(Fn * mu * HUB_R / Lh, 2),
                              note="펠트-PLA μ 0.3 (추정). 25 N 이면 손에서 약 1.2 N 의 미는 힘 — 손잡이가 흘러내리지 않을 정도. 나사로 0~60 N 조절"))

BUTTONS = [
    dict(id="B1-B4", name="통신 햇 4방향 (위/아래/앞/뒤)", part="5방향 택트 스위치 모듈 (10×10 DIP, 누름 포함)", where="위 앞쪽, 엄지", sr="U1 A-D", price=1500),
    dict(id="B5", name="통신 햇 누름", part="(같은 5방향 택트)", where="", sr="U1 E", price=0),
    dict(id="B6-B7", name="도그파이트 / 미사일 오버라이드 (3단)", part="MTS-103 미니 토글 on-off-on", where="안쪽 면 앞", sr="U1 F-G", price=900),
    dict(id="B8-B9", name="스피드브레이크 (3단: 펴기 순간 / 중립 / 접기)", part="MTS-123 미니 토글 (on)-off-on", where="안쪽 면 뒤", sr="U1 H, U2 A", price=1200),
    dict(id="B10", name="언케이지 / 커서 클릭", part="12 mm 택트 + 캡", where="위 뒤쪽", sr="U2 B", price=300),
    dict(id="B11", name="검지 버튼 (자유 배정)", part="12 mm 택트 + 캡", where="앞면", sr="U2 C", price=300),
]

BUY = [  # name, qty, KRW total (추정, 국내 쇼핑몰 2026 대략값), note
    ("608ZZ 베어링", 2, 2000, ""), ("Ø8 SUS304 봉 100 mm (64 mm 로 자름, 끝 평면 1 곳)", 1, 3000, "비자성 — 자석 자리"),
    ("자석 Ø6×2.5 직경 방향 (예비 포함)", 3, 1500, "AS5600 용"), ("AS5600 모듈", 1, 3000, "아날로그 OUT 사용"),
    ("M6×40 별 손잡이 나사 + 너트 + 작은 압축 스프링 + 펠트 3 mm", 1, 4000, "마찰"),
    ("5방향 택트 스위치 모듈 (10×10)", 1, 1500, "통신 햇"), ("MTS-103 미니 토글 on-off-on", 1, 900, "도그파이트"),
    ("MTS-123 미니 토글 (on)-off-on", 1, 1200, "스피드브레이크"), ("12 mm 택트 스위치 + 캡", 2, 600, ""),
    ("74HC165 ×2 + 만능기판 + 10 kΩ 풀업 ×10", 1, 2000, "손잡이 안"), ("6심 케이블 2 m + 커넥터", 1, 3000, "손잡이 → 보드"),
    ("M3 · M4 볼트 · 너트 · 무두나사", 1, 3000, ""),
]

if __name__ == "__main__":
    poses = [TRAVEL[0], -15, 0, 15, TRAVEL[1]]
    res = check_pairs(parts, posed, [(a,) for a in poses], ALLOW)
    # stop check: lug must touch the stop block within 1.5 deg past each travel end
    def stop_at(sign):
        for k in range(0, 40):
            a = (TRAVEL[1] if sign > 0 else TRAVEL[0]) + sign * k * 0.25
            if (posed("lever", a) & parts["frame"]["shape"]).volume > 0.2: return round(a, 2)
        return None
    stops = dict(fwd=stop_at(1), back=stop_at(-1))
    stg = strength()
    info = export_parts(parts, HERE, dict(version="v4", pivot=[0, 0, PZ], travel_deg=list(TRAVEL), l_hand=round(L_HAND), printer=[240, 240, 240],
                                          arc_mm=round(L_HAND * math.radians(TRAVEL[1] - TRAVEL[0])), sensor="AS5600 analog OUT -> STM32F103 ADC (FreeJoy)",
                                          based_on="Spock 'F-16 Viper Throttle' (Printables 552322, CC BY-NC) + Hempstick F-16 grip — reference only, no geometry copied"),
                        extra=dict(check=[dict(pose=p, hits=b) for p, b in res], stops_hit_deg=stops, strength=stg, buttons=BUTTONS, buy=[dict(name=a, qty=b, krw=c, note=d) for a, b, c, d in BUY]))
    for i in info: print(f"{i['name']:16s} {i['group']:6s} {i['kind']:5s} {i['size']} {i['grams'] or ''}")
    for p, b in res: print("pose", p, b if b else "none")
    print("stops hit at", stops, "L_hand", round(L_HAND))
    for r in stg["rows"] + stg["creep"]: print(f"  {r['name']}: {r['load']} / {r['limit']} {r['unit']} SF {r['sf']}")
    print("friction", stg["friction"])
