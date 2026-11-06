"""Pilot body for the cockpit (Blender, background):
    blender -b <pilot .blend> -P pilot_blender.py -- [--out <dir>] [--preview]

Source model (NOT in this repo, third-party): "Low Poly Fighter Pilot (rigged)" by Erik Castillo (erik90mx), CC0 on
OpenGameArt (https://opengameart.org/content/low-poly-fighter-pilot-rigged), kept under C:/GyroSimParts/thirdparty/pilot/
(see SOURCE.md there). It already has a helmet with visor, oxygen mask + hose, flight suit, vest and an IK rig.

What this script does (all numbers in UE body cm, X fwd, Y right, Z up, eye (430, 0, 100) - cockpit layout.py):
  1. seats the rigged pilot: hips on the seat, spine reclined with the seat, hands on the stick / throttle grips (IK
     targets ControladorMuneca.R/L, fists closed), feet on the pedals (Pie.R/L), the design eye at layout.EYE;
  2. evaluates the posed meshes and splits them into BODY (everything below the collar) and HEAD (helmet, visor,
     mask, upper hose; origin = the eye, so Unreal can hang it on the view camera and it follows the head / HMD);
  3. body: one skinned mesh with a single root bone and morph targets for the controls (linear blend in Unreal):
     StickR / StickL (roll +-STICK_DEG), StickF / StickB (pitch), ThrF / ThrB (throttle +-THR_DEG from the middle),
     RudR / RudL (right pedal forward = left pedal back, +-PEDAL_CM), ToeL / ToeR (toe brakes TOE_DEG);
  4. material slots by region: PL_Suit (flight suit), PL_GSuit (G-suit trousers), PL_Harness (vest / harness),
     PL_Glove, PL_Boot, PL_Helmet, PL_Visor, PL_Mask, PL_Hose;
  5. writes pilot_body.fbx, pilot_head.fbx, pilot_manifest.json (+ preview PNGs with --preview) to --out
     (default C:/GyroSimParts/thirdparty/pilot/out - generated from third-party data, kept out of git).
"""
import bpy, json, math, os, sys, time
import bmesh
from mathutils import Vector, Matrix

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "cockpit"))
import layout as L            # noqa: E402

ARGS = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
OUT = ARGS[ARGS.index("--out") + 1] if "--out" in ARGS else "C:/GyroSimParts/thirdparty/pilot/out"
PREVIEW = "--preview" in ARGS
os.makedirs(OUT, exist_ok=True)
V = Vector

# ---- controls (must match sim_client: STICK_ROLL / STICK_PITCH 12.75, THR_SWING 30, PEDAL_CM 4, TOE_DEG 18) ----------
STICK_DEG, THR_DEG, PEDAL_CM, TOE_DEG = 12.75, 30.0, 4.0, 18.0
STICK_PIVOT = V(L.STICK_PIVOT)
STICK_GRIP = STICK_PIVOT + V((0.0, 0.0, (L.STICK_GRIP_Z0 + L.STICK_GRIP_Z1) / 2 - STICK_PIVOT.z + 1.0))
THR_PIVOT = V(L.THR_PIVOT)
THR_R = (L.THR_GRIP_Z0 + L.THR_GRIP_Z1) / 2 - THR_PIVOT.z           # grip centre distance from the throttle pivot
PEDAL = {s: V((L.PEDAL_HINGE_X, s * L.PEDAL_Y, L.PEDAL_HINGE_Z)) for s in (-1, 1)}
EYE = V(L.EYE)

# ---- source rig ---------------------------------------------------------------------------------------------------
SCENE = "Escena"
ARM = "Esqueleto Univers.000"
S = 9.0                         # cm per source unit (source pilot ~21.7 units tall -> ~1.95 m incl. helmet / boots)
EYE_SRC = V((0.0, -1.25, 8.7))  # design eye in the source rest pose (between the eyes, behind the visor) - estimate
HEAD_BONES = ("Cabeza", "casco", "Lente", "Quijada", "Bone.006")


def src_to_ue(p, eye_src):
    """source world (pilot faces -Y, right hand +X, Z up) -> UE body cm, the source eye mapped to EYE."""
    d = p - eye_src
    return V((EYE.x - d.y * S, d.x * S, EYE.z + d.z * S))


def ue_to_src(q, eye_src):
    return V((eye_src.x + (q.y) / S, eye_src.y - (q.x - EYE.x) / S, eye_src.z + (q.z - EYE.z) / S))


def ue_to_export(q):
    """UE body cm -> Blender export space (same convention as cockpit/model_blender.py: (x, -y, z) / 100, faces reversed)."""
    return V((q.x / 100.0, -q.y / 100.0, q.z / 100.0))


sc = bpy.context.scene            # run with -S Escena
assert sc.name == SCENE, "start Blender with -S %s" % SCENE
A = bpy.data.objects[ARM]
MW = A.matrix_world
MWI = MW.inverted()


def pb(n):
    return A.pose.bones[n]


def set_world_loc(name, p_src, rot=None):
    """put pose bone `name` at source-world point p_src; rot = armature-space 3x3 (default: its rest orientation)."""
    b = pb(name)
    m = MWI @ Matrix.Translation(p_src)
    r = (rot.normalized() if rot is not None else b.bone.matrix_local.to_3x3().normalized()).to_4x4()
    b.matrix = Matrix.Translation(m.to_translation()) @ r
    bpy.context.view_layer.update()


def head_eye_world():
    """current source-world position of the design eye (rides on the Cabeza bone)."""
    b = pb("Cabeza")
    rest = A.data.bones["Cabeza"].matrix_local
    local = rest.inverted() @ (MWI @ EYE_SRC)
    return MW @ (b.matrix @ local)


def reset_pose():
    for b in A.pose.bones:
        b.location = (0, 0, 0)
        b.rotation_quaternion = (1, 0, 0, 0)
        b.rotation_euler = (0, 0, 0)
        b.scale = (1, 1, 1)
    bpy.context.view_layer.update()


# hand frames. Source rest (T-pose): wrist -> knuckles along the arm (right +x_src = UE +y, left -x_src = UE -y), palm
# down, thumb forward. On the grips (both hands): wrist -> knuckles forward (+x UE), palm facing left (-y UE, the right
# hand wraps the centre stick from its right side, the left hand the throttle grip from inboard), thumb up (+z UE).
# R_UE maps the rest hand axes to those (rows of a 3x3 in UE body space); HAND_TILT pitches the hand forward (deg).
R_UE = {"R": Matrix(((0, 1, 0), (0, 0, 1), (1, 0, 0))), "L": Matrix(((0, -1, 0), (0, 0, 1), (1, 0, 0)))}
M_SU = Matrix(((0, -1, 0), (1, 0, 0), (0, 0, 1)))       # source direction -> UE direction (see src_to_ue)
HAND_TILT = {"R": 15.0, "L": 10.0}


def hand_rot(side, extra_ue=Matrix.Identity(3)):
    b = A.data.bones["ControladorMuneca." + side]
    r0 = (MW.to_3x3() @ b.matrix_local.to_3x3()).normalized()                 # rest frame in source world
    tilt = Matrix.Rotation(math.radians(HAND_TILT[side]), 3, V((0, 1, 0)))    # UE: top of the hand forward
    R = M_SU.transposed() @ (extra_ue @ tilt @ R_UE[side]) @ M_SU               # UE rotation -> source world
    return MWI.to_3x3() @ (R @ r0)


def ue_rot_about(axis_ue, deg):
    """rotation in UE body space -> the same rotation in source space (3x3)."""
    a = V(axis_ue)
    a_src = V((a.y, -a.x, a.z))           # direction mapping UE -> source (see src_to_ue)
    return Matrix.Rotation(math.radians(deg), 3, a_src.normalized())


def rotate_world(name, R3):
    """rotate pose bone `name` about its head by the source-world rotation R3 (independent of the bone roll)."""
    b = pb(name)
    M = b.matrix.copy()
    h = M.to_translation()
    Ra = (MWI.to_3x3() @ R3 @ MW.to_3x3()).to_4x4()
    b.matrix = Matrix.Translation(h) @ Ra @ Matrix.Translation(-h) @ M
    bpy.context.view_layer.update()


SPINE_RECLINE, NECK_FWD = -14.0, -10.0


def pose(ctrl, eye_src):
    """ctrl: sr, sf (-1..1), thr (0..1), rud (-1..1), brk_l, brk_r (0..1). Places hips / spine / targets."""
    reset_pose()
    # spine: recline with the seat back (the source stands upright)
    rotate_world("Abdomen", ue_rot_about((0, 1, 0), -SPINE_RECLINE))     # pitch back about the pilot's left-right axis
    rotate_world("Cuello", ue_rot_about((0, 1, 0), NECK_FWD))           # head back upright
    hip_ue = V(HIP_UE)
    for _ in range(3):                    # hips placed so the posed eye lands on EYE
        set_world_loc("CaderA", ue_to_src(hip_ue, eye_src))
        e = src_to_ue(head_eye_world(), eye_src)
        hip_ue += EYE - e
        hip_ue.z = max(hip_ue.z, HIP_MIN_Z)
        hip_ue.y = 0.0                    # body on the centre line (the source head is turned a little)
    POSE_INFO.update(hip=list(hip_ue), eye_err=list(EYE - src_to_ue(head_eye_world(), eye_src)))
    # hands: stick grip rotated with the stick (roll about x, pitch about y), throttle grip on its arc
    # geometric control directions (sim_client converts its actor rotations to these weights): sr +1 = stick top to
    # the right (+y), sf +1 = stick top forward (+x), thr 1 = throttle grip 30 deg forward of the middle
    rs = Matrix.Rotation(math.radians(-STICK_DEG * ctrl["sr"]), 3, 'X') @ Matrix.Rotation(math.radians(STICK_DEG * ctrl["sf"]), 3, 'Y')
    g = STICK_PIVOT + rs @ (STICK_GRIP - STICK_PIVOT)
    set_world_loc("ControladorMuneca.R", ue_to_src(g + rs @ V(HAND_OFF["R"]), eye_src), hand_rot("R", rs))
    th = math.radians(THR_DEG * (2.0 * ctrl["thr"] - 1.0))
    rt = Matrix.Rotation(th, 3, 'Y')
    gt = THR_PIVOT + rt @ V((0.0, 0.0, THR_R))
    set_world_loc("ControladorMuneca.L", ue_to_src(gt + rt @ V(HAND_OFF["L"]), eye_src), hand_rot("L", rt))
    # elbow poles: out to the side, below and behind the elbows
    set_world_loc("Codo.R", ue_to_src(V((400.0, 45.0, 40.0)), eye_src))
    set_world_loc("Codo.L", ue_to_src(V((400.0, -45.0, 40.0)), eye_src))
    # feet on the pedals (rudder: right pedal forward = +rud), toe brakes pitch the foot about the heel
    for s, side, bk in ((1, "R", "brk_r"), (-1, "L", "brk_l")):
        p = PEDAL[s] + V((s * PEDAL_CM * ctrl["rud"], 0.0, 0.0)) + V(FOOT_OFF)
        r = ue_rot_about((0, 1, 0), -(FOOT_PITCH - TOE_DEG * ctrl[bk]))      # toes up on the plate, brake = toes forward
        b = A.data.bones["Pie." + side]
        set_world_loc("Pie." + side, ue_to_src(p, eye_src), MWI.to_3x3() @ r @ MW.to_3x3() @ b.matrix_local.to_3x3())
        set_world_loc("Rodilla." + side, ue_to_src(V((520.0, s * 18.0, 60.0)), eye_src))
    # fists: close the fingers (CerrarMano local X rotation drives the finger action, -60 = closed)
    for side in ("R", "L"):
        n = "CerrarMano." + side
        if n in A.pose.bones:
            pb(n).rotation_mode = 'XYZ'
            pb(n).rotation_euler = (math.radians(FIST_DEG), 0.0, 0.0)
    bpy.context.view_layer.update()


HIP_UE = (418.0, 0.0, 36.0)
POSE_INFO = {}
HIP_MIN_Z = L.SEAT_Z + 8.0
HAND_OFF = {"R": (-8.0, 3.0, -1.0), "L": (-8.0, 3.0, -1.0)}    # wrist target relative to the grip centre (cm)
FOOT_OFF = (-8.0, 0.0, 2.0)                                   # Pie (heel controller) relative to the pedal hinge
FOOT_PITCH = 35.0
FIST_DEG = -55.0
NEUTRAL = dict(sr=0.0, sf=0.0, thr=0.5, rud=0.0, brk_l=0.0, brk_r=0.0)
MORPHS = {"StickR": dict(sr=1.0), "StickL": dict(sr=-1.0), "StickF": dict(sf=1.0), "StickB": dict(sf=-1.0),
          "ThrF": dict(thr=1.0), "ThrB": dict(thr=0.0), "RudR": dict(rud=1.0), "RudL": dict(rud=-1.0),
          "ToeL": dict(brk_l=1.0), "ToeR": dict(brk_r=1.0)}


# ---- collect the posed meshes ----------------------------------------------------------------------------------------
def visible_meshes():
    return [o for o in sc.objects if o.type == "MESH" and o.visible_get() and not o.hide_render and len(o.data.polygons) > 0]


def grab(eye_src):
    """evaluated (posed) geometry of every visible mesh -> list of (obj name, verts UE, faces, face materials)."""
    dg = bpy.context.evaluated_depsgraph_get()
    out = []
    for o in visible_meshes():
        ev = o.evaluated_get(dg)
        me = ev.to_mesh()
        mw = ev.matrix_world
        vs = [src_to_ue(mw @ v.co, eye_src) for v in me.vertices]
        fs = [list(p.vertices) for p in me.polygons]
        out.append((o.name, vs, fs))
        ev.to_mesh_clear()
    return out


SLOT_COLORS = {"PL_Suit": (0.10, 0.11, 0.07), "PL_GSuit": (0.07, 0.08, 0.05), "PL_Harness": (0.03, 0.03, 0.03),
               "PL_Glove": (0.02, 0.018, 0.015), "PL_Boot": (0.015, 0.015, 0.015), "PL_Helmet": (0.55, 0.56, 0.55),
               "PL_Visor": (0.02, 0.02, 0.025), "PL_Mask": (0.06, 0.065, 0.05), "PL_Hose": (0.03, 0.03, 0.03)}


def classify(name, f_center, head):
    """material slot for a face (by source object and position, UE cm)."""
    n = name.lower()
    if n.startswith("mano"):
        return "PL_Glove"
    if n.startswith("tubo"):
        return "PL_Hose"
    if head:
        if n.startswith("sphere") and f_center.x > EYE.x - 1.0 and f_center.z < EYE.z + 6.0 and f_center.z > EYE.z - 6.0:
            return "PL_Visor"
        if f_center.z < EYE.z - 4.0 and f_center.x > EYE.x - 2.0:
            return "PL_Mask"
        return "PL_Helmet"
    if n.startswith("pecho") or n.startswith("cube") or n.startswith("plane"):
        return "PL_Harness"
    if f_center.z < BOOT_Z:
        return "PL_Boot"
    if f_center.z < GSUIT_Z1 and f_center.x > HIP_X_MIN:
        return "PL_GSuit"
    return "PL_Suit"


BOOT_Z = -2.0
GSUIT_Z1 = 50.0
HIP_X_MIN = 400.0
HOSE_HEAD_R = 26.0
NECK_Z = 83.0                     # below this: body (relative to the posed eye at z 100)
HEAD_R = 17.0                     # head / helmet sphere radius around HEAD_C


def is_head(p):
    """helmet, face, mask: an ellipsoid around the eye (the mask reaches ~15 cm forward of the eye), above the collar."""
    d = p - (EYE + V((-4.0, 0.0, 0.0)))
    return p.z > NECK_Z and (d.x / 22.0) ** 2 + (d.y / 17.0) ** 2 + (d.z / 24.0) ** 2 < 1.0


HEAD_C = EYE + V((-8.0, 0.0, 3.0))


def build(eye_src):
    pose(NEUTRAL, eye_src)
    base = grab(eye_src)
    keys = {}
    for k, c in MORPHS.items():
        cc = dict(NEUTRAL)
        cc.update(c)
        pose(cc, eye_src)
        keys[k] = grab(eye_src)
    pose(NEUTRAL, eye_src)
    # split faces into body / head
    body = dict(V=[], F=[], M=[], K={k: [] for k in MORPHS})
    head = dict(V=[], F=[], M=[])
    slots_b, slots_h = [], []
    for oi, (name, vs, fs) in enumerate(base):
        bmap, hmap = {}, {}
        for f in fs:
            c = sum((vs[i] for i in f), V()) / len(f)
            if name.lower().startswith("tubo"):
                # oxygen hose: the part at the mask rides with the head, the rest stays on the chest (seen below the
                # chin in first person; a hose starting at the eye filled the look-down view)
                hd = (c - EYE).length < HOSE_HEAD_R
            else:
                hd = is_head(c) or (name.lower().startswith("sphere") and c.z > NECK_Z)
            tgt, mp, slots = (head, hmap, slots_h) if hd else (body, bmap, slots_b)
            idx = []
            for i in f:
                if i not in mp:
                    mp[i] = len(tgt["V"])
                    tgt["V"].append(vs[i])
                    if tgt is body:
                        for k in MORPHS:
                            body["K"][k].append(keys[k][oi][1][i])
                idx.append(mp[i])
            sl = classify(name, c, hd)
            if sl not in slots:
                slots.append(sl)
            tgt["F"].append(idx)
            tgt["M"].append(slots.index(sl))
    return body, head, slots_b, slots_h


def make_mesh(name, data, slots, origin, keys=None):
    me = bpy.data.meshes.new(name)
    vs = [ue_to_export(v - origin) for v in data["V"]]
    me.from_pydata(vs, [], [f[::-1] for f in data["F"]])     # (x, -y, z) mirror -> reverse the winding
    me.update()
    for sl in slots:
        m = bpy.data.materials.get(sl) or bpy.data.materials.new(sl)
        c = SLOT_COLORS.get(sl, (0.5, 0.5, 0.5))
        m.diffuse_color = (c[0], c[1], c[2], 1.0)
        me.materials.append(m)
    for p, mi in zip(me.polygons, data["M"]):
        p.material_index = mi
        p.use_smooth = True
    ob = bpy.data.objects.new(name, me)
    out_sc.collection.objects.link(ob)
    if keys:
        ob.shape_key_add(name="Basis")
        for k, kv in keys.items():
            sk = ob.shape_key_add(name=k)
            for i, v in enumerate(kv):
                sk.data[i].co = ue_to_export(v - origin)
    return ob


def export_fbx(objs, path, skeletal):
    bpy.ops.object.select_all(action='DESELECT')
    for o in objs:
        o.select_set(True)
    bpy.context.view_layer.objects.active = objs[0]
    bpy.ops.export_scene.fbx(filepath=path, use_selection=True, axis_forward='X', axis_up='Z', apply_unit_scale=True, global_scale=1.0,
                             apply_scale_options='FBX_SCALE_NONE', bake_space_transform=not skeletal, mesh_smooth_type='FACE',
                             use_mesh_modifiers=False, use_tspace=False, add_leaf_bones=False,
                             object_types={'MESH', 'ARMATURE'} if skeletal else {'MESH'}, use_armature_deform_only=True,
                             bake_anim=False, path_mode='STRIP')


t0 = time.time()
eye_src = V(EYE_SRC)
body, head, slots_b, slots_h = build(eye_src)
print("[pilot] pose", {k: [round(x, 1) for x in v] for k, v in POSE_INFO.items()})
near = [v for v in body["V"] if (v - EYE).length < 25.0]
if near:
    print("[pilot] body verts within 25 cm of the eye:", len(near), "x", round(min(v.x for v in near), 1), round(max(v.x for v in near), 1),
          "z", round(min(v.z for v in near), 1), round(max(v.z for v in near), 1))
print("[pilot] body verts %d faces %d slots %s | head verts %d faces %d slots %s" % (len(body["V"]), len(body["F"]), slots_b,
                                                                                    len(head["V"]), len(head["F"]), slots_h))
# write into the same scene (background Blender has no window to switch scenes); the source meshes stay out of the
# export (selection) and out of the previews (hide_render)
SRC_MESHES = visible_meshes()
out_sc = sc
ob_b = make_mesh("pilot_body", body, slots_b, V((0, 0, 0)), body["K"])
ob_h = make_mesh("pilot_head", head, slots_h, EYE)
arm_d = bpy.data.armatures.new("pilot_rig")
arm = bpy.data.objects.new("pilot_rig", arm_d)
out_sc.collection.objects.link(arm)
bpy.context.view_layer.objects.active = arm
bpy.ops.object.mode_set(mode='EDIT')
eb = arm_d.edit_bones.new("root")
eb.head, eb.tail = (4.2, 0.0, 0.3), (4.2, 0.0, 0.5)
bpy.ops.object.mode_set(mode='OBJECT')
ob_b.parent = arm
vg = ob_b.vertex_groups.new(name="root")
vg.add(list(range(len(body["V"]))), 1.0, 'REPLACE')
mod = ob_b.modifiers.new("arm", 'ARMATURE')
mod.object = arm
export_fbx([arm, ob_b], os.path.join(OUT, "pilot_body.fbx"), True)
export_fbx([ob_h], os.path.join(OUT, "pilot_head.fbx"), False)
man = dict(made=time.strftime("%Y-%m-%d %H:%M:%S"), frame="UE body cm, X fwd, Y right, Z up; head origin = eye", eye=list(EYE),
           scale_cm_per_unit=S, morphs=list(MORPHS), controls=dict(stick_deg=STICK_DEG, thr_deg=THR_DEG, pedal_cm=PEDAL_CM, toe_deg=TOE_DEG),
           slots_body=slots_b, slots_head=slots_h, colors=SLOT_COLORS, head_center=list(HEAD_C), head_r=HEAD_R,
           body_verts=len(body["V"]), body_faces=len(body["F"]), head_faces=len(head["F"]),
           source="Low Poly Fighter Pilot (rigged), Erik Castillo, CC0, opengameart.org/content/low-poly-fighter-pilot-rigged")
json.dump(man, open(os.path.join(OUT, "pilot_manifest.json"), "w"), indent=1)
print("[pilot] done %.1f s -> %s" % (time.time() - t0, OUT))

if PREVIEW:
    # cockpit context: shell + controls from Art/Cockpit (same export space)
    ck = os.path.normpath(os.path.join(HERE, "..", "..", "Art", "Cockpit"))
    cman = json.load(open(os.path.join(ck, "manifest.json")))
    for n, piv in ((("ck_shell", None),) if "--shell" in ARGS else ()) + (("ck_stick", "StickPivot"), ("ck_throttle", "ThrottlePivot"),
                                                                       ("ck_pedal_l", "PedalL"), ("ck_pedal_r", "PedalR")):
        before = set(bpy.data.objects)
        bpy.ops.import_scene.fbx(filepath=os.path.join(ck, n + ".fbx"))
        for o in set(bpy.data.objects) - before:
            if piv:
                pv = cman["pivots"][piv]
                o.location = (pv[0] / 100, -pv[1] / 100, pv[2] / 100)
    for o in SRC_MESHES:
        o.hide_render = True
    ob_h.location = ue_to_export(EYE)
    cam = bpy.data.objects.new("cam", bpy.data.cameras.new("cam"))
    out_sc.collection.objects.link(cam)
    out_sc.camera = cam
    out_sc.render.engine = "BLENDER_WORKBENCH"
    out_sc.display.shading.color_type = 'MATERIAL'
    out_sc.render.resolution_x, out_sc.render.resolution_y = 1000, 700
    for tag, c_ue, t_ue, lens in (("side", (450, -300, 50), (450, 0, 50), 30), ("eye", (430, 0, 100), (480, 0, 40), 16),
                                  ("front", (650, 0, 80), (440, 0, 55), 30), ("top", (450, 0, 330), (450, 0, 50), 30),
                                  ("stick", (500, 45, 75), (462, 0, 52), 35), ("throttle", (470, 10, 85), (441, -32, 55), 35),
                                  ("feet", (520, -60, 30), (480, 0, -5), 30)):
        c, t = ue_to_export(V(c_ue)), ue_to_export(V(t_ue))
        cam.location = c
        cam.rotation_euler = (t - c).to_track_quat('-Z', 'Y').to_euler()
        cam.data.lens = lens
        cam.data.clip_start = 0.02
        ob_h.hide_render = tag == "eye"
        out_sc.render.filepath = os.path.join(OUT, "preview_%s.png" % tag)
        bpy.ops.render.render(write_still=True, scene=out_sc.name)
    print("[pilot] previews written")
