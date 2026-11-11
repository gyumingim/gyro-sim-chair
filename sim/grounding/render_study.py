"""Building-grounding study, headless Blender part (docs/research/building-grounding-study.md).

    blender -b --factory-startup -P sim/grounding/render_study.py -- prep   CFG.json
    blender -b --factory-startup -P sim/grounding/render_study.py -- render CFG.json [variant,variant ...]

Run it through sim/impostor/run_locked.ps1 (holds C:\\GyroSimTiles\\ue_offscreen.lock). Scans and Busan data are only
read; nothing is written next to them.

CFG (JSON): kind 'scan' | 'busan'; src = OBJ / glb of the scan, or the busan_scene.py JSON; scale (scan units -> m);
center [x, y] and half (m) of the study box; out = output folder; views = [[name, cam heading, pitch, dist], ...];
sun = [azimuth, elevation]; variants = {name: {...}}; params = {...} (fix values, written by analyse.py / by hand).

prep:   loads the scene, casts rays straight down on a 0.5 m grid over the box -> OUT/prep.npz (dsm, cls: 0 nothing,
        1 ground object, 2 building object (Busan only; a scan is one mesh, classify.py splits it from the heights)).
render: needs OUT/rasters.npz from classify.py. Every material gets the same per-pixel logic: world XY -> rasters
        (terrain height DTM, building mask BM, distance to the nearest footprint DIST, canyon field CAN), height above
        the terrain HAG; AOVs hag / dist / bm for the metrics; switches for the variants:
          light 'full' (Cycles: sky occlusion + bounce, = a scan's real light) | 'ue' (sky light unoccluded, no bounce:
                 what Lumen does with Cesium meshes it cannot see), shadow (sun casts shadows),
          ground 'tex' | 'flat' (ground pixels -> one median colour) | 'ortho' (ground pixels -> a non-true ortho photo of
                 the scene itself, 12 deg off nadir: roofs / walls painted next to the mesh, our V-World situation),
          f3 (UE's current facade darkening, Busan base), fa (photo-offset fix: neutral tone over footprint + lean zone),
          fb (ground contact band k exp(-d / w)), fc (stronger facade foot darkening).
        Output per view x variant: OUT/<view>__<variant>/{img,col,sun,nrm,hag,dist,bm}0001.exr (linear, 32 bit).
"""
import json, math, os, sys, time
import bpy
import numpy as np
from mathutils import Matrix, Vector

argv = sys.argv[sys.argv.index("--") + 1:]
MODE, CFG = argv[0], json.load(open(argv[1], encoding="utf-8"))
ONLY = argv[2].split(",") if len(argv) > 2 and argv[2] else None
OUT = CFG["out"]
os.makedirs(OUT, exist_ok=True)
RES = 0.5
LOG = open(os.path.join(OUT, "blender_%s.log" % MODE), "a", encoding="utf-8")


def log(*a):
    s = time.strftime("%H:%M:%S ") + " ".join(str(x) for x in a)
    print(s, flush=True)
    LOG.write(s + "\n")
    LOG.flush()


# ----------------------------------------------------------------------------------------------------- scene loading
def clear():
    bpy.ops.wm.read_factory_settings(use_empty=True)


def load_scan():
    src = CFG["src"]
    if src.lower().endswith(".obj"):
        bpy.ops.wm.obj_import(filepath=src, forward_axis="Y", up_axis="Z")
    else:
        bpy.ops.import_scene.gltf(filepath=src)
    k = float(CFG.get("scale", 1.0))
    cx, cy = CFG["center"]
    cz = float(CFG.get("center_z", 0.0))
    for o in list(bpy.context.scene.objects):
        if o.parent is None:
            o.scale = o.scale * k
            o.location = o.location * k - Vector((cx, cy, cz))
    bpy.context.view_layer.update()
    for o in bpy.context.scene.objects:
        if o.type == "MESH":
            o["gs_role"] = 0


def load_busan():
    sc = json.load(open(CFG["src"], encoding="utf-8"))
    R, C0 = np.array(sc["R"]), np.array(sc["C0"])
    Cy = np.array([[1, 0, 0], [0, 0, -1], [0, 1, 0]], float)      # glTF y-up -> Blender z-up (importer convention)
    E = np.eye(4)
    E[:3, :3], E[:3, 3] = R.T, -R.T @ C0                           # Blender world of the glb (= ECEF) -> local ENU
    for t in sc["tiles"]:
        before = set(bpy.data.objects)
        bpy.ops.import_scene.gltf(filepath=t["path"])
        new = [o for o in bpy.data.objects if o not in before]
        M = np.array(t["matrix"], float).reshape(4, 4).T          # glTF column-major
        Mb = np.eye(4)
        Mb[:3, :3], Mb[:3, 3] = Cy @ M[:3, :3] @ Cy.T, Cy @ M[:3, 3]
        W = E @ Mb                                                 # double precision: ECEF offsets never touch float32
        for o in new:
            if o.type == "MESH":
                o.parent = None
                o.matrix_world = Matrix(W.tolist())
                o["gs_role"] = 2
            else:
                bpy.data.objects.remove(o)
    # ground: terrain grid + the cached V-World photo, assembled in memory only (never saved)
    g = sc["ground"]
    n = g["n"]
    P = np.array(g["P"], float).reshape(n * n, 3)
    UV = np.array(g["uv"], float).reshape(n * n, 2)
    faces = [(i * n + j, i * n + j + 1, (i + 1) * n + j + 1, (i + 1) * n + j) for i in range(n - 1) for j in range(n - 1)]
    me = bpy.data.meshes.new("ground")
    me.from_pydata(P.tolist(), [], faces)
    uvl = me.uv_layers.new(name="UVMap")
    li = np.empty(len(me.loops), np.int64)
    me.loops.foreach_get("vertex_index", li)
    uvl.data.foreach_set("uv", UV[li].astype(np.float32).ravel())
    me.update()
    ob = bpy.data.objects.new("ground", me)
    bpy.context.scene.collection.objects.link(ob)
    ob["gs_role"] = 1
    mz = sc["mosaic"]
    x0, y0, x1, y1 = mz["box"]
    W_, H_ = x1 - x0, y1 - y0
    arr = np.full((H_, W_, 4), 0.4, np.float32)
    arr[..., 3] = 1.0
    for ty, tx, p in mz["tiles"]:
        im = bpy.data.images.load(p, check_existing=False)
        w, h = im.size
        px = np.empty(w * h * 4, np.float32)
        im.pixels.foreach_get(px)
        px = px.reshape(h, w, 4)[::-1]                               # top row first
        bpy.data.images.remove(im)
        ax0, ay0 = max(x0, tx * 256), max(y0, ty * 256)
        ax1, ay1 = min(x1, tx * 256 + 256), min(y1, ty * 256 + 256)
        arr[ay0 - y0:ay1 - y0, ax0 - x0:ax1 - x0] = px[ay0 - ty * 256:ay1 - ty * 256, ax0 - tx * 256:ax1 - tx * 256]
    img = bpy.data.images.new("vw_mosaic_mem", W_, H_, alpha=False)
    img.pixels.foreach_set(arr[::-1].ravel())
    img.update()
    img.pack()                                           # in the session only: the .blend is never saved
    mat = bpy.data.materials.new("ground_photo")
    mat.use_nodes = True
    nt = mat.node_tree
    bsdf = nt.nodes["Principled BSDF"]
    bsdf.inputs["Roughness"].default_value = 1.0
    tx_ = nt.nodes.new("ShaderNodeTexImage")
    tx_.image = img
    tx_.interpolation = "Cubic"
    nt.links.new(tx_.outputs["Color"], bsdf.inputs["Base Color"])
    ob.data.materials.append(mat)
    for o in bpy.context.scene.objects:
        if o.type == "MESH" and o.get("gs_role") == 2:
            b = [o.matrix_world @ Vector(c) for c in o.bound_box]
            log("tile", o.name, "x %.0f..%.0f y %.0f..%.0f z %.0f..%.0f" % (min(v.x for v in b), max(v.x for v in b),
                min(v.y for v in b), max(v.y for v in b), min(v.z for v in b), max(v.z for v in b)))


def load():
    clear()
    (load_busan if CFG["kind"] == "busan" else load_scan)()


# ---------------------------------------------------------------------------------------------------------------- prep
def prep():
    from mathutils.bvhtree import BVHTree
    dg = bpy.context.evaluated_depsgraph_get()
    verts, tris, role = [], [], []
    off = 0
    for o in bpy.context.scene.objects:
        if o.type != "MESH":
            continue
        me = o.evaluated_get(dg).to_mesh()
        me.calc_loop_triangles()
        nv = len(me.vertices)
        co = np.empty(nv * 3, np.float64)
        me.vertices.foreach_get("co", co)
        co = co.reshape(-1, 3)
        M = np.array(o.matrix_world)
        co = co @ M[:3, :3].T + M[:3, 3]
        t = np.empty(len(me.loop_triangles) * 3, np.int64)
        me.loop_triangles.foreach_get("vertices", t)
        verts.append(co)
        tris.append(t.reshape(-1, 3) + off)
        role.append(np.full(len(t) // 3, int(o.get("gs_role", 0)), np.int8))
        off += nv
        o.evaluated_get(dg).to_mesh_clear()
    V = np.concatenate(verts)
    T = np.concatenate(tris)
    ROLE = np.concatenate(role)
    log("bvh", len(V), "verts", len(T), "tris")
    bvh = BVHTree.FromPolygons(V.tolist(), T.tolist(), all_triangles=True)
    half = float(CFG["half"])
    n = int(round(2 * half / RES))
    x0 = y0 = -half
    dsm = np.full((n, n), np.nan, np.float32)
    cls = np.zeros((n, n), np.int8)
    ztop = float(V[:, 2].max()) + 10.0
    down = Vector((0, 0, -1))
    for i in range(n):
        y = y0 + (i + 0.5) * RES
        for j in range(n):
            loc, nrm, idx, d = bvh.ray_cast(Vector((x0 + (j + 0.5) * RES, y, ztop)), down)
            if loc is not None:
                dsm[i, j] = loc.z
                cls[i, j] = ROLE[idx]
    np.savez_compressed(os.path.join(OUT, "prep.npz"), dsm=dsm, cls=cls, x0=x0, y0=y0, res=RES,
                        zmin=float(V[:, 2].min()), made=time.strftime("%Y-%m-%d %H:%M:%S"), src=CFG["src"])
    log("prep done", n, "x", n, "hits", int(np.isfinite(dsm).sum()))


# ----------------------------------------------------------------------------------------------------------- rendering
def float_image(name, a):
    """a: rows from the south (row 0 = y0), 2D -> Non-Color float image in memory."""
    h, w = a.shape
    img = bpy.data.images.new(name, w, h, alpha=False, float_buffer=True, is_data=True)
    img.colorspace_settings.name = "Non-Color"          # before the pixels: changing it regenerates a generated image
    px = np.ones((h, w, 4), np.float32)
    px[..., 0] = px[..., 1] = px[..., 2] = a
    img.pixels.foreach_set(px.ravel())
    img.update()
    img.pack()
    return img


SW = {}            # switch name -> list of Value nodes (one per material)


def switch(nt, name, val=0.0):
    v = nt.nodes.new("ShaderNodeValue")
    v.outputs[0].default_value = val
    v.label = name
    SW.setdefault(name, []).append(v)
    return v.outputs[0]


def set_switch(name, val):
    for v in SW.get(name, []):
        v.outputs[0].default_value = float(val)


def mth(nt, op, a, b=None, clamp=False):
    m = nt.nodes.new("ShaderNodeMath")
    m.operation = op
    m.use_clamp = clamp
    for k, x in enumerate((a, b)):
        if x is None:
            continue
        if isinstance(x, (int, float)):
            m.inputs[k].default_value = float(x)
        else:
            nt.links.new(x, m.inputs[k])
    return m.outputs[0]


def mix(nt, f, a, b, blend="MIX"):
    m = nt.nodes.new("ShaderNodeMix")
    m.data_type = "RGBA"
    m.blend_type = blend
    for sock, x in ((m.inputs[0], f), (m.inputs[6], a), (m.inputs[7], b)):
        if isinstance(x, (int, float)):
            sock.default_value = float(x)
        elif isinstance(x, tuple):
            sock.default_value = x
        else:
            nt.links.new(x, sock)
    return m.outputs[2]


def rgb(nt, name, c):
    n_ = nt.nodes.new("ShaderNodeRGB")
    n_.outputs[0].default_value = (c[0], c[1], c[2], 1.0)
    n_.label = name
    SW.setdefault("rgb_" + name, []).append(n_)
    return n_.outputs[0]


def instrument(mat, RA, P, ortho_img, ortho_map):
    nt = mat.node_tree
    bsdf = next((n for n in nt.nodes if n.type == "BSDF_PRINCIPLED"), None)
    out = next((n for n in nt.nodes if n.type == "OUTPUT_MATERIAL"), None)
    if bsdf is None or out is None:
        return False
    bc = bsdf.inputs["Base Color"]
    if bc.is_linked:
        col0 = bc.links[0].from_socket
    else:
        col0 = rgb(nt, "const", bc.default_value[:3])
    geo = nt.nodes.new("ShaderNodeNewGeometry")
    sep = nt.nodes.new("ShaderNodeSeparateXYZ")
    nt.links.new(geo.outputs["Position"], sep.inputs[0])
    mp = nt.nodes.new("ShaderNodeMapping")
    mp.vector_type = "POINT"
    Wm, Hm = RA["w"], RA["h"]
    mp.inputs["Scale"].default_value = (1.0 / Wm, 1.0 / Hm, 0.0)
    mp.inputs["Location"].default_value = (-RA["x0"] / Wm, -RA["y0"] / Hm, 0.0)
    nt.links.new(geo.outputs["Position"], mp.inputs[0])

    def tex(img, interp="Linear"):
        t = nt.nodes.new("ShaderNodeTexImage")
        t.image = img
        t.interpolation = interp
        t.extension = "EXTEND"
        nt.links.new(mp.outputs[0], t.inputs[0])
        return t.outputs["Color"]
    dtm, bm, dist, can, lean = (tex(RA["img"][k]) for k in ("dtm", "bm", "dist", "can", "lean"))
    hag = mth(nt, "SUBTRACT", sep.outputs["Z"], dtm)
    for nm, s in (("hag", hag), ("dist", dist), ("bm", bm)):
        a = nt.nodes.new("ShaderNodeOutputAOV")
        a.aov_name = nm
        nt.links.new(s, a.inputs["Value"])
    # classes
    sepn = nt.nodes.new("ShaderNodeSeparateXYZ")
    nt.links.new(geo.outputs["Normal"], sepn.inputs[0])
    nz = sepn.outputs["Z"]
    # ground = low and facing up (not 'outside the building mask': the mask is 1 m wider than the footprint, which left an
    # un-darkened 1 m rim of the photo around every building - a bright halo)
    isg = mth(nt, "MULTIPLY", mth(nt, "LESS_THAN", hag, 0.7), mth(nt, "GREATER_THAN", nz, 0.6))
    vert = mth(nt, "LESS_THAN", mth(nt, "ABSOLUTE", nz), 0.5)
    isf = mth(nt, "MULTIPLY", mth(nt, "MULTIPLY", vert, mth(nt, "GREATER_THAN", bm, 0.5)), mth(nt, "GREATER_THAN", hag, -1.5))
    za = mth(nt, "MAXIMUM", hag, 0.0)
    col = col0
    # ground replacement (scan ablations)
    col = mix(nt, mth(nt, "MULTIPLY", isg, switch(nt, "flat")), col, rgb(nt, "flat", P.get("flat", (0.3, 0.3, 0.3))))
    if ortho_img is not None:
        cxyz = nt.nodes.new("ShaderNodeCombineXYZ")
        nt.links.new(sep.outputs["X"], cxyz.inputs[0])
        nt.links.new(sep.outputs["Y"], cxyz.inputs[1])
        nt.links.new(dtm, cxyz.inputs[2])
        m1 = nt.nodes.new("ShaderNodeMapping")
        m1.vector_type = "TEXTURE"
        m1.inputs["Location"].default_value = ortho_map["loc"]
        m1.inputs["Rotation"].default_value = ortho_map["rot"]
        m1.inputs["Scale"].default_value = (ortho_map["scale"], ortho_map["scale"], 1.0)
        nt.links.new(cxyz.outputs[0], m1.inputs[0])
        m2 = nt.nodes.new("ShaderNodeMapping")
        m2.vector_type = "POINT"
        m2.inputs["Location"].default_value = (0.5, 0.5, 0.0)
        nt.links.new(m1.outputs[0], m2.inputs[0])
        ot = nt.nodes.new("ShaderNodeTexImage")
        ot.image = ortho_img
        ot.extension = "EXTEND"
        nt.links.new(m2.outputs[0], ot.inputs[0])
        col = mix(nt, mth(nt, "MULTIPLY", isg, switch(nt, "ortho")), col, ot.outputs["Color"])
    # UE's current facade darkening (f3, buildings_facade.hlsl GdBase 0.5 / GdBaseH 8 / GdGrad 0.6 / GdGradH 50 / GdFloor 0.7)
    foot = mth(nt, "EXPONENT", mth(nt, "DIVIDE", za, -8.0))
    lowf = mth(nt, "SUBTRACT", 1.0, mth(nt, "DIVIDE", za, 50.0), clamp=True)
    canyon = mth(nt, "MULTIPLY", mth(nt, "MAXIMUM", can, 0.7), mth(nt, "POWER", lowf, 1.5))
    f3 = mth(nt, "MULTIPLY", mth(nt, "SUBTRACT", 1.0, mth(nt, "MULTIPLY", foot, 0.5)),
              mth(nt, "SUBTRACT", 1.0, mth(nt, "MULTIPLY", canyon, 0.6)))
    f3m = mth(nt, "ADD", 1.0, mth(nt, "MULTIPLY", mth(nt, "MULTIPLY", isf, switch(nt, "f3")), mth(nt, "SUBTRACT", f3, 1.0)))
    col = mix(nt, 1.0, col, f3m, "MULTIPLY")
    # fix a: neutral shadowed ground tone over the footprint margin + lean zone
    col = mix(nt, mth(nt, "MULTIPLY", mth(nt, "MULTIPLY", isg, lean), switch(nt, "fa")), col, rgb(nt, "tone", P.get("tone", (0.12, 0.12, 0.12))))
    # fix a', texture kept: the photo inside the same mask multiplied by tone_mul (darker, a little desaturated)
    col = mix(nt, mth(nt, "MULTIPLY", mth(nt, "MULTIPLY", isg, lean), switch(nt, "fam")), col,
              rgb(nt, "tone_mul", P.get("tone_mul", (0.5, 0.5, 0.5))), "MULTIPLY")
    # fix b: ground contact band 1 - k exp(-d / w)
    band = mth(nt, "MULTIPLY", switch(nt, "fb_k", P.get("fb_k", 0.4)),
                mth(nt, "EXPONENT", mth(nt, "DIVIDE", mth(nt, "MAXIMUM", dist, 0.0), mth(nt, "MULTIPLY", -1.0, switch(nt, "fb_w", P.get("fb_w", 3.0))))))
    bm_ = mth(nt, "SUBTRACT", 1.0, mth(nt, "MULTIPLY", mth(nt, "MULTIPLY", isg, switch(nt, "fb")), band))
    col = mix(nt, 1.0, col, bm_, "MULTIPLY")
    # fix c: facade foot darkening 1 - k exp(-z / h)
    fc = mth(nt, "SUBTRACT", 1.0, mth(nt, "MULTIPLY", mth(nt, "MULTIPLY", isf, switch(nt, "fc")),
                                         mth(nt, "MULTIPLY", switch(nt, "fc_k", P.get("fc_k", 0.45)),
                                              mth(nt, "EXPONENT", mth(nt, "DIVIDE", za, mth(nt, "MULTIPLY", -1.0, switch(nt, "fc_h", P.get("fc_h", 4.0))))))))
    col = mix(nt, 1.0, col, fc, "MULTIPLY")
    nt.links.new(col, bc)
    # shading: principled (+ 'ue' unoccluded sky ambient as emission) or pure albedo emission (ortho photo pass)
    sh0 = out.inputs["Surface"].links[0].from_socket if out.inputs["Surface"].is_linked else bsdf.outputs[0]
    em = nt.nodes.new("ShaderNodeEmission")
    sky = P.get("sky", (0.30, 0.36, 0.46))
    # unoccluded sky irradiance / pi per unit albedo: up-facing 1, walls 0.5 (+ lower hemisphere ~ ground 0.2)
    amb = mth(nt, "ADD", 0.6, mth(nt, "MULTIPLY", nz, 0.4))
    amb = mth(nt, "MULTIPLY", amb, switch(nt, "ue"))
    tint = mix(nt, 1.0, col, (sky[0], sky[1], sky[2], 1.0), "MULTIPLY")
    nt.links.new(tint, em.inputs["Color"])
    nt.links.new(amb, em.inputs["Strength"])
    add = nt.nodes.new("ShaderNodeAddShader")
    nt.links.new(sh0, add.inputs[0])
    nt.links.new(em.outputs[0], add.inputs[1])
    em2 = nt.nodes.new("ShaderNodeEmission")
    nt.links.new(col, em2.inputs["Color"])
    ms = nt.nodes.new("ShaderNodeMixShader")
    nt.links.new(switch(nt, "emit"), ms.inputs[0])
    nt.links.new(add.outputs[0], ms.inputs[1])
    nt.links.new(em2.outputs[0], ms.inputs[2])
    nt.links.new(ms.outputs[0], out.inputs["Surface"])
    return True


def setup_cycles(samples):
    sc = bpy.context.scene
    sc.render.engine = "CYCLES"
    prefs = bpy.context.preferences.addons["cycles"].preferences
    dev = "NONE"
    for t in ("OPTIX", "CUDA"):
        try:
            prefs.compute_device_type = t
            try:
                prefs.refresh_devices()
            except Exception:
                prefs.get_devices()
            if any(d.type == t for d in prefs.devices):
                dev = t
                break
        except Exception:
            pass
    for d in prefs.devices:
        d.use = d.type == dev
    sc.cycles.device = "GPU" if dev != "NONE" else "CPU"
    sc.render.threads_mode = "FIXED"
    sc.render.threads = 8                                        # half the cores at most (power rule)
    sc.cycles.samples = samples
    sc.cycles.use_denoising = True
    sc.cycles.denoiser = "OPENIMAGEDENOISE"
    sc.cycles.max_bounces = 4
    sc.view_settings.view_transform = "Standard"
    log("device", sc.cycles.device, dev)


def world(sky):
    w = bpy.data.worlds.new("w")
    bpy.context.scene.world = w
    w.use_nodes = True
    nt = w.node_tree
    bg = nt.nodes["Background"]
    bg.inputs["Color"].default_value = (sky[0], sky[1], sky[2], 1.0)
    lp = nt.nodes.new("ShaderNodeLightPath")
    bk = nt.nodes.new("ShaderNodeBackground")
    bk.inputs["Color"].default_value = (0, 0, 0, 1)
    ms = nt.nodes.new("ShaderNodeMixShader")
    sw = nt.nodes.new("ShaderNodeValue")
    sw.label = "ue_world"
    # factor = max(is camera ray, 1 - ue): ue -> black for every non-camera ray
    mx = nt.nodes.new("ShaderNodeMath")
    mx.operation = "MAXIMUM"
    nt.links.new(lp.outputs["Is Camera Ray"], mx.inputs[0])
    inv = nt.nodes.new("ShaderNodeMath")
    inv.operation = "SUBTRACT"
    inv.inputs[0].default_value = 1.0
    nt.links.new(sw.outputs[0], inv.inputs[1])
    nt.links.new(inv.outputs[0], mx.inputs[1])
    nt.links.new(mx.outputs[0], ms.inputs[0])
    nt.links.new(bk.outputs[0], ms.inputs[1])
    nt.links.new(bg.outputs[0], ms.inputs[2])
    nt.links.new(ms.outputs[0], nt.nodes["World Output"].inputs["Surface"])
    SW.setdefault("ue", []).append(sw)
    w.lightgroup = "sky"


def compositor(path_prefix):
    sc = bpy.context.scene
    sc.use_nodes = True
    nt = sc.node_tree
    for n in list(nt.nodes):
        nt.nodes.remove(n)
    rl = nt.nodes.new("CompositorNodeRLayers")
    fo = nt.nodes.new("CompositorNodeOutputFile")
    fo.base_path = path_prefix
    fo.format.file_format = "OPEN_EXR"
    fo.format.color_depth = "32"
    fo.format.color_mode = "RGB"
    fo.file_slots.clear()
    for slot, sock in (("img", "Image"), ("col", "DiffCol"), ("sun", "Combined_sun"), ("nrm", "Normal"),
                       ("hag", "hag"), ("dist", "dist"), ("bm", "bm")):
        fo.file_slots.new(slot)
        src = rl.outputs[sock]
        if sock == "Normal":                                   # vector pass -> colour socket, so the EXR has R/G/B
            mx = nt.nodes.new("CompositorNodeMixRGB")
            mx.blend_type = "MIX"
            mx.use_clamp = False
            mx.inputs[0].default_value = 0.0
            nt.links.new(src, mx.inputs[1])
            nt.links.new(src, mx.inputs[2])
            src = mx.outputs[0]
        nt.links.new(src, fo.inputs[slot])
    return fo


def place_camera(cam, heading, pitch, dist, tz):
    h, p = math_r(heading), math_r(pitch)
    cam.location = Vector((-math.sin(h) * math.cos(p) * dist, -math.cos(h) * math.cos(p) * dist, tz + math.sin(p) * dist))
    cam.rotation_euler = (math.pi / 2 - p, 0.0, -h)


def math_r(d):
    return math.radians(d)


def render_all():
    sc = bpy.context.scene
    rz = np.load(os.path.join(OUT, "rasters.npz"))
    P = dict(CFG.get("params", {}))
    pj = os.path.join(OUT, "params.json")
    if os.path.exists(pj):
        P.update(json.load(open(pj, encoding="utf-8")))
    res = float(rz["res"])
    RA = dict(x0=float(rz["x0"]), y0=float(rz["y0"]), w=rz["dtm"].shape[1] * res, h=rz["dtm"].shape[0] * res, img={})
    for k in ("dtm", "bm", "dist", "can", "lean"):
        RA["img"][k] = float_image("ra_" + k, rz[k].astype(np.float32))
    vl = sc.view_layers[0]
    for nm in ("hag", "dist", "bm"):
        a = vl.aovs.add()
        a.name, a.type = nm, "VALUE"
    vl.use_pass_diffuse_color = True
    vl.use_pass_normal = True
    vl.lightgroups.add(name="sun")
    vl.lightgroups.add(name="sky")
    setup_cycles(int(CFG.get("samples", 96)))
    sky = P.get("sky", (0.30, 0.36, 0.46))
    world(sky)
    sun_d = bpy.data.lights.new("sun", "SUN")
    sun_d.energy = float(P.get("sun_e", 5.0))
    sun_d.angle = math.radians(0.53)
    sun = bpy.data.objects.new("sun", sun_d)
    sc.collection.objects.link(sun)
    az, el = CFG.get("sun", (215.0, 42.0))
    sun.rotation_euler = (math.radians(90 - el), 0.0, math.radians(180 - az))
    sun.lightgroup = "sun"
    cam_d = bpy.data.cameras.new("cam")
    cam = bpy.data.objects.new("cam", cam_d)
    sc.collection.objects.link(cam)
    sc.camera = cam
    tz = float(np.nanmedian(rz["dtm"]))
    # ortho photo of the scene itself (non-true ortho, 12 deg off nadir), for the 'ortho' ground ablation
    variants = CFG["variants"]
    need_ortho = any(v.get("ground") == "ortho" for v in variants.values())
    ortho_img, ortho_map = None, None
    if need_ortho:
        ocam_d = bpy.data.cameras.new("ocam")
        ocam_d.type = "ORTHO"
        half = float(CFG["half"])
        ocam_d.ortho_scale = 2.0 * half
        ocam_d.clip_end = 5000
        ocam = bpy.data.objects.new("ocam", ocam_d)
        sc.collection.objects.link(ocam)
        tilt, tdir = math.radians(12.0), math.radians(float(P.get("ortho_dir", 160.0)))
        ocam.rotation_euler = (tilt, 0.0, -tdir + math.pi)
        bpy.context.view_layer.update()
        fwd = ocam.matrix_world.to_3x3() @ Vector((0, 0, -1))
        ocam.location = Vector((0, 0, tz)) - fwd * 1500.0
        ortho_map = dict(loc=tuple(ocam.location), rot=tuple(ocam.rotation_euler), scale=2.0 * half)
    mats = [m for m in bpy.data.materials if m.use_nodes and m.users > 0]
    for m in mats:
        pass
    # ortho pass first (emission of the plain albedo), then instrument with the photo
    if need_ortho:
        opath = os.path.join(OUT, "ortho_self.png")
        if not os.path.exists(opath):
            for m in mats:
                instrument(m, RA, P, None, None)
            set_switch("emit", 1)
            sc.camera = ocam
            sc.render.resolution_x = sc.render.resolution_y = 2048
            sc.render.filepath = opath
            sc.render.image_settings.file_format = "PNG"
            sc.use_nodes = False
            sc.cycles.samples = 16
            bpy.ops.render.render(write_still=True)
            log("ortho photo", opath)
            # rebuild clean materials: reload scene and redo
            return "RELOAD"
        ortho_img = bpy.data.images.load(opath)
    for m in mats:
        ok = instrument(m, RA, P, ortho_img, ortho_map)
        log("material", m.name, ok)
    for k in ("flat", "tone", "tone_mul"):
        if k in P:
            for n_ in SW.get("rgb_" + k, []):
                n_.outputs[0].default_value = (P[k][0], P[k][1], P[k][2], 1.0)
    sc.camera = cam
    sc.render.resolution_x, sc.render.resolution_y = CFG.get("res", (1280, 720))
    sc.cycles.samples = int(CFG.get("samples", 96))
    cam_d.lens = 18.0 / math.tan(math.radians(CFG.get("hfov", 50.0) / 2))
    cam_d.clip_end = 6000
    for vname, v in variants.items():
        if ONLY and vname not in ONLY:
            continue
        ue = v.get("light", "full") == "ue"
        set_switch("ue", 1 if ue else 0)
        sc.cycles.diffuse_bounces = 0 if ue else 3
        sc.cycles.glossy_bounces = 0 if ue else 2
        sun_d.use_shadow = bool(v.get("shadow", True))
        set_switch("flat", 1 if v.get("ground") == "flat" else 0)
        set_switch("ortho", 1 if v.get("ground") == "ortho" else 0)
        for f in ("f3", "fa", "fam", "fb", "fc"):
            set_switch(f, 1 if v.get(f) else 0)
        for k in ("fb_k", "fb_w", "fc_k", "fc_h"):
            set_switch(k, v.get(k, P.get(k, {"fb_k": 0.4, "fb_w": 3.0, "fc_k": 0.45, "fc_h": 4.0}[k])))
        tm = v.get("tone_mul", P.get("tone_mul", (0.5, 0.5, 0.5)))
        for n_ in SW.get("rgb_tone_mul", []):
            n_.outputs[0].default_value = (tm[0], tm[1], tm[2], 1.0)
        set_switch("emit", 0)
        for (vn, hd, pt, ds) in CFG["views"]:
            d = os.path.join(OUT, "%s__%s" % (vn, vname))
            if os.path.exists(os.path.join(d, "img0001.exr")):
                continue
            place_camera(cam, hd, pt, ds, tz)
            compositor(d + os.sep)
            sc.render.filepath = os.path.join(d, "unused_")
            t0 = time.time()
            bpy.ops.render.render(write_still=False)
            log("rendered", vn, vname, "%.1f s" % (time.time() - t0))
    return "OK"


if MODE == "prep":
    load()
    prep()
elif MODE == "render":
    load()
    r = render_all()
    if r == "RELOAD":
        SW.clear()
        load()
        render_all()
log("end", MODE)
