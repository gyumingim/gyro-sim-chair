"""Shared pieces of the Busan 'life' layer (moving cars and ships): local frame, instance file format, deterministic RNG.
Used by sim/traffic_build.py, sim/ships_build.py (offline, numpy) - the Unreal side (Content/Python/life_look.py) reads the
same file format with the standard library only.

Local frame: east-north-up tangent plane at ANCHOR (ellipsoid height 0), stored the Unreal way: X = north, Y = east,
Z = up, centimetres. life_look puts the whole actor at the right place for the current Cesium origin with one rigid
transform, so moving the georeference origin never needs the instances again.

Instance file (C:/GyroSimTiles/life/<name>.bin + <name>.json):
  json: dict(made, input, anchor, groups=[dict(name, mesh, kind, count, offset)], ...)
  bin : per group `count` records of REC float32 (little endian):
        x, y, z (cm, local frame), yaw, pitch (deg, UE rotator), cd0..cd7 (the material's per-instance custom data)
  custom data (M_GyroLife, Scripts/life_material.py): see life_material.CD
        0 L     piece length cm (the instance shows while 0 <= x < L)
        1 c     lattice phase cm in [0, D)
        2 j     slot of this instance on its piece (x = .. + j D)
        3 v     speed cm/s (0 = parked / at anchor: x = c + jD)
        4 D     spacing along the lane cm
        5 seed  lane seed in [0, 1) (colour / variant = hash(seed, car number n))
        6 flags 1 = first piece of an open chain (grow in), 2 = last piece (shrink out)
        7 K     integer: car number n = j + K - floor((t v + c) / D) - the same car keeps its colour from piece to piece
  x(t) = mod(t * v + c, D) + j D : every instance of a lane sits on the same lattice (cars D apart), so a car that leaves
  piece k at its end is the car that appears at the start of piece k + 1 at the same moment - no popping inside a chain.
"""
import math, os, struct

import numpy as np

ANCHOR = (35.12, 129.07)                    # lat, lon - middle of Busan harbour; local frame origin (ellipsoid h 0)
OUT = os.environ.get("GYROSIM_LIFE", r"C:\GyroSimTiles\life")
REC = 13                                    # floats per record: x y z yaw pitch + 8 custom data
NCD = 8
A, E2 = 6378137.0, 6.69437999014e-3


def ecef(lat, lon, h):
    la, lo = np.radians(lat), np.radians(lon)
    sl, cl = np.sin(la), np.cos(la)
    n = A / np.sqrt(1 - E2 * sl * sl)
    return np.stack(((n + h) * cl * np.cos(lo), (n + h) * cl * np.sin(lo), (n * (1 - E2) + h) * sl), -1)


def _axes(lat, lon):
    la, lo = math.radians(lat), math.radians(lon)
    sl, cl, so, co = math.sin(la), math.cos(la), math.sin(lo), math.cos(lo)
    return np.array((-so, co, 0.0)), np.array((-sl * co, -sl * so, cl)), np.array((cl * co, cl * so, sl))


_O = ecef(np.array(ANCHOR[0]), np.array(ANCHOR[1]), np.array(0.0))
_E, _N, _U = _axes(*ANCHOR)


def local(lat, lon, h_ell):
    """lat / lon / ellipsoid height (m) -> local X north, Y east, Z up in METRES (n, 3)."""
    d = ecef(np.asarray(lat, float), np.asarray(lon, float), np.asarray(h_ell, float)) - _O
    return np.stack((d @ _N, d @ _E, d @ _U), -1)


# flat helper for planning (metres east / north of ANCHOR, good to ~1e-3 over 40 km - only for lane geometry)
KX = 111320.0 * math.cos(math.radians(ANCHOR[0]))
KY = 110574.0


def en(lat, lon):
    return (np.asarray(lon) - ANCHOR[1]) * KX, (np.asarray(lat) - ANCHOR[0]) * KY


def latlon(e, n):
    return ANCHOR[0] + np.asarray(n) / KY, ANCHOR[1] + np.asarray(e) / KX


def rng(name, seed=20261110):
    """deterministic generator per named stream (captures repeat exactly)."""
    h = 0
    for ch in name:
        h = (h * 131 + ord(ch)) % 2147483647
    return np.random.default_rng((seed * 1000003 + h) % (2 ** 63))


def write(name, groups, meta):
    """groups: list of (group name, mesh asset, kind, records (n, REC) float32). -> path of the .bin"""
    import json, time
    os.makedirs(OUT, exist_ok=True)
    binp, jsp = os.path.join(OUT, name + ".bin"), os.path.join(OUT, name + ".json")
    idx, off = [], 0
    with open(binp + ".part", "wb") as f:
        for g, mesh, kind, recs in groups:
            r = np.ascontiguousarray(recs, dtype="<f4").reshape(-1, REC)
            f.write(r.tobytes())
            idx.append(dict(name=g, mesh=mesh, kind=kind, count=int(len(r)), offset=off))
            off += r.nbytes
    os.replace(binp + ".part", binp)
    out = dict(made=time.strftime("%Y-%m-%d %H:%M:%S"), anchor=ANCHOR, rec=REC, ncd=NCD, groups=idx, **meta)
    with open(jsp, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=1, ensure_ascii=False)
    return binp


def lanes_to_records(P, closed, v, D, seed_rng, piece_max, start_flag=True, end_flag=True, phase=None):
    """one directed lane = polyline P (n, 3) local metres -> records (m, REC) on the lane lattice.
    closed: P[0] == P[-1] loop -> D is adjusted so the loop length is a whole number of spacings (seamless).
    v m/s, D m. Pieces are split to <= piece_max m. phase: lattice phase m (random if None)."""
    P = np.asarray(P, float)
    seg = np.diff(P, axis=0)
    ln = np.linalg.norm(seg, axis=1)
    keep = ln > 0.05
    if not keep.any():
        return np.zeros((0, REC), np.float32)
    # split long segments
    pts = [P[0]]
    for k in range(len(seg)):
        if not keep[k]:
            continue
        m = max(1, int(math.ceil(ln[k] / piece_max)))
        for j in range(1, m + 1):
            pts.append(P[k] + seg[k] * (j / m))
    P = np.array(pts)
    seg = np.diff(P, axis=0)
    ln = np.linalg.norm(seg, axis=1)
    S = float(ln.sum())
    if closed:
        D = S / max(1, round(S / D))
    s0 = np.concatenate(([0.0], np.cumsum(ln)[:-1]))
    ph = float(seed_rng.uniform(0, D)) if phase is None else phase
    lane_seed = float(seed_rng.random())
    out = []
    for k in range(len(seg)):
        L = ln[k]
        c = (ph - s0[k]) % D                      # global position g = t v + ph + i D ; on this piece x = g - s0
        K = round((c + s0[k] - ph) / D)
        hz = math.hypot(seg[k, 0], seg[k, 1])
        yaw = math.degrees(math.atan2(seg[k, 1], seg[k, 0]))
        pitch = math.degrees(math.atan2(seg[k, 2], hz))
        fl = 0.0
        if not closed:
            if k == 0 and start_flag:
                fl += 1.0
            if k == len(seg) - 1 and end_flag:
                fl += 2.0
        nj = int(math.ceil(L / D)) if v > 0 else 0
        for j in range(max(1, nj)):
            out.append((P[k, 0] * 100, P[k, 1] * 100, P[k, 2] * 100, yaw, pitch,
                        L * 100, c * 100, j, v * 100, D * 100, lane_seed, fl, K))
    return np.array(out, np.float32).reshape(-1, REC)
