"""Current time tool."""
from __future__ import annotations

from datetime import datetime
from datetime import timezone as tzmod
from typing import Any

from app.tools.base import ToolResult


class CurrentTimeTool:
    """Returns the current date and time, optionally for a named place."""

    name = "current_time"
    description = (
        "Get the current date and time. Pass `location` for the time in a specific "
        "city or country (resolved to its real timezone); pass `timezone` directly "
        "if you already know the IANA zone name. Defaults to UTC."
    )

    async def invoke(
        self,
        timezone: str = "",
        location: str = "",
        **kwargs: Any,
    ) -> ToolResult:
        """Return the current time, resolving `location` to a timezone if given."""
        resolved_timezone = timezone
        if location and not timezone:
            from app.tools.geocoding import geocode

            geocoded = await geocode(location)
            if not geocoded or not geocoded.get("timezone"):
                return ToolResult(success=False, error=f"Could not find location: {location}")
            resolved_timezone = geocoded["timezone"]

        try:
            from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

            tz = ZoneInfo(resolved_timezone) if resolved_timezone else tzmod.utc
            now = datetime.now(tz)
            return ToolResult(
                success=True,
                output={
                    "datetime": now.isoformat(),
                    "timezone": str(tz),
                    "date": now.strftime("%Y-%m-%d"),
                    "time": now.strftime("%H:%M:%S"),
                    "location": location or None,
                },
                metadata={"timezone": str(tz)},
            )
        except ZoneInfoNotFoundError:
            return ToolResult(success=False, error=f"Unknown timezone: {resolved_timezone}")

    def to_dict(self) -> dict[str, Any]:
        """Return tool metadata."""
        return {
            "name": self.name,
            "description": self.description,
            "parameters": {
                "type": "object",
                "properties": {
                    "location": {
                        "type": "string",
                        "description": "City or place name to get the local time for (e.g. 'Hyderabad', 'Madhapur, Hyderabad', 'Tokyo')",
                    },
                    "timezone": {
                        "type": "string",
                        "description": "IANA timezone name if already known (e.g. America/New_York). Overrides `location`.",
                    },
                },
            },
        }
