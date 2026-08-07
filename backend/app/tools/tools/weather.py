"""Weather tool using Open-Meteo (no API key required)."""
from __future__ import annotations

from typing import Any

from app.tools.base import ToolResult


class WeatherTool:
    """Fetches current weather and forecast for a location."""

    name = "weather"
    description = "Get current weather and forecast for a city or coordinates."

    async def invoke(self, city: str = "", latitude: float | None = None, longitude: float | None = None, **kwargs: Any) -> ToolResult:
        """Fetch weather data for a location."""
        try:
            import httpx

            if latitude is None or longitude is None:
                if not city:
                    return ToolResult(success=False, error="Provide a city or coordinates")
                from app.tools.geocoding import geocode as geocode_location

                geocoded = await geocode_location(city)
                if not geocoded:
                    return ToolResult(success=False, error=f"Could not find location: {city}")
                latitude, longitude = geocoded["lat"], geocoded["lon"]

            params = {
                "latitude": latitude,
                "longitude": longitude,
                "current_weather": "true",
                "hourly": "temperature_2m,relative_humidity_2m,wind_speed_10m",
                "forecast_days": 1,
            }
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get("https://api.open-meteo.com/v1/forecast", params=params)
                resp.raise_for_status()
                data = resp.json()

            current = data.get("current_weather", {})
            return ToolResult(
                success=True,
                output={
                    "location": city or f"{latitude}, {longitude}",
                    "temperature_c": current.get("temperature"),
                    "windspeed_kmh": current.get("windspeed"),
                    "weather_code": current.get("weathercode"),
                    "unit": data.get("current_weather_units", {}),
                },
                metadata={"latitude": latitude, "longitude": longitude},
            )
        except Exception as exc:
            return ToolResult(success=False, error=f"Weather lookup failed: {exc}")

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
