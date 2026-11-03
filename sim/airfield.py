"""The real airfield the sim starts at - shared by server.py (JSBSim) and the Unreal client / level builder.

Cheongju Air Base / Cheongju Int'l Airport (RKTU), runway 06R/24L.
  Field elevation 191 ft (58 m) AMSL - OurAirports RKTU (davidmegginson.github.io/ourairports-data) and
    https://en.wikipedia.org/wiki/Cheongju_International_Airport
  Runways from OpenStreetMap (Overpass, aeroway=runway):
    06R/24L 45 m wide: 06R end 36.7078737N 127.4874876E, 24L end 36.7229393N 127.5117932E -> 2738 m, true heading 052.38
    06L/24R 60 m wide: 06L end 36.7100557N 127.4868159E, 24R end 36.7251153N 127.5111227E -> 2738 m, true heading 052.39
  Geoid height (EGM2008) at RKTU = +25.08 m (https://geographiclib.sourceforge.io/cgi-bin/GeoidEval?input=36.7154+127.4996).
    Cesium terrain / 3D tiles heights are ellipsoidal; JSBSim's "sea level" is the WGS84 ellipsoid, so the Unreal client
    shows JSBSim altitude h at ellipsoid height h + GEOID_N (= the real AMSL height).
JSBSim's ground is this constant field elevation everywhere (hills are not in the flight model).
"""
import math

FIELD_FT = 191.0
FIELD_M = FIELD_FT * 0.3048
GEOID_N = 25.08
RWY = dict(name="06R", lat=36.7078737, lon=127.4874876, hdg=52.38, len_m=2738.0, w_m=45.0)     # 06R threshold
RWY2 = dict(name="06L", lat=36.7100557, lon=127.4868159, hdg=52.39, len_m=2738.0, w_m=60.0)    # parallel runway
M_LAT, M_LON = 110950.0, 111320.0 * math.cos(math.radians(RWY["lat"]))                         # m per degree near RKTU
START_ALONG = 150.0                       # sim start / Unreal world origin: 150 m down runway 06R


def rwy_point(along, cross=0.0, rwy=RWY):
    """lat/lon of a point `along` m past the threshold on the centre line (+cross = right of the centre line), m."""
    h = math.radians(rwy["hdg"])
    n = along * math.cos(h) - cross * math.sin(h)
    e = along * math.sin(h) + cross * math.cos(h)
    return rwy["lat"] + n / M_LAT, rwy["lon"] + e / M_LON


LAT0, LON0 = rwy_point(START_ALONG)
