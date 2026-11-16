"""Seated jet-pilot pose for the UE5 mannequin (Manny), computed outside Unreal (plain Python + numpy):

    python Scripts/pilot/manny_pose.py --mesh <manny_mesh.json> [--out <manny_posed.json>] [--obj <preview.obj>]

Input  manny_mesh.json  (written by Scripts/pilot/ue_manny.py step "dump", from /Game/ThirdParty/Mannequins - Epic
       content, never in git): reference-pose vertices / triangles / skin weights of SKM_Manny_Simple LOD0 and the
       component-space reference bone positions.
Output manny_posed.json: posed vertex positions in the aircraft body frame (UE cm, X fwd, Y right, Z up; the mesh is
       attached to the Aircraft actor like the old PilotBody), a material class per triangle (0 suit, 1 G-suit trousers,
       2 gloves, 3 boots, 4 harness) and the triangles to drop (head: the first-person eye sits there; the PilotHead
       helmet actor still stands in for it outside the cockpit view). ue_manny.py step "build" turns it into the static
       mesh /Game/ThirdParty/Mannequins/SM_PilotManny.

The pose is plain forward kinematics on Manny's reference skeleton: every bone gets a rotation about its joint (world
delta), children follow, vertices are linear-blend skinned with Manny's own weights. Arms and legs are two-bone IK with
the elbow / knee hinge kept in Manny's own bend plane. Targets come from the cockpit layout (Scripts/cockpit_blender/
ck2_layout.py and the level): eye (430, 0, 100), sidestick grip (right hand), throttle grip (left hand), left thigh
under the kneeboard (454, -14, 53.2, ck2_model.KNEE), feet toward the rudder pedals (hinge 489.9, +-13.5, -12).
"""
import argparse
import json
import math
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "cockpit_blender"))
import ck2_layout as L          # noqa: E402

EYE = np.array(L.EYE, float)                      # (430, 0, 100)
SCALE = 0.92                                      # Manny is ~1.80 m; the rig eye / seat / kneeboard fit a ~1.70 m pilot
# torso: pitch of each segment (deg, + = top leans back). The seat back is 15 deg; F-16 pilots sit a bit forward of it.
LEAN = dict(pelvis=5.0, spine_01=5.0, spine_02=9.0, spine_03=18.0, spine_04=18.0, spine_05=18.0, neck_01=-30.0, neck_02=-30.0, head=0.0)
PROTRACT = 14.0                                   # shoulders forward (deg about the vertical, at the clavicles)
KNEE_BOARD = np.array((454.0, -14.0, 53.2))       # ck2_model.KNEE centre (board face); slab back 0.9 cm under it
THIGH_CLEAR = 1.2                                 # cm between the thigh top and the board back
PEDAL_HINGE_X, PEDAL_HINGE_Z, PEDAL_Y, PEDAL_LEAN = 489.9, -12.0, 13.5, 20.0
STICK = L.STICK_SIDE                              # sidestick (cockpit_v2 default GYROSIM_CK2_STICK=side)
THR = L.THR
HEAD_BONES = ("head",)                            # triangles skinned mostly to these are dropped


# ---- small rotation helpers (3x3 matrices) ---------------------------------------------------------------------------
def unit(v):
    v = np.asarray(v, float)
    n = np.linalg.norm(v)
    return v / n if n > 1e-9 else v


def rot(axis, deg):
    a = unit(axis)
    t = math.radians(deg)
    K = np.array([[0, -a[2], a[1]], [a[2], 0, -a[0]], [-a[1], a[0], 0]])
    return np.eye(3) + math.sin(t) * K + (1 - math.cos(t)) * K @ K


def frame(d, h):
    """orthonormal frame (columns): x = d, y = h made perpendicular to d, z = x cross y"""
    x = unit(d)
    y = unit(np.asarray(h, float) - x * np.dot(h, x))
    return np.column_stack([x, y, np.cross(x, y)])


def map_frames(d0, h0, d1, h1):
    """rotation taking direction d0 (with hint h0) onto d1 (hint h1)"""
    return frame(d1, h1) @ frame(d0, h0).T


def twist_angle(R, axis):
    """signed angle of the twist part of rotation R about `axis`"""
    a = unit(axis)
    p = unit(np.cross(a, [0.3, 0.5, 0.8]) if abs(np.dot(a, unit([0.3, 0.5, 0.8]))) < 0.95 else np.cross(a, [1, 0, 0]))
    q = R @ p
    q = q - a * np.dot(q, a)
    return math.degrees(math.atan2(np.dot(np.cross(p, q), a), np.dot(p, q)))


# ---- skeleton -------------------------------------------------------------------------------------------------------
class Skel:
    def __init__(self, names, parents, ref_pos, scale):
        self.names, self.parent = names, parents
        self.idx = {n: i for i, n in enumerate(names)}
        # Manny component space: x = character LEFT, y = forward, z = up -> aircraft frame X fwd, Y right, Z up
        self.ref = np.array([(p[1], -p[0], p[2]) for p in ref_pos], float) * scale
        self.D = [None] * len(names)            # world delta rotation per bone (None = inherit parent)
        self.pos = None
        self.Dw = None

    def ch(self, n):
        return [m for m in self.names if self.parent[self.idx[m]] == self.idx[n]]

    def set(self, n, R):
        self.D[self.idx[n]] = R

    def solve(self, root_pos):
        """FK: positions / deltas of all bones (root moved to root_pos)."""
        n = len(self.names)
        pos, Dw = np.zeros((n, 3)), [None] * n
        for i in range(n):                       # names are in hierarchy order (parent first)
            p = self.parent[i]
            if p < 0:
                Dw[i] = self.D[i] if self.D[i] is not None else np.eye(3)
                pos[i] = root_pos
            else:
                Dw[i] = self.D[i] if self.D[i] is not None else Dw[p]
                pos[i] = pos[p] + Dw[p] @ (self.ref[i] - self.ref[p])
        self.pos, self.Dw = pos, Dw
        return pos

    def p(self, n):
        return self.pos[self.idx[n]]

    def r(self, n):
        return self.ref[self.idx[n]]


def two_bone(a, l1, l2, target, pole):
    """joint position for a two-bone chain from a to target (clamped to reach), bending toward pole"""
    d = target - a
    dist = np.linalg.norm(d)
    dist_c = min(dist, (l1 + l2) * 0.999)
    dn = unit(d)
    t = target if dist <= dist_c else a + dn * dist_c
    x = (l1 * l1 - l2 * l2 + dist_c * dist_c) / (2 * dist_c)
    h = math.sqrt(max(0.0, l1 * l1 - x * x))
    pv = unit(pole - dn * np.dot(pole, dn))
    return a + dn * x + pv * h, t, dist - dist_c


# ---- the pose -------------------------------------------------------------------------------------------------------
def pose(S, eye_local, verbose=True):
    """S: Skel (reference scaled). eye_local: Manny's eye in the scaled aircraft-oriented ref frame."""
    info = {}
    Y = np.array([0.0, 1.0, 0.0])
    # torso: lean each segment back about the aircraft Y axis (rot about +Y by +a moves +Z toward +X, so lean = -a)
    for n, a in LEAN.items():
        S.set(n, rot(Y, -a))
    S.set("root", np.eye(3))
    S.solve(np.zeros(3))
    R5 = S.Dw[S.idx["spine_05"]]
    S.set("clavicle_r", rot([0, 0, 1], -PROTRACT) @ R5)        # right shoulder (+Y) forward = about -Z... checked below
    S.set("clavicle_l", rot([0, 0, 1], PROTRACT) @ R5)
    head_i = S.idx["head"]
    eye_now = S.pos[head_i] + S.Dw[head_i] @ (eye_local - S.r("head"))
    root = EYE - eye_now                          # put the eye exactly on the design eye
    S.solve(root)

    # ---- legs: left thigh under the kneeboard, knees apart, feet toward the pedals
    plate_up = np.array([math.sin(math.radians(PEDAL_LEAN)), 0.0, math.cos(math.radians(PEDAL_LEAN))])
    plate_n = np.array([-math.cos(math.radians(PEDAL_LEAN)), 0.0, math.sin(math.radians(PEDAL_LEAN))])   # toward the pilot
    for sd, s in (("l", -1.0), ("r", 1.0)):
        hip = S.p("thigh_" + sd)
        l1 = np.linalg.norm(S.r("calf_" + sd) - S.r("thigh_" + sd))
        l2 = np.linalg.norm(S.r("foot_" + sd) - S.r("calf_" + sd))
        knee = np.array([KNEE_X, s * KNEE_Y, KNEE_Z])
        knee = hip + unit(knee - hip) * l1
        ball_t = np.array([PEDAL_HINGE_X, s * PEDAL_Y, PEDAL_HINGE_Z]) + plate_up * BALL_UP + plate_n * 2.5
        # foot frame on the plate: heel->toe along plate_up tilted back by FOOT_TILT, sole facing the plate
        fdir = unit(rot(np.cross(plate_up, plate_n), -FOOT_TILT) @ plate_up)
        fr = S.r("ball_" + sd) - S.r("foot_" + sd)
        ref_fd, ref_up = unit(fr), np.array([0.0, 0.0, 1.0])
        up_t = unit(np.cross(np.cross(fdir, plate_n), fdir)) if False else unit(plate_n - fdir * np.dot(plate_n, fdir))
        Rf = map_frames(ref_fd, ref_up, fdir, up_t)
        ankle_t = ball_t - Rf @ fr
        d = ankle_t - knee
        ankle = knee + unit(d) * l2
        info["ankle_miss_" + sd] = round(float(np.linalg.norm(d) - l2), 1)
        lat_ref = np.array([0.0, -1.0, 0.0])                     # knee hinge in the reference (straight legs)
        thigh_ref = S.r("calf_" + sd) - S.r("thigh_" + sd)
        calf_ref = S.r("foot_" + sd) - S.r("calf_" + sd)
        hinge = unit(np.cross(ankle - knee, knee - hip))
        if np.dot(hinge, lat_ref) < 0:
            hinge = -hinge
        S.set("thigh_" + sd, map_frames(thigh_ref, lat_ref, knee - hip, hinge))
        S.set("calf_" + sd, map_frames(calf_ref, lat_ref, ankle - knee, hinge))
        S.set("foot_" + sd, Rf)
    S.solve(root)

    # ---- arms: right hand on the sidestick grip, left hand on the throttle grip
    lean = math.radians(STICK["lean"])
    sp = np.array(STICK["pivot"], float)
    g_axis = np.array([math.sin(lean), 0.0, math.cos(lean)])
    grip_r = sp + g_axis * (-2.7 + 5.2 + 4.2) + np.array([0.6, -0.2, 0.0])     # ck2_model.build_stick grip middle
    tp = np.array(THR["pivot"], float)
    grip_l = tp + np.array([0.8, -1.6, 10.5])                                 # ck2_model.build_throttle grip body centre
    targets = {
        # side: (grip centre, finger direction, palm normal (toward the grip), offset of the palm centre from the grip)
        "r": (grip_r, unit([1.0, 0.0, -0.25]), unit([0.0, -1.0, 0.15]), HAND_R_OFF),
        "l": (grip_l, unit([1.0, 0.0, -0.25]), unit([0.0, 0.55, -1.0]), HAND_L_OFF),
    }
    poles = {"r": unit([-0.4, 1.0, -0.9]), "l": unit([-0.4, -1.0, -0.9])}
    for sd, (g, fd_t, palm_t, off) in targets.items():
        h, m1 = S.r("hand_" + sd), S.r("middle_01_" + sd)
        fd0 = unit(m1 - h)
        tip = S.r("middle_03_" + sd) - m1
        palm0 = unit(tip - fd0 * np.dot(tip, fd0))                           # fingers curl toward the palm
        Rh = map_frames(fd0, palm0, fd_t, palm_t)
        palm_c = h + (m1 - h) * 0.55                                        # palm centre in the reference
        wrist_t = g + np.asarray(off) - Rh @ (palm_c - h)
        sh = S.p("upperarm_" + sd)
        l1 = np.linalg.norm(S.r("lowerarm_" + sd) - S.r("upperarm_" + sd))
        l2 = np.linalg.norm(S.r("hand_" + sd) - S.r("lowerarm_" + sd))
        elbow, wr, miss = two_bone(sh, l1, l2, wrist_t, poles[sd])
        info["wrist_miss_" + sd] = round(float(miss), 1)
        u0, f0 = S.r("lowerarm_" + sd) - S.r("upperarm_" + sd), S.r("hand_" + sd) - S.r("lowerarm_" + sd)
        hinge0 = unit(np.cross(u0, f0))
        hinge1 = unit(np.cross(elbow - sh, wr - elbow))
        Ru = map_frames(u0, hinge0, elbow - sh, hinge1)
        Rl = map_frames(f0, hinge0, wr - elbow, hinge1)
        S.set("upperarm_" + sd, Ru)
        S.set("lowerarm_" + sd, Rl)
        S.set("hand_" + sd, Rh)
        # forearm twist bones take part of the wrist twist (no candy-wrapper wrist)
        tw = twist_angle(Rh @ Rl.T, wr - elbow)
        info["wrist_twist_" + sd] = round(tw, 1)
        for tb in ("lowerarm_twist_01_", "lowerarm_twist_02_"):
            n = tb + sd
            k = np.linalg.norm(S.r(n) - S.r("lowerarm_" + sd)) / max(1e-6, l2)
            S.set(n, rot(wr - elbow, tw * min(1.0, k)) @ Rl)
        # fingers: curl about the knuckle line (index -> pinky), thumb a little
        lat0 = unit(S.r("index_01_" + sd) - S.r("pinky_01_" + sd))
        axis_ref = unit(np.cross(fd0, palm0))                                # rotating fd0 toward palm0 about this
        for f, curls in (FINGER_CURL if sd == "r" else FINGER_CURL_L).items():
            acc = 0.0
            for j, c in zip(("_01_", "_02_", "_03_"), curls):
                acc += c
                S.set(f + j + sd, Rh @ rot(axis_ref, acc))
        acc = 0.0
        for j, c in zip(("_01_", "_02_", "_03_"), THUMB_CURL):
            acc += c
            S.set("thumb" + j + sd, Rh @ rot(fd0, THUMB_ROLL[sd]) @ rot(axis_ref, acc))
    S.solve(root)
    info["root"] = [round(float(x), 1) for x in root]
    for n in ("pelvis", "thigh_l", "thigh_r", "calf_l", "calf_r", "foot_l", "ball_l", "upperarm_r", "lowerarm_r", "hand_r", "hand_l", "neck_01", "head"):
        info["at_" + n] = [round(float(x), 1) for x in S.p(n)]
    return info


# tunables found with the previews (numbers in aircraft cm / deg)
KNEE_X, KNEE_Y, KNEE_Z = 470.0, 15.0, 48.0
BALL_UP, FOOT_TILT = 16.0, 25.0
HAND_R_OFF = (0.0, 3.6, 0.0)          # palm centre right of the grip axis (hand wraps it from the right)
HAND_L_OFF = (-1.0, -2.5, 7.9)        # palm centre on top of the throttle grip body, a little outboard
FINGER_CURL = dict(index=(55.0, 60.0, 35.0), middle=(60.0, 65.0, 35.0), ring=(65.0, 65.0, 35.0), pinky=(70.0, 65.0, 35.0))
THUMB_CURL = (35.0, 25.0, 15.0)
THUMB_ROLL = dict(r=-20.0, l=15.0)    # thumb swung up over the grip head (deg about the finger direction)
FINGER_CURL_L = dict(index=(35.0, 40.0, 25.0), middle=(40.0, 40.0, 25.0), ring=(45.0, 40.0, 25.0), pinky=(50.0, 40.0, 25.0))


def back_pen(X):
    """how far body points are behind the seat back cushion front (ck2_model.build_seat: back(z, 4..5.5), 15 deg)"""
    z = X[:, 2]
    xb = 408.0 - (z - 26.0) * math.tan(math.radians(15.0)) + 5.0
    m = (z > 30.0) & (z < 95.0) & (np.abs(X[:, 1]) < 18.0)
    return np.where(m, xb - X[:, 0], -99.0)


def weight_matrix(W, nb):
    Wm = np.zeros((len(W), nb))
    for v, ws in enumerate(W):
        for bi, w in ws:
            Wm[v, bi] += w
    return Wm


def skin(S, P, Wm, bone_names_mesh):
    """linear blend skinning of the scaled aircraft-oriented reference vertices (Wm: vertices x mesh bones)"""
    out = np.zeros_like(P)
    for bi, n in enumerate(bone_names_mesh):
        w = Wm[:, bi]
        nz = w > 0
        if not nz.any():
            continue
        b = S.idx[n]
        out[nz] += w[nz, None] * (S.pos[b] + (P[nz] - S.ref[b]) @ S.Dw[b].T)
    return out


def classify(S, W, bone_names_mesh, Pref, T):
    """material class per triangle from the dominant bone of its vertices (+ reference-pose position)"""
    dom = []
    for v in range(len(W)):
        bi, _ = max(W[v], key=lambda x: x[1])
        dom.append(bone_names_mesh[bi])
    head = np.array([d in HEAD_BONES for d in dom])
    hand = np.array([d.startswith(("hand_", "index", "middle", "ring", "pinky", "thumb")) for d in dom])
    foot = np.array([d.startswith(("foot_", "ball_")) for d in dom]) | (Pref[:, 2] < 13.0 * SCALE)
    legs = np.array([d.startswith(("thigh", "calf")) for d in dom])
    cls, drop = [], []
    for ti, (a, b, c) in enumerate(T):
        vs = (a, b, c)
        if sum(head[v] for v in vs) >= 2:
            drop.append(ti)
            cls.append(0)
            continue
        if sum(hand[v] for v in vs) >= 2:
            cls.append(2)
        elif sum(foot[v] for v in vs) >= 2:
            cls.append(3)
        elif sum(legs[v] for v in vs) >= 2:
            cls.append(1)
        else:
            cls.append(0)
    return cls, drop


def cap_holes(X, T, keep, cls):
    """close the open loops left by the dropped head (fan to the loop centre); returns new X, T, cls, keep"""
    from collections import defaultdict
    cnt, nxt = defaultdict(int), {}
    for ti, t in enumerate(T):
        if not keep[ti]:
            continue
        for a, b in ((t[0], t[1]), (t[1], t[2]), (t[2], t[0])):
            cnt[(min(a, b), max(a, b))] += 1
            nxt[(a, b)] = True
    bnd = {}
    for (a, b) in nxt:                                     # boundary half-edges: edge used once
        if cnt[(min(a, b), max(a, b))] == 1:
            bnd[b] = a                                     # walk the loop against the body edges: the cap faces outward
    X, T, cls, keep = list(map(list, X)), [list(t) for t in T], list(cls), list(keep)
    seen, loops = set(), []
    for s0 in list(bnd):
        if s0 in seen:
            continue
        loop, v = [], s0
        while v not in seen and v in bnd:
            seen.add(v)
            loop.append(v)
            v = bnd[v]
        if len(loop) >= 3:
            loops.append(loop)
    for loop in loops:
        c = np.mean([X[v] for v in loop], axis=0)
        ci = len(X)
        X.append(list(c))
        for i in range(len(loop)):
            T.append([loop[i], loop[(i + 1) % len(loop)], ci])
            cls.append(0)
            keep.append(True)
    return np.array(X), T, cls, np.array(keep), len(loops)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mesh", required=True)
    ap.add_argument("--out")
    ap.add_argument("--obj")
    a = ap.parse_args()
    D = json.load(open(a.mesh, encoding="utf-8"))
    names = [b["name"] for b in D["bones"]]
    parents = [b["parent"] for b in D["bones"]]
    S = Skel(names, parents, [D["ref_bones"][n] for n in names], SCALE)
    P = np.array([(p[1], -p[0], p[2]) for p in D["P"]], float) * SCALE
    T = D["T"]
    # Manny's eye: front of the face at eye height, 2.5 cm in from the surface
    hz = (S.r("head")[2] + 7.0 * SCALE)
    sel = (np.abs(P[:, 2] - hz) < 1.0 * SCALE) & (np.abs(P[:, 1]) < 2.0 * SCALE)
    eye_local = np.array([P[sel, 0].max() - 2.5 * SCALE, 0.0, hz])
    Wm = weight_matrix(D["W"], len(names))
    cls, drop = classify(S, D["W"], names, P, T)
    keep = np.ones(len(T), bool)
    keep[drop] = False
    used = np.unique(np.array(T)[keep].ravel())
    inuse = np.zeros(len(P), bool)
    inuse[used] = True
    global KNEE_Z
    lo, hi = 25.0, 80.0                      # knee height so the left thigh top sits THIGH_CLEAR under the kneeboard back
    for _ in range(14):
        KNEE_Z = (lo + hi) / 2
        info = pose(S, eye_local)
        X = skin(S, P, Wm, names)
        kb = inuse & (X[:, 0] > KNEE_BOARD[0] - 10) & (X[:, 0] < KNEE_BOARD[0] + 10) & (np.abs(X[:, 1] - KNEE_BOARD[1]) < 6)
        top = X[kb, 2].max()
        if top > KNEE_BOARD[2] - 0.9 - THIGH_CLEAR:
            hi = KNEE_Z
        else:
            lo = KNEE_Z
    info["knee_z_target"] = round(KNEE_Z, 1)
    info["eye_local"] = [round(float(x), 1) for x in eye_local]
    info["near_eye_cm"] = round(float(np.min(np.linalg.norm(X[used] - EYE, axis=1))), 1)
    # thigh top under the kneeboard (left), and seat contact
    kb = (X[:, 0] > KNEE_BOARD[0] - 10) & (X[:, 0] < KNEE_BOARD[0] + 10) & (np.abs(X[:, 1] - KNEE_BOARD[1]) < 6)
    kb &= np.isin(np.arange(len(X)), used)
    info["thigh_top_under_board"] = round(float(X[kb, 2].max()), 1) if kb.any() else None
    info["board_back_z"] = KNEE_BOARD[2] - 0.9
    info["lowest_z_seat_area"] = round(float(X[used][(X[used][:, 0] < 450) & (np.abs(X[used][:, 1]) < 20), 2].min()), 1)
    info["min_x_back"] = round(float(X[used][:, 0].min()), 1)
    info["back_pen_cm"] = round(float(back_pen(X[used]).max()), 1)
    info["y_extent_hips"] = [round(float(X[used][(X[used][:, 2] < 45) & (X[used][:, 0] < 440), 1].min()), 1),
                             round(float(X[used][(X[used][:, 2] < 45) & (X[used][:, 0] < 440), 1].max()), 1)]
    info["n_tris"] = int(keep.sum())
    nt0 = len(T)
    X, T, cls, keep, nl = cap_holes(X, T, keep, cls)
    info["capped_loops"] = nl
    print(json.dumps(info, indent=1))
    if a.out:
        capT = [dict(v=[int(x) for x in T[i]], cls=int(cls[i])) for i in range(nt0, len(T))]
        json.dump(dict(P=[[round(float(c), 3) for c in p] for p in X], cls=[int(c) for c in cls[:nt0]], drop=[int(d) for d in drop], capT=capT, info=info),
                  open(a.out, "w"))
    if a.obj:
        with open(a.obj, "w") as f:
            for p in X:
                f.write("v %.3f %.3f %.3f\n" % (p[0] / 100.0, -p[1] / 100.0, p[2] / 100.0))     # Blender export space
            for k in range(5):
                f.write("g cls%d\nusemtl PM%d\n" % (k, k))
                for ti, t in enumerate(T):
                    if keep[ti] and cls[ti] == k:
                        f.write("f %d %d %d\n" % (t[0] + 1, t[1] + 1, t[2] + 1))   # UE (left-handed) -> Blender (x, -y, z): same order
    return info


if __name__ == "__main__":
    main()
