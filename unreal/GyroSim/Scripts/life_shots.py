"""Busan 'life' layer check (developer use): moving cars / ships shots, a frame sequence and GPU with life on / off,
without the sim server. A SECOND editor, never visible (the caller holds C:/GyroSimTiles/ue_offscreen.lock):
    UnrealEditor.exe GyroSim.uproject /Game/Maps/FlightMap -GyroSimLifeShots -RenderOffscreen -nosplash -unattended -nosound -ABSLOG=<log>
Same set-up as art_shots.py (local terrain + V-World cache by file://, buildings / roads / landmarks / trees, monitor
preset) + life_look.apply. Motion is frozen per shot with life_look.set_time (TFix) so shots repeat exactly.
Env:
  GYROSIM_LIFE_VIEWS  JSON file [[name, lat, lon, alt m MSL, heading, pitch, fov, {"t": s, "seq": [n, dt], "gpu": 1}], ..]
  GYROSIM_LIFE_LOG    the -ABSLOG file (GPU numbers are read from it)
  GYROSIM_SHOTS_DIR   output folder (default C:/GyroSimTiles/shots/life), result shots_life.json
Quits the editor when done.
"""
import json, math, os, re, time
import unreal
import sim_client
import roads_look
import trees_look
import landmarks_look
import life_look

log = lambda *a: unreal.log("[lifeshots] " + " ".join(str(x) for x in a))
les = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
ues = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem)
OUT = os.environ.get("GYROSIM_SHOTS_DIR", r"C:\GyroSimTiles\shots\life")
os.makedirs(OUT, exist_ok=True)
GEOID = 29.2
VIEWS = json.load(open(os.environ["GYROSIM_LIFE_VIEWS"], encoding="utf-8-sig"))
LOGF = os.environ.get("GYROSIM_LIFE_LOG", "")
ST = dict(t=time.monotonic(), t0=time.monotonic(), phase="wait_editor", vi=0, h=None, res={}, gpu=[], q=[])


def cmd(c):
    unreal.SystemLibrary.execute_console_command(ues.get_game_world(), c)


def find(world, tag):
    a = unreal.GameplayStatics.get_all_actors_with_tag(world, tag)
    return a[0] if a else None


def progress(ts):
    try:
        return float(ts.get_editor_property("load_progress"))
    except Exception:
        return 100.0


def setup_cesium(world):
    gr, ts, b = find(world, "CesiumGeoreference"), find(world, "CesiumGround"), find(world, "CesiumBuildings")
    grid = find(world, "GridGround")
    if grid:
        grid.set_actor_hidden_in_game(True)
    for a in unreal.GameplayStatics.get_all_actors_with_tag(world, "Airfield"):
        a.set_actor_hidden_in_game(True)
    rot = unreal.Rotator(roll=0, pitch=0, yaw=90.0)
    ts.set_actor_location_and_rotation(unreal.Vector(0, 0, 0), rot, False, True)
    ts.set_actor_hidden_in_game(False)
    ts.set_editor_property("tileset_source", unreal.TilesetSource.FROM_URL)
    ts.set_editor_property("url", "file:///C:/GyroSimTiles/terrain/tiles/layer.json")
    ovs = {c.get_class().get_name(): c for c in ts.get_components_by_class(unreal.CesiumRasterOverlay)}
    for o in ovs.values():
        o.remove_from_tileset()
    ov = ovs.get("CesiumUrlTemplateRasterOverlay")
    ov.set_editor_property("template_url", "file:///C:/GyroSimTiles/vworld/Satellite/{z}/{reverseY}/{x}.jpg")
    ov.set_editor_property("minimum_level", 6)
    ov.set_editor_property("maximum_level", 19)
    ov.set_maximum_screen_space_error(1.0)
    ov.set_maximum_simultaneous_tile_loads(8)
    ov.add_to_tileset()
    ov.set_active(True)
    try:
        import atmos_look
        atmos_look.apply_ground(ts)
    except Exception as e:
        log("ground look", repr(e))
    ts.refresh_tileset()
    b.set_actor_location_and_rotation(unreal.Vector(0, 0, 0), rot, False, True)
    b.set_editor_property("tileset_source", unreal.TilesetSource.FROM_URL)
    for k, v in (("maximum_screen_space_error", 16.0), ("create_physics_meshes", False), ("show_credits_on_screen", False)):
        b.set_editor_property(k, v)
    b.set_editor_property("url", "file:///C:/GyroSimTiles/buildings/tiles/tileset.json")
    try:
        import buildings_look
        if not buildings_look.apply(b, lambda m: log(m)):
            m = unreal.load_asset(buildings_look.MAT)
            if m:
                b.set_editor_property("material", m)
    except Exception as e:
        log("buildings look", repr(e))
    b.set_actor_hidden_in_game(False)
    b.refresh_tileset()
    ST["extra"] = [x for x in (roads_look.apply(world, log, gr), landmarks_look.apply(world, log, gr),
                               trees_look.apply(world, log, gr)) if x is not None]
    t0 = time.monotonic()
    ST["life"] = life_look.apply(world, log, gr)
    ST["life_fill_s"] = round(time.monotonic() - t0, 2)
    return gr, ts, b


def place_view(vw):
    name, lat, lon, alt, hdg, pitch, fov = vw[:7]
    ST["gr"].set_origin_longitude_latitude_height(unreal.Vector(lon, lat, GEOID))
    life_look.follow_now()
    ST["cam"].set_actor_location_and_rotation(unreal.Vector(0.0, 0.0, alt * 100.0), unreal.Rotator(roll=0.0, pitch=pitch, yaw=hdg), False, True)
    ST["cam"].camera_component.set_editor_property("field_of_view", fov)


def gpu_from_log():
    try:
        with open(LOGF, encoding="utf-8", errors="ignore") as f:
            txt = f.read()[-300000:]
        g = re.findall(r"Average GPU frametime: ([\d.]+) ms", txt)
        return float(g[-1]) if g else None
    except OSError:
        return None


def plan(vw):
    """the steps of one view: shots (tag, t) then GPU on / off."""
    o = vw[7] if len(vw) > 7 else {}
    t = float(o.get("t", 100.0))
    q = [("shot", "", t)]
    if o.get("seq"):
        n, dt = o["seq"]
        q += [("shot", "_f%02d" % i, t + i * dt) for i in range(int(n))]
    if o.get("off"):
        q.append(("shot_off", "_off", t))
    if o.get("gpu"):
        q += [("gpu", "on", t), ("gpu", "off", t)]
    return q


def life_vis(on):
    a = life_look.find(ST["w"])
    if a is not None:
        a.set_actor_hidden_in_game(not on)


def tick(dt):
    try:
        now = time.monotonic()
        el = now - ST["t"]
        ph = ST["phase"]
        if ph == "wait_editor" and el > float(os.environ.get("GYROSIM_ART_WAIT", "40")):
            for m in (roads_look, landmarks_look, trees_look, life_look):
                try:
                    m.spawn_editor(log)
                except Exception as e:
                    log("spawn", repr(e))
            les.editor_request_begin_play()
            ST.update(phase="wait_pie", t=now)
        elif ph == "wait_pie":
            w = ues.get_game_world()
            if w is not None and el > 3.0:
                ST["w"] = w
                ST["gr"], ST["ts"], ST["b"] = setup_cesium(w)
                cam = ST["cam"] = find(w, "SimView")
                rule = unreal.DetachmentRule.KEEP_WORLD
                cam.detach_from_actor(rule, rule, rule)
                for tag in ("Aircraft", "SimCamera", "Canopy", "Gear", "Pilot", "CockpitFill"):
                    for a in unreal.GameplayStatics.get_all_actors_with_tag(w, tag):
                        for x in [a] + list(a.get_attached_actors(True) if hasattr(a, "get_attached_actors") else []):
                            if x != cam:
                                x.set_actor_hidden_in_game(True)
                cam.camera_component.set_editor_property("constrain_aspect_ratio", False)
                unreal.GameplayStatics.get_player_controller(w, 0).set_view_target_with_blend(cam, 0.0)
                try:
                    sim_client.apply_preset("monitor", w)
                except Exception as e:
                    log("preset", repr(e))
                cmd("t.MaxFPS 0"); cmd("r.VSync 0"); cmd("t.FPSChart.OpenFolderOnDump 0")
                ST.update(phase="view", t=now, vi=0)
            elif el > 120:
                log("no PIE world"); ST.update(phase="end", t=now)
        elif ph == "view" and el > 1.0:
            if ST["vi"] >= len(VIEWS):
                ST.update(phase="end", t=now); return
            unreal.GameplayStatics.get_player_controller(ST["w"], 0).set_view_target_with_blend(ST["cam"], 0.0)
            place_view(VIEWS[ST["vi"]])
            ST["q"] = plan(VIEWS[ST["vi"]])
            ST.update(phase="load", t=now)
        elif ph == "load":
            ps = [progress(ST["ts"]), progress(ST["b"])] + [progress(x) for x in ST.get("extra", [])]
            if (min(ps) >= 99.9 and el > 8.0) or el > 120.0:
                ST["load"] = dict(load_s=round(el, 1), progress=[round(p, 1) for p in ps])
                ST.update(phase="step", t=now)
        elif ph == "step":
            if not ST["q"]:
                life_vis(True)
                ST["vi"] += 1
                ST.update(phase="view", t=now); return
            kind, tag, t = ST["q"][0]
            life_vis(kind != "shot_off" and not (kind == "gpu" and tag == "off"))
            life_look.set_time(ST["w"], t)
            ST.update(phase="settle", t=now)
        elif ph == "settle" and el > (5.0 if ST["q"][0][1] in ("", "_off", "on", "off") else 1.2):
            kind, tag, t = ST["q"][0]
            vw = VIEWS[ST["vi"]]
            if kind in ("shot", "shot_off"):
                fn = os.path.join(OUT, "%s%s.png" % (vw[0], tag)).replace("\\", "/")
                cmd("HighResShot %s filename=%s" % (os.environ.get("GYROSIM_SHOT_RES", "1600x900"), fn))
                ST["res"][vw[0] + tag] = dict(ST.get("load", {}), file=fn, t=t)
                log("shot", fn, "t", t)
                ST["q"].pop(0)
                ST.update(phase="step", t=now)
            else:
                vp = unreal.WidgetLayoutLibrary.get_viewport_size(ST["w"])
                sp = max(25.0, min(400.0, 100.0 * math.sqrt(1920 * 1080 / max(1.0, vp.x * vp.y))))
                ST["sp"] = (round(vp.x), round(vp.y), round(sp))
                cmd("r.ScreenPercentage %.0f" % sp)
                life_look.set_time(ST["w"], None)            # live motion while measuring (WPO every frame)
                ST.update(phase="gpu_start", t=now)
        elif ph == "gpu_start" and el > 3.0:
            cmd("startfpschart")
            ST.update(phase="gpu_run", t=now, dts=[])
        elif ph == "gpu_run":
            ST["dts"].append(dt)
            if el > 10.0:
                cmd("stopfpschart")
                ST.update(phase="gpu_collect", t=now)
        elif ph == "gpu_collect" and el > 1.0:
            kind, tag, t = ST["q"].pop(0)
            d = sorted(ST["dts"][5:])
            r = dict(view=VIEWS[ST["vi"]][0], life=tag, gpu_ms=gpu_from_log(), viewport=ST["sp"][:2], screen_percentage=ST["sp"][2],
                     frames=len(d), avg_ms=round(sum(d) / len(d) * 1000, 2) if d else None)
            ST["gpu"].append(r)
            log("gpu", json.dumps(r))
            cmd("r.ScreenPercentage 100")
            ST.update(phase="step", t=now)
        elif ph == "end" and el > 2.0:
            env = {k: v for k, v in os.environ.items() if k.startswith("GYROSIM_")
                   and not any(s in k.upper() for s in ("KEY", "TOKEN", "SECRET", "PASS", "AUTH"))}
            res = dict(made=time.strftime("%Y-%m-%d %H:%M:%S"), seconds=round(now - ST["t0"]), views=VIEWS, env=env, shots=ST["res"],
                       gpu=ST["gpu"], life_counts=life_look.ST.get("counts"), life_fill_s=ST.get("life_fill_s"),
                       note="editor PIE without the sim server; local tiles; monitor preset; motion frozen per shot (TFix)")
            with open(os.path.join(OUT, "shots_life.json"), "w", encoding="utf-8") as f:
                json.dump(res, f, indent=1, ensure_ascii=False, default=str)
            log("done ->", OUT)
            les.editor_request_end_play()
            ST.update(phase="quit", t=now)
        elif ph == "quit" and el > 3.0:
            unreal.unregister_slate_post_tick_callback(ST["h"])
            if os.environ.get("GYROSIM_ART_QUIT", "1") == "1":
                unreal.SystemLibrary.quit_editor()
    except Exception as e:
        import traceback
        log("error", repr(e), " | ".join(traceback.format_exc().splitlines()))
        ST.update(phase="end" if ST["phase"] not in ("end", "quit") else "quit", t=time.monotonic())


sim_client.stop()                      # this editor must not talk to a running server (the user's session)
ST["h"] = unreal.register_slate_post_tick_callback(tick)
log("scheduled", len(VIEWS), "views ->", OUT)
