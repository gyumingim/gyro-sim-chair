"""Measures the inner limits of the FlightGear F-16 exterior around the cockpit (skin half width per x / z, canopy
glass bottom edge and top) by slicing ThirdParty/f16_obj/F16_Exterior.obj and F16_Glass.obj, and prints the tables
used as FIT_* in layout.py (our tub must stay inside that skin: no poke-through / z-fighting in the chase view).
Only needed again if the exterior model changes.  python fit_exterior.py
"""
import os
import numpy as np

D = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "ThirdParty", "f16_obj"))


def load(f):
    V, T = [], []
    for l in open(os.path.join(D, f)):
        if l.startswith("v "):
            _, x, y, z = l.split()[:4]
            V.append((float(x), float(z), float(y)))          # OBJ = (ue_x, ue_z, ue_y)
        elif l.startswith("f "):
            idx = [int(p.split("/")[0]) - 1 for p in l.split()[1:]]
            T += [(idx[0], idx[i], idx[i + 1]) for i in range(1, len(idx) - 1)]
    return np.array(V), np.array(T)


def slice_x(V, T, x):
    P = V[T]
    d = P[:, :, 0] - x
    out = []
    for tri, dd in zip(P, d):
        if dd.max() <= 0 or dd.min() >= 0:
            continue
        pts = [tri[a] + dd[a] / (dd[a] - dd[b]) * (tri[b] - tri[a]) for a, b in ((0, 1), (1, 2), (2, 0)) if (dd[a] > 0) != (dd[b] > 0)]
        if len(pts) == 2:
            out.append(pts)
    return np.array(out)


if __name__ == "__main__":
    E, G = load("F16_Exterior.obj"), load("F16_Glass.obj")
    for x in range(360, 571, 10):
        S = slice_x(*E, x)
        row = []
        for z in range(-10, 71, 10):
            ys = [abs(a[1] + (z - a[2]) / (b[2] - a[2]) * (b[1] - a[1])) for a, b in S if (a[2] - z) * (b[2] - z) <= 0 and a[2] != b[2]]
            ys = [y for y in ys if y < 90]
            row.append(float(round(max(ys), 1)) if ys else None)
        Sg = slice_x(*G, x)
        gl = None
        if len(Sg):
            P = Sg.reshape(-1, 3)
            i = P[:, 2].argmin()
            gl = tuple(float(round(v, 1)) for v in (abs(P[i, 1]), P[i, 2], P[:, 2].max()))
        print(x, "skin z-10..70:", row, "glass (bottom |y|, bottom z, top z):", gl)
