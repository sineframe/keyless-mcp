"""Recorded contract tests for the Sunrise-Sunset adapter."""

import pytest

from m3_tests._support.results import result_text

pytestmark = pytest.mark.m3(suite_name="sunrise_sunset")


def test_lists_the_sun_times_tool(connect) -> None:
    """The geo adapter advertises its location and optional date inputs."""
    with connect("sunrise_sunset") as client:
        tools = {tool.name: tool for tool in client.list_all_tools()}
    tool = tools["sunrise_sunset_get_times"]
    assert tuple(tool.input_schema["required"]) == ("latitude", "longitude")


def test_get_times_returns_documented_utc_values(connect) -> None:
    """A fixed Malaga date returns ISO-8601 UTC solar events from the v1 API."""
    with connect("sunrise_sunset") as client:
        result = client.call_tool(
            "sunrise_sunset_get_times",
            {"latitude": 36.72016, "longitude": -4.42034, "date": "2020-01-15"},
        )
    assert result.is_error is False, result_text(result)
    data = result.structured_content
    assert data["status"] == "OK"
    assert data["tzid"] == "UTC"
    assert data["results"]["sunrise"] == "2020-01-15T07:29:17+00:00"
    assert data["results"]["day_length"] == 35715
    assert data["source_url"] == "https://sunrise-sunset.org"


def test_get_times_rejects_out_of_range_latitude(connect) -> None:
    """Coordinates outside the documented latitude range fail before a request."""
    with connect("sunrise_sunset") as client:
        result = client.call_tool("sunrise_sunset_get_times", {"latitude": 999, "longitude": 0})
    assert result.is_error is True
    assert "latitude must be between -90 and 90" in result_text(result)


@pytest.mark.live
def test_live_get_times_hits_the_real_api(connect) -> None:
    """The free public API accepts the adapter's UTC request format."""
    with connect("sunrise_sunset", mode="live") as client:
        result = client.call_tool(
            "sunrise_sunset_get_times",
            {"latitude": 36.72016, "longitude": -4.42034, "date": "2020-01-15"},
        )
    assert result.is_error is False, result_text(result)
