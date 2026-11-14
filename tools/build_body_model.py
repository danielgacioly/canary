"""Build the hologram body model from the MakeHuman base mesh (CC0).

Input : MakeHuman `base.obj` (https://github.com/makehumancommunity/makehuman,
        makehuman/data/3dobjs/base.obj, assets licensed CC0 1.0).
Output: frontend/public/models/body.glb   (positions, normals, _REGION, indices)
        frontend/public/models/joints.json (joint centres, metres, feet at y=0)

The body is scaled to 1.75 m, centred on x/z, with the feet on the floor.
Every vertex gets a surface region (head, torso, arm, hand, leg, foot) by its
nearest bone segment, so the app can highlight and pick body regions.

Usage:
    python3 tools/build_body_model.py path/to/base.obj
Needs numpy.
"""
import json
import pathlib
import struct
import sys

import numpy as np

HEIGHT_M = 1.75
REGIONS = ["head", "torso", "arm", "hand", "leg", "foot"]


def parse_obj(path):
    verts, groups, group = [], {}, None
    for line in open(path, encoding="utf-8"):
        if line.startswith("v "):
            verts.append([float(x) for x in line.split()[1:4]])
        elif line.startswith("g "):
            group = line.split()[1]
        elif line.startswith("f "):
            groups.setdefault(group, []).append([int(t.split("/")[0]) - 1 for t in line.split()[1:]])
    return np.array(verts, dtype=np.float64), groups


def seg_dist(p, a, b):
    ab = b - a
    t = np.clip(((p - a) @ ab) / max(ab @ ab, 1e-9), 0, 1)
    return np.linalg.norm(p - (a + t[:, None] * ab), axis=1)


def main(obj_path):
    root = pathlib.Path(__file__).resolve().parents[1]
    out_dir = root / "frontend" / "public" / "models"
    out_dir.mkdir(parents=True, exist_ok=True)

    V, G = parse_obj(obj_path)
    joints = {k[len("joint-"):]: V[np.unique(np.array(f))].mean(0) for k, f in G.items() if k.startswith("joint-")}

    faces = np.array(G["body"])
    used = np.unique(faces)
    remap = -np.ones(len(V), dtype=np.int64)
    remap[used] = np.arange(len(used))
    P = V[used]

    # metres, feet on the floor, centred
    lo, hi = P.min(0), P.max(0)
    scale = HEIGHT_M / (hi[1] - lo[1])
    offset = np.array([-(lo[0] + hi[0]) / 2, -lo[1], -(lo[2] + hi[2]) / 2])
    P = (P + offset) * scale
    joints = {k: ((v + offset) * scale) for k, v in joints.items()}

    quads = remap[faces]
    tris = np.concatenate([quads[:, [0, 1, 2]], quads[:, [0, 2, 3]]])

    # smooth normals
    N = np.zeros_like(P)
    fn = np.cross(P[tris[:, 1]] - P[tris[:, 0]], P[tris[:, 2]] - P[tris[:, 0]])
    for i in range(3):
        np.add.at(N, tris[:, i], fn)
    N /= np.linalg.norm(N, axis=1, keepdims=True).clip(1e-9)

    # regions by nearest bone segment
    J = joints
    segs = [("head", "neck", "head-2"), ("torso", "pelvis", "neck")]
    for s in "lr":
        segs += [
            ("torso", "neck", f"{s}-shoulder"),
            ("arm", f"{s}-shoulder", f"{s}-elbow"),
            ("arm", f"{s}-elbow", f"{s}-hand"),
            ("hand", f"{s}-hand", f"{s}-finger-3-4"),
            ("hand", f"{s}-hand", f"{s}-finger-1-4"),
            ("leg", f"{s}-upper-leg", f"{s}-knee"),
            ("leg", f"{s}-knee", f"{s}-ankle"),
            ("foot", f"{s}-ankle", f"{s}-toe-1-3"),
            ("foot", f"{s}-ankle", f"{s}-toe-5-3"),
            ("torso", "pelvis", f"{s}-upper-leg"),
        ]
    D = np.stack([seg_dist(P, J[a], J[b]) for _, a, b in segs], axis=1)
    region = np.array([REGIONS.index(segs[i][0]) for i in D.argmin(1)], dtype=np.float32)
    # the head/neck boundary: anything above the neck joint and near the midline is head
    region[(P[:, 1] > J["neck"][1] + 0.02) & (np.abs(P[:, 0]) < 0.14)] = REGIONS.index("head")

    write_glb(out_dir / "body.glb", P.astype(np.float32), N.astype(np.float32), region, tris.astype(np.uint32))
    keep = {k: [round(float(x), 4) for x in v] for k, v in joints.items()}
    (out_dir / "joints.json").write_text(json.dumps({"regions": REGIONS, "joints": keep}, indent=0))
    print(f"body.glb: {len(P)} vertices, {len(tris)} triangles; joints.json: {len(keep)} joints")


def write_glb(path, pos, nrm, region, idx):
    blobs, views, accessors = [], [], []

    def add(arr, target, comp, typ, minmax=False):
        data = arr.tobytes()
        off = sum(len(b) for b in blobs)
        pad = (-len(data)) % 4
        blobs.append(data + b"\0" * pad)
        views.append({"buffer": 0, "byteOffset": off, "byteLength": len(data), "target": target})
        acc = {"bufferView": len(views) - 1, "componentType": comp, "count": int(len(arr)), "type": typ}
        if minmax:
            acc["min"] = arr.min(0).tolist()
            acc["max"] = arr.max(0).tolist()
        accessors.append(acc)
        return len(accessors) - 1

    a_pos = add(pos, 34962, 5126, "VEC3", True)
    a_nrm = add(nrm, 34962, 5126, "VEC3")
    a_reg = add(region, 34962, 5126, "SCALAR")
    a_idx = add(idx.reshape(-1), 34963, 5125, "SCALAR")
    binary = b"".join(blobs)
    gltf = {
        "asset": {"version": "2.0", "generator": "canary build_body_model.py", "copyright": "MakeHuman base mesh, CC0 1.0"},
        "scene": 0,
        "scenes": [{"nodes": [0]}],
        "nodes": [{"mesh": 0, "name": "body"}],
        "meshes": [{"name": "body", "primitives": [{"attributes": {"POSITION": a_pos, "NORMAL": a_nrm, "_REGION": a_reg}, "indices": a_idx}]}],
        "buffers": [{"byteLength": len(binary)}],
        "bufferViews": views,
        "accessors": accessors,
    }
    js = json.dumps(gltf, separators=(",", ":")).encode()
    js += b" " * ((-len(js)) % 4)
    with open(path, "wb") as f:
        f.write(struct.pack("<III", 0x46546C67, 2, 12 + 8 + len(js) + 8 + len(binary)))
        f.write(struct.pack("<II", len(js), 0x4E4F534A) + js)
        f.write(struct.pack("<II", len(binary), 0x004E4942) + binary)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    main(sys.argv[1])
