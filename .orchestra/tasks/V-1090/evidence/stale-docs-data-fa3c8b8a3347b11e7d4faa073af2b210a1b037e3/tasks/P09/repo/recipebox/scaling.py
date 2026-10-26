"""Scaling recipes to a different number of servings, and display helpers."""
from recipebox.models import Ingredient, Recipe


def scale_recipe(recipe: Recipe, servings: int) -> Recipe:
    """Return a copy of a recipe with every quantity scaled to the given servings."""
    if servings <= 0:
        raise ValueError("servings must be positive, got {}".format(servings))
    factor = servings / recipe.servings
    scaled = [
        Ingredient(name=item.name, quantity=item.quantity * factor, unit=item.unit)
        for item in recipe.ingredients
    ]
    return Recipe(title=recipe.title, servings=servings, ingredients=scaled)


def round_quantity(value: float) -> float:
    """Round to a precision that makes sense in a kitchen."""
    if value >= 100:
        return float(round(value))
    if value >= 10:
        return round(value * 2) / 2
    return round(value, 2)


def format_quantity(value: float) -> str:
    """Format a rounded quantity without trailing zeros, e.g. 2.0 -> "2"."""
    return "{:g}".format(round_quantity(value))


def format_ingredient(ingredient: Ingredient) -> str:
    """Return a display line such as "200 g flour" or "2 eggs"."""
    amount = format_quantity(ingredient.quantity)
    if ingredient.unit == "pc":
        return "{} {}".format(amount, ingredient.name)
    return "{} {} {}".format(amount, ingredient.unit, ingredient.name)


def recipe_lines(recipe: Recipe) -> list[str]:
    """Return the printable lines of a recipe, title first."""
    header = "{} (serves {})".format(recipe.title, recipe.servings)
    return [header] + ["- " + format_ingredient(item) for item in recipe.ingredients]
