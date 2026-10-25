"""Personalised recommendation scores and menu ordering (feature F8).

Each drink gets a score built from four transparent signals. The reasons are
kept so the UI can explain *why* a drink is on top:

* time of day   - caffeine in the morning, lighter drinks in the evening
* weather       - hot drinks when cold/rainy, iced drinks when warm
* history       - how often the logged-in user ordered the drink
* mood          - optional result of the camera mood detection (F9)
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

from .catalog import Drink
from .weather import Weather

TOP_N = 3


@dataclass
class Recommendation:
    """A drink with its score and the reasons that produced it."""

    drink: Drink
    score: float
    reasons: list[str] = field(default_factory=list)
    highlighted: bool = False


def daypart(hour: int) -> str:
    """Map an hour to a part of the day.

    Args:
        hour: 0-23.

    Returns:
        str: ``"morning"`` (5-10), ``"afternoon"`` (11-16) or ``"evening"``.
    """
    if 5 <= hour <= 10:
        return "morning"
    if 11 <= hour <= 16:
        return "afternoon"
    return "evening"


def time_score(drink: Drink, hour: int) -> tuple[float, str | None]:
    """Score a drink for the time of day (max 25).

    Args:
        drink: candidate drink.
        hour: current hour 0-23.

    Returns:
        tuple[float, str | None]: points and an optional reason.
    """
    part = daypart(hour)
    if part == "morning":
        pts = min(25.0, drink.caffeine_mg / 126 * 25)
        return pts, "Morning boost" if pts >= 12 else None
    if part == "afternoon":
        pts = 15.0 if 50 <= drink.caffeine_mg <= 100 else 8.0
        return pts, "Afternoon pick-me-up" if pts > 10 else None
    pts = 25.0 if drink.caffeine_mg <= 20 else max(0.0, 15 - drink.caffeine_mg / 10)
    return pts, "Low caffeine for the evening" if pts >= 15 else None


def weather_score(drink: Drink, weather: Weather | None) -> tuple[float, str | None]:
    """Score a drink for the weather (max 25).

    Args:
        drink: candidate drink.
        weather: current weather, or None when the service is unavailable.

    Returns:
        tuple[float, str | None]: points and an optional reason.
    """
    if weather is None:
        return 0.0, None
    t, cond = weather.temperature_c, weather.condition
    if drink.is_cold:
        if t >= 20:
            return 25.0, f"Warm day ({t:.0f} C)"
        return (8.0 if t >= 12 else 0.0), None
    pts = 0.0
    if t <= 10:
        pts += 15.0
    if cond in ("Rainy", "Snowy"):
        pts += 10.0 if drink.has_milk or drink.cocoa_g else 5.0
    if pts:
        return pts, f"{cond}, {t:.0f} C outside"
    return 5.0, None


def history_score(drink: Drink, counts: Counter) -> tuple[float, str | None]:
    """Score a drink by the user's order history (max 40).

    Args:
        drink: candidate drink.
        counts: drink_id -> number of past orders by this user.

    Returns:
        tuple[float, str | None]: points and an optional reason.
    """
    total = sum(counts.values())
    n = counts.get(drink.id, 0)
    if not total or not n:
        return 0.0, None
    pts = 40.0 * n / max(counts.values())
    return pts, f"You ordered it {n}x"


def mood_score(drink: Drink, mood: str | None) -> tuple[float, str | None]:
    """Score a drink for the detected mood (max 30).

    Args:
        drink: candidate drink.
        mood: ``"Tired"``, ``"Happy"``, ``"Stressed"``, ``"Neutral"`` or None.

    Returns:
        tuple[float, str | None]: points and an optional reason.
    """
    if mood == "Tired":
        pts = min(30.0, drink.caffeine_mg / 126 * 30)
        return pts, "You look tired" if pts >= 15 else None
    if mood == "Happy":
        pts = (15.0 if drink.sweet else 0.0) + (15.0 if drink.is_cold else 0.0)
        return pts, "Matches your good mood" if pts else None
    if mood == "Stressed":
        pts = 30.0 if drink.caffeine_mg <= 20 else (15.0 if drink.cocoa_g else 0.0)
        return pts, "Something calming" if pts else None
    return 0.0, None


def recommend(drinks: list[Drink], hour: int, weather: Weather | None,
              counts: Counter | None = None, mood: str | None = None,
              top_n: int = TOP_N) -> list[Recommendation]:
    """Score all drinks and return them ordered best-first (F8).

    Args:
        drinks: menu items to rank.
        hour: current hour 0-23.
        weather: current weather or None (service down -> signal skipped).
        counts: the user's order counts per drink id (None/empty for guests).
        mood: detected mood or None.
        top_n: how many of the best drinks to mark as highlighted.

    Returns:
        list[Recommendation]: sorted by score descending; ties keep menu order.
    """
    counts = counts or Counter()
    out = []
    for d in drinks:
        score, reasons = 0.0, []
        for pts, why in (time_score(d, hour), weather_score(d, weather),
                         history_score(d, counts), mood_score(d, mood)):
            score += pts
            if why:
                reasons.append(why)
        out.append(Recommendation(d, round(score, 1), reasons))
    out.sort(key=lambda r: -r.score)
    for r in out[:top_n]:
        r.highlighted = r.score > 0
    return out
