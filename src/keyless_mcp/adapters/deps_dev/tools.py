"""Bounded package metadata and dependency graphs from Google's deps.dev v3 API."""

import re
from datetime import datetime
from typing import Annotated, Any
from urllib.parse import quote

from pydantic import Field

from keyless_mcp.core import AdapterHttp, InvalidInput, ToolRegistry, UpstreamError, truncate

BASE_URL = "https://api.deps.dev/v3"
SYSTEMS = {"NPM", "PYPI", "GO", "MAVEN", "CARGO", "NUGET", "RUBYGEMS"}
GRAPH_SYSTEMS = {"NPM", "PYPI", "MAVEN", "CARGO"}
MAX_ITEMS = 20
MAX_NODES = 100
MAX_EDGES = 200
SOURCE = {
    "source": "deps.dev (Google Open Source Insights)",
    "data_terms_url": "https://docs.deps.dev/api/v3/#data",
}
System = Annotated[
    str,
    Field(
        description="Registry: npm, pypi, go, maven, cargo, nuget or rubygems; "
        "case-insensitive, e.g. 'npm'."
    ),
]
Name = Annotated[
    str,
    Field(
        description="Package name, at most 512 characters, e.g. 'react', '@types/node' "
        "or 'org.slf4j:slf4j-api'. Pass the name unencoded."
    ),
]
Version = Annotated[
    str,
    Field(
        description="Exact published version, at most 256 characters, e.g. '18.2.0' "
        "or 'v1.3.0'; not a path or version range."
    ),
]


def _system(system: str) -> str:
    value = system.strip().upper()
    if value not in SYSTEMS:
        raise InvalidInput(f"system must be one of {', '.join(sorted(SYSTEMS))}; e.g. 'npm'.")
    return value


def _package_url(system: str, name: str) -> str:
    clean = name.strip()
    if (
        not clean
        or len(clean) > 512
        or any(c.isspace() or not c.isprintable() for c in clean)
        or any(part in {"", ".", ".."} for part in clean.split("/"))
        or any(c in clean for c in "\\?#%")
    ):
        raise InvalidInput(
            "name must be a nonempty package name without whitespace or path traversal, "
            "at most 512 characters; e.g. '@types/node'."
        )
    return f"{BASE_URL}/systems/{_system(system)}/packages/{quote(clean, safe='')}"


def _version_url(system: str, name: str, version: str) -> str:
    value = version.strip()
    if (
        len(value) > 256
        or value in {".", ".."}
        or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._+!~:-]*", value)
    ):
        raise InvalidInput(
            "version must be an exact version without paths or whitespace, "
            "at most 256 characters; e.g. '18.2.0'."
        )
    return f"{_package_url(system, name)}/versions/{quote(value, safe='')}"


def _version_summary(data: Any) -> dict[str, Any]:
    if not isinstance(data, dict) or not isinstance(data.get("versionKey"), dict):
        raise UpstreamError("deps.dev returned an invalid version: missing versionKey.")
    return {
        "version_key": data["versionKey"],
        "published_at": data.get("publishedAt"),
        "is_default": data.get("isDefault", False),
        "is_deprecated": data.get("isDeprecated", False),
        "deprecated_reason": truncate(data.get("deprecatedReason"), 300),
    }


def _published_time(value: str | None) -> float:
    if not value:
        return float("-inf")
    try:
        date = datetime.fromisoformat(value)
        if date.tzinfo is not None:
            return date.timestamp()
    except (ValueError, TypeError):
        pass
    raise UpstreamError("deps.dev returned an invalid publication timestamp.")


def register(tools: ToolRegistry, http: AdapterHttp) -> None:
    @tools.tool(title="Get deps.dev package version")
    async def deps_dev_get_version(system: System, name: Name, version: Version) -> dict[str, Any]:
        """Get a published package version's date, package licenses, deprecation, advisory
        IDs and source links from deps.dev. Supports seven registries. Lists are capped at
        20 entries with omitted counts; package licenses describe the package, not API data."""
        url = _version_url(system, name, version)
        data = await http.get_json(url)
        result = _version_summary(data)
        result.update(SOURCE)
        result["source_url"] = url
        for source_key, output_key in [
            ("licenses", "licenses"),
            ("advisoryKeys", "advisory_ids"),
            ("links", "links"),
            ("relatedProjects", "related_projects"),
        ]:
            values = data.get(source_key) or []
            selected = values[:MAX_ITEMS]
            if source_key == "advisoryKeys":
                selected = [entry["id"] for entry in selected]
            result[output_key] = selected
            result[f"{output_key}_omitted"] = max(0, len(values) - len(selected))
        return result

    @tools.tool(title="Get deps.dev package versions")
    async def deps_dev_get_package(
        system: System,
        name: Name,
        max_versions: Annotated[
            int,
            Field(
                strict=True,
                description="Most recently published versions to return, 1 to 20; "
                "e.g. 5. Default 5.",
            ),
        ] = 5,
    ) -> dict[str, Any]:
        """List recent versions of a package across seven registries, newest publication
        first. Marks default versions and returns the default separately even if outside
        the selected recent versions. Missing publication dates sort last; counts and
        truncated describe the capped version list."""
        if not 1 <= max_versions <= MAX_ITEMS:
            raise InvalidInput("max_versions must be between 1 and 20.")
        url = _package_url(system, name)
        data = await http.get_json(url)
        if (
            not isinstance(data, dict)
            or not isinstance(data.get("packageKey"), dict)
            or not isinstance(data.get("versions"), list)
        ):
            raise UpstreamError(
                "deps.dev returned an invalid package: expected packageKey and versions."
            )
        versions = [_version_summary(v) for v in data["versions"]]
        versions.sort(key=lambda v: _published_time(v["published_at"]), reverse=True)
        return {
            **SOURCE,
            "source_url": url,
            "package_key": data["packageKey"],
            "total": len(versions),
            "returned": min(len(versions), max_versions),
            "truncated": len(versions) > max_versions,
            "default_version": next((v["version_key"] for v in versions if v["is_default"]), None),
            "versions": versions[:max_versions],
        }

    @tools.tool(title="Get deps.dev resolved dependencies")
    async def deps_dev_get_dependencies(
        system: System,
        name: Name,
        version: Version,
        max_nodes: Annotated[
            int,
            Field(
                strict=True,
                description="Graph nodes including the root to return, 1 to 100; e.g. 50. "
                "Default 50. At most 200 edges are returned.",
            ),
        ] = 50,
    ) -> dict[str, Any]:
        """Get a resolved dependency graph for npm, PyPI, Maven or Cargo (other registries
        currently have metadata only). Nodes retain version keys, SELF/DIRECT/INDIRECT
        relations and resolution errors. Edges refer to returned node indexes. Counts and
        truncated flag omitted nodes/edges; resolution_errors warns of provider-reported
        incomplete resolution even when the response was not capped."""
        if not 1 <= max_nodes <= MAX_NODES:
            raise InvalidInput("max_nodes must be between 1 and 100.")
        system = _system(system)
        if system not in GRAPH_SYSTEMS:
            raise InvalidInput(
                "Resolved dependencies are available for NPM, PYPI, MAVEN and CARGO only. "
                "Use deps_dev_get_version or deps_dev_get_package for metadata "
                "from other registries."
            )
        url = _version_url(system, name, version) + ":dependencies"
        data = await http.get_json(url)
        if (
            not isinstance(data, dict)
            or not isinstance(data.get("nodes"), list)
            or not isinstance(data.get("edges", []), list)
        ):
            raise UpstreamError(
                "deps.dev returned an invalid dependency graph: expected nodes and edges."
            )
        nodes = data["nodes"]
        returned = []
        for node in nodes[:max_nodes]:
            key = _version_summary(node)["version_key"]
            errors = node.get("errors") or []
            returned.append(
                {
                    "version_key": key,
                    "relation": node.get("relation"),
                    "bundled": node.get("bundled", False),
                    "errors": [truncate(e, 500) for e in errors[:MAX_ITEMS]],
                    "errors_omitted": max(0, len(errors) - MAX_ITEMS),
                }
            )
        edges = data.get("edges", [])
        selected_edges = []
        for edge in edges:
            start, end = edge.get("fromNode", 0), edge.get("toNode", 0)
            if (
                not isinstance(start, int)
                or not isinstance(end, int)
                or not 0 <= start < len(nodes)
                or not 0 <= end < len(nodes)
            ):
                raise UpstreamError("deps.dev returned an invalid dependency edge index.")
            if start < len(returned) and end < len(returned) and len(selected_edges) < MAX_EDGES:
                selected_edges.append(
                    {
                        "from_node": start,
                        "to_node": end,
                        "requirement": truncate(edge.get("requirement"), 200),
                    }
                )
        return {
            **SOURCE,
            "source_url": url,
            "data_license": "CC-BY-4.0",
            "data_license_url": "https://creativecommons.org/licenses/by/4.0/",
            "nodes": returned,
            "nodes_total": len(nodes),
            "nodes_returned": len(returned),
            "edges": selected_edges,
            "edges_total": len(edges),
            "edges_returned": len(selected_edges),
            "truncated": len(nodes) > len(returned) or len(edges) > len(selected_edges),
            "resolution_errors": bool(data.get("error")) or any(n.get("errors") for n in nodes),
            "nodes_with_errors": sum(bool(n.get("errors")) for n in nodes),
            "error": truncate(data.get("error"), 1000),
        }
