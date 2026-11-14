"""Mirrored-geometry canopy reflection (11-13, user request): the cockpit interior is copied and MIRRORED across a few planes
fitted to the canopy (left side y = -SIDE_Y, right side y = +SIDE_Y, top z = TOP_Z, aircraft-local cm), one copy per region,
placed outside the glass. Seen through the canopy, each copy looks like the interior reflected in that part of the glass.
Each copy uses M_CkCanopyGhost (additive, unlit, two-sided, no shadows / collision): shaded neutral grey x Fresnel of the
region's plane x a mask that keeps it visible only through its own canopy region (view-direction test from the camera in
the aircraft frame), x Ghost (strength). Full = 1: no Fresnel (debug, the mirrored shapes at full brightness).
EDITOR worlds only (CockpitView): Python cannot spawn actors into a Play world - the sim would need the copies placed in
FlightMap (an add_*_actor style script) or spawned by a Blueprint. Not done.
    import canopy_ghost; canopy_ghost.build(world, ghost=0.6)      # faint
    canopy_ghost.set_strength(world, ghost=5.0, full=1.0)            # debug full
    canopy_ghost.remove(world)
"""
import unreal

MAT = "/Game/Cockpit/Materials/M_CkCanopyGhost"
TAG = "CanopyGhost"
SIDE_Y, TOP_Z = 34.0, 127.0                      # canopy bbox: y -33.8..34.0, z 62.5..127.1 (F16_Glass / _Smooth)
REGIONS = (("left", 0.0, (0.0, -SIDE_Y, 0.0), (1.0, -1.0, 1.0)),
           ("right", 1.0, (0.0, SIDE_Y, 0.0), (1.0, -1.0, 1.0)),
           ("top", 2.0, (0.0, 0.0, TOP_Z), (1.0, 1.0, -1.0)))
SOURCE_PREFIX = ("AC_CkShell", "AC_ck_", "Light_", "AC_ck_gear")   # cockpit shell (panel, consoles, seat, HUD hardware), stick ...
log = lambda *a: unreal.log("[canopy_ghost] " + " ".join(str(x) for x in a))
eas = lambda: unreal.get_editor_subsystem(unreal.EditorActorSubsystem)


def _aircraft(world):
    a = unreal.GameplayStatics.get_all_actors_with_tag(world, "Aircraft")
    return a[0] if a else None


def _sources(world, ac):
    out = []
    for a in [ac] + list(ac.get_attached_actors(True, True)):
        lab = a.get_actor_label()
        if any(lab.startswith(p) for p in SOURCE_PREFIX):
            for c in a.get_components_by_class(unreal.StaticMeshComponent):
                if c.static_mesh is not None and c.is_visible():
                    out.append(c)
    return out


def remove(world):
    for a in unreal.GameplayStatics.get_all_actors_with_tag(world, TAG):
        eas().destroy_actor(a)


def _mids(world):
    out = []
    for a in unreal.GameplayStatics.get_all_actors_with_tag(world, TAG):
        for c in a.get_components_by_class(unreal.StaticMeshComponent):
            for i in range(c.get_num_materials()):
                m = c.get_material(i)
                if isinstance(m, unreal.MaterialInstanceDynamic) and m not in out:
                    out.append(m)
    return out


def set_strength(world, ghost=0.6, full=0.0):
    ac = _aircraft(world)
    fw, rt, up = ac.get_actor_forward_vector(), ac.get_actor_right_vector(), ac.get_actor_up_vector()
    sun = [a for a in unreal.GameplayStatics.get_all_actors_of_class(world, unreal.DirectionalLight)]
    sd = sun[0].get_actor_forward_vector() if sun else unreal.Vector(0, 0, -1)
    lc = lambda v: unreal.LinearColor(v.x, v.y, v.z, 0.0)
    for m in _mids(world):
        m.set_scalar_parameter_value("Ghost", float(ghost))
        m.set_scalar_parameter_value("Full", float(full))
        m.set_vector_parameter_value("Fw", lc(fw)); m.set_vector_parameter_value("Rt", lc(rt)); m.set_vector_parameter_value("Up", lc(up))
        m.set_vector_parameter_value("SunDir", lc(sd))


def build(world, ghost=0.6, full=0.0):
    """(re)build the mirrored copies in an EDITOR world; returns the number of copied components."""
    remove(world)
    ac = _aircraft(world)
    mat = unreal.load_asset(MAT)
    if ac is None or mat is None:
        log("no", "aircraft" if ac is None else "material")
        return 0
    act = ac.get_actor_transform()
    src = _sources(world, ac)
    n = 0
    for name, reg, origin, scale in REGIONS:
        mid = unreal.MaterialLibrary.create_dynamic_material_instance(world, mat)
        mid.set_scalar_parameter_value("Region", reg)
        root = eas().spawn_actor_from_class(unreal.StaticMeshActor, ac.get_actor_location(), ac.get_actor_rotation(), transient=True)
        root.set_actor_label("CanopyGhost_" + name)
        root.tags = [unreal.Name(TAG)]
        root.root_component.set_mobility(unreal.ComponentMobility.MOVABLE)
        root.attach_to_actor(ac, unreal.Name(""), unreal.AttachmentRule.KEEP_WORLD, unreal.AttachmentRule.KEEP_WORLD,
                             unreal.AttachmentRule.KEEP_WORLD, False)
        root.root_component.set_relative_location_and_rotation(unreal.Vector(*origin), unreal.Rotator(0, 0, 0), False, True)
        root.set_actor_relative_scale3d(unreal.Vector(*scale))          # the mirror (negative scale on one axis)
        for c in src:
            rel = unreal.MathLibrary.make_relative_transform(c.get_world_transform(), act)   # in the aircraft frame
            t = rel.translation
            cp = eas().spawn_actor_from_class(unreal.StaticMeshActor, ac.get_actor_location(), ac.get_actor_rotation(), transient=True)
            cp.tags = [unreal.Name(TAG)]
            sm = cp.static_mesh_component
            sm.set_mobility(unreal.ComponentMobility.MOVABLE)
            sm.set_static_mesh(c.static_mesh)
            sm.set_cast_shadow(False)
            sm.set_collision_enabled(unreal.CollisionEnabled.NO_COLLISION)
            for i in range(sm.get_num_materials()):
                sm.set_material(i, mid)
            cp.attach_to_actor(root, unreal.Name(""), unreal.AttachmentRule.KEEP_WORLD, unreal.AttachmentRule.KEEP_WORLD,
                               unreal.AttachmentRule.KEEP_WORLD, False)
            cp.root_component.set_relative_transform(
                unreal.Transform(location=unreal.Vector(t.x - origin[0], t.y - origin[1], t.z - origin[2]),
                                 rotation=rel.rotation.rotator(), scale=rel.scale3d), False, True)
            n += 1
    set_strength(world, ghost, full)
    log("built", n, "mirrored components in", len(REGIONS), "regions, ghost", ghost, "full", full)
    return n
