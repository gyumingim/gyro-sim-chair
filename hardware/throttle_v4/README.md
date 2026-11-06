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

We downloaded two grip STLs from the Spock model (no login, public API) to a folder outside this repo only to check the
size of a real-scale grip (about 145 x 65 x 115 mm). Our grip is a new, simplified shape drawn in `throttle_v4.py`;
no geometry was copied. If you want the detailed F-16 grip, download it from the link above and follow its CC BY-NC terms
(no commercial use, give credit).
