"""Shared HTTP error envelopes for route modules."""

from fastapi.responses import JSONResponse


def keyed_auth_required(
    message: str = "", *, include_ok: bool = False,
) -> JSONResponse:
    error: dict[str, object] = {
        "code": "KEYED_AUTH_REQUIRED",
        "outcome_unknown": False,
    }
    if message:
        error["message"] = message
    payload: dict[str, object] = {"error": error}
    if include_ok:
        payload["ok"] = False
    return JSONResponse(payload, status_code=403)
