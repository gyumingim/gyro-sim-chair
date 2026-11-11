"""Triangles per tree of the old blob tiles (sim/veg_v2.py tiles_v2): parses a sample of near (c/) and far (b/) tile glbs
(EXT_mesh_gpu_instancing: triangles of each prototype x its instance count).
    python -I sim/impostor/blob_tris.py [n sample]
"""
import glob, json, os, random, struct, sys

ROOT = r"C:/GyroSimTiles/veg/tiles_v2"


def glb_stats(p):
    b = open(p, "rb").read()
    n = struct.unpack_from("<I", b, 12)[0]
    g = json.loads(b[20:20 + n])
    tris = inst = 0
    for nd in g.get("nodes", []):
        if "mesh" not in nd:
            continue
        ext = nd.get("extensions", {}).get("EXT_mesh_gpu_instancing")
        k = g["accessors"][list(ext["attributes"].values())[0]]["count"] if ext else 1
        t = 0
        for pr in g["meshes"][nd["mesh"]]["primitives"]:
            t += g["accessors"][pr["indices"]]["count"] // 3 if "indices" in pr else g["accessors"][pr["attributes"]["POSITION"]]["count"] // 3
        tris += t * k
        inst += k
    return tris, inst


if __name__ == "__main__":
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 300
    random.seed(1)
    for lev in ("c", "b"):
        fs = glob.glob(os.path.join(ROOT, lev, "*.glb"))
        T = I = 0
        for p in random.sample(fs, min(n, len(fs))):
            t, i = glb_stats(p)
            T += t; I += i
        print(lev, "files", len(fs), "sampled tris / instance %.1f" % (T / max(I, 1)), "instances", I)
