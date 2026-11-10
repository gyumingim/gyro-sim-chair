"""Cockpit v2 check shots + GPU (developer use). Needs the sim server (Busan start, muted) and a SECOND editor that is
never visible, holding C:/GyroSimTiles/ue_offscreen.lock:
    UnrealEditor.exe GyroSim.uproject /Game/Maps/FlightMap -RenderOffscreen -nosound -nosplash -ABSLOG=<log>
        -ExecCmds="py <repo>/unreal/GyroSim/Scripts/cockpit_blender/ck2_shots.py"
(env GYROSIM_FULLSCREEN=0, GYROSIM_CK2SHOT_LOG=<same log> for the GPU numbers). Starts Play, keeps this process's
windows off the desktop without activation, and per spot (paused, same pose) shoots the pilot-eye view with the v1
cockpit and with v2 (cockpit_v2.set_mode), plus close-ups (front panel, left / right console) at Haeundae, then GPU
(startfpschart, screen percentage scaled to 1080p pixels) for v1 / v2 in the cockpit view. Quits when done.
Out: GYROSIM_SHOTS_DIR (default C:/GyroSimTiles/shots/cockpit2) + shots.json.
"""
import ctypes, json, math, os, re, time
import ctypes.wintypes as W
import unreal
import sim_client
import cockpit_v2

log = lambda *a: unreal.log("[ck2shots] " + " ".join(str(x) for x in a))
ues = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem)
les = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
OUT = os.environ.get("GYROSIM_SHOTS_DIR", r"C:\GyroSimTiles\shots\cockpit2")
os.makedirs(OUT, exist_ok=True)
RES = os.environ.get("GYROSIM_SHOT_RES", "1600x900")
LOGF = os.environ.get("GYROSIM_CK2SHOT_LOG", "")
ONLY = os.environ.get("GYROSIM_CK2SHOT_ONLY", "")          # "v2" = skip the v1 shots / GPU (iteration rounds)
C = sim_client.client
SAY = lambda m: C()._send(m)
CRUISE = {"ail": 0.0, "elev": 0.0, "rud": 0.0, "brk_l": 0.0, "brk_r": 0.0, "thr": 0.75, "gear": 0.0}
SPOTS = [("haeundae", dict(lat=35.1440, lon=129.1700, alt_m=350.0, hdg=340.0, kts=250.0)),
         ("gwangan", dict(lat=35.1180, lon=129.1120, alt_m=250.0, hdg=20.0, kts=250.0))]
# close-ups: (name, look pitch, look yaw, fov)
CLOSE = [("panel", -24.0, 0.0, 52.0), ("left", -48.0, -52.0, 62.0), ("right", -48.0, 52.0, 62.0)]
ST = dict(t=time.monotonic(), t0=time.monotonic(), phase="wait_editor", h=None, res={}, gpu=[], q=[])
U32 = ctypes.windll.user32
PID = os.getpid()
SWP = 0x0001 | 0x0004 | 0x0010
EnumProc = ctypes.WINFUNCTYPE(ctypes.c_bool, W.HWND, W.LPARAM)


def hide_windows():
    def cb(h, l):
        p = ctypes.c_ulong()
        U32.GetWindowThreadProcessId(h, ctypes.byref(p))
        if p.value == PID and U32.IsWindowVisible(h):
            r = W.RECT()
            U32.GetWindowRect(h, ctypes.byref(r))
            if r.left > -20000:
                if U32.IsZoomed(h) or U32.IsIconic(h):
                    U32.ShowWindow(h, 4)
                U32.SetWindowPos(h, 0, -32000, -32000, 0, 0, SWP)
        return True
    U32.EnumWindows(EnumProc(cb), 0)


def cmd(c):
    unreal.SystemLibrary.execute_console_command(ues.get_game_world(), c)


def progress(ts):
    try:
        return round(float(ts.get_editor_property("load_progress")), 1) if ts else None
    except Exception:
        return None


def gpu_from_log():
    try:
        with open(LOGF, encoding="utf-8", errors="ignore") as f:
            txt = f.read()[-400000:]
        g = re.findall(r"Average GPU frametime: ([\d.]+) ms", txt)
        return float(g[-1]) if g else None
    except OSError:
        return None


def plan():
    sts = ("v2",) if ONLY == "v2" else ("v2", "v1")
    q = []
    if os.environ.get("GYROSIM_CK2SHOT_DEBUG"):        # buffer views of the v2 panel (material debugging)
        q.append(("place",) + SPOTS[0])
        for b in ("BaseColor", "Roughness", "Metallic", "WorldNormal", "AmbientOcclusion"):
            q.append(("state", "v2", -24.0, 0.0, 52.0)); q.append(("buf", b)); q.append(("shot", "dbg_%s" % b))
        q.append(("buf", None))
        return q
    # all v2 shots first, then v1: Lumen keeps a stale surface cache for a while after a mesh swap
    for st in sts:
        for name, spec in SPOTS:
            q.append(("place", name, spec))
            q.append(("state", st, 0.0, 0.0, 75.0)); q.append(("shot", "%s_eye_%s" % (name, st)))
            if name == "haeundae":
                for cn, p, y, fov in CLOSE:
                    q.append(("state", st, p, y, fov)); q.append(("shot", "%s_%s_%s" % (name, cn, st)))
                if LOGF:
                    q.append(("state", st, 0.0, 0.0, 75.0)); q.append(("gpu", "cockpit_%s" % st))
    return q


def set_fov(c, fov):
    try:
        c.view_cam.camera_component.set_field_of_view(fov)
    except Exception as e:
        log("fov", repr(e))


def tick(dt):
    try:
        now = time.monotonic()
        if now - ST.get("hide_t", 0) > 0.25:
            ST["hide_t"] = now
            hide_windows()
        el = now - ST["t"]
        c = C()
        if c is not None:
            c.max_tries = 0
            c.fs_auto_t = None
        ph = ST["phase"]
        if ph == "wait_editor" and el > float(os.environ.get("GYROSIM_CK2SHOT_WAIT", "20")):
            les.editor_request_begin_play()
            ST.update(phase="wait_world", t=now)
        elif ph == "wait_world":
            if c and c.aircraft is not None and c.s is not None and getattr(c, "startup_done", True) and el > 5.0:
                SAY({"cmd": "tut", "op": "stop"})
                cmd("t.MaxFPS 0"); cmd("r.VSync 0"); cmd("t.FPSChart.OpenFolderOnDump 0")
                ST.update(phase="next", t=now, q=plan())
                log("cockpit v2 on:", cockpit_v2.is_on())
            elif el > 180:
                log("no game world / packets after 180 s"); ST.update(phase="end", t=now)
        elif ph == "next" and el > 0.5:
            if not ST["q"]:
                ST.update(phase="end", t=now); return
            step = ST["q"].pop(0)
            ST["step"] = step
            k = step[0]
            if k == "place":
                SAY({"cmd": "tut", "op": "free"})
                SAY(dict(step[2], cmd="place"))
                SAY({"cmd": "pause", "on": True})
                c.override = dict(CRUISE)
                ST.update(phase="load", t=now, spec=step[2], resent=0)
            elif k == "state":
                _, st, p, y, fov = step
                cockpit_v2.set_mode(st == "v2")
                c.override = dict(CRUISE)
                if c.view != "cockpit":
                    c.set_view("cockpit")
                c.look_tgt = [p, y]
                set_fov(c, fov)
                ST.update(phase="settle", t=now, fov=fov)
            elif k == "shot":
                set_fov(c, ST.get("fov", 75.0))
                fn = os.path.join(OUT, step[1] + ".png").replace("\\", "/")
                if os.path.exists(fn):
                    os.remove(fn)
                cmd("HighResShot %s filename=%s" % (RES, fn))
                s = c.s or {}
                ST["res"][step[1]] = dict(file=fn, view=c.view, v2=cockpit_v2.is_on(), look=list(c.look), fov=ST.get("fov"), lat=s.get("lat"), lon=s.get("lon"),
                                          alt_m=s.get("alt_m"), psi=s.get("psi"), load=ST.get("load"))
                log("shot", fn)
                ST.update(phase="wait_file", t=now, file=fn)
            elif k == "buf":
                if step[1]:
                    cmd("r.BufferVisualizationTarget %s" % step[1]); cmd("ShowFlag.VisualizeBuffer 1")
                else:
                    cmd("ShowFlag.VisualizeBuffer 0")
                ST.update(phase="settle", t=now)
            elif k == "gpu":
                vp = unreal.WidgetLayoutLibrary.get_viewport_size(ues.get_game_world())
                sp = max(25.0, min(400.0, 100.0 * math.sqrt(1920 * 1080 / max(1.0, vp.x * vp.y))))
                ST["sp"] = (round(vp.x), round(vp.y), round(sp))
                cmd("r.ScreenPercentage %.0f" % sp)
                ST.update(phase="gpu_start", t=now)
        elif ph == "load":
            sp, s_ = ST.get("spec") or {}, c.s or {}
            if sp and el > 6.0 + 6.0 * ST.get("resent", 0) and ST.get("resent", 0) < 5 and abs(float(s_.get("lat", 0.0) or 0.0) - sp["lat"]) > 0.01:
                SAY({"cmd": "tut", "op": "free"}); SAY(dict(sp, cmd="place")); SAY({"cmd": "pause", "on": True})   # server was not ready
                ST["resent"] = ST.get("resent", 0) + 1
                log("place resent", ST["resent"], s_.get("lat"), s_.get("lon"))
                return
            p1, p2 = progress(getattr(c, "tileset", None)), progress(getattr(c, "buildings", None))
            if (p1 is not None and p1 >= 99.9 and (p2 is None or p2 >= 99.9) and el > 10.0) or el > 90.0:
                ST["load"] = dict(load_s=round(el, 1), terrain=p1, buildings=p2)
                ST.update(phase="next", t=now)
        elif ph == "wait_file":
            if os.path.exists(ST["file"]) or el > 30.0:
                if el > 30.0:
                    log("shot file missing after 30 s", ST["file"])
                ST.update(phase="next", t=now)
        elif ph == "settle" and el > 4.0:
            ST.update(phase="next", t=now)
        elif ph == "gpu_start" and el > 4.0:
            cmd("startfpschart")
            ST.update(phase="gpu_run", t=now, dts=[])
        elif ph == "gpu_run":
            ST["dts"].append(dt)
            if el > 10.0:
                cmd("stopfpschart")
                ST.update(phase="gpu_collect", t=now)
        elif ph == "gpu_collect" and el > 2.0:
            d = sorted(ST["dts"][5:])
            r = dict(label=ST["step"][1], gpu_ms=gpu_from_log(), viewport=ST["sp"][:2], screen_percentage=ST["sp"][2], frames=len(d),
                     avg_ms=round(sum(d) / len(d) * 1000, 2) if d else None)
            ST["gpu"].append(r)
            log("gpu", json.dumps(r))
            cmd("r.ScreenPercentage 100")
            ST.update(phase="next", t=now)
        elif ph == "end" and el > 2.0:
            if c:
                c.override = None
            res = dict(made=time.strftime("%Y-%m-%d %H:%M:%S"), seconds=round(now - ST["t0"]), shots=ST["res"], gpu=ST["gpu"],
                       manifest=cockpit_v2.MAN_PATH, note="second off-screen editor, PIE, sim server Busan start paused per spot; v1 = old cockpit, "
                                                          "v2 = cockpit_v2 (same Play session, set_mode)")
            with open(os.path.join(OUT, "shots.json"), "w", encoding="utf-8") as f:
                json.dump(res, f, indent=1, ensure_ascii=False, default=str)
            log("done ->", OUT)
            les.editor_request_end_play()
            ST.update(phase="quit", t=now)
        elif ph == "quit" and el > 3.0:
            unreal.unregister_slate_post_tick_callback(ST["h"])
            unreal.SystemLibrary.quit_editor()
    except Exception as e:
        import traceback
        log("error", repr(e), " | ".join(traceback.format_exc().splitlines()))
        ST.update(phase="quit" if ST["phase"] in ("end", "quit") else "end", t=time.monotonic())


if C() is None:
    sim_client.start()
ST["h"] = unreal.register_slate_post_tick_callback(tick)
log("scheduled ->", OUT)
