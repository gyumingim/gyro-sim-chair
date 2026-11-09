"""Busan minimap picture for the Unreal minimap (sim_client.py _minimap), made from the LOCAL V-World tile cache.

    python sim/minimap_build.py               # -> C:/GyroSimTiles/minimap/busan_minimap.png + .json   (no API calls)

The picture is a Web Mercator mosaic of the cached V-World Satellite tiles (z14; a missing z14 tile is put together from
its cached z15 / z16 children, sea / no tile = flat sea colour) over a square box around Busan, scaled to SIZE px (default 1024, env GYROSIM_MINIMAP_PX), with
the city border (KOSTAT 2013 provinces, the file vworld_fill.py downloaded) and a few Korean place names (positions
approximate, for orientation only). The .json holds the Mercator bounds so Unreal can put the aircraft marker on it.

V-World terms (docs/vworld-integration.md): the output stays OUTSIDE git (C:/GyroSimTiles, or GYROSIM_TILES) - it is a
derived picture of V-World tiles. Never commit or upload it.
"""
import glob, io, json, math, os, sys, time
from PIL import Image, ImageDraw, ImageFont

TILES = os.environ.get("GYROSIM_TILES", r"C:\GyroSimTiles")
SAT = os.path.join(TILES, "vworld", "Satellite")
OUT = os.path.join(TILES, "minimap")
BOUNDARY = os.path.join(TILES, "incoming", "boundary_dl", "prov2013.json")
BOX = (128.75, 34.96, 129.33, 35.40)          # = terrain_dem.HIRES busan box (lon0, lat0, lon1, lat1)
Z, SIZE = 14, int(os.environ.get("GYROSIM_MINIMAP_PX", "1024"))      # Unreal draws it 1:1 into a SIZE px render target
SEA = (22, 46, 70)
FONT = r"C:\Windows\Fonts\malgunbd.ttf"
# (name, lat, lon[, label side: l = left of the dot, up = above, down = below]) - approximate centres, orientation only
PLACES = [("김해공항", 35.1733, 128.9469, "l"), ("서면", 35.1578, 129.0600, "up"), ("부산역", 35.1151, 129.0422),
          ("해운대", 35.1587, 129.1604), ("광안리", 35.1532, 129.1187, "down"), ("남포동", 35.0979, 129.0300, "l"),
          ("영도", 35.0800, 129.0680), ("사상", 35.1526, 128.9910), ("구포", 35.2056, 129.0036),
          ("동래", 35.2050, 129.0786), ("금정산", 35.2827, 129.0446), ("기장", 35.2445, 129.2222),
          ("다대포", 35.0469, 128.9660), ("부산신항", 35.0750, 128.8300),
          ("낙동강", 35.1200, 128.9420)]


def merc(lat, lon):
    """lat/lon -> Web Mercator world coordinate in 0..1 (x east, y south)."""
    s = math.sin(math.radians(lat))
    return (lon + 180.0) / 360.0, 0.5 - math.log((1 + s) / (1 - s)) / (4 * math.pi)


def tile_img(z, x, y, depth=2):
    """256 px picture of tile (z, x, y) from the cache: the file, else its 4 children (recursively), else None."""
    p = os.path.join(SAT, str(z), str(y), "%d.jpg" % x)
    if os.path.exists(p):
        try:
            return Image.open(p).convert("RGB")
        except Exception:
            pass
    if depth <= 0:
        return None
    kids = [(dx, dy, tile_img(z + 1, 2 * x + dx, 2 * y + dy, depth - 1)) for dy in (0, 1) for dx in (0, 1)]
    if all(k[2] is None for k in kids):
        return None
    im = Image.new("RGB", (512, 512), SEA)
    for dx, dy, k in kids:
        if k is not None:
            im.paste(k.resize((256, 256), Image.LANCZOS) if k.size != (256, 256) else k, (256 * dx, 256 * dy))
    return im.resize((256, 256), Image.LANCZOS)


def border_rings():
    try:
        d = json.load(open(BOUNDARY, encoding="utf-8"))
    except Exception as e:
        print("no boundary file (%s) - no border line" % e)
        return []
    for f in d.get("features", []):
        pr = f.get("properties") or {}
        txt = " ".join(str(v) for v in pr.values())
        if "Busan" in txt or "부산" in txt:
            g = f["geometry"]
            polys = g["coordinates"] if g["type"] == "MultiPolygon" else [g["coordinates"]]
            return [ring for poly in polys for ring in poly]
    return []


def build():
    t0 = time.time()
    # square box (in Mercator) around the Busan box centre, side = the larger box side + 4 % margin
    x0, y1 = merc(BOX[1], BOX[0])
    x1, y0 = merc(BOX[3], BOX[2])
    cx, cy, half = (x0 + x1) / 2, (y0 + y1) / 2, max(x1 - x0, y1 - y0) * 0.52
    mx0, my0, mx1, my1 = cx - half, cy - half, cx + half, cy + half
    n = 2 ** Z
    tx0, ty0, tx1, ty1 = int(mx0 * n), int(my0 * n), int(mx1 * n), int(my1 * n)
    W, H = (tx1 - tx0 + 1) * 256, (ty1 - ty0 + 1) * 256
    big = Image.new("RGB", (W, H), SEA)
    used = missing = 0
    for ty in range(ty0, ty1 + 1):
        for tx in range(tx0, tx1 + 1):
            im = tile_img(Z, tx, ty)
            if im is None:
                missing += 1
                continue
            used += 1
            big.paste(im, ((tx - tx0) * 256, (ty - ty0) * 256))
    # crop to the square box, scale
    px = lambda mx, my: ((mx * n - tx0) * 256, (my * n - ty0) * 256)
    a, b = px(mx0, my0), px(mx1, my1)
    img = big.crop((int(round(a[0])), int(round(a[1])), int(round(b[0])), int(round(b[1])))).resize((SIZE, SIZE), Image.LANCZOS)
    # slightly darker, so the marker / names stand out
    img = Image.eval(img, lambda v: int(v * 0.85))
    dr = ImageDraw.Draw(img, "RGBA")
    to_px = lambda lat, lon: ((merc(lat, lon)[0] - mx0) / (mx1 - mx0) * SIZE, (merc(lat, lon)[1] - my0) / (my1 - my0) * SIZE)
    K = SIZE / 2048.0                              # sizes below were chosen at 2048 px
    for ring in border_rings():
        pts = [to_px(p[1], p[0]) for p in ring]
        if len(pts) > 2:
            dr.line(pts + [pts[0]], fill=(255, 255, 255, 170), width=max(2, int(round(5 * K))), joint="curve")
    try:
        font = ImageFont.truetype(FONT, int(round(80 * K)))
        small = ImageFont.truetype(FONT, int(round(36 * K)))
    except Exception:
        font = small = ImageFont.load_default()
    for name, lat, lon, *side in PLACES:
        x, y = to_px(lat, lon)
        d = 7 * K
        dr.ellipse((x - d, y - d, x + d, y + d), fill=(255, 220, 90, 230))
        side = side[0] if side else "r"
        g = 12 * K
        at, anchor = {"l": ((x - g, y), "rm"), "up": ((x, y - g), "mb"), "down": ((x, y + g), "mt")}.get(side, ((x + g, y), "lm"))
        dr.text(at, name, font=font, fill=(255, 255, 255, 255), anchor=anchor, stroke_width=max(2, int(round(5 * K))), stroke_fill=(0, 0, 0, 230))
    dr.text((SIZE - 16 * K, SIZE - 12 * K), "지도: 브이월드(V-World), 국토교통부", font=small, fill=(255, 255, 255, 220), anchor="rb",
            stroke_width=max(1, int(round(3 * K))), stroke_fill=(0, 0, 0, 200))
    os.makedirs(OUT, exist_ok=True)
    png = os.path.join(OUT, "busan_minimap.png")
    img.save(png, optimize=True)
    lat_of = lambda my: math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * my))))
    meta = dict(made=time.strftime("%Y-%m-%d %H:%M:%S"), png=png, size=SIZE, zoom=Z, merc=[mx0, my0, mx1, my1],
                lon=[mx0 * 360 - 180, mx1 * 360 - 180], lat=[lat_of(my1), lat_of(my0)], tiles_used=used, tiles_missing_sea=missing,
                source="V-World Satellite tile cache " + SAT + " (local only, never commit)", places=PLACES,
                note="merc = Web Mercator 0..1 (x east, y south) of the picture's left / top / right / bottom edges")
    with open(os.path.join(OUT, "busan_minimap.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=1)
    print("minimap %d px, z%d tiles used %d, empty (sea) %d, %.0f s -> %s" % (SIZE, Z, used, missing, time.time() - t0, png))
    print("lat %.4f..%.4f lon %.4f..%.4f" % (meta["lat"][0], meta["lat"][1], meta["lon"][0], meta["lon"][1]))


if __name__ == "__main__":
    build()
