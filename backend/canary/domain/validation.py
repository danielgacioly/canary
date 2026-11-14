"""Input checks shared by every form on the server.

The web app checks the same rules before it sends anything (frontend/src/lib/validate.ts), but the server never
trusts that: a bad value is refused here with a 422 and `detail: [{"field", "message"}]`, and nothing is written.

The ranges are typing limits (they catch typos and impossible numbers). They are NOT clinical ranges and say
nothing about what is healthy. Every one is a prototype assumption (`verified: false`).
"""
import math
from datetime import date
from typing import Any, Dict, Iterable, List, Optional


class ValidationFailure(ValueError):
    """One or more field errors. `errors` is the list sent back as `detail`."""

    def __init__(self, errors: List[Dict[str, str]]):
        self.errors = errors
        super().__init__("; ".join(e["message"] for e in errors))


class FieldError(ValidationFailure):
    """One field is wrong: `field` names it and `message` says what to fix."""

    def __init__(self, field: str, message: str):
        self.field, self.message = field, message
        super().__init__([{"field": field, "message": message}])


def _fmt(n: float) -> str:
    return str(int(n)) if float(n).is_integer() else str(n)


def _unit(unit: str) -> str:
    return f" {unit}" if unit else ""


def number(payload: dict, key: str, label: str, lo: float, hi: float, unit: str = "", integer: bool = False,
           decimals: Optional[int] = None, required: bool = False, field: Optional[str] = None) -> Optional[float]:
    """A number in [lo, hi]. None when absent and not required. Booleans, strings and NaN are not numbers."""
    field = field or key
    v = payload.get(key)
    if v is None:
        if required:
            raise FieldError(field, f"{label} is required")
        return None
    if isinstance(v, bool) or not isinstance(v, (int, float)) or math.isnan(v) or math.isinf(v):
        raise FieldError(field, f"{label} must be a number")
    if integer and v != int(v):
        raise FieldError(field, f"{label} must be a whole number")
    if decimals is not None and round(v, decimals) != v:
        raise FieldError(field, f"{label} can have at most {decimals} decimal place{'s' if decimals != 1 else ''}")
    if not lo <= v <= hi:
        raise FieldError(field, f"{label} must be between {_fmt(lo)} and {_fmt(hi)}{_unit(unit)}")
    return v


def text(payload: dict, key: str, label: str, min_len: int = 0, max_len: int = 200, required: bool = False,
         field: Optional[str] = None) -> str:
    """A string whose trimmed length is within bounds. Anything that is not a string is refused."""
    field = field or key
    v = payload.get(key)
    if v is None:
        v = ""
    if not isinstance(v, str):
        raise FieldError(field, f"{label} must be text")
    n = len(v.strip())
    if n == 0 and required:
        raise FieldError(field, f"{label} is required")
    if n and n < min_len:
        raise FieldError(field, f"{label} must be at least {min_len} characters")
    if len(v) > max_len:
        raise FieldError(field, f"{label} must be at most {max_len} characters")
    return v


def one_of(payload: dict, key: str, label: str, options: Iterable[Any], required: bool = False, field: Optional[str] = None) -> Any:
    field = field or key
    options = list(options)
    v = payload.get(key)
    if v is None or v == "":
        if required:
            raise FieldError(field, f"{label} is required")
        return v
    if v not in options:
        raise FieldError(field, f"{label} must be one of: {', '.join(str(o) for o in options)}")
    return v


def clock(payload: dict, key: str, label: str, field: Optional[str] = None) -> str:
    """A 24-hour time, HH:MM."""
    field = field or key
    v = payload.get(key)
    if not v:
        raise FieldError(field, f"{label} is required")
    if not isinstance(v, str) or len(v) != 5 or v[2] != ":" or not (v[:2] + v[3:]).isdigit() or int(v[:2]) > 23 or int(v[3:]) > 59:
        raise FieldError(field, f"{label} must be a time like 23:30")
    return v


def parse_date(value: str, label: str, field: str) -> date:
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError):
        raise FieldError(field, f"{label} is not a real date")


def age_on(dob: date, day: date) -> int:
    return day.year - dob.year - ((day.month, day.day) < (dob.month, dob.day))


PHOTO_MAX_CHARS = 600_000  # the whole data URL; the web app sends ~1024 px JPEGs well under this
_PHOTO_TYPES = {"image/jpeg": (b"\xff\xd8\xff",), "image/png": (b"\x89PNG\r\n\x1a\n",), "image/webp": (b"RIFF",)}


def image_data_url(value: Any, label: str = "The photo", field: str = "photo", max_chars: int = PHOTO_MAX_CHARS) -> str:
    """A base64 data URL of a JPEG, PNG or WebP picture (checked by its first bytes, not by what it says it is)."""
    import base64
    import binascii
    if not isinstance(value, str) or not value.startswith("data:") or ";base64," not in value:
        raise FieldError(field, f"{label} must be an image sent as a base64 data URL")
    head, _, body = value.partition(";base64,")
    mime = head[5:]
    if mime not in _PHOTO_TYPES:
        raise FieldError(field, f"{label} must be a PNG, JPEG or WebP image")
    if len(value) > max_chars:
        raise FieldError(field, f"{label} is too large ({len(value) // 1000} KB; the limit is {max_chars // 1000} KB)")
    try:
        raw = base64.b64decode(body, validate=True)
    except (binascii.Error, ValueError):
        raise FieldError(field, f"{label} is not valid image data")
    if not any(raw.startswith(m) for m in _PHOTO_TYPES[mime]) or (mime == "image/webp" and raw[8:12] != b"WEBP"):
        raise FieldError(field, f"{label} is not a real {mime.split('/')[1].upper()} image")
    return value
