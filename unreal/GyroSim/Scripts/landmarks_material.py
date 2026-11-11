"""Builds the landmark glass material (CesiumLandmarks tileset, sim/landmarks/landmarks_build.py glb tiles):
  /Game/Landmarks/M_GyroLandmark   = a copy of Cesium's M_CesiumBaseMaterial (same glTF material layers: base colour /
                                     metallic-roughness textures, vertex colour, texture coordinate sets) whose layer
                                     output goes through one Custom node (Scripts/landmarks_glass.hlsl): dark reflective
                                     curtain-wall glass with per-pane / per-floor variation and pane tilt, darker mullions.
  /Game/Landmarks/MI_GyroLandmark  = a copy of MI_CesiumThreeOverlaysAndClipping re-parented to it, parameters =
                                     landmarks_look.GLASS.
Applied at Play by Content/Python/landmarks_look.py (GYROSIM_LM_GLASS=0 = Cesium's default material, the look before).
Run with no editor holding these assets open (new assets only; FlightMap is not touched or saved):
    UnrealEditor-Cmd.exe GyroSim.uproject -run=pythonscript -script=<this file> -unattended -nosplash -nullrhi
Re-running rebuilds both in place.
"""
import os, sys
import unreal

PATH = "/Game/Landmarks"
MAT, MI = PATH + "/M_GyroLandmark", PATH + "/MI_GyroLandmark"
SRC_MAT = "/CesiumForUnreal/Materials/M_CesiumBaseMaterial"
SRC_MI = "/CesiumForUnreal/Materials/Instances/MI_CesiumThreeOverlaysAndClipping"
HLSL = os.path.join(os.path.dirname(os.path.abspath(__file__)), "landmarks_glass.hlsl")
MEL, EAL = unreal.MaterialEditingLibrary, unreal.EditorAssetLibrary
log = lambda *a: unreal.log("[lm_mat] " + " ".join(str(x) for x in a))

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "Content", "Python"))
import landmarks_look                                                  # noqa: E402  (parameter defaults)


def build():
    for p in (MI, MAT):
        if EAL.does_asset_exist(p):
            EAL.delete_asset(p)
    m = EAL.duplicate_asset(SRC_MAT, MAT)
    layers = MEL.get_material_property_input_node(m, unreal.MaterialProperty.MP_MATERIAL_ATTRIBUTES)
    X = lambda cls, x, y: MEL.create_material_expression(m, cls, x, y)
    brk = X(unreal.MaterialExpressionBreakMaterialAttributes, 400, -200)
    MEL.connect_material_expressions(layers, "", brk, "")
    mk = X(unreal.MaterialExpressionMakeMaterialAttributes, 1400, -200)
    for pin in ("EmissiveColor", "Opacity", "OpacityMask", "AmbientOcclusion", "WorldPositionOffset"):
        if not MEL.connect_material_expressions(brk, pin, mk, pin):
            log("pass-through failed", pin)
    tc = X(unreal.MaterialExpressionTextureCoordinate, 400, 300)
    nrm = X(unreal.MaterialExpressionVertexNormalWS, 400, 400)
    cam = X(unreal.MaterialExpressionCameraVectorWS, 400, 480)                     # backlit v2 (11-11): view and sun direction
    sun = X(unreal.MaterialExpressionSkyAtmosphereLightDirection, 400, 540)
    cu = X(unreal.MaterialExpressionCustom, 900, -200)
    cu.set_editor_property("code", open(HLSL, encoding="utf-8").read())
    cu.set_editor_property("description", "GyroGlass")
    cu.set_editor_property("output_type", unreal.CustomMaterialOutputType.CMOT_FLOAT3)
    srcs = [("C", brk, "BaseColor"), ("Rg", brk, "Roughness"), ("Mt", brk, "Metallic"), ("Sp", brk, "Specular"),
            ("UV", tc, ""), ("N", nrm, ""), ("V", cam, ""), ("L", sun, "")]
    y = 600
    for k, v in landmarks_look.GLASS.items():
        e = X(unreal.MaterialExpressionScalarParameter, 400, y)
        e.set_editor_property("parameter_name", k)
        e.set_editor_property("default_value", float(v))
        srcs.append((k, e, ""))
        y += 80
    ins = []
    for n, _, _ in srcs:
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
    try:
        cu.post_edit_change()
    except Exception:
        pass
    for n, e, pin in srcs:
        if not MEL.connect_material_expressions(e, pin, cu, n):
            log("connect failed", n)
    for pin, dst in (("", "BaseColor"), ("Rough", "Roughness"), ("Metal", "Metallic"), ("Spec", "Specular"), ("NormalWS", "Normal")):
        if not MEL.connect_material_expressions(cu, pin, mk, dst):
            log("connect to attributes failed", pin, dst)
    MEL.connect_material_property(mk, "", unreal.MaterialProperty.MP_MATERIAL_ATTRIBUTES)
    m.set_editor_property("tangent_space_normal", False)              # the Custom node returns a world-space normal
    MEL.recompile_material(m)
    EAL.save_asset(MAT, only_if_is_dirty=False)
    mi = EAL.duplicate_asset(SRC_MI, MI)
    MEL.set_material_instance_parent(mi, m)
    for k, v in landmarks_look.GLASS.items():
        MEL.set_material_instance_scalar_parameter_value(mi, k, float(v))
    MEL.update_material_instance(mi)
    EAL.save_asset(MI, only_if_is_dirty=False)
    log("built", MAT, MI, "scalars", len(MEL.get_scalar_parameter_names(mi)))
    return m, mi


if __name__ != "landmarks_material":               # run as a script (commandlet / exec), not on import
    build()
