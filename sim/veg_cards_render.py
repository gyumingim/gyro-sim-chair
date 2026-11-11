"""Headless Blender previews of the leaf-card trees (sim/veg_cards.py glTFs) - no Unreal, no window.

    blender -b --factory-startup -P sim/veg_cards_render.py -- CARDS_DIR OUT_DIR [shot ...]
    (run through sim/impostor/run_locked.ps1 so it holds C:\\GyroSimTiles\\ue_offscreen.lock)

Shots: pine_one, pine_16, oak_one, oak_16, forest_100, forest_300, forest_800, base_100, base_300, base_800.
forest_* = ~400 trees (70 % pine, 30 % oak) on a 110 m x 110 m slope (5.5 m spacing); base_* = the same positions with the current game
proxy (veg_shape prototypes, vertex colour x AO as M_GyroTree2 approx). Cycles CPU, sun + gradient sky, no haze.
Materials follow the glTF: foliage = atlas rgb x COLOR_0, alpha MASK 0.5, back faces culled (Geometry.Backfacing ->
transparent, like a single-sided material); bark / baseline = COLOR_0. Foliage adds 20 % translucency (UE two-sided
foliage approx). Writes OUT_DIR/<shot>.png and OUT_DIR/render.json (camera, fov, time per shot).
"""
import json, math, os, sys, time
import bpy

argv = sys.argv[sys.argv.index("--") + 1:]
CARDS, OUT = argv[0], argv[1]
SHOTS = argv[2:] or ["pine_one", "pine_16", "oak_one", "oak_16", "forest_100", "forest_300", "forest_800",
                     "base_100", "base_300", "base_800"]
os.makedirs(OUT, exist_ok=True)
META = json.load(open(os.path.join(CARDS, "cards.json")))
LOG = {"made": time.strftime("%Y-%m-%dT%H:%M:%S"), "cards": CARDS, "shots": {}}


def log(*a):
    print("[cards_render]", *a, flush=True)


# ---------------------------------------------------------------- scene setup ---------------------------------------------
bpy.ops.wm.read_factory_settings(use_empty=True)
sc = bpy.context.scene
sc.render.engine = "CYCLES"
sc.cycles.device = "CPU"
sc.render.threads_mode = "FIXED"
sc.render.threads = 12
sc.cycles.samples = 40
sc.cycles.use_adaptive_sampling = True
sc.cycles.use_denoising = True
sc.cycles.max_bounces = 4
sc.cycles.diffuse_bounces = 2
sc.cycles.transparent_max_bounces = 48
sc.render.resolution_x, sc.render.resolution_y = 1280, 720
sc.view_settings.view_transform = "AgX"
sc.view_settings.exposure = 0.6; sc.view_settings.look = "AgX - Medium High Contrast"

world = bpy.data.worlds.new("w"); sc.world = world; world.use_nodes = True
wn = world.node_tree.nodes; wn.clear()
sky = wn.new("ShaderNodeTexGradient")                         # simple sky: horizon haze -> blue zenith
ramp = wn.new("ShaderNodeValToRGB")
ramp.color_ramp.elements[0].color = (0.62, 0.68, 0.74, 1); ramp.color_ramp.elements[1].color = (0.30, 0.45, 0.70, 1)
tc = wn.new("ShaderNodeTexCoord"); sep = wn.new("ShaderNodeSeparateXYZ")
world.node_tree.links.new(tc.outputs["Generated"], sep.inputs[0]); world.node_tree.links.new(sep.outputs[2], ramp.inputs[0])
bg = wn.new("ShaderNodeBackground"); bg.inputs[1].default_value = 0.9
wo = wn.new("ShaderNodeOutputWorld")
world.node_tree.links.new(ramp.outputs[0], bg.inputs[0]); world.node_tree.links.new(bg.outputs[0], wo.inputs[0])
sun_d = bpy.data.lights.new("sun", "SUN"); sun_d.energy = 4.0; sun_d.angle = math.radians(1.0)
sun = bpy.data.objects.new("sun", sun_d); sc.collection.objects.link(sun)
sun.rotation_euler = (math.radians(90 - 38), 0, math.radians(135 + 180 - 90))

SLOPE = math.radians(14)                                       # hillside rises towards +y


def ground_z(x, y):
    return math.tan(SLOPE) * y + 1.5 * math.sin(x / 23.0) * math.cos(y / 31.0)


def make_ground():
    me = bpy.data.meshes.new("ground")
    N, L = 120, 1600.0
    vs, fs = [], []
    for j in range(N + 1):
        for i in range(N + 1):
            x, y = -L / 2 + L * i / N, -L / 2 + L * j / N
            vs.append((x, y, ground_z(x, y)))
    for j in range(N):
        for i in range(N):
            a = j * (N + 1) + i
            fs.append((a, a + 1, a + N + 2, a + N + 1))
    me.from_pydata(vs, [], fs); me.update()
    for p in me.polygons:
        p.use_smooth = True
    ob = bpy.data.objects.new("ground", me); sc.collection.objects.link(ob)
    m = bpy.data.materials.new("ground"); m.use_nodes = True
    nt = m.node_tree; bsdf = nt.nodes["Principled BSDF"]
    noise = nt.nodes.new("ShaderNodeTexNoise"); noise.inputs["Scale"].default_value = 0.08
    ramp = nt.nodes.new("ShaderNodeValToRGB")
    ramp.color_ramp.elements[0].color = (0.045, 0.040, 0.024, 1); ramp.color_ramp.elements[1].color = (0.075, 0.075, 0.040, 1)
    nt.links.new(noise.outputs[0], ramp.inputs[0]); nt.links.new(ramp.outputs[0], bsdf.inputs["Base Color"])
    bsdf.inputs["Roughness"].default_value = 0.95
    ob.data.materials.append(m)
    return ob


make_ground()


# ---------------------------------------------------------------- tree prototypes ---------------------------------------------
def foliage_material(img, attr):
    m = bpy.data.materials.new("cards"); m.use_nodes = True
    nt = m.node_tree; N = nt.nodes; Lk = nt.links
    bsdf = N["Principled BSDF"]; out = N["Material Output"]
    tex = N.new("ShaderNodeTexImage"); tex.image = img; tex.interpolation = "Linear"; tex.extension = "CLIP"
    ca = N.new("ShaderNodeVertexColor"); ca.layer_name = attr
    mul = N.new("ShaderNodeMix"); mul.data_type = "RGBA"; mul.blend_type = "MULTIPLY"; mul.inputs[0].default_value = 1.0
    Lk.new(tex.outputs["Color"], mul.inputs[6]); Lk.new(ca.outputs["Color"], mul.inputs[7])
    Lk.new(mul.outputs[2], bsdf.inputs["Base Color"])
    bsdf.inputs["Roughness"].default_value = 0.85
    tr = N.new("ShaderNodeBsdfTranslucent"); Lk.new(mul.outputs[2], tr.inputs[0])
    mixT = N.new("ShaderNodeMixShader"); mixT.inputs[0].default_value = 0.2
    Lk.new(bsdf.outputs[0], mixT.inputs[1]); Lk.new(tr.outputs[0], mixT.inputs[2])
    gt = N.new("ShaderNodeMath"); gt.operation = "GREATER_THAN"; gt.inputs[1].default_value = 0.5   # alphaMode MASK 0.5
    Lk.new(tex.outputs["Alpha"], gt.inputs[0])
    geo = N.new("ShaderNodeNewGeometry")
    sub = N.new("ShaderNodeMath"); sub.operation = "SUBTRACT"; sub.use_clamp = True
    Lk.new(gt.outputs[0], sub.inputs[0]); Lk.new(geo.outputs["Backfacing"], sub.inputs[1])      # single-sided
    trn = N.new("ShaderNodeBsdfTransparent")
    mixA = N.new("ShaderNodeMixShader")
    Lk.new(sub.outputs[0], mixA.inputs[0]); Lk.new(trn.outputs[0], mixA.inputs[1]); Lk.new(mixT.outputs[0], mixA.inputs[2])
    Lk.new(mixA.outputs[0], out.inputs["Surface"])
    return m


def vcol_material(attr, name):
    m = bpy.data.materials.new(name); m.use_nodes = True
    nt = m.node_tree; bsdf = nt.nodes["Principled BSDF"]
    ca = nt.nodes.new("ShaderNodeVertexColor"); ca.layer_name = attr
    nt.links.new(ca.outputs["Color"], bsdf.inputs["Base Color"])
    bsdf.inputs["Roughness"].default_value = 0.9
    return m


ATLAS = bpy.data.images.load(os.path.join(CARDS, "atlas.png")); ATLAS.alpha_mode = "STRAIGHT"
PROTO = {}
hidden = bpy.data.collections.new("protos")


def proto(name):
    if name in PROTO:
        return PROTO[name]
    before = set(bpy.data.objects)
    bpy.ops.import_scene.gltf(filepath=os.path.join(CARDS, name + ".glb"))
    new = [o for o in bpy.data.objects if o not in before]
    ob = [o for o in new if o.type == "MESH"][0]
    for o in new:
        for c in list(o.users_collection):
            c.objects.unlink(o)
    me = ob.data
    attr = me.color_attributes[0].name if me.color_attributes else "Color"
    fol = foliage_material(ATLAS, attr)
    for i, ms in enumerate(me.materials):
        nm = ms.name if ms else ""
        if "foliage" in nm:
            me.materials[i] = fol
        else:
            me.materials[i] = vcol_material(attr, "bark")
    ob.matrix_world = __import__("mathutils").Matrix.Identity(4)
    PROTO[name] = ob
    return ob


placed = []


def place(name, x, y, yaw, s=1.0, z=None):
    src = proto(name)
    o = src.copy(); o.data = src.data
    sc.collection.objects.link(o)
    o.location = (x, y, ground_z(x, y) - 0.1 if z is None else z)
    o.rotation_euler = (0, 0, yaw)
    o.scale = (s, s, s)
    placed.append(o)
    return o


def clear():
    for o in placed:
        bpy.data.objects.remove(o, do_unlink=True)
    placed.clear()


def camera(loc, look, fov_deg):
    import mathutils
    cd = bpy.data.cameras.new("cam"); cd.lens_unit = "FOV"; cd.angle = math.radians(fov_deg); cd.sensor_fit = "HORIZONTAL"
    cd.clip_start = 0.5; cd.clip_end = 5000
    co = bpy.data.objects.new("cam", cd); sc.collection.objects.link(co)
    co.location = loc
    d = mathutils.Vector(look) - mathutils.Vector(loc)
    co.rotation_euler = d.to_track_quat("-Z", "Y").to_euler()
    sc.camera = co
    return co


def render(shot, cam_info):
    t0 = time.time()
    sc.render.filepath = os.path.join(OUT, shot + ".png")
    bpy.ops.render.render(write_still=True)
    LOG["shots"][shot] = dict(cam_info, sec=round(time.time() - t0, 1), trees=len(placed))
    log(shot, "%.1f s" % (time.time() - t0), len(placed), "trees")
    json.dump(LOG, open(os.path.join(OUT, "render.json"), "w"), indent=1)


PINES = [t["name"] for t in META["trees"] if t["species"] == "pine"]
OAKS = [t["name"] for t in META["trees"] if t["species"] == "oak"]


def rng(seed):
    import random
    return random.Random(seed)


def forest_positions():
    r = rng(11)
    pts = []
    # ~400 trees on a jittered grid, 110 m x 110 m, ~5.5 m spacing (closed canopy like the Busan slopes)
    n = 20
    for j in range(n):
        for i in range(n):
            x = -55 + (i + 0.5) * 110 / n + r.uniform(-2.0, 2.0)
            y = -55 + (j + 0.5) * 110 / n + r.uniform(-2.0, 2.0)
            pts.append((x, y, r.uniform(0, 2 * math.pi), r.uniform(0.8, 1.15), r.random() < 0.7, r.randrange(1000)))
    return pts


def group16(species, base):
    r = rng(5 if species == "pine" else 6)
    names = PINES if species == "pine" else OAKS
    for k in range(16):
        i, j = k % 4, k // 4
        place(names[k % len(names)], (i - 1.5) * 7.5 + r.uniform(-1.5, 1.5), (j - 1.5) * 7.5 + r.uniform(-1.5, 1.5),
              r.uniform(0, 2 * math.pi), r.uniform(0.85, 1.12))


for shot in SHOTS:
    clear()
    if shot in ("pine_one", "oak_one"):
        nm = PINES[0] if shot == "pine_one" else OAKS[0]
        place(nm, 0, 0, 0.6, z=ground_z(0, 0) - 0.1)
        H = [t for t in META["trees"] if t["name"] == nm][0]["H"]
        gz = ground_z(0, 0)
        dist = 3.0 * H
        info = dict(fov=40, dist=round(dist, 1), what=nm)
        camera((0, -dist, gz + H * 0.5 + 1.0), (0, 0, gz + H * 0.55), 40)
    elif shot in ("pine_16", "oak_16"):
        group16(shot[:-3], 0)
        info = dict(fov=50, dist=55, elev_deg=22)
        camera((0, -55, ground_z(0, 0) + 28), (0, 0, ground_z(0, 0) + 4), 50)
    else:
        kind, d = shot.split("_"); d = float(d)
        for x, y, yaw, s, is_pine, k in forest_positions():
            if kind == "base":
                place("baseline_pine" if is_pine else "baseline_oak", x, y, yaw, s)
            else:
                place(PINES[k % len(PINES)] if is_pine else OAKS[k % len(OAKS)], x, y, yaw, s)
        fov = min(70.0, math.degrees(2 * math.atan(70.0 / d)))
        el = math.radians(20)                                        # looking down 20 deg (aircraft over the slope)
        tgt = (0, 0, ground_z(0, 0) + 5)
        loc = (0, -d * math.cos(el), tgt[2] + d * math.sin(el))
        camera(loc, tgt, fov)
        info = dict(fov=round(fov, 1), dist=d, elev_deg=20, n=400)
    render(shot, info)
log("done")
