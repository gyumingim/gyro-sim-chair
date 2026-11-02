"""GyroSim visual client - runs inside the Unreal editor (Python), drives Play-In-Editor from sim/server.py.

  state in : UDP JSON 127.0.0.1:4220, 60 Hz (lat/lon/alt_m, phi/theta/psi in deg = NED Euler, ...)
  input out: UDP JSON 127.0.0.1:4221 ({"ctrl": {...}} / {"cmd": "reset"|"pause"}) - keyboard, only while the
             editor window has focus (Windows GetAsyncKeyState), so the browser page / joystick still work otherwise.

World frame: X = north, Y = east, Z = up, cm; origin = (lat0, lon0) from the packet, sea level = Z 0.
NED Euler -> UE Rotator: roll = phi, pitch = theta, yaw = psi (UE yaw turns X toward Y = north toward east).

Started by init_unreal.py on editor start. In the editor Python console:  import sim_client; sim_client.status()
"""
import ctypes, json, math, os, socket, time
import unreal

STATE_ADDR = ("127.0.0.1", 4220)
CMD_ADDR = ("127.0.0.1", 4221)
EYE = (430.0, 0.0, 100.0)          # cockpit eye point in body axes, cm (fwd, right, up) from the aircraft reference
CHASE_BACK, CHASE_UP = 2600.0, 650.0
GEAR_BOTTOM_CM = 190.0             # model wheels are this far below the actor origin
AGL_REST_M = 1.66                  # JSBSim F-16 h-agl when standing on the runway (measured from server.py, runway start)
Z_OFFSET_CM = GEAR_BOTTOM_CM - AGL_REST_M * 100.0

A_WGS, E2 = 6378137.0, 6.69437999014e-3

VK = dict(LEFT=0x25, UP=0x26, RIGHT=0x27, DOWN=0x28, A=0x41, D=0x44, W=0x57, S=0x53, B=0x42, G=0x47,
          R=0x52, T=0x54, V=0x56, P=0x50, H=0x48)


def _log(*a):
    unreal.log("[sim_client] " + " ".join(str(x) for x in a))


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
        self.aircraft = self.camera = None
        self.canopy = []
        self.chase_yaw = None
        self.last_log = 0.0
        self.frames = 0
        self.handle = None
        self.override = None          # dict of ctrl values to force (sent even without focus), None = keyboard

    # ---------------------------------------------------------------------------------------------------------------
    def _bind_world(self, world):
        self.world = world
        acs = unreal.GameplayStatics.get_all_actors_with_tag(world, "Aircraft")
        cams = unreal.GameplayStatics.get_all_actors_with_tag(world, "SimCamera")
        self.aircraft = acs[0] if acs else None
        self.canopy = list(unreal.GameplayStatics.get_all_actors_with_tag(world, "Canopy"))
        self.camera = cams[0] if cams else None
        _log("game world", world.get_name(), "aircraft", bool(self.aircraft), "camera", bool(self.camera))
        self._set_view_target()

    def _set_view_target(self):
        pc = unreal.GameplayStatics.get_player_controller(self.world, 0)
        if pc and self.camera and pc.get_view_target() != self.camera:
            pc.set_view_target_with_blend(self.camera, 0.0)

    def _recv(self):
        if not self.bound:
            return
        while True:
            try:
                data = self.sock.recv(65536)
            except (BlockingIOError, OSError):
                break
            try:
                self.s = json.loads(data)
                self.rx_n += 1
                self.rx_t = time.monotonic()
            except ValueError:
                pass

    def _send(self, m):
        try:
            self.out.sendto(json.dumps(m).encode(), CMD_ADDR)
        except OSError:
            pass

    # ---------------------------------------------------------------------------------------------------------------
    @staticmethod
    def to_world(s):
        lat0 = math.radians(s["lat0"])
        sl = math.sin(lat0)
        w = 1 - E2 * sl * sl
        m_r = A_WGS * (1 - E2) / w ** 1.5                     # meridian radius
        n_r = A_WGS / math.sqrt(w)                            # prime vertical radius
        north = math.radians(s["lat"] - s["lat0"]) * m_r
        east = math.radians(s["lon"] - s["lon0"]) * n_r * math.cos(lat0)
        loc = unreal.Vector(north * 100.0, east * 100.0, s["alt_m"] * 100.0 + Z_OFFSET_CM)
        rot = unreal.Rotator(roll=s["phi"], pitch=s["theta"], yaw=s["psi"])
        return loc, rot

    def _sync_reset(self):
        """Follow the server after a reset (or on first packet): take its throttle / gear so we don't fight it."""
        s, c = self.s, self.ctrl
        if not s or s.get("rid") == self.rid:
            return
        first = self.rid is None
        self.rid = s.get("rid")
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

        def axis(pos, neg, v, rate=2.0):
            a, b = kb.down(pos), kb.down(neg)
            v += ((1 if a else 0) - (1 if b else 0)) * rate * dt
            if not a and not b:
                v -= v * min(1.0, 4 * dt)
            return max(-1.0, min(1.0, v))

        c["ail"] = axis("RIGHT", "LEFT", c["ail"])
        c["elev"] = axis("UP", "DOWN", c["elev"])            # JSBSim + elevator = nose down: up arrow = push, down = pull
        c["rud"] = axis("D", "A", c["rud"])
        c["thr"] = max(0.0, min(1.0, c["thr"] + ((1 if kb.down("W") else 0) - (1 if kb.down("S") else 0)) * 0.4 * dt))
        c["brk_l"] = c["brk_r"] = 1.0 if kb.down("B") else 0.0
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
            self.hud = not self.hud
        self._send({"ctrl": c, "rid": self.rid})

    def _place(self, dt):
        s = self.s
        loc, rot = self.to_world(s)
        self.aircraft.set_actor_location_and_rotation(loc, rot, False, True)
        fwd, right, up = rot.get_forward_vector(), rot.get_right_vector(), rot.get_up_vector()
        for a in self.canopy:
            a.set_actor_hidden_in_game(self.view == "cockpit")
        if self.view == "cockpit":
            eye = loc + fwd * EYE[0] + right * EYE[1] + up * EYE[2]
            self.camera.set_actor_location_and_rotation(eye, rot, False, True)
        else:
            if self.chase_yaw is None:
                self.chase_yaw = s["psi"]
            d = (s["psi"] - self.chase_yaw + 180) % 360 - 180
            self.chase_yaw += d * min(1.0, 3.0 * dt)
            yaw = math.radians(self.chase_yaw)
            back = unreal.Vector(math.cos(yaw), math.sin(yaw), 0.0)
            eye = loc - back * CHASE_BACK + unreal.Vector(0, 0, CHASE_UP)
            look = unreal.MathLibrary.find_look_at_rotation(eye, loc + unreal.Vector(0, 0, 150))
            self.camera.set_actor_location_and_rotation(eye, look, False, True)

    def _hud(self):
        s = self.s
        age = time.monotonic() - self.rx_t
        if s is None or age > 1.0:
            txt = "GyroSim: no data from sim/server.py on UDP 4220 - start  python sim/server.py"
        else:
            txt = ("{view}  IAS {kts:5.0f} kt  ALT {alt:6.0f} ft  AGL {agl:5.0f} ft  VS {vs:+6.0f} fpm  HDG {hdg:03.0f}  "
                   "roll {phi:+5.1f}  pitch {th:+5.1f}  AoA {a:4.1f}  G {nz:4.1f}  THR {thr:3.0f}%  GEAR {gear}  "
                   "chair r{cr:+5.1f} p{cp:+5.1f}  [{src}]{paused}").format(
                view=self.view.upper(), kts=s["kts"], alt=s["alt_m"] / 0.3048, agl=s["agl_m"] / 0.3048, vs=s["vs_fpm"],
                hdg=s["psi"] % 360, phi=s["phi"], th=s["theta"], a=s["alpha"], nz=s["nz"], thr=s["thr"] * 100,
                gear="DN" if s["gear"] > 0.5 else "UP", cr=s["chair_roll"], cp=s["chair_pitch"], src=s.get("src", "?"),
                paused="  PAUSED" if s.get("paused") else "")
        try:
            unreal.SystemLibrary.print_string(self.world, txt, True, False, unreal.LinearColor(0.25, 1.0, 0.45, 1.0), 0.0)
        except Exception:
            pass

    def tick(self, dt):
        try:
            self._recv()
            world = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_game_world()
            if world is None:
                self.world = self.aircraft = self.camera = None
                return
            if world != self.world or self.aircraft is None:
                self._bind_world(world)
                if self.aircraft is None:
                    return
            self._keyboard(dt)
            if self.s is not None:
                self._place(dt)
            self._set_view_target()
            if self.hud:
                self._hud()
            self.frames += 1
            now = time.monotonic()
            if now - self.last_log > 5.0 and self.s is not None:
                fps = self.frames / (now - self.last_log) if self.last_log else 0.0
                self.frames = 0
                self.last_log = now
                l = self.aircraft.get_actor_location()
                _log("t=%.1f rx=%d alt=%.0fm phi=%.1f th=%.1f psi=%.1f -> actor (%.0f, %.0f, %.0f) cm view=%s fps=%.0f" % (
                    self.s["t"], self.rx_n, self.s["alt_m"], self.s["phi"], self.s["theta"], self.s["psi"], l.x, l.y, l.z, self.view, fps))
        except Exception as e:
            now = time.monotonic()
            if now - self.last_log > 2.0:
                self.last_log = now
                _log("tick error:", repr(e))

    def status(self):
        s = self.s or {}
        return dict(bound=self.bound, rx=self.rx_n, age=round(time.monotonic() - self.rx_t, 2), view=self.view,
                    world=self.world.get_name() if self.world else None, t=s.get("t"), alt_m=s.get("alt_m"))


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
