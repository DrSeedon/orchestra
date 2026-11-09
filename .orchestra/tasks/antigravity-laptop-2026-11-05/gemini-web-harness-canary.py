"""Explicit operator probe: exactly one real Gemini Web generation through Harness."""
import asyncio
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

import app
from app.gemini_web_auth import gemini_web_readiness
from app.harness.gemini_web import GeminiWebClient
from app.models import get_model_spec, validate_harness_model_spec


async def main():
    result = {"model": "gemini-web/gemini-argon", "app_path": app.__file__,
              "actual_model_attribution": "not-exposed-by-client-output"}
    client = GeminiWebClient(result["model"])
    request = client._request

    async def capture(*args, **kwargs):
        response = await request(*args, **kwargs)
        if response is not None:
            for key in ("owner_match", "selected_model", "selected_display_name"):
                result[key] = response[key]
        return response

    client._request = capture
    started = time.monotonic()
    try:
        result["readiness"] = gemini_web_readiness()["ready"]
        validate_harness_model_spec(get_model_spec(result["model"]))
        events = [event async for event in client.stream(
            [{"role": "user", "content": "Reply with exactly OK."}], [],
        )]
        result["response_is_ok"] = "".join(e.text for e in events if e.kind == "text_delta").strip() == "OK"
        result["events"] = [e.kind for e in events]
        result["usage"] = events[-1].usage
        result["success"] = bool(result["response_is_ok"] and result.get("owner_match")
                                 and result.get("selected_model") == "gemini-argon")
    except Exception:
        result["success"] = False
        result["error"] = "Harness canary failed; no vendor diagnostics exported"
    finally:
        await client.aclose()
        result["duration_seconds"] = round(time.monotonic() - started, 3)
        result["helper_processes_remaining"] = len(client._processes)
        Path(__file__).with_name("gemini-web-harness-result.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2) + "\n")
        print(json.dumps(result, ensure_ascii=False))
    return 0 if result["success"] else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
