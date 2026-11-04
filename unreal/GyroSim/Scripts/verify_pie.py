"""Automated check, run when the editor starts with:  UnrealEditor.exe GyroSim.uproject -GyroSimVerify  (see init_unreal.py)
or inside the open editor:  exec(open(r"<project>/Scripts/verify_pie.py").read())
Starts PIE (monitor mode), checks: aircraft follows sim/server.py, roll/pitch sign convention, cockpit controls follow
the control values, tutorial panel shows, key guide panel shows and toggles (K), interpolation smoothness (per-frame motion with / without interpolation).
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

@at(0)
def lesson1():
    c = C()
    c.view, c.look_down = "cockpit", False
    c.override = dict(NEUTRAL)
    c._send({"cmd": "tut", "op": "start", "lesson": 1})

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
    check("runway_cockpit_tutorial"); check_cockpit("cockpit_gauges_runway"); shot("2_cockpit_tutorial")

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
    k = key_state()
    k["ok"] = bool(k["found"] and k["tex"] and k["shown"] is True and k["hidden"] is False)
    RESULT["key_panel_visible"] = k

@at(14.5)
def panel_off():
    C().panel_on = False                  # H key: tutorial panel off
    C().keys_on = False                   # K key: key guide panel off

@at(15.1)
def panel_check():
    c = C()
    RESULT["panel_toggle"] = dict(panel_on=c.panel_on, panel_shown=c.panel_shown, ok=c.panel_shown is False)
    k = key_state()
    k["ok"] = bool(k["shown"] is False and k["hidden"] is True)
    RESULT["key_panel_toggle_off"] = k
    c.panel_on = True
    c.keys_on = True

@at(15.25)
def keys_back():
    k = key_state()
    k["ok"] = bool(k["shown"] is True and k["hidden"] is False)
    RESULT["key_panel_toggle_on"] = k

@at(15.3)
def air():
    c = C()
    c.override = dict(NEUTRAL)
    c._send({"cmd": "tut", "op": "stop"})
    c._send({"cmd": "reset", "mode": "air"})

@at(18.5)
def c_air():
    check("air_cockpit_level"); check_cockpit("cockpit_gauges_air"); shot("2b_cockpit_air_hud")

@at(19.1)
def m0():
    motion_start()                       # after the screenshot hitch

@at(20.5)
def m1():
    motion_stop("motion_interp_on"); C().no_interp = True; motion_start()

@at(22.5)
def m2():
    motion_stop("motion_interp_off"); C().no_interp = False

@at(23)
def bank():
    C().override = {"ail": 0.35, "elev": -0.15, "rud": 0.0}

@at(24.5)
def unbank():
    C().override = {"ail": 0.0, "elev": -0.1, "rud": 0.0}

@at(26.5)
def c_bank():
    check("air_cockpit_banked"); shot("3_cockpit_banked")

@at(26.7)
def look_inst():
    C().look_tgt = [-36.0, 0.0]

@at(28.2)
def c_inst():
    check_cockpit("cockpit_gauges_banked"); shot("3b_cockpit_instruments_banked")

@at(28.4)
def look_fwd():
    C().look_tgt = [0.0, 0.0]

@at(29)
def chase():
    C().view = "chase"; C().chase_yaw = None

@at(32)
def c_chase():
    check("air_chase_banked"); shot("4_chase_banked")

@at(33)
def lesson5():
    c = C()
    c.override = dict(NEUTRAL)
    c._send({"cmd": "tut", "op": "start", "lesson": 5})

@at(39)
def c_rw():
    check("runway_chase"); shot("5_chase_runway")

@at(40)
def cockpit_rw():
    C().view = "cockpit"

@at(43)
def c_rw2():
    check("runway_cockpit_lesson5"); shot("6_cockpit_runway_lesson5")

@at(44)
def finish():
    c = C()
    c.override = None
    c.view = "cockpit"
    c._send({"cmd": "tut", "op": "stop"})
    c._send({"cmd": "reset", "mode": "air"})
    with open(os.path.join(OUT, "verify_result.json"), "w", encoding="utf-8") as f:
        json.dump(dict(made=time.strftime("%Y-%m-%d %H:%M:%S"), checks=RESULT), f, indent=1, ensure_ascii=False)
    log("done ->", OUT)

@at(46)
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
        log("error", repr(e))
        unreal.unregister_slate_post_tick_callback(state["handle"])


if C() is None:
    sim_client.start()
state["handle"] = unreal.register_slate_post_tick_callback(tick)
log("scheduled; PIE in", WAIT_S, "s")
