"""Busan / Korea air and light (11-09): hazy coastal air, sun from the south, sea surface and V-World photo colour match.
Applied at Play from Python (never baked into FlightMap.umap, so the map file is not touched while an editor has it open):
  apply(world, preset)    sim_client.apply_look (every quality preset switch, after realism v2): sun, sky atmosphere,
                          height fog, sky light, post process. The first call remembers the map's values ('before').
  apply_ground(tileset)   sim_client._vworld_ground: the V-World terrain tileset gets /Game/Materials/Ground/MI_GyroGround
                          (Scripts/ground_material.py + ground_look.hlsl: sea surface + photo colour match).
Switch: GYROSIM_ATMOS=off (or STATE['on'] = False and apply again) = the look before this pass (map + realism v2 values,
Cesium's stock ground material). Reasons, sources and before / after numbers: docs/atmosphere-busan.md.
"""
import math, os
import unreal

log = lambda *a: unreal.log("[atmos] " + " ".join(str(x) for x in a))
STATE = dict(on=os.environ.get("GYROSIM_ATMOS", "on") != "off", orig={})
GROUND_MI = "/Game/Materials/Ground/MI_GyroGround"

# ---- air / light -------------------------------------------------------------------------------------------------------
# Sun: south-west, 42 deg up (~14 h local in spring / autumn). The map had it in the north-west (azimuth 325), which the
# sun never is at 38 deg elevation in Korea, and V-World orthophotos (shot around midday) have their baked shadows
# pointing north - with the sun in the south the 3D buildings' shadows now agree with the photo's.
SUN_AZ, SUN_EL = 215.0, 42.0
AIR = dict(
    # Mie = aerosol haze. Visibility V = 3.912 / extinction (Koschmieder). Busan daytime visibility is mostly 15-25 km
    # and Korean aerosol optical depth ~0.3-0.4, i.e. Mie extinction ~0.15-0.2 /km in a ~1.2 km mixed layer. The engine
    # default (0.004 /km scattering, x1.3 in the map) is clean-air (V > 300 km): distant ground did not fade at all.
    # Tuned against the reference photos (far-ridge contrast, docs/atmosphere-busan.md): green-channel Mie scattering
    # 0.07 /km (+ Rayleigh 0.013) = visibility ~45 km at the ground, thinning with height (1.2 km scale height).
    # Colour: aerosol scattering falls with wavelength (Angstrom exponent ~1.3 for urban / coastal aerosol), so the
    # red / green / blue coefficients are (680/550)^-1.3 : 1 : (440/550)^-1.3 = 0.76 : 1 : 1.34 -> blue-grey haze
    # instead of the engine's grey (white Mie); picked a bit bluer (0.45 : 0.70 : 1) from the photo comparison (far
    # ridge / horizon chroma). Little absorption (single-scattering albedo ~0.97, coastal / sea-salt mix) and phase
    # anisotropy g 0.6 (engine 0.8; measured aerosol g ~0.6-0.7): the haze is brighter, also looking away from the sun
    # - with 0.8 / 9 % absorption the horizon came out darker and greyer than in every reference photo.
    sky=dict(mie_scattering_scale=0.093, mie_scattering=(0.45, 0.70, 1.0), mie_absorption_scale=0.002,
             mie_absorption=(1.0, 1.0, 1.0), mie_anisotropy=0.6, mie_exponential_distribution=1.2,
             aerial_pespective_view_distance_scale=1.0),
    # the old height fog had a fixed blue in-scatter colour (no sun direction): now mostly the sky atmosphere does the haze
    fog=dict(fog_density=0.00002, fog_height_falloff=0.2),
    # photo-like grade: the hazier air lowers contrast everywhere; a little global contrast / saturation brings the near
    # field back to the reference photos' numbers (near-field sigma L* 20-25, chroma 7-13) - measured, not by eye only
    pp=dict(color_saturation=(1.0, 1.0, 1.0, 1.06), color_contrast=(1.0, 1.0, 1.0, 1.08)),
    # camera-like finish: photos are sharpened in-camera; a light tonemapper sharpen on the monitor only (VR: none,
    # it shimmers on the headset's moving pixels)
    cvars=dict(monitor={"r.Tonemapper.Sharpen": 0.5}, vr={"r.Tonemapper.Sharpen": 0.0}),
)
# sun direction -> light rotator (light travels away from the sun: yaw = azimuth - 180, pitch = -elevation)
SUN_ROT = (-SUN_EL, SUN_AZ - 180.0)

# ---- ground material parameters (MI_GyroGround; defaults of M_GyroGround) ---------------------------------------------
GROUND = dict(
    WaterOn=1.0,
    SeaH0=1.0, SeaH1=3.5,              # m above the sea: full water below SeaH0, land above SeaH1
    GuardL0=0.20, GuardL1=0.35,        # photo luminance (linear): brighter = ship / pier / foam, stays land
    GuardB0=0.002, GuardB1=0.010,      # B - R (linear): below = grey / brown rock or quay, stays land
    CurvM=635500000.0, CurvN=638500000.0,    # cm, WGS84 meridian / prime-vertical radii at 35.2 N
    PhotoSeaLum=0.05,                  # typical V-World sea luminance (linear) - the photo's variation is kept around it
    ShallowSat=0.35, ShallowGain=0.8, ShallowMix=0.4,
    WaterRough=0.08, WaterRoughFar=0.22, WaterSpec=0.25,     # water F0 = 0.02 -> Specular 0.25
    WaveScale=1800.0, WaveStrength=0.12, WaveFadeM=1500.0,
    LandSat=1.0, LandContrast=1.0, LandMid=0.12, LandGain=1.0,     # photo colours as they are (x1.08 overshot the photos' chroma)
    DeepColor=(0.045, 0.090, 0.140), LandTint=(1.0, 1.0, 1.0),
)


def _set(obj, k, v, tag):
    try:
        if isinstance(v, (tuple, list)):
            v = unreal.Vector4(*v) if len(v) == 4 else unreal.LinearColor(v[0], v[1], v[2], 1.0)   # colour grading = Vector4
        obj.set_editor_property(k, v)
    except Exception as e:
        log("skip", tag, k, repr(e)[:120])


def _get(obj, k):
    try:
        v = obj.get_editor_property(k)
        if isinstance(v, unreal.LinearColor):
            return (v.r, v.g, v.b)
        if isinstance(v, unreal.Vector4):
            return (v.x, v.y, v.z, v.w)
        return v
    except Exception:
        return None


def _actors(world, cls):
    return list(unreal.GameplayStatics.get_all_actors_of_class(world, cls)) if world else []


def _comps(world):
    out = {}
    for cls, ccls, tag in ((unreal.SkyAtmosphere, unreal.SkyAtmosphereComponent, "sky"),
                           (unreal.ExponentialHeightFog, unreal.ExponentialHeightFogComponent, "fog"),
                           (unreal.DirectionalLight, unreal.DirectionalLightComponent, "light")):
        for a in _actors(world, cls):
            out.setdefault(tag, []).append((a, a.get_component_by_class(ccls)))
    return out


def apply(world, preset="monitor", on=None):
    """air / light values (on) or the remembered map values (off) for this world. The map value of every property is
    remembered the first time this pass touches it (per world), so 'off' restores exactly what was there."""
    on = STATE["on"] if on is None else on
    if world is None:
        return
    try:
        cs = _comps(world)
        orig = STATE["orig"].setdefault(world.get_path_name(), dict(sky={}, fog={}, pp={}, sun=None, cvars={}))
        if orig["sun"] is None and cs.get("light"):
            r = cs["light"][0][0].get_actor_rotation()
            orig["sun"] = (r.pitch, r.yaw)
        for tag in ("sky", "fog"):
            for _, c in cs.get(tag, []):
                for k, v in AIR[tag].items():
                    if k not in orig[tag]:
                        orig[tag][k] = _get(c, k)
                    want = v if on else orig[tag][k]
                    if want is not None:
                        _set(c, k, want, tag)
                if not on:                                       # keys an earlier 'on' call set but AIR no longer has
                    for k, v0 in orig[tag].items():
                        if k not in AIR[tag] and v0 is not None:
                            _set(c, k, v0, tag)
        rot = SUN_ROT if on else orig["sun"]
        if rot:
            for a, _ in cs.get("light", []):
                a.set_actor_rotation(unreal.Rotator(roll=0.0, pitch=rot[0], yaw=rot[1]), False)
        for a in _actors(world, unreal.PostProcessVolume):
            ps = a.get_editor_property("settings")
            for k, v in AIR["pp"].items():
                if k not in orig["pp"]:
                    orig["pp"][k] = (_get(ps, "override_" + k), _get(ps, k))
            for k, (ov, v0) in list(orig["pp"].items()):
                if on and k in AIR["pp"]:
                    _set(ps, "override_" + k, True, "pp")
                    _set(ps, k, AIR["pp"][k], "pp")
                else:
                    _set(ps, "override_" + k, bool(ov), "pp")
                    if v0 is not None:
                        _set(ps, k, v0, "pp")
            a.set_editor_property("settings", ps)
        for k, v in AIR.get("cvars", {}).get(preset, {}).items():
            if k not in orig["cvars"]:
                orig["cvars"][k] = unreal.SystemLibrary.get_console_variable_float_value(k)
            unreal.SystemLibrary.execute_console_command(world, "%s %s" % (k, v if on else orig["cvars"][k]))
        log("air", preset, "on" if on else "off (map values)")
    except Exception as e:
        log("apply failed", repr(e))


def _pps(world):
    for a in _actors(world, unreal.PostProcessVolume):
        return a.get_editor_property("settings")
    return None


def write_ground_params(mi, params):
    """parameters into a MaterialInstanceConstant (editor; the tileset's dynamic instances inherit them)."""
    MEL = unreal.MaterialEditingLibrary
    for k, v in params.items():
        if isinstance(v, (tuple, list)):
            MEL.set_material_instance_vector_parameter_value(mi, k, unreal.LinearColor(*(list(v) + [1.0])[:4]))
        else:
            MEL.set_material_instance_scalar_parameter_value(mi, k, float(v))
    MEL.update_material_instance(mi)


def apply_ground(tileset, on=None):
    """V-World terrain tileset material: MI_GyroGround (on) or Cesium's stock material (off / asset missing).
    Call before refresh_tileset (the tiles take the material when they are created)."""
    on = STATE["on"] if on is None else on
    if tileset is None:
        return False
    m = None
    if on:
        try:                                     # load_asset, not does_asset_exist: the asset registry may still be scanning
            m = unreal.load_asset(GROUND_MI)
        except Exception:
            m = None
    try:
        tileset.set_editor_property("material", m)
        log("ground material", GROUND_MI if m else "Cesium default")
    except Exception as e:
        log("ground material failed", repr(e))
    return m is not None
