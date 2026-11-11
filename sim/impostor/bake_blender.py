"""Impostor bake + reference renders of the real downloaded tree models, inside headless Blender (11-11).

Run only through the lock runner (power rule), never with a window:
    powershell -NoProfile -File sim/impostor/run_locked.ps1 -exe <blender.exe> \
        -argstr "-b --factory-startup -P sim/impostor/bake_blender.py -- <job.json>" -log <log>

job.json (written by sim/impostor/pipeline.py):
    {"out": dir, "species": {name: {"src": file, "kind": "usd"|"gltf", "node": i}}, "bake": [names], "grid": 8, "px": 256,
     "spp": 48, "scenes": [{"name", "res": [w, h], "spp", "cam": {"loc", "at", "fov"}, "trees": [[name, x, y, yaw_deg, scale]],
     "ground": true, "sun": [az_deg, el_deg]}]}

--bake: every species is rendered from grid x grid hemi-octahedral directions (orthographic, transparent film, Cycles GPU)
into single-layer EXRs: diffuse colour, normal (world), depth (Z), AO (local, 2.5 m), alpha. pipeline.py packs them.
--scenes: full-mesh reference pictures (sun + uniform sky + ground) with collection instances, the same cameras the
impostor software renderer uses -> real vs impostor side by side.
Models are third-party (Fab Megascans: UE only; Poly Haven: CC0): nothing made here goes into git.
"""
import bpy, json, math, os, sys, time
from mathutils import Vector, Matrix

ARGS = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
JOB = json.load(open(ARGS[0]))
OUT = JOB["out"]
t0 = time.time()


def log(*a):
    print("[imp %6.1fs]" % (time.time() - t0), *a, flush=True)


def gpu_setup(scene):
    scene.render.engine = "CYCLES"
    pr = bpy.context.preferences.addons["cycles"].preferences
    for kind in ("OPTIX", "CUDA"):
        try:
            pr.compute_device_type = kind
            pr.get_devices()
            devs = [d for d in pr.devices if d.type == kind]
            if devs:
                for d in pr.devices:
                    d.use = d.type == kind
                scene.cycles.device = "GPU"
                log("device", kind, [d.name for d in devs])
                return
        except Exception as e:                                            # noqa: BLE001
            log("no", kind, e)
    scene.cycles.device = "CPU"
    log("device CPU")


def hemi_oct_dir(u, v):
    """grid uv in [-1,1]^2 -> unit direction, z >= 0 (hemi-octahedron, 45 deg rotated)."""
    x = (u + v) * 0.5
    y = (u - v) * 0.5
    z = 1.0 - abs(x) - abs(y)
    d = Vector((x, y, max(z, 0.0)))
    return d.normalized()


# ---- import -------------------------------------------------------------------------------------------------------
def prep_gltf(src, node, tmpdir):
    """a copy of the glTF json that holds only one tree node (absolute buffer / image paths, translation zeroed)."""
    g = json.load(open(src))
    base = os.path.dirname(src)
    for b in g.get("buffers", []):
        b["uri"] = os.path.join(base, b["uri"]).replace("\\", "/")
    for im in g.get("images", []):
        if "uri" in im:
            im["uri"] = os.path.join(base, im["uri"]).replace("\\", "/")
    nd = g["nodes"][node]
    nd.pop("translation", None)
    nd.pop("children", None)
    g["meshes"] = [g["meshes"][nd["mesh"]]]
    nd["mesh"] = 0
    g["nodes"] = [nd]
    g["scenes"] = [{"nodes": [0]}]
    g["scene"] = 0
    os.makedirs(tmpdir, exist_ok=True)
    p = os.path.join(tmpdir, "%s_node%d.gltf" % (os.path.splitext(os.path.basename(src))[0], node))
    json.dump(g, open(p, "w"))
    return p


def leaf_variation(mat, strength=0.22):
    """flat Megascans USD leaf colour (no textures in the Fab USD) -> random brightness / hue per leaf island."""
    nt = mat.node_tree
    bsdf = next((n for n in nt.nodes if n.bl_idname == "ShaderNodeBsdfPrincipled"), None)
    if bsdf is None or bsdf.inputs["Base Color"].is_linked:
        return
    c = tuple(bsdf.inputs["Base Color"].default_value)
    geo = nt.nodes.new("ShaderNodeNewGeometry")
    oi = nt.nodes.new("ShaderNodeObjectInfo")
    ramp = nt.nodes.new("ShaderNodeValToRGB")
    e = ramp.color_ramp.elements
    e[0].color = (c[0] * 0.72, c[1] * 0.78, c[2] * 0.7, 1)
    e[1].color = (c[0] * 1.35, c[1] * 1.22, c[2] * 1.05, 1)
    mix = nt.nodes.new("ShaderNodeMath"); mix.operation = "MULTIPLY_ADD"
    mix.inputs[1].default_value = 0.7
    nt.links.new(geo.outputs["Random Per Island"], mix.inputs[0])
    nt.links.new(oi.outputs["Random"], mix.inputs[2])
    mix2 = nt.nodes.new("ShaderNodeMath"); mix2.operation = "MULTIPLY"; mix2.inputs[1].default_value = 1 / 1.7
    nt.links.new(mix.outputs[0], mix2.inputs[0])
    nt.links.new(mix2.outputs[0], ramp.inputs["Fac"])
    nt.links.new(ramp.outputs["Color"], bsdf.inputs["Base Color"])


def import_species(name, sp, tmpdir):
    """imports one tree into its own collection; returns (collection, bbox min, bbox max) in world metres, z up."""
    before = set(bpy.data.objects)
    mats_before = set(bpy.data.materials)
    if sp["kind"] == "usd":
        bpy.ops.wm.usd_import(filepath=sp["src"])
    else:
        bpy.ops.import_scene.gltf(filepath=prep_gltf(sp["src"], sp["node"], tmpdir))
    new = [o for o in bpy.data.objects if o not in before]
    col = bpy.data.collections.new("T_" + name)
    bpy.context.scene.collection.children.link(col)
    for o in new:
        for c in list(o.users_collection):
            if c.name.startswith("proto") or c.name == "prototypes":
                continue                                                    # USD instancer prototypes stay where they are
            c.objects.unlink(o)
        if not o.users_collection:
            col.objects.link(o)
    for m in bpy.data.materials:
        if m in mats_before:
            continue
        nm = m.name.lower()
        if sp["kind"] == "usd" and "twosided" in nm:
            leaf_variation(m)
        if "dead" in nm and sp.get("hide_dead", False):
            pass
    bpy.context.view_layer.update()
    dg = bpy.context.evaluated_depsgraph_get()
    lo = Vector((1e9, 1e9, 1e9)); hi = -lo
    names = {o.name for o in col.objects}
    n_inst = 0
    for inst in dg.object_instances:
        src = inst.instance_object if inst.is_instance else inst.object
        par = inst.parent.name if inst.is_instance and inst.parent else inst.object.name
        if par not in names and src.name not in names:
            continue
        if src.type not in ("MESH",):
            continue
        n_inst += 1
        M = inst.matrix_world
        for c in src.bound_box:
            w = M @ Vector(c)
            lo = Vector(map(min, lo, w)); hi = Vector(map(max, hi, w))
    tris = 0
    for o in new:
        if o.type == "MESH":
            tris += sum(len(p.vertices) - 2 for p in o.data.polygons)
    log("imported", name, "objects", len(new), "mesh instances", n_inst, "proto tris", tris, "bbox", tuple(lo), tuple(hi))
    return col, lo, hi, n_inst, tris


def base_point(lo, hi):
    return Vector(((lo.x + hi.x) / 2, (lo.y + hi.y) / 2, lo.z))


# ---- bake ---------------------------------------------------------------------------------------------------------
def setup_passes(scene, outdir):
    vl = scene.view_layers[0]
    vl.use_pass_diffuse_color = True
    vl.use_pass_normal = True
    vl.use_pass_z = True
    vl.use_pass_ambient_occlusion = True
    scene.use_nodes = True
    nt = scene.node_tree
    for n in list(nt.nodes):
        nt.nodes.remove(n)
    rl = nt.nodes.new("CompositorNodeRLayers")
    fo = nt.nodes.new("CompositorNodeOutputFile")
    fo.base_path = outdir
    fo.format.file_format = "OPEN_EXR"
    fo.format.color_depth = "32"
    fo.format.exr_codec = "ZIP"
    fo.file_slots.clear()
    for sock in ("DiffCol", "Normal", "Depth", "AO", "Alpha"):
        fo.file_slots.new(sock + "_")
        if sock == "Normal":                                                # vector -> colour socket (RGB channels in the EXR)
            gm = nt.nodes.new("CompositorNodeGamma"); gm.inputs["Gamma"].default_value = 1.0
            nt.links.new(rl.outputs[sock], gm.inputs["Image"])
            nt.links.new(gm.outputs["Image"], fo.inputs[sock + "_"])
        else:
            nt.links.new(rl.outputs[sock], fo.inputs[sock + "_"])
    comp = nt.nodes.new("CompositorNodeComposite")
    nt.links.new(rl.outputs["Image"], comp.inputs["Image"])


def bake(names):
    scene = bpy.context.scene
    gpu_setup(scene)
    G, PX = JOB["grid"], JOB["px"]
    scene.render.resolution_x = scene.render.resolution_y = PX
    scene.render.resolution_percentage = 100
    scene.render.film_transparent = True
    scene.render.filter_size = 1.2
    scene.cycles.samples = JOB.get("spp", 48)
    scene.cycles.use_adaptive_sampling = False
    scene.cycles.use_denoising = False
    scene.cycles.max_bounces = 0
    scene.cycles.diffuse_bounces = scene.cycles.glossy_bounces = scene.cycles.transmission_bounces = 0
    scene.cycles.transparent_max_bounces = 16
    scene.render.use_persistent_data = True
    scene.view_settings.view_transform = "Standard"
    if scene.world is None:
        scene.world = bpy.data.worlds.new("W")
    scene.world.light_settings.distance = JOB.get("ao_m", 2.5)
    cam_d = bpy.data.cameras.new("C"); cam_d.type = "ORTHO"
    cam = bpy.data.objects.new("C", cam_d); scene.collection.objects.link(cam); scene.camera = cam
    meta_all = {}
    for name in names:
        sp = JOB["species"][name]
        col, lo, hi, n_inst, tris = import_species(name, sp, os.path.join(OUT, "_tmp"))
        for c in bpy.data.collections:                                      # only this tree visible
            if c.name.startswith("T_"):
                c.hide_render = c != col
        ctr = (lo + hi) / 2
        R = (hi - lo).length / 2
        cam_d.ortho_scale = 2 * R
        cam_d.clip_start = 0.01; cam_d.clip_end = 4 * R + 10
        fdir = os.path.join(OUT, "frames", name)
        os.makedirs(fdir, exist_ok=True)
        setup_passes(scene, fdir)
        dirs = []
        for j in range(G):
            for i in range(G):
                k = j * G + i
                u = (i + 0.5) / G * 2 - 1; v = (j + 0.5) / G * 2 - 1
                d = hemi_oct_dir(u, v)
                if d.z < 0.02:                                               # keep the camera just above the horizon
                    d = Vector((d.x, d.y, 0.02)).normalized()
                dirs.append(tuple(d))
                cam.location = ctr + d * (2 * R + 2)
                up = Vector((0, 0, 1)) if abs(d.z) < 0.999 else Vector((0, 1, 0))
                cam.rotation_euler = (-d).to_track_quat("-Z", "Y").to_euler() if abs(d.z) < 0.999 else \
                    Matrix(((1, 0, 0), (0, 1, 0), (0, 0, 1))).to_euler()
                scene.frame_current = k + 1
                bpy.ops.render.render(write_still=False)
            log(name, "row", j + 1, "/", G)
        meta_all[name] = dict(lo=tuple(lo), hi=tuple(hi), center=tuple(ctr), radius=R, base=tuple(base_point(lo, hi)),
                              cam_dist=2 * R + 2, grid=G, px=PX, dirs=dirs, mesh_instances=n_inst, proto_tris=tris,
                              src=sp["src"], made=time.strftime("%Y-%m-%d %H:%M:%S"))
        json.dump(meta_all[name], open(os.path.join(fdir, "meta.json"), "w"), indent=1)
        log("baked", name, "R", round(R, 2), "h", round(hi.z - lo.z, 2))
        for o in list(col.objects):
            pass
    return meta_all


# ---- reference scenes (full meshes) -------------------------------------------------------------------------------
def scenes():
    scene = bpy.context.scene
    gpu_setup(scene)
    scene.render.film_transparent = False
    scene.cycles.use_adaptive_sampling = True
    scene.cycles.use_denoising = True
    scene.cycles.max_bounces = 4
    scene.cycles.diffuse_bounces = 2
    scene.cycles.transparent_max_bounces = 16
    scene.view_settings.view_transform = "Standard"
    scene.render.image_settings.file_format = "PNG"
    sky = JOB["sky"]; sun = JOB["sun"]
    w = bpy.data.worlds.new("W"); scene.world = w; w.use_nodes = True
    bg = w.node_tree.nodes["Background"]; bg.inputs[0].default_value = (*sky["rgb"], 1); bg.inputs[1].default_value = 1.0
    sd = bpy.data.lights.new("S", "SUN"); sd.energy = sun["strength"]; sd.color = sun["rgb"]; sd.angle = math.radians(1.5)
    so = bpy.data.objects.new("S", sd); scene.collection.objects.link(so)
    az, el = math.radians(sun["az"]), math.radians(sun["el"])
    L = Vector((math.cos(el) * math.cos(az), math.cos(el) * math.sin(az), math.sin(el)))
    so.rotation_euler = (-L).to_track_quat("-Z", "Y").to_euler()
    # ground
    gm = bpy.data.materials.new("Ground"); gm.use_nodes = True
    gm.node_tree.nodes["Principled BSDF"].inputs["Base Color"].default_value = (*JOB["ground_rgb"], 1)
    gm.node_tree.nodes["Principled BSDF"].inputs["Roughness"].default_value = 1.0
    bpy.ops.mesh.primitive_plane_add(size=4000)
    gp = bpy.context.active_object; gp.data.materials.append(gm)
    used = {t[0] for s in JOB["scenes"] for t in s["trees"]}
    need = [k for k in JOB["species"] if k in used]     # job order (= bake order): Blender 4.5 USD face-set import crashed
                                                        # on oak after alder + fir (assign_facesets_to_material_indices)
    cols = {}
    for name in need:
        col, lo, hi, _n, _t = import_species(name, JOB["species"][name], os.path.join(OUT, "_tmp"))
        col.instance_offset = base_point(lo, hi)
        cols[name] = col
    for col in cols.values():                                                # rendered only through instances
        bpy.context.view_layer.layer_collection.children[col.name].exclude = True
    bpy.context.view_layer.active_layer_collection = bpy.context.view_layer.layer_collection
    cam_d = bpy.data.cameras.new("C"); cam_d.sensor_fit = "HORIZONTAL"
    cam = bpy.data.objects.new("C", cam_d); scene.collection.objects.link(cam); scene.camera = cam
    holder = bpy.data.collections.new("Placed"); scene.collection.children.link(holder)
    os.makedirs(os.path.join(OUT, "real"), exist_ok=True)
    for sc in JOB["scenes"]:
        for o in list(holder.objects):
            bpy.data.objects.remove(o)
        for name, x, y, yaw, s in sc["trees"]:
            e = bpy.data.objects.new("I", None); e.instance_type = "COLLECTION"; e.instance_collection = cols[name]
            e.location = (x, y, 0); e.rotation_euler = (0, 0, math.radians(yaw)); e.scale = (s, s, s)
            holder.objects.link(e)
        gp.hide_render = not sc.get("ground", True)
        scene.render.film_transparent = not sc.get("ground", True)
        c = sc["cam"]
        cam.location = c["loc"]
        cam.rotation_euler = (Vector(c["at"]) - Vector(c["loc"])).to_track_quat("-Z", "Y").to_euler()
        cam_d.angle = math.radians(c["fov"])
        cam_d.clip_start = 0.1; cam_d.clip_end = 5000
        scene.render.resolution_x, scene.render.resolution_y = sc["res"]
        scene.cycles.samples = sc.get("spp", 128)
        scene.render.filepath = os.path.join(OUT, "real", sc["name"] + ".png")
        t1 = time.time()
        bpy.ops.render.render(write_still=True)
        log("scene", sc["name"], "trees", len(sc["trees"]), "s", round(time.time() - t1, 1))


bpy.ops.wm.read_factory_settings(use_empty=True)                          # no default cube / light / camera
if JOB.get("mode") == "bake":
    bake(JOB["bake"])
else:
    scenes()
log("done")
