"""Real-leaf trees near the aircraft (11-11, docs/trees-near-busan.md) - OPT-IN (GYROSIM_TREES_NEAR=1); default off since 11-11
(decimation stripped the leaves -> grey sticks; the blob proxy tiles stay the default).

The trees are the same ~19.9 M Busan trees as the v2 tiles (sim/veg_v2.py: position, height, crown width, species),
stored by sim/trees_near_build.py --db in C:/GyroSimTiles/veg/near/trees_near.bin (250 m cells of the life layer's local
frame). Around the camera, cells within RADIUS are streamed into the map's 'GyroTreesNear' actor (Scripts/
add_trees_near_actor.py; offscreen shots add it to the editor world with spawn_editor()) - a pool of cell slots, each with
KINDS InstancedStaticMeshComponents - carrying the reduced real tree models (Nanite, /Game/ThirdParty/Trees/Near/
SM_TreeNear_*, Scripts/trees_near_assets.py; git-ignored) and the own material /Game/Trees/M_GyroTreeNear (one dynamic
instance per kind = the species tint; per-tree / per-leaf variation in the material). Filling is spread over frames
(BUDGET_MS of Python per frame). Trees beyond RADIUS are culled per instance (round edge). No collision.

Toggles (env):
  GYROSIM_TREES_NEAR=1        on (default 0 = off -> the blob proxy tiles, trees_look)
  GYROSIM_TREES_PROXY=0       with NEAR=1: no blob tiles (default 1 = blob tiles as well)
  GYROSIM_TREES_NEAR_R        radius m (default 900 monitor; 450 when a headset is on or GYROSIM_TREES_NEAR_VR=1)
  GYROSIM_TREES_NEAR_LITE     1 (default 11-11) = one light model (oak D, 350 k tri) for every tree, recoloured / reshaped
                              per species; 0 = the 8-model set (Poly Haven pine x3, oak x4, alder) - imported later
  GYROSIM_TREES_NEAR_SHADOW=0 no shadows from the near trees
Called from trees_look.apply (sim_client._vworld_ground) - no other hook.
"""
import array, json, math, os, time
import unreal
import geo

TAG = "GyroTreesNear"
DIR = os.environ.get("GYROSIM_TREES_NEAR_DIR", r"C:/GyroSimTiles/veg/near").replace("\\", "/")
MESH = "/Game/ThirdParty/Trees/Near/"
MAT = "/Game/Trees/M_GyroTreeNear"
MESH_INFO = r"C:/GyroSimTiles/assets/trees_near/meshes.json"
ANCHOR = (35.12, 129.07)                                     # = sim/life_common.ANCHOR (the data frame)
SLOTS = 64                                                   # cell slots in the map actor
KINDS = 8                                                    # components per slot
BUDGET_MS = float(os.environ.get("GYROSIM_TREES_NEAR_BUDGET_MS", "4"))
# species (sim/trees_near_build.SPECIES): 0 소나무 pine, 1 곰솔 bpine, 2 broadleaf, 3 shrub
# linear canopy tints (from sim/veg_v2.TINT; the material scales them to leaf albedo with Gain)
# 11-11 shot 1: the veg_v2 blues read grey-black on real leaves next to the photo ground -> less blue (pine still bluer / darker)
TINT = {0: (0.036, 0.062, 0.030), 1: (0.030, 0.054, 0.031), 2: (0.066, 0.105, 0.030), 3: (0.058, 0.094, 0.034)}
# kind -> (mesh, species of its tint); species -> kinds it draws from
FULL = [("pine_a", 0), ("pine_b", 0), ("pine_c", 1), ("oak_a", 2), ("oak_b", 2), ("oak_c", 2), ("alder_c", 2), ("oak_d", 3)]
FULL_PICK = {0: (0, 1), 1: (2,), 2: (3, 4, 5, 6), 3: (7,)}
LITE_MESH = "oak_d"                                          # the lightest downloaded model (3.7 M source triangles)
LITE = [(LITE_MESH, 0), (LITE_MESH, 1), (LITE_MESH, 2), (LITE_MESH, 3)]
LITE_PICK = {0: (0,), 1: (1,), 2: (2,), 3: (3,)}
LITE_SHAPE = {0: (0.75, 1.15), 1: (0.8, 1.05), 2: (1.0, 1.0), 3: (1.0, 1.0)}   # xy / z on the one model: narrower pines
ST = dict(actor=None, georef=None, origin=None, h=None, t=0.0, loaded={}, free=[], queue=[], work=[], meta=None, f=None,
          meshes={}, info={}, mids=[], log=unreal.log, radius=900.0, lite=False, layout=FULL, pick=FULL_PICK, stats={},
          slot_comps={}, world=None)


def enabled():
    return os.environ.get("GYROSIM_TREES", "1") != "0" and os.environ.get("GYROSIM_TREES_NEAR", "0") == "1"


def proxy_on():
    return os.environ.get("GYROSIM_TREES_PROXY", "1") != "0"


def find(world):
    a = unreal.GameplayStatics.get_all_actors_with_tag(world, TAG)
    return a[0] if a else None


def comp_tag(slot, k):
    return "TN_%02d_%d" % (slot, k)


def comps(actor):
    out = {}
    for c in actor.get_components_by_class(unreal.InstancedStaticMeshComponent):
        for t in c.get_editor_property("component_tags"):
            out[str(t)] = c
    return out


def place(actor, georef):
    """the actor transform for the georeference origin (same as life_look.place). -> origin key."""
    o = georef.get_origin_longitude_latitude_height()
    key = (round(o.x, 9), round(o.y, 9), round(o.z, 3))
    f = geo.Frame(o.y, o.x, o.z)
    p = f.world(ANCHOR[0], ANCHOR[1], 0.0)
    e, n, u = geo.enu_axes(*ANCHOR)
    roll, pitch, yaw = geo.euler_from_axes(f.vec(n), f.vec(u))
    actor.set_actor_location_and_rotation(unreal.Vector(*p), unreal.Rotator(roll=roll, pitch=pitch, yaw=yaw), False, True)
    return key


def _vr():
    if os.environ.get("GYROSIM_TREES_NEAR_VR", "0") == "1":
        return True
    try:
        return bool(unreal.HeadMountedDisplayFunctionLibrary.is_head_mounted_display_enabled())
    except Exception:
        return False


def radius():
    r = os.environ.get("GYROSIM_TREES_NEAR_R")
    if r:
        return float(r)
    return 450.0 if _vr() else 900.0


def _load_mesh(name):
    for p in (MESH + "SM_TreeNear_" + name, MESH + "SM_TreeNear_" + name + "/StaticMeshes/SM_TreeNear_" + name):
        try:                                               # load_asset directly (does_asset_exist missed them at Play)
            sm = unreal.load_asset(p)
            if isinstance(sm, unreal.StaticMesh):
                return sm
        except Exception:
            pass
    return None


def _setup(actor, world, log):
    cs = comps(actor)
    ST["slot_comps"] = {s: [cs.get(comp_tag(s, k)) for k in range(KINDS)] for s in range(SLOTS)}
    shadow = os.environ.get("GYROSIM_TREES_NEAR_SHADOW", "1") != "0"
    try:
        mat = unreal.load_asset(MAT)
    except Exception:
        mat = None
    mids = []
    for k in range(KINDS):
        mid = None
        if k < len(ST["layout"]) and mat is not None:
            mid = unreal.MaterialLibrary.create_dynamic_material_instance(world, mat)
            t = TINT[ST["layout"][k][1]]
            mid.set_vector_parameter_value("Tint", unreal.LinearColor(t[0], t[1], t[2], 1.0))
        mids.append(mid)
    ST["mids"] = mids
    ok = 0
    for s in range(SLOTS):
        for k, c in enumerate(ST["slot_comps"][s]):
            if c is None:
                continue
            c.clear_instances()
            sm = ST["meshes"].get(ST["layout"][k][0]) if k < len(ST["layout"]) else None
            if sm is None:
                c.set_visibility(False, False)
                continue
            c.set_static_mesh(sm)
            if mids[k] is not None:
                c.set_material(0, mids[k])
            c.set_cull_distances(0, int(ST["radius"] * 100.0))
            c.set_cast_shadow(shadow)
            c.set_collision_enabled(unreal.CollisionEnabled.NO_COLLISION)
            c.set_visibility(True, False)
            ok += 1
    return ok


def apply(world, log=unreal.log, georef=None):
    """start the near trees in `world`. -> the actor, or None (off / no data / no actor / no meshes)."""
    ST["log"] = log
    if not enabled():
        log("[trees_near] off (GYROSIM_TREES_NEAR=0)")
        return None
    a = find(world)
    if a is None:
        log("[trees_near] no GyroTreesNear actor in the map: run Scripts/add_trees_near_actor.py once with the editor closed")
        return None
    js = DIR + "/trees_near.json"
    if not os.path.isfile(js):
        log("[trees_near] no data at %s (python -I sim/trees_near_build.py --db)" % DIR)
        return None
    if georef is None:
        g = unreal.GameplayStatics.get_all_actors_with_tag(world, "CesiumGeoreference")
        georef = g[0] if g else None
    if georef is None:
        log("[trees_near] no CesiumGeoreference")
        return None
    t0 = time.monotonic()
    if ST["meta"] is None or ST.get("meta_src") != js:
        ST["meta"] = json.load(open(js, encoding="utf-8"))
        ST["meta_src"] = js
    if ST["f"] is None:
        ST["f"] = open(DIR + "/trees_near.bin", "rb")
    ST["lite"] = os.environ.get("GYROSIM_TREES_NEAR_LITE", "1") != "0"         # 11-11 default: lite (pine / 8-model set pending)
    ST["layout"], ST["pick"] = (LITE, LITE_PICK) if ST["lite"] else (FULL, FULL_PICK)
    ST["radius"] = radius()
    try:
        ST["info"] = json.load(open(MESH_INFO, encoding="utf-8"))["meshes"]
    except Exception:
        ST["info"] = {}
    names = sorted(set(m for m, _ in ST["layout"]))
    ST["meshes"] = {m: _load_mesh(m) for m in names}
    missing = [m for m, v in ST["meshes"].items() if v is None]
    if len(missing) == len(names):
        log("[trees_near] no meshes under %s (Scripts/trees_near_assets.py)" % MESH)
        return None
    ST.update(world=world, work=[], queue=[], loaded={}, free=list(range(SLOTS)), stats=dict(cells=0, trees=0, fill_ms=0.0, max_tick_ms=0.0))
    n = _setup(a, world, log)
    try:
        a.root_component.set_mobility(unreal.ComponentMobility.MOVABLE)
    except Exception:
        pass
    ST.update(actor=a, georef=georef, origin=place(a, georef), t=1.0)
    a.set_actor_hidden_in_game(False)
    if ST["h"] is None:
        ST["h"] = unreal.register_slate_post_tick_callback(_tick)
    log("[trees_near] on: radius %.0f m, %s, %d components, meshes missing %s, shadows %s (%.1f s)" % (
        ST["radius"], "lite (%s)" % LITE_MESH if ST["lite"] else "%d models" % len(names), n, missing,
        os.environ.get("GYROSIM_TREES_NEAR_SHADOW", "1") != "0", time.monotonic() - t0))
    return a


def _cam_local():
    try:
        p = unreal.GameplayStatics.get_player_camera_manager(ST["world"], 0).get_camera_location()
    except Exception:
        return None
    return ST["actor"].get_actor_transform().inverse_transform_location(p)


def _wanted(c):
    cell = ST["meta"]["cell_m"] * 100.0
    R = ST["radius"] * 100.0
    i0, j0 = int(math.floor(c.x / cell)), int(math.floor(c.y / cell))
    k = int(math.ceil(R / cell)) + 1
    out = []
    for i in range(i0 - k, i0 + k + 1):
        for j in range(j0 - k, j0 + k + 1):
            dx = max(i * cell - c.x, 0.0, c.x - (i + 1) * cell)
            dy = max(j * cell - c.y, 0.0, c.y - (j + 1) * cell)
            d2 = dx * dx + dy * dy
            if d2 < R * R:
                out.append((d2, "%d_%d" % (i, j)))
    out.sort()
    return [k_ for _, k_ in out]


def _hash(i):
    return ((i * 2654435761) & 0xFFFFFFFF) / 4294967296.0


def _plan(key, slot):
    """read one cell -> work items (slot, kind, transforms list) for the fill queue. -> number of trees."""
    meta = ST["meta"]
    ent = meta["cells"].get(key)
    if ent is None:
        return 0
    first, n = ent
    rec = meta["rec"]
    ST["f"].seek(first * rec * 4)
    R = array.array("f")
    R.frombytes(ST["f"].read(n * rec * 4))
    info, layout, pick, lite = ST["info"], ST["layout"], ST["pick"], ST["lite"]
    dims = {}
    for k, (m, _s) in enumerate(layout):
        mi = info.get(m, {})
        dims[k] = (float(mi.get("height_m", 12.0)) or 12.0, float(mi.get("crown_r_m", 3.0)) or 3.0)
    groups = {}
    for i in range(n):
        b = i * rec
        sp = int(R[b + 6])
        ch = pick.get(sp, pick[2])
        k = ch[int(_hash(first + i) * len(ch)) % len(ch)]
        if ST["meshes"].get(layout[k][0]) is None:
            continue
        H, Rc = dims[k]
        h, r = max(R[b + 4], 1.5), max(R[b + 5], 0.8)
        s = h / H
        sxy = s * min(2.0 if lite else 1.45, max(0.7, r / (Rc * s)))      # lite: the slim oak D widened to the crown
        if lite:
            fx, fz = LITE_SHAPE.get(sp, (1.0, 1.0))
            sxy *= fx
            s *= fz
        groups.setdefault(k, []).append(unreal.Transform(unreal.Vector(R[b], R[b + 1], R[b + 2]),
                                                         unreal.Rotator(roll=0.0, pitch=0.0, yaw=R[b + 3]), unreal.Vector(sxy, sxy, s)))
    for k, T in groups.items():
        for a in range(0, len(T), 600):
            ST["work"].append((key, slot, k, T[a:a + 600]))
    return n


def _clear_slot(slot):
    for c in ST["slot_comps"].get(slot, []):
        if c is not None and c.get_instance_count():
            c.clear_instances()


def _tick(dt):
    ST["t"] += dt
    a, g = ST["actor"], ST["georef"]
    try:
        if a is None or g is None or not unreal.SystemLibrary.is_valid(a) or not unreal.SystemLibrary.is_valid(g):
            raise RuntimeError("gone")
        t0 = time.perf_counter()
        if ST["t"] >= 1.0:
            ST["t"] = 0.0
            o = g.get_origin_longitude_latitude_height()
            if (round(o.x, 9), round(o.y, 9), round(o.z, 3)) != ST["origin"]:
                ST["origin"] = place(a, g)
            c = _cam_local()
            if c is not None:
                want = _wanted(c)
                ws = set(want)
                for key in [k for k in ST["loaded"] if k not in ws]:          # cells left behind -> slot free
                    slot = ST["loaded"].pop(key)
                    ST["work"] = [w for w in ST["work"] if w[1] != slot]
                    _clear_slot(slot)
                    ST["free"].append(slot)
                ST["queue"] = [k for k in want if k not in ST["loaded"]]
        while (time.perf_counter() - t0) * 1000.0 < BUDGET_MS:
            if ST["work"]:
                key, slot, k, T = ST["work"].pop(0)
                c = ST["slot_comps"][slot][k]
                if c is not None:
                    c.add_instances(T, False, False)
                ST["stats"]["trees"] += len(T)
            elif ST["queue"] and ST["free"]:
                key = ST["queue"].pop(0)
                slot = ST["free"].pop(0)
                _clear_slot(slot)
                ST["loaded"][key] = slot
                _plan(key, slot)
                ST["stats"]["cells"] += 1
            else:
                break
        ms = (time.perf_counter() - t0) * 1000.0
        ST["stats"]["fill_ms"] = round(ms, 2)
        ST["stats"]["max_tick_ms"] = round(max(ST["stats"]["max_tick_ms"], ms), 2)
    except Exception as e:
        if str(e) != "gone":
            ST["log"]("[trees_near] tick %r" % (e,))
        unreal.unregister_slate_post_tick_callback(ST["h"])
        ST.update(h=None, actor=None, georef=None)


def pending():
    """cells / chunks still to fill (shot scripts wait for 0)."""
    return (len(ST["queue"]) + len(ST["work"])) if ST["h"] is not None else 0


def loaded_trees():
    tot = 0
    for slot in ST["loaded"].values():
        for c in ST["slot_comps"].get(slot, []):
            if c is not None:
                tot += c.get_instance_count()
    return tot


def follow_now():
    """re-place and recompute the wanted cells on the next tick (after a script moved the origin / camera)."""
    if ST["actor"] is not None and ST["georef"] is not None:
        ST["origin"] = place(ST["actor"], ST["georef"])
        ST["t"] = 1.0


def hide(world):
    a = find(world)
    if a is not None:
        a.set_actor_hidden_in_game(True)


def make_actor(log=unreal.log):
    """spawn the GyroTreesNear actor with SLOTS x KINDS empty ISM components into the editor world."""
    eas = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
    a = eas.spawn_actor_from_class(unreal.StaticMeshActor, unreal.Vector(0, 0, 0))
    a.set_actor_label(TAG)
    a.tags = [unreal.Name(TAG)]
    a.root_component.set_mobility(unreal.ComponentMobility.MOVABLE)
    sds = unreal.get_engine_subsystem(unreal.SubobjectDataSubsystem)
    SDL = unreal.SubobjectDataBlueprintFunctionLibrary
    root_h = sds.k2_gather_subobject_data_for_instance(a)[0]
    for s in range(SLOTS):
        for k in range(KINDS):
            tag = comp_tag(s, k)
            h, fail = sds.add_new_subobject(unreal.AddNewSubobjectParams(parent_handle=root_h, new_class=unreal.InstancedStaticMeshComponent))
            try:
                sds.rename_subobject(h, unreal.Text(tag))
            except Exception:
                pass
            c = SDL.get_object(SDL.get_data(h))
            c.set_editor_property("component_tags", [unreal.Name(tag)])
            c.set_editor_property("mobility", unreal.ComponentMobility.MOVABLE)
            c.set_collision_enabled(unreal.CollisionEnabled.NO_COLLISION)
    a.set_actor_hidden_in_game(True)
    return a


def spawn_editor(log=unreal.log):
    """the actor in the EDITOR world before Play (offscreen shot editors only, never saved)."""
    w = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_editor_world()
    a = find(w)
    if a is None:
        a = make_actor(log)
        log("[trees_near] editor-world actor spawned")
    return a
