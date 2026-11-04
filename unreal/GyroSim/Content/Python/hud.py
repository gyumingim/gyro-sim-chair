"""Fighter-style HUD and the three cockpit displays, drawn with UCanvas into render targets (sim_client.py puts them on
the world-space HUD plane and the display planes, so they work on the monitor and in VR).

HUD plane geometry (must match Scripts/build_level.py): plane HUD_D cm ahead of the eye, perpendicular to body X,
square, +-HUD_HALF deg around elevation HUD_EL0. A body-frame direction (x fwd, y right, z up) lands on pixel
  px = C + C * (y/x) / tan(HALF),  py = C - C * (z/x - tan(EL0)) / tan(HALF)     (C = RT size / 2)
so the horizon / pitch ladder and the flight path marker are conformal (line up with the outside world) at the eye
point. The ladder is a static atlas (draw_ladder) that the HUD material (build_level.LADDER_HLSL) looks up per pixel
from roll / pitch every frame; this Python canvas only redraws text, tapes and the FPM (HUD_HZ).

Displays (cockpit v2, every element live): MFD_C training (lesson panel picture from the server + live target bars +
30 s deviation trend), MFD_L flight data, MFD_R chair / session / warnings. Beginner mode adds Korean labels: pictures
from the label atlas (Art/Cockpit/tex/T_CkLabels.png, Scripts/cockpit/make_labels.py) because the canvas font has no
Hangul. Render targets have mips (no shimmer at VR distance).
"""
import json, math, os
import unreal

HUD_D, HUD_HALF, HUD_EL0 = 2000.0, 14.0, -6.0
RT_HUD = 1024
DISP = {"MFD_C": (1280, 800), "MFD_L": (1024, 1024), "MFD_R": (1024, 1024)}     # logical drawing size (coordinates below)
DISP_SCALE = 0.75          # physical render target = logical x this (no mips: Canvas does not rebuild them; the display
                           # material supersamples 3 x 3 instead - no shimmer at VR / monitor distance)
LAD_W, LAD_H, LAD_AZ = 1024, 8192, 16.0     # pitch ladder atlas: x = azimuth -16..16 deg, y = elevation +90..-90 deg
GREEN = unreal.LinearColor(0.25, 1.0, 0.35, 1.0)
DIM = unreal.LinearColor(0.12, 0.55, 0.18, 1.0)
AMBER = unreal.LinearColor(1.0, 0.75, 0.15, 1.0)
RED = unreal.LinearColor(1.0, 0.2, 0.15, 1.0)
WHITE = unreal.LinearColor(0.9, 0.95, 1.0, 1.0)
GREY = unreal.LinearColor(0.45, 0.5, 0.55, 1.0)
CYAN = unreal.LinearColor(0.45, 0.8, 1.0, 1.0)
DARK = unreal.LinearColor(0.02, 0.03, 0.035, 1.0)
CLEAR = unreal.LinearColor(0, 0, 0, 0)
ST_COL = (GREEN, AMBER, RED)
V2 = unreal.Vector2D
RL = unreal.RenderingLibrary
_T = math.tan(math.radians(HUD_HALF))
_T0 = math.tan(math.radians(HUD_EL0))
PROJ = unreal.Paths.convert_relative_path_to_full(unreal.Paths.project_dir())
LBL_DIR = os.path.join(PROJ, "Art", "Cockpit", "tex")
WARN_TXT = {"pullup": ("PULL UP", "w_pullup", RED), "terrain": ("TERRAIN", "w_terrain", RED), "overg": ("OVER-G", "w_overg", RED),
            "stall": ("STALL", "w_stall", RED), "gear": ("GEAR", "w_gear", AMBER)}


def level_to_body(v, phi, th):
    """vector in the heading-aligned level frame (x fwd horizontal, y right, z up) -> body frame (x fwd, y right, z up)."""
    x, y, z = v
    ct, st, cp, sp = math.cos(th), math.sin(th), math.cos(phi), math.sin(phi)
    x1, z1 = x * ct + z * st, -x * st + z * ct
    return x1, y * cp - z1 * sp, y * sp + z1 * cp


def _rt(world, w, h, clear):
    return RL.create_render_target2d(world, int(w * DISP_SCALE), int(h * DISP_SCALE), unreal.TextureRenderTargetFormat.RTF_RGBA8, clear)


class Painter:
    def __init__(self, world):
        self.world = world
        self.font = unreal.load_asset("/Engine/EngineFonts/RobotoDistanceField")
        self.rt_hud = RL.create_render_target2d(world, RT_HUD, RT_HUD, unreal.TextureRenderTargetFormat.RTF_RGBA8, CLEAR)
        self.rt_disp = {k: _rt(world, w, h, unreal.LinearColor(0, 0, 0, 1)) for k, (w, h) in DISP.items()}
        self.rt_ladder = RL.create_render_target2d(world, LAD_W, LAD_H, unreal.TextureRenderTargetFormat.RTF_RGBA8, CLEAR)
        self.c = None
        self.ts = 1.0
        self.k = 1.0                         # logical -> physical pixel scale of the current target
        self.white = unreal.load_asset("/Engine/EngineResources/WhiteSquareTexture")
        self.lbl, self.lbl_rects, self.lbl_size = None, {}, (1, 1)
        try:
            j = json.load(open(os.path.join(LBL_DIR, "labels.json"), encoding="utf-8"))
            self.lbl_rects, self.lbl_size = j["rects"], tuple(j["size"])
            self.lbl = RL.import_file_as_texture2d(world, os.path.join(LBL_DIR, "T_CkLabels.png"))
        except Exception as e:
            unreal.log("[hud] label atlas missing: %r" % (e,))
        self.draw_ladder()
        self.hist = []                       # (t, dev / tol) of the first training target, ~5 Hz, last 30 s
        self.last = {}                       # last values drawn per display (verify)

    # ---- primitives -------------------------------------------------------------------------------------------------
    def _begin(self, rt, clear):
        RL.clear_render_target2d(self.world, rt, clear)
        self.c, _size, self.ctx = RL.begin_draw_canvas_to_render_target(self.world, rt)

    def _end(self):
        RL.end_draw_canvas_to_render_target(self.world, self.ctx)
        self.c = None

    def line(self, a, b, col=GREEN, w=4.0):
        k = self.k
        self.c.draw_line(V2(a[0] * k, a[1] * k), V2(b[0] * k, b[1] * k), max(1.0, w * k), col)

    def text(self, s, x, y, size=1.0, col=GREEN, center=True, vcenter=True):
        k = size * self.ts * self.k
        self.c.draw_text(self.font, s, V2(x * self.k, y * self.k), V2(k, k), col, 0.0, CLEAR, V2(0, 0), center, vcenter, False, col)

    def box(self, x, y, w, h, col=GREEN, t=3.5):
        k = self.k
        self.c.draw_box(V2(x * k, y * k), V2(w * k, h * k), max(1.0, t * k), col)

    def fill(self, x, y, w, h, col):
        if w > 0 and h > 0:
            k = self.k
            self.c.draw_texture(self.white, V2(x * k, y * k), V2(w * k, h * k), V2(0, 0), V2(1, 1), col, unreal.BlendMode.BLEND_TRANSLUCENT, 0.0, V2(0, 0))

    def circle(self, x, y, r, col=GREEN, n=16, w=4.0):
        p = [(x + r * math.cos(2 * math.pi * i / n), y + r * math.sin(2 * math.pi * i / n)) for i in range(n + 1)]
        for i in range(n):
            self.line(p[i], p[i + 1], col, w)

    def label(self, key, x, y, h, col=WHITE, anchor="l"):
        """Korean label picture from the atlas, height h px; anchor l / c / r at (x, y = vertical centre). Returns width."""
        r = self.lbl_rects.get(key)
        if not r or self.lbl is None:
            return 0
        W, H = self.lbl_size
        w = r[2] * h / r[3]
        x0 = x if anchor == "l" else x - w / 2 if anchor == "c" else x - w
        k = self.k
        if self.c is not None and self.k == 1.0:                 # HUD: keep callouts inside the HUD picture
            x0 = max(4.0, min(RT_HUD - 4.0 - w, x0))
        self.c.draw_texture(self.lbl, V2(x0 * k, (y - h / 2) * k), V2(w * k, h * k), V2(r[0] / W, r[1] / H), V2(r[2] / W, r[3] / H), col,
                            unreal.BlendMode.BLEND_TRANSLUCENT, 0.0, V2(0, 0))
        return w

    def image(self, tex, x, y, w, h, col=WHITE):
        if tex is not None:
            k = self.k
            self.c.draw_texture(tex, V2(x * k, y * k), V2(w * k, h * k), V2(0, 0), V2(1, 1), col, unreal.BlendMode.BLEND_TRANSLUCENT, 0.0, V2(0, 0))

    @staticmethod
    def proj(v):
        """body direction -> HUD pixel, None if behind."""
        x, y, z = v
        if x <= 1e-3:
            return None
        C = RT_HUD / 2
        return C + C * (y / x) / _T, C - C * (z / x - _T0) / _T

    # ---- pitch ladder atlas (drawn once; the HUD material looks it up from roll / pitch) ----------------------------
    def draw_ladder(self):
        self._begin(self.rt_ladder, CLEAR)
        self.ts = 1.6
        self.k = 1.0
        X = lambda az: (az + LAD_AZ) / (2 * LAD_AZ) * LAD_W
        Y = lambda el: (90.0 - el) / 180.0 * LAD_H
        try:
            for pd in range(-90, 91, 5):
                y = Y(pd)
                segs = [(-14.0, -1.6), (1.6, 14.0)] if pd == 0 else [(-5.2, -1.6), (1.6, 5.2)]
                for a0, a1 in segs:
                    x0, x1 = X(a0), X(a1)
                    if pd < 0:
                        for k in range(4):
                            u0, u1 = k / 4.0, k / 4.0 + 0.16
                            self.line((x0 + (x1 - x0) * u0, y), (x0 + (x1 - x0) * u1, y), GREEN, 5.0)
                    else:
                        self.line((x0, y), (x1, y), GREEN, 5.0)
                    if pd != 0:
                        xo = x0 if a0 < -2 else x1
                        self.line((xo, y), (xo, y + (32 if pd > 0 else -32)), GREEN, 5.0)    # tick toward the horizon
                        self.text("%d" % abs(pd), X((a0 - 1.4) if a0 < -2 else (a1 + 1.4)), y, 0.75)
        finally:
            self._end()

    # ---- HUD --------------------------------------------------------------------------------------------------------
    def draw_hud(self, s, extra):
        """s = sim packet, extra = dict(radar_m, warn, line_tex, note, beginner)."""
        self._begin(self.rt_hud, CLEAR)
        self.ts = 1.6
        self.k = 1.0
        try:
            self._hud(s, extra)
        finally:
            self._end()

    def _hud(self, s, ex):
        C = RT_HUD / 2
        beg = ex.get("beginner")
        lc = unreal.LinearColor(0.5, 1.0, 0.6, 1.0)
        lh = 34
        # boresight (gun cross) at body X
        b = self.proj((1, 0, 0))
        self.line((b[0] - 22, b[1]), (b[0] - 8, b[1]))
        self.line((b[0] + 8, b[1]), (b[0] + 22, b[1]))
        self.line((b[0], b[1] - 14), (b[0], b[1] - 4))
        # flight path marker (alpha / beta)
        al, be = math.radians(s.get("alpha", 0.0)), math.radians(s.get("beta", 0.0))
        f = self.proj((math.cos(al) * math.cos(be), math.sin(be), -math.sin(al) * math.cos(be)))
        if f:
            fx, fy = max(40, min(RT_HUD - 40, f[0])), max(40, min(RT_HUD - 40, f[1]))
            self.circle(fx, fy, 11)
            self.line((fx - 28, fy), (fx - 11, fy))
            self.line((fx + 11, fy), (fx + 28, fy))
            self.line((fx, fy - 11), (fx, fy - 24))
            if beg:
                self.label("hud_fpm", fx + 36, fy + 26, lh * 0.85, lc)
        if beg:
            self.label("hud_bore", b[0] + 30, b[1] - 18, lh * 0.85, lc)
            self.label("hud_ladder", C + 150, 150, lh * 0.85, lc)
        # heading tape (bottom)
        hdg = s["psi"] % 360
        y0, px_deg = 860, 13.0
        self.line((C, y0 - 30), (C - 9, y0 - 44))
        self.line((C, y0 - 30), (C + 9, y0 - 44))
        for d in range(int(hdg) - 20, int(hdg) + 21):
            if d % 5:
                continue
            x = C + (d - hdg) * px_deg
            if abs(x - C) > 250:
                continue
            self.line((x, y0 - 22), (x, y0 - (8 if d % 10 else 0)), GREEN, 2.5)
            if d % 10 == 0:
                self.text("%02d" % ((d % 360) // 10), x, y0 + 22, 0.75)
        self.box(C - 50, y0 + 44, 100, 50)
        self.text("%03.0f" % hdg, C, y0 + 69, 0.95)
        if beg:
            self.label("hud_hdg", C + 62, y0 + 69, lh, lc)
        # airspeed (left) / altitude (right) boxes
        ya, xl, xr = 470, 262, 762                  # boxes ~ +-7 deg from the centre
        self.box(xl - 85, ya - 32, 170, 64)
        self.text("%3.0f" % s["kts"], xl, ya, 1.3)
        self.text("M %.2f" % s.get("mach", 0.0), xl, ya + 64, 0.9)
        g = s.get("nz", 1.0)
        self.text("G %.1f" % g, xl, ya - 66, 0.9, AMBER if g > 7.0 or g < -1.5 else GREEN)
        aoa = s.get("alpha", 0.0)
        self.text("AOA %.1f" % aoa if s["kts"] > 40 else "AOA --", xl, ya + 112, 0.8, AMBER if aoa > 15 and s["kts"] > 40 else GREEN)
        alt = s["alt_m"] / 0.3048
        self.box(xr - 100, ya - 32, 200, 64)
        self.text("{:,.0f}".format(alt), xr, ya, 1.3)
        vs = s.get("vs_fpm", 0.0)
        self.text("%+5.0f" % vs, xr, ya - 66, 0.9)
        r = ex.get("radar_m")
        if r is not None:
            self.text("R {:,.0f}".format(r / 0.3048), xr, ya + 64, 0.9, AMBER if r < 150 and vs < -500 else GREEN)
        if beg:                                      # callouts outside the boxes (left of speed, right of altitude)
            self.label("hud_spd", xl - 92, ya, lh, lc, "r")
            self.label("hud_mach", xl - 92, ya + 64, lh * 0.85, lc, "r")
            self.label("hud_g", xl - 92, ya - 66, lh * 0.85, lc, "r")
            self.label("hud_aoa", xl - 92, ya + 112, lh * 0.85, lc, "r")
            self.label("hud_alt", xr + 108, ya, lh, lc)
            self.label("hud_vs", xr + 108, ya - 66, lh * 0.85, lc)
            self.label("hud_agl", xr + 108, ya + 64, lh * 0.85, lc)
        if s.get("brk", 0.0) > 0.3:
            self.text("BRAKE", xr, 650, 0.8, AMBER)
        if s.get("paused") and not ex.get("menu"):
            self.text("PAUSED", C, 300, 1.2, AMBER)
        w = ex.get("warn")
        if w:
            self.text(w, C, 360, 1.4, RED)
        # instructor line (Korean picture from the server, green on black = transparent here)
        lt = ex.get("line_tex")
        if lt is not None and ex.get("line_on"):
            self.image(lt, C - 400, 735, 800, 56)
        note = ex.get("note")
        if note:
            self.text(note, C, 120, 0.6, AMBER)

    # ---- displays ---------------------------------------------------------------------------------------------------
    def draw_display(self, tag, s, ex):
        self._begin(self.rt_disp[tag], unreal.LinearColor(0.004, 0.008, 0.01, 1.0))
        self.ts = 1.0
        self.k = DISP_SCALE
        try:
            {"MFD_C": self._train, "MFD_L": self._pfd, "MFD_R": self._session}[tag](s, ex)
        finally:
            self._end()

    def _title(self, en, ko_t, ko_d, ex, W):
        if ex.get("beginner"):
            self.label(ko_t, 28, 56, 50, CYAN)          # 20 px lower than before: the bezel covered the top (review)
            self.label(ko_d, 28, 100, 32, GREY)
            return 124
        self.text(en, 28, 54, 1.8, CYAN, center=False)
        return 88

    def _tile(self, x, y, w, h, en, ko, val, col, unit, size, ex):
        """framed value tile: small label top-left (Korean in beginner mode), big value centred, unit bottom-right."""
        self.box(x, y, w, h, unreal.LinearColor(0.12, 0.16, 0.2, 1.0), 2)
        if ex.get("beginner"):
            self.label(ko, x + 14, y + 24, 34, GREY)
        else:
            self.text(en, x + 14, y + 24, 1.25, GREY, center=False)
        self.text(val, x + w / 2, y + h / 2 + 14, size, col)
        if unit:
            self.text(unit, x + w - 50, y + h - 22, 1.1, GREY)

    def _pfd(self, s, ex):
        """flight data: big tiles, colours = normal (green) / caution (amber) / danger (red)."""
        y = self._title("FLIGHT DATA", "pfd_t", "pfd_d", ex, 1024)
        ft, kts, vs = s["alt_m"] / 0.3048, s["kts"], s.get("vs_fpm", 0.0)
        air = not s.get("wow")
        aoa, g = s.get("alpha", 0.0), s.get("nz", 1.0)
        spd_c = RED if (air and (aoa > 25 or kts < 120)) else AMBER if (air and kts < 160 and s.get("gear", 0) < 0.5) or kts > 650 else GREEN
        W2 = 488
        self._tile(16, y, W2, 230, "SPD", "r_spd", "%3.0f" % kts, spd_c, "KT", 4.4, ex)
        self._tile(520, y, W2, 230, "ALT", "r_alt", "{:,.0f}".format(ft), GREEN, "FT", 4.0, ex)
        y += 246
        vs_c = AMBER if abs(vs) > 4000 else GREEN
        self._tile(16, y, W2, 180, "VS", "r_vs", ("%+.0f" % vs) if abs(vs) >= 50 else "0", vs_c, "FPM", 3.2, ex)
        self._tile(520, y, W2, 180, "HDG", "r_hdg", "%03.0f" % (s["psi"] % 360), GREEN, "DEG", 3.2, ex)
        y += 196
        r = ex.get("radar_m")
        rr = (r / 0.3048) if r is not None else None
        if ex.get("beginner") and (rr is None or rr >= 5000):       # beginner: height above the ground instead of Mach
            self._tile(16, y, W2, 150, "AGL  R", "r_agl", "", GREEN, "", 2.8, ex)
            self.label("v_high", 16 + W2 / 2, y + 88, 52, GREEN, "c")
        elif rr is not None and rr < 5000:
            self._tile(16, y, W2, 150, "AGL  R", "r_agl", "{:,.0f}".format(rr), RED if (rr < 500 and vs < -1500 and air) else AMBER if (rr < 1000 and air) else GREEN,
                       "FT", 2.8, ex)
        else:
            self._tile(16, y, W2, 150, "MACH", "r_mach", "%.2f" % s.get("mach", 0.0), GREEN, "", 2.8, ex)
        gm = ex.get("gmax", 1.0)
        gcol = RED if g > 9 or g < -3 else AMBER if g > 7 else GREEN
        self._tile(520, y, W2, 150, "G  (MAX %.1f)" % gm, "r_g", "%.1f" % g, gcol, "", 2.8, ex)
        if ex.get("beginner"):
            self.text("MAX %.1f" % gm, 520 + W2 - 90, y + 24, 1.2, RED if gm > 9 else AMBER if gm > 7 else GREY)
        y += 166
        thr = s.get("thr", 0.0)
        if ex.get("beginner"):
            self.label("r_thr", 24, y + 20, 34, GREY)
        else:
            self.text("THR", 24, y + 20, 1.3, GREY, center=False)
        self.box(200, y + 2, 560, 38, GREY, 2)
        self.fill(202, y + 4, 556 * max(0.0, min(1.0, thr)), 34, AMBER if thr > 0.95 else GREEN)
        self.text("%3.0f%%%s" % (thr * 100, " AB" if thr > 0.95 else ""), 890, y + 21, 2.0, AMBER if thr > 0.95 else GREEN)
        y += 64
        gear = s.get("gear", 0.0)
        gtxt, gcol = ("DOWN", GREEN) if gear > 0.95 else ("UP", WHITE) if gear < 0.05 else ("TRANSIT", AMBER)
        aoa_c = RED if aoa > 25 and air else AMBER if aoa > 15 and air else GREEN
        if ex.get("beginner"):
            self.label("r_gear", 24, y + 20, 34, GREY)
            self.label("r_aoa", 360, y + 20, 34, GREY)
            self.label("r_brk", 700, y + 20, 34, GREY)
        else:
            for xx, t in ((24, "GEAR"), (360, "AOA"), (700, "BRAKE")):
                self.text(t, xx, y + 20, 1.3, GREY, center=False)
        if ex.get("beginner"):
            self.label({"DOWN": "v_down", "UP": "v_up"}.get(gtxt, "v_transit"), 150, y + 22, 44, gcol)
        else:
            self.text(gtxt, 250, y + 22, 2.0, gcol)
        self.text(("%.1f" % aoa) if kts > 40 else "--", 640 if ex.get("beginner") else 590, y + 22, 2.0, aoa_c)
        bk = s.get("brk", 0.0) > 0.3
        if ex.get("beginner"):
            self.label("v_on" if bk else "v_off", 880, y + 22, 44, AMBER if bk else GREY)
        else:
            self.text("ON" if bk else "OFF", 930, y + 22, 2.0, AMBER if bk else GREY)
        self.last["MFD_L"] = dict(kts=round(kts), ft=round(ft), vs=round(vs), thr=round(thr * 100), gear=gtxt, g=round(g, 1), gmax=round(gm, 1))

    def _train(self, s, ex):
        """training display: the server's lesson picture (Korean) + live target bars and the deviation trend."""
        W, H = DISP["MFD_C"]
        tut = s.get("tut") or {}
        tex = ex.get("panel_tex")
        self.image(tex, 0, 0, W, H)
        if tex is None:
            self.text("TRAINING - waiting for sim/server.py", W / 2, H / 2, 1.6, AMBER)
        ph = tut.get("phase")
        tg = tut.get("targets") or []
        self.last["MFD_C"] = dict(phase=ph, targets=[(t.get("name"), t.get("txt"), t.get("st")) for t in tg])
        if ph not in ("practice", "solo") or not tg:
            return
        # band y 470..680 (render.py keeps it free in practice / solo): up to 3 rows + the trend on the right
        y0, rh = 482, 62
        self.fill(14, y0 - 30, W - 28, rh * min(3, len(tg)) + 14, unreal.LinearColor(0.0, 0.02, 0.03, 0.85))
        for i, t in enumerate(tg[:3]):
            y = y0 + i * rh
            col = ST_COL[min(2, max(0, int(t.get("st", 0))))]
            if ex.get("beginner"):
                self.label("t_" + t["name"], 30, y, 36, WHITE)
            else:
                self.text(t["name"], 30, y, 1.3, WHITE, center=False)
            self.text("%s" % t.get("txt", ""), 330, y, 2.5, col)
            self.text("%s ±%g %s" % (t.get("ttxt", ""), t.get("tol", 0), t.get("unit", "")), 565, y, 1.25, GREY)
            # deviation bar: centre = target, green band = tolerance, marker = now
            bx, bw = 700, 300
            tol = max(1e-6, float(t.get("tol", 1)))
            k = bw / 2 / (3 * tol)
            self.box(bx, y - 12, bw, 24, GREY, 2)
            self.fill(bx + bw / 2 - tol * k, y - 10, 2 * tol * k, 20, unreal.LinearColor(0.05, 0.3, 0.12, 1.0))
            d = max(-3 * tol, min(3 * tol, float(t.get("dev", 0))))
            mx = bx + bw / 2 + d * k
            self.fill(mx - 5, y - 16, 10, 32, col)
        # trend of the first target over the last 30 s (deviation / tolerance)
        t0 = tut.get("t", 0.0) or 0.0
        if tg:
            v = float(tg[0].get("dev", 0)) / max(1e-6, float(tg[0].get("tol", 1)))
            if not self.hist or t0 - self.hist[-1][0] >= 0.2 or t0 < self.hist[-1][0]:
                if self.hist and t0 < self.hist[-1][0]:
                    self.hist = []
                self.hist.append((t0, v))
            self.hist = [p for p in self.hist if t0 - p[0] <= 30.0]
        gx, gy, gw, gh = 1030, y0 - 24, 230, rh * min(3, len(tg)) - 4
        self.box(gx, gy, gw, gh, GREY, 2)
        mid = gy + gh / 2
        self.fill(gx + 2, mid - gh / 6, gw - 4, gh / 3, unreal.LinearColor(0.05, 0.3, 0.12, 1.0))
        pts = [(gx + gw - (t0 - t) / 30.0 * gw, mid - max(-3.0, min(3.0, v)) / 3.0 * gh / 2) for t, v in self.hist]
        for a, b in zip(pts, pts[1:]):
            self.line(a, b, AMBER, 3)
        if ex.get("beginner"):
            self.label("r_trend", gx, gy - 14, 24, GREY)

    def _session(self, s, ex):
        """chair cue vs its limits, flight time, status, warnings (master caution logic)."""
        y = self._title("CHAIR / STATUS", "ses_t", "ses_d", ex, 1024)
        t = s.get("t", 0.0)
        beg = ex.get("beginner")
        self._tile(16, y, 480, 130, "FLT TIME", "r_time", "%d:%02d" % (int(t) // 60, int(t) % 60), WHITE, "", 3.0, ex)
        # status chips (right of the time)
        chips = []
        if s.get("paused") and not (s.get("tut") or {}).get("menu"):
            chips.append(("PAUSED", "s_paused", AMBER))
        if ex.get("loading"):
            chips.append(("LOADING", "s_loading", AMBER))
        if s.get("demo"):
            chips.append(("DEMO", "s_demo", CYAN))
        if s.get("assist"):
            chips.append(("ASSIST", "s_assist", GREEN))
        if s.get("slow"):
            chips.append(("SLOW 0.5x", "s_slow", GREEN))
        cy = y + 22
        for en, ko, col in chips[:3]:
            if beg:
                self.label(ko, 520, cy, 34, col)
            else:
                self.text(en, 520, cy, 1.4, col, center=False)
            cy += 42
        y += 146
        lim = s.get("chair_lim") or (18.0, 14.0)
        rate = s.get("chair_rate") or (1.3, 0.95)
        tgt = s.get("chair_tgt") or (0.0, 0.0)
        for en, ko, val, tv, L, rt in (("CHAIR ROLL", "r_croll", s.get("chair_roll", 0.0), tgt[0], lim[0], rate[0]),
                                       ("CHAIR PITCH", "r_cpitch", s.get("chair_pitch", 0.0), tgt[1], lim[1], rate[1])):
            self.box(16, y, 992, 150, unreal.LinearColor(0.12, 0.16, 0.2, 1.0), 2)
            if beg:
                self.label(ko, 30, y + 26, 36, GREY)
            else:
                self.text(en, 30, y + 26, 1.3, GREY, center=False)
            near = abs(val) > 0.9 * L
            self.text("%+.1f" % val, 880, y + 34, 2.6, AMBER if near else GREEN)
            bx, bw, by = 40, 940, y + 92
            self.box(bx, by - 16, bw, 32, GREY, 2)
            k = bw / 2 / L
            self.fill(bx + bw / 2 - 2, by - 16, 4, 32, GREY)
            self.fill(bx + bw / 2 + max(-L, min(L, val)) * k - 8, by - 22, 16, 44, AMBER if near else GREEN)
            self.fill(bx + bw / 2 + max(-L, min(L, tv)) * k - 2, by - 26, 4, 52, CYAN)
            self.text("-%g" % L, bx + 26, by + 34, 1.0, GREY)
            self.text("+%g" % L, bx + bw - 26, by + 34, 1.0, GREY)
            if beg:
                w = self.label("r_rate", bx + bw / 2 - 40, by + 34, 26, GREY, "c")
                self.text("%g" % rt, bx + bw / 2 - 40 + w / 2 + 34, by + 34, 1.0, GREY)
            else:
                self.text("max %g deg/s" % rt, bx + bw / 2, by + 34, 1.0, GREY)
            y += 166
        # warnings
        act = ex.get("warnings") or []
        if beg:
            self.label("r_warn", 24, y + 20, 40, WHITE)
        else:
            self.text("WARNINGS", 24, y + 20, 1.5, WHITE, center=False)
        y += 50
        for key, (en, ko, col) in WARN_TXT.items():
            on = key in act
            c = col if on else unreal.LinearColor(0.16, 0.18, 0.2, 1.0)
            if on:
                self.fill(16, y - 4, 992, 54, unreal.LinearColor(col.r * 0.3, col.g * 0.3, col.b * 0.3, 1.0))
            if beg:
                self.label(ko, 30, y + 23, 36, c)
            else:
                self.text(en, 30, y + 23, 1.7, c, center=False)
            y += 58
        self.last["MFD_R"] = dict(warnings=list(act), chair=[round(s.get("chair_roll", 0.0), 1), round(s.get("chair_pitch", 0.0), 1)])
