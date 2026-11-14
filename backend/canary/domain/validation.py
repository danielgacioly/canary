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
