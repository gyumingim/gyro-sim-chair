"""Look of the local 3D buildings (CesiumBuildings tileset, vworld mode): the procedural facade material
/Game/Buildings/M_GyroBuilding (Scripts/buildings_material.py + buildings_facade.hlsl). Called by sim_client
_local_buildings before refresh_tileset. GYROSIM_BLDG_MAT=0 keeps Cesium's stock material (A/B checks).
The facade styles need tiles built after 11-09 (buildings_build.py --tiles); older tiles render as before.
Art pass 11-10 (material parameter ArtFix, default 1 in the asset): per-building wall paint palette, a bit darker / less
warm walls, brand stripes only in the top floors and muted. GYROSIM_BLDG_ART=0 = the look before (dynamic instance with
ArtFix 0; Cesium copies its parameter values onto every tile's material)."""
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
    if m is not None and os.environ.get("GYROSIM_BLDG_ART", "1") == "0":
        try:
            m = unreal.MaterialLibrary.create_dynamic_material_instance(tileset.get_world(), m)
            m.set_scalar_parameter_value("ArtFix", 0.0)
        except Exception as e:
            log("[buildings_look] art off failed %r" % (e,))
    try:
        tileset.set_editor_property("material", m)
        log("[buildings_look] material %s art %s" % (MAT if m else "Cesium default", os.environ.get("GYROSIM_BLDG_ART", "1")))
        return m is not None
    except Exception as e:
        log("[buildings_look] material failed %r" % (e,))
        return False
