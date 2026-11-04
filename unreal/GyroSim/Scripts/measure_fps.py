"""FPS / GPU-time measurement in PIE (monitor mode). Run inside the open editor (Python console or remote exec):
    exec(open(r"<project>/Scripts/measure_fps.py").read())

The editor caps PIE at 120 fps, so the useful number is the GPU frame time (startfpschart/stopfpschart summary in the
log). The PIE viewport is small, so r.ScreenPercentage is raised to render ~1920x1080 pixels ("1080p") and, for the VR
estimate, ~2 x 1832x1920 pixels (Quest 2 class headset, both eyes) with the VR preset. Pixel-count scaling is an
estimate of VR cost, not a headset measurement. Writes Saved/verify/fps_<label>.json. Needs sim/server.py running.
GYROSIM_FPS_LABEL env var = label (default 'run').
"""
import json, math, os, re, time
import unreal
import sim_client

_les = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
_ues = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem)
_OUT = os.path.join(unreal.Paths.project_saved_dir(), "verify")
os.makedirs(_OUT, exist_ok=True)
_LOG = os.path.join(unreal.Paths.project_log_dir(), "GyroSim.log")
_label = os.environ.get("GYROSIM_FPS_LABEL", "run")
_PHASES = [("cockpit_1080p", 1920 * 1080, "monitor", "cockpit"), ("chase_1080p", 1920 * 1080, "monitor", "chase"),
           ("cockpit_vr_pixels", 2 * 1832 * 1920, "vr", "cockpit")]
_st = dict(phase="start", t=time.monotonic(), i=0, dts=[], res={}, h=None)


def _cmd(c):
    unreal.SystemLibrary.execute_console_command(_ues.get_game_world(), c)


def _gpu_from_log():
    try:
        with open(_LOG, encoding="utf-8", errors="ignore") as f:
            txt = f.read()[-200000:]
        g = re.findall(r"Average GPU frametime: ([\d.]+) ms", txt)
        gt = re.findall(r"Average GameThread frametime: ([\d.]+) ms", txt)
        return (float(g[-1]) if g else None), (float(gt[-1]) if gt else None)
    except OSError:
        return None, None


def _summ(dts):
    dts = sorted(dts)
    n = len(dts)
    if not n:
        return {}
    avg = sum(dts) / n
    return dict(frames=n, avg_fps=round(1 / avg, 1), avg_ms=round(avg * 1000, 2), p95_ms=round(dts[int(n * 0.95) - 1] * 1000, 2))


def _preset(name):
    f = getattr(sim_client, "apply_preset", None)
    if f:
        f(name)


def _tick(dt):
    try:
        now = time.monotonic()
        el = now - _st["t"]
        ph = _st["phase"]
        c = sim_client.client()
        if ph == "start":
            _les.editor_request_begin_play()
            _st.update(phase="wait", t=now)
        elif ph == "wait":
            if _ues.get_game_world() is not None and c and c.aircraft is not None and c.s is not None and getattr(c, "startup_done", True):
                c._send({"cmd": "reset", "mode": "air"})
                _st.update(phase="setup", t=now)
        elif ph == "setup" and el > 3:
            name, px, preset, view = _PHASES[_st["i"]]
            _cmd("t.MaxFPS 0"); _cmd("r.VSync 0")
            _preset(preset)
            vp = unreal.WidgetLayoutLibrary.get_viewport_size(_ues.get_game_world())
            sp = max(25.0, min(400.0, 100.0 * math.sqrt(px / max(1.0, vp.x * vp.y))))
            _cmd("r.ScreenPercentage %.0f" % sp)
            c.view, c.chase_yaw = view, None
            _st["cur"] = dict(viewport=[round(vp.x), round(vp.y)], screen_percentage=round(sp), preset=preset, view=view,
                              render_px=[round(vp.x * sp / 100), round(vp.y * sp / 100)])
            _st.update(phase="warm", t=now)
        elif ph == "warm" and el > 2:
            _cmd("startfpschart")
            _st.update(phase="run", t=now, dts=[])
        elif ph == "run":
            _st["dts"].append(dt)
            if el > 6:
                _cmd("stopfpschart")
                _st.update(phase="collect", t=now)
        elif ph == "collect" and el > 0.5:
            name = _PHASES[_st["i"]][0]
            gpu, gt = _gpu_from_log()
            r = dict(_st["cur"], **_summ(_st["dts"][5:]), gpu_ms=gpu, game_thread_ms=gt)
            _st["res"][name] = r
            unreal.log("[fps] %s %s" % (name, json.dumps(r)))
            _st["i"] += 1
            _st.update(phase="setup" if _st["i"] < len(_PHASES) else "end", t=now)
        elif ph == "end":
            _cmd("r.ScreenPercentage 100")
            _preset("monitor")
            c.view = "cockpit"
            _les.editor_request_end_play()
            _st["res"].update(label=_label, made=time.strftime("%Y-%m-%d %H:%M:%S"),
                              hmd=unreal.HeadMountedDisplayFunctionLibrary.is_head_mounted_display_enabled())
            with open(os.path.join(_OUT, "fps_%s.json" % _label), "w") as f:
                json.dump(_st["res"], f, indent=1)
            unreal.log("[fps] done -> fps_%s.json" % _label)
            unreal.unregister_slate_post_tick_callback(_st["h"])
    except Exception as e:
        unreal.log_error("[fps] error %r" % (e,))
        unreal.unregister_slate_post_tick_callback(_st["h"])


_st["h"] = unreal.register_slate_post_tick_callback(_tick)
