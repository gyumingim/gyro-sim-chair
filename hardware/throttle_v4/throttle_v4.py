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
from build123d import Axis, Pos, Rot, Box, Plane, Polyline, make_face, extrude, fillet, Solid, Vector, Location
from ctl_lib import box, cx, cy, cz, tube, bearing, export_parts, check_pairs, auto_fill, PLA_MECH, C0_608, sf

HERE = os.path.dirname(os.path.abspath(__file__))
PZ = 60                     # pivot height above the frame underside
HUB_R, HUB_W = 20, 40       # hub radius, width (|y| <= 20)
CH = (21, 31)               # cheek |y| range (10 thick, 608 seat 7 deep from outside)
ARM = (14, 10, 110)         # arm half-x, half-y, top above the pivot
TRAVEL = (-30, 30)          # lever angle range deg (+ = forward = more thrust)
GAP = 0.4                   # arm -> stop bar gap at the end of travel (rubber pad 0.4..1 mm optional)
L_HAND = ARM[2] + 64         # pivot -> palm centre on the public F-16 Viper grip (palm about 64 mm above our lever top, 추정)
FL = (-75, 95, -45, 45, 6)  # floor x0, x1, y0, y1, thickness (= v3 base plate, same 4 x M6 shelf holes)

parts = {}
def part(name, shape, group, kind="print", note="", material="PLA", orient="", fill=0.25):
    if kind == "print": fill = auto_fill(shape, fill)
    parts[name] = dict(shape=shape, group=group, kind=kind, note=note, material=material, orient=orient, fill=fill)

def rot_y(shape, ang, c=(0, 0, PZ)):
    return shape.rotate(Axis(c, (0, 1, 0)), ang) if ang else shape

def soft(shape, r):
    """fillet every edge (falls back to smaller radii, then to the sharp shape)."""
    for rr in (r, r * 0.6, r * 0.35):
        try:
            out = fillet(shape.edges(), rr)
            if out.is_valid: return out
        except Exception:
            pass
    return shape
def rbox(x0, x1, y0, y1, z0, z1, r=2.0): return soft(box(x0, x1, y0, y1, z0, z1), r)
def rcyl_y(x, z, y0, y1, d, r=1.5): return soft(cy(x, z, y0, y1, d), r)
def gusset(xa, xb, h, y0, y1):
    """triangle in x-z (right angle at (xa, 0)), extruded over y0..y1, edges rounded."""
    f = make_face(Polyline((xa, 0), (xb, 0), (xa, h), close=True))
    return soft(Pos(0, y1, 0) * extrude(Plane.XZ * f, amount=y1 - y0), 1.5)
def cbore_z(x, y, z_top, d_hole, d_head, depth, z_bot):
    return cz(x, y, z_bot, z_top + 1, d_hole) + cz(x, y, z_top - depth, z_top + 1, d_head)

# ---------------- frame (one print) ----------------
x0, x1, y0, y1, ft = FL
fr = rbox(x0, x1, y0, y1, 0, ft, 2.5)
for x in (-60, 80):
    for y in (-32, 32):
        fr -= cbore_z(x, y, ft, 6.6, 11.5, 2.5, -1)                       # M6 to the shelf (same holes as v3), heads sunk
for s in (1, -1):
    yi, yo = sorted((s * CH[0], s * CH[1]))
    ch = rbox(-34, 34, yi, yo, 0, PZ, 2) + rcyl_y(0, PZ, yi, yo, 68, 2)
    ch -= box(-40, 40, yi - 1, yo + 1, PZ + 24, PZ + 60)
    ch = soft(ch, 1.5)
    ch -= cy(0, PZ, yi - 1, yo + 1, 10.5)                                # shaft clearance
    ch -= cy(0, PZ, s * (CH[1] - 7), s * CH[1] + s, 22.1)                # 608 seat from outside (press fit, check 22.0..22.2)
    fr += ch
    fr += gusset(-34, -58, 34, yi, yo) + gusset(34, 58, 34, yi, yo)      # rounded triangular gussets front / rear
STOP_R = (36, 56)
def stop_bar(side):                     # side +1 = front bar (forward stop), -1 = rear bar (back stop)
    a = TRAVEL[1] if side > 0 else TRAVEL[0]
    xa, xb = (ARM[0] + GAP, ARM[0] + GAP + 12) if side > 0 else (-ARM[0] - GAP - 12, -ARM[0] - GAP)
    b = rot_y(rbox(xa, xb, -CH[1], CH[1], PZ + STOP_R[0], PZ + STOP_R[1], 2.5), a)
    bb = b.bounding_box()
    zc = (bb.min.Z + bb.max.Z) / 2
    for s_ in (1, -1):                  # cheek web under the bar (cheek y band only, outside every moving part)
        yi, yo = sorted((s_ * CH[0], s_ * CH[1]))
        xin, xout = (bb.min.X, bb.max.X) if side > 0 else (bb.max.X, bb.min.X)
        f = make_face(Polyline((xin, 0), (xout, 0), (xout, zc - 6), (xin, zc), close=True))
        b += soft(Pos(0, yo, 0) * extrude(Plane.XZ * f, amount=yo - yi), 1.5)
    return b
for side in (-1, 1):
    fr += stop_bar(side)
# friction boss (rear, +y band): M6 thumb screw along x, square shoe channel 12 (z) x 10 (y)
FY = (12.0, 20.5)
boss = rbox(-HUB_R - 24, -HUB_R - 1, ARM[1] + 0.6, CH[0] + 0.5, PZ - 10, PZ + 10, 2)
boss += rbox(-HUB_R - 24, -HUB_R - 14, ARM[1] + 0.6, CH[0] + 0.5, ft - 0.5, PZ - 8, 2)        # post down to the floor
boss -= box(-HUB_R - 15, -HUB_R - 0.9, FY[0] - 0.2, FY[1] + 0.2, PZ - 6.2, PZ + 6.2)        # shoe channel
boss -= cx((FY[0] + FY[1]) / 2, PZ, -HUB_R - 25, -HUB_R - 10, 5.0)                       # M6 thread (tap) / or M6 nut in the slot below
boss -= box(-HUB_R - 21, -HUB_R - 15.5, (FY[0] + FY[1]) / 2 - 5.6, (FY[0] + FY[1]) / 2 + 5.6, PZ - 5.6, PZ + 20)  # M6 nut slot from the top
fr += boss
for z in (PZ - 8, PZ + 8):                                               # sensor cover screws (M3 self-tap)
    fr -= cy(-24, z, CH[1] - 8, CH[1] + 1, 2.8)
fr -= box(-30, 30, -3, 3, -1, 2)                                         # cable groove under the frame (to the board)
part("frame", fr, "fixed", note="틀 (한 덩어리): 바닥 170×90 (v3 와 같은 M6 구멍 4 개, 머리 묻힘) + 양 볼 (608 자리) + 앞뒤 멈춤 막대 2 (팔이 닿음) + 마찰 보스",
     orient="바닥면을 바닥에, 채움 30 %, 벽 4 겹", fill=0.3)
for s, nm in ((1, "L"), (-1, "R")):
    part(f"bearing_{nm}", bearing("y", (0, PZ), s * (CH[1] - 7), s * CH[1]), "fixed", kind="buy", material="steel", note="608-2RS")

# friction shoe + felt + thumb screw
FXC = -HUB_R - 0.5
shoe = box(FXC - 12, FXC - 3, FY[0] + 0.1, FY[1] - 0.1, PZ - 6, PZ + 6) - cy(0, PZ, FY[0] - 1, FY[1] + 1, 2 * HUB_R + 6)
part("friction_shoe", shoe, "fixed", note="마찰 신발 (앞면에 펠트 3 mm 접착): 나사가 뒤에서 밀어 허브 원통면을 누름", orient="옆면을 바닥에, 채움 100 %", fill=1.0)
part("felt_pad", box(FXC - 3, FXC, FY[0] + 0.5, FY[1] - 0.5, PZ - 5.5, PZ + 5.5) - cy(0, PZ, FY[0], FY[1], 2 * HUB_R + 0.4), "fixed", kind="buy", material="felt",
     note="펠트 3 mm 조각 10×11 (양면테이프)")
knob = cx((FY[0] + FY[1]) / 2, PZ, -HUB_R - 46, -HUB_R - 12, 6)
for k in range(6):                                                        # star knob (6 lobes)
    a = k * math.pi / 3
    knob += cx((FY[0] + FY[1]) / 2 + 8 * math.cos(a), PZ + 8 * math.sin(a), -HUB_R - 56, -HUB_R - 46, 9)
knob += cx((FY[0] + FY[1]) / 2, PZ, -HUB_R - 56, -HUB_R - 46, 16)
part("friction_screw", knob, "fixed", kind="buy", material="steel", note="M6×40 별 손잡이 나사 + 너트 + 작은 압축 스프링 (조임 감 부드럽게)")

# sensor cover (+y side): closed rounded cover over the AS5600, chip ~2 mm from the magnet, screw heads sunk
SY = CH[1] + 3.5                                                         # board inner face
cap = rbox(-32, 16, CH[1], SY + 8, PZ - 17, PZ + 17, 3)
cap -= box(-12, 12, SY - 0.1, SY + 1.7, PZ - 12, PZ + 12)                 # board pocket 1.6 + slack
cap -= box(-14, 13.5, CH[1] - 0.1, SY, PZ - 13.5, PZ + 13.5)              # inside clearance (608 face, magnet, parts)
for z in (PZ - 8, PZ + 8):
    cap -= cy(-24, z, CH[1] - 1, SY + 9, 3.4) + cy(-24, z, SY + 5, SY + 9, 6.4)   # M3, head sunk 3 mm
cap -= box(10, 17, SY + 1, SY + 4, PZ - 3, PZ + 3)                        # wire exit (front)
part("sensor_cap", cap, "fixed", note="AS5600 덮개 (+y 볼 바깥을 덮음, M3 2 개 머리 묻힘): 칩이 자석에서 약 2 mm", orient="바깥면을 바닥에")
part("as5600", box(-11.5, 11.5, SY, SY + 1.6, PZ - 11.5, PZ + 11.5), "fixed", kind="buy", material="PCB", note="AS5600 보드 (아날로그 OUT → STM32 ADC, 3.3 V 전원)")

# ---------------- lever (one print) ----------------
lev = rcyl_y(0, PZ, -HUB_W / 2, HUB_W / 2, 2 * HUB_R, 2.5)
lev += soft(box(-ARM[0], ARM[0], -ARM[1], ARM[1], PZ, PZ + ARM[2]), 4)
lev -= cy(0, PZ, -HUB_W / 2 - 1, HUB_W / 2 + 1, 8.15)                    # shaft
lev -= cz(0, -10, PZ - 1, PZ + HUB_R + 1, 2.8)                            # M3 grub on the shaft (shaft has a flat), from the top
lev -= box(-3.1, 25, -12.6, -7.4, PZ + 9, PZ + 11.6)                      # M3 nut slot, inserted from +x
lev -= cy(0, PZ + ARM[2] - 12, -ARM[1] - 1, ARM[1] + 1, 4.3)              # M4 cross bolt (grip)
lev -= cy(0, PZ + ARM[2] - 28, -ARM[1] - 1, ARM[1] + 1, 4.3)
lev -= box(-3.5, 3.5, -ARM[1] - 1, -ARM[1] + 4, PZ + 4, PZ + ARM[2] + 1)  # cable groove along the arm (-y face)
part("lever", lev, "lever", note="레버 (한 덩어리): 허브 Ø40×40 + 팔 28×20 (모서리 둥글게, 팔 옆면이 멈춤 막대에 닿음). Ø8 축에 M3 무두나사",
     orient="옆면 (y) 을 바닥에 눕혀 (팔 굽힘이 층 안), 채움 40 %, 벽 4 겹", fill=0.4)
part("shaft", cy(0, PZ, -CH[1] - 1, CH[1] + 1.5, 8), "lever", kind="buy", material="steel", note="Ø8 스테인리스 (SUS304, 비자성) 봉 64 mm, 한쪽 끝 Ø6×2.5 자석 홈, 무두나사 자리 평면")
part("magnet", cy(0, PZ, CH[1] + 1.5, CH[1] + 3.0, 6), "lever", kind="buy", material="NdFeB", note="자석 Ø6×2.5 직경 방향 (축 끝에 접착, 축 끝면에서 1.5 mm 튀어나옴)")

# ---------------- grip adapter (our part): lever top -> public F-16 Viper throttle grip ----------------
# Fits the grip of "F-16 Viper Throttle" by Spock (printables.com/model/552322, CC BY-NC; grip from the Hempstick Project).
# That grip clamps a 44.4 mm thick tongue between its front and rear arms with ONE 1/4" (M6) bolt. Only those interface
# numbers are used here (measured from the public STEP); the adapter shape itself is ours. The grip file is NOT in this repo.
# Spock frame: x inboard, y up, z aft; their arm axis u = (0, .899, .438) (26 deg aft of vertical), bolt axis d = (0, .438, -.899).
# Our lever stays vertical; the adapter carries the 26 deg so the grip sits as in Spock's assembly at our lever angle 0.
U_O = Vector(-0.438, 0, 0.899)           # their arm axis in our frame (leans 26 deg aft)
D_O = Vector(0.899, 0, 0.438)            # their bolt axis in our frame
T_TOP = Vector(0, 0, PZ + ARM[2])        # our lever top centre  <->  Spock point (x 0, u 140, d 0)
SPOCK_REF = [0.0, 0.899 * 140, 0.438 * 140]
TONGUE_T = 44.2                           # clamp thickness (their tongue 44.4, 0.1 mm clearance per side)
def tplane(): return Plane(origin=T_TOP, x_dir=D_O, z_dir=U_O)      # local x = d, local y = outboard (-x_s), local z = u - 140
def tbox(y0, y1, z0, z1): return tplane() * Pos(0, (y0 + y1) / 2, (z0 + z1) / 2) * Box(TONGUE_T, y1 - y0, z1 - z0)
ad = soft(tbox(-4.7, 18.7, -14, 54.2), 3) + soft(tbox(-19.4, 0.5, 33.5, 64.4), 3)      # tongue: outboard part + raised inboard part
ad += rbox(-ARM[0] - 5, ARM[0] + 5, -ARM[1] - 5, ARM[1] + 5, T_TOP.Z - 36, T_TOP.Z + 4, 3)   # socket over our lever top
ad = soft(ad, 1.5)
ad -= box(-ARM[0] - 0.3, ARM[0] + 0.3, -ARM[1] - 0.3, ARM[1] + 0.3, T_TOP.Z - 37, T_TOP.Z + 0.3)  # pocket for the lever arm
for zc in (PZ + ARM[2] - 12, PZ + ARM[2] - 28):                          # M4 cross bolts, heads / nuts sunk
    ad -= cy(0, zc, -40, 40, 4.3) + cy(0, zc, ARM[1] + 3.5, 40, 8.2) + cy(0, zc, -40, -ARM[1] - 3.5, 8.2)
BOLT = tplane() * Pos(0, -11.0, 55.4)                                       # grip bolt axis (x_s 11, u 195.4) along d
ad -= Solid.make_cylinder(3.3, 80, Plane(origin=BOLT.position - D_O * 40, z_dir=D_O))
ad -= box(-3.5, 3.5, -ARM[1] - 6, -ARM[1] + 4, T_TOP.Z - 37, T_TOP.Z + 1)  # cable groove continues up
part("grip_adapter", ad, "lever", note="손잡이 어댑터 (우리 부품): 레버 위에 끼워 M4 2 개, 위 혀 (두께 44.2) 를 공개 F-16 Viper 손잡이가 앞뒤로 물고 M6 볼트 1 개 (26° 뒤로 기울임 포함)",
     orient="혀의 넓은 면 (d) 을 바닥에, 채움 40 %, 벽 4 겹", fill=0.4)
part("grip_bolt", Solid.make_cylinder(3.0, 60, Plane(origin=BOLT.position - D_O * 30, z_dir=D_O)), "lever", kind="buy", material="steel",
     note="M6×60 볼트 + 너트 (원래는 1/4\" 볼트) — 손잡이 앞뒤 팔 + 어댑터 혀를 관통")

# ---------------- checks ----------------
def posed(name, ang):
    s = parts[name]["shape"]
    return rot_y(s, ang) if parts[name]["group"] == "lever" else s

MATES = [("frame", "bearing_L"), ("frame", "bearing_R"), ("shaft", "bearing_L"), ("shaft", "bearing_R"), ("shaft", "lever"), ("shaft", "magnet"),
         ("frame", "friction_shoe"), ("friction_shoe", "felt_pad"), ("felt_pad", "lever"), ("frame", "friction_screw"), ("friction_screw", "friction_shoe"),
         ("frame", "sensor_cap"), ("sensor_cap", "as5600"), ("lever", "grip_adapter"), ("grip_adapter", "grip_bolt"), ("frame", "felt_pad"), ("shaft", "frame"), ("magnet", "sensor_cap")]
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
            sf("어댑터 M4 2 개 전단", F / 4 / (math.pi * 3.3 ** 2 / 4), 0.6 * 400, note="4.8 볼트 0.6×400"),
            sf("M4 구멍 눌림 (팔 PLA, 16 mm 간격, Ø4 × 20)", F * (Lh - (ARM[2] - 20)) / 16 / (20 * 4), M["comp"], note="손 힘이 위쪽 볼트에 지렛대로 걸림"),
            sf("손잡이 M6 볼트 전단 (양쪽 팔 = 2 면)", F / 2 / 20.1, 0.6 * 400, note="4.8 급"),
            sf("어댑터 혀 볼트 구멍 눌림 (Ø6 × 44)", F / (6 * 44), M["comp"]),
            sf("어댑터 소켓 굽힘 (바깥 38×30 − 안 28.6×20.6, 레버 없다고 봄 = 보수적)", F * (Lh - ARM[2] + 36) / (((30 * 38 ** 3 - 20.6 * 28.6 ** 3) / 12) / 19), M["z"], note="세워 출력하면 층 사이")]
    # friction: holding torque needed vs shoe normal force (μ felt-PLA ~0.3, 추정)
    Fn = 25.0; mu = 0.3
    creep = [sf("마찰 신발 압력 (25 N / 10×11, 계속)", Fn / 110, M["creep"])]
    return dict(panic_N=F, l_hand=round(Lh), stop_force_N=round(Fs), rows=rows, creep=creep,
                friction=dict(shoe_N=Fn, mu=mu, torque_Nm=round(Fn * mu * HUB_R / 1000, 3), hand_N=round(Fn * mu * HUB_R / Lh, 2),
                              note="펠트-PLA μ 0.3 (추정). 25 N 이면 손에서 약 1.2 N 의 미는 힘 — 손잡이가 흘러내리지 않을 정도. 나사로 0~60 N 조절"))

BUTTONS = [   # switches of the public F-16 Viper grip (Spock), wired to the same FreeJoy board
    dict(id="B1-B5", name="통신 햇 (4방향 + 누름)", part="햇 스위치 (원작 Alt hatswitch: 6×6 택트 조합)", where="위 앞쪽, 엄지", sr="U1 A-E", price=600),
    dict(id="B6-B7", name="도그파이트 / 미사일 오버라이드 (3단 슬라이드)", part="MTS-103 미니 토글 on-off-on + 슬라이드 통", where="앞 위, 검지", sr="U1 F-G", price=900),
    dict(id="B8-B9", name="스피드브레이크 (3단 슬라이드)", part="MTS-123 미니 토글 (on)-off-on + 슬라이드 통", where="안쪽 면, 엄지 밑", sr="U1 H, U2 A", price=1200),
    dict(id="B10", name="커서 누름 (RDR CURSOR)", part="PS2 아날로그 썸스틱 모듈 (누름 포함)", where="앞쪽, 검지", sr="U2 B", price=1500),
    dict(id="B11", name="언케이지 (MAN RNG 누름)", part="6×6 택트 (가변저항 뒤)", where="앞 아래, 가운데 손가락", sr="U2 C", price=100),
    dict(id="A1-A2", name="커서 X / Y", part="(같은 썸스틱)", where="", sr="PA6 / PA7", price=0),
    dict(id="A3", name="안테나 고각 (ANT ELEV) 휠", part="10 kΩ 가변저항 (가운데 걸림 있으면 좋음)", where="앞, 검지", sr="PB0", price=800),
    dict(id="A4", name="MAN RNG 노브", part="10 kΩ 가변저항", where="앞 아래", sr="PB1", price=800),
]

BUY = [  # name, qty, KRW total (추정, 국내 쇼핑몰 2026 대략값), note
    ("608ZZ 베어링", 2, 2000, ""), ("Ø8 SUS304 봉 100 mm (64 mm 로 자름, 끝 평면 1 곳)", 1, 3000, "비자성 — 자석 자리"),
    ("자석 Ø6×2.5 직경 방향 (예비 포함)", 3, 1500, "AS5600 용"), ("AS5600 모듈", 1, 3000, "아날로그 OUT 사용"),
    ("M6×40 별 손잡이 나사 + 너트 + 작은 압축 스프링 + 펠트 3 mm", 1, 4000, "마찰"),
    ("손잡이 스위치: 6×6 택트 ×6, MTS-103, MTS-123, PS2 썸스틱, 10 kΩ 가변저항 ×2", 1, 5000, "공개 F-16 Viper 손잡이용"),
    ("손잡이 출력 PLA (공개 파일, 약 250 g 추정)", 1, 6500, "BottomBody · TopCover · 캡류"),
    ("M6×60 볼트 + 너트 (손잡이 ↔ 어댑터), #8/M4 나사 (손잡이 조립)", 1, 2500, ""),
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
                                          based_on="grip = Spock 'F-16 Viper Throttle' (Printables 552322, CC BY-NC, Hempstick grip) — NOT in repo; adapter fits its 44.4 mm tongue + 1 bolt",
                                          spock_mount=dict(spock_ref=SPOCK_REF, ours_ref=[T_TOP.X, T_TOP.Y, T_TOP.Z], note="ours = R*(s - spock_ref) + ours_ref, R: x=-z_s, y=-x_s, z=y_s")),
                        extra=dict(check=[dict(pose=p, hits=b) for p, b in res], stops_hit_deg=stops, strength=stg, buttons=BUTTONS, buy=[dict(name=a, qty=b, krw=c, note=d) for a, b, c, d in BUY]))
    for i in info: print(f"{i['name']:16s} {i['group']:6s} {i['kind']:5s} {i['size']} {i['grams'] or ''}")
    for p, b in res: print("pose", p, b if b else "none")
    print("stops hit at", stops, "L_hand", round(L_HAND))
    for r in stg["rows"] + stg["creep"]: print(f"  {r['name']}: {r['load']} / {r['limit']} {r['unit']} SF {r['sf']}")
    print("friction", stg["friction"])
