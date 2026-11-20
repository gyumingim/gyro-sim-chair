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

# 11-19: suit 0.022 -> 0.011 (half; user: the suit looks too bright in VR - sunlit albedo above ~0.03 reads near white at the
# cockpit exposure), G-suit 0.016 -> 0.0085
# material class (manny_pose.classify) -> M_CkSurface parameters (linear colours). 11-16: suit 0.085 rendered almost white in
# the look-down view (chest sRGB ~190 at exp_min 1.0) -> about 1/4
NO_MASKS = dict(AOAmt=0.0, EdgeGain=0.0, Dirt=0.0, Wear=0.0, Cavity=0.0, NormalAmt=0.0)
SLOTS = [
    ("PM_Suit", dict(Tint=(0.011, 0.013, 0.0078), Rough=0.85, RoughVar=0.1, Sheen=0.0, Polish=0.0, NormalAmt=0.8, NormalTile=60.0)),      # olive-grey flight suit
    ("PM_GSuit", dict(Tint=(0.0085, 0.010, 0.0062), Rough=0.85, RoughVar=0.1, Sheen=0.0, Polish=0.0, NormalAmt=0.8, NormalTile=60.0)),    # darker G-suit trousers
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


SMM = DEST + "/SKM_PilotMannyM"


def import_fbx(fbx=None):
    """11-19: the pilot with control morph targets: MANNY_DIR/manny_pilot.fbx (Scripts/pilot/manny_fbx.py) ->
    SKM_PilotMannyM (+ its own one-bone skeleton), slots = the MI_PM_* instances. SKM_PilotManny (static) stays."""
    fbx = fbx or os.path.join(MANNY_DIR, "manny_pilot.fbx")
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
    t = unreal.AssetImportTask()
    t.filename, t.destination_path, t.destination_name, t.automated, t.replace_existing, t.save = fbx, DEST, "SKM_PilotMannyM", True, True, True
    t.options = o
    unreal.AssetToolsHelpers.get_asset_tools().import_asset_tasks([t])
    sk = unreal.load_asset(SMM)
    if sk is None:
        log("import_fbx failed", fbx)
        return None
    master = unreal.load_asset("/Game/Cockpit/Materials/M_CkSurface")
    for u in ("MATUSAGE_SKELETAL_MESH", "MATUSAGE_MORPH_TARGETS"):
        try:
            MEL.set_material_usage(master, getattr(unreal.MaterialUsage, u))
        except Exception as e:
            log("material usage", u, repr(e)[:100])
    mats = dict(materials())
    sm = list(sk.get_editor_property("materials"))
    for i, m in enumerate(sm):
        n = str(m.get_editor_property("material_slot_name"))
        key = next((k for k in mats if n.startswith(k)), None)
        if key:
            m.set_editor_property("material_interface", mats[key])
            sm[i] = m
    sk.set_editor_property("materials", sm)
    EAL.save_loaded_asset(sk)
    info = dict(slots=[str(m.material_slot_name) for m in sk.get_editor_property("materials")], bounds=str(sk.get_bounds()))
    try:
        info["morphs"] = [str(m.get_name()) for m in sk.get_editor_property("morph_targets")]
    except Exception as e:
        info["morphs"] = repr(e)[:120]
    log("import_fbx", info)
    return info


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


# =====================================================================================================================
# 11-20 round 6: cloth / leather detail. materials6() = textures (Scripts/pilot/suit_textures.py -> MANNY_DIR/tex6) +
# master M_PilotCloth + instances MI6_PM_* (the MI_PM_* instances of M_CkSurface stay: A/B in one Play session).
# M_PilotCloth, 3 texture samples, default lit, opaque, UV0 (the pilot FBX has ONE UV channel, metres: u = round the body
# segment x 0.08 m, v = along it). Packed linear textures: RG normal xy, B / A data, all neutral at 0.5.
#   Detail  (T_PM6_Weave | T_PM6_Leather) x DetailTile : normal x DetailAmt, B -> roughness +- RoughVar, A -> cavity (DetailAO)
#   Wrinkle (T_PM6_Wrinkle) x WrinkleTile              : normal x WrinkleAmt, B -> fold cavity on base colour (WrinkleAO)
#   Macro   (T_PM6_Wrinkle) x MacroTile + offset       : normal x MacroAmt (broad folds), A -> albedo mottling (TintVar)
#   seam (Custom node, no texture): raised seam + two stitch rows along v at u = (SeamOffset + k) x half turn; SeamAmt 0 = off
#   BaseColor = Tint x cavities x mottling x (1 + Fuzz x Fresnel^3) x stitches   (cavities / mottling keep the mean)
#   Roughness = clamp((Rough + (B - 0.5) x RoughVar) x (1 - Sheen x Fresnel), 0.15, 1)      Specular = Spec x detail cavity
TEX6 = DEST + "/Tex6"
MASTER6 = DEST + "/M_PilotCloth"
TEX6_DIR = os.path.join(MANNY_DIR, "tex6")
# 11-20 first Unreal look (capture r6a): weave at tile 12.5 / amt 1 read as a gingham check and the Fuzz 0.8 paled the chest;
# leather at tile 14 / amt 1 + wrinkle 0.5 read as reptile skin. Finer and weaker:
CLOTH = dict(Rough=0.85, RoughVar=0.25, Spec=0.35, Sheen=0.0, Fuzz=0.3, DetailTile=22.0, DetailAmt=0.6, DetailAO=0.3, WrinkleTile=5.0,
             WrinkleAmt=0.8, WrinkleAO=0.4, MacroTile=1.7, MacroAmt=0.5, TintVar=0.2, SeamAmt=1.0, SeamOffset=0.5)
LEATHER = dict(Detail="T_PM6_Leather", RoughVar=0.25, Spec=0.5, Sheen=0.25, Fuzz=0.2, DetailTile=26.0, DetailAmt=0.5, DetailAO=0.3,
               WrinkleTile=9.0, WrinkleAmt=0.3, WrinkleAO=0.25, MacroTile=3.1, MacroAmt=0.2, TintVar=0.2, SeamAmt=0.0)
SLOTS6 = [      # tints = SLOTS (11-19 values: not brighter). name -> M_PilotCloth parameters ("Detail" = texture name)
    ("PM_Suit", dict(CLOTH, Tint=(0.011, 0.013, 0.0078))),
    ("PM_GSuit", dict(CLOTH, Tint=(0.0085, 0.010, 0.0062), DetailTile=24.0, WrinkleTile=6.5, WrinkleAmt=0.5, WrinkleAO=0.3, MacroAmt=0.3)),   # tight garment
    ("PM_Glove", dict(LEATHER, Tint=(0.006, 0.006, 0.006), Rough=0.7)),
    ("PM_Boot", dict(LEATHER, Tint=(0.006, 0.006, 0.006), Rough=0.55, DetailTile=20.0, WrinkleTile=7.0, WrinkleAmt=0.3)),
    ("PM_Harness", dict(CLOTH, Tint=(0.03, 0.03, 0.028), Rough=0.7, DetailTile=25.0, WrinkleAmt=0.2, WrinkleAO=0.2, MacroAmt=0.1, SeamAmt=0.0)),
]
SEAM_HLSL = """
// UV = body UVs in metres (u round the segment, v along). Returns (normal x offset, base colour factor, 0).
float hc = 0.2513274;                                   // half the unwrap: pi x 0.08 m (manny_fbx.py RUV)
float sd = (frac(UV.x / hc - Off + 0.5) - 0.5) * hc;    // signed distance to the nearest seam line
float ad = abs(sd);
float w = 0.0035;
float bump = exp(-(sd * sd) / (w * w));                 // raised seam, about 7 mm wide, 1.1 mm high
float fu = fwidth(UV.x);
float fv = fwidth(UV.y);
float fadeN = saturate(2.0 - fu / 0.003);
float nx = 2.0 * sd * bump * 0.0011 / (w * w) * fadeN;
float t = (ad - 0.0062) / 0.0008;                       // stitch rows 6.2 mm either side
float row = exp(-t * t);
float f = frac(UV.y / 0.0036);                          // 3.6 mm stitch pitch
float dash = smoothstep(0.0, 0.15, f) * (1.0 - smoothstep(0.62, 0.77, f));
float fadeS = saturate(1.5 - max(fu / 0.0012, fv / 0.0018));
float e = (ad - 0.0040) / 0.0010;                       // dark line where the seam folds under
float alb = 1.0 + Amt * (fadeS * row * (0.45 * dash - 0.30 * (1.0 - dash)) - 0.22 * fadeN * exp(-e * e));
return float3(nx * Amt, alb, 0.0);
"""


def _try(what, fn):
    """optional step: log and carry on (this code is run blind in an offscreen editor)"""
    try:
        return fn()
    except Exception as e:
        log("materials6 optional step failed:", what, repr(e)[:200])
        return None


def import_tex6(tex_dir=None):
    """MANNY_DIR/tex6/T_PM6_*.png -> /Game/ThirdParty/Mannequins/Tex6 as linear BC7 (packed data, NOT normal maps)"""
    tex_dir = tex_dir or TEX6_DIR
    out = {}
    for n in ("T_PM6_Weave", "T_PM6_Wrinkle", "T_PM6_Leather"):
        f = os.path.join(tex_dir, n + ".png")
        if not os.path.exists(f):
            raise RuntimeError("missing %s - run: python Scripts/pilot/suit_textures.py" % f)
        t = unreal.AssetImportTask()
        t.filename, t.destination_path, t.destination_name, t.automated, t.replace_existing, t.save = f, TEX6, n, True, True, True
        unreal.AssetToolsHelpers.get_asset_tools().import_asset_tasks([t])
        tx = unreal.load_asset(TEX6 + "/" + n)
        if tx is None:
            raise RuntimeError("texture import failed: " + f)
        tx.set_editor_property("srgb", False)
        if _try(n + " TC_BC7", lambda: tx.set_editor_property("compression_settings", unreal.TextureCompressionSettings.TC_BC7) or True) is None:
            _try(n + " TC_VECTOR_DISPLACEMENTMAP",
                 lambda: tx.set_editor_property("compression_settings", unreal.TextureCompressionSettings.TC_VECTOR_DISPLACEMENTMAP))
        _try(n + " flip_green_channel", lambda: tx.set_editor_property("flip_green_channel", False))
        _try(n + " address", lambda: (tx.set_editor_property("address_x", unreal.TextureAddress.TA_WRAP),
                                      tx.set_editor_property("address_y", unreal.TextureAddress.TA_WRAP)))
        EAL.save_loaded_asset(tx)
        out[n] = tx
        log("tex6", n, "srgb", tx.get_editor_property("srgb"), "compression", tx.get_editor_property("compression_settings"))
    return out


def _sampler6(tex):
    """sampler type that matches the texture as it really is now (a mismatch is a material compile error)"""
    ST, TC = unreal.MaterialSamplerType, unreal.TextureCompressionSettings
    cs, srgb = tex.get_editor_property("compression_settings"), tex.get_editor_property("srgb")
    if cs == TC.TC_NORMALMAP:
        return ST.SAMPLERTYPE_NORMAL
    if cs == TC.TC_MASKS:
        return ST.SAMPLERTYPE_MASKS
    if cs in (TC.TC_GRAYSCALE, TC.TC_ALPHA):
        return ST.SAMPLERTYPE_GRAYSCALE if srgb else ST.SAMPLERTYPE_LINEAR_GRAYSCALE
    return ST.SAMPLERTYPE_COLOR if srgb else ST.SAMPLERTYPE_LINEAR_COLOR


def master6(tx, seams=True):
    """M_PilotCloth (see the block comment above). Rebuilt in place when it exists (instances keep their parent)."""
    ME = unreal
    if EAL.does_asset_exist(MASTER6):
        m = unreal.load_asset(MASTER6)
        MEL.delete_all_material_expressions(m)
    else:
        m = unreal.AssetToolsHelpers.get_asset_tools().create_asset("M_PilotCloth", DEST, unreal.Material, unreal.MaterialFactoryNew())

    def X(cls, x, y, **kw):
        e = MEL.create_material_expression(m, cls, x, y)
        for k, v in kw.items():
            e.set_editor_property(k, v)
        return e

    def con(a, b, pin, out=""):
        if not MEL.connect_material_expressions(a, out, b, pin):
            log("materials6 CONNECT FAILED", a.get_name(), repr(out), "->", b.get_name(), repr(pin))
        return b

    def C(v, x, y):
        return X(ME.MaterialExpressionConstant, x, y, r=v)

    def SP(n, v, x, y):
        return X(ME.MaterialExpressionScalarParameter, x, y, parameter_name=n, default_value=v)

    def OP(cls, a, b, x, y, pa="", pb=""):
        e = X(cls, x, y)
        con(a, e, "A", pa)
        con(b, e, "B", pb)
        return e

    MUL = lambda a, b, x, y, pa="", pb="": OP(ME.MaterialExpressionMultiply, a, b, x, y, pa, pb)
    ADD = lambda a, b, x, y, pa="", pb="": OP(ME.MaterialExpressionAdd, a, b, x, y, pa, pb)
    SUB = lambda a, b, x, y, pa="", pb="": OP(ME.MaterialExpressionSubtract, a, b, x, y, pa, pb)

    def MASK(a, ch, x, y, out=""):
        e = X(ME.MaterialExpressionComponentMask, x, y, r="r" in ch, g="g" in ch, b="b" in ch, a="a" in ch)
        return con(a, e, "", out)

    def TS(name, tex, uv, x, y):
        e = X(ME.MaterialExpressionTextureSampleParameter2D, x, y, parameter_name=name)
        e.set_editor_property("texture", tex)
        e.set_editor_property("sampler_type", _sampler6(tex))
        return con(uv, e, "UVs")

    def signed(sample, pin, amt, x, y):
        """(channel - 0.5) x 2 x amt"""
        return MUL(MUL(SUB(sample, half, x, y, pin), two, x + 130, y), amt, x + 260, y)

    half, two, one = C(0.5, -2600, -700), C(2.0, -2600, -640), C(1.0, -2600, -580)
    uv = X(ME.MaterialExpressionTextureCoordinate, -3000, 0)          # UV0
    weave, wrk = tx["T_PM6_Weave"], tx["T_PM6_Wrinkle"]
    D = TS("Detail", weave, MUL(uv, SP("DetailTile", 12.5, -3000, 120), -2800, 60), -2600, 0)
    W = TS("Wrinkle", wrk, MUL(uv, SP("WrinkleTile", 5.0, -3000, 420), -2800, 360), -2600, 300)
    off = X(ME.MaterialExpressionConstant2Vector, -2950, 780, r=0.37, g=0.61)
    M = TS("Macro", wrk, ADD(MUL(uv, SP("MacroTile", 1.7, -3000, 720), -2800, 660), off, -2700, 700), -2600, 600)
    # ---- normal: sum of the three tangent xy (+ seam), z = 1, normalised
    nD = signed(MASK(D, "rg", -2350, 0), "", SP("DetailAmt", 1.0, -2350, 80), -2200, 0)
    nW = signed(MASK(W, "rg", -2350, 300), "", SP("WrinkleAmt", 1.0, -2350, 380), -2200, 300)
    nM = signed(MASK(M, "rg", -2350, 600), "", SP("MacroAmt", 0.5, -2350, 680), -2200, 600)
    nxy = ADD(ADD(nD, nW, -1750, 150), nM, -1600, 300)
    seam = None
    if seams:
        def mk_seam():
            cu = X(ME.MaterialExpressionCustom, -2600, 1000)
            cu.set_editor_property("code", SEAM_HLSL)
            cu.set_editor_property("output_type", unreal.CustomMaterialOutputType.CMOT_FLOAT3)
            ins = []
            for n in ("UV", "Off", "Amt"):
                ci = unreal.CustomInput()
                ci.set_editor_property("input_name", n)
                ins.append(ci)
            cu.set_editor_property("inputs", ins)
            con(uv, cu, "UV")
            con(SP("SeamOffset", 0.5, -2900, 1060), cu, "Off")
            con(SP("SeamAmt", 1.0, -2900, 1140), cu, "Amt")
            return cu
        seam = _try("seam custom node (the material is built without seams)", mk_seam)
    if seam is not None:
        sx = X(ME.MaterialExpressionAppendVector, -2100, 1000)
        con(MASK(seam, "r", -2300, 1000), sx, "A")
        con(C(0.0, -2300, 1080), sx, "B")
        nxy = ADD(nxy, sx, -1450, 400)
    ap = X(ME.MaterialExpressionAppendVector, -1300, 400)
    con(nxy, ap, "A")
    con(one, ap, "B")
    nrm = con(ap, X(ME.MaterialExpressionNormalize, -1150, 400), "")
    MEL.connect_material_property(nrm, "", unreal.MaterialProperty.MP_NORMAL)
    # ---- base colour
    tint = X(ME.MaterialExpressionVectorParameter, -2000, -500, parameter_name="Tint", default_value=unreal.LinearColor(0.011, 0.013, 0.0078, 1.0))
    cavD = ADD(one, signed(D, "A", SP("DetailAO", 0.5, -2350, -220), -2200, -300), -1750, -300)       # 1 + (A x 2 - 1) x DetailAO
    cavW = ADD(one, signed(W, "B", SP("WrinkleAO", 0.5, -2350, -60), -2200, -140), -1750, -140)
    mot = ADD(one, signed(M, "A", SP("TintVar", 0.3, -2350, 860), -2200, 800), -1750, 800)
    fres = X(ME.MaterialExpressionFresnel, -1900, 1300)
    _try("fresnel exponent", lambda: fres.set_editor_property("exponent", 3.0))
    _try("fresnel base_reflect_fraction", lambda: fres.set_editor_property("base_reflect_fraction", 0.0))
    fuzz = ADD(one, MUL(fres, SP("Fuzz", 0.8, -1900, 1420), -1700, 1350), -1550, 1350)
    b = MUL(MUL(MUL(MASK(tint, "rgb", -1800, -500), cavD, -1500, -450), cavW, -1350, -400), MUL(mot, fuzz, -1400, 900), -1150, -350)
    if seam is not None:
        b = MUL(b, MASK(seam, "g", -2300, 1160), -1000, -300)
    MEL.connect_material_property(b, "", unreal.MaterialProperty.MP_BASE_COLOR)
    # ---- roughness / specular / metallic
    r1 = ADD(SP("Rough", 0.85, -1900, 1600), MUL(SUB(D, half, -1900, 1700, "B"), SP("RoughVar", 0.25, -1900, 1800), -1700, 1720), -1500, 1650)
    r2 = MUL(r1, SUB(one, MUL(fres, SP("Sheen", 0.0, -1900, 1500), -1700, 1500), -1550, 1500), -1350, 1600)
    rc = X(ME.MaterialExpressionClamp, -1200, 1600)
    _try("clamp defaults", lambda: (rc.set_editor_property("min_default", 0.15), rc.set_editor_property("max_default", 1.0)))
    con(r2, rc, "")
    MEL.connect_material_property(rc, "", unreal.MaterialProperty.MP_ROUGHNESS)
    sat = con(MUL(SP("Spec", 0.35, -1900, 2000), cavD, -1700, 2000), X(ME.MaterialExpressionSaturate, -1500, 2000), "")
    MEL.connect_material_property(sat, "", unreal.MaterialProperty.MP_SPECULAR)
    MEL.connect_material_property(SP("Metal", 0.0, -1900, 2150), "", unreal.MaterialProperty.MP_METALLIC)
    for u in ("MATUSAGE_SKELETAL_MESH", "MATUSAGE_MORPH_TARGETS"):
        _try("usage " + u, lambda u=u: MEL.set_material_usage(m, getattr(unreal.MaterialUsage, u)))
    log("M_PilotCloth graph done, recompile ...")
    MEL.recompile_material(m)
    log("M_PilotCloth recompiled, save ...")
    EAL.save_loaded_asset(m)
    log("M_PilotCloth saved")
    info = dict(path=MASTER6, seams=seam is not None, expressions=_try("count", lambda: MEL.get_num_material_expressions(m)))
    # (11-20: the first run hung for 26 min right after the usage flags; statistics only on request)
    st = _try("statistics", lambda: MEL.get_statistics(m)) if os.environ.get("M7_STATS", "0") == "1" else None
    if st is not None:      # 0 pixel instructions / 0 samplers = the shader did not compile (look for M_PilotCloth errors in editor.log)
        info.update(pixel_instructions=st.num_pixel_shader_instructions, samplers=st.num_samplers,
                    texture_samples=_try("num_pixel_texture_samples", lambda: st.num_pixel_texture_samples))
    log("M_PilotCloth", info)
    return m, info


def materials6(seams=True, slots=None, tex_dir=None):
    """textures + M_PilotCloth + MI6_PM_* instances; safe to re-run. -> dict (JSON friendly) of what was made.
    seams=False builds the master without the Custom (HLSL) seam node, in case that node is what fails to compile."""
    tx = import_tex6(tex_dir)
    m, info = master6(tx, seams)
    made = {}
    for name, prm in (slots or SLOTS6):
        path = DEST + "/MI6_" + name
        mi = unreal.load_asset(path) if EAL.does_asset_exist(path) else unreal.AssetToolsHelpers.get_asset_tools().create_asset(
            "MI6_" + name, DEST, unreal.MaterialInstanceConstant, unreal.MaterialInstanceConstantFactoryNew())
        MEL.set_material_instance_parent(mi, m)
        MEL.clear_all_material_instance_parameters(mi)
        bad = []
        for k, v in prm.items():
            if k in ("SeamAmt", "SeamOffset") and not info["seams"]:
                continue
            if k == "Detail":
                ok = MEL.set_material_instance_texture_parameter_value(mi, k, tx[v])
            elif isinstance(v, tuple):
                ok = MEL.set_material_instance_vector_parameter_value(mi, k, unreal.LinearColor(v[0], v[1], v[2], 1.0))
            else:
                ok = MEL.set_material_instance_scalar_parameter_value(mi, k, float(v))
            if not ok:
                bad.append(k)
        MEL.update_material_instance(mi)
        EAL.save_loaded_asset(mi)
        made[path] = dict(prm, parameters_not_set=bad)
    scal = _try("scalar parameter names", lambda: sorted(str(n) for n in MEL.get_scalar_parameter_names(m)))
    out = dict(master=info, textures={n: t.get_path_name() for n, t in tx.items()}, instances=made, master_scalar_parameters=scal)
    log("materials6", json.dumps(out, default=str)[:1500])
    return out
