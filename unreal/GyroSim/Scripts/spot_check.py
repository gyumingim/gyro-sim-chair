"""Busan start picker check (developer use): server started with  python sim/server.py --start rkpk --free-flight  in the
'vworld' ground mode, editor launched with  -GyroSimPlay -GyroSimSpot -RenderOffscreen  (init_unreal.py).

  1. Play comes from the -GyroSimPlay autoplay; the picker must be open (packet 'spot') and shown on the plate, sim paused.
  2. shot of the picker; the mouse mapping (plate_uv) is checked by projecting known picture points to the screen and back.
  3. every preset: picker 'sel' + 'go' (the same commands the keys send), pause, shot of the start view, and the packet /
     aircraft actor position compared with the preset (lat / lon / alt / heading); then the picker is opened again.
  4. a point clicked on the map (picker 'click' u / v, as the mouse sends it) -> start there.
  5. picker opened from the menu (cancel allowed) -> cancel puts the aircraft back where it was.
Any window of this process is kept off the desktop without activating it. Shots + result go OUTSIDE git (V-World photo):
GYROSIM_SHOTS_DIR, default C:/GyroSimTiles/shots/spot. Quits the editor when done (GYROSIM_SPOT_QUIT=0 keeps it).
"""
import ctypes, json, math, os, sys, time
import ctypes.wintypes as W
import unreal
import sim_client

log = lambda *a: unreal.log("[spot_check] " + " ".join(str(x) for x in a))
ues = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem)
les = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
OUT = os.environ.get("GYROSIM_SHOTS_DIR", r"C:\GyroSimTiles\shots\spot")
os.makedirs(OUT, exist_ok=True)
REPO = os.path.normpath(os.path.join(unreal.Paths.convert_relative_path_to_full(unreal.Paths.project_dir()), "..", ".."))
sys.path.insert(0, os.path.join(REPO, "sim"))
import start_spots as SS                      # noqa: E402  (presets / layout only; the server owns the state)
C = sim_client.client
SAY = lambda m: C()._send(m)
RES = os.environ.get("GYROSIM_SHOT_RES", "1280x720")
CUSTOM_LL = (35.1900, 129.1000)               # map click test point (north of Hwangnyeongsan)
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


def dist_m(lat1, lon1, lat2, lon2):
    return math.hypot((lat2 - lat1) * 110950.0, (lon2 - lon1) * 111320.0 * math.cos(math.radians(lat1)))


def shot(name):
    fn = os.path.join(OUT, name + ".png").replace("\\", "/")
    unreal.SystemLibrary.execute_console_command(ues.get_game_world(), "HighResShot %s filename=%s" % (RES, fn))
    ST["shots"].append(fn)
    return fn


def loaded(c, el, lo=6.0, hi=45.0):
    p1, p2 = progress(c.tileset), progress(getattr(c, "buildings", None))
    return (p1 is not None and p1 >= 99.9 and (p2 is None or p2 >= 99.9) and el > lo) or el > hi


def uv_roundtrip(c):
    """project picture points (u, v) of the picker plate to the screen, back through plate_uv -> max error."""
    pc = unreal.GameplayStatics.get_player_controller(c.world, 0)
    a = c.mm["actor"]
    w, h = c.spot_cm
    P, fx, ry = a.get_actor_location(), a.get_actor_forward_vector(), a.get_actor_right_vector()
    errs = []
    for u, v in ((0.5, 0.5), (0.2, 0.3), (0.8, 0.9), (0.66, 0.1)):
        wp = P + fx * ((u - 0.5) * w) + ry * ((v - 0.5) * h)
        r = unreal.GameplayStatics.project_world_to_screen(pc, wp, False)
        r = [x for x in (r if isinstance(r, (tuple, list)) else (r,)) if not isinstance(x, bool)]
        if not r:
            return None
        sxy = r[0]
        got = c.spot_uv(sxy.x, sxy.y)
        if got is None:
            return None
        errs.append(math.hypot(got[0] - u, got[1] - v))
    return round(max(errs), 5)


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
        ph = ST["phase"]
        sp = ((c.s or {}).get("spot") or {}) if c else {}
        if ph == "wait_play":
            if ues.get_game_world() is not None:
                ST["autoplay_s"] = round(now - ST["t0"], 1)
                ST.update(phase="wait_picker", t=now)
            elif el > 240:
                log("autoplay did not start Play in 240 s")
                ST.update(phase="end", t=now)
        elif ph == "wait_picker":                   # picker open + shown, sim paused, ground loaded
            if c and c.aircraft is not None and sp.get("open") and getattr(c, "spot_shown", False) and loaded(c, el, 10.0, 90.0):
                s = c.s
                ST["res"]["picker"] = dict(open=sp.get("open"), shown=c.spot_shown, paused=s.get("paused"), key=sp.get("key"),
                                           spot=sp.get("spot"), plate_cm=[round(x, 1) for x in c.spot_cm], uv_err=uv_roundtrip(c),
                                           startup=c.start.get("phase"), t_s=round(now - ST["t0"], 1))
                ST["t_sim0"] = s.get("t")
                log("picker", json.dumps(ST["res"]["picker"], ensure_ascii=False, default=str))
                ST.update(phase="picker_shot", t=now)
            elif el > 150:
                log("picker not shown after 150 s", sp, getattr(c, "spot_shown", None))
                ST["res"]["picker"] = dict(open=sp.get("open"), shown=getattr(c, "spot_shown", None), fail="not shown")
                ST.update(phase="end", t=now)
        elif ph == "picker_shot" and el > 2.0:
            ST["res"]["picker"]["paused_still"] = bool(c.s.get("paused")) and c.s.get("t") == ST["t_sim0"]
            shot("spot_00_picker")
            try:
                vp = unreal.WidgetLayoutLibrary.get_viewport_size(c.world)
                ST["res"]["picker"]["viewport"] = [round(vp.x), round(vp.y)]
            except Exception:
                pass
            ST.update(phase="end" if os.environ.get("GYROSIM_SPOT_PICKER_ONLY") == "1" else "setup", t=now)
        elif ph == "setup" and el > 1.5:
            n = len(SS.PRESETS)
            if ST["i"] > n:
                ST.update(phase="cancel_open", t=now)
                return
            if not sp.get("open"):
                SAY({"cmd": "spot", "op": "open", "cancel": False})
                return
            if ST["i"] < n:
                SAY({"cmd": "spot", "op": "sel", "i": ST["i"]})
            else:                                   # map click (as the mouse sends it)
                x, y = SS.Picker(render=False, last_file=os.devnull).to_px(*CUSTOM_LL)
                SAY({"cmd": "spot", "op": "click", "u": x / SS.W, "v": y / SS.H})
            ST.update(phase="pick_shot", t=now)
        elif ph == "pick_shot" and el > 1.2:        # picker with this selection (first two and the map click only)
            if ST["i"] in (0, 1, len(SS.PRESETS)):
                shot("spot_%02d_picker_sel" % (ST["i"] + 1))
            ST.update(phase="go", t=now)
        elif ph == "go" and el > 1.0:
            ST["go_rid"] = (c.s or {}).get("rid")
            SAY({"cmd": "spot", "op": "go"})
            ST.update(phase="hold", t=now)
        elif ph == "hold":
            s = c.s or {}
            if s.get("rid") != ST["go_rid"] and not sp.get("open"):
                SAY({"cmd": "pause", "on": True})
                ST["go_s"] = dict(lat=s["lat"], lon=s["lon"], alt_m=s["alt_m"], psi=s["psi"], kts=s.get("kts"), wow=s.get("wow"))
                c.set_view("cockpit")
                c.look_tgt = [0.0, 0.0]
                ST.update(phase="load", t=now)
            elif el > 10:
                log("go not taken", sp)
                ST["res"]["step%d" % ST["i"]] = dict(fail="go not taken")
                ST["i"] += 1
                ST.update(phase="setup", t=now)
        elif ph == "load" and loaded(c, el):
            ST["load_s"] = round(el, 1)
            ST.update(phase="shoot", t=now)
        elif ph == "shoot" and el > 2.0:
            i = ST["i"]
            n = len(SS.PRESETS)
            if i < n:
                key, name, lat, lon, alt, hdg = SS.PRESETS[i]
            else:
                key, name, (lat, lon), alt, hdg = "custom", "지도 클릭", CUSTOM_LL, None, None
            s = c.s or {}
            g = ST["go_s"]
            loc_exp, _ = c.to_world(s)
            loc = c.aircraft.get_actor_location()
            r = dict(key=key, name=name, load_s=ST.get("load_s"), go_lat=round(g["lat"], 5), go_lon=round(g["lon"], 5),
                     go_alt_m=round(g["alt_m"], 1), go_psi=round(g["psi"], 1), go_kts=round(g["kts"] or 0, 1), wow=g["wow"],
                     err_m=round(dist_m(lat, lon, g["lat"], g["lon"]), 1),
                     alt_err_m=None if alt is None or key == "gimhae" else round(g["alt_m"] - alt, 1),
                     hdg_err=None if hdg is None else round((g["psi"] - hdg + 180) % 360 - 180, 1),
                     actor_vs_packet_cm=round(math.sqrt((loc.x - loc_exp.x) ** 2 + (loc.y - loc_exp.y) ** 2 + (loc.z - loc_exp.z) ** 2), 1),
                     paused=s.get("paused"), view=c.view)
            r["shot"] = shot("spot_%02d_%s" % (i + 1, key))
            ST["res"]["step%d" % i] = r
            log(key, json.dumps(r, ensure_ascii=False, default=str))
            ST["i"] += 1
            ST.update(phase="setup", t=now)
        # ---- picker from the menu, then cancel: the aircraft goes back --------------------------------------------------
        elif ph == "cancel_open" and el > 1.0:
            s = c.s or {}
            ST["before"] = dict(lat=s["lat"], lon=s["lon"], alt_m=s["alt_m"])
            SAY({"cmd": "spot", "op": "open", "cancel": True})
            ST.update(phase="cancel_sel", t=now)
        elif ph == "cancel_sel" and el > 1.0:
            SAY({"cmd": "spot", "op": "sel", "i": 6})          # another place -> previewed there after 0.5 s
            ST.update(phase="cancel_go", t=now)
        elif ph == "cancel_go" and el > 2.5:
            s = c.s or {}
            ST["previewed"] = dict(lat=s["lat"], lon=s["lon"], alt_m=s["alt_m"], paused=s.get("paused"))
            SAY({"cmd": "spot", "op": "cancel"})
            SAY({"cmd": "pause", "on": True})               # free flight here (no menu behind it): hold it to measure
            ST.update(phase="cancel_check", t=now)
        elif ph == "cancel_check" and el > 1.5:
            s, b, p = c.s or {}, ST["before"], ST["previewed"]
            ST["res"]["cancel"] = dict(preview_moved_m=round(dist_m(b["lat"], b["lon"], p["lat"], p["lon"])), preview_paused=p["paused"],
                                       back_err_m=round(dist_m(b["lat"], b["lon"], s["lat"], s["lon"]), 1),
                                       back_alt_err_m=round(s["alt_m"] - b["alt_m"], 1), open_after=sp.get("open"))
            log("cancel", ST["res"]["cancel"])
            ST.update(phase="end", t=now)
        elif ph == "end" and el > 2.0:
            n = len(SS.PRESETS)
            steps = [ST["res"].get("step%d" % i) or {} for i in range(n + 1)]
            pk, cn = ST["res"].get("picker") or {}, ST["res"].get("cancel") or {}
            if os.environ.get("GYROSIM_SPOT_PICKER_ONLY") == "1":
                steps = []
            ok_steps = all(not v.get("fail") and v.get("err_m") is not None and v["err_m"] < 60 and v["actor_vs_packet_cm"] < 50
                           and (v["alt_err_m"] is None or abs(v["alt_err_m"]) < 15) and (v["hdg_err"] is None or abs(v["hdg_err"]) < 3)
                           for v in steps)
            gim = steps[[p[0] for p in SS.PRESETS].index("gimhae")] if steps else {"wow": True}
            res = dict(made=time.strftime("%Y-%m-%d %H:%M:%S"), seconds=round(now - ST["t0"]), autoplay_s=ST.get("autoplay_s"),
                       ground=getattr(c, "cesium_mode", None) if c else None, windows_moved=ST.get("windows_moved", 0),
                       picker=pk, cancel=cn, steps=steps, shots=ST["shots"],
                       ok=bool(pk.get("open") and pk.get("shown") and pk.get("paused") and pk.get("paused_still")
                               and pk.get("uv_err") is not None and pk["uv_err"] < 0.01 and ok_steps and gim.get("wow")
                               and (not steps or (cn.get("preview_moved_m", 0) > 1000 and cn.get("back_err_m", 1e9) < 60 and not cn.get("open_after")))))
            with open(os.path.join(OUT, "spot_result%s.json" % ("_picker" if os.environ.get("GYROSIM_SPOT_PICKER_ONLY") == "1" else "")), "w", encoding="utf-8") as f:
                json.dump(res, f, indent=1, ensure_ascii=False, default=str)
            log("done ok=%s ->" % res["ok"], OUT)
            les.editor_request_end_play()
            ST.update(phase="quit", t=now)
        elif ph == "quit" and el > 3.0:
            unreal.unregister_slate_post_tick_callback(ST["h"])
            if os.environ.get("GYROSIM_SPOT_QUIT", "1") == "1":
                unreal.SystemLibrary.quit_editor()
    except Exception as e:
        import traceback
        log("error", repr(e), " | ".join(traceback.format_exc().splitlines()))
        ST.update(phase="quit" if ST["phase"] in ("end", "quit") else "end", t=time.monotonic())


if C() is None:
    sim_client.start()
ST["h"] = unreal.register_slate_post_tick_callback(tick)
log("scheduled", len(SS.PRESETS), "presets + map click + cancel ->", OUT)
