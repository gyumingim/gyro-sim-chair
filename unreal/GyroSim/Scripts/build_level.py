"""Builds /Game/Maps/FlightMap from engine basic shapes. Run headless:

  "C:\\Program Files\\Epic Games\\UE_5.8\\Engine\\Binaries\\Win64\\UnrealEditor-Cmd.exe" ^
      <path>\\GyroSim.uproject -run=pythonscript -script=<path>\\Scripts\\build_level.py -unattended -nosplash

Re-running rebuilds the map from scratch (materials are reused). Units: cm. X = north, Y = east, Z = up.
Runway: 3000 m x 45 m along X; the sim's start point (lat0/lon0) = world origin, which is 150 m north of the
south threshold, so a runway start has ~2.85 km ahead.
"""
import math
import unreal

MAP = "/Game/Maps/FlightMap"
MAT_DIR = "/Game/Materials"
log = lambda *a: unreal.log("[build_level] " + " ".join(str(x) for x in a))

eas = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
les = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
assets = unreal.AssetToolsHelpers.get_asset_tools()
MEL = unreal.MaterialEditingLibrary

SHAPE = {n: unreal.load_asset(f"/Engine/BasicShapes/{n}.{n}") for n in ("Plane", "Cube", "Cylinder", "Cone", "Sphere")}
for n, m in SHAPE.items():
    b = m.get_bounds()
    log("shape", n, "origin", b.origin, "extent", b.box_extent)


def material(name, rgb, rough=0.8, metal=0.0):
    path = f"{MAT_DIR}/{name}"
    if unreal.EditorAssetLibrary.does_asset_exist(path):
        return unreal.load_asset(path)
    m = assets.create_asset(name, MAT_DIR, unreal.Material, unreal.MaterialFactoryNew())
    c = MEL.create_material_expression(m, unreal.MaterialExpressionConstant3Vector, -400, 0)
    c.set_editor_property("constant", unreal.LinearColor(rgb[0], rgb[1], rgb[2], 1.0))
    MEL.connect_material_property(c, "", unreal.MaterialProperty.MP_BASE_COLOR)
    r = MEL.create_material_expression(m, unreal.MaterialExpressionConstant, -400, 200)
    r.set_editor_property("r", rough)
    MEL.connect_material_property(r, "", unreal.MaterialProperty.MP_ROUGHNESS)
    if metal:
        k = MEL.create_material_expression(m, unreal.MaterialExpressionConstant, -400, 300)
        k.set_editor_property("r", metal)
        MEL.connect_material_property(k, "", unreal.MaterialProperty.MP_METALLIC)
    MEL.recompile_material(m)
    unreal.EditorAssetLibrary.save_loaded_asset(m)
    return m


MAT = dict(
    grass=material("M_Grass", (0.07, 0.16, 0.04), 0.95),
    hill=material("M_Hill", (0.10, 0.12, 0.05), 0.95),
    rock=material("M_Rock", (0.20, 0.18, 0.15), 0.9),
    asphalt=material("M_Asphalt", (0.025, 0.025, 0.028), 0.85),
    mark=material("M_Mark", (0.8, 0.8, 0.8), 0.7),
    body=material("M_Body", (0.33, 0.36, 0.40), 0.45, 0.3),
    dark=material("M_Dark", (0.05, 0.05, 0.06), 0.5),
    canopy=material("M_Canopy", (0.25, 0.20, 0.05), 0.1, 0.8),
)

# ---- fresh level -------------------------------------------------------------------------------------------------
if unreal.EditorAssetLibrary.does_asset_exist(MAP):
    les.load_level(MAP)
    for a in eas.get_all_level_actors():
        eas.destroy_actor(a)
    log("cleared existing", MAP)
else:
    les.new_level(MAP)
    log("created", MAP)


def mesh(label, shape, loc, scale, mat, rot=(0, 0, 0), movable=False, shadows=True):
    a = eas.spawn_actor_from_class(unreal.StaticMeshActor, unreal.Vector(*loc), unreal.Rotator(roll=rot[0], pitch=rot[1], yaw=rot[2]))
    a.set_actor_label(label)
    c = a.static_mesh_component
    c.set_static_mesh(SHAPE[shape])
    c.set_material(0, mat)
    a.set_actor_scale3d(unreal.Vector(*scale))
    c.set_mobility(unreal.ComponentMobility.MOVABLE if movable else unreal.ComponentMobility.STATIC)
    c.set_editor_property("cast_shadow", shadows)
    return a


# ---- ground, runway ------------------------------------------------------------------------------------------------
# ground: 20 x 20 tiles of 20 km = 400 km square at z = -5 cm. (One single 400 km plane was not drawn when seen from
# altitude - only near the camera - so it is tiled.)
TILE = 2.0e6
for i in range(-10, 10):
    for j in range(-10, 10):
        g = mesh(f"Ground_{i + 10:02d}_{j + 10:02d}", "Plane", ((i + 0.5) * TILE, (j + 0.5) * TILE, -5), (TILE / 100, TILE / 100, 1),
                 MAT["grass"], shadows=False)
        g.static_mesh_component.set_editor_property("affect_distance_field_lighting", False)
RW_LEN, RW_W, RW_X0 = 300000.0, 4500.0, -15000.0                                           # cm; south threshold at x = -150 m
rw_cx = RW_X0 + RW_LEN / 2
mesh("Runway", "Plane", (rw_cx, 0, 1), (RW_LEN / 100, RW_W / 100, 1), MAT["asphalt"], shadows=False)
mesh("RunwayShoulder", "Plane", (rw_cx, 0, -2), (RW_LEN / 100 + 60, RW_W / 100 + 30, 1), MAT["rock"], shadows=False)
# centre line: 30 m stripes, 20 m gaps, 0.9 m wide
x = RW_X0 + 15000 + 3000
n = 0
while x + 3000 < RW_X0 + RW_LEN - 15000:
    mesh(f"CL_{n:03d}", "Plane", (x + 1500, 0, 3), (30, 0.9, 1), MAT["mark"], shadows=False)
    x += 5000
    n += 1
log("centre line stripes", n)
# threshold piano keys (both ends) + side lines
for end, xs in (("S", RW_X0 + 1000), ("N", RW_X0 + RW_LEN - 1000 - 3000)):
    for k in range(8):
        y = -1900 + k * 543 if k < 4 else 270 + (k - 4) * 543
        mesh(f"THR_{end}{k}", "Plane", (xs + 1500, y + 90, 3), (30, 1.8, 1), MAT["mark"], shadows=False)
for side in (-1, 1):
    mesh(f"Edge_{'L' if side < 0 else 'R'}", "Plane", (rw_cx, side * (RW_W / 2 - 60), 3), (RW_LEN / 100, 0.9, 1), MAT["mark"], shadows=False)

# a couple of hangars + a tower so speed/height are readable near the ground
for i, x in enumerate((20000, 32000, 44000)):
    mesh(f"Hangar_{i}", "Cube", (x, -12000, 600), (60, 40, 12), MAT["rock"])
mesh("Tower", "Cylinder", (60000, -9000, 1500), (6, 6, 30), MAT["mark"])

# ---- hills ---------------------------------------------------------------------------------------------------------
import random
random.seed(7)
nh = 0
for i in range(70):
    r = random.uniform(5e5, 3.5e6)                   # 5 .. 35 km
    th = random.uniform(0, 2 * math.pi)
    hx, hy = r * math.cos(th), r * math.sin(th)
    if abs(hy) < 3e5 and -2e5 < hx < 8e5:            # keep the approach / climb-out corridor clear
        continue
    h = random.uniform(2e4, 1.2e5)                   # 200 .. 1200 m high
    w = h * random.uniform(2.5, 5.0)
    if random.random() < 0.6:
        mesh(f"Hill_{i:02d}", "Cone", (hx, hy, 0), (w / 100, w / 100 * random.uniform(0.7, 1.3), h / 100), MAT["hill"])
    else:
        mesh(f"Hill_{i:02d}", "Sphere", (hx, hy, -h * 0.4), (w / 100, w / 100, h * 1.4 / 100), MAT["hill"])
    nh += 1
log("hills", nh)

# ---- sky + lights --------------------------------------------------------------------------------------------------
sun = eas.spawn_actor_from_class(unreal.DirectionalLight, unreal.Vector(0, 0, 50000), unreal.Rotator(roll=0, pitch=-40, yaw=135))
sun.set_actor_label("Sun")
lc = sun.get_component_by_class(unreal.DirectionalLightComponent)
lc.set_mobility(unreal.ComponentMobility.MOVABLE)
lc.set_editor_property("intensity", 10.0)
lc.set_editor_property("atmosphere_sun_light", True)
for prop, val in (("dynamic_shadow_distance_movable_light", 30000.0),):
    try:
        lc.set_editor_property(prop, val)
    except Exception as e:
        log("skip", prop, e)

sky = eas.spawn_actor_from_class(unreal.SkyAtmosphere, unreal.Vector(0, 0, 0))
sky.set_actor_label("SkyAtmosphere")
try:      # default aerial perspective turns the whole ground blue from a few km up; keep it lighter
    sky.get_component_by_class(unreal.SkyAtmosphereComponent).set_editor_property("aerial_pespective_view_distance_scale", 0.3)   # sic: engine typo
except Exception as e:
    log("aerial perspective scale skipped", e)

sl = eas.spawn_actor_from_class(unreal.SkyLight, unreal.Vector(0, 0, 20000))
sl.set_actor_label("SkyLight")
slc = sl.get_component_by_class(unreal.SkyLightComponent)
slc.set_mobility(unreal.ComponentMobility.MOVABLE)
slc.set_editor_property("real_time_capture", True)

fog = eas.spawn_actor_from_class(unreal.ExponentialHeightFog, unreal.Vector(0, 0, 0))
fog.set_actor_label("HeightFog")
fc = fog.get_component_by_class(unreal.ExponentialHeightFogComponent)
fc.set_editor_property("fog_density", 0.0001)          # thin: denser fog turns the ground below ~1 km blue
fc.set_editor_property("fog_height_falloff", 0.2)

cloud_mat = unreal.load_asset("/Engine/EngineSky/VolumetricClouds/m_SimpleVolumetricCloud_Inst")
if cloud_mat:
    vc = eas.spawn_actor_from_class(unreal.VolumetricCloud, unreal.Vector(0, 0, 0))
    vc.set_actor_label("VolumetricCloud")
    vcc = vc.get_component_by_class(unreal.VolumetricCloudComponent)
    vcc.set_editor_property("material", cloud_mat)
    vcc.set_editor_property("layer_bottom_altitude", 3.0)     # km
    vcc.set_editor_property("layer_height", 4.0)
    log("volumetric cloud", cloud_mat.get_path_name())
else:
    log("no cloud material - skipped VolumetricCloud")

pp = eas.spawn_actor_from_class(unreal.PostProcessVolume, unreal.Vector(0, 0, 0))
pp.set_actor_label("PostProcess")
pp.set_editor_property("unbound", True)

ps = eas.spawn_actor_from_class(unreal.PlayerStart, unreal.Vector(-3000, 0, 300))
ps.set_actor_label("PlayerStart")

# ---- aircraft (root = empty static mesh actor at the JSBSim reference point, body axes = actor axes) ---------------
root = eas.spawn_actor_from_class(unreal.StaticMeshActor, unreal.Vector(0, 0, 0))
root.set_actor_label("Aircraft")
root.static_mesh_component.set_mobility(unreal.ComponentMobility.MOVABLE)
root.tags = [unreal.Name("Aircraft")]
G = 150.0                                        # cm, fuselage centre-line height above the actor origin offset (see below)
Z0 = 0.0                                         # actor origin = JSBSim position; parts placed around it
parts = [
    # label, shape, loc (body frame, cm), scale, mat, rot (roll, pitch, yaw)
    ("AC_Fuselage", "Cylinder", (0, 0, Z0), (1.15, 1.15, 13.0), MAT["body"], (0, 90, 0)),
    ("AC_Nose", "Cone", (760, 0, Z0), (1.1, 1.1, 2.4), MAT["dark"], (0, -90, 0)),
    ("AC_Canopy", "Sphere", (380, 0, Z0 + 60), (2.6, 0.85, 0.75), MAT["canopy"], (0, 0, 0)),
    ("AC_Wing", "Cube", (-80, 0, Z0 - 10), (3.6, 9.4, 0.14), MAT["body"], (0, 0, 0)),
    ("AC_Strake_L", "Cube", (180, -70, Z0 - 10), (3.0, 0.8, 0.12), MAT["body"], (0, 0, -12)),
    ("AC_Strake_R", "Cube", (180, 70, Z0 - 10), (3.0, 0.8, 0.12), MAT["body"], (0, 0, 12)),
    ("AC_HTail", "Cube", (-560, 0, Z0 - 5), (1.7, 5.6, 0.1), MAT["body"], (0, 0, 0)),
    ("AC_Fin", "Cube", (-540, 0, Z0 + 170), (2.2, 0.12, 2.6), MAT["body"], (0, 0, 0)),
    ("AC_Nozzle", "Cylinder", (-680, 0, Z0), (0.95, 0.95, 0.6), MAT["dark"], (0, 90, 0)),
    ("AC_TipL", "Cube", (-80, -470, Z0 - 5), (2.5, 0.1, 0.1), MAT["mark"], (0, 0, 0)),
    ("AC_TipR", "Cube", (-80, 470, Z0 - 5), (2.5, 0.1, 0.1), MAT["mark"], (0, 0, 0)),
    ("AC_GearN", "Cylinder", (450, 0, Z0 - 110), (0.15, 0.15, 1.6), MAT["dark"], (0, 0, 0)),
    ("AC_GearL", "Cylinder", (-60, -120, Z0 - 110), (0.18, 0.18, 1.6), MAT["dark"], (0, 0, 0)),
    ("AC_GearR", "Cylinder", (-60, 120, Z0 - 110), (0.18, 0.18, 1.6), MAT["dark"], (0, 0, 0)),
]
for label, shape, loc, sc, mat, rot in parts:
    p = mesh(label, shape, loc, sc, mat, rot, movable=True)
    p.static_mesh_component.set_collision_enabled(unreal.CollisionEnabled.NO_COLLISION)
    p.tags = [unreal.Name("AircraftPart")] + ([unreal.Name("Canopy")] if label == "AC_Canopy" else [])
    p.attach_to_actor(root, unreal.Name(""), unreal.AttachmentRule.KEEP_WORLD, unreal.AttachmentRule.KEEP_WORLD,
                      unreal.AttachmentRule.KEEP_WORLD, False)

cam = eas.spawn_actor_from_class(unreal.CameraActor, unreal.Vector(-3000, 0, 800), unreal.Rotator(roll=0, pitch=-5, yaw=0))
cam.set_actor_label("SimCamera")
cam.tags = [unreal.Name("SimCamera")]
cc = cam.camera_component
cc.set_mobility(unreal.ComponentMobility.MOVABLE)
cc.set_editor_property("field_of_view", 75.0)
cc.set_editor_property("constrain_aspect_ratio", False)
cam.set_editor_property("auto_activate_for_player", unreal.AutoReceiveInput.PLAYER0)

# ---- world settings: plain GameModeBase (spawns an invisible DefaultPawn; the camera actor is the view target) ---
ws = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_editor_world().get_world_settings()
try:
    ws.set_editor_property("default_game_mode", unreal.GameModeBase)
except Exception as e:
    log("game mode override skipped", e)

ok = les.save_current_level()
log("saved", MAP, ok, "actors", len(eas.get_all_level_actors()))
