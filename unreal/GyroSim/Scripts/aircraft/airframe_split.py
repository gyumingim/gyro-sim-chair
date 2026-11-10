#!/usr/bin/env python3
"""airframe_split.py - the exterior of the GPL FlightGear F-16 (fetch_f16_model.py cache) split into a body and the
moving control surfaces, for the UE airframe pass (Scripts/aircraft/ue_airframe.py, sim_client / airframe_live.py).

Writes into ThirdParty/f16_airframe/ (outside git, GPL-2.0 derived like f16_obj/):
  F16_Body.obj           exterior minus the moving surfaces (same frame as F16_Exterior: UE body cm, OBJ = UE (X, Z, Y))
  F16_FlapL/R.obj        flaperons (roll + flaps)        - vertices relative to the hinge point
  F16_StabL/R.obj        all-moving horizontal tails     - "
  F16_LefL/R.obj         leading-edge flaps (alpha)      - "
  F16_Rudder.obj         rudder                          - "
  tex_*.png              textures used (copied / converted by fetch_f16_model.TexOut)
  airframe.json          per part: hinge point (UE cm), unit axis whose + rotation moves the trailing edge DOWN (flaps,
                         stabs, LEF) or to the RIGHT (rudder), triangle counts; nav-light / strobe / beacon points.
Hinge points and axes = the FlightGear model's own rotate animations (Models/F-16.xml), converted to UE.
Run: python Scripts/aircraft/airframe_split.py  (CPython 3.10+, numpy, Pillow; reads only the local f16_src cache)
"""
from __future__ import annotations

import json
import re
import shutil
import sys
import time
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import fetch_f16_model as F  # noqa: E402
import airframe_v2 as V2  # noqa: E402

OUT = F.THIRD / "f16_airframe"
F.OUT = OUT                                     # TexOut / write_obj write here

# FG model frame (m, x aft, y right, z up): center + axis of each rotate animation in Models/F-16.xml
SURF = {
    "F16_FlapL":  dict(objs=r"^Left(Upper|Lower)Flap$",  c=(1.54, -2.35, 0.12),  a=(0.150157, -0.987872, -0.039515), sense="down"),
    "F16_FlapR":  dict(objs=r"^Right(Upper|Lower)Flap$", c=(1.54, 2.35, 0.12),   a=(0.150157, 0.987872, -0.039515), sense="down"),
    "F16_StabL":  dict(objs=r"^Left(Upper|Lower)HorizonTail$",  c=(4.36, -1.965, -0.1), a=(0.0, -0.981645, -0.190720), sense="down"),
    "F16_StabR":  dict(objs=r"^Right(Upper|Lower)HorizonTail$", c=(4.36, 1.965, -0.1),  a=(0.0, 0.981645, -0.190720), sense="down"),
    "F16_LefL":   dict(objs=r"^Left(Upper|Lower)Lef$",   c=(0.24, -3.0, 0.035),  a=(0.549345, -0.834983, -0.031988), sense="down"),
    "F16_LefR":   dict(objs=r"^Right(Upper|Lower)Lef$",  c=(0.24, 3.0, 0.035),   a=(0.550908, 0.834232, -0.023610), sense="down"),
    "F16_Rudder": dict(objs=r"^Rudder(\.\d+)?$", c=(4.915, 0.0, 2.095), a=(0.547371, 0.0, 0.836890), sense="right"),
}
DROP = r"Logo|USAF|VstabBand"
FIN_RECT = (0.52, 0.865, 0.74, 0.995)        # unused atlas area (white background of the FG skin) for the fin sides
FIN_X, FIN_Z = (-575.0, -255.0), (110.0, 340.0)


MISSILE_RECT = (0.45, 0.968, 0.50, 0.992)    # unused atlas area painted plain missile white-grey by airframe_bake.py


def add_aim9(a2, body):
    """generic AIM-9-like training rounds (our own simple shapes: tube, ogive nose, 4 canards, 4 tail fins) on both
    wingtip rails, appended to the v2 body. Rail = body vertices beyond |y| 465 cm."""
    V = body["V"][np.unique(body["T"])]
    mk = np.bincount(body["MK"]).argmax()
    parts = []
    for side in (-1, 1):
        R = V[V[:, 1] * side > 465.0]
        if len(R) < 4:
            continue
        yc, zc = float(np.median(R[:, 1])), float(R[:, 2].min()) - 7.0
        xn = float(R[:, 0].max()) + 55.0                  # nose ahead of the rail
        L, r, n = 287.0, 6.35, 16
        xs = np.array([xn - L, xn - 40.0, xn - 22.0, xn - 10.0, xn - 2.0])
        rs = np.array([r, r, r * 0.8, r * 0.45, r * 0.08])
        ang = np.linspace(0, 2 * np.pi, n + 1)[:-1]
        ring = lambda x, rr: np.stack([np.full(n, x), yc + rr * np.cos(ang), zc + rr * np.sin(ang)], 1)   # noqa: E731
        verts = np.concatenate([ring(x, rr) for x, rr in zip(xs, rs)] + [np.array([[xn, yc, zc], [xn - L, yc, zc]])])
        tri, nrm = [], []
        for i in range(len(xs) - 1):
            for j in range(n):
                a, b = i * n + j, i * n + (j + 1) % n
                c, d = a + n, b + n
                tri += [(a, c, b), (b, c, d)]
        tip, tail = len(verts) - 2, len(verts) - 1
        last = (len(xs) - 1) * n
        for j in range(n):
            tri.append((last + j, tip, last + (j + 1) % n))
            tri.append((j, (j + 1) % n, tail))
        def fin(x0, x1, x2, span, rot):                   # root x0..x1 at the tube, tip edge x2..x1 at 'span'
            dy, dz = np.cos(rot), np.sin(rot)
            p = [[x0, yc + r * dy, zc + r * dz], [x1, yc + r * dy, zc + r * dz], [x1, yc + span * dy, zc + span * dz], [x2, yc + span * dy, zc + span * dz]]
            return np.array(p)
        fins = []
        for rot in np.radians([45, 135, 225, 315]):
            fins.append(fin(xn - L, xn - L + 32.0, xn - L + 20.0, 32.0, rot))
            fins.append(fin(xn - 62.0, xn - 48.0, xn - 50.0, 17.0, rot))
        base = len(verts)
        for f in fins:
            verts = np.concatenate([verts, f])
            k = len(verts) - 4
            tri += [(k, k + 1, k + 2), (k, k + 2, k + 3)]
        parts.append((verts, np.array(tri)))
    if not parts:
        return a2, 0
    Vs, Ts, axes, off = [], [], [], 0
    for v, tt in parts:
        Vs.append(v); Ts.append(tt + off); off += len(v)
        axes.append(np.repeat(v[len(v) - 33][None], len(tt), 0))   # tail-centre vertex (rings, tip, tail, then 8 fins x 4) = axis point
    Vn, Tn = np.concatenate(Vs), np.concatenate(Ts)
    AX = np.concatenate(axes)
    P = Vn[Tn]
    fn = np.cross(P[:, 1] - P[:, 0], P[:, 2] - P[:, 0])
    fu = fn / np.maximum(np.linalg.norm(fn, axis=1, keepdims=True), 1e-9)
    # shading normals: tube = radial from the missile axis, fins = face normal (two-sided material);
    # geometric winding opposite to N (this pipeline's rule)
    rad = P - AX[:, None, :]
    rad[..., 0] = 0
    rn = rad / np.maximum(np.linalg.norm(rad, axis=2, keepdims=True), 1e-9)
    nfin = 16                                             # 8 fins x 2 tris per side, last in each side's list
    is_fin = np.concatenate([np.r_[np.zeros(len(tt) - nfin, bool), np.ones(nfin, bool)] for _, tt in parts])
    N = np.where(is_fin[:, None, None], np.repeat(fu[:, None], 3, 1), rn)
    flip = np.einsum("ij,ij->i", fu, N.mean(1)) > 0
    Tn[flip] = Tn[flip][:, [0, 2, 1]]
    P = Vn[Tn]
    N[flip] = N[flip][:, [0, 2, 1]]
    u0, v0, u1, v1 = MISSILE_RECT
    UV = np.zeros((len(Tn), 3, 2))
    UV[:, :, 0] = u0 + (P[:, :, 0] - P[:, :, 0].min()) / max(1e-6, np.ptp(P[:, :, 0])) * (u1 - u0)
    UV[:, :, 1] = v0 + ((np.arange(3)[None, :] + np.arange(len(Tn))[:, None]) % 3) / 2.0 * (v1 - v0)
    out = dict(V=np.concatenate([a2["V"], Vn]), T=np.concatenate([a2["T"], Tn + len(a2["V"])]), UV=np.concatenate([a2["UV"], UV]),
               N=np.concatenate([a2["N"], N]), MK=np.concatenate([a2["MK"], np.full(len(Tn), mk)]),
               DS=np.concatenate([a2["DS"], np.ones(len(Tn), bool) if a2["DS"].dtype == bool else np.ones(len(Tn), a2["DS"].dtype)]))
    return out, int(len(Tn))


def add_petals(a2, body, n=15):
    """round 5: real nozzle petals - 15 slightly overlapping curved strips (2 tris x 4 segments each) on a cone around the
    exhaust exit, using the nozzle material (MI_AF2_NozzleGE: titanium -> straw -> blued, petal normal map). UVs run
    along the left (titanium -> straw) part of tex_af2_noz_base."""
    noz = np.array([bool(F.MATKEYS[k][0]) and "nozzle-GE" in F.MATKEYS[k][0] for k in body["MK"]])
    if not noz.any():
        return a2, 0
    P = body["V"][body["T"][noz]].reshape(-1, 3)
    cy, cz = float(np.median(P[:, 1])), float(np.median(P[:, 2]))
    r = np.hypot(P[:, 1] - cy, P[:, 2] - cz)
    xe = float(P[:, 0].min())                                       # exit (aft end)
    aft = P[:, 0] < xe + 8.0
    r_exit = float(r[aft].max()) if aft.any() else float(r.max())
    xf, x_e = xe + 55.0, xe - 2.0                                   # petals run from 55 cm ahead of the exit to the exit
    rf, re = r_exit * 1.10, r_exit * 1.01                          # converging cone
    mk = int(np.bincount(body["MK"][noz]).argmax())
    V, Tt, UV, N = [], [], [], []
    seg = 4
    w = 2 * np.pi / n * 1.12                                         # 12 % overlap
    for i in range(n):
        a0 = 2 * np.pi * i / n
        lift = 0.35 if i % 2 else 0.0                               # alternate petals sit slightly outside (overlap)
        base = len(V)
        for s in range(seg + 1):
            for e in (0, 1):
                f = s / seg
                x = xf + (x_e - xf) * f
                rr = rf + (re - rf) * f + lift
                ang = a0 - w / 2 + w * e
                V.append([x, cy + rr * np.cos(ang), cz + rr * np.sin(ang)])
                UV.append([0.03 + 0.33 * f, 0.25 + 0.6 * e])
        for s in range(seg):
            a, b = base + 2 * s, base + 2 * s + 1
            c, d = a + 2, b + 2
            Tt += [(a, c, b), (b, c, d)]
    V, Tt, UV = np.array(V), np.array(Tt), np.array(UV)
    Pt = V[Tt]
    fn = np.cross(Pt[:, 1] - Pt[:, 0], Pt[:, 2] - Pt[:, 0])
    fu = fn / np.maximum(np.linalg.norm(fn, axis=1, keepdims=True), 1e-9)
    rad = Pt.copy(); rad[..., 0] = 0; rad[..., 1] -= cy; rad[..., 2] -= cz
    Nn = rad / np.maximum(np.linalg.norm(rad, axis=2, keepdims=True), 1e-9)
    Nn = Nn * 0.97 + np.array([0.0, 0.0, 0.0])
    Nn[..., 0] = 0.12                                                # cone tilt (converging toward the exit)
    Nn /= np.linalg.norm(Nn, axis=2, keepdims=True)
    UVt = UV[Tt]
    flip = np.einsum("ij,ij->i", fu, Nn.mean(1)) > 0                 # geometric winding against N (pipeline rule)
    Tt[flip] = Tt[flip][:, [0, 2, 1]]
    UVt[flip] = UVt[flip][:, [0, 2, 1]]
    Nn[flip] = Nn[flip][:, [0, 2, 1]]
    out = dict(V=np.concatenate([a2["V"], V]), T=np.concatenate([a2["T"], Tt + len(a2["V"])]), UV=np.concatenate([a2["UV"], UVt]),
               N=np.concatenate([a2["N"], Nn]), MK=np.concatenate([a2["MK"], np.full(len(Tt), mk)]),
               DS=np.concatenate([a2["DS"], np.ones(len(Tt), a2["DS"].dtype)]))
    F.log(f"nozzle petals: exit x {xe:.0f}, r_exit {r_exit:.1f}, axis y {cy:.1f} z {cz:.1f}")
    return out, int(len(Tt))


def fix_uv(arr):
    """triangles with zero UV area (the FG fin sides: they were hidden under the full-size marking decal planes, which
    we drop) have no tangent frame -> the normal-mapped paint rendered them near black (r3 shots). They get a planar
    mapping (dominant axis) shrunk to ~1.5 texels around the texel they used, so the colour stays and the tangent
    frame exists. Corner normals of the fin sides are pointed away from the fin's mid plane."""
    V, T, UV, N = arr["V"], arr["T"], arr["UV"], arr["N"]
    e1, e2 = UV[:, 1] - UV[:, 0], UV[:, 2] - UV[:, 0]
    bad = np.abs(e1[:, 0] * e2[:, 1] - e1[:, 1] * e2[:, 0]) < 1e-9
    if bad.any():
        P = V[T[bad]]                                         # (n, 3, 3)
        fn = np.cross(P[:, 1] - P[:, 0], P[:, 2] - P[:, 0])
        ax = np.argmax(np.abs(fn), axis=1)
        for k in range(3):
            s = ax == k
            if not s.any():
                continue
            a, b = [i for i in range(3) if i != k]
            Q = P[s]
            lo, hi = Q.reshape(-1, 3).min(0), Q.reshape(-1, 3).max(0)
            idx = np.nonzero(bad)[0][s]
            c0 = UV[idx].mean(1, keepdims=True)                # keep the colour they had (their single texel) ...
            cc = Q.mean(1)
            on_fin = (np.abs(cc[:, 1]) < 8.0) & (cc[:, 2] > 110.0) & (cc[:, 0] < -350.0)
            c0[on_fin] = np.array([[0.62, 0.935]])             # ... except the fin sides: their texel is the dark top-wing grey;
                                                                # a real fin is the light grey (plain patch, no panel lines)
            q = Q - Q.mean(1, keepdims=True)
            sc = 0.0008 / max(1e-6, float(np.abs(q).max()))      # ~1.5 texel tangent-frame triangle around it
            UV[idx] = c0 + np.stack([q[:, :, a], q[:, :, b]], -1) * sc
            if k == 1 and on_fin.any():                        # v2 round 3: fin sides get a real planar map into an unused
                u0, v0, u1, v1 = FIN_RECT                      # atlas rect (airframe_bake paints the fin + generic tail code)
                F_ = Q[on_fin]
                u = u0 + (F_[:, :, 0] - FIN_X[0]) / (FIN_X[1] - FIN_X[0]) * (u1 - u0)
                left = F_[:, :, 1].mean(1) < 0.3                # left side seen from outside: +x runs to the viewer's left
                u[left] = u0 + u1 - u[left]
                v = v0 + (F_[:, :, 2] - FIN_Z[0]) / (FIN_Z[1] - FIN_Z[0]) * (v1 - v0)
                UV[idx[on_fin]] = np.stack([u, v], -1)
    # round 4: ALL fin / rudder side faces (not only the zero-UV ones) get the planar fin-rect mapping, so the fin code,
    # serial and fin cap cover the whole side
    Pa = V[T]
    ca = Pa.mean(1)
    fn_a = np.cross(Pa[:, 1] - Pa[:, 0], Pa[:, 2] - Pa[:, 0])
    side = (np.abs(ca[:, 1]) < 8.0) & (ca[:, 2] > 110.0) & (ca[:, 0] < -350.0) &            (np.abs(fn_a[:, 1]) > 0.7 * np.linalg.norm(fn_a, axis=1))
    if side.any():
        u0, v0, u1, v1 = FIN_RECT
        Fs = Pa[side]
        u = u0 + (Fs[:, :, 0] - FIN_X[0]) / (FIN_X[1] - FIN_X[0]) * (u1 - u0)
        left = Fs[:, :, 1].mean(1) < 0.3
        u[left] = u0 + u1 - u[left]
        v = v0 + (Fs[:, :, 2] - FIN_Z[0]) / (FIN_Z[1] - FIN_Z[0]) * (v1 - v0)
        UV[side] = np.stack([u, v], -1)
    c = V[T].mean(1)
    fin = (np.abs(c[:, 1]) < 8.0) & (c[:, 2] > 110.0) & (c[:, 0] < -350.0) & (np.abs(N.mean(1)[:, 1]) > 0.5)
    flips = 0
    if fin.any():
        mid = float(np.median(c[fin, 1]))
        want = np.where(c[:, 1] >= mid, 1.0, -1.0)
        flip = fin[:, None] & (np.sign(N[:, :, 1]) != want[:, None])
        N[flip] = -N[flip]
        flips = int(flip.sum())
    return int(bad.sum()), flips


def main():
    t0 = time.time()
    OUT.mkdir(parents=True, exist_ok=True)
    repo = F.Repo()
    texres = F.TexResolver(repo)
    loader = F.Loader(repo, texres, F.skip_model)
    root = loader.load("Models/F-16.xml", ())
    parts, dropped = F.collect(root)
    ext = parts["F16_Exterior"]
    new = {n: F.Part(n) for n in ["F16_Body"] + list(SURF)}
    for (n, mask), label in zip(ext.chunks, ext.objects):
        if re.search(DROP, n.name):                   # unit / national markings: no real livery on our aircraft
            dropped[label + " (airframe: marking)"] = len(n.T)
            continue
        decal = np.array([bool(F.MATKEYS[k][0]) and "f16trans" in F.MATKEYS[k][0] for k in n.MK], bool)
        mask = mask & ~decal                          # tail codes / unit band decals (f16trans.png)
        if not mask.any():
            continue
        tgt = next((k for k, s in SURF.items() if re.search(s["objs"], n.name)), "F16_Body")
        new[tgt].chunks.append((n, mask))
        new[tgt].objects.append(label)
    texout = F.TexOut(repo)
    info = dict(made=time.strftime("%Y-%m-%d %H:%M:%S"), script="Scripts/aircraft/airframe_split.py",
                source=dict(repo=F.REPO_URL, commit=F.SHA, license="GPL-2.0-or-later"), parts={})
    bake = []
    for nm, part in new.items():
        if not part.chunks:
            F.log(f"[warn] {nm}: no objects")
            continue
        arr = F.build_part_arrays(part)
        rec = dict(objects=sorted(set(part.objects)), triangles=int(len(arr["T"])))
        rec["uv_fix"] = fix_uv(arr)                       # (zero-UV-area tris remapped, fin corner normals flipped)
        F.log(f"{nm}: uv / normal fix {rec['uv_fix']}")
        bake.append({k: arr[k].copy() for k in ("V", "T", "UV", "N", "MK")} | dict(part=nm))   # absolute coords for airframe_bake.py
        if nm in SURF:
            s = SURF[nm]
            c_ue = F.fg_to_ue(np.array(s["c"]))
            a_ue = F.fgdir_to_ue(np.array(s["a"]))
            a_ue = a_ue / np.linalg.norm(a_ue)
            used = arr["V"][np.unique(arr["T"])]
            p = used.mean(0) - c_ue                       # surface centroid relative to the hinge
            mv = np.cross(a_ue, p)                        # motion of the centroid for a small + rotation (numeric, as FQuat)
            if (s["sense"] == "down" and mv[2] > 0) or (s["sense"] == "right" and mv[1] < 0):
                a_ue = -a_ue
            arr["V"] = arr["V"] - c_ue                    # mesh pivot = hinge point
            rec.update(hinge_ue_cm=c_ue.round(3).tolist(), axis_ue=a_ue.round(6).tolist(), sense=s["sense"],
                       centroid_rel_cm=p.round(1).tolist())
        mats, gid = F.material_table(arr, texout, nm)
        F.write_obj(nm, arr, mats, gid)
        # v2: welded, angle-weighted crease normals, PN-triangle subdivision (2 levels on the body, 1 on surfaces)
        a2, st = V2.smooth_v2(arr, levels=2 if nm == "F16_Body" else 1)
        if nm == "F16_Body":
            a2, nm9 = add_aim9(a2, arr)
            a2, npet = add_petals(a2, arr)
            F.log(f"nozzle petals: {npet} tris")
            F.log(f"AIM-9 shapes: {nm9} tris")
        m2, g2 = F.material_table(a2, texout, nm)
        F.write_obj(nm + "_v2", a2, m2, g2)
        rec["v2"] = st
        F.log(f"{nm}_v2: {st}")
        used = arr["V"][np.unique(arr["T"])]
        rec.update(bbox_ue_cm=dict(min=used.min(0).round(1).tolist(), max=used.max(0).round(1).tolist()),
                   materials=[dict(name=g["name"], texture=g["texture"], kd=g["kd"], transparent=g["transparent"],
                                   triangles=g["triangles"]) for g in mats])
        info["parts"][nm] = rec
        F.log(f"{nm}: {rec['triangles']} tris, {len(rec['objects'])} objects")
    # light points from the body extents (wing tips, fin top, belly) - positions only, our own lights
    b = info["parts"]["F16_Body"]["bbox_ue_cm"]
    body = F.build_part_arrays(new["F16_Body"])
    V = body["V"][np.unique(body["T"])]
    tipL, tipR = V[np.argmin(V[:, 1])], V[np.argmax(V[:, 1])]
    fin = V[np.argmax(V[:, 2])]
    info["lights_ue_cm"] = dict(nav_left=tipL.round(1).tolist(), nav_right=tipR.round(1).tolist(), fin_top=fin.round(1).tolist(),
                                tail=[round(float(b["min"][0]), 1), 0.0, round(float(fin[2]) - 80.0, 1)])
    for lf in ("LICENSE", "copyright.txt", "authors.txt"):
        p = repo.get(lf)
        if p is not None:
            shutil.copyfile(p, OUT / lf)
    (OUT / "airframe.json").write_text(json.dumps(info, indent=1), encoding="utf-8")
    np.savez_compressed(OUT / "bake_input.npz", **{f"{b['part']}__{k}": v for b in bake for k, v in b.items() if k != "part"},
                        texkeys=np.array([F.MATKEYS[k][0] or "" for k in range(len(F.MATKEYS))]),
                        mnames=np.array([str(F.MATKEYS[k][4]) for k in range(len(F.MATKEYS))]))
    F.log(f"done in {time.time() - t0:.0f} s -> {OUT}")


if __name__ == "__main__":
    main()
