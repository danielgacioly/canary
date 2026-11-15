"""Settings read from environment variables. Defaults are for local development only."""
import os
import pathlib
import re
import secrets
from typing import Dict, List

ROOT = pathlib.Path(__file__).resolve().parents[2]


PIN_RE = re.compile(r"^\d{4}$")


def _pins(raw: str) -> Dict[str, str]:
    """Parse "h:1001,k:1002" into {"h": "1001", ...}. Every PIN must be exactly 4 digits."""
    out = {}
    for part in raw.split(","):
        if not part.strip():
            continue
        who, _, pin = part.partition(":")
        who, pin = who.strip(), pin.strip()
        if not who or not PIN_RE.match(pin):
            raise ValueError(f"CANARY_CREW_PINS: PIN for '{who}' must be exactly 4 digits")
        out[who] = pin
    return out


def _pin(name: str, raw: str) -> str:
    if not PIN_RE.match(raw):
        raise ValueError(f"{name} must be exactly 4 digits")
    return raw


MODES = ("demo", "flight")


def _mode(raw: str) -> str:
    if raw not in MODES:
        raise ValueError(f"CANARY_MODE must be one of {', '.join(MODES)}, not '{raw}'")
    return raw


def _bootstrap(raw: str) -> str:
    return _pin("CANARY_CONTROL_BOOTSTRAP_PIN", raw) if raw else ""


MODE = _mode(os.environ.get("CANARY_MODE", "demo"))


class Settings:
    db_path: str = os.environ.get("CANARY_DB", str(ROOT / "backend" / "canary.db"))
    # "demo": the bundled demo mission loads on first start and the demo-only endpoints exist. "flight": nothing is loaded
    # for you, the demo-only endpoints answer 404, the delay runs in real time, and a secret and a bootstrap PIN are required.
    mode: str = MODE
    # The first Canary Control sign-in, accepted only while no MCC account is registered. Demo default 4242; flight: required.
    control_bootstrap_pin: str = _bootstrap(os.environ.get("CANARY_CONTROL_BOOTSTRAP_PIN", "4242" if MODE == "demo" else ""))
    # Fallback PIN of a crew id that has no stored PIN ("id:pin,..."): a demo convenience, empty in flight mode.
    crew_pins: Dict[str, str] = _pins(os.environ.get("CANARY_CREW_PINS", "h:1001,k:1002,a:1003,t:1004" if MODE == "demo" else ""))
    # PBKDF2 rounds for PIN hashes. Leave the default: a stored hash does not record the count, so changing it
    # invalidates every stored PIN. The test suite lowers it to run fast.
    pin_iterations: int = int(os.environ.get("CANARY_PBKDF2_ITERATIONS", "100000"))
    token_secret: str = os.environ.get("CANARY_TOKEN_SECRET") or secrets.token_hex(16)
    token_ttl_s: int = int(os.environ.get("CANARY_TOKEN_TTL", "3600"))
    # Communication delay runs this many times faster than real time in the demo.
    delay_speedup: float = float(os.environ.get("CANARY_DELAY_SPEEDUP", "1" if MODE == "flight" else "20"))
    # NASA DONKI live space weather. DEMO_KEY works with low rate limits.
    nasa_api_key: str = os.environ.get("NASA_API_KEY", "DEMO_KEY")
    live_space_weather: bool = os.environ.get("CANARY_LIVE_SPACE_WEATHER", "0") == "1"
    # AI assistant provider: "none" (default), "anthropic" or "local". See canary/assistant/providers.py
    llm_provider: str = os.environ.get("CANARY_LLM_PROVIDER", "none")
    frontend_dist: str = os.environ.get("CANARY_FRONTEND_DIST", str(ROOT / "frontend" / "dist"))
    # Web origins that may call the API from another origin (comma-separated). The dev server proxies /api and
    # `make serve` is one origin, so neither needs this; it keeps a page from some other origin off the API.
    cors_origins: List[str] = [o.strip() for o in os.environ.get(
        "CANARY_CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173").split(",") if o.strip()]
    # Compute the six demo-story days in the background at start-up, so the first click on a scene is quick.
    # Key a sensor, wearable or lab must send (header X-Canary-Key) to POST /api/observations. Empty: ingest is off.
    ingest_key: str = os.environ.get("CANARY_INGEST_KEY", "")
    # Mission package (a folder under data/missions) loaded on first start and by "reset demo". Empty: start with no data.
    mission_package: str = os.environ.get("CANARY_MISSION_PACKAGE", "odyssey1-mars")
    missions_dir: str = os.environ.get("CANARY_MISSIONS_DIR", str(ROOT / "data" / "missions"))
    warm_cache: bool = os.environ.get("CANARY_WARM", "1") == "1"
    # Background thread that notices a new mission day (every `day_sync_seconds`) and runs what a new day triggers.
    day_sync: bool = os.environ.get("CANARY_DAY_SYNC", "1") == "1"
    day_sync_seconds: int = int(os.environ.get("CANARY_DAY_SYNC_SECONDS", "600"))


settings = Settings()


def check_mode() -> None:
    """Refuse to start in flight mode without the secrets a real mission needs. Called when the API starts."""
    if settings.mode not in MODES:
        raise RuntimeError(f"CANARY_MODE must be one of {', '.join(MODES)}")
    if settings.mode == "flight":
        missing = [n for n, ok in (("CANARY_TOKEN_SECRET", bool(os.environ.get("CANARY_TOKEN_SECRET"))),
                                   ("CANARY_CONTROL_BOOTSTRAP_PIN", bool(settings.control_bootstrap_pin))) if not ok]
        if missing:
            raise RuntimeError("Flight mode needs " + " and ".join(missing) + " to be set. Canary will not start without them.")
