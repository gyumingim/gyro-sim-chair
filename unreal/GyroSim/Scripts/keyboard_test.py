"""Keyboard path test (developer use): synthesizes OS key events (keybd_event) while the editor window is in front,
so the real GetAsyncKeyState path in sim_client is exercised. Run inside the open editor with sim/server.py running:
    exec(open(r"<project>/Scripts/keyboard_test.py").read())
Writes Saved/verify/keyboard_test.json. Synthesized events, not a person on a keyboard.
"""
import ctypes, json, os, time
import unreal
import sim_client

_u32 = ctypes.windll.user32
_les = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
_ues = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem)
_OUT = os.path.join(unreal.Paths.project_saved_dir(), "verify")
_R = {}
_k = dict(t0=None, i=0, h=None, phase="pie", tp=time.monotonic())


def _key(vk, down):
    _u32.keybd_event(vk, 0, 0 if down else 2, 0)


def _front():
    pid = os.getpid()
    found = []
    @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
    def cb(h, _):
        p = ctypes.c_ulong()
        _u32.GetWindowThreadProcessId(h, ctypes.byref(p))
        if p.value == pid and _u32.IsWindowVisible(h) and _u32.GetWindowTextLengthW(h) > 0:
            found.append(h)
        return True
    _u32.EnumWindows(cb, 0)
    for h in found:
        _u32.ShowWindow(h, 9)
        _key(0x12, True); _key(0x12, False)          # ALT tap lets SetForegroundWindow work from a background process
        _u32.SetForegroundWindow(h)
    return sim_client.client().kb.focused()


def _snap(name):
    c = sim_client.client()
    s = c.s or {}
    t = s.get("tut") or {}
    _R[name] = dict(focused=c.kb.focused(), local=dict((k, round(v, 2)) for k, v in c.ctrl.items()),
                    packet=dict((k, round(s.get(k, -9), 2)) for k in ("ail", "elev", "rud", "thr", "brk")),
                    tut=dict(on=t.get("on"), menu=t.get("menu"), lesson=t.get("lesson"), step=t.get("step")), view=c.view)
    unreal.log("[kbtest] %s %s" % (name, json.dumps(_R[name], ensure_ascii=False)))


VK = sim_client.VK
_STEPS = [
    (0.0, lambda: _R.update(front=_front())),
    (0.5, lambda: _snap("idle")),
    (0.6, lambda: _key(VK["RIGHT"], True)),
    (0.9, lambda: _snap("right_0.3s")),
    (1.4, lambda: _snap("right_0.8s")),
    (1.5, lambda: _key(VK["RIGHT"], False)),
    (1.6, lambda: _key(VK["DOWN"], True)),
    (2.4, lambda: _snap("down_0.8s")),
    (2.5, lambda: _key(VK["DOWN"], False)),
    (3.0, lambda: _snap("released_0.5s")),
    (3.1, lambda: _key(VK["F1"], True)), (3.2, lambda: _key(VK["F1"], False)),
    (3.6, lambda: _snap("F1_menu")),
    (3.7, lambda: _key(VK["K2"], True)), (3.8, lambda: _key(VK["K2"], False)),
    (4.5, lambda: _snap("key2_lesson2")),
    (4.6, lambda: _key(VK["N"], True)), (4.7, lambda: _key(VK["N"], False)),
    (5.2, lambda: _snap("N_next")),
    (5.3, lambda: _key(VK["F2"], True)), (5.4, lambda: _key(VK["F2"], False)),
    (5.9, lambda: _snap("F2_stop")),
    (6.0, lambda: _key(VK["V"], True)), (6.1, lambda: _key(VK["V"], False)),
    (6.4, lambda: _snap("V_chase")),
    (6.5, lambda: _key(VK["V"], True)), (6.6, lambda: _key(VK["V"], False)),
]


def _tick(dt):
    try:
        now = time.monotonic()
        c = sim_client.client()
        if _k["phase"] == "pie":
            if _ues.get_game_world() is None:
                _les.editor_request_begin_play()
            _k["phase"] = "wait"
            return
        if _k["phase"] == "wait":
            if _ues.get_game_world() is not None and c and c.aircraft is not None and c.s is not None and now - _k["tp"] > 3:
                c.override = None
                c._send({"cmd": "reset", "mode": "air"})
                _k.update(phase="run", t0=now)
            return
        el = now - _k["t0"]
        while _k["i"] < len(_STEPS) and el >= _STEPS[_k["i"]][0]:
            _STEPS[_k["i"]][1]()
            _k["i"] += 1
        if _k["i"] >= len(_STEPS) and el > 7.5:
            with open(os.path.join(_OUT, "keyboard_test.json"), "w", encoding="utf-8") as f:
                json.dump(dict(made=time.strftime("%Y-%m-%d %H:%M:%S"), note="synthesized keybd_event", results=_R), f, indent=1, ensure_ascii=False)
            _les.editor_request_end_play()
            unreal.unregister_slate_post_tick_callback(_k["h"])
    except Exception as e:
        unreal.log_error("[kbtest] %r" % (e,))
        unreal.unregister_slate_post_tick_callback(_k["h"])


_k["h"] = unreal.register_slate_post_tick_callback(_tick)
