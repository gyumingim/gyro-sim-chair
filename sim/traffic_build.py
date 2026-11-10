"""Moving cars on Busan's main roads (Unreal 'life' layer): OSM road centre lines -> directed lanes -> instance records
for the InstancedStaticMeshComponents of the 'GyroLife' actor (Content/Python/life_look.py, material M_GyroLife moves
them on the GPU - no per-frame Python).

    python -I sim/traffic_build.py --fetch    Overpass API, one request (~20-60 s) -> C:\\GyroSimTiles\\osm\\busan_traffic.json
    python -I sim/traffic_build.py --build    -> C:\\GyroSimTiles\\life\\traffic.bin / traffic.json

Data: OSM ways highway = motorway / trunk / primary / secondary / tertiary (+ _link) in the Busan box (ODbL,
(c) OpenStreetMap contributors; credit already on the roads plate). Tunnels are left out (cars would drive over the hill).
Heights: ground ways = the rendered Cesium terrain mesh (buildings_build.mesh_height + EGM2008 N) + 0.10 m; bridge /
elevated ways = the deck heights sim/roads_build.py solves for its bridge tiles (its own cache busan_roads.json, read
only; same graph -> the cars sit on the drawn decks, both 광안대교 levels included).
Lanes: two-way roads = one lane each side (motorway / trunk / primary: 2 a side), right-hand traffic, 3.3 m lanes;
one-way roads as tagged. Density / speed by class (CLASS below, 추정 for daytime Busan, not measured).
Deterministic: every random draw comes from life_common.rng(<name>) - the same build gives the same file.
Run with `python -I` (the input is a download): user site-packages are added back; no code is read from the data folder.
"""
import json, math, os, sys, time, site
if sys.flags.isolated:
    site.addsitedir(site.getusersitepackages())
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import numpy as np                                        # noqa: E402
import life_common as LC                                  # noqa: E402

OSM_DIR = os.environ.get("GYROSIM_OSM", r"C:\GyroSimTiles\osm")
OSM_FILE = os.path.join(OSM_DIR, "busan_traffic.json")
BOX = (34.96, 128.75, 35.40, 129.33)                      # S W N E = roads_build / terrain_dem.HIRES busan box (fetch)
# cars only in the city core (S W N E): 사하 / 사상 / 서면 / 동래 / 해운대 / 광안 / 남포 / 영도 / 북항 - outside it the roads stay empty
CORE = tuple(float(x) for x in os.environ.get("GYROSIM_TRAFFIC_BOX", "35.03,128.93,35.27,129.215").split(","))
SIMPLIFY = 0.30                                           # m, Douglas-Peucker tolerance (3D) before the pieces are cut
OVERPASS = os.environ.get("GYROSIM_OVERPASS", "https://overpass-api.de/api/interpreter")
UA = "gyro-sim-chair traffic_build.py (personal flight sim; one request per manual run)"
# class: (lanes drawn per direction on a two-way road, car spacing per lane m, speed m/s, bus share, truck share)
# spacing / speed = 추정 daytime flow (moving traffic ~ 25-60 m gap in a lane), kept sparse enough for the GPU budget
# 11-10 round 2: denser on the arterials / bridges (first pass looked sparse from the air): 28-30 m per lane on
# motorway / trunk / primary (busy daytime flow, 추정), 42 m secondary
CLASS = dict(motorway=(2, 28.0, 20.0, 0.04, 0.22), trunk=(2, 28.0, 16.0, 0.05, 0.15), primary=(2, 30.0, 12.0, 0.10, 0.08),
             secondary=(1, 42.0, 11.0, 0.08, 0.06), tertiary=(1, 70.0, 10.0, 0.04, 0.05),
             motorway_link=(1, 50.0, 14.0, 0.02, 0.15), trunk_link=(1, 50.0, 12.0, 0.03, 0.10), primary_link=(1, 55.0, 11.0, 0.05, 0.05),
             secondary_link=(1, 90.0, 10.0, 0.03, 0.04), tertiary_link=(1, 110.0, 9.0, 0.02, 0.04))
LANE_M = 3.3
STEP = 25.0                                               # densify ground ways (terrain following), m
PIECE = 150.0                                             # longest straight piece, m (= the vehicle mesh's +X bounds extension)
LIFT = 0.10                                               # m above the terrain / deck


def query():
    s, w, n, e = BOX
    return ('[out:json][timeout:300];\nway["highway"~"^(motorway|trunk|primary|secondary|tertiary)(_link)?$"](%g,%g,%g,%g);\n'
            "out body;\n>;\nout skel qt;\n") % (s, w, n, e)


def fetch():
    import urllib.request, urllib.parse
    os.makedirs(OSM_DIR, exist_ok=True)
    q = query()
    t0 = time.time()
    req = urllib.request.Request(OVERPASS, data=urllib.parse.urlencode({"data": q}).encode(), headers={"User-Agent": UA})
    b = urllib.request.urlopen(req, timeout=400).read()
    d = json.loads(b)
    tmp = OSM_FILE + ".part"
    with open(tmp, "wb") as f:
        f.write(b)
    os.replace(tmp, OSM_FILE)
    man = dict(made=time.strftime("%Y-%m-%d %H:%M:%S"), url=OVERPASS, query=q, bytes=len(b), seconds=round(time.time() - t0, 1),
               osm_base=d.get("osm3s", {}).get("timestamp_osm_base"), licence="ODbL, (c) OpenStreetMap contributors", elements=len(d["elements"]))
    with open(OSM_FILE[:-5] + "_manifest.json", "w", encoding="utf-8") as f:
        json.dump(man, f, indent=1, ensure_ascii=False)
    print("fetched %d elements, %.1f MB, %.0f s -> %s" % (man["elements"], len(b) / 1e6, man["seconds"], OSM_FILE))


def _int(v, d=None):
    try:
        return int(str(v).split(";")[0].strip())
    except (TypeError, ValueError):
        return d


def bridge_heights():
    """roads_build's solved deck heights: {osm way id: (lat (n), lon (n), h MSL (n))} along its densified graph."""
    import roads_build as R
    import terrain_dem as T
    import buildings_build as B
    nodes, elev, ground, _ = R.load()
    dem = T.Dem()
    G = R.Graph(nodes, elev, ground)
    extra = {}
    if R.SIG:
        R.stack_double_deck(G)
        extra = R.gwangan_zones(G)
    h = R.solve_heights(G, dem, B.mesh_height, extra)[0]
    out = {}
    for wd in G.ways:
        ii = np.array(wd["idx"])
        la, lo = R.latlon(G.px[ii], G.py[ii])
        out[wd["w"]["id"]] = (np.asarray(la), np.asarray(lo), np.asarray(h[ii], float))
    return out, dem


def ground_msl(dem, la, lo):
    """rendered terrain height m MSL: the terrain mesh (buildings_build.mesh_height), and inside the coast band the coast-aware
    tiles swapped in 11-10 (sim/coast_build.rendered_msl: sea walls / beaches near the OSM coastline)."""
    import buildings_build as B
    h = B.mesh_height(dem, la, lo)
    try:
        import coast_build as CB
        sd, _ = CB.field_at(la, lo)
        near = sd < 1e4                                       # whole Busan box (coast tiles re-encoded at levels 13-16 everywhere there)
        if np.any(near):
            h = np.where(near, CB.rendered_msl(dem, la, lo), h)
    except Exception as e:                                   # no coast field built: plain mesh
        print("coast field not used:", e)
    return h


def offset_line(E, N, d):
    """polyline (east, north) offset d m to the RIGHT of its direction (miter, clamped)."""
    P = np.stack((E, N), 1)
    t = np.diff(P, axis=0)
    t /= np.maximum(np.linalg.norm(t, axis=1, keepdims=True), 1e-9)
    nr = np.stack((t[:, 1], -t[:, 0]), 1)                     # right normal of each segment (east, north)
    nv = np.zeros_like(P)
    nv[0], nv[-1] = nr[0], nr[-1]
    if len(nr) > 1:
        m = nr[:-1] + nr[1:]
        m /= np.maximum(np.linalg.norm(m, axis=1, keepdims=True), 1e-9)
        cos = np.maximum((m * nr[1:]).sum(1), 0.5)
        nv[1:-1] = m / cos[:, None]
    Q = P + nv * d
    return Q[:, 0], Q[:, 1]


def simplify(P, tol):
    """Douglas-Peucker on a 3D polyline (n, 3) -> kept points."""
    keep = np.zeros(len(P), bool)
    keep[0] = keep[-1] = True
    st = [(0, len(P) - 1)]
    while st:
        a, b = st.pop()
        if b <= a + 1:
            continue
        ab = P[b] - P[a]
        L2 = float(ab @ ab)
        q = P[a + 1:b] - P[a]
        t = np.clip((q @ ab) / max(L2, 1e-9), 0, 1)
        d = np.linalg.norm(q - t[:, None] * ab, axis=1)
        k = int(np.argmax(d))
        if d[k] > tol:
            m = a + 1 + k
            keep[m] = True
            st += [(a, m), (m, b)]
    return P[keep]


def densify(E, N, H, step):
    out_e, out_n, out_h = [E[0]], [N[0]], [np.nan if H is None else H[0]]
    for k in range(1, len(E)):
        L = math.hypot(E[k] - E[k - 1], N[k] - N[k - 1])
        m = max(1, int(math.ceil(L / step)))
        for j in range(1, m + 1):
            f = j / m
            out_e.append(E[k - 1] + (E[k] - E[k - 1]) * f)
            out_n.append(N[k - 1] + (N[k] - N[k - 1]) * f)
            out_h.append(np.nan if H is None else H[k - 1] + (H[k] - H[k - 1]) * f)
    return np.array(out_e), np.array(out_n), np.array(out_h)


def build():
    import terrain_dem as T
    import buildings_build as B
    t0 = time.time()
    d = json.load(open(OSM_FILE, encoding="utf-8"))
    osm_base = d.get("osm3s", {}).get("timestamp_osm_base")
    nodes = {e["id"]: (e["lat"], e["lon"]) for e in d["elements"] if e["type"] == "node"}
    ways = [e for e in d["elements"] if e["type"] == "way" and len(e.get("nodes", ())) >= 2]
    print("osm: %d ways, %d nodes (base %s)" % (len(ways), len(nodes), osm_base), flush=True)
    bh, dem = bridge_heights()
    print("bridge decks from roads_build: %d ways, %.0f s" % (len(bh), time.time() - t0), flush=True)
    lanes, segs = [], []                                     # lanes: (class, E, N, H MSL (nan = ground), lane key)
    stat = dict(ways=0, tunnels=0, bridge_ways=0, bridge_missing=0, km=0.0)
    for w in ways:
        t = w.get("tags", {})
        hw = t.get("highway")
        if hw not in CLASS or any(n not in nodes for n in w["nodes"]):
            continue
        c0 = nodes[w["nodes"][len(w["nodes"]) // 2]]
        if not (CORE[0] <= c0[0] <= CORE[2] and CORE[1] <= c0[1] <= CORE[3]):
            continue
        if t.get("tunnel", "no") not in ("no", "") or t.get("covered", "no") == "yes" or t.get("construction") or t.get("access") in ("no", "private"):
            stat["tunnels"] += 1
            continue
        br = t.get("bridge", "no") not in ("no", "") or _int(t.get("layer"), 0) >= 1
        if br and w["id"] in bh:
            la, lo, hm = bh[w["id"]]
            E0, N0 = LC.en(la, lo)
            Hm = hm
            stat["bridge_ways"] += 1
        else:
            if br:                                           # a bridge roads_build skipped (residential / footway class mix-ups): ground is wrong
                stat["bridge_missing"] += 1
                continue
            la = np.array([nodes[n][0] for n in w["nodes"]])
            lo = np.array([nodes[n][1] for n in w["nodes"]])
            E0, N0 = LC.en(la, lo)
            Hm = None
        oneway = t.get("oneway", "no")
        if hw in ("motorway",) and oneway == "no":
            oneway = "yes"
        two = oneway not in ("yes", "1", "-1", "true")
        nper = CLASS[hw][0]
        lt = _int(t.get("lanes"))
        if lt:
            nper = max(1, min(nper, lt // 2 if two else lt))
        if not two:
            nper = min(nper, 2)
        H0 = np.full(len(E0), np.nan) if Hm is None else np.asarray(Hm, float)
        nd = (w["nodes"][0], w["nodes"][-1])
        if oneway == "-1":
            E0, N0, H0, nd = E0[::-1], N0[::-1], H0[::-1], nd[::-1]
        L = float(np.hypot(np.diff(E0), np.diff(N0)).sum())
        stat["ways"] += 1
        stat["km"] += L / 1000.0
        segs.append(dict(id=w["id"], key=(hw, two, nper), E=np.asarray(E0, float), N=np.asarray(N0, float), H=H0, nd=list(nd)))
    # join ways end to end into long chains (same class / direction rule / lanes, a node shared by exactly two way ends and
    # no other way end): one lattice per chain, so cars run on through OSM way splits instead of shrinking out there
    ends = {}
    for i, s in enumerate(segs):
        for k in (0, 1):
            ends.setdefault(s["nd"][k], []).append((i, k))
    used = [False] * len(segs)

    def partner(node, i):
        e = ends.get(node, [])
        if len(e) != 2:
            return None
        j, k = e[0] if e[1][0] == i else e[1]
        if j == i or used[j] or segs[j]["key"] != segs[i]["key"]:
            return None
        return j, k
    chains = []
    for i0, s0 in enumerate(segs):
        if used[i0]:
            continue
        used[i0] = True
        two = s0["key"][1]
        parts = [(i0, False)]
        cur, node = i0, s0["nd"][1]                       # forward
        while True:
            p = partner(node, cur)
            if p is None:
                break
            j, k = p
            if k == 1 and not two:                        # one-way: must enter at its start
                break
            used[j] = True
            rev = k == 1
            parts.append((j, rev))
            node = segs[j]["nd"][0 if rev else 1]
            cur = j
        cur, node = i0, s0["nd"][0]                       # backward
        while True:
            p = partner(node, cur)
            if p is None:
                break
            j, k = p
            if k == 0 and not two:                        # one-way: must leave at its end
                break
            used[j] = True
            rev = k == 0
            parts.insert(0, (j, rev))
            node = segs[j]["nd"][1 if rev else 0]
            cur = j
        E, N, H = [], [], []
        for j, rev in parts:
            s = segs[j]
            e_, n_, h_ = (s["E"][::-1], s["N"][::-1], s["H"][::-1]) if rev else (s["E"], s["N"], s["H"])
            if E:
                e_, n_, h_ = e_[1:], n_[1:], h_[1:]
            E.append(e_); N.append(n_); H.append(h_)
        chains.append((s0["key"], np.concatenate(E), np.concatenate(N), np.concatenate(H), "%d_%d" % (segs[parts[0][0]]["id"], len(parts))))
    stat["chains"] = len(chains)
    for (hw, two, nper), E0, N0, H0, cid in chains:
        if len(E0) < 2:
            continue
        for sgn in ([1, -1] if two else [1]):
            E1, N1, H1 = (E0, N0, H0) if sgn > 0 else (E0[::-1], N0[::-1], H0[::-1])
            for li in range(nper):
                off = (li + 0.5) * LANE_M if two else (li + 0.5 - nper / 2.0) * LANE_M
                Eo, No = offset_line(E1, N1, off) if off else (E1, N1)
                lanes.append((hw, Eo, No, H1, "%s_%d_%d" % (cid, sgn, li)))
    print("lanes %d from %d ways in %d chains (%.0f km of road), %d tunnels/private skipped, %d bridge ways (%d not in roads_build, skipped)" % (
        len(lanes), stat["ways"], stat["chains"], stat["km"], stat["tunnels"], stat["bridge_ways"], stat["bridge_missing"]), flush=True)
    recs = []
    lane_km, at_once = 0.0, 0.0
    cls_ix = {k: i for i, k in enumerate(CLASS)}
    for hw, Eo, No, H1, key in lanes:
        Ed, Nd, Hd = densify(Eo, No, H1, STEP)              # nan (ground) stays nan between ground points
        la, lo = LC.latlon(Ed, Nd)
        g_ = np.isnan(Hd)
        if g_.any():
            Hd[g_] = ground_msl(dem, la[g_], lo[g_])
        he = Hd + dem.geoid_n(la, lo) + LIFT
        P = simplify(LC.local(la, lo, he), SIMPLIFY)
        lk = float(np.linalg.norm(np.diff(P, axis=0), axis=1).sum())
        nper, D, v, pb, pt = CLASS[hw]
        g = LC.rng("lane" + key)
        sp = v * float(g.uniform(0.85, 1.12))
        R = LC.lanes_to_records(P, False, sp, D, g, PIECE)
        if not len(R):
            continue
        # one mesh with every vehicle body (SM_LifeVehicle): the material keeps the body hash(lane seed, car number)
        # picks (bus / truck shares by road class = the integer part of the seed) and collapses the others
        R[:, 10] += cls_ix[hw]
        recs.append(R)
        lane_km += lk / 1000.0
        at_once += lk / D
    R = np.concatenate(recs) if recs else np.zeros((0, LC.REC), np.float32)
    groups = [("vehicle", "SM_LifeVehicle", "road", R)]
    n = len(R)
    meta = dict(input=dict(osm=OSM_FILE, osm_base=osm_base, roads_build_cache=os.path.join(OSM_DIR, "busan_roads.json")),
                seconds=round(time.time() - t0), stat=stat, lanes=len(lanes), lane_km=round(lane_km, 1), instances=n,
                vehicles_at_once=round(at_once), class_index=list(CLASS),
                rules=dict(CLASS=CLASS, LANE_M=LANE_M, STEP=STEP, PIECE=PIECE, LIFT=LIFT),
                licence="road geometry: OpenStreetMap contributors (ODbL)")
    p = LC.write("traffic", groups, meta)
    print("done: %d instances, %.0f lane-km, %d vehicles at once, %.0f s -> %s" % (n, lane_km, meta["vehicles_at_once"], time.time() - t0, p), flush=True)


if __name__ == "__main__":
    if "--fetch" in sys.argv:
        fetch()
    if "--build" in sys.argv:
        build()
