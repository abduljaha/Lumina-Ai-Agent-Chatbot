"""Shared geocoding helper for tools that need to resolve a place name.

Open-Meteo's geocoding API only matches individual place names - a compound
query like "Madhapur, Hyderabad" (neighborhood, city) returns nothing even
though "Madhapur" and "Hyderabad" each resolve cleanly on their own. Both the
weather and time tools hit this, so the comma-splitting fallback lives here
once instead of being duplicated in each tool.
"""
from __future__ import annotations

from typing import Any


async def geocode(location: str) -> dict[str, Any] | None:
    """Resolve a place name to latitude/longitude/timezone.

    Tries the full string first, then falls back to each comma-separated
    segment (most specific first) so "Madhapur, Hyderabad" still resolves
    even though the API only recognizes "Madhapur" or "Hyderabad" alone.
    """
    import httpx

    candidates = [location.strip()]
    if "," in location:
        candidates.extend(part.strip() for part in location.split(",") if part.strip())
    else:
        # Same problem without a comma, e.g. "madhapur hyderabad" (spoken/
        # typed without punctuation) - try each word too, broadest (last)
        # first, since compound "neighborhood city" phrasing usually ends
        # with the city name the API actually recognizes.
        words = [w.strip() for w in location.split() if w.strip()]
        if len(words) > 1:
            candidates.extend(reversed(words))

    async with httpx.AsyncClient(timeout=15) as client:
        for candidate in candidates:
            if not candidate:
                continue
            try:
                resp = await client.get(
                    "https://geocoding-api.open-meteo.com/v1/search",
                    params={"name": candidate, "count": 1},
                )
                resp.raise_for_status()
                data = resp.json()
            except Exception:
                continue
            results = data.get("results")
            if results:
                r = results[0]
                return {
                    "lat": r["latitude"],
                    "lon": r["longitude"],
                    "timezone": r.get("timezone"),
                    "resolved_name": r.get("name"),
                    "matched_query": candidate,
                }
    return None
