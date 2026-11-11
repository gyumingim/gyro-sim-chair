"""Shots + GPU time for the near real-leaf trees (Content/Python/trees_near.py, docs/trees-near-busan.md), no sim server.
Runs inside the offscreen editor of Scripts/trees_shots.py:
    set GYROSIM_TREES_NEAR_SHOTS=1 and launch  UnrealEditor.exe GyroSim.uproject /Game/Maps/FlightMap -GyroSimTreeShots
        -RenderOffscreen -nosplash -nosound -ABSLOG=<file>   (GYROSIM_TSHOT_LOG = the same file, for the GPU numbers)
Holds nothing itself: the caller holds C:/GyroSimTiles/ue_offscreen.lock. Quits the editor when done.
States (GYROSIM_TNS_STATES, comma list, each once):
    none   no 3D trees at all (GPU floor)          blob   the old round tiles (before)
    near   real-leaf trees, default (lite: oak D for every tree, recoloured per species)   near_r<m>  another radius
    full   the 8-model set (needs those meshes imported)
    noshadow  near trees without shadows
Out: GYROSIM_SHOTS_DIR (default C:/GyroSimTiles/shots/trees_near - V-World imagery stays outside git), shots.json.
"""
import json, math, os, re, time
import unreal
import photo_src
import sim_client
import roads_look
import trees_look
import trees_near
import trees_imp

log = lambda *a: unreal.log("[tnshots] " + " ".join(str(x) for x in a))
les = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
ues = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem)
OUT = os.environ.get("GYROSIM_SHOTS_DIR", r"C:\GyroSimTiles\shots\trees_near")
os.makedirs(OUT, exist_ok=True)
ROOT = r"C:/GyroSimTiles/buildings"
GEOID = 29.2
STATES = os.environ.get("GYROSIM_TNS_STATES", "none,blob,near").split(",")
# (name, target lat, lon, target m MSL, camera bearing from the target deg, horizontal distance m, camera m MSL)
# ground (Copernicus DEM, 11-11): 동백섬 57 m, 황령산 slope 328 m / top 423 m, 장산 slope 424 m / top 626 m, 부산시민공원 30 m,
# 금정산 788 m, 이기대 42 m. low = camera 60-150 m above the ground under it, mid = 300-800 m above the hills.
VIEWS = [("dongbaek_low", 35.1535, 129.1520, 35.0, 200.0, 380.0, 120.0),
         ("hwang_low", 35.1590, 129.0870, 320.0, 60.0, 320.0, 440.0),
         ("jang_low", 35.1905, 129.1500, 420.0, 150.0, 320.0, 540.0),
         ("park_low", 35.1685, 129.0570, 30.0, 180.0, 320.0, 140.0),
         ("jang_mid", 35.1920, 129.1480, 500.0, 150.0, 1500.0, 1050.0),
         ("hwang_mid", 35.1572, 129.0820, 380.0, 200.0, 1300.0, 850.0),
         ("geum_mid", 35.2800, 129.0505, 700.0, 120.0, 1600.0, 1350.0),
         ("igidae_mid", 35.1300, 129.1190, 40.0, 250.0, 1200.0, 480.0),
         ("hwang_close", 35.1590, 129.0870, 320.0, 60.0, 140.0, 390.0)]          # 11-11 impostor check: ~70 m above the crowns
if os.environ.get("GYROSIM_TNS_VIEWS"):
    VIEWS = [v for v in VIEWS if v[0] in os.environ["GYROSIM_TNS_VIEWS"].split(",")]
GPU_VIEWS = os.environ.get("GYROSIM_TNS_GPU", "dongbaek_low,hwang_low,park_low,jang_mid").split(",")
# states shot only in these views (the rest: GPU views only) - keeps the run short
SHOT_ALL = os.environ.get("GYROSIM_TNS_SHOT_ALL", "blob,near").split(",")
LOGF = os.environ.get("GYROSIM_TSHOT_LOG", "")
ST = dict(t=time.monotonic(), t0=time.monotonic(), phase="wait_editor", si=0, vi=0, h=None, res={}, gpu=[], counts={})


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
    b.set_editor_property("url", "file:///%s/tiles/tileset.json" % ROOT)
    m = unreal.load_asset("/Game/Buildings/M_GyroBuilding") if unreal.EditorAssetLibrary.does_asset_exist("/Game/Buildings/M_GyroBuilding") else None
    b.set_editor_property("material", m)
    b.set_actor_hidden_in_game(False)
    b.refresh_tileset()
    try:
        import buildings_look
        buildings_look.apply(b, log)
    except Exception as e:
        log("buildings look", repr(e))
    ST["roads"] = roads_look.apply(world, log, gr)
    os.environ["GYROSIM_TREES_NEAR"] = "0"                 # the blob tiles first (trees_look as before), near trees per state
    os.environ["GYROSIM_TREES_IMPOSTOR"] = "0"             # (impostors are the default since 11-11: off for the blob actor)
    ST["blob"] = trees_look.apply(world, log, gr)
    os.environ["GYROSIM_TREES_NEAR"] = "1"
    return gr, ts, b


def set_state(st):
    w = ST["w"]
    blob = ST.get("blob")
    if blob is not None:
        blob.set_actor_hidden_in_game(st != "blob")
    near = st.startswith("near") or st in ("full", "noshadow")
    imp = st.startswith("imp")
    if imp:                                                # impostor cards (trees_imp) in the same actor
        os.environ["GYROSIM_TREES_NEAR"] = "0"
        os.environ["GYROSIM_TREES_IMPOSTOR"] = "1"
        os.environ["GYROSIM_TREES_IMP_SHADOW_M"] = "0" if st == "imp_noshadow" else os.environ.get("GYROSIM_TNS_IMP_SHADOW_M", "1500")
        m = re.match(r"imp_r(\d+)", st)
        if m:
            os.environ["GYROSIM_TREES_IMP_R"] = m.group(1)
        else:
            os.environ.pop("GYROSIM_TREES_IMP_R", None)
        m = re.search(r"_f(\d+)", st)                      # imp_f0 = one view per tree from 0 m (far material everywhere)
        if m:
            os.environ["GYROSIM_TREES_IMP_FAR"] = m.group(1)
        else:
            os.environ.pop("GYROSIM_TREES_IMP_FAR", None)
        m = re.search(r"_s(\d+)", st)                      # imp_s6 = crown-volume normal blend 0.6
        if m:
            os.environ["GYROSIM_TREES_IMP_SPH"] = str(int(m.group(1)) / 10.0)
        else:
            os.environ.pop("GYROSIM_TREES_IMP_SPH", None)
        m = re.search(r"_a(\d+)", st)                      # imp_a16 = alpha (coverage) x 1.6
        if m:
            os.environ["GYROSIM_TREES_IMP_ALPHA"] = str(int(m.group(1)) / 10.0)
        else:
            os.environ.pop("GYROSIM_TREES_IMP_ALPHA", None)
        ST["imp"] = trees_imp.apply(w, log, ST["gr"])
        log("state", st, "imp", ST["imp"] is not None)
        return
    if near:
        os.environ["GYROSIM_TREES_NEAR"] = "1"
        os.environ["GYROSIM_TREES_NEAR_LITE"] = "0" if st == "full" else "1"
        os.environ["GYROSIM_TREES_NEAR_SHADOW"] = "0" if st == "noshadow" else "1"
        m = re.match(r"near_r(\d+)", st)
        if m:
            os.environ["GYROSIM_TREES_NEAR_R"] = m.group(1)
        else:
            os.environ.pop("GYROSIM_TREES_NEAR_R", None)
        ST["near"] = trees_near.apply(w, log, ST["gr"])
    else:
        trees_near.hide(w)
    log("state", st, "blob", blob is not None, "near", near and ST.get("near") is not None)


# in-flight frame time (11-11 impostor check): the camera flies a straight line at FLY_SPEED, FLY_S seconds, over 황령산 toward
# 장산, 650 m MSL (above every hill on the way), after the start view has loaded. States in GYROSIM_TNS_FLY (comma list).
FLY = [x for x in os.environ.get("GYROSIM_TNS_FLY", "").split(",") if x]
FLY_SPEED = float(os.environ.get("GYROSIM_TNS_FLY_SPEED", "90"))
FLY_S = float(os.environ.get("GYROSIM_TNS_FLY_S", "50"))
FLY_ROUTE = (35.1590, 129.0870, 58.0, 650.0)                 # start lat, lon, bearing deg, m MSL


def fly_place(d):
    lat, lon, brg, alt = FLY_ROUTE
    if d == 0.0:
        ST["gr"].set_origin_longitude_latitude_height(unreal.Vector(lon, lat, GEOID))
    br = math.radians(brg)
    cam = unreal.Vector(d * math.cos(br) * 100.0, d * math.sin(br) * 100.0, alt * 100.0)
    ST["cam"].set_actor_location_and_rotation(cam, unreal.Rotator(roll=0, pitch=-12.0, yaw=brg), False, True)
    if d == 0.0:
        trees_near.follow_now()
        trees_imp.follow_now()


def place_view(v):
    name, lat, lon, th, brg, dist, ch = v
    ST["gr"].set_origin_longitude_latitude_height(unreal.Vector(lon, lat, GEOID))
    br = math.radians(brg)
    n, e = dist * math.cos(br), dist * math.sin(br)
    cam = unreal.Vector(n * 100.0, e * 100.0, ch * 100.0)
    tgt = unreal.Vector(0.0, 0.0, th * 100.0)
    d = tgt - cam
    yaw = math.degrees(math.atan2(d.y, d.x))
    pitch = math.degrees(math.atan2(d.z, math.hypot(d.x, d.y)))
    ST["cam"].set_actor_location_and_rotation(cam, unreal.Rotator(roll=0, pitch=pitch, yaw=yaw), False, True)
    trees_near.follow_now()
    trees_imp.follow_now()


def gpu_from_log():
    try:
        with open(LOGF, encoding="utf-8", errors="ignore") as f:
            txt = f.read()[-300000:]
        g = re.findall(r"Average GPU frametime: ([\d.]+) ms", txt)
        return float(g[-1]) if g else None
    except OSError:
        return None


def csv_stats():
    """mean triangles / draw calls per frame from the newest CSV profile (csvprofile start/stop around the GPU run)."""
    import glob
    d = os.path.join(unreal.Paths.project_saved_dir(), "Profiling", "CSV")
    fs = sorted(glob.glob(os.path.join(d, "*.csv")), key=os.path.getmtime)
    if not fs:
        return dict(csv=None)
    try:
        rows = open(fs[-1], encoding="utf-8", errors="ignore").read().splitlines()
        head = rows[0].split(",")
        out = dict(csv=os.path.basename(fs[-1]))
        for col in ("RHI/PrimitivesDrawn", "RHI/DrawCalls"):
            if col in head:
                i = head.index(col)
                vals = []
                for r in rows[1:]:
                    c = r.split(",")
                    if len(c) > i:
                        try:
                            vals.append(float(c[i]))
                        except ValueError:
                            pass
                vals = vals[5:] or vals
                out[col.split("/")[1]] = round(sum(vals) / len(vals)) if vals else None
        return out
    except Exception as e:
        return dict(csv=repr(e))


def want_view(st, v):
    return st in SHOT_ALL or v[0] in GPU_VIEWS


def tick(dt):
    try:
        now = time.monotonic()
        el = now - ST["t"]
        ph = ST["phase"]
        if ph == "wait_editor" and el > float(os.environ.get("GYROSIM_TSHOT_WAIT", "40")):
            roads_look.spawn_editor(log)
            trees_look.spawn_editor(log)
            trees_near.spawn_editor(log)
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
            while ST["vi"] < len(VIEWS) and not want_view(STATES[ST["si"]], VIEWS[ST["vi"]]):
                ST["vi"] += 1
            if ST["vi"] >= len(VIEWS):
                if STATES[ST["si"]] in FLY and not ST.get("flown"):
                    ST.update(phase="fly_setup", t=now, flown=True); return
                ST["si"] += 1
                ST.update(phase="state", t=now, flown=False); return
            pc = unreal.GameplayStatics.get_player_controller(ST["w"], 0)
            pc.set_view_target_with_blend(ST["cam"], 0.0)
            place_view(VIEWS[ST["vi"]])
            ST.update(phase="load", t=now, quiet=None)
        elif ph == "load":
            p1, p2 = progress(ST["ts"]), progress(ST["b"])
            st = STATES[ST["si"]]
            p3 = progress(ST["blob"]) if (st == "blob" and ST.get("blob") is not None) else 100.0
            pend = trees_near.pending() if (st.startswith("near") or st in ("full", "noshadow")) else (trees_imp.pending() if st.startswith("imp") else 0)
            if pend == 0 and ST.get("quiet") is None and el > 2.0:
                ST["quiet"] = now
            elif pend:
                ST["quiet"] = None
            ready = p1 >= 99.9 and p2 >= 99.9 and p3 >= 99.9 and ST.get("quiet") is not None and now - ST["quiet"] > 6.0 and el > 10.0
            if ready or el > 150.0:
                ST["load"] = dict(load_s=round(el, 1), terrain=round(p1, 1), buildings=round(p2, 1), blob=round(p3, 1), near_pending=pend,
                                  near_trees=trees_near.loaded_trees() if pend == 0 and ST.get("near") is not None and st != "blob" and st != "none" else 0,
                                  near_fill_ms=trees_near.ST["stats"].get("fill_ms"),
                                  imp_trees=trees_imp.loaded_trees() if st.startswith("imp") and pend == 0 else 0)
                ST.update(phase="shoot", t=now)
        elif ph == "shoot" and el > 3.0:
            v, st = VIEWS[ST["vi"]], STATES[ST["si"]]
            fn = os.path.join(OUT, "%s_%s.png" % (v[0], st)).replace("\\", "/")
            cmd("HighResShot %s filename=%s" % (os.environ.get("GYROSIM_SHOT_RES", "1600x900"), fn))
            ST["res"]["%s_%s" % (v[0], st)] = dict(ST.pop("load", {}), file=fn)
            log("shot", fn, json.dumps(ST["res"]["%s_%s" % (v[0], st)]))
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
            cmd("csvprofile start")
            ST.update(phase="gpu_run", t=now, dts=[])
        elif ph == "gpu_run":
            ST["dts"].append(dt)
            if el > 8.0:
                cmd("stopfpschart")
                cmd("csvprofile stop")
                ST.update(phase="gpu_collect", t=now)
        elif ph == "gpu_collect" and el > 4.0:
            v, st = VIEWS[ST["vi"]], STATES[ST["si"]]
            d = sorted(ST["dts"][5:])
            r = dict(view=v[0], state=st, pixels="1080p", gpu_ms=gpu_from_log(), viewport=ST["sp"][:2], screen_percentage=ST["sp"][2],
                     frames=len(d), avg_ms=round(sum(d) / len(d) * 1000, 2) if d else None,
                     near_trees=ST["res"].get("%s_%s" % (v[0], st), {}).get("near_trees"),
                     imp_trees=ST["res"].get("%s_%s" % (v[0], st), {}).get("imp_trees"), **csv_stats())
            ST["gpu"].append(r)
            log("gpu", json.dumps(r))
            cmd("r.ScreenPercentage 100")
            ST["vi"] += 1
            ST.update(phase="view", t=now)
        elif ph == "fly_setup":
            fly_place(0.0)
            ST.update(phase="fly_load", t=now, quiet=None)
        elif ph == "fly_load":
            st = STATES[ST["si"]]
            pend = trees_imp.pending() if st.startswith("imp") else 0
            p = min(progress(ST["ts"]), progress(ST["b"]), progress(ST["blob"]) if (st == "blob" and ST.get("blob")) else 100.0)
            if (p >= 99.9 and pend == 0 and el > 8.0) or el > 90.0:
                ST.update(phase="fly", t=now, dts=[], gt=[], fly_d=0.0)
                trees_imp.ST["stats"]["max_tick_ms"] = 0.0
        elif ph == "fly":
            ST["fly_d"] += FLY_SPEED * dt
            fly_place(ST["fly_d"])
            ST["dts"].append(dt)
            ST["gt"].append(trees_imp.ST["stats"].get("fill_ms") or 0.0 if STATES[ST["si"]].startswith("imp") else 0.0)
            if el > FLY_S:
                ST.update(phase="fly_done", t=now)
        elif ph == "fly_done":
            st = STATES[ST["si"]]
            d = sorted(x * 1000.0 for x in ST["dts"][10:])
            g = sorted(ST["gt"][10:])
            q = lambda a, f: round(a[min(len(a) - 1, int(f * len(a)))], 2) if a else None
            r = dict(state=st, route=FLY_ROUTE, speed_mps=FLY_SPEED, seconds=FLY_S, frames=len(d), mean_ms=round(sum(d) / len(d), 2) if d else None,
                     p50=q(d, 0.5), p95=q(d, 0.95), p99=q(d, 0.99), max=round(d[-1], 1) if d else None,
                     over33=sum(1 for x in d if x > 33.4), over50=sum(1 for x in d if x > 50.0),
                     imp_py_p99=q(g, 0.99), imp_py_max=round(g[-1], 2) if g else None,
                     imp_trees=trees_imp.loaded_trees() if st.startswith("imp") else 0, imp_pending=trees_imp.pending() if st.startswith("imp") else 0)
            ST.setdefault("fly", []).append(r)
            log("fly", json.dumps(r))
            ST.update(phase="view", t=now, vi=len(VIEWS))
        elif ph == "end" and el > 2.0:
            res = dict(made=time.strftime("%Y-%m-%d %H:%M:%S"), seconds=round(now - ST["t0"]), states=STATES, views=VIEWS, shots=ST["res"], gpu=ST["gpu"],
                       fly=ST.get("fly", []),
                       near_data=trees_near.DIR, near_meshes=trees_near.MESH_INFO,
                       note="editor PIE without the sim server; lighting = map + monitor preset; GPU = Average GPU frametime of an 8 s fpschart, once per state")
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


sim_client.stop()
ST["h"] = unreal.register_slate_post_tick_callback(tick)
log("scheduled", STATES, "x", len(VIEWS), "views ->", OUT)
