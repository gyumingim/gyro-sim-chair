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
import geo, hud
importlib.reload(geo); importlib.reload(hud)

STATE_ADDR = ("127.0.0.1", 4220)
CMD_ADDR = ("127.0.0.1", 4221)
EYE = (430.0, 0.0, 100.0)          # cockpit eye point in body axes, cm (fwd, right, up) from the aircraft reference
CHASE_BACK, CHASE_UP = 2600.0, 650.0
GEAR_BOTTOM_CM = 177.5             # F-16 model tire bottom below the actor origin (ThirdParty/f16_obj/manifest.json)
AGL_REST_M = 1.66                  # JSBSim F-16 h-agl when standing on the runway (measured from server.py, runway start)
Z_OFFSET_CM = GEAR_BOTTOM_CM - AGL_REST_M * 100.0
INTERP_DELAY = 1 / 60 + 0.004      # s behind the newest packet
MAX_EXTRAP = 0.05

TOKEN_FILE = os.path.join(unreal.Paths.convert_relative_path_to_full(unreal.Paths.project_config_dir()), "cesium_token.txt")
EOX_URL = "https://tiles.maps.eox.at/wmts/1.0.0/s2cloudless-2024_3857/default/g/{z}/{reverseY}/{x}.jpg"
ION_TERRAIN, ION_BING, ION_PHOTOREAL = 1, 2, 2275207
RUNWAYS = ((36.7078737, 127.4874876, 36.7229393, 127.5117932), (36.7100557, 127.4868159, 36.7251153, 127.5111227))   # RKTU (airfield.py)
HUD_HZ = 30.0                      # HUD text / FPM / tapes redraw rate (Python canvas ~1 ms); the pitch ladder moves every frame (material)
MFD_HZ = 5.0
KEY_PNG = os.path.normpath(os.path.join(unreal.Paths.convert_relative_path_to_full(unreal.Paths.project_dir()), "..", "..", "sim", "key_panel.png"))

VK = dict(LEFT=0x25, UP=0x26, RIGHT=0x27, DOWN=0x28, A=0x41, D=0x44, W=0x57, S=0x53, B=0x42, G=0x47,
          R=0x52, T=0x54, V=0x56, P=0x50, H=0x48, U=0x55, C=0x43, Q=0x51, E=0x45, N=0x4E, M=0x4D,
          K=0x4B, F1=0x70, F2=0x71, F3=0x72, F9=0x78, **{"K%d" % i: 0x30 + i for i in range(1, 7)})

# keyboard "stick" feel: rate toward the held direction (per s), spring back to centre, slower start (ease-in)
RAMP = dict(ail=1.8, elev=1.3, rud=1.6)
STICK_ROLL, STICK_PITCH, THR_TRAVEL, PEDAL_CM, TOE_DEG = 12.0, 10.0, 80.0, 6.0, 15.0
HUD_BRIGHT, MFD_BRIGHT = 2.0, 1.2
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
        self.keys_on = True           # K: key guide panel on/off
        self.keys_shown = None
        self.keys_tex = False
        self.key_panel = None
        self.painter = None
        self.screens = {}
        self.hud_t = self.mfd_t = self.trace_t = 0.0
        self.hud_vis = None
        self.hud_n, self.hud_ms = 0, 0.0
        self.cesium_mode = None       # 'terrain' | 'photoreal' | 'flat' | 'none' | 'error'
        self.radar_m = None           # height above whatever is under the aircraft (line trace), m
        self.crashed = False
        self.t_bind = 0.0
        self.georef = self.tileset = None

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
        for tag in ("StickPivot", "ThrottlePivot", "PedalL", "PedalR"):
            a = self._find(tag)
            if a:
                b = a.root_component.get_editor_property("relative_location")
                self.pivots[tag] = (a, unreal.Vector(b.x, b.y, b.z))
        self.texts = {}
        self.panel = self._find("TutorPanel")
        self.key_panel = self._find("KeyPanel")
        self.painter = None
        self.screens = {}
        try:
            self.painter = hud.Painter(world)
            for tag, rt in (("HUD", self.painter.rt_hud), ("MFD_L", self.painter.rt_mfd[0]), ("MFD_R", self.painter.rt_mfd[1])):
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
        self._setup_cesium()
        self.panel_mid = None
        self.panel_shown = None
        if self.panel:
            try:
                self.panel_mid = self.panel.static_mesh_component.create_and_set_material_instance_dynamic(0)
            except Exception as e:
                _log("panel material", e)
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
    def read_token():
        """(token, mode) from Config/cesium_token.txt: first non-comment line = Cesium ion access token, optional
        line 'photoreal' = Google Photorealistic 3D Tiles instead of World Terrain + Bing."""
        try:
            lines = [l.strip() for l in open(TOKEN_FILE, encoding="utf-8-sig") if l.strip() and not l.strip().startswith("#")]
        except OSError:
            return None, None
        if not lines:
            return None, None
        return lines[0], ("photoreal" if any(l.lower() == "photoreal" for l in lines[1:]) else "terrain")

    def _setup_cesium(self):
        gr, ts = self._find("CesiumGeoreference"), self._find("CesiumGround")
        self.georef, self.tileset = gr, ts
        if not ts or not hasattr(unreal, "Cesium3DTileset"):
            self.cesium_mode = "none"
            return
        token, mode = self.read_token()
        ovs = {c.get_class().get_name(): c for c in ts.get_components_by_class(unreal.CesiumRasterOverlay)}
        eox, ion = ovs.get("CesiumUrlTemplateRasterOverlay"), ovs.get("CesiumIonRasterOverlay")
        try:
            if token:
                ts.set_actor_location_and_rotation(unreal.Vector(0, 0, 0), unreal.Rotator(roll=0, pitch=0, yaw=90.0), False, True)
                if eox:
                    eox.remove_from_tileset()
                ts.set_editor_property("ion_access_token", token)
                ts.set_editor_property("ion_asset_id", ION_PHOTOREAL if mode == "photoreal" else ION_TERRAIN)
                ts.set_editor_property("tileset_source", unreal.TilesetSource.FROM_CESIUM_ION)
                if ion and mode != "photoreal":
                    ion.set_editor_property("ion_access_token", token)
                    ion.set_editor_property("ion_asset_id", ION_BING)
                    ion.add_to_tileset()
                ts.refresh_tileset()
                self.cesium_mode = mode
            else:
                if ion:
                    ion.remove_from_tileset()
                self.cesium_mode = "flat" if eox else "error"
        except Exception as e:
            _log("cesium setup failed", repr(e))
            self.cesium_mode = "error"
        _log("cesium mode", self.cesium_mode, "token file", TOKEN_FILE, "found" if token else "missing", "overlays", sorted(ovs))

    def _cesium_fallback(self, why):
        """terrain mode failed -> ellipsoid at the field elevation + Sentinel-2 imagery (same as no token)."""
        ts = self.tileset
        _log("cesium fallback to flat:", why)
        try:
            ovs = {c.get_class().get_name(): c for c in ts.get_components_by_class(unreal.CesiumRasterOverlay)}
            if "CesiumIonRasterOverlay" in ovs:
                ovs["CesiumIonRasterOverlay"].remove_from_tileset()
            ts.set_editor_property("tileset_source", unreal.TilesetSource.FROM_ELLIPSOID)
            h = self.s.get("field_m", 58.2) if self.s else 58.2
            ts.set_actor_location_and_rotation(unreal.Vector(0, 0, h * 100.0 - 30.0), unreal.Rotator(roll=0, pitch=0, yaw=90.0), False, True)
            if "CesiumUrlTemplateRasterOverlay" in ovs:
                ovs["CesiumUrlTemplateRasterOverlay"].add_to_tileset()
            ts.refresh_tileset()
        except Exception as e:
            _log("fallback failed", repr(e))
        self.cesium_mode = "flat"
        self.cesium_failed = why
        self.t_bind = time.perf_counter()          # show the HUD note again

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
            self._send({"ctrl": dict(self.ctrl, **self.override), "rid": self.rid})
            return
        if not self.kb.focused():
            self.kb.prev.clear()
            return
        kb, c = self.kb, self.ctrl

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
            self._send({"cmd": "reset", "mode": "air"})
        if kb.pressed("T"):
            self._send({"cmd": "reset", "mode": "runway"})
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
            self._send({"cmd": "tut", "op": "restart"})
        for i in range(1, 7):
            if kb.pressed("K%d" % i):
                self._send({"cmd": "tut", "op": "start", "lesson": i})
        # VR
        if kb.pressed("F3"):
            recenter()
        if kb.pressed("F9"):
            unreal.SystemLibrary.execute_console_command(self.world, "stereo %s" % ("off" if self.hmd else "on"))
        self._send({"ctrl": c, "rid": self.rid})

    # ---------------------------------------------------------------------------------------------------------------
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
            for i in (0, 1):
                nv = self.look[i] + (self.look_tgt[i] - self.look[i]) * k
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
        # F-16 side stick on the right console (the real one moves only a few mm - shown +-STICK_ROLL / STICK_PITCH deg
        # so the input is visible), throttle on the left console: FlightGear throttle.xml travel 80 deg, top forward = more.
        if "StickPivot" in P:
            P["StickPivot"][0].set_actor_relative_rotation(unreal.Rotator(roll=STICK_ROLL * d["ail"], pitch=-STICK_PITCH * d["elev"], yaw=0.0), False, True)
        if "ThrottlePivot" in P:
            P["ThrottlePivot"][0].set_actor_relative_rotation(unreal.Rotator(roll=0.0, pitch=-THR_TRAVEL * d["thr"], yaw=0.0), False, True)
        for tag, sign, bk in (("PedalL", -1.0, "brk_l"), ("PedalR", 1.0, "brk_r")):
            if tag in P:
                a, base = P[tag]
                a.root_component.set_relative_location_and_rotation(base + unreal.Vector(PEDAL_CM * sign * d["rud"], 0, 0),
                                                                    unreal.Rotator(roll=0.0, pitch=-TOE_DEG * d[bk], yaw=0.0), False, True)
        g = s.get("gear", 1.0) > 0.05
        if g != self.gear_shown:
            self.gear_shown = g
            for a in self.gear_parts:
                a.set_actor_hidden_in_game(not g)

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
        if self.crashed:
            ex["warn"] = "TERRAIN  -  R / T RESTART"
        else:
            r, vs = ex["radar_m"], s.get("vs_fpm", 0) * 0.00508
            if r is not None and not s.get("wow") and vs < -1 and r / -vs < 6.0 and s.get("gear", 0) < 0.5:
                ex["warn"] = "PULL UP"
        if tut.get("on") and not tut.get("menu"):
            n = int(round(tut.get("prog", 0) * 10))
            ex["tut_line"] = "LESSON %d  STEP %d/%d  [%s%s]%s" % (tut.get("lesson", 0), tut.get("step", 0), tut.get("n", 0), "|" * n, "." * (10 - n),
                                                                ("  SCORE %d" % tut["score"]) if tut.get("score") is not None else "")
        if self.cesium_mode == "flat" and now - self.t_bind < 25:
            ex["note"] = ("CESIUM TERRAIN FAILED (TOKEN?) - FLAT GROUND" if getattr(self, "cesium_failed", None)
                          else "NO CESIUM TOKEN: FLAT GROUND + SATELLITE PHOTO  (unreal/README.md)")
        return ex

    def _mfd_extra(self):
        s = self.s
        lat, lon = s["lat"], s["lon"]
        ml, mo = 110950.0, 111320.0 * math.cos(math.radians(lat))
        rws = []
        for rw in s.get("runways") or RUNWAYS:
            rws.append(((rw[0] - lat) * ml, (rw[1] - lon) * mo, (rw[2] - lat) * ml, (rw[3] - lon) * mo))
        n, e = rws[0][0], rws[0][1]
        line = {"terrain": "MAP: CESIUM WORLD TERRAIN", "photoreal": "MAP: GOOGLE 3D TILES", "flat": "FLAT GROUND - NO CESIUM TOKEN",
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
        if P and fresh and now - self.mfd_t >= 0.5 / MFD_HZ:           # one MFD per call, alternating (spreads the cost)
            self.mfd_t = now
            try:
                self.mfd_i = 1 - getattr(self, "mfd_i", 0)
                tag = ("MFD_L", "MFD_R")[self.mfd_i]
                if tag in self.screens:
                    P.draw_mfd(self.mfd_i, s, self._mfd_extra())
            except Exception as e:
                _log("mfd draw", repr(e))
        if now - self.txt_t < 1 / 15:
            return
        self.txt_t = now
        # tutorial panel (Korean text rendered to PNG by sim/tutorial.py), H toggles
        if self.key_panel:                                      # key guide panel, K toggles
            ks = self.keys_on and self.keys_tex
            if self.keys_shown != ks:
                self.keys_shown = ks
                self.key_panel.set_actor_hidden_in_game(not ks)
        tut = (s or {}).get("tut") or {}
        show = bool(tut.get("on")) and bool(tut.get("img")) and self.panel_on
        if self.panel:
            if self.panel_shown != show:
                self.panel_shown = show
                self.panel.set_actor_hidden_in_game(not show)
            if show and tut.get("ver") != self.tut_ver and self.panel_mid:
                path = tut["img"]
                if os.path.exists(path):
                    tex = unreal.RenderingLibrary.import_file_as_texture2d(self.world, path)
                    if tex:
                        self.panel_mid.set_texture_parameter_value("Tex", tex)
                        self.tut_ver = tut.get("ver")

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
                    radar_m=self.radar_m, crashed=self.crashed, panel_on=self.panel_on)


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
