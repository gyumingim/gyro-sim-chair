r"""Adds the 'GyroTreesNear' actor (real-leaf trees near the aircraft, Content/Python/trees_near.py) to /Game/Maps/FlightMap
without rebuilding the map. Python cannot spawn an actor into the Play world, so the actor has to be in the map.

Headless, editor CLOSED (it saves the map), holding C:\GyroSimTiles\ue_offscreen.lock:
  "C:\Program Files\Epic Games\UE_5.8\Engine\Binaries\Win64\UnrealEditor-Cmd.exe" <path>\GyroSim.uproject ^
      -run=pythonscript -script=<path>\Scripts\add_trees_near_actor.py -unattended -nosplash -nullrhi

A StaticMeshActor (no mesh) with trees_near.SLOTS x len(MESHES) empty InstancedStaticMeshComponents (tags TN_<slot>_<mesh>),
hidden until trees_near.apply fills it at Play. The map references no third-party asset (meshes are set at Play).
Safe to run again (skips when it exists). GYROSIM_TREES_NEAR_MAP = another map.
"""
import os
import unreal
import trees_near

MAP = os.environ.get("GYROSIM_TREES_NEAR_MAP", "/Game/Maps/FlightMap")
log = lambda *a: unreal.log("[add_trees_near] " + " ".join(str(x) for x in a))
eas = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
les = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)

les.load_level(MAP)
have = [a for a in eas.get_all_level_actors() if unreal.Name(trees_near.TAG) in a.tags]
if have:
    log(trees_near.TAG, "actor already in", MAP, "- nothing to do")
else:
    a = trees_near.make_actor(log)
    ok = les.save_current_level()
    log(trees_near.TAG, "actor added with", len(trees_near.comps(a)), "components, saved", MAP, ok)
