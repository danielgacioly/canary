"""Settings read from environment variables. Defaults are for local development only."""
import os
import pathlib
import re
import secrets
from typing import Dict

from dotenv import load_dotenv

ROOT = pathlib.Path(__file__).resolve().parents[2]



def load_env_file(path: pathlib.Path = ROOT / ".env") -> bool:
    """Load the repository-root .env regardless of the process working directory.

    Explicit process variables (including isolated test paths) take precedence. CANARY_SKIP_DOTENV=1 skips the
    file entirely: the test suite sets it so a developer's .env (real keys, slow timeouts) never leaks into tests.
    """
    if os.environ.get("CANARY_SKIP_DOTENV", "").strip() == "1":
        return False
    return load_dotenv(path, override=False)


load_env_file()


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


def _medical_pin(raw: str) -> str:
    if not PIN_RE.match(raw):
        raise ValueError("CANARY_MEDICAL_PIN must be exactly 4 digits")
    return raw


class Settings:
    db_path: str = os.environ.get("CANARY_DB", str(ROOT / "backend" / "canary.db"))
    # Demo PIN for the medical team mode. Change it anywhere outside a demo.
    medical_pin: str = _medical_pin(os.environ.get("CANARY_MEDICAL_PIN", "1961"))
    # Default PIN of each crew member's private space ("id:pin,..."). A PIN changed in the app is stored hashed
    # in the settings table and wins over this default until the demo is reset.
    control_pin: str = _medical_pin(os.environ.get("CANARY_CONTROL_PIN", "4242"))
    crew_pins: Dict[str, str] = _pins(os.environ.get("CANARY_CREW_PINS", "h:1001,k:1002,a:1003,t:1004"))
    # PBKDF2 rounds for PIN hashes. Leave the default: a stored hash does not record the count, so changing it
    # invalidates every stored PIN. The test suite lowers it to run fast.
    pin_iterations: int = int(os.environ.get("CANARY_PBKDF2_ITERATIONS", "100000"))
    token_secret: str = os.environ.get("CANARY_TOKEN_SECRET", secrets.token_hex(16))
    token_ttl_s: int = int(os.environ.get("CANARY_TOKEN_TTL", "3600"))
    # Communication delay runs this many times faster than real time in the demo.
    delay_speedup: float = float(os.environ.get("CANARY_DELAY_SPEEDUP", "20"))
    # NASA DONKI live space weather. DEMO_KEY works with low rate limits.
    nasa_api_key: str = os.environ.get("NASA_API_KEY", "DEMO_KEY")
    live_space_weather: bool = os.environ.get("CANARY_LIVE_SPACE_WEATHER", "0") == "1"
    # Auto selects the configured API key (Gemini first when both are present); none forces offline.
    llm_provider: str = os.environ.get("CANARY_LLM_PROVIDER", "auto").strip().lower()
    # Optional global model override. It applies only when CANARY_LLM_PROVIDER names a provider explicitly;
    # with "auto" each provider uses its own model below, so switching by API key never sends one provider's
    # model id to the other.
    llm_model: str = os.environ.get("CANARY_LLM_MODEL", "").strip()
    # Flash-Lite passed the live tool-calling smoke test (docs/ai/plan.md); keep in sync with env.example.
    gemini_model: str = os.environ.get("CANARY_GEMINI_MODEL", "gemini-3.1-flash-lite")
    anthropic_model: str = os.environ.get("CANARY_ANTHROPIC_MODEL", "claude-sonnet-5-5")
    llm_effort: str = os.environ.get("CANARY_LLM_EFFORT", "low")
    # After this many seconds the answer falls back to grounded rules. Raise it locally for slow networks.
    llm_timeout_s: float = float(os.environ.get("CANARY_LLM_TIMEOUT_S", "15"))
    # Tool-calling rounds per question, and tool calls per question across all rounds.
    llm_max_steps: int = int(os.environ.get("CANARY_LLM_MAX_STEPS", "3"))
    llm_max_tool_calls: int = int(os.environ.get("CANARY_LLM_MAX_TOOL_CALLS", "6"))
    # Knowledge base file, built offline by `make index`, read-only at runtime.
    kb_path: str = os.environ.get("CANARY_KB", str(ROOT / "backend" / "kb.db"))
    # Embedder for knowledge search: "local" (fastembed) or "none" (BM25 only).
    embedder: str = os.environ.get("CANARY_EMBEDDER", "local")
    frontend_dist: str = os.environ.get("CANARY_FRONTEND_DIST", str(ROOT / "frontend" / "dist"))
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
