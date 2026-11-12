"""Live look tuning server for the slider page (http://127.0.0.1:8767/today/busan_tune/ - static, served elsewhere).
    python -I sim/tune_server.py [--port 8768]        (127.0.0.1 only; no third-party packages)
API (JSON; CORS for the page's origin http://127.0.0.1:8767):
  GET  /api/state            {"values": defaults + live, "defaults", "live", "ranges", "render_server": bool}
  POST /api/params  {k: v}   live values -> C:/GyroSimTiles/tune/params.json (the running sim applies them within ~0.5 s,
                             unreal/GyroSim/Content/Python/tune_look.py)
  POST /api/save             live values become the defaults: unreal/GyroSim/Content/Python/tune_defaults.json
  POST /api/revert           live file = the defaults again
  POST /api/render {"view"}  asks the persistent offscreen editor (art_shots.py GYROSIM_ART_SERVE=1) for a shot with the
                             live values; waits up to 90 s -> {"img": "/api/img/<id>.png", "seconds"}
  GET  /api/img/<id>.png     the rendered PNG (C:/GyroSimTiles/tune/renders)
"""
import json, os, re, sys, threading, time, uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
TUNE = os.environ.get("GYROSIM_TUNE_DIR", r"C:\GyroSimTiles\tune")
PARAMS = os.path.join(TUNE, "params.json")
DEFAULTS = os.path.join(os.path.dirname(HERE), "unreal", "GyroSim", "Content", "Python", "tune_defaults.json")
LOCK = r"C:\GyroSimTiles\ue_offscreen.lock"
ORIGIN = "http://127.0.0.1:8767"
ALLOWED_ORIGINS = (ORIGIN, "http://localhost:8767")    # POST is refused from any other page
RENDER_LOCK = threading.Lock()                  # one render request at a time (a second click waits its turn)
# slider ranges (also in docs/grounded-day-busan.md): key -> (min, max, step, label)
RANGES = {
    "sun_az": (0, 360, 1, "해 방위 (deg, 0 = 북)"), "sun_el": (5, 80, 1, "해 높이 (deg)"),
    "sun_mult": (0.3, 2.0, 0.05, "햇빛 세기 x"), "sky_mult": (0.0, 2.0, 0.05, "하늘빛 세기 x"),
    "exposure_bias": (-2.0, 2.0, 0.1, "노출 보정 (EV)"),
    "le_shadow": (0.4, 1.2, 0.05, "로컬 노출: 그림자 대비"), "le_highlight": (0.4, 1.2, 0.05, "로컬 노출: 밝은 곳 대비"),
    "GdBase": (0.0, 0.9, 0.05, "건물 발밑 어둡게"), "GdBaseH": (1.0, 20.0, 0.5, "발밑 높이 (m)"),
    "GdGrad": (0.0, 0.9, 0.05, "건물 아래→위 어둡기"), "GdGradH": (10.0, 120.0, 5.0, "어둡기 끝나는 높이 (m)"),
    "GdFloor": (0.0, 1.0, 0.05, "트인 곳 최소 어둡기"), "GdAO": (0.0, 1.0, 0.05, "건물 하늘빛 가림 (AO)"),
    "GdTint": (0.6, 1.2, 0.02, "건물 벽 밝기 x"), "GdSat": (0.5, 1.3, 0.05, "건물 벽 채도 x"),
    "GdGroundAO": (0.0, 1.0, 0.05, "땅 하늘빛 가림 (AO)"), "GdCanyonAlb": (0.0, 1.0, 0.05, "골목 땅 어둡게"),
    "GdLeanDark": (0.0, 0.8, 0.05, "고층 발밑 땅 어둡게"),
    # ground photo v2 (11-11, docs/ground-photo-busan.md): V-World photo grade at render time (land only)
    "PhGain": (0.5, 1.2, 0.01, "땅 사진 밝기 x"), "PhGamma": (0.7, 1.5, 0.02, "땅 사진 감마 (클수록 중간톤 어둡게)"),
    "PhSat": (0.5, 1.3, 0.02, "땅 사진 채도 x"), "PhKnee": (0.2, 1.0, 0.02, "땅 사진 밝은 곳 누르기 시작 (1 = 끔)"),
    # photo relief (11-11, docs/photo-relief-busan.md): AI height from the photo -> ground normals + shadows (relief_look.py)
    "RelGain": (0.0, 40.0, 0.5, "사진 입체: 높이 배율 (m/단위, 20 = 기본)"), "RelNormal": (0.0, 3.0, 0.05, "사진 입체: 면 기울기(노멀) 세기"),
    "RelShadow": (0.0, 1.0, 0.05, "사진 입체: 그림자 세기"),
}


def _read(p):
    try:
        with open(p, encoding="utf-8-sig") as f:
            return json.load(f)
    except Exception:
        return {}


def _write(p, d):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(d, f, indent=1, ensure_ascii=False)
    os.replace(tmp, p)


def _clean(d):
    out = {}
    for k, v in d.items():
        if k in RANGES and isinstance(v, (int, float)):
            lo, hi = RANGES[k][:2]
            out[k] = max(lo, min(hi, float(v)))
    return out


def _render_server():
    try:
        with open(LOCK, encoding="utf-8-sig") as f:
            return "tune_serve" in f.read()
    except OSError:
        return False


class H(BaseHTTPRequestHandler):
    def _send(self, code, obj=None, body=None, ctype="application/json"):
        b = body if body is not None else json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(b)))
        self.send_header("Access-Control-Allow-Origin", ORIGIN)
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(b)

    def log_message(self, *a):
        pass

    def do_OPTIONS(self):
        self._send(204, body=b"")

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        if n > 65536:
            return {}
        try:
            return json.loads(self.rfile.read(n) or b"{}")
        except Exception:
            return {}

    def do_GET(self):
        if self.path == "/api/state":
            d, l = _clean(_read(DEFAULTS)), _clean(_read(PARAMS))
            return self._send(200, dict(values=dict(d, **l), defaults=d, live=l, ranges=RANGES, render_server=_render_server()))
        m = re.fullmatch(r"/api/img/([0-9a-f]{8,32})\.png", self.path.split("?", 1)[0])   # page adds ?t= cache-buster
        if m:
            p = os.path.join(TUNE, "renders", m.group(1) + ".png")
            if os.path.exists(p):
                return self._send(200, body=open(p, "rb").read(), ctype="image/png")
        self._send(404, dict(error="not found"))

    def _refuse(self):
        """-> an error reply for a POST that must not act: a browser page from another origin (a text/plain POST needs no
        preflight, so CORS alone does not stop it) or a body that is not JSON. No Origin = curl / python, allowed."""
        org = self.headers.get("Origin")
        if org and org.rstrip("/") not in ALLOWED_ORIGINS:
            return 403, "origin not allowed"
        n = int(self.headers.get("Content-Length") or 0)
        ctype = (self.headers.get("Content-Type") or "").split(";")[0].strip().lower()
        if n > 0 and ctype != "application/json":
            return 415, "Content-Type must be application/json"
        return None

    def do_POST(self):
        bad = self._refuse()
        if bad:
            return self._send(bad[0], dict(error=bad[1]))
        if self.path == "/api/params":
            v = dict(_clean(_read(PARAMS)), **_clean(self._body()))
            _write(PARAMS, v)
            return self._send(200, dict(ok=True, live=v))
        if self.path == "/api/save":
            cur = _read(DEFAULTS)
            note = cur.get("_note")
            new = dict(_clean(cur), **_clean(_read(PARAMS)))
            if note:
                new = dict(_note=note, **new)
            new["_saved"] = time.strftime("%Y-%m-%d %H:%M:%S")
            _write(DEFAULTS, new)
            return self._send(200, dict(ok=True, defaults=new))
        if self.path == "/api/revert":
            d = _clean(_read(DEFAULTS))
            _write(PARAMS, d)
            return self._send(200, dict(ok=True, live=d))
        if self.path == "/api/render":
            if not _render_server():
                return self._send(503, dict(error="렌더 서버(오프스크린 UE)가 꺼져 있음"))
            b = self._body()
            if not RENDER_LOCK.acquire(timeout=120):
                return self._send(503, dict(error="다른 렌더가 아직 진행 중"))
            try:
                return self._render(b)
            finally:
                RENDER_LOCK.release()
        self._send(404, dict(error="not found"))

    def _render(self, b):
            rid = uuid.uuid4().hex[:16]
            _write(os.path.join(TUNE, "render_req.json"), dict(id=rid, view=str(b.get("view", "n5_gwangan_500"))[:64], res="1920x1080"))
            t0 = time.time()
            while time.time() - t0 < 90:
                d = _read(os.path.join(TUNE, "render_done.json"))
                if d.get("id") == rid:
                    ok = bool(d.get("file"))
                    return self._send(200 if ok else 500, dict(img="/api/img/%s.png" % rid if ok else None, seconds=d.get("seconds")))
                time.sleep(0.25)
            return self._send(504, dict(error="시간 초과 (90 초) - 렌더 서버 로그: C:/GyroSimTiles/tune/ue_serve.log"))


def main():
    port = int(sys.argv[sys.argv.index("--port") + 1]) if "--port" in sys.argv else 8768
    os.makedirs(TUNE, exist_ok=True)
    ThreadingHTTPServer(("127.0.0.1", port), H).serve_forever()


if __name__ == "__main__":
    main()
