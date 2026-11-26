"""Recorded MCP contracts for Frankfurter's currency reference rates."""

import datetime

import pytest

from m3_tests._support.cassettes import recorded
from m3_tests._support.results import result_text

pytestmark = pytest.mark.m3(suite_name="frankfurter")
BASE_URL = "https://api.frankfurter.dev/v1"


def test_lists_the_frankfurter_tools(connect) -> None:
    """Finance tools advertise their required date range and optional currency filters."""
    with connect("frankfurter") as client:
        tools = {t.name: t for t in client.list_all_tools() if t.name.startswith("frankfurter_")}
    assert set(tools) == {
        "frankfurter_get_rates",
        "frankfurter_get_time_series",
        "frankfurter_list_currencies",
    }
    assert tools["frankfurter_get_rates"].input_schema["properties"]["base"]["default"] == "EUR"
    assert tuple(tools["frankfurter_get_time_series"].input_schema["required"]) == (
        "start_date",
        "end_date",
    )


def test_historical_rates_report_the_working_day(connect, replaying) -> None:
    """A Saturday request reports Friday's observation date, not the requested date."""
    with connect("frankfurter") as client:
        result = client.call_tool(
            "frankfurter_get_rates", {"date": "2024-01-06", "symbols": "USD, GBP"}
        )
    assert not result.is_error, result_text(result)
    data = result.structured_content
    assert data["base"] == "EUR"
    assert data["date"] == "2024-01-05"
    assert data["amount"] == 1
    assert set(data["rates"]) == {"USD", "GBP"}
    assert all(value > 0 for value in data["rates"].values())
    if replaying:
        expected = recorded("frankfurter", f"{BASE_URL}/2024-01-06?base=EUR&symbols=USD,GBP")
        assert data["rates"] == expected["rates"]
    assert data["source_url"].startswith(f"{BASE_URL}/2024-01-06?")


def test_latest_rates_keep_the_observation_date(connect, replaying) -> None:
    """The latest request returns a dated USD reference rate in EUR."""
    with connect("frankfurter") as client:
        result = client.call_tool("frankfurter_get_rates", {"base": "USD", "symbols": "EUR"})
    assert not result.is_error, result_text(result)
    data = result.structured_content
    assert data["base"] == "USD"
    assert set(data["rates"]) == {"EUR"}
    assert datetime.date.fromisoformat(data["date"])
    if replaying:
        expected = recorded("frankfurter", f"{BASE_URL}/latest?base=USD&symbols=EUR")
        assert data["date"] == expected["date"]
        assert data["rates"] == expected["rates"]


def test_time_series_returns_daily_rates(connect, replaying) -> None:
    """A short historical range returns the three requested working days and one currency."""
    with connect("frankfurter") as client:
        result = client.call_tool(
            "frankfurter_get_time_series",
            {"start_date": "2024-01-02", "end_date": "2024-01-04", "symbols": "USD"},
        )
    assert not result.is_error, result_text(result)
    data = result.structured_content
    assert data["base"] == "EUR"
    assert data["start_date"] == "2024-01-02"
    assert data["end_date"] == "2024-01-04"
    assert set(data["rates"]) == {"2024-01-02", "2024-01-03", "2024-01-04"}
    assert all(set(rates) == {"USD"} and rates["USD"] > 0 for rates in data["rates"].values())
    if replaying:
        expected = recorded(
            "frankfurter", f"{BASE_URL}/2024-01-02..2024-01-04?base=EUR&symbols=USD"
        )
        assert data["rates"] == expected["rates"]


@pytest.mark.parametrize("end_date", ["2024-01-02", "2024-02-01"])
def test_time_series_accepts_one_and_31_days(connect, end_date) -> None:
    """Inclusive one-day and maximum-length ranges both return historical observations."""
    with connect("frankfurter") as client:
        result = client.call_tool(
            "frankfurter_get_time_series",
            {"start_date": "2024-01-02", "end_date": end_date, "symbols": "USD"},
        )
    assert not result.is_error, result_text(result)
    data = result.structured_content
    assert data["start_date"] == "2024-01-02"
    assert data["end_date"] == end_date
    assert 1 <= len(data["rates"]) <= 31
    assert all(set(rates) == {"USD"} for rates in data["rates"].values())


def test_list_currencies_returns_codes_and_names(connect) -> None:
    """The supported currencies include the euro, US dollar and British pound."""
    with connect("frankfurter") as client:
        result = client.call_tool("frankfurter_list_currencies", {})
    assert not result.is_error, result_text(result)
    data = result.structured_content
    assert data["currencies"]["EUR"] == "Euro"
    assert data["currencies"]["USD"] == "United States Dollar"
    assert data["currencies"]["GBP"] == "British Pound"
    assert data["count"] == len(data["currencies"])
    assert data["source_url"] == f"{BASE_URL}/currencies"


def test_unknown_base_reports_upstream_error(connect) -> None:
    """A syntactically valid but unknown code preserves the API's 404 error."""
    with connect("frankfurter") as client:
        result = client.call_tool("frankfurter_get_rates", {"base": "ZZZ"})
    assert result.is_error
    assert "404" in result_text(result)
    assert "not found" in result_text(result).lower()


@pytest.mark.parametrize(
    ("tool", "arguments", "message"),
    [
        ("get_rates", {"base": "eur"}, "three uppercase letters"),
        ("get_rates", {"symbols": "USD,,GBP"}, "three uppercase letters"),
        ("get_rates", {"symbols": ""}, "three uppercase letters"),
        ("get_rates", {"date": "2024-02-30"}, "valid calendar date"),
        ("get_rates", {"date": "20240106"}, "YYYY-MM-DD"),
        ("get_rates", {"date": "../currencies"}, "YYYY-MM-DD"),
        (
            "get_time_series",
            {"start_date": "2024-01-05", "end_date": "2024-01-02"},
            "must not be after",
        ),
        (
            "get_time_series",
            {"start_date": "2024-01-01", "end_date": "2024-02-01"},
            "31 calendar days",
        ),
    ],
)
def test_invalid_arguments_fail_before_http(connect, tool, arguments, message) -> None:
    """Invalid dates, ranges and currency filters fail without needing a cassette."""
    with connect("frankfurter") as client:
        result = client.call_tool(f"frankfurter_{tool}", arguments)
    assert result.is_error
    assert message in result_text(result)


@pytest.mark.live
def test_live_rates_hit_the_real_api(connect) -> None:
    """The live API returns the requested fixed-date USD reference rate."""
    with connect("frankfurter", mode="live") as client:
        result = client.call_tool("frankfurter_get_rates", {"date": "2024-01-06", "symbols": "USD"})
    assert not result.is_error, result_text(result)
    assert result.structured_content["date"] == "2024-01-05"
    assert result.structured_content["rates"]["USD"] > 0
