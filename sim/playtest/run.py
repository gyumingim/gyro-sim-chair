"""Offline playtest: scripted student bots fly every lesson end to end (JSBSim, faster than real time, no network).

    python sim/playtest/run.py                 all bots x all lessons
    python sim/playtest/run.py --bots good --lessons 2 5
Bots (autopilot + a human model): good (small delay / noise), sloppy (late, overshoots, noisy), wrong (pushes the
wrong way for the first seconds of every step, then corrects - checks the corrective coaching).
Each bot: briefing (presses N), watches the demo, practice (follows the step goal), solo, debrief; a failed solo is
retried up to 2 times. Logs: sim/playtest/logs/<bot>_L<n>.json (everything the instructor said, results), summary.json.
"""
import argparse, json, math, os, random, sys, time
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from simcore import Sim                                   # noqa: E402
from training.engine import Trainer                       # noqa: E402
from training.autopilot import Autopilot                  # noqa: E402
from training import lessons as LS                        # noqa: E402

LOGS = os.path.join(HERE, "logs")
BOTS = {"good": dict(delay=0.15, noise=0.005, gain=0.6, wrong=0.0, drift=0.0),
        "sloppy": dict(delay=0.35, noise=0.04, gain=1.1, wrong=0.0, drift=0.03),
        "wrong": dict(delay=0.25, noise=0.02, gain=0.7, wrong=3.0, drift=0.0)}
FPS = 60


class Student:
    def __init__(self, kind, seed=1):
        self.p = BOTS[kind]
        self.ap = Autopilot(gain=self.p["gain"])
        self.buf = []
        self.rng = random.Random(seed)
        self.n = {"ail": 0.0, "elev": 0.0}
        self.step_key = None
        self.t_step = 0.0

    def ctrl(self, s, goal, key, dt):
        if key != self.step_key:
            self.step_key, self.t_step = key, 0.0
            self.ap.reset()
        self.t_step += dt
        c = self.ap.update(s, goal or {}, dt) if goal else dict(self.ap.last)
        if goal and "ctrl" not in goal:
            for k in ("ail", "elev"):
                self.n[k] = 0.97 * self.n[k] + self.rng.gauss(0, self.p["noise"])
                c[k] = max(-1, min(1, c[k] + self.n[k] + (self.p["drift"] * math.sin(self.t_step * 0.7) if k == "elev" else 0)))
            if self.t_step < self.p["wrong"]:
                c["ail"], c["elev"] = -c["ail"], -c["elev"]
        self.buf.append(c)
        d = int(self.p["delay"] * FPS)
        return self.buf.pop(0) if len(self.buf) > d else dict(self.ap.last, ail=0.0, elev=0.0)


def run(bot, li, max_min=25.0, retries=2, seed=1):
    sim = Sim("air")
    tr = Trainer(sim.reset, profiles_dir=os.path.join(HERE, "_profiles"), render=False)
    tr.prof.load("bot_%s" % bot)
    tr.prof.cur["lessons"] = {}
    tr.prof.cur["settings"]["assist"] = "off"
    tr.assist_set = "off"
    stu = Student(bot, seed)
    tr.start(li)
    t, wait, results, phases = 0.0, 0.0, [], []
    tries = 0
    while t < max_min * 60:
        s = sim.packet()
        s["paused"] = tr.want_pause
        pub = tr.update(s, 0.0 if tr.want_pause else 1 / FPS)
        ph = tr.phase
        if not phases or phases[-1][1] != ph:
            phases.append((round(t, 1), ph))
        if tr.want_pause:
            wait += 1 / FPS
            t += 1 / FPS
            if ph == "debrief" and wait > 1.0:
                db = tr.debrief
                results.append(dict(score=db["score"], passed=db["passed"], tasks=db["tasks"], good=db["good"], fix=db["fix"]))
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
            try:
                goal = st.goal(s, L["vars"]) if st.goal else None
            except (KeyError, TypeError, ValueError):
                goal = None
            sim.ctrl.update(stu.ctrl(s, goal, (ph, L["step"]), 1 / FPS))
        sim.frame(assist=tr.assist, slow=tr.slow)
        t += 1 / FPS
    said = [dict(t=a, phase=b, text=c) for a, b, c in tr.log]
    return dict(bot=bot, lesson=li, title=LS.lesson(li)["title"], sim_min=round(t / 60, 2), results=results, phases=phases, said=said,
                passed=any(r["passed"] for r in results), best=max((r["score"] for r in results), default=None),
                coach_fix=sum(1 for x in said if "—" in x["text"] and x["phase"] == "practice"),
                praise=sum(1 for x in said if x["text"].startswith("좋아요")), crashes=sum(1 for p in phases if p[1] == "crash"))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--bots", nargs="*", default=list(BOTS))
    ap.add_argument("--lessons", nargs="*", type=int, default=list(range(len(LS.LESSONS))))
    a = ap.parse_args()
    os.makedirs(LOGS, exist_ok=True)
    summ = []
    for b in a.bots:
        for li in a.lessons:
            t0 = time.time()
            r = run(b, li)
            r["wall_s"] = round(time.time() - t0, 1)
            json.dump(r, open(os.path.join(LOGS, "%s_L%d.json" % (b, li)), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
            line = dict(bot=b, lesson=li, passed=r["passed"], best=r["best"], tries=len(r["results"]), crashes=r["crashes"], coach=r["coach_fix"],
                        praise=r["praise"], sim_min=r["sim_min"], wall_s=r["wall_s"],
                        fails=[t["text"] for res in r["results"][-1:] for t in res["tasks"] if not t["done"]])
            summ.append(line)
            print(json.dumps(line, ensure_ascii=False), flush=True)
    json.dump(dict(made=time.strftime("%Y-%m-%d %H:%M:%S"), runs=summ), open(os.path.join(LOGS, "summary.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
