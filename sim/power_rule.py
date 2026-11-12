"""Power rule for heavy CPU builds (the PC's power supply tripped twice under load, 11-11).

A heavy build (buildings / terrain / coast / veg / trees tiles) runs
  - at below-normal priority (Windows BELOW_NORMAL_PRIORITY_CLASS; pool workers inherit it),
  - on half the logical cores by default (an explicit env value such as GYROSIM_VEG_PROCS or GYROSIM_WORKERS wins),
  - only while holding the shared lock C:\\GyroSimTiles\\ue_offscreen.lock, with the same convention as
    sim/impostor/run_locked.ps1 and unreal/GyroSim/Scripts/tune_serve.ps1: created atomically (create-new) with our own
    token line, refused (exit 3) when someone else holds it, removed on exit only if it still holds our token.
Set GYROSIM_LOCK_HELD=1 when a wrapper (run_locked.ps1) already holds the lock for this job.

Lock convention for ALL holders (this is the one place it is written down):
  - first line = token "<job> pid<Windows PID> <time> <guid>" (PowerShell holders, this module); create-new only.
  - a holder removes the lock only while its first line is still its own token.
  - a holder that may run longer than 2 minutes without an UnrealEditor process keeps the mtime fresh (this module
    touches it every REFRESH_S from a daemon thread), because sim/landmarks/run_shots.sh treats a lock older than
    120 s with no UnrealEditor alive (or older than 30 min) as stale.
  - run_shots.sh never takes over a lock whose token names a live pid.
"""
import atexit, os, sys, threading, time, uuid

REFRESH_S = 30.0

LOCK = r"C:\GyroSimTiles\ue_offscreen.lock"


def half_cores():
    return max(1, (os.cpu_count() or 2) // 2)


def workers(env=None):
    """worker count: the explicit env value (env, then GYROSIM_WORKERS) if set, else half the logical cores."""
    for k in ((env,) if env else ()) + ("GYROSIM_WORKERS",):
        v = os.environ.get(k)
        if v:
            try:
                return max(1, int(v))
            except ValueError:
                pass
    return half_cores()


def below_normal():
    """-> True when the process now runs at below-normal priority (read back, not assumed)."""
    try:
        if os.name == "nt":
            import ctypes
            from ctypes import wintypes
            k = ctypes.WinDLL("kernel32", use_last_error=True)
            k.GetCurrentProcess.restype = wintypes.HANDLE      # untyped, the 64-bit pseudo-handle is truncated (error 6)
            k.SetPriorityClass.argtypes = [wintypes.HANDLE, wintypes.DWORD]
            k.SetPriorityClass.restype = wintypes.BOOL
            k.GetPriorityClass.argtypes = [wintypes.HANDLE]
            k.GetPriorityClass.restype = wintypes.DWORD
            h = k.GetCurrentProcess()
            if not k.SetPriorityClass(h, 0x4000):               # BELOW_NORMAL_PRIORITY_CLASS
                print("power_rule: SetPriorityClass failed (error %d)" % ctypes.get_last_error(), flush=True)
            return k.GetPriorityClass(h) == 0x4000
        os.nice(5)
        return os.nice(0) > 0
    except (OSError, AttributeError) as e:
        print("power_rule: priority not changed (%r)" % (e,), flush=True)
        return False


def _release(token):
    try:
        with open(LOCK, encoding="utf-8-sig") as f:
            first = f.readline().strip()
        if first == token:
            os.remove(LOCK)
    except OSError:
        pass


def take_lock(name):
    """-> our token, or exits 3 when the lock is held by another job."""
    if os.environ.get("GYROSIM_LOCK_HELD") == "1":
        print("power_rule: GYROSIM_LOCK_HELD=1 - the caller holds %s" % LOCK, flush=True)
        return None
    token = "%s pid%d %s %s" % (name, os.getpid(), time.strftime("%Y-%m-%dT%H:%M:%S"), uuid.uuid4())
    os.makedirs(os.path.dirname(LOCK), exist_ok=True)
    try:
        fd = os.open(LOCK, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        try:
            with open(LOCK, encoding="utf-8-sig", errors="replace") as f:
                held = f.read().strip()
        except OSError:
            held = "?"
        print("lock busy: %s (%s) - not started" % (held, LOCK), flush=True)
        sys.exit(3)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(token + "\n")
    atexit.register(_release, token)
    threading.Thread(target=_refresh, args=(token,), name="lock_refresh", daemon=True).start()
    return token


def _refresh(token):
    """keep the lock's mtime fresh while it is ours (run_shots.sh stale rule), stop once it is not."""
    while True:
        time.sleep(REFRESH_S)
        try:
            with open(LOCK, encoding="utf-8-sig") as f:
                if f.readline().strip() != token:
                    return
            os.utime(LOCK, None)
        except OSError:
            return


def heavy_job(name, env=None):
    """call at the start of a heavy __main__ run: below-normal priority + the shared lock. -> default worker count."""
    low = below_normal()
    take_lock(name)
    n = workers(env)
    print("power_rule: %s holds %s, priority %s, %d workers" % (name, LOCK, "below-normal" if low else "NOT lowered (normal)", n),
          flush=True)
    return n
