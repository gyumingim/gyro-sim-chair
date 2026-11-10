"""Builds the V-World ground material (vworld mode, Cesium terrain tileset 'CesiumGround'):
  /Game/Materials/Ground/M_GyroGround   = a copy of Cesium's M_CesiumBaseMaterial (same material layer stack, so the
                                          raster overlay still finds its 'Overlay0..' layers) whose layer output goes
                                          through one Custom node (Scripts/ground_look.hlsl): sea surface (dark water body,
                                          wind-wave normals, F0 0.02, glint roughness growing with distance) on the 0 m MSL
                                          DEM sea, and a colour match of the land photo (saturation / contrast / gain).
  /Game/Materials/Ground/MI_GyroGround  = a copy of MI_CesiumThreeOverlaysAndClipping re-parented to it; the look
                                          parameters (atmos_look.GROUND + SEA_NEW) are written into this instance.
  /Game/Materials/Ground/MI_GyroGround_Sea0 = the same with atmos_look.GROUND only (the sea before 11-10, GYROSIM_SEA_LOOK=0).
Applied at Play by Content/Python/atmos_look.py (sim_client _vworld_ground -> atmos_look.apply_ground). Run in an editor
that does not have these assets open (new assets only; FlightMap is not touched or saved):
    UnrealEditor-Cmd.exe GyroSim.uproject -run=pythonscript -script=<this file> -unattended -nosplash -nullrhi
Re-running rebuilds both in place. Parameter defaults = atmos_look.GROUND (tuned against reference photos, see
docs/atmosphere-busan.md).
"""
import os, sys
import unreal

PATH = "/Game/Materials/Ground"
MAT, MI = PATH + "/M_GyroGround", PATH + "/MI_GyroGround"
SRC_MAT = "/CesiumForUnreal/Materials/M_CesiumBaseMaterial"
SRC_MI = "/CesiumForUnreal/Materials/Instances/MI_CesiumThreeOverlaysAndClipping"
WAVES = "/CesiumForUnreal/Textures/T_Water_TilingNormal_With_Height_02_Softened"
HLSL = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ground_look.hlsl")
MEL, EAL = unreal.MaterialEditingLibrary, unreal.EditorAssetLibrary
log = lambda *a: unreal.log("[ground_mat] " + " ".join(str(x) for x in a))

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "Content", "Python"))
import atmos_look                                                     # noqa: E402  (parameter defaults)


def _scalar_names():
    return [k for k, v in atmos_look.GROUND.items() if not isinstance(v, (tuple, list))]


def _vector_names():
    return [k for k, v in atmos_look.GROUND.items() if isinstance(v, (tuple, list))]


def build():
    for p in (atmos_look.GROUND_MI_SEA0, MI, MAT):
        if EAL.does_asset_exist(p):
            EAL.delete_asset(p)
    m = EAL.duplicate_asset(SRC_MAT, MAT)
    layers = MEL.get_material_property_input_node(m, unreal.MaterialProperty.MP_MATERIAL_ATTRIBUTES)
    X = lambda cls, x, y: MEL.create_material_expression(m, cls, x, y)
    brk = X(unreal.MaterialExpressionBreakMaterialAttributes, 400, -200)
    MEL.connect_material_expressions(layers, "", brk, "")
    mk = X(unreal.MaterialExpressionMakeMaterialAttributes, 1400, -200)
    for pin in ("Metallic", "EmissiveColor", "Opacity", "OpacityMask", "AmbientOcclusion", "WorldPositionOffset"):
        if not MEL.connect_material_expressions(brk, pin, mk, pin):
            log("pass-through failed", pin)
    nrm = X(unreal.MaterialExpressionVertexNormalWS, 400, 300)
    wpa = X(unreal.MaterialExpressionWorldPosition, 400, 400)
    wpr = X(unreal.MaterialExpressionWorldPosition, 400, 500)
    wpr.set_editor_property("world_position_shader_offset", unreal.WorldPositionIncludedOffsets.WPT_CAMERA_RELATIVE)
    tim = X(unreal.MaterialExpressionTime, 400, 600)
    wt = X(unreal.MaterialExpressionTextureObjectParameter, 400, 700)
    wt.set_editor_property("parameter_name", "WaveTex")
    wt.set_editor_property("texture", unreal.load_asset(WAVES))
    cu = X(unreal.MaterialExpressionCustom, 900, -200)
    cu.set_editor_property("code", open(HLSL, encoding="utf-8").read())
    cu.set_editor_property("description", "GyroGround")
    cu.set_editor_property("output_type", unreal.CustomMaterialOutputType.CMOT_FLOAT3)
    srcs = [("C", brk, "BaseColor"), ("Rg", brk, "Roughness"), ("Sp", brk, "Specular"), ("N", nrm, ""), ("P", wpa, ""),
            ("Q", wpr, ""), ("T", tim, ""), ("WaveTex", wt, "")]
    y = 800
    for k in _scalar_names():
        e = X(unreal.MaterialExpressionScalarParameter, 400, y)
        e.set_editor_property("parameter_name", k)
        e.set_editor_property("default_value", float(atmos_look.GROUND[k]))
        srcs.append((k, e, ""))
        y += 80
    for k in _vector_names():
        e = X(unreal.MaterialExpressionVectorParameter, 400, y)
        e.set_editor_property("parameter_name", k)
        e.set_editor_property("default_value", unreal.LinearColor(*(list(atmos_look.GROUND[k]) + [1.0])[:4]))
        mask = X(unreal.MaterialExpressionComponentMask, 650, y)
        for c in ("r", "g", "b"):
            mask.set_editor_property(c, True)
        MEL.connect_material_expressions(e, "", mask, "")
        srcs.append((k, mask, ""))
        y += 120
    ins = []
    for n, _, _ in srcs:
        ci = unreal.CustomInput()
        ci.set_editor_property("input_name", n)
        ins.append(ci)
    cu.set_editor_property("inputs", ins)
    outs = []
    for n, t in (("Rough", unreal.CustomMaterialOutputType.CMOT_FLOAT1), ("Spec", unreal.CustomMaterialOutputType.CMOT_FLOAT1),
                 ("NormalWS", unreal.CustomMaterialOutputType.CMOT_FLOAT3), ("Mask", unreal.CustomMaterialOutputType.CMOT_FLOAT1)):
        co = unreal.CustomOutput()
        co.set_editor_property("output_name", n)
        co.set_editor_property("output_type", t)
        outs.append(co)
    cu.set_editor_property("additional_outputs", outs)
    try:
        cu.post_edit_change()
    except Exception:
        pass
    for n, e, pin in srcs:
        if not MEL.connect_material_expressions(e, pin, cu, n):
            log("connect failed", n)
    for pin, dst in (("", "BaseColor"), ("Rough", "Roughness"), ("Spec", "Specular"), ("NormalWS", "Normal")):
        if not MEL.connect_material_expressions(cu, pin, mk, dst):
            log("connect to attributes failed", pin, dst)
    MEL.connect_material_property(mk, "", unreal.MaterialProperty.MP_MATERIAL_ATTRIBUTES)
    m.set_editor_property("tangent_space_normal", False)              # the Custom node returns a world-space normal
    MEL.recompile_material(m)
    EAL.save_asset(MAT, only_if_is_dirty=False)
    mi = EAL.duplicate_asset(SRC_MI, MI)
    MEL.set_material_instance_parent(mi, m)
    atmos_look.write_ground_params(mi, {**atmos_look.GROUND, **atmos_look.SEA_NEW, **atmos_look.SEA_ART})
    EAL.save_asset(MI, only_if_is_dirty=False)
    # the sea before the 11-10 pass (GYROSIM_SEA_LOOK=0): the 11-09 values, waves without the grazing fix
    if EAL.does_asset_exist(atmos_look.GROUND_MI_SEA0):
        EAL.delete_asset(atmos_look.GROUND_MI_SEA0)
    mi0 = EAL.duplicate_asset(SRC_MI, atmos_look.GROUND_MI_SEA0)
    MEL.set_material_instance_parent(mi0, m)
    atmos_look.write_ground_params(mi0, atmos_look.GROUND)
    EAL.save_asset(atmos_look.GROUND_MI_SEA0, only_if_is_dirty=False)
    log("built", MAT, MI, "texture params", MEL.get_texture_parameter_names(mi), "scalars", len(MEL.get_scalar_parameter_names(mi)))
    return m, mi


if __name__ != "ground_material":                 # run as a script (commandlet / exec), not on import
    build()
