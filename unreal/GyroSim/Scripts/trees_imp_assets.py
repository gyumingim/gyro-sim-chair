r"""Impostor trees (Content/Python/trees_imp.py, docs/trees-impostor-busan.md): imports the baked atlases + the card mesh and
builds the material.

  /Game/ThirdParty/Trees/Impostor/T_Imp_<name>_A / _B   C:/GyroSimTiles/assets/trees_impostor/T_Imp_*.png (sim/impostor/pipeline.py;
                                                     baked from Poly Haven CC0 + Fab Megascans models -> git-ignored folder)
  /Game/Trees/Imp/SM_GyroImpCard                     own card mesh (one quad, sim/impostor/pipeline.py --ue)
  /Game/Trees/M_GyroTreeImp                          own material (Scripts/trees_imp_card.hlsl vertex, trees_imp.hlsl pixel)

Headless, editor CLOSED (or one without these assets open), holding C:\GyroSimTiles\ue_offscreen.lock:
  "C:\Program Files\Epic Games\UE_5.8\Engine\Binaries\Win64\UnrealEditor-Cmd.exe" <path>\GyroSim.uproject ^
      -run=pythonscript -script=<path>\Scripts\trees_imp_assets.py -unattended -nosplash -nullrhi
GYROSIM_TREES_IMP_ASSETS = "textures,card,material" (default all) or a subset.
"""
import json, os, time
import unreal

SRC = os.environ.get("GYROSIM_IMPOSTOR_DIR", r"C:/GyroSimTiles/assets/trees_impostor").replace("\\", "/")
TPATH = "/Game/ThirdParty/Trees/Impostor"
CPATH = "/Game/Trees/Imp"
MAT_PATH, MAT_NAME = "/Game/Trees", "M_GyroTreeImp"
HERE = os.path.dirname(os.path.abspath(__file__))
PARAMS = dict(G=8.0, Far=0.0, Gain=1.0, VarAmt=1.0, AoAmt=0.7, Dither=0.0)
EAL = unreal.EditorAssetLibrary
MEL = unreal.MaterialEditingLibrary
log = lambda *a: unreal.log_warning("[trees_imp_assets] " + " ".join(str(x) for x in a))
log("start", __name__)
F1, F3 = unreal.CustomMaterialOutputType.CMOT_FLOAT1, unreal.CustomMaterialOutputType.CMOT_FLOAT3

COLOR_HLSL = r"""
// per-tree variation (PerInstanceRandom) + species colour (ColorMul, one material instance per kind) + global gain
float r = frac(PIR * 7.13);
float g2 = frac(PIR * 13.7);
float3 c = C * Mul * Gain * lerp(1.0, 0.86 + 0.28 * r, VarAmt);
c *= lerp(float3(1, 1, 1), float3(1.0 + 0.10 * (g2 - 0.5), 1.0, 1.0 - 0.12 * (g2 - 0.5)), VarAmt);
AOut = lerp(1.0, AOin, AoAmt);
// stochastic coverage (the temporal upscaler averages it): far mips keep the crown's real coverage instead of thinning
float2 sp = Parameters.SvPosition.xy + float(View.StateFrameIndexMod8) * float2(5.588238, 5.588238);
float n = frac(52.9829189 * frac(dot(sp, float2(0.06711056, 0.00583715))));
Mask = Dither > 0.5 ? saturate(A - n + 0.5) : A;
return c;
"""


def tex_import():
    info = json.load(open(SRC + "/imp_info.json", encoding="utf-8"))
    names = sorted({k["atlas"] for k in info["kinds"]})
    tasks = []
    for n in names:
        for s in ("A", "B"):
            t = unreal.AssetImportTask()
            t.filename = "%s/T_Imp_%s_%s.png" % (SRC, n, s)
            t.destination_path = TPATH
            t.destination_name = "T_Imp_%s_%s" % (n, s)
            t.automated = True
            t.replace_existing = True
            t.save = False
            tasks.append(t)
    unreal.AssetToolsHelpers.get_asset_tools().import_asset_tasks(tasks)
    for n in names:
        for s in ("A", "B"):
            p = "%s/T_Imp_%s_%s" % (TPATH, n, s)
            tx = unreal.load_asset(p)
            if tx is None:
                log("TEXTURE IMPORT FAILED", p)
                continue
            tx.set_editor_property("srgb", s == "A")
            tx.set_editor_property("compression_settings", unreal.TextureCompressionSettings.TC_BC7)
            tx.set_editor_property("lod_group", unreal.TextureGroup.TEXTUREGROUP_WORLD)
            try:
                tx.set_editor_property("max_texture_size", 2048)
            except Exception:
                pass
            EAL.save_loaded_asset(tx)
            log("texture", p, tx.blueprint_get_size_x(), tx.blueprint_get_size_y())


def card_import(mat):
    t = unreal.AssetImportTask()
    t.filename = SRC + "/SM_GyroImpCard.glb"
    t.destination_path = CPATH
    t.destination_name = "SM_GyroImpCard"
    t.automated = True
    t.replace_existing = True
    t.save = False
    try:
        p = unreal.InterchangeGenericAssetsPipeline()
        mp = p.get_editor_property("mesh_pipeline")
        for k, v in (("build_nanite", False), ("generate_lightmap_u_vs", False), ("collision", False), ("import_static_meshes", True),
                     ("import_skeletal_meshes", False), ("combine_static_meshes", True)):
            try:
                mp.set_editor_property(k, v)
            except Exception as e:
                log("pipeline", k, repr(e)[:100])
        try:
            p.get_editor_property("material_pipeline").set_editor_property("import_materials", False)
        except Exception as e:
            log("pipeline materials", repr(e)[:100])
        t.set_editor_property("options", p)
    except Exception as e:
        log("no interchange pipeline", repr(e)[:120])
    unreal.AssetToolsHelpers.get_asset_tools().import_asset_tasks([t])
    sm = None
    for p in EAL.list_assets(CPATH, recursive=True, include_folder=False):
        a = unreal.load_asset(p.split(".")[0])
        if isinstance(a, unreal.StaticMesh):
            sm = a
            break
    if sm is None:
        log("CARD IMPORT FAILED")
        return None
    try:
        ns = sm.get_editor_property("nanite_settings")
        ns.set_editor_property("enabled", False)
        sm.set_editor_property("nanite_settings", ns)
    except Exception as e:
        log("nanite", repr(e)[:100])
    if mat is not None:
        sm.set_material(0, mat)
    EAL.save_loaded_asset(sm)
    b = sm.get_bounding_box()
    log("card", sm.get_path_name(), "bounds", [round(v) for v in (b.min.x, b.min.y, b.min.z, b.max.x, b.max.y, b.max.z)],
        "tris", sm.get_num_triangles(0) if hasattr(sm, "get_num_triangles") else "?")
    return sm


def _pos_src(name):
    E = unreal.MaterialPositionTransformSource
    for k in (name, "TRANSFORMPOSSOURCE_" + name):
        if hasattr(E, k):
            return getattr(E, k)
    raise RuntimeError("no position transform source %s in %s" % (name, [x for x in dir(E) if x.isupper()]))


def _vec_src(name):
    E = unreal.MaterialVectorCoordTransformSource
    for k in (name, "TRANSFORMSOURCE_" + name):
        if hasattr(E, k):
            return getattr(E, k)
    raise RuntimeError("no vector source %s in %s" % (name, [x for x in dir(E) if x.isupper()]))


def _vec_dst(name):
    E = unreal.MaterialVectorCoordTransform
    for k in (name, "TRANSFORM_" + name):
        if hasattr(E, k):
            return getattr(E, k)
    raise RuntimeError("no vector dest %s in %s" % (name, [x for x in dir(E) if x.isupper()]))


def _custom(m, x, y, code, desc, ins, outs, out_type=F3):
    cu = MEL.create_material_expression(m, unreal.MaterialExpressionCustom, x, y)
    cu.set_editor_property("code", code)
    cu.set_editor_property("description", desc)
    cu.set_editor_property("output_type", out_type)
    L = []
    for n in ins:
        ci = unreal.CustomInput()
        ci.set_editor_property("input_name", n)
        L.append(ci)
    cu.set_editor_property("inputs", L)
    O = []
    for n, t in outs:
        co = unreal.CustomOutput()
        co.set_editor_property("output_name", n)
        co.set_editor_property("output_type", t)
        O.append(co)
    cu.set_editor_property("additional_outputs", O)
    try:
        cu.post_edit_change()
    except Exception:
        pass
    return cu


def _instance_space():
    """ISM: 'Local' = the component; the per-instance space is 'Instance & Particle'."""
    P = [x for x in dir(unreal.MaterialPositionTransformSource) if x.isupper()]
    V = [x for x in dir(unreal.MaterialVectorCoordTransformSource) if x.isupper()]
    log("position spaces", P, "vector spaces", V)
    pi = next((x for x in P if "INSTANCE" in x), None)
    vi = next((x for x in V if "INSTANCE" in x), None)
    if pi is None or vi is None:
        raise RuntimeError("no instance space")
    return pi, vi


def build_material():
    global LOCAL_POS, LOCAL_VEC
    LOCAL_POS, LOCAL_VEC = _instance_space()
    full = MAT_PATH + "/" + MAT_NAME
    if EAL.does_asset_exist(full):
        m = unreal.load_asset(full)
        MEL.delete_all_material_expressions(m)
    else:
        m = unreal.AssetToolsHelpers.get_asset_tools().create_asset(MAT_NAME, MAT_PATH, unreal.Material, unreal.MaterialFactoryNew())
    m.set_editor_property("blend_mode", unreal.BlendMode.BLEND_MASKED)
    m.set_editor_property("two_sided", True)
    m.set_editor_property("tangent_space_normal", False)
    m.set_editor_property("opacity_mask_clip_value", 0.5)
    m.set_editor_property("shading_model", unreal.MaterialShadingModel.MSM_DEFAULT_LIT)
    for flag, v in (("used_with_instanced_static_meshes", True), ("used_with_static_lighting", False)):
        try:
            m.set_editor_property(flag, v)
        except Exception as e:
            log("flag", flag, repr(e))
    X = lambda cls, x, y: MEL.create_material_expression(m, cls, x, y)
    cam = X(unreal.MaterialExpressionCameraPositionWS, -2200, -200)
    wp = X(unreal.MaterialExpressionWorldPosition, -2200, 0)
    tcam = X(unreal.MaterialExpressionTransformPosition, -1900, -200)
    tpix = X(unreal.MaterialExpressionTransformPosition, -1900, 0)
    for t in (tcam, tpix):
        t.set_editor_property("transform_source_type", _pos_src("WORLD"))
        t.set_editor_property("transform_type", _pos_src(LOCAL_POS))
    MEL.connect_material_expressions(cam, "", tcam, "")
    MEL.connect_material_expressions(wp, "", tpix, "")
    uv = X(unreal.MaterialExpressionTextureCoordinate, -1900, 200)
    P = {}
    y = 400
    for k, v in PARAMS.items():
        e = X(unreal.MaterialExpressionScalarParameter, -1900, y)
        e.set_editor_property("parameter_name", k)
        e.set_editor_property("default_value", float(v))
        P[k] = e
        y += 90
    texa = X(unreal.MaterialExpressionTextureObjectParameter, -1900, y + 50)
    texa.set_editor_property("parameter_name", "TexA")
    texb = X(unreal.MaterialExpressionTextureObjectParameter, -1900, y + 250)
    texb.set_editor_property("parameter_name", "TexB")
    try:
        ta = unreal.load_asset(TPATH + "/T_Imp_pine_a_A"); tb = unreal.load_asset(TPATH + "/T_Imp_pine_a_B")
        if ta:
            texa.set_editor_property("texture", ta)
        if tb:
            texb.set_editor_property("texture", tb)
            texb.set_editor_property("sampler_type", unreal.MaterialSamplerType.SAMPLERTYPE_LINEAR_COLOR)
    except Exception as e:
        log("default textures", repr(e)[:120])
    mul = X(unreal.MaterialExpressionVectorParameter, -1900, y + 450)
    mul.set_editor_property("parameter_name", "ColorMul")
    mul.set_editor_property("default_value", unreal.LinearColor(0.5, 0.93, 1.3, 1.0))
    pir = X(unreal.MaterialExpressionPerInstanceRandom, -1900, y + 600)
    # vertex: card facing the camera
    card = _custom(m, -1400, -400, open(os.path.join(HERE, "trees_imp_card.hlsl"), encoding="utf-8").read(), "ImpCard",
                   ["CamL", "PosL", "UV"], [])
    MEL.connect_material_expressions(tcam, "", card, "CamL")
    MEL.connect_material_expressions(tpix, "", card, "PosL")
    MEL.connect_material_expressions(uv, "", card, "UV")
    wpo = X(unreal.MaterialExpressionTransform, -1000, -400)
    wpo.set_editor_property("transform_source_type", _vec_src(LOCAL_VEC))
    wpo.set_editor_property("transform_type", _vec_dst("WORLD"))
    MEL.connect_material_expressions(card, "", wpo, "")
    # pixel: impostor
    pix = _custom(m, -1400, 0, open(os.path.join(HERE, "trees_imp.hlsl"), encoding="utf-8").read(), "ImpPix",
                  ["CamL", "PixL", "TexA", "TexB", "G", "Far"], [("Alpha", F1), ("NrmL", F3), ("AO", F1), ("PdoL", F3)])
    for n, src in (("CamL", tcam), ("PixL", tpix), ("TexA", texa), ("TexB", texb), ("G", P["G"]), ("Far", P["Far"])):
        if not MEL.connect_material_expressions(src, "", pix, n):
            log("connect failed", n)
    col = _custom(m, -900, 200, COLOR_HLSL, "ImpColor", ["C", "Mul", "Gain", "PIR", "VarAmt", "A", "AOin", "AoAmt", "Dither"],
                  [("AOut", F1), ("Mask", F1)])
    for n, src, pin in (("C", pix, ""), ("Mul", mul, ""), ("Gain", P["Gain"], ""), ("PIR", pir, ""), ("VarAmt", P["VarAmt"], ""),
                        ("A", pix, "Alpha"), ("AOin", pix, "AO"), ("AoAmt", P["AoAmt"], ""), ("Dither", P["Dither"], "")):
        if not MEL.connect_material_expressions(src, pin, col, n):
            log("connect failed", n)
    nw = X(unreal.MaterialExpressionTransform, -900, 500)
    nw.set_editor_property("transform_source_type", _vec_src(LOCAL_VEC))
    nw.set_editor_property("transform_type", _vec_dst("WORLD"))
    MEL.connect_material_expressions(pix, "NrmL", nw, "")
    nn = X(unreal.MaterialExpressionNormalize, -700, 500)
    MEL.connect_material_expressions(nw, "", nn, "")
    pw = X(unreal.MaterialExpressionTransform, -900, 650)
    pw.set_editor_property("transform_source_type", _vec_src(LOCAL_VEC))
    pw.set_editor_property("transform_type", _vec_dst("WORLD"))
    MEL.connect_material_expressions(pix, "PdoL", pw, "")
    pl = X(unreal.MaterialExpressionLength, -700, 650)
    MEL.connect_material_expressions(pw, "", pl, "")
    MP = unreal.MaterialProperty
    ok = [MEL.connect_material_property(col, "", MP.MP_BASE_COLOR),
          MEL.connect_material_property(col, "AOut", MP.MP_AMBIENT_OCCLUSION),
          MEL.connect_material_property(col, "Mask", MP.MP_OPACITY_MASK),
          MEL.connect_material_property(nn, "", MP.MP_NORMAL),
          MEL.connect_material_property(wpo, "", MP.MP_WORLD_POSITION_OFFSET)]
    pdo = [k for k in dir(MP) if "DEPTH" in k.upper()]
    log("depth properties", pdo)
    if pdo and os.environ.get("GYROSIM_TREES_IMP_PDO", "1") == "1":
        ok.append(MEL.connect_material_property(pl, "", getattr(MP, pdo[0])))
    rough = X(unreal.MaterialExpressionConstant, -700, 800); rough.set_editor_property("r", 0.85)
    spec = X(unreal.MaterialExpressionConstant, -700, 880); spec.set_editor_property("r", 0.2)
    ok += [MEL.connect_material_property(rough, "", MP.MP_ROUGHNESS), MEL.connect_material_property(spec, "", MP.MP_SPECULAR)]
    log("property connects", ok)
    MEL.recompile_material(m)
    EAL.save_asset(full, only_if_is_dirty=False)
    log("built", full)
    return m


if __name__ in ("__main__", "gyrosim_trees_imp_assets"):
    what = os.environ.get("GYROSIM_TREES_IMP_ASSETS", "textures,card,material")
    t0 = time.time()
    if "textures" in what:
        tex_import()
    m = build_material() if "material" in what else unreal.load_asset(MAT_PATH + "/" + MAT_NAME)
    if "card" in what:
        card_import(m)
    log("done %.0f s" % (time.time() - t0))
