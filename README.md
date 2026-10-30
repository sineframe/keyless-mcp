# keyless-mcp

<!-- mcp-name: io.github.sineframe/keyless-mcp -->

One MCP server that gives your agent tools over free public APIs such as arXiv, Wikipedia, PyPI, npm, OSV, Open-Meteo, the World Bank and Hacker News. It needs no API keys and no accounts.

[![CI](https://github.com/sineframe/keyless-mcp/actions/workflows/ci.yml/badge.svg)](https://github.com/sineframe/keyless-mcp/actions/workflows/ci.yml)
[![Python](https://img.shields.io/python/required-version-toml?tomlFilePath=https%3A%2F%2Fraw.githubusercontent.com%2Fsineframe%2Fkeyless-mcp%2Fmain%2Fpyproject.toml)](https://github.com/sineframe/keyless-mcp/blob/main/pyproject.toml)
[![License: Apache-2.0](https://img.shields.io/badge/license-Apache--2.0-blue)](https://github.com/sineframe/keyless-mcp/blob/main/LICENSE)
[![Tested with M3](https://img.shields.io/badge/tested%20with-M3-6f42c1)](https://github.com/sineframe/m3)
[![Hacktoberfest](https://img.shields.io/badge/hacktoberfest-friendly-ff7518)](https://github.com/sineframe/keyless-mcp/issues?q=is%3Aissue+is%3Aopen+label%3Ahacktoberfest)

## What it is

Most MCP servers need a token before they do anything. Plenty of useful data sits behind public APIs that need none, and keyless-mcp wraps those in one server so you add it once and your agent can look things up right away.

The tools are grouped into toolsets, so you can switch groups on or off. `make tools` from a clone, or [ADAPTERS.md](https://github.com/sineframe/keyless-mcp/blob/main/ADAPTERS.md), lists every adapter and tool. These are the adapters so far:

- science: `arxiv`, `wikipedia`
- dev: `npm`, `osv`, `pypi`
- geo: `open_meteo`, `world_bank`
- news: `hackernews`

Every tool is read-only and returns a small structured result. Upstream failures (a 404, a timeout, bad JSON) come back as ordinary tool errors that the agent can read. The server calls only the APIs your agent asks about, and it has no telemetry and writes nothing to disk.

Here is what it looks like in use. The tool result comes from a real call on 2026-10-11, and the agent's reply is condensed:

```text
You:    Are there known security vulnerabilities in version 2.4.1 of the PyPI package jinja2?

Agent:  [calls osv_query_package with ecosystem="PyPI", name="jinja2", version="2.4.1"]

Agent:  Yes. OSV lists 18 advisories for jinja2 2.4.1. One is GHSA-462w-v97r-4m45 (CVE-2019-10906),
        a sandbox escape through string formatting, rated high and fixed in 2.10.1. Another is
        GHSA-8r7q-cvjq-x353, an incorrect privilege assignment fixed in 2.7.2. Upgrading to
        2.10.1 or later covers both.
```

## Quick start

You need [uv](https://docs.astral.sh/uv/), which runs Python tools without a manual install.

```sh
# macOS and Linux
curl -LsSf https://astral.sh/uv/install.sh | sh

# Windows (PowerShell)
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

keyless-mcp is not on PyPI yet, so for now every client below starts it straight from GitHub. The first start downloads and builds the package, which takes a few seconds, and later starts reuse the cache. Check that it works first:

```sh
uvx --from git+https://github.com/sineframe/keyless-mcp keyless-mcp --list-tools
```

That prints a table of every tool with its toolset and a one-line description. Working from a clone of the repository instead? Use `uv run --directory /path/to/keyless-mcp keyless-mcp` in place of the `uvx --from ...` part.

### Claude Code

```sh
claude mcp add keyless -- uvx --from git+https://github.com/sineframe/keyless-mcp keyless-mcp
```

The `--` matters. Everything after it is the server command, so flags such as `--toolsets` reach keyless-mcp and not `claude`. Add `--scope user` before the name to have it in every project, or `--scope project` to write it to a `.mcp.json` your team can commit. Run `claude mcp list` to check it, or type `/mcp` inside Claude Code.

### Claude Desktop

Open Settings, then Developer, then Edit Config. That opens `claude_desktop_config.json`, which lives at `~/Library/Application Support/Claude/claude_desktop_config.json` on macOS and `%APPDATA%\Claude\claude_desktop_config.json` on Windows. Add the server:

```json
{
  "mcpServers": {
    "keyless": {
      "command": "uvx",
      "args": ["--from", "git+https://github.com/sineframe/keyless-mcp", "keyless-mcp"]
    }
  }
}
```

Quit Claude Desktop completely and start it again. If it says the server could not start, desktop apps often do not see your shell's PATH. Run `which uvx` (macOS, Linux) or `where uvx` (Windows) and put that full path in `command`.

### Cursor

Put this in `.cursor/mcp.json` for one project, or `~/.cursor/mcp.json` for all of them:

```json
{
  "mcpServers": {
    "keyless": {
      "type": "stdio",
      "command": "uvx",
      "args": ["--from", "git+https://github.com/sineframe/keyless-mcp", "keyless-mcp"]
    }
  }
}
```

### VS Code

Create `.vscode/mcp.json` in your workspace. VS Code uses the key `servers` here, not `mcpServers`:

```json
{
  "servers": {
    "keyless": {
      "type": "stdio",
      "command": "uvx",
      "args": ["--from", "git+https://github.com/sineframe/keyless-mcp", "keyless-mcp"]
    }
  }
}
```

To add it to your user profile instead, run the command palette entry "MCP: Open User Configuration" and paste the same block, or use the command line:

```sh
code --add-mcp '{"name":"keyless","command":"uvx","args":["--from","git+https://github.com/sineframe/keyless-mcp","keyless-mcp"]}'
```

### Codex

```sh
codex mcp add keyless -- uvx --from git+https://github.com/sineframe/keyless-mcp keyless-mcp
```

That writes this to `~/.codex/config.toml`, which you can also edit by hand:

```toml
[mcp_servers.keyless]
command = "uvx"
args = ["--from", "git+https://github.com/sineframe/keyless-mcp", "keyless-mcp"]
```

### After the first release

Once keyless-mcp is on PyPI, drop the `--from git+...` part and the commands get shorter:

```sh
uvx keyless-mcp --list-tools
claude mcp add keyless -- uvx keyless-mcp
codex mcp add keyless -- uvx keyless-mcp
```

In the JSON and TOML files, use `"args": ["keyless-mcp"]` (Cursor, VS Code, Claude Desktop) or `args = ["keyless-mcp"]` (Codex). For VS Code's command line, use `code --add-mcp '{"name":"keyless","command":"uvx","args":["keyless-mcp"]}'`.

### Docker

```sh
docker run -i --rm --no-healthcheck ghcr.io/sineframe/keyless-mcp
```

The image is published to `ghcr.io` when a release is tagged, so this works after the first release. To build it yourself, run `docker build -t keyless-mcp .` and use `keyless-mcp` as the image name. Use the same line as the server command in any client above, for example `claude mcp add keyless -- docker run -i --rm --no-healthcheck ghcr.io/sineframe/keyless-mcp`. The `-i` flag is required because the server talks over stdin and stdout. Disable the image's HTTP health check for stdio, which has no HTTP listener.

### Streamable HTTP

For clients that connect by URL instead of launching a process, start the server with the HTTP transport. From a clone, that is:

```sh
uv run keyless-mcp --transport http --port 8000
```

The endpoint is `http://127.0.0.1:8000/mcp`. It binds to localhost by default. Inside a container, add `--host 0.0.0.0` and publish the port.

`GET /health` returns HTTP 200 with `status`, `version`, the toolsets with registered adapters, and their total `tools` count. It only reads local process metadata; it does not check upstream API availability. The Docker health check probes this endpoint on port 8000 using Python's standard library. If you change the port, override the probe with `docker run --health-cmd`, or disable it with `--no-healthcheck`.

## Choosing toolsets

The server has seven toolsets and offers every tool by default. Fewer tools means less for the agent to weigh, so pick the ones you need with a flag or an environment variable:

```sh
uvx --from git+https://github.com/sineframe/keyless-mcp keyless-mcp --toolsets dev,geo
KEYLESS_MCP_TOOLSETS=dev,geo uvx --from git+https://github.com/sineframe/keyless-mcp keyless-mcp
```

From a clone, use `uv run keyless-mcp --toolsets dev,geo` instead. If both the flag and the variable are set, the flag wins. In a client, add the flag after the server command. For example:

```sh
claude mcp add keyless -- uvx --from git+https://github.com/sineframe/keyless-mcp keyless-mcp --toolsets dev,geo
```

```json
{ "command": "uvx", "args": ["--from", "git+https://github.com/sineframe/keyless-mcp", "keyless-mcp", "--toolsets", "dev,geo"] }
```

| Toolset | What is in it |
|---|---|
| `science` | arXiv paper search and metadata, Wikipedia search and summaries |
| `dev` | npm and PyPI package lookups, OSV vulnerability search |
| `geo` | Open-Meteo forecasts and geocoding, World Bank country data |
| `news` | Hacker News top stories and items |
| `finance`, `reference`, `fun` | No adapters yet. The names are reserved and the [open issues](https://github.com/sineframe/keyless-mcp/labels/good%20first%20issue) add the first ones. |

Until an adapter lands in one of those last three, selecting only that toolset serves no tools. An unknown name stops the server with a message listing the valid ones. Add `--list-tools` to any command to see what would be served.

## Tools

| Adapter | Tools | Upstream API |
|---|---|---|
| arXiv | `arxiv_search`, `arxiv_get_paper` | [arXiv API](https://info.arxiv.org/help/api/user-manual.html) |
| Wikipedia | `wikipedia_search`, `wikipedia_get_summary` | [Wikimedia Core REST API](https://api.wikimedia.org/wiki/Core_REST_API) |
| npm | `npm_get_package`, `npm_search` | [npm registry](https://github.com/npm/registry/blob/main/docs/REGISTRY-API.md) |
| OSV | `osv_query_package`, `osv_get_vulnerability` | [OSV.dev](https://google.github.io/osv.dev/api/) |
| PyPI | `pypi_get_package`, `pypi_get_release` | [PyPI JSON API](https://docs.pypi.org/api/json/) |
| Open-Meteo | `open_meteo_forecast`, `open_meteo_geocode` | [Open-Meteo](https://open-meteo.com/en/docs) |
| World Bank | `world_bank_country_search`, `world_bank_country_by_code` | [World Bank country API](https://datahelpdesk.worldbank.org/knowledgebase/articles/898590-country-api-queries) |
| Hacker News | `hackernews_top_stories`, `hackernews_get_item` | [HN Firebase API](https://github.com/HackerNews/API) |

[ADAPTERS.md](https://github.com/sineframe/keyless-mcp/blob/main/ADAPTERS.md) has the full descriptions and the per-adapter agent pass rates. It is generated from the code, so it stays current.

## How it is tested

Every tool is tested with [M3](https://github.com/sineframe/m3), a testing tool for MCP servers and agents. The tests start the real server over stdio, call each tool through an MCP client, and check the results.

- On every pull request, the whole suite runs offline. The server replays recorded HTTP responses (cassettes), so CI needs no network and no secrets, and a fork's pull request runs the same checks as a maintainer's.
- Benchmark scores must not go down: CI compares each pull request's M3 results with `benchmarks/baseline.json` on main and fails if any score is lower (`make test && make benchmark` checks yours, and [CONTRIBUTING.md](https://github.com/sineframe/keyless-mcp/blob/main/CONTRIBUTING.md) explains it).
- Every night, a live lane calls the real APIs. If an upstream changes shape or goes down, the job opens an `upstream-drift` issue.
- Every night, an agent lane gives Claude Code and Codex plain-English questions that never name a tool, such as "Are there known security vulnerabilities in version 2.4.1 of the PyPI package jinja2?". It checks whether the agent picked the right tool and made a successful call, over 3 trials per prompt. This lane costs model tokens, so it runs only where the maintainers have set credentials.

The latest agent snapshot is Codex (`gpt-6.1-sol`), which picked the right tool on 10 of 10 prompts, with 1 trial each, on 2026-10-11. That is one model on one day. Treat it as a smoke check and not as a stable rate. The raw file is [`docs/results/agent-codex-latest.json`](https://github.com/sineframe/keyless-mcp/blob/main/docs/results/agent-codex-latest.json), and ADAPTERS.md shows the same numbers per adapter.

If you build MCP servers, this setup may be useful to copy. A tool description is only good if an agent picks the tool because of it, and unit tests of your handlers cannot tell you that. Running the server through a real MCP client against recorded traffic catches broken schemas and error handling on every commit. Running agents against it catches descriptions that mislead. [`docs/agent-testing.md`](https://github.com/sineframe/keyless-mcp/blob/main/docs/agent-testing.md) explains how the two lanes work, and the [M3 repository](https://github.com/sineframe/m3) has the tool itself.

## Contributing

New adapters are the most useful contribution, and the repository keeps a backlog of small ones. To run the tests on your machine, you need `git`, `make` and [uv](https://docs.astral.sh/uv/):

```sh
git clone https://github.com/sineframe/keyless-mcp && cd keyless-mcp
make setup
make test
```

`make setup` installs Python 3.12, the dependencies and the M3 tooling into `.venv`. `make test` then runs the whole suite offline in under a minute. Run `make` on its own to list every command.

To add your first adapter in about 15 minutes:

1. Pick an API from the issues labeled [good first issue](https://github.com/sineframe/keyless-mcp/labels/good%20first%20issue) and comment to claim it.
2. Run `make new-adapter NAME=your_api TOOLSET=dev`. It creates the adapter folder and a test file with TODOs.
3. Fill in `adapter.yaml` and `tools.py`, then run `make record ADAPTER=your_api` to capture real responses as cassettes.
4. Run `make test`, then `make adapters-md`, and open a pull request.

[CONTRIBUTING.md](https://github.com/sineframe/keyless-mcp/blob/main/CONTRIBUTING.md) has the details, and [docs/adapter-contract.md](https://github.com/sineframe/keyless-mcp/blob/main/docs/adapter-contract.md) is the reference for what an adapter must contain.

### Hacktoberfest

The issues are labeled `hacktoberfest`. Hacktoberfest 2026 no longer counts pull requests toward rewards, so that label is there to help you find the issues and nothing more. What you get is credit in the places that last: your name on the adapter's row in ADAPTERS.md, your entry in the contributors list below, and a mention in the release notes.

## FAQ

Why are there no API keys?

Each adapter wraps an API that works without one. If a service needs a key, it does not belong here. That keeps setup to one line and means nothing secret ever passes through the server.

What about rate limits?

Every adapter declares its upstream's limit in `adapter.yaml`, and the shared HTTP client spaces requests to stay under it. Some public APIs are strict about anonymous use, and the server identifies itself with a `User-Agent` of the form `keyless-mcp/<version> (+https://github.com/sineframe/keyless-mcp)`. If an upstream rate-limits you anyway, the agent gets a readable error and not a crash.

What does it send, and to whom?

When a tool runs, the server makes a request to that tool's public API with the arguments the agent chose. It makes no other requests, has no analytics or telemetry, and stores nothing.

Can I use it without an MCP client?

Yes. `uvx --from git+https://github.com/sineframe/keyless-mcp keyless-mcp --list-tools` prints the catalog, and the HTTP transport lets any MCP client connect by URL. The tools are plain Python functions in `src/keyless_mcp/adapters/`.

A tool returned an error. Is it a bug?

Often it is the upstream: an unknown id returns a 404, and a busy API returns a 429 or 5xx. The message says which. If the same call keeps failing, [open a bug](https://github.com/sineframe/keyless-mcp/issues/new?template=bug.yml) with the tool name and arguments. The nightly live tests catch most upstream changes too.

## Contributors

No one has contributed yet, so this list is empty. It follows the [all-contributors](https://allcontributors.org) specification. To be added after your first merged pull request, comment `@all-contributors please add @your-handle for code` on it.

<!-- ALL-CONTRIBUTORS-LIST:START -->
<!-- ALL-CONTRIBUTORS-LIST:END -->

## License

Apache-2.0. Copyright 2026 SineFrame. See [LICENSE](https://github.com/sineframe/keyless-mcp/blob/main/LICENSE).
