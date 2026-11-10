"""Cockpit view feel (sim_client): head motion from G, look into the turn, engine vibration, turbulence / runway
rumble, and the engine / wind sound. Everything is small on purpose (cm and tenths of a degree).

Comfort: the motion is OFF in VR (the headset owns the view; moving the world around the head makes people sick) and
OFF while the motion chair runs (it already moves the body). Chair = the chair bridge (control/chair_bridge.py) holds
UDP 127.0.0.1:4210 on this PC (checked every 5 s by trying to bind it), or GYROSIM_CHAIR=1 (=0 forces 'no chair').
Canopy scratch glints faint and only near the sun, cockpit paint matte (CANOPY / COCKPIT_LOOK, GYROSIM_CKLOOK=0 = before).
GYROSIM_COCKPIT=0: start in the eye view without the cockpit and no head motion (the old feel). GYROSIM_SHAKE=0: cockpit
kept, head motion off. GYROSIM_SOUND=0: no sound.

Head motion (body axes, cm; spring 1.6 Hz, damping 0.7 = the head lags and settles):
  forward accel ax g  -> head back 2.0 cm/g;  side accel ay g -> head the other way 2.5 cm/g;  +G -> head down 1.2 cm/g
Look into the turn: yaw toward the low wing up to 6 deg in steady banks (fades in 10..30 deg bank), slight pitch-up in
a pull (0.15 deg per deg/s, max 3), 1.2 s smoothing. Engine buzz 0.02 deg x throttle. Turbulence: three slow sines
(0.4 / 0.9 / 1.7 Hz) up to 1.2 cm / 0.25 deg pitch / 0.35 deg roll, scaled by airspeed and fading above 300 m AGL to
30 % at 3000 m. On the runway: rumble with ground speed.
"""
import math
import os
import random
import socket
import time

import unreal

COCKPIT_ON = os.environ.get("GYROSIM_COCKPIT", "1") != "0"
SHAKE_ON = COCKPIT_ON and os.environ.get("GYROSIM_SHAKE", "1") != "0"
SOUND_ON = os.environ.get("GYROSIM_SOUND", "1") != "0"
CHAIR_PORT = 4210
# canopy (realism v3 glass + fx layer): scratch glints only close to the sun direction and faint (v3: Gain 3, GlintPow 10)
LOOK_ON = os.environ.get("GYROSIM_CKLOOK", "1") != "0"
CANOPY = dict(Gain=float(os.environ.get("GYROSIM_CANOPY_GAIN", "0.35")), GlintPow=40.0, AnisoPow=10.0)
# cockpit paint (M_CkSurface instances): matte painted metal, no grazing sheen, darker, edges worn on the canopy bow;
# glare shield / panels dark matte (11-10 review: the bow read as smooth plastic, the coaming as glossy)
COCKPIT_LOOK = {
    "MI_Frame": dict(Tint=(0.014, 0.015, 0.016), Rough=0.9, RoughVar=0.1, Sheen=0.0, Polish=0.0, Spec=0.15, Wear=0.25, EdgeGain=1.0),
    "MI_Metal": dict(Tint=(0.18, 0.18, 0.18), Rough=0.6, Sheen=0.0),          # bolt heads on the bow: dull, not white
    "MI_Chrome": dict(Tint=(0.35, 0.35, 0.35), Rough=0.35),
    "MI_AntiGlare": dict(Rough=0.96, RoughVar=0.05, Sheen=0.0, Polish=0.0, Spec=0.2),
    "MI_Panel": dict(Rough=0.88, Sheen=0.0, Polish=0.3, Spec=0.3),
    "MI_Paint": dict(Tint=(0.07, 0.075, 0.075), Rough=0.8, Sheen=0.0, Polish=0.3, Spec=0.35),
    "MI_Paint2": dict(Rough=0.8, Sheen=0.0, Polish=0.3, Spec=0.35),
    "MI_Wall": dict(Rough=0.8, Sheen=0.0, Polish=0.3, Spec=0.35),
    "MI_Black": dict(Rough=0.8, Sheen=0.0, Spec=0.35),
    "MI_HUDFrame": dict(Rough=0.8, Sheen=0.0, Polish=0.2, Spec=0.35),
    "MI_Bezel": dict(Rough=0.7, Sheen=0.0, Spec=0.35),
}
SND = dict(engine="/Game/Aircraft/Sounds/SW_EngineLoop", wind="/Game/Aircraft/Sounds/SW_WindLoop")


def _log(*a):
    unreal.log("[view_fx] " + " ".join(str(x) for x in a))


def _cl(v, lo, hi):
    return lo if v < lo else hi if v > hi else v


def _f(s, k, d=0.0):
    try:
        v = s.get(k, d)
        return float(v) if v is not None else d
    except Exception:
        return d


class ViewFx:
    def __init__(self):
        self.pos = [0.0, 0.0, 0.0]
        self.vel = [0.0, 0.0, 0.0]
        self.look = [0.0, 0.0]
        self.t = 0.0
        self.ph = [random.random() * 6.2832 for _ in range(16)]
        self.chair = False
        self.chair_t = -1e9
        self.why = ""
        self.out = ((0.0, 0.0, 0.0), (0.0, 0.0, 0.0))
        self.snd = {}
        self.snd_world = None
        self.spool = None
        self.hidden_eye = None

    # ---- comfort gates ------------------------------------------------------------------------------------------
    def chair_active(self, now):
        env = os.environ.get("GYROSIM_CHAIR", "")
        if env in ("0", "1"):
            return env == "1"
        if now - self.chair_t < 5.0:
            return self.chair
        self.chair_t = now
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.bind(("127.0.0.1", CHAIR_PORT))
            on = False
        except OSError:
            on = True                                         # the chair bridge holds the port
        finally:
            s.close()
        if on != self.chair:
            _log("motion chair", "running - head motion off" if on else "not running")
        self.chair = on
        return on

    # ---- head motion ----------------------------------------------------------------------------------------------
    def update(self, s, dt, hmd, view, now):
        """returns ((dx, dy, dz) cm in body axes for the eye point, (dpitch, dyaw, droll) deg for the view camera)."""
        dt = _cl(dt, 0.0, 0.1)
        self.t += dt
        live = SHAKE_ON and view == "cockpit" and not hmd and s is not None and not s.get("paused") and not s.get("crashed")
        why = "vr" if hmd else ("chair" if self.chair_active(now) else ("" if live else "off"))
        if why != self.why:
            self.why = why
            _log("head motion", "on" if not why else "off (%s)" % why)
        if why:
            live = False
        k = 2 * math.pi * 1.6
        if live:
            ax, ay, nz = _f(s, "ax"), _f(s, "ay"), _f(s, "nz", 1.0)
            tgt = [_cl(-2.0 * ax, -3.0, 3.0), _cl(-2.5 * ay, -3.0, 3.0), _cl(-1.2 * (nz - 1.0), -5.0, 2.0)]
        else:
            tgt = [0.0, 0.0, 0.0]
        for i in range(3):                                    # damped spring (semi-implicit Euler)
            a = k * k * (tgt[i] - self.pos[i]) - 2 * 0.7 * k * self.vel[i]
            self.vel[i] += a * dt
            self.pos[i] += self.vel[i] * dt
        if live and not s.get("wow"):
            phi = _f(s, "phi")
            fade = _cl((abs(phi) - 10.0) / 20.0, 0.0, 1.0)
            lt = [_cl(0.15 * _f(s, "q_dps"), -2.0, 3.0), _cl(0.1 * phi, -6.0, 6.0) * fade]
        else:
            lt = [0.0, 0.0]
        kk = 1.0 - math.exp(-dt / 1.2)
        self.look = [self.look[i] + (lt[i] - self.look[i]) * kk for i in range(2)]
        dp = dr = dz = 0.0
        if live:
            kts, thr = _f(s, "kts"), _f(s, "thr")
            T = self.t
            ph = self.ph
            buzz = 0.02 * (0.3 + thr)
            dp += buzz * math.sin(2 * math.pi * 17.3 * T + ph[0]) * math.sin(2 * math.pi * 0.7 * T + ph[1])
            dr += buzz * math.sin(2 * math.pi * 19.1 * T + ph[2]) * math.sin(2 * math.pi * 0.5 * T + ph[3])
            if s.get("wow"):
                g = _cl(kts / 150.0, 0.0, 1.0)
                dz += 0.4 * g * (math.sin(2 * math.pi * 9.0 * T + ph[4]) * 0.6 + math.sin(2 * math.pi * 13.7 * T + ph[5]) * 0.4)
                dp += 0.06 * g * math.sin(2 * math.pi * 7.3 * T + ph[6])
            else:
                agl = _f(s, "agl_m", 1000.0)
                alt_f = 1.0 if agl < 300 else max(0.3, 1.0 - 0.7 * (agl - 300.0) / 2700.0)
                spd_f = _cl(kts / 300.0, 0.0, 1.3)
                tb = spd_f * alt_f
                w = lambda f, p: math.sin(2 * math.pi * f * T + p)          # noqa: E731
                n1 = 0.5 * w(0.4, ph[7]) + 0.3 * w(0.9, ph[8]) + 0.2 * w(1.7, ph[9])
                n2 = 0.5 * w(0.37, ph[10]) + 0.3 * w(1.1, ph[11]) + 0.2 * w(1.9, ph[12])
                n3 = 0.5 * w(0.45, ph[13]) + 0.3 * w(0.8, ph[14]) + 0.2 * w(1.5, ph[15])
                dz += 1.2 * tb * n1
                dp += 0.25 * tb * n2
                dr += 0.35 * tb * n3
        self.out = ((self.pos[0], self.pos[1], self.pos[2] + dz), (self.look[0] + dp, self.look[1], dr))
        return self.out

    # ---- eye view: cockpit and airframe not drawn -------------------------------------------------------------------
    def eye_view(self, world, aircraft, on):
        """component visibility of the aircraft and everything attached (actor hidden flags stay with sim_client)."""
        if aircraft is None or self.hidden_eye == on:
            return
        if self.hidden_eye is None:                           # new Play world: nothing of ours is hidden there
            self.eye_hid = []
        self.hidden_eye = on
        try:
            if on:                                            # hide what is visible now, remember it
                acts = [aircraft] + list(aircraft.get_attached_actors(True, True) if hasattr(aircraft, "get_attached_actors") else [])
                self.eye_hid = [c for a in acts for c in a.get_components_by_class(unreal.PrimitiveComponent) if c.is_visible()]
                for c in self.eye_hid:
                    c.set_visibility(False, False)
            else:                                             # give back exactly those
                for c in getattr(self, "eye_hid", []):
                    c.set_visibility(True, False)
                self.eye_hid = []
            _log("eye view (no cockpit)" if on else "cockpit drawn", len(getattr(self, "eye_hid", [])), "components")
        except Exception as e:
            _log("eye view", repr(e))

    # ---- canopy: scratch glints toned down (realism v3 had Gain 3 = bright arcs over the whole sky) ------------------
    def canopy(self, world, now):
        """every 1 s: canopy and cockpit materials that are not our dynamic instances (a preset change re-sets them)
        get one with our values (CANOPY / COCKPIT_LOOK); set_look(False) puts the old values back (A/B shots)."""
        if world is None or now - getattr(self, "ck_t", -1e9) < 1.0:
            return
        self.ck_t = now
        try:
            if getattr(self, "look_world", None) is not world:
                self.look_world, self.look_mids, self.look_on = world, [], LOOK_ON
            acts = list(unreal.GameplayStatics.get_all_actors_with_tag(world, "Canopy"))
            ac = unreal.GameplayStatics.get_all_actors_with_tag(world, "Aircraft")
            if ac:
                acts += [a for a in ac[0].get_attached_actors(True, True) if a not in acts]
            n, names = 0, set()
            for a in acts:
                for smc in a.get_components_by_class(unreal.StaticMeshComponent):
                    for i in range(smc.get_num_materials()):
                        m = smc.get_material(i)
                        if m is None or isinstance(m, unreal.MaterialInstanceDynamic):
                            continue
                        name = m.get_name()
                        vals = CANOPY if "Canopy" in name else COCKPIT_LOOK.get(name)
                        if vals is None:
                            continue
                        mid = smc.create_dynamic_material_instance(i, m)
                        if not mid:
                            continue
                        old = {k: (mid.get_scalar_parameter_value(k) if not isinstance(v, tuple) else mid.get_vector_parameter_value(k))
                               for k, v in vals.items()}
                        self.look_mids.append((mid, vals, old))
                        self._apply(mid, vals if self.look_on else old)
                        n += 1
                        names.add(name)
            if n:
                _log("look: %d material slots (canopy glints / cockpit paint), on=%s" % (n, self.look_on), sorted(names))
        except Exception as e:
            if not getattr(self, "_ck_err", None):
                self._ck_err = repr(e)
                _log("canopy / cockpit look", repr(e))

    @staticmethod
    def _apply(mid, vals):
        for k, v in vals.items():
            if isinstance(v, tuple):
                mid.set_vector_parameter_value(k, unreal.LinearColor(v[0], v[1], v[2], 1.0))
            elif isinstance(v, unreal.LinearColor):
                mid.set_vector_parameter_value(k, v)
            else:
                mid.set_scalar_parameter_value(k, float(v))

    def set_look(self, on):
        """True = toned-down canopy glints + matte cockpit paint, False = the values before (A/B)."""
        self.look_on = on
        for mid, vals, old in getattr(self, "look_mids", []):
            self._apply(mid, vals if on else old)

    # ---- sound --------------------------------------------------------------------------------------------------
    def sound(self, world, s, dt):
        if not SOUND_ON or world is None:
            return
        try:
            if self.snd_world is not world:
                self.snd_world, self.snd = world, {}
                spawn = getattr(unreal.GameplayStatics, "spawn_sound2d", None) or getattr(unreal.GameplayStatics, "spawn_sound_2d")
                for k, p in SND.items():
                    sw = unreal.load_asset(p)
                    if sw is None:
                        continue
                    ac = spawn(world, sw, 0.05, 1.0, 0.0, None, False, False)
                    if ac:
                        self.snd[k] = [ac, 0.0, 1.0]
                _log("sound", sorted(self.snd))
            if not self.snd:
                return
            run = s is not None and not s.get("paused") and not s.get("crashed")
            thr, kts = (_f(s, "thr"), _f(s, "kts")) if s else (0.0, 0.0)
            if self.spool is None:
                self.spool = thr
            self.spool += (thr - self.spool) * (1.0 - math.exp(-_cl(dt, 0, 0.1) / 1.8))      # engine spools slowly
            want = dict(engine=((0.22 + 0.45 * self.spool) if run else 0.0, 0.75 + 0.55 * self.spool),
                        wind=((_cl((kts - 40.0) / 450.0, 0.0, 1.0) ** 1.4) * 0.9 if run else 0.0, 0.8 + _cl(kts / 900.0, 0.0, 0.8)))
            for k, (v, p) in want.items():
                h = self.snd.get(k)
                if not h:
                    continue
                ac = h[0]
                if abs(v - h[1]) > 0.01:
                    h[1] = v
                    ac.set_volume_multiplier(max(0.0001, v))
                if abs(p - h[2]) > 0.01:
                    h[2] = p
                    ac.set_pitch_multiplier(p)
        except Exception as e:
            if not getattr(self, "_snd_err", None):
                self._snd_err = repr(e)
                _log("sound", repr(e))
