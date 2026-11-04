"""Soak test against the running sim/server.py (WebSocket), default 1 hour:
    python sim/playtest/soak.py [--minutes 60] [--no-restart]
Cycles lessons 0..10 through the real server: briefing pages (N), the whole demo (autopilot moves the controls),
practice for ~25 s with random small stick inputs, then 'end' -> debrief -> menu; once per cycle also pause, the
R-twice lesson reset, menu navigation and repeat (Z). Halfway through, the server is killed and started again (same
command line) and the client must reconnect and find the menu (server restart / reconnect check).
Watches: packet rate, server memory (RSS), Python tracebacks in sim/out/server.err / server.log, stale panel images.
Voice is switched off for the run and restored at the end. Writes sim/playtest/logs/soak.json (+ prints a summary).
"""
import argparse, asyncio, json, os, random, subprocess, sys, time
import psutil
import websockets

HERE = os.path.dirname(os.path.abspath(__file__))
SIM = os.path.dirname(HERE)
URL = "ws://127.0.0.1:8781"
OUT = os.path.join(HERE, "logs", "soak.json")
ERR = [os.path.join(SIM, "out", "server.err"), os.path.join(SIM, "out", "server.log")]


def server_proc():
    for p in psutil.process_iter(["pid", "cmdline"]):
        cl = p.info.get("cmdline") or []
        if any(c.endswith("server.py") for c in cl) and any("python" in c.lower() for c in cl[:1]):
            return p
    return None


def tracebacks():
    n = 0
    for f in ERR:
        try:
            n += open(f, encoding="utf-8", errors="ignore").read().count("Traceback")
        except OSError:
            pass
    return n


def restart_server():
    p = server_proc()
    if p:
        p.kill()
        p.wait(10)
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    log = open(os.path.join(SIM, "out", "server.log"), "a", encoding="utf-8")
    err = open(os.path.join(SIM, "out", "server.err"), "a", encoding="utf-8")
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(subprocess, "DETACHED_PROCESS", 0)
    subprocess.Popen([sys.executable, "server.py"], cwd=SIM, stdout=log, stderr=err, env=env, creationflags=flags)


class Client:
    def __init__(self):
        self.ws, self.S, self.n = None, {}, 0

    async def connect(self, timeout=40):
        t0 = time.monotonic()
        while time.monotonic() - t0 < timeout:
            try:
                self.ws = await websockets.connect(URL, max_size=2 ** 22)
                await self.pump(0.5)
                return time.monotonic() - t0
            except (OSError, websockets.exceptions.WebSocketException):
                await asyncio.sleep(0.5)
        raise RuntimeError("server did not come back")

    async def pump(self, sec, ctrl=None):
        t0 = time.monotonic()
        while time.monotonic() - t0 < sec:
            if ctrl is not None:
                await self.ws.send(json.dumps({"ctrl": ctrl}))
            try:
                self.S.update(json.loads(await asyncio.wait_for(self.ws.recv(), 0.5)))
                self.n += 1
            except asyncio.TimeoutError:
                continue

    async def cmd(self, m, wait=0.3):
        await self.ws.send(json.dumps(m))
        await self.pump(wait)

    def T(self):
        return self.S.get("tut") or {}


async def lesson(c, i, log):
    await c.cmd({"cmd": "tut", "op": "start", "lesson": i}, 0.5)
    k = 0
    while c.T().get("phase") == "brief" and k < 12:
        await c.cmd({"cmd": "tut", "op": "next"}, 0.4)
        k += 1
    t0 = time.monotonic()
    while c.T().get("phase") == "demo" and time.monotonic() - t0 < 150:       # let the demo fly to its end
        await c.pump(1.0)
    demo_s = time.monotonic() - t0
    ph = c.T().get("phase")
    t0 = time.monotonic()
    while time.monotonic() - t0 < 25 and c.T().get("phase") in ("practice", "crash"):
        if i in (0, 7):                                                     # on the runway: stand still on the brakes
            ctl = dict(ail=random.uniform(-0.3, 0.3), elev=random.uniform(-0.3, 0.3), rud=0.0, thr=0.0, brk_l=1, brk_r=1)
        else:
            ctl = dict(ail=random.uniform(-0.15, 0.15), elev=random.uniform(-0.1, 0.1), rud=0.0, thr=0.8, brk_l=0, brk_r=0)
        await c.pump(0.25, ctl)
    await c.cmd({"cmd": "tut", "op": "end"}, 0.8)
    deb = c.T().get("phase")
    log.append(dict(t=time.strftime("%H:%M:%S"), lesson=i, demo_s=round(demo_s, 1), after_demo=ph, end_phase=deb, img=c.T().get("img"), ver=c.T().get("ver")))
    if deb == "crash":                                                       # a crash is a valid outcome: retry must work
        log[-1]["crash"] = True
        await c.cmd({"cmd": "tut", "op": "retry"}, 0.8)
        log[-1]["after_retry"] = c.T().get("phase")
        return c.T().get("phase") in ("practice", "solo", "demo")
    return deb == "debrief"


async def extras(c):
    """pause, R twice during a lesson, menu navigation, repeat."""
    ok = {}
    await c.cmd({"cmd": "tut", "op": "free"}, 0.8)                           # free flight: only the user pause counts
    p0 = bool(c.S.get("paused"))
    await c.cmd({"cmd": "pause"}, 0.4)
    p1 = bool(c.S.get("paused"))
    await c.cmd({"cmd": "pause"}, 0.4)
    ok["pause_toggles"] = p1 != p0 and bool(c.S.get("paused")) == p0
    await c.cmd({"cmd": "tut", "op": "start", "lesson": 2}, 0.5)
    await c.cmd({"cmd": "reset", "mode": "air", "user": True}, 0.4)
    first = c.T().get("phase")
    await c.cmd({"cmd": "reset", "mode": "air", "user": True}, 0.6)
    ok["reset_needs_two"] = first == "brief" and c.T().get("phase") == "free"
    await c.cmd({"cmd": "tut", "op": "menu"}, 0.4)
    for op in ("down", "down", "up", "select", "back"):
        await c.cmd({"cmd": "menu", "op": op}, 0.3)
    ok["menu_nav"] = c.T().get("phase") == "menu"
    s0 = c.T().get("say_n", 0)
    await c.cmd({"cmd": "tut", "op": "repeat"}, 0.4)
    ok["repeat"] = c.T().get("say_n", 0) > s0
    return ok


async def main(minutes, restart):
    R = dict(made=time.strftime("%Y-%m-%d %H:%M:%S"), minutes=minutes, cycles=[], samples=[], lessons=[], restart=None, problems=[])
    c = Client()
    await c.connect()
    voice_was = bool(c.T().get("voice"))
    if voice_was:
        await c.cmd({"cmd": "voice", "op": "toggle"})
    tb0 = tracebacks()
    t_end = time.monotonic() + minutes * 60
    t_half = time.monotonic() + minutes * 30
    cyc = 0
    while time.monotonic() < t_end:
        cyc += 1
        res = dict(cycle=cyc, t=time.strftime("%H:%M:%S"), lessons_ok=0, lessons_bad=[])
        for i in range(11):
            if time.monotonic() >= t_end:
                break
            try:
                ok = await lesson(c, i, R["lessons"])
            except (websockets.exceptions.WebSocketException, OSError) as e:
                R["problems"].append("%s lesson %d connection: %r" % (time.strftime("%H:%M:%S"), i, e))
                await c.connect()
                continue
            res["lessons_ok" if ok else "lessons_bad"] = (res["lessons_ok"] + 1) if ok else res["lessons_bad"] + [i]
            p = server_proc()
            n0, t0 = c.n, time.monotonic()
            await c.pump(2.0)
            R["samples"].append(dict(t=time.strftime("%H:%M:%S"), rss_mb=round(p.memory_info().rss / 2 ** 20, 1) if p else None,
                                     hz=round((c.n - n0) / (time.monotonic() - t0), 1), tracebacks=tracebacks() - tb0))
            if restart and R["restart"] is None and time.monotonic() > t_half:
                t0 = time.monotonic()
                restart_server()
                try:
                    await c.ws.close()
                except Exception:
                    pass
                await asyncio.sleep(1.0)
                dt = await c.connect()
                await c.pump(1.5)
                R["restart"] = dict(t=time.strftime("%H:%M:%S"), reconnect_s=round(time.monotonic() - t0, 1), phase=c.T().get("phase"),
                                    ok=c.T().get("phase") == "menu" and bool(c.S))
                if c.T().get("voice"):
                    await c.cmd({"cmd": "voice", "op": "toggle"})
        res["extras"] = await extras(c)
        R["cycles"].append(res)
        print(json.dumps(res, ensure_ascii=False), flush=True)
        json.dump(R, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    await c.cmd({"cmd": "tut", "op": "stop"})
    if voice_was and not c.T().get("voice"):
        await c.cmd({"cmd": "voice", "op": "toggle"})
    rss = [s["rss_mb"] for s in R["samples"] if s["rss_mb"]]
    R["summary"] = dict(cycles=len(R["cycles"]), lessons=len(R["lessons"]), bad=sum(len(c_["lessons_bad"]) for c_ in R["cycles"]),
                        extras_ok=all(all(c_["extras"].values()) for c_ in R["cycles"]), crashes=sum(1 for x in R["lessons"] if x.get("crash")), rss_first=rss[0] if rss else None,
                        rss_last=rss[-1] if rss else None, rss_max=max(rss) if rss else None,
                        hz_min=min(s["hz"] for s in R["samples"]) if R["samples"] else None, tracebacks=tracebacks() - tb0,
                        restart_ok=(R["restart"] or {}).get("ok") if restart else None)
    R["finished"] = time.strftime("%Y-%m-%d %H:%M:%S")
    json.dump(R, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("SUMMARY", json.dumps(R["summary"]), flush=True)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--minutes", type=float, default=60)
    ap.add_argument("--no-restart", action="store_true")
    a = ap.parse_args()
    asyncio.run(main(a.minutes, not a.no_restart))
