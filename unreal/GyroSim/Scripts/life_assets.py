r"""Builds the assets of the Busan 'life' layer (moving cars / ships, Content/Python/life_look.py):
  /Game/Life/Meshes/SM_Life*   imported from C:/GyroSimTiles/life/meshes/*.glb (sim/life_meshes.py, original low-poly models)
  /Game/Life/M_GyroLifeVehicle, M_GyroLifeShip, M_GyroLifeWake   motion on the GPU (World Position Offset from the
      instance custom data, Scripts/life_motion.hlsl + life_vehicle.hlsl / life_ship.hlsl / life_wake.hlsl)

Headless (new assets only, the map is not touched):
  UnrealEditor-Cmd.exe GyroSim.uproject -run=pythonscript -script=<this file> -unattended -nosplash -nullrhi
GYROSIM_LIFE_ASSETS = meshes | materials (default both). Re-running rebuilds in place.
"""
import json, os
import unreal

HERE = os.path.dirname(os.path.abspath(__file__))
MESH_DIR = os.environ.get("GYROSIM_LIFE", r"C:/GyroSimTiles/life").replace("\\", "/") + "/meshes"
PATH, MPATH = "/Game/Life", "/Game/Life/Meshes"
MEL = unreal.MaterialEditingLibrary
EAL = unreal.EditorAssetLibrary
log = lambda *a: unreal.log("[life_assets] " + " ".join(str(x) for x in a))
# bounds extension (cm, mesh local): the instance moves up to one piece length along +X (traffic PIECE 150 m, ship
# pieces <= 1.5 km; the wake mesh is scaled by length / 100 m >= 0.13, so its local extension is / 0.13)
BOUNDS = dict(SM_LifeVehicle=((-700, -300, -100), (15700, 300, 450)),
              SM_LifeWake=((-1000, -1000, -100), (1160000, 1000, 100)))
SHIP_BOUNDS = ((-500, -500, -200), (151000, 500, 500))
FAR = dict(vehicle=150000.0, ship=2500000.0, wake=800000.0)          # shrink-out distance cm (life_look sets the cull distance to it)


def import_meshes():
    files = sorted(f for f in os.listdir(MESH_DIR) if f.endswith(".glb"))
    info = json.load(open(MESH_DIR + "/meshes.json", encoding="utf-8"))["meshes"]
    tasks = []
    for f in files:
        t = unreal.AssetImportTask()
        t.filename = MESH_DIR + "/" + f
        t.destination_path = MPATH
        t.destination_name = os.path.splitext(f)[0]
        t.automated = True
        t.replace_existing = True
        t.save = False
        tasks.append(t)
    unreal.AssetToolsHelpers.get_asset_tools().import_asset_tasks(tasks)
    out = {}
    for f in files:
        name = os.path.splitext(f)[0]
        sm = None
        for p in EAL.list_assets(MPATH, recursive=True, include_folder=False):
            a = unreal.load_asset(p.split(".")[0])
            if isinstance(a, unreal.StaticMesh) and a.get_name().endswith(name):
                sm = a
                if a.get_name() == name:
                    break
        if sm is None:
            log("IMPORT FAILED", f)
            continue
        try:
            ns = sm.get_editor_property("nanite_settings")
            ns.set_editor_property("enabled", False)
            sm.set_editor_property("nanite_settings", ns)
        except Exception as e:
            log("nanite", name, repr(e))
        lo, hi = BOUNDS.get(name, SHIP_BOUNDS)
        sm.set_editor_property("negative_bounds_extension", unreal.Vector(*[-v for v in lo]))
        sm.set_editor_property("positive_bounds_extension", unreal.Vector(*hi))
        b = sm.get_bounding_box()
        want = info.get(name, {})
        log("mesh", sm.get_path_name(), "bounds cm", [round(v) for v in (b.min.x, b.min.y, b.min.z)], [round(v) for v in (b.max.x, b.max.y, b.max.z)],
            "drawn m", want.get("min"), want.get("max"), "verts", want.get("verts"))
        EAL.save_loaded_asset(sm)
        out[name] = sm
    return out


def _x(m, cls, x, y):
    return MEL.create_material_expression(m, cls, x, y)


def _custom(m, code, inputs, x, y, out_type, extra=()):
    cu = _x(m, unreal.MaterialExpressionCustom, x, y)
    cu.set_editor_property("code", code)
    cu.set_editor_property("description", "GyroLife")
    cu.set_editor_property("output_type", out_type)
    ins = []
    for n, _, _ in inputs:
        ci = unreal.CustomInput()
        ci.set_editor_property("input_name", n)
        ins.append(ci)
    cu.set_editor_property("inputs", ins)
    outs = []
    for n, t in extra:
        co = unreal.CustomOutput()
        co.set_editor_property("output_name", n)
        co.set_editor_property("output_type", t)
        outs.append(co)
    cu.set_editor_property("additional_outputs", outs)
    try:
        cu.post_edit_change()
    except Exception:
        pass
    for n, src, pin in inputs:
        if not MEL.connect_material_expressions(src, pin, cu, n):
            log("connect failed", n)
    return cu


def _motion_inputs(m, far):
    """custom-node inputs of life_motion.hlsl: [(name, expression, pin)]"""
    srcs = []
    for i, n in enumerate(("L", "C", "J", "V", "D", "SEED", "FL", "K")):
        e = _x(m, unreal.MaterialExpressionPerInstanceCustomData, -1600, -400 + i * 70)
        e.set_editor_property("data_index", i)
        srcs.append((n, e, ""))
    srcs.append(("T", _x(m, unreal.MaterialExpressionTime, -1600, 200), ""))
    tf = _x(m, unreal.MaterialExpressionScalarParameter, -1600, 270)
    tf.set_editor_property("parameter_name", "TFix")
    tf.set_editor_property("default_value", -1.0)
    srcs.append(("TFix", tf, ""))
    fr = _x(m, unreal.MaterialExpressionScalarParameter, -1600, 340)
    fr.set_editor_property("parameter_name", "Far")
    fr.set_editor_property("default_value", far)
    srcs.append(("Far", fr, ""))
    lp = None
    if hasattr(unreal, "MaterialExpressionLocalPosition"):
        lp = _x(m, unreal.MaterialExpressionLocalPosition, -1600, 410)
    else:
        wp0 = _x(m, unreal.MaterialExpressionWorldPosition, -1900, 410)
        lp = _x(m, unreal.MaterialExpressionTransformPosition, -1600, 410)
        lp.set_editor_property("transform_source_type", unreal.MaterialPositionTransformSource.TRANSFORMPOSSOURCE_WORLD)
        lp.set_editor_property("transform_type", unreal.MaterialPositionTransformSource.TRANSFORMPOSSOURCE_LOCAL)
        MEL.connect_material_expressions(wp0, "", lp, "")
    srcs.append(("LP", lp, ""))
    wpr = _x(m, unreal.MaterialExpressionWorldPosition, -1600, 480)
    for nm in ("WPT_CAMERA_RELATIVE_EXCLUDE_ALL_SHADER_OFFSETS", "WPT_CAMERA_RELATIVE"):
        if hasattr(unreal.WorldPositionIncludedOffsets, nm):
            wpr.set_editor_property("world_position_shader_offset", getattr(unreal.WorldPositionIncludedOffsets, nm))
            break
    srcs.append(("WPR", wpr, ""))
    one = _x(m, unreal.MaterialExpressionConstant3Vector, -1900, 550)
    one.set_editor_property("constant", unreal.LinearColor(1, 0, 0, 0))
    ax = _local_to_world(m, one, -1600, 550)
    srcs.append(("AX", ax, ""))
    return srcs


def _local_to_world(m, src, x, y):
    tr = _x(m, unreal.MaterialExpressionTransform, x, y)
    tr.set_editor_property("transform_source_type", unreal.MaterialVectorCoordTransformSource.TRANSFORMSOURCE_LOCAL)
    tr.set_editor_property("transform_type", unreal.MaterialVectorCoordTransform.TRANSFORM_WORLD)
    MEL.connect_material_expressions(src, "", tr, "")
    return tr


def _new(name):
    full = PATH + "/" + name
    if EAL.does_asset_exist(full):
        m = unreal.load_asset(full)
        MEL.delete_all_material_expressions(m)
    else:
        m = unreal.AssetToolsHelpers.get_asset_tools().create_asset(name, PATH, unreal.Material, unreal.MaterialFactoryNew())
    m.set_editor_property("used_with_instanced_static_meshes", True)
    try:
        m.set_editor_property("used_with_static_lighting", False)
    except Exception:
        pass
    return m, full


def _code(body_file, head_extra=""):
    head = open(os.path.join(HERE, "life_motion.hlsl"), encoding="utf-8-sig").read()
    body = open(os.path.join(HERE, body_file), encoding="utf-8-sig").read() if body_file.endswith(".hlsl") else body_file
    return "float SC = length(AX);\n" + head + head_extra + "\n" + body


def build_opaque(name, body_file, far, extra_inputs=(), px_file=None):
    m, full = _new(name)
    F1, F3, F4 = (unreal.CustomMaterialOutputType.CMOT_FLOAT1, unreal.CustomMaterialOutputType.CMOT_FLOAT3,
                  unreal.CustomMaterialOutputType.CMOT_FLOAT4)
    srcs = _motion_inputs(m, far)
    uv = _x(m, unreal.MaterialExpressionTextureCoordinate, -1600, 620)
    srcs.append(("UV", uv, ""))
    for n, cls, prop, val in extra_inputs:
        e = _x(m, cls, -1600, 700 + 70 * len(srcs))
        if prop:
            e.set_editor_property(prop, val)
        srcs.append((n, e, ""))
    cu = _custom(m, _code(body_file), srcs, -900, 0, F3, extra=(("CR", F4),))
    wpo = _local_to_world(m, cu, -500, 300)
    MEL.connect_material_property(wpo, "", unreal.MaterialProperty.MP_WORLD_POSITION_OFFSET)
    vi = _x(m, unreal.MaterialExpressionVertexInterpolator, -500, 0)
    MEL.connect_material_expressions(cu, "CR", vi, "")
    src = vi
    if px_file:                                                  # pixel stage (container boxes)
        lp = _x(m, unreal.MaterialExpressionLocalPosition, -700, 500) if hasattr(unreal, "MaterialExpressionLocalPosition") else None
        uv2 = _x(m, unreal.MaterialExpressionTextureCoordinate, -700, 600)
        ins = [("CR", vi, ""), ("UV", uv2, "")] + ([("LP", lp, "")] if lp else [])
        src = _custom(m, open(os.path.join(HERE, px_file), encoding="utf-8-sig").read(), ins, -450, 0, F4)
    rgb = _x(m, unreal.MaterialExpressionComponentMask, -300, 0)
    for k, v in (("r", True), ("g", True), ("b", True), ("a", False)):
        rgb.set_editor_property(k, v)
    al = _x(m, unreal.MaterialExpressionComponentMask, -300, 120)
    for k, v in (("r", False), ("g", False), ("b", False), ("a", True)):
        al.set_editor_property(k, v)
    MEL.connect_material_expressions(src, "", rgb, "")
    MEL.connect_material_expressions(src, "", al, "")
    MEL.connect_material_property(rgb, "", unreal.MaterialProperty.MP_BASE_COLOR)
    MEL.connect_material_property(al, "", unreal.MaterialProperty.MP_ROUGHNESS)
    MEL.recompile_material(m)
    EAL.save_asset(full, only_if_is_dirty=False)
    log("built", full)


WAKE_VS = """CR = float4(0, 0, 0, 0);
return float3(x / max(SC, 0.01), 0, 30.0 / max(SC, 0.01)) + (LP * s - LP);
"""


def build_wake():
    m, full = _new("M_GyroLifeWake")
    m.set_editor_property("blend_mode", unreal.BlendMode.BLEND_TRANSLUCENT)
    try:
        m.set_editor_property("translucency_lighting_mode", unreal.TranslucencyLightingMode.TLM_VOLUMETRIC_NON_DIRECTIONAL)
    except Exception as e:
        log("translucency mode", repr(e))
    F1, F3, F4 = (unreal.CustomMaterialOutputType.CMOT_FLOAT1, unreal.CustomMaterialOutputType.CMOT_FLOAT3,
                  unreal.CustomMaterialOutputType.CMOT_FLOAT4)
    srcs = _motion_inputs(m, FAR["wake"])
    cu = _custom(m, _code(WAKE_VS), srcs, -900, 0, F3, extra=(("CR", F4),))
    wpo = _local_to_world(m, cu, -500, 300)
    MEL.connect_material_property(wpo, "", unreal.MaterialProperty.MP_WORLD_POSITION_OFFSET)
    # pixel: foam opacity
    vc = _x(m, unreal.MaterialExpressionVertexColor, -1600, 900)
    wp = _x(m, unreal.MaterialExpressionWorldPosition, -1600, 970)
    spd = _x(m, unreal.MaterialExpressionPerInstanceCustomData, -1600, 1040)
    spd.set_editor_property("data_index", 3)
    tm = _x(m, unreal.MaterialExpressionTime, -1600, 1110)
    tf = _x(m, unreal.MaterialExpressionScalarParameter, -1600, 1180)
    tf.set_editor_property("parameter_name", "TFix")
    tf.set_editor_property("default_value", -1.0)
    amt = _x(m, unreal.MaterialExpressionScalarParameter, -1600, 1250)
    amt.set_editor_property("parameter_name", "Amt")
    amt.set_editor_property("default_value", 1.0)
    ps = [("VC", vc, ""), ("P", wp, ""), ("Spd", spd, ""), ("T", tm, ""), ("TFix", tf, ""), ("Amt", amt, "")]
    op = _custom(m, open(os.path.join(HERE, "life_wake.hlsl"), encoding="utf-8-sig").read(), ps, -900, 900, F1)
    MEL.connect_material_property(op, "", unreal.MaterialProperty.MP_OPACITY)
    col = _x(m, unreal.MaterialExpressionConstant3Vector, -500, 700)
    col.set_editor_property("constant", unreal.LinearColor(0.72, 0.78, 0.80, 1))
    MEL.connect_material_property(col, "", unreal.MaterialProperty.MP_BASE_COLOR)
    r = _x(m, unreal.MaterialExpressionConstant, -500, 800)
    r.set_editor_property("r", 0.7)
    MEL.connect_material_property(r, "", unreal.MaterialProperty.MP_ROUGHNESS)
    MEL.recompile_material(m)
    EAL.save_asset(full, only_if_is_dirty=False)
    log("built", full)


def build_materials():
    build_opaque("M_GyroLifeVehicle", "life_vehicle.hlsl", FAR["vehicle"])
    kind = (("Kind", unreal.MaterialExpressionScalarParameter, "parameter_name", "Kind"),
            ("VC", unreal.MaterialExpressionVertexColor, None, None))
    build_opaque("M_GyroLifeShip", "life_ship.hlsl", FAR["ship"], kind, px_file="life_ship_px.hlsl")
    build_wake()


if __name__ in ("__main__", "gyrosim_life_assets"):
    what = os.environ.get("GYROSIM_LIFE_ASSETS", "meshes,materials")
    if "meshes" in what:
        import_meshes()
    if "materials" in what:
        build_materials()
    log("done")
