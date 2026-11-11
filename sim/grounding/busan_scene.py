"""Building-grounding study (docs/research/building-grounding-study.md): scene description of one Busan spot for the
headless Blender renders (sim/grounding/render_study.py). Reads only local caches, writes one JSON (no imagery):

    python -I sim/grounding/busan_scene.py NAME LAT LON HALF_M OUT.json

  tiles   building glb paths (C:/GyroSimTiles/buildings/tiles) whose region overlaps the box + their node matrix
  frame   R (ECEF -> ENU columns) and C0 (ECEF of the centre at h = 0): Blender turns the glb ECEF frame into local ENU
  ground  n x n grid, ENU positions (rendered terrain mesh height + geoid, as buildings_lookdev.py) and UV into a mosaic
  mosaic  zoom, pixel box and the cached V-World tile paths. Blender reads the JPEGs read-only into memory; the mosaic
          is never written to disk (V-World data stays in its cache).
"""
import json, math, os, struct, sys, site, time
if sys.flags.isolated:
    site.addsitedir(site.getusersitepackages())
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import numpy as np                                        # noqa: E402
import buildings_build as B                               # noqa: E402
import buildings_tex as BT                                # noqa: E402
import terrain_dem as T                                   # noqa: E402

TILES = os.environ.get("GYROSIM_BUILDINGS_TILES", r"C:\GyroSimTiles\buildings\tiles")


def tiles_near(ts, lat, lon, half_m):
    out = []
    la, lo = math.radians(lat), math.radians(lon)
    dla, dlo = half_m / 6371000.0, half_m / (6371000.0 * math.cos(la))

    def walk(n):
        w, s, e, nn = n["boundingVolume"]["region"][:4]
        if e < lo - dlo or w > lo + dlo or nn < la - dla or s > la + dla:
            return
        if "content" in n:
            out.append(n["content"]["uri"])
        for c in n.get("children", []):
            walk(c)
    walk(ts["root"])
    return out


def node_matrix(path):
    d = open(path, "rb").read(65536 * 4)
    L, = struct.unpack("<I", d[12:16])
    j = json.loads(d[20:20 + L])
    return j["nodes"][j["scenes"][0]["nodes"][0]].get("matrix")


def main(name, lat, lon, half_m, out):
    ts = json.load(open(os.path.join(TILES, "tileset.json"), encoding="utf-8"))
    uris = tiles_near(ts, lat, lon, half_m)
    tiles = [dict(path=os.path.join(TILES, u), matrix=node_matrix(os.path.join(TILES, u))) for u in uris]
    R = B.enu_rot(lat, lon)
    C0 = B.ecef(np.array(lat), np.array(lon), np.array(0.0)).reshape(3)
    dem = T.Dem()
    n = 161
    g = half_m * 1.15
    dl, dn = g / T.M_LAT, g / (111320.0 * math.cos(math.radians(lat)))
    LA, LO = np.meshgrid(np.linspace(lat - dl, lat + dl, n), np.linspace(lon - dn, lon + dn, n), indexing="ij")
    h = B.mesh_height(dem, LA, LO) + dem.geoid_n(LA, LO)
    P = (B.ecef(LA, LO, h) - C0) @ R
    sat = BT.Sat()
    z = None
    for zz in (18, 17, 16):
        X, Y = sat.px(zz, LA, LO)
        x0, y0, x1, y1 = int(X.min()) - 1, int(Y.min()) - 1, int(X.max()) + 2, int(Y.max()) + 2
        if (x1 - x0) <= 8192 and sat.covered(zz, x0, y0, x1, y1):
            z = zz
            break
    if z is None:
        raise SystemExit("no full V-World cache cover at z16-18 for this box")
    paths = [[ty, tx, os.path.join(sat.root, str(z), str(ty), "%d.jpg" % tx)]
             for ty in range(y0 // 256, (y1 - 1) // 256 + 1) for tx in range(x0 // 256, (x1 - 1) // 256 + 1)]
    uv = np.stack(((X - x0) / (x1 - x0), 1.0 - (Y - y0) / (y1 - y0)), -1)        # Blender image v = 0 at the bottom
    sc = dict(name=name, made=time.strftime("%Y-%m-%d %H:%M:%S"), lat=lat, lon=lon, half_m=half_m,
              tileset=ts["asset"].get("tilesetVersion"), tiles=tiles, R=R.tolist(), C0=C0.tolist(),
              ground=dict(n=n, P=np.round(P, 3).reshape(-1).tolist(), uv=np.round(uv, 6).reshape(-1).tolist()),
              mosaic=dict(z=z, box=[x0, y0, x1, y1], tiles=paths),
              note="V-World tiles are read from the cache in memory only (preview); never copied")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(sc, f)
    print("tiles", len(tiles), "zoom", z, "mosaic px", x1 - x0, y1 - y0, "->", out)


if __name__ == "__main__":
    a = sys.argv[1:]
    main(a[0], float(a[1]), float(a[2]), float(a[3]), a[4])
