"""Drink catalogue, customisation options, live price/nutrition and ingredient needs.

Feature F2 (browse menu + nutrition) and F3 (real-time customisation) are
implemented here as pure functions so the GUI can recompute them every frame.
"""

from __future__ import annotations

import sqlite3
from dataclasses import asdict, dataclass, replace

MILK_OPTIONS = ["No milk", "Whole milk", "Skim milk", "Oat milk", "Almond milk"]
TEMPERATURES = ["Warm (60 C)", "Hot (70 C)", "Extra hot (80 C)"]
COLD_TEMPERATURE = "Iced (4 C)"
SYRUPS = ["Vanilla", "Caramel", "Hazelnut"]
STRENGTH_LABELS = {1: "Mild", 2: "Light", 3: "Medium", 4: "Strong", 5: "Extra strong"}

# per 100 ml: kcal, sugar g, fat g
MILK_NUTRITION = {
    "No milk": (0, 0.0, 0.0),
    "Whole milk": (64, 4.8, 3.6),
    "Skim milk": (35, 5.0, 0.1),
    "Oat milk": (46, 4.0, 1.5),
    "Almond milk": (15, 0.1, 1.1),
}
MILK_SURCHARGE = {"Oat milk": 5.0, "Almond milk": 5.0}
SYRUP_PRICE = 4.0          # SEK per shot
SYRUP_ML = 10.0            # ml per shot
SYRUP_KCAL, SYRUP_SUGAR = 27, 7.0
EXTRA_SHOT_PRICE = 7.0
EXTRA_SHOT_COFFEE_G = 8.0
EXTRA_SHOT_CAFFEINE = 63
STRONG_SURCHARGE = 3.0     # strength 5
CATEGORIES = ["All", "Espresso", "Milk coffee", "Chocolate", "Iced"]
CURRENCY = "SEK"


@dataclass(frozen=True)
class Drink:
    """One menu item as stored in the ``drinks`` table (base recipe values)."""

    id: int
    name: str
    category: str
    base_price: float
    calories: int
    sugar_g: float
    fat_g: float
    caffeine_mg: int
    coffee_g: float
    milk_ml: float
    water_ml: float
    cocoa_g: float
    ice_g: float
    is_cold: bool
    sweet: bool
    description: str

    @property
    def has_milk(self) -> bool:
        """Return True if the base recipe contains milk.

        Returns:
            bool: True when ``milk_ml`` > 0.
        """
        return self.milk_ml > 0

    @property
    def has_coffee(self) -> bool:
        """Return True if the base recipe uses coffee beans.

        Returns:
            bool: True when ``coffee_g`` > 0.
        """
        return self.coffee_g > 0


@dataclass(frozen=True)
class Customization:
    """User-chosen parameters for one beverage (F3)."""

    milk: str = "Whole milk"
    strength: int = 3
    temperature: str = "Hot (70 C)"
    syrup: str = "Vanilla"
    syrup_shots: int = 0
    extra_shot: bool = False

    def to_dict(self) -> dict:
        """Convert the customisation to a plain dictionary.

        Returns:
            dict: field name -> value, convenient for SQL inserts and display.
        """
        return asdict(self)


@dataclass(frozen=True)
class Nutrition:
    """Computed nutrition facts for a customised drink."""

    calories: int
    sugar_g: float
    fat_g: float
    caffeine_mg: int


def _row_to_drink(row: sqlite3.Row) -> Drink:
    """Map a database row to a :class:`Drink`.

    Args:
        row: one row of the ``drinks`` table.

    Returns:
        Drink: immutable drink object.
    """
    return Drink(
        id=row["id"], name=row["name"], category=row["category"],
        base_price=row["base_price"], calories=row["calories"], sugar_g=row["sugar_g"],
        fat_g=row["fat_g"], caffeine_mg=row["caffeine_mg"], coffee_g=row["coffee_g"],
        milk_ml=row["milk_ml"], water_ml=row["water_ml"], cocoa_g=row["cocoa_g"],
        ice_g=row["ice_g"], is_cold=bool(row["is_cold"]), sweet=bool(row["sweet"]),
        description=row["description"],
    )


def list_drinks(conn: sqlite3.Connection, category: str = "All") -> list[Drink]:
    """Return the drinks of one category (or all), ordered by id.

    Args:
        conn: open database connection.
        category: one of :data:`CATEGORIES`; ``"All"`` returns every drink.

    Returns:
        list[Drink]: matching drinks.
    """
    if category == "All":
        rows = conn.execute("SELECT * FROM drinks ORDER BY id").fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM drinks WHERE category = ? ORDER BY id", (category,)
        ).fetchall()
    return [_row_to_drink(r) for r in rows]


def get_drink(conn: sqlite3.Connection, drink_id: int) -> Drink | None:
    """Look up a single drink by id.

    Args:
        conn: open database connection.
        drink_id: primary key in ``drinks``.

    Returns:
        Drink | None: the drink, or None if the id does not exist.
    """
    row = conn.execute("SELECT * FROM drinks WHERE id = ?", (drink_id,)).fetchone()
    return _row_to_drink(row) if row else None


def default_customization(drink: Drink, default_milk: str = "Whole milk",
                          default_strength: int = 3) -> Customization:
    """Build the starting customisation for a drink, honouring profile defaults.

    Args:
        drink: the selected drink.
        default_milk: the user's preferred milk (from the preference profile).
        default_strength: the user's preferred strength 1-5.

    Returns:
        Customization: sensible defaults (no milk for black drinks, iced for cold).
    """
    milk = default_milk if drink.has_milk else "No milk"
    if drink.has_milk and milk == "No milk":
        milk = "Whole milk"
    temperature = COLD_TEMPERATURE if drink.is_cold else "Hot (70 C)"
    strength = default_strength if drink.has_coffee else 1
    return Customization(milk=milk, strength=strength, temperature=temperature,
                         syrup_shots=1 if drink.name == "Caramel Frappe" else 0,
                         syrup="Caramel" if drink.name == "Caramel Frappe" else "Vanilla")


def normalize(drink: Drink, custom: Customization) -> Customization:
    """Clamp a customisation to values that are valid for the given drink.

    Args:
        drink: the selected drink.
        custom: requested customisation (may contain out-of-range values).

    Returns:
        Customization: corrected copy (e.g. strength 1-5, syrup 0-4, iced for cold drinks).
    """
    strength = min(5, max(1, int(custom.strength)))
    shots = min(4, max(0, int(custom.syrup_shots)))
    milk = custom.milk if custom.milk in MILK_OPTIONS else "Whole milk"
    if not drink.has_milk:
        milk = "No milk"
    elif milk == "No milk":
        milk = "Whole milk"
    temperature = custom.temperature
    if drink.is_cold:
        temperature = COLD_TEMPERATURE
    elif temperature not in TEMPERATURES:
        temperature = "Hot (70 C)"
    syrup = custom.syrup if custom.syrup in SYRUPS else "Vanilla"
    extra = bool(custom.extra_shot) and drink.has_coffee
    return replace(custom, milk=milk, strength=strength, temperature=temperature,
                   syrup=syrup, syrup_shots=shots, extra_shot=extra)


def compute_price(drink: Drink, custom: Customization) -> float:
    """Calculate the live price of a customised drink (F3).

    Args:
        drink: the selected drink.
        custom: customisation chosen by the user.

    Returns:
        float: price in SEK, rounded to 2 decimals.
    """
    c = normalize(drink, custom)
    price = drink.base_price
    price += MILK_SURCHARGE.get(c.milk, 0.0)
    price += SYRUP_PRICE * c.syrup_shots
    price += EXTRA_SHOT_PRICE if c.extra_shot else 0.0
    price += STRONG_SURCHARGE if c.strength == 5 and drink.has_coffee else 0.0
    return round(price, 2)


def compute_nutrition(drink: Drink, custom: Customization) -> Nutrition:
    """Calculate nutrition facts of a customised drink (F2/F3).

    The base values in the catalogue assume whole milk; the milk part is
    swapped for the selected milk type, then syrup and extra shots are added.

    Args:
        drink: the selected drink.
        custom: customisation chosen by the user.

    Returns:
        Nutrition: calories, sugar, fat and caffeine.
    """
    c = normalize(drink, custom)
    whole = MILK_NUTRITION["Whole milk"]
    chosen = MILK_NUTRITION[c.milk]
    factor = drink.milk_ml / 100.0
    kcal = drink.calories + (chosen[0] - whole[0]) * factor
    sugar = drink.sugar_g + (chosen[1] - whole[1]) * factor
    fat = drink.fat_g + (chosen[2] - whole[2]) * factor
    kcal += SYRUP_KCAL * c.syrup_shots
    sugar += SYRUP_SUGAR * c.syrup_shots
    strength_factor = c.strength / 3.0 if drink.has_coffee else 1.0
    caffeine = drink.caffeine_mg * strength_factor
    caffeine += EXTRA_SHOT_CAFFEINE if c.extra_shot else 0
    return Nutrition(calories=max(0, round(kcal)), sugar_g=round(max(0.0, sugar), 1),
                     fat_g=round(max(0.0, fat), 1), caffeine_mg=round(caffeine))


def ingredient_needs(drink: Drink, custom: Customization) -> dict[str, float]:
    """Return how much of each inventory ingredient one serving consumes.

    Args:
        drink: the selected drink.
        custom: customisation chosen by the user.

    Returns:
        dict[str, float]: ingredient name -> amount in its inventory unit.
    """
    c = normalize(drink, custom)
    needs: dict[str, float] = {"Cups": 1}
    if drink.water_ml:
        needs["Water"] = drink.water_ml
    if drink.has_coffee:
        beans = drink.coffee_g * (0.7 + 0.1 * c.strength)
        beans += EXTRA_SHOT_COFFEE_G if c.extra_shot else 0
        needs["Coffee beans"] = round(beans, 1)
    if drink.has_milk and c.milk != "No milk":
        needs[c.milk] = drink.milk_ml
    if drink.cocoa_g:
        needs["Cocoa"] = drink.cocoa_g
    if drink.ice_g:
        needs["Ice"] = drink.ice_g
    if c.syrup_shots:
        needs["Syrup"] = SYRUP_ML * c.syrup_shots
    return needs


def describe(custom: Customization) -> str:
    """Produce a short human-readable summary of a customisation.

    Args:
        custom: the customisation.

    Returns:
        str: e.g. ``"Oat milk, Strong, Hot (70 C), 2x Caramel, +1 shot"``.
    """
    parts = [custom.milk, STRENGTH_LABELS.get(custom.strength, str(custom.strength)),
             custom.temperature]
    if custom.syrup_shots:
        parts.append(f"{custom.syrup_shots}x {custom.syrup}")
    if custom.extra_shot:
        parts.append("+1 shot")
    return ", ".join(parts)
