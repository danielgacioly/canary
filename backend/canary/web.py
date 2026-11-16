"""The web layer around the API: security headers, request metrics, the built app's static files, and the health probes' checks.

- Every response carries the security headers (CSP, frame and referrer policy). Every `/api/` response is `Cache-Control: no-store`:
  the API answers with live, personal and signed-in data, and no browser or proxy may keep it.
- Every request is timed. `/api/metrics` (Mission Control only) reports per-route request counts, errors and p50/p95 latency
  from this process. The numbers live in memory: one process, one count (see README, Operations).
- The built app is served from `dist`: a file that exists is served, a route of the app returns index.html, and an unknown
  `/api/` path or a missing asset (a path with a file extension, or under `assets/`) is a 404, never the app's HTML.
"""
import logging
import math
import pathlib
import sqlite3
import threading
import time
from collections import deque
from typing import Dict, List

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.datastructures import MutableHeaders

log = logging.getLogger("canary")

# The app loads only its own code, styles, fonts, models and images. Nothing comes from another origin at run time (see
# frontend/index.html); the API is the same origin. `unsafe-inline` for styles: React sets style attributes at run time.
CSP = ("default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; "
       "font-src 'self'; connect-src 'self'; media-src 'self' blob:; worker-src 'self' blob:; object-src 'none'; "
       "base-uri 'self'; form-action 'self'; frame-ancestors 'none'")
SECURITY_HEADERS = {
    "Content-Security-Policy": CSP,
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
}


class SecurityHeaders:
    """Pure ASGI middleware: the security headers on every response, and no-store on every API response."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        api = scope["path"] == "/api" or scope["path"].startswith("/api/")

        async def send_with_headers(message):
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                for name, value in SECURITY_HEADERS.items():
                    headers[name] = value
                if api:
                    headers["Cache-Control"] = "no-store"
            await send(message)

        await self.app(scope, receive, send_with_headers)


class Metrics:
    """Per-route request counts, errors and recent durations, kept in memory for this process."""

    WINDOW = 500  # durations kept per route: the percentiles are over the latest this many requests

    def __init__(self):
        self._lock = threading.Lock()
        self._routes: Dict[str, dict] = {}
        self._since = time.time()

    def record(self, route: str, status: int, seconds: float) -> None:
        with self._lock:
            r = self._routes.setdefault(route, {"requests": 0, "errors": 0, "durations": deque(maxlen=self.WINDOW)})
            r["requests"] += 1
            if status >= 500:
                r["errors"] += 1
            r["durations"].append(seconds)

    def snapshot(self) -> dict:
        with self._lock:
            rows = [(k, v["requests"], v["errors"], sorted(v["durations"])) for k, v in self._routes.items()]
        rows.sort(key=lambda x: -x[1])
        return {
            "since": round(self._since),
            "requests": sum(r[1] for r in rows),
            "errors": sum(r[2] for r in rows),
            "routes": [{"route": k, "requests": n, "errors": e, "p50_ms": _percentile(d, 50), "p95_ms": _percentile(d, 95)}
                       for k, n, e, d in rows],
        }


def _percentile(sorted_seconds: List[float], p: int):
    if not sorted_seconds:
        return None
    rank = math.ceil(p / 100 * len(sorted_seconds))  # nearest-rank
    return round(sorted_seconds[max(0, rank - 1)] * 1000, 2)


METRICS = Metrics()


class RequestMetrics:
    """Pure ASGI middleware: times every HTTP request and files it under its route template (`GET /api/crew/{crew_id}`).
    A request that matches no route is filed as `(unmatched)`, so a scanner cannot grow the table."""

    def __init__(self, app, metrics: Metrics = METRICS):
        self.app = app
        self.metrics = metrics

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        start = time.perf_counter()
        status = {"code": 500}  # stays 500 when the app raises before it answers

        async def send_and_note(message):
            if message["type"] == "http.response.start":
                status["code"] = message["status"]
            await send(message)

        try:
            await self.app(scope, receive, send_and_note)
        finally:
            route = scope.get("route")
            template = getattr(route, "path", None) or "(unmatched)"
            self.metrics.record(f"{scope['method']} {template}", status["code"], time.perf_counter() - start)


def kb_ready(path: str) -> str:
    """'ok' when the knowledge base file opens read-only and has its tables; otherwise what is wrong with it."""
    p = pathlib.Path(path)
    if not p.is_file():
        return "missing"
    try:
        conn = sqlite3.connect(f"file:{p}?mode=ro", uri=True, timeout=2)
        try:
            conn.execute("SELECT COUNT(*) FROM sqlite_master").fetchone()
        finally:
            conn.close()
    except sqlite3.Error:
        log.exception("knowledge base %s cannot be read", path)
        return "unreadable"
    return "ok"


def spa_file(dist: pathlib.Path, path: str) -> pathlib.Path:
    """The file under `dist` that `path` names, or dist/index.html when there is none or it would leave `dist`."""
    root = dist.resolve()
    f = (root / path).resolve()
    return f if path and f.is_file() and f.is_relative_to(root) else root / "index.html"


def mount_spa(app: FastAPI, dist: pathlib.Path) -> None:
    """Serve the built app from `dist`. Registered last, so every API route is matched before it."""
    app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        target = spa_file(dist, path)
        if target != dist.resolve() / "index.html" or path == "index.html":
            return FileResponse(target)  # a file that exists under dist
        is_api = path == "api" or path.startswith("api/")
        is_asset = path.startswith("assets/") or bool(pathlib.PurePosixPath(path).suffix)
        if is_api or is_asset:
            raise HTTPException(404, "Not found")  # never the app's HTML for an API path or a missing file
        return FileResponse(target)
