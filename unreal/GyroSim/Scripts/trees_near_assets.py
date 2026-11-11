r"""Near real-leaf trees (Content/Python/trees_near.py): imports the reduced tree meshes and builds the material.

  /Game/ThirdParty/Trees/Near/SM_TreeNear_*   from C:/GyroSimTiles/assets/trees_near/*.glb (sim/trees_near_build.py --meshes;
                                              derived from Poly Haven CC0 + Fab Megascans models -> git-ignored folder)
                                              Nanite on (Preserve Area: thin foliage keeps its coverage when simplified)
  /Game/Trees/M_GyroTreeNear                  own material (Scripts/trees_near.hlsl), two-sided foliage, no textures

Headless, editor CLOSED or one that does not have the assets open, and holding C:\GyroSimTiles\ue_offscreen.lock:
  "C:\Program Files\Epic Games\UE_5.8\Engine\Binaries\Win64\UnrealEditor-Cmd.exe" <path>\GyroSim.uproject ^
      -run=pythonscript -script=<path>\Scripts\trees_near_assets.py -unattended -nosplash -nullrhi
GYROSIM_TREES_NEAR_ASSETS = "meshes,material" (default both) or one of them; GYROSIM_TREES_NEAR_ONLY = mesh names.
"""
import json, os, time
import unreal

SRC = os.environ.get("GYROSIM_TREES_NEAR_MESHES", r"C:/GyroSimTiles/assets/trees_near").replace("\\", "/")
MPATH = "/Game/ThirdParty/Trees/Near"
MAT_PATH, MAT_NAME = "/Game/Trees", "M_GyroTreeNear"
HLSL = os.path.join(os.path.dirname(os.path.abspath(__file__)), "trees_near.hlsl")
PARAMS = dict(Gain=3.6, VarAmt=1.0, OccAmt=0.45, SssAmt=0.6, BarkGain=1.0)     # 11-11 shot 1: 2.2 / 0.8 read grey-black
EAL = unreal.EditorAssetLibrary
MEL = unreal.MaterialEditingLibrary
log = lambda *a: unreal.log("[trees_near_assets] " + " ".join(str(x) for x in a))


def build_material():
    full = MAT_PATH + "/" + MAT_NAME
    if EAL.does_asset_exist(full):
        m = unreal.load_asset(full)
        MEL.delete_all_material_expressions(m)
    else:
        m = unreal.AssetToolsHelpers.get_asset_tools().create_asset(MAT_NAME, MAT_PATH, unreal.Material, unreal.MaterialFactoryNew())
    m.set_editor_property("two_sided", True)
    m.set_editor_property("shading_model", unreal.MaterialShadingModel.MSM_TWO_SIDED_FOLIAGE)
    for flag, v in (("used_with_instanced_static_meshes", True), ("used_with_nanite", True), ("used_with_static_lighting", False)):
        try:
            m.set_editor_property(flag, v)
        except Exception as e:
            log("flag", flag, repr(e))
    X = lambda cls, x, y: MEL.create_material_expression(m, cls, x, y)
    vc = X(unreal.MaterialExpressionVertexColor, -1300, 0)
    tint = X(unreal.MaterialExpressionVectorParameter, -1300, 150)       # species tint (trees_near: one instance per kind)
    tint.set_editor_property("parameter_name", "Tint")
    tint.set_editor_property("default_value", unreal.LinearColor(0.045, 0.075, 0.040, 1.0))
    pir = X(unreal.MaterialExpressionPerInstanceRandom, -1300, 300)
    srcs = [("VC", vc, ""), ("T", tint, ""), ("PIR", pir, "")]
    y = 450
    for k, v in PARAMS.items():
        e = X(unreal.MaterialExpressionScalarParameter, -1300, y)
        e.set_editor_property("parameter_name", k)
        e.set_editor_property("default_value", float(v))
        srcs.append((k, e, ""))
        y += 90
    cu = X(unreal.MaterialExpressionCustom, -600, 0)
    cu.set_editor_property("code", open(HLSL, encoding="utf-8").read())
    cu.set_editor_property("description", "GyroTreeNear")
    F1, F3 = unreal.CustomMaterialOutputType.CMOT_FLOAT1, unreal.CustomMaterialOutputType.CMOT_FLOAT3
    cu.set_editor_property("output_type", F3)
    ins = []
    for n, _, _ in srcs:
        ci = unreal.CustomInput()
        ci.set_editor_property("input_name", n)
        ins.append(ci)
    cu.set_editor_property("inputs", ins)
    outs = []
    for n, t in (("Rough", F1), ("SSS", F3), ("AOut", F1)):
        co = unreal.CustomOutput()
        co.set_editor_property("output_name", n)
        co.set_editor_property("output_type", t)
        outs.append(co)
    cu.set_editor_property("additional_outputs", outs)
    try:
        cu.post_edit_change()
    except Exception:
        pass
    for n, src, pin in srcs:
        if not MEL.connect_material_expressions(src, pin, cu, n):
            log("connect failed", n)
    MP = unreal.MaterialProperty
    MEL.connect_material_property(cu, "", MP.MP_BASE_COLOR)
    for pin, prop in (("Rough", MP.MP_ROUGHNESS), ("SSS", MP.MP_SUBSURFACE_COLOR), ("AOut", MP.MP_AMBIENT_OCCLUSION)):
        if not MEL.connect_material_property(cu, pin, prop):
            log("property connect failed", pin)
    sp = X(unreal.MaterialExpressionConstant, -600, 500)
    sp.set_editor_property("r", 0.1)
    MEL.connect_material_property(sp, "", MP.MP_SPECULAR)
    MEL.recompile_material(m)
    EAL.save_asset(full, only_if_is_dirty=False)
    log("built", full)
    return m


def _pipeline():
    try:
        p = unreal.InterchangeGenericAssetsPipeline()
        mp = p.get_editor_property("mesh_pipeline")
        for k, v in (("build_nanite", True), ("generate_lightmap_u_vs", False), ("collision", False), ("import_static_meshes", True),
                     ("import_skeletal_meshes", False), ("combine_static_meshes", True)):
            try:
                mp.set_editor_property(k, v)
            except Exception as e:
                log("pipeline", k, repr(e)[:120])
        try:
            p.get_editor_property("material_pipeline").set_editor_property("import_materials", False)
        except Exception as e:
            log("pipeline materials", repr(e)[:120])
        return p
    except Exception as e:
        log("no interchange pipeline", repr(e)[:160])
        return None


def import_meshes(mat):
    only = [x for x in os.environ.get("GYROSIM_TREES_NEAR_ONLY", "").split(",") if x]
    files = sorted(f for f in os.listdir(SRC) if f.endswith(".glb") and (not only or any(f == "SM_TreeNear_%s.glb" % o for o in only)))
    info = json.load(open(SRC + "/meshes.json", encoding="utf-8"))["meshes"]
    pipe = _pipeline()
    out = {}
    for f in files:
        t0 = time.time()
        name = os.path.splitext(f)[0]
        t = unreal.AssetImportTask()
        t.filename = SRC + "/" + f
        t.destination_path = MPATH
        t.destination_name = name
        t.automated = True
        t.replace_existing = True
        t.save = False
        if pipe is not None:
            try:
                t.set_editor_property("options", pipe)
            except Exception as e:
                log("options", repr(e)[:120])
        unreal.AssetToolsHelpers.get_asset_tools().import_asset_tasks([t])
        sm = None
        for p in EAL.list_assets(MPATH, recursive=True, include_folder=False):
            a = unreal.load_asset(p.split(".")[0])
            if isinstance(a, unreal.StaticMesh) and a.get_name() == name:
                sm = a
                break
        if sm is None:
            log("IMPORT FAILED", f)
            continue
        try:
            ns = sm.get_editor_property("nanite_settings")
            ns.set_editor_property("enabled", True)
            try:                                   # UE 5.8: shape preservation enum (older: bool preserve_area)
                ns.set_editor_property("shape_preservation", unreal.NaniteShapePreservation.PRESERVE_AREA)
            except Exception as e:
                try:
                    ns.set_editor_property("preserve_area", True)
                except Exception:
                    log("nanite preserve area", repr(e)[:160], [k for k in dir(ns) if not k.startswith("_")][:60])
            sm.set_editor_property("nanite_settings", ns)
        except Exception as e:
            log("nanite", name, repr(e))
        try:
            if mat is not None:
                sm.set_material(0, mat)
        except Exception as e:
            log("material slot", repr(e))
        try:
            sm.set_editor_property("light_map_resolution", 4)
        except Exception:
            pass
        EAL.save_loaded_asset(sm)
        b = sm.get_bounding_box()
        key = name.replace("SM_TreeNear_", "")
        log("mesh", sm.get_path_name(), "bounds cm", [round(v) for v in (b.min.x, b.min.y, b.min.z)], [round(v) for v in (b.max.x, b.max.y, b.max.z)],
            "want h m", info.get(key, {}).get("height_m"), "tris", info.get(key, {}).get("triangles"), "%.0f s" % (time.time() - t0))
        out[name] = sm
    return out


if __name__ in ("__main__", "gyrosim_trees_near_assets"):
    what = os.environ.get("GYROSIM_TREES_NEAR_ASSETS", "meshes,material")
    m = build_material() if "material" in what else (unreal.load_asset(MAT_PATH + "/" + MAT_NAME) if EAL.does_asset_exist(MAT_PATH + "/" + MAT_NAME) else None)
    if "meshes" in what:
        import_meshes(m)
    log("done")
