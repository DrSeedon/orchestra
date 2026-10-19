"""Bounded image loading for Telegram attachments and workspace image tools."""

import os
import stat
from io import BytesIO
from pathlib import Path

MAX_INLINE_IMAGE_BYTES = 20 * 1024 * 1024

_MIME_TYPES = {
    "PNG": "image/png",
    "JPEG": "image/jpeg",
    "WEBP": "image/webp",
    "GIF": "image/gif",
}


def _validated_mime(data: bytes) -> str:
    from PIL import Image

    try:
        with Image.open(BytesIO(data)) as image:
            image.verify()
            mime = _MIME_TYPES.get(image.format or "")
    except Exception as exc:
        raise ValueError("image bytes are not a valid supported image") from exc
    if not mime:
        raise ValueError("image MIME is not a supported PNG, JPEG, WEBP or GIF image")
    return mime


def read_image(path: str, allowed_root: str | Path, *, root_label: str = "workspace",
               direct_child: bool = False) -> tuple[Path, bytes, str]:
    """Read and validate one image that resolves inside an explicitly allowed root."""
    root = Path(allowed_root).resolve()
    candidate = Path(path)
    try:
        resolved = ((root / candidate).resolve(strict=True) if not candidate.is_absolute()
                    else candidate.resolve(strict=True))
    except OSError as exc:
        raise ValueError(f"image file unavailable: {path}: {exc}") from exc
    if (resolved == root or root not in resolved.parents
            or (direct_child and resolved.parent != root)):
        raise ValueError(f"image path is outside the {root_label}: {path}")

    try:
        fd = os.open(resolved, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        with os.fdopen(fd, "rb") as image_file:
            info = os.fstat(image_file.fileno())
            if not stat.S_ISREG(info.st_mode):
                raise ValueError(f"image path is not a regular file: {path}")
            if info.st_size > MAX_INLINE_IMAGE_BYTES:
                raise ValueError(f"image exceeds {MAX_INLINE_IMAGE_BYTES} bytes: {path}")
            data = image_file.read(MAX_INLINE_IMAGE_BYTES + 1)
        if len(data) > MAX_INLINE_IMAGE_BYTES:
            raise ValueError(f"image exceeds {MAX_INLINE_IMAGE_BYTES} bytes: {path}")
    except OSError as exc:
        raise ValueError(f"image file unavailable: {path}: {exc}") from exc
    return resolved, data, _validated_mime(data)
