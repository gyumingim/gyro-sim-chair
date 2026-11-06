"""Cockpit realism screenshots (developer use): the same fixed views under both quality presets, for before / after
comparison of lighting / material / model work. Launch the editor with  -GyroSimShots  (init_unreal.py; label from the
GYROSIM_SHOTS_LABEL environment variable, default 'run') or exec inside the open editor. Needs sim/server.py running.
Writes Saved/verify/realism/<label>/<preset>_<view>.png and shots.json. If GYROSIM_FPS_LABEL is set too, the GPU
measurement (measure_fps.py) runs right after, in the same editor session.
Views (all with the instructor stopped, beginner labels on): air level flight heading 000 (sun front-left, 38 deg up):
hud, lookdown, left console, right console, sun side (canopy glass toward the sun); runway 06R: lookdown, chase.
Realism v2 (Scripts/realism_v2.py, docs/realism-v2-plan.md): every view is taken with the v1 and the v2 values in the same
session (GYROSIM_SHOTS_V2, default 'off,on' -> <preset>_v1_<view>.png / <preset>_v2_<view>.png). GYROSIM_OFFSCREEN=1
(default) keeps the editor windows off the desktop without taking focus (busan_check.py method). GYROSIM_SHOTS_QUIT=1
quits the editor at the end (after the GPU measurement; GYROSIM_FPS_V2_AB=1 measures v2 then v1 -> fps_<label>_v1.json).
Canopy A/B (11-06): GYROSIM_SHOTS_V2 also takes 'v3' (= v2 values + canopy M_CkCanopyV3; 'on' = v2 values + the V2 canopy),
GYROSIM_CANOPY_BUILD=1 (re)builds M_CkCanopyV3 before PIE (no level rebuild), GYROSIM_FPS_STATES='v3,on' measures those
states one after another (fps_<label>.json, fps_<label>_on.json). GYROSIM_SHOTS_DIR = output folder (V-World / Busan
imagery must stay outside git: C:/GyroSimTiles/shots/...), GYROSIM_SHOTS_VIEWS = comma list of view names to keep.
"""
import json, os, time
import unreal
import sim_client
import sys
sys.path.insert(0, os.path.join(unreal.Paths.project_dir(), "Scripts"))
import realism_v2                                    # noqa: E402
realism_v2.install_hook(sim_client)
if os.environ.get("GYROSIM_OFFSCREEN", "1") == "1":
    realism_v2.keep_offscreen()

log = lambda *a: unreal.log("[shots] " + " ".join(str(x) for x in a))
les = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
ues = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem)
LABEL = os.environ.get("GYROSIM_SHOTS_LABEL", "run")
OUT = os.environ.get("GYROSIM_SHOTS_DIR") or os.path.join(unreal.Paths.project_saved_dir(), "verify", "realism", LABEL)
os.makedirs(OUT, exist_ok=True)
C = sim_client.client
SAY = lambda m: C()._send(m)
NEUTRAL = {"ail": 0.0, "elev": 0.0, "rud": 0.0, "brk_l": 0.0, "brk_r": 0.0, "thr": 0.75}
# (name, mode, view, look pitch, look yaw, look_down)
VIEWS = [("hud", "air", "cockpit", 0.0, 0.0, False), ("lookdown", "air", "cockpit", -35.0, 0.0, True),
         ("left", "air", "cockpit", -42.0, -62.0, False), ("right", "air", "cockpit", -30.0, 55.0, False),
         ("sun", "air", "cockpit", 22.0, -38.0, False),
         ("rw_lookdown", "runway", "cockpit", -35.0, 0.0, True), ("rw_chase", "runway", "chase", 0.0, 0.0, False)]
if os.environ.get("GYROSIM_SHOTS_VIEWS"):
    VIEWS = [v for v in VIEWS if v[0] in os.environ["GYROSIM_SHOTS_VIEWS"].split(",")]
PRESETS = os.environ.get("GYROSIM_SHOTS_PRESETS", "monitor,vr").split(",")
V2TOK = [x.strip() for x in os.environ.get("GYROSIM_SHOTS_V2", "off,on").split(",")]
V2STATES = [t != "off" for t in V2TOK]
TAG = {"off": "v1", "on": "v2", "v3": "v3"}


def _state(tok):
    """'off' = v1, 'on' = v2 values + V2 canopy, 'v3' = v2 values + V3 canopy."""
    realism_v2.STATE["on"] = tok != "off"
    realism_v2.STATE["canopy"] = "v3" if tok == "v3" else "v2"


if os.environ.get("GYROSIM_CANOPY_BUILD") == "1" or ("v3" in V2TOK and
                                                    not unreal.EditorAssetLibrary.does_asset_exist(realism_v2.CANOPY_V3)):
    realism_v2.build_canopy_v3()
ST = dict(t=time.monotonic(), pie=False, i=0, phase="wait_pie", h=None, mode=None, shots=[])


def cmd(c):
    unreal.SystemLibrary.execute_console_command(ues.get_game_world(), c)


def jobs():
    out = []
    for p in PRESETS:
        for tok in V2TOK:
            for v in VIEWS:
                out.append((p, tok) + v)
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
            preset, on, name, mode, view, lp, ly, ld = JOBS[ST["i"]]
            if ST.get("look") != (preset, on):
                _state(on)
                sim_client.apply_preset(preset, ues.get_game_world())     # apply_look -> realism_v2 profile (hook)
                c.preset = preset
                c.hmd_check_t = now + 3600.0          # keep the forced preset (no headset)
                ST["look"] = (preset, on)
                ST["mode"] = None                     # re-settle: exposure adaptation after a look change
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
            preset, on, name = JOBS[ST["i"]][:3]
            fn = os.path.join(OUT, "%s_%s_%s.png" % (preset, TAG.get(on, on), name)).replace("\\", "/")
            cmd("HighResShot 1600x900 filename=%s" % fn)
            ST["shots"].append(dict(file=os.path.basename(fn), preset=preset, realism=TAG.get(on, on), view=name,
                                    alt_m=round(c.s.get("alt_m", 0), 1),
                                    psi=round(c.s.get("psi", 0), 1)))
            log("shot", fn)
            ST["i"] += 1
            ST.update(phase="setup", t=now)
        elif ph == "end" and el > 1.5 and not ST.get("clip_done"):
            # HUD clip check: narrow the clip window on the live HUD material (C_Wd 34 -> 14 cm) for one shot
            ST["clip_done"] = True
            for a in unreal.GameplayStatics.get_all_actors_with_tag(ues.get_game_world(), "HUD"):
                mt = a.static_mesh_component.get_material(0)
                if isinstance(mt, unreal.MaterialInstanceDynamic):
                    for fn_ in ("k2_get_scalar_parameter_value", "get_scalar_parameter_value"):
                        try:
                            ST["clip_wd"] = getattr(mt, fn_)("C_Wd")
                            break
                        except Exception:
                            pass
                    mt.set_scalar_parameter_value("C_Wd", 14.0)
                    ST["clip_mid"] = mt
            c.view, c.look_down, c.look_tgt = "cockpit", False, [0.0, 0.0]
            ST.update(phase="clipshot", t=now)
        elif ph == "clipshot" and el > 1.5:
            fn = os.path.join(OUT, "cliptest_hud_14cm.png").replace("\\", "/")
            cmd("HighResShot 1600x900 filename=%s" % fn)
            ST["shots"].append(dict(file=os.path.basename(fn), preset=c.preset, view="cliptest"))
            ST.update(phase="clipreset", t=now)
        elif ph == "clipreset" and el > 1.5:
            if ST.get("clip_mid"):
                ST["clip_mid"].set_scalar_parameter_value("C_Wd", ST.get("clip_wd") or 33.8)
            ST.update(phase="end", t=now)
        elif ph == "end" and el > 1.5:
            c.override = None
            c.look_down, c.look_tgt, c.view = False, [0.0, 0.0], "cockpit"
            c.hmd_check_t = 0.0
            realism_v2.STATE["on"] = True
            realism_v2.STATE["canopy"] = os.environ.get("GYROSIM_CANOPY", "v3")
            sim_client.apply_preset("monitor", ues.get_game_world())
            c.preset = "monitor"
            with open(os.path.join(OUT, "shots.json"), "w") as f:
                json.dump(dict(label=LABEL, made=time.strftime("%Y-%m-%d %H:%M:%S"), shots=ST["shots"],
                               v2=dict(common=realism_v2.V2_COMMON, profile=realism_v2.V2_PROFILE, v1=realism_v2.V1)),
                          f, indent=1, default=str)
            les.editor_request_end_play()
            unreal.unregister_slate_post_tick_callback(ST["h"])
            log("done ->", OUT)
            fps_runs = []
            if os.environ.get("GYROSIM_FPS_LABEL"):
                base = os.environ["GYROSIM_FPS_LABEL"]
                fps_runs = [(base, V2TOK[-1])] + ([(base + "_v1", "off")] if os.environ.get("GYROSIM_FPS_V2_AB") == "1" else [])
                if os.environ.get("GYROSIM_FPS_STATES"):
                    fs = [t.strip() for t in os.environ["GYROSIM_FPS_STATES"].split(",")]
                    fps_runs = [(base if i == 0 else base + "_" + t, t) for i, t in enumerate(fs)]
            ST2 = dict(t=time.monotonic(), h=None, runs=fps_runs, wait=None)
            vdir = os.path.join(unreal.Paths.project_saved_dir(), "verify")

            def _later(dt2):                       # measure_fps.py runs one after another (v2, then v1), then quit
                now2 = time.monotonic()
                if ST2["wait"]:
                    fj, t0 = ST2["wait"]
                    if not (os.path.exists(fj) and os.path.getmtime(fj) > t0):
                        if now2 - ST2["t"] < 600.0:
                            return
                        log("fps timeout", fj)
                        les.editor_request_end_play()
                    ST2["wait"] = None
                    ST2["t"] = now2
                    return
                if now2 - ST2["t"] < 8.0:          # give PIE a moment to shut down
                    return
                if ST2["runs"]:
                    lbl, on = ST2["runs"].pop(0)
                    os.environ["GYROSIM_FPS_LABEL"] = lbl
                    _state(on)
                    ST2["wait"] = (os.path.join(vdir, "fps_%s.json" % lbl), time.time())
                    ST2["t"] = now2
                    p = os.path.join(unreal.Paths.project_dir(), "Scripts", "measure_fps.py")
                    exec(compile(open(p, encoding="utf-8").read(), p, "exec"), {"__name__": "gyrosim_fps"})
                    return
                unreal.unregister_slate_post_tick_callback(ST2["h"])
                realism_v2.STATE["on"] = True
                realism_v2.STATE["canopy"] = os.environ.get("GYROSIM_CANOPY", "v3")
                realism_v2.stop_offscreen()
                if os.environ.get("GYROSIM_SHOTS_QUIT") == "1":
                    log("quit")
                    unreal.SystemLibrary.quit_editor()
            ST2["h"] = unreal.register_slate_post_tick_callback(_later)
    except Exception as e:
        import traceback
        log("error", repr(e), " | ".join(traceback.format_exc().splitlines()))
        unreal.unregister_slate_post_tick_callback(ST["h"])


if C() is None:
    sim_client.start()
ST["h"] = unreal.register_slate_post_tick_callback(tick)
log("scheduled", len(JOBS), "shots ->", OUT)
