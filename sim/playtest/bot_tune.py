"""Quick bot-model check: one student bot holds a few simple goals (no instructor), prints how steady it is.

    python sim/playtest/bot_tune.py [bot ...] [--assist]
Columns: goal, theta (mean/std deg), alt range (ft), bank std (deg), max |nz-1|, min AGL (ft).
A bot that diverges here (alt range of thousands of ft, nz swings) cannot pass the attitude lessons either.
"""
import math, os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)
from simcore import Sim                                   # noqa: E402
from run import Student, BOTS, FPS                        # noqa: E402

CASES = [("air", "pitch 5", lambda s, t: dict(pitch=5, bank=0, spd=350)),
         ("air", "alt 6000 hdg 0", lambda s, t: dict(alt=6000, hdg=0, spd=350)),
         ("air", "bank 20", lambda s, t: dict(pitch=2, bank=20, spd=350)),
         ("air", "bank 45 alt", lambda s, t: dict(alt=6000, bank=45, spd=350)),
         ("air", "climb 8000", lambda s, t: dict(alt=8000, hdg=0, spd=350, vs_max=3000)),
         ("approach", "vs -800", lambda s, t: dict(vs=-800 if t > 15 else 0, hdg=52.4, spd=160, gear=1))]


def trial(bot, mode, goal, secs=60, assist=False, seed=1):
    sim = Sim(mode)
    stu = Student(bot, seed)
    t, th, al, ph, nz, agl = 0.0, [], [], [], 0.0, 1e9
    while t < secs:
        s = sim.packet()
        sim.ctrl.update(stu.ctrl(s, goal(s, t), ("x", 0, "x"), 1 / FPS))
        sim.frame(assist=assist)
        t += 1 / FPS
        if t > 10:
            th.append(s["theta"]); al.append(s["alt_m"] / 0.3048); ph.append(s["phi"])
            nz = max(nz, abs(s["nz"] - 1)); agl = min(agl, s["agl_m"] / 0.3048)
    m = sum(th) / len(th)
    sd = lambda v: math.sqrt(sum((x - sum(v) / len(v)) ** 2 for x in v) / len(v))
    return "%-15s th %5.1f/%4.1f  alt %6.0f  bank sd %4.1f (mean %5.1f)  |nz-1| %4.1f  agl %6.0f" % (
        "", m, sd(th), max(al) - min(al), sd(ph), sum(ph) / len(ph), nz, agl)


if __name__ == "__main__":
    bots = [a for a in sys.argv[1:] if not a.startswith("--")] or list(BOTS)
    for b in bots:
        print(b, BOTS[b])
        for mode, name, g in CASES:
            print("  %-15s" % name, trial(b, mode, g, assist="--assist" in sys.argv)[15:], flush=True)
