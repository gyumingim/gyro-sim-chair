# Runs automatically when the GyroSim project opens in the Unreal editor (PythonScriptPlugin).
# Starts the UDP client that moves the aircraft/camera from sim/server.py during Play-In-Editor.
import unreal
_cmd = unreal.SystemLibrary.get_command_line().lower()
try:
    if "-run=" in _cmd:          # commandlet (e.g. build_level.py): no client
        raise ImportError("commandlet - client not started")
    import sim_client
    sim_client.start()
except ImportError as e:
    unreal.log("[sim_client] %s" % e)
except Exception as e:
    unreal.log_error("[sim_client] failed to start: %r" % (e,))

# Automated check (developer use): launch the editor with  -GyroSimVerify  to run Scripts/verify_pie.py once the
# editor is up (-ExecutePythonScript would quit the editor afterwards, so it is not used).
if "-gyrosimverify" in _cmd:
    import os
    _p = os.path.join(unreal.Paths.project_dir(), "Scripts", "verify_pie.py")
    exec(compile(open(_p, encoding="utf-8").read(), _p, "exec"), {"__name__": "gyrosim_verify"})

# GPU / frame-time measurement (developer use): launch with  -GyroSimFps  (Scripts/measure_fps.py; label from the
# GYROSIM_FPS_LABEL environment variable). Leaves the editor open like -GyroSimVerify.
if "-gyrosimfps" in _cmd:
    import os, time
    _fps = dict(t=time.monotonic(), h=None)

    def _fps_start(dt):                     # wait 45 s (shaders / DDC settle), then run the measurement once
        if time.monotonic() - _fps["t"] < 45.0:
            return
        unreal.unregister_slate_post_tick_callback(_fps["h"])
        _p = os.path.join(unreal.Paths.project_dir(), "Scripts", "measure_fps.py")
        exec(compile(open(_p, encoding="utf-8").read(), _p, "exec"), {"__name__": "gyrosim_fps"})
    _fps["h"] = unreal.register_slate_post_tick_callback(_fps_start)
