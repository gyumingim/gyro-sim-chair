"""Live check against a running server.py (WebSocket): the whole trainee path through the real server.
    python sim/test_live.py        -> sim/out/test_live.json, prints PASS / FAIL per check
menu (down / select) -> lesson 2 -> briefing pages (N) -> demo (autopilot moves the controls) -> skip -> practice:
keyboard vs rig wording (mode toggle), scripted pilot pushes the altitude off target -> corrective coaching,
the training panel image is served at /out/, repeat (Z) re-says the instruction, voice present, menu again at the end.
"""
import asyncio, json, os, sys, time, urllib.request
import websockets
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from training.autopilot import Autopilot     # noqa: E402

URL = "ws://127.0.0.1:8781"
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "out", "test_live.json")
R = dict(made=time.strftime("%Y-%m-%d %H:%M:%S"), checks={})


def check(name, ok, **info):
    R["checks"][name] = dict(ok=bool(ok), **info)
    print(("OK   " if ok else "FAIL ") + name, json.dumps(info, ensure_ascii=False)[:300], flush=True)


async def main():
    async with websockets.connect(URL, max_size=2 ** 22) as ws:
        S = {}

        async def pump(sec, ctrl=None):
            t0 = time.monotonic()
            seen = []
            while time.monotonic() - t0 < sec:
                if ctrl is not None:
                    await ws.send(json.dumps({"ctrl": ctrl(S) if callable(ctrl) else ctrl}))
                try:
                    S.update(json.loads(await asyncio.wait_for(ws.recv(), 0.5)))
                except asyncio.TimeoutError:
                    continue
                T = S.get("tut") or {}
                k = (T.get("phase"), T.get("step"), T.get("instr"), T.get("coach"), T.get("spoken"))
                if not seen or seen[-1] != k:
                    seen.append(k)
            return seen

        async def cmd(m, wait=0.35):
            await ws.send(json.dumps(m))
            await pump(wait)

        T = lambda: S.get("tut") or {}
        await pump(0.5)
        await cmd({"cmd": "tut", "op": "stop"})                       # -> menu
        check("menu_at_start", T().get("phase") == "menu" and S.get("paused"), phase=T().get("phase"), items=T().get("items"))
        check("voice_available", T().get("voice_ok"), voice=T().get("voice"))
        await cmd({"cmd": "menu", "op": "down"})                      # "강의 고르기"
        await cmd({"cmd": "menu", "op": "select"})
        for _ in range(2):
            await cmd({"cmd": "menu", "op": "down"})                  # lesson 2
        sel_text = (T().get("items") or [""])[T().get("sel", 0)]
        await cmd({"cmd": "menu", "op": "select"})
        check("menu_selects_lesson", T().get("phase") == "brief" and T().get("lesson") == 2, sel=sel_text, phase=T().get("phase"))
        pages = []
        while T().get("phase") == "brief" and len(pages) < 10:
            pages.append(T().get("text"))
            await cmd({"cmd": "tut", "op": "next"})
        check("briefing_pages", len(pages) >= 3 and T().get("phase") == "demo", n=len(pages), first=pages[0][:60] if pages else "")
        seen = await pump(4.0)
        check("demo_flies", T().get("phase") == "demo" and S.get("demo") and not S.get("paused"), ail=S.get("ail"), elev=S.get("elev"),
              said=[x[4] for x in seen if x[4]][-2:])
        await cmd({"cmd": "tut", "op": "next"}, 1.0)                  # skip the demo -> practice
        await cmd({"cmd": "tut", "op": "beginner", "on": False}, 0.6)
        while T().get("mode") != "kbd" or not T().get("mode_auto") is False:
            await cmd({"cmd": "tut", "op": "mode"})
            if T().get("mode") == "kbd" and not T().get("mode_auto"):
                break
        await pump(1.0, lambda S: {})
        k = T().get("instr", "")
        await cmd({"cmd": "tut", "op": "mode"}, 0.6)                  # kbd -> rig
        r = T().get("instr", "")
        await cmd({"cmd": "tut", "op": "mode"})                       # -> auto
        check("keyboard_vs_rig_wording", T().get("phase") == "practice" and k != r and "키" in k and "손" in r, kbd=k, rig=r)
        n0 = T().get("say_n", 0)
        await cmd({"cmd": "tut", "op": "repeat"}, 0.6)
        check("repeat_instruction", T().get("say_n", 0) > n0, spoken=T().get("spoken"))
        # scripted pilot: nose down until 250 ft low, then hold there -> coaching must ask for a pull
        ap = Autopilot(gain=0.6)
        alt0 = S["alt_m"] / 0.3048
        goal = lambda S: dict(pitch=-4.0, bank=0, spd=350) if S["alt_m"] / 0.3048 > alt0 - 230 else dict(alt=alt0 - 260, hdg=0, spd=350)
        seen = await pump(14.0, lambda S: {k: v for k, v in ap.update(S, goal(S), 1 / 60).items() if k in ("ail", "elev", "thr", "rud")})
        coach = [x[3] for x in seen if x[3]]
        check("coaching_on_deviation", any("고도" in c and ("당기" in c or "↓" in c) for c in coach), coach=coach[:3],
              targets=T().get("targets"))
        img = T().get("img") or ""
        try:
            data = urllib.request.urlopen("http://127.0.0.1:8780/out/" + os.path.basename(img), timeout=3).read()
            check("panel_image_served", len(data) > 5000 and data[:4] == b"\x89PNG", bytes=len(data), img=img)
        except OSError as e:
            check("panel_image_served", False, err=repr(e))
        await cmd({"cmd": "tut", "op": "beginner", "on": True})
        await cmd({"cmd": "tut", "op": "stop"})
        await cmd({"cmd": "reset", "mode": "air"})
        check("back_to_menu", T().get("phase") == "menu", phase=T().get("phase"))
    R["ok"] = all(c["ok"] for c in R["checks"].values())
    json.dump(R, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("PASS" if R["ok"] else "FAIL", "->", OUT)


asyncio.run(main())
