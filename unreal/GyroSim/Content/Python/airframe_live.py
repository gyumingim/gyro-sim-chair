"""Airframe at Play (sim_client calls bind() once per Play world and update() every frame).

Scripts/aircraft/ue_airframe.py put hidden parts on the Aircraft actor in FlightMap: AC_Surf_* (control surfaces, mesh
pivot on the hinge, tag 'axis:x,y,z' = body-axis unit vector whose + rotation moves the trailing edge down / the
rudder to the right) and AC_Light_* (lens spheres). When all of them and /Game/ThirdParty/F16/Airframe/Meshes/F16_Body
exist, the one-piece exterior is swapped for the body without the surfaces and the parts are shown. Anything missing ->
nothing changes (old exterior). GYROSIM_AIRFRAME=0 keeps the old exterior too.

Surfaces follow the stick / pedal commands in the packet (ail, elev, rud; FBW mixing is approximated) with actuator
rate limits; the leading-edge flaps follow alpha; trailing-edge flaps drop with the gear handle down. Lights: steady
red / green / white nav lights, double-flash white strobes, red beacon.
"""
import math
import os
import time

import unreal

BODY = "/Game/ThirdParty/F16/Airframe/Meshes/F16_Body"
PAINT = "/Game/ThirdParty/F16/Airframe/Materials/MI_AF_Paint"
SURFS = ("FlapL", "FlapR", "StabL", "StabR", "LefL", "LefR", "Rudder")
RATE = dict(Flap=60.0, Stab=60.0, Lef=25.0, Rudder=90.0)          # deg/s actuator rate limits (approx.)
LIM = dict(Flap=(-23.0, 20.0), Stab=(-25.0, 25.0), Lef=(-2.0, 25.0), Rudder=(-30.0, 30.0))
ON = os.environ.get("GYROSIM_AIRFRAME", "1") != "0"


def _log(*a):
    unreal.log("[airframe] " + " ".join(str(x) for x in a))


def _tagval(a, key):
    for t in a.tags:
        s = str(t)
        if s.startswith(key):
            return s[len(key):]
    return None


class Airframe:
    def __init__(self):
        self.ok = False
        self.surf = {}
        self.lights = {}
        self.defl = {}
        self.light_on = {}
        self.world = None
        self.ext = None

    def bind(self, world, aircraft):
        self.__init__()
        self.world = world
        if not ON or aircraft is None:
            return
        try:
            body = unreal.load_asset(BODY)                  # (no does_asset_exist: the registry may still be scanning at Play)
            for a in unreal.GameplayStatics.get_all_actors_with_tag(world, "AirframeSurf"):
                n, ax = _tagval(a, "Surf_"), _tagval(a, "axis:")
                if n and ax:
                    self.surf[n] = (a, [float(v) for v in ax.split(",")])
            for a in unreal.GameplayStatics.get_all_actors_with_tag(world, "AirframeLight"):
                n, rgb = _tagval(a, "Light_"), _tagval(a, "rgb:")
                if n:
                    mid = a.static_mesh_component.create_dynamic_material_instance(0)
                    if mid and rgb:
                        c = [float(v) for v in rgb.split(",")]
                        mid.set_vector_parameter_value("Color", unreal.LinearColor(c[0], c[1], c[2], 1.0))
                    self.lights[n] = (a, mid)
            ext = None
            for a in unreal.GameplayStatics.get_all_actors_with_tag(world, "AircraftPart"):
                if a.get_actor_label().startswith("AC_F16_Exterior") if hasattr(a, "get_actor_label") else False:
                    ext = a
            if ext is None:                                   # labels are editor-only in some builds: find by mesh name
                for a in unreal.GameplayStatics.get_all_actors_with_tag(world, "AircraftPart"):
                    c = getattr(a, "static_mesh_component", None)
                    m = c.static_mesh if c else None
                    if m and m.get_name() == "F16_Exterior":
                        ext = a
            if body is None or ext is None or any(s not in self.surf for s in SURFS):
                _log("not complete (body %s, exterior %s, surfaces %s) - old exterior kept" % (bool(body), bool(ext), sorted(self.surf)))
                self.surf, self.lights = {}, {}
                return
            self.ext, self.body, self.orig = ext, body, ext.static_mesh_component.static_mesh
            self.paint = unreal.load_asset(PAINT)
            self.gear = []                                    # landing gear: same painted skin (slot of the F-16 skin)
            for a in unreal.GameplayStatics.get_all_actors_with_tag(world, "Gear"):
                c = getattr(a, "static_mesh_component", None)
                if c and c.static_mesh:
                    self.gear += [(c, i) for i, sl in enumerate(c.static_mesh.static_materials) if str(sl.material_slot_name).lower().endswith("_f16")]
            self.defl = {n: 0.0 for n in SURFS}
            self.set_enabled(True)
            _log("airframe on: body + %d surfaces + %d lights" % (len(self.surf), len(self.lights)))

        except Exception as e:
            _log("bind failed", repr(e))
            self.ok = False

    def set_enabled(self, on):
        """True = body + moving surfaces + lights + painted skin; False = the old one-piece exterior (A/B shots)."""
        if not getattr(self, "ext", None):
            return
        self.ext.static_mesh_component.set_static_mesh(self.body if on else self.orig)
        for c, i in self.gear:
            c.set_material(i, self.paint if (on and self.paint) else c.static_mesh.get_material(i))
        for a, _ in list(self.surf.values()) + list(self.lights.values()):
            a.set_actor_hidden_in_game(not on)
        self.ok = on
        self._placed = False

    def targets(self, s):
        ail, elev, rud = (float(s.get(k, 0.0) or 0.0) for k in ("ail", "elev", "rud"))
        alpha = float(s.get("alpha", 0.0) or 0.0)
        gear_dn = float(s.get("gear_cmd", s.get("gear", 0.0)) or 0.0) > 0.5
        flap = 20.0 if gear_dn and float(s.get("kts", 0.0) or 0.0) < 240 else 0.0
        lef = -2.0 if s.get("wow") else 1.38 * alpha - 2.0
        # right roll (ail +): right flaperon / stabilator trailing edge up, left down; elev + (push): stabs down
        return dict(FlapL=flap + 21.5 * ail, FlapR=flap - 21.5 * ail,
                    StabL=25.0 * elev + 5.0 * ail, StabR=25.0 * elev - 5.0 * ail,
                    LefL=lef, LefR=lef, Rudder=30.0 * rud)

    def update(self, s, dt):
        if not self.ok or s is None:
            return
        try:
            tg = self.targets(s)
            for n, (a, ax) in self.surf.items():
                kind = n.rstrip("LR") if n != "Rudder" else "Rudder"
                lo, hi = LIM[kind]
                t = max(lo, min(hi, tg[n]))
                cur = self.defl.get(n, 0.0)
                step = RATE[kind] * max(dt, 0.0)
                nv = cur + max(-step, min(step, t - cur))
                if abs(nv - cur) < 1e-3 and n in self.defl and getattr(self, "_placed", False):
                    continue
                self.defl[n] = nv
                h = math.radians(nv) / 2.0
                sh = math.sin(h)
                q = unreal.Quat(ax[0] * sh, ax[1] * sh, ax[2] * sh, math.cos(h))
                a.set_actor_relative_rotation(q.rotator(), False, True)
            self._placed = True
            now = time.perf_counter()
            ph = now % 1.2
            strobe = ph < 0.05 or 0.16 < ph < 0.21
            beacon = (now % 1.0) < 0.12
            for n, (a, mid) in self.lights.items():
                want = 40.0 if n.startswith("Nav") or n == "Tail" else (900.0 if n.startswith("Strobe") and strobe else
                                                                       (120.0 if n == "Beacon" and beacon else 0.0))
                if self.light_on.get(n) != want and mid:
                    self.light_on[n] = want
                    mid.set_scalar_parameter_value("Glow", want)
        except Exception as e:
            if not getattr(self, "_err", None):
                self._err = repr(e)
                _log("update", repr(e))
