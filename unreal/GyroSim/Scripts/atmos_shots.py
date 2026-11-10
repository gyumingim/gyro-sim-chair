"""Busan air / light / sea shots (developer use), without the sim server: a SECOND editor launched with
    UnrealEditor.exe GyroSim.uproject -GyroSimAtmosShots -RenderOffscreen -nosplash -ABSLOG=<file>
(init_unreal.py). This editor's sim client is stopped first (no UDP to a running server / the user's session), then Play
starts and the script sets up Cesium like sim_client (V-World photo on the local terrain + local buildings with the facade
material, from the proxy), puts the map's view camera at each view and takes HighResShots per variant.
Views = the camera spots of the reference photos (C:/GyroSimTiles/refs/busan_atmos/refs.json, estimates) + two flight
views. Variants (GYROSIM_ATMOS_VARIANTS = JSON file, default: before, after): list of
    {"name": .., "on": true|false, "sky": {..}, "fog": {..}, "pp": {..}, "sun": [el, az], "ground": {..}}
(on=false = the map values + Cesium's stock ground material; on=true = atmos_look values with these overrides).
GPU time (startfpschart, ~1080p pixels) per variant on GYROSIM_ATMOS_GPU views when -ABSLOG is given.
Out: GYROSIM_SHOTS_DIR (default C:/GyroSimTiles/shots/atmos - V-World imagery stays outside git), shots.json. Quits when done.
"""
import json, math, os, re, time
import unreal
import sim_client
import atmos_look

log = lambda *a: unreal.log("[ashots] " + " ".join(str(x) for x in a))
les = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
ues = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem)
OUT = os.environ.get("GYROSIM_SHOTS_DIR", r"C:\GyroSimTiles\shots\atmos")
os.makedirs(OUT, exist_ok=True)
PORT = int(os.environ.get("GYROSIM_ATMOS_PORT", "0")) or sim_client.SimClient.vworld_port()   # a private cache-only proxy may be used
ORIGIN = (35.166538855175816, 128.93864926265002, 29.17)       # = server --start rkpk (lat0, lon0, geoid_n): same frame as Play
# (name, camera lat, lon, alt m MSL, heading deg, pitch deg, horizontal fov deg)
VIEWS = [("r01_dongu", 35.110, 129.032, 150.0, 40.0, -15.0, 75.0),
         ("r02_oryukdo", 35.100, 129.122, 80.0, 160.0, -8.0, 75.0),
         ("r04_yeongdo", 35.083, 129.050, 200.0, 250.0, -6.0, 40.0),
         ("r05_nampo", 35.1008, 129.0325, 170.0, 200.0, -38.0, 75.0),
         ("r07_taejongdae", 35.0470, 129.0800, 120.0, 30.0, -28.0, 75.0),
         ("r10_northport", 35.112, 129.038, 150.0, 40.0, -22.0, 60.0),
         ("r11_harbor", 35.1008, 129.0325, 170.0, 60.0, -8.0, 60.0),
         ("f1_haeundae_1000", 35.120, 129.200, 1000.0, 300.0, -12.0, 75.0),     # flight view, no photo
         ("f2_sea_sun_300", 35.130, 129.190, 300.0, 215.0, -10.0, 75.0)]       # toward the sun over the sea (glint)
if os.environ.get("GYROSIM_ATMOS_VIEWS"):
    VIEWS = [v for v in VIEWS if v[0] in os.environ["GYROSIM_ATMOS_VIEWS"].split(",")]
VARIANTS = [dict(name="before", on=False), dict(name="after", on=True)]
if os.environ.get("GYROSIM_ATMOS_VARIANTS"):
    VARIANTS = json.load(open(os.environ["GYROSIM_ATMOS_VARIANTS"], encoding="utf-8"))
GPU_VIEWS = [x for x in os.environ.get("GYROSIM_ATMOS_GPU", "f1_haeundae_1000,r11_harbor").split(",") if x]
LOGF = os.environ.get("GYROSIM_ATMOS_LOG", "")
ST = dict(t=time.monotonic(), t0=time.monotonic(), phase="wait_editor", si=0, vi=0, h=None, res={}, gpu=[], mi=None)
BASE = dict(sky=dict(atmos_look.AIR["sky"]), fog=dict(atmos_look.AIR["fog"]), pp=dict(atmos_look.AIR["pp"]),
            sun=(atmos_look.SUN_EL, atmos_look.SUN_AZ), ground=dict(atmos_look.GROUND))


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
    gr.set_origin_longitude_latitude_height(unreal.Vector(ORIGIN[1], ORIGIN[0], ORIGIN[2]))
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
    ov.set_editor_property("maximum_level", sim_client.VW_MAX_LEVEL)
    ov.set_maximum_screen_space_error(sim_client.VW_SSE_HIRES)
    ov.set_maximum_simultaneous_tile_loads(8)
    ov.add_to_tileset()
    ov.set_active(True)
    ST["mi"] = unreal.load_asset(atmos_look.GROUND_MI)
    ts.set_editor_property("material", ST["mi"])
    ts.refresh_tileset()
    b.set_actor_location_and_rotation(unreal.Vector(0, 0, 0), rot, False, True)
    b.set_editor_property("tileset_source", unreal.TilesetSource.FROM_URL)
    b.set_editor_property("url", "http://127.0.0.1:%d/buildings/tileset.json" % PORT)
    for k, v in (("maximum_screen_space_error", sim_client.VW_BLDG_SSE), ("create_physics_meshes", False), ("show_credits_on_screen", False)):
        b.set_editor_property(k, v)
    try:
        import buildings_look                                      # facade material, as in Play
        if not buildings_look.apply(b, lambda m: log(m)):         # asset registry may still be scanning: load directly
            mat = unreal.load_asset(buildings_look.MAT)
            if mat:
                b.set_editor_property("material", mat)
                log("buildings material loaded directly", buildings_look.MAT)
    except Exception as e:
        log("buildings look", repr(e))
    b.set_actor_hidden_in_game(False)
    b.refresh_tileset()
    return gr, ts, b


# ground 'off' = MI_GyroGround with neutral parameters (no water, photo colours untouched) - the same pixels as Cesium's
# stock material (same layer stack, vertex normal, layer roughness / specular), but switching needs no tileset reload
GROUND_OFF = dict(WaterOn=0.0, LandSat=1.0, LandContrast=1.0, LandGain=1.0, LandTint=(1.0, 1.0, 1.0))


def set_variant(v):
    w, on = ST["w"], bool(v.get("on", True))
    if on:
        atmos_look.AIR["sky"] = dict(BASE["sky"], **v.get("sky", {}))
        atmos_look.AIR["fog"] = dict(BASE["fog"], **v.get("fog", {}))
        atmos_look.AIR["pp"] = dict(BASE["pp"], **v.get("pp", {}))
        el, az = v.get("sun", BASE["sun"])
        atmos_look.SUN_ROT = (-el, az - 180.0)
        g = dict(BASE["ground"], **v.get("ground", {}))
    else:
        # 'before' also undoes the pp keys any variant touched
        keys = set(BASE["pp"]) | {k for x in VARIANTS for k in x.get("pp", {})}
        atmos_look.AIR["pp"] = {k: BASE["pp"].get(k, 0.0) for k in keys}
        g = dict(BASE["ground"], **GROUND_OFF)
    atmos_look.apply(w, "monitor", on=on)
    if ST["mi"]:
        atmos_look.write_ground_params(ST["mi"], {k: tuple(x) if isinstance(x, list) else x for k, x in g.items()})   # in memory only
    log("variant", v.get("name"), json.dumps(v)[:300])


def place_view(vw):
    name, lat, lon, alt, hdg, pitch, fov = vw
    import geo
    f = geo.Frame(*ORIGIN)
    x, y, z = f.world(lat, lon, alt + ORIGIN[2])                      # alt MSL ~ ellipsoid alt + geoid (N ~ const over Busan)
    # heading / pitch in the local level at the camera (the frame's level tilts 0.45 deg per 50 km)
    fw, rt, up = f.body_axes(lat, lon, 0.0, pitch, hdg)
    roll, p, yw = geo.euler_from_axes(fw, up)
    ST["cam"].set_actor_location_and_rotation(unreal.Vector(x, y, z), unreal.Rotator(roll=roll, pitch=p, yaw=yw), False, True)
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
        if ph == "wait_editor" and el > float(os.environ.get("GYROSIM_ATMOS_WAIT", "40")):
            les.editor_request_begin_play()
            ST.update(phase="wait_pie", t=now)
        elif ph == "wait_pie":
            w = ues.get_game_world()
            if w is not None and el > 3.0:
                ST["w"] = w
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
                    sim_client.apply_preset("monitor", w)          # realism v2 + atmos_look (remembers the map values first)
                except Exception as e:
                    log("preset", repr(e))
                ST["gr"], ST["ts"], ST["b"] = setup_cesium(w)
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
            p1, p2 = progress(ST["ts"]), progress(ST["b"])
            if (p1 >= 99.9 and p2 >= 99.9 and el > 6.0) or el > 90.0:
                ST["load"] = dict(load_s=round(el, 1), terrain=round(p1, 1), buildings=round(p2, 1))
                ST.update(phase="variant", t=now)
        elif ph == "variant":
            if ST["si"] >= len(VARIANTS):
                ST["vi"] += 1
                ST.update(phase="view", t=now); return
            set_variant(VARIANTS[ST["si"]])
            ST.update(phase="shoot", t=now)
        elif ph == "shoot" and el > float(os.environ.get("GYROSIM_ATMOS_SETTLE", "4")):   # auto exposure settles
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
            if el > 8.0:
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
            res = dict(made=time.strftime("%Y-%m-%d %H:%M:%S"), seconds=round(now - ST["t0"]), origin=ORIGIN, views=VIEWS,
                       variants=VARIANTS, shots=ST["res"], gpu=ST["gpu"],
                       note="editor PIE without the sim server; map lighting + monitor preset (realism v2) + atmos_look variant")
            with open(os.path.join(OUT, "shots.json"), "w", encoding="utf-8") as f:
                json.dump(res, f, indent=1, ensure_ascii=False)
            log("done ->", OUT)
            les.editor_request_end_play()
            ST.update(phase="quit", t=now)
        elif ph == "quit" and el > 3.0:
            unreal.unregister_slate_post_tick_callback(ST["h"])
            if os.environ.get("GYROSIM_ATMOS_QUIT", "1") == "1":
                unreal.SystemLibrary.quit_editor()
    except Exception as e:
        import traceback
        log("error", repr(e), " | ".join(traceback.format_exc().splitlines()))
        ST.update(phase="end" if ST["phase"] not in ("end", "quit") else "quit", t=time.monotonic())


sim_client.stop()                      # this editor must not talk to a running server (the user's session)
ST["h"] = unreal.register_slate_post_tick_callback(tick)
log("scheduled", len(VARIANTS), "variants x", len(VIEWS), "views ->", OUT)
