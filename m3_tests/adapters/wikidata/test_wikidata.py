"""Wikidata adapter: catalog, happy paths, language fallback and error paths, from cassettes."""

from __future__ import annotations

import pytest

from m3_tests._support.cassettes import recorded
from m3_tests._support.results import result_text

pytestmark = pytest.mark.m3(suite_name="wikidata")

API = "https://www.wikidata.org/w/api.php"


def entity_request(entity_id: str, language: str, sites: str) -> str:
    """The wbgetentities URL the adapter sends, so a test can read its own cassette."""
    return (
        f"{API}?action=wbgetentities&ids={entity_id}&props=labels%7Cdescriptions%7Csitelinks"
        f"&languages={language}&languagefallback=1&sitefilter={sites}&format=json"
    )


def test_lists_both_wikidata_tools_with_documented_inputs(connect) -> None:
    """The catalog has wikidata_search_entities(query) and wikidata_get_entity(entity_id)."""
    with connect("wikidata") as client:
        tools = {t.name: t for t in client.list_all_tools() if t.name.startswith("wikidata_")}
    assert set(tools) == {"wikidata_search_entities", "wikidata_get_entity"}
    search, entity = tools["wikidata_search_entities"], tools["wikidata_get_entity"]
    assert list(search.input_schema["required"]) == ["query"]
    assert set(search.input_schema["properties"]) == {"query", "language", "limit"}
    assert search.input_schema["properties"]["language"]["default"] == "en"
    assert search.input_schema["properties"]["limit"]["default"] == 5
    assert list(entity.input_schema["required"]) == ["entity_id"]
    assert set(entity.input_schema["properties"]) == {"entity_id", "language"}
    assert entity.input_schema["properties"]["language"]["default"] == "en"
    for tool in (search, entity):
        assert tool.description
        for prop in tool.input_schema["properties"].values():
            assert prop["description"]


def test_search_finds_douglas_adams_as_q42(connect) -> None:
    """Searching 'Douglas Adams' returns compact results that include Q42 with a canonical URL."""
    with connect("wikidata") as client:
        result = client.call_tool(
            "wikidata_search_entities", {"query": "  Douglas Adams ", "limit": 2}
        )
    assert result.is_error is False, result_text(result)
    data = result.structured_content
    assert data["query"] == "Douglas Adams"
    assert data["language"] == "en"
    assert data["returned"] == len(data["results"]) <= 2
    by_id = {r["id"]: r for r in data["results"]}
    assert "Q42" in by_id
    assert by_id["Q42"]["label"] == "Douglas Adams"
    assert by_id["Q42"]["description"]
    for item in data["results"]:
        assert set(item) == {"id", "label", "description", "url", "match"}
        assert item["url"] == f"https://www.wikidata.org/wiki/{item['id']}"


def test_get_entity_returns_q42_label_description_and_wikipedia_link(connect) -> None:
    """Q42 is Douglas Adams; the result is compact and links his English Wikipedia article."""
    with connect("wikidata") as client:
        result = client.call_tool("wikidata_get_entity", {"entity_id": "Q42"})
    assert result.is_error is False, result_text(result)
    data = result.structured_content
    assert data["id"] == "Q42"
    assert data["label"] == "Douglas Adams"
    assert data["description"]
    assert data["url"] == "https://www.wikidata.org/wiki/Q42"
    assert data["wikipedia"] == {
        "language": "en",
        "title": "Douglas Adams",
        "url": "https://en.wikipedia.org/wiki/Douglas_Adams",
    }
    assert "claims" not in data


def test_get_entity_falls_back_when_the_label_is_not_in_the_requested_language(
    connect, replaying
) -> None:
    """For 'de' the label may be filed under another language (Q42's is 'mul'); we report it."""
    with connect("wikidata") as client:
        result = client.call_tool("wikidata_get_entity", {"entity_id": "Q42", "language": "de"})
    assert result.is_error is False, result_text(result)
    data = result.structured_content
    assert data["language"] == "de"
    assert data["label"] == "Douglas Adams"
    assert data["label_language"]
    assert data["description"]
    assert data["wikipedia"]["language"] in {"de", "en"}
    if replaying:  # which language the API fell back to can change; read it from the cassette
        body = recorded("wikidata", entity_request("Q42", "de", "dewiki%7Cenwiki"))
        label = body["entities"]["Q42"]["labels"]["de"]
        assert data["label_language"] == label["language"]
        assert data["label"] == label["value"]


def test_get_entity_without_sitelinks_has_no_wikipedia_link(connect) -> None:
    """P31 ('instance of') is a property with no Wikipedia article: wikipedia is null."""
    with connect("wikidata") as client:
        result = client.call_tool("wikidata_get_entity", {"entity_id": "P31"})
    assert result.is_error is False, result_text(result)
    data = result.structured_content
    assert data["id"] == "P31"
    assert data["label"] == "instance of"
    assert data["wikipedia"] is None


def test_unknown_entity_in_an_http_200_body_becomes_a_readable_error(connect, replaying) -> None:
    """'Qzzz' gets HTTP 200 with an error body (no-such-entity); the tool reports it clearly."""
    with connect("wikidata") as client:
        result = client.call_tool("wikidata_get_entity", {"entity_id": "Qzzz"})
    assert result.is_error is True
    text = result_text(result)
    assert "no-such-entity" in text
    assert "Qzzz" in text
    if replaying:
        body = recorded("wikidata", entity_request("Qzzz", "en", "enwiki"))
        assert body["error"]["code"] == "no-such-entity"


@pytest.mark.parametrize(
    ("tool", "arguments", "message"),
    [
        ("wikidata_search_entities", {"query": "  "}, "query must not be empty"),
        ("wikidata_search_entities", {"query": "x", "limit": 0}, "limit must be between 1 and 50"),
        ("wikidata_search_entities", {"query": "x", "limit": 51}, "limit must be between 1 and 50"),
        ("wikidata_search_entities", {"query": "x", "language": "evil.com/"}, "language code"),
        ("wikidata_get_entity", {"entity_id": " "}, "entity_id must not be empty"),
        ("wikidata_get_entity", {"entity_id": "Q42|Q1"}, "single ID"),
        ("wikidata_get_entity", {"entity_id": "Q42", "language": "EN US"}, "language code"),
    ],
)
def test_invalid_input_is_rejected_before_any_request(connect, tool, arguments, message) -> None:
    """Bad arguments are is_error results with a fix-it message; no cassette is needed."""
    with connect("wikidata") as client:
        result = client.call_tool(tool, arguments)
    assert result.is_error is True
    assert message in result_text(result)


@pytest.mark.live
def test_live_search_and_lookup_hit_the_real_api(connect) -> None:
    """Smoke test against the real Wikidata API (excluded from PR CI)."""
    with connect("wikidata", mode="live") as client:
        search = client.call_tool("wikidata_search_entities", {"query": "Douglas Adams"})
        entity = client.call_tool("wikidata_get_entity", {"entity_id": "Q42"})
    assert search.is_error is False, result_text(search)
    assert search.structured_content["results"]
    assert entity.is_error is False, result_text(entity)
    assert entity.structured_content["id"] == "Q42"
    assert entity.structured_content["label"]
