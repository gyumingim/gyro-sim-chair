"""Flight simulator server for the gyro chair: JSBSim F-16 + training (instructor, lessons, menu) + network.

JSBSim (F-16 model that ships with JSBSim) runs here at 120 Hz in real time (simcore.Sim). The training engine
(training/engine.py: start menu, trainee profiles, 11 lessons with briefing / demo autopilot / practice / solo /
debrief, instructor voice) runs every frame on the same state.
  - browser page (web/index.html): 3D view + HUD + training panel, WebSocket 8781 (state 60 Hz, controls / commands in)
  - Unreal client (unreal/GyroSim): state UDP JSON -> 127.0.0.1:4220 (60 Hz), controls / commands <- UDP 4221
  - chair: {"roll", "pitch"} UDP JSON -> 127.0.0.1:4210 (cue at the real chair's rate / accel / limits, simcore.Chair)
Joystick (pygame, controls.json): axes override browser / Unreal axes; buttons drive the menu (trigger = select / next,
second button = back / open the menu) and the stick forward / back moves the menu selection, so the whole menu works
without a keyboard or mouse (VR).
Control priority: joystick axes > Unreal UDP (if a ctrl packet arrived in the last 0.5 s) > browser WebSocket.
The demo autopilot (training) overrides the controls while a demo runs.

--free-flight (GyroSim_Busan.bat): no start menu, free flight (no instructor, no lesson, no demo autopilot); F1 still opens the
menu. Without it the trainer starts in the menu as before.
Busan start picker (start_spots.py, only with --start rkpk): with --free-flight every Play first shows the picker (the sim
stays paused until a spot is chosen; --no-picker = straight into flight at the default air start as before); the F1 menu
item '출발 위치 고르기' opens it mid-flight. Commands {"cmd": "spot", "op": ...} (start_spots.Picker.command).

Run:  python server.py [--start rkpk] [--free-flight]      then open http://127.0.0.1:8780/   (--start: airfield, default rktu = Cheongju)
"""
import asyncio, json, math, os, socket, sys, threading, time
# start airfield (sim/airfield.py AIRFIELDS): --start rkpk (Busan Gimhae 36L) | rktu (Cheongju 06R, default), or the
# GYROSIM_START environment variable. Set before anything imports airfield (simcore, terrain_dem).
if "--start" in sys.argv:
    os.environ["GYROSIM_START"] = sys.argv[sys.argv.index("--start") + 1].strip().lower()
os.environ.setdefault("SDL_JOYSTICK_ALLOW_BACKGROUND_EVENTS", "1")     # joystick keeps working while Unreal has focus
os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from websockets.asyncio.server import serve
from simcore import Sim, START, CHAIR_LIM, CHAIR_RATE
from airfield import FIELD_FT, GEOID_N, RWY, LAT0, LON0, APT, AF as FIELD, runway_lines
LAT0_LON0 = (LAT0, LON0)
APT_INFO = dict(apt=APT, apt_icao=FIELD["icao"], runways=[list(r) for r in runway_lines(APT)], tower=list(FIELD["tower"]))
print("sim: start airfield %s %s runway %s (field %.1f m, geoid N %.2f m)" % (FIELD["icao"], FIELD["name"], RWY["name"], FIELD_FT * 0.3048, GEOID_N), flush=True)
from training.engine import Trainer
from voice import Voice

HTTP_PORT, WS_PORT = 8780, 8781
CHAIR_UDP = ("127.0.0.1", 4210)
UNREAL_UDP = ("127.0.0.1", 4220)          # state out
CMD_UDP_PORT = 4221                       # control / command in
UDP_FRESH_S = 0.5
HERE = os.path.dirname(os.path.abspath(__file__))
WEB = os.path.join(HERE, "web")
OUT = os.path.join(HERE, "out")
CONTROLS = os.path.join(HERE, "controls.json")

sim = Sim("air")


def terrain_wanted():
    """real South Korea terrain under JSBSim (Copernicus DEM, terrain_dem.py): in the Unreal 'vworld' ground mode
    (Config/cesium_token.txt line 'vworld', same switch as the tile proxy), or forced with --terrain / off with --no-terrain."""
    if "--no-terrain" in sys.argv:
        return False
    if "--terrain" in sys.argv:
        return True
    try:
        import vworld_proxy
        return vworld_proxy.ground_mode_is_vworld()
    except Exception:
        return False


DEM = ROOFS = None
if terrain_wanted():
    try:
        import terrain_dem
        DEM = terrain_dem.get()
    except Exception as e:
        print("sim: terrain not loaded:", repr(e), flush=True)
    ROOFS = None
    if DEM and "--no-buildings" not in sys.argv:
        try:
            ROOFS = terrain_dem.roofs()      # 3D buildings (sim/buildings_build.py --ground): roofs are ground for the crash check
        except Exception as e:
            print("sim: building roofs not loaded:", repr(e), flush=True)
    if DEM:
        if ROOFS:
            def ground_msl(lat, lon, _d=DEM.height_msl, _r=ROOFS.roof_msl):
                g, r = _d(lat, lon), _r(lat, lon)
                return g if r is None or r <= g else r
            sim.terrain = ground_msl
            print("sim: building roofs in the ground (%s, raster %s)" % (terrain_dem.BUILDINGS_ROOT, ROOFS.made), flush=True)
        else:
            sim.terrain = DEM.height_msl
        sim.reset("air")
        print("sim: JSBSim ground = Copernicus DEM (%d cells, %s); field %.1f m at %s" % (len(DEM.cells), terrain_dem.ROOT, DEM.height_msl(LAT0_LON0[0], LAT0_LON0[1]), FIELD["icao"]), flush=True)
    else:
        print("sim: terrain data missing (python sim/terrain_fetch.py && python sim/terrain_build.py --all) - flat field elevation", flush=True)
state = dict(paused=False, rid=0, snap=None, udp_ctrl_t=-1e9, joy=None, joy_name="", hmd=False, hmd_t=-1e9, t_start=time.time(), crashed=False,
             errors=0)
udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
_lock = threading.RLock()                 # sim / trainer are touched from the asyncio loop and the joystick thread


# 'place' (checks / scripts): values outside these are refused (absurd starts gave NaN flights). The start picker
# (sim/start_spots.py) stays well inside: 250 kt, 60 m AGL .. 3000 m.
PLACE_LIMITS = dict(lat=(-89.0, 89.0), lon=(-180.0, 180.0), alt_m=(-100.0, 15000.0), hdg=(-720.0, 720.0), kts=(100.0, 700.0))


def place_ok(at):
    return all(math.isfinite(v) and PLACE_LIMITS[k][0] <= v <= PLACE_LIMITS[k][1] for k, v in at.items())


def reset(mode, at=None):
    with _lock:
        if mode == "air" and at is None and state.get("spot_at") and getattr(globals().get("trainer"), "L", None) is None:   # free flight (R, crash retry): chosen spot
            at = state["spot_at"]
        try:
            sim.reset(mode, at)
        except RuntimeError as e:                    # JSBSim refused the start (simcore already flies untrimmed on a trim failure)
            print("sim: reset %s %r failed (%s) - keeping the current flight" % (mode, at, e), flush=True)
            return
        state["rid"] += 1
        state["paused"] = False
        state["crashed"] = False
        state["crash_obj"] = None
        if "trainer" in globals():
            trainer.free_t0 = trainer.clock          # free flight: crash check starts 1 s after a (re)start


voice = Voice()                           # instructor voice (offline Korean SAPI), text only if unavailable
trainer = Trainer(reset, voice)
picker = None                             # Busan start picker (start_spots.py): Busan start airfield only
if FIELD["id"] == "rkpk":
    try:
        from start_spots import Picker
        picker = Picker(ground=sim.terrain)
    except Exception as e:
        print("sim: start picker not available:", repr(e), flush=True)
SPOT_FIRST = picker is not None and "--free-flight" in sys.argv and "--no-picker" not in sys.argv
if "--free-flight" in sys.argv:           # skip the start menu: free flight from the first Play (user flies at once)
    trainer.L, trainer.phase, trainer.free_t0 = None, "free", 0.0
    if SPOT_FIRST:
        trainer._say("어디서 출발할지 고르세요. 엔터를 누르면 출발해요.", force=True)
    else:
        trainer._say("자유 비행이에요. 바로 조종하세요. F1 을 누르면 메뉴로 가요.", force=True)
    print("sim: free flight (no start menu)%s" % (", start picker first" if SPOT_FIRST else ""), flush=True)


def spot_open(can_cancel=False):
    """show the start picker; the sim stays paused while it is open. can_cancel (opened from the F1 menu): Backspace goes
    back to the menu and puts the aircraft back where it was."""
    if picker is None:
        return
    with _lock:
        s = state["snap"] or {}
        state["spot_ret"] = None
        if can_cancel and "lat" in s:
            state["spot_ret"] = ("runway", None) if s.get("wow") else ("air", dict(lat=s["lat"], lon=s["lon"], alt_m=s["alt_m"], hdg=s["psi"],
                                                                                    kts=max(200.0, s.get("kts", 250.0))))
        picker.open, picker.can_cancel, picker.previewed = True, can_cancel, None
        picker.changed_t = time.monotonic()          # preview the selection (aircraft put there, still paused)


def spot_close(go):
    with _lock:
        sp = picker.spot() if go else None
        if go and sp is None:
            return
        picker.open = False
        if go:
            picker.save_last()
            state["spot_at"] = None if sp["mode"] == "runway" else {k: sp[k] for k in ("lat", "lon", "alt_m", "hdg", "kts")}
            trainer.L, trainer.crash, trainer.debrief, trainer.phase = None, None, None, "free"
            reset(sp["mode"], None if sp["mode"] == "runway" else {k: sp[k] for k in ("lat", "lon", "alt_m", "hdg", "kts")})
            trainer._say("%s에서 출발해요." % sp["name"].split(" (")[0], force=True)
            print("sim: start spot %s %s %.5f %.5f alt %.0f m hdg %.0f" % (sp["key"], sp["mode"], sp["lat"], sp["lon"], sp["alt_m"], sp["hdg"]), flush=True)
        elif picker.previewed is not None and state.get("spot_ret"):     # back where it was before the preview
            mode, at = state["spot_ret"]
            reset(mode, at)
            trainer.free_t0 = trainer.clock
        picker.previewed = None


if picker is not None:
    trainer.on_spot = lambda: spot_open(can_cancel=True)     # F1 menu item '출발 위치 고르기 (부산)'
    if SPOT_FIRST:
        spot_open()


def terrain_check(s, dt_sim):
    """DEM ground: below the terrain, or (almost) on the ground away from the airfield (mountain, field, sea) = crash
    (red screen via the trainer's 'crashed' check). JSBSim's gear would otherwise just stand on the slope."""
    import terrain_dem
    s.update(terrain="dem", terrain_m=round(sim.terrain_m or 0.0, 1), geoid_here=round(DEM.geoid_here(s["lat"], s["lon"]), 2))
    if dt_sim <= 0 or state["crashed"]:
        return
    off_field = float(terrain_dem.airfield_weight(s["lat"], s["lon"])) <= 0.0
    # off the airfield 2.5 m above the ground is already a hit (the trainer's gear-up / hard-landing checks fire at 2.4 m)
    if s["agl_m"] < -0.5 or (off_field and (s["wow"] or s["agl_m"] < 2.5)):
        state["crashed"] = True
        # the ground under the aircraft was a building roof (sim.terrain = max(DEM, roof)) -> say so on the crash screen
        on_bldg = ROOFS is not None and (ROOFS.roof_msl(s["lat"], s["lon"]) or -1e9) > DEM.height_msl(s["lat"], s["lon"]) + 0.5
        state["crash_obj"] = "building" if on_bldg else "terrain"
        print("sim: %s hit at %.5f %.5f, ground %.0f m, agl %.1f m, wow %s, off field %s" % (
            state["crash_obj"], s["lat"], s["lon"], sim.terrain_m or 0.0, s["agl_m"], s["wow"], off_field), flush=True)


def snapshot(dt_sim):
    s = sim.packet(1 / 60 if dt_sim > 0 else 0.0)
    if DEM:
        terrain_check(s, dt_sim)
    s.update(APT_INFO)
    spot_on = picker is not None and picker.open
    s.update(lat0=START["lat"], lon0=START["lon"], paused=state["paused"] or trainer.want_pause or spot_on, user_paused=state["paused"], rid=state["rid"],
             field_m=FIELD_FT * 0.3048, geoid_n=GEOID_N, rwy_hdg=RWY["hdg"], joystick=state["joy_name"],
             src="joystick" if state["joy"] else ("unreal" if udp_fresh() else "browser"),
             hmd=state["hmd"] and time.monotonic() - state["hmd_t"] < 2.0, crashed=state["crashed"], crash_obj=state.get("crash_obj") if state["crashed"] else None, demo=trainer.ctrl_override is not None,
             assist=trainer.assist, slow=trainer.slow, chair_lim=CHAIR_LIM, chair_rate=CHAIR_RATE, uptime=round(time.time() - state["t_start"]))
    if picker is not None:
        s["spot"] = picker.public()
    try:
        s["tut"] = trainer.update(s, dt_sim)
    except Exception as e:                                   # the lesson logic must never stop the simulator
        state["errors"] += 1
        if state["errors"] < 20:
            print("sim: training error", repr(e), flush=True)
        s["tut"] = dict(on=False, phase="error", error=repr(e))
    for payload, addr in ((dict(roll=round(s["chair_roll"], 2), pitch=round(s["chair_pitch"], 2)), CHAIR_UDP), (s, UNREAL_UDP)):
        try:
            udp.sendto(json.dumps(payload).encode(), addr)
        except OSError:
            pass
    state["snap"] = s
    return s


def udp_fresh():
    return time.monotonic() - state["udp_ctrl_t"] < UDP_FRESH_S


def handle_msg(m, src):
    """Same JSON for WebSocket (src='ws'), UDP 4221 (src='udp') and the joystick buttons (src='joy')."""
    with _lock:
        cmd = m.get("cmd")
        if cmd == "spot" and picker is not None:
            if m.get("op") == "open":
                spot_open(can_cancel=bool(m.get("cancel", True)))
                return
            if not picker.open:
                return
            r = picker.command(m)
            if r == "go":
                spot_close(True)
            elif r == "cancel":
                spot_close(False)
            return
        if cmd == "reset":
            if m.get("play") and SPOT_FIRST:            # Unreal Play started: fresh run -> the start picker first
                reset(m.get("mode", "air"))
                spot_open()
                return
            if m.get("user") and trainer.phase == "crash":      # crash screen: R = retry (same step / same start)
                trainer.command({"cmd": "tut", "op": "retry"})
                return
            if m.get("user") and not trainer.allow_reset():   # R / T key during a lesson: ask once (no lost lesson by a stray key)
                return
            reset(m.get("mode", "air"))
        elif cmd == "place":                     # checks: air start at lat / lon / alt_m (MSL) / hdg / kts, e.g. near a mountain
            if picker is not None:
                picker.open = False                  # scripted placement (checks) closes the start picker
            try:
                at = {k: float(m[k]) for k in ("lat", "lon", "alt_m", "hdg", "kts") if k in m}
                if "lat" in at and "lon" in at and "alt_m" in at and place_ok(at):
                    reset("air", at)
                else:
                    print("sim: place refused (needs lat / lon / alt_m inside %s): %r" % (PLACE_LIMITS, at), flush=True)
            except (TypeError, ValueError, OverflowError):
                pass
        elif cmd in ("tut", "menu", "voice"):
            trainer.command(m)
        elif cmd == "pause":                     # toggle, or set with {"on": true/false} (Unreal Play start)
            state["paused"] = bool(m["on"]) if "on" in m else not state["paused"]
        elif cmd == "crashed":                   # Unreal: hit real terrain (Cesium) while JSBSim still flies
            state["crashed"] = bool(m.get("on", True))
        elif "ctrl" in m:
            if "rid" in m and m["rid"] != state["rid"]:
                return                               # sent before the client saw the last reset (stale gear/throttle)
            if src == "udp":
                state["udp_ctrl_t"] = time.monotonic()
                if "hmd" in m:                       # Unreal reports a VR headset -> instructor uses rig wording
                    state["hmd"], state["hmd_t"] = bool(m["hmd"]), time.monotonic()
            elif udp_fresh():
                return                               # Unreal is driving; ignore the browser's idle controls
            joy_keys = state["joy"] or ()
            try:
                vals = {k: float(v) for k, v in m["ctrl"].items() if k in sim.ctrl and k not in joy_keys}
            except OverflowError:                    # an integer too big for a float
                return
            if all(math.isfinite(v) for v in vals.values()):       # NaN / inf (JSON allows them): drop the message, keep last values
                sim.ctrl.update(vals)


class CmdUDP(asyncio.DatagramProtocol):
    def datagram_received(self, data, addr):
        try:
            handle_msg(json.loads(data), "udp")
        except (ValueError, TypeError, AttributeError, OverflowError, RecursionError):
            pass


def joystick_thread():
    """pygame joystick poll, 100 Hz. Axes -> controls (state['joy'] = mapped axis names while connected);
    buttons / stick -> menu and lesson navigation (controls.json "buttons")."""
    try:
        import pygame
    except ImportError:
        print("sim: pygame not installed - no joystick (pip install pygame)", flush=True)
        return
    try:
        cfg = json.load(open(CONTROLS, encoding="utf-8"))
    except (OSError, ValueError) as e:
        print(f"sim: controls.json unreadable ({e}) - using defaults", flush=True)
        cfg = {}
    axes = cfg.get("axes") or {"ail": {"axis": 0}, "elev": {"axis": 1, "invert": True}, "thr": {"axis": 2}, "rud": {"axis": 3}}
    btn = dict(dict(select=0, back=1, repeat=2, menu=3), **(cfg.get("buttons") or {}))
    dz, idx = float(cfg.get("deadzone", 0.03)), int(cfg.get("joystick_index", 0))
    pygame.init(); pygame.joystick.init()
    js = None
    prev_b, nav = {}, 0
    while True:
        try:
            pygame.event.pump()
            if js is None and pygame.joystick.get_count() > idx:
                js = pygame.joystick.Joystick(idx); js.init()
                state["joy_name"] = js.get_name()
                state["joy"] = {k for k, a in axes.items() if a.get("axis", -1) < js.get_numaxes()}
                print(f"sim: joystick '{state['joy_name']}' axes={js.get_numaxes()} buttons={js.get_numbuttons()} -> {sorted(state['joy'])}", flush=True)
            elif js is not None and pygame.joystick.get_count() <= idx:
                print("sim: joystick removed", flush=True)
                js, state["joy"], state["joy_name"] = None, None, ""
            if js is not None:
                vals = {}
                for k in state["joy"]:
                    v = js.get_axis(axes[k]["axis"])
                    if axes[k].get("invert"):
                        v = -v
                    if abs(v) < dz:
                        v = 0.0
                    vals[k] = (1 - v) / 2 if k == "thr" else v
                in_spot = picker is not None and picker.open
                in_menu = trainer.phase == "menu" and not in_spot
                with _lock:
                    if not in_menu and not in_spot:
                        sim.ctrl.update(vals)
                if in_spot:                              # start picker: stick fwd / back = list, left / right = heading, buttons
                    e, a = vals.get("elev", 0.0), vals.get("ail", 0.0)
                    z = 1 if e > 0.6 else -1 if e < -0.6 else 0
                    x = 1 if a > 0.6 else -1 if a < -0.6 else 0
                    if z and z != nav:
                        handle_msg({"cmd": "spot", "op": "up" if z > 0 else "down"}, "joy")
                    if x and x != state.get("joy_x"):
                        handle_msg({"cmd": "spot", "op": "hdg", "d": x}, "joy")
                    nav, state["joy_x"] = z, x
                    for name, b in btn.items():
                        if b is None or b >= js.get_numbuttons():
                            continue
                        down = bool(js.get_button(b))
                        if down and not prev_b.get(name):
                            op = dict(select="go", back="cancel", repeat="random").get(name)
                            if op:
                                handle_msg({"cmd": "spot", "op": op}, "joy")
                        prev_b[name] = down
                    time.sleep(0.01)
                    continue
                # menu: stick forward / back = up / down (edge, with a dead band), buttons = select / back / repeat / menu
                e = vals.get("elev", 0.0)
                z = 1 if e > 0.6 else -1 if e < -0.6 else 0
                if in_menu and z and z != nav:
                    handle_msg({"cmd": "menu", "op": "up" if z > 0 else "down"}, "joy")
                nav = z
                for name, b in btn.items():
                    if b is None or b >= js.get_numbuttons():
                        continue
                    down = bool(js.get_button(b))
                    if down and not prev_b.get(name):
                        if name == "select":
                            handle_msg({"cmd": "menu", "op": "select"} if in_menu else {"cmd": "tut", "op": "next"}, "joy")
                        elif name == "back":
                            handle_msg({"cmd": "menu", "op": "back"} if in_menu else {"cmd": "tut", "op": "menu"}, "joy")
                        elif name == "repeat":
                            handle_msg({"cmd": "tut", "op": "repeat"}, "joy")
                        elif name == "menu":
                            handle_msg({"cmd": "tut", "op": "menu"}, "joy")
                    prev_b[name] = down
        except Exception as e:                       # unplugged mid-read etc.
            print(f"sim: joystick error {e}", flush=True)
            js, state["joy"], state["joy_name"] = None, None, ""
        time.sleep(0.01)


def local_origin(origin):
    """True when a WebSocket / POST may act: no Origin header (Unreal, python clients) or a page served from this PC
    (http(s)://127.0.0.1:* or localhost:*). Any other web page open in a browser must not reset / pause / steer the sim."""
    if not origin:
        return True
    from urllib.parse import urlsplit
    try:
        u = urlsplit(origin.strip())
        u.port                                       # raises ValueError on a bad port
    except ValueError:
        return False
    return u.scheme in ("http", "https") and u.hostname in ("127.0.0.1", "localhost") and not u.username and u.path in ("", "/")


def ws_origin_check(connection, request):
    origins = request.headers.get_all("Origin")
    if not all(local_origin(o) for o in origins):
        print("sim: WebSocket refused, Origin %r is not this PC" % (origins,), flush=True)
        return connection.respond(403, "origin not allowed")
    return None


async def handler(ws):
    async def rx():
        async for msg in ws:
            try:
                handle_msg(json.loads(msg), "ws")
            except (ValueError, TypeError, AttributeError, OverflowError, RecursionError):
                pass
    task = asyncio.create_task(rx())
    try:
        while True:
            if state["snap"] is not None:
                await ws.send(json.dumps(state["snap"]))
            await asyncio.sleep(1 / 60)
    except Exception:
        pass
    finally:
        task.cancel()


async def physics():
    nxt = time.perf_counter()
    while True:
        nxt += 1 / 60
        with _lock:
            if picker is not None and picker.open:
                sp = picker.preview_due()              # start picker: put the aircraft at the selection, still paused
                if sp is not None:
                    reset(sp["mode"], None if sp["mode"] == "runway" else {k: sp[k] for k in ("lat", "lon", "alt_m", "hdg", "kts")})
            paused = state["paused"] or trainer.want_pause or (picker is not None and picker.open)
            dt_sim = 0.0
            if not paused:
                if trainer.ctrl_override:               # demo autopilot flies (the cockpit stick / throttle show it)
                    sim.ctrl.update(trainer.ctrl_override)
                sim.frame(assist=trainer.assist, slow=trainer.slow)
                dt_sim = (1 / 120) if trainer.slow else (1 / 60)
            snapshot(dt_sim)                            # chair cue + Unreal UDP + training + cached for WebSocket
        await asyncio.sleep(max(0, nxt - time.perf_counter()))
        if time.perf_counter() - nxt > 0.5:             # fell behind (debugger, sleep): don't try to catch up
            nxt = time.perf_counter()


def http_server():
    docs = os.path.join(os.path.dirname(HERE), "docs")

    class Handler(SimpleHTTPRequestHandler):           # sim/web at /, repo docs/ at /docs/, training images at /out/
        def translate_path(self, path):
            p = path.split("?")[0]
            if p.startswith("/docs/"):
                return os.path.join(docs, os.path.basename(p))
            if p.startswith("/out/"):
                return os.path.join(OUT, os.path.basename(p))
            return super().translate_path(path)

        def end_headers(self):
            self.send_header("Cache-Control", "no-store")
            super().end_headers()

        def log_message(self, *a):
            pass
    os.chdir(WEB)
    ThreadingHTTPServer(("127.0.0.1", HTTP_PORT), Handler).serve_forever()


async def main():
    threading.Thread(target=http_server, daemon=True).start()
    # V-World tile proxy (key, cache, budget) for the Unreal 'vworld' ground mode: started here when
    # unreal/GyroSim/Config/cesium_token.txt has a 'vworld' line (or with --vworld-proxy); skipped if one already runs
    try:
        import vworld_proxy
        if "--vworld-proxy" in sys.argv or vworld_proxy.ground_mode_is_vworld():
            vworld_proxy.start_in_thread()
    except Exception as e:
        print("vworld proxy not started:", repr(e), flush=True)
    threading.Thread(target=joystick_thread, daemon=True).start()
    await asyncio.get_running_loop().create_datagram_endpoint(CmdUDP, local_addr=("127.0.0.1", CMD_UDP_PORT))
    async with serve(handler, "127.0.0.1", WS_PORT, process_request=ws_origin_check):
        print(f"sim: open http://127.0.0.1:{HTTP_PORT}/  (ws {WS_PORT}, chair UDP {CHAIR_UDP}, "
              f"Unreal state UDP {UNREAL_UDP}, cmd UDP {CMD_UDP_PORT})", flush=True)
        await physics()

if __name__ == "__main__":
    asyncio.run(main())
