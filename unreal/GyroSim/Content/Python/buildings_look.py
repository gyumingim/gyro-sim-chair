"""Look of the local 3D buildings (CesiumBuildings tileset, vworld mode): the procedural facade material
/Game/Buildings/M_GyroBuilding (Scripts/buildings_material.py + buildings_facade.hlsl). Called by sim_client
_local_buildings before refresh_tileset. GYROSIM_BLDG_MAT=0 keeps Cesium's stock material (A/B checks).
The facade styles need tiles built after 11-09 (buildings_build.py --tiles); older tiles render as before.
Art pass 11-10 (material parameter ArtFix, default 1 in the asset): per-building wall paint palette, a bit darker / less
warm walls, brand stripes only in the top floors and muted. GYROSIM_BLDG_ART=0 = the look before (dynamic instance with
ArtFix 0; Cesium copies its parameter values onto every tile's material).
v3 (11-10 evening): building-type detail (gables with dong numbers, stair cores, AC units / louvres, shops, pilotis,
brick / stone, rooftop tanks / machine rooms / laundry, sharpened roof photo). GYROSIM_BLDG_V3=0 = the look before v3:
material M_GyroBuilding_v2 and, when it exists, the tile folder kept at the v3 swap (buildings/tiles_prev_<date>_v3, newest).
GYROSIM_BLDG_TILES_DIR = a tile folder name under C:/GyroSimTiles/buildings (or a full path) to load instead of the URL the
caller set (offscreen before / after shots of a tiles_new build).
Round 2 (11-10 night): roofs procedural by default (photo = low-frequency tint), GYROSIM_BLDG_ROOF_PHOTO=1 = the photo roofs.
Backlit v2 (11-11, docs/backlit-busan.md): glass-tower panes go dark with sparse glints when the camera looks toward a low
sun (material parameters BacklitV2 / BkMetal / BkDark / BkRough / BkKeep); GYROSIM_BACKLIT_V2=0 = the look before.
Grounded day (11-11, docs/grounded-day-busan.md): canyon / foot occlusion of the walls from the building occlusion field
(material parameters GdOn / GdAO / GdBase ..); GYROSIM_GROUNDED_DAY=0 = the look before (GdOn 0)."""
import glob, os
import unreal

MAT = "/Game/Buildings/M_GyroBuilding"
MAT_V2 = "/Game/Buildings/M_GyroBuilding_v2"
ROOT = r"C:/GyroSimTiles/buildings"


def _tiles_url():
    d = os.environ.get("GYROSIM_BLDG_TILES_DIR", "")
    if not d and os.environ.get("GYROSIM_BLDG_V3", "1") == "0":
        prev = sorted(glob.glob(ROOT + "/tiles_prev_*_v3/tileset.json"))
        d = os.path.dirname(prev[-1]) if prev else ""
    if not d:
        return None
    if not os.path.isabs(d):
        d = ROOT + "/" + d
    f = os.path.join(d, "tileset.json")
    return "file:///" + f.replace("\\", "/") if os.path.isfile(f) else None


def apply(tileset, log=unreal.log):
    if tileset is None:
        return False
    want = os.environ.get("GYROSIM_BLDG_MAT", "1") != "0"
    v3 = os.environ.get("GYROSIM_BLDG_V3", "1") != "0"
    url = _tiles_url()
    if url:
        try:
            tileset.set_editor_property("tileset_source", unreal.TilesetSource.FROM_URL)
            tileset.set_editor_property("url", url)
            log("[buildings_look] tiles %s" % url)
        except Exception as e:
            log("[buildings_look] tiles url failed %r" % (e,))
    m = None
    if want:                                    # load_asset, not does_asset_exist: the asset registry may still be
        try:                                    # scanning right after editor start (-GyroSimPlay autoplay)
            m = unreal.load_asset(MAT if v3 else MAT_V2)
            if m is None and not v3:
                m = unreal.load_asset(MAT)
        except Exception:
            m = None
    art_off = os.environ.get("GYROSIM_BLDG_ART", "1") == "0"
    roof_photo = os.environ.get("GYROSIM_BLDG_ROOF_PHOTO", "0") == "1"      # round 2: 1 = photo roofs (default procedural)
    backlit_off = os.environ.get("GYROSIM_BACKLIT_V2", "1") == "0"            # 11-11: dark backlit glass off (look before)
    gd_off = os.environ.get("GYROSIM_GROUNDED_DAY", "1") == "0"               # 11-11: grounded day occlusion off (look before)
    try:                                                                      # 11-12: building contact (facade foot band)
        import atmos_look
        bc_on = atmos_look.bldg_contact_on()
    except Exception:
        bc_on = False
    if m is not None and (art_off or roof_photo or backlit_off or gd_off or bc_on):
        try:
            m = unreal.MaterialLibrary.create_dynamic_material_instance(tileset.get_world(), m)
            if art_off:
                m.set_scalar_parameter_value("ArtFix", 0.0)
            if roof_photo:
                m.set_scalar_parameter_value("RoofPhoto", 1.0)
            if backlit_off:
                m.set_scalar_parameter_value("BacklitV2", 0.0)
            if gd_off:
                m.set_scalar_parameter_value("GdOn", 0.0)
            if bc_on:
                m.set_scalar_parameter_value("BcOn", 1.0)
                for k, v in atmos_look.BC_BLDG.items():
                    m.set_scalar_parameter_value(k, float(v))
        except Exception as e:
            log("[buildings_look] parameter instance failed %r" % (e,))
    try:
        tileset.set_editor_property("material", m)
        log("[buildings_look] material %s art %s v3 %s" % (m.get_name() if m else "Cesium default", os.environ.get("GYROSIM_BLDG_ART", "1"), v3))
        return m is not None
    except Exception as e:
        log("[buildings_look] material failed %r" % (e,))
        return False
