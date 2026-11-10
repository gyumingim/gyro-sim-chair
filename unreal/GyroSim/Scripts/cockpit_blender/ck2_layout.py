"""Cockpit v2 (F-16 Block 50/52 style interior) - one place for every dimension, shared by
ck2_textures.py (PIL atlas: panel paint, legends, dial faces, normal map) and ck2_model.py (Blender geometry).
Pure Python (math only).

Frame: Unreal aircraft body frame, cm. X forward, Y right, Z up. Eye point EYE = (430, 0, 100) (= sim_client.EYE).
All geometry is our own (original model, no third-party mesh). Proportions follow real F-16 photos
(C:/GyroSimTiles/refs/f16_cockpit, sources.json there; best views 003 top-down MLU, 005 Block 52, 010 right console):
narrow centre instrument column (ASI | ALT, AOA | ADI | VVI, HSI) running down to the seat, two MFDs flanking its top,
the ICP keypad under the HUD, engine gauges on the angled right wing, leg wells either side of the column, side
consoles with black panels and white legends, sidestick forward on the right console, throttle on the left console.

Fixed by the sim (kept from Scripts/cockpit/layout.py): eye point, the HUD combiner optical surface (build_level HUD clip),
F-16 exterior skin limits (FIT_* via Scripts/cockpit/layout.py), stick / throttle pivots near the physical rig controls.
"""
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "cockpit"))
import layout as OLD          # noqa: E402  (exterior fit tables, rig positions; read only)

EYE = OLD.EYE
skin_half_width, glass_bottom, glass_top = OLD.skin_half_width, OLD.glass_bottom, OLD.glass_top

# ---------------------------------------------------------------------------------------------------------------------
# main instrument panel face: x(z) = PANEL_X0 - PANEL_TILT * (z - 40); top leans toward the pilot (same plane as v1,
# so the old needle / ADI frames keep their orientation)
PANEL_X0, PANEL_TILT = 509.0, 0.12
_n = math.hypot(1.0, PANEL_TILT)
PANEL_N = (-1.0 / _n, 0.0, -PANEL_TILT / _n)          # toward the pilot
PANEL_UP = (-PANEL_TILT / _n, 0.0, 1.0 / _n)


def panel_x(z):
    return PANEL_X0 - PANEL_TILT * (z - 40.0)


def add(a, b, k=1.0):
    return (a[0] + b[0] * k, a[1] + b[1] * k, a[2] + b[2] * k)


def panel_pt(u, v, off=0.0):
    """centre panel (u = y right, v = z up, cm) -> UE point, `off` cm toward the pilot"""
    return add((panel_x(v), u, v), PANEL_N, off)


# angled wings either side of the MFDs (engine gauges right, armament / RWR left): hinge at |u| = WING_U, folded
# WING_DEG toward the pilot
WING_U, WING_DEG, WING_W = 32.0, 38.0, 8.0
WING_V0, WING_V1 = 41.2, 55.0
AUX_U0, AUX_U1 = 27.0, 39.0       # auxiliary panels outboard of the leg wells (|u|), v 18..41


def wing_frame(side):
    """(origin at hinge v=0, ex = along the wing outward, ey = up, n = toward the pilot) for side -1 (left) / +1"""
    t = math.radians(WING_DEG)
    ex = add((0.0, side * math.cos(t), 0.0), PANEL_N, math.sin(t))
    ex = (ex[0], ex[1], ex[2])
    n = add(tuple(c * math.cos(t) for c in PANEL_N), (0.0, -side * math.sin(t), 0.0))
    return ex, PANEL_UP, n


def wing_pt(side, w, v, off=0.0):
    ex, ey, n = wing_frame(side)
    p = panel_pt(side * WING_U, v)
    return add(add(p, ex, w), n, off)


# glare shield: lip over the panel top, flat-topped hood running forward under the windscreen
LIP_HALF, LIP_Z0, LIP_ZC = 33.0, 61.0, 68.8          # lip height LIP_ZC on the centre line, LIP_Z0 at |u| = LIP_HALF
LIP_OVER = 4.0                                        # hood overhang toward the pilot past the panel face
GLARE_X1 = 541.0


def lip_z(u):
    a = min(1.0, abs(u) / LIP_HALF)
    return LIP_Z0 + (LIP_ZC - LIP_Z0) * math.sqrt(max(0.0, 1.0 - a ** 4))


# HUD combiner: the optical surface is FIXED (build_level.py HUD clip uses Art/Cockpit/manifest.json hud_combiner)
# v2 (11-10): narrower / shorter glass (review: the 27.8 x 31 cm glass and its heavy frame looked oversized). Same base and
# tilt (the HUD clip material's constants); the width / height are scalar params (C_Wd / C_H1) set at Play by cockpit_v2.
# 24 cm wide = +-9.8 deg at ~70 cm (speed / altitude boxes fit), top 28 cm = about +5 deg (F-16 HUD TFOV ~25 deg).
HUD = dict(base=(500.5, 0.0, 78.2), fwd=(0.9510565, 0.0, 0.309017), up=(-0.309017, 0.0, 0.9510565), w=22.4, h0=0.9, h1=26.4, r=1.6,
           poly=[(-9.7, 4.42), (9.7, 4.42), (11.2, 11.42), (11.2, 19.6), (5.8, 26.4), (-5.8, 26.4), (-11.2, 19.6), (-11.2, 11.42)])    # round 4: a little smaller
HUD_BODY = dict(x0=500.0, x1=528.0, w=17.0, z0=69.5, z1=76.8)   # HUD housing on the glare shield

# ---------------------------------------------------------------------------------------------------------------------
# front panel elements (centre panel u, v)
COL_HALF = 11.5            # centre instrument column half width
COL_V0 = 14.0              # column bottom
WELL_DEPTH = 13.0          # leg wells: lower panel either side of the column is set this far forward
WELL_V1 = 41.0             # leg well top (under the MFDs)
MFD_U, MFD_V, MFD_BEZEL, MFD_SCREEN = 23.5, 53.0, 16.6, 11.6     # photo 001: MFD centres level with the ICP foot
MFD_DEPTH = 2.2     # 4 in class display, bezel with 5 OSBs a side
ICP = dict(u=0.0, v=61.4, w=15.0, h=8.8, depth=3.2)               # integrated control panel (keypad), under the HUD
DED = dict(u=0.0, v=54.8, w=11.0, h=3.6, bw=13.6, bh=5.2)         # data entry display (green text window)
# instruments: name: (u, v, bezel diameter, dial face, sim needle / ball)
GAUGES = {
    "ASI": (-5.6, 47.4, 7.6, "asi", "asi"),
    "ALT": (5.6, 47.4, 7.6, "alt", "alt"),
    "AOA": (-8.6, 38.6, 3.6, "aoa_tape", None),
    "ADI": (0.0, 38.6, 9.0, "adi", "adi"),
    "VVI": (8.6, 38.6, 3.6, "vvi_tape", None),
    "HSI": (0.0, 28.6, 8.6, "hsi", None),
}
# needle frames of the sim (Needle_<n>, NeedleFrame parent): dial centre -> manifest; vsi drives the VVI window via a
# small round standby VVI on the right of the column (round gauge so the needle reads)
VVI_ROUND = (8.6, 38.6, 3.6)
LEFT_LOW = {"FUEL": (-21.5, 34.5, 6.6, "fuel"), "CLOCK": (-27.5, 26.0, 5.2, "clock")}
RIGHT_LOW = {"CMPS": (19.0, 35.5, 5.0, "compass"), "OXY": (27.0, 35.5, 5.0, "oxy"), "EPU": (27.0, 27.0, 4.4, "epu")}
WING_GAUGES = {"NOZ": (4.0, 52.2, 3.9, "noz"), "RPM": (4.0, 48.1, 4.1, "rpm"), "FTIT": (4.0, 44.0, 3.9, "ftit")}
RWR = dict(w=4.1, v=50.0, size=6.4)                  # left wing: threat warning azimuth indicator (square scope)
EYEBROW_L = dict(u0=-29.0, u1=-13.0, v0=61.9, v1=65.0)
EYEBROW_R = dict(u0=13.0, u1=29.0, v0=61.9, v1=65.0)
# sim lights: name -> (where, u/w, v, w, h, colour, legend)
# sim lights: name -> (plate, a, b, w, h, colour, legend) in plate cm. MC / WARN take the first / last eyebrow lamp cells,
# the others sit on the left auxiliary console (front of the left console) next to the gear handle
LIGHTS = {"MC": ("UF_L", 1.75, 1.45, 3.0, 2.3, "amber", "MASTER|CAUTION"), "WARN": ("UF_R", 4.85, 1.45, 3.0, 2.3, "red", "WARNING"),
          "BRAKE": ("AUX_L", 3.6, 4.8, 3.4, 1.8, "amber", "BRAKES"), "ASSIST": ("AUX_L", 7.6, 4.8, 3.4, 1.8, "green", "ASSIST"),
          "SLOW": ("AUX_L", 3.6, 2.4, 3.4, 1.8, "green", "SLOW"), "VOICE": ("AUX_L", 7.6, 2.4, 3.4, 1.8, "green", "VOICE")}
GEAR = dict(plate="AUX_L", a=14.0, b=8.0, travel=16.0)       # gear handle (wheel knob) on the left auxiliary console
GEAR_LIGHTS = [(19.5, 13.4), (18.0, 11.4), (21.0, 11.4)]     # nose, left, right (plate cm; green, sim GearLights)
EJECT = dict(x=465.0, z=30.0, w=13.0)                # yellow ejection loop at the seat front (between the knees)

# ---------------------------------------------------------------------------------------------------------------------
# consoles
CONSOLE_Z = 40.0
CONSOLE_IN, CONSOLE_OUT = 24.5, 47.0
CONSOLE_X0, CONSOLE_X1 = 382.0, 503.0
STICK_SIDE = dict(pivot=(462.0, 33.5, 42.5), lean=12.0)   # sidestick pivot (boot top), grip leans forward
THR = dict(pivot=(441.0, -32.0, 43.5), slot=(-35.5, 425.0, 470.0))   # same pivot as v1 (physical rig)
ARMREST = dict(x0=414.0, x1=448.0, y0=29.0, y1=44.0, z1=47.0)


def wall_y(x, z):
    """cockpit inner wall |y| at (x, z): F-16 skin minus gap"""
    return skin_half_width(x, z) - 1.8


SILL_Z0 = 66.0             # sill (canopy rail) top area


# ---------------------------------------------------------------------------------------------------------------------
# plates: textured faces (atlas regions). Each plate: name, origin (UE, the plate's (0,0) corner), ex, ey (unit), w, h
# (cm), ppc (atlas px per cm), raise (cm above the base surface), items (drawn by ck2_textures, built by ck2_model).
# item kinds: label(x, y, text, size, [align]) | screw(x, y) | toggle(x, y, [style]) | knob(x, y, d, [ticks]) |
# button(x, y, w, h, [text]) | dial(x, y, d, face) | lamp(x, y, w, h, colour, text) | grille(x0, y0, x1, y1) |
# display(x, y, w, h, lines) | guard(x, y, colour) | stripes(x0, y0, x1, y1) | wheel(x, y)

def _console_plates(side):
    """F-16 style console panel stacks, front (high x) to back. side -1 left, +1 right. Returns (name, x0, x1, u0, u1, title, items)
    with items in plate cm (x = across, right positive, y = forward)."""
    if side < 0:
        return [
            ("AUX_L", 486.0, 502.5, "", [("wheel", GEAR["a"], GEAR["b"]), ("label", 14.0, 15.3, "WHEELS", 0.5), ("label", 6.0, 14.6, "DN LOCK REL", 0.32),
                                         ("stripes", 9.6, 4.0, 10.8, 12.0), ("toggle", 4.0, 10.5), ("label", 4.0, 12.6, "ANTI-SKID", 0.36)]
             + [("lamp",) + LIGHTS[k][1:] for k in ("BRAKE", "ASSIST", "SLOW", "VOICE")]
             + [("lamp", a, b, 1.5, 1.5, "green", "") for a, b in GEAR_LIGHTS]),
            ("L_FLCS", 470.0, 485.5, "FLT CONTROL", [("guard", 5.0, 8.5, "red"), ("toggle", 11.0, 8.5), ("toggle", 16.5, 8.5), ("knob", 5.0, 3.5, 2.4),
                                                     ("toggle", 11.0, 3.5), ("button", 16.5, 3.5, 2.6, 2.0, "RESET")]),
            ("L_THR", 425.0, 469.5, "", []),        # throttle quadrant (built separately)
            ("L_ECM", 405.0, 424.5, "ECM", [("button", 3.5 + 3.4 * i, 14.0, 2.6, 2.4, "") for i in range(6)] + [("knob", 5.0, 6.5, 2.6), ("knob", 12.0, 6.5, 2.2), ("toggle", 18.0, 6.5)]),
            ("L_AUD1", 393.5, 404.5, "AUDIO 1", [("knob", 3.5 + 4.0 * i, 6.0, 2.4) for i in range(5)]),
            ("L_AUD2", 382.5, 393.0, "AUDIO 2", [("knob", 4.0, 5.5, 2.4), ("knob", 9.0, 5.5, 2.4), ("toggle", 14.0, 5.5), ("toggle", 18.5, 5.5)]),
        ]
    return [
        ("AUX_R", 486.0, 502.5, "", [("dial", 5.0, 10.0, 4.4, "oil"), ("dial", 11.5, 10.0, 3.8, "hyd"), ("knob", 18.0, 10.0, 2.6, "HYD PRESS"),
                                     ("toggle", 5.0, 3.5), ("toggle", 10.0, 3.5), ("toggle", 15.0, 3.5)]),
        ("R_GRILLE", 471.5, 490.5, "", [("grille", 2.5, 2.5, 20.0, 16.0)]),
        ("R_STICK", 452.0, 471.0, "", []),       # sidestick base area
        ("R_HUD", 438.0, 451.5, "HUD", [("toggle", 3.5 + 4.0 * i, 9.5) for i in range(5)] + [("toggle", 3.5 + 4.0 * i, 4.0) for i in range(5)]),
        ("R_LIGHT", 420.0, 437.5, "INTERIOR LIGHTING", [("knob", 4.0 + 4.8 * i, 12.0, 2.4) for i in range(4)] + [("knob", 4.0 + 4.8 * i, 5.0, 2.4) for i in range(4)]),
        ("R_AIR", 403.5, 419.5, "AIR COND", [("knob", 6.0, 8.0, 3.0), ("knob", 15.0, 8.0, 3.0), ("guard", 10.5, 3.0, "red")]),
        ("R_AVP", 382.5, 403.0, "AVIONIC POWER", [("toggle", 3.5 + 4.0 * i, 14.5) for i in range(5)] + [("knob", 6.0, 6.5, 3.0), ("toggle", 13.0, 6.5), ("toggle", 18.0, 6.5)]),
    ]


TOGGLE_LABELS = {  # generic legends (no real part numbers / logos)
    "L_TEST": ["FLCS PWR", "PROBE HT", "EPU/GEN", "", "OXY", "MAL IND"], "L_FLCS": ["DIGITAL", "ALT FLAPS", "LE FLAPS", "BIT", "MANUAL", ""],
    "L_ECM": ["1", "2", "3", "4", "5", "6", "PWR", "DIM", "XMIT"], "L_AUD1": ["COMM 1", "COMM 2", "MSL", "THREAT", "INTERCOM"],
    "L_AUD2": ["TACAN", "ILS", "HOT MIC", "VOICE MSG"],
    "AUX_R": ["L HDPT", "R HDPT", "FCR"], "R_HUD": ["SCALES", "FPM", "DED DATA", "DEPR RET", "SPEED", "ALT", "BRT", "TEST", "STEP", "VAH"],
    "R_LIGHT": ["CONSOLES", "INST PNL", "DATA DISP", "FLOOD", "CONSOLES", "INST PNL", "FLOOD", "MAL & IND"],
    "R_AIR": ["TEMP", "AIR SOURCE", "DEFOG"], "R_AVP": ["MMC", "ST STA", "MFD", "UFC", "GPS", "INS", "DL", "MAP"],
}


FILL_WORDS = ["PWR", "TEST", "NORM", "ARM", "AUTO", "MAN", "BIT", "RESET", "XFER", "STBY", "EMER", "DIM", "MODE", "SEL", "ON", "AUX",
              "IFF", "MSL", "TACAN", "DATA", "CMDS", "FLARE", "CHAFF", "JMR", "PRGM", "HOLD", "NAV", "ILS", "LAND", "TAXI", "ANTI ICE", "PROBE"]


def densify(p, sx=3.6, sy=4.4, keep_out=2.7, top_margin=2.4, seed=1):
    """fill the empty area of a plate with rows of switches / knobs / guards / breakers (review round 4: too sparse).
    Deterministic. Items keep `keep_out` cm from existing ones; legends come from FILL_WORDS (generic text)."""
    import random
    rnd = random.Random(sum(map(ord, p["name"])) * 31 + seed)   # stable across processes (no str hash)
    pts = [(it[1], it[2]) for it in p["items"] if len(it) > 2 and isinstance(it[1], (int, float))]
    big = [it for it in p["items"] if it[0] in ("grille", "stripes")]
    w, h = p["w"], p["h"] - (top_margin if p.get("title") else 0.8)
    out = []
    y = 2.2
    row = 0
    while y < h - 1.4:
        x = 2.2 + (sx / 2 if row % 2 else 0.0)
        kind = rnd.choice(("toggle", "toggle", "knob", "breaker", "toggle", "button"))
        while x < w - 1.6:
            free = all((x - a) ** 2 + (y - b) ** 2 > keep_out ** 2 for a, b in pts)
            free = free and not any(it[1] - 1.0 < x < it[3] + 1.0 and it[2] - 1.0 < y < it[4] + 1.0 for it in big)
            if free:
                k = kind if rnd.random() > 0.15 else rnd.choice(("guard", "knob", "toggle"))
                if k == "toggle":
                    out.append(("toggle", x, y, rnd.choice(FILL_WORDS)))
                elif k == "knob":
                    out.append(("knob", x, y, rnd.choice((2.0, 2.2, 2.6)), rnd.choice(FILL_WORDS)))
                elif k == "breaker":
                    out.append(("breaker", x, y))
                elif k == "button":
                    out.append(("button", x, y, 2.4, 1.6, rnd.choice(FILL_WORDS)))
                else:
                    out.append(("guard", x, y, rnd.choice(("red", "red", "black"))))
                pts.append((x, y))
            x += sx if kind != "breaker" else 1.6
        y += sy if kind != "breaker" else 2.6
        row += 1
    p["items"] = p["items"] + out
    return p


def console_plates():
    """console top plates in the generic plate format"""
    out = []
    for side in (-1, 1):
        for name, x0, x1, title, items in _console_plates(side):
            w = CONSOLE_OUT - CONSOLE_IN
            u0 = -CONSOLE_OUT if side < 0 else CONSOLE_IN
            pl = dict(name=name, origin=(x0, u0, CONSOLE_Z), ex=(0.0, 1.0, 0.0), ey=(1.0, 0.0, 0.0), w=w, h=x1 - x0, ppc=30,
                      raise_=0.35, title=title, items=list(items), kind="console")
            if name not in ("L_THR", "R_STICK", "AUX_L"):
                densify(pl)
            out.append(pl)
    return out


def panel_plates():
    """front panel plates (centre column, MFD surrounds, eyebrows, wings, lower panels)"""
    P = []

    def pp(name, u0, v0, u1, v1, items, title="", ppc=40, raise_=0.4):
        P.append(dict(name=name, origin=panel_pt(u0, v0), ex=(0.0, 1.0, 0.0), ey=PANEL_UP, w=u1 - u0, h=v1 - v0, ppc=ppc, raise_=raise_,
                      title=title, items=items, kind="panel", uv0=(u0, v0)))

    # centre column: three stacked plates
    it = []
    for n, (u, v, d, face, _s) in GAUGES.items():
        if n in ("ASI", "ALT"):
            it.append(("dial", u + COL_HALF, v - 43.2, d, face))
    pp("C_TOP", -COL_HALF, 43.2, COL_HALF, 52.0, it)
    it = [("dial", 0.0 + COL_HALF, 38.6 - 33.6, 9.0, "adi"), ("tape", -8.6 + COL_HALF, 5.0, 3.0, 7.4, "AOA"), ("dial", 8.6 + COL_HALF, 5.0, 3.6, "vvi")]
    pp("C_MID", -COL_HALF, 33.6, COL_HALF, 43.0, it)
    it = [("dial", COL_HALF, 28.6 - 14.0, 8.6, "hsi"), ("knob", 3.0, 18.0, 2.4, "HDG"), ("knob", 3.0, 11.0, 2.4, "CRS"), ("label", 3.0, 7.9, "MODE", 0.55),
          ("toggle", 20.0, 16.5), ("knob", 20.0, 10.8, 2.6, "FUEL QTY SEL"), ("label", 7.0, 3.2, "PEDAL ADJ", 0.6), ("button", 15.5, 3.2, 3.4, 2.4, "")]
    pp("C_LOW", -COL_HALF, COL_V0, COL_HALF, 33.4, it)
    # ICP (keypad box standing ICP["depth"] proud of the panel): face plate, keys are raised boxes whose tops map here
    keys = []
    for r, row in enumerate((("1|T-ILS", "2|ALOW", "3"), ("4|STPT", "5|CRUS", "6|TIME"), ("7|MARK", "8|FIX", "9|A-CAL"), ("RCL", "0|M-SEL", "ENTR"))):
        for c, t in enumerate(row):
            keys.append(("button", 5.6 + 1.9 * c, 6.1 - 1.65 * r, 1.6, 1.35, t))
    for r, t in enumerate(("COM|1", "COM|2", "IFF", "LIST")):
        keys.append(("button", 1.9, 6.1 - 1.65 * r, 2.2, 1.35, t))
    keys += [("button", 11.6, 6.1, 1.9, 1.35, "A-A"), ("button", 13.6, 6.1, 1.9, 1.35, "A-G"), ("rocker", 12.6, 3.3, 1.2, 2.6, ""),
             ("toggle", 11.4, 0.9), ("button", 13.7, 1.0, 1.6, 1.1, "WX")]
    keys += [("wheel_s", 2.4 + 3.4 * i, 8.0, 1.6, t) for i, t in enumerate(("SYM", "BRT", "DEPR", "CONT"))]
    P.append(dict(name="ICP", origin=panel_pt(ICP["u"] - ICP["w"] / 2, ICP["v"] - ICP["h"] / 2, ICP["depth"]), ex=(0.0, 1.0, 0.0), ey=PANEL_UP,
                  w=ICP["w"], h=ICP["h"], ppc=64, raise_=0.0, title="", kind="icp", items=keys))
    # MFD bezel faces (bezel box stands MFD_DEPTH proud); OSB buttons are boxes mapped here
    for s in (-1, 1):
        b, it = MFD_BEZEL, []
        for k in range(5):
            o = -4.6 + 2.3 * k
            it += [("button", b / 2 + o, b - 1.15, 1.3, 1.1, ""), ("button", b / 2 + o, 1.15, 1.3, 1.1, ""),
                   ("button", 1.15, b / 2 - o, 1.1, 1.3, ""), ("button", b - 1.15, b / 2 - o, 1.1, 1.3, "")]
        it += [("rocker", 1.2, b - 1.2, 1.0, 1.6, "GAIN"), ("rocker", b - 1.2, b - 1.2, 1.0, 1.6, "SYM"), ("rocker", 1.2, 1.2, 1.0, 1.6, "BRT"),
               ("rocker", b - 1.2, 1.2, 1.0, 1.6, "CON")]
        u0 = s * MFD_U - b / 2
        P.append(dict(name="MFD_%s_BZ" % ("L" if s < 0 else "R"), origin=panel_pt(u0, MFD_V - b / 2, MFD_DEPTH), ex=(0.0, 1.0, 0.0), ey=PANEL_UP,
                      w=b, h=b, ppc=48, raise_=0.0, title="", kind="mfd", items=it, screen=MFD_SCREEN))
    # ICP surround + DED plate
    pp("C_DED", -DED["bw"] / 2 - 1.0, DED["v"] - DED["bh"] / 2, DED["bw"] / 2 + 1.0, DED["v"] + DED["bh"] / 2,
       [("display", DED["bw"] / 2 + 1.0, DED["bh"] / 2, DED["w"], DED["h"], ["UHF 292.30  STPT  8", "   ", "VHF   1    10:42:08", "M1 3  C  6400  MAN T 75X"])], ppc=40)
    # MFD surrounds (plates behind the bezels, sides of the column up to the eyebrows)
    for s in (-1, 1):
        u0, u1 = (-WING_U, -COL_HALF - 0.2) if s < 0 else (COL_HALF + 0.2, WING_U)
        mfd_low = MFD_V - MFD_BEZEL / 2 - WELL_V1
        strip = [("knob", 2.6 + 3.4 * i, mfd_low / 2 + 0.1, 1.6, "") for i in range(int((u1 - u0 - 3.0) / 3.4))]
        pp("MFDS_%s" % ("L" if s < 0 else "R"), u0, WELL_V1, u1, 61.7, strip, ppc=20)
    pp("EB_L", EYEBROW_L["u0"], EYEBROW_L["v0"], EYEBROW_L["u1"], EYEBROW_L["v1"],
       [("lamp", 1.3 + 2.6 * i, 1.8, 2.3, 2.6, c, t) for i, (c, t) in enumerate((("amber", ""), ("amber", "TF\nFAIL"), ("amber", "ENG\nFIRE"), ("amber", "HYD"), ("red", "OXY\nLOW"), ("amber", "ENGINE")))],
       ppc=40)
    pp("EB_R", EYEBROW_R["u0"], EYEBROW_R["v0"], EYEBROW_R["u1"], EYEBROW_R["v1"],
       [("lamp", 1.3 + 2.6 * i, 1.8, 2.3, 2.6, c, t) for i, (c, t) in enumerate((("red", "FLCS"), ("amber", "DBU\nON"), ("amber", "TO/LDG\nCONFIG"), ("amber", "CANOPY"), ("amber", "AR/NWS"), ("red", "")))],
       ppc=40)
    # leg wells either side of the column (set WELL_DEPTH forward), auxiliary panels outboard of them
    for s, nm in ((-1, "LW_L"), (1, "LW_R")):
        u0 = -AUX_U0 + 0.3 if s < 0 else COL_HALF + 0.6
        wl = AUX_U0 - COL_HALF - 0.9
        brk = [("breaker", 2.0 + 1.6 * i, 18.6 - 2.6 * r) for r in range(3) for i in range(int((wl - 3.0) / 1.6))]
        P.append(dict(name=nm, origin=add(panel_pt(u0, 18.0), (WELL_DEPTH, 0, 0)), ex=(0.0, 1.0, 0.0), ey=PANEL_UP, w=wl,
                      h=WELL_V1 - 18.0 - 0.4, ppc=24, raise_=0.3, title="", kind="well",
                      items=brk + [("label", wl / 2, 20.9, "CIRCUIT BREAKERS", 0.5), ("label", wl / 2, 9.0, "DO NOT STEP|ON PANEL", 0.55),
                                   ("toggle", 3.0, 4.0, "LIGHTS"), ("toggle", 7.0, 4.0, "FAN"), ("knob", 11.5, 4.2, 2.2, "TEMP")]))
    # wings
    for s in (-1, 1):
        ex, ey, n = wing_frame(s)
        o = wing_pt(s, 0.0, WING_V0) if s > 0 else wing_pt(s, WING_W, WING_V0)
        exr = ex if s > 0 else tuple(-c for c in ex)          # texture u always runs to the pilot's right
        if s > 0:
            items = [("dial", w, v - WING_V0, d, face) for _n, (w, v, d, face) in WING_GAUGES.items()]
        else:
            items = [("rwr", WING_W - RWR["w"], RWR["v"] - WING_V0, RWR["size"]), ("toggle", 2.4, 3.2), ("toggle", 5.8, 3.2),
                     ("label", 2.4, 1.0, "MASTER ARM", 0.4), ("label", 5.8, 1.0, "LASER", 0.4), ("label", 4.1, 13.6, "THREAT", 0.45)]
        P.append(dict(name="WING_%s" % ("L" if s < 0 else "R"), origin=o, ex=exr, ey=ey, w=WING_W, h=WING_V1 - WING_V0, ppc=40, raise_=0.4,
                      title="", kind="wing", items=items, side=s))
    return P


UF_PODS = {"UF_L": (-15.5, [("amber", "MASTER|CAUTION"), ("amber", "TF FAIL")]), "UF_R": (15.5, [("red", "ENGINE"), ("red", "WARNING")])}


def uf_frame(u):
    """up-front warning light pod on the glare shield lip at lateral u: (centre, ex, ey, n) with n toward the eye"""
    x = panel_x(LIP_ZC) - LIP_OVER + 3.2
    c = (x, u, lip_z(u) + 2.6)
    n = tuple(e - q for e, q in zip(EYE, c))
    l = math.sqrt(sum(v * v for v in n))
    n = tuple(v / l for v in n)
    ex = (n[1], -n[0], 0.0)                                  # n x z, horizontal
    l = math.hypot(ex[0], ex[1])
    ex = (ex[0] / l, ex[1] / l, 0.0)
    if ex[1] < 0:
        ex = (-ex[0], -ex[1], 0.0)
    ey = (ex[1] * n[2] - ex[2] * n[1], ex[2] * n[0] - ex[0] * n[2], ex[0] * n[1] - ex[1] * n[0])
    if ey[2] < 0:
        ey = tuple(-v for v in ey)
    return c, ex, ey, n


def side_plates():
    """small placards on the sloped side walls / sill (generic warning text)"""
    P = []
    for s, x0, name, txt in ((-1, 436.0, "SW_L", "EJECTION CONTROLS|LOCKED BEFORE|GROUND EGRESS"), (1, 470.0, "SW_R", "CANOPY JETTISON|PULL HANDLE|FULL TRAVEL"),
                             (-1, 404.0, "SW_L2", "OXYGEN|CHECK PRESSURE|BEFORE FLIGHT"), (1, 420.0, "SW_R2", "DANGER|EJECTION SEAT|NO STEP")):
        y = s * (CONSOLE_OUT + 3.0)
        P.append(dict(name=name, origin=(x0, y, 47.0), ex=(1.0, 0.0, 0.0) if s < 0 else (-1.0, 0.0, 0.0), ey=(0.0, -s * 0.5, 0.866), w=13.0, h=5.0, ppc=40,
                      raise_=0.15, title="", kind="placard", items=[("label", 6.5, 2.5, txt, 0.62)]))
    w, h = 6.4, 2.9
    for name, (u, cells) in UF_PODS.items():
        c, ex, ey, n = uf_frame(u)
        o = tuple(c[i] - ex[i] * w / 2 - ey[i] * h / 2 for i in range(3))
        P.append(dict(name=name, origin=o, ex=ex, ey=ey, w=w, h=h, ppc=60, raise_=0.0, title="", kind="pod",
                      items=[("lamp", 1.75 + 3.1 * i, 1.45, 3.0, 2.3, col, txt) for i, (col, txt) in enumerate(cells)]))
    return P


def all_plates():
    return panel_plates() + console_plates() + side_plates()


# ---------------------------------------------------------------------------------------------------------------------
# atlas packing (deterministic shelf packing, shared by both scripts)
ATLAS = 4096
KNURL_SW = (0, 3776, 256, 256)               # diamond knurl / grip texture (height -> normal), tiled inside by the model
RUBBER_SW = (272, 3776, 256, 256)            # fine rubber / boot grain
SWATCH = (4096 - 64, 4096 - 64, 64, 64)       # white swatch (x, y, w, h) bottom-right corner, flat normal
STRIPE_SW = (4096 - 192, 4096 - 64, 128, 64)  # yellow / black hazard stripes swatch (ejection loop)


def pack():
    plates = all_plates()
    order = sorted(range(len(plates)), key=lambda i: -plates[i]["h"] * plates[i]["ppc"])
    x = y = shelf = 0
    pad = 8
    for i in order:
        p = plates[i]
        pw, ph = int(math.ceil(p["w"] * p["ppc"])) + 2 * pad, int(math.ceil(p["h"] * p["ppc"])) + 2 * pad
        if x + pw > ATLAS:
            x, y, shelf = 0, y + shelf, 0
        p["px"] = (x + pad, y + pad, pw - 2 * pad, ph - 2 * pad)
        x += pw
        shelf = max(shelf, ph)
    if y + shelf > ATLAS - 80:
        raise RuntimeError("atlas overflow %d" % (y + shelf))
    return plates


def plate_uv(p, a, b):
    """plate cm (a across, b up) -> atlas UV (Blender convention, v up)"""
    x0, y0, w, h = p["px"]
    px = x0 + a / p["w"] * w
    py = y0 + (1.0 - b / p["h"]) * h
    return (px / ATLAS, 1.0 - py / ATLAS)


def swatch_uv(sw=SWATCH):
    return ((sw[0] + sw[2] / 2) / ATLAS, 1.0 - (sw[1] + sw[3] / 2) / ATLAS)


# colours (sRGB 0..255) sampled from the reference photos (003 / 005 / 010, hangar light, approximate)
COL = dict(panel=(84, 88, 90),       # dark gull grey (photo 003 hangar ~#4A4D4A, FS 36231 ~ (96, 96, 94)); review: v2 was near-black
            panel_light=(64, 67, 69), legend=(232, 232, 226), structure=(78, 82, 84), glare=(22, 22, 23),
           well=(70, 73, 75), dial=(16, 16, 17))
