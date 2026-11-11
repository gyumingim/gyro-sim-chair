"""Grounded day (11-11, docs/grounded-day-busan.md): building occlusion field for the Busan box, render-time data for the
ground and building materials. Built from the GIS building footprints + heights only (buildings_build.py work npz; no
V-World imagery is read or stored).

  python -I sim/bldg_ao_build.py   -> C:/GyroSimTiles/buildings/ao/bldg_ao.png (8192 x 8192 RGBA, linear) + bldg_ao.json

Same equirectangular grid as the coast mask (coast_build.py BOX / MASK_N, row 0 = north), so the materials reuse the
MPC_GyroCoast world -> UV rows. Channels:
  R  sky-view factor of the ground (1 = open sky). Estimate, not a ray-traced SVF: the mean horizon tangent at distance s
     is taken as gaussian-mean(building height, sigma = s) / s for s = 6..192 m, t = max over s, SVF = 1 / (1 + t^2)
     (= cos^2 of the horizon angle). Inside a footprint: the value of the nearest open-ground pixel.
  G  building base, m MSL + 5 (1 m steps, 0..250 m), nearest building outside footprints (the facade samples it at its foot)
  B  'lean zone' near tall buildings: max over buildings of 1 - d / (0.25 h) outside the footprint (h >= 20 m), where the
     ortho photo's off-nadir lean puts the tower's own facade / roof on the ground (bright skirt at the foot)
  A  signed distance to the nearest footprint edge (contact band, 11-12 docs/research/building-grounding-study.md):
     A = (d + 8) x 8, d in m (< 0 inside, -8 .. +23.9 m in 1/8 m steps; inside = A < 64). Computed on a 2x finer grid
     and averaged (edge position error ~ +-1.5 m instead of +-3 m); bilinear filtering keeps it exact along straight walls.
Lumen sees no Cesium mesh (no distance fields, HW ray tracing off), so the sky light reaches street canyons unoccluded:
the materials put R into their AmbientOcclusion output (sky / indirect light only) - see ground_look.hlsl / buildings_facade.hlsl.
"""
import json, os, sys, time, site
if sys.flags.isolated:
    site.addsitedir(site.getusersitepackages())
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import numpy as np                                        # noqa: E402

WORK = os.environ.get("GYROSIM_BLDG_WORK", r"C:\GyroSimTiles\buildings\work")
OUT = os.environ.get("GYROSIM_BLDG_AO", r"C:\GyroSimTiles\buildings\ao")
BOX = (34.96, 128.75, 35.40, 129.33)                      # S W N E = coast_build.BOX (same grid as T_GyroCoast)
N = 8192
SCALES = (6.0, 12.0, 24.0, 48.0, 96.0, 192.0)             # m
LEAN = 0.25                                               # lean zone length / building height (off-nadir ~14 deg, 추정)


def polys(D):
    import shapely
    nring, rop = D["nring"], D["ring_of_poly"]
    ring_start = np.concatenate(([0], np.cumsum(nring)[:-1]))
    lon, lat = D["lon"], D["lat"]
    out = {}
    for r in range(len(nring)):                           # outer ring only (holes filled: courtyards count as building)
        p = int(rop[r])
        if p in out:
            continue
        a, b = ring_start[r], ring_start[r] + nring[r]
        if nring[r] >= 4:
            out[p] = shapely.Polygon(np.stack((lon[a:b], lat[a:b]), 1))
    return out


def main():
    import rasterio.features, rasterio.transform
    from scipy import ndimage
    t0 = time.time()
    s, w, n, e = BOX
    tr = rasterio.transform.from_origin(w, n, (e - w) / N, (n - s) / N)
    px = (e - w) / N * 111320.0 * np.cos(np.radians(0.5 * (s + n)))
    py = (n - s) / N * 110950.0
    pm = 0.5 * (px + py)
    H = np.zeros((N, N), np.float32)
    tr2 = rasterio.transform.from_origin(w, n, (e - w) / (2 * N), (n - s) / (2 * N))
    F2 = np.zeros((2 * N, 2 * N), bool)                   # footprints on the 2x grid (signed distance, channel A)
    BASE = np.full((N, N), np.nan, np.float32)
    srcs = []
    for f in sorted(os.listdir(WORK)):
        if not (f.startswith("buildings_") and f.endswith(".npz")):
            continue
        with np.load(os.path.join(WORK, f)) as z:          # plain arrays (NpzFile re-reads on every [] access)
            D = {k: z[k] for k in ("lon", "lat", "nring", "ring_of_poly", "h", "base", "clat", "clon")}
        inb = (D["clat"] > s) & (D["clat"] < n) & (D["clon"] > w) & (D["clon"] < e)
        if not inb.any():
            continue
        P = polys(D)
        idx = [i for i in np.argsort(D["h"]) if inb[i] and i in P]     # low first: the tallest wins where footprints touch
        h = rasterio.features.rasterize([(P[i], float(D["h"][i])) for i in idx], out_shape=(N, N), transform=tr, dtype=np.float32)
        b = rasterio.features.rasterize([(P[i], float(D["base"][i])) for i in idx], out_shape=(N, N), transform=tr, dtype=np.float32,
                                        fill=np.nan)
        F2 |= rasterio.features.rasterize([(P[i], 1) for i in idx], out_shape=(2 * N, 2 * N), transform=tr2, dtype=np.uint8) > 0
        upd = h > H
        H[upd] = h[upd]
        BASE[upd] = b[upd]
        srcs.append(dict(file=f, buildings=len(idx)))
        print(f, len(idx), "buildings", round(time.time() - t0), "s", flush=True)
    inside = H > 0.0
    # R: sky-view factor estimate
    t = np.zeros((N, N), np.float32)
    for sc in SCALES:
        m = ndimage.gaussian_filter(H, sc / pm, mode="constant")
        t = np.maximum(t, m / sc)
        print("scale", sc, round(time.time() - t0), "s", flush=True)
    svf = 1.0 / (1.0 + t * t)
    _, ind = ndimage.distance_transform_edt(inside, return_indices=True)
    svf = svf[ind[0], ind[1]]                            # inside: the nearest open pixel's value
    # G: base, nearest building outside
    d_out, ind2 = ndimage.distance_transform_edt(~inside, return_indices=True)
    base = BASE[ind2[0], ind2[1]]
    base = np.nan_to_num(base, nan=0.0)
    # B: lean zone near tall buildings (by height band)
    lean = np.zeros((N, N), np.float32)
    for h0, h1 in ((20, 40), (40, 80), (80, 160), (160, 1000)):
        sel = inside & (H >= h0) & (H < h1)
        if not sel.any():
            continue
        d = ndimage.distance_transform_edt(~sel) * pm
        hm = float(np.median(H[sel]))
        lean = np.maximum(lean, np.clip(1.0 - d / (LEAN * hm), 0.0, 1.0) * (~inside))
    # A: signed distance (m) on the 2x grid, averaged 2 x 2
    sd = ndimage.distance_transform_edt(~F2).astype(np.float32)
    sd -= ndimage.distance_transform_edt(F2).astype(np.float32)
    sd *= 0.5 * pm
    sd = sd.reshape(N, 2, N, 2).mean(axis=(1, 3))
    del F2
    img = np.stack([np.clip(svf * 255.0 + 0.5, 0, 255), np.clip(base + 5.0 + 0.5, 0, 255), np.clip(lean * 255.0 + 0.5, 0, 255),
                    np.clip((sd + 8.0) * 8.0 + 0.5, 0, 255)], -1).astype(np.uint8)
    os.makedirs(OUT, exist_ok=True)
    from PIL import Image
    Image.fromarray(img, "RGBA").save(os.path.join(OUT, "bldg_ao.png"), optimize=False, compress_level=6)
    oc = ~inside & (d_out * pm < 60.0)
    meta = dict(made=time.strftime("%Y-%m-%d %H:%M:%S"), seconds=round(time.time() - t0), box_swne=list(BOX), size=N,
                pixel_m=[float(px), float(py)], sources=srcs, scales_m=list(SCALES), lean=LEAN,
                encoding=dict(R="sky-view factor estimate x 255 (ground)", G="building base m MSL + 5 (nearest building)",
                              B="lean zone 1 - d / (0.25 h), h >= 20 m, x 255",
                              A="signed distance to the footprint edge (d + 8) x 8, d m (< 0 inside); inside = A < 64"),
                stats=dict(inside_frac=float(inside.mean()), svf_ground_near_buildings_median=float(np.median(svf[oc])) if oc.any() else None,
                           svf_ground_near_buildings_p10=float(np.percentile(svf[oc], 10)) if oc.any() else None,
                           base_max=float(np.nanmax(BASE)) if np.isfinite(BASE).any() else None, h_max=float(H.max())),
                note="GIS footprints / heights only (buildings_build.py work npz); render-time data, kept out of git")
    json.dump(meta, open(os.path.join(OUT, "bldg_ao.json"), "w"), indent=1)
    print(json.dumps(meta["stats"]), round(time.time() - t0), "s")


if __name__ == "__main__":
    main()
