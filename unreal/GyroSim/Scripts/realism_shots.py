"""Cockpit realism screenshots (developer use): the same fixed views under both quality presets, for before / after
comparison of lighting / material / model work. Launch the editor with  -GyroSimShots  (init_unreal.py; label from the
GYROSIM_SHOTS_LABEL environment variable, default 'run') or exec inside the open editor. Needs sim/server.py running.
Writes Saved/verify/realism/<label>/<preset>_<view>.png and shots.json. If GYROSIM_FPS_LABEL is set too, the GPU
measurement (measure_fps.py) runs right after, in the same editor session.
Views (all with the instructor stopped, beginner labels on): air level flight heading 000 (sun front-left, 38 deg up):
hud, lookdown, left console, right console, sun side (canopy glass toward the sun); runway 06R: lookdown, chase.
"""
import json, os, time
import unreal
import sim_client

log = lambda *a: unreal.log("[shots] " + " ".join(str(x) for x in a))
les = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
ues = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem)
LABEL = os.environ.get("GYROSIM_SHOTS_LABEL", "run")
OUT = os.path.join(unreal.Paths.project_saved_dir(), "verify", "realism", LABEL)
os.makedirs(OUT, exist_ok=True)
C = sim_client.client
SAY = lambda m: C()._send(m)
NEUTRAL = {"ail": 0.0, "elev": 0.0, "rud": 0.0, "brk_l": 0.0, "brk_r": 0.0, "thr": 0.75}
# (name, mode, view, look pitch, look yaw, look_down)
VIEWS = [("hud", "air", "cockpit", 0.0, 0.0, False), ("lookdown", "air", "cockpit", -35.0, 0.0, True),
         ("left", "air", "cockpit", -42.0, -62.0, False), ("right", "air", "cockpit", -30.0, 55.0, False),
         ("sun", "air", "cockpit", 22.0, -38.0, False),
         ("rw_lookdown", "runway", "cockpit", -35.0, 0.0, True), ("rw_chase", "runway", "chase", 0.0, 0.0, False)]
PRESETS = os.environ.get("GYROSIM_SHOTS_PRESETS", "monitor,vr").split(",")
ST = dict(t=time.monotonic(), pie=False, i=0, phase="wait_pie", h=None, mode=None, shots=[])


def cmd(c):
    unreal.SystemLibrary.execute_console_command(ues.get_game_world(), c)


def jobs():
    out = []
    for p in PRESETS:
        for v in VIEWS:
            out.append((p,) + v)
    return out


JOBS = jobs()


def tick(dt):
    try:
        now = time.monotonic()
        el = now - ST["t"]
        c = C()
        ph = ST["phase"]
        if ph == "wait_pie":
            if el > float(os.environ.get("GYROSIM_SHOTS_WAIT", "45")):
                les.editor_request_begin_play()
                ST.update(phase="wait_world", t=now)
        elif ph == "wait_world":
            if ues.get_game_world() is not None and c and c.aircraft is not None and c.s is not None and getattr(c, "startup_done", True):
                SAY({"cmd": "tut", "op": "stop"})
                SAY({"cmd": "tut", "op": "beginner", "on": True})
                ST.update(phase="setup", t=now)
        elif ph == "setup" and el > 1.0:
            if ST["i"] >= len(JOBS):
                ST.update(phase="end", t=now)
                return
            preset, name, mode, view, lp, ly, ld = JOBS[ST["i"]]
            if c.preset != preset:
                sim_client.apply_preset(preset, ues.get_game_world())
                c.preset = preset
                c.hmd_check_t = now + 3600.0          # keep the forced preset (no headset)
            if ST["mode"] != (preset, mode):
                SAY({"cmd": "reset", "mode": mode})
                SAY({"cmd": "tut", "op": "free"})
                ST["mode"] = (preset, mode)
                ST["settle"] = 4.0
            else:
                ST["settle"] = 1.6
            c.override = dict(NEUTRAL, thr=0.0, brk_l=1.0, brk_r=1.0) if mode == "runway" else dict(NEUTRAL)
            c.view, c.chase_yaw = view, None
            c.look_down = ld
            c.look_tgt = [lp, ly]
            ST.update(phase="settle", t=now)
        elif ph == "settle" and el > ST["settle"]:
            preset, name = JOBS[ST["i"]][:2]
            fn = os.path.join(OUT, "%s_%s.png" % (preset, name)).replace("\\", "/")
            cmd("HighResShot 1600x900 filename=%s" % fn)
            ST["shots"].append(dict(file=os.path.basename(fn), preset=preset, view=name, alt_m=round(c.s.get("alt_m", 0), 1),
                                    psi=round(c.s.get("psi", 0), 1)))
            log("shot", fn)
            ST["i"] += 1
            ST.update(phase="setup", t=now)
        elif ph == "end" and el > 1.5:
            c.override = None
            c.look_down, c.look_tgt, c.view = False, [0.0, 0.0], "cockpit"
            c.hmd_check_t = 0.0
            sim_client.apply_preset("monitor", ues.get_game_world())
            c.preset = "monitor"
            with open(os.path.join(OUT, "shots.json"), "w") as f:
                json.dump(dict(label=LABEL, made=time.strftime("%Y-%m-%d %H:%M:%S"), shots=ST["shots"]), f, indent=1)
            les.editor_request_end_play()
            unreal.unregister_slate_post_tick_callback(ST["h"])
            log("done ->", OUT)
            if os.environ.get("GYROSIM_FPS_LABEL"):
                ST2 = dict(t=time.monotonic(), h=None)

                def _later(dt2):                   # give PIE a moment to shut down, then measure
                    if time.monotonic() - ST2["t"] < 8.0:
                        return
                    unreal.unregister_slate_post_tick_callback(ST2["h"])
                    p = os.path.join(unreal.Paths.project_dir(), "Scripts", "measure_fps.py")
                    exec(compile(open(p, encoding="utf-8").read(), p, "exec"), {"__name__": "gyrosim_fps"})
                ST2["h"] = unreal.register_slate_post_tick_callback(_later)
    except Exception as e:
        import traceback
        log("error", repr(e), " | ".join(traceback.format_exc().splitlines()))
        unreal.unregister_slate_post_tick_callback(ST["h"])


if C() is None:
    sim_client.start()
ST["h"] = unreal.register_slate_post_tick_callback(tick)
log("scheduled", len(JOBS), "shots ->", OUT)
