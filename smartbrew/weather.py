"""Simulated weather service used by the recommender.

The real machine would call an external weather API. The prototype keeps the
values in memory so they can be changed from the Simulation tab, and raises
:class:`ServiceUnavailable` when the network is switched off, so the
recommender's fallback can be demonstrated.
"""

from __future__ import annotations

from dataclasses import dataclass

CONDITIONS = ["Sunny", "Cloudy", "Rainy", "Snowy"]


class ServiceUnavailable(RuntimeError):
    """Raised when an external service cannot be reached."""


@dataclass
class Weather:
    """A weather reading."""

    temperature_c: float
    condition: str


class WeatherService:
    """In-memory stand-in for an external weather API."""

    def __init__(self, temperature_c: float = 7.0, condition: str = "Cloudy") -> None:
        """Create the service with an initial reading.

        Args:
            temperature_c: outdoor temperature in Celsius.
            condition: one of :data:`CONDITIONS`.

        Returns:
            None.
        """
        self.current = Weather(temperature_c, condition)
        self.online = True

    def get(self) -> Weather:
        """Fetch the current weather.

        Returns:
            Weather: the reading.

        Raises:
            ServiceUnavailable: when the network is offline.
        """
        if not self.online:
            raise ServiceUnavailable("Weather API unreachable")
        return Weather(self.current.temperature_c, self.current.condition)

    def set(self, temperature_c: float, condition: str) -> None:
        """Change the simulated reading.

        Args:
            temperature_c: outdoor temperature in Celsius.
            condition: one of :data:`CONDITIONS`.

        Returns:
            None.
        """
        self.current = Weather(float(temperature_c),
                               condition if condition in CONDITIONS else "Cloudy")
