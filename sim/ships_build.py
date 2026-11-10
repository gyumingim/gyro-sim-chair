"""Ships around Busan (Unreal 'life' layer): hand-drawn sea lanes (closed loops, so no ship ever pops in or out) and
anchored ships -> instance records for the 'GyroLife' actor (Content/Python/life_look.py; materials M_GyroLifeShip /
M_GyroLifeWake move them and draw the wakes on the GPU).

    python -I sim/ships_build.py --build      -> C:\\GyroSimTiles\\life\\ships.bin / ships.json (+ water grid cache)
    python -I sim/ships_build.py --map        -> C:\\GyroSimTiles\\life\\ships_map.png (lanes on the water mask, check)

Lanes are waypoints (lat, lon) drawn from the chart picture of Busan (북항 / 감만 / 신선대 approaches, 남항, 감천,
광안리 / 해운대 coast, 영도 묘박지 (anchorage), the 부산-일본 ferry line out to the south-east). They are 추정, not AIS
tracks. Every waypoint is pushed to water with enough clearance for the ship (the rendered terrain mesh: height <= 0.3 m
MSL = sea; clearance = distance to land), legs that still cross land get an extra point, corners are rounded (Chaikin).
Sea level = 0 m MSL + EGM2008 N (= the flattened sea of the terrain tiles). Deterministic (life_common.rng).
"""
import json, math, os, sys, time, site
if sys.flags.isolated:
    site.addsitedir(site.getusersitepackages())
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import numpy as np                                        # noqa: E402
import life_common as LC                                  # noqa: E402

GRID = os.path.join(LC.OUT, "water_grid.npz")
BOX = (34.93, 128.93, 35.22, 129.30)                      # S W N E of the water grid
RES = 40.0
KN = 0.5144
# ship types: mesh, length m (mesh size), speed knots, clearance m (from land), spacing on a loop m, wake
TYPES = dict(
    container=dict(mesh="SM_LifeContainer", len=300.0, kn=11.0, clr=180.0, wake=True),
    feeder=dict(mesh="SM_LifeFeeder", len=170.0, kn=12.0, clr=130.0, wake=True),
    ferry=dict(mesh="SM_LifeFerry", len=165.0, kn=17.0, clr=130.0, wake=True),
    fishing=dict(mesh="SM_LifeFishing", len=24.0, kn=8.0, clr=60.0, wake=True),
    boat=dict(mesh="SM_LifeBoat", len=13.0, kn=16.0, clr=50.0, wake=True),
    tug=dict(mesh="SM_LifeTug", len=30.0, kn=9.0, clr=60.0, wake=True),
    bulk=dict(mesh="SM_LifeBulk", len=225.0, kn=0.0, clr=200.0, wake=False),
)
# loops: (name, type, ships on the loop, waypoints lat/lon) - first point repeated at the end by the builder
LOOPS = [
    # 북항: container ships in from the south-east past 오륙도 to 감만 / 신선대 and out again (inbound west of outbound)
    ("northport_container", "container", 5, [(34.96, 129.24), (35.045, 129.150), (35.078, 129.112), (35.092, 129.098),
                                             (35.100, 129.085), (35.096, 129.074), (35.088, 129.090), (35.072, 129.122),
                                             (35.040, 129.168), (34.97, 129.27)]),
    ("northport_feeder", "feeder", 5, [(34.99, 129.20), (35.060, 129.128), (35.085, 129.100), (35.098, 129.070),
                                       (35.104, 129.058), (35.098, 129.060), (35.090, 129.080), (35.070, 129.118), (35.000, 129.215)]),
    # 부산-일본 ferry: 국제여객터미널 (북항) -> breakwater -> 오륙도 -> south-east toward 대마도 / 후쿠오카 and back
    ("japan_ferry", "ferry", 3, [(35.112, 129.050), (35.104, 129.062), (35.093, 129.090), (35.080, 129.118),
                                 (35.040, 129.170), (34.95, 129.30), (34.935, 129.285), (35.030, 129.165),
                                 (35.074, 129.115), (35.090, 129.084), (35.103, 129.058)]),
    # 남항 / 영도 west: small cargo and tugs between 남항 and the outer anchorage
    ("namhang_tug", "tug", 3, [(35.085, 129.030), (35.070, 129.035), (35.050, 129.045), (35.040, 129.060),
                               (35.050, 129.055), (35.068, 129.040)]),
    ("northport_tug", "tug", 3, [(35.104, 129.060), (35.100, 129.080), (35.092, 129.094), (35.097, 129.072)]),
    # 감천항 fishing boats out to the south
    ("gamcheon_fishing", "fishing", 4, [(35.074, 129.000), (35.060, 129.005), (35.048, 129.009), (35.030, 129.015),
                                        (35.010, 129.000), (35.025, 128.990), (35.040, 129.003), (35.056, 129.006)]),
    # 남항 (자갈치 / 공동어시장) fishing fleet
    ("namhang_fishing", "fishing", 5, [(35.084, 129.031), (35.078, 129.032), (35.065, 129.028), (35.040, 129.020), (35.010, 129.060),
                                       (35.030, 129.080), (35.055, 129.050), (35.072, 129.036)]),
    # 광안리 bay: yachts / tour boats under 광안대교
    ("gwangalli_boats", "boat", 5, [(35.152, 129.128), (35.145, 129.120), (35.135, 129.125), (35.130, 129.140),
                                    (35.142, 129.145), (35.150, 129.140)]),
    ("gwangalli_out", "boat", 3, [(35.148, 129.135), (35.125, 129.135), (35.110, 129.150), (35.120, 129.170),
                                  (35.140, 129.160)]),
    # 해운대 / 미포 / 청사포 coast: tour boats and fishing
    ("haeundae_boats", "boat", 4, [(35.150, 129.163), (35.145, 129.175), (35.150, 129.190), (35.140, 129.200),
                                   (35.130, 129.180), (35.138, 129.160)]),
    ("haeundae_fishing", "fishing", 4, [(35.155, 129.195), (35.140, 129.215), (35.110, 129.230), (35.100, 129.200),
                                        (35.125, 129.185)]),
    # 영도 east / 태종대 sightseeing and fishing
    ("taejongdae_boats", "boat", 3, [(35.085, 129.095), (35.065, 129.100), (35.045, 129.095), (35.040, 129.075),
                                     (35.055, 129.105), (35.075, 129.105)]),
]
# 영도 / 남외항 anchorage (묘박지): ships at anchor, (lat, lon, type) - headings swing together with the wind
ANCHOR_HDG = 25.0                                         # deg true the bows point (north-east wind, 추정), +- 15 per ship
ANCHORED = [(35.040, 129.020, "bulk"), (35.032, 129.040, "bulk"), (35.045, 129.040, "container"), (35.025, 129.060, "bulk"),
            (35.020, 129.030, "feeder"), (35.012, 129.050, "bulk"), (35.036, 129.075, "feeder"), (35.010, 129.075, "bulk"),
            (35.000, 129.035, "container"), (35.050, 129.110, "bulk"), (35.040, 129.125, "feeder"), (34.995, 129.065, "bulk")]


def grid():
    """water grid (height, clearance to land in m), built once from the rendered terrain mesh."""
    if os.path.isfile(GRID):
        z = np.load(GRID)
        if tuple(z["box"]) == BOX and float(z["res"]) == RES:
            return z["h"], z["clr"]
    import terrain_dem as T
    import buildings_build as B
    from scipy import ndimage
    S, W, N, E = BOX
    ny = int((N - S) * 110574 / RES)
    nx = int((E - W) * 111320 * math.cos(math.radians(35.1)) / RES)
    LA, LO = np.meshgrid(np.linspace(N, S, ny), np.linspace(W, E, nx), indexing="ij")
    h = B.mesh_height(T.Dem(), LA.ravel(), LO.ravel()).reshape(ny, nx)
    clr = ndimage.distance_transform_edt(h <= 0.3) * RES
    os.makedirs(LC.OUT, exist_ok=True)
    np.savez_compressed(GRID, h=h.astype(np.float32), clr=clr.astype(np.float32), box=np.array(BOX), res=RES)
    return h, clr


def _ij(lat, lon, shape):
    S, W, N, E = BOX
    i = (N - np.asarray(lat)) / (N - S) * (shape[0] - 1)
    j = (np.asarray(lon) - W) / (E - W) * (shape[1] - 1)
    return i, j


def clearance(clr, lat, lon):
    i, j = _ij(lat, lon, clr.shape)
    inside = (i >= 0) & (i <= clr.shape[0] - 1) & (j >= 0) & (j <= clr.shape[1] - 1)
    ii = np.clip(np.round(i).astype(int), 0, clr.shape[0] - 1)
    jj = np.clip(np.round(j).astype(int), 0, clr.shape[1] - 1)
    return np.where(inside, clr[ii, jj], 1e5)               # outside the grid = open sea (the box ends at sea)


def push(clr, lat, lon, need):
    """nearest grid cell with clearance >= need (search outwards), -> (lat, lon, moved m)."""
    if clearance(clr, lat, lon) >= need:
        return lat, lon, 0.0
    i, j = _ij(lat, lon, clr.shape)
    i, j = int(round(float(i))), int(round(float(j)))
    for r in range(1, 200):
        ii, jj = np.mgrid[i - r:i + r + 1, j - r:j + r + 1]
        ok = (ii >= 0) & (jj >= 0) & (ii < clr.shape[0]) & (jj < clr.shape[1])
        ii, jj = ii[ok], jj[ok]
        good = clr[ii, jj] >= need
        if good.any():
            d = (ii - i) ** 2 + (jj - j) ** 2
            d = np.where(good, d, 1 << 30)
            k = int(np.argmin(d))
            S, W, N, E = BOX
            la = N - ii[k] / (clr.shape[0] - 1) * (N - S)
            lo = W + jj[k] / (clr.shape[1] - 1) * (E - W)
            return la, lo, math.sqrt(d[k]) * RES
    return lat, lon, -1.0


def fix_loop(clr, pts, need, log):
    P = []
    for la, lo in pts:
        la2, lo2, m = push(clr, la, lo, need)
        if m:
            log("   point %.4f %.4f moved %.0f m" % (la, lo, m))
        P.append((la2, lo2))
    P.append(P[0])
    # legs over land: insert the pushed midpoint, a few rounds
    for _ in range(6):
        out, bad = [P[0]], 0
        for a, b in zip(P, P[1:]):
            n = max(2, int(math.hypot((b[0] - a[0]) * 110574, (b[1] - a[1]) * 91000) / 40))
            f = np.linspace(0, 1, n)
            c = clearance(clr, a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f)
            if c.min() < need * 0.7:
                bad += 1
                k = int(np.argmin(c))
                la2, lo2, _ = push(clr, a[0] + (b[0] - a[0]) * f[k], a[1] + (b[1] - a[1]) * f[k], need)
                out.append((la2, lo2))
            out.append(b)
        P = out
        if not bad:
            break
    return P


def simplify(X, tol):
    from traffic_build import simplify as dp
    Y = dp(np.asarray(X, float), tol)
    return Y


def chaikin(P, rounds=3):
    P = np.asarray(P, float)
    for _ in range(rounds):
        Q = P[:-1] * 0.75 + P[1:] * 0.25
        R = P[:-1] * 0.25 + P[1:] * 0.75
        P = np.empty((2 * len(Q), 2))
        P[0::2], P[1::2] = Q, R
        P = np.vstack((P, P[:1]))
    return P


def build(write=True):
    import terrain_dem as T
    t0 = time.time()
    h, clr = grid()
    dem = T.Dem()
    lines = []
    log = lambda *a: lines.append(" ".join(str(x) for x in a)) or print(*a, flush=True)
    groups, wakes, plan = {}, [], []
    for name, typ, nships, pts in LOOPS:
        ty = TYPES[typ]
        P = fix_loop(clr, pts, ty["clr"], log)
        P = chaikin(P)
        f = np.linspace(0, 1, 5)[:-1]                         # rounded corners / legs may cut a point: push those back
        P = np.concatenate([P[k] + (P[k + 1] - P[k]) * f[:, None] for k in range(len(P) - 1)])
        for k in range(len(P)):
            if clearance(clr, P[k, 0], P[k, 1]) < ty["clr"] * 0.6:
                P[k] = push(clr, P[k, 0], P[k, 1], ty["clr"] * 0.6)[:2]
        P = chaikin(np.vstack((P, P[:1])), 1)
        f = np.linspace(0, 1, 8)[:-1]                         # clearance along the legs, not only at the points
        dense = np.concatenate([P[k] + (P[k + 1] - P[k]) * f[:, None] for k in range(len(P) - 1)])
        c = clearance(clr, dense[:, 0], dense[:, 1])
        if c.min() < ty["clr"] * 0.3:
            kk = np.where(c < ty["clr"] * 0.3)[0]
            log("   WARN %s: %d samples closer than %.0f m to land, first at %.4f %.4f" % (name, len(kk), ty["clr"] * 0.3, dense[kk[0], 0], dense[kk[0], 1]))
        la, lo = P[:, 0], P[:, 1]
        he = dem.geoid_n(la, lo)                              # sea = 0 MSL
        X = LC.local(la, lo, he)
        S = float(np.linalg.norm(np.diff(X, axis=0), axis=1).sum())
        g = LC.rng("ship_" + name)
        v = ty["kn"] * KN * float(g.uniform(0.9, 1.1))
        X = simplify(X, 3.0)                                  # few long pieces = few instances (each runs the vertex shader)
        R = LC.lanes_to_records(X, True, v, S / nships, g, 1500.0)
        R[:, 10] += 0.0
        groups.setdefault(typ, []).append(R)
        if ty["wake"]:
            wakes.append((typ, R))
        plan.append(dict(name=name, type=typ, ships=nships, km=round(S / 1000, 2), knots=round(v / KN, 1),
                         lap_min=round(S / v / 60, 1), min_clearance_m=round(float(c.min())), pieces=int(len(R)),
                         lat=[round(float(x), 5) for x in la[::4]], lon=[round(float(x), 5) for x in lo[::4]]))
        log("%-20s %-9s %d ships  %5.1f km  %4.1f kn  lap %5.1f min  min clearance %4.0f m  %d instances" % (
            name, typ, nships, S / 1000, v / KN, S / v / 60, c.min(), len(R)))
    g = LC.rng("anchored")
    for la, lo, typ in ANCHORED:
        la2, lo2, m = push(clr, la, lo, TYPES[typ]["clr"] * 1.2)
        if m:
            log("   anchored %.4f %.4f moved %.0f m" % (la, lo, m))
        X = LC.local(np.array([la2]), np.array([lo2]), dem.geoid_n(np.array([la2]), np.array([lo2])))[0]
        hdg = ANCHOR_HDG + float(g.uniform(-15, 15))
        r = np.array([[X[0] * 100, X[1] * 100, X[2] * 100, hdg, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0, float(g.random()), 0.0, 0.0]], np.float32)
        groups.setdefault(typ, []).append(r)
        plan.append(dict(name="anchored", type=typ, lat=round(la2, 5), lon=round(lo2, 5), hdg=round(hdg, 1)))
    out = []
    for typ, rs in groups.items():
        out.append((typ, TYPES[typ]["mesh"], "ship", np.concatenate(rs)))
    wk = np.concatenate([r for _, r in wakes]) if wakes else np.zeros((0, LC.REC), np.float32)
    # wake instance scale = ship length / 100 m (SM_LifeWake is drawn for a 100 m ship): x y z yaw pitch + cd, scale in json
    wscale = np.concatenate([np.full(len(r), TYPES[t]["len"] / 100.0, np.float32) for t, r in wakes]) if wakes else np.zeros(0, np.float32)
    wk = wk.copy()
    out.append(("wake", "SM_LifeWake", "wake", wk))
    meta = dict(input=dict(water_grid=GRID, note="lanes = hand-drawn waypoints (추정), pushed to water with clearance"),
                seconds=round(time.time() - t0), loops=plan, types=TYPES, wake_scale=[round(float(x), 3) for x in wscale],
                log=lines)
    if write:
        p = LC.write("ships", out, meta)
        print("done: %s -> %s" % (", ".join("%s %d" % (o[0], len(o[3])) for o in out), p), flush=True)
    return plan, h, clr


def draw_map():
    from PIL import Image, ImageDraw
    plan, h, clr = build(write=False)
    water = h <= 0.3
    im = np.where(water[..., None], np.array([30, 70, 140]), np.array([190, 190, 185])).astype(np.uint8)
    img = Image.fromarray(im).resize((h.shape[1] * 2, h.shape[0] * 2), Image.NEAREST)
    dr = ImageDraw.Draw(img)
    col = dict(container=(255, 80, 60), feeder=(255, 160, 60), ferry=(255, 255, 255), fishing=(80, 255, 120), boat=(255, 120, 255),
               tug=(255, 230, 0), bulk=(0, 0, 0))
    for p in plan:
        if p["name"] == "anchored":
            i, j = _ij(p["lat"], p["lon"], h.shape)
            dr.ellipse((j * 2 - 6, i * 2 - 6, j * 2 + 6, i * 2 + 6), fill=col[p["type"]], outline=(255, 255, 255))
            continue
        i, j = _ij(np.array(p["lat"]), np.array(p["lon"]), h.shape)
        dr.line(list(zip(j * 2, i * 2)), fill=col[p["type"]], width=3)
    S, W, N, E = BOX
    for la in np.arange(34.95, 35.22, 0.05):
        i, _ = _ij(la, W, h.shape)
        dr.text((4, i * 2), "%.2f" % la, fill=(0, 0, 0))
    for lo in np.arange(128.95, 129.30, 0.05):
        _, j = _ij(S, lo, h.shape)
        dr.text((j * 2, 4), "%.2f" % lo, fill=(0, 0, 0))
    p = os.path.join(LC.OUT, "ships_map.png")
    img.save(p)
    print("map ->", p)


if __name__ == "__main__":
    if "--map" in sys.argv:
        draw_map()
    if "--build" in sys.argv:
        build()
