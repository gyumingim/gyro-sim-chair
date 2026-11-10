#!/usr/bin/env python3
"""make_sounds.py - our own synthesized loops for the cockpit sound (no recordings, no third-party audio):
  Art/Sounds/engine_loop.wav   jet engine heard through the canopy: low roar (filtered noise) + turbine whine
                               (a few drifting partials) + slight rumble, 6 s seamless loop
  Art/Sounds/wind_loop.wav     airflow over the canopy: band-passed noise with slow gusting, 6 s seamless loop
Pitch / volume follow throttle and airspeed at run time (Content/Python/view_fx.py). 22.05 kHz mono 16 bit.
Run: python Scripts/aircraft/make_sounds.py   (numpy, scipy)
"""
import wave
from pathlib import Path

import numpy as np
from scipy.signal import butter, sosfiltfilt

SR, DUR = 22050, 6.0
OUT = Path(__file__).resolve().parents[2] / "Art" / "Sounds"


def band(x, lo, hi):
    sos = butter(2, [lo, hi], btype="band", fs=SR, output="sos") if lo else butter(2, hi, btype="low", fs=SR, output="sos")
    return sosfiltfilt(sos, x)


def loop(x, fade=0.5):
    """seamless loop: the tail cross-faded into the head (equal power)."""
    n = int(fade * SR)
    head, body, tail = x[:n], x[n:-n] if n else x, x[-n:]
    t = np.linspace(0, np.pi / 2, n)
    mixed = tail * np.cos(t) + head * np.sin(t)
    return np.concatenate([mixed, x[n:-n]])


def save(name, x, peak=0.6):
    x = x / (np.abs(x).max() + 1e-9) * peak
    OUT.mkdir(parents=True, exist_ok=True)
    with wave.open(str(OUT / name), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(SR)
        w.writeframes((x * 32767).astype("<i2").tobytes())
    print(name, len(x) / SR, "s")


def main():
    rng = np.random.default_rng(11)
    n = int((DUR + 0.5) * SR)
    t = np.arange(n) / SR
    white = rng.normal(0, 1, n)
    roar = band(white, 0, 380) * 1.0 + band(white, 380, 1400) * 0.35
    rumble = band(rng.normal(0, 1, n), 0, 60) * 1.6
    whine = np.zeros(n)
    for f, a in ((1180.0, 0.10), (2360.0, 0.05), (3540.0, 0.025), (590.0, 0.04)):
        drift = 1.0 + 0.004 * np.sin(2 * np.pi * 0.21 * t + rng.random() * 6)
        whine += a * np.sin(2 * np.pi * f * np.cumsum(drift) / SR)
    eng = roar * 0.55 + rumble * 0.25 + whine * 3.0 * np.std(roar)
    save("engine_loop.wav", loop(eng))
    gust = 0.65 + 0.35 * band(rng.normal(0, 1, n), 0, 0.6) / 0.05
    gust = np.clip(gust, 0.3, 1.2)
    w = band(rng.normal(0, 1, n), 180, 1800) * 0.8 + band(rng.normal(0, 1, n), 1800, 5000) * 0.25
    save("wind_loop.wav", loop(w * gust))


if __name__ == "__main__":
    main()
