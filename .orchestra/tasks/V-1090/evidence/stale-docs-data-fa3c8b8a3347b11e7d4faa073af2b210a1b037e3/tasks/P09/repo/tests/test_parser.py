import pytest

from recipebox.models import Ingredient
from recipebox.parser import load_recipe, parse_ingredient_line, parse_recipe

PANCAKES = """
# Pancakes (serves 4)
200 g flour
300 ml milk
2 eggs
1 tbsp sugar
"""


def test_parse_ingredient_with_unit():
    assert parse_ingredient_line("200 g flour") == Ingredient("flour", 200.0, "g")
    assert parse_ingredient_line("1.5 Cup milk") == Ingredient("milk", 1.5, "cup")


def test_parse_ingredient_without_unit():
    assert parse_ingredient_line("2 eggs") == Ingredient("eggs", 2.0, "pc")
    assert parse_ingredient_line("3 large apples") == Ingredient("large apples", 3.0, "pc")


def test_parse_recipe():
    recipe = parse_recipe(PANCAKES)
    assert recipe.title == "Pancakes"
    assert recipe.servings == 4
    assert recipe.ingredient_names() == ["flour", "milk", "eggs", "sugar"]
    assert recipe.find_ingredient("MILK").quantity == 300.0


def test_parse_errors():
    with pytest.raises(ValueError):
        parse_recipe("")
    with pytest.raises(ValueError):
        parse_recipe("Pancakes\n200 g flour")
    with pytest.raises(ValueError):
        parse_ingredient_line("some flour")


def test_load_recipe(tmp_path):
    recipe_file = tmp_path / "pancakes.txt"
    recipe_file.write_text(PANCAKES, encoding="utf-8")
    recipe = load_recipe(str(recipe_file))
    assert recipe.title == "Pancakes"
    assert len(recipe.ingredients) == 4
