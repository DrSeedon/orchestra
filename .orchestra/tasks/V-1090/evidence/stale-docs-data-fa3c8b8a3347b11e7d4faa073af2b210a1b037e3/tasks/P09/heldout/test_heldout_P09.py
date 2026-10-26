import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENTRY = "recipebox.shopping"

RECIPES = {
    "pancakes.txt": "# Pancakes (serves 4)\n200 g flour\n300 ml milk\n2 eggs\n1 tbsp sugar\n",
    "bread.txt": "# Bread (serves 2)\n0.5 kg Flour\n7 g yeast\n250 ml water\n1 tsp sugar\n1 tsp salt\n",
    "omelette.txt": "# Omelette (serves 1)\n3 eggs\n1 tbsp butter\n",
    "cake.txt": "# Cake (serves 8)\n200 g butter\n4 eggs\n250 g sugar\n",
}


def write_recipes(folder):
    os.makedirs(folder, exist_ok=True)
    for name, text in RECIPES.items():
        with open(os.path.join(folder, name), "w", encoding="utf-8") as handle:
            handle.write(text)


def write_plan(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(text)


def run(plan, output):
    return subprocess.run(
        [sys.executable, "-m", ENTRY, str(plan), str(output)],
        cwd=ROOT, capture_output=True, text=True, timeout=120,
    )


def read_json(path):
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def test_shopping_list_for_two_recipes(tmp_path):
    write_recipes(str(tmp_path))
    plan = tmp_path / "week.txt"
    write_plan(str(plan), "pancakes.txt 8\n\nbread.txt   1\n")
    output = tmp_path / "list.json"
    proc = run(plan, output)
    assert proc.returncode == 0, proc.stderr
    assert read_json(output) == {
        "items": [
            {"name": "eggs", "quantity": 4, "unit": "pc", "recipes": ["Pancakes"]},
            {"name": "flour", "quantity": 650, "unit": "g", "recipes": ["Pancakes", "Bread"]},
            {"name": "milk", "quantity": 600, "unit": "ml", "recipes": ["Pancakes"]},
            {"name": "salt", "quantity": 2.46, "unit": "ml", "recipes": ["Bread"]},
            {"name": "sugar", "quantity": 32, "unit": "ml", "recipes": ["Pancakes", "Bread"]},
            {"name": "water", "quantity": 125, "unit": "ml", "recipes": ["Bread"]},
            {"name": "yeast", "quantity": 3.5, "unit": "g", "recipes": ["Bread"]},
        ],
        "lines": [
            "4 eggs (Pancakes)",
            "650 g flour (Pancakes, Bread)",
            "600 ml milk (Pancakes)",
            "2.46 ml salt (Bread)",
            "32 ml sugar (Pancakes, Bread)",
            "125 ml water (Bread)",
            "3.5 g yeast (Bread)",
        ],
    }


def test_units_kept_apart_and_repeated_recipe(tmp_path):
    write_recipes(str(tmp_path))
    plan = tmp_path / "week.txt"
    write_plan(str(plan), "omelette.txt 2\ncake.txt 4\nomelette.txt 1\n")
    output = tmp_path / "list.json"
    proc = run(plan, output)
    assert proc.returncode == 0, proc.stderr
    assert read_json(output) == {
        "items": [
            {"name": "butter", "quantity": 100, "unit": "g", "recipes": ["Cake"]},
            {"name": "butter", "quantity": 44.5, "unit": "ml", "recipes": ["Omelette"]},
            {"name": "eggs", "quantity": 11, "unit": "pc", "recipes": ["Omelette", "Cake"]},
            {"name": "sugar", "quantity": 125, "unit": "g", "recipes": ["Cake"]},
        ],
        "lines": [
            "100 g butter (Cake)",
            "44.5 ml butter (Omelette)",
            "11 eggs (Omelette, Cake)",
            "125 g sugar (Cake)",
        ],
    }


def test_recipe_files_found_next_to_plan(tmp_path):
    write_recipes(str(tmp_path / "recipes"))
    plan = tmp_path / "plans" / "week.txt"
    write_plan(str(plan), "../recipes/cake.txt 8\n")
    output = tmp_path / "list.json"
    proc = run(plan, output)
    assert proc.returncode == 0, proc.stderr
    assert read_json(output)["lines"] == [
        "200 g butter (Cake)",
        "4 eggs (Cake)",
        "250 g sugar (Cake)",
    ]


def test_missing_recipe_fails(tmp_path):
    write_recipes(str(tmp_path))
    output = tmp_path / "list.json"
    plan = tmp_path / "week.txt"
    write_plan(str(plan), "pancakes.txt 4\nsoup.txt 2\n")
    assert run(plan, output).returncode == 2
    assert not output.exists()
    assert run(tmp_path / "nothing.txt", output).returncode == 2
    assert not output.exists()


def test_bad_servings_fail(tmp_path):
    write_recipes(str(tmp_path))
    output = tmp_path / "list.json"
    plan = tmp_path / "week.txt"
    for line in ("pancakes.txt 0", "pancakes.txt two", "pancakes.txt", "pancakes.txt -3"):
        write_plan(str(plan), "bread.txt 2\n" + line + "\n")
        assert run(plan, output).returncode == 2, line
        assert not output.exists()


def test_unparsable_recipe_fails(tmp_path):
    write_recipes(str(tmp_path))
    with open(tmp_path / "notes.txt", "w", encoding="utf-8") as handle:
        handle.write("Soup for two\n1 l water\n")
    output = tmp_path / "list.json"
    plan = tmp_path / "week.txt"
    write_plan(str(plan), "cake.txt 8\nnotes.txt 2\n")
    assert run(plan, output).returncode == 2
    assert not output.exists()
