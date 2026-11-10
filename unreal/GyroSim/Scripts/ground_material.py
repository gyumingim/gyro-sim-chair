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


COAST_PNG = os.environ.get("GYROSIM_COAST_PNG", r"C:/GyroSimTiles/coast/coast_mask.png")
COAST_TEX = PATH + "/T_GyroCoast"
MPC = PATH + "/MPC_GyroCoast"


def _defaults():
    return {**atmos_look.GROUND, **getattr(atmos_look, "SEA_COAST_DEF", {})}


def _scalar_names():
    return [k for k, v in _defaults().items() if not isinstance(v, (tuple, list))]


def _vector_names():
    return [k for k, v in _defaults().items() if isinstance(v, (tuple, list))]


def coast_assets():
    """coast v2: T_GyroCoast (the OSM coast mask, sim/coast_build.py --mask; data from OSM, kept out of git like the tiles)
    and MPC_GyroCoast (CoastU / CoastV world -> mask UV rows, set at Play by coast_look.py). -> (texture or None, mpc)."""
    tex = None
    if os.path.isfile(COAST_PNG):
        t = unreal.AssetImportTask()
        for k, v in (("filename", COAST_PNG), ("destination_path", PATH), ("destination_name", "T_GyroCoast"), ("automated", True),
                     ("replace_existing", True), ("save", False)):
            t.set_editor_property(k, v)
        unreal.AssetToolsHelpers.get_asset_tools().import_asset_tasks([t])
        tex = unreal.load_asset(COAST_TEX)
        if tex:
            for k, v in (("srgb", False), ("compression_settings", unreal.TextureCompressionSettings.TC_BC7),
                         ("never_stream", True), ("address_x", unreal.TextureAddress.TA_CLAMP), ("address_y", unreal.TextureAddress.TA_CLAMP),
                         ("lod_group", unreal.TextureGroup.TEXTUREGROUP_WORLD)):
                try:
                    tex.set_editor_property(k, v)
                except Exception as e:
                    log("coast tex", k, repr(e))
            try:
                tex.set_editor_property("max_texture_size", 8192)
            except Exception:
                pass
            tex.post_edit_change()
            EAL.save_asset(COAST_TEX, only_if_is_dirty=False)
            log("coast mask imported", COAST_TEX, tex.blueprint_get_size_x(), tex.blueprint_get_size_y())
    else:
        log("no coast mask", COAST_PNG, "- CoastOn stays 0 (python -I sim/coast_build.py --mask)")
    mpc = unreal.load_asset(MPC) if EAL.does_asset_exist(MPC) else None
    if mpc is None:
        mpc = unreal.AssetToolsHelpers.get_asset_tools().create_asset("MPC_GyroCoast", PATH, unreal.MaterialParameterCollection,
                                                                      unreal.MaterialParameterCollectionFactoryNew())
    vps = []
    for n in ("CoastU", "CoastV"):
        v = unreal.CollectionVectorParameter()
        v.set_editor_property("parameter_name", n)
        v.set_editor_property("default_value", unreal.LinearColor(0.0, 0.0, -1.0, 0.0))      # u = v = -1: outside -> coast v2 idle
        vps.append(v)
    mpc.set_editor_property("vector_parameters", vps)
    EAL.save_asset(MPC, only_if_is_dirty=False)
    return tex, mpc


def build():
    for p in (atmos_look.GROUND_MI_SEA0, MI, MAT):
        if EAL.does_asset_exist(p):
            EAL.delete_asset(p)
    ctex, mpc = coast_assets()
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
    ct = X(unreal.MaterialExpressionTextureObjectParameter, 150, 700)            # coast v2 mask (+ its sampler in HLSL)
    ct.set_editor_property("parameter_name", "CoastTex")
    if ctex:
        ct.set_editor_property("texture", ctex)
    ct.set_editor_property("sampler_type", unreal.MaterialSamplerType.SAMPLERTYPE_LINEAR_COLOR)
    srcs.append(("CoastTex", ct, ""))
    for i, n in enumerate(("CoastU", "CoastV")):
        cp = X(unreal.MaterialExpressionCollectionParameter, 150, 800 + 120 * i)
        cp.set_editor_property("collection", mpc)
        cp.set_editor_property("parameter_name", n)
        mk3 = X(unreal.MaterialExpressionComponentMask, 300, 800 + 120 * i)
        for c in ("r", "g", "b"):
            mk3.set_editor_property(c, True)
        MEL.connect_material_expressions(cp, "", mk3, "")
        srcs.append((n, mk3, ""))
    y = 800
    D = _defaults()
    for k in _scalar_names():
        e = X(unreal.MaterialExpressionScalarParameter, 400, y)
        e.set_editor_property("parameter_name", k)
        e.set_editor_property("default_value", float(D[k]))
        srcs.append((k, e, ""))
        y += 80
    for k in _vector_names():
        e = X(unreal.MaterialExpressionVectorParameter, 400, y)
        e.set_editor_property("parameter_name", k)
        e.set_editor_property("default_value", unreal.LinearColor(*(list(D[k]) + [1.0])[:4]))
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
    atmos_look.write_ground_params(mi, {**atmos_look.GROUND, **atmos_look.SEA_NEW, **atmos_look.SEA_ART,
                                        **(getattr(atmos_look, "SEA_COAST", {}) if ctex else {})})
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
