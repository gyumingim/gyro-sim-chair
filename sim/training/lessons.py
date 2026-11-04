"""Curriculum: 11 lessons from zero to landing (+ optional G / basic aerobatics), Korean, for a beginner alone.

Every lesson: briefing pages (what and why) -> demo (autopilot flies it, the stick / throttle move in the cockpit)
-> guided practice (instructor coaches) -> solo check (instructor quiet, scored) -> debrief (score, good / fix,
key graph). Pass = solo score >= PASS (70) unless the lesson says otherwise.

Step(text, check, hold, ...):
  text      short context line (what the step is)
  kbd / rig instructor instruction: keyboard keys / physical rig (left hand throttle, right hand centre stick, feet on
            the pedals, toe brakes). str or fn(s, L) -> str (live values, evaluated once at step entry)
  check     fn(s, L) -> bool, held for `hold` s in a row (sim time) completes the step
  targets   [T(...)] what to hold: shown live (value, deviation, colour), coached, scored
  goal      fn(s, L) -> autopilot goal (training/autopilot.py): flies the demo, drives the playtest bots
  timeout   s: practice -> hint + "N to skip" offer; solo -> task failed (score 0) and move on
  duration  s: scored "fly for this long" task (completes after the time, score = time in tolerance)
  beginner  only in beginner mode (instrument tour)
Numbers for the F-16 (JSBSim model): rotate ~150 kt to 10 deg pitch, final approach ~160 kt / ~13 deg AoA max,
3 deg glide path (~800 fpm at 160 kt), pattern 1500 ft above the field. Sources: docs/sim-tutorial.html.
"""
import math

FT = 0.3048
FIELD_FT = 191.0
PASS = 70


def hdg_err(psi, target):
    return (psi - target + 180) % 360 - 180


def ft(s):
    return s["alt_m"] / FT


def agl_ft(s):
    return s["agl_m"] / FT


class T:
    """target to hold: name (display), unit, value(s, L), target (number or fn(L)), tolerance.
    coach: give corrections; band: only coach when |dev| < band * tol (far away = still flying there)."""
    def __init__(self, name, unit, value, target, tol, coach=True, band=4.0, fmt="%.0f"):
        self.name, self.unit, self.value, self.target, self.tol = name, unit, value, target, tol
        self.coach, self.band, self.fmt = coach, band, fmt

    def tgt(self, L):
        return self.target(L) if callable(self.target) else self.target


class Step:
    def __init__(self, text, check=None, hold=0.3, hint="", enter=None, kbd="", rig="", targets=(), goal=None, timeout=None,
                 duration=None, beginner=False, monitor=None):
        self.text, self.check, self.hold, self.hint, self.enter = text, check or (lambda s, L: True), hold, hint, enter
        self.kbd, self.rig = kbd or text, rig or kbd or text
        self.targets, self.goal, self.timeout, self.duration = list(targets), goal, timeout, duration
        self.beginner, self.monitor = beginner, monitor


class Seg:
    """demo segment: narration, autopilot goal fn(s, L), until fn(s, L) or `dur` seconds."""
    def __init__(self, say, goal, dur=None, until=None):
        self.say, self.goal, self.dur, self.until = say, goal, dur, until


# ---- targets -------------------------------------------------------------------------------------------------------
ALT = lambda tgt, tol=100, **k: T("ALT", "FT", lambda s, L: ft(s), tgt, tol, **k)
HDG = lambda tgt, tol=5, **k: T("HDG", "DEG", lambda s, L: (s["psi"] % 360), tgt, tol, **k)
BANK = lambda tgt, tol=5, **k: T("BANK", "DEG", lambda s, L: s["phi"], tgt, tol, **k)
VS = lambda tgt, tol, **k: T("VS", "FPM", lambda s, L: s["vs_fpm"], tgt, tol, **k)
SPD = lambda tgt, tol, **k: T("SPD", "KT", lambda s, L: s["kts"], tgt, tol, **k)
PITCH = lambda tgt, tol=2, **k: T("PITCH", "DEG", lambda s, L: s["theta"], tgt, tol, fmt="%.1f", **k)
CTR = lambda tol=8, **k: T("CTR", "M", lambda s, L: s.get("cross_m", 0.0), 0.0, tol, fmt="%+.0f", **k)
THR = lambda tgt, tol, **k: T("THR", "%", lambda s, L: s["thr"] * 100, tgt, tol, **k)
G = lambda tgt, tol, **k: T("G", "G", lambda s, L: s.get("nz", 1.0), tgt, tol, fmt="%.1f", **k)
CTL = lambda name, key, tgt, tol=0.4: T(name, "", lambda s, L, k=key: s.get(k, 0.0), tgt, tol, coach=False, fmt="%+.2f")

# what to do to raise / lower a value: (keyboard, rig)
INC = {"ALT": ("↓ 키를 살짝 눌러 기수를 드세요", "오른손으로 스틱을 살짝 몸 쪽으로 당기세요"),
       "VS": ("↓ 키를 살짝 눌러 기수를 드세요", "오른손으로 스틱을 살짝 당기세요"),
       "PITCH": ("↓ 키를 살짝 눌러 기수를 드세요", "오른손으로 스틱을 살짝 당기세요"),
       "G": ("↓ 키를 조금 더 눌러 당기세요", "오른손으로 스틱을 조금 더 당기세요"),
       "HDG": ("→ 키를 톡 눌러 오른쪽으로 살짝 돌리세요", "오른손으로 스틱을 살짝 오른쪽으로 기울이세요"),
       "BANK": ("→ 키를 톡 누르세요", "오른손으로 스틱을 살짝 오른쪽으로 기울이세요"),
       "SPD": ("W 키로 스로틀을 조금 올리세요", "왼손으로 스로틀을 조금 앞으로 미세요"),
       "THR": ("W 키로 스로틀을 올리세요", "왼손으로 스로틀을 앞으로 미세요"),
       "CTR": ("오른쪽으로 살짝: 땅에서는 D 키(페달), 공중에서는 → 키를 톡", "오른쪽으로 살짝: 땅에서는 오른발 페달, 공중에서는 스틱을 오른쪽으로 살짝")}
DEC = {"ALT": ("↑ 키를 톡 눌러 기수를 조금 내리세요", "오른손으로 스틱을 살짝 앞으로 미세요"),
       "VS": ("↑ 키를 톡 눌러 기수를 조금 내리세요", "오른손으로 스틱을 살짝 앞으로 미세요"),
       "PITCH": ("↑ 키를 톡 눌러 기수를 조금 내리세요", "오른손으로 스틱을 살짝 앞으로 미세요"),
       "G": ("↓ 키를 조금 풀어 주세요", "오른손으로 당기던 스틱을 조금 풀어 주세요"),
       "HDG": ("← 키를 톡 눌러 왼쪽으로 살짝 돌리세요", "오른손으로 스틱을 살짝 왼쪽으로 기울이세요"),
       "BANK": ("← 키를 톡 누르세요", "오른손으로 스틱을 살짝 왼쪽으로 기울이세요"),
       "SPD": ("S 키로 스로틀을 조금 줄이세요", "왼손으로 스로틀을 조금 당기세요"),
       "THR": ("S 키로 스로틀을 줄이세요", "왼손으로 스로틀을 당기세요"),
       "CTR": ("왼쪽으로 살짝: 땅에서는 A 키(페달), 공중에서는 ← 키를 톡", "왼쪽으로 살짝: 땅에서는 왼발 페달, 공중에서는 스틱을 왼쪽으로 살짝")}
NAME_KO = {"ALT": "고도", "HDG": "방위", "BANK": "경사", "VS": "상승률", "SPD": "속도", "PITCH": "기수 각도", "CTR": "중심선", "THR": "스로틀",
           "G": "G", "AIL": "스틱 좌우", "ELEV": "스틱 앞뒤", "RUD": "페달", "BRK": "브레이크"}


def problem(name, val, tgt, dev):
    """what is wrong, in words (dev = val - tgt, HDG dev already wrapped)."""
    if name == "ALT":
        return "고도가 낮아지고 있어요" if dev < 0 else "고도가 높아요"
    if name == "HDG":
        return "방위가 왼쪽으로 틀어졌어요" if dev < 0 else "방위가 오른쪽으로 틀어졌어요"
    if name == "BANK":
        if abs(tgt) < 1:
            return "날개를 수평으로 맞추세요"
        return ("경사가 너무 깊어요, %d°까지만" % abs(tgt)) if abs(val) > abs(tgt) else ("경사가 부족해요, %d°까지" % abs(tgt))
    if name == "VS":
        return ("강하율이 너무 커요" if val < 0 else "상승이 느려요") if dev < 0 else ("상승률이 너무 커요" if val > 0 else "강하가 느려요")
    if name == "SPD":
        return "속도가 낮아요" if dev < 0 else "속도가 높아요"
    if name == "PITCH":
        return "기수가 낮아요" if dev < 0 else "기수가 너무 높아요"
    if name == "CTR":
        return "중심선 왼쪽으로 벗어났어요" if dev < 0 else "중심선 오른쪽으로 벗어났어요"
    if name == "THR":
        return "스로틀이 부족해요" if dev < 0 else "스로틀이 너무 많아요"
    if name == "G":
        return "G 가 부족해요" if dev < 0 else "G 가 너무 커요"
    return name


def tour(text, say):
    """beginner-mode instrument tour step: same wording for keyboard and rig, live values via say(s, L) -> text."""
    return Step(text, hold=6.0, kbd=say, rig=say, beginner=True)


def keep(s, L, alt=None, hdg=None, spd=None):
    """autopilot goal helper."""
    g = {}
    if alt is not None:
        g["alt"] = alt
    if hdg is not None:
        g["hdg"] = hdg
    if spd is not None:
        g["spd"] = spd
    return g


def set_ref(s, L):
    L["alt0"], L["hdg0"] = round(ft(s), -1), round(s["psi"]) % 360


A0 = lambda L: L.get("alt0", 6000)


# =====================================================================================================================
def l0_orientation():
    c = lambda k, v: (lambda s, L: dict(ctrl={k: v}))
    return dict(
        id=0, title="0. 오리엔테이션", short="조종 장치와 계기", mode="runway", demo=[], solo=[], pass_score=0,
        brief=["이 시뮬레이터는 F-16 전투기를 혼자 처음부터 배울 수 있게 만든 훈련기예요. 교관 목소리와 가운데 훈련 화면이 할 일을 알려 줘요.",
               "모든 강의는 브리핑, 시범 비행, 연습, 단독 점검, 결과 순서예요. 시범에서는 자동 조종이 먼저 보여 주고, 스틱과 스로틀이 저절로 움직여요.",
               "언제든 P 로 멈출 수 있고, Z 를 누르면 교관이 방금 말을 다시 해 줘요. 어려우면 설정에서 쉬운 모드와 느린 시간을 켜세요.",
               "이번 강의에서는 비행기를 세워 둔 채 조종 장치와 계기를 하나씩 익혀요. 시험은 없어요."],
        practice=[
            Step("조종 장치 위치", hold=5,
                 kbd="키보드로 조종해요. 화살표는 스틱(↓ 가 당기기), A D 는 페달, W S 는 스로틀, B 는 브레이크, G 는 바퀴예요.",
                 rig="오른손은 가운데 스틱, 왼손은 왼쪽 스로틀, 두 발은 페달 위에 올려 두세요. 페달 윗부분을 발끝으로 누르면 브레이크예요."),
            tour("계기판 둘러보기", lambda s, L: "계기판 가운데 큰 화면은 훈련 화면이에요. 지금 할 일과 목표, 점수가 여기 나와요."),
            tour("계기판 둘러보기", lambda s, L: "왼쪽 화면은 비행 정보, 오른쪽 화면은 의자 움직임과 경고예요."),
            tour("계기판 둘러보기", lambda s, L: "가운데 아래 둥근 계기는 자세계예요. 위는 하늘, 아래는 땅, 비행기가 얼마나 기울었는지 보여 줘요."),
            tour("계기판 둘러보기", lambda s, L: "자세계 왼쪽 아래는 속도계, 오른쪽 아래는 고도계, 맨 아래는 승강계예요."),
            Step("스틱 오른쪽 = 오른쪽으로 기울기", lambda s, L: s["ail"] > 0.6, 0.3, "화면 속 스틱도 같이 오른쪽으로 기울어요",
                 kbd="→ 키를 누르고 있어 스틱을 오른쪽으로 기울이세요", rig="오른손으로 스틱을 오른쪽으로 끝까지 기울이세요",
                 targets=[CTL("AIL", "ail", 1.0)], goal=c("ail", 1.0)),
            Step("스틱 왼쪽 = 왼쪽으로 기울기", lambda s, L: s["ail"] < -0.6,
                 kbd="← 키를 누르고 있어 스틱을 왼쪽으로 기울이세요", rig="오른손으로 스틱을 왼쪽으로 끝까지 기울이세요",
                 targets=[CTL("AIL", "ail", -1.0)], goal=c("ail", -1.0)),
            Step("스틱 당기기 = 기수 올림", lambda s, L: s["elev"] < -0.6, 0.3, "키보드: ↓ = 당기기, ↑ = 밀기 (비행기 조종간과 같은 방향)",
                 kbd="↓ 키를 누르고 있어 스틱을 당기세요. 기수가 올라가는 방향이에요", rig="오른손으로 스틱을 몸 쪽으로 끝까지 당기세요",
                 targets=[CTL("ELEV", "elev", -1.0)], goal=c("elev", -1.0)),
            Step("스틱 밀기 = 기수 내림", lambda s, L: s["elev"] > 0.6,
                 kbd="↑ 키를 누르고 있어 스틱을 미세요. 기수가 내려가는 방향이에요", rig="오른손으로 스틱을 앞으로 끝까지 미세요",
                 targets=[CTL("ELEV", "elev", 1.0)], goal=c("elev", 1.0)),
            Step("왼쪽 페달 = 기수를 왼쪽으로", lambda s, L: s["rud"] < -0.6,
                 kbd="A 키로 왼쪽 페달을 밟으세요", rig="왼발로 왼쪽 페달을 끝까지 밟으세요", targets=[CTL("RUD", "rud", -1.0)], goal=c("rud", -1.0)),
            Step("오른쪽 페달 = 기수를 오른쪽으로", lambda s, L: s["rud"] > 0.6,
                 kbd="D 키로 오른쪽 페달을 밟으세요", rig="오른발로 오른쪽 페달을 끝까지 밟으세요", targets=[CTL("RUD", "rud", 1.0)], goal=c("rud", 1.0)),
            Step("브레이크 = 페달 윗부분", lambda s, L: s["brk"] > 0.5,
                 kbd="B 키를 누르고 있어 브레이크를 거세요", rig="양발 끝으로 페달 윗부분을 앞으로 눌러 브레이크를 거세요",
                 targets=[CTL("BRK", "brk", 1.0)], goal=c("brk", 1.0)),
            Step("스로틀 올리기 = 엔진 출력", lambda s, L: s["thr"] > 0.3, 0.3, "브레이크를 잡고 있어야 앞으로 안 굴러가요",
                 kbd="B 로 브레이크를 잡은 채 W 키로 스로틀을 30% 이상 올리세요",
                 rig="브레이크를 밟은 채 왼손으로 스로틀을 조금 앞으로 미세요. 30% 이상", targets=[CTL("THR", "thr", 0.65, 0.35)],
                 goal=lambda s, L: dict(ctrl={"thr": 0.5, "brk": 1.0})),
            Step("스로틀 내리기", lambda s, L: s["thr"] < 0.03,
                 kbd="S 키로 스로틀을 0% 까지 내리세요", rig="왼손으로 스로틀을 몸 쪽으로 끝까지 당기세요", targets=[CTL("THR", "thr", 0.0, 0.03)],
                 goal=lambda s, L: dict(ctrl={"thr": 0.0, "brk": 1.0})),
            Step("바퀴 손잡이", lambda s, L: True, 4,
                 kbd="G 키는 바퀴를 올리고 내려요. 땅에서는 누르지 마세요. 계기판 왼쪽 흰 손잡이가 같이 움직여요.",
                 rig="G 키(또는 계기판 왼쪽 흰 기어 손잡이)는 바퀴를 올리고 내려요. 땅에서는 쓰지 마세요."),
        ])


def l1_attitude():
    lv = lambda s, L: dict(alt=None) if False else dict(pitch=1.5, bank=0, spd=350)
    return dict(
        id=1, title="1. 자세와 조종 효과", short="기수와 기울기", mode="air",
        brief=["비행기는 스틱으로 두 가지를 바꿔요. 앞뒤는 기수 각도(피치), 좌우는 기울기(경사, 롤)예요.",
               "F-16 은 컴퓨터가 도와줘서 스틱을 놓으면 그 자세를 그대로 유지해요. 그래서 작게 움직이고 놓는 게 요령이에요.",
               "HUD 의 가로줄 사다리가 기수 각도예요. 5 도마다 줄이 있어요. 자세계는 하늘과 땅의 기울기를 보여 줘요."],
        demo=[Seg("먼저 제가 보여 줄게요. 스틱을 살짝 당기면 기수가 올라가요. 지금 5 도.", lambda s, L: dict(pitch=5, bank=0, spd=350), 7),
              Seg("스틱을 살짝 밀면 다시 수평이에요.", lambda s, L: dict(pitch=1.5, bank=0, spd=350), 6),
              Seg("스틱을 오른쪽으로 기울이면 오른쪽으로 기울어요. 경사 20 도.", lambda s, L: dict(pitch=2, bank=20, spd=350), 7),
              Seg("반대로 기울여 수평으로 돌아와요.", lambda s, L: dict(pitch=1.5, bank=0, spd=350), 6)],
        practice=[
            Step("기수 5° 들기", lambda s, L: abs(s["theta"] - 5) < 1.5, 3, "HUD 사다리의 5 줄에 맞추기",
                 kbd="↓ 키를 살짝 눌러 기수를 5° 까지 들고, 손을 떼서 3 초 유지하세요", rig="오른손으로 스틱을 살짝 당겨 기수 5°, 그리고 힘을 빼서 3 초 유지하세요",
                 targets=[PITCH(5, 1.5)], goal=lambda s, L: dict(pitch=5, bank=0, spd=350), timeout=60),
            Step("기수 수평으로", lambda s, L: abs(s["theta"] - 1.5) < 1.5, 3,
                 kbd="↑ 키를 톡 눌러 기수를 수평(1~2°)으로 돌리고 3 초", rig="스틱을 살짝 밀어 기수를 수평(1~2°)으로 돌리고 3 초",
                 targets=[PITCH(1.5, 1.5)], goal=lv, timeout=60),
            Step("오른쪽 경사 20°", lambda s, L: abs(s["phi"] - 20) < 5, 3,
                 kbd="→ 키를 톡톡 눌러 오른쪽으로 20° 기울이고 손을 떼서 3 초", rig="오른손으로 스틱을 살짝 오른쪽으로 기울여 20°, 그리고 가운데로. 3 초",
                 targets=[BANK(20, 5)], goal=lambda s, L: dict(pitch=2, bank=20, spd=350), timeout=60),
            Step("날개 수평", lambda s, L: abs(s["phi"]) < 4, 3,
                 kbd="← 키를 톡톡 눌러 날개를 수평으로", rig="스틱을 살짝 왼쪽으로 기울여 날개를 수평으로",
                 targets=[BANK(0, 4)], goal=lv, timeout=60),
            Step("왼쪽 경사 20°", lambda s, L: abs(s["phi"] + 20) < 5, 3,
                 kbd="← 키를 톡톡 눌러 왼쪽으로 20° 기울이고 손을 떼서 3 초", rig="스틱을 살짝 왼쪽으로 기울여 20°, 그리고 가운데로. 3 초",
                 targets=[BANK(-20, 5)], goal=lambda s, L: dict(pitch=2, bank=-20, spd=350), timeout=60),
            Step("날개 수평", lambda s, L: abs(s["phi"]) < 4, 3,
                 kbd="→ 키를 톡톡 눌러 날개를 수평으로", rig="스틱을 살짝 오른쪽으로 기울여 날개를 수평으로",
                 targets=[BANK(0, 4)], goal=lv, timeout=60),
        ],
        solo=[
            Step("기수 5° 를 5 초", lambda s, L: abs(s["theta"] - 5) < 1.5, 5, targets=[PITCH(5, 1.5)],
                 kbd="기수 5° 를 만들어 5 초 유지", rig="기수 5° 를 만들어 5 초 유지", goal=lambda s, L: dict(pitch=5, bank=0, spd=350), timeout=45),
            Step("오른쪽 경사 20° 를 5 초", lambda s, L: abs(s["phi"] - 20) < 5, 5, targets=[BANK(20, 5)],
                 kbd="오른쪽 경사 20° 를 5 초 유지", goal=lambda s, L: dict(pitch=2, bank=20, spd=350), timeout=45),
            Step("왼쪽 경사 20° 를 5 초", lambda s, L: abs(s["phi"] + 20) < 5, 5, targets=[BANK(-20, 5)],
                 kbd="왼쪽 경사 20° 를 5 초 유지", goal=lambda s, L: dict(pitch=2, bank=-20, spd=350), timeout=45),
            Step("수평 자세 5 초", lambda s, L: abs(s["phi"]) < 4 and abs(s["theta"] - 1.5) < 2, 5, targets=[BANK(0, 4), PITCH(1.5, 2)],
                 kbd="날개 수평, 기수 수평으로 5 초", goal=lv, timeout=45),
        ], key="BANK")


def l2_level():
    return dict(
        id=2, title="2. 수평 직진", short="고도와 방위 지키기", mode="air",
        brief=["수평 직진은 모든 비행의 기본이에요. 고도와 방향을 그대로 지키는 거예요.",
               "요령: 눈은 바깥 수평선과 HUD 를 보고, 고도가 변하기 시작하면 아주 작게 고쳐요. 크게 움직이면 출렁거려요.",
               "고도가 내려가면 살짝 당기고, 올라가면 살짝 밀어요. 방향이 틀어지면 반대쪽으로 아주 조금 기울였다가 다시 수평."],
        demo=[Seg("제가 먼저 수평으로 갈게요. HUD 오른쪽 고도 숫자와 아래 방위가 거의 안 변하죠.", lambda s, L: dict(alt=6000, hdg=0, spd=350), 10),
              Seg("자세계도 하늘과 땅의 경계가 가운데, 수평이에요.", lambda s, L: dict(alt=6000, hdg=0, spd=350), 6)],
        practice=[
            tour("HUD 읽기", lambda s, L: "앞 유리의 초록 글씨가 HUD 예요. 왼쪽 상자가 속도예요. 지금 %d kt." % round(s["kts"])),
            tour("HUD 읽기", lambda s, L: "오른쪽 상자가 고도, 해수면 기준 높이예요. 지금 %d ft." % round(ft(s), -1)),
            tour("HUD 읽기", lambda s, L: "아래 숫자가 방위, 비행기가 향한 방향이에요. 지금 %03d 도." % (round(s["psi"]) % 360)),
            tour("HUD 읽기", lambda s, L: "가운데 작은 동그라미는 비행경로, 비행기가 실제로 가는 방향이에요."),
            Step("고도 ±150 ft, 방위 000 ±5° 를 15 초", lambda s, L: abs(ft(s) - A0(L)) < 150 and abs(hdg_err(s["psi"], 0)) < 5, 15,
                 "기수가 내려가면 살짝 당기기, 기울면 반대쪽으로 톡", enter=set_ref,
                 kbd=lambda s, L: "고도 %d ft, 방위 000 을 15 초 지키세요. 화살표 키를 아주 짧게 톡톡" % A0(L),
                 rig=lambda s, L: "오른손 손끝으로 스틱을 아주 조금씩 움직여 고도 %d ft, 방위 000 을 15 초 지키세요" % A0(L),
                 targets=[ALT(A0, 150), HDG(0, 5)], goal=lambda s, L: dict(alt=A0(L), hdg=0, spd=350), timeout=120),
        ],
        solo=[
            Step("고도 ±100 ft, 방위 ±5° 로 30 초 비행", enter=set_ref, duration=30,
                 kbd=lambda s, L: "30 초 동안 고도 %d ft, 방위 000 을 지키세요" % A0(L),
                 targets=[ALT(A0, 100), HDG(0, 5)], goal=lambda s, L: dict(alt=A0(L), hdg=0, spd=350)),
        ], key="ALT")


def l3_power():
    return dict(
        id=3, title="3. 출력과 속도", short="스로틀로 속도 바꾸기", mode="air",
        brief=["스로틀은 속도를, 스틱은 고도를 맡아요. 속도를 줄이면 비행기가 내려가려 하니 기수를 조금 들어 고도를 지켜요.",
               "F-16 은 컴퓨터가 자동으로 트림을 맞춰서 따로 트림 손잡이를 쓸 필요가 없어요. 원하는 자세에서 손을 놓으면 돼요.",
               "속도는 바로 안 바뀌어요. 스로틀을 움직이고 몇 초 기다리는 게 요령이에요."],
        demo=[Seg("스로틀을 줄여 300 kt 로 감속할게요. 기수가 조금 들리는 걸 보세요.", lambda s, L: dict(alt=6000, hdg=0, spd=300), 20),
              Seg("다시 350 kt 로. 스로틀을 앞으로.", lambda s, L: dict(alt=6000, hdg=0, spd=350), 16)],
        practice=[
            Step("300 kt 로 감속, 고도 유지", lambda s, L: abs(s["kts"] - 300) < 10 and abs(ft(s) - 6000) < 150, 5, "스로틀은 조금만, 그리고 기다리기",
                 kbd="S 키로 스로틀을 조금 줄여 300 kt 로. ↓ 를 살짝 눌러 고도 6000 ft 를 지키세요",
                 rig="왼손으로 스로틀을 조금 당겨 300 kt 로. 오른손으로 스틱을 살짝 당겨 고도 6000 ft 를 지키세요",
                 targets=[SPD(300, 10), ALT(6000, 150)], goal=lambda s, L: dict(alt=6000, hdg=0, spd=300), timeout=120),
            Step("350 kt 로 가속, 고도 유지", lambda s, L: abs(s["kts"] - 350) < 10 and abs(ft(s) - 6000) < 150, 5,
                 kbd="W 키로 스로틀을 올려 350 kt 로. ↑ 를 톡 눌러 고도를 지키세요",
                 rig="왼손으로 스로틀을 조금 밀어 350 kt 로. 스틱을 살짝 밀어 고도를 지키세요",
                 targets=[SPD(350, 10), ALT(6000, 150)], goal=lambda s, L: dict(alt=6000, hdg=0, spd=350), timeout=120),
        ],
        solo=[
            Step("300 kt ±10, 고도 6000 ±100 으로 맞추고 10 초", lambda s, L: abs(s["kts"] - 300) < 10 and abs(ft(s) - 6000) < 100, 10,
                 kbd="300 kt, 6000 ft 로 10 초", targets=[SPD(300, 10), ALT(6000, 100)], goal=lambda s, L: dict(alt=6000, hdg=0, spd=300), timeout=90),
            Step("350 kt ±10, 고도 6000 ±100 으로 맞추고 10 초", lambda s, L: abs(s["kts"] - 350) < 10 and abs(ft(s) - 6000) < 100, 10,
                 kbd="350 kt, 6000 ft 로 10 초", targets=[SPD(350, 10), ALT(6000, 100)], goal=lambda s, L: dict(alt=6000, hdg=0, spd=350), timeout=90),
        ], key="SPD")


def l4_climb():
    lvl = lambda a, tol=150: (lambda s, L: abs(ft(s) - a) < tol and abs(s["vs_fpm"]) < 1000)
    return dict(
        id=4, title="4. 상승과 강하", short="고도 바꾸기", mode="air",
        brief=["올라가려면 스로틀을 올리고 기수를 들어요. 내려가려면 스로틀을 조금 줄이고 기수를 내려요.",
               "목표 고도에 가까워지면 미리 기수를 풀어요. 상승률의 10 분의 1 만큼 일찍. 예: 3000 fpm 이면 300 ft 전부터.",
               "상승률(VS)은 HUD 고도 위의 숫자, 오른쪽 화면, 승강계에서 볼 수 있어요."],
        demo=[Seg("7000 ft 로 상승할게요. 기수 들고, 스로틀 앞으로.", lambda s, L: dict(alt=7000, hdg=0, spd=350, vs_max=2500), 26),
              Seg("목표 근처에서 기수를 풀어 수평. 6000 ft 로 내려갈게요.", lambda s, L: dict(alt=6000, hdg=0, spd=350, vs_max=2500), 26)],
        practice=[
            Step("7000 ft ±150 으로 상승, 수평으로 5 초", lvl(7000), 5, "6700 ft 부터 기수를 천천히 내리기",
                 kbd="W 로 스로틀을 올리고 ↓ 로 기수를 5~8° 드세요. 6700 ft 부터 ↑ 로 천천히 풀어 7000 ft",
                 rig="왼손으로 스로틀을 밀고 오른손으로 스틱을 당겨 기수 5~8°. 6700 ft 부터 스틱을 풀어 7000 ft",
                 targets=[ALT(7000, 150)], goal=lambda s, L: dict(alt=7000, hdg=0, spd=350, vs_max=2500), timeout=150),
            Step("6000 ft ±150 으로 강하, 수평으로 5 초", lvl(6000), 5, "속도가 너무 빨라지면 스로틀을 조금 줄이기",
                 kbd="↑ 로 기수를 -3° 쯤 내리고, 6300 ft 부터 ↓ 로 천천히 풀어 6000 ft",
                 rig="스틱을 살짝 밀어 기수 -3°, 6300 ft 부터 천천히 당겨 6000 ft",
                 targets=[ALT(6000, 150)], goal=lambda s, L: dict(alt=6000, hdg=0, spd=350, vs_max=2500), timeout=150),
        ],
        solo=[
            Step("8000 ft 로 상승해서 10 초", lvl(8000), 10, kbd="8000 ft 로 상승해서 10 초 수평", targets=[ALT(8000, 150, band=3)],
                 goal=lambda s, L: dict(alt=8000, hdg=0, spd=350, vs_max=3000), timeout=150),
            Step("6000 ft 로 강하해서 10 초", lvl(6000), 10, kbd="6000 ft 로 강하해서 10 초 수평", targets=[ALT(6000, 150, band=3)],
                 goal=lambda s, L: dict(alt=6000, hdg=0, spd=350, vs_max=3000), timeout=150),
        ], key="ALT", monitor=lambda s, L, dt: L.update(over=max(L.get("over", 0), ft(s) - 8000 if L.get("phase_i", 0) == 0 else 0)))


def l5_turns():
    A = lambda tol=200: ALT(A0, tol)
    roll_out = lambda h: (lambda s, L: abs(hdg_err(s["psi"], h)) < 5 and abs(s["phi"]) < 5 and abs(ft(s) - A0(L)) < 200)
    return dict(
        id=5, title="5. 선회", short="경사 30° 와 45°", mode="air",
        brief=["선회 = 기울이고 살짝 당기기. 기울이면 날개 힘이 옆으로 가서 고도가 떨어지려 해요. 그래서 살짝 당겨요.",
               "경사 30° 선회는 기본, 45° 는 급선회예요. 경사가 깊을수록 더 많이 당겨야 하고 G(몸이 눌리는 힘)가 커져요.",
               "선회를 멈출 때는 목표 방향 10° 전부터 날개를 수평으로 돌려요."],
        demo=[Seg("오른쪽으로 30° 기울이고 살짝 당겨요. 고도가 그대로죠.", lambda s, L: dict(alt=6000, bank=30, spd=350), 12),
              Seg("이제 풀어서 수평.", lambda s, L: dict(alt=6000, bank=0, spd=350), 6)],
        practice=[
            Step("오른쪽 30° 선회해서 방위 090", roll_out(90), 3, "080 에서 풀기 시작", enter=set_ref,
                 kbd="→ 로 30° 기울이고 ↓ 로 살짝 당겨 고도 유지. 방위 080 에서 ← 로 풀어 090 에 맞추세요",
                 rig="스틱을 오른쪽으로 기울여 30°, 살짝 당겨 고도 유지. 080 에서 왼쪽으로 풀어 090 에 맞추세요",
                 targets=[BANK(30, 7, coach=False), A()], goal=lambda s, L: dict(alt=A0(L), hdg=90, bank_max=30, spd=350), timeout=150),
            Step("왼쪽 30° 선회해서 방위 000", roll_out(0), 3,
                 kbd="← 로 30° 기울이고 ↓ 로 살짝 당기기. 방위 010 에서 → 로 풀어 000",
                 rig="스틱을 왼쪽으로 30°, 살짝 당겨 고도 유지. 010 에서 오른쪽으로 풀어 000",
                 targets=[BANK(-30, 7, coach=False), A()], goal=lambda s, L: dict(alt=A0(L), hdg=0, bank_max=30, spd=350), timeout=150),
            Step("급선회: 오른쪽 45° 를 15 초", lambda s, L: abs(s["phi"] - 45) < 7 and abs(ft(s) - A0(L)) < 300, 15, "더 많이 당겨야 해요. G 가 1.4 정도",
                 kbd="→ 로 45° 기울이고 ↓ 를 꾹 눌러 고도를 지키세요", rig="스틱을 오른쪽으로 45° 기울이고 더 당겨 고도를 지키세요",
                 targets=[BANK(45, 7), ALT(A0, 300)], goal=lambda s, L: dict(alt=A0(L), bank=45, spd=350), timeout=120),
            Step("날개 수평", lambda s, L: abs(s["phi"]) < 5, 2, kbd="← 로 날개를 수평으로", rig="스틱을 왼쪽으로 풀어 날개 수평",
                 targets=[BANK(0, 5)], goal=lambda s, L: dict(alt=A0(L), bank=0, spd=350), timeout=60),
        ],
        solo=[
            Step("오른쪽 30° 선회로 방위 090, 고도 ±200", roll_out(90), 3, enter=set_ref, kbd="오른쪽 선회로 090, 고도 유지",
                 targets=[BANK(30, 7, coach=False), A()], goal=lambda s, L: dict(alt=A0(L), hdg=90, bank_max=30, spd=350), timeout=150),
            Step("급선회 왼쪽 45° 를 15 초, 고도 ±300", lambda s, L: abs(s["phi"] + 45) < 7 and abs(ft(s) - A0(L)) < 300, 15,
                 kbd="왼쪽 45° 급선회 15 초", targets=[BANK(-45, 7), ALT(A0, 300)], goal=lambda s, L: dict(alt=A0(L), bank=-45, spd=350), timeout=120),
        ], key="ALT")


def l6_combined():
    return dict(
        id=6, title="6. 복합 기동", short="상승 선회 · 강하 선회", mode="air",
        brief=["실제 비행은 상승하면서 돌고, 내려가면서 돌아요. 지금까지 배운 걸 합쳐요.",
               "경사는 30°, 상승률은 1500 fpm 정도. 고도와 방위 중 먼저 닿는 쪽부터 맞추고 나머지를 맞춰요."],
        demo=[Seg("상승하면서 오른쪽으로 돌게요. 경사 30°.", lambda s, L: dict(alt=7500, hdg=90, bank_max=30, spd=350, vs_max=1500), 25)],
        practice=[
            Step("상승 선회: 7500 ft, 방위 090", lambda s, L: abs(ft(s) - 7500) < 150 and abs(hdg_err(s["psi"], 90)) < 7 and abs(s["phi"]) < 7, 3,
                 kbd="W 와 ↓ 로 상승, → 로 30° 기울여 오른쪽 선회. 7500 ft, 방위 090 에서 수평",
                 rig="스로틀을 밀고 스틱을 당겨 상승, 오른쪽으로 30° 기울여 선회. 7500 ft, 방위 090 에서 수평",
                 targets=[ALT(7500, 150, band=3), HDG(90, 7, band=3)], goal=lambda s, L: dict(alt=7500, hdg=90, bank_max=30, spd=350, vs_max=1500),
                 timeout=180),
            Step("강하 선회: 6000 ft, 방위 000", lambda s, L: abs(ft(s) - 6000) < 150 and abs(hdg_err(s["psi"], 0)) < 7 and abs(s["phi"]) < 7, 3,
                 kbd="↑ 로 기수를 조금 내리고 ← 로 30° 왼쪽 선회. 6000 ft, 방위 000 에서 수평",
                 rig="스틱을 살짝 밀어 강하, 왼쪽으로 30° 선회. 6000 ft, 방위 000 에서 수평",
                 targets=[ALT(6000, 150, band=3), HDG(0, 7, band=3)], goal=lambda s, L: dict(alt=6000, hdg=0, bank_max=30, spd=350, vs_max=1500),
                 timeout=180),
        ],
        solo=[
            Step("상승 선회 7500 ft / 090", lambda s, L: abs(ft(s) - 7500) < 150 and abs(hdg_err(s["psi"], 90)) < 7 and abs(s["phi"]) < 7, 5,
                 kbd="7500 ft, 방위 090 으로 상승 선회", targets=[ALT(7500, 150, band=3), HDG(90, 7, band=3)],
                 goal=lambda s, L: dict(alt=7500, hdg=90, bank_max=30, spd=350, vs_max=1500), timeout=180),
            Step("강하 선회 6000 ft / 000", lambda s, L: abs(ft(s) - 6000) < 150 and abs(hdg_err(s["psi"], 0)) < 7 and abs(s["phi"]) < 7, 5,
                 kbd="6000 ft, 방위 000 으로 강하 선회", targets=[ALT(6000, 150, band=3), HDG(0, 7, band=3)],
                 goal=lambda s, L: dict(alt=6000, hdg=0, bank_max=30, spd=350, vs_max=1500), timeout=180),
        ], key="ALT")


def _to_mon(s, L, dt):
    if s["wow"] and s["theta"] > 13:
        L["strike"] = True
    if s["kts"] > 300 and s["gear"] > 0.5:
        L["gear_fast"] = True
    if s["wow"] and s["kts"] > 40:
        L["lat"] = max(L.get("lat", 0), abs(s.get("cross_m", 0)))


def _takeoff_steps(solo=False):
    G1 = lambda s, L: dict(thr=1.0, ground=True)
    return [
        Step("스로틀 최대", lambda s, L: s["thr"] > 0.95, 0.3,
             kbd="W 키를 누르고 있어 스로틀을 끝까지 올리세요", rig="왼손으로 스로틀을 끝까지 앞으로 미세요",
             targets=[THR(100, 5, coach=False)], goal=G1, timeout=None if not solo else 30),
        Step("활주: 가운데 선, 150 kt 까지", lambda s, L: s["kts"] >= 148, 0.2, "기수가 돌면 반대쪽 페달을 톡",
             kbd="A D 로 가운데 선을 따라가세요. 150 kt 가 되면 당겨요",
             rig="두 발로 페달을 살짝씩 밟아 가운데 선을 따라가세요. 150 kt 가 되면 당겨요",
             targets=[CTR(8), SPD(150, 15, coach=False)], goal=G1, timeout=60),
        Step("기수 들기 (로테이션) 10°", lambda s, L: s["theta"] > 8 or not s["wow"], 0.3, "13° 넘기면 꼬리가 땅에 닿아요",
             kbd="속도 150 kt — 지금 ↓ 키로 기수를 10° 까지 부드럽게 드세요",
             rig="속도 150 kt — 지금 오른손으로 스틱을 부드럽게 당겨 기수 10°",
             targets=[PITCH(10, 2)], goal=lambda s, L: dict(thr=1.0, ground=True, rotate_kt=145, pitch=10), timeout=30),
        Step("이륙, 상승 중", lambda s, L: not s["wow"] and s["agl_m"] > 15 and s["vs_fpm"] > 0, 1,
             kbd="기수 10° 를 유지하세요. 곧 바퀴가 떠요", rig="스틱을 그대로 잡고 기수 10° 를 유지하세요",
             targets=[PITCH(10, 3)], goal=lambda s, L: dict(thr=1.0, ground=True, rotate_kt=145, pitch=10), timeout=40),
        Step("바퀴 올리기", lambda s, L: s["gear"] < 0.1, 0.3, "300 kt 전에 올려야 해요",
             kbd="G 키로 바퀴를 올리세요", rig="G 키(또는 기어 손잡이)로 바퀴를 올리세요",
             targets=[PITCH(10, 4)], goal=lambda s, L: dict(thr=1.0, pitch=10, gear=0), timeout=25),
        Step("2000 ft 까지 상승, 300 kt", lambda s, L: ft(s) > 2000 and s["kts"] < 360, 0.5, "F-16 은 가속이 빨라요. 스로틀을 줄여 300 kt 근처로",
             kbd="기수 10° 로 2000 ft 까지. S 로 스로틀을 줄여 속도 300 kt 근처", rig="기수 10° 로 2000 ft 까지. 왼손으로 스로틀을 당겨 속도 300 kt 근처",
             targets=[ALT(2000, 150, coach=False), SPD(300, 50, coach=False)], goal=lambda s, L: dict(alt=2500, spd=300, hdg=52.4, vs_max=4000), timeout=90),
    ]


def l7_takeoff():
    return dict(
        id=7, title="7. 이륙", short="활주와 로테이션", mode="runway",
        brief=["청주 기지 활주로 06R 에서 이륙해요. 순서: 스로틀 최대 → 가운데 선 따라 활주 → 150 kt 에서 기수 10° → 이륙 → 바퀴 올리기 → 2000 ft.",
               "활주 중에는 스틱이 아니라 페달로 방향을 잡아요. 기수를 13° 넘게 들면 꼬리가 땅에 닿으니 조심.",
               "바퀴는 300 kt 를 넘기 전에 올려요. F-16 은 가속이 빨라서 금방이에요."],
        demo=[Seg("제가 먼저 이륙할게요. 스로틀 최대, 페달로 가운데 선.", lambda s, L: dict(thr=1.0, ground=True, rotate_kt=145, pitch=10), 9),
              Seg("150 kt, 기수를 10° 까지. 이륙!", lambda s, L: dict(thr=1.0, ground=True, rotate_kt=145, pitch=10, gear=1), 7),
              Seg("바퀴 올리고 2000 ft 까지 상승.", lambda s, L: dict(thr=0.85, pitch=10, gear=0), 10)],
        practice=_takeoff_steps(), solo=_takeoff_steps(True), key="CTR", monitor=_to_mon,
        penalties=lambda L: (25 if L.get("strike") else 0) + (15 if L.get("gear_fast") else 0) + int(max(0, L.get("lat", 0) - 8) * 2),
        penalty_text=lambda L: [t for c, t in ((L.get("strike"), "꼬리가 땅에 닿았어요 (기수 13° 넘음): 기수를 더 부드럽게, 10° 에서 멈추기"),
                                               (L.get("gear_fast"), "바퀴를 늦게 올렸어요 (300 kt 넘음): 이륙하면 바로 G"),
                                               (L.get("lat", 0) > 8, "활주 중 중심선에서 %.0f m 벗어났어요: 페달을 일찍, 작게" % L.get("lat", 0))) if c])


def _pattern_steps(solo=False):
    TH = (52.38 + 180) % 360
    BASE = (52.38 + 90) % 360
    return [
        Step("다운윈드: 1700 ft, 250 kt, 방위 232", lambda s, L: s.get("along_m", 0) < -1500, 0.2, "활주로와 나란히, 왼쪽 창밖에 활주로가 보여요",
             kbd="방위 232, 고도 1700 ft, 250 kt 를 지키며 활주로 끝을 지나가세요",
             rig="스틱으로 방위 232, 고도 1700 ft 를 지키고 스로틀로 250 kt. 활주로 끝을 지나가세요",
             targets=[HDG(TH, 7), ALT(1700, 150), SPD(250, 20)], goal=lambda s, L: dict(alt=1700, hdg=TH, spd=250), timeout=None if not solo else 90),
        Step("바퀴 내리기, 200 kt", lambda s, L: s["gear"] > 0.9 and s["kts"] < 215, 0.5, "바퀴는 250 kt 아래에서",
             kbd="G 키로 바퀴를 내리고 S 로 스로틀을 줄여 200 kt", rig="G 키(또는 기어 손잡이)로 바퀴를 내리고, 스로틀을 당겨 200 kt",
             targets=[SPD(200, 15), ALT(1700, 150)], goal=lambda s, L: dict(alt=1700, hdg=TH, spd=200, gear=1), timeout=60),
        Step("베이스 선회: 왼쪽으로 방위 142, 1200 ft", lambda s, L: abs(hdg_err(s["psi"], BASE)) < 10 and s.get("cross_m", -9e9) > -2200, 0.5,
             "왼쪽 30° 선회하며 천천히 강하",
             kbd="← 로 30° 기울여 왼쪽으로 돌아 방위 142. ↑ 를 톡 눌러 1200 ft 로 천천히 내려가세요",
             rig="스틱을 왼쪽으로 30° 기울여 방위 142 로. 스틱을 살짝 밀어 1200 ft 로 천천히",
             targets=[HDG(BASE, 10, band=2), ALT(1200, 200, coach=False), SPD(200, 20)],
             goal=lambda s, L: dict(alt=1200, hdg=BASE, bank_max=30, spd=190, gear=1, vs_max=900), timeout=120),
        Step("파이널 선회: 활주로 정렬 (방위 052)", lambda s, L: abs(hdg_err(s["psi"], 52.4)) < 8 and abs(s.get("cross_m", 0)) < 80, 2,
             "활주로 가운데 선이 화면 가운데 오게",
             kbd="← 로 다시 왼쪽 선회, 활주로 가운데 선이 정면에 오면 날개 수평. 방위 052",
             rig="스틱을 왼쪽으로 기울여 다시 선회, 활주로가 정면에 오면 날개 수평. 방위 052",
             targets=[HDG(52.4, 8, band=3), CTR(80, band=3), SPD(170, 20)],
             goal=lambda s, L: dict(alt=1000, hdg=52.4 + max(-30, min(30, -0.03 * s.get("cross_m", 0))) if s.get("cross_m", -9e9) > -1700 else BASE,
                                    bank_max=30, spd=170, gear=1, vs_max=900), timeout=120),
    ]


def l8_pattern():
    return dict(
        id=8, title="8. 장주 비행", short="활주로 둘레 사각형", mode="downwind",
        brief=["장주는 착륙하려고 활주로 둘레를 도는 사각형 길이에요. 다운윈드 → 베이스 → 파이널 순서.",
               "지금 활주로 왼쪽 3 km, 반대 방향(방위 232)으로 날고 있어요. 고도는 활주로 위 1500 ft(해수면 1700 ft), 250 kt.",
               "활주로 끝을 지나면 바퀴를 내리고 왼쪽으로 돌아 베이스(142), 다시 왼쪽으로 돌아 파이널(052)에서 활주로에 정렬해요."],
        demo=[Seg("다운윈드를 따라 갈게요. 왼쪽 창밖 활주로를 보세요.", lambda s, L: dict(alt=1700, hdg=232.4, spd=250), 14),
              Seg("바퀴 내리고 감속.", lambda s, L: dict(alt=1700, hdg=232.4, spd=200, gear=1), 12)],
        practice=_pattern_steps(), solo=_pattern_steps(True), key="ALT")


def _land_mon(s, L, dt):
    if s["wow"] and "td" not in L:
        L["td"] = dict(vs=s["vs_fpm"], e=s.get("cross_m", 0), n=s.get("along_m", 0), theta=s["theta"], kts=s["kts"])


AIM_M = 300.0                     # aim point: 300 m past the threshold
TAN3 = math.tan(math.radians(3.0))
WHEEL_FT = 5.0                    # agl at the CG with the wheels on the ground (JSBSim F-16)


def wheel_ft(s):
    return agl_ft(s) - WHEEL_FT


def _glide_vs(s):
    """vertical speed for the 3 deg path to the aim point (+ a gentle correction back onto it), then the flare:
    from ~80 ft the sink rate eases off smoothly with height (about 850 -> 200 fpm at touchdown), no sudden pull.
    The height is looked ahead 1 s, because the nose (and the sink rate) needs a moment to follow the stick."""
    nom = s["kts"] * 101.27 * TAN3                                        # 3 deg at this speed (~850 fpm at 160 kt)
    h_path = max(0.0, AIM_M - s.get("along_m", 0.0)) * TAN3 / FT
    vs = -nom - max(-200.0, min(200.0, 3.0 * (wheel_ft(s) - h_path)))
    h_ahead = max(0.0, wheel_ft(s) + s["vs_fpm"] / 60.0 * 1.0)
    return max(vs, -(150.0 + 9.0 * h_ahead))


def _land_lat(s, lim=15.0):
    return 52.4 + max(-lim, min(lim, -0.04 * s.get("cross_m", 0)))


def _glide(s, L):
    g = dict(vs=_glide_vs(s), hdg=_land_lat(s), gear=1)
    if wheel_ft(s) < 50:
        g["thr"] = 0.0                                                    # 50 ft: throttle to idle
    else:
        g["spd"] = 160
    return g


def _land_steps(solo=False):
    return [
        Step("바퀴 내리기", lambda s, L: s["gear"] > 0.9, 0.3, kbd="G 키로 바퀴를 내리세요", rig="G 키(또는 기어 손잡이)로 바퀴를 내리세요",
             goal=lambda s, L: dict(alt=1740, hdg=52.4, spd=175, gear=1), timeout=40),
        Step("속도 160 kt", lambda s, L: s["kts"] < 168, 1, "기수는 조금 들린 채 (받음각 8~12°)",
             kbd="S 키로 스로틀을 줄여 160 kt. 고도는 그대로", rig="왼손으로 스로틀을 조금 당겨 160 kt. 고도는 그대로",
             targets=[SPD(160, 8)], goal=lambda s, L: dict(alt=1740, hdg=52.4, spd=160, gear=1), timeout=60),
        Step("3° 강하: 강하율 800 fpm, 활주로 가운데, R 300 ft 까지", lambda s, L: s["agl_m"] < 90, 0.2, "활주로 문턱이 화면 속 한 점에 머물게",
             kbd="↑ ↓ 로 강하율 800 fpm, ← → 로 활주로 가운데. 속도는 W S 로 160 kt. R 300 까지",
             rig="스틱을 조금씩 밀고 당겨 강하율 800 fpm, 좌우로 살짝 기울여 활주로 가운데로. 속도는 스로틀로 160 kt. R 300 까지",
             targets=[VS(-800, 200), CTR(20), SPD(160, 10)], goal=_glide, timeout=150),
        Step("접지: R 50 에서 스로틀 0, 살짝 당기기", lambda s, L: s["wow"], 0.1, "강하율을 300 fpm 쯤으로 부드럽게 줄이기",
             kbd="R 50 에서 S 로 스로틀 0, ↓ 키로 살짝 당겨 강하를 줄이며 내려앉으세요",
             rig="R 50 에서 왼손으로 스로틀을 끝까지 당기고, 오른손으로 스틱을 살짝 당겨 강하를 줄이며 내려앉으세요",
             targets=[VS(-300, 250, coach=False), CTR(15)], goal=_glide, timeout=60),
        Step("정지", lambda s, L: s["kts"] < 5 and s["wow"], 0.5,
             kbd="B 키로 브레이크를 걸어 멈추세요. A D 로 가운데 선", rig="양발 끝으로 페달 윗부분을 눌러 브레이크, 멈추세요. 페달로 가운데 선",
             targets=[CTR(15)], goal=lambda s, L: dict(thr=0.0, ground=True, brk=1.0, gear=1), timeout=60),
    ]


def l9_landing():
    def pen(L):
        td = L.get("td")
        if not td:
            return 100
        vs = abs(td["vs"])
        p = 0 if vs < 400 else 15 if vs < 700 else 35 if vs < 1100 else 60
        p += 0 if abs(td["e"]) < 10 else 10 if abs(td["e"]) < 22 else 25
        p += 0 if 0 < td["n"] < 900 else 10 if -50 < td["n"] < 1800 else 25
        return p

    def ptxt(L):
        td = L.get("td")
        if not td:
            return ["접지하지 못했어요"]
        out = ["접지 강하율 %.0f fpm %s" % (abs(td["vs"]), "(부드러움)" if abs(td["vs"]) < 400 else "— R 50 에서 조금 더 일찍, 살짝 당기기"),
               "중심선에서 %.0f m %s" % (abs(td["e"]), "" if abs(td["e"]) < 10 else "— 페달과 작은 경사로 일찍 맞추기"),
               "문턱 뒤 %.0f m 에서 접지 %s" % (td["n"], "" if 0 < td["n"] < 900 else "— 조준점(문턱 300 m)을 화면 한 점에")]
        return out

    return dict(
        id=9, title="9. 접근과 착륙", short="3° 강하와 접지", mode="approach",
        brief=["활주로 06R 9 km 앞, 활주로 위 1550 ft, 180 kt 에서 시작해요. 3° 미끄럼길로 내려가요.",
               "F-16 접근 속도는 160 kt 정도, 강하율 800 fpm. 활주로 문턱 숫자가 화면 속 한 점에 머물면 길이 맞는 거예요.",
               "착륙할 때 높이는 HUD 고도 아래의 R 숫자(땅에서 잰 높이)를 봐요. 큰 고도 숫자는 해수면 기준이라 땅에 닿아도 190 쯤이에요.",
               "R 50 에서 스로틀을 끝까지 줄이고 살짝 당겨 강하를 줄여요(플레어). 땅에 닿으면 브레이크."],
        demo=[Seg("바퀴 내리고 160 kt 로 감속할게요.", lambda s, L: dict(alt=1740, hdg=52.4, spd=160, gear=1), 14),
              Seg("이제 800 fpm 쯤으로 강하, 활주로 가운데로. 활주로 문턱이 화면 속 한 점에 머물러요.", _glide, until=lambda s, L: s["agl_m"] < 90),
              Seg("R 300. R 50 에서 스로틀을 끝까지 줄이고 살짝 당겨 강하를 줄여요.", _glide, until=lambda s, L: s["wow"]),
              Seg("접지! 브레이크로 멈춰요.", lambda s, L: dict(thr=0.0, ground=True, brk=1.0, gear=1), until=lambda s, L: s["kts"] < 5)],
        practice=_land_steps(), solo=_land_steps(True), key="VS", monitor=_land_mon, penalties=pen, penalty_text=ptxt)


def _roll_mon(s, L, dt):
    """counts the roll angle of the aileron roll: only fast rolling (> 45 deg/s) counts, so levelling the wings
    before the roll or small corrections do not."""
    p = s.get("p_dps", 0.0)
    if abs(p) > 45:
        L["roll_acc"] = L.get("roll_acc", 0.0) + p * dt


def _roll_steps(solo=False):
    turn = lambda s, L: dict(alt=A0(L) if "alt0" in L else 12000, bank=60, spd=350)
    two_g = lambda s, L: abs(s.get("nz", 1) - 2) < 0.8 and abs(s["phi"] - 60) < 12
    nose = lambda s, L: s["theta"] > 8 and abs(s["phi"]) < 10
    level = lambda s, L: abs(s["phi"]) < 5 and abs(s["theta"]) < 5
    roll_go = lambda s, L: dict(ctrl={"ail": 1.0, "elev": 0.0})
    if solo:
        return [
            Step("2G 선회 5 초", two_g, 5, enter=set_ref, kbd="경사 60°, 2G 선회 5 초", rig="경사 60°, 2G 선회 5 초",
                 targets=[G(2, 0.8), BANK(60, 12, coach=False)], goal=turn, timeout=90),
            Step("롤 준비: 날개 수평, 기수 10°", nose, 0.5, kbd="날개 수평, 기수 10°", rig="날개 수평, 기수 10°",
                 targets=[PITCH(10, 3), BANK(0, 10)], goal=lambda s, L: dict(pitch=11, bank=0, thr=1.0), timeout=40),
            Step("에일러론 롤", lambda s, L: abs(L.get("roll_acc", 0)) > 340, 0.1, enter=lambda s, L: L.update(roll_acc=0.0), monitor=_roll_mon,
                 kbd="에일러론 롤 한 바퀴", rig="에일러론 롤 한 바퀴", goal=roll_go, timeout=30),
            Step("수평 회복", level, 3, kbd="날개 수평, 기수 수평", rig="날개 수평, 기수 수평", targets=[BANK(0, 5), PITCH(1.5, 4)],
                 goal=lambda s, L: dict(pitch=1.5, bank=0, spd=380), timeout=40),
        ]
    return [
        Step("2G 선회 (경사 60°) 를 5 초", two_g, 5, "경사 60° 에서 고도를 지키면 저절로 2G 쯤", enter=set_ref,
             kbd="→ 로 60° 기울이고 ↓ 를 꾹 눌러 고도를 지키세요. G 가 2 쯤 돼요", rig="스틱을 오른쪽으로 60° 기울이고 당겨서 고도를 지키세요. G 가 2 쯤 돼요",
             targets=[G(2, 0.8), BANK(60, 12, coach=False)], goal=turn, timeout=90),
        Step("롤 준비: 날개 수평, 기수 10°", nose, 0.5, "먼저 날개를 펴고, 그다음 기수를 들기",
             kbd="← 로 날개를 수평으로 펴고, ↓ 로 기수를 10° 드세요. W 로 스로틀 최대",
             rig="스틱을 왼쪽으로 기울여 날개를 수평으로, 그다음 당겨 기수 10°. 스로틀 최대",
             targets=[PITCH(10, 3), BANK(0, 10)], goal=lambda s, L: dict(pitch=11, bank=0, thr=1.0), timeout=40),
        Step("에일러론 롤 한 바퀴", lambda s, L: abs(L.get("roll_acc", 0)) > 340, 0.1, "스틱 앞뒤는 가운데, 옆으로만 끝까지",
             enter=lambda s, L: L.update(roll_acc=0.0), monitor=_roll_mon,
             kbd="→ 를 끝까지 누르고 있어 한 바퀴 도세요. ↑ ↓ 는 누르지 마세요. 한 바퀴 돌면 손을 떼요",
             rig="스틱을 오른쪽 끝까지 기울여 한 바퀴. 앞뒤로는 움직이지 마세요. 한 바퀴 돌면 가운데로",
             goal=roll_go, timeout=30),
        Step("수평 회복", level, 2, kbd="날개 수평, 기수 수평", rig="날개 수평, 기수 수평",
             targets=[BANK(0, 5), PITCH(1.5, 4)], goal=lambda s, L: dict(pitch=1.5, bank=0, spd=380), timeout=40),
    ]


def l10_g():
    return dict(
        id=10, title="10. G 와 기본 곡예 (선택)", short="2G 선회, 에일러론 롤", mode="air_high",
        assist=False,                                   # 60 deg bank and a full roll: the stability assist (45 deg limit) stays off here
        brief=["G 는 몸이 눌리는 무게의 배수예요. 2G 면 몸무게가 두 배예요. F-16 은 9G 까지 견디지만 사람은 훈련이 필요해요.",
               "의자는 G 를 그대로 만들 수 없어요. 화면의 G 숫자로 느낌을 대신해요.",
               "에일러론 롤은 스틱을 옆으로 끝까지 기울여 한 바퀴 도는 기동이에요. 시작 전에 날개를 펴고 기수를 10° 들어요.",
               "이 강의는 경사 60° 와 한 바퀴 롤을 해야 해서 쉬운 모드(자세 보조)가 꺼져 있어요. 12000 ft 라 고도는 넉넉해요."],
        demo=[Seg("경사 60° 로 기울이고 당겨 고도를 지키면 2G. 몸무게가 두 배예요. F-16 은 9G 까지, 넘으면 안 돼요.",
                  lambda s, L: dict(alt=12000, bank=60, spd=350), 12),
              Seg("날개를 펴고, 기수 10°.", lambda s, L: dict(pitch=11, bank=0, thr=1.0),
                  until=lambda s, L: L.update(roll_acc=0.0) or (s["theta"] > 8 and abs(s["phi"]) < 10)),
              Seg("스틱을 오른쪽 끝까지. 한 바퀴!", lambda s, L: dict(ctrl={"ail": 1.0, "elev": 0.0}), 5,
                  until=lambda s, L: _roll_mon(s, L, 1 / 60.0) or abs(L.get("roll_acc", 0)) > 330),
              Seg("손을 떼고 수평으로.", lambda s, L: dict(pitch=1.5, bank=0, spd=380), 6)],
        practice=_roll_steps(), solo=_roll_steps(True), key="G")


LESSONS = [l0_orientation, l1_attitude, l2_level, l3_power, l4_climb, l5_turns, l6_combined, l7_takeoff, l8_pattern, l9_landing, l10_g]


def lesson(i):
    d = LESSONS[i]()
    d.setdefault("demo", [])
    d.setdefault("solo", [])
    d.setdefault("pass_score", PASS)
    d.setdefault("key", "ALT")
    return d
