"""Software-in-the-loop test: the real firmware core (firmware/chair/lib/chair_core/chair_core.c, built as a DLL with zig cc)
drives the chair plant model (control/chair_model.py), and the PC bridge (control/chair_bridge.py) feeds it.

    python control/sil.py            -> runs every scenario, writes control/out/sil_*.png and control/out/sil_results.json

Build needs `pip install ziglang` (no admin). The plant: per-axis weighted pendulum, worm motor = speed source with
deadband + 50 ms lag, AS5600 position sensor with an unknown offset, IMU with noise / bias / mount error.
"""
import ctypes as C, json, math, os, random, subprocess, sys
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
CORE = os.path.join(REPO, "firmware", "chair", "lib", "chair_core")
OUT = os.path.join(HERE, "out")
BUILD = os.path.join(OUT, "build")
sys.path.insert(0, HERE)
import chair_model as cm
from chair_bridge import Bridge, Config, parse_telemetry, frame

NAX = 2
F2 = C.c_float * NAX


class Params(C.Structure):
    _fields_ = [("v_full_mm_s", F2), ("v_max_mm_s", F2), ("a_max_mm_s2", F2), ("duty_min", C.c_float), ("kp_x", C.c_float),
                ("ki_th", C.c_float), ("trim_max_mm", C.c_float), ("kd_gyro", C.c_float), ("travel_mm", F2), ("soft_margin_mm", C.c_float),
                ("k_design", F2), ("rate_max_deg_s", F2), ("soft_lim_deg", F2), ("return_rate_deg_s", C.c_float),
                ("fault_angle_deg", F2), ("fault_angle_ms", C.c_uint32), ("pc_timeout_ms", C.c_uint32), ("imu_timeout_ms", C.c_uint32),
                ("pos_jump_mm", C.c_float), ("stall_ms", C.c_uint32), ("stall_mm", C.c_float), ("cal_step_mm", C.c_float),
                ("cal_settle_ms", C.c_uint32), ("cal_avg_ms", C.c_uint32), ("cal_level_tol_deg", C.c_float), ("home_speed_frac", C.c_float),
                ("comp_tau_s", C.c_float), ("lp_tau_s", C.c_float)]


class Inputs(C.Structure):
    _fields_ = [("now_ms", C.c_uint32), ("imu_ok", C.c_uint8), ("acc", C.c_float * 3), ("gyro", C.c_float * 3),
                ("pos_ok", C.c_uint8 * NAX), ("pos_raw_mm", F2), ("lim_pos", C.c_uint8 * NAX), ("lim_neg", C.c_uint8 * NAX),
                ("index", C.c_uint8 * NAX), ("estop_ok", C.c_uint8), ("pins_stowed", C.c_uint8), ("deck_stowed", C.c_uint8)]


class Outputs(C.Structure):
    _fields_ = [("duty", F2), ("state", C.c_uint8), ("faults", C.c_uint32), ("buzzer", C.c_uint8), ("led", C.c_uint8), ("save_nvs", C.c_uint8)]


def build():
    os.makedirs(BUILD, exist_ok=True)
    dll = os.path.join(BUILD, "chair_core.dll")
    src = [os.path.join(CORE, "chair_core.c")]
    if not os.path.exists(dll) or os.path.getmtime(dll) < max(os.path.getmtime(s) for s in src + [os.path.join(CORE, "chair_core.h")]):
        subprocess.check_call([sys.executable, "-m", "ziglang", "cc", "-std=c99", "-O2", "-Wall", "-Wextra", "-shared", "-DCORE_DLL",
                               "-o", dll] + src)
    lib = C.CDLL(dll)
    lib.core_sizeof.restype = C.c_int
    lib.core_rx_line.argtypes = [C.c_void_p, C.c_char_p, C.c_uint32]
    lib.core_tx_line.argtypes = [C.c_void_p, C.c_char_p, C.c_int]
    lib.core_step.argtypes = [C.c_void_p, C.POINTER(Inputs), C.POINTER(Outputs)]
    lib.core_init.argtypes = [C.c_void_p, C.POINTER(Params)]
    lib.core_default_params.argtypes = [C.POINTER(Params)]
    lib.core_state_name.restype = C.c_char_p
    return lib


LIB = None


class Sil:
    DT_MS = 5

    def __init__(self, rider_kg=80.0, rider_cg=0.10, start_x=(0.0, 0.0), v_scale=0.9, seed=1, params=None, imu_bias=(0.8, -0.5)):
        global LIB
        if LIB is None:
            LIB = build()
        self.lib = LIB
        self.P = Params(); self.lib.core_default_params(C.byref(self.P))
        if params:
            for k, v in params.items():
                setattr(self.P, k, v)
        self.core = C.create_string_buffer(self.lib.core_sizeof())
        self.lib.core_init(self.core, C.byref(self.P))
        pitch, roll = cm.axes(rider_kg=rider_kg, rider_cg_below=rider_cg)
        self.pl = [cm.Plant(roll), cm.Plant(pitch)]           # index 0 roll, 1 pitch (same as the firmware)
        for i in range(2):
            self.pl[i].x = start_x[i]
            self.pl[i].th = math.radians(self.pl[i].ax.eq_deg(start_x[i]))
        self.v = [0.0, 0.0]
        self.v_full = [41.7 * v_scale, 41.7 * v_scale]          # real motor 10 % slower than the firmware thinks
        self.deadband = 0.06
        self.off = [123.4, -77.7]                               # AS5600 unwrap offset (unknown to the firmware)
        self.rng = random.Random(seed)
        self.imu_bias = imu_bias                                # mounting error deg (roll, pitch)
        self.gyro_bias = (0.3, -0.2)
        self.t_ms = 0
        self.sw = dict(estop_ok=True, pins_stowed=False, deck_stowed=False, imu_ok=True, pos_ok=[True, True], lim_broken=[False, False])
        self.rider_tq = [0.0, 0.0]
        self.locked = True
        self.inp = Inputs(); self.out = Outputs()
        self.log = []
        self.rx_q = []
        self.saved = 0

    def set_switches(self, **kw):
        self.sw.update(kw)
        if "pins_stowed" in kw:
            self.locked = not kw["pins_stowed"]

    def rx(self, line):
        self.lib.core_rx_line(self.core, line.encode("ascii"), self.t_ms)

    def tx(self):
        b = C.create_string_buffer(256)
        n = self.lib.core_tx_line(self.core, b, 256)
        return b.value.decode("ascii") if n > 0 else None

    def step(self):
        self.t_ms += self.DT_MS
        dt = self.DT_MS / 1000
        I = self.inp
        I.now_ms = self.t_ms
        roll, pitch = self.pl
        # IMU (on the cage), x fwd y left z up; specific force for the gimbal (roll outside, pitch inside)
        ph = roll.th + math.radians(self.imu_bias[0]); th = pitch.th + math.radians(self.imu_bias[1])
        n = lambda s: self.rng.gauss(0, s)
        f = (math.sin(th) * math.cos(ph) + n(0.004), math.sin(ph) + n(0.004), math.cos(th) * math.cos(ph) + n(0.004))
        I.imu_ok = 1 if self.sw["imu_ok"] else 0
        for k in range(3):
            I.acc[k] = f[k] if self.sw["imu_ok"] else 0.0
        I.gyro[0] = math.degrees(roll.om) * math.cos(pitch.th) + self.gyro_bias[0] + n(0.1)
        I.gyro[1] = -math.degrees(pitch.om) + self.gyro_bias[1] + n(0.1)
        I.gyro[2] = 0.0
        for i, p in enumerate(self.pl):
            trav = p.ax.xmax * 1000
            I.pos_ok[i] = 1 if self.sw["pos_ok"][i] else 0
            I.pos_raw_mm[i] = round((p.x * 1000 + self.off[i]) / 0.0244) * 0.0244
            I.lim_pos[i] = 1 if (p.x * 1000 >= trav - 5 or self.sw["lim_broken"][i]) else 0
            I.lim_neg[i] = 1 if (p.x * 1000 <= -trav + 5 or self.sw["lim_broken"][i]) else 0
            I.index[i] = 1 if abs(p.x * 1000) < 3.0 else 0
        I.estop_ok = 1 if self.sw["estop_ok"] else 0
        I.pins_stowed = 1 if self.sw["pins_stowed"] else 0
        I.deck_stowed = 1 if self.sw["deck_stowed"] else 0
        self.lib.core_step(self.core, C.byref(I), C.byref(self.out))
        if self.out.save_nvs:
            self.saved += 1
        # actuators: worm motor = speed source (self-locking: duty 0 or no power -> weight stays)
        for i, p in enumerate(self.pl):
            d = self.out.duty[i] if self.sw["estop_ok"] else 0.0
            mag = max(0.0, abs(d) - self.deadband) / (1 - self.deadband)
            v_tgt = math.copysign(mag * self.v_full[i], d) / 1000
            self.v[i] += (v_tgt - self.v[i]) * dt / 0.05
            if abs(self.v[i]) < 1e-6 and v_tgt == 0:
                self.v[i] = 0.0
            if self.locked:                                   # lock pin in: chair held at 0 deg
                p.x = max(-p.ax.xmax, min(p.ax.xmax, p.x + self.v[i] * dt)); p.th = 0.0; p.om = 0.0
            else:
                p.step(dt, self.v[i], self.rider_tq[i])
        self.log.append((self.t_ms / 1000, math.degrees(roll.th), math.degrees(pitch.th), roll.x * 1000, pitch.x * 1000,
                         self.out.state, self.out.faults, self.out.duty[0], self.out.duty[1]))

    def run_until(self, t_s):
        lines = []
        while self.t_ms / 1000 < t_s:
            self.step()
            if self.t_ms % 50 == 0:
                l = self.tx()
                if l:
                    lines.append(l)
        return lines

    def state(self):
        return self.lib.core_state_name(self.out.state).decode()


class Harness:
    """Sil + Bridge connected like the real thing (bridge at 50 Hz, telemetry at 20 Hz), cue function of time."""

    def __init__(self, sil: Sil, cfg=None):
        self.s = sil
        self.b = Bridge(cfg or Config())
        self.cue = lambda t: (0.0, 0.0)
        self.udp_on = True
        self.rec = []
        self.next_send = 0.0

    def run(self, until):
        while self.s.t_ms / 1000 < until:
            t = self.s.t_ms / 1000
            if t >= self.next_send:
                if self.udp_on:
                    r, p = self.cue(t)
                    self.b.on_udp(json.dumps(dict(roll=r, pitch=p)).encode(), t)
                for line in self.b.tick(t):
                    self.s.rx(line)
                self.next_send += 0.02
            self.s.step()
            if self.s.t_ms % 50 == 0:
                line = self.s.tx()
                if line:
                    T = self.b.on_line(line, self.s.t_ms / 1000)
                    if T:
                        self.rec.append((T["ms"] / 1000, self.b.target["roll"], self.b.target["pitch"], self.b.out["roll"], self.b.out["pitch"],
                                         T["ref_r"], T["ref_p"], T["roll"], T["pitch"], T["state"]))

    def cmd(self, w):
        self.b.command(w)

    def wait_state(self, st, timeout):
        t_end = self.s.t_ms / 1000 + timeout
        while self.s.t_ms / 1000 < t_end:
            self.run(self.s.t_ms / 1000 + 0.1)
            if self.s.state() == st:
                return True
        return False


def boot_and_calibrate(h: Harness, results, tag):
    s = h.s
    h.run(2.0)
    assert s.state() == "LOCKED", s.state()
    h.cmd("ZERO"); h.run(2.5)
    s.set_switches(pins_stowed=True, deck_stowed=True)   # pins out into their holders, deck parked
    h.run(3.0)
    assert s.state() == "IDLE", s.state()
    t0 = s.t_ms / 1000
    h.cmd("CAL")
    ok = h.wait_state("READY", 200)
    h.run(s.t_ms / 1000 + 0.3)                             # let one telemetry frame through
    T = h.b.tel
    results[tag + "_cal"] = dict(ok=ok, time_s=s.t_ms / 1000 - t0, k_r=T["k_r"], k_p=T["k_p"], max_r=T["max_r"], max_p=T["max_p"],
                                 true_k_r=s.pl[0].ax.m / s.pl[0].ax.Md / 1000, true_k_p=s.pl[1].ax.m / s.pl[1].ax.Md / 1000,
                                 roll_after=T["roll"], pitch_after=T["pitch"], true_roll=s.log[-1][1], true_pitch=s.log[-1][2], saved=s.saved)
    return ok


def plot_run(h: Harness, path, title, t_from=0.0):
    import matplotlib; matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    L = [r for r in h.s.log if r[0] >= t_from]
    R = [r for r in h.rec if r[0] >= t_from]
    fig, ax = plt.subplots(3, 1, figsize=(11, 8), sharex=True)
    t = [r[0] for r in L]
    for k, (nm, ci, ti, ri, si) in enumerate((("roll", 1, 1, 5, 1), ("pitch", 2, 2, 6, 2))):
        a = ax[k]
        a.plot([r[0] for r in R], [r[ci] for r in R], color="0.65", lw=1, label="sim cue (UDP)")
        a.plot([r[0] for r in R], [r[3 + k] for r in R], "--", color="#d9822b", lw=1.2, label="bridge shaped cue")
        a.plot([r[0] for r in R], [r[ri] for r in R], ":", color="#6c5ce7", lw=1.2, label="firmware reference")
        a.plot(t, [r[si] for r in L], color="#2f6fd6", lw=1.6, label="chair angle (plant)")
        a.set_ylabel(f"{nm} (deg)"); a.grid(alpha=0.3); a.legend(fontsize=7, loc="upper right")
    a = ax[2]
    a.plot(t, [r[3] for r in L], label="roll weight x (mm)"); a.plot(t, [r[4] for r in L], label="pitch weight x (mm)")
    a2 = a.twinx(); a2.step(t, [r[5] for r in L], color="0.5", lw=0.8, where="post"); a2.set_yticks(range(9))
    a2.set_yticklabels(["BOOT", "IDLE", "LOCKED", "CAL", "READY", "RUN", "RETURN", "FAULT", "ESTOP"], fontsize=7)
    a.set_xlabel("time (s)"); a.set_ylabel("mm"); a.grid(alpha=0.3); a.legend(fontsize=7, loc="upper left")
    fig.suptitle(title); fig.tight_layout(); fig.savefig(path, dpi=105); plt.close(fig)


def lag_and_gain(rec, k, t0, t1, freq):
    """fit sine at freq to cue (bridge input) and chair angle -> amplitude ratio and lag (s)."""
    import numpy as np
    R = [r for r in rec if t0 <= r[0] <= t1]
    t = np.array([r[0] for r in R]); u = np.array([r[1 + k] for r in R]); y = np.array([r[7 + k] for r in R])
    def fit(z):
        A = np.c_[np.sin(2 * np.pi * freq * t), np.cos(2 * np.pi * freq * t), np.ones_like(t)]
        c, *_ = np.linalg.lstsq(A, z, rcond=None)
        return math.hypot(c[0], c[1]), math.atan2(c[1], c[0])
    au, pu = fit(u); ay, py = fit(y)
    lag = ((pu - py) % (2 * math.pi)) / (2 * math.pi * freq)
    return ay / au, lag


def main():
    os.makedirs(OUT, exist_ok=True)
    res = dict(created=datetime.now().isoformat(timespec="seconds"), inputs=dict(core="firmware/chair/lib/chair_core/chair_core.c",
               plant="control/chair_model.py (80 kg rider unless noted, zeta 0.03, motor 10 % slower than assumed, IMU mount error 0.8/-0.5 deg)"))
    checks = []

    def check(name, cond, info=""):
        checks.append(dict(name=name, ok=bool(cond), info=info)); print(("PASS " if cond else "FAIL ") + name, info)

    # 1. boot, zero, calibrate (weights start off-centre), steps
    h = Harness(Sil(start_x=(0.20, -0.10)))
    ok = boot_and_calibrate(h, res, "step")
    c = res["step_cal"]
    check("calibration completes", ok, f"{c['time_s']:.0f} s")
    check("calibrated k within 10 % (roll)", abs(c["k_r"] / c["true_k_r"] - 1) < 0.1, f"{c['k_r']:.3e} vs {c['true_k_r']:.3e}")
    check("calibrated k within 10 % (pitch)", abs(c["k_p"] / c["true_k_p"] - 1) < 0.1, f"{c['k_p']:.3e} vs {c['true_k_p']:.3e}")
    check("level after calibration (true angle, includes IMU mount error removed by ZERO)", abs(c["true_roll"]) < 0.5 and abs(c["true_pitch"]) < 0.5,
          f"roll {c['true_roll']:.2f} pitch {c['true_pitch']:.2f}")
    t_cal = h.s.t_ms / 1000
    h.cmd("ARM"); h.run(t_cal + 1)
    check("ARM -> RUN", h.s.state() == "RUN", h.s.state())
    ts = t_cal + 2
    h.cue = lambda t: (10.0 if ts <= t < ts + 25 else 0.0, 8.0 if ts <= t < ts + 25 else 0.0)
    h.run(ts + 50)
    L = [r for r in h.s.log if ts <= r[0] <= ts + 25]
    def t_reach(idx, val):
        for r in L:
            if r[idx] >= val:
                return r[0] - ts
        return None
    rr, rp = t_reach(1, 9.0), t_reach(2, 7.2)
    over_r = max(r[1] for r in L) - 10; over_p = max(r[2] for r in L) - 8
    res["step"] = dict(t90_roll_s=rr, t90_pitch_s=rp, overshoot_roll_deg=over_r, overshoot_pitch_deg=over_p,
                       final_roll=h.s.log[-1][1], final_pitch=h.s.log[-1][2])
    check("step 10 deg roll reaches 90 %", rr is not None, f"{rr} s")
    check("step 8 deg pitch reaches 90 %", rp is not None, f"{rp} s")
    check("step overshoot < 0.5 deg", over_r < 0.5 and over_p < 0.5, f"roll {over_r:.2f} pitch {over_p:.2f}")
    plot_run(h, os.path.join(OUT, "sil_step.png"), "SIL: boot - zero (pins in) - calibration - ARM - step roll 10 / pitch 8 deg")

    # 2. sine
    h.cue = lambda t: (8 * math.sin(2 * math.pi * 0.02 * (t - ts)), 6 * math.sin(2 * math.pi * 0.05 * (t - ts)))
    t1 = h.s.t_ms / 1000
    h.run(t1 + 110)
    gr, lr = lag_and_gain(h.rec, 0, t1 + 30, t1 + 110, 0.02)
    gp, lp = lag_and_gain(h.rec, 1, t1 + 30, t1 + 110, 0.05)
    res["sine"] = dict(roll_0p02Hz_8deg=dict(gain=gr, lag_s=lr), pitch_0p05Hz_6deg=dict(gain=gp, lag_s=lp))
    check("sine roll 0.02 Hz 8 deg tracks (gain > 0.8)", gr > 0.8, f"gain {gr:.2f} lag {lr:.1f} s")
    check("sine pitch 0.05 Hz 6 deg (rate 1.9 deg/s > limit -> attenuated, informative)", True, f"gain {gp:.2f} lag {lp:.1f} s")
    plot_run(h, os.path.join(OUT, "sil_sine.png"), "SIL: sine cues (roll 8 deg 0.02 Hz, pitch 6 deg 0.05 Hz) — rate limited chair", t_from=t1)

    # 3. watchdog: whole PC (bridge) stops -> firmware returns to level by itself
    t2 = h.s.t_ms / 1000
    h.cue = lambda t: (12.0, 10.0)
    h.run(t2 + 20)
    ang_before = (h.s.log[-1][1], h.s.log[-1][2])
    t_cut = h.s.t_ms / 1000
    while h.s.t_ms / 1000 < t_cut + 40:     # no bridge packets at all
        h.s.step()
    res["watchdog"] = dict(before=ang_before, after=(h.s.log[-1][1], h.s.log[-1][2]), state=h.s.state())
    check("watchdog: no packets -> RETURN -> READY level", h.s.state() == "READY" and abs(h.s.log[-1][1]) < 0.6 and abs(h.s.log[-1][2]) < 0.6,
          f"{ang_before[0]:.1f}/{ang_before[1]:.1f} -> {h.s.log[-1][1]:.2f}/{h.s.log[-1][2]:.2f}, {h.s.state()}")
    h.next_send = h.s.t_ms / 1000
    plot_run(h, os.path.join(OUT, "sil_watchdog.png"), "SIL: PC packets stop at %.0f s -> firmware levels the chair slowly" % t_cut, t_from=t2)

    # 3b. deadman in the bridge: only the sim stops (bridge keeps the heartbeat) -> shaped cue ramps to 0
    h.run(h.s.t_ms / 1000 + 1); h.cmd("ARM"); h.run(h.s.t_ms / 1000 + 1)
    h.cue = lambda t: (10.0, 0.0); t3 = h.s.t_ms / 1000; h.run(t3 + 15)
    h.udp_on = False; h.run(t3 + 40)
    check("bridge deadman: sim UDP stops -> level while staying in RUN", h.s.state() == "RUN" and abs(h.s.log[-1][1]) < 0.6,
          f"{h.s.state()} roll {h.s.log[-1][1]:.2f}")
    h.udp_on = True

    # 4. e-stop mid tilt: weights stop where they are (worm self-lock), RESET -> slow return
    h.cue = lambda t: (12.0, 0.0); t4 = h.s.t_ms / 1000; h.run(t4 + 12)
    h.s.set_switches(estop_ok=False); h.run(t4 + 20)
    a_es = h.s.log[-1][1]; x_es = h.s.log[-1][3]
    h.cue = lambda t: (-15.0, 0.0); h.run(t4 + 26)
    check("e-stop: state ESTOP, weight does not move", h.s.state() == "ESTOP" and abs(h.s.log[-1][3] - x_es) < 0.5, f"x {x_es:.1f} -> {h.s.log[-1][3]:.1f}")
    h.s.set_switches(estop_ok=True); h.run(t4 + 28)
    check("e-stop released: still ESTOP until RESET", h.s.state() == "ESTOP")
    h.cmd("RESET"); h.run(t4 + 60)
    check("RESET after e-stop -> RETURN -> READY level", h.s.state() == "READY" and abs(h.s.log[-1][1]) < 0.6, f"{h.s.state()} roll {h.s.log[-1][1]:.2f}")
    plot_run(h, os.path.join(OUT, "sil_estop.png"), "SIL: e-stop at %.0f s (chair stays tilted), released + RESET at %.0f s -> slow return" % (t4 + 12, t4 + 28), t_from=t4 - 2)

    # 5. lock pin / deck interlock: no motion, cal cleared
    h.cmd("ARM"); h.run(h.s.t_ms / 1000 + 1)
    h.s.sw["deck_stowed"] = False; t5 = h.s.t_ms / 1000
    x5 = (h.s.log[-1][3], h.s.log[-1][4])
    h.cue = lambda t: (10.0, 10.0); h.run(t5 + 10)
    check("deck switch open -> LOCKED, no weight motion", h.s.state() == "LOCKED" and abs(h.s.log[-1][3] - x5[0]) < 0.5 and abs(h.s.log[-1][4] - x5[1]) < 0.5)
    h.cmd("CAL"); h.run(t5 + 12)
    check("CAL refused while LOCKED", h.s.state() == "LOCKED")
    h.s.sw["deck_stowed"] = True; h.run(t5 + 13)
    h.cmd("ARM"); h.run(t5 + 15)
    check("after LOCKED, ARM refused until a new calibration (new rider)", h.s.state() == "IDLE", h.s.state())

    # 6. IMU failure while running -> FAULT -> position-only return to the level position
    tc = h.s.t_ms / 1000; h.cmd("CAL"); h.wait_state("READY", 200); res["recal_time_s"] = h.s.t_ms / 1000 - tc; h.cmd("ARM"); h.run(h.s.t_ms / 1000 + 1)
    h.cue = lambda t: (10.0, -8.0); t6 = h.s.t_ms / 1000; h.run(t6 + 15)
    h.s.sw["imu_ok"] = False; h.run(t6 + 50)
    check("IMU lost -> FAULT, weights back to the level position", h.s.state() == "FAULT" and abs(h.s.log[-1][1]) < 1.0 and abs(h.s.log[-1][2]) < 1.0,
          f"{h.s.state()} roll {h.s.log[-1][1]:.2f} pitch {h.s.log[-1][2]:.2f}")
    h.s.sw["imu_ok"] = True; h.cmd("RESET"); h.run(t6 + 52)
    check("RESET from FAULT -> IDLE (calibrate again)", h.s.state() == "IDLE", h.s.state())
    plot_run(h, os.path.join(OUT, "sil_imu_fault.png"), "SIL: IMU lost at %.0f s -> FAULT -> position-only return" % (t6 + 15), t_from=t6 - 2)

    # 7. heavy rider with low CG + stall (blocked belt)
    h7 = Harness(Sil(rider_kg=105, rider_cg=0.15, start_x=(-0.3, 0.25), seed=3))
    ok7 = boot_and_calibrate(h7, res, "heavy")
    c7 = res["heavy_cal"]
    check("heavy rider (105 kg, CG 150 mm): calibration ok, k within 10 %", ok7 and abs(c7["k_r"] / c7["true_k_r"] - 1) < 0.1 and abs(c7["k_p"] / c7["true_k_p"] - 1) < 0.1,
          f"k_r {c7['k_r']:.3e}/{c7['true_k_r']:.3e} k_p {c7['k_p']:.3e}/{c7['true_k_p']:.3e}, max roll {c7['max_r']}, max pitch {c7['max_p']}")
    h7.cmd("ARM"); h7.run(h7.s.t_ms / 1000 + 1)
    h7.cue = lambda t: (20.0, 15.0); t7 = h7.s.t_ms / 1000; h7.run(t7 + 30)
    mr = max(r[1] for r in h7.s.log if r[0] > t7); mp = max(r[2] for r in h7.s.log if r[0] > t7)
    check("heavy rider: cue 20/15 clipped to achievable - 1 deg, no FAULT", h7.s.state() == "RUN" and mr < c7["max_r"][1] and mp < c7["max_p"][1],
          f"max roll {mr:.1f} (achievable {c7['max_r'][1]:.1f}), pitch {mp:.1f} ({c7['max_p'][1]:.1f})")
    h7.cue = lambda t: (0.0, 0.0); h7.run(t7 + 33)
    h7.s.v_full[1] = 0.0                                     # pitch belt jammed
    h7.run(t7 + 40)
    check("stall (pitch jammed) -> FAULT STALL_P", h7.s.state() == "FAULT" and (h7.s.out.faults & 0x20), f"{h7.s.state()} faults {h7.s.out.faults:#x}")

    # 8. rider leans hard (disturbance torque) during RUN: trim loop holds the angle
    h8 = Harness(Sil(seed=5))
    boot_and_calibrate(h8, res, "lean")
    h8.cmd("ARM"); h8.run(h8.s.t_ms / 1000 + 1)
    t8 = h8.s.t_ms / 1000; h8.cue = lambda t: (5.0, 0.0); h8.run(t8 + 15)
    for k in range(1, 101):                                  # rider shifts 3 cm sideways (~24 N m) over 0.5 s
        h8.s.rider_tq[0] = 9.81 * 80 * 0.03 * k / 100; h8.run(t8 + 15 + 0.005 * k)
    h8.run(t8 + 45)
    pk = max(r[1] for r in h8.s.log if r[0] > t8 + 15)
    res["lean"] = dict(peak_roll=pk, final_roll=h8.s.log[-1][1])
    check("rider leans 3 cm: angle restored by trim within 0.5 deg", abs(h8.s.log[-1][1] - 5.0) < 0.5, f"roll {h8.s.log[-1][1]:.2f}, peak {pk:.1f} (no damper)")
    plot_run(h8, os.path.join(OUT, "sil_lean.png"), "SIL: rider leans 3 cm at %.0f s, the trim loop moves the weight to hold 5 deg" % (t8 + 15), t_from=t8 - 2)

    res["checks"] = checks
    res["passed"] = sum(c["ok"] for c in checks); res["total"] = len(checks)
    with open(os.path.join(OUT, "sil_results.json"), "w", encoding="utf-8") as f:
        json.dump(res, f, indent=1, ensure_ascii=False, default=float)
    print(f"{res['passed']}/{res['total']} checks passed")
    return 0 if res["passed"] == res["total"] else 1


if __name__ == "__main__":
    sys.exit(main())
