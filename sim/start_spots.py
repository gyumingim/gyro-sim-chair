"""Busan start-location picker (server side): preset spots, a point clicked on the Busan map, altitude / heading,
'random', the last choice remembered in sim/out/start_spot.json (local, outside git).

The server (server.py) owns the picker state; it is shown in Unreal as one picture (map + list + buttons) that this module
draws with PIL into sim/out/spot_N.png (rotating names), on the 'Minimap' plate moved to the middle of the view
(sim_client._spot_screen). While the picker is open the sim stays paused; a selection is previewed (the aircraft is put
there, still paused, 0.5 s after the last change) so the view behind the picture shows where you will start.

Commands ({"cmd": "spot", "op": ...}, from Unreal keys / mouse, the joystick thread or the browser):
  open | cancel | up | down | sel (i) | alt (d = +1 / -1 steps) | hdg (d) | point (lat, lon) | click (u, v on the picture)
  | random | go
Keys in Unreal: Up / Down = list, Left / Right = heading -/+ 15 deg (Shift 5), PageUp / PageDown or W / S = altitude
+/- 50 m, Enter / Space = start, R = random, Backspace = back to the menu (only when opened from the F1 menu), Tab = hide
the picture (look at the preview), mouse click on the map / list / buttons.

The map picture is the minimap made by sim/minimap_build.py from the local V-World tile cache (C:/GyroSimTiles/minimap,
outside git, V-World terms 19조); without it the map area is plain grey with the preset dots.
"""
import json, math, os, random, threading, time
# PIL is imported where the picture is drawn (Unreal's Python imports this module for the presets / layout only)

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "out")
LAST = os.path.join(OUT, "start_spot.json")
MINIMAP_DIR = os.path.join(os.environ.get("GYROSIM_TILES", r"C:\GyroSimTiles"), "minimap")
FONT, FONT_B = r"C:\Windows\Fonts\malgun.ttf", r"C:\Windows\Fonts\malgunbd.ttf"

KTS = 250.0                      # air start speed (F-16 trims level here at low altitude)
ALT_STEP, HDG_STEP = 50.0, 15.0
ALT_MAX, AGL_MIN, AGL_CUSTOM = 3000.0, 60.0, 300.0
PREVIEW_S = 0.5                  # put the aircraft at the selection this long after the last change (still paused)

# (key, name, lat, lon, alt_m MSL, heading true deg). Start points are a little off the place, looking at it; altitudes
# clear the hills / towers ahead (Marine City towers ~300 m, LCT 411 m, Geumjeongsan 801 m, Hwangnyeongsan 427 m).
# 'gimhae' = on the runway (36L, stopped, the server's runway start).
PRESETS = [
    ("haeundae", "해운대·마린시티", 35.1400, 129.1700, 500.0, 320.0),
    ("gwangalli", "광안리·광안대교", 35.1200, 129.1250, 400.0, 0.0),
    ("centum", "센텀시티", 35.1500, 129.1150, 500.0, 35.0),
    ("seomyeon", "서면", 35.1350, 129.0550, 600.0, 10.0),
    ("nampo", "남포동·자갈치", 35.0800, 129.0250, 400.0, 0.0),
    ("station", "북항·부산역", 35.1050, 129.0750, 450.0, 290.0),
    ("yeongdo", "영도·태종대", 35.0300, 129.0600, 300.0, 50.0),
    ("songdo", "송도", 35.0550, 129.0200, 500.0, 350.0),
    ("dadaepo", "다대포", 35.0250, 128.9750, 300.0, 340.0),
    ("gijang", "기장·해동용궁사", 35.1700, 129.2150, 300.0, 20.0),
    ("gimhae", "김해공항 (활주로)", 35.1665, 128.9386, 2.0, 353.96),
    ("geumjeongsan", "금정산", 35.2500, 129.0600, 1100.0, 340.0),
    ("hwangnyeongsan", "황령산", 35.1350, 129.0950, 750.0, 340.0),
]
# where each number is drawn on the map (the place itself; the start point above is a little off it, looking at it)
PLACE = dict(haeundae=(35.1580, 129.1520), gwangalli=(35.1530, 129.1180), centum=(35.1690, 129.1310), seomyeon=(35.1578, 129.0600),
             nampo=(35.0970, 129.0300), station=(35.1150, 129.0420), yeongdo=(35.0530, 129.0850), songdo=(35.0760, 129.0170),
             dadaepo=(35.0470, 128.9660), gijang=(35.1880, 129.2230), gimhae=(35.1730, 128.9470), geumjeongsan=(35.2830, 129.0450),
             hwangnyeongsan=(35.1570, 129.0830))
CUSTOM, RANDOM = "custom", "random"
COMPASS = ("북", "북동", "동", "남동", "남", "남서", "서", "북서")

# picture layout (px): map square on the left, list + controls on the right
W, H, MAP = 1600, 1000, 1000
X0 = MAP + 30
ROW_Y0, ROW_H = 92, 44
BG, EDGE = (6, 12, 18), (60, 200, 110)
GREEN, WHITE, GREY, YELLOW, RED, SEL_BG = (120, 255, 160), (235, 240, 245), (165, 180, 195), (255, 225, 120), (255, 90, 80), (24, 70, 48)
_F = {}


def F(sz, bold=False):
    from PIL import ImageFont
    k = (sz, bold)
    if k not in _F:
        try:
            _F[k] = ImageFont.truetype(FONT_B if bold else FONT, sz)
        except OSError:
            _F[k] = ImageFont.load_default()
    return _F[k]


def compass(h):
    return COMPASS[int(((h % 360) + 22.5) // 45) % 8]


def _merc(lat, lon):
    s = math.sin(math.radians(max(-85.0, min(85.0, lat))))
    return (lon + 180.0) / 360.0, 0.5 - math.log((1 + s) / (1 - s)) / (4 * math.pi)


def _unmerc(mx, my):
    lon = mx * 360.0 - 180.0
    lat = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * my))))
    return lat, lon


def _finite(v):
    """client number -> finite float, or None (NaN / inf / a huge int / not a number)."""
    try:
        f = float(v)
    except (TypeError, ValueError, OverflowError):
        return None
    return f if math.isfinite(f) else None


class Picker:
    def __init__(self, ground=None, render=True, out_dir=OUT, last_file=LAST, minimap_dir=MINIMAP_DIR):
        """ground(lat, lon) -> ground / roof height MSL m (server: DEM + roofs) or None."""
        self.ground = ground
        self.render_on = render
        self.out_dir, self.last_file = out_dir, last_file
        os.makedirs(out_dir, exist_ok=True)
        self.open = False
        self.can_cancel = False
        self.rows = [p[0] for p in PRESETS] + [CUSTOM, RANDOM]
        self.sel = 0
        self.custom = None                       # (lat, lon) clicked on the map
        self.alt, self.hdg = PRESETS[0][4], PRESETS[0][5]
        self.changed_t = None                    # preview pending since (monotonic)
        self.previewed = None
        self.ver, self.img, self._img_ver, self._key = 0, "", 0, None
        self._lock = threading.Lock()
        self._base = None
        self.merc = None
        try:
            meta = json.load(open(os.path.join(minimap_dir, "busan_minimap.json"), encoding="utf-8"))
            self.merc = tuple(meta["merc"])
            self._map_png = os.path.join(minimap_dir, "busan_minimap.png")
        except (OSError, ValueError, KeyError):
            self._map_png = None
        if self.merc is None:                    # no minimap: same box as minimap_build.BOX
            (x0, y0), (x1, y1) = _merc(35.40, 128.75), _merc(34.96, 129.33)
            self.merc = (x0, y0, x1, y1)
        self._load_last()

    # ---- state ------------------------------------------------------------------------------------------------------
    @property
    def key(self):
        return self.rows[self.sel % len(self.rows)]

    def preset(self, key):
        return next((p for p in PRESETS if p[0] == key), None)

    def ground_at(self, lat, lon):
        if self.ground is None:
            return None
        try:
            g = self.ground(lat, lon)
            return None if g is None else float(g)
        except Exception:
            return None

    def _alt_min(self, lat, lon):
        g = self.ground_at(lat, lon)
        return (g if g is not None else 0.0) + AGL_MIN

    def _select(self, i, keep=False):
        self.sel = i % len(self.rows)
        k = self.key
        p = self.preset(k)
        if p and not keep:
            self.alt, self.hdg = p[4], p[5]
        elif k == CUSTOM and self.custom and not keep:
            self.alt = self._custom_alt(*self.custom)
        self._changed()

    def _custom_alt(self, lat, lon):
        g = self.ground_at(lat, lon)
        a = max(AGL_CUSTOM, (g or 0.0) + AGL_CUSTOM)
        return min(ALT_MAX, math.ceil(a / ALT_STEP) * ALT_STEP)

    def _changed(self):
        self.changed_t = time.monotonic()

    def spot(self, rng=None):
        """the current selection as a start: dict(key, name, mode 'air' | 'runway', lat, lon, alt_m, hdg, kts) or None
        (custom row without a point). 'random' picks one of the air presets (not the current one)."""
        k = self.key
        if k == RANDOM:
            pool = [p for p in PRESETS if p[0] != "gimhae"]
            p = (rng or random).choice(pool)
            return dict(key=p[0], name=p[1], mode="air", lat=p[2], lon=p[3], alt_m=p[4], hdg=p[5], kts=KTS, random=True)
        if k == CUSTOM:
            if not self.custom:
                return None
            lat, lon = self.custom
            return dict(key=CUSTOM, name="지도에서 고른 곳", mode="air", lat=lat, lon=lon, alt_m=max(self.alt, self._alt_min(lat, lon)),
                        hdg=self.hdg % 360, kts=KTS)
        p = self.preset(k)
        if k == "gimhae":
            return dict(key=k, name=p[1], mode="runway", lat=p[2], lon=p[3], alt_m=p[4], hdg=p[5], kts=0.0)
        return dict(key=k, name=p[1], mode="air", lat=p[2], lon=p[3], alt_m=max(self.alt, self._alt_min(p[2], p[3])), hdg=self.hdg % 360, kts=KTS)

    def _load_last(self):
        try:
            d = json.load(open(self.last_file, encoding="utf-8"))
            nums = [float(d[k]) for k in ("alt_m", "hdg", "lat", "lon") if d.get(k) is not None]
        except (OSError, ValueError, TypeError, AttributeError, OverflowError, RecursionError):
            return
        if not all(math.isfinite(v) for v in nums):          # a corrupt last-spot file (NaN / inf): ignore it
            return
        k = d.get("key")
        if k not in self.rows:
            return
        if k == CUSTOM:
            if d.get("lat") is None:
                return
            self.custom = (float(d["lat"]), float(d["lon"]))
        self.sel = self.rows.index(k)
        if k != RANDOM:
            self.alt = float(d.get("alt_m", self.alt))
            self.hdg = float(d.get("hdg", self.hdg))
        if k == RANDOM:
            self.alt, self.hdg = PRESETS[0][4], PRESETS[0][5]

    def save_last(self):
        k = self.key
        if not (math.isfinite(self.alt) and math.isfinite(self.hdg)):     # never write NaN / inf to the last-spot file
            return
        d = dict(key=k, alt_m=self.alt, hdg=self.hdg % 360, saved=time.strftime("%Y-%m-%d %H:%M:%S"))
        if k == CUSTOM and self.custom:
            d.update(lat=self.custom[0], lon=self.custom[1])
        try:
            with open(self.last_file, "w", encoding="utf-8") as f:
                json.dump(d, f, ensure_ascii=False, indent=1)
        except OSError:
            pass

    # ---- map <-> picture ----------------------------------------------------------------------------------------------
    def to_px(self, lat, lon):
        x0, y0, x1, y1 = self.merc
        mx, my = _merc(lat, lon)
        return (mx - x0) / (x1 - x0) * MAP, (my - y0) / (y1 - y0) * MAP

    def from_px(self, x, y):
        x0, y0, x1, y1 = self.merc
        return _unmerc(x0 + x / MAP * (x1 - x0), y0 + y / MAP * (y1 - y0))

    # buttons on the right side (x0, y0, x1, y1) px
    BTN = dict(alt_dn=(X0 + 330, 770, X0 + 390, 816), alt_up=(X0 + 400, 770, X0 + 460, 816),
               hdg_dn=(X0 + 330, 824, X0 + 390, 870), hdg_up=(X0 + 400, 824, X0 + 460, 870),
               go=(X0, 886, X0 + 300, 950), cancel=(X0 + 320, 886, X0 + 540, 950))

    # ---- commands -----------------------------------------------------------------------------------------------------
    def command(self, m):
        """returns 'go' / 'cancel' when the caller must act, else None."""
        op = m.get("op")
        if op == "up":
            self._select(self.sel - 1)
        elif op == "down":
            self._select(self.sel + 1)
        elif op == "sel":
            try:
                self._select(int(m.get("i", 0)))
            except (TypeError, ValueError):
                pass
        elif op == "alt":
            d = _finite(m.get("d", 1))
            if d is not None:
                self._step_alt(d)
        elif op == "hdg":
            d, step = _finite(m.get("d", 1)), _finite(m.get("step", HDG_STEP))
            h = (self.hdg + d * step) % 360 if d is not None and step is not None else float("nan")
            if not math.isfinite(h):                               # NaN / inf / overflow (scripted client): ignored
                return None
            self.hdg = h
            if self.key == RANDOM:
                self._select(0)
            self._changed()
        elif op == "point":
            try:
                self._point(float(m["lat"]), float(m["lon"]))
            except (KeyError, TypeError, ValueError):
                pass
        elif op == "click":
            try:
                return self._click(float(m["u"]) * W, float(m["v"]) * H)
            except (KeyError, TypeError, ValueError):
                pass
        elif op == "random":
            self._select(self.rows.index(RANDOM))
        elif op == "go":
            return "go" if self.spot() is not None else None
        elif op == "cancel":
            return "cancel" if self.can_cancel else None
        return None

    def _step_alt(self, d):
        if self.key == RANDOM or self.key == "gimhae":
            return
        s = self.spot()
        lo = self._alt_min(s["lat"], s["lon"]) if s else AGL_MIN
        a = math.floor(self.alt / ALT_STEP + 1e-6) * ALT_STEP if d < 0 and self.alt % ALT_STEP else self.alt
        self.alt = max(math.ceil(lo / ALT_STEP) * ALT_STEP, min(ALT_MAX, a + d * ALT_STEP))
        self._changed()

    def _point(self, lat, lon):
        x, y = self.to_px(lat, lon)
        if not (0 <= x <= MAP and 0 <= y <= MAP):
            return
        self.custom = (round(lat, 5), round(lon, 5))
        keep_hdg = self.hdg
        self._select(self.rows.index(CUSTOM))
        self.hdg = keep_hdg
        self.alt = self._custom_alt(lat, lon)

    def _click(self, x, y):
        if 0 <= x < MAP and 0 <= y < MAP:
            for i, p in enumerate(PRESETS):                # on a preset dot: that preset
                px, py = self.to_px(*PLACE.get(p[0], p[2:4]))
                if math.hypot(px - x, py - y) <= 18:
                    self._select(i)
                    return None
            self._point(*self.from_px(x, y))
            return None
        for i in range(len(self.rows)):
            y0 = ROW_Y0 + i * ROW_H
            if X0 - 10 <= x <= W - 20 and y0 <= y < y0 + ROW_H:
                self._select(i)
                return None
        for name, (a, b, c, d) in self.BTN.items():
            if a <= x <= c and b <= y <= d:
                if name == "go":
                    return self.command({"op": "go"})
                if name == "cancel":
                    return self.command({"op": "cancel"})
                if name.startswith("alt"):
                    self._step_alt(1 if name.endswith("up") else -1)
                else:
                    self.command({"op": "hdg", "d": 1 if name.endswith("up") else -1})
        return None

    def preview_due(self):
        """the spot to preview now (debounced), or None."""
        if self.changed_t is None or time.monotonic() - self.changed_t < PREVIEW_S:
            return None
        self.changed_t = None
        if self.key == RANDOM:
            return None
        s = self.spot()
        if s is None:
            return None
        k = (s["mode"], round(s["lat"], 5), round(s["lon"], 5), round(s["alt_m"]), round(s["hdg"]))
        if k == self.previewed:
            return None
        self.previewed = k
        return s

    # ---- picture ------------------------------------------------------------------------------------------------------
    def public(self):
        s = self.spot() if self.open else None
        d = dict(open=self.open, can_cancel=self.can_cancel, sel=self.sel, key=self.key, spot=s)
        if self.open:
            key = (self.sel, self.custom, round(self.alt), round(self.hdg), self.can_cancel)
            if self.render_on and key != self._key:
                self._key = key
                self.ver += 1
                threading.Thread(target=self._render, args=(self.ver,), daemon=True).start()
        d.update(ver=self._img_ver, img=self.img)
        return d

    def _render(self, ver):
        with self._lock:
            try:
                fn = os.path.join(self.out_dir, "spot_%d.png" % (ver % 4))
                self.render().save(fn, compress_level=1)
            except Exception as e:
                print("spot picker: render failed", repr(e), flush=True)
                return
            if ver > self._img_ver:
                self.img, self._img_ver = fn, ver

    def _base_map(self):
        from PIL import Image, ImageDraw
        if self._base is None:
            im = None
            if self._map_png and os.path.exists(self._map_png):
                try:
                    im = Image.open(self._map_png).convert("RGB").resize((MAP, MAP), Image.LANCZOS)
                except OSError:
                    im = None
            if im is None:
                im = Image.new("RGB", (MAP, MAP), (40, 52, 64))
                ImageDraw.Draw(im).text((30, 30), "지도 그림 없음 (python sim/minimap_build.py)", font=F(26), fill=WHITE)
            g = ImageDraw.Draw(im)
            for i, p in enumerate(PRESETS):
                x, y = self.to_px(*PLACE.get(p[0], p[2:4]))
                g.ellipse([x - 15, y - 15, x + 15, y + 15], fill=(10, 20, 30), outline=YELLOW, width=3)
                t = str(i + 1)
                g.text((x - g.textlength(t, font=F(20, True)) / 2, y - 14), t, font=F(20, True), fill=YELLOW)
            self._base = im
        return self._base

    def render(self):
        from PIL import Image, ImageDraw
        im = Image.new("RGB", (W, H), BG)
        im.paste(self._base_map(), (0, 0))
        g = ImageDraw.Draw(im)
        s = self.spot()
        k = self.key
        # selection on the map: ring + heading arrow
        if s is not None and k != RANDOM:
            x, y = self.to_px(s["lat"], s["lon"])
            h = math.radians(s["hdg"])
            fx, fy = math.sin(h), -math.cos(h)
            for col, wd in (((0, 0, 0), 9), (RED, 5)):
                g.line([(x, y), (x + fx * 80, y + fy * 80)], fill=col, width=wd)
                ax, ay = x + fx * 80, y + fy * 80
                for sgn in (-1, 1):
                    a2 = h + math.pi + sgn * 0.45
                    g.line([(ax, ay), (ax + math.sin(a2) * 24, ay - math.cos(a2) * 24)], fill=col, width=wd)
            g.ellipse([x - 22, y - 22, x + 22, y + 22], outline=(0, 0, 0), width=8)
            g.ellipse([x - 22, y - 22, x + 22, y + 22], outline=RED, width=4)
            if k == CUSTOM:
                for col, wd in (((0, 0, 0), 6), (WHITE, 2)):
                    g.line([(x - 34, y), (x - 10, y)], fill=col, width=wd); g.line([(x + 10, y), (x + 34, y)], fill=col, width=wd)
                    g.line([(x, y - 34), (x, y - 10)], fill=col, width=wd); g.line([(x, y + 10), (x, y + 34)], fill=col, width=wd)
        g.rectangle([0, 0, MAP - 1, H - 1], outline=(200, 215, 230), width=3)
        g.rectangle([10, H - 46, 520, H - 10], fill=(0, 0, 0))
        g.text((20, H - 44), "지도를 누르면 그 위치에서 출발해요", font=F(24), fill=WHITE)
        # right side
        g.rectangle([MAP, 0, W - 1, H - 1], outline=EDGE, width=4)
        g.text((X0, 22), "어디서 출발할까요?", font=F(40, True), fill=GREEN)
        for i, rk in enumerate(self.rows):
            y0 = ROW_Y0 + i * ROW_H
            if i == self.sel:
                g.rectangle([X0 - 10, y0, W - 20, y0 + ROW_H - 4], fill=SEL_BG, outline=GREEN, width=2)
            p = self.preset(rk)
            if p:
                label = "%2d  %s" % (i + 1, p[1])
            elif rk == CUSTOM:
                label = "     지도에서 고른 곳" + ("" if self.custom else " (지도를 누르세요)")
            else:
                label = "     무작위"
            g.text((X0, y0 + 4), label, font=F(27, i == self.sel), fill=WHITE if i == self.sel else GREY)
        # altitude / heading / speed
        y = 770
        if k == RANDOM:
            g.text((X0, y + 6), "고도·방향: 고른 곳에 맞춰 자동", font=F(26), fill=GREY)
        elif k == "gimhae":
            g.text((X0, y + 6), "활주로 36L 에 멈춘 채 출발 (방향 354°)", font=F(26), fill=GREY)
            g.text((X0, y + 60), "W 스로틀, G 바퀴, B 브레이크", font=F(24), fill=GREY)
        elif s is not None:
            gr = self.ground_at(s["lat"], s["lon"])
            g.text((X0, y + 6), "고도 %d m" % s["alt_m"] + ("  (땅 위 %d m)" % (s["alt_m"] - gr) if gr is not None else ""), font=F(26, True), fill=WHITE)
            g.text((X0, y + 60), "방향 %03d° %s   %d kt" % (round(s["hdg"]) % 360, compass(s["hdg"]), KTS), font=F(26, True), fill=WHITE)
            for name in ("alt_dn", "alt_up", "hdg_dn", "hdg_up"):
                a, b, c, d = self.BTN[name]
                g.rectangle([a, b, c, d], fill=(30, 44, 58), outline=GREY, width=2)
                t = "-" if name.endswith("dn") else "+"
                g.text(((a + c) / 2 - g.textlength(t, font=F(34, True)) / 2, b - 2), t, font=F(34, True), fill=WHITE)
        else:
            g.text((X0, y + 6), "지도에서 출발할 곳을 누르세요", font=F(26), fill=YELLOW)
        a, b, c, d = self.BTN["go"]
        ok = s is not None
        g.rectangle([a, b, c, d], fill=(30, 140, 70) if ok else (40, 60, 50), outline=GREEN, width=3)
        g.text((a + 30, b + 8), "출발 (Enter)", font=F(32, True), fill=WHITE if ok else GREY)
        if self.can_cancel:
            a, b, c, d = self.BTN["cancel"]
            g.rectangle([a, b, c, d], fill=(50, 50, 60), outline=GREY, width=2)
            g.text((a + 22, b + 12), "메뉴로 (Bksp)", font=F(28), fill=WHITE)
        hint, sz = "↑↓ 고르기  ←→ 방향  PgUp/PgDn 고도  R 무작위  Tab 미리보기", 20
        while sz > 12 and g.textlength(hint, font=F(sz)) > W - 20 - X0:
            sz -= 1
        g.text((X0, 960), hint, font=F(sz), fill=GREY)
        return im
