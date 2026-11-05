"""3D buildings (국토교통부 GIS건물통합정보 -> sim/buildings_build.py -> /buildings/tileset.json) in the vworld mode -
check (developer use). Needs the 'vworld' ground mode (Config/cesium_token.txt line or GYROSIM_GROUND=vworld for the
editor AND the server), sim/server.py running (tile proxy + DEM + roof raster). Launch the editor with
-GyroSimVWorldBuildings (init_unreal.py). GYROSIM_MUTE / quiet server recommended (the crash is loud).

Shots (Saved/verify/vworld_buildings/): Cheongju downtown low pass (chase, cockpit), the tallest apartment complex
(신영지웰시티, 45 F) from an orbit, a steep top-down orbit over downtown with the buildings on and off (footprints vs the
V-World roofs, eyeball), RKTU runway start (chase + side), a camera-floor shot next to a tower, and a flight into the
towers -> red crash screen ("건물에 부딪힘"). Then GPU time with the buildings hidden / shown at the same paused view,
alternating (off, on, off, on) x 2 views. Result: vworld_buildings_result.json (proxy API count before / after).
"""
import json, math, os, re, time
import unreal
import sim_client

log = lambda *a: unreal.log("[vwbldg] " + " ".join(str(x) for x in a))
les = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
ues = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem)
OUT = os.path.join(unreal.Paths.project_saved_dir(), "verify", "vworld_buildings")
os.makedirs(OUT, exist_ok=True)
LOG = os.path.join(unreal.Paths.project_log_dir(), "GyroSim.log")
C = sim_client.client
SAY = lambda m: C()._send(m)
HOLD = {"ail": 0.0, "elev": 0.0, "rud": 0.0, "brk_l": 1.0, "brk_r": 1.0, "thr": 0.0}
FLY = dict(HOLD, brk_l=0.0, brk_r=0.0, thr=0.8)
JIWELL = (36.6445, 127.4250)               # 신영지웰시티 1차 (45 F, 147 m), ground ~47 m MSL
DOWNTOWN = (36.6330, 127.4950)             # east of 두산위브더제니스 (41 F), looking west over the old town


def off(p, brg, km):
    return (p[0] + km * math.cos(math.radians(brg)) / 110.95, p[1] + km * math.sin(math.radians(brg)) / (111.32 * math.cos(math.radians(p[0]))))


LOW = dict(lat=DOWNTOWN[0], lon=DOWNTOWN[1], alt_m=230.0, hdg=275.0, kts=250.0)              # ~180 m above the town
APT = dict(lat=off(JIWELL, 90, 1.2)[0], lon=off(JIWELL, 90, 1.2)[1], alt_m=260.0, hdg=270.0, kts=250.0)
TOP = dict(lat=36.6390, lon=127.4800, alt_m=700.0, hdg=0.0, kts=250.0)                         # top-down over 성안길 / 상당구
FLOOR = dict(lat=off(JIWELL, 90, 0.25)[0], lon=off(JIWELL, 90, 0.25)[1], alt_m=120.0, hdg=270.0, kts=250.0)
CRASH = dict(lat=off(JIWELL, 90, 1.6)[0], lon=off(JIWELL, 90, 1.6)[1], alt_m=140.0, hdg=270.0, kts=300.0)   # roofs ~194 m
# (name, start, view, orbit [yaw, el, dist cm] or None, kind, buildings shown)
SHOTS = [("downtown_chase", LOW, "chase", None, "shot", True),
         ("downtown_cockpit", LOW, "cockpit", None, "shot", True),
         ("apartments_orbit", APT, "orbit", [200.0, 6.0, 60000.0], "shot", True),
         ("apartments_chase", APT, "chase", None, "shot", True),
         ("align_top_on", TOP, "orbit", [0.0, 80.0, 50000.0], "shot", True),
         ("align_top_off", TOP, "orbit", [0.0, 80.0, 50000.0], "shot", False),
         ("floor_orbit_low", FLOOR, "orbit", [270.0, -20.0, 30000.0], "floor", True),
         ("runway_chase", "runway", "chase", None, "runway", True),
         ("runway_side", "runway", "orbit", [90.0, 2.0, 6000.0], "runway", True),
         ("crash", CRASH, "cockpit", None, "crash", True)]
FPS_VIEWS = [("downtown_chase", LOW, "chase"), ("downtown_cockpit", LOW, "cockpit")]
FPS_ORDER = [False, True, False, True]      # buildings shown? (A/B alternating, 2 repeats each)
ST = dict(t=time.monotonic(), phase="wait_pie", i=0, h=None, res={}, shots=[], start=None, fps=[], fi=0)


def shot(name):
    fn = os.path.join(OUT, name + ".png").replace("\\", "/")
    unreal.SystemLibrary.execute_console_command(ues.get_game_world(), "HighResShot %s filename=%s" % (os.environ.get("GYROSIM_SHOT_RES", "1600x900"), fn))
    ST["shots"].append(os.path.basename(fn))


def cmd(c):
    unreal.SystemLibrary.execute_console_command(ues.get_game_world(), c)


def progress(ts):
    try:
        return round(float(ts.get_editor_property("load_progress")), 1) if ts else None
    except Exception:
        return None


def show_buildings(on):
    b = getattr(C(), "buildings", None)
    if b:
        b.set_actor_hidden_in_game(not on)


def checks():
    c = C()
    r = dict(ground=c.cesium_mode, vw_local=getattr(c, "vw_local", None), vw_bldg=getattr(c, "vw_bldg", None))
    b = getattr(c, "buildings", None)
    try:
        r["buildings_url"] = b.get_editor_property("url") if b else None
        r["buildings_physics"] = bool(b.get_editor_property("create_physics_meshes")) if b else None
    except Exception as e:
        r["buildings_url"] = repr(e)
    st = c.vworld_status(1.0)
    r["proxy"] = st
    r["server_terrain"] = (c.s or {}).get("terrain")
    r["ok"] = (c.cesium_mode == "vworld" and bool(getattr(c, "vw_bldg", False)) and str(r.get("buildings_url", "")).endswith("/buildings/tileset.json")
               and st is not None and bool(st.get("buildings")))
    return r


def ground_under(c, p):
    """first hit Z (trace: terrain or a building) under world point p, cm, or None."""
    try:
        r = unreal.SystemLibrary.line_trace_single(c.world, unreal.Vector(p.x, p.y, p.z + 1000000.0), unreal.Vector(p.x, p.y, p.z - 1000000.0),
                                                   unreal.TraceTypeQuery.TRACE_TYPE_QUERY1, False, c._ground_ignore(), unreal.DrawDebugTrace.NONE, True)
        hit = r if isinstance(r, unreal.HitResult) else (r[-1] if isinstance(r, (tuple, list)) else None)
        t = hit.to_tuple() if hit is not None else None
        return (t[4].z, t[9].get_name() if t[9] else None) if t and t[0] else (None, None)
    except Exception as e:
        log("trace", repr(e))
        return None, None


def gpu_from_log():
    try:
        with open(LOG, encoding="utf-8", errors="ignore") as f:
            txt = f.read()[-200000:]
        g = re.findall(r"Average GPU frametime: ([\d.]+) ms", txt)
        return float(g[-1]) if g else None
    except OSError:
        return None


def start(spec, pause):
    SAY({"cmd": "tut", "op": "free"})
    if isinstance(spec, dict):
        SAY(dict(spec, cmd="place"))
    else:
        SAY({"cmd": "reset", "mode": spec})
    if pause:
        SAY({"cmd": "pause", "on": True})


def loaded(c):
    p1, p2 = progress(c.tileset), progress(getattr(c, "buildings", None))
    return p1, p2, (p1 is not None and p1 >= 99.9) and (p2 is None or p2 >= 99.9)


def tick(dt):
    try:
        now = time.monotonic()
        el = now - ST["t"]
        c = C()
        ph = ST["phase"]
        if ph == "wait_pie":
            if el > float(os.environ.get("GYROSIM_VWORLD_WAIT", "45")):
                les.editor_request_begin_play()
                ST.update(phase="wait_world", t=now)
        elif ph == "wait_world":
            if ues.get_game_world() is not None and c and c.aircraft is not None and c.s is not None and c.startup_done:
                SAY({"cmd": "tut", "op": "stop"})
                ST["res"]["setup"] = checks()
                ST["proxy_before"] = ST["res"]["setup"].get("proxy")
                log("setup", json.dumps(ST["res"]["setup"], default=str))
                ST.update(phase="setup", t=now)
        elif ph == "setup" and el > 1.0:
            if ST["i"] >= len(SHOTS):
                ST.update(phase="fps_setup", t=now)
                return
            name, spec, view, orb, kind, bon = SHOTS[ST["i"]]
            key = spec if not isinstance(spec, dict) else json.dumps(spec, sort_keys=True)
            if ST["start"] != key or kind == "crash":
                start(spec, kind != "crash")
                ST["start"] = key
                ST["t_start"] = now
            show_buildings(bon)
            c.override = dict(FLY if kind == "crash" else HOLD if spec == "runway" else dict(HOLD, brk_l=0.0, brk_r=0.0, thr=0.75))
            c.set_view(view)
            if orb is not None:
                c.orbit[view] = list(orb)
            ST.update(phase="load", t=now)
        elif ph == "load":
            name, spec, view, orb, kind, bon = SHOTS[ST["i"]]
            if orb is not None:
                c.orbit[view] = list(orb)
            if kind == "crash":
                tut = (c.s or {}).get("tut") or {}
                if tut.get("phase") == "crash":
                    ST["res"][name] = dict(crash=tut.get("crash"), crash_obj=(c.s or {}).get("crash_obj"), t_flight_s=round(now - ST["t_start"], 1),
                                           lat=c.s.get("lat"), lon=c.s.get("lon"), alt_m=round(c.s.get("alt_m", 0), 1), terrain_m=c.s.get("terrain_m"),
                                           agl_m=round(c.s.get("agl_m", 0), 1))
                    ST.update(phase="shoot", t=now)
                elif el > 60.0:
                    ST["res"][name] = dict(crash=None, timeout=True, alt_m=c.s.get("alt_m"), terrain_m=c.s.get("terrain_m"), tut_phase=tut.get("phase"))
                    ST.update(phase="shoot", t=now)
                return
            p1, p2, ok = loaded(c)
            if (ok and el > 6.0) or el > 60.0:
                ST["load"] = dict(load_s=round(el, 1), terrain_progress=p1, buildings_progress=p2)
                ST.update(phase="shoot", t=now)
        elif ph == "shoot" and el > 1.5:
            name, spec, view, orb, kind, bon = SHOTS[ST["i"]]
            shot(name)
            s = c.s or {}
            r = ST["res"].setdefault(name, {})
            r.update(ST.pop("load", {}), view=c.view, buildings_shown=bon, alt_m=round(s.get("alt_m", 0), 1), terrain_m=s.get("terrain_m"),
                     agl_m=round(s.get("agl_m", 0), 2), radar_m=None if c.radar_m is None else round(c.radar_m, 2), wow=s.get("wow"),
                     crashed=s.get("crashed"))
            if view != "cockpit":
                cam = c.camera.get_actor_location()
                g, what = ground_under(c, cam)
                r["camera_above_hit_m"] = None if g is None else round((cam.z - g) / 100.0, 2)
                r["camera_trace_hit"] = what
                if kind == "floor":
                    r["floor_ok"] = g is not None and cam.z - g >= 100.0
            if kind == "runway":
                r["runway_ok"] = bool(s.get("wow")) and not s.get("crashed") and abs(s.get("agl_m", 9) - 1.24) < 0.5
            log(name, json.dumps(r, default=str))
            ST["i"] += 1
            ST.update(phase="setup", t=now)
        # ---- GPU A/B: same paused view, buildings hidden / shown alternately ----------------------------------------------
        elif ph == "fps_setup" and el > 1.0:
            if ST["fi"] >= len(FPS_VIEWS) * len(FPS_ORDER):
                ST.update(phase="end", t=now)
                return
            vname, spec, view = FPS_VIEWS[ST["fi"] // len(FPS_ORDER)]
            on = FPS_ORDER[ST["fi"] % len(FPS_ORDER)]
            if ST["fi"] % len(FPS_ORDER) == 0:
                start(spec, True)
                c.override = dict(HOLD, brk_l=0.0, brk_r=0.0, thr=0.75)
                c.set_view(view)
            show_buildings(True)                  # tiles load with buildings shown, then hide for the 'off' run
            cmd("t.MaxFPS 0"); cmd("r.VSync 0")
            vp = unreal.WidgetLayoutLibrary.get_viewport_size(ues.get_game_world())
            sp = max(25.0, min(400.0, 100.0 * math.sqrt(1920 * 1080 / max(1.0, vp.x * vp.y))))
            cmd("r.ScreenPercentage %.0f" % sp)
            ST["cur"] = dict(view=vname, buildings=on, viewport=[round(vp.x), round(vp.y)], screen_percentage=round(sp))
            ST.update(phase="fps_load", t=now)
        elif ph == "fps_load":
            p1, p2, ok = loaded(c)
            if (ok and el > 4.0) or el > 60.0:
                show_buildings(ST["cur"]["buildings"])
                ST.update(phase="fps_warm", t=now)
        elif ph == "fps_warm" and el > 3.0:
            cmd("t.FPSChart.OpenFolderOnDump 0")
            cmd("startfpschart")
            ST.update(phase="fps_run", t=now, dts=[])
        elif ph == "fps_run":
            ST["dts"].append(dt)
            if el > 6.0:
                cmd("stopfpschart")
                ST.update(phase="fps_collect", t=now)
        elif ph == "fps_collect" and el > 0.7:
            d = sorted(ST["dts"][5:])
            r = dict(ST["cur"], gpu_ms=gpu_from_log(), frames=len(d), avg_ms=round(sum(d) / len(d) * 1000, 2) if d else None)
            ST["fps"].append(r)
            log("fps", json.dumps(r))
            ST["fi"] += 1
            ST.update(phase="fps_setup", t=now)
        elif ph == "end" and el > 2.0:
            cmd("r.ScreenPercentage 100")
            show_buildings(True)
            c.override = None
            c.set_view("cockpit")
            SAY({"cmd": "tut", "op": "free"})
            SAY({"cmd": "pause", "on": False})
            r = checks()
            pb, pa = ST.get("proxy_before") or {}, r.get("proxy") or {}
            cr = ST["res"].get("crash", {})
            rw = [v.get("runway_ok") for k, v in ST["res"].items() if isinstance(v, dict) and "runway_ok" in v]
            fl = [v.get("floor_ok") for k, v in ST["res"].items() if isinstance(v, dict) and "floor_ok" in v]
            summ = {}
            for f in ST["fps"]:
                summ.setdefault("%s_%s" % (f["view"], "on" if f["buildings"] else "off"), []).append(f["gpu_ms"])
            res = dict(made=time.strftime("%Y-%m-%d %H:%M:%S"), checks=r, shots=ST["shots"], steps=ST["res"], fps=ST["fps"], fps_gpu_ms=summ,
                       api_requests_this_check=(pa.get("used_today", 0) - pb.get("used_today", 0)) if pa and pb else None,
                       crash_ok=cr.get("crash_obj") == "building", runway_ok=all(rw) and bool(rw), floor_ok=all(fl) and bool(fl),
                       ok=bool(r["ok"] and ST["res"]["setup"]["ok"] and cr.get("crash_obj") == "building" and all(rw) and all(fl)))
            with open(os.path.join(OUT, "vworld_buildings_result.json"), "w", encoding="utf-8") as f:
                json.dump(res, f, indent=1, ensure_ascii=False, default=str)
            log("done ok=%s api=%s ->" % (res["ok"], res["api_requests_this_check"]), OUT)
            les.editor_request_end_play()
            unreal.unregister_slate_post_tick_callback(ST["h"])
    except Exception as e:
        import traceback
        log("error", repr(e), " | ".join(traceback.format_exc().splitlines()))
        unreal.unregister_slate_post_tick_callback(ST["h"])


if C() is None:
    sim_client.start()
ST["h"] = unreal.register_slate_post_tick_callback(tick)
log("scheduled", len(SHOTS), "shots + GPU A/B ->", OUT)
