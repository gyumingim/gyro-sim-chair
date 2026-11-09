"""True full screen for the Play-In-Editor window (11-09, user: "알트 엔터해도 전체화면 안됨").

Why Alt+Enter does nothing in PIE (UE 5.8 source): the key only sets the r.setres console variable; its sink runs at the
start of the next editor tick, outside the PIE world, where FApp::IsGame() is false, and FSceneViewport::ResizeFrame
("Resizing the window directly is only supported in the game") returns without touching the window.
Here the same request is made from inside the PIE world tick (a next-tick timer on a small Python UObject whose outer is
the PIE world -> GIsPlayInEditorWorld is true there): UGameUserSettings.ApplyResolutionSettings calls the console sinks
at once -> ResizeFrame -> SWindow.SetWindowMode(WindowedFullscreen) = borderless window over the whole monitor, title
bar collapsed (SWindow does that for full screen modes). Windowed = back to a normal PIE window.

    import pie_fullscreen; pie_fullscreen.request(world, True | False | None)   (None = toggle)
sim_client: on (auto) when Play was started by GyroSim_Busan.bat (-GyroSimPlay) on a monitor (not VR); F11 / Alt+Enter toggle.
"""
import ctypes, os
import unreal

WINDOWED = (1600, 900)                  # size of the PIE window when full screen is turned off
_st = dict(want=None, on=False, n=0, obj=None, last="", world=None)


def _log(*a):
    unreal.log("[pie_fullscreen] " + " ".join(str(x) for x in a))


def _monitor_px():
    """primary monitor size in physical pixels (the editor process is DPI aware)."""
    try:
        u = ctypes.windll.user32
        return int(u.GetSystemMetrics(0)), int(u.GetSystemMetrics(1))
    except Exception:
        return 1920, 1080


def _apply_now():
    """must run inside the PIE world tick (see the module note)."""
    want = _st["want"]
    if want is None:
        return
    _st["n"] += 1
    gus = unreal.GameUserSettings.get_game_user_settings()
    if want:
        w, h = _monitor_px()
        mode = unreal.WindowMode.WINDOWED_FULLSCREEN
    else:
        w, h = WINDOWED
        mode = unreal.WindowMode.WINDOWED
    # the request must differ from the engine's current one (an earlier Alt+Enter may have stored the same values while
    # it could not be applied); WindowedFullscreen fills the monitor whatever the size, a 1 px change is harmless
    h -= _st["n"] % 2
    gus.set_screen_resolution(unreal.IntPoint(w, h))
    gus.set_fullscreen_mode(mode)
    gus.apply_resolution_settings(False)
    _st["on"] = bool(want)
    _st["want"] = None
    try:
        cur = unreal.SystemLibrary.get_console_variable_string_value("r.SetRes")
    except Exception:
        cur = "?"
    _st["last"] = "%s %dx%d (r.SetRes %s)" % ("fullscreen" if want else "windowed", w, h, cur)
    _log("applied", _st["last"])


@unreal.uclass()
class GyroSimFullscreen(unreal.Object):
    @unreal.ufunction()
    def apply_mode(self):
        try:
            _apply_now()
        except Exception as e:
            _log("apply failed", repr(e))


def request(world, on=None):
    """ask for full screen (True), windowed (False) or the other one (None); applied on the next PIE tick."""
    if world is None:
        return False
    _st["want"] = (not _st["on"]) if on is None else bool(on)
    try:
        if _st["obj"] is None or _st["world"] != world:
            _st["obj"] = unreal.new_object(GyroSimFullscreen, outer=world)
            _st["world"] = world
        unreal.SystemLibrary.set_timer_for_next_tick(_st["obj"], "apply_mode")
        return True
    except Exception as e:
        _log("request failed", repr(e))
        return False


def reset():
    """new Play: the engine opens the PIE window windowed again."""
    _st.update(want=None, on=False, obj=None, world=None)


def is_on():
    return _st["on"]


def status():
    return dict(on=_st["on"], n=_st["n"], last=_st["last"], window=pie_window_rect())


def pie_window_rect():
    """(left, top, right, bottom) of this editor's PIE window and the monitor size, None without a window (off-screen)."""
    if os.name != "nt":
        return None
    import ctypes.wintypes as W
    u32 = ctypes.windll.user32
    pid = os.getpid()
    found = []
    CB = ctypes.WINFUNCTYPE(ctypes.c_bool, W.HWND, W.LPARAM)

    def cb(h, l):
        p = ctypes.c_ulong()
        u32.GetWindowThreadProcessId(h, ctypes.byref(p))
        if p.value == pid and u32.IsWindowVisible(h):
            n = u32.GetWindowTextLengthW(h)
            buf = ctypes.create_unicode_buffer(n + 1)
            u32.GetWindowTextW(h, buf, n + 1)
            if "[NetMode:" in buf.value:
                found.append(h)
        return True
    u32.EnumWindows(CB(cb), 0)
    if not found:
        return None
    r = W.RECT()
    u32.GetWindowRect(found[0], ctypes.byref(r))
    return dict(rect=(r.left, r.top, r.right, r.bottom), monitor=_monitor_px())
