"""endoflife.date v1 contracts: recorded MCP calls and fixed-date lifecycle semantics."""

import datetime
import re

import pytest

from keyless_mcp.adapters.endoflife import tools as adapter
from keyless_mcp.core import UpstreamError, cassette
from m3_tests._support.cassettes import recorded
from m3_tests._support.results import result_text

pytestmark = pytest.mark.m3(suite_name="endoflife")
BASE_URL = "https://endoflife.date/api/v1"
TODAY = datetime.date(2026, 11, 27)


def test_lists_the_endoflife_tools(connect) -> None:
    """The dev catalog offers product lookup and slug discovery, with a bounded default."""
    with connect("endoflife", toolsets=["dev"]) as client:
        tools = {t.name: t for t in client.list_all_tools() if t.name.startswith("endoflife_")}
    assert set(tools) == {"endoflife_get_product", "endoflife_list_products"}
    schema = tools["endoflife_get_product"].input_schema
    assert tuple(schema["required"]) == ("product",)
    assert schema["properties"]["limit"]["default"] == 10


def test_python_releases_report_versions_dates_and_source(connect, replaying) -> None:
    """The Python product returns two release cycles, preserving documented v1 fields."""
    with connect("endoflife") as client:
        result = client.call_tool("endoflife_get_product", {"product": "python", "limit": 2})
    assert not result.is_error, result_text(result)
    data = result.structured_content
    assert data["product"] == "python"
    assert data["returned"] == len(data["cycles"]) == 2
    assert data["total"] >= data["returned"]
    assert data["source_url"] == f"{BASE_URL}/products/python/"
    as_of = datetime.date.fromisoformat(data["as_of"])
    for cycle in data["cycles"]:
        assert cycle["cycle"]
        assert datetime.date.fromisoformat(cycle["release_date"])
        assert cycle["latest"]
        if isinstance(cycle["eol"], str):
            assert cycle["eol_passed"] == (datetime.date.fromisoformat(cycle["eol"]) <= as_of)
        else:
            assert cycle["eol_passed"] is cycle["eol"]
    if replaying:
        source = recorded("endoflife", f"{BASE_URL}/products/python/")["result"]
        assert data["total"] == len(source["releases"])
        for cycle, release in zip(data["cycles"], source["releases"], strict=False):
            assert cycle["cycle"] == release["name"]
            assert cycle["latest"] == release["latest"]["name"]
            assert cycle["latest_release_date"] == release["latest"]["date"]
            assert cycle["eol"] == (
                release["eolFrom"] if release["eolFrom"] is not None else release["isEol"]
            )
            assert cycle["support"] == (
                release["eoasFrom"] if release["eoasFrom"] is not None else not release["isEoas"]
            )
            assert cycle["lts"] == (
                release["ltsFrom"] if release["ltsFrom"] is not None else release["isLts"]
            )


@pytest.mark.parametrize("limit", [1, 25])
def test_cycle_limit_bounds_the_response(connect, limit) -> None:
    with connect("endoflife") as client:
        result = client.call_tool("endoflife_get_product", {"product": "python", "limit": limit})
    assert not result.is_error, result_text(result)
    data = result.structured_content
    assert data["returned"] == len(data["cycles"]) == min(limit, data["total"])


def test_lists_canonical_product_slugs(connect, replaying) -> None:
    """Discovery returns canonical names, rather than the full upstream metadata index."""
    with connect("endoflife") as client:
        result = client.call_tool("endoflife_list_products", {})
    assert not result.is_error, result_text(result)
    data = result.structured_content
    assert {"python", "ubuntu", "nodejs"} <= set(data["products"])
    assert data["count"] == len(data["products"])
    assert all(re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", slug) for slug in data["products"])
    assert data["source_url"] == f"{BASE_URL}/products/"
    if replaying:
        assert list(data["products"]) == [
            product["name"] for product in recorded("endoflife", f"{BASE_URL}/products/")["result"]
        ]


def test_unknown_product_handles_an_html_404(connect) -> None:
    with connect("endoflife") as client:
        result = client.call_tool("endoflife_get_product", {"product": "notaproduct"})
    assert result.is_error
    assert "404" in result_text(result)
    assert "not found" in result_text(result).lower()


@pytest.mark.parametrize(
    "arguments, message",
    [
        ({"product": ""}, "slug"),
        ({"product": "Python"}, "slug"),
        ({"product": "../python"}, "slug"),
        ({"product": "python?limit=1"}, "slug"),
        ({"product": "python", "limit": -1}, "between 1 and 25"),
        ({"product": "python", "limit": 0}, "between 1 and 25"),
        ({"product": "python", "limit": 26}, "between 1 and 25"),
        ({"product": "python", "limit": 500}, "between 1 and 25"),
    ],
)
def test_invalid_input_is_rejected_before_http(connect, arguments, message) -> None:
    with connect("endoflife") as client:
        result = client.call_tool("endoflife_get_product", arguments)
    assert result.is_error
    assert message in result_text(result)


@pytest.mark.parametrize(
    "release, expected",
    [
        ({"eolFrom": "2026-11-26", "isEol": False}, True),
        ({"eolFrom": "2026-11-27", "isEol": False}, True),
        ({"eolFrom": "2026-11-28", "isEol": True}, False),
        ({"eolFrom": None, "isEol": True}, True),
        ({"eolFrom": None, "isEol": False}, False),
        ({}, None),
        ({"isEol": 0}, None),
        ({"isEol": "false"}, None),
    ],
)
def test_eol_dates_use_the_utc_reference_day_and_booleans_are_not_dates(release, expected) -> None:
    """Fixed reference days make boundary expectations independent of the live calendar."""
    cycle = adapter._cycle({"name": "1", **release}, TODAY)
    assert cycle["eol_passed"] is expected


@pytest.mark.parametrize(
    "release, support, lts",
    [
        ({"isEoas": False, "isLts": False}, True, False),
        ({"isEol": False, "isEoas": True, "isLts": True}, False, True),
        (
            {"eoasFrom": "2027-01-01", "isEoas": False, "ltsFrom": "2026-01-01", "isLts": True},
            "2027-01-01",
            "2026-01-01",
        ),
        ({}, None, None),
    ],
)
def test_support_lts_and_missing_latest_are_preserved(release, support, lts) -> None:
    cycle = adapter._cycle({"name": "1", **release}, TODAY)
    assert cycle["support"] == support
    if "isEol" in release:
        assert cycle["eol_passed"] is release["isEol"]
    assert cycle["lts"] == lts
    assert cycle["latest"] is None
    assert cycle["latest_release_date"] is None
    assert cycle["release_date"] is None


def test_a_malformed_eol_date_is_an_upstream_error() -> None:
    with pytest.raises(UpstreamError, match="EOL date"):
        adapter._cycle({"name": "1", "eolFrom": "not-a-date"}, TODAY)


@pytest.mark.parametrize("result", [None, [], {"name": "broken"}, {"releases": {}}])
def test_unusable_product_responses_are_readable_errors(connect, tmp_path, result) -> None:
    """Synthetic responses are replay-only, so recording never sends these cases upstream."""
    cassette.save(
        tmp_path,
        "GET",
        f"{BASE_URL}/products/python/",
        None,
        cassette.RecordedResponse(200, "application/json", {"result": result}),
    )
    with connect("endoflife", mode="replay", cassettes=tmp_path) as client:
        response = client.call_tool("endoflife_get_product", {"product": "python"})
    assert response.is_error
    assert "response" in result_text(response)


@pytest.mark.live
def test_live_both_tools_hit_the_current_api(connect) -> None:
    with connect("endoflife", mode="live") as client:
        product = client.call_tool("endoflife_get_product", {"product": "python", "limit": 1})
        products = client.call_tool("endoflife_list_products", {})
    assert not product.is_error, result_text(product)
    assert not products.is_error, result_text(products)
    assert product.structured_content["returned"] == 1
    assert "python" in products.structured_content["products"]


@pytest.mark.parametrize("limit", [True, False, 1.0, 1.5])
def test_limit_requires_an_integer_without_boolean_or_float_coercion(connect, limit) -> None:
    with connect("endoflife", validate_schemas=False) as client:
        result = client.call_tool("endoflife_get_product", {"product": "python", "limit": limit})
    assert result.is_error
    assert "integer" in result_text(result).lower()


@pytest.mark.parametrize(
    "release, message",
    [
        (None, "release cycle"),
        ([], "release cycle"),
        ({}, "release cycle"),
        ({"name": 1}, "release cycle"),
        ({"name": "1", "latest": []}, "latest version"),
        ({"name": "1", "latest": "1.2"}, "latest version"),
        ({"name": "1", "latest": {"name": []}}, "latest version"),
        ({"name": "1", "latest": {"date": 20261127}}, "latest version"),
    ],
)
def test_malformed_releases_raise_clear_upstream_errors(release, message) -> None:
    with pytest.raises(UpstreamError, match=message):
        adapter._cycle(release, TODAY)


@pytest.mark.parametrize("entry", [None, [], {}, {"name": 1}])
def test_malformed_product_index_entries_are_readable_errors(connect, tmp_path, entry) -> None:
    cassette.save(
        tmp_path,
        "GET",
        f"{BASE_URL}/products/",
        None,
        cassette.RecordedResponse(200, "application/json", {"result": [entry]}),
    )
    with connect("endoflife", mode="replay", cassettes=tmp_path) as client:
        result = client.call_tool("endoflife_list_products", {})
    assert result.is_error
    assert "product index entry" in result_text(result)
