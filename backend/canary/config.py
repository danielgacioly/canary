"""Settings read from environment variables. Defaults are for local development only."""
import os
import pathlib
import secrets

ROOT = pathlib.Path(__file__).resolve().parents[2]


class Settings:
    db_path: str = os.environ.get("CANARY_DB", str(ROOT / "backend" / "canary.db"))
    # Demo PIN for the medical team mode. Change it anywhere outside a demo.
    medical_pin: str = os.environ.get("CANARY_MEDICAL_PIN", "1961")
    token_secret: str = os.environ.get("CANARY_TOKEN_SECRET", secrets.token_hex(16))
    token_ttl_s: int = int(os.environ.get("CANARY_TOKEN_TTL", "3600"))
    # Communication delay runs this many times faster than real time in the demo.
    delay_speedup: float = float(os.environ.get("CANARY_DELAY_SPEEDUP", "20"))
    # NASA DONKI live space weather. DEMO_KEY works with low rate limits.
    nasa_api_key: str = os.environ.get("NASA_API_KEY", "DEMO_KEY")
    live_space_weather: bool = os.environ.get("CANARY_LIVE_SPACE_WEATHER", "0") == "1"
    # AI assistant provider: "none" (default), "anthropic" or "local". See canary/assistant/providers.py
    llm_provider: str = os.environ.get("CANARY_LLM_PROVIDER", "none")
    frontend_dist: str = os.environ.get("CANARY_FRONTEND_DIST", str(ROOT / "frontend" / "dist"))


settings = Settings()
