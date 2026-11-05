"""Busan start check (developer use): server started with  python sim/server.py --start rkpk  in the 'vworld' ground mode,
editor launched with  -GyroSimBusan  (init_unreal.py). Off-screen: every editor / PIE window of this process is moved off
the desktop without activating it, and the previous foreground window gets focus back (the user may be working).

Shots (GYROSIM_SHOTS_DIR, default C:\\GyroSimTiles\\shots\\busan - outside git: the V-World photo of a joint-use air base
must not go into the public repo): RKPK 36L runway start in the cockpit (HUD) and from the side, a 300 m cockpit view from
Busan station toward Seomyeon, Haeundae from a chase view, a steep top-down orbit over Seomyeon (z19 photo detail and
building footprints). Result: busan_result.json (airfield sync, proxy tile sources and API count before / after).
"""
import ctypes, json, math, os, time
import ctypes.wintypes as W
import unreal
import sim_client

log = lambda *a: unreal.log("[busan] " + " ".join(str(x) for x in a))
les = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
ues = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem)
OUT = os.environ.get("GYROSIM_SHOTS_DIR", r"C:\GyroSimTiles\shots\busan")
os.makedirs(OUT, exist_ok=True)
C = sim_client.client
SAY = lambda m: C()._send(m)
HOLD = {"ail": 0.0, "elev": 0.0, "rud": 0.0, "brk_l": 1.0, "brk_r": 1.0, "thr": 0.0}
CRUISE = dict(HOLD, brk_l=0.0, brk_r=0.0, thr=0.75)
STATION_300 = dict(lat=35.1000, lon=129.0480, alt_m=300.0, hdg=12.0, kts=250.0)      # over 부산역 / port, toward 서면
HAEUNDAE = dict(lat=35.1440, lon=129.1700, alt_m=350.0, hdg=340.0, kts=250.0)        # over the sea, toward the beach towers
SEOMYEON = dict(lat=35.1578, lon=129.0600, alt_m=250.0, hdg=0.0, kts=250.0)
SUN_300 = dict(STATION_300, hdg=322.0)                                               # same spot, nose toward the sun (az ~322, 38 deg up)
# (name, start, view, orbit [yaw, el, dist cm] or None[, cockpit look [pitch, yaw] deg])
SHOTS = [("busan_rkpk_runway_cockpit", "runway", "cockpit", None),
         ("busan_rkpk_runway_side", "runway", "orbit", [90.0, 2.0, 6000.0]),
         ("busan_cockpit_300m_to_seomyeon", STATION_300, "cockpit", None),
         ("busan_cockpit_300m_sun", SUN_300, "cockpit", None, [20.0, 0.0]),     # sun glare / canopy reflection (realism v2)
         ("busan_haeundae_chase", HAEUNDAE, "chase", None),
         ("busan_seomyeon_top", SEOMYEON, "orbit", [0.0, 80.0, 45000.0]),
         ("busan_seomyeon_top_close", SEOMYEON, "orbit", [0.0, 85.0, 12000.0])]
if os.environ.get("GYROSIM_BUSAN_SHOTS"):
    SHOTS = [x for x in SHOTS if x[0] in os.environ["GYROSIM_BUSAN_SHOTS"].split(",")]
ST = dict(t=time.monotonic(), t0=time.monotonic(), phase="wait_pie", i=0, h=None, res={}, shots=[], start=None, fg=None)

# ---- keep every window of this process off the desktop, give focus back ---------------------------------------------
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
                    U32.ShowWindow(h, 4)             # SW_SHOWNOACTIVATE (restore, so it keeps rendering)
                U32.SetWindowPos(h, 0, -32000 + 40 * len(found), -32000, 0, 0, SWP)
                found.append(h)
        return True
    U32.EnumWindows(EnumProc(cb), 0)
    fg = U32.GetForegroundWindow()
    if fg and not _ours(fg):
        ST["fg"] = fg
    elif fg and ST["fg"] and U32.IsWindow(ST["fg"]):
        U32.SetForegroundWindow(ST["fg"])           # we are foreground now, so this is allowed
    return len(found)


def shot(name):
    fn = os.path.join(OUT, name + ".png").replace("\\", "/")
    unreal.SystemLibrary.execute_console_command(ues.get_game_world(), "HighResShot %s filename=%s" % (os.environ.get("GYROSIM_SHOT_RES", "1600x900"), fn))
    ST["shots"].append(fn)


def progress(ts):
    try:
        return round(float(ts.get_editor_property("load_progress")), 1) if ts else None
    except Exception:
        return None


def start(spec):
    SAY({"cmd": "tut", "op": "free"})
    if isinstance(spec, dict):
        SAY(dict(spec, cmd="place"))
    else:
        SAY({"cmd": "reset", "mode": spec})
    SAY({"cmd": "pause", "on": True})


def checks(c):
    s = c.s or {}
    fields = unreal.GameplayStatics.get_all_actors_with_tag(c.world, "Airfield") if c.world else []
    vis = []
    for a in fields:
        try:
            if not a.get_editor_property("hidden"):
                vis.append(str(a.get_actor_label()))
        except Exception as e:
            vis.append("? " + repr(e)[:60])
    gr = c.georef
    org = None
    try:
        o = gr.get_editor_property("origin_latitude"), gr.get_editor_property("origin_longitude"), gr.get_editor_property("origin_height")
        org = [round(float(v), 7) for v in o]
    except Exception as e:
        org = repr(e)
    return dict(apt=s.get("apt"), lat0=s.get("lat0"), lon0=s.get("lon0"), geoid_n=s.get("geoid_n"), field_m=s.get("field_m"),
                georef_origin=org, airfield_actors=len(fields), shown=vis, ground=c.cesium_mode, vw_local=getattr(c, "vw_local", None),
                vw_bldg=getattr(c, "vw_bldg", None), server_terrain=s.get("terrain"), proxy=c.vworld_status(1.0))


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
        if ph == "wait_pie":
            if el > float(os.environ.get("GYROSIM_VWORLD_WAIT", "45")):
                les.editor_request_begin_play()
                ST.update(phase="wait_world", t=now)
        elif ph == "wait_world":
            if ues.get_game_world() is not None and c and c.aircraft is not None and c.s is not None and c.startup_done:
                SAY({"cmd": "tut", "op": "stop"})
                ST["res"]["setup"] = checks(c)
                ST["proxy_before"] = ST["res"]["setup"].get("proxy")
                log("setup", json.dumps(ST["res"]["setup"], default=str))
                ST.update(phase="setup", t=now)
            elif el > 120:
                log("no game world / packets after 120 s")
                ST.update(phase="end", t=now)
        elif ph == "setup" and el > 1.0:
            if ST["i"] >= len(SHOTS):
                ST.update(phase="end", t=now)
                return
            name, spec, view, orb = SHOTS[ST["i"]][:4]
            key = spec if not isinstance(spec, dict) else json.dumps(spec, sort_keys=True)
            if ST["start"] != key:
                start(spec)
                ST["start"] = key
            c.override = dict(HOLD if spec == "runway" else CRUISE)
            c.set_view(view)
            c.look_tgt = list(SHOTS[ST["i"]][4]) if len(SHOTS[ST["i"]]) > 4 else [0.0, 0.0]
            if orb is not None:
                c.orbit[view] = list(orb)
            ST.update(phase="load", t=now)
        elif ph == "load":
            name, spec, view, orb = SHOTS[ST["i"]][:4]
            if orb is not None:
                c.orbit[view] = list(orb)
            p1, p2 = progress(c.tileset), progress(getattr(c, "buildings", None))
            if (p1 is not None and p1 >= 99.9 and (p2 is None or p2 >= 99.9) and el > 8.0) or el > 75.0:
                ST["load"] = dict(load_s=round(el, 1), terrain_progress=p1, buildings_progress=p2)
                ST.update(phase="shoot", t=now)
        elif ph == "shoot" and el > 2.0:
            name, spec, view, orb = SHOTS[ST["i"]][:4]
            shot(name)
            s = c.s or {}
            r = ST["res"].setdefault(name, {})
            r.update(ST.pop("load", {}), view=c.view, lat=s.get("lat"), lon=s.get("lon"), alt_m=round(s.get("alt_m", 0), 2),
                     terrain_m=s.get("terrain_m"), agl_m=round(s.get("agl_m", 0), 2), radar_m=None if c.radar_m is None else round(c.radar_m, 2),
                     wow=s.get("wow"), crashed=s.get("crashed"), psi=round(s.get("psi", 0), 1))
            if spec == "runway":
                r["runway_ok"] = bool(s.get("wow")) and not s.get("crashed") and abs(s.get("agl_m", 9) - 1.66) < 0.5
            log(name, json.dumps(r, default=str))
            ST["i"] += 1
            ST.update(phase="setup", t=now)
        elif ph == "end" and el > 3.0:
            c.override = None
            c.look_tgt = [0.0, 0.0]
            c.set_view("cockpit")
            SAY({"cmd": "tut", "op": "free"})
            r = checks(c)
            pb, pa = ST.get("proxy_before") or {}, r.get("proxy") or {}
            res = dict(made=time.strftime("%Y-%m-%d %H:%M:%S"), seconds=round(now - ST["t0"]), checks=r, shots=ST["shots"], steps=ST["res"],
                       api_requests_this_check=(pa.get("used_today", 0) - pb.get("used_today", 0)) if pa and pb else None,
                       ok=bool(r.get("apt") == "rkpk" and r.get("ground") == "vworld" and all(v.get("runway_ok", True) for v in ST["res"].values() if isinstance(v, dict))))
            with open(os.path.join(OUT, "busan_result.json"), "w", encoding="utf-8") as f:
                json.dump(res, f, indent=1, ensure_ascii=False, default=str)
            log("done ok=%s ->" % res["ok"], OUT)
            les.editor_request_end_play()
            ST.update(phase="quit", t=now)
        elif ph == "quit" and el > 3.0:
            unreal.unregister_slate_post_tick_callback(ST["h"])
            if os.environ.get("GYROSIM_BUSAN_QUIT", "1") == "1":
                unreal.SystemLibrary.quit_editor()
    except Exception as e:
        import traceback
        log("error", repr(e), " | ".join(traceback.format_exc().splitlines()))
        ST.update(phase="quit" if ST["phase"] in ("end", "quit") else "end", t=time.monotonic())


if C() is None:
    sim_client.start()
ST["h"] = unreal.register_slate_post_tick_callback(tick)
log("scheduled", len(SHOTS), "shots ->", OUT)
