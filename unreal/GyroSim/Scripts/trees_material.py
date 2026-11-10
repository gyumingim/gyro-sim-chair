"""Builds /Game/Trees/M_GyroTree: the material of the 3D trees tileset (CesiumTrees, trees_look.apply sets it at Play;
GYROSIM_TREES_ART=0 keeps Cesium's stock material). Leaf clumps / gaps / per-clump lighting from
Scripts/trees_foliage.hlsl in one Custom node on the tiles' vertex colour - no textures. Art pass 11-10 (docs/art-busan.md).

Run in an editor that does not have the asset open (new asset, nothing else is touched or saved):
    UnrealEditor-Cmd.exe GyroSim.uproject -run=pythonscript -script=<this file> -unattended -nosplash -nullrhi
Re-running rebuilds the graph in place. Builds M_GyroTree (v1) and the v2 pair M_GyroTree2 / M_GyroTree2W
(GYROSIM_TREE_MAT=1 or 2 = only that one).
"""
import os
import unreal

PATH, NAME = "/Game/Trees", "M_GyroTree"
HLSL = os.path.join(os.path.dirname(os.path.abspath(__file__)), "trees_foliage.hlsl")
PARAMS = dict(Amt=1.0, ClumpM=1.8, GapDark=0.6, Bump=1.0)    # 11-10 sweep: 0.9 m clumps faded out beyond ~150 m
MEL = unreal.MaterialEditingLibrary
log = lambda *a: unreal.log("[tree_mat] " + " ".join(str(x) for x in a))


def build():
    full = PATH + "/" + NAME
    if unreal.EditorAssetLibrary.does_asset_exist(full):
        m = unreal.load_asset(full)
        MEL.delete_all_material_expressions(m)
    else:
        m = unreal.AssetToolsHelpers.get_asset_tools().create_asset(NAME, PATH, unreal.Material, unreal.MaterialFactoryNew())
    m.set_editor_property("tangent_space_normal", False)
    m.set_editor_property("two_sided", False)
    for flag in ("used_with_instanced_static_meshes", "used_with_static_lighting"):
        try:
            m.set_editor_property(flag, flag == "used_with_instanced_static_meshes")
        except Exception as e:
            log("flag", flag, repr(e))
    X = lambda cls, x, y: MEL.create_material_expression(m, cls, x, y)
    vc = X(unreal.MaterialExpressionVertexColor, -1100, 0)
    wp = X(unreal.MaterialExpressionWorldPosition, -1100, 150)
    nrm = X(unreal.MaterialExpressionVertexNormalWS, -1100, 300)
    srcs = [("VC", vc), ("P", wp), ("N", nrm)]
    y = 450
    for k, v in PARAMS.items():
        e = X(unreal.MaterialExpressionScalarParameter, -1100, y)
        e.set_editor_property("parameter_name", k)
        e.set_editor_property("default_value", float(v))
        srcs.append((k, e))
        y += 100
    cu = X(unreal.MaterialExpressionCustom, -500, 0)
    cu.set_editor_property("code", open(HLSL, encoding="utf-8").read())
    cu.set_editor_property("description", "GyroTree")
    cu.set_editor_property("output_type", unreal.CustomMaterialOutputType.CMOT_FLOAT3)
    ins = []
    for n, _ in srcs:
        ci = unreal.CustomInput()
        ci.set_editor_property("input_name", n)
        ins.append(ci)
    cu.set_editor_property("inputs", ins)
    outs = []
    for n, t in (("Rough", unreal.CustomMaterialOutputType.CMOT_FLOAT1), ("NormalWS", unreal.CustomMaterialOutputType.CMOT_FLOAT3)):
        co = unreal.CustomOutput()
        co.set_editor_property("output_name", n)
        co.set_editor_property("output_type", t)
        outs.append(co)
    cu.set_editor_property("additional_outputs", outs)
    try:
        cu.post_edit_change()
    except Exception:
        pass
    for n, src in srcs:
        if not MEL.connect_material_expressions(src, "", cu, n):
            log("connect failed", n)
    MEL.connect_material_property(cu, "", unreal.MaterialProperty.MP_BASE_COLOR)
    for pin, prop in (("Rough", unreal.MaterialProperty.MP_ROUGHNESS), ("NormalWS", unreal.MaterialProperty.MP_NORMAL)):
        if not MEL.connect_material_property(cu, pin, prop):
            log("property connect failed", pin)
    sp = X(unreal.MaterialExpressionConstant, -500, 400)
    sp.set_editor_property("r", 0.3)
    MEL.connect_material_property(sp, "", unreal.MaterialProperty.MP_SPECULAR)
    MEL.recompile_material(m)
    unreal.EditorAssetLibrary.save_asset(full, only_if_is_dirty=False)
    log("built", full)
    return m


# ---- v2 (11-10 second pass, sim/veg_v2.py tiles): /Game/Trees/M_GyroTree2 (+ M_GyroTree2W with wind sway) -------------
NAME2 = "M_GyroTree2"
HLSL2 = os.path.join(os.path.dirname(os.path.abspath(__file__)), "trees_foliage2.hlsl")
PARAMS2 = dict(VarAmt=1.0, Season=0.0, AoBase=0.7, AoAmb=0.85, ClumpM=0.7, GapDark=0.5, Bump=0.8, SssAmt=0.4, Gain=0.9, RimAmt=0.35)
WIND2 = dict(WindAmp=18.0, WindHz=0.35)                      # cm at the tree top, Hz (M_GyroTree2W only)
WIND_HLSL = """// gentle sway (vertex): crown top moves WindAmp cm, quadratic with the height above the instance origin, own phase per tree
float3 d = P - O;
float hf = saturate(d.z / 1500.0);
float ph = PIR * 6.2832 + dot(O.xy, float2(0.0007, 0.0011));
float s = sin(T * 6.2832 * WindHz + ph) + 0.35 * sin(T * 6.2832 * WindHz * 2.3 + ph * 1.7);
return float3(0.8, 0.6, 0.0) * (WindAmp * hf * hf * s);
"""


def build2(name=NAME2, wind=False):
    """two-sided-foliage material on the v2 tiles' vertex colour (tint + packed kind / ao), PerInstanceRandom variation."""
    full = PATH + "/" + name
    if unreal.EditorAssetLibrary.does_asset_exist(full):
        m = unreal.load_asset(full)
        MEL.delete_all_material_expressions(m)
    else:
        m = unreal.AssetToolsHelpers.get_asset_tools().create_asset(name, PATH, unreal.Material, unreal.MaterialFactoryNew())
    m.set_editor_property("tangent_space_normal", False)
    m.set_editor_property("two_sided", False)
    m.set_editor_property("shading_model", unreal.MaterialShadingModel.MSM_TWO_SIDED_FOLIAGE)
    for flag in ("used_with_instanced_static_meshes", "used_with_static_lighting"):
        try:
            m.set_editor_property(flag, flag == "used_with_instanced_static_meshes")
        except Exception as e:
            log("flag", flag, repr(e))
    X = lambda cls, x, y: MEL.create_material_expression(m, cls, x, y)
    vc = X(unreal.MaterialExpressionVertexColor, -1300, 0)
    wp = X(unreal.MaterialExpressionWorldPosition, -1300, 150)
    nrm = X(unreal.MaterialExpressionVertexNormalWS, -1300, 300)
    pir = X(unreal.MaterialExpressionPerInstanceRandom, -1300, 400)
    cam = X(unreal.MaterialExpressionCameraVectorWS, -1300, 450)
    srcs = [("VC", vc, ""), ("VA", vc, "A"), ("P", wp, ""), ("N", nrm, ""), ("PIR", pir, ""), ("V", cam, "")]
    y = 500
    for k, v in PARAMS2.items():
        e = X(unreal.MaterialExpressionScalarParameter, -1300, y)
        e.set_editor_property("parameter_name", k)
        e.set_editor_property("default_value", float(v))
        srcs.append((k, e, ""))
        y += 90
    cu = X(unreal.MaterialExpressionCustom, -600, 0)
    cu.set_editor_property("code", open(HLSL2, encoding="utf-8").read())
    cu.set_editor_property("description", "GyroTree2")
    cu.set_editor_property("output_type", unreal.CustomMaterialOutputType.CMOT_FLOAT3)
    ins = []
    for n, _, _ in srcs:
        ci = unreal.CustomInput()
        ci.set_editor_property("input_name", n)
        ins.append(ci)
    cu.set_editor_property("inputs", ins)
    outs = []
    F1, F3 = unreal.CustomMaterialOutputType.CMOT_FLOAT1, unreal.CustomMaterialOutputType.CMOT_FLOAT3
    for n, t in (("Rough", F1), ("NormalWS", F3), ("SSS", F3), ("AOut", F1)):
        co = unreal.CustomOutput()
        co.set_editor_property("output_name", n)
        co.set_editor_property("output_type", t)
        outs.append(co)
    cu.set_editor_property("additional_outputs", outs)
    try:
        cu.post_edit_change()
    except Exception:
        pass
    for n, src, pin in srcs:
        if not MEL.connect_material_expressions(src, pin, cu, n):
            log("connect failed", n)
    MP = unreal.MaterialProperty
    MEL.connect_material_property(cu, "", MP.MP_BASE_COLOR)
    for pin, prop in (("Rough", MP.MP_ROUGHNESS), ("NormalWS", MP.MP_NORMAL), ("SSS", MP.MP_SUBSURFACE_COLOR), ("AOut", MP.MP_AMBIENT_OCCLUSION)):
        if not MEL.connect_material_property(cu, pin, prop):
            log("property connect failed", pin)
    sp = X(unreal.MaterialExpressionConstant, -600, 500)
    sp.set_editor_property("r", 0.3)
    MEL.connect_material_property(sp, "", MP.MP_SPECULAR)
    if wind:
        wpa = X(unreal.MaterialExpressionWorldPosition, -1300, 1400)
        obj = X(unreal.MaterialExpressionObjectPositionWS, -1300, 1500)
        tim = X(unreal.MaterialExpressionTime, -1300, 1600)
        pir2 = X(unreal.MaterialExpressionPerInstanceRandom, -1300, 1700)
        wsrc = [("P", wpa), ("O", obj), ("T", tim), ("PIR", pir2)]
        y = 1800
        for k, v in WIND2.items():
            e = X(unreal.MaterialExpressionScalarParameter, -1300, y)
            e.set_editor_property("parameter_name", k)
            e.set_editor_property("default_value", float(v))
            wsrc.append((k, e)); y += 90
        wc = X(unreal.MaterialExpressionCustom, -600, 1400)
        wc.set_editor_property("code", WIND_HLSL)
        wc.set_editor_property("description", "GyroTreeWind")
        wc.set_editor_property("output_type", F3)
        wi = []
        for n, _ in wsrc:
            ci = unreal.CustomInput(); ci.set_editor_property("input_name", n); wi.append(ci)
        wc.set_editor_property("inputs", wi)
        for n, src in wsrc:
            if not MEL.connect_material_expressions(src, "", wc, n):
                log("wind connect failed", n)
        MEL.connect_material_property(wc, "", MP.MP_WORLD_POSITION_OFFSET)
    MEL.recompile_material(m)
    unreal.EditorAssetLibrary.save_asset(full, only_if_is_dirty=False)
    log("built", full, "wind" if wind else "")
    return m


if __name__ in ("__main__", "gyrosim_tree_mat"):
    if os.environ.get("GYROSIM_TREE_MAT", "") in ("", "1", "all"):
        build()
    if os.environ.get("GYROSIM_TREE_MAT", "") in ("", "2", "all"):
        build2()
        build2(NAME2 + "W", wind=True)
