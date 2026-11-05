"""Simulation core shared by server.py (real time, network) and the offline playtest harness (playtest/run.py, faster
than real time): JSBSim F-16 setup per start mode, controls (+ beginner stability assist), chair cue, state packet.

Start modes: air (6000 ft, 350 kt, heading 000), runway (06R threshold + 150 m, stopped), approach (9 km final,
1550 ft above the field, 180 kt, gear up), downwind (left-hand traffic pattern for runway 06R: 3 km left of the
centre line, abeam mid-runway, heading 232, 1500 ft above the field, 250 kt), air_high (12000 ft, 400 kt, G lesson).
"""
import math
import jsbsim
from airfield import FIELD_FT, GEOID_N, RWY, LAT0, LON0, rwy_point

DT = 1 / 120
START = dict(lat=LAT0, lon=LON0, alt_ft=6000, kts=350, hdg=0.0, rwy_hdg=RWY["hdg"])
CHAIR_LIM = (18.0, 14.0)                  # roll, pitch limits (deg) = control/chair_model.py recommendation (chair_bridge enforces the same)
CHAIR_RATE = (1.3, 0.95)                  # deg/s  (physical chair can do ~1.61 / 1.13, estimate)
CHAIR_ACC = (0.6, 0.48)                   # deg/s^2
CHAIR_LP = 0.5                            # s, low-pass on the cue target
MODES = ("air", "runway", "approach", "downwind", "air_high")
# beginner stability assist: bank / pitch limits (rolls back only from beyond the limit); half-speed sim is a separate option
ASSIST_BANK, ASSIST_PITCH_UP, ASSIST_PITCH_DN = 45.0, 20.0, -15.0


def new_fdm(mode="air", at=None):
    fdm = jsbsim.FGFDMExec(jsbsim.get_default_root_dir())
    fdm.set_debug_level(0)
    fdm.set_dt(DT)
    fdm.load_model("f16")
    fdm["ic/lat-geod-deg"], fdm["ic/long-gc-deg"] = START["lat"], START["lon"]
    fdm["ic/psi-true-deg"] = START["hdg"]
    fdm["ic/terrain-elevation-ft"] = FIELD_FT
    if mode in ("runway", "approach"):
        fdm["ic/psi-true-deg"] = RWY["hdg"]
    if mode == "approach":                       # 9 km before the 06R threshold, 3 deg path
        fdm["ic/lat-geod-deg"], fdm["ic/long-gc-deg"] = rwy_point(-9000.0)
    if mode == "downwind":
        fdm["ic/lat-geod-deg"], fdm["ic/long-gc-deg"] = rwy_point(1400.0, -3000.0)
        fdm["ic/psi-true-deg"] = (RWY["hdg"] + 180.0) % 360
    if mode == "runway":
        fdm["ic/h-agl-ft"] = 4.0
        fdm["ic/vc-kts"] = 0
        fdm["ic/theta-deg"] = 0
    elif mode == "approach":
        fdm["ic/h-sl-ft"] = FIELD_FT + 1550
        fdm["ic/vc-kts"] = 180
        fdm["ic/gamma-deg"] = 0
    elif mode == "air_high":                     # G / aerobatics lesson: room below
        fdm["ic/h-sl-ft"] = 12000
        fdm["ic/vc-kts"] = 400
        fdm["ic/gamma-deg"] = 0
    elif mode == "downwind":
        fdm["ic/h-sl-ft"] = FIELD_FT + 1500
        fdm["ic/vc-kts"] = 250
        fdm["ic/gamma-deg"] = 0
    else:
        fdm["ic/h-sl-ft"] = START["alt_ft"]
        fdm["ic/vc-kts"] = START["kts"]
        fdm["ic/gamma-deg"] = 0
    if at:                                       # 'place' (checks / instructor): air start anywhere, dict(lat, lon, alt_m, hdg, kts)
        fdm["ic/lat-geod-deg"], fdm["ic/long-gc-deg"] = at["lat"], at["lon"]
        fdm["ic/h-sl-ft"] = at["alt_m"] / 0.3048
        fdm["ic/psi-true-deg"] = at.get("hdg", 0.0)
        fdm["ic/vc-kts"] = at.get("kts", 300.0)
        fdm["ic/gamma-deg"] = 0
    fdm.run_ic()
    fdm["propulsion/set-running"] = -1           # start all engines
    fdm["gear/gear-cmd-norm"] = 1 if mode == "runway" else 0
    if mode == "runway":
        fdm["fcs/throttle-cmd-norm"] = 0.0
    else:
        fdm["simulation/do_simple_trim"] = 1       # level flight trim: sets throttle + pitch trim
    return fdm


class Chair:
    """Motion cue for the weight-shift chair: tilt toward the aircraft attitude (scaled) + sustained accelerations,
    low-passed (CHAIR_LP), then followed with the chair's real rate / acceleration limits (CHAIR_RATE / CHAIR_ACC)
    inside CHAIR_LIM (values from control/chair_model.py, docs/chair-control.html)."""
    def __init__(self):
        self.roll = self.pitch = 0.0
        self.vr = self.vp = 0.0
        self.tr = self.tp = 0.0

    @staticmethod
    def _follow(x, v, tgt, rate, acc, dt):
        # accelerate toward the speed that stops exactly at the target, within rate / accel limits
        want = max(-rate, min(rate, math.copysign(math.sqrt(2 * acc * abs(tgt - x)), tgt - x)))
        v += max(-acc * dt, min(acc * dt, want - v))
        return x + v * dt, v

    def update(self, phi_deg, theta_deg, ax_g, ay_g, dt):
        tgt_r = max(-CHAIR_LIM[0], min(CHAIR_LIM[0], 0.35 * phi_deg + 25 * ay_g))
        tgt_p = max(-CHAIR_LIM[1], min(CHAIR_LIM[1], 0.30 * theta_deg + 20 * ax_g))
        k = min(1.0, dt / CHAIR_LP)
        self.tr += (tgt_r - self.tr) * k
        self.tp += (tgt_p - self.tp) * k
        self.roll, self.vr = self._follow(self.roll, self.vr, self.tr, CHAIR_RATE[0], CHAIR_ACC[0], dt)
        self.pitch, self.vp = self._follow(self.pitch, self.vp, self.tp, CHAIR_RATE[1], CHAIR_ACC[1], dt)
        self.roll = max(-CHAIR_LIM[0], min(CHAIR_LIM[0], self.roll))
        self.pitch = max(-CHAIR_LIM[1], min(CHAIR_LIM[1], self.pitch))
        return self.roll, self.pitch


class Sim:
    """one flight: fdm + controls + chair. frame() = 1/60 s of real time (2 fdm steps, 1 with the slow-motion assist)."""
    def __init__(self, mode="air", terrain=None):
        self.ctrl = dict(ail=0.0, elev=0.0, rud=0.0, thr=0.0, brk_l=0.0, brk_r=0.0, gear=0.0)
        # terrain: None = JSBSim's ground is the flat field elevation everywhere (default, playtest), or a function
        # (lat, lon) -> MSL height in m (server.py, vworld ground mode: Copernicus DEM, terrain_dem.py) applied every frame
        self.terrain = terrain
        self.terrain_m = None
        self.reset(mode)

    def reset(self, mode, at=None):
        self.mode = mode if mode in MODES else "air"
        self.fdm = new_fdm(self.mode, at if self.mode == "air" else None)
        self.chair = Chair()
        self.ctrl.update(ail=0.0, elev=0.0, rud=0.0, brk_l=0.0, brk_r=0.0)
        self.ctrl["gear"] = 1.0 if self.mode == "runway" else 0.0
        self.ctrl["thr"] = self.thr_init = self.fdm["fcs/throttle-cmd-norm"]
        self.applied = dict(self.ctrl)
        self.set_terrain()

    def apply(self, assist=False):
        f, c = self.fdm, dict(self.ctrl)
        if assist:
            phi, th = math.degrees(f["attitude/phi-rad"]), math.degrees(f["attitude/theta-rad"])
            on_ground = any(f["gear/unit[%d]/WOW" % i] > 0.5 for i in range(3))
            if not on_ground:
                if abs(c["ail"]) < 0.05 and abs(phi) > ASSIST_BANK:   # stick centred beyond the limit: roll back to it
                    c["ail"] = max(-0.15, min(0.15, -0.012 * (phi - math.copysign(ASSIST_BANK, phi))))
                if phi > ASSIST_BANK and c["ail"] > 0 or phi < -ASSIST_BANK and c["ail"] < 0:
                    c["ail"] = -0.01 * (phi - math.copysign(ASSIST_BANK, phi))
                if th > ASSIST_PITCH_UP and c["elev"] < 0:
                    c["elev"] = 0.02 * (th - ASSIST_PITCH_UP)
                if th < ASSIST_PITCH_DN and c["elev"] > 0:
                    c["elev"] = 0.02 * (th - ASSIST_PITCH_DN)
        f["fcs/aileron-cmd-norm"] = c["ail"]
        f["fcs/elevator-cmd-norm"] = c["elev"]
        f["fcs/rudder-cmd-norm"] = c["rud"]
        f["fcs/throttle-cmd-norm"] = c["thr"]
        f["fcs/left-brake-cmd-norm"] = c["brk_l"]
        f["fcs/right-brake-cmd-norm"] = c["brk_r"]
        f["gear/gear-cmd-norm"] = c["gear"]
        self.applied = c

    def set_terrain(self):
        """JSBSim terrain elevation = DEM height under the aircraft (the ground callback is a level plane at that
        height, refreshed every frame = 60 Hz; 500 kt moves 4 m per frame, 1/8 of the DEM spacing)."""
        if self.terrain is None:
            return
        f = self.fdm
        self.terrain_m = float(self.terrain(f["position/lat-geod-deg"], f["position/long-gc-deg"]))
        f["position/terrain-elevation-asl-ft"] = self.terrain_m / 0.3048

    def frame(self, assist=False, slow=False):
        self.apply(assist)
        self.set_terrain()
        for _ in range(1 if slow else 2):
            self.fdm.run()

    def packet(self, dt=1 / 60):
        f = self.fdm
        g = 32.174
        ax, ay = f["accelerations/a-pilot-x-ft_sec2"] / g, f["accelerations/a-pilot-y-ft_sec2"] / g
        phi, th, psi = math.degrees(f["attitude/phi-rad"]), math.degrees(f["attitude/theta-rad"]), math.degrees(f["attitude/psi-rad"])
        cr, cp = self.chair.update(phi, th, ax, ay, dt)
        c = self.ctrl
        lat, lon = f["position/lat-geod-deg"], f["position/long-gc-deg"]
        n, e = (lat - START["lat"]) * 110950.0, (lon - START["lon"]) * 111320.0 * math.cos(math.radians(START["lat"]))
        h = math.radians(RWY["hdg"])
        along, cross = n * math.cos(h) + e * math.sin(h), -n * math.sin(h) + e * math.cos(h)   # from the start point, runway axes
        return dict(along_m=along + 150.0, cross_m=cross,                                       # along = m past the 06R threshold
                    t=f.get_sim_time(), lat=f["position/lat-geod-deg"], lon=f["position/long-gc-deg"], alt_m=f["position/h-sl-ft"] * 0.3048,
                    agl_m=f["position/h-agl-ft"] * 0.3048, phi=phi, theta=th, psi=psi, kts=f["velocities/vc-kts"], mach=f["velocities/mach"],
                    vs_fpm=f["velocities/h-dot-fps"] * 60, alpha=f["aero/alpha-deg"], nz=-f["accelerations/n-pilot-z-norm"],
                    thr=f["fcs/throttle-cmd-norm"], gear=f["gear/gear-pos-norm"], ax=ax, ay=ay, chair_roll=cr, chair_pitch=cp, chair_tgt=[round(self.chair.tr, 2), round(self.chair.tp, 2)], chair_rate=CHAIR_RATE,
                    lat0=START["lat"], lon0=START["lon"], field_m=FIELD_FT * 0.3048, geoid_n=GEOID_N,
                    rwy_hdg=RWY["hdg"], beta=f["aero/beta-deg"], gamma=math.degrees(f["flight-path/gamma-rad"]),
                    p_dps=math.degrees(f["velocities/p-rad_sec"]), q_dps=math.degrees(f["velocities/q-rad_sec"]),
                    wow=any(f["gear/unit[%d]/WOW" % i] > 0.5 for i in range(3)) and f["position/h-agl-ft"] < 13.0,   # JSBSim keeps WOW after liftoff while the gear retracts
                    thr_init=self.thr_init, gear_init=1.0 if self.mode == "runway" else 0.0,
                    ail=c["ail"], elev=c["elev"], rud=c["rud"], brk=(c["brk_l"] + c["brk_r"]) / 2, brk_l=c["brk_l"], brk_r=c["brk_r"],
                    gear_cmd=c["gear"], chair_lim=CHAIR_LIM, mode=self.mode)
