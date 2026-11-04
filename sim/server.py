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

Run:  python server.py      then open http://127.0.0.1:8780/
"""
import asyncio, json, os, socket, threading, time
os.environ.setdefault("SDL_JOYSTICK_ALLOW_BACKGROUND_EVENTS", "1")     # joystick keeps working while Unreal has focus
os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from websockets.asyncio.server import serve
from simcore import Sim, START, CHAIR_LIM, CHAIR_RATE
from airfield import FIELD_FT, GEOID_N, RWY
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
state = dict(paused=False, rid=0, snap=None, udp_ctrl_t=-1e9, joy=None, joy_name="", hmd=False, hmd_t=-1e9, t_start=time.time(), crashed=False,
             errors=0)
udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
_lock = threading.RLock()                 # sim / trainer are touched from the asyncio loop and the joystick thread


def reset(mode):
    with _lock:
        sim.reset(mode)
        state["rid"] += 1
        state["paused"] = False
        state["crashed"] = False


voice = Voice()                           # instructor voice (offline Korean SAPI), text only if unavailable
trainer = Trainer(reset, voice)


def snapshot(dt_sim):
    s = sim.packet(1 / 60 if dt_sim > 0 else 0.0)
    s.update(lat0=START["lat"], lon0=START["lon"], paused=state["paused"] or trainer.want_pause, user_paused=state["paused"], rid=state["rid"],
             field_m=FIELD_FT * 0.3048, geoid_n=GEOID_N, rwy_hdg=RWY["hdg"], joystick=state["joy_name"],
             src="joystick" if state["joy"] else ("unreal" if udp_fresh() else "browser"),
             hmd=state["hmd"] and time.monotonic() - state["hmd_t"] < 2.0, crashed=state["crashed"], demo=trainer.ctrl_override is not None,
             assist=trainer.assist, slow=trainer.slow, chair_lim=CHAIR_LIM, chair_rate=CHAIR_RATE, uptime=round(time.time() - state["t_start"]))
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
        if cmd == "reset":
            if m.get("user") and not trainer.allow_reset():   # R / T key during a lesson: ask once (no lost lesson by a stray key)
                return
            reset(m.get("mode", "air"))
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
            sim.ctrl.update({k: float(v) for k, v in m["ctrl"].items() if k in sim.ctrl and k not in joy_keys})


class CmdUDP(asyncio.DatagramProtocol):
    def datagram_received(self, data, addr):
        try:
            handle_msg(json.loads(data), "udp")
        except (ValueError, TypeError, AttributeError):
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
                in_menu = trainer.phase == "menu"
                with _lock:
                    if not in_menu:
                        sim.ctrl.update(vals)
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


async def handler(ws):
    async def rx():
        async for msg in ws:
            try:
                handle_msg(json.loads(msg), "ws")
            except (ValueError, TypeError, AttributeError):
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
            paused = state["paused"] or trainer.want_pause
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
    threading.Thread(target=joystick_thread, daemon=True).start()
    await asyncio.get_running_loop().create_datagram_endpoint(CmdUDP, local_addr=("127.0.0.1", CMD_UDP_PORT))
    async with serve(handler, "127.0.0.1", WS_PORT):
        print(f"sim: open http://127.0.0.1:{HTTP_PORT}/  (ws {WS_PORT}, chair UDP {CHAIR_UDP}, "
              f"Unreal state UDP {UNREAL_UDP}, cmd UDP {CMD_UDP_PORT})", flush=True)
        await physics()

if __name__ == "__main__":
    asyncio.run(main())
