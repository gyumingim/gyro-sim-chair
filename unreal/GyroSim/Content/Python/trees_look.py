"""3D trees on Busan's hills / parks (sim/veg_build.py -> 3D Tiles on disk) for the vworld mode on the local terrain.
The map's 'CesiumTrees' tileset (Scripts/add_trees_actor.py; off = no URL, hidden) is pointed at
file:///C:/GyroSimTiles/veg/tiles/tileset.json (GYROSIM_TREES_TILES moves it). GYROSIM_TREES=0 = off.
Streaming by distance is the tileset itself: nothing beyond ~3 km (empty tiles), one-lump far trees 1-3 km, full trees
inside ~1 km (REPLACE refinement, veg_build.GE). Instanced meshes (glTF EXT_mesh_gpu_instancing), no physics (the server
does not know trees either). Called by sim_client._vworld_ground after the roads; credit line in
sim/vworld_trees_attribution.png (sim_client._attribution uses it when this returned an actor)."""
import os
import unreal

TILES = os.environ.get("GYROSIM_TREES_TILES", r"C:/GyroSimTiles/veg/tiles").replace("\\", "/")
TAG = "CesiumTrees"
SSE = float(os.environ.get("GYROSIM_TREES_SSE", "16"))


def url():
    p = TILES + "/tileset.json"
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


def apply(world, log=unreal.log, georef=None):
    """point the map's trees tileset in `world` at the local tiles. -> the actor, or None (off / no tiles / no actor)."""
    if os.environ.get("GYROSIM_TREES", "1") == "0":
        log("[trees] off (GYROSIM_TREES=0)")
        return None
    u = url()
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
        a.set_actor_hidden_in_game(False)
        a.refresh_tileset()
        log("[trees] on: %s (sse %.0f)" % (u, SSE))
        return a
    except Exception as e:
        log("[trees] failed %r" % (e,))
        return None


def hide(world):
    a = find(world)
    if a is not None:
        a.set_actor_hidden_in_game(True)
