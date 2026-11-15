"""Remove the inside of the mouth from the body shell (frontend/public/models/body.glb).

The MakeHuman body carries a mouth cavity behind the lips. Through the see-through skin of the hologram it shows as a
bright bag inside the face and means nothing, so its triangles are dropped. A triangle of the mouth area counts as
inside when almost no ray from its centre reaches the outside of the head. Only the index buffer changes; vertices,
normals and regions stay as they are, so the joints and the anatomy fit are untouched.

Usage: python3 tools/strip_mouth.py [--dry-run]
"""
import json
import pathlib
import struct
import sys

import numpy as np

PATH = pathlib.Path(__file__).resolve().parents[1] / "frontend" / "public" / "models" / "body.glb"
AREA = dict(x=0.05, y=(1.47, 1.62), z=-0.09)    # metres: around the mouth, front half of the head
RAYS, ESCAPE = 64, 0.08                          # inside = fewer than 8 % of the rays get out


def load(path):
    b = path.read_bytes()
    n = struct.unpack("<I", b[12:16])[0]
    j = json.loads(b[20:20 + n])
    bin_start = 20 + n + 8
    blob = b[bin_start:]
    acc = j["accessors"]

    def arr(i, dtype, width):
        bv = j["bufferViews"][acc[i]["bufferView"]]
        a = np.frombuffer(blob, dtype, acc[i]["count"] * width, bv["byteOffset"])
        return a.reshape(-1, width) if width > 1 else a

    prim = j["meshes"][0]["primitives"][0]
    V = arr(prim["attributes"]["POSITION"], np.float32, 3).astype(np.float64)
    R = arr(prim["attributes"]["_REGION"], np.float32, 1)
    F = arr(prim["indices"], np.uint32, 1).reshape(-1, 3)
    return j, blob, V, R, F


def directions(n):
    i = np.arange(n) + 0.5
    phi = np.arccos(1 - 2 * i / n)
    th = np.pi * (1 + 5 ** 0.5) * i
    return np.stack([np.cos(th) * np.sin(phi), np.cos(phi), np.sin(th) * np.sin(phi)], 1)


def blocked(o, d, A, E1, E2):
    """for one origin and many directions: does each ray hit any triangle (Moller-Trumbore)?"""
    out = np.zeros(len(d), bool)
    for k, dk in enumerate(d):
        p = np.cross(dk, E2)
        det = np.einsum("ij,ij->i", E1, p)
        ok = np.abs(det) > 1e-12
        inv = np.where(ok, 1 / np.where(ok, det, 1), 0)
        t = o - A
        u = np.einsum("ij,ij->i", t, p) * inv
        q = np.cross(t, E1)
        v = (q @ dk) * inv
        w = np.einsum("ij,ij->i", E2, q) * inv
        out[k] = np.any(ok & (u >= 0) & (v >= 0) & (u + v <= 1) & (w > 1e-5))
    return out


def main():
    j, blob, V, R, F = load(PATH)
    head = np.round(R[F[:, 0]]) == 0
    C = V[F].mean(1)
    area = head & (np.abs(C[:, 0]) < AREA["x"]) & (C[:, 1] > AREA["y"][0]) & (C[:, 1] < AREA["y"][1]) & (C[:, 2] > AREA["z"])
    T = V[F[head]]
    A, E1, E2 = T[:, 0], T[:, 1] - T[:, 0], T[:, 2] - T[:, 0]
    D = directions(RAYS)
    inside = np.zeros(len(F), bool)
    for i in np.where(area)[0]:
        n = np.cross(V[F[i, 1]] - V[F[i, 0]], V[F[i, 2]] - V[F[i, 0]])
        n /= np.linalg.norm(n) + 1e-12
        o = C[i] + n * 1e-4
        free = 1 - blocked(o, D, A, E1, E2).mean()
        o2 = C[i] - n * 1e-4                        # the winding of the bag may face either way
        free = max(free, 1 - blocked(o2, D, A, E1, E2).mean())
        inside[i] = free < ESCAPE
    print(f"mouth area {area.sum()} triangles, inside {inside.sum()}")
    if inside.any():
        c = C[inside]
        print("inside box", np.round(c.min(0), 3), np.round(c.max(0), 3))
    if "--dry-run" in sys.argv:
        return
    keep = F[~inside].astype(np.uint32).ravel()
    prim = j["meshes"][0]["primitives"][0]
    ia = j["accessors"][prim["indices"]]
    bv = j["bufferViews"][ia["bufferView"]]
    assert bv["byteOffset"] + bv["byteLength"] == len(blob.rstrip(b"\0")) or bv["byteOffset"] + bv["byteLength"] <= len(blob)
    new_blob = blob[:bv["byteOffset"]] + keep.tobytes()
    ia["count"] = int(keep.size)
    bv["byteLength"] = int(keep.nbytes)
    j["buffers"][0]["byteLength"] = len(new_blob)
    js = json.dumps(j, separators=(",", ":")).encode()
    js += b" " * (-len(js) % 4)
    new_blob += b"\0" * (-len(new_blob) % 4)
    out = b"glTF" + struct.pack("<II", 2, 12 + 8 + len(js) + 8 + len(new_blob))
    out += struct.pack("<I", len(js)) + b"JSON" + js + struct.pack("<I", len(new_blob)) + b"BIN\0" + new_blob
    PATH.write_bytes(out)
    print(f"{PATH.name}: {len(F)} -> {len(F) - inside.sum()} triangles")


if __name__ == "__main__":
    main()
