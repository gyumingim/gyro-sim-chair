"""GyroSim visual client - runs inside the Unreal editor (Python), drives Play-In-Editor (monitor or VR Preview) from sim/server.py.

  state in : UDP JSON 127.0.0.1:4220, 60 Hz (lat/lon/alt_m, phi/theta/psi deg = NED Euler, controls, tutorial ...)
  input out: UDP JSON 127.0.0.1:4221 ({"ctrl": {...}} / {"cmd": "reset"|"pause"|"tut"}) - keyboard, only while the
             editor window has focus (Windows GetAsyncKeyState), so the browser page / joystick still work otherwise.

World frame: X = north, Y = east, Z = up, cm; origin = (lat0, lon0) from the packet, sea level = Z 0.
NED Euler -> UE Rotator: roll = phi, pitch = theta, yaw = psi (UE yaw turns X toward Y = north toward east).

Smooth motion: packets carry the sim time t. The client keeps the last packets, maps sim time to local time
(perf_counter) and renders ~1 packet interval in the past, interpolating position (linear) and attitude (quaternion
slerp); at most 50 ms extrapolation when a packet is late.

VR: VR Preview (Play dropdown) uses the HMD through OpenXR. The camera actor is put at the cockpit eye point with the
aircraft attitude; the HMD pose is added by the camera component (lock to HMD), so head look works on top. HUD texts
and the tutorial panel are world-space actors attached to the camera actor (visible in VR). F3 = recenter.

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
INTERP_DELAY = 1 / 60 + 0.004      # s behind the newest packet
MAX_EXTRAP = 0.05

A_WGS, E2 = 6378137.0, 6.69437999014e-3

VK = dict(LEFT=0x25, UP=0x26, RIGHT=0x27, DOWN=0x28, A=0x41, D=0x44, W=0x57, S=0x53, B=0x42, G=0x47,
          R=0x52, T=0x54, V=0x56, P=0x50, H=0x48, C=0x43, Q=0x51, E=0x45, N=0x4E, M=0x4D,
          F1=0x70, F2=0x71, F3=0x72, F9=0x78, **{"K%d" % i: 0x30 + i for i in range(1, 7)})

# keyboard "stick" feel: rate toward the held direction (per s), spring back to centre, slower start (ease-in)
RAMP = dict(ail=1.8, elev=1.3, rud=1.6)
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

    def push(self, s, now, loc):
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
        self.buf.append((t, (loc.x, loc.y, loc.z), e2q(s["phi"], s["theta"], s["psi"])))
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
        for tag in ("HUD_SPD", "HUD_ALT", "HUD_HDG", "HUD_MID", "HUD_STAT"):
            a = self._find(tag)
            if a:
                self.texts[tag] = a.text_render
        self.panel = self._find("TutorPanel")
        self.panel_mid = None
        self.panel_shown = None
        if self.panel:
            try:
                self.panel_mid = self.panel.static_mesh_component.create_and_set_material_instance_dynamic(0)
            except Exception as e:
                _log("panel material", e)
        self.txt_cache.clear()
        self.tut_ver = -1
        self.gear_shown = None
        self.interp.reset()
        self.preset = None
        _log("game world", world.get_name(), "aircraft", bool(self.aircraft), "camera", bool(self.camera),
             "pivots", sorted(self.pivots), "texts", len(self.texts), "panel", bool(self.panel_mid))
        self._set_view_target()

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
            loc, _ = self.to_world(s)
            self.interp.push(s, self.rx_t, loc)

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
            self.hud = not self.hud
            self.txt_cache.clear()
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
        if "StickPivot" in P:
            P["StickPivot"][0].set_actor_relative_rotation(unreal.Rotator(roll=18.0 * d["ail"], pitch=-14.0 * d["elev"], yaw=0.0), False, True)
        if "ThrottlePivot" in P:
            P["ThrottlePivot"][0].set_actor_relative_rotation(unreal.Rotator(roll=0.0, pitch=25.0 - 50.0 * d["thr"], yaw=0.0), False, True)
        for tag, sign, bk in (("PedalL", -1.0, "brk_l"), ("PedalR", 1.0, "brk_r")):
            if tag in P:
                a, base = P[tag]
                a.root_component.set_relative_location_and_rotation(base + unreal.Vector(6.0 * sign * d["rud"], 0, 0),
                                                                    unreal.Rotator(roll=0.0, pitch=-18.0 * d[bk], yaw=0.0), False, True)
        g = s.get("gear", 1.0) > 0.05
        if g != self.gear_shown:
            self.gear_shown = g
            for a in self.gear_parts:
                a.set_actor_hidden_in_game(not g)

    def _set_text(self, tag, txt):
        if self.txt_cache.get(tag) != txt and tag in self.texts:
            self.txt_cache[tag] = txt
            self.texts[tag].set_text(txt)

    def _overlay(self, now):
        if now - self.txt_t < 1 / 15:
            return
        self.txt_t = now
        s = self.s
        age = now - self.rx_t
        tut = (s or {}).get("tut") or {}
        if s is None or age > 1.0:
            for t in ("HUD_SPD", "HUD_ALT", "HUD_HDG", "HUD_MID"):
                self._set_text(t, "")
            self._set_text("HUD_STAT", "NO DATA - start  python sim/server.py  (UDP 4220)")
        elif not self.hud:
            for t in self.texts:
                self._set_text(t, "")
        else:
            self._set_text("HUD_SPD", "%3.0f KT<br>M %.2f<br>G %.1f<br>AOA %.1f" % (s["kts"], s["mach"], s["nz"], s["alpha"]))
            self._set_text("HUD_ALT", "%5.0f FT<br>%+5.0f FPM<br>R %5.0f" % (s["alt_m"] / 0.3048, s["vs_fpm"], s["agl_m"] / 0.3048))
            self._set_text("HUD_HDG", "%03.0f" % (s["psi"] % 360))
            self._set_text("HUD_MID", "BANK %+3.0f   PITCH %+3.0f" % (s["phi"], s["theta"]))
            stat = "THR %3.0f%%  GEAR %s  BRK %s  [%s]%s" % (s["thr"] * 100, "DN" if s["gear"] > 0.5 else ("UP" if s["gear"] < 0.05 else "--"),
                                                          "ON" if s.get("brk", 0) > 0.3 else "--", s.get("src", "?"), "  PAUSED" if s.get("paused") else "")
            if tut.get("on") and not tut.get("menu"):
                n = int(round(tut.get("prog", 0) * 10))
                stat += "<br>LESSON %d  STEP %d/%d  [%s%s]%s" % (tut.get("lesson", 0), tut.get("step", 0), tut.get("n", 0), "#" * n, "-" * (10 - n),
                                                              ("  SCORE %d" % tut["score"]) if tut.get("score") is not None else "")
            else:
                stat += "<br>F1 = LESSONS"
            self._set_text("HUD_STAT", stat)
        # tutorial panel (Korean text rendered to PNG by sim/tutorial.py)
        show = bool(tut.get("on")) and bool(tut.get("img"))
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
            self._check_hmd(now)
            self._keyboard(dt)
            if self.s is not None:
                self._place(dt, now)
                self._controls(dt)
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
                    interp_n=len(self.interp.buf))


def recenter():
    try:
        unreal.HeadMountedDisplayFunctionLibrary.reset_orientation_and_position(0.0, unreal.OrientPositionSelector.ORIENTATION_AND_POSITION)
        _log("VR recenter")
    except Exception as e:
        _log("recenter failed", e)


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
