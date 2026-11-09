"""GyroSim visual client - runs inside the Unreal editor (Python), drives Play-In-Editor (monitor or VR Preview) from sim/server.py.

  state in : UDP JSON 127.0.0.1:4220, 60 Hz (lat/lon/alt_m, phi/theta/psi deg = NED Euler, controls, tutorial ...)
  input out: UDP JSON 127.0.0.1:4221 ({"ctrl": {...}} / {"cmd": "reset"|"pause"|"tut"}) - keyboard, only while the
             editor window has focus (Windows GetAsyncKeyState), so the browser page / joystick still work otherwise.

World frame: X = north, Y = east, Z = up, cm; origin = (lat0, lon0) from the packet at ellipsoid height geoid_n
(Z 0 = mean sea level there), exact WGS84 local tangent frame (geo.py) = Cesium's frame turned by yaw 90 deg, so the
aircraft sits on the real Earth curvature like the Cesium globe. NED Euler -> UE Rotator: roll = phi, pitch = theta,
yaw = psi (plus the small tilt of the local level away from the origin, geo.Frame.body_axes).

Cesium (Play): Config/cesium_token.txt (your Cesium ion token, not in git) -> Cesium World Terrain + Bing aerial imagery
(line 2 "photoreal" -> Google Photorealistic 3D Tiles). No token -> WGS84 ellipsoid raised to the field elevation +
Sentinel-2 cloudless satellite imagery (EOX, no login), note on the HUD / right MFD.
HUD / MFDs: hud.py draws them with UCanvas into render targets on world-space planes (VR works).

Smooth motion: packets carry the sim time t. The client keeps the last packets, maps sim time to local time
(perf_counter) and renders ~1 packet interval in the past, interpolating position (linear) and attitude (quaternion
slerp); at most 50 ms extrapolation when a packet is late.

VR: VR Preview (Play dropdown) uses the HMD through OpenXR. The camera actor is put at the cockpit eye point with the
aircraft attitude; the HMD pose is added by the camera component (lock to HMD), so head look works on top. HUD texts
the tutorial panel (H) and the key guide panel (K, right side) are world-space actors on the camera rig (visible in VR). F3 = recenter.

Started by init_unreal.py on editor start. In the editor Python console:  import sim_client; sim_client.status()
"""
import ctypes, importlib, json, math, os, socket, time
import unreal
import geo, hud, cockpit_gauges as gauges
importlib.reload(geo); importlib.reload(hud); importlib.reload(gauges)
import pie_fullscreen                 # not reloaded: it defines a UObject class (PIE full screen, F11 / Alt+Enter)
# Play started by GyroSim_Busan.bat (-GyroSimPlay): PIE window in true full screen (borderless, whole main monitor) on a
# monitor (not VR). GYROSIM_FULLSCREEN=0 keeps the old maximized window, =1 forces it for a Play pressed by hand too.
FULLSCREEN_AUTO = os.environ.get("GYROSIM_FULLSCREEN", "1" if "-gyrosimplay" in unreal.SystemLibrary.get_command_line().lower() else "0") == "1"

STATE_ADDR = ("127.0.0.1", 4220)
CMD_ADDR = ("127.0.0.1", 4221)
EYE = (430.0, 0.0, 100.0)          # cockpit eye point in body axes, cm (fwd, right, up) from the aircraft reference
CHASE_BACK, CHASE_UP = 2600.0, 650.0
# third-person views (V cycles, Shift+V back): cockpit -> chase (behind, follows the heading) -> orbit (side, fixed to the
# world, turn around the aircraft) -> flyby (a fixed point ahead the aircraft flies past) -> tower (fixed point by the
# runway) -> cockpit. Outside the cockpit: Q/E turn around, PageUp/PageDown up/down, + / - / mouse wheel zoom, mouse drag
# (monitor) turns, Home resets. VR: no camera pitch / roll from us (only yaw), turns / zoom in snap steps, flyby / tower
# are static points (re-placed with a snap, never moved while you look).
VIEWS = ("cockpit", "chase", "orbit", "flyby", "tower")
ORBIT_DEFAULT = dict(chase=(0.0, math.degrees(math.atan2(CHASE_UP, CHASE_BACK)), math.hypot(CHASE_BACK, CHASE_UP)),
                     orbit=(90.0, 12.0, 3500.0))           # (yaw offset deg, elevation deg, distance cm)
ORBIT_EL = (-25.0, 85.0)
ORBIT_DIST = (900.0, 40000.0)
ORBIT_YAW_RATE, ORBIT_EL_RATE, ZOOM_RATE, MOUSE_DEG_PX, WHEEL_STEP = 70.0, 45.0, 1.8, 0.25, 0.87
VR_SNAP_YAW, VR_SNAP_EL, VR_SNAP_ZOOM = 30.0, 15.0, 1.3
LOOK_AT_UP_CM = 150.0
TOWER_LL, TOWER_AGL_M = (36.7190, 127.4962), 35.0       # fixed camera ~500 m NW of the 06R midpoint, 35 m up (not the real tower); packet "tower" = the start airfield's
FLYBY_LEAD_S, FLYBY_MIN_M, FLYBY_SIDE_M, FLYBY_DOWN_M = 5.0, 300.0, 40.0, 10.0
VIEW_FOV = 75.0                                          # = build_level camera field of view
TOWER_SPAN_M = 60.0                                      # monitor tower / flyby auto zoom: this many m across the view at the aircraft
GEAR_BOTTOM_CM = 177.5             # F-16 model tire bottom below the actor origin (ThirdParty/f16_obj/manifest.json)
AGL_REST_M = 1.66                  # JSBSim F-16 h-agl when standing on the runway (measured from server.py, runway start)
Z_OFFSET_CM = GEAR_BOTTOM_CM - AGL_REST_M * 100.0
INTERP_DELAY = 1 / 60 + 0.004      # s behind the newest packet
MAX_EXTRAP = 0.05

GROUND_MODES = ("grid", "fields", "photo", "terrain", "photoreal", "vworld")
STARTUP_MODE = "air"               # Play always starts here (fresh run, not wherever the server drifted to)
STARTUP_MIN, STARTUP_MAX, STARTUP_FPS = 1.5, 15.0, 90.0
TOKEN_FILE = os.path.join(unreal.Paths.convert_relative_path_to_full(unreal.Paths.project_config_dir()), "cesium_token.txt")
EOX_URL = "https://tiles.maps.eox.at/wmts/1.0.0/s2cloudless-2024_3857/default/g/{z}/{reverseY}/{x}.jpg"
ION_TERRAIN, ION_BING, ION_PHOTOREAL, ION_OSM_BUILDINGS = 1, 2, 2275207, 96188
# 'vworld' ground (docs/vworld-integration.md): V-World aerial photos through the local tile proxy sim/vworld_proxy.py
# (holds the key, cache, budget; started by sim/server.py). Korea only, online zoom <= 16. Terrain = Cesium World
# Terrain only with an ion token, else the flat ellipsoid at the field elevation; OSM buildings only with a token.
# Never mixed with Sentinel-2 / Bing (terms 14조). On-screen source note (terms 13조): sim/vworld_attribution.png.
VW_CFG = os.path.join(unreal.Paths.convert_relative_path_to_full(unreal.Paths.project_config_dir()), "vworld_proxy.json")
VW_PORT = 8790                      # = vworld_proxy.DEFAULTS["port"] (overridden by Config/vworld_proxy.json "port")
VW_MAX_LEVEL = 19                   # the proxy only fetches online up to its max_online_zoom (16); 17-19 = cache (Busan z19 fill) or
                                    # the cached parent cut out. Cesium reaches 17-19 only over the deeper terrain tiles (Busan, terrain_dem.HIRES)
RKTU_FIELD_M = 191.0 * 0.3048       # the map (build_level) is built around RKTU: grid ground at this field elevation
VW_SSE = 4.0                        # raster overlay screen-space error (default 2): half the texel density, ~1/4 of the requests
# where V-World z19 is cached (Busan fill), starting there: overlay SSE 1 = 4x the texel density -> z19 near the aircraft on the
# deeper terrain tiles (terrain_dem.HIRES), z17 at mid range (texture size cap 2048 per terrain tile). Elsewhere it stays 4
# (more requests would only burn the daily budget: online fetches stop at z16, beyond that it is the cache or the parent cut out).
VW_SSE_HIRES, VW_HIRES_APTS = 1.0, ("rkpk",)
VW_ATTRIB_PNG = os.path.normpath(os.path.join(unreal.Paths.convert_relative_path_to_full(unreal.Paths.project_dir()), "..", "..", "sim", "vworld_attribution.png"))
VW_ATTRIB_D, VW_ATTRIB_W = 150.0, 0.30         # cm ahead of the view camera, width as a fraction of the view width
# local South Korea terrain (Copernicus DEM GLO-30 -> quantized-mesh, sim/terrain_build.py) from the same proxy at
# /terrain/layer.json: preferred in the vworld mode (before Cesium World Terrain); its credit is on the source plate
VW_TERRAIN_ATTRIB_PNG = os.path.join(os.path.dirname(VW_ATTRIB_PNG), "vworld_terrain_attribution.png")
VW_TERRAIN_ATTRIB_W = 0.40
# local 3D buildings (국토교통부 GIS건물통합정보 -> 3D Tiles, sim/buildings_build.py) from the same proxy at
# /buildings/tileset.json: in the vworld mode on the local terrain (before Cesium OSM Buildings); credit on the plate
VW_BLDG_ATTRIB_PNG = os.path.join(os.path.dirname(VW_ATTRIB_PNG), "vworld_buildings_attribution.png")
VW_BLDG_SSE = 16.0                  # buildings tileset screen-space error (tiles: geometricError 500 / 130 / 50 / 0)
# Busan minimap (11-09): picture made from the local V-World tile cache by sim/minimap_build.py (outside git, terms 19조),
# drawn 1:1 into a render target with the aircraft marker + heading arrow, on the 'Minimap' plate (build_level /
# Scripts/add_minimap.py). Shown in the vworld mode while the aircraft is over / near the picture: top right on the monitor,
# head-locked lower right in VR. J toggles it.
MINIMAP_DIR = os.path.join(os.environ.get("GYROSIM_TILES", "C:\\GyroSimTiles"), "minimap")
MINIMAP_W = 0.27                    # monitor: plate width as a fraction of the view width
MINIMAP_VR_CM, MINIMAP_VR_DIR = 34.0, (24.0, -20.0)    # VR: width at VW_ATTRIB_D, direction (right deg, up deg)
MINIMAP_HZ, MINIMAP_NEAR = 10.0, 0.25                   # redraw rate; shown up to this fraction of the picture outside it
RUNWAYS = ((36.7078737, 127.4874876, 36.7229393, 127.5117932), (36.7100557, 127.4868159, 36.7251153, 127.5111227))   # RKTU (airfield.py)
DISP_HZ, DISP_ORDER = 30.0, ("MFD_C", "MFD_L", "MFD_C", "MFD_R")   # one display per call: training 15 Hz, flight / chair 7.5 Hz
HUD_HZ = 30.0                      # HUD text / FPM / tapes redraw rate (Python canvas ~1 ms); the pitch ladder moves every frame (material)
MFD_HZ = 5.0
KEY_PNG = os.path.normpath(os.path.join(unreal.Paths.convert_relative_path_to_full(unreal.Paths.project_dir()), "..", "..", "sim", "key_panel.png"))

VK = dict(LEFT=0x25, UP=0x26, RIGHT=0x27, DOWN=0x28, A=0x41, D=0x44, W=0x57, S=0x53, B=0x42, G=0x47,
          R=0x52, T=0x54, V=0x56, P=0x50, H=0x48, U=0x55, C=0x43, Q=0x51, E=0x45, N=0x4E, M=0x4D,
          LBUTTON=0x01, RBUTTON=0x02, SHIFT=0x10, PRIOR=0x21, NEXT=0x22, HOME=0x24, PLUS=0xBB, MINUS=0xBD, ADD=0x6B, SUBTRACT=0x6D,
          K=0x4B, J=0x4A, MENU=0x12, F1=0x70, F2=0x71, F3=0x72, F9=0x78, F11=0x7A, RETURN=0x0D, SPACE=0x20, BACK=0x08, Z=0x5A, I=0x49, Y=0x59, L=0x4C,
          **{"K%d" % i: 0x30 + i for i in range(0, 10)})

# keyboard "stick" feel: rate toward the held direction (per s), spring back to centre, slower start (ease-in)
RAMP = dict(ail=1.8, elev=1.3, rud=1.6)
# our cockpit moves 1:1 with the physical rig (v4 controls, 2026-11-06): centre stick +-12.75 deg both axes (hardware/stick_v4
# stops), throttle +-30 deg (0 = aft, 1 = forward, hardware/throttle_v4), pedals +-4.0 cm fore/aft (hardware/pedals TRAVEL),
# toe brakes 18 deg (hardware/pedals/brakes_v4), gear handle +-16 deg (down = handle down)
STICK_ROLL, STICK_PITCH, THR_SWING, PEDAL_CM, TOE_DEG, GEAR_HANDLE_DEG = 12.75, 12.75, 30.0, 4.0, 18.0, 16.0
NEEDLES = ("asi", "alt", "alt10k", "vsi")
HUD_BRIGHT, MFD_BRIGHT = 2.0, 1.2
CRASH_BG = unreal.LinearColor(0.305, 0.0052, 0.0052, 1.0)     # = render.py CRASH_BG (150, 16, 16) sRGB, linear
CRASH_BTN = dict(retry=(60 / 1024, 430 / 640, 492 / 1024, 590 / 640), menu=(532 / 1024, 430 / 640, 964 / 1024, 590 / 640))  # = render.py
CRASH_W, CRASH_H = 160.0, 100.0          # CrashPanel plane size, cm (build_level)
CENTER = 3.0
THR_RATE = 0.35
BRK_RATE = 4.0


def _log(*a):
    unreal.log("[sim_client] " + " ".join(str(x) for x in a))


# ---- quaternion helpers (NED Euler, deg) ------------------------------------------------------------------------
def e2q(phi, th, psi):
    p, t, s = (math.radians(a) / 2 for a in (phi, th, psi))
    cp, sp, ct, st, cs, ss = math.cos(p), math.sin(p), math.cos(t), math.sin(t), math.cos(s), math.sin(s)
    return (cp * ct * cs + sp * st * ss, sp * ct * cs - cp * st * ss, cp * st * cs + sp * ct * ss, cp * ct * ss - sp * st * cs)


def q2e(q):
    w, x, y, z = q
    phi = math.degrees(math.atan2(2 * (w * x + y * z), 1 - 2 * (x * x + y * y)))
    th = math.degrees(math.asin(max(-1.0, min(1.0, 2 * (w * y - z * x)))))
    psi = math.degrees(math.atan2(2 * (w * z + x * y), 1 - 2 * (y * y + z * z)))
    return phi, th, psi


def slerp(a, b, u):
    d = sum(i * j for i, j in zip(a, b))
    if d < 0:
        b, d = tuple(-i for i in b), -d
    if d > 0.9995:
        r = tuple(i + (j - i) * u for i, j in zip(a, b))
    else:
        om = math.acos(min(1.0, d))
        so = math.sin(om)
        ka, kb = math.sin((1 - u) * om) / so, math.sin(u * om) / so
        r = tuple(ka * i + kb * j for i, j in zip(a, b))
    n = math.sqrt(sum(i * i for i in r))
    return tuple(i / n for i in r)


class Interp:
    """Sim-time -> local-time mapping + interpolation of (position, attitude) between packets."""
    def __init__(self):
        self.reset()

    def reset(self):
        self.buf = []                  # (t_sim, (x, y, z) cm, quat)
        self.off = None

    def push(self, s, now, loc, rot):
        t = s["t"]
        if self.buf and (t < self.buf[-1][0] - 1e-6 or t - self.buf[-1][0] > 0.5):
            self.reset()
        if self.buf and abs(t - self.buf[-1][0]) < 1e-6:
            return                      # paused / duplicate
        off = now - t
        if self.off is None or off < self.off:
            self.off = off
        elif off - self.off > 0.25:     # clock jump (pause, hitch): re-anchor
            self.reset()
            self.off = off
        else:
            self.off += min(off - self.off, 0.0005)     # follow slow drift upward
        self.buf.append((t, (loc.x, loc.y, loc.z), e2q(rot.roll, rot.pitch, rot.yaw)))
        if len(self.buf) > 12:
            self.buf.pop(0)

    def sample(self, now):
        b = self.buf
        if not b:
            return None
        tr = now - self.off - INTERP_DELAY
        if len(b) == 1 or tr <= b[0][0]:
            i, u = 0, 0.0
            if len(b) == 1:
                return b[0][1], q2e(b[0][2])
        elif tr >= b[-1][0]:
            i = len(b) - 2
            span = b[-1][0] - b[-2][0]
            u = 1.0 + min(tr - b[-1][0], MAX_EXTRAP) / span if span > 0 else 1.0
        else:
            i = 0
            while b[i + 1][0] < tr:
                i += 1
            span = b[i + 1][0] - b[i][0]
            u = (tr - b[i][0]) / span if span > 0 else 0.0
        (t0, p0, q0), (t1, p1, q1) = b[i], b[i + 1]
        pos = tuple(a + (c - a) * u for a, c in zip(p0, p1))
        return pos, q2e(slerp(q0, q1, u))


class Keyboard:
    def __init__(self):
        self.ok = os.name == "nt"
        if self.ok:
            self.u32 = ctypes.windll.user32
            self.pid = os.getpid()
        self.prev = {}

    def focused(self):
        if not self.ok:
            return False
        hwnd = self.u32.GetForegroundWindow()
        pid = ctypes.c_ulong()
        self.u32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        return pid.value == self.pid

    def down(self, k):
        return bool(self.u32.GetAsyncKeyState(VK[k]) & 0x8000)

    def pressed(self, k):            # rising edge
        d = self.down(k)
        p = self.prev.get(k, False)
        self.prev[k] = d
        return d and not p

    def cursor(self):
        import ctypes.wintypes
        pt = ctypes.wintypes.POINT()
        self.u32.GetCursorPos(ctypes.byref(pt))
        return pt.x, pt.y


# ---- quality presets -----------------------------------------------------------------------------------------------
PRESETS = {
    # monitor: Lumen GI + reflections, virtual shadow maps, TSR, full clouds
    "monitor": {"r.DynamicGlobalIlluminationMethod": 1, "r.ReflectionMethod": 1, "r.Shadow.Virtual.Enable": 1,
                "r.AntiAliasingMethod": 4, "r.VolumetricCloud.ViewRaySampleMaxCount": 768, "r.ScreenPercentage": 100,
                "sg.ShadowQuality": 3, "sg.PostProcessQuality": 3, "r.Lumen.ScreenProbeGather.ScreenTraces": 1},
    # VR (both eyes at 90 Hz): no Lumen (sky light + SSR), cascaded shadow maps, TAA, cheaper clouds
    "vr": {"r.DynamicGlobalIlluminationMethod": 0, "r.ReflectionMethod": 2, "r.Shadow.Virtual.Enable": 0,
           "r.AntiAliasingMethod": 2, "r.VolumetricCloud.ViewRaySampleMaxCount": 256, "r.ScreenPercentage": 100,
           "sg.ShadowQuality": 2, "sg.PostProcessQuality": 2, "r.Lumen.ScreenProbeGather.ScreenTraces": 0},
}


# per-preset lighting look (realism pass 11-05). Monitor has Lumen GI (bounce light fills the cockpit) so the fill
# light can be low; VR has no GI (sky light + distance-field AO only), so it keeps more fill or the shadows go black.
# shadow_contrast: local exposure shadow contrast (1 = shadows not lifted), exp_min: lowest EV100 the auto exposure may
# drop to when looking down into the cockpit (outside view = build_level.EXPOSURE_EV 2.0).
PRESET_LOOK = {
    "monitor": dict(fill_cd=1.4, shadow_contrast=0.85, highlight_contrast=0.85, exp_min=0.3, contact_shadow=0.03, vignette=0.2),
    "vr": dict(fill_cd=2.4, shadow_contrast=0.8, highlight_contrast=0.85, exp_min=0.3, contact_shadow=0.02, vignette=0.0),
}


def apply_look(name, world):
    lk = PRESET_LOOK.get(name)
    if not lk or world is None:
        return
    try:
        for a in unreal.GameplayStatics.get_all_actors_with_tag(world, "CockpitFill"):
            a.point_light_component.set_intensity(lk["fill_cd"])
        for a in unreal.GameplayStatics.get_all_actors_of_class(world, unreal.DirectionalLight):
            lc = a.get_component_by_class(unreal.DirectionalLightComponent)
            lc.set_editor_property("contact_shadow_length", lk["contact_shadow"])
        for a in unreal.GameplayStatics.get_all_actors_of_class(world, unreal.PostProcessVolume):
            ps = a.get_editor_property("settings")
            for k, v in (("local_exposure_shadow_contrast_scale", lk["shadow_contrast"]),
                         ("local_exposure_highlight_contrast_scale", lk["highlight_contrast"]),
                         ("auto_exposure_min_brightness", lk["exp_min"]), ("vignette_intensity", lk["vignette"])):
                ps.set_editor_property("override_" + k, True)
                ps.set_editor_property(k, v)
            a.set_editor_property("settings", ps)
    except Exception as e:
        _log("look", name, repr(e))
    _realism_v2(name, world)


def _realism_v2(name, world):
    """realism v2 profile per preset (Scripts/realism_v2.py, docs/realism-v2-plan.md 2.2): VR gets standard bloom and no
    lens flare instead of the monitor values baked into the level."""
    try:
        import sys
        sd = os.path.join(unreal.Paths.project_dir(), "Scripts")
        if sd not in sys.path:
            sys.path.insert(0, sd)
        import realism_v2
        realism_v2.apply_profile(name, world)
    except Exception as e:
        _log("realism_v2", name, repr(e))


apply_look._realism_v2 = True          # realism_v2.install_hook: already built in, nothing to wrap


def apply_preset(name, world=None):
    p = PRESETS.get(name)
    if not p:
        return False
    if world is None:
        world = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_game_world() or \
            unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_editor_world()
    for k, v in p.items():
        unreal.SystemLibrary.execute_console_command(world, "%s %s" % (k, v))
    apply_look(name, world)
    _log("quality preset", name)
    return True


class SimClient:
    def __init__(self):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setblocking(False)
        try:
            self.sock.bind(STATE_ADDR)
            self.bound = True
        except OSError as e:
            self.bound = False
            _log("cannot bind UDP", STATE_ADDR, e, "- another client running?")
        self.out = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.kb = Keyboard()
        self.ctrl = dict(ail=0.0, elev=0.0, rud=0.0, thr=0.0, brk_l=0.0, brk_r=0.0, gear=0.0)
        self.view = "cockpit"
        self.hud = True
        self.s = None
        self.rx_n = 0
        self.rx_t = 0.0
        self.rid = None
        self.world = None
        self.aircraft = self.camera = self.view_cam = None
        self.interp = Interp()
        self.chase_yaw = None
        self.orbit = {k: list(v) for k, v in ORBIT_DEFAULT.items()}   # per view: [yaw offset, elevation, distance]
        self.orbit_vel = [0.0, 0.0, 0.0]   # held keys: yaw / elevation deg/s, zoom (log) per s
        self.orbit_world_yaw = None
        self.view_pt = None                # flyby / tower: fixed camera point (+ VR fixed rotation)
        self.view_zoom = dict(flyby=1.0, tower=1.0)
        self.inject = None                 # tests: dict(dx, dy, wheel) as if from the mouse, consumed once
        self.mouse_prev = None
        self.fov_set = None
        self.last_log = 0.0
        self.frames = 0
        self.handle = None
        self.override = None          # dict of ctrl values to force (sent even without focus), None = keyboard
        self.no_interp = False        # True = draw the newest packet (old behaviour), for comparison
        self.look = [0.0, 0.0]        # monitor head look (pitch, yaw), deg; target below
        self.look_tgt = [0.0, 0.0]
        self.look_down = False
        self.hmd = False
        self.preset = None
        self.hmd_check_t = 0.0
        self.disp = dict(ail=0.0, elev=0.0, rud=0.0, thr=0.0, brk_l=0.0, brk_r=0.0)
        self.txt_t = 0.0
        self.txt_cache = {}
        self.tut_ver = -1
        self.gear_shown = None
        self.last_pose = None
        self.panel_on = True          # H: tutorial panel on/off
        self.keys_on = False          # K: key guide panel on/off in flight (always shown in the menu; review: it cluttered the view)
        self.keys_shown = None
        self.keys_tex = False
        self.key_panel = None
        self.painter = None
        self.screens = {}
        self.hud_t = self.mfd_t = self.trace_t = 0.0
        self.hud_vis = None
        self.hud_n, self.hud_ms = 0, 0.0
        self.disp_ms = 0.0
        self.warnings, self.gmax, self.gmax_rid = [], 1.0, None
        self.panel_tex = self.line_tex = None
        self.lights, self.lights_on, self.beg_labels, self.beg_shown = {}, {}, [], None
        self.cesium_mode = None       # 'terrain' | 'photoreal' | 'flat' | 'none' | 'error'
        self.radar_m = None           # height above whatever is under the aircraft (line trace), m
        self.crashed = False
        self.t_bind = 0.0
        self.georef = self.tileset = self.grid = None
        self.start = dict(phase="done", dts=[])

    # ---------------------------------------------------------------------------------------------------------------
    def _find(self, tag):
        a = unreal.GameplayStatics.get_all_actors_with_tag(self.world, tag)
        return a[0] if a else None

    def _bind_world(self, world):
        self.world = world
        self.apt_key = None                            # _apt_sync: Cesium origin / airfield meshes follow the packet's start airfield
        self.aircraft = self._find("Aircraft")
        self.camera = self._find("SimCamera")          # rig: moved by us, carries the overlays
        self.view_cam = self._find("SimView") or self.camera   # CameraActor = view target (HMD / head look rotate it)
        self.canopy = list(unreal.GameplayStatics.get_all_actors_with_tag(world, "Canopy"))
        self.gear_parts = list(unreal.GameplayStatics.get_all_actors_with_tag(world, "Gear"))
        self.pivots = {}
        for tag in ("StickPivot", "ThrottlePivot", "PedalL", "PedalR", "GearHandle"):
            a = self._find(tag)
            if a:
                b = a.root_component.get_editor_property("relative_location")
                self.pivots[tag] = (a, unreal.Vector(b.x, b.y, b.z))
        self.needles = {n: self._find("Needle_" + n) for n in NEEDLES}
        self.needles = {n: a for n, a in self.needles.items() if a}
        self.adi = self._find("ADIBall")
        self.gear_lights = self._find("GearLights")
        self.pilot_body, self.pilot_head, self.pilot_view = self._find("PilotBody"), self._find("PilotHead"), None   # Scripts/pilot
        self.gear_lit = None
        self.gauge_vals = {}
        self.lights = {k: self._find("Light_" + k) for k in ("MC", "WARN", "BRAKE", "ASSIST", "SLOW", "VOICE")}
        self.lights = {k: a for k, a in self.lights.items() if a}
        self.lights_on = {}
        self.beg_labels = list(unreal.GameplayStatics.get_all_actors_with_tag(world, "BeginnerLabel"))
        self.beg_shown = None
        self.panel_tex = self.line_tex = None
        self.warnings, self.gmax, self.gmax_rid = [], 1.0, None
        self.texts = {}
        self.panel = self._find("TutorPanel")
        self.key_panel = self._find("KeyPanel")
        self.painter = None
        self.screens = {}
        try:
            self.painter = hud.Painter(world)
            for tag, rt in [("HUD", self.painter.rt_hud)] + list(self.painter.rt_disp.items()):
                a = self._find(tag)
                if a:
                    mid = a.static_mesh_component.create_and_set_material_instance_dynamic(0)
                    mid.set_texture_parameter_value("Tex", rt)
                    if tag == "HUD":
                        mid.set_texture_parameter_value("Ladder", self.painter.rt_ladder)
                        mid.set_scalar_parameter_value("TexAlpha", 1.0)
                        mid.set_scalar_parameter_value("Brightness", HUD_BRIGHT)
                    else:
                        mid.set_scalar_parameter_value("Brightness", MFD_BRIGHT)
                    self.screens[tag] = (a, mid)
        except Exception as e:
            _log("HUD painter", repr(e))
        self.terrain_hit = False
        self.cesium_failed = None
        self.trace_ignore = [self.aircraft] + list(unreal.GameplayStatics.get_all_actors_with_tag(world, "AircraftPart"))
        self.crashed = False
        self.t_bind = time.perf_counter()
        self.hud_vis = None
        self.ladder_on = None
        self.max_tries = 0 if FULLSCREEN_AUTO else 40       # maximize the new PIE window over the next frames
        pie_fullscreen.reset()
        self.fs_auto_t = time.perf_counter() + 1.0 if FULLSCREEN_AUTO else None   # full screen 1 s after Play (window up, VR known)
        self.fs_check_t = None
        self.start = dict(phase="reset", t0=time.perf_counter(), sent=-9.0, rid0=(self.s or {}).get("rid"), dts=[])
        self._setup_cesium()
        self.panel_mid = None
        self.panel_shown = None
        if self.panel:
            try:
                self.panel_mid = self.panel.static_mesh_component.create_and_set_material_instance_dynamic(0)
            except Exception as e:
                _log("panel material", e)
        # crash screen (red back plane + the server's crash picture, on the view camera, hidden until a crash)
        self.crash_back, self.crash_panel, self.crash_mid, self.crash_shown = self._find("CrashBack"), self._find("CrashPanel"), None, None
        try:
            if self.crash_back:
                red = unreal.RenderingLibrary.create_render_target2d(world, 4, 4, unreal.TextureRenderTargetFormat.RTF_RGBA8, CRASH_BG)
                self.crash_back.static_mesh_component.create_and_set_material_instance_dynamic(0).set_texture_parameter_value("Tex", red)
            if self.crash_panel:
                self.crash_mid = self.crash_panel.static_mesh_component.create_and_set_material_instance_dynamic(0)
        except Exception as e:
            _log("crash screen", repr(e))
        self.keys_shown = None
        self.keys_tex = False
        if self.key_panel:                              # key guide (sim/key_panel.png, made by sim/key_panel.py)
            try:
                tex = unreal.RenderingLibrary.import_file_as_texture2d(world, KEY_PNG) if os.path.exists(KEY_PNG) else None
                if tex:
                    self.key_panel.static_mesh_component.create_and_set_material_instance_dynamic(0).set_texture_parameter_value("Tex", tex)
                    self.keys_tex = True
                    w, h = tex.blueprint_get_size_x(), tex.blueprint_get_size_y()
                    if w and h:                           # plane height follows the picture (key_panel.py H)
                        sc = self.key_panel.get_actor_scale3d()
                        self.key_panel.set_actor_scale3d(unreal.Vector(sc.x, sc.x * h / w, sc.z))
                else:
                    _log("key panel image missing", KEY_PNG)
            except Exception as e:
                _log("key panel", repr(e))
        self.txt_cache.clear()
        self.tut_ver = -1
        self.gear_shown = None
        self.interp.reset()
        self.preset = None
        _log("game world", world.get_name(), "aircraft", bool(self.aircraft), "camera", bool(self.camera),
             "pivots", sorted(self.pivots), "screens", sorted(self.screens), "panel", bool(self.panel_mid), "keys", self.keys_tex, "cesium", self.cesium_mode)
        self._set_view_target()

    @staticmethod
    def read_ground_cfg():
        """(token, mode) from Config/cesium_token.txt (not in git). Lines: '#' comment, a mode keyword
        grid | photo | terrain | photoreal, anything else = Cesium ion access token.
        No file / no token -> 'grid' (local grid ground, nothing streamed). Token -> 'terrain' unless a keyword says
        otherwise. 'photo' = Sentinel-2 satellite photo on flat ground (no token needed, streamed)."""
        try:
            lines = [l.strip() for l in open(TOKEN_FILE, encoding="utf-8-sig") if l.strip() and not l.strip().startswith("#")]
        except OSError:
            lines = []
        kws = [l.lower() for l in lines if l.lower() in GROUND_MODES]
        token = next((l for l in lines if l.lower() not in GROUND_MODES), None)
        env = os.environ.get("GYROSIM_GROUND", "").strip().lower()      # developer checks: overrides the file's keyword
        if env in GROUND_MODES:
            kws.append(env)
        mode = kws[-1] if kws else ("terrain" if token else "grid")
        if mode in ("terrain", "photoreal") and not token:
            mode = "grid"
        return token, mode       # 'vworld' works with or without a token (token = real terrain + OSM buildings)

    read_token = read_ground_cfg

    def _ground(self, mode, token=None):
        """Switch the ground: grid mesh, or the Cesium tileset (photo / terrain / photoreal)."""
        ts = self.tileset
        if self.grid:
            self.grid.set_actor_hidden_in_game(mode not in ("grid", "fields", "none"))
            # 'fields' = the same ground mesh with the procedural countryside material (optional look; default = grid)
            mat = unreal.load_asset("/Game/Materials/M_Countryside" if mode == "fields" else "/Game/Materials/M_Grid")
            if mat:
                self.grid.static_mesh_component.set_material(0, mat)
            if mode == "fields":
                mode = "grid"                             # no streaming: the tileset stays off
        if not ts:
            return
        ovs = {c.get_class().get_name(): c for c in ts.get_components_by_class(unreal.CesiumRasterOverlay)}
        eox, ion = ovs.get("CesiumUrlTemplateRasterOverlay"), ovs.get("CesiumIonRasterOverlay")
        for o in (eox, ion):
            if o:
                o.remove_from_tileset()
        if mode == "grid":                                # tileset off: no streaming at all
            ts.set_editor_property("tileset_source", unreal.TilesetSource.FROM_URL)
            ts.set_editor_property("url", "")
            ts.set_actor_hidden_in_game(True)
            return
        ts.set_actor_hidden_in_game(False)
        if mode == "vworld":
            self._vworld_ground(ts, eox, token)
        elif mode == "photo":
            h = self.s.get("field_m", 58.2) if self.s else 58.2
            ts.set_actor_location_and_rotation(unreal.Vector(0, 0, h * 100.0 - 30.0), unreal.Rotator(roll=0, pitch=0, yaw=90.0), False, True)
            ts.set_editor_property("tileset_source", unreal.TilesetSource.FROM_ELLIPSOID)
            if eox:
                eox.set_editor_property("template_url", EOX_URL)
                eox.set_editor_property("maximum_level", 15)
                eox.add_to_tileset()
                eox.set_active(True)
        else:
            ts.set_actor_location_and_rotation(unreal.Vector(0, 0, 0), unreal.Rotator(roll=0, pitch=0, yaw=90.0), False, True)
            ts.set_editor_property("ion_access_token", token)
            ts.set_editor_property("ion_asset_id", ION_PHOTOREAL if mode == "photoreal" else ION_TERRAIN)
            ts.set_editor_property("tileset_source", unreal.TilesetSource.FROM_CESIUM_ION)
            if ion and mode == "terrain":
                ion.set_editor_property("ion_access_token", token)
                ion.set_editor_property("ion_asset_id", ION_BING)
                ion.add_to_tileset()
                ion.set_active(True)
        ts.refresh_tileset()

    @staticmethod
    def vworld_port():
        try:
            with open(VW_CFG, encoding="utf-8-sig") as f:
                return int(json.load(f).get("port", VW_PORT))
        except (OSError, ValueError, TypeError):
            return VW_PORT

    def vworld_status(self, timeout=0.4):
        """the proxy's /status (budget, online / stopped), None if it is not running. Never contains the key."""
        import urllib.request
        try:
            with urllib.request.urlopen("http://127.0.0.1:%d/status" % self.vworld_port(), timeout=timeout) as r:
                return json.loads(r.read().decode("utf-8"))
        except Exception:
            return None

    def _vworld_ground(self, ts, ov, token):
        """V-World photo overlay (through the local proxy, never Sentinel-2 / Bing) on the local South Korea terrain
        (Copernicus DEM, the proxy's /terrain/layer.json), else Cesium World Terrain (token), else the flat ellipsoid
        raised to the field elevation."""
        local = bool((self.vw_stat or {}).get("terrain"))
        self.vw_local = local
        if local:
            ts.set_actor_location_and_rotation(unreal.Vector(0, 0, 0), unreal.Rotator(roll=0, pitch=0, yaw=90.0), False, True)
            ts.set_editor_property("tileset_source", unreal.TilesetSource.FROM_URL)
            ts.set_editor_property("url", "http://127.0.0.1:%d/terrain/layer.json" % self.vworld_port())
        elif token:
            ts.set_actor_location_and_rotation(unreal.Vector(0, 0, 0), unreal.Rotator(roll=0, pitch=0, yaw=90.0), False, True)
            ts.set_editor_property("ion_access_token", token)
            ts.set_editor_property("ion_asset_id", ION_TERRAIN)
            ts.set_editor_property("tileset_source", unreal.TilesetSource.FROM_CESIUM_ION)
        else:
            h = self.s.get("field_m", 58.2) if self.s else 58.2
            ts.set_actor_location_and_rotation(unreal.Vector(0, 0, h * 100.0 - 30.0), unreal.Rotator(roll=0, pitch=0, yaw=90.0), False, True)
            ts.set_editor_property("tileset_source", unreal.TilesetSource.FROM_ELLIPSOID)
        self.vw_terrain = local or bool(token)
        if ov:
            ov.set_editor_property("template_url", "http://127.0.0.1:%d/vworld/sat/{z}/{reverseY}/{x}.jpg" % self.vworld_port())
            ov.set_editor_property("minimum_level", 0)                 # the proxy answers 0-5 / outside Korea locally (blank)
            ov.set_editor_property("maximum_level", VW_MAX_LEVEL)
            try:
                ov.set_maximum_screen_space_error(VW_SSE)
                ov.set_maximum_simultaneous_tile_loads(8)
            except Exception as e:
                _log("vworld overlay options", repr(e))
            ov.add_to_tileset()
            ov.set_active(True)               # auto_activate is off in the map: add_to_tileset alone left it inactive (no requests)
        if local and (self.vw_stat or {}).get("buildings"):
            self._local_buildings()
        elif token:
            self._osm_buildings(token)

    def _local_buildings(self):
        """3D buildings from the proxy (/buildings/tileset.json, built offline from 국토교통부 GIS건물통합정보): the
        CesiumBuildings tileset (build_level: off, no URL) pointed at the local URL. Physics meshes on, so the camera
        floor trace stands on roofs too (crashes are judged by the server's roof raster)."""
        try:
            b = self.buildings = self._find("CesiumBuildings")
            if b is None:
                _log("local buildings: no CesiumBuildings actor in the map (run build_level.py)")
                return
            b.set_actor_location_and_rotation(unreal.Vector(0, 0, 0), unreal.Rotator(roll=0, pitch=0, yaw=90.0), False, True)
            b.set_editor_property("tileset_source", unreal.TilesetSource.FROM_URL)
            b.set_editor_property("url", "http://127.0.0.1:%d/buildings/tileset.json" % self.vworld_port())
            for k, v in (("maximum_screen_space_error", VW_BLDG_SSE), ("create_physics_meshes", True), ("show_credits_on_screen", False)):
                try:
                    b.set_editor_property(k, v)
                except Exception as e:
                    _log("local buildings", k, repr(e))
            off = os.environ.get("GYROSIM_BUILDINGS_OFF", "") == "1"         # A/B checks (FPS without buildings)
            b.set_actor_hidden_in_game(off)
            b.refresh_tileset()
            self.vw_bldg = not off
            _log("local buildings on" if self.vw_bldg else "local buildings off (GYROSIM_BUILDINGS_OFF)")
        except Exception as e:
            _log("local buildings failed", repr(e))

    def _osm_buildings(self, token):
        """Cesium OSM Buildings (ion asset 96188, needs the token): a second tileset spawned in the Play world."""
        try:
            b = self.buildings = self._find("CesiumBuildings")          # build_level: off (no URL) until here
            if b is None:
                _log("OSM buildings: no CesiumBuildings actor in the map (run build_level.py)")
                return
            b.set_editor_property("ion_access_token", token)
            b.set_editor_property("ion_asset_id", ION_OSM_BUILDINGS)
            b.set_editor_property("tileset_source", unreal.TilesetSource.FROM_CESIUM_ION)
            b.set_actor_hidden_in_game(False)
            b.refresh_tileset()
            _log("OSM buildings on")
        except Exception as e:
            _log("OSM buildings failed", repr(e))

    def _setup_cesium(self):
        gr, ts = self._find("CesiumGeoreference"), self._find("CesiumGround")
        self.georef, self.tileset, self.grid = gr, ts, self._find("GridGround")
        self.buildings, self.vw_terrain, self.vw_note, self.vw_stat, self.attrib = None, False, None, None, None
        self.vw_local = self.vw_bldg = False
        token, mode = self.read_ground_cfg()
        if not ts or not hasattr(unreal, "Cesium3DTileset"):
            mode = (mode if mode == "fields" else "grid") if self.grid else "none"
        if mode == "vworld":
            self.vw_stat = self.vworld_status(1.0)
            if self.vw_stat is None:                  # no proxy -> grid (never Sentinel-2 in place of V-World)
                _log("vworld: tile proxy not running on port", self.vworld_port(), "- grid ground (start sim/server.py or sim/vworld_proxy.py)")
                self.cesium_failed = "V-WORLD PROXY NOT RUNNING - GRID GROUND"
                mode = "grid"
        try:
            self._ground(mode, token)
            self.cesium_mode = mode
        except Exception as e:
            _log("ground setup failed", repr(e))
            self.cesium_mode = "error"
        _log("ground mode", self.cesium_mode, "config", TOKEN_FILE, "token" if token else "no token",
             ("local DEM terrain" if self.vw_local else "terrain" if self.vw_terrain else "flat ellipsoid (no ion token)") if self.cesium_mode == "vworld" else "")
        self._attribution()

    def _apt_sync(self):
        """Start airfield from the packet (server.py --start, sim/airfield.py): the map is built around RKTU, other airfields'
        runway meshes in their own frames (build_level build_airfield, tags Airfield / Airfield_<id>). Move the Cesium
        georeference origin to the packet's lat0 / lon0 / geoid_n (= the world frame to_world uses, so sky, fog and lights
        stay near the world origin), show only that airfield's meshes, put the grid ground at its field elevation."""
        s = self.s
        if not s or self.world is None:
            return
        apt = s.get("apt", "rktu")
        key = (apt, s["lat0"], s["lon0"], s.get("geoid_n", 0.0))
        if key == self.apt_key:
            return
        self.apt_key = key
        try:
            if self.georef:
                self.georef.set_origin_longitude_latitude_height(unreal.Vector(s["lon0"], s["lat0"], s.get("geoid_n", 0.0)))
            shown = 0
            fields = unreal.GameplayStatics.get_all_actors_with_tag(self.world, "Airfield")
            for a in fields:
                on = a.actor_has_tag("Airfield_" + apt)
                a.set_actor_hidden_in_game(not on)
                shown += on
            if self.grid:
                self.grid.set_actor_location(unreal.Vector(0, 0, (s.get("field_m", RKTU_FIELD_M) - RKTU_FIELD_M) * 100.0), False, True)
            if self.cesium_mode == "vworld" and self.tileset:
                for o in self.tileset.get_components_by_class(unreal.CesiumUrlTemplateRasterOverlay):
                    o.set_maximum_screen_space_error(VW_SSE_HIRES if apt in VW_HIRES_APTS else VW_SSE)
            if apt != "rktu" and not fields:
                _log("start airfield", apt, "but the map has no Airfield tags - rebuild it (Scripts/build_level.py)")
            _log("start airfield %s: Cesium origin %.6f %.6f h %.2f, %d of %d airfield actors shown" % (apt, s["lat0"], s["lon0"], s.get("geoid_n", 0.0), shown, len(fields)))
        except Exception as e:
            _log("airfield sync failed", repr(e))

    def _cesium_fallback(self, why):
        """terrain mode failed -> grid ground (tileset off); vworld on terrain -> vworld on the flat ellipsoid."""
        if self.cesium_mode == "vworld":
            _log("vworld terrain failed -> flat ellipsoid:", why)
            self.vw_stat = dict(self.vw_stat or {}, terrain=False)       # no second try of the local terrain
            self.vw_bldg = False
            try:
                if getattr(self, "buildings", None):
                    self.buildings.set_actor_hidden_in_game(True)
                self._ground("vworld", None)
            except Exception as e:
                _log("fallback failed", repr(e))
            self.cesium_failed = "CESIUM TERRAIN FAILED (TOKEN?) - V-WORLD FLAT"
            self.t_bind = time.perf_counter()
            return
        _log("cesium fallback to grid:", why)
        try:
            self._ground("grid")
        except Exception as e:
            _log("fallback failed", repr(e))
        self.cesium_mode = "grid"
        self.cesium_failed = why
        self.t_bind = time.perf_counter()          # show the HUD note again

    # ---- PIE window: true full screen (pie_fullscreen.py), maximized as the fallback ------------------------------------
    def _window_mode(self, now):
        if self.hmd:                                         # VR Preview: the window is only the mirror
            self.fs_auto_t = self.fs_check_t = None
            return
        if self.fs_auto_t is not None and now >= self.fs_auto_t:
            self.fs_auto_t = None
            # only a separate PIE window (Play in 'New Editor Window'); Play inside the editor viewport would make the whole
            # editor full screen (off-screen check runs have no window at all)
            own = pie_fullscreen.pie_window_rect() is not None or "-renderoffscreen" in unreal.SystemLibrary.get_command_line().lower()
            if own and pie_fullscreen.request(self.world, True):
                self.fs_check_t = now + 2.0
            else:
                self.max_tries = 40
        if self.fs_check_t is not None and now >= self.fs_check_t:
            self.fs_check_t = None
            w = pie_fullscreen.pie_window_rect()
            if w is not None:
                l, tp, r, b = w["rect"]
                mw, mh = w["monitor"]
                full = l <= 0 and tp <= 0 and r >= mw and b >= mh
                _log("PIE window %s after the full screen request: %s, monitor %dx%d" % ("FULL SCREEN" if full else "not full screen", w["rect"], mw, mh))
                if not full:
                    self.max_tries = 40                      # did not take: at least maximize like before
            else:
                _log("full screen requested (%s); no PIE window on the desktop (off-screen run)" % pie_fullscreen.status().get("last"))
        if getattr(self, "max_tries", 0) > 0:
            self.max_tries -= 1
            if maximize_pie_window():
                self.max_tries = 0
                _log("PIE window maximized")

    def toggle_fullscreen(self):
        if self.world is not None and not self.hmd and (pie_fullscreen.is_on() or pie_fullscreen.pie_window_rect() is not None):
            on = not pie_fullscreen.is_on()
            pie_fullscreen.request(self.world, on)
            _log("full screen", "on" if on else "off")

    # ---- Play start: fresh air start, paused until the scene renders at full rate ---------------------------------
    def _startup(self, now, dt):
        """On every new Play: reset the sim to the air start (the server keeps flying while Unreal is not playing),
        keep it paused while shaders / textures settle, unpause when the frame rate is back (or after STARTUP_MAX s)."""
        st = self.start
        if st["phase"] == "done":
            return
        s = self.s
        el = now - st["t0"]
        st["dts"].append(dt)
        if st["phase"] == "reset":
            if el - st["sent"] > 1.0:                                  # (re)send until the server confirms
                st["sent"] = el
                self._send({"cmd": "reset", "mode": STARTUP_MODE})
            if s and s.get("rid") != st["rid0"]:
                st["phase"] = "pause"
        if st["phase"] == "pause":
            if s and s.get("paused"):
                st["phase"], st["t_wait"] = "wait", el
            elif el - st.get("p_sent", -9) > 0.5:
                st["p_sent"] = el
                self._send({"cmd": "pause", "on": True})
        elif st["phase"] == "wait":
            if s and not s.get("paused"):                              # someone else unpaused / reset (tutorial, script)
                st["phase"] = "done"
            else:
                d = st["dts"][-30:]
                fps = len(d) / sum(d) if d and sum(d) > 0 else 0.0
                if (el > STARTUP_MIN and len(d) >= 30 and fps >= STARTUP_FPS) or el > STARTUP_MAX:
                    self._send({"cmd": "pause", "on": False})
                    st["phase"], st["ready_s"], st["ready_fps"] = "done", round(el, 2), round(fps, 1)
        if st["phase"] == "done":
            d = st["dts"]
            st["min_fps_startup"] = round(1.0 / max(d), 1) if d else None
            _log("startup done after %.1f s (fps %s, slowest frame %.0f ms)" % (el, st.get("ready_fps"), 1000 * max(d) if d else 0))

    @property
    def startup_done(self):
        return self.start["phase"] == "done"

    def _set_view_target(self):
        pc = unreal.GameplayStatics.get_player_controller(self.world, 0)
        if pc and self.view_cam and pc.get_view_target() != self.view_cam:
            pc.set_view_target_with_blend(self.view_cam, 0.0)

    def _recv(self):
        if not self.bound:
            return
        while True:
            try:
                data = self.sock.recv(65536)
            except (BlockingIOError, OSError):
                break
            try:
                s = json.loads(data)
            except ValueError:
                continue
            self.s = s
            self.rx_n += 1
            self.rx_t = time.perf_counter()
            if s.get("paused") or s.get("rid") != self.rid:
                self.interp.reset()
            loc, rot = self.to_world(s)
            self.interp.push(s, self.rx_t, loc, rot)

    def _send(self, m):
        try:
            self.out.sendto(json.dumps(m).encode(), CMD_ADDR)
        except OSError:
            pass

    # ---------------------------------------------------------------------------------------------------------------
    _frame = None

    @classmethod
    def to_world(cls, s):
        """packet -> (UE location of the aircraft reference, UE rotator) on the exact WGS84 frame (geo.py)."""
        n = s.get("geoid_n", 0.0)
        f = cls._frame
        if f is None or (f.lat0, f.lon0, f.h0) != (s["lat0"], s["lon0"], n):
            f = cls._frame = geo.Frame(s["lat0"], s["lon0"], n)
        fwd, right, up = f.body_axes(s["lat"], s["lon"], s["phi"], s["theta"], s["psi"])
        x, y, z = f.world(s["lat"], s["lon"], s["alt_m"] + s.get("geoid_here", n))   # DEM mode: EGM2008 N under the aircraft
        loc = unreal.Vector(x, y, z) + unreal.Vector(*up) * Z_OFFSET_CM
        r, p, yw = geo.euler_from_axes(fwd, up)
        return loc, unreal.Rotator(roll=r, pitch=p, yaw=yw)

    def _sync_reset(self):
        """Follow the server after a reset (or on first packet): take its throttle / gear so we don't fight it."""
        s, c = self.s, self.ctrl
        if not s or s.get("rid") == self.rid:
            return
        first = self.rid is None
        self.rid = s.get("rid")
        self.crashed = False
        c["thr"] = float(s["thr"] if first else s.get("thr_init", c["thr"]))
        c["gear"] = float((s["gear"] > 0.5) if first else s.get("gear_init", c["gear"]))
        c.update(ail=0.0, elev=0.0, rud=0.0)

    def _keyboard(self, dt):
        self._sync_reset()
        if self.override is not None:                       # scripted input (tests / automation)
            self._send({"ctrl": dict(self.ctrl, **self.override), "rid": self.rid, "hmd": self.hmd})
            return
        if not self.kb.focused():
            self.kb.prev.clear()
            return
        kb, c = self.kb, self.ctrl
        tut = (self.s or {}).get("tut") or {}
        if kb.pressed("F11") or (kb.down("MENU") and kb.pressed("RETURN")):     # full screen on / off (any phase)
            self.toggle_fullscreen()
        if tut.get("phase") == "menu":                      # start menu: arrows / Enter / Space / Backspace drive it
            for k, op in (("UP", "up"), ("DOWN", "down"), ("RETURN", "select"), ("SPACE", "select"), ("BACK", "back"), ("RIGHT", "select"),
                          ("LEFT", "back")):
                if kb.pressed(k):
                    self._send({"cmd": "menu", "op": op})
            if kb.pressed("F1"):
                self._send({"cmd": "tut", "op": "menu"})
            for k in ("Z", "Y", "L", "I", "N", "M"):
                kb.pressed(k)
            self._send({"ctrl": c, "rid": self.rid, "hmd": self.hmd})
            return

        if tut.get("phase") == "crash":                     # red crash screen: sim frozen, only retry / menu
            op = None
            if kb.pressed("RETURN") or kb.pressed("SPACE") or kb.pressed("R") or kb.pressed("N") or kb.pressed("M"):
                op = "retry"
            if kb.pressed("F1"):
                op = "menu"
            if kb.pressed("LBUTTON"):
                op = self.crash_click() or op
            for k in ("Z", "Y", "L", "I", "T", "P", "G"):
                kb.pressed(k)
            if op:
                self._send({"cmd": "tut", "op": op})
            self._send({"ctrl": c, "rid": self.rid, "hmd": self.hmd})
            return

        def axis(name, pos, neg):
            a, b = kb.down(pos), kb.down(neg)
            v = c[name]
            tgt = (1 if a else 0) - (1 if b else 0)
            if tgt:
                rate = RAMP[name] * (0.45 + 0.55 * min(1.0, abs(v) * 2.5)) if (tgt > 0) == (v >= 0) else CENTER
                v += max(-rate * dt, min(rate * dt, tgt - v))
            else:
                v -= max(-CENTER * dt, min(CENTER * dt, v))
            c[name] = max(-1.0, min(1.0, v))

        axis("ail", "RIGHT", "LEFT")
        axis("elev", "UP", "DOWN")            # JSBSim + elevator = nose down: up arrow = push, down = pull
        axis("rud", "D", "A")
        c["thr"] = max(0.0, min(1.0, c["thr"] + ((1 if kb.down("W") else 0) - (1 if kb.down("S") else 0)) * THR_RATE * dt))
        b = 1.0 if kb.down("B") else 0.0
        c["brk_l"] = c["brk_r"] = max(0.0, min(1.0, c["brk_l"] + max(-BRK_RATE * dt, min(BRK_RATE * dt, b - c["brk_l"]))))
        if kb.pressed("G"):
            c["gear"] = 0.0 if c["gear"] else 1.0
        if kb.pressed("R"):
            self._send({"cmd": "reset", "mode": "air", "user": True})
        if kb.pressed("T"):
            self._send({"cmd": "reset", "mode": "runway", "user": True})
        if kb.pressed("P"):
            self._send({"cmd": "pause"})
        if kb.pressed("V"):
            self.cycle_view(-1 if kb.down("SHIFT") else 1)
        self._orbit_keys(kb)
        if kb.pressed("H"):
            self.panel_on = not self.panel_on
        if kb.pressed("K"):
            self.keys_on = not self.keys_on
        if kb.pressed("U"):
            self.hud = not self.hud
            self.hud_t = 0.0
        if kb.pressed("C"):
            self.look_down = not self.look_down
        self.look_tgt = [-35.0 if self.look_down else 0.0, (60.0 if kb.down("E") else 0.0) - (60.0 if kb.down("Q") else 0.0)]
        # tutorial
        if kb.pressed("F1"):
            self._send({"cmd": "tut", "op": "menu"})
        if kb.pressed("F2"):
            self._send({"cmd": "tut", "op": "stop"})
        if kb.pressed("N"):
            self._send({"cmd": "tut", "op": "next"})
        if kb.pressed("M"):
            self._send({"cmd": "tut", "op": "retry"})
        if kb.pressed("Z"):                                  # say the instruction again
            self._send({"cmd": "tut", "op": "repeat"})
        if kb.pressed("I"):                                  # instruction wording: auto -> keyboard -> rig
            self._send({"cmd": "tut", "op": "mode"})
        if kb.pressed("Y"):                                  # instructor voice on / off
            self._send({"cmd": "voice", "op": "toggle"})
        if kb.pressed("L"):                                  # beginner labels / explanations on / off
            self._send({"cmd": "tut", "op": "beginner"})
        if kb.pressed("RETURN") or kb.pressed("SPACE"):
            if tut.get("phase") in ("brief", "debrief", "crash"):
                self._send({"cmd": "tut", "op": "next"})
        for i in range(0, 10):
            if kb.pressed("K%d" % i):
                self._send({"cmd": "tut", "op": "start", "lesson": i})
        # VR
        if kb.pressed("F3"):
            recenter()
        if kb.pressed("F9"):
            unreal.SystemLibrary.execute_console_command(self.world, "stereo %s" % ("off" if self.hmd else "on"))
        self._send({"ctrl": c, "rid": self.rid, "hmd": self.hmd})

    # ---- third-person views ---------------------------------------------------------------------------------------
    def cycle_view(self, step=1):
        i = VIEWS.index(self.view) if self.view in VIEWS else 0
        self.set_view(VIEWS[(i + step) % len(VIEWS)])

    def set_view(self, v):
        self.view = v
        self.chase_yaw = None
        self.view_pt = None                                   # flyby / tower: placed on the next frame
        if v == "orbit":                                       # start on the right side, then fixed to the world
            self.orbit["orbit"] = list(ORBIT_DEFAULT["orbit"])
            self.orbit_world_yaw = None
        _log("view", v)

    def _orbit_keys(self, kb):
        """Q/E, PageUp/PageDown, + / -, Home and the mouse (monitor) for the outside views."""
        self.orbit_vel = [0.0, 0.0, 0.0]
        if self.view == "cockpit":
            self.mouse_prev = None
            return
        o = self.orbit.get(self.view)
        if self.hmd:                                           # VR: snap steps on key presses
            for k, d, i, stp in (("Q", -1, 0, VR_SNAP_YAW), ("E", 1, 0, VR_SNAP_YAW), ("PRIOR", 1, 1, VR_SNAP_EL), ("NEXT", -1, 1, VR_SNAP_EL)):
                if kb.pressed(k) and o is not None:
                    o[i] += d * stp
            for ks, f in ((("PLUS", "ADD"), 1 / VR_SNAP_ZOOM), (("MINUS", "SUBTRACT"), VR_SNAP_ZOOM)):
                if any([kb.pressed(k) for k in ks]):
                    self._zoom(f)
        else:
            self.orbit_vel = [ORBIT_YAW_RATE * ((1 if kb.down("E") else 0) - (1 if kb.down("Q") else 0)),
                              ORBIT_EL_RATE * ((1 if kb.down("PRIOR") else 0) - (1 if kb.down("NEXT") else 0)),
                              ZOOM_RATE * ((1 if kb.down("MINUS") or kb.down("SUBTRACT") else 0) - (1 if kb.down("PLUS") or kb.down("ADD") else 0))]
            self._mouse(kb)
        if kb.pressed("HOME"):
            self.reset_orbit()

    def reset_orbit(self):
        if self.view in self.orbit:
            self.orbit[self.view][:] = list(ORBIT_DEFAULT[self.view])
            self.orbit_world_yaw = None
        self.view_pt = None
        if self.view in self.view_zoom:
            self.view_zoom[self.view] = 1.0

    def _zoom(self, f):
        if self.view in self.orbit:
            o = self.orbit[self.view]
            o[2] = max(ORBIT_DIST[0], min(ORBIT_DIST[1], o[2] * f))
        elif self.view in self.view_zoom:                     # flyby / tower: zoom the lens (monitor only, see _fov)
            self.view_zoom[self.view] = max(0.1, min(20.0, self.view_zoom[self.view] / f))

    def _mouse(self, kb):
        """monitor: left / right button drag turns around the aircraft, wheel zooms. Both the UE player input (mouse
        captured by the Play viewport) and the Windows cursor (not captured) are read; the bigger one wins."""
        dx = dy = wheel = 0.0
        try:
            pc = unreal.GameplayStatics.get_player_controller(self.world, 0)
            if pc is not None:
                keys = getattr(self, "_mkeys", None)
                if keys is None:
                    keys = self._mkeys = {}
                    for n in ("LeftMouseButton", "RightMouseButton", "MouseWheelAxis", "MouseScrollUp", "MouseScrollDown"):
                        k = unreal.Key()
                        k.set_editor_property("key_name", n)
                        keys[n] = k
                drag = pc.is_input_key_down(keys["LeftMouseButton"]) or pc.is_input_key_down(keys["RightMouseButton"])
                d = pc.get_input_mouse_delta()
                if drag and d:
                    dx, dy = float(d[0]), -float(d[1])            # UE MouseY + = up; screen y + = down
                wheel = float(pc.get_input_analog_key_state(keys["MouseWheelAxis"]) or 0.0)
                if not wheel:
                    wheel = (1.0 if pc.was_input_key_just_pressed(keys["MouseScrollUp"]) else 0.0) - \
                            (1.0 if pc.was_input_key_just_pressed(keys["MouseScrollDown"]) else 0.0)
        except Exception as e:
            if time.perf_counter() - self.last_log > 2:
                _log("mouse", repr(e))
        cur = kb.cursor() if (kb.down("LBUTTON") or kb.down("RBUTTON")) else None
        if cur and self.mouse_prev:
            wx, wy = cur[0] - self.mouse_prev[0], cur[1] - self.mouse_prev[1]
            if abs(wx) + abs(wy) > abs(dx) + abs(dy):
                dx, dy = float(wx), float(wy)
        self.mouse_prev = cur
        self.apply_mouse(dx, dy, wheel)

    def apply_mouse(self, dx, dy, wheel):
        """dx / dy in screen pixels (y down), wheel in notches (+ = toward the screen = closer)."""
        o = self.orbit.get(self.view)
        if o is not None and (dx or dy):
            o[0] += dx * MOUSE_DEG_PX
            o[1] += dy * MOUSE_DEG_PX                         # drag down = camera goes up (look from above)
        if wheel:
            self._zoom(WHEEL_STEP ** wheel)

    def _ground_ignore(self):
        """actors a ground trace must pass through: the aircraft and the camera rig (HUD, panels and the hidden crash /
        source plates hang on the view camera and have collision - a trace under the camera hit its own red plate)."""
        ig = getattr(self, "ground_ig", None)
        if ig is None or getattr(self, "ground_ig_world", None) is not self.world:
            ig = list(self.trace_ignore)
            try:
                if self.camera:
                    ig += [self.camera] + list(self.camera.get_attached_actors(True, True))
            except Exception as e:
                _log("ground ignore", repr(e))
            self.ground_ig, self.ground_ig_world = ig, self.world
        return ig

    def _has_terrain(self):
        return self.cesium_mode in ("terrain", "photoreal") or (self.cesium_mode == "vworld" and getattr(self, "vw_terrain", False))

    def _ground_z(self, x, y):
        """world Z (cm) of the ground under world point x, y: the real terrain (Cesium tiles have collision, one line
        trace) when there is terrain, else the flat field elevation on the curved Earth."""
        f, s = self._frame, self.s or {}
        if f is None:
            return -1e9
        lat = f.lat0 + x / 100.0 / 110950.0
        lon = f.lon0 + y / 100.0 / (111320.0 * math.cos(math.radians(f.lat0)))
        flat = f.world(lat, lon, s.get("field_m", 58.2) + s.get("geoid_n", 0.0))[2]
        if not self._has_terrain() or self.world is None:
            return flat
        try:
            r = unreal.SystemLibrary.line_trace_single(self.world, unreal.Vector(x, y, flat + 1000000.0), unreal.Vector(x, y, flat - 200000.0),
                                                       unreal.TraceTypeQuery.TRACE_TYPE_QUERY1, False, self._ground_ignore(),
                                                       unreal.DrawDebugTrace.NONE, True)
            hit = r if isinstance(r, unreal.HitResult) else (r[-1] if isinstance(r, (tuple, list)) else None)
            t = hit.to_tuple() if hit is not None else None
            if t and t[0]:
                return t[4].z
        except Exception as e:
            if time.perf_counter() - getattr(self, "gz_log_t", 0.0) > 5.0:
                self.gz_log_t = time.perf_counter()
                _log("ground trace", repr(e))
        return flat

    def _look(self, eye, tgt):
        r = unreal.MathLibrary.find_look_at_rotation(eye, tgt)
        if self.hmd:                                          # VR: yaw only, the head does pitch / roll (comfort)
            r = unreal.Rotator(roll=0.0, pitch=0.0, yaw=r.yaw)
        return r

    def _fov(self, want):
        """monitor only (VR: the headset owns the lens)."""
        if self.hmd:
            want = VIEW_FOV
        if self.fov_set is None or abs(want - self.fov_set) > 0.05:
            self.fov_set = want
            try:
                self.view_cam.camera_component.set_field_of_view(want)
            except Exception as e:
                _log("fov", repr(e))
            self._attrib_place()                              # the source note keeps its size on screen

    def _place_outside(self, dt, loc, rot):
        tgt = loc + unreal.Vector(0, 0, LOOK_AT_UP_CM)
        v = self.view
        if v in ("chase", "orbit"):
            o = self.orbit[v]
            if not self.hmd:
                o[0] += self.orbit_vel[0] * dt
                o[1] += self.orbit_vel[1] * dt
                if self.orbit_vel[2]:
                    o[2] = o[2] * math.exp(self.orbit_vel[2] * dt)
            o[1] = max(ORBIT_EL[0], min(ORBIT_EL[1], o[1]))
            o[2] = max(ORBIT_DIST[0], min(ORBIT_DIST[1], o[2]))
            if v == "chase":                                  # behind, the heading followed smoothly (as before)
                if self.chase_yaw is None:
                    self.chase_yaw = rot.yaw
                d = (rot.yaw - self.chase_yaw + 180) % 360 - 180
                self.chase_yaw += d * min(1.0, 3.0 * dt)
                base = self.chase_yaw + 180.0
            else:                                             # orbit: fixed to the world (set when entering)
                if self.orbit_world_yaw is None:
                    self.orbit_world_yaw = rot.yaw
                base = self.orbit_world_yaw
            az, el = math.radians(base + o[0]), math.radians(o[1])
            off = unreal.Vector(math.cos(el) * math.cos(az), math.cos(el) * math.sin(az), math.sin(el)) * o[2]
            # the chase default reproduces the old fixed chase point (2600 cm back, 650 up from the aircraft origin)
            eye = loc + off if v == "chase" else tgt + off
            gz = self._ground_z(eye.x, eye.y) + 200.0
            if eye.z < gz:
                eye = unreal.Vector(eye.x, eye.y, gz)
            self.camera.set_actor_location_and_rotation(eye, self._look(eye, tgt), False, False)
            self._fov(VIEW_FOV)
            return
        # flyby / tower: a fixed point
        new = False
        if v == "tower":
            if self.view_pt is None:
                f, s = self._frame, self.s
                tl = s.get("tower") or TOWER_LL
                p = f.world(tl[0], tl[1], s.get("field_m", 58.2) + s.get("geoid_n", 0.0) + TOWER_AGL_M)
                self.view_pt = [unreal.Vector(*p), None]
                new = True
        else:
            fwd = rot.get_forward_vector()
            fh = unreal.Vector(fwd.x, fwd.y, 0.0)
            n = math.hypot(fh.x, fh.y)
            fh = fh * (1.0 / n) if n > 1e-3 else unreal.Vector(1, 0, 0)
            spd = max(0.0, (self.s or {}).get("kts", 0.0)) * 0.5144
            lead = max(FLYBY_MIN_M, spd * FLYBY_LEAD_S) * 100.0
            pt = self.view_pt[0] if self.view_pt else None
            if pt is not None:
                rel = loc - pt
                past = (rel.x * fh.x + rel.y * fh.y) > lead * 0.6          # well past the point
                far = math.sqrt(rel.x ** 2 + rel.y ** 2 + rel.z ** 2) > max(3 * lead, 500000.0)
                if past or far:
                    pt = None
            if pt is None:
                side = unreal.Vector(-fh.y, fh.x, 0.0)                     # right of the track (X north, Y east)
                p = loc + fh * lead + side * (FLYBY_SIDE_M * 100.0) - unreal.Vector(0, 0, FLYBY_DOWN_M * 100.0)
                gz = self._ground_z(p.x, p.y) + 300.0
                self.view_pt = [unreal.Vector(p.x, p.y, max(p.z, gz)), None]
                self.flyby_n = getattr(self, "flyby_n", 0) + 1
                new = True
        eye = self.view_pt[0]
        if self.hmd:                                          # VR: static, aimed once (snap), the head looks around
            if new or self.view_pt[1] is None:
                self.view_pt[1] = self._look(eye, tgt)
            rr = self.view_pt[1]
        else:
            rr = self._look(eye, tgt)
        self.camera.set_actor_location_and_rotation(eye, rr, False, False)
        dist_m = math.sqrt((tgt.x - eye.x) ** 2 + (tgt.y - eye.y) ** 2 + (tgt.z - eye.z) ** 2) / 100.0
        span = TOWER_SPAN_M / self.view_zoom.get(v, 1.0)
        self._fov(max(2.0, min(VIEW_FOV, math.degrees(2 * math.atan2(span / 2, max(1.0, dist_m))))))

    # ---------------------------------------------------------------------------------------------------------------
    def crash_uv(self, sx=None, sy=None):
        """viewport pixel (default: the mouse) -> (u, v) on the crash picture, or None."""
        if not self.crash_panel or self.world is None:
            return None
        pc = unreal.GameplayStatics.get_player_controller(self.world, 0)
        if pc is None:
            return None
        if sx is None:
            m = pc.get_mouse_position()
            m = [x for x in (m if isinstance(m, (tuple, list)) else (m,)) if not isinstance(x, bool)]
            if len(m) < 2:
                return None
            sx, sy = m[0], m[1]
        r = pc.deproject_screen_position_to_world(sx, sy)
        r = [x for x in (r if isinstance(r, (tuple, list)) else (r,)) if not isinstance(x, bool)]
        if len(r) < 2:
            return None
        o, d = r[0], r[1]
        a = self.crash_panel
        P, n = a.get_actor_location(), a.get_actor_up_vector()
        den = d.x * n.x + d.y * n.y + d.z * n.z
        if abs(den) < 1e-6:
            return None
        t = ((P.x - o.x) * n.x + (P.y - o.y) * n.y + (P.z - o.z) * n.z) / den
        h = unreal.Vector(o.x + d.x * t - P.x, o.y + d.y * t - P.y, o.z + d.z * t - P.z)
        fx, ry = a.get_actor_forward_vector(), a.get_actor_right_vector()     # plane local X = picture right, local Y = picture down
        u = 0.5 + (h.x * fx.x + h.y * fx.y + h.z * fx.z) / CRASH_W
        v = 0.5 + (h.x * ry.x + h.y * ry.y + h.z * ry.z) / CRASH_H
        return u, v

    def crash_click(self, sx=None, sy=None):
        uv = self.crash_uv(sx, sy)
        if not uv:
            return None
        for op, (u0, v0, u1, v1) in CRASH_BTN.items():
            if u0 <= uv[0] <= u1 and v0 <= uv[1] <= v1:
                return op
        return None

    def _crash_screen(self, tut):
        on = tut.get("phase") == "crash" and self.panel_tex is not None and self.crash_panel is not None
        if on and self.crash_mid is not None:
            self.crash_mid.set_texture_parameter_value("Tex", self.panel_tex)
        if on == self.crash_shown:
            return
        self.crash_shown = on
        for a in (self.crash_back, self.crash_panel):
            if a:
                a.set_actor_hidden_in_game(not on)
        try:                                                  # mouse cursor for the buttons (monitor)
            pc = unreal.GameplayStatics.get_player_controller(self.world, 0)
            if pc and not self.hmd:
                pc.set_editor_property("show_mouse_cursor", on)
        except Exception as e:
            _log("crash cursor", repr(e))

    def _check_hmd(self, now):
        if now - self.hmd_check_t < 1.0 and self.preset is not None:
            return
        self.hmd_check_t = now
        try:
            h = bool(unreal.HeadMountedDisplayFunctionLibrary.is_head_mounted_display_enabled())
        except Exception:
            h = False
        want = "vr" if h else "monitor"
        if h != self.hmd or self.preset != want:
            self.hmd = h
            if h:
                try:
                    org = getattr(unreal.HMDTrackingOrigin, "LOCAL", None) or getattr(unreal.HMDTrackingOrigin, "EYE")
                    unreal.HeadMountedDisplayFunctionLibrary.set_tracking_origin(org)       # seated: origin = head
                    recenter()
                except Exception as e:
                    _log("tracking origin", e)
            apply_preset(want, self.world)
            self.preset = want
            if self.view_cam:                                       # in VR the HMD owns the camera
                self.view_cam.set_actor_relative_rotation(unreal.Rotator(roll=0.0, pitch=0.0, yaw=0.0), False, True)

    def _pose(self, now):
        s = self.s
        if self.no_interp or s.get("paused"):
            loc, rot = self.to_world(s)
            return loc, rot
        r = self.interp.sample(now)
        if r is None:
            return self.to_world(s)
        (x, y, z), (phi, th, psi) = r
        return unreal.Vector(x, y, z), unreal.Rotator(roll=phi, pitch=th, yaw=psi)

    def _place(self, dt, now):
        loc, rot = self._pose(now)
        self.last_pose = (loc, rot)
        # teleport=False keeps the previous transform for motion vectors (TSR / TAA would smear the panel / aircraft)
        self.aircraft.set_actor_location_and_rotation(loc, rot, False, False)
        fwd, right, up = rot.get_forward_vector(), rot.get_right_vector(), rot.get_up_vector()
        if self.view not in VIEWS:
            self.view = "cockpit"
        if self.view == "cockpit":
            eye = loc + fwd * EYE[0] + right * EYE[1] + up * EYE[2]
            self.camera.set_actor_location_and_rotation(eye, rot, False, False)
            self._fov(VIEW_FOV)
        else:
            self._place_outside(dt, loc, rot)
        if not self.hmd:                                            # monitor head look (C = look down, Q/E = left/right)
            k = min(1.0, 6.0 * dt)
            changed = False
            tgt = self.look_tgt if self.view == "cockpit" else (0.0, 0.0)   # chase: camera aims at the aircraft (centred)
            if self.view != getattr(self, "_look_view", None):
                self._look_view = self.view
                self.look = [float(tgt[0]), float(tgt[1])]               # snap on a view change (no swing across)
                changed = True
            for i in (0, 1):
                nv = self.look[i] + (tgt[i] - self.look[i]) * k
                changed |= abs(nv - self.look[i]) > 1e-3
                self.look[i] = nv
            if changed or self.frames < 3:
                self.view_cam.set_actor_relative_rotation(unreal.Rotator(roll=0.0, pitch=self.look[0], yaw=self.look[1]), False, True)

    def _controls(self, dt):
        s = self.s
        src = s if "ail" in s else self.ctrl
        k = min(1.0, 25.0 * dt)
        for n in self.disp:
            self.disp[n] += (float(src.get(n, s.get(n, 0.0)) or 0.0) - self.disp[n]) * k
        d, P = self.disp, self.pivots
        # centre stick (+-STICK_ROLL / STICK_PITCH = the rig's +-20 deg), throttle on the left console swinging
        # -THR_SWING (idle, aft) .. +THR_SWING (full, forward), pedals fore/aft + toe brakes, gear handle follows the command
        if "StickPivot" in P:
            P["StickPivot"][0].set_actor_relative_rotation(unreal.Rotator(roll=STICK_ROLL * d["ail"], pitch=-STICK_PITCH * d["elev"], yaw=0.0), False, True)
        if "ThrottlePivot" in P:
            P["ThrottlePivot"][0].set_actor_relative_rotation(unreal.Rotator(roll=0.0, pitch=-THR_SWING * (2.0 * d["thr"] - 1.0), yaw=0.0), False, True)
        for tag, sign, bk in (("PedalL", -1.0, "brk_l"), ("PedalR", 1.0, "brk_r")):
            if tag in P:
                a, base = P[tag]
                a.root_component.set_relative_location_and_rotation(base + unreal.Vector(PEDAL_CM * sign * d["rud"], 0, 0),
                                                                    unreal.Rotator(roll=0.0, pitch=-TOE_DEG * d[bk], yaw=0.0), False, True)
        gv = self.gauge_vals
        cmd = float(s.get("gear_cmd", self.ctrl.get("gear", 1.0)) or 0.0)
        gv["gh"] = gv.get("gh", cmd) + (cmd - gv.get("gh", cmd)) * min(1.0, 8.0 * dt)
        if "GearHandle" in P:
            P["GearHandle"][0].set_actor_relative_rotation(unreal.Rotator(roll=0.0, pitch=GEAR_HANDLE_DEG * (2.0 * gv["gh"] - 1.0), yaw=0.0), False, True)
        g = s.get("gear", 1.0) > 0.05
        if g != self.gear_shown:
            self.gear_shown = g
            for a in self.gear_parts:
                a.set_actor_hidden_in_game(not g)
        lit = s.get("gear", 0.0) > 0.98
        if self.gear_lights and lit != self.gear_lit:
            self.gear_lit = lit
            self.gear_lights.set_actor_hidden_in_game(not lit)
        self._gauges(dt)
        self._pilot()
        if s.get("rid") != self.gmax_rid:
            self.gmax_rid, self.gmax = s.get("rid"), 1.0
        if not s.get("paused"):
            self.gmax = max(self.gmax, s.get("nz", 1.0))
        self.warnings = self._warnings()
        self._lights()

    def _pilot(self):
        """pilot body (Scripts/pilot/ue_pilot.py): morph targets follow the controls as they are drawn (weights from the
        stick / throttle actors' tilt, so the sign conventions of _controls carry over), the helmet rides on the view
        camera (follows the look / HMD) and is left out of the main pass in the cockpit view (no helmet inside the eye;
        it still casts its shadow); outside views put it back on the shoulders."""
        b, h = self.pilot_body, self.pilot_head
        if b:
            try:
                d, P, w = self.disp, self.pivots, {}
                if "StickPivot" in P:
                    u = unreal.MathLibrary.get_up_vector(P["StickPivot"][0].root_component.get_editor_property("relative_rotation"))
                    f, r = math.degrees(math.atan2(u.x, u.z)) / STICK_PITCH, math.degrees(math.atan2(u.y, u.z)) / STICK_ROLL
                    w.update(StickF=max(0.0, f), StickB=max(0.0, -f), StickR=max(0.0, r), StickL=max(0.0, -r))
                if "ThrottlePivot" in P:
                    u = unreal.MathLibrary.get_up_vector(P["ThrottlePivot"][0].root_component.get_editor_property("relative_rotation"))
                    t = math.degrees(math.atan2(u.x, u.z)) / THR_SWING
                    w.update(ThrF=max(0.0, t), ThrB=max(0.0, -t))
                w.update(RudR=max(0.0, d["rud"]), RudL=max(0.0, -d["rud"]), ToeL=d["brk_l"], ToeR=d["brk_r"])
                sk = b.skeletal_mesh_component
                for k, v in w.items():
                    sk.set_morph_target(k, min(1.0, v), False)
            except Exception as e:
                if not getattr(self, "pilot_err", None):
                    self.pilot_err = repr(e)
                    _log("pilot morphs", repr(e))
        if h and self.view != self.pilot_view:
            self.pilot_view = self.view
            R = unreal.AttachmentRule
            try:
                c = h.static_mesh_component
                if self.view == "cockpit" and self.view_cam:
                    h.attach_to_actor(self.view_cam, unreal.Name(""), R.SNAP_TO_TARGET, R.SNAP_TO_TARGET, R.KEEP_WORLD, False)
                    c.set_render_in_main_pass(False)
                elif self.aircraft:
                    h.attach_to_actor(self.aircraft, unreal.Name(""), R.SNAP_TO_TARGET, R.SNAP_TO_TARGET, R.KEEP_WORLD, False)
                    h.set_actor_relative_location(unreal.Vector(*EYE), False, True)
                    c.set_render_in_main_pass(True)
            except Exception as e:
                _log("pilot head", repr(e))

    def _warnings(self):
        """active warnings (priority order): pullup, terrain, overg, stall, gear."""
        s = self.s
        w = []
        if s.get("paused") or not self.startup_done:
            return w
        air = not s.get("wow")
        r = self.radar_m if self.radar_m is not None else s.get("agl_m")
        vs = s.get("vs_fpm", 0) * 0.00508
        if self.crashed or s.get("crashed"):
            w.append("terrain")
        elif r is not None and air and vs < -1 and r / -vs < 6.0 and not (s.get("gear", 0) > 0.5 and vs > -6.0):
            w.append("pullup")
        nz = s.get("nz", 1.0)
        if nz > 9.0 or nz < -3.0:
            w.append("overg")
        if air and (s.get("alpha", 0) > 25 or (s.get("kts", 999) < 120 and (s.get("agl_m", 0) or 0) > 15)):
            w.append("stall")
        # F-16 landing gear warning: gear up, below 190 kt and 10,000 ft, descending faster than 250 fpm
        if air and s.get("kts", 999) < 190 and s.get("alt_m", 1e9) / 0.3048 < 10000 and s.get("gear", 1) < 0.5 and s.get("vs_fpm", 0) < -250:
            w.append("gear")
        return w

    def _lights(self):
        s = self.s
        tut = s.get("tut") or {}
        w = self.warnings
        want = dict(MC=bool(w), WARN=any(k in ("pullup", "terrain", "overg", "stall") for k in w), BRAKE=s.get("brk", 0.0) > 0.3,
                    ASSIST=bool(s.get("assist")), SLOW=bool(s.get("slow")), VOICE=bool(tut.get("voice")))
        if want["WARN"] and int(time.perf_counter() * 2.5) % 2:
            want["WARN"] = False                                       # the red warning light flashes
        for k, on in want.items():
            a = self.lights.get(k)
            if a and self.lights_on.get(k) != on:
                self.lights_on[k] = on
                a.set_actor_hidden_in_game(not on)

    def _gauges(self, dt):
        """standby needles (cockpit_gauges scales, clockwise as seen by the pilot = negative roll of the needle actor
        whose X points at the pilot) and the ADI ball (pitch first, then bank about the viewing axis)."""
        s, gv = self.s, self.gauge_vals
        k = min(1.0, 15.0 * dt)
        ft = s.get("alt_m", 0.0) / 0.3048
        tgt = dict(kts=s.get("kts", 0.0), ft=ft, vs=s.get("vs_fpm", 0.0))
        for n, v in tgt.items():
            gv[n] = v if n not in gv or abs(v - gv[n]) > (2000.0 if n == "ft" else 1e9) else gv[n] + (v - gv[n]) * k
        ang = dict(asi=gauges.asi_deg(gv["kts"]), alt=gauges.alt_deg(gv["ft"]), alt10k=gauges.alt10k_deg(gv["ft"]), vsi=gauges.vsi_deg(gv["vs"]))
        for n, a in self.needles.items():
            a.set_actor_relative_rotation(unreal.Rotator(roll=-ang[n], pitch=0.0, yaw=0.0), False, True)
        if self.adi and self.last_pose:
            r = self.last_pose[1]
            ball = unreal.MathLibrary.compose_rotators(unreal.Rotator(roll=0.0, pitch=-r.pitch, yaw=0.0), unreal.Rotator(roll=r.roll, pitch=0.0, yaw=0.0))
            self.adi.set_actor_relative_rotation(ball, False, True)

    def _fog_follow(self, now):
        """keep the height fog at sea level under the aircraft, 2 Hz. The world frame is the flat tangent plane at RKTU, so
        far away the ground lies far below Z = 0 (1.3 km at 170 km, Seoraksan) and the exponential fog (falloff 0.2)
        became opaque there. Near RKTU this is the old placement (Z = 0)."""
        if now - getattr(self, "fog_t", 0.0) < 0.5 or not self.s or self._frame is None or self.world is None:
            return
        self.fog_t = now
        try:
            if getattr(self, "fog_world", None) is not self.world:
                fogs = unreal.GameplayStatics.get_all_actors_of_class(self.world, unreal.ExponentialHeightFog)
                self.fog, self.fog_world, self.fog_z = (fogs[0] if fogs else None), self.world, None
                self.fog_z0 = fogs[0].get_actor_location().z if fogs else 0.0
            if self.fog is None:
                return
            s, f = self.s, self._frame
            x, y, z = f.world(s["lat"], s["lon"], s.get("geoid_here", s.get("geoid_n", 0.0)))
            z += self.fog_z0
            if self.fog_z is None or abs(z - self.fog_z) > 500.0:          # 5 m steps: no per-frame changes
                self.fog.set_actor_location(unreal.Vector(x, y, z), False, True)
                self.fog_z = z
        except Exception as e:
            if now - self.last_log > 2:
                _log("fog follow", repr(e))

    def _trace(self, now):
        """Height of the wheels above whatever is under the aircraft (Cesium terrain tiles have collision), 10 Hz.
        JSBSim's ground is flat at the field elevation, so with real terrain this is the only hill check: below the
        terrain while JSBSim still flies = terrain collision -> pause."""
        s = self.s
        if not s or not self.last_pose or now - self.trace_t < 0.1:
            return
        self.trace_t = now
        if self.cesium_mode not in ("terrain", "photoreal") and not (self.cesium_mode == "vworld" and getattr(self, "vw_terrain", False)):
            self.radar_m = s.get("agl_m")
            return
        loc = self.last_pose[0]
        start, end = loc + unreal.Vector(0, 0, 200000.0), loc - unreal.Vector(0, 0, 3000000.0)
        try:
            r = unreal.SystemLibrary.line_trace_single(self.world, start, end, unreal.TraceTypeQuery.TRACE_TYPE_QUERY1, False,
                                                       self._ground_ignore(), unreal.DrawDebugTrace.NONE, True)
            hit = r if isinstance(r, unreal.HitResult) else (r[-1] if isinstance(r, (tuple, list)) else None)
            t = hit.to_tuple() if hit is not None else None
            if t and t[0]:
                self.radar_m = (loc.z - t[4].z - Z_OFFSET_CM) / 100.0
                self.terrain_hit = True
            else:
                self.radar_m = s.get("agl_m")
                if not getattr(self, "terrain_hit", False) and now - self.t_bind > 20.0:
                    self._cesium_fallback("no terrain tiles 20 s after Play (token rejected / offline?)")
        except Exception as e:
            self.radar_m = s.get("agl_m")
            if now - self.last_log > 2:
                _log("trace", repr(e))
        # DEM ground (server terrain="dem"): the server sees the same terrain and owns the crash (red screen) - no pause here
        if (not self.crashed and self.radar_m is not None and self.radar_m < -1.0 and not s.get("wow") and s.get("agl_m", 0) > 15
                and not s.get("paused") and s.get("terrain") != "dem"):
            self.crashed = True
            self._send({"cmd": "pause"})
            _log("terrain collision at radar %.1f m, JSBSim agl %.1f m" % (self.radar_m, s.get("agl_m", 0)))

    def _hud_extra(self, now):
        s = self.s
        tut = s.get("tut") or {}
        ex = dict(radar_m=self.radar_m if self.radar_m is not None else s.get("agl_m"))
        w = self.warnings
        if "terrain" in w:
            ex["warn"] = "TERRAIN  -  R / T RESTART"
        elif w:
            ex["warn"] = hud.WARN_TXT[w[0]][0]
            ex["warn_key"] = w[0]
        ex.update(beginner=bool(tut.get("beginner", True)), line_tex=self.line_tex, menu=tut.get("phase") == "menu",
                  line_on=tut.get("phase") in ("practice", "solo", "demo", "brief", "crash"))
        if not self.startup_done:
            ex["note"] = "LOADING - SIM PAUSED"
        elif getattr(self, "cesium_failed", None) and now - self.t_bind < 25:
            ex["note"] = self.cesium_failed if isinstance(self.cesium_failed, str) and self.cesium_failed.isupper() else "CESIUM TERRAIN FAILED (TOKEN?) - GRID GROUND"
        elif self.cesium_mode == "vworld" and self.vw_note:
            ex["note"] = self.vw_note
        return ex

    def _mfd_extra(self):
        s = self.s
        lat, lon = s["lat"], s["lon"]
        ml, mo = 110950.0, 111320.0 * math.cos(math.radians(lat))
        rws = []
        for rw in s.get("runways") or RUNWAYS:
            rws.append(((rw[0] - lat) * ml, (rw[1] - lon) * mo, (rw[2] - lat) * ml, (rw[3] - lon) * mo))
        n, e = rws[0][0], rws[0][1]
        line = {"terrain": "MAP: CESIUM WORLD TERRAIN", "photoreal": "MAP: GOOGLE 3D TILES", "photo": "MAP: SATELLITE PHOTO (FLAT)",
                "grid": "MAP: GRID (FLAT, 1 KM)", "fields": "MAP: FIELDS (FLAT, DRAWN)",
                "vworld": "MAP: V-WORLD PHOTO " + ("+ DEM 30 M" + (" + BLDG" if getattr(self, "vw_bldg", False) else "") if getattr(self, "vw_local", False) else "+ TERRAIN" if getattr(self, "vw_terrain", False) else "(FLAT)"),
                "none": "NO CESIUM PLUGIN", "error": "CESIUM ERROR - SEE LOG"}.get(self.cesium_mode, "")
        return dict(runways=rws, rkt_dist_m=math.hypot(n, e), rkt_brg=math.degrees(math.atan2(e, n)), cesium_line=line)

    def _overlay(self, now):
        s = self.s
        fresh = s is not None and now - self.rx_t < 1.0
        P = self.painter
        hv = self.view == "cockpit"
        if "HUD" in self.screens and getattr(self, "hud_vis", None) != hv:      # no HUD in the chase view
            self.hud_vis = hv
            self.screens["HUD"][0].set_actor_hidden_in_game(not hv)
        if hv and "HUD" in self.screens and self.last_pose:          # ladder: every frame, interpolated attitude
            r = self.last_pose[1]
            mid = self.screens["HUD"][1]
            mid.set_scalar_parameter_value("Roll", math.radians(r.roll))
            mid.set_scalar_parameter_value("Pitch", math.radians(r.pitch))
            on = 1.0 if (self.hud and fresh) else 0.0
            if getattr(self, "ladder_on", None) != on:
                self.ladder_on = on
                mid.set_scalar_parameter_value("LadderOn", on)
        if P and hv and "HUD" in self.screens and now - self.hud_t >= 1.0 / HUD_HZ:
            self.hud_t = now
            t0 = time.perf_counter()
            try:
                if not fresh:
                    P._begin(P.rt_hud, hud.CLEAR)
                    P.text("NO DATA - start  python sim/server.py  (UDP 4220)", 512, 450, 1.0, hud.AMBER)
                    P._end()
                elif not self.hud:
                    if self.hud_n >= 0:
                        P._begin(P.rt_hud, hud.CLEAR); P._end()
                        self.hud_n = -1
                else:
                    sv = dict(s)
                    if self.last_pose:                      # interpolated attitude (smooth ladder)
                        r = self.last_pose[1]
                        sv["phi"], sv["theta"] = r.roll, r.pitch
                    P.draw_hud(sv, self._hud_extra(now))
                    self.hud_n = max(0, self.hud_n) + 1
                    self.hud_ms += ((time.perf_counter() - t0) * 1000 - self.hud_ms) * 0.05
            except Exception as e:
                if now - self.last_log > 2:
                    self.last_log = now
                    _log("hud draw", repr(e))
        if P and fresh and now - self.mfd_t >= 1.0 / DISP_HZ:          # one display per call, in turn (spreads the cost)
            self.mfd_t = now
            try:
                self.mfd_i = (getattr(self, "mfd_i", 0) + 1) % len(DISP_ORDER)
                tag = DISP_ORDER[self.mfd_i]
                if tag in self.screens:
                    t0 = time.perf_counter()
                    tut = s.get("tut") or {}
                    P.draw_display(tag, s, dict(beginner=bool(tut.get("beginner", True)), radar_m=self.radar_m, gmax=self.gmax,
                                                warnings=self.warnings, panel_tex=self.panel_tex, loading=not self.startup_done))
                    self.disp_ms += ((time.perf_counter() - t0) * 1000 - self.disp_ms) * 0.05
            except Exception as e:
                if now - self.last_log > 2:
                    self.last_log = now
                    _log("display draw", repr(e))
        if now - self.txt_t < 1 / 15:
            return
        self.txt_t = now
        # tutorial panel (Korean text rendered to PNG by sim/tutorial.py), H toggles
        if self.key_panel:                                      # key guide panel: shown in the menu, K toggles it in flight
            ks = (self.keys_on or bool(((s or {}).get("tut") or {}).get("menu"))) and self.keys_tex
            if self.keys_shown != ks:
                self.keys_shown = ks
                self.key_panel.set_actor_hidden_in_game(not ks)
        tut = (s or {}).get("tut") or {}
        # lesson panel picture + HUD instruction line (Korean PNGs from the server) -> training display, tutorial panel, HUD
        if tut.get("ver") != self.tut_ver and tut.get("img"):
            try:
                if os.path.exists(tut["img"]):
                    tex = unreal.RenderingLibrary.import_file_as_texture2d(self.world, tut["img"])
                    if tex:
                        self.panel_tex = tex
                        if self.panel_mid:
                            self.panel_mid.set_texture_parameter_value("Tex", tex)
                if tut.get("line_img") and os.path.exists(tut["line_img"]):
                    self.line_tex = unreal.RenderingLibrary.import_file_as_texture2d(self.world, tut["line_img"])
                self.tut_ver = tut.get("ver")
                self.mfd_t = 0.0
            except Exception as e:
                _log("tut image", repr(e))
        # world-space lesson panel (lower left): VR only (11-05: on the monitor it floated over the view; the centre
        # training display shows the same picture there)
        show = bool(tut.get("on")) and self.panel_tex is not None and self.panel_on and self.hmd
        if self.panel:
            if self.panel_shown != show:
                self.panel_shown = show
                self.panel.set_actor_hidden_in_game(not show)
        self._crash_screen(tut)
        # beginner callouts on the panel
        beg = bool(tut.get("beginner", True)) and self.view == "cockpit"
        if beg != self.beg_shown:
            self.beg_shown = beg
            for a in self.beg_labels:
                a.set_actor_hidden_in_game(not beg)

    def _attribution(self):
        """V-World source note (terms 13조) in the vworld mode: a small plate on the view camera, lower right on the
        monitor (sized with the lens, so the tower zoom keeps it the same on screen), low centre in VR. Spawned here."""
        on = self.cesium_mode == "vworld"
        a = getattr(self, "attrib", None)
        if not on:
            if a:
                a.set_actor_hidden_in_game(True)
            return
        try:
            if a is None:
                a = self._find("Attribution")          # build_level: plate on the view camera (M_Crash: unlit, no depth test)
                if a is None:
                    _log("attribution: no Attribution actor in the map (run build_level.py)")
                    return
                mid = a.static_mesh_component.create_and_set_material_instance_dynamic(0)
                png = (VW_BLDG_ATTRIB_PNG if getattr(self, "vw_bldg", False) else VW_TERRAIN_ATTRIB_PNG) if getattr(self, "vw_local", False) else VW_ATTRIB_PNG
                # + Copernicus credit (+ building data credit)
                tex = unreal.RenderingLibrary.import_file_as_texture2d(self.world, png) if os.path.exists(png) else None
                if tex and mid:
                    mid.set_texture_parameter_value("Tex", tex)
                    self.attrib_aspect = tex.blueprint_get_size_x() / max(1, tex.blueprint_get_size_y())
                else:
                    _log("attribution image missing", png)
                self.attrib = a
                self.attrib_key = None
            a.set_actor_hidden_in_game(False)
            self._attrib_place()
            _log("V-World attribution shown")
        except Exception as e:
            _log("attribution", repr(e))

    def _attrib_place(self):
        a = getattr(self, "attrib", None)
        if a is None or self.cesium_mode != "vworld":
            return
        try:
            vp = unreal.WidgetLayoutLibrary.get_viewport_size(self.world)
            aspect = vp.x / vp.y if vp.y > 0 else 16 / 9
        except Exception:
            aspect = 16 / 9
        fov = self.fov_set or VIEW_FOV
        key = (round(fov, 2), round(aspect, 3), self.hmd)
        if key == getattr(self, "attrib_key", None):
            return
        self.attrib_key = key
        D = VW_ATTRIB_D
        if self.hmd:                                             # VR: low centre, 26 deg down, fixed size (head-locked)
            hw, w = D * math.tan(math.radians(VIEW_FOV / 2)), 55.0 if getattr(self, "vw_local", False) else 40.0
            pos = unreal.Vector(D, 0.0, -D * math.tan(math.radians(26.0)))
        else:
            hw = D * math.tan(math.radians(fov / 2))             # half view width at D
            hh = hw / aspect
            w = 2 * hw * (VW_TERRAIN_ATTRIB_W if getattr(self, "vw_local", False) else VW_ATTRIB_W)
            h = w / getattr(self, "attrib_aspect", 1024 / 96)
            m = 0.015 * 2 * hw
            pos = unreal.Vector(D, hw - m - w / 2, -(hh - m - h / 2))
        h = w / getattr(self, "attrib_aspect", 1024 / 96)
        # plane local X = picture right, local Y = picture down (same rotation as the crash panel: normal toward the eye)
        r = unreal.MathLibrary.make_rot_from_zx(unreal.Vector(-1, 0, 0), unreal.Vector(0, 1, 0))
        a.set_actor_relative_location(pos, False, True)
        a.set_actor_relative_rotation(r, False, True)
        a.set_actor_relative_scale3d(unreal.Vector(w / 100.0, h / 100.0, 1.0))

    # ---- Busan minimap ----------------------------------------------------------------------------------------------
    def _minimap_init(self):
        """once per Play world: plate, render target, picture + bounds (sim/minimap_build.py). Leaves mm['ok'] False when
        anything is missing (logged once) - the sim runs as before."""
        mm = self.mm = dict(world=self.world, ok=False, shown=None, key=None, t=0.0, pos=None)
        try:
            meta = json.load(open(os.path.join(MINIMAP_DIR, "busan_minimap.json"), encoding="utf-8"))
            png = os.path.join(MINIMAP_DIR, "busan_minimap.png")
            a = self._find("Minimap")
            if a is None:
                _log("minimap: no Minimap actor in the map (run Scripts/add_minimap.py)")
                return
            tex = unreal.RenderingLibrary.import_file_as_texture2d(self.world, png)
            if tex is None:
                _log("minimap: cannot load", png)
                return
            n = int(meta.get("size") or tex.blueprint_get_size_x())
            rt = unreal.RenderingLibrary.create_render_target2d(self.world, n, n, unreal.TextureRenderTargetFormat.RTF_RGBA8,
                                                                  unreal.LinearColor(0, 0, 0, 1))
            mid = a.static_mesh_component.create_and_set_material_instance_dynamic(0)
            mid.set_texture_parameter_value("Tex", rt)
            mm.update(ok=True, actor=a, tex=tex, rt=rt, n=n, merc=meta["merc"],
                      white=unreal.load_asset("/Engine/EngineResources/WhiteSquareTexture"))
            a.set_actor_hidden_in_game(True)
            _log("minimap ready", png, n, "px")
        except FileNotFoundError:
            _log("minimap: no picture in", MINIMAP_DIR, "(python sim/minimap_build.py)")
        except Exception as e:
            _log("minimap init", repr(e))

    @staticmethod
    def _merc(lat, lon):
        sl = math.sin(math.radians(max(-85.0, min(85.0, lat))))
        return (lon + 180.0) / 360.0, 0.5 - math.log((1 + sl) / (1 - sl)) / (4 * math.pi)

    def minimap_uv(self, lat, lon):
        """aircraft position on the minimap picture, 0..1 (x right, y down); outside the picture < 0 or > 1."""
        x0, y0, x1, y1 = self.mm["merc"]
        mx, my = self._merc(lat, lon)
        return (mx - x0) / (x1 - x0), (my - y0) / (y1 - y0)

    def _minimap_place(self):
        mm = self.mm
        try:
            vp = unreal.WidgetLayoutLibrary.get_viewport_size(self.world)
            aspect = vp.x / vp.y if vp.y > 0 else 16 / 9
        except Exception:
            aspect = 16 / 9
        fov = self.fov_set or VIEW_FOV
        key = (round(fov, 2), round(aspect, 3), self.hmd)
        if key == mm["key"]:
            return
        mm["key"] = key
        mm["view"] = key
        D = VW_ATTRIB_D
        if self.hmd:                                             # VR: lower right, fixed size (head-locked, like the source note)
            w = MINIMAP_VR_CM
            pos = unreal.Vector(D, D * math.tan(math.radians(MINIMAP_VR_DIR[0])), D * math.tan(math.radians(MINIMAP_VR_DIR[1])))
        else:                                                    # monitor: top right corner, a margin from the edges
            hw = D * math.tan(math.radians(fov / 2))
            hh = hw / aspect
            w = min(2 * hw * MINIMAP_W, 2 * hh * 0.45)
            m = 0.02 * 2 * hw
            pos = unreal.Vector(D, hw - m - w / 2, hh - m - w / 2)
        r = unreal.MathLibrary.make_rot_from_zx(unreal.Vector(-1, 0, 0), unreal.Vector(0, 1, 0))
        a = mm["actor"]
        a.set_actor_relative_location(pos, False, True)
        a.set_actor_relative_rotation(r, False, True)
        a.set_actor_relative_scale3d(unreal.Vector(w / 100.0, w / 100.0, 1.0))

    def _minimap(self, now):
        mm = getattr(self, "mm", None)
        if mm is None or mm.get("world") != self.world:
            if self.cesium_mode is None:                 # ground not set up yet
                return
            self._minimap_init()
            mm = self.mm
        if not mm["ok"]:
            return
        if self.kb.focused() and self.kb.pressed("J"):
            self.minimap_on = not getattr(self, "minimap_on", True)
        s = self.s
        show = False
        u = v = 0.0
        if s is not None and self.cesium_mode == "vworld" and getattr(self, "minimap_on", True) and "lat" in s:
            u, v = self.minimap_uv(s["lat"], s["lon"])
            show = -MINIMAP_NEAR <= u <= 1 + MINIMAP_NEAR and -MINIMAP_NEAR <= v <= 1 + MINIMAP_NEAR
        if show != mm["shown"]:
            mm["shown"] = show
            mm["actor"].set_actor_hidden_in_game(not show)
        if not show:
            return
        self._minimap_place()
        if now - mm["t"] < 1.0 / MINIMAP_HZ:
            return
        mm["t"] = now
        try:
            RL, V2 = unreal.RenderingLibrary, unreal.Vector2D
            n = mm["n"]
            c, _size, ctx = RL.begin_draw_canvas_to_render_target(self.world, mm["rt"])
            try:
                c.draw_texture(mm["tex"], V2(0, 0), V2(n, n), V2(0, 0), V2(1, 1), unreal.LinearColor(1, 1, 1, 1),
                               unreal.BlendMode.BLEND_OPAQUE, 0.0, V2(0, 0))
                k = n / 1024.0
                x, y = max(0.0, min(1.0, u)) * n, max(0.0, min(1.0, v)) * n     # outside the picture: pinned to the edge
                hd = math.radians(s.get("psi", 0.0))                     # heading, true: 0 = north = picture up
                fwd = (math.sin(hd), -math.cos(hd))
                rgt = (math.cos(hd), math.sin(hd))
                L, B, W = 34 * k, 16 * k, 12 * k
                tip = (x + fwd[0] * L, y + fwd[1] * L)
                tail = (x - fwd[0] * L * 0.45, y - fwd[1] * L * 0.45)
                wl = (tail[0] - rgt[0] * B, tail[1] - rgt[1] * B)
                wr = (tail[0] + rgt[0] * B, tail[1] + rgt[1] * B)
                black, yel, red = unreal.LinearColor(0, 0, 0, 1), unreal.LinearColor(1.0, 0.85, 0.1, 1), unreal.LinearColor(1.0, 0.15, 0.1, 1)
                for col, th in ((black, 9 * k), (red, 4.5 * k)):         # heading line ahead of the arrow
                    c.draw_line(V2(*tip), V2(x + fwd[0] * L * 2.4, y + fwd[1] * L * 2.4), th, col)
                for col, th in ((black, 12 * k), (yel, 6 * k)):          # arrow: outlined chevron
                    for a_, b_ in ((tip, wl), (tip, wr), (wl, tail), (wr, tail)):
                        c.draw_line(V2(*a_), V2(*b_), th, col)
                c.draw_texture(mm["white"], V2(x - W / 2, y - W / 2), V2(W, W), V2(0, 0), V2(1, 1), red,
                               unreal.BlendMode.BLEND_OPAQUE, 0.0, V2(0, 0))
                fr = unreal.LinearColor(0.85, 0.9, 1.0, 1)              # frame
                for a_, b_ in (((0, 0), (n, 0)), ((n, 0), (n, n)), ((n, n), (0, n)), ((0, n), (0, 0))):
                    c.draw_line(V2(*a_), V2(*b_), 4 * k, fr)
            finally:
                RL.end_draw_canvas_to_render_target(self.world, ctx)
            mm["pos"] = (round(u, 4), round(v, 4), round(s.get("psi", 0.0), 1))
        except Exception as e:
            if now - self.last_log > 2:
                self.last_log = now
                _log("minimap draw", repr(e))

    def _vworld_poll(self, now):
        """proxy status every 5 s (budget / stopped) -> HUD note; the proxy never sends the key."""
        if self.cesium_mode != "vworld" or now - getattr(self, "vw_poll_t", 0.0) < 5.0:
            return
        self.vw_poll_t = now
        st = self.vworld_status(0.15)
        self.vw_stat = st
        if st is None:
            self.vw_note = "V-WORLD PROXY STOPPED - CACHED TILES ONLY"
        elif not st.get("online"):
            self.vw_note = "V-WORLD OFFLINE (%s) - CACHE / LOW-RES" % str(st.get("why", "")).upper()[:40]
        else:
            self.vw_note = None
        self._attrib_place()

    def tick(self, dt):
        try:
            now = time.perf_counter()
            self._recv()
            world = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_game_world()
            if world is None:
                self.world = self.aircraft = self.camera = None
                return
            if world != self.world or self.aircraft is None:
                self._bind_world(world)
                if self.aircraft is None:
                    return
            self._window_mode(now)
            self._check_hmd(now)
            self._startup(now, dt)
            self._keyboard(dt)
            if self.s is not None:
                self._apt_sync()
                self._place(dt, now)
                self._controls(dt)
            self._trace(now)
            self._fog_follow(now)
            self._vworld_poll(now)
            self._minimap(now)
            self._overlay(now)
            self._set_view_target()
            self.frames += 1
            if now - self.last_log > 5.0 and self.s is not None:
                fps = self.frames / (now - self.last_log) if self.last_log else 0.0
                self.frames = 0
                self.last_log = now
                l = self.aircraft.get_actor_location()
                _log("t=%.1f rx=%d alt=%.0fm phi=%.1f th=%.1f psi=%.1f -> actor (%.0f, %.0f, %.0f) cm view=%s hmd=%s fps=%.0f" % (
                    self.s["t"], self.rx_n, self.s["alt_m"], self.s["phi"], self.s["theta"], self.s["psi"], l.x, l.y, l.z,
                    self.view, self.hmd, fps))
        except Exception as e:
            now = time.perf_counter()
            if now - self.last_log > 2.0:
                self.last_log = now
                _log("tick error:", repr(e))

    def status(self):
        s = self.s or {}
        return dict(bound=self.bound, rx=self.rx_n, age=round(time.perf_counter() - self.rx_t, 2), view=self.view, hmd=self.hmd,
                    preset=self.preset, world=self.world.get_name() if self.world else None, t=s.get("t"), alt_m=s.get("alt_m"),
                    interp_n=len(self.interp.buf), cesium=self.cesium_mode, hud_frames=self.hud_n, hud_ms=round(self.hud_ms, 2),
                    radar_m=self.radar_m, crashed=self.crashed, panel_on=self.panel_on,
                    startup={k: v for k, v in self.start.items() if k != "dts"},
                    minimap={k: (getattr(self, "mm", None) or {}).get(k) for k in ("ok", "shown", "pos")})


def recenter():
    try:
        unreal.HeadMountedDisplayFunctionLibrary.reset_orientation_and_position(0.0, unreal.OrientPositionSelector.ORIENTATION_AND_POSITION)
        _log("VR recenter")
    except Exception as e:
        _log("recenter failed", e)


def maximize_pie_window():
    """Maximize the Play-in-new-window (PIE) window of this editor process (Windows). Returns True when found.
    The project defaults Play to 'New Editor Window' (Config/DefaultEditorPerProjectUserSettings.ini); fallback when the
    true full screen (pie_fullscreen.py, F11 / Alt+Enter) did not take."""
    if os.name != "nt":
        return False
    import ctypes.wintypes as W
    u32 = ctypes.windll.user32
    pid = os.getpid()
    found = []
    CB = ctypes.WINFUNCTYPE(ctypes.c_bool, W.HWND, W.LPARAM)

    def cb(h, l):
        p = ctypes.c_ulong()
        u32.GetWindowThreadProcessId(h, ctypes.byref(p))
        if p.value == pid and u32.IsWindowVisible(h):
            n = u32.GetWindowTextLengthW(h)
            buf = ctypes.create_unicode_buffer(n + 1)
            u32.GetWindowTextW(h, buf, n + 1)
            t = buf.value
            if "[NetMode:" in t:                     # "GyroSim 프리뷰 [NetMode: Standalone 0] ..." (any editor language)
                found.append(h)
        return True
    u32.EnumWindows(CB(cb), 0)
    for h in found:
        u32.ShowWindow(h, 3)            # SW_MAXIMIZE
    return bool(found)


def start():
    import builtins
    old = getattr(builtins, "_gyrosim_client", None)
    if old is not None:
        stop()
    try:      # keep PIE running at full rate when the browser / another window has focus ("Use Less CPU when in Background")
        cdo = unreal.find_object(None, "/Script/UnrealEd.Default__EditorPerformanceSettings")
        cdo.set_editor_property("bThrottleCPUWhenNotForeground", False)
        _log("background throttling off:", not cdo.get_editor_property("bThrottleCPUWhenNotForeground"))
    except Exception as e:
        _log("could not disable background throttling:", e)
    c = SimClient()
    c.handle = unreal.register_slate_post_tick_callback(c.tick)
    builtins._gyrosim_client = c
    _log("started (UDP in %s, cmd out %s)" % (STATE_ADDR, CMD_ADDR))
    return c


def stop():
    import builtins
    c = getattr(builtins, "_gyrosim_client", None)
    if c is None:
        return
    if c.handle is not None:
        unreal.unregister_slate_post_tick_callback(c.handle)
    c.sock.close()
    builtins._gyrosim_client = None
    _log("stopped")


def client():
    import builtins
    return getattr(builtins, "_gyrosim_client", None)


def status():
    c = client()
    return c.status() if c else "not running"
