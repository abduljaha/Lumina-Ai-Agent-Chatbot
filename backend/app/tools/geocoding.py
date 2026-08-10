"""Shared geocoding helper for tools that need to resolve a place name.

Handles three real failure modes found in Open-Meteo's geocoding API
(verified live, not just guessed at):

1. Compound queries - "Madhapur, Hyderabad" (neighborhood, city) returns
   nothing even though "Madhapur" and "Hyderabad" each resolve cleanly
   alone. Both the weather and time tools hit this, so the comma/word
   splitting fallback lives here once instead of being duplicated per tool.
2. Historical/alternate city names resolving to a completely unrelated,
   obscure same-named place - "Calcutta" -> a village in South Africa,
   "Saigon" -> a town in Chad, "Bangalore" -> "Bangalore Town", Pakistan,
   because the real city is only indexed under its current official name
   ("Kolkata", "Ho Chi Minh City", "Bengaluru"). No amount of retrying or
   splitting fixes this - it needs an explicit alias map.
3. Plain misspellings ("banglore", "delhy", "newyork") returning zero
   results outright - the API does no fuzzy/edit-distance matching, so a
   conservative difflib pass against a pool of major world cities corrects
   these before the API call, while leaving anything not in the pool
   (smaller towns nobody typo'd) to pass through unchanged, same as before.
"""
from __future__ import annotations

import asyncio
import difflib
import logging
from typing import Any

logger = logging.getLogger("app")

_GEOCODE_TIMEOUT_SECONDS = 15
_MAX_ATTEMPTS = 3
_RETRY_BACKOFF_SECONDS = 0.5

# Colonial/historical names Open-Meteo's gazetteer resolves to an unrelated
# place of the same name elsewhere in the world, rather than the well-known
# city - mapped straight to the name that city is actually indexed under.
_CITY_ALIASES: dict[str, str] = {
    "bombay": "Mumbai",
    "calcutta": "Kolkata",
    "madras": "Chennai",
    "bangalore": "Bengaluru",
    "banglore": "Bengaluru",
    "bengaluru": "Bengaluru",
    "poona": "Pune",
    "cochin": "Kochi",
    "trivandrum": "Thiruvananthapuram",
    "mysore": "Mysuru",
    "peking": "Beijing",
    "canton": "Guangzhou",
    "saigon": "Ho Chi Minh City",
    "rangoon": "Yangon",
    "constantinople": "Istanbul",
    "siam": "Bangkok",
    "leningrad": "Saint Petersburg",
    "stalingrad": "Volgograd",
    "danzig": "Gdansk",
    "batavia": "Jakarta",
    "salisbury": "Harare",
    "new amsterdam": "New York",
}

# Reference pool for typo correction - major world capitals/metros plus
# every alias target above, so a misspelling of either the colonial or
# modern name ("banglore", "bengaluruu") corrects to the right query.
_MAJOR_CITIES: tuple[str, ...] = (
    "New York", "Los Angeles", "Chicago", "Houston", "San Francisco", "Seattle",
    "Boston", "Washington", "Miami", "Toronto", "Vancouver", "Montreal",
    "Mexico City", "Sao Paulo", "Rio de Janeiro", "Buenos Aires", "Lima",
    "Bogota", "Santiago", "London", "Paris", "Berlin", "Madrid", "Rome",
    "Amsterdam", "Vienna", "Zurich", "Geneva", "Brussels", "Dublin", "Lisbon",
    "Stockholm", "Oslo", "Copenhagen", "Helsinki", "Warsaw", "Prague",
    "Budapest", "Athens", "Istanbul", "Moscow", "Saint Petersburg", "Kyiv",
    "Dubai", "Abu Dhabi", "Doha", "Riyadh", "Tel Aviv", "Cairo", "Istanbul",
    "Mumbai", "Delhi", "New Delhi", "Bengaluru", "Hyderabad", "Chennai",
    "Kolkata", "Pune", "Ahmedabad", "Jaipur", "Lucknow", "Kochi",
    "Thiruvananthapuram", "Mysuru", "Chandigarh", "Bhopal", "Indore",
    "Nagpur", "Surat", "Visakhapatnam", "Patna", "Kanpur", "Coimbatore",
    "Karachi", "Lahore", "Islamabad", "Dhaka", "Colombo", "Kathmandu",
    "Beijing", "Shanghai", "Guangzhou", "Shenzhen", "Hong Kong", "Macau",
    "Taipei", "Tokyo", "Osaka", "Kyoto", "Seoul", "Busan", "Bangkok",
    "Ho Chi Minh City", "Hanoi", "Singapore", "Kuala Lumpur", "Jakarta",
    "Manila", "Yangon", "Phnom Penh", "Sydney", "Melbourne", "Brisbane",
    "Perth", "Auckland", "Wellington", "Lagos", "Nairobi", "Cape Town",
    "Johannesburg", "Harare", "Kinshasa", "Addis Ababa", "Casablanca",
    "Algiers", "Tunis", "Accra", "Gdansk", "Warsaw", "Volgograd",
)
_FUZZY_POOL_LOWER: dict[str, str] = {
    c.lower(): c for c in {*_MAJOR_CITIES, *_CITY_ALIASES.values()}
}

# Higher-significance settlement types outrank a bare "populated place" of
# the same or unknown population when disambiguating between same-named
# results - a national/administrative capital named "Paris" should win over
# an unremarkable "Paris" hamlet even if population data is missing for both.
_FEATURE_CODE_RANK: dict[str, int] = {
    "PPLC": 3,  # capital of a country
    "PPLA": 2,  # capital of a first-order admin division (state/province)
    "PPLA2": 1,  # capital of a second-order admin division
}


def _correct_location_name(location: str) -> str:
    """Best-effort correction for known aliases and common misspellings.

    Conservative on purpose: only corrects when there's a known alias or a
    close (cutoff=0.75) fuzzy match against the major-city pool. Anything
    else - including real but obscure place names - passes through
    unchanged, exactly as it did before this function existed.
    """
    key = location.strip().lower()
    if not key:
        return location
    if key in _CITY_ALIASES:
        corrected = _CITY_ALIASES[key]
        logger.info("Corrected location alias %r -> %r", location, corrected)
        return corrected
    matches = difflib.get_close_matches(key, _FUZZY_POOL_LOWER.keys(), n=1, cutoff=0.75)
    if matches:
        corrected = _FUZZY_POOL_LOWER[matches[0]]
        if corrected.lower() != key:
            logger.info("Corrected likely misspelling %r -> %r", location, corrected)
        return corrected
    return location


def _rank_result(result: dict[str, Any]) -> tuple[int, int]:
    """Sort key for picking the best of several same/similar-named results.

    Population (higher is better) first, then settlement significance as a
    tie-breaker for places Open-Meteo has no population figure for at all -
    which capitals frequently don't, since `_FEATURE_CODE_RANK` still lets a
    "PPLC" beat an unranked "PPL" of unknown population.
    """
    population = result.get("population") or 0
    feature_rank = _FEATURE_CODE_RANK.get(result.get("feature_code") or "", 0)
    return (population, feature_rank)


async def _search_once(client: Any, name: str) -> list[dict[str, Any]]:
    """A single geocoding API call. Raises on network/HTTP failure; returns [] for no match."""
    resp = await client.get(
        "https://geocoding-api.open-meteo.com/v1/search",
        params={"name": name, "count": 10},
    )
    resp.raise_for_status()
    data = resp.json()
    return data.get("results") or []


async def _search_with_retry(client: Any, name: str) -> list[dict[str, Any]]:
    """Retry a single candidate's search on transient network/HTTP errors only.

    A 4xx or a clean empty result is deterministic - retrying it wastes time
    and just delays returning "not found". Only connection/timeout errors and
    5xx responses are worth a second attempt.
    """
    import httpx

    last_exc: Exception | None = None
    for attempt in range(1, _MAX_ATTEMPTS + 1):
        try:
            return await _search_once(client, name)
        except httpx.HTTPStatusError as exc:
            if exc.response is not None and exc.response.status_code < 500:
                raise  # deterministic client error - don't retry
            last_exc = exc
        except (httpx.TimeoutException, httpx.ConnectError, httpx.ReadError) as exc:
            last_exc = exc

        if attempt < _MAX_ATTEMPTS:
            logger.warning(
                "Geocoding lookup for %r failed transiently (attempt %d/%d): %s - retrying",
                name, attempt, _MAX_ATTEMPTS, last_exc,
            )
            await asyncio.sleep(_RETRY_BACKOFF_SECONDS * attempt)

    assert last_exc is not None
    raise last_exc


async def geocode(location: str) -> dict[str, Any] | None:
    """Resolve a place name to latitude/longitude/timezone.

    Corrects known aliases/misspellings, then tries the full string, then
    falls back to each comma- or word-separated segment (most specific
    first) for compound queries like "Madhapur, Hyderabad". When a candidate
    returns multiple same-named results, picks the most significant one
    (population, then capital status) instead of blindly taking the first -
    Open-Meteo's own ordering put an obscure Pakistani "Bangalore Town"
    ahead of nothing (the real city isn't indexed under that name at all)
    and a Scottish hamlet "Newyork" ahead of New York City for unspaced
    queries, both verified live against the API.
    """
    import httpx

    raw_candidates = [location.strip()]
    if "," in location:
        raw_candidates.extend(part.strip() for part in location.split(",") if part.strip())
    else:
        words = [w.strip() for w in location.split() if w.strip()]
        if len(words) > 1:
            raw_candidates.extend(reversed(words))

    # Alias/misspelling correction is applied to EACH candidate individually
    # (not just the top-level string) - a garbled or compound query like
    # "bangalore, what time is it in tokyo" (see tool_selection.py's
    # location extraction, which can hand this whole thing over as one
    # string) only becomes correctable once split down to the "bangalore"
    # piece alone. Correcting only the combined string up front and never
    # revisiting the split pieces silently skipped correction for exactly
    # the queries that need splitting the most - verified live: this was
    # resolving "bangalore" to Pakistan's "Bangalore Town" even though the
    # standalone alias correction maps it straight to Bengaluru, India.
    candidates: list[str] = []
    seen: set[str] = set()
    for raw in raw_candidates:
        for candidate in (_correct_location_name(raw), raw):
            key = candidate.strip().lower()
            if not key or key in seen:
                continue
            seen.add(key)
            candidates.append(candidate.strip())

    async with httpx.AsyncClient(timeout=_GEOCODE_TIMEOUT_SECONDS) as client:
        for candidate in candidates:
            if not candidate:
                continue
            try:
                results = await _search_with_retry(client, candidate)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Geocoding lookup for %r ultimately failed: %s", candidate, exc)
                continue
            if not results:
                continue
            best = max(results, key=_rank_result)
            return {
                "lat": best["latitude"],
                "lon": best["longitude"],
                "timezone": best.get("timezone"),
                "resolved_name": best.get("name"),
                "country": best.get("country"),
                "matched_query": candidate,
            }
    return None
