"""One-shot isolated source mutations against V-1156 behavioral regression tests."""

import json
import os
from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / ".orchestra/tasks/V-1156/private"
UV = Path.home() / ".local/share/orchestra/tools/uv/0.11.28/bin/uv"
TEST = "tests/test_terra_v1156.py"
MUTATIONS = [
    ("wrong_alias", "app/models.py", '"terra": "gpt-6.1-terra",',
     '"terra": "gpt-6.1-sol",', "test_alias_reaches_native_model_and_request"),
    ("agent_flags_bypass", "app/models.py",
     'MANUAL_ONLY_MODEL_IDS = frozenset({"gpt-6-astra", "gpt-6.1-sol", "gpt-6.1-terra"})',
     'MANUAL_ONLY_MODEL_IDS = frozenset({"gpt-6-astra", "gpt-6.1-sol"})',
     "test_old_flags_and_billing_do_not_open_terra_to_agents"),
    ("wrong_provider", "app/models.py",
     'id="gpt-6.1-terra", name="GPT-6.1 Terra",\n        runtime="codex", provider="openai",',
     'id="gpt-6.1-terra", name="GPT-6.1 Terra",\n        runtime="codex", provider="x-ai",',
     "test_alias_reaches_native_model_and_request"),
    ("api_window_as_cli", "app/models.py",
     'id="gpt-6.1-terra", name="GPT-6.1 Terra",\n        runtime="codex", provider="openai", context_length=258400,',
     'id="gpt-6.1-terra", name="GPT-6.1 Terra",\n        runtime="codex", provider="openai", context_length=1050000,',
     "test_alias_reaches_native_model_and_request"),
    ("wrong_cached_rate", "app/backend_codex.py",
     '"gpt-6.1-terra": {"input": 1.0, "cached": 0.05,',
     '"gpt-6.1-terra": {"input": 1.0, "cached": 0.1,',
     "test_standard_api_equivalent_prices_charge_each_token_once"),
    ("wrong_write_rate", "app/backend_codex.py",
     '"gpt-6.1-terra": {"input": 1.0, "cached": 0.05, "write": 1.25,',
     '"gpt-6.1-terra": {"input": 1.0, "cached": 0.05, "write": 2.5,',
     "test_standard_api_equivalent_prices_charge_each_token_once"),
]


def main():
    results = []
    for label, relative, before, after, target in MUTATIONS:
        path = ROOT / relative
        original = path.read_bytes()
        source = original.decode()
        if source.count(before) != 1:
            raise RuntimeError(f"{label}: mutation anchor is not unique")
        try:
            path.write_text(source.replace(before, after))
            command = [str(UV), "run", "--frozen", "python", "-m", "pytest",
                       f"{TEST}::{target}", "-q", "--tb=short"]
            with (OUT / f"mutation-{label}.log").open("w") as output:
                run = subprocess.run(command, cwd=ROOT, env=os.environ.copy(),
                                     stdout=output, stderr=subprocess.STDOUT, timeout=90)
            log = (OUT / f"mutation-{label}.log").read_text()
            caught = run.returncode == 1 and f"FAILED {TEST}::{target}" in log
            results.append({"mutation": label, "returncode": run.returncode, "caught": caught})
        finally:
            path.write_bytes(original)
    (OUT / "mutations.json").write_text(json.dumps(results, indent=2) + "\n")
    print(json.dumps(results, indent=2))
    if not all(item["caught"] for item in results):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
