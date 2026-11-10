"""Cockpit v2 at Play (F-16 Block 50/52 style interior, Scripts/cockpit_blender). sim_client calls apply(world) at the
start of _bind_world (before it reads the pivots / needles / screens) and after_bind(client) once the HUD material
instance exists.

FlightMap is not changed. The v1 actors placed by Scripts/cockpit/ue_cockpit.py keep their tags; we only swap their
meshes and move them:
  AC_CkShell / AC_CkGlass         -> ck2_shell / ck2_glass (panel, consoles, seat, HUD hardware, kneeboard / glass)
  StickPivot (+ child mesh)       -> sidestick on the right console (GYROSIM_CK2_STICK=center keeps the v1 centre stick)
  ThrottlePivot, GearHandle, GearLights, Light_*   -> v2 meshes / positions
  NeedleFrame_* / ADIFrame        -> v2 dial centres (needle scale = dial size / v1 size)
  MFD_L / MFD_R screen planes     -> the 4 in class MFD windows;  MFD_C (training display) -> kneeboard on the left thigh
  BeginnerLabel planes            -> next to the v2 instruments
  HUD clip (C_Wd / C_H1 params)   -> the narrower v2 combiner glass
Assets: /Game/ThirdParty/Cockpit2 (Scripts/cockpit_blender/ck2_ue_import.py, gitignored), positions: the export
manifest (C:/GyroSimTiles/assets/cockpit/export/manifest.json). Anything missing -> v1 stays. GYROSIM_COCKPIT_V2=0 = v1.
set_mode(False / True) switches back and forth at runtime (A/B shots).
"""
import json
import os

import unreal

ON = os.environ.get("GYROSIM_COCKPIT_V2", "1") != "0"
STICK = os.environ.get("GYROSIM_CK2_STICK", "side")
MAN_PATH = os.environ.get("GYROSIM_CK2_MANIFEST", r"C:\GyroSimTiles\assets\cockpit\export\manifest.json")
MESH = "/Game/ThirdParty/Cockpit2/Meshes/"
V1_SIZE = 7.2                     # v1 dial bezel the needles were made for
HUD_V1 = dict(C_Wd=27.8, C_H1=31.03357749110842)

_st = dict(world=None, saved=[], applied=False, man=None)


def _log(*a):
    unreal.log("[cockpit_v2] " + " ".join(str(x) for x in a))


def _v(p):
    return unreal.Vector(float(p[0]), float(p[1]), float(p[2]))


def _mesh(n):
    return unreal.load_asset(MESH + n)


def _smc(a):
    return getattr(a, "static_mesh_component", None)


def _save(a):
    """remember an actor's mesh and relative transform once (restored by set_mode(False))"""
    for s in _st["saved"]:
        if s[0] == a:
            return
    rc = a.root_component
    c = _smc(a)
    mats = [c.get_material(i) for i in range(c.get_num_materials())] if c else []     # component overrides (realism passes set some)
    _st["saved"].append((a, c.static_mesh if c else None, rc.get_editor_property("relative_location"),
                         rc.get_editor_property("relative_rotation"), rc.get_editor_property("relative_scale3d"), mats))


def _place(a, loc=None, rot=None, scale=None, mesh=None):
    _save(a)
    if mesh is not None and _smc(a):
        c = _smc(a)
        c.set_static_mesh(mesh)
        for i in range(c.get_num_materials()):      # drop the v1 per-slot overrides (the old glass got an opaque one)
            c.set_material(i, mesh.get_material(i))
    if loc is not None:
        a.set_actor_relative_location(_v(loc), False, True)
    if rot is not None:
        a.set_actor_relative_rotation(rot, False, True)
    if scale is not None:
        a.set_actor_relative_scale3d(_v(scale))


def _tag(world, t):
    return list(unreal.GameplayStatics.get_all_actors_with_tag(world, t))


def _rot_xz(x, z):
    return unreal.MathLibrary.make_rot_from_xz(_v(x), _v(z))


def _rot_zx(z, x=(0.0, 1.0, 0.0)):
    return unreal.MathLibrary.make_rot_from_zx(_v(z), _v(x))


def _children(a):
    try:
        return list(a.get_attached_actors(False, True))
    except TypeError:
        return list(a.get_attached_actors())


def _parent(a):
    try:
        return a.get_attach_parent_actor()
    except Exception:
        return None


def apply(world):
    """swap the cockpit (before sim_client binds the tags). Safe to call once per Play world."""
    if not ON or world is None:
        return False
    if _st["world"] is world and _st["applied"]:
        return True
    _st.update(world=world, saved=[], applied=False)
    try:
        man = json.load(open(MAN_PATH, encoding="utf-8"))
        shell, glass = _mesh("ck2_shell"), _mesh("ck2_glass")
        if not (shell and glass):
            _log("assets missing (run Scripts/cockpit_blender/ck2_ue_import.py) - v1 kept")
            return False
        _st["man"] = man
        _do(world, man, shell, glass)
        _st["applied"] = True
        _log("v2 on: stick=%s, %d actors changed" % (STICK, len(_st["saved"])))
        return True
    except Exception as e:
        import traceback
        _log("apply failed - v1 kept", repr(e), " | ".join(traceback.format_exc().splitlines()[-4:]))
        set_mode(False)
        return False


def _do(world, man, shell, glass):
    zero = unreal.Rotator(roll=0.0, pitch=0.0, yaw=0.0)
    for a in _tag(world, "Cockpit"):
        c = _smc(a)
        n = c.static_mesh.get_name() if c and c.static_mesh else ""
        if n == "ck_shell":
            _place(a, mesh=shell)
            if os.environ.get("GYROSIM_CK2_DFL", "1") == "0":     # 11-11: DF now built two-sided -> Lumen OK
                _lumen_off(c)
        elif n == "ck_glass":
            _place(a, mesh=glass)
            if os.environ.get("GYROSIM_CK2_GLASS", "1") == "0":       # debug: no instrument / HUD glass
                a.static_mesh_component.set_visibility(False, False)
    PV = man["pivots"]
    for tag, part in (("StickPivot", "ck2_stick"), ("ThrottlePivot", "ck2_throttle"), ("GearHandle", "ck2_gearhandle")):
        if tag == "StickPivot" and STICK == "center":
            continue
        piv = _tag(world, tag)
        m = _mesh(part)
        if not piv or not m:
            continue
        piv = piv[0]
        _place(piv, loc=PV[tag], rot=zero)
        for ch in _children(piv):
            if _smc(ch):
                _place(ch, loc=(0.0, 0.0, 0.0), rot=zero, mesh=m)
    gl = _tag(world, "GearLights")
    if gl and _mesh(man.get("gearlights", "ck2_gearlights")):
        p = gl[0]
        _place(p, loc=(0.0, 0.0, 0.0), rot=zero, mesh=_mesh(man.get("gearlights", "ck2_gearlights")))
    for name, li in (man.get("lights") or {}).items():
        for a in _tag(world, "Light_" + name):
            m = _mesh(li["part"])
            if m:
                _place(a, loc=(0.0, 0.0, 0.0), rot=zero, mesh=m)
    # needles / ADI: move their (untagged) parent frames
    for nd, f in man["needles"].items():
        for a in _tag(world, "Needle_" + nd):
            fr = _parent(a) or a
            s = float(f.get("scale", 1.0))
            _place(fr, loc=f["center"], rot=_rot_xz(f["x_axis"], f["z_axis"]), scale=(s, s, s))
    b = PV.get("ADIBall")
    for a in _tag(world, "ADIBall"):
        fr = _parent(a) or a
        _place(fr, loc=b["center"], rot=_rot_xz(b["x_axis"], b["z_axis"]))
    # screens
    for tag, s in man["screens"].items():
        for a in _tag(world, tag):
            w, h = s["size"]
            _place(a, loc=s["center"], rot=_rot_zx(s["normal"], s.get("right", (0.0, 1.0, 0.0)) if tag != "MFD_C" else _right(s)),
                   scale=(w / 100.0, h / 100.0, 1.0))
    # beginner callouts (Korean name pictures): identified by their material (MI_Lbl_<key>)
    cal = man.get("callouts") or {}
    for a in _tag(world, "BeginnerLabel"):
        c = _smc(a)
        try:
            mn = c.get_material(0).get_name()
        except Exception:
            continue
        k = mn[len("MI_Lbl_"):] if mn.startswith("MI_Lbl_") else None
        if k in cal:
            _place(a, loc=cal[k]["center"], rot=_rot_zx(cal[k]["normal"]))


def _lumen_off(c):
    """the v2 shell's mesh distance field comes out empty (thin open surfaces): Lumen's surface cache then lit it in bright
    blotches (HUD body, upper panel). Keep it out of distance-field lighting; screen-space GI / shadows still apply."""
    for k, v in (("affect_distance_field_lighting", False),):
        try:
            c.set_editor_property(k, v)
        except Exception as e:
            _log("component flag", k, repr(e))


def _right(s):
    k = s.get("right")
    if k is None:
        n, up = s["normal"], s["up"]
        k = (n[1] * up[2] - n[2] * up[1], n[2] * up[0] - n[0] * up[2], n[0] * up[1] - n[1] * up[0])      # n x up = pilot's right
    return k


def after_bind(client):
    """HUD clip to the v2 combiner (scalar params of the HUD dynamic instance created by sim_client)"""
    if not _st["applied"]:
        return
    try:
        hc = (_st["man"] or {}).get("hud_combiner") or {}
        a_mid = (getattr(client, "screens", {}) or {}).get("HUD")
        if a_mid and hc:
            mid = a_mid[1]
            mid.set_scalar_parameter_value("C_Wd", float(hc["w"]))
            mid.set_scalar_parameter_value("C_H1", float(hc["h1"]))
            _st["hud_mid"] = mid
    except Exception as e:
        _log("hud clip", repr(e))


def set_mode(on):
    """False = put every changed actor back (v1 look), True = apply again (A/B shots in one Play session)"""
    w = _st["world"]
    if not on:
        for a, mesh, loc, rot, sc, mats in _st["saved"]:
            try:
                if mesh is not None and _smc(a) and _smc(a).static_mesh != mesh:      # only parts whose mesh we swapped
                    _smc(a).set_static_mesh(mesh)                                     # (screens keep sim_client's live MIDs)
                    for i, m in enumerate(mats):
                        _smc(a).set_material(i, m)
                a.set_actor_relative_location(loc, False, True)
                a.set_actor_relative_rotation(rot, False, True)
                a.set_actor_relative_scale3d(sc)
            except Exception:
                pass
        mid = _st.get("hud_mid")
        if mid:
            for k, v in HUD_V1.items():
                mid.set_scalar_parameter_value(k, v)
        _st["applied"] = False
    elif w is not None and _st["man"]:
        _do(w, _st["man"], _mesh("ck2_shell"), _mesh("ck2_glass"))
        _st["applied"] = True
        mid = _st.get("hud_mid")
        hc = _st["man"].get("hud_combiner") or {}
        if mid and hc:
            mid.set_scalar_parameter_value("C_Wd", float(hc["w"]))
            mid.set_scalar_parameter_value("C_H1", float(hc["h1"]))


def is_on():
    return bool(_st["applied"])
