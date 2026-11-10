"""Local V-World (브이월드) aerial-photo tile proxy for the Unreal client's `vworld` ground mode.

    python sim/vworld_proxy.py                 run it on its own (127.0.0.1 only)
    python sim/vworld_proxy.py --status        print the usage / budget / cache state and exit (no API call)
    python sim/vworld_proxy.py --selftest      check the rules against a fake upstream (no V-World request at all)
    python sim/vworld_proxy.py --prefetch      slow cache fill - REFUSES to run unless permitted (see TERMS below)
    python sim/vworld_proxy.py --make-attribution   redraw sim/vworld_attribution.png (on-screen source note)
    sim/server.py starts it in a thread by itself when Config/cesium_token.txt selects `vworld`.

Unreal (Cesium CesiumUrlTemplateRasterOverlay) asks  http://127.0.0.1:<port>/vworld/sat/{z}/{reverseY}/{x}.jpg
(reverseY = Google row, north = 0, = V-World WMTS TileRow). The proxy is the only place that knows the key: it reads
unreal/GyroSim/Config/vworld_key.txt (git-ignored; the repo is PUBLIC) and never prints / logs / writes it (every log
line goes through _safe(), which masks it as <KEY>).

Rules (docs/vworld-integration.md section 2; all values configurable in unreal/GyroSim/Config/vworld_proxy.json,
example: sim/vworld_proxy.example.json):
  - call the API as little as possible: disk cache first, at most `rate_per_s` (4) requests/s and `concurrency` (4) at
    once, `daily_budget` (2000) requests per day (Korean time, resets at 00:00 KST), online only up to
    `max_online_zoom` (16), only inside Korea, never below zoom 6 (V-World has 6-19).
  - a reply is a tile only if it is a real JPEG (FF D8 FF): V-World sends errors as HTTP 200 + XML.
    OVER_REQUEST_LIMIT / INVALID_KEY / UNAVAILABLE_KEY (or the Korean "unregistered key" text) -> no more API calls
    until the next 00:00 KST (persisted, survives restarts). FileNotFound / 404 -> remembered as empty, not asked
    again. Other errors / network / HTTP 429 / 5xx -> exponential back-off 1, 2, 4 ... 300 s for all requests, and a
    tile that failed 3 times is not asked again for 24 h.
  - status 'derived' rows = tiles made locally by sim/vworld_fill.py --derive (2x2 cached children -> 1 parent, no API
    call); served like cached tiles, never fetched over.
  - when a tile cannot be fetched (budget, back-off, cache-only, zoom > 16 ...): the tile from the cache -> a lower-zoom
    cached tile cut out and upscaled -> a plain blank tile. Fallback replies carry no-store so Cesium asks again later.
    Out of Korea and zoom 0-5 are always the blank tile (no Sentinel-2 or other imagery is ever mixed in: terms 14).
  - white no-data gaps (11-10, GYROSIM_VW_GAPFIX=0 = off): some V-World z16-z19 tiles carry a pure-white band where two
    photo sets meet (Busan: an east-west seam at ~35.25 N, ~700 tiles; it draped over 금정산 as a "white road").
    A cached tile with white full rows / columns (gap_fraction >= GAP_MIN) is not served; the same "lower-zoom tile cut
    out and upscaled" fallback is, from the first ancestor whose cut-out has no gap (source 'gapfix', no-store). The
    stored tiles are never changed (terms 13조 10항 / 19조 4항: display-time choice of which V-World tile to show only).
    Results are remembered in <cache_dir>/gapfix.json (per tile file size + mtime).
    Offscreen shots: `python -I sim/vworld_proxy.py --cache-only-port <port> --parent-pid <pid>` = a cache-only instance
    (never calls the API, never reads the key) that exits with its parent (Content/Python/photo_src.py starts it).
TERMS (V-World 이용약관 19조 "오픈플랫폼에서 제공되는 데이터는 무단으로 저장하지 못합니다", 18조):
  - `permanent_cache` is OFF by default: every cached tile is deleted when the server's Cache-Control max-age has run
    out (259200 s = 3 days, measured), counted from the download.
  - Turn `permanent_cache` (and `prefetch_enabled`) on ONLY after written permission from 공간정보산업진흥원
    (V-World operator; 1661-0115, vworld@spacen.or.kr). The prefetch job refuses to run unless both are on.
  - the cache lives outside the repo (default C:\\GyroSimTiles\\vworld) and must never be committed (19조, 측량성과 국외
    반출): .gitignore also blocks GyroSimTiles/ and tile_cache/ in case it is pointed into the repo.
Usage log: <cache_dir>/usage.json (today's count, stop state) and usage.jsonl (one line per API request, no key).
"""
import io, json, os, re, sqlite3, sys, threading, time, urllib.error, urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
UE_CONFIG = os.path.join(REPO, "unreal", "GyroSim", "Config")
KEY_FILE = os.path.join(UE_CONFIG, "vworld_key.txt")
CONFIG_FILE = os.path.join(UE_CONFIG, "vworld_proxy.json")
UPSTREAM = "https://api.vworld.kr/req/wmts/1.0.0/{key}/{layer}/{z}/{y}/{x}.jpeg"     # TileMatrix / TileRow / TileCol

DEFAULTS = dict(
    port=8790,                       # 127.0.0.1 only (8765 from the research note is taken by another local tool here)
    mode="online",                   # online | cache-only (never calls the API) | off (blank tiles only)
    cache_dir=r"C:\GyroSimTiles\vworld",
    permanent_cache=False,           # TERMS 19조: ON only after written permission from 공간정보산업진흥원
    prefetch_enabled=False,          # TERMS: same; the prefetch job also needs permanent_cache
    rate_per_s=4.0,
    concurrency=4,
    daily_budget=2000,
    max_online_zoom=16,
    min_zoom=6,                      # V-World Satellite has 6-19
    korea_bbox=[124.5, 32.8, 132.0, 38.9],     # lon W, lat S, lon E, lat N (incl. Jeju, Ulleungdo, Dokdo)
    layer="Satellite",
    referer="",                      # V-World does not check it today (measured); set if that changes
    default_max_age=259200,          # used when the reply has no Cache-Control max-age
    queue_wait_s=12.0,               # longest a request waits for a rate-limit slot before it gets the fallback
    timeout_s=10.0,
    blank_rgb=[74, 84, 66],          # plain tile colour (dull land)
    prefetch_reserve=500,            # prefetch leaves this many of the daily budget for flying
)
STOP_CODES = ("OVER_REQUEST_LIMIT", "INVALID_KEY", "UNAVAILABLE_KEY", "등록되지 않은 인증키", "사용할 수 없는 인증키", "일일 제한")
EMPTY_CODES = ("FileNotFound", "FILE_NOT_FOUND", "NOT_FOUND")
KST = 9 * 3600
GAPFIX = os.environ.get("GYROSIM_VW_GAPFIX", "1") != "0"
GAP_MIN = 0.03                       # fraction of full white rows / columns (seam tile 19/207217/450086 = 0.64; white roofs 0)
GAP_ZMIN = 14

try:
    from PIL import Image
except ImportError:                  # no PIL: no upscaled parent tiles, blank = 404
    Image = None


def load_config(path=CONFIG_FILE):
    cfg = dict(DEFAULTS)
    try:
        with open(path, encoding="utf-8-sig") as f:
            user = json.load(f)
        cfg.update({k: v for k, v in user.items() if not k.startswith("_")})
    except OSError:
        pass
    except ValueError as e:
        print("vworld_proxy: bad config %s (%s) - using defaults" % (path, e), flush=True)
    return cfg


def read_key(path=KEY_FILE):
    try:
        with open(path, encoding="utf-8-sig") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#"):
                    return line
    except OSError:
        pass
    return None


def kst_day(t=None):
    return time.strftime("%Y-%m-%d", time.gmtime((time.time() if t is None else t) + KST))


def next_kst_midnight(t=None):
    t = time.time() if t is None else t
    return (int((t + KST) // 86400) + 1) * 86400 - KST


def gap_fraction(im, lo=250, frac=0.98):
    """no-data gap measure of a PIL image: the larger of the fractions of rows / columns that are >= 98 % pure white
    (L >= 250). White roofs score 0 (texture, never whole rows); the V-World seam bands score their height."""
    import numpy as np
    a = np.asarray(im.convert("L")) >= lo
    if a.size == 0:
        return 0.0
    return float(max((a.mean(1) >= frac).mean(), (a.mean(0) >= frac).mean()))


def tile_lonlat_box(z, y, x):
    """(lon W, lat S, lon E, lat N) of a Web-Mercator tile, y = row from the north."""
    import math
    n = 2 ** z

    def lat(r):
        return math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * r / n))))
    return x / n * 360 - 180, lat(y + 1), (x + 1) / n * 360 - 180, lat(y)


class Proxy:
    def __init__(self, cfg=None, key=None, upstream=UPSTREAM, role="flight"):
        self.cfg = cfg or load_config()
        self.role = role                     # flight (Unreal) | fill (sim/vworld_fill.py): fill requests are counted apart
        self.last_rec = None                 # the last upstream request record (usage.jsonl line), for the filler
        self.key = key if key is not None else read_key()
        self.upstream = upstream
        self.dir = self.cfg["cache_dir"]
        self.tiles = os.path.join(self.dir, self.cfg["layer"])
        os.makedirs(self.tiles, exist_ok=True)
        self.lock = threading.RLock()
        self.db = sqlite3.connect(os.path.join(self.dir, "index.sqlite"), check_same_thread=False)
        self.db.execute("CREATE TABLE IF NOT EXISTS t (z INT, y INT, x INT, fetched REAL, max_age REAL, status TEXT, fails INT DEFAULT 0, "
                        "retry_after REAL DEFAULT 0, PRIMARY KEY (z, y, x))")
        self.db.commit()
        self.usage_path = os.path.join(self.dir, "usage.json")
        self.usage = self._load_usage()
        self.sem = threading.BoundedSemaphore(max(1, int(self.cfg["concurrency"])))
        self.bucket, self.bucket_t = 1.0, time.monotonic()
        self.backoff_s, self.backoff_until = 0.0, 0.0
        self.served = dict(cache=0, online=0, parent=0, blank=0, gapfix=0)
        self.gap_path = os.path.join(self.dir, "gapfix.json")
        try:
            with open(self.gap_path, encoding="utf-8") as f:
                self.gaps = json.load(f)
        except (OSError, ValueError):
            self.gaps = {}
        self.gaps_new = 0
        self.served_z = {}
        self.session_api = 0
        self._blank = None
        self.last_cleanup = 0.0
        self.cleanup()

    # ---- helpers -------------------------------------------------------------------------------------------------
    def _safe(self, s):
        s = str(s)
        return s.replace(self.key, "<KEY>") if self.key else s

    def log(self, *a):
        print(self._safe("vworld_proxy: " + " ".join(str(x) for x in a)), flush=True)

    def _load_usage(self):
        try:
            with open(self.usage_path, encoding="utf-8") as f:
                u = json.load(f)
        except (OSError, ValueError):
            u = {}
        if u.get("day") != kst_day():
            u = dict(day=kst_day(), count=0, errors=0, fill_count=0, stop_until=u.get("stop_until", 0), stop_reason=u.get("stop_reason"))
        return u

    def _sync_usage(self):
        """merge usage.json written by another process (flight proxy + filler run apart): counts and stop take the max."""
        try:
            with open(self.usage_path, encoding="utf-8") as f:
                u = json.load(f)
        except (OSError, ValueError):
            return
        if u.get("day") == self.usage.get("day"):
            for k in ("count", "errors", "fill_count"):
                self.usage[k] = max(self.usage.get(k, 0), u.get(k, 0))
        if u.get("stop_until", 0) > self.usage.get("stop_until", 0):
            self.usage.update(stop_until=u["stop_until"], stop_reason=u.get("stop_reason"))

    def flight_count(self):
        """today's requests that count against `daily_budget`: the flight proxy's own (filler requests excluded - the
        filler has its own day plan from the observed server limit, sim/vworld_fill.py), all of them for the filler."""
        c = self.usage.get("count", 0)
        return c - self.usage.get("fill_count", 0) if self.role == "flight" else c

    def _save_usage(self):
        tmp = self.usage_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self.usage, f, ensure_ascii=False)
        os.replace(tmp, self.usage_path)

    def _roll_day(self):
        if self.usage.get("day") != kst_day():
            self.usage.update(day=kst_day(), count=0, errors=0, fill_count=0)
            self._save_usage()

    def _path(self, z, y, x):
        return os.path.join(self.tiles, str(z), str(y), "%d.jpg" % x)

    def _row(self, z, y, x):
        with self.lock:                      # one sqlite connection shared by the handler threads
            return self.db.execute("SELECT fetched, max_age, status, fails, retry_after FROM t WHERE z=? AND y=? AND x=?", (z, y, x)).fetchone()

    def _fresh(self, row, now):
        return row is not None and (self.cfg["permanent_cache"] or row[0] + row[1] > now)

    def cleanup(self):
        """TERMS 19: delete every tile whose server max-age (3 days) has run out, unless permanent_cache is on."""
        now = time.time()
        self.last_cleanup = now
        if self.cfg["permanent_cache"]:
            return 0
        with self.lock:
            old = self.db.execute("SELECT z, y, x FROM t WHERE status IN ('ok', 'empty', 'derived') AND fetched + max_age <= ?", (now,)).fetchall()
            for z, y, x in old:
                try:
                    os.remove(self._path(z, y, x))
                except OSError:
                    pass
            self.db.execute("DELETE FROM t WHERE status IN ('ok', 'empty', 'derived') AND fetched + max_age <= ?", (now,))
            self.db.execute("DELETE FROM t WHERE status = 'fail' AND retry_after < ? AND fails >= 3", (now,))
            self.db.commit()
        if old:
            self.log("expired tiles deleted:", len(old))
        return len(old)

    def in_korea(self, z, y, x):
        w, s, e, n = tile_lonlat_box(z, y, x)
        W, S, E, N = self.cfg["korea_bbox"]
        return e > W and w < E and n > S and s < N

    def blank(self):
        if self._blank is None and Image is not None:
            b = io.BytesIO()
            Image.new("RGB", (256, 256), tuple(self.cfg["blank_rgb"])).save(b, "JPEG", quality=80)
            self._blank = b.getvalue()
        return self._blank

    def online_state(self):
        """(allowed, reason) for calling the API now."""
        self._roll_day()
        now = time.time()
        if self.cfg["mode"] != "online":
            return False, "mode " + self.cfg["mode"]
        if not self.key:
            return False, "no key file"
        if self.usage.get("stop_until", 0) > now:
            return False, "stopped for today: %s" % self.usage.get("stop_reason")
        if self.flight_count() >= int(self.cfg["daily_budget"]):
            return False, "daily budget used (%d)" % self.flight_count()
        if self.backoff_until > now:
            return False, "back-off %.0f s" % (self.backoff_until - now)
        return True, "online"

    def _take_slot(self):
        """token bucket, rate_per_s; False if no slot within queue_wait_s."""
        t_end = time.monotonic() + float(self.cfg["queue_wait_s"])
        rate = float(self.cfg["rate_per_s"])
        while True:
            with self.lock:
                now = time.monotonic()
                self.bucket = min(1.0, self.bucket + (now - self.bucket_t) * rate)
                self.bucket_t = now
                if self.bucket >= 1.0:
                    self.bucket -= 1.0
                    return True
                wait = (1.0 - self.bucket) / rate
            if time.monotonic() + wait > t_end:
                return False
            time.sleep(wait)

    # ---- the API call ------------------------------------------------------------------------------------------------
    def _fetch(self, z, y, x):
        """one upstream request (counted). Returns (kind, data, max_age) kind = tile | empty | stop | error | skipped."""
        url = self.upstream.format(key=self.key, layer=self.cfg["layer"], z=z, y=y, x=x)
        hdr = {"User-Agent": "GyroSim-tile-proxy/1"}
        if self.cfg.get("referer"):
            hdr["Referer"] = self.cfg["referer"]
        with self.lock:                      # check + count in one step (parallel requests must not overrun the budget)
            self._sync_usage()
            if not self.online_state()[0]:
                return "skipped", b"", 0.0
            self.usage["count"] += 1
            if self.role == "fill":
                self.usage["fill_count"] = self.usage.get("fill_count", 0) + 1
            self.session_api += 1
            self._save_usage()
        t0 = time.monotonic()
        code, data, max_age, note = None, b"", None, ""
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=hdr), timeout=float(self.cfg["timeout_s"])) as r:
                code, data = r.status, r.read()
                m = re.search(r"max-age=(\d+)", r.headers.get("Cache-Control", "") or "")
                max_age = float(m.group(1)) if m else None
        except urllib.error.HTTPError as e:
            code = e.code
            try:
                data = e.read()
            except Exception:
                data = b""
        except Exception as e:                                   # network: no URL in the message (key safe), masked anyway
            note = type(e).__name__
        if data[:3] == b"\xff\xd8\xff" and code == 200:
            kind = "tile"
        else:
            txt = data[:4000].decode("utf-8", "replace")
            if any(c in txt for c in STOP_CODES):
                kind = "stop"
                note = next(c for c in STOP_CODES if c in txt)
            elif code == 404 or any(c in txt for c in EMPTY_CODES):
                kind = "empty"
            else:
                kind = "error"
                m = re.search(r'code="([^"]+)"|<(?:ows:)?ExceptionText>([^<]{0,80})', txt)
                note = note or (m.group(1) or m.group(2) if m else "") or ("HTTP %s, %d bytes" % (code, len(data)))
        rec = dict(t=time.strftime("%Y-%m-%d %H:%M:%S"), z=z, y=y, x=x, http=code, kind=kind, bytes=len(data),
                   ms=round((time.monotonic() - t0) * 1000), note=self._safe(note), role=self.role)
        if kind != "tile":                   # error text for the filler's rate / limit check (key masked)
            rec["text"] = self._safe(re.sub(r"\s+", " ", data[:300].decode("utf-8", "replace")))
        self.last_rec = rec
        with self.lock:
            if kind in ("stop", "error"):
                self.usage["errors"] = self.usage.get("errors", 0) + 1
            if kind == "stop":
                self.usage.update(stop_until=next_kst_midnight(), stop_reason=self._safe(note))
                self.log("API stopped until 00:00 KST:", note)
            self._save_usage()
            try:
                with open(os.path.join(self.dir, "usage.jsonl"), "a", encoding="utf-8") as f:
                    f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            except OSError:
                pass
        return kind, data, max_age or float(self.cfg["default_max_age"])

    def gap(self, z, y, x, path=None, data=None):
        """gap_fraction of the cached tile z/y/x (memo + gapfix.json, keyed by file size and mtime). 0 when unknown."""
        if Image is None:
            return 0.0
        path = path or self._path(z, y, x)
        try:
            st = os.stat(path)
        except OSError:
            return 0.0
        k = "%d/%d/%d" % (z, y, x)
        e = self.gaps.get(k)
        if e and e[0] == st.st_size and abs(e[1] - st.st_mtime) < 1.0:
            return e[2]
        try:
            im = Image.open(io.BytesIO(data) if data is not None else path)
            g = round(gap_fraction(im), 4)
        except OSError:
            return 0.0
        with self.lock:
            self.gaps[k] = [st.st_size, st.st_mtime, g]
            self.gaps_new += 1
            if self.gaps_new >= 200:
                self.save_gaps()
        return g

    def save_gaps(self):
        with self.lock:
            try:
                tmp = self.gap_path + ".%d.tmp" % os.getpid()
                with open(tmp, "w", encoding="utf-8") as f:
                    json.dump(self.gaps, f, separators=(",", ":"))
                os.replace(tmp, self.gap_path)
                self.gaps_new = 0
            except OSError as e:
                self.log("gapfix.json not saved", repr(e))

    def _parent(self, z, y, x, now):
        """a cached lower-zoom tile, cut out and upscaled to 256 px (no-store), or None. With GAPFIX a cut-out that holds
        a white no-data band is skipped (next ancestor)."""
        if Image is None:
            return None
        for dz in range(1, 7):
            pz = z - dz
            if pz < self.cfg["min_zoom"]:
                break
            py, px = y >> dz, x >> dz
            row = self._row(pz, py, px)
            if row is None or row[2] not in ("ok", "derived") or not self._fresh(row, now):
                continue
            try:
                im = Image.open(self._path(pz, py, px)).convert("RGB")
                n, s = 2 ** dz, 256 / 2 ** dz
                ox, oy = (x - px * n) * s, (y - py * n) * s
                im = im.crop((int(ox), int(oy), int(ox + s), int(oy + s)))
                if GAPFIX and gap_fraction(im, 235, 0.9) > 0.0:    # any (near) white row / column in the cut-out: next ancestor
                    continue                                        # (locally derived parents carry the seam, blurred)
                im = im.resize((256, 256), Image.BILINEAR)
                b = io.BytesIO()
                im.save(b, "JPEG", quality=85)
                return b.getvalue()
            except OSError:
                continue
        return None

    def get(self, z, y, x):
        """-> (bytes or None, source, cacheable). source = cache | online | parent | blank."""
        now = time.time()
        if now - self.last_cleanup > 600:
            self.cleanup()
        c = self.cfg
        if self.cfg["mode"] == "off" or z < c["min_zoom"] or z > 19 or not self.in_korea(z, y, x):
            return self.blank(), "blank", False
        with self.lock:
            row = self._row(z, y, x)
        if row is not None and self._fresh(row, now):
            if row[2] == "empty":
                return self.blank(), "blank", False
            try:
                with open(self._path(z, y, x), "rb") as f:
                    data = f.read()
                if GAPFIX and z >= GAP_ZMIN and self.gap(z, y, x, data=data) >= GAP_MIN:
                    p = self._parent(z, y, x, now)               # white no-data band: an ancestor without the gap
                    if p is not None:
                        return p, "gapfix", False
                return data, "cache", True
            except OSError:
                row = None
        blocked = row is not None and row[2] == "fail" and row[4] > now
        ok, why = self.online_state()
        if ok and not blocked and z <= c["max_online_zoom"]:
            with self.sem:
                ok, why = self.online_state()                  # may have changed while waiting
                if ok and self._take_slot():
                    kind, data, max_age = self._fetch(z, y, x)
                    with self.lock:
                        if kind == "tile":
                            p = self._path(z, y, x)
                            os.makedirs(os.path.dirname(p), exist_ok=True)
                            with open(p + ".tmp", "wb") as f:
                                f.write(data)
                            os.replace(p + ".tmp", p)
                            self.db.execute("INSERT OR REPLACE INTO t VALUES (?, ?, ?, ?, ?, 'ok', 0, 0)", (z, y, x, time.time(), max_age))
                            self.backoff_s = 0.0
                        elif kind == "empty":
                            self.db.execute("INSERT OR REPLACE INTO t VALUES (?, ?, ?, ?, ?, 'empty', 0, 0)", (z, y, x, time.time(), max_age))
                        elif kind == "error":
                            self.backoff_s = min(300.0, max(1.0, self.backoff_s * 2))
                            self.backoff_until = time.time() + self.backoff_s
                            fails = (row[3] if row is not None and row[2] == "fail" else 0) + 1
                            self.db.execute("INSERT OR REPLACE INTO t VALUES (?, ?, ?, 0, 0, 'fail', ?, ?)",
                                            (z, y, x, fails, time.time() + 86400 if fails >= 3 else 0))
                            self.log("upstream error, back-off %.0f s (tile %d/%d/%d fail %d)" % (self.backoff_s, z, y, x, fails))
                        self.db.commit()
                    if kind == "tile":
                        return data, "online", True
                    if kind == "empty":
                        return self.blank(), "blank", False
        p = self._parent(z, y, x, now)
        if p is not None:
            return p, "parent", False
        return self.blank(), "blank", False

    def status(self):
        with self.lock:
            self._sync_usage()
        ok, why = self.online_state()
        with self.lock:
            n = self.db.execute("SELECT COUNT(*) FROM t WHERE status IN ('ok', 'derived')").fetchone()[0]
        u = self.usage
        return dict(service="vworld_proxy", mode=self.cfg["mode"], online=ok, why=why, day=u.get("day"), used_today=u.get("count", 0),
                    budget=int(self.cfg["daily_budget"]), left=max(0, int(self.cfg["daily_budget"]) - self.flight_count()),
                    fill_today=u.get("fill_count", 0),
                    errors_today=u.get("errors", 0), stop_until=u.get("stop_until", 0), stop_reason=u.get("stop_reason"),
                    session_api=self.session_api, served=dict(self.served), served_z=dict(sorted(self.served_z.items())), cache_tiles=n, permanent_cache=bool(self.cfg["permanent_cache"]),
                    max_online_zoom=self.cfg["max_online_zoom"], has_key=bool(self.key),
                    terrain=os.path.exists(os.path.join(TERRAIN_DIR, "layer.json")),
                    buildings=os.path.exists(os.path.join(BUILDINGS_DIR, "tileset.json")))


TILE_RE = re.compile(r"^/vworld/sat/(\d+)/(\d+)/(\d+)\.jpe?g$")
TERRAIN_RE = re.compile(r"^/terrain/(\d+)/(\d+)/(\d+)\.terrain$")
# local South Korea terrain (Copernicus DEM GLO-30 -> quantized-mesh, sim/terrain_build.py), served from disk next to
# the photos so the Unreal 'vworld' mode needs one local port. No upstream request ever (the files are built offline).
TERRAIN_DIR = os.path.join(os.environ.get("GYROSIM_TERRAIN", r"C:\GyroSimTiles\terrain"), "tiles")


def terrain_file(path):
    """/terrain/layer.json or /terrain/{z}/{x}/{y}.terrain -> (file, content type) or None (no path tricks possible:
    only these two patterns, numbers only)."""
    if path == "/terrain/layer.json":
        return os.path.join(TERRAIN_DIR, "layer.json"), "application/json"
    m = TERRAIN_RE.match(path)
    if m:
        z, x, y = m.groups()
        return os.path.join(TERRAIN_DIR, z, x, y + ".terrain"), "application/vnd.quantized-mesh"
    return None


BUILDINGS_RE = re.compile(r"^/buildings/([abc])/(-?\d+)_(-?\d+)\.glb$")
# local 3D buildings (국토교통부 GIS건물통합정보 -> 3D Tiles, sim/buildings_build.py), also built offline, no upstream request
BUILDINGS_DIR = os.path.join(os.environ.get("GYROSIM_BUILDINGS", r"C:\GyroSimTiles\buildings"), "tiles")


def buildings_file(path):
    """/buildings/tileset.json or /buildings/{a|b|c}/{i}_{j}.glb -> (file, content type) or None (numbers only)."""
    if path == "/buildings/tileset.json":
        return os.path.join(BUILDINGS_DIR, "tileset.json"), "application/json"
    m = BUILDINGS_RE.match(path)
    if m:
        lvl, i, j = m.groups()
        return os.path.join(BUILDINGS_DIR, lvl, "%s_%s.glb" % (i, j)), "model/gltf-binary"
    return None


def make_handler(px):
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _send(self, code, body, ctype, cache):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", cache)
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            path = self.path.split("?")[0]
            try:
                if path in ("/status", "/vworld/status"):
                    return self._send(200, json.dumps(px.status(), ensure_ascii=False).encode(), "application/json", "no-store")
                tf = terrain_file(path) if path.startswith("/terrain/") else buildings_file(path) if path.startswith("/buildings/") else None
                if tf:
                    try:
                        with open(tf[0], "rb") as f:
                            body = f.read()
                    except OSError:
                        return self._send(404, b"no local tile", "text/plain", "no-store")
                    kind = "terrain" if path.startswith("/terrain/") else "buildings"
                    with px.lock:
                        px.served[kind] = px.served.get(kind, 0) + 1
                    # tiles are gzip files sent as they are: Cesium's GunzipAssetAccessor unpacks them (gzip magic)
                    return self._send(200, body, tf[1], "no-store")
                m = TILE_RE.match(path)
                if not m:
                    return self._send(404, b"not found", "text/plain", "no-store")
                z, y, x = (int(v) for v in m.groups())
                if not (0 <= x < 2 ** z and 0 <= y < 2 ** z):
                    return self._send(404, b"bad tile", "text/plain", "no-store")
                data, src, _ = px.get(z, y, x)
                with px.lock:
                    px.served[src] = px.served.get(src, 0) + 1
                    px.served_z["%d_%s" % (z, src)] = px.served_z.get("%d_%s" % (z, src), 0) + 1     # zoom x source (checks: is z19 used?)
                if data is None:
                    return self._send(404, b"no tile", "text/plain", "no-store")
                # no-store everywhere: Cesium keeps no second copy (TERMS 19), and fallback tiles get asked for again
                self.send_response(200)
                self.send_header("Content-Type", "image/jpeg")
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Cache-Control", "no-store")
                self.send_header("X-Tile-Source", src)
                self.end_headers()
                self.wfile.write(data)
            except (BrokenPipeError, ConnectionResetError):
                pass
            except Exception as e:
                px.log("handler error", repr(e))
                try:
                    self._send(500, b"error", "text/plain", "no-store")
                except Exception:
                    pass
    return H


def serve(cfg=None, px=None, block=True):
    px = px or Proxy(cfg)
    srv = ThreadingHTTPServer(("127.0.0.1", int(px.cfg["port"])), make_handler(px))
    srv.daemon_threads = True
    ok, why = px.online_state()
    px.log("listening on http://127.0.0.1:%d/vworld/sat/{z}/{y}/{x}.jpg  key %s, %s, used today %d / %d, cache %s, permanent_cache %s" % (
        px.cfg["port"], "found" if px.key else "MISSING", why, px.usage.get("count", 0), px.cfg["daily_budget"], px.dir, px.cfg["permanent_cache"]))
    if block:
        srv.serve_forever()
    else:
        threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, px


def start_in_thread():
    """for sim/server.py: start unless another proxy already owns the port. Returns the Proxy or None."""
    try:
        return serve(block=False)[1]
    except OSError as e:
        print("vworld_proxy: not started here (%s) - another proxy running?" % e, flush=True)
        return None


def ground_mode_is_vworld():
    if os.environ.get("GYROSIM_GROUND"):             # developer checks: the ground mode without editing Config/cesium_token.txt
        return os.environ["GYROSIM_GROUND"].strip().lower() == "vworld"
    try:
        with open(os.path.join(UE_CONFIG, "cesium_token.txt"), encoding="utf-8-sig") as f:
            return any(l.strip().lower() == "vworld" for l in f)
    except OSError:
        return False


ATTRIB_TEXT = "지도: 브이월드(V-World), 국토교통부"
ATTRIB_PNG = os.path.join(HERE, "vworld_attribution.png")


def make_attribution(path=ATTRIB_PNG):
    """the on-screen source note (V-World terms 13조) as a PNG (Korean font; the Unreal canvas font has no Hangul).
    Committed (our own text, no map data); sim_client shows it in the vworld ground mode."""
    from PIL import ImageDraw, ImageFont
    W, H = 1024, 96
    im = Image.new("RGB", (W, H), (10, 12, 14))
    g = ImageDraw.Draw(im)
    f = ImageFont.truetype(r"C:\Windows\Fonts\malgunbd.ttf", 54)
    g.text((W / 2, H / 2), ATTRIB_TEXT, font=f, fill=(235, 238, 240), anchor="mm")
    im.save(path)
    make_terrain_attribution()
    return path


TERRAIN_ATTRIB_PNG = os.path.join(HERE, "vworld_terrain_attribution.png")
TERRAIN_ATTRIB_LINES = ("지형: Copernicus DEM GLO-30 © DLR e.V. 2010-2014 and © Airbus Defence and Space GmbH 2014-2018",
                        "provided under COPERNICUS by the European Union and ESA; all rights reserved")


def make_terrain_attribution(path=TERRAIN_ATTRIB_PNG):
    """V-World note + the Copernicus DEM credit (required by its licence) for the vworld mode on the local terrain."""
    from PIL import ImageDraw, ImageFont
    W, H = 1600, 200
    im = Image.new("RGB", (W, H), (10, 12, 14))
    g = ImageDraw.Draw(im)
    g.text((W / 2, 48), ATTRIB_TEXT, font=ImageFont.truetype(r"C:\Windows\Fonts\malgunbd.ttf", 54), fill=(235, 238, 240), anchor="mm")
    f = ImageFont.truetype(r"C:\Windows\Fonts\malgun.ttf", 30)
    for i, t in enumerate(TERRAIN_ATTRIB_LINES):
        g.text((W / 2, 116 + 44 * i), t, font=f, fill=(215, 220, 224), anchor="mm")
    im.save(path)
    make_buildings_attribution()
    return path


BLDG_ATTRIB_PNG = os.path.join(HERE, "vworld_buildings_attribution.png")
BLDG_ATTRIB_LINE = "건물: 국토교통부 GIS건물통합정보 (CC BY)"


def make_buildings_attribution(path=BLDG_ATTRIB_PNG):
    """the terrain plate + the building data credit (sim/buildings_build.py tiles shown)."""
    from PIL import ImageDraw, ImageFont
    W, H = 1600, 250
    im = Image.new("RGB", (W, H), (10, 12, 14))
    g = ImageDraw.Draw(im)
    g.text((W / 2, 48), ATTRIB_TEXT, font=ImageFont.truetype(r"C:\Windows\Fonts\malgunbd.ttf", 54), fill=(235, 238, 240), anchor="mm")
    f = ImageFont.truetype(r"C:\Windows\Fonts\malgun.ttf", 30)
    for i, t in enumerate((BLDG_ATTRIB_LINE,) + TERRAIN_ATTRIB_LINES):
        g.text((W / 2, 116 + 44 * i), t, font=f, fill=(215, 220, 224), anchor="mm")
    im.save(path)
    return path


# ---- prefetch (disabled unless permitted) ---------------------------------------------------------------------------
def prefetch(cfg=None):
    import math
    cfg = cfg or load_config()
    if not (cfg.get("prefetch_enabled") and cfg.get("permanent_cache")):
        print("vworld_proxy: prefetch is DISABLED. V-World terms 19조 forbid storing data without permission; turn on "
              "permanent_cache and prefetch_enabled in %s only after written permission from 공간정보산업진흥원." % CONFIG_FILE)
        return 1
    px = Proxy(cfg)
    W, S, E, N = cfg["korea_bbox"]
    for z in range(int(cfg["min_zoom"]), 15):
        n = 2 ** z
        x0, x1 = int((W + 180) / 360 * n), int((E + 180) / 360 * n)
        ty = lambda lat: int((1 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2 * n)
        for y in range(ty(N), ty(S) + 1):
            for x in range(x0, x1 + 1):
                if px.usage["count"] >= int(cfg["daily_budget"]) - int(cfg["prefetch_reserve"]):
                    print("prefetch: budget left for flying reached - continue tomorrow")
                    return 0
                px.get(z, y, x)
    return 0


# ---- self test (fake upstream, no V-World request) -------------------------------------------------------------------
def selftest():
    import tempfile, urllib.request as U
    fake_hits = []

    class Fake(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):
            fake_hits.append(self.path)
            mode = FAKE["mode"]
            if mode == "jpeg":
                b = io.BytesIO()
                Image.new("RGB", (256, 256), (200, 30, 30)).save(b, "JPEG")
                body, code, ct = b.getvalue(), 200, "image/jpeg"
            elif mode == "500":
                body, code, ct = b"oops", 500, "text/plain"
            else:
                body = ('<?xml version="1.0"?><ExceptionReport><Exception exceptionCode="%s"><ExceptionText>%s</ExceptionText>'
                        '</Exception></ExceptionReport>' % (mode, mode)).encode()
                code, ct = 200, "text/xml"
            self.send_response(code)
            self.send_header("Content-Type", ct)
            self.send_header("Cache-Control", "max-age=259200")
            self.end_headers()
            self.wfile.write(body)
    FAKE = dict(mode="jpeg")
    up = ThreadingHTTPServer(("127.0.0.1", 0), Fake)
    threading.Thread(target=up.serve_forever, daemon=True).start()
    tmp = tempfile.mkdtemp(prefix="vwproxy_test_")
    cfg = dict(DEFAULTS, cache_dir=tmp, port=0, daily_budget=6, rate_per_s=50.0, queue_wait_s=1.0)
    px = Proxy(cfg, key="TESTKEY123", upstream="http://127.0.0.1:%d/{key}/{layer}/{z}/{y}/{x}.jpeg" % up.server_address[1])
    res = {}
    z, y, x = 15, 12900, 27990                                 # near RKTU
    a = px.get(z, y, x); res["online_first"] = a[1] == "online"
    b = px.get(z, y, x); res["cache_second"] = b[1] == "cache" and len(fake_hits) == 1
    c = px.get(z + 1, y * 2 + 1, x * 2); FAKE["mode"] = "jpeg"
    res["child_online"] = c[1] == "online"
    res["out_of_korea_blank"] = px.get(15, 0, 0)[1] == "blank" and len(fake_hits) == 2
    res["low_zoom_blank"] = px.get(3, 3, 6)[1] == "blank" and len(fake_hits) == 2
    res["zoom17_parent_no_call"] = px.get(17, y * 4, x * 4)[1] == "parent" and len(fake_hits) == 2
    FAKE["mode"] = "500"
    e = px.get(15, y, x + 5); res["http500_fallback"] = e[1] in ("parent", "blank") and px.backoff_until > time.time()
    px.backoff_until = 0
    FAKE["mode"] = "SomethingElse"
    e = px.get(15, y, x + 6); res["xml200_not_cached"] = e[1] != "online" and px._row(15, y, x + 6)[2] == "fail"
    px.backoff_until = 0
    FAKE["mode"] = "OVER_REQUEST_LIMIT"
    n0 = len(fake_hits)
    e = px.get(15, y, x + 7)
    f = px.get(15, y, x + 8)
    res["over_limit_stops_day"] = px.usage["stop_until"] > time.time() and len(fake_hits) == n0 + 1 and f[1] != "online"
    px.usage["stop_until"] = 0
    px._save_usage()                                       # (the proxy merges usage.json from other processes)
    FAKE["mode"] = "jpeg"
    px.usage["count"] = 6
    px._save_usage()                                       # (the proxy merges usage.json from other processes)
    n0 = len(fake_hits)
    g = px.get(15, y, x + 9); res["budget_stops"] = len(fake_hits) == n0 and g[1] in ("parent", "blank")
    # parallel requests never overrun the budget (2 left, 8 at once -> exactly 2 calls)
    px.usage["count"] = 4
    px._save_usage()                                       # (the proxy merges usage.json from other processes)
    n0 = len(fake_hits)
    th = [threading.Thread(target=px.get, args=(15, y + 1, x + k)) for k in range(8)]
    [t.start() for t in th]
    [t.join() for t in th]
    res["parallel_budget_exact"] = len(fake_hits) - n0 == 2 and px.usage["count"] == 6
    # expiry: age a tile past max-age -> cleanup deletes the file
    px.db.execute("UPDATE t SET fetched = fetched - 300000 WHERE z=? AND y=? AND x=?", (z, y, x)); px.db.commit()
    res["expiry_deletes"] = px.cleanup() == 1 and not os.path.exists(px._path(z, y, x)) and px._row(z, y, x) is None
    res["fail_block_kept"] = px._row(15, y, x + 6) is not None
    # the key never reaches the logs / usage files
    blob = ""
    for fn in ("usage.json", "usage.jsonl"):
        try:
            blob += open(os.path.join(tmp, fn), encoding="utf-8").read()
        except OSError:
            pass
    res["key_not_in_files"] = "TESTKEY123" not in blob
    # filler requests (role fill, another process) do not use up the flight budget; the flight proxy sees them via usage.json
    pf = Proxy(dict(cfg, daily_budget=100), key="TESTKEY123", upstream=px.upstream, role="fill")
    pf.usage.update(count=50, fill_count=44); pf._save_usage()
    k = pf.get(15, y + 3, x)
    with px.lock:
        px._sync_usage()
    res["fill_counted_apart"] = k[1] == "online" and px.usage["count"] >= 51 and px.usage["fill_count"] == 45 and px.flight_count() == 6         and not px.online_state()[0] and pf.last_rec["role"] == "fill"
    px.usage.update(fill_count=46)
    px._save_usage()                                       # (the proxy merges usage.json from other processes)
    res["fill_frees_flight"] = px.online_state()[0]
    res["prefetch_refuses_by_default"] = prefetch(dict(DEFAULTS, cache_dir=tmp)) == 1
    up.shutdown()
    ok = all(res.values())
    print(json.dumps(dict(ok=ok, checks=res, fake_upstream_requests=len(fake_hits), vworld_requests=0), indent=1))
    return 0 if ok else 1


if __name__ == "__main__":
    a = sys.argv[1:]
    if "--selftest" in a:
        sys.exit(selftest())
    if "--make-attribution" in a:
        print(make_attribution())
        sys.exit(0)
    if "--prefetch" in a:
        sys.exit(prefetch())
    if "--cache-only-port" in a:                          # offscreen shots: cache only, no key, dies with its parent
        cfg = dict(load_config(), mode="cache-only", port=int(a[a.index("--cache-only-port") + 1]))
        ppid = int(a[a.index("--parent-pid") + 1]) if "--parent-pid" in a else 0
        srv, px = serve(cfg, Proxy(cfg, key=""), block=False)

        def alive(pid):
            if os.name == "nt":
                import ctypes
                h = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)        # PROCESS_QUERY_LIMITED_INFORMATION
                if not h:
                    return False
                code = ctypes.c_ulong()
                ctypes.windll.kernel32.GetExitCodeProcess(h, ctypes.byref(code))
                ctypes.windll.kernel32.CloseHandle(h)
                return code.value == 259                                        # STILL_ACTIVE
            try:
                os.kill(pid, 0)
                return True
            except OSError:
                return False
        while not ppid or alive(ppid):
            time.sleep(2.0)
        px.save_gaps()
        sys.exit(0)
    if "--status" in a:
        p = Proxy()
        print(json.dumps(p.status(), ensure_ascii=False, indent=1))
        sys.exit(0)
    serve()
