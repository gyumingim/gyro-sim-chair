"""Fighter-style HUD and the two MFD pages, drawn with UCanvas into render targets (sim_client.py puts them on the
world-space HUD plane and the MFD screens, so they work on the monitor and in VR).

HUD plane geometry (must match Scripts/build_level.py): plane HUD_D cm ahead of the eye, perpendicular to body X,
square, +-HUD_HALF deg around elevation HUD_EL0. A body-frame direction (x fwd, y right, z up) lands on pixel
  px = C + C * (y/x) / tan(HALF),  py = C - C * (z/x - tan(EL0)) / tan(HALF)     (C = RT size / 2)
so the horizon / pitch ladder and the flight path marker are conformal (line up with the outside world) at the eye
point. The ladder is a static atlas (draw_ladder) that the HUD material (build_level.LADDER_HLSL) looks up per pixel
from roll / pitch every frame; this Python canvas only redraws text, tapes and the FPM (HUD_HZ).
"""
import math
import unreal

HUD_D, HUD_HALF, HUD_EL0 = 2000.0, 14.0, -6.0
RT_HUD, RT_MFD = 1024, 512
LAD_W, LAD_H, LAD_AZ = 1024, 8192, 16.0     # pitch ladder atlas: x = azimuth -16..16 deg, y = elevation +90..-90 deg
GREEN = unreal.LinearColor(0.25, 1.0, 0.35, 1.0)
DIM = unreal.LinearColor(0.12, 0.55, 0.18, 1.0)
AMBER = unreal.LinearColor(1.0, 0.75, 0.15, 1.0)
RED = unreal.LinearColor(1.0, 0.2, 0.15, 1.0)
WHITE = unreal.LinearColor(0.9, 0.95, 1.0, 1.0)
CLEAR = unreal.LinearColor(0, 0, 0, 0)
V2 = unreal.Vector2D
RL = unreal.RenderingLibrary
_T = math.tan(math.radians(HUD_HALF))
_T0 = math.tan(math.radians(HUD_EL0))


def level_to_body(v, phi, th):
    """vector in the heading-aligned level frame (x fwd horizontal, y right, z up) -> body frame (x fwd, y right, z up)."""
    x, y, z = v
    ct, st, cp, sp = math.cos(th), math.sin(th), math.cos(phi), math.sin(phi)
    x1, z1 = x * ct + z * st, -x * st + z * ct
    return x1, y * cp - z1 * sp, y * sp + z1 * cp


class Painter:
    def __init__(self, world):
        self.world = world
        self.font = unreal.load_asset("/Engine/EngineFonts/RobotoDistanceField")
        self.rt_hud = RL.create_render_target2d(world, RT_HUD, RT_HUD, unreal.TextureRenderTargetFormat.RTF_RGBA8, CLEAR)
        self.rt_mfd = [RL.create_render_target2d(world, RT_MFD, RT_MFD, unreal.TextureRenderTargetFormat.RTF_RGBA8, unreal.LinearColor(0, 0, 0, 1))
                       for _ in range(2)]
        self.rt_ladder = RL.create_render_target2d(world, LAD_W, LAD_H, unreal.TextureRenderTargetFormat.RTF_RGBA8, CLEAR)
        self.c = None
        self.ts = 1.0
        self.draw_ladder()                     # text scale (HUD 1.6, MFD 1.0)

    # ---- primitives -------------------------------------------------------------------------------------------------
    def _begin(self, rt, clear):
        RL.clear_render_target2d(self.world, rt, clear)
        self.c, _size, self.ctx = RL.begin_draw_canvas_to_render_target(self.world, rt)

    def _end(self):
        RL.end_draw_canvas_to_render_target(self.world, self.ctx)
        self.c = None

    def line(self, a, b, col=GREEN, w=4.0):
        self.c.draw_line(V2(a[0], a[1]), V2(b[0], b[1]), w, col)

    def text(self, s, x, y, size=1.0, col=GREEN, center=True, vcenter=True):
        k = size * self.ts
        self.c.draw_text(self.font, s, V2(x, y), V2(k, k), col, 0.0, CLEAR, V2(0, 0), center, vcenter, False, col)

    def box(self, x, y, w, h, col=GREEN, t=3.5):
        self.c.draw_box(V2(x, y), V2(w, h), t, col)

    def circle(self, x, y, r, col=GREEN, n=16, w=4.0):
        p = [(x + r * math.cos(2 * math.pi * i / n), y + r * math.sin(2 * math.pi * i / n)) for i in range(n + 1)]
        for i in range(n):
            self.line(p[i], p[i + 1], col, w)

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
        """s = sim packet, extra = dict(radar_m, warn, tut_line, note, src)."""
        self._begin(self.rt_hud, CLEAR)
        self.ts = 1.6
        try:
            self._hud(s, extra)
        finally:
            self._end()

    def _hud(self, s, ex):
        C = RT_HUD / 2
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
        # heading tape (bottom)
        hdg = s["psi"] % 360
        y0, px_deg = 880, 13.0
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
        # throttle / gear / brake (lower left)
        thr = s.get("thr", 0.0)
        self.text("THR %3.0f%%%s" % (thr * 100, " AB" if thr > 0.99 else ""), xl, 650, 0.8)
        gear = s.get("gear", 0.0)
        gtxt = "GEAR DN" if gear > 0.95 else ("GEAR UP" if gear < 0.05 else "GEAR TRANS")
        self.text(gtxt, xl, 694, 0.8, GREEN if gear > 0.95 or gear < 0.05 else AMBER)
        if s.get("brk", 0.0) > 0.3:
            self.text("BRAKE", xr, 650, 0.8, AMBER)
        if s.get("paused"):
            self.text("PAUSED", C, 300, 1.2, AMBER)
        w = ex.get("warn")
        if w:
            self.text(w, C, 360, 1.4, RED)
        tl = ex.get("tut_line")
        if tl:
            self.text(tl, C, 770, 0.75)
        note = ex.get("note")
        if note:
            self.text(note, C, 120, 0.6, AMBER)

    # ---- MFDs (5 Hz) ------------------------------------------------------------------------------------------------
    def draw_mfd(self, i, s, ex):
        self._begin(self.rt_mfd[i], unreal.LinearColor(0.004, 0.012, 0.006, 1.0))
        self.ts = 1.0
        try:
            (self._mfd_flight if i == 0 else self._mfd_map)(s, ex)
        finally:
            self._end()

    def _osb(self, labels_top, labels_bottom):
        for k, t in enumerate(labels_top):
            self.text(t, 64 + k * 96, 24, 1.0, WHITE)
        for k, t in enumerate(labels_bottom):
            self.text(t, 64 + k * 96, 490, 1.0, WHITE)

    def _mfd_flight(self, s, ex):
        self._osb(["FLCS", "ENG", "FUEL", "TEST", "DTE"], ["SWAP", "HUD", "", "", "HSD"])
        rows = [("SPD", "%3.0f KT" % s["kts"]), ("MACH", "%.2f" % s.get("mach", 0)), ("ALT", "{:,.0f} FT".format(s["alt_m"] / 0.3048)),
                ("VS", "%+.0f FPM" % s.get("vs_fpm", 0)), ("G", "%.1f" % s.get("nz", 1)), ("AOA", "%.1f DEG" % s.get("alpha", 0) if s["kts"] > 40 else "--"),
                ("THR", "%3.0f %%" % (s.get("thr", 0) * 100)), ("GEAR", "DOWN" if s.get("gear", 0) > 0.95 else "UP" if s.get("gear", 0) < 0.05 else "MOVING"),
                ("BRAKE", "ON" if s.get("brk", 0) > 0.3 else "OFF"), ("WOW", "GROUND" if s.get("wow") else "AIR")]
        for k, (a, b) in enumerate(rows):
            y = 72 + k * 39
            self.text(a, 30, y, 1.25, DIM, center=False)
            self.text(b, 170, y, 1.4, GREEN, center=False)
        # throttle bar
        thr = s.get("thr", 0.0)
        self.box(452, 80, 30, 360, DIM, 2)
        h = 356 * thr
        for k in range(int(h / 6)):
            self.line((456, 438 - k * 6), (478, 438 - k * 6), GREEN, 3)

    def _mfd_map(self, s, ex):
        self._osb(["HSD", "DEP", "CNTL", "", "RKTU"], ["SWAP", "FCR", "", "", "SMS"])
        C, scale = 256, 230 / 10000.0          # 10 km range ring radius 230 px, heading up
        hdg = math.radians(s["psi"])
        self.circle(C, 270, 230, DIM, 48, 2)
        self.circle(C, 270, 115, DIM, 32, 2)
        self.text("10", C + 168, 270 - 168, 1.0, DIM)
        self.text("5", C + 84, 270 - 84, 1.0, DIM)
        for rw in ex.get("runways", ()):              # [(n0, e0, n1, e1)] metres from the aircraft
            pts = []
            for n, e in ((rw[0], rw[1]), (rw[2], rw[3])):
                x = e * math.cos(hdg) - n * math.sin(hdg)
                y = n * math.cos(hdg) + e * math.sin(hdg)
                pts.append((C + x * scale, 270 - y * scale))
            self.line(pts[0], pts[1], WHITE, 4)
        self.line((C, 258), (C, 290), GREEN, 3)       # own aircraft
        self.line((C - 14, 268), (C + 14, 268), GREEN, 3)
        self.line((C - 6, 288), (C + 6, 288), GREEN, 3)
        self.text("HDG %03.0f" % (s["psi"] % 360), 100, 64, 1.15, GREEN)
        d = ex.get("rkt_dist_m")
        if d is not None:
            self.text("RKTU %.1f NM %03.0f" % (d / 1852.0, ex.get("rkt_brg", 0) % 360), 370, 64, 1.15, GREEN)
        self.text(ex.get("cesium_line", ""), C, 450, 1.0, AMBER if "FLAT" in ex.get("cesium_line", "") else DIM)
