"""Before / after shots of the 3D trees over Busan's hills (sim/veg_build.py tiles, Content/Python/trees_look.py) + GPU
time, without the sim server. Launch a SECOND editor, never visible:
    UnrealEditor.exe GyroSim.uproject /Game/Maps/FlightMap -GyroSimTreeShots -RenderOffscreen -nosplash -ABSLOG=<file>
(init_unreal.py; GYROSIM_TSHOT_LOG = the same log file, for the GPU numbers). Its own sim client is stopped first (no UDP
to the user's server), Play starts, Cesium is set up like sim_client but from the local folders (terrain tiles + V-World
photo cache by file://, no proxy, no API call; GYROSIM_TSHOT_PROXY=1 = through the proxy), local buildings with
M_GyroBuilding, roads + trees via roads_look / trees_look.apply (the same calls sim_client makes; the actors are spawned in
this editor's editor world before Play and never saved), air / light via atmos_look. before = trees hidden, after = shown.
GPU: ~1080p pixels, and GYROSIM_TSHOT_VR views again at the VR pixel count (7.0 M, the README's VR rows).
Out: GYROSIM_SHOTS_DIR (default C:/GyroSimTiles/shots/trees - V-World imagery stays outside git), shots.json.
Quits the editor when done. Only one offscreen editor at a time: the caller holds C:/GyroSimTiles/ue_offscreen.lock.
"""
import json, math, os, re, time
import unreal
import photo_src                      # V-World photo with the white-gap fix (cache-only proxy), as at Play
import sim_client
import roads_look
import trees_look

log = lambda *a: unreal.log("[tshots] " + " ".join(str(x) for x in a))
les = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
ues = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem)
OUT = os.environ.get("GYROSIM_SHOTS_DIR", r"C:\GyroSimTiles\shots\trees")
os.makedirs(OUT, exist_ok=True)
ROOT = r"C:/GyroSimTiles/buildings"
STATES = os.environ.get("GYROSIM_TSHOT_STATES", "before,after").split(",")
GEOID = 29.2
PORT = int(os.environ.get("GYROSIM_TSHOT_PORT", "0")) or (sim_client.SimClient.vworld_port() if hasattr(sim_client, "SimClient") else 8790)
# (name, target lat, lon, target height m MSL, camera bearing from the target deg, horizontal distance m, camera height m MSL)
# summits from the Copernicus DEM (11-10): 장산 35.1942 129.145 625 m, 황령산 35.1572 129.082 424 m, 금정산 35.2800 129.0505 788 m,
# 승학산 35.1167 128.9800 487 m. Camera ~300 m / ~800 m above the summit, looking at the upper slopes.
VIEWS = [("jangsan_300", 35.1920, 129.1480, 540.0, 150.0, 1100.0, 925.0),
         ("jangsan_800", 35.1920, 129.1480, 500.0, 150.0, 2600.0, 1425.0),
         ("hwangryeong_300", 35.1572, 129.0820, 360.0, 200.0, 1000.0, 725.0),
         ("hwangryeong_800", 35.1572, 129.0820, 330.0, 200.0, 2500.0, 1225.0),
         ("geumjeong_300", 35.2800, 129.0505, 700.0, 120.0, 1100.0, 1090.0),
         ("geumjeong_800", 35.2800, 129.0505, 660.0, 120.0, 2600.0, 1590.0),
         ("seunghak_300", 35.1167, 128.9800, 420.0, 90.0, 1000.0, 790.0),
         ("seunghak_800", 35.1167, 128.9800, 390.0, 90.0, 2500.0, 1290.0),
         ("hwangryeong_low", 35.1560, 129.0800, 330.0, 160.0, 450.0, 520.0)]
for _ev in filter(None, os.environ.get("GYROSIM_TSHOT_EXTRA", "").split(";")):     # "name,lat,lon,h,bearing,dist,camh;..."
    _p = _ev.split(",")
    VIEWS.append((_p[0],) + tuple(float(x) for x in _p[1:7]))
if os.environ.get("GYROSIM_TSHOT_VIEWS"):
    VIEWS = [v for v in VIEWS if v[0] in os.environ["GYROSIM_TSHOT_VIEWS"].split(",")]
GPU_VIEWS = os.environ.get("GYROSIM_TSHOT_GPU", "hwangryeong_300,jangsan_800,hwangryeong_low").split(",")
VR_VIEWS = os.environ.get("GYROSIM_TSHOT_VR", "hwangryeong_300").split(",")
VR_PIXELS = 7.0e6
LOGF = os.environ.get("GYROSIM_TSHOT_LOG", "")
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
    local = os.environ.get("GYROSIM_TSHOT_PROXY") != "1"
    ts.set_editor_property("url", "file:///C:/GyroSimTiles/terrain/tiles/layer.json" if local else "http://127.0.0.1:%d/terrain/layer.json" % PORT)
    ovs = {c.get_class().get_name(): c for c in ts.get_components_by_class(unreal.CesiumRasterOverlay)}
    for o in ovs.values():
        o.remove_from_tileset()
    ov = ovs.get("CesiumUrlTemplateRasterOverlay")
    ov.set_editor_property("template_url", photo_src.template() if local else
                           "http://127.0.0.1:%d/vworld/sat/{z}/{reverseY}/{x}.jpg" % PORT)
    ov.set_editor_property("minimum_level", 6 if local else 0)
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
    m = unreal.load_asset("/Game/Buildings/M_GyroBuilding") if unreal.EditorAssetLibrary.does_asset_exist("/Game/Buildings/M_GyroBuilding") else None
    b.set_editor_property("material", m)
    b.set_actor_hidden_in_game(False)
    b.refresh_tileset()
    ST["roads"] = roads_look.apply(world, log, gr)
    ST["trees"] = trees_look.apply(world, log, gr)
    return gr, ts, b


def set_state(st):
    r = ST.get("trees")
    if r is not None:
        r.set_actor_hidden_in_game(st == "before")
    log("state", st, "trees", "none" if r is None else ("hidden" if st == "before" else "shown"))


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
        if ph == "wait_editor" and el > float(os.environ.get("GYROSIM_TSHOT_WAIT", "40")):
            probe()
            if os.environ.get("GYROSIM_TSHOT_PRESPAWN", "1") == "1":     # editor-world actors before Play (PIE copies them; never saved)
                roads_look.spawn_editor(log)
                trees_look.spawn_editor(log)
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
            p3 = progress(ST["trees"]) if ST.get("trees") is not None else 100.0
            if (p1 >= 99.9 and p2 >= 99.9 and p3 >= 99.9 and el > 8.0) or el > 120.0:
                ST["load"] = dict(load_s=round(el, 1), terrain=round(p1, 1), buildings=round(p2, 1), trees=round(p3, 1))
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
            px = VR_PIXELS if ST.get("vrpass") else 1920 * 1080
            sp = max(25.0, min(400.0, 100.0 * math.sqrt(px / max(1.0, vp.x * vp.y))))
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
            r = dict(view=v[0], state=st, pixels="vr_7.0M" if ST.get("vrpass") else "1080p", gpu_ms=gpu_from_log(), viewport=ST["sp"][:2],
                     screen_percentage=ST["sp"][2], frames=len(d), avg_ms=round(sum(d) / len(d) * 1000, 2) if d else None)
            ST["gpu"].append(r)
            log("gpu", json.dumps(r))
            cmd("r.ScreenPercentage 100")
            if v[0] in VR_VIEWS and not ST.get("vrpass"):
                ST.update(phase="gpu_warm", t=now, vrpass=True)
                return
            ST["vrpass"] = False
            ST["vi"] += 1
            ST.update(phase="view", t=now)
        elif ph == "end" and el > 2.0:
            res = dict(made=time.strftime("%Y-%m-%d %H:%M:%S"), seconds=round(now - ST["t0"]), trees_tiles=trees_look.TILES, trees_on=ST.get("trees") is not None, roads_on=ST.get("roads") is not None, views=VIEWS, shots=ST["res"], gpu=ST["gpu"],
                       note="editor PIE without the sim server; lighting = map + monitor preset")
            with open(os.path.join(OUT, "shots.json"), "w", encoding="utf-8") as f:
                json.dump(res, f, indent=1, ensure_ascii=False)
            log("done ->", OUT)
            les.editor_request_end_play()
            ST.update(phase="quit", t=now)
        elif ph == "quit" and el > 3.0:
            unreal.unregister_slate_post_tick_callback(ST["h"])
            if os.environ.get("GYROSIM_TSHOT_QUIT", "1") == "1":
                unreal.SystemLibrary.quit_editor()
    except Exception as e:
        import traceback
        log("error", repr(e), " | ".join(traceback.format_exc().splitlines()))
        ST.update(phase="end" if ST["phase"] not in ("end", "quit") else "quit", t=time.monotonic())


if os.environ.get("GYROSIM_TREES_NEAR_SHOTS", "0") == "1":     # near real-leaf trees (Scripts/trees_near_shots.py) instead
    _p = os.path.join(unreal.Paths.project_dir(), "Scripts", "trees_near_shots.py")
    exec(compile(open(_p, encoding="utf-8").read(), _p, "exec"), {"__name__": "gyrosim_trees_near_shots"})
else:
    sim_client.stop()                      # this editor must not talk to a running server (the user's session)
    ST["h"] = unreal.register_slate_post_tick_callback(tick)
    log("scheduled", len(STATES), "states x", len(VIEWS), "views ->", OUT)
