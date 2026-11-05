"""Automated check, run when the editor starts with:  UnrealEditor.exe GyroSim.uproject -GyroSimVerify  (see init_unreal.py)
or inside the open editor:  exec(open(r"<project>/Scripts/verify_pie.py").read())
Starts PIE (monitor mode), checks: start menu, lesson flow (briefing -> practice -> debrief), cockpit controls follow
the control values, standby needles / ADI / gear handle / gear lights, the displays show the state, warnings (synthetic
states + a real over-G pull, master caution light), beginner labels on / off, keyboard vs rig instruction wording, key
guide panel toggle (K), interpolation smoothness, chase view, third-person views (V cycle, orbit by mouse / keys, flyby,
tower, HUD hidden outside the cockpit, VR comfort). Screenshots of all of it (incl. clouds).
Screenshots + verify_result.json go to Saved/verify/. Needs sim/server.py running. Leaves the editor open.
"""
import json, math, os, time
import unreal
import sim_client

log = lambda *a: unreal.log("[verify] " + " ".join(str(x) for x in a))
les = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
ues = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem)
OUT = os.path.join(unreal.Paths.project_saved_dir(), "verify")
os.makedirs(OUT, exist_ok=True)
RESULT = {}
C = sim_client.client


def shot(name):
    w = ues.get_game_world()
    unreal.SystemLibrary.execute_console_command(w, "HighResShot 1600x900 filename=%s" % os.path.join(OUT, name + ".png").replace("\\", "/"))
    log("screenshot", name)


def check(name):
    c = C()
    s, a = c.s, c.aircraft
    loc, rot = a.get_actor_location(), a.get_actor_rotation()
    exp, _ = sim_client.SimClient.to_world(s)
    right_z = rot.get_right_vector().z
    fwd_z = rot.get_forward_vector().z
    cam = c.camera.get_actor_location()
    pc = unreal.GameplayStatics.get_player_controller(c.world, 0)
    vt = pc.get_view_target().get_name() if pc and pc.get_view_target() else None
    r = dict(t=round(s["t"], 2), rx=c.rx_n, alt_m=round(s["alt_m"], 1), phi=round(s["phi"], 2), theta=round(s["theta"], 2),
             psi=round(s["psi"], 2), actor=[round(loc.x), round(loc.y), round(loc.z)], packet=[round(exp.x), round(exp.y), round(exp.z)],
             actor_vs_packet_cm=round(math.dist((loc.x, loc.y, loc.z), (exp.x, exp.y, exp.z))),
             actor_rot=[round(rot.roll, 2), round(rot.pitch, 2), round(rot.yaw, 2)], right_z=round(right_z, 3), fwd_z=round(fwd_z, 3),
             cam=[round(cam.x), round(cam.y), round(cam.z)], view_target=vt, view=c.view, src=s.get("src"), hmd=c.hmd, preset=c.preset)
    r["roll_sign_ok"] = (abs(s["phi"]) < 2) or ((s["phi"] > 0) == (right_z < 0))
    r["pitch_sign_ok"] = (abs(s["theta"]) < 1) or ((s["theta"] > 0) == (fwd_z > 0))
    RESULT[name] = r
    log(name, json.dumps(r))


def check_controls(name, exp):
    c = C()
    out = dict(packet={k: round(c.s.get(k, -9), 2) for k in ("ail", "elev", "rud", "thr", "brk_l", "brk_r")})
    for tag, (a, base) in c.pivots.items():
        rc = a.root_component
        rr, rl = rc.get_editor_property("relative_rotation"), rc.get_editor_property("relative_location")
        out[tag] = dict(rot=[round(rr.roll, 1), round(rr.pitch, 1)], dx=round(rl.x - base.x, 1))
    sc = sim_client
    st = out.get("StickPivot", {}).get("rot", [0, 0])
    out["stick_ok"] = abs(st[0] - sc.STICK_ROLL * exp["ail"]) < 1.5 and abs(st[1] + sc.STICK_PITCH * exp["elev"]) < 1.5
    out["pedal_ok"] = abs(out.get("PedalR", {}).get("dx", 0) - sc.PEDAL_CM * exp["rud"]) < 1 and abs(out.get("PedalL", {}).get("dx", 0) + sc.PEDAL_CM * exp["rud"]) < 1
    out["brake_ok"] = abs(out.get("PedalL", {}).get("rot", [0, 0])[1] + sc.TOE_DEG * exp["brk"]) < 2
    th = out.get("ThrottlePivot", {}).get("rot", [0, 0])[1]
    out["throttle_ok"] = abs(th + sc.THR_SWING * (2 * c.s.get("thr", 0) - 1)) < 3
    tut = c.s.get("tut") or {}
    out["tutorial"] = dict(on=tut.get("on"), lesson=tut.get("lesson"), step=tut.get("step"), text=tut.get("text"), img=tut.get("img"),
                           panel_ver=c.tut_ver, panel_shown=c.panel_shown)
    out["hud"] = dict(frames=c.hud_n, draw_ms=round(c.hud_ms, 2), visible=c.hud_vis, cesium=c.cesium_mode, radar_m=c.radar_m,
                      screens=sorted(c.screens))
    RESULT[name] = out
    log(name, json.dumps(out, ensure_ascii=False))


def check_cockpit(name):
    """our cockpit: needles follow the sim state (cockpit_gauges scales), ADI ball follows the attitude, gear handle
    follows the gear command, gear lights follow the gear position."""
    import cockpit_gauges as G
    c = C()
    s = c.s
    out = dict(kts=round(s.get("kts", 0), 1), alt_ft=round(s.get("alt_m", 0) / 0.3048), vs_fpm=round(s.get("vs_fpm", 0)), gear=round(s.get("gear", 0), 2),
               gear_cmd=s.get("gear_cmd"), found=dict(needles=sorted(c.needles), adi=bool(c.adi), gear_lights=bool(c.gear_lights),
                                                      gear_handle="GearHandle" in c.pivots))
    exp = dict(asi=G.asi_deg(s.get("kts", 0)), alt=G.alt_deg(s.get("alt_m", 0) / 0.3048), alt10k=G.alt10k_deg(s.get("alt_m", 0) / 0.3048),
               vsi=G.vsi_deg(s.get("vs_fpm", 0)))
    nd = {}
    for n, a in c.needles.items():
        r = a.root_component.get_editor_property("relative_rotation")
        diff = (r.roll + exp[n] + 180) % 360 - 180
        nd[n] = dict(roll=round(r.roll, 1), expected=round(-exp[n], 1), ok=abs(diff) < 4.0)
    out["needles"] = nd
    if c.adi:
        r = c.adi.root_component.get_editor_property("relative_rotation")
        ap = c.aircraft.get_actor_rotation()
        e = unreal.MathLibrary.compose_rotators(unreal.Rotator(roll=0.0, pitch=-ap.pitch, yaw=0.0), unreal.Rotator(roll=ap.roll, pitch=0.0, yaw=0.0))
        q1, q2 = r.quaternion(), e.quaternion()
        dot = abs(q1.x * q2.x + q1.y * q2.y + q1.z * q2.z + q1.w * q2.w)
        out["adi"] = dict(rot=[round(r.roll, 1), round(r.pitch, 1), round(r.yaw, 1)], aircraft=[round(ap.roll, 1), round(ap.pitch, 1)],
                          ok=dot > 0.995)
    if "GearHandle" in c.pivots:
        p = c.pivots["GearHandle"][0].root_component.get_editor_property("relative_rotation").pitch
        down = (s.get("gear_cmd", 1) or 0) > 0.5
        out["gear_handle"] = dict(pitch=round(p, 1), ok=(p > 10) if down else (p < -10))
    if c.gear_lights:
        hid = bool(c.gear_lights.get_editor_property("hidden"))
        out["gear_lights"] = dict(hidden=hid, ok=hid == (s.get("gear", 0) <= 0.98))
    out["ok"] = all(v["ok"] for v in nd.values()) and len(nd) == 4 and out.get("adi", {}).get("ok", False) and \
        out.get("gear_handle", {}).get("ok", False) and out.get("gear_lights", {}).get("ok", False)
    RESULT[name] = out
    log(name, json.dumps(out))


MOTION = dict(on=False, pts=[])


def motion_start():
    MOTION.update(on=True, pts=[])


def motion_stop(name):
    MOTION["on"] = False
    tp = MOTION["pts"]
    p = [q[1:] for q in tp]
    d = [math.dist(p[i], p[i + 1]) for i in range(len(p) - 1)]
    v = [d[i] / (tp[i + 1][0] - tp[i][0]) for i in range(len(d)) if tp[i + 1][0] > tp[i][0]]    # cm/s per frame
    if len(d) > 5:
        m = sum(d) / len(d)
        sd = math.sqrt(sum((x - m) ** 2 for x in d) / len(d))
        acc = [abs(d[i + 1] - d[i]) for i in range(len(d) - 1)]
        RESULT[name] = dict(frames=len(p), mean_step_cm=round(m, 1), std_step_cm=round(sd, 1), cv=round(sd / m, 3) if m else None,
                            zero_steps=sum(1 for x in d if x < 0.01 * m), mean_abs_step_change_cm=round(sum(acc) / len(acc), 1))
        RESULT[name]["steps_cm"] = [round(x) for x in d]
        RESULT[name]["dts_ms"] = [round((tp[i + 1][0] - tp[i][0]) * 1000, 1) for i in range(len(d))]
        if len(v) > 5:            # speed per frame (step / frame time): independent of frame-time jitter
            mv = sum(v) / len(v)
            RESULT[name]["speed_cv"] = round(math.sqrt(sum((x - mv) ** 2 for x in v) / len(v)) / mv, 3) if mv else None
        log(name, json.dumps(RESULT[name]))


T0 = [None]
steps = []
def at(t):
    def deco(f):
        steps.append([t, f])
        return f
    return deco

NEUTRAL = {"ail": 0.0, "elev": 0.0, "rud": 0.0, "brk_l": 0.0, "brk_r": 0.0}
TUT = lambda: (C().s or {}).get("tut") or {}
SAY = lambda m: C()._send(m)
FOV = lambda v: unreal.SystemLibrary.execute_console_command(ues.get_game_world(), "fov %g" % v)


def look(p, y, fov=0):
    c = C()
    c.look_down = False
    c.look_tgt = [p, y]
    FOV(fov)


def check_displays(name):
    """the displays show the state: flight data numbers = packet, training display phase / targets, warnings list."""
    c = C()
    s = c.s
    last = c.painter.last if c.painter else {}
    L = last.get("MFD_L") or {}
    out = dict(last=last, kts=round(s["kts"]), ft=round(s["alt_m"] / 0.3048))
    out["pfd_ok"] = bool(L) and abs(L.get("kts", -999) - s["kts"]) < 8 and abs(L.get("ft", -999) - s["alt_m"] / 0.3048) < 60
    Cd = last.get("MFD_C") or {}
    out["train_ok"] = Cd.get("phase") == TUT().get("phase")
    out["disp_ms"] = round(c.disp_ms, 2)
    out["ok"] = out["pfd_ok"] and out["train_ok"]
    RESULT[name] = out
    log(name, json.dumps(out, default=str)[:600])


def check_warning_logic():
    """synthetic states through SimClient._warnings (the real flights below show the lights too)."""
    c = C()
    base = dict(c.s, paused=False, wow=False, agl_m=1800.0, alt_m=1830.0 + 10000, vs_fpm=0.0, nz=1.0, alpha=3.0, kts=350.0, gear=0.0, crashed=False)
    cases = dict(level=({}, []), stall=(dict(alpha=28.0), ["stall"]), slow=(dict(kts=105.0), ["stall"]), overg=(dict(nz=9.6), ["overg"]),
                 pullup=(dict(agl_m=120.0, vs_fpm=-4000.0), ["pullup"]), gear=(dict(agl_m=200.0, alt_m=600.0, kts=180.0, vs_fpm=-600.0), ["gear"]))
    out = {}
    saved, rr, cr = c.s, c.radar_m, c.crashed
    try:
        for n, (chg, exp) in cases.items():
            c.s = dict(base, **chg)
            c.radar_m = c.s["agl_m"]
            c.crashed = False
            w = c._warnings()
            out[n] = dict(got=w, expected=exp, ok=all(e in w for e in exp) and (bool(w) == bool(exp)))
    finally:
        c.s, c.radar_m, c.crashed = saved, rr, cr
    out["ok"] = all(v["ok"] for v in out.values() if isinstance(v, dict))
    RESULT["warning_logic"] = out
    log("warning_logic", json.dumps(out))


def panel_hidden(name):
    """the floating lesson panel is VR only (monitor: the centre training display shows the same picture)."""
    c = C()
    hid = bool(c.panel.get_editor_property("hidden")) if c.panel else None
    RESULT[name] = dict(hmd=c.hmd, panel_shown=c.panel_shown, actor_hidden=hid, ok=(not c.hmd) and not c.panel_shown and hid is not False)


def light_state():
    c = C()
    return {k: (not bool(a.get_editor_property("hidden"))) for k, a in c.lights.items()}


# ---- 0: menu at Play start ---------------------------------------------------------------------------------------
@at(0)
def menu_start():
    c = C()
    c.view, c.look_down = "cockpit", False
    c.override = dict(NEUTRAL)
    SAY({"cmd": "tut", "op": "stop"})
    SAY({"cmd": "tut", "op": "beginner", "on": True})

@at(1.5)
def c_menu():
    t = TUT()
    RESULT["menu_at_start"] = dict(phase=t.get("phase"), items=t.get("items"), paused=C().s.get("paused"), ok=t.get("phase") == "menu" and C().s.get("paused"))
    panel_hidden("panel_hidden_monitor_menu")
    look(-24.0, 0.0, 50)

@at(3)
def s_menu():
    shot("0_menu_training_display")

# ---- lesson 0 on the runway: briefing -> practice (controls) ---------------------------------------------------
@at(3.2)
def l0():
    look(0.0, 0.0)
    SAY({"cmd": "tut", "op": "start", "lesson": 0})

@at(4)
def l0_brief():
    t = TUT()
    RESULT["lesson_briefing"] = dict(phase=t.get("phase"), title=t.get("title"), text=t.get("text"), ok=t.get("phase") == "brief")
    for _ in range(int(t.get("n") or 5)):
        SAY({"cmd": "tut", "op": "next"})

@at(5.5)
def l0_practice():
    t = TUT()
    RESULT["lesson_practice_starts"] = dict(phase=t.get("phase"), instr=t.get("instr"), ok=t.get("phase") == "practice" and bool(t.get("instr")))

@at(6)
def deflect():
    C().override = {"ail": 0.7, "elev": -0.6, "rud": 0.8, "brk_l": 1.0, "brk_r": 1.0}

@at(7)
def look_down():
    C().look_down = True
    C().look_tgt = [-35.0, 0.0]

@at(9)
def c_ctrl():
    check_controls("cockpit_controls", dict(ail=0.7, elev=-0.6, rud=0.8, brk=1.0)); shot("1_cockpit_controls_lookdown")
    RESULT["light_brake"] = dict(lights=light_state(), ok=light_state().get("BRAKE") is True)

@at(9.3)
def look_left():
    C().look_tgt = [-42.0, -62.0]
    C().override = {"ail": 0.0, "elev": 0.0, "rud": 0.0, "brk_l": 0.0, "brk_r": 0.0, "thr": 0.8}

@at(11)
def c_thr():
    check_controls("cockpit_throttle", dict(ail=0.0, elev=0.0, rud=0.0, brk=0.0)); shot("1b_cockpit_throttle_left")

@at(11.3)
def look_right():
    C().look_tgt = [-30.0, 55.0]

@at(12.6)
def c_right():
    shot("1c_cockpit_right_console")

@at(12.8)
def look_up():
    C().look_down = False
    C().look_tgt = [0.0, 0.0]
    C().override = {"ail": 0.0, "elev": 0.0, "rud": 0.0, "brk_l": 1.0, "brk_r": 1.0, "thr": 0.0}

@at(14.3)
def c_tut():
    check("runway_cockpit_tutorial"); check_cockpit("cockpit_gauges_runway"); check_displays("displays_runway"); shot("2_cockpit_tutorial")

def key_state():
    c = C()
    kp = c.key_panel
    hidden = None
    if kp:
        try:
            hidden = bool(kp.is_hidden())
        except Exception:
            hidden = bool(kp.get_editor_property("hidden"))
    return dict(found=bool(kp), tex=c.keys_tex, keys_on=c.keys_on, shown=c.keys_shown, hidden=hidden)

@at(14.4)
def keys_before():
    k = key_state()                                   # default in flight: hidden (shown in the menu only)
    k["ok"] = bool(k["found"] and k["tex"] and k["shown"] is False and k["hidden"] is True)
    RESULT["key_panel_default_hidden"] = k

@at(14.5)
def panel_on():
    C().keys_on = True                                # = K

@at(15.1)
def panel_check():
    k = key_state()
    k["ok"] = bool(k["shown"] is True and k["hidden"] is False)
    RESULT["key_panel_toggle_on"] = k
    C().keys_on = False

@at(15.25)
def keys_back():
    k = key_state()
    k["ok"] = bool(k["shown"] is False and k["hidden"] is True)
    RESULT["key_panel_toggle_off"] = k

# ---- lesson 0 to the end with N -> debrief ------------------------------------------------------------------------
@at(15.4)
def l0_skip():
    SAY({"cmd": "tut", "op": "end"})

@at(16.6)
def c_debrief():
    t = TUT()
    RESULT["debrief"] = dict(phase=t.get("phase"), score=t.get("score"), ok=t.get("phase") == "debrief")
    look(-24.0, 0.0, 50)

@at(18)
def s_debrief():
    shot("2c_debrief_training_display")

# ---- lesson 2 (air): practice instruction in keyboard and rig wording, training display close-ups -----------------
@at(18.2)
def l2():
    look(0.0, 0.0)
    SAY({"cmd": "tut", "op": "start", "lesson": 2})

@at(19)
def l2_brief():
    for _ in range(int(TUT().get("n") or 4)):
        SAY({"cmd": "tut", "op": "next"})
    SAY({"cmd": "tut", "op": "next"})              # skip the demo

@at(20)
def l2_tour_skip():
    SAY({"cmd": "tut", "op": "beginner", "on": False})   # expert: tour skipped -> the hold step with targets
    C().override = dict(NEUTRAL, elev=0.06)

@at(21.5)
def l2_kbd():
    c = C()
    c.override = dict(NEUTRAL)
    while TUT().get("mode") != "kbd":
        break
    SAY({"cmd": "tut", "op": "beginner", "on": True})

@at(23)
def s_kbd():
    t = TUT()
    RESULT["instruction_kbd"] = dict(mode=t.get("mode"), instr=t.get("instr"), phase=t.get("phase"), targets=len(t.get("targets") or []),
                                     ok=t.get("phase") == "practice" and "키" in (t.get("instr") or ""))
    check_displays("displays_practice")
    shot("3a_hud_instruction_keyboard")

@at(23.3)
def s_kbd_look():
    look(-24.0, 0.0, 50)

@at(24.5)
def s_kbd_disp():
    shot("3b_training_display_keyboard")

@at(24.8)
def s_mode_rig():
    SAY({"cmd": "tut", "op": "mode"})          # auto(kbd) -> kbd forced
    SAY({"cmd": "tut", "op": "mode"})          # -> rig

@at(26)
def s_rig_disp():
    t = TUT()
    RESULT["instruction_rig"] = dict(mode=t.get("mode"), instr=t.get("instr"), ok=t.get("mode") == "rig" and "손" in (t.get("instr") or ""))
    shot("3c_training_display_rig")

@at(26.3)
def s_rig_look():
    look(-32.0, -18.0, 32)

@at(27.5)
def s_pfd():
    check_displays("displays_pfd")
    shot("3d_flight_display_closeup")

@at(27.8)
def s_pfd_look():
    look(-32.0, 18.0, 32)

@at(29)
def s_session():
    shot("3e_chair_display_closeup")

@at(29.3)
def s_session_look():
    look(-36.0, 0.0, 34)

@at(30.5)
def s_gauges():
    check_cockpit("cockpit_gauges_air")
    shot("3f_standby_gauges_beginner_labels")

@at(30.8)
def s_beg_off():
    SAY({"cmd": "tut", "op": "beginner", "on": False})

@at(31.5)
def s_expert():
    RESULT["beginner_labels_off"] = dict(hidden=[bool(a.get_editor_property("hidden")) for a in C().beg_labels][:3], ok=all(bool(a.get_editor_property("hidden")) for a in C().beg_labels) and bool(C().beg_labels))
    shot("3g_standby_gauges_expert")

@at(31.8)
def s_expert_look():
    look(0.0, 0.0)
    SAY({"cmd": "tut", "op": "mode"})          # rig -> auto

@at(32.5)
def s_hud_expert():
    shot("3h_hud_expert")

@at(32.8)
def s_beg_on():
    SAY({"cmd": "tut", "op": "beginner", "on": True})

@at(33.5)
def s_hud_beginner():
    shot("3i_hud_beginner")
    check_warning_logic()

# ---- free flight: warnings for real (hard pull = over-G), motion smoothness, bank, chase, clouds -------------------
@at(34)
def free():
    c = C()
    c.override = dict(NEUTRAL)
    SAY({"cmd": "tut", "op": "free"})

@at(37)
def c_air():
    check("air_cockpit_level"); shot("4a_cockpit_air_hud")

@at(37.6)
def m0():
    motion_start()

@at(39)
def m1():
    motion_stop("motion_interp_on"); C().no_interp = True; motion_start()

@at(41)
def m2():
    motion_stop("motion_interp_off"); C().no_interp = False

@at(41.5)
def bank():
    C().override = {"ail": 0.35, "elev": -0.15, "rud": 0.0}

@at(43)
def unbank():
    C().override = {"ail": 0.0, "elev": -0.1, "rud": 0.0}

@at(44.5)
def c_bank():
    check("air_cockpit_banked"); shot("4b_cockpit_banked")

@at(44.7)
def look_inst():
    C().look_tgt = [-36.0, 0.0]

@at(46.2)
def c_inst():
    check_cockpit("cockpit_gauges_banked"); shot("4c_cockpit_instruments_banked")

@at(46.4)
def gear_up_approach():
    """real warning: approach start (gear up, 180 kt), idle and a gentle descent -> below 190 kt sinking (F-16 gear warning) -> GEAR + master caution."""
    c = C()
    c.look_tgt = [-24.0, 0.0]
    SAY({"cmd": "reset", "mode": "approach"})
    c.override = {"ail": 0.0, "elev": 0.04, "rud": 0.0, "gear": 0.0, "thr": 0.0}

@at(49.5)
def hold_sink():
    C().override = {"ail": 0.0, "elev": 0.04, "rud": 0.0, "gear": 0.0, "thr": 0.0}

@at(56)
def c_warn():
    c = C()
    RESULT["warning_real_gear"] = dict(agl_m=round(c.s.get("agl_m", 0)), kts=round(c.s.get("kts", 0)), warnings=list(c.warnings), lights=light_state(),
                                       ok=("gear" in c.warnings) and light_state().get("MC") is True)
    shot("5_warning_gear_active")

@at(56.3)
def recover():
    C().override = dict(NEUTRAL)
    SAY({"cmd": "tut", "op": "free"})

@at(59)
def c_clear():
    RESULT["warning_clears"] = dict(warnings=list(C().warnings), lights=light_state(), ok=not C().warnings and light_state().get("MC") is False)
    look(8.0, -35.0)

@at(60.5)
def s_clouds():
    shot("6a_clouds_from_cockpit")

@at(60.8)
def s_to_chase():
    look(0.0, 0.0)
    C().view = "chase"; C().chase_yaw = None

@at(63.5)
def c_chase():
    check("air_chase"); shot("6b_chase_near_clouds")
    panel_hidden("panel_hidden_monitor_chase")

@at(63.8)
def s_to_runway():
    C().view = "cockpit"
    SAY({"cmd": "reset", "mode": "runway"})

@at(67.5)
def c_rw():
    C().view = "chase"; C().chase_yaw = None

@at(70.5)
def c_rw2():
    check("runway_chase"); shot("7_chase_runway")

@at(70.8)
def s_rw_back():
    C().view = "cockpit"

# ---- third-person views (V cycle, orbit by mouse / keys, flyby / tower fixed points, HUD hidden outside the
# cockpit, VR comfort: no camera pitch / roll, static flyby / tower) -------------------------------------------------
VW = {}


def cam_rel():
    """camera minus the aircraft: (distance m, azimuth deg, elevation deg) + camera rotation."""
    c = C()
    a, k = c.aircraft.get_actor_location(), c.camera.get_actor_location()
    d = unreal.Vector(k.x - a.x, k.y - a.y, k.z - a.z)
    r = c.camera.get_actor_rotation()
    h = math.hypot(d.x, d.y)
    return dict(dist_m=round(math.sqrt(h * h + d.z * d.z) / 100.0, 2), az=round(math.degrees(math.atan2(d.y, d.x)), 2),
                el=round(math.degrees(math.atan2(d.z, h)), 2), rot=[round(r.roll, 2), round(r.pitch, 2), round(r.yaw, 2)],
                cam=[round(k.x), round(k.y), round(k.z)], fov=round(c.fov_set or 0, 2))


def outside_ok(name, extra_ok=True, **kw):
    c = C()
    hud_hidden = bool(c.screens["HUD"][0].get_editor_property("hidden")) if "HUD" in c.screens else None
    beg_hidden = all(bool(a.get_editor_property("hidden")) for a in c.beg_labels) if c.beg_labels else True
    r = dict(view=c.view, **cam_rel(), hud_hidden=hud_hidden, beginner_labels_hidden=beg_hidden, **kw)
    r["ok"] = bool(extra_ok) and hud_hidden is True and beg_hidden and c.view != "cockpit"
    RESULT[name] = r
    log(name, json.dumps(r, default=str))
    return r

@at(70.9)
def v_setup():
    c = C()
    SAY({"cmd": "tut", "op": "free"})
    SAY({"cmd": "reset", "mode": "air"})
    c.override = dict(NEUTRAL, thr=0.75)
    c.set_view("cockpit")

@at(73.0)
def v_cycle():
    c = C()
    seq = []
    for _ in range(5):
        c.cycle_view(1)
        seq.append(c.view)
    c.cycle_view(-1)
    back = c.view
    RESULT["view_cycle"] = dict(forward=seq, shift_v_back_from_cockpit=back,
                                ok=seq == ["chase", "orbit", "flyby", "tower", "cockpit"] and back == "tower")
    c.set_view("chase")

@at(74.5)
def v_chase():
    r = cam_rel()
    a = C().aircraft.get_actor_rotation()
    behind = abs(((r["az"] - (a.yaw + 180.0)) + 180) % 360 - 180)
    outside_ok("view_chase", abs(r["dist_m"] - 26.8) < 3.0 and behind < 15.0, behind_err_deg=round(behind, 1))
    shot("9a_view_chase")

@at(74.8)
def v_orbit():
    C().set_view("orbit")

@at(76.0)
def v_orbit0():
    VW["o0"] = cam_rel()
    a = C().aircraft.get_actor_rotation()
    VW["side_err"] = abs(((VW["o0"]["az"] - (a.yaw + 90.0)) + 180) % 360 - 180)      # starts on the right side
    C().apply_mouse(240.0, 0.0, 2.0)          # drag 240 px right (= 60 deg) + 2 wheel notches closer

@at(77.0)
def v_orbit1():
    o0, o1 = VW["o0"], cam_rel()
    daz = (o1["az"] - o0["az"] + 180) % 360 - 180
    ratio = o1["dist_m"] / o0["dist_m"]
    outside_ok("view_orbit_mouse", VW["side_err"] < 15.0 and abs(daz - 60.0) < 4.0 and abs(ratio - 0.87 ** 2) < 0.03,
               start_side_err_deg=round(VW["side_err"], 1), drag_turn_deg=round(daz, 1), wheel_dist_ratio=round(ratio, 3))
    C().orbit_vel = [70.0, 45.0, 0.0]          # = holding E + PageUp (keys are read only with the editor focused)
    VW["o1"] = o1

@at(78.0)
def v_orbit_keys():
    c = C()
    c.orbit_vel = [0.0, 0.0, 0.0]
    o2 = cam_rel()
    daz = (o2["az"] - VW["o1"]["az"] + 180) % 360 - 180
    RESULT["view_orbit_keys"] = dict(turn_deg=round(daz, 1), el_from=VW["o1"]["el"], el_to=o2["el"],
                                     ok=50.0 < daz < 90.0 and o2["el"] - VW["o1"]["el"] > 25.0)
    shot("9b_view_orbit")
    c.reset_orbit()

@at(78.3)
def v_flyby():
    VW["fb_n"] = getattr(C(), "flyby_n", 0)
    C().set_view("flyby")

@at(79.0)
def v_flyby0():
    VW["fb0"] = cam_rel()

@at(79.6)
def v_flyby1():
    c = C()
    f1 = cam_rel()
    still = f1["cam"] == VW["fb0"]["cam"]
    closer = f1["dist_m"] < VW["fb0"]["dist_m"]
    outside_ok("view_flyby", still and closer and f1["fov"] < 75.0, static_point=still, aircraft_closing=closer,
               dist_m_from=VW["fb0"]["dist_m"], placed=getattr(c, "flyby_n", 0) - VW["fb_n"])
    shot("9c_view_flyby")

@at(88.0)
def v_flyby2():
    c = C()
    n = getattr(c, "flyby_n", 0) - VW["fb_n"]
    RESULT["view_flyby_replaced_after_pass"] = dict(placed=n, now=cam_rel(), ok=n >= 2)
    c.set_view("tower")

@at(89.0)
def v_tower():
    c = C()
    t0 = cam_rel()
    f = c._frame
    s = c.s
    exp = f.world(sim_client.TOWER_LL[0], sim_client.TOWER_LL[1], s["field_m"] + s["geoid_n"] + sim_client.TOWER_AGL_M)
    err = math.dist(t0["cam"], exp) / 100.0
    outside_ok("view_tower", err < 1.0 and t0["fov"] < 75.0, tower_err_m=round(err, 2))
    shot("9d_view_tower")

@at(89.3)
def v_vr():
    """VR comfort (flag forced, no headset): the rig gets yaw only, flyby / tower do not move or turn."""
    c = C()
    c.hmd, c.hmd_check_t = True, time.perf_counter() + 3600.0
    VW["vr"] = {}
    VW["vr_views"] = ["chase", "orbit", "flyby", "tower"]
    c.set_view("chase")

def _vr_sample(v):
    c = C()
    r = cam_rel()
    VW["vr"].setdefault(v, []).append(r)

@at(90.0)
def v_vr_chase():
    _vr_sample("chase"); C().set_view("orbit")

@at(90.7)
def v_vr_orbit():
    _vr_sample("orbit"); C().set_view("flyby")

@at(91.4)
def v_vr_flyby_a():
    _vr_sample("flyby")

@at(92.0)
def v_vr_flyby_b():
    _vr_sample("flyby"); C().set_view("tower")

@at(92.7)
def v_vr_tower_a():
    _vr_sample("tower")

@at(93.4)
def v_vr_tower_b():
    _vr_sample("tower")
    c = C()
    out = {}
    for v, rs in VW["vr"].items():
        out[v] = dict(rot=[r["rot"] for r in rs], ok=all(abs(r["rot"][0]) < 0.01 and abs(r["rot"][1]) < 0.01 for r in rs))
        if v in ("flyby", "tower"):
            out[v]["static"] = rs[0]["cam"] == rs[-1]["cam"] and rs[0]["rot"] == rs[-1]["rot"]
            out[v]["ok"] = out[v]["ok"] and out[v]["static"]
    RESULT["view_vr_comfort"] = dict(views=out, fov=c.fov_set, ok=all(v["ok"] for v in out.values()) and len(out) == 4 and c.fov_set == sim_client.VIEW_FOV)
    c.hmd, c.hmd_check_t = False, 0.0
    c.set_view("cockpit")

@at(95.5)
def v_back_cockpit():
    c = C()
    hud_hidden = bool(c.screens["HUD"][0].get_editor_property("hidden")) if "HUD" in c.screens else None
    RESULT["view_cockpit_hud_back"] = dict(view=c.view, hud_hidden=hud_hidden, fov=c.fov_set, ok=c.view == "cockpit" and hud_hidden is False and c.fov_set == sim_client.VIEW_FOV)

# ---- crash in free flight: dive into the ground -> red crash screen (sim frozen, input locked 1 s, buttons map to
# clicks) -> retry -> flying again from the same start ------------------------------------------------------------
@at(97)
def crash_setup():
    c = C()
    SAY({"cmd": "tut", "op": "free"})
    c.look_tgt = [0.0, 0.0]

@at(98.5)
def crash_dive():
    SAY({"cmd": "reset", "mode": "approach"})
    C().override = {"ail": 0.0, "elev": 0.6, "rud": 0.0, "gear": 0.0, "thr": 0.6}

CR = dict(t0=None, st=0)

def _crash_btn_click(op):
    """screen point of a button centre on the crash picture -> crash_click() (same path as a mouse click)."""
    c = C()
    u0, v0, u1, v1 = sim_client.CRASH_BTN[op]
    a = c.crash_panel
    P, fx, ry = a.get_actor_location(), a.get_actor_forward_vector(), a.get_actor_right_vector()
    du, dv = ((u0 + u1) / 2 - 0.5) * sim_client.CRASH_W, ((v0 + v1) / 2 - 0.5) * sim_client.CRASH_H
    wp = unreal.Vector(P.x + fx.x * du + ry.x * dv, P.y + fx.y * du + ry.y * dv, P.z + fx.z * du + ry.z * dv)
    pc = unreal.GameplayStatics.get_player_controller(c.world, 0)
    r = pc.project_world_location_to_screen(wp)
    r = [x for x in (r if isinstance(r, (tuple, list)) else (r,)) if not isinstance(x, bool)]
    sp = r[0]
    return dict(screen=[round(sp.x), round(sp.y)], got=c.crash_click(sp.x, sp.y))

@at(99)
def crash_seq():
    c = C()
    now = time.monotonic()
    t = TUT()
    ph = t.get("phase")
    if CR["t0"] is None:
        CR["t0"] = now
    st = CR["st"]
    if st == 0:
        if ph == "crash":
            CR.update(seen=now, st=1, sim_t=c.s.get("t"))
            CR["info"] = dict(crash=t.get("crash"), paused=c.s.get("paused"), agl_m=round(c.s.get("agl_m", 0), 1), vs=round(c.s.get("vs_fpm", 0)))
            SAY({"cmd": "tut", "op": "retry"})                  # inside the 1 s lock: must be ignored
        elif now - CR["t0"] > 30:
            RESULT["crash_screen"] = dict(ok=False, error="no crash within 30 s", phase=ph, agl_m=c.s.get("agl_m"))
            CR["st"] = 9
    elif st == 1 and now - CR["seen"] > 0.6:
        hid = [bool(a.get_editor_property("hidden")) for a in (c.crash_back, c.crash_panel) if a]
        CR["shown"] = dict(crash_shown=c.crash_shown, actors_hidden=hid, ok=bool(c.crash_shown) and hid == [False, False])
        CR["locked"] = dict(phase=ph, ok=ph == "crash")
        CR["frozen"] = dict(sim_t0=CR["sim_t"], sim_t=c.s.get("t"), paused=c.s.get("paused"), ok=bool(c.s.get("paused")) and c.s.get("t") == CR["sim_t"])
        try:
            CR["click"] = dict(retry=_crash_btn_click("retry"), menu=_crash_btn_click("menu"))
            CR["click"]["ok"] = CR["click"]["retry"]["got"] == "retry" and CR["click"]["menu"]["got"] == "menu"
        except Exception as e:
            CR["click"] = dict(ok=False, error=repr(e))
        shot("8_crash_red_screen")
        CR["st"] = 2
    elif st == 2 and now - CR["seen"] > 1.6:
        c.override = dict(NEUTRAL)
        SAY({"cmd": "tut", "op": "retry"})
        CR.update(st=3, t_retry=now)
    elif st == 3 and now - CR["t_retry"] > 1.5:
        CR["t1"] = c.s.get("t")
        CR["st"] = 4
    elif st == 4 and now - CR["t_retry"] > 2.5:
        hid = [bool(a.get_editor_property("hidden")) for a in (c.crash_back, c.crash_panel) if a]
        again = dict(phase=ph, paused=c.s.get("paused"), mode=c.s.get("mode"), sim_t=[CR["t1"], c.s.get("t")], alt_ft=round(c.s.get("alt_m", 0) / 0.3048),
                     actors_hidden=hid)
        again["ok"] = ph == "free" and not c.s.get("paused") and c.s.get("t", 0) > (CR["t1"] or 0) and c.s.get("mode") == "approach" and all(hid)
        RESULT["crash_screen"] = dict(info=CR["info"], shown=CR["shown"], input_lock=CR["locked"], frozen=CR["frozen"], click=CR["click"],
                                      flying_again=again,
                                      ok=all(CR[k]["ok"] for k in ("shown", "locked", "frozen", "click")) and again["ok"])
        log("crash_screen", json.dumps(RESULT["crash_screen"], ensure_ascii=False, default=str))
        CR["st"] = 9
    if CR["st"] != 9:
        steps.insert(0, [time.monotonic() - T0[0] + 0.1, crash_seq])

@at(99.5)
def finish():
    c = C()
    c.override = None
    c.view = "cockpit"
    FOV(0)
    SAY({"cmd": "tut", "op": "stop"})
    with open(os.path.join(OUT, "verify_result.json"), "w", encoding="utf-8") as f:
        json.dump(dict(made=time.strftime("%Y-%m-%d %H:%M:%S"), checks=RESULT), f, indent=1, ensure_ascii=False, default=str)
    log("done ->", OUT)

@at(101.5)
def stop_pie():
    les.editor_request_end_play()
    log("PIE stopped")


state = dict(t_start=time.monotonic(), pie=False, handle=None, frames=0)
WAIT_S = float(os.environ.get("GYROSIM_VERIFY_WAIT", "45"))      # let shaders / DDC settle first


def tick(dt):
    try:
        state["frames"] += 1
        now = time.monotonic()
        if not state["pie"]:
            if now - state["t_start"] > WAIT_S:
                log("begin PIE after", round(now - state["t_start"]), "s, frames", state["frames"])
                les.editor_request_begin_play()
                state["pie"] = True
            return
        c = C()
        if T0[0] is None:
            if ues.get_game_world() is not None and c and c.aircraft is not None and c.s is not None and c.startup_done:
                T0[0] = now
                RESULT["startup"] = {k: v for k, v in c.start.items() if k != "dts"}
                log("PIE world up, client bound, startup done", json.dumps(RESULT["startup"]))
            return
        if dt > 0.5:                     # editor hitch (shader compile, screenshot): shift the timeline, don't skip steps
            T0[0] += dt
            log("hitch %.1f s - timeline shifted" % dt)
        if MOTION["on"] and c.aircraft:
            l = c.aircraft.get_actor_location()
            MOTION["pts"].append((time.perf_counter(), l.x, l.y, l.z))
        el = now - T0[0]
        while steps and el >= steps[0][0]:
            t, f = steps.pop(0)
            f()
        if not steps:
            unreal.unregister_slate_post_tick_callback(state["handle"])
    except Exception as e:
        import traceback
        log("error", repr(e), " | ".join(traceback.format_exc().splitlines()))
        unreal.unregister_slate_post_tick_callback(state["handle"])


if C() is None:
    sim_client.start()
state["handle"] = unreal.register_slate_post_tick_callback(tick)
log("scheduled; PIE in", WAIT_S, "s")
