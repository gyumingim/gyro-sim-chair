"""Before / after shots of the Busan landmark models (developer use, sim/landmarks/landmarks_build.py tiles), without the
sim server. Launch a SECOND editor, never visible (Scripts/landmarks_shots.sh does it, holding C:/GyroSimTiles/ue_offscreen.lock):
    UnrealEditor.exe GyroSim.uproject /Game/Maps/FlightMap -GyroSimLandmarkShots -RenderOffscreen -nosplash -ABSLOG=<file>
Its own sim client is stopped first (no UDP to the user's server). The launcher copies FlightMap.umap to
Content/Maps/_tmp/FlightMap_lmtest.umap and opens THAT map; the CesiumLandmarks actor is spawned there only (refused on
any other map; never saved; the launcher deletes the copy). (Duplicating the map in the editor and loading it crashed:
"World Memory Leaks" on load_level.)
Ground = local terrain + cached V-World photo by file:// (no proxy, no API call). States:
  before = live building tiles (GYROSIM_LSHOT_OLD, default 'tiles') + landmarks hidden
  after  = building tiles built with exclude.json (GYROSIM_LSHOT_NEW, default 'tiles_lmtest') + landmarks shown
Both with /Game/Buildings/M_GyroBuilding on the buildings, and the OSM bridges (roads_look, GYROSIM_LSHOT_ROADS=0 = off,
as in the shots before 11-10). Views: sim/landmarks/views.json (+ GYROSIM_LSHOT_VIEWS_FILE). Out: GYROSIM_SHOTS_DIR
(default C:/GyroSimTiles/shots/landmarks - V-World imagery stays outside git) + shots.json. GPU (startfpschart, ~1080p
pixels) on GYROSIM_LSHOT_GPU views. Quits the editor when done.
"""
import json, math, os, re, time
import unreal
import sim_client
import landmarks_look
import roads_look

log = lambda *a: unreal.log("[lshots] " + " ".join(str(x) for x in a))
les = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
ues = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem)
OUT = os.environ.get("GYROSIM_SHOTS_DIR", r"C:\GyroSimTiles\shots\landmarks")
os.makedirs(OUT, exist_ok=True)
ROOT = r"C:/GyroSimTiles/buildings"
OLD = os.environ.get("GYROSIM_LSHOT_OLD", "tiles")
NEW = os.environ.get("GYROSIM_LSHOT_NEW", "tiles_lmtest" if os.path.isfile(ROOT + "/tiles_lmtest/tileset.json") else "tiles")
STATES = os.environ.get("GYROSIM_LSHOT_STATES", "before,after").split(",")
TMP_MAP = "/Game/Maps/_tmp/FlightMap_lmtest"
GEOID = 29.2
REPO = os.path.abspath(os.path.join(unreal.Paths.project_dir(), "..", ".."))
VIEWS = [tuple(v[:7]) for v in json.load(open(os.path.join(REPO, "sim", "landmarks", "views.json"), encoding="utf-8"))["views"]]
# extra views (same format, optional 9th item = horizontal FOV deg), e.g. sea views at the atmosphere reference spots
if os.environ.get("GYROSIM_LSHOT_VIEWS_FILE"):
    VIEWS += [tuple(v[:7]) + ((float(v[8]),) if len(v) > 8 and v[8] else ()) for v in
              json.load(open(os.environ["GYROSIM_LSHOT_VIEWS_FILE"], encoding="utf-8"))["views"]]
if os.environ.get("GYROSIM_LSHOT_VIEWS"):
    VIEWS = [v for v in VIEWS if v[0] in os.environ["GYROSIM_LSHOT_VIEWS"].split(",")]
GPU_VIEWS = os.environ.get("GYROSIM_LSHOT_GPU", "marine_air,haeundae_overview").split(",")
LOGF = os.environ.get("GYROSIM_LSHOT_LOG", "")
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


def on_temp_map():
    w = ues.get_editor_world()
    name = w.get_path_name() if w else ""
    log("editor world", name)
    return "_lmtest" in name


def setup_cesium(world):
    gr, ts, b = find(world, "CesiumGeoreference"), find(world, "CesiumGround"), find(world, "CesiumBuildings")
    grid = find(world, "GridGround")
    if grid:
        grid.set_actor_hidden_in_game(True)
    for a in unreal.GameplayStatics.get_all_actors_with_tag(world, "Airfield"):
        a.set_actor_hidden_in_game(True)
    rot = unreal.Rotator(roll=0, pitch=0, yaw=90.0)
    for a in (ts, b):                       # the map copy's actors still point at the ORIGINAL map's georeference: re-link
        try:
            a.set_georeference(gr)
        except Exception as e:
            log("georeference", repr(e))
    ts.set_actor_location_and_rotation(unreal.Vector(0, 0, 0), rot, False, True)
    ts.set_actor_hidden_in_game(False)
    ts.set_editor_property("tileset_source", unreal.TilesetSource.FROM_URL)
    ts.set_editor_property("url", "file:///C:/GyroSimTiles/terrain/tiles/layer.json")     # local terrain (no proxy)
    ovs = {c.get_class().get_name(): c for c in ts.get_components_by_class(unreal.CesiumRasterOverlay)}
    for o in ovs.values():
        o.remove_from_tileset()
    ov = ovs.get("CesiumUrlTemplateRasterOverlay")
    ov.set_editor_property("template_url", "file:///C:/GyroSimTiles/vworld/Satellite/{z}/{reverseY}/{x}.jpg")   # cache, read only
    ov.set_editor_property("minimum_level", 6)
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
    m = unreal.load_asset("/Game/Buildings/M_GyroBuilding") if unreal.EditorAssetLibrary.does_asset_exist("/Game/Buildings/M_GyroBuilding") else None
    b.set_editor_property("material", m)
    b.set_actor_hidden_in_game(False)
    if os.environ.get("GYROSIM_LSHOT_ATMOS", "0") == "1":
        try:
            import atmos_look                                      # same air / sea look as Play (other agent's layer, optional)
            atmos_look.apply_ground(ts)
        except Exception as e:
            log("atmos ground", repr(e))
    ST["lm"] = landmarks_look.apply(world, log, gr)
    # OSM bridges / elevated roads (CesiumRoads, as at Play). Before 11-10 the shots had no roads (GYROSIM_LSHOT_ROADS=0)
    ST["roads"] = roads_look.apply(world, log, gr) if os.environ.get("GYROSIM_LSHOT_ROADS", "1") == "1" else None
    return gr, ts, b


def set_state(st):
    b, lm = ST["b"], ST.get("lm")
    folder = OLD if st == "before" else NEW
    b.set_editor_property("url", "file:///%s/%s/tileset.json" % (ROOT, folder))
    b.refresh_tileset()
    if lm is not None:
        lm.set_actor_hidden_in_game(st == "before")
    log("state", st, "buildings", folder, "landmarks", "none" if lm is None else ("hidden" if st == "before" else "shown"))


def place_view(v):
    name, lat, lon, th, brg, dist, ch = v[:7]
    ST["cam"].camera_component.set_editor_property("field_of_view", v[7] if len(v) > 7 else float(os.environ.get("GYROSIM_LSHOT_FOV", "55")))
    ST["gr"].set_origin_longitude_latitude_height(unreal.Vector(lon, lat, GEOID))
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


def tick(dt):
    try:
        now = time.monotonic()
        el = now - ST["t"]
        ph = ST["phase"]
        if ph == "wait_editor" and el > float(os.environ.get("GYROSIM_LSHOT_WAIT", "40")):
            if on_temp_map():
                landmarks_look.spawn_editor(log)
                if os.environ.get("GYROSIM_LSHOT_ROADS", "1") == "1":
                    roads_look.spawn_editor(log)          # no-op when the map already has the CesiumRoads actor
            else:
                log("not on the temporary map copy - landmarks actor NOT spawned (shots without landmarks)")
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
                ST["cam"].camera_component.set_editor_property("field_of_view", float(os.environ.get("GYROSIM_LSHOT_FOV", "55")))
                ST["cam"].camera_component.set_editor_property("constrain_aspect_ratio", False)
                pc = unreal.GameplayStatics.get_player_controller(w, 0)
                pc.set_view_target_with_blend(ST["cam"], 0.0)
                try:
                    sim_client.apply_preset("monitor", w)
                except Exception as e:
                    log("preset", repr(e))
                if os.environ.get("GYROSIM_LSHOT_ATMOS", "0") == "1":
                    try:
                        import atmos_look
                        atmos_look.apply(w, "monitor")
                    except Exception as e:
                        log("atmos", repr(e))
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
            p3 = progress(ST["lm"]) if ST.get("lm") is not None else 100.0
            p4 = progress(ST["roads"]) if ST.get("roads") is not None else 100.0
            if (p1 >= 99.9 and p2 >= 99.9 and p3 >= 99.9 and p4 >= 99.9 and el > 6.0) or el > 90.0:
                ST["load"] = dict(load_s=round(el, 1), terrain=round(p1, 1), buildings=round(p2, 1), landmarks=round(p3, 1))
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
            res = dict(made=time.strftime("%Y-%m-%d %H:%M:%S"), seconds=round(now - ST["t0"]), landmark_tiles=landmarks_look.TILES,
                       landmarks_on=ST.get("lm") is not None, roads_on=ST.get("roads") is not None,
                       env={k: v for k, v in os.environ.items() if k.startswith(("GYROSIM_LSHOT", "GYROSIM_LM_", "GYROSIM_SEA", "GYROSIM_ATMOS", "GYROSIM_ROADS", "GYROSIM_LANDMARK"))}, buildings_before=OLD, buildings_after=NEW, views=VIEWS, shots=ST["res"], gpu=ST["gpu"],
                       note="editor PIE on a temporary map copy, no sim server; local terrain / cached photo; lighting = map + monitor preset + atmos_look")
            with open(os.path.join(OUT, "shots.json"), "w", encoding="utf-8") as f:
                json.dump(res, f, indent=1, ensure_ascii=False)
            log("done ->", OUT)
            les.editor_request_end_play()
            ST.update(phase="quit", t=now)
        elif ph == "quit" and el > 3.0:
            unreal.unregister_slate_post_tick_callback(ST["h"])
            if os.environ.get("GYROSIM_LSHOT_QUIT", "1") == "1":
                unreal.SystemLibrary.quit_editor()
    except Exception as e:
        import traceback
        log("error", repr(e), " | ".join(traceback.format_exc().splitlines()))
        ST.update(phase="end" if ST["phase"] not in ("end", "quit") else "quit", t=time.monotonic())


sim_client.stop()                      # this editor must not talk to a running server (the user's session)
ST["h"] = unreal.register_slate_post_tick_callback(tick)
log("scheduled", len(STATES), "states x", len(VIEWS), "views ->", OUT)
