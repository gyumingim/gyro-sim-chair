"""Manny pilot with control morph targets (11-19): manny_posed.json -> manny_pilot.fbx (Blender, background).

    blender -b --factory-startup --python Scripts/pilot/manny_fbx.py -- [--dir MANNY_DIR] [--preview out.png]

Input  MANNY_DIR/manny_posed.json (Scripts/pilot/manny_pose.py: posed vertices in aircraft body cm, triangles, material
       class per triangle, dropped head triangles, collar cap, sparse control offsets "morphs").
Output MANNY_DIR/manny_pilot.fbx: one skinned mesh on a single bone, material slots PM_Suit / PM_GSuit / PM_Glove /
       PM_Boot / PM_Harness, shape keys StickR/L/F/B, ThrF/B, RudR/L (the names sim_client._pilot drives), box-projected
       UVs in metres (fabric normal map). Scripts/pilot/ue_manny.py import_fbx() turns it into
       /Game/ThirdParty/Mannequins/SKM_PilotMannyM. Derived from Epic content: MANNY_DIR is outside git.
"""
import json
import os
import sys
import time

import bpy
import bmesh

ARGS = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
DIR = ARGS[ARGS.index("--dir") + 1] if "--dir" in ARGS else os.environ.get("GYROSIM_MANNY_DIR", "C:/GyroSimParts/thirdparty/manny")
PREVIEW = ARGS[ARGS.index("--preview") + 1] if "--preview" in ARGS else None
SLOTS = ("PM_Suit", "PM_GSuit", "PM_Glove", "PM_Boot", "PM_Harness")
COLORS = ((0.10, 0.12, 0.07), (0.07, 0.085, 0.05), (0.02, 0.02, 0.02), (0.02, 0.02, 0.02), (0.05, 0.05, 0.05))

t0 = time.time()
D = json.load(open(os.path.join(DIR, "manny_posed.json"), encoding="utf-8"))
P, T, cls, drop = D["P"], D["T"], D["cls"], set(D["drop"])
ex = lambda p: (p[0] / 100.0, -p[1] / 100.0, p[2] / 100.0)          # UE body cm -> export space (cockpit / old pilot convention)
faces, fm = [], []
for ti, t in enumerate(T):
    if ti not in drop:
        faces.append(t[::-1])                                      # (x, -y, z) mirror -> reverse the winding
        fm.append(cls[ti])
for t in D.get("capT", []):
    faces.append(t["v"][::-1])
    fm.append(t["cls"])

# ---- suit details (11-19): raised patches laid on the posed body by ray casts (aircraft cm): chest zip, chest pockets,
# name tape, right thigh pocket + flap. Each new vertex copies the control offsets of the nearest body vertex.
from mathutils import Vector as _V
from mathutils.bvhtree import BVHTree
P = [list(q) for q in P]
NP0 = len(P)
_bvh = BVHTree.FromPolygons([_V(q) for q in P], [f[::-1] for f in faces])
SRC = {}                                   # new vertex -> body vertex it follows
PATCH_F = []                               # (first face, last face + 1, ray direction)


def _unit(v):
    v = _V(v)
    return v.normalized()


def patch(c, d, u, w, h, lift, slot, step=1.0, rim=0.35, reach=14.0):
    """rectangle w x h (cm) centred on the ray from c along d, u = its long axis (made perpendicular to d)"""
    d = _unit(d)
    u = _unit(_V(u) - d * _V(u).dot(d))
    v = d.cross(u)
    def axis(n):
        k = max(2, int(round(n / step)))
        return [-n / 2 - rim] + [-n / 2 + n * i / k for i in range(k + 1)] + [n / 2 + rim]
    A, B = axis(w), axis(h)
    ids = {}
    for i, a in enumerate(A):
        for j, b in enumerate(B):
            o = _V(c) + u * a + v * b - d * 4.0
            hit = _bvh.ray_cast(o, d, reach)
            if hit[0] is None:
                continue
            inner = 0 < i < len(A) - 1 and 0 < j < len(B) - 1
            q = hit[0] - d * (lift if inner else -0.12)
            ids[(i, j)] = len(P)
            SRC[len(P)] = faces[hit[2]][0]          # a vertex of the triangle that was hit (the nearest vertex in space
            #                                         could be on the arm lying beside the chest: the patch tore when it moved)
            P.append([q.x, q.y, q.z])
    f0 = len(faces)
    for i in range(len(A) - 1):
        for j in range(len(B) - 1):
            k = [ids.get((i, j)), ids.get((i + 1, j)), ids.get((i + 1, j + 1)), ids.get((i, j + 1))]
            if None in k:
                continue
            faces.append([k[0], k[1], k[2]])
            fm.append(slot)
            faces.append([k[0], k[2], k[3]])
            fm.append(slot)
    PATCH_F.append((f0, len(faces), d))
    return len(faces) - f0


_n = 0
BK = (-1.0, 0.0, -0.12)                                            # onto the chest from the front
_n += patch((470.0, 0.0, 70.0), BK, (0, 0, 1), 36.0, 0.6, 0.12, 1, reach=60.0)           # zip (darker olive; glossy black read as a pale strip)
for _sd in (-1, 1):
    _n += patch((470.0, _sd * 9.5, 72.0), BK, (0, 1, 0), 9.5, 8.5, 0.28, 0, reach=60.0)  # chest pockets
    _n += patch((470.0, _sd * 9.5, 75.6), BK, (0, 1, 0), 10.1, 2.6, 0.5, 0, reach=60.0)  # their flaps
_n += patch((470.0, -9.5, 79.6), BK, (0, 1, 0), 9.0, 2.2, 0.22, 1, reach=60.0)           # name tape (left chest)
_th = _unit((38.3, 5.6, 9.5))                                      # right thigh axis (hip -> knee)
_c = _V((452.0, 12.5, 62.0))
_n += patch(_c, (0, 0.18, -1), _th, 15.0, 10.5, 0.35, 1, reach=30.0)                      # thigh pocket
_n += patch(_c - _th * 6.2, (0, 0.18, -1), (0, 1, 0), 11.2, 3.2, 0.6, 1, reach=30.0)      # flap
print("[manny_fbx] suit detail faces", _n, "vertices", len(P) - NP0)
for o in list(bpy.data.objects):
    bpy.data.objects.remove(o, do_unlink=True)
me = bpy.data.meshes.new("manny_pilot")
me.from_pydata([ex(p) for p in P], [], faces)
me.update()
for n, c in zip(SLOTS, COLORS):
    m = bpy.data.materials.new(n)
    m.diffuse_color = (c[0], c[1], c[2], 1.0)
    me.materials.append(m)
for poly, k in zip(me.polygons, fm):
    poly.material_index = k
    poly.use_smooth = True
ob = bpy.data.objects.new("manny_pilot", me)
bpy.context.scene.collection.objects.link(ob)
bpy.context.view_layer.objects.active = ob
ob.select_set(True)
# consistent outward normals (whatever the source winding), UVs = box projection, 1 UV unit per metre
bm = bmesh.new()
bm.from_mesh(me)
bm.faces.ensure_lookup_table()
_pf = {i for f0, f1, d in PATCH_F for i in range(f0, f1)}
bmesh.ops.recalc_face_normals(bm, faces=[f for f in bm.faces if f.index not in _pf])
for f0, f1, d in PATCH_F:                    # patches face against their ray
    dd = _V((d.x, -d.y, d.z))
    for i in range(f0, f1):
        bm.faces[i].normal_update()
        if bm.faces[i].normal.dot(dd) > 0:
            bm.faces[i].normal_flip()
uv = bm.loops.layers.uv.new("UVMap")
# UVs (metres): every body segment unwrapped as a cylinder about its own posed axis (u = arc length at an 8 cm radius,
# v = distance along the axis); a face is unwrapped with ONE segment (its first vertex's) and its u kept continuous
# across the +-pi wrap, so the fabric normal map has no triangle-sized tangent flips (a per-face box projection had).
import math as _m
VSEG, SEGAX = D.get("vseg"), D.get("seg_axis")
_fr = []
for a, b in (SEGAX or []):
    a, b = _V(a), _V(b)
    ax = (b - a).normalized()
    e1 = ax.cross(_V((0.0, 1.0, 0.0)))
    e1 = (e1 if e1.length > 0.2 else ax.cross(_V((0.0, 0.0, 1.0)))).normalized()
    _fr.append((a, ax, e1, ax.cross(e1)))
_seg_v = lambda vi: VSEG[vi] if vi < len(VSEG) else VSEG[SRC.get(vi, 0)] if vi in SRC else 0
RUV = 0.08
for f in bm.faces:
    if not _fr:
        n = f.normal
        a = max(range(3), key=lambda i: abs(n[i]))
        i, j = [(1, 2), (0, 2), (0, 1)][a]
        for lp in f.loops:
            lp[uv].uv = (lp.vert.co[i], lp.vert.co[j])
        continue
    o, ax, e1, e2 = _fr[_seg_v(f.loops[0].vert.index)]
    th0 = None
    for lp in f.loops:
        q = _V(P[lp.vert.index]) - o
        th = _m.atan2(q.dot(e2), q.dot(e1))
        if th0 is None:
            th0 = th
        elif th - th0 > _m.pi:
            th -= 2 * _m.pi
        elif th - th0 < -_m.pi:
            th += 2 * _m.pi
        lp[uv].uv = (th * RUV, q.dot(ax) / 100.0)
bm.to_mesh(me)
bm.free()
me.update()
used = sorted({v for f in faces for v in f})
ob.shape_key_add(name="Basis")
for name, m in D.get("morphs", {}).items():
    sk = ob.shape_key_add(name=name)
    dm = dict(zip(m["i"], m["d"]))
    for vi, d in dm.items():
        p = P[vi]
        sk.data[vi].co = ex((p[0] + d[0], p[1] + d[1], p[2] + d[2]))
    for vi, src in SRC.items():              # suit detail vertices ride on the body
        d = dm.get(src)
        if d:
            p = P[vi]
            sk.data[vi].co = ex((p[0] + d[0], p[1] + d[1], p[2] + d[2]))
arm_d = bpy.data.armatures.new("manny_rig")
arm = bpy.data.objects.new("manny_rig", arm_d)
bpy.context.scene.collection.objects.link(arm)
bpy.context.view_layer.objects.active = arm
bpy.ops.object.mode_set(mode='EDIT')
eb = arm_d.edit_bones.new("root")
eb.head, eb.tail = (4.2, 0.0, 0.3), (4.2, 0.0, 0.5)
bpy.ops.object.mode_set(mode='OBJECT')
ob.parent = arm
vg = ob.vertex_groups.new(name="root")
vg.add(list(range(len(P))), 1.0, 'REPLACE')
mod = ob.modifiers.new("arm", 'ARMATURE')
mod.object = arm
bpy.ops.object.select_all(action='DESELECT')
arm.select_set(True)
ob.select_set(True)
bpy.context.view_layer.objects.active = arm
out = os.path.join(DIR, "manny_pilot.fbx")
bpy.ops.export_scene.fbx(filepath=out, use_selection=True, axis_forward='X', axis_up='Z', apply_unit_scale=True, global_scale=1.0,
                         apply_scale_options='FBX_SCALE_NONE', bake_space_transform=False, mesh_smooth_type='FACE',
                         use_mesh_modifiers=False, use_tspace=False, add_leaf_bones=False, object_types={'MESH', 'ARMATURE'},
                         use_armature_deform_only=True, bake_anim=False, path_mode='STRIP')
print("[manny_fbx] %s  verts %d (used %d) faces %d  shape keys %s  %.1f s" % (out, len(P), len(used), len(faces), list(D.get("morphs", {})), time.time() - t0))

if PREVIEW:
    # quick look (workbench): left hand on the throttle + right hand on the stick, with the cockpit moving parts if exported
    import math
    from mathutils import Vector
    ck = os.environ.get("GYROSIM_CK2_DIR", "C:/GyroSimTiles/assets/cockpit4") + "/export"
    man = json.load(open(ck + "/manifest.json", encoding="utf-8")) if os.path.exists(ck + "/manifest.json") else {"parts": {}}
    for n in ("ck2_throttle", "ck2_stick", "ck2_shell"):
        f = os.path.join(ck, n + ".fbx")
        if os.path.exists(f):
            bpy.ops.import_scene.fbx(filepath=f)
            org = man["parts"].get(n, {}).get("origin", [0, 0, 0])
            for o in bpy.context.selected_objects:
                o.location = Vector(ex(org))
    sc = bpy.context.scene
    sc.render.engine = 'BLENDER_WORKBENCH'
    sc.display.shading.light = 'STUDIO'
    sc.display.shading.color_type = 'MATERIAL'
    sc.display.shading.show_cavity = True
    sc.render.resolution_x, sc.render.resolution_y = 1280, 720
    cam_d = bpy.data.cameras.new("c")
    cam = bpy.data.objects.new("c", cam_d)
    sc.collection.objects.link(cam)
    sc.camera = cam
    views = dict(thr=((430, -8, 96), (442, -33, 54), 30), thr_side=((455, -5, 62), (441.6, -32.6, 53.7), 40), stick=((430, 8, 96), (463, 33, 50), 30),
                 down=((430, 0, 100), (470, 0, 30), 75))
    keys = ob.data.shape_keys.key_blocks if ob.data.shape_keys else {}
    for vn, (eye, tgt, fov) in views.items():
        for kn in (("base", "ThrF", "ThrB") if vn.startswith("thr") else ("base",)):
            for k in keys:
                k.value = 1.0 if k.name == kn else 0.0
            if kn != "base":                                     # throttle part swung with the morph (about its pivot, export space)
                pass
            e, t = Vector(ex(eye)), Vector(ex(tgt))
            cam.location = e
            cam.rotation_euler = (t - e).to_track_quat('-Z', 'Y').to_euler()
            cam_d.lens_unit = 'FOV'
            cam_d.angle = math.radians(fov)
            cam_d.clip_start = 0.01
            sc.render.filepath = PREVIEW.replace(".png", "_%s_%s.png" % (vn, kn))
            bpy.ops.render.render(write_still=True)
    print("[manny_fbx] previews", PREVIEW)
