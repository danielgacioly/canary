"""Idempotency-Key for the mutating API routes. The same key with the same body returns the first answer and writes nothing
again; the same key with a different body is refused (409). Only a successful answer (2xx) is remembered, so a refused
request can be retried. The keys live in the `idempotency` table that the readings ingest (POST /api/observations) already
uses; a key belongs to the signed-in person (or to no one, for an anonymous request) and to one method and path.

Sign-in routes, the readings ingest (which keeps its own per-device rule) and large bodies (more than LIMIT bytes, or no
Content-Length) are not covered: they pass through unchanged.
"""
import hashlib
import json
import time

from . import db

LIMIT = 256_000
MUTATING = {"POST", "PUT", "PATCH", "DELETE"}
SKIP_PREFIXES = ("/api/observations",)  # the ingest keeps its own table rule
NAMESPACE = "api|"  # keeps these keys apart from the device ids the ingest stores in the same table


def _skip(path: str) -> bool:
    return path.startswith(SKIP_PREFIXES) or "/session" in path


def _scope(headers: dict, method: str, path: str) -> str:
    who = hashlib.sha256(headers.get(b"authorization", b"").decode("latin-1").encode()).hexdigest()[:16]
    return f"{NAMESPACE}{who}|{method} {path}"


async def _send_json(send, status: int, payload: dict) -> None:
    body = json.dumps(payload).encode()
    await send({"type": "http.response.start", "status": status,
                "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())]})
    await send({"type": "http.response.body", "body": body})


class IdempotencyMiddleware:
    """Pure ASGI, so the body is read once, replayed to the route, and the answer is seen as it is sent."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["method"] not in MUTATING or not scope["path"].startswith("/api/") or _skip(scope["path"]):
            return await self.app(scope, receive, send)
        headers = {k.lower(): v for k, v in scope.get("headers", [])}
        key = headers.get(b"idempotency-key", b"").decode("latin-1").strip()[:128]
        try:
            declared = int(headers.get(b"content-length", b"0") or 0)
        except ValueError:
            declared = LIMIT + 1
        if not key or declared > LIMIT or b"content-length" not in headers and scope["method"] != "DELETE":
            return await self.app(scope, receive, send)

        body = b""
        while True:  # the body is small (declared above), read it whole
            msg = await receive()
            if msg["type"] == "http.disconnect":
                return
            body += msg.get("body", b"")
            if not msg.get("more_body", False):
                break
        digest = hashlib.sha256(body).hexdigest()
        sid = _scope(headers, scope["method"], scope["path"])
        old = db.q("SELECT body_hash, response FROM idempotency WHERE device_id=? AND key=?", (sid, key))
        if old:
            if old[0]["body_hash"] != digest:
                return await _send_json(send, 409, {"detail": "This Idempotency-Key was already used with a different body"})
            saved = json.loads(old[0]["response"])
            out = saved["body"].encode()
            await send({"type": "http.response.start", "status": saved["status"],
                        "headers": [(b"content-type", saved["type"].encode()), (b"content-length", str(len(out)).encode()),
                                    (b"idempotent-replay", b"true")]})
            return await send({"type": "http.response.body", "body": out})

        replayed = False

        async def replay_receive():
            nonlocal replayed
            if not replayed:
                replayed = True
                return {"type": "http.request", "body": body, "more_body": False}
            return await receive()

        captured = {"status": None, "type": b"application/json", "chunks": []}

        async def capture_send(msg):
            if msg["type"] == "http.response.start":
                captured["status"] = msg["status"]
                for k, v in msg.get("headers", []):
                    if k.lower() == b"content-type":
                        captured["type"] = v
            elif msg["type"] == "http.response.body":
                captured["chunks"].append(msg.get("body", b""))
                if not msg.get("more_body", False) and captured["status"] and 200 <= captured["status"] < 300:
                    text = b"".join(captured["chunks"]).decode("utf-8", "replace")
                    db.x("INSERT OR REPLACE INTO idempotency(device_id,key,body_hash,response,created_at) VALUES(?,?,?,?,?)",
                         (sid, key, digest, json.dumps({"status": captured["status"], "type": captured["type"].decode("latin-1"),
                                                         "body": text}), time.time()))
            await send(msg)

        return await self.app(scope, replay_receive, capture_send)
