"""Automated check, run when the editor starts with:  UnrealEditor.exe GyroSim.uproject -GyroSimVerify  (see init_unreal.py)
or inside the open editor:  exec(open(r"<project>/Scripts/verify_pie.py").read())
Starts PIE (monitor mode), checks: aircraft follows sim/server.py, roll/pitch sign convention, cockpit controls follow
the control values, tutorial panel shows, interpolation smoothness (per-frame motion with / without interpolation).
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
    st = out.get("StickPivot", {}).get("rot", [0, 0])
    out["stick_ok"] = abs(st[0] - 18 * exp["ail"]) < 2 and abs(st[1] + 14 * exp["elev"]) < 2
    out["pedal_ok"] = abs(out.get("PedalR", {}).get("dx", 0) - 6 * exp["rud"]) < 1 and abs(out.get("PedalL", {}).get("dx", 0) + 6 * exp["rud"]) < 1
    out["brake_ok"] = abs(out.get("PedalL", {}).get("rot", [0, 0])[1] + 18 * exp["brk"]) < 2
    th = out.get("ThrottlePivot", {}).get("rot", [0, 0])[1]
    out["throttle_ok"] = abs(th - (25 - 50 * c.s.get("thr", 0))) < 2
    tut = c.s.get("tut") or {}
    out["tutorial"] = dict(on=tut.get("on"), lesson=tut.get("lesson"), step=tut.get("step"), text=tut.get("text"), img=tut.get("img"),
                           panel_ver=c.tut_ver, panel_shown=c.panel_shown)
    out["hud_text"] = {k: v for k, v in c.txt_cache.items()}
    RESULT[name] = out
    log(name, json.dumps(out, ensure_ascii=False))


MOTION = dict(on=False, pts=[])


def motion_start():
    MOTION.update(on=True, pts=[])


def motion_stop(name):
    MOTION["on"] = False
    p = MOTION["pts"]
    d = [math.dist(p[i], p[i + 1]) for i in range(len(p) - 1)]
    d = [x for x in d]
    if len(d) > 5:
        m = sum(d) / len(d)
        sd = math.sqrt(sum((x - m) ** 2 for x in d) / len(d))
        acc = [abs(d[i + 1] - d[i]) for i in range(len(d) - 1)]
        RESULT[name] = dict(frames=len(p), mean_step_cm=round(m, 1), std_step_cm=round(sd, 1), cv=round(sd / m, 3) if m else None,
                            zero_steps=sum(1 for x in d if x < 0.01 * m), mean_abs_step_change_cm=round(sum(acc) / len(acc), 1))
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
    C().look_tgt = [-30.0, -55.0]
    C().override = {"ail": 0.0, "elev": 0.0, "rud": 0.0, "brk_l": 0.0, "brk_r": 0.0, "thr": 0.8}

@at(11)
def c_thr():
    check_controls("cockpit_throttle", dict(ail=0.0, elev=0.0, rud=0.0, brk=0.0)); shot("1b_cockpit_throttle_left")

@at(11.3)
def look_up():
    C().look_down = False
    C().look_tgt = [0.0, 0.0]
    C().override = {"ail": 0.0, "elev": 0.0, "rud": 0.0, "brk_l": 1.0, "brk_r": 1.0, "thr": 0.0}

@at(12.8)
def c_tut():
    check("runway_cockpit_tutorial"); shot("2_cockpit_tutorial")

@at(13.2)
def air():
    c = C()
    c.override = dict(NEUTRAL)
    c._send({"cmd": "tut", "op": "stop"})
    c._send({"cmd": "reset", "mode": "air"})

@at(17)
def c_air():
    check("air_cockpit_level"); motion_start()

@at(19)
def m1():
    motion_stop("motion_interp_on"); C().no_interp = True; motion_start()

@at(21)
def m2():
    motion_stop("motion_interp_off"); C().no_interp = False

@at(21.5)
def bank():
    C().override = {"ail": 0.35, "elev": -0.15, "rud": 0.0}

@at(23)
def unbank():
    C().override = {"ail": 0.0, "elev": -0.1, "rud": 0.0}

@at(25)
def c_bank():
    check("air_cockpit_banked"); shot("3_cockpit_banked")

@at(26)
def chase():
    C().view = "chase"; C().chase_yaw = None

@at(29)
def c_chase():
    check("air_chase_banked"); shot("4_chase_banked")

@at(30)
def lesson5():
    c = C()
    c.override = dict(NEUTRAL)
    c._send({"cmd": "tut", "op": "start", "lesson": 5})

@at(36)
def c_rw():
    check("runway_chase"); shot("5_chase_runway")

@at(37)
def cockpit_rw():
    C().view = "cockpit"

@at(40)
def c_rw2():
    check("runway_cockpit_lesson5"); shot("6_cockpit_runway_lesson5")

@at(41)
def finish():
    c = C()
    c.override = None
    c.view = "cockpit"
    c._send({"cmd": "tut", "op": "stop"})
    c._send({"cmd": "reset", "mode": "air"})
    with open(os.path.join(OUT, "verify_result.json"), "w", encoding="utf-8") as f:
        json.dump(dict(made=time.strftime("%Y-%m-%d %H:%M:%S"), checks=RESULT), f, indent=1, ensure_ascii=False)
    log("done ->", OUT)

@at(43)
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
            if ues.get_game_world() is not None and c and c.aircraft is not None and c.s is not None:
                T0[0] = now
                log("PIE world up, client bound")
            return
        if dt > 0.5:                     # editor hitch (shader compile, screenshot): shift the timeline, don't skip steps
            T0[0] += dt
            log("hitch %.1f s - timeline shifted" % dt)
        if MOTION["on"] and c.aircraft:
            l = c.aircraft.get_actor_location()
            MOTION["pts"].append((l.x, l.y, l.z))
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
