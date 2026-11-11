"""Impostor trees from the real downloaded models (11-11): bake -> atlases -> software impostor renders -> preview page.

    python -I sim/impostor/pipeline.py --bake       headless Blender (lock) -> frames EXR   (bake_blender.py)
    python -I sim/impostor/pipeline.py --assemble   frames -> atlases T_Imp_<name>_A.png (albedo sRGB + alpha),
                                                    T_Imp_<name>_B.png (oct normal xy, depth, AO)  + meta json
    python -I sim/impostor/pipeline.py --real       headless Blender (lock): full-mesh reference renders of the scenes
    python -I sim/impostor/pipeline.py --imp        software impostor renders of the same scenes (reads the 8-bit atlases)
    python -I sim/impostor/pipeline.py --page DIR   preview page

Impostor = hemi-octahedral G x G views (upper hemisphere; the sim looks at trees from above / the side, never from below),
each view an orthographic frame of the whole bounding sphere. At run time one camera-facing quad per tree (2 triangles);
the pixel shader blends the 4 nearest views (bilinear in the view grid) and re-projects each through its own view plane.
The software renderer here does the same with the PNG atlases (8-bit, like the game textures) + a sun shadow map built from
impostors seen from the sun, so the picture is what the impostor can show - not the full mesh.

Outputs: C:\\GyroSimTiles\\assets\\trees_impostor\\ (outside git: Megascans-derived atlases are Fab-licensed, UE only).
"""
import glob, json, math, os, subprocess, sys, time, site
if sys.flags.isolated:
    site.addsitedir(site.getusersitepackages())
os.environ["OPENCV_IO_ENABLE_OPENEXR"] = "1"
import numpy as np                                                      # noqa: E402
import cv2                                                              # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.environ.get("GYROSIM_IMPOSTOR_DIR", r"C:\GyroSimTiles\assets\trees_impostor")
SRC = r"C:\GyroSimTiles\assets\trees_src"
BLENDER = os.environ.get("BLENDER", os.path.expanduser(r"~\tools\blender\blender-4.5.15-windows-x64\blender.exe"))
G, PX, SPP = 8, 256, 64

# name -> source, preview group, target height range (m) for the scenes (Busan: red pine 10-16 m, oak 12-16 m)
SPECIES = dict(
    pine_a=dict(kind="gltf", src=SRC + r"\polyhaven_pine_tree_01\pine_tree_01_1k.gltf", node=0, h=(11, 16)),
    pine_b=dict(kind="gltf", src=SRC + r"\polyhaven_pine_tree_01\pine_tree_01_1k.gltf", node=1, h=(10, 15)),
    pine_c=dict(kind="gltf", src=SRC + r"\polyhaven_pine_tree_01\pine_tree_01_1k.gltf", node=2, h=(10, 15)),
    psap_a=dict(kind="gltf", src=SRC + r"\polyhaven_pine_sapling_medium\pine_sapling_medium_1k.gltf", node=0, h=None),
    fir_a=dict(kind="gltf", src=SRC + r"\polyhaven_fir_tree_01\fir_tree_01_1k.gltf", node=0, h=(14, 19)),
    oak_b=dict(kind="usd", src=SRC + r"\tree_english_oak_forest_01_usd\Tree_English_Oak_Forest_01_B.usd", h=(12, 16)),
    oak_c=dict(kind="usd", src=SRC + r"\tree_english_oak_forest_01_usd\Tree_English_Oak_Forest_01_C.usd", h=(12, 16)),
    alder_b=dict(kind="usd", src=SRC + r"\tree_black_alder_01_usd\Tree_Black_Alder_01_B.usd", h=(10, 13)),
)
GROUPS = dict(          # preview sections: key -> (Korean title, members, spacing m, licence)
    pine=("소나무 (Poly Haven pine_tree_01, 3 종류 섞음)", ["pine_a", "pine_b", "pine_c"], 4.5, "CC0"),
    psap=("어린 소나무 (Poly Haven pine_sapling_medium)", ["psap_a"], 3.0, "CC0"),
    fir=("전나무 (Poly Haven fir_tree_01) — 편백·삼나무 조림지 대용", ["fir_a"], 4.0, "CC0"),
    oak=("참나무 (Megascans English Oak Forest B·C)", ["oak_b", "oak_c"], 6.0, "Fab (UE 전용)"),
    alder=("오리나무 (Megascans Black Alder B)", ["alder_b"], 5.0, "Fab (UE 전용)"),
)
SUN = dict(az=-120.0, el=40.0, strength=4.0, rgb=(1.0, 0.95, 0.88))
SKY = dict(rgb=(0.20, 0.26, 0.38))
GROUND = (0.075, 0.085, 0.05)


def run_blender(job, tag):
    os.makedirs(OUT, exist_ok=True)
    jp = os.path.join(OUT, "job_%s.json" % tag)
    json.dump(job, open(jp, "w"), indent=1)
    logp = os.path.join(OUT, "blender_%s.log" % tag)
    cmd = ["powershell", "-NoProfile", "-NonInteractive", "-File", os.path.join(HERE, "run_locked.ps1"), "-exe", BLENDER,
           "-argstr", '-b --factory-startup -P "%s" -- "%s"' % (os.path.join(HERE, "bake_blender.py"), jp), "-log", logp]
    t = time.time()
    r = subprocess.run(cmd, capture_output=True, text=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    print(r.stdout.strip(), "exit", r.returncode, "s", round(time.time() - t))
    for line in open(logp, encoding="utf-8", errors="replace"):
        if line.startswith("[imp") and " row " not in line:
            print("  ", line.rstrip())
    if r.returncode != 0:
        sys.exit("blender failed (%d), see %s" % (r.returncode, logp))


def species_job():
    return {k: dict(kind=v["kind"], src=v["src"].replace("\\", "/"), node=v.get("node", 0)) for k, v in SPECIES.items()}


# ---- bake + assemble ----------------------------------------------------------------------------------------------
def do_bake(names):
    run_blender(dict(mode="bake", out=OUT.replace("\\", "/"), grid=G, px=PX, spp=SPP, ao_m=2.5, species=species_job(),
                     bake=names), "bake")


def oct_encode(n):
    n = n / np.maximum(np.abs(n).sum(-1, keepdims=True), 1e-8)
    x, y, z = n[..., 0], n[..., 1], n[..., 2]
    ox = np.where(z >= 0, x, (1 - np.abs(y)) * np.sign(x + 1e-12))
    oy = np.where(z >= 0, y, (1 - np.abs(x)) * np.sign(y + 1e-12))
    return np.stack([ox, oy], -1)


def oct_decode(e):
    x, y = e[..., 0], e[..., 1]
    z = 1 - np.abs(x) - np.abs(y)
    t = np.maximum(-z, 0)
    x = x - np.sign(x) * t
    y = y - np.sign(y) * t
    n = np.stack([x, y, z], -1)
    return n / np.maximum(np.linalg.norm(n, axis=-1, keepdims=True), 1e-8)


def srgb_enc(x):
    x = np.clip(x, 0, 1)
    return np.where(x <= 0.0031308, 12.92 * x, 1.055 * np.power(x, 1 / 2.4) - 0.055)


def srgb_dec(x):
    return np.where(x <= 0.04045, x / 12.92, np.power((x + 0.055) / 1.055, 2.4))


def dilate(rgb, a, n=24):
    """push colour into empty texels (so mips / bilinear do not pull in black)."""
    rgb = rgb.copy(); m = a > 0.02
    for _ in range(n):
        if m.all():
            break
        acc = np.zeros_like(rgb); cnt = np.zeros(m.shape, np.float32)
        for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            mm = np.roll(m, (dy, dx), (0, 1)); acc += np.roll(rgb, (dy, dx), (0, 1)) * mm[..., None]; cnt += mm
        new = (~m) & (cnt > 0)
        rgb[new] = acc[new] / cnt[new][:, None]
        m = m | new
    return rgb


def frame_basis(d):
    d = np.asarray(d, float)
    up = np.array([0, 0, 1.0]) - d[2] * d
    up /= np.linalg.norm(up)
    return np.cross(up, d), up                                           # camera X (right), Y (up); camera looks along -d


def assemble(name):
    fdir = os.path.join(OUT, "frames", name)
    meta = json.load(open(os.path.join(fdir, "meta.json")))
    g, px, R, dist = meta["grid"], meta["px"], meta["radius"], meta["cam_dist"]
    A = np.zeros((g * px, g * px, 4), np.uint8); B = np.zeros((g * px, g * px, 4), np.uint8)
    rd = lambda n, k: cv2.imread(os.path.join(fdir, "%s_%04d.exr" % (n, k + 1)), cv2.IMREAD_UNCHANGED)
    cover = []
    for k in range(g * g):
        a = rd("Alpha", k)[..., 0]
        sa = np.maximum(a, 1e-4)[..., None]
        dc = rd("DiffCol", k)[..., 2::-1] / sa                              # cv2 = BGR(A)
        nr = rd("Normal", k)[..., 2::-1] / sa
        ao = np.clip(rd("AO", k)[..., 0] / sa[..., 0], 0, 1)
        z = rd("Depth", k)[..., 0]
        d = np.array(meta["dirs"][k])
        nr /= np.maximum(np.linalg.norm(nr, axis=-1, keepdims=True), 1e-6)
        flip = (nr @ d) < 0
        nr[flip] *= -1                                                      # two-sided leaves: the side facing the view
        off = np.where(a > 0.01, np.clip((z - dist) / (2 * R) + 0.5, 0, 1), 1.0)   # 0 = near, 1 = far (bounding sphere)
        dc = dilate(dc, a); nr = dilate(nr, a); ao = dilate(ao[..., None], a)[..., 0]
        off = dilate(off[..., None], a)[..., 0]
        j, i = divmod(k, g)
        sl = (slice(j * px, (j + 1) * px), slice(i * px, (i + 1) * px))
        A[sl] = np.dstack([np.round(srgb_enc(dc) * 255), np.round(np.clip(a, 0, 1) * 255)]).astype(np.uint8)
        oe = oct_encode(nr) * 0.5 + 0.5
        B[sl] = np.round(np.dstack([oe, off, ao]) * 255).astype(np.uint8)
        cover.append(float((a > 0.5).mean()))
    cv2.imwrite(os.path.join(OUT, "T_Imp_%s_A.png" % name), A[..., [2, 1, 0, 3]])
    cv2.imwrite(os.path.join(OUT, "T_Imp_%s_B.png" % name), B[..., [2, 1, 0, 3]])
    meta.update(atlas_px=g * px, mean_coverage=round(float(np.mean(cover)), 3), assembled=time.strftime("%Y-%m-%d %H:%M:%S"),
                textures=["T_Imp_%s_A.png" % name, "T_Imp_%s_B.png" % name],
                packing="A: sRGB albedo (diffuse colour pass) + alpha; B: oct-normal xy (world, z up), depth 0..1 over the "
                        "bounding sphere diameter along the view (0.5 = centre), AO (Cycles, 2.5 m)")
    json.dump(meta, open(os.path.join(OUT, "T_Imp_%s.json" % name), "w"), indent=1)
    print("atlas", name, "coverage", meta["mean_coverage"], "R", round(R, 2), "h", round(meta["hi"][2] - meta["lo"][2], 2))


# ---- scenes (shared by the Blender reference and the impostor renderer) -------------------------------------------
def load_meta(name):
    return json.load(open(os.path.join(OUT, "T_Imp_%s.json" % name)))


def native_h(m):
    return m["hi"][2] - m["lo"][2]


def tree_scale(name, rng):
    m = load_meta(name); h = SPECIES[name]["h"]
    if h is None:
        return float(rng.uniform(0.85, 1.15))
    return float(rng.uniform(*h) / native_h(m))


def look(loc, at, fov):
    return dict(loc=[float(v) for v in loc], at=[float(v) for v in at], fov=float(fov))


def make_scenes():
    rng = np.random.default_rng(11)
    sc = []
    for gk, (_t, mem, sp, _l) in GROUPS.items():
        m0 = load_meta(mem[0]); s0 = tree_scale(mem[0], np.random.default_rng(1)) if SPECIES[mem[0]]["h"] else 1.0
        h = native_h(m0) * s0; ctr_z = h * 0.5
        # angles: one tree, 4 views
        for ai, (el, az) in enumerate(((5, -60), (30, -10), (60, 40), (88, 0))):
            dist = h * 1.25 / math.tan(math.radians(15)) * 0.5 + 2
            e, a = math.radians(el), math.radians(az)
            loc = (dist * math.cos(e) * math.cos(a), dist * math.cos(e) * math.sin(a), ctr_z + dist * math.sin(e))
            sc.append(dict(name="%s_ang%d" % (gk, ai), res=[480, 480], spp=96, ground=False,
                           cam=look(loc, (0, 0, ctr_z), 30), trees=[[mem[0], 0, 0, 0, s0]]))
        # hero: full mesh close-up with ground
        sc.append(dict(name="%s_hero" % gk, res=[960, 1080], spp=160, ground=True,
                       cam=look((-h * 1.9, -h * 0.5, h * 0.35), (0, 0, h * 0.5), 32), trees=[[mem[0], 0, 0, 0, s0]]))
        # 16 trees
        tr = []
        for j in range(4):
            for i in range(4):
                n = mem[(i + j) % len(mem)]
                tr.append([n, (i - 1.5) * sp * 1.7 + rng.normal(0, sp * 0.25), (j - 1.5) * sp * 1.7 + rng.normal(0, sp * 0.25),
                           float(rng.uniform(0, 360)), tree_scale(n, rng)])
        sc.append(dict(name="%s_g16" % gk, res=[1280, 720], spp=128, ground=True,
                       cam=look((-sp * 9.5, -sp * 4.5, h * 1.6), (0, 0, h * 0.25), 50), trees=tr))
        # 400-tree forest, 100 m and 300 m altitude
        tr = forest(mem, sp, rng, 20)
        sc.append(dict(name="%s_f100" % gk, res=[1280, 720], spp=96, ground=True, cam=look((-150, -40, 100), (0, 0, 0), 50), trees=tr))
        sc.append(dict(name="%s_f300" % gk, res=[1280, 720], spp=96, ground=True, cam=look((-300, -80, 300), (0, 0, 0), 25), trees=tr))
    # mixed Busan-like hill forest: red pine 70 %, saplings 10 %, oak / alder 20 %
    mix = ["pine_a"] * 24 + ["pine_b"] * 23 + ["pine_c"] * 23 + ["psap_a"] * 10 + ["oak_b"] * 7 + ["oak_c"] * 6 + ["alder_b"] * 7
    tr = forest(mix, 4.6, rng, 20)
    sc.append(dict(name="mix_f100", res=[1280, 720], spp=96, ground=True, cam=look((-150, -40, 100), (0, 0, 0), 50), trees=tr))
    sc.append(dict(name="mix_f300", res=[1280, 720], spp=96, ground=True, cam=look((-300, -80, 300), (0, 0, 0), 25), trees=tr))
    json.dump(dict(scenes=sc, sun=SUN, sky=SKY, ground_rgb=GROUND, made=time.strftime("%Y-%m-%d %H:%M:%S")),
              open(os.path.join(OUT, "scenes.json"), "w"), indent=0)
    return sc


def forest(mem, sp, rng, n):
    tr = []
    for j in range(n):
        for i in range(n):
            nm = mem[int(rng.integers(len(mem)))]
            tr.append([nm, (i - (n - 1) / 2) * sp + rng.normal(0, sp * 0.3), (j - (n - 1) / 2) * sp + rng.normal(0, sp * 0.3),
                       float(rng.uniform(0, 360)), tree_scale(nm, rng)])
    return tr


def do_real():
    S = json.load(open(os.path.join(OUT, "scenes.json")))
    run_blender(dict(mode="scenes", out=OUT.replace("\\", "/"), species=species_job(), scenes=S["scenes"], sun=S["sun"],
                     sky=S["sky"], ground_rgb=S["ground_rgb"]), "real")


# ---- software impostor renderer -----------------------------------------------------------------------------------
class Imp:
    """one species: frames from the 8-bit atlases, premultiplied mip chain, view grid."""

    def __init__(self, name):
        m = load_meta(name)
        self.m = m; self.g = m["grid"]; self.px = m["px"]; self.R = m["radius"]
        A = cv2.imread(os.path.join(OUT, m["textures"][0]), cv2.IMREAD_UNCHANGED)[..., [2, 1, 0, 3]].astype(np.float32) / 255
        B = cv2.imread(os.path.join(OUT, m["textures"][1]), cv2.IMREAD_UNCHANGED)[..., [2, 1, 0, 3]].astype(np.float32) / 255
        g, px = self.g, self.px
        alb = srgb_dec(A[..., :3]); a = A[..., 3:4]
        n = oct_decode(B[..., :2] * 2 - 1)
        attrs = np.concatenate([alb, n, B[..., 2:4]], -1)                    # 8: albedo3 normal3 depth ao
        F = np.concatenate([attrs * a, a], -1).reshape(g, px, g, px, 9).transpose(0, 2, 1, 3, 4).reshape(g * g, px, px, 9)
        self.mips = [F]
        while self.mips[-1].shape[1] > 4:
            f = self.mips[-1]
            self.mips.append(0.25 * (f[:, 0::2, 0::2] + f[:, 1::2, 0::2] + f[:, 0::2, 1::2] + f[:, 1::2, 1::2]))
        self.dirs = np.array(m["dirs"])
        self.bases = [frame_basis(d) for d in self.dirs]
        self.center = np.array(m["center"]); self.base = np.array(m["base"])

    def weights(self, v):
        """local view direction (unit, toward the viewer) -> [(frame, weight)] bilinear in the hemi-oct grid."""
        v = np.array([v[0], v[1], max(v[2], 0.0)])
        s = np.abs(v).sum()
        x, y = v[0] / s, v[1] / s
        u, w = x + y, x - y
        gi = (u + 1) / 2 * self.g - 0.5; gj = (w + 1) / 2 * self.g - 0.5
        gi = min(max(gi, 0), self.g - 1); gj = min(max(gj, 0), self.g - 1)
        i0, j0 = int(min(math.floor(gi), self.g - 2)), int(min(math.floor(gj), self.g - 2))
        fi, fj = gi - i0, gj - j0
        out = []
        for di, dj, wt in ((0, 0, (1 - fi) * (1 - fj)), (1, 0, fi * (1 - fj)), (0, 1, (1 - fi) * fj), (1, 1, fi * fj)):
            if wt > 1e-3:
                out.append(((j0 + dj) * self.g + i0 + di, wt))
        return out

    def sample(self, lev, k, col, row):
        f = self.mips[lev][k]; n = f.shape[0]
        c = col * n - 0.5; r = row * n - 0.5
        c0 = np.floor(c).astype(int); r0 = np.floor(r).astype(int); fc = (c - c0)[:, None]; fr = (r - r0)[:, None]
        out = 0
        for dc, dr, w in ((0, 0, (1 - fc) * (1 - fr)), (1, 0, fc * (1 - fr)), (0, 1, (1 - fc) * fr), (1, 1, fc * fr)):
            cc = c0 + dc; rr = r0 + dr
            ok = ((cc >= 0) & (cc < n) & (rr >= 0) & (rr < n))[:, None]
            out = out + w * f[np.clip(rr, 0, n - 1), np.clip(cc, 0, n - 1)] * ok
        return out


def rz(yaw):
    c, s = math.cos(math.radians(yaw)), math.sin(math.radians(yaw))
    return np.array([[c, -s, 0], [s, c, 0], [0, 0, 1.0]])


class View:
    def __init__(self, W, H, persp=None, ortho=None):
        self.W, self.H = W, H
        if persp:
            loc = np.array(persp["loc"], float); at = np.array(persp["at"], float)
            self.o = loc; fw = at - loc; fw /= np.linalg.norm(fw)
            self.f = (W / 2) / math.tan(math.radians(persp["fov"]) / 2); self.persp = True
        else:
            fw = np.array(ortho["dir"], float); fw /= np.linalg.norm(fw)
            self.o = np.array(ortho["center"], float); self.m = ortho["m_per_px"]; self.persp = False
        self.fw = fw
        r = np.cross(fw, [0, 0, 1.0]); r /= np.linalg.norm(r); self.r = r; self.u = np.cross(r, fw)

    def rays(self, xs, ys):
        X = (xs + 0.5 - self.W / 2); Y = (ys + 0.5 - self.H / 2)
        if self.persp:
            D = self.fw[None] + (X[:, None] * self.r[None] - Y[:, None] * self.u[None]) / self.f
            D /= np.linalg.norm(D, axis=1, keepdims=True)
            return np.repeat(self.o[None], len(xs), 0), D
        O = self.o[None] + (X[:, None] * self.r[None] - Y[:, None] * self.u[None]) * self.m
        return O, np.repeat(self.fw[None], len(xs), 0)

    def bbox(self, C, rad):
        p = C - self.o
        z = p @ self.fw
        if self.persp:
            if z < rad + 0.5:
                return None
            sx = self.W / 2 + self.f * (p @ self.r) / z; sy = self.H / 2 - self.f * (p @ self.u) / z
            rp = self.f * rad / math.sqrt(max(z * z - rad * rad, 1e-6)) + 2
            return sx - rp, sy - rp, sx + rp, sy + rp, z
        sx = self.W / 2 + (p @ self.r) / self.m; sy = self.H / 2 - (p @ self.u) / self.m; rp = rad / self.m + 2
        return sx - rp, sy - rp, sx + rp, sy + rp, z


def raster_trees(view, trees, imps, attrs=True, thresh=0.5):
    """z-buffer of impostor cards. returns depth (along the ray), and if attrs: albedo, normal (world), ao."""
    W, H = view.W, view.H
    zb = np.full(H * W, np.inf, np.float32)
    if attrs:
        alb = np.zeros((H * W, 3), np.float32); nor = np.zeros((H * W, 3), np.float32); ao = np.ones(H * W, np.float32)
    for name, x, y, yaw, s in trees:
        imp = imps[name]; Rm = rz(yaw)
        pos = np.array([x, y, 0.0])
        C = pos + Rm @ ((imp.center - imp.base) * s); rad = imp.R * s
        bb = view.bbox(C, rad)
        if bb is None:
            continue
        x0, y0, x1, y1, zc = bb
        x0, y0 = max(int(x0), 0), max(int(y0), 0); x1, y1 = min(int(math.ceil(x1)), W), min(int(math.ceil(y1)), H)
        if x0 >= x1 or y0 >= y1:
            continue
        ys, xs = np.mgrid[y0:y1, x0:x1]; xs = xs.ravel(); ys = ys.ravel()
        O, D = view.rays(xs.astype(np.float32), ys.astype(np.float32))
        vw = (view.o - C) if view.persp else -view.fw
        vl = Rm.T @ (vw / np.linalg.norm(vw))
        foot = (zc / view.f) if view.persp else view.m                     # metres per screen pixel at the tree
        lev = int(np.clip(math.floor(math.log2(max(foot * imp.px / (2 * rad), 1.0))), 0, len(imp.mips) - 1))
        acc = 0; Qacc = 0
        for k, wt in imp.weights(vl):
            dk = Rm @ imp.dirs[k]; X, Y = imp.bases[k]; X = Rm @ X; Y = Rm @ Y
            den = D @ dk
            t = ((C - O) @ dk) / np.where(np.abs(den) < 1e-6, -1e-6, den)
            P = O + t[:, None] * D
            a = ((P - C) @ X) / rad; b = ((P - C) @ Y) / rad
            smp = imp.sample(lev, k, (a + 1) / 2, (1 - b) / 2)            # premultiplied 9
            acc = acc + wt * smp
            al = np.maximum(smp[:, 8:9], 1e-5)
            off = (smp[:, 6:7] / al - 0.5) * 2 * rad                        # + = farther from that view
            Qacc = Qacc + wt * smp[:, 8:9] * (P - dk[None] * off)
        a = acc[:, 8]
        hit = a > thresh
        if not hit.any():
            continue
        Q = Qacc[hit] / a[hit, None]
        td = ((Q - O[hit]) * D[hit]).sum(1)
        idx = ys[hit] * W + xs[hit]
        closer = td < zb[idx]
        idx = idx[closer]; zb[idx] = td[closer]
        if attrs:
            at = acc[hit][closer] / a[hit][closer, None]
            alb[idx] = at[:, 0:3]
            n = at[:, 3:6] @ Rm.T; n /= np.maximum(np.linalg.norm(n, axis=1, keepdims=True), 1e-6)
            nor[idx] = n; ao[idx] = at[:, 7]
    if attrs:
        return zb, alb, nor, ao
    return zb


def sun_dir():
    az, el = math.radians(SUN["az"]), math.radians(SUN["el"])
    return np.array([math.cos(el) * math.cos(az), math.cos(el) * math.sin(az), math.sin(el)])


def render_imp(sc, imps, ss=2):
    W, H = sc["res"][0] * ss, sc["res"][1] * ss
    view = View(W, H, persp=sc["cam"])
    zb, alb, nor, ao = raster_trees(view, sc["trees"], imps)
    ys, xs = np.mgrid[0:H, 0:W]; xs = xs.ravel(); ys = ys.ravel()
    O, D = view.rays(xs.astype(np.float32), ys.astype(np.float32))
    tg = np.where(D[:, 2] < -1e-4, -O[:, 2] / np.minimum(D[:, 2], -1e-4), np.inf)
    ground = bool(sc.get("ground", True))
    tree = np.isfinite(zb) & ((zb < tg) if ground else True)
    gnd = (~tree & np.isfinite(tg)) if ground else np.zeros_like(tree)
    L = sun_dir()
    sky = np.array(SKY["rgb"]); sunc = np.array(SUN["rgb"]) * SUN["strength"] / math.pi
    img = np.tile(sky[None], (H * W, 1)).astype(np.float32)
    alpha = (tree | gnd).astype(np.float32)
    # sun shadow map from impostors seen from the sun
    pts_t = O[tree] + zb[tree, None] * D[tree]
    pts_g = O[gnd] + tg[gnd, None] * D[gnd]
    allp = np.array([[t[1], t[2], 0.0] for t in sc["trees"]])
    ext = np.ptp(allp[:, :2], 0).max() / 2 + 25
    mpp = max(ext * 2 / 3000, 0.03)
    n_l = int(ext * 2 / mpp) + 1
    lc = allp.mean(0) + L * 200
    lv = View(n_l, n_l, ortho=dict(dir=-L, center=lc, m_per_px=mpp))
    lz = raster_trees(lv, sc["trees"], imps, attrs=False, thresh=0.5).reshape(n_l, n_l)

    def shadow(P, bias):
        p = P - lv.o
        sx = p @ lv.r / mpp + n_l / 2 - 0.5; sy = n_l / 2 - p @ lv.u / mpp - 0.5; d = p @ lv.fw
        lit = 0
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                xi = np.clip(np.round(sx).astype(int) + dx, 0, n_l - 1); yi = np.clip(np.round(sy).astype(int) + dy, 0, n_l - 1)
                lit = lit + (lz[yi, xi] > d - bias)
        return lit / 9.0
    if tree.any():
        sh = shadow(pts_t, 0.8)
        nl = np.clip(nor[tree] @ L, 0, 1)
        img[tree] = alb[tree] * (sky[None] * ao[tree, None] + sunc[None] * (nl * sh)[:, None])
    if gnd.any():
        sh = shadow(pts_g, 0.15)
        img[gnd] = np.array(GROUND)[None] * (sky[None] + sunc[None] * (L[2] * sh)[:, None])
    img = img.reshape(H, W, 3); alpha = alpha.reshape(H, W)
    if ss > 1:
        img = img.reshape(H // ss, ss, W // ss, ss, 3).mean((1, 3)); alpha = alpha.reshape(H // ss, ss, W // ss, ss).mean((1, 3))
    return img, alpha


def do_imp(only=None):
    S = json.load(open(os.path.join(OUT, "scenes.json")))
    os.makedirs(os.path.join(OUT, "imp"), exist_ok=True)
    imps = {}
    for sc in S["scenes"]:
        if only and not sc["name"].startswith(only):
            continue
        for t in sc["trees"]:
            if t[0] not in imps:
                imps[t[0]] = Imp(t[0])
        t0 = time.time()
        img, a = render_imp(sc, imps)
        out = np.dstack([srgb_enc(img), a]) if not sc.get("ground", True) else srgb_enc(img)
        o8 = np.round(out * 255).astype(np.uint8)
        cv2.imwrite(os.path.join(OUT, "imp", sc["name"] + ".png"), o8[..., [2, 1, 0, 3]] if o8.shape[2] == 4 else o8[..., ::-1])
        print("imp", sc["name"], len(sc["trees"]), "trees", round(time.time() - t0, 1), "s", flush=True)


if __name__ == "__main__":
    a = sys.argv[1:]
    names = [x for x in a[1:] if x in SPECIES] or list(SPECIES)
    if "--bake" in a:
        do_bake(names)
    if "--assemble" in a:
        for n in names:
            assemble(n)
    if "--scenes" in a:
        make_scenes()
    if "--real" in a:
        do_real()
    if "--imp" in a:
        do_imp(a[a.index("--imp") + 1] if len(a) > a.index("--imp") + 1 and not a[a.index("--imp") + 1].startswith("-") else None)


# ---- Unreal hand-off (step 2): card mesh + per-kind info ---------------------------------------------------------------
# runtime kinds (Content/Python/trees_imp.py; the GyroTreesNear actor has 8 components per slot):
#   kind -> (atlas species, colour target = sim/veg_v2.TINT of the Busan species it stands for - tuned on the photos there)
UE_KINDS = [("pine_a", "pine"), ("pine_b", "pine"), ("pine_c", "pine"), ("psap_a", "pine"),
            ("oak_b", "broad"), ("oak_c", "broad"), ("alder_b", "broad"), ("pine_c", "bpine")]
GAIN, BALANCE = 4.2, [1.04, 0.97, 0.62]                 # 11-11 calibration (hwang_low, gain-1 ratio blob / imp R 4.5 G 4.2 B 2.6)
TARGET = dict(pine=(0.034, 0.060, 0.043), bpine=(0.028, 0.052, 0.043), broad=(0.070, 0.112, 0.038), shrub=(0.058, 0.094, 0.044))


def write_card(path):
    """one quad (2 triangles), its 4 corners on the diagonal plane of the +-1 m cube (bounds = the bounding sphere box);
    the material moves the corners to face the camera (world position offset). UV0 = corner id."""
    import struct
    P = np.array([[-1, -1, -1], [1, 1, -1], [1, 1, 1], [-1, -1, 1]], np.float32)
    N = np.tile(np.array([[0.7071, -0.7071, 0]], np.float32), (4, 1))
    UV = np.array([[0, 1], [1, 1], [1, 0], [0, 0]], np.float32)
    F = np.array([0, 1, 2, 0, 2, 3], np.uint32)

    def pad(b, c=b"\0"):
        return b + c * ((4 - len(b) % 4) % 4)
    blobs = [P.tobytes(), N.tobytes(), UV.tobytes(), F.tobytes()]
    offs, buf = [], b""
    for b in blobs:
        offs.append(len(buf)); buf += pad(b)
    g = dict(asset=dict(version="2.0", generator="gyro-sim-chair sim/impostor/pipeline.py"), scene=0, scenes=[dict(nodes=[0])],
             nodes=[dict(mesh=0, name="SM_GyroImpCard")], materials=[dict(name="ImpCard", doubleSided=True)],
             meshes=[dict(primitives=[dict(attributes=dict(POSITION=0, NORMAL=1, TEXCOORD_0=2), indices=3, material=0)])],
             buffers=[dict(byteLength=len(buf))],
             bufferViews=[dict(buffer=0, byteOffset=offs[i], byteLength=len(blobs[i]), target=34963 if i == 3 else 34962) for i in range(4)],
             accessors=[dict(bufferView=0, componentType=5126, count=4, type="VEC3", min=[-1, -1, -1], max=[1, 1, 1]),
                        dict(bufferView=1, componentType=5126, count=4, type="VEC3"),
                        dict(bufferView=2, componentType=5126, count=4, type="VEC2"),
                        dict(bufferView=3, componentType=5125, count=6, type="SCALAR")])
    js = pad(json.dumps(g).encode(), b" ")
    with open(path, "wb") as f:
        f.write(struct.pack("<III", 0x46546C67, 2, 12 + 8 + len(js) + 8 + len(buf)))
        f.write(struct.pack("<II", len(js), 0x4E4F534A)); f.write(js)
        f.write(struct.pack("<II", len(buf), 0x004E4942)); f.write(buf)


def ue_info():
    """C:/GyroSimTiles/assets/trees_impostor/imp_info.json for Scripts/trees_imp_assets.py and Content/Python/trees_imp.py."""
    write_card(os.path.join(OUT, "SM_GyroImpCard.glb"))
    kinds = []
    for name, tgt in UE_KINDS:
        m = load_meta(name)
        A = cv2.imread(os.path.join(OUT, m["textures"][0]), cv2.IMREAD_UNCHANGED)[..., [2, 1, 0, 3]].astype(np.float32) / 255
        a = A[..., 3] > 0.5
        mean = srgb_dec(A[..., :3])[a].mean(0)
        mul = np.clip(np.array(TARGET[tgt]) / np.maximum(mean, 1e-4), 0.25, 3.0) * np.array(BALANCE)
        lo, hi, c, b = (np.array(m[k]) for k in ("lo", "hi", "center", "base"))
        kinds.append(dict(atlas=name, target=tgt, R=m["radius"], h=float(hi[2] - lo[2]),
                          crown_r=float(max(hi[0] - lo[0], hi[1] - lo[1]) / 2),
                          center_off=[float(v) for v in (c - b)],                # Blender axes (x, y, z) m; UE local = (x, -y, z)
                          atlas_mean=[round(float(v), 4) for v in mean], color_mul=[round(float(v), 3) for v in mul],
                          tex=["T_Imp_%s_A" % name, "T_Imp_%s_B" % name]))
    info = dict(made=time.strftime("%Y-%m-%d %H:%M:%S"), grid=G, px=PX, card="SM_GyroImpCard.glb", kinds=kinds,
                gain=GAIN, balance=BALANCE, note="color_mul = veg_v2 species albedo / atlas mean (opaque texels) x balance; gain + balance "
                "calibrated 11-11 on hwang_low (sim/impostor/calib.py: tree pixels vs the old photo-tuned blob trees)")
    json.dump(info, open(os.path.join(OUT, "imp_info.json"), "w"), indent=1)
    for k in kinds:
        print(k["atlas"], k["target"], "R", round(k["R"], 2), "mul", k["color_mul"])


if __name__ == "__main__" and "--ue" in sys.argv:
    ue_info()
