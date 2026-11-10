"""Busan landmark models (sim/landmarks/landmarks_build.py -> 3D Tiles on disk) for the vworld mode on the local terrain.
The map's 'CesiumLandmarks' tileset (Scripts/add_landmarks_actor.py, run once with the editor closed; off = no URL) is
pointed at file:///C:/GyroSimTiles/landmarks/tiles/tileset.json (GYROSIM_LANDMARK_TILES moves it). GYROSIM_LANDMARKS=0 = off.
Called by sim_client._vworld_ground after the roads. The GIS boxes of the same buildings are left out of the building
tiles through C:/GyroSimTiles/landmarks/exclude.json (sim/buildings_build.py --tiles).
Glass / panels use Cesium's default glTF material (base colour + metallic-roughness textures baked in the glb), physics
meshes on so the camera floor trace stands on them like on the building tiles."""
import os
import unreal

TILES = os.environ.get("GYROSIM_LANDMARK_TILES", r"C:/GyroSimTiles/landmarks/tiles").replace("\\", "/")
TAG = "CesiumLandmarks"
SSE = 8.0


def url():
    p = TILES + "/tileset.json"
    return ("file:///" + p.lstrip("/")) if os.path.isfile(p) else None


def find(world):
    a = unreal.GameplayStatics.get_all_actors_with_tag(world, TAG)
    return a[0] if a else None


def spawn_editor(log=unreal.log):
    """the landmarks tileset as an actor in the EDITOR world before Play (Play copies the editor world). Dirties the level:
    only for the offscreen check editor on a temporary map copy (never saved), not for the user's editor."""
    w = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_editor_world()
    a = find(w)
    if a is None:
        a = unreal.get_editor_subsystem(unreal.EditorActorSubsystem).spawn_actor_from_class(unreal.Cesium3DTileset, unreal.Vector(0, 0, 0))
        a.tags = [unreal.Name(TAG)]
        a.set_editor_property("tileset_source", unreal.TilesetSource.FROM_URL)
        a.set_editor_property("url", "")
        a.set_actor_hidden_in_game(True)
        log("[landmarks] editor-world actor spawned")
    return a


def apply(world, log=unreal.log, georef=None):
    """point the landmarks tileset in `world` at the local tiles. -> the actor, or None (off / no tiles / no actor)."""
    if os.environ.get("GYROSIM_LANDMARKS", "1") == "0":
        log("[landmarks] off (GYROSIM_LANDMARKS=0)")
        return None
    u = url()
    if u is None:
        log("[landmarks] no tiles at %s (python -I sim/landmarks/landmarks_build.py --build)" % TILES)
        return None
    try:
        a = find(world)
        if a is None:                         # Python cannot spawn into the Play world -> the actor must be in the map
            log("[landmarks] no CesiumLandmarks actor in the map: run Scripts/add_landmarks_actor.py once with the editor closed")
            return None
        if georef is not None:
            try:
                a.set_georeference(georef)
            except Exception as e:
                log("[landmarks] georeference %r" % (e,))
        a.set_actor_location_and_rotation(unreal.Vector(0, 0, 0), unreal.Rotator(roll=0, pitch=0, yaw=90.0), False, True)
        a.set_editor_property("tileset_source", unreal.TilesetSource.FROM_URL)
        a.set_editor_property("url", u)
        for k, v in (("maximum_screen_space_error", SSE), ("create_physics_meshes", True), ("show_credits_on_screen", False)):
            try:
                a.set_editor_property(k, v)
            except Exception as e:
                log("[landmarks] %s %r" % (k, e))
        try:
            a.set_editor_property("material", None)            # Cesium default glTF material (PBR from the glb)
        except Exception:
            pass
        a.set_actor_hidden_in_game(False)
        a.refresh_tileset()
        log("[landmarks] on: %s" % u)
        return a
    except Exception as e:
        log("[landmarks] failed %r" % (e,))
        return None


def hide(world):
    a = find(world)
    if a is not None:
        a.set_actor_hidden_in_game(True)
