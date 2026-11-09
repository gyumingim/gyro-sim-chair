"""Adds the Busan minimap plate (actor tag 'Minimap') to /Game/Maps/FlightMap without rebuilding the map.

Headless, editor closed:
  "C:\\Program Files\\Epic Games\\UE_5.8\\Engine\\Binaries\\Win64\\UnrealEditor-Cmd.exe" <path>\\GyroSim.uproject ^
      -run=pythonscript -script=<path>\\Scripts\\add_minimap.py -unattended -nosplash -nullrhi

Same kind of plate as 'Attribution' (build_level.py): a Plane with M_Crash (unlit, no depth test), attached to the SimView
camera, hidden in game. sim_client._minimap shows it (top right on the monitor, head-locked lower right in VR) and draws the
map + aircraft marker into its texture. build_level.py makes the same actor on a full rebuild. Safe to run again (skips
when the actor exists).
"""
import unreal

MAP = "/Game/Maps/FlightMap"
log = lambda *a: unreal.log("[add_minimap] " + " ".join(str(x) for x in a))
eas = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
les = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)

les.load_level(MAP)
actors = eas.get_all_level_actors()
tagged = lambda t: [a for a in actors if unreal.Name(t) in a.tags]
if tagged("Minimap"):
    log("Minimap actor already in", MAP, "- nothing to do")
else:
    view, att = tagged("SimView"), tagged("Attribution")
    if not view or not att:
        raise RuntimeError("SimView / Attribution actor missing - run build_level.py")
    view, att = view[0], att[0]
    src = att.static_mesh_component
    a = eas.spawn_actor_from_class(unreal.StaticMeshActor, att.get_actor_location(), att.get_actor_rotation())
    a.set_actor_label("Minimap")
    c = a.static_mesh_component
    c.set_mobility(unreal.ComponentMobility.MOVABLE)
    c.set_static_mesh(src.static_mesh)
    c.set_material(0, src.get_material(0))
    c.set_editor_property("cast_shadow", False)
    c.set_collision_enabled(unreal.CollisionEnabled.NO_COLLISION)
    c.set_editor_property("translucency_sort_priority", 98)      # under the crash screen (100 / 101), next to the source note (99)
    a.set_actor_scale3d(unreal.Vector(0.3, 0.3, 1.0))
    a.tags = [unreal.Name("Minimap"), unreal.Name("Overlay")]
    a.set_actor_hidden_in_game(True)
    a.attach_to_actor(view, unreal.Name(""), unreal.AttachmentRule.KEEP_WORLD, unreal.AttachmentRule.KEEP_WORLD,
                      unreal.AttachmentRule.KEEP_WORLD, False)
    ok = les.save_current_level()
    log("Minimap actor added, saved", MAP, ok, "actors", len(eas.get_all_level_actors()))
