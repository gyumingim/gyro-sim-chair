"""Builds /Game/Maps/FlightMap: Cesium globe at Cheongju Air Base (RKTU), photo-textured runways, sky, the FlightGear
F-16 exterior (chase view) with OUR OWN cockpit inside (Art/Cockpit, made by Scripts/cockpit/build_cockpit.py with
Blender: centre stick / left throttle / pedals at the physical rig's positions, live standby needles, gear handle),
world-space HUD / MFD screens / tutorial panel.

Before the first build (once per checkout, see unreal/README.md):
  powershell -ExecutionPolicy Bypass -File Scripts\\install_cesium.ps1    (Cesium for Unreal plugin, not in git)
  python Scripts\\fetch_f16_model.py                                      (F-16 model -> ThirdParty/f16_obj, GPL-2.0)
  python Scripts\\fetch_textures.py                                       (Poly Haven CC0 photo textures)
Run headless (editor closed):
  "C:\\Program Files\\Epic Games\\UE_5.8\\Engine\\Binaries\\Win64\\UnrealEditor-Cmd.exe" ^
      <path>\\GyroSim.uproject -run=pythonscript -script=<path>\\Scripts\\build_level.py -unattended -nosplash
or inside the open editor (Python console):  exec(open(r"<path>/Scripts/build_level.py").read())

Units cm. World X = north, Y = east, Z = up; origin = sim start point (sim/airfield.py LAT0/LON0, 150 m down runway
06R) at ellipsoid height GEOID_N, i.e. Z 0 = mean sea level there (geo.py). Runways are placed exactly on their real
coordinates (OpenStreetMap) and follow the Earth's curvature like JSBSim's ground (field elevation 191 ft).
Third-party content is imported to /Game/ThirdParty (not in git - .gitignore); licenses in ATTRIBUTION.md.

Actors with tags used by sim_client: Aircraft, AircraftPart, Gear, Canopy, Cockpit, StickPivot, ThrottlePivot, PedalL,
PedalR, GearHandle, GearLights, Needle_asi / Needle_alt / Needle_alt10k / Needle_vsi, ADIBall, SimCamera (rig),
SimView (camera), HUD (plane), MFD_L / MFD_R (screens), TutorPanel, KeyPanel, CesiumGeoreference, CesiumGround.
"""
import json, math, os, sys
import unreal

PROJ = unreal.Paths.convert_relative_path_to_full(unreal.Paths.project_dir())
REPO = os.path.normpath(os.path.join(PROJ, "..", ".."))
sys.path.insert(0, os.path.join(REPO, "sim"))
sys.path.insert(0, os.path.join(PROJ, "Content", "Python"))
import airfield as AF                       # noqa: E402
import geo                                  # noqa: E402

MAP = "/Game/Maps/FlightMap"
MAT_DIR = "/Game/Materials"
MESH_DIR = "/Game/Meshes"
TP = "/Game/ThirdParty"
F16_SRC = os.path.join(PROJ, "ThirdParty", "f16_obj")
CK_SRC = os.path.join(PROJ, "Art", "Cockpit")               # our cockpit (FBX + textures + manifest, in git)
CK = "/Game/Cockpit"
PH_SRC = os.path.join(PROJ, "ThirdParty", "polyhaven")
log = lambda *a: unreal.log("[build_level] " + " ".join(str(x) for x in a))

eas = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
les = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
EAL = unreal.EditorAssetLibrary
assets = unreal.AssetToolsHelpers.get_asset_tools()
MEL = unreal.MaterialEditingLibrary
GP = unreal.GeometryScript_Primitives
V, R2 = unreal.Vector, unreal.Vector2D
SHAPE = {n: unreal.load_asset(f"/Engine/BasicShapes/{n}.{n}") for n in ("Plane", "Cube", "Cylinder", "Cone", "Sphere")}
EYE = (430.0, 0.0, 100.0)            # must match sim_client.EYE (= FlightGear F-16 pilot eye point)
FRAME = geo.Frame(AF.LAT0, AF.LON0, AF.GEOID_N)
H_FIELD = AF.FIELD_M + AF.GEOID_N    # ellipsoid height of the runway surface (= JSBSim ground)
HAS_CESIUM = hasattr(unreal, "CesiumGeoreference") and hasattr(unreal, "Cesium3DTileset")


# =====================================================================================================================
# materials
def _new_material(name, folder=MAT_DIR):
    path = f"{folder}/{name}"
    if EAL.does_asset_exist(path):
        m = unreal.load_asset(path)
        MEL.delete_all_material_expressions(m)
        return m
    return assets.create_asset(name, folder, unreal.Material, unreal.MaterialFactoryNew())


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


def _tex_sample(m, tex, uv, x, y, param=None):
    if param:
        s = _expr(m, unreal.MaterialExpressionTextureSampleParameter2D, x, y, parameter_name=param)
    else:
        s = _expr(m, unreal.MaterialExpressionTextureSample, x, y)
    s.set_editor_property("texture", tex)
    s.set_editor_property("sampler_type", _sampler_type(tex))
    if uv is not None:
        MEL.connect_material_expressions(uv, "", s, "UVs")
    return s


def _op(m, cls, a, b, x, y, a_out="", b_out=""):
    e = _expr(m, cls, x, y)
    MEL.connect_material_expressions(a, a_out, e, "A")
    MEL.connect_material_expressions(b, b_out, e, "B")
    return e


def _sparam(m, n, v, x, y):
    return _expr(m, unreal.MaterialExpressionScalarParameter, x, y, parameter_name=n, default_value=v)


def _vparam(m, n, c, x, y):
    return _expr(m, unreal.MaterialExpressionVectorParameter, x, y, parameter_name=n, default_value=unreal.LinearColor(c[0], c[1], c[2], 1.0))


def simple_material(name, rgb, rough=0.8, metal=0.0, emissive=0.0, two_sided=False):
    m = _new_material(name)
    c = _const3(m, rgb, -500, 0)
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


def _after_tsr(m):
    """translucent, composited after motion blur / TSR (camera-locked overlays would ghost otherwise)."""
    m.set_editor_property("shading_model", unreal.MaterialShadingModel.MSM_UNLIT)
    m.set_editor_property("blend_mode", unreal.BlendMode.BLEND_TRANSLUCENT)
    try:
        m.set_editor_property("translucency_pass", unreal.MaterialTranslucencyPass.MTP_AFTER_MOTION_BLUR)
    except Exception as e:
        log("translucency pass", e)


LADDER_HLSL = """
float u = (2.0 * UV.x - 1.0) * T;
float w = T0 + (1.0 - 2.0 * UV.y) * T;
float3 d = normalize(float3(1.0, u, w));
float cr = cos(Roll), sr = sin(Roll);
float y1 = d.y * cr + d.z * sr;
float z1 = -d.y * sr + d.z * cr;
float ct = cos(Pitch), st = sin(Pitch);
float x = d.x * ct - z1 * st;
float z = d.x * st + z1 * ct;
float el = degrees(asin(clamp(z, -1.0, 1.0)));
float az = degrees(atan2(y1, x));
return float2((az + AzMax) / (2.0 * AzMax), (90.0 - el) / 180.0);
"""


def screen_material(name, no_depth=False, bright=1.0, ladder=False):
    """Unlit screen: emissive = texture parameter 'Tex' (tutorial PNG / canvas render target) x Brightness,
    opacity = 'Opacity' param x (TexAlpha ? coverage from the colour : 1). no_depth = drawn over the cockpit (HUD, collimated look)."""
    m = _new_material(name)
    _after_tsr(m)
    if no_depth:
        m.set_editor_property("disable_depth_test", True)
    t = _expr(m, unreal.MaterialExpressionTextureSampleParameter2D, -800, 0, parameter_name="Tex")
    tex = unreal.load_asset("/Engine/EngineResources/Black")
    t.set_editor_property("texture", tex)
    t.set_editor_property("sampler_type", _sampler_type(tex))
    if ladder:
        # pitch ladder: a static atlas (render target 'Ladder', azimuth x elevation in the level frame) looked up per
        # pixel from the aircraft roll / pitch (radians, params Roll / Pitch) - conformal, no per-frame drawing.
        cu = _expr(m, unreal.MaterialExpressionCustom, -1300, -400)
        cu.set_editor_property("code", LADDER_HLSL)
        cu.set_editor_property("output_type", unreal.CustomMaterialOutputType.CMOT_FLOAT2)
        ins = []
        for n in ("UV", "Roll", "Pitch", "T", "T0", "AzMax"):
            ci = unreal.CustomInput()
            ci.set_editor_property("input_name", n)
            ins.append(ci)
        cu.set_editor_property("inputs", ins)
        MEL.connect_material_expressions(_expr(m, unreal.MaterialExpressionTextureCoordinate, -1500, -500), "", cu, "UV")
        MEL.connect_material_expressions(_sparam(m, "Roll", 0.0, -1500, -420), "", cu, "Roll")
        MEL.connect_material_expressions(_sparam(m, "Pitch", 0.0, -1500, -340), "", cu, "Pitch")
        MEL.connect_material_expressions(_sparam(m, "T", math.tan(math.radians(14.0)), -1500, -260), "", cu, "T")
        MEL.connect_material_expressions(_sparam(m, "T0", math.tan(math.radians(-6.0)), -1500, -180), "", cu, "T0")
        MEL.connect_material_expressions(_sparam(m, "AzMax", 16.0, -1500, -100), "", cu, "AzMax")
        lt = _expr(m, unreal.MaterialExpressionTextureSampleParameter2D, -1000, -400, parameter_name="Ladder")
        lt.set_editor_property("texture", tex)
        lt.set_editor_property("sampler_type", _sampler_type(tex))
        lt.set_editor_property("sampler_source", unreal.SamplerSourceMode.SSM_CLAMP_WORLD_GROUP_SETTINGS)
        MEL.connect_material_expressions(cu, "", lt, "UVs")
        lm = _op(m, unreal.MaterialExpressionMultiply, lt, _sparam(m, "LadderOn", 1.0, -1000, -250), -800, -350)
        t = _op(m, unreal.MaterialExpressionAdd, t, lm, -650, -100)
    e = _op(m, unreal.MaterialExpressionMultiply, t, _sparam(m, "Brightness", bright, -800, 250), -500, 0)
    MEL.connect_material_property(e, "", unreal.MaterialProperty.MP_EMISSIVE_COLOR)
    # coverage from colour (canvas text does not write alpha): saturate((r + g + b) * 2)
    t3 = _expr(m, unreal.MaterialExpressionComponentMask, -700, 380, r=True, g=True, b=True, a=False)
    MEL.connect_material_expressions(t, "", t3, "")
    rgb = _op(m, unreal.MaterialExpressionDotProduct, t3, _const3(m, (1, 1, 1), -700, 480), -550, 380)
    cov = _expr(m, unreal.MaterialExpressionSaturate, -350, 380)
    MEL.connect_material_expressions(_op(m, unreal.MaterialExpressionMultiply, rgb, _const(m, 2.0, -650, 480), -450, 380), "", cov, "")
    a = _expr(m, unreal.MaterialExpressionLinearInterpolate, -500, 300)
    MEL.connect_material_expressions(_const(m, 1.0, -800, 350), "", a, "A")
    MEL.connect_material_expressions(cov, "", a, "B")
    MEL.connect_material_expressions(_sparam(m, "TexAlpha", 0.0, -800, 450), "", a, "Alpha")
    op = _op(m, unreal.MaterialExpressionMultiply, a, _sparam(m, "Opacity", 1.0, -800, 550), -300, 300)
    MEL.connect_material_property(op, "", unreal.MaterialProperty.MP_OPACITY)
    return _finish(m)


GRID_HLSL = """
// countryside from the air (no texture, nothing streamed): irregular fields with crop rows and hedges, forest
// patches, large-scale brightness variation. Every detail fades out by its pixel footprint (fwidth) -> no moire.
float2 p = WP.xy / 100.0;                                  // metres
float nz[3];
float scl[3] = {1.0 / 700.0, 1.0 / 2600.0, 1.0 / 9000.0};
[unroll] for (int k = 0; k < 3; k++) {
    float2 x = p * scl[k] + k * 13.7;
    float2 i = floor(x); float2 f = frac(x); f = f * f * (3.0 - 2.0 * f);
    float a = frac(sin(dot(i, float2(127.1, 311.7))) * 43758.5453);
    float b = frac(sin(dot(i + float2(1, 0), float2(127.1, 311.7))) * 43758.5453);
    float c = frac(sin(dot(i + float2(0, 1), float2(127.1, 311.7))) * 43758.5453);
    float d = frac(sin(dot(i + float2(1, 1), float2(127.1, 311.7))) * 43758.5453);
    nz[k] = lerp(lerp(a, b, f.x), lerp(c, d, f.x), f.y);
}
float FS = 380.0;                                           // field size, m
float2 q = p / FS + (float2(nz[0], nz[1]) - 0.5) * 0.9;
float2 cell = floor(q);
float2 fr = frac(q);
float h = frac(sin(dot(cell, float2(41.3, 289.1))) * 43758.5453);
float h2 = frac(sin(dot(cell, float2(17.9, 93.7))) * 24634.6345);
float3 col = h < 0.30 ? float3(0.075, 0.115, 0.035) : h < 0.50 ? float3(0.115, 0.125, 0.045) : h < 0.65 ? float3(0.135, 0.115, 0.065)
           : h < 0.82 ? float3(0.055, 0.085, 0.030) : float3(0.095, 0.085, 0.060);
col *= 0.85 + 0.3 * h2;
// crop rows inside a field (6 m period, direction per field)
float ang = h2 * 3.14159;
float r = dot(p, float2(cos(ang), sin(ang))) / 6.0;
float rw = fwidth(r);
float rows = (0.5 + 0.5 * sin(r * 6.28318)) * saturate(1.0 - rw * 2.5);
col *= 1.0 - 0.18 * rows;
// hedges / tracks between fields (about 4 m)
float2 e = min(fr, 1.0 - fr) * FS;
float2 ew = max(fwidth(q) * FS, 1e-3);
float edge = max(saturate((4.0 - e.x) / ew.x), saturate((4.0 - e.y) / ew.y)) * saturate(4.0 / max(ew.x, ew.y));
col = lerp(col, float3(0.045, 0.06, 0.03), edge * 0.8);
// forest and hills (dark), villages (light grey), large brightness variation
float forest = smoothstep(0.58, 0.66, nz[2] * 0.7 + nz[1] * 0.3);
col = lerp(col, float3(0.03, 0.05, 0.022), forest);
float town = smoothstep(0.86, 0.9, h * (0.6 + 0.4 * nz[1])) * (1.0 - forest);
col = lerp(col, float3(0.16, 0.15, 0.14), town * 0.8);
col *= 0.8 + 0.4 * nz[1];
return col;
"""


def grid_material():
    """M_Grid (name kept, the ground mesh is still 'GridGround'): procedural countryside - irregular fields, crop rows,
    hedges, forest and villages - computed from the world position (no texture). Replaced the debug grid look
    (review 2026-11-04: 'grid ground at altitude' was the worst visual problem)."""
    m = _new_material("M_Grid")
    wp = _expr(m, unreal.MaterialExpressionWorldPosition, -1400, 0)
    cu = _expr(m, unreal.MaterialExpressionCustom, -1100, 0)
    cu.set_editor_property("code", GRID_HLSL)
    cu.set_editor_property("output_type", unreal.CustomMaterialOutputType.CMOT_FLOAT3)
    ci = unreal.CustomInput()
    ci.set_editor_property("input_name", "WP")
    cu.set_editor_property("inputs", [ci])
    MEL.connect_material_expressions(wp, "", cu, "WP")
    MEL.connect_material_property(cu, "", unreal.MaterialProperty.MP_BASE_COLOR)
    MEL.connect_material_property(_const(m, 0.92, -400, 200), "", unreal.MaterialProperty.MP_ROUGHNESS)
    MEL.connect_material_property(_const(m, 0.15, -400, 280), "", unreal.MaterialProperty.MP_SPECULAR)
    return _finish(m)


def photo_master():
    """M_Photo: world-aligned photo texture (Poly Haven colour / normal / roughness), tile size param 'TileCm', large
    scale brightness variation so the tiling does not show from the air. Parameters: Diff, Nor, Rough, TileCm, Tint."""
    m = _new_material("M_Photo")
    wp = _expr(m, unreal.MaterialExpressionWorldPosition, -2000, 0)
    xy = _expr(m, unreal.MaterialExpressionComponentMask, -1800, 0, r=True, g=True, b=False, a=False)
    MEL.connect_material_expressions(wp, "", xy, "")
    uv = _op(m, unreal.MaterialExpressionDivide, xy, _sparam(m, "TileCm", 300.0, -1800, 120), -1600, 0)
    uvm = _op(m, unreal.MaterialExpressionDivide, xy, _const(m, 60000.0, -1800, 220), -1600, 200)
    dflt = unreal.load_asset("/Engine/EngineMaterials/DefaultDiffuse")
    nflt = unreal.load_asset("/Engine/EngineMaterials/DefaultNormal")
    gflt = unreal.load_asset("/Engine/EngineMaterials/T_Default_MacroVariation")
    d = _tex_sample(m, dflt, uv, -1300, -200, "Diff")
    n = _tex_sample(m, nflt, uv, -1300, 100, "Nor")
    r = _expr(m, unreal.MaterialExpressionTextureSampleParameter2D, -1300, 400, parameter_name="Rough")
    r.set_editor_property("texture", gflt)
    r.set_editor_property("sampler_type", _sampler_type(gflt))
    MEL.connect_material_expressions(uv, "", r, "UVs")
    mac = _tex_sample(m, gflt, uvm, -1300, 650)
    mac2 = _op(m, unreal.MaterialExpressionAdd, _op(m, unreal.MaterialExpressionMultiply, mac, _const(m, 0.5, -1100, 750), -950, 650, "R"),
               _const(m, 0.75, -1100, 850), -800, 650)
    col = _op(m, unreal.MaterialExpressionMultiply, _op(m, unreal.MaterialExpressionMultiply, d, _vparam(m, "Tint", (1, 1, 1), -1100, -300), -900, -200),
              mac2, -600, -100)
    ds = _expr(m, unreal.MaterialExpressionDesaturation, -400, -100)
    MEL.connect_material_expressions(col, "", ds, "")
    MEL.connect_material_expressions(_sparam(m, "Desat", 0.0, -600, 0), "", ds, "Fraction")
    MEL.connect_material_property(ds, "", unreal.MaterialProperty.MP_BASE_COLOR)
    MEL.connect_material_property(n, "", unreal.MaterialProperty.MP_NORMAL)
    MEL.connect_material_property(r, "R", unreal.MaterialProperty.MP_ROUGHNESS)
    MEL.connect_material_property(_const(m, 0.3, -600, 500), "", unreal.MaterialProperty.MP_SPECULAR)
    return _finish(m)


def f16_master(name, masked=False, textured=True):
    """M_F16Tex / M_F16Masked / M_F16Color: FlightGear F-16 surfaces. Params Tex, Tint, Rough, Metal, Emissive."""
    m = _new_material(name)
    m.set_editor_property("two_sided", True)
    tint = _vparam(m, "Tint", (1, 1, 1), -900, -300)
    if textured:
        t = _expr(m, unreal.MaterialExpressionTextureSampleParameter2D, -900, 0, parameter_name="Tex")
        tex = unreal.load_asset("/Engine/EngineMaterials/DefaultDiffuse")
        t.set_editor_property("texture", tex)
        t.set_editor_property("sampler_type", unreal.MaterialSamplerType.SAMPLERTYPE_COLOR)
        col = _op(m, unreal.MaterialExpressionMultiply, t, tint, -600, -100)
        if masked:
            m.set_editor_property("blend_mode", unreal.BlendMode.BLEND_MASKED)
            MEL.connect_material_property(t, "A", unreal.MaterialProperty.MP_OPACITY_MASK)
            m.set_editor_property("opacity_mask_clip_value", 0.4)
    else:
        col = tint
    MEL.connect_material_property(col, "", unreal.MaterialProperty.MP_BASE_COLOR)
    MEL.connect_material_property(_sparam(m, "Rough", 0.55, -600, 200), "", unreal.MaterialProperty.MP_ROUGHNESS)
    MEL.connect_material_property(_sparam(m, "Metal", 0.0, -600, 300), "", unreal.MaterialProperty.MP_METALLIC)
    em = _op(m, unreal.MaterialExpressionMultiply, col, _sparam(m, "Emissive", 0.0, -800, 450), -400, 450)
    MEL.connect_material_property(em, "", unreal.MaterialProperty.MP_EMISSIVE_COLOR)
    return _finish(m)


def instance(name, parent, scalars=None, colors=None, textures=None, folder=MAT_DIR):
    path = f"{folder}/{name}"
    mi = unreal.load_asset(path) if EAL.does_asset_exist(path) else \
        assets.create_asset(name, folder, unreal.MaterialInstanceConstant, unreal.MaterialInstanceConstantFactoryNew())
    MEL.set_material_instance_parent(mi, parent)
    MEL.clear_all_material_instance_parameters(mi)
    for k, v in (scalars or {}).items():
        MEL.set_material_instance_scalar_parameter_value(mi, k, v)
    for k, c in (colors or {}).items():
        MEL.set_material_instance_vector_parameter_value(mi, k, unreal.LinearColor(c[0], c[1], c[2], 1.0))
    for k, t in (textures or {}).items():
        MEL.set_material_instance_texture_parameter_value(mi, k, t)
    MEL.update_material_instance(mi)
    EAL.save_loaded_asset(mi)
    return mi


def import_textures(files, dest, kinds=None):
    """files = [abs path]; kinds[path] = 'normal' | 'linear' | 'color'. Returns {basename_noext: Texture2D}."""
    tasks = []
    for f in files:
        t = unreal.AssetImportTask()
        t.filename = f
        t.destination_path = dest
        t.automated = True
        t.replace_existing = True
        t.save = True
        tasks.append(t)
    assets.import_asset_tasks(tasks)
    out = {}
    for f in files:
        n = os.path.splitext(os.path.basename(f))[0].replace(".", "_")
        tex = unreal.load_asset(f"{dest}/{n}")
        if not tex:
            log("texture import failed", f)
            continue
        k = (kinds or {}).get(f, "color")
        if k == "normal":
            tex.set_editor_property("compression_settings", unreal.TextureCompressionSettings.TC_NORMALMAP)
            tex.set_editor_property("srgb", False)
        elif k == "linear":
            tex.set_editor_property("srgb", False)
        EAL.save_loaded_asset(tex)
        out[n] = tex
    return out


OBSOLETE = ["Meshes/" + n for n in ("SM_Canopy", "SM_CanopyBow300", "SM_Fields0", "SM_Fields1", "SM_Fields2", "SM_Fin", "SM_Forests",
                                     "SM_FusAft", "SM_FusNose", "SM_FusTub", "SM_GroundRing", "SM_HTail0", "SM_HTail2", "SM_RunwayMarks",
                                     "SM_Terrain", "SM_Towns", "SM_Wing")] +            ["Materials/" + n for n in ("MI_Asphalt", "MI_Concrete", "MI_Field1", "MI_Field2", "MI_Field3", "MI_Grass", "MI_Terrain", "MI_Trees",
                                       "M_Body", "M_BodyDark", "M_Cockpit", "M_HUDText", "M_MFD", "M_Metal", "M_NavGreen", "M_NavRed", "M_Red",
                                       "M_Seat", "M_Yellow", "M_Surface")]
for n in OBSOLETE:
    if EAL.does_asset_exist("/Game/" + n):
        EAL.delete_asset("/Game/" + n)
log("materials ...")
MAT = dict(
    mark=simple_material("M_Mark", (0.75, 0.75, 0.72), 0.7),
    dark=simple_material("M_Dark", (0.035, 0.035, 0.04), 0.55, two_sided=True),
    ground=simple_material("M_FlatGround", (0.07, 0.10, 0.04), 0.95),
    canopy=glass_material("M_Canopy", (0.30, 0.27, 0.15), 0.06),
    hudglass=glass_material("M_HUDGlass", (0.3, 0.45, 0.35), 0.03),
    panel=screen_material("M_TutorPanel"),
    hud=screen_material("M_HUD", no_depth=True, bright=1.0, ladder=True),
    mfd=screen_material("M_MFDScreen"),
)
PHOTO = photo_master()
MAT["grid"] = grid_material()
for role, aid, tile, tint, desat in (("runway", "concrete_pavement", 180.0, (0.8, 0.82, 0.86), 0.75), ("taxiway", "asphalt_02", 400.0, (1, 1, 1), 0.3),
                                     ("grass", "leafy_grass", 250.0, (0.36, 0.5, 0.3), 0.2)):
    d = os.path.join(PH_SRC, aid)
    fs = {k: os.path.join(d, f"{aid}_{k}.jpg") for k in ("diff", "nor", "rough")}
    if all(os.path.exists(f) for f in fs.values()):
        tx = import_textures(list(fs.values()), f"{TP}/PolyHaven/{aid}", {fs["nor"]: "normal", fs["rough"]: "linear"})
        get = lambda k: tx.get(os.path.splitext(os.path.basename(fs[k]))[0])
        MAT[role] = instance(f"MI_{role.capitalize()}", PHOTO, dict(TileCm=tile, Desat=desat), dict(Tint=tint),
                             dict(Diff=get("diff"), Nor=get("nor"), Rough=get("rough")), folder=f"{TP}/PolyHaven")
    else:
        log("Poly Haven texture missing (run Scripts/fetch_textures.py):", aid)
        MAT[role] = simple_material(f"M_{role.capitalize()}Plain", {"runway": (0.25, 0.25, 0.24), "taxiway": (0.06, 0.06, 0.065),
                                                                     "grass": (0.06, 0.12, 0.04)}[role], 0.9)
log("materials done")


# =====================================================================================================================
# Geometry Script helpers
def gs_opts():
    return unreal.GeometryScriptPrimitiveOptions()


def save_mesh(dm, name, recompute_normals=True):
    path = f"{MESH_DIR}/{name}"
    if recompute_normals:
        unreal.GeometryScript_Normals.recompute_normals(dm, unreal.GeometryScriptCalculateNormalsOptions())
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
        o.set_editor_property("enable_nanite", False)
        sm, _ = unreal.GeometryScript_NewAssetUtils.create_new_static_mesh_asset_from_mesh(dm, path, o)
    if sm:
        EAL.save_loaded_asset(sm)
    return sm


def geo_mesh(dm, rwy, dz_cm):
    """vertices in runway axes (x = m past the threshold, y = m right of the centre line, z ignored) -> world cm on the
    curved Earth at field elevation + dz_cm (same surface JSBSim rolls on)."""
    _, pts, _gaps = unreal.GeometryScript_MeshQueries.get_all_vertex_positions(dm, False)
    arr = unreal.GeometryScript_List.convert_vector_list_to_array(pts)
    out = []
    for p in arr:
        lat, lon = AF.rwy_point(p.x, p.y, rwy)
        out.append(V(*FRAME.world(lat, lon, H_FIELD + (p.z + dz_cm) / 100.0)))
    unreal.GeometryScript_MeshEdits.set_all_mesh_vertex_positions(dm, unreal.GeometryScript_List.convert_array_to_vector_list(out))
    return dm


def rect(dm, x0, x1, y0, y1, nx=0, ny=0):
    """rectangle in runway axes (metres), subdivided nx x ny."""
    GP.append_rectangle_xy(dm, gs_opts(), unreal.Transform(location=V((x0 + x1) / 2, (y0 + y1) / 2, 0)), x1 - x0, y1 - y0, nx, ny)


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
        if mat is not None:
            for i in range(max(1, c.get_num_materials())):
                c.set_material(i, mat)
    a.set_actor_scale3d(V(*scale))
    c.set_editor_property("cast_shadow", shadows)
    c.set_collision_enabled(unreal.CollisionEnabled.NO_COLLISION)
    if tags:
        a.tags = [unreal.Name(t) for t in tags]
    return a


# =====================================================================================================================
# Cesium globe (terrain + imagery set up at Play by sim_client: ion token -> Cesium World Terrain + Bing aerial,
# no token -> WGS84 ellipsoid raised to the field elevation + Sentinel-2 cloudless imagery)
if HAS_CESIUM:
    gr = eas.spawn_actor_from_class(unreal.CesiumGeoreference, V(0, 0, 0))
    gr.set_actor_label("CesiumGeoreference")
    gr.tags = [unreal.Name("CesiumGeoreference")]
    gr.set_origin_longitude_latitude_height(V(AF.LON0, AF.LAT0, AF.GEOID_N))
    ts = eas.spawn_actor_from_class(unreal.Cesium3DTileset, V(0, 0, 0))
    ts.set_actor_label("CesiumGround")
    ts.tags = [unreal.Name("CesiumGround")]
    try:
        ts.root_component.set_mobility(unreal.ComponentMobility.MOVABLE)
    except Exception as e:
        log("tileset mobility", e)
    ts.set_georeference(gr)
    # off by default (no tile streaming, ground = grid). sim_client switches it on for the photo / terrain modes.
    ts.set_editor_property("tileset_source", unreal.TilesetSource.FROM_URL)
    ts.set_editor_property("url", "")
    # Cesium's frame is X east / Y south; this project's is X north / Y east -> yaw +90. Ellipsoid raised to the field.
    ts.set_actor_location_and_rotation(V(0, 0, (H_FIELD - AF.GEOID_N) * 100.0 - 30.0), unreal.Rotator(yaw=90.0), False, True)
    for k, v in (("maximum_screen_space_error", 8.0), ("show_credits_on_screen", True)):
        try:
            ts.set_editor_property(k, v)
        except Exception as e:
            log("tileset", k, e)
    # raster overlays (components added like in the Details panel): Sentinel-2 cloudless (EOX, no login, active in the
    # map) and Bing aerial via Cesium ion (inactive; sim_client turns it on when Config/cesium_token.txt exists)
    sds = unreal.get_engine_subsystem(unreal.SubobjectDataSubsystem)
    SDL = unreal.SubobjectDataBlueprintFunctionLibrary

    def add_comp(actor, cls, props):
        root_h = sds.k2_gather_subobject_data_for_instance(actor)[0]
        h, fail = sds.add_new_subobject(unreal.AddNewSubobjectParams(parent_handle=root_h, new_class=cls))
        c = SDL.get_object(SDL.get_data(h))
        for k, v in props.items():
            c.set_editor_property(k, v)
        return c
    add_comp(ts, unreal.CesiumUrlTemplateRasterOverlay, dict(
        template_url="https://tiles.maps.eox.at/wmts/1.0.0/s2cloudless-2024_3857/default/g/{z}/{reverseY}/{x}.jpg",
        maximum_level=15, material_layer_key="Overlay0", auto_activate=False))
    add_comp(ts, unreal.CesiumIonRasterOverlay, dict(ion_asset_id=0, material_layer_key="Overlay1", auto_activate=False))   # asset 2 set at Play
    log("Cesium georeference + ground tileset placed, overlays",
        [c.get_class().get_name() for c in ts.get_components_by_class(unreal.CesiumRasterOverlay)])
else:
    log("Cesium for Unreal not loaded - grid ground only (run Scripts/install_cesium.ps1 for real terrain)")

# grid ground (default; local mesh, nothing streamed): 600 km square on the curved Earth at the field elevation
# (= JSBSim's ground), 200 x 200 cells, dense in the middle (first cell ~30 m), so it reaches the horizon.
GRID_R, GRID_N = 300000.0, 200
dm = unreal.DynamicMesh()
GP.append_rectangle_xy(dm, gs_opts(), unreal.Transform(), 2.0, 2.0, GRID_N, GRID_N)
_, pts, _gaps = unreal.GeometryScript_MeshQueries.get_all_vertex_positions(dm, False)
out = []
for p in unreal.GeometryScript_List.convert_vector_list_to_array(pts):
    n = GRID_R * math.copysign(p.x * p.x, p.x)
    e = GRID_R * math.copysign(p.y * p.y, p.y)
    lat, lon = AF.LAT0 + n / AF.M_LAT, AF.LON0 + e / AF.M_LON
    out.append(V(*FRAME.world(lat, lon, H_FIELD - 0.3)))
unreal.GeometryScript_MeshEdits.set_all_mesh_vertex_positions(dm, unreal.GeometryScript_List.convert_array_to_vector_list(out))
grid = place("GridGround", save_mesh(dm, "SM_GridGround"), (0, 0, 0), MAT["grid"], shadows=False, tags=("GridGround",))
grid.static_mesh_component.set_editor_property("affect_distance_field_lighting", False)
grid.static_mesh_component.set_mobility(unreal.ComponentMobility.MOVABLE)      # sim_client hides it in photo / terrain mode
log("grid ground done")

# ---- airfield: both RKTU runways on their real coordinates ----------------------------------------------------------
STEP = 100.0          # m, curvature sampling along the runway


def runway(rwy, ends):
    L, W = rwy["len_m"], rwy["w_m"]
    n = int(L / STEP)
    s = unreal.DynamicMesh(); rect(s, 0, L, -W / 2, W / 2, n, 2)
    a = place(f"Runway_{rwy['name']}", save_mesh(geo_mesh(s, rwy, 0.0), f"SM_Runway_{rwy['name']}"), (0, 0, 0), MAT["runway"], shadows=False)
    g = unreal.DynamicMesh()
    for y0, y1 in ((-W / 2 - 25, -W / 2), (W / 2, W / 2 + 25)):     # close-up grass shoulders; the satellite photo beyond
        rect(g, -60, L + 60, y0, y1, n + 2, 1)
    rect(g, -60, 0, -W / 2, W / 2, 1, 1)
    rect(g, L, L + 60, -W / 2, W / 2, 1, 1)
    place(f"Grass_{rwy['name']}", save_mesh(geo_mesh(g, rwy, -12.0), f"SM_Grass_{rwy['name']}"), (0, 0, 0), MAT["grass"], shadows=False)
    mk = unreal.DynamicMesh()

    def m(x0, x1, y0, y1):
        rect(mk, x0, x1, y0, y1, max(0, int((x1 - x0) / STEP)), 0)
    x = 30 + 60                                              # centre line: 30 m stripes, 20 m gaps (after the numbers)
    while x + 30 < L - 90:
        m(x, x + 30, -0.45, 0.45)
        x += 50
    for xs, sgn in ((6.0, 1), (L - 6.0, -1)):                # threshold piano keys (16 x 1.8 m) both ends
        for k in range(16):
            y = -W / 2 + 3 + k * (W - 6) / 15.0
            m(min(xs, xs + 30 * sgn), max(xs, xs + 30 * sgn), y - 0.9, y + 0.9)
    for xs in (300.0, L - 300.0 - 45):                       # aiming point
        for side in (-1, 1):
            m(xs, xs + 45, side * 6.5 - 2.5 + 0, side * 6.5 + 2.5)
    for xs in (150.0, 450.0, 600.0, L - 150 - 22.5, L - 450 - 22.5, L - 600 - 22.5):     # touchdown zone bars
        for side in (-1, 1):
            m(xs, xs + 22.5, side * 6.0 - 1.0, side * 6.0 + 1.0)
            m(xs, xs + 22.5, side * 9.5 - 1.0, side * 9.5 + 1.0)
    for side in (-1, 1):                                     # edge stripes
        m(0, L, side * (W / 2 - 1.2) - 0.45, side * (W / 2 - 1.2) + 0.45)
    place(f"RunwayMarks_{rwy['name']}", save_mesh(geo_mesh(mk, rwy, 2.0), f"SM_RunwayMarks_{rwy['name']}"), (0, 0, 0), MAT["mark"], shadows=False)
    for txt, along, yaw_add in ((ends[0], 50.0, 0.0), (ends[1], L - 50.0, 180.0)):
        lat, lon = AF.rwy_point(along, 0.0, rwy)
        p = FRAME.world(lat, lon, H_FIELD + 0.03)
        t = eas.spawn_actor_from_class(unreal.TextRenderActor, V(*p), unreal.Rotator(roll=0, pitch=90, yaw=rwy["hdg"] + yaw_add))
        t.set_actor_label(f"RunwayNumber_{txt}")
        tc = t.text_render
        tc.set_editor_property("text", txt)
        tc.set_editor_property("world_size", 1800.0)
        tc.set_editor_property("horizontal_alignment", unreal.HorizTextAligment.EHTA_CENTER)
        tc.set_editor_property("vertical_alignment", unreal.VerticalTextAligment.EVRTA_TEXT_CENTER)
        tc.set_editor_property("text_render_color", unreal.Color(r=200, g=200, b=195, a=255))
        tc.set_editor_property("cast_shadow", False)
    return a


runway(AF.RWY, ("06R", "24L"))
runway(AF.RWY2, ("06L", "24R"))
# parallel taxiway links between the runways (visual)
tw = unreal.DynamicMesh()
for along in (300.0, 1370.0, 2440.0):
    rect(tw, along - 11, along + 11, -AF.RWY["w_m"] / 2 - 175, -AF.RWY["w_m"] / 2, 1, 2)
place("TaxiLinks", save_mesh(geo_mesh(tw, AF.RWY, -1.0), "SM_TaxiLinks"), (0, 0, 0), MAT["taxiway"], shadows=False)
log("airfield done")

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
    sky.get_component_by_class(unreal.SkyAtmosphereComponent).set_editor_property("aerial_pespective_view_distance_scale", 0.6)  # sic
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
fc.set_editor_property("fog_density", 0.00002)
fc.set_editor_property("fog_height_falloff", 0.2)
try:
    fc.set_editor_property("fog_inscattering_luminance", unreal.LinearColor(0.35, 0.45, 0.6, 1.0))
except Exception:
    pass
# clouds: our instance of the engine's volumetric cloud material, scattered cumulus around the training altitude
# (bases CLOUD_BASE_KM ~ 3300 ft, tops up to ~ CLOUD_BASE_KM + CLOUD_TOP_KM): fly under, through and above them.
# Parameters tuned from screenshots (README "구름"); sample counts per quality preset in sim_client.PRESETS.
CLOUD_BASE_KM, CLOUD_TOP_KM = 1.0, 2.6
# picked from 4 screenshot variants (11-04, variant C): defined cumulus, scattered, some below / some above 6000 ft
CLOUD_PARAMS = dict(Cloud_GlobalCoverage=-0.22, Cloud_GlobalDensity=0.045, Layout_CloudGlobalScale=110.0)
CLOUD_VECTORS = dict(Noise_Strength=(1.3, 0.15, 0.05, 2.5), Layout_CloudType=(1.0, 1.0, 1.0, 3.0))
cloud_parent = unreal.load_asset("/Engine/EngineSky/VolumetricClouds/m_SimpleVolumetricCloud_Inst")
cloud_mat = instance("MI_Clouds", cloud_parent, CLOUD_PARAMS, None, None) if cloud_parent else None
if cloud_mat:
    for k, v in CLOUD_VECTORS.items():
        MEL.set_material_instance_vector_parameter_value(cloud_mat, k, unreal.LinearColor(*v))
    MEL.update_material_instance(cloud_mat)
    EAL.save_loaded_asset(cloud_mat)
if cloud_mat:
    vc = eas.spawn_actor_from_class(unreal.VolumetricCloud, V(0, 0, 0))
    vc.set_actor_label("VolumetricCloud")
    vcc = vc.get_component_by_class(unreal.VolumetricCloudComponent)
    vcc.set_editor_property("material", cloud_mat)
    vcc.set_editor_property("layer_bottom_altitude", CLOUD_BASE_KM + AF.FIELD_M / 1000.0)
    vcc.set_editor_property("layer_height", CLOUD_TOP_KM)
    for k, v in (("view_sample_count_scale", 1.2), ("shadow_view_sample_count_scale", 0.8), ("sky_light_cloud_bottom_occlusion", 0.6),
                 ("shadow_tracing_distance", 15.0), ("stop_tracing_transmittance_threshold", 0.005)):
        try:
            vcc.set_editor_property(k, v)
        except Exception as e:
            log("cloud", k, e)
EXPOSURE_EV, EXPOSURE_RANGE = 2.0, 1.5     # outside-view EV100 in this level's lighting (sun 10 lux; measured in PIE 11-04)
pp = eas.spawn_actor_from_class(unreal.PostProcessVolume, V(0, 0, 0))
pp.set_actor_label("PostProcess")
pp.set_editor_property("unbound", True)
ps = pp.get_editor_property("settings")
for k, v in (("override_motion_blur_amount", True), ("motion_blur_amount", 0.0), ("override_bloom_intensity", True), ("bloom_intensity", 0.35),
             ("override_auto_exposure_bias", True), ("auto_exposure_bias", 0.3), ("override_vignette_intensity", True), ("vignette_intensity", 0.2),
             ("override_lumen_final_gather_quality", True), ("lumen_final_gather_quality", 1.0),
             ("override_lumen_scene_detail", True), ("lumen_scene_detail", 1.0),
             # exposure: narrow auto-exposure range around the outside-view value, so looking down into the cockpit
             # does not blow out the sky; local exposure lifts the cockpit shadows instead
             ("override_auto_exposure_min_brightness", True), ("auto_exposure_min_brightness", EXPOSURE_EV - EXPOSURE_RANGE),
             ("override_auto_exposure_max_brightness", True), ("auto_exposure_max_brightness", EXPOSURE_EV + 0.5),
             ("override_local_exposure_shadow_contrast_scale", True), ("local_exposure_shadow_contrast_scale", 0.75),
             ("override_local_exposure_highlight_contrast_scale", True), ("local_exposure_highlight_contrast_scale", 0.85)):
    try:
        ps.set_editor_property(k, v)
    except Exception as e:
        log("pp skip", k, e)
pp.set_editor_property("settings", ps)
eas.spawn_actor_from_class(unreal.PlayerStart, V(-3000, 0, AF.FIELD_M * 100 + 300)).set_actor_label("PlayerStart")
log("sky done")

# =====================================================================================================================
# aircraft: FlightGear F-16 (ThirdParty/f16_obj, OBJ in Unreal body cm, see fetch_f16_model.py). The legacy FBX-SDK
# OBJ importer maps OBJ (x, y, z) -> UE (x, -y, z); the converter wrote OBJ = UE (X, Z, Y), so a copy with
# (x, y, z) -> (x, -z, y) is imported (Interchange's OBJ importer fails on these files: "Bad MeshDescription").
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


def _prep_obj(src, dst):
    with open(src, encoding="utf-8") as f, open(dst, "w", encoding="utf-8") as g:
        for line in f:
            if line.startswith("v ") or line.startswith("vn "):
                k, x, y, z = line.split()[:4]
                g.write("%s %s %s %s\n" % (k, x, "%.6g" % -float(z), y))
            else:
                g.write(line)


F16_KEEP = ("F16_Exterior", "F16_Glass", "F16_Gear")     # the FlightGear cockpit interior is replaced by ours


def import_f16():
    man = json.load(open(os.path.join(F16_SRC, "manifest.json"), encoding="utf-8"))
    man["parts"] = [p for p in man["parts"] if p["name"] in F16_KEEP]
    tmp = os.path.join(PROJ, "Intermediate", "f16_import")
    os.makedirs(tmp, exist_ok=True)
    try:   # legacy (FBX SDK) OBJ importer
        unreal.SystemLibrary.execute_console_command(unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_editor_world(),
                                                     "Interchange.FeatureFlags.Import.OBJ 0")
    except Exception as e:
        log("interchange flag", e)
    texfiles = sorted({os.path.join(F16_SRC, mt["texture"]) for p in man["parts"] for mt in p["materials"] if mt.get("texture")})
    tex = import_textures(texfiles, f"{TP}/F16/Textures")
    m_tex, m_mask, m_col = f16_master("M_F16Tex"), f16_master("M_F16Masked", masked=True), f16_master("M_F16Color", textured=False)
    meshes, mats = {}, {}
    for p in man["parts"]:
        name = p["name"]
        src = os.path.join(F16_SRC, p["obj"])
        dst = os.path.join(tmp, p["obj"])
        _prep_obj(src, dst)
        mtl = os.path.splitext(p["obj"])[0] + ".mtl"
        if os.path.exists(os.path.join(F16_SRC, mtl)):
            with open(os.path.join(F16_SRC, mtl), encoding="utf-8") as f, open(os.path.join(tmp, mtl), "w", encoding="utf-8") as g:
                g.write(f.read())
        t = unreal.AssetImportTask()
        t.filename = dst
        t.destination_path = f"{TP}/F16/Meshes"
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
        try:
            sd.set_editor_property("convert_scene", False)
        except Exception:
            pass
        t.options = o
        assets.import_asset_tasks([t])
        sm = unreal.load_asset(f"{TP}/F16/Meshes/{name}")
        if not sm:
            log("F-16 import failed", name)
            continue
        # materials: one instance per OBJ material, assigned by slot name
        slots = {}
        for i, sl in enumerate(sm.static_materials):
            slots[str(sl.material_slot_name)] = i
        for mt in p["materials"]:
            mname = mt["name"]
            kd = mt.get("kd") or [1, 1, 1]
            sc = dict(Rough=0.45 if name == "F16_Exterior" else 0.6, Metal=0.0, Emissive=0.6 if mt.get("emissive") else 0.0)
            if name == "F16_Glass" or (mt.get("transparent") and not mt.get("texture")) or "HUDGlass" in (mt.get("ac_materials") or []):
                mi = MAT["hudglass"] if "HUDGlass" in (mt.get("ac_materials") or []) else MAT["canopy"]
            elif mt.get("texture"):
                tx = tex.get(os.path.splitext(mt["texture"])[0])
                par = m_mask if mt.get("transparent") else m_tex
                mi = instance("MI_" + mname, par, sc, dict(Tint=kd), dict(Tex=tx) if tx else None, folder=f"{TP}/F16/Materials")
            else:
                mi = instance("MI_" + mname, m_col, sc, dict(Tint=kd), folder=f"{TP}/F16/Materials")
            idx = slots.get(mname)
            if idx is None:            # slot names can get a suffix; match by prefix
                idx = next((i for s, i in slots.items() if s.startswith(mname)), None)
            if idx is not None:
                sm.set_material(idx, mi)
            mats[mname] = mi
        EAL.save_loaded_asset(sm)
        b = sm.get_bounding_box()
        log("F-16 part", name, "slots", len(slots), "bbox", [round(v) for v in (b.min.x, b.min.y, b.min.z, b.max.x, b.max.y, b.max.z)])
        meshes[name] = sm
    return man, meshes


MAN, F16 = (None, {})
if os.path.exists(os.path.join(F16_SRC, "manifest.json")):
    MAN, F16 = import_f16()
else:
    log("ThirdParty/f16_obj missing - run Scripts/fetch_f16_model.py")
if F16:
    ac("AC_F16_Exterior", F16.get("F16_Exterior"), None)
    ac("AC_F16_Glass", F16.get("F16_Glass"), None, tags=("Canopy",), shadows=False)
    ac("AC_F16_Gear", F16.get("F16_Gear"), None, tags=("Gear",))
    log("tire bottom z", MAN.get("tire_bottom_z_ue_cm"), "(sim_client.GEAR_BOTTOM_CM)")
# our cockpit (Scripts/cockpit/ue_cockpit.py, uses the helpers above): parts, pivots, needles, MFD screens
_ckp = os.path.join(PROJ, "Scripts", "cockpit", "ue_cockpit.py")
exec(compile(open(_ckp, encoding="utf-8").read(), _ckp, "exec"))
log("aircraft done")

# =====================================================================================================================
# camera rig (tag SimCamera, moved by sim_client) carrying the view camera (tag SimView), the HUD plane and the
# tutorial panel. The CameraActor's root is its camera component, which the HMD drives in VR (and the monitor head look
# rotates), so the overlays hang on the rig, not on the camera.
cam = place("SimCameraRig", None, EYE, None, movable=True, shadows=False, tags=("SimCamera",))
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

# HUD: plane HUD_D ahead of the eye, normal along body X, covering +-HUD_HALF deg around elevation HUD_EL0 (values must
# match sim_client.HUD_*). Drawn without depth test after TSR = collimated look, no ghosting, visible in VR.
HUD_D, HUD_HALF, HUD_EL0 = 2000.0, 14.0, -6.0
size = 2 * HUD_D * math.tan(math.radians(HUD_HALF))
hl = V(EYE[0] + HUD_D, 0.0, EYE[2] + HUD_D * math.tan(math.radians(HUD_EL0)))
r = unreal.MathLibrary.make_rot_from_zx(V(-1, 0, 0), V(0, 1, 0))
hud = place("HUD", SHAPE["Plane"], (hl.x, hl.y, hl.z), MAT["hud"], (r.roll, r.pitch, r.yaw), (size / 100.0, size / 100.0, 1), movable=True,
            shadows=False, tags=("HUD", "Overlay"))
attach(hud, cam)
# tutorial panel: small, lower left (over the left console), not in the forward view. H toggles it.
PANEL_LOC = V(EYE[0] + 70, -36, EYE[2] - 21)
prot = unreal.MathLibrary.make_rot_from_zx(V(*EYE) - PANEL_LOC, V(0, 1, 0))
panel = place("TutorPanel", SHAPE["Plane"], (PANEL_LOC.x, PANEL_LOC.y, PANEL_LOC.z), MAT["panel"], rot=(prot.roll, prot.pitch, prot.yaw),
              scale=(0.26, 0.13, 1), movable=True, shadows=False, tags=("TutorPanel", "Overlay"))
attach(panel, cam)
# key guide panel (sim/key_panel.png, loaded by sim_client): mirror of the tutorial panel, lower right. K toggles it.
KEYS_LOC = V(PANEL_LOC.x, -PANEL_LOC.y, PANEL_LOC.z)
krot = unreal.MathLibrary.make_rot_from_zx(V(*EYE) - KEYS_LOC, V(0, 1, 0))
keys = place("KeyPanel", SHAPE["Plane"], (KEYS_LOC.x, KEYS_LOC.y, KEYS_LOC.z), MAT["panel"], rot=(krot.roll, krot.pitch, krot.yaw),
             scale=(0.26, 0.13, 1), movable=True, shadows=False, tags=("KeyPanel", "Overlay"))
attach(keys, cam)
log("camera + overlays done")

ws = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_editor_world().get_world_settings()
try:
    ws.set_editor_property("default_game_mode", unreal.GameModeBase)
except Exception as e:
    log("game mode override skipped", e)
ok = les.save_current_level()
log("saved", MAP, ok, "actors", len(eas.get_all_level_actors()))
