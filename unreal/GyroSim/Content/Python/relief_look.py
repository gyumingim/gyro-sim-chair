"""Photo relief at Play (11-11, docs/photo-relief-busan.md): small height field from the V-World ortho photo around the
camera, for the ground material's lighting (normals) and height-field shadows (Scripts/ground_look.hlsl 'photo relief').

RAM / GPU only (V-World terms: no changed or stored copies of the photo): sim/photo_relief.py (own Python with torch,
GYROSIM_RELIEF_PY, default C:/Users/a3162/venvs/photodepth) makes each z18 tile's height on request from the same photo
URL the Cesium overlay uses (16-bit grey PNG); this module draws the tiles into the render target RT_GyroRelief (RGBA16F - R16F reads back wrong, 8 x 8 z18 tiles = 4096 px,
~1 km, toroidal slots, recentred ahead of the camera) and keeps the Rel* vectors of MPC_GyroTune up to date:
  RelU / RelU2, RelV / RelV2   world (km from the Cesium origin, quadratic) -> z19 px from the window corner
  RelWin  (corner px mod RT size x, y, RT size px, -)
  RelSun  direction to the sun (world)        RelK (height gain x, normal strength, shadow strength, -)
  RelF    (fade start m, fade end m, m per z19 px, on)
Nothing is written to disk. GYROSIM_PHOTO_DEPTH=0 -> RelF.w = 0 (the ground as before, no worker started).
Live knobs (tune page, tune_look values): RelGain (m per model unit, 20 = as made), RelNormal, RelShadow.
"""
import json, math, os, queue, socket, subprocess, sys, threading, time, urllib.request
import unreal

MPC = "/Game/Materials/Ground/MPC_GyroTune"          # Rel* vectors (a material may use only 2 collections)
RT = "/Game/Materials/Ground/RT_GyroRelief"
N = 8                                   # tiles per side in the RT
TILE = 512                              # z19 px per z18 tile
SIZE = N * TILE
AHEAD_M = 300.0                         # window centre ahead of the camera
PY = os.environ.get("GYROSIM_RELIEF_PY", r"C:/Users/a3162/venvs/photodepth/Scripts/python.exe")
HF = os.environ.get("GYROSIM_RELIEF_HF", r"C:/Users/a3162/venvs/hf_photodepth")
REPO = os.path.abspath(os.path.join(unreal.Paths.project_dir(), "..", ".."))
MADE_GAIN = 20.0                        # sim/photo_relief.py GAIN (m per model unit) the tiles are made with
DEF = dict(RelGain=20.0, RelNormal=1.0, RelShadow=0.6, RelFadeNear=500.0, RelFadeFar=1100.0)
ST = dict(h=None, port=None, proc=None, rt=None, mpc=None, world=None, origin=None, fit=None, fit_c=None, win=None,
          slots={}, want=[], busy=set(), done=queue.Queue(), t=0.0, zero=None, n_drawn=0, n_req=0, ms_draw=0.0, on=False,
          photo=None, errors=0, last_err="")
log = lambda *a: unreal.log("[relief] " + " ".join(str(x) for x in a))


def on():
    return os.environ.get("GYROSIM_PHOTO_DEPTH", "0") == "1"     # default OFF (11-11): in-flight hitches p99 38 ms until the tile upload is async


# ---- worker -----------------------------------------------------------------------------------------------------------
def _free_port():
    s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close()
    return p


def _worker(photo):
    if ST["port"] and ST["proc"] is not None and ST["proc"].poll() is None:
        return True
    if not os.path.isfile(PY):
        log("no relief python", PY, "- relief off")
        return False
    port = int(os.environ.get("GYROSIM_RELIEF_PORT", "0")) or _free_port()
    env = dict(os.environ, HF_HOME=HF, HF_HUB_OFFLINE="1", PYTHONIOENCODING="utf-8")
    try:
        ST["proc"] = subprocess.Popen([PY, "-I", os.path.join(REPO, "sim", "photo_relief.py"), "--port", str(port), "--photo", photo,
                                       "--parent-pid", str(os.getpid())], cwd=REPO, env=env, stdin=subprocess.DEVNULL,
                                      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                      creationflags=0x08000000 if sys.platform == "win32" else 0)      # CREATE_NO_WINDOW
    except OSError as e:
        log("worker start failed", repr(e))
        return False
    ST["port"] = port
    log("worker starting on port", port)
    return True


def _fetch(key):
    x, y = key
    t0 = time.perf_counter()
    try:
        with urllib.request.urlopen("http://127.0.0.1:%d/relief/%d/%d.png" % (ST["port"], x, y), timeout=30) as r:
            ST["done"].put((key, r.read(), time.perf_counter() - t0))
    except Exception as e:
        ST["done"].put((key, None, repr(e)))


# ---- geometry ---------------------------------------------------------------------------------------------------------
def _origin(world):
    for a in unreal.GameplayStatics.get_all_actors_of_class(world, unreal.CesiumGeoreference):
        try:
            return (float(a.get_editor_property("origin_latitude")), float(a.get_editor_property("origin_longitude")),
                    float(a.get_editor_property("origin_height")))
        except Exception:
            return None
    return None


def _gpx(lat, lon):
    n = 2 ** 19 * 256
    return (lon + 180.0) / 360.0 * n, (1 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2 * n


def _latlon(fr, x, y):
    """world cm -> lat, lon (Newton on geo.Frame.world)"""
    lat = fr.lat0 + x / 100.0 / 110950.0
    lon = fr.lon0 + y / 100.0 / (111320.0 * math.cos(math.radians(fr.lat0)))
    for _ in range(3):
        wx, wy, _ = fr.world(lat, lon, 29.0)
        lat += (x - wx) / 100.0 / 110950.0
        lon += (y - wy) / 100.0 / (111320.0 * math.cos(math.radians(lat)))
    return lat, lon


def _solve(rows, t):
    K = len(rows[0])
    A = [[0.0] * K for _ in range(K)]; b = [0.0] * K
    for r, tv in zip(rows, t):
        for p in range(K):
            b[p] += r[p] * tv
            for q in range(K):
                A[p][q] += r[p] * r[q]
    for p in range(K):
        m = max(range(p, K), key=lambda r2: abs(A[r2][p]))
        A[p], A[m], b[p], b[m] = A[m], A[p], b[m], b[p]
        piv = A[p][p]; A[p] = [a / piv for a in A[p]]; b[p] /= piv
        for r2 in range(K):
            if r2 != p:
                f = A[r2][p]; A[r2] = [a - f * c for a, c in zip(A[r2], A[p])]; b[r2] -= f * b[p]
    return b


def _fit(origin, cx, cy):
    """quadratic rows world km -> global z19 px minus a reference (rx, ry), over +-3 km around world (cx, cy) cm."""
    import geo
    fr = geo.Frame(*origin)
    lat_c, lon_c = _latlon(fr, cx, cy)
    rx, ry = (int(v) // TILE * TILE for v in _gpx(lat_c, lon_c))
    rows, us, vs = [], [], []
    for i in range(9):
        for j in range(9):
            lat = lat_c + (i - 4) * 3000.0 / 4 / 110950.0
            lon = lon_c + (j - 4) * 3000.0 / 4 / (111320.0 * math.cos(math.radians(lat_c)))
            x, y, _ = fr.world(lat, lon, 29.0)
            xk, yk = x * 1e-5, y * 1e-5
            rows.append((xk, yk, 1.0, xk * xk, xk * yk, yk * yk))
            gx, gy = _gpx(lat, lon)
            us.append(gx - rx); vs.append(gy - ry)
    cu, cv = _solve(rows, us), _solve(rows, vs)
    err = max(math.hypot(sum(a * b for a, b in zip(cu, r)) - u, sum(a * b for a, b in zip(cv, r)) - v) for r, u, v in zip(rows, us, vs))
    pxm = 40075016.686 * math.cos(math.radians(lat_c)) / 2 ** 19 / 256
    return dict(u=cu, v=cv, ref=(rx, ry), err_px=err, center=(cx, cy), pxm=pxm, fr=fr)


def _to_px(f, x, y):
    xk, yk = x * 1e-5, y * 1e-5
    r = (xk, yk, 1.0, xk * xk, xk * yk, yk * yk)
    return f["ref"][0] + sum(a * b for a, b in zip(f["u"], r)), f["ref"][1] + sum(a * b for a, b in zip(f["v"], r))


# ---- render target ----------------------------------------------------------------------------------------------------
def _zero_tex(world):
    if ST["zero"] is None:
        import struct, zlib
        raw = b"".join(b"\x00" + b"\x00" * 4 for _ in range(2))          # 2 x 2 grey16, all 0
        ch = lambda t, d: struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xffffffff)
        png = b"\x89PNG\r\n\x1a\n" + ch(b"IHDR", struct.pack(">IIBBBBB", 2, 2, 16, 0, 0, 0, 0)) + ch(b"IDAT", zlib.compress(raw)) + ch(b"IEND", b"")
        ST["zero"] = _buf(png)
    return ST["zero"]


def _draw(world, tex, sx, sy, more=()):
    """tex into slot (sx, sy) (and (tex, sx, sy) in more), one canvas pass, opaque (raw values, RGBA16F = gamma 1)."""
    R = unreal.RenderingLibrary
    canvas, size, ctx = R.begin_draw_canvas_to_render_target(world, ST["rt"])
    for t, x, y in ((tex, sx, sy),) + tuple(more):
        canvas.draw_texture(t, unreal.Vector2D(x * TILE, y * TILE), unreal.Vector2D(TILE, TILE), unreal.Vector2D(0, 0),
                            unreal.Vector2D(1, 1), unreal.LinearColor(1, 1, 1, 1), unreal.BlendMode.BLEND_OPAQUE)
    R.end_draw_canvas_to_render_target(world, ctx)


def _buf(b):
    if ST.get("buf_mode") != "list":
        try:
            t = unreal.RenderingLibrary.import_buffer_as_texture2d(ST["world"], b)
            ST["buf_mode"] = "bytes"
            return t
        except Exception:
            ST["buf_mode"] = "list"
    return unreal.RenderingLibrary.import_buffer_as_texture2d(ST["world"], list(b))


def _set(world, name, v):
    unreal.MaterialLibrary.set_vector_parameter_value(world, ST["mpc"], name, unreal.LinearColor(*[float(a) for a in v]))


def _knobs():
    d = dict(DEF)
    try:
        import tune_look
        if tune_look.on():
            d.update({k: float(v) for k, v in tune_look.values().items() if k in DEF})
    except Exception:
        pass
    return d


def _sun(world):
    for a in unreal.GameplayStatics.get_all_actors_of_class(world, unreal.DirectionalLight):
        f = a.get_actor_forward_vector()
        return (-f.x, -f.y, -f.z)
    return (0.0, 0.0, 1.0)


def _update(world):
    cm = unreal.GameplayStatics.get_player_camera_manager(world, 0)
    if cm is None:
        return
    loc, fwd = cm.get_camera_location(), cm.get_actor_forward_vector()
    o = _origin(world)
    if o is None:
        return
    f = ST["fit"]
    if f is None or o != ST["origin"] or math.hypot(loc.x - f["center"][0], loc.y - f["center"][1]) > 150000.0:
        ST["fit"], ST["origin"] = f, o = _fit(o, loc.x, loc.y), o
        log("fit origin %.5f %.5f: max error %.3f px" % (o[0], o[1], f["err_px"]))
        ST["win"] = None
    hz = math.hypot(fwd.x, fwd.y) or 1.0
    ax, ay = loc.x + fwd.x / hz * AHEAD_M * 100.0, loc.y + fwd.y / hz * AHEAD_M * 100.0
    gx, gy = _to_px(f, ax, ay)
    tx0, ty0 = int(gx // TILE) - N // 2, int(gy // TILE) - N // 2
    if ST["win"] != (tx0, ty0):
        ST["win"] = (tx0, ty0)
        want = [(tx0 + i, ty0 + j) for j in range(N) for i in range(N)]
        cx, cy = _to_px(f, loc.x, loc.y)
        want.sort(key=lambda k: (k[0] * TILE + TILE / 2 - cx) ** 2 + (k[1] * TILE + TILE / 2 - cy) ** 2)
        wset = set(want)
        for k in [k for k in ST["slots"] if k not in wset]:
            del ST["slots"][k]
        ST["want"] = [k for k in want if k not in ST["slots"]]
        if ST["want"]:                                      # slots about to be reused: zero (A = 0, no relief) until drawn
            z = _zero_tex(world)
            _draw(world, z, ST["want"][0][0] % N, ST["want"][0][1] % N, [(z, k[0] % N, k[1] % N) for k in ST["want"][1:]])
    # window corner -> rows relative to it; RT uv = frac((p + corner mod SIZE) / SIZE)
    cx0, cy0 = tx0 * TILE - f["ref"][0], ty0 * TILE - f["ref"][1]
    u, v = f["u"], f["v"]
    _set(world, "RelU", (u[0], u[1], u[2] - cx0, 0.0)); _set(world, "RelU2", (u[3], u[4], u[5], 0.0))
    _set(world, "RelV", (v[0], v[1], v[2] - cy0, 0.0)); _set(world, "RelV2", (v[3], v[4], v[5], 0.0))
    _set(world, "RelWin", ((tx0 % N) * TILE, (ty0 % N) * TILE, SIZE, 0.0))
    s = _sun(world)
    _set(world, "RelSun", (s[0], s[1], s[2], 0.0))
    k = _knobs()
    _set(world, "RelK", (k["RelGain"] / MADE_GAIN, k["RelNormal"], k["RelShadow"], 0.0))
    _set(world, "RelF", (k["RelFadeNear"], k["RelFadeFar"], f["pxm"], 1.0))


def _photo_url():
    if ST.get("photo_arg"):
        return ST["photo_arg"]
    try:
        for c in ST["ts"].get_components_by_class(unreal.CesiumUrlTemplateRasterOverlay):
            u = str(c.get_editor_property("template_url"))
            if "/vworld/sat/" in u or "/Satellite/" in u:
                return u
    except Exception:
        pass
    return "http://127.0.0.1:8790/vworld/sat/{z}/{reverseY}/{x}.jpg"


def _tick(dt):
    try:
        w = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_game_world()
        if w is None or not ST["on"]:
            return
        url = _photo_url()
        if url != ST["photo"]:
            if ST["proc"] is not None:
                try:
                    ST["proc"].kill()                         # our own worker (started below with our pid as parent)
                except Exception:
                    pass
                ST["proc"] = None
            ST["photo"] = url
            if not _worker(url):
                ST["on"] = False
                return
            ST["world"] = None
        if w != ST["world"]:
            ST.update(world=w, slots={}, win=None, fit=None, want=[])
            unreal.RenderingLibrary.clear_render_target2d(w, ST["rt"], unreal.LinearColor(0, 0, 0, 0))
        ST["t"] += dt
        if ST["t"] >= 0.2:
            ST["t"] = 0.0
            _update(w)
        while len(ST["busy"]) < 2 and ST["want"]:            # two requests in flight
            k = ST["want"].pop(0)
            ST["busy"].add(k); ST["n_req"] += 1
            threading.Thread(target=_fetch, args=(k,), daemon=True).start()
        for _ in range(1):                                    # one RT draw per frame (import ~11-15 ms on the game thread)
            try:
                k, b, info = ST["done"].get_nowait()
            except queue.Empty:
                break
            ST["busy"].discard(k)
            if b is None:
                ST["errors"] += 1; ST["last_err"] = str(info)[:200]
                if ST["win"] and ST["errors"] < 2000:
                    ST["want"].append(k)                      # worker still loading the model: try again later
                continue
            tx0, ty0 = ST["win"] or (None, None)
            if tx0 is None or not (tx0 <= k[0] < tx0 + N and ty0 <= k[1] < ty0 + N):
                continue                                      # left the window meanwhile
            t0 = time.perf_counter()
            tex = _buf(b)
            t1 = time.perf_counter()
            ST["ms_import"] = ST.get("ms_import", 0.0) + (t1 - t0) * 1000
            if tex is not None:
                _draw(w, tex, k[0] % N, k[1] % N)
                ST["slots"][k] = True
                ST["n_drawn"] += 1
                if os.environ.get("GYROSIM_RELIEF_CHECK") == "1" and ST["n_drawn"] in (5, 40):
                    ST["check"] = check(w, k, b)
            ST["ms_draw"] += (time.perf_counter() - t0) * 1000
    except Exception as e:
        ST["errors"] += 1; ST["last_err"] = repr(e)
        if ST["errors"] < 20:
            log("tick", repr(e))


def _png_px(b, x, y):
    """RGBA16 value (0..1) at (x, y) of a filter-0 PNG made by sim/photo_relief.py (debug check)."""
    import struct, zlib
    i, idat, w = 8, b"", 0
    while i < len(b):
        n = struct.unpack(">I", b[i:i + 4])[0]; t = b[i + 4:i + 8]; d = b[i + 8:i + 8 + n]; i += 12 + n
        if t == b"IHDR":
            w = struct.unpack(">I", d[:4])[0]
        elif t == b"IDAT":
            idat += d
    raw = zlib.decompress(idat)
    o = y * (1 + w * 2) + 1 + x * 2
    return [struct.unpack(">H", raw[o:o + 2])[0] / 65535.0]


def check(world, k, b):
    """RT read-back of tile k (drawn from PNG bytes b) at a few pixels vs the PNG -> log (debug, GYROSIM_RELIEF_CHECK=1)."""
    out = []
    for (x, y) in ((100, 200), (300, 50), (450, 400)):
        e = _png_px(b, x, y)
        g = unreal.RenderingLibrary.read_render_target_raw_pixel(world, ST["rt"], (k[0] % N) * TILE + x, (k[1] % N) * TILE + y, False)
        out.append(dict(px=(x, y), png=round(e[0], 4), rt=[round(g.r, 4), round(g.g, 4), round(g.b, 4), round(g.a, 4)]))
    log("check", k, "rt size", ST["rt"].get_editor_property("size_x"), ST["rt"].get_editor_property("render_target_format"), json.dumps(out))
    return out


def status():
    return dict(on=ST["on"], port=ST["port"], drawn=ST["n_drawn"], requested=ST["n_req"], resident=len(ST["slots"]),
                pending=len(ST["want"]), busy=len(ST["busy"]), errors=ST["errors"], last_err=ST["last_err"],
                ms_draw_avg=round(ST["ms_draw"] / max(1, ST["n_drawn"]), 2),
                ms_import_avg=round(ST.get("ms_import", 0.0) / max(1, ST["n_drawn"]), 2), buf_mode=ST.get("buf_mode"),
                fit_err_px=(ST["fit"] or {}).get("err_px"))


def worker_status():
    try:
        with urllib.request.urlopen("http://127.0.0.1:%d/status" % ST["port"], timeout=2) as r:
            return json.loads(r.read())
    except Exception as e:
        return dict(error=repr(e))


def start(tileset=None, photo=None):
    """at Play after the ground material is set (atmos_look.apply_ground). Idempotent."""
    ST["mpc"] = ST["mpc"] or unreal.load_asset(MPC)
    ST["rt"] = ST["rt"] or unreal.load_asset(RT)
    if ST["mpc"] is None or ST["rt"] is None:
        log("no", MPC, "/", RT, "(run Scripts/ground_material.py) - relief off")
        return False
    world = tileset.get_world() if tileset is not None else None
    if not on():
        ST["on"] = False
        if world is not None:
            _set(world, "RelF", (0.0, 0.0, 0.0, 0.0))
        log("GYROSIM_PHOTO_DEPTH=0: off")
        return False                                      # off: no resize to SIZE (4096^2 x 8 B = 128 MiB)
    try:                                                  # the asset's size does not stick when set in the commandlet
        if ST["rt"].get_editor_property("size_x") != SIZE or ST["rt"].get_editor_property("size_y") != SIZE:
            unreal.RenderingLibrary.resize_render_target2d(ST["rt"], SIZE, SIZE)
    except Exception as e:
        log("rt resize", repr(e))
    if not os.path.isfile(PY):
        log("no relief python", PY, "- relief off")
        return False
    ST.update(ts=tileset, photo_arg=photo, on=True)        # the worker starts on the first tick (the overlay URL is set by then)
    ST["world"] = None                                    # clear + refit on the next tick
    if ST["h"] is None:
        ST["h"] = unreal.register_slate_post_tick_callback(_tick)
    return True
