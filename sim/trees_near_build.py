"""Real-leaf trees near the aircraft (11-11): the data for unreal/GyroSim/Content/Python/trees_near.py.

    python -I sim/trees_near_build.py --db        tree instances (same trees as sim/veg_v2.py) -> C:\\GyroSimTiles\\veg\\near\\
    python -I sim/trees_near_build.py --meshes    reduced real tree meshes (glb) -> C:\\GyroSimTiles\\assets\\trees_near\\
    python -I sim/trees_near_build.py --preview D software pictures of the reduced meshes (no Unreal)

--db: runs veg_v2.block_attrs on every prep block (C:\\GyroSimTiles\\veg\\work\\b_*.npz: positions / heights / crowns from
the Meta canopy-height map, species from the terrain - the same 19.9 M trees as the v2 tiles, rock outcrops left out) and
writes them sorted into 250 m cells of the life layer's local frame (sim/life_common.ANCHOR: X north, Y east, Z up, cm):
    trees_near.bin   float32 records x y z yaw_deg h_m r_m species tint_r tint_g tint_b  (REC = 10)
    trees_near.json  cells {"i_j": [first record, count]}, cell size, species names, made / inputs
--meshes: the downloaded models are 3.7 M - 756 M triangles once their twig instancers are flattened; each is cut to a
Nanite-friendly 0.3 - 0.8 M triangles here (pine needle tufts: a random share of the tufts, each grown so the crown stays
as dense; oak / alder twigs: quadric decimation of the twig prototype, then flattened; bark decimated). Vertex colour:
R = 255 foliage / 0 bark, G = per-piece random, B = crown occlusion (inner / low = dark), A = height in the tree.
No textures (material /Game/Trees/M_GyroTreeNear, Scripts/trees_near_material.py, own code).
Outputs are derived from third-party models -> never in git (docs/trees-near-busan.md lists sources and licences).
"""
import glob, json, math, os, struct, sys, time, site
if sys.flags.isolated:
    site.addsitedir(site.getusersitepackages())
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import numpy as np                                                      # noqa: E402

NEAR = os.environ.get("GYROSIM_TREES_NEAR_DIR", r"C:\GyroSimTiles\veg\near")
SRC = r"C:\GyroSimTiles\assets\trees_src"
MESH_OUT = os.environ.get("GYROSIM_TREES_NEAR_MESHES", r"C:\GyroSimTiles\assets\trees_near")
CELL = 250.0                                                            # m
REC = 10
SPECIES = ("pine", "bpine", "broad", "shrub")                           # veg_v2 GROUPS without rock

# reduced meshes: name -> (source, kind, budget triangles). Sources (licences: docs/trees-near-busan.md):
#   Poly Haven pine_tree_01 (CC0) a / b / c; Fab Megascans English Oak Forest 01 A-D and Black Alder 01 C (Fab, UE only)
MESHES = dict(
    pine_a=("gltf", SRC + r"\polyhaven_pine_tree_01\pine_tree_01_1k.gltf", 0, 700000),
    pine_b=("gltf", SRC + r"\polyhaven_pine_tree_01\pine_tree_01_1k.gltf", 1, 600000),
    pine_c=("gltf", SRC + r"\polyhaven_pine_tree_01\pine_tree_01_1k.gltf", 2, 650000),
    oak_a=("usd", SRC + r"\tree_english_oak_forest_01_usd\Tree_English_Oak_Forest_01_A.usd", None, 600000),
    oak_b=("usd", SRC + r"\tree_english_oak_forest_01_usd\Tree_English_Oak_Forest_01_B.usd", None, 600000),
    oak_c=("usd", SRC + r"\tree_english_oak_forest_01_usd\Tree_English_Oak_Forest_01_C.usd", None, 600000),
    oak_d=("usd", SRC + r"\tree_english_oak_forest_01_usd\Tree_English_Oak_Forest_01_D.usd", None, 350000),
    alder_c=("usd", SRC + r"\tree_black_alder_01_usd\Tree_Black_Alder_01_C.usd", None, 700000),
)


# ---- instance database ---------------------------------------------------------------------------------------------
def _attrs(f):
    import veg_v2 as V2
    r = V2.block_attrs(f)
    if r is None:
        return None
    o, _st = r
    grp = V2.SPECIES_OF[o["pid"]]
    keep = grp < 4                                                       # rock outcrops are not trees
    return {k: v[keep] for k, v in o.items()} | dict(grp=grp[keep].astype(np.int8))


def build_db():
    import veg_v2 as V2
    import veg_build as V
    import life_common as L
    from multiprocessing import Pool
    t0 = time.time()
    fs = sorted(glob.glob(os.path.join(V.WORK, "b_*.npz")))
    parts = {}
    with Pool(int(os.environ.get("GYROSIM_VEG_PROCS", "12")), initializer=V2._init2) as pool:
        for res in pool.imap(_attrs, fs, chunksize=4):
            if res is None:
                continue
            for k, v in res.items():
                parts.setdefault(k, []).append(v)
    D = {k: np.concatenate(v) for k, v in parts.items()}
    n = len(D["lat"])
    print("trees %d (%.0f s)" % (n, time.time() - t0), flush=True)
    P = np.empty((n, 3))
    for a in range(0, n, 2000000):
        P[a:a + 2000000] = L.local(D["lat"][a:a + 2000000], D["lon"][a:a + 2000000], D["base"][a:a + 2000000].astype(np.float64))
    ci = np.floor(P[:, 0] / CELL).astype(np.int64)
    cj = np.floor(P[:, 1] / CELL).astype(np.int64)
    order = np.lexsort((cj, ci))
    R = np.empty((n, REC), np.float32)
    R[:, 0:3] = P * 100.0
    R[:, 3] = D["yaw"].astype(np.float64) * 360.0
    R[:, 4] = D["h"]
    R[:, 5] = D["r"]
    R[:, 6] = D["grp"]
    R[:, 7:10] = D["tint"]
    R = R[order]
    key = ci[order] * 100000 + cj[order]
    cuts = np.r_[0, np.nonzero(np.diff(key))[0] + 1, n]
    cio, cjo = ci[order], cj[order]
    cells = {"%d_%d" % (cio[a], cjo[a]): [int(a), int(b - a)] for a, b in zip(cuts[:-1], cuts[1:])}
    os.makedirs(NEAR, exist_ok=True)
    tmp = os.path.join(NEAR, "trees_near.bin.tmp")
    R.tofile(tmp)
    os.replace(tmp, os.path.join(NEAR, "trees_near.bin"))
    meta = dict(made=time.strftime("%Y-%m-%d %H:%M:%S"), seconds=round(time.time() - t0), trees=int(n), rec=REC, cell_m=CELL,
                anchor=L.ANCHOR, frame="life_common.local: X north, Y east, Z up, cm; z = ellipsoid height of the tree base",
                fields="x y z yaw_deg h_m r_m species tint_r tint_g tint_b", species=SPECIES,
                per_species={s: int((D["grp"] == k).sum()) for k, s in enumerate(SPECIES)},
                h_mean=round(float(D["h"].mean()), 2), r_mean=round(float(D["r"].mean()), 2),
                inputs=dict(work=V.WORK, n_blocks=len(fs), veg_v2=os.path.getmtime(os.path.join(HERE, "veg_v2.py"))),
                cells=cells)
    json.dump(meta, open(os.path.join(NEAR, "trees_near.json"), "w"))
    print(json.dumps({k: v for k, v in meta.items() if k != "cells"}), "cells", len(cells), "max per cell", max(c[1] for c in cells.values()))


# ---- mesh reduction ------------------------------------------------------------------------------------------------
def _tri_fan(fc, fi):
    st = np.concatenate(([0], np.cumsum(fc)[:-1]))
    out = []
    for k in range(2, int(fc.max())):
        sel = fc > k
        out.append(np.stack((fi[st[sel]], fi[st[sel] + k - 1], fi[st[sel] + k]), 1))
    return np.concatenate(out).astype(np.int64)


def _simplify(P, F, keep):
    """quadric decimation to `keep` (share of triangles); tiny meshes are left alone."""
    import fast_simplification as fsim
    if keep >= 0.98 or len(F) < 60:
        return P, F
    P2, F2 = fsim.simplify(np.ascontiguousarray(P, np.float32), np.ascontiguousarray(F, np.int32), target_reduction=1.0 - keep, agg=7)
    return np.asarray(P2, np.float64), np.asarray(F2, np.int64)


def _components(n, F):
    from scipy.sparse import coo_matrix
    from scipy.sparse.csgraph import connected_components
    e = np.concatenate((F[:, [0, 1]], F[:, [1, 2]]))
    return connected_components(coo_matrix((np.ones(len(e)), (e[:, 0], e[:, 1])), shape=(n, n)), directed=False)


def read_gltf_tree(path, mesh_i, budget, rng):
    """Poly Haven pine: bark + trunk meshes kept, needle tufts (twig, 13-vertex pieces) subsampled to the budget."""
    g = json.load(open(path))
    mm = np.memmap(os.path.join(os.path.dirname(path), g["buffers"][0]["uri"]), np.uint8, "r")
    CT = {5126: np.float32, 5125: np.uint32, 5123: np.uint16}
    NCn = {"SCALAR": 1, "VEC3": 3}

    def acc(i):
        a = g["accessors"][i]; v = g["bufferViews"][a["bufferView"]]
        dt = np.dtype(CT[a["componentType"]]); k = NCn[a["type"]]
        off = v.get("byteOffset", 0) + a.get("byteOffset", 0)
        st = v.get("byteStride", 0) or k * dt.itemsize
        raw = np.asarray(mm[off:off + st * a["count"]]).reshape(a["count"], st)[:, :k * dt.itemsize]
        return np.ascontiguousarray(raw).view(dt).reshape(a["count"], k).astype(np.float64 if dt == np.float32 else np.int64)
    m = g["meshes"][mesh_i]
    bark, fol = [], []
    twig_tris = sum(g["accessors"][p["indices"]]["count"] // 3 for p in m["primitives"] if "twig" in g["materials"][p["material"]]["name"])
    other = sum(g["accessors"][p["indices"]]["count"] // 3 for p in m["primitives"] if "twig" not in g["materials"][p["material"]]["name"])
    for p in m["primitives"]:
        name = g["materials"][p["material"]]["name"]
        P = acc(p["attributes"]["POSITION"]); F = acc(p["indices"]).reshape(-1, 3)
        if "twig" in name:
            nc, lab = _components(len(P), F)
            f = min(1.0, max(0.02, (budget - other) / max(twig_tris, 1)))
            pick = rng.random(nc) < f
            grow = f ** -0.42                                           # keep the crown about as dense (area ~ f * grow^2)
            fl = lab[F[:, 0]]
            F = F[pick[fl]]
            cen = np.zeros((nc, 3)); cnt = np.bincount(lab, minlength=nc)[:, None]
            np.add.at(cen, lab, P); cen /= np.maximum(cnt, 1)
            P = cen[lab] + (P - cen[lab]) * grow
            piece = lab
            fol.append((P, F, piece))
        else:
            if "dead" in name:
                continue
            P2, F2 = _simplify(P, F, min(1.0, 40000.0 / max(len(F), 1)) if "trunk" in name else 1.0)
            bark.append((P2, F2))
    return bark, fol, dict(source_tris=int(twig_tris + other), twig_share=round(float(f), 4), grow=round(float(grow), 3))


def read_usd_tree(path, budget, rng):
    """Megascans Megaplants USD: trunk mesh decimated, twig prototypes decimated once, then flattened by the instancer."""
    from pxr import Usd, UsdGeom
    s = Usd.Stage.Open(path, load=Usd.Stage.LoadAll)
    xc = UsdGeom.XformCache()
    meshes, inst = {}, []
    for p in s.Traverse():
        t = p.GetTypeName()
        if t == "Mesh":
            mm = UsdGeom.Mesh(p)
            P = np.asarray(mm.GetPointsAttr().Get(), np.float64)
            fc = np.asarray(mm.GetFaceVertexCountsAttr().Get()); fi = np.asarray(mm.GetFaceVertexIndicesAttr().Get())
            meshes[str(p.GetPath())] = (P, _tri_fan(fc, fi), np.array(xc.GetLocalToWorldTransform(p)))
        elif t == "PointInstancer":
            pi = UsdGeom.PointInstancer(p)
            xf = pi.ComputeInstanceTransformsAtTime(Usd.TimeCode.Default(), Usd.TimeCode.Default())
            inst.append(([str(x) for x in pi.GetPrototypesRel().GetTargets()], np.asarray(pi.GetProtoIndicesAttr().Get()),
                         [np.array(T) for T in xf], np.array(xc.GetLocalToWorldTransform(p))))
    proto_of = {}
    for targets, idx, xf, M in inst:
        for k, tg in enumerate(targets):
            proto_of[tg] = proto_of.get(tg, 0) + int((idx == k).sum())
    direct = {k: v for k, v in meshes.items() if not any(k.startswith(tg + "/") or k == tg for tg in proto_of)}
    flat_twig = 0
    for tg, cnt in proto_of.items():
        flat_twig += cnt * sum(len(v[1]) for k, v in meshes.items() if k.startswith(tg + "/") or k == tg)
    trunk_tris = sum(len(v[1]) for v in direct.values())
    trunk_keep = min(1.0, 60000.0 / max(trunk_tris, 1))
    twig_keep = min(1.0, max(0.004, (budget - 60000.0) / max(flat_twig, 1)))
    bark, fol = [], []
    for k, (P, F, M) in direct.items():
        P2, F2 = _simplify(P, F, trunk_keep)
        bark.append(((np.c_[P2, np.ones(len(P2))] @ M)[:, :3], F2))
    red = {}
    for tg in proto_of:
        parts = []
        for k, (P, F, M) in meshes.items():
            if k.startswith(tg + "/") or k == tg:
                P2, F2 = _simplify(P, F, twig_keep)
                Mp = M @ np.linalg.inv(np.array(xc.GetLocalToWorldTransform(s.GetPrimAtPath(tg))))   # mesh -> prototype root
                Q = (np.c_[P2, np.ones(len(P2))] @ Mp)[:, :3]
                parts.append((Q, F2) + tuple(_components(len(Q), F2)))
        red[tg] = parts
    pid = 0
    for targets, idx, xf, M in inst:
        for i, T in enumerate(xf):
            W = T @ M
            for P, F, nc, lab in red[targets[idx[i]]]:
                Q = (np.c_[P, np.ones(len(P))] @ W)[:, :3]
                fol.append((Q, F, lab + pid))
                pid += nc
    return bark, fol, dict(source_tris=int(trunk_tris + flat_twig), twig_keep=round(float(twig_keep), 4), trunk_keep=round(float(trunk_keep), 4))


def assemble(bark, fol, rng):
    """one mesh: y up, metres, trunk base at the origin; vertex colour kind / random / occlusion / height."""
    PB = np.concatenate([b[0] for b in bark]) if bark else np.zeros((0, 3))
    y0 = np.percentile(PB[:, 1], 0.2) if len(PB) else 0.0
    low = PB[PB[:, 1] < y0 + 1.0] if len(PB) else np.zeros((0, 3))
    cx, cz = (np.median(low[:, 0]), np.median(low[:, 2])) if len(low) else (0.0, 0.0)
    off = np.array([cx, y0, cz])
    Ps, Fs, Cs = [], [], []
    nv = 0
    PF = np.concatenate([f[0] for f in fol]) - off
    H = max(float(PF[:, 1].max()), float((PB[:, 1] - y0).max()) if len(PB) else 0.0)
    rxz = np.hypot(PF[:, 0], PF[:, 2])
    hb = np.clip((PF[:, 1] / H * 12).astype(int), 0, 11)
    rmax = np.array([np.percentile(rxz[hb == k], 95) if (hb == k).sum() > 20 else rxz.max() for k in range(12)])
    for P, F in bark:
        P = P - off
        C = np.zeros((len(P), 4), np.uint8)
        C[:, 1] = rng.integers(0, 256)
        C[:, 2] = np.clip(255 * (0.35 + 0.5 * P[:, 1] / H), 0, 255)
        C[:, 3] = np.clip(255 * P[:, 1] / H, 0, 255)
        Ps.append(P); Fs.append(F + nv); Cs.append(C); nv += len(P)
    for P, F, piece in fol:
        P = P - off
        used = np.unique(F)
        remap = -np.ones(len(P), np.int64); remap[used] = np.arange(len(used))
        P, F, piece = P[used], remap[F], piece[used]
        C = np.zeros((len(P), 4), np.uint8)
        C[:, 0] = 255
        C[:, 1] = (((np.asarray(piece).astype(np.uint64) * np.uint64(2654435761)) & np.uint64(0xFFFFFFFF)) >> np.uint64(24)).astype(np.uint8)
        hb_ = np.clip((P[:, 1] / H * 12).astype(int), 0, 11)
        d = np.clip(np.hypot(P[:, 0], P[:, 2]) / np.maximum(rmax[hb_], 0.3), 0, 1.2)
        occ = np.clip(0.25 + 0.55 * d ** 0.8 + 0.3 * (P[:, 1] / H), 0, 1)
        C[:, 2] = (255 * occ).astype(np.uint8)
        C[:, 3] = np.clip(255 * P[:, 1] / H, 0, 255).astype(np.uint8)
        Ps.append(P); Fs.append(F + nv); Cs.append(C); nv += len(P)
    P = np.concatenate(Ps); F = np.concatenate(Fs); C = np.concatenate(Cs)
    # normals: face area weighted; foliage bent 45 % toward the crown envelope (soft canopy shading, not beads)
    fn = np.cross(P[F[:, 1]] - P[F[:, 0]], P[F[:, 2]] - P[F[:, 0]])
    N = np.zeros_like(P)
    for k in range(3):
        np.add.at(N, F[:, k], fn)
    N /= np.maximum(np.linalg.norm(N, axis=1, keepdims=True), 1e-12)
    isf = C[:, 0] > 127
    cc = np.array([0.0, 0.55 * H, 0.0])
    out = P - cc; out[:, 1] *= 0.6
    out /= np.maximum(np.linalg.norm(out, axis=1, keepdims=True), 1e-9)
    N[isf] = N[isf] * 0.55 + out[isf] * 0.45
    N /= np.maximum(np.linalg.norm(N, axis=1, keepdims=True), 1e-12)
    rc = float(np.percentile(np.hypot(P[isf, 0], P[isf, 2]), 97)) if isf.any() else 1.0
    return P.astype(np.float32), N.astype(np.float32), C, F.astype(np.uint32), dict(height_m=round(H, 2), crown_r_m=round(rc, 2))


def write_glb(path, P, N, C, F):
    def pad(b, c=b"\0"):
        return b + c * ((4 - len(b) % 4) % 4)
    blobs = [P.tobytes(), N.tobytes(), C.tobytes(), F.tobytes()]
    offs, buf = [], b""
    for b in blobs:
        offs.append(len(buf)); buf += pad(b)
    nv = len(P)
    g = dict(asset=dict(version="2.0", generator="gyro-sim-chair sim/trees_near_build.py"), scene=0, scenes=[dict(nodes=[0])],
             nodes=[dict(mesh=0, name=os.path.splitext(os.path.basename(path))[0])],
             materials=[dict(name="TreeNear", doubleSided=True)],
             meshes=[dict(primitives=[dict(attributes=dict(POSITION=0, NORMAL=1, COLOR_0=2), indices=3, material=0)])],
             buffers=[dict(byteLength=len(buf))],
             bufferViews=[dict(buffer=0, byteOffset=offs[0], byteLength=len(blobs[0]), target=34962),
                          dict(buffer=0, byteOffset=offs[1], byteLength=len(blobs[1]), target=34962),
                          dict(buffer=0, byteOffset=offs[2], byteLength=len(blobs[2]), target=34962),
                          dict(buffer=0, byteOffset=offs[3], byteLength=len(blobs[3]), target=34963)],
             accessors=[dict(bufferView=0, componentType=5126, count=nv, type="VEC3", min=P.min(0).tolist(), max=P.max(0).tolist()),
                        dict(bufferView=1, componentType=5126, count=nv, type="VEC3"),
                        dict(bufferView=2, componentType=5121, normalized=True, count=nv, type="VEC4"),
                        dict(bufferView=3, componentType=5125, count=int(F.size), type="SCALAR")])
    js = pad(json.dumps(g).encode(), b" ")
    with open(path, "wb") as f:
        f.write(struct.pack("<III", 0x46546C67, 2, 12 + 8 + len(js) + 8 + len(buf)))
        f.write(struct.pack("<II", len(js), 0x4E4F534A)); f.write(js)
        f.write(struct.pack("<II", len(buf), 0x004E4942)); f.write(buf)


def build_meshes(names=None):
    os.makedirs(MESH_OUT, exist_ok=True)
    manp = os.path.join(MESH_OUT, "meshes.json")
    man = json.load(open(manp)) if os.path.isfile(manp) else dict(meshes={})
    for name, (kind, src, mi, budget) in MESHES.items():
        if names and name not in names:
            continue
        t0 = time.time()
        rng = np.random.default_rng(sum(map(ord, name)))
        if kind == "gltf":
            bark, fol, info = read_gltf_tree(src, mi, budget, rng)
        else:
            bark, fol, info = read_usd_tree(src, budget, rng)
        P, N, C, F, dims = assemble(bark, fol, rng)
        P = P[:, [0, 1, 2]]
        out = os.path.join(MESH_OUT, "SM_TreeNear_%s.glb" % name)
        write_glb(out, P, N, C, F)
        man["meshes"][name] = dict(file=os.path.basename(out), src=src, triangles=int(len(F) // 3) if F.ndim == 1 else int(len(F)),
                                   verts=int(len(P)), seconds=round(time.time() - t0, 1), made=time.strftime("%Y-%m-%d %H:%M:%S"), **dims, **info)
        print(name, json.dumps(man["meshes"][name]), flush=True)
        json.dump(man, open(manp, "w"), indent=1)


def preview(outdir, names=None):
    """side + top silhouettes with simple lighting (matplotlib), for checking the reductions without Unreal."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    os.makedirs(outdir, exist_ok=True)
    man = json.load(open(os.path.join(MESH_OUT, "meshes.json")))["meshes"]
    for name, m in man.items():
        if names and name not in names:
            continue
        b = open(os.path.join(MESH_OUT, m["file"]), "rb").read()
        jl = struct.unpack("<I", b[12:16])[0]
        g = json.loads(b[20:20 + jl]); bin0 = 20 + jl + 8
        av = lambda i, dt, k: np.frombuffer(b, dt, g["accessors"][i]["count"] * k, bin0 + g["bufferViews"][i]["byteOffset"]).reshape(-1, k)
        P = av(0, np.float32, 3); C = av(2, np.uint8, 4)
        sel = np.random.default_rng(0).choice(len(P), min(len(P), 400000), replace=False)
        P, C = P[sel], C[sel]
        col = np.where(C[:, :1] > 127, np.c_[0.18, 0.32, 0.12] * (0.4 + 0.8 * C[:, 2:3] / 255.0), np.c_[0.35, 0.25, 0.18] * np.ones((1, 1)))
        fig, ax = plt.subplots(1, 2, figsize=(10, 6), dpi=110)
        o = np.argsort(P[:, 2]); ax[0].scatter(P[o, 0], P[o, 1], s=0.05, c=np.clip(col[o], 0, 1)); ax[0].set_aspect("equal"); ax[0].set_title("%s side %d tri" % (name, m["triangles"]))
        o = np.argsort(P[:, 1]); ax[1].scatter(P[o, 0], P[o, 2], s=0.05, c=np.clip(col[o], 0, 1)); ax[1].set_aspect("equal"); ax[1].set_title("top")
        fig.savefig(os.path.join(outdir, name + ".png")); plt.close(fig)


if __name__ == "__main__":
    a = sys.argv[1:]
    sel = [x for x in a if not x.startswith("--")]
    if "--db" in a:
        build_db()
    if "--meshes" in a:
        build_meshes(sel or None)
    if "--preview" in a:
        preview(a[a.index("--preview") + 1], [x for x in sel if x != a[a.index("--preview") + 1]] or None)
