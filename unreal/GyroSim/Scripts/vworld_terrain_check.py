"""V-World photos on the local South Korea terrain (Copernicus DEM, sim/terrain_build.py) - check (developer use).
Needs Config/cesium_token.txt with a 'vworld' line and sim/server.py running (it starts the tile proxy, which also
serves /terrain/, and puts JSBSim on the DEM). Launch the editor with -GyroSimVWorldTerrain (init_unreal.py).
Set GYROSIM_MUTE=1 for the server so the crash is silent.

Shots (Saved/verify/vworld_terrain/): runway side view (runway mesh vs terrain), runway chase, Seoraksan from 7 km
(chase / cockpit / orbit side), the camera-floor test on a slope (orbit at the lowest angle, flyby, chase: camera must
stay above the terrain), and a deliberate flight into Seoraksan -> red crash screen. Few V-World calls: aircraft
paused for the views, one area only. Result: vworld_terrain_result.json (proxy API count before / after).
"""
import json, math, os, time
import unreal
import sim_client

log = lambda *a: unreal.log("[vwterrain] " + " ".join(str(x) for x in a))
les = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
ues = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem)
OUT = os.path.join(unreal.Paths.project_saved_dir(), "verify", "vworld_terrain")
os.makedirs(OUT, exist_ok=True)
C = sim_client.client
SAY = lambda m: C()._send(m)
HOLD = {"ail": 0.0, "elev": 0.0, "rud": 0.0, "brk_l": 1.0, "brk_r": 1.0, "thr": 0.0}
FLY = dict(HOLD, brk_l=0.0, brk_r=0.0, thr=0.8)
PEAK = (38.1192, 128.4653)                 # Seoraksan Daecheongbong 1708 m


def from_peak(brg, km):
    return (PEAK[0] + km * math.cos(math.radians(brg)) / 110.95,
            PEAK[1] + km * math.sin(math.radians(brg)) / (111.32 * math.cos(math.radians(PEAK[0]))))


P7 = from_peak(237.0, 7.0)                 # 7 km SW of the peak, DEM 862 m
P35 = from_peak(237.0, 3.5)                # on the ridge 3.5 km SW, DEM ~1120 m
VIEW_AT = dict(lat=P7[0], lon=P7[1], alt_m=1900.0, hdg=57.0, kts=300.0)
CRASH_AT = dict(lat=P7[0], lon=P7[1], alt_m=1300.0, hdg=57.0, kts=400.0)      # terrain reaches 1433 m 5.5 km ahead
SLOPE_AT = dict(lat=P35[0], lon=P35[1], alt_m=1180.0, hdg=57.0, kts=300.0)    # ~60 m above the slope
# (name, start, view, orbit [yaw, el, dist cm] or None, kind)
SHOTS = [("runway_side", "runway", "orbit", [90.0, 2.0, 6000.0], "shot"),
         ("runway_chase", "runway", "chase", None, "shot"),
         ("seorak_chase", VIEW_AT, "chase", None, "shot"),
         ("seorak_cockpit", VIEW_AT, "cockpit", None, "shot"),
         ("seorak_orbit", VIEW_AT, "orbit", [100.0, 8.0, 40000.0], "shot"),
         ("slope_orbit_low", SLOPE_AT, "orbit", [180.0, -25.0, 40000.0], "floor"),
         ("slope_chase", SLOPE_AT, "chase", None, "floor"),
         ("slope_flyby", SLOPE_AT, "flyby", None, "floor"),
         ("crash", CRASH_AT, "cockpit", None, "crash")]
ST = dict(t=time.monotonic(), phase="wait_pie", i=0, h=None, res={}, shots=[], start=None)


def shot(name):
    fn = os.path.join(OUT, name + ".png").replace("\\", "/")
    # fixed size: the editor window may be small (off-screen / not focused while the PC is in use)
    unreal.SystemLibrary.execute_console_command(ues.get_game_world(), "HighResShot %s filename=%s" % (os.environ.get("GYROSIM_SHOT_RES", "1600x900"), fn))
    ST["shots"].append(os.path.basename(fn))


def progress():
    c = C()
    try:
        return round(float(c.tileset.get_editor_property("load_progress")), 1) if c.tileset else None
    except Exception:
        return None


def checks():
    c = C()
    r = dict(ground=c.cesium_mode, vw_terrain=getattr(c, "vw_terrain", None), vw_local=getattr(c, "vw_local", None))
    try:
        r["tileset_url"] = c.tileset.get_editor_property("url")
        r["tileset_source"] = str(c.tileset.get_editor_property("tileset_source"))
    except Exception as e:
        r["tileset_url"] = repr(e)
    ovs = {o.get_class().get_name(): o for o in c.tileset.get_components_by_class(unreal.CesiumRasterOverlay)} if c.tileset else {}
    url = ovs["CesiumUrlTemplateRasterOverlay"].get_editor_property("template_url") if "CesiumUrlTemplateRasterOverlay" in ovs else ""
    r["overlay_url"] = url
    r["url_local_ok"] = url.startswith("http://127.0.0.1:") and "vworld.kr" not in url
    a = getattr(c, "attrib", None)
    r["attribution"] = dict(found=bool(a), hidden=bool(a.get_editor_property("hidden")) if a else None)
    st = c.vworld_status(1.0)
    r["proxy"] = st
    s = c.s or {}
    r["server_terrain"] = s.get("terrain")
    r["ok"] = (c.cesium_mode == "vworld" and bool(getattr(c, "vw_local", False)) and r["url_local_ok"]
               and str(r.get("tileset_url", "")).endswith("/terrain/layer.json") and r["attribution"]["hidden"] is False
               and st is not None and s.get("terrain") == "dem")
    return r


def ground_under(c, p):
    """terrain Z (trace) under world point p, cm, or None."""
    try:
        r = unreal.SystemLibrary.line_trace_single(c.world, unreal.Vector(p.x, p.y, p.z + 1000000.0), unreal.Vector(p.x, p.y, p.z - 1000000.0),
                                                   unreal.TraceTypeQuery.TRACE_TYPE_QUERY1, False, c._ground_ignore(), unreal.DrawDebugTrace.NONE, True)
        hit = r if isinstance(r, unreal.HitResult) else (r[-1] if isinstance(r, (tuple, list)) else None)
        t = hit.to_tuple() if hit is not None else None
        return t[4].z if t and t[0] else None
    except Exception as e:
        log("trace", repr(e))
        return None


def start(spec, pause):
    SAY({"cmd": "tut", "op": "free"})                 # free flight (restarts at the air start), then the wanted start
    if isinstance(spec, dict):
        SAY(dict(spec, cmd="place"))
    else:
        SAY({"cmd": "reset", "mode": spec})
    if pause:
        SAY({"cmd": "pause", "on": True})


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
                ST.update(phase="end", t=now)
                return
            name, spec, view, orb, kind = SHOTS[ST["i"]]
            if ST["start"] != (spec if not isinstance(spec, dict) else json.dumps(spec, sort_keys=True)) or kind == "crash":
                start(spec, kind != "crash")
                ST["start"] = spec if not isinstance(spec, dict) else json.dumps(spec, sort_keys=True)
                ST["t_start"] = now
            c.override = dict(FLY if kind == "crash" else HOLD if spec == "runway" else dict(HOLD, brk_l=0.0, brk_r=0.0, thr=0.75))
            c.set_view(view)
            if orb is not None:
                c.orbit[view] = list(orb)
            ST.update(phase="load", t=now)
        elif ph == "load":
            name, spec, view, orb, kind = SHOTS[ST["i"]]
            if orb is not None:
                c.orbit[view] = list(orb)
            if kind == "crash":
                tut = (c.s or {}).get("tut") or {}
                if tut.get("phase") == "crash":
                    ST["res"][name] = dict(crash=tut.get("crash"), t_flight_s=round(now - ST["t_start"], 1), lat=c.s.get("lat"), lon=c.s.get("lon"),
                                           alt_m=round(c.s.get("alt_m", 0), 1), terrain_m=c.s.get("terrain_m"), agl_m=round(c.s.get("agl_m", 0), 1))
                    ST.update(phase="shoot", t=now)
                elif el > 60.0:
                    ST["res"][name] = dict(crash=None, timeout=True, alt_m=c.s.get("alt_m"), terrain_m=c.s.get("terrain_m"), tut_phase=tut.get("phase"))
                    ST.update(phase="shoot", t=now)
                return
            p = progress()
            if (p is not None and p >= 99.9 and el > 5.0) or el > 45.0:
                ST["load"] = dict(load_s=round(el, 1), load_progress=p)
                ST.update(phase="shoot", t=now)
        elif ph == "shoot" and el > 1.5:
            name, spec, view, orb, kind = SHOTS[ST["i"]]
            shot(name)
            r = ST["res"].setdefault(name, {})
            r.update(ST.pop("load", {}), view=c.view, alt_m=round((c.s or {}).get("alt_m", 0), 1), terrain_m=(c.s or {}).get("terrain_m"),
                     agl_m=round((c.s or {}).get("agl_m", 0), 2), radar_m=None if c.radar_m is None else round(c.radar_m, 2))
            if kind in ("floor", "shot") and view != "cockpit":
                cam = c.camera.get_actor_location()
                g = ground_under(c, cam)
                r["camera_above_ground_m"] = None if g is None else round((cam.z - g) / 100.0, 2)
                if kind == "floor":
                    r["floor_ok"] = g is not None and cam.z - g >= 100.0
            log(name, json.dumps(r, default=str))
            ST["i"] += 1
            ST.update(phase="setup", t=now)
        elif ph == "end" and el > 2.0:
            c.override = None
            c.set_view("cockpit")
            SAY({"cmd": "tut", "op": "free"})
            SAY({"cmd": "pause", "on": False})
            r = checks()
            pb, pa = ST.get("proxy_before") or {}, r.get("proxy") or {}
            cr = ST["res"].get("crash", {})
            floors = [v.get("floor_ok") for k, v in ST["res"].items() if isinstance(v, dict) and "floor_ok" in v]
            res = dict(made=time.strftime("%Y-%m-%d %H:%M:%S"), checks=r, shots=ST["shots"], steps=ST["res"],
                       api_requests_this_check=(pa.get("used_today", 0) - pb.get("used_today", 0)) if pa and pb else None,
                       crash_ok=bool(cr.get("crash")), floor_ok=all(floors) and bool(floors),
                       ok=bool(r["ok"] and ST["res"]["setup"]["ok"] and cr.get("crash") and all(floors)))
            with open(os.path.join(OUT, "vworld_terrain_result.json"), "w", encoding="utf-8") as f:
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
log("scheduled", len(SHOTS), "shots ->", OUT)
