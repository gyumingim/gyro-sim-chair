"""Look of the local 3D buildings (CesiumBuildings tileset, vworld mode): the procedural facade material
/Game/Buildings/M_GyroBuilding (Scripts/buildings_material.py + buildings_facade.hlsl). Called by sim_client
_local_buildings before refresh_tileset. GYROSIM_BLDG_MAT=0 keeps Cesium's stock material (A/B checks).
The facade styles need tiles built after 11-09 (buildings_build.py --tiles); older tiles render as before."""
import os
import unreal

MAT = "/Game/Buildings/M_GyroBuilding"


def apply(tileset, log=unreal.log):
    if tileset is None:
        return False
    want = os.environ.get("GYROSIM_BLDG_MAT", "1") != "0"
    m = None
    if want:                                    # load_asset, not does_asset_exist: the asset registry may still be
        try:                                    # scanning right after editor start (-GyroSimPlay autoplay)
            m = unreal.load_asset(MAT)
        except Exception:
            m = None
    try:
        tileset.set_editor_property("material", m)
        log("[buildings_look] material %s" % (MAT if m else "Cesium default"))
        return m is not None
    except Exception as e:
        log("[buildings_look] material failed %r" % (e,))
        return False
