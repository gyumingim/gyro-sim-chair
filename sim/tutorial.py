"""Beginner flight lessons (Korean), checked from the sim state. Used by server.py.

Each lesson = reset mode + list of steps. A step is done when its condition holds for `hold` seconds in a row.
State goes out in every snapshot as s["tut"]; the panel text is also drawn into a PNG (sim/out/) so Unreal can show
Korean text in the cockpit (world space, works in VR too) without a Hangul font asset.

Commands (WebSocket / UDP 4221):  {"cmd": "tut", "op": "menu" | "start" | "next" | "restart" | "stop", "lesson": 1..6}
"""
import json, math, os, threading, time

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "out")
SCORES = os.path.join(OUT, "tutorial_scores.json")
FONT = r"C:\Windows\Fonts\malgun.ttf"
FONT_B = r"C:\Windows\Fonts\malgunbd.ttf"
FT = 0.3048


def hdg_err(psi, target):
    return (psi - target + 180) % 360 - 180


def ne(s):
    """north, east of the aircraft from the start point (lat0/lon0), m. Runway: east 0, north -150 .. 2850."""
    n = (s["lat"] - s["lat0"]) * 110540.0
    e = (s["lon"] - s["lon0"]) * 111320.0 * math.cos(math.radians(s["lat0"]))
    return n, e


class Step:
    def __init__(self, text, check, hold=0.3, hint="", enter=None):
        self.text, self.check, self.hold, self.hint, self.enter = text, check, hold, hint, enter


def _ft(s):
    return s["alt_m"] / FT


# ---------------------------------------------------------------------------------------------------------------------
# lessons. check(s, L) -> bool ; L = lesson runtime dict (ref values, penalties)
def lesson_controls():
    c = lambda k: (lambda s, L: s.get(k, 0.0))
    return dict(
        title="1. 조종 장치 익히기", mode="runway",
        steps=[
            Step("활주로에 서 있습니다. 조종석 아래 스틱·왼쪽 스로틀·발밑 페달을 보세요.", lambda s, L: True, 5),
            Step("스틱 오른쪽:  → 키를 누르고 있기", lambda s, L: s["ail"] > 0.6, 0.3, "→ 를 누르면 스틱이 천천히 오른쪽으로 기웁니다"),
            Step("스틱 왼쪽:  ← 키", lambda s, L: s["ail"] < -0.6),
            Step("스틱 당기기 (기수 올림):  ↓ 키", lambda s, L: s["elev"] < -0.6, 0.3, "↓ = 당기기, ↑ = 밀기 (실제 조종간과 같음)"),
            Step("스틱 밀기 (기수 내림):  ↑ 키", lambda s, L: s["elev"] > 0.6),
            Step("왼쪽 페달 (러더):  A 키", lambda s, L: s["rud"] < -0.6),
            Step("오른쪽 페달:  D 키", lambda s, L: s["rud"] > 0.6),
            Step("브레이크:  B 키 (페달 윗부분이 앞으로 눌림)", lambda s, L: s["brk"] > 0.5),
            Step("스로틀 올리기:  W 키로 30% 이상 (B 로 브레이크를 같이 잡기)", lambda s, L: s["thr"] > 0.3, 0.3, "스로틀 손잡이가 앞으로 미끄러집니다"),
            Step("스로틀 내리기:  S 키로 0% 까지", lambda s, L: s["thr"] < 0.03),
            Step("잘했습니다. G = 바퀴(기어), V = 시점, P = 일시정지. 다음 강의: 2 수평 직진", lambda s, L: True, 4),
        ])


def lesson_level():
    def enter(s, L):
        L["alt0"], L["hdg0"] = _ft(s), 0.0

    def ok(s, L):
        return abs(_ft(s) - L["alt0"]) < 100 and abs(hdg_err(s["psi"], L["hdg0"])) < 5

    return dict(
        title="2. 수평 직진 유지", mode="air",
        steps=[
            Step("공중 6000 ft, 350 kt. HUD: 왼쪽 = 속도, 오른쪽 = 고도, 위 = 방위.", lambda s, L: True, 6, enter=enter),
            Step("고도 ±100 ft, 방위 000 ±5° 를 15 초 유지하세요.", ok, 15,
                 "작게 움직이기. 기수가 내려가면 ↓ 를 살짝, 기울면 반대쪽 화살표를 톡"),
            Step("수평 비행 완료!", lambda s, L: True, 3),
        ],
        monitor=lambda s, L, dt: L.update(dev=max(L.get("dev", 0), abs(_ft(s) - L.get("alt0", _ft(s))))),
        score=lambda L: max(0, 100 - int(L.get("dev", 0) / 10)))


def lesson_turns():
    def enter(s, L):
        L["alt0"] = _ft(s)

    alt_ok = lambda s, L: abs(_ft(s) - L["alt0"]) < 300
    return dict(
        title="3. 선회 (경사 30°)", mode="air",
        steps=[
            Step("선회 = 기울이고 살짝 당기기. 경사 30° 에서 고도를 지킵니다.", lambda s, L: True, 5, enter=enter),
            Step("오른쪽 경사 30° (25~35°) 만들고 유지:  → 톡, ↓ 살짝", lambda s, L: 25 <= s["phi"] <= 35, 2),
            Step("방위 090 까지 선회, 080 에서 풀기 시작 → 수평(경사 <5°)으로 090 ±5°",
                 lambda s, L: abs(hdg_err(s["psi"], 90)) < 5 and abs(s["phi"]) < 5 and alt_ok(s, L), 3, "선회 중에 고도 ±300 ft"),
            Step("이번엔 왼쪽 경사 30°:  ← 톡, ↓ 살짝", lambda s, L: -35 <= s["phi"] <= -25, 2),
            Step("방위 000 으로 돌아와 수평", lambda s, L: abs(hdg_err(s["psi"], 0)) < 5 and abs(s["phi"]) < 5 and alt_ok(s, L), 3),
            Step("선회 완료!", lambda s, L: True, 3),
        ],
        monitor=lambda s, L, dt: L.update(dev=max(L.get("dev", 0), abs(_ft(s) - L.get("alt0", _ft(s)))),
                                          over=L.get("over", 0) or abs(s["phi"]) > 45),
        score=lambda L: max(0, 100 - int(max(0, L.get("dev", 0) - 100) / 10) - (15 if L.get("over") else 0)))


def lesson_climb():
    def lvl(target):
        return lambda s, L: abs(_ft(s) - target) < 100 and abs(s["vs_fpm"]) < 500

    def mon(s, L, dt):
        a = _ft(s)
        L["over"] = max(L.get("over", 0), a - 8000 if L["i"] <= 1 else 4900 - a if L["i"] >= 2 else 0)
        L["slow"] = L.get("slow", 0) or s["kts"] < 200

    return dict(
        title="4. 상승과 강하", mode="air",
        steps=[
            Step("상승: 스로틀 ↑(W) + 기수 10°.  강하: 스로틀 ↓(S) + 기수 -5°.", lambda s, L: True, 5),
            Step("8000 ft 로 상승해서 ±100 ft, 상승률 <500 fpm 으로 5 초 유지", lvl(8000), 5, "목표 500 ft 전부터 기수를 천천히 내리기"),
            Step("5000 ft 로 강하해서 ±100 ft 로 5 초 유지", lvl(5000), 5, "속도 200 kt 아래로 떨어뜨리지 않기"),
            Step("상승·강하 완료!", lambda s, L: True, 3),
        ],
        monitor=mon,
        score=lambda L: max(0, 100 - int(max(0, L.get("over", 0) - 100) / 10) - (15 if L.get("slow") else 0)))


def lesson_takeoff():
    def mon(s, L, dt):
        n, e = ne(s)
        L["lat"] = max(L.get("lat", 0), abs(e) if s["wow"] else 0)
        if s["wow"] and s["theta"] > 13:
            L["strike"] = True
        if s["kts"] > 300 and s["gear"] > 0.5:
            L["gear_fast"] = True

    return dict(
        title="5. 이륙", mode="runway",
        steps=[
            Step("활주로 끝에 정지. 목표: 150 kt 에서 기수 들기 → 이륙 → 기어 올리기.", lambda s, L: True, 5),
            Step("스로틀 최대:  W 를 누르고 있기 (100%)", lambda s, L: s["thr"] > 0.95, 0.3),
            Step("활주. 가운데 선 유지 (A/D 페달). 150 kt 까지 기다리기", lambda s, L: s["kts"] >= 145, 0.2, "기수가 돌면 반대쪽 페달을 톡"),
            Step("기수 들기:  ↓ 당겨서 피치 8~12°", lambda s, L: s["theta"] > 8, 0.3, "15° 넘기면 꼬리가 땅에 닿습니다"),
            Step("이륙! 땅에서 50 ft 이상, 상승 중", lambda s, L: not s["wow"] and s["agl_m"] > 15 and s["vs_fpm"] > 0, 1),
            Step("기어 올리기:  G 키", lambda s, L: s["gear"] < 0.1, 0.3, "300 kt 전에 올리기"),
            Step("1500 ft 까지 상승", lambda s, L: _ft(s) > 1500, 0.3),
            Step("이륙 완료!", lambda s, L: True, 3),
        ],
        monitor=mon,
        score=lambda L: max(0, 100 - (25 if L.get("strike") else 0) - (15 if L.get("gear_fast") else 0)
                           - int(max(0, L.get("lat", 0) - 8) * 2)))


def lesson_landing():
    def mon(s, L, dt):
        if s["wow"] and "td" not in L:
            n, e = ne(s)
            L["td"] = dict(vs=s["vs_fpm"], e=e, n=n, theta=s["theta"], kts=s["kts"])

    def score(L):
        td = L.get("td")
        if not td:
            return 0
        vs = abs(td["vs"])
        sc = 60 if vs < 300 else 45 if vs < 600 else 25 if vs < 900 else 0
        sc += 20 if abs(td["e"]) < 10 else 10 if abs(td["e"]) < 22 else 0
        sc += 20 if -150 < td["n"] < 750 else 10 if -150 < td["n"] < 2000 else 0
        return 0 if vs > 1500 or td["theta"] < -3 else sc

    def td_text(L):
        td = L.get("td")
        return "" if not td else "접지 강하율 %.0f fpm · 중심선 %.0f m · 문턱 뒤 %.0f m" % (abs(td["vs"]), td["e"], td["n"] + 150)

    return dict(
        title="6. 착륙 접근", mode="approach",
        steps=[
            Step("활주로 9 km 앞, 1550 ft, 180 kt. 3° 강하로 접근합니다.", lambda s, L: True, 4),
            Step("기어 내리기:  G 키", lambda s, L: s["gear"] > 0.9, 0.3),
            Step("속도 160 kt 근처로 (S 로 스로틀 줄이기)", lambda s, L: s["kts"] < 168, 1, "기수는 약간 위 (받음각 10° 정도)"),
            Step("활주로 정렬 유지하며 강하 (강하율 600~800 fpm). 300 ft 까지",
                 lambda s, L: s["agl_m"] < 90, 0.2, "활주로 문턱 숫자가 화면 속 한 점에 머물게"),
            Step("접지: 50 ft 에서 스로틀 0, ↓ 살짝 당겨 플레어", lambda s, L: s["wow"], 0.1),
            Step("정지: B 브레이크, 스로틀 0", lambda s, L: s["kts"] < 5 and s["wow"], 0.5),
            Step("착륙 완료!", lambda s, L: True, 4),
        ],
        monitor=mon, score=score, extra=td_text)


LESSONS = [lesson_controls, lesson_level, lesson_turns, lesson_climb, lesson_takeoff, lesson_landing]


# ---------------------------------------------------------------------------------------------------------------------
class Tutorial:
    def __init__(self, reset_fn):
        self.reset_fn = reset_fn            # reset_fn(mode) -> new sim
        self.menu = False
        self.L = None                       # running lesson dict
        self.no = 0
        self.ver = 0
        self.msg = ""
        self.best = {}
        try:
            self.best = {int(k): v for k, v in json.load(open(SCORES, encoding="utf-8")).items()}
        except (OSError, ValueError):
            pass
        os.makedirs(OUT, exist_ok=True)
        self._key = None
        self._img = ""
        self._img_ver = 0
        self.msg_t = 0.0
        self._render_lock = threading.Lock()

    # ---- commands -------------------------------------------------------------------------------------------------
    def command(self, m):
        op = m.get("op")
        if op == "menu":
            self.menu = not self.menu
        elif op == "start":
            self.start(int(m.get("lesson", self.no or 1)))
        elif op == "restart" and self.no:
            self.start(self.no)
        elif op == "next" and self.L:
            self._advance(skipped=True)
        elif op == "stop":
            self.L, self.no, self.menu, self.msg = None, 0, False, ""

    def start(self, no):
        if not 1 <= no <= len(LESSONS):
            return
        self.no, self.menu = no, False
        self.L = LESSONS[no - 1]()
        self.L.update(i=0, held=0.0, skipped=0, t0=time.monotonic(), done=False, entered=False, final=None)
        self.msg = ""
        self.reset_fn(self.L["mode"])

    def _advance(self, skipped=False):
        L = self.L
        if L["done"]:
            if skipped:                           # N after the end -> next lesson
                self.start(self.no + 1) if self.no < len(LESSONS) else self.command({"op": "stop"})
            return
        L["skipped"] += 1 if skipped else 0
        L["i"] += 1
        L["held"] = 0.0
        L["entered"] = False
        if L["i"] >= len(L["steps"]) - 1:         # last step = "done" message
            L["done"] = True
            sc = L["score"](L) if "score" in L else 100
            sc = max(0, sc - 20 * L["skipped"])
            L["final"] = sc
            if sc > self.best.get(self.no, -1):
                self.best[self.no] = sc
                try:
                    json.dump(self.best, open(SCORES, "w", encoding="utf-8"))
                except OSError:
                    pass

    # ---- per frame ------------------------------------------------------------------------------------------------
    def update(self, s, dt):
        L = self.L
        if L and not L["done"] and not s.get("paused"):
            st = L["steps"][L["i"]]
            if not L["entered"]:
                L["entered"] = True
                if st.enter:
                    st.enter(s, L)
            if "monitor" in L:
                L["monitor"](s, L, dt)
            try:
                ok = st.check(s, L)
            except (KeyError, TypeError):
                ok = False
            if ok:
                L["held"] += dt
                if L["held"] >= st.hold:
                    self._advance()
            else:
                if L["held"] > 0.5 and st.hold >= 2:
                    self.msg, self.msg_t = "조건을 벗어나 타이머가 다시 시작됩니다", time.monotonic()
                L["held"] = 0.0
        return self.public()

    def public(self):
        L = self.L
        if self.msg and time.monotonic() - self.msg_t > 3:
            self.msg = ""
        if self.menu or not L:
            lines = ["%d. %s   %s" % (i + 1, f().get("title", "")[3:], ("최고 %d 점" % self.best[i + 1]) if i + 1 in self.best else "")
                     for i, f in enumerate(LESSONS)]
            d = dict(on=bool(self.menu), menu=True, lesson=0, title="비행 훈련 강의", step=0, n=0,
                     text="\n".join(lines), hint="숫자 1~6 = 강의 시작 · F1 = 메뉴 닫기 · F2 = 강의 끄기", prog=0.0, score=None)
        else:
            i = L["i"]
            st = L["steps"][i]
            prog = 1.0 if L["done"] else min(1.0, L["held"] / st.hold) if st.hold else 0.0
            extra = L["extra"](L) if "extra" in L else ""
            text = st.text if not L["done"] else L["steps"][-1].text + ("\n점수 %d / 100" % L["final"]) + ("\n" + extra if extra else "")
            hint = st.hint if not L["done"] else ("N = 다음 강의 · M = 다시 하기 · F1 = 메뉴")
            d = dict(on=True, menu=False, lesson=self.no, title=L["title"], step=min(i + 1, len(L["steps"]) - 1),
                     n=len(L["steps"]) - 1, text=text, hint=hint, prog=round(prog, 2), score=L["final"], done=L["done"],
                     msg=self.msg if not L["done"] else "")
        key = (d["title"], d["text"], d["hint"], d.get("msg", ""), round(d["prog"] * 10), d["step"], d["on"])
        if key != self._key:
            self._key = key
            self.ver += 1
            threading.Thread(target=self._render, args=(dict(d), self.ver), daemon=True).start()
        d["ver"] = self._img_ver
        d["img"] = self._img
        return d

    # ---- panel image (for Unreal) --------------------------------------------------------------------------------
    def _render(self, d, ver):
        try:
            from PIL import Image, ImageDraw, ImageFont
        except ImportError:
            return
        with self._render_lock:
            W, H = 1024, 512
            im = Image.new("RGB", (W, H), (8, 14, 22))
            g = ImageDraw.Draw(im)
            fb, f, fs = ImageFont.truetype(FONT_B, 44), ImageFont.truetype(FONT, 34), ImageFont.truetype(FONT, 26)
            g.rectangle([0, 0, W - 1, H - 1], outline=(60, 200, 110), width=4)
            head = d["title"] + ("" if d["menu"] else "   %d / %d" % (d["step"], d["n"]))
            g.text((28, 18), head, font=fb, fill=(120, 255, 160))
            y = 90
            for para in d["text"].split("\n"):
                for line in _wrap(g, para, f, W - 56):
                    g.text((28, y), line, font=f, fill=(235, 240, 245))
                    y += 46
            if d.get("hint"):
                y += 6
                for line in _wrap(g, d["hint"], fs, W - 56):
                    g.text((28, y), line, font=fs, fill=(150, 190, 230))
                    y += 34
            if d.get("msg"):
                g.text((28, H - 100), d["msg"], font=fs, fill=(255, 170, 90))
            if not d["menu"]:
                g.rectangle([28, H - 50, W - 28, H - 26], outline=(90, 110, 130), width=2)
                g.rectangle([30, H - 48, 30 + int((W - 60) * d["prog"]), H - 28], fill=(60, 200, 110))
                if d.get("score") is not None:
                    g.text((W - 260, 22), "점수 %d" % d["score"], font=fb, fill=(255, 220, 120))
            path = os.path.join(OUT, "tut_panel_%d.png" % (ver % 4))
            tmp = path + ".tmp.png"
            im.save(tmp)
            os.replace(tmp, path)
            if ver > self._img_ver:
                self._img, self._img_ver = path.replace("\\", "/"), ver


def _wrap(g, text, font, width):
    out, cur = [], ""
    for ch in text:
        if g.textlength(cur + ch, font=font) > width:
            cut = cur.rfind(" ")
            if cut > len(cur) // 2:
                out.append(cur[:cut]); cur = cur[cut + 1:] + ch
            else:
                out.append(cur); cur = ch
        else:
            cur += ch
    if cur:
        out.append(cur)
    return out
