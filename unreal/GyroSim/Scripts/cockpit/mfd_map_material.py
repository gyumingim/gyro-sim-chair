"""M_MfdMap (11-15): UI-domain material the right MFD moving map (Content/Python/mfd_map.py) draws each V-World tile
with (Canvas draw_material into the MFD_R render target). Render-time look only: Tex -> desaturate (Desat) -> x Bright
(linear). The stored tiles are never changed or copied. Run inside the editor (offscreen session or Python console):
    exec(open(r'<repo>/unreal/GyroSim/Scripts/cockpit/mfd_map_material.py').read()); build()
"""
import unreal

PATH, NAME = "/Game/Cockpit/Materials", "M_MfdMap"


def build():
    MEL = unreal.MaterialEditingLibrary
    full = PATH + "/" + NAME
    if unreal.EditorAssetLibrary.does_asset_exist(full):
        m = unreal.load_asset(full)
        MEL.delete_all_material_expressions(m)
    else:
        m = unreal.AssetToolsHelpers.get_asset_tools().create_asset(NAME, PATH, unreal.Material, unreal.MaterialFactoryNew())
    m.set_editor_property("material_domain", unreal.MaterialDomain.MD_UI)
    m.set_editor_property("blend_mode", unreal.BlendMode.BLEND_OPAQUE)
    X = lambda cls, x, y: MEL.create_material_expression(m, cls, x, y)
    tex = X(unreal.MaterialExpressionTextureSampleParameter2D, -800, 0)
    tex.set_editor_property("parameter_name", "Tex")
    tex.set_editor_property("texture", unreal.load_asset("/Engine/EngineResources/WhiteSquareTexture"))
    tex.set_editor_property("sampler_type", unreal.MaterialSamplerType.SAMPLERTYPE_COLOR)
    ds = X(unreal.MaterialExpressionScalarParameter, -800, 250)
    ds.set_editor_property("parameter_name", "Desat")
    ds.set_editor_property("default_value", 0.6)
    br = X(unreal.MaterialExpressionScalarParameter, -500, 250)
    br.set_editor_property("parameter_name", "Bright")
    br.set_editor_property("default_value", 0.325)
    de = X(unreal.MaterialExpressionDesaturation, -500, 0)
    mul = X(unreal.MaterialExpressionMultiply, -250, 0)
    ok = [MEL.connect_material_expressions(tex, "RGB", de, ""), MEL.connect_material_expressions(ds, "", de, "Fraction"),
          MEL.connect_material_expressions(de, "", mul, "A"), MEL.connect_material_expressions(br, "", mul, "B"),
          MEL.connect_material_property(mul, "", unreal.MaterialProperty.MP_EMISSIVE_COLOR)]
    MEL.recompile_material(m)
    saved = unreal.EditorAssetLibrary.save_loaded_asset(m, False)
    unreal.log("[mfd_map_material] %s built, links %s, saved %s" % (full, ok, saved))
    return all(ok) and saved
