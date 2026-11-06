"""Pilot body in the Unreal level (developer step, run in the GUI editor - not in a -nullrhi commandlet).

    exec(open(r"<project>/Scripts/pilot/ue_pilot.py").read())      or   build()  after import

Imports the meshes made by Scripts/pilot/pilot_blender.py from PILOT_SRC (C:/GyroSimParts/thirdparty/pilot/out, generated
from a third-party CC0 model, see SOURCE.md there) to /Game/ThirdParty/Pilot (not in git, like the F-16), makes one
material instance per slot from the cockpit master M_CkSurface and places them in the open level:
  PilotBody  SkeletalMeshActor, attached to the Aircraft actor (mesh in UE body cm); morph targets for the controls
             (StickR/L/F/B, ThrF/B, RudR/L, ToeL/R) set every frame by sim_client._pilot
  PilotHead  StaticMeshActor (helmet, visor, mask; origin = the eye), attached to the SimView camera so it follows the
             look / HMD. sim_client hides it from the main pass in the cockpit view (it still casts shadows) and moves
             it onto the aircraft for the outside views.
Saves the assets and the level.
"""
import json, os
import unreal

PILOT_SRC = os.environ.get("GYROSIM_PILOT_SRC", "C:/GyroSimParts/thirdparty/pilot/out")
DEST = "/Game/ThirdParty/Pilot"
EAL, MEL = unreal.EditorAssetLibrary, unreal.MaterialEditingLibrary
eas = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
log = lambda *a: unreal.log("[pilot] " + " ".join(str(x) for x in a))

# slot -> M_CkSurface parameters (colours linear). Sage-green flight suit, darker G-suit, black harness / gloves / boots,
# grey-white helmet, dark visor, olive-black mask, black hose.
SLOT_PRM = {
    "PL_Suit": dict(Tint=(0.16, 0.18, 0.12), Rough=0.85, RoughVar=0.15, Sheen=0.0, Polish=0.0),
    "PL_GSuit": dict(Tint=(0.12, 0.13, 0.09), Rough=0.8, RoughVar=0.15, Sheen=0.0, Polish=0.0),
    "PL_Harness": dict(Tint=(0.05, 0.05, 0.048), Rough=0.7, RoughVar=0.2, Sheen=0.1, Polish=0.2),
    "PL_Glove": dict(Tint=(0.04, 0.035, 0.03), Rough=0.6, RoughVar=0.2, Sheen=0.3, Polish=0.3),
    "PL_Boot": dict(Tint=(0.03, 0.03, 0.03), Rough=0.45, RoughVar=0.2, Sheen=0.3, Polish=0.3),
    "PL_Helmet": dict(Tint=(0.50, 0.51, 0.50), Rough=0.4, RoughVar=0.2, Sheen=0.3, Polish=0.2),
    "PL_Visor": dict(Tint=(0.01, 0.01, 0.012), Rough=0.05, RoughVar=0.0, Sheen=0.0, Polish=0.0, Spec=0.8),
    "PL_Mask": dict(Tint=(0.08, 0.085, 0.07), Rough=0.6, RoughVar=0.2, Sheen=0.1, Polish=0.1),
    "PL_Hose": dict(Tint=(0.04, 0.04, 0.04), Rough=0.55, RoughVar=0.1, Sheen=0.2, Polish=0.0),
}


# the pilot meshes have no UVs / vertex colours (missing vertex colour = white = "baked masks on UV2" in M_CkSurface,
# which made the whole body black, 11-06): no baked AO / edges / dirt / detail normal
NO_MASKS = dict(AOAmt=0.0, EdgeGain=0.0, Dirt=0.0, Wear=0.0, Cavity=0.0, NormalAmt=0.0)
for _p in SLOT_PRM.values():
    for _k, _v in NO_MASKS.items():
        _p.setdefault(_k, _v)


def _task(fbx, opts):
    t = unreal.AssetImportTask()
    t.filename, t.destination_path, t.automated, t.replace_existing, t.save = fbx, DEST, True, True, True
    t.options = opts
    unreal.AssetToolsHelpers.get_asset_tools().import_asset_tasks([t])
    return unreal.load_asset(DEST + "/" + os.path.splitext(os.path.basename(fbx))[0])


def import_body():
    o = unreal.FbxImportUI()
    o.set_editor_property("import_mesh", True)
    o.set_editor_property("import_as_skeletal", True)
    o.set_editor_property("mesh_type_to_import", unreal.FBXImportType.FBXIT_SKELETAL_MESH)
    o.set_editor_property("import_materials", False)
    o.set_editor_property("import_textures", False)
    o.set_editor_property("import_animations", False)
    o.set_editor_property("create_physics_asset", False)
    sd = o.get_editor_property("skeletal_mesh_import_data")
    sd.set_editor_property("import_morph_targets", True)
    sd.set_editor_property("normal_import_method", unreal.FBXNormalImportMethod.FBXNIM_IMPORT_NORMALS)
    return _task(os.path.join(PILOT_SRC, "pilot_body.fbx"), o)


def import_head():
    o = unreal.FbxImportUI()
    o.set_editor_property("import_mesh", True)
    o.set_editor_property("import_materials", False)
    o.set_editor_property("import_textures", False)
    o.set_editor_property("import_as_skeletal", False)
    o.set_editor_property("mesh_type_to_import", unreal.FBXImportType.FBXIT_STATIC_MESH)
    sd = o.get_editor_property("static_mesh_import_data")
    sd.set_editor_property("combine_meshes", True)
    sd.set_editor_property("generate_lightmap_u_vs", False)
    sd.set_editor_property("auto_generate_collision", False)
    sd.set_editor_property("normal_import_method", unreal.FBXNormalImportMethod.FBXNIM_IMPORT_NORMALS)
    return _task(os.path.join(PILOT_SRC, "pilot_head.fbx"), o)


def materials():
    master = unreal.load_asset("/Game/Cockpit/Materials/M_CkSurface")
    # without these usage flags a skinned / morphing mesh renders with the default material in game (white pilot, 11-06)
    for u in ("MATUSAGE_SKELETAL_MESH", "MATUSAGE_MORPH_TARGETS"):
        try:
            MEL.set_material_usage(master, getattr(unreal.MaterialUsage, u))
        except Exception as e:
            log("material usage", u, repr(e)[:100])
    EAL.save_loaded_asset(master)
    pn = unreal.load_asset("/Game/Cockpit/Textures/T_CkFabricN")
    out = {}
    for slot, prm in SLOT_PRM.items():
        path = DEST + "/MI_" + slot
        mi = unreal.load_asset(path) if EAL.does_asset_exist(path) else unreal.AssetToolsHelpers.get_asset_tools().create_asset(
            "MI_" + slot, DEST, unreal.MaterialInstanceConstant, unreal.MaterialInstanceConstantFactoryNew())
        MEL.set_material_instance_parent(mi, master)
        MEL.clear_all_material_instance_parameters(mi)
        for k, v in prm.items():
            if isinstance(v, tuple):
                MEL.set_material_instance_vector_parameter_value(mi, k, unreal.LinearColor(v[0], v[1], v[2], 1.0))
            else:
                MEL.set_material_instance_scalar_parameter_value(mi, k, v)
        if pn and prm.get("NormalAmt"):
            MEL.set_material_instance_texture_parameter_value(mi, "NormalTex", pn)
        MEL.update_material_instance(mi)
        EAL.save_loaded_asset(mi)
        out[slot] = mi
    return out


def _slot_mats(mesh, mats, skeletal):
    if skeletal:
        sm = list(mesh.get_editor_property("materials"))
        for i, m in enumerate(sm):
            n = str(m.get_editor_property("material_slot_name"))
            key = next((k for k in mats if n.startswith(k)), None)
            if key:
                m.set_editor_property("material_interface", mats[key])
                sm[i] = m
        mesh.set_editor_property("materials", sm)
    else:
        for i, sl in enumerate(mesh.static_materials):
            n = str(sl.material_slot_name)
            key = next((k for k in mats if n.startswith(k)), None)
            if key:
                mesh.set_material(i, mats[key])
    EAL.save_loaded_asset(mesh)


def _find(world, tag):
    a = unreal.GameplayStatics.get_all_actors_with_tag(world, tag)
    return a[0] if a else None


def place(world=None):
    world = world or unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_editor_world()
    body, head = unreal.load_asset(DEST + "/pilot_body"), unreal.load_asset(DEST + "/pilot_head")
    for tag in ("PilotBody", "PilotHead"):                       # replace earlier copies
        for a in unreal.GameplayStatics.get_all_actors_with_tag(world, tag):
            eas.destroy_actor(a)
    ac, view = _find(world, "Aircraft"), _find(world, "SimView")
    if not (body and head and ac and view):
        log("missing", body, head, ac, view)
        return None
    b = eas.spawn_actor_from_class(unreal.SkeletalMeshActor, ac.get_actor_location(), ac.get_actor_rotation())
    b.set_actor_label("PilotBody")
    b.tags = [unreal.Name("AircraftPart"), unreal.Name("PilotBody")]
    sk = b.skeletal_mesh_component
    sk.set_mobility(unreal.ComponentMobility.MOVABLE)
    try:
        sk.set_skeletal_mesh_asset(body)
    except Exception:
        sk.set_editor_property("skeletal_mesh_asset", body)
    sk.set_collision_enabled(unreal.CollisionEnabled.NO_COLLISION)
    sk.set_editor_property("cast_shadow", True)
    b.attach_to_actor(ac, unreal.Name(""), unreal.AttachmentRule.SNAP_TO_TARGET, unreal.AttachmentRule.SNAP_TO_TARGET,
                      unreal.AttachmentRule.KEEP_WORLD, False)
    h = eas.spawn_actor_from_class(unreal.StaticMeshActor, view.get_actor_location(), view.get_actor_rotation())
    h.set_actor_label("PilotHead")
    h.tags = [unreal.Name("AircraftPart"), unreal.Name("PilotHead")]
    c = h.static_mesh_component
    c.set_mobility(unreal.ComponentMobility.MOVABLE)
    c.set_static_mesh(head)
    c.set_collision_enabled(unreal.CollisionEnabled.NO_COLLISION)
    c.set_editor_property("cast_shadow", True)
    h.attach_to_actor(view, unreal.Name(""), unreal.AttachmentRule.SNAP_TO_TARGET, unreal.AttachmentRule.SNAP_TO_TARGET,
                      unreal.AttachmentRule.KEEP_WORLD, False)
    mats = {k: unreal.load_asset(DEST + "/MI_" + k) for k in SLOT_PRM}
    for comp in (sk, c):                       # per-component materials by slot name (the asset slots did not stick)
        for i, n in enumerate(comp.get_material_slot_names()):
            key = next((k for k in mats if str(n).startswith(k)), None)
            if key and mats[key]:
                comp.set_material(i, mats[key])
    log("component materials", [str(m.get_name()) if m else None for m in sk.get_materials()])
    bb = b.get_actor_bounds(False)
    log("placed: body bounds centre", bb[0], "extent", bb[1], "(expect centre ~ x 445 z 45 relative to the aircraft)",
        "aircraft", ac.get_actor_location())
    return b, h


def build(save_level=True):
    mats = materials()
    body, head = import_body(), import_head()
    log("imported", body, head)
    if body:
        _slot_mats(body, mats, True)
        try:
            log("morph targets", [str(m.get_name()) for m in body.get_editor_property("morph_targets")])
        except Exception as e:
            log("morph list", repr(e)[:100])
    if head:
        _slot_mats(head, mats, False)
    r = place()
    if r and save_level:
        unreal.get_editor_subsystem(unreal.LevelEditorSubsystem).save_current_level()
        log("level saved")
    return r


if __name__ != "pilot_module":
    build()
