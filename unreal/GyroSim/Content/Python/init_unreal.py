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

# Realism screenshots (developer use): launch with  -GyroSimShots  (Scripts/realism_shots.py; label from
# GYROSIM_SHOTS_LABEL, and the GPU measurement right after it when GYROSIM_FPS_LABEL is set). Leaves the editor open.
if "-gyrosimshots" in _cmd:
    import os
    _p = os.path.join(unreal.Paths.project_dir(), "Scripts", "realism_shots.py")
    exec(compile(open(_p, encoding="utf-8").read(), _p, "exec"), {"__name__": "gyrosim_shots"})

# V-World ground mode check (developer use): launch with  -GyroSimVWorld  (Scripts/vworld_check.py, needs the 'vworld'
# line in Config/cesium_token.txt and the tile proxy). Leaves the editor open.
if "-gyrosimvworld" in _cmd.replace("-gyrosimvworldterrain", "").replace("-gyrosimvworldbuildings", ""):
    import os
    _p = os.path.join(unreal.Paths.project_dir(), "Scripts", "vworld_check.py")
    exec(compile(open(_p, encoding="utf-8").read(), _p, "exec"), {"__name__": "gyrosim_vworld"})

# V-World photos on the local Copernicus DEM terrain (developer use): launch with  -GyroSimVWorldTerrain
# (Scripts/vworld_terrain_check.py: runway / Seoraksan views, camera floor, mountain crash). Leaves the editor open.
if "-gyrosimvworldterrain" in _cmd:
    import os
    _p = os.path.join(unreal.Paths.project_dir(), "Scripts", "vworld_terrain_check.py")
    exec(compile(open(_p, encoding="utf-8").read(), _p, "exec"), {"__name__": "gyrosim_vworld_terrain"})

# 3D buildings in the vworld mode (developer use): launch with  -GyroSimVWorldBuildings  (Scripts/vworld_buildings_check.py:
# downtown / apartments / footprint alignment / runway views, building crash, GPU with buildings off / on). Leaves the editor open.
if "-gyrosimvworldbuildings" in _cmd:
    import os
    _p = os.path.join(unreal.Paths.project_dir(), "Scripts", "vworld_buildings_check.py")
    exec(compile(open(_p, encoding="utf-8").read(), _p, "exec"), {"__name__": "gyrosim_vworld_buildings"})

# Busan start (developer use): server with  --start rkpk  in the vworld mode, launch with  -GyroSimBusan
# (Scripts/busan_check.py: RKPK runway cockpit / side, 300 m over Busan, Haeundae, Seomyeon top-down; windows kept off-screen,
# shots outside git in C:/GyroSimTiles/shots/busan). Quits the editor when done (GYROSIM_BUSAN_QUIT=0 keeps it).
if "-gyrosimbusan" in _cmd:
    import os
    _p = os.path.join(unreal.Paths.project_dir(), "Scripts", "busan_check.py")
    exec(compile(open(_p, encoding="utf-8").read(), _p, "exec"), {"__name__": "gyrosim_busan"})

# One-step play (GyroSim_Busan.bat at the repo root): launch with  -GyroSimPlay  -> Play (new window, maximized by
# sim_client) starts by itself once the editor is up and idle. GYROSIM_PLAY_WAIT = minimum seconds after start (default 8).
if "-gyrosimplay" in _cmd and "-run=" not in _cmd:
    import time
    _pl = dict(t=time.monotonic(), h=None, idle=None)

    def _autoplay(dt):
        try:
            now = time.monotonic()
            ues = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem)
            if ues.get_game_world() is not None:              # already playing (user pressed Play)
                unreal.unregister_slate_post_tick_callback(_pl["h"])
                return
            if now - _pl["t"] < float(__import__("os").environ.get("GYROSIM_PLAY_WAIT", "8")):
                return
            if dt > 0.25:                                      # editor still hitching (loading): wait for 3 s of smooth frames
                _pl["idle"] = None
                return
            if _pl["idle"] is None:
                _pl["idle"] = now
                return
            if now - _pl["idle"] < 3.0:
                return
            unreal.unregister_slate_post_tick_callback(_pl["h"])
            unreal.log("[gyrosim] -GyroSimPlay: starting Play")
            unreal.get_editor_subsystem(unreal.LevelEditorSubsystem).editor_request_begin_play()
        except Exception as e:
            unreal.log_error("[gyrosim] autoplay failed: %r" % (e,))
            unreal.unregister_slate_post_tick_callback(_pl["h"])
    _pl["h"] = unreal.register_slate_post_tick_callback(_autoplay)

# Busan minimap check (developer use): server with  --start rkpk  in the vworld mode, launch with
# -GyroSimPlay -GyroSimMinimap -RenderOffscreen  (Scripts/minimap_check.py: autoplay, 4 Busan shots, marker position vs
# lat / lon; shots outside git in C:/GyroSimTiles/shots/minimap). Quits the editor when done.
if "-gyrosimminimap" in _cmd:
    import os
    _p = os.path.join(unreal.Paths.project_dir(), "Scripts", "minimap_check.py")
    exec(compile(open(_p, encoding="utf-8").read(), _p, "exec"), {"__name__": "gyrosim_minimap"})

# Busan buildings before / after shots (developer use, Scripts/buildings_shots.py): a SECOND editor launched with
# -GyroSimBldgShots -RenderOffscreen stops its own sim client (never talks to the server) and quits when done.
if "-gyrosimbldgshots" in _cmd:
    import os
    _p = os.path.join(unreal.Paths.project_dir(), "Scripts", "buildings_shots.py")
    exec(compile(open(_p, encoding="utf-8").read(), _p, "exec"), {"__name__": "gyrosim_bldg_shots"})
