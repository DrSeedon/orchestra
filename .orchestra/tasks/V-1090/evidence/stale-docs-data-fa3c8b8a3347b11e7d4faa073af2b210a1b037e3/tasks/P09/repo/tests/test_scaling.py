import pytest

from recipebox.models import Ingredient, Recipe
from recipebox.scaling import (
    format_ingredient,
    format_quantity,
    recipe_lines,
    round_quantity,
    scale_recipe,
)


def make_recipe():
    return Recipe(
        title="Bread",
        servings=2,
        ingredients=[Ingredient("flour", 500.0, "g"), Ingredient("yeast", 7.0, "g")],
    )


def test_scale_recipe_doubles():
    scaled = scale_recipe(make_recipe(), 4)
    assert scaled.servings == 4
    assert [item.quantity for item in scaled.ingredients] == [1000.0, 14.0]


def test_scale_recipe_keeps_original():
    recipe = make_recipe()
    scale_recipe(recipe, 1)
    assert recipe.ingredients[0].quantity == 500.0


def test_scale_recipe_rejects_zero():
    with pytest.raises(ValueError):
        scale_recipe(make_recipe(), 0)


def test_round_and_format_quantity():
    assert round_quantity(123.4) == 123.0
    assert round_quantity(12.3) == 12.5
    assert round_quantity(1.234) == 1.23
    assert format_quantity(2.0) == "2"


def test_format_lines():
    assert format_ingredient(Ingredient("eggs", 2.0, "pc")) == "2 eggs"
    assert recipe_lines(make_recipe()) == ["Bread (serves 2)", "- 500 g flour", "- 7 g yeast"]
