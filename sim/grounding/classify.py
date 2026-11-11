"""Building-grounding study: rasters for the renders from OUT/prep.npz (render_study.py prep).

    python sim/grounding/classify.py OUT_DIR scan|busan [--lean 0.25]

-> OUT/rasters.npz (rows from the south, 0.5 m), OUT/mask.png (check picture: grey = DSM, red = buildings, green = trees)
  dtm   terrain height. Busan: the terrain mesh where the ray hit the ground object, filled under buildings. Scan: grey
        opening (121 m) of the surface, then only points within 0.6 m of it, filled by normalized gaussian convolution.
  bm    building mask, dilated 1 m (so wall pixels at the footprint edge count as building). Busan: hits on the
        tile objects. Scan: 2.5 m above the terrain and smooth (trees are rough), cleaned (open / close, >= 30 m2).
  dist  m to the nearest footprint (0 inside)
  can   1 - sky-view factor of the open ground, same estimate as sim/bldg_ao_build.py (gaussian mean height / s for
        s = 6..192 m); inside a footprint the nearest open-ground value (the facade samples its street)
  lean  fix (a) mask: 1 inside footprints and 2 m around them, ramps to 0 over the lean zone 0.25 h of buildings
        >= 15 m (the ortho photo's off-nadir lean puts the building's own roof / wall there), soft edge
Same method for the scans and for Busan (one ruler).
"""
import json, os, sys, time
import numpy as np
from scipy import ndimage as nd

SCALES = (6.0, 12.0, 24.0, 48.0, 96.0, 192.0)


def fill_nearest(a, valid):
    idx = nd.distance_transform_edt(~valid, return_distances=False, return_indices=True)
    return a[tuple(idx)]


def norm_fill(a, valid, sigmas=(2.0, 6.0, 20.0, 60.0)):
    out = np.where(valid, a, np.nan)
    v = valid.astype(np.float64)
    a0 = np.where(valid, a, 0.0)
    for s in sigmas:
        num, den = nd.gaussian_filter(a0, s), nd.gaussian_filter(v, s)
        f = np.isnan(out) & (den > 1e-3)
        out[f] = num[f] / den[f]
    return np.where(np.isnan(out), np.nanmedian(a[valid]), out)


def main(out, kind, lean_k=0.25):
    z = np.load(os.path.join(out, "prep.npz"))
    dsm, cls, res = z["dsm"].astype(np.float64), z["cls"], float(z["res"])
    hit = np.isfinite(dsm)
    dsm_f = np.where(hit, dsm, np.nanmin(dsm))
    if kind == "busan":
        ground = (cls == 1) & hit
        dtm = norm_fill(dsm_f, ground, sigmas=(4.0, 12.0, 40.0, 120.0))
        b = (cls == 2) & (dsm_f - dtm > 1.0)
        tree = np.zeros_like(b)
    else:
        # progressive morphological filter (Zhang et al. 2003, IEEE TGRS 41(4)): growing openings, slope-aware thresholds
        surf = np.where(hit, dsm_f, 1e4)
        ground = hit.copy()
        wprev = 0.0
        for wm in (3.0, 9.0, 21.0, 41.0, 81.0, 121.0):
            w = int(round(wm / res)) | 1
            op = nd.grey_opening(surf, size=(w, w))
            thr = min(0.5 + 0.12 * (wm - wprev), 3.0) if wprev else 0.5
            ground &= ~(surf - op > thr)
            surf, wprev = op, wm
        ground &= hit
        dtm = norm_fill(dsm_f, ground)
        ground = hit & (dsm_f - dtm < 0.6)
        dtm = norm_fill(dsm_f, ground)
        hag = dsm_f - dtm
        rough = nd.uniform_filter(np.abs(dsm_f - nd.median_filter(dsm_f, 5)), 7)
        tall = hit & (hag > 2.5)
        b = tall & (rough < 0.30)
        b = nd.binary_opening(b, iterations=3)
        b = nd.binary_closing(b, iterations=3)
        lab, nl = nd.label(b)
        sz = np.bincount(lab.ravel())
        keep = sz >= 30.0 / res ** 2
        keep[0] = False
        b = keep[lab]
        tree = tall & ~b
    hag = dsm_f - dtm
    bm = nd.binary_dilation(b, iterations=int(round(1.0 / res)))
    dist = nd.distance_transform_edt(~b) * res
    # sky-view estimate of the open ground (bldg_ao_build.py formula)
    hb = np.where(b, np.maximum(hag, 0.0), 0.0)
    t = np.zeros_like(hb)
    for s in SCALES:
        t = np.maximum(t, nd.gaussian_filter(hb, s / res) / s)
    svf = 1.0 / (1.0 + t * t)
    can = fill_nearest(1.0 - svf, ~b)
    # building height per footprint (for the lean zone)
    lab, nl = nd.label(b)
    hmax = nd.maximum(hag, lab, index=np.arange(1, nl + 1)) if nl else np.zeros(0)
    hpx = np.zeros_like(hag)
    if nl:
        hpx[b] = np.asarray(hmax)[lab[b] - 1]
    near_idx = nd.distance_transform_edt(~b, return_distances=False, return_indices=True)
    hn = hpx[tuple(near_idx)]
    lz = np.where(hn >= 15.0, lean_k * hn, 0.0)
    lean = np.clip(1.0 - np.maximum(dist - 2.0, 0.0) / np.maximum(lz, 1.0), 0.0, 1.0)
    lean = np.where(dist <= 2.0, 1.0, np.where(lz > 0, lean, 0.0))
    lean = nd.gaussian_filter(lean, 1.0 / res)
    np.savez_compressed(os.path.join(out, "rasters.npz"), dtm=dtm.astype(np.float32), bm=bm.astype(np.float32),
                        dist=dist.astype(np.float32), can=can.astype(np.float32), lean=lean.astype(np.float32),
                        hag=hag.astype(np.float32), tree=tree, x0=z["x0"], y0=z["y0"], res=res,
                        made=time.strftime("%Y-%m-%d %H:%M:%S"), kind=kind)
    from PIL import Image
    g = (dsm_f - np.nanpercentile(dsm_f, 1)) / max(np.nanpercentile(dsm_f, 99) - np.nanpercentile(dsm_f, 1), 1)
    rgb = np.stack([np.clip(g, 0, 1)] * 3, -1) * 200
    rgb[b] = rgb[b] * 0.5 + np.array([255, 40, 40]) * 0.5
    rgb[tree] = rgb[tree] * 0.5 + np.array([40, 220, 40]) * 0.5
    Image.fromarray(rgb[::-1].astype(np.uint8)).save(os.path.join(out, "mask.png"))
    st = dict(building_frac=float(b.mean()), tree_frac=float(tree.mean()), ground_frac=float(ground.mean()),
              n_buildings=int(nl), hag_bld_med=float(np.median(hag[b])) if b.any() else 0.0,
              dtm_range=[float(dtm.min()), float(dtm.max())])
    json.dump(st, open(os.path.join(out, "classify.json"), "w"), indent=1)
    print(out, st)


if __name__ == "__main__":
    a = sys.argv[1:]
    main(a[0], a[1], float(a[3]) if len(a) > 3 and a[2] == "--lean" else 0.25)
