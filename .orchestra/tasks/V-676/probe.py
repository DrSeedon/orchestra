#!/usr/bin/env python3
"""V-676: измеряем срок жизни prefix-кеша маршрута OpenRouter.

Для каждой паузы — независимая проба со СВОИМ префиксом (уникальный маркер в начале,
поэтому кеши проб не пересекаются): тёплый вызов пишет кеш, через паузу повторный вызов
тем же префиксом читает cached_tokens. Провайдер закреплён, чтобы тёплый и пробный
вызовы попали в один кеш. Пробы идут параллельно, общее время ≈ максимальной паузе.
Результат — JSONL, его читает оркестратор после сигнала таймера.
"""
import asyncio
import json
import os
import time
import uuid
from pathlib import Path

import httpx

HERE = Path(__file__).resolve().parent
OUT = HERE / "results.jsonl"
DONE = HERE / "DONE"
URL = "https://openrouter.ai/api/v1/chat/completions"

# (модель, провайдер для пина). Провайдер — тот, что реально отдавал нам ответы.
ROUTES = [
    ("deepseek/deepseek-v4.1-flash", "DeepInfra"),
    ("deepseek/deepseek-v4.1-flash", "StreamLake"),
    ("deepseek/deepseek-v4.1-flash", "Together"),
]
DELAYS_MIN = [1, 2, 5, 10, 20, 30, 45, 60, 90, 120]

# ~4000 токенов стабильного префикса: выше минимума кеша у провайдеров.
FILLER = ("The quick brown fox jumps over the lazy dog near the riverbank. " * 6 + "\n") * 90


def _key() -> str:
    for line in (Path("/home/kesha/orchestra/.env")).read_text().splitlines():
        if line.startswith("OPENROUTER_API_KEY="):
            return line.split("=", 1)[1].strip()
    raise SystemExit("no OPENROUTER_API_KEY")


async def call(client, key, model, provider, marker):
    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": f"SESSION {marker}\n{FILLER}"},
            {"role": "user", "content": "Reply with the single word: ok"},
        ],
        "max_tokens": 3,
        "usage": {"include": True},
        "provider": {"order": [provider], "allow_fallbacks": False},
    }
    r = await client.post(URL, headers={"Authorization": f"Bearer {key}"}, json=body, timeout=120)
    j = r.json()
    u = j.get("usage") or {}
    det = u.get("prompt_tokens_details") or {}
    return {
        "http": r.status_code,
        "provider": j.get("provider"),
        "prompt_tokens": u.get("prompt_tokens"),
        "cached": det.get("cached_tokens") if isinstance(det, dict) else None,
        "cost": u.get("cost"),
        "err": (j.get("error") or {}).get("message") if isinstance(j.get("error"), dict) else j.get("error"),
    }


async def trial(client, key, model, provider, delay_min):
    marker = uuid.uuid4().hex
    rec = {"model": model, "pin_provider": provider, "delay_min": delay_min, "marker": marker}
    try:
        rec["warm"] = await call(client, key, model, provider, marker)
        await asyncio.sleep(delay_min * 60)
        rec["probe"] = await call(client, key, model, provider, marker)
    except Exception as e:
        rec["exception"] = repr(e)
    rec["ts"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    with OUT.open("a") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return rec


async def main():
    key = _key()
    async with httpx.AsyncClient() as client:
        tasks = [trial(client, key, m, p, d) for (m, p) in ROUTES for d in DELAYS_MIN]
        await asyncio.gather(*tasks)
    DONE.write_text(time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))


if __name__ == "__main__":
    asyncio.run(main())
