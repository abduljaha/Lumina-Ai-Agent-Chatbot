"""Weather tool using Open-Meteo (no API key required)."""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from app.tools.base import ToolResult

logger = logging.getLogger("app")

_FORECAST_TIMEOUT_SECONDS = 15
_MAX_ATTEMPTS = 3
_RETRY_BACKOFF_SECONDS = 0.5


class WeatherTool:
    """Fetches current weather and forecast for a location."""

    name = "weather"
    description = "Get current weather and forecast for a city or coordinates."

    async def invoke(self, city: str = "", latitude: float | None = None, longitude: float | None = None, **kwargs: Any) -> ToolResult:
        """Fetch weather data for a location."""
        import httpx

        resolved_name = city
        try:
            if latitude is None or longitude is None:
                if not city:
                    return ToolResult(success=False, error="Provide a city or coordinates")
                from app.tools.geocoding import geocode as geocode_location

                geocoded = await geocode_location(city)
                if not geocoded:
                    return ToolResult(
                        success=False,
                        error=f"Could not find location: {city}",
                        metadata={"transient": False},
                    )
                latitude, longitude = geocoded["lat"], geocoded["lon"]
                # Report back what was actually resolved (e.g. "banglore" ->
                # "Bengaluru, India") so a corrected/disambiguated match is
                # visible in the answer instead of silently substituted.
                resolved_name = geocoded.get("resolved_name") or city
                if geocoded.get("country"):
                    resolved_name = f"{resolved_name}, {geocoded['country']}"
        except Exception as exc:  # noqa: BLE001
            return ToolResult(success=False, error=f"Could not resolve location {city!r}: {exc}")

        params = {
            "latitude": latitude,
            "longitude": longitude,
            "current_weather": "true",
            "hourly": "temperature_2m,relative_humidity_2m,wind_speed_10m",
            "forecast_days": 1,
        }

        last_exc: Exception | None = None
        async with httpx.AsyncClient(timeout=_FORECAST_TIMEOUT_SECONDS) as client:
            for attempt in range(1, _MAX_ATTEMPTS + 1):
                try:
                    resp = await client.get("https://api.open-meteo.com/v1/forecast", params=params)
                    resp.raise_for_status()
                    data = resp.json()
                    current = data.get("current_weather", {})
                    return ToolResult(
                        success=True,
                        output={
                            "location": resolved_name or f"{latitude}, {longitude}",
                            "temperature_c": current.get("temperature"),
                            "windspeed_kmh": current.get("windspeed"),
                            "weather_code": current.get("weathercode"),
                            "unit": data.get("current_weather_units", {}),
                        },
                        metadata={"latitude": latitude, "longitude": longitude},
                    )
                except httpx.HTTPStatusError as exc:
                    if exc.response is not None and exc.response.status_code < 500:
                        return ToolResult(success=False, error=f"Weather lookup failed: {exc}", metadata={"transient": False})
                    last_exc = exc
                except (httpx.TimeoutException, httpx.ConnectError, httpx.ReadError) as exc:
                    last_exc = exc
                except Exception as exc:  # noqa: BLE001
                    return ToolResult(success=False, error=f"Weather lookup failed: {exc}", metadata={"transient": False})

                if attempt < _MAX_ATTEMPTS:
                    logger.warning(
                        "Weather forecast fetch for %r failed transiently (attempt %d/%d): %s - retrying",
                        resolved_name, attempt, _MAX_ATTEMPTS, last_exc,
                    )
                    await asyncio.sleep(_RETRY_BACKOFF_SECONDS * attempt)

        return ToolResult(
            success=False,
            error=f"Weather lookup failed after {_MAX_ATTEMPTS} attempts: {last_exc}",
            metadata={"transient": True},
        )

    def to_dict(self) -> dict[str, Any]:
        """Return tool metadata."""
        return {
            "name": self.name,
            "description": self.description,
            "parameters": {
                "type": "object",
                "properties": {
                    "city": {"type": "string", "description": "City name"},
                    "latitude": {"type": "number", "description": "Latitude"},
                    "longitude": {"type": "number", "description": "Longitude"},
                },
            },
        }
