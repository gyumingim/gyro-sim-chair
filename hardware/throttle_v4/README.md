# Throttle v4 (simple) + toe brakes v4

Own build123d scripts only. No third-party model files are in this repository.

- `throttle_v4.py` -> `stl/*.stl`, `parts.json` (BOM with prices (estimate), button map, strength, interference check)
- `../pedals/brakes_v4.py` -> `../pedals/stl_brakes_v4/*.stl` + `parts.json`
- Page: `docs/throttle_v4.html`

## Based on (attribution)

The layout ideas (single long-travel lever, F-16-like grip with comms hat, dogfight slide/toggle, speedbrake 3-position
switch, MTS-103 / MTS-123 mini toggles, FreeJoy/MMJoy wiring) come from:

- "F-16 Viper Throttle" by **Spock** — https://www.printables.com/model/552322 (also Thingiverse thing:4733645).
  Licence: **Creative Commons Attribution-NonCommercial (CC BY-NC)** (read from the Printables public API, 2026-11-06).
- Its grip is based on the **Hempstick Project** F-16 throttle grip model —
  http://www.seedling.org/The_Official_Hempstick_Site/F16_Throttle.html (licence not stated on the pages we found).
- FreeJoy firmware docs (AS5600 analog mode, 74HC165 shift registers) — https://github.com/FreeJoy-Team/FreeJoyWiki

**The grip itself is the public Spock grip** — download and print it from the link above (CC BY-NC: no commercial
use, give credit). It is NOT in this repository. Our `grip_adapter` (in `throttle_v4.py`, our own shape) sits on our lever
top and carries the grip's mount: a 44.4 mm thick tongue clamped by the grip's front/rear arms with one 1/4" (M6) bolt,
leaning 26 deg aft as in Spock's assembly. Only these interface numbers were measured from the public STEP (downloaded
without login to a folder outside this repo); the adapter was checked against that STEP: no overlap with any grip part.
The bolt hole position is measured (about +-2 mm, estimate); drill it through together with the grip if needed.
