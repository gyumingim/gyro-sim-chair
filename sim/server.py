"""Simple flight simulator prototype for the gyro chair.

JSBSim (F-16 model that ships with JSBSim) runs here at 120 Hz in real time.
The browser page (web/index.html) shows the 3D view + HUD, reads the joystick/keyboard and sends the controls
over a WebSocket. Every frame we also compute a chair command (roll/pitch, slow tilt-coordination cue) and send it
as UDP JSON to the chair controller (127.0.0.1:4210 by default) — nothing listens there yet, that's fine.

Run:  python server.py      then open http://127.0.0.1:8780/
"""
import asyncio, json, math, os, socket, threading, time
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import jsbsim
from websockets.asyncio.server import serve

HTTP_PORT, WS_PORT = 8780, 8781
CHAIR_UDP = ("127.0.0.1", 4210)
DT = 1 / 120
WEB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web")
START = dict(lat=36.70, lon=127.50, alt_ft=6000, kts=350, hdg=0.0)       # somewhere over central Korea, sea-level ground

def new_fdm(mode="air"):
    fdm = jsbsim.FGFDMExec(jsbsim.get_default_root_dir())
    fdm.set_debug_level(0)
    fdm.set_dt(DT)
    fdm.load_model("f16")
    fdm["ic/lat-geod-deg"], fdm["ic/long-gc-deg"] = START["lat"], START["lon"]
    fdm["ic/psi-true-deg"] = START["hdg"]
    fdm["ic/terrain-elevation-ft"] = 0
    if mode == "runway":
        fdm["ic/h-agl-ft"] = 4.0
        fdm["ic/vc-kts"] = 0
        fdm["ic/theta-deg"] = 0
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

state = dict(fdm=new_fdm(), ctrl=dict(ail=0, elev=0, rud=0, thr=0.0, brk_l=0, brk_r=0, gear=0), chair=Chair(), paused=False, rid=0)
state["ctrl"]["thr"] = state["thr_init"] = state["fdm"]["fcs/throttle-cmd-norm"]
udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

def snapshot():
    f = state["fdm"]
    g = 32.174
    ax, ay = f["accelerations/a-pilot-x-ft_sec2"] / g, f["accelerations/a-pilot-y-ft_sec2"] / g
    phi, th, psi = math.degrees(f["attitude/phi-rad"]), math.degrees(f["attitude/theta-rad"]), math.degrees(f["attitude/psi-rad"])
    cr, cp = state["chair"].update(phi, th, ax, ay, 1 / 60)
    s = dict(t=f.get_sim_time(), lat=f["position/lat-geod-deg"], lon=f["position/long-gc-deg"], alt_m=f["position/h-sl-ft"] * 0.3048,
             agl_m=f["position/h-agl-ft"] * 0.3048, phi=phi, theta=th, psi=psi, kts=f["velocities/vc-kts"], mach=f["velocities/mach"],
             vs_fpm=f["velocities/h-dot-fps"] * 60, alpha=f["aero/alpha-deg"], nz=-f["accelerations/n-pilot-z-norm"],
             thr=f["fcs/throttle-cmd-norm"], gear=f["gear/gear-pos-norm"], ax=ax, ay=ay, chair_roll=cr, chair_pitch=cp,
             lat0=START["lat"], lon0=START["lon"], paused=state["paused"],
             rid=state["rid"], thr_init=state["thr_init"], gear_init=state["ctrl"]["gear"])
    try:
        udp.sendto(json.dumps(dict(roll=round(cr, 2), pitch=round(cp, 2))).encode(), CHAIR_UDP)
    except OSError:
        pass
    return s

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
            m = json.loads(msg)
            if m.get("cmd") == "reset":
                state["fdm"] = new_fdm(m.get("mode", "air")); state["chair"] = Chair()
                state["ctrl"]["gear"] = 1 if m.get("mode") == "runway" else 0
                state["ctrl"]["thr"] = state["thr_init"] = state["fdm"]["fcs/throttle-cmd-norm"]
                state["rid"] += 1
            elif m.get("cmd") == "pause":
                state["paused"] = not state["paused"]
            elif "ctrl" in m:
                state["ctrl"].update({k: float(v) for k, v in m["ctrl"].items() if k in state["ctrl"]})
    task = asyncio.create_task(rx())
    try:
        while True:
            await ws.send(json.dumps(snapshot()))
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
        await asyncio.sleep(max(0, nxt - time.perf_counter()))

def http_server():
    os.chdir(WEB)
    ThreadingHTTPServer(("127.0.0.1", HTTP_PORT), SimpleHTTPRequestHandler).serve_forever()

async def main():
    threading.Thread(target=http_server, daemon=True).start()
    async with serve(handler, "127.0.0.1", WS_PORT):
        print(f"sim: open http://127.0.0.1:{HTTP_PORT}/  (ws {WS_PORT}, chair UDP {CHAIR_UDP})", flush=True)
        await physics()

if __name__ == "__main__":
    asyncio.run(main())
