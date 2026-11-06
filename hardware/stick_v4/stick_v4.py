"""Centre stick v4 (simple): U-joint cross on 4 x 608, ONE compression spring + flat plate centring, AS5600 per axis,
round stop collar in a gate lid, 4 x M6 T-nuts onto two 4040 cross bars (x = +-70). F-16 grip (third party, NOT in
this repo) on a printed adapter.

Units mm, N. x forward, y left, z up, origin = base underside centre. Every strength / force number here = 추정.

Grip: "F-16 Sidestick Grip" by Spock (Printables 233472 / Thingiverse 4544115), CC BY-NC-SA. Measured from the author's
viper-grip.step (local copy only, C:/GyroSimParts/thirdparty/f16_grip): mount bore Ø25.0 straight up from the grip
underside, >= 30 deep free of internals; at 3..6 mm above the underside a Ø32 groove over the front and back 90 deg
sectors (the grip halves split left/right, so lugs on the adapter are captured when the two halves are screwed shut).

Run:  python stick_v4.py   (writes stl/*.stl + parts.json, prints checks)
"""
import math, os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from ctl_lib import box, cx, cy, cz, tube, bearing, export_parts, check_pairs, PLA_MECH as M, C0_608, sf
from build123d import Axis, Pos, Rot, Cylinder

HERE = os.path.dirname(os.path.abspath(__file__))

# ---------------- main values ----------------
PZ = 105                        # pivot (cross centre) above the base underside
BASE_T = 6                      # floor thickness
WX0, WX1 = 50, 62               # front / back wall |x| range (608 seats), 12 thick
WY0, WY1 = 62, 67               # side wall |y| range, 5 thick
FL_X = 88                       # floor flange |x| (M6 slots at x = +-70 -> 4040 cross bars)
GZ = PZ + 78                    # gate lid underside
GT = 6                          # gate lid thickness
HOLE_D = 76                     # gate hole diameter (round = same stop angle every way)
COL = (PZ + 66, PZ + 100, 38)   # stop collar z0, z1, OD
FX0, FX1 = 34, 48.5              # roll frame front/back wall |x| range
FY0, FY1 = 26, 38               # roll frame side wall |y| range (pitch 608 seats)
FZ = 17                         # roll frame half height
HUB_FL = (PZ - 36, PZ - 30, 80)  # hub centring flange z0, z1, OD  (flat underside = the face the spring plate pushes on)
DISC = (PZ - 42, PZ - 36, 96)   # spring plate z0, z1, OD (floats on the spring)
SPRING = dict(d=5.0, D_out=40.0, n=6, L0=58.0, k=24.0)     # music wire compression spring; k = G d^4 / (8 D^3 n) ~ 24 (D mean 35), solid ~40
PRE = SPRING["L0"] - (DISC[0] - (BASE_T + 2))               # preload compression (mm) at centre (2 mm seat ring)
TUBE25_TOP = PZ + 515           # lower tube Ø25 x 2.5 top
GRIP_Z = PZ + 575               # F-16 grip underside (bore mouth)
HAND_Y = 85                     # palm centre above the grip underside (F-16 trigger at 97..131 -> palm ~85, 추정)
L_HAND = GRIP_Z - PZ + HAND_Y   # pivot -> hand
AD_Z0 = GRIP_Z - 20             # adapter bottom (= INTERFACE.md "grip underside": Ø20 tube goes 40 mm in)
T20_TOP = AD_Z0 + 40            # Ø20 x 2 tube top (= GRIP_Z + 20, inside the grip bore)
T20_BOT = T20_TOP - 140         # Ø20 tube 140 long, bottom 60 mm inside the Ø25 tube (as v3)

parts = {}
def part(name, shape, group, kind="print", note="", material="PLA", orient="", fill=0.35, price=None, qty=1):
    parts[name] = dict(shape=shape, group=group, kind=kind, note=note, material=material, orient=orient, fill=fill)
    if price is not None: parts[name]["price"] = price
    parts[name]["qty"] = qty

# ---------------- 1 base box (fixed) ----------------
b = box(-FL_X, FL_X, -WY1, WY1, 0, BASE_T)
for s in (1, -1):
    b += box(s * WX0, s * WX1, -WY1, WY1, BASE_T - 0.5, GZ)
    b += box(-WX1, WX1, s * WY0, s * WY1, BASE_T - 0.5, GZ)
    b += box(s * WX1, s * (WX1 + 14), -WY1, WY1, BASE_T - 0.5, BASE_T + 10)     # flange ribs
for s in (1, -1):
    b -= cx(0, PZ, s * (WX0 + 1.5), s * (WX1 + 1), 22.05)                      # 608 seat, 1.5 mm lip left on the inside face
    b -= cx(0, PZ, s * (WX0 - 1), s * (WX0 + 2), 14)                           # lip hole (shaft + inner race clearance)
    for y in (-40, 40):
        b -= cz(s * 70, y, -1, BASE_T + 11, 6.6)                              # M6 -> T-nut (4040 cross bars at x = +-70)
        b -= cz(s * 70, y, BASE_T, BASE_T + 11, 13)                           # washer pocket
    for y in (-50, 50):
        b -= cz(s * (WX0 + WX1) / 2, y, GZ - 12, GZ + 1, 2.6)                  # M3 x 12 self-tap: lid screws (4)
# windows in the side walls (light, cable, look inside), floor seat ring for the spring
for s in (1, -1):
    b -= box(-36, 36, s * (WY0 - 1), s * (WY1 + 1), BASE_T + 14, PZ - 20)
b += tube("z", (0, 0), BASE_T - 0.5, BASE_T + 2, 44, 34)                       # spring seat ring
b -= cx(0, BASE_T + 30, -WX1 - 1, -WX0 + 1, 10)                                # cable exit (back wall, below the bearing)
for z in (PZ - 13, PZ + 13):
    b -= cx(0, z, -WX1 - 1, -WX1 + 8, 2.6)                                     # AS5600 (roll) M3 self-tap on the back wall
part("base_box", b, "fixed", note="받침 상자 (PLA 한 덩어리): 바닥 + 앞뒤 벽 12 t (608 자리) + 옆벽 5 t, 아래 M6 ×4 → 4040 T너트",
     orient="바닥을 바닥에, 지지대 없이 (608 자리 위 반원 = 다리 놓기 짧음)", fill=0.35)

# ---------------- 2 gate lid (fixed) ----------------
g = box(-WX1, WX1, -WY1, WY1, GZ, GZ + GT) - cz(0, 0, GZ - 1, GZ + GT + 1, HOLE_D)
for s in (1, -1):
    g += box(s * (WX0 - 4), s * (WX0 - 0.2), -40, 40, GZ - 6, GZ)               # lips inside the end walls (pitch stop load -> wall faces)
    g += box(-40, 40, s * (WY0 - 4), s * (WY0 - 0.2), GZ - 6, GZ)               # lips inside the side walls (roll stop load)
    for y in (-50, 50):
        g -= cz(s * (WX0 + WX1) / 2, y, GZ - 1, GZ + GT + 1, 3.4)
part("gate_lid", g, "fixed", note="게이트 뚜껑: 둥근 구멍 Ø76 = 멈춤 (모든 방향 같은 각). 안쪽 턱 4 개가 벽 면에 기대 멈춤 힘을 벽으로 넘김, M3 ×4",
     orient="뒤집어서 (턱을 위로)", fill=0.6)

# ---------------- 3 roll frame (roll group) ----------------
f = box(-FX1, FX1, -FY1, FY1, PZ - FZ, PZ + FZ) - box(-FX0, FX0, -FY0, FY0, PZ - FZ - 1, PZ + FZ + 1)
for s in (1, -1):
    f -= cx(0, PZ, s * (FX0 - 1), s * (FX1 + 1), 8.0)                          # roll stub holes (press + M3 grub)
    f -= cz(s * (FX0 + FX1) / 2, 0, PZ, PZ + FZ + 1, 2.6)                      # M3 grub onto each stub
    f -= cy(0, PZ, s * (FY0 + 1.5), s * (FY1 + 1), 22.05)                      # pitch 608 seats, 1.5 lip inside
    f -= cy(0, PZ, s * (FY0 - 1), s * (FY0 + 2), 14)
# AS5600 (pitch) bracket: two posts on the -y side wall, board at y = -52
for x in (-13, 13):
    f += box(x - 4, x + 4, -50, -FY1 + 0.5, PZ - 4, PZ + 4) - cy(x, PZ, -51, -40, 2.6)
part("roll_frame", f, "roll", note="roll 틀 (십자 바깥): 앞뒤 Ø8 축 토막 2 (M3 무두볼트), 옆 608 2 (pitch), −y 쪽 AS5600 기둥",
     orient="눕혀서 (z 를 위로)", fill=0.6)

# ---------------- 4 stick hub (pitch group) ----------------
h = box(-16, 16, -(FY0 - 0.5), FY0 - 0.5, PZ - 20, PZ + 20)   # 0.5 mm to the frame: roll stop load -> frame face, not the 608s
h += cz(0, 0, PZ + 10, PZ + 50, 40)                                             # Ø25 tube socket boss
h += box(-9, 9, -32, -18, PZ + 22, PZ + 50)                                    # clamp ears (-y side: clear of the frame in pitch)
h += cz(0, 0, HUB_FL[1] - 0.01, PZ - 19, 30)                                   # tail
h += cz(0, 0, HUB_FL[0], HUB_FL[1], HUB_FL[2])                                 # centring flange (flat underside)
h -= cy(0, PZ, -FY0, FY0, 8.1)                                                 # pitch shaft
h -= cz(10, 0, PZ, PZ + 21, 3.3)                                               # M4 set screw onto the shaft D-flat (tapped in PLA / insert)
h -= cz(0, 0, PZ + 8, PZ + 51, 25.3)                                           # Ø25 tube socket 42 deep
h -= box(-1, 1, -33, -10, PZ + 20, PZ + 51)                                    # clamp slit
for z in (PZ + 29, PZ + 43):
    h -= cx(-26, z, -10, 10, 5.5)                                              # M5 clamp bolts
h -= cx(0, PZ + 14, -21, -8, 9)                                                # cable out of the tube (back side)
part("stick_hub", h, "pitch", note="스틱 허브 (십자 안쪽, pitch 로 돎): Ø25 관 소켓 42 mm + M5 클램프 2, 아래 Ø80 평면 = 스프링 판이 미는 면",
     orient="소켓을 위로, 채움 60 %", fill=0.6)

# ---------------- 5 spring plate (floats on the spring) ----------------
d_ = cz(0, 0, DISC[0], DISC[1], DISC[2]) + tube("z", (0, 0), DISC[0] - 4, DISC[0], 40.5 - 0.01 + 6, 40.5)   # skirt locates the spring top
part("spring_plate", d_, "disc", note="스프링 판 (뜸): 스프링이 위로 밀어 허브 평면에 붙임 → 기울이면 판 가장자리가 눌려 가운데로 돌아옴 (가운데 걸림 = 예압)",
     orient="평면을 바닥에", fill=0.4)

# ---------------- 6 stop collar (pitch group) ----------------
c_ = tube("z", (0, 0), COL[0], COL[1], COL[2], 25.3)
c_ -= cx(0, (COL[0] + COL[1]) / 2, 10, 20, 2.6)                                # M3 grub (self-tap) onto the tube
part("stop_collar", c_, "pitch", note="멈춤 링 Ø38: 관에 끼워 M3 무두볼트. 뚜껑 구멍 Ø76 가장자리에 닿아 멈춤 (원하면 고무 호스 감기)",
     orient="그대로", fill=0.8)

# ---------------- 7 grip adapter (pitch group) ----------------
G0 = GRIP_Z
a = cz(0, 0, AD_Z0, G0, 34)                                                     # neck under the grip (Ø34 <= grip underside Ø39)
a += cz(0, 0, G0 - 0.01, G0 + 26, 24.8)                                         # plug in the Ø25 bore (26 deep, internals start ~30)
for s in (1, -1):                                                               # lugs into the Ø32 groove (front/back 90° sectors), captured by the grip halves
    lug = cz(0, 0, G0 + 3.3, G0 + 5.7, 31.4) - cz(0, 0, G0 + 3, G0 + 6, 24)
    lug &= box(s * 4, s * 20, -11, 11, G0 + 3, G0 + 6)
    a += lug
a -= cz(0, 0, AD_Z0 - 1, T20_TOP, 20.4)                                         # Ø20 socket 40 deep (INTERFACE.md)
a -= cz(0, 0, T20_TOP - 0.01, G0 + 27, 14)                                      # cable passage into the grip
a += box(-10.2, -8, -1.9, 1.9, T20_TOP - 6, T20_TOP)                            # key rib (back, -x) into the tube's 4 x 6 notch
a -= cy(0, AD_Z0 + 8, -18, 18, 4.3)                                             # M4 x 35 cross bolt (32 below the tube top, see note)
part("grip_adapter", a, "pitch", note="F-16 손잡이 어댑터: 아래 Ø20 관 소켓 40 (INTERFACE.md), 위 Ø24.8 마개 26 mm + 앞뒤 걸쇠 (손잡이 반쪽 2 개가 덮어 잡음), M4 가로볼트",
     orient="소켓을 아래로 (걸쇠 아래 지지대 조금)", fill=1.0)

# ---------------- bought parts (shown in the viewer) ----------------
for s, nm in ((1, "front"), (-1, "back")):
    part(f"bearing_roll_{nm}", bearing("x", (0, PZ), s * (WX0 + 1.5), s * (WX0 + 8.5)), "fixed", kind="buy", material="steel", note="608ZZ (roll)", price=700)
    part(f"stub_roll_{nm}", cx(0, PZ, s * FX0, s * (WX0 + 8.5 + (8 if s < 0 else 0)), 8), "roll", kind="buy", material="steel",
         note="Ø8 리니어 샤프트 (SUJ2) 토막 " + ("40 mm, 뒤쪽은 끝에 자석" if s < 0 else "32 mm"), price=1500)
for s, nm in ((1, "L"), (-1, "R")):
    part(f"bearing_pitch_{nm}", bearing("y", (0, PZ), s * (FY0 + 1.5), s * (FY0 + 8.5)), "roll", kind="buy", material="steel", note="608ZZ (pitch)", price=700)
part("pitch_shaft", cy(0, PZ, -(FY1 + 8), FY1 - 1, 8), "pitch", kind="buy", material="steel", note="Ø8 리니어 샤프트 (SUJ2) 83 mm, D컷 (허브 M4 무두볼트), −y 끝에 자석", price=2500)
part("magnet_roll", cx(0, PZ, -(WX0 + 16.5), -(WX0 + 19), 6), "roll", kind="buy", material="NdFeB", note="자석 Ø6×2.5 직경 방향 착자 (AS5600 세트), 축 끝에 접착", price=0)
part("magnet_pitch", cy(0, PZ, -(FY1 + 8), -(FY1 + 10.5), 6), "pitch", kind="buy", material="NdFeB", note="자석 Ø6×2.5 직경 방향 (AS5600 세트)", price=0)
part("as5600_roll", box(-WX1 - 9.6, -WX1 - 8, -11.5, 11.5, PZ - 11.5, PZ + 11.5), "fixed", kind="buy", material="PCB", note="AS5600 보드 (roll), 뒤벽 바깥 M3 ×2 + 스페이서 8", price=2500)
part("as5600_pitch", box(-11.5, 11.5, -53.6, -52, PZ - 11.5, PZ + 11.5), "roll", kind="buy", material="PCB", note="AS5600 보드 (pitch), roll 틀 기둥에 M3 ×2", price=2500)
part("spring", tube("z", (0, 0), BASE_T + 2, DISC[0], SPRING["D_out"], SPRING["D_out"] - 2 * SPRING["d"]), "fixed", kind="buy", material="steel",
     note=f"압축 스프링 선경 {SPRING['d']} 바깥 Ø{SPRING['D_out']:.0f} 자유장 {SPRING['L0']:.0f} 유효 {SPRING['n']} 감김 (k ≈ {SPRING['k']} N/mm, 추정)", price=5000)
part("stick_tube", tube("z", (0, 0), PZ + 8, TUBE25_TOP, 25, 20), "pitch", kind="buy", material="AL6061",
     note=f"아래 관 알루미늄 Ø25×2.5t, {TUBE25_TOP - PZ - 8} mm (v3 와 같음)", price=9000)
part("grip_tube", tube("z", (0, 0), T20_BOT, T20_TOP, 20, 16), "pitch", kind="buy", material="AL6061",
     note="위 관 Ø20×2t 140 mm (INTERFACE.md): 아래 60 mm 가 Ø25 관 속 (M5 가로볼트), 위 40 mm 가 어댑터 속 (M4 가로볼트, 뒤 4×6 홈)", price=4000)
gp = cz(0, 0, G0, G0 + 25, 40) + cz(0, 0, G0 + 25, G0 + 175, 34)                 # crude proxy only (the real grip is third party)
part("grip_proxy", gp, "pitch", kind="ref", material="ref", note="F-16 손잡이 자리 (모양 아님, 대략 크기). 실제 STL 은 저장소에 없음: Printables 233472 (CC BY-NC-SA) 에서 받기")


# ---------------- grip inputs, wiring, bought-parts list (prices = 추정, KRW, Korean shops / AliExpress, 2026-11) ----------------
BUTTONS = [  # (no, name, F-16 function, grip part (Printables 233472), switch)
    (1, "TRG1", "방아쇠 1단 (카메라/조준)", "Viper Trigger", "택트 6×6×4.3"),
    (2, "TRG2", "방아쇠 2단 (기총)", "Viper Trigger", "택트 6×6×4.3"),
    (3, "PICKLE", "무장 투하 (피클)", "Viper Pickle", "택트 6×6×4.3"),
    (4, "NWS", "NWS / A/R 해제 / MSL STEP", "Viper NWS", "택트 6×6×4.3"),
    (5, "PINKY", "새끼손가락 스위치 (모드 전환)", "Viper Pinkie", "택트 6×6×4.3"),
    (6, "PADDLE", "패들 (오토파일럿 끊기)", "Viper Paddle", "택트 6×6×4.3 (+ 패들 스프링)"),
    (7, "TRIM_U", "트림 햇 ↑ (기수 내림)", "Trim hat + hat base", "택트 6×6×4.3"),
    (8, "TRIM_D", "트림 햇 ↓", "Trim hat", "택트 6×6×4.3"),
    (9, "TRIM_L", "트림 햇 ←", "Trim hat", "택트 6×6×4.3"),
    (10, "TRIM_R", "트림 햇 →", "Trim hat", "택트 6×6×4.3"),
    (11, "TMS_U", "TMS ↑ (표적 관리)", "TMS hat", "택트 6×6×4.3"),
    (12, "TMS_D", "TMS ↓", "TMS hat", "택트 6×6×4.3"),
    (13, "TMS_L", "TMS ←", "TMS hat", "택트 6×6×4.3"),
    (14, "TMS_R", "TMS →", "TMS hat", "택트 6×6×4.3"),
    (15, "DMS_U", "DMS ↑ (화면 관리)", "DMS hat", "택트 6×6×4.3"),
    (16, "DMS_D", "DMS ↓", "DMS hat", "택트 6×6×4.3"),
    (17, "DMS_L", "DMS ←", "DMS hat", "택트 6×6×4.3"),
    (18, "DMS_R", "DMS →", "DMS hat", "택트 6×6×4.3"),
    (19, "CMS_U", "CMS ↑ (대응책: 채프/플레어)", "CMS hat", "택트 6×6×4.3"),
    (20, "CMS_D", "CMS ↓", "CMS hat", "택트 6×6×4.3"),
    (21, "CMS_L", "CMS ←", "CMS hat", "택트 6×6×4.3"),
    (22, "CMS_R", "CMS →", "CMS hat", "택트 6×6×4.3"),
    (23, "CMS_P", "CMS 누름", "hatswitch push (CMS)", "택트 6×6×4.3"),
    (24, "TMS_P", "TMS 누름 (예비)", "hatswitch push (TMS)", "택트 6×6×4.3"),
]
WIRING = [  # (from, to, wire, note)
    ("스위치 24 개 (한쪽)", "74HC165 ×3 입력 D0~D7 (1번 칩 = 1~8, 2번 = 9~16, 3번 = 17~24)", "손잡이 속 짧은 선", "각 입력 10 kΩ 풀업 → 3.3 V, 누르면 GND (눌림 = LOW)"),
    ("스위치 24 개 (다른 쪽)", "GND 공통", "손잡이 속", "다이오드 필요 없음 (매트릭스 아님)"),
    ("74HC165 #1 QH", "#2 DS(SER), #2 QH → #3 DS", "손잡이 속", "3 개 줄줄이 (daisy chain), #3 DS = GND"),
    ("3.3 V", "블루필 3.3 V", "6 심 차폐선 1번", "관 속 Ø16 통과, 선 바깥 Ø5 이하"),
    ("GND", "블루필 GND", "6 심 2번 + 차폐", ""),
    ("CLK (CP, 3 칩 공통)", "블루필 PB3 (SPI1 SCK)", "6 심 3번", "[확인 필요] FreeJoy 설정기에서 시프트 레지스터 핀 확인"),
    ("PL (래치, 3 칩 공통)", "블루필 PA15 (예)", "6 심 4번", "[확인 필요] 설정기에서 'ShiftReg LATCH' 지정"),
    ("QH (#3 출력)", "블루필 PB4 (예)", "6 심 5번", "[확인 필요] 설정기에서 'ShiftReg DATA' 지정"),
    ("CE (칩 enable)", "GND", "손잡이 속", ""),
    ("예비", "-", "6 심 6번", "나중에 LED 등"),
    ("AS5600 roll OUT", "블루필 PA0 (ADC, 축 X)", "짧은 3 심 (5V 아님, 3.3 V)", "AS5600 아날로그 출력 모드 (두 개 I2C 주소 같아서 I2C 대신)"),
    ("AS5600 pitch OUT", "블루필 PA1 (ADC, 축 Y)", "짧은 3 심 (roll 틀에 고정 → 고리 남김)", "pitch 센서는 roll 틀과 같이 움직임: 선 여유 50 mm"),
    ("블루필 USB", "PC", "USB", "FreeJoy = USB 조이스틱 (드라이버 없음)"),
]
BUY = [  # (item, qty, KRW 추정, note)
    ("608ZZ 베어링", "4", 2800, "개당 약 700"),
    ("Ø8 리니어 샤프트 SUJ2 300 mm", "1 (83 + 32 + 40 으로 자름)", 4000, "D컷 1 곳 줄로"),
    ("압축 스프링 선경 5 · 바깥 Ø40 · 자유장 58 · 유효 6 감김", "1", 5000, "스프링 몰 주문 (k ≈ 24 N/mm). 가벼움/무거움용 선경 4.5 / 5.5 추가 시 +1 만"),
    ("알루미늄 원관 Ø25×2.5 (507 mm)", "1", 9000, "v3 와 같은 관 (있으면 재사용)"),
    ("알루미늄 원관 Ø20×2 (140 mm)", "1", 4000, "INTERFACE.md 규격, 위 4×6 홈"),
    ("AS5600 모듈 + 자석 Ø6×2.5", "2", 5000, "알리 세트 약 2,500"),
    ("STM32F103 블루필 (FreeJoy)", "1", 6000, "기존 STM32 를 쓰면 0"),
    ("74HC165 (DIP-16) + 만능기판 + 10 kΩ ×24", "3", 3500, ""),
    ("택트 스위치 6×6×4.3 (100 개 묶음)", "약 26 사용", 3000, "손잡이 설계 그대로 (22~25 개 + 예비)"),
    ("6 심 차폐선 2 m", "1", 3000, ""),
    ("볼트: M6×16 + 4040 T너트 4, M5×30 2, M4×35 1, M4 무두 1, M3 무두 3, M3×12 8, M2×8 10 (햇), M3×20 2 (손잡이)", "1 식", 7000, ""),
]

# ---------------- pose + checks ----------------
def posed(name, roll, pitch):
    s = parts[name]["shape"]; g = parts[name]["group"]
    if g == "disc": return s                                       # plate: pushed down at tilt (checked separately)
    if g == "pitch" and pitch: s = s.rotate(Axis((0, 0, PZ), (0, 1, 0)), pitch)
    if g in ("pitch", "roll") and roll: s = s.rotate(Axis((0, 0, PZ), (1, 0, 0)), roll)
    return s

MATES = [("base_box", "bearing_roll_front"), ("base_box", "bearing_roll_back"), ("stub_roll_front", "bearing_roll_front"), ("stub_roll_back", "bearing_roll_back"),
         ("stub_roll_front", "roll_frame"), ("stub_roll_back", "roll_frame"), ("stub_roll_front", "base_box"), ("stub_roll_back", "base_box"),
         ("roll_frame", "bearing_pitch_L"), ("roll_frame", "bearing_pitch_R"), ("pitch_shaft", "bearing_pitch_L"), ("pitch_shaft", "bearing_pitch_R"),
         ("pitch_shaft", "stick_hub"), ("pitch_shaft", "roll_frame"), ("stick_hub", "stick_tube"), ("stick_tube", "stop_collar"), ("stick_tube", "grip_tube"),
         ("grip_tube", "grip_adapter"), ("grip_adapter", "grip_proxy"), ("grip_tube", "grip_proxy"), ("base_box", "gate_lid"), ("base_box", "spring"),
         ("spring", "spring_plate"), ("stick_hub", "spring_plate"), ("magnet_roll", "stub_roll_back"), ("magnet_pitch", "pitch_shaft"),
         ("as5600_roll", "base_box"), ("as5600_pitch", "roll_frame"), ("stub_roll_back", "magnet_roll"), ("base_box", "magnet_roll"), ("base_box", "as5600_roll")]
ALLOW = {frozenset(p) for p in MATES}

def spring_torque(theta_deg, k=SPRING["k"], pre=None):
    """Torque (N*mm) of the spring plate on the hub flange: rim point (R, -a) of the flat underside pushes the plate down
    by d = R sin t - a (1 - cos t); vertical force F = k (pre + d) acting at arm R cos t - a sin t."""
    pre = PRE if pre is None else pre
    R = HUB_FL[2] / 2; a_ = PZ - HUB_FL[0]; t = math.radians(theta_deg)
    d = R * math.sin(t) - a_ * (1 - math.cos(t))
    F = k * (pre + d)
    return F * (R * math.cos(t) - a_ * math.sin(t)), d, F

def forces():
    angs = list(range(0, 14))
    var = {}
    for nm, kf, pf in (("light", 0.6, 1), ("default", 1, 1), ("heavy", 1.5, 1.5)):
        var[nm] = dict(k=round(SPRING["k"] * kf, 1), pre=round(PRE * pf, 1), N=[round(spring_torque(a_, SPRING["k"] * kf, PRE * pf)[0] / L_HAND, 1) for a_ in angs])
    return dict(angles=angs, variants=var, l_hand=L_HAND, pre_mm=PRE,
                note="손 힘 (N) = 스프링 토크 / 손 거리. roll · pitch 같음 (둥근 판). 판-허브 미끄럼 마찰 · 608 마찰 빼고 계산 (추정). 가벼움 = k 15 스프링 / 무거움 = k 36 스프링 (같은 바깥 Ø40, 선경만 다름)")

def strength(stop_deg):
    F = 200.0
    hc = GZ + GT / 2 - PZ                                         # collar contact height above the pivot
    Fg = F * L_HAND / hc; Rp = Fg - F
    rows = [sf("멈춤 링 ↔ 뚜껑 구멍 가장자리 눌림 (접촉 15 mm × 6 t)", Fg / (15 * GT), M["comp"]),
            sf("608 정적 정격 (pivot 힘 / 2 개)", Rp / 2, C0_608, unit="N", note="정격 C0 = 영구 눌림 시작 (깨짐 아님)"),
            sf("608 자리 PLA 눌림 (Ø22 × 7)", Rp / 2 / (22 * 7), M["comp"])]
    Zs = math.pi * 8 ** 3 / 32
    rows.append(sf("pitch 축 Ø8 굽힘 (베어링 간격 64, 허브 폭 49)", Rp * (2 * 64 - 49) / 8 / Zs, 500, note="SUJ2 리니어 샤프트 (고주파 경화) 항복 500 이상으로 봄 (추정)"))
    arm = (WX0 + 5) - FX1                                          # frame face -> bearing centre
    rows.append(sf("roll 축 토막 Ø8 굽힘 (틀 면 → 베어링 중심 %d mm)" % arm, Rp / 2 * arm / Zs, 500))
    Zt = math.pi * (25 ** 4 - 20 ** 4) / (32 * 25)
    rows.append(sf("알루미늄 관 Ø25×2.5 굽힘 (멈춤 링 위)", F * (L_HAND - hc) / Zt, 170, note="6063-T5 항복 약 170 (6061-T6 이면 240)"))
    Mb = Rp * 22; Zb = math.pi * (40 ** 4 - 25.3 ** 4) / (32 * 40)
    rows.append(sf("허브 소켓 뿌리 굽힘 (층 사이)", Mb / Zb, M["z"], note="소켓을 위로 출력 → 층 사이 20 MPa 로 봄"))
    # gate lid lip: push from the collar goes into a wall face over a lip 80 long x 6 high: lid in-plane, OK; wall face bending
    t = WX1 - WX0; Zw = 2 * WY1 * t ** 2 / 6
    rows.append(sf("앞/뒤벽 위끝 굽힘 (턱이 벽을 밂, 옆벽이 잡음 → 보 길이 134 양끝 고정)", Fg * 2 * WY1 / 8 / Zw, M["z"], note="세워 출력 → 층 사이"))
    I_box = 2 * (2 * WY1) * t * (WX0 + t / 2) ** 2 + 2 * (WY1 - WY0) * (2 * WX0) ** 3 / 12
    rows.append(sf("상자 뿌리 굽힘 (바닥 ↔ 벽, 상자 단면)", F * L_HAND / (I_box / WX1), M["z"]))
    rows.append(sf("M6 T너트 볼트 인장 (x 간격 140, 2 개)", F * L_HAND / 140 / 2 / 1000, 11.6, unit="kN", note="8.8 볼트 보증 하중"))
    rows.append(sf("어댑터 Ø20 소켓 벽 (손잡이 굽힘 29 N·m 의 짝힘, 40 mm 깊이)", 29000 / 30 / (20 * 6), M["comp"], note="관이 소켓 위 · 아래 끝을 밂, 접촉 20×6 mm² 로 봄"))
    Tf, _, Ff = spring_torque(12)
    creep = [sf("스프링 판 ↔ 허브 평면 접촉 (예압, 계속)", SPRING["k"] * PRE / (math.pi * 40 ** 2 - math.pi * 15 ** 2), M["creep"], note="가운데에선 넓은 면 접촉"),
             sf("허브 가장자리 ↔ 판 (12° 끝, 순간, 선 접촉 10 mm 로 봄)", Ff / (10 * 2), M["comp"])]
    return dict(F_hand=F, gate_force=round(Fg), pivot_force=round(Rp), stop_deg=stop_deg, rows=rows, creep=creep,
                note="손 200 N 을 멈춤에 댄 채. PLA 층 안 50 / 층 사이 20 / 압축 60 MPa, 계속 10 MPa (추정)")

if __name__ == "__main__":
    def stop(axis, sg):
        a_ = 8.0
        while a_ < 25:
            a_ += 0.25
            r, p = (sg * a_, 0) if axis == "roll" else (0, sg * a_)
            try: v = (posed("stop_collar", r, p) & parts["gate_lid"]["shape"]).volume
            except Exception: v = 0
            if v > 0.05: return a_
        return None
    stops = dict(roll_L=stop("roll", 1), roll_R=stop("roll", -1), fwd=stop("pitch", 1), aft=stop("pitch", -1))
    T = min(v for v in stops.values()) - 0.5
    lid = parts.pop("gate_lid"); disc = parts.pop("spring_plate"); spr = parts.pop("spring"); gp_ = parts.pop("grip_proxy")
    poses = [(0, 0), (T, 0), (-T, 0), (0, T), (0, -T), (T * 0.7, T * 0.7), (-T * 0.7, -T * 0.7)]
    res = check_pairs(parts, posed, poses, ALLOW)
    # hub flange vs plate: at tilt the plate must go DOWN, never sideways into the walls (flange rim |x| vs wall)
    fl = parts["stick_hub"]["shape"]
    rim = max(posed("stick_hub", 0, T).bounding_box().max.X, posed("stick_hub", T, 0).bounding_box().max.Y)
    parts["gate_lid"] = lid; parts["spring_plate"] = disc; parts["spring"] = spr; parts["grip_proxy"] = gp_
    f = forces(); stg = strength(stops)
    info = export_parts({k: v for k, v in parts.items() if v["kind"] != "ref" or True}, HERE,
                        dict(pivot=[0, 0, PZ], stops_deg=stops, l_hand=L_HAND, grip_z=GRIP_Z, tube25_top=TUBE25_TOP, t20_top=T20_TOP,
                             printer=[240, 240, 240], spring=SPRING, preload_mm=PRE, hub_rim_reach=round(rim, 1), wall_inner_x=WX0),
                        extra=dict(forces=f, strength=stg, check=[dict(pose=p, hits=b_) for p, b_ in res],
                                   buttons=[dict(no=n, id=i, func=fn, part=pt, switch=sw) for n, i, fn, pt, sw in BUTTONS],
                                   wiring=[dict(frm=a_, to=b_, wire=c_, note=d_) for a_, b_, c_, d_ in WIRING],
                                   buy=[dict(item=a_, qty=b_, krw=c_, note=d_) for a_, b_, c_, d_ in BUY],
                                   third_party=dict(grip='F-16 Sidestick Grip by Spock', url='https://www.printables.com/model/233472', thingiverse='https://www.thingiverse.com/thing:4544115',
                                                    hat='https://www.thingiverse.com/thing:4543158 (same files are in the Printables zip hat_switch_files_incl_step_and_sldprt.zip)', license='CC BY-NC-SA (Printables page, read 2026-11-06)',
                                                    printed_parts_g_est=250, note='NOT in this repo (NC licence, public repo). Print from the source page.')))
    # remove STL of the proxy (not a part to print) is kept for the viewer only; mark it
    for i in info:
        print(f"{i['name']:18s} {i['group']:6s} {i['kind']:5s} {i['size']}  {i['grams'] or ''}")
    for p, b_ in res: print("pose", p, b_ if b_ else "none")
    print("stops", stops, "L_HAND", L_HAND, "PRE", PRE, "rim", round(rim, 1))
    print("hand N default", f["variants"]["default"]["N"])
    for r in stg["rows"] + stg["creep"]: print(f"SF {r['sf']:6.2f}  {r['load']:8.2f}/{r['limit']} {r['unit']}  {r['name']}")
