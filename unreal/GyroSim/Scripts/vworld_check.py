"""V-World ground mode check (developer use). Needs Config/cesium_token.txt with a 'vworld' line, sim/server.py running
(it starts the tile proxy sim/vworld_proxy.py) - or the proxy started on its own. Launch the editor with
-GyroSimVWorld (init_unreal.py) or exec inside the open editor. Few API calls: the aircraft stands still (runway start,
then the air start paused), tiles come from the proxy cache on later runs.
Checks: ground mode = vworld, overlay URL = the local proxy (no V-World host / key in Unreal), Sentinel-2 / Bing not on
the tileset, the source note is on screen, the proxy answers and served tiles. Screenshots (cockpit + chase, runway and
air) + vworld_result.json -> Saved/verify/vworld/. Proxy API count before / after goes into the result.
"""
import json, os, time
import unreal
import sim_client

log = lambda *a: unreal.log("[vworld] " + " ".join(str(x) for x in a))
les = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
ues = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem)
OUT = os.path.join(unreal.Paths.project_saved_dir(), "verify", "vworld")
os.makedirs(OUT, exist_ok=True)
C = sim_client.client
SAY = lambda m: C()._send(m)
HOLD = {"ail": 0.0, "elev": 0.0, "rud": 0.0, "brk_l": 1.0, "brk_r": 1.0, "thr": 0.0}
# (name, start mode, view, pause)
SHOTS = [("runway_cockpit", "runway", "cockpit", False), ("runway_chase", "runway", "chase", False),
         ("air_cockpit", "air", "cockpit", True), ("air_chase", "air", "chase", True), ("air_tower", "air", "tower", True)]
ST = dict(t=time.monotonic(), phase="wait_pie", i=0, h=None, res={}, shots=[], mode=None)


def shot(name):
    fn = os.path.join(OUT, name + ".png").replace("\\", "/")
    # viewport aspect (multiplier, not a fixed size): the source note sits in the corner of the real viewport
    unreal.SystemLibrary.execute_console_command(ues.get_game_world(), "HighResShot 1 filename=%s" % fn)
    ST["shots"].append(os.path.basename(fn))


def progress():
    c = C()
    try:
        return round(float(c.tileset.get_editor_property("load_progress")), 1) if c.tileset else None
    except Exception:
        return None


def checks():
    c = C()
    r = dict(ground=c.cesium_mode, terrain=getattr(c, "vw_terrain", None))
    ovs = {o.get_class().get_name(): o for o in c.tileset.get_components_by_class(unreal.CesiumRasterOverlay)} if c.tileset else {}
    url = ovs["CesiumUrlTemplateRasterOverlay"].get_editor_property("template_url") if "CesiumUrlTemplateRasterOverlay" in ovs else ""
    r["overlay_url"] = url
    r["overlay_max_level"] = ovs["CesiumUrlTemplateRasterOverlay"].get_editor_property("maximum_level") if url else None
    r["url_local_ok"] = url.startswith("http://127.0.0.1:") and "vworld.kr" not in url and "eox" not in url
    ion = ovs.get("CesiumIonRasterOverlay")
    r["ion_overlay_asset"] = ion.get_editor_property("ion_asset_id") if ion else None
    a = getattr(c, "attrib", None)
    r["attribution"] = dict(found=bool(a), hidden=bool(a.get_editor_property("hidden")) if a else None,
                            rel=[round(v, 1) for v in (a.root_component.get_editor_property("relative_location").to_tuple() if a else ())])
    st = c.vworld_status(1.0)
    r["proxy"] = st
    r["ok"] = (c.cesium_mode == "vworld" and r["url_local_ok"] and r["attribution"]["found"] and r["attribution"]["hidden"] is False
               and st is not None and r["overlay_max_level"] == sim_client.VW_MAX_LEVEL)
    return r


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
            name, mode, view, pause = SHOTS[ST["i"]]
            if ST["mode"] != mode:
                SAY({"cmd": "tut", "op": "free"})              # free flight first (it restarts at the air start), then the start
                SAY({"cmd": "reset", "mode": mode})
                if pause:
                    SAY({"cmd": "pause", "on": True})
                ST["mode"] = mode
            c.override = dict(HOLD) if mode == "runway" else dict(HOLD, brk_l=0.0, brk_r=0.0, thr=0.75)
            c.set_view(view)
            ST.update(phase="load", t=now, t_load=now)
        elif ph == "load":
            mode, pause = SHOTS[ST["i"]][1], SHOTS[ST["i"]][3]
            if c.s.get("mode") != mode and el > 0.8 and now - ST.get("resent", 0) > 1.0:   # the first reset can be lost at Play start
                ST["resent"] = now
                SAY({"cmd": "tut", "op": "free"})              # free flight first (it restarts at the air start), then the start
                SAY({"cmd": "reset", "mode": mode})
                if pause:
                    SAY({"cmd": "pause", "on": True})
            p = progress()
            if (p is not None and p >= 99.9 and el > 4.0) or el > 40.0:
                ST["load_s"] = round(el, 1)
                ST["load_pct"] = p
                ST.update(phase="shoot", t=now)
        elif ph == "shoot" and el > 1.0:
            name = SHOTS[ST["i"]][0]
            shot(name)
            ST["res"][name] = dict(load_s=ST["load_s"], load_progress=ST["load_pct"], view=c.view, alt_m=round(c.s.get("alt_m", 0), 1))
            log(name, json.dumps(ST["res"][name]))
            ST["i"] += 1
            ST.update(phase="setup", t=now)
        elif ph == "end" and el > 1.5:
            c.override = None
            c.set_view("cockpit")
            SAY({"cmd": "pause", "on": False})
            r = checks()
            pb, pa = ST.get("proxy_before") or {}, r.get("proxy") or {}
            res = dict(made=time.strftime("%Y-%m-%d %H:%M:%S"), checks=r, shots=ST["shots"], steps=ST["res"],
                       api_requests_this_check=(pa.get("used_today", 0) - pb.get("used_today", 0)) if pa and pb else None,
                       ok=r["ok"] and ST["res"]["setup"]["ok"])
            with open(os.path.join(OUT, "vworld_result.json"), "w", encoding="utf-8") as f:
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
