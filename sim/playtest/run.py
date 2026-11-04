"""Offline playtest: scripted student bots fly every lesson end to end (JSBSim, faster than real time, no network).

    python sim/playtest/run.py                 good / sloppy / wrong x all lessons, assist off
    python sim/playtest/run.py --bots good --lessons 2 5 --assist both [--trace] [--sim-patch] [--engine-as-is]
Bots = autopilot (the intent) + a human model (reaction delay, stick speed limit, tremor, drift, correction gain):
good (calm), sloppy (late, shaky, over-corrects pitch), wrong (wrong way at the start of each step until it sees it
or is told), clumsy (stress test, not in the default set). Each bot: briefing (presses N), watches the demo, practice
(follows the step goal, presses N 30 s after a timeout hint), solo (up to 2 retries), debrief.
Logs: sim/playtest/logs/<bot>_L<n>[_on][_simpatch].json, summary*.json. See README.md (Korean).
"""
import argparse, json, math, os, random, sys, time
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from simcore import Sim                                   # noqa: E402
from training.engine import Trainer                       # noqa: E402
from training.autopilot import Autopilot                  # noqa: E402
from training import lessons as LS                        # noqa: E402

LOGS = os.path.join(HERE, "logs")
# human model per bot: reaction delay (s), stick tremor (stationary std, stick units) with correlation time tau (s),
# autopilot pitch / roll gain (how hard the student corrects, >1 = overshoots; a human with a long delay corrects
# roll more gently or it oscillates), stick rate limit (full travel per s), wrong-way time
# at the start of each step (s), slow elevator drift amplitude (attention lapses).
BOTS = {"good": dict(delay=0.15, noise=0.005, tau=0.6, gain=0.8, roll=0.8, rate=4.0, wrong=0.0, drift=0.0),
        "sloppy": dict(delay=0.35, noise=0.025, tau=0.8, gain=1.3, roll=0.6, rate=2.0, wrong=0.0, drift=0.02),
        "wrong": dict(delay=0.25, noise=0.012, tau=0.7, gain=0.9, roll=0.7, rate=3.0, wrong=2.5, drift=0.0),
        # stress test (not in the default set): very late, shaky, over-controls - shows the checks are not trivial
        "clumsy": dict(delay=0.5, noise=0.05, tau=0.8, gain=1.6, roll=0.9, rate=1.5, wrong=0.0, drift=0.04)}
DEFAULT_BOTS = ("good", "sloppy", "wrong")
FPS = 60
ENGINE_AS_IS = False


class Student:
    """autopilot (the 'intent') -> wrong-way reflex -> reaction delay -> limited stick speed + tremor + drift.
    Wrong-way reflex (wrong bot): at the start of every step the stick goes the wrong way until the student sees it -
    after `wrong` s, or once the bank has moved 15 deg / the nose 5 deg the wrong way; after a crash in a step the
    student remembers and the reflex for that step is halved (then gone after a few crashes)."""
    def __init__(self, kind, seed=1):
        self.p = BOTS[kind]
        self.ap = Autopilot(gain=self.p["gain"], roll_gain=self.p["roll"])
        self.buf = []
        self.rng = random.Random(seed)
        self.n = {"ail": 0.0, "elev": 0.0}
        self.stick = {"ail": 0.0, "elev": 0.0}
        self.step_key = None
        self.t_step = 0.0
        self.wrong_t = {}                                         # step text -> wrong-way time (s), learned from crashes
        self.wrong_on = {"ail": False, "elev": False}
        self.att0 = (0.0, 0.0)
        self.wrong_end = {"self": 0, "coach": 0, "time": 0}       # how each wrong-way episode ended (wrong bot)

    def heard(self):
        """the instructor gave a correction: a wrong-way student fixes it at once."""
        for k in ("ail", "elev"):
            if self.wrong_on[k]:
                self.wrong_on[k] = False
                self.wrong_end["coach"] += 1

    def crashed(self):
        if self.step_key:
            k = self.step_key[2]
            self.wrong_t[k] = 0.5 * self.wrong_t.get(k, self.p["wrong"])
            if self.wrong_t[k] < 0.4:
                self.wrong_t[k] = 0.0

    def ctrl(self, s, goal, key, dt):
        p = self.p
        if key != self.step_key:                                  # new step: the wrong-way reflex again; a new phase (sim reset):
            if not self.step_key or key[0] != self.step_key[0]:   # forget the autopilot memory (integrators)
                self.ap.reset()
            self.step_key, self.t_step = key, 0.0
            self.wrong_on = {"ail": True, "elev": True}
            self.att0 = (s["phi"], s["theta"])
        self.t_step += dt
        c = self.ap.update(s, goal or {}, dt) if goal else dict(self.ap.last)
        free = bool(goal) and "ctrl" not in goal                  # flying (not a fixed 'press this key' step)
        if free:
            tw = self.wrong_t.get(key[2], p["wrong"])
            for k, moved in (("ail", abs(s["phi"] - self.att0[0]) > 15), ("elev", abs(s["theta"] - self.att0[1]) > 5)):
                if self.wrong_on[k] and (self.t_step >= tw or moved):
                    self.wrong_on[k] = False
                    if tw > 0:
                        self.wrong_end["time" if self.t_step >= tw else "self"] += 1
            for k in ("ail", "elev"):
                if self.wrong_on[k]:
                    c[k] = -c[k]
        self.buf.append(c)
        d = int(p["delay"] * FPS)
        out = dict(self.buf.pop(0)) if len(self.buf) > d else dict(c)
        a = math.exp(-dt / p["tau"])
        for k in ("ail", "elev"):
            want = out[k]
            if free:
                self.n[k] = a * self.n[k] + math.sqrt(1 - a * a) * self.rng.gauss(0, p["noise"])
                want += self.n[k] + (p["drift"] * math.sin(self.t_step * 0.7) if k == "elev" else 0.0)
            r = p["rate"] * dt
            self.stick[k] += max(-r, min(r, want - self.stick[k]))
            out[k] = max(-1.0, min(1.0, self.stick[k]))
        return out


def _apply_proposed(self, assist=False):
    """Sim.apply with the PROPOSED simcore change (--sim-patch): with the stick centred the assist no longer rolls the
    wings level from any bank (that undid every held 20-45 deg bank: tap -> release -> the bank is gone in ~1 s); it
    only rolls back to the assist bank limit (45 deg) from beyond it. Everything else as simcore.Sim.apply."""
    import simcore as SC
    f, c = self.fdm, dict(self.ctrl)
    if assist:
        phi, th = math.degrees(f["attitude/phi-rad"]), math.degrees(f["attitude/theta-rad"])
        on_ground = any(f["gear/unit[%d]/WOW" % i] > 0.5 for i in range(3))
        if not on_ground:
            if abs(c["ail"]) < 0.05 and abs(phi) > SC.ASSIST_BANK:
                c["ail"] = max(-0.15, min(0.15, -0.012 * (phi - math.copysign(SC.ASSIST_BANK, phi))))
            if phi > SC.ASSIST_BANK and c["ail"] > 0 or phi < -SC.ASSIST_BANK and c["ail"] < 0:
                c["ail"] = -0.01 * (phi - math.copysign(SC.ASSIST_BANK, phi))
            if th > SC.ASSIST_PITCH_UP and c["elev"] < 0:
                c["elev"] = 0.02 * (th - SC.ASSIST_PITCH_UP)
            if th < SC.ASSIST_PITCH_DN and c["elev"] > 0:
                c["elev"] = 0.02 * (th - SC.ASSIST_PITCH_DN)
    f["fcs/aileron-cmd-norm"] = c["ail"]
    f["fcs/elevator-cmd-norm"] = c["elev"]
    f["fcs/rudder-cmd-norm"] = c["rud"]
    f["fcs/throttle-cmd-norm"] = c["thr"]
    f["fcs/left-brake-cmd-norm"] = c["brk_l"]
    f["fcs/right-brake-cmd-norm"] = c["brk_r"]
    f["gear/gear-cmd-norm"] = c["gear"]
    self.applied = c


def _jsonable(v):
    try:
        json.dumps(v)
        return True
    except (TypeError, ValueError):
        return False


TRACE_KEYS = ("alt_m", "agl_m", "kts", "theta", "phi", "psi", "vs_fpm", "nz", "alpha", "cross_m", "along_m", "elev", "ail", "rud", "thr", "gear")


def run(bot, li, assist="off", max_min=25.0, retries=2, seed=1, trace=False):
    """one bot flies lesson li: brief -> demo -> practice -> solo (+ up to `retries` solo retries) -> debrief.
    In practice the bot presses N (skip) when a step is still not done 30 s after its timeout hint, like a beginner would."""
    sim = Sim("air")
    tr = Trainer(sim.reset, profiles_dir=os.path.join(HERE, "_profiles"), render=False)
    tr.prof.load("bot_%s" % bot)
    tr.prof.cur["lessons"] = {}
    tr.prof.cur["settings"]["assist"] = assist
    tr.assist_set = assist
    stu = Student(bot, seed)
    tr.start(li)
    t, wait, results, phases, rows = 0.0, 0.0, [], [], []
    tries, skips, t_row = 0, [], 0.0
    while t < max_min * 60:
        s = sim.packet()
        s["paused"] = tr.want_pause
        coach_t0 = tr.coach_t
        tr.update(s, 0.0 if tr.want_pause else 1 / FPS)
        if tr.coach_t != coach_t0 and tr.coach_kind == "fix" and tr.coach:
            stu.heard()
        ph = tr.phase
        if not phases or phases[-1][1] != ph:
            phases.append((round(t, 1), ph))
            if ph == "crash":
                stu.crashed()
        if tr.want_pause:
            wait += 1 / FPS
            t += 1 / FPS
            if ph == "debrief" and wait > 1.0:
                db = tr.debrief
                results.append(dict(score=db["score"], passed=db["passed"], assist=db.get("assist"), tasks=db["tasks"], good=db["good"], fix=db["fix"],
                                    vars={k: v for k, v in tr.L["vars"].items() if _jsonable(v)}))
                if db["passed"] or tries >= retries or not tr.L["d"]["solo"]:
                    break
                tries += 1
                tr.command({"cmd": "tut", "op": "retry"})
                wait = 0.0
            elif ph in ("brief", "crash") and wait > 0.8:
                tr.command({"cmd": "tut", "op": "next"})
                wait = 0.0
            elif ph == "menu":
                break
            continue
        wait = 0.0
        if ph == "demo":
            if tr.ctrl_override:
                sim.ctrl.update(tr.ctrl_override)
        elif ph in ("practice", "solo"):
            L = tr.L
            steps = tr._steps()
            st = steps[min(L["step"], len(steps) - 1)]
            if ph == "practice" and st.timeout and L["t_step"] > st.timeout + 30:
                skips.append(st.text)
                tr.command({"cmd": "tut", "op": "next"})
                continue
            try:
                goal = st.goal(s, L["vars"]) if st.goal else None
            except (KeyError, TypeError, ValueError):
                goal = None
            sim.ctrl.update(stu.ctrl(s, goal, (ph, L["step"], st.text), 1 / FPS))
        if trace and t >= t_row:
            t_row = t + 0.5
            stp = tr.L["step"] if tr.L else -1
            rows.append([round(t, 1), ph, stp] + [round(float(s.get(k, 0.0)), 2) for k in TRACE_KEYS])
        # lesson "assist": False (L10) = the assist stays off in that lesson. engine.py does not read the flag yet (requested
        # change), so the harness applies it here; --engine-as-is uses tr.assist unchanged.
        asst_now = tr.assist and (ENGINE_AS_IS or not tr.L or tr.L["d"].get("assist", True))
        sim.frame(assist=asst_now, slow=tr.slow)
        t += 1 / FPS
    said = [dict(t=a, phase=b, text=c) for a, b, c in tr.log]
    instr = set()
    for stp in LS.lesson(li)["practice"] + LS.lesson(li)["solo"]:
        instr.update(x for x in (stp.kbd, stp.rig, stp.text) if isinstance(x, str))
    out = dict(bot=bot, lesson=li, assist=assist, title=LS.lesson(li)["title"], sim_min=round(t / 60, 2), results=results, phases=phases, said=said,
               passed=any(r["passed"] for r in results), best=max((r["score"] for r in results), default=None),
               first_try=bool(results and results[0]["passed"]), practice_skips=skips, wrong_end=stu.wrong_end,
               coach_fix=sum(1 for x in said if "—" in x["text"] and x["phase"] == "practice" and x["text"] not in instr),
               praise=sum(1 for x in said if x["text"].startswith("좋아요")), crashes=sum(1 for p in phases if p[1] == "crash"),
               crash_why=sorted(set(x["text"].split(". ")[1] for x in said if x["phase"] == "crash" and x["text"].startswith("괜찮아요"))))
    if trace:
        out["trace_cols"] = ["t", "phase", "step"] + list(TRACE_KEYS)
        out["trace"] = rows
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--bots", nargs="*", default=list(DEFAULT_BOTS), help="good sloppy wrong (default) and clumsy (stress test)")
    ap.add_argument("--lessons", nargs="*", type=int, default=list(range(len(LS.LESSONS))))
    ap.add_argument("--assist", default="off", choices=("off", "on", "auto", "both"),
                    help="beginner stability assist: off (default), on, auto (engine rule: first two attempts), both = off then on")
    ap.add_argument("--trace", action="store_true", help="store a 2 Hz state trace in each log (for plots / debugging)")
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--sim-patch", action="store_true", help="fly with the proposed simcore assist change (no wing leveller below 45 deg)")
    ap.add_argument("--engine-as-is", action="store_true", help="ignore the lesson 'assist' flag (as engine.py behaves today)")
    a = ap.parse_args()
    ENGINE_AS_IS = a.engine_as_is
    if a.sim_patch:
        Sim.apply = _apply_proposed
    os.makedirs(LOGS, exist_ok=True)
    for asst in (("off", "on") if a.assist == "both" else (a.assist,)):
        summ = []
        for b in a.bots:
            for li in a.lessons:
                t0 = time.time()
                r = run(b, li, assist=asst, trace=a.trace, seed=a.seed)
                r["wall_s"] = round(time.time() - t0, 1)
                json.dump(r, open(os.path.join(LOGS, "%s_L%d%s%s.json" % (b, li, "" if asst == "off" else "_" + asst, ("_simpatch" if a.sim_patch else "") + ("_asis" if a.engine_as_is else ""))), "w", encoding="utf-8"),
                          ensure_ascii=False, indent=1)
                td = next((res["vars"].get("td") for res in r["results"][::-1] if res["vars"].get("td")), None)
                line = dict(bot=b, lesson=li, assist=asst, passed=r["passed"], first_try=r["first_try"], best=r["best"], tries=len(r["results"]),
                            scores=[res["score"] for res in r["results"]], crashes=r["crashes"], crash_why=r["crash_why"],
                            skips=len(r["practice_skips"]), coach=r["coach_fix"], wrong_end=r["wrong_end"] if BOTS[b]["wrong"] else None, praise=r["praise"], sim_min=r["sim_min"], wall_s=r["wall_s"],
                            fails=[t["text"] for res in r["results"][-1:] for t in res["tasks"] if not t["done"]])
                if td:
                    line["touchdown"] = {k: round(v) for k, v in td.items()}
                summ.append(line)
                print(json.dumps(line, ensure_ascii=False), flush=True)
        name = ("summary.json" if asst == "off" else "summary_assist_%s.json" % asst).replace(".json", ("_simpatch" if a.sim_patch else "") + ("_asis" if a.engine_as_is else "") + ".json")
        json.dump(dict(made=time.strftime("%Y-%m-%d %H:%M:%S"), assist=asst, bots={b: BOTS[b] for b in a.bots}, seed=a.seed,
                       sim_patch=a.sim_patch, lesson_assist_flag="ignored (engine as is)" if a.engine_as_is else "applied by the harness (requested engine change)", runs=summ),
                  open(os.path.join(LOGS, name), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
