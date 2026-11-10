"""Builds /Game/Trees/M_GyroTree: the material of the 3D trees tileset (CesiumTrees, trees_look.apply sets it at Play;
GYROSIM_TREES_ART=0 keeps Cesium's stock material). Leaf clumps / gaps / per-clump lighting from
Scripts/trees_foliage.hlsl in one Custom node on the tiles' vertex colour - no textures. Art pass 11-10 (docs/art-busan.md).

Run in an editor that does not have the asset open (new asset, nothing else is touched or saved):
    UnrealEditor-Cmd.exe GyroSim.uproject -run=pythonscript -script=<this file> -unattended -nosplash -nullrhi
Re-running rebuilds the graph in place.
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


if __name__ in ("__main__", "gyrosim_tree_mat"):
    build()
