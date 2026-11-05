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
Switches: GYROSIM_REALISM_V2=0 at build = pure v1 level; GYROSIM_REALISM_V2_RUNTIME=off = v1 values at runtime.
GPU cost numbers in comments are estimates (not measured) until phase 2.
"""
import os
import unreal

log = lambda *a: unreal.log("[realism_v2] " + " ".join(str(x) for x in a))
ENABLED = os.environ.get("GYROSIM_REALISM_V2", "1") != "0"
STATE = dict(on=os.environ.get("GYROSIM_REALISM_V2_RUNTIME", "on") != "off", mids={})

CK_MAT = "/Game/Cockpit/Materials"
CANOPY_V1 = CK_MAT + "/M_CkCanopy"
CANOPY_V2 = CK_MAT + "/M_CkCanopyV2"
CLOUD_MI = "/Game/Materials/MI_Clouds"

# ---- values -----------------------------------------------------------------------------------------------------------
# v1 (restore values for the 'off' state): what build_level.py sets, or the engine default where v1 sets nothing.
V1 = dict(
    light=dict(light_source_angle=0.53, cast_shadows_on_atmosphere=False, cloud_shadow_extent=150.0),
    sky=dict(sky_luminance_factor=(1.0, 1.0, 1.0)),
    skylight=dict(cloud_ambient_occlusion=False),
    cloud=dict(stop_tracing_transmittance_threshold=0.005),
    cloud_density=0.045,
    pp=dict(bloom_method="standard", bloom_intensity=0.35, lens_flare_intensity=None,      # None = no override (engine default)
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
                    pp=dict(bloom_method="convolution", bloom_intensity=0.6, lens_flare_intensity=0.12)),
    # VR (90 Hz both eyes): no lens effects (eyes have no lens ghosts), standard bloom, cheaper clouds (guide #9).
    "vr": dict(light=dict(cast_shadows_on_atmosphere=False), cloud=dict(stop_tracing_transmittance_threshold=0.01),
               pp=dict(bloom_method="standard", bloom_intensity=0.3, lens_flare_intensity=0.0)),
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
    if n == 0 and use_env:                       # compile failed (e.g. node not allowed here) -> constant sky colour
        return _canopy_v2(g, sun_dir, use_env=False)
    return m


def build(g):
    """build_level.py hook (editor world, before the level is saved)."""
    if not ENABLED:
        log("off (GYROSIM_REALISM_V2=0) - level stays v1")
        return
    try:
        sd = g["sun"].get_actor_forward_vector()
        sg = (g.get("F16") or {}).get("F16_Glass")
        if sg:
            cm = _canopy_v2(g, (-sd.x, -sd.y, -sd.z))
            for i in range(len(sg.static_materials)):
                sg.set_material(i, cm)
            unreal.EditorAssetLibrary.save_loaded_asset(sg)
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
            mid = unreal.KismetMaterialLibrary.create_dynamic_material_instance(world, parent)
            STATE["mids"]["cloud"] = mid
            try:
                comp.set_material(mid)
            except Exception:
                comp.set_editor_property("material", mid)
        mid.set_scalar_parameter_value("Cloud_GlobalDensity", dens)
    except Exception as e:
        log("cloud density", repr(e))


def _canopy(world, on):
    m = unreal.load_asset(CANOPY_V2 if on else CANOPY_V1)
    if not m:
        log("canopy material missing", CANOPY_V2 if on else CANOPY_V1)
        return
    for a in unreal.GameplayStatics.get_all_actors_with_tag(world, "Canopy"):
        smc = a.get_component_by_class(unreal.StaticMeshComponent)
        if smc:
            for i in range(smc.get_num_materials()):
                smc.set_material(i, m)


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
