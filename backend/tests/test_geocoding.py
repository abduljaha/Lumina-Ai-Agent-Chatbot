"""Tests for the shared geocoding helper - alias/misspelling correction,
population-aware disambiguation, and retry/fallback behavior on network
failures. All network calls are mocked (no live API dependency), except
where noted as an explicit opt-in live check.
"""
from __future__ import annotations

import httpx
import pytest

from app.tools.geocoding import _correct_location_name, geocode


# ---------------------------------------------------------------------------
# Pure correction logic - no network involved
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "raw,expected",
    [
        ("bombay", "Mumbai"),
        ("BOMBAY", "Mumbai"),
        ("calcutta", "Kolkata"),
        ("madras", "Chennai"),
        ("saigon", "Ho Chi Minh City"),
        ("peking", "Beijing"),
        ("bangalore", "Bengaluru"),
    ],
)
def test_known_alias_is_corrected(raw: str, expected: str) -> None:
    """Historical/colonial names that Open-Meteo resolves to an unrelated place get remapped."""
    assert _correct_location_name(raw) == expected


@pytest.mark.parametrize(
    "misspelled,expected",
    [
        ("banglore", "Bengaluru"),
        ("delhy", "Delhi"),
        ("newyork", "New York"),
    ],
)
def test_common_misspelling_is_fuzzy_corrected(misspelled: str, expected: str) -> None:
    """A close-enough typo of a major city corrects via difflib against the reference pool."""
    assert _correct_location_name(misspelled) == expected


def test_unrecognized_place_passes_through_unchanged() -> None:
    """A real but obscure place name (not in the reference pool) is left untouched."""
    assert _correct_location_name("Springfield") == "Springfield"
    assert _correct_location_name("Madhapur") == "Madhapur"


# ---------------------------------------------------------------------------
# Full geocode() - network mocked
# ---------------------------------------------------------------------------
class _FakeResponse:
    def __init__(self, payload: dict, status_code: int = 200) -> None:
        self._payload = payload
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            request = httpx.Request("GET", "https://geocoding-api.open-meteo.com/v1/search")
            response = httpx.Response(self.status_code, request=request)
            raise httpx.HTTPStatusError("error", request=request, response=response)

    def json(self) -> dict:
        return self._payload


def _result(name: str, country: str, lat: float, lon: float, tz: str, population: int = 0, feature_code: str = "PPL") -> dict:
    return {
        "name": name, "country": country, "latitude": lat, "longitude": lon,
        "timezone": tz, "population": population, "feature_code": feature_code,
    }


@pytest.mark.asyncio
async def test_geocode_picks_highest_population_among_same_named_results(monkeypatch) -> None:
    """Multiple "Paris" results - the real French capital must outrank small US towns."""
    payload = {
        "results": [
            _result("Paris", "United States", 33.66, -95.55, "America/Chicago", population=25000, feature_code="PPLA2"),
            _result("Paris", "France", 48.85, 2.35, "Europe/Paris", population=2138551, feature_code="PPLC"),
        ]
    }

    async def fake_get(self, url, params=None, **kwargs):
        return _FakeResponse(payload)

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)
    result = await geocode("paris")
    assert result is not None
    assert result["timezone"] == "Europe/Paris"
    assert result["country"] == "France"


@pytest.mark.asyncio
async def test_geocode_retries_transient_failure_then_succeeds(monkeypatch) -> None:
    """A 503 (transient) is retried and a later attempt can still succeed."""
    calls = {"n": 0}
    payload = {"results": [_result("Tokyo", "Japan", 35.68, 139.69, "Asia/Tokyo", population=9000000, feature_code="PPLC")]}

    async def fake_get(self, url, params=None, **kwargs):
        calls["n"] += 1
        if calls["n"] < 2:
            return _FakeResponse({}, status_code=503)
        return _FakeResponse(payload)

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)
    result = await geocode("tokyo")
    assert result is not None
    assert result["resolved_name"] == "Tokyo"
    assert calls["n"] >= 2  # actually retried, not just lucky on the first call


@pytest.mark.asyncio
async def test_geocode_gives_up_gracefully_after_repeated_transient_failures(monkeypatch) -> None:
    """Persistent network failure returns None (a clear "not found") instead of raising."""

    async def fake_get(self, url, params=None, **kwargs):
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)
    result = await geocode("anywhere")
    assert result is None


@pytest.mark.asyncio
async def test_geocode_does_not_retry_deterministic_client_error(monkeypatch) -> None:
    """A 400-class error is not worth retrying - only the client-error path is exercised, not backoff."""
    calls = {"n": 0}

    async def fake_get(self, url, params=None, **kwargs):
        calls["n"] += 1
        return _FakeResponse({}, status_code=404)

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)
    result = await geocode("zz_no_such_place_zz")
    assert result is None
    # One call per candidate tried (original + any split fallbacks), not
    # 3x per candidate from the transient-retry loop.
    assert calls["n"] <= 3


@pytest.mark.asyncio
async def test_geocode_resolves_compound_neighborhood_city_query(monkeypatch) -> None:
    """"Madhapur, Hyderabad" only matches when split into segments."""

    async def fake_get(self, url, params=None, **kwargs):
        name = params["name"]
        if name.lower() == "madhapur":
            return _FakeResponse({"results": [_result("Madhapur", "India", 17.44, 78.38, "Asia/Kolkata")]})
        return _FakeResponse({"results": []})

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)
    result = await geocode("Madhapur, Hyderabad")
    assert result is not None
    assert result["resolved_name"] == "Madhapur"


@pytest.mark.asyncio
async def test_alias_correction_applies_to_split_candidates_not_just_the_whole_string(monkeypatch) -> None:
    """A garbled/compound query (e.g. from imperfect location extraction on a
    multi-tool message) only becomes correctable once split down to its
    "bangalore" piece - correction must be retried on each split candidate,
    not just the original combined string, or it silently never fires."""

    async def fake_get(self, url, params=None, **kwargs):
        name = params["name"].lower()
        if name == "bengaluru":
            return _FakeResponse({"results": [_result("Bengaluru", "India", 12.97, 77.59, "Asia/Kolkata", population=8000000, feature_code="PPLA")]})
        if name == "bangalore":
            # What Open-Meteo actually returns for the UNCORRECTED name - a
            # same-named place in the wrong country entirely.
            return _FakeResponse({"results": [_result("Bangalore Town", "Pakistan", 24.87, 67.08, "Asia/Karachi")]})
        return _FakeResponse({"results": []})

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)
    result = await geocode("bangalore, what time is it in tokyo")
    assert result is not None
    assert result["country"] == "India"
    assert result["resolved_name"] == "Bengaluru"
