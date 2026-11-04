"""GyroSim cockpit layout - one place for every dimension, shared by make_textures.py (PIL, panel / dial textures) and
model_blender.py (Blender, geometry). Pure Python, no imports beyond math.

Frame: Unreal aircraft body frame, cm. X = forward, Y = right, Z = up. Eye point EYE = (430, 0, 100) (= sim_client.EYE,
the camera / VR head origin). Everything is our own geometry (license-clean); proportions follow public-domain USAF /
NASA cockpit photos (see ATTRIBUTION.md): centre stick, left throttle, rudder pedals with toe brakes, T-50 / F/A-18
style front panel (up-front control panel under the HUD, two MFDs, standby instruments in the middle).

Physical rig -> virtual cockpit
-------------------------------
The hand / foot controls sit where the real controls of the gyro chair are, relative to the seated eye (important in
VR). Source: index.html chair model (mm, x fwd, y LEFT, z up, origin = pitch axis, cage parts shifted by CAGE_SHIFT
= -49 mm) and the DIY control models hardware/stick/stick.py, hardware/throttle/throttle.py, hardware/pedals/pedals.py.
RIG_EYE is an ESTIMATE (index.html head sphere centre (-159, 0, 400) + 80 mm forward, 10 mm up) - adjust here when the
real eye position in the chair is measured, then rebuild (python Scripts/cockpit/build_cockpit.py + build_level.py).

The F-16 exterior (FlightGear, chase view) is kept for now; FIT_* below are its inner limits (measured by
fit_exterior.py) so our tub stays inside its skin (no poke-through, no z-fighting).
"""
import math

EYE = (430.0, 0.0, 100.0)

# ---- physical rig (mm, index.html frame after CAGE_SHIFT) ----------------------------------------------------------
RIG_EYE = (-79.0, 0.0, 410.0)       # estimate, see above


def rig(x, y_left, z):
    """index.html rig mm -> UE body cm (relative to EYE)."""
    return (EYE[0] + (x - RIG_EYE[0]) / 10.0, -y_left / 10.0, EYE[2] + (z - RIG_EYE[2]) / 10.0)


# centre stick: stick_base column x 241..291 (centre 266), top z -300; stick.py gimbal 60 mm above its base,
# grip 171..293 mm above the base. Travel +-20 deg both axes (stick.py TRAVEL).
STICK_PIVOT = rig(266, 0, -300 + 60)                 # (464.5, 0, 35)
STICK_GRIP_Z0, STICK_GRIP_Z1 = rig(0, 0, -300 + 171)[2], rig(0, 0, -300 + 293)[2]
STICK_TRAVEL = 20.0
# throttle: index throttle box x -49..111 (centre 31), y 290..350 (centre 320 = left), base underside z -200;
# throttle.py pivot 45 mm above the base, grip 140..215 mm above the base, swing +-30 deg (0 = aft, 1 = forward).
THR_PIVOT = rig(31, 320, -200 + 45)                  # (441, -32, 43.5)
THR_GRIP_Z0, THR_GRIP_Z1 = rig(0, 0, -200 + 140)[2], rig(0, 0, -200 + 215)[2]
THR_SWING = 30.0
CONSOLE_Z = rig(0, 0, -200)[2]                       # 39: throttle base = console top
# pedals: pedals.py hinge 70 mm above its base (bar 40 + 30), pedal centres |y| 135 mm, plates 84 x 220 mm leaning
# 20 deg forward, rudder bar +-20 deg about the centre (= pedal +-46 mm fore/aft), toe brake 15 deg.
# index.html pedal plates x 516..531, base on the rail at z -780.
PEDAL_HINGE_X, PEDAL_HINGE_Z = rig(520, 0, -780 + 70)[0], rig(0, 0, -780 + 70)[2]   # 489.9, -12
PEDAL_Y = 13.5
PEDAL_W, PEDAL_H, PEDAL_LEAN = 8.4, 22.0, 20.0
PEDAL_TRAVEL_CM = PEDAL_Y * math.sin(math.radians(20.0))    # 4.6
TOE_BRAKE_DEG = 15.0
SEAT_Z = rig(0, 0, -330)[2]                          # 26: seat surface
SEAT_FRONT_X = rig(181, 0, 0)[0]                     # 456
SEAT_BACK_X = rig(-299, 0, 0)[0]                     # 408 (backrest bottom), 15 deg recline
SEAT_RECLINE = 15.0

# ---- F-16 exterior fit (fit_exterior.py) ----------------------------------------------------------------------------
# skin half width (cm) at x stations and z levels; glass bottom edge (half width, z) and top z per x.
FIT_X = [360, 370, 380, 390, 400, 410, 420, 430, 440, 450, 460, 470, 480, 490, 500, 510, 520, 530, 540, 550, 560]
FIT_Z = [-10, 0, 10, 20, 30, 40, 50, 60, 70]
FIT_SKIN = [
    [68.5, 38.7, 72.0, 86.7, 79.1, 71.6, 61.5, 51.0, 40.3],
    [60.0, 39.4, 70.3, 85.0, 77.4, 69.9, 60.8, 50.3, 39.7],
    [56.2, 40.8, 69.0, 83.3, 75.7, 68.2, 60.2, 49.2, 38.8],
    [17.3, 42.2, 67.8, 82.0, 74.6, 67.1, 58.7, 47.8, 37.7],
    [17.7, 43.6, 66.6, 80.1, 73.5, 65.9, 57.3, 46.4, 36.6],
    [18.0, 45.0, 65.3, 78.6, 72.3, 64.8, 55.9, 44.8, 35.5],
    [18.3, 46.4, 64.0, 77.1, 71.2, 63.7, 54.4, 43.2, 34.4],
    [18.7, 47.8, 62.5, 75.6, 69.8, 62.6, 53.0, 41.7, 33.2],
    [19.0, 49.2, 61.4, 74.1, 68.3, 61.5, 51.5, 40.1, 32.0],
    [19.3, 50.6, 60.9, 72.6, 66.8, 60.3, 49.9, 38.6, 31.0],
    [20.7, 51.4, 60.4, 71.1, 65.3, 59.2, 48.4, 37.3, 30.5],
    [22.2, 51.0, 59.9, 69.6, 63.8, 58.0, 47.2, 36.0, 30.0],
    [23.7, 50.5, 59.5, 68.1, 62.3, 56.7, 46.2, 34.9, 29.5],
    [25.2, 50.0, 59.0, 66.7, 60.9, 55.3, 45.1, 33.8, 29.0],
    [26.7, 49.5, 58.5, 65.2, 59.4, 53.8, 44.1, 32.6, 28.5],
    [28.2, 49.1, 58.0, 63.7, 58.0, 52.4, 43.0, 31.6, 28.0],
    [29.7, 48.6, 57.5, 62.2, 56.9, 51.0, 41.9, 30.7, 27.0],
    [31.2, 48.1, 57.1, 60.7, 55.7, 49.5, 40.7, 29.7, 26.0],
    [32.7, 47.6, 56.6, 59.2, 54.5, 48.1, 39.3, 28.7, 22.0],
    [34.2, 47.1, 56.1, 58.0, 53.4, 46.7, 37.9, 24.8, 16.0],
    [35.5, 47.1, 55.7, 56.8, 52.2, 45.2, 36.4, 14.6, 10.0],
]
# canopy glass bottom edge (half width, z) and glass top z (outer surface)
FIT_GLASS = {360: (30.2, 79.4, 94.2), 370: (28.5, 106.7, 126.7), 380: (33.4, 81.4, 126.1), 390: (32.9, 75.4, 125.6),
             400: (32.9, 74.4, 125.0), 410: (32.8, 73.3, 124.2), 420: (32.6, 72.2, 123.1), 430: (32.4, 71.1, 120.9),
             440: (32.1, 70.0, 118.7), 450: (31.6, 69.1, 116.0), 460: (31.0, 68.4, 113.3), 470: (30.4, 67.6, 110.1),
             480: (29.9, 66.8, 105.6), 490: (29.2, 66.0, 101.1), 500: (28.6, 65.2, 96.6), 510: (27.9, 64.5, 92.0),
             520: (27.2, 63.7, 87.1), 530: (26.3, 62.9, 81.5), 540: (22.5, 62.7, 75.0), 550: (16.5, 62.5, 68.7)}
# inner canopy arch shape at x = 468 (half width / height normalised), used to place the windscreen bow
GLASS_ARCH_468 = [(30.56, 67.74), (30.39, 73.74), (30.19, 80.63), (28.74, 84.65), (26.54, 90.35), (23.0, 98.31), (20.3, 102.63),
                  (16.9, 106.27), (12.11, 108.55), (4.72, 110.11), (0.0, 110.17)]
GLASS_ARCH_372 = [(31.03, 101.53), (25.92, 110.84), (17.45, 118.28), (14.98, 120.89), (9.47, 123.87), (0.0, 125.6)]


def _interp(xs, ys, x):
    if x <= xs[0]:
        return ys[0]
    for i in range(len(xs) - 1):
        if x <= xs[i + 1]:
            t = (x - xs[i]) / (xs[i + 1] - xs[i])
            return ys[i] + t * (ys[i + 1] - ys[i])
    return ys[-1]


def skin_half_width(x, z):
    row = [_interp(FIT_X, [FIT_SKIN[i][j] for i in range(len(FIT_X))], x) for j in range(len(FIT_Z))]
    return _interp(FIT_Z, row, z)


def glass_bottom(x):
    xs = sorted(k for k in FIT_GLASS if k >= 390)
    return (_interp(xs, [FIT_GLASS[k][0] for k in xs], x), _interp(xs, [FIT_GLASS[k][1] for k in xs], x))


def glass_top(x):
    xs = sorted(k for k in FIT_GLASS if k >= 380)
    return _interp(xs, [FIT_GLASS[k][2] for k in xs], x)


# ---- cockpit structure ----------------------------------------------------------------------------------------------
TUB_X0, TUB_X1 = 376.0, 514.0        # aft bulkhead, front of the foot well
CONSOLE_IN = 25.0                     # console inner edge |y|
SKIN_GAP = 1.6                        # tub inner wall offset inside the F-16 skin


def floor_z(x):
    return -9.0 if x <= 430 else (-13.0 if x >= 480 else -9.0 - 4.0 * (x - 430) / 50.0)


# main instrument panel face: x(z) = PANEL_X0 - PANEL_TILT * (z - 40); top leans toward the pilot
PANEL_X0, PANEL_TILT = 509.0, 0.12
PANEL_Z0 = 12.0                       # bottom edge (between the consoles)
LIP_Y, LIP_Z0, LIP_ZC = 26.5, 65.0, 77.0   # glare shield lip: ellipse from (+-LIP_Y, LIP_Z0) to (0, LIP_ZC)
GLARE_X1 = 542.0                      # glare shield runs forward under the windscreen to here


def panel_x(z):
    return PANEL_X0 - PANEL_TILT * (z - 40.0)


def lip_z(y):
    a = min(1.0, abs(y) / LIP_Y)
    return LIP_Z0 + (LIP_ZC - LIP_Z0) * math.sqrt(max(0.0, 1.0 - a * a))


PANEL_N = (-1.0 / math.hypot(1, PANEL_TILT), 0.0, -PANEL_TILT / math.hypot(1, PANEL_TILT))   # face normal, toward the pilot
PANEL_UP = (-PANEL_TILT / math.hypot(1, PANEL_TILT), 0.0, 1.0 / math.hypot(1, PANEL_TILT))


def panel_pt(u, v, off=0.0):
    """main panel face coordinates (u = y right, v = z up, cm) -> UE point, `off` cm toward the pilot."""
    return (panel_x(v) + PANEL_N[0] * off, u, v + PANEL_N[2] * off)


# HUD: combiner frame on the glare shield, tilted back (top toward the pilot)
HUD_X, HUD_Z0, HUD_Z1, HUD_W, HUD_TILT = 500.5, 77.6, 95.0, 22.0, 18.0
BOW_X = 468.0                          # windscreen bow (follows the canopy glass, above the HUD field of view)
REAR_ARCH_X = 372.0

# ---- instruments / screens on the main panel (u = y, v = z) --------------------------------------------------------
MFD_BEZEL, MFD_SCREEN = 15.0, 10.6
MFD = {"MFD_L": (-21.0, 46.5), "MFD_R": (21.0, 46.5)}
UFCP = dict(u=0.0, v=65.4, w=19.0, h=17.6)
GAUGES = {   # name: (u, v, bezel diameter, dial), live ones have needles
    "ADI": (0.0, 50.4, 9.0, "adi"),
    "ASI": (-6.4, 39.5, 7.2, "asi"),
    "ALT": (6.4, 39.5, 7.2, "alt"),
    "VSI": (0.0, 29.9, 7.2, "vsi"),
    "CLOCK": (35.0, 45.0, 5.6, "clock"),
    "RPM": (19.0, 31.0, 6.0, "rpm"),
    "FTIT": (19.0, 20.5, 6.0, "ftit"),
    "FUEL": (0.0, 19.6, 6.6, "fuel"),
}
LIVE_NEEDLES = {"ASI": ["asi"], "ALT": ["alt", "alt10k"], "VSI": ["vsi"]}
GEAR_HANDLE = dict(u=-35.5, v=46.0, arm=6.5, knob=3.6, travel=16.0)
GEAR_LIGHTS = [(-19.0, 34.0), (-22.0, 31.0), (-16.0, 31.0)]   # nose, left, right
EYEBROWS = {"EB_L": (-17.6, 59.8, ("MASTER CAUTION", "FIRE"), ("amber", "red")),
            "EB_R": (17.6, 59.8, ("ENG", "HYD/OIL"), ("red", "amber"))}

# main panel decorative / small controls (kind, u, v, label, opts)
MAIN_ELEMENTS = [
    ("toggle", -22.0, 21.5, "MASTER ARM", dict(pos=("ARM", "OFF", "SIM"), state=0)),
    ("button", -16.0, 21.5, "EMER JETT", dict(ring="stripe")),
    ("toggle", -19.0, 15.0, "LDG LT", dict(pos=("ON", "TAXI", "OFF"), state=1)),
    ("knob", 35.0, 40.4, "BARO", dict(small=True)),
    ("knob", -34.0, 41.0, "HOOK", dict(small=True)),
]

# ---- consoles: top plates (u = y right, v = x forward) ------------------------------------------------------------
# (name, u0, u1, v0, v1, title, [elements]) ; element = (kind, u, v, label, opts)
CONSOLE_PANELS = [
    ("L1", -48.5, -25.6, 378.5, 399.5, "COMM", [
        ("knob", -42.5, 393.5, "VOL", {}), ("knob", -32.0, 393.5, "CHAN", {}),
        ("toggle", -42.5, 384.0, "SQL", dict(pos=("ON", "", "OFF"), state=0)), ("display", -31.5, 384.0, "CH 12", dict(w=7.0, h=2.2))]),
    ("L2", -48.5, -25.6, 400.0, 421.0, "AUDIO", [
        ("knob", -43.0, 415.0, "COMM 1", {}), ("knob", -31.5, 415.0, "COMM 2", {}),
        ("knob", -43.0, 405.5, "SECURE", {}), ("knob", -31.5, 405.5, "TACAN", {})]),
    ("L3", -48.5, -40.0, 421.5, 460.5, "ENG", [
        ("toggle", -44.2, 452.0, "ENG CONT", dict(pos=("PRI", "", "SEC"), state=0)),
        ("toggle", -44.2, 441.5, "AB RESET", dict(pos=("ON", "NORM", ""), state=1)),
        ("button", -44.2, 431.0, "IDLE DET", {}),
        ("knob", -44.2, 424.6, "FRICT", dict(small=True))]),
    ("L4", -48.5, -25.6, 461.0, 480.0, "ENGINE START", [
        ("guard", -43.0, 470.5, "JFS", dict(pos=("START", "OFF", ""), state=1)),
        ("toggle", -36.0, 470.5, "MAX PWR", dict(pos=("ON", "", "OFF"), state=2)),
        ("knob", -29.5, 470.5, "ENG FEED", dict(small=True))]),
    ("L5", -48.5, -25.6, 480.5, 498.5, "FUEL", [
        ("guard", -43.0, 489.5, "MASTER", dict(pos=("ON", "", "OFF"), state=0, color="red")),
        ("toggle", -36.0, 489.5, "INERT", dict(pos=("ON", "", "OFF"), state=2)),
        ("toggle", -29.5, 489.5, "EXT TRANS", dict(pos=("WING", "", "NORM"), state=2))]),
    ("R1", 25.6, 48.5, 378.5, 399.5, "OXYGEN", [
        ("light", 30.5, 394.0, "FLOW", dict(color="green", w=3.2, h=1.6)), ("gauge", 42.0, 393.5, "O2 QTY", dict(d=4.6, dial="o2")),
        ("toggle", 30.0, 384.0, "SUPPLY", dict(pos=("ON", "", "OFF"), state=0)), ("toggle", 36.5, 384.0, "DILUTER", dict(pos=("100%", "", "NORM"), state=2)),
        ("toggle", 43.0, 384.0, "EMERG", dict(pos=("EMER", "NORM", "TEST"), state=1))]),
    ("R2", 25.6, 48.5, 400.0, 421.0, "SENSOR PWR", [
        ("toggle", 29.5, 410.5, "L HDPT", dict(pos=("ON", "", "OFF"), state=2)), ("toggle", 35.0, 410.5, "R HDPT", dict(pos=("ON", "", "OFF"), state=2)),
        ("toggle", 40.5, 410.5, "FCR", dict(pos=("ON", "", "OFF"), state=0)), ("toggle", 46.0, 410.5, "RDR ALT", dict(pos=("ON", "STBY", "OFF"), state=0))]),
    ("R3", 25.6, 48.5, 421.5, 443.0, "AVIONICS POWER", [
        ("toggle", 29.5, 436.5, "MMC", dict(pos=("ON", "", "OFF"), state=0)), ("toggle", 35.0, 436.5, "ST STA", dict(pos=("ON", "", "OFF"), state=0)),
        ("toggle", 40.5, 436.5, "MFD", dict(pos=("ON", "", "OFF"), state=0)), ("toggle", 46.0, 436.5, "UFC", dict(pos=("ON", "", "OFF"), state=0)),
        ("knob", 32.0, 426.5, "INS", dict(ticks=("OFF", "STOR", "NORM", "NAV"))), ("toggle", 42.5, 426.5, "GPS", dict(pos=("ON", "", "OFF"), state=0))]),
    ("R4", 25.6, 48.5, 443.5, 465.0, "LIGHTING", [
        ("knob", 31.0, 459.0, "PRIMARY", {}), ("knob", 42.0, 459.0, "FLOOD", {}),
        ("knob", 31.0, 449.5, "INST", {}), ("knob", 42.0, 449.5, "CONSOLE", {})]),
    ("R5", 25.6, 48.5, 465.5, 485.0, "ENV CONT", [
        ("knob", 31.0, 476.0, "TEMP", dict(ticks=("COLD", "", "HOT"))), ("knob", 42.0, 476.0, "AIR SOURCE", dict(ticks=("OFF", "NORM", "DUMP", "RAM"))),
        ("toggle", 36.5, 468.5, "DEFOG", dict(pos=("ON", "", "OFF"), state=2))]),
    ("R6", 25.6, 48.5, 485.5, 498.5, "ANTI-ICE", [
        ("toggle", 31.0, 491.8, "ENG", dict(pos=("ON", "AUTO", "OFF"), state=1)), ("toggle", 41.0, 491.8, "PITOT", dict(pos=("ON", "", "OFF"), state=0))]),
]
THR_HOUSING = dict(u0=-39.0, u1=-25.6, v0=421.5, v1=460.5, h=4.6)   # throttle quadrant housing on the left console

# ---- texture atlas ----------------------------------------------------------------------------------------------------
ATLAS = 4096
PX_MAIN, PX_CONSOLE, PX_SMALL = 20, 24, 32     # px per cm
MAIN_U0, MAIN_U1, MAIN_V0, MAIN_V1 = -60.0, 60.0, 10.0, 80.0
DIALS = ["asi", "alt", "vsi", "adi", "clock", "rpm", "ftit", "fuel", "oil", "o2", "stripe"]
DIAL_TILE = 512


def dial_tile(name):
    """(u0, v0, u1, v1) in 0..1 of the 2048 dial atlas (4 x 4 tiles of 512)."""
    i = DIALS.index(name)
    c, r = i % 4, i // 4
    return (c / 4.0, r / 4.0, (c + 1) / 4.0, (r + 1) / 4.0)
