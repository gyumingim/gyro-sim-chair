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

STATE_ADDR = ("127.0.0.1", 4220)
CMD_ADDR = ("127.0.0.1", 4221)
EYE = (430.0, 0.0, 100.0)          # cockpit eye point in body axes, cm (fwd, right, up) from the aircraft reference
CHASE_BACK, CHASE_UP = 2600.0, 650.0
GEAR_BOTTOM_CM = 177.5             # F-16 model tire bottom below the actor origin (ThirdParty/f16_obj/manifest.json)
AGL_REST_M = 1.66                  # JSBSim F-16 h-agl when standing on the runway (measured from server.py, runway start)
Z_OFFSET_CM = GEAR_BOTTOM_CM - AGL_REST_M * 100.0
INTERP_DELAY = 1 / 60 + 0.004      # s behind the newest packet
MAX_EXTRAP = 0.05

GROUND_MODES = ("grid", "fields", "photo", "terrain", "photoreal")
STARTUP_MODE = "air"               # Play always starts here (fresh run, not wherever the server drifted to)
STARTUP_MIN, STARTUP_MAX, STARTUP_FPS = 1.5, 15.0, 90.0
TOKEN_FILE = os.path.join(unreal.Paths.convert_relative_path_to_full(unreal.Paths.project_config_dir()), "cesium_token.txt")
EOX_URL = "https://tiles.maps.eox.at/wmts/1.0.0/s2cloudless-2024_3857/default/g/{z}/{reverseY}/{x}.jpg"
ION_TERRAIN, ION_BING, ION_PHOTOREAL = 1, 2, 2275207
RUNWAYS = ((36.7078737, 127.4874876, 36.7229393, 127.5117932), (36.7100557, 127.4868159, 36.7251153, 127.5111227))   # RKTU (airfield.py)
DISP_HZ, DISP_ORDER = 30.0, ("MFD_C", "MFD_L", "MFD_C", "MFD_R")   # one display per call: training 15 Hz, flight / chair 7.5 Hz
HUD_HZ = 30.0                      # HUD text / FPM / tapes redraw rate (Python canvas ~1 ms); the pitch ladder moves every frame (material)
MFD_HZ = 5.0
KEY_PNG = os.path.normpath(os.path.join(unreal.Paths.convert_relative_path_to_full(unreal.Paths.project_dir()), "..", "..", "sim", "key_panel.png"))

VK = dict(LEFT=0x25, UP=0x26, RIGHT=0x27, DOWN=0x28, A=0x41, D=0x44, W=0x57, S=0x53, B=0x42, G=0x47,
          R=0x52, T=0x54, V=0x56, P=0x50, H=0x48, U=0x55, C=0x43, Q=0x51, E=0x45, N=0x4E, M=0x4D,
          LBUTTON=0x01, K=0x4B, F1=0x70, F2=0x71, F3=0x72, F9=0x78, RETURN=0x0D, SPACE=0x20, BACK=0x08, Z=0x5A, I=0x49, Y=0x59, L=0x4C,
          **{"K%d" % i: 0x30 + i for i in range(0, 10)})

# keyboard "stick" feel: rate toward the held direction (per s), spring back to centre, slower start (ease-in)
RAMP = dict(ail=1.8, elev=1.3, rud=1.6)
# our cockpit (Scripts/cockpit/layout.py) = the physical rig: centre stick +-20 deg both axes (hardware/stick TRAVEL),
# throttle +-30 deg (0 = aft, 1 = forward, hardware/throttle SWING), rudder bar +-20 deg = pedals +-4.6 cm fore/aft,
# toe brakes 15 deg, gear handle +-16 deg (down = handle down)
STICK_ROLL, STICK_PITCH, THR_SWING, PEDAL_CM, TOE_DEG, GEAR_HANDLE_DEG = 20.0, 20.0, 30.0, 4.62, 15.0, 16.0
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


def apply_preset(name, world=None):
    p = PRESETS.get(name)
    if not p:
        return False
    if world is None:
        world = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_game_world() or \
            unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_editor_world()
    for k, v in p.items():
        unreal.SystemLibrary.execute_console_command(world, "%s %s" % (k, v))
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
        self.max_tries = 40               # maximize the new PIE window over the next frames
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
        mode = kws[-1] if kws else ("terrain" if token else "grid")
        if mode in ("terrain", "photoreal") and not token:
            mode = "grid"
        return token, mode

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
        if mode == "photo":
            h = self.s.get("field_m", 58.2) if self.s else 58.2
            ts.set_actor_location_and_rotation(unreal.Vector(0, 0, h * 100.0 - 30.0), unreal.Rotator(roll=0, pitch=0, yaw=90.0), False, True)
            ts.set_editor_property("tileset_source", unreal.TilesetSource.FROM_ELLIPSOID)
            if eox:
                eox.add_to_tileset()
        else:
            ts.set_actor_location_and_rotation(unreal.Vector(0, 0, 0), unreal.Rotator(roll=0, pitch=0, yaw=90.0), False, True)
            ts.set_editor_property("ion_access_token", token)
            ts.set_editor_property("ion_asset_id", ION_PHOTOREAL if mode == "photoreal" else ION_TERRAIN)
            ts.set_editor_property("tileset_source", unreal.TilesetSource.FROM_CESIUM_ION)
            if ion and mode == "terrain":
                ion.set_editor_property("ion_access_token", token)
                ion.set_editor_property("ion_asset_id", ION_BING)
                ion.add_to_tileset()
        ts.refresh_tileset()

    def _setup_cesium(self):
        gr, ts = self._find("CesiumGeoreference"), self._find("CesiumGround")
        self.georef, self.tileset, self.grid = gr, ts, self._find("GridGround")
        token, mode = self.read_ground_cfg()
        if not ts or not hasattr(unreal, "Cesium3DTileset"):
            mode = (mode if mode == "fields" else "grid") if self.grid else "none"
        try:
            self._ground(mode, token)
            self.cesium_mode = mode
        except Exception as e:
            _log("ground setup failed", repr(e))
            self.cesium_mode = "error"
        _log("ground mode", self.cesium_mode, "config", TOKEN_FILE, "token" if token else "no token")

    def _cesium_fallback(self, why):
        """terrain mode failed -> grid ground (tileset off)."""
        _log("cesium fallback to grid:", why)
        try:
            self._ground("grid")
        except Exception as e:
            _log("fallback failed", repr(e))
        self.cesium_mode = "grid"
        self.cesium_failed = why
        self.t_bind = time.perf_counter()          # show the HUD note again

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
        x, y, z = f.world(s["lat"], s["lon"], s["alt_m"] + n)
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
            self.view = "chase" if self.view == "cockpit" else "cockpit"
            self.chase_yaw = None
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
        if self.view == "cockpit":
            eye = loc + fwd * EYE[0] + right * EYE[1] + up * EYE[2]
            self.camera.set_actor_location_and_rotation(eye, rot, False, False)
        else:
            if self.chase_yaw is None:
                self.chase_yaw = rot.yaw
            d = (rot.yaw - self.chase_yaw + 180) % 360 - 180
            self.chase_yaw += d * min(1.0, 3.0 * dt)
            yaw = math.radians(self.chase_yaw)
            back = unreal.Vector(math.cos(yaw), math.sin(yaw), 0.0)
            eye = loc - back * CHASE_BACK + unreal.Vector(0, 0, CHASE_UP)
            look = unreal.MathLibrary.find_look_at_rotation(eye, loc + unreal.Vector(0, 0, 150))
            if self.hmd:                                            # VR: no camera pitch/roll from us (comfort)
                look = unreal.Rotator(roll=0.0, pitch=0.0, yaw=look.yaw)
            self.camera.set_actor_location_and_rotation(eye, look, False, False)
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
        if s.get("rid") != self.gmax_rid:
            self.gmax_rid, self.gmax = s.get("rid"), 1.0
        if not s.get("paused"):
            self.gmax = max(self.gmax, s.get("nz", 1.0))
        self.warnings = self._warnings()
        self._lights()

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

    def _trace(self, now):
        """Height of the wheels above whatever is under the aircraft (Cesium terrain tiles have collision), 10 Hz.
        JSBSim's ground is flat at the field elevation, so with real terrain this is the only hill check: below the
        terrain while JSBSim still flies = terrain collision -> pause."""
        s = self.s
        if not s or not self.last_pose or now - self.trace_t < 0.1:
            return
        self.trace_t = now
        if self.cesium_mode not in ("terrain", "photoreal"):
            self.radar_m = s.get("agl_m")
            return
        loc = self.last_pose[0]
        start, end = loc + unreal.Vector(0, 0, 200000.0), loc - unreal.Vector(0, 0, 3000000.0)
        try:
            r = unreal.SystemLibrary.line_trace_single(self.world, start, end, unreal.TraceTypeQuery.TRACE_TYPE_QUERY1, False,
                                                       self.trace_ignore, unreal.DrawDebugTrace.NONE, True)
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
        if (not self.crashed and self.radar_m is not None and self.radar_m < -1.0 and not s.get("wow") and s.get("agl_m", 0) > 15
                and not s.get("paused")):
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
            ex["note"] = "CESIUM TERRAIN FAILED (TOKEN?) - GRID GROUND"
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
            if getattr(self, "max_tries", 0) > 0 and not self.hmd:
                self.max_tries -= 1
                if maximize_pie_window():
                    self.max_tries = 0
                    _log("PIE window maximized")
            self._check_hmd(now)
            self._startup(now, dt)
            self._keyboard(dt)
            if self.s is not None:
                self._place(dt, now)
                self._controls(dt)
            self._trace(now)
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
                    startup={k: v for k, v in self.start.items() if k != "dts"})


def recenter():
    try:
        unreal.HeadMountedDisplayFunctionLibrary.reset_orientation_and_position(0.0, unreal.OrientPositionSelector.ORIENTATION_AND_POSITION)
        _log("VR recenter")
    except Exception as e:
        _log("recenter failed", e)


def maximize_pie_window():
    """Maximize the Play-in-new-window (PIE) window of this editor process (Windows). Returns True when found.
    The project defaults Play to 'New Editor Window' (Config/DefaultEditorPerProjectUserSettings.ini); F11 = fullscreen."""
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
