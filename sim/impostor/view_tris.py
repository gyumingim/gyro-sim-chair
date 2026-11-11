"""Triangles of the trees inside a shot view (Scripts/trees_near_shots.py VIEWS): blobs vs impostors, from the tree database
(trees_near.bin) and the blob tiles' per-tree triangles (blob_tris.py). Frustum: horizontal FOV 70, 16:9.
Blob LOD at 1080p: near tiles (~309 tri) inside GE_b * 1080 / (2 tan(fovy/2) * SSE) = 12 * 85.7 = 1.03 km, far (~28 tri) to
45 * 85.7 = 3.86 km (sim/veg_v2.GE2, trees_look SSE 16). Impostors: 2 triangles per tree inside 3.9 km.
    python -I sim/impostor/view_tris.py [views]
"""
import json, math, os, sys, site
if sys.flags.isolated:
    site.addsitedir(site.getusersitepackages())
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import numpy as np                                                      # noqa: E402
import life_common as L                                                 # noqa: E402

DIR = r"C:/GyroSimTiles/veg/near"
GEOID = 29.2
VIEWS = {"hwang_low": (35.1590, 129.0870, 320.0, 60.0, 320.0, 440.0), "park_low": (35.1685, 129.0570, 30.0, 180.0, 320.0, 140.0),
         "jang_mid": (35.1920, 129.1480, 500.0, 150.0, 1500.0, 1050.0)}
NEAR_T, FAR_T, IMP_T = 309.2, 27.6, 2
R_NEAR, R_FAR, R_IMP = 1030.0, 3860.0, 3900.0


def main(views):
    meta = json.load(open(DIR + "/trees_near.json"))
    rec = meta["rec"]
    raw = np.fromfile(DIR + "/trees_near.bin", np.float32).reshape(-1, rec)
    out = {}
    for v in views:
        lat, lon, th, brg, dist, ch = VIEWS[v]
        # target / camera in the local frame (X north, Y east, Z up, cm)
        tgt = np.array(L.local(lat, lon, th + GEOID), float).ravel() * (100.0 if np.abs(L.local(lat, lon, 0)).max() < 1e6 else 1.0)
        br = math.radians(brg)
        dn, de = dist * math.cos(br), dist * math.sin(br)
        clat, clon = lat + dn / L.KY, lon + de / L.KX
        cam = np.array(L.local(clat, clon, ch + GEOID), float).ravel() * (100.0 if np.abs(L.local(lat, lon, 0)).max() < 1e6 else 1.0)
        P = raw[:, :3].astype(np.float64)
        d = P - cam
        hd = np.hypot(d[:, 0], d[:, 1]) / 100.0
        sel = hd < 4000
        d = d[sel]; hd = hd[sel]
        f = tgt - cam; f /= np.linalg.norm(f)
        r = np.cross(f, [0, 0, 1.0]); r /= np.linalg.norm(r); u = np.cross(r, f)
        z = d @ f
        tx, ty = math.tan(math.radians(35)), math.tan(math.radians(35)) * 9 / 16
        inview = (z > 0) & (np.abs(d @ r) < z * tx + 1500) & (np.abs(d @ u) < z * ty + 1500)
        near = inview & (hd < R_NEAR); far = inview & (hd >= R_NEAR) & (hd < R_FAR); imp = inview & (hd < R_IMP)
        blob = near.sum() * NEAR_T + far.sum() * FAR_T
        out[v] = dict(trees_in_view=int(imp.sum()), blob_near=int(near.sum()), blob_far=int(far.sum()), blob_tris=int(blob),
                      imp_tris=int(imp.sum() * IMP_T), ratio=round(blob / max(imp.sum() * IMP_T, 1), 1))
        print(v, out[v])
    json.dump(out, open(os.path.join(r"C:/GyroSimTiles/shots/trees_imp", "view_tris.json"), "w"), indent=1)


if __name__ == "__main__":
    main(sys.argv[1].split(",") if len(sys.argv) > 1 else list(VIEWS))
