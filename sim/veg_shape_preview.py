"""Standalone previews of the tree prototypes (sim/veg_shape.py new, sim/veg_v2.py current) - no Unreal.
A small numpy z-buffer rasteriser with a sun shadow map; the shading imitates M_GyroTree2 (trees_foliage2.hlsl): vertex
tint x per-tree variation, AO into base colour (AoBase 0.7) and ambient (AoAmb 0.85), sun + sky. Approximations (stated
on the preview page): no translucency, no leaf-noise normals, no TAA / mips; 'shader' variant = the planned per-pixel
ragged crown edge (world noise cut where the crown turns away from the camera) + per-clump top light, approximated here.

    python -I sim/veg_shape_preview.py OUTDIR           sheets + groups + forest patch PNGs, preview.json
"""
import json, math, os, sys, time, site
if sys.flags.isolated:
    site.addsitedir(site.getusersitepackages())
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import numpy as np                                        # noqa: E402
import veg_v2 as V2                                       # noqa: E402
import veg_shape as S                                     # noqa: E402

SUN = np.array([-0.45, 0.72, 0.38]); SUN /= np.linalg.norm(SUN)
SUN_I, SKY_I = 3.2, np.array([0.75, 0.85, 1.05]) * 0.95
BG = np.array([0.55, 0.62, 0.70])
GROUND = np.array([0.055, 0.062, 0.038])
GROUP_OF = {"pine": "pine", "bpine": "bpine", "broad": "broad", "shrub": "shrub", "rock": "rock"}


def proto_arrays(pid, far, new):
    nm = V2.PROTOS[pid][0]
    g = V2.GROUPS[V2.SPECIES_OF[pid]]
    trunk = V2.TRUNK["pine" if nm in ("pine", "bpine") else ("broad" if nm == "broad" else "shrub")]
    m = (S.build_proto if new else V2.build_proto)(pid, far)
    P, Nn, Cu, I = m.arrays(V2.TINT[g], V2.TINT[g] if nm == "rock" else trunk)
    import veg_build as V
    col = V.srgb_to_lin(Cu[:, :3].astype(np.float64))
    kind = Cu[:, 3] // 64
    ao = (Cu[:, 3] % 64) / 63.0
    return P.astype(np.float64), Nn.astype(np.float64), col, kind.astype(np.float64), ao, I.reshape(-1, 3), m.ntri


def instance(arr, pos, h, r, yaw, tintmul):
    """unit prototype -> world (y up) at pos with height h, crown radius r, yaw; normals by the inverse transpose."""
    P, Nn, col, kind, ao, I, _ = arr
    c, s = math.cos(yaw), math.sin(yaw)
    Ry = np.array([[c, 0, -s], [0, 1, 0], [s, 0, c]])
    sc = np.array([r, h, r])
    Pw = (P * sc) @ Ry.T + pos
    Nw = (Nn / sc) @ Ry.T
    Nw /= np.linalg.norm(Nw, axis=1, keepdims=True) + 1e-12
    colw = np.where((kind == 0)[:, None], col, col * tintmul)
    return Pw, Nw, colw, kind, ao, I


class Cam:
    def __init__(self, eye, tgt, fov=None, ortho=None, W=640, H=480):
        self.eye = np.asarray(eye, np.float64); f = np.asarray(tgt, np.float64) - self.eye
        self.f = f / np.linalg.norm(f)
        upv = np.array([0, 1.0, 0]) if abs(self.f[1]) < 0.99 else np.array([0, 0, 1.0])
        self.r = np.cross(self.f, upv); self.r /= np.linalg.norm(self.r)
        self.u = np.cross(self.r, self.f)
        self.fov, self.ortho, self.W, self.H = fov, ortho, W, H

    def project(self, P):
        d = P - self.eye
        x, y, z = d @ self.r, d @ self.u, d @ self.f
        if self.ortho:
            k = self.W / self.ortho
            return self.W / 2 + x * k, self.H / 2 - y * k, z
        k = (self.W / 2) / math.tan(math.radians(self.fov) / 2)
        zz = np.maximum(z, 1e-3)
        return self.W / 2 + x / zz * k, self.H / 2 - y / zz * k, z


def vnoise(p):
    i = np.floor(p); f = p - i; u = f * f * (3 - 2 * f)
    def h(o):
        q = i + o
        return np.modf(np.sin(q @ np.array([127.1, 311.7, 74.7])) * 43758.5453)[0] % 1.0
    n = 0
    for dx in (0, 1):
        for dy in (0, 1):
            for dz in (0, 1):
                w = (u[:, 0] if dx else 1 - u[:, 0]) * (u[:, 1] if dy else 1 - u[:, 1]) * (u[:, 2] if dz else 1 - u[:, 2])
                n = n + w * h(np.array([dx, dy, dz], np.float64))
    return n


def raster(cam, tris, attrs, ragged=False, depth_only=False):
    """tris (T,3,3) world, attrs (T,3,k) [col3, n3, ao, kind, pos3] -> zbuf, gbuf."""
    W, H = cam.W, cam.H
    zb = np.full((H, W), np.inf)
    gb = None if depth_only else np.zeros((H, W, attrs.shape[2]))
    T = len(tris)
    X, Y, Z = cam.project(tris.reshape(-1, 3))
    X, Y, Z = X.reshape(T, 3), Y.reshape(T, 3), Z.reshape(T, 3)
    for t in range(T):
        if (Z[t] <= 0.5).any():
            continue
        x, y = X[t], Y[t]
        x0, x1 = max(int(math.floor(x.min())), 0), min(int(math.ceil(x.max())), W - 1)
        y0, y1 = max(int(math.floor(y.min())), 0), min(int(math.ceil(y.max())), H - 1)
        if x0 > x1 or y0 > y1:
            continue
        area = (x[1] - x[0]) * (y[2] - y[0]) - (x[2] - x[0]) * (y[1] - y[0])
        if abs(area) < 1e-9:
            continue
        gx, gy = np.meshgrid(np.arange(x0, x1 + 1) + 0.5, np.arange(y0, y1 + 1) + 0.5)
        w0 = ((x[1] - gx) * (y[2] - gy) - (x[2] - gx) * (y[1] - gy)) / area
        w1 = ((x[2] - gx) * (y[0] - gy) - (x[0] - gx) * (y[2] - gy)) / area
        w2 = 1 - w0 - w1
        ins = (w0 >= 0) & (w1 >= 0) & (w2 >= 0)
        if not ins.any():
            continue
        yy, xx = np.nonzero(ins)
        b = np.stack((w0[ins], w1[ins], w2[ins]), 1)
        z = b @ Z[t]
        py, px = yy + y0, xx + x0
        ok = z < zb[py, px]
        if not ok.any():
            continue
        py, px, z, b = py[ok], px[ok], z[ok], b[ok]
        if depth_only:
            zb[py, px] = z
            continue
        a = b @ attrs[t]
        if ragged and attrs[t, 0, 7] > 0.5:               # foliage: cut holes where the crown turns away (silhouette)
            pos = a[:, 8:11]
            n = a[:, 3:6] / (np.linalg.norm(a[:, 3:6], axis=1, keepdims=True) + 1e-9)
            v = pos - cam.eye; v /= np.linalg.norm(v, axis=1, keepdims=True)
            rim = 1 - np.abs((n * v).sum(1))
            nz = 0.65 * vnoise(pos / 0.9) + 0.35 * vnoise(pos / 0.37)
            keep = nz > np.clip((rim - 0.45) / 0.5, 0, 1) * 0.8
            if not keep.any():
                continue
            py, px, z, a = py[keep], px[keep], z[keep], a[keep]
        zb[py, px] = z
        gb[py, px] = a
    return zb, gb


def shade(cam, zb, gb, smap=None, toplight=False):
    H, W = zb.shape
    img = np.tile(BG, (H, W, 1))
    m = np.isfinite(zb)
    col, n, ao, kind, pos = gb[m, 0:3], gb[m, 3:6], gb[m, 6], gb[m, 7], gb[m, 8:11]
    n /= np.linalg.norm(n, axis=1, keepdims=True) + 1e-9
    v = cam.eye - pos; v /= np.linalg.norm(v, axis=1, keepdims=True)
    n = np.where(((n * v).sum(1) < 0)[:, None] & (kind[:, None] >= 0), -n, n) if False else n
    fol = kind > 0.5
    sh = np.ones(len(pos))
    if smap is not None:
        sc, szb = smap
        X, Y, Z = sc.project(pos)
        xi, yi = np.clip(X.astype(int), 0, sc.W - 1), np.clip(Y.astype(int), 0, sc.H - 1)
        acc = np.zeros(len(pos))
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                acc += (Z - 0.35 <= szb[np.clip(yi + dy, 0, sc.H - 1), np.clip(xi + dx, 0, sc.W - 1)])
        sh = acc / 9.0
    ndl = np.clip(n @ SUN, 0, 1)
    if toplight:                                          # planned shader: wrap light on foliage (pads read lit on top)
        ndl = np.where(fol, np.clip((n @ SUN + 0.25) / 1.25, 0, 1), ndl)
    base = np.where(fol[:, None], col * 0.9 * (1 + 0.0) * (1 - 0.7 + 0.7 * ao)[:, None], col * (0.3 + 0.7 * ao)[:, None])
    gnd = kind < -0.5
    base = np.where(gnd[:, None], col, base)
    amb = (1 - 0.85 + 0.85 * ao) * (0.55 + 0.45 * np.clip(n[:, 1], -1, 1) * 0.5 + 0.225)
    lit = base * (SUN_I * ndl * sh)[:, None] + base * SKY_I[None] * amb[:, None]
    img[m] = 1 - np.exp(-lit * 1.6)
    out = np.clip(img, 0, 1) ** (1 / 2.2)
    return (out * 255).astype(np.uint8)


def scene_arrays(items, ground=None):
    """items: list of instance() tuples -> tris, attrs."""
    T, A = [], []
    for Pw, Nw, colw, kind, ao, I in items:
        at = np.concatenate((colw, Nw, ao[:, None], kind[:, None], Pw), 1)
        T.append(Pw[I]); A.append(at[I])
    if ground is not None:
        (x0, x1, z0, z1, y) = ground
        g = np.array([[x0, y, z0], [x1, y, z0], [x1, y, z1], [x0, y, z1]], np.float64)
        Ig = np.array([[0, 1, 2], [0, 2, 3]])
        at = np.concatenate((np.tile(GROUND, (4, 1)), np.tile([0, 1, 0], (4, 1)), np.ones((4, 1)), -np.ones((4, 1)), g), 1)
        T.append(g[Ig]); A.append(at[Ig])
    return np.concatenate(T), np.concatenate(A)


def render(items, cam, ground=None, shadows=True, ragged=False, toplight=False):
    tris, attrs = scene_arrays(items, ground)
    smap = None
    if shadows:
        c = attrs[:, :, 8:11].reshape(-1, 3)
        ctr = (c.min(0) + c.max(0)) / 2
        ext = np.linalg.norm(c.max(0) - c.min(0)) * 1.05
        res = 2048 if ext > 60 else 1024
        sc = Cam(ctr + SUN * ext, ctr, ortho=ext, W=res, H=res)
        szb, _ = raster(sc, tris, attrs, ragged=False, depth_only=True)
        smap = (sc, szb)
    zb, gb = raster(cam, tris, attrs, ragged=ragged)
    return shade(cam, zb, gb, smap, toplight)


def tintmul(rg, g):
    return np.asarray(V2.TINT[g]) * 0 + rg.uniform(0.88, 1.12) * rg.uniform(0.95, 1.05, 3)


def main(out):
    from PIL import Image, ImageDraw
    os.makedirs(out, exist_ok=True)
    t0 = time.time()
    pids = [0, 1, 2, 3, 4, 5, 6, 7, 8, 9]                 # rocks unchanged (veg_v2.proto_rock)
    meta = dict(made=time.strftime("%Y-%m-%d %H:%M:%S"), code="sim/veg_shape.py + sim/veg_shape_preview.py", protos={}, images={})
    cache = {}

    def arr(pid, far, new):
        k = (pid, far, new)
        if k not in cache:
            cache[k] = proto_arrays(pid, far, new)
        return cache[k]

    # ---- 1. sheets: per prototype side + top, current vs new ------------------------------------------------------
    for pid in pids:
        nm, var = V2.PROTOS[pid]
        g = V2.GROUPS[V2.SPECIES_OF[pid]]
        Href, Rref = {"pine": (12, 4), "bpine": (11, 4), "broad": (11, 4.4), "shrub": (2.5, 1.6)}[g]
        if nm == "pine" and var == 3:
            Href, Rref = 12, 2.8
        tiles = []
        for new in (False, True):
            for far in (False, True):
                a = arr(pid, far, new)
                it = instance(a, np.zeros(3), Href, Rref, 0.3, np.ones(3))
                gr = (-Href, Href, -Href, Href, 0.0)
                side = Cam((Href * 1.6, Href * 0.55, Href * 1.6), (0, Href * 0.5, 0), fov=40, W=300, H=300)
                img_s = render([it], side, gr, shadows=True)
                if far:
                    tiles.append(("%s far" % ("NEW" if new else "CUR"), img_s, a[6]))
                    continue
                top = Cam((0.001, Href * 3, 0), (0, 0, 0), ortho=Rref * 3.4, W=300, H=300)
                img_t = render([it], top, gr, shadows=True)
                tiles.append(("%s side" % ("NEW" if new else "CUR"), img_s, a[6]))
                tiles.append(("%s top" % ("NEW" if new else "CUR"), img_t, a[6]))
        # shader approx (new, near): ragged + top light
        a = arr(pid, False, True)
        it = instance(a, np.zeros(3), Href, Rref, 0.3, np.ones(3))
        side = Cam((Href * 1.6, Href * 0.55, Href * 1.6), (0, Href * 0.5, 0), fov=40, W=300, H=300)
        tiles.append(("NEW+shader", render([it], side, (-Href, Href, -Href, Href, 0.0), ragged=True, toplight=True), a[6]))
        sheet = Image.new("RGB", (300 * len(tiles), 330), (245, 245, 245))
        d = ImageDraw.Draw(sheet)
        for i, (lab, im, nt) in enumerate(tiles):
            sheet.paste(Image.fromarray(im), (300 * i, 30))
            d.text((300 * i + 6, 8), "%s  %d tri" % (lab, nt), fill=(0, 0, 0))
        fn = "sheet_%s%d.png" % (nm, var)
        sheet.save(os.path.join(out, fn))
        meta["protos"]["%s%d" % (nm, var)] = dict(new_near=arr(pid, False, True)[6], new_far=arr(pid, True, True)[6],
                                                   cur_near=arr(pid, False, False)[6], cur_far=arr(pid, True, False)[6], sheet=fn)
        print("sheet", fn, round(time.time() - t0, 1), flush=True)

    # ---- 2. groups of 16 per species: varied scale / yaw / tint, current vs new vs new+shader ---------------------
    groups = dict(pine=[0, 1, 2], bpine=[3], broad=[4, 5, 6, 7], shrub=[8, 9])
    for g, pl in groups.items():
        rg = np.random.default_rng(77)
        Href, Rref = {"pine": (12, 4), "bpine": (11, 4), "broad": (11, 4.4), "shrub": (2.5, 1.6)}[g]
        sp = Rref * 1.5
        trees = []
        for k in range(16):
            i, j = k % 4, k // 4
            pos = np.array([(i - 1.5) * sp + rg.uniform(-0.3, 0.3) * sp, 0, (j - 1.5) * sp + rg.uniform(-0.3, 0.3) * sp])
            s = rg.uniform(0.7, 1.3)
            trees.append((pl[rg.integers(len(pl))], pos, Href * s * rg.uniform(0.9, 1.1), Rref * s * rg.uniform(0.85, 1.15),
                          rg.uniform(0, 2 * math.pi), tintmul(rg, g)))
        ext = sp * 3 + Rref * 2
        cam = Cam((ext * 1.25, ext * 0.75, ext * 1.0), (0, Href * 0.35, 0), fov=45, W=640, H=420)
        gr = (-ext, ext, -ext, ext, 0.0)
        imgs = []
        for lab, new, rag in (("CUR", False, False), ("NEW", True, False), ("NEW+shader", True, True)):
            items = [instance(arr(p, False, new), pos, h, r, yaw, tm) for p, pos, h, r, yaw, tm in trees]
            imgs.append((lab, render(items, cam, gr, ragged=rag, toplight=rag)))
        for lab, im in imgs:
            fn = "group_%s_%s.png" % (g, lab.replace("+", "_").lower())
            Image.fromarray(im).save(os.path.join(out, fn))
            meta["images"][fn] = dict(group=g, variant=lab, trees=16)
        print("group", g, round(time.time() - t0, 1), flush=True)

    # ---- 3. forest patch seen from ~300 m (about 4 px per m, like a 1600 px shot at 70 deg fov) ---------------------
    rg = np.random.default_rng(5)
    L = 150.0
    trees = []
    pts = []
    while len(pts) < 400:                                 # ~180 trees / ha on 2.25 ha (closed canopy, as the tiles + infill)
        p = rg.uniform(-L / 2, L / 2, 2)
        if all((p[0] - q[0]) ** 2 + (p[1] - q[1]) ** 2 > 3.7 ** 2 for q in pts):
            pts.append(p)
    for p in pts:
        x = (p[0] + 40) / 60.0 + 0.4 * math.sin(p[1] / 23.0)          # pine on one side, oak on the other, mixed band
        pine = rg.random() < 1 / (1 + math.exp(-2.0 * x))
        if pine:
            pid = [0, 0, 1, 2, 3][rg.integers(5)]
        else:
            pid = [4, 5, 6, 7][rg.integers(4)]
        g = V2.GROUPS[V2.SPECIES_OF[pid]]
        h = rg.uniform(8, 15)
        r = h * rg.uniform(0.34, 0.46) * (0.75 if pid == 2 else 1.0)
        trees.append((pid, np.array([p[0], 0, p[1]]), h, r, rg.uniform(0, 2 * math.pi), tintmul(rg, g)))
    cam = Cam((230, 190, 150), (0, 0, 0), fov=26, W=1200, H=700)
    gr = (-L, L, -L, L, 0.0)
    for lab, new, rag in (("CUR", False, False), ("NEW", True, False), ("NEW+shader", True, True)):
        items = [instance(arr(p, False, new), pos, h, r, yaw, tm) for p, pos, h, r, yaw, tm in trees]
        im = render(items, cam, gr, ragged=rag, toplight=rag)
        fn = "forest300_%s.png" % lab.replace("+", "_").lower()
        Image.fromarray(im).save(os.path.join(out, fn))
        meta["images"][fn] = dict(variant=lab, trees=len(trees), cam_dist_m=round(float(np.linalg.norm(cam.eye)), 1), fov=26, px=[1200, 700])
        print("forest", lab, round(time.time() - t0, 1), flush=True)
    meta["seconds"] = round(time.time() - t0, 1)
    meta["approx"] = ("software rasteriser; shading imitates M_GyroTree2 (vertex tint, AO 0.7/0.85, sun + sky, sun shadow map); "
                      "no translucency / leaf-noise normals / TAA; NEW+shader = planned ragged crown edge + wrap light, approximated")
    json.dump(meta, open(os.path.join(out, "preview.json"), "w"), indent=1)
    print("done", out, meta["seconds"])


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else r"C:\GyroSimTiles\veg\shape_preview")
