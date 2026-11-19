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
SRC = {}                                   # new vertex -> ((i0, i1, i2), (w0, w1, w2)): the body triangle it rides on
PATCH_F = []                               # (first face, last face + 1, ray direction)
VSEG0, SEGN = D.get("vseg") or [], D.get("seg_names") or []
_BODY_FACES = list(faces)                  # the body alone (patches are appended to `faces` later)
_SEG_BVH = {}


def _bvh_for(segs):
    """BVH of the body triangles of the named segments only (11-19 hands: a chest-pocket ray that first met the
    upper arm rode on the arm - at full throttle those vertices were dragged out of the pocket = pale spikes)"""
    if not segs or not VSEG0:
        return _bvh, None
    if segs not in _SEG_BVH:
        ids = {SEGN.index(n) for n in segs if n in SEGN}
        fmap = [i for i, f in enumerate(_BODY_FACES) if all(v < len(VSEG0) and VSEG0[v] in ids for v in f)]
        _SEG_BVH[segs] = (BVHTree.FromPolygons([_V(q) for q in P[:NP0]], [_BODY_FACES[i][::-1] for i in fmap]), fmap)
    return _SEG_BVH[segs]


def _bary(q, a, b, c):
    v0, v1, v2 = b - a, c - a, q - a
    d00, d01, d11, d20, d21 = v0.dot(v0), v0.dot(v1), v1.dot(v1), v2.dot(v0), v2.dot(v1)
    den = d00 * d11 - d01 * d01
    if abs(den) < 1e-12:
        return (1.0, 0.0, 0.0)
    v = (d11 * d20 - d01 * d21) / den
    w = (d00 * d21 - d01 * d20) / den
    return (1.0 - v - w, v, w)


def _unit(v):
    v = _V(v)
    return v.normalized()


def patch(c, d, u, w, h, lift, slot, step=1.0, rim=0.35, reach=14.0, segs=None, tear=None):
    """rectangle w x h (cm) centred on the ray from c along d, u = its long axis (made perpendicular to d);
    segs = body segments the rays may land on (seg_names of manny_pose); tear = drop quads whose corners landed
    at depths more than this apart (cm): a panel on a curled hand must not bridge from the knuckles to a finger"""
    dep = {}
    bv, fmap = _bvh_for(tuple(segs) if segs else None)
    other = 0
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
            hit = bv.ray_cast(o, d, reach)
            if hit[0] is None:
                continue
            fi = fmap[hit[2]] if fmap is not None else hit[2]
            if fmap is not None:
                h0 = _bvh.ray_cast(o, d, reach)
                other += 1 if (h0[0] is not None and h0[2] != fi and (h0[0] - hit[0]).length > 0.5) else 0
            inner = 0 < i < len(A) - 1 and 0 < j < len(B) - 1
            q = hit[0] - d * (lift if inner else -0.12)
            ids[(i, j)] = len(P)
            dep[(i, j)] = (hit[0] - o).dot(d)
            tri = _BODY_FACES[fi]                   # the patch vertex rides on the triangle that was hit (barycentric:
            #                                         exact for the rigid hand; never a vertex of another body part)
            SRC[len(P)] = (tuple(tri), _bary(hit[0], _V(P[tri[0]]), _V(P[tri[1]]), _V(P[tri[2]])))
            P.append([q.x, q.y, q.z])
    f0 = len(faces)
    for i in range(len(A) - 1):
        for j in range(len(B) - 1):
            k = [ids.get((i, j)), ids.get((i + 1, j)), ids.get((i + 1, j + 1)), ids.get((i, j + 1))]
            if None in k:
                continue
            if tear is not None:
                dz = [dep[q] for q in ((i, j), (i + 1, j), (i + 1, j + 1), (i, j + 1))]
                if max(dz) - min(dz) > tear:
                    continue
            faces.append([k[0], k[1], k[2]])
            fm.append(slot)
            faces.append([k[0], k[2], k[3]])
            fm.append(slot)
    PATCH_F.append((f0, len(faces), d))
    if other:
        print("[manny_fbx] patch at", [round(x, 1) for x in c], ": %d rays would have landed on another body part first (kept on %s)" % (other, segs))
    return len(faces) - f0


_n = 0
BK = (-1.0, 0.0, -0.12)                                            # onto the chest from the front
_TS = ("torso",)
_n += patch((470.0, 0.0, 70.0), BK, (0, 0, 1), 36.0, 0.6, 0.12, 1, reach=60.0, segs=_TS)           # zip (darker olive; glossy black read as a pale strip)
for _sd in (-1, 1):
    _n += patch((470.0, _sd * 9.5, 72.0), BK, (0, 1, 0), 9.5, 8.5, 0.28, 0, reach=60.0, segs=_TS)  # chest pockets
    _n += patch((470.0, _sd * 9.5, 75.6), BK, (0, 1, 0), 10.1, 2.6, 0.5, 0, reach=60.0, segs=_TS)  # their flaps
_n += patch((470.0, -9.5, 79.6), BK, (0, 1, 0), 9.0, 2.2, 0.22, 1, reach=60.0, segs=_TS)           # name tape (left chest)
_th = _unit((38.3, 5.6, 9.5))                                      # right thigh axis (hip -> knee)
_c = _V((452.0, 12.5, 62.0))
_n += patch(_c, (0, 0.18, -1), _th, 15.0, 10.5, 0.35, 1, reach=30.0, segs=("thigh_r",))                      # thigh pocket
_n += patch(_c - _th * 6.2, (0, 0.18, -1), (0, 1, 0), 11.2, 3.2, 0.6, 1, reach=30.0, segs=("thigh_r",))      # flap
# 11-19 (hands): glove construction on the back of each hand - a padded panel and a wrist tab (relief only, glove
# slot). Frames from manny_pose ("hands"). OFF by default (GYROSIM_GLOVE_PADS=1): on Manny's wrinkled, curled glove the
# projected panels come out with ragged edges (previews manny/h1, h2) - they look like torn tape, worse than nothing.
for _sd, _H in ((D.get("hands") or {}).items() if os.environ.get("GYROSIM_GLOVE_PADS", "0") == "1" else ()):
    _fd, _pn = _V(_H["fd"]), _V(_H["palm_n"])
    _mc = [_V(q) for q in _H["mcp"]]
    _row = (_mc[0] - _mc[3])
    _cen = (_mc[0] + _mc[1] + _mc[2] + _mc[3]) / 4.0
    _hs = ("hand_" + _sd,)
    _n += patch(_cen - _fd * 2.4 - _pn * 1.5, _pn, _row, _row.length + 0.6, 2.4, 0.17, 2, step=0.4, rim=0.2, reach=7.0, segs=_hs, tear=0.35)   # back-of-hand panel
    _n += patch(_V(_H["hand"]) + _fd * 1.0 - _pn * 2.0, _pn, _row, 4.4, 1.8, 0.15, 2, step=0.4, rim=0.2, reach=7.0, segs=_hs, tear=0.35)      # wrist tab
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
_seg_v = lambda vi: VSEG[vi] if vi < len(VSEG) else VSEG[SRC[vi][0][0]] if vi in SRC else 0
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
    for vi, (tri, wts) in SRC.items():       # suit / glove detail vertices ride on their body triangle
        d = [0.0, 0.0, 0.0]
        for k, wk in zip(tri, wts):
            dk = dm.get(k)
            if dk:
                d = [d[0] + wk * dk[0], d[1] + wk * dk[1], d[2] + wk * dk[2]]
        if d[0] or d[1] or d[2]:
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
    # quick look (workbench, 11-19 hands): each hand TOGETHER with its grip, built straight from ck2_model.build_stick /
    # build_throttle (not from an old export), close-ups from 5-6 sides, the throttle swung with ThrF / ThrB; plus an
    # exact check: intersecting triangle pairs hand x grip and the distance of the nearest hand vertices
    import math
    from mathutils import Vector, Matrix
    HERE = os.path.dirname(os.path.abspath(__file__))
    ckp = os.path.join(HERE, "..", "cockpit_blender", "ck2_model.py")
    src = open(ckp, encoding="utf-8").read().rstrip()
    assert src.endswith("\nmain()"), "ck2_model.py tail changed"
    _argv = sys.argv
    sys.argv = ["blender", "--", "--out", os.path.dirname(PREVIEW)]
    ns = {"__name__": "ck2_preview", "__file__": ckp}
    exec(compile(src[:-6], ckp, "exec"), ns)
    sys.argv = _argv
    spv, tpv = ns["build_stick"](), ns["build_throttle"]()
    grips = {}
    for n, org in (("ck2_stick", spv), ("ck2_throttle", tpv)):
        g = ns["to_blender"](ns["PARTS"][n], org)
        g.location = Vector(ex(org))
        grips[n] = g
        print("[manny_fbx] preview part", n, "tris", ns["tri_count"](g))
    for m in bpy.data.materials:
        if m.name.startswith("CK2_"):
            m.diffuse_color = ((0.30, 0.31, 0.34, 1) if "Grip" in m.name else (0.55, 0.5, 0.4, 1) if m.name in ("CK2_Knob", "CK2_Screw", "CK2_Chrome")
                               else (0.6, 0.1, 0.08, 1) if m.name == "CK2_Red" else (0.16, 0.16, 0.17, 1))
    ck = os.environ.get("GYROSIM_CK2_DIR", "C:/GyroSimTiles/assets/cockpit4") + "/export"
    shell = []
    if os.path.exists(os.path.join(ck, "ck2_shell.fbx")) and "--noshell" not in ARGS:
        bpy.ops.import_scene.fbx(filepath=os.path.join(ck, "ck2_shell.fbx"))
        shell = list(bpy.context.selected_objects)
    for n, c in zip(SLOTS, ((0.20, 0.23, 0.14), (0.13, 0.155, 0.09), (0.085, 0.075, 0.07), (0.03, 0.03, 0.03), (0.1, 0.1, 0.1))):
        bpy.data.materials[n].diffuse_color = (c[0], c[1], c[2], 1.0)       # brighter than the game colours: shapes must read
    sc = bpy.context.scene
    sc.render.engine = 'BLENDER_WORKBENCH'
    sc.display.shading.light = 'STUDIO'
    sc.display.shading.color_type = 'MATERIAL'
    sc.display.shading.show_cavity = True
    sc.render.resolution_x, sc.render.resolution_y = 1280, 720
    wld = bpy.data.worlds.new("w")
    wld.color = (0.22, 0.24, 0.27)
    sc.world = wld
    cam_d = bpy.data.cameras.new("c")
    cam = bpy.data.objects.new("c", cam_d)
    sc.collection.objects.link(cam)
    sc.camera = cam
    sys.path.insert(0, os.path.join(HERE, "..", "cockpit_blender"))
    import ck2_layout as _L
    THR_DEG = 30.0                                                      # manny_pose.THR_DEG
    tp = Vector(_L.THR["pivot"])
    gl = tp + Vector(_L.THR_GRIP)
    sp = Vector(_L.STICK_SIDE["pivot"])
    gs = sp + Vector((2.0, 0.0, 7.0))
    keys = ob.data.shape_keys.key_blocks if ob.data.shape_keys else {}
    morphs = D.get("morphs", {})
    hand_ids = {sd: {SEGN.index("hand_" + sd)} for sd in ("l", "r")} if SEGN else {}

    def posed(kn):
        """vertex positions (aircraft cm) with one control morph fully on"""
        X = [Vector(q) for q in P]
        m = morphs.get(kn)
        if m:
            dm = dict(zip(m["i"], m["d"]))
            for vi, d in dm.items():
                X[vi] = X[vi] + Vector(d)
            for vi, (tri, wts) in SRC.items():
                for k, wk in zip(tri, wts):
                    if k in dm:
                        X[vi] = X[vi] + Vector(dm[k]) * wk
        return X

    def check(kn, sd, part, deg):
        if not hand_ids:
            return
        X = posed(kn)
        hf = [f for f in faces if all((VSEG0[v] if v < len(VSEG0) else VSEG0[SRC[v][0][0]] if v in SRC else -1) in hand_ids[sd] for v in f)]
        Pt = ns["PARTS"][part]
        piv = tp if part == "ck2_throttle" else sp
        R = Matrix.Rotation(math.radians(deg), 3, 'Y')                 # UE: +Y rotation leans +Z toward +X (as manny_pose.rot)
        GV = [piv + R @ (Vector(q) - piv) for q in Pt.V]
        gb = BVHTree.FromPolygons(GV, Pt.F)
        hb = BVHTree.FromPolygons(X, hf)
        pairs = hb.overlap(gb)
        hv = sorted({v for f in hf for v in f})
        ds = sorted((gb.find_nearest(X[v])[3], v) for v in hv)
        near = [d for d, v in ds[:200]]
        print("[manny_fbx] check %-5s %s x %s: %d intersecting triangle pairs; nearest hand vertices %.2f / %.2f / %.2f cm (1st / 50th / 200th), within 0.3 cm: %d"
              % (kn, "hand_" + sd, part, len(pairs), near[0], near[min(49, len(near) - 1)], near[-1], sum(1 for d, v in ds if d < 0.3)))

    for kn, deg in (("base", 0.0), ("ThrF", THR_DEG), ("ThrB", -THR_DEG)):
        check(kn, "l", "ck2_throttle", deg)
    check("base", "r", "ck2_stick", 0.0)
    EYE = Vector((430.0, 0.0, 100.0))
    thr_views = dict(eye=(EYE + Vector((0, -6, -2)), 24), inb=(Vector((2, 30, 6)), 34), front=(Vector((30, 4, 4)), 34), below=(Vector((8, -22, -22)), 40),
                     top=(Vector((-2, 0.01, 32)), 34), aft=(Vector((-30, 6, 12)), 36))
    st_views = dict(eye=(EYE + Vector((0, 6, -2)), 22), inb=(Vector((3, -30, 6)), 34), front=(Vector((30, -4, 6)), 34), outb=(Vector((4, 30, 4)), 34),
                    top=(Vector((-4, 0.01, 32)), 34), aft=(Vector((-30, 2, 8)), 34))

    def shot(name, e, t, fov, ctx=True):
        for o_ in shell:                                                 # close-ups: without the cockpit shell in the way
            o_.hide_render = not ctx
        e, t = Vector(ex(e)), Vector(ex(t))
        cam.location = e
        cam.rotation_euler = (t - e).to_track_quat('-Z', 'Y').to_euler()
        cam_d.lens_unit = 'FOV'
        cam_d.angle = math.radians(fov)
        cam_d.clip_start = 0.01
        sc.render.filepath = PREVIEW.replace(".png", "_%s.png" % name)
        bpy.ops.render.render(write_still=True)

    wr = {sd: Vector((D.get("hands") or {}).get(sd, {}).get("hand", (440, -33 if sd == "l" else 33, 58))) for sd in ("l", "r")}
    for kn, deg in (("base", 0.0), ("ThrF", THR_DEG), ("ThrB", -THR_DEG)):
        for k in keys:
            k.value = 1.0 if k.name == kn else 0.0
        grips["ck2_throttle"].rotation_euler = (0.0, math.radians(deg), 0.0)     # export space: same sense about +Y
        g = tp + Matrix.Rotation(math.radians(deg), 3, 'Y') @ (gl - tp)
        for vn, (off, fov) in thr_views.items():
            shot("thr_%s_%s" % (vn, kn), off if vn == "eye" else g + off, g, fov, ctx=vn == "eye")
        shot("lcon_%s" % kn, EYE, Vector((445, -36, 30)), 55)
        if kn == "base":
            for vn, (off, fov) in st_views.items():
                shot("st_%s" % vn, off if vn == "eye" else gs + off, gs, fov, ctx=vn == "eye")
            for sd_ in ("l", "r"):                                       # the back of each hand, square on
                H_ = (D.get("hands") or {}).get(sd_)
                if H_:
                    c_ = Vector(H_["hand"]) + Vector(H_["fd"]) * 5.0
                    shot("back_%s" % sd_, c_ - Vector(H_["palm_n"]) * 26.0 - Vector(H_["fd"]) * 6.0, c_, 36, ctx=False)
            shot("down", EYE, Vector((470, 0, 30)), 75)
            # the Unreal capture cameras (CK scripts/views.json): judge the hands from where the pilot sees them
            shot("ue_stick_close", EYE, Vector((462, 33.5, 46)), 28)
            shot("ue_rconsole", EYE, Vector((445, 36, 30)), 55)
            shot("ue_throttle_close", EYE, Vector((441, -33, 50)), 28)
            shot("ue_rear_l", EYE, EYE + Vector((-74.0, -62.1, -25.9)), 90)          # pitch -15, yaw -140
            shot("ue_rear_l_body", EYE, EYE + Vector((-74.0, -62.1, -25.9)), 90, ctx=False)
            shot("ue_left90_body", EYE, EYE + Vector((0, -86.6, -50)), 90, ctx=False)
            shot("left90", EYE, EYE + Vector((0, -86.6, -50)), 90)
            shot("cuff_l", EYE + Vector((-4, -10, -8)), wr["l"], 26)
            shot("cuff_r", EYE + Vector((-4, 10, -8)), wr["r"], 26)
    print("[manny_fbx] previews", PREVIEW)
