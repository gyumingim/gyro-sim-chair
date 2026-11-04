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
    """M_CkSurface: atlas colour x Tint, backlit legends (atlas alpha), edge wear / cavity from the vertex colour (R),
    grunge (UV1) on roughness / albedo, optional tiling normal map (fabric)."""
    m = _new_material("M_CkSurface", CK + "/Materials")
    uv0 = _expr(m, unreal.MaterialExpressionTextureCoordinate, -2200, -200)
    uv1 = _expr(m, unreal.MaterialExpressionTextureCoordinate, -2200, 400, coordinate_index=1)
    white = unreal.load_asset("/Engine/EngineResources/WhiteSquareTexture")
    tex = _tex_sample(m, white, uv0, -1900, -300, "Tex")
    trgb = tex                                   # texture sample "" output = RGB, alpha on pin "A"
    base = _op(m, unreal.MaterialExpressionMultiply, trgb, _vrgb(m, "Tint", (1, 1, 1), -1900, -450), -1650, -350)
    gr = unreal.load_asset(CK + "/Textures/T_CkGrunge")
    g = _tex_sample(m, gr, _op(m, unreal.MaterialExpressionMultiply, uv1, _sparam(m, "GrungeTile", 2.5, -2200, 520), -2000, 450), -1800, 400)
    gR = _expr(m, unreal.MaterialExpressionComponentMask, -1600, 400, r=True, g=False, b=False, a=False)
    MEL.connect_material_expressions(g, "", gR, "")
    vc = _expr(m, unreal.MaterialExpressionVertexColor, -2200, 150)
    # wear = saturate((vc.R - WearLo) * 8) * saturate(grunge * 2 - 0.4) * Wear
    w0 = _expr(m, unreal.MaterialExpressionSaturate, -1500, 150)
    MEL.connect_material_expressions(_op(m, unreal.MaterialExpressionMultiply,
                                         _op(m, unreal.MaterialExpressionSubtract, vc, _sparam(m, "WearLo", 0.56, -2000, 250), -1800, 150, "R"),
                                         _const(m, 8.0, -1800, 250), -1650, 150), "", w0, "")
    gm = _expr(m, unreal.MaterialExpressionSaturate, -1350, 330)
    MEL.connect_material_expressions(_op(m, unreal.MaterialExpressionSubtract, _op(m, unreal.MaterialExpressionMultiply, gR, _const(m, 2.0, -1500, 480), -1450, 400),
                                         _const(m, 0.4, -1500, 560), -1400, 330), "", gm, "")
    wear = _op(m, unreal.MaterialExpressionMultiply, _op(m, unreal.MaterialExpressionMultiply, w0, gm, -1250, 200), _sparam(m, "Wear", 0.0, -1400, 260), -1100, 200)
    cav = _expr(m, unreal.MaterialExpressionSaturate, -1500, 0)
    MEL.connect_material_expressions(_op(m, unreal.MaterialExpressionMultiply,
                                         _op(m, unreal.MaterialExpressionSubtract, _const(m, 0.45, -2000, 50), vc, -1800, 0, "", "R"),
                                         _const(m, 5.0, -1800, 80), -1650, 0), "", cav, "")
    shade = _op(m, unreal.MaterialExpressionSubtract, _const(m, 1.0, -1300, 60),
                _op(m, unreal.MaterialExpressionMultiply, cav, _sparam(m, "Cavity", 0.5, -1450, 100), -1350, 0), -1200, 0)
    gvar = _expr(m, unreal.MaterialExpressionLinearInterpolate, -1300, -120)       # subtle albedo variation from the grunge
    MEL.connect_material_expressions(_const(m, 0.97, -1450, -160), "", gvar, "A")
    MEL.connect_material_expressions(_const(m, 1.02, -1450, -120), "", gvar, "B")
    MEL.connect_material_expressions(gR, "", gvar, "Alpha")
    b1 = _op(m, unreal.MaterialExpressionMultiply, _op(m, unreal.MaterialExpressionMultiply, base, shade, -1100, -250), gvar, -950, -250)
    bw = _expr(m, unreal.MaterialExpressionLinearInterpolate, -800, -250)
    MEL.connect_material_expressions(b1, "", bw, "A")
    MEL.connect_material_expressions(_vrgb(m, "WearColor", (0.22, 0.22, 0.21), -1000, -350), "", bw, "B")
    MEL.connect_material_expressions(wear, "", bw, "Alpha")
    MEL.connect_material_property(bw, "", unreal.MaterialProperty.MP_BASE_COLOR)
    rv = _expr(m, unreal.MaterialExpressionLinearInterpolate, -1000, 500)
    MEL.connect_material_expressions(_const(m, 0.95, -1200, 480), "", rv, "A")
    MEL.connect_material_expressions(_const(m, 1.05, -1200, 540), "", rv, "B")
    MEL.connect_material_expressions(gR, "", rv, "Alpha")
    rough = _op(m, unreal.MaterialExpressionSubtract, _op(m, unreal.MaterialExpressionMultiply, _sparam(m, "Rough", 0.6, -1000, 420), rv, -850, 450),
                _op(m, unreal.MaterialExpressionMultiply, wear, _const(m, 0.25, -1000, 620), -850, 560), -700, 480)
    rc = _expr(m, unreal.MaterialExpressionClamp, -550, 480)
    MEL.connect_material_expressions(rough, "", rc, "")
    MEL.connect_material_property(rc, "", unreal.MaterialProperty.MP_ROUGHNESS)
    mt = _expr(m, unreal.MaterialExpressionLinearInterpolate, -700, 650)
    MEL.connect_material_expressions(_sparam(m, "Metal", 0.0, -900, 650), "", mt, "A")
    MEL.connect_material_expressions(_sparam(m, "WearMetal", 0.6, -900, 720), "", mt, "B")
    MEL.connect_material_expressions(wear, "", mt, "Alpha")
    MEL.connect_material_property(mt, "", unreal.MaterialProperty.MP_METALLIC)
    # emissive: backlit legends (atlas alpha) + self emission
    bl = _op(m, unreal.MaterialExpressionMultiply, _op(m, unreal.MaterialExpressionMultiply, trgb, tex, -1400, -650, "", "A"),
             _op(m, unreal.MaterialExpressionMultiply, _sparam(m, "Backlight", 0.0, -1600, -500), _vrgb(m, "BacklightColor", (0.85, 1.0, 0.75), -1600, -420), -1400, -480),
             -1200, -600)
    em = _op(m, unreal.MaterialExpressionAdd, bl, _op(m, unreal.MaterialExpressionMultiply, base, _sparam(m, "Emissive", 0.0, -1400, -360), -1200, -400), -1000, -550)
    MEL.connect_material_property(em, "", unreal.MaterialProperty.MP_EMISSIVE_COLOR)
    # normal: tiling map on UV1, strength NormalAmt (0 = flat)
    nt = unreal.load_asset(CK + "/Textures/T_CkFabricN")
    nn = _tex_sample(m, nt, _op(m, unreal.MaterialExpressionMultiply, uv1, _sparam(m, "NormalTile", 4.0, -2200, 800), -2000, 760), -1800, 760, "NormalTex")
    nl = _expr(m, unreal.MaterialExpressionLinearInterpolate, -1500, 760)
    nrgb = _expr(m, unreal.MaterialExpressionComponentMask, -1650, 760, r=True, g=True, b=True, a=False)
    MEL.connect_material_expressions(nn, "", nrgb, "")
    MEL.connect_material_expressions(_const3(m, (0, 0, 1), -1700, 900), "", nl, "A")
    MEL.connect_material_expressions(nrgb, "", nl, "B")
    MEL.connect_material_expressions(_sparam(m, "NormalAmt", 0.0, -1700, 960), "", nl, "Alpha")
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


# slot -> parameters (colours linear)
CK_SLOTS = {
    "CK_Panel": dict(tex="T_CkPanels", Rough=0.82, Backlight=2.6, Wear=0.35, Cavity=0.5),
    "CK_Dial": dict(tex="T_CkDials", Rough=0.45, Backlight=2.2, Wear=0.0, Cavity=0.0),
    "CK_ADI": dict(tex="T_CkADI", Rough=0.3, Wear=0.0, Cavity=0.0),
    "CK_Paint": dict(Tint=(0.040, 0.043, 0.047), Rough=0.7, Wear=0.5),
    "CK_Paint2": dict(Tint=(0.026, 0.028, 0.030), Rough=0.6, Wear=0.8),
    "CK_Black": dict(Tint=(0.012, 0.012, 0.013), Rough=0.5, Wear=0.6),
    "CK_AntiGlare": dict(Tint=(0.007, 0.007, 0.008), Rough=0.95, Wear=0.15),
    "CK_Metal": dict(Tint=(0.42, 0.43, 0.44), Metal=1.0, Rough=0.38),
    "CK_Chrome": dict(Tint=(0.8, 0.8, 0.8), Metal=1.0, Rough=0.16),
    "CK_Frame": dict(Tint=(0.032, 0.034, 0.037), Rough=0.45, Wear=1.0),
    "CK_Rubber": dict(Tint=(0.014, 0.014, 0.014), Rough=0.85),
    "CK_Grip": dict(Tint=(0.018, 0.018, 0.019), Rough=0.72, Wear=0.25, NormalAmt=0.5, NormalTile=10.0),
    "CK_Fabric": dict(Tint=(0.028, 0.032, 0.020), Rough=0.95, NormalAmt=1.0, NormalTile=5.0),
    "CK_Webbing": dict(Tint=(0.055, 0.060, 0.032), Rough=0.9, NormalAmt=1.0, NormalTile=9.0),
    "CK_Seat": dict(Tint=(0.016, 0.017, 0.018), Rough=0.55, Wear=0.8),
    "CK_Red": dict(Tint=(0.32, 0.012, 0.010), Rough=0.4, Wear=0.4),
    "CK_RedGuard": dict(Tint=(0.30, 0.014, 0.008), Rough=0.35, Wear=0.6),
    "CK_White": dict(Tint=(0.7, 0.7, 0.68), Rough=0.5),
    "CK_Knob": dict(Tint=(0.012, 0.012, 0.013), Rough=0.4, Wear=0.5),
    "CK_Needle": dict(Tint=(0.85, 0.85, 0.82), Rough=0.5, Emissive=0.5),
    "CK_Orange": dict(Tint=(0.8, 0.22, 0.01), Rough=0.5, Emissive=0.4),
    "CK_LensG": dict(Tint=(0.01, 0.05, 0.015), Rough=0.08, Emissive=0.15),
    "CK_LensA": dict(Tint=(0.08, 0.04, 0.003), Rough=0.08, Emissive=0.15),
    "CK_LensR": dict(Tint=(0.08, 0.005, 0.003), Rough=0.08, Emissive=0.15),
    "CK_LightG": dict(Tint=(0.15, 1.0, 0.3), Rough=0.1, Emissive=8.0),
    "CK_Hole": dict(Tint=(0.0, 0.0, 0.0), Rough=1.0),
    "CK_GearKnob": dict(Tint=(0.72, 0.71, 0.67), Rough=0.35, Wear=0.3),
    "CK_HUDFrame": dict(Tint=(0.03, 0.03, 0.032), Metal=0.6, Rough=0.35, Wear=0.6),
    "CK_HUDExit": dict(Tint=(0.0, 0.01, 0.005), Rough=0.05),
    "CK_Mirror": dict(Tint=(0.6, 0.62, 0.64), Metal=1.0, Rough=0.12),
    "CK_Bezel": dict(Tint=(0.010, 0.010, 0.011), Rough=0.32, Wear=0.5, Cavity=0.4),
    "CK_LightLit": dict(tex="T_CkPanels", Rough=0.2, Emissive=7.0),
    "CK_Wall": dict(tex="T_CkPanels", Rough=0.68, Wear=0.6, Cavity=0.5, GrungeTile=2.0),
}
CK_GLASS = {"CK_Glass": ("M_CkInstGlass", (0.6, 0.65, 0.7), 0.05), "CK_HUDGlass": ("M_CkHUDGlass", (0.45, 0.7, 0.55), 0.07),
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
    names = ("T_CkPanels.png", "T_CkDials.png", "T_CkADI.png", "T_CkGrunge.png", "T_CkFabricN.png")
    tx = import_textures([os.path.join(tdir, f) for f in names], CK + "/Textures",
                         {os.path.join(tdir, "T_CkGrunge.png"): "linear", os.path.join(tdir, "T_CkFabricN.png"): "normal"})
    for n in ("T_CkPanels", "T_CkDials"):
        if n in tx:
            tx[n].set_editor_property("compression_settings", unreal.TextureCompressionSettings.TC_BC7)
            EAL.save_loaded_asset(tx[n])
    master = ck_master()
    mats = {}
    for slot, prm in CK_SLOTS.items():
        sc = {k: v for k, v in prm.items() if isinstance(v, (int, float))}
        co = {k: v for k, v in prm.items() if isinstance(v, tuple)}
        te = {"Tex": tx[prm["tex"]]} if prm.get("tex") in tx else {}
        mats[slot] = instance("MI_" + slot[3:], master, sc, co, te, folder=CK + "/Materials")
    for slot, (name, rgb, op) in CK_GLASS.items():
        mats[slot] = ck_glass(name, rgb, op)
    meshes = {}
    for name, info in man["parts"].items():
        sm = ck_import_mesh(os.path.join(CK_SRC, info["fbx"]), CK + "/Meshes")
        if not sm:
            log("cockpit import failed", name)
            continue
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
