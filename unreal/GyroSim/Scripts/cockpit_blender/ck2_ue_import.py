"""Cockpit v2 -> Unreal assets (run in a SECOND, off-screen editor commandlet; never the user's editor):
  UnrealEditor-Cmd.exe GyroSim.uproject -run=pythonscript -script=<repo>/unreal/GyroSim/Scripts/cockpit_blender/ck2_ue_import.py
      -unattended -nosplash -nullrhi
Imports C:/GyroSimTiles/assets/cockpit/{export,tex} (ck2_model.py / ck2_textures.py output) into /Game/ThirdParty/Cockpit2
(gitignored like all generated texture content; rebuild any time from the scripts), builds the materials:
  M_Ck2Surface  master: atlas x Tint, baked masks on UV1 (R AO, G convex edge, B wide cavity), tiling grunge, edge wear to
                primer, dust on up-facing cavities, panel-line / screw / engraving normal map, backlit legends (atlas alpha)
  M_Ck2Glass    translucent instrument / HUD combiner glass      M_Ck2Lamp  unlit lamp-on colour (sim lights)
and one instance per Blender slot. FlightMap is NOT touched: Content/Python/cockpit_v2.py swaps the meshes at Play.
"""
import json
import os
import time

import unreal

SRC = r"C:\GyroSimTiles\assets\cockpit"
EXP, TEXD = os.path.join(SRC, "export"), os.path.join(SRC, "tex")
DST = "/Game/ThirdParty/Cockpit2"
EAL, MEL = unreal.EditorAssetLibrary, unreal.MaterialEditingLibrary
AT = unreal.AssetToolsHelpers.get_asset_tools()


def log(*a):
    unreal.log("[ck2import] " + " ".join(str(x) for x in a))


def import_tex(path, kind="srgb"):
    t = unreal.AssetImportTask()
    t.filename, t.destination_path, t.automated, t.replace_existing, t.save = path, DST + "/Textures", True, True, True
    AT.import_asset_tasks([t])
    n = os.path.splitext(os.path.basename(path))[0]
    tx = unreal.load_asset(DST + "/Textures/" + n)
    if tx:
        if kind == "normal":
            tx.set_editor_property("compression_settings", unreal.TextureCompressionSettings.TC_NORMALMAP)
            tx.set_editor_property("srgb", False)
            tx.set_editor_property("flip_green_channel", False)
        elif kind == "linear":
            tx.set_editor_property("compression_settings", unreal.TextureCompressionSettings.TC_MASKS)
            tx.set_editor_property("srgb", False)
        elif kind == "gray":
            tx.set_editor_property("compression_settings", unreal.TextureCompressionSettings.TC_GRAYSCALE)
            tx.set_editor_property("srgb", False)
        else:
            tx.set_editor_property("compression_settings", unreal.TextureCompressionSettings.TC_BC7)
        EAL.save_loaded_asset(tx)
    return tx


def new_mat(name):
    p = DST + "/Materials/" + name
    if EAL.does_asset_exist(p):
        EAL.delete_asset(p)
    return AT.create_asset(name, DST + "/Materials", unreal.Material, unreal.MaterialFactoryNew())


def X(m, cls, x, y, **kw):
    e = MEL.create_material_expression(m, cls, x, y)
    for k, v in kw.items():
        e.set_editor_property(k, v)
    return e


def C(m, v, x, y):
    return X(m, unreal.MaterialExpressionConstant, x, y, r=v)


def SP(m, n, v, x, y):
    return X(m, unreal.MaterialExpressionScalarParameter, x, y, parameter_name=n, default_value=v)


def VP(m, n, c, x, y):
    v = X(m, unreal.MaterialExpressionVectorParameter, x, y, parameter_name=n, default_value=unreal.LinearColor(c[0], c[1], c[2], 1.0))
    k = X(m, unreal.MaterialExpressionComponentMask, x + 160, y, r=True, g=True, b=True, a=False)
    MEL.connect_material_expressions(v, "", k, "")
    return k


def OP(m, cls, a, b, x, y, pa="", pb=""):
    e = X(m, cls, x, y)
    MEL.connect_material_expressions(a, pa, e, "A")
    MEL.connect_material_expressions(b, pb, e, "B")
    return e


def MUL(m, a, b, x, y, pa="", pb=""):
    return OP(m, unreal.MaterialExpressionMultiply, a, b, x, y, pa, pb)


def ADD(m, a, b, x, y):
    return OP(m, unreal.MaterialExpressionAdd, a, b, x, y)


def SUB(m, a, b, x, y):
    return OP(m, unreal.MaterialExpressionSubtract, a, b, x, y)


def LERP(m, a, b, t, x, y):
    e = X(m, unreal.MaterialExpressionLinearInterpolate, x, y)
    MEL.connect_material_expressions(a, "", e, "A")
    MEL.connect_material_expressions(b, "", e, "B")
    MEL.connect_material_expressions(t, "", e, "Alpha")
    return e


def SAT(m, a, x, y):
    e = X(m, unreal.MaterialExpressionSaturate, x, y)
    MEL.connect_material_expressions(a, "", e, "")
    return e


def MASK(m, a, ch, x, y, pin=""):
    e = X(m, unreal.MaterialExpressionComponentMask, x, y, r=ch == "r", g=ch == "g", b=ch == "b", a=ch == "a")
    MEL.connect_material_expressions(a, pin, e, "")
    return e


def TS(m, name, tex, uv, x, y, stype=None):
    e = X(m, unreal.MaterialExpressionTextureSampleParameter2D, x, y, parameter_name=name)
    e.set_editor_property("texture", tex)
    e.set_editor_property("sampler_type", stype or unreal.MaterialSamplerType.SAMPLERTYPE_COLOR)
    MEL.connect_material_expressions(uv, "", e, "UVs")
    return e


def master(tx):
    m = new_mat("M_Ck2Surface")
    m.set_editor_property("two_sided", True)
    uv0 = X(m, unreal.MaterialExpressionTextureCoordinate, -3000, 0)
    uv1 = X(m, unreal.MaterialExpressionTextureCoordinate, -3000, 600, coordinate_index=1)
    at = TS(m, "Tex", tx["T_Ck2Atlas"], uv0, -2700, -200)
    nm = TS(m, "Normal", tx["T_Ck2Normal"], uv0, -2700, 1400, unreal.MaterialSamplerType.SAMPLERTYPE_NORMAL)
    mk = TS(m, "Masks", tx["T_Ck2Masks"], uv1, -2700, 600, unreal.MaterialSamplerType.SAMPLERTYPE_MASKS)
    gr = TS(m, "Grunge", tx["T_Ck2Grunge"], MUL(m, uv1, SP(m, "GrungeTile", 6.0, -3000, 800), -2850, 700), -2700, 900,
            unreal.MaterialSamplerType.SAMPLERTYPE_LINEAR_GRAYSCALE)
    one = C(m, 1.0, -2300, 1300)
    aoR, edG, cavB, g = MASK(m, mk, "r", -2400, 560), MASK(m, mk, "g", -2400, 620), MASK(m, mk, "b", -2400, 680), MASK(m, gr, "r", -2400, 900)
    rgb = X(m, unreal.MaterialExpressionComponentMask, -2400, -260, r=True, g=True, b=True, a=False)
    MEL.connect_material_expressions(at, "", rgb, "")
    base = MUL(m, rgb, VP(m, "Tint", (1, 1, 1), -2600, -100), -2200, -200)
    # AO (baked): lerp(1, ao, AOAmt)
    ao = LERP(m, one, aoR, SP(m, "AOAmt", 1.0, -2400, 760), -2100, 600)
    # edge wear: saturate((edge * EdgeWear + (grunge - 0.5) * 0.7 - 0.55) * 6)
    wear = SAT(m, MUL(m, SUB(m, ADD(m, MUL(m, edG, SP(m, "EdgeWear", 0.6, -2300, 1000), -2150, 950),
                                     MUL(m, SUB(m, g, C(m, 0.5, -2300, 1100), -2150, 1050), C(m, 0.7, -2150, 1120), -2000, 1050), -1900, 1000),
                                C(m, 0.85, -1900, 1100), -1750, 1000), C(m, 6.0, -1750, 1100), -1600, 1000), -1450, 1000)
    # dust: up-facing x wide cavity x grunge x Dust
    nws = X(m, unreal.MaterialExpressionVertexNormalWS, -2400, 1200)
    up = SAT(m, MASK(m, nws, "b", -2250, 1200), -2100, 1200)
    dust = SAT(m, MUL(m, MUL(m, MUL(m, up, SP(m, "Dust", 0.35, -2100, 1300), -1950, 1250), ADD(m, MUL(m, g, C(m, 0.9, -2100, 1400), -1950, 1380),
                                                                                                C(m, 0.3, -1950, 1450), -1800, 1400), -1700, 1300),
                       ADD(m, SUB(m, one, cavB, -1800, 1500), C(m, 0.35, -1800, 1560), -1650, 1520), -1550, 1350), -1400, 1350)
    gvar = LERP(m, C(m, 0.88, -2100, -60), C(m, 1.08, -2100, -20), g, -1950, -60)
    b1 = MUL(m, base, gvar, -1800, -200)
    b2 = LERP(m, b1, VP(m, "WearColor", (0.16, 0.165, 0.17), -1800, -380), wear, -1600, -260)
    b3 = LERP(m, b2, VP(m, "DustColor", (0.19, 0.17, 0.14), -1600, -420), MUL(m, dust, C(m, 0.12, -1600, -60), -1450, -80), -1400, -260)
    # convex edges catch light (subtle lift of the base colour on the baked edge mask, round 2 review: looked flat)
    lit_edge = MUL(m, edG, SP(m, "EdgeLift", 0.035, -1400, -500), -1250, -480)
    MEL.connect_material_property(ADD(m, MUL(m, b3, ao, -1200, -200), lit_edge, -1100, -300), "", unreal.MaterialProperty.MP_BASE_COLOR)
    MEL.connect_material_property(MUL(m, SP(m, "Spec", 0.5, -1300, 400), ao, -1150, 400), "", unreal.MaterialProperty.MP_SPECULAR)
    r = ADD(m, SP(m, "Rough", 0.6, -1600, 600), MUL(m, SUB(m, g, C(m, 0.5, -1750, 760), -1650, 740), SP(m, "RoughVar", 0.25, -1750, 820), -1500, 740), -1350, 650)
    r = SUB(m, ADD(m, r, MUL(m, dust, C(m, 0.12, -1400, 860), -1300, 840), -1200, 700), MUL(m, wear, C(m, 0.2, -1400, 940), -1300, 920), -1100, 720)
    rc = X(m, unreal.MaterialExpressionClamp, -950, 700, min_default=0.04, max_default=1.0)
    MEL.connect_material_expressions(r, "", rc, "")
    MEL.connect_material_property(rc, "", unreal.MaterialProperty.MP_ROUGHNESS)
    MEL.connect_material_property(LERP(m, SP(m, "Metal", 0.0, -1300, 1100), SP(m, "WearMetal", 0.0, -1300, 1160), wear, -1100, 1100), "",
                                  unreal.MaterialProperty.MP_METALLIC)
    # emissive: Emissive x atlas colour (DED / RWR) + backlit legends (atlas alpha) x Backlight
    em = ADD(m, MUL(m, rgb, SP(m, "Emissive", 0.0, -2200, -600), -2000, -620),
             MUL(m, at, MUL(m, SP(m, "Backlight", 0.0, -2300, -720), VP(m, "BacklightColor", (0.75, 1.0, 0.7), -2500, -800), -2150, -760), -2000, -720,
                 pa="A"), -1800, -650)
    MEL.connect_material_property(em, "", unreal.MaterialProperty.MP_EMISSIVE_COLOR)
    flat = X(m, unreal.MaterialExpressionConstant3Vector, -2400, 1600, constant=unreal.LinearColor(0, 0, 1, 1))
    nrgb = X(m, unreal.MaterialExpressionComponentMask, -2400, 1450, r=True, g=True, b=True, a=False)
    MEL.connect_material_expressions(nm, "", nrgb, "")
    MEL.connect_material_property(LERP(m, flat, nrgb, SP(m, "NormalAmt", 1.0, -2400, 1700), -2100, 1500), "", unreal.MaterialProperty.MP_NORMAL)
    MEL.recompile_material(m)
    EAL.save_loaded_asset(m)
    return m


def glass_mat():
    m = new_mat("M_Ck2Glass")
    m.set_editor_property("blend_mode", unreal.BlendMode.BLEND_TRANSLUCENT)
    m.set_editor_property("two_sided", True)
    try:
        m.set_editor_property("translucency_lighting_mode", unreal.TranslucencyLightingMode.TLM_SURFACE_PER_PIXEL_LIGHTING)
    except Exception as e:
        log("glass lighting mode", e)
    MEL.connect_material_property(VP(m, "Tint", (0.02, 0.025, 0.03), -600, 0), "", unreal.MaterialProperty.MP_BASE_COLOR)
    MEL.connect_material_property(SP(m, "Rough", 0.05, -600, 200), "", unreal.MaterialProperty.MP_ROUGHNESS)
    MEL.connect_material_property(SP(m, "Spec", 0.6, -600, 260), "", unreal.MaterialProperty.MP_SPECULAR)
    fr = X(m, unreal.MaterialExpressionFresnel, -800, 400, exponent=3.0)
    op = ADD(m, SP(m, "Opacity", 0.06, -800, 330), MUL(m, fr, SP(m, "FresnelOp", 0.5, -800, 480), -650, 430), -500, 360)
    MEL.connect_material_property(MUL(m, VP(m, "EdgeTint", (0.0, 0.0, 0.0), -800, 560), fr, -650, 560), "", unreal.MaterialProperty.MP_EMISSIVE_COLOR)
    MEL.connect_material_property(op, "", unreal.MaterialProperty.MP_OPACITY)
    MEL.recompile_material(m)
    EAL.save_loaded_asset(m)
    return m


def lamp_mat():
    m = new_mat("M_Ck2Lamp")
    m.set_editor_property("shading_model", unreal.MaterialShadingModel.MSM_UNLIT)
    MEL.connect_material_property(MUL(m, VP(m, "Color", (1.0, 0.5, 0.05), -600, 0), SP(m, "Intensity", 6.0, -600, 150), -400, 50), "",
                                  unreal.MaterialProperty.MP_EMISSIVE_COLOR)
    MEL.recompile_material(m)
    EAL.save_loaded_asset(m)
    return m


# slot -> instance parameters (linear colours, matched to the reference photos)
DARK = (0.055, 0.058, 0.06)
SLOTS = {
    "CK2_Plate": dict(Rough=0.52, EdgeWear=1, Dust=0.7, NormalAmt=1.0, Spec=0.45, EdgeLift=0.03, WearColor=(0.42, 0.43, 0.4), WearMetal=0.3),
    "CK2_Plate0": dict(Tint=DARK, Rough=0.55, NormalAmt=0.0, Spec=0.35),
    "CK2_PlateSide": dict(Tint=(0.05, 0.052, 0.054), Rough=0.6, NormalAmt=0.0, Spec=0.35),
    "CK2_Paint": dict(Tint=(0.1, 0.105, 0.105), Rough=0.55, EdgeWear=0.8, Dust=0.8, NormalAmt=0.0, Spec=0.45, EdgeLift=0.05, WearColor=(0.42, 0.43, 0.4), WearMetal=0.3),
    "CK2_Well": dict(Tint=(0.115, 0.118, 0.115), Rough=0.6, EdgeWear=0.7, Dust=1.1, NormalAmt=0.0, Spec=0.35, WearColor=(0.42, 0.43, 0.4)),
    "CK2_Wall": dict(Tint=(0.075, 0.078, 0.078), Rough=0.58, EdgeWear=0.8, Dust=0.8, NormalAmt=0.0, Spec=0.35, WearColor=(0.42, 0.43, 0.4)),
    "CK2_Glare": dict(Tint=(0.022, 0.022, 0.024), Rough=0.95, RoughVar=0.22, EdgeWear=0.10, Dust=1, NormalAmt=0.0, Spec=0.2, GrungeTile=14),
    "CK2_Rubber": dict(Tint=(0.01, 0.01, 0.01), Rough=0.92, EdgeWear=0.00, NormalAmt=0.0, Spec=0.25),
    "CK2_HUDBody": dict(Tint=(0.03, 0.031, 0.033), Rough=0.6, EdgeWear=0.30, NormalAmt=0.0, Spec=0.35),
    "CK2_HUDFrame": dict(Tint=(0.05, 0.05, 0.052), Rough=0.4, Metal=0.6, EdgeWear=0.20, NormalAmt=0.0),
    "CK2_Frame": dict(Tint=(0.03, 0.031, 0.033), Rough=0.5, EdgeWear=0.9, WearMetal=1, WearColor=(0.5, 0.5, 0.5), NormalAmt=0.0, Spec=0.35, Dust=0.6),
    "CK2_Metal": dict(Tint=(0.55, 0.55, 0.56), Rough=0.3, Metal=1.0, WearMetal=1.0, NormalAmt=0.0, EdgeWear=0.00),
    "CK2_Chrome": dict(Tint=(0.8, 0.8, 0.8), Rough=0.15, Metal=1.0, WearMetal=1.0, NormalAmt=0.0, EdgeWear=0.00, Dust=0.0),
    "CK2_Knob": dict(Tint=(0.008, 0.008, 0.009), Rough=0.32, EdgeWear=0.15, WearColor=(0.08, 0.08, 0.08), NormalAmt=0.0, Spec=0.5),
    "CK2_White": dict(Tint=(0.8, 0.8, 0.78), Rough=0.5, NormalAmt=0.0, EdgeWear=0.00, Backlight=0.0),
    "CK2_Bezel": dict(Tint=(0.03, 0.031, 0.033), Rough=0.4, EdgeWear=0.6, NormalAmt=0.0, Spec=0.5, WearColor=(0.42, 0.43, 0.4)),
    "CK2_Red": dict(Tint=(0.42, 0.02, 0.015), Rough=0.4, EdgeWear=0.25, NormalAmt=0.0),
    "CK2_Lens": dict(Rough=0.45, Spec=0.3, EdgeWear=0.00, Dust=0.1, NormalAmt=0.0, Emissive=0.9),
    "CK2_Lit": dict(Rough=0.1, Emissive=1.6, EdgeWear=0.00, Dust=0.0, NormalAmt=0.0, AOAmt=0.0),
    "CK2_Screen_L": dict(Tint=(0.002, 0.003, 0.004), Rough=0.08, Spec=0.7, EdgeWear=0.00, Dust=0.0, NormalAmt=0.0),
    "CK2_Screen_R": dict(Tint=(0.002, 0.003, 0.004), Rough=0.08, Spec=0.7, EdgeWear=0.00, Dust=0.0, NormalAmt=0.0),
    "CK2_SeatPaint": dict(Tint=(0.075, 0.085, 0.065), Rough=0.78, EdgeWear=0.40, NormalAmt=0.0, Spec=0.35),
    "CK2_Fleece": dict(Tint=(0.014, 0.014, 0.014), Rough=0.95, RoughVar=0.05, EdgeWear=0.00, Dust=0.2, NormalAmt=0.0, Spec=0.2),
    "CK2_Headrest": dict(Tint=(0.10, 0.11, 0.09), Rough=0.9, EdgeWear=0.00, NormalAmt=0.0, Spec=0.3),
    "CK2_Boot": dict(Tint=(0.17, 0.18, 0.18), Rough=0.7, EdgeWear=0.00, NormalAmt=1),
    "CK2_Grip": dict(Tint=(0.012, 0.012, 0.013), Rough=0.62, EdgeWear=0.4, WearColor=(0.05, 0.05, 0.05), NormalAmt=1),
    "CK2_GearKnob": dict(Tint=(0.7, 0.7, 0.68), Rough=0.35, EdgeWear=0.00, NormalAmt=0.0),
    "CK2_Kneeboard": dict(Tint=(0.03, 0.03, 0.032), Rough=0.5, NormalAmt=0.0),
    "CK2_HUDEdge": dict(Tint=(0.32, 0.36, 0.16), Rough=0.25, Metal=0.7, NormalAmt=0.0, EdgeWear=0.0, Dust=0.0),
    "CK2_Hose": dict(Tint=(0.07, 0.08, 0.045), Rough=0.75, NormalAmt=0.0, EdgeWear=0.0, Dust=0.4),
    "CK2_Strap": dict(Tint=(0.07, 0.08, 0.05), Rough=0.9, NormalAmt=0.0, EdgeWear=0.00),
}
GLASS = {"CK2_Glass": dict(Tint=(0.0, 0.0, 0.0), Opacity=0.03, FresnelOp=0.55, Rough=0.04), "CK2_HUDGlass": dict(Tint=(0.0, 0.0, 0.0), Opacity=0.018, FresnelOp=0.3, Rough=0.03, EdgeTint=(0.0, 0.0, 0.0))}
# 11-13 HUD combiner: was Tint (0.10, 0.14, 0.05) / Opacity 0.16 / FresnelOp 0.6 / EdgeTint (0.05, 0.07, 0.015) -> the lit
# yellow-green base colour over two panes (~30 % cover) read as an opaque plate; real combiner = near-clear, faint reflection.
# Neutral (Tint / EdgeTint 0, Opacity 0.018 x 2 panes): mean colour behind the glass = the no-glass shot within 1 %
LAMPS = {"amber": (1.0, 0.45, 0.04), "red": (1.0, 0.06, 0.03), "green": (0.15, 1.0, 0.25)}


def instance(name, parent, prm):
    p = DST + "/Materials/" + name
    mi = unreal.load_asset(p) if EAL.does_asset_exist(p) else AT.create_asset(name, DST + "/Materials", unreal.MaterialInstanceConstant,
                                                                               unreal.MaterialInstanceConstantFactoryNew())
    MEL.set_material_instance_parent(mi, parent)
    for k, v in prm.items():
        if isinstance(v, tuple):
            MEL.set_material_instance_vector_parameter_value(mi, k, unreal.LinearColor(v[0], v[1], v[2], 1.0))
        else:
            MEL.set_material_instance_scalar_parameter_value(mi, k, float(v))
    EAL.save_loaded_asset(mi)
    return mi


def import_mesh(fbx):
    t = unreal.AssetImportTask()
    t.filename, t.destination_path, t.automated, t.replace_existing, t.save = fbx, DST + "/Meshes", True, True, True
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
    sd.set_editor_property("normal_import_method", unreal.FBXNormalImportMethod.FBXNIM_IMPORT_NORMALS_AND_TANGENTS)
    t.options = o
    AT.import_asset_tasks([t])
    return unreal.load_asset(DST + "/Meshes/" + os.path.splitext(os.path.basename(fbx))[0])


def main():
    t0 = time.time()
    man = json.load(open(os.path.join(EXP, "manifest.json"), encoding="utf-8"))
    tx = {"T_Ck2Atlas": import_tex(os.path.join(TEXD, "T_Ck2Atlas.png")), "T_Ck2Normal": import_tex(os.path.join(TEXD, "T_Ck2Normal.png"), "normal"),
          "T_Ck2Grunge": import_tex(os.path.join(TEXD, "T_Ck2Grunge.png"), "gray"), "T_Ck2Masks": import_tex(os.path.join(EXP, "T_Ck2Masks.png"), "linear")}
    log("textures", {k: bool(v) for k, v in tx.items()})
    ms, mg, ml = master(tx), glass_mat(), lamp_mat()
    mats = {k: instance("MI_Ck2" + k[3:], ms, v) for k, v in SLOTS.items()}
    mats.update({k: instance("MI_Ck2" + k[3:], mg, v) for k, v in GLASS.items()})
    mats.update({"CK2_LampOn_" + c: instance("MI_Ck2_LampOn_" + c, ml, dict(Color=rgb, Intensity=1.4)) for c, rgb in LAMPS.items()})
    res = {}
    for name, info in man["parts"].items():
        sm = import_mesh(os.path.join(EXP, info["fbx"]))
        if not sm:
            log("import failed", name)
            continue
        miss = []
        for i, sl in enumerate(sm.static_materials):
            sn = str(sl.material_slot_name)
            key = sn if sn in mats else next((k for k in sorted(mats, key=len, reverse=True) if sn.startswith(k)), None)
            if key:
                sm.set_material(i, mats[key])
            else:
                miss.append(sn)
        try:   # distance field from all triangles, two-sided (thin open panels); rebuilt after the materials are set
            sms = unreal.get_editor_subsystem(unreal.StaticMeshEditorSubsystem) or unreal.EditorStaticMeshLibrary   # None in the commandlet
            bs = sms.get_lod_build_settings(sm, 0)
            for k, v in (("generate_distance_field_as_if_two_sided", True), ("distance_field_resolution_scale", 2.0)):
                try:
                    bs.set_editor_property(k, v)
                except Exception as e:
                    log("build setting", k, repr(e))
            sms.set_lod_build_settings(sm, 0, bs)
        except Exception as e:
            log("lod build settings", repr(e))
        EAL.save_loaded_asset(sm)
        try:
            nuv = unreal.get_editor_subsystem(unreal.StaticMeshEditorSubsystem).get_num_uv_channels(sm, 0)
        except Exception:
            nuv = None
        res[name] = dict(slots=len(sm.static_materials), missing=miss, uv=nuv)
        log("mesh", name, res[name])
    json.dump(dict(made=time.strftime("%Y-%m-%d %H:%M:%S"), seconds=round(time.time() - t0, 1), meshes=res, manifest_made=man.get("made")),
              open(os.path.join(SRC, "ue_import.json"), "w"), indent=1)
    log("done %.1f s" % (time.time() - t0))


main()
