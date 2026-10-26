"""Recipe and ingredient records."""
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Ingredient:
    """An amount of one ingredient, e.g. 200 g flour."""

    name: str
    quantity: float
    unit: str


@dataclass
class Recipe:
    """A titled list of ingredients for a number of servings."""

    title: str
    servings: int
    ingredients: list[Ingredient] = field(default_factory=list)

    def ingredient_names(self) -> list[str]:
        """Return the ingredient names in recipe order."""
        return [ingredient.name for ingredient in self.ingredients]

    def find_ingredient(self, name: str) -> Ingredient:
        """Return the ingredient with the given name (case-insensitive)."""
        for ingredient in self.ingredients:
            if ingredient.name.lower() == name.lower():
                return ingredient
        raise KeyError("no ingredient {!r} in {!r}".format(name, self.title))
