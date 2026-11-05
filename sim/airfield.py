"""The real airfields the sim can start at - shared by server.py (JSBSim), terrain_dem / terrain_build (DEM flattening)
and the Unreal client / level builder.

Selected start (module names FIELD_FT, RWY, LAT0 ... below): `python sim/server.py --start rkpk`, or the environment
variable GYROSIM_START=rkpk (server.py sets it from --start before anything imports this module). Default RKTU.

Cheongju Air Base / Cheongju Int'l Airport (RKTU), runway 06R/24L.
  Field elevation 191 ft (58 m) AMSL - OurAirports RKTU (davidmegginson.github.io/ourairports-data) and
    https://en.wikipedia.org/wiki/Cheongju_International_Airport
  Runways from OpenStreetMap (Overpass, aeroway=runway):
    06R/24L 45 m wide: 06R end 36.7078737N 127.4874876E, 24L end 36.7229393N 127.5117932E -> 2738 m, true heading 052.38
    06L/24R 60 m wide: 06L end 36.7100557N 127.4868159E, 24R end 36.7251153N 127.5111227E -> 2738 m, true heading 052.39
  Geoid height (EGM2008) at RKTU = +25.08 m (https://geographiclib.sourceforge.io/cgi-bin/GeoidEval?input=36.7154+127.4996).

Gimhae Int'l Airport, Busan (RKPK, joint use with the ROK Air Force 5th Air Mobility Wing), runway 36L/18R (start).
  Aerodrome elevation 6 ft (1.8 m) - OurAirports airports.csv RKPK (davidmegginson.github.io/ourairports-data/airports.csv)
  Runways - OpenStreetMap ways 25555901 / 25371187 (source tag "MoLIT AIS"), checked 2026-11-05 via Overpass, lengths from
  OurAirports runways.csv / OSM length tags (3200 m and 2743 m = the AIP lengths):
    36L/18R 60 m wide: 36L end 35.1651944N 128.9388227E, true heading 353.96, 3200 m
      (OurAirports 36L 35.165199N 128.938995E = 16 m east of OSM; OSM used - finer digits, MoLIT source)
    36R/18L 46 m wide: 36R end 35.1694676N 128.9405906E, 18L end 35.1940559N 128.9374224E -> 2743 m, true heading 353.97
  Geoid height (EGM2008) at the RKPK ARP 35.1795N 128.9380E = +29.17 m (GeographicLib GeoidEval, same URL with that input).
  V-World hides the whole base under fake fields (checked on the cached z19 tiles) -> the runways are our own meshes.

Cesium terrain / 3D tiles heights are ellipsoidal; JSBSim's "sea level" is the WGS84 ellipsoid, so the Unreal client
shows JSBSim altitude h at ellipsoid height h + GEOID_N (= the real AMSL height).
"""
import math
import os

M_LAT = 110950.0                          # m per degree latitude (Korea)


def _m_lon(lat):
    return 111320.0 * math.cos(math.radians(lat))


# flat: the DEM flattened to field_ft in runway axes of rwy (x = m past its threshold, y = m right of its centre line),
# core box then a cosine blend (terrain_dem.BLEND_M). tower: fixed camera point (tower view), not the real tower.
AIRFIELDS = {
    "rktu": dict(id="rktu", icao="RKTU", name="Cheongju", field_ft=191.0, geoid_n=25.08,
                 rwy=dict(name="06R", lat=36.7078737, lon=127.4874876, hdg=52.38, len_m=2738.0, w_m=45.0),
                 rwy2=dict(name="06L", lat=36.7100557, lon=127.4868159, hdg=52.39, len_m=2738.0, w_m=60.0),
                 ends=(("06R", "24L"), ("06L", "24R")), taxi_links=True,
                 flat_x=(-500.0, 3250.0), flat_y=(-480.0, 260.0), tower=(36.7190, 127.4962), air_hdg=0.0),
    "rkpk": dict(id="rkpk", icao="RKPK", name="Gimhae (Busan)", field_ft=6.0, geoid_n=29.17,
                 rwy=dict(name="36L", lat=35.1651944, lon=128.9388227, hdg=353.96, len_m=3200.0, w_m=60.0),
                 rwy2=dict(name="36R", lat=35.1694676, lon=128.9405906, hdg=353.97, len_m=2743.0, w_m=46.0),
                 ends=(("36L", "18R"), ("36R", "18L")), taxi_links=False,
                 flat_x=(-500.0, 3700.0), flat_y=(-200.0, 400.0), tower=(35.1760, 128.9300), air_hdg=95.0),
}
DEFAULT = "rktu"


def selected():
    k = os.environ.get("GYROSIM_START", "").strip().lower() or DEFAULT
    if k not in AIRFIELDS:
        raise SystemExit("unknown start airfield %r (known: %s)" % (k, ", ".join(AIRFIELDS)))
    return k


def rwy_point(along, cross=0.0, rwy=None):
    """lat/lon of a point `along` m past the threshold on the centre line (+cross = right of the centre line), m."""
    rwy = rwy or RWY
    h = math.radians(rwy["hdg"])
    n = along * math.cos(h) - cross * math.sin(h)
    e = along * math.sin(h) + cross * math.cos(h)
    return rwy["lat"] + n / M_LAT, rwy["lon"] + e / _m_lon(rwy["lat"])


START_ALONG = 150.0                       # sim start / Unreal world origin: 150 m down the start runway


def origin(apt):
    """(lat0, lon0) of an airfield = the sim start point / its Unreal world origin."""
    return rwy_point(START_ALONG, 0.0, AIRFIELDS[apt]["rwy"])


def runway_lines(apt):
    """[(lat1, lon1, lat2, lon2), ...] threshold to far end of every runway (MFD map)."""
    a = AIRFIELDS[apt]
    out = []
    for r in (a["rwy"], a["rwy2"]):
        p = rwy_point(r["len_m"], 0.0, r)
        out.append((r["lat"], r["lon"], p[0], p[1]))
    return out


APT = selected()
AF = AIRFIELDS[APT]
FIELD_FT = AF["field_ft"]
FIELD_M = FIELD_FT * 0.3048
GEOID_N = AF["geoid_n"]
RWY = AF["rwy"]
RWY2 = AF["rwy2"]
M_LON = _m_lon(RWY["lat"])
LAT0, LON0 = origin(APT)
