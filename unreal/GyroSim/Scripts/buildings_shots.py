"""Before / after shots of the Busan 3D buildings (developer use), without the sim server: launch a SECOND editor with
    UnrealEditor.exe GyroSim.uproject -GyroSimBldgShots -RenderOffscreen -nosplash -ABSLOG=<file>
(init_unreal.py). The sim client of this editor is stopped first (no UDP to a running server / user session), then Play
starts and this script sets up Cesium itself like sim_client (V-World photo on the local terrain from the proxy, origin
at each target), points the buildings tileset at a tile folder by file:// URL and takes HighResShots from a fixed camera.
States (GYROSIM_BSHOT_STATES, default 'before,after'): before = GYROSIM_BSHOT_OLD (default tiles; 11-09 old = tiles_prev_20261109) + stock material,
after = GYROSIM_BSHOT_NEW (default tiles_new, else tiles) + /Game/Buildings/M_GyroBuilding. GPU time (startfpschart,
~1080p pixels) per state on the GPU views. Out: GYROSIM_SHOTS_DIR (default C:/GyroSimTiles/shots/buildings - V-World
imagery stays outside git), shots.json. Lighting = the map + sim_client.apply_preset('monitor') (no server-driven sun /
fog follow), so compare before / after, not against PIE screenshots. Quits the editor when done.
"""
import json, math, os, re, time
import unreal
import photo_src                      # V-World photo with the white-gap fix (cache-only proxy), as at Play
import sim_client

log = lambda *a: unreal.log("[bshots] " + " ".join(str(x) for x in a))
les = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
ues = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem)
OUT = os.environ.get("GYROSIM_SHOTS_DIR", r"C:\GyroSimTiles\shots\buildings")
os.makedirs(OUT, exist_ok=True)
ROOT = r"C:/GyroSimTiles/buildings"
NEW = os.environ.get("GYROSIM_BSHOT_NEW", "tiles_new" if os.path.isfile(ROOT + "/tiles_new/tileset.json") else "tiles")
STATES = os.environ.get("GYROSIM_BSHOT_STATES", "before,after").split(",")
GEOID = 29.2
PORT = sim_client.SimClient.vworld_port() if hasattr(sim_client, "SimClient") else 8790
# (name, target lat, lon, target height m MSL, camera bearing from the target deg, horizontal distance m, camera height m MSL)
VIEWS = [("haeundae_300", 35.1565, 129.1435, 80.0, 160.0, 900.0, 300.0),      # Marine City towers from the sea (SSE), 300 m up
         ("haeundae_1000", 35.1585, 129.1560, 50.0, 170.0, 2600.0, 1000.0),   # Marine City + Haeundae beach towers / LCT
         ("haeundae_close", 35.1560, 129.1430, 90.0, 175.0, 450.0, 150.0),    # close look at the tower facades
         ("apartments_300", 35.1700, 129.1760, 40.0, 200.0, 650.0, 300.0),    # Haeundae new town apartment blocks (좌동)
         ("seomyeon_300", 35.1578, 129.0600, 20.0, 200.0, 700.0, 300.0),
         ("seomyeon_1000", 35.1578, 129.0600, 20.0, 210.0, 2200.0, 1000.0),
         ("busanstation_300", 35.1151, 129.0414, 15.0, 120.0, 700.0, 300.0),
         ("busanstation_1000", 35.1151, 129.0414, 15.0, 135.0, 2200.0, 1000.0),
         # depth close-ups (11-10): ~150 m and ~300 m up, oblique
         ("apartments_150", 35.1700, 129.1760, 40.0, 200.0, 260.0, 150.0),
         ("apartments_300o", 35.1700, 129.1760, 40.0, 230.0, 420.0, 300.0),
         ("marinecity_150", 35.1560, 129.1430, 120.0, 190.0, 380.0, 150.0),
         ("marinecity_300o", 35.1565, 129.1435, 120.0, 140.0, 650.0, 300.0),
         ("seomyeon_150", 35.1578, 129.0600, 20.0, 200.0, 300.0, 150.0),
         ("seomyeon_300o", 35.1578, 129.0600, 20.0, 240.0, 450.0, 300.0)]
if os.environ.get("GYROSIM_BSHOT_VIEWS"):
    VIEWS = [v for v in VIEWS if v[0] in os.environ["GYROSIM_BSHOT_VIEWS"].split(",")]
GPU_VIEWS = os.environ.get("GYROSIM_BSHOT_GPU", "seomyeon_300,haeundae_1000").split(",")
LOGF = os.environ.get("GYROSIM_BSHOT_LOG", "")
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
    # GYROSIM_BSHOT_LOCAL=1: terrain + photo straight from the local folders (file://, no proxy / server needed; the
    # photo cache is read only, no API call; missing tiles just stay empty)
    local = os.environ.get("GYROSIM_BSHOT_LOCAL") == "1"
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
    ts.refresh_tileset()
    b.set_actor_location_and_rotation(unreal.Vector(0, 0, 0), rot, False, True)
    b.set_editor_property("tileset_source", unreal.TilesetSource.FROM_URL)
    for k, v in (("maximum_screen_space_error", 16.0), ("create_physics_meshes", False), ("show_credits_on_screen", False)):
        b.set_editor_property(k, v)
    b.set_actor_hidden_in_game(False)
    return gr, ts, b


# GYROSIM_BSHOT_SPEC = "state=folder|material,..." overrides the two default states (material '-' = Cesium stock)
SPEC = dict(x.split("=", 1) for x in os.environ.get("GYROSIM_BSHOT_SPEC", "").split(",") if "=" in x)


def set_state(st):
    b = ST["b"]
    if st in SPEC:
        folder, mp = SPEC[st].split("|")
        mat = None if mp == "-" else unreal.load_asset(mp)
        b.set_editor_property("url", "file:///%s/%s/tileset.json" % (ROOT, folder))
        b.set_editor_property("material", mat)
        b.refresh_tileset()
        log("state", st, folder, "material", mat.get_name() if mat else "Cesium default")
        return
    folder = os.environ.get("GYROSIM_BSHOT_OLD", "tiles") if st == "before" else NEW
    b.set_editor_property("url", "file:///%s/%s/tileset.json" % (ROOT, folder))
    mat = unreal.load_asset("/Game/Buildings/M_GyroBuilding") if st == "after" else None
    b.set_editor_property("material", mat)
    b.refresh_tileset()
    log("state", st, folder, "material", mat.get_name() if mat else "Cesium default")


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


def tick(dt):
    try:
        now = time.monotonic()
        el = now - ST["t"]
        ph = ST["phase"]
        if ph == "wait_editor" and el > float(os.environ.get("GYROSIM_BSHOT_WAIT", "40")):
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
            if (p1 >= 99.9 and p2 >= 99.9 and el > 6.0) or el > float(os.environ.get("GYROSIM_BSHOT_LOADMAX", "90")):
                ST["load"] = dict(load_s=round(el, 1), terrain=round(p1, 1), buildings=round(p2, 1))
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
            res = dict(made=time.strftime("%Y-%m-%d %H:%M:%S"), seconds=round(now - ST["t0"]), new_tiles=NEW, views=VIEWS, shots=ST["res"], gpu=ST["gpu"],
                       note="editor PIE without the sim server; lighting = map + monitor preset")
            with open(os.path.join(OUT, "shots.json"), "w", encoding="utf-8") as f:
                json.dump(res, f, indent=1, ensure_ascii=False)
            log("done ->", OUT)
            les.editor_request_end_play()
            ST.update(phase="quit", t=now)
        elif ph == "quit" and el > 3.0:
            unreal.unregister_slate_post_tick_callback(ST["h"])
            if os.environ.get("GYROSIM_BSHOT_QUIT", "1") == "1":
                unreal.SystemLibrary.quit_editor()
    except Exception as e:
        import traceback
        log("error", repr(e), " | ".join(traceback.format_exc().splitlines()))
        ST.update(phase="end" if ST["phase"] not in ("end", "quit") else "quit", t=time.monotonic())


sim_client.stop()                      # this editor must not talk to a running server (the user's session)
ST["h"] = unreal.register_slate_post_tick_callback(tick)
log("scheduled", len(STATES), "states x", len(VIEWS), "views ->", OUT)
