"""Moving cars and ships over Busan (the 'life' layer) for the vworld mode on the local terrain.

The map's 'GyroLife' actor (Scripts/add_life_actor.py, run once with the editor closed; hidden until here) holds one
InstancedStaticMeshComponent per mesh (component tags LifeVehicle, LifeContainer, ... LifeWake). At Play, apply() fills
them once from C:/GyroSimTiles/life/traffic.bin + ships.bin (sim/traffic_build.py, sim/ships_build.py) and from then on
the GPU moves everything: the materials (/Game/Life/M_GyroLife*, Scripts/life_assets.py) slide each instance along its
road / sea-lane piece with World Position Offset from the per-instance custom data - no per-frame Python, no shadows,
no collision. The only Python after the fill is a 1 s check that moves the whole actor when the Cesium origin moves.

Toggles: GYROSIM_TRAFFIC=0 (no cars), GYROSIM_SHIPS=0 (no ships / wakes), GYROSIM_LIFE=0 (both).
GYROSIM_LIFE_DIR = data folder. set_time(world, t) freezes the motion at t seconds (repeatable shots), None = live.
Called by sim_client._vworld_ground after the trees.
"""
import array, json, os, time
import unreal
import geo

TAG = "GyroLife"
DIR = os.environ.get("GYROSIM_LIFE_DIR", r"C:/GyroSimTiles/life").replace("\\", "/")
ANCHOR = (35.12, 129.07)                                   # = sim/life_common.ANCHOR
# group (file) -> (component tag, material, Kind, cull / far distance cm)
GROUPS = dict(vehicle=("LifeVehicle", "/Game/Life/M_GyroLifeVehicle", 0, 150000.0),
              container=("LifeContainer", "/Game/Life/M_GyroLifeShip", 0, 2500000.0),
              feeder=("LifeFeeder", "/Game/Life/M_GyroLifeShip", 1, 2500000.0),
              ferry=("LifeFerry", "/Game/Life/M_GyroLifeShip", 2, 2500000.0),
              bulk=("LifeBulk", "/Game/Life/M_GyroLifeShip", 3, 2500000.0),
              tug=("LifeTug", "/Game/Life/M_GyroLifeShip", 4, 800000.0),
              fishing=("LifeFishing", "/Game/Life/M_GyroLifeShip", 5, 800000.0),
              boat=("LifeBoat", "/Game/Life/M_GyroLifeShip", 6, 600000.0),
              wake=("LifeWake", "/Game/Life/M_GyroLifeWake", 0, 800000.0))
COMPONENTS = [v[0] for v in GROUPS.values()]
MESH = "/Game/Life/Meshes/"
ST = dict(actor=None, georef=None, origin=None, h=None, t=0.0, mids=[], counts={}, log=unreal.log)


def find(world):
    a = unreal.GameplayStatics.get_all_actors_with_tag(world, TAG)
    return a[0] if a else None


def comps(actor):
    out = {}
    for c in actor.get_components_by_class(unreal.InstancedStaticMeshComponent):
        for t in c.get_editor_property("component_tags"):
            out[str(t)] = c
    return out


def place(actor, georef):
    """the actor transform for the georeference's current origin: local frame (X north, Y east, Z up at ANCHOR, h 0)
    -> this project's Unreal world frame (geo.Frame at the origin). -> origin key."""
    o = georef.get_origin_longitude_latitude_height()
    key = (round(o.x, 9), round(o.y, 9), round(o.z, 3))
    f = geo.Frame(o.y, o.x, o.z)
    p = f.world(ANCHOR[0], ANCHOR[1], 0.0)
    e, n, u = geo.enu_axes(*ANCHOR)
    roll, pitch, yaw = geo.euler_from_axes(f.vec(n), f.vec(u))
    actor.set_actor_location_and_rotation(unreal.Vector(*p), unreal.Rotator(roll=roll, pitch=pitch, yaw=yaw), False, True)
    return key


def _read(name):
    js = DIR + "/" + name + ".json"
    if not os.path.isfile(js):
        return None, None
    meta = json.load(open(js, encoding="utf-8"))
    with open(DIR + "/" + name + ".bin", "rb") as f:
        raw = f.read()
    return meta, raw


def _fill(c, group, recs, n, rec, scales, log):
    tag, mat, kind, far = GROUPS[group]
    nm = "SM_Life" + group.capitalize()
    sm = None
    for p in (MESH + nm + "/StaticMeshes/" + nm, MESH + nm):       # Interchange puts each glb in its own folder
        try:                                                     # load_asset: the registry may still be scanning at Play
            sm = unreal.load_asset(p)
        except Exception:
            sm = None
        if sm is not None:
            break
    try:
        m = unreal.load_asset(mat)
    except Exception:
        m = None
    if sm is None or m is None:
        log("[life] %s: mesh %s / material %s missing (Scripts/life_assets.py)" % (group, sm is not None, m is not None))
        return 0
    c.clear_instances()
    c.set_static_mesh(sm)
    mid = c.create_dynamic_material_instance(0, m)
    mid.set_scalar_parameter_value("Kind", float(kind))
    mid.set_scalar_parameter_value("Far", far)
    ST["mids"].append(mid)
    try:
        c.set_num_custom_data_floats(8)
    except Exception:
        c.set_editor_property("num_custom_data_floats", 8)
    c.set_cull_distances(0, int(far))
    c.set_cast_shadow(False)
    c.set_collision_enabled(unreal.CollisionEnabled.NO_COLLISION)
    T = []
    for i in range(n):
        b = i * rec
        s = scales[i] if scales else 1.0
        T.append(unreal.Transform(unreal.Vector(recs[b], recs[b + 1], recs[b + 2]),
                                  unreal.Rotator(roll=0.0, pitch=recs[b + 4], yaw=recs[b + 3]), unreal.Vector(s, s, s)))
    c.add_instances(T, False, False)
    for i in range(n):
        b = i * rec + 5
        c.set_custom_data(i, list(recs[b:b + 8]), i == n - 1)
    return n


def apply(world, log=unreal.log, georef=None):
    """fill and show the GyroLife actor in `world`. -> the actor, or None (off / no data / no actor)."""
    ST["log"] = log
    if os.environ.get("GYROSIM_LIFE", "1") == "0":
        log("[life] off (GYROSIM_LIFE=0)")
        return None
    cars, ships = os.environ.get("GYROSIM_TRAFFIC", "1") != "0", os.environ.get("GYROSIM_SHIPS", "1") != "0"
    a = find(world)
    if a is None:
        log("[life] no GyroLife actor in the map: run Scripts/add_life_actor.py once with the editor closed")
        return None
    if georef is None:
        g = unreal.GameplayStatics.get_all_actors_with_tag(world, "CesiumGeoreference")
        georef = g[0] if g else None
    if georef is None:
        log("[life] no CesiumGeoreference")
        return None
    t0 = time.monotonic()
    cs = comps(a)
    ST["mids"], ST["counts"] = [], {}
    for name, on in (("traffic", cars), ("ships", ships)):
        meta, raw = _read(name) if on else (None, None)
        if on and meta is None:
            log("[life] no %s data in %s (python -I sim/%s_build.py --build)" % (name, DIR, "traffic" if name == "traffic" else "ships"))
        groups = meta["groups"] if meta else []
        for gname in [g for g, v in GROUPS.items() if (g == "vehicle") == (name == "traffic")]:
            c = cs.get(GROUPS[gname][0])
            if c is None:
                continue
            gi = next((g for g in groups if g["name"] == gname), None)
            if gi is None or not gi["count"]:
                c.clear_instances()
                c.set_visibility(False, False)
                continue
            rec = int(meta["rec"])
            recs = array.array("f")
            recs.frombytes(raw[gi["offset"]:gi["offset"] + gi["count"] * rec * 4])
            scales = meta.get("wake_scale") if gname == "wake" else None
            ST["counts"][gname] = _fill(c, gname, recs, gi["count"], rec, scales, log)
            c.set_visibility(True, False)
    if not ST["counts"]:
        a.set_actor_hidden_in_game(True)
        return None
    try:
        a.root_component.set_mobility(unreal.ComponentMobility.MOVABLE)
    except Exception:
        pass
    ST.update(actor=a, georef=georef, origin=place(a, georef))
    a.set_actor_hidden_in_game(False)
    if ST["h"] is None:
        ST["h"] = unreal.register_slate_post_tick_callback(_tick)
    log("[life] on: %s in %.1f s (cars %s, ships %s)" % (", ".join("%s %d" % kv for kv in ST["counts"].items()), time.monotonic() - t0, cars, ships))
    return a


def _tick(dt):
    """follow the Cesium origin (start spot changes / shot scripts move it); stops when the Play world is gone."""
    ST["t"] += dt
    if ST["t"] < 1.0:
        return
    ST["t"] = 0.0
    a, g = ST["actor"], ST["georef"]
    try:
        if a is None or g is None or not unreal.SystemLibrary.is_valid(a) or not unreal.SystemLibrary.is_valid(g):
            raise RuntimeError("gone")
        o = g.get_origin_longitude_latitude_height()
        if (round(o.x, 9), round(o.y, 9), round(o.z, 3)) != ST["origin"]:
            ST["origin"] = place(a, g)
    except Exception:
        unreal.unregister_slate_post_tick_callback(ST["h"])
        ST.update(h=None, actor=None, georef=None, mids=[])


def follow_now():
    """re-place at once (after a script moved the origin)."""
    if ST["actor"] is not None and ST["georef"] is not None:
        ST["origin"] = place(ST["actor"], ST["georef"])


def set_time(world, t=None):
    """freeze the motion at t seconds (all GyroLife materials), None = live game time."""
    for m in ST["mids"]:
        try:
            m.set_scalar_parameter_value("TFix", -1.0 if t is None else float(t))
        except Exception:
            pass


def hide(world):
    a = find(world)
    if a is not None:
        a.set_actor_hidden_in_game(True)


def spawn_editor(log=unreal.log):
    """the GyroLife actor in the EDITOR world before Play (offscreen check editors only, never saved)."""
    w = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_editor_world()
    a = find(w)
    if a is None:
        a = make_actor(log)
        log("[life] editor-world actor spawned")
    return a


def make_actor(log=unreal.log):
    """spawn the GyroLife actor with its ISM components into the editor world (add_life_actor.py saves it)."""
    eas = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
    a = eas.spawn_actor_from_class(unreal.StaticMeshActor, unreal.Vector(0, 0, 0))
    a.set_actor_label(TAG)
    a.tags = [unreal.Name(TAG)]
    a.root_component.set_mobility(unreal.ComponentMobility.MOVABLE)
    sds = unreal.get_engine_subsystem(unreal.SubobjectDataSubsystem)
    SDL = unreal.SubobjectDataBlueprintFunctionLibrary
    root_h = sds.k2_gather_subobject_data_for_instance(a)[0]
    for tag in COMPONENTS:
        h, fail = sds.add_new_subobject(unreal.AddNewSubobjectParams(parent_handle=root_h, new_class=unreal.InstancedStaticMeshComponent))
        try:
            sds.rename_subobject(h, unreal.Text(tag))
        except Exception:
            pass
        c = SDL.get_object(SDL.get_data(h))
        c.set_editor_property("component_tags", [unreal.Name(tag)])
        c.set_editor_property("mobility", unreal.ComponentMobility.MOVABLE)
        c.set_editor_property("cast_shadow", False)
        c.set_editor_property("num_custom_data_floats", 8)
        c.set_collision_enabled(unreal.CollisionEnabled.NO_COLLISION)
    a.set_actor_hidden_in_game(True)
    return a
