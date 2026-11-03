"""WGS84 geodesy shared by sim_client.py (runtime) and Scripts/build_level.py (level build). No unreal import.

Unreal world frame of this project: X = north, Y = east, Z = up (cm), origin = (lat0, lon0) at ellipsoid height h0.
It is the exact local tangent (ENU) frame at the origin, so the Earth curves away from Z = 0 (about 0.8 m at 3 km,
196 m at 50 km) - the same frame Cesium for Unreal uses (Cesium: X east, Y south, Z up), turned by yaw +90 deg on the
Cesium tileset actor. JSBSim altitude h (above its ellipsoid "sea level") is shown at ellipsoid height h + geoid_n.
"""
import math

A, E2 = 6378137.0, 6.69437999014e-3


def ecef(lat, lon, h):
    la, lo = math.radians(lat), math.radians(lon)
    sl, cl, so, co = math.sin(la), math.cos(la), math.sin(lo), math.cos(lo)
    n = A / math.sqrt(1 - E2 * sl * sl)
    return ((n + h) * cl * co, (n + h) * cl * so, (n * (1 - E2) + h) * sl)


def enu_axes(lat, lon):
    """unit east, north, up vectors (ECEF) at lat/lon."""
    la, lo = math.radians(lat), math.radians(lon)
    sl, cl, so, co = math.sin(la), math.cos(la), math.sin(lo), math.cos(lo)
    return (-so, co, 0.0), (-sl * co, -sl * so, cl), (cl * co, cl * so, sl)


def _dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


class Frame:
    """origin (lat0, lon0, h0 ellipsoid m) -> Unreal world cm (X north, Y east, Z up)."""
    def __init__(self, lat0, lon0, h0):
        self.lat0, self.lon0, self.h0 = lat0, lon0, h0
        self.o = ecef(lat0, lon0, h0)
        self.e, self.n, self.u = enu_axes(lat0, lon0)
        self._rot_key = None

    def world(self, lat, lon, h):
        p = ecef(lat, lon, h)
        d = (p[0] - self.o[0], p[1] - self.o[1], p[2] - self.o[2])
        return _dot(d, self.n) * 100.0, _dot(d, self.e) * 100.0, _dot(d, self.u) * 100.0

    def vec(self, v_ecef):
        """ECEF direction -> world (X north, Y east, Z up) direction."""
        return _dot(v_ecef, self.n), _dot(v_ecef, self.e), _dot(v_ecef, self.u)

    def body_axes(self, lat, lon, phi, theta, psi):
        """forward, right, up unit vectors (world frame) of a body with NED Euler angles (deg) at lat/lon - includes
        the tilt of the local level at (lat, lon) against the origin's level (0.45 deg per 50 km)."""
        p, t, s = (math.radians(a) for a in (phi, theta, psi))
        cp, sp, ct, st, cs, ss = math.cos(p), math.sin(p), math.cos(t), math.sin(t), math.cos(s), math.sin(s)
        f_ned = (ct * cs, ct * ss, -st)
        r_ned = (sp * st * cs - cp * ss, sp * st * ss + cp * cs, sp * ct)
        d_ned = (cp * st * cs + sp * ss, cp * st * ss - sp * cs, cp * ct)
        key = (round(lat, 4), round(lon, 4))
        if key != self._rot_key:
            self._rot_key = key
            self._enu = enu_axes(lat, lon)
        e, n, u = self._enu

        def to_world(v_ned):                       # local NED -> ECEF -> origin world frame
            ve = tuple(v_ned[1] * e[i] + v_ned[0] * n[i] - v_ned[2] * u[i] for i in range(3))
            return self.vec(ve)
        f, r, d = to_world(f_ned), to_world(r_ned), to_world(d_ned)
        return f, r, (-d[0], -d[1], -d[2])


def euler_from_axes(f, u):
    """UE rotator angles (roll, pitch, yaw deg) of a body with forward f and up u (world X north, Y east, Z up,
    UE left-handed: roll = right wing down positive, same as NED phi)."""
    yaw = math.degrees(math.atan2(f[1], f[0]))
    pitch = math.degrees(math.asin(max(-1.0, min(1.0, f[2]))))
    # roll: angle of the body up vector around f, measured from the 'no roll' up vector
    cy, sy = math.cos(math.radians(yaw)), math.sin(math.radians(yaw))
    cpi, spi = math.cos(math.radians(pitch)), math.sin(math.radians(pitch))
    up0 = (-spi * cy, -spi * sy, cpi)               # up with zero roll
    right0 = (-sy, cy, 0.0)                         # right with zero roll (UE: +Y when yaw 0)
    roll = math.degrees(math.atan2(_dot(u, right0), _dot(u, up0)))
    return roll, pitch, yaw
