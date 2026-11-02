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
