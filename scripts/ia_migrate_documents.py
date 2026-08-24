"""Administrative entry point for the reversible document cutover."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from app.ia.cutover import DocumentCutoverError, cutover_api


def migration_api(request: Mapping[str, Any]) -> Mapping[str, Any]:
    """Run the shadow-import transition through the configured cutover owner."""

    if not isinstance(request, Mapping) or request.get("operation") != "shadow":
        raise DocumentCutoverError("migration operation must be 'shadow'")
    return cutover_api(request)
