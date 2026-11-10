"""3D bridges / elevated roads over Busan (OpenStreetMap, sim/roads_build.py -> 3D Tiles on disk) for the vworld mode
on the local terrain. The map's 'CesiumRoads' tileset (build_level.py, or Scripts/add_roads_actor.py for an existing map;
off = no URL) is pointed at file:///C:/GyroSimTiles/roads/tiles/tileset.json (GYROSIM_ROADS_TILES moves it). GYROSIM_ROADS=0 = off.
Called by sim_client._vworld_ground after the buildings; the on-screen credit (© OpenStreetMap contributors) is the
plate sim/vworld_roads_attribution.png, chosen by sim_client._attribution when this returned True.
No physics meshes (the server does not know the bridges either: flying through one is not a crash)."""
import os
import unreal

TILES = os.environ.get("GYROSIM_ROADS_TILES", r"C:/GyroSimTiles/roads/tiles").replace("\\", "/")
TAG = "CesiumRoads"
SSE = 16.0


def url():
    p = TILES + "/tileset.json"
    return ("file:///" + p.lstrip("/")) if os.path.isfile(p) else None


def find(world):
    a = unreal.GameplayStatics.get_all_actors_with_tag(world, TAG)
    return a[0] if a else None


def spawn_editor(log=unreal.log):
    """the roads tileset as an actor in the EDITOR world before Play (Play copies the editor world). Dirties the level:
    only for the offscreen check editor (never saved), not for the user's editor."""
    w = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_editor_world()
    a = find(w)
    if a is None:
        a = unreal.get_editor_subsystem(unreal.EditorActorSubsystem).spawn_actor_from_class(unreal.Cesium3DTileset, unreal.Vector(0, 0, 0))
        a.tags = [unreal.Name(TAG)]
        a.set_editor_property("tileset_source", unreal.TilesetSource.FROM_URL)
        a.set_editor_property("url", "")
        a.set_actor_hidden_in_game(True)
        log("[roads] editor-world actor spawned")
    return a


def apply(world, log=unreal.log, georef=None):
    """spawn (or reuse) the roads tileset in `world`. -> the actor, or None (off / no tiles / failed)."""
    if os.environ.get("GYROSIM_ROADS", "1") == "0":
        log("[roads] off (GYROSIM_ROADS=0)")
        return None
    u = url()
    if u is None:
        log("[roads] no tiles at %s (python -I sim/roads_build.py --tiles)" % TILES)
        return None
    try:
        a = find(world)
        if a is None:                         # Python has no actor spawn into the Play world -> the actor must be in the map
            log("[roads] no CesiumRoads actor in the map: run Scripts/add_roads_actor.py once with the editor closed")
            return None
        if georef is not None:
            try:
                a.set_georeference(georef)
            except Exception as e:
                log("[roads] georeference %r" % (e,))
        a.set_actor_location_and_rotation(unreal.Vector(0, 0, 0), unreal.Rotator(roll=0, pitch=0, yaw=90.0), False, True)
        a.set_editor_property("tileset_source", unreal.TilesetSource.FROM_URL)
        a.set_editor_property("url", u)
        for k, v in (("maximum_screen_space_error", SSE), ("create_physics_meshes", False), ("show_credits_on_screen", False)):
            try:
                a.set_editor_property(k, v)
            except Exception as e:
                log("[roads] %s %r" % (k, e))
        a.set_actor_hidden_in_game(False)
        a.refresh_tileset()
        log("[roads] on: %s" % u)
        return a
    except Exception as e:
        log("[roads] failed %r" % (e,))
        return None


def hide(world):
    a = find(world)
    if a is not None:
        a.set_actor_hidden_in_game(True)
