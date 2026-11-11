"""Art-direction survey / before-after shots of the Busan Play look (developer use), without the sim server.
Launch a SECOND editor, never visible (the caller holds C:/GyroSimTiles/ue_offscreen.lock):
    UnrealEditor.exe GyroSim.uproject /Game/Maps/FlightMap -GyroSimArtShots -RenderOffscreen -nosplash -unattended -ABSLOG=<log>
Same set-up as grade_shots.py (local terrain + V-World cache by file://, buildings / roads / landmarks / trees via their
*_look modules, sim_client.apply_preset 'monitor' = realism v2 + atmos_look + grade_look). Every GYROSIM_* toggle comes from
the environment of the launch, so one launch = one variant (before / after = two launches with different env).
Env:
  GYROSIM_ART_VIEWS   JSON file: [[name, lat, lon, alt m MSL, heading deg, pitch deg, horizontal fov deg, {opts}], ..]
                      opts: sun = [azimuth deg, elevation deg] (else atmos_look's sun)
  GYROSIM_ART_PICK    comma list of view names to shoot (default all)
  GYROSIM_ART_TAG     file suffix (default 'shot') -> <view>_<tag>.png
  GYROSIM_ART_GPU     comma list of views with a GPU measurement (startfpschart 10 s, ~1080p pixels)
  GYROSIM_ART_LOG     the -ABSLOG file (GPU numbers are read from it)
  GYROSIM_ART_VARIANTS JSON file (sweeps only): [{"name": .., "ground": {MI param: value}, "bldg": {param: value}, "tree": {param: value},
                      "trees": {"v2": 0|1, "look2": 0|1, "tiles": folder} (trees_look version / v2 material extras / tile build),
                      "cloud": {VolumetricCloudComponent prop: value}, "cloudmat": {cloud material param: value}, "sky": {SkyAtmosphereComponent prop: value},
                      "fog": {..}, "skylight": {SkyLightComponent prop: value}, "light": {DirectionalLightComponent prop: value},
                      "cvars": {console variable: value}, "pp": {grade_look extra},
                      "lm": {MI_GyroLandmark scalar: value} (instance of the MI asset itself),
                      "grounded": 0|1, "grounded_def": {atmos_look.GROUNDED_DEF key: value} (low-sun cloud shadow fade)}, ..] - each view is shot once per variant (tilesets whose
                      material changes are refreshed and reloaded); file <view>_<variant>.png. Default: one shot, TAG.
  GYROSIM_ART_HOOK    optional .py file exec'd once after the Play look is applied (probes / dumps; gets ST, log, unreal)
  GYROSIM_SHOTS_DIR   output folder (default C:/GyroSimTiles/shots/art - V-World imagery stays outside git), shots_<tag>.json
Quits the editor when done.
"""
import json, math, os, re, time
import unreal
import photo_src                      # V-World photo with the white-gap fix (cache-only proxy), as at Play
import sim_client
import roads_look
import trees_look
import piers_look
import landmarks_look

log = lambda *a: unreal.log("[artshots] " + " ".join(str(x) for x in a))
les = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
ues = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem)
OUT = os.environ.get("GYROSIM_SHOTS_DIR", r"C:\GyroSimTiles\shots\art")
os.makedirs(OUT, exist_ok=True)
ROOT = r"C:/GyroSimTiles/buildings"
GEOID = 29.2
TAG = os.environ.get("GYROSIM_ART_TAG", "shot")
VIEWS = json.load(open(os.environ["GYROSIM_ART_VIEWS"], encoding="utf-8-sig"))
if os.environ.get("GYROSIM_ART_PICK"):
    VIEWS = [v for v in VIEWS if v[0] in os.environ["GYROSIM_ART_PICK"].split(",")]
GPU_VIEWS = [x for x in os.environ.get("GYROSIM_ART_GPU", "").split(",") if x]
LOGF = os.environ.get("GYROSIM_ART_LOG", "")
VARIANTS = json.load(open(os.environ["GYROSIM_ART_VARIANTS"], encoding="utf-8-sig")) if os.environ.get("GYROSIM_ART_VARIANTS") else [dict(name=TAG)]
ST = dict(t=time.monotonic(), t0=time.monotonic(), phase="wait_editor", vi=0, si=0, h=None, res={}, gpu=[], cur=None)


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
    ts.set_editor_property("url", "file:///%s/layer.json" % os.environ.get("GYROSIM_ART_TERRAIN", "C:/GyroSimTiles/terrain/tiles").replace("\\", "/"))
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
                               trees_look.apply(world, log, gr), piers_look.apply(world, log, gr)) if x is not None]
    return gr, ts, b


def set_sun(opts):
    import atmos_look
    if opts.get("sun"):
        az, el = opts["sun"]
        rot = (-el, az - 180.0)
    else:
        rot = atmos_look.SUN_ROT if atmos_look.STATE["on"] else None
    if rot is None:
        return
    for a in unreal.GameplayStatics.get_all_actors_of_class(ST["w"], unreal.DirectionalLight):
        a.set_actor_rotation(unreal.Rotator(roll=0.0, pitch=rot[0], yaw=rot[1]), False)
    grounded()


def grounded():
    """low-sun cloud shadow fade (atmos_look.apply_grounded) for the current sun and variant ('grounded': 0 | 1,
    'grounded_def': {CLOUD_SURF_LOW / CLOUD_EL_LOW / CLOUD_EL_HIGH} for sweeps; the module values are restored after)"""
    import atmos_look
    v = ST.get("cur") or {}
    keep = dict(atmos_look.GROUNDED_DEF)
    atmos_look.GROUNDED_DEF.update(v.get("grounded_def") or {})
    try:
        atmos_look.apply_grounded(ST["w"], on=(atmos_look.grounded_on() if v.get("grounded") is None else bool(v["grounded"])))
    finally:
        atmos_look.GROUNDED_DEF.clear(); atmos_look.GROUNDED_DEF.update(keep)


def _mid(tileset, base_attr, params):
    """dynamic instance of the tileset's current material with params set (Cesium copies its values onto every tile)."""
    base = ST.setdefault("base_mat", {}).setdefault(base_attr, unreal.load_asset(landmarks_look.GLASS_MI) if base_attr == "lm"
                                                    else tileset.get_editor_property("material"))   # lm: never a MID of the Play MID
    if not params:
        tileset.set_editor_property("material", base)
        return
    m = unreal.MaterialLibrary.create_dynamic_material_instance(ST["w"], base)
    for k, v in params.items():
        if isinstance(v, (list, tuple)):
            m.set_vector_parameter_value(k, unreal.LinearColor(*(list(v) + [1.0])[:4]))
        else:
            m.set_scalar_parameter_value(k, float(v))
    tileset.set_editor_property("material", m)


CLOUD_VEC = {"Cloud_AlbedoColor", "Layout_WindControls", "Layout_CloudType"}


def set_variant(v):
    """-> True when a tileset was refreshed (wait for the load again)."""
    w = ST["w"]
    prev = ST["cur"] or {}
    reload = False
    if v.get("ground") != prev.get("ground") or ST["cur"] is None:
        _mid(ST["ts"], "ground", v.get("ground")); ST["ts"].refresh_tileset(); reload = True
    if v.get("bldg") != prev.get("bldg") or ST["cur"] is None:
        _mid(ST["b"], "bldg", v.get("bldg")); ST["b"].refresh_tileset(); reload = True
    if "trees" in v and v.get("trees") != prev.get("trees"):          # trees v1 / v2 / v2 without look extras (one-run A/B)
        tv = v["trees"]
        trees_look.apply(w, log, ST["gr"], v2=bool(tv.get("v2", True)), look2=bool(tv.get("look2", True)), tiles=tv.get("tiles"))
        ST.get("base_mat", {}).pop("tree", None)
        reload = True
    lm = landmarks_look.find(w)                  # landmark glass parameters (MI_GyroLandmark scalars)
    if lm is not None and (v.get("lm") != prev.get("lm") or ST["cur"] is None) and (v.get("lm") or prev.get("lm") or ST.get("lm_mid")):
        _mid(lm, "lm", v.get("lm")); lm.refresh_tileset(); reload = True; ST["lm_mid"] = True
    tr = trees_look.find(w)
    if tr is not None and (v.get("tree") != prev.get("tree") or ST["cur"] is None):
        _mid(tr, "tree", v.get("tree")); tr.refresh_tileset(); reload = True
    if v.get("pp") is not None or prev.get("pp") is not None:
        # first: apply_look re-applies realism v2 / atmos / light / grade, i.e. it would undo the component values below
        import grade_look
        sim_client.apply_look("monitor", w)
        grade_look.apply(w, "monitor", extra=v.get("pp"))
        vw = VIEWS[ST["vi"]]                     # apply_look -> atmos_look.apply puts the sun back to its default:
        set_sun(vw[7] if len(vw) > 7 else {})    # the view's own sun again (a16 / a17 / a18 were shot with the default sun)
    cm = v.get("cloudmat") or {}                 # cloud material parameters on the cloud component's dynamic instance
    if cm or prev.get("cloudmat"):
        for a in unreal.GameplayStatics.get_all_actors_of_class(w, unreal.VolumetricCloud):
            c = a.get_component_by_class(unreal.VolumetricCloudComponent)
            m = c.get_editor_property("material")
            if not isinstance(m, unreal.MaterialInstanceDynamic):
                m = unreal.MaterialLibrary.create_dynamic_material_instance(w, m)
                c.set_editor_property("material", m)
            co = ST.setdefault("orig_cloudmat", {})
            for k in set(co) | set(cm):
                if k not in co:
                    co[k] = m.get_vector_parameter_value(k) if k in CLOUD_VEC else m.get_scalar_parameter_value(k)
                val = cm.get(k, co[k])
                if k in CLOUD_VEC:
                    if isinstance(val, (list, tuple)):
                        val = unreal.LinearColor(*(list(val) + [1.0])[:4])
                    m.set_vector_parameter_value(k, val)
                else:
                    m.set_scalar_parameter_value(k, float(val))
    import atmos_look
    for key, cls, ccls in (("cloud", unreal.VolumetricCloud, unreal.VolumetricCloudComponent),
                           ("sky", unreal.SkyAtmosphere, unreal.SkyAtmosphereComponent),
                           ("fog", unreal.ExponentialHeightFog, unreal.ExponentialHeightFogComponent),
                           ("skylight", unreal.SkyLight, unreal.SkyLightComponent),
                           ("light", unreal.DirectionalLight, unreal.DirectionalLightComponent)):
        orig = ST.setdefault("orig_" + key, {})
        want = v.get(key) or {}
        for a in unreal.GameplayStatics.get_all_actors_of_class(w, cls):
            c = a.get_component_by_class(ccls)
            for k in set(orig) | set(want):
                if k not in orig:
                    orig[k] = atmos_look._get(c, k)
                    log("orig", key, k, orig[k])
                val = want.get(k, orig[k])
                if val is not None:
                    atmos_look._set(c, k, val, key)
    corig = ST.setdefault("orig_cvars", {})
    cw = v.get("cvars") or {}
    for k in set(corig) | set(cw):
        if k not in corig:
            corig[k] = unreal.SystemLibrary.get_console_variable_float_value(k)
            log("orig cvar", k, corig[k])
        val = cw.get(k, corig[k])
        cmd("%s %s" % (k, ("%g" % val) if isinstance(val, float) else val))
    ST["cur"] = v
    if "light" not in v:                         # a variant's explicit light values win over the grounded rule
        grounded()
    log("variant", json.dumps(v)[:300])
    return reload


def place_view(vw):
    name, lat, lon, alt, hdg, pitch, fov = vw[:7]
    opts = vw[7] if len(vw) > 7 else {}
    ST["gr"].set_origin_longitude_latitude_height(unreal.Vector(lon, lat, GEOID))
    ST["cam"].set_actor_location_and_rotation(unreal.Vector(0.0, 0.0, alt * 100.0),
                                              unreal.Rotator(roll=0.0, pitch=pitch, yaw=hdg), False, True)
    ST["cam"].camera_component.set_editor_property("field_of_view", fov)
    set_sun(opts)


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
        if ph == "wait_editor" and el > float(os.environ.get("GYROSIM_ART_WAIT", "40")):
            for m in (roads_look, landmarks_look, trees_look, piers_look):   # editor-world actors before Play (never saved)
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
                if os.environ.get("GYROSIM_ART_HOOK"):
                    try:
                        exec(open(os.environ["GYROSIM_ART_HOOK"], encoding="utf-8").read(), dict(ST=ST, log=log, unreal=unreal, OUT=OUT))
                    except Exception as e:
                        log("hook", repr(e))
                ST.update(phase="view", t=now, vi=0)
            elif el > 120:
                log("no PIE world"); ST.update(phase="end", t=now)
        elif ph == "view" and el > 1.0:
            if ST["vi"] >= len(VIEWS):
                ST.update(phase="end", t=now); return
            pc = unreal.GameplayStatics.get_player_controller(ST["w"], 0)
            pc.set_view_target_with_blend(ST["cam"], 0.0)
            place_view(VIEWS[ST["vi"]])
            ST.update(phase="load", t=now, si=0, after_variant=False)
        elif ph == "load":
            ps = [progress(ST["ts"]), progress(ST["b"])] + [progress(x) for x in ST.get("extra", [])]
            if (min(ps) >= 99.9 and el > 8.0) or el > 120.0:
                ST["load"] = dict(load_s=round(el, 1), progress=[round(p, 1) for p in ps])
                ST.update(phase="shoot" if ST.get("after_variant") else "variant", t=now)
        elif ph == "variant":
            if ST["si"] >= len(VARIANTS):
                ST["vi"] += 1
                ST.update(phase="view", t=now); return
            v = VARIANTS[ST["si"]]
            if len(VARIANTS) > 1 or v.keys() - {"name"}:
                if set_variant(v):
                    ST.update(phase="load", t=now, after_variant=True); return
            ST.update(phase="shoot", t=now, after_variant=False)
        elif ph == "shoot" and el > float(os.environ.get("GYROSIM_ART_SETTLE", "5")):     # auto exposure settles
            vw, vn = VIEWS[ST["vi"]], VARIANTS[ST["si"]]["name"]
            fn = os.path.join(OUT, "%s_%s.png" % (vw[0], vn)).replace("\\", "/")
            cmd("HighResShot %s filename=%s" % (os.environ.get("GYROSIM_SHOT_RES", "1600x900"), fn))
            ST["res"]["%s_%s" % (vw[0], vn)] = dict(ST.get("load", {}), file=fn)
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
            vw = VIEWS[ST["vi"]]
            d = sorted(ST["dts"][5:])
            r = dict(view=vw[0], variant=VARIANTS[ST["si"]]["name"], gpu_ms=gpu_from_log(), viewport=ST["sp"][:2], screen_percentage=ST["sp"][2],
                     frames=len(d), avg_ms=round(sum(d) / len(d) * 1000, 2) if d else None)
            ST["gpu"].append(r)
            log("gpu", json.dumps(r))
            cmd("r.ScreenPercentage 100")
            ST["si"] += 1
            ST.update(phase="variant", t=now)
        elif ph == "end" and el > 2.0:
            env = {k: v for k, v in os.environ.items() if k.startswith("GYROSIM_")
                   and not any(s in k.upper() for s in ("KEY", "TOKEN", "SECRET", "PASS", "AUTH"))}
            git = {}
            try:                               # which code made these shots: HEAD + hash of the uncommitted diff
                import subprocess, hashlib
                repo = os.path.abspath(unreal.Paths.convert_relative_path_to_full(unreal.Paths.project_dir()))
                run = lambda *a: subprocess.run(["git", "-C", repo] + list(a), capture_output=True, timeout=20,
                                                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).stdout
                git = dict(head=run("rev-parse", "HEAD").decode().strip(),
                           diff_sha1=hashlib.sha1(run("diff", "HEAD")).hexdigest(),
                           dirty=[l for l in run("status", "--porcelain", "-uno").decode().splitlines()][:60])
            except Exception as e:
                git = dict(error=repr(e)[:120])
            res = dict(made=time.strftime("%Y-%m-%d %H:%M:%S"), seconds=round(now - ST["t0"]), tag=TAG, git=git, views=VIEWS, variants=VARIANTS,
                       env=env, shots=ST["res"], gpu=ST["gpu"],
                       note="editor PIE without the sim server; local tiles; monitor preset (realism v2, atmos_look, grade_look)")
            with open(os.path.join(OUT, "shots_%s.json" % TAG), "w", encoding="utf-8") as f:
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
log("scheduled", len(VIEWS), "views, tag", TAG, "->", OUT)
