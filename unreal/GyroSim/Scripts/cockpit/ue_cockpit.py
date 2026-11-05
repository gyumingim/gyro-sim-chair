"""Unreal side of our cockpit (exec'd by Scripts/build_level.py, shares its helpers: _new_material, _expr, _op, ac, ...).
Imports Art/Cockpit (FBX parts with the mesh origin at the pivot, textures, manifest.json) to /Game/Cockpit, builds the
materials (one master M_CkSurface + an instance per Blender material slot, two glass materials) and places the parts
on the aircraft with the tags sim_client drives (StickPivot, ThrottlePivot, PedalL/R, GearHandle, GearLights,
Needle_<name>, ADIBall, MFD_L / MFD_R).
"""


def _vrgb(m, name, c, x, y):
    """vector parameter masked to RGB (vector parameters are float4)."""
    k = _expr(m, unreal.MaterialExpressionComponentMask, x + 150, y, r=True, g=True, b=True, a=False)
    MEL.connect_material_expressions(_vparam(m, name, c, x, y), "", k, "")
    return k


def ck_master():
    """M_CkSurface: atlas colour x Tint, backlit legends (atlas alpha), grunge (UV1), detail / fabric normal (UV1) and,
    on parts with baked masks (vertex colour G = 1, ck_shell): T_CkShellMasks on UV2 (R = AO, G = convex edges + hand
    touch zones, B = dirt). Parts without masks keep the old per-vertex edge / cavity values (vertex colour R).
    Realism pass 11-05: wider grunge breakup (albedo 0.85..1.10, roughness +-RoughVar/2), AO on BaseColor and Specular,
    dirt layer, worn paint = bare aluminium (metal 1), edge wear thresholded with the grunge (no soft cloudy blend)."""
    m = _new_material("M_CkSurface", CK + "/Materials")
    E, O, C, SP = unreal.MaterialExpressionComponentMask, _op, _const, _sparam
    MUL, ADD, SUB, LERP = (unreal.MaterialExpressionMultiply, unreal.MaterialExpressionAdd, unreal.MaterialExpressionSubtract,
                           unreal.MaterialExpressionLinearInterpolate)

    def mask(src, ch, x, y):
        k = _expr(m, E, x, y, r=ch == "r", g=ch == "g", b=ch == "b", a=ch == "a")
        MEL.connect_material_expressions(src, "", k, "")
        return k

    def sat(src, x, y):
        k = _expr(m, unreal.MaterialExpressionSaturate, x, y)
        MEL.connect_material_expressions(src, "", k, "")
        return k

    def lerp(a, b, t, x, y):
        k = _expr(m, LERP, x, y)
        for pin, v in (("A", a), ("B", b), ("Alpha", t)):
            MEL.connect_material_expressions(v, "", k, pin)
        return k

    uv0 = _expr(m, unreal.MaterialExpressionTextureCoordinate, -3000, -200)
    uv1 = _expr(m, unreal.MaterialExpressionTextureCoordinate, -3000, 400, coordinate_index=1)
    uv2 = _expr(m, unreal.MaterialExpressionTextureCoordinate, -3000, 1100, coordinate_index=2)
    white = unreal.load_asset("/Engine/EngineResources/WhiteSquareTexture")
    tex = _tex_sample(m, white, uv0, -2700, -300, "Tex")
    base = O(m, MUL, tex, _vrgb(m, "Tint", (1, 1, 1), -2700, -450), -2400, -350)
    gr = unreal.load_asset(CK + "/Textures/T_CkGrunge")
    g = _tex_sample(m, gr, O(m, MUL, uv1, SP(m, "GrungeTile", 2.5, -3000, 520), -2800, 450), -2600, 400)
    gR = mask(g, "r", -2400, 400)
    vc = _expr(m, unreal.MaterialExpressionVertexColor, -3000, 150)
    vR, vG = mask(vc, "r", -2800, 120), mask(vc, "g", -2800, 200)
    mt = unreal.load_asset(CK + "/Textures/T_CkShellMasks")
    mk = _tex_sample(m, mt if mt else white, uv2, -2700, 1100)
    mR, mG, mB = mask(mk, "r", -2400, 1000), mask(mk, "g", -2400, 1080), mask(mk, "b", -2400, 1160)
    one = C(m, 1.0, -2400, 900)
    # AO: baked (flagged parts) or the old vertex cavity (others)
    vcav = O(m, MUL, sat(O(m, MUL, O(m, SUB, C(m, 0.45, -2600, 40), vR, -2500, 0), C(m, 5.0, -2500, 80), -2400, 0), -2300, 0),
             SP(m, "Cavity", 0.5, -2400, 60), -2200, 0)
    ao_old = O(m, SUB, one, vcav, -2100, 0)
    ao_bk = lerp(one, mR, SP(m, "AOAmt", 1.0, -2300, 1240), -2100, 1050)
    ao = lerp(ao_old, ao_bk, vG, -1900, 300)
    # edges: vertex edge value (bevel faces) and baked edge / touch mask (flagged parts)
    vedge = sat(O(m, MUL, O(m, SUB, vR, SP(m, "WearLo", 0.56, -2600, 250), -2500, 220), C(m, 8.0, -2500, 300), -2400, 230), -2300, 230)
    edge = _expr(m, unreal.MaterialExpressionMax, -2100, 600)
    MEL.connect_material_expressions(vedge, "", edge, "A")
    MEL.connect_material_expressions(O(m, MUL, O(m, MUL, mG, vG, -2300, 1300), SP(m, "EdgeGain", 1.0, -2500, 1350), -2200, 1300), "", edge, "B")
    # wear = saturate((edge + (grunge - 0.5) * 0.8 - (1 - Wear)) * 6)  -> sharp-edged chips, grunge breaks the line up
    wearin = O(m, SUB, O(m, ADD, edge, O(m, MUL, O(m, SUB, gR, C(m, 0.5, -2300, 470), -2200, 440), C(m, 0.8, -2200, 520), -2100, 450), -1950, 500),
               O(m, SUB, one, SP(m, "Wear", 0.0, -2200, 660), -2050, 640), -1800, 520)
    wear = sat(O(m, MUL, wearin, C(m, 6.0, -1800, 600), -1650, 520), -1500, 520)
    # dirt (flagged parts): saturate((maskB * Dirt + grunge * 0.5 - 0.55) * 3)
    dirt = sat(O(m, MUL, O(m, SUB, O(m, ADD, O(m, MUL, O(m, MUL, mB, vG, -2300, 1400), SP(m, "Dirt", 0.0, -2300, 1480), -2200, 1420),
                                      O(m, MUL, gR, C(m, 0.5, -2300, 1560), -2200, 1540), -2100, 1450), C(m, 0.55, -2100, 1560), -2000, 1460),
                    C(m, 3.0, -2000, 1560), -1900, 1460), -1800, 1460)
    # base colour: tint x grunge variation (0.85..1.10), dirt, AO, then worn paint -> bare metal
    gvar = lerp(C(m, 0.85, -2200, -160), C(m, 1.10, -2200, -120), gR, -2000, -140)
    b1 = O(m, MUL, base, gvar, -1800, -250)
    b2 = lerp(b1, _vrgb(m, "DirtColor", (0.045, 0.040, 0.032), -1900, -60), O(m, MUL, dirt, C(m, 0.6, -1800, 30), -1700, 0), -1600, -200)
    b3 = O(m, MUL, b2, ao, -1450, -200)
    bw = lerp(b3, _vrgb(m, "WearColor", (0.55, 0.56, 0.57), -1500, -350), wear, -1250, -250)
    MEL.connect_material_property(bw, "", unreal.MaterialProperty.MP_BASE_COLOR)
    MEL.connect_material_property(O(m, MUL, C(m, 0.5, -1300, 1000), ao, -1150, 1000), "", unreal.MaterialProperty.MP_SPECULAR)
    # roughness = clamp(Rough + (grunge - 0.5) * RoughVar + dirt * 0.15 - wear * 0.25)
    r1 = O(m, ADD, SP(m, "Rough", 0.6, -1500, 700), O(m, MUL, O(m, SUB, gR, C(m, 0.5, -1700, 800), -1600, 780), SP(m, "RoughVar", 0.3, -1700, 860), -1450, 800), -1300, 720)
    r2 = O(m, SUB, O(m, ADD, r1, O(m, MUL, dirt, C(m, 0.15, -1400, 900), -1300, 880), -1200, 760), O(m, MUL, wear, C(m, 0.25, -1400, 980), -1300, 960), -1100, 800)
    rc = _expr(m, unreal.MaterialExpressionClamp, -950, 800, min_default=0.05, max_default=1.0)
    MEL.connect_material_expressions(r2, "", rc, "")
    MEL.connect_material_property(rc, "", unreal.MaterialProperty.MP_ROUGHNESS)
    MEL.connect_material_property(lerp(SP(m, "Metal", 0.0, -1300, 1100), SP(m, "WearMetal", 1.0, -1300, 1160), wear, -1100, 1100), "",
                                  unreal.MaterialProperty.MP_METALLIC)
    # emissive: backlit legends (atlas alpha) + self emission
    bl = O(m, MUL, O(m, MUL, tex, tex, -2200, -650, "", "A"),
           O(m, MUL, SP(m, "Backlight", 0.0, -2400, -500), _vrgb(m, "BacklightColor", (0.85, 1.0, 0.75), -2400, -420), -2200, -480), -2000, -600)
    em = O(m, ADD, bl, O(m, MUL, base, SP(m, "Emissive", 0.0, -2200, -360), -2000, -400), -1800, -550)
    MEL.connect_material_property(em, "", unreal.MaterialProperty.MP_EMISSIVE_COLOR)
    # normal: tiling map on UV1 (fabric / grip weave, or the paint detail normal), strength NormalAmt (0 = flat)
    nt = unreal.load_asset(CK + "/Textures/T_CkFabricN")
    nn = _tex_sample(m, nt, O(m, MUL, uv1, SP(m, "NormalTile", 4.0, -3000, 1800), -2800, 1760), -2600, 1760, "NormalTex")
    nrgb = _expr(m, E, -2400, 1760, r=True, g=True, b=True, a=False)
    MEL.connect_material_expressions(nn, "", nrgb, "")
    nl = lerp(_const3(m, (0, 0, 1), -2400, 1900), nrgb, SP(m, "NormalAmt", 0.0, -2400, 1960), -2200, 1800)
    MEL.connect_material_property(nl, "", unreal.MaterialProperty.MP_NORMAL)
    m = _finish(m)
    st = MEL.get_statistics(m)
    log("M_CkSurface compiled: pixel instructions", st.num_pixel_shader_instructions, "samplers", st.num_samplers)
    return m


def ck_glass(name, rgb, opacity):
    m = _new_material(name, CK + "/Materials")
    m.set_editor_property("blend_mode", unreal.BlendMode.BLEND_TRANSLUCENT)
    try:
        m.set_editor_property("translucency_lighting_mode", unreal.TranslucencyLightingMode.TLM_SURFACE)
    except Exception as e:
        log("glass lighting mode", e)
    MEL.connect_material_property(_const3(m, rgb, -500, 0), "", unreal.MaterialProperty.MP_BASE_COLOR)
    MEL.connect_material_property(_const(m, 0.04, -500, 120), "", unreal.MaterialProperty.MP_ROUGHNESS)
    MEL.connect_material_property(_const(m, 0.5, -500, 200), "", unreal.MaterialProperty.MP_SPECULAR)
    fr = _expr(m, unreal.MaterialExpressionFresnel, -700, 300)
    op = _op(m, unreal.MaterialExpressionAdd, _const(m, opacity, -700, 420),
             _op(m, unreal.MaterialExpressionMultiply, fr, _const(m, 0.18, -900, 420), -600, 380), -400, 320)
    MEL.connect_material_property(op, "", unreal.MaterialProperty.MP_OPACITY)
    return _finish(m)


# slot -> parameters (colours linear). Realism pass 11-05 (docs/cockpit-modeling-guide.md 5-6, photos c06 / c28 / d03):
# tub / walls FS 36231 dark gull grey, panels / consoles matte black >= 0.016 (PBR floor), worn paint = bare aluminium,
# Wear = how readily edges chip (0 none, 1 every edge), Dirt = dirt layer amount, PN = hard-surface detail normal.
PN = dict(NormalTex="T_CkPaintN", NormalAmt=0.2, NormalTile=7.0)
CK_SLOTS = {
    "CK_Panel": dict(tex="T_CkPanels", Rough=0.82, RoughVar=0.25, Backlight=2.6, Wear=0.35, Dirt=0.35, **PN),
    "CK_Dial": dict(tex="T_CkDials", Rough=0.45, RoughVar=0.1, Backlight=2.2, Cavity=0.0),
    "CK_ADI": dict(tex="T_CkADI", Rough=0.3, RoughVar=0.05, Cavity=0.0),
    "CK_Paint": dict(Tint=(0.13, 0.14, 0.14), Rough=0.62, RoughVar=0.3, Wear=0.4, Dirt=0.35, **PN),
    "CK_Paint2": dict(Tint=(0.030, 0.032, 0.034), Rough=0.6, RoughVar=0.25, Wear=0.6, Dirt=0.4, **PN),
    "CK_Black": dict(Tint=(0.018, 0.018, 0.019), Rough=0.55, RoughVar=0.25, Wear=0.5, Dirt=0.3, **PN),
    "CK_AntiGlare": dict(Tint=(0.012, 0.012, 0.013), Rough=0.93, RoughVar=0.1, Wear=0.1, Dirt=0.25, EdgeGain=0.5, NormalTex="T_CkPaintN",
                         NormalAmt=0.2, NormalTile=7.0),
    "CK_Metal": dict(Tint=(0.55, 0.56, 0.57), Metal=1.0, Rough=0.4, RoughVar=0.2, Dirt=0.3),
    "CK_Chrome": dict(Tint=(0.8, 0.8, 0.8), Metal=1.0, Rough=0.18, RoughVar=0.1),
    "CK_Frame": dict(Tint=(0.03, 0.032, 0.035), Rough=0.62, RoughVar=0.3, Wear=0.3, EdgeGain=1.0, Dirt=0.3, WearColor=(0.30, 0.31, 0.32), **PN),
    "CK_Rubber": dict(Tint=(0.02, 0.02, 0.02), Rough=0.85, RoughVar=0.15, Dirt=0.4),
    "CK_Grip": dict(Tint=(0.02, 0.02, 0.021), Rough=0.7, RoughVar=0.2, Wear=0.25, NormalAmt=0.5, NormalTile=10.0),
    "CK_Fabric": dict(Tint=(0.028, 0.032, 0.020), Rough=0.95, RoughVar=0.1, Dirt=0.3, NormalAmt=1.0, NormalTile=5.0),
    "CK_Webbing": dict(Tint=(0.055, 0.060, 0.032), Rough=0.9, RoughVar=0.1, Dirt=0.3, NormalAmt=1.0, NormalTile=9.0),
    "CK_Seat": dict(Tint=(0.022, 0.023, 0.024), Rough=0.55, RoughVar=0.3, Wear=0.6, Dirt=0.4, **PN),
    "CK_Red": dict(Tint=(0.32, 0.012, 0.010), Rough=0.4, Wear=0.4),
    "CK_RedGuard": dict(Tint=(0.30, 0.014, 0.008), Rough=0.35, Wear=0.6),
    "CK_White": dict(Tint=(0.7, 0.7, 0.68), Rough=0.5),
    "CK_Knob": dict(Tint=(0.016, 0.016, 0.017), Rough=0.4, Wear=0.5),
    "CK_Needle": dict(Tint=(0.85, 0.85, 0.82), Rough=0.5, RoughVar=0.0, Emissive=0.5),
    "CK_Orange": dict(Tint=(0.8, 0.22, 0.01), Rough=0.5, Emissive=0.4),
    "CK_LensG": dict(Tint=(0.01, 0.05, 0.015), Rough=0.08, RoughVar=0.05, Emissive=0.15),
    "CK_LensA": dict(Tint=(0.08, 0.04, 0.003), Rough=0.08, RoughVar=0.05, Emissive=0.15),
    "CK_LensR": dict(Tint=(0.08, 0.005, 0.003), Rough=0.08, RoughVar=0.05, Emissive=0.15),
    "CK_LightG": dict(Tint=(0.15, 1.0, 0.3), Rough=0.1, RoughVar=0.0, Emissive=8.0),
    "CK_Hole": dict(Tint=(0.0, 0.0, 0.0), Rough=1.0, RoughVar=0.0),
    "CK_GearKnob": dict(Tint=(0.72, 0.71, 0.67), Rough=0.35, Wear=0.3),
    "CK_HUDFrame": dict(Tint=(0.016, 0.016, 0.017), Rough=0.5, RoughVar=0.25, Wear=0.45, Dirt=0.3, **PN),
    "CK_HUDExit": dict(Tint=(0.0, 0.01, 0.005), Rough=0.05, RoughVar=0.0),
    "CK_Mirror": dict(Tint=(0.6, 0.62, 0.64), Metal=1.0, Rough=0.12, RoughVar=0.0),
    "CK_Bezel": dict(Tint=(0.016, 0.016, 0.017), Rough=0.4, RoughVar=0.2, Wear=0.4, Cavity=0.4, **PN),
    "CK_LightLit": dict(tex="T_CkPanels", Rough=0.2, RoughVar=0.0, Emissive=7.0),
    "CK_Wall": dict(tex="T_CkPanels", Rough=0.66, RoughVar=0.3, Wear=0.4, Dirt=0.35, Cavity=0.5, GrungeTile=2.0, **PN),
}
CK_GLASS = {"CK_Glass": ("M_CkInstGlass", (0.6, 0.65, 0.7), 0.05), "CK_HUDGlass": ("M_CkHUDGlass", (0.5, 0.78, 0.5), 0.09),
            "CK_DispGlass": ("M_CkDispGlass", (0.55, 0.6, 0.65), 0.03)}


DISPLAY_HLSL = """
float2 dx = ddx(UV) * 0.33, dy = ddy(UV) * 0.33;
float3 c = 0;
[unroll] for (int i = -1; i <= 1; i++)
[unroll] for (int j = -1; j <= 1; j++)
    c += Texture2DSample(T, TSampler, UV + dx * i + dy * j).rgb;
return c / 9.0;
"""


def ck_display():
    """M_CkDisplay: opaque unlit glass display = render target 'Tex' x Brightness, 3 x 3 supersampled over the pixel
    footprint (the canvas render targets have no mips) - crisp, no shimmer at VR distance. Opaque so the display glass
    (reflections) can sit in front of it."""
    m = _new_material("M_CkDisplay", CK + "/Materials")
    m.set_editor_property("shading_model", unreal.MaterialShadingModel.MSM_UNLIT)
    t = _expr(m, unreal.MaterialExpressionTextureObjectParameter, -1100, 0, parameter_name="Tex")
    tex = unreal.load_asset("/Engine/EngineResources/Black")
    t.set_editor_property("texture", tex)
    cu = _expr(m, unreal.MaterialExpressionCustom, -800, 0)
    cu.set_editor_property("code", DISPLAY_HLSL)
    cu.set_editor_property("output_type", unreal.CustomMaterialOutputType.CMOT_FLOAT3)
    ins = []
    for n in ("T", "UV"):
        ci = unreal.CustomInput()
        ci.set_editor_property("input_name", n)
        ins.append(ci)
    cu.set_editor_property("inputs", ins)
    MEL.connect_material_expressions(t, "", cu, "T")
    MEL.connect_material_expressions(_expr(m, unreal.MaterialExpressionTextureCoordinate, -1100, 200), "", cu, "UV")
    e = _op(m, unreal.MaterialExpressionMultiply, cu, _sparam(m, "Brightness", 1.0, -800, 250), -500, 0)
    MEL.connect_material_property(e, "", unreal.MaterialProperty.MP_EMISSIVE_COLOR)
    return _finish(m)


def ck_label():
    """M_CkLabel: unlit masked label plane (green text on black PNG -> opacity from brightness)."""
    m = _new_material("M_CkLabel", CK + "/Materials")
    m.set_editor_property("shading_model", unreal.MaterialShadingModel.MSM_UNLIT)
    m.set_editor_property("blend_mode", unreal.BlendMode.BLEND_MASKED)
    t = _expr(m, unreal.MaterialExpressionTextureSampleParameter2D, -800, 0, parameter_name="Tex")
    tex = unreal.load_asset("/Engine/EngineResources/Black")
    t.set_editor_property("texture", tex)
    t.set_editor_property("sampler_type", _sampler_type(tex))
    MEL.connect_material_property(_op(m, unreal.MaterialExpressionMultiply, t, _sparam(m, "Brightness", 1.6, -800, 250), -500, 0), "",
                                  unreal.MaterialProperty.MP_EMISSIVE_COLOR)
    g = _expr(m, unreal.MaterialExpressionComponentMask, -600, 300, r=False, g=True, b=False, a=False)
    MEL.connect_material_expressions(t, "", g, "")
    MEL.connect_material_property(_op(m, unreal.MaterialExpressionAdd, g, _const(m, 0.06, -700, 400), -400, 300), "",
                                  unreal.MaterialProperty.MP_OPACITY_MASK)
    m.set_editor_property("opacity_mask_clip_value", 0.12)
    return _finish(m)


CANOPY_HLSL = """
float3 d = LP - Eye;
float az = atan2(d.y, d.x);
float el = atan2(d.z, length(d.xy));
float2 uv = float2(az, -el) * Tile;
float4 t = Texture2DSample(T, TSampler, uv);
float scr = t.r;
float smu = t.g;
float c = saturate(dot(normalize(-CV), normalize(Sun)));
float glint = pow(c, 40.0);            // scratches light up only around the sun direction (arcs around the sun, photo d09)
float halo = pow(c, 4.0);              // dust / haze on the glass veils the view toward the sun
float fr = pow(1.0 - saturate(abs(dot(normalize(CV), normalize(N)))), 4.0);
float op = Base + fr * FresAmt + smu * SmudgeAmt * (0.3 + 0.7 * halo) + scr * glint * 0.12 + halo * HaloAmt * smu;
op = saturate(op);
float3 e = SunCol * (scr * glint * Gain + smu * halo * HaloGlow);
return float4(e / max(op, 0.02), op);
"""


def ck_canopy(sun_dir):
    """M_CkCanopy (on the F-16 canopy glass): nearly clear polycarbonate with fine circular polishing scratches that only
    light up around the sun (fake glint: scratch mask x (view . sun)^12, photos d09 / v2), smudges / dust that veil the
    view toward the sun, Fresnel at grazing angles. Scratch mapping = view angles from the design eye (no UVs needed).
    Translucency volume lighting (cheap) - the glints are emissive."""
    m = _new_material("M_CkCanopy", CK + "/Materials")
    m.set_editor_property("blend_mode", unreal.BlendMode.BLEND_TRANSLUCENT)
    m.set_editor_property("two_sided", True)
    m.set_editor_property("shading_model", unreal.MaterialShadingModel.MSM_UNLIT)
    cu = _expr(m, unreal.MaterialExpressionCustom, -600, 0)
    cu.set_editor_property("code", CANOPY_HLSL)
    cu.set_editor_property("output_type", unreal.CustomMaterialOutputType.CMOT_FLOAT4)
    names = ("LP", "CV", "N", "Sun", "SunCol", "T", "Eye", "Tile", "Gain", "Base", "FresAmt", "SmudgeAmt", "HaloAmt", "HaloGlow")
    ins = []
    for n in names:
        ci = unreal.CustomInput()
        ci.set_editor_property("input_name", n)
        ins.append(ci)
    cu.set_editor_property("inputs", ins)
    lp = _expr(m, unreal.MaterialExpressionTransformPosition, -1000, -300, transform_source_type=unreal.MaterialPositionTransformSource.TRANSFORMPOSSOURCE_WORLD,
               transform_type=unreal.MaterialPositionTransformSource.TRANSFORMPOSSOURCE_LOCAL)
    MEL.connect_material_expressions(_expr(m, unreal.MaterialExpressionWorldPosition, -1200, -300), "", lp, "")
    MEL.connect_material_expressions(lp, "", cu, "LP")
    MEL.connect_material_expressions(_expr(m, unreal.MaterialExpressionCameraVectorWS, -1000, -220), "", cu, "CV")
    MEL.connect_material_expressions(_expr(m, unreal.MaterialExpressionVertexNormalWS, -1000, -160), "", cu, "N")
    MEL.connect_material_expressions(_vrgb(m, "SunDir", sun_dir, -1200, -100), "", cu, "Sun")
    MEL.connect_material_expressions(_vrgb(m, "SunColor", (1.0, 0.96, 0.9), -1200, -20), "", cu, "SunCol")
    t = _expr(m, unreal.MaterialExpressionTextureObjectParameter, -1000, 60, parameter_name="Scratch")
    st = unreal.load_asset(CK + "/Textures/T_CkCanopyScratch")
    if st:
        t.set_editor_property("texture", st)
    MEL.connect_material_expressions(t, "", cu, "T")
    MEL.connect_material_expressions(_const3(m, EYE, -1000, 140), "", cu, "Eye")
    for i, (n, v) in enumerate((("Tile", 1.3), ("Gain", 0.7), ("Base", 0.008), ("FresAmt", 0.12), ("SmudgeAmt", 0.003), ("HaloAmt", 0.012),
                                ("HaloGlow", 0.08))):
        MEL.connect_material_expressions(_sparam(m, n, v, -1000, 220 + 60 * i), "", cu, n)
    rgb = _expr(m, unreal.MaterialExpressionComponentMask, -300, -50, r=True, g=True, b=True, a=False)
    MEL.connect_material_expressions(cu, "", rgb, "")
    a = _expr(m, unreal.MaterialExpressionComponentMask, -300, 80, r=False, g=False, b=False, a=True)
    MEL.connect_material_expressions(cu, "", a, "")
    MEL.connect_material_property(rgb, "", unreal.MaterialProperty.MP_EMISSIVE_COLOR)
    MEL.connect_material_property(a, "", unreal.MaterialProperty.MP_OPACITY)
    return _finish(m)


CK_FILL_LOC, CK_FILL_CD = (452.0, 0.0, 92.0), 1.6     # cockpit fill light (cd): lifts the shadowed interior a little


def ck_import_mesh(fbx, dest):
    t = unreal.AssetImportTask()
    t.filename = fbx
    t.destination_path = dest
    t.automated = True
    t.replace_existing = True
    t.save = True
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
    sd.set_editor_property("vertex_color_import_option", unreal.VertexColorImportOption.REPLACE)
    t.options = o
    assets.import_asset_tasks([t])
    n = os.path.splitext(os.path.basename(fbx))[0]
    return unreal.load_asset(f"{dest}/{n}")


def build_cockpit():
    man = json.load(open(os.path.join(CK_SRC, "manifest.json"), encoding="utf-8"))
    tdir = os.path.join(CK_SRC, "tex")
    names = ("T_CkPanels.png", "T_CkDials.png", "T_CkADI.png", "T_CkGrunge.png", "T_CkFabricN.png", "T_CkPaintN.png", "T_CkShellMasks.png",
             "T_CkCanopyScratch.png")
    names = [n for n in names if os.path.exists(os.path.join(tdir, n))]
    tx = import_textures([os.path.join(tdir, f) for f in names], CK + "/Textures",
                         {os.path.join(tdir, "T_CkGrunge.png"): "linear", os.path.join(tdir, "T_CkFabricN.png"): "normal",
                          os.path.join(tdir, "T_CkPaintN.png"): "normal", os.path.join(tdir, "T_CkShellMasks.png"): "linear",
                          os.path.join(tdir, "T_CkCanopyScratch.png"): "linear"})
    for n in ("T_CkShellMasks", "T_CkCanopyScratch"):       # masks: no sRGB, BC1-class mask compression
        if n in tx:
            tx[n].set_editor_property("compression_settings", unreal.TextureCompressionSettings.TC_MASKS)
            EAL.save_loaded_asset(tx[n])
    for n in ("T_CkPanels", "T_CkDials"):
        if n in tx:
            tx[n].set_editor_property("compression_settings", unreal.TextureCompressionSettings.TC_BC7)
            EAL.save_loaded_asset(tx[n])
    # CC0 normal maps from Poly Haven (Scripts/fetch_textures.py -> ThirdParty/polyhaven, not in git): seat fleece and
    # grip leather. Missing -> the slots keep our generated weave normal.
    for aid, slots in (("curly_teddy_natural", {"CK_Fabric": 1.2}), ("fabric_leather_02", {"CK_Grip": 4.0})):
        f = os.path.join(PH_SRC, aid, aid + "_nor.jpg")
        if not os.path.exists(f):
            log("CC0 texture missing (run Scripts/fetch_textures.py):", f)
            continue
        t = import_textures([f], TP + "/polyhaven", {f: "normal"}).get(aid + "_nor")
        if t:
            tx[aid + "_nor"] = t
            for sl, tile in slots.items():
                CK_SLOTS[sl].update(NormalTex=aid + "_nor", NormalTile=tile, NormalAmt=1.0)
    master = ck_master()
    mats = {}
    for slot, prm in CK_SLOTS.items():
        sc = {k: v for k, v in prm.items() if isinstance(v, (int, float))}
        co = {k: v for k, v in prm.items() if isinstance(v, tuple)}
        te = {"Tex": tx[prm["tex"]]} if prm.get("tex") in tx else {}
        if prm.get("NormalTex") in tx:
            te["NormalTex"] = tx[prm["NormalTex"]]
        mats[slot] = instance("MI_" + slot[3:], master, sc, co, te, folder=CK + "/Materials")
    for slot, (name, rgb, op) in CK_GLASS.items():
        mats[slot] = ck_glass(name, rgb, op)
    meshes = {}
    for name, info in man["parts"].items():
        sm = ck_import_mesh(os.path.join(CK_SRC, info["fbx"]), CK + "/Meshes")
        if not sm:
            log("cockpit import failed", name)
            continue
        if name == "ck_shell":
            try:
                sms = unreal.get_editor_subsystem(unreal.StaticMeshEditorSubsystem)      # None in the -nullrhi commandlet
                n_uv = (sms or unreal.EditorStaticMeshLibrary).get_num_uv_channels(sm, 0)
                # note: the deprecated EditorStaticMeshLibrary call reported 0 in the 11-05 commandlet build although the
                # FBX has the same 3 UV layers as before
            except Exception as e:
                n_uv = repr(e)
            log("ck_shell UV channels:", n_uv, "(3 = baked mask UV2 present)")
        for i, sl in enumerate(sm.static_materials):
            sn = str(sl.material_slot_name)
            key = sn if sn in mats else next((k for k in sorted(mats, key=len, reverse=True) if sn.startswith(k)), None)
            if key:
                sm.set_material(i, mats[key])
            else:
                log("cockpit: no material for slot", sn, "in", name)
        EAL.save_loaded_asset(sm)
        meshes[name] = sm
    if not globals().get("CK_PLACE", True):
        ck_display()
        log("cockpit assets re-imported (no placement)")
        return
    PV, NE, SC = man["pivots"], man["needles"], man["screens"]
    ac("AC_CkShell", meshes.get("ck_shell"), None, tags=("Cockpit",))
    ac("AC_CkGlass", meshes.get("ck_glass"), None, tags=("Cockpit",), shadows=False)
    for part_, tag in (("ck_stick", "StickPivot"), ("ck_throttle", "ThrottlePivot"), ("ck_pedal_l", "PedalL"), ("ck_pedal_r", "PedalR"),
                       ("ck_gearhandle", "GearHandle")):
        pv = PV[tag]
        a = ac(tag, None, None, tuple(pv), tags=(tag,))
        ac("AC_" + part_, meshes.get(part_), None, tuple(pv), parent=a)
    ac("AC_ck_gearlights", meshes.get("ck_gearlights"), None, tuple(PV["GearHandle"]), tags=("GearLights",), shadows=False)

    def frame_rot(x_axis, z_axis):
        r = unreal.MathLibrary.make_rot_from_xz(V(*x_axis), V(*z_axis))
        return (r.roll, r.pitch, r.yaw)
    for nd, f in NE.items():
        rr = frame_rot(f["x_axis"], f["z_axis"])
        fr = ac("NeedleFrame_" + nd, None, None, tuple(f["center"]), rr)
        ac("Needle_" + nd, meshes.get("ck_needle_" + nd), None, tuple(f["center"]), rr, tags=("Needle_" + nd,), parent=fr, shadows=False)
    b = PV["ADIBall"]
    rr = frame_rot(b["x_axis"], b["z_axis"])
    fr = ac("ADIFrame", None, None, tuple(b["center"]), rr)
    ac("ADIBall", meshes.get("ck_adi_ball"), None, tuple(b["center"]), rr, tags=("ADIBall",), parent=fr, shadows=False)
    fl = eas.spawn_actor_from_class(unreal.PointLight, V(*CK_FILL_LOC))
    fl.set_actor_label("CockpitFill")
    lc = fl.point_light_component
    lc.set_mobility(unreal.ComponentMobility.MOVABLE)
    for k, v in (("intensity", CK_FILL_CD), ("attenuation_radius", 150.0), ("source_radius", 25.0), ("cast_shadows", False),
                 ("light_color", unreal.Color(r=235, g=240, b=255, a=255)), ("intensity_units", unreal.LightUnits.CANDELAS)):
        try:
            lc.set_editor_property(k, v)
        except Exception as e:
            log("fill light", k, e)
    fl.tags = [unreal.Name("AircraftPart"), unreal.Name("CockpitFill")]
    attach(fl, root)
    # canopy glass (the F-16 exterior's glass mesh, placed by build_level before this file): our scratch / glint material
    try:
        sg = (globals().get("F16") or {}).get("F16_Glass")
        if sg:
            sd = sun.get_actor_forward_vector()
            cm = ck_canopy((-sd.x, -sd.y, -sd.z))
            for i, sl in enumerate(sg.static_materials):
                log("canopy slot", i, sl.material_slot_name)
                sg.set_material(i, cm)
            EAL.save_loaded_asset(sg)
    except Exception as e:
        log("canopy material failed", repr(e))
    disp = ck_display()
    for tag, s in SC.items():
        r = unreal.MathLibrary.make_rot_from_zx(V(*s["normal"]), V(0, 1, 0))
        w, h = (s["size"], s["size"]) if not isinstance(s["size"], list) else s["size"]
        ac(tag, SHAPE["Plane"], disp, tuple(s["center"]), (r.roll, r.pitch, r.yaw), (w / 100.0, h / 100.0, 1), tags=(tag,), shadows=False)
    # live lights (lit overlays, shown by sim_client when their condition is true)
    for name, li in (man.get("lights") or {}).items():
        ac("Light_" + name, meshes.get(li["part"]), None, (0, 0, 0), tags=("Light_" + name,), shadows=False)
    # beginner-mode callouts on the panel (Korean label pictures, hidden in expert mode by sim_client)
    try:
        cos = json.load(open(os.path.join(tdir, "callouts.json"), encoding="utf-8"))
        lm = ck_label()
        files = [os.path.join(tdir, "lbl_%s.png" % k) for k in cos]
        ltx = import_textures([f for f in files if os.path.exists(f)], CK + "/Textures/Labels")
        import importlib
        sys.path.insert(0, os.path.join(PROJ, "Scripts", "cockpit"))
        import layout as CKL
        importlib.reload(CKL)
        for k, (u, v) in CKL.CALLOUT_POS.items():
            tx = ltx.get("lbl_" + k)
            if not tx:
                continue
            mi = instance("MI_Lbl_" + k, lm, None, None, {"Tex": tx}, folder=CK + "/Materials/Labels")
            c = CKL.panel_pt(u, v, 0.35)
            r = unreal.MathLibrary.make_rot_from_zx(V(*CKL.PANEL_N), V(0, 1, 0))
            ac("Lbl_" + k, SHAPE["Plane"], mi, c, (r.roll, r.pitch, r.yaw), (cos[k]["w"] / 100.0, cos[k]["h"] / 100.0, 1), tags=("BeginnerLabel",),
               shadows=False)
    except Exception as e:
        log("beginner callouts failed", repr(e))
    log("cockpit placed:", sorted(meshes), "made", man.get("made"))


if os.path.exists(os.path.join(CK_SRC, "manifest.json")):
    build_cockpit()
else:
    log("Art/Cockpit/manifest.json missing - run Scripts/cockpit/build_cockpit.py (needs Blender)")
