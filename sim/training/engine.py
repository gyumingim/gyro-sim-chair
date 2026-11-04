"""Training engine: start menu, trainee profiles, lesson flow (briefing -> demo -> practice -> solo -> debrief),
instructor (instructions per input mode, live coaching, voice), scoring, crash handling, free flight.

Used by server.py (real time) and playtest/run.py (offline, faster than real time). Time = sim time (dt passed in),
so the bots run at any speed. Interface:
    tr = Trainer(reset_fn, voice=None, profiles_dir=...)
    tr.command(msg)                     {"cmd": "tut" | "menu" | "voice", "op": ...}
    pub = tr.update(s, dt)              per frame (dt = sim seconds advanced this frame, 0 while paused)
    tr.want_pause, tr.ctrl_override, tr.assist, tr.slow     read by the server each frame
Commands (op): tut: menu | start(lesson) | next | restart | retry | stop | mode | beginner(on) | repeat | free
               menu: open | close | up | down | select | back      voice: toggle | on | volume(v) | rate(v)
"""
import json, math, os, re, threading, time
from . import lessons as LS
from .autopilot import Autopilot

HERE = os.path.dirname(os.path.abspath(__file__))
SIM = os.path.dirname(HERE)
COACH_COOLDOWN, COACH_REPEAT, PRAISE_AFTER, PRAISE_GAP = 6.0, 12.0, 4.0, 15.0
SAMPLE_DT = 0.2
PHASE_KO = {"menu": "메뉴", "brief": "브리핑", "demo": "시범 비행", "practice": "연습", "solo": "단독 점검", "debrief": "결과", "crash": "다시 해 봐요",
            "free": "자유 비행", "idle": ""}


def grade(sc):
    return None if sc is None else "A" if sc >= 90 else "B" if sc >= 75 else "C" if sc >= 60 else "D"


# ---- trainee profiles ----------------------------------------------------------------------------------------------
class Profiles:
    def __init__(self, d):
        self.dir = d
        os.makedirs(d, exist_ok=True)
        self.cur = None

    def names(self):
        out = []
        for f in sorted(os.listdir(self.dir)):
            if f.endswith(".json"):
                try:
                    out.append(json.load(open(os.path.join(self.dir, f), encoding="utf-8"))["name"])
                except (OSError, ValueError, KeyError):
                    pass
        return out

    def _path(self, name):
        return os.path.join(self.dir, re.sub(r"[^\w가-힣-]", "_", name) + ".json")

    def load(self, name):
        try:
            p = json.load(open(self._path(name), encoding="utf-8"))
        except (OSError, ValueError):
            p = dict(name=name, created=time.strftime("%Y-%m-%d %H:%M"), lessons={},
                     settings=dict(voice=True, volume=90, rate=0, beginner=True, assist="auto", slow=False, mode="auto"))
        p.setdefault("settings", {})
        self.cur = p
        self.save()
        return p

    def new_name(self):
        n = 1
        names = set(self.names())
        while "훈련생 %d" % n in names:
            n += 1
        return "훈련생 %d" % n

    def save(self):
        if self.cur:
            tmp = self._path(self.cur["name"]) + ".tmp"
            json.dump(self.cur, open(tmp, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
            os.replace(tmp, self._path(self.cur["name"]))

    def lesson(self, i):
        return self.cur["lessons"].setdefault(str(i), dict(attempts=0, passes=0, best=None, last=None, history=[]))

    def next_lesson(self):
        for i in range(len(LS.LESSONS)):
            r = self.cur["lessons"].get(str(i))
            if not r or not r.get("passes"):
                return i
        return len(LS.LESSONS) - 1


class Trainer:
    def __init__(self, reset_fn, voice=None, profiles_dir=None, render=True):
        self.reset_fn = reset_fn
        self.voice = voice
        self.render_on = render
        self.prof = Profiles(profiles_dir or os.path.join(SIM, "profiles"))
        names = self.prof.names()
        self.prof.load(names[0] if names else self.prof.new_name())
        st = self.prof.cur["settings"]
        self.beginner = st.get("beginner", True)
        self.mode_force = None if st.get("mode", "auto") == "auto" else st["mode"]
        self.assist_set = st.get("assist", "auto")           # auto | on | off
        self.slow_set = bool(st.get("slow", False))
        if voice:
            voice.on = st.get("voice", True)
            voice.set_params(st.get("volume", 90), st.get("rate", 0)) if hasattr(voice, "set_params") else None
        self.mode = "kbd"
        self.phase = "menu"
        self.menu = dict(page="main", sel=0, stack=[])
        self.L = None
        self.ap = Autopilot()
        self.clock = 0.0                     # seconds since start (sim time)
        self.coach, self.coach_t, self.coach_kind = "", -1e9, ""
        self.said, self.say_n, self.spoken = {}, 0, ""
        self.log = []                        # (clock, kind, text) for playtests
        self.targets, self.ok_since = [], None
        self.want_pause, self.ctrl_override, self.assist, self.slow = True, None, False, False
        self.s = {}
        self.ver, self._key, self._img, self._line, self._img_ver = 0, None, "", "", 0
        self._render_lock = threading.Lock()
        self.msg, self.msg_t = "", -1e9
        self.crash = None
        self.debrief = None
        self._say("안녕하세요, %s 님. 메뉴에서 이어서 하기를 고르면 바로 시작해요." % self.prof.cur["name"], force=True)

    # =================================================================================================================
    # commands
    def command(self, m):
        cmd, op = m.get("cmd"), m.get("op")
        if cmd == "voice":
            self._voice_cmd(op, m)
            return
        if cmd == "menu":
            self._menu_cmd(op)
            return
        if op == "menu":
            self._menu_cmd("close" if self.phase == "menu" else "open")
        elif op == "start":
            self.start(int(m.get("lesson", 0)))
        elif op == "free":
            self.free_flight()
        elif op == "stop":
            self.stop()
        elif op == "repeat":
            self._say(self.spoken or self._current_text(), force=True)
        elif op == "mode":                   # auto -> kbd -> rig -> auto
            self.mode_force = {None: "kbd", "kbd": "rig", "rig": None}[self.mode_force]
            self.prof.cur["settings"]["mode"] = self.mode_force or "auto"
            self.prof.save()
            self._key = None
        elif op == "beginner":
            self.beginner = (not self.beginner) if "on" not in m else bool(m["on"])
            self.prof.cur["settings"]["beginner"] = self.beginner
            self.prof.save()
            self._key = None
        elif op == "assist":
            self.assist_set = m.get("value") or {"auto": "on", "on": "off", "off": "auto"}[self.assist_set]
            self.prof.cur["settings"]["assist"] = self.assist_set
            self.prof.save()
        elif op == "slow":
            self.slow_set = (not self.slow_set) if "on" not in m else bool(m["on"])
            self.prof.cur["settings"]["slow"] = self.slow_set
            self.prof.save()
        elif op in ("next", "select"):
            self._next()
        elif op in ("restart", "retry"):
            self._retry()
        elif op == "end" and self.L and self.phase in ("practice", "solo", "demo"):   # tests / instructor: straight to the debrief
            self._begin_phase("debrief")

    def _voice_cmd(self, op, m):
        v, st = self.voice, self.prof.cur["settings"]
        if op == "toggle" or op == "on":
            on = (not st.get("voice", True)) if op == "toggle" else bool(m.get("on", True))
            st["voice"] = on
            if v:
                v.on = on
                if not on:
                    v.say_now("")
        elif op == "volume":
            st["volume"] = max(0, min(100, int(m.get("value", 90))))
        elif op == "rate":
            st["rate"] = max(-5, min(5, int(m.get("value", 0))))
        if v and hasattr(v, "set_params"):
            v.set_params(st.get("volume", 90), st.get("rate", 0))
        self.prof.save()
        self._key = None

    # ---- menu ---------------------------------------------------------------------------------------------------------
    def menu_items(self):
        pg = self.menu["page"]
        st = self.prof.cur["settings"]
        if pg == "main":
            nl = self.prof.next_lesson()
            return [("continue", "이어서 하기: %s" % LS.lesson(nl)["title"]), ("lessons", "강의 고르기"), ("free", "자유 비행 (교관 없음)"),
                    ("trainee", "훈련생: %s" % self.prof.cur["name"]), ("settings", "설정"), ("close", "닫기")]
        if pg == "lessons":
            out = []
            for i in range(len(LS.LESSONS)):
                d = LS.lesson(i)
                r = self.prof.cur["lessons"].get(str(i)) or {}
                mark = ("  ✓ 최고 %d" % r["best"]) if r.get("passes") else (("  최고 %d" % r["best"]) if r.get("best") is not None else "")
                out.append(("lesson:%d" % i, "%s — %s%s" % (d["title"], d["short"], mark)))
            return out + [("back", "뒤로")]
        if pg == "trainee":
            return [("pick:" + n, ("▶ " if n == self.prof.cur["name"] else "") + n) for n in self.prof.names()] + [("newtrainee", "새 훈련생 만들기"),
                                                                                                                  ("back", "뒤로")]
        if pg == "settings":
            vok = bool(self.voice and self.voice.ok)
            return [("voice", "교관 목소리: %s" % (("켬" if st.get("voice", True) else "끔") if vok else "없음 (한국어 음성 미설치)")),
                    ("volume", "목소리 크기: %d" % st.get("volume", 90)), ("rate", "말 빠르기: %s" % {-2: "느림", 0: "보통", 2: "빠름"}.get(st.get("rate", 0), st.get("rate", 0))),
                    ("beginner", "초보자 설명: %s" % ("켬" if self.beginner else "끔")),
                    ("assist", "쉬운 모드 (자세 보조): %s" % {"auto": "자동 (처음 두 번)", "on": "켬", "off": "끔"}[self.assist_set]),
                    ("slow", "느린 시간 (0.5배): %s" % ("켬" if self.slow_set else "끔")),
                    ("mode", "안내 방식: %s" % {None: "자동", "kbd": "키보드", "rig": "조종 장치"}[self.mode_force]), ("back", "뒤로")]
        return [("back", "뒤로")]

    def _menu_cmd(self, op):
        if op == "open":
            if self.phase != "menu":
                self.menu.update(page="main", sel=0, stack=[], ret=self.phase)
                self.phase = "menu"
                self._say("메뉴예요. 위아래로 고르고, 엔터나 트리거로 선택하세요.", force=True)
            return
        if self.phase != "menu":
            return
        items = self.menu_items()
        if op == "close":
            ret = self.menu.get("ret")
            self.phase = ret if ret not in (None, "menu") else ("free" if not self.L else "practice")
            if self.phase == "free" and not self.L:
                self.free_flight()
            return
        if op == "up":
            self.menu["sel"] = (self.menu["sel"] - 1) % len(items)
        elif op == "down":
            self.menu["sel"] = (self.menu["sel"] + 1) % len(items)
        elif op == "back":
            if self.menu["stack"]:
                self.menu["page"], self.menu["sel"] = self.menu["stack"].pop()
            else:
                self._menu_cmd("close")
            return
        elif op == "select":
            key = items[self.menu["sel"] % len(items)][0]
            self._menu_select(key)
            return
        self._say(items[self.menu["sel"]][1], force=True)

    def _menu_select(self, key):
        st = self.prof.cur["settings"]
        go = lambda pg: (self.menu["stack"].append((self.menu["page"], self.menu["sel"])), self.menu.update(page=pg, sel=0))
        if key == "continue":
            self.start(self.prof.next_lesson())
        elif key in ("lessons", "trainee", "settings"):
            go(key)
            self._say({"lessons": "강의를 고르세요.", "trainee": "훈련생을 고르세요.", "settings": "설정이에요."}[key], force=True)
        elif key == "free":
            self.free_flight()
        elif key == "close":
            self._menu_cmd("close")
        elif key == "back":
            self._menu_cmd("back")
        elif key.startswith("lesson:"):
            self.start(int(key[7:]))
        elif key.startswith("pick:"):
            self.prof.load(key[5:])
            self.__init_settings_from_profile()
            self._say("%s 님으로 바꿨어요." % key[5:], force=True)
        elif key == "newtrainee":
            n = self.prof.new_name()
            self.prof.load(n)
            self.__init_settings_from_profile()
            self._say("새 훈련생 %s 을 만들었어요." % n, force=True)
        elif key == "voice":
            self._voice_cmd("toggle", {})
        elif key == "volume":
            self._voice_cmd("volume", {"value": {100: 40, 40: 60, 60: 80, 80: 100}.get(st.get("volume", 90), 100)})
            self._say("목소리 크기 %d" % st["volume"], force=True)
        elif key == "rate":
            self._voice_cmd("rate", {"value": {0: 2, 2: -2, -2: 0}.get(st.get("rate", 0), 0)})
            self._say("이 빠르기로 말할게요.", force=True)
        elif key in ("beginner", "assist", "slow", "mode"):
            self.command({"cmd": "tut", "op": key})
        self._key = None

    def __init_settings_from_profile(self):
        st = self.prof.cur["settings"]
        self.beginner = st.get("beginner", True)
        self.mode_force = None if st.get("mode", "auto") == "auto" else st["mode"]
        self.assist_set = st.get("assist", "auto")
        self.slow_set = bool(st.get("slow", False))
        if self.voice:
            self.voice.on = st.get("voice", True)
            if hasattr(self.voice, "set_params"):
                self.voice.set_params(st.get("volume", 90), st.get("rate", 0))

    # =================================================================================================================
    # lesson flow
    def start(self, i):
        if not 0 <= i < len(LS.LESSONS):
            return
        d = LS.lesson(i)
        rec = self.prof.lesson(i)
        self.L = dict(d=d, i=i, page=0, seg=0, step=0, held=0.0, entered=False, t_phase=0.0, t_step=0.0, t_in=0.0, tasks=[], samples=[],
                      vars={}, timeout_said=False, attempt=rec["attempts"] + 1)
        self.crash, self.debrief = None, None
        self.phase = "brief"
        self.reset_fn(d["mode"])
        self.ap.reset()
        self._enter_brief_page()

    def stop(self):
        self.L, self.phase, self.crash, self.debrief = None, "menu", None, None
        self.menu.update(page="main", sel=0, stack=[], ret=None)
        self.coach = ""

    def free_flight(self):
        self.L, self.crash, self.debrief = None, None, None
        self.phase = "free"
        self.reset_fn("air")
        self._say("자유 비행이에요. 교관은 쉬어요. F1 을 누르면 메뉴로 돌아가요.", force=True)

    def _nk(self, josa="을"):
        """the 'next' key in the current input mode, with its particle."""
        if not josa:
            return "트리거" if self.mode == "rig" else "N"
        return ("트리거" + ("를" if josa == "을" else "나")) if self.mode == "rig" else ("N " + josa)

    def allow_reset(self):
        """R / T during a lesson: the first press asks, the second (within 4 s) ends the lesson and resets."""
        if not self.L or self.phase in ("free", "idle", "debrief"):     # the F1 menu opened mid-lesson still asks
            if self.phase == "debrief":
                self.L, self.phase, self.debrief = None, "free", None
            return True
        if time.monotonic() - getattr(self, "_rst_t", -1e9) < 4.0:
            self._rst_t = -1e9
            self.L, self.crash, self.debrief = None, None, None
            self.phase = "free"
            self._say("강의를 끝냈어요. 자유 비행이에요. F1 을 누르면 메뉴로 돌아가요.", force=True)
            return True
        self._rst_t = time.monotonic()
        self.msg, self.msg_t = "한 번 더 누르면 강의를 끝내요", time.monotonic()
        self._say("한 번 더 누르면 강의를 끝내고 자유 비행으로 새로 시작해요.", force=True)
        return False

    def _brief_pages(self):
        d = self.L["d"]
        pages = list(d["brief"])
        a = self._assist_on()
        pages.append(("이번에는 쉬운 모드가 켜져 있어요. 비행기가 너무 많이 기울거나 들리지 않게 컴퓨터가 잡아 줘요. " if a else "")
                     + ("시범 비행 다음에 연습, 그다음 혼자 하는 단독 점검이에요. " if d["solo"] else "연습만 하면 돼요. ")
                     + "준비되면 %s 누르세요." % self._nk())
        return pages

    def _enter_brief_page(self):
        p = self._brief_pages()[self.L["page"]]
        self._say(p, force=True)

    def _assist_on(self):
        if self.L and not self.L["d"].get("assist", True):      # lesson turns the easy mode off (G / aerobatics)
            return False
        if self.assist_set == "on":
            return True
        if self.assist_set == "off" or not self.L:
            return False
        return self.L["attempt"] <= 2 and self.L["i"] >= 1

    def _next(self):
        """N / trigger: continue (briefing page, demo skip, practice skip, debrief -> next lesson, crash -> retry)."""
        if self.phase == "menu":
            self._menu_cmd("select")
            return
        L = self.L
        if not L:
            return
        if self.phase == "brief":
            L["page"] += 1
            if L["page"] >= len(self._brief_pages()):
                self._begin_phase("demo" if L["d"]["demo"] else "practice")
            else:
                self._enter_brief_page()
        elif self.phase == "demo":
            self._begin_phase("practice")
        elif self.phase == "practice":
            self._advance(skipped=True)
        elif self.phase == "solo":
            if time.monotonic() - getattr(self, "_skip_t", -1e9) < 4.0:      # wall time: the sim clock stops when paused
                self._skip_t = -1e9
                self._advance(skipped=True)
            else:
                self._skip_t = time.monotonic()
                self.msg, self.msg_t = "건너뛰려면 한 번 더 (이 단계 0 점)", time.monotonic()
                self._say("단독 점검 단계를 건너뛰려면 한 번 더 누르세요. 이 단계는 0 점이 돼요.", force=True)
        elif self.phase == "debrief":
            dbf = self.debrief or {}
            if dbf.get("passed") and L["i"] + 1 < len(LS.LESSONS):
                self.start(L["i"] + 1)
            elif dbf.get("passed"):
                self.stop()
            else:
                self._retry()
        elif self.phase == "crash":
            self._retry()

    def _retry(self):
        """M: debrief -> solo again; crash -> the phase again from where it makes sense; otherwise restart the lesson."""
        L = self.L
        if not L:
            return
        if self.phase == "debrief" and L["d"]["solo"]:
            self._begin_phase("solo")
        elif self.phase == "crash" and self.crash:
            ph, step = self.crash["phase"], self.crash["step"]
            self.crash = None
            # air lessons: the same step again (the start state fits); runway / approach / pattern: the phase from the start
            same = ph == "practice" and L["d"]["mode"] in ("air", "air_high")
            self._begin_phase(ph, step=step if same else 0)
        else:
            self.start(L["i"])

    def _begin_phase(self, ph, step=0):
        L = self.L
        d = L["d"]
        self.phase = ph
        L.update(step=step, held=0.0, entered=False, t_phase=0.0, t_step=0.0, t_in=0.0, seg=0, timeout_said=False)
        self.ap.reset()
        self.coach = ""
        if ph in ("demo", "practice", "solo"):
            self.reset_fn(d["mode"])
            L["vars"] = {}
        if ph == "demo":
            self._say("시범 비행이에요. 제가 조종할 테니 스틱과 스로틀이 어떻게 움직이는지 보세요. 건너뛰려면 %s." % self._nk(""), force=True)
            L["seg_t"] = 0.0
            L["seg_said"] = False
        elif ph == "practice":
            self._say("이제 직접 해 봐요. 제가 옆에서 알려 줄게요.", force=True) if step == 0 else None
        elif ph == "solo":
            L["tasks"], L["samples"] = [], []
            self._say("단독 점검이에요. 이번엔 혼자 해 보세요. 저는 조용히 볼게요.", force=True)
            rec = self.prof.lesson(L["i"])
            rec["attempts"] += 1
            L["attempt"] = rec["attempts"]
            self.prof.save()
        elif ph == "debrief":
            self._make_debrief()

    def _steps(self):
        L = self.L
        return L["d"]["practice"] if self.phase == "practice" else L["d"]["solo"]

    def _advance(self, skipped=False, failed=False):
        L = self.L
        steps = self._steps()
        st = steps[L["step"]]
        if self.phase == "solo":
            self._close_task(st, skipped=skipped, failed=failed)
        L["step"] += 1
        L.update(held=0.0, entered=False, t_step=0.0, t_in=0.0, timeout_said=False)
        self.ok_since = None
        if L["step"] >= len(steps):
            if self.phase == "practice":
                if L["d"]["solo"]:
                    self._say("연습 끝! 잘했어요.", force=True)
                    self._begin_phase("solo")
                else:
                    self._begin_phase("debrief")
            else:
                self._begin_phase("debrief")

    # ---- solo scoring ----------------------------------------------------------------------------------------------
    def _close_task(self, st, skipped=False, failed=False):
        L = self.L
        t = L.get("task") or {}
        done = not skipped and not failed
        cap = t.get("t_cap", 0.0)
        intol = (t.get("t_in_cap", 0.0) / cap) if cap > 0.2 else (1.0 if done and not st.targets else 0.0)
        sc = 0 if not done else (60 + 40 * intol) if st.targets else 100
        L["tasks"].append(dict(text=st.text, done=done, skipped=skipped, failed=failed, intol=round(100 * intol), score=round(sc),
                               maxdev={k: round(v, 1) for k, v in t.get("maxdev", {}).items()}, t=round(L["t_step"], 1),
                               names=[x.name for x in st.targets], tols={x.name: x.tol for x in st.targets},
                               units={x.name: {"FT": "ft", "DEG": "°", "FPM": "fpm", "KT": "kt", "M": "m", "%": "%", "G": "G"}.get(x.unit, "") for x in st.targets}))
        L["task"] = None

    def _track_task(self, st, dt, all_ok):
        L = self.L
        t = L.setdefault("task", None) or {}
        if not L.get("task"):
            L["task"] = t
        if all_ok:
            t["cap"] = True
        if t.get("cap") or st.duration:
            t["t_cap"] = t.get("t_cap", 0.0) + dt
            if all_ok:
                t["t_in_cap"] = t.get("t_in_cap", 0.0) + dt
            md = t.setdefault("maxdev", {})
            for x in self.targets:
                md[x["name"]] = max(md.get(x["name"], 0.0), abs(x["dev"]))

    def _make_debrief(self):
        L = self.L
        d = L["d"]
        tasks = L["tasks"]
        if not d["solo"]:
            score, passed = 100, True
            good, fix = ["조종 장치와 계기를 모두 익혔어요."], []
        else:
            base = sum(t["score"] for t in tasks) / max(1, len(tasks))
            pen = d["penalties"](L["vars"]) if "penalties" in d else 0
            score = int(max(0, min(100, round(base - pen))))
            passed = score >= d["pass_score"] and all(t["done"] for t in tasks)
            good, fix = [], []
            for t in tasks:
                if not t["done"]:
                    fix.append("'%s' 단계는 %s" % (t["text"], "건너뛰었어요 (-점수)" if t["skipped"] else "시간 안에 못 했어요. 연습에서 다시 해 봐요"))
                    continue
                for n in t["names"]:
                    ko = LS.NAME_KO.get(n, n)
                    md = t["maxdev"].get(n)
                    if t["intol"] >= 80:
                        good.append("%s: %s%s 잘 지켰어요 (범위 안 %d%%)" % (t["text"], ko, _obj(ko), t["intol"]))
                        break
                    elif md is not None and md > t["tols"][n]:
                        fix.append("%s: %s%s 최대 %s %s 벗어났어요 (허용 ±%s). 작게, 일찍 고치기" % (t["text"], ko, _subj(ko), _fmt(md), t.get("units", {}).get(n, ""), _fmt(t["tols"][n])))
            if "penalty_text" in d:
                fix += d["penalty_text"](L["vars"])
            if not fix:
                good.append("모든 점검을 깔끔하게 끝냈어요")
        rec = self.prof.lesson(L["i"])
        rec["last"] = score
        rec["best"] = score if rec["best"] is None else max(rec["best"], score)
        if passed:
            rec["passes"] += 1
        rec["history"] = (rec["history"] + [dict(ts=time.strftime("%Y-%m-%d %H:%M"), score=score, passed=passed, assist=self._assist_on())])[-20:]
        self.prof.save()
        key = d["key"]
        graph = [(round(t, 1), v) for t, v in L["samples"]]
        tol = next((x.tol for st in d["solo"] for x in st.targets if x.name == key), None)
        self.debrief = dict(score=score, grade=grade(score), passed=passed, pass_score=d["pass_score"], good=good[:4], fix=fix[:4], tasks=tasks,
                            key=key, key_ko=LS.NAME_KO.get(key, key), tol=tol, graph=graph[-300:], assist=self._assist_on())
        nxt = ("%s 누르면 다음 강의로 가요." % self._nk() if L["i"] + 1 < len(LS.LESSONS) else "모든 강의를 마쳤어요!") if passed else "%s M 으로 단독 점검을 다시 해요." % self._nk("이나")
        say = ("통과! " if passed else "아쉬워요, 이번엔 통과 점수 %d 에 못 미쳤어요. " % d["pass_score"]) + ("점수 %d 점, %s 등급. " % (score, grade(score)) if d["solo"] else "")
        if good:
            say += "잘한 점: " + good[0] + ". "
        if fix:
            say += "고칠 점: " + fix[0] + ". "
        self._say(say + nxt, force=True)

    # =================================================================================================================
    # instructor
    def _instr(self, st):
        v = st.rig if self.mode == "rig" else st.kbd
        if callable(v):                       # live-value text: evaluated once per step entry / mode change
            L = self.L
            key = (self.phase, L["step"], self.mode)
            if L.get("_ik") == key:
                return L["_it"]
            try:
                t = v(self.s, L["vars"])
            except (KeyError, TypeError, ValueError):
                t = st.text
            L["_ik"], L["_it"] = key, t
            return t
        return v

    def _current_text(self):
        if self.phase == "brief" and self.L:
            return self._brief_pages()[self.L["page"]]
        if self.phase in ("practice", "solo") and self.L:
            return self._instr(self._steps()[self.L["step"]])
        if self.phase == "crash" and self.crash:
            return self.crash["say"]
        return ""

    def _say(self, text, force=False):
        if not text:
            return
        if not force and self.clock - self.said.get(text, -1e9) < COACH_REPEAT:
            return
        self.said[text] = self.clock
        self.say_n += 1
        self.spoken = text
        self.log.append((round(self.clock, 1), self.phase, text))
        if len(self.log) > 2000:
            del self.log[:500]
        if self.voice:
            self.voice.say(text)

    def _set_coach(self, text, kind):
        self.coach, self.coach_t, self.coach_kind = text, self.clock, kind
        self._say(text)

    def _eval_targets(self, s, st):
        Lv = self.L["vars"]
        self.targets = []
        all_ok = bool(st.targets)
        worst = None
        for t in st.targets:
            try:
                v = float(t.value(s, Lv))
                tg = float(t.tgt(Lv))
            except (KeyError, TypeError, ValueError):
                continue
            dev = LS.hdg_err(v, tg) if t.name == "HDG" else v - tg
            ad = abs(dev)
            stt = 0 if ad <= t.tol else 1 if ad <= 2 * t.tol else 2
            self.targets.append(dict(name=t.name, ko=LS.NAME_KO.get(t.name, t.name), unit=t.unit, val=round(v, 2), tgt=round(tg, 2), tol=t.tol,
                                     dev=round(dev, 2), st=stt, txt=(t.fmt % v), ttxt=(t.fmt % tg)))
            all_ok = all_ok and stt == 0
            if t.coach and stt > 0 and ad < t.band * t.tol:
                sev = ad / t.tol
                if worst is None or sev > worst[0]:
                    worst = (sev, t, v, tg, dev)
        return all_ok, worst

    def _coach_step(self, st, all_ok, worst):
        # wrong direction: deviation beyond tolerance and growing fast -> say so at once (short cooldown, any band)
        L = self.L
        prev = L.setdefault("_dev_hist", {})
        if self.phase == "practice" and L["t_step"] > 1.0 and self.clock - self.coach_t > 2.0:
            for t, x in zip(st.targets, self.targets):
                if not t.coach:
                    continue
                ad = abs(x["dev"])
                p = prev.get(x["name"])
                if p is not None and ad > t.tol and ad - p[1] > 0.5 * t.tol and self.clock - p[0] <= 1.05:
                    how = (LS.INC if x["dev"] < 0 else LS.DEC).get(x["name"])
                    if how:
                        self._set_coach("반대 방향이에요 — %s" % (how[1] if self.mode == "rig" else how[0]), "fix")
                        prev.clear()
                        break
        for x in self.targets:
            p = prev.get(x["name"])
            if p is None or self.clock - p[0] >= 1.0:
                prev[x["name"]] = (self.clock, abs(x["dev"]))
        if all_ok:
            self.ok_since = self.ok_since if self.ok_since is not None else self.clock
        else:
            self.ok_since = None
        if self.phase != "practice" or self.clock - self.coach_t < COACH_COOLDOWN:
            return
        if worst is not None and worst[0] > 1.3:
            sev, t, v, tg, dev = worst
            how = (LS.INC if dev < 0 else LS.DEC).get(t.name)
            if how:
                self._set_coach("%s — %s" % (LS.problem(t.name, v, tg, dev), how[1] if self.mode == "rig" else how[0]), "fix")
        elif self.ok_since is not None and self.clock - self.ok_since > PRAISE_AFTER and self.clock - self.coach_t > PRAISE_GAP \
                and any(t.coach for t in st.targets):
            self._set_coach("좋아요, 그대로 유지하세요", "good")

    # ---- crash / failure ---------------------------------------------------------------------------------------------
    def _check_crash(self, s):
        d = self.L["d"] if self.L else None
        vs, why, say = s.get("vs_fpm", 0.0), None, None
        on_rwy = abs(s.get("cross_m", 0)) < 24 and -100 < s.get("along_m", 0) < 2750      # 06R: 2744 x 45 m
        if s.get("wow") and vs < -1500:
            why, say = "너무 세게 땅에 닿았어요", "강하율 %.0f fpm 으로 땅에 닿았어요. 다음엔 R 50 (땅까지 50 ft) 에서 스틱을 살짝 당겨 강하를 300 fpm 아래로 줄여요." % -vs
        elif s.get("wow") and abs(s.get("phi", 0)) > 25:
            why, say = "날개가 땅에 닿았어요", "기운 채로 땅에 닿았어요. 접지 전에는 날개를 수평으로 맞춰요."
        elif s.get("wow") and s.get("kts", 0) > 50 and not on_rwy:
            why, say = "활주로 밖으로 나갔어요", "활주로를 벗어났어요. 활주 중에는 페달을 작게, 일찍 써서 가운데 선을 따라가요."
        elif s.get("nz", 1.0) > 10.0 or s.get("nz", 1.0) < -3.5:
            why, say = "기체가 견디는 G 를 넘었어요", "G 가 %.1f 까지 갔어요. F-16 한계는 +9G, -3G 예요. 스틱을 부드럽게." % s["nz"]
        elif d and d["mode"] in ("air", "air_high") and s.get("agl_m", 999) < 300 and not s.get("wow"):
            why, say = "너무 낮게 내려왔어요", "땅에서 %d ft 까지 내려왔어요. 공중 연습은 안전 고도 1000 ft 위에서 해요. 기수를 조금씩만 내려요." % (s["agl_m"] / 0.3048)
        elif s.get("crashed"):
            why, say = "지형에 부딪혔어요", "산이나 땅에 부딪혔어요. 고도를 충분히 지켜요."
        return (why, say) if why else None

    # =================================================================================================================
    def update(self, s, dt):
        self.s = s
        self.clock += dt if dt > 0 else 1 / 60.0 * 0.0
        mode = self.mode_force or ("rig" if (s.get("joystick") or s.get("hmd")) else "kbd")
        if mode != self.mode:
            self.mode = mode
            self._key = None
            if self.L and self.phase in ("practice", "solo"):
                self._say(self._instr(self._steps()[self.L["step"]]), force=True)
        self.ctrl_override = None
        L = self.L
        ph = self.phase
        self.assist = self._assist_on() and ph in ("practice", "solo")
        self.slow = self.slow_set and ph in ("practice", "solo")
        self.want_pause = ph in ("menu", "brief", "debrief", "crash")
        if ph == "demo" and L:
            self._demo(s, dt)
        elif ph in ("practice", "solo") and L and not s.get("paused") and dt > 0:
            self._fly(s, dt)
        elif ph == "free":
            self.targets = []
        return self.public()

    def _demo(self, s, dt):
        L = self.L
        segs = L["d"]["demo"]
        if L["seg"] >= len(segs):
            self._say("시범 끝. 이제 직접 해 볼게요.", force=True)
            self._begin_phase("practice")
            return
        sg = segs[L["seg"]]
        if not L["seg_said"]:
            L["seg_said"] = True
            self._say(sg.say, force=True)
        self.ctrl_override = self.ap.update(s, sg.goal(s, L["vars"]), dt)
        L["seg_t"] += dt
        if (sg.dur and L["seg_t"] >= sg.dur) or (sg.until and sg.until(s, L["vars"])):
            L["seg"] += 1
            L["seg_t"], L["seg_said"] = 0.0, False

    def _fly(self, s, dt):
        L = self.L
        steps = self._steps()
        if L["step"] >= len(steps):
            return
        st = steps[L["step"]]
        while st.beginner and not self.beginner:
            L["step"] += 1
            if L["step"] >= len(steps):
                self._advance()
                return
            st = steps[L["step"]]
        L["t_phase"] += dt
        if not L["entered"]:
            L["entered"] = True
            if st.enter:
                st.enter(s, L["vars"])
            self.coach, self.coach_t = "", self.clock
            self._say(self._instr(st), force=True)
        c = self._check_crash(s)
        if c:
            self.crash = dict(why=c[0], say=c[1], phase=self.phase, step=L["step"],
                              state={k: round(float(s.get(k, 0)), 1) for k in ("kts", "along_m", "cross_m", "agl_m", "vs_fpm", "theta", "phi", "nz")})
            self.log.append((round(self.clock, 1), "crash_state", json.dumps(self.crash["state"])))
            self.phase = "crash"
            self.want_pause = True
            self._say("괜찮아요. %s. %s M 이나 %s 누르면 다시 해요." % (c[0], c[1], self._nk()), force=True)
            return
        if "monitor" in L["d"]:
            L["d"]["monitor"](s, L["vars"], dt)
        if st.monitor:
            st.monitor(s, L["vars"], dt)
        all_ok, worst = self._eval_targets(s, st)
        self._coach_step(st, all_ok, worst)
        L["t_step"] += dt
        if all_ok:
            L["t_in"] += dt
        if self.phase == "solo":
            self._track_task(st, dt, all_ok)
            L["_sample_t"] = L.get("_sample_t", 0.0) + dt
            if L["_sample_t"] >= SAMPLE_DT:
                L["_sample_t"] = 0.0
                k = next((x for x in self.targets if x["name"] == L["d"]["key"]), None)
                if k:
                    L["samples"].append((L["t_phase"], k["dev"]))
        if st.duration:
            if L["t_step"] >= st.duration:
                self._advance()
            return
        try:
            ok = st.check(s, L["vars"])
        except (KeyError, TypeError, ValueError):
            ok = False
        if ok:
            L["held"] += dt
            if L["held"] >= st.hold:
                if self.phase == "practice" and st.targets and L["held"] > 1.0:
                    self._say("좋아요!", force=False)
                self._advance()
                return
        else:
            if L["held"] > 0.5 and st.hold >= 2:
                self.msg, self.msg_t = "조건을 벗어나 타이머가 다시 시작돼요", time.monotonic()
            L["held"] = 0.0
        if st.timeout and L["t_step"] > st.timeout:
            if self.phase == "solo":
                self._advance(failed=True)
            elif not L["timeout_said"]:
                L["timeout_said"] = True
                self._set_coach(("어려우면 괜찮아요. 힌트: %s. %s 누르면 넘어가요." % (st.hint, self._nk())) if st.hint else "어려우면 %s 눌러 넘어가도 돼요." % self._nk(), "fix")

    # =================================================================================================================
    def public(self):
        L = self.L
        ph = self.phase
        coach = self.coach if self.clock - self.coach_t < 8 else ""
        msg = self.msg if time.monotonic() - self.msg_t < 3 else ""          # wall time: also shown while paused
        d = dict(on=ph != "idle", phase=ph, phase_ko=PHASE_KO.get(ph, ""), menu=ph == "menu", trainee=self.prof.cur["name"], mode=self.mode,
                 mode_auto=self.mode_force is None, beginner=self.beginner, assist=self.assist, slow=self.slow,
                 voice=bool(self.voice and self.voice.ok and self.voice.on), voice_ok=bool(self.voice and self.voice.ok), say_n=self.say_n,
                 spoken=self.spoken, coach=coach, coach_kind=self.coach_kind if coach else "", msg=msg, targets=self.targets if ph in ("practice", "solo") else [])
        d.update(lesson=-1, title="", step=0, n=0, text="", instr="", hint="", prog=0.0, score=None)
        if ph == "menu":
            items = self.menu_items()
            d.update(title={"main": "메뉴", "lessons": "강의 고르기", "trainee": "훈련생", "settings": "설정"}[self.menu["page"]],
                     items=[t for _, t in items], sel=self.menu["sel"] % len(items))
        if L:
            dd = L["d"]
            d.update(lesson=L["i"], title=dd["title"], attempt=L["attempt"])
            if ph == "brief":
                pages = self._brief_pages()
                d.update(text=pages[L["page"]], step=L["page"] + 1, n=len(pages), instr="")
            elif ph == "demo":
                segs = dd["demo"]
                sg = segs[min(L["seg"], len(segs) - 1)] if segs else None
                d.update(text=sg.say if sg else "", step=L["seg"] + 1, n=len(segs), prog=min(1.0, L["seg_t"] / sg.dur) if sg and sg.dur else 0.0)
            elif ph in ("practice", "solo"):
                steps = self._steps()
                vis = [x for x in steps if self.beginner or not x.beginner]
                st = steps[min(L["step"], len(steps) - 1)]
                prog = min(1.0, L["t_step"] / st.duration) if st.duration else (min(1.0, L["held"] / st.hold) if st.hold else 0.0)
                d.update(text=st.text, instr=self._instr(st), hint=st.hint if ph == "practice" else "", prog=round(prog, 2),
                         step=(vis.index(st) + 1) if st in vis else L["step"] + 1, n=len(vis),
                         intol=round(100 * L["t_in"] / L["t_step"]) if (L["t_step"] > 0 and st.targets) else None,
                         t=round(L["t_phase"], 1), timeout=st.timeout, t_step=round(L["t_step"], 1),
                         tasks=[dict(text=t["text"], done=t["done"], score=t["score"]) for t in L["tasks"]] if ph == "solo" else [])
                if ph == "solo":
                    done = L["tasks"]
                    d["live_score"] = round(sum(t["score"] for t in done) / len(done)) if done else None
                    d["grade"] = grade(d["live_score"])
            elif ph == "debrief":
                d.update(debrief=self.debrief, score=self.debrief["score"] if self.debrief else None,
                         text="통과!" if self.debrief and self.debrief["passed"] else "다시 해 봐요")
            elif ph == "crash" and self.crash:
                d.update(crash=dict(why=self.crash["why"], say=self.crash["say"]), text=self.crash["why"], instr=self.crash["say"])
            rec = self.prof.cur["lessons"].get(str(L["i"])) or {}
            d["best"] = rec.get("best")
        d["lessons_passed"] = sum(1 for r in self.prof.cur["lessons"].values() if r.get("passes"))
        d["lessons_total"] = len(LS.LESSONS)
        key = (ph, d["title"], d["text"], d["instr"], d.get("hint"), msg, coach, round(d["prog"] * 10), d["step"], self.mode, self.beginner,
               d.get("live_score"), d.get("sel"), tuple(d.get("items") or ()), d.get("score"), d["voice"])
        if self.render_on and key != self._key:
            self._key = key
            self.ver += 1
            from .render import render_panel
            threading.Thread(target=self._render, args=(render_panel, dict(d), self.ver), daemon=True).start()
        d["ver"], d["img"], d["line_img"] = self._img_ver, self._img, self._line
        return d

    def _render(self, fn, d, ver):
        with self._render_lock:
            try:
                p, l = fn(d, ver)
            except Exception as e:                  # never let a drawing problem stop the lesson
                print("training: render failed", repr(e), flush=True)
                return
            if ver > self._img_ver:
                self._img, self._line, self._img_ver = p, l, ver


def _has_batchim(w):
    c = (w or " ").strip()[-1:]
    if "가" <= c <= "힣":
        return (ord(c) - 0xAC00) % 28 != 0
    return c in "LMNRlmnr0136789"          # G, ALT, ... read in Korean: rough rule for letters / digits


def _obj(w):
    return "을" if _has_batchim(w) else "를"


def _subj(w):
    return "이" if _has_batchim(w) else "가"


def _fmt(v):
    return ("%.0f" % v) if abs(v) >= 10 else ("%.1f" % v)
