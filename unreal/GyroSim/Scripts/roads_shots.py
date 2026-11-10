"""Before / after shots of the OSM bridges / elevated roads over Busan (developer use, sim/roads_build.py tiles), without
the sim server. Launch a SECOND editor, never visible:
    UnrealEditor.exe GyroSim.uproject /Game/Maps/FlightMap -GyroSimRoadShots -RenderOffscreen -nosplash -ABSLOG=<file>
(init_unreal.py; -ExecutePythonScript would quit the editor right after the script; GYROSIM_RSHOT_LOG = the same log file, for the GPU numbers). Its own sim client is stopped first (no UDP to the user's
server), Play starts, Cesium is set up like sim_client (V-World photo on the local terrain from the proxy, local buildings
with M_GyroBuilding), roads via Content/Python/roads_look.apply (the same call sim_client makes), before = roads hidden,
after = roads shown. Out: GYROSIM_SHOTS_DIR (default C:/GyroSimTiles/shots/roads - V-World imagery stays outside git),
shots.json. Quits the editor when done. Only one offscreen editor at a time: the caller holds C:/GyroSimTiles/ue_offscreen.lock.
"""
import json, math, os, re, time
import unreal
import sim_client
import roads_look

log = lambda *a: unreal.log("[rshots] " + " ".join(str(x) for x in a))
les = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
ues = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem)
OUT = os.environ.get("GYROSIM_SHOTS_DIR", r"C:\GyroSimTiles\shots\roads")
os.makedirs(OUT, exist_ok=True)
ROOT = r"C:/GyroSimTiles/buildings"
STATES = os.environ.get("GYROSIM_RSHOT_STATES", "before,after").split(",")
GEOID = 29.2
PORT = int(os.environ.get("GYROSIM_RSHOT_PORT", "0")) or (sim_client.SimClient.vworld_port() if hasattr(sim_client, "SimClient") else 8790)
# (name, target lat, lon, target height m MSL, camera bearing from the target deg, horizontal distance m, camera height m MSL)
VIEWS = [("gwangan_300", 35.14575, 129.1284, 40.0, 120.0, 900.0, 300.0),      # 광안대교 main span from the sea side, 300 m up
         ("gwangan_close", 35.14575, 129.1284, 40.0, 35.0, 420.0, 80.0),     # towers / cables / deck, low
         ("gwangan_top", 35.1442, 129.1269, 40.0, 0.0, 0.5, 520.0),          # straight down: deck vs photo bridge
         ("bhb_300", 35.10587, 129.0652, 50.0, 250.0, 1100.0, 300.0),        # 부산항대교 from the west
         ("bhb_top", 35.10587, 129.0652, 50.0, 0.0, 0.5, 650.0),
         ("overpass_300", 35.15148, 129.05535, 15.0, 200.0, 700.0, 300.0),   # 동서고가로 (범천 / 서면 남쪽)
         ("overpass_close", 35.15148, 129.05535, 15.0, 150.0, 260.0, 70.0),
         ("overpass_top", 35.15148, 129.05535, 15.0, 0.0, 0.5, 380.0),
         ("nakdong_300", 35.2160, 128.9978, 12.0, 160.0, 900.0, 300.0),      # 구포낙동강교
         ("nakdong_top", 35.2160, 128.9978, 12.0, 0.0, 0.5, 450.0)]
if os.environ.get("GYROSIM_RSHOT_VIEWS"):
    VIEWS = [v for v in VIEWS if v[0] in os.environ["GYROSIM_RSHOT_VIEWS"].split(",")]
GPU_VIEWS = os.environ.get("GYROSIM_RSHOT_GPU", "gwangan_300,overpass_300").split(",")
LOGF = os.environ.get("GYROSIM_RSHOT_LOG", "")
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
    ts.set_editor_property("url", "http://127.0.0.1:%d/terrain/layer.json" % PORT)
    ovs = {c.get_class().get_name(): c for c in ts.get_components_by_class(unreal.CesiumRasterOverlay)}
    for o in ovs.values():
        o.remove_from_tileset()
    ov = ovs.get("CesiumUrlTemplateRasterOverlay")
    ov.set_editor_property("template_url", "http://127.0.0.1:%d/vworld/sat/{z}/{reverseY}/{x}.jpg" % PORT)
    ov.set_editor_property("minimum_level", 0)
    ov.set_editor_property("maximum_level", 19)
    ov.set_maximum_screen_space_error(1.0)
    ov.set_maximum_simultaneous_tile_loads(8)
    ov.add_to_tileset()
    ov.set_active(True)
    ts.refresh_tileset()
    b.set_actor_location_and_rotation(unreal.Vector(0, 0, 0), rot, False, True)
    b.set_editor_property("tileset_source", unreal.TilesetSource.FROM_URL)
    for k, v in (("maximum_screen_space_error", 16.0), ("create_physics_meshes", False), ("show_credits_on_screen", False)):
        b.set_editor_property(k, v)
    b.set_editor_property("url", "file:///%s/tiles/tileset.json" % ROOT)
    m = unreal.load_asset("/Game/Buildings/M_GyroBuilding") if unreal.EditorAssetLibrary.does_asset_exist("/Game/Buildings/M_GyroBuilding") else None
    b.set_editor_property("material", m)
    b.set_actor_hidden_in_game(False)
    b.refresh_tileset()
    ST["roads"] = roads_look.apply(world, log, gr)
    return gr, ts, b


def set_state(st):
    r = ST.get("roads")
    if r is not None:
        r.set_actor_hidden_in_game(st == "before")
    log("state", st, "roads", "none" if r is None else ("hidden" if st == "before" else "shown"))


def place_view(v):
    name, lat, lon, th, brg, dist, ch = v
    ST["gr"].set_origin_longitude_latitude_height(unreal.Vector(lon, lat, GEOID))
    # local frame (tilesets yaw 90 like sim_client): X north, Y east, Z up, cm; z 0 = the origin height (~MSL)
    br = math.radians(brg)
    n, e = dist * math.cos(br), dist * math.sin(br)
    cam = unreal.Vector(n * 100.0, e * 100.0, ch * 100.0)
    tgt = unreal.Vector(0.0, 0.0, th * 100.0)
    d = tgt - cam
    yaw = math.degrees(math.atan2(d.y, d.x))
    pitch = math.degrees(math.atan2(d.z, math.hypot(d.x, d.y)))
    ST["cam"].set_actor_location_and_rotation(cam, unreal.Rotator(roll=0, pitch=pitch, yaw=yaw), False, True)


def gpu_from_log():
    try:
        with open(LOGF, encoding="utf-8", errors="ignore") as f:
            txt = f.read()[-300000:]
        g = re.findall(r"Average GPU frametime: ([\d.]+) ms", txt)
        return float(g[-1]) if g else None
    except OSError:
        return None


def probe():
    """log which spawn / component / PIE hooks this Python build exposes (roads_look needs one that works in Play)."""
    for nm in ("GameplayStatics", "EditorActorSubsystem", "LevelEditorSubsystem", "UnrealEditorSubsystem", "Actor", "World", "EditorLevelLibrary", "ChildActorComponent", "Package", "EditorLoadingAndSavingUtils", "EditorAssetLibrary"):
        c = getattr(unreal, nm, None)
        if c is None:
            continue
        ks = [k for k in dir(c) if any(w in k for w in ("spawn", "component", "pie", "play", "child", "world", "dirty", "transient"))]
        log("probe", nm, ",".join(ks)[:1500])


def tick(dt):
    try:
        now = time.monotonic()
        el = now - ST["t"]
        ph = ST["phase"]
        if ph == "wait_editor" and el > float(os.environ.get("GYROSIM_RSHOT_WAIT", "40")):
            probe()
            if os.environ.get("GYROSIM_RSHOT_PRESPAWN", "1") == "1":     # editor-world actor before Play (PIE copies it)
                roads_look.spawn_editor(log)
            les.editor_request_begin_play()
            ST.update(phase="wait_pie", t=now)
        elif ph == "wait_pie":
            w = ues.get_game_world()
            if w is not None and el > 3.0:
                ST["w"] = w
                ST["gr"], ST["ts"], ST["b"] = setup_cesium(w)
                cam = ST["cam"] = find(w, "SimView")          # the map's view camera, taken off the rig
                rule = unreal.DetachmentRule.KEEP_WORLD
                cam.detach_from_actor(rule, rule, rule)
                hidden = 0
                for tag in ("Aircraft", "SimCamera", "Canopy", "Gear", "Pilot", "CockpitFill"):   # nothing of the jet / rig in view
                    for a in unreal.GameplayStatics.get_all_actors_with_tag(w, tag):
                        for x in [a] + list(a.get_attached_actors(True) if hasattr(a, "get_attached_actors") else []):
                            if x != cam:
                                x.set_actor_hidden_in_game(True)
                                hidden += 1
                log("hidden actors", hidden)
                ST["cam"].camera_component.set_editor_property("field_of_view", 70.0)
                ST["cam"].camera_component.set_editor_property("constrain_aspect_ratio", False)
                pc = unreal.GameplayStatics.get_player_controller(w, 0)
                pc.set_view_target_with_blend(ST["cam"], 0.0)
                try:
                    sim_client.apply_preset("monitor", w)
                except Exception as e:
                    log("preset", repr(e))
                cmd("t.MaxFPS 0"); cmd("r.VSync 0"); cmd("t.FPSChart.OpenFolderOnDump 0")
                ST.update(phase="state", t=now)
            elif el > 120:
                log("no PIE world"); ST.update(phase="end", t=now)
        elif ph == "state":
            if ST["si"] >= len(STATES):
                ST.update(phase="end", t=now); return
            set_state(STATES[ST["si"]])
            ST.update(phase="view", t=now, vi=0)
        elif ph == "view" and el > 1.0:
            if ST["vi"] >= len(VIEWS):
                ST["si"] += 1
                ST.update(phase="state", t=now); return
            pc = unreal.GameplayStatics.get_player_controller(ST["w"], 0)
            pc.set_view_target_with_blend(ST["cam"], 0.0)
            place_view(VIEWS[ST["vi"]])
            ST.update(phase="load", t=now)
        elif ph == "load":
            p1, p2 = progress(ST["ts"]), progress(ST["b"])
            p3 = progress(ST["roads"]) if ST.get("roads") is not None else 100.0
            if (p1 >= 99.9 and p2 >= 99.9 and p3 >= 99.9 and el > 6.0) or el > 90.0:
                ST["load"] = dict(load_s=round(el, 1), terrain=round(p1, 1), buildings=round(p2, 1), roads=round(p3, 1))
                ST.update(phase="shoot", t=now)
        elif ph == "shoot" and el > 3.0:
            v, st = VIEWS[ST["vi"]], STATES[ST["si"]]
            fn = os.path.join(OUT, "%s_%s.png" % (v[0], st)).replace("\\", "/")
            cmd("HighResShot %s filename=%s" % (os.environ.get("GYROSIM_SHOT_RES", "1600x900"), fn))
            ST["res"]["%s_%s" % (v[0], st)] = dict(ST.pop("load", {}), file=fn)
            log("shot", fn)
            if v[0] in GPU_VIEWS and LOGF:
                ST.update(phase="gpu_warm", t=now)
            else:
                ST["vi"] += 1
                ST.update(phase="view", t=now)
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
            if el > 8.0:
                cmd("stopfpschart")
                ST.update(phase="gpu_collect", t=now)
        elif ph == "gpu_collect" and el > 1.0:
            v, st = VIEWS[ST["vi"]], STATES[ST["si"]]
            d = sorted(ST["dts"][5:])
            r = dict(view=v[0], state=st, gpu_ms=gpu_from_log(), viewport=ST["sp"][:2], screen_percentage=ST["sp"][2],
                     frames=len(d), avg_ms=round(sum(d) / len(d) * 1000, 2) if d else None)
            ST["gpu"].append(r)
            log("gpu", json.dumps(r))
            cmd("r.ScreenPercentage 100")
            ST["vi"] += 1
            ST.update(phase="view", t=now)
        elif ph == "end" and el > 2.0:
            res = dict(made=time.strftime("%Y-%m-%d %H:%M:%S"), seconds=round(now - ST["t0"]), roads_tiles=roads_look.TILES, roads_on=ST.get("roads") is not None, views=VIEWS, shots=ST["res"], gpu=ST["gpu"],
                       note="editor PIE without the sim server; lighting = map + monitor preset")
            with open(os.path.join(OUT, "shots.json"), "w", encoding="utf-8") as f:
                json.dump(res, f, indent=1, ensure_ascii=False)
            log("done ->", OUT)
            les.editor_request_end_play()
            ST.update(phase="quit", t=now)
        elif ph == "quit" and el > 3.0:
            unreal.unregister_slate_post_tick_callback(ST["h"])
            if os.environ.get("GYROSIM_RSHOT_QUIT", "1") == "1":
                unreal.SystemLibrary.quit_editor()
    except Exception as e:
        import traceback
        log("error", repr(e), " | ".join(traceback.format_exc().splitlines()))
        ST.update(phase="end" if ST["phase"] not in ("end", "quit") else "quit", t=time.monotonic())


sim_client.stop()                      # this editor must not talk to a running server (the user's session)
ST["h"] = unreal.register_slate_post_tick_callback(tick)
log("scheduled", len(STATES), "states x", len(VIEWS), "views ->", OUT)
