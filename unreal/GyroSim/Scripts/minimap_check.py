"""Busan minimap check (developer use): server started with  python sim/server.py --start rkpk  in the 'vworld' ground
mode, editor launched with  -GyroSimPlay -GyroSimMinimap -RenderOffscreen  (init_unreal.py). Play is started by the
-GyroSimPlay autoplay (that is part of what is checked), then the aircraft is put at a few Busan points and a shot is
taken at each; the minimap marker position (sim_client status 'minimap') is compared with the one computed here from the
packet lat / lon. Any window of this process is kept off the desktop without activating it (in case -RenderOffscreen
still makes one). Shots and result go OUTSIDE git (V-World photo): GYROSIM_SHOTS_DIR, default C:/GyroSimTiles/shots/minimap.
Quits the editor when done.
"""
import ctypes, json, math, os, time
import ctypes.wintypes as W
import unreal
import sim_client

log = lambda *a: unreal.log("[minimap_check] " + " ".join(str(x) for x in a))
ues = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem)
les = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
OUT = os.environ.get("GYROSIM_SHOTS_DIR", r"C:\GyroSimTiles\shots\minimap")
os.makedirs(OUT, exist_ok=True)
C = sim_client.client
SAY = lambda m: C()._send(m)
HOLD = {"ail": 0.0, "elev": 0.0, "rud": 0.0, "brk_l": 1.0, "brk_r": 1.0, "thr": 0.0}
CRUISE = dict(HOLD, brk_l=0.0, brk_r=0.0, thr=0.75)
# (name, start, view, orbit [yaw, el, dist cm] or None)
SHOTS = [("mm_1_gimhae_runway_cockpit", "runway", "cockpit", None),
         ("mm_2_station_300m_cockpit", dict(lat=35.1000, lon=129.0480, alt_m=300.0, hdg=12.0, kts=250.0), "cockpit", None),
         ("mm_3_haeundae_chase", dict(lat=35.1440, lon=129.1700, alt_m=350.0, hdg=340.0, kts=250.0), "chase", None),
         ("mm_4_gijang_north_cockpit", dict(lat=35.2600, lon=129.2000, alt_m=600.0, hdg=200.0, kts=250.0), "cockpit", None),
         # top-down over Sasang (not filled before 11-09: z16 blur then) - z19 photo detail now
         ("mm_5_sasang_top", dict(lat=35.1526, lon=128.9910, alt_m=250.0, hdg=0.0, kts=250.0), "orbit", [0.0, 85.0, 12000.0])]
ST = dict(t=time.monotonic(), t0=time.monotonic(), phase="wait_play", i=0, h=None, res={}, shots=[], fg=None)

U32 = ctypes.windll.user32
PID = os.getpid()
SWP = 0x0001 | 0x0004 | 0x0010            # NOSIZE | NOZORDER | NOACTIVATE
EnumProc = ctypes.WINFUNCTYPE(ctypes.c_bool, W.HWND, W.LPARAM)


def _ours(h):
    p = ctypes.c_ulong()
    U32.GetWindowThreadProcessId(h, ctypes.byref(p))
    return p.value == PID


def hide_windows():
    found = []

    def cb(h, l):
        if _ours(h) and U32.IsWindowVisible(h):
            r = W.RECT()
            U32.GetWindowRect(h, ctypes.byref(r))
            if r.left > -20000:
                if U32.IsZoomed(h) or U32.IsIconic(h):
                    U32.ShowWindow(h, 4)             # SW_SHOWNOACTIVATE
                U32.SetWindowPos(h, 0, -32000 + 40 * len(found), -32000, 0, 0, SWP)
                found.append(h)
        return True
    U32.EnumWindows(EnumProc(cb), 0)
    fg = U32.GetForegroundWindow()
    if fg and not _ours(fg):
        ST["fg"] = fg
    elif fg and ST["fg"] and U32.IsWindow(ST["fg"]):
        U32.SetForegroundWindow(ST["fg"])
    ST["windows_moved"] = ST.get("windows_moved", 0) + len(found)
    return len(found)


def progress(ts):
    try:
        return round(float(ts.get_editor_property("load_progress")), 1) if ts else None
    except Exception:
        return None


def expected_uv(c, lat, lon):
    x0, y0, x1, y1 = c.mm["merc"]
    sl = math.sin(math.radians(lat))
    mx, my = (lon + 180.0) / 360.0, 0.5 - math.log((1 + sl) / (1 - sl)) / (4 * math.pi)
    return (mx - x0) / (x1 - x0), (my - y0) / (y1 - y0)


def tick(dt):
    try:
        now = time.monotonic()
        if now - ST.get("hide_t", 0) > 0.25:
            ST["hide_t"] = now
            hide_windows()
        el = now - ST["t"]
        c = C()
        if c is not None:
            c.max_tries = 0                         # no PIE maximize
        ph = ST["phase"]
        if ph == "wait_play":                       # Play must come from the -GyroSimPlay autoplay
            if ues.get_game_world() is not None:
                ST["autoplay_s"] = round(now - ST["t0"], 1)
                ST.update(phase="wait_world", t=now)
            elif el > 240:
                log("autoplay did not start Play in 240 s")
                ST.update(phase="end", t=now)
        elif ph == "wait_world":
            if c and c.aircraft is not None and c.s is not None and c.startup_done:
                SAY({"cmd": "tut", "op": "stop"})
                ST.update(phase="setup", t=now)
            elif el > 120:
                log("no game world / packets after 120 s")
                ST.update(phase="end", t=now)
        elif ph == "setup" and el > 1.0:
            if ST["i"] >= len(SHOTS):
                ST.update(phase="end", t=now)
                return
            name, spec, view, orb = SHOTS[ST["i"]]
            SAY({"cmd": "tut", "op": "free"})
            SAY(dict(spec, cmd="place") if isinstance(spec, dict) else {"cmd": "reset", "mode": spec})
            SAY({"cmd": "pause", "on": True})
            c.override = dict(HOLD if spec == "runway" else CRUISE)
            c.set_view(view)
            c.look_tgt = [0.0, 0.0]
            if orb is not None:
                c.orbit[view] = list(orb)
            ST.update(phase="load", t=now)
        elif ph == "load":
            p1, p2 = progress(c.tileset), progress(getattr(c, "buildings", None))
            if (p1 is not None and p1 >= 99.9 and (p2 is None or p2 >= 99.9) and el > 8.0) or el > 75.0:
                ST["load"] = dict(load_s=round(el, 1), terrain_progress=p1, buildings_progress=p2)
                ST.update(phase="shoot", t=now)
        elif ph == "shoot" and el > 2.0:
            name = SHOTS[ST["i"]][0]
            fn = os.path.join(OUT, name + ".png").replace("\\", "/")
            unreal.SystemLibrary.execute_console_command(ues.get_game_world(), "HighResShot %s filename=%s" % (os.environ.get("GYROSIM_SHOT_RES", "1920x1080"), fn))
            ST["shots"].append(fn)
            s = c.s or {}
            mm = getattr(c, "mm", None) or {}
            exp = expected_uv(c, s["lat"], s["lon"]) if mm.get("ok") and "lat" in s else None
            got = mm.get("pos")
            r = ST["res"].setdefault(name, {})
            r.update(ST.pop("load", {}), view=c.view, lat=s.get("lat"), lon=s.get("lon"), alt_m=round(s.get("alt_m", 0), 1),
                     psi=round(s.get("psi", 0), 1), apt=s.get("apt"), minimap_ok=mm.get("ok"), minimap_shown=mm.get("shown"),
                     minimap_uv_psi=got, expected_uv=[round(x, 4) for x in exp] if exp else None,
                     uv_err=round(math.hypot(got[0] - exp[0], got[1] - exp[1]), 4) if got and exp else None,
                     minimap_place_key_fov_aspect_hmd=mm.get("view"), actor_hidden=bool(mm["actor"].get_editor_property("hidden")) if mm.get("actor") else None)
            log(name, json.dumps(r, default=str))
            ST["i"] += 1
            ST.update(phase="setup", t=now)
        elif ph == "end" and el > 3.0:
            c = C()
            if c:
                c.override = None
                c.set_view("cockpit")
            steps = [v for v in ST["res"].values() if isinstance(v, dict)]
            uvs = [tuple(v["minimap_uv_psi"][:2]) for v in steps if v.get("minimap_uv_psi")]
            res = dict(made=time.strftime("%Y-%m-%d %H:%M:%S"), seconds=round(now - ST["t0"]), autoplay_s=ST.get("autoplay_s"),
                       ground=getattr(c, "cesium_mode", None) if c else None, windows_moved=ST.get("windows_moved", 0),
                       shots=ST["shots"], steps=ST["res"],
                       ok=bool(ST.get("autoplay_s") is not None and len(steps) == len(SHOTS)
                               and all(v.get("minimap_shown") and not v.get("actor_hidden") and v.get("uv_err") is not None and v["uv_err"] < 0.01 for v in steps)
                               and len(set(uvs)) == len(uvs)))
            with open(os.path.join(OUT, "minimap_result.json"), "w", encoding="utf-8") as f:
                json.dump(res, f, indent=1, ensure_ascii=False, default=str)
            log("done ok=%s ->" % res["ok"], OUT)
            les.editor_request_end_play()
            ST.update(phase="quit", t=now)
        elif ph == "quit" and el > 3.0:
            unreal.unregister_slate_post_tick_callback(ST["h"])
            if os.environ.get("GYROSIM_MINIMAP_QUIT", "1") == "1":
                unreal.SystemLibrary.quit_editor()
    except Exception as e:
        import traceback
        log("error", repr(e), " | ".join(traceback.format_exc().splitlines()))
        ST.update(phase="quit" if ST["phase"] in ("end", "quit") else "end", t=time.monotonic())


if C() is None:
    sim_client.start()
ST["h"] = unreal.register_slate_post_tick_callback(tick)
log("scheduled", len(SHOTS), "shots ->", OUT)
