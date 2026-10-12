# Adapter contract

An adapter wraps one free, no-auth public API as a few MCP tools. This page is everything an
adapter author needs. The fastest start is the scaffold:

```sh
make new-adapter NAME=open_meteo TOOLSET=geo    # then follow the printed next steps
```

`make test` (offline) must pass before you open a pull request, and it checks this contract for you.

## What an adapter is

One directory, one API:

```
src/keyless_mcp/adapters/<name>/
    __init__.py      docstring only
    adapter.yaml     metadata (below)
    tools.py         defines register(tools, http)
m3_tests/adapters/<name>/
    __init__.py
    test_<name>.py   M3 tests
    cassettes/       recorded HTTP, one JSON file per request
```

Adapters are discovered automatically: any subpackage of `keyless_mcp.adapters` with an
`adapter.yaml` is loaded. Directories starting with `_` (the template) are skipped. There is no
registry to edit.

## adapter.yaml

All fields are required.

| Field | Meaning |
|---|---|
| `name` | Lowercase snake_case. Must equal the directory name. Prefix of every tool name. |
| `title` | Human-readable name of the API. |
| `description` | One sentence on what the API offers. |
| `toolset` | One of `science`, `dev`, `geo`, `news`, `finance`, `reference`, `fun`. Users enable toolsets with `--toolsets a,b` or `KEYLESS_MCP_TOOLSETS`. |
| `base_url` | The API's base URL (`http(s)://`). |
| `docs_url` | Link to the API's documentation. |
| `rate_limit_per_minute` | Positive integer. The server spaces requests to stay under it, so use the API's documented limit, rounded down. |
| `author` | Your GitHub handle. |

## Registering tools

`tools.py` exposes `register(tools, http)`. `tools.tool()` registers a function as an MCP tool;
`http` is the only way to make requests.

Rules, all enforced at startup or by `m3_tests/catalog/test_contract.py`:

- **Name**: `<adapter>_<verb>` in snake_case, e.g. `arxiv_search`, `osv_query_package`. The
  function name is the tool name.
- **Descriptions**: the function docstring is the tool description. Say what the tool returns
  and when to use it; agents pick tools from these sentences. Every parameter needs
  `Annotated[<type>, Field(description="...")]` with an example value and its limits.
- **Defaults**: give optional parameters a default (`max_results: int = 5`).
- **Results**: return a compact `dict[str, Any]` (put lists under a named key, add `total` or
  `returned` counts). Trim long text with `truncate(text, n)` and include source URLs.
- **Read-only**: tools are annotated read-only and open-world automatically.
- Do not add `from __future__ import annotations` to `tools.py`; the schema is built from the
  annotations at runtime.

## HTTP and errors

Never import `httpx` or `requests`. Use the `http` handle:

```python
data = await http.get_json(url, params)  # parsed JSON
data = await http.post_json(url, {"q": "x"})  # JSON body, parsed JSON reply
text = await http.get_text(url, params)  # raw text, e.g. XML
```

It sets the `User-Agent`, applies timeouts and your `rate_limit_per_minute`, retries transient GET
failures (429, 502, 503 and 504) within a bounded budget, and leaves POST single-attempt. It also
provides offline record/replay (below) and turns every upstream failure (HTTP 4xx/5xx, timeout,
connection error, invalid JSON) into `UpstreamError`, which reaches the agent as a tool result
with `isError` and a readable message. You normally do nothing.

Raise these from `keyless_mcp.core` yourself:

- `InvalidInput("...")` for bad arguments. Say how to fix it ("max_results must be between 1
  and 25"). Check inputs before making a request.
- `UpstreamError("...", status=...)` when the API answers 200 with an unusable body (for
  example unparseable XML).

To give a friendlier message for one status, catch it: `except UpstreamError as exc: if
exc.status == 404: raise InvalidInput(...) from None; raise`.

Any other exception is treated as a bug and the agent only sees a generic failure.

## Minimal example

`adapters/catfacts/adapter.yaml`:

```yaml
name: catfacts
title: Cat Facts
description: Random facts about cats.
toolset: science
base_url: https://catfact.ninja
docs_url: https://catfact.ninja/#/Facts
rate_limit_per_minute: 30
author: your-github-handle
```

`adapters/catfacts/tools.py`:

```python
from typing import Annotated, Any

from pydantic import Field

from keyless_mcp.core import AdapterHttp, InvalidInput, ToolRegistry, truncate

BASE_URL = "https://catfact.ninja"


def register(tools: ToolRegistry, http: AdapterHttp) -> None:
    @tools.tool(title="Random cat facts")
    async def catfacts_random(
        count: Annotated[
            int, Field(description="How many facts to return, 1 to 5. Default 1.")
        ] = 1,
    ) -> dict[str, Any]:
        """Return random facts about cats, each with its length in characters."""
        if not 1 <= count <= 5:
            raise InvalidInput("count must be between 1 and 5.")
        facts = []
        for _ in range(count):
            data = await http.get_json(f"{BASE_URL}/fact")
            facts.append({"fact": truncate(data["fact"], 500), "length": data["length"]})
        return {"returned": len(facts), "facts": facts}
```

## Cassettes: recording and replaying HTTP

Tests never touch the network. The shared client has three modes, set by
`KEYLESS_MCP_HTTP_MODE`, with cassettes in `KEYLESS_MCP_CASSETTE_DIR`:

| Mode | Behaviour |
|---|---|
| `live` (default for the server) | Real requests. |
| `record` | Real requests; each request/response is written as a JSON cassette. |
| `replay` (default for tests) | No network. A request with no cassette fails with a message naming the request and how to record it. |

A cassette is one file per request, named `<method>_<host>_<path>_<hash>.json`, keyed by a hash
of the method, URL (query parameters sorted) and body. It holds the request, status, content type
and body. Request headers are never stored, and email addresses anywhere in a response are
replaced with `redacted@example.invalid` when the cassette is written (registries like npm and
PyPI list maintainer contacts). The one exception is the generic `git@` SSH user in a repository URL, which is dropped
(`git@github.com:o/r.git` becomes `ssh://github.com/o/r.git`) because it is not a person. Do not assert on an email. Commit cassettes; keep them small by
choosing queries with short answers.

```sh
make record ADAPTER=catfacts    # re-runs its tests live; swaps in new cassettes only if all pass
git diff m3_tests/adapters/catfacts/cassettes
```

If a test needs a request nobody has recorded, replay fails with `no cassette for GET <url>`
and the command to record it. A test that changes its arguments needs a re-record.

## Tests

`m3_tests/adapters/<name>/test_<name>.py` is run by M3. It must have
`pytestmark = pytest.mark.m3(suite_name="<name>")` and use the `connect` fixture, which starts
the server over stdio against the adapter's cassettes:

```python
import pytest

from m3_tests._support.results import result_text

pytestmark = pytest.mark.m3(suite_name="catfacts")


def test_random_returns_the_requested_number_of_facts(connect) -> None:
    """catfacts_random(count=2) returns two facts with their lengths."""
    with connect("catfacts") as client:
        result = client.call_tool("catfacts_random", {"count": 2})
    assert result.is_error is False, result_text(result)
    facts = result.structured_content["facts"]
    assert len(facts) == 2
    assert all(f["length"] == len(f["fact"]) for f in facts)


def test_random_rejects_a_bad_count(connect) -> None:
    with connect("catfacts") as client:
        result = client.call_tool("catfacts_random", {"count": 99})
    assert result.is_error is True
    assert "between 1 and 5" in result_text(result)


@pytest.mark.live
def test_live_smoke(connect) -> None:
    """Hits the real API; excluded from `make test`, run with `make test-live`."""
    with connect("catfacts", mode="live") as client:
        assert client.call_tool("catfacts_random", {}).is_error is False
```

Write at least:

1. A catalog test: the tools exist and their required inputs are right.
2. A happy-path test per tool that asserts on real content, with expected values taken from the
   API's documentation or the specification, not copied from whatever the server returned.
3. An error-path test asserting `is_error is True` for invalid input, and one for an upstream
   error (for example an unknown id) if the API has one.
4. A `@pytest.mark.live` smoke test.

`connect` validates tool input schemas by default; pass `validate_schemas=False` to send
arguments the schema would reject. Markers: `live` hits the real network and `agent` needs an
agent harness; neither runs in `make test`.

## Frozen in replay, shape in live

`make test` replays cassettes. `make record ADAPTER=<name>` runs the same tests against the live
API, swaps in the new cassettes if they pass, then replays them once to check. Live data moves: a
front page, a latest version, a release count. A test that pins such a value to a literal passes
against the old cassette and fails against the fresh one.

The rule: pin only data that cannot change upstream (a 2007 item, a country's ISO code, the
metadata of one released version). Otherwise read the expected value from the cassette. The
`replaying` fixture says which mode you are in, and `recorded()` returns what the cassette holds,
loaded the way replay loads it:

```python
from m3_tests._support.cassettes import recorded

API = "https://hacker-news.firebaseio.com/v0"


def test_top_stories(connect, replaying) -> None:
    with connect("hackernews") as client:
        result = client.call_tool("hackernews_top_stories", {"limit": 3})
    stories = result.structured_content["stories"]
    assert [s["rank"] for s in stories] == [1, 2, 3]  # holds for any data
    if replaying:  # live data differs, so compare with the cassette, never a copied literal
        assert [s["id"] for s in stories] == recorded("hackernews", f"{API}/topstories.json")[:3]
        for story in stories:
            item = recorded("hackernews", f"{API}/item/{story['id']}.json")
            assert story["score"] == item["score"]
```

Always assert the shape and the invariants that hold for any data, in every mode. If the replay
check at the end of `make record` fails, a test pins a moved value: change it to read from the
cassette, or restore the old cassettes with `git checkout`.

## Checklist

- [ ] `adapter.yaml` complete; `name` equals the directory
- [ ] Tool names are `<adapter>_<verb>`; every tool and parameter has a description
- [ ] No `httpx`/`requests` import; errors use `InvalidInput` / `UpstreamError`
- [ ] Tests: catalog, happy path, error path, live smoke; cassettes recorded and committed
- [ ] `make record ADAPTER=<name>` passes, replay check included (values that move upstream are read from the cassette)
- [ ] `make test` and `make lint` pass; `make tools` lists your tools
