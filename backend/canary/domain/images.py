"""Photos sent by the crew (vital-sign displays, profile pictures). A picture is decoded before it is kept: its dimensions are
read from the file header and refused above a pixel limit before any pixel is decoded (no decompression bombs), then the
whole picture is decoded, so a truncated or corrupt file is refused too. Without Pillow only the strict header check of
validation.image_data_url applies. Each person may keep a limited number of check-in photos.
"""
import base64
import binascii
import io
from typing import Optional

from .. import db
from . import validation as V
from .validation import FieldError

try:  # Pillow is optional: without it the header check is the only check
    from PIL import Image  # type: ignore
except Exception:  # noqa: BLE001
    Image = None

MAX_PIXELS = 12_000_000  # 4000 x 3000: more than any display needs
MAX_SIDE = 6000
MAX_CHECKIN_PHOTOS = 60  # per person, kept in the database (a profile picture replaces the old one, it is not counted)
_FORMATS = {"image/png": "PNG", "image/jpeg": "JPEG", "image/webp": "WEBP"}


def check(value, label: str = "The photo", field: str = "photo") -> str:
    """The data URL of a picture that really is a PNG, JPEG or WebP, within the size and pixel limits. Raises FieldError."""
    value = V.image_data_url(value, label, field)  # prefix, base64, byte size and file signature
    if Image is None:
        return value
    head, _, body = value.partition(";base64,")
    try:
        raw = base64.b64decode(body, validate=True)
        im = Image.open(io.BytesIO(raw))  # reads the header only
        w, h = im.size
        if w < 1 or h < 1 or w > MAX_SIDE or h > MAX_SIDE or w * h > MAX_PIXELS:
            raise FieldError(field, f"{label} is too large in pixels ({w} x {h}; the limit is {MAX_SIDE} on a side and {MAX_PIXELS // 1_000_000} million pixels)")
        if im.format != _FORMATS[head[5:]]:
            raise FieldError(field, f"{label} is not a real {_FORMATS[head[5:]]} image")
        im.load()  # decodes every pixel: a truncated or damaged file fails here, not later in a chart or a report
    except FieldError:
        raise
    except (binascii.Error, ValueError, OSError, SyntaxError, KeyError, Image.DecompressionBombError):
        raise FieldError(field, f"{label} is not valid image data")
    return value


def checkin_photos_of(crew_id: str) -> int:
    return db.q("SELECT COUNT(*) n FROM checkin_photos WHERE crew_id=?", (crew_id,))[0]["n"]


def room_for_checkin_photo(crew_id: str) -> None:
    """Refuse a check-in photo once the person has kept the maximum (FieldError, 422, nothing stored)."""
    if checkin_photos_of(crew_id) >= MAX_CHECKIN_PHOTOS:
        raise FieldError("photo", f"The photo store is full for this person ({MAX_CHECKIN_PHOTOS} photos); ask the medical team to clear old ones")


def check_checkin_photo(value, crew_id: str) -> Optional[str]:
    room_for_checkin_photo(crew_id)
    return check(value, "The photo of the display")
