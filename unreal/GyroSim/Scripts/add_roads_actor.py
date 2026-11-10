r"""Adds the 'CesiumRoads' tileset actor (OSM bridges / elevated roads, Content/Python/roads_look.py) to /Game/Maps/FlightMap
without rebuilding the map. Python cannot spawn an actor into the Play world, so the actor has to be in the map.

Headless, editor CLOSED (it saves the map):
  "C:\Program Files\Epic Games\UE_5.8\Engine\Binaries\Win64\UnrealEditor-Cmd.exe" <path>\GyroSim.uproject ^
      -run=pythonscript -script=<path>\Scripts\add_roads_actor.py -unattended -nosplash -nullrhi

Same kind of actor as CesiumBuildings (build_level.py): off (no URL, hidden) until sim_client._vworld_ground calls
roads_look.apply at Play. build_level.py makes the same actor on a full rebuild. Safe to run again (skips when it exists).
"""
import unreal

MAP = "/Game/Maps/FlightMap"
log = lambda *a: unreal.log("[add_roads] " + " ".join(str(x) for x in a))
eas = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
les = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)

les.load_level(MAP)
actors = eas.get_all_level_actors()
tagged = lambda t: [a for a in actors if unreal.Name(t) in a.tags]
if tagged("CesiumRoads"):
    log("CesiumRoads actor already in", MAP, "- nothing to do")
else:
    gr = tagged("CesiumGeoreference")
    if not gr:
        raise RuntimeError("CesiumGeoreference actor missing - run build_level.py")
    a = eas.spawn_actor_from_class(unreal.Cesium3DTileset, unreal.Vector(0, 0, 0))
    a.set_actor_label("CesiumRoads")
    a.tags = [unreal.Name("CesiumRoads")]
    try:
        a.root_component.set_mobility(unreal.ComponentMobility.MOVABLE)
    except Exception as e:
        log("mobility", e)
    a.set_georeference(gr[0])
    a.set_editor_property("tileset_source", unreal.TilesetSource.FROM_URL)
    a.set_editor_property("url", "")
    a.set_actor_location_and_rotation(unreal.Vector(0, 0, 0), unreal.Rotator(yaw=90.0), False, True)
    a.set_actor_hidden_in_game(True)
    ok = les.save_current_level()
    log("CesiumRoads actor added, saved", MAP, ok, "actors", len(eas.get_all_level_actors()))
