"""Real-agent lane: given a plain-English question, does the agent pick the right keyless tool?

Each case is one natural-language prompt that never names a tool. The agent gets the whole
keyless-mcp catalog (every adapter), so a pass means it chose the right tool among every other tool
in the catalog, and the assertion checks the call M3 recorded on the wire (tool, arguments and a
successful result), not what the agent says it did.

The server runs in LIVE mode: real agent, real upstream APIs, real data. These tests cost model
tokens and need network, so they are marked ``agent`` and ``live`` and never run in ``make test``.
Run them with ``make agent`` (see docs/agent-testing.md).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

import pytest
from m3 import ExecutionOutcome, expect

from m3_tests._support.servers import keyless_server

pytestmark = [
    pytest.mark.m3(suite_name="agent-tool-selection"),
    pytest.mark.agent,
    pytest.mark.live,
]

ALIAS = "keyless"

# Hints are added per harness kind, and only where a harness needs one. Codex brings its own web
# search and, left alone, answers from that, which says nothing about keyless-mcp. Its hint points
# the agent at the server without naming any tool, so the test still measures which of the
# catalog's tools it picks. Claude Code needs none: M3 turns its built-in tools off. A harness
# not listed here gets the bare prompt.
HARNESS_HINTS: dict[str, str] = {
    "codex": f"Use only the tools of the `{ALIAS}` MCP server for this; do not browse the web. ",
}

Check = Callable[[Mapping[str, Any]], bool]


def _text(args: Mapping[str, Any], key: str) -> str:
    return str(args.get(key, "")).strip().lower()


def _near(args: Mapping[str, Any], lat: float, lon: float, tolerance: float = 1.0) -> bool:
    try:
        return (
            abs(float(args["latitude"]) - lat) <= tolerance
            and abs(float(args["longitude"]) - lon) <= tolerance
        )
    except (KeyError, TypeError, ValueError):
        return False


def _in_range(args: Mapping[str, Any], key: str, low: int, high: int, default: int) -> bool:
    """True when the optional integer argument is absent (server default) or within bounds."""
    try:
        return low <= int(args.get(key, default)) <= high
    except (TypeError, ValueError):
        return False


def _currency_pair(args: Mapping[str, Any], one: str, other: str) -> bool:
    """True when the call covers the pair in either direction; no symbols means every currency."""
    base = _text(args, "base") or "eur"
    symbols = args.get("symbols")
    targets = (
        None if symbols is None else {code.strip().lower() for code in str(symbols).split(",")}
    )
    for left, right in ((one, other), (other, one)):
        if base == left and (targets is None or right in targets):
            return True
    return False


@dataclass(frozen=True)
class Case:
    """One prompt and the call that proves the agent picked the right tool."""

    id: str
    prompt: str
    tools: tuple[str, ...]  # any one of these tool names is acceptable
    arguments_ok: Check  # key arguments, checked on the recorded call
    must_not_call: tuple[str, ...] = ()  # look-alike tools that would be the wrong choice


CASES = (
    Case(
        "arxiv-search",
        "Find a few recent arXiv preprints about retrieval-augmented generation.",
        ("arxiv_search",),
        lambda a: "retrieval" in _text(a, "query"),
    ),
    Case(
        "arxiv-paper",
        "Give me the abstract and authors of arXiv paper 1706.03762.",
        ("arxiv_get_paper",),
        lambda a: "1706.03762" in _text(a, "arxiv_id"),
    ),
    Case(
        "osv-query",
        "Are there known security vulnerabilities in version 2.4.1 of the PyPI package jinja2?",
        ("osv_query_package",),
        lambda a: (
            _text(a, "name") == "jinja2"
            and _text(a, "ecosystem") == "pypi"
            and _text(a, "version") == "2.4.1"
        ),
    ),
    Case(
        "osv-advisory",
        "What is security advisory GHSA-35jh-r3h4-6jhm about, and which version fixes it?",
        ("osv_get_vulnerability",),
        lambda a: _text(a, "vuln_id") == "ghsa-35jh-r3h4-6jhm",
    ),
    Case(
        "wikipedia-summary",
        "Give me a short summary of Alan Turing from Wikipedia.",
        ("wikipedia_get_summary",),
        lambda a: "turing" in _text(a, "title"),
    ),
    Case(
        "pypi-package",
        "What is the latest released version of the Python package requests, and what license?",
        ("pypi_get_package",),
        lambda a: _text(a, "name") == "requests",
        must_not_call=("npm_get_package",),
    ),
    Case(
        "npm-package",
        "What is the latest version of the npm package express?",
        ("npm_get_package",),
        lambda a: _text(a, "name") == "express",
        must_not_call=("pypi_get_package",),
    ),
    Case(
        "open-meteo-forecast",
        "What will the weather be like in Lisbon over the next three days?",
        ("open_meteo_forecast",),
        lambda a: _near(a, 38.72, -9.14),
    ),
    Case(
        "world-bank-country",
        "What is the capital city and the region of Japan, according to World Bank data?",
        ("world_bank_country_search", "world_bank_country_by_code"),
        lambda a: _text(a, "name") == "japan" or _text(a, "code") in {"jp", "jpn"},
    ),
    Case(
        "hackernews-top",
        "What are the top stories on Hacker News right now?",
        ("hackernews_top_stories",),
        lambda a: _in_range(a, "limit", 1, 30, default=10),
    ),
    Case(
        "sunrise-sunset-times",
        "What time did the sun rise and set at latitude 36.72, longitude -4.42 on 2024-06-21?",
        ("sunrise_sunset_get_times",),
        lambda a: _near(a, 36.72, -4.42) and _text(a, "date") == "2024-06-21",
    ),
    Case(
        "frankfurter-rate",
        "What was the euro to US dollar reference exchange rate on 2 January 2024?",
        ("frankfurter_get_rates",),
        lambda a: _text(a, "date") == "2024-01-02" and _currency_pair(a, "eur", "usd"),
    ),
    Case(
        "frankfurter-series",
        "Show the daily euro to British pound reference rate from 2 to 12 January 2024.",
        ("frankfurter_get_time_series",),
        lambda a: (
            _text(a, "start_date") == "2024-01-02"
            and _text(a, "end_date") == "2024-01-12"
            and _currency_pair(a, "eur", "gbp")
        ),
    ),
    Case(
        "endoflife-product",
        "When does Python 3.12 reach end of life?",
        ("endoflife_get_product",),
        lambda a: _text(a, "product") == "python",
    ),
)


def _arguments(call: Mapping[str, Any]) -> Mapping[str, Any]:
    value = call["arguments"]
    return value if isinstance(value, Mapping) else {}


@pytest.mark.parametrize("case", CASES, ids=lambda case: case.id)
def test_agent_picks_the_right_tool(agent, m3_kit, case: Case) -> None:
    server = keyless_server("agent", mode="live", name=ALIAS)
    kind = agent.harness.lower().replace("-", "_")
    options: dict[str, Any] = {}
    if kind not in {"claude", "claude_code"}:
        # Claude Code is limited to the server as a whole and cannot take a per-tool list; other
        # harnesses get every keyless tool, which keeps them off their own shell and web tools.
        with m3_kit.direct(server) as client:
            options["tools"] = [f"{ALIAS}:{tool.name}" for tool in client.list_all_tools()]

    prompt = HARNESS_HINTS.get(kind, "") + case.prompt
    result = agent.run(prompt, server=server, timeout=180, **options)

    assert result.snapshot.outcome is ExecutionOutcome.COMPLETED, result.error
    expect(result).to_have_tool_call(
        server=ALIAS,
        status="success",
        min_count=1,
        predicate=lambda call: call["tool"] in case.tools and case.arguments_ok(_arguments(call)),
    )
    for wrong in case.must_not_call:
        expect(result).to_not_have_tool_call(wrong, server=ALIAS)
