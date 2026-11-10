"""Backlight fill (11-10): shaded / backlit facades get sky and ground bounce light like in real photos.
Applied at Play from Python (atmos_look.apply calls apply() on every quality preset switch; never baked into FlightMap.umap).
Switch: GYROSIM_BACKLIGHT_FIX=0 = the look before this pass (map values). Reasons and numbers: docs/haze-backlight-busan.md.

Cause (measured, offscreen A/B on the art_shots views): the sky light (real-time capture) has 'lower hemisphere is solid
colour' on with black, and Lumen cannot see the ground: the Cesium terrain / building tiles are runtime meshes without mesh
distance fields (software Lumen, no hardware ray tracing) and Lumen's scene ends at 200 m (lumen_scene_view_distance) while the
camera flies at 100-3000 m. Every diffuse ray that leaves the screen therefore ends in the sky light cubemap, whose lower half
was black: a vertical facade saw only the upper sky (half its hemisphere) and no ground bounce at all - backlit walls went
near-black (backlit morning view: 97 % of the city pixels below L* 15). Fix: the lower hemisphere stays a solid colour but
a dim ground grey instead of black = the missing ground bounce (and the ground under the horizon in sky-light reflections).
Tried: lower hemisphere from the capture (the sky atmosphere's virtual planet ground, even with ground albedo 0.05 / 0.10)
= washed-out white facades in every view (the virtual ground carries the bright low haze); Lumen sky-light leaking 0.15
= almost no change in backlight. The colour is in the captured sky's units (sun 10 lux in this project) and does not follow
the sun - the sim has one fixed sun (atmos_look.SUN_*); a moving sun would need it scaled with sin(elevation).
"""
import os
import unreal

log = lambda *a: unreal.log("[light] " + " ".join(str(x) for x in a))
STATE = dict(on=os.environ.get("GYROSIM_BACKLIGHT_FIX", "1") != "0", orig={})

VALUES = dict(
    skylight=dict(lower_hemisphere_is_black=True, lower_hemisphere_color=(0.25, 0.25, 0.235)),
    sky=dict(),
    pp=dict(),
)


def _actors(world, cls):
    return list(unreal.GameplayStatics.get_all_actors_of_class(world, cls)) if world else []


def apply(world, preset="monitor", on=None):
    on = STATE["on"] if on is None else on
    if world is None:
        return
    import atmos_look
    _get, _set = atmos_look._get, atmos_look._set
    try:
        orig = STATE["orig"].setdefault(world.get_path_name(), dict(skylight={}, sky={}, pp={}))
        for tag, cls, ccls in (("skylight", unreal.SkyLight, unreal.SkyLightComponent),
                               ("sky", unreal.SkyAtmosphere, unreal.SkyAtmosphereComponent)):
            for a in _actors(world, cls):
                c = a.get_component_by_class(ccls)
                if c is None:
                    continue
                for k, v in VALUES[tag].items():
                    if k not in orig[tag]:
                        orig[tag][k] = _get(c, k)
                    want = v if on else orig[tag][k]
                    if want is not None:
                        _set(c, k, want, tag)
        for a in _actors(world, unreal.PostProcessVolume):
            ps = a.get_editor_property("settings")
            for k, v in VALUES["pp"].items():
                if k not in orig["pp"]:
                    orig["pp"][k] = (_get(ps, "override_" + k), _get(ps, k))
                ov, v0 = orig["pp"][k]
                _set(ps, "override_" + k, True if on else bool(ov), "pp")
                if on or v0 is not None:
                    _set(ps, k, v if on else v0, "pp")
            a.set_editor_property("settings", ps)
        log(preset, "on" if on else "off (map values)")
    except Exception as e:
        log("apply failed", repr(e))
