"""Building-grounding study: metrics + preview PNGs from the render_study.py EXRs.

    python sim/grounding/analyse.py ROOT scene[,scene...] [--ref full|base] -> ROOT/metrics.json, ROOT/png/<scene>__<view>__<variant>.jpg

Per render (linear EXR passes, same ruler for scans and Busan; all brightness numbers in stops = log2 of medians of the
luminance Y, so the exposure does not matter):
  facade_foot        facade pixels 0-3 m above the terrain vs 6-20 m (negative = darker foot)
  facade_foot_alb    the same on the albedo pass (DiffCol): what the texture itself carries
  ground_contact     ground 0.5-2.5 m from a footprint vs 15-30 m, all pixels (shadow + occlusion + texture)
  ground_contact_lit the same, sunlit pixels only (occlusion + texture, no cast shadow)
  ground_contact_alb the same on the albedo pass (baked darkening in the photo / scan texture)
  band_w             m from the footprint where the sunlit ground gets within 0.15 stop of the far ground
  base_step          facade 0-2 m vs ground 0-2 m (the step across the base line; 0 = blended)
  shadow_contrast    ground in the sun's shadow vs sunlit ground; shadow_near = shadowed share of the ground within 10 m
  chroma_diff        100 x rg-chromaticity distance between the facade foot (0-6 m) and the ground within 10 m
  ghost              texture busyness of the ground ring 0-6 m vs 15-30 m (|logY - blurred|; > 1 = busier next to the
                     building, e.g. a photo with the building's own roof / wall painted there)
Sun visibility = sun light-group pass / (albedo x E cos / pi); < 0.5 = shadow. Ground = < 0.6 m above the terrain and
outside the building mask; facade = building mask and |n_z| < 0.35.
"""
import json, math, os, sys, time
os.environ.setdefault("OPENCV_IO_ENABLE_OPENEXR", "1")
import cv2
import numpy as np

SUN_E, SUN_AZ, SUN_EL = 5.0, 215.0, 42.0
KEYS = ["facade_foot", "facade_foot_alb", "ground_contact", "ground_contact_lit", "ground_contact_alb", "band_w",
        "base_step", "shadow_contrast", "shadow_near", "chroma_diff", "ghost"]
SCORE = {"facade_foot": 0.15, "ground_contact": 0.15, "ground_contact_lit": 0.1, "band_w": 1.0, "base_step": 0.15,
         "chroma_diff": 1.0, "ghost": 0.1}


def rd(d, n):
    a = cv2.imread(os.path.join(d, n + "0001.exr"), cv2.IMREAD_UNCHANGED)   # (normal pass written as R/G/B)
    if a is None:
        return None
    a = a.astype(np.float64)
    return a[..., 2::-1] if a.ndim == 3 else np.repeat(a[..., None], 3, -1)


def lum(a):
    return a[..., 0] * 0.2126 + a[..., 1] * 0.7152 + a[..., 2] * 0.0722


def med(x, m, n_min=200):
    v = x[m]
    return float(np.median(v)) if v.size >= n_min else float("nan")


def st(a, b):
    return float(np.log2(a / b)) if a > 0 and b > 0 and np.isfinite(a) and np.isfinite(b) else float("nan")


def load(d):
    img, col, sun, nrm = rd(d, "img"), rd(d, "col"), rd(d, "sun"), rd(d, "nrm")
    hag, dist, bm = rd(d, "hag")[..., 0], rd(d, "dist")[..., 0], rd(d, "bm")[..., 0]
    return dict(img=img, col=col, sun=sun, nrm=nrm, hag=hag, dist=dist, bm=bm)


def classes(R):
    Y, A = lum(R["img"]), lum(R["col"])
    n = R["nrm"]
    valid = (A > 1e-4) & (np.abs(n).sum(-1) > 0.5)
    az, el = math.radians(SUN_AZ), math.radians(SUN_EL)
    L = np.array([math.sin(az) * math.cos(el), math.cos(az) * math.cos(el), math.sin(el)])
    cs = n @ L
    vis = lum(R["sun"]) / np.maximum(A * SUN_E * np.maximum(cs, 1e-3) / math.pi, 1e-6)
    ground = valid & (R["hag"] < 0.6) & (R["bm"] < 0.5)
    facade = valid & (R["bm"] > 0.5) & (np.abs(n[..., 2]) < 0.35) & (R["hag"] > -0.5)
    lit = (vis > 0.5) & (cs > 0.15)
    shadow = (vis < 0.35) & (cs > 0.15)
    return Y, A, ground, facade, lit, shadow, valid


def metrics(R):
    Y, A, g, f, lit, sh, valid = classes(R)
    h, d = R["hag"], R["dist"]
    m = {}
    m["facade_foot"] = st(med(Y, f & (h < 3)), med(Y, f & (h > 6) & (h < 20)))
    m["facade_foot_alb"] = st(med(A, f & (h < 3)), med(A, f & (h > 6) & (h < 20)))
    near, far = g & (d > 0.5) & (d < 2.5), g & (d > 15) & (d < 30)
    m["ground_contact"] = st(med(Y, near), med(Y, far))
    m["ground_contact_lit"] = st(med(Y, near & lit), med(Y, far & lit))
    m["ground_contact_alb"] = st(med(A, near), med(A, far))
    farl = med(Y, far & lit)
    w = 15.0
    prof = []
    for b in range(15):
        v = med(Y, g & lit & (d >= b) & (d < b + 1), 80)
        prof.append(st(v, farl))
    for b, s in enumerate(prof):
        if np.isfinite(s) and s >= -0.15:
            w = b + 0.5
            break
    m["band_w"] = w
    m["profile"] = [round(x, 3) if np.isfinite(x) else None for x in prof]
    m["base_step"] = st(med(Y, f & (h < 2)), med(Y, g & (d < 2)))
    m["shadow_contrast"] = st(med(Y, g & sh & (d < 30)), med(Y, g & lit & (d < 30)))
    gn = g & (d < 10)
    m["shadow_near"] = float((gn & sh).sum() / max(gn.sum(), 1))
    c = R["img"] / np.maximum(R["img"].sum(-1, keepdims=True), 1e-6)
    cf, cg = f & (h < 6), g & (d < 10)
    if cf.sum() > 200 and cg.sum() > 200:
        m["chroma_diff"] = float(100 * np.linalg.norm(np.median(c[cf][:, :2], 0) - np.median(c[cg][:, :2], 0)))
    else:
        m["chroma_diff"] = float("nan")
    lY = np.log2(np.maximum(Y, 1e-5))
    hp = np.abs(lY - cv2.GaussianBlur(lY, (0, 0), 2.0))
    a, b = med(hp, g & (d < 6)), med(hp, far)
    m["ghost"] = float(a / b) if b > 0 and np.isfinite(a) else float("nan")
    m["n_facade"], m["n_ground"] = int(f.sum()), int(g.sum())
    return m, (Y, f, g, lit, sh)


def tone(x, k):
    y = np.clip(x * k, 0, None)
    y = y / (1 + 0.25 * y)                                   # mild shoulder
    y = np.where(y <= 0.0031308, 12.92 * y, 1.055 * np.power(np.clip(y, 0, None), 1 / 2.4) - 0.055)
    return (np.clip(y, 0, 1) * 255).astype(np.uint8)


def main(root, scenes, ref_by_kind):
    out = json.load(open(os.path.join(root, "metrics.json"), encoding="utf-8")) if os.path.exists(os.path.join(root, "metrics.json")) else {}
    pdir = os.path.join(root, "png")
    os.makedirs(pdir, exist_ok=True)
    for sc in scenes:
        cfg = json.load(open(os.path.join(root, "cfg_%s.json" % sc), encoding="utf-8"))
        ref = ref_by_kind[cfg["kind"]]
        for vn, *_ in cfg["views"]:
            dref = os.path.join(root, sc, "%s__%s" % (vn, ref))
            Rr = load(dref)
            Y, A, g, f, lit, sh, valid = classes(Rr)
            k = 0.55 / max(np.percentile(Y[valid], 90), 1e-6)
            # class overlay for the page (reference variant)
            ov = tone(Rr["img"], k).astype(np.float64)
            ov[f] = ov[f] * 0.5 + np.array([230, 60, 60]) * 0.5
            ov[g & (Rr["dist"] < 2.5)] = ov[g & (Rr["dist"] < 2.5)] * 0.4 + np.array([255, 220, 0]) * 0.6
            ov[g & (Rr["dist"] > 15) & (Rr["dist"] < 30)] = ov[g & (Rr["dist"] > 15) & (Rr["dist"] < 30)] * 0.5 + np.array([60, 140, 255]) * 0.5
            cv2.imwrite(os.path.join(pdir, "%s__%s__classes.jpg" % (sc, vn)), ov[..., ::-1].astype(np.uint8), [cv2.IMWRITE_JPEG_QUALITY, 88])
            for var in cfg["variants"]:
                d = os.path.join(root, sc, "%s__%s" % (vn, var))
                if not os.path.exists(os.path.join(d, "img0001.exr")):
                    continue
                R = load(d)
                m, _ = metrics(R)
                m.update(scene=sc, kind=cfg["kind"], view=vn, variant=var, made=time.strftime("%Y-%m-%d %H:%M:%S"),
                         exr_time=time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(os.path.getmtime(os.path.join(d, "img0001.exr")))))
                out["%s|%s|%s" % (sc, vn, var)] = m
                cv2.imwrite(os.path.join(pdir, "%s__%s__%s.jpg" % (sc, vn, var)), tone(R["img"], k)[..., ::-1], [cv2.IMWRITE_JPEG_QUALITY, 88])
            print(sc, vn, "done")
    json.dump(out, open(os.path.join(root, "metrics.json"), "w", encoding="utf-8"), indent=1)
    return out


def summarize(root):
    M = json.load(open(os.path.join(root, "metrics.json"), encoding="utf-8"))
    rows = list(M.values())
    tgt_rows = [r for r in rows if r["kind"] == "scan" and r["variant"] == "full"]
    target, scale = {}, {}
    for k in KEYS:
        v = np.array([r[k] for r in tgt_rows if r.get(k) is not None and np.isfinite(r[k])])
        target[k] = float(np.median(v)) if v.size else float("nan")
        spread = (np.percentile(v, 75) - np.percentile(v, 25)) if v.size > 2 else 0.0
        scale[k] = max(float(spread), SCORE.get(k, 0.1))
    agg = {}
    for r in rows:
        key = (r["scene"] if r["kind"] == "scan" else "busan", r["variant"]) if r["kind"] == "busan" else (r["scene"], r["variant"])
        agg.setdefault(key, []).append(r)
    table = {}
    for (sc, var), rs in agg.items():
        t = {k: float(np.nanmedian([x[k] for x in rs])) for k in KEYS}
        dist = [min(abs(t[k] - target[k]) / scale[k], 3.0) for k in SCORE if np.isfinite(t[k]) and np.isfinite(target[k])]
        t["gap"] = float(np.mean(dist)) if dist else float("nan")
        # per-render gaps (views x scenes) -> spread of the gap
        g_each = []
        for x in rs:
            dd = [min(abs(x[k] - target[k]) / scale[k], 3.0) for k in SCORE if np.isfinite(x[k]) and np.isfinite(target[k])]
            g_each.append(float(np.mean(dd)))
        t["gap_each"] = g_each
        t["n"] = len(rs)
        table["%s|%s" % (sc, var)] = t
    s = dict(target=target, scale=scale, table=table, made=time.strftime("%Y-%m-%d %H:%M:%S"))
    json.dump(s, open(os.path.join(root, "summary.json"), "w", encoding="utf-8"), indent=1)
    return s


if __name__ == "__main__":
    a = sys.argv[1:]
    root = a[0]
    if len(a) > 1 and a[1] != "--summary":
        main(root, a[1].split(","), {"scan": "full", "busan": "base"})
    s = summarize(root)
    ks = ["gap"] + KEYS
    print("%-22s" % "row", " ".join("%8s" % k[:8] for k in ks))
    print("%-22s" % "TARGET", " ".join("%8.2f" % s["target"].get(k, float('nan')) if k != "gap" else "%8s" % "" for k in ks))
    for name, t in sorted(s["table"].items()):
        print("%-22s" % name, " ".join("%8.2f" % t[k] for k in ks))
