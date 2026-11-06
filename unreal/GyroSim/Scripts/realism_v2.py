"""Realism v2 (outside look): sky colour, clouds, sun glare, canopy glass reflections / tint, exposure speed.
Plan, gaps and sources: docs/realism-v2-plan.md. v1 = the state of commit 5209af9 (build_level.py sky section +
ue_cockpit.ck_canopy + sim_client.PRESET_LOOK); v2 changes only the values listed in V2_COMMON / V2_PROFILE below.

Two entry points:
  build(g)                    called by build_level.py (g = its globals) unless GYROSIM_REALISM_V2=0: builds the canopy
                              material M_CkCanopyV2, puts it on the F-16 glass mesh, writes the v2 cloud density into
                              MI_Clouds and bakes the 'monitor' profile into the level actors.
  apply_profile(name, world)  runtime (PIE), per quality preset ('monitor' / 'vr'); with STATE['on'] False it restores the
                              v1 values (same session before / after, see realism_shots.py GYROSIM_SHOTS_V2).
  install_hook(sim_client)    wraps sim_client.apply_look so every preset switch also applies the v2 profile (used by
                              realism_shots.py / measure_fps.py; the permanent hook in sim_client is a phase-2 step).
Switches: GYROSIM_REALISM_V2=0 at build = pure v1 level; GYROSIM_REALISM_V2_RUNTIME=off = v1 values at runtime;
GYROSIM_CANOPY=v2 (or STATE['canopy']='v2' + preset re-apply) = the 11-05 V2 canopy glass instead of V3 (default).
GPU cost numbers in comments are estimates (not measured) until phase 2.
"""
import os
import unreal

log = lambda *a: unreal.log("[realism_v2] " + " ".join(str(x) for x in a))
ENABLED = os.environ.get("GYROSIM_REALISM_V2", "1") != "0"
STATE = dict(on=os.environ.get("GYROSIM_REALISM_V2_RUNTIME", "on") != "off", mids={},
             canopy=os.environ.get("GYROSIM_CANOPY", "v3"))        # canopy glass with v2 on: "v3" (default since 11-06) or "v2" (back)

CK_MAT = "/Game/Cockpit/Materials"
CANOPY_V1 = CK_MAT + "/M_CkCanopy"
CANOPY_V2 = CK_MAT + "/M_CkCanopyV2"
CANOPY_V3 = CK_MAT + "/M_CkCanopyV3"
CLOUD_MI = "/Game/Materials/MI_Clouds"
BOKEH_HEX = "/Game/Cockpit/Textures/T_BokehHex"

# ---- values -----------------------------------------------------------------------------------------------------------
# v1 (restore values for the 'off' state): what build_level.py sets, or the engine default where v1 sets nothing.
V1 = dict(
    light=dict(light_source_angle=0.53, cast_shadows_on_atmosphere=False, cloud_shadow_extent=150.0),
    sky=dict(sky_luminance_factor=(1.0, 1.0, 1.0)),
    skylight=dict(cloud_ambient_occlusion=False),
    cloud=dict(stop_tracing_transmittance_threshold=0.005),
    cloud_density=0.045,
    pp=dict(bloom_method="standard", bloom_intensity=0.35, lens_flare_intensity=None,      # None = no override (engine default)
            lens_flare_bokeh_shape=None, lens_flare_bokeh_size=None, lens_flare_threshold=None,
            auto_exposure_speed_up=None, auto_exposure_speed_down=None),
)
# v2, same in both presets
V2_COMMON = dict(
    # UE default sun angle (0.5357 deg; real sun 0.53-0.545). Softens VSM / contact shadow penumbra by a hair.
    light=dict(light_source_angle=0.5357, cloud_shadow_extent=60.0),     # cloud shadow map over 60 km instead of 150 km
    # = ~2.5x the texel density -> crisper cloud shadows on the ground (clouds at 1-3.6 km), same cost.
    # sky only (not terrain / cockpit): darker, bluer upper sky. Measured gap: our upper sky sat 0.33-0.39 / value
    # 0.66-0.73 vs photos 0.46-0.62 / 0.53-0.65 (docs/realism-v2-plan.md 1.1). Horizon stays white (aerial persp. unchanged).
    sky=dict(sky_luminance_factor=(0.80, 0.86, 1.0)),
    # clouds darken the sky light under / inside them (cloud bases, ground under overcast) - one small 2D map.
    skylight=dict(cloud_ambient_occlusion=True, cloud_ambient_occlusion_strength=1.0, cloud_ambient_occlusion_extent=60.0,
                  cloud_ambient_occlusion_aperture_scale=0.05),
    # optically thicker cumulus: crisper edges and darker bases (v1 0.045 looked wispy / cotton-like). Coverage and
    # layout (user's variant C, 11-04) unchanged.
    cloud_density=0.07,
    pp=dict(auto_exposure_speed_up=2.0, auto_exposure_speed_down=1.0),   # slower brightening (~2 stops/s), no pumping
)
# v2, per preset
V2_PROFILE = {
    # monitor (120 fps cap, GPU ~4 ms at 1080p): energy-conserving convolution bloom = veiling glare / star around the sun
    # disc, a faint lens flare (camera look on a flat screen), sun light shafts through cloud gaps (opaque shadow in air).
    "monitor": dict(light=dict(cast_shadows_on_atmosphere=True), cloud=dict(stop_tracing_transmittance_threshold=0.005),
                    pp=dict(bloom_method="convolution", bloom_intensity=0.6, lens_flare_intensity=0.4,
                            # 11-06: hexagonal ghosts (6-blade aperture, T_BokehHex) only from the sun (threshold), a bit
                            # larger and stronger so they read as hexagons when looking near the sun
                            lens_flare_bokeh_shape=BOKEH_HEX, lens_flare_bokeh_size=5.0, lens_flare_threshold=8.0)),
    # VR (90 Hz both eyes): no lens effects (eyes have no lens ghosts), standard bloom, cheaper clouds (guide #9).
    "vr": dict(light=dict(cast_shadows_on_atmosphere=False), cloud=dict(stop_tracing_transmittance_threshold=0.01),
               pp=dict(bloom_method="standard", bloom_intensity=0.3, lens_flare_intensity=0.0, lens_flare_bokeh_shape=None,
                       lens_flare_bokeh_size=None, lens_flare_threshold=None)),
}
# canopy V2 scalar defaults (the v1 ones are kept as they were in ue_cockpit.ck_canopy)
CANOPY_V1_PARAMS = (("Tile", 1.3), ("Gain", 0.7), ("Base", 0.008), ("FresAmt", 0.12), ("SmudgeAmt", 0.003), ("HaloAmt", 0.012),
                    ("HaloGlow", 0.08))
CANOPY_V2_PARAMS = (("F0", 0.05),        # polycarbonate n ~ 1.585 -> Schlick F0 = ((n-1)/(n+1))^2 = 0.051
                    ("ReflAmt", 1.0),    # x Fresnel: sky reflection (sky light cube map along the mirror ray)
                    ("TintAmt", 0.06),   # share of the background replaced by (background x TintCol): warm coated glass
                    ("VeilPow", 8.0),    # broad forward-scatter haze of the whole glass toward the sun (photo c23)
                    ("VeilGlow", 0.025))
CANOPY_TINT = (1.0, 0.9, 0.7)

CANOPY_V2_HLSL = """
float3 d = LP - Eye;
float az = atan2(d.y, d.x);
float el = atan2(d.z, length(d.xy));
float2 uv = float2(az, -el) * Tile;
float4 t = Texture2DSample(T, TSampler, uv);
float scr = t.r;
float smu = t.g;
float c = saturate(dot(normalize(-CV), normalize(Sun)));
float glint = pow(c, 40.0);
float halo = pow(c, 4.0);
float veil = pow(c, VeilPow);
float cosv = saturate(abs(dot(normalize(CV), normalize(N))));
float fr = pow(1.0 - cosv, 4.0);
float F = (F0 + (1.0 - F0) * pow(1.0 - cosv, 5.0)) * ReflAmt;
float inside = saturate((dot(normalize(R), normalize(Up)) + 0.15) * 4.0);   // mirror ray into the cockpit tub = dark
float op = Base + fr * FresAmt + smu * SmudgeAmt * (0.3 + 0.7 * halo) + scr * glint * 0.12 + halo * HaloAmt * smu;
op = saturate(op + F + TintAmt);
float3 e = SunCol * (scr * glint * Gain + smu * halo * HaloGlow + veil * VeilGlow) + Env * F * inside + Bg * TintCol * TintAmt;
return float4(e / max(op, 0.02), op);
"""


# canopy V3 (11-06, "glass must be visible like F-16 photos / renders"). Thin Translucent shading model: the background
# is MULTIPLIED by a per-channel transmittance in the blend unit (dual-source blending), so the scene behind keeps its
# full HDR range (the sun disc, bloom and the lens flare survive). The first V3 re-drew the background through the
# SceneColor node instead, which lost the sun's HDR brightness (sun = small dot, no bloom / flare; 11-06 shots canopy_v3h).
#   transmittance = Tr * (1-F) * (1-h)        Tr = lerp(1, TintCol, TintAmt) ^ min(1/cos, PathMax)  (Beer path length:
#                                             clear-ish looking straight through, amber toward the grazing edges / sill)
#   emissive      = Refl * F + sun mirror glint + anisotropic scratch glints + halo / veil + smudge haze
#   Refl = sky light cube map for mirror rays going up; mirror rays going down hit a plane at the coaming height (local
#          z = CoamZ): forward of GsX = black glare shield, sides = grey consoles with panel blocks, middle = pilot /
#          stick (dark). Lit by the sky light from above and the sun (InSun x sun height). Rays wobble toward the edges.
#   Scratches: T_CkCanopyAniso (R mask, BA = scratch direction). A scratch glints where its tangent is perpendicular to
#          the direction toward the sun in the view-angle texture space (anisotropic: circular polishing marks make a
#          bright radial streak through the sun, wipe marks light up only at some sun angles). Absolute brightness
#          (Gain; the EnvUp-scaled first try was invisible on screen).
#   Distortion: refraction (index-of-refraction mode) 1 + Dist x (1-cos)^3 -> the outside view bends a little toward
#          the grazing edges of the bubble; the distortion pass works on the HDR scene colour.
# Values are look-matched to photos (estimates, not measured). The HUD is in the after-motion-blur pass -> not tinted.
# NOTE: build this material in the GUI editor (realism_shots GYROSIM_CANOPY_BUILD=1 or build_canopy_v3()); a copy built
# by a -nullrhi commandlet was saved with a broken Custom input ("missing input 1 (LP)") -> default material (11-06).
CANOPY_V3_PARAMS = (("Tile", 1.3),
                    ("Gain", 4.0),       # scratch glint radiance (absolute; V2 used 0.7 without the anisotropy)
                    ("GlintPow", 10.0),  # glint falloff away from the sun: ((cos+1)/2)^GlintPow
                    ("AnisoPow", 6.0),  # how exactly the scratch must be perpendicular to the sun direction
                    ("HaloGlow", 0.04),
                    ("SunSpec", 2.0),    # mirror image of the sun in the glass, very narrow lobe
                    ("F0", 0.07),        # polycarbonate 0.05 + gold / ITO coating (estimate)
                    ("ReflAmt", 0.85),
                    ("TintAmt", 0.30),   # straight through: (1, 0.946, 0.856) transmission
                    ("PathMax", 3.0),    # grazing (the raked F-16 front, the sill): up to 3x the path -> (1, 0.85, 0.63)
                    ("InSun", 4.0),      # sun-lit interior ~4x brighter than the sky-lit one (estimate)
                    ("LitAbs", 8.0),     # interior light level seen in the glass (absolute, look-matched)
                    ("CoamZ", 76.0),     # coaming / console height (local cm) for the interior reflection
                    ("GsX", 468.0),      # glare shield starts here (local x, cm)
                    ("Wobble", 0.05),    # reflection ray wobble at grazing angles
                    ("Dist", 0.02),      # refraction index excess at grazing angles (edge distortion)
                    ("SmudgeAmt", 0.03), # faint haze where the smudge texture is (stronger toward the sun)
                    ("VeilPow", 8.0), ("VeilGlow", 0.02))
CANOPY_V3_TINT = (1.0, 0.85, 0.58)
CANOPY_V3_INCOL = (0.30, 0.29, 0.28)   # console albedo seen in the glass (grey panels); glare shield / pilot darker

# small nodes for the transmittance and refraction pins (a Custom node with texture / sky light inputs gave transmittance 0
# = black glass on the ThinTranslucent output, 11-06)
CANOPY_V3_TR_HLSL = """
float cosv = max(abs(dot(normalize(CV), normalize(N))), 0.05);
float F = saturate((F0 + (1.0 - F0) * pow(1.0 - cosv, 5.0)) * ReflAmt);
float3 Tr = pow(saturate(lerp(float3(1.0, 1.0, 1.0), TintCol, TintAmt)), min(1.0 / cosv, PathMax));
return Tr * (1.0 - F);
"""
CANOPY_V3_RF_HLSL = """
float gz = 1.0 - max(abs(dot(normalize(CV), normalize(N))), 0.05);
return 1.0 + Dist * gz * gz * gz;
"""

CANOPY_V3_HLSL = """
float3 up = normalize(Up);
float3 fw = normalize(Fw);
float3 rt = normalize(Rt);
float3 v = normalize(CV);
float3 n = normalize(N);
float cosv = max(abs(dot(v, n)), 0.05);
float gz = 1.0 - cosv;
float3 d = LP - Eye;
float2 puv = float2(atan2(d.y, d.x), -atan2(d.z, length(d.xy)));
float4 t = Texture2DSample(T, TSampler, puv * Tile);
float scr = t.r;
float smu = t.g;
float3 sw = normalize(Sun);
float c = dot(-v, sw);
float halo = pow(saturate(c), 4.0);
float h = smu * SmudgeAmt * (0.35 + 0.65 * halo);
float F = saturate((F0 + (1.0 - F0) * pow(gz, 5.0)) * ReflAmt);
float2 t2 = t.ba * 2.0 - 1.0;
float3 sl = float3(dot(sw, fw), dot(sw, rt), dot(sw, up));
float2 suv = float2(atan2(sl.y, sl.x), -atan2(sl.z, length(sl.xy)));
float2 ds = suv - puv;
ds.x = ds.x - 6.2831853 * round(ds.x / 6.2831853);
float psi = atan2(ds.y, ds.x);
float aniso = pow(saturate(0.5 - 0.5 * dot(t2, float2(cos(2.0 * psi), sin(2.0 * psi)))), AnisoPow);
float glint = pow(saturate(c * 0.5 + 0.5), GlintPow) * step(0.0, c + 0.3);
float veil = pow(saturate(c), VeilPow);
float3 r = normalize(R + n * Wobble * gz * gz * sin(LP.x * 0.11 + LP.y * 0.07 + LP.z * 0.09));
float3 rl = float3(dot(r, fw), dot(r, rt), dot(r, up));
float sunUp = saturate(dot(sw, up));
float3 lit = SunCol * LitAbs * (0.25 + InSun * 0.25 * sunUp);   // absolute (EnvUp-scaled light was far too dark on screen)
float3 inner = Env;
if (rl.z < -0.02) {
    float th = (CoamZ - LP.z) / rl.z;
    float3 H = LP + rl * max(th, 0.0);
    float gs = smoothstep(GsX - 3.0, GsX + 3.0, H.x) * (1.0 - smoothstep(31.0, 37.0, abs(H.y)));
    float con = (1.0 - smoothstep(GsX - 3.0, GsX + 3.0, H.x)) * smoothstep(327.0, 333.0, H.x) * smoothstep(15.0, 21.0, abs(H.y));
    float3 alb = lerp(InCol * 0.35, InCol, con);
    alb = lerp(alb, InCol * 0.08, gs);
    alb *= 0.6 + 0.8 * frac(sin(dot(floor(H.xy / 7.0), float2(12.9898, 78.233))) * 43758.5453) * con;
    inner = lit * alb;
}
float skyw = saturate((rl.z + 0.15) * 4.0);
float3 refl = lerp(inner, Env, skyw);
float sky = dot(EnvUp, float3(0.333, 0.333, 0.333));
float sun = pow(saturate(dot(r, sw)), 3000.0) * SunSpec;
float3 e = refl * F + EnvUp * h * 2.0 + SunCol * sun * F * 10.0
         + SunCol * (scr * aniso * glint * Gain + smu * halo * HaloGlow + veil * VeilGlow);
return float4(e, 1.0);
"""


def _mat_helpers():
    """the build_level.py material helpers, for building the canopy outside a level build (realism_shots.py)."""
    MEL, EAL = unreal.MaterialEditingLibrary, unreal.EditorAssetLibrary

    def _new_material(name, folder):
        path = folder + "/" + name
        if EAL.does_asset_exist(path):
            m = unreal.load_asset(path)
            MEL.delete_all_material_expressions(m)
            return m
        return unreal.AssetToolsHelpers.get_asset_tools().create_asset(name, folder, unreal.Material, unreal.MaterialFactoryNew())

    def _finish(m):
        MEL.recompile_material(m)
        EAL.save_loaded_asset(m)
        return m

    def _expr(m, cls, x, y, **props):
        e = MEL.create_material_expression(m, cls, x, y)
        for k, v in props.items():
            e.set_editor_property(k, v)
        return e

    def _const3(m, c, x, y):
        return _expr(m, unreal.MaterialExpressionConstant3Vector, x, y, constant=unreal.LinearColor(c[0], c[1], c[2], 1.0))

    def _sparam(m, n, v, x, y):
        return _expr(m, unreal.MaterialExpressionScalarParameter, x, y, parameter_name=n, default_value=v)

    def _vparam(m, n, c, x, y):
        return _expr(m, unreal.MaterialExpressionVectorParameter, x, y, parameter_name=n,
                     default_value=unreal.LinearColor(c[0], c[1], c[2], 1.0))
    import sim_client
    return dict(_new_material=_new_material, _finish=_finish, _expr=_expr, _const3=_const3, _sparam=_sparam, _vparam=_vparam,
                EYE=tuple(sim_client.EYE))


def level_sun_dir(world=None):
    world = world or unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_editor_world()
    for a in _actors(world, unreal.DirectionalLight):
        f = a.get_actor_forward_vector()
        return (-f.x, -f.y, -f.z)
    return (0.6, 0.45, 0.62)


def _canopy_tex(name, srgb=False, comp=None):
    """imports Art/Cockpit/tex/<name>.png to /Game/Cockpit/Textures when missing or older than the png."""
    png = os.path.join(unreal.Paths.project_dir(), "Art", "Cockpit", "tex", name + ".png")
    path = "/Game/Cockpit/Textures/" + name
    if not os.path.exists(png):
        log("texture missing (run Scripts/cockpit/make_textures.py --canopy-v3):", png)
        return unreal.load_asset(path) if unreal.EditorAssetLibrary.does_asset_exist(path) else None
    ua = os.path.join(unreal.Paths.project_content_dir(), "Cockpit", "Textures", name + ".uasset")
    if not (os.path.exists(ua) and os.path.getmtime(ua) >= os.path.getmtime(png)):
        t = unreal.AssetImportTask()
        t.filename, t.destination_path, t.automated, t.replace_existing, t.save = png, "/Game/Cockpit/Textures", True, True, True
        unreal.AssetToolsHelpers.get_asset_tools().import_asset_tasks([t])
        tx = unreal.load_asset(path)
        if tx:
            tx.set_editor_property("srgb", srgb)
            if comp is not None:
                tx.set_editor_property("compression_settings", comp)
            unreal.EditorAssetLibrary.save_loaded_asset(tx)
        log("imported", name)
    return unreal.load_asset(path)


def _canopy_v3(g, sun_dir):
    """M_CkCanopyV3 (inner glass shell): ThinTranslucent, transmittance + refraction only. M_CkCanopyV3Fx (outer shell,
    on the same surface): additive unlit, the reflections / glints / haze. ThinTranslucent scales its emissive by the
    opacity (= surface coverage) and opacity 1 hid the background (black glass), so the light the glass adds goes to a
    separate additive layer (11-06). Returns (glass, fx)."""
    fx = _canopy_v3_mat(g, sun_dir, fx=True)
    return _canopy_v3_mat(g, sun_dir, fx=False), fx


def _canopy_v3_mat(g, sun_dir, fx):
    _new_material, _expr, _sparam, _vparam, _const3, _finish = (g[k] for k in ("_new_material", "_expr", "_sparam", "_vparam",
                                                                                 "_const3", "_finish"))
    MEL = unreal.MaterialEditingLibrary
    m = _new_material("M_CkCanopyV3Fx" if fx else "M_CkCanopyV3", CK_MAT)
    m.set_editor_property("two_sided", True)
    if fx:
        m.set_editor_property("blend_mode", unreal.BlendMode.BLEND_ADDITIVE)
        m.set_editor_property("shading_model", unreal.MaterialShadingModel.MSM_UNLIT)
    else:
        m.set_editor_property("blend_mode", unreal.BlendMode.BLEND_TRANSLUCENT)
        m.set_editor_property("shading_model", unreal.MaterialShadingModel.MSM_THIN_TRANSLUCENT)
        m.set_editor_property("translucency_lighting_mode", unreal.TranslucencyLightingMode.TLM_SURFACE_PER_PIXEL_LIGHTING)
        for k, v in (("refraction_mode", "RM_INDEX_OF_REFRACTION"), ("refraction_method", "RM_INDEX_OF_REFRACTION")):
            try:
                m.set_editor_property(k, getattr(unreal.RefractionMode, v))
                break
            except Exception:
                pass

    def con(a, b, pin):
        if not MEL.connect_material_expressions(a, "", b, pin):
            log("canopy v3: not connected", pin)

    def rgb(src, x, y):
        k = _expr(m, unreal.MaterialExpressionComponentMask, x, y, r=True, g=True, b=True, a=False)
        con(src, k, "")
        return k
    pn = tuple(n for n, _ in CANOPY_V3_PARAMS)
    cus = []
    nodes = [(CANOPY_V3_HLSL, ("LP", "CV", "N", "R", "Up", "Fw", "Rt", "Sun", "SunCol", "T", "Eye", "Env", "EnvUp", "TintCol",
                               "InCol") + pn, unreal.CustomMaterialOutputType.CMOT_FLOAT4)] if fx else [
             (CANOPY_V3_TR_HLSL, ("CV", "N", "TintCol", "TintAmt", "PathMax", "F0", "ReflAmt"), unreal.CustomMaterialOutputType.CMOT_FLOAT3),
             (CANOPY_V3_RF_HLSL, ("CV", "N", "Dist"), unreal.CustomMaterialOutputType.CMOT_FLOAT1)]
    for i, (code, names, out) in enumerate(nodes):
        cu = _expr(m, unreal.MaterialExpressionCustom, -600, -200 + 250 * i)
        cu.set_editor_property("code", code)
        cu.set_editor_property("output_type", out)
        ins = []
        for n in names:
            ci = unreal.CustomInput()
            ci.set_editor_property("input_name", n)
            ins.append(ci)
        cu.set_editor_property("inputs", ins)
        cus.append((cu, set(names)))

    def to_all(src, pin):
        for cu, nm in cus:
            if pin in nm:
                con(src, cu, pin)
    lp = _expr(m, unreal.MaterialExpressionTransformPosition, -1000, -300,
               transform_source_type=unreal.MaterialPositionTransformSource.TRANSFORMPOSSOURCE_WORLD,
               transform_type=unreal.MaterialPositionTransformSource.TRANSFORMPOSSOURCE_LOCAL)
    con(_expr(m, unreal.MaterialExpressionWorldPosition, -1200, -300), lp, "")
    to_all(lp, "LP")
    cv = _expr(m, unreal.MaterialExpressionCameraVectorWS, -1000, -220)
    to_all(cv, "CV")
    to_all(_expr(m, unreal.MaterialExpressionVertexNormalWS, -1000, -160), "N")
    rv = _expr(m, unreal.MaterialExpressionReflectionVectorWS, -1000, -100)
    to_all(rv, "R")
    axes = {}
    for k, (vec, y) in {"Up": ((0.0, 0.0, 1.0), -40), "Fw": ((1.0, 0.0, 0.0), -560), "Rt": ((0.0, 1.0, 0.0), -500)}.items():
        tr = _expr(m, unreal.MaterialExpressionTransform, -1000, y,
                   transform_source_type=unreal.MaterialVectorCoordTransformSource.TRANSFORMSOURCE_LOCAL,
                   transform_type=unreal.MaterialVectorCoordTransform.TRANSFORM_WORLD)
        con(_const3(m, vec, -1200, y), tr, "")
        to_all(tr, k)
        axes[k] = tr
    to_all(rgb(_vparam(m, "SunDir", sun_dir, -1400, 20), -1200, 20), "Sun")
    to_all(rgb(_vparam(m, "SunColor", (1.0, 0.96, 0.9), -1400, 80), -1200, 80), "SunCol")
    if fx:
        t = _expr(m, unreal.MaterialExpressionTextureObjectParameter, -1000, 140, parameter_name="Scratch")
        st = _canopy_tex("T_CkCanopyAniso", comp=unreal.TextureCompressionSettings.TC_VECTOR_DISPLACEMENTMAP)
        if st:
            t.set_editor_property("texture", st)
        to_all(t, "T")
        to_all(_const3(m, g["EYE"], -1000, 200), "Eye")
        env = _expr(m, unreal.MaterialExpressionSkyLightEnvMapSample, -1000, 260)
        con(rv, env, "Direction")
        con(_sparam(m, "EnvRough", 0.06, -1200, 260), env, "Roughness")
        envup = _expr(m, unreal.MaterialExpressionSkyLightEnvMapSample, -1000, 330)
        con(axes["Up"], envup, "Direction")
        con(_sparam(m, "UpRough", 1.0, -1200, 330), envup, "Roughness")
        to_all(env, "Env")
        to_all(envup, "EnvUp")
    dbg = os.environ.get("GYROSIM_CANOPY_DEBUG") == "1"      # diagnostic: pure green glass (is V3 really on screen?)
    to_all(rgb(_vparam(m, "TintCol", (0.0, 1.0, 0.0) if dbg else CANOPY_V3_TINT, -1400, 460), -1200, 460), "TintCol")
    to_all(rgb(_vparam(m, "InCol", CANOPY_V3_INCOL, -1400, 520), -1200, 520), "InCol")
    used = set().union(*(nm for _, nm in cus))
    for i, (n, v) in enumerate(CANOPY_V3_PARAMS):
        if n in used:
            to_all(_sparam(m, n, 1.0 if (dbg and n == "TintAmt") else v, -1000, 580 + 60 * i), n)
    if fx:
        MEL.connect_material_property(rgb(cus[0][0], -300, -200), "", unreal.MaterialProperty.MP_EMISSIVE_COLOR)
        return _canopy_stats(_finish(m))
    # delete_all_material_expressions leaves the ThinTranslucent output node behind -> a rebuild had two and failed to
    # compile ("only one Thin Translucent Material node", default material; 11-06): remove old ones by object path
    for k in range(16):
        old = unreal.find_object(None, "%s:MaterialExpressionThinTranslucentMaterialOutput_%d" % (m.get_path_name(), k))
        if old:
            MEL.delete_material_expression(m, old)
            log("removed old", old.get_name())
    tto = _expr(m, unreal.MaterialExpressionThinTranslucentMaterialOutput, -100, 50)
    con(cus[0][0], tto, "TransmittanceColor")
    MEL.connect_material_property(cus[1][0], "", unreal.MaterialProperty.MP_REFRACTION)
    for prop, val in ((unreal.MaterialProperty.MP_BASE_COLOR, 0.0), (unreal.MaterialProperty.MP_SPECULAR, 0.0),
                      (unreal.MaterialProperty.MP_ROUGHNESS, 1.0), (unreal.MaterialProperty.MP_OPACITY, 0.0)):
        # opacity = surface coverage of the (black) base layer: 1 hid the background completely (black glass, 11-06);
        # 0 = the background seen through the transmittance, emissive still added
        MEL.connect_material_property(_expr(m, unreal.MaterialExpressionConstant, -300, 500, r=val), "", prop)
    return _canopy_stats(_finish(m))


def _canopy_stats(m):
    try:
        n = unreal.MaterialEditingLibrary.get_statistics(m).num_pixel_shader_instructions
    except Exception as ex:
        n = -1
        log("canopy v3 stats", repr(ex))
    log(m.get_name(), "compiled: pixel instructions", n, "shading", m.get_editor_property("shading_model"),
        "blend", m.get_editor_property("blend_mode"))
    return m


CANOPY_V3FX = CK_MAT + "/M_CkCanopyV3Fx"
CANOPY_OUTER_SLOT = "col_ffe080"        # slot name part of the outer shell (manifest: glassOutsideMat)


def build_canopy_v3(world=None):
    """standalone (open GUI editor, no level rebuild): (re)builds M_CkCanopyV3 + M_CkCanopyV3Fx with the level's sun
    direction and the hexagon lens flare bokeh texture. Returns (glass, fx)."""
    _canopy_tex("T_BokehHex", srgb=True)
    return _canopy_v3(_mat_helpers(), level_sun_dir(world))


# ---- canopy material (build time, needs build_level's helpers) --------------------------------------------------------
def _canopy_v2(g, sun_dir, use_env=True):
    _new_material, _expr, _sparam, _vparam, _const3, _finish = (g[k] for k in ("_new_material", "_expr", "_sparam", "_vparam",
                                                                                 "_const3", "_finish"))
    MEL = unreal.MaterialEditingLibrary
    m = _new_material("M_CkCanopyV2", CK_MAT)
    m.set_editor_property("blend_mode", unreal.BlendMode.BLEND_TRANSLUCENT)
    m.set_editor_property("two_sided", True)
    m.set_editor_property("shading_model", unreal.MaterialShadingModel.MSM_UNLIT)
    cu = _expr(m, unreal.MaterialExpressionCustom, -600, 0)
    cu.set_editor_property("code", CANOPY_V2_HLSL)
    cu.set_editor_property("output_type", unreal.CustomMaterialOutputType.CMOT_FLOAT4)
    scal = CANOPY_V1_PARAMS + CANOPY_V2_PARAMS
    names = ("LP", "CV", "N", "R", "Up", "Sun", "SunCol", "T", "Eye", "Env", "Bg", "TintCol") + tuple(n for n, _ in scal)
    ins = []
    for n in names:
        ci = unreal.CustomInput()
        ci.set_editor_property("input_name", n)
        ins.append(ci)
    cu.set_editor_property("inputs", ins)

    def rgb(src, x, y):
        k = _expr(m, unreal.MaterialExpressionComponentMask, x, y, r=True, g=True, b=True, a=False)
        MEL.connect_material_expressions(src, "", k, "")
        return k
    lp = _expr(m, unreal.MaterialExpressionTransformPosition, -1000, -300,
               transform_source_type=unreal.MaterialPositionTransformSource.TRANSFORMPOSSOURCE_WORLD,
               transform_type=unreal.MaterialPositionTransformSource.TRANSFORMPOSSOURCE_LOCAL)
    MEL.connect_material_expressions(_expr(m, unreal.MaterialExpressionWorldPosition, -1200, -300), "", lp, "")
    MEL.connect_material_expressions(lp, "", cu, "LP")
    cv = _expr(m, unreal.MaterialExpressionCameraVectorWS, -1000, -220)
    MEL.connect_material_expressions(cv, "", cu, "CV")
    MEL.connect_material_expressions(_expr(m, unreal.MaterialExpressionVertexNormalWS, -1000, -160), "", cu, "N")
    rv = _expr(m, unreal.MaterialExpressionReflectionVectorWS, -1000, -100)
    MEL.connect_material_expressions(rv, "", cu, "R")
    up = _expr(m, unreal.MaterialExpressionTransform, -1000, -40,
               transform_source_type=unreal.MaterialVectorCoordTransformSource.TRANSFORMSOURCE_LOCAL,
               transform_type=unreal.MaterialVectorCoordTransform.TRANSFORM_WORLD)
    MEL.connect_material_expressions(_const3(m, (0.0, 0.0, 1.0), -1200, -40), "", up, "")
    MEL.connect_material_expressions(up, "", cu, "Up")
    MEL.connect_material_expressions(rgb(_vparam(m, "SunDir", sun_dir, -1400, 20), -1200, 20), "", cu, "Sun")
    MEL.connect_material_expressions(rgb(_vparam(m, "SunColor", (1.0, 0.96, 0.9), -1400, 80), -1200, 80), "", cu, "SunCol")
    t = _expr(m, unreal.MaterialExpressionTextureObjectParameter, -1000, 140, parameter_name="Scratch")
    st = unreal.load_asset("/Game/Cockpit/Textures/T_CkCanopyScratch")
    if st:
        t.set_editor_property("texture", st)
    MEL.connect_material_expressions(t, "", cu, "T")
    MEL.connect_material_expressions(_const3(m, g["EYE"], -1000, 200), "", cu, "Eye")
    # sky light cube map: along the mirror ray (reflection) and along the view ray (background estimate for the tint)
    env = bg = None
    if use_env and hasattr(unreal, "MaterialExpressionSkyLightEnvMapSample"):
        env = _expr(m, unreal.MaterialExpressionSkyLightEnvMapSample, -1000, 260)
        MEL.connect_material_expressions(rv, "", env, "Direction")
        MEL.connect_material_expressions(_sparam(m, "EnvRough", 0.08, -1200, 260), "", env, "Roughness")
        neg = _expr(m, unreal.MaterialExpressionMultiply, -1200, 330, const_b=-1.0)
        MEL.connect_material_expressions(cv, "", neg, "A")
        bg = _expr(m, unreal.MaterialExpressionSkyLightEnvMapSample, -1000, 330)
        MEL.connect_material_expressions(neg, "", bg, "Direction")
        MEL.connect_material_expressions(_sparam(m, "BgRough", 0.4, -1200, 400), "", bg, "Roughness")
    if env is None:                              # fallback: constant sky colour (no cube map node in this engine build)
        log("SkyLightEnvMapSample not used - constant sky colour")
        env = rgb(_vparam(m, "SkyCol", (0.25, 0.35, 0.55), -1400, 260), -1200, 260)
        bg = env
    MEL.connect_material_expressions(env, "", cu, "Env")
    MEL.connect_material_expressions(bg, "", cu, "Bg")
    MEL.connect_material_expressions(rgb(_vparam(m, "TintCol", CANOPY_TINT, -1400, 460), -1200, 460), "", cu, "TintCol")
    for i, (n, v) in enumerate(scal):
        MEL.connect_material_expressions(_sparam(m, n, v, -1000, 520 + 60 * i), "", cu, n)
    e = _expr(m, unreal.MaterialExpressionComponentMask, -300, -50, r=True, g=True, b=True, a=False)
    MEL.connect_material_expressions(cu, "", e, "")
    a = _expr(m, unreal.MaterialExpressionComponentMask, -300, 80, r=False, g=False, b=False, a=True)
    MEL.connect_material_expressions(cu, "", a, "")
    MEL.connect_material_property(e, "", unreal.MaterialProperty.MP_EMISSIVE_COLOR)
    MEL.connect_material_property(a, "", unreal.MaterialProperty.MP_OPACITY)
    m = _finish(m)
    try:
        st = MEL.get_statistics(m)
        n = st.num_pixel_shader_instructions
    except Exception as ex:
        n = -1
        log("canopy stats", repr(ex))
    log("M_CkCanopyV2 compiled: pixel instructions", n, "env", use_env)
    nullrhi = "-nullrhi" in unreal.SystemLibrary.get_command_line().lower()   # headless build: no shader compile -> 0
    if n == 0 and use_env and not nullrhi:       # compile failed (e.g. node not allowed here) -> constant sky colour
        return _canopy_v2(g, sun_dir, use_env=False)
    return m


def set_glass_asset(sg=None):
    """default materials of the F-16 glass mesh asset (editor viewport / anything not switched at runtime): STATE's
    canopy (v3: inner shell M_CkCanopyV3, outer shell M_CkCanopyV3Fx; v2: M_CkCanopyV2 on both). Saves the asset."""
    sg = sg or _load("/Game/ThirdParty/F16/Meshes/F16_Glass")
    if not sg:
        return
    v3 = STATE.get("canopy") == "v3" and _load(CANOPY_V3) and _load(CANOPY_V3FX)
    for i, sl in enumerate(sg.static_materials):
        outer = CANOPY_OUTER_SLOT in str(sl.material_slot_name)
        sg.set_material(i, _load(CANOPY_V3FX if outer else CANOPY_V3) if v3 else _load(CANOPY_V2))
    unreal.EditorAssetLibrary.save_loaded_asset(sg)
    log("F16_Glass asset ->", "v3" if v3 else "v2")


def build(g):
    """build_level.py hook (editor world, before the level is saved)."""
    if not ENABLED:
        log("off (GYROSIM_REALISM_V2=0) - level stays v1")
        return
    try:
        sd = g["sun"].get_actor_forward_vector()
        sg = (g.get("F16") or {}).get("F16_Glass")
        if sg:
            _canopy_v2(g, (-sd.x, -sd.y, -sd.z))
            if "-nullrhi" not in unreal.SystemLibrary.get_command_line().lower():
                try:                     # V3 only in a GUI editor (a -nullrhi build saves a broken Custom node, 11-06)
                    _canopy_v3(g, (-sd.x, -sd.y, -sd.z))
                except Exception as e3:
                    log("canopy v3 failed (existing asset kept)", repr(e3))
            set_glass_asset(sg)
    except Exception as e:
        log("canopy v2 failed", repr(e))
    try:
        mi = unreal.load_asset(CLOUD_MI)
        if mi:
            unreal.MaterialEditingLibrary.set_material_instance_scalar_parameter_value(mi, "Cloud_GlobalDensity", V2_COMMON["cloud_density"])
            unreal.MaterialEditingLibrary.update_material_instance(mi)
            unreal.EditorAssetLibrary.save_loaded_asset(mi)
    except Exception as e:
        log("cloud density", repr(e))
    world = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_editor_world()
    apply_profile("monitor", world, bake=True)
    log("built (monitor profile baked)")


# ---- runtime ------------------------------------------------------------------------------------------------------------
def _set(obj, k, v, tag):
    try:
        if isinstance(v, tuple):
            v = unreal.LinearColor(v[0], v[1], v[2], 1.0)
        obj.set_editor_property(k, v)
    except Exception as e:
        log("skip", tag, k, repr(e)[:120])


def _merged(name, on):
    if not on:
        return dict(V1)
    out = {}
    prof = V2_PROFILE.get(name, V2_PROFILE["monitor"])
    for sect in ("light", "sky", "skylight", "cloud", "pp"):
        d = dict(V2_COMMON.get(sect, {}))
        d.update(prof.get(sect, {}))
        out[sect] = d
    out["cloud_density"] = V2_COMMON["cloud_density"]
    return out


def _actors(world, cls):
    return list(unreal.GameplayStatics.get_all_actors_of_class(world, cls)) if world else []


def apply_profile(name, world, on=None, bake=False):
    """Sets the v2 (or v1 when off) values for preset 'name' on the sky / light / cloud / post process actors and the
    canopy of 'world'. bake=True (build time): asset-level changes only, no dynamic material instances."""
    on = STATE["on"] if on is None else on
    v = _merged(name, on)
    try:
        for a in _actors(world, unreal.DirectionalLight):
            lc = a.get_component_by_class(unreal.DirectionalLightComponent)
            for k, x in v["light"].items():
                _set(lc, k, x, "light")
        for a in _actors(world, unreal.SkyAtmosphere):
            c = a.get_component_by_class(unreal.SkyAtmosphereComponent)
            for k, x in v["sky"].items():
                _set(c, k, x, "sky")
        for a in _actors(world, unreal.SkyLight):
            c = a.get_component_by_class(unreal.SkyLightComponent)
            for k, x in v["skylight"].items():
                _set(c, k, x, "skylight")
        for a in _actors(world, unreal.VolumetricCloud):
            c = a.get_component_by_class(unreal.VolumetricCloudComponent)
            for k, x in v["cloud"].items():
                _set(c, k, x, "cloud")
            if not bake:
                _cloud_density(world, c, v["cloud_density"])
        for a in _actors(world, unreal.PostProcessVolume):
            ps = a.get_editor_property("settings")
            for k, x in v["pp"].items():
                if k == "bloom_method":
                    _set(ps, "override_bloom_method", True, "pp")
                    _set(ps, "bloom_method", unreal.BloomMethod.BM_FFT if x == "convolution" else unreal.BloomMethod.BM_SOG, "pp")
                elif x is None:
                    _set(ps, "override_" + k, False, "pp")
                elif k == "lens_flare_bokeh_shape":
                    tex = _load(x)
                    _set(ps, "override_" + k, tex is not None, "pp")
                    if tex:
                        _set(ps, k, tex, "pp")
                else:
                    _set(ps, "override_" + k, True, "pp")
                    _set(ps, k, x, "pp")
            a.set_editor_property("settings", ps)
        if not bake:
            _canopy(world, on)
        log("profile", name, "v2" if on else "v1", "bake" if bake else "")
    except Exception as e:
        log("apply_profile", name, repr(e))


def _cloud_density(world, comp, dens):
    """runtime: a dynamic instance of MI_Clouds with the wanted density (asset value = what build baked)."""
    try:
        mid = STATE["mids"].get("cloud")
        try:
            cur = comp.get_editor_property("material")
        except Exception:
            cur = None
        if mid is None or cur != mid:             # new PIE session (same path names!) -> new component -> new MID
            parent = unreal.load_asset(CLOUD_MI)
            if not parent:
                return
            mid = unreal.MaterialLibrary.create_dynamic_material_instance(world, parent)
            STATE["mids"]["cloud"] = mid
            try:
                comp.set_material(mid)
            except Exception:
                comp.set_editor_property("material", mid)
        mid.set_scalar_parameter_value("Cloud_GlobalDensity", dens)
    except Exception as e:
        log("cloud density", repr(e))


def _load(path):
    """load_asset that also works in PIE. EditorAssetLibrary (does_asset_exist ...) refuses during Play ("The Editor is
    currently in a play mode") and returned False -> the old _canopy silently fell back to V2 in every PIE session: the
    real reason no V3 change (not even the green test glass) ever showed in the 11-06 captures."""
    try:
        return unreal.load_asset(path)
    except Exception:
        return None


def _canopy(world, on):
    path = CANOPY_V1 if not on else (CANOPY_V3 if STATE.get("canopy") == "v3" else CANOPY_V2)
    m = _load(path)
    if m is None and path == CANOPY_V3:
        path = CANOPY_V2
        m = _load(path)
    if not m:
        log("canopy material missing", path)
        return
    for a in unreal.GameplayStatics.get_all_actors_with_tag(world, "Canopy"):
        smc = a.get_component_by_class(unreal.StaticMeshComponent)
        if smc:
            try:                                # V3 is opaque over the scene: drawn before every other translucent
                smc.set_translucent_sort_priority(-10 if path == CANOPY_V3 else 0)
            except Exception as e:
                log("canopy sort", repr(e)[:100])
            fxm = _load(CANOPY_V3FX) if path == CANOPY_V3 else None      # V3: inner shell = glass, outer shell = fx layer
            names = [str(n) for n in smc.get_material_slot_names()]
            for i in range(smc.get_num_materials()):
                outer = fxm is not None and i < len(names) and CANOPY_OUTER_SLOT in names[i]
                smc.set_material(i, fxm if outer else m)
            log("canopy", a.get_name(), "state", STATE.get("canopy"), "slots", names, "->", [x.get_name() if x else None for x in smc.get_materials()])


def set_state(on, sim_client=None, world=None):
    """switch v1 / v2 at runtime and re-apply the client's current preset (realism_shots before / after)."""
    STATE["on"] = bool(on)
    if sim_client is not None:
        c = sim_client.client() if callable(getattr(sim_client, "client", None)) else None
        name = getattr(c, "preset", None) or "monitor"
        sim_client.apply_preset(name, world)


def install_hook(sim_client):
    """every sim_client.apply_look(name, world) also applies the v2 profile (idempotent)."""
    if getattr(sim_client.apply_look, "_realism_v2", False):
        return
    orig = sim_client.apply_look

    def apply_look(name, world):
        orig(name, world)
        apply_profile(name, world)
    apply_look._realism_v2 = True
    sim_client.apply_look = apply_look
    log("hook installed on sim_client.apply_look, state", "v2" if STATE["on"] else "v1")


# ---- off-screen helper (same method as busan_check.py: windows of this process moved off the desktop, no activation,
# the previous foreground window gets focus back) -------------------------------------------------------------------------
def keep_offscreen():
    import ctypes, time
    import ctypes.wintypes as W
    U32 = ctypes.windll.user32
    PID = os.getpid()
    SWP = 0x0001 | 0x0004 | 0x0010            # NOSIZE | NOZORDER | NOACTIVATE
    EnumProc = ctypes.WINFUNCTYPE(ctypes.c_bool, W.HWND, W.LPARAM)
    st = dict(fg=None, t=0.0, h=None)

    def ours(h):
        p = ctypes.c_ulong()
        U32.GetWindowThreadProcessId(h, ctypes.byref(p))
        return p.value == PID

    def hide():
        found = []

        def cb(h, l):
            if ours(h) and U32.IsWindowVisible(h):
                r = W.RECT()
                U32.GetWindowRect(h, ctypes.byref(r))
                if r.left > -20000:
                    if U32.IsZoomed(h) or U32.IsIconic(h):
                        U32.ShowWindow(h, 4)             # SW_SHOWNOACTIVATE (restore, so it keeps rendering)
                    U32.SetWindowPos(h, 0, -32000 + 40 * len(found), -32000, 0, 0, SWP)
                    found.append(h)
            return True
        U32.EnumWindows(EnumProc(cb), 0)
        fg = U32.GetForegroundWindow()
        if fg and not ours(fg):
            st["fg"] = fg
        elif fg and st["fg"] and U32.IsWindow(st["fg"]):
            U32.SetForegroundWindow(st["fg"])

    def tick(dt):
        now = time.monotonic()
        if now - st["t"] > 0.25:
            st["t"] = now
            try:
                hide()
            except Exception as e:
                log("offscreen", repr(e))
    try:                                        # a background editor would be throttled (wrong fps, slow settle)
        eps = unreal.get_default_object(unreal.EditorPerformanceSettings)
        st["throttle"] = eps.get_editor_property("throttle_cpu_when_not_foreground")
        eps.set_editor_property("throttle_cpu_when_not_foreground", False)
    except Exception as e:
        log("background throttle", repr(e))
    hide()
    st["h"] = unreal.register_slate_post_tick_callback(tick)
    OFFSCREEN.update(st)
    return st


OFFSCREEN = {}


def stop_offscreen():
    """unregister the off-screen tick and restore the background throttle setting (call before quitting / handing back)."""
    if OFFSCREEN.get("h"):
        unreal.unregister_slate_post_tick_callback(OFFSCREEN.pop("h"))
    if "throttle" in OFFSCREEN:
        try:
            unreal.get_default_object(unreal.EditorPerformanceSettings).set_editor_property("throttle_cpu_when_not_foreground",
                                                                                          OFFSCREEN.pop("throttle"))
        except Exception as e:
            log("background throttle restore", repr(e))
