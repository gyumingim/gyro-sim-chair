"""Live effect OFF / ON switches (11-13): find by eye which effect gives the cockpit view its overall yellow-brown look.
The slider page's '효과 끄기/켜기' section (sim/tune_server.py, http://127.0.0.1:8768/) writes off_<name>: true into
C:/GyroSimTiles/tune/params.json; tune_look.apply calls apply(world, values) after the sliders, and tune_look._tick calls
refresh(world) every second while something is off (new tiles / a HUD that sim_client shows again).
Nothing is saved: no asset, no map, no tune_defaults.json. Each switch remembers the value it replaced (per world) and puts
it back when it goes ON again; a value another module changed meanwhile becomes the new 'before'. Absent / false = ON
(today's look, untouched).
Kinds:
  pp      PostProcessVolume settings -> engine-neutral values (override on), restored with their override flag
  prop    component properties (fog / sky atmosphere / sun / sky light) -> neutral values
  vis     component visibility (fog, sky atmosphere, clouds, sun, sky light, cockpit fill light)
  prim    primitive components' hidden-in-game flag of tagged actors (canopy, HUD glass, cockpit, HUD, minimap) - a flag
          sim_client / view_fx never touch (they use actor hidden / component visibility), so no fight
  actor   actor hidden-in-game (Cesium tilesets: their tile components come and go)
  cvar    console variables
  mpc     MPC_GyroTune values (ground photo grade, grounded-day darkening): done in tune_look.apply via mpc_override()
  mat     the V-World ground tileset's material -> Cesium default (sea, coast, photo grade all off) - refreshes the tileset (slow)
"""
import unreal

log = lambda *a: unreal.log("[fx] " + " ".join(str(x) for x in a))

ONE4, ZERO4 = (1.0, 1.0, 1.0, 1.0), (0.0, 0.0, 0.0, 0.0)
_GRADE = {}
for _r in ("", "_shadows", "_midtones", "_highlights"):
    for _k in ("saturation", "contrast", "gamma", "gain"):
        _GRADE["color_%s%s" % (_k, _r)] = ONE4
    _GRADE["color_offset" + _r] = ZERO4
_GRADE.update(blue_correction=0.6, expand_gamut=1.0)

PP = {
    "off_wb": dict(white_temp=6500.0, white_tint=0.0, scene_color_tint=(1.0, 1.0, 1.0)),
    "off_grade": _GRADE,
    "off_tone": dict(film_slope=0.88, film_toe=0.55, film_shoulder=0.26, film_black_clip=0.0, film_white_clip=0.04, tone_curve_amount=1.0),
    "off_lut": dict(color_grading_intensity=0.0),
    "off_autoexp": dict(auto_exposure_bias=0.0),
    "off_localexp": dict(local_exposure_shadow_contrast_scale=1.0, local_exposure_highlight_contrast_scale=1.0, local_exposure_detail_strength=1.0),
    "off_bloom": dict(bloom_intensity=0.0, lens_flare_intensity=0.0),
    "off_vignette": dict(vignette_intensity=0.0, film_grain_intensity=0.0, scene_fringe_intensity=0.0),
    "off_ao": dict(ambient_occlusion_intensity=0.0),
    "off_lumen": dict(dynamic_global_illumination_method="NONE"),
}
PROP = {   # key -> [(actor class, component class, {prop: neutral})]
    "off_fogglow": [("ExponentialHeightFog", "ExponentialHeightFogComponent", dict(directional_inscattering_luminance=(0.0, 0.0, 0.0)))],
    "off_aerial": [("SkyAtmosphere", "SkyAtmosphereComponent", dict(aerial_pespective_view_distance_scale=0.0))],
    "off_skytint": [("SkyAtmosphere", "SkyAtmosphereComponent", dict(sky_luminance_factor=(1.0, 1.0, 1.0)))],
    "off_suncolor": [("DirectionalLight", "DirectionalLightComponent", dict(light_color="WHITE", use_temperature=False))],
    "off_skycolor": [("SkyLight", "SkyLightComponent", dict(light_color="WHITE", lower_hemisphere_color=(0.0, 0.0, 0.0)))],
}
VIS = {    # key -> [(actor class or 'tag:<Tag>', component class)]
    "off_fog": [("ExponentialHeightFog", "ExponentialHeightFogComponent")],
    "off_skyatmos": [("SkyAtmosphere", "SkyAtmosphereComponent")],
    "off_clouds": [("VolumetricCloud", "VolumetricCloudComponent")],
    "off_sun": [("DirectionalLight", "DirectionalLightComponent")],
    "off_skylight": [("SkyLight", "SkyLightComponent")],
    "off_cockpitlight": [("tag:CockpitFill", "LightComponent")],
}
PRIM = ("off_canopy", "off_hudglass", "off_cockpit", "off_hud", "off_minimap")
ACTOR = {"off_buildings": ("CesiumBuildings",), "off_landmarks": ("CesiumLandmarks",), "off_trees": ("CesiumTrees", "GyroTreesNear"),
         "off_roads": ("CesiumRoads", "CesiumPiers"), "off_life": ("GyroLife",)}
CVAR = {"off_ao": {"r.Lumen.ScreenProbeGather.ShortRangeAO": 0}, "off_vignette": {"r.Tonemapper.Sharpen": 0}}
MPC_OFF = {"off_photo": dict(PhGain=1.0, PhGamma=1.0, PhSat=1.0, PhKnee=1.0),
           "off_gd": dict(GdBase=0.0, GdGrad=0.0, GdAO=0.0, GdTint=1.0, GdSat=1.0, GdGroundAO=0.0, GdCanyonAlb=0.0, GdLeanDark=0.0)}
MAT = ("off_groundmat",)
NO_COCKPIT = {"Canopy", "HUD", "Minimap", "Overlay", "SimCamera", "SimView", "CrashBack", "CrashPanel", "TutorPanel", "KeyPanel"}
KEYS = tuple(PP) + tuple(k for k in PROP) + tuple(VIS) + PRIM + tuple(ACTOR) + tuple(MPC_OFF) + MAT

ST = dict(world=None, pp={}, prop={}, vis={}, prim={}, actor={}, cvar={}, mat=None, off=set())


def offs(v):
    return {k for k in KEYS if (v or {}).get(k) in (True, 1, 1.0, "1", "true")}


def mpc_override(v, d):
    """tune_look: MPC_GyroTune values with the mpc switches applied (d is changed in place)."""
    for k in offs(v):
        if k in MPC_OFF:
            d.update(MPC_OFF[k])
    return d


# ---- helpers ------------------------------------------------------------------------------------------------------------
def _cls(name):
    return getattr(unreal, name, None)


def _norm(x):
    """comparable plain value"""
    if isinstance(x, unreal.Vector4):
        return tuple(round(float(c), 5) for c in (x.x, x.y, x.z, x.w))
    if isinstance(x, unreal.LinearColor):
        return tuple(round(float(c), 5) for c in (x.r, x.g, x.b, x.a))
    if isinstance(x, unreal.Color):
        return (x.r, x.g, x.b, x.a)
    if isinstance(x, float):
        return round(x, 5)
    if isinstance(x, (tuple, list)):
        return tuple(_norm(c) for c in x)
    return str(x) if isinstance(x, unreal.EnumBase) else x


def _copy(x):
    """own copy of a struct value: get_editor_property on a struct member can return a view into the parent struct,
    which then follows our own later writes (the remembered 'before' became the neutral value)"""
    if isinstance(x, unreal.Vector4):
        return unreal.Vector4(x.x, x.y, x.z, x.w)
    if isinstance(x, unreal.LinearColor):
        return unreal.LinearColor(x.r, x.g, x.b, x.a)
    if isinstance(x, unreal.Color):
        return unreal.Color(r=x.r, g=x.g, b=x.b, a=x.a)
    return x


def _val(obj, k, v):
    """neutral value v as the property's own type"""
    cur = obj.get_editor_property(k)
    if v == "WHITE":
        return unreal.Color(r=255, g=255, b=255, a=255) if isinstance(cur, unreal.Color) else unreal.LinearColor(1.0, 1.0, 1.0, 1.0)
    if v == "NONE":
        return type(cur).NONE
    if isinstance(v, (tuple, list)):
        if isinstance(cur, unreal.Vector4):
            return unreal.Vector4(*v)
        if isinstance(cur, unreal.Color):
            return unreal.Color(r=int(v[0] * 255), g=int(v[1] * 255), b=int(v[2] * 255), a=255)
        return unreal.LinearColor(v[0], v[1], v[2], v[3] if len(v) > 3 else 1.0)
    if isinstance(cur, bool):
        return bool(v)
    return float(v)


def _actors(w, spec):
    if spec.startswith("tag:"):
        return list(unreal.GameplayStatics.get_all_actors_with_tag(w, spec[4:]))
    c = _cls(spec)
    return list(unreal.GameplayStatics.get_all_actors_of_class(w, c)) if c else []


def _comps(w, aspec, cspec):
    cc = _cls(cspec)
    out = []
    for a in _actors(w, aspec):
        out += [c for c in a.get_components_by_class(cc)] if cc else []
    return out


def _tags(a):
    return {str(t) for t in a.get_editor_property("tags")}


def _attached(a):
    try:
        return list(a.get_attached_actors(True, True))
    except Exception:
        return []


def _mesh_name(a):
    try:
        c = a.get_component_by_class(unreal.StaticMeshComponent)
        return c.static_mesh.get_name() if c and c.static_mesh else ""
    except Exception:
        return ""


def _prim_actors(w, key):
    tag = lambda t: list(unreal.GameplayStatics.get_all_actors_with_tag(w, t))
    if key == "off_canopy":
        return tag("Canopy")
    if key == "off_hudglass":
        return [a for a in tag("Cockpit") if "glass" in _mesh_name(a).lower()]
    if key == "off_hud":
        return tag("HUD")
    if key == "off_minimap":
        return tag("Minimap")
    if key == "off_cockpit":
        glass = set(_prim_actors(w, "off_hudglass"))
        out = []
        for root in tag("Aircraft"):
            for a in [root] + _attached(root):
                if a not in glass and not (_tags(a) & NO_COCKPIT) and a not in out:
                    out.append(a)
        return out
    return []


# ---- the switches -------------------------------------------------------------------------------------------------------
def _same(a, b):
    return _norm(a) == _norm(b)


def _do_pp(w, off):
    S = ST["pp"]                                # (volume path, prop) -> [override, value, value we set]
    if not (off & set(PP)) and not S:
        return
    for vol in unreal.GameplayStatics.get_all_actors_of_class(w, unreal.PostProcessVolume):
        ps = vol.get_editor_property("settings")
        path, dirty = vol.get_path_name(), False
        for key, props in PP.items():
            for k, v in props.items():
                sk = (path, k)
                try:
                    if key in off:
                        cur = ps.get_editor_property(k)
                        if sk not in S or not _same(cur, S[sk][2]):
                            S[sk] = [bool(ps.get_editor_property("override_" + k)), _copy(cur), None]
                        nv = _val(ps, k, v)
                        if S[sk][2] is None or not _same(cur, nv) or not ps.get_editor_property("override_" + k):
                            ps.set_editor_property("override_" + k, True)
                            ps.set_editor_property(k, nv)
                            dirty = True
                        S[sk][2] = _copy(ps.get_editor_property(k))
                    elif sk in S:
                        ov, v0, mine = S.pop(sk)
                        if mine is None or _same(ps.get_editor_property(k), mine):   # nobody changed it since: put it back
                            ps.set_editor_property("override_" + k, ov)
                            ps.set_editor_property(k, v0)
                            dirty = True
                except Exception as e:
                    log("pp", k, repr(e)[:120])
        if dirty:
            vol.set_editor_property("settings", ps)


def _do_prop(w, off):
    S = ST["prop"]
    for key, specs in PROP.items():
        for aspec, cspec, props in specs:
            if key not in off and not any(sk[0] == key for sk in S):
                continue
            for c in _comps(w, aspec, cspec):
                for k, v in props.items():
                    sk = (key, c.get_path_name(), k)
                    try:
                        cur = c.get_editor_property(k)
                        if key in off:
                            nv = _val(c, k, v)
                            if sk not in S or not _same(cur, S[sk][1]):
                                S[sk] = [_copy(cur), None]
                            if not _same(cur, nv):
                                c.set_editor_property(k, nv)
                            S[sk][1] = _copy(c.get_editor_property(k))
                        elif sk in S:
                            v0, mine = S.pop(sk)
                            if mine is None or _same(cur, mine):
                                c.set_editor_property(k, v0)
                    except Exception as e:
                        log("prop", k, repr(e)[:120])
    for sk in [sk for sk in S if sk[0] not in off]:          # components that are gone
        S.pop(sk, None)


def _do_vis(w, off):
    S = ST["vis"]                               # component path -> (component, was visible)
    for key, specs in VIS.items():
        for aspec, cspec in specs:
            if key in off:
                for c in _comps(w, aspec, cspec):
                    p = c.get_path_name()
                    if c.is_visible():
                        S[(key, p)] = (c, True)
                        c.set_visibility(False, False)
                    elif (key, p) not in S:
                        S[(key, p)] = (c, False)
    for sk in [sk for sk in S if sk[0] not in off]:
        c, was = S.pop(sk)
        try:
            if was:
                c.set_visibility(True, False)
        except Exception:
            pass


def _do_prim(w, off):
    S = ST["prim"]                              # (key, component path) -> (component, hidden_in_game before)
    for key in PRIM:
        if key not in off:
            continue
        for a in _prim_actors(w, key):
            for c in a.get_components_by_class(unreal.PrimitiveComponent):
                sk = (key, c.get_path_name())
                try:
                    h = bool(c.get_editor_property("hidden_in_game"))
                    if sk not in S:
                        S[sk] = (c, h)
                    if not h:
                        c.set_hidden_in_game(True, False)
                except Exception as e:
                    log("prim", repr(e)[:120])
    for sk in [sk for sk in S if sk[0] not in off]:
        c, h = S.pop(sk)
        try:
            if any(s[1] == sk[1] for s in S):    # still hidden by another switch (cockpit vs glass never overlap)
                continue
            c.set_hidden_in_game(h, False)
        except Exception:
            pass


def _hidden(a):
    try:
        return bool(a.get_editor_property("hidden"))
    except Exception:
        return False


def _do_actor(w, off):
    S = ST["actor"]                             # (key, actor path) -> (actor, hidden before)
    for key, tags in ACTOR.items():
        if key not in off:
            continue
        for t in tags:
            for a in unreal.GameplayStatics.get_all_actors_with_tag(w, t):
                sk = (key, a.get_path_name())
                h = _hidden(a)
                if sk not in S:
                    S[sk] = (a, h)
                if not h:
                    a.set_actor_hidden_in_game(True)
    for sk in [sk for sk in S if sk[0] not in off]:
        a, h = S.pop(sk)
        try:
            a.set_actor_hidden_in_game(h)
        except Exception:
            pass


def _do_cvar(w, off):
    S = ST["cvar"]
    for key, cv in CVAR.items():
        for k, v in cv.items():
            if key in off and k not in S:
                S[k] = unreal.SystemLibrary.get_console_variable_float_value(k)
                unreal.SystemLibrary.execute_console_command(w, "%s %s" % (k, v))
            elif key not in off and k in S and not any(k in CVAR[o] for o in off if o in CVAR):
                unreal.SystemLibrary.execute_console_command(w, "%s %g" % (k, S.pop(k)))


def _do_mat(w, off):
    """ground tileset material: off_groundmat = Cesium's stock material (no sea / coast / photo grade / grounded).
    (A coast-only switch, CoastOn / CoastFaceOn / SeaArt 0, was tried 11-13: it turned the whole sea and city ground brown = misleading, dropped.)"""
    want = "stock" if "off_groundmat" in off else None
    m = ST["mat"]                               # None or dict(ts, orig, mode, mine)
    if want is None and m is None:
        return
    for ts in unreal.GameplayStatics.get_all_actors_with_tag(w, "CesiumGround")[:1]:
        cur = ts.get_editor_property("material")
        if m is not None and m["mine"] != cur:     # someone (sim_client._vworld_ground) set a new material: new 'before'
            m = ST["mat"] = dict(orig=cur, mode=None, mine=cur)
        if m is None:
            m = ST["mat"] = dict(orig=cur, mode=None, mine=cur)
        if want == m["mode"]:
            return
        new = m["orig"] if want is None else None
        ts.set_editor_property("material", new)
        ts.refresh_tileset()
        log("ground material", want or "back", "->", new.get_name() if new else "Cesium default")
        if want is None:
            ST["mat"] = None
        else:
            m.update(mode=want, mine=new)


def apply(world, v, full=True):
    """switches from the tune values v (off_*: true). full=False (the 1 s refresh): only the visibility kinds."""
    if world is None:
        return set()
    if ST["world"] != world:                # new Play world: nothing of ours is set there
        ST.update(world=world, pp={}, prop={}, vis={}, prim={}, actor={}, cvar={}, mat=None)
    off = offs(v)
    steps = (_do_vis, _do_prim, _do_actor) + ((_do_pp, _do_prop, _do_cvar, _do_mat) if full else ())
    for f in steps:
        try:
            f(world, off)
        except Exception as e:
            log(f.__name__, repr(e)[:160])
    if full and off != ST["off"]:
        log("off:", ",".join(sorted(off)) or "(none)")
    ST["off"] = off
    return off


def active():
    return bool(ST["off"])
