"""Simple scripted autopilot for demos (and as the core of the playtest student bots).

ap = Autopilot(); ctrl = ap.update(s, goal, dt)
goal keys (all optional):
  ctrl={...}          fixed control values (e.g. {"ail": 1.0} for the controls tour, {"gear": 0})
  alt (ft), vs (fpm)  vertical: hold altitude (vs from the error) or a vertical speed
  pitch (deg)         vertical: hold a pitch attitude instead
  hdg (deg), bank (deg), bank_max (deg)   lateral: turn to a heading with bank <= bank_max, or hold a bank
  spd (kt) / thr (0..1)                   speed with the throttle, or a fixed throttle
  ground=True         on the runway: rudder keeps the centre line (cross track from the packet), brakes off
  rotate_kt           ground roll: lift the nose to `pitch` once above this speed
  gear (0/1), brk (0..1)
JSBSim F-16 conventions: elevator + = nose down (push), aileron + = roll right, rudder + = yaw right.
"""
import math


def clamp(v, a, b):
    return max(a, min(b, v))


def hdg_err(target, psi):
    return (target - psi + 180) % 360 - 180


class Autopilot:
    def __init__(self, gain=1.0, roll_gain=None):
        self.gain = gain                                   # pitch (and roll unless roll_gain is given) loop gain
        self.roll_gain = gain if roll_gain is None else roll_gain
        self.thr_i = None
        self.vi = 0.0
        self.gi = 0.0
        self.last = dict(ail=0.0, elev=0.0, rud=0.0, thr=0.0, brk_l=0.0, brk_r=0.0, gear=0.0)

    def reset(self):
        self.thr_i = None
        self.vi = 0.0
        self.gi = 0.0

    def update(self, s, goal, dt):
        g = goal or {}
        out = dict(self.last)
        out["gear"] = s.get("gear_cmd", out["gear"])          # keep the current gear / throttle unless the goal sets them
        if "thr" not in g and "spd" not in g:
            out["thr"] = s.get("thr", out["thr"])
        ft = s["alt_m"] / 0.3048
        # ---- lateral
        if "g" in g and "bank" not in g:                               # level turn at a load factor: bank = acos(1/g), less if sinking
            bank_t = math.degrees(math.acos(1.0 / max(1.05, g["g"]))) + clamp(0.004 * s.get("vs_fpm", 0.0), -25.0, 8.0)
        elif "hdg" in g and "bank" not in g:
            e = hdg_err(g["hdg"], s["psi"])
            bank_t = clamp(2.0 * e, -g.get("bank_max", 30.0), g.get("bank_max", 30.0))
        else:
            bank_t = g.get("bank", 0.0)
        kr = min(1.0, 330.0 / max(150.0, s["kts"]))                   # roll rate per stick grows with speed: correct more gently
        ail = 0.035 * (bank_t - s["phi"]) - 0.010 * s.get("p_dps", 0.0)
        out["ail"] = clamp(ail * self.roll_gain * kr, -0.6, 0.6)
        # ---- vertical
        ks = min(1.0, (300.0 / max(150.0, s["kts"])) ** 2)          # less pitch authority at high speed (g-command stick)
        if "g" in g and not s.get("wow"):                            # hold a load factor (G lesson)
            self.gi = clamp(getattr(self, "gi", 0.0) + 0.008 * (g["g"] - s.get("nz", 1.0)) * dt, -0.6, 0.6)
            out["elev"] = clamp(-(0.015 * (g["g"] - s.get("nz", 1.0)) + self.gi), -0.8, 0.3)
        elif g.get("ground") and s.get("wow"):
            rk = g.get("rotate_kt")
            th_t = g.get("pitch", 0.0) if rk is not None and s["kts"] >= rk else None
            if th_t is None:
                out["elev"] = 0.0
            else:
                out["elev"] = clamp(-(0.12 * (th_t - s["theta"]) - 0.04 * s.get("q_dps", 0.0)), -0.6, 0.3)
        else:
            if "pitch" in g:
                th_t = g["pitch"]
            else:
                if "alt" in g:
                    vs_t = clamp(3.0 * (g["alt"] - ft), -g.get("vs_max", 2500.0), g.get("vs_max", 2500.0))
                else:
                    vs_t = g.get("vs", 0.0)
                v_fps = max(100.0, s["kts"] * 1.6878)
                gamma_t = math.degrees(math.asin(clamp(vs_t / 60.0 / v_fps, -0.5, 0.5)))
                self.vi = clamp(self.vi + 0.0010 * (vs_t - s.get("vs_fpm", 0.0)) * dt, -6.0, 6.0)      # integrator: removes the steady vs error
                th_t = gamma_t + s.get("alpha", 0.0) * math.cos(math.radians(s["phi"])) + self.vi
            # in a bank the nose needs extra pull: the error term handles it, plus a 1/cos feed-forward
            ff = -0.04 * (1.0 / max(0.4, math.cos(math.radians(s["phi"]))) - 1.0)
            out["elev"] = clamp((-(0.07 * (th_t - s["theta"]) - 0.03 * s.get("q_dps", 0.0)) + ff) * self.gain * ks, -0.7 * ks, 0.5 * ks)
        # g protection (a careful pilot never pulls past ~5 G or pushes below 0 G here): ease the stick off near the limits
        if not s.get("wow") and "g" not in g and not (g.get("ctrl") and "elev" in g["ctrl"]):
            nz = s.get("nz", 1.0)
            if nz < 0.0 and out["elev"] > 0:
                out["elev"] = max(0.0, out["elev"] + 0.15 * nz)
            elif nz > 5.0 and out["elev"] < 0:
                out["elev"] = min(0.0, out["elev"] + 0.05 * (nz - 5.0))
        # ---- speed
        if "thr" in g:
            out["thr"] = g["thr"]
        elif "spd" in g:
            if self.thr_i is None:
                self.thr_i = s.get("thr", 0.5)
            err = g["spd"] - s["kts"]
            self.thr_i = clamp(self.thr_i + 0.004 * err * dt, 0.0, 1.0)
            out["thr"] = clamp(self.thr_i + 0.015 * err, 0.0, 1.0)
        # ---- ground: centre line with the rudder
        if g.get("ground") and s.get("wow"):
            cross = s.get("cross_m", 0.0)
            he = hdg_err(s.get("rwy_hdg", 0.0), s["psi"])
            out["rud"] = clamp(-0.06 * cross + 0.08 * he, -0.6, 0.6)
            out["ail"] = 0.0
        else:
            out["rud"] = 0.0
        for k in ("gear", "brk"):
            if k in g:
                if k == "gear":
                    out["gear"] = float(g["gear"])
                else:
                    out["brk_l"] = out["brk_r"] = float(g["brk"])
        if "brk" not in g:
            out["brk_l"] = out["brk_r"] = 0.0
        for k, v in (g.get("ctrl") or {}).items():
            if k == "brk":
                out["brk_l"] = out["brk_r"] = v
            else:
                out[k] = v
        self.last = out
        return dict(out)
