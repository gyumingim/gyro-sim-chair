r"""Tall Busan buildings that the 국토교통부 GIS건물통합정보 file (AL_D010_26_20261009) does not have, taken from OpenStreetMap
and fed to sim/buildings_build.py as one more work file, so they get the same tiles / facade look as the GIS blocks.

    python -I sim/landmarks/osm_fill.py --fetch     Overpass: Busan boundary + buildings >= 20 levels or >= 60 m tag (no account)
                                                    -> C:\GyroSimTiles\landmarks\work\osmfill\osm_tall.json
    python -I sim/landmarks/osm_fill.py --select    keep the ones with no rendered GIS block of >= 60 % of their height under
                                                    them (work/buildings_busan.npz), inside Busan, not on a landmark model's footprint
                                                    -> osmfill\osm_fill.shp (EPSG:5186, the GIS field names) + osmfill\select.json
    python -I sim/buildings_build.py --prep --shp C:\GyroSimTiles\landmarks\work\osmfill\osm_fill.shp --whole --name busan_osmfill
                                                    -> work\buildings_busan_osmfill.npz, picked up by every later --tiles

Found 2026-11-10: whole new tower blocks are missing from the GIS file (The W 4 x 246 m, Hillstate Ijin Bay City 247 m,
Marina G7 2 x 200 m, Eco Delta City, Myeongji ...) and the North Port redevelopment site still holds pre-demolition records.
Heights: OVERRIDE (published, with source) > OSM height > OSM building:levels (-> 1.5 + 2.9 m per floor, the GIS rule).
Field map: A0 = -way id, A1 = 'osm_w<id>' (uid, never a GIS A1), A8 use code from building=*, A16 height, A26 levels,
A24 name. OSM data (c) OpenStreetMap contributors, ODbL - data stays outside git.
"""
import json, os, re, sys, time, site
if sys.flags.isolated:
    site.addsitedir(site.getusersitepackages())
import numpy as np

ROOT = os.environ.get("GYROSIM_LANDMARKS", r"C:\GyroSimTiles\landmarks")
OUT = os.path.join(ROOT, "work", "osmfill")
RAW = os.path.join(OUT, "osm_tall.json")
SHP = os.path.join(OUT, "osm_fill.shp")
NPZ = os.path.join(os.environ.get("GYROSIM_BUILDINGS", r"C:\GyroSimTiles\buildings"), "work", "buildings_busan.npz")
EXCLUDE = os.path.join(ROOT, "exclude.json")
BBOX = (34.88, 128.75, 35.40, 129.32)
UA = "GyroSimLandmarks/0.1 (personal flight sim)"
W_ = "en.wikipedia.org/wiki/List_of_tallest_buildings_in_Busan"
NAMED = {  # OSM way id -> (height m, floors, source); published numbers beat the OSM tags
    783628293: (246.0, 69, "The W, 246 m / 69 F (" + W_ + ")"), 783628294: (246.0, 69, "The W, 246 m / 69 F (" + W_ + ")"),
    783628295: (246.0, 69, "The W, 246 m / 69 F (" + W_ + ")"), 783628296: (246.0, 69, "The W, 246 m / 69 F (" + W_ + ")"),
    1387271453: (247.0, 69, "Hillstate Ijin Bay City A, 247 m / 69 F (" + W_ + ")"),
    1387271451: (189.0, 59, "Hillstate Ijin Bay City B/C, 189 m / 59 F (" + W_ + ")"), 1387271452: (189.0, 59, "Hillstate Ijin Bay City B/C, 189 m / 59 F (" + W_ + ")"),
    987862339: (199.9, 61, "Marina G7, 199.9 m / 61 F (skyscrapercenter.com/building/marina-g7-building-a/39164)"),
    987862340: (199.9, 61, "Marina G7, 199.9 m / 61 F (skyscrapercenter.com/building/marina-g7-building-a/39164)"),
}
A8 = dict(apartments="02000", residential="02000", house="01000", commercial="14000", office="14000", retail="07000",
          hotel="15000", mixed_use="14000")


def overpass(q):
    import urllib.request, urllib.parse
    req = urllib.request.Request("https://overpass-api.de/api/interpreter", data=urllib.parse.urlencode(dict(data=q)).encode(),
                                 headers={"User-Agent": UA})
    return json.load(urllib.request.urlopen(req, timeout=300))


def fetch():
    os.makedirs(OUT, exist_ok=True)
    bb = "(%g,%g,%g,%g)" % BBOX
    q = ('[out:json][timeout:240];(way["building"]["building:levels"~"^([2-9][0-9]|1[0-9][0-9])$"]%s;'
         'way["building"]["height"~"^([6-9][0-9]|[1-4][0-9][0-9])(\\\\.[0-9]+)?$"]%s;);out tags geom;' % (bb, bb))
    d = overpass(q)
    b = overpass('[out:json][timeout:120];relation["boundary"="administrative"]["admin_level"="4"]["name"="부산광역시"];out geom;')
    d["boundary"] = b["elements"]
    d["fetched"], d["query"] = time.strftime("%Y-%m-%d %H:%M:%S"), q
    json.dump(d, open(RAW, "w", encoding="utf-8"), ensure_ascii=False)
    print("osm: %d ways, boundary %d -> %s" % (len(d["elements"]), len(b["elements"]), RAW))


def num(s):
    m = re.match(r"\s*([\d.]+)", s or "")
    return float(m.group(1)) if m else None


def select():
    import shapely, geopandas as gpd
    from pyproj import Transformer
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from landmarks_build import join_ways
    tf = Transformer.from_crs("EPSG:4326", "EPSG:5186", always_xy=True)
    d = json.load(open(RAW, encoding="utf-8"))
    # Busan boundary (outer rings of the admin relation)
    rings = join_ways([m["geometry"] for el in d["boundary"] for m in el.get("members", []) if m.get("role") == "outer" and m.get("geometry")])
    polys = []
    for r in rings:
        x, y = tf.transform([p["lon"] for p in r], [p["lat"] for p in r])
        if len(x) >= 4:
            polys.append(shapely.make_valid(shapely.Polygon(list(zip(x, y)))))
    busan = shapely.union_all(polys)
    assert busan.area > 5e8, ("Busan boundary looks wrong", busan.area)
    # rendered GIS blocks (work npz: rings in lon / lat, h)
    z = np.load(NPZ)
    lon, lat, nring, rop, H = z["lon"], z["lat"], z["nring"], z["ring_of_poly"], z["h"]
    first = np.concatenate(([True], np.diff(rop) != 0))                  # exterior ring of each polygon
    starts = np.concatenate(([0], np.cumsum(nring)[:-1]))
    X, Y = tf.transform(lon, lat)
    X, Y = np.asarray(X), np.asarray(Y)
    # landmark models stand on GIS footprints that the tiles skip (exclude.json): count them as covered (any height)
    lm = set(json.load(open(EXCLUDE, encoding="utf-8")).get("ids", [])) if os.path.isfile(EXCLUDE) else set()
    uid, SRC = z["uid"], z["src"]
    g, gh, gsrc = [], [], []
    for k in np.flatnonzero(first):
        s, n = starts[k], nring[k]
        if n >= 4:
            g.append(shapely.Polygon(np.c_[X[s:s + n], Y[s:s + n]]))
            gh.append(1e4 if uid[rop[k]] in lm else float(H[rop[k]]))
            gsrc.append(0 if uid[rop[k]] in lm else int(SRC[rop[k]]))
    g, gh, gsrc = np.asarray(g), np.asarray(gh), np.asarray(gsrc)
    tree = shapely.STRtree(g)
    print("gis: %d rendered footprints" % len(g), flush=True)
    from specs import SPECS                                       # OSM ways a landmark model is built on
    lm_ways = {int(f[4:]) for sp in SPECS for f in sp["foot"] if f.startswith("way:")}
    keep, rows, conflicts, dups = [], [], [], []
    for e in d["elements"]:
        if e["type"] != "way" or "geometry" not in e or e["id"] in lm_ways:
            continue
        t = e.get("tags", {})
        lv, h = num(t.get("building:levels")), num(t.get("height"))
        x, y = tf.transform([p["lon"] for p in e["geometry"]], [p["lat"] for p in e["geometry"]])
        if len(x) < 4:
            continue
        P = shapely.make_valid(shapely.Polygon(list(zip(x, y))))
        P = max(getattr(P, "geoms", [P]), key=lambda q: q.area) if P.geom_type != "Polygon" else P
        if P.area < 150 or not busan.contains(P.centroid):
            continue
        src = "osm height" if h else "osm levels"
        cla, clo = np.mean([p["lat"] for p in e["geometry"]]), np.mean([p["lon"] for p in e["geometry"]])
        if e["id"] in NAMED:
            h, lv, src = NAMED[e["id"]]
        Ho = h if h else 1.5 + 2.9 * lv
        if Ho < 60:
            continue
        # missing = no rendered GIS block with a real height (A16 / floors) on >= 30 % of it; blocks with only an area-default
        # height (no data, ~8-10 m) do not count. A GIS block with data at 35-60 % of the
        # OSM height = a conflict: listed, not added; lower ones are taken as stale records of what stood there before.
        hit = [i for i in tree.query(P) if gsrc[i] != 3]
        ov = [(g[i].intersection(P).area, gh[i]) for i in hit]
        if sum(a for a, hh in ov if hh >= 0.6 * Ho) >= 0.3 * P.area:
            continue
        if sum(a for a, hh in ov if hh >= 0.35 * Ho) >= 0.3 * P.area:          # lower ones = pre-redevelopment records
            conflicts.append(dict(id=e["id"], lat=round(cla, 6), lon=round(clo, 6), osm_h=Ho, gis_h=max(hh for a, hh in ov), name=t.get("name")))
            continue
        # offset duplicate (independent audit 11-10: ~75 OSM outlines sit 8-20 m off the GIS block of the same tower): a GIS
        # block with a real height within +-25 % of the OSM height, <= 15 m from the OSM outline, centroids <= 35 m apart
        near = [i for i in tree.query(P.buffer(15.0)) if gsrc[i] in (1, 2) and abs(gh[i] - Ho) <= 0.25 * Ho
                and g[i].centroid.distance(P.centroid) <= 35.0]
        if near:
            dups.append(dict(id=e["id"], lat=round(cla, 6), lon=round(clo, 6), osm_h=Ho, gis_h=float(gh[near[0]]), name=t.get("name")))
            continue
        keep.append(P)
        rows.append(dict(A0=-int(e["id"]), A1="osm_w%d" % e["id"], A8=A8.get(t.get("building"), "02000" if (lv or 0) >= 15 else ""),
                         A9=t.get("building", ""), A12=round(P.area, 1), A16=float(h or 0.0), A26=float(lv or 0.0), A27=0.0,
                         A24=(t.get("name") or "")[:60], osm_h=t.get("height", ""), h_src=src, lat=round(cla, 6), lon=round(clo, 6)))
    gdf = gpd.GeoDataFrame([{k: v for k, v in r.items() if k in ("A0", "A1", "A8", "A9", "A12", "A16", "A26", "A27", "A24")} for r in rows],
                           geometry=keep, crs="EPSG:5186")
    gdf.to_file(SHP, encoding="cp949", engine="pyogrio")
    hs = np.array([r["A16"] or 1.5 + 2.9 * r["A26"] for r in rows])
    json.dump(dict(made=time.strftime("%Y-%m-%d %H:%M:%S"), inputs=dict(osm=RAW, osm_fetched=d.get("fetched"), gis_npz=NPZ),
                   rule="OSM building >= 60 m (height tag, else 1.5 + 2.9 m x levels, i.e. >= 21 levels) inside Busan with < 30 %% of its area under rendered GIS blocks that have a height (A16 / floors); GIS blocks with data at 35-60 %% of the OSM height = conflicts, not added (lower = stale pre-redevelopment records)",
                   count=len(rows), height_m=dict(max=float(hs.max()), median=float(np.median(hs)), over_150=int((hs >= 150).sum())),
                   named=[r for r in rows if not r["h_src"].startswith("osm")], conflicts=conflicts, offset_duplicates=dups, buildings=rows),
              open(os.path.join(OUT, "select.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=0)
    print("select: %d OSM buildings missing from the GIS tiles (max %.0f m, %d >= 150 m) -> %s; %d height conflicts, %d offset duplicates (not added)" % (
        len(rows), hs.max(), (hs >= 150).sum(), SHP, len(conflicts), len(dups)))


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    a = sys.argv[1:]
    if "--fetch" in a:
        fetch()
    if "--select" in a:
        select()
    if not a:
        print(__doc__)
