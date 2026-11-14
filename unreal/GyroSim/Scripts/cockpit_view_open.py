"""Open /Game/Maps/CockpitView for looking at the cockpit v2 (CockpitView.bat): the editor viewport camera goes to the pilot
eye (the SimView camera actor), Game View on, the canopy / cockpit paint dynamic instances of view_fx (as at Play; in memory
only, so the level shows as changed - do not save it on close), the sim's monitor render settings (sim_client.PRESETS 'monitor' + atmos_look cvars, Lumen GI
on as in the sim), then light on the GPU: t.MaxFPS 30, r.ScreenPercentage 75. No Play, nothing is saved.
Env (tests): GYROSIM_CKVIEW_SHOT = png -> one 1280x720 shot from the eye camera, GYROSIM_CKVIEW_QUIT=1 -> quit after it.
"""
import os, sys, time
import unreal

DST = "/Game/Maps/CockpitView"
ues = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem)
les = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
log = lambda *a: unreal.log("[ckview] " + " ".join(str(x) for x in a))
ST = dict(t=time.monotonic(), phase="wait", h=None)
PY = os.path.join(unreal.Paths.project_dir(), "Content", "Python")
if PY not in sys.path:
    sys.path.insert(0, PY)


def cmd(c):
    unreal.SystemLibrary.execute_console_command(ues.get_editor_world(), c)


def eye():
    c = unreal.GameplayStatics.get_all_actors_with_tag(ues.get_editor_world(), "SimView")
    return c[0] if c else None


def settings():
    try:
        import sim_client, atmos_look
        for k, v in list(sim_client.PRESETS["monitor"].items()) + list(atmos_look.AIR["cvars"]["monitor"].items()):
            cmd("%s %s" % (k, v))
    except Exception as e:
        log("cvars", repr(e))
    cmd("t.MaxFPS 30"); cmd("r.ScreenPercentage 75"); cmd("r.VSync 0")


def canopy_tick(now):
    """11-14: keep calling view_fx's canopy() (it throttles itself to 1 s) until the interior cube is baked, as the sim
    does every frame: one call at open (before) set the capture up but never baked it (the bake waits CUBE_DELAY s),
    so CockpitView showed the canopy reflection without the cockpit in it."""
    fx = ST.get("fx")
    if fx is None:
        return
    try:
        fx.canopy(ues.get_editor_world(), now)
    except Exception as e:
        log("canopy look", repr(e)); ST["fx"] = None; return
    if getattr(fx, "cube_baked", False) or now - ST["fx_t0"] > 60.0 or (now - ST["fx_t0"] > 5.0 and not getattr(fx, "cube_wanted", False)):
        log("canopy interior cube", "baked" if getattr(fx, "cube_baked", False) else "not baked (reflection off or no capture)")
        ST["fx"] = None


def tick(dt):
    try:
        now = time.monotonic()
        canopy_tick(now)
        el = now - ST["t"]
        ph = ST["phase"]
        if ph == "wait" and el > 3.0:
            w = ues.get_editor_world()
            if w is None or not w.get_path_name().startswith(DST + "."):
                if el > 60.0:
                    les.load_level(DST); ST["t"] = now
                return
            settings()
            c = eye()
            if c:
                ues.set_level_viewport_camera_info(c.get_actor_location(), c.get_actor_rotation())
                log("viewport at the eye", c.get_actor_location())
            try:                                     # canopy scratch glints / cockpit paint as at Play (view_fx dynamic
                import view_fx                       # instances; in memory only - the level asset keeps the plain ones)
                ST["fx"], ST["fx_t0"] = view_fx.ViewFx(), now
                ST["fx"].canopy(w, now)
            except Exception as e:
                log("canopy look", repr(e))
            try:
                les.editor_set_game_view(True)       # no editor icons, hidden-in-game actors hidden (as in the sim)
            except Exception as e:
                log("game view", repr(e))
            ST.update(phase="again", t=now)
        elif ph == "again" and el > 5.0:            # once more: the viewport may still have been coming up
            settings()
            c = eye()
            if c:
                ues.set_level_viewport_camera_info(c.get_actor_location(), c.get_actor_rotation())
            ST.update(phase="shot" if os.environ.get("GYROSIM_CKVIEW_SHOT") else "done", t=now)
        elif ph == "shot" and el > 4.0:
            ST.update(phase="shoot", t=now)
            les.pilot_level_actor(eye())                # the eye camera's own FOV (75 deg) for the test shot only
        elif ph == "shoot" and el > 8.0:
            ST.update(phase="after_shot", t=now)       # before the command: it can tick us again
            fn = os.environ["GYROSIM_CKVIEW_SHOT"].replace("\\", "/")
            cmd("HighResShot 1280x720 filename=%s" % fn)
            log("shot", fn)
        elif ph == "after_shot" and el > 8.0:
            les.eject_pilot_level_actor()
            ST.update(phase="done", t=now)
        elif ph == "done" and ST.get("fx") is None:     # (after the interior cube bake)
            unreal.unregister_slate_post_tick_callback(ST["h"])
            log("ready")
            if os.environ.get("GYROSIM_CKVIEW_QUIT") == "1":
                unreal.SystemLibrary.quit_editor()
    except Exception as e:
        import traceback
        log("error", repr(e), " | ".join(traceback.format_exc().splitlines()[-4:]))
        unreal.unregister_slate_post_tick_callback(ST["h"])


ST["h"] = unreal.register_slate_post_tick_callback(tick)
log("open scheduled")
