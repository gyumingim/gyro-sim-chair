"""Gate test tile for the leaf-card trees (sim/veg_cards.py): ONE small Cesium 3D tile with instanced (EXT_mesh_gpu_instancing)
alpha-MASK card trees on the real tree positions around the 'hwangryeong_low' shot target (황령산 west slope), so an offscreen
UE render (Scripts/trees_shots.py, GYROSIM_TREES_TILES = this folder, stock Cesium material) shows whether Cesium for Unreal
draws the card holes. Nothing in the game changes: the normal tiles stay where they are.

    python -I sim/veg_cards_gate.py OUTDIR [radius_m]      -> OUTDIR/tileset.json + OUTDIR/t.glb + gate.json
"""
import io, json, math, os, sys, time, site
if sys.flags.isolated:
    site.addsitedir(site.getusersitepackages())
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import numpy as np                                        # noqa: E402
import veg_build as V                                     # noqa: E402
import veg_cards as VC                                    # noqa: E402

TARGET = (35.1560, 129.0800)                              # trees_shots.py VIEWS 'hwangryeong_low' target


def main(out, radius=250.0):
    import buildings_build as B
    os.makedirs(out, exist_ok=True)
    i, j = int(math.floor(TARGET[0] / V.DLA)), int(math.floor(TARGET[1] / V.DLO))
    z = np.load(os.path.join(V.WORK, "b_%d_%d.npz" % (i, j)))
    lat, lon = z["lat"], z["lon"]
    d = np.hypot((lat - TARGET[0]) * 111000.0, (lon - TARGET[1]) * 111000.0 * math.cos(math.radians(TARGET[0])))
    m = d < radius
    lat, lon, base, h = lat[m].astype(np.float64), lon[m].astype(np.float64), z["base"][m].astype(np.float64), z["h"][m].astype(np.float64)
    yaw = z["yaw"][m].astype(np.float64) * 2 * math.pi
    n = len(lat)
    rg = np.random.default_rng(3)
    is_pine = rg.uniform(size=n) < 0.7
    center = (float(lat.mean()), float(lon.mean()))
    R = B.enu_rot(*center)
    C0 = B.ecef(np.array(center[0]), np.array(center[1]), np.array(0.0)).reshape(3)
    E = (B.ecef(lat, lon, base) - C0) @ R
    S = np.array([[1, 0, 0], [0, 0, 1], [0, -1, 0]], np.float64)
    Tl = E @ S.T
    Rq = np.stack((np.zeros_like(yaw), np.sin(yaw / 2), np.zeros_like(yaw), np.cos(yaw / 2)), 1)
    Mx = np.eye(4); Mx[:3, :3] = S @ R @ S.T; Mx[:3, 3] = S @ C0          # same transform as veg_v2.tile_glb2
    img = VC.make_atlas(); bb = io.BytesIO(); img.save(bb, "PNG")
    protos = [("pine_%02d" % v,) + VC.pine(v) for v in range(10)] + [("oak_%02d" % v,) + VC.oak(v) for v in range(5)]
    pick = np.where(is_pine, rg.integers(0, 10, n), 10 + rg.integers(0, 5, n))
    items, tris = [], 0
    for k, (name, T, info) in enumerate(protos):
        sel = pick == k
        if not sel.any():
            continue
        s = (h[sel] + V.SINK) / info["H"]
        items.append((name, T, (Tl[sel], Rq[sel], np.stack((s, s, s), 1))))
        tris += T.ntri * int(sel.sum())
    glb = VC.glb_bytes(items, bb.getvalue(), Mx)
    open(os.path.join(out, "t.glb"), "wb").write(glb)
    region = [math.radians(lon.min() - 1e-4), math.radians(lat.min() - 1e-4), math.radians(lon.max() + 1e-4),
              math.radians(lat.max() + 1e-4), float(base.min()) - 5, float((base + h).max()) + 10]
    ts = dict(asset=dict(version="1.1", generator="gyro-sim-chair sim/veg_cards_gate.py"), geometricError=1000.0,
              root=dict(boundingVolume=dict(region=region), geometricError=0.0, refine="REPLACE", content=dict(uri="t.glb")))
    json.dump(ts, open(os.path.join(out, "tileset.json"), "w"))
    meta = dict(made=time.strftime("%Y-%m-%dT%H:%M:%S"), trees=int(n), pine=int(is_pine.sum()), triangles=int(tris), bytes=len(glb),
                center=center, radius_m=radius, src=os.path.join(V.WORK, "b_%d_%d.npz" % (i, j)))
    json.dump(meta, open(os.path.join(out, "gate.json"), "w"), indent=1)
    print(meta)


if __name__ == "__main__":
    main(sys.argv[1], float(sys.argv[2]) if len(sys.argv) > 2 else 250.0)
