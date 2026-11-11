"""Live look tuning (11-11, docs/grounded-day-busan.md 'sliders'): the slider page (http://127.0.0.1:8767/today/busan_tune/,
server sim/tune_server.py on 127.0.0.1:8768) writes C:/GyroSimTiles/tune/params.json; this module re-reads it whenever its
mtime changes (light Slate tick, 0.5 s) and applies the values at once, no restart:
  sun_az / sun_el (deg)          sun direction (then atmos_look.apply_grounded: low-sun cloud shadow rule)
  sun_mult, sky_mult             DirectionalLight / SkyLight intensity x (of the values at the first apply)
  exposure_bias                  PostProcessVolume auto exposure bias (EV, absolute)
  le_shadow / le_highlight       local exposure shadow / highlight contrast scale (1 = no lift / compression)
  GdBase .. GdLeanDark           grounded-day material values through MPC_GyroTune (TuneA..C; TuneOn = 1)
Defaults: tune_defaults.json next to this file (the slider page's '저장' writes it; in git, numbers only).
Values missing from both files leave the look as the other modules set it. GYROSIM_TUNE=0 = off (nothing is read).
"""
import json, os, time
import unreal

PARAMS = os.environ.get("GYROSIM_TUNE_FILE", r"C:/GyroSimTiles/tune/params.json")
DEFAULTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tune_defaults.json")
MPC = "/Game/Materials/Ground/MPC_GyroTune"
GD_KEYS = (("TuneA", ("TuneOn", "GdBase", "GdBaseH", "GdGrad")), ("TuneB", ("GdGradH", "GdFloor", "GdAO", "GdTint")),
           ("TuneC", ("GdSat", "GdGroundAO", "GdCanyonAlb", "GdLeanDark")))
ST = dict(h=None, world=None, mtime=None, t=0.0, orig={}, applied={})
log = lambda *a: unreal.log("[tune] " + " ".join(str(x) for x in a))


def on():
    return os.environ.get("GYROSIM_TUNE", "1") != "0"


def _read(p):
    try:
        with open(p, encoding="utf-8-sig") as f:
            d = json.load(f)
        return {k: v for k, v in d.items() if not k.startswith("_")}
    except Exception:
        return {}


def values():
    """defaults (tune_defaults.json) overridden by the live file (params.json)"""
    v = _read(DEFAULTS)
    v.update(_read(PARAMS))
    return v


def _actors(w, cls):
    return unreal.GameplayStatics.get_all_actors_of_class(w, cls)


def apply(world=None, v=None):
    w = world or ST.get("world")
    if w is None:
        return {}
    v = values() if v is None else v
    o = ST["orig"]
    if "sun_az" in v or "sun_el" in v:
        try:
            import atmos_look
            az = float(v.get("sun_az", atmos_look.SUN_AZ)); el = float(v.get("sun_el", atmos_look.SUN_EL))
            for a in _actors(w, unreal.DirectionalLight):
                a.set_actor_rotation(unreal.Rotator(roll=0.0, pitch=-el, yaw=az - 180.0), False)
            atmos_look.apply_grounded(w)
        except Exception as e:
            log("sun", repr(e))
    for key, cls, ccls in (("sun_mult", unreal.DirectionalLight, unreal.DirectionalLightComponent), ("sky_mult", unreal.SkyLight, unreal.SkyLightComponent)):
        if key in v:
            for a in _actors(w, cls):
                c = a.get_component_by_class(ccls)
                k = key + a.get_path_name()
                if k not in o:
                    o[k] = float(c.get_editor_property("intensity"))
                c.set_intensity(o[k] * float(v[key]))
    pp = {k2: v[k1] for k1, k2 in (("exposure_bias", "auto_exposure_bias"), ("le_shadow", "local_exposure_shadow_contrast_scale"),
                                   ("le_highlight", "local_exposure_highlight_contrast_scale")) if k1 in v}
    if pp:
        for a in _actors(w, unreal.PostProcessVolume):
            ps = a.get_editor_property("settings")
            for k, x in pp.items():
                ps.set_editor_property("override_" + k, True)
                ps.set_editor_property(k, float(x))
            a.set_editor_property("settings", ps)
    if any(k in v for _, ks in GD_KEYS for k in ks[1:]):
        try:
            mpc = unreal.load_asset(MPC)
            if mpc is not None:
                d = _gd_defaults()
                d.update({k: float(x) for k, x in v.items() if isinstance(x, (int, float))})
                d["TuneOn"] = 1.0
                for vec, ks in GD_KEYS:
                    unreal.MaterialLibrary.set_vector_parameter_value(w, mpc, vec, unreal.LinearColor(*[float(d.get(k, 0.0)) for k in ks]))
        except Exception as e:
            log("mpc", repr(e))
    ST["applied"] = dict(v)
    return v


def _gd_defaults():
    """material defaults (buildings_material.GD, atmos_look.GD_GROUND) so keys the files leave out keep the built look"""
    d = dict(GdBase=0.5, GdBaseH=8.0, GdGrad=0.6, GdGradH=50.0, GdFloor=0.7, GdAO=1.0, GdTint=1.0, GdSat=1.0)
    try:
        import atmos_look
        g = getattr(atmos_look, "GD_GROUND", {})
        d.update(GdGroundAO=g.get("GdAO", 1.0), GdCanyonAlb=g.get("GdCanyonAlb", 0.0), GdLeanDark=g.get("GdLeanDark", 0.0))
    except Exception:
        pass
    return d


def _mtime():
    try:
        return (os.path.getmtime(PARAMS), os.path.getmtime(DEFAULTS) if os.path.exists(DEFAULTS) else 0.0)
    except OSError:
        return (0.0, os.path.getmtime(DEFAULTS) if os.path.exists(DEFAULTS) else 0.0)


def _tick(dt):
    try:
        now = time.monotonic()
        if now - ST["t"] < 0.5:
            return
        ST["t"] = now
        w = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_game_world()
        if w is None:
            return
        m = _mtime()
        if w != ST["world"] or m != ST["mtime"]:
            ST["world"], ST["mtime"] = w, m
            if w != ST.get("orig_world"):
                ST["orig"].clear(); ST["orig_world"] = w
            v = apply(w)
            log("applied", json.dumps(v)[:300])
    except Exception as e:
        log("tick", repr(e))


def start(world=None):
    """called after the Play look is applied (sim_client.apply_look); idempotent."""
    if not on():
        return
    os.makedirs(os.path.dirname(PARAMS), exist_ok=True)
    ST["mtime"] = None                       # re-apply on the next tick (the look modules just reset light / pp values)
    if ST["h"] is None:
        ST["h"] = unreal.register_slate_post_tick_callback(_tick)
        log("watching", PARAMS)
