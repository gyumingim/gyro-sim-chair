"""Clump proxies of downloaded high-detail tree models (Fab / Megascans 'Megaplants' USD, any USD with a twig PointInstancer
or plain foliage meshes) for the 3D trees v2 (sim/veg_v2.py). The source trees are 0.3-2 M vertices (Nanite foliage) and
cannot go into the instanced 3D Tiles; what we keep is their SHAPE: where the foliage is (k-means of the twig / leaf
positions -> 14 leaf clumps near, 4 far) and the trunk axis (centroids of the bark mesh per height band). veg_v2 builds the
prototypes from these with its own clump / AO / colour code, so the result is the same kind of 150-400 triangle tree as
the procedural ones, only with the real crown shape.

    python -I sim/veg_proxy.py --out C:\\GyroSimTiles\\veg\\protos_fab broad=<file.usd> broad=<file.usd> pine=<file.usd> ...

Output (outside git - derived from third-party assets whose licence does not allow redistribution): <out>/<group>_<k>.npz
with clump centres / semi-axes (unit height 1, unit crown radius 1, y up), the trunk polyline + radii, the source file
name and the true height / crown radius in metres. veg_v2 reads the folder named by GYROSIM_TREES_PROTOS.
Reads USD with pxr (usd-core) only; nothing in the asset is executed.
"""
import os, sys, json, time, site
if sys.flags.isolated:
    site.addsitedir(site.getusersitepackages())
import numpy as np


def foliage_and_bark(path):
    from pxr import Usd, UsdGeom
    s = Usd.Stage.Open(path, load=Usd.Stage.LoadAll)
    up = UsdGeom.GetStageUpAxis(s)
    mpu = UsdGeom.GetStageMetersPerUnit(s) or 1.0
    xc = UsdGeom.XformCache()
    fol, bark = [], []
    for p in s.Traverse():
        t = p.GetTypeName()
        if t == "PointInstancer":
            pi = UsdGeom.PointInstancer(p)
            M = np.array(xc.GetLocalToWorldTransform(p))           # row-vector convention (p' = p M)
            protos = pi.GetPrototypesRel().GetTargets()
            cent = []
            for tgt in protos:                                     # prototype centre + half size (twig / branch)
                pts = []
                for q in Usd.PrimRange(s.GetPrimAtPath(tgt)):
                    if q.GetTypeName() == "Mesh":
                        a = UsdGeom.Mesh(q).GetPointsAttr().Get()
                        if a is not None and len(a):
                            pts.append(np.asarray(a, np.float64)[:: max(1, len(a) // 4000)])
                P = np.concatenate(pts) if pts else np.zeros((1, 3))
                cent.append((P.mean(0), P[np.random.default_rng(0).choice(len(P), min(len(P), 24), replace=False)]))
            xf = pi.ComputeInstanceTransformsAtTime(Usd.TimeCode.Default(), Usd.TimeCode.Default())
            idx = np.asarray(pi.GetProtoIndicesAttr().Get())
            for k, T in enumerate(xf):
                T = np.array(T) @ M
                c, samp = cent[idx[k]]
                Q = np.c_[samp, np.ones(len(samp))] @ T
                fol.append(Q[:, :3])
        elif t == "Mesh" and "/Prototypes/" not in str(p.GetPath()):
            a = UsdGeom.Mesh(p).GetPointsAttr().Get()
            if a is None:
                continue
            M = np.array(xc.GetLocalToWorldTransform(p))
            P = np.asarray(a, np.float64)
            P = (np.c_[P, np.ones(len(P))] @ M)[:, :3]
            nm = p.GetName().lower()
            (fol if any(k in nm for k in ("leaf", "leaves", "foliage", "needle", "twig")) else bark).append(P)
    F = np.concatenate(fol) * mpu if fol else np.zeros((0, 3))
    B = np.concatenate(bark) * mpu if bark else np.zeros((0, 3))
    if up == "Z":
        F, B = F[:, [0, 2, 1]] * [1, 1, -1], B[:, [0, 2, 1]] * [1, 1, -1]
    return F, B


def proxy(F, B, n_near=14, n_far=4, seed=0):
    import cv2
    y0 = min(F[:, 1].min(), B[:, 1].min() if len(B) else 0.0)
    if len(B):
        y0 = np.percentile(B[:, 1], 0.2)
    F = F - [0, y0, 0]; B = B - [0, y0, 0] if len(B) else B
    H = max(F[:, 1].max(), B[:, 1].max() if len(B) else 0)
    # trunk axis: bark centroid per 0.6 m band from the ground up to the crown base (lowest 5 % of the foliage)
    cb = np.percentile(F[:, 1], 5)
    axis, rad = [], []
    c = np.median(B[B[:, 1] < 1.0][:, [0, 2]], 0) if len(B) and (B[:, 1] < 1.0).any() else np.zeros(2)
    y = 0.0
    while len(B) and y < min(cb + 0.25 * (H - cb), 0.85 * H):
        m = (B[:, 1] >= y) & (B[:, 1] < y + 0.6)
        if m.sum() > 10:
            d = np.hypot(B[m, 0] - c[0], B[m, 2] - c[1])
            core = m.copy(); core[m] = d < max(0.5, np.percentile(d, 30) * 2.0)
            if core.sum() > 5:
                c = np.median(B[core][:, [0, 2]], 0)
                rad.append(float(np.median(np.hypot(B[core, 0] - c[0], B[core, 2] - c[1]))))
                axis.append((c[0], y + 0.3, c[1]))
        y += 0.6
    axis = np.array(axis) if axis else np.array([[0, 0, 0], [0, cb, 0]], float)
    rad = np.array(rad) if rad else np.array([0.15, 0.1])
    base = axis[0, [0, 2]]
    F = F - [base[0], 0, base[1]]; axis = axis - [base[0], 0, base[1]]
    Rc = float(np.percentile(np.hypot(F[:, 0], F[:, 2]), 99)) + 0.35
    out = dict(height_m=float(H), crown_r_m=Rc, crown_base=float(cb / H))
    data = F.astype(np.float32)
    cv2.setRNGSeed(seed)
    for nm, k in (("near", n_near), ("far", n_far)):
        crit = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 50, 1e-4)
        _, lab, cen = cv2.kmeans(data, k, None, crit, 4, cv2.KMEANS_PP_CENTERS)
        lab = lab.reshape(-1)
        semi = []
        for j in range(k):
            Q = F[lab == j]
            sd = Q.std(0) if len(Q) > 3 else np.full(3, 0.3)
            semi.append(np.maximum(2.2 * sd + 0.3, 0.5))
        semi = np.array(semi)
        u = np.array([Rc, H, Rc])
        out[nm + "_c"] = (cen / u).astype(np.float32)
        out[nm + "_s"] = (semi / u).astype(np.float32)
    out["trunk"] = (axis / [Rc, H, Rc]).astype(np.float32)
    out["trunk_r"] = (np.clip(rad, 0.04, 0.6) / Rc).astype(np.float32)
    return out


def main(a):
    out = a[a.index("--out") + 1]
    os.makedirs(out, exist_ok=True)
    cnt, man = {}, []
    for arg in a:
        if "=" not in arg:
            continue
        g, f = arg.split("=", 1)
        t0 = time.time()
        F, B = foliage_and_bark(f)
        if len(F) < 50:
            print("no foliage in", f); continue
        r = proxy(F, B, seed=len(man))
        k = cnt.get(g, 0); cnt[g] = k + 1
        fn = os.path.join(out, "%s_%d.npz" % (g, k))
        np.savez(fn, src=os.path.basename(f), **r)
        man.append(dict(file=os.path.basename(fn), src=f, group=g, height_m=round(r["height_m"], 2), crown_r_m=round(r["crown_r_m"], 2),
                        crown_base=round(r["crown_base"], 2), foliage_pts=int(len(F)), bark_pts=int(len(B)), seconds=round(time.time() - t0, 1)))
        print(json.dumps(man[-1]), flush=True)
    json.dump(dict(made=time.strftime("%Y-%m-%d %H:%M:%S"), protos=man,
                   note="derived from third-party tree models (licence: see each source); never commit"), open(os.path.join(out, "manifest.json"), "w"), indent=1)


if __name__ == "__main__":
    main(sys.argv[1:])
