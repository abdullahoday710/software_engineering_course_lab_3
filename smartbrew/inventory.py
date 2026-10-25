"""Ingredient stock and waste bins (features F4 and F10).

F4: a drink can be selected only if every ingredient it needs stays usable,
i.e. the level is above the minimum threshold and covers one serving.
F10: technicians refill ingredients and empty bins; bins raise an alert at
80 % and halt the machine when full.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from . import events
from .catalog import MILK_OPTIONS, Customization, Drink, ingredient_needs

BIN_ALERT_RATIO = 0.8
GROUNDS_PER_BEAN_G = 1.6   # wet grounds weigh more than the dry beans
WASTE_ML_PER_DRINK = 15.0


@dataclass(frozen=True)
class Ingredient:
    """Current state of one ingredient container."""

    name: str
    level: float
    capacity: float
    threshold: float
    unit: str

    @property
    def ratio(self) -> float:
        """Fill ratio between 0 and 1.

        Returns:
            float: level / capacity.
        """
        return max(0.0, min(1.0, self.level / self.capacity)) if self.capacity else 0.0

    @property
    def below_threshold(self) -> bool:
        """Whether the level is at or under the minimum threshold.

        Returns:
            bool: True if the ingredient counts as depleted.
        """
        return self.level <= self.threshold


@dataclass(frozen=True)
class Bin:
    """Current state of a waste bin."""

    name: str
    level: float
    capacity: float
    unit: str

    @property
    def ratio(self) -> float:
        """Fill ratio between 0 and 1.

        Returns:
            float: level / capacity.
        """
        return max(0.0, min(1.0, self.level / self.capacity)) if self.capacity else 1.0

    @property
    def needs_emptying(self) -> bool:
        """Whether the bin passed the alert level (80 %).

        Returns:
            bool: True if a technician should empty it.
        """
        return self.ratio >= BIN_ALERT_RATIO

    @property
    def full(self) -> bool:
        """Whether the bin is full, which halts the machine.

        Returns:
            bool: True at 100 %.
        """
        return self.level >= self.capacity


def get_ingredients(conn: sqlite3.Connection) -> dict[str, Ingredient]:
    """Load all ingredient containers.

    Args:
        conn: open database connection.

    Returns:
        dict[str, Ingredient]: ingredient name -> state, in insertion order.
    """
    rows = conn.execute("SELECT * FROM ingredients ORDER BY rowid").fetchall()
    return {r["name"]: Ingredient(r["name"], r["level"], r["capacity"], r["threshold"], r["unit"])
            for r in rows}


def is_usable(ing: Ingredient, amount: float) -> bool:
    """Check that an ingredient is above threshold and covers the amount.

    Args:
        ing: ingredient state.
        amount: quantity one serving needs.

    Returns:
        bool: True if the ingredient may be used.
    """
    return not ing.below_threshold and ing.level >= amount


def missing_for(conn: sqlite3.Connection, drink: Drink, custom: Customization) -> list[str]:
    """List ingredients that block this exact customised drink.

    Args:
        conn: open database connection.
        drink: selected drink.
        custom: chosen customisation.

    Returns:
        list[str]: names of depleted ingredients (empty if the drink can be made).
    """
    stock = get_ingredients(conn)
    missing = []
    for name, amount in ingredient_needs(drink, custom).items():
        ing = stock.get(name)
        if ing is None or not is_usable(ing, amount):
            missing.append(name)
    return missing


def available_milks(conn: sqlite3.Connection, drink: Drink) -> list[str]:
    """Return the milk options that are currently in stock for a drink.

    Args:
        conn: open database connection.
        drink: selected drink.

    Returns:
        list[str]: usable milk names; ``["No milk"]`` for drinks without milk.
    """
    if not drink.has_milk:
        return ["No milk"]
    stock = get_ingredients(conn)
    return [m for m in MILK_OPTIONS[1:] if m in stock and is_usable(stock[m], drink.milk_ml)]


def drink_availability(conn: sqlite3.Connection, drink: Drink,
                       custom: Customization) -> tuple[bool, list[str]]:
    """Decide whether a drink may be selected on the menu (F4).

    A milk drink stays available if *any* milk type is in stock, because the
    customer can switch milk; it is greyed out when all milk types are depleted.

    Args:
        conn: open database connection.
        drink: menu item.
        custom: its default customisation.

    Returns:
        tuple[bool, list[str]]: (available, list of blocking ingredient names).
    """
    missing = missing_for(conn, drink, custom)
    if drink.has_milk and custom.milk in missing:
        if available_milks(conn, drink):
            missing = [m for m in missing if m != custom.milk]
        else:
            missing = [m for m in missing if m not in MILK_OPTIONS] + ["Milk (all types)"]
    return (not missing, missing)


def consume(conn: sqlite3.Connection, drink: Drink, custom: Customization) -> None:
    """Subtract one serving from stock and add its waste to the bins.

    Also logs a ``Low Ingredient Threshold`` warning for each ingredient that
    crosses its threshold and a bin alert when a bin passes 80 %.

    Args:
        conn: open database connection.
        drink: dispensed drink.
        custom: its customisation.

    Returns:
        None.
    """
    needs = ingredient_needs(drink, custom)
    before = get_ingredients(conn)
    for name, amount in needs.items():
        conn.execute("UPDATE ingredients SET level = MAX(0, level - ?) WHERE name = ?",
                     (amount, name))
    beans = needs.get("Coffee beans", 0.0)
    bins_before = get_bins(conn)
    conn.execute("UPDATE bins SET level = level + ? WHERE name = 'Coffee grounds'",
                 (beans * GROUNDS_PER_BEAN_G,))
    conn.execute("UPDATE bins SET level = level + ? WHERE name = 'Liquid waste'",
                 (WASTE_ML_PER_DRINK,))
    conn.commit()

    after = get_ingredients(conn)
    for name in needs:
        if name in after and after[name].below_threshold and not before[name].below_threshold:
            events.log(conn, events.WARNING, "Inventory",
                       f"Low Ingredient Threshold: {name} ({after[name].level:.0f} {after[name].unit})")
    for name, b in get_bins(conn).items():
        old = bins_before[name]
        if b.full and not old.full:
            events.log(conn, events.ERROR, "Bins", f"{name} bin overflow - machine halted")
        elif b.needs_emptying and not old.needs_emptying:
            events.log(conn, events.WARNING, "Bins", f"{name} bin needs emptying ({b.ratio:.0%})")


def refill(conn: sqlite3.Connection, name: str) -> None:
    """Reset one ingredient counter to maximum capacity (technician refill).

    Args:
        conn: open database connection.
        name: ingredient name.

    Returns:
        None. Raises KeyError if the ingredient does not exist.
    """
    cur = conn.execute("UPDATE ingredients SET level = capacity WHERE name = ?", (name,))
    if cur.rowcount == 0:
        raise KeyError(name)
    conn.commit()
    events.log(conn, events.INFO, "Technician", f"Refilled {name} to 100%")


def set_level(conn: sqlite3.Connection, name: str, level: float) -> None:
    """Set an ingredient level directly (simulation / demo control).

    Args:
        conn: open database connection.
        name: ingredient name.
        level: new level in the ingredient's unit (clamped to 0..capacity).

    Returns:
        None.
    """
    conn.execute("UPDATE ingredients SET level = MAX(0, MIN(capacity, ?)) WHERE name = ?",
                 (level, name))
    conn.commit()


def get_bins(conn: sqlite3.Connection) -> dict[str, Bin]:
    """Load the waste bins.

    Args:
        conn: open database connection.

    Returns:
        dict[str, Bin]: bin name -> state.
    """
    rows = conn.execute("SELECT * FROM bins ORDER BY rowid").fetchall()
    return {r["name"]: Bin(r["name"], r["level"], r["capacity"], r["unit"]) for r in rows}


def set_bin_level(conn: sqlite3.Connection, name: str, level: float) -> None:
    """Set a bin level directly (sensor simulation), logging alerts on crossings.

    Args:
        conn: open database connection.
        name: bin name.
        level: new fill level in the bin's unit.

    Returns:
        None.
    """
    old = get_bins(conn)[name]
    conn.execute("UPDATE bins SET level = MAX(0, ?) WHERE name = ?", (level, name))
    conn.commit()
    new = get_bins(conn)[name]
    if new.full and not old.full:
        events.log(conn, events.ERROR, "Bins", f"{name} bin overflow - machine halted")
    elif new.needs_emptying and not old.needs_emptying:
        events.log(conn, events.WARNING, "Bins", f"{name} bin needs emptying ({new.ratio:.0%})")


def empty_bin(conn: sqlite3.Connection, name: str) -> None:
    """Record that a technician emptied a bin.

    Args:
        conn: open database connection.
        name: bin name.

    Returns:
        None.
    """
    conn.execute("UPDATE bins SET level = 0 WHERE name = ?", (name,))
    conn.commit()
    events.log(conn, events.INFO, "Technician", f"Emptied {name} bin")
