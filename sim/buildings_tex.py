"""Textures for the 3D buildings (sim/buildings_build.py --tiles): roofs show the V-World photo of that spot, walls get
window rows (one per real floor) tinted by a colour derived from the photo of that building's roof.

Only tiles ALREADY in the proxy cache (C:\\GyroSimTiles\\vworld\\Satellite\\{z}\\{y}\\{x}.jpg, WMTS row from the north,
Web Mercator) are read - no API call is ever made here. Everything derived (roof atlases inside the glb) stays in
C:\\GyroSimTiles (never in git, never uploaded: V-World terms 18 / 19, see docs/vworld-integration.md 7).

Roof: per glb tile one JPEG atlas; each building's footprint box is cut out of the best cached zoom (17 .. 14) and packed
(shelf packing, 2 px of real neighbouring pixels around each cut, so no seams). Roof UV = the vertex's Mercator pixel.
Wall colour (per building): photo pixels inside the footprint (eroded 1 px when big enough), darkest 35 % (shadows) and
brightest 3 % (glare) dropped, per-channel median, times grey-world gains (the photos have a blue-green cast) = roof colour. Wall = that colour moved toward a wall-like lightness
for the use class and with its chroma scaled down per class (apartments mostly off-white, factories keep the panel
colour); green (painted flat roofs) is damped further - walls are rarely green. No photo -> a class palette (가정).
Walls: one 64 x 64 floor-module texture per use class (plain, house, apartment, shop ground floor, office / upper
floors, factory), one primitive per class in each glb, sampler REPEAT in u and v: u repeats once per bay along the ring
(whole bays per ring), v once per floor (the data's floor count when it fits the height). One quad per wall edge as
before; shops get a separate ground-floor band (shop window texture).
"""
import io, math, os
import numpy as np

SAT = os.path.join(os.environ.get("GYROSIM_VWORLD_CACHE", r"C:\GyroSimTiles\vworld"), "Satellite")
# best first. v3 (11-10): z18 first (0.49 m/px in Busan, cache 100 % after the 11-09 fill) - z17 roofs (0.98 m/px) were
# blurry at 150 m. The atlas cap below scales a dense tile back toward z17. GYROSIM_BLDG_V3=0 = the old (17, 16, 15, 14).
ZOOMS = (17, 16, 15, 14) if os.environ.get("GYROSIM_BLDG_V3", "1") == "0" else (18, 17, 16, 15, 14)
ROOF_MIN_PX = 8                            # footprint pixels needed for a photo roof (z16 ~ 30 m2, z14 ~ 470 m2)
COLOR_MIN_PX = 4
CROP_MAX = 256 if os.environ.get("GYROSIM_BLDG_V3", "1") == "0" else 384   # px, larger cut-outs are scaled down
PAD = 2
ATLAS_MAX = 2048

# use classes (same order as buildings_build.USE_NAMES)
PLAIN, HOUSE, APT, SHOP, OFFICE, FACTORY = range(6)
#              plain  house  apt   shop  office factory
WALL_L = np.array([0.62, 0.74, 0.86, 0.72, 0.74, 0.76])     # target wall luminance (sRGB 0..1)
WALL_MIX = np.array([0.6, 0.6, 0.75, 0.6, 0.6, 0.6])        # how far the roof lightness is moved to that target
CAST_STRENGTH = 0.5                                          # photo colour cast removed (grey world over the cache) before the hue is used
WALL_K = np.array([0.6, 0.65, 0.35, 0.5, 0.45, 0.7])        # chroma kept from the roof colour
GREEN_K = 0.35                                               # extra factor for green hues
BAY = np.array([4.0, 3.6, 3.0, 4.0, 3.2, 6.0])               # m per texture repeat along the wall
FLOOR_H = np.array([0.0, 3.0, 2.9, 3.6, 3.6, 0.0])           # m per floor when the data has no floor count (0 = one module)
# atlas rows: 0 plain, 1 house, 2 apartment, 3 shop ground floor, 4 punched windows (shop upper floors, small offices),
# 5 factory, 6 curtain wall (offices >= 8 floors), 7 spare (plain)
ROW_N = 8
# no photo: class palettes (sRGB), picked by building id (가정: typical Korean colours)
PALETTE = {PLAIN: [(0.62, 0.61, 0.58), (0.55, 0.55, 0.55), (0.66, 0.64, 0.60)],
           HOUSE: [(0.86, 0.84, 0.78), (0.74, 0.70, 0.64), (0.62, 0.45, 0.38), (0.80, 0.78, 0.74), (0.70, 0.66, 0.58)],
           APT: [(0.88, 0.86, 0.82), (0.84, 0.80, 0.72), (0.86, 0.86, 0.86), (0.80, 0.78, 0.74)],
           SHOP: [(0.80, 0.78, 0.74), (0.70, 0.68, 0.64), (0.66, 0.56, 0.48), (0.78, 0.80, 0.82), (0.60, 0.60, 0.60)],
           OFFICE: [(0.78, 0.78, 0.76), (0.70, 0.72, 0.74), (0.74, 0.68, 0.60), (0.64, 0.64, 0.64)],
           FACTORY: [(0.80, 0.80, 0.78), (0.62, 0.68, 0.76), (0.70, 0.70, 0.70), (0.56, 0.64, 0.70)]}


def srgb_to_lin(c):
    c = np.asarray(c, np.float64)
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)


def lum(c):
    c = np.asarray(c)
    return 0.299 * c[..., 0] + 0.587 * c[..., 1] + 0.114 * c[..., 2]


def wall_from_roof(roof, cls, jitter):
    """roof: sRGB 0..1 (3,), cls: use class, jitter -1..1 -> wall sRGB 0..1."""
    roof = np.asarray(roof, np.float64)
    lr = float(lum(roof))
    d = roof - lr                                            # chroma part
    k = WALL_K[cls]
    r, g, b = roof
    if g > r and g >= b * 0.95:                              # green-ish (painted roofs, trees on the edge)
        k *= GREEN_K
    lw = lr + (WALL_L[cls] - lr) * WALL_MIX[cls] + 0.04 * jitter
    return np.clip(lw + k * d, 0.0, 1.0)


def palette_wall(cls, u):
    p = PALETTE[int(cls)]
    return np.array(p[int(u * len(p)) % len(p)])


# ---- satellite cache -------------------------------------------------------------------------------------------------
class Sat:
    """read-only access to the cached V-World tiles (decoded tiles kept in a small LRU)."""

    def __init__(self, root=SAT):
        self.root = root
        self.have = {}
        for z in ZOOMS:
            zd = os.path.join(root, str(z))
            if not os.path.isdir(zd):
                continue
            s = set()
            for yd in os.scandir(zd):
                if yd.is_dir():
                    for f in os.scandir(yd.path):
                        if f.name.endswith(".jpg") and f.stat().st_size > 100:
                            s.add((int(yd.name), int(f.name[:-4])))
            self.have[z] = s
        self.lru = {}

    def cast_gain(self):
        """per-channel gains that remove the photo's overall colour cast (the V-World photos here are blue-green):
        grey world over the near-neutral pixels of up to 300 cached tiles (zoom 14-16, 64 x 64 thumbnails), luminance
        kept, CAST_STRENGTH of it."""
        if getattr(self, "_gain", None) is None:
            from PIL import Image
            acc, n = np.zeros(3), 0
            for z in (16, 15, 14):
                for (ty, tx) in sorted(self.have.get(z, ()))[:: max(1, len(self.have.get(z, ())) // 100)]:
                    with Image.open(os.path.join(self.root, str(z), str(ty), "%d.jpg" % tx)) as im:
                        p = np.asarray(im.convert("RGB").resize((64, 64)), np.float64).reshape(-1, 3) / 255.0
                    # near-neutral, not dark pixels only (roads, concrete, roofs): vegetation would read as a green cast
                    p = p[(p.max(1) - p.min(1) < 0.12) & (lum(p) > 0.25)]
                    acc += p.sum(0)
                    n += len(p)
            m = acc / max(n, 1) if n else np.array([0.5, 0.5, 0.5])
            g = float(lum(m)) / np.maximum(m, 1e-3)
            self._gain = 1.0 + CAST_STRENGTH * (g - 1.0)
            self.mean_rgb = m
        return self._gain

    def tiles_count(self):
        return {z: len(s) for z, s in self.have.items()}

    @staticmethod
    def px(z, lat, lon):
        """global Web Mercator pixel coordinates (256 px tiles, y from the north) at zoom z."""
        n = 256.0 * (1 << z)
        la = np.radians(np.clip(lat, -85, 85))
        return (np.asarray(lon) + 180.0) / 360.0 * n, (1.0 - np.log(np.tan(la) + 1.0 / np.cos(la)) / math.pi) / 2.0 * n

    def covered(self, z, x0, y0, x1, y1):
        s = self.have.get(z)
        if not s:
            return False
        for ty in range(y0 // 256, (y1 - 1) // 256 + 1):
            for tx in range(x0 // 256, (x1 - 1) // 256 + 1):
                if (ty, tx) not in s:
                    return False
        return True

    def tile(self, z, ty, tx):
        k = (z, ty, tx)
        a = self.lru.get(k)
        if a is None:
            from PIL import Image
            with Image.open(os.path.join(self.root, str(z), str(ty), "%d.jpg" % tx)) as im:
                a = np.asarray(im.convert("RGB"))
            if len(self.lru) > 1500:
                self.lru.clear()
            self.lru[k] = a
        return a

    def crop(self, z, x0, y0, x1, y1):
        out = np.zeros((y1 - y0, x1 - x0, 3), np.uint8)
        for ty in range(y0 // 256, (y1 - 1) // 256 + 1):
            for tx in range(x0 // 256, (x1 - 1) // 256 + 1):
                t = self.tile(z, ty, tx)
                ax0, ay0 = max(x0, tx * 256), max(y0, ty * 256)
                ax1, ay1 = min(x1, tx * 256 + 256), min(y1, ty * 256 + 256)
                out[ay0 - y0:ay1 - y0, ax0 - x0:ax1 - x0] = t[ay0 - ty * 256:ay1 - ty * 256, ax0 - tx * 256:ax1 - tx * 256]
        return out


def roof_sample(sat, rings_ll):
    """rings_ll: [(lat, lon) arrays, exterior first] -> dict(z, x0, y0, img, color sRGB 0..1 or None, npx) or None."""
    from PIL import Image, ImageDraw
    la = np.concatenate([r[0] for r in rings_ll])
    lo = np.concatenate([r[1] for r in rings_ll])
    for z in ZOOMS:
        X, Y = sat.px(z, la, lo)
        x0, y0 = int(math.floor(X.min())) - PAD, int(math.floor(Y.min())) - PAD
        x1, y1 = int(math.ceil(X.max())) + PAD, int(math.ceil(Y.max())) + PAD
        if not sat.covered(z, x0, y0, x1, y1):
            continue
        img = sat.crop(z, x0, y0, x1, y1)
        m = Image.new("L", (x1 - x0, y1 - y0), 0)
        dr = ImageDraw.Draw(m)
        for i, (rla, rlo) in enumerate(rings_ll):
            rx, ry = sat.px(z, rla, rlo)
            dr.polygon(list(zip((rx - x0).tolist(), (ry - y0).tolist())), fill=0 if i else 1)
        mask = np.asarray(m, bool)
        npx = int(mask.sum())
        if npx >= 40:                                         # 1 px erosion: edge pixels mix the ground / walls / shadows
            e = mask.copy()
            e[1:] &= mask[:-1]
            e[:-1] &= mask[1:]
            e[:, 1:] &= mask[:, :-1]
            e[:, :-1] &= mask[:, 1:]
            if e.sum() >= 20:
                mask = e
        col = None
        if npx >= COLOR_MIN_PX:
            p = img[mask].astype(np.float64) / 255.0
            y = lum(p)
            lo_, hi_ = np.percentile(y, 35), np.percentile(y, 97)
            sel = (y >= lo_) & (y <= hi_)
            if sel.sum() >= 2:
                p = p[sel]
            col = np.clip(np.median(p, axis=0) * sat.cast_gain(), 0.0, 1.0)
        return dict(z=z, x0=x0, y0=y0, img=img, color=col, npx=npx)
    return None


# ---- roof atlas ------------------------------------------------------------------------------------------------------
def pack(sizes, width):
    """shelf packing of (w, h) boxes (tallest first) -> positions, used height."""
    order = sorted(range(len(sizes)), key=lambda i: -sizes[i][1])
    pos = [None] * len(sizes)
    x = y = shelf = 0
    for i in order:
        w, h = sizes[i]
        if x + w > width:
            x, y, shelf = 0, y + shelf, 0
        pos[i] = (x, y)
        x += w
        shelf = max(shelf, h)
    return pos, y + shelf


def roof_atlas(cuts):
    """cuts: list of HxWx3 uint8 images -> (jpeg bytes, atlas w, h, [(ox, oy, scale)], white patch (u, v)).
    The first 4 x 4 block is white (roofs without a photo point there and keep their vertex colour)."""
    from PIL import Image
    imgs = [np.full((4, 4, 3), 255, np.uint8)] + list(cuts)
    scale = 1.0
    for _ in range(8):
        sz = []
        for im in imgs:
            h, w = im.shape[:2]
            f = min(scale, CROP_MAX / max(h, w)) if len(sz) else 1.0
            sz.append((max(1, int(round(w * f))), max(1, int(round(h * f)))))
        area = sum(w * h for w, h in sz)
        width = 1 << max(6, int(math.ceil(math.log2(max(16.0, math.sqrt(area * 1.15))))))
        width = min(max(width, 1 << int(math.ceil(math.log2(max(w for w, _ in sz))))), ATLAS_MAX)   # widest cut fits
        pos, hgt = pack(sz, width)
        if hgt <= ATLAS_MAX:
            break
        scale *= 0.75
    hgt = max(4, (hgt + 3) // 4 * 4)
    # empty space = the mean photo colour (was black: mip maps bled black into roof edges at distance)
    mean = np.mean([c.reshape(-1, 3).mean(0) for c in cuts], axis=0) if cuts else np.full(3, 128.0)
    atlas = np.empty((hgt, width, 3), np.uint8)
    atlas[:] = np.clip(mean, 0, 255).astype(np.uint8)
    out = []
    for im, (w, h), (x, y) in zip(imgs, sz, pos):
        w0 = im.shape[1]
        if (w, h) != (im.shape[1], im.shape[0]):
            im = np.asarray(Image.fromarray(im).resize((w, h), Image.BILINEAR))
        atlas[y:y + h, x:x + w] = im
        # scale = cut width / ORIGINAL width (bug until 11-10: taken after the resize, so always 1.0 - every scaled-down cut
        # (big footprints > CROP_MAX px, and whole dense tiles over ATLAS_MAX) got UVs past its cut: black / foreign roofs)
        out.append((x, y, w / w0 if w0 else 1.0))
    bio = io.BytesIO()
    Image.fromarray(atlas).save(bio, "JPEG", quality=85, optimize=True)
    return bio.getvalue(), width, hgt, out[1:], ((out[0][0] + 2) / width, (out[0][1] + 2) / hgt)


# ---- wall atlas ------------------------------------------------------------------------------------------------------
_WALL_PNG = None


def wall_atlas_png():
    """64 x 512 sRGB PNG, rows of 64 px = one floor module x one bay. Wall surface ~ 0.93 (the vertex colour tints it),
    glass dark blue-grey with a little sky at the top; every module has a plain band at the top and bottom so mip-map
    bleed between rows stays wall-on-wall."""
    global _WALL_PNG
    if _WALL_PNG is not None:
        return _WALL_PNG
    from PIL import Image
    rng = np.random.default_rng(7)
    W, R = 64, 64
    img = np.zeros((R * ROW_N, W, 3), np.float64)
    wall = np.array([0.93, 0.93, 0.92])

    def glass(h):
        t = np.linspace(0, 1, h)[:, None]
        top, bot = np.array([0.55, 0.62, 0.70]), np.array([0.30, 0.35, 0.41])
        return top * (1 - t) + bot * t

    for r in range(ROW_N):
        m = np.tile(wall, (R, W, 1)) + rng.normal(0, 0.012, (R, W, 1))
        if r == 1:                                   # house: one window with a frame and a sill
            m[16:44, 17:47] = 0.80
            m[18:42, 19:45] = glass(24)[:, None, :]
            m[30:31, 19:45] = 0.75; m[18:42, 31:33] = 0.75
            m[44:47, 15:49] = 0.62
        elif r == 2:                                 # apartment: wide balcony glazing + railing band
            m[10:46, 4:60] = 0.82
            m[12:44, 6:58] = glass(32)[:, None, :]
            m[12:44, 31:33] = 0.80; m[12:44, 6:8] = 0.80; m[12:44, 56:58] = 0.80
            m[36:46, 4:60] = 0.86                      # railing / balcony parapet (lighter)
            m[46:50, 0:64] = 0.70                      # slab edge
        elif r == 3:                                 # shop ground floor: sign band + shop window
            m[4:16, 2:62] = 0.55
            m[20:62, 3:61] = glass(42)[:, None, :] * 1.1
            m[20:62, 31:33] = 0.55
        elif r == 4:                                 # shop upper floors / small offices: two punched windows per bay
            for x0 in (5, 37):
                m[16:46, x0 - 1:x0 + 23] = 0.80
                m[18:44, x0:x0 + 22] = glass(26)[:, None, :]
                m[18:44, x0 + 10:x0 + 12] = 0.78
            m[46:48, :] = 0.84
        elif r == 6:                                 # large office: curtain wall (ribbon glass, thin mullions)
            m[10:54, :] = glass(44)[:, None, :]
            m[10:54, 0:2] = 0.66; m[10:54, 31:33] = 0.66
            m[8:10, :] = 0.72; m[54:56, :] = 0.72
        elif r == 5:                                 # factory panel: ribs + clerestory strip
            for x in range(0, W, 8):
                m[:, x:x + 1] *= 0.86
            m[6:16, 6:58] = glass(10)[:, None, :]
        img[r * R:(r + 1) * R] = m
    a = (np.clip(img, 0, 1) * 255 + 0.5).astype(np.uint8)
    bio = io.BytesIO()
    Image.fromarray(a).save(bio, "PNG", optimize=True)
    _WALL_PNG = bio.getvalue()
    return _WALL_PNG


_WALL_PNGS = None


def wall_pngs():
    """the atlas rows as separate 64 x 64 PNGs (one material each, REPEAT in u and v: no per-floor geometry)."""
    global _WALL_PNGS
    if _WALL_PNGS is None:
        from PIL import Image
        a = Image.open(io.BytesIO(wall_atlas_png())).convert("RGB")
        out = []
        for r in range(7):
            bio = io.BytesIO()
            a.crop((0, r * 64, 64, r * 64 + 64)).save(bio, "PNG", optimize=True)
            out.append(bio.getvalue())
        _WALL_PNGS = out
    return _WALL_PNGS


WALL_NAMES = ("wall_plain", "wall_house", "wall_apartment", "wall_shopfront", "wall_punched", "wall_factory", "wall_curtain")

# ---- facade styles for the Unreal building material (unreal/GyroSim/Scripts/buildings_material.py) -------------------
# One glb primitive per style. The style is carried in the glTF roughnessFactor (STYLE_R0 + 0.01 x style, 0.60 .. 0.68:
# the stock Cesium material just reads it as roughness, older tiles have 0.8 walls / 0.95 roofs = "legacy" in the
# material). Per building: vertex colour RGB = wall tint (as before), alpha = 128 + 64 x end-wall flag + seed (0..63) -
# alpha stays >= 0.5, so the stock (masked) Cesium material never clips it. The window patterns themselves are drawn by
# the material from the UV (u = bays along the ring, v = floors down from the roof); the PNG modules stay for the
# stock material / lookdev preview.
ST_PLAIN, ST_HOUSE, ST_APT, ST_SHOP, ST_PUNCHED, ST_FACTORY, ST_CURTAIN, ST_GLASS_TOWER, ST_RIBBON = range(9)
# v3 (11-10): rooftop props (water tanks, laundry racks, lift machine rooms: alpha = 128 + 16 x kind + seed 0..15),
# low apartments (다세대 / 연립 = 빌라, <= 5 floors) and a ground-floor pilotis / lobby band. Style ids up to 19 fit the
# material's 0.60 .. 0.79 range (older tiles: 0.8 walls / 0.95 roofs).
ST_PROP, ST_VILLA, ST_PILOTI, ST_PODIUM = 9, 10, 11, 12
PROP_TANK, PROP_LAUNDRY, PROP_ROOM, PROP_TANK_STEEL, PROP_ROOFROOM, PROP_TARP, PROP_SOLAR = range(7)
STYLE_NAMES = ("plain", "house", "apartment", "shopfront", "punched", "factory", "curtain", "glass_tower", "ribbon",
               "prop", "villa", "piloti", "podium")
STYLE_PNG = (0, 1, 2, 3, 4, 5, 6, 6, 4, 0, 4, 3, 3)            # style -> wall_pngs() module for the stock material
V3 = os.environ.get("GYROSIM_BLDG_V3", "1") != "0"
VILLA_FLOORS = 5                                            # apartments up to this many floors: 빌라 (pilotis, brick / tile)
STYLE_R0 = 0.60
GLASS_TOWER_FLOORS = 40                                     # apartments this tall: glass residential towers (Haeundae, Marine City)
HIGHRISE_FLOORS = 15                                        # non-residential this tall: curtain wall
END_WALL_K = 0.5                                            # apartment edges shorter than this x the longest edge = end (gable) walls


def wall_style(cls, nf):
    """facade style of the upper floors (shops: the ground floor is ST_SHOP separately) - 가정: Korean typology by use + floors."""
    if cls == PLAIN:
        return ST_PLAIN
    if cls == HOUSE:
        return ST_HOUSE if nf < HIGHRISE_FLOORS else ST_CURTAIN
    if cls == APT:
        if V3 and nf <= VILLA_FLOORS:
            return ST_VILLA
        return ST_GLASS_TOWER if nf >= GLASS_TOWER_FLOORS else ST_APT
    if cls == FACTORY:
        return ST_FACTORY
    if cls == OFFICE:
        return ST_CURTAIN if nf >= 8 else ST_RIBBON if nf >= 3 else ST_PUNCHED
    return ST_CURTAIN if nf >= HIGHRISE_FLOORS else ST_PUNCHED          # shops / mixed use


def style_roughness(st):
    return round(STYLE_R0 + 0.01 * st, 3)
