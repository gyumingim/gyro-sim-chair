"""Builds /Game/Buildings/M_GyroBuilding: the material of the local 3D buildings tileset (CesiumBuildings, sim_client
_local_buildings -> buildings_look.apply). Procedural facades (window rows per floor, per use / height style, interior
mapping, reflective glass) from Scripts/buildings_facade.hlsl in one Custom node - no textures besides the tile's own
baseColorTexture (roof photo). Cesium sets the glTF values as global parameters on its dynamic instances
(CesiumGltfComponent.cpp SetGltfParameterValues: baseColorTexture, baseColorFactor, roughnessFactor ...), so a plain
material with those parameter names works.

Run in an editor that does not have the asset open (new asset, nothing else is touched or saved):
    UnrealEditor-Cmd.exe GyroSim.uproject -run=pythonscript -script=<this file> -unattended -nosplash -nullrhi
or exec() it in the editor. Re-running rebuilds the graph in place.
"""
import os
import unreal

HERE = os.path.dirname(os.path.abspath(__file__))
PATH, NAME = os.environ.get("GYROSIM_BLDG_MAT_PATH", "/Game/Buildings"), os.environ.get("GYROSIM_BLDG_MAT_NAME", "M_GyroBuilding")
HLSL = os.environ.get("GYROSIM_BLDG_HLSL") or os.path.join(HERE, "buildings_facade.hlsl")   # A/B: older copies
# v3 (11-10): the same graph is also built as M_GyroBuilding_v2 from buildings_facade_v2.hlsl (the look before v3, used by
# buildings_look when GYROSIM_BLDG_V3=0). GYROSIM_BLDG_MAT_V2=0 skips it.
V2 = (NAME + "_v2", os.path.join(HERE, "buildings_facade_v2.hlsl"))
MEL = unreal.MaterialEditingLibrary
log = lambda *a: unreal.log("[bldg_mat] " + " ".join(str(x) for x in a))


def build(NAME=NAME, HLSL=HLSL):
    full = PATH + "/" + NAME
    at = unreal.AssetToolsHelpers.get_asset_tools()
    if unreal.EditorAssetLibrary.does_asset_exist(full):
        m = unreal.load_asset(full)
        MEL.delete_all_material_expressions(m)
    else:
        m = at.create_asset(NAME, PATH, unreal.Material, unreal.MaterialFactoryNew())
    m.set_editor_property("tangent_space_normal", False)       # the Custom node returns a world-space normal
    m.set_editor_property("two_sided", False)
    for flag in ("used_with_static_lighting",):
        try:
            m.set_editor_property(flag, False)
        except Exception:
            pass
    X = lambda cls, x, y: MEL.create_material_expression(m, cls, x, y)

    tc = X(unreal.MaterialExpressionTextureCoordinate, -1400, 0)
    # v3: the glTF texture as a texture OBJECT parameter (Cesium sets it by name like the sample parameter before), sampled
    # once here (Tex) and handed to the Custom node too (TexObj: roof sharpening taps, atlas size)
    tobj = X(unreal.MaterialExpressionTextureObjectParameter, -1400, -300)
    tobj.set_editor_property("parameter_name", "baseColorTexture")
    tobj.set_editor_property("texture", unreal.load_asset("/Engine/EngineResources/WhiteSquareTexture"))
    tobj.set_editor_property("sampler_type", unreal.MaterialSamplerType.SAMPLERTYPE_COLOR)
    tex = X(unreal.MaterialExpressionTextureSample, -1100, -300)
    tex.set_editor_property("sampler_type", unreal.MaterialSamplerType.SAMPLERTYPE_COLOR)
    if not MEL.connect_material_expressions(tobj, "", tex, "Tex"):
        log("connect failed: texture object -> sample")
    MEL.connect_material_expressions(tc, "", tex, "UVs")
    bcf = X(unreal.MaterialExpressionVectorParameter, -1100, -500)
    bcf.set_editor_property("parameter_name", "baseColorFactor")
    bcf.set_editor_property("default_value", unreal.LinearColor(1, 1, 1, 1))
    mul = X(unreal.MaterialExpressionMultiply, -800, -400)
    MEL.connect_material_expressions(tex, "RGB", mul, "A")
    MEL.connect_material_expressions(bcf, "", mul, "B")
    rf = X(unreal.MaterialExpressionScalarParameter, -1100, 100)
    rf.set_editor_property("parameter_name", "roughnessFactor")
    rf.set_editor_property("default_value", 0.8)
    vc = X(unreal.MaterialExpressionVertexColor, -1100, 250)
    nrm = X(unreal.MaterialExpressionVertexNormalWS, -1100, 400)
    cam = X(unreal.MaterialExpressionCameraVectorWS, -1100, 500)
    wp = X(unreal.MaterialExpressionWorldPosition, -1100, 600)
    try:
        wp.set_editor_property("world_position_shader_offset", unreal.WorldPositionIncludedOffsets.WPT_CAMERA_RELATIVE)
    except Exception as e:
        log("world position offset option", repr(e))

    sun = X(unreal.MaterialExpressionSkyAtmosphereLightDirection, -1100, 700)     # direction to the sun (light index 0)
    art = X(unreal.MaterialExpressionScalarParameter, -1100, 800)                   # art pass 11-10 on / off (buildings_look)
    art.set_editor_property("parameter_name", "ArtFix")
    art.set_editor_property("default_value", 1.0)
    cu = X(unreal.MaterialExpressionCustom, -500, 0)
    cu.set_editor_property("code", open(HLSL, encoding="utf-8").read())
    cu.set_editor_property("description", "GyroFacade")
    cu.set_editor_property("output_type", unreal.CustomMaterialOutputType.CMOT_FLOAT3)
    ins = []
    for n in ("UV", "VC", "R", "Tex", "N", "V", "P", "L", "A", "TexObj"):
        ci = unreal.CustomInput()
        ci.set_editor_property("input_name", n)
        ins.append(ci)
    cu.set_editor_property("inputs", ins)
    outs = []
    for n, t in (("Rough", unreal.CustomMaterialOutputType.CMOT_FLOAT1), ("Metal", unreal.CustomMaterialOutputType.CMOT_FLOAT1),
                 ("Spec", unreal.CustomMaterialOutputType.CMOT_FLOAT1), ("NormalWS", unreal.CustomMaterialOutputType.CMOT_FLOAT3)):
        co = unreal.CustomOutput()
        co.set_editor_property("output_name", n)
        co.set_editor_property("output_type", t)
        outs.append(co)
    cu.set_editor_property("additional_outputs", outs)
    # pins are rebuilt from the inputs / outputs arrays on property change
    try:
        cu.post_edit_change()
    except Exception:
        pass
    for src, pin in ((tc, "UV"), (vc, "VC"), (rf, "R"), (mul, "Tex"), (nrm, "N"), (cam, "V"), (wp, "P"), (sun, "L"), (art, "A"), (tobj, "TexObj")):
        if src is vc:                                                    # VertexColor "" is RGB: append A -> RGBA
            app = X(unreal.MaterialExpressionAppendVector, -800, 250)
            MEL.connect_material_expressions(vc, "", app, "A")
            MEL.connect_material_expressions(vc, "A", app, "B")
            src = app
        if not MEL.connect_material_expressions(src, "", cu, pin):
            log("connect failed", pin)
    MEL.connect_material_property(cu, "", unreal.MaterialProperty.MP_BASE_COLOR)
    for pin, prop in (("Rough", unreal.MaterialProperty.MP_ROUGHNESS), ("Metal", unreal.MaterialProperty.MP_METALLIC),
                      ("Spec", unreal.MaterialProperty.MP_SPECULAR), ("NormalWS", unreal.MaterialProperty.MP_NORMAL)):
        if not MEL.connect_material_property(cu, pin, prop):
            log("property connect failed", pin)
    MEL.recompile_material(m)
    unreal.EditorAssetLibrary.save_asset(full, only_if_is_dirty=False)
    log("built", full)
    return m


if __name__ in ("__main__", "gyrosim_bldg_mat"):
    build()
    if os.environ.get("GYROSIM_BLDG_MAT_V2", "1") != "0" and not os.environ.get("GYROSIM_BLDG_HLSL") and os.path.isfile(V2[1]):
        build(*V2)
