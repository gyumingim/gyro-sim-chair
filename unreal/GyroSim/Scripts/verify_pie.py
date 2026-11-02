"""Automated check, run when the editor starts with:  UnrealEditor.exe GyroSim.uproject -GyroSimVerify  (see init_unreal.py)
Starts PIE, checks the aircraft follows sim/server.py, checks the roll/pitch sign convention, takes screenshots
(cockpit, banked chase, runway chase) into Saved/Screenshots/WindowsEditor, logs '[verify]' lines, then stops PIE.
Needs sim/server.py running. Leaves the editor open.
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


def shot(name):
    w = ues.get_game_world()
    unreal.SystemLibrary.execute_console_command(w, "HighResShot 1600x900 filename=%s" % os.path.join(OUT, name + ".png").replace("\\", "/"))
    log("screenshot", name)


def check(name):
    c = sim_client.client()
    s, a = c.s, c.aircraft
    loc, rot = a.get_actor_location(), a.get_actor_rotation()
    exp, _ = sim_client.SimClient.to_world(s)
    right_z = rot.get_right_vector().z
    fwd_z = rot.get_forward_vector().z
    cam = c.camera.get_actor_location()
    pc = unreal.GameplayStatics.get_player_controller(c.world, 0)
    vt = pc.get_view_target().get_name() if pc and pc.get_view_target() else None
    cam_mgr = unreal.GameplayStatics.get_player_camera_manager(c.world, 0)
    pov = cam_mgr.get_camera_location() if cam_mgr else None
    r = dict(t=round(s["t"], 2), rx=c.rx_n, alt_m=round(s["alt_m"], 1), phi=round(s["phi"], 2), theta=round(s["theta"], 2),
             psi=round(s["psi"], 2), actor=[round(loc.x), round(loc.y), round(loc.z)], expected=[round(exp.x), round(exp.y), round(exp.z)],
             actor_rot=[round(rot.roll, 2), round(rot.pitch, 2), round(rot.yaw, 2)], right_z=round(right_z, 3), fwd_z=round(fwd_z, 3),
             cam=[round(cam.x), round(cam.y), round(cam.z)], pov=[round(pov.x), round(pov.y), round(pov.z)] if pov else None,
             view_target=vt, view=c.view, src=s.get("src"))
    # sign checks: NED phi>0 = right wing down -> right vector z < 0;  theta>0 = nose up -> forward z > 0
    r["roll_sign_ok"] = (abs(s["phi"]) < 2) or ((s["phi"] > 0) == (right_z < 0))
    r["pitch_sign_ok"] = (abs(s["theta"]) < 1) or ((s["theta"] > 0) == (fwd_z > 0))
    RESULT[name] = r
    log(name, json.dumps(r))


# timeline: (seconds after PIE start, action)
T0 = [None]
steps = []
def at(t):
    def deco(f):
        steps.append([t, f])
        return f
    return deco

@at(0)
def reset_air():
    sim_client.client().view = "cockpit"
    sim_client.client().override = {"ail": 0.0, "elev": 0.0, "rud": 0.0}
    sim_client.client()._send({"cmd": "reset", "mode": "air"})

@at(6)
def c1():
    check("air_cockpit_level"); shot("1_cockpit_level")

@at(8)
def bank():
    sim_client.client().override = {"ail": 0.35, "elev": -0.15, "rud": 0.0}

@at(9.5)
def unbank():
    sim_client.client().override = {"ail": 0.0, "elev": -0.1, "rud": 0.0}

@at(12)
def c2():
    check("air_cockpit_banked"); shot("2_cockpit_banked")

@at(13)
def chase():
    sim_client.client().view = "chase"

@at(16)
def c3():
    check("air_chase_banked"); shot("3_chase_banked")

def hide(cls, hidden=True):
    w = ues.get_game_world()
    for a in unreal.GameplayStatics.get_all_actors_of_class(w, cls):
        a.set_actor_hidden_in_game(hidden)

@at(16.2)
def d1():
    sim_client.client()._send({"cmd": "pause"}); hide(unreal.ExponentialHeightFog)

@at(16.8)
def d1s():
    shot("6_diag_nofog")

@at(17.4)
def d2():
    hide(unreal.VolumetricCloud)

@at(18.0)
def d2s():
    shot("7_diag_nofog_nocloud")

@at(18.6)
def d3():
    hide(unreal.SkyAtmosphere)

@at(19.2)
def d3s():
    shot("8_diag_nofog_nocloud_noatmo")

@at(19.5)
def d3b():
    w = ues.get_game_world()
    for l in unreal.GameplayStatics.get_all_actors_of_class(w, unreal.DirectionalLight):
        l.light_component.set_cast_shadows(False)

@at(19.75)
def d3c():
    shot("9_diag_nofog_nocloud_noatmo_noshadow")

@at(19.8)
def d4():
    w = ues.get_game_world()
    for l in unreal.GameplayStatics.get_all_actors_of_class(w, unreal.DirectionalLight):
        l.light_component.set_cast_shadows(True)
    for c in (unreal.ExponentialHeightFog, unreal.VolumetricCloud, unreal.SkyAtmosphere):
        hide(c, False)
    sim_client.client()._send({"cmd": "pause"})

@at(20.5)
def runway():
    sim_client.client().override = {"ail": 0.0, "elev": 0.0, "rud": 0.0}
    sim_client.client()._send({"cmd": "reset", "mode": "runway"})

@at(27)
def c4():
    check("runway_chase"); shot("4_chase_runway")

@at(28)
def cockpit_rw():
    sim_client.client().view = "cockpit"

@at(31)
def c5():
    check("runway_cockpit"); shot("5_cockpit_runway")

@at(33)
def finish():
    c = sim_client.client()
    c.override = None
    c.view = "cockpit"
    c._send({"cmd": "reset", "mode": "air"})
    with open(os.path.join(OUT, "verify_result.json"), "w") as f:
        json.dump(dict(made=time.strftime("%Y-%m-%d %H:%M:%S"), checks=RESULT), f, indent=1)
    log("done ->", OUT)

@at(35)
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
        c = sim_client.client()
        if T0[0] is None:
            if ues.get_game_world() is not None and c and c.aircraft is not None and c.s is not None:
                T0[0] = now
                log("PIE world up, client bound")
            return
        el = now - T0[0]
        while steps and el >= steps[0][0]:
            t, f = steps.pop(0)
            f()
        if not steps:
            unreal.unregister_slate_post_tick_callback(state["handle"])
    except Exception as e:
        log("error", repr(e))
        unreal.unregister_slate_post_tick_callback(state["handle"])


if sim_client.client() is None:
    sim_client.start()
state["handle"] = unreal.register_slate_post_tick_callback(tick)
log("scheduled; PIE in", WAIT_S, "s")
