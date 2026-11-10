#!/usr/bin/env python3
"""airframe_split.py - the exterior of the GPL FlightGear F-16 (fetch_f16_model.py cache) split into a body and the
moving control surfaces, for the UE airframe pass (Scripts/aircraft/ue_airframe.py, sim_client / airframe_live.py).

Writes into ThirdParty/f16_airframe/ (outside git, GPL-2.0 derived like f16_obj/):
  F16_Body.obj           exterior minus the moving surfaces (same frame as F16_Exterior: UE body cm, OBJ = UE (X, Z, Y))
  F16_FlapL/R.obj        flaperons (roll + flaps)        - vertices relative to the hinge point
  F16_StabL/R.obj        all-moving horizontal tails     - "
  F16_LefL/R.obj         leading-edge flaps (alpha)      - "
  F16_Rudder.obj         rudder                          - "
  tex_*.png              textures used (copied / converted by fetch_f16_model.TexOut)
  airframe.json          per part: hinge point (UE cm), unit axis whose + rotation moves the trailing edge DOWN (flaps,
                         stabs, LEF) or to the RIGHT (rudder), triangle counts; nav-light / strobe / beacon points.
Hinge points and axes = the FlightGear model's own rotate animations (Models/F-16.xml), converted to UE.
Run: python Scripts/aircraft/airframe_split.py  (CPython 3.10+, numpy, Pillow; reads only the local f16_src cache)
"""
from __future__ import annotations

import json
import re
import shutil
import sys
import time
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import fetch_f16_model as F  # noqa: E402

OUT = F.THIRD / "f16_airframe"
F.OUT = OUT                                     # TexOut / write_obj write here

# FG model frame (m, x aft, y right, z up): center + axis of each rotate animation in Models/F-16.xml
SURF = {
    "F16_FlapL":  dict(objs=r"^Left(Upper|Lower)Flap$",  c=(1.54, -2.35, 0.12),  a=(0.150157, -0.987872, -0.039515), sense="down"),
    "F16_FlapR":  dict(objs=r"^Right(Upper|Lower)Flap$", c=(1.54, 2.35, 0.12),   a=(0.150157, 0.987872, -0.039515), sense="down"),
    "F16_StabL":  dict(objs=r"^Left(Upper|Lower)HorizonTail$",  c=(4.36, -1.965, -0.1), a=(0.0, -0.981645, -0.190720), sense="down"),
    "F16_StabR":  dict(objs=r"^Right(Upper|Lower)HorizonTail$", c=(4.36, 1.965, -0.1),  a=(0.0, 0.981645, -0.190720), sense="down"),
    "F16_LefL":   dict(objs=r"^Left(Upper|Lower)Lef$",   c=(0.24, -3.0, 0.035),  a=(0.549345, -0.834983, -0.031988), sense="down"),
    "F16_LefR":   dict(objs=r"^Right(Upper|Lower)Lef$",  c=(0.24, 3.0, 0.035),   a=(0.550908, 0.834232, -0.023610), sense="down"),
    "F16_Rudder": dict(objs=r"^Rudder(\.\d+)?$", c=(4.915, 0.0, 2.095), a=(0.547371, 0.0, 0.836890), sense="right"),
}
DROP = r"Logo|USAF|VstabBand"


def main():
    t0 = time.time()
    OUT.mkdir(parents=True, exist_ok=True)
    repo = F.Repo()
    texres = F.TexResolver(repo)
    loader = F.Loader(repo, texres, F.skip_model)
    root = loader.load("Models/F-16.xml", ())
    parts, dropped = F.collect(root)
    ext = parts["F16_Exterior"]
    new = {n: F.Part(n) for n in ["F16_Body"] + list(SURF)}
    for (n, mask), label in zip(ext.chunks, ext.objects):
        if re.search(DROP, n.name):                   # unit / national markings: no real livery on our aircraft
            dropped[label + " (airframe: marking)"] = len(n.T)
            continue
        decal = np.array([bool(F.MATKEYS[k][0]) and "f16trans" in F.MATKEYS[k][0] for k in n.MK], bool)
        mask = mask & ~decal                          # tail codes / unit band decals (f16trans.png)
        if not mask.any():
            continue
        tgt = next((k for k, s in SURF.items() if re.search(s["objs"], n.name)), "F16_Body")
        new[tgt].chunks.append((n, mask))
        new[tgt].objects.append(label)
    texout = F.TexOut(repo)
    info = dict(made=time.strftime("%Y-%m-%d %H:%M:%S"), script="Scripts/aircraft/airframe_split.py",
                source=dict(repo=F.REPO_URL, commit=F.SHA, license="GPL-2.0-or-later"), parts={})
    for nm, part in new.items():
        if not part.chunks:
            F.log(f"[warn] {nm}: no objects")
            continue
        arr = F.build_part_arrays(part)
        rec = dict(objects=sorted(set(part.objects)), triangles=int(len(arr["T"])))
        if nm in SURF:
            s = SURF[nm]
            c_ue = F.fg_to_ue(np.array(s["c"]))
            a_ue = F.fgdir_to_ue(np.array(s["a"]))
            a_ue = a_ue / np.linalg.norm(a_ue)
            used = arr["V"][np.unique(arr["T"])]
            p = used.mean(0) - c_ue                       # surface centroid relative to the hinge
            mv = np.cross(a_ue, p)                        # motion of the centroid for a small + rotation (numeric, as FQuat)
            if (s["sense"] == "down" and mv[2] > 0) or (s["sense"] == "right" and mv[1] < 0):
                a_ue = -a_ue
            arr["V"] = arr["V"] - c_ue                    # mesh pivot = hinge point
            rec.update(hinge_ue_cm=c_ue.round(3).tolist(), axis_ue=a_ue.round(6).tolist(), sense=s["sense"],
                       centroid_rel_cm=p.round(1).tolist())
        mats, gid = F.material_table(arr, texout, nm)
        F.write_obj(nm, arr, mats, gid)
        used = arr["V"][np.unique(arr["T"])]
        rec.update(bbox_ue_cm=dict(min=used.min(0).round(1).tolist(), max=used.max(0).round(1).tolist()),
                   materials=[dict(name=g["name"], texture=g["texture"], kd=g["kd"], transparent=g["transparent"],
                                   triangles=g["triangles"]) for g in mats])
        info["parts"][nm] = rec
        F.log(f"{nm}: {rec['triangles']} tris, {len(rec['objects'])} objects")
    # light points from the body extents (wing tips, fin top, belly) - positions only, our own lights
    b = info["parts"]["F16_Body"]["bbox_ue_cm"]
    body = F.build_part_arrays(new["F16_Body"])
    V = body["V"][np.unique(body["T"])]
    tipL, tipR = V[np.argmin(V[:, 1])], V[np.argmax(V[:, 1])]
    fin = V[np.argmax(V[:, 2])]
    info["lights_ue_cm"] = dict(nav_left=tipL.round(1).tolist(), nav_right=tipR.round(1).tolist(), fin_top=fin.round(1).tolist(),
                                tail=[round(float(b["min"][0]), 1), 0.0, round(float(fin[2]) - 80.0, 1)])
    for lf in ("LICENSE", "copyright.txt", "authors.txt"):
        p = repo.get(lf)
        if p is not None:
            shutil.copyfile(p, OUT / lf)
    (OUT / "airframe.json").write_text(json.dumps(info, indent=1), encoding="utf-8")
    F.log(f"done in {time.time() - t0:.0f} s -> {OUT}")


if __name__ == "__main__":
    main()
