"""Busan colour grade before / after shots + GPU time (developer use, Content/Python/grade_look.py), without the sim server.
Launch a SECOND editor, never visible:
    UnrealEditor.exe GyroSim.uproject /Game/Maps/FlightMap -GyroSimGradeShots -RenderOffscreen -nosplash -ABSLOG=<file>
(init_unreal.py; GYROSIM_GSHOT_LOG = the same log file, for the GPU numbers). Its own sim client is stopped first (no UDP to
the user's server), Play starts, Cesium is set up like sim_client from the local folders (terrain tiles + V-World photo
cache by file://, no proxy, no API call), local buildings with M_GyroBuilding, roads / landmarks / trees via their *_look
modules, air / light via sim_client.apply_preset (realism v2 + atmos_look + grade_look) - i.e. the Play look.
Variants (GYROSIM_GSHOT_VARIANTS = JSON file; default before = legacy, after = grade):
    [{"name": .., "mode": "grade" | "legacy" | "map", "pp": {key: value, ..}}, ..]   (pp = grade_look.apply extra overrides)
Views: (name, camera lat, lon, alt m MSL, heading deg, pitch deg, horizontal fov deg); the georeference origin is moved to
each camera (like trees_shots), camera at the origin. GYROSIM_GSHOT_VIEWS = comma list to pick.
Out: GYROSIM_SHOTS_DIR (default C:/GyroSimTiles/shots/grade - V-World imagery stays outside git), shots.json.
Quits the editor when done. Only one offscreen editor at a time: the caller holds C:/GyroSimTiles/ue_offscreen.lock.
"""
import json, math, os, re, time
import unreal
import photo_src                      # V-World photo with the white-gap fix (cache-only proxy), as at Play
import sim_client
import roads_look
import trees_look
import landmarks_look
import grade_look

log = lambda *a: unreal.log("[gshots] " + " ".join(str(x) for x in a))
les = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
ues = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem)
OUT = os.environ.get("GYROSIM_SHOTS_DIR", r"C:\GyroSimTiles\shots\grade")
os.makedirs(OUT, exist_ok=True)
ROOT = r"C:/GyroSimTiles/buildings"
GEOID = 29.2
# the atmos_shots views (camera spots of C:/GyroSimTiles/refs/busan_atmos photos, estimates) + views matched to the
# C:/GyroSimTiles/refs/grade set (estimates) + flight-height views
VIEWS = [("r01_dongu", 35.110, 129.032, 150.0, 40.0, -15.0, 75.0),
         ("r02_oryukdo", 35.100, 129.122, 80.0, 160.0, -8.0, 75.0),
         ("r04_yeongdo", 35.083, 129.050, 200.0, 250.0, -6.0, 40.0),
         ("r05_nampo", 35.1008, 129.0325, 170.0, 200.0, -38.0, 75.0),
         ("r07_taejongdae", 35.0470, 129.0800, 120.0, 30.0, -28.0, 75.0),
         ("r11_harbor", 35.1008, 129.0325, 170.0, 60.0, -8.0, 60.0),
         ("g_haeundae_marine", 35.1530, 129.1450, 250.0, 240.0, -12.0, 70.0),
         ("g_gwangan_hwang", 35.1572, 129.0820, 450.0, 110.0, -8.0, 70.0),
         ("g_haeundae_beach", 35.1560, 129.1700, 200.0, 250.0, -10.0, 70.0),
         ("g_seomyeon_400", 35.1500, 129.0500, 400.0, 20.0, -15.0, 70.0),     # over Seomyeon toward Geumjeongsan
         ("g_suyeong_300", 35.1600, 129.1150, 300.0, 30.0, -15.0, 70.0),      # Suyeong river / Centum City
         ("f1_haeundae_1000", 35.120, 129.200, 1000.0, 300.0, -12.0, 75.0),
         ("f3_city_1500", 35.080, 129.060, 1500.0, 0.0, -20.0, 75.0)]
if os.environ.get("GYROSIM_GSHOT_VIEWS"):
    VIEWS = [v for v in VIEWS if v[0] in os.environ["GYROSIM_GSHOT_VIEWS"].split(",")]
VARIANTS = [dict(name="before", mode="legacy"), dict(name="after", mode="grade")]
if os.environ.get("GYROSIM_GSHOT_VARIANTS"):
    VARIANTS = json.load(open(os.environ["GYROSIM_GSHOT_VARIANTS"], encoding="utf-8-sig"))
GPU_VIEWS = [x for x in os.environ.get("GYROSIM_GSHOT_GPU", "f1_haeundae_1000,r11_harbor").split(",") if x]
LOGF = os.environ.get("GYROSIM_GSHOT_LOG", "")
ST = dict(t=time.monotonic(), t0=time.monotonic(), phase="wait_editor", si=0, vi=0, h=None, res={}, gpu=[])


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
    ov.set_editor_property("template_url", photo_src.template())
    ov.set_editor_property("minimum_level", 6)
    ov.set_editor_property("maximum_level", 19)
    ov.set_maximum_screen_space_error(1.0)
    ov.set_maximum_simultaneous_tile_loads(8)
    ov.add_to_tileset()
    ov.set_active(True)
    try:                                       # sea surface + photo colour match, as in Play
        import atmos_look
        atmos_look.apply_ground(ts)
    except Exception as e:
        log("ground look", repr(e))
    ts.refresh_tileset()
    b.set_actor_location_and_rotation(unreal.Vector(0, 0, 0), rot, False, True)
    b.set_editor_property("tileset_source", unreal.TilesetSource.FROM_URL)
    for k, v in (("maximum_screen_space_error", 16.0), ("create_physics_meshes", False), ("show_credits_on_screen", False)):
        b.set_editor_property(k, v)
    b.set_editor_property("url", "file:///%s/tiles/tileset.json" % ROOT)
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
    return gr, ts, b


def set_variant(v):
    sim_client.apply_look("monitor", ST["w"])          # resets the keys other modules own (vignette, bloom ..) first
    grade_look.apply(ST["w"], "monitor", m=v.get("mode", "grade"), extra=v.get("pp"))
    log("variant", json.dumps(v)[:300])


def place_view(vw):
    name, lat, lon, alt, hdg, pitch, fov = vw
    ST["gr"].set_origin_longitude_latitude_height(unreal.Vector(lon, lat, GEOID))
    ST["cam"].set_actor_location_and_rotation(unreal.Vector(0.0, 0.0, alt * 100.0),
                                              unreal.Rotator(roll=0.0, pitch=pitch, yaw=hdg), False, True)
    ST["cam"].camera_component.set_editor_property("field_of_view", fov)


def gpu_from_log():
    try:
        with open(LOGF, encoding="utf-8", errors="ignore") as f:
            txt = f.read()[-300000:]
        g = re.findall(r"Average GPU frametime: ([\d.]+) ms", txt)
        return float(g[-1]) if g else None
    except OSError:
        return None


def tick(dt):
    try:
        now = time.monotonic()
        el = now - ST["t"]
        ph = ST["phase"]
        if ph == "wait_editor" and el > float(os.environ.get("GYROSIM_GSHOT_WAIT", "40")):
            for m in (roads_look, landmarks_look, trees_look):       # editor-world actors before Play (never saved)
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
                pc = unreal.GameplayStatics.get_player_controller(w, 0)
                pc.set_view_target_with_blend(cam, 0.0)
                try:
                    sim_client.apply_preset("monitor", w)          # realism v2 + atmos_look + grade_look, as in Play
                except Exception as e:
                    log("preset", repr(e))
                cmd("t.MaxFPS 0"); cmd("r.VSync 0"); cmd("t.FPSChart.OpenFolderOnDump 0")
                ST.update(phase="view", t=now, vi=0)
            elif el > 120:
                log("no PIE world"); ST.update(phase="end", t=now)
        elif ph == "view" and el > 1.0:
            if ST["vi"] >= len(VIEWS):
                ST.update(phase="end", t=now); return
            pc = unreal.GameplayStatics.get_player_controller(ST["w"], 0)
            pc.set_view_target_with_blend(ST["cam"], 0.0)
            place_view(VIEWS[ST["vi"]])
            ST.update(phase="load", t=now, si=0)
        elif ph == "load":
            ps = [progress(ST["ts"]), progress(ST["b"])] + [progress(x) for x in ST.get("extra", [])]
            if (min(ps) >= 99.9 and el > 8.0) or el > 120.0:
                ST["load"] = dict(load_s=round(el, 1), progress=[round(p, 1) for p in ps])
                ST.update(phase="variant", t=now)
        elif ph == "variant":
            if ST["si"] >= len(VARIANTS):
                ST["vi"] += 1
                ST.update(phase="view", t=now); return
            set_variant(VARIANTS[ST["si"]])
            ST.update(phase="shoot", t=now)
        elif ph == "shoot" and el > float(os.environ.get("GYROSIM_GSHOT_SETTLE", "4")):     # auto exposure settles
            vw, v = VIEWS[ST["vi"]], VARIANTS[ST["si"]]
            fn = os.path.join(OUT, "%s_%s.png" % (vw[0], v["name"])).replace("\\", "/")
            cmd("HighResShot %s filename=%s" % (os.environ.get("GYROSIM_SHOT_RES", "1600x900"), fn))
            ST["res"]["%s_%s" % (vw[0], v["name"])] = dict(ST.get("load", {}), file=fn)
            log("shot", fn)
            if vw[0] in GPU_VIEWS and LOGF and v.get("gpu", True):
                ST.update(phase="gpu_warm", t=now)
            else:
                ST["si"] += 1
                ST.update(phase="variant", t=now)
        elif ph == "gpu_warm" and el > 3.0:
            vp = unreal.WidgetLayoutLibrary.get_viewport_size(ST["w"])
            sp = max(25.0, min(400.0, 100.0 * math.sqrt(1920 * 1080 / max(1.0, vp.x * vp.y))))
            ST["sp"] = (round(vp.x), round(vp.y), round(sp))
            cmd("r.ScreenPercentage %.0f" % sp)
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
            vw, v = VIEWS[ST["vi"]], VARIANTS[ST["si"]]
            d = sorted(ST["dts"][5:])
            r = dict(view=vw[0], variant=v["name"], gpu_ms=gpu_from_log(), viewport=ST["sp"][:2], screen_percentage=ST["sp"][2],
                     frames=len(d), avg_ms=round(sum(d) / len(d) * 1000, 2) if d else None)
            ST["gpu"].append(r)
            log("gpu", json.dumps(r))
            cmd("r.ScreenPercentage 100")
            ST["si"] += 1
            ST.update(phase="variant", t=now)
        elif ph == "end" and el > 2.0:
            res = dict(made=time.strftime("%Y-%m-%d %H:%M:%S"), seconds=round(now - ST["t0"]), views=VIEWS, variants=VARIANTS,
                       grade=grade_look.GRADE, legacy=grade_look.LEGACY, shots=ST["res"], gpu=ST["gpu"],
                       note="editor PIE without the sim server; local tiles; map lighting + monitor preset (realism v2, atmos_look) + grade_look variant")
            with open(os.path.join(OUT, "shots.json"), "w", encoding="utf-8") as f:
                json.dump(res, f, indent=1, ensure_ascii=False, default=str)
            log("done ->", OUT)
            les.editor_request_end_play()
            ST.update(phase="quit", t=now)
        elif ph == "quit" and el > 3.0:
            unreal.unregister_slate_post_tick_callback(ST["h"])
            if os.environ.get("GYROSIM_GSHOT_QUIT", "1") == "1":
                unreal.SystemLibrary.quit_editor()
    except Exception as e:
        import traceback
        log("error", repr(e), " | ".join(traceback.format_exc().splitlines()))
        ST.update(phase="end" if ST["phase"] not in ("end", "quit") else "quit", t=time.monotonic())


sim_client.stop()                      # this editor must not talk to a running server (the user's session)
ST["h"] = unreal.register_slate_post_tick_callback(tick)
log("scheduled", len(VARIANTS), "variants x", len(VIEWS), "views ->", OUT)
