"""Saved custom recipes for one-touch ordering (feature F7)."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from .catalog import Customization

MAX_NAME = 30


class RecipeError(ValueError):
    """Raised for invalid recipe operations; the message is user-facing."""


@dataclass(frozen=True)
class Recipe:
    """A named, saved customisation of a drink."""

    id: int
    user_id: int
    name: str
    drink_id: int
    custom: Customization


def _row_to_recipe(row: sqlite3.Row) -> Recipe:
    """Map a ``recipes`` row to a :class:`Recipe`.

    Args:
        row: database row.

    Returns:
        Recipe: the recipe.
    """
    custom = Customization(milk=row["milk"], strength=row["strength"],
                           temperature=row["temperature"], syrup=row["syrup"],
                           syrup_shots=row["syrup_shots"], extra_shot=bool(row["extra_shot"]))
    return Recipe(row["id"], row["user_id"], row["name"], row["drink_id"], custom)


def _check_name(conn: sqlite3.Connection, user_id: int, name: str,
                exclude_id: int | None = None) -> str:
    """Validate a recipe name and make sure it is unique for the user.

    Args:
        conn: open database connection.
        user_id: owner.
        name: proposed name.
        exclude_id: recipe id to ignore (when renaming itself).

    Returns:
        str: the trimmed name.

    Raises:
        RecipeError: empty, too long or duplicate name.
    """
    name = name.strip()
    if not name:
        raise RecipeError("Please give the recipe a name.")
    if len(name) > MAX_NAME:
        raise RecipeError(f"Name must be at most {MAX_NAME} characters.")
    row = conn.execute("SELECT id FROM recipes WHERE user_id = ? AND lower(name) = lower(?)",
                       (user_id, name)).fetchone()
    if row and row["id"] != exclude_id:
        raise RecipeError(f"You already have a recipe called '{name}'.")
    return name


def save_recipe(conn: sqlite3.Connection, user_id: int, name: str, drink_id: int,
                custom: Customization) -> Recipe:
    """Save a new named recipe to the user's profile.

    Args:
        conn: open database connection.
        user_id: owner (must be logged in).
        name: unique recipe name for this user.
        drink_id: base drink.
        custom: customisation to store.

    Returns:
        Recipe: the saved recipe.

    Raises:
        RecipeError: invalid or duplicate name.
    """
    name = _check_name(conn, user_id, name)
    cur = conn.execute(
        "INSERT INTO recipes (user_id, name, drink_id, milk, strength, temperature, syrup,"
        " syrup_shots, extra_shot) VALUES (?,?,?,?,?,?,?,?,?)",
        (user_id, name, drink_id, custom.milk, custom.strength, custom.temperature,
         custom.syrup, custom.syrup_shots, int(custom.extra_shot)),
    )
    conn.commit()
    return get_recipe(conn, int(cur.lastrowid))


def update_recipe(conn: sqlite3.Connection, recipe_id: int, name: str,
                  custom: Customization) -> Recipe:
    """Rename and/or modify a saved recipe.

    Args:
        conn: open database connection.
        recipe_id: recipe to change.
        name: new (or same) name.
        custom: new customisation.

    Returns:
        Recipe: updated recipe.

    Raises:
        RecipeError: recipe missing, or invalid/duplicate name.
    """
    old = get_recipe(conn, recipe_id)
    name = _check_name(conn, old.user_id, name, exclude_id=recipe_id)
    conn.execute(
        "UPDATE recipes SET name = ?, milk = ?, strength = ?, temperature = ?, syrup = ?,"
        " syrup_shots = ?, extra_shot = ? WHERE id = ?",
        (name, custom.milk, custom.strength, custom.temperature, custom.syrup,
         custom.syrup_shots, int(custom.extra_shot), recipe_id),
    )
    conn.commit()
    return get_recipe(conn, recipe_id)


def delete_recipe(conn: sqlite3.Connection, recipe_id: int) -> None:
    """Delete a saved recipe.

    Args:
        conn: open database connection.
        recipe_id: recipe to delete.

    Returns:
        None.
    """
    conn.execute("DELETE FROM recipes WHERE id = ?", (recipe_id,))
    conn.commit()


def get_recipe(conn: sqlite3.Connection, recipe_id: int) -> Recipe:
    """Load one recipe.

    Args:
        conn: open database connection.
        recipe_id: primary key.

    Returns:
        Recipe: the recipe.

    Raises:
        RecipeError: recipe does not exist.
    """
    row = conn.execute("SELECT * FROM recipes WHERE id = ?", (recipe_id,)).fetchone()
    if row is None:
        raise RecipeError("Recipe not found.")
    return _row_to_recipe(row)


def list_recipes(conn: sqlite3.Connection, user_id: int) -> list[Recipe]:
    """Return all recipes of a user, alphabetically.

    Args:
        conn: open database connection.
        user_id: owner.

    Returns:
        list[Recipe]: the user's recipes.
    """
    rows = conn.execute("SELECT * FROM recipes WHERE user_id = ? ORDER BY lower(name)",
                        (user_id,)).fetchall()
    return [_row_to_recipe(r) for r in rows]
