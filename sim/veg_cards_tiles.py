"""Leaf-card tree tiles (11-11, user pick (c) 'spread big cards'): the veg_v2 tile build (same 19.9 M trees, same blocks,
same placement / colour bins) with the pine / coast pine / broadleaf prototypes replaced by sim/veg_cards.py card trees:
  near (C tiles, < ~1 km): spread big-card trees, ~370-600 triangles (front + back cards + trunk)
  far  (B tiles, 1-3.9 km): 8 enlarged cards of the same tree, 32 triangles (old far shapes 24-32)
  shrubs / rocks: the old veg_v2 shapes (UV = -1 -> the material draws them opaque).
Vertex colour = the veg_v2 encoding (sRGB tint, A = 64 kind + ao); TEXCOORD_0 = leaf atlas uv (-1 = no texture).
The atlas is NOT in the tiles: the material /Game/Trees/M_GyroTreeCard (Scripts/trees_material.py build_card) samples the
texture asset T_GyroTreeCards imported from C:/GyroSimTiles/veg/cards_atlas.png (written here). Each glb carries a 4x4
white base colour texture only so Cesium loads TEXCOORD_0 into UV channel 0.

    python -I sim/veg_cards_tiles.py         -> C:/GyroSimTiles/veg/tiles_cards (tmp -> swap, keeps tiles_cards_prev)
Run holding C:/GyroSimTiles/ue_offscreen.lock (big CPU job; <= half the cores, below-normal priority); the swap is skipped while any UnrealEditor runs.
"""
import io, json, math, os, struct, sys, site
if sys.flags.isolated:
    site.addsitedir(site.getusersitepackages())
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
os.environ.setdefault("GYROSIM_VEG_TILES2", r"C:\GyroSimTiles\veg\tiles_cards")
import numpy as np                                        # noqa: E402
import veg_build as V                                     # noqa: E402
import veg_v2 as V2                                       # noqa: E402
import veg_cards as VC                                    # noqa: E402

ATLAS_OUT = r"C:\GyroSimTiles\veg\cards_atlas.png"
VC.CARD_SCALE, VC.CLUMP_MUL, VC.CARD_MUL, VC.SPREAD = VC.VARIANTS["spread"]
# (prototype slot, colour bin) -> card tree: pine 0/1 umbrella, pine3 = young dense-stand (narrow), bpine (coast) umbrella
CARD_OF = {(0, 0): ("pine", 0), (0, 1): ("pine", 1), (1, 0): ("pine", 2), (1, 1): ("pine", 3), (2, 0): ("pine", 8),
           (2, 1): ("pine", 9), (3, 0): ("pine", 4), (3, 1): ("pine", 5), (4, 0): ("oak", 0), (4, 1): ("oak", 1),
           (5, 0): ("oak", 2), (5, 1): ("oak", 3), (6, 0): ("oak", 4), (6, 1): ("oak", 0), (7, 0): ("oak", 1), (7, 1): ("oak", 2)}
KIND_OF = dict(pine=1, oak=2)
_CALLS = {}
_ORIG_BUILD = V2.build_proto


class _Arr:
    def __init__(self, arr):
        self.a = arr

    def arrays(self, tint, trunk):
        return self.a(tint, trunk)


def card_proto(pid, far):
    """replaces veg_v2.build_proto inside tiles2: tiles2 calls it once per colour bin in bin order (counted here)."""
    k = (pid, far)
    b = _CALLS.get(k, 0); _CALLS[k] = b + 1
    b %= V2.NBIN
    if (pid, b) not in CARD_OF:
        m = _ORIG_BUILD(pid, far)

        def old(tint, trunk):
            P, Nn, Cu, I = m.arrays(tint, trunk)
            return P, Nn, Cu, I, np.full((len(P), 2), -1.0, np.float32)
        return _Arr(old)
    sp, var = CARD_OF[(pid, b)]
    T, info = (VC.pine if sp == "pine" else VC.oak)(var)

    def cards(tint, trunk):
        near = VC.unit_arrays(T, KIND_OF[sp], tint)
        if not far:
            return near[:5]
        return VC.unit_arrays(VC.far_tree(T, 8, seed=var), KIND_OF[sp], tint, foliage_only=True, extent=near[5])[:5]
    return _Arr(cards)


def _tiny_png():
    from PIL import Image
    bb = io.BytesIO(); Image.new("RGBA", (4, 4), (255, 255, 255, 255)).save(bb, "PNG")
    return bb.getvalue()


TINY = None


def glb_instanced_uv(protos, groups, Mx):
    """veg_build.glb_instanced + TEXCOORD_0 (protos: (P, N, C, I, UV))."""
    global TINY
    if TINY is None:
        TINY = _tiny_png()
    blob = bytearray(); views, accs = [], []

    def view(bb, target=None):
        blob.extend(b"\0" * ((-len(blob)) % 4))
        v = dict(buffer=0, byteOffset=len(blob), byteLength=len(bb))
        if target:
            v["target"] = target
        blob.extend(bb); views.append(v)
        return len(views) - 1

    def acc(arr, typ, ct=5126, target=None, norm=False, mm=False):
        a = dict(bufferView=view(arr.tobytes(), target), componentType=ct, count=len(arr), type=typ)
        if norm:
            a["normalized"] = True
        if mm:
            a["min"], a["max"] = arr.min(0).tolist(), arr.max(0).tolist()
        accs.append(a)
        return len(accs) - 1
    meshes, pm = [], {}
    for k in sorted({g[0] for g in groups}):
        P, Nn, C, I, UV = protos[k]
        attrs = dict(POSITION=acc(P, "VEC3", target=34962, mm=True), NORMAL=acc(Nn, "VEC3", target=34962),
                     COLOR_0=acc(C, "VEC4", ct=5121, target=34962, norm=True), TEXCOORD_0=acc(UV, "VEC2", target=34962))
        pm[k] = len(meshes)
        meshes.append(dict(primitives=[dict(attributes=attrs, indices=acc(I, "SCALAR", ct=5125, target=34963), material=0, mode=4)]))
    nodes = [dict(matrix=[float(v) for v in Mx.T.reshape(-1)], children=[])]
    for k, T_, R_, S_ in groups:
        ext = dict(EXT_mesh_gpu_instancing=dict(attributes=dict(TRANSLATION=acc(T_.astype(np.float32), "VEC3"),
                                                                ROTATION=acc(R_.astype(np.float32), "VEC4"),
                                                                SCALE=acc(S_.astype(np.float32), "VEC3"))))
        nodes[0]["children"].append(len(nodes))
        nodes.append(dict(mesh=pm[k], extensions=ext))
    img = view(TINY)
    blob.extend(b"\0" * ((-len(blob)) % 4))
    gl = dict(asset=dict(version="2.0", generator="gyro-sim-chair veg_cards_tiles.py"), extensionsUsed=["EXT_mesh_gpu_instancing"],
              extensionsRequired=["EXT_mesh_gpu_instancing"], scene=0, scenes=[dict(nodes=[0])], nodes=nodes, meshes=meshes,
              materials=[dict(name="cards", pbrMetallicRoughness=dict(baseColorTexture=dict(index=0, texCoord=0), baseColorFactor=[1, 1, 1, 1],
                                                                     metallicFactor=0.0, roughnessFactor=0.9))],
              textures=[dict(source=0, sampler=0)], images=[dict(bufferView=img, mimeType="image/png")],
              samplers=[dict(magFilter=9728, minFilter=9728)],
              accessors=accs, bufferViews=views, buffers=[dict(byteLength=len(blob))])
    js = json.dumps(gl, separators=(",", ":")).encode(); js += b" " * ((-len(js)) % 4)
    total = 12 + 8 + len(js) + 8 + len(blob)
    return struct.pack("<III", 0x46546C67, 2, total) + struct.pack("<II", len(js), 0x4E4F534A) + js + struct.pack("<II", len(blob), 0x004E4942) + bytes(blob)


if __name__ == "__main__":
    # power rule (PSU tripped twice 11-11): below-normal priority (pool workers inherit it), at most half the cores
    import power_rule                                   # typed SetPriorityClass + read back (sim/power_rule.py)
    low = power_rule.below_normal()
    os.environ["GYROSIM_VEG_PROCS"] = str(min(int(os.environ.get("GYROSIM_VEG_PROCS", "6")), max(1, (os.cpu_count() or 2) // 2)))
    print("procs", os.environ["GYROSIM_VEG_PROCS"], "priority", "below-normal" if low else "NOT lowered (normal)", flush=True)
    img = VC.make_atlas()
    img.save(ATLAS_OUT)
    a = np.asarray(img).astype(np.float64) / 255.0
    lin = np.where(a[..., :3] <= 0.04045, a[..., :3] / 12.92, ((a[..., :3] + 0.055) / 1.055) ** 2.4)
    m = a[..., 3] > 0.5
    lum = lin[m] @ np.array([0.2126, 0.7152, 0.0722])
    print("atlas", ATLAS_OUT, "opaque mean lum (linear) %.4f" % lum.mean(), "mean rgb", lin[m].mean(0).round(4).tolist(), flush=True)
    V2.build_proto = card_proto
    V.glb_instanced = glb_instanced_uv
    V2.tiles2(sys.argv[1:])
    bj = os.path.join(V2.TILES2, "build.json")
    if os.path.isfile(bj):
        d = json.load(open(bj)); d["cards"] = dict(variant="spread", card_of={"%d_%d" % k: "%s_%02d" % v for k, v in CARD_OF.items()},
                                                  atlas=ATLAS_OUT, atlas_lum=round(float(lum.mean()), 4))
        json.dump(d, open(bj, "w"), indent=1)
