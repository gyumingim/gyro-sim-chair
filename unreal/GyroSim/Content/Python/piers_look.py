"""Piers / breakwaters / groynes and port quay faces over Busan (OpenStreetMap, sim/coast_build.py --piers -> 3D Tiles on disk)
for the vworld mode on the local terrain: the map's 'CesiumPiers' tileset (Scripts/add_piers_actor.py, off = no URL) is pointed
at file:///C:/GyroSimTiles/piers/tiles/tileset.json (GYROSIM_PIERS_TILES moves it). GYROSIM_PIERS=0 = off.
Called by sim_client._vworld_ground next to the roads; the on-screen OSM credit is the roads plate
(sim/vworld_roads_attribution.png, © OpenStreetMap contributors), chosen by sim_client._attribution when roads or piers are on.
No physics meshes (like the bridges)."""
import os
import unreal

TILES = os.environ.get("GYROSIM_PIERS_TILES", r"C:/GyroSimTiles/piers/tiles").replace("\\", "/")
TAG = "CesiumPiers"
SSE = 16.0


def url():
    p = TILES + "/tileset.json"
    return ("file:///" + p.lstrip("/")) if os.path.isfile(p) else None


def find(world):
    a = unreal.GameplayStatics.get_all_actors_with_tag(world, TAG)
    return a[0] if a else None


def spawn_editor(log=unreal.log):
    """the piers tileset as an actor in the EDITOR world before Play (offscreen check editors only, never saved)."""
    w = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_editor_world()
    a = find(w)
    if a is None:
        a = unreal.get_editor_subsystem(unreal.EditorActorSubsystem).spawn_actor_from_class(unreal.Cesium3DTileset, unreal.Vector(0, 0, 0))
        a.tags = [unreal.Name(TAG)]
        a.set_editor_property("tileset_source", unreal.TilesetSource.FROM_URL)
        a.set_editor_property("url", "")
        a.set_actor_hidden_in_game(True)
        log("[piers] editor-world actor spawned")
    return a


def apply(world, log=unreal.log, georef=None):
    """point the piers tileset in `world` at the tiles. -> the actor, or None (off / no tiles / no actor)."""
    if os.environ.get("GYROSIM_PIERS", "1") == "0":
        log("[piers] off (GYROSIM_PIERS=0)")
        a = find(world)
        if a is not None:
            a.set_actor_hidden_in_game(True)
        return None
    u = url()
    if u is None:
        log("[piers] no tiles at %s (python -I sim/coast_build.py --piers)" % TILES)
        return None
    try:
        a = find(world)
        if a is None:
            log("[piers] no CesiumPiers actor in the map: run Scripts/add_piers_actor.py once with the editor closed")
            return None
        if georef is not None:
            try:
                a.set_georeference(georef)
            except Exception as e:
                log("[piers] georeference %r" % (e,))
        a.set_actor_location_and_rotation(unreal.Vector(0, 0, 0), unreal.Rotator(roll=0, pitch=0, yaw=90.0), False, True)
        a.set_editor_property("tileset_source", unreal.TilesetSource.FROM_URL)
        a.set_editor_property("url", u)
        for k, v in (("maximum_screen_space_error", SSE), ("create_physics_meshes", False), ("show_credits_on_screen", False)):
            try:
                a.set_editor_property(k, v)
            except Exception as e:
                log("[piers] %s %r" % (k, e))
        a.set_actor_hidden_in_game(False)
        a.refresh_tileset()
        log("[piers] on: %s" % u)
        return a
    except Exception as e:
        log("[piers] failed %r" % (e,))
        return None
