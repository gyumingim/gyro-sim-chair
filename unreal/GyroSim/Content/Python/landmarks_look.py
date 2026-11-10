"""Busan landmark models (sim/landmarks/landmarks_build.py -> 3D Tiles on disk) for the vworld mode on the local terrain.
The map's 'CesiumLandmarks' tileset (Scripts/add_landmarks_actor.py, run once with the editor closed; off = no URL) is
pointed at file:///C:/GyroSimTiles/landmarks/tiles/tileset.json (GYROSIM_LANDMARK_TILES moves it). GYROSIM_LANDMARKS=0 = off.
Called by sim_client._vworld_ground after the roads. The GIS boxes of the same buildings are left out of the building
tiles through C:/GyroSimTiles/landmarks/exclude.json (sim/buildings_build.py --tiles).
Glass: /Game/Landmarks/MI_GyroLandmark (Scripts/landmarks_material.py + landmarks_glass.hlsl, 11-10): Cesium's glTF
material layers (base colour + metallic-roughness textures baked in the glb) and then reflective curtain-wall glass on the
glass-module pixels (dark body, ~10-20 % sky reflection, per-pane / per-floor variation and tilt, darker mullions).
GYROSIM_LM_GLASS=0 = Cesium's default material (the look before 11-10, A/B). Physics meshes on so the camera floor trace
stands on them like on the building tiles."""
import os
import unreal

TILES = os.environ.get("GYROSIM_LANDMARK_TILES", r"C:/GyroSimTiles/landmarks/tiles").replace("\\", "/")
TAG = "CesiumLandmarks"
SSE = 8.0
GLASS_MI = "/Game/Landmarks/MI_GyroLandmark"
# glass parameters (defaults of M_GyroLandmark, written into MI_GyroLandmark by Scripts/landmarks_material.py).
# PaneM / FrameM / PaneR / FrameR = the glb's glass-pane and frame metallic / roughness (specs.MATS: panes 0.5-0.6 / 0.07-0.1,
# frames 0.1 / 0.55): pixels on that blend line are glass modules, everything else keeps the glb look.
# Pane: base x GlassDark, metallic 0.6 / specular 1 -> F0 ~0.2 tinted by the glass colour (reflective coated curtain
# wall: ~10-30 % visible reflectance, 추정 from maker data sheets), roughness 0.03 + up to 0.05 per pane.
# GlassDark 0.45 / metallic 0.7 (first pass) measured too dark against the photos: Zenith from the air sRGB (62, 73, 89),
# LCT from the beach (63, 89, 121) vs photos (93, 116, 144) / (104, 129, 160) - the photos' glass is about as bright on
# average as the old look; what differs is the pane / floor variation and the sharp reflections, so 0.8 / 0.6.
# Variation per pane / floor (brightness +-PaneVar/2, +-FloorVar/2) and a random pane tilt up to TiltDeg plus a pillow of
# BowDeg inside each pane - fades out where panes get smaller than a pixel. Mullions: base x FrameGain, brushed aluminium.
GLASS = dict(GlassOn=1.0, Grid=4.0, PaneM=0.55, FrameM=0.10, PaneR=0.09, FrameR=0.55,
             GlassDark=0.8, GlassMetal=0.6, GlassSpec=1.0, GlassRough=0.03, GlassRoughVar=0.05,
             PaneVar=0.30, FloorVar=0.20, TiltDeg=0.8, BowDeg=0.4,
             FrameGain=0.75, FrameMetal=0.6, FrameRough=0.35)


def url():
    p = TILES + "/tileset.json"
    return ("file:///" + p.lstrip("/")) if os.path.isfile(p) else None


def find(world):
    a = unreal.GameplayStatics.get_all_actors_with_tag(world, TAG)
    return a[0] if a else None


def spawn_editor(log=unreal.log):
    """the landmarks tileset as an actor in the EDITOR world before Play (Play copies the editor world). Dirties the level:
    only for the offscreen check editor on a temporary map copy (never saved), not for the user's editor."""
    w = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_editor_world()
    a = find(w)
    if a is None:
        a = unreal.get_editor_subsystem(unreal.EditorActorSubsystem).spawn_actor_from_class(unreal.Cesium3DTileset, unreal.Vector(0, 0, 0))
        a.tags = [unreal.Name(TAG)]
        a.set_editor_property("tileset_source", unreal.TilesetSource.FROM_URL)
        a.set_editor_property("url", "")
        a.set_actor_hidden_in_game(True)
        log("[landmarks] editor-world actor spawned")
    return a


def apply(world, log=unreal.log, georef=None):
    """point the landmarks tileset in `world` at the local tiles. -> the actor, or None (off / no tiles / no actor)."""
    if os.environ.get("GYROSIM_LANDMARKS", "1") == "0":
        log("[landmarks] off (GYROSIM_LANDMARKS=0)")
        return None
    u = url()
    if u is None:
        log("[landmarks] no tiles at %s (python -I sim/landmarks/landmarks_build.py --build)" % TILES)
        return None
    try:
        a = find(world)
        if a is None:                         # Python cannot spawn into the Play world -> the actor must be in the map
            log("[landmarks] no CesiumLandmarks actor in the map: run Scripts/add_landmarks_actor.py once with the editor closed")
            return None
        if georef is not None:
            try:
                a.set_georeference(georef)
            except Exception as e:
                log("[landmarks] georeference %r" % (e,))
        a.set_actor_location_and_rotation(unreal.Vector(0, 0, 0), unreal.Rotator(roll=0, pitch=0, yaw=90.0), False, True)
        a.set_editor_property("tileset_source", unreal.TilesetSource.FROM_URL)
        a.set_editor_property("url", u)
        for k, v in (("maximum_screen_space_error", SSE), ("create_physics_meshes", True), ("show_credits_on_screen", False)):
            try:
                a.set_editor_property(k, v)
            except Exception as e:
                log("[landmarks] %s %r" % (k, e))
        m = None
        if os.environ.get("GYROSIM_LM_GLASS", "1") != "0":
            try:                                               # load_asset: the registry may still be scanning at autoplay
                m = unreal.load_asset(GLASS_MI)
            except Exception:
                m = None
        try:
            a.set_editor_property("material", m)               # None = Cesium default glTF material (PBR from the glb)
            log("[landmarks] material %s" % (GLASS_MI if m else "Cesium default"))
        except Exception as e:
            log("[landmarks] material %r" % (e,))
        a.set_actor_hidden_in_game(False)
        a.refresh_tileset()
        log("[landmarks] on: %s" % u)
        return a
    except Exception as e:
        log("[landmarks] failed %r" % (e,))
        return None


def hide(world):
    a = find(world)
    if a is not None:
        a.set_actor_hidden_in_game(True)
