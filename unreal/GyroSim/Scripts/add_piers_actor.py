r"""Adds the 'CesiumPiers' tileset actor (OSM piers / breakwaters / quay faces, Content/Python/piers_look.py) to /Game/Maps/FlightMap
without rebuilding the map. Python cannot spawn an actor into the Play world, so the actor has to be in the map.

Headless, editor CLOSED (it saves the map):
  "C:\Program Files\Epic Games\UE_5.8\Engine\Binaries\Win64\UnrealEditor-Cmd.exe" <path>\GyroSim.uproject ^
      -run=pythonscript -script=<path>\Scripts\add_piers_actor.py -unattended -nosplash -nullrhi

Same kind of actor as CesiumRoads: off (no URL, hidden) until sim_client._vworld_ground calls
piers_look.apply at Play. Safe to run again (skips when it exists).
"""
import unreal

MAP = "/Game/Maps/FlightMap"
log = lambda *a: unreal.log("[add_piers] " + " ".join(str(x) for x in a))
eas = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
les = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)

les.load_level(MAP)
actors = eas.get_all_level_actors()
tagged = lambda t: [a for a in actors if unreal.Name(t) in a.tags]
if tagged("CesiumPiers"):
    log("CesiumPiers actor already in", MAP, "- nothing to do")
else:
    gr = tagged("CesiumGeoreference")
    if not gr:
        raise RuntimeError("CesiumGeoreference actor missing - run build_level.py")
    a = eas.spawn_actor_from_class(unreal.Cesium3DTileset, unreal.Vector(0, 0, 0))
    a.set_actor_label("CesiumPiers")
    a.tags = [unreal.Name("CesiumPiers")]
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
    log("CesiumPiers actor added, saved", MAP, ok, "actors", len(eas.get_all_level_actors()))
