"""Slow, resumable V-World photo cache fill for one region (Busan, 부산광역시): ONLY zoom 19 is downloaded; z18 .. z14
are made locally from the cached z19 tiles (2x2 -> 1, Lanczos, same JPEG tables) after every run and with --derive.

    python sim/vworld_fill.py --build-region          make the Busan tile list (no V-World request)
    python sim/vworld_fill.py --status                progress / today's plan / observed limits / ETA (no request)
    python sim/vworld_fill.py --run-until-budget      fill until today's plan, the server's daily limit or an error
    pythonw sim/vworld_fill.py --run-until-budget     the same without any console window (all output in the log)
    python sim/vworld_fill.py --run-until-budget --max-requests 150    a short test batch
    python sim/vworld_fill.py --derive [--rebuild]  make z18..z14 locally from the cached z19 tiles (no request)
    python sim/vworld_fill.py --stop                  ask a running fill to stop after its current request

Every request goes through sim/vworld_proxy.Proxy (role "fill"): the same cache (C:/GyroSimTiles/vworld), the same
sqlite index, the same usage.json day count and the same stop rules (OVER_REQUEST_LIMIT / key error -> no request
until 00:00 KST). The key is read only by the Proxy and never printed or logged (all text goes through Proxy._safe).
Filler requests are counted apart (usage.json fill_count), so the flight proxy's own `daily_budget` is not used up
by the filler. max_online_zoom is raised to 19 inside this process only (the flight proxy keeps its own setting).

Limits (the real V-World numbers are not published, docs/vworld-integration.md 1절): found by observation, never hammered:
  - one connection, `rate_per_s` (3) requests/s with jitter, a sanity ceiling `max_per_min` (150) per minute;
    observed per-minute / per-hour counts are written to the status file.
  - per day: until the server answers OVER_REQUEST_LIMIT or the safety ceiling `day_ceiling` (30,000 key requests/day,
    flight included). On OVER_REQUEST_LIMIT the count reached that day is recorded as the observed daily limit, the
    filler stops for the KST day, and from then on plans each day at `plan_frac` (85 %) of the lowest observed limit
    minus `flight_reserve` (300) for flying.
  - a rate-type error (HTTP 429, or a limit text that names seconds / minutes / too many requests): the rate is halved
    (persisted) and recorded, then the proxy's exponential back-off is waited out.
  - INVALID_KEY / UNAVAILABLE_KEY / "등록되지 않은 / 사용할 수 없는 인증키": stop at once for the day and report (exit 3).
  - network / 5xx / other errors: the proxy's back-off (1, 2, 4 ... 300 s); 20 errors in a row ends the run.
  - pauses while the flight proxy (127.0.0.1:8790) is running (flying first); gives up after 30 min and exits.
TERMS: needs permanent_cache = true in Config/vworld_proxy.json (otherwise the tiles would be deleted after 3 days).
The tiles never go into git (C:/GyroSimTiles is outside the repo) and are never uploaded (V-World 약관 19조).
"""
import json, math, os, random, socket, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import vworld_proxy as VP                                    # noqa: E402

REGION = "busan"
BOUNDARY_URL = "https://raw.githubusercontent.com/southkorea/southkorea-maps/master/kostat/2013/json/skorea_provinces_geo.json"
BOUNDARY_FILE = r"C:\GyroSimTiles\incoming\boundary_dl\prov2013.json"     # KOSTAT 2013 시도 경계 (WGS84), code 21 = 부산
BUILDINGS_ZIP = r"C:\GyroSimTiles\incoming\zips\AL_D010_26_20261009.zip"    # GIS건물통합정보 부산 (EPSG:5186)
DERIVE_MIN_ZOOM = 14          # z18 .. z14 are made locally from the cached z19 tiles (2x2 -> 1), never fetched
BUFFER_M = 300.0              # around the boundary and around Busan buildings outside it (reclaimed port land, 2013 lines)
# fill order: z19 only, per z14 block (2 km), the block nearest a priority point first
PRIORITY = [("RKPK Gimhae airport", 35.1795, 128.9382), ("Seomyeon", 35.1578, 129.0600),
            ("Busan station", 35.1151, 129.0422), ("Haeundae", 35.1587, 129.1604)]
FILL_DEFAULTS = dict(
    rate_per_s=3.0,           # start value; halved (persisted in the state file) on every rate-type error
    jitter=0.35,              # each gap = 1/rate * uniform(1 - jitter, 1 + jitter)
    min_rate=0.2,
    max_per_min=150,          # sanity ceiling only
    day_ceiling=30000,        # key requests per KST day (flight included) while no daily limit has been observed
    plan_frac=0.85,           # after a limit was observed: plan the day at 85 % of it ...
    flight_reserve=300,       # ... minus this for flying
    max_consecutive_errors=20,
    max_error_frac=0.05,      # more errors than this (after 100 fill requests today) ends the run
    min_free_gb=20.0,
    pause_while_flying=True,
    flying_wait_min=30.0,
)
RATE_WORDS = ("429", "TOO_MANY", "Too Many", "per second", "per minute", "초당", "분당", "1초", "1분", "RATE", "rate limit")
KEY_WORDS = ("INVALID_KEY", "UNAVAILABLE_KEY", "등록되지 않은 인증키", "사용할 수 없는 인증키")


def cfg_all():
    cfg = VP.load_config()
    fill = dict(FILL_DEFAULTS)
    fill.update({k: v for k, v in (cfg.get("fill") or {}).items() if not k.startswith("_")})
    return cfg, fill


def paths(cfg):
    d = cfg["cache_dir"]
    return dict(dir=os.path.join(d, "fill"), tiles=os.path.join(d, "fill", REGION + "_tiles.json"),
                region=os.path.join(d, "fill", REGION + "_region.geojson"),
                log=os.path.join(d, "fill_%s.log" % REGION), status=os.path.join(d, "fill_%s_status.json" % REGION),
                state=os.path.join(d, "fill_%s_state.json" % REGION), lock=os.path.join(d, "fill_%s.lock" % REGION),
                stop=os.path.join(d, "fill_%s.stop" % REGION))


def now_s():
    return time.strftime("%Y-%m-%d %H:%M:%S")


def jload(p, default):
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def jsave(p, obj):
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1)
    os.replace(tmp, p)


def tkey(z, y, x):
    return (z << 44) | (y << 22) | x


# ---- region -> ordered tile list (offline) ---------------------------------------------------------------------------
def sha256(p):
    import hashlib
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def build_region():
    import zipfile
    import numpy as np
    import shapely, pyogrio
    from shapely.geometry import shape, mapping
    from shapely.ops import transform
    from pyproj import Transformer, Geod
    cfg, _ = cfg_all()
    P = paths(cfg)
    os.makedirs(P["dir"], exist_ok=True)
    t0 = time.time()
    if not os.path.exists(BOUNDARY_FILE):                    # public file, no account
        import urllib.request
        os.makedirs(os.path.dirname(BOUNDARY_FILE), exist_ok=True)
        urllib.request.urlretrieve(BOUNDARY_URL, BOUNDARY_FILE)
    with open(BOUNDARY_FILE, encoding="utf-8") as f:
        fc = json.load(f)
    g = [shape(ft["geometry"]) for ft in fc["features"] if str(ft["properties"].get("code")) == "21"]
    assert len(g) == 1, "Busan (code 21) not found in the boundary file"
    g = g[0]
    to_m = Transformer.from_crs("EPSG:4326", "EPSG:5186", always_xy=True).transform
    to_geo = Transformer.from_crs("EPSG:5186", "EPSG:4326", always_xy=True).transform
    gm = transform(to_m, g)
    # Busan buildings outside the 2013 line (new port / reclaimed land): their centroids, buffered too
    pts = []
    with zipfile.ZipFile(BUILDINGS_ZIP) as zf:
        shps = [m for m in zf.namelist() if m.lower().endswith(".shp")]
    for m in shps:
        df = pyogrio.read_dataframe("/vsizip/%s/%s" % (BUILDINGS_ZIP.replace("\\", "/"), m), columns=[], read_geometry=True)
        pts.append(shapely.centroid(np.asarray(df.geometry.values)))
    pts = np.concatenate(pts)
    shapely.prepare(gm)
    outside = pts[~shapely.contains(gm, pts)]
    extra = shapely.union_all(shapely.buffer(outside, BUFFER_M, quad_segs=4)) if len(outside) else None
    rm = gm.buffer(BUFFER_M, quad_segs=4)
    if extra is not None:
        rm = rm.union(extra)
    rm = rm.simplify(10.0)
    region = transform(to_geo, rm)
    area = abs(Geod(ellps="WGS84").geometry_area_perimeter(g)[0]) / 1e6
    area_r = abs(Geod(ellps="WGS84").geometry_area_perimeter(region)[0]) / 1e6
    shapely.prepare(region)
    W, S, E, N = region.bounds

    def tx(lon, n):
        return int((lon + 180) / 360 * n)

    def ty(lat, n):
        return int((1 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2 * n)

    def dist_km(lat, lon):
        return min(math.hypot((lat - a) * 111.0, (lon - b) * 111.0 * math.cos(math.radians(a))) for _, a, b in PRIORITY)

    by_z = {}
    for z in range(DERIVE_MIN_ZOOM, 20):                     # only z19 is fetched; the others are counted for the derive step
        n = 2 ** z
        xs = np.arange(tx(W, n), tx(E, n) + 1)
        ys = np.arange(ty(N, n), ty(S, n) + 1)
        X, Y = np.meshgrid(xs, ys)
        X, Y = X.ravel(), Y.ravel()
        lon0 = X / n * 360 - 180
        lon1 = (X + 1) / n * 360 - 180
        lat_n = np.degrees(np.arctan(np.sinh(np.pi * (1 - 2 * Y / n))))
        lat_s = np.degrees(np.arctan(np.sinh(np.pi * (1 - 2 * (Y + 1) / n))))
        hit = shapely.intersects(region, shapely.box(lon0, lat_s, lon1, lat_n))
        by_z[z] = (Y[hit], X[hit])
    blocks = {}                                               # z19 tiles per z14 block (2 km), nearest block first
    for y, x in zip(*by_z[19]):
        blocks.setdefault((int(y) >> 5, int(x) >> 5), []).append([19, int(y), int(x)])
    n14 = 2 ** 14

    def bdist(b):
        y, x = b
        lat = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * (y + 0.5) / n14))))
        return dist_km(lat, (x + 0.5) / n14 * 360 - 180)
    order = []
    for b in sorted(blocks, key=bdist):
        order += sorted(blocks[b])
    counts = {str(z): int(len(by_z[z][0])) for z in by_z}
    meta = dict(region=REGION, created=now_s(), boundary=dict(file=BOUNDARY_FILE, url=BOUNDARY_URL, sha256=sha256(BOUNDARY_FILE),
                note="KOSTAT 2013 시도 경계 via southkorea/southkorea-maps, code 21"),
                buildings=dict(file=BUILDINGS_ZIP, sha256=sha256(BUILDINGS_ZIP), outside_boundary=int(len(outside))),
                buffer_m=BUFFER_M, area_boundary_km2=round(area, 1), area_region_km2=round(area_r, 1),
                order="z19 only, per z14 block (2 km) nearest a priority point first; z18..z%d are made locally (--derive)" % DERIVE_MIN_ZOOM,
                priority=PRIORITY, counts=counts, total=len(order))
    jsave(P["tiles"], dict(meta=meta, tiles=order))
    with open(P["region"], "w", encoding="utf-8") as f:
        json.dump(dict(type="Feature", properties=meta | dict(counts=counts), geometry=mapping(region)), f)
    print(json.dumps(dict(meta, seconds=round(time.time() - t0, 1)), ensure_ascii=False, indent=1))
    return 0


# ---- local parent tiles from the cached z19 (no API call) ------------------------------------------------------------
def derive(px=None, tiles=None, min_zoom=DERIVE_MIN_ZOOM, rebuild=False, log=print):
    """z18 .. min_zoom made from the cached children: 4 children (512 px) -> 1 tile (256 px, Lanczos), JPEG saved with the
    children's own quantisation tables (= the same JPEG quality as V-World's). A parent is made only when all 4 children
    are there ('ok' / 'derived' file, or 'empty' = V-World has no tile -> the proxy's blank colour); a missing child is
    filled from the parent's own older version or the nearest cached ancestor, else the parent is skipped.
    Real downloaded tiles ('ok') are never overwritten. Rows get status 'derived' (rebuild: --derive --rebuild);
    every made tile is one line in fill/derived.jsonl. Re-made only when a child is newer than it."""
    from PIL import Image, JpegImagePlugin
    import io
    cfg, _ = cfg_all()
    P = paths(cfg)
    if px is None:
        px = VP.Proxy(dict(cfg, mode="cache-only"), key="", role="fill")
        px.log = lambda *a: None
    if tiles is None:
        tiles = jload(P["tiles"], {}).get("tiles", [])
    t0 = time.time()
    with px.lock:
        if rebuild:
            old = px.db.execute("SELECT z, y, x FROM t WHERE status='derived'").fetchall()
            for z, y, x in old:
                try:
                    os.remove(px._path(z, y, x))
                except OSError:
                    pass
            px.db.execute("DELETE FROM t WHERE status='derived'")
            px.db.commit()
            log("derive: rebuild - %d derived tiles removed" % len(old))
        rows = {tkey(z, y, x): (st, fe) for z, y, x, st, fe in
                px.db.execute("SELECT z, y, x, status, fetched FROM t WHERE z >= ? AND status IN ('ok', 'empty', 'derived')",
                              (max(0, min_zoom - 6),))}
    blank = Image.new("RGB", (256, 256), tuple(cfg["blank_rgb"]))
    qref = [None]

    def open_tile(z, y, x):
        im = Image.open(px._path(z, y, x))
        if qref[0] is None and rows.get(tkey(z, y, x), ("",))[0] == "ok" and isinstance(im, JpegImagePlugin.JpegImageFile):
            qref[0] = (im.quantization, JpegImagePlugin.get_sampling(im))
        return im.convert("RGB")

    def ancestor_quadrant(z, y, x):
        """256 px picture of tile (z, y, x) cut from the nearest cached ancestor, or None."""
        for dz in range(1, 7):
            pz, py, pxx = z - dz, y >> dz, x >> dz
            r = rows.get(tkey(pz, py, pxx))
            if r is None or r[0] not in ("ok", "derived"):
                continue
            try:
                im = open_tile(pz, py, pxx)
            except OSError:
                continue
            n, sz = 2 ** dz, 256 / 2 ** dz
            ox, oy = (x - pxx * n) * sz, (y - py * n) * sz
            return im.crop((int(ox), int(oy), int(ox + sz), int(oy + sz))).resize((256, 256), Image.LANCZOS)
        return None
    level = {(y, x) for z, y, x in tiles if z == 19}
    made, made_z, skipped_missing = 0, {}, 0
    dlog = open(os.path.join(P["dir"], "derived.jsonl"), "a", encoding="utf-8")
    for z in range(18, min_zoom - 1, -1):
        parents = {(y >> 1, x >> 1) for y, x in level}
        n_made = 0
        for y, x in sorted(parents):
            k = tkey(z, y, x)
            cur = rows.get(k)
            if cur is not None and cur[0] in ("ok", "empty"):
                continue                                          # a real downloaded tile (or V-World's "none") stays
            kids = [(2 * y + dy, 2 * x + dx) for dy in (0, 1) for dx in (0, 1)]
            kr = [rows.get(tkey(z + 1, cy, cx)) for cy, cx in kids]
            if all(r is None or r[0] == "empty" for r in kr):
                continue                                          # nothing there yet / sea only
            newest = max(r[1] for r in kr if r is not None)
            if cur is not None and cur[0] == "derived" and cur[1] >= newest and all(r is not None for r in kr):
                continue                                          # up to date
            canvas = Image.new("RGB", (512, 512))
            ok = True
            for i, ((cy, cx), r) in enumerate(zip(kids, kr)):
                pic = None
                if r is not None and r[0] in ("ok", "derived"):
                    try:
                        pic = open_tile(z + 1, cy, cx)
                    except OSError:
                        pic = None
                elif r is not None and r[0] == "empty":
                    pic = blank
                if pic is None:
                    pic = ancestor_quadrant(z + 1, cy, cx)        # the parent's own older version is an ancestor too
                if pic is None:
                    ok = False
                    break
                canvas.paste(pic, ((i % 2) * 256, (i // 2) * 256))
            if not ok:
                skipped_missing += 1
                continue
            out = canvas.resize((256, 256), Image.LANCZOS)
            b = io.BytesIO()
            if qref[0] is not None:
                out.save(b, "JPEG", qtables=qref[0][0], subsampling=qref[0][1])
            else:
                out.save(b, "JPEG", quality=90)
            p = px._path(z, y, x)
            os.makedirs(os.path.dirname(p), exist_ok=True)
            with open(p + ".tmp", "wb") as f:
                f.write(b.getvalue())
            os.replace(p + ".tmp", p)
            t = time.time()
            with px.lock:
                px.db.execute("INSERT OR REPLACE INTO t VALUES (?, ?, ?, ?, ?, 'derived', 0, 0)", (z, y, x, t, float(cfg["default_max_age"])))
            rows[k] = ("derived", t)
            dlog.write(json.dumps(dict(t=now_s(), z=z, y=y, x=x, src="z%d children" % (z + 1), bytes=len(b.getvalue()))) + "\n")
            n_made += 1
        with px.lock:
            px.db.commit()
        made_z[str(z)] = n_made
        made += n_made
        level = parents
    dlog.close()
    log("derive: %d tiles made locally %s, %d skipped (a child missing and no cached ancestor), %.0f s, 0 API calls" % (
        made, made_z, skipped_missing, time.time() - t0))
    return made_z


def derived_counts(px):
    with px.lock:
        return {str(z): n for z, n in px.db.execute("SELECT z, COUNT(*) FROM t WHERE status='derived' GROUP BY z")}


# ---- state / plan ----------------------------------------------------------------------------------------------------
def load_state(P, fill):
    st = jload(P["state"], {})
    st.setdefault("rate_per_s", float(fill["rate_per_s"]))
    st.setdefault("observed_daily_limits", [])     # [{day, count_at_stop, at}]
    st.setdefault("rate_events", [])               # [{day, at, http, note, rate_before, rate_after}]
    st.setdefault("key_errors", [])
    st.setdefault("days", {})                      # day -> {fill_requests, errors, end}
    return st


def day_plan(st, fill):
    """-> (cap on today's key request count, why)."""
    lims = [d["count_at_stop"] for d in st["observed_daily_limits"]]
    if lims:
        lim = min(lims)
        return max(0, int(fill["plan_frac"] * lim) - int(fill["flight_reserve"])), "85%% of observed limit %d - %d reserve" % (lim, fill["flight_reserve"])
    return int(fill["day_ceiling"]), "no limit observed yet: until OVER_REQUEST_LIMIT or safety ceiling"


def done_keys(px):
    with px.lock:
        rows = px.db.execute("SELECT z, y, x FROM t WHERE status IN ('ok', 'empty')").fetchall()
    return {tkey(*r) for r in rows}


def progress(tiles, done):
    per = {}
    for z, y, x in tiles:
        p = per.setdefault(str(z), [0, 0])
        p[1] += 1
        if tkey(z, y, x) in done:
            p[0] += 1
    d = sum(v[0] for v in per.values())
    return d, len(tiles), per


def cache_bytes_estimate(px, tiles, done, sample=400):
    """average size of cached region tiles (sample) x done tiles -> (avg bytes, done bytes)"""
    have = [t for t in tiles if tkey(*t) in done]
    if not have:
        return None, 0
    random.seed(1)
    pick = random.sample(have, min(sample, len(have)))
    sizes = []
    for z, y, x in pick:
        try:
            sizes.append(os.path.getsize(px._path(z, y, x)))
        except OSError:
            pass                                               # 'empty' rows (no file)
    avg = sum(sizes) / len(sizes) if sizes else 0
    return avg, avg * len(have) * (len(sizes) / max(1, len(pick)))


def eta_text(st, fill, left):
    cap, _ = day_plan(st, fill)
    if st["observed_daily_limits"]:
        per_day = max(1, cap)
        return "%.1f days at %d fill requests/day (plan)" % (left / per_day, per_day), left / per_day
    per_day = int(fill["day_ceiling"]) - int(fill["flight_reserve"])
    return "daily limit not observed yet; at least %.1f days (safety ceiling %d/day)" % (left / per_day, per_day), None


def flight_proxy_running(cfg):
    s = socket.socket()
    s.settimeout(0.5)
    try:
        return s.connect_ex(("127.0.0.1", int(cfg["port"]))) == 0
    finally:
        s.close()


# ---- the run ---------------------------------------------------------------------------------------------------------
class Run:
    def __init__(self, max_requests=None):
        self.cfg, self.fill = cfg_all()
        self.P = paths(self.cfg)
        self.max_requests = max_requests
        self.logf = open(self.P["log"], "a", encoding="utf-8")
        self.px = None

    def log(self, *a):
        s = now_s() + "  " + " ".join(str(x) for x in a)
        if self.px is not None:
            s = self.px._safe(s)
        self.logf.write(s + "\n")
        self.logf.flush()
        if sys.stdout is not None:                               # pythonw: no console
            try:
                print(s, flush=True)
            except Exception:
                pass

    def main(self):
        import msvcrt
        P, cfg, fill = self.P, self.cfg, self.fill
        if not cfg.get("permanent_cache"):
            self.log("REFUSED: permanent_cache is off in Config/vworld_proxy.json (tiles would be deleted after 3 days, terms 19조)")
            return 2
        if not os.path.exists(P["tiles"]):
            self.log("REFUSED: no tile list - run  python sim/vworld_fill.py --build-region  first")
            return 2
        self.lockf = open(P["lock"], "a+")
        try:
            msvcrt.locking(self.lockf.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            self.log("another fill run is active (lock held) - exiting")
            return 0
        if os.path.exists(P["stop"]):
            os.remove(P["stop"])                              # an old stop request: this run was started on purpose
        tl = jload(P["tiles"], None)
        tiles = tl["tiles"]
        self.st = st = load_state(P, fill)
        pcfg = dict(cfg, daily_budget=10 ** 9, max_online_zoom=19, rate_per_s=20.0, concurrency=1, queue_wait_s=60.0)
        self.px = px = VP.Proxy(pcfg, role="fill")             # same cache / index / usage.json / stop rules
        px.log = lambda *a: self.log("proxy:", *a)
        if not px.key:
            self.log("REFUSED: no key file")
            return 2
        done = done_keys(px)
        d0, total, _ = progress(tiles, done)
        cap, why = day_plan(st, fill)
        self.log("START region %s: done %d / %d, rate %.2f/s, today used %d (fill %d), plan cap %d (%s), max_requests %s"
                 % (REGION, d0, total, st["rate_per_s"], px.usage.get("count", 0), px.usage.get("fill_count", 0), cap, why, self.max_requests))
        self.t_req = []                                       # request times (observed rates)
        self.n_req = self.n_err = 0
        self.consec = 0
        self.end = "finished"
        code = 0
        last_status = 0.0
        last_fly_check = 0.0
        t_start = time.time()
        for i, (z, y, x) in enumerate(tiles):
            k = tkey(z, y, x)
            if k in done:
                continue
            # ---- stop conditions -------------------------------------------------------------------------------
            if os.path.exists(P["stop"]):
                os.remove(P["stop"])
                self.end = "stop requested"
                break
            if self.max_requests is not None and self.n_req >= self.max_requests:
                self.end = "max_requests %d reached" % self.max_requests
                break
            if time.time() - last_fly_check > 20:
                last_fly_check = time.time()
                if fill["pause_while_flying"] and flight_proxy_running(cfg):
                    if not self.wait_flying():
                        self.end = "flight proxy running (flying first) - try later"
                        break
                if VP.shutil_free_gb(cfg["cache_dir"]) < float(fill["min_free_gb"]):
                    self.end = "disk almost full (< %.0f GB free)" % fill["min_free_gb"]
                    break
            with px.lock:
                px._sync_usage()
                px._roll_day()
            cap, why = day_plan(st, fill)
            if px.usage.get("count", 0) >= cap:
                self.end = "today's plan reached (%d key requests today, cap %d: %s)" % (px.usage["count"], cap, why)
                break
            if self.n_req >= 100 and self.n_err > float(fill["max_error_frac"]) * self.n_req:
                self.end = "too many errors this run (%d of %d)" % (self.n_err, self.n_req)
                break
            ok, why_off = px.online_state()
            if not ok:
                if why_off.startswith("back-off"):
                    time.sleep(max(0.0, px.backoff_until - time.time()) + 0.2)
                    ok, why_off = px.online_state()
                if not ok:
                    self.end = "proxy offline: " + why_off
                    break
            self.pace()
            # ---- one tile --------------------------------------------------------------------------------------
            n0 = px.session_api
            px.get(z, y, x)
            if px.session_api == n0:
                continue                                      # no request was made (blocked tile / other process)
            self.n_req += 1
            self.t_req.append(time.time())
            day = px.usage.get("day")
            dd = st["days"].setdefault(day, dict(fill_requests=0, errors=0))
            dd["fill_requests"] += 1
            rec = px.last_rec or {}
            kind = rec.get("kind")
            if kind in ("tile", "empty"):
                self.consec = 0
                done.add(k)
            else:
                self.n_err += 1
                self.consec += 1
                dd["errors"] += 1
                r = self.handle_error(rec, day)
                if r is not None:
                    code = r
                    break
                if self.consec >= int(fill["max_consecutive_errors"]):
                    self.end = "%d errors in a row (network?)" % self.consec
                    break
            if time.time() - last_status > 30:
                last_status = time.time()
                self.write_status(tiles, done, running=True)
            if self.n_req % 200 == 0:
                self.log("progress: %d requests this run, %d errors, rate %.2f/s, last %s/%d/%d, today %d (fill %d)" % (
                    self.n_req, self.n_err, st["rate_per_s"], z, y, x, px.usage.get("count", 0), px.usage.get("fill_count", 0)))
        dur = time.time() - t_start
        try:
            derive(px, tiles, log=self.log)
        except Exception as e:
            self.log("derive failed:", repr(e))
        day = px.usage.get("day")
        if day in st["days"]:
            st["days"][day]["end"] = self.end
        jsave(P["state"], st)
        s = self.write_status(tiles, done, running=False)
        self.log("END %s: %d requests (%d errors) in %.0f s (%.2f/s), done %d / %d, today %d key requests (fill %d), ETA %s" % (
            self.end, self.n_req, self.n_err, dur, self.n_req / max(1.0, dur), s["done"], s["total"], px.usage.get("count", 0),
            px.usage.get("fill_count", 0), s["eta"]))
        return code

    def wait_flying(self):
        t_end = time.time() + 60 * float(self.fill["flying_wait_min"])
        self.log("flight proxy is running on port %s - pausing (flying first)" % self.cfg["port"])
        while time.time() < t_end:
            time.sleep(30)
            if os.path.exists(self.P["stop"]):
                return False
            if not flight_proxy_running(self.cfg):
                self.log("flight proxy gone - continuing")
                return True
        return False

    def pace(self):
        f = self.fill
        gap = 1.0 / max(float(f["min_rate"]), self.st["rate_per_s"])
        if self.t_req:
            wait = self.t_req[-1] + gap * random.uniform(1 - f["jitter"], 1 + f["jitter"]) - time.time()
            if wait > 0:
                time.sleep(wait)
        now = time.time()
        recent = [t for t in self.t_req[-int(f["max_per_min"]):] if t > now - 60]
        if len(recent) >= int(f["max_per_min"]):
            time.sleep(max(0.0, recent[0] + 60 - now) + 0.05)
        if len(self.t_req) > 20000:
            self.t_req = self.t_req[-5000:]

    def handle_error(self, rec, day):
        """-> exit code to end the run, or None to go on (after the back-off)."""
        px, st = self.px, self.st
        text = (rec.get("note") or "") + " " + (rec.get("text") or "")
        http = rec.get("http")
        self.log("error: http %s kind %s note %s text %s" % (http, rec.get("kind"), rec.get("note"), (rec.get("text") or "")[:160]))
        if any(w in text for w in KEY_WORDS):
            st["key_errors"].append(dict(day=day, at=now_s(), note=rec.get("note")))
            self.end = "KEY ERROR (%s) - stopped for the day, check the key" % rec.get("note")
            return 3
        rate_type = http == 429 or any(w in text for w in RATE_WORDS)
        if rec.get("kind") == "stop" and not rate_type:                   # OVER_REQUEST_LIMIT / 일일 제한: the daily limit
            c = int(px.usage.get("count", 0)) - 1                         # requests that got through today
            st["observed_daily_limits"].append(dict(day=day, count_at_stop=c, fill_count=int(px.usage.get("fill_count", 0)), at=now_s(),
                                                    note=rec.get("note")))
            self.end = "server daily limit reached (%s) at %d key requests today - stopped until 00:00 KST" % (rec.get("note"), c)
            return 4
        if rate_type:
            before = st["rate_per_s"]
            st["rate_per_s"] = max(float(self.fill["min_rate"]), before / 2)
            st["rate_events"].append(dict(day=day, at=now_s(), http=http, note=rec.get("note"), rate_before=before,
                                          rate_after=st["rate_per_s"], last_min=self.count_since(60)))
            self.log("rate-type error: rate %.2f -> %.2f /s" % (before, st["rate_per_s"]))
            if rec.get("kind") == "stop":                                  # the proxy stopped the day on a rate message:
                with px.lock:                                              # wait 120 s instead, at half the rate
                    px.usage.update(stop_until=0, stop_reason=None)
                    px.backoff_until = max(px.backoff_until, time.time() + 120)
                    px._save_usage()
            jsave(self.P["state"], st)
        wait = max(0.0, px.backoff_until - time.time())
        if wait > 0:
            time.sleep(wait + 0.2)
        return None

    def count_since(self, s):
        t = time.time() - s
        return sum(1 for v in self.t_req if v > t)

    def write_status(self, tiles, done, running):
        s = status_dict(self.cfg, self.fill, self.st, self.px, tiles, done)
        s.update(running=running, run_end=None if running else self.end, run_requests=self.n_req, run_errors=self.n_err,
                 observed_last_min=self.count_since(60), observed_last_hour=self.count_since(3600))
        jsave(self.P["status"], s)
        return s


def status_dict(cfg, fill, st, px, tiles, done):
    d, total, per = progress(tiles, done)
    avg, have_b = cache_bytes_estimate(px, tiles, done)
    eta, days = eta_text(st, fill, total - d)
    cap, why = day_plan(st, fill)
    u = px.usage
    return dict(region=REGION, updated=now_s(), done=d, total=total, pct=round(100.0 * d / max(1, total), 2), per_zoom=per,
                avg_tile_bytes=round(avg) if avg else None, done_gb=round(have_b / 1e9, 3),
                total_gb_estimate=round((avg or 15000) * total / 1e9, 2), day=u.get("day"), key_requests_today=u.get("count", 0),
                fill_requests_today=u.get("fill_count", 0), errors_today=u.get("errors", 0), plan_cap_today=cap, plan=why,
                stop_until=u.get("stop_until", 0), stop_reason=u.get("stop_reason"), rate_per_s=st["rate_per_s"],
                max_per_min=fill["max_per_min"], observed_daily_limits=st["observed_daily_limits"], rate_events=st["rate_events"],
                key_errors=st["key_errors"], derived_tiles=derived_counts(px), eta=eta, eta_days=days, days=st["days"])


def print_status():
    cfg, fill = cfg_all()
    P = paths(cfg)
    tl = jload(P["tiles"], None)
    if tl is None:
        print("no tile list yet: python sim/vworld_fill.py --build-region")
        return 1
    px = VP.Proxy(dict(cfg, mode="cache-only"), key="", role="fill")    # read only: never calls the API, no key loaded
    px.log = lambda *a: None
    st = load_state(P, fill)
    s = status_dict(cfg, fill, st, px, tl["tiles"], done_keys(px))
    last = jload(P["status"], {})
    s["last_run"] = {k: last.get(k) for k in ("updated", "running", "run_end", "run_requests", "run_errors", "observed_last_min", "observed_last_hour")}
    s.pop("days", None)
    print(json.dumps(s, ensure_ascii=False, indent=1))
    return 0


def request_stop():
    cfg, _ = cfg_all()
    P = paths(cfg)
    with open(P["stop"], "w") as f:
        f.write(now_s())
    print("stop requested (%s); a running fill exits after its current request" % P["stop"])
    return 0


def _free_gb(path):
    import shutil
    return shutil.disk_usage(path).free / 1e9


VP.shutil_free_gb = _free_gb


if __name__ == "__main__":
    a = sys.argv[1:]
    if "--build-region" in a:
        sys.exit(build_region())
    if "--derive" in a:
        derive(rebuild="--rebuild" in a)
        sys.exit(0)
    if "--status" in a:
        sys.exit(print_status())
    if "--stop" in a:
        sys.exit(request_stop())
    if "--run-until-budget" in a:
        mr = int(a[a.index("--max-requests") + 1]) if "--max-requests" in a else None
        sys.exit(Run(mr).main())
    print(__doc__)
