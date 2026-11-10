"""Busan global colour grade (11-10): the post-process colour of the whole picture, matched to the statistics of many real
Busan photos (not one photo, not by eye). Single owner of the global grade keys below (saturation, contrast, gamma, gain,
offset, shadows / midtones / highlights, white balance, filmic tone curve, exposure bias); atmos_look.py no longer sets
saturation / contrast (its 11-09 values x1.06 / x1.08 moved here as LEGACY).
Applied at Play from Python, never baked into FlightMap.umap:
  apply(world, preset)   sim_client.apply_look (every quality preset switch), right after atmos_look.apply.
Modes:  grade   GRADE values (default)
        legacy  GYROSIM_GRADE=0: the look before this pass (atmos_look's x1.06 / x1.08 on the map values)
        map     GYROSIM_ATMOS=off: the map's own values (the look before the 11-09 atmosphere pass)
The map value of every key is remembered the first time this module touches it (per world), so legacy / map restore
exactly what was there. Reasons, numbers and sources: docs/grade-busan.md.
"""
import os
import unreal

log = lambda *a: unreal.log("[grade] " + " ".join(str(x) for x in a))
STATE = dict(on=os.environ.get("GYROSIM_GRADE", "1") not in ("0", "off", "false"), orig={}, mode=None)

# the 11-09 atmosphere pass's global grade (was atmos_look.AIR["pp"])
LEGACY = dict(color_saturation=(1.0, 1.0, 1.0, 1.06), color_contrast=(1.0, 1.0, 1.0, 1.08))

# measured grade (values: docs/grade-busan.md). Vector4 = (R, G, B, all); 1.0 = neutral.
# Gap before (median of 13 views vs 90 real photos / 59 photographers, CIELAB): blacks lifted (city L* p5 21 vs 13),
# whites dull (p95 75 vs 85), low contrast (city sigma L* 16 vs 21), blue cast on the ground (city b* -3 .. -5 vs 0,
# grey-world R/G 0.76 vs 0.84), grey sky (C* 6 vs 12). Building chroma was already right (C* 10 vs 9.5).
GRADE = dict(
    # warmer land, sky kept blue: a little global warming (engine 6500 K) + warm gain on shadows / mid-tones only
    # (land), highlights (sky, clouds) untouched. 7500 K globally fixed the land but greyed the sky (sweep 11-10).
    white_temp=6900.0,
    color_gain_shadows=(1.05, 1.0, 0.92, 1.0), color_gain_midtones=(1.05, 1.0, 0.92, 1.0),
    auto_exposure_bias=0.35,               # map 0.3 (+0.05 EV; the bluer sky factor below also brightens the sky light)
    film_slope=1.0, film_toe=0.6,          # filmic curve (engine 0.88 / 0.55): steeper S, deeper blacks (0.65 crushed low views)
    color_contrast=(1.0, 1.0, 1.0, 1.2),   # was 1.08 (1.3 crushed shadows between buildings to L* 1-4 in low views)
    color_saturation=(1.0, 1.0, 1.0, 0.88),  # the steeper curve adds chroma; this keeps buildings / trees near the photos' C*
    # bluer sky luminance (realism v2 0.80 / 0.86 / 1.0), sky pixels (and the sky light it captures)
    **{"sky.sky_luminance_factor": (0.42, 0.72, 1.35)},
)
# per preset additions (VR: same colour; nothing preset-specific yet)
PRESET = {"monitor": {}, "vr": {}}
# keys other modules set on every apply_look before this one (sim_client.PRESET_LOOK, realism_v2): overridden when the
# grade has them, never restored here
OTHERS = {"vignette_intensity", "bloom_intensity", "local_exposure_shadow_contrast_scale",
          "local_exposure_highlight_contrast_scale", "auto_exposure_min_brightness"}


def _vec(v):
    if isinstance(v, (tuple, list)):
        return unreal.Vector4(*v) if len(v) == 4 else unreal.LinearColor(v[0], v[1], v[2], 1.0)
    return v


def _get(ps, k):
    try:
        v = ps.get_editor_property(k)
        if isinstance(v, unreal.Vector4):
            return (v.x, v.y, v.z, v.w)
        if isinstance(v, unreal.LinearColor):
            return (v.r, v.g, v.b)
        return v
    except Exception:
        return None


def _set(ps, k, v):
    try:
        ps.set_editor_property(k, _vec(v))
        return True
    except Exception as e:
        log("skip", k, repr(e)[:120])
        return False


def mode():
    try:
        import atmos_look
        if not atmos_look.STATE["on"]:
            return "map"
    except Exception:
        pass
    return "grade" if STATE["on"] else "legacy"


def values(preset="monitor", m=None):
    m = m or mode()
    if m == "grade":
        return dict(GRADE, **PRESET.get(preset, {}))
    if m == "legacy":
        return dict(LEGACY)
    return {}


def apply(world, preset="monitor", m=None, extra=None):
    """global grade for every PostProcessVolume of `world`. m: 'grade' | 'legacy' | 'map' (default from the env).
    extra: key -> value overrides on top (offscreen sweeps only)."""
    if world is None:
        return
    m = m or mode()
    want = values(preset, m)
    if extra:
        want.update(extra)
    try:
        # "sky.<prop>" = SkyAtmosphereComponent property (realism_v2 sets sky_luminance_factor before every call: no restore)
        for k in [k for k in want if k.startswith("sky.")]:
            v = want.pop(k)
            for a in unreal.GameplayStatics.get_all_actors_of_class(world, unreal.SkyAtmosphere):
                c = a.get_component_by_class(unreal.SkyAtmosphereComponent)
                if c is not None:
                    _set(c, k[4:], v)
        orig = STATE["orig"].setdefault(world.get_path_name(), {})
        keys = set(orig) | set(want) | set(GRADE) | set(LEGACY)
        keys = {k for k in keys if not k.startswith("sky.")}
        for a in unreal.GameplayStatics.get_all_actors_of_class(world, unreal.PostProcessVolume):
            ps = a.get_editor_property("settings")
            for k in keys:
                if k in OTHERS:                      # set again by sim_client / realism_v2 before every call: no restore
                    if k in want:
                        _set(ps, "override_" + k, True)
                        _set(ps, k, want[k])
                    continue
                if k not in orig:
                    orig[k] = (_get(ps, "override_" + k), _get(ps, k))
                if k in want:
                    _set(ps, "override_" + k, True)
                    _set(ps, k, want[k])
                else:
                    ov, v0 = orig[k]
                    _set(ps, "override_" + k, bool(ov))
                    if v0 is not None:
                        _set(ps, k, v0)
            a.set_editor_property("settings", ps)
        STATE["mode"] = m
        log(preset, m, len(want), "keys")
    except Exception as e:
        log("apply failed", repr(e))
