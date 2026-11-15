"""Build the inner-anatomy model of the hologram from BodyParts3D.

Input : BodyParts3D 4.0 "PART-OF" OBJ release (https://dbarchive.biosciencedbc.jp/en/bodyparts3d/download.html)
        (one OBJ per element, named FJxxxx.obj) plus the two text tables that map organ
        names to those elements: partof_parts_list_e.txt and partof_element_parts.txt.
        BodyParts3D, (c) The Database Center for Life Science, CC BY-SA 2.1 Japan
        (the OBJ files carry that notice in their header; the site now also states CC BY 4.0).
Output: frontend/public/models/anatomy.glb   (one mesh per structure, tagged with its system in `extras`)

What it does
  1. picks the elements of each system (skeleton, brain, eyes, heart, lungs, gut, kidneys, immune);
  2. fits them to the MakeHuman body of body.glb (feet on y=0, 1.75 m, +z forward, left = +x):
       - trunk, head, pelvis and organs: one common height-preserving "slice warp" that keeps everything
         inside the body silhouette of every height band,
       - arms and legs: each bone chain is moved by a similarity transform onto the joints of joints.json;
  3. decimates with `npx @gltf-transform/cli` (weld + simplify), recomputes smooth normals and
     writes a meshopt-compressed GLB (needs network the first time, to fetch the CLI).

The spleen is not in BodyParts3D: it is a small procedural ellipsoid, and it is the only part that is.

Usage:
    python3 tools/build_anatomy_model.py --bp3d DIR_WITH_FJ_OBJ_FILES --lists DIR_WITH_THE_TXT_TABLES [--preview OUT_DIR]
Needs numpy and node (npx). Treat the BodyParts3D download as data: this script only reads it.
"""
import argparse
import collections
import json
import pathlib
import re
import shutil
import struct
import subprocess
import sys
import tempfile

import numpy as np

ROOT = pathlib.Path(__file__).resolve().parents[1]
MODELS = ROOT / "frontend" / "public" / "models"
SCALE = 1.018          # BodyParts3D man is 1.72 m; the MakeHuman body 1.75 m
GROUND_MM = 78.0       # BodyParts3D feet stand 78 mm below its z = 0
GLOW_K, GLOW_EXP = 0.4, 0.8   # light per mesh = K / layers^EXP


# ----------------------------------------------------------------------------- data access
class BP3D:
    def __init__(self, obj_dir, list_dir):
        self.obj_dir = pathlib.Path(obj_dir)
        rows = [l.rstrip("\n").split("\t") for l in open(pathlib.Path(list_dir) / "partof_parts_list_e.txt", encoding="utf-8")][1:]
        self.name = {r[0]: r[2] for r in rows}
        self.ids = collections.defaultdict(list)
        for cid, nm in self.name.items():
            self.ids[nm].append(cid)
        self.elements = collections.defaultdict(list)
        for l in list(open(pathlib.Path(list_dir) / "partof_element_parts.txt", encoding="utf-8"))[1:]:
            c, _, f = l.rstrip("\n").split("\t")
            self.elements[c].append(f)
        self._cache = {}

    def fj(self, *names):
        """element ids of the concepts with exactly these names"""
        out = []
        for n in names:
            if n not in self.ids:
                raise KeyError(n)
            for cid in self.ids[n]:
                out += self.elements[cid]
        return list(dict.fromkeys(out))

    def fj_re(self, pattern, exclude=None):
        rx = re.compile(pattern, re.I)
        ex = re.compile(exclude, re.I) if exclude else None
        out = []
        for cid, nm in self.name.items():
            if rx.search(nm) and not (ex and ex.search(nm)) and len(self.elements[cid]) == 1:
                out += self.elements[cid]
        return list(dict.fromkeys(out))

    def mesh(self, fj):
        if fj not in self._cache:
            V, F = [], []
            for l in open(self.obj_dir / f"{fj}.obj", encoding="utf-8", errors="ignore"):
                if l.startswith("v "):
                    V.append([float(x) for x in l.split()[1:4]])
                elif l.startswith("f "):
                    t = [int(x.split("/")[0]) - 1 for x in l.split()[1:]]
                    for i in range(1, len(t) - 1):
                        F.append([t[0], t[i], t[i + 1]])
            self._cache[fj] = (np.array(V, dtype=np.float64), np.array(F, dtype=np.int64))
        return self._cache[fj]

    def merged(self, fjs):
        Vs, Fs, o = [], [], 0
        for f in fjs:
            V, F = self.mesh(f)
            Vs.append(V)
            Fs.append(F + o)
            o += len(V)
        return np.vstack(Vs), np.vstack(Fs)


def read_glb(path):
    """positions, indices, region of the single-mesh body.glb"""
    b = open(path, "rb").read()
    jl = struct.unpack("<I", b[12:16])[0]
    js = json.loads(b[20:20 + jl])
    binary = b[20 + jl + 8:]

    def acc(i):
        a = js["accessors"][i]
        v = js["bufferViews"][a["bufferView"]]
        ct = {5126: "<f4", 5125: "<u4", 5123: "<u2"}[a["componentType"]]
        n = {"SCALAR": 1, "VEC3": 3}[a["type"]]
        return np.frombuffer(binary, dtype=ct, count=a["count"] * n, offset=v["byteOffset"] + a.get("byteOffset", 0)).reshape(-1, n).copy()

    p = js["meshes"][0]["primitives"][0]
    return acc(p["attributes"]["POSITION"]).astype(np.float64), acc(p["indices"]).reshape(-1, 3).astype(np.int64), acc(p["attributes"]["_REGION"])[:, 0]


# ----------------------------------------------------------------------------- geometry helpers
def to_frame(V):
    """BodyParts3D (mm; x right-to-left, y back-to-front negative, z up) to metres, y up, +z forward. A proper rotation."""
    return np.stack([V[:, 0] * SCALE / 1000, (V[:, 2] + GROUND_MM) * SCALE / 1000, -V[:, 1] * SCALE / 1000], 1)


def axis_ends(V, cap=0.06):
    """(proximal anchor, distal anchor) of a long bone: centroids of the first and last `cap` of its length (z high = proximal)."""
    c = V.mean(0)
    u = np.linalg.svd(V - c, full_matrices=False)[2][0]
    t = (V - c) @ u
    if u[1] < 0:      # point toward +y (up in the converted frame)
        u, t = -u, -t
    lo, hi = t.min(), t.max()
    n = hi - lo
    return V[t >= hi - cap * n].mean(0), V[t <= lo + cap * n].mean(0)


def rot_between(a, b):
    a = a / np.linalg.norm(a)
    b = b / np.linalg.norm(b)
    v = np.cross(a, b)
    c = float(a @ b)
    if c < -0.999999:
        p = np.cross(a, [1, 0, 0] if abs(a[0]) < 0.9 else [0, 1, 0])
        p /= np.linalg.norm(p)
        return 2 * np.outer(p, p) - np.eye(3)
    k = np.array([[0, -v[2], v[1]], [v[2], 0, -v[0]], [-v[1], v[0], 0]])
    return np.eye(3) + k + k @ k / (1 + c)


class Similarity:
    """p -> dst0 + s R (p - src0), the rotation taking the src0->src1 direction onto dst0->dst1"""

    def __init__(self, src0, src1, dst0, dst1):
        d_src, d_dst = src1 - src0, dst1 - dst0
        self.s = np.linalg.norm(d_dst) / np.linalg.norm(d_src)
        self.R = rot_between(d_src, d_dst)
        self.src0, self.dst0 = src0, dst0

    def __call__(self, V):
        return self.dst0 + self.s * (V - self.src0) @ self.R.T


def smooth(a, sigma_bins):
    k = np.exp(-0.5 * (np.arange(-4 * sigma_bins, 4 * sigma_bins + 1) / sigma_bins) ** 2)
    k /= k.sum()
    pad = np.pad(a, 4 * sigma_bins, mode="edge")
    return np.convolve(pad, k, mode="valid")


class TorsoWarp:
    """Height-preserving slice warp: in every height band the inner structures (BodyParts3D) are scaled in x and z
    so that they fit inside the MakeHuman torso/head of that band, with a margin for flesh and skin."""

    BAND = 0.01

    def __init__(self, body_V, body_region, inner_V, margin=0.88):
        ys = np.arange(0.80, 1.78, self.BAND)
        self.ys = ys
        n = len(ys)
        mh = np.full((n, 4), np.nan)    # xhalf, zlo, zhi
        bp = np.full((n, 4), np.nan)
        torso = (body_region == 0) | (body_region == 1)
        for i, y in enumerate(ys):
            m = torso & (np.abs(body_V[:, 1] - y) <= 0.0125)
            if m.sum() > 8:
                q = body_V[m]
                mh[i] = [np.abs(q[:, 0]).max(), q[:, 2].min(), q[:, 2].max(), 1]
            m = np.abs(inner_V[:, 1] - y) <= 0.0125
            if m.sum() > 30:
                q = inner_V[m]
                bp[i] = [np.abs(q[:, 0]).max(), q[:, 2].min(), q[:, 2].max(), 1]
        ok = ~np.isnan(mh[:, 0]) & ~np.isnan(bp[:, 0])
        sx = np.interp(ys, ys[ok], (margin * mh[ok, 0] / bp[ok, 0]))
        sz = np.interp(ys, ys[ok], (margin * (mh[ok, 2] - mh[ok, 1]) / (bp[ok, 2] - bp[ok, 1])))
        zcb = np.interp(ys, ys[ok], (bp[ok, 1] + bp[ok, 2]) / 2)
        zcm = np.interp(ys, ys[ok], (mh[ok, 1] + mh[ok, 2]) / 2)
        self.hx = smooth(np.interp(ys, ys[ok], mh[ok, 0]), 2)
        self.hz = smooth(np.interp(ys, ys[ok], (mh[ok, 2] - mh[ok, 1]) / 2), 2)
        self.cz = smooth(zcm, 2)
        self.sx = smooth(np.clip(sx, 0.6, 1.25), 2)
        self.sz = smooth(np.clip(sz, 0.6, 1.3), 2)
        self.zcb = smooth(zcb, 2)

    def __call__(self, V, safety=0.965):
        P = V.copy()
        y = P[:, 1]
        f = lambda a: np.interp(y, self.ys, a)
        P[:, 0] = P[:, 0] * f(self.sx)
        P[:, 2] = f(self.cz) + (P[:, 2] - f(self.zcb)) * f(self.sz)
        hx, hz, cz = f(self.hx) * safety, f(self.hz) * safety, f(self.cz)
        r = np.sqrt((P[:, 0] / hx) ** 2 + ((P[:, 2] - cz) / hz) ** 2)
        k = np.where(r > 1, 1 / np.maximum(r, 1e-9), 1)
        P[:, 0] *= k
        P[:, 2] = cz + (P[:, 2] - cz) * k
        return P


# ----------------------------------------------------------------------------- the parts
class Part:
    def __init__(self, name, system, kind, V, F, tris, color=None, uv=False):
        self.name, self.system, self.kind, self.V, self.F, self.tris, self.color, self.uv = name, system, kind, V, F, tris, color, uv


def build_parts(db, log):
    parts = []

    def add(name, system, kind, fjs, tris, xf, color=None, uv=False, group=None):
        V, F = db.merged(fjs)
        parts.append(Part(name, system, kind, to_frame(V), F, tris, color, uv))
        parts[-1].xf = xf
        parts[-1].group = group or name
        return parts[-1]

    # ---------------- the elements, by region
    sk = db.fj("skeleton (in vivo)")
    eyeish = set(db.fj_re(r"choroid|cornea|iris|lacrimal gland|lens|sclera|vitreous|anterior chamber|suspensory ligament of"))
    sk = [f for f in sk if f not in eyeish]
    skull_fj = [f for f in db.fj("skull") if f not in db.fj("mandible", "hyoid bone")]
    vert_fj = db.fj_re(r"vertebra$|^atlas$|^axis$|^intervertebral disk|^sacrum$")
    rib_fj = db.fj_re(r"rib$|costal cartilage$|sternum$|^manubrium$|xiphoid")
    hip_fj = db.fj("right hip bone", "left hip bone")
    scap_fj = {s: db.fj(f"{s} scapula", f"{s} clavicle") for s in ("left", "right")}
    known = set(skull_fj) | set(db.fj("mandible", "hyoid bone")) | set(vert_fj) | set(rib_fj) | set(hip_fj) | set(sum(scap_fj.values(), []))
    left_over = [f for f in sk if f not in known and f not in db.fj_re(r"pelvic girdle")]
    log(f"skeleton elements left over (ignored): {len(left_over)}")

    add("skull", "skeleton", "bone", skull_fj, 17000, "torso")
    add("jaw", "skeleton", "bone", db.fj("mandible", "hyoid bone"), 2600, "torso")
    add("spine", "skeleton", "bone", vert_fj, 19000, "torso")
    add("thorax", "skeleton", "bone", rib_fj, 24000, "torso")
    add("pelvis", "skeleton", "bone", hip_fj, 5500, "torso")
    for s in ("left", "right"):
        add(f"shoulder_{s}", "skeleton", "bone", scap_fj[s], 4200, "torso")

    chains = {}
    for s in ("left", "right"):
        chains[s] = dict(
            humerus=db.fj(f"{s} humerus"), forearm=db.fj(f"{s} radius", f"{s} ulna"),
            hand=db.fj_re(rf"(phalanx of {s} (thumb|index finger|middle finger|ring finger|little finger)|{s} .* metacarpal bone$)") + db.fj(f"skeleton of {s} hand proper"),
            femur=db.fj(f"{s} femur", f"{s} patella"), shin=db.fj(f"{s} tibia", f"{s} fibula"),
            foot=db.fj_re(rf"(phalanx of {s} (big |)toe|phalanx of {s} (second|third|fourth|little) toe|{s} .*metatarsal bone$|^{s} (talus|calcaneus|cuboid bone)$|navicular bone of {s} foot|^{s} .*cuneiform bone$)"))
    for s in ("left", "right"):
        c = chains[s]
        log(f"{s}: hand {len(c['hand'])} foot {len(c['foot'])} elements")
        add(f"humerus_{s}", "skeleton", "bone", c["humerus"], 1700, f"humerus_{s}", group=f"arm_{s}")
        add(f"forearm_{s}", "skeleton", "bone", c["forearm"], 1500, f"forearm_{s}", group=f"arm_{s}")
        add(f"hand_{s}", "skeleton", "bone", c["hand"], 4500, f"hand_{s}")
        add(f"femur_{s}", "skeleton", "bone", c["femur"], 3000, f"femur_{s}", group=f"leg_{s}")
        add(f"shin_{s}", "skeleton", "bone", c["shin"], 2700, f"shin_{s}", group=f"leg_{s}")
        add(f"foot_{s}", "skeleton", "bone", c["foot"], 5200, f"foot_{s}")

    # organs
    add("brain", "brain", "organ", [f for f in db.fj("brain") if f not in set(db.fj_re(r"ventricle|cerebral aqueduct|internal capsule|hippocampus|colliculus|habenula|pineal|hypothalam|cingulate|parahippocampal|insula"))], 26000, "torso")
    add("eye_left", "eyes", "organ", db.fj("left sclera", "left cornea", "left iris"), 700, "eye")
    add("eye_right", "eyes", "organ", db.fj("right sclera", "right cornea", "right iris"), 700, "eye")
    add("heart", "heart", "organ", db.fj("myocardium of left ventricle", "myocardium of right ventricle", "wall of right atrium", "wall of left atrium"), 15000, "torso")
    for nm, fj in (("aorta", db.fj("ascending aorta", "arch of aorta", "descending thoracic aorta", "abdominal aorta")),
                   ("pulmonary_trunk", db.fj("pulmonary trunk")),
                   ("vena_cava", db.fj("superior vena cava", "inferior vena cava"))):
        add(nm, "heart", "vessel", fj, 1800, "torso", uv=True)
    # lungs: BodyParts3D has the airways and vessels of the lungs, not a lobe surface; the envelope is made in `lung_envelope`
    for s in ("left", "right"):
        add(f"airways_{s}", "lungs", "vessel", db.fj(f"{s} bronchial tree"), 3000, "torso", uv=True)
        add(f"lung_vessels_{s}", "lungs", "vessel", db.fj(f"{s} pulmonary artery", f"{s} superior pulmonary vein", f"{s} inferior pulmonary vein"), 3500, "torso", uv=True)
    add("trachea", "lungs", "vessel", db.fj("trachea", "right main bronchus", "left main bronchus"), 2200, "torso", uv=True)
    # gut
    liver = db.fj_re(r"^hepatovenous segment|^caudate lobe of liver$")
    add("liver", "gut", "organ", liver, 7000, "torso", color="#ffb86b")
    add("stomach", "gut", "organ", db.fj("stomach"), 1800, "torso")
    add("gallbladder", "gut", "organ", db.fj("gallbladder"), 500, "torso", color="#ffb86b")
    add("pancreas", "gut", "organ", db.fj("pancreas"), 2500, "torso")
    add("small_intestine", "gut", "organ", db.fj("small intestine"), 9000, "torso")
    add("large_intestine", "gut", "organ", db.fj("ascending colon", "transverse colon", "descending colon", "rectum", "cecum", "appendix"), 9000, "torso")
    # kidneys + bladder
    for s in ("left", "right"):
        add(f"kidney_{s}", "kidneys", "organ", db.fj(f"{s} kidney"), 2300, "torso")
    add("bladder", "kidneys", "organ", db.fj("urinary bladder"), 226, "torso")
    add("thymus", "immune", "organ", db.fj("thymus"), 2000, "torso")
    return parts, chains




# ----------------------------------------------------------------------------- lungs: envelope around the airways and vessels
def surface_nets(f, origin, h):
    """naive surface nets: one vertex per sign-changing cell, one quad per sign-changing grid edge (outward winding)"""
    inside = f > 0
    nx, ny, nz = f.shape
    corners = [(i, j, k) for i in (0, 1) for j in (0, 1) for k in (0, 1)]
    vals = np.stack([f[i:nx - 1 + i, j:ny - 1 + j, k:nz - 1 + k] for (i, j, k) in corners], -1)
    s = vals > 0
    mixed = s.any(-1) & ~s.all(-1)
    cell_id = -np.ones(mixed.shape, dtype=np.int64)
    ci = np.argwhere(mixed)
    cell_id[mixed] = np.arange(len(ci))
    vals = vals[mixed]
    cpos = np.array(corners, dtype=float)
    pos = np.zeros((len(ci), 3))
    cnt = np.zeros(len(ci))
    for a, b in [(0, 1), (2, 3), (4, 5), (6, 7), (0, 2), (1, 3), (4, 6), (5, 7), (0, 4), (1, 5), (2, 6), (3, 7)]:
        va, vb = vals[:, a], vals[:, b]
        cross = (va > 0) != (vb > 0)
        t = np.where(cross, va / np.where(va == vb, 1, va - vb), 0)
        pos += np.where(cross[:, None], cpos[a] + (cpos[b] - cpos[a]) * t[:, None], 0)
        cnt += cross
    V = origin + (ci + pos / np.maximum(cnt, 1)[:, None]) * h
    F = []
    for axis in range(3):
        b1, b2 = (axis + 1) % 3, (axis + 2) % 3
        hi = [slice(0, None)] * 3
        lo = [slice(0, None)] * 3
        shape = list(f.shape)
        shape[axis] -= 1
        lo[axis], hi[axis] = slice(0, shape[axis]), slice(1, shape[axis] + 1)
        e0, e1 = inside[tuple(lo)], inside[tuple(hi)]
        for p in np.argwhere(e0 != e1):
            if p[b1] < 1 or p[b2] < 1 or p[b1] > nz * 0 + f.shape[b1] - 2 or p[b2] > f.shape[b2] - 2:
                continue
            c = []
            for d1, d2 in ((0, 0), (1, 0), (1, 1), (0, 1)):
                q = p.copy()
                q[b1] -= d1
                q[b2] -= d2
                c.append(cell_id[tuple(q)] if q[axis] < cell_id.shape[axis] else -1)
            if min(c) < 0:
                continue
            quad = c if e0[tuple(p)] else c[::-1]
            F += [[quad[0], quad[1], quad[2]], [quad[0], quad[2], quad[3]]]
    return V, np.array(F, dtype=np.int64)


def lung_envelope(points, h=0.005, radius=0.016, level=0.08):
    """A smooth closed surface around a cloud of points: Gaussian blobs on a voxel grid, then surface nets."""
    lo, hi = points.min(0) - radius * 2.5, points.max(0) + radius * 2.5
    g = np.zeros(tuple(np.ceil((hi - lo) / h).astype(int) + 1), dtype=np.float32)
    idx = np.floor((points - lo) / h).astype(int)
    np.add.at(g, (idx[:, 0], idx[:, 1], idx[:, 2]), 1.0)
    k = int(np.ceil(radius * 2 / h))
    ax = np.arange(-k, k + 1)
    kern = np.exp(-(ax[:, None, None] ** 2 + ax[None, :, None] ** 2 + ax[None, None, :] ** 2) * (h / radius) ** 2 / 2).astype(np.float32)
    shape = [int(2 ** np.ceil(np.log2(a + 2 * k + 1))) for a in g.shape]
    ax3 = (0, 1, 2)
    out = np.fft.irfftn(np.fft.rfftn(g, shape, ax3) * np.fft.rfftn(kern, shape, ax3), shape, ax3)[k:k + g.shape[0], k:k + g.shape[1], k:k + g.shape[2]]
    out = out / out.max()
    return surface_nets(out - level, lo, h)


# ----------------------------------------------------------------------------- fitting
def fit_parts(parts, chains, db, body_V, body_R, J, log):
    jt = lambda k: np.array(J[k], dtype=np.float64)

    def piece(fjs):
        return to_frame(db.merged(fjs)[0])

    # 1. depth offset: the spine of the model on the spine joints of the body
    spine_src = np.mean([piece(db.fj(n)).mean(0)[2] for n in db.name.values() if n.endswith(" vertebra") and ("lumbar" in n or "thoracic" in n or "cervical" in n)][:12])
    off = np.mean([J[k][2] for k in ("spine-4", "spine-3", "spine-2", "spine-1")]) - spine_src
    log(f"depth offset {off:+.4f} m")
    shift = np.array([0, 0, off])
    for p in parts:
        p.V = p.V + shift
    # 2. the lungs need an envelope (BodyParts3D has the airways and vessels only)
    for s in ("left", "right"):
        pts = np.vstack([q.V for q in parts if q.name in (f"airways_{s}", f"lung_vessels_{s}")])
        V, F = lung_envelope(pts)
        env = Part(f"lung_{s}", "lungs", "organ", V, F, 9000)
        env.xf, env.group = "torso", f"lung_{s}"
        parts.insert(0, env)
        log(f"lung envelope {s}: {len(V)} vertices {len(F)} triangles")
    # 3. torso warp
    inner = np.vstack([p.V for p in parts if p.xf == "torso"])
    warp = TorsoWarp(body_V, body_R, inner)
    for p in parts:
        if p.xf == "torso":
            p.V = warp(p.V)
    # 4. eyes onto the eye joints
    for p in parts:
        if p.xf == "eye":
            side = "l" if p.name.endswith("left") else "r"
            p.V = warp(p.V)
            d = jt(f"{side}-eye") - p.V.mean(0)
            log(f"eye {side} shift {np.round(d * 1000, 1)} mm")
            p.V = p.V + d
    # 5. limbs
    for side, sj in (("left", "l"), ("right", "r")):
        c = chains[side]
        sh = lambda fjs: piece(fjs) + shift
        Vh, Vf = sh(c["humerus"]), sh(c["forearm"])
        h0, h1 = axis_ends(Vh)
        f0, f1 = axis_ends(Vf)
        elbow_src, wrist_src = (h1 + f0) / 2, f1
        shoulder_dst = warp(h0[None])[0]
        T_h = Similarity(h0, elbow_src, shoulder_dst, jt(f"{sj}-elbow"))
        T_f = Similarity(elbow_src, wrist_src, jt(f"{sj}-elbow"), jt(f"{sj}-hand"))
        Vhand = sh(c["hand"])
        tip = Vhand[Vhand[:, 1].argmin()]
        T_hand = Similarity(wrist_src, tip, jt(f"{sj}-hand"), jt(f"{sj}-finger-3-4"))
        Vfe, Vsh = sh(c["femur"]), sh(c["shin"])
        fe0, fe1 = axis_ends(Vfe)
        sh0, sh1 = axis_ends(Vsh)
        knee_src, ankle_src = (fe1 + sh0) / 2, sh1
        hip_dst = 0.5 * (warp(fe0[None])[0] + jt(f"{sj}-upper-leg"))
        T_fe = Similarity(fe0, knee_src, hip_dst, jt(f"{sj}-knee"))
        T_sh = Similarity(knee_src, ankle_src, jt(f"{sj}-knee"), jt(f"{sj}-ankle"))
        Vfoot = sh(c["foot"])
        toe = Vfoot[Vfoot[:, 2].argmax()]
        T_foot = Similarity(ankle_src, toe, jt(f"{sj}-ankle"), jt(f"{sj}-toe-2-4"))
        for name, T in (("humerus", T_h), ("forearm", T_f), ("hand", T_hand), ("femur", T_fe), ("shin", T_sh), ("foot", T_foot)):
            for p in parts:
                if p.xf == f"{name}_{side}":
                    p.V = T(p.V)
                    log(f"{p.name}: scale {T.s:.3f}")
    return warp


def check_inside(parts, warp, log):
    for p in parts:
        if p.xf != "torso":
            continue
        y = p.V[:, 1]
        hx, hz, cz = (np.interp(y, warp.ys, a) for a in (warp.hx, warp.hz, warp.cz))
        r = np.sqrt((p.V[:, 0] / hx) ** 2 + ((p.V[:, 2] - cz) / hz) ** 2)
        log(f"  inside check {p.name:18s} max radius {r.max():.3f}  over 1.0: {(r > 1).sum()}")


# ----------------------------------------------------------------------------- mesh output
def smooth_normals(V, F):
    N = np.zeros_like(V)
    fn = np.cross(V[F[:, 1]] - V[F[:, 0]], V[F[:, 2]] - V[F[:, 0]])
    for i in range(3):
        np.add.at(N, F[:, i], fn)
    return N / np.linalg.norm(N, axis=1, keepdims=True).clip(1e-12)


def signed_volume(V, F):
    return float(np.einsum("ij,ij->", V[F[:, 0]], np.cross(V[F[:, 1]], V[F[:, 2]])) / 6)


def depth_layers(V, F, cell=0.004):
    """Average number of front-facing surface layers a viewer sees through the mesh (front, side, top views).
    The hologram shaders add light layer on layer, so thick, folded meshes (skull, brain, bowel) need less light per layer."""
    tri = V[F]
    cr = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0]) / 2
    c = tri.mean(1)
    out = []
    for ax in range(3):
        a, b = [i for i in range(3) if i != ax]
        area = np.abs(cr[:, ax]).sum() / 2        # half of the triangles face the viewer
        cells = len({(int(x // cell), int(y // cell)) for x, y in zip(c[:, a], c[:, b])})
        out.append(area / max(1e-9, cells * cell * cell))
    return float(np.mean(out))


def write_glb(path, nodes, scene_extras=None, generator="canary build_anatomy_model.py"):
    """nodes: dicts with name, extras, V, N, F, optional UV"""
    blobs, views, accessors, meshes, gnodes = [], [], [], [], []

    def add(arr, target, comp, typ, minmax=False):
        data = arr.tobytes()
        off = sum(len(b) for b in blobs)
        blobs.append(data + b"\0" * ((-len(data)) % 4))
        views.append({"buffer": 0, "byteOffset": off, "byteLength": len(data), "target": target})
        acc = {"bufferView": len(views) - 1, "componentType": comp, "count": int(len(arr)), "type": typ}
        if minmax:
            acc["min"], acc["max"] = arr.min(0).tolist(), arr.max(0).tolist()
        accessors.append(acc)
        return len(accessors) - 1

    for i, n in enumerate(nodes):
        attrs = {"POSITION": add(n["V"].astype(np.float32), 34962, 5126, "VEC3", True), "NORMAL": add(n["N"].astype(np.float32), 34962, 5126, "VEC3")}
        if n.get("UV") is not None:
            attrs["TEXCOORD_0"] = add(n["UV"].astype(np.float32), 34962, 5126, "VEC2")
        idx = add(n["F"].astype(np.uint32).reshape(-1), 34963, 5125, "SCALAR")
        meshes.append({"name": n["name"], "primitives": [{"attributes": attrs, "indices": idx}]})
        gnodes.append({"name": n["name"], "mesh": i, "extras": n["extras"]})
    binary = b"".join(blobs)
    gltf = {"asset": {"version": "2.0", "generator": generator, "copyright": "BodyParts3D, (c) The Database Center for Life Science, CC BY-SA 2.1 Japan"},
            "scene": 0, "scenes": [{"nodes": list(range(len(gnodes))), "extras": scene_extras or {}}], "nodes": gnodes, "meshes": meshes,
            "buffers": [{"byteLength": len(binary)}], "bufferViews": views, "accessors": accessors}
    js = json.dumps(gltf, separators=(",", ":")).encode()
    js += b" " * ((-len(js)) % 4)
    with open(path, "wb") as f:
        f.write(struct.pack("<III", 0x46546C67, 2, 12 + 8 + len(js) + 8 + len(binary)))
        f.write(struct.pack("<II", len(js), 0x4E4F534A) + js)
        f.write(struct.pack("<II", len(binary), 0x004E4942) + binary)


def read_nodes(path):
    b = open(path, "rb").read()
    jl = struct.unpack("<I", b[12:16])[0]
    js = json.loads(b[20:20 + jl])
    binary = b[20 + jl + 8:]

    def acc(i):
        a = js["accessors"][i]
        v = js["bufferViews"][a["bufferView"]]
        dt = np.dtype({5126: "<f4", 5125: "<u4", 5123: "<u2"}[a["componentType"]])
        n = {"SCALAR": 1, "VEC2": 2, "VEC3": 3}[a["type"]]
        stride = v.get("byteStride", n * dt.itemsize)     # gltf-transform interleaves vertex attributes
        start = v.get("byteOffset", 0) + a.get("byteOffset", 0)
        raw = np.frombuffer(binary, dtype=np.uint8, count=(a["count"] - 1) * stride + n * dt.itemsize, offset=start)
        view = np.ndarray((a["count"], n), dtype=dt, buffer=raw, strides=(stride, dt.itemsize))
        return view.copy()

    out = []
    for n in js["nodes"]:
        p = js["meshes"][n["mesh"]]["primitives"][0]
        out.append({"name": n["name"], "extras": n.get("extras", {}), "V": acc(p["attributes"]["POSITION"]).astype(np.float64), "F": acc(p["indices"]).reshape(-1, 3).astype(np.int64)})
    return out


def cli(*args):
    r = subprocess.run(["npx", "--yes", "@gltf-transform/cli", *map(str, args)], capture_output=True, text=True)
    if r.returncode:
        sys.exit(f"gltf-transform {' '.join(map(str, args))} failed:\n{r.stdout}\n{r.stderr}")


def decimate(parts, work, log):
    """weld + simplify each group of parts at its own ratio with gltf-transform; returns {name: (V, F)}"""
    buckets = collections.defaultdict(list)
    for p in parts:
        ratio = min(1.0, p.tris / max(1, len(p.F)))
        buckets[round(ratio * 40) / 40 if ratio < 0.97 else 1.0].append(p)
    out = {}
    for i, (ratio, ps) in enumerate(sorted(buckets.items())):
        src, welded, simp = work / f"b{i}.glb", work / f"b{i}w.glb", work / f"b{i}s.glb"
        write_glb(src, [dict(name=p.name, extras={}, V=p.V, N=np.zeros_like(p.V), F=p.F) for p in ps])
        cli("weld", src, welded)
        if ratio < 1.0:
            cli("simplify", welded, simp, "--ratio", max(ratio, 0.01), "--error", 0.05)
        else:
            shutil.copy(welded, simp)
        for n in read_nodes(simp):
            out[n["name"]] = (n["V"], n["F"])
            log(f"  {n['name']:18s} ratio {ratio:.3f}: {len(n['F'])} triangles")
    return out


# ----------------------------------------------------------------------------- preview (software splats, for checking the fit)
def preview(parts, body_V, out_dir, views=("front", "side")):
    import zlib
    palette = {"skeleton": (198, 251, 255), "brain": (178, 139, 255), "eyes": (124, 243, 255), "heart": (255, 95, 168), "lungs": (111, 216, 255),
               "gut": (255, 211, 107), "kidneys": (255, 168, 96), "immune": (157, 255, 154)}
    out_dir = pathlib.Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(1)
    pts, cols = [], []
    for p in parts:
        tri = p.V[p.F]
        area = np.linalg.norm(np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0]), axis=1) / 2
        n = np.maximum(1, (area / 1.5e-6).astype(int))
        n = np.minimum(n, 60)
        rep = np.repeat(np.arange(len(tri)), n)
        r1, r2 = rng.random((2, len(rep)))
        flip = r1 + r2 > 1
        r1[flip], r2[flip] = 1 - r1[flip], 1 - r2[flip]
        q = tri[rep, 0] + r1[:, None] * (tri[rep, 1] - tri[rep, 0]) + r2[:, None] * (tri[rep, 2] - tri[rep, 0])
        pts.append(q)
        cols.append(np.tile(palette.get(p.system, (255, 255, 255)), (len(q), 1)))
    pts, cols = np.vstack(pts), np.vstack(cols).astype(float)
    sel = rng.random(len(body_V)) < 0.25
    for view in views:
        for crop, (y0, y1) in {"full": (0.0, 1.78), "head": (1.45, 1.78), "torso": (0.8, 1.5)}.items():
            H = 900
            sc = H / (y1 - y0)
            W = int((1.2 if crop == "full" else 0.55) * sc) if view == "front" else int(0.5 * sc)
            img = np.zeros((H, W, 3), dtype=np.float32)
            zb = np.full((H, W), -9.0)

            def draw(P, C, fade):
                u = P[:, 0] if view == "front" else P[:, 2] + 0.05
                d = P[:, 2] if view == "front" else P[:, 0]
                px = (W / 2 + u * sc).astype(int)
                py = (H - 1 - (P[:, 1] - y0) * sc).astype(int)
                ok = (px >= 0) & (px < W) & (py >= 0) & (py < H)
                order = np.argsort(d[ok])
                px, py, d, C = px[ok][order], py[ok][order], d[ok][order], C[ok][order]
                for a, b in ((0, 0), (1, 0), (0, 1)):
                    qx, qy = np.clip(px + a, 0, W - 1), np.clip(py + b, 0, H - 1)
                    img[qy, qx] = np.where(zb[qy, qx, None] <= d[:, None], C * fade, img[qy, qx]) if fade >= 1 else np.maximum(img[qy, qx], C * fade)
                    if fade >= 1:
                        zb[qy, qx] = np.maximum(zb[qy, qx], d)

            draw(body_V[sel], np.tile((70, 70, 90), (sel.sum(), 1)).astype(float), 0.6)
            draw(pts, cols, 1.0)
            raw = b"".join(b"\0" + bytes(np.clip(img[r], 0, 255).astype(np.uint8).tobytes()) for r in range(H))

            def chunk(t, d):
                return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)

            png = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", W, H, 8, 2, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(raw, 6)) + chunk(b"IEND", b"")
            (out_dir / f"{view}-{crop}.png").write_bytes(png)


# ----------------------------------------------------------------------------- main
def spleen():
    """Not in BodyParts3D: a small ellipsoid with a gentle bump, centred on the origin (placed by the caller)."""
    n = 28
    u, v = np.meshgrid(np.linspace(0, np.pi, n), np.linspace(0, 2 * np.pi, n * 2, endpoint=False), indexing="ij")
    P = np.stack([np.sin(u) * np.cos(v), np.cos(u), np.sin(u) * np.sin(v)], -1).reshape(-1, 3)
    P *= (1 + 0.06 * np.sin(P[:, 1] * 9.0 + P[:, 0] * 4.0) * np.cos(P[:, 2] * 7.0))[:, None]
    F = []
    for i in range(n - 1):
        for j in range(n * 2):
            a, b = i * n * 2 + j, i * n * 2 + (j + 1) % (n * 2)
            c, d = a + n * 2, b + n * 2
            F += [[a, c, b], [b, c, d]]
    return P, np.array(F, dtype=np.int64)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--bp3d", required=True, help="directory with the FJxxxx.obj files")
    ap.add_argument("--lists", required=True, help="directory with partof_parts_list_e.txt and partof_element_parts.txt")
    ap.add_argument("--out", default=str(MODELS / "anatomy.glb"))
    ap.add_argument("--preview", help="write software-rendered check images of the fitted model here, then stop")
    ap.add_argument("--keep", help="keep the intermediate files in this directory")
    a = ap.parse_args()
    log = lambda m: print(m, flush=True)

    body_V, _, body_R = read_glb(MODELS / "body.glb")
    J = json.loads((MODELS / "joints.json").read_text())["joints"]
    db = BP3D(a.bp3d, a.lists)
    parts, chains = build_parts(db, log)
    warp = fit_parts(parts, chains, db, body_V, body_R, J, log)

    # the spleen, between the stomach, the left kidney and the diaphragm
    kid = next(p for p in parts if p.name == "kidney_left").V
    sto = next(p for p in parts if p.name == "stomach").V
    c = np.array([sto[:, 0].max() - 0.012, kid[:, 1].mean() + 0.035, kid[:, 2].mean() + 0.035])
    SV, SF = spleen()
    SV = SV * np.array([0.022, 0.048, 0.03])
    ang = np.radians(-18)
    R = np.array([[np.cos(ang), -np.sin(ang), 0], [np.sin(ang), np.cos(ang), 0], [0, 0, 1]])
    sp = Part("spleen", "immune", "organ", SV @ R.T + c, SF, 600)
    sp.xf, sp.group = "none", "spleen"
    parts.append(sp)

    check_inside(parts, warp, log)
    if a.preview:
        preview(parts, body_V, a.preview)
        log(f"preview written to {a.preview}")
        return

    # merge pieces of one mesh, simplify, normals
    groups = collections.OrderedDict()
    for p in parts:
        groups.setdefault(p.group, []).append(p)
    merged = []
    for g, ps in groups.items():
        V = np.vstack([q.V for q in ps])
        o, Fs = 0, []
        for q in ps:
            Fs.append(q.F + o)
            o += len(q.V)
        m = Part(g, ps[0].system, ps[0].kind, V, np.vstack(Fs), sum(q.tris for q in ps), ps[0].color, ps[0].uv)
        merged.append(m)
    work = pathlib.Path(a.keep) if a.keep else pathlib.Path(tempfile.mkdtemp(prefix="canary-anatomy-"))
    work.mkdir(parents=True, exist_ok=True)
    dec = decimate(merged, work, log)
    nodes, total = [], 0
    for m in merged:
        V, F = dec[m.name]
        if signed_volume(V, F) < 0:
            F = F[:, ::-1].copy()
        N = smooth_normals(V, F)
        layers = depth_layers(V, F)
        ex = {"system": m.system, "kind": m.kind, "part": m.name, "layers": round(layers, 2), "glow": round(float(np.clip(GLOW_K / max(layers, 1.0) ** GLOW_EXP, 0.1, 1.0)), 3)}
        log(f"  {m.name:18s} layers {layers:5.2f} glow {ex['glow']}")
        if m.color:
            ex["color"] = m.color
        node = dict(name=m.name, extras=ex, V=V, N=N, F=F)
        if m.uv:     # flow shaders run their light pulses along uv.x: use the height
            node["UV"] = np.stack([V[:, 1] * (-3.0 if m.name == "aorta" else 3.0), np.zeros(len(V))], 1)
        nodes.append(node)
        total += len(F)
    # centre line of the vertebral canal, for the nerves that are drawn procedurally
    sv = next(p.V for p in parts if p.name == "spine")
    canal = []
    for y in np.arange(0.90, 1.60, 0.03):
        q = sv[np.abs(sv[:, 1] - y) < 0.015]
        if len(q):
            canal.append([round(float(q[:, 0].mean()), 4), round(float(y), 4), round(float(q[:, 2].mean()) - 0.012, 4)])
    extras = {"spine": canal, "source": "BodyParts3D, (c) The Database Center for Life Science, CC BY-SA 2.1 Japan; spleen is procedural",
              "triangles": total, "frame": "MakeHuman body.glb: metres, feet on y=0, +z forward, left = +x"}
    stage = work / "stage.glb"
    write_glb(stage, nodes, extras)
    out = pathlib.Path(a.out)
    cli("meshopt", stage, out, "--level", "high")
    log(f"{out}: {total} triangles in {len(nodes)} meshes, {out.stat().st_size / 1e6:.2f} MB")


if __name__ == "__main__":
    main()
