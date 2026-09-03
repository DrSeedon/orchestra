"""#208 Q3 — машинная часть судейства. Написано ДО возврата воркеров.

Конвенция-независимый грейдер: не предполагает, ВХОДЯТ ли cache-write токены в
`input_tokens` (это решение воркера). Ставку записи кеша выделяет конечной разностью:
две вызова, отличающиеся только числом write-токенов, дают Δcost/N = ставка записи.

Запуск: python3 grade.py <worktree>
"""
import importlib.util
import inspect
import json
import sys
from pathlib import Path

WT = Path(sys.argv[1])
SRC = WT / "app" / "backend_codex.py"


def load():
    # грузим ФАЙЛ воркера, не пакет: у него могут быть чужие зависимости
    spec = importlib.util.spec_from_file_location("wk_backend_codex", SRC)
    mod = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(WT))
    spec.loader.exec_module(mod)
    return mod


def call(fn, params, model, inp, cached, out, write):
    """Собрать вызов по ИМЕНАМ параметров, какие бы воркер ни выбрал."""
    kw = {}
    for p in params:
        low = p.lower()
        if low == "model" or "model" in low:
            kw[p] = model
        elif "write" in low or "creat" in low:
            kw[p] = write
        elif "cach" in low:
            kw[p] = cached
        elif "out" in low:
            kw[p] = out
        elif "in" in low:
            kw[p] = inp
        else:
            kw[p] = 0
    return fn(**kw)


def main():
    mod = load()
    fn = mod._codex_cost
    params = [p for p in inspect.signature(fn).parameters]
    res = {"signature": params, "prices_keys": sorted(mod.CODEX_TOKEN_PRICES)}

    has_write = any(("write" in p.lower() or "creat" in p.lower()) for p in params)
    res["A2_has_write_param"] = has_write

    N = 1_000_000
    if has_write:
        base = call(fn, params, "gpt-5.6-sol", N, 0, 0, 0)
        with_w = call(fn, params, "gpt-5.6-sol", N, 0, 0, N)
        res["sol_rate_input_per_1M"] = round(base, 6)
        res["sol_delta_per_1M_write"] = round(with_w - base, 6)
        # ожидание: 6.25 (ставка записи). 5.0 = всё ещё свежий вход. 0 = проигнорировано.
        # Две законные конвенции, воркер выбирает сам и обязан обосновать:
        #  (a) input ВКЛЮЧАЕТ write  -> cost(input=N, write=N) == N*write_rate
        #  (b) write АДДИТИВЕН       -> cost(input=N, write=N) == N*(input_rate+write_rate)
        # Неверно: == N*input_rate (проигнорировано) или == N*2*input_rate (посчитано свежим).
        ok = True
        for m, ir, wr in (("gpt-5.6-sol", 5.0, 6.25), ("gpt-5.6-terra", 2.0, 2.50),
                          ("gpt-5.6-luna", 0.2, 0.25)):
            b = call(fn, params, m, N, 0, 0, 0)
            w = call(fn, params, m, N, 0, 0, N)
            incl = abs(w - wr) < 0.001
            addi = abs(w - (ir + wr)) < 0.001
            res[f"{m}_base/withwrite"] = [round(b, 6), round(w, 6)]
            res[f"{m}_verdict"] = ("inclusive" if incl else "additive" if addi
                                   else "ignored" if abs(w - ir) < 0.001 else "WRONG")
            ok = ok and (incl or addi)
        res["A2_write_rate_ok"] = ok
    else:
        res["A2_write_rate_ok"] = False

    # кешированный вход не должен был съехать
    res["sol_cached_only"] = round(call(fn, params, "gpt-5.6-sol", N, N, 0, 0), 6)
    res["A2_cached_unchanged"] = abs(res["sol_cached_only"] - 0.5) < 0.001
    res["sol_output_only"] = round(call(fn, params, "gpt-5.6-sol", 0, 0, N, 0), 6)
    res["A2_output_unchanged"] = abs(res["sol_output_only"] - 30.0) < 0.001

    # A3 — Spark больше не ноль
    def probe(name):
        try:
            return ("value", call(fn, params, name, N, 0, 0, 0))
        except Exception as e:
            return (type(e).__name__, str(e)[:90])
    res["A3_spark"] = probe("gpt-5.3-codex-spark")
    res["A3_spark_not_silent_zero"] = res["A3_spark"] != ("value", 0.0)
    res["unknown_model"] = probe("no-such-model")
    print(json.dumps(res, indent=1, ensure_ascii=False))


main()
