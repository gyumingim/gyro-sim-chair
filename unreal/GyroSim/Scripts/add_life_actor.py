r"""Adds the 'GyroLife' actor (moving cars / ships, Content/Python/life_look.py) to /Game/Maps/FlightMap without
rebuilding the map. Python cannot spawn an actor into the Play world, so the actor has to be in the map.

Headless, editor CLOSED (it saves the map), after Scripts/life_assets.py:
  "C:\Program Files\Epic Games\UE_5.8\Engine\Binaries\Win64\UnrealEditor-Cmd.exe" <path>\GyroSim.uproject ^
      -run=pythonscript -script=<path>\Scripts\add_life_actor.py -unattended -nosplash -nullrhi

A StaticMeshActor (no mesh) with one empty InstancedStaticMeshComponent per life mesh (tags LifeVehicle ... LifeWake),
hidden until life_look.apply fills it at Play. Safe to run again (skips when it exists). GYROSIM_LIFE_MAP = another map.
"""
import os
import unreal
import life_look

MAP = os.environ.get("GYROSIM_LIFE_MAP", "/Game/Maps/FlightMap")
log = lambda *a: unreal.log("[add_life] " + " ".join(str(x) for x in a))
eas = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
les = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)

les.load_level(MAP)
have = [a for a in eas.get_all_level_actors() if unreal.Name(life_look.TAG) in a.tags]
if have:
    log(life_look.TAG, "actor already in", MAP, "- nothing to do")
else:
    a = life_look.make_actor(log)
    ok = les.save_current_level()
    log(life_look.TAG, "actor added with", len(life_look.comps(a)), "components, saved", MAP, ok)
