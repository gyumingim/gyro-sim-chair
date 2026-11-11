"""Impostor trees (11-11, docs/trees-impostor-busan.md) - DEFAULT since 11-11; GYROSIM_TREES_IMPOSTOR=0 = the old blob tiles.

Every Busan tree (the same ~19.6 M trees as the blob tiles: sim/trees_near_build.py --db -> C:/GyroSimTiles/veg/near/trees_near.bin,
position / height / crown radius / species) within RADIUS of the camera is one camera-facing card (2 triangles) drawn with
/Game/Trees/M_GyroTreeImp: a hemi-octahedral impostor of a real downloaded tree model (8 x 8 views of the upper hemisphere
baked in headless Blender, sim/impostor/; textures /Game/ThirdParty/Trees/Impostor/T_Imp_* - git-ignored, Fab / CC0 derived).
The cards go into the map's existing 'GyroTreesNear' actor (64 slots x 8 InstancedStaticMeshComponents, Scripts/
add_trees_near_actor.py): one slot = one BLOCK (5 x 5 data cells = 1.25 km), one component per kind (atlas + species colour).
Blocks beyond FAR_M use the one-view material variant (Far=1, cheaper); blocks beyond SHADOW_M cast no shadow.
Filling is spread over frames (BUDGET_MS of Python per frame).

Toggles (env):
  GYROSIM_TREES_IMPOSTOR=0    off -> the blob tiles (trees_look, the look before)
  GYROSIM_TREES_IMP_R         radius m (default 3900 = the blob tiles' reach)
  GYROSIM_TREES_IMP_FAR       distance m from which a block uses one view per tree (default 2000)
  GYROSIM_TREES_IMP_SHADOW_M  shadow-casting distance m (default 1500; 0 = no shadows)
  GYROSIM_TREES_IMP_GAIN      brightness multiplier on top of imp_info.json "gain"
  GYROSIM_TREES_IMP_DITHER=1  stochastic alpha (TSR-averaged coverage) instead of the plain 0.5 clip (default 0: streaks)
Called from trees_look.apply (sim_client._vworld_ground) - no other hook.
"""
import array, json, math, os, time
import unreal
import trees_near

TAG = trees_near.TAG
DIR = trees_near.DIR
INFO = os.environ.get("GYROSIM_IMPOSTOR_DIR", r"C:/GyroSimTiles/assets/trees_impostor").replace("\\", "/") + "/imp_info.json"
MAT = "/Game/Trees/M_GyroTreeImp"
CARD = "/Game/Trees/Imp/SM_GyroImpCard/StaticMeshes/SM_GyroImpCard"
TEX = "/Game/ThirdParty/Trees/Impostor/"
SLOTS, KINDS = trees_near.SLOTS, trees_near.KINDS
BLOCK = 5                                                    # data cells per block side (250 m cells -> 1.25 km)
BUDGET_MS = float(os.environ.get("GYROSIM_TREES_IMP_BUDGET_MS", "4"))
ST = dict(actor=None, georef=None, origin=None, h=None, t=0.0, loaded={}, free=[], queue=[], work=[], meta=None, f=None,
          blocks={}, kinds=[], mids={}, log=unreal.log, radius=3900.0, far=2000.0, shadow_m=1500.0, slot_comps={}, world=None,
          card=None, stats={})


def enabled():
    return (os.environ.get("GYROSIM_TREES", "1") != "0" and os.environ.get("GYROSIM_TREES_IMPOSTOR", "0") == "1"   # 11-11: OFF until finished (work stopped mid-integration)
            and os.environ.get("GYROSIM_TREES_NEAR", "0") != "1")


def _hash(i):
    return ((i * 2654435761) & 0xFFFFFFFF) / 4294967296.0


def _mid(world, mat, k, far):
    kd = ST["kinds"][k]
    mid = unreal.MaterialLibrary.create_dynamic_material_instance(world, mat)
    for p, t in (("TexA", kd["tex"][0]), ("TexB", kd["tex"][1])):
        tx = unreal.load_asset(TEX + t)
        if tx is None:
            raise RuntimeError("no texture " + TEX + t)
        mid.set_texture_parameter_value(p, tx)
    c = kd["color_mul"]
    mid.set_vector_parameter_value("ColorMul", unreal.LinearColor(c[0], c[1], c[2], 1.0))
    mid.set_scalar_parameter_value("Gain", ST["gain"])
    mid.set_scalar_parameter_value("Far", 1.0 if far else 0.0)
    # 11-11: plain alpha clip (dither + TSR smeared the cards into streaks in the close check shot)
    mid.set_scalar_parameter_value("Dither", float(os.environ.get("GYROSIM_TREES_IMP_DITHER", "0")))
    for kv in os.environ.get("GYROSIM_TREES_IMP_PARAMS", "").split(","):     # test overrides, e.g. AoAmt=0.5,Dither=0
        if "=" in kv:
            n, v = kv.split("=")
            mid.set_scalar_parameter_value(n.strip(), float(v))
    return mid


def apply(world, log=unreal.log, georef=None):
    """start the impostor trees in `world`. -> the actor, or None (off / missing data, actor, assets)."""
    ST["log"] = log
    if not enabled():
        log("[trees_imp] off")
        return None
    a = trees_near.find(world)
    if a is None:
        log("[trees_imp] no GyroTreesNear actor in the map (Scripts/add_trees_near_actor.py, editor closed)")
        return None
    js = DIR + "/trees_near.json"
    if not os.path.isfile(js) or not os.path.isfile(INFO):
        log("[trees_imp] missing %s or %s" % (js, INFO))
        return None
    if georef is None:
        g = unreal.GameplayStatics.get_all_actors_with_tag(world, "CesiumGeoreference")
        georef = g[0] if g else None
    if georef is None:
        log("[trees_imp] no CesiumGeoreference")
        return None
    t0 = time.monotonic()
    if ST["meta"] is None:
        ST["meta"] = json.load(open(js, encoding="utf-8"))
        blocks = {}
        for key in ST["meta"]["cells"]:
            i, j = map(int, key.split("_"))
            blocks.setdefault((i // BLOCK, j // BLOCK), []).append(key)
        ST["blocks"] = blocks
    if ST["f"] is None:
        ST["f"] = open(DIR + "/trees_near.bin", "rb")
    info = json.load(open(INFO, encoding="utf-8"))
    ST["kinds"] = info["kinds"][:KINDS]
    ST["gain"] = float(info.get("gain", 1.0)) * float(os.environ.get("GYROSIM_TREES_IMP_GAIN", "1"))
    ST["radius"] = float(os.environ.get("GYROSIM_TREES_IMP_R", "3900"))
    ST["far"] = float(os.environ.get("GYROSIM_TREES_IMP_FAR", "2000"))
    ST["shadow_m"] = float(os.environ.get("GYROSIM_TREES_IMP_SHADOW_M", "1500"))
    mat = unreal.load_asset(MAT)
    card = unreal.load_asset(CARD)
    if mat is None or card is None:
        log("[trees_imp] no material / card (Scripts/trees_imp_assets.py)")
        return None
    try:
        ST["mids"] = {(k, far): _mid(world, mat, k, far) for k in range(len(ST["kinds"])) for far in (False, True)}
    except Exception as e:
        log("[trees_imp] textures %r" % (e,))
        return None
    cs = trees_near.comps(a)
    ST["slot_comps"] = {s: [cs.get(trees_near.comp_tag(s, k)) for k in range(KINDS)] for s in range(SLOTS)}
    n = 0
    for s in range(SLOTS):
        for k, c in enumerate(ST["slot_comps"][s]):
            if c is None:
                continue
            c.clear_instances()
            if k >= len(ST["kinds"]):
                c.set_visibility(False, False)
                continue
            c.set_static_mesh(card)
            c.set_material(0, ST["mids"][(k, False)])
            c.set_cull_distances(0, int(ST["radius"] * 100.0))
            c.set_cast_shadow(False)
            c.set_collision_enabled(unreal.CollisionEnabled.NO_COLLISION)
            c.set_visibility(True, False)
            n += 1
    ST.update(world=world, work=[], queue=[], loaded={}, free=list(range(SLOTS)), card=card,
              stats=dict(blocks=0, trees=0, fill_ms=0.0, max_tick_ms=0.0))
    try:
        a.root_component.set_mobility(unreal.ComponentMobility.MOVABLE)
    except Exception:
        pass
    ST.update(actor=a, georef=georef, origin=trees_near.place(a, georef), t=1.0)
    a.set_actor_hidden_in_game(False)
    if ST["h"] is None:
        ST["h"] = unreal.register_slate_post_tick_callback(_tick)
    log("[trees_imp] on: radius %.0f m, far %.0f m, shadows to %.0f m, %d components, gain %.2f (%.1f s)" % (
        ST["radius"], ST["far"], ST["shadow_m"], n, ST["gain"], time.monotonic() - t0))
    return a


def _cam_local():
    try:
        p = unreal.GameplayStatics.get_player_camera_manager(ST["world"], 0).get_camera_location()
    except Exception:
        return None
    return ST["actor"].get_actor_transform().inverse_transform_location(p)


def _block_d2(c, bi, bj):
    size = ST["meta"]["cell_m"] * 100.0 * BLOCK
    dx = max(bi * size - c.x, 0.0, c.x - (bi + 1) * size)
    dy = max(bj * size - c.y, 0.0, c.y - (bj + 1) * size)
    return dx * dx + dy * dy


def _wanted(c):
    R = ST["radius"] * 100.0
    out = [(d2, b) for b in ST["blocks"] for d2 in (_block_d2(c, *b),) if d2 < R * R]
    out.sort()
    return out


def _pick(sp, h, idx):
    if sp == 0:
        return 3 if h < 7.0 else int(_hash(idx) * 3) % 3
    if sp == 1:
        return 3 if h < 7.0 else 7
    if sp == 2:
        return 4 + int(_hash(idx) * 3) % 3
    return 6                                                 # shrub: the alder, low and wide (crown data)


def _plan(b, slot):
    """read one block -> work items (slot, kind, transforms) for the fill queue. -> number of trees."""
    meta = ST["meta"]; rec = meta["rec"]; kinds = ST["kinds"]
    groups = {}
    tot = 0
    for key in ST["blocks"][b]:
        first, n = meta["cells"][key]
        ST["f"].seek(first * rec * 4)
        R = array.array("f")
        R.frombytes(ST["f"].read(n * rec * 4))
        for i in range(n):
            o = i * rec
            sp = int(R[o + 6]); h = max(R[o + 4], 1.5); r = max(R[o + 5], 0.8)
            k = _pick(sp, h, first + i)
            kd = kinds[k]
            sz = h / kd["h"]
            sxy = sz * min(1.4, max(0.75, r / (kd["crown_r"] * sz)))
            yaw = R[o + 3]
            cy, sy = math.cos(math.radians(yaw)), math.sin(math.radians(yaw))
            ox, oy, oz = kd["center_off"][0] * sxy * 100.0, -kd["center_off"][1] * sxy * 100.0, kd["center_off"][2] * sz * 100.0
            loc = unreal.Vector(R[o] + ox * cy - oy * sy, R[o + 1] + ox * sy + oy * cy, R[o + 2] + oz)
            s = kd["R"]
            groups.setdefault(k, []).append(unreal.Transform(loc, unreal.Rotator(roll=0.0, pitch=0.0, yaw=yaw),
                                                             unreal.Vector(s * sxy, s * sxy, s * sz)))
            tot += 1
    for k, T in groups.items():
        for a in range(0, len(T), 1000):
            ST["work"].append((b, slot, k, T[a:a + 1000]))
    return tot


def _clear_slot(slot):
    for c in ST["slot_comps"].get(slot, []):
        if c is not None and c.get_instance_count():
            c.clear_instances()


def _style_slot(slot, d2):
    far = d2 > (ST["far"] * 100.0) ** 2
    shadow = d2 < (ST["shadow_m"] * 100.0) ** 2
    for k, c in enumerate(ST["slot_comps"].get(slot, [])):
        if c is None or k >= len(ST["kinds"]):
            continue
        c.set_material(0, ST["mids"][(k, far)])
        c.set_cast_shadow(shadow)


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
                ST["origin"] = trees_near.place(a, g)
            c = _cam_local()
            if c is not None:
                want = _wanted(c)
                ws = {b: d2 for d2, b in want}
                for b in [x for x in ST["loaded"] if x not in ws]:          # blocks left behind -> slot free
                    slot = ST["loaded"].pop(b)
                    ST["work"] = [w for w in ST["work"] if w[1] != slot]
                    _clear_slot(slot)
                    ST["free"].append(slot)
                for b, slot in ST["loaded"].items():                       # near / far / shadow per block distance
                    _style_slot(slot, ws[b])
                ST["queue"] = [(d2, b) for d2, b in want if b not in ST["loaded"]]
        while (time.perf_counter() - t0) * 1000.0 < BUDGET_MS:
            if ST["work"]:
                b, slot, k, T = ST["work"].pop(0)
                c = ST["slot_comps"][slot][k]
                if c is not None:
                    c.add_instances(T, False, False)
                ST["stats"]["trees"] += len(T)
            elif ST["queue"] and ST["free"]:
                d2, b = ST["queue"].pop(0)
                slot = ST["free"].pop(0)
                _clear_slot(slot)
                _style_slot(slot, d2)
                ST["loaded"][b] = slot
                _plan(b, slot)
                ST["stats"]["blocks"] += 1
            else:
                break
        ms = (time.perf_counter() - t0) * 1000.0
        ST["stats"]["fill_ms"] = round(ms, 2)
        ST["stats"]["max_tick_ms"] = round(max(ST["stats"]["max_tick_ms"], ms), 2)
    except Exception as e:
        if str(e) != "gone":
            ST["log"]("[trees_imp] tick %r" % (e,))
        unreal.unregister_slate_post_tick_callback(ST["h"])
        ST.update(h=None, actor=None, georef=None)


def pending():
    return (len(ST["queue"]) + len(ST["work"])) if ST["h"] is not None else 0


def loaded_trees():
    tot = 0
    for slot in ST["loaded"].values():
        for c in ST["slot_comps"].get(slot, []):
            if c is not None:
                tot += c.get_instance_count()
    return tot


def follow_now():
    if ST["actor"] is not None and ST["georef"] is not None:
        ST["origin"] = trees_near.place(ST["actor"], ST["georef"])
        ST["t"] = 1.0


def hide(world):
    trees_near.hide(world)
