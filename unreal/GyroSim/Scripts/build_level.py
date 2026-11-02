"""Builds /Game/Maps/FlightMap: terrain, airfield, sky, an F-16-like aircraft with a cockpit and moving controls.

Run headless (editor closed):
  "C:\\Program Files\\Epic Games\\UE_5.8\\Engine\\Binaries\\Win64\\UnrealEditor-Cmd.exe" ^
      <path>\\GyroSim.uproject -run=pythonscript -script=<path>\\Scripts\\build_level.py -unattended -nosplash
or inside the open editor (Python console):  exec(open(r"<path>/Scripts/build_level.py").read())

Re-running rebuilds the map, the generated meshes (/Game/Meshes, Geometry Script) and the materials (/Game/Materials).
Units: cm. X = north, Y = east, Z = up. Runway 3000 m x 45 m along X; the sim start point (lat0/lon0) = world origin,
150 m north of the south threshold. Terrain is visual only: JSBSim's ground is flat at sea level (0 ft).

Aircraft actor "Aircraft" (tag Aircraft) = JSBSim reference point, body axes = actor axes (X fwd, Y right, Z up).
Moving cockpit controls are pivot actors attached to it (tags StickPivot, ThrottlePivot, PedalL, PedalR), the camera
"SimCamera" carries the world-space HUD texts (tags HUD_*) and the tutorial panel (tag TutorPanel) so they are visible
in VR too.
"""
import math, random
import unreal

MAP = "/Game/Maps/FlightMap"
MAT_DIR = "/Game/Materials"
MESH_DIR = "/Game/Meshes"
log = lambda *a: unreal.log("[build_level] " + " ".join(str(x) for x in a))

eas = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
les = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
EAL = unreal.EditorAssetLibrary
assets = unreal.AssetToolsHelpers.get_asset_tools()
MEL = unreal.MaterialEditingLibrary
GP = unreal.GeometryScript_Primitives
V, R2 = unreal.Vector, unreal.Vector2D

SHAPE = {n: unreal.load_asset(f"/Engine/BasicShapes/{n}.{n}") for n in ("Plane", "Cube", "Cylinder", "Cone", "Sphere")}
EYE = (430.0, 0.0, 100.0)            # must match sim_client.EYE


# =====================================================================================================================
# materials
def _new_material(name):
    path = f"{MAT_DIR}/{name}"
    if EAL.does_asset_exist(path):
        m = unreal.load_asset(path)
        MEL.delete_all_material_expressions(m)
        return m
    return assets.create_asset(name, MAT_DIR, unreal.Material, unreal.MaterialFactoryNew())


def _finish(m):
    MEL.recompile_material(m)
    EAL.save_loaded_asset(m)
    return m


def _expr(m, cls, x, y, **props):
    e = MEL.create_material_expression(m, cls, x, y)
    for k, v in props.items():
        e.set_editor_property(k, v)
    return e


def _const3(m, rgb, x, y):
    return _expr(m, unreal.MaterialExpressionConstant3Vector, x, y, constant=unreal.LinearColor(rgb[0], rgb[1], rgb[2], 1.0))


def _const(m, v, x, y):
    return _expr(m, unreal.MaterialExpressionConstant, x, y, r=v)


def _sampler_type(tex):
    cs = tex.get_editor_property("compression_settings")
    srgb = tex.get_editor_property("srgb")
    if cs == unreal.TextureCompressionSettings.TC_GRAYSCALE or cs == unreal.TextureCompressionSettings.TC_ALPHA:
        return unreal.MaterialSamplerType.SAMPLERTYPE_GRAYSCALE if srgb else unreal.MaterialSamplerType.SAMPLERTYPE_LINEAR_GRAYSCALE
    if cs == unreal.TextureCompressionSettings.TC_NORMALMAP:
        return unreal.MaterialSamplerType.SAMPLERTYPE_NORMAL
    if cs == unreal.TextureCompressionSettings.TC_MASKS:
        return unreal.MaterialSamplerType.SAMPLERTYPE_MASKS
    return unreal.MaterialSamplerType.SAMPLERTYPE_COLOR if srgb else unreal.MaterialSamplerType.SAMPLERTYPE_LINEAR_COLOR


def _tex_sample(m, tex, uv, x, y):
    s = _expr(m, unreal.MaterialExpressionTextureSample, x, y)
    s.set_editor_property("texture", tex)
    s.set_editor_property("sampler_type", _sampler_type(tex))
    MEL.connect_material_expressions(uv, "", s, "UVs")
    return s


def _op(m, cls, a, b, x, y, a_out="", b_out=""):
    e = _expr(m, cls, x, y)
    MEL.connect_material_expressions(a, a_out, e, "A")
    MEL.connect_material_expressions(b, b_out, e, "B")
    return e


def simple_material(name, rgb, rough=0.8, metal=0.0, emissive=0.0, two_sided=False, back=None):
    """back = colour of the back faces (two-sided only), e.g. the dark inside of the cockpit tub."""
    m = _new_material(name)
    c = _const3(m, rgb, -500, 0)
    if back is not None:
        sgn = _expr(m, unreal.MaterialExpressionTwoSidedSign, -900, -200)
        a = _op(m, unreal.MaterialExpressionMultiply, sgn, _const(m, 0.5, -900, -100), -750, -150)
        a2 = _op(m, unreal.MaterialExpressionAdd, a, _const(m, 0.5, -900, -50), -650, -150)
        l = _expr(m, unreal.MaterialExpressionLinearInterpolate, -350, -100)
        MEL.connect_material_expressions(_const3(m, back, -700, -300), "", l, "A")
        MEL.connect_material_expressions(c, "", l, "B")
        MEL.connect_material_expressions(a2, "", l, "Alpha")
        MEL.connect_material_property(l, "", unreal.MaterialProperty.MP_BASE_COLOR)
    else:
        MEL.connect_material_property(c, "", unreal.MaterialProperty.MP_BASE_COLOR)
    MEL.connect_material_property(_const(m, rough, -500, 150), "", unreal.MaterialProperty.MP_ROUGHNESS)
    if metal:
        MEL.connect_material_property(_const(m, metal, -500, 250), "", unreal.MaterialProperty.MP_METALLIC)
    if emissive:
        e = _op(m, unreal.MaterialExpressionMultiply, c, _const(m, emissive, -700, 350), -300, 350)
        MEL.connect_material_property(e, "", unreal.MaterialProperty.MP_EMISSIVE_COLOR)
    m.set_editor_property("two_sided", two_sided)
    return _finish(m)


def glass_material(name, rgb, opacity):
    m = _new_material(name)
    m.set_editor_property("blend_mode", unreal.BlendMode.BLEND_TRANSLUCENT)
    m.set_editor_property("two_sided", True)
    MEL.connect_material_property(_const3(m, rgb, -500, 0), "", unreal.MaterialProperty.MP_BASE_COLOR)
    MEL.connect_material_property(_const(m, 0.05, -500, 120), "", unreal.MaterialProperty.MP_ROUGHNESS)
    MEL.connect_material_property(_const(m, 0.9, -500, 200), "", unreal.MaterialProperty.MP_SPECULAR)
    fr = _expr(m, unreal.MaterialExpressionFresnel, -700, 300)
    op = _op(m, unreal.MaterialExpressionAdd, _const(m, opacity, -700, 420), _op(m, unreal.MaterialExpressionMultiply, fr, _const(m, 0.25, -900, 420), -600, 380), -400, 320)
    MEL.connect_material_property(op, "", unreal.MaterialProperty.MP_OPACITY)
    return _finish(m)


def panel_material(name):
    """Unlit, emissive = texture parameter 'Tex' (the tutorial panel PNG is put in at runtime)."""
    m = _new_material(name)
    m.set_editor_property("shading_model", unreal.MaterialShadingModel.MSM_UNLIT)
    # translucent "after motion blur" = composited after TSR/TAA, so a changed panel image shows at once (no ghosting)
    m.set_editor_property("blend_mode", unreal.BlendMode.BLEND_TRANSLUCENT)
    try:
        m.set_editor_property("translucency_pass", unreal.MaterialTranslucencyPass.MTP_AFTER_MOTION_BLUR)
    except Exception as e:
        log("translucency pass", e)
    MEL.connect_material_property(_const(m, 1.0, -500, 300), "", unreal.MaterialProperty.MP_OPACITY)
    t = _expr(m, unreal.MaterialExpressionTextureSampleParameter2D, -600, 0, parameter_name="Tex")
    tex = unreal.load_asset("/Engine/EngineResources/Black")  or unreal.load_asset("/Engine/EngineMaterials/T_Default_MacroVariation")
    t.set_editor_property("texture", tex)
    t.set_editor_property("sampler_type", _sampler_type(tex))
    e = _op(m, unreal.MaterialExpressionMultiply, t, _expr(m, unreal.MaterialExpressionScalarParameter, -800, 250, parameter_name="Brightness", default_value=1.0), -300, 0)
    MEL.connect_material_property(e, "", unreal.MaterialProperty.MP_EMISSIVE_COLOR)
    return _finish(m)


def hud_text_material(name):
    """TextRender material: unlit translucent, drawn after TSR/TAA (camera-locked text would smear otherwise).
    Font = distance-field font parameter "Font" (TextRender puts its own font in), colour = TextRender colour (vertex colour)."""
    m = _new_material(name)
    m.set_editor_property("shading_model", unreal.MaterialShadingModel.MSM_UNLIT)
    m.set_editor_property("blend_mode", unreal.BlendMode.BLEND_TRANSLUCENT)
    try:
        m.set_editor_property("translucency_pass", unreal.MaterialTranslucencyPass.MTP_AFTER_MOTION_BLUR)
    except Exception as e:
        log("translucency pass", e)
    f = _expr(m, unreal.MaterialExpressionFontSampleParameter, -900, 0, parameter_name="Font")
    font = unreal.load_asset("/Engine/EngineFonts/RobotoDistanceField")
    if font:
        f.set_editor_property("font", font)
    a = _op(m, unreal.MaterialExpressionSubtract, f, _const(m, 0.5, -900, 200), -700, 100, "A")
    a2 = _op(m, unreal.MaterialExpressionMultiply, a, _const(m, 10.0, -700, 250), -550, 100)
    a3 = _op(m, unreal.MaterialExpressionAdd, a2, _const(m, 0.5, -550, 250), -400, 100)
    sat = _expr(m, unreal.MaterialExpressionSaturate, -250, 100)
    MEL.connect_material_expressions(a3, "", sat, "")
    MEL.connect_material_property(sat, "", unreal.MaterialProperty.MP_OPACITY)
    vc = _expr(m, unreal.MaterialExpressionVertexColor, -700, -150)
    e = _op(m, unreal.MaterialExpressionMultiply, vc, _const(m, 1.6, -700, -50), -400, -100)
    MEL.connect_material_property(e, "", unreal.MaterialProperty.MP_EMISSIVE_COLOR)
    return _finish(m)


def surface_master():
    """M_Surface: world-aligned colour variation (macro + mid + detail noise) with a height blend. Parameters:
    ColorA, ColorB, ColorHigh, MacroScale, MidScale, DetailScale, DetailStrength, HeightStart, HeightRange, Roughness."""
    m = _new_material("M_Surface")
    macro_t = unreal.load_asset("/Engine/EngineMaterials/T_Default_MacroVariation")
    noise_t = unreal.load_asset("/Engine/EngineMaterials/Good64x64TilingNoiseHighFreq")
    P = lambda n, v, x, y: _expr(m, unreal.MaterialExpressionScalarParameter, x, y, parameter_name=n, default_value=v)
    C = lambda n, c, x, y: _expr(m, unreal.MaterialExpressionVectorParameter, x, y, parameter_name=n, default_value=unreal.LinearColor(*c, 1.0))
    wp = _expr(m, unreal.MaterialExpressionWorldPosition, -2000, 0)
    xy = _expr(m, unreal.MaterialExpressionComponentMask, -1800, 0, r=True, g=True, b=False, a=False)
    MEL.connect_material_expressions(wp, "", xy, "")
    z = _expr(m, unreal.MaterialExpressionComponentMask, -1800, 500, r=False, g=False, b=True, a=False)
    MEL.connect_material_expressions(wp, "", z, "")
    uv1 = _op(m, unreal.MaterialExpressionDivide, xy, P("MacroScale", 400000.0, -1800, 120), -1600, 0)
    uv2 = _op(m, unreal.MaterialExpressionDivide, xy, P("MidScale", 30000.0, -1800, 220), -1600, 150)
    uv3 = _op(m, unreal.MaterialExpressionDivide, xy, P("DetailScale", 600.0, -1800, 320), -1600, 300)
    s1 = _tex_sample(m, macro_t, uv1, -1400, 0)
    s2 = _tex_sample(m, macro_t, uv2, -1400, 200)
    s3 = _tex_sample(m, noise_t, uv3, -1400, 400)
    mix = _op(m, unreal.MaterialExpressionMultiply, s1, s2, -1150, 100, "R", "G")
    mix2 = _op(m, unreal.MaterialExpressionMultiply, mix, _const(m, 2.2, -1300, 600), -1000, 100)
    sat = _expr(m, unreal.MaterialExpressionSaturate, -850, 100)
    MEL.connect_material_expressions(mix2, "", sat, "")
    base = _expr(m, unreal.MaterialExpressionLinearInterpolate, -700, 0)
    MEL.connect_material_expressions(C("ColorA", (0.06, 0.14, 0.035), -900, -200), "", base, "A")
    MEL.connect_material_expressions(C("ColorB", (0.13, 0.15, 0.06), -900, -100), "", base, "B")
    MEL.connect_material_expressions(sat, "", base, "Alpha")
    ds = P("DetailStrength", 0.25, -1300, 700)
    lo = _op(m, unreal.MaterialExpressionSubtract, _const(m, 1.0, -1150, 650), ds, -1000, 650)
    hi = _op(m, unreal.MaterialExpressionAdd, _const(m, 1.0, -1150, 750), ds, -1000, 750)
    det = _expr(m, unreal.MaterialExpressionLinearInterpolate, -850, 400)
    MEL.connect_material_expressions(lo, "", det, "A")
    MEL.connect_material_expressions(hi, "", det, "B")
    MEL.connect_material_expressions(s3, "R", det, "Alpha")
    col = _op(m, unreal.MaterialExpressionMultiply, base, det, -550, 100)
    hz = _op(m, unreal.MaterialExpressionSubtract, z, P("HeightStart", 1.0e7, -1800, 600), -1600, 500)
    hz2 = _op(m, unreal.MaterialExpressionDivide, hz, P("HeightRange", 50000.0, -1800, 700), -1450, 500)
    hs = _expr(m, unreal.MaterialExpressionSaturate, -1300, 500)
    MEL.connect_material_expressions(hz2, "", hs, "")
    fin = _expr(m, unreal.MaterialExpressionLinearInterpolate, -350, 100)
    MEL.connect_material_expressions(col, "", fin, "A")
    MEL.connect_material_expressions(C("ColorHigh", (0.16, 0.14, 0.11), -550, 300), "", fin, "B")
    MEL.connect_material_expressions(hs, "", fin, "Alpha")
    MEL.connect_material_property(fin, "", unreal.MaterialProperty.MP_BASE_COLOR)
    MEL.connect_material_property(P("Roughness", 0.92, -550, 450), "", unreal.MaterialProperty.MP_ROUGHNESS)
    MEL.connect_material_property(P("Specular", 0.2, -550, 550), "", unreal.MaterialProperty.MP_SPECULAR)
    return _finish(m)


def instance(name, parent, scalars=None, colors=None):
    path = f"{MAT_DIR}/{name}"
    mi = unreal.load_asset(path) if EAL.does_asset_exist(path) else \
        assets.create_asset(name, MAT_DIR, unreal.MaterialInstanceConstant, unreal.MaterialInstanceConstantFactoryNew())
    MEL.set_material_instance_parent(mi, parent)
    MEL.clear_all_material_instance_parameters(mi)
    for k, v in (scalars or {}).items():
        MEL.set_material_instance_scalar_parameter_value(mi, k, v)
    for k, c in (colors or {}).items():
        MEL.set_material_instance_vector_parameter_value(mi, k, unreal.LinearColor(c[0], c[1], c[2], 1.0))
    MEL.update_material_instance(mi)
    EAL.save_loaded_asset(mi)
    return mi


SURF = surface_master()
MAT = dict(
    grass=instance("MI_Grass", SURF, dict(Specular=0.0, MacroScale=300000.0, MidScale=25000.0, DetailScale=500.0, DetailStrength=0.3),
                   dict(ColorA=(0.045, 0.11, 0.03), ColorB=(0.12, 0.13, 0.05))),
    terrain=instance("MI_Terrain", SURF, dict(Specular=0.0, MacroScale=500000.0, MidScale=40000.0, DetailScale=800.0, DetailStrength=0.25,
                                              HeightStart=25000.0, HeightRange=70000.0),
                     dict(ColorA=(0.04, 0.09, 0.03), ColorB=(0.10, 0.11, 0.05), ColorHigh=(0.17, 0.15, 0.12))),
    asphalt=instance("MI_Asphalt", SURF, dict(MacroScale=80000.0, MidScale=4000.0, DetailScale=120.0, DetailStrength=0.35, Roughness=0.8),
                     dict(ColorA=(0.028, 0.028, 0.03), ColorB=(0.05, 0.05, 0.052))),
    concrete=instance("MI_Concrete", SURF, dict(MacroScale=50000.0, MidScale=3000.0, DetailScale=150.0, DetailStrength=0.2, Roughness=0.85),
                      dict(ColorA=(0.16, 0.155, 0.145), ColorB=(0.24, 0.23, 0.21))),
    field1=instance("MI_Field1", SURF, dict(Specular=0.0, MacroScale=60000.0, MidScale=5000.0, DetailScale=300.0, DetailStrength=0.3),
                    dict(ColorA=(0.16, 0.14, 0.06), ColorB=(0.22, 0.19, 0.08))),
    field2=instance("MI_Field2", SURF, dict(Specular=0.0, MacroScale=60000.0, MidScale=5000.0, DetailScale=300.0, DetailStrength=0.3),
                    dict(ColorA=(0.07, 0.16, 0.04), ColorB=(0.10, 0.20, 0.05))),
    field3=instance("MI_Field3", SURF, dict(Specular=0.0, MacroScale=60000.0, MidScale=5000.0, DetailScale=300.0, DetailStrength=0.3),
                    dict(ColorA=(0.12, 0.08, 0.05), ColorB=(0.15, 0.11, 0.07))),
    tree=instance("MI_Trees", SURF, dict(Specular=0.0, MacroScale=40000.0, MidScale=3000.0, DetailScale=200.0, DetailStrength=0.3),
                  dict(ColorA=(0.02, 0.06, 0.02), ColorB=(0.04, 0.08, 0.025))),
    mark=simple_material("M_Mark", (0.75, 0.75, 0.72), 0.7),
    body=simple_material("M_Body", (0.36, 0.39, 0.43), 0.42, 0.15, two_sided=True, back=(0.05, 0.055, 0.06)),
    body_dark=simple_material("M_BodyDark", (0.20, 0.22, 0.25), 0.5, 0.1, two_sided=True),
    dark=simple_material("M_Dark", (0.035, 0.035, 0.04), 0.55, two_sided=True),
    metal=simple_material("M_Metal", (0.25, 0.24, 0.22), 0.35, 0.9, two_sided=True),
    cockpit=simple_material("M_Cockpit", (0.07, 0.075, 0.08), 0.7, two_sided=True),
    seat=simple_material("M_Seat", (0.06, 0.07, 0.05), 0.85),
    yellow=simple_material("M_Yellow", (0.7, 0.55, 0.05), 0.5),
    red=simple_material("M_Red", (0.6, 0.02, 0.02), 0.5),
    mfd=simple_material("M_MFD", (0.02, 0.06, 0.035), 0.25, emissive=0.5),
    navR=simple_material("M_NavRed", (1.0, 0.05, 0.03), 0.4, emissive=30.0),
    navG=simple_material("M_NavGreen", (0.05, 1.0, 0.2), 0.4, emissive=30.0),
    canopy=glass_material("M_Canopy", (0.30, 0.27, 0.15), 0.07),
    hudglass=glass_material("M_HUDGlass", (0.3, 0.45, 0.35), 0.015),
    panel=panel_material("M_TutorPanel"),
    hudtext=hud_text_material("M_HUDText"),
)
log("materials done")


# =====================================================================================================================
# Geometry Script helpers
def gs_opts():
    return unreal.GeometryScriptPrimitiveOptions()


def save_mesh(dm, name, nanite=False):
    path = f"{MESH_DIR}/{name}"
    unreal.GeometryScript_Normals.compute_split_normals(dm, unreal.GeometryScriptSplitNormalsOptions(split_by_opening_angle=True, opening_angle_deg=40.0),
                                                       unreal.GeometryScriptCalculateNormalsOptions())
    if EAL.does_asset_exist(path):
        sm = unreal.load_asset(path)
        o = unreal.GeometryScriptCopyMeshToAssetOptions()
        o.set_editor_property("enable_recompute_normals", False)
        o.set_editor_property("enable_recompute_tangents", True)
        unreal.GeometryScript_AssetUtils.copy_mesh_to_static_mesh(dm, sm, o, unreal.GeometryScriptMeshWriteLOD())
    else:
        o = unreal.GeometryScriptCreateNewStaticMeshAssetOptions()
        o.set_editor_property("enable_recompute_normals", False)
        o.set_editor_property("enable_recompute_tangents", True)
        o.set_editor_property("enable_collision", False)
        o.set_editor_property("enable_nanite", nanite)
        sm, _ = unreal.GeometryScript_NewAssetUtils.create_new_static_mesh_asset_from_mesh(dm, path, o)
    if sm:
        try:
            ns = sm.get_editor_property("nanite_settings")
            if ns.get_editor_property("enabled") != nanite:
                ns.set_editor_property("enabled", nanite)
                sm.set_editor_property("nanite_settings", ns)
        except Exception as e:
            log("nanite setting skipped", name, e)
        EAL.save_loaded_asset(sm)
    return sm


def bbox(dm):
    return unreal.GeometryScript_MeshQueries.get_mesh_bounding_box(dm)


def revolve_x(profile, steps=32, degrees=360.0, offset=0.0):
    """profile = [(x, r), ...] -> DynamicMesh revolved around the body X axis (faces flipped so the outside is the front)."""
    for pitch in (-90.0, 90.0):
        dm = unreal.DynamicMesh()
        ro = unreal.GeometryScriptRevolveOptions(revolve_degrees=degrees, degree_offset=offset, fill_partial_revolve_endcaps=False)
        po = gs_opts()
        po.set_editor_property("flip_orientation", True)
        GP.append_revolve_path(dm, po, unreal.Transform(rotation=unreal.Rotator(pitch=pitch)), [R2(r, x) for x, r in profile], ro, steps, False)
        b = bbox(dm)
        if abs(b.max.x - max(p[0] for p in profile)) < 5 and abs(b.min.x - min(p[0] for p in profile)) < 5:
            return dm
    log("revolve_x: axis check failed, bbox", b)
    return dm


def extrude(poly, height, transform):
    dm = unreal.DynamicMesh()
    GP.append_simple_extrude_polygon(dm, gs_opts(), transform, [R2(x, y) for x, y in poly], height, 0, True)
    return dm


# =====================================================================================================================
# fresh level
if EAL.does_asset_exist(MAP):
    les.load_level(MAP)
    for a in eas.get_all_level_actors():
        eas.destroy_actor(a)
    log("cleared existing", MAP)
else:
    les.new_level(MAP)
    log("created", MAP)


def place(label, mesh_asset, loc, mat, rot=(0, 0, 0), scale=(1, 1, 1), movable=False, shadows=True, tags=()):
    a = eas.spawn_actor_from_class(unreal.StaticMeshActor, V(*loc), unreal.Rotator(roll=rot[0], pitch=rot[1], yaw=rot[2]))
    a.set_actor_label(label)
    c = a.static_mesh_component
    c.set_mobility(unreal.ComponentMobility.MOVABLE if movable else unreal.ComponentMobility.STATIC)
    if mesh_asset is not None:
        c.set_static_mesh(mesh_asset)
        n = max(1, c.get_num_materials())
        for i in range(n):
            c.set_material(i, mat)
    a.set_actor_scale3d(V(*scale))
    c.set_editor_property("cast_shadow", shadows)
    c.set_collision_enabled(unreal.CollisionEnabled.NO_COLLISION)
    if tags:
        a.tags = [unreal.Name(t) for t in tags]
    return a


def shape(label, s, loc, scale, mat, rot=(0, 0, 0), **kw):
    return place(label, SHAPE[s], loc, mat, rot, scale, **kw)


# =====================================================================================================================
# terrain (160 km square, visual only) + flat ground ring out to 400 km
def _hash(ix, iy, seed):
    n = (ix * 374761393 + iy * 668265263 + seed * 2147483647) & 0xFFFFFFFF
    n = ((n ^ (n >> 13)) * 1274126177) & 0xFFFFFFFF
    return ((n ^ (n >> 16)) & 0xFFFF) / 65535.0


def vnoise(x, y, seed):
    ix, iy = math.floor(x), math.floor(y)
    fx, fy = x - ix, y - iy
    ux, uy = fx * fx * (3 - 2 * fx), fy * fy * (3 - 2 * fy)
    a, b = _hash(ix, iy, seed), _hash(ix + 1, iy, seed)
    c, d = _hash(ix, iy + 1, seed), _hash(ix + 1, iy + 1, seed)
    return (a + (b - a) * ux) * (1 - uy) + (c + (d - c) * ux) * uy


def fbm(x, y, seed, octaves=5):
    s, amp, tot = 0.0, 1.0, 0.0
    for o in range(octaves):
        s += vnoise(x, y, seed + o) * amp
        tot += amp
        x, y, amp = x * 2.03, y * 2.03, amp * 0.5
    return s / tot


def smooth(e0, e1, v):
    t = max(0.0, min(1.0, (v - e0) / (e1 - e0)))
    return t * t * (3 - 2 * t)


def corridor_dist(x, y):                  # m, distance to the runway + approach / climb-out line (x -20 km .. 25 km, y 0)
    cx = max(-20000.0, min(25000.0, x))
    return math.hypot(x - cx, y)


TER_HALF, TER_N = 80000.0, 255           # m, grid steps


def terrain_h(x, y):                     # m
    d = corridor_dist(x, y)
    edge = smooth(TER_HALF, TER_HALF - 12000, max(abs(x), abs(y)))
    mtn = smooth(3500, 15000, d)
    r = fbm(x / 22000 + 3.1, y / 22000 - 1.7, 11)
    ridge = 1 - abs(2 * fbm(x / 9000, y / 9000, 23) - 1)
    big = 0.35 + 0.9 * fbm(x / 60000, y / 60000, 41, 3)
    h = (0.3 * r + 0.7 * ridge * ridge) * 1500 * big * mtn
    roll = fbm(x / 3000, y / 3000, 57, 3) * 40 * smooth(9000, 14000, d)
    return max(0.0, (h + roll) * edge)


def build_terrain():
    dm = unreal.DynamicMesh()
    GP.append_rectangle_xy(dm, gs_opts(), unreal.Transform(), TER_HALF * 200, TER_HALF * 200, TER_N, TER_N)
    _, pts, _gaps = unreal.GeometryScript_MeshQueries.get_all_vertex_positions(dm, False)
    arr = unreal.GeometryScript_List.convert_vector_list_to_array(pts)
    out = []
    for p in arr:
        out.append(V(p.x, p.y, terrain_h(p.x / 100, p.y / 100) * 100 - 12))
    unreal.GeometryScript_MeshEdits.set_all_mesh_vertex_positions(dm, unreal.GeometryScript_List.convert_array_to_vector_list(out))
    unreal.GeometryScript_Normals.recompute_normals(dm, unreal.GeometryScriptCalculateNormalsOptions())
    log("terrain verts", len(out), "bbox", bbox(dm))
    return save_mesh(dm, "SM_Terrain", nanite=False)      # Nanite dropped the near flat part of this 160 km mesh


ter = place("Terrain", build_terrain(), (0, 0, 0), MAT["terrain"], shadows=True)
ter.static_mesh_component.set_editor_property("affect_distance_field_lighting", False)

TILE = 2.0e6
dm = unreal.DynamicMesh()
for i in range(-10, 10):
    for j in range(-10, 10):
        cx, cy = (i + 0.5) * TILE, (j + 0.5) * TILE
        if abs(cx) < TER_HALF * 100 and abs(cy) < TER_HALF * 100:
            continue
        GP.append_rectangle_xy(dm, gs_opts(), unreal.Transform(location=V(cx, cy, -12)), TILE, TILE, 2, 2)
g = place("GroundRing", save_mesh(dm, "SM_GroundRing"), (0, 0, 0), MAT["terrain"], shadows=False)
g.static_mesh_component.set_editor_property("affect_distance_field_lighting", False)

# ---- airfield ------------------------------------------------------------------------------------------------------
RW_LEN, RW_W, RW_X0 = 300000.0, 4500.0, -15000.0
rw_cx = RW_X0 + RW_LEN / 2
shape("Runway", "Plane", (rw_cx, 0, 1), (RW_LEN / 100, RW_W / 100, 1), MAT["asphalt"], shadows=False)
shape("RunwayShoulder", "Plane", (rw_cx, 0, -4), (RW_LEN / 100 + 120, RW_W / 100 + 30, 1), MAT["concrete"], shadows=False)
shape("Taxiway", "Plane", (rw_cx, -15000, 1), (RW_LEN / 100 - 400, 23, 1), MAT["asphalt"], shadows=False)
for k, x in enumerate((RW_X0 + 30000, rw_cx, RW_X0 + RW_LEN - 30000)):
    shape(f"TaxiLink_{k}", "Plane", (x, -7500, 0.5), (23, 150, 1), MAT["asphalt"], shadows=False)
shape("Apron", "Plane", (32000, -22000, 1), (450, 140, 1), MAT["concrete"], shadows=False)
marks = unreal.DynamicMesh()
def mark_rect(cx, cy, sx, sy):
    GP.append_rectangle_xy(marks, gs_opts(), unreal.Transform(location=V(cx, cy, 3)), sx, sy, 0, 0)
x = RW_X0 + 15000 + 3000
while x + 3000 < RW_X0 + RW_LEN - 15000:
    mark_rect(x + 1500, 0, 3000, 90)
    x += 5000
for xs in (RW_X0 + 600, RW_X0 + RW_LEN - 600 - 3000):
    for k in range(12):
        y = -2000 + k * 340 + (200 if k >= 6 else 0)
        mark_rect(xs + 1500, y + 60, 3000, 180)
for xs in (RW_X0 + 30000 + 2250, RW_X0 + RW_LEN - 30000 - 2250):  # aiming point blocks, 300 m in
    for side in (-1, 1):
        mark_rect(xs, side * 900, 4500, 1000)
for xs in (RW_X0 + 45000, RW_X0 + RW_LEN - 45000):               # touchdown zone bars
    for side in (-1, 1):
        mark_rect(xs, side * 900, 2250, 350)
        mark_rect(xs, side * 1400, 2250, 350)
for side in (-1, 1):
    mark_rect(rw_cx, side * (RW_W / 2 - 60), RW_LEN, 90)
place("RunwayMarkings", save_mesh(marks, "SM_RunwayMarks"), (0, 0, 0), MAT["mark"], shadows=False)
for txt, x, yaw in (("36", RW_X0 + 4800, 0.0), ("18", RW_X0 + RW_LEN - 4800, 180.0)):
    t = eas.spawn_actor_from_class(unreal.TextRenderActor, V(x, 0, 4), unreal.Rotator(roll=0, pitch=90, yaw=yaw))
    t.set_actor_label("RunwayNumber_" + txt)
    tc = t.text_render
    tc.set_editor_property("text", txt)
    tc.set_editor_property("world_size", 1800.0)
    tc.set_editor_property("horizontal_alignment", unreal.HorizTextAligment.EHTA_CENTER)
    tc.set_editor_property("vertical_alignment", unreal.VerticalTextAligment.EVRTA_TEXT_CENTER)
    tc.set_editor_property("text_render_color", unreal.Color(r=200, g=200, b=195, a=255))
    tc.set_editor_property("cast_shadow", False)
for i, x in enumerate((20000, 32000, 44000)):
    shape(f"Hangar_{i}", "Cube", (x, -30000, 700), (60, 45, 14), MAT["concrete"])
    shape(f"HangarRoof_{i}", "Cylinder", (x, -30000, 1400), (12, 45, 60), MAT["metal"], rot=(0, 90, 0))
shape("Tower", "Cylinder", (56000, -24000, 1600), (5, 5, 32), MAT["concrete"])
shape("TowerCab", "Cylinder", (56000, -24000, 3400), (8, 8, 4), MAT["canopy"])
log("airfield done")

# ---- fields, forests, town (merged meshes: one draw call each) ----------------------------------------------------
random.seed(7)
fields = [unreal.DynamicMesh() for _ in range(3)]
trees = unreal.DynamicMesh()
houses = unreal.DynamicMesh()
nf = nt = nb = 0
for i in range(900):
    x, y = random.uniform(-14000, 26000), random.uniform(-12000, 12000)
    if abs(y) < 700 or terrain_h(x, y) > 1.0:
        continue
    sx, sy = random.uniform(150, 600), random.uniform(100, 400)
    GP.append_rectangle_xy(fields[i % 3], gs_opts(), unreal.Transform(location=V(x * 100, y * 100, -8), rotation=unreal.Rotator(yaw=random.choice((0, 0, 90, 12, -8)))), sx * 100, sy * 100, 0, 0)
    nf += 1
for i, f in enumerate(fields):
    place(f"Fields_{i}", save_mesh(f, f"SM_Fields{i}"), (0, 0, 0), MAT["field%d" % (i + 1)], shadows=False)
for c in range(90):
    cx, cy = random.uniform(-16000, 28000), random.uniform(-14000, 14000)
    if abs(cy) < 900 or (abs(cy) < 2500 and -2000 < cx < 4000):
        continue
    for k in range(40):
        x, y = cx + random.gauss(0, 250), cy + random.gauss(0, 250)
        if abs(y) < 800:
            continue
        h = random.uniform(9, 16)
        GP.append_cone(trees, gs_opts(), unreal.Transform(location=V(x * 100, y * 100, terrain_h(x, y) * 100 - 10)), h * 22, 30, h * 100, 6, 1, True)
        nt += 1
place("Forests", save_mesh(trees, "SM_Forests"), (0, 0, 0), MAT["tree"])
for c, (tx, ty) in enumerate(((12000, -6000), (-6000, 7000), (22000, 5000))):
    for k in range(70):
        x, y = tx + random.gauss(0, 500), ty + random.gauss(0, 500)
        if abs(y) < 900:
            continue
        w, d, h = random.uniform(8, 20), random.uniform(8, 25), random.uniform(5, 18)
        GP.append_box(houses, gs_opts(), unreal.Transform(location=V(x * 100, y * 100, -10), rotation=unreal.Rotator(yaw=random.uniform(0, 90))), w * 100, d * 100, h * 100)
        nb += 1
place("Towns", save_mesh(houses, "SM_Towns"), (0, 0, 0), MAT["concrete"])
log("fields", nf, "trees", nt, "houses", nb)

# =====================================================================================================================
# sky, light, fog, clouds, post process
sun = eas.spawn_actor_from_class(unreal.DirectionalLight, V(0, 0, 50000), unreal.Rotator(roll=0, pitch=-38, yaw=145))
sun.set_actor_label("Sun")
lc = sun.get_component_by_class(unreal.DirectionalLightComponent)
lc.set_mobility(unreal.ComponentMobility.MOVABLE)
lc.set_editor_property("intensity", 10.0)
lc.set_editor_property("atmosphere_sun_light", True)
for prop, val in (("dynamic_shadow_distance_movable_light", 40000.0), ("cast_cloud_shadows", True), ("light_source_angle", 0.53)):
    try:
        lc.set_editor_property(prop, val)
    except Exception as e:
        log("skip", prop, e)

sky = eas.spawn_actor_from_class(unreal.SkyAtmosphere, V(0, 0, 0))
sky.set_actor_label("SkyAtmosphere")
try:
    sky.get_component_by_class(unreal.SkyAtmosphereComponent).set_editor_property("aerial_pespective_view_distance_scale", 0.45)  # sic
except Exception as e:
    log("aerial perspective scale skipped", e)

sl = eas.spawn_actor_from_class(unreal.SkyLight, V(0, 0, 20000))
sl.set_actor_label("SkyLight")
slc = sl.get_component_by_class(unreal.SkyLightComponent)
slc.set_mobility(unreal.ComponentMobility.MOVABLE)
slc.set_editor_property("real_time_capture", True)

fog = eas.spawn_actor_from_class(unreal.ExponentialHeightFog, V(0, 0, 0))
fog.set_actor_label("HeightFog")
fc = fog.get_component_by_class(unreal.ExponentialHeightFogComponent)
fc.set_editor_property("fog_density", 0.00002)            # thin: denser fog turns the ground near the eye pale blue
fc.set_editor_property("fog_height_falloff", 0.2)
try:
    fc.set_editor_property("fog_inscattering_luminance", unreal.LinearColor(0.35, 0.45, 0.6, 1.0))
except Exception:
    pass

cloud_mat = unreal.load_asset("/Engine/EngineSky/VolumetricClouds/m_SimpleVolumetricCloud_Inst")
if cloud_mat:
    vc = eas.spawn_actor_from_class(unreal.VolumetricCloud, V(0, 0, 0))
    vc.set_actor_label("VolumetricCloud")
    vcc = vc.get_component_by_class(unreal.VolumetricCloudComponent)
    vcc.set_editor_property("material", cloud_mat)
    vcc.set_editor_property("layer_bottom_altitude", 2.4)    # km
    vcc.set_editor_property("layer_height", 3.0)
    for k, v in (("view_sample_count_scale", 0.7), ("shadow_view_sample_count_scale", 0.5)):
        try:
            vcc.set_editor_property(k, v)
        except Exception as e:
            log("cloud", k, e)

pp = eas.spawn_actor_from_class(unreal.PostProcessVolume, V(0, 0, 0))
pp.set_actor_label("PostProcess")
pp.set_editor_property("unbound", True)
ps = pp.get_editor_property("settings")
for k, v in (("override_motion_blur_amount", True), ("motion_blur_amount", 0.0), ("override_bloom_intensity", True), ("bloom_intensity", 0.35),
             ("override_auto_exposure_bias", True), ("auto_exposure_bias", 0.3), ("override_vignette_intensity", True), ("vignette_intensity", 0.25),
             ("override_lumen_final_gather_quality", True), ("lumen_final_gather_quality", 1.0),
             ("override_lumen_scene_detail", True), ("lumen_scene_detail", 1.0)):
    try:
        ps.set_editor_property(k, v)
    except Exception as e:
        log("pp skip", k, e)
pp.set_editor_property("settings", ps)

eas.spawn_actor_from_class(unreal.PlayerStart, V(-3000, 0, 300)).set_actor_label("PlayerStart")
log("sky done")

# =====================================================================================================================
# aircraft (F-16-like, body frame cm; JSBSim reference = actor origin; wheels 190 cm below it)
root = eas.spawn_actor_from_class(unreal.StaticMeshActor, V(0, 0, 0))
root.set_actor_label("Aircraft")
root.static_mesh_component.set_mobility(unreal.ComponentMobility.MOVABLE)
root.tags = [unreal.Name("Aircraft")]


def attach(child, parent):
    child.attach_to_actor(parent, unreal.Name(""), unreal.AttachmentRule.KEEP_WORLD, unreal.AttachmentRule.KEEP_WORLD,
                          unreal.AttachmentRule.KEEP_WORLD, False)


def ac(label, mesh_asset, mat, loc=(0, 0, 0), rot=(0, 0, 0), scale=(1, 1, 1), tags=(), parent=None, shadows=True):
    a = place(label, mesh_asset, loc, mat, rot, scale, movable=True, shadows=shadows, tags=("AircraftPart",) + tuple(tags))
    attach(a, parent or root)
    return a


def acs(label, s, loc, scale, mat, rot=(0, 0, 0), **kw):       # basic shape (cm sizes / 100)
    return ac(label, SHAPE[s], mat, loc, rot, scale, **kw)


FUS = [(800, 0), (770, 14), (720, 30), (650, 46), (560, 60), (480, 70), (400, 76), (300, 82), (150, 86), (0, 88),
       (-200, 88), (-400, 84), (-550, 76), (-650, 66), (-700, 60)]


def fus_section(x0, x1):
    pts = [p for p in FUS if x0 <= p[0] <= x1]
    return sorted(pts, key=lambda p: -p[0])


ac("AC_Nose", save_mesh(revolve_x(fus_section(650, 800), 32), "SM_FusNose"), MAT["body_dark"])
ac("AC_FusAft", save_mesh(revolve_x(fus_section(-700, 300), 32), "SM_FusAft"), MAT["body"])
# cockpit tub: 280 deg revolve (opening on top) between x 300 and 650
best = None
for off in range(0, 360, 20):
    dm = revolve_x(fus_section(300, 650), 32, 280.0, float(off))
    b = bbox(dm)
    sc = b.max.z + abs(b.max.y + b.min.y)
    if best is None or sc < best[0]:
        best = (sc, off, dm)
log("tub opening offset", best[1], "bbox", bbox(best[2]))
ac("AC_CockpitTub", save_mesh(best[2], "SM_FusTub"), MAT["body"])
# wing (40 deg leading edge, strakes), tails
wing = [(420, -46), (100, -96), (-219, -470), (-330, -470), (-330, 470), (-219, 470), (100, 96), (420, 46)]
ac("AC_Wing", save_mesh(extrude(wing, 14, unreal.Transform(location=V(0, 0, -22))), "SM_Wing"), MAT["body"])
for side in (-1, 1):
    ht = [(-540, 60 * side), (-640, 300 * side), (-700, 300 * side), (-720, 60 * side)]
    ac(f"AC_HTail_{side}", save_mesh(extrude(ht if side > 0 else ht[::-1], 8, unreal.Transform(location=V(0, 0, -6))), f"SM_HTail{side + 1}"), MAT["body"])
fin_poly = [(-380, 0), (-640, 330), (-700, 330), (-720, 0)]
fin = None
for roll in (90.0, -90.0):
    dm = extrude(fin_poly, 10, unreal.Transform(location=V(0, -5, 70), rotation=unreal.Rotator(roll=roll)))
    if bbox(dm).max.z > 350:
        fin = dm
        break
ac("AC_Fin", save_mesh(fin or dm, "SM_Fin"), MAT["body"])
acs("AC_Intake", "Cube", (230, 0, -95), (2.2, 0.9, 0.45), MAT["body"])
acs("AC_IntakeMouth", "Cube", (342, 0, -95), (0.05, 0.82, 0.38), MAT["dark"])
acs("AC_Nozzle", "Cylinder", (-735, 0, 0), (1.15, 1.15, 0.75), MAT["metal"], rot=(0, 90, 0))
acs("AC_NozzleIn", "Cylinder", (-770, 0, 0), (0.95, 0.95, 0.05), MAT["dark"], rot=(0, 90, 0))
for side in (-1, 1):
    acs(f"AC_Missile_{side}", "Cylinder", (-230, side * 485, -15), (0.13, 0.13, 2.9), MAT["body_dark"], rot=(0, 90, 0))
    acs(f"AC_Rail_{side}", "Cube", (-260, side * 474, -15), (2.2, 0.06, 0.06), MAT["dark"])
acs("AC_NavL", "Sphere", (-250, -472, -8), (0.06, 0.06, 0.06), MAT["navR"], shadows=False)
acs("AC_NavR", "Sphere", (-250, 472, -8), (0.06, 0.06, 0.06), MAT["navG"], shadows=False)
# landing gear (tag Gear: hidden when retracted)
for label, x, y in (("N", 420, 0), ("L", -60, -120), ("R", -60, 120)):
    acs(f"AC_GearStrut{label}", "Cylinder", (x, y, -128), (0.14, 0.14, 0.62), MAT["metal"], tags=("Gear",))
    acs(f"AC_GearWheel{label}", "Cylinder", (x, y, -160), (0.6, 0.6, 0.18 if label == "N" else 0.24), MAT["dark"], rot=(90, 0, 0), tags=("Gear",))
# canopy glass + frame
dm = unreal.DynamicMesh()
GP.append_sphere_lat_long(dm, gs_opts(), unreal.Transform(location=V(420, 0, 62), scale=V(170 / 50.0, 47 / 50.0, 64 / 50.0)), 50.0, 16, 32)
ac("AC_Canopy", save_mesh(dm, "SM_Canopy"), MAT["canopy"], tags=("Canopy",), shadows=False)
for x in (300,):                     # rear bow only (the F-16 bubble has no front frame)
    k = math.sqrt(max(0.0, 1 - ((x - 420) / 170.0) ** 2))
    best = None
    for off in range(0, 360, 45):
        dm = unreal.DynamicMesh()
        ro = unreal.GeometryScriptRevolveOptions(revolve_degrees=180.0, degree_offset=float(off))
        GP.append_torus(dm, gs_opts(), unreal.Transform(location=V(x, 0, 62), rotation=unreal.Rotator(pitch=90)), ro, 47 * k, 2.2, 24, 6)
        try:
            unreal.GeometryScript_MeshTransforms.scale_mesh(dm, V(1, 1, 64 / 47.0), V(x, 0, 62))
        except Exception as e:
            log("bow scale", e)
        b = bbox(dm)
        if b.min.z > 55 and (best is None or b.max.z > best[0]):
            best = (b.max.z, dm)
    ac(f"AC_CanopyBow_{x}", save_mesh(best[1] if best else dm, f"SM_CanopyBow{x}"), MAT["dark"])
for side in (-1, 1):
    acs(f"AC_CanopySill_{side}", "Cube", (440, side * 46, 60), (3.2, 0.05, 0.05), MAT["dark"])

# ---- cockpit interior -------------------------------------------------------------------------------------------
acs("CP_Floor", "Cube", (480, 0, -8), (3.4, 0.8, 0.04), MAT["cockpit"])
acs("CP_SeatPan", "Cube", (440, 0, 30), (0.55, 0.45, 0.10), MAT["seat"])
acs("CP_SeatBack", "Cube", (400, 0, 80), (0.10, 0.45, 0.95), MAT["seat"], rot=(0, -12, 0))
acs("CP_Headrest", "Cube", (395, 0, 128), (0.14, 0.3, 0.2), MAT["seat"], rot=(0, -12, 0))
acs("CP_EjectHandle", "Cube", (468, 0, 37), (0.04, 0.16, 0.03), MAT["yellow"])
# panel top ~15 deg below the eye (over-nose view), bottom high enough to see the pedals under it
acs("CP_Panel", "Cube", (572, 0, 54), (0.08, 0.80, 0.18), MAT["cockpit"], rot=(0, 15, 0))
acs("CP_Glareshield", "Cube", (556, 0, 64.5), (0.40, 0.66, 0.05), MAT["cockpit"])
for i, y in enumerate((-21, 21)):
    acs(f"CP_MFD_{i}", "Cube", (567, y, 54), (0.02, 0.14, 0.14), MAT["mfd"], rot=(0, 15, 0), shadows=False)
for i, (y, z) in enumerate(((-6, 58), (6, 58), (0, 49))):
    acs(f"CP_Gauge_{i}", "Cylinder", (568, y, z), (0.06, 0.06, 0.02), MAT["dark"], rot=(0, 75, 0), shadows=False)
acs("CP_HUDGlass", "Cube", (552, 0, 77), (0.01, 0.20, 0.20), MAT["hudglass"], rot=(0, -20, 0), shadows=False)
for side in (-1, 1):
    acs(f"CP_Console_{side}", "Cube", (470, side * 42, 36), (1.3, 0.16, 0.08), MAT["cockpit"])
acs("CP_ThrottleSlot", "Cube", (470, -42, 40.5), (0.5, 0.03, 0.01), MAT["dark"])
acs("CP_RudderWell", "Cube", (600, 0, -4), (0.3, 0.6, 0.02), MAT["dark"])

# stick: pivot at the base, between the knees. sim_client rotates the pivot: roll = +ail*18 (top to the right),
# pitch = -elev*14 (+elev = push = top forward)
stick = ac("StickPivot", None, MAT["dark"], (520, 0, 8), tags=("StickPivot",))
acs("CP_StickBoot", "Sphere", (520, 0, 10), (0.12, 0.12, 0.05), MAT["seat"], parent=stick)
acs("CP_StickShaft", "Cylinder", (520, 0, 32), (0.036, 0.036, 0.46), MAT["dark"], parent=stick)
acs("CP_StickGrip", "Cylinder", (521, 0, 60), (0.055, 0.05, 0.13), MAT["seat"], rot=(0, -12, 0), parent=stick)
acs("CP_StickButton", "Sphere", (523, 0, 67.5), (0.025, 0.025, 0.02), MAT["red"], parent=stick)
acs("CP_StickTrigger", "Cube", (524.5, 0, 60), (0.012, 0.012, 0.03), MAT["metal"], parent=stick)
# throttle: lever on the left console, pivot under the slot; pitch = 25 - 50*thr (forward = more thrust)
thr = ac("ThrottlePivot", None, MAT["dark"], (470, -42, 32), tags=("ThrottlePivot",))
acs("CP_ThrottleLever", "Cylinder", (470, -42, 46), (0.04, 0.04, 0.28), MAT["metal"], parent=thr)
acs("CP_ThrottleGrip", "Cube", (471, -42, 62), (0.10, 0.07, 0.12), MAT["seat"], parent=thr)
acs("CP_ThrottleButton", "Sphere", (476, -40, 66), (0.025, 0.025, 0.025), MAT["red"], parent=thr)
# rudder pedals: pivot at the heel; x moves +-6 cm with rudder, toe brake tilts the plate forward (pitch -18*brk)
for side, tag in ((-1, "PedalL"), (1, "PedalR")):
    p = ac(tag, None, MAT["dark"], (600, side * 18, 2), tags=(tag,))
    acs(f"CP_{tag}_Plate", "Cube", (600, side * 18, 15), (0.03, 0.11, 0.24), MAT["metal"], rot=(0, -18, 0), parent=p)
    acs(f"CP_{tag}_Toe", "Cube", (603, side * 18, 25), (0.025, 0.12, 0.05), MAT["yellow"], rot=(0, -18, 0), parent=p)
    acs(f"CP_{tag}_Arm", "Cylinder", (608, side * 18, 4), (0.03, 0.03, 0.16), MAT["dark"], rot=(0, 90, 0), parent=p)
log("aircraft done")

# =====================================================================================================================
# camera rig (tag SimCamera, moved by sim_client) carrying the view camera (tag SimView) and the world-space overlays.
# The CameraActor's root is its camera component, which the HMD drives in VR (and the monitor head look rotates),
# so the overlays hang on the rig, not on the camera.
cam = place("SimCameraRig", None, EYE, MAT["dark"], movable=True, shadows=False, tags=("SimCamera",))
view = eas.spawn_actor_from_class(unreal.CameraActor, V(*EYE), unreal.Rotator(roll=0, pitch=0, yaw=0))
view.set_actor_label("SimView")
view.tags = [unreal.Name("SimView")]
attach(view, cam)
cc = view.camera_component
cc.set_editor_property("field_of_view", 75.0)
cc.set_editor_property("constrain_aspect_ratio", False)
try:
    cc.set_editor_property("lock_to_hmd", True)
except Exception as e:
    log("lock_to_hmd", e)
view.set_editor_property("auto_activate_for_player", unreal.AutoReceiveInput.PLAYER0)
try:
    view.root_component.set_mobility(unreal.ComponentMobility.MOVABLE)
except Exception:
    pass


def hud_text(tag, loc, size, align=unreal.HorizTextAligment.EHTA_CENTER, color=(30, 255, 80)):
    t = eas.spawn_actor_from_class(unreal.TextRenderActor, V(EYE[0] + loc[0], loc[1], EYE[2] + loc[2]), unreal.Rotator(yaw=180.0))
    t.set_actor_label(tag)
    t.tags = [unreal.Name(tag), unreal.Name("Overlay")]
    tc = t.text_render
    tc.set_mobility(unreal.ComponentMobility.MOVABLE)
    tc.set_editor_property("text", tag)
    tc.set_editor_property("world_size", size)
    tc.set_editor_property("horizontal_alignment", align)
    tc.set_editor_property("vertical_alignment", unreal.VerticalTextAligment.EVRTA_TEXT_CENTER)
    tc.set_editor_property("text_render_color", unreal.Color(r=color[0], g=color[1], b=color[2], a=255))
    tc.set_editor_property("cast_shadow", False)
    tc.set_editor_property("text_material", MAT["hudtext"])
    attach(t, cam)
    return t


# offsets from the eye (fwd, right, up), cm. HUD on the combiner (~130 cm), status line lower.
hud_text("HUD_SPD", (130, -20, 4), 2.2, unreal.HorizTextAligment.EHTA_RIGHT)
hud_text("HUD_ALT", (130, 20, 4), 2.2, unreal.HorizTextAligment.EHTA_LEFT)
hud_text("HUD_HDG", (130, 0, 15), 2.0)
hud_text("HUD_MID", (130, 0, -2), 1.6)
hud_text("HUD_STAT", (130, -2, -12), 1.5, unreal.HorizTextAligment.EHTA_LEFT, color=(200, 230, 255))
PANEL_LOC = V(EYE[0] + 92, -34, EYE[2] - 19)
prot = unreal.MathLibrary.make_rot_from_zx(V(*EYE) - PANEL_LOC, V(0, 1, 0))      # plane normal (Z) toward the eye, X to the right
panel = place("TutorPanel", SHAPE["Plane"], (PANEL_LOC.x, PANEL_LOC.y, PANEL_LOC.z), MAT["panel"], rot=(prot.roll, prot.pitch, prot.yaw),
              scale=(0.46, 0.23, 1), movable=True, shadows=False, tags=("TutorPanel", "Overlay"))
attach(panel, cam)
log("camera + overlays done")

# ---- world settings ----------------------------------------------------------------------------------------------
ws = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_editor_world().get_world_settings()
try:
    ws.set_editor_property("default_game_mode", unreal.GameModeBase)
except Exception as e:
    log("game mode override skipped", e)

ok = les.save_current_level()
log("saved", MAP, ok, "actors", len(eas.get_all_level_actors()))
