"""V-World photo source for the OFFSCREEN shot scripts (developer checks, no sim server): the same white-gap selection as
Play (sim/vworld_proxy.py, GYROSIM_VW_GAPFIX). template() starts a cache-only proxy instance of sim/vworld_proxy.py
(system Python, hidden, never calls the API, never reads the key, exits when this editor exits) on a free 127.0.0.1 port
and returns its URL template; GYROSIM_VW_GAPFIX=0 or any failure -> the plain cache by file:// as before (read only).
The proxy answers with no-store, so Cesium keeps no copy in cesium-request-cache.sqlite."""
import os, shutil, socket, subprocess, sys, time
import unreal

FILE_TEMPLATE = "file:///C:/GyroSimTiles/vworld/Satellite/{z}/{reverseY}/{x}.jpg"
REPO = os.path.abspath(os.path.join(unreal.Paths.project_dir(), "..", ".."))
_port = None


def _free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def _up(port, t=12.0):
    t0 = time.time()
    while time.time() - t0 < t:
        try:
            socket.create_connection(("127.0.0.1", port), 0.5).close()
            return True
        except OSError:
            time.sleep(0.3)
    return False


def template(log=unreal.log):
    global _port
    if os.environ.get("GYROSIM_VW_GAPFIX", "1") == "0":
        log("[photo_src] gap fix off: file:// cache")
        return FILE_TEMPLATE
    if _port is None:
        py = os.environ.get("GYROSIM_SYS_PYTHON") or shutil.which("python") or shutil.which("py")
        if not py:
            log("[photo_src] no system python: file:// cache")
            return FILE_TEMPLATE
        port = _free_port()
        try:
            subprocess.Popen([py, os.path.join(REPO, "sim", "vworld_proxy.py"), "--cache-only-port", str(port), "--parent-pid", str(os.getpid())],
                             cwd=REPO, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                             creationflags=0x08000000 if sys.platform == "win32" else 0)     # CREATE_NO_WINDOW
        except OSError as e:
            log("[photo_src] proxy start failed %r: file:// cache" % (e,))
            return FILE_TEMPLATE
        if not _up(port):
            log("[photo_src] proxy not up: file:// cache")
            return FILE_TEMPLATE
        _port = port
        log("[photo_src] cache-only proxy with gap fix on port %d" % port)
    return "http://127.0.0.1:%d/vworld/sat/{z}/{reverseY}/{x}.jpg" % _port
