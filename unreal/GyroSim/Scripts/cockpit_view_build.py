"""Cockpit v2 viewing level (11-13): /Game/Maps/CockpitView = a copy of FlightMap with only the aircraft / cockpit (v2 meshes,
as cockpit_v2.apply swaps them at Play), the camera rig (SimView = pilot eye) and the sky / sun / fog / clouds / post-process
actors, with the Play look baked in (sim_client.apply_preset 'monitor' = realism v2 + atmos_look + light_look + grade_look,
then tune_look with the slider values). No Cesium / city / trees / airfield / HUD symbology plate. FlightMap is never saved.
Build (no editor open; holds C:/GyroSimTiles/ue_offscreen.lock):
  1. copy Content/Maps/FlightMap.umap to Content/Maps/CockpitView.umap on disk (EditorAssetLibrary duplicate / save-as of a
     map failed in UE 5.8, and saving in a rendering editor trips the Cesium credits widget's world-leak check)
  2. UnrealEditor-Cmd.exe GyroSim.uproject -run=pythonscript -script=<this file> -nullrhi -unattended -nosplash
Open it: CockpitView.bat (repo root) -> Scripts/cockpit_view_open.py puts the editor camera at the eye.
"""
import os, sys, time
import unreal

SRC, DST = "/Game/Maps/FlightMap", "/Game/Maps/CockpitView"
ALT_CM = 35000.0                                   # aircraft 350 m above the sky atmosphere ground (the A/B view's height)
ENV = ("DirectionalLight", "SkyLight", "SkyAtmosphere", "VolumetricCloud", "ExponentialHeightFog", "PostProcessVolume")
ROOT_TAGS = ("Aircraft", "SimCamera", "SimView", "Canopy", "Gear", "Pilot", "PilotBody", "PilotHead", "CockpitFill", "Cockpit",
             "AircraftPart")
DROP_TAGS = ("Overlay", "HUD", "Minimap", "CrashBack", "CrashPanel", "TutorPanel", "KeyPanel", "Attribution", "BeginnerLabel")
INFRA = ("WorldSettings", "Brush", "DefaultPhysicsVolume", "GameplayDebuggerPlayerManager", "AbstractNavData", "LevelBounds")
EAL = unreal.EditorAssetLibrary
les = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
eas = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
ues = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem)
log = lambda *a: unreal.log("[ckview] " + " ".join(str(x) for x in a))
ST = dict(t=time.monotonic(), phase="wait", h=None)
PY = os.path.join(unreal.Paths.project_dir(), "Content", "Python")
SCR = os.path.dirname(os.path.abspath(__file__)) if "__file__" in globals() else os.path.join(unreal.Paths.project_dir(), "Scripts")
for p in (PY, SCR):
    if p not in sys.path:
        sys.path.insert(0, p)


def tags(a):
    return {str(t) for t in a.tags}


def parent(a):
    try:
        return a.get_attach_parent_actor()
    except Exception:
        return None


def build():
    w = unreal.EditorLoadingAndSavingUtils.load_map(DST)
    if w is None:
        raise RuntimeError("load failed")
    if not w.get_path_name().startswith(DST + "."):
        raise RuntimeError("current world is %s, not %s - stopping (FlightMap must not be changed)" % (w.get_path_name(), DST))
    acts = list(eas.get_all_level_actors())
    keep = set()
    for a in acts:
        cls = a.get_class().get_name()
        if cls in ENV or (tags(a) & set(ROOT_TAGS)) or any(t.startswith(("Needle_", "Light_", "MFD_")) or t in (
                "StickPivot", "ThrottlePivot", "PedalL", "PedalR", "GearHandle", "GearLights", "ADIBall") for t in tags(a)):
            keep.add(a)
    changed = True                                 # whole attachment trees of what we keep (untagged needle frames etc.)
    while changed:
        changed = False
        for a in acts:
            if a in keep:
                continue
            p = parent(a)
            if (p is not None and p in keep) or any(parent(k) == a for k in keep):
                keep.add(a); changed = True
    drop = [a for a in acts if (a not in keep and a.get_class().get_name() not in INFRA) or (tags(a) & set(DROP_TAGS))]
    log("keep", len(keep) - len([a for a in drop if a in keep]), "drop", len(drop), ":",
        ", ".join(sorted("%s(%s)" % (a.get_actor_label(), a.get_class().get_name()) for a in drop))[:3000])
    for a in drop:
        eas.destroy_actor(a)
    import cockpit_v2                              # v2 meshes, as at Play
    log("cockpit_v2", cockpit_v2.apply(w))
    for a in eas.get_all_level_actors():           # lift the aircraft / rig / pilot roots
        if a.get_class().get_name() in ENV or a.get_class().get_name() in INFRA or parent(a) is not None:
            continue
        p = a.get_actor_location()
        a.set_actor_location(unreal.Vector(p.x, p.y, p.z + ALT_CM), False, True)
    import sim_client
    try:
        sim_client.stop()
    except Exception:
        pass
    sim_client.apply_preset("monitor", w)          # cvars + realism v2 + atmos + light + grade (+ tune_look.start)
    import tune_look
    v = {k: x for k, x in tune_look.values().items() if not k.startswith("off_")}
    tune_look.apply(w, v)                          # slider values (sun direction etc.), as the running sim applies them
    pkg = w.get_outermost()                        # direct package save (save_current_level re-loads the renamed world and
    ok = unreal.EditorLoadingAndSavingUtils.save_packages([pkg], False)   # trips the Cesium credits widget leak check)
    log("saved", DST, ok)
    return w


if __name__ == "__main__" or True:
    try:
        build()
    except Exception as e:
        import traceback
        log("error", repr(e), " | ".join(traceback.format_exc().splitlines()[-6:]))
