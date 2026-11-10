r"""ue_airframe.py - airframe realism pass, headless (editor CLOSED; hold C:\GyroSimTiles\ue_offscreen.lock):
  "C:\Program Files\Epic Games\UE_5.8\Engine\Binaries\Win64\UnrealEditor-Cmd.exe" <path>\GyroSim.uproject ^
      -run=pythonscript -script=<path>\Scripts\aircraft\ue_airframe.py -unattended -nosplash -nullrhi

Assets (no map change):
  /Game/Aircraft/M_GyroAirframe          painted metal skin: skin texture x tint, panel lines / rivets darker and
                                         slightly recessed (normal map), grime around panels, roughness variation (ours)
  /Game/Aircraft/M_GyroNavLight          unlit emissive lens for the nav / strobe lights (ours)
  /Game/Aircraft/Sounds/SW_EngineLoop, SW_WindLoop   looping sounds from Art/Sounds (ours, make_sounds.py)
  /Game/ThirdParty/F16/Airframe/...      F16_Body + 7 control surfaces (airframe_split.py), derived skin textures
                                         (airframe_tex.py), material instances - GPL-2.0 derived, outside git
Map (GYROSIM_AF_MAP=0 skips it): /Game/Maps/FlightMap gets hidden actors attached to 'Aircraft':
  AC_Surf_<name> (tags AircraftPart, AirframeSurf, Surf_<name>, axis:<x>,<y>,<z>) at the hinge points, and
  AC_Light_<name> (tags AircraftPart, AirframeLight, Light_<name>) lens spheres. Content/Python/airframe_live.py shows
  them and swaps the exterior mesh at Play; without them the old one-piece exterior stays. Safe to run again.
"""
import json
import os

import unreal

PROJ = unreal.Paths.convert_relative_path_to_full(unreal.Paths.project_dir())
SRC = os.path.join(PROJ, "ThirdParty", "f16_airframe")
ART = os.path.join(PROJ, "Art", "Sounds")
TP = "/Game/ThirdParty/F16/Airframe"
OWN = "/Game/Aircraft"
MAP = "/Game/Maps/FlightMap"
log = lambda *a: unreal.log("[airframe] " + " ".join(str(x) for x in a))
EAL = unreal.EditorAssetLibrary
MEL = unreal.MaterialEditingLibrary
assets = unreal.AssetToolsHelpers.get_asset_tools()
MP = unreal.MaterialProperty


# ---- material helpers (same style as build_level.py) ----------------------------------------------------------------
def _new_material(name, folder):
    path = f"{folder}/{name}"
    if EAL.does_asset_exist(path):
        m = unreal.load_asset(path)
        MEL.delete_all_material_expressions(m)
        return m
    return assets.create_asset(name, folder, unreal.Material, unreal.MaterialFactoryNew())


def _expr(m, cls, x, y, **props):
    e = MEL.create_material_expression(m, cls, x, y)
    for k, v in props.items():
        e.set_editor_property(k, v)
    return e


def _const(m, v, x, y):
    return _expr(m, unreal.MaterialExpressionConstant, x, y, r=v)


def _const3(m, c, x, y):
    return _expr(m, unreal.MaterialExpressionConstant3Vector, x, y, constant=unreal.LinearColor(c[0], c[1], c[2], 1.0))


def _sp(m, n, v, x, y):
    return _expr(m, unreal.MaterialExpressionScalarParameter, x, y, parameter_name=n, default_value=v)


def _vp(m, n, c, x, y):
    return _expr(m, unreal.MaterialExpressionVectorParameter, x, y, parameter_name=n, default_value=unreal.LinearColor(c[0], c[1], c[2], 1.0))


def _op(m, cls, a, b, x, y, ao="", bo=""):
    e = _expr(m, cls, x, y)
    MEL.connect_material_expressions(a, ao, e, "A")
    MEL.connect_material_expressions(b, bo, e, "B")
    return e


def _tp(m, n, tex, st, x, y):
    s = _expr(m, unreal.MaterialExpressionTextureSampleParameter2D, x, y, parameter_name=n)
    s.set_editor_property("texture", tex)
    s.set_editor_property("sampler_type", st)
    return s


def _lerp(m, a, b, alpha, x, y, ao="", bo="", lo=""):
    e = _expr(m, unreal.MaterialExpressionLinearInterpolate, x, y)
    MEL.connect_material_expressions(a, ao, e, "A")
    MEL.connect_material_expressions(b, bo, e, "B")
    MEL.connect_material_expressions(alpha, lo, e, "Alpha")
    return e


def clear_coat(m, cc, cr):
    """thin clear coat when the material property enum exposes the custom data pins (name differs between versions);
    else the default lit model (11-10: the first try set the model but not the pins -> a full-strength coat)."""
    p0 = next((getattr(MP, n) for n in ("MP_CUSTOM_DATA0", "MP_CUSTOMDATA0", "MP_CUSTOM_DATA_0") if hasattr(MP, n)), None)
    p1 = next((getattr(MP, n) for n in ("MP_CUSTOM_DATA1", "MP_CUSTOMDATA1", "MP_CUSTOM_DATA_1") if hasattr(MP, n)), None)
    if p0 is None or p1 is None:
        m.set_editor_property("shading_model", unreal.MaterialShadingModel.MSM_DEFAULT_LIT)
        log("clear coat pins not exposed - default lit", [n for n in dir(MP) if n.startswith("MP_")][:40])
        return
    m.set_editor_property("shading_model", unreal.MaterialShadingModel.MSM_CLEAR_COAT)
    MEL.connect_material_property(_sp(m, "ClearCoat", cc, -550, 700), "", p0)
    MEL.connect_material_property(_sp(m, "ClearCoatRough", cr, -550, 780), "", p1)


def airframe_master(tx):
    """BaseColor = Paint * Tint * (1 - LineDark * line * Detail) * lerp(1, GrimeTint, grime * GrimeAmt * Detail)
    Roughness = Rough + (rvar - 0.5) * RoughVar * Detail + line * 0.12 * Detail;  Normal = lerp(flat, Nrm, NormalStr * Detail)."""
    m = _new_material("M_GyroAirframe", TP + "/Materials")      # GPL textures as defaults -> gitignored folder
    m.set_editor_property("two_sided", True)
    ST = unreal.MaterialSamplerType
    paint = _tp(m, "Paint", tx["tex_f16_paint"], ST.SAMPLERTYPE_COLOR, -1600, -400)
    mask = _tp(m, "Mask", tx["tex_f16_m"], ST.SAMPLERTYPE_LINEAR_COLOR, -1600, 0)
    nrm = _tp(m, "Nrm", tx["tex_f16_n"], ST.SAMPLERTYPE_NORMAL, -1600, 400)
    detail = _sp(m, "Detail", 1.0, -1600, 700)
    line = _op(m, unreal.MaterialExpressionMultiply, mask, detail, -1300, -50, "R", "")
    grime = _op(m, unreal.MaterialExpressionMultiply, _op(m, unreal.MaterialExpressionMultiply, mask, detail, -1300, 60, "G", ""),
                _sp(m, "GrimeAmt", 0.35, -1450, 160), -1150, 60)
    col = _op(m, unreal.MaterialExpressionMultiply, paint, _vp(m, "Tint", (0.62, 0.62, 0.62), -1450, -300), -1250, -400, "RGB", "")
    one = _const(m, 1.0, -1250, -200)
    lined = _op(m, unreal.MaterialExpressionSubtract, one, _op(m, unreal.MaterialExpressionMultiply, line, _sp(m, "LineDark", 0.45, -1300, -150), -1100, -150), -950, -200)
    col2 = _op(m, unreal.MaterialExpressionMultiply, col, lined, -800, -350)
    gtint = _lerp(m, _const3(m, (1, 1, 1), -900, -50), _vp(m, "GrimeTint", (0.62, 0.58, 0.52), -1000, 0), grime, -750, -50)
    base = _op(m, unreal.MaterialExpressionMultiply, col2, gtint, -550, -300)
    MEL.connect_material_property(base, "", MP.MP_BASE_COLOR)
    rv = _op(m, unreal.MaterialExpressionMultiply, _op(m, unreal.MaterialExpressionSubtract, mask, _const(m, 0.5, -1300, 330), -1150, 260, "B", ""),
             _op(m, unreal.MaterialExpressionMultiply, _sp(m, "RoughVar", 0.25, -1300, 420), detail, -1150, 400), -950, 300)
    rough = _op(m, unreal.MaterialExpressionAdd, _op(m, unreal.MaterialExpressionAdd, _sp(m, "Rough", 0.55, -900, 180), rv, -750, 220),
                _op(m, unreal.MaterialExpressionMultiply, line, _const(m, 0.12, -900, 120), -750, 120), -550, 180)
    MEL.connect_material_property(rough, "", MP.MP_ROUGHNESS)
    MEL.connect_material_property(_sp(m, "Metal", 0.0, -550, 280), "", MP.MP_METALLIC)
    nstr = _op(m, unreal.MaterialExpressionMultiply, _sp(m, "NormalStr", 1.0, -1300, 560), detail, -1150, 560)
    n = _lerp(m, _const3(m, (0, 0, 1), -1150, 480), nrm, nstr, -550, 420, "", "RGB", "")
    MEL.connect_material_property(n, "", MP.MP_NORMAL)
    # light bounced up from the ground / sea (the sky light's lower half is black and Lumen does not see the far Cesium
    # ground, so the belly went near black, r4): emissive = base x BounceColor x Bounce x saturate(-normal.z)
    wn = _expr(m, unreal.MaterialExpressionVertexNormalWS, -1300, 900)
    nz = _expr(m, unreal.MaterialExpressionComponentMask, -1150, 900, r=False, g=False, b=True, a=False)
    MEL.connect_material_expressions(wn, "", nz, "")
    down = _expr(m, unreal.MaterialExpressionSaturate, -900, 900)
    MEL.connect_material_expressions(_op(m, unreal.MaterialExpressionMultiply, nz, _const(m, -1.0, -1150, 980), -1000, 900), "", down, "")
    # + sky fill on every side (r6: the shaded fin side measured sRGB ~30 against ~170 on the lit nose; real photos keep
    # the shaded grey around a third of the lit side): amount = Bounce x down + SkyFill x (1 - down)
    amt = _op(m, unreal.MaterialExpressionAdd, _op(m, unreal.MaterialExpressionMultiply, down, _sp(m, "Bounce", 0.6, -900, 1080), -750, 1050),
              _op(m, unreal.MaterialExpressionMultiply, _op(m, unreal.MaterialExpressionSubtract, _const(m, 1.0, -1000, 1160), down, -900, 1160),
                  _sp(m, "SkyFill", 0.4, -900, 1240), -750, 1180), -650, 1100)
    bounce = _op(m, unreal.MaterialExpressionMultiply, _op(m, unreal.MaterialExpressionMultiply, base, _vp(m, "BounceColor", (0.85, 0.85, 0.8), -900, 1000), -750, 950),
                 amt, -550, 980)
    MEL.connect_material_property(bounce, "", MP.MP_EMISSIVE_COLOR)
    # semi-gloss paint: a thin clear coat (sharper sky / sun reflection at grazing angles) over the matte base
    clear_coat(m, 0.15, 0.35)
    MEL.recompile_material(m)
    EAL.save_loaded_asset(m)
    return m


def light_master():
    m = _new_material("M_GyroNavLight", OWN)
    m.set_editor_property("shading_model", unreal.MaterialShadingModel.MSM_UNLIT)
    e = _op(m, unreal.MaterialExpressionMultiply, _vp(m, "Color", (1, 1, 1), -600, 0), _sp(m, "Glow", 20.0, -600, 150), -350, 50)
    MEL.connect_material_property(e, "", MP.MP_EMISSIVE_COLOR)
    MEL.recompile_material(m)
    EAL.save_loaded_asset(m)
    return m


def instance(name, parent, folder, scalars=None, colors=None, textures=None):
    path = f"{folder}/{name}"
    mi = unreal.load_asset(path) if EAL.does_asset_exist(path) else \
        assets.create_asset(name, folder, unreal.MaterialInstanceConstant, unreal.MaterialInstanceConstantFactoryNew())
    MEL.set_material_instance_parent(mi, parent)
    MEL.clear_all_material_instance_parameters(mi)
    for k, v in (scalars or {}).items():
        MEL.set_material_instance_scalar_parameter_value(mi, k, v)
    for k, c in (colors or {}).items():
        MEL.set_material_instance_vector_parameter_value(mi, k, unreal.LinearColor(c[0], c[1], c[2], 1.0))
    for k, t in (textures or {}).items():
        MEL.set_material_instance_texture_parameter_value(mi, k, t)
    MEL.update_material_instance(mi)
    EAL.save_loaded_asset(mi)
    return mi


def import_files(files, dest):
    tasks = []
    for f in files:
        t = unreal.AssetImportTask()
        t.filename = f
        t.destination_path = dest
        t.automated = True
        t.replace_existing = True
        t.save = True
        tasks.append(t)
    assets.import_asset_tasks(tasks)
    return {os.path.splitext(os.path.basename(f))[0]: unreal.load_asset(f"{dest}/{os.path.splitext(os.path.basename(f))[0]}") for f in files}


def textures():
    names = ("tex_f16_paint", "tex_f16_n", "tex_f16_m", "tex_nozzle_GE", "tex_nozzle_ring")
    tx = import_files([os.path.join(SRC, n + ".png") for n in names], TP + "/Textures")
    TC = unreal.TextureCompressionSettings
    tx["tex_f16_n"].set_editor_property("compression_settings", TC.TC_NORMALMAP)
    tx["tex_f16_n"].set_editor_property("srgb", False)
    tx["tex_f16_m"].set_editor_property("srgb", False)
    for t in tx.values():
        EAL.save_loaded_asset(t)
    return tx


def meshes(suffix=""):
    info = json.load(open(os.path.join(SRC, "airframe.json"), encoding="utf-8"))
    tmp = os.path.join(PROJ, "Intermediate", "f16_airframe_import")
    os.makedirs(tmp, exist_ok=True)
    try:
        unreal.SystemLibrary.execute_console_command(unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_editor_world(),
                                                     "Interchange.FeatureFlags.Import.OBJ 0")   # legacy (FBX SDK) OBJ importer
    except Exception as e:
        log("interchange flag", e)
    out = {}
    for name in [n + suffix for n in info["parts"]]:
        src, dst = os.path.join(SRC, name + ".obj"), os.path.join(tmp, name + ".obj")
        with open(src, encoding="utf-8") as f, open(dst, "w", encoding="utf-8") as g:   # = build_level._prep_obj
            for ln in f:
                if ln.startswith("v ") or ln.startswith("vn "):
                    k, x, y, z = ln.split()[:4]
                    g.write("%s %s %s %s\n" % (k, x, "%.6g" % -float(z), y))
                else:
                    g.write(ln)
        with open(os.path.join(SRC, name + ".mtl"), encoding="utf-8") as f, open(os.path.join(tmp, name + ".mtl"), "w", encoding="utf-8") as g:
            g.write(f.read())
        t = unreal.AssetImportTask()
        t.filename, t.destination_path, t.automated, t.replace_existing, t.save = dst, TP + "/Meshes", True, True, True
        o = unreal.FbxImportUI()
        o.set_editor_property("import_mesh", True)
        o.set_editor_property("import_materials", False)
        o.set_editor_property("import_textures", False)
        o.set_editor_property("import_as_skeletal", False)
        o.set_editor_property("mesh_type_to_import", unreal.FBXImportType.FBXIT_STATIC_MESH)
        sd = o.get_editor_property("static_mesh_import_data")
        sd.set_editor_property("combine_meshes", True)
        sd.set_editor_property("generate_lightmap_u_vs", False)
        sd.set_editor_property("auto_generate_collision", False)
        sd.set_editor_property("normal_import_method", unreal.FBXNormalImportMethod.FBXNIM_IMPORT_NORMALS)
        try:
            sd.set_editor_property("convert_scene", False)
        except Exception:
            pass
        t.options = o
        assets.import_asset_tasks([t])
        sm = unreal.load_asset(f"{TP}/Meshes/{name}")
        if not sm:
            log("import failed", name)
            continue
        b = sm.get_bounding_box()
        log("mesh", name, "slots", [str(s.material_slot_name) for s in sm.static_materials],
            "bbox", [round(v) for v in (b.min.x, b.min.y, b.min.z, b.max.x, b.max.y, b.max.z)])
        out[name] = sm
    return info, out


def assign(sm, mis):
    for i, sl in enumerate(sm.static_materials):
        n = str(sl.material_slot_name).lower()
        mi = mis["paint"]
        if "nozzle_ge" in n:
            mi = mis["nozzle_ge"]
        elif "nozzle_ring" in n:
            mi = mis["nozzle_ring"]
        elif "texture_t" in n:
            mi = unreal.load_asset("/Game/ThirdParty/F16/Materials/MI_M_Exterior_texture_T") or mi
        sm.set_material(i, mi)
    EAL.save_loaded_asset(sm)


def sounds():
    import shutil
    tmp = os.path.join(PROJ, "Intermediate", "f16_airframe_import")
    os.makedirs(tmp, exist_ok=True)
    files = []
    for src, dst in (("engine_loop.wav", "SW_EngineLoop.wav"), ("wind_loop.wav", "SW_WindLoop.wav")):
        if os.path.exists(os.path.join(ART, src)):
            shutil.copyfile(os.path.join(ART, src), os.path.join(tmp, dst))
            files.append(os.path.join(tmp, dst))
    for k, sw in import_files(files, OWN + "/Sounds").items():
        if not sw:
            log("sound import failed", k)
            continue
        sw.set_editor_property("looping", True)
        EAL.save_loaded_asset(sw)
        log("sound", sw.get_path_name(), "looping", sw.get_editor_property("looping"))


def map_actors(info, sm, light_mi):
    eas = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
    les = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
    les.load_level(MAP)
    actors = eas.get_all_level_actors()
    root = [a for a in actors if unreal.Name("Aircraft") in a.tags]
    if not root:
        raise RuntimeError("Aircraft actor missing")
    root = root[0]
    old = [a for a in actors if unreal.Name("AirframeSurf") in a.tags or unreal.Name("AirframeLight") in a.tags]
    for a in old:
        eas.destroy_actor(a)
    R = unreal.AttachmentRule
    for name, p in info["parts"].items():
        if "hinge_ue_cm" not in p or name not in sm:
            continue
        short = name[4:]
        a = eas.spawn_actor_from_class(unreal.StaticMeshActor, unreal.Vector(*p["hinge_ue_cm"]))
        a.set_actor_label("AC_Surf_" + short)
        c = a.static_mesh_component
        c.set_mobility(unreal.ComponentMobility.MOVABLE)
        c.set_static_mesh(sm[name])
        c.set_collision_enabled(unreal.CollisionEnabled.NO_COLLISION)
        a.tags = [unreal.Name(t) for t in ("AircraftPart", "AirframeSurf", "Surf_" + short, "axis:%.6f,%.6f,%.6f" % tuple(p["axis_ue"]))]
        a.attach_to_actor(root, unreal.Name(""), R.KEEP_WORLD, R.KEEP_WORLD, R.KEEP_WORLD, False)
        a.set_actor_relative_location(unreal.Vector(*p["hinge_ue_cm"]), False, True)
        a.set_actor_hidden_in_game(True)
    sphere = unreal.load_asset("/Engine/BasicShapes/Sphere")
    L = info["lights_ue_cm"]
    for name, pos, col, d in (("NavL", L["nav_left"], (1.0, 0.02, 0.01), 7.0), ("NavR", L["nav_right"], (0.02, 1.0, 0.15), 7.0),
                              ("Tail", L["tail"], (1.0, 1.0, 1.0), 6.0),
                              ("StrobeL", [L["nav_left"][0] - 12, L["nav_left"][1] + 3, L["nav_left"][2]], (1.0, 1.0, 1.0), 6.0),
                              ("StrobeR", [L["nav_right"][0] - 12, L["nav_right"][1] - 3, L["nav_right"][2]], (1.0, 1.0, 1.0), 6.0),
                              ("Beacon", [L["fin_top"][0] + 20, 0.0, L["fin_top"][2] - 6], (1.0, 0.05, 0.0), 6.0)):
        a = eas.spawn_actor_from_class(unreal.StaticMeshActor, unreal.Vector(*pos))
        a.set_actor_label("AC_Light_" + name)
        c = a.static_mesh_component
        c.set_mobility(unreal.ComponentMobility.MOVABLE)
        c.set_static_mesh(sphere)
        c.set_material(0, light_mi)
        c.set_cast_shadow(False)
        c.set_collision_enabled(unreal.CollisionEnabled.NO_COLLISION)
        a.set_actor_scale3d(unreal.Vector(d / 100.0, d / 100.0, d / 100.0))
        a.tags = [unreal.Name(t) for t in ("AircraftPart", "AirframeLight", "Light_" + name, "rgb:%.3f,%.3f,%.3f" % col)]
        a.attach_to_actor(root, unreal.Name(""), R.KEEP_WORLD, R.KEEP_WORLD, R.KEEP_WORLD, False)
        a.set_actor_relative_location(unreal.Vector(*pos), False, True)
        a.set_actor_hidden_in_game(True)
    ok = les.save_current_level()
    log("map actors added, saved", MAP, ok)


def airframe2_master(tx2):
    """M_GyroAirframe2 (v2, 4K baked set from airframe_bake.py): BaseColor = Base x Tint (lines, rivets, two-tone, soot,
    half AO already in it); AO = ORM.r (indirect light); Roughness = ORM.g x RoughScale; Metallic = ORM.b; Normal = lerp(flat,
    Nrm, NormalStr); thin clear coat; ground bounce + sky fill emissive x AO (same reason as v1: black shaded sides)."""
    m = _new_material("M_GyroAirframe2", TP + "/Materials")     # GPL textures as defaults -> gitignored folder
    m.set_editor_property("two_sided", True)
    ST = unreal.MaterialSamplerType
    base = _tp(m, "Base", tx2["tex_af2_base"], ST.SAMPLERTYPE_COLOR, -1600, -400)
    orm = _tp(m, "ORM", tx2["tex_af2_orm"], ST.SAMPLERTYPE_MASKS, -1600, 0)
    nrm = _tp(m, "Nrm", tx2["tex_af2_n"], ST.SAMPLERTYPE_NORMAL, -1600, 400)
    col = _op(m, unreal.MaterialExpressionMultiply, base, _vp(m, "Tint", (1, 1, 1), -1450, -300), -1250, -400, "RGB", "")
    MEL.connect_material_property(col, "", MP.MP_BASE_COLOR)
    aoh = _lerp(m, _const(m, 1.0, -1300, -60), orm, _sp(m, "AOAmt", 0.5, -1300, -20), -1100, -40, "", "R", "")   # round 3: half-strength AO
    MEL.connect_material_property(aoh, "", MP.MP_AMBIENT_OCCLUSION)
    MEL.connect_material_property(_op(m, unreal.MaterialExpressionMultiply, orm, _sp(m, "RoughScale", 1.15, -1300, 120), -1100, 60, "G", ""), "", MP.MP_ROUGHNESS)
    MEL.connect_material_property(_op(m, unreal.MaterialExpressionMultiply, orm, _sp(m, "MetalScale", 1.0, -1300, 220), -1100, 200, "B", ""), "", MP.MP_METALLIC)
    MEL.connect_material_property(_sp(m, "Spec", 0.5, -1100, 300), "", MP.MP_SPECULAR)
    n = _lerp(m, _const3(m, (0, 0, 1), -1150, 480), nrm, _sp(m, "NormalStr", 1.0, -1300, 560), -550, 420, "", "RGB", "")
    MEL.connect_material_property(n, "", MP.MP_NORMAL)
    wn = _expr(m, unreal.MaterialExpressionVertexNormalWS, -1300, 900)
    nz = _expr(m, unreal.MaterialExpressionComponentMask, -1150, 900, r=False, g=False, b=True, a=False)
    MEL.connect_material_expressions(wn, "", nz, "")
    down = _expr(m, unreal.MaterialExpressionSaturate, -900, 900)
    MEL.connect_material_expressions(_op(m, unreal.MaterialExpressionMultiply, nz, _const(m, -1.0, -1150, 980), -1000, 900), "", down, "")
    amt = _op(m, unreal.MaterialExpressionAdd, _op(m, unreal.MaterialExpressionMultiply, down, _sp(m, "Bounce", 1.3, -900, 1080), -750, 1050),
              _op(m, unreal.MaterialExpressionMultiply, _op(m, unreal.MaterialExpressionSubtract, _const(m, 1.0, -1000, 1160), down, -900, 1160),
                  _sp(m, "SkyFill", 0.5, -900, 1240), -750, 1180), -650, 1100)
    em = _op(m, unreal.MaterialExpressionMultiply, _op(m, unreal.MaterialExpressionMultiply, col, amt, -500, 1000),
             _op(m, unreal.MaterialExpressionMultiply, orm, _vp(m, "BounceColor", (0.85, 0.85, 0.85), -900, 1300), -700, 1300, "R", ""), -400, 1100)
    MEL.connect_material_property(em, "", MP.MP_EMISSIVE_COLOR)
    clear_coat(m, 0.2, 0.3)
    MEL.recompile_material(m)
    EAL.save_loaded_asset(m)
    return m


def glass_ext_master():
    """M_GyroGlassExt: the canopy seen from OUTSIDE (chase / orbit / flyby / tower; airframe_live swaps it in): gold
    tinted (ITO coating), strong Fresnel reflection, see-through head on, forward-shaded translucency (sharp reflections)."""
    m = _new_material("M_GyroGlassExt", OWN)
    m.set_editor_property("blend_mode", unreal.BlendMode.BLEND_TRANSLUCENT)
    m.set_editor_property("two_sided", True)
    try:
        tlm = getattr(unreal.TranslucencyLightingMode, "TLM_SURFACE_FORWARD_SHADING", None) or unreal.TranslucencyLightingMode.TLM_SURFACE_PER_PIXEL_LIGHTING
        m.set_editor_property("translucency_lighting_mode", tlm)     # forward shading: sharp sky / sun reflections
    except Exception as e:
        log("glass lighting mode", repr(e))
    # round 4: clear (dark base so the glass is not milky), faint gold, Fresnel reflection toward the edges
    # round 3: mostly clear (the pilot shows), faint gold tint, sharp reflections
    MEL.connect_material_property(_vp(m, "Tint", (0.05, 0.045, 0.02), -600, -200), "", MP.MP_BASE_COLOR)
    MEL.connect_material_property(_sp(m, "Metal", 0.0, -600, -100), "", MP.MP_METALLIC)
    MEL.connect_material_property(_sp(m, "Rough", 0.05, -600, 0), "", MP.MP_ROUGHNESS)
    MEL.connect_material_property(_sp(m, "Spec", 0.9, -600, 80), "", MP.MP_SPECULAR)
    fr = _expr(m, unreal.MaterialExpressionFresnel, -800, 200, exponent=4.0)
    op = _lerp(m, _sp(m, "OpacityFace", 0.12, -800, 300), _sp(m, "OpacityEdge", 0.7, -800, 380), fr, -500, 250)
    MEL.connect_material_property(op, "", MP.MP_OPACITY)
    MEL.recompile_material(m)
    EAL.save_loaded_asset(m)
    return m


def v2(tx, m1):
    names = ("tex_af2_base", "tex_af2_n", "tex_af2_orm", "tex_af2_noz_base", "tex_af2_noz_n", "tex_af2_noz_orm")
    if not all(os.path.exists(os.path.join(SRC, n + ".png")) for n in names):
        log("v2 textures missing (run airframe_bake.py) - v2 skipped")
        return
    tx2 = import_files([os.path.join(SRC, n + ".png") for n in names], TP + "/Textures")
    TC = unreal.TextureCompressionSettings
    tx2["tex_af2_n"].set_editor_property("compression_settings", TC.TC_NORMALMAP)
    tx2["tex_af2_n"].set_editor_property("srgb", False)
    for o in ("tex_af2_orm", "tex_af2_noz_orm"):
        tx2[o].set_editor_property("compression_settings", TC.TC_MASKS)
        tx2[o].set_editor_property("srgb", False)
    tx2["tex_af2_noz_n"].set_editor_property("compression_settings", TC.TC_NORMALMAP)
    tx2["tex_af2_noz_n"].set_editor_property("srgb", False)
    for t in tx2.values():
        t.set_editor_property("max_texture_size", 4096)
        EAL.save_loaded_asset(t)
    m2 = airframe2_master(tx2)
    glass_ext_master()
    folder = TP + "/Materials"
    mis = dict(paint=instance("MI_AF2_Paint", m2, folder, textures=dict(Base=tx2["tex_af2_base"], ORM=tx2["tex_af2_orm"], Nrm=tx2["tex_af2_n"])),
               # nozzle: heat-darkened metal (blued / bronze toward the exit), petals from the FG nozzle model
               # round 3: burnished titanium petals - metal 1, rough 0.35, warm grey-gold
               # round 4: own nozzle set (airframe_bake.nozzle_bake): titanium -> straw -> blued toward the exit, dark liner,
               # petal ribs in the normal map; metal / rough from its ORM
               nozzle_ge=instance("MI_AF2_NozzleGE", m2, folder, scalars=dict(RoughScale=1.0, SkyFill=0.25, Bounce=0.5),
                                  textures=dict(Base=tx2["tex_af2_noz_base"], ORM=tx2["tex_af2_noz_orm"], Nrm=tx2["tex_af2_noz_n"])),
               nozzle_ring=instance("MI_AF2_NozzleRing", m1, folder, scalars=dict(Detail=0.0, Metal=0.85, Rough=0.5, ClearCoat=0.0),
                                    colors=dict(Tint=(0.16, 0.15, 0.15)), textures=dict(Paint=tx["tex_nozzle_ring"])))
    _, sm2 = meshes("_v2")
    for s in sm2.values():
        assign(s, mis)
    log("v2 meshes", sorted(sm2))


def main():
    tx = textures()
    m = airframe_master(tx)
    lm = light_master()
    folder = TP + "/Materials"
    mis = dict(paint=instance("MI_AF_Paint", m, folder, scalars=dict(LineDark=0.25, NormalStr=0.6, Rough=0.5, RoughVar=0.08, GrimeAmt=0.18), textures=dict(Paint=tx["tex_f16_paint"], Mask=tx["tex_f16_m"], Nrm=tx["tex_f16_n"])),
               nozzle_ge=instance("MI_AF_NozzleGE", m, folder, scalars=dict(Detail=0.0, Metal=0.85, Rough=0.38, ClearCoat=0.0), colors=dict(Tint=(0.75, 0.72, 0.68)),
                                  textures=dict(Paint=tx["tex_nozzle_GE"])),
               nozzle_ring=instance("MI_AF_NozzleRing", m, folder, scalars=dict(Detail=0.0, Metal=0.8, Rough=0.45, ClearCoat=0.0), colors=dict(Tint=(0.3, 0.3, 0.3)),
                                    textures=dict(Paint=tx["tex_nozzle_ring"])))
    light_mi = instance("MI_AF_Light", lm, OWN)
    info, sm = meshes()
    for s in sm.values():
        assign(s, mis)
    sounds()
    v2(tx, m)
    for old in (OWN + "/M_GyroAirframe", OWN + "/M_GyroAirframe2"):     # moved to the gitignored folder (GPL defaults)
        if EAL.does_asset_exist(old):
            log("delete old", old, EAL.delete_asset(old))
    if os.environ.get("GYROSIM_AF_MAP", "1") != "0":
        map_actors(info, sm, light_mi)
    log("done")


main()
