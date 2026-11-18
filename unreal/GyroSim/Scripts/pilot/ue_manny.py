"""Manny pilot body (11-15): Unreal side of Scripts/pilot/manny_pose.py. Run in the editor (GUI or -RenderOffscreen),
not in a -nullrhi commandlet:

    import ue_manny; ue_manny.install()   # once: copy SKM_Manny_Simple + skeleton + materials from the engine templates
                                         #       to /Game/ThirdParty/Mannequins (gitignored - Epic content, never commit)
    ue_manny.dump()                      # MANNY_DIR/manny_mesh.json: reference vertices, triangles, skin weights, bones
    python Scripts/pilot/manny_pose.py --mesh MANNY_DIR/manny_mesh.json --out MANNY_DIR/manny_posed.json   (outside UE)
    ue_manny.build(); (a few seconds later) ue_manny.finish()   # SKM_PilotManny + its 5 material instances

MANNY_DIR = $GYROSIM_MANNY_DIR or C:/GyroSimParts/thirdparty/manny (derived from Epic content: outside git).
Content/Python/pilot_manny.py puts SKM_PilotManny on the PilotBody actor at Play (GYROSIM_PILOT=old keeps the old pilot).
SKM_PilotManny is a skeletal mesh only so it can replace the PilotBody actor's mesh (Python cannot spawn actors into a
Play world): Manny's skeleton and weights, but the bind-pose vertices ARE the posed pilot (never animated).
Materials: instances of the cockpit master M_CkSurface (flat matte, no baked masks - like Scripts/pilot/ue_pilot.py),
no mannequin textures / logo.
"""
import glob
import json
import os
import shutil

import unreal

MANNY_DIR = os.environ.get("GYROSIM_MANNY_DIR", "C:/GyroSimParts/thirdparty/manny")
DEST = "/Game/ThirdParty/Mannequins"
SKM = DEST + "/Meshes/SKM_Manny_Simple"
SM = DEST + "/SKM_PilotManny"
TEMPLATE = "C:/Program Files/Epic Games/UE_5.8/Templates/TemplateResources/High/Characters/Content/Mannequins"
EAL, MEL = unreal.EditorAssetLibrary, unreal.MaterialEditingLibrary
GA, GQ, GB, GL = unreal.GeometryScript_AssetUtils, unreal.GeometryScript_MeshQueries, unreal.GeometryScript_BoneWeights, unreal.GeometryScript_List
log = lambda *a: unreal.log("[ue_manny] " + " ".join(str(x) for x in a))

# material class (manny_pose.classify) -> M_CkSurface parameters (linear colours). 11-16: suit 0.085 rendered almost white in
# the look-down view (chest sRGB ~190 at exp_min 1.0) -> about 1/4
NO_MASKS = dict(AOAmt=0.0, EdgeGain=0.0, Dirt=0.0, Wear=0.0, Cavity=0.0, NormalAmt=0.0)
SLOTS = [
    ("PM_Suit", dict(Tint=(0.015, 0.0175, 0.0105), Rough=0.85, RoughVar=0.1, Sheen=0.0, Polish=0.0, NormalAmt=0.8, NormalTile=60.0)),      # olive-grey flight suit
    ("PM_GSuit", dict(Tint=(0.011, 0.013, 0.008), Rough=0.85, RoughVar=0.1, Sheen=0.0, Polish=0.0, NormalAmt=0.8, NormalTile=60.0)),    # darker G-suit trousers
    ("PM_Glove", dict(Tint=(0.006, 0.006, 0.006), Rough=0.75, RoughVar=0.1, Sheen=0.0, Polish=0.0)),    # black matte gloves
    ("PM_Boot", dict(Tint=(0.006, 0.006, 0.006), Rough=0.6, RoughVar=0.1, Sheen=0.0, Polish=0.0)),      # black boots
    ("PM_Harness", dict(Tint=(0.03, 0.03, 0.028), Rough=0.7, RoughVar=0.1, Sheen=0.0, Polish=0.0)),     # (unused for now)
]


def install():
    """copy the needed template files into Content/Characters/Mannequins (their package path), then rename the folder
    to /Game/ThirdParty/Mannequins inside the editor (references fixed by the rename). Read-only on Program Files.
    The emptied staging folder (redirectors) is left for the file system: delete Content/Characters after the editor quits."""
    if EAL.does_asset_exist(SKM):
        log("installed already")
        return True
    content = unreal.Paths.convert_relative_path_to_full(unreal.Paths.project_content_dir())
    stage = os.path.join(content, "Characters", "Mannequins")
    pats = ["Meshes/SKM_Manny_Simple.uasset", "Meshes/SK_Mannequin.uasset", "Rigs/PA_Mannequin.uasset", "Materials/M_Mannequin.uasset",
            "Materials/Manny/*.uasset", "Textures/Manny/*.uasset", "Textures/Shared/*.uasset"]
    for p in pats:
        for f in glob.glob(os.path.join(TEMPLATE, p)):
            d = os.path.join(stage, os.path.relpath(f, TEMPLATE))
            os.makedirs(os.path.dirname(d), exist_ok=True)
            shutil.copy2(f, d)
    unreal.AssetRegistryHelpers.get_asset_registry().scan_paths_synchronous(["/Game/Characters"], True)
    ok = EAL.rename_directory("/Game/Characters/Mannequins", DEST)
    log("install rename", ok)
    return ok


def _tr(t):
    p = t.translation
    return [round(p.x, 4), round(p.y, 4), round(p.z, 4)]


def dump(out_dir=MANNY_DIR):
    os.makedirs(out_dir, exist_ok=True)
    sk = unreal.load_asset(SKM)
    dm = unreal.DynamicMesh()
    GA.copy_mesh_from_skeletal_mesh(sk, dm, unreal.GeometryScriptCopyMeshFromAssetOptions(), unreal.GeometryScriptMeshReadLOD())
    P = GL.convert_vector_list_to_array(GQ.get_all_vertex_positions(dm, False)[1])
    T = GL.convert_triangle_list_to_array(GQ.get_all_triangle_indices(dm, False)[1])
    bones = [dict(i=b.index, name=str(b.name), parent=b.parent_index) for b in GB.get_all_bones_info(dm)[1]]
    prof = unreal.GeometryScriptBoneWeightProfile()
    W = [[[b.bone_index, round(b.weight, 4)] for b in GB.get_vertex_bone_weights(dm, v, prof)[1]] for v in range(len(P))]
    # reference bone positions (component space) from a temporary actor
    eas = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
    a = eas.spawn_actor_from_class(unreal.SkeletalMeshActor, unreal.Vector(0, 0, 0), transient=True)
    c = a.skeletal_mesh_component
    c.set_skeletal_mesh_asset(sk)
    ref = {}
    for i in range(c.get_num_bones()):
        n = c.get_bone_name(i)
        ref[str(n)] = _tr(c.get_socket_transform(n, unreal.RelativeTransformSpace.RTS_COMPONENT))
    eas.destroy_actor(a)
    data = dict(P=[[round(p.x, 4), round(p.y, 4), round(p.z, 4)] for p in P], T=[[t.x, t.y, t.z] for t in T], bones=bones, W=W, ref_bones=ref,
                source=SKM)
    fn = os.path.join(out_dir, "manny_mesh.json")
    json.dump(data, open(fn, "w"))
    log("dump", fn, len(P), "vertices", len(T), "triangles")
    return fn


def materials():
    master = unreal.load_asset("/Game/Cockpit/Materials/M_CkSurface")
    out = []
    for name, prm in SLOTS:
        path = DEST + "/MI_" + name
        mi = unreal.load_asset(path) if EAL.does_asset_exist(path) else unreal.AssetToolsHelpers.get_asset_tools().create_asset(
            "MI_" + name, DEST, unreal.MaterialInstanceConstant, unreal.MaterialInstanceConstantFactoryNew())
        MEL.set_material_instance_parent(mi, master)
        MEL.clear_all_material_instance_parameters(mi)
        for k, v in list(NO_MASKS.items()) + list(prm.items()):      # slot values win (11-18: fabric normal on the suit)
            if isinstance(v, tuple):
                MEL.set_material_instance_vector_parameter_value(mi, k, unreal.LinearColor(v[0], v[1], v[2], 1.0))
            else:
                MEL.set_material_instance_scalar_parameter_value(mi, k, v)
        MEL.update_material_instance(mi)
        EAL.save_loaded_asset(mi)
        out.append((name, mi))
    return out


def finish():
    """second step of build(), run a few seconds later (ticks in between): setting material slots right after a mesh
    build asserted (StaticMeshBuild.cpp AsyncTask == nullptr, UE 5.8, 11-16)."""
    sk = unreal.load_asset(SM)
    mats = materials()
    sk.set_editor_property("materials", [unreal.SkeletalMaterial(material_interface=mi, material_slot_name=unreal.Name(n)) for n, mi in mats])
    EAL.save_loaded_asset(sk)
    info = dict(bounds=str(sk.get_bounds()), slots=[str(m.material_slot_name) for m in sk.get_editor_property("materials")])
    log("finish", info)
    return info


def build(posed=None):
    """mesh only (call finish() a few seconds later for the materials)"""
    posed = posed or os.path.join(MANNY_DIR, "manny_posed.json")
    D = json.load(open(posed, encoding="utf-8"))
    sk = unreal.load_asset(SKM)
    dm = unreal.DynamicMesh()
    GA.copy_mesh_from_skeletal_mesh(sk, dm, unreal.GeometryScriptCopyMeshFromAssetOptions(), unreal.GeometryScriptMeshReadLOD())
    n0 = GQ.get_vertex_count(dm)
    nt0 = GQ.get_num_triangle_i_ds(dm)
    P, cls, drop = D["P"], D["cls"], D["drop"]
    GEd = unreal.GeometryScript_MeshEdits
    GEd.set_all_mesh_vertex_positions(dm, GL.convert_array_to_vector_list([unreal.Vector(*p) for p in P[:n0]]))
    by_cls = {}
    for ti in range(nt0):
        by_cls.setdefault(cls[ti], []).append(ti)
    GEd.delete_triangles_from_mesh(dm, GL.convert_array_to_index_list(drop))
    # extra vertices / triangles of the neck cap (manny_pose.cap_holes: appended after the originals)
    vmap = {}
    for v in range(n0, len(P)):
        vmap[v] = GEd.add_vertex_to_mesh(dm, unreal.Vector(*P[v]))[1]
    capT = D.get("capT", [])
    cap_by_cls, bad = {}, 0
    for t in capT:
        tt = [vmap.get(x, x) for x in t["v"]]
        tid = GEd.add_triangle_to_mesh(dm, unreal.IntVector(tt[0], tt[1], tt[2]))[1]
        if tid < 0:                          # non-manifold / duplicate: skip
            bad += 1
            continue
        cap_by_cls.setdefault(t["cls"], []).append(tid)    # new triangles may reuse freed (dropped) IDs: kept apart
    dropset = set(drop)
    GM = unreal.GeometryScript_Materials
    for k in set(by_cls) | set(cap_by_cls):
        tids = [t for t in by_cls.get(k, []) if t not in dropset] + cap_by_cls.get(k, [])
        GM.set_material_id_on_triangles(dm, GL.convert_array_to_index_list(tids), int(k))
    # one smooth per-vertex normal set over everything (the cap triangles have no elements in the copied overlay)
    unreal.GeometryScript_Normals.set_per_vertex_normals(dm)
    # the cap vertex has no skin weights: rigid on spine_05
    bi = {str(b.name): b.index for b in GB.get_all_bones_info(dm)[1]}
    w = unreal.GeometryScriptBoneWeight()
    w.set_editor_property("bone_index", bi.get("spine_05", 0))
    w.set_editor_property("weight", 1.0)
    for v in vmap.values():
        GB.set_vertex_bone_weights(dm, v, [w], unreal.GeometryScriptBoneWeightProfile())
    skel = sk.get_editor_property("skeleton")
    if EAL.does_asset_exist(SM):                 # (rebuild: delete the asset first if the slots change)
        out = unreal.load_asset(SM)
        wo = unreal.GeometryScriptCopyMeshToAssetOptions()
        for k, v in (("enable_recompute_normals", False), ("enable_recompute_tangents", True), ("replace_materials", False)):
            try:
                wo.set_editor_property(k, v)
            except Exception:
                pass
        GA.copy_mesh_to_skeletal_mesh(dm, out, wo, unreal.GeometryScriptMeshWriteLOD())
    else:
        opts = unreal.GeometryScriptCreateNewSkeletalMeshAssetOptions()
        # one section per material ID only when the slots are given here (an empty map gave 1 section, 11-16)
        opts.set_editor_property("materials", {unreal.Name(n): mi for n, mi in materials()})
        for k, v in (("enable_recompute_normals", False), ("enable_recompute_tangents", True)):
            try:
                opts.set_editor_property(k, v)
            except Exception:
                pass
        out = unreal.GeometryScript_NewAssetUtils.create_new_skeletal_mesh_asset_from_mesh(dm, skel, SM, opts)[0]
    info = dict(vertices=GQ.get_vertex_count(dm), triangles=GQ.get_num_triangle_i_ds(dm), dropped=len(drop), cap=len(capT), cap_failed=bad)
    log("build", info)
    return info
