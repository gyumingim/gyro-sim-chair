"""Photo relief A/B shots + GPU + frame time while the relief worker infers (developer use; docs/photo-relief-busan.md).
A SECOND editor, never visible, holding C:/GyroSimTiles/ue_offscreen.lock (the caller takes it):
    UnrealEditor.exe GyroSim.uproject /Game/Maps/FlightMap -RenderOffscreen -nosplash -nosound -unattended
        -ExecCmds="py <repo>/unreal/GyroSim/Scripts/relief_shots.py" -ABSLOG=<log>
GYROSIM_RSHOT_LOG = the same log (GPU numbers). Own sim client stopped first (no UDP to the user's server). Cesium as
grade_shots.py (local terrain, V-World photo through a cache-only proxy, buildings, roads, trees) + atmos_look ground
(-> relief_look starts its worker on the photo proxy). Variants per view: off (RelF.w 0) / on. GPU: fpschart 10 s at
1920 x 1080 pixels (screen percentage), on / off. Fly: the camera moves at GYROSIM_RSHOT_FLY_MS m/s for 20 s (new tiles
-> inference + RT draws) with relief on, then off: frame dt mean / p95 / p99.
Out: GYROSIM_SHOTS_DIR (default C:/GyroSimTiles/shots/relief - V-World derived, stays outside git), shots.json.
"""
import json, math, os, re, time
import unreal
import photo_src
import sim_client
import roads_look
import trees_look
import landmarks_look

log = lambda *a: unreal.log("[rshots] " + " ".join(str(x) for x in a))
les = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
ues = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem)
OUT = os.environ.get("GYROSIM_SHOTS_DIR", r"C:\GyroSimTiles\shots\relief")
os.makedirs(OUT, exist_ok=True)
ROOT = r"C:/GyroSimTiles/buildings"
GEOID = 29.2


def tile_center(x, y, z=18):
    n = 2 ** z
    lon = (x + 0.5) / n * 360.0 - 180.0
    lat = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * (y + 0.5) / n))))
    return lat, lon


def cam_for(tx, ty, alt, hdg, back_m):
    lat, lon = tile_center(tx, ty)
    h = math.radians(hdg)
    return (lat - back_m * math.cos(h) / 110950.0, lon - back_m * math.sin(h) / (111320.0 * math.cos(math.radians(lat))))


# (name, z18 x, z18 y, camera alt m MSL, heading, pitch, fov, horizontal distance back from the tile centre m)
SPOTS = [("road_haeundaero", 225121, 103693, 110.0, 20.0, -24.0, 60.0, 200.0),      # 해운대로 / 해변로: cars, median
         ("beach_gwangalli", 225093, 103698, 80.0, 340.0, -26.0, 60.0, 140.0),      # 광안리 해변: umbrellas, mats
         ("houses_nomesh", 225167, 103655, 190.0, 20.0, -28.0, 60.0, 260.0),        # 기장 villas missing from the 3D tiles
         ("houses_haeundae", 225134, 103689, 150.0, 20.0, -26.0, 60.0, 240.0)]       # 우동 houses (mostly 3D meshes)
VIEWS = []
for nm, tx, ty, alt, hdg, pit, fov, back in SPOTS:
    la, lo = cam_for(tx, ty, alt, hdg, back)
    VIEWS.append((nm, la, lo, alt, hdg, pit, fov))
if os.environ.get("GYROSIM_RSHOT_VIEWS"):
    VIEWS = [v for v in VIEWS if v[0] in os.environ["GYROSIM_RSHOT_VIEWS"].split(",")]
VARIANTS = [dict(name="off"), dict(name="on")]
GPU_VIEWS = [x for x in os.environ.get("GYROSIM_RSHOT_GPU", "road_haeundaero").split(",") if x]
FLY = os.environ.get("GYROSIM_RSHOT_FLY", "1") == "1"
FLY_MS = float(os.environ.get("GYROSIM_RSHOT_FLY_MS", "80"))
LOGF = os.environ.get("GYROSIM_RSHOT_LOG", "")
ST = dict(t=time.monotonic(), t0=time.monotonic(), phase="wait_editor", si=0, vi=0, h=None, res={}, gpu=[], fly=[])


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
    import atmos_look
    atmos_look.apply_ground(ts)                   # -> relief_look.start(ts)
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
    import relief_look
    on = v["name"] == "on"
    relief_look.ST["on"] = on
    if not on:
        relief_look._set(ST["w"], "RelF", (0.0, 0.0, 0.0, 0.0))
    log("variant", v["name"])


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


def relief_idle():
    import relief_look
    s = relief_look.status()
    return s["pending"] == 0 and s["busy"] == 0 and s["resident"] >= 16, s


def stats(d):
    d = sorted(d)
    if not d:
        return {}
    q = lambda p: round(d[min(len(d) - 1, int(p * len(d)))] * 1000, 2)
    return dict(frames=len(d), mean_ms=round(sum(d) / len(d) * 1000, 2), p50_ms=q(0.5), p95_ms=q(0.95), p99_ms=q(0.99), max_ms=q(1.0))


def tick(dt):
    try:
        now = time.monotonic()
        el = now - ST["t"]
        ph = ST["phase"]
        if ph == "wait_editor" and el > float(os.environ.get("GYROSIM_RSHOT_WAIT", "40")):
            for m in (roads_look, landmarks_look, trees_look):
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
                try:
                    import tune_look
                    tune_look.apply(w)                    # tune_defaults.json look (sun 215 / 42 ..), as at Play
                except Exception as e:
                    log("tune", repr(e))
                cmd("t.MaxFPS 0"); cmd("r.VSync 0"); cmd("t.FPSChart.OpenFolderOnDump 0")
                ST.update(phase="view", t=now, vi=0)
            elif el > 120:
                log("no PIE world"); ST.update(phase="end", t=now)
        elif ph == "view" and el > 1.0:
            if ST["vi"] >= len(VIEWS):
                ST.update(phase="fly" if FLY else "end", t=now, si=0); return
            unreal.GameplayStatics.get_player_controller(ST["w"], 0).set_view_target_with_blend(ST["cam"], 0.0)
            place_view(VIEWS[ST["vi"]])
            set_variant(dict(name="on"))
            ST.update(phase="load", t=now, si=0)
        elif ph == "load":
            ps = [progress(ST["ts"]), progress(ST["b"])] + [progress(x) for x in ST.get("extra", [])]
            idle, rs = relief_idle()
            if (min(ps) >= 99.9 and idle and el > 8.0) or el > 150.0:
                ST["load"] = dict(load_s=round(el, 1), progress=[round(p, 1) for p in ps], relief=rs)
                log("loaded", json.dumps(ST["load"]))
                ST.update(phase="variant", t=now)
        elif ph == "variant":
            if ST["si"] >= len(VARIANTS):
                ST["vi"] += 1
                ST.update(phase="view", t=now); return
            set_variant(VARIANTS[ST["si"]])
            ST.update(phase="shoot", t=now)
        elif ph == "shoot" and el > float(os.environ.get("GYROSIM_RSHOT_SETTLE", "4")):
            vw, v = VIEWS[ST["vi"]], VARIANTS[ST["si"]]
            fn = os.path.join(OUT, "%s_%s.png" % (vw[0], v["name"])).replace("\\", "/")
            cmd("HighResShot %s filename=%s" % (os.environ.get("GYROSIM_SHOT_RES", "1600x900"), fn))
            ST["res"]["%s_%s" % (vw[0], v["name"])] = dict(ST.get("load", {}), file=fn)
            log("shot", fn)
            if vw[0] in GPU_VIEWS and LOGF:
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
            r = dict(view=vw[0], variant=v["name"], gpu_ms=gpu_from_log(), viewport=ST["sp"][:2], screen_percentage=ST["sp"][2],
                     **stats(ST["dts"][5:]))
            ST["gpu"].append(r)
            log("gpu", json.dumps(r))
            cmd("r.ScreenPercentage 100")
            ST["si"] += 1
            ST.update(phase="variant", t=now)
        elif ph == "fly":                                  # relief on (new tiles while moving), then off; same path
            if ST["si"] >= 2:
                ST.update(phase="end", t=now); return
            v = ["on", "off"][ST["si"]]
            vw = VIEWS[0]
            place_view((vw[0], vw[1] - 0.004 * ST["si"], vw[2], vw[3], vw[4], vw[5], vw[6]))
            set_variant(dict(name=v))
            ST.update(phase="fly_settle", t=now, dts=[], fly_v=v)
        elif ph == "fly_settle" and el > 6.0:
            import relief_look
            ST.update(phase="fly_run", t=now, dts=[], drawn0=relief_look.ST["n_drawn"], req0=relief_look.ST["n_req"])
        elif ph == "fly_run":
            ST["dts"].append(dt)
            c = ST["cam"]
            l = c.get_actor_location()
            f = c.get_actor_forward_vector()
            hz = math.hypot(f.x, f.y) or 1.0
            c.set_actor_location(unreal.Vector(l.x + f.x / hz * FLY_MS * 100.0 * dt, l.y + f.y / hz * FLY_MS * 100.0 * dt, l.z), False, True)
            if el > 20.0:
                import relief_look
                r = dict(variant=ST["fly_v"], speed_ms=FLY_MS, seconds=round(el, 1), tiles_drawn=relief_look.ST["n_drawn"] - ST["drawn0"],
                         tiles_requested=relief_look.ST["n_req"] - ST["req0"], relief=relief_look.status(),
                         worker=relief_look.worker_status(), **stats(ST["dts"][10:]))
                ST["fly"].append(r)
                log("fly", json.dumps(r))
                ST["si"] += 1
                ST.update(phase="fly", t=now)
        elif ph == "end" and el > 2.0:
            import relief_look
            res = dict(made=time.strftime("%Y-%m-%d %H:%M:%S"), seconds=round(now - ST["t0"]), views=VIEWS, spots=SPOTS,
                       shots=ST["res"], gpu=ST["gpu"], fly=ST["fly"], relief=relief_look.status(), worker=relief_look.worker_status(),
                       note="editor PIE without the sim server; local tiles; monitor preset + tune defaults; relief off = RelF.w 0")
            with open(os.path.join(OUT, "shots.json"), "w", encoding="utf-8") as f:
                json.dump(res, f, indent=1, ensure_ascii=False, default=str)
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


sim_client.stop()
ST["h"] = unreal.register_slate_post_tick_callback(tick)
log("scheduled", len(VARIANTS), "variants x", len(VIEWS), "views ->", OUT)
