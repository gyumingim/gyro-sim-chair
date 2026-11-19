"""Pilot body v2 (11-15): the UE5 mannequin (Manny) seated as a jet pilot, swapped in at Play.

/Game/ThirdParty/Mannequins/SKM_PilotManny (Epic content, gitignored) is built offline by Scripts/pilot/ue_manny.py
from the pose in Scripts/pilot/manny_pose.py: thighs on the seat, left thigh under the kneeboard, right hand on the
sidestick, left hand on the throttle, feet toward the pedals, head removed (the eye sits there) and the neck capped.
Its vertices are already posed in aircraft body cm (the reference pose is never animated), so it simply replaces the
mesh of the existing PilotBody SkeletalMeshActor, which already rides on the Aircraft actor with an identity
transform. (Python cannot spawn actors into a Play world - canopy_ghost.py - so nothing is spawned.)
Flat matte materials (M_CkSurface instances): olive-grey suit, darker G-suit trousers, black gloves and boots.

GYROSIM_PILOT=old keeps the old Blender pilot (with its control morphs). A missing asset (fresh clone) keeps it too.
The PilotHead helmet (outside views / its shadow in the cockpit), the PilotBody tag (kept out of the canopy reflection
cube) and the canopy shader's analytic helmet / pilot spheres are unchanged.
"""
import os
import unreal

MESH = "/Game/ThirdParty/Mannequins/SKM_PilotManny"
# 11-19: the same pilot with control morph targets (hands ride on the stick / throttle, feet on the pedals; built by
# Scripts/pilot/manny_fbx.py + ue_manny.import_fbx). Missing asset or GYROSIM_PILOT_HANDS=0 -> the static one above.
MESH_M = "/Game/ThirdParty/Mannequins/SKM_PilotMannyM"
_use = dict(path=None)
SLOTS = ("PM_Suit", "PM_GSuit", "PM_Glove", "PM_Boot", "PM_Harness")
_st = {}                                    # actor path -> (old mesh, old materials)


def _log(*a):
    unreal.log("[pilot_manny] " + " ".join(str(x) for x in a))


def wanted():
    return os.environ.get("GYROSIM_PILOT", "manny").strip().lower() != "old"


def _pick():
    if os.environ.get("GYROSIM_PILOT_HANDS", "1").strip() != "0" and unreal.load_asset(MESH_M) is not None:
        return MESH_M
    return MESH


def has_morphs():
    """True when the mesh now on the PilotBody actor has the control morph targets (sim_client._pilot drives them)"""
    return _use["path"] == MESH_M


def _smc(actor):
    return actor.get_component_by_class(unreal.SkeletalMeshComponent) if actor else None


def _swap(actor, new, path=None):
    """new=True: Manny mesh + materials; False: back to what the actor had."""
    c = _smc(actor)
    key = actor.get_path_name()
    if key not in _st:
        _st[key] = (c.get_skinned_asset() if hasattr(c, "get_skinned_asset") else c.get_editor_property("skeletal_mesh_asset"),
                    list(c.get_materials()))
    if new:
        path = path or _pick()
        mesh = unreal.load_asset(path)
        c.set_skeletal_mesh_asset(mesh)
        names = [str(n) for n in c.get_material_slot_names()]
        for i in range(len(names)):                 # by slot name (the FBX build keeps only the used slots), else by index
            sl = next((s for s in SLOTS if names[i].startswith(s)), SLOTS[i] if i < len(SLOTS) else None)
            mi = unreal.load_asset("/Game/ThirdParty/Mannequins/MI_" + sl) if sl else None
            if mi is not None:
                c.set_material(i, mi)
        _use["path"] = path
    else:
        mesh, mats = _st[key]
        c.set_skeletal_mesh_asset(mesh)
        for i, m in enumerate(mats):
            c.set_material(i, m)
        _use["path"] = None
    return actor


def apply(world, old_body):
    """put the Manny mesh on the PilotBody actor. Returns the actor (Manny on) or None (old pilot kept). Never raises."""
    try:
        if world is None or old_body is None or not wanted():
            return None
        if unreal.load_asset(MESH) is None:           # (does_asset_exist refuses during Play - mfd_map note)
            _log("asset missing (run Scripts/pilot/ue_manny.py) - old pilot kept")
            return None
        _swap(old_body, True)
        _log("on: %s on %s (GYROSIM_PILOT=old for the old pilot)" % (_use["path"], old_body.get_actor_label()))
        return old_body
    except Exception as e:
        _log("failed - old pilot kept", repr(e))
        try:
            _swap(old_body, False)
        except Exception:
            pass
        return None


def set_mode(world, mode):
    """runtime A/B (shots): mode 'old', 'manny' (default pick), 'static' (no morphs) or 'hands'. Returns the PilotBody
    actor. (sim_client reads has_morphs() only at bind: switching to 'hands' in a run that started static shows the
    neutral pose.)"""
    a = list(unreal.GameplayStatics.get_all_actors_with_tag(world, "PilotBody"))
    if not a:
        return None
    return _swap(a[0], mode != "old", {"static": MESH, "hands": MESH_M}.get(mode))
