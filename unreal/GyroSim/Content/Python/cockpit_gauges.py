"""Standby instrument scales of the GyroSim cockpit - shared by the dial texture generator
(Scripts/cockpit/make_textures.py) and the live needles in sim_client.py, so the printed scale and the needle agree.

Angles are degrees clockwise from 12 o'clock, as seen by the pilot.
"""
import math

ASI_MAX, ASI_SWEEP = 800.0, 320.0          # knots, 0 at 12 o'clock
VSI_MAX, VSI_SWEEP, VSI_K = 6000.0, 165.0, 1800.0   # ft/min, 0 at 9 o'clock, compressed scale
ALT_REV = 1000.0                            # ft per turn of the long needle (short needle: 10 000 ft per turn)
ADI_PITCH_DEG_PER_DEG = 1.0                 # ball: true pitch angles (lines every 5 deg)


def asi_deg(kts):
    return ASI_SWEEP * max(0.0, min(ASI_MAX, kts)) / ASI_MAX


def alt_deg(ft):
    return 360.0 * (ft % ALT_REV) / ALT_REV


def alt10k_deg(ft):
    return 360.0 * (ft % 10000.0) / 10000.0


def vsi_deg(fpm):
    v = max(-VSI_MAX, min(VSI_MAX, fpm))
    f = (1.0 - math.exp(-abs(v) / VSI_K)) / (1.0 - math.exp(-VSI_MAX / VSI_K))
    return -90.0 + math.copysign(VSI_SWEEP * f, v)
