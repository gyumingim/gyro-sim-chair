"""Coast v2 at Play (vworld mode, Busan): keeps the ground material's world -> coast-mask mapping right.
T_GyroCoast (sim/coast_build.py --mask; imported by Scripts/ground_material.py) is an equirectangular raster over the Busan box
(C:/GyroSimTiles/coast/coast_mask.json). The material (ground_look.hlsl 'coast v2') turns the world position P (cm, X north,
Y east, origin = the Cesium georeference origin) into mask UV with two affine rows, CoastU / CoastV, in the material parameter
collection MPC_GyroCoast. The Cesium origin moves (start airfield, art_shots views), so start() registers a light tick that
refits the rows whenever the origin changes (least squares over a 9 x 9 lat / lon grid; residual logged, ~0.5 m).
Toggles: GYROSIM_COAST_V2=0 -> CoastOn 0 (the sea rule before), GYROSIM_SEA_MASK=0 -> BridgeMaskOn 0 (bridge ghosts back).
"""
import json, math, os
import unreal

MPC = "/Game/Materials/Ground/MPC_GyroCoast"
MASK_JSON = os.environ.get("GYROSIM_COAST_MASK_JSON", r"C:/GyroSimTiles/coast/coast_mask.json")
BOX = (34.96, 128.75, 35.40, 129.33)                      # S W N E (fallback when the json is missing)
ST = dict(handle=None, key=None, mpc=None, fit=None, t=0.0)
log = lambda *a: unreal.log("[coast] " + " ".join(str(x) for x in a))


def ground_params_off():
    """dynamic-instance overrides for the A/B toggles."""
    off = {}
    if os.environ.get("GYROSIM_COAST_V2", "1") == "0":
        off["CoastOn"] = 0.0
    if os.environ.get("GYROSIM_SEA_MASK", "1") == "0":
        off["BridgeMaskOn"] = 0.0
    return off


def _box():
    try:
        with open(MASK_JSON, encoding="utf-8") as f:
            return tuple(json.load(f)["box_swne"])
    except Exception:
        return BOX


def fit(lat0, lon0, h0):
    """affine rows (a, b, c) for u and v: u = a Px + b Py + c, with P in cm of the world frame at origin (lat0, lon0, h0)."""
    import geo
    s, w, n, e = _box()
    fr = geo.Frame(lat0, lon0, h0)
    rows, us, vs = [], [], []
    for i in range(9):
        for j in range(9):
            lat, lon = s + (n - s) * i / 8.0, w + (e - w) * j / 8.0
            x, y, _ = fr.world(lat, lon, 29.0)
            rows.append((x, y, 1.0))
            us.append((lon - w) / (e - w))
            vs.append((n - lat) / (n - s))
    # 3 x 3 normal equations (no numpy in every editor python): scale x, y to km for conditioning
    def solve(t):
        A = [[0.0] * 3 for _ in range(3)]
        bb = [0.0] * 3
        for (x, y, o), tv in zip(rows, t):
            r = (x * 1e-5, y * 1e-5, o)
            for p in range(3):
                bb[p] += r[p] * tv
                for q in range(3):
                    A[p][q] += r[p] * r[q]
        for p in range(3):                                # Gauss-Jordan
            piv = A[p][p]
            for q in range(3):
                A[p][q] /= piv
            bb[p] /= piv
            for r2 in range(3):
                if r2 != p:
                    f = A[r2][p]
                    for q in range(3):
                        A[r2][q] -= f * A[p][q]
                    bb[r2] -= f * bb[p]
        return (bb[0] * 1e-5, bb[1] * 1e-5, bb[2])
    cu, cv = solve(us), solve(vs)
    err = 0.0
    for (x, y, _), u, v in zip(rows, us, vs):
        du = (cu[0] * x + cu[1] * y + cu[2] - u) * (e - w) * 111320.0 * math.cos(math.radians((s + n) / 2))
        dv = (cv[0] * x + cv[1] * y + cv[2] - v) * (n - s) * 110574.0
        err = max(err, math.hypot(du, dv))
    return cu, cv, err


def _origin(world):
    for a in unreal.GameplayStatics.get_all_actors_of_class(world, unreal.CesiumGeoreference):
        try:
            return (float(a.get_editor_property("origin_latitude")), float(a.get_editor_property("origin_longitude")),
                    float(a.get_editor_property("origin_height")))
        except Exception:
            return None
    return None


def sync(world, force=False):
    """refit + write MPC_GyroCoast when the georeference origin changed. -> True when written."""
    if world is None:
        return False
    o = _origin(world)
    if o is None or (o == ST["key"] and not force):
        return False
    if ST["mpc"] is None:
        ST["mpc"] = unreal.load_asset(MPC)
        if ST["mpc"] is None:
            log("no", MPC, "(run Scripts/ground_material.py)")
            ST["key"] = o
            return False
    cu, cv, err = fit(*o)
    K = unreal.KismetMaterialLibrary
    K.set_vector_parameter_value(world, ST["mpc"], "CoastU", unreal.LinearColor(cu[0], cu[1], cu[2], 0.0))
    K.set_vector_parameter_value(world, ST["mpc"], "CoastV", unreal.LinearColor(cv[0], cv[1], cv[2], 0.0))
    ST["key"], ST["fit"] = o, dict(u=cu, v=cv, max_err_m=round(err, 2))
    log("mask mapping for origin %.5f %.5f: max fit error %.2f m" % (o[0], o[1], err))
    return True


def _tick(dt):
    ST["t"] += dt
    if ST["t"] < 0.25:
        return
    ST["t"] = 0.0
    try:
        ues = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem)
        w = ues.get_game_world()
        if w is not None:
            sync(w)
    except Exception:
        pass


def start(tileset=None):
    """first fit now (the tileset's world) and keep following the origin."""
    try:
        if tileset is not None:
            ST["key"] = None
            sync(tileset.get_world(), force=True)
    except Exception as e:
        log("sync", repr(e))
    if ST["handle"] is None:
        try:
            ST["handle"] = unreal.register_slate_post_tick_callback(_tick)
        except Exception as e:
            log("tick", repr(e))
