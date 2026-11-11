"""3D trees on Busan's hills / parks (sim/veg_build.py -> 3D Tiles on disk) for the vworld mode on the local terrain.
The map's 'CesiumTrees' tileset (Scripts/add_trees_actor.py; off = no URL, hidden) is pointed at
file:///C:/GyroSimTiles/veg/tiles/tileset.json (GYROSIM_TREES_TILES moves it). GYROSIM_TREES=0 = off.
Streaming by distance is the tileset itself: nothing beyond ~3 km (empty tiles), one-lump far trees 1-3 km, full trees
inside ~1 km (REPLACE refinement, veg_build.GE). Instanced meshes (glTF EXT_mesh_gpu_instancing), no physics (the server
does not know trees either). Called by sim_client._vworld_ground after the roads; credit line in
sim/vworld_trees_attribution.png (sim_client._attribution uses it when this returned an actor).
Art pass 11-10: material /Game/Trees/M_GyroTree (Scripts/trees_material.py + trees_foliage.hlsl: leaf clumps, dark gaps,
per-clump lighting on the vertex-coloured blob crowns); GYROSIM_TREES_ART=0 = Cesium's stock material (the look before).
v2 (default, see V2 below): tiles_v2 + M_GyroTree2; GYROSIM_TREES_V2=0 = v1.
11-12: leaf-card trees tiles_cards + M_GyroTreeCard on top of v2 (GYROSIM_TREES_CARDS=0 = the v2 blobs)."""
import os
import unreal

TAG = "CesiumTrees"
SSE = float(os.environ.get("GYROSIM_TREES_SSE", "16"))
# Trees v2 (11-10 second pass, sim/veg_v2.py): clump-built pine / oak / shrub prototypes (broadleaf crown shapes from the
# Fab Megascans oak / alder models, sim/veg_proxy.py), species by terrain, rock outcrops left bare, leaf albedo colours,
# material M_GyroTree2 (two-sided foliage). A/B toggles (each on its own):
#   GYROSIM_TREES_V2=0     the v1 tiles + M_GyroTree (the look before; v2 tiles need the v2 material - packed vertex colour)
#   GYROSIM_TREES_LOOK2=0  v2 tiles, but the material extras off (per-tree variation, leaf noise, translucency, baked AO
#                          in the base colour) = plain decoded vertex colour
#   GYROSIM_TREES_CANOPY=0 no crown pattern on the photo forest beyond the trees (atmos_look / ground_look.hlsl)
#   GYROSIM_TREES_WIND=1   M_GyroTree2W (gentle sway, world position offset; off by default - cost not measured)
_V2_TILES = r"C:/GyroSimTiles/veg/tiles_v2"
_V1_TILES = r"C:/GyroSimTiles/veg/tiles"
# 11-12 leaf-card trees (sim/veg_cards_tiles.py + /Game/Trees/M_GyroTreeCard): default when built; GYROSIM_TREES_CARDS=0 =
# the old blob tiles (tiles_v2 + M_GyroTree2)
_CARD_TILES = r"C:/GyroSimTiles/veg/tiles_cards"
_CARD_MAT = "/Game/Trees/M_GyroTreeCard"
CARDS_DEFAULT = "1"


def cards_on():
    if os.environ.get("GYROSIM_TREES_CARDS", CARDS_DEFAULT) == "0" or os.environ.get("GYROSIM_TREES_TILES"):
        return False
    why = [k for k, ok in (("no tiles", os.path.isfile(_CARD_TILES + "/tileset.json")),
                           ("no material", unreal.load_asset(_CARD_MAT) is not None)) if not ok]
    if why:
        unreal.log("[trees] leaf-card trees unavailable (%s) -> blob tiles" % ", ".join(why))
    return not why
LOOK2_OFF = dict(VarAmt=0.0, GapDark=0.0, Bump=0.0, SssAmt=0.0, AoBase=0.0, AoAmb=0.0, RimAmt=0.0)
STATE = dict(v2=None)


def config(v2=None):
    """-> (v2, tiles folder, material path) for this launch (env) or the forced version."""
    if v2 is None:
        v2 = os.environ.get("GYROSIM_TREES_V2", "1") != "0"
    if v2 and not os.path.isfile(_V2_TILES + "/tileset.json") and not os.environ.get("GYROSIM_TREES_TILES"):
        v2 = False                                     # no v2 tiles built yet -> v1
    tiles = os.environ.get("GYROSIM_TREES_TILES", _V2_TILES if v2 else _V1_TILES).replace("\\", "/")
    if v2 and cards_on():
        return v2, _CARD_TILES, _CARD_MAT
    mat = ("/Game/Trees/M_GyroTree2" + ("W" if os.environ.get("GYROSIM_TREES_WIND", "0") == "1" else "")) if v2 else "/Game/Trees/M_GyroTree"
    return v2, tiles, mat


V2, TILES, MAT = config()


def url(tiles=None):
    p = (tiles or TILES) + "/tileset.json"
    return ("file:///" + p.lstrip("/")) if os.path.isfile(p) else None


def find(world):
    a = unreal.GameplayStatics.get_all_actors_with_tag(world, TAG)
    return a[0] if a else None


def spawn_editor(log=unreal.log):
    """the trees tileset as an actor in the EDITOR world before Play (Play copies the editor world). Dirties the level:
    only for the offscreen check editor (never saved), not for the user's editor."""
    w = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_editor_world()
    a = find(w)
    if a is None:
        a = unreal.get_editor_subsystem(unreal.EditorActorSubsystem).spawn_actor_from_class(unreal.Cesium3DTileset, unreal.Vector(0, 0, 0))
        a.tags = [unreal.Name(TAG)]
        a.set_editor_property("tileset_source", unreal.TilesetSource.FROM_URL)
        a.set_editor_property("url", "")
        a.set_actor_hidden_in_game(True)
        log("[trees] editor-world actor spawned")
    return a


def apply(world, log=unreal.log, georef=None, v2=None, look2=None, tiles=None):
    """point the map's trees tileset in `world` at the local tiles. -> the actor, or None (off / no tiles / no actor).
    v2 / look2: force the version / the v2 material extras (shot scripts' one-run A/B), else the env toggles."""
    if os.environ.get("GYROSIM_TREES", "1") == "0":
        log("[trees] off (GYROSIM_TREES=0)")
        return None
    near = None
    try:                                           # 11-11: opt-in real-leaf near trees (GYROSIM_TREES_NEAR=1, default off)
        import trees_near
        if trees_near.enabled():
            near = trees_near.apply(world, log, georef)
            if not trees_near.proxy_on():          # GYROSIM_TREES_PROXY=0 = no blob tiles (default 1 = blobs too)
                hide(world)
                log("[trees] blob tiles off (near trees %s; GYROSIM_TREES_NEAR=0 = the old look)" % ("on" if near else "unavailable"))
                return near
    except Exception as e:
        log("[trees] near trees %r" % (e,))
    try:                                           # 11-11: impostor trees, opt-in (GYROSIM_TREES_IMPOSTOR=1; default = blob tiles)
        import trees_imp
        if trees_imp.enabled():
            imp = trees_imp.apply(world, log, georef)
            if imp is not None:
                hide(world)
                log("[trees] impostor trees on, blob tiles off (GYROSIM_TREES_IMPOSTOR=0 = the old look)")
                return imp
            log("[trees] impostor trees unavailable -> blob tiles")
    except Exception as e:
        log("[trees] impostor trees %r" % (e,))
    V2, TILES, MAT = config(v2)
    if tiles:                                      # shot scripts: another tile build (e.g. the previous round) in the same run
        TILES = tiles.replace("\\", "/")
    if look2 is None:
        look2 = os.environ.get("GYROSIM_TREES_LOOK2", "1") != "0"
    STATE.update(v2=V2, look2=look2)
    u = url(TILES)
    if u is None:
        log("[trees] no tiles at %s (python -I sim/veg_build.py --prep --tiles)" % TILES)
        return None
    try:
        a = find(world)
        if a is None:                         # Python has no actor spawn into the Play world -> the actor must be in the map
            log("[trees] no CesiumTrees actor in the map: run Scripts/add_trees_actor.py once with the editor closed")
            return None
        if georef is not None:
            try:
                a.set_georeference(georef)
            except Exception as e:
                log("[trees] georeference %r" % (e,))
        a.set_actor_location_and_rotation(unreal.Vector(0, 0, 0), unreal.Rotator(roll=0, pitch=0, yaw=90.0), False, True)
        a.set_editor_property("tileset_source", unreal.TilesetSource.FROM_URL)
        a.set_editor_property("url", u)
        for k, v in (("maximum_screen_space_error", SSE), ("create_physics_meshes", False), ("show_credits_on_screen", False),
                     ("preload_siblings", False)):
            try:
                a.set_editor_property(k, v)
            except Exception as e:
                log("[trees] %s %r" % (k, e))
        m = None
        if V2 or os.environ.get("GYROSIM_TREES_ART", "1") != "0":
            try:
                m = unreal.load_asset(MAT)
            except Exception:
                m = None
        if m is not None and V2 and not look2:          # A/B: v2 material extras off (dynamic instance, Cesium copies it)
            try:
                m = unreal.MaterialLibrary.create_dynamic_material_instance(world, m)
                for k, v in LOOK2_OFF.items():
                    m.set_scalar_parameter_value(k, v)
            except Exception as e:
                log("[trees] look2 off %r" % (e,))
        try:
            a.set_editor_property("material", m)
        except Exception as e:
            log("[trees] material %r" % (e,))
        a.set_actor_hidden_in_game(False)
        a.refresh_tileset()
        log("[trees] on: %s (sse %.0f) material %s look2 %s" % (u, SSE, MAT if m else "Cesium default", look2 if V2 else "-"))
        return a
    except Exception as e:
        log("[trees] failed %r" % (e,))
        return None


def hide(world):
    a = find(world)
    if a is not None:
        a.set_actor_hidden_in_game(True)
