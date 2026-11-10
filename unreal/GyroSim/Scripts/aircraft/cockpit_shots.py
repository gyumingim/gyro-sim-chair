"""Cockpit / airframe check shots (developer use). Needs the sim server (Busan start, muted):
    GYROSIM_MUTE=1 python sim/server.py --start rkpk --free-flight --no-picker
and a SECOND editor, never visible (holding C:/GyroSimTiles/ue_offscreen.lock):
    UnrealEditor.exe GyroSim.uproject /Game/Maps/FlightMap -GyroSimCockpitShots -RenderOffscreen -nosound -nosplash -ABSLOG=<log>
(env GYROSIM_FULLSCREEN=0, GYROSIM_CKSHOT_LOG=<log> for the GPU numbers). Play is started here; every window of this
process is kept off the desktop without activation. Per spot (Haeundae, Gwangan Bridge, Nampo; paused, same pose):
  cockpit view with the airframe pass off ('before' = old exterior skin) and on ('after'), and the eye view (no cockpit);
Gwangan: exterior 3/4 front / side / from below, before / after (same stick / pedal input, surfaces only move 'after');
Haeundae: chase view before / after, GPU (startfpschart, ~1080p pixels) cockpit + chase before / after, then a short
unpaused flight with a roll-in and pull (head motion sequence: 12 frames + per-frame head offsets in shake.json).
Out: GYROSIM_SHOTS_DIR (default C:/GyroSimTiles/shots/cockpit - V-World imagery stays outside git) + shots.json.
Quits the editor when done.
"""
import ctypes, json, math, os, re, time
import ctypes.wintypes as W
import unreal
import sim_client

log = lambda *a: unreal.log("[ckshots] " + " ".join(str(x) for x in a))
ues = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem)
les = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
OUT = os.environ.get("GYROSIM_SHOTS_DIR", r"C:\GyroSimTiles\shots\cockpit")
os.makedirs(OUT, exist_ok=True)
RES = os.environ.get("GYROSIM_SHOT_RES", "1600x900")
LOGF = os.environ.get("GYROSIM_CKSHOT_LOG", "")
C = sim_client.client
SAY = lambda m: C()._send(m)
CRUISE = {"ail": 0.0, "elev": 0.0, "rud": 0.0, "brk_l": 0.0, "brk_r": 0.0, "thr": 0.75, "gear": 0.0}
DEFLECT = dict(CRUISE, ail=0.45, elev=-0.35, rud=0.4)
SPOTS = [("haeundae", dict(lat=35.1440, lon=129.1700, alt_m=350.0, hdg=340.0, kts=250.0)),
         ("gwangan", dict(lat=35.1180, lon=129.1120, alt_m=250.0, hdg=20.0, kts=250.0)),
         ("nampo", dict(lat=35.0700, lon=129.0320, alt_m=300.0, hdg=355.0, kts=250.0))]
EXT = [("ext34front", [35.0, 8.0, 2300.0]), ("extside", [90.0, 2.0, 2100.0]), ("extbelow", [55.0, -25.0, 1900.0])]
ST = dict(t=time.monotonic(), t0=time.monotonic(), phase="wait_editor", h=None, res={}, gpu=[], q=[], fg=None, series=[])

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


def lighting_report(w, c):
    """shadow / fog facts for the airframe check: cast shadow flags of the aircraft parts, the sun light's shadow
    settings, height fog / sky atmosphere present."""
    r = {}
    try:
        parts = [c.aircraft] + list(c.aircraft.get_attached_actors(True, True))
        cs = {p.get_name(): p.static_mesh_component.get_editor_property("cast_shadow") for p in parts if getattr(p, "static_mesh_component", None)}
        r["aircraft_parts"], r["cast_shadow_on"] = len(cs), sum(1 for x in cs.values() if x)
        r["no_shadow"] = sorted(k for k, v in cs.items() if not v)
        mats = set()
        for p in parts:
            for smc in p.get_components_by_class(unreal.StaticMeshComponent):
                for i in range(smc.get_num_materials()):
                    m = smc.get_material(i)
                    if m:
                        mats.add(m.get_name() if not isinstance(m, unreal.MaterialInstanceDynamic) else "MID:" + (m.parent.get_name() if m.parent else "?"))
        r["materials"] = sorted(mats)
        for a in unreal.GameplayStatics.get_all_actors_of_class(w, unreal.DirectionalLight):
            lc = a.light_component
            r.setdefault("sun", []).append({k: lc.get_editor_property(k) for k in ("cast_shadows", "cast_dynamic_shadows", "dynamic_shadow_distance_movable_light",
                                                                                 "dynamic_shadow_cascades", "contact_shadow_length", "intensity", "atmosphere_sun_light")
                                            if _has(lc, k)})
        r["height_fog"] = len(unreal.GameplayStatics.get_all_actors_of_class(w, unreal.ExponentialHeightFog))
        r["sky_atmosphere"] = len(unreal.GameplayStatics.get_all_actors_of_class(w, unreal.SkyAtmosphere))
        ext = getattr(c.af, "ext", None)
        if ext:
            m = ext.static_mesh_component.get_material(0)
            r["exterior_mat0"] = m.get_name() if m else None
    except Exception as e:
        r["error"] = repr(e)
    return r


def _has(o, k):
    try:
        o.get_editor_property(k)
        return True
    except Exception:
        return False


def plan_ext():
    """GYROSIM_CKSHOT_SET=ext: outside views only (airframe rounds), before = GYROSIM_CKSHOT_BEFORE mode (v1), after = v2."""
    q = [("place", "gwangan", SPOTS[1][1]), ("state", "after", "orbit", EXT[0][1], DEFLECT), ("wait", 20.0)]   # tiles behind the first view
    for vn, orb in EXT + [("extrear", [150.0, 14.0, 1500.0])]:
        for st in ("before", "after"):
            q.append(("state", st, "orbit", orb, DEFLECT)); q.append(("shot", "gwangan_%s_%s" % (vn, st)))
    q.append(("place", "haeundae", SPOTS[0][1]))
    for st in ("before", "after"):
        q.append(("state", st, "chase", None, CRUISE)); q.append(("shot", "haeundae_chase_%s" % st))
    if LOGF:
        for st in ("before", "after"):
            q.append(("state", st, "chase", None, CRUISE)); q.append(("gpu", "chase_%s" % st))
    return q


def plan():
    """the step queue: ('place', spot) / ('state', name, view, orbit, ctrl) / ('shot', file) / ('gpu', label) / ('fly',)"""
    if os.environ.get("GYROSIM_CKSHOT_SET") == "ext":
        return plan_ext()
    q = []
    for name, spec in SPOTS:
        q.append(("place", name, spec))
        for st in ("before", "after"):
            q.append(("state", st, "cockpit", None, CRUISE)); q.append(("shot", "%s_cockpit_%s" % (name, st)))
        q.append(("state", "after", "eye", None, CRUISE)); q.append(("shot", "%s_eye" % name))
        if name == "gwangan":
            for vn, orb in EXT:
                for st in ("before", "after"):
                    q.append(("state", st, "orbit", orb, DEFLECT)); q.append(("shot", "%s_%s_%s" % (name, vn, st)))
                if os.environ.get("GYROSIM_CKSHOT_DIAG") and vn == "ext34front":     # diagnosis: paint without the normal map / fin parts
                    for dg in ("nonormal", "noshadow", "norudder"):
                        q.append(("state", "after", "orbit", orb, DEFLECT)); q.append(("diag", dg)); q.append(("shot", "%s_%s_diag_%s" % (name, vn, dg))); q.append(("undiag", dg))
        if name == "haeundae":
            for st in ("before", "after"):
                q.append(("state", st, "chase", None, CRUISE)); q.append(("shot", "%s_chase_%s" % (name, st)))
            if LOGF:
                for st in ("before", "after"):
                    for v in ("cockpit", "chase"):
                        q.append(("state", st, v, None, CRUISE)); q.append(("gpu", "%s_%s" % (v, st)))
    q.append(("place", "haeundae", SPOTS[0][1]))
    q.append(("state", "after", "cockpit", None, CRUISE))
    q.append(("fly",))
    return q


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
        if ph == "wait_editor" and el > float(os.environ.get("GYROSIM_CKSHOT_WAIT", "30")):
            les.editor_request_begin_play()
            ST.update(phase="wait_world", t=now)
        elif ph == "wait_world":
            if c and c.aircraft is not None and c.s is not None and c.startup_done and el > 5.0:
                SAY({"cmd": "tut", "op": "stop"})
                cmd("t.MaxFPS 0"); cmd("r.VSync 0"); cmd("t.FPSChart.OpenFolderOnDump 0")
                ST.update(phase="next", t=now, q=plan())
                if os.environ.get("GYROSIM_CKSHOT_SET") == "ext":       # compile / stream the v2 materials before any shot
                    c.af.set_mode("v2"); c.set_view("chase")
                    ST.update(phase="warm", t=now)
                log("airframe ok", c.af.ok, "surfaces", sorted(c.af.surf), "lights", sorted(c.af.lights))
                ST["lighting"] = lighting_report(ues.get_game_world(), c)
                log("lighting", json.dumps(ST["lighting"], default=str))
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
                ST["spot"] = step[1]
                ST.update(phase="load", t=now)
            elif k == "state":
                _, st, view, orb, ctrl = step
                before = os.environ.get("GYROSIM_CKSHOT_BEFORE", "orig")
                c.af.set_mode("v2" if st == "after" else before) if hasattr(c.af, "set_mode") else c.af.set_enabled(st == "after")
                c.fx.set_look(st == "after" or os.environ.get("GYROSIM_CKSHOT_SET") == "ext")   # canopy glints + cockpit paint: old / new
                c.override = dict(ctrl)
                if c.view != view:
                    c.set_view(view)
                c.look_tgt = [0.0, 0.0]
                if orb is not None:
                    c.orbit[view] = list(orb)
                    c.orbit_world_yaw = None
                ST.update(phase="settle", t=now)
            elif k == "wait":
                ST.update(phase="waitstep", t=now, wait=step[1])
            elif k in ("diag", "undiag"):
                on, dg = k == "diag", step[1]
                ext = c.af.ext
                if dg == "nonormal":
                    smc = ext.static_mesh_component
                    if on:
                        ST["diag_mat"] = smc.get_material(0)
                        mid = smc.create_dynamic_material_instance(0, ST["diag_mat"])
                        mid.set_scalar_parameter_value("NormalStr", 0.0)
                    else:
                        smc.set_material(0, ST.get("diag_mat"))
                elif dg == "noshadow":
                    for a in [ext] + [x for x, _ in c.af.surf.values()]:
                        a.static_mesh_component.set_cast_shadow(not on)
                elif dg == "norudder":
                    c.af.surf["Rudder"][0].set_actor_hidden_in_game(on)
                log("diag", dg, on)
                ST.update(phase="settle", t=now)
            elif k == "shot":
                fn = os.path.join(OUT, step[1] + ".png").replace("\\", "/")
                cmd("HighResShot %s filename=%s" % (RES, fn))
                s = c.s or {}
                ST["res"][step[1]] = dict(file=fn, view=c.view, airframe=c.af.ok, mode=getattr(c.af, "mode", None), glass_out=getattr(c.af, "glass_out", None), lat=s.get("lat"), lon=s.get("lon"), alt_m=s.get("alt_m"),
                                          psi=s.get("psi"), defl={k2: round(v, 1) for k2, v in c.af.defl.items()}, load=ST.get("load"))
                log("shot", fn)
                ST.update(phase="wait_file", t=now, file=fn)
            elif k == "gpu":
                vp = unreal.WidgetLayoutLibrary.get_viewport_size(ues.get_game_world())
                sp = max(25.0, min(400.0, 100.0 * math.sqrt(1920 * 1080 / max(1.0, vp.x * vp.y))))
                ST["sp"] = (round(vp.x), round(vp.y), round(sp))
                cmd("r.ScreenPercentage %.0f" % sp)
                ST.update(phase="gpu_start", t=now)
            elif k == "fly":
                c.override = dict(CRUISE)
                SAY({"cmd": "pause", "on": False})
                ST.update(phase="fly", t=now, series=[], frames=0)
        elif ph == "load":
            p1, p2 = progress(getattr(c, "tileset", None)), progress(getattr(c, "buildings", None))
            if (p1 is not None and p1 >= 99.9 and (p2 is None or p2 >= 99.9) and el > 10.0) or el > 90.0:
                ST["load"] = dict(load_s=round(el, 1), terrain=p1, buildings=p2)
                ST.update(phase="next", t=now)
        elif ph == "waitstep" and el > ST["wait"]:
            ST.update(phase="next", t=now)
        elif ph == "wait_file":                       # a hitch (shader compile) must not let the next view into this shot
            if os.path.exists(ST["file"]) or el > 30.0:
                if el > 30.0:
                    log("shot file missing after 30 s", ST["file"])
                ST.update(phase="next", t=now)
        elif ph == "warm" and el > float(os.environ.get("GYROSIM_CKSHOT_WARM", "25")):
            c.af.set_mode("v1")
            ST.update(phase="next", t=now)
        elif ph == "settle" and el > 3.0:
            ST.update(phase="next", t=now)
        elif ph == "gpu_start" and el > 3.0:
            cmd("startfpschart")
            ST.update(phase="gpu_run", t=now, dts=[])
        elif ph == "gpu_run":
            ST["dts"].append(dt)
            if el > 8.0:
                cmd("stopfpschart")
                ST.update(phase="gpu_collect", t=now)
        elif ph == "gpu_collect" and el > 1.5:
            d = sorted(ST["dts"][5:])
            r = dict(label=ST["step"][1], gpu_ms=gpu_from_log(), viewport=ST["sp"][:2], screen_percentage=ST["sp"][2], frames=len(d),
                     avg_ms=round(sum(d) / len(d) * 1000, 2) if d else None)
            ST["gpu"].append(r)
            log("gpu", json.dumps(r))
            cmd("r.ScreenPercentage 100")
            ST.update(phase="next", t=now)
        elif ph == "fly":
            s = c.s or {}
            # 0-2 s level, 2-7 s roll to 45 deg bank (P control on the bank angle), 3.5-7 s pull (~2 G), 7-10 s roll out
            ctl = dict(CRUISE, thr=float(s.get("thr_init", 0.6) or 0.6))
            phi, p = float(s.get("phi", 0.0) or 0.0), float(s.get("p_dps", 0.0) or 0.0)
            if 2.0 < el <= 7.0:
                ctl["ail"] = max(-0.3, min(0.3, 0.012 * (45.0 - phi) - 0.004 * p))
            elif el > 7.0:
                ctl["ail"] = max(-0.3, min(0.3, 0.012 * (0.0 - phi) - 0.004 * p))
            if 3.5 < el <= 7.0:
                ctl["elev"] = -0.15
            c.override = ctl
            (hx, hy, hz), (fp, fy, fr) = c.fx.out
            ST["series"].append(dict(t=round(el, 3), head_cm=[round(hx, 2), round(hy, 2), round(hz, 2)], rot_deg=[round(fp, 3), round(fy, 3), round(fr, 3)],
                                     nz=s.get("nz"), ax=s.get("ax"), ay=s.get("ay"), phi=s.get("phi"), kts=s.get("kts"), agl_m=s.get("agl_m"),
                                     why=c.fx.why, defl={k2: round(v, 1) for k2, v in c.af.defl.items()}))
            if el > 1.0 + ST["frames"] * 0.7 and ST["frames"] < 12:
                fn = os.path.join(OUT, "shake_%02d.png" % ST["frames"]).replace("\\", "/")
                cmd("HighResShot 960x540 filename=%s" % fn)
                ST["frames"] += 1
            if el > 10.0:
                SAY({"cmd": "pause", "on": True})
                with open(os.path.join(OUT, "shake.json"), "w", encoding="utf-8") as f:
                    json.dump(ST["series"], f)
                ST.update(phase="next", t=now)
        elif ph == "end" and el > 2.0:
            if c:
                c.override = None
            res = dict(made=time.strftime("%Y-%m-%d %H:%M:%S"), seconds=round(now - ST["t0"]), shots=ST["res"], gpu=ST["gpu"], lighting=ST.get("lighting"),
                       note="editor PIE (second, off-screen editor), sim server Busan start paused at each spot; before = airframe pass off "
                            "(old one-piece exterior), after = body + moving surfaces + lights + painted skin; head motion only when unpaused")
            with open(os.path.join(OUT, "shots.json"), "w", encoding="utf-8") as f:
                json.dump(res, f, indent=1, ensure_ascii=False, default=str)
            log("done ->", OUT)
            les.editor_request_end_play()
            ST.update(phase="quit", t=now)
        elif ph == "quit" and el > 3.0:
            unreal.unregister_slate_post_tick_callback(ST["h"])
            if os.environ.get("GYROSIM_CKSHOT_QUIT", "1") == "1":
                unreal.SystemLibrary.quit_editor()
    except Exception as e:
        import traceback
        log("error", repr(e), " | ".join(traceback.format_exc().splitlines()))
        ST.update(phase="quit" if ST["phase"] in ("end", "quit") else "end", t=time.monotonic())


if C() is None:
    sim_client.start()
ST["h"] = unreal.register_slate_post_tick_callback(tick)
log("scheduled ->", OUT)
