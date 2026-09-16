"""Проба всех `:free` маршрутов OpenRouter на пригодность воркеру (#V-581).

Проверяется не «заявляет ли модель tools», а то, что решает на практике: доходит ли
она до КОНЦА нашего протокола инструментов — сделать корректный вызов с правильным
аргументом, принять результат и ответить по нему. Модель, которая зовёт инструмент,
но игнорирует его ответ, воркером быть не может.

Потолок расхода задан до первого вызова: 2 запроса на модель плюс максимум одна
повторная попытка на 429, общий бюджет времени 15 минут.
"""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request

API = "https://openrouter.ai/api/v1"
KEY = os.environ["OPENROUTER_API_KEY"]
MARKER = 4242  # ответ инструмента: в финальном тексте он обязан появиться
DEADLINE = time.time() + 15 * 60

TOOLS = [{
    "type": "function",
    "function": {
        "name": "line_count",
        "description": "Return the number of lines in a repository file.",
        "parameters": {
            "type": "object",
            "properties": {"path": {"type": "string", "description": "Repo-relative path"}},
            "required": ["path"],
        },
    },
}]
ASK = ("Use the line_count tool for the file app/quota_gate.py, then reply with the "
       "number it returned and nothing else.")


def call(model: str, messages: list, timeout: int = 90) -> tuple[int, dict, float]:
    body = json.dumps({"model": model, "messages": messages, "tools": TOOLS,
                       "tool_choice": "auto", "max_tokens": 700}).encode()
    req = urllib.request.Request(
        f"{API}/chat/completions", data=body,
        headers={"Authorization": f"Bearer {KEY}", "Content-Type": "application/json"},
    )
    started = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read()), time.time() - started
    except urllib.error.HTTPError as error:
        raw = error.read().decode("utf-8", "replace")[:400]
        try:
            payload = json.loads(raw)
        except Exception:
            payload = {"error": {"message": raw}}
        return error.code, payload, time.time() - started
    except Exception as error:  # таймаут/сеть — это тоже результат замера
        return 0, {"error": {"message": f"{type(error).__name__}: {error}"}}, time.time() - started


def probe(model: str) -> dict:
    out = {"model": model, "tool_call": False, "arg_ok": False, "used_result": False,
           "status": "", "seconds": 0.0, "note": ""}
    messages = [{"role": "user", "content": ASK}]
    code, data, took = call(model, messages)
    if code == 429:
        time.sleep(20)
        code, data, took = call(model, messages)
    out["seconds"] = round(took, 1)
    if code != 200:
        out["status"] = f"HTTP {code}"
        out["note"] = str((data.get("error") or {}).get("message", ""))[:160]
        return out
    choice = (data.get("choices") or [{}])[0]
    msg = choice.get("message") or {}
    calls = msg.get("tool_calls") or []
    if not calls:
        out["status"] = "no tool call"
        out["note"] = str(msg.get("content", ""))[:120]
        return out
    out["tool_call"] = True
    fn = (calls[0].get("function") or {})
    try:
        args = json.loads(fn.get("arguments") or "{}")
    except Exception:
        args = {}
    out["arg_ok"] = fn.get("name") == "line_count" and "quota_gate" in str(args.get("path", ""))
    messages += [
        {"role": "assistant", "content": msg.get("content") or "", "tool_calls": calls},
        {"role": "tool", "tool_call_id": calls[0].get("id", "call_1"),
         "name": "line_count", "content": str(MARKER)},
    ]
    code2, data2, took2 = call(model, messages)
    out["seconds"] = round(took + took2, 1)
    if code2 != 200:
        out["status"] = f"round2 HTTP {code2}"
        out["note"] = str((data2.get("error") or {}).get("message", ""))[:160]
        return out
    text = str(((data2.get("choices") or [{}])[0].get("message") or {}).get("content") or "")
    out["used_result"] = str(MARKER) in text
    out["status"] = "OK" if out["used_result"] and out["arg_ok"] else "incomplete"
    out["note"] = text.strip().replace("\n", " ")[:120]
    return out


def main() -> None:
    with urllib.request.urlopen(f"{API}/models", timeout=60) as resp:
        catalog = json.loads(resp.read())["data"]
    free = [m for m in catalog
            if m.get("id", "").endswith(":free")
            and "tools" in (m.get("supported_parameters") or [])]
    free.sort(key=lambda m: -(m.get("context_length") or 0))
    print(f"кандидатов :free с tools: {len(free)}\n", flush=True)
    results = []
    for spec in free:
        if time.time() > DEADLINE:
            print("бюджет времени исчерпан, остальные не опрошены", flush=True)
            break
        row = probe(spec["id"])
        row["context"] = spec.get("context_length")
        results.append(row)
        print(f"{row['status']:<14} {row['model']:<50} {row['seconds']:>6}s "
              f"call={row['tool_call']} arg={row['arg_ok']} used={row['used_result']} "
              f"| {row['note']}", flush=True)
    path = ".orchestra/tasks/V-581/probe-results.json"
    with open(path, "w") as handle:
        json.dump(results, handle, ensure_ascii=False, indent=2)
    ok = [r for r in results if r["status"] == "OK"]
    print(f"\nПРОШЛИ ПОЛНЫЙ ПРОТОКОЛ: {len(ok)} из {len(results)}")
    for row in ok:
        print(f"  {row['model']:<50} ctx={row['context']:<9} {row['seconds']}s")


if __name__ == "__main__":
    main()
