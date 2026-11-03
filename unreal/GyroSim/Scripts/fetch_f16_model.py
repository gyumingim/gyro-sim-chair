#!/usr/bin/env python3
"""fetch_f16_model.py - FlightGear F-16 -> OBJ/MTL/PNG parts for the GyroSim Unreal project.

What it does
------------
1. Downloads (and caches) only the files that are needed from the FlightGear F-16
   aircraft repository into  ThirdParty/f16_src/<repo path>  (mirrors repo paths).
2. Loads the FlightGear model XML tree (Models/F-16.xml -> f16.ac, nozzle,
   Models/Cockpit/Main/cockpit.xml and every included sub-model) the way
   FlightGear/SimGear does: <offsets> (pitch, then roll, then heading, then
   translate), <model> includes (recursive), model <condition>s, and the
   static part of animations (select / rotate / translate / scale evaluated
   at a default property state = block-50 cockpit, gear down, everything else 0).
3. Splits the result into parts and writes, into ThirdParty/f16_obj/ :
     F16_Exterior.obj, F16_Glass.obj, F16_Gear.obj, F16_Cockpit.obj,
     F16_Stick.obj, F16_Throttle.obj, F16_PedalL.obj, F16_PedalR.obj
   (one .mtl per .obj), PNG textures (tex_*.png, max 2048 px), manifest.json,
   preview_*.png renders (exterior side/top/front/3-4, *_tex = texture colour at UV
   centroid, cockpit from the eye at 15/40 deg down, controls + pivots overlay),
   and copies of LICENSE / copyright.txt / authors.txt.
   Static pose = FG at default properties: gear down & uncompressed, canopy closed,
   surfaces neutral, throttle at throttle-movement=0 (idle, +40 deg in throttle.xml),
   GE nozzle, block-50 cockpit (sim/variant-id 5). Dropped: effects, lights, flames,
   chute, pilot, kneeboards, HMCS, stores, ground equipment, invisible pick boxes.

Run:  python fetch_f16_model.py            (CPython 3.10+, numpy, Pillow, matplotlib)
      python fetch_f16_model.py --no-preview

Source / license
----------------
Source:  https://github.com/NikolaiVChr/f16   (FlightGear F-16, "f16" aircraft)
Commit:  cc204ce03aa05500c4f9d904aff902efd5efaa90
Raw:     https://raw.githubusercontent.com/NikolaiVChr/f16/<commit>/<path>
License: GNU GPL v2.0 or later (see LICENSE, copyright.txt; authors in authors.txt,
         all copied into f16_obj/).  The converted meshes/textures are derived works
         of that GPL-2.0 package and stay under the GPL-2.0.

Coordinates (see manifest.json "convention")
---------------------------------------------
AC3D file (x, y, z) [Y up]  ->  FlightGear model frame (x aft, y right, z up, m) = (x, -z, y).
FG -> Unreal body frame (cm, X fwd, Y right, Z up, left-handed), FG eye point
(x=-4.105, y=0, z=0.8579) at UE (430, 0, 100):
    ue_x = (-x_fg - 4.105) * 100 + 430
    ue_y =   y_fg * 100
    ue_z = ( z_fg - 0.8579) * 100 + 100
OBJ file is written right-handed Y-up as  OBJ (x, y, z) = (ue_x, ue_z, ue_y)  [cm],
which is what the Unreal OBJ importer (FBX-style conversion, Convert Scene on,
Force Front X Axis off) maps back to UE (X, Y, Z) = (obj_x, obj_z, obj_y).
Front faces are CCW in the OBJ's right-handed frame (AC3D winding preserved:
fg->obj is a proper rotation, det = +1).  vt = AC3D (u, v) unchanged (OpenGL,
v=0 at image bottom; standard OBJ); PNGs are stored top row first as usual.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import math
import os
import re
import shutil
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

import numpy as np

SHA = "cc204ce03aa05500c4f9d904aff902efd5efaa90"
REPO_URL = "https://github.com/NikolaiVChr/f16"
RAW = f"https://raw.githubusercontent.com/NikolaiVChr/f16/{SHA}/"
TREE_API = f"https://api.github.com/repos/NikolaiVChr/f16/git/trees/{SHA}?recursive=1"

HERE = Path(__file__).resolve().parent
THIRD = HERE.parent / "ThirdParty"
SRC = THIRD / "f16_src"
OUT = THIRD / "f16_obj"

# FG eye point (f16-base.xml, view n=0: z-offset -4.105 = model x, y-offset 0.8579 = model z)
EYE_FG = np.array([-4.105, 0.0, 0.8579])
EYE_UE = np.array([430.0, 0.0, 100.0])

DEFAULT_CREASE = 61.0
MAX_TEX = 2048          # larger textures are downscaled (UVs stay valid)

LOG: list[str] = []


def log(msg: str) -> None:
    LOG.append(msg)
    print(msg, flush=True)


# ----------------------------------------------------------------------------
# Repository access (cached raw downloads)
# ----------------------------------------------------------------------------
class Repo:
    def __init__(self) -> None:
        SRC.mkdir(parents=True, exist_ok=True)
        self.files: dict[str, int] = {}
        self.lower: dict[str, str] = {}
        self.downloaded = 0
        self.bytes = 0
        self._load_tree()

    def _load_tree(self) -> None:
        cache = SRC / "_tree.json"
        data = None
        if cache.exists():
            data = json.loads(cache.read_text(encoding="utf-8"))
        else:
            try:
                req = urllib.request.Request(TREE_API, headers={"User-Agent": "gyrosim-f16-fetch"})
                with urllib.request.urlopen(req, timeout=60) as r:
                    data = json.loads(r.read().decode("utf-8"))
                cache.write_text(json.dumps(data), encoding="utf-8")
            except Exception as e:  # noqa: BLE001
                log(f"[warn] tree listing failed ({e}); falling back to blind raw fetches")
        if data:
            for e in data.get("tree", []):
                if e.get("type") == "blob":
                    self.files[e["path"]] = e.get("size", 0)
                    self.lower[e["path"].lower()] = e["path"]

    def exists(self, path: str) -> str | None:
        """Return the repo path (case-fixed) if it exists in the tree."""
        path = path.replace("\\", "/")
        if not self.files:
            return path
        if path in self.files:
            return path
        return self.lower.get(path.lower())

    def get(self, path: str) -> Path | None:
        rp = self.exists(path)
        if rp is None:
            return None
        local = SRC / rp
        if local.exists() and (not self.files or local.stat().st_size == self.files.get(rp, local.stat().st_size)):
            return local
        url = RAW + urllib.request.quote(rp)
        for attempt in range(4):
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "gyrosim-f16-fetch"})
                with urllib.request.urlopen(req, timeout=120) as r:
                    blob = r.read()
                local.parent.mkdir(parents=True, exist_ok=True)
                local.write_bytes(blob)
                self.downloaded += 1
                self.bytes += len(blob)
                return local
            except urllib.error.HTTPError as e:
                if e.code == 404:
                    log(f"[missing] {rp} (404)")
                    return None
                time.sleep(1.5 * (attempt + 1))
            except Exception:  # noqa: BLE001
                time.sleep(1.5 * (attempt + 1))
        log(f"[error] download failed: {rp}")
        return None


def norm_join(base_dir: str, rel: str) -> str:
    parts: list[str] = []
    for p in (base_dir + "/" + rel if base_dir else rel).replace("\\", "/").split("/"):
        if p in ("", "."):
            continue
        if p == "..":
            if parts:
                parts.pop()
            continue
        parts.append(p)
    return "/".join(parts)


def resolve_model_path(repo: Repo, xml_dir: str, path: str) -> str | None:
    path = path.strip().replace("\\", "/")
    cands = []
    if path.startswith("Aircraft/f16/"):
        cands.append(path[len("Aircraft/f16/"):])
    else:
        cands.append(norm_join(xml_dir, path))
        cands.append(path)
    for c in cands:
        rp = repo.exists(c)
        if rp:
            return rp
    return None


# ----------------------------------------------------------------------------
# Geometry containers
# ----------------------------------------------------------------------------
class Mat:
    __slots__ = ("name", "rgb", "amb", "emis", "spec", "shi", "trans")

    def __init__(self, name, rgb, amb, emis, spec, shi, trans):
        self.name, self.rgb, self.amb, self.emis, self.spec, self.shi, self.trans = name, rgb, amb, emis, spec, shi, trans


class Node:
    """Scene node. Mesh data (if any) is already expressed in the frame of the
    model file that owns the node at the current stage of loading."""

    __slots__ = ("name", "kids", "V", "T", "UV", "MK", "SM", "DS", "crease", "src", "hidden", "tags")

    def __init__(self, name: str):
        self.name = name
        self.kids: list[Node] = []
        self.V = None      # (n,3) float64 vertices
        self.T = None      # (m,3) int triangle vertex indices
        self.UV = None     # (m,3,2) per-corner uv (texrep/texoff applied)
        self.MK = None     # (m,) int material-key ids (global table)
        self.SM = None     # (m,) bool smooth shaded
        self.DS = None     # (m,) bool double sided
        self.crease = DEFAULT_CREASE
        self.src = ""
        self.hidden = False
        self.tags: dict = {}

    def walk(self):
        yield self
        for k in self.kids:
            yield from k.walk()

    def find(self, name: str):
        return [n for n in self.walk() if n.name == name]

    def transform(self, M: np.ndarray) -> None:
        for n in self.walk():
            if n.V is not None and len(n.V):
                n.V = n.V @ M[:3, :3].T + M[:3, 3]
                if np.linalg.det(M[:3, :3]) < 0:
                    n.T = n.T[:, ::-1].copy()
                    n.UV = n.UV[:, ::-1].copy()


# global material-key table: key -> id
MATKEYS: list[tuple] = []
MATKEY_ID: dict[tuple, int] = {}


def matkey(tex: str | None, m: Mat) -> int:
    key = (tex, tuple(round(c, 3) for c in m.rgb), tuple(round(c, 3) for c in m.emis), round(m.trans, 3), m.name)
    if key not in MATKEY_ID:
        MATKEY_ID[key] = len(MATKEYS)
        MATKEYS.append(key)
    return MATKEY_ID[key]


# ----------------------------------------------------------------------------
# AC3D parser
# ----------------------------------------------------------------------------
def triangulate(pts: np.ndarray) -> list[tuple[int, int, int]]:
    n = len(pts)
    if n < 3:
        return []
    if n == 3:
        return [(0, 1, 2)]
    # Newell normal
    nrm = np.zeros(3)
    for i in range(n):
        a, b = pts[i], pts[(i + 1) % n]
        nrm += np.array([(a[1] - b[1]) * (a[2] + b[2]), (a[2] - b[2]) * (a[0] + b[0]), (a[0] - b[0]) * (a[1] + b[1])])
    ln = np.linalg.norm(nrm)
    if ln < 1e-14:
        return [(0, i, i + 1) for i in range(1, n - 1)]
    nrm /= ln
    ax = int(np.argmax(np.abs(nrm)))
    i0, i1 = [(1, 2), (2, 0), (0, 1)][ax]
    p2 = pts[:, [i0, i1]]
    if nrm[ax] < 0:
        p2 = p2[:, ::-1]

    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    # convex check -> fan
    convex = all(cross(p2[i], p2[(i + 1) % n], p2[(i + 2) % n]) >= -1e-12 for i in range(n))
    if convex:
        return [(0, i, i + 1) for i in range(1, n - 1)]
    idx = list(range(n))
    tris = []
    guard = 0
    while len(idx) > 3 and guard < 10 * n:
        guard += 1
        found = False
        m = len(idx)
        for k in range(m):
            a, b, c = idx[(k - 1) % m], idx[k], idx[(k + 1) % m]
            if cross(p2[a], p2[b], p2[c]) <= 1e-14:
                continue
            ok = True
            for j in idx:
                if j in (a, b, c):
                    continue
                p = p2[j]
                if cross(p2[a], p2[b], p) >= 0 and cross(p2[b], p2[c], p) >= 0 and cross(p2[c], p2[a], p) >= 0:
                    ok = False
                    break
            if ok:
                tris.append((a, b, c))
                idx.pop(k)
                found = True
                break
        if not found:
            break
    if len(idx) == 3:
        tris.append(tuple(idx))
    elif len(idx) > 3:
        tris += [(idx[0], idx[i], idx[i + 1]) for i in range(1, len(idx) - 1)]
    return tris


AC_TO_FG = np.array([[1.0, 0, 0], [0, 0, -1.0], [0, 1.0, 0]])  # fg = AC_TO_FG @ ac


class TexResolver:
    """Maps AC texture names to local files and later to output PNG names."""

    def __init__(self, repo: Repo):
        self.repo = repo
        self.map: dict[tuple[str, str], str | None] = {}
        self.missing: set[str] = set()

    def resolve(self, ac_dir: str, tex: str) -> str | None:
        key = (ac_dir, tex)
        if key in self.map:
            return self.map[key]
        t = tex.replace("\\", "/")
        cands = []
        if t.startswith("Aircraft/f16/"):
            cands.append(t[len("Aircraft/f16/"):])
        cands += [norm_join(ac_dir, t), t, norm_join(ac_dir, os.path.basename(t))]
        stem = os.path.splitext(t)[0]
        for ext in (".png", ".rgb", ".sgi", ".dds", ".jpg"):
            cands.append(norm_join(ac_dir, stem + ext))
        rp = None
        for c in cands:
            rp = self.repo.exists(c)
            if rp:
                break
        if rp is None or self.repo.get(rp) is None:
            self.missing.add(f"{tex} (from {ac_dir or '.'})")
            rp = None
        self.map[key] = rp
        return rp


def parse_ac(path: Path, repo_path: str, texres: TexResolver) -> Node:
    ac_dir = os.path.dirname(repo_path)
    lines = path.read_text(encoding="latin-1").splitlines()
    pos = 0
    mats: list[Mat] = []

    while pos < len(lines):
        ln = lines[pos].strip()
        if ln.startswith("MATERIAL"):
            m = re.match(r'MATERIAL\s+"?(.*?)"?\s+rgb\s+(.*)', ln)
            name = m.group(1) if m else ""
            toks = ln.split()

            def grab(key, cnt):
                if key in toks:
                    i = toks.index(key)
                    return [float(x) for x in toks[i + 1:i + 1 + cnt]]
                return [0.0] * cnt

            mats.append(Mat(name, grab("rgb", 3), grab("amb", 3), grab("emis", 3), grab("spec", 3),
                            grab("shi", 1)[0], grab("trans", 1)[0]))
            pos += 1
            continue
        if ln.startswith("OBJECT"):
            break
        pos += 1

    def read_object(parent_R, parent_t):
        nonlocal pos
        while pos < len(lines) and not lines[pos].strip().startswith("OBJECT"):
            pos += 1
        if pos >= len(lines):
            return Node("")
        hdr = lines[pos].split()
        pos += 1
        node = Node("")
        node.src = repo_path
        node.tags["actype"] = hdr[1] if len(hdr) > 1 else ""
        tex = None
        texrep = (1.0, 1.0)
        texoff = (0.0, 0.0)
        R = np.eye(3)
        loc = np.zeros(3)
        verts = None
        tris, uvs, mks, sms, dss = [], [], [], [], []
        nkids = 0
        while pos < len(lines):
            raw = lines[pos]
            s = raw.strip()
            pos += 1
            if not s:
                continue
            tok = s.split(None, 1)
            key = tok[0]
            rest = tok[1] if len(tok) > 1 else ""
            if key == "name":
                node.name = rest.strip().strip('"')
            elif key == "data":
                nchar = int(rest)
                if nchar == 0:
                    continue
                got = 0
                while got < nchar and pos < len(lines):
                    got += len(lines[pos]) + 1
                    pos += 1
            elif key == "texture":
                tex = rest.strip().strip('"')
            elif key == "texrep":
                a = rest.split()
                texrep = (float(a[0]), float(a[1]))
            elif key == "texoff":
                a = rest.split()
                texoff = (float(a[0]), float(a[1]))
            elif key == "rot":
                a = [float(x) for x in rest.split()]
                R = np.array(a, dtype=float).reshape(3, 3)
            elif key == "loc":
                loc = np.array([float(x) for x in rest.split()[:3]])
            elif key == "crease":
                node.crease = float(rest)
            elif key == "numvert":
                nv = int(rest)
                arr = np.array([[float(x) for x in lines[pos + i].split()[:3]] for i in range(nv)], dtype=float) \
                    if nv else np.zeros((0, 3))
                pos += nv
                verts = arr
            elif key == "numsurf":
                ns = int(rest)
                for _ in range(ns):
                    flags = 0
                    mat = 0
                    refs = []
                    while pos < len(lines):
                        s2 = lines[pos].strip()
                        pos += 1
                        if not s2:
                            continue
                        k2 = s2.split()
                        if k2[0] == "SURF":
                            flags = int(k2[1], 16)
                        elif k2[0] == "mat":
                            mat = int(k2[1])
                        elif k2[0] == "refs":
                            nr = int(k2[1])
                            for i in range(nr):
                                a = lines[pos + i].split()
                                refs.append((int(a[0]), float(a[1]) if len(a) > 1 else 0.0,
                                             float(a[2]) if len(a) > 2 else 0.0))
                            pos += nr
                            break
                    typ = flags & 0x0F
                    if typ != 0 or len(refs) < 3 or verts is None:
                        continue
                    vidx = [r[0] for r in refs]
                    if max(vidx) >= len(verts):
                        continue
                    m = mats[mat] if mat < len(mats) else Mat("default", [1, 1, 1], [1, 1, 1], [0, 0, 0], [0, 0, 0], 0, 0)
                    tp = texres.resolve(ac_dir, tex) if tex else None
                    mk = matkey(tp, m)
                    for (a, b, c) in triangulate(verts[vidx]):
                        tris.append((vidx[a], vidx[b], vidx[c]))
                        uvs.append([[texoff[0] + refs[q][1] * texrep[0], texoff[1] + refs[q][2] * texrep[1]]
                                    for q in (a, b, c)])
                        mks.append(mk)
                        sms.append(bool(flags & 0x10))
                        dss.append(bool(flags & 0x20))
            elif key == "kids":
                nkids = int(rest)
                break
        # world (file) transform of this object
        Rw = parent_R @ R
        tw = parent_R @ loc + parent_t
        if verts is not None and len(tris):
            vw = verts @ Rw.T + tw
            node.V = vw @ AC_TO_FG.T
            node.T = np.array(tris, dtype=np.int64)
            node.UV = np.array(uvs, dtype=np.float64)
            node.MK = np.array(mks, dtype=np.int64)
            node.SM = np.array(sms, dtype=bool)
            node.DS = np.array(dss, dtype=bool)
        for _ in range(nkids):
            node.kids.append(read_object(Rw, tw))
        return node

    root = Node(os.path.basename(repo_path))
    while pos < len(lines):
        if lines[pos].strip().startswith("OBJECT"):
            root.kids.append(read_object(np.eye(3), np.zeros(3)))
        else:
            pos += 1
    # AC 'world' object: keep its kids directly
    if len(root.kids) == 1 and root.kids[0].tags.get("actype") == "world":
        w = root.kids[0]
        root.kids = w.kids
    for n in root.walk():
        n.tags.setdefault("mats", mats)
    return root


# ----------------------------------------------------------------------------
# FlightGear property state + condition evaluation
# ----------------------------------------------------------------------------
PROPS: dict[str, object] = {
    "sim/variant-id": 5,                     # Block 50 (MLU-style cockpit, F-16-FS stick)
    "sim/model/livery/actype": "F-16C-50",
    "sim/current-view/internal": True,
    "sim/current-view/name": "Cockpit View",
    "sim/multiplay/generic/int[9]": 5,
    "sim/multiplay/generic/int[10]": 0,      # 0 = GE nozzle (default)
    "gear/gear[0]/position-norm": 1.0,
    "gear/gear[1]/position-norm": 1.0,
    "gear/gear[2]/position-norm": 1.0,
    "gear/gear[0]/wow": True,
    "gear/gear[1]/wow": True,
    "gear/gear[2]/wow": True,
    "controls/gear/gear-down": True,
    "fdm/jsbsim/gear/gear-pos-norm": 1.0,
    "fdm/jsbsim/gear/unit[0]/pos-norm": 1.0,
    "fdm/jsbsim/gear/unit[1]/pos-norm": 1.0,
    "fdm/jsbsim/gear/unit[2]/pos-norm": 1.0,
    "sim/rendering/rembrandt/enabled": False,
    "sim/version/compositor-support": True,
    "sim/rendering/shaders/skydome": True,
}


def _norm_prop(p: str) -> str:
    p = p.strip().lstrip("/")
    p = re.sub(r"\[0\]", "[0]", p)
    return p


def getprop(p: str):
    p = _norm_prop(p)
    if p in PROPS:
        return PROPS[p]
    q = re.sub(r"\[0\]", "", p)
    for k, v in PROPS.items():
        if re.sub(r"\[0\]", "", k) == q:
            return v
    return 0


def _tonum(v):
    if isinstance(v, bool):
        return 1.0 if v else 0.0
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _operand(el, root):
    tag = el.tag
    if tag == "property":
        return getprop(prop_name(el, root))
    if tag == "value":
        return (el.text or "").strip()
    if tag == "expression":
        return 0
    return 0


def _cmp_vals(a, b):
    na, nb = _tonum(a), _tonum(b)
    if na is not None and nb is not None:
        return na, nb
    return str(a), str(b)


def eval_cond(el, root) -> bool:
    """FG <condition>: children ANDed."""
    return all(eval_term(c, root) for c in el if isinstance(c.tag, str))


def eval_term(c, root) -> bool:
    t = c.tag
    if t in ("and", "condition"):
        return all(eval_term(x, root) for x in c if isinstance(x.tag, str))
    if t == "or":
        return any(eval_term(x, root) for x in c if isinstance(x.tag, str))
    if t == "not":
        return not all(eval_term(x, root) for x in c if isinstance(x.tag, str))
    if t == "property":
        v = getprop(prop_name(c, root))
        n = _tonum(v)
        return bool(n) if n is not None else bool(v)
    if t in ("equals", "not-equals", "less-than", "greater-than", "less-than-equals", "greater-than-equals"):
        ops = [x for x in c if isinstance(x.tag, str) and x.tag in ("property", "value", "expression")]
        if len(ops) < 2:
            return False
        a, b = _cmp_vals(_operand(ops[0], root), _operand(ops[1], root))
        try:
            return {"equals": a == b, "not-equals": a != b, "less-than": a < b, "greater-than": a > b,
                    "less-than-equals": a <= b, "greater-than-equals": a >= b}[t]
        except TypeError:
            return False
    return True


def prop_name(el, root) -> str:
    alias = el.get("alias")
    if alias:
        # alias like ../../params/foo : resolve in this file's root
        cur = root
        ok = True
        for part in [p for p in alias.split("/") if p not in ("", "..", ".")]:
            nxt = cur.find(part)
            if nxt is None:
                ok = False
                break
            cur = nxt
        if ok and cur is not None and cur.text:
            return cur.text.strip()
        return ""
    return (el.text or "").strip()


def fnum(el, tag, default=0.0, root=None):
    if el is None:
        return default
    x = el.find(tag)
    if x is None or x.text is None:
        if x is not None and x.get("alias") and root is not None:
            pn = prop_name(x, root)
            try:
                return float(pn)
            except ValueError:
                return default
        return default
    try:
        return float(x.text.strip())
    except ValueError:
        return default


# ----------------------------------------------------------------------------
# Transforms
# ----------------------------------------------------------------------------
def rot_axis(axis, deg):
    a = np.asarray(axis, float)
    n = np.linalg.norm(a)
    if n < 1e-12:
        return np.eye(3)
    x, y, z = a / n
    t = math.radians(deg)
    c, s = math.cos(t), math.sin(t)
    C = 1 - c
    return np.array([[c + x * x * C, x * y * C - z * s, x * z * C + y * s],
                     [y * x * C + z * s, c + y * y * C, y * z * C - x * s],
                     [z * x * C - y * s, z * y * C + x * s, c + z * z * C]])


def offsets_matrix(off, root=None) -> np.ndarray:
    """SimGear: res = makeRotate(pitch,Y, roll,X, heading,Z) * translate  (OSG row vectors)
    -> column form: v' = Rz(h) Rx(r) Ry(p) v + t."""
    M = np.eye(4)
    if off is None:
        return M
    p = fnum(off, "pitch-deg", 0, root)
    r = fnum(off, "roll-deg", 0, root)
    h = fnum(off, "heading-deg", 0, root)
    R = rot_axis((0, 0, 1), h) @ rot_axis((1, 0, 0), r) @ rot_axis((0, 1, 0), p)
    M[:3, :3] = R
    M[:3, 3] = [fnum(off, "x-m", 0, root), fnum(off, "y-m", 0, root), fnum(off, "z-m", 0, root)]
    return M


def anim_value(a, root, unit: str, default_start=0.0, dflt_offset=0.0):
    """SimGear read_value: (prop or starting-position) -> interpolation | *factor + offset, clipped."""
    pe = a.find("property")
    if pe is not None and prop_name(pe, root):
        v = _tonum(getprop(prop_name(pe, root))) or 0.0
    else:
        v = fnum(a, f"starting-position{unit}", default_start, root)
    interp = a.find("interpolation")
    if interp is not None:
        pts = []
        for e in interp.findall("entry"):
            pts.append((fnum(e, "ind", 0), fnum(e, "dep", 0)))
        if pts:
            pts.sort()
            xs = [p[0] for p in pts]
            ys = [p[1] for p in pts]
            return float(np.interp(v, xs, ys))
    if a.find("factor") is not None:
        v *= fnum(a, "factor", 1.0, root)
    if a.find(f"offset{unit}") is not None:
        v += fnum(a, f"offset{unit}", 0.0, root)
    lo = a.find(f"min{unit}")
    hi = a.find(f"max{unit}")
    if lo is not None:
        v = max(v, fnum(a, f"min{unit}", -1e30, root))
    if hi is not None:
        v = min(v, fnum(a, f"max{unit}", 1e30, root))
    return v


def axis_center(a, root):
    ax = a.find("axis")
    center = np.array([fnum(a.find("center"), "x-m", 0, root), fnum(a.find("center"), "y-m", 0, root),
                       fnum(a.find("center"), "z-m", 0, root)])
    if ax is not None and ax.find("x1-m") is not None:
        p1 = np.array([fnum(ax, "x1-m", 0, root), fnum(ax, "y1-m", 0, root), fnum(ax, "z1-m", 0, root)])
        p2 = np.array([fnum(ax, "x2-m", 0, root), fnum(ax, "y2-m", 0, root), fnum(ax, "z2-m", 0, root)])
        return p2 - p1, (p1 + p2) / 2
    if ax is not None and ax.find("object-name") is not None:
        return None, None
    axis = np.array([fnum(ax, "x", 0, root), fnum(ax, "y", 0, root), fnum(ax, "z", 0, root)]) if ax is not None \
        else np.array([0.0, 0.0, 1.0])
    return axis, center


def anim_matrix(a, root, typ: str):
    """Static (default-state) matrix for transform animations, or None for identity."""
    M = np.eye(4)
    if typ in ("rotate", "knob"):
        ang = anim_value(a, root, "-deg")
        if abs(ang) < 1e-9:
            return None
        axis, c = axis_center(a, root)
        if axis is None:
            return None
        R = rot_axis(axis, ang)
        M[:3, :3] = R
        M[:3, 3] = c - R @ c
        return M
    if typ in ("translate", "slider"):
        d = anim_value(a, root, "-m")
        if abs(d) < 1e-12:
            return None
        axis, _ = axis_center(a, root)
        if axis is None or np.linalg.norm(axis) < 1e-12:
            return None
        M[:3, 3] = d * axis / np.linalg.norm(axis)
        return M
    if typ == "scale":
        pe = a.find("property")
        v = (_tonum(getprop(prop_name(pe, root))) or 0.0) if pe is not None else 0.0
        s = []
        for k in "xyz":
            f = fnum(a, f"{k}-factor", 1.0 if a.find("factor") is None else fnum(a, "factor", 1.0), root)
            o = fnum(a, f"{k}-offset", 1.0, root)
            s.append(v * f + o if pe is not None else o)
        if np.allclose(s, 1.0):
            return None
        c = np.array([fnum(a.find("center"), "x-m", 0, root), fnum(a.find("center"), "y-m", 0, root),
                      fnum(a.find("center"), "z-m", 0, root)])
        S = np.diag(s)
        M[:3, :3] = S
        M[:3, 3] = c - S @ c
        return M
    return None


# ----------------------------------------------------------------------------
# FG model XML loader
# ----------------------------------------------------------------------------
class Loader:
    def __init__(self, repo: Repo, texres: TexResolver, skip_model):
        self.repo = repo
        self.texres = texres
        self.skip_model = skip_model   # callable(name, path, depth_names) -> bool
        self.loaded: list[str] = []
        self.skipped: list[str] = []
        self.external: list[str] = []
        self.ac_cache: dict[str, Path] = {}

    def parse_xml(self, rp: str):
        p = self.repo.get(rp)
        if p is None:
            return None
        txt = p.read_bytes().decode("utf-8", errors="replace").lstrip("﻿")
        try:
            root = ET.fromstring(txt)
        except ET.ParseError:
            txt2 = re.sub(r"<!--.*?-->", "", txt, flags=re.S)
            root = ET.fromstring(txt2)
        inc = root.get("include")
        if inc:
            irp = resolve_model_path(self.repo, os.path.dirname(rp), inc)
            if irp:
                base = self.parse_xml(irp)
                if base is not None:
                    for ch in list(base)[::-1]:
                        if root.find(ch.tag) is None or ch.tag in ("animation", "model", "effect"):
                            root.insert(0, ch)
        return root

    def load(self, rp: str, chain: tuple = ()) -> Node | None:
        if rp.lower().endswith(".ac"):
            p = self.repo.get(rp)
            if p is None:
                return None
            self.loaded.append(rp)
            return parse_ac(p, rp, self.texres)
        if not rp.lower().endswith(".xml"):
            self.external.append(rp)
            return None
        root = self.parse_xml(rp)
        if root is None:
            return None
        self.loaded.append(rp)
        xml_dir = os.path.dirname(rp)
        grp = Node(os.path.basename(rp))
        grp.src = rp
        path_el = root.find("path")
        if path_el is not None and path_el.text and path_el.text.strip():
            acp = resolve_model_path(self.repo, xml_dir, path_el.text)
            if acp is None:
                self.external.append(norm_join(xml_dir, path_el.text.strip()))
            else:
                sub = self.load(acp, chain)
                if sub is not None:
                    grp.kids.append(sub)
        # sub-models
        for m in root.findall("model"):
            name = (m.findtext("name") or "").strip()
            mpath = (m.findtext("path") or "").strip()
            cond = m.find("condition")
            if cond is not None and not eval_cond(cond, root):
                self.skipped.append(f"{rp}: <model> {name} ({mpath}) condition false")
                continue
            if self.skip_model(name, mpath, chain + (name,)):
                self.skipped.append(f"{rp}: <model> {name} ({mpath}) excluded")
                continue
            srp = resolve_model_path(self.repo, xml_dir, mpath)
            if srp is None:
                self.external.append(mpath)
                continue
            sub = self.load(srp, chain + (name,))
            if sub is None:
                continue
            off = m.find("offsets")
            if off is not None:
                sub.transform(offsets_matrix(off, root))
            node = Node(name)
            node.kids.append(sub)
            node.src = srp
            grp.kids.append(node)
        # animations: first-listed = outermost transform -> apply to vertices in reverse order
        anims = root.findall("animation")
        hide_names: set[str] = set()
        for a in anims:
            typ = (a.findtext("type") or "").strip()
            names = [(e.text or "").strip() for e in a.findall("object-name")]
            if typ == "select":
                cond = a.find("condition")
                if cond is not None and not eval_cond(cond, root):
                    hide_names.update(names)
            elif typ in ("pick", "knob", "slider", "touch"):
                vis = a.findtext("visible")
                if vis is not None and vis.strip().lower() in ("false", "0"):
                    hide_names.update(names)
            elif typ in ("light",):
                hide_names.update(names)
        for a in reversed(anims):
            typ = (a.findtext("type") or "").strip()
            if typ not in ("rotate", "translate", "scale", "knob", "slider"):
                continue
            M = anim_matrix(a, root, typ)
            if M is None:
                continue
            names = [(e.text or "").strip() for e in a.findall("object-name")]
            done = set()
            for nm in names:
                for n in grp.find(nm):
                    if id(n) in done:
                        continue
                    done.add(id(n))
                    n.transform(M)
        for nm in hide_names:
            for n in grp.find(nm):
                n.hidden = True
        own = root.find("offsets")
        if own is not None and len(list(own)):
            grp.transform(offsets_matrix(own, root))
        return grp


# ----------------------------------------------------------------------------
# Part selection
# ----------------------------------------------------------------------------
# F-16.xml sub-models that are kept (everything else = effects, lights, pilot, stores, ground equipment)
EXT_KEEP_MODELS = {"interior", "PW_nozzle", "GE_nozzle", "brakeL", "brakeU", "outlet"}
# cockpit.xml sub-models that are not part of any output
CKPT_DROP_MODELS = {"knee1", "knee2", "HMCS-basic", "HMCS-norm", "Pilot_ext", "Pilot_int"}
# cockpit.xml sub-models that become their own parts
CKPT_PART_MODELS = {"F-16-FS": "F16_Stick", "Throttle": "F16_Throttle", "RudderPedals": "F16_Pedals"}

# f16.ac objects dropped from the exterior (effects / lights / logos / not wanted)
EXT_DROP_PATTERNS = [
    r"flame", r"afterburner", r"^AB_", r"^Chute$", r"Flare", r"LightCone", r"Halo", r"^pos_lights",
    r"PosLight", r"FormationL", r"Strobe",
    r"RNLAF", r"Winglogo", r"^Rect$", r"LogoPilot",
]
GEAR_PATTERNS = [r"Tire", r"Strut", r"Wheel", r"Oleo", r"GearDoor", r"MainDoor", r"Torque", r"Scissor",
                 r"Brake(?!.*Speed)", r"Axle", r"LandingGear", r"Gear"]
GLASS_PATTERNS = [r"Canopy(Forward|Back)(Inside|Outside)", r"[Gg]lass"]


def match_any(pats, name):
    return any(re.search(p, name) for p in pats)


def skip_model(name: str, path: str, chain: tuple) -> bool:
    if len(chain) == 1:   # children of F-16.xml
        return name not in EXT_KEEP_MODELS
    if "interior" in chain and name in CKPT_DROP_MODELS:
        return True
    low = path.lower()
    if any(k in low for k in ("/effects/", "kneeboard", "hmcs", "pilot_", "/pilots/")):
        return True
    return False


# ----------------------------------------------------------------------------
# Collect meshes into parts
# ----------------------------------------------------------------------------
class Part:
    def __init__(self, name):
        self.name = name
        self.chunks: list[tuple[Node, np.ndarray]] = []   # (node, tri mask)
        self.objects: list[str] = []


def collect(root: Node):
    parts = {n: Part(n) for n in ["F16_Exterior", "F16_Glass", "F16_Gear", "F16_Cockpit", "F16_Stick",
                                  "F16_Throttle", "F16_Pedals"]}
    dropped: dict[str, int] = {}

    def visit(n: Node, ctx: str, under_gear: bool, hidden: bool):
        if n.hidden:
            hidden = True
        name = n.name
        if ctx == "ext" and name == "interior":
            ctx = "ckpt"
        if ctx == "ckpt" and name in CKPT_PART_MODELS:
            ctx = CKPT_PART_MODELS[name]
        if ctx == "ext" and n.src == "Models/f16.ac" and (name == "LandingGear" or match_any(GEAR_PATTERNS, name)) \
                and not re.search(r"Speedbrake|Well|Bay", name):
            under_gear = True
        if n.V is not None and n.T is not None and len(n.T):
            label = f"{os.path.basename(n.src)}:{name}"
            if hidden:
                dropped[label + " (hidden by select/condition)"] = len(n.T)
            elif ctx == "ext":
                trans = np.array([MATKEYS[k][3] > 0.05 for k in n.MK])
                is_glass = match_any(GLASS_PATTERNS, name) or (
                    trans.mean() > 0.5 and any("canopy" in (MATKEYS[k][0] or "").lower() for k in n.MK))
                if match_any(EXT_DROP_PATTERNS, name):
                    dropped[label] = len(n.T)
                elif is_glass:
                    parts["F16_Glass"].chunks.append((n, np.ones(len(n.T), bool)))
                    parts["F16_Glass"].objects.append(label)
                elif under_gear:
                    parts["F16_Gear"].chunks.append((n, np.ones(len(n.T), bool)))
                    parts["F16_Gear"].objects.append(label)
                else:
                    parts["F16_Exterior"].chunks.append((n, np.ones(len(n.T), bool)))
                    parts["F16_Exterior"].objects.append(label)
            elif ctx == "ckpt":
                if re.search(r"hotspot|^pick|_pick$", name, re.I):
                    dropped[label] = len(n.T)
                else:
                    parts["F16_Cockpit"].chunks.append((n, np.ones(len(n.T), bool)))
                    parts["F16_Cockpit"].objects.append(label)
            else:
                parts[ctx].chunks.append((n, np.ones(len(n.T), bool)))
                parts[ctx].objects.append(label)
        for k in n.kids:
            visit(k, ctx, under_gear, hidden)

    visit(root, "ext", False, False)
    return parts, dropped


# ----------------------------------------------------------------------------
# Normals
# ----------------------------------------------------------------------------
def corner_normals(V, T, SM, crease_deg):
    p0, p1, p2 = V[T[:, 0]], V[T[:, 1]], V[T[:, 2]]
    fn = np.cross(p1 - p0, p2 - p0)            # area weighted
    ln = np.linalg.norm(fn, axis=1, keepdims=True)
    fu = fn / np.maximum(ln, 1e-20)
    m = len(T)
    out = np.repeat(fu[:, None, :], 3, axis=1).copy()
    if not SM.any():
        return out
    cosc = math.cos(math.radians(min(max(crease_deg, 0.0), 180.0)))
    cv = T.ravel()
    cf = np.repeat(np.arange(m), 3)
    sm_c = SM[cf]
    idx = np.nonzero(sm_c)[0]
    if len(idx) == 0:
        return out
    order = idx[np.argsort(cv[idx], kind="stable")]
    sv = cv[order]
    starts = np.r_[0, np.nonzero(np.diff(sv))[0] + 1]
    lens = np.diff(np.r_[starts, len(sv)])
    acc = np.zeros((3 * m, 3))
    # chunked pair expansion
    gi = 0
    while gi < len(starts):
        gj = gi
        tot = 0
        while gj < len(starts) and tot < 4_000_000:
            tot += int(lens[gj]) ** 2
            gj += 1
        st, ln_ = starts[gi:gj], lens[gi:gj]
        rep = np.repeat(np.arange(len(st)), ln_ * ln_)
        base = np.repeat(st, ln_ * ln_)
        within = np.arange(len(rep)) - np.repeat(np.cumsum(ln_ * ln_) - ln_ * ln_, ln_ * ln_)
        L = ln_[rep]
        a = order[base + within // L]
        b = order[base + within % L]
        fa, fb = cf[a], cf[b]
        ok = np.einsum("ij,ij->i", fu[fa], fu[fb]) >= cosc - 1e-9
        np.add.at(acc, a[ok], fn[fb[ok]])
        gi = gj
    acc = acc.reshape(m, 3, 3)
    l2 = np.linalg.norm(acc, axis=2, keepdims=True)
    sm3 = np.repeat(SM[:, None], 3, axis=1)
    good = (l2[..., 0] > 1e-20) & sm3
    out[good] = (acc / np.maximum(l2, 1e-20))[good]
    return out


# ----------------------------------------------------------------------------
# Output conversion
# ----------------------------------------------------------------------------
def fg_to_ue(P):
    P = np.asarray(P, float)
    return np.stack([(EYE_FG[0] - P[..., 0]) * 100 + EYE_UE[0],
                     P[..., 1] * 100 + EYE_UE[1],
                     (P[..., 2] - EYE_FG[2]) * 100 + EYE_UE[2]], axis=-1)


def fgdir_to_ue(D):
    D = np.asarray(D, float)
    return np.stack([-D[..., 0], D[..., 1], D[..., 2]], axis=-1)


def ue_to_obj(P):
    P = np.asarray(P, float)
    return np.stack([P[..., 0], P[..., 2], P[..., 1]], axis=-1)


class TexOut:
    def __init__(self, repo: Repo):
        self.repo = repo
        self.done: dict[str, dict] = {}

    def png_for(self, rp: str) -> dict | None:
        if rp in self.done:
            return self.done[rp]
        from PIL import Image
        p = self.repo.get(rp)
        info = None
        if p is not None:
            try:
                im = Image.open(p)
                im.load()
                if im.mode not in ("RGB", "RGBA"):
                    im = im.convert("RGBA" if ("A" in im.mode or "transparency" in im.info) else "RGB")
                if max(im.size) > MAX_TEX:
                    sc = MAX_TEX / max(im.size)
                    im = im.resize((max(1, round(im.size[0] * sc)), max(1, round(im.size[1] * sc))),
                                   Image.LANCZOS)
                alpha = False
                if im.mode == "RGBA":
                    a = np.asarray(im)[..., 3]
                    alpha = bool((a < 250).mean() > 0.002)
                    if not alpha:
                        im = im.convert("RGB")
                stem = re.sub(r"[^A-Za-z0-9_]+", "_", os.path.splitext(rp)[0].replace("Models/", ""))
                fname = f"tex_{stem}.png"
                im.save(OUT / fname, optimize=True)
                info = {"png": fname, "alpha": alpha, "src": rp, "size": list(im.size)}
            except Exception as e:  # noqa: BLE001
                log(f"[warn] texture {rp} unreadable: {e}")
        self.done[rp] = info
        return info


INVISIBLE_DROPPED: dict[str, int] = {}


def build_part_arrays(part: Part):
    """Concatenate node chunks -> arrays in UE cm. Returns dict."""
    Vs, Ts, UVs, Ns, MKs, DSs = [], [], [], [], [], []
    off = 0
    for n, mask in part.chunks:
        # AC materials with trans >= 0.99 and no texture are invisible in FG (pick boxes etc.) -> drop
        invisible = np.array([MATKEYS[k][3] >= 0.99 and MATKEYS[k][0] is None for k in n.MK], bool)
        if invisible[mask].any():
            INVISIBLE_DROPPED[f"{os.path.basename(n.src)}:{n.name}"] = int(invisible[mask].sum())
        mask = mask & ~invisible
        T = n.T[mask]
        if not len(T):
            continue
        N = corner_normals(n.V, T, n.SM[mask], n.crease)
        Vs.append(n.V)
        Ts.append(T + off)
        UVs.append(n.UV[mask])
        Ns.append(N)
        MKs.append(n.MK[mask])
        DSs.append(n.DS[mask])
        off += len(n.V)
    if not Vs:
        return None
    V = fg_to_ue(np.concatenate(Vs))
    T = np.concatenate(Ts)
    # drop unused vertices
    used = np.unique(T)
    remap = -np.ones(len(V), np.int64)
    remap[used] = np.arange(len(used))
    V = V[used]
    T = remap[T]
    # drop degenerate triangles
    a = np.cross(V[T[:, 1]] - V[T[:, 0]], V[T[:, 2]] - V[T[:, 0]])
    good = np.linalg.norm(a, axis=1) > 1e-10
    sel = lambda x: np.concatenate(x)[good]  # noqa: E731
    return {"V": V, "T": T[good], "UV": sel(UVs), "N": fgdir_to_ue(sel(Ns)), "MK": sel(MKs), "DS": sel(DSs)}


def material_table(arr, texout: TexOut, part_name: str):
    """Group MK ids into OBJ materials: one per (texture, transparent, emissive); untextured by colour."""
    groups: dict[tuple, dict] = {}
    gid = np.zeros(len(arr["MK"]), np.int64)
    for mk in np.unique(arr["MK"]):
        tex, rgb, emis, trans, mname = MATKEYS[mk]
        tinfo = texout.png_for(tex) if tex else None
        transparent = trans > 0.05 or bool(tinfo and tinfo["alpha"])
        emissive = max(emis) > 0.3
        if tinfo:
            key = ("tex", tinfo["png"], transparent, emissive)
        else:
            key = ("col", rgb, transparent, emissive)
        if key not in groups:
            stem = (os.path.splitext(tinfo["png"])[0][4:] if tinfo else
                    "col_%02x%02x%02x" % tuple(int(round(c * 255)) for c in rgb))
            nm = f"M_{part_name[4:]}_{stem}" + ("_T" if transparent else "") + ("_E" if emissive else "")
            groups[key] = {"name": nm, "texture": tinfo["png"] if tinfo else None,
                           "kd": [round(c, 4) for c in (rgb if not tinfo else rgb)],
                           "emissive_rgb": [round(c, 4) for c in emis],
                           "opacity": round(1.0 - trans, 4), "transparent": transparent,
                           "emissive": emissive, "two_sided": False, "id": len(groups),
                           "ac_materials": set(), "triangles": 0, "texture_alpha": bool(tinfo and tinfo["alpha"])}
        g = groups[key]
        g["ac_materials"].add(mname)
        sel = arr["MK"] == mk
        gid[sel] = g["id"]
        g["triangles"] += int(sel.sum())
        if arr["DS"][sel].any():
            g["two_sided"] = True
    mats = sorted(groups.values(), key=lambda g: g["id"])
    for g in mats:
        g["ac_materials"] = sorted(g["ac_materials"])
    return mats, gid


_IMG_CACHE: dict[str, np.ndarray] = {}


def tri_colors(arr, mats, gid):
    """Preview helper: texture colour at each triangle's UV centroid, using the same convention the
    OBJ declares (v up -> image row = (1 - v) * H). Untextured -> Kd."""
    from PIL import Image
    out = np.zeros((len(arr["T"]), 3))
    uvc = arr["UV"].mean(axis=1)
    for g in mats:
        sel = gid == g["id"]
        if g["texture"]:
            if g["texture"] not in _IMG_CACHE:
                _IMG_CACHE[g["texture"]] = np.asarray(Image.open(OUT / g["texture"]).convert("RGB"), float) / 255
            img = _IMG_CACHE[g["texture"]]
            h, w = img.shape[:2]
            u = np.mod(uvc[sel, 0], 1.0)
            v = np.mod(uvc[sel, 1], 1.0)
            col = img[np.clip(((1 - v) * h).astype(int), 0, h - 1), np.clip((u * w).astype(int), 0, w - 1)]
            out[sel] = col * np.asarray(g["kd"])[None, :]
        else:
            out[sel] = np.asarray(g["kd"])
    return out


def write_obj(part_name: str, arr, mats, gid):
    obj_path = OUT / f"{part_name}.obj"
    mtl_path = OUT / f"{part_name}.mtl"
    P = ue_to_obj(arr["V"])
    N = ue_to_obj(arr["N"])
    T = arr["T"]
    UV = arr["UV"].reshape(-1, 2)
    Nc = N.reshape(-1, 3)
    uvq = np.round(UV, 6)
    uvu, uvi = np.unique(uvq, axis=0, return_inverse=True)
    nq = np.round(Nc, 4)
    nu, ni = np.unique(nq, axis=0, return_inverse=True)
    uvi = uvi.reshape(-1, 3)
    ni = ni.reshape(-1, 3)
    with open(mtl_path, "w", encoding="ascii", newline="\n") as f:
        f.write(f"# {part_name} - FlightGear F-16 ({REPO_URL} @ {SHA}), GPL-2.0\n")
        for g in mats:
            f.write(f"\nnewmtl {g['name']}\n")
            f.write("Ka 0 0 0\nKd %.4f %.4f %.4f\nKs 0.1 0.1 0.1\nNs 20\n" % tuple(g["kd"]))
            if g["emissive"]:
                f.write("Ke %.4f %.4f %.4f\n" % tuple(g["emissive_rgb"]))
            f.write(f"d {g['opacity']:.4f}\nillum 2\n")
            if g["texture"]:
                f.write(f"map_Kd {g['texture']}\n")
                if g["texture_alpha"]:
                    f.write(f"map_d {g['texture']}\n")
    order = np.argsort(gid, kind="stable")
    with open(obj_path, "w", encoding="ascii", newline="\n") as f:
        f.write(f"# {part_name} - converted from FlightGear F-16 ({REPO_URL} @ {SHA}), GPL-2.0-or-later\n")
        f.write("# OBJ axes (right-handed, Y up), centimetres: OBJ(x,y,z) = UE(X, Z, Y);"
                " UE body frame X fwd, Y right, Z up; FG eye at UE (430,0,100)\n")
        f.write("# Front faces CCW (right-handed). vt = AC3D uv unchanged (v up, OpenGL/OBJ convention)\n")
        f.write(f"mtllib {mtl_path.name}\no {part_name}\n")
        f.write("".join("v %.4f %.4f %.4f\n" % tuple(p) for p in P))
        f.write("".join("vt %.6f %.6f\n" % tuple(t) for t in uvu))
        f.write("".join("vn %.4f %.4f %.4f\n" % tuple(n) for n in nu))
        cur = -1
        lines = []
        for t in order:
            if gid[t] != cur:
                cur = gid[t]
                lines.append(f"g {mats[cur]['name']}\nusemtl {mats[cur]['name']}\n")
            a, b, c = T[t] + 1
            ua, ub, uc = uvi[t] + 1
            na, nb, nc = ni[t] + 1
            lines.append(f"f {a}/{ua}/{na} {b}/{ub}/{nb} {c}/{uc}/{nc}\n")
        f.write("".join(lines))
    return obj_path.name, mtl_path.name


# ----------------------------------------------------------------------------
# Pivots
# ----------------------------------------------------------------------------
def find_anim_center(repo: Repo, rp: str, prefer_axis=None):
    """Return list of (center_fg, axis, property, object-names) of rotate animations in an XML."""
    p = repo.get(rp)
    if p is None:
        return []
    root = ET.fromstring(p.read_bytes().decode("utf-8", errors="replace").lstrip("﻿"))
    res = []
    for a in root.findall("animation"):
        if (a.findtext("type") or "").strip() not in ("rotate", "translate"):
            continue
        axis, c = axis_center(a, root)
        res.append({"type": a.findtext("type").strip(), "center": None if c is None else c.tolist(),
                    "axis": None if axis is None else axis.tolist(),
                    "property": prop_name(a.find("property"), root) if a.find("property") is not None else "",
                    "factor": fnum(a, "factor", 1.0, root), "offset": fnum(a, "offset-deg", fnum(a, "offset-m", 0.0)),
                    "objects": [(e.text or "").strip() for e in a.findall("object-name")]})
    return res


# ----------------------------------------------------------------------------
# Previews (painter's algorithm with matplotlib PolyCollection)
# ----------------------------------------------------------------------------
def render(ax, arrs_colors, view, title="", light=(0.4, -0.5, 0.75), persp=None, alpha=1.0, zorder=1):
    """view: 3x3 rotation, rows = screen right, screen up, toward viewer (in UE frame).
    persp: dict(eye=..., fov=deg) for perspective."""
    from matplotlib.collections import PolyCollection
    polys, cols, depth = [], [], []
    L = np.asarray(light, float)
    L /= np.linalg.norm(L)
    for arr, base in arrs_colors:
        if arr is None:
            continue
        V, T = arr["V"], arr["T"]
        tri = V[T]                                  # (m,3,3) UE
        fn = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
        fn /= np.maximum(np.linalg.norm(fn, axis=1, keepdims=True), 1e-12)
        if persp is not None:
            rel = tri - persp["eye"]
            cam = rel @ view.T                      # x right, y up, z toward viewer (forward = -z)
            zf = -cam[..., 2]
            keep = (zf > 2.0).all(axis=1)
            cam, zf, fnk = cam[keep], zf[keep], fn[keep]
            tsel = np.nonzero(keep)[0]
            f = 1.0 / math.tan(math.radians(persp["fov"]) / 2)
            xy = np.stack([cam[..., 0] / zf * f, cam[..., 1] / zf * f], axis=-1)
            inside = (np.abs(xy) < 3).all(axis=(1, 2))
            xy, zf, fnk = xy[inside], zf[inside], fnk[inside]
            tsel = tsel[inside]
            d = zf.mean(axis=1)
            vdir = -(tri[keep][inside].mean(axis=1) - persp["eye"])
            vdir /= np.maximum(np.linalg.norm(vdir, axis=1, keepdims=True), 1e-9)
            sh = np.abs(np.einsum("ij,j->i", fnk, L))
            depth.append(-d)
        else:
            cam = tri @ view.T
            xy = cam[..., :2]
            d = cam[..., 2].mean(axis=1)
            sh = np.abs(np.einsum("ij,j->i", fn, L))
            depth.append(d)
            tsel = np.arange(len(T))
        shade = 0.35 + 0.65 * sh
        if isinstance(base, str):        # "tex": per-triangle texture colour sampled at the UV centroid
            c = np.clip(arr["tri_color"][tsel] * (0.45 + 0.55 * shade[:, None]), 0, 1)
        else:
            c = np.clip(np.asarray(base)[None, :] * shade[:, None], 0, 1)
        polys.append(xy)
        cols.append(c)
    if not polys:
        return
    P = np.concatenate(polys)
    C = np.concatenate(cols)
    D = np.concatenate(depth)
    o = np.argsort(D)
    pc = PolyCollection(P[o], facecolors=C[o], edgecolors="none", antialiaseds=False, alpha=alpha,
                        zorder=zorder)
    ax.add_collection(pc)
    ax.set_aspect("equal")
    ax.autoscale_view()
    ax.set_title(title, fontsize=9)


def look_rot(fwd, up=(0, 0, 1)):
    f = np.asarray(fwd, float)
    f /= np.linalg.norm(f)
    u = np.asarray(up, float)
    # UE is left-handed: right = up x fwd  (X fwd, Y right, Z up => Z x X = Y)
    r = np.cross(u, f)
    r /= np.linalg.norm(r)
    u2 = np.cross(f, r)
    # screen: right, up, toward viewer (-fwd); screen x must increase to viewer's right
    return np.stack([r, u2, -f])


def previews(arrays: dict, info: dict):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    ext = [(arrays.get("F16_Exterior"), (0.75, 0.77, 0.80)), (arrays.get("F16_Gear"), (0.30, 0.30, 0.32)),
           (arrays.get("F16_Glass"), (0.45, 0.70, 0.95))]
    views = {
        # name: (rotation rows screen-right, screen-up, toward-viewer) in UE frame, viewer looks along -row3
        "side": look_rot((0, 1, 0)),           # looking toward +Y (from left side) -> nose at screen left? see title
        "top": np.array([[0, 1, 0], [1, 0, 0], [0, 0, 1.0]]),     # from above, nose up, right wing right
        "front": look_rot((-1, 0, 0)),         # looking aft at the nose: aircraft right on screen left
        "34": look_rot((-0.6, 0.55, -0.45)),
    }
    titles = {"side": "SIDE view from LEFT (looking +Y): nose at screen left", "top": "TOP view (nose up, right wing right)",
              "front": "FRONT view (looking aft; aircraft RIGHT wing on screen LEFT)", "34": "3/4 view from front-left-above"}
    for k, R in views.items():
        fig, ax = plt.subplots(figsize=(12, 8), dpi=110)
        render(ax, ext, R, titles[k])
        ax.set_xlabel("screen right [cm]")
        ax.grid(alpha=0.2)
        fig.tight_layout()
        fig.savefig(OUT / f"preview_exterior_{k}.png")
        plt.close(fig)
        if k not in ("side", "34", "top"):
            continue
        fig, ax = plt.subplots(figsize=(12, 8), dpi=110)
        render(ax, [(arrays.get("F16_Exterior"), "tex"), (arrays.get("F16_Gear"), "tex"),
                    (arrays.get("F16_Glass"), (0.45, 0.70, 0.95))], R,
               titles[k] + " - colour = texture sampled at UV centroid (checks UV/V-flip)")
        ax.grid(alpha=0.2)
        fig.tight_layout()
        fig.savefig(OUT / f"preview_exterior_{k}_tex.png")
        plt.close(fig)

    # cockpit from the eye (two pitches)
    ck = [(arrays.get("F16_Cockpit"), "tex"), (arrays.get("F16_Exterior"), (0.75, 0.77, 0.80))]
    ctl = [(arrays.get("F16_Stick"), (0.9, 0.2, 0.2)), (arrays.get("F16_Throttle"), (0.2, 0.8, 0.2)),
           (arrays.get("F16_PedalL"), (0.2, 0.4, 1.0)), (arrays.get("F16_PedalR"), (1.0, 0.6, 0.1))]
    for deg, fname in ((15, "preview_cockpit_eye.png"), (40, "preview_cockpit_eye_down40.png")):
        pitch = math.radians(-deg)
        R = look_rot((math.cos(pitch), 0, math.sin(pitch)))
        fig, ax = plt.subplots(figsize=(12, 9), dpi=110)
        render(ax, ck + ctl, R, f"Cockpit from FG eye (UE 430,0,100), {deg} deg down, 75 deg HFOV; "
               "red=stick green=throttle blue/orange=pedals L/R (glass hidden)", persp={"eye": EYE_UE, "fov": 75})
        ax.set_xlim(-1, 1)
        ax.set_ylim(-0.75, 0.75)
        fig.tight_layout()
        fig.savefig(OUT / fname)
        plt.close(fig)

    # controls overlay: cockpit faint in the background, controls drawn on top
    TOP = np.array([[0, 1, 0], [1, 0, 0], [0, 0, 1.0]])
    SIDE = look_rot((0, 1, 0))
    fig, axs = plt.subplots(1, 2, figsize=(16, 8), dpi=100)
    for a, R, ttl in ((axs[0], SIDE, "Controls, side view from LEFT (nose left)"),
                      (axs[1], TOP, "Controls, top view (nose up, aircraft right = screen right)")):
        render(a, [(arrays.get("F16_Cockpit"), (0.92, 0.92, 0.92))], R, ttl, alpha=0.35)
        render(a, ctl, R, ttl + " | red stick, green throttle, blue PedalL, orange PedalR, + = pivot", zorder=3)
        a.grid(alpha=0.3)
        for nm, pv in info.get("pivots", {}).items():
            s = R @ np.asarray(pv, float)
            a.plot(s[0], s[1], "k+", ms=16, mew=2, zorder=5)
            a.annotate(nm, (s[0], s[1]), fontsize=7, zorder=5)
        s = R @ EYE_UE
        a.plot(s[0], s[1], "mo", zorder=5)
        a.annotate("eye", (s[0], s[1]), zorder=5)
    axs[0].set_xlim(-(EYE_UE[0] + 130), -(EYE_UE[0] - 70))
    axs[0].set_ylim(-20, 120)
    axs[1].set_xlim(-70, 70)
    axs[1].set_ylim(EYE_UE[0] - 40, EYE_UE[0] + 120)
    fig.tight_layout()
    fig.savefig(OUT / "preview_controls.png")
    plt.close(fig)


# ----------------------------------------------------------------------------
# main
# ----------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--no-preview", action="store_true")
    args = ap.parse_args()
    t0 = time.time()
    OUT.mkdir(parents=True, exist_ok=True)
    for old in OUT.glob("*"):
        if old.is_file() and (old.suffix in (".obj", ".mtl") or old.name.startswith(("tex_", "preview_"))):
            old.unlink()
    repo = Repo()
    texres = TexResolver(repo)
    loader = Loader(repo, texres, skip_model)
    root = loader.load("Models/F-16.xml", ())
    parts, dropped = collect(root)

    arrays = {}
    for nm, part in parts.items():
        arrays[nm] = build_part_arrays(part) if part.chunks else None

    # split pedals into L/R by UE y sign (left = negative Y)
    ped = arrays.pop("F16_Pedals", None)
    if ped is not None:
        cen = ped["V"][ped["T"]].mean(axis=1)[:, 1]
        for side, sel in (("F16_PedalL", cen < 0), ("F16_PedalR", cen >= 0)):
            arrays[side] = {k: (v[sel] if k != "V" else v) for k, v in ped.items()}
    texout = TexOut(repo)

    # pivots from animation centers
    pivots = {}
    pivot_src = {}
    stick_rp, thr_rp, ped_rp = "Models/Cockpit/Main/stick.xml", "Models/Cockpit/throttle.xml", \
        "Models/Cockpit/rudder_pedals.xml"
    ckroot = loader.parse_xml("Models/Cockpit/Main/cockpit.xml")

    def model_offsets(name):
        for m in ckroot.findall("model"):
            if (m.findtext("name") or "").strip() == name and (m.find("condition") is None or eval_cond(m.find("condition"), ckroot)):
                return offsets_matrix(m.find("offsets"), ckroot)
        return np.eye(4)

    for pname, rp, mname in (("F16_Stick", stick_rp, "F-16-FS"), ("F16_Throttle", thr_rp, "Throttle"),
                             ("F16_Pedals", ped_rp, "RudderPedals")):
        an = [a for a in find_anim_center(repo, rp) if a["type"] == "rotate" and a["center"] is not None]
        M = model_offsets(mname)
        for a in find_anim_center(repo, rp):
            a["center_ue_cm"] = None if a["center"] is None else                 fg_to_ue(M[:3, :3] @ np.array(a["center"]) + M[:3, 3]).round(3).tolist()
            a["axis_ue"] = None if a["axis"] is None else                 fgdir_to_ue(M[:3, :3] @ np.array(a["axis"])).round(5).tolist()
            pivot_src.setdefault(pname, {"xml": rp, "offsets_model": mname, "animations": []})["animations"].append(a)
        if pname == "F16_Pedals":
            # one center per pedal side if present, else mirror
            cs = [np.array(a["center"]) for a in an]
            for side, sgn in (("F16_PedalL", -1), ("F16_PedalR", 1)):
                arr = arrays.get(side)
                c = None
                for cc in cs:
                    w = (M[:3, :3] @ cc + M[:3, 3])
                    if np.sign(w[1]) == sgn and abs(w[1]) > 1e-3:
                        c = w
                if c is None and cs:
                    w = M[:3, :3] @ cs[0] + M[:3, 3]
                    c = w.copy()
                    if arr is not None:
                        c[1] = (arr["V"][np.unique(arr["T"])][:, 1].mean() / 100.0)
                if c is not None:
                    pivots[side] = fg_to_ue(c).round(3).tolist()
                    if arr is not None and abs(c[1]) < 1e-6:
                        pv = np.array(pivots[side])
                        pv[1] = arr["V"][np.unique(arr["T"])][:, 1].mean()
                        pivots[side] = pv.round(3).tolist()
        elif an:
            c = np.array(an[0]["center"])
            pivots[pname] = fg_to_ue(M[:3, :3] @ c + M[:3, 3]).round(3).tolist()

    # write parts
    manifest_parts = []
    for nm in ["F16_Exterior", "F16_Glass", "F16_Gear", "F16_Cockpit", "F16_Stick", "F16_Throttle",
               "F16_PedalL", "F16_PedalR"]:
        arr = arrays.get(nm)
        if arr is None or not len(arr["T"]):
            log(f"[warn] part {nm} is empty")
            continue
        mats, gid = material_table(arr, texout, nm)
        arr["tri_color"] = tri_colors(arr, mats, gid)
        objn, mtln = write_obj(nm, arr, mats, gid)
        used = arr["V"][np.unique(arr["T"])]
        src_part = "F16_Pedals" if nm.startswith("F16_Pedal") else nm
        manifest_parts.append({
            "name": nm, "obj": objn, "mtl": mtln, "triangles": int(len(arr["T"])),
            "vertices": int(len(used)),
            "bbox_ue_cm": {"min": used.min(0).round(2).tolist(), "max": used.max(0).round(2).tolist()},
            "pivot_ue_cm": pivots.get(nm),
            "materials": [{k: g[k] for k in ("name", "texture", "kd", "opacity", "two_sided", "transparent",
                                             "emissive", "triangles", "ac_materials")} for g in mats],
            "source_objects": sorted(set(parts[src_part].objects)) if src_part in parts else [],
        })
        log(f"{nm}: {len(arr['T'])} tris, bbox {used.min(0).round(1)} .. {used.max(0).round(1)}")

    # tire bottom
    tire_z = None
    gear = arrays.get("F16_Gear")
    tire_nodes = [n for n, _ in parts["F16_Gear"].chunks if re.search("Tire|Wheel", n.name)]
    if tire_nodes:
        tz = min(fg_to_ue(n.V[np.unique(n.T)])[:, 2].min() for n in tire_nodes)
        tire_z = round(float(tz), 2)
    elif gear is not None:
        tire_z = round(float(gear["V"][:, 2].min()), 2)

    # license files
    for lf in ("LICENSE", "copyright.txt", "authors.txt"):
        p = repo.get(lf)
        if p is not None:
            shutil.copyfile(p, OUT / lf)

    allv = np.concatenate([arrays[n]["V"][np.unique(arrays[n]["T"])] for n in ("F16_Exterior", "F16_Gear", "F16_Glass")
                           if arrays.get(n) is not None])
    ext_dims = (allv.max(0) - allv.min(0)).round(1).tolist()
    manifest = {
        "made": _dt.datetime.now().astimezone().isoformat(timespec="seconds"),
        "script": "Scripts/fetch_f16_model.py",
        "source": {"repo": REPO_URL, "commit": SHA, "raw": RAW + "<path>", "license": "GPL-2.0-or-later",
                   "license_files": ["LICENSE", "copyright.txt", "authors.txt"],
                   "root_model": "Models/F-16.xml", "files_used": sorted(set(loader.loaded))},
        "property_state": {k: v for k, v in PROPS.items()},
        "convention": {
            "ue_frame": "Unreal body frame, centimetres, X forward, Y right, Z up (left-handed)",
            "fg_frame": "FlightGear model frame, metres, x aft, y right, z up (right-handed)",
            "ac_to_fg": "fg(x,y,z) = ac(x, -z, y)",
            "fg_to_ue": "ue_x = (-x_fg - 4.105)*100 + 430 ; ue_y = y_fg*100 ; ue_z = (z_fg - 0.8579)*100 + 100",
            "obj_axes": "OBJ(x, y, z) = UE(X, Z, Y)  i.e. obj +x = UE forward, obj +y = UE up, obj +z = UE right",
            "obj_handedness": "right-handed Y-up (standard OBJ); front faces CCW seen from outside",
            "expected_unreal_mapping": "UE(X,Y,Z) = (obj_x, obj_z, obj_y): this is what UE's OBJ/FBX-style import "
                                       "does for a Y-up right-handed file (same as Blender OBJ export with "
                                       "Forward -Z / Up Y)",
            "units": "1 OBJ unit = 1 cm (no scaling needed)",
            "uv": "vt = AC3D (u,v) unchanged: v=0 is the BOTTOM of the image (OpenGL/OBJ convention); "
                  "PNG files are ordinary top-row-first images. Unreal's importer flips V itself (v_ue = 1 - v).",
            "unreal_import": {
                "uniform_scale": 1.0, "import_rotation_deg": [0, 0, 0], "import_translation": [0, 0, 0],
                "convert_scene": True, "force_front_x_axis": False, "convert_scene_unit": False,
                "combine_meshes": True, "normals": "import normals (do not recompute)",
                "verify": "After import: nose at +X (~+1000 cm), fin top at +Z, throttle (F16_Throttle) at "
                          "Y < 0 (LEFT console, about -49 cm), eye reference (430,0,100). If the throttle "
                          "ends up at +Y the importer mirrored Y: set import scale (1,-1,1) or rotate; if the "
                          "aircraft is lying on its side the importer did not swap Y/Z: use import rotation "
                          "(roll) 90 deg."},
            "eye_ue_cm": EYE_UE.tolist(), "eye_fg_m": EYE_FG.tolist(),
        },
        "eye_ue_cm": EYE_UE.tolist(),
        "tire_bottom_z_ue_cm": tire_z,
        "pivots_ue_cm": pivots,
        "pivot_sources": pivot_src,
        "exterior_dims_ue_cm": {"length_x": ext_dims[0], "span_y": ext_dims[1], "height_z": ext_dims[2]},
        "parts": manifest_parts,
        "dropped_objects": dict(sorted(dropped.items())),
        "dropped_invisible_triangles": dict(sorted(INVISIBLE_DROPPED.items())),
        "skipped_models": loader.skipped,
        "external_or_missing_models": sorted(set(loader.external)),
        "missing_textures": sorted(texres.missing),
        "textures": {k: v for k, v in texout.done.items() if v},
        "download": {"files_this_run": repo.downloaded, "bytes_this_run": repo.bytes,
                     "cache_bytes_total": sum(p.stat().st_size for p in SRC.rglob("*") if p.is_file())},
    }
    info = {"pivots": pivots}
    if not args.no_preview:
        previews(arrays, info)
        manifest["previews"] = sorted(p.name for p in OUT.glob("preview_*.png"))
    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    log(f"exterior dims (cm) L/span/H: {ext_dims}; tire bottom z: {tire_z}; pivots: {pivots}")
    log(f"downloaded {repo.downloaded} files / {repo.bytes/1e6:.1f} MB this run; done in {time.time()-t0:.0f} s")


if __name__ == "__main__":
    main()
