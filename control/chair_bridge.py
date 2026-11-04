"""PC side of the chair controller: sim UDP cues -> safety shaping -> serial to the ESP32 board.

    python control/chair_bridge.py --port COM5          # real board (ESP32 USB serial, 115200)
    python control/chair_bridge.py --sil                # no hardware: firmware core DLL + chair plant model in the loop
    python control/chair_bridge.py --list-ports

Console commands (type + Enter): zero, cal, arm, disarm, reset, status, quit
  zero   = level reference of the IMU, only accepted while the lock pins are IN (chair mechanically at 0 deg)
  cal    = 탑승 후 초기 캘리 (pins out, deck away): home weights (first time), level, measure deg per mm, ~45 s
  arm    = start following the sim (board must be READY)
  disarm = return slowly to level

Input:  UDP JSON {"roll": deg, "pitch": deg} on 127.0.0.1:4210 (sim/server.py Chair, ~60 Hz). roll + = right side down, pitch + = nose up.
Output: "$C,<seq>,<roll cdeg>,<pitch cdeg>,<flags>*<crc8 hex>\n" at 50 Hz (also a heartbeat), "$K,<seq>,<WORD>*HH\n" commands.
Board:  "$T,..." telemetry at 20 Hz (see parse_telemetry).

Safety done here (the firmware repeats the important ones; the hardware e-stop does not depend on either):
  * soft limits (config, and the board's measured achievable angles - 1 deg)
  * low-pass + acceleration + rate limit matched to the slow weight-shift chair (control/chair_model.py)
  * deadman: no sim packet for udp_timeout_s -> target ramps to 0 (chair levels), heartbeat to the board continues
  * board link: no telemetry for link_timeout_s -> warning; the board itself levels after 0.5 s without our packets
  * the shaper follows the board's own reference whenever the board is not in RUN, so ARM / RESET never makes a jump
"""
import argparse, json, math, os, socket, sys, threading, time
from dataclasses import dataclass, field

HERE = os.path.dirname(os.path.abspath(__file__))


def crc8(s: str) -> int:
    crc = 0
    for ch in s.encode("ascii"):
        crc ^= ch
        for _ in range(8):
            crc = ((crc << 1) ^ 0x07) & 0xFF if crc & 0x80 else (crc << 1) & 0xFF
    return crc


def frame(body: str) -> str:
    return f"${body}*{crc8(body):02X}"


def check_frame(line: str):
    """Returns the body between $ and * if the CRC matches, else None."""
    line = line.strip()
    if not line.startswith("$") or "*" not in line:
        return None
    body, _, cs = line[1:].rpartition("*")
    try:
        return body if int(cs, 16) == crc8(body) else None
    except ValueError:
        return None


TELEM_FIELDS = ["ms", "state", "cal_r", "cal_p", "faults", "sw", "roll", "pitch", "x_r", "x_p", "cal_ok", "home_ok",
                "max_r_pos", "max_r_neg", "max_p_pos", "max_p_neg", "ref_r", "ref_p", "k_r", "k_p"]
SW_BITS = ["estop_ok", "pins_stowed", "deck_stowed", "imu_ok", "pos_ok_r", "pos_ok_p", "lim_r+", "lim_r-", "lim_p+", "lim_p-", "idx_r", "idx_p"]
FAULT_BITS = ["IMU", "POS_R", "POS_P", "OVERANGLE", "STALL_R", "STALL_P", "LIMIT", "CAL", "TIMEOUT", "INTERLOCK"]


def parse_telemetry(line: str):
    body = check_frame(line)
    if not body or not body.startswith("T,"):
        return None
    v = body.split(",")[1:]
    if len(v) != len(TELEM_FIELDS):
        return None
    d = dict(zip(TELEM_FIELDS, v))
    t = dict(ms=int(d["ms"]), state=d["state"], cal=(int(d["cal_r"]), int(d["cal_p"])), faults=int(d["faults"], 16), sw=int(d["sw"], 16),
             roll=int(d["roll"]) / 100, pitch=int(d["pitch"]) / 100, x_r=int(d["x_r"]) / 10, x_p=int(d["x_p"]) / 10,
             cal_ok=d["cal_ok"] == "1", home_ok=d["home_ok"] == "1",
             max_r=(int(d["max_r_neg"]) / 100, int(d["max_r_pos"]) / 100), max_p=(int(d["max_p_neg"]) / 100, int(d["max_p_pos"]) / 100),
             ref_r=int(d["ref_r"]) / 100, ref_p=int(d["ref_p"]) / 100, k_r=int(d["k_r"]) / 1e7, k_p=int(d["k_p"]) / 1e7)
    t["switches"] = [n for i, n in enumerate(SW_BITS) if t["sw"] >> i & 1]
    t["fault_names"] = [n for i, n in enumerate(FAULT_BITS) if t["faults"] >> i & 1]
    return t


@dataclass
class Config:
    udp_host: str = "127.0.0.1"
    udp_port: int = 4210
    send_hz: float = 50.0
    udp_timeout_s: float = 0.3
    link_timeout_s: float = 1.0
    # from control/chair_model.py (WGM40C 1/218 + 20T, 80 kg rider; 추정 — re-run after measuring the real chair)
    rate_deg_s: dict = field(default_factory=lambda: dict(roll=1.45, pitch=1.0))
    accel_deg_s2: dict = field(default_factory=lambda: dict(roll=0.66, pitch=0.51))
    soft_limit_deg: dict = field(default_factory=lambda: dict(roll=18.0, pitch=14.0))
    lowpass_s: float = 0.5
    follow_gain: float = 2.0          # 1/s, how hard the shaped cue chases the filtered target
    achievable_margin_deg: float = 1.0


class AxisShaper:
    """target -> clamp -> low-pass -> follower with |rate| <= R and |accel| <= A (stops without overshoot)."""

    def __init__(self, rate, accel, lim, tau, gain):
        self.R, self.A, self.lim, self.tau, self.K = rate, accel, lim, tau, gain
        self.lo, self.hi = -lim, lim
        self.f = 0.0      # low-passed target
        self.y = 0.0      # shaped output
        self.v = 0.0      # its rate

    def reset(self, y):
        self.f = self.y = y
        self.v = 0.0

    def set_bounds(self, lo, hi):
        self.lo, self.hi = max(-self.lim, lo), min(self.lim, hi)

    def step(self, u, dt):
        u = min(self.hi, max(self.lo, u))
        self.f += (u - self.f) * dt / (self.tau + dt)
        err = self.f - self.y
        v_des = max(-self.R, min(self.R, self.K * err))
        adt = self.A * dt                                   # discrete-time braking speed: stops exactly on the target
        vb = adt * (math.sqrt(0.25 + 2 * abs(err) / (adt * dt)) - 0.5)
        if abs(v_des) > vb:
            v_des = math.copysign(vb, v_des)
        self.v += max(-self.A * dt, min(self.A * dt, v_des - self.v))
        self.y += self.v * dt
        if not (self.lo <= self.y <= self.hi):              # bounds moved (board reported a smaller range)
            self.y = min(self.hi, max(self.lo, self.y)); self.v = 0.0
        return self.y


class Bridge:
    """Transport-free core: feed on_udp / on_line, call tick(now) at send_hz and write what it returns."""

    def __init__(self, cfg: Config = None):
        self.cfg = cfg or Config()
        c = self.cfg
        self.ax = dict(roll=AxisShaper(c.rate_deg_s["roll"], c.accel_deg_s2["roll"], c.soft_limit_deg["roll"], c.lowpass_s, c.follow_gain),
                       pitch=AxisShaper(c.rate_deg_s["pitch"], c.accel_deg_s2["pitch"], c.soft_limit_deg["pitch"], c.lowpass_s, c.follow_gain))
        self.seq = 0
        self.target = dict(roll=0.0, pitch=0.0)
        self.udp_t = -1e9
        self.tel = None
        self.tel_t = -1e9
        self.last_tick = None
        self.pending = []
        self.events = []

    # ---- inputs ----
    def on_udp(self, data: bytes, now: float):
        try:
            d = json.loads(data.decode("utf-8"))
            r, p = float(d["roll"]), float(d["pitch"])
        except (ValueError, KeyError, TypeError, UnicodeDecodeError):
            return False
        if not (math.isfinite(r) and math.isfinite(p)):
            return False
        self.target = dict(roll=r, pitch=p)
        self.udp_t = now
        return True

    def on_line(self, line: str, now: float):
        t = parse_telemetry(line)
        if t is None:
            return None
        prev = self.tel["state"] if self.tel else None
        self.tel, self.tel_t = t, now
        if prev != t["state"]:
            self.events.append((now, f"board {prev} -> {t['state']} faults={t['fault_names']}"))
        m = self.cfg.achievable_margin_deg
        if t["cal_ok"]:
            self.ax["roll"].set_bounds(t["max_r"][0] + m, t["max_r"][1] - m)
            self.ax["pitch"].set_bounds(t["max_p"][0] + m, t["max_p"][1] - m)
        return t

    def command(self, word: str):
        word = word.strip().upper()
        if word not in ("ARM", "DISARM", "STOP", "CAL", "ZERO", "RESET", "PING"):
            raise ValueError(word)
        self.pending.append(word)

    # ---- status ----
    def sim_alive(self, now):
        return now - self.udp_t < self.cfg.udp_timeout_s

    def link_alive(self, now):
        return now - self.tel_t < self.cfg.link_timeout_s

    # ---- output ----
    def tick(self, now: float):
        dt = 1 / self.cfg.send_hz if self.last_tick is None else max(1e-3, min(0.1, now - self.last_tick))
        self.last_tick = now
        running = bool(self.tel) and self.tel["state"] == "RUN"
        if not running:
            # board not following: keep the shaper on the board's reference so ARM / RESET start without a jump
            if self.tel:
                self.ax["roll"].reset(self.tel["ref_r"]); self.ax["pitch"].reset(self.tel["ref_p"])
            out = dict(roll=self.ax["roll"].y, pitch=self.ax["pitch"].y)
        else:
            alive = self.sim_alive(now)
            tgt = self.target if alive else dict(roll=0.0, pitch=0.0)     # deadman: level
            out = {k: self.ax[k].step(tgt[k], dt) for k in ("roll", "pitch")}
        lines = []
        for w in self.pending:
            self.seq += 1
            lines.append(frame(f"K,{self.seq},{w}"))
        self.pending.clear()
        self.seq += 1
        flags = 1
        lines.append(frame(f"C,{self.seq},{round(out['roll'] * 100)},{round(out['pitch'] * 100)},{flags}"))
        self.out = out
        return lines


# ---------------------------------------------------------------- transports
class SerialLink:
    def __init__(self, port, baud=115200):
        import serial
        self.s = serial.Serial(port, baud, timeout=0)
        self.buf = b""

    def write(self, line):
        self.s.write((line + "\n").encode("ascii"))

    def read_lines(self):
        self.buf += self.s.read(4096)
        *lines, self.buf = self.buf.split(b"\n")
        return [l.decode("ascii", "replace").strip() for l in lines]


class SilLink:
    """Firmware core DLL + plant model, stepped in real time by the bridge loop."""

    def __init__(self):
        sys.path.insert(0, HERE)
        import sil
        self.sim = sil.Sil(start_x=(0.12, -0.05))
        self.sim.set_switches(pins_stowed=True, deck_stowed=True)
        self.t0 = time.monotonic()
        self.out = []

    def write(self, line):
        self.sim.rx(line)

    def read_lines(self):
        now = time.monotonic() - self.t0
        self.out += self.sim.run_until(now)
        o, self.out = self.out, []
        return o


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port")
    ap.add_argument("--baud", type=int, default=115200)
    ap.add_argument("--sil", action="store_true")
    ap.add_argument("--list-ports", action="store_true")
    ap.add_argument("--log", default=os.path.join(HERE, "out", "bridge_log.csv"))
    a = ap.parse_args()
    if a.list_ports:
        from serial.tools import list_ports
        for p in list_ports.comports():
            print(p.device, p.description)
        return
    if not a.port and not a.sil:
        ap.error("--port COMx or --sil")
    link = SilLink() if a.sil else SerialLink(a.port, a.baud)
    br = Bridge()
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind((br.cfg.udp_host, br.cfg.udp_port)); sock.setblocking(False)
    os.makedirs(os.path.dirname(a.log), exist_ok=True)
    log = open(a.log, "w", encoding="utf-8")
    log.write("t,state,faults,target_roll,target_pitch,cue_roll,cue_pitch,roll,pitch,x_r,x_p\n")
    stop = threading.Event()

    def console():
        for raw in sys.stdin:
            w = raw.strip().lower()
            if w in ("quit", "exit", "q"):
                stop.set(); return
            if w == "status":
                print(json.dumps(br.tel, ensure_ascii=False)); continue
            try:
                br.command(w)
            except ValueError:
                print("commands: zero cal arm disarm reset status quit")
    threading.Thread(target=console, daemon=True).start()
    print(f"bridge: UDP {br.cfg.udp_host}:{br.cfg.udp_port} -> {'SIL' if a.sil else a.port}. type 'cal' after boarding, then 'arm'.")
    t0 = time.monotonic(); next_t = t0; last_warn = 0
    try:
        while not stop.is_set():
            now = time.monotonic()
            while True:
                try:
                    data, _ = sock.recvfrom(2048)
                except (BlockingIOError, OSError):
                    break
                br.on_udp(data, now)
            for line in link.read_lines():
                br.on_line(line, now)
            while br.events:
                print(f"[{br.events[0][0]-t0:7.1f}] {br.events.pop(0)[1]}")
            if now >= next_t:
                for line in br.tick(now):
                    link.write(line)
                next_t += 1 / br.cfg.send_hz
                if br.tel:
                    T = br.tel
                    log.write(f"{now-t0:.3f},{T['state']},{T['faults']:x},{br.target['roll']:.2f},{br.target['pitch']:.2f},{br.out['roll']:.2f},{br.out['pitch']:.2f},"
                              f"{T['roll']:.2f},{T['pitch']:.2f},{T['x_r']:.1f},{T['x_p']:.1f}\n")
                if not br.link_alive(now) and now - last_warn > 2:
                    print("WARNING: no telemetry from the board"); last_warn = now
            time.sleep(0.002)
    finally:
        log.close()


if __name__ == "__main__":
    main()
