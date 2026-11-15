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


# ---------------------------------------------------------------- incoming measurements (rows of observations)
import re as _re  # noqa: E402
from datetime import datetime as _dt, timedelta as _td  # noqa: E402

OBS_ORIGINS = ("real", "simulated")
OBS_METHODS = ("wearable", "manual", "test", "blood", "urine", "environment", "dosimeter", "lab", "sensor")
OBS_DEFAULTS = {"origin": "real", "method": "sensor", "source": "api", "note": ""}
MAX_ERRORS = 50  # a batch with thousands of bad rows reports the first ones, not all of them
_ISO = _re.compile(r"^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.\d+)?(?:Z|[+-]00:?00)$")
_TIME = _re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


class ObsContext:
    """What a batch is checked against: the people who exist and the launch date that turns a day into a date."""

    def __init__(self, crew_ids: Iterable[str], launch_date: str):
        from . import catalog
        self.crew = set(crew_ids) | {catalog.CABIN_ID}
        self.launch = date.fromisoformat(launch_date)
        self._by_stamp: Dict[str, int] = {}
        self._by_day: Dict[int, str] = {}

    def day_of(self, stamp: str) -> Optional[int]:
        """Mission day of an ISO UTC timestamp like 2035-06-01T08:00:00Z, or None when it is not a real timestamp."""
        d = self._by_stamp.get(stamp)
        if d is None:
            m = _ISO.match(stamp)
            if not m:
                return None
            try:
                _dt(*(int(g) for g in m.groups()))
                d = (date(int(m.group(1)), int(m.group(2)), int(m.group(3))) - self.launch).days
            except ValueError:
                return None
            self._by_stamp[stamp] = d
        return d

    def stamp_of(self, day: int) -> str:
        s = self._by_day.get(day)
        if s is None:
            s = self._by_day[day] = (self.launch + _td(days=day)).isoformat() + "T08:00:00Z"
        return s


def observation_row(i: int, raw: Any, ctx: ObsContext, prefix: str = "rows") -> tuple:
    """One measurement, checked: (crew_id, day, indicator, value, unit, origin, method, source, note, measured_at).

    Raises FieldError with the path of the first thing wrong, like `rows.12.value`. A row has `crew_id` (a registered
    person or `cabin`), `indicator`, `value`, `unit`, and `measured_at` (ISO UTC, e.g. 2035-06-01T08:00:00Z) or `day`
    (mission day; the reading is stamped at 08:00 UTC of that day). `origin`, `method`, `source` and `note` are optional.
    """
    from . import catalog
    path = f"{prefix}.{i}"
    if not isinstance(raw, dict):
        raise FieldError(path, "A reading must be an object")
    crew = raw.get("crew_id")
    if crew is None or crew == "":
        raise FieldError(f"{path}.crew_id", "crew_id is required")
    if not isinstance(crew, str) or crew not in ctx.crew:
        raise FieldError(f"{path}.crew_id", f"Unknown crew id: {_shorten(crew)}")
    ind = raw.get("indicator")
    if ind is None or ind == "":
        raise FieldError(f"{path}.indicator", "indicator is required")
    spec = catalog.ACCEPT.get(ind) if isinstance(ind, str) else None
    if spec is None:
        raise FieldError(f"{path}.indicator", f"Unknown indicator: {_shorten(ind)}")
    v = raw.get("value")
    if v is None or v == "":
        raise FieldError(f"{path}.value", "value is required")
    if isinstance(v, str):
        try:
            v = float(v)
        except ValueError:
            raise FieldError(f"{path}.value", "value must be a number")
    if isinstance(v, bool) or not isinstance(v, (int, float)) or math.isnan(v) or math.isinf(v):
        raise FieldError(f"{path}.value", "value must be a number")
    lo, hi = spec["range"]
    if not lo <= v <= hi:
        raise FieldError(f"{path}.value", f"{ind} must be between {_fmt(lo)} and {_fmt(hi)} {spec['units'][0]}")
    unit = raw.get("unit")
    if unit is None or unit == "":
        raise FieldError(f"{path}.unit", "unit is required")
    if unit not in spec["units"]:
        raise FieldError(f"{path}.unit", f"{ind} is measured in {' or '.join(spec['units'])}, not {_shorten(unit)}")
    stamp, day = raw.get("measured_at"), raw.get("day")
    if stamp not in (None, ""):
        if not isinstance(stamp, str):
            raise FieldError(f"{path}.measured_at", "measured_at must be a UTC time like 2035-06-01T08:00:00Z")
        d = ctx.day_of(stamp)
        if d is None:
            raise FieldError(f"{path}.measured_at", "measured_at must be a real UTC time like 2035-06-01T08:00:00Z")
        if day not in (None, ""):
            try:
                same = int(day) == d
            except (TypeError, ValueError):
                same = False
            if not same:
                raise FieldError(f"{path}.day", "day does not match measured_at")
        day = d
    elif day not in (None, ""):
        try:
            if isinstance(day, bool) or (isinstance(day, float) and day != int(day)):
                raise ValueError
            day = int(day)
        except (TypeError, ValueError):
            raise FieldError(f"{path}.day", "day must be a whole number of mission days")
        if not -3650 <= day <= 36500:
            raise FieldError(f"{path}.day", "day is outside the mission")
        stamp = ctx.stamp_of(day)
    else:
        raise FieldError(f"{path}.measured_at", "Send measured_at (UTC time) or day")
    out = []
    for k, max_len, options in (("origin", 20, OBS_ORIGINS), ("method", 20, OBS_METHODS), ("source", 80, None), ("note", 200, None)):
        x = raw.get(k)
        x = OBS_DEFAULTS[k] if x is None or x == "" else x
        if not isinstance(x, str) or len(x) > max_len:
            raise FieldError(f"{path}.{k}", f"{k} must be text of at most {max_len} characters")
        if options and x not in options:
            raise FieldError(f"{path}.{k}", f"{k} must be one of: {', '.join(options)}")
        out.append(x)
    return (crew, day, ind, float(v), unit, out[0], out[1], out[2], out[3], stamp)


def _shorten(x: Any, n: int = 40) -> str:
    s = str(x)
    return s if len(s) <= n else s[:n] + "..."


def observation_rows(rows: Any, ctx: ObsContext, prefix: str = "rows", file: str = "") -> List[tuple]:
    """Check every row; raises ValidationFailure with up to MAX_ERRORS field errors (all-or-nothing: the caller writes
    only when this returns)."""
    if not isinstance(rows, list):
        raise FieldError(prefix, "rows must be a list of readings")
    out, errs = [], []
    for i, raw in enumerate(rows):
        try:
            out.append(observation_row(i, raw, ctx, prefix))
        except FieldError as e:
            errs.append({"field": e.field, "message": (file + ": " if file else "") + e.message})
            if len(errs) >= MAX_ERRORS:
                break
    if errs:
        raise ValidationFailure(errs)
    return out


def clock_time(value: Any, field: str) -> str:
    if not isinstance(value, str) or not _TIME.match(value):
        raise FieldError(field, "must be a time like 12:00")
    return value
