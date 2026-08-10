"""Tests for the weather and current-time tools - location resolution,
retry-on-transient-failure, and clear (non-fabricated) error responses.
Geocoding itself is covered in test_geocoding.py; here it's mocked so these
tests focus on each tool's own behavior.
"""
from __future__ import annotations

import httpx
import pytest

from app.tools.tools.time_tool import CurrentTimeTool
from app.tools.tools.weather import WeatherTool


class _FakeForecastResponse:
    def __init__(self, payload: dict, status_code: int = 200) -> None:
        self._payload = payload
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            request = httpx.Request("GET", "https://api.open-meteo.com/v1/forecast")
            response = httpx.Response(self.status_code, request=request)
            raise httpx.HTTPStatusError("error", request=request, response=response)

    def json(self) -> dict:
        return self._payload


_FORECAST_PAYLOAD = {
    "current_weather": {"temperature": 28.4, "windspeed": 11.2, "weathercode": 1},
    "current_weather_units": {"temperature": "°C", "windspeed": "km/h"},
}


# ---------------------------------------------------------------------------
# Weather tool
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_weather_resolves_misspelled_city_and_returns_data(monkeypatch) -> None:
    """A misspelled city still geocodes (via the geocoding module's own correction) and gets weather."""

    async def fake_geocode(location: str):
        assert location == "banglore"
        return {"lat": 12.97, "lon": 77.59, "timezone": "Asia/Kolkata", "resolved_name": "Bengaluru", "country": "India"}

    async def fake_get(self, url, params=None, **kwargs):
        return _FakeForecastResponse(_FORECAST_PAYLOAD)

    monkeypatch.setattr("app.tools.geocoding.geocode", fake_geocode)
    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)

    tool = WeatherTool()
    result = await tool.invoke(city="banglore")
    assert result.success
    assert result.output["location"] == "Bengaluru, India"
    assert result.output["temperature_c"] == 28.4


@pytest.mark.asyncio
async def test_weather_unresolvable_location_returns_clear_error(monkeypatch) -> None:
    """A location that can't be geocoded at all fails clearly instead of fabricating weather."""

    async def fake_geocode(location: str):
        return None

    monkeypatch.setattr("app.tools.geocoding.geocode", fake_geocode)

    tool = WeatherTool()
    result = await tool.invoke(city="zzznosuchplacezzz")
    assert not result.success
    assert "zzznosuchplacezzz" in result.error


@pytest.mark.asyncio
async def test_weather_retries_transient_forecast_failure_then_succeeds(monkeypatch) -> None:
    """A 503 from the forecast API (not the geocoder) is retried, not surfaced as a hard failure."""
    calls = {"n": 0}

    async def fake_geocode(location: str):
        return {"lat": 1.0, "lon": 2.0, "timezone": "UTC", "resolved_name": "Testville", "country": None}

    async def fake_get(self, url, params=None, **kwargs):
        calls["n"] += 1
        if calls["n"] < 2:
            return _FakeForecastResponse({}, status_code=503)
        return _FakeForecastResponse(_FORECAST_PAYLOAD)

    monkeypatch.setattr("app.tools.geocoding.geocode", fake_geocode)
    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)

    tool = WeatherTool()
    result = await tool.invoke(city="Testville")
    assert result.success
    assert calls["n"] >= 2


@pytest.mark.asyncio
async def test_weather_gives_up_after_persistent_forecast_failure(monkeypatch) -> None:
    """Persistent forecast-API failure after all retries returns a clear, marked-transient error."""

    async def fake_geocode(location: str):
        return {"lat": 1.0, "lon": 2.0, "timezone": "UTC", "resolved_name": "Testville", "country": None}

    async def fake_get(self, url, params=None, **kwargs):
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr("app.tools.geocoding.geocode", fake_geocode)
    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)

    tool = WeatherTool()
    result = await tool.invoke(city="Testville")
    assert not result.success
    assert result.metadata.get("transient") is True


@pytest.mark.asyncio
async def test_weather_requires_city_or_coordinates() -> None:
    tool = WeatherTool()
    result = await tool.invoke()
    assert not result.success


# ---------------------------------------------------------------------------
# Current-time tool
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_time_resolves_location_to_correct_timezone(monkeypatch) -> None:
    async def fake_geocode(location: str):
        assert location == "delhy"
        return {"lat": 28.65, "lon": 77.23, "timezone": "Asia/Kolkata", "resolved_name": "Delhi", "country": "India"}

    monkeypatch.setattr("app.tools.geocoding.geocode", fake_geocode)

    tool = CurrentTimeTool()
    result = await tool.invoke(location="delhy")
    assert result.success
    assert result.output["timezone"] == "Asia/Kolkata"
    assert result.output["location"] == "Delhi, India"


@pytest.mark.asyncio
async def test_time_explicit_timezone_skips_geocoding(monkeypatch) -> None:
    async def fake_geocode(location: str):
        raise AssertionError("geocode should not be called when timezone is given explicitly")

    monkeypatch.setattr("app.tools.geocoding.geocode", fake_geocode)

    tool = CurrentTimeTool()
    result = await tool.invoke(timezone="America/New_York")
    assert result.success
    assert result.output["timezone"] == "America/New_York"


@pytest.mark.asyncio
async def test_time_unresolvable_location_returns_clear_error(monkeypatch) -> None:
    async def fake_geocode(location: str):
        return None

    monkeypatch.setattr("app.tools.geocoding.geocode", fake_geocode)

    tool = CurrentTimeTool()
    result = await tool.invoke(location="zzznosuchplacezzz")
    assert not result.success
    assert "zzznosuchplacezzz" in result.error


@pytest.mark.asyncio
async def test_time_invalid_explicit_timezone_returns_clear_error() -> None:
    tool = CurrentTimeTool()
    result = await tool.invoke(timezone="Not/ARealZone")
    assert not result.success
    assert "timezone" in result.error.lower()
