"""airframe_v2.py - smoother exterior geometry for the airframe v2 pass (used by airframe_split.py).

  weld()        vertices welded by position (0.05 cm) across the FG objects of a part, so smoothing crosses object seams
  normals()     angle-weighted corner normals with a crease angle: faces closer than CREASE deg share a normal
                (fuselage, nose, intakes, canopy sill blend), sharper edges stay hard (wing / tail leading and trailing
                edges, which meet at ~150-180 deg)
  subdivide()   one 1 -> 4 split per level; each new edge midpoint is the PN-triangle (curved point-normal triangle)
                midpoint when the edge is smooth on both sides, the straight midpoint on crease / open / non-manifold
                edges -> curved surfaces round out, hard edges and silhouettes of thin surfaces stay crisp, no cracks
                (one midpoint per welded edge)
Arrays use fetch_f16_model.build_part_arrays' layout: V (nv,3) UE cm, T (n,3), UV (n,3,2), N (n,3,3), MK (n,), DS (n,).
"""
import numpy as np

CREASE = 42.0
WELD_CM = 0.05


def weld(arr):
    V, T = arr["V"], arr["T"]
    key = np.round(V / WELD_CM).astype(np.int64)
    _, first, inv = np.unique(key, axis=0, return_index=True, return_inverse=True)
    inv = inv.reshape(-1)
    out = dict(arr)
    out["V"] = V[first]
    out["T"] = inv[T]
    good = (out["T"][:, 0] != out["T"][:, 1]) & (out["T"][:, 1] != out["T"][:, 2]) & (out["T"][:, 0] != out["T"][:, 2])
    for k in ("T", "UV", "N", "MK", "DS"):
        out[k] = out[k][good]
    return out


def _face(V, T):
    p0, p1, p2 = V[T[:, 0]], V[T[:, 1]], V[T[:, 2]]
    fn = np.cross(p1 - p0, p2 - p0)
    fu = fn / np.maximum(np.linalg.norm(fn, axis=1, keepdims=True), 1e-12)
    ang = np.zeros((len(T), 3))
    for i, (a, b, c) in enumerate(((p0, p1, p2), (p1, p2, p0), (p2, p0, p1))):
        u, v = b - a, c - a
        cs = np.einsum("ij,ij->i", u, v) / np.maximum(np.linalg.norm(u, axis=1) * np.linalg.norm(v, axis=1), 1e-12)
        ang[:, i] = np.arccos(np.clip(cs, -1, 1))
    return fu, ang


def normals(arr, crease=CREASE):
    """corner normals: for each corner, sum of angle x unit normal of the faces around the same welded vertex whose
    normal is within the crease angle of this face. Sign follows the incoming corner normals (the FG files' outward
    normals are opposite to the geometric winding in this pipeline)."""
    V, T = arr["V"], arr["T"]
    fu, ang = _face(V, T)
    sgn = np.sign(np.einsum("ij,ij->i", fu, arr["N"].mean(1)))
    sgn[sgn == 0] = 1.0
    fu = fu * sgn[:, None]                                   # face normals pointing like the shading normals
    m = len(T)
    cv, cf = T.ravel(), np.repeat(np.arange(m), 3)
    w = ang.ravel()
    order = np.argsort(cv, kind="stable")
    sv = cv[order]
    starts = np.r_[0, np.nonzero(np.diff(sv))[0] + 1]
    lens = np.diff(np.r_[starts, len(sv)])
    cosc = np.cos(np.radians(crease))
    acc = np.zeros((3 * m, 3))
    gi = 0
    while gi < len(starts):
        gj, tot = gi, 0
        while gj < len(starts) and tot < 3_000_000:
            tot += int(lens[gj]) ** 2
            gj += 1
        st, ln = starts[gi:gj], lens[gi:gj]
        rep = np.repeat(np.arange(len(st)), ln * ln)
        base = np.repeat(st, ln * ln)
        within = np.arange(len(rep)) - np.repeat(np.cumsum(ln * ln) - ln * ln, ln * ln)
        L = ln[rep]
        a = order[base + within // L]
        b = order[base + within % L]
        fa, fb = cf[a], cf[b]
        ok = np.einsum("ij,ij->i", fu[fa], fu[fb]) >= cosc - 1e-9
        np.add.at(acc, a[ok], fu[fb[ok]] * w[b[ok], None])
        gi = gj
    acc = acc.reshape(m, 3, 3)
    n = acc / np.maximum(np.linalg.norm(acc, axis=2, keepdims=True), 1e-12)
    bad = np.linalg.norm(acc, axis=2) < 1e-9
    n[bad] = np.repeat(fu[:, None, :], 3, axis=1)[bad]
    out = dict(arr)
    out["N"] = n
    return out


def subdivide(arr):
    V, T, N, UV = arr["V"], arr["T"], arr["N"], arr["UV"]
    m = len(T)
    E = np.stack([T[:, [0, 1]], T[:, [1, 2]], T[:, [2, 0]]], 1)          # (m,3,2) edges per tri: 01, 12, 20
    EN = np.stack([N[:, [0, 1]], N[:, [1, 2]], N[:, [2, 0]]], 1)         # (m,3,2,3) corner normals at the edge ends
    lo, hi = E.min(2), E.max(2)
    key = lo.astype(np.int64) * (len(V) + 1) + hi
    flipped = E[:, :, 0] > E[:, :, 1]
    nlo = np.where(flipped[..., None], EN[:, :, 1], EN[:, :, 0])            # normal at the lower-index end, per tri edge
    nhi = np.where(flipped[..., None], EN[:, :, 0], EN[:, :, 1])
    k = key.ravel()
    uk, inv, cnt = np.unique(k, return_inverse=True, return_counts=True)
    inv = inv.reshape(-1)
    nlo_f, nhi_f = nlo.reshape(-1, 3), nhi.reshape(-1, 3)
    # an edge is smooth when exactly two tris share it and both give the same normals at both ends
    ref_lo = np.zeros((len(uk), 3)); ref_hi = np.zeros((len(uk), 3))
    ref_lo[inv] = nlo_f; ref_hi[inv] = nhi_f                               # one representative per edge (last write)
    same = (np.einsum("ij,ij->i", ref_lo[inv], nlo_f) > 0.999) & (np.einsum("ij,ij->i", ref_hi[inv], nhi_f) > 0.999)
    allsame = np.ones(len(uk), bool)
    np.logical_and.at(allsame, inv, same)
    smooth = allsame & (cnt == 2)
    elo, ehi = lo.ravel(), hi.ravel()
    e_lo = np.zeros(len(uk), np.int64); e_hi = np.zeros(len(uk), np.int64)
    e_lo[inv] = elo; e_hi[inv] = ehi
    p0, p1 = V[e_lo], V[e_hi]
    mid = (p0 + p1) / 2
    w01 = np.einsum("ij,ij->i", p1 - p0, ref_lo)
    w10 = np.einsum("ij,ij->i", p0 - p1, ref_hi)
    pn = mid - (w01[:, None] * ref_lo + w10[:, None] * ref_hi) / 8.0
    mid = np.where(smooth[:, None], pn, mid)
    nv = len(V)
    V2 = np.concatenate([V, mid])
    M = (nv + inv).reshape(m, 3)                                           # midpoint vertex of edges 01, 12, 20
    a, b, c = T[:, 0], T[:, 1], T[:, 2]
    m01, m12, m20 = M[:, 0], M[:, 1], M[:, 2]
    T2 = np.concatenate([np.stack([a, m01, m20], 1), np.stack([m01, b, m12], 1), np.stack([m20, m12, c], 1), np.stack([m01, m12, m20], 1)])
    uva, uvb, uvc = UV[:, 0], UV[:, 1], UV[:, 2]
    u01, u12, u20 = (uva + uvb) / 2, (uvb + uvc) / 2, (uvc + uva) / 2
    UV2 = np.concatenate([np.stack([uva, u01, u20], 1), np.stack([u01, uvb, u12], 1), np.stack([u20, u12, uvc], 1), np.stack([u01, u12, u20], 1)])
    na, nb, nc = N[:, 0], N[:, 1], N[:, 2]
    n01, n12, n20 = (na + nb) / 2, (nb + nc) / 2, (nc + na) / 2
    N2 = np.concatenate([np.stack([na, n01, n20], 1), np.stack([n01, nb, n12], 1), np.stack([n20, n12, nc], 1), np.stack([n01, n12, n20], 1)])
    rep = lambda x: np.concatenate([x, x, x, x])                           # noqa: E731
    return dict(V=V2, T=T2, UV=UV2, N=N2, MK=rep(arr["MK"]), DS=rep(arr["DS"])), int(smooth.sum()), len(uk)


def smooth_v2(arr, levels=1):
    """weld -> normals -> (subdivide -> normals) x levels. Returns (new arrays, stats)."""
    a = normals(weld(arr))
    st = []
    for _ in range(levels):
        a, ns, ne = subdivide(a)
        a = normals(a)
        st.append(dict(smooth_edges=ns, edges=ne, tris=int(len(a["T"]))))
    return a, st
