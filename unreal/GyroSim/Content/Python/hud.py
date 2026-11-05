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
# readability pass (11-05, user: "values are clear but hard to read"): one small type scale per surface, sized for the
# headset (side displays ~11 deg wide, ~90 logical px / deg; HUD 36.6 px / deg). Canvas number size 1.0 ~ 15.7 px cap
# height; Korean label pictures: glyph ~ 0.58 x the label height.
BOLD = os.environ.get("GYROSIM_NO_BOLD") != "1"     # A/B switch for the frame-time check only
HUD_PLATE = 0.12                 # grey of the backing plates behind HUD text (M_HUD maps it to "dark, no light": build_level.HUD_PLATE)
PLATE = unreal.LinearColor(HUD_PLATE, HUD_PLATE, HUD_PLATE, 1.0)
HUD_BIG, HUD_NUM = 1.5, 1.15     # HUD numbers (x ts 1.6): speed / altitude boxes, other values (was 1.3 / 0.8-0.9)
HUD_LBL = 44                     # HUD Korean labels (was 34; symbology callouts 0.85 x)
D_TITLE, D_LBL, D_VAL, D_SUB = 84, 72, 5.6, 2.4    # displays: title / row label height (px), big value / small value size
LBL_COL = unreal.LinearColor(0.72, 0.78, 0.84, 1.0)    # row labels (was GREY 0.45 - too dim)
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

    def text(self, s, x, y, size=1.0, col=GREEN, center=True, vcenter=True, plate=False):
        k = size * self.ts * self.k
        if plate:
            w, h = self.tsize(s, size)
            x0 = x - w / 2 if center else x
            self.fill(x0 - 8, y - h * 0.5 - 4 if vcenter else y - 4, w + 16, h + 8, PLATE)
        # outlined in its own colour = a bolder stroke (the canvas distance-field font is thin)
        self.c.draw_text(self.font, s, V2(x * self.k, y * self.k), V2(k, k), col, 0.0, CLEAR, V2(0, 0), center, vcenter, BOLD, col)

    def tsize(self, s, size):
        """text extent in logical px."""
        k = size * self.ts * self.k
        try:
            v = self.c.k2_text_size(self.font, s, V2(k, k))
            return v.x / self.k, v.y / self.k
        except Exception:
            return len(s) * 9.0 * size * self.ts, 16.0 * size * self.ts

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

    def label(self, key, x, y, h, col=WHITE, anchor="l", plate=False):
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
        if plate:
            self.fill(x0, y - h * 0.4, w, h * 0.8, PLATE)
        self.c.draw_texture(self.lbl, V2(x0 * k, (y - h / 2) * k), V2(w * k, h * k), V2(r[0] / W, r[1] / H), V2(r[2] / W, r[3] / H), col,
                            unreal.BlendMode.BLEND_TRANSLUCENT, 0.0, V2(0, 0))
        return w

    def image(self, tex, x, y, w, h, col=WHITE, additive=False):
        if tex is not None:
            k = self.k
            self.c.draw_texture(tex, V2(x * k, y * k), V2(w * k, h * k), V2(0, 0), V2(1, 1), col,
                                unreal.BlendMode.BLEND_ADDITIVE if additive else unreal.BlendMode.BLEND_TRANSLUCENT, 0.0, V2(0, 0))

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
        lh = HUD_LBL
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
                self.label("hud_fpm", fx, fy + 44, lh * 0.85, lc, "c", plate=True)     # below the marker (right of it hit the VS column)
        if beg and not (f and math.hypot(f[0] - b[0], f[1] - b[1]) < 90):    # skip when the marker sits on the boresight (labels collided)
            self.label("hud_bore", b[0] + 30, b[1] - 22, lh * 0.85, lc, plate=True)
            self.label("hud_ladder", C + 150, 150, lh * 0.85, lc, plate=True)
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
                self.text("%02d" % ((d % 360) // 10), x, y0 + 22, 0.85)
        self.fill(C - 50, y0 + 44, 100, 54, PLATE)
        self.box(C - 50, y0 + 44, 100, 54)
        self.text("%03.0f" % hdg, C, y0 + 71, HUD_NUM)
        if beg:
            self.label("hud_hdg", C + 60, y0 + 71, lh, lc, plate=True)
        # airspeed (left) / altitude (right) boxes, ~ +-7 deg from the centre
        ya, xl, xr = 470, 262, 762
        kts, alt, vs, g = s["kts"], s["alt_m"] / 0.3048, s.get("vs_fpm", 0.0), s.get("nz", 1.0)
        aoa = s.get("alpha", 0.0)
        r = ex.get("radar_m")
        gcol = AMBER if g > 7.0 or g < -1.5 else GREEN
        rcol = AMBER if (r is not None and r < 150 and vs < -500) else GREEN
        for x, wb, v in ((xl, 170, "%3.0f" % kts), (xr, 210, "{:,.0f}".format(alt))):
            self.fill(x - wb / 2, ya - 34, wb, 68, PLATE)
            self.box(x - wb / 2, ya - 34, wb, 68)
            self.text(v, x, ya, HUD_BIG)
        if beg:
            # beginner: each value with its Korean name right above it (stacked in the column - side-by-side names did
            # not fit at a readable size); Mach and AOA left out (instructor never uses them)
            self.label("hud_spd", xl, ya - 62, lh, lc, "c", plate=True)
            self.label("hud_g", xl, ya + 62, lh, lc, "c", plate=True)
            self.text("%.1f" % g, xl, ya + 102, HUD_NUM, gcol, plate=True)
            self.label("hud_vs", xr, ya - 148, lh, lc, "c", plate=True)
            self.text("%+.0f" % vs if abs(vs) >= 50 else "0", xr, ya - 108, HUD_NUM, plate=True)
            self.label("hud_alt", xr, ya - 62, lh, lc, "c", plate=True)
            if r is not None:
                self.label("hud_agl", xr, ya + 62, lh, lc, "c", plate=True)
                self.text("{:,.0f}".format(r / 0.3048), xr, ya + 102, HUD_NUM, rcol, plate=True)
        else:
            self.text("G %.1f" % g, xl, ya - 70, HUD_NUM, gcol, plate=True)
            self.text("M %.2f" % s.get("mach", 0.0), xl, ya + 70, HUD_NUM, plate=True)
            self.text("AOA %.1f" % aoa if kts > 40 else "AOA --", xl, ya + 116, HUD_NUM, AMBER if aoa > 15 and kts > 40 else GREEN, plate=True)
            self.text("%+5.0f" % vs, xr, ya - 70, HUD_NUM, plate=True)
            if r is not None:
                self.text("R {:,.0f}".format(r / 0.3048), xr, ya + 70, HUD_NUM, rcol, plate=True)
        if s.get("brk", 0.0) > 0.3:
            self.text("BRAKE", xr, 652, HUD_NUM, AMBER, plate=True)
        if s.get("paused") and not ex.get("menu"):
            self.text("PAUSED", C, 170, 1.4, AMBER, plate=True)
        w = ex.get("warn")
        if w:
            self.text(w, C, 222, 1.6, RED, plate=True)          # above the value columns
            wk = ex.get("warn_key")
            if beg and wk:                           # beginner: the short Korean line too (the side display is small in VR)
                self.label("wd_" + wk, C, 272, lh, WHITE, "c", plate=True)
        # instructor line (Korean picture from the server, green on black, cropped to the text, 1-2 lines): drawn 1:1
        # on a dark plate, bottom at the heading caret
        lt = ex.get("line_tex")
        if lt is not None and ex.get("line_on"):
            try:
                iw, ih = float(lt.blueprint_get_size_x()), float(lt.blueprint_get_size_y())
            except Exception:
                iw, ih = 800.0, 56.0
            if iw > 8:
                sc = min(1.0, 1000.0 / iw)
                w2, h2 = iw * sc, ih * sc
                x0, y1 = C - w2 / 2, 812
                self.fill(x0, y1 - h2, w2, h2, PLATE)
                self.image(lt, x0, y1 - h2, w2, h2, additive=True)
        note = ex.get("note")
        if note:
            self.text(note, C, 120, 0.8, AMBER, plate=True)

    # ---- displays ---------------------------------------------------------------------------------------------------
    def draw_display(self, tag, s, ex):
        self._begin(self.rt_disp[tag], unreal.LinearColor(0.004, 0.008, 0.01, 1.0))
        self.ts = 1.0
        self.k = DISP_SCALE
        try:
            {"MFD_C": self._train, "MFD_L": self._pfd, "MFD_R": self._session}[tag](s, ex)
        finally:
            self._end()

    def _title(self, en, ko_t, ex):
        """display title (one line; the old grey explanation line under it is gone - unreadable and rarely needed)."""
        if ex.get("beginner"):
            self.label(ko_t, 24, 72, D_TITLE, CYAN)       # the bezel covers the top ~40 px
        else:
            self.text(en, 28, 72, 2.6, CYAN, center=False)
        return 126

    def _name(self, en, ko, x, y, ex, col=None, anchor="l"):
        """row name: Korean picture (beginner) or English text, same visual size."""
        col = col or LBL_COL
        if ex.get("beginner"):
            return self.label(ko, x, y, D_LBL, col, anchor)
        self.text(en, x, y, D_SUB, col, center=anchor == "c")
        return self.tsize(en, D_SUB)[0]

    def _tile(self, x, y, w, h, en, ko, val, col, ex, size=D_VAL):
        """framed value tile: name (with unit) on top, big value below."""
        self.box(x, y, w, h, unreal.LinearColor(0.16, 0.2, 0.25, 1.0), 2)
        self._name(en, ko, x + 18, y + 40, ex)
        if val:
            self.text(val, x + w / 2, y + 40 + (h - 40) / 2 + 4, size, col)

    def _pfd(self, s, ex):
        """flight data: six big tiles + throttle and gear rows; colours = normal (green) / caution (amber) / danger (red)."""
        y = self._title("FLIGHT DATA", "pfd_t", ex)
        ft, kts, vs = s["alt_m"] / 0.3048, s["kts"], s.get("vs_fpm", 0.0)
        air = not s.get("wow")
        aoa, g = s.get("alpha", 0.0), s.get("nz", 1.0)
        spd_c = RED if (air and (aoa > 25 or kts < 120)) else AMBER if (air and kts < 160 and s.get("gear", 0) < 0.5) or kts > 650 else GREEN
        W2, TH = 492, 214
        X1, X2 = 12, 520
        self._tile(X1, y, W2, TH, "SPEED KT", "d_spd", "%3.0f" % kts, spd_c, ex)
        self._tile(X2, y, W2, TH, "ALT FT", "d_alt", "{:,.0f}".format(ft), GREEN, ex)
        y += TH + 10
        vs_c = AMBER if abs(vs) > 4000 else GREEN
        self._tile(X1, y, W2, TH, "VS FPM", "d_vs", ("%+.0f" % vs) if abs(vs) >= 50 else "0", vs_c, ex)
        self._tile(X2, y, W2, TH, "HDG", "d_hdg", "%03.0f" % (s["psi"] % 360), GREEN, ex)
        y += TH + 10
        r = ex.get("radar_m")
        rr = (r / 0.3048) if r is not None else None
        if rr is None or rr >= 5000:
            self._tile(X1, y, W2, TH, "AGL FT", "d_agl", "", GREEN, ex)
            if ex.get("beginner"):
                self.label("v_high", X1 + W2 / 2, y + 40 + (TH - 40) / 2 + 4, D_LBL, GREEN, "c")
            else:
                self.text("> 5,000", X1 + W2 / 2, y + 40 + (TH - 40) / 2 + 4, 4.0, GREEN)
        else:
            self._tile(X1, y, W2, TH, "AGL FT", "d_agl", "{:,.0f}".format(rr),
                       RED if (rr < 500 and vs < -1500 and air) else AMBER if (rr < 1000 and air) else GREEN, ex)
        gm = ex.get("gmax", 1.0)
        gcol = RED if g > 9 or g < -3 else AMBER if g > 7 else GREEN
        self._tile(X2, y, W2, TH, "G", "d_g", "%.1f" % g, gcol, ex)
        y += TH + 14
        # throttle: name, bar, percent (one row) / gear: name, state (one row); AOA and brake are on the HUD / lights
        thr = s.get("thr", 0.0)
        tc = AMBER if thr > 0.95 else GREEN
        self._name("THR", "d_thr", 18, y + 40, ex)
        self.box(250, y + 14, 470, 52, LBL_COL, 2)
        self.fill(253, y + 17, 464 * max(0.0, min(1.0, thr)), 46, tc)
        self.text("%3.0f%%%s" % (thr * 100, " AB" if thr > 0.95 else ""), 870, y + 40, 3.6, tc)
        y += 92
        gear = s.get("gear", 0.0)
        gtxt, gcol = ("DOWN", GREEN) if gear > 0.95 else ("UP", WHITE) if gear < 0.05 else ("TRANSIT", AMBER)
        self._name("GEAR", "d_gear", 18, y + 40, ex)
        if ex.get("beginner"):
            self.label({"DOWN": "v_down", "UP": "v_up"}.get(gtxt, "v_transit"), 250, y + 40, D_LBL, gcol)
        else:
            self.text(gtxt, 250, y + 40, 3.6, gcol, center=False)
        if s.get("brk", 0.0) > 0.3:
            self._name("BRAKE", "r_brk", 640, y + 40, ex, AMBER)
        self.last["MFD_L"] = dict(kts=round(kts), ft=round(ft), vs=round(vs), thr=round(thr * 100), gear=gtxt, g=round(g, 1), gmax=round(gm, 1))

    def _train(self, s, ex):
        """training display: the server's lesson picture (Korean) + live target rows (name, value, target, bar) and
        the deviation trend of the first target."""
        W, H = DISP["MFD_C"]
        tut = s.get("tut") or {}
        tex = ex.get("panel_tex")
        self.image(tex, 0, 0, W, H)
        if tex is None:
            self.text("TRAINING - waiting for sim/server.py", W / 2, H / 2, 2.4, AMBER)
        ph = tut.get("phase")
        tg = tut.get("targets") or []
        self.last["MFD_C"] = dict(phase=ph, targets=[(t.get("name"), t.get("txt"), t.get("st")) for t in tg])
        if ph not in ("practice", "solo") or not tg:
            return
        # band y 430..690 (render.py keeps server y 344..552 free in practice / solo): up to 3 rows + the trend
        y0, rh = 476, 86
        n = min(3, len(tg))
        self.fill(14, y0 - 46, W - 28, rh * n + 8, unreal.LinearColor(0.0, 0.02, 0.03, 0.9))
        for i, t in enumerate(tg[:3]):
            y = y0 + i * rh
            col = ST_COL[min(2, max(0, int(t.get("st", 0))))]
            if ex.get("beginner"):
                self.label("t_" + t["name"], 26, y, 64, WHITE)
            else:
                self.text(t["name"], 30, y, 2.4, WHITE, center=False)
            self.text("%s" % t.get("txt", ""), 350, y, 3.6, col)
            self.text("%s ±%g" % (t.get("ttxt", ""), t.get("tol", 0)), 482, y, 1.8, LBL_COL, center=False)
            # deviation bar: centre = target, green band = tolerance, marker = now
            bx, bw = 770, 240
            tol = max(1e-6, float(t.get("tol", 1)))
            k = bw / 2 / (3 * tol)
            self.box(bx, y - 16, bw, 32, LBL_COL, 2)
            self.fill(bx + bw / 2 - tol * k, y - 13, 2 * tol * k, 26, unreal.LinearColor(0.05, 0.35, 0.14, 1.0))
            d = max(-3 * tol, min(3 * tol, float(t.get("dev", 0))))
            mx = bx + bw / 2 + d * k
            self.fill(mx - 7, y - 24, 14, 48, col)
        # trend of the first target over the last 30 s (deviation / tolerance)
        t0 = tut.get("t", 0.0) or 0.0
        if tg:
            v = float(tg[0].get("dev", 0)) / max(1e-6, float(tg[0].get("tol", 1)))
            if not self.hist or t0 - self.hist[-1][0] >= 0.2 or t0 < self.hist[-1][0]:
                if self.hist and t0 < self.hist[-1][0]:
                    self.hist = []
                self.hist.append((t0, v))
            self.hist = [p for p in self.hist if t0 - p[0] <= 30.0]
        gx, gy, gw, gh = 1030, y0 - 36, 230, rh * n - 12
        self.box(gx, gy, gw, gh, LBL_COL, 2)
        mid = gy + gh / 2
        self.fill(gx + 2, mid - gh / 6, gw - 4, gh / 3, unreal.LinearColor(0.05, 0.35, 0.14, 1.0))
        pts = [(gx + gw - (t0 - t) / 30.0 * gw, mid - max(-3.0, min(3.0, v)) / 3.0 * gh / 2) for t, v in self.hist]
        for a, b in zip(pts, pts[1:]):
            self.line(a, b, AMBER, 4)

    def _session(self, s, ex):
        """chair cue vs its limits, status, ACTIVE warnings only (big, with a short Korean line); master caution logic."""
        y = self._title("CHAIR / WARNINGS", "ses_t", ex)
        t = s.get("t", 0.0)
        beg = ex.get("beginner")
        self.text("%d:%02d" % (int(t) // 60, int(t) % 60), 920, 72, 3.0, LBL_COL)      # flight time, small, top right
        lim = s.get("chair_lim") or (18.0, 14.0)
        tgt = s.get("chair_tgt") or (0.0, 0.0)
        for en, ko, val, tv, L in (("CHAIR ROLL", "d_croll", s.get("chair_roll", 0.0), tgt[0], lim[0]),
                                   ("CHAIR PITCH", "d_cpitch", s.get("chair_pitch", 0.0), tgt[1], lim[1])):
            self.box(12, y, 1000, 196, unreal.LinearColor(0.16, 0.2, 0.25, 1.0), 2)
            self._name(en, ko, 28, y + 44, ex)
            near = abs(val) > 0.9 * L
            self.text("%+.1f" % val, 880, y + 48, 4.2, AMBER if near else GREEN)
            bx, bw, by = 120, 784, y + 136
            self.box(bx, by - 22, bw, 44, LBL_COL, 2)
            k = bw / 2 / L
            self.fill(bx + bw / 2 - 2, by - 22, 4, 44, LBL_COL)
            self.fill(bx + bw / 2 + max(-L, min(L, val)) * k - 10, by - 30, 20, 60, AMBER if near else GREEN)
            self.fill(bx + bw / 2 + max(-L, min(L, tv)) * k - 3, by - 34, 6, 68, CYAN)
            self.text("-%g" % L, 64, by, D_SUB, LBL_COL)
            self.text("+%g" % L, 960, by, D_SUB, LBL_COL)
            y += 208
        # status (only what is on): paused / loading / demo / easy mode / slow time
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
        if chips:
            x = 24
            for en, ko, col in chips[:2]:
                w = self._name(en, ko, x, y + 40, ex, col)
                x += w + 40
            y += 84
        # warnings: only the active ones, big (the old list of all five in dim small text was unreadable)
        act = [k for k in WARN_TXT if k in (ex.get("warnings") or [])]
        y += 10
        if not act:
            self._name("NO WARNINGS", "wd_none", 512, y + 60, ex, unreal.LinearColor(0.35, 0.4, 0.45, 1.0), "c")
        for key in act[:2]:
            en, _ko, col = WARN_TXT[key]
            self.fill(12, y, 1000, 168, unreal.LinearColor(col.r * 0.28, col.g * 0.28, col.b * 0.28, 1.0))
            self.text(en, 28, y + 48, 4.2, col, center=False)
            if beg:
                self.label("wd_" + key, 28, y + 122, 68, WHITE)
            y += 178
        self.last["MFD_R"] = dict(warnings=list(act), chair=[round(s.get("chair_roll", 0.0), 1), round(s.get("chair_pitch", 0.0), 1)])
