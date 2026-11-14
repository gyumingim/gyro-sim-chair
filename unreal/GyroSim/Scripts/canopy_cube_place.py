"""Canopy interior cube (11-14): place the SceneCaptureCube that view_fx.interior_cube bakes at Play into FlightMap
(Python cannot spawn actors into a Play world). Actor: SceneCaptureCube 'CanopyCube' (tag CanopyCube), attached to the
actor tagged Aircraft at the local point view_fx.CUBE_POS (412, 0, 75) cm, rotation 0, movable, render target
RT_CkCanopyInterior, capture every frame / on movement OFF (view_fx bakes it once per Play world: 2048 + mips, show-only
list of AircraftPart meshes, no direct sun / sky / fog / clouds). Idempotent: an existing CanopyCube actor is reused.
Run with no editor open, holding C:/GyroSimTiles/ue_offscreen.lock (sim/impostor/run_locked.ps1):
  UnrealEditor-Cmd.exe GyroSim.uproject -run=pythonscript -script=<this file> -nullrhi -unattended -nosplash
(direct package save as in cockpit_view_build.py: a rendering editor trips the Cesium credits widget leak check on save)
"""
import unreal

MAP = "/Game/Maps/FlightMap"
RT = "/Game/Cockpit/Materials/RT_CkCanopyInterior"
POS = (412.0, 0.0, 75.0)            # = view_fx.CUBE_POS (aircraft-local cm)
log = lambda *a: unreal.log("[cubeplace] " + " ".join(str(x) for x in a))
eas = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)


def main():
    w = unreal.EditorLoadingAndSavingUtils.load_map(MAP)
    if w is None or not w.get_path_name().startswith(MAP + "."):
        raise RuntimeError("FlightMap not loaded: %s" % (w.get_path_name() if w else None))
    acts = list(eas.get_all_level_actors())
    ac = [a for a in acts if "Aircraft" in {str(t) for t in a.tags}]
    if len(ac) != 1:
        raise RuntimeError("expected one Aircraft actor, found %d" % len(ac))
    ac = ac[0]
    caps = [a for a in acts if "CanopyCube" in {str(t) for t in a.tags}]
    log("aircraft", ac.get_actor_label(), ac.get_actor_location(), ac.get_actor_rotation(), "existing CanopyCube", len(caps))
    for extra in caps[1:]:
        eas.destroy_actor(extra)
    cap = caps[0] if caps else eas.spawn_actor_from_class(unreal.SceneCaptureCube, ac.get_actor_location(), ac.get_actor_rotation())
    cap.set_actor_label("CanopyCube")
    cap.tags = [unreal.Name("CanopyCube")]
    cap.root_component.set_mobility(unreal.ComponentMobility.MOVABLE)
    cap.attach_to_actor(ac, unreal.Name(""), unreal.AttachmentRule.KEEP_WORLD, unreal.AttachmentRule.KEEP_WORLD,
                        unreal.AttachmentRule.KEEP_WORLD, False)
    cap.root_component.set_relative_location_and_rotation(unreal.Vector(*POS), unreal.Rotator(0.0, 0.0, 0.0), False, True)
    cc = cap.get_component_by_class(unreal.SceneCaptureComponentCube)
    cc.set_editor_property("texture_target", unreal.load_asset(RT))
    cc.set_editor_property("capture_every_frame", False)
    cc.set_editor_property("capture_on_movement", False)
    cc.set_editor_property("capture_rotation", True)
    cc.set_editor_property("capture_source", unreal.SceneCaptureSource.SCS_SCENE_COLOR_HDR)
    log("CanopyCube", cap.get_path_name(), "parent", cap.get_attach_parent_actor().get_actor_label(),
        "rel", cap.root_component.get_editor_property("relative_location"), "world", cap.get_actor_location(),
        "rt", cc.get_editor_property("texture_target"), "every_frame", cc.get_editor_property("capture_every_frame"))
    ok = unreal.EditorLoadingAndSavingUtils.save_packages([w.get_outermost()], False)
    log("saved", MAP, ok)


try:
    main()
except Exception as e:
    import traceback
    log("error", repr(e), " | ".join(traceback.format_exc().splitlines()[-6:]))
