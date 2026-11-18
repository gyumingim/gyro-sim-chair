"""Right MFD moving map (11-15, user decision; replaces the floating head-locked Busan minimap plate by default).

Drawn by hud.Painter into the MFD_R render target (so it is a cockpit display on the monitor and in VR):
  - V-World satellite tiles straight from the LOCAL tile cache (C:/GyroSimTiles/vworld/Satellite/<z>/<y>/<x>.jpg, z13,
    ~4 km per tile at Busan). Nothing new is written to disk: the tiles are imported as transient textures and dimmed /
    desaturated at render time by the UI material M_MfdMap (Scripts/cockpit/mfd_map_material.py), stored tiles untouched
    (terms 13조 10항 / 19조: no changed copies; render-time look only, like ground_detail.hlsl).
  - heading-up, own-ship triangle low in the middle, green range rings 5 / 10 km, 'N' on the outer ring.
  - place names upright, one size, from the label atlas Art/Cockpit/tex/T_MapNames.png (Scripts/cockpit/make_map_labels.py;
    the canvas font has no Hangul); positions = sim/minimap_build.PLACES (approximate, orientation only).
  - the V-World credit line on the map itself (the screen plate stays too).
Missing tiles (sea / outside the cache) stay the dark display background. A few tiles are imported per redraw
(MAX_NEW), so flying into new ground fills in over ~1 s instead of one long hitch (a cold start with no pause - map
first switched on, or a jump in flight - takes several seconds: ~50 tiles on the display at one per map redraw).
"""
import json, math, os
import unreal

TILES = os.path.join(os.environ.get("GYROSIM_TILES", "C:\\GyroSimTiles"), "vworld", "Satellite")
Z = 13
MAT = "/Game/Cockpit/Materials/M_MfdMap"
SAT = 0.40                        # user 11-15: ~40 % saturation
BRIGHT = 0.60                     # ~60 % brightness as a display (sRGB) value -> linear x 0.6^2.2 in the material
PX_KM = 44.0                      # logical display px per km (display 1024 x 1024 logical)
OWN = (512.0, 700.0)              # own-ship position on the display (heading-up: more map ahead)
RINGS_KM = (5.0, 10.0)
# tile imports per redraw. 11-15 (stutter fix): 6 -> 1 (each is a synchronous JPEG import, a few ms); the disc around the
# aircraft is preloaded while the sim is paused / the start picker is open (preload, PRELOAD_N per frame)
MAX_NEW = 1
PRELOAD_N = 2
# redraw only when the picture would change: moved > REDRAW_PX logical px, turned > REDRAW_DEG, other inputs changed, a tile
# still pending, or REDRAW_MAX_S passed
REDRAW_PX, REDRAW_DEG, REDRAW_MAX_S = 2.0, 0.5, 1.0
NAME_H = 44.0                     # place name height (logical px), the same for every name
PROJ = unreal.Paths.convert_relative_path_to_full(unreal.Paths.project_dir())
LBL_DIR = os.path.join(PROJ, "Art", "Cockpit", "tex")
V2 = unreal.Vector2D
RL = unreal.RenderingLibrary
EARTH_C = 40075016.686
log = lambda *a: unreal.log("[mfd_map] " + " ".join(str(x) for x in a))


def merc(lat, lon):
    s = math.sin(math.radians(max(-85.0, min(85.0, lat))))
    return (lon + 180.0) / 360.0, 0.5 - math.log((1 + s) / (1 - s)) / (4 * math.pi)


class MfdMap:
    def __init__(self, world):
        self.world = world
        self.tiles = {}
        self.new = 0
        self.last = None                  # (px x, px y, psi, key, time) of the last draw (changed())
        self.pending = False              # a tile in view was left for a later redraw (MAX_NEW)
        self.disc = (None, [])            # ((tile x, tile y, S rounded), [(tx, ty), ...]) tile set around the aircraft
        self.mat = unreal.load_asset(MAT)        # (EditorAssetLibrary refuses during PIE: plain load)
        self.ok = self.mat is not None and os.path.isdir(os.path.join(TILES, str(Z)))
        self.white = unreal.load_asset("/Engine/EngineResources/WhiteSquareTexture")
        self.atlas, self.rects, self.size, self.places, self.credit = None, {}, (1, 1), [], None
        try:
            j = json.load(open(os.path.join(LBL_DIR, "mapnames.json"), encoding="utf-8"))
            self.rects, self.size, self.places, self.credit = j["rects"], tuple(j["size"]), j["places"], j.get("credit")
            self.atlas = RL.import_file_as_texture2d(world, os.path.join(LBL_DIR, "T_MapNames.png"))
        except Exception as e:
            log("name atlas missing", repr(e))
        log("ready" if self.ok else "off (no M_MfdMap or no z%d tile cache)" % Z, TILES)

    def _tile(self, x, y):
        key = (x, y)
        if key in self.tiles:
            return self.tiles[key]
        p = os.path.join(TILES, str(Z), str(y), "%d.jpg" % x)
        if not os.path.exists(p):
            self.tiles[key] = None
            return None
        if self.new >= MAX_NEW:
            return None                          # next redraw
        self.new += 1
        mid = None
        try:
            tex = RL.import_file_as_texture2d(self.world, p)
            if tex is not None:
                mid = unreal.MaterialLibrary.create_dynamic_material_instance(self.world, self.mat)
                mid.set_texture_parameter_value("Tex", tex)
                mid.set_scalar_parameter_value("Desat", 1.0 - SAT)
                mid.set_scalar_parameter_value("Bright", BRIGHT ** 2.2)
        except Exception as e:
            log("tile", key, repr(e))
        self.tiles[key] = mid
        return mid

    @staticmethod
    def _scale(lat):
        return PX_KM * EARTH_C * math.cos(math.radians(lat)) / 2 ** Z / 1000.0      # logical px per tile

    def _disc(self, mx, my, S):
        """tiles within reach of the display around (mx, my) (tile units); recomputed only when the aircraft enters
        another tile (radius + 1 tile so it covers the whole tile it is in)."""
        key = (int(math.floor(mx)), int(math.floor(my)), round(S))
        if self.disc[0] != key:
            rmax = math.hypot(512.0, OWN[1]) / S + 0.75 + 1.0
            cx, cy = key[0] + 0.5, key[1] + 0.5
            ts = [(tx, ty) for ty in range(int(math.floor(cy - rmax)), int(math.floor(cy + rmax)) + 1)
                  for tx in range(int(math.floor(cx - rmax)), int(math.floor(cx + rmax)) + 1)
                  if math.hypot(tx + 0.5 - cx, ty + 0.5 - cy) <= rmax]
            ts.sort(key=lambda t: math.hypot(t[0] + 0.5 - cx, t[1] + 0.5 - cy))     # nearest first (preload order)
            self.disc = (key, ts)
        return self.disc[1]

    def changed(self, s, key, now):
        """True when a redraw would look different from the last one (and then remembers this state as drawn)."""
        lat, lon, psi = float(s.get("lat", 0.0)), float(s.get("lon", 0.0)), float(s.get("psi", 0.0))
        mx, my = merc(lat, lon)
        S = self._scale(lat)
        x, y = mx * 2 ** Z * S, my * 2 ** Z * S
        key = (key, round(float(s.get("chair_roll", 0.0)) * 2), round(float(s.get("chair_pitch", 0.0)) * 2))
        L = self.last
        if (L is None or self.pending or key != L[3] or now - L[4] >= REDRAW_MAX_S or math.hypot(x - L[0], y - L[1]) > REDRAW_PX
                or abs((psi - L[2] + 180.0) % 360.0 - 180.0) > REDRAW_DEG):
            self.last = (x, y, psi, key, now)
            return True
        return False

    def preload(self, s, n):
        """import up to n not yet loaded tiles of the disc around the aircraft (nearest first), no drawing."""
        if not self.ok or "lat" not in s:
            return 0
        lat, lon = float(s["lat"]), float(s["lon"])
        mx, my = merc(lat, lon)
        k = 0
        for tx, ty in self._disc(mx * 2 ** Z, my * 2 ** Z, self._scale(lat)):
            if (tx, ty) in self.tiles:
                continue
            if k >= n:
                break
            self.new = 0
            self._tile(tx, ty)
            k += 1
        return k

    def _label(self, c, k, key, x, y, h, col, anchor="c"):
        r = self.rects.get(key)
        if not r or self.atlas is None:
            return 0.0
        W, H = self.size
        w = r[2] * h / r[3]
        x0 = x - w / 2 if anchor == "c" else x - w if anchor == "r" else x
        for dx, dy, cc in ((2.5, 2.5, unreal.LinearColor(0, 0, 0, 0.9)), (0, 0, col)):     # dark drop shadow, then the name
            c.draw_texture(self.atlas, V2((x0 + dx) * k, (y - h / 2 + dy) * k), V2(w * k, h * k), V2(r[0] / W, r[1] / H),
                           V2(r[2] / W, r[3] / H), cc, unreal.BlendMode.BLEND_TRANSLUCENT, 0.0, V2(0, 0))
        return w

    def draw(self, P, s, green, dim, white):
        """map page background (tiles, rings, names, own-ship) into the open canvas of P (logical 1024 x 1024)."""
        c, k = P.c, P.k
        self.new = 0
        lat, lon = float(s.get("lat", 0.0)), float(s.get("lon", 0.0))
        psi = float(s.get("psi", 0.0))
        sp, cp = math.sin(math.radians(psi)), math.cos(math.radians(psi))
        n = 2 ** Z
        mx, my = merc(lat, lon)
        mx, my = mx * n, my * n
        S = self._scale(lat)                     # logical px per tile

        def to_screen(dx_t, dy_t):               # tile units east / south of the own-ship -> display px
            e, no = dx_t * S, -dy_t * S
            return OWN[0] + e * cp - no * sp, OWN[1] - (e * sp + no * cp)
        self.pending = False
        if self.ok:
            z = S + 1.5                          # a hair of overlap: no seams between rotated tiles
            h = 0.7072 * z                       # half diagonal: a rotated tile outside this margin is off the display
            for tx, ty in self._disc(mx, my, S):     # 11-15: cached tile set, off-display tiles neither drawn nor imported
                dx, dy = tx + 0.5 - mx, ty + 0.5 - my
                cx, cy = to_screen(dx, dy)
                if cx < -h or cx > 1024.0 + h or cy < -h or cy > 1024.0 + h:
                    continue
                mid = self._tile(tx, ty)
                if mid is None:
                    if (tx, ty) not in self.tiles:
                        self.pending = True      # left for the next redraw (MAX_NEW)
                    continue
                c.draw_material(mid, V2((cx - z / 2) * k, (cy - z / 2) * k), V2(z * k, z * k), V2(0, 0), V2(1, 1), -psi, V2(0.5, 0.5))
        # range rings + their distances, 'N' on the outer ring
        for i, rk in enumerate(RINGS_KM):
            P.circle(OWN[0], OWN[1], rk * PX_KM, green if i == len(RINGS_KM) - 1 else dim, 72, 3.0)
            P.text("%g" % rk, OWN[0] + rk * PX_KM * 0.71 + 18, OWN[1] - rk * PX_KM * 0.71 - 4, 2.0, green, center=False)
        rN = RINGS_KM[-1] * PX_KM
        P.text("N", OWN[0] - sp * rN, OWN[1] - cp * rN, 2.6, white)
        # place names: upright, one size, dot at the place
        for name, plat, plon in self.places:
            px, py = merc(plat, plon)
            x, y = to_screen(px * n - mx, py * n - my)
            if not (40 < x < 984 and 120 < y < 980):
                continue
            c.draw_texture(self.white, V2((x - 6) * k, (y - 6) * k), V2(12 * k, 12 * k), V2(0, 0), V2(1, 1),
                           unreal.LinearColor(1.0, 0.86, 0.35, 1.0), unreal.BlendMode.BLEND_OPAQUE, 0.0, V2(0, 0))
            self._label(c, k, name, x, y - 32, NAME_H, white)
        # own-ship triangle (points up = the heading), black outline under a white one
        tri = ((OWN[0], OWN[1] - 30), (OWN[0] + 18, OWN[1] + 18), (OWN[0] - 18, OWN[1] + 18))
        for col, w in ((unreal.LinearColor(0, 0, 0, 1), 10.0), (unreal.LinearColor(1.0, 0.9, 0.2, 1), 5.0)):
            for a, b in ((tri[0], tri[1]), (tri[1], tri[2]), (tri[2], tri[0])):
                P.line(a, b, col, w)
        P.text("HDG %03d" % (int(round(psi)) % 360), 512, 76, 2.6, green)
        if self.credit:
            self._label(c, k, self.credit, 1000, 962, 30.0, unreal.LinearColor(0.85, 0.88, 0.9, 1.0), "r")
