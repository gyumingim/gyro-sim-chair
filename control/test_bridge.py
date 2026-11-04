"""Checks of the PC-side logic (no hardware). python control/test_bridge.py -> prints PASS/FAIL, exit code 0/1."""
import json, math, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from chair_bridge import AxisShaper, Bridge, Config, check_frame, crc8, frame, parse_telemetry

R = []


def check(name, cond, info=""):
    R.append(bool(cond)); print(("PASS " if cond else "FAIL ") + name, info)


# CRC-8 poly 0x07, init 0: standard check value for "123456789" is 0xF4
check("crc8 check value", crc8("123456789") == 0xF4, hex(crc8("123456789")))
check("frame round trip", check_frame(frame("C,1,100,-200,1")) == "C,1,100,-200,1")
check("corrupted frame rejected", check_frame(frame("C,1,100,-200,1").replace("100", "900")) is None)

# shaper limits
c = Config()
sh = AxisShaper(1.3, 0.6, 18.0, 0.5, 2.0)
ys, dt = [], 0.02
for i in range(3000):
    ys.append(sh.step(30.0 if i < 1500 else -30.0, dt))
rates = [(b - a) / dt for a, b in zip(ys, ys[1:])]
acc = [(b - a) / dt for a, b in zip(rates, rates[1:])]
check("shaper soft limit 18", max(ys) <= 18.0 + 1e-9 and min(ys) >= -18.0 - 1e-9, f"{max(ys):.2f}/{min(ys):.2f}")
check("shaper rate <= 1.3 deg/s", max(abs(r) for r in rates) <= 1.3 + 1e-6, f"{max(abs(r) for r in rates):.3f}")
check("shaper accel <= 0.6 deg/s^2 (+15 % for the final snap onto the target)", max(abs(a) for a in acc[:1400]) <= 0.6 * 1.15, f"{max(abs(a) for a in acc[:1400]):.3f}")
sh2 = AxisShaper(1.45, 0.66, 18.0, 0.5, 2.0); ys2 = [sh2.step(5.0, dt) for _ in range(2000)]
check("shaper settles on 5 deg without overshoot", abs(ys2[-1] - 5) < 0.01 and max(ys2) < 5.05, f"{ys2[-1]:.3f} max {max(ys2):.3f}")


def telem(state="RUN", ref=(0, 0), maxr=(-21.4, 20.3), maxp=(-15.8, 15.8), cal_ok=1):
    body = (f"T,1000,{state},6,6,0,fff,0,0,0,0,{cal_ok},1,{round(maxr[1]*100)},{round(maxr[0]*100)},{round(maxp[1]*100)},{round(maxp[0]*100)},"
            f"{round(ref[0]*100)},{round(ref[1]*100)},6745,4717")
    return frame(body)


t = parse_telemetry(telem())
check("telemetry parse", t and t["state"] == "RUN" and t["max_r"] == (-21.4, 20.3) and "estop_ok" in t["switches"], str(t and t["switches"]))

# bridge: no jump on ARM, deadman, achievable bounds, bad UDP
b = Bridge(); now = 0.0
b.on_line(telem("READY", ref=(0.0, 0.0)), now)
b.on_udp(json.dumps(dict(roll=15, pitch=10)).encode(), now)
out = None
for i in range(50):
    now += 0.02; b.on_udp(json.dumps(dict(roll=15, pitch=10)).encode(), now); b.tick(now)
check("not RUN -> bridge holds the board reference (0)", abs(b.out["roll"]) < 1e-9)
b.on_line(telem("RUN", ref=(0.0, 0.0), maxr=(-10.0, 10.0)), now)
for i in range(1500):
    now += 0.02; b.on_udp(json.dumps(dict(roll=15, pitch=10)).encode(), now); b.tick(now)
check("achievable bound (board says 10, margin 1) clamps roll to 9", abs(b.out["roll"] - 9.0) < 0.01, f"{b.out['roll']:.2f}")
check("pitch soft limit 14 not hit by a 10 deg cue", abs(b.out["pitch"] - 10.0) < 0.01, f"{b.out['pitch']:.2f}")
for i in range(1500):
    now += 0.02; b.tick(now)                       # UDP stopped
check("deadman: no UDP -> cue back to 0", abs(b.out["roll"]) < 0.01 and abs(b.out["pitch"]) < 0.01, f"{b.out['roll']:.3f}")
check("bad UDP rejected", not b.on_udp(b"{roll:", now) and not b.on_udp(json.dumps(dict(roll="nan", pitch=0)).encode(), now))
lines = b.tick(now)
check("heartbeat frame every tick, seq increases", lines[-1].startswith("$C,") and int(lines[-1].split(",")[1]) == b.seq)
b.command("arm"); lines = b.tick(now)
check("command frame sent before the cue frame", lines[0].startswith("$K,") and "ARM" in lines[0] and lines[1].startswith("$C,"))
print(f"{sum(R)}/{len(R)} passed")
sys.exit(0 if all(R) else 1)
