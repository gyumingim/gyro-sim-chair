"""Busan landmark descriptions for landmarks_build.py: footprint source, heights (with sources), and a build function that
draws the shape read off the reference photos. Heights above ground in m. 'est' in a note = estimated (no published number).

Footprint keys: gis:<A1 uid> (국토교통부 GIS건물통합정보, Busan 2026-10-09), way:<id> / relation:<id> (OpenStreetMap, fetched
by --osm), ellipse:lat,lon,a,b,rot (digitised from the local V-World photo; a = east, b = north semi-axis m).
Reference photos (local only): C:\\GyroSimTiles\\landmarks\\refs\\<key>\\sources.json lists each Commons file page + licence.
"""
import math
import numpy as np

# ------------------------------------------------------------------------------------------------- materials (linear rgb)
# u_m / v_m = metres covered by one texture repeat along / up the wall (tex nb bays x nf floors)
MATS = {
    "lct_glass": dict(u_m=6.0, v_m=16.2, tex=dict(glass=(0.34, 0.43, 0.52), frame=(0.60, 0.65, 0.70), mull=2, band=3, var=0.05, metal=0.6, rough=0.08)),
    "lct_glass_light": dict(u_m=6.0, v_m=16.2, tex=dict(glass=(0.42, 0.50, 0.57), frame=(0.70, 0.74, 0.77), mull=3, band=4, var=0.05, metal=0.5, rough=0.1)),
    "zenith_glass": dict(u_m=6.0, v_m=14.8, tex=dict(glass=(0.22, 0.36, 0.48), frame=(0.66, 0.70, 0.73), band_rgb=(0.74, 0.77, 0.79), mull=2, band=9, var=0.06, metal=0.55, rough=0.1)),
    "ipark_glass": dict(u_m=6.0, v_m=16.0, tex=dict(glass=(0.22, 0.36, 0.54), frame=(0.50, 0.58, 0.68), mull=2, sub=2, band=3, var=0.07, metal=0.6, rough=0.08)),
    "bifc_glass": dict(u_m=6.0, v_m=18.4, tex=dict(glass=(0.33, 0.47, 0.58), frame=(0.78, 0.80, 0.82), mull=6, band=4, var=0.04, metal=0.55, rough=0.1)),
    "hyatt_diag": dict(u_m=28.0, v_m=28.0, size=512, tex=dict(nb=8, nf=8, glass=(0.20, 0.28, 0.36), frame=(0.82, 0.82, 0.80), mull=0, band=2, diag=256, diag_w=10, var=0.05, metal=0.55, rough=0.1)),
    "hotel_stone": dict(u_m=14.0, v_m=15.2, tex=dict(panel=1, glass=(0.52, 0.47, 0.40), win=(0.62, 0.55, (0.08, 0.10, 0.12)), mull=0, band=0, frame_rough=0.7, frame_metal=0.0, rough=0.15, metal=0.4)),
    "concrete": dict(u_m=20.0, v_m=20.0, tex=dict(panel=1, glass=(0.55, 0.55, 0.53), mull=0, band=0, frame_rough=0.85, frame_metal=0.0)),
    "white_panel": dict(u_m=12.0, v_m=12.0, tex=dict(panel=1, glass=(0.72, 0.73, 0.72), mull=0, band=0, hstripe=(64, 2), band_rgb=(0.6, 0.6, 0.6), frame_rough=0.6, frame_metal=0.05)),
    "stands": dict(u_m=16.0, v_m=8.0, tex=dict(panel=1, glass=(0.42, 0.43, 0.45), mull=0, band=0, hstripe=(16, 5), band_rgb=(0.25, 0.27, 0.32), frame_rough=0.8, frame_metal=0.0)),
    "stands_orange": dict(u_m=16.0, v_m=8.0, tex=dict(panel=1, glass=(0.48, 0.20, 0.12), mull=0, band=0, hstripe=(16, 5), band_rgb=(0.30, 0.30, 0.32), frame_rough=0.8, frame_metal=0.0)),
    "membrane": dict(u_m=30.0, v_m=30.0, double=True, tex=dict(panel=1, glass=(0.82, 0.83, 0.82), mull=0, band=0, frame_rough=0.55, frame_metal=0.0)),
    "metal_roof": dict(u_m=24.0, v_m=24.0, tex=dict(panel=1, glass=(0.50, 0.52, 0.53), mull=0, band=0, hstripe=(32, 3), band_rgb=(0.40, 0.42, 0.43), frame_rough=0.35, frame_metal=0.7)),
    "roof_grey": dict(u_m=30.0, v_m=30.0, tex=dict(panel=1, glass=(0.38, 0.38, 0.37), mull=0, band=0, frame_rough=0.9, frame_metal=0.0)),
    "glass_curtain": dict(u_m=9.0, v_m=18.0, tex=dict(glass=(0.22, 0.32, 0.40), frame=(0.74, 0.76, 0.77), mull=4, band=5, var=0.04, metal=0.5, rough=0.08)),
    "glass_dark": dict(u_m=8.0, v_m=16.0, tex=dict(glass=(0.10, 0.13, 0.17), frame=(0.35, 0.37, 0.40), mull=3, band=4, var=0.05, metal=0.6, rough=0.07)),
    "tower_white": dict(u_m=10.0, v_m=10.0, tex=dict(panel=1, glass=(0.80, 0.80, 0.78), mull=0, band=0, hstripe=(128, 2), band_rgb=(0.66, 0.66, 0.66), frame_rough=0.45, frame_metal=0.05)),
    "led_under": dict(u_m=20.0, v_m=20.0, double=True, tex=dict(panel=1, glass=(0.30, 0.33, 0.42), mull=0, band=0, hstripe=(32, 3), band_rgb=(0.55, 0.58, 0.70), frame_rough=0.5, frame_metal=0.3)),
    "roof_dark": dict(u_m=20.0, v_m=20.0, tex=dict(panel=1, glass=(0.20, 0.22, 0.22), mull=0, band=0, hstripe=(24, 3), band_rgb=(0.13, 0.14, 0.14), frame_rough=0.6, frame_metal=0.2)),
    # 2026-11-10 districts: painted steel (cranes, masts, cable car) and the Lotte Gwangbok silver drum, no windows
    "steel_white": dict(u_m=8.0, v_m=8.0, tex=dict(panel=1, glass=(0.72, 0.73, 0.72), mull=0, band=0, frame_rough=0.45, frame_metal=0.3)),
    "steel_orange": dict(u_m=8.0, v_m=8.0, tex=dict(panel=1, glass=(0.56, 0.17, 0.06), mull=0, band=0, frame_rough=0.45, frame_metal=0.3)),
    "steel_red": dict(u_m=8.0, v_m=8.0, tex=dict(panel=1, glass=(0.50, 0.06, 0.05), mull=0, band=0, frame_rough=0.45, frame_metal=0.3)),
    "steel_grey": dict(u_m=8.0, v_m=8.0, tex=dict(panel=1, glass=(0.40, 0.42, 0.43), mull=0, band=0, frame_rough=0.4, frame_metal=0.5)),
    "cable": dict(u_m=8.0, v_m=8.0, tex=dict(panel=1, glass=(0.12, 0.12, 0.13), mull=0, band=0, frame_rough=0.4, frame_metal=0.6)),
    "silver_panel": dict(u_m=6.0, v_m=6.0, tex=dict(panel=1, glass=(0.62, 0.64, 0.66), mull=0, band=0, hstripe=(64, 2), band_rgb=(0.48, 0.50, 0.52), frame_rough=0.3, frame_metal=0.6)),
}


# --------------------------------------------------------------------------------------------------------- shape helpers
def _P():
    import landmarks_build as L
    return L


def radial(poly, n=96, outer=True, c=None):
    """resample a polygon ring by angle around its centroid (ray hits: farthest for the exterior, nearest for a hole)."""
    import shapely
    c = c or poly.centroid
    R = 1e4
    ring = poly.exterior if outer else poly.interiors[0]
    out = []
    for t in np.linspace(0, 2 * math.pi, n, endpoint=False):
        ray = shapely.LineString([(c.x, c.y), (c.x + R * math.cos(t), c.y + R * math.sin(t))])
        hit = ray.intersection(ring)
        pts = [(g.x, g.y) for g in getattr(hit, "geoms", [hit]) if g.geom_type == "Point"]
        if not pts:
            out.append(out[-1] if out else (c.x, c.y))
            continue
        d = [math.hypot(x - c.x, y - c.y) for x, y in pts]
        out.append(pts[int(np.argmax(d) if outer else np.argmin(d))])
    return np.asarray(out)


def principal(poly):
    """unit vector of the long axis (PCA of the densified ring) and the centroid."""
    L = _P()
    r = L.densify(L.ring_xy(poly.exterior), 1.0)
    c = r.mean(0)
    w, v = np.linalg.eigh(np.cov((r - c).T))
    return v[:, np.argmax(w)], c


def wings(poly, n):
    """split a cross / Y plan into n wing pieces: sector boundaries half-way between the n farthest ring points (wing tips).
    Returns pieces sorted by tip angle and the tip angles."""
    import shapely
    L = _P()
    c = poly.centroid
    r = L.densify(L.ring_xy(poly.exterior), 0.5)
    ang = np.arctan2(r[:, 1] - c.y, r[:, 0] - c.x)
    rad = np.hypot(r[:, 0] - c.x, r[:, 1] - c.y)
    # tips: n largest local maxima of the radius, at least 360/(2n) degrees apart
    order = np.argsort(-rad)
    tips = []
    for i in order:
        if all(abs((ang[i] - t + math.pi) % (2 * math.pi) - math.pi) > math.pi / n for t in tips):
            tips.append(ang[i])
        if len(tips) == n:
            break
    tips = sorted(tips)
    pieces = []
    for k in range(n):
        a0 = tips[k - 1] + ((tips[k] - tips[k - 1]) % (2 * math.pi)) / 2
        a1 = tips[k] + ((tips[(k + 1) % n] - tips[k]) % (2 * math.pi)) / 2
        if a1 < a0:
            a1 += 2 * math.pi
        arc = np.linspace(a0, a1, 24)
        R = 1e3
        wedge = shapely.Polygon([(c.x, c.y)] + [(c.x + R * math.cos(t), c.y + R * math.sin(t)) for t in arc])
        p = poly.intersection(wedge)
        p = max(getattr(p, "geoms", [p]), key=lambda g: g.area)
        pieces.append(p)
    return pieces, tips


def tower(cx, poly, h, mat, roof="roof_grey", parapet=1.2, top=None, color=None):
    _P().prism(cx.M, poly, 0.0, top if top is not None else h, mat, roof, parapet=parapet, color=color)


def screen(cx, poly, z0, z1, mat, inset=0.0):
    """open glass screen (crown fins) along a footprint outline, both sides."""
    L = _P()
    import shapely
    p = shapely.geometry.polygon.orient(poly.buffer(-inset) if inset else poly, 1.0)
    ring = L.densify(L.ring_xy(p.exterior), 2.0)
    L.wall(cx.M, ring, z0, z1, mat, both=True)


def core(cx, poly, z0, h, frac=0.35, mat="concrete"):
    """rooftop machine room / core box centred on the footprint."""
    import shapely
    c = poly.centroid
    b = shapely.affinity.scale(poly, frac, frac, origin=c)
    _P().prism(cx.M, b, z0 - 0.5, z0 + h, mat, "roof_grey", parapet=0.0)


# ----------------------------------------------------------------------------------------------------- landmark builders
def b_lct(h, fracs, curved=False):
    """SOM / Samoo Y-plan towers (photos: lct/*): three wings, flat or (landmark) gently curved crown, wings ending at
    different heights; silver-blue glass, lighter vertical stripe at the wing tips."""
    def f(cx):
        p = cx.foot(cx.spec["foot"][0])
        pieces, _ = wings(p, 3)
        for piece, fr in zip(pieces, fracs):
            ht = h * fr
            if curved:
                c = p.centroid
                Rm = max(math.hypot(x - c.x, y - c.y) for x, y in p.exterior.coords)
                top = (lambda ht_: (lambda x, y: ht_ - 9.0 * (np.hypot(x - c.x, y - c.y) / Rm) ** 2))(ht)
            else:
                top = ht
            tower(cx, piece, ht, "lct_glass", parapet=2.0, top=top)
        core(cx, p, min(h * fr for fr in fracs), 6.0, frac=0.25)
    return f


def b_zenith(h, fl):
    """DeStefano + Partners X-plan towers (photos: zenith/*, crop of Marine_City__Busan.jpg): four petal wings stepping down
    at the crown, glass screen above the roof, blue glass with light slab lines."""
    def f(cx):
        p = cx.foot(cx.spec["foot"][0])
        pieces, _ = wings(p, 4)
        fr = [1.0, 0.975, 0.95, 0.975]
        for piece, k in zip(pieces, fr):
            tower(cx, piece, h * k - 7.0, "zenith_glass", parapet=0.8)
            screen(cx, piece, h * k - 7.5, h * k, "zenith_glass")            # glass crown fins (lit at night)
        core(cx, p, h * 0.95 - 7.0, 5.0, frac=0.3)
    return f


def b_ipark(h, low=0.8):
    """Studio Libeskind sail towers (photos: ipark/*, Marine_City__Busan.jpg): fan plan, crown edge rising in a concave
    curve to a sharp tip at the narrow end; deep blue glass with a fine light grid."""
    def f(cx):
        p = cx.foot(cx.spec["foot"][0])
        ax, c = principal(p)
        L = _P()
        r = L.densify(L.ring_xy(p.exterior), 0.5)
        s = (r - c) @ ax
        s0, s1 = s.min(), s.max()
        import shapely
        # tip = the narrower end (less area in its last 20 %)
        def end_area(lo, hi):
            band = shapely.Polygon([tuple(c + ax * lo + np.array([-ax[1], ax[0]]) * 500), tuple(c + ax * hi + np.array([-ax[1], ax[0]]) * 500),
                                    tuple(c + ax * hi - np.array([-ax[1], ax[0]]) * 500), tuple(c + ax * lo - np.array([-ax[1], ax[0]]) * 500)])
            return p.intersection(band).area
        sgn = 1.0 if end_area(s1 - 0.2 * (s1 - s0), s1) < end_area(s0, s0 + 0.2 * (s1 - s0)) else -1.0

        def top(x, y):
            t = ((np.column_stack((x, y)) - c) @ ax - s0) / (s1 - s0)
            t = t if sgn > 0 else 1.0 - t
            t = np.clip(t, 0, 1)
            return h * (low + (1 - low) * t ** 2.2)
        L.prism(cx.M, p, 0.0, top, "ipark_glass", "ipark_glass", parapet=0.0, roof_cell=3.0)
    return f


def b_hyatt(h):
    """Park Hyatt Busan (Studio Libeskind, photos: parkhyatt/*, marine crop): diagrid white lines over dark glass."""
    def f(cx):
        p = cx.foot(cx.spec["foot"][0])
        tower(cx, p, h, "hyatt_diag", parapet=1.5)
    return f


def b_bifc(cx):
    """BIFC (289 m, 63 F; OSM way 498976943 footprint - the GIS one is a 327 m2 sliver): square-ish plan, tilted crown
    plane (est. 6 % of the height across the diagonal), light blue glass with strong white mullions; BIFC mall podium."""
    p = cx.foot("way:498976943")
    h = 289.0
    ax, c = principal(p)
    r = np.asarray(p.exterior.coords)
    d = np.array([1.0, 1.0]) / math.sqrt(2)
    s = (r[:, :2] - c) @ d
    s0, s1 = s.min(), s.max()
    top = lambda x, y: h - 14.0 * (1 - (((np.column_stack((x, y)) - c) @ d - s0) / (s1 - s0)))
    tower(cx, p, h, "bifc_glass", parapet=3.0, top=top)
    try:
        pm = cx.foot("way:499064197")                          # BIFC mall (est. 24 m - no published height)
        tower(cx, pm.difference(p.buffer(0.5)), 24.0, "glass_curtain", parapet=1.0)
    except AssertionError:
        pass


def b_lotte_seomyeon(cx):
    """Lotte Hotel Busan + Lotte Department Store (one GIS footprint extruded to 171.66 m by the GIS rule): department
    store podium (est. 52 m, 13 F) + hotel slab tower to 171.66 m (43 F, GIS A16) in the west half - tower outline
    read off the local V-World photo (roof with helipad), est. +- 10 m."""
    import shapely
    p = cx.foot(cx.spec["foot"][0])
    x0, y0 = cx.ll(35.1568, 129.0560)                           # ortho crop centre the box was read from
    t = shapely.box(x0 - 76, y0 - 38, x0 + 4, y0 + 8).intersection(p)
    tower(cx, p.difference(t.buffer(0.3)), 52.0, "hotel_stone", parapet=1.5)
    tower(cx, t, 171.66 - 6, "hotel_stone", parapet=2.0)
    core(cx, t, 171.66 - 6, 6.0, frac=0.45)


def b_busantower(cx):
    """Diamond Tower (ex-Busan Tower, 1973, renewed 2021; 120 m, OSM way 480601129; observation deck modelled on the
    Dabotap pagoda - great-towers.com): white tapering shaft, two-tier glass deck with pagoda-like roofs, mast."""
    L = _P()
    p = cx.foot("way:480601129")
    c = p.centroid
    r0 = max(4.0, math.sqrt(p.area / math.pi) * 0.5)
    L.lathe(cx.M, [(r0 * 3.2, 0), (r0 * 3.2, 7), (r0 * 1.2, 7.5), (r0 * 1.0, 8)], "white_panel", cx=c.x, cy=c.y)     # base pavilion
    L.lathe(cx.M, [(4.2, 7), (3.4, 78), (3.4, 82), (8.5, 86)], "tower_white", cx=c.x, cy=c.y)
    L.lathe(cx.M, [(8.5, 86), (8.5, 92)], "glass_dark", cx=c.x, cy=c.y, segs=8)
    L.lathe(cx.M, [(8.5, 92), (10.5, 93.5), (7.0, 95)], "tower_white", cx=c.x, cy=c.y, segs=8)
    L.lathe(cx.M, [(7.0, 95), (7.0, 100)], "glass_dark", cx=c.x, cy=c.y, segs=8)
    L.lathe(cx.M, [(7.0, 100), (8.6, 101.5), (3.0, 105), (1.6, 108)], "tower_white", cx=c.x, cy=c.y, segs=8)
    L.lathe(cx.M, [(0.6, 108), (0.25, 120), (0.0, 120.1)], "white_panel", cx=c.x, cy=c.y, segs=8)


def b_cinema(cx):
    """Busan Cinema Center (Coop Himmelb(l)au 2011). The GIS 'Cinemountain' footprint (17,890 m2) is the whole site outline
    under the roofs, so the parts come from OSM: Cinemountain (way 569696778, glass block, GIS height 43.2 m / 9 F),
    BIFF Hill (way 569696779, GIS 16.8 m), Big Roof (way 569696783: 163 x 60 m, 85 m cantilever - Wikipedia / Trimble) on the
    Double Cone (way 569696781), Small Roof (relation 8112573) over Cinemountain. Roof heights est.: Big Roof underside
    38 -> 42 m towards the cantilever tip, 4 m thick, lit underside; Small Roof 44-47 m."""
    L = _P()
    import shapely
    try:
        cm = cx.foot("way:569696778")
    except AssertionError:
        cm = cx.foot("gis:2011211519501857697800000000")
    tower(cx, cm, 43.2, "glass_dark", parapet=0.5)
    try:
        bh = cx.foot("way:569696779")
    except AssertionError:
        bh = cx.foot("gis:2011211560151857586300000000")
    tower(cx, bh.difference(cm.buffer(0.5)), 16.8, "white_panel", parapet=0.8)
    big = shapely.geometry.polygon.orient(cx.foot("way:569696783"), 1.0)
    dc = cx.foot("way:569696781")
    cc = dc.centroid
    ax, c = principal(big)
    sgn = 1.0 if (np.array([cc.x, cc.y]) - c) @ ax < 0 else -1.0          # cantilever tip = away from the cone
    under = lambda x, y: 40.0 + 2.0 * sgn * np.clip(((np.column_stack((x, y)) - c) @ ax) / 80.0, -1, 1)
    L.cap(cx.M, big, under, "led_under", up=False, cell=6.0)
    L.cap(cx.M, big, lambda x, y: under(x, y) + 4.0, "metal_roof", up=True, cell=6.0)
    ring = L.densify(L.ring_xy(big.exterior), 3.0)
    zz = under(ring[:, 0], ring[:, 1])
    L.wall(cx.M, ring, zz, zz + 4.0, "white_panel")
    try:
        sm = shapely.geometry.polygon.orient(cx.foot("relation:8112573"), 1.0)
        L.cap(cx.M, sm, 44.0, "led_under", up=False)
        L.cap(cx.M, sm, 47.0, "metal_roof", up=True)
        L.wall(cx.M, L.densify(L.ring_xy(sm.exterior), 3.0), 44.0, 47.0, "white_panel")
    except AssertionError:
        pass
    R = math.sqrt(dc.area / math.pi)
    prof = [(R, 0), (R * 0.75, 6), (R * 0.42, 15), (R * 0.75, 28), (R * 1.25, 38)]
    L.lathe(cx.M, prof, "glass_curtain", cx=cc.x, cy=cc.y, segs=40)


def b_bexco(cx):
    """BEXCO Exhibition Center 1 (GIS 52 m incl. the entrance, 7 F; OSM roof:shape=skillion): long hall with a roof
    sloping across the short side (est. 28 -> 38 m), glass walls, light roof (BEXCO aerial photos, bexco/*)."""
    L = _P()
    p = cx.foot(cx.spec["foot"][0])
    ax, c = principal(p)
    nrm = np.array([-ax[1], ax[0]])
    r = np.asarray(p.exterior.coords)[:, :2]
    s = (r - c) @ nrm
    s0, s1 = s.min(), s.max()
    top = lambda x, y: 28.0 + 10.0 * ((np.column_stack((x, y)) - c) @ nrm - s0) / (s1 - s0)
    L.prism(cx.M, p, 0.0, top, "glass_curtain", "white_panel", parapet=0.0, roof_cell=10.0)     # aerial photos: light roofs


def b_station(cx):
    """Busan Station (2004, GIS 31.85 m, 5 F): glass hall under a curved metal roof (vault across the short side)."""
    L = _P()
    p = cx.foot(cx.spec["foot"][0])
    ax, c = principal(p)
    nrm = np.array([-ax[1], ax[0]])
    r = np.asarray(p.exterior.coords)[:, :2]
    half = np.abs((r - c) @ nrm).max()
    top = lambda x, y: 22.0 + 9.85 * (1 - np.clip(((np.column_stack((x, y)) - c) @ nrm / half) ** 2, 0, 1))
    L.prism(cx.M, p, 0.0, top, "glass_curtain", "metal_roof", parapet=0.0, roof_cell=6.0)


def b_stadium(cx, outer, inner, z_in, z_out, seats, roof=None, roof_frac=None):
    L = _P()
    L.bowl(cx.M, outer, inner, z_in, z_out, seats, rows=5)
    L.wall(cx.M, outer, 0.0, z_out + 1.0, "concrete")
    L.wall(cx.M, inner[::-1], 0.0, z_in, "concrete")                        # field wall (faces the field)


def b_sajik(cx):
    """Sajik Baseball Stadium (1985; NOT in the GIS data - outline digitised from the local V-World photo, est. +-5 m):
    open bowl, stands rising to ~26 m (est.), roof canopy over the upper stands behind home plate (south), 6 light towers."""
    L = _P()
    import shapely
    p = cx.foot(cx.spec["foot"][0])
    c = p.centroid
    outer = radial(p, 96)
    inner = c.x + (outer[:, 0] - c.x) * 0.66, c.y + (outer[:, 1] - c.y) * 0.64
    inner = np.column_stack(inner)
    b_stadium(cx, outer, inner, 2.5, 26.0, "stands")
    # canopy over the southern half (home plate side)
    ang = np.arctan2(outer[:, 1] - c.y, outer[:, 0] - c.x)
    sel = np.flatnonzero(np.sin(ang) < -0.25)
    o = outer[sel]
    i = c.x + (o[:, 0] - c.x) * 0.84, c.y + (o[:, 1] - c.y) * 0.84
    i = np.column_stack(i)
    can = shapely.Polygon(np.concatenate((o, i[::-1])))
    if can.is_valid and can.area > 0:
        L.cap(cx.M, can, 30.0, "roof_dark", up=True)
        L.cap(cx.M, can, 29.2, "roof_dark", up=False)
    for t in np.radians([20, 90, 160, 200, 270, 340]):
        k = int(np.argmin(np.abs((ang - t + math.pi) % (2 * math.pi) - math.pi)))
        L.lathe(cx.M, [(1.2, 0), (0.8, 46), (0.0, 46.1)], "concrete", cx=outer[k, 0], cy=outer[k, 1], segs=6)
        L.prism(cx.M, shapely.box(outer[k, 0] - 4, outer[k, 1] - 0.6, outer[k, 0] + 4, outer[k, 1] + 0.6), 44.0, 48.0, "white_panel", "roof_grey", parapet=0.0)


def b_asiad(cx):
    """Busan Asiad Main Stadium (2001): cable-dome membrane ring roof on 48 masts, total height 56.4 m (GIS A16 of the mast
    record and ktriptips.com), scalloped eaves (the GIS ring = the roof outline). Stands rising to ~28 m (est.)."""
    L = _P()
    import shapely
    ring = cx.foot("gis:1971387406421898148400000000", simplify=0.0)
    c = ring.centroid
    outer = radial(ring, 144, True, c)
    hole = radial(ring, 144, False, c) if len(ring.interiors) else c.x + (outer - [c.x, c.y]) * 0.55
    field = np.column_stack((c.x + (hole[:, 0] - c.x) * 0.80, c.y + (hole[:, 1] - c.y) * 0.80))
    st_out = np.column_stack((c.x + (outer[:, 0] - c.x) * 0.93, c.y + (outer[:, 1] - c.y) * 0.93))
    b_stadium(cx, st_out, field, 2.0, 27.0, "stands_orange")
    # membrane: outer eave z 34 -> inner edge z 42, double sided, on the real (scalloped) outline
    rp = shapely.geometry.polygon.orient(ring, 1.0)
    R_out = np.hypot(outer[:, 0] - c.x, outer[:, 1] - c.y).mean()
    R_in = np.hypot(hole[:, 0] - c.x, hole[:, 1] - c.y).mean()
    zf = lambda x, y: 34.0 + 8.0 * np.clip((R_out - np.hypot(x - c.x, y - c.y)) / max(R_out - R_in, 1), 0, 1)
    L.cap(cx.M, rp, zf, "membrane", up=True, cell=8.0)
    # 48 masts on the outer edge, tops at 56.4 m
    for t in np.linspace(0, 2 * math.pi, 48, endpoint=False):
        k = int(round(t / (2 * math.pi) * len(outer))) % len(outer)
        x, y = c.x + (outer[k, 0] - c.x) * 0.97, c.y + (outer[k, 1] - c.y) * 0.97
        L.lathe(cx.M, [(1.0, 0), (0.7, 56.4), (0.0, 56.5)], "white_panel", cx=x, cy=y, segs=6)


def b_nurimaru(cx):
    """Nurimaru APEC House (2005, GIS 24.6 m, 3 F): glass walls under a big overhanging roof shaped after a traditional
    pavilion (jeongja) - roof rises from the eaves (est. 10 m) to 24.6 m, dark grey."""
    L = _P()
    import shapely
    p = cx.foot(cx.spec["foot"][0])
    L.prism(cx.M, p.buffer(-2.0), 0.0, 10.0, "glass_curtain", "roof_grey", parapet=0.0)
    roof = shapely.geometry.polygon.orient(p.buffer(3.0), 1.0)
    D = max(roof.exterior.distance(shapely.Point(x, y)) for x, y in roof.buffer(-1).exterior.coords) if False else None
    c = roof.centroid
    pts = np.asarray(roof.exterior.coords)[:, :2]
    Rm = np.hypot(pts[:, 0] - c.x, pts[:, 1] - c.y).max()
    zf = lambda x, y: 9.5 + 15.1 * (1 - np.clip(np.hypot(x - c.x, y - c.y) / Rm, 0, 1)) ** 0.6
    L.cap(cx.M, roof, zf, "roof_dark", up=True, cell=4.0)
    L.cap(cx.M, roof, 9.5, "roof_dark", up=False)


def b_terminal(h_wall, h_top, mat="glass_curtain", wave=0.0, rise=(0.0, 0.0), roof_mat="metal_roof"):
    """airport / ferry terminal: glass walls, vaulted (or waved) roof with 3 m eaves, ends optionally swept up
    (rise = metres at the -axis / +axis end). Heights est."""
    def f(cx):
        L = _P()
        import shapely
        p = cx.foot(cx.spec["foot"][0], simplify=1.0)
        ax, c = principal(p)
        nrm = np.array([-ax[1], ax[0]])
        r = np.asarray(p.exterior.coords)[:, :2]
        half = np.abs((r - c) @ nrm).max() + 3.0

        def top(x, y):
            q = np.column_stack((x, y)) - c
            z = h_wall + (h_top - h_wall) * (1 - np.clip((q @ nrm / half) ** 2, 0, 1))
            if wave:
                z = z + wave * np.sin(q @ ax / 45.0 * math.pi)
            if rise[0] or rise[1]:
                sa = q @ ax
                smax = np.abs(np.asarray(p.exterior.coords)[:, :2] - c) @ np.abs(ax)
                t = np.clip(sa / max(smax.max(), 1.0), -1, 1)
                z = z + np.where(t > 0, rise[1], rise[0]) * np.abs(t) ** 4
            return z
        L.prism(cx.M, p, 0.0, h_wall, mat, "roof_grey", parapet=0.0)
        rf = shapely.geometry.polygon.orient(p.buffer(3.0, join_style=2), 1.0)
        L.cap(cx.M, rf, top, roof_mat, up=True, cell=8.0)
        L.cap(cx.M, rf, lambda x, y: top(x, y) - 1.2, "white_panel", up=False, cell=10.0)
        ring = L.densify(L.ring_xy(rf.exterior), 4.0)
        zt = top(ring[:, 0], ring[:, 1])
        L.wall(cx.M, ring, zt - 1.2, zt, "white_panel")
    return f


# ------------------------------------------------------------------------------------- helpers for spread-out structures
_DEM = {}


def ground_rel(cx, lat, lon):
    """rendered-terrain height (MSL) at lat / lon minus the model's base (the rule landmarks_build.build uses: lowest
    level-13 mesh point on the footprint ring / centroid - 0.3 m + base_dz), so pieces far from the footprint (crane rows,
    cable car pylons, masts) stand on their own ground."""
    import buildings_build as BB, terrain_dem as T
    if "dem" not in _DEM:
        _DEM["dem"] = T.Dem()
    dem = _DEM["dem"]
    if _DEM.get("key") != id(cx):
        L = _P()
        fl = cx.local(cx.foot5186)
        ring = L.densify(L.ring_xy(fl.exterior), 8.0)
        la, lo = cx.to_ll(ring[:, 0], ring[:, 1])
        cla, clo = cx.origin
        _DEM["base"] = float(BB.mesh_height(dem, np.append(la, cla), np.append(lo, clo)).min()) - 0.3 + cx.spec.get("base_dz", 0.0)
        _DEM["key"] = id(cx)
    return float(BB.mesh_height(dem, np.array([lat]), np.array([lon]))[0]) - _DEM["base"]


def beam(cx, a, b, w, mat, d=None):
    """straight member of w x w (or w x d) section between 3D points a, b (local metres), capped ends."""
    a, b = np.asarray(a, float), np.asarray(b, float)
    ax = b - a
    L = np.linalg.norm(ax)
    if L < 1e-6:
        return
    ax /= L
    up = np.array([0.0, 0.0, 1.0]) if abs(ax[2]) < 0.9 else np.array([1.0, 0.0, 0.0])
    u = np.cross(ax, up)
    u /= np.linalg.norm(u)
    v = np.cross(u, ax)
    hu, hv = w / 2, (d if d else w) / 2
    cs = [(-hu, -hv), (hu, -hv), (hu, hv), (-hu, hv)]
    P, N, UV, I = [], [], [], []
    k = 0
    for i in range(4):
        (p0, q0), (p1, q1) = cs[i], cs[(i + 1) % 4]
        o0, o1 = u * p0 + v * q0, u * p1 + v * q1
        n = o0 + o1
        n = n / np.linalg.norm(n)
        P += [a + o0, a + o1, b + o1, b + o0]
        N += [n] * 4
        UV += [(0, 0), (w, 0), (w, L), (0, L)]
        I += [k, k + 1, k + 2, k, k + 2, k + 3]
        k += 4
    for e, s_ in ((a, -1.0), (b, 1.0)):                               # end caps
        P += [e + u * p + v * q for p, q in cs]
        N += [ax * s_] * 4
        UV += [(0, 0), (w, 0), (w, w), (0, w)]
        I += [k, k + 1, k + 2, k, k + 2, k + 3]
        k += 4
    P, N, I = np.asarray(P), np.asarray(N), np.asarray(I).reshape(-1, 3)
    t = P[I]
    fn = np.cross(t[:, 1] - t[:, 0], t[:, 2] - t[:, 0])               # wind every triangle with its normal
    flip = np.sum(fn * N[I[:, 0]], axis=1) < 0
    I[flip] = I[flip][:, ::-1]
    cx.M.tris(mat, P, N, UV, I)


def lattice(cx, x, y, z0, legs, mat, bands=None, dz=6.0):
    """square steel lattice tower: legs = [(z, half width), ...] bottom to top; X bracing on each face every ~dz m;
    bands = (material, panels per band) for warning paint."""
    prof = np.asarray(legs, float)
    zs = np.arange(prof[0, 0], prof[-1, 0] + 1e-6, dz)
    if zs[-1] < prof[-1, 0]:
        zs = np.append(zs, prof[-1, 0])
    hw = np.interp(zs, prof[:, 0], prof[:, 1])
    C = [(1, 1), (-1, 1), (-1, -1), (1, -1)]
    pt = lambda i, c: (x + C[c][0] * hw[i], y + C[c][1] * hw[i], z0 + zs[i])
    for i in range(len(zs) - 1):
        m = mat if not bands or (i // bands[1]) % 2 == 0 else bands[0]
        lw = max(0.35, hw[i] * 0.09)
        for c in range(4):
            beam(cx, pt(i, c), pt(i + 1, c), lw, m)
            beam(cx, pt(i, c), pt(i + 1, (c + 1) % 4), lw * 0.45, m)
            beam(cx, pt(i + 1, c), pt(i, (c + 1) % 4), lw * 0.45, m)
            beam(cx, pt(i + 1, c), pt(i + 1, (c + 1) % 4), lw * 0.5, m)


# ------------------------------------------------------------------------------------- 2026-11-10 districts (builders)
def b_cranes(cranes, sea):
    """ship-to-shore container cranes on a quay. Positions = crane bodies digitised from the local V-World photo
    (sinseondae / gamman crops 2026-11-10, +-10 m), boom up / down as in that photo; colour from the photos
    (Sinseondae: red with white machinery houses, cranes/Sinseondae_Day.png; Gamman: orange / white, V-World photo). Size 추정 for the older
    North Port A-frame cranes (no published per-crane data; newstomato: cab 35-50 m above the quay): rail gauge 30 m,
    legs 18 m apart along the quay, girder at 42-46 m, outreach 50 m, backreach 22 m, A-frame apex 72 m, boom up 80 deg."""
    def f(cx):
        sv = np.asarray(sea, float)
        sv /= np.linalg.norm(sv)
        al = np.array([-sv[1], sv[0]])                                 # along the quay
        G, S, ZG, OUT, BACK, APEX = 30.0, 18.0, 42.0, 50.0, 22.0, 72.0
        for la, lo, down, col in cranes:
            mat = dict(o="steel_orange", r="steel_red").get(col, "steel_white")
            x, y = cx.ll(la, lo)
            z0 = ground_rel(cx, la, lo)
            p = np.array([x, y])
            for s_ in (-0.5, 0.5):
                a, b = p + al * S * s_, p + al * S * s_ - sv * G
                for q in (a, b):                                        # sea leg, land leg
                    beam(cx, (q[0], q[1], z0 - 0.5), (q[0], q[1], z0 + ZG), 2.2, mat)
                beam(cx, (a[0], a[1], z0 + 12), (b[0], b[1], z0 + 12), 1.8, mat)            # portal tie beams
                beam(cx, (a[0], a[1], z0 + ZG), (b[0], b[1], z0 + ZG), 2.5, mat)
                g0 = p + al * S * s_ * 0.55 - sv * (G + BACK)                               # girder: back end -> sea legs
                ga = p + al * S * s_ * 0.55
                beam(cx, (g0[0], g0[1], z0 + ZG + 2), (ga[0], ga[1], z0 + ZG + 2), 2.6, mat, d=3.5)
                if down:
                    tip = ga + sv * OUT
                    beam(cx, (ga[0], ga[1], z0 + ZG + 2), (tip[0], tip[1], z0 + ZG + 2), 2.4, mat, d=3.0)
                    tz = (tip[0], tip[1], z0 + ZG + 3.5)
                else:
                    ang = math.radians(80.0)
                    tip = ga + sv * OUT * math.cos(ang)
                    tz = (tip[0], tip[1], z0 + ZG + 2 + OUT * math.sin(ang))
                    beam(cx, (ga[0], ga[1], z0 + ZG + 2), tz, 2.2, mat, d=2.6)
                ap = p + al * S * s_ * 0.45 - sv * 6.0                                       # A-frame + stays
                apz = (ap[0], ap[1], z0 + APEX)
                beam(cx, (a[0], a[1], z0 + ZG + 2), apz, 1.4, mat)
                beam(cx, (b[0], b[1], z0 + ZG + 2), apz, 1.4, mat)
                beam(cx, apz, tz, 0.5, mat)
                beam(cx, apz, (g0[0], g0[1], z0 + ZG + 3), 0.5, mat)
            mh = p - sv * (G + BACK * 0.55)                                                  # machinery house
            beam(cx, (mh[0] - al[0] * 5.5, mh[1] - al[1] * 5.5, z0 + ZG + 5), (mh[0] + al[0] * 5.5, mh[1] + al[1] * 5.5, z0 + ZG + 5), 12.0,
                 "steel_white" if col == "r" else mat, d=6.0)
    return f


def b_hwangnyeong(cx):
    """Hwangnyeongsan (427 m) broadcast towers at the OSM mast nodes 4735801755 (KBS / MBC) and 4735801754 (KNN): square
    steel lattice towers of ~100 m (namu.wiki/w/황령산 '약 100 m' -> 추정), KBS / MBC painted red / white, KNN grey (photo
    hwangnyeong/Tr_st_hwangnyeongsan.jpg); leg spread and antenna section 추정 from that photo."""
    for (la, lo), bands in (((35.15793, 129.08194), ("steel_red", 2)), ((35.15877, 129.08314), None)):
        x, y = cx.ll(la, lo)
        z0 = ground_rel(cx, la, lo) - 1.0
        mat = "steel_white" if bands else "steel_grey"
        lattice(cx, x, y, z0, [(0, 7.0), (40, 3.6), (72, 1.6), (80, 1.2)], mat, bands=bands)
        beam(cx, (x, y, z0 + 80), (x, y, z0 + 100), 1.0, bands[0] if bands else mat)
        for zz in (40.0, 72.0):                                        # platforms
            beam(cx, (x - 4.5, y, z0 + zz), (x + 4.5, y, z0 + zz), 9.0, "steel_grey", d=0.6)


def b_songdo_cable(cx):
    """Songdo Marine Cable Car 'Busan Air Cruise' (2017, 1.62 km, namu.wiki/w/송도해상케이블카): OSM gondola way
    667458143; pylons = OSM nodes 8892624276 / 8892624275 / 8892624277, stations = OSM 5209159366 (Songdo Bay) and
    5209159295 (Sky Park). Sea pylon 86 m (segye.com/newsView/20170705002888 '바다에 세워진 높이 86 철탑'); land pylons
    40 m, station boxes and rope heights 추정. Two ropes 7 m apart, sag 4 % of the span, a few cabins."""
    import shapely
    L = _P()
    pts = [((35.07633, 129.02354), "station", 14.0), ((35.07369, 129.02301), "pylon", 40.0), ((35.06827, 129.02189), "pylon", 86.0),
           ((35.06188, 129.02051), "pylon", 40.0), ((35.06153, 129.02044), "station", 12.0)]
    P = []
    for (la, lo), kind, h in pts:
        x, y = cx.ll(la, lo)
        P.append((x, y, ground_rel(cx, la, lo), kind, h))
    d = np.array([P[-1][0] - P[0][0], P[-1][1] - P[0][1]])
    d /= np.linalg.norm(d)
    n = np.array([-d[1], d[0]])
    tops = []
    for x, y, z0, kind, h in P:
        if kind == "pylon":
            big = h > 60
            L.lathe(cx.M, [(4.5 if big else 2.6, z0 - 2), (3.0 if big else 1.8, z0 + h * 0.6), (1.8 if big else 1.3, z0 + h)], "steel_white", cx=x, cy=y, segs=12)
            beam(cx, (x - n[0] * 6, y - n[1] * 6, z0 + h), (x + n[0] * 6, y + n[1] * 6, z0 + h), 2.0, "steel_white", d=1.6)
            tops.append(z0 + h - 1.0)
        else:
            box = shapely.Polygon([tuple(np.array([x, y]) + d * a + n * b) for a, b in ((-14, -10), (14, -10), (14, 10), (-14, 10))])
            L.prism(cx.M, box, z0 - 1, z0 + h, "glass_curtain", "roof_grey", parapet=0.8)
            tops.append(z0 + h - 3.0)
    rng = np.random.default_rng(7)
    cols = ["steel_red", "steel_white", "steel_orange"]
    for side in (-3.5, 3.5):
        for i in range(len(P) - 1):
            a = np.array([P[i][0], P[i][1]]) + n * side
            b = np.array([P[i + 1][0], P[i + 1][1]]) + n * side
            span = float(np.linalg.norm(b - a))
            zt = lambda t: tops[i] + (tops[i + 1] - tops[i]) * t - 0.04 * span * 4 * t * (1 - t)
            k = max(2, int(span / 25))
            prev = None
            for t in np.linspace(0, 1, k + 1):
                q = a + (b - a) * t
                if prev is not None:
                    beam(cx, prev, (q[0], q[1], zt(t)), 0.45, "cable")
                prev = (q[0], q[1], zt(t))
            for t in ((0.3, 0.7) if span > 200 else ()):              # cabins under the rope
                t = t + rng.uniform(-0.08, 0.08)
                q = a + (b - a) * t
                z = zt(t)
                beam(cx, (q[0], q[1], z - 0.3), (q[0], q[1], z - 3.6), 0.2, "cable")
                beam(cx, (q[0] - d[0] * 1.3, q[1] - d[1] * 1.3, z - 5.0), (q[0] + d[0] * 1.3, q[1] + d[1] * 1.3, z - 5.0), 2.4,
                     cols[int(rng.integers(3))], d=2.4)


def b_jagalchi(cx):
    """Jagalchi Market (2006; GIS A16 40.8 m / 7 F = the roof tip): glass hall under white 'seagull wing' roof shells
    (photos jagalchi/Jagalchi_Market_20200523_014.jpg / _015): the footprint narrows to the west and the roof rises from
    the east end to a pointed tip over the west end. Wall height 22 m and the roof curve 추정 from the photos."""
    import shapely
    L = _P()
    p = cx.foot(cx.spec["foot"][0])
    ax, c = principal(p)
    nrm = np.array([-ax[1], ax[0]])
    r = np.asarray(p.exterior.coords)[:, :2]
    s = (r - c) @ ax
    s0, s1 = s.min(), s.max()

    def band(lo, hi):
        return p.intersection(shapely.Polygon([tuple(c + ax * lo + nrm * 300), tuple(c + ax * hi + nrm * 300),
                                               tuple(c + ax * hi - nrm * 300), tuple(c + ax * lo - nrm * 300)])).area
    sg = 1.0 if band(s1 - 0.2 * (s1 - s0), s1) < band(s0, s0 + 0.2 * (s1 - s0)) else -1.0     # +1: tip at the +axis end

    def tt(x, y):
        q = (np.column_stack((x, y)) - c) @ ax
        t = (q - s0) / (s1 - s0)
        return np.clip(t if sg > 0 else 1 - t, 0, 1)
    L.prism(cx.M, p.buffer(-1.5), 0.0, 22.0, "glass_curtain", "roof_grey", parapet=0.0)
    roof = shapely.geometry.polygon.orient(p.buffer(2.5), 1.0)
    zf = lambda x, y: 25.0 + 15.8 * tt(x, y) ** 2.2
    L.cap(cx.M, roof, zf, "white_panel", up=True, cell=5.0)
    L.cap(cx.M, roof, lambda x, y: zf(x, y) - 1.0, "white_panel", up=False, cell=5.0)
    ring = L.densify(L.ring_xy(roof.exterior), 3.0)
    z = zf(ring[:, 0], ring[:, 1])
    L.wall(cx.M, ring, z - 1.0, z, "white_panel")
    mid = p.buffer(-7.0)                                               # lower inner wing shell (the overlapping 'feathers')
    if not mid.is_empty and mid.geom_type == "Polygon":
        z2 = lambda x, y: 22.5 + 9.0 * np.sin(np.pi * tt(x, y)) ** 1.5
        L.cap(cx.M, shapely.geometry.polygon.orient(mid, 1.0), z2, "white_panel", up=True, cell=5.0)


def b_lotte_gwangbok(cx):
    """Lotte Department Store Gwangbok + Lotte Mall (Aqua Mall), 2009 / 2010: one OSM outline (way 243769199, 12 levels).
    The GIS file has only the department-store half, with A16 8.0 m against 11 floors (data error; the tiles drew it at
    33 m from the floors) and no mall. Dept store 11 F, mall 13 F (ko.wikipedia 부산롯데타워) -> 50 / 58 m 추정 (4.4 m
    retail floors). Silver drum = dept store (lotte_gwangbok/Busan_Lotte_Department_Store.jpg), white block = the mall
    (Lotte_Mall_Busan_Gwangbok_Store.jpg). The Lotte Tower beside it is under construction (core ~13 F in 2026-03, news1):
    not modelled."""
    L = _P()
    p = cx.foot("way:243769199")
    north = None
    try:
        g = cx.foot("gis:2010203270951776816300000000")
        north = p.intersection(g.buffer(4.0))
        north = max(getattr(north, "geoms", [north]), key=lambda q: q.area)
    except AssertionError:
        pass
    if north is not None and north.area > 1000:
        south = p.difference(north.buffer(0.5))
        south = max(getattr(south, "geoms", [south]), key=lambda q: q.area)
        L.prism(cx.M, north, 0.0, 50.0, "silver_panel", "roof_grey", parapet=1.5)
        L.prism(cx.M, south, 0.0, 58.0, "white_panel", "roof_grey", parapet=1.5)
    else:
        L.prism(cx.M, p, 0.0, 54.0, "white_panel", "roof_grey", parapet=1.5)


# -------------------------------------------------------------------------------------------------------------- the list
W = "https://en.wikipedia.org/wiki/"
SPECS = [
    dict(key="lct_landmark", name="LCT The Sharp Landmark Tower", site=(35.1599, 129.1697), foot=["gis:2019215407021845410100000000"],
         build=b_lct(411.6, (1.0, 0.95, 0.86), curved=True), refs=[W + "Haeundae_LCT_The_Sharp"], h_src="GIS A16 411.6 m / 101 F; Wikipedia 411.6 m"),
    dict(key="lct_a", name="LCT The Sharp Residential A", site=(35.1613, 129.1680), foot=["gis:2019215247841846945500000000"],
         build=b_lct(339.1, (1.0, 0.97, 0.94)), refs=[W + "Haeundae_LCT_The_Sharp"], h_src="GIS A16 339.1 m / 85 F; Wikipedia 339.1 m"),
    dict(key="lct_b", name="LCT The Sharp Residential B", site=(35.1608, 129.1689), foot=["gis:2019215330321846338100000000"],
         build=b_lct(333.1, (1.0, 0.97, 0.94)), refs=[W + "Haeundae_LCT_The_Sharp"], h_src="GIS A16 333.1 m / 85 F; Wikipedia 333 m"),
    dict(key="zenith_101", name="Doosan We've the Zenith 101", site=(35.1568, 129.1460), foot=["gis:2011213248961841972300000000"],
         build=b_zenith(299.9, 80), refs=[W + "Doosan_Haeundae_We%27ve_the_Zenith"], h_src="GIS A16 299.9 m / 80 F; Wikipedia 300 m"),
    dict(key="zenith_102", name="Doosan We've the Zenith 102", site=(35.1572, 129.1448), foot=["gis:2011213138331842357100000000"],
         build=b_zenith(283.9, 75), refs=[W + "Doosan_Haeundae_We%27ve_the_Zenith"], h_src="GIS A16 283.9 m / 75 F; Wikipedia 281.5 m"),
    dict(key="zenith_103", name="Doosan We've the Zenith 103", site=(35.1561, 129.1453), foot=["gis:2011213179691841090400000000"],
         build=b_zenith(267.9, 70), refs=[W + "Doosan_Haeundae_We%27ve_the_Zenith"], h_src="GIS A16 267.9 m / 70 F; Wikipedia 265 m"),
    dict(key="ipark_t1", name="Haeundae I'Park Marina Tower 1", site=(35.1571, 129.1426), foot=["gis:2011212931271842194500000000"],
         build=b_ipark(273.5), refs=["https://www.skyscrapercenter.com/building/haeundae-i-park-marina-tower-1/8755"], h_src="GIS A16 273.5 m / 66 F"),
    dict(key="ipark_t2", name="Haeundae I'Park Marina Tower 2", site=(35.1560, 129.1420), foot=["gis:2011212884791841071000000000"],
         build=b_ipark(292.7), refs=["https://www.skyscrapercenter.com/busan/haeundae-i-park-marina-tower-2/8754/"], h_src="GIS A16 292.7 m / 72 F"),
    dict(key="ipark_t3", name="Haeundae I'Park Marina Tower 3", site=(35.1552, 129.1424), foot=["gis:2011212916141840141400000000"],
         build=b_ipark(206.3, low=0.84), refs=["https://www.skyscrapercenter.com/"], h_src="GIS A16 206.3 m / 46 F"),
    dict(key="park_hyatt", name="Park Hyatt Busan", site=(35.1566, 129.1418), foot=["gis:2012212865241841651700000000"],
         build=b_hyatt(169.8), refs=[], h_src="GIS A16 169.8 m / 34 F; OSM height 170"),
    dict(key="bifc", name="Busan International Finance Center", site=(35.1461, 129.0664), foot=["way:498976943"],
         exclude=["2014205999771830786900000000"], build=b_bifc, refs=[W + "Busan_International_Finance_Center"],
         h_src="Wikipedia 289 m / 63 F; OSM height 289 (GIS footprint wrong: 327 m2 sliver)"),
    dict(key="lotte_seomyeon", name="Lotte Hotel Busan / Lotte Dept. Store Seomyeon", site=(35.1568, 129.0560), foot=["gis:1997205047581841785600000000"],
         build=b_lotte_seomyeon, refs=[], h_src="GIS A16 171.66 m / 42 F (tower); podium 52 m est."),
    dict(key="busan_tower", name="Diamond Tower (Busan Tower)", site=(35.1007, 129.0324), site_r=150, foot=["way:480601129"],
         build=b_busantower, refs=[W + "Busan_Tower", "https://www.great-towers.com/tower/busan-tower"], h_src="OSM height 120 / Wikipedia 120 m; deck tiers est."),
    dict(key="cinema_center", name="Busan Cinema Center", site=(35.1710, 129.1272), site_r=200,
         foot=["gis:2011211519501857697800000000", "gis:2011211560151857586300000000", "way:569696783"],
         build=b_cinema, refs=[W + "Busan_Cinema_Center", "https://www.trimble.com/blog/construction/en-US/article/busan-cinema-center-has-the-longest-cantilever-roof-in-the-world"],
         h_src="GIS 43.2 / 16.8 m; Big Roof 163 x 60 m, 85 m cantilever (Wikipedia); roof heights est."),
    dict(key="bexco", name="BEXCO Exhibition Center 1", site=(35.1690, 129.1359), foot=["gis:2006212321231855469800000000"],
         build=b_bexco, refs=[W + "BEXCO"], h_src="GIS A16 52 m / 7 F; roof slope est."),
    dict(key="busan_station", name="Busan Station", site=(35.1164, 129.0429), foot=["gis:2004203855821797008300000000"],
         build=b_station, refs=[W + "Busan_station"], h_src="GIS A16 31.85 m / 5 F"),
    dict(key="sajik_baseball", name="Sajik Baseball Stadium", site=(35.1942, 129.0615), site_r=200,
         foot=["ellipse:35.19418,129.06152,97,112,0"], build=b_sajik, refs=[W + "Sajik_Baseball_Stadium"],
         h_src="not in GIS; outline digitised from V-World photo; stand / roof / light-tower heights est."),
    dict(key="asiad_stadium", name="Busan Asiad Main Stadium", site=(35.1902, 129.0588), site_r=250,
         foot=["gis:1971387406421898148400000000"], exclude=["2001387451621898263800000000"], build=b_asiad,
         refs=[W + "Busan_Asiad_Main_Stadium", "https://www.ktriptips.com/eng/leisure/1955161"], h_src="56.4 m total (ktriptips, = GIS A16 of the mast record); 48 masts"),
    dict(key="nurimaru", name="Nurimaru APEC House", site=(35.1523, 129.1514), site_r=150, foot=["gis:2005213733621836967400000000"],
         build=b_nurimaru, refs=[W + "Nurimaru_APEC_House"], h_src="GIS A16 24.6 m / 3 F; eave height est."),
    dict(key="gimhae_intl", name="Gimhae Intl. Airport International Terminal", site=(35.1735, 128.9480), site_r=700, foot=["relation:4450292"],
         build=b_terminal(15.0, 22.0), refs=[W + "Gimhae_International_Airport"], h_src="not in GIS (airfield); OSM outline; heights est."),
    dict(key="gimhae_dom", name="Gimhae Intl. Airport Domestic Terminal", site=(35.1735, 128.9480), site_r=700, foot=["relation:4450291"],
         build=b_terminal(16.0, 24.0), refs=[W + "Gimhae_International_Airport"], h_src="not in GIS (airfield); OSM outline; heights est."),
    dict(key="ferry_terminal", name="Busan Port International Passenger Terminal", site=(35.1180, 129.0480), site_r=500, foot=["way:368597686"],
         build=b_terminal(22.0, 30.0, mat="glass_curtain", rise=(6.0, 18.0), roof_mat="white_panel"), refs=["https://www.busanpa.com/bpt/Contents.do?mCode=MN0006"], h_src="not in GIS; OSM outline (levels -1..5); heights est."),
    # ---- 2026-11-10: districts outside Haeundae (survey and sources on the compare page; GIS gaps -> osm_fill.py)
    dict(key="cranes_gamman", name="Gamman / Shin-Gamman container cranes", site=(35.1045, 129.0800), site_r=50, foot=["ellipse:35.10450,129.08000,4,4,0"],
         build=lambda cx: (b_cranes([(35.1039, 129.078597, 1, 'o'), (35.1039, 129.079698, 1, 'o'), (35.1039, 129.080211, 1, 'w'), (35.1039, 129.081924, 0, 'o'), (35.1039, 129.082229, 0, 'w'), (35.1039, 129.085128, 0, 'o'), (35.1039, 129.085409, 0, 'o'), (35.1039, 129.08651, 0, 'w'), (35.1039, 129.087366, 1, 'w'), (35.1039, 129.089238, 0, 'w'), (35.1039, 129.09002, 0, 'w')], (0.0, -1.0))(cx),
                           b_cranes([(35.107674, 129.068686, 1, 'w'), (35.107246, 129.069395, 0, 'w'), (35.106176, 129.071301, 0, 'w'), (35.105125, 129.072907, 0, 'w'), (35.104495, 129.074028, 1, 'w'), (35.104342, 129.07429, 0, 'w')], (-0.59, -0.81))(cx)),
         refs=["https://www.busan.go.kr/eng/north-port"], h_src="17 cranes digitised from the V-World photo (busan.go.kr: Gamman 9 + Shin-Gamman / 1B 13 STS); size 추정"),
    dict(key="cranes_sinseondae", name="Sinseondae container cranes", site=(35.1005, 129.0950), site_r=50, foot=["ellipse:35.10050,129.09480,4,4,0"],
         build=b_cranes([(35.106556, 129.09409, 1, 'r'), (35.10596, 129.094215, 1, 'r'), (35.105095, 129.094278, 1, 'r'), (35.104005, 129.094303, 1, 'r'), (35.103552, 129.094341, 1, 'r'), (35.102595, 129.094467, 1, 'r'), (35.102235, 129.094505, 1, 'r'), (35.101567, 129.094593, 1, 'r'), (35.100743, 129.094656, 1, 'r'), (35.100301, 129.094718, 1, 'r'), (35.099169, 129.094806, 1, 'r'), (35.0985, 129.094882, 1, 'r'), (35.096576, 129.095159, 1, 'r'), (35.096288, 129.095259, 1, 'r'), (35.095908, 129.095309, 1, 'r'), (35.095342, 129.095385, 1, 'r'), (35.094519, 129.095473, 1, 'r')], (-0.996, -0.094)),
         refs=["https://www.busan.go.kr/eng/north-port"], h_src="17 cranes digitised from the V-World photo (= busan.go.kr: Sinseondae 17 STS); size 추정"),
    dict(key="hwangnyeong_masts", name="Hwangnyeongsan broadcast towers (KBS/MBC, KNN)", site=(35.1584, 129.0826), site_r=150,
         foot=["ellipse:35.15835,129.08255,4,4,0"], build=b_hwangnyeong, refs=["https://namu.wiki/w/%ED%99%A9%EB%A0%B9%EC%82%B0"],
         h_src="namu.wiki: two towers ~100 m (추정); positions = OSM mast nodes"),
    dict(key="songdo_cable", name="Songdo Marine Cable Car (Busan Air Cruise)", site=(35.0690, 129.0220), site_r=100,
         foot=["ellipse:35.06900,129.02200,4,4,0"], build=b_songdo_cable,
         refs=["https://www.segye.com/newsView/20170705002888", "https://namu.wiki/w/%EC%86%A1%EB%8F%84%ED%95%B4%EC%83%81%EC%BC%80%EC%9D%B4%EB%B8%94%EC%B9%B4"],
         h_src="sea pylon 86 m (Segye 2017-07-05); land pylons 40 m, stations 추정; OSM gondola / pylon / station nodes"),
    dict(key="jagalchi", name="Jagalchi Market", site=(35.0966, 129.0306), site_r=150, foot=["gis:2006202732561775066100000000"],
         build=b_jagalchi, refs=["https://www.busannavi.net/en/?p=210"], h_src="GIS A16 40.8 m / 7 F (roof tip); wall 22 m and roof curve 추정"),
    dict(key="lotte_gwangbok", name="Lotte Dept. Store Gwangbok + Lotte Mall", site=(35.0975, 129.0365), site_r=200, foot=["way:243769199"],
         build=b_lotte_gwangbok, refs=["https://ko.wikipedia.org/wiki/%EB%B6%80%EC%82%B0%EB%A1%AF%EB%8D%B0%ED%83%80%EC%9B%8C"],
         h_src="11 F / 13 F (ko.wikipedia); 50 / 58 m 추정; GIS A16 8.0 m is wrong and the mall half is missing in GIS"),
]
for s in SPECS:
    s.setdefault("method", "parametric (footprint + published height + reference photos)")
