# Chair v8.4 frame (Fusion export)

`chair_v8_4_frame.step` — the chair frame exported on 2026-11-12 from the Fusion document
"자이로 의자 v8.3 (웹에서) 복구" (base frame, roll ring, pitch cage, lock pins; mm, x forward, y left, z up,
origin = where the roll and pitch axes cross).

Left out on purpose:
- stick / throttle / pedals sub-assemblies (our own parts live in `hardware/stick_v4`, `throttle_v4`, `pedals`);
  the F-16 / Viper grip is CC BY-NC-SA and is never committed (see `hardware/stick_v4/README.md`);
- the bucket seat mesh (Printables 1180590, public domain; a mesh, not exportable to STEP).

The web model (`index.html`, PARTS table) is older (v8.3, 2026-11-05) — this STEP is newer.

## Changes since v8.3 (2026-11-12)
Fasteners
- Every PLA part that bolts to 4040: M8 -> **M3** (hole 3.4) + **3x12 fender washer** in the old 14.5 / 16 head pockets, M3 T-nuts (slot 8).
  The washer keeps the PLA bearing area close to an M8 head.
- Kept as before (PLA-to-PLA joints with hidden nuts): roll arc segment joints **M8**, brace splices M5, stick plate M6.

Base braces (PLA, 4 legs)
- Foot: short stub past the leg removed; outer end follows the leg's top face down to the profile; 2 x M3 (M3x20) on the slope.
- Top at the post: pad follows the leg's top face up to the post (one flat face, no step); 2 x M3 moved to z -566 / -588.

Locks
- Yaw spare bolt plate (300x300x10) removed; roll lock ears stand on the 4040 with a foot flange + rib, M3 into the top slot.
- Pitch lock: the red lock blocks are gone. A 12 mm pin goes straight through the ring side bar and the cage side rail
  (13 mm cross holes) at x -300. Ring side bars cut back to end at x 182 (962 mm instead of 1190 mm).

Pitch weight drive (both sides, modelled)
- PLA carriage on 4 x 608ZZ rollers (on the rail top, beside the slot) + 2 POM T-sliders in the top slot (anti-tip).
- HTD 5M belt loop inside each side rail; PLA belt clamp on the carriage.
- Front: PLA U-bracket + idler pulley on an M8 axle, M6 tension bolt from an end plate.
- Back: PLA U-bracket with 2 x KFL001 flange bearings on the 12 mm drive shaft; one worm motor drives both sides.
- New 4040 cross member (840 mm) under the side-rail back ends, PLA motor plate on top.
- Stroke is limited to -523 / +615 mm (the back end cannot move back: the ring back bar is at r = 780 mm from the
  pitch axis). Pitch weights raised 16.5 -> **19 kg** (+1.25 kg plate per side) so 523 mm still gives 15 deg (estimate).

Other
- VR headset hook removed.

## 4040 cost check (estimate)
29 cut pieces, 23.5 m (before this revision's side-bar cut and the new cross member):
yjprofile tiered cut price ~481,000 won vs kiprofile 23,100 won/m + 10 % ~597,000 won. Shipping and tapping not included.
