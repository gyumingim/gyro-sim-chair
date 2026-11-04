"""Chair dynamics model for the weight-shift gyro sim chair (2 axes, each a weighted pendulum).

Run:  python control/chair_model.py            -> prints the numbers, writes control/out/chair_model.json + PNGs
      python control/chair_model.py --from-index  (re-extract masses / inertias from index.html with node first)

Model per axis (body frame, small yaw-free gimbal, axes treated as independent):
    I(x) th'' = g (Mx0 + m x) cos th - g Md sin th - m h x'' - c th'
    tan(th_eq) = (Mx0 + m x) / Md                         (same as index.html balance())
  th   tilt toward the side the weights move to (deg in the API, rad inside)
  x    weight position on its rail from the centre (m)
  m    moving weight mass, h its height above the pivot (weights sit ABOVE the pivot: h > 0)
  Md   restoring moment sum(m_i * -z_i) of the whole tilting body incl. the weights at x = 0 (kg m)
  I    inertia about the pivot, point masses from index.html + rider's own inertia (assumed)
  c    viscous damping, from an assumed damping ratio zeta (no damper on the v4 chair)

Every number marked ASSUMED / 추정 is a guess that must be measured on the real chair.
"""
import json, math, os, re, subprocess, sys, tempfile
from dataclasses import dataclass, asdict, field
from datetime import datetime

G = 9.81
HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
OUT = os.path.join(HERE, "out")

# ---- numbers from index.html balance() (80 kg rider, CG 100 mm below the pivots), extracted 2026-11-04 with node ----
INDEX = dict(mp=14.44, hp=0.1249, mr=18.61, hr=0.1559, Mdp=30.61, Mxp=0.0028, Mdr=27.59, Myr=-0.3007,
             Ip=25.45, Ir=29.06, xmax=0.600, ymax=0.565, restP=0.005, restR=-0.62,
             maxP=(15.81, -15.80), maxR=(20.31, -21.41), Tp=1.83, Tr=2.06)

# ---- drive (index.html: WGM40C-315724 1/218 ~25 rpm, HTD5M 20T pulley = 100 mm per turn) ----
MOTOR_RPM = 25.0          # ASSUMED: 550 rpm (fastest listed) x 10 / 218 -> ~25 rpm at no load; real loaded rpm lower
PULLEY_MM_PER_REV = 100.0  # HTD5M 20T: 20 teeth x 5 mm
RIDER_OWN_I = dict(pitch=5.0, roll=4.0)   # ASSUMED kg m^2: seated 80 kg body about its own CG (index.html uses a point mass)
ZETA = 0.03               # ASSUMED damping ratio without a damper (pillow blocks + rider), 추정
RIDER_KG, RIDER_CG_BELOW = 80.0, 0.100    # index.html defaults
CAGE_SHIFT_M = -0.049                     # index.html: rider/cage body sits 49 mm behind the pitch axis
# Frames: index.html uses x fwd, y LEFT. Everything returned here is in the FIRMWARE frame:
#   roll + = right side down (roll weight + = toward the right), pitch + = nose up (pitch weight + = toward the rear).


def extract_from_index():
    """Run index.html's own geometry + balance() code in node and return its numbers (keeps this file honest)."""
    src = open(os.path.join(REPO, "index.html"), encoding="utf-8").read()
    a = src.index("// ======================= MODEL DATA"); b = src.index("// ======================= SCENE")
    c = src.index("// ======================= CALCULATIONS"); d = src.index("const f1=", c)
    js = ('const $=id=>({value: id==="inM"?"%g":"%g"});\n' % (RIDER_KG, RIDER_CG_BELOW * 1000) + src[a:b] + src[c:d] +
          "\nconst B=balance();console.log(JSON.stringify({mp:B.mp,hp:B.hp,mr:B.mr,hr:B.hr,Mdp:B.Mdp,Mxp:B.Mxp,Mdr:B.Mdr,Myr:B.Myr,"
          "Ip:B.Ip,Ir:B.Ir,xmax:B.xmax,ymax:B.ymax,restP:B.restP,restR:B.restR,maxP:B.maxP,maxR:B.maxR,Tp:B.Tp,Tr:B.Tr}));")
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False, encoding="utf-8") as f:
        f.write(js); p = f.name
    try:
        return json.loads(subprocess.check_output(["node", p], text=True))
    finally:
        os.unlink(p)


@dataclass
class Axis:
    name: str
    m: float        # moving weight kg
    h: float        # weight height above pivot m
    Md: float       # restoring moment kg m (weights at centre)
    Mx0: float      # rest imbalance kg m
    I0: float       # inertia about pivot kg m^2 (weights at centre)
    xmax: float     # weight travel +- m
    zeta: float = ZETA

    @property
    def K(self):            # rad -> N m stiffness at 0 deg
        return G * self.Md

    @property
    def wn(self):
        return math.sqrt(self.K / self.I0)

    @property
    def period(self):
        return 2 * math.pi / self.wn

    @property
    def c(self):
        return 2 * self.zeta * math.sqrt(self.K * self.I0)

    def eq_deg(self, x):
        return math.degrees(math.atan2(self.Mx0 + self.m * x, self.Md))

    def x_for_deg(self, th_deg):
        return (math.tan(math.radians(th_deg)) * self.Md - self.Mx0) / self.m

    def gain_deg_per_mm(self, th_deg=0.0):     # d th / d x at an angle (static), deg per mm
        t = math.radians(th_deg)
        return math.degrees(self.m / self.Md * math.cos(t) ** 2) / 1000

    def accel(self, th, om, x, xdd):
        I = self.I0 + self.m * x * x
        tq = G * (self.Mx0 + self.m * x) * math.cos(th) - G * self.Md * math.sin(th) - self.m * self.h * xdd - self.c * om
        return tq / I


class Plant:
    """Integrates one axis. Hard stop (rubber) at +-31 deg modelled as a stiff spring-damper."""
    STOP_DEG = 31.0

    def __init__(self, ax: Axis, th_deg=None):
        self.ax = ax
        self.x = 0.0; self.v = 0.0
        self.th = math.radians(ax.eq_deg(0.0) if th_deg is None else th_deg); self.om = 0.0

    def step(self, dt, v_cmd, rider_tq=0.0):
        """v_cmd = weight velocity (m/s) the belt actually moves at this step (worm drive: no back-drive)."""
        xdd = (v_cmd - self.v) / dt
        self.v = v_cmd
        self.x = max(-self.ax.xmax, min(self.ax.xmax, self.x + v_cmd * dt))
        n = 4
        for _ in range(n):
            h = dt / n
            a = self.ax.accel(self.th, self.om, self.x, xdd) + rider_tq / (self.ax.I0)
            s = math.radians(self.STOP_DEG)
            if abs(self.th) > s:
                a += (-(abs(self.th) - s) * 4000 * math.copysign(1, self.th) - 60 * self.om) / self.ax.I0
            self.om += a * h; self.th += self.om * h
        return math.degrees(self.th)


def axes(src=INDEX, rider_kg=RIDER_KG, rider_cg_below=RIDER_CG_BELOW):
    dM = (rider_kg - RIDER_KG) * rider_cg_below + RIDER_KG * (rider_cg_below - RIDER_CG_BELOW)
    dI = (rider_kg * rider_cg_below ** 2 - RIDER_KG * RIDER_CG_BELOW ** 2)
    Mxp = src["Mxp"] + (rider_kg - RIDER_KG) * CAGE_SHIFT_M      # rider sits behind the pitch axis (index frame, + = fwd)
    pitch = Axis("pitch", src["mp"], src["hp"], src["Mdp"] + dM, -Mxp, src["Ip"] + RIDER_OWN_I["pitch"] * rider_kg / RIDER_KG + dI, src["xmax"])
    roll = Axis("roll", src["mr"], src["hr"], src["Mdr"] + dM, -src["Myr"], src["Ir"] + RIDER_OWN_I["roll"] * rider_kg / RIDER_KG + dI, src["ymax"])
    return pitch, roll


def weight_speed(rpm=MOTOR_RPM, mm_rev=PULLEY_MM_PER_REV):
    return rpm * mm_rev / 60 / 1000   # m/s


def move_profile(ax, x_target, v_max, a_max, T=20.0, dt=0.002, zeta=None):
    """Open-loop: weight moves 0 -> x_target with a trapezoid (a_max = inf -> velocity step). Returns t, th, x."""
    if zeta is not None:
        ax = Axis(**{**asdict(ax), "zeta": zeta})
    p = Plant(ax, th_deg=ax.eq_deg(0)); v = 0.0; ts, ths, xs = [], [], []
    t = 0.0
    while t < T:
        rem = x_target - p.x
        v_des = math.copysign(min(v_max, math.sqrt(2 * a_max * abs(rem)) if math.isfinite(a_max) else v_max), rem) if abs(rem) > 1e-5 else 0.0
        if math.isfinite(a_max):
            v += max(-a_max * dt, min(a_max * dt, v_des - v))
        else:
            v = v_des if abs(rem) > v_max * dt else rem / dt
        p.step(dt, v); t += dt
        ts.append(t); ths.append(math.degrees(p.th)); xs.append(p.x)
    return ts, ths, xs


def residual_swing(ts, ths, t_from):
    seg = [a for t, a in zip(ts, ths) if t >= t_from]
    return (max(seg) - min(seg)) / 2 if seg else 0.0


def torque_needed(ax, pulley_r_m=0.0159, tilt_deg=31.0, mu=0.03, a=0.1):
    """Belt pull to hold/move the weight at the rubber stop angle (worst case) and the output shaft torque."""
    F = ax.m * (G * math.sin(math.radians(tilt_deg)) + mu * G * math.cos(math.radians(tilt_deg)) + a)
    return F, F * pulley_r_m


def analyse():
    pitch, roll = axes()
    v = weight_speed()
    res = dict(created=datetime.now().isoformat(timespec="seconds"), frame="firmware: roll + = right side down, pitch + = nose up",
               inputs=dict(index_numbers=INDEX, motor_rpm=MOTOR_RPM, pulley_mm_per_rev=PULLEY_MM_PER_REV,
                           rider_own_inertia=RIDER_OWN_I, zeta=ZETA, rider_kg=RIDER_KG, rider_cg_below_m=RIDER_CG_BELOW,
                           assumed=["motor rpm 25 (no-load estimate)", "rider own inertia", "damping ratio 0.03",
                                    "axes independent (roll/pitch coupling ignored)", "belt has no slip/stretch"]),
               weight_speed_mm_s=v * 1000, axes={})
    for ax in (pitch, roll):
        g0 = ax.gain_deg_per_mm(0); rate0 = g0 * v * 1000
        th_max = ax.eq_deg(ax.xmax)
        t_full = ax.xmax / v
        x10 = ax.x_for_deg(10.0)
        F, Tq = torque_needed(ax)
        ts, ths, _ = move_profile(ax, ax.x_for_deg(10.0), v, float("inf"), T=20)
        t_end = x10 / v
        sw_step = residual_swing(ts, ths, t_end + 1.0)
        a_rec = v / ax.period
        ts2, ths2, _ = move_profile(ax, ax.x_for_deg(10.0), v, a_rec, T=24)
        sw_ramp = residual_swing(ts2, ths2, t_end + ax.period + 1.0)
        res["axes"][ax.name] = dict(
            m_kg=ax.m, Md_kgm=ax.Md, I_kgm2=ax.I0, period_s=ax.period, wn_rad_s=ax.wn, zeta=ax.zeta,
            gain_deg_per_mm=g0, gain_mm_per_deg=1 / g0, max_tilt_deg=[ax.eq_deg(ax.xmax), ax.eq_deg(-ax.xmax)],
            max_rate_deg_s_at_0=rate0, max_rate_deg_s_at_max=ax.gain_deg_per_mm(th_max) * v * 1000,
            time_centre_to_end_s=t_full, time_0_to_10deg_s=t_end,
            residual_swing_deg_velocity_step=sw_step, residual_swing_deg_ramped=sw_ramp,
            recommended_weight_accel_mm_s2=a_rec * 1000,
            belt_pull_N_at_31deg=F, shaft_torque_Nm_20T=Tq, shaft_torque_kgfcm_20T=Tq / 0.0981)
    # rider sensitivity
    sens = {}
    for kg, zc in ((60, 0.10), (80, 0.10), (100, 0.10), (80, 0.05), (80, 0.20)):
        p, r = axes(rider_kg=kg, rider_cg_below=zc)
        sens[f"{kg}kg_cg{int(zc*1000)}mm"] = dict(pitch_rest=p.eq_deg(0), pitch_max=[p.eq_deg(p.xmax), p.eq_deg(-p.xmax)],
                                                 roll_rest=r.eq_deg(0), roll_max=[r.eq_deg(r.xmax), r.eq_deg(-r.xmax)],
                                                 pitch_rate=p.gain_deg_per_mm() * v * 1000, roll_rate=r.gain_deg_per_mm() * v * 1000,
                                                 pitch_T=p.period, roll_T=r.period)
    res["rider_sensitivity"] = sens
    # speed options (all need torque / self-lock checks)
    opts = []
    for label, rpm, mm in (("현재: 1/218 + 20T", 25, 100), ("1/218 + 30T 풀리", 25, 150), ("감속비 약 1/100 + 20T (추정 55 rpm)", 55, 100),
                           ("감속비 약 1/100 + 30T", 55, 150), ("1/28 + 20T (약 196 rpm)", 196, 100)):
        vv = rpm * mm / 60 / 1000
        opts.append(dict(option=label, weight_mm_s=vv * 1000, pitch_deg_s=pitch.gain_deg_per_mm() * vv * 1000,
                         roll_deg_s=roll.gain_deg_per_mm() * vv * 1000, shaft_torque_scale=mm / 100))
    res["speed_options"] = opts
    # rate available at the edge of the cue range (pitch 14, roll 18 deg): cos^2 lowers it
    pr = pitch.gain_deg_per_mm(14.0) * v * 1000
    rr = roll.gain_deg_per_mm(18.0) * v * 1000
    res["cue_8deg_s_realistic"] = False
    res["recommended_cue"] = dict(
        rate_deg_s=dict(pitch=round(0.9 * pr, 2), roll=round(0.9 * rr, 2), note="0.9 x achievable at the soft limit (pitch 14, roll 18 deg)"),
        accel_deg_s2=dict(pitch=round(0.9 * pr / pitch.period, 2), roll=round(0.9 * rr / roll.period, 2)),
        soft_limit_deg=dict(pitch=[-14.0, 14.0], roll=[-18.0, 18.0]),
        prefilter_lowpass_s=0.5,
        washout_proposal=dict(note="for sim/server.py Chair (not edited here): tilt coordination + attitude hint with washout",
                              pitch="LP(1.0 s)[57.3*0.8*ax_g] + 0.2*HP(15 s)[theta]",
                              roll="LP(1.0 s)[57.3*0.8*ay_g] + 0.25*HP(15 s)[phi]",
                              rate_limit="as rate_deg_s above, not 8 deg/s"))
    return res, pitch, roll


def plots(pitch, roll, v):
    import matplotlib; matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, axs = plt.subplots(1, 2, figsize=(11, 4), sharey=False)
    for a, ax in zip(axs, (pitch, roll)):
        x10 = ax.x_for_deg(10.0)
        for lab, acc, z, sty in (("velocity step, zeta 0.03", float("inf"), 0.03, "-"), (f"accel ramp v/T, zeta 0.03", v / ax.period, 0.03, "-"),
                                 ("velocity step, zeta 0.10", float("inf"), 0.10, "--")):
            ts, ths, _ = move_profile(ax, x10, v, acc, T=22, zeta=z)
            a.plot(ts, ths, sty, label=lab, lw=1.6)
        a.axhline(10, color="0.6", lw=0.8, ls=":")
        a.set_title(f"{ax.name}: weights 0 -> 10 deg position ({x10*1000:.0f} mm) at {v*1000:.0f} mm/s")
        a.set_xlabel("time (s)"); a.set_ylabel("tilt (deg)"); a.grid(alpha=0.3); a.legend(fontsize=8)
    fig.tight_layout(); p = os.path.join(OUT, "chair_open_loop.png"); fig.savefig(p, dpi=110); plt.close(fig)
    return p


def main():
    global INDEX
    if "--from-index" in sys.argv:
        INDEX = {**INDEX, **extract_from_index()}
    os.makedirs(OUT, exist_ok=True)
    res, pitch, roll = analyse()
    v = res["weight_speed_mm_s"] / 1000
    res["png"] = os.path.relpath(plots(pitch, roll, v), REPO).replace("\\", "/")
    with open(os.path.join(OUT, "chair_model.json"), "w", encoding="utf-8") as f:
        json.dump(res, f, indent=1, ensure_ascii=False)
    print(f"weight speed {res['weight_speed_mm_s']:.1f} mm/s  (motor {MOTOR_RPM} rpm x {PULLEY_MM_PER_REV:.0f} mm/rev, ASSUMED)")
    for k, a in res["axes"].items():
        print(f"{k:5s}: {a['gain_mm_per_deg']:.1f} mm/deg, max rate {a['max_rate_deg_s_at_0']:.2f} deg/s, max tilt {a['max_tilt_deg'][0]:+.1f}/{a['max_tilt_deg'][1]:+.1f} deg,"
              f" 0->10 deg {a['time_0_to_10deg_s']:.1f} s, period {a['period_s']:.2f} s, swing after velocity step {a['residual_swing_deg_velocity_step']:.2f} deg"
              f" / ramped {a['residual_swing_deg_ramped']:.2f} deg, shaft torque at 31 deg {a['shaft_torque_kgfcm_20T']:.1f} kgf cm")
    print("8 deg/s cue realistic?", res["cue_8deg_s_realistic"])
    print("recommended cue:", json.dumps(res["recommended_cue"]["rate_deg_s"]), json.dumps(res["recommended_cue"]["accel_deg_s2"]))
    for o in res["speed_options"]:
        print(f"  {o['option']}: {o['weight_mm_s']:.0f} mm/s -> pitch {o['pitch_deg_s']:.1f}, roll {o['roll_deg_s']:.1f} deg/s (torque x{o['shaft_torque_scale']:.1f})")
    for k, s in res["rider_sensitivity"].items():
        print(f"  rider {k}: pitch rest {s['pitch_rest']:+.1f} max {s['pitch_max'][0]:+.1f}/{s['pitch_max'][1]:+.1f}, roll max {s['roll_max'][0]:+.1f}/{s['roll_max'][1]:+.1f}, rates {s['pitch_rate']:.2f}/{s['roll_rate']:.2f} deg/s, T {s['pitch_T']:.2f}/{s['roll_T']:.2f} s")


if __name__ == "__main__":
    main()
