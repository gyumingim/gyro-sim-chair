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
# 11-13 clear glass from inside (cockpit A/B: hiding the canopy alone removed the whole yellow-brown cast): the V3 glass had an
# amber Beer-path tint (TintCol (1, 0.85, 0.58) x TintAmt 0.3, up to 3x the path at grazing angles) - the F-16 gold coating is
# an OUTSIDE reflection look - and a strong grazing reflection (ReflAmt 0.85) of the dark coaming. Together = brown glow
# along the sills and a dark brown blob above the glare shield behind the HUD. Now neutral (no tint), faint fresnel / sky
# reflection (ReflAmt 0.15; 0.30 since the interior cube below), almost no smudge haze. Eye-point warmth with these = the canopy hidden (scratchpad canopy r3).
CANOPY = dict(Gain=float(os.environ.get("GYROSIM_CANOPY_GAIN", "0.35")), GlintPow=40.0, AnisoPow=10.0,
              TintAmt=0.0, TintCol=(1.0, 1.0, 1.0), ReflAmt=0.30, SmudgeAmt=0.005)
# 11-13 V4 (scratchpad review canopy_fable.md option 1, diag in scratchpad canopy_fix): the milky veil and the angular 'window'
# were NOT reflections - with every reflection term at 0 the ThinTranslucent inner shell (M_CkCanopyV3) still added 40-68/255
# of sky colour (gone when that slot is not drawn). The inner slot now gets M_CkCanopyTrans (modulate: background x (1 - F))
# and the outer additive shell M_CkCanopyV3Fx draws the V4 reflection: F x L with a closed cockpit proxy (sill floor, rear
# bulkhead, pilot spheres) and bright frame rings around the fuselage axis (the bent concentric arcs of canopy photos, c12).
# Physical Fresnel (polycarbonate F0 0.05), no veil / halo / smudge terms. No ray tracing needed (VR-safe).
V4_ON = os.environ.get("GYROSIM_CANOPY_V4", "1") != "0"
# 11-13 smooth canopy: /Game/ThirdParty/F16/Meshes/F16_Glass_Smooth = the same glass (identical vertex positions / bbox)
# subdivided once (simple) with normals transferred from a Catmull-Clark copy (scratchpad canopy_smooth/smooth2.py) - the
# 856-triangle original gave faceted reflections (stair-stepped arcs). GYROSIM_CANOPY_SMOOTH=0 = the original mesh.
# 11-13 (later) that CC-normal mesh measured WORSE (kaleidoscope zebra, normal error p95 ~9 deg; scratchpad canopy_curve):
# /Game/ThirdParty/F16/Meshes/F16_Glass_Fit = a true smooth refit of the original vertices (symmetric cubic-RBF surface per
# piece, original outline, ~2.5 cm remesh, analytic normals, inner shell = parallel 6.3 mm offset, UV0 transferred,
# 16-bit tangent basis; scratchpad canopy_curve/fitmesh2.py). 11-13 user decision: Fit is the default (improved in place).
# GYROSIM_CANOPY_SMOOTH: 1 / fit (default) = F16_Glass_Fit, cc = the old F16_Glass_Smooth, 0 = the original mesh.
_SMOOTH = os.environ.get("GYROSIM_CANOPY_SMOOTH", "fit").strip().lower()
SMOOTH_ON = _SMOOTH != "0"
SMOOTH_MESH = "/Game/ThirdParty/F16/Meshes/" + ("F16_Glass_Smooth" if _SMOOTH == "cc" else "F16_Glass_Fit")
TRANS_MAT = "/Game/Cockpit/Materials/M_CkCanopyTrans"
# 11-13 grey plate over the canopy top (offscreen diag scratchpad canopy_curve/t15): it was the V4 reflection of the outer
# Fx shell (ReflAmt 1 x the closed cockpit proxy: looking up, the mirror ray hits the lit proxy floor) - reflection was meant
# to be OFF (user 11-13). Fx shell ReflAmt 0 unless GYROSIM_CANOPY_FXREFL=1; the inner transmission shell keeps its
# Fresnel loss (background x (1 - F), F0 0.05) and the scratch glints stay.
FX_REFL_ON = os.environ.get("GYROSIM_CANOPY_FXREFL", "0") == "1"
# 11-13 physically based reflection (V5 Fx shader, review canopy_reflection_advice.md), applied live every second
# (ViewFx.refl_live) from the look page (tune_look params, section '캐노피 반사'): cr_on (0/1, default 1 = ON since 11-14, user
# decision; 0 = off), cr_mult (overall x, 1 = physical: two-surface Fresnel ReflAmt 1.9), cr_cube (interior cube gain, 1 = physical),
# cr_lit (live-sun pilot / sunlit-edge layers, 1 = physical), cr_glint (scratch glints / sun spot x). The shader reuses
# inputs: InSun = SunE (directional light lux), LitAbs = SkyE, HaloGlow = LitGain, VeilPow = SunPow, Wobble = CubeMinLod.
REFL_F2 = 1.9                   # ReflAmt for two glass surfaces (the inner shell has no specular)
SKY_E_FRAC = 0.15               # sky illuminance / sun illuminance on an up-facing surface (clear day, estimate)
REFL_ON_VALS = dict(F0=0.05, PilotRefl=1.0, RingGain=1.0, VeilPow=400.0, Wobble=1.0)
if V4_ON:
    CANOPY.update(F0=0.05, ReflAmt=1.0, SmudgeAmt=0.0, HaloGlow=0.0, VeilGlow=0.0, CubeAmt=0.0,
                  RingGain=float(os.environ.get("GYROSIM_CANOPY_RINGS", "0.0")), RingX0=315.0, RingW=3.0, BulkX=300.0)
# 11-13 interior in the glass: the canopy's reflection is drawn by its own outer-shell shader (M_CkCanopyV3Fx: unlit additive,
# the inner ThinTranslucent shell has Specular 0), so engine reflections (Lumen front-layer translucency reflections, reflection
# captures) never reach it - tested, no change. Instead a cube map of the real cockpit is captured at the eye in the aircraft
# frame (SceneCaptureCube at the tub centre, capture_rotation on, pilot / canopy / overlays hidden) into RT_CkCanopyInterior and the shader's
# downward 'inner' reflection (was a flat coaming plane) samples it (CubeAmt). Re-captured every CUBE_S s (the light on the
# panel changes with attitude); 256 px faces. GYROSIM_CANOPY_CUBE=0 = the analytic interior as before.
# 11-13 (later): baked interior cube in the V4 shader (scratchpad review canopy_techniques.md 4.2): captured ONCE at the design
# eye in the aircraft frame, 512 px, sky / fog / clouds black (capture show flags), parallax box = the cockpit; weak gain.
CUBE_ON = os.environ.get("GYROSIM_CANOPY_CUBE", "0") == "1"      # 11-13 user: off by default (busy interior pattern)
CUBE_RT = "/Game/Cockpit/Materials/RT_CkCanopyInterior"
CUBE_S = float(os.environ.get("GYROSIM_CANOPY_CUBE_S", "1e9"))     # re-capture period (s); default: once per world
# one-time bake face size (512 showed seam jaggies). 11-13 user: higher is better -> 2048 = the largest that works: the
# engine clamps cube render targets to 2048 in editor builds (UTextureRenderTargetCube::PostEditChangeProperty MaxSize).
CUBE_PX = int(os.environ.get("GYROSIM_CANOPY_CUBE_PX", "2048"))
# 11-14 (FlightMap Play, offscreen A/B, scratchpad canopy_cube_map): a bake on the first Play tick gave large bright planes in
# the glass; the same cube re-baked after the world had loaded gave the faint reflection seen in CockpitView. Cause not found
# (look / light / exposure still settling at the first tick - guess). The one bake now waits CUBE_DELAY s after the capture
# actor is set up; until then the shader gets CubeAmt 0.
CUBE_DELAY = float(os.environ.get("GYROSIM_CANOPY_CUBE_DELAY", "10"))
# 11-13 (review canopy_reflection_advice.md): no direct sun in the bake (the sun direction would be baked in; sunlit parts are
# the live analytic layers in the Fx shader) - sky light + emissive instruments only; HDR (FloatRGBA) + mips.
CUBE_BLACK_FLAGS = ("Atmosphere", "Fog", "Cloud", "VolumetricFog", "DirectionalLights")
CUBE_POS = (412.0, 0.0, 75.0)   # capture point = centre of the ellipsoid proxy below (aircraft-local cm)
# parallax-corrected lookup (11-13, "the dome must bend the interior like a curved mirror"): the shader intersects the
# reflection ray from the canopy pixel with this box around the tub (local cm; canopy 267..558 / +-34 / 63..127, shell
# 370..541 / +-50 / -10..127) and samples the cube with (hit - CUBE_POS) -> near interior parts sit at their real place.
CUBE = dict(CubeAmt=1.0, CubeGain=float(os.environ.get("GYROSIM_CANOPY_CUBE_GAIN", "1.0")),
            PxMode=1.0, PxMin=(252.0, -52.0, 5.0), PxMax=(572.0, 52.0, 145.0), CubePos=CUBE_POS)
# 11-13 proxy: ellipsoid inscribed in PxMin..PxMax (PxMode 1) instead of the box (PxMode 0): no creases where box faces meet.
# Compared with a Blender Cycles 100 %-mirror render of the same cockpit (scratchpad canopy_proxy): mean edge correlation
# ellipsoid 0.23 / sphere 0.20 / box 0.18 over 5 views (all weak; single run).     # gain 4: the dark interior ghosts visibly on the bright sky (look-matched, not measured)
# 11-13 ray-traced canopy reflection (experiment, off; needs r.RayTracing=True, r.SkinCache.CompileShaders=True and SM6 in
# DefaultEngine.ini - those were removed again 11-14 because RT is unused; add them back to try it). When hardware ray
# tracing is available and Lumen is the GI method (monitor preset), the front glass shell (M_CkCanopyV3) gets a real
# specular (SpecAmt / GlassRough params) and Lumen front-layer translucency reflections with hardware ray tracing (hit
# lighting) draw the real cockpit bent by the dome; the fake reflection of the outer shell (ReflAmt, interior cube) is
# switched off. No ray tracing (VR preset, other GPU, GYROSIM_CANOPY_RT=0) -> the cube look above.
RT_WANT = os.environ.get("GYROSIM_CANOPY_RT", "0") == "1"    # 11-13: off by default (Busan GPU load unmeasured, PSU)
RT_CVARS = {"r.Lumen.HardwareRayTracing": 1, "r.Lumen.HardwareRayTracing.LightingMode": 2,
            "r.Lumen.TranslucencyReflections.FrontLayer.EnableForProject": 1, "r.Lumen.TranslucencyReflections.FrontLayer.Enable": 1}
RT_CANOPY = dict(SpecAmt=float(os.environ.get("GYROSIM_CANOPY_SPEC", "1.0")), GlassRough=0.02)
RT_FX = dict(ReflAmt=0.0, CubeAmt=0.0)         # outer shell: scratch glints only
# 'bent mirror' shell (11-13, user request): a copy of the canopy dome (same mesh, 0.5 % smaller about the eye) with a pure
# mirror material (M_CkCanopyMirror: white, metallic 1, roughness 0, dithered opacity MirrorOpacity) - with ray-traced
# reflections it shows what a curved mirror in the canopy's place reflects; at low opacity it blends that over the view.
# GYROSIM_CANOPY_MIRROR = opacity 0..1 (0 = off); only with ray tracing.
MIRROR_MAT = "/Game/Cockpit/Materials/M_CkCanopyMirror"
MIRROR = float(os.environ.get("GYROSIM_CANOPY_MIRROR", "0"))
MIRROR_SHRINK = 0.995


def rt_available():
    try:
        g = unreal.SystemLibrary.get_console_variable_int_value
        return RT_WANT and g("r.RayTracing") == 1 and g("r.DynamicGlobalIlluminationMethod") == 1
    except Exception:
        return False


CUBE_HIDE_TAGS = ("CanopyMirror", "Canopy", "PilotHead", "PilotBody", "Pilot", "HUD", "Overlay", "Minimap", "TutorPanel", "KeyPanel", "CrashBack", "CrashPanel")
# 11-13 (user screenshots, cube gain 3): the reflection showed virtual overlays (Korean beginner callouts, the kneeboard
# training display, ...) and no pilot. The cube now renders a SHOW-ONLY list: physical aircraft parts (actors tagged
# AircraftPart: cockpit shell, frame / bow, sills, instruments, real lights / MFD glow, exterior skin) minus anything
# virtual or glass, and minus the pilot (review canopy_reflection_advice.md: the bake point is inside his torso; the
# helmet / shoulders are live-shaded analytic spheres in the Fx shader). New overlays are excluded automatically unless
# they are tagged AircraftPart. Scratchpad canopy_curve/t20, t21.
CUBE_SHOW_TAG = "AircraftPart"
CUBE_EXCLUDE_TAGS = ("Overlay", "HUD", "Minimap", "TutorPanel", "KeyPanel", "CrashBack", "CrashPanel", "Attribution",
                     "BeginnerLabel", "MFD_C", "Canopy", "CanopyMirror", "CanopyGhost", "SimView", "SimCamera",
                     "PilotHead", "PilotBody", "Pilot")   # pilot: analytic spheres in the shader (the bake point is in his torso)


def cube_content(world, cc):
    """show-only list of the canopy interior cube (physical aircraft parts, no pilot / overlays / glass)"""
    excl = set(CUBE_EXCLUDE_TAGS)
    show = [a for a in unreal.GameplayStatics.get_all_actors_with_tag(world, CUBE_SHOW_TAG)
            if not excl & {str(t) for t in a.tags}]
    cc.set_editor_property("primitive_render_mode", unreal.SceneCapturePrimitiveRenderMode.PRM_USE_SHOW_ONLY_LIST)
    cc.clear_show_only_components()          # (show_only_actors / hidden_actors are not settable from Python on a
    cc.clear_hidden_components()             #  spawned capture: 'cannot be edited on templates' -> component lists)
    for a in show:
        cc.show_only_actor_components(a, True)
    return show
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
                self.look_skip = set()                        # (component, slot, material) seen with no entry: not re-tested
            self.smooth_canopy(world)
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
                        key = (smc, i, m)                     # a new part or a re-set material is a new key: examined again
                        if key in self.look_skip:
                            continue
                        name = m.get_name()
                        vals = self._canopy_vals(name) if "Canopy" in name else COCKPIT_LOOK.get(name)
                        if vals is None:
                            self.look_skip.add(key)
                            continue
                        src = m
                        if V4_ON and name == "M_CkCanopyV3" and not rt_available():   # inner shell -> transmission only
                            src = unreal.load_asset(TRANS_MAT) or m
                        mid = smc.create_dynamic_material_instance(i, src)
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
            self.rt_mode(world)
            self.refl_live(world)
            self.interior_cube(world, now)
        except Exception as e:
            if not getattr(self, "_ck_err", None):
                self._ck_err = repr(e)
                _log("canopy / cockpit look", repr(e))

    def smooth_canopy(self, world):
        """once per world: the canopy component gets the smooth mesh, materials kept per slot name (slot order differs)."""
        if not SMOOTH_ON or getattr(self, "smooth_world", None) is world:
            return
        self.smooth_world = world
        new = unreal.load_asset(SMOOTH_MESH)
        if new is None:
            _log("canopy smooth mesh missing", SMOOTH_MESH)
            return
        for a in unreal.GameplayStatics.get_all_actors_with_tag(world, "Canopy"):
            for c in a.get_components_by_class(unreal.StaticMeshComponent):
                old = c.static_mesh
                if old is None or old == new or old.get_name() != "F16_Glass":
                    continue
                names = [str(n) for n in c.get_material_slot_names()]
                mats = {n: c.get_material(i) for i, n in enumerate(names)}
                c.set_static_mesh(new)
                for n, m in mats.items():
                    if m is not None:
                        c.set_material_by_name(unreal.Name(n), m)
                _log("canopy: smooth mesh", new.get_name())

    def refl_live(self, world):
        """every second: canopy reflection on/off + strengths (look page) and the LIVE sun for the analytic layers"""
        try:
            v = {}
            try:
                import tune_look
                if tune_look.on():
                    v = tune_look.ST.get("applied") or tune_look.values()
            except Exception:
                v = {}
            on = FX_REFL_ON or float(v.get("cr_on", 1.0)) >= 0.5      # 11-14 user: ON by default
            mult, cg, lg, gg = (float(v.get(k, 1.0)) for k in ("cr_mult", "cr_cube", "cr_lit", "cr_glint"))
            self.cube_wanted = on and cg > 0.0
            sun_e, sdir = 0.0, None
            for a in unreal.GameplayStatics.get_all_actors_of_class(world, unreal.DirectionalLight):
                c = a.get_component_by_class(unreal.DirectionalLightComponent)
                if c is None or not c.is_visible():
                    continue
                col = c.get_editor_property("light_color")
                lum = (0.2126 * col.r + 0.7152 * col.g + 0.0722 * col.b) / 255.0
                sun_e = float(c.get_editor_property("intensity")) * max(lum, 1e-3)
                f = a.get_actor_forward_vector()
                sdir = unreal.LinearColor(-f.x, -f.y, -f.z, 0.0)
                break
            cube_ok = getattr(self, "cube_cap", None) is not None and getattr(self, "cube_baked", False)
            for mid, vals, old in getattr(self, "look_mids", []):
                if "Fx" not in mid.parent.get_name():
                    continue
                d = dict(Gain=CANOPY.get("Gain", 0.35) * gg)
                if on:
                    d.update(REFL_ON_VALS, ReflAmt=REFL_F2 * mult, HaloGlow=lg, InSun=sun_e, LitAbs=SKY_E_FRAC * sun_e,
                             CubeGain=cg, CubeAmt=1.0 if cube_ok and cg > 0.0 else 0.0)
                    if cube_ok:
                        d.update({k: x for k, x in CUBE.items() if k not in ("CubeAmt", "CubeGain")})
                else:
                    d.update(ReflAmt=0.0, CubeAmt=0.0)
                self._apply(mid, d)
                if sdir is not None:
                    mid.set_vector_parameter_value("SunDir", sdir)
            self.refl_state = dict(on=on, mult=mult, cube=cg, lit=lg, glint=gg, sun_e=round(sun_e, 3), cube_ok=cube_ok)
        except Exception as e:
            if not getattr(self, "_refl_err", None):
                self._refl_err = repr(e)
                _log("canopy reflection live", repr(e))

    def _canopy_vals(self, name):
        if not rt_available():
            if "Fx" in name and not FX_REFL_ON:
                return dict(CANOPY, ReflAmt=0.0)          # outer shell: no interior-proxy reflection (grey plate overhead)
            return CANOPY
        return dict(CANOPY, **RT_FX) if "Fx" in name else dict(CANOPY, **RT_CANOPY)

    def rt_mode(self, world, force=False):
        """ray-traced canopy reflection on / off (rt_available() can change with the quality preset): cvars once per change,
        the canopy instances' values, the mirror shell."""
        rt = rt_available()
        if not force and getattr(self, "rt_world", None) is world and self.rt_state == rt:
            return
        self.rt_world, self.rt_state = world, rt
        if rt:
            for k, v in RT_CVARS.items():
                unreal.SystemLibrary.execute_console_command(world, "%s %s" % (k, v))
        for mid, vals, old in getattr(self, "look_mids", []):
            if "Canopy" in mid.parent.get_name() and self.look_on:
                self._apply(mid, self._canopy_vals(mid.parent.get_name()))
        self.mirror(world, MIRROR if rt else 0.0)
        _log("canopy reflection:", "ray traced (spec %.2f, mirror %.2f)" % (RT_CANOPY["SpecAmt"], MIRROR) if rt else "interior cube")

    def mirror(self, world, opacity):
        """the bent-mirror shell (see MIRROR); opacity 0 hides it. Returns the actor."""
        try:
            a = getattr(self, "mirror_actor", None)
            if a is not None and getattr(self, "mirror_world", None) is not world:
                a = None
            if a is None and opacity > 0.0:
                can = unreal.GameplayStatics.get_all_actors_with_tag(world, "Canopy")
                mat = unreal.load_asset(MIRROR_MAT)
                if not can or mat is None:
                    _log("canopy mirror: no", "canopy" if not can else "material")
                    return None
                can = can[0]
                smc0 = can.get_component_by_class(unreal.StaticMeshComponent)
                if world == unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_editor_world():
                    a = unreal.get_editor_subsystem(unreal.EditorActorSubsystem).spawn_actor_from_class(
                        unreal.StaticMeshActor, can.get_actor_location(), can.get_actor_rotation(), transient=True)
                else:
                    a = unreal.GameplayStatics.finish_spawning_actor(
                        unreal.GameplayStatics.begin_deferred_actor_spawn_from_class(world, unreal.StaticMeshActor, unreal.Transform()),
                        unreal.Transform())
                a.tags = [unreal.Name("CanopyMirror"), unreal.Name("AircraftPart")]
                a.root_component.set_mobility(unreal.ComponentMobility.MOVABLE)
                a.attach_to_actor(can, unreal.Name(""), unreal.AttachmentRule.KEEP_WORLD, unreal.AttachmentRule.KEEP_WORLD,
                                  unreal.AttachmentRule.KEEP_WORLD, False)
                s = MIRROR_SHRINK                               # shrink toward the eye: just inside the glass, no z-fight
                e = unreal.Vector(430.0 * (1 - s), 0.0, 100.0 * (1 - s))
                a.root_component.set_relative_location_and_rotation(e, unreal.Rotator(0.0, 0.0, 0.0), False, True)
                a.set_actor_relative_scale3d(unreal.Vector(s, s, s))
                smc = a.static_mesh_component
                smc.set_static_mesh(smc0.static_mesh)
                smc.set_cast_shadow(False)
                smc.set_collision_enabled(unreal.CollisionEnabled.NO_COLLISION)
                mid = unreal.MaterialLibrary.create_dynamic_material_instance(world, mat)
                for i in range(smc.get_num_materials()):
                    smc.set_material(i, mid)
                self.mirror_actor, self.mirror_world, self.mirror_mid = a, world, mid
            if a is not None:
                self.mirror_mid.set_scalar_parameter_value("MirrorOpacity", float(opacity))
                a.static_mesh_component.set_visibility(opacity > 0.0, False)
            return a
        except Exception as e:
            _log("canopy mirror", repr(e))
            return None

    def interior_cube(self, world, now):
        """eye cube map of the cockpit for the canopy reflection (see CUBE_ON); called from canopy()."""
        if not (CUBE_ON or getattr(self, "cube_wanted", False)) or world is None or rt_available():
            return
        try:
            if getattr(self, "cube_world", None) is not world:
                self.cube_world, self.cube_cap, self.cube_baked = world, None, False
                self.cube_t = now + CUBE_DELAY - CUBE_S          # first (and by default only) bake CUBE_DELAY s from now
                rt = unreal.load_asset(CUBE_RT)
                ac = unreal.GameplayStatics.get_all_actors_with_tag(world, "Aircraft")
                if rt is None or not ac:
                    _log("canopy cube: no", "render target" if rt is None else "aircraft")
                    return
                ac = ac[0]
                # the capture actor: a map-placed SceneCaptureCube tagged CanopyCube (Python cannot spawn actors into a Play
                # world - no deferred-spawn / add-component binding), or in an editor world (CockpitView) a transient one
                caps = list(unreal.GameplayStatics.get_all_actors_with_tag(world, "CanopyCube"))
                cap = caps[0] if caps else None
                if cap is None and world == unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_editor_world():
                    cap = unreal.get_editor_subsystem(unreal.EditorActorSubsystem).spawn_actor_from_class(
                        unreal.SceneCaptureCube, ac.get_actor_location(), ac.get_actor_rotation(), transient=True)
                    cap.tags = [unreal.Name("CanopyCube")]
                if cap is None:
                    _log("canopy cube: no CanopyCube actor in this map (needs a placed SceneCaptureCube) - analytic interior only")
                    return
                if cap.get_attach_parent_actor() != ac:
                    cap.attach_to_actor(ac, unreal.Name(""), unreal.AttachmentRule.KEEP_WORLD, unreal.AttachmentRule.KEEP_WORLD,
                                        unreal.AttachmentRule.KEEP_WORLD, False)
                cap.root_component.set_relative_location_and_rotation(unreal.Vector(*CUBE_POS), unreal.Rotator(0.0, 0.0, 0.0), False, True)
                cc = cap.get_component_by_class(unreal.SceneCaptureComponentCube)
                cc.set_editor_property("texture_target", rt)
                cc.set_editor_property("capture_rotation", True)
                cc.set_editor_property("capture_every_frame", False)
                cc.set_editor_property("capture_on_movement", False)
                cc.set_editor_property("capture_source", unreal.SceneCaptureSource.SCS_SCENE_COLOR_HDR)
                try:                                            # sky / fog / clouds black: only the cockpit reflects
                    fl = []
                    for n in CUBE_BLACK_FLAGS:
                        f = unreal.EngineShowFlagsSetting()
                        f.set_editor_property("show_flag_name", n); f.set_editor_property("enabled", False)
                        fl.append(f)
                    cc.set_editor_property("show_flag_settings", fl)
                    rt.set_editor_property("size_x", CUBE_PX)
                    rt.set_editor_property("auto_generate_mips", True)       # footprint mips (V5 shader LOD)
                except Exception as e:
                    _log("canopy cube flags", repr(e))
                show = cube_content(world, cc)
                self.cube_cap = cc
                _log("canopy cube: capture at the eye, show-only %d physical parts (no pilot / overlays / glass), no direct sun" % len(show))
            if self.cube_cap is not None and now - self.cube_t >= CUBE_S:
                self.cube_t = now
                self.cube_cap.capture_scene()
                if not self.cube_baked:
                    _log("canopy cube: baked (%s)" % self.cube_cap.get_owner().get_name())
                self.cube_baked = True
                for mid, vals, old in getattr(self, "look_mids", []):
                    if "Fx" in mid.parent.get_name() and self.look_on:
                        self._apply(mid, CUBE)
        except Exception as e:
            if not getattr(self, "_cube_err", None):
                self._cube_err = repr(e)
                _log("canopy cube", repr(e))

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
        for mid, vals, old in getattr(self, "look_mids", []):
            if "Fx" in mid.parent.get_name() and getattr(self, "cube_cap", None) is not None and getattr(self, "cube_baked", False):
                self._apply(mid, CUBE if on else dict(CubeAmt=0.0))

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
