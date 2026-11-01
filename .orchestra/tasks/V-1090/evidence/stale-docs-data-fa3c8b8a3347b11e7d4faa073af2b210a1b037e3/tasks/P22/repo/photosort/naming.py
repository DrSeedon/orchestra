"""Recognise photo files and read the day a photo was taken from its file name."""
import logging
import re
from datetime import date
from typing import List, Optional

logger = logging.getLogger(__name__)

PHOTO_EXTENSIONS = (".jpg", ".jpeg", ".png", ".heic", ".tif", ".tiff")

# Camera names: IMG_20240315_101500.jpg, PXL_20231231_235959123.jpg, VID-20240101-120000.
_COMPACT = re.compile(r"(?<!\d)(\d{4})(\d{2})(\d{2})[_-]\d{6}")
# Exported names: 2024-01-05 08.00.00.png, Screenshot 2024-02-29 at 10.11.12.png.
_DASHED = re.compile(r"(?<!\d)(\d{4})-(\d{2})-(\d{2})(?!\d)")
DATE_PATTERNS: List[re.Pattern] = [_COMPACT, _DASHED]


def is_photo(name: str) -> bool:
    """Tell whether a file name ends in one of the photo extensions, in any case."""
    return name.lower().endswith(PHOTO_EXTENSIONS)


def date_from_name(name: str) -> Optional[date]:
    """Read the day a photo was taken from its file name.

    The patterns in DATE_PATTERNS are tried in order. A match that is not a real
    calendar day (such as 20231399) is ignored. Returns None when no pattern gives
    a valid day.
    """
    for pattern in DATE_PATTERNS:
        match = pattern.search(name)
        if not match:
            continue
        year, month, day = (int(part) for part in match.groups())
        try:
            return date(year, month, day)
        except ValueError:
            logger.debug("ignoring impossible date %s in %s", match.group(0), name)
    return None
