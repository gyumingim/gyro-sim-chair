"""Busan / Korea air and light (11-09): hazy coastal air, sun from the south, sea surface and V-World photo colour match.
Applied at Play from Python (never baked into FlightMap.umap, so the map file is not touched while an editor has it open):
  apply(world, preset)    sim_client.apply_look (every quality preset switch, after realism v2): sun, sky atmosphere,
                          height fog, sky light, post process. The first call remembers the map's values ('before').
  apply_ground(tileset)   sim_client._vworld_ground: the V-World terrain tileset gets /Game/Materials/Ground/MI_GyroGround
                          (Scripts/ground_material.py + ground_look.hlsl: sea surface + photo colour match);
                          GYROSIM_SEA_LOOK=0 = MI_GyroGround_Sea0, the sea before the 11-10 pass (A/B).
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
    # global colour grade (was saturation x1.06 / contrast x1.08 here): moved to grade_look.py (11-10, single owner;
    # those values are grade_look.LEGACY = GYROSIM_GRADE=0)
    pp=dict(),
    # camera-like finish: photos are sharpened in-camera; a light tonemapper sharpen on the monitor only (VR: none,
    # it shimmers on the headset's moving pixels)
    cvars=dict(monitor={"r.Tonemapper.Sharpen": 0.5}, vr={"r.Tonemapper.Sharpen": 0.0}),
)
# sun direction -> light rotator (light travels away from the sun: yaw = azimuth - 180, pitch = -elevation)
SUN_ROT = (-SUN_EL, SUN_AZ - 180.0)

# ---- haze v2 (11-10, docs/haze-backlight-busan.md; GYROSIM_HAZE_V2=0 = the values above) --------------------------------
# Distant clouds stayed sharp down to the horizon with a thin lavender line under them, distant land too clear / yellow.
# Measured causes (offscreen A/B, same run, frozen clouds):
#  - the Mie haze lives in the sky atmosphere with a 1.2 km scale height, so clouds (1.06-3.7 km) and the air in front of
#    them are nearly clean; the clouds DO get aerial perspective (r.VolumetricCloud.EnableAerialPerspectiveSampling 0 made
#    them visibly harder), there is just too little of it at cloud height. Mie x3.2 hazed them but turned the whole land
#    beige / flat (it scales the haze near the camera too).
#  - the height fog was effectively off (density 0.00002) and its falloff 0.2 means a layer ~50 m thick (UE halves the
#    density every 1000 / falloff cm): the art pass's fog test (falloff 0.35) was a 29 m layer under the camera - no effect.
#  - the lavender line = clear sky between the sea horizon and the last clouds, tinted by the grade's sky luminance factor
#    (0.42, 0.72, 1.35); nothing in front of it to hide it.
# Fix: a boundary-layer height fog (the sea-level haze of Busan's 15-25 km visibility): falloff 0.012 = density halves
# every ~0.8 km (Korean mixed layer ~1-1.5 km), starting 3 km from the camera so near views keep their contrast, blue-grey
# in-scatter (the engine default light-blue luminance; the sky-ambient-only version, in-scatter 0, gave a dark blue band).
# The fog is applied to the volumetric clouds too (r.VolumetricCloud.ApplyFogLate 1): far clouds fade into the haze band.
HAZE_V2 = os.environ.get("GYROSIM_HAZE_V2", "0") != "0"     # TEMP default off while tuning
HAZE_FOG = dict(fog_density=0.0008, fog_height_falloff=0.012, start_distance=300000.0,
                fog_inscattering_luminance=(0.35, 0.45, 0.6))
if HAZE_V2:
    AIR["fog"] = dict(AIR["fog"], **HAZE_FOG)

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
    # land micro-texture (11-10, ground_look.hlsl; GYROSIM_GROUND_SHARP=0 sets DetailAmp 0 at Play): +-7 % luminance noise
    # at 0.13 / 0.37 m, full on vegetation, 55 % on grey ground / roads, 25 % on bright roofs, faded 150 -> 700 m
    DetailAmp=0.07, DetailL1=0.13, DetailL2=0.37, DetailVeg=1.0, DetailGrey=0.55, DetailBright=0.25,
    DetailNear=150.0, DetailFar=700.0,
    # art pass 11-10 (ground_look.hlsl, SeaArt 1 only in MI_GyroGround via SEA_ART): sea without a visible wave-texture
    # repeat - rotated second copy of the small octaves, rough / calm patches (noise SeaMacroM m, +-SeaMacroAmp), small
    # octaves faded by screen footprint
    SeaArt=0.0, SeaMacroM=420.0, SeaMacroAmp=0.5,
    # trees v2 (11-10, ground_look.hlsl): crown-sized pattern on dark-green photo forest (beyond the 3D trees);
    # GYROSIM_TREES_CANOPY=0 (or GYROSIM_TREES_V2=0) sets CanopyAmp 0 at Play
    CanopyAmp=1.0, CanopyM=5.5, CanopyDark=0.45, CanopyBump=0.9,
)
GROUND_SHARP = os.environ.get("GYROSIM_GROUND_SHARP", "1") != "0"
# Sea pass 11-10 (GYROSIM_SEA_LOOK=0 = the 11-09 values above, MI_GyroGround_Sea0). Measured on the landmark shots
# (same view, Play look): Marine City from the sea, near sea sRGB ~(102, 127, 144) vs the photo ~(40, 89, 141) - the
# blue matches, red / green are too high = too much grey horizon sky in the reflection, too little blue body.
#  - wave slopes: WaveStrength 0.12 gave ~3-7 deg slopes, so the far sea mirrored only the pale hazy horizon. Sea-surface
#    slope statistics (Cox & Munk 1954: variance ~0.003 + 0.00512 U, U = wind m/s) give ~10 deg rms at 5 m/s -> 0.2: the
#    wave faces reflect higher, bluer sky (and the backs show the water body);
#  - water body: bluer, a little brighter deep colour (the deep sea took the V-World photo's dark teal-green, from the
#    orthophoto grade / sun angle; daylight Busan sea in the photos is medium blue). The shallow mix toward the photo stays
#    (turquoise water at rocks / beaches: Taejongdae photo near the cliffs sRGB ~(54, 115, 120)).
# Measured after (same views): Marine City from the sea (75, 117, 159), behind the Gwangan bridge (43, 87, 130) vs photo
# (40, 89, 141) - first pass with ShallowMix 0.15 turned the Taejongdae shallows deep blue (18, 76, 135), so it is back to 0.4.
# Second pass: deep colour (0.022, 0.075, 0.185) measured Taejongdae from 120 m (11, 50, 112) - too dark / saturated
# against the photo's teal (54, 115, 120) - and Gwangan bridge view (31, 70, 119) vs (40, 89, 141): a bit greener, less blue.
SEA_NEW = dict(DeepColor=(0.030, 0.085, 0.165), WaveStrength=0.2)
SEA_ON = os.environ.get("GYROSIM_SEA_LOOK", "1") != "0"
# Art pass 11-10 (docs/art-busan.md): GYROSIM_SEA_ART=0 = the sea of SEA_NEW (dynamic instance at Play).
# Measured (SegFormer sea region, median of the sweep views vs 66 real photos with sea, refs/grade): SEA_NEW sea C* 22-25 /
# hue 263-265 / b* -21..-25 (royal blue) vs photos 14.4 / 241 / -12.1 (steel / teal blue). Most of the colour is the
# reflected (blue-graded) sky: a slightly lower water specular (0.19: F0 0.015, grazing reflection ~0.75) and rougher
# water (reflections blur toward the pale horizon) + a greener deep colour. Sweep: (0.040, 0.100, 0.115) / spec 0.18 hit
# C* 14.1 but hue 223 (too green); (0.035, 0.090, 0.140) / spec 0.20 C* 18.5 / hue 257; this is in between.
SEA_ART = dict(SeaArt=1.0, DeepColor=(0.038, 0.096, 0.128), WaterRough=0.115, WaterRoughFar=0.29, WaterSpec=0.19)
GROUND_MI_SEA0 = "/Game/Materials/Ground/MI_GyroGround_Sea0"
# Coast v2 (11-10, ground_look.hlsl "coast v2", coast_look.py, sim/coast_build.py docstring): OSM coastline signed
# distance field T_GyroCoast -> crisp shore, bridge ghosts masked out of the sea photo, procedural sea beyond SeaPhotoFar m
# from the shore (no photo-tile seams), concrete faces on the man-made shore step of the coast-aware terrain.
# SEA_COAST_DEF = material defaults (CoastOn 0 = the sea rule before, also MI_GyroGround_Sea0); SEA_COAST = MI_GyroGround.
# A/B at Play (dynamic instance): GYROSIM_COAST_V2=0 -> CoastOn 0, GYROSIM_SEA_MASK=0 -> BridgeMaskOn 0.
SEA_COAST_DEF = dict(CoastOn=0.0, CoastD=40.0, BridgeD=40.0, FarD=1000.0, BridgeMaskOn=1.0, CoastGuardM=40.0, CoastInlandM=60.0,
                     SeaPhotoNear=40.0, SeaPhotoFar=160.0, WetBandM=0.6, SeaWallColor=(0.30, 0.30, 0.28), SeaWallWet=(0.075, 0.08, 0.07))
SEA_COAST = dict(SEA_COAST_DEF, CoastOn=1.0)


def _set(obj, k, v, tag):
    try:
        if isinstance(v, (tuple, list)):
            v0 = v
            v = unreal.Vector4(*v) if len(v) == 4 else unreal.LinearColor(v[0], v[1], v[2], 1.0)   # colour grading = Vector4
            if k in FCOLOR_KEYS:                 # FColor properties (sRGB bytes), e.g. SkyAtmosphere ground_albedo
                v = unreal.Color(r=int(v0[0]), g=int(v0[1]), b=int(v0[2]), a=255)
        obj.set_editor_property(k, v)
    except Exception as e:
        log("skip", tag, k, repr(e)[:120])


FCOLOR_KEYS = {"ground_albedo"}


def _get(obj, k):
    try:
        v = obj.get_editor_property(k)
        if isinstance(v, unreal.LinearColor):
            return (v.r, v.g, v.b)
        if isinstance(v, unreal.Vector4):
            return (v.x, v.y, v.z, v.w)
        if isinstance(v, unreal.Color):
            return (v.r, v.g, v.b)
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
    try:                                         # backlight fill (sky light lower hemisphere): light_look.py
        import light_look
        light_look.apply(world, preset, on=(light_look.STATE["on"] and on))
    except Exception as e:
        log("light look", repr(e))


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
            m = unreal.load_asset(GROUND_MI if SEA_ON else GROUND_MI_SEA0)     # Sea0 = the sea before 11-10
        except Exception:
            m = None
    off = {}
    if m is not None and SEA_ON and os.environ.get("GYROSIM_SEA_ART", "1") == "0":
        off.update({k: dict(GROUND, **SEA_NEW)[k] for k in SEA_ART})
    if m is not None and not GROUND_SHARP:
        off["DetailAmp"] = 0.0
    if m is not None and SEA_ON:                 # coast v2 A/B toggles + the world -> coast mask mapping (coast_look.py)
        try:
            import coast_look
            off.update(coast_look.ground_params_off())
            coast_look.start(tileset)
        except Exception as e:
            log("coast look", repr(e))
    if m is not None and os.environ.get("GYROSIM_TREES_CANOPY", os.environ.get("GYROSIM_TREES_V2", "1")) == "0":
        off["CanopyAmp"] = 0.0                   # trees v2 ground canopy pattern off (A/B)
    if off:       # A/B: render-time ground detail off (Cesium copies a dynamic instance's
        try:                                     # parameter values onto every tile's material)
            m = unreal.MaterialLibrary.create_dynamic_material_instance(tileset.get_world(), m)
            for k, v in off.items():
                if isinstance(v, (tuple, list)):
                    m.set_vector_parameter_value(k, unreal.LinearColor(*(list(v) + [1.0])[:4]))
                else:
                    m.set_scalar_parameter_value(k, float(v))
        except Exception as e:
            log("ground params off failed", repr(e))
    try:
        tileset.set_editor_property("material", m)
        log("ground material", (GROUND_MI if SEA_ON else GROUND_MI_SEA0) if m else "Cesium default", "sharp", GROUND_SHARP,
            "sea art", os.environ.get("GYROSIM_SEA_ART", "1"))
    except Exception as e:
        log("ground material failed", repr(e))
    return m is not None
