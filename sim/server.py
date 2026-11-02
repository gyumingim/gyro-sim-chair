"""Simple flight simulator prototype for the gyro chair.

JSBSim (F-16 model that ships with JSBSim) runs here at 120 Hz in real time.
The browser page (web/index.html) shows the 3D view + HUD, reads the joystick/keyboard and sends the controls
over a WebSocket. Every frame we also compute a chair command (roll/pitch, slow tilt-coordination cue) and send it
as UDP JSON to the chair controller (127.0.0.1:4210 by default) — nothing listens there yet, that's fine.

Unreal client (unreal/GyroSim): the same snapshot also goes out as UDP JSON to 127.0.0.1:4220 at 60 Hz, and control /
command packets (same JSON as the WebSocket messages) are accepted on UDP 4221.
Joystick (pygame, mapping in controls.json) overrides browser/Unreal axes when one is plugged in.
Control priority: joystick axes > Unreal UDP (if a ctrl packet arrived in the last 0.5 s) > browser WebSocket.

Run:  python server.py      then open http://127.0.0.1:8780/
"""
import asyncio, json, math, os, socket, threading, time
os.environ.setdefault("SDL_JOYSTICK_ALLOW_BACKGROUND_EVENTS", "1")     # joystick keeps working while Unreal has focus
os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import jsbsim
from tutorial import Tutorial
from websockets.asyncio.server import serve

HTTP_PORT, WS_PORT = 8780, 8781
CHAIR_UDP = ("127.0.0.1", 4210)
UNREAL_UDP = ("127.0.0.1", 4220)          # state out
CMD_UDP_PORT = 4221                       # control / command in
UDP_FRESH_S = 0.5
DT = 1 / 120
HERE = os.path.dirname(os.path.abspath(__file__))
WEB = os.path.join(HERE, "web")
CONTROLS = os.path.join(HERE, "controls.json")
START = dict(lat=36.70, lon=127.50, alt_ft=6000, kts=350, hdg=0.0)       # somewhere over central Korea, sea-level ground

def new_fdm(mode="air"):
    fdm = jsbsim.FGFDMExec(jsbsim.get_default_root_dir())
    fdm.set_debug_level(0)
    fdm.set_dt(DT)
    fdm.load_model("f16")
    fdm["ic/lat-geod-deg"], fdm["ic/long-gc-deg"] = START["lat"], START["lon"]
    if mode == "approach":                       # tutorial lesson 6: 9 km before the south threshold (north -150 m), 3 deg path
        fdm["ic/lat-geod-deg"] = START["lat"] + (-150.0 - 9000.0) / 110540.0
    fdm["ic/psi-true-deg"] = START["hdg"]
    fdm["ic/terrain-elevation-ft"] = 0
    if mode == "runway":
        fdm["ic/h-agl-ft"] = 4.0
        fdm["ic/vc-kts"] = 0
        fdm["ic/theta-deg"] = 0
    elif mode == "approach":
        fdm["ic/h-sl-ft"] = 1550
        fdm["ic/vc-kts"] = 180
        fdm["ic/gamma-deg"] = 0
    else:
        fdm["ic/h-sl-ft"] = START["alt_ft"]
        fdm["ic/vc-kts"] = START["kts"]
        fdm["ic/gamma-deg"] = 0
    fdm.run_ic()
    fdm["propulsion/set-running"] = -1           # start all engines
    fdm["gear/gear-cmd-norm"] = 1 if mode == "runway" else 0
    if mode == "runway":
        fdm["fcs/throttle-cmd-norm"] = 0.0
    else:
        fdm["simulation/do_simple_trim"] = 1       # level flight trim: sets throttle + pitch trim
    return fdm

class Chair:
    """Very small motion cue: tilt toward the aircraft attitude (scaled) + sustained accelerations, rate-limited."""
    def __init__(self):
        self.roll = self.pitch = 0.0
    def update(self, phi_deg, theta_deg, ax_g, ay_g, dt):
        tgt_r = max(-20, min(20, 0.35 * phi_deg + 25 * ay_g))
        tgt_p = max(-15, min(15, 0.30 * theta_deg + 20 * ax_g))
        rate = 8 * dt                                   # ≤ 8 deg/s, the weight-shift chair is slow anyway
        self.roll += max(-rate, min(rate, tgt_r - self.roll))
        self.pitch += max(-rate, min(rate, tgt_p - self.pitch))
        return self.roll, self.pitch

state = dict(fdm=new_fdm(), ctrl=dict(ail=0, elev=0, rud=0, thr=0.0, brk_l=0, brk_r=0, gear=0), chair=Chair(), paused=False, rid=0,
             snap=None, udp_ctrl_t=-1e9, joy=None, joy_name="")
state["ctrl"]["thr"] = state["thr_init"] = state["fdm"]["fcs/throttle-cmd-norm"]
udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

def snapshot():
    f = state["fdm"]
    g = 32.174
    ax, ay = f["accelerations/a-pilot-x-ft_sec2"] / g, f["accelerations/a-pilot-y-ft_sec2"] / g
    phi, th, psi = math.degrees(f["attitude/phi-rad"]), math.degrees(f["attitude/theta-rad"]), math.degrees(f["attitude/psi-rad"])
    cr, cp = state["chair"].update(phi, th, ax, ay, 1 / 60)
    c = state["ctrl"]
    s = dict(t=f.get_sim_time(), lat=f["position/lat-geod-deg"], lon=f["position/long-gc-deg"], alt_m=f["position/h-sl-ft"] * 0.3048,
             agl_m=f["position/h-agl-ft"] * 0.3048, phi=phi, theta=th, psi=psi, kts=f["velocities/vc-kts"], mach=f["velocities/mach"],
             vs_fpm=f["velocities/h-dot-fps"] * 60, alpha=f["aero/alpha-deg"], nz=-f["accelerations/n-pilot-z-norm"],
             thr=f["fcs/throttle-cmd-norm"], gear=f["gear/gear-pos-norm"], ax=ax, ay=ay, chair_roll=cr, chair_pitch=cp,
             lat0=START["lat"], lon0=START["lon"], paused=state["paused"],
             rid=state["rid"], thr_init=state["thr_init"], gear_init=state["ctrl"]["gear"],
             ail=c["ail"], elev=c["elev"], rud=c["rud"], brk=(c["brk_l"] + c["brk_r"]) / 2, brk_l=c["brk_l"], brk_r=c["brk_r"],
             gear_cmd=c["gear"], wow=any(f["gear/unit[%d]/WOW" % i] > 0.5 for i in range(3)),
             joystick=state["joy_name"], src="joystick" if state["joy"] else ("unreal" if udp_fresh() else "browser"))
    s["tut"] = tutorial.update(s, 1 / 60)
    for payload, addr in ((dict(roll=round(cr, 2), pitch=round(cp, 2)), CHAIR_UDP), (s, UNREAL_UDP)):
        try:
            udp.sendto(json.dumps(payload).encode(), addr)
        except OSError:
            pass
    state["snap"] = s
    return s

def udp_fresh():
    return time.monotonic() - state["udp_ctrl_t"] < UDP_FRESH_S

def reset(mode):
    state["fdm"] = new_fdm(mode); state["chair"] = Chair()
    state["ctrl"].update(ail=0, elev=0, rud=0, brk_l=0, brk_r=0)
    state["ctrl"]["gear"] = 1 if mode == "runway" else 0
    state["ctrl"]["thr"] = state["thr_init"] = state["fdm"]["fcs/throttle-cmd-norm"]
    state["rid"] += 1
    state["paused"] = False

tutorial = Tutorial(reset)

def handle_msg(m, src):
    """Same JSON for WebSocket (src='ws') and UDP 4221 (src='udp')."""
    if m.get("cmd") == "reset":
        reset(m.get("mode", "air"))
    elif m.get("cmd") == "tut":
        tutorial.command(m)
    elif m.get("cmd") == "pause":
        state["paused"] = not state["paused"]
    elif "ctrl" in m:
        if "rid" in m and m["rid"] != state["rid"]:
            return                                   # sent before the client saw the last reset (stale gear/throttle)
        if src == "udp":
            state["udp_ctrl_t"] = time.monotonic()
        elif udp_fresh():
            return                                   # Unreal is driving; ignore the browser's idle controls
        joy_keys = state["joy"] or ()
        state["ctrl"].update({k: float(v) for k, v in m["ctrl"].items() if k in state["ctrl"] and k not in joy_keys})

class CmdUDP(asyncio.DatagramProtocol):
    def datagram_received(self, data, addr):
        try:
            handle_msg(json.loads(data), "udp")
        except (ValueError, TypeError, AttributeError):
            pass

def joystick_thread():
    """pygame joystick poll, 100 Hz. Sets state['joy'] = set of mapped axis names while a stick is connected."""
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
    dz, idx = float(cfg.get("deadzone", 0.03)), int(cfg.get("joystick_index", 0))
    pygame.init(); pygame.joystick.init()
    js = None
    while True:
        try:
            pygame.event.pump()
            if js is None and pygame.joystick.get_count() > idx:
                js = pygame.joystick.Joystick(idx); js.init()
                state["joy_name"] = js.get_name()
                state["joy"] = {k for k, a in axes.items() if a.get("axis", -1) < js.get_numaxes()}
                print(f"sim: joystick '{state['joy_name']}' axes={js.get_numaxes()} -> {sorted(state['joy'])}", flush=True)
            elif js is not None and pygame.joystick.get_count() <= idx:
                print("sim: joystick removed", flush=True)
                js, state["joy"], state["joy_name"] = None, None, ""
            if js is not None:
                for k in state["joy"]:
                    v = js.get_axis(axes[k]["axis"])
                    if axes[k].get("invert"):
                        v = -v
                    if abs(v) < dz:
                        v = 0.0
                    state["ctrl"][k] = (1 - v) / 2 if k == "thr" else v
        except Exception as e:                       # unplugged mid-read etc.
            print(f"sim: joystick error {e}", flush=True)
            js, state["joy"], state["joy_name"] = None, None, ""
        time.sleep(0.01)

def apply_controls():
    f, c = state["fdm"], state["ctrl"]
    f["fcs/aileron-cmd-norm"] = c["ail"]
    f["fcs/elevator-cmd-norm"] = c["elev"]
    f["fcs/rudder-cmd-norm"] = c["rud"]
    f["fcs/throttle-cmd-norm"] = c["thr"]
    f["fcs/left-brake-cmd-norm"] = c["brk_l"]
    f["fcs/right-brake-cmd-norm"] = c["brk_r"]
    f["gear/gear-cmd-norm"] = c["gear"]

async def handler(ws):
    async def rx():
        async for msg in ws:
            handle_msg(json.loads(msg), "ws")
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
        if not state["paused"]:
            apply_controls()
            for _ in range(2):                      # 2 × 1/120 s per 1/60 s frame
                state["fdm"].run()
        snapshot()                                  # once per frame: chair cue + Unreal UDP + cached for WebSocket
        await asyncio.sleep(max(0, nxt - time.perf_counter()))

def http_server():
    docs = os.path.join(os.path.dirname(HERE), "docs")

    class Handler(SimpleHTTPRequestHandler):           # sim/web at /, repo docs/ at /docs/ (tutorial manual)
        def translate_path(self, path):
            if path.startswith("/docs/"):
                return os.path.join(docs, os.path.basename(path.split("?")[0]))
            return super().translate_path(path)
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
