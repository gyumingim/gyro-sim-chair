"""Colour calibration of the impostor trees against the old blob trees in the same game views (the blob colours were tuned
on the real Busan photos, sim/veg_v2.py TINT notes): mean linear colour of the pixels the trees change (vs the no-tree shot).
    python -I sim/impostor/calib.py <imp shots dir> <blob shots dir> [views]
"""
import os, sys, site
if sys.flags.isolated:
    site.addsitedir(site.getusersitepackages())
import numpy as np, cv2                                                 # noqa: E402


def lin(p):
    x = cv2.imread(p)[..., ::-1].astype(np.float64) / 255
    return np.where(x <= 0.04045, x / 12.92, ((x + 0.055) / 1.055) ** 2.4)


def tree_mean(shot, none):
    a, b = lin(shot), lin(none)
    m = np.abs(a - b).sum(-1) > 0.012
    return a[m].mean(0), m.mean()


if __name__ == "__main__":
    di, db = sys.argv[1], sys.argv[2]
    views = sys.argv[3].split(",") if len(sys.argv) > 3 else ["hwang_low", "park_low", "jang_mid"]
    ri, rb = [], []
    for v in views:
        none = os.path.join(di, v + "_none.png")
        mi, fi = tree_mean(os.path.join(di, v + "_imp.png"), none)
        mb, fb = tree_mean(os.path.join(db, v + "_blob.png"), none)
        print(v, "imp", mi.round(4), "cover %.2f" % fi, "| blob", mb.round(4), "cover %.2f" % fb, "| ratio", (mb / mi).round(3))
        ri.append(mi); rb.append(mb)
    r = np.mean(rb, 0) / np.mean(ri, 0)
    print("mean ratio blob / imp (per channel)", r.round(3))
