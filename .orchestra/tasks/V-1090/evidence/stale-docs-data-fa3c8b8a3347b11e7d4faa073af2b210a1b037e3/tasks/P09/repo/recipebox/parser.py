"""Parsing recipes from plain text.

A recipe file looks like this:

    # Pancakes (serves 4)
    200 g flour
    300 ml milk
    2 eggs
"""
import re

from recipebox.models import Ingredient, Recipe
from recipebox.units import unit_kind

_TITLE_RE = re.compile(r"^#\s*(.+?)\s*\(serves\s+(\d+)\)\s*$")
_LINE_RE = re.compile(r"^(\d+(?:\.\d+)?)\s+(.+)$")


def parse_ingredient_line(line: str) -> Ingredient:
    """Parse "200 g flour" or "2 eggs" into an ingredient."""
    match = _LINE_RE.match(line.strip())
    if match is None:
        raise ValueError("cannot parse ingredient line: {!r}".format(line))
    quantity = float(match.group(1))
    rest = match.group(2).split(maxsplit=1)
    if len(rest) == 2 and _is_unit(rest[0]):
        return Ingredient(name=rest[1].strip(), quantity=quantity, unit=rest[0].lower())
    return Ingredient(name=match.group(2).strip(), quantity=quantity, unit="pc")


def parse_recipe(text: str) -> Recipe:
    """Parse a whole recipe: a title line followed by ingredient lines."""
    lines = [line for line in text.splitlines() if line.strip()]
    if not lines:
        raise ValueError("empty recipe")
    title_match = _TITLE_RE.match(lines[0].strip())
    if title_match is None:
        raise ValueError("bad title line: {!r}".format(lines[0]))
    ingredients = [parse_ingredient_line(line) for line in lines[1:]]
    return Recipe(
        title=title_match.group(1),
        servings=int(title_match.group(2)),
        ingredients=ingredients,
    )


def load_recipe(file_name: str) -> Recipe:
    """Read and parse a recipe file."""
    with open(file_name, encoding="utf-8") as handle:
        return parse_recipe(handle.read())


def _is_unit(word: str) -> bool:
    """Return True if a word is a known unit symbol."""
    try:
        unit_kind(word)
    except ValueError:
        return False
    return word.strip() != ""
