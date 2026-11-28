"""deps.dev adapter: real MCP catalog, bounded responses and offline error paths."""

from __future__ import annotations

import pytest

from m3_tests._support.results import result_text

pytestmark = pytest.mark.m3(suite_name="deps_dev")


def test_lists_the_deps_dev_tools_with_documented_inputs(connect) -> None:
    """All three tools expose registry/package inputs and versions where required."""
    with connect("deps_dev") as client:
        tools = {t.name: t for t in client.list_all_tools() if t.name.startswith("deps_dev_")}
    assert set(tools) == {
        "deps_dev_get_version",
        "deps_dev_get_package",
        "deps_dev_get_dependencies",
    }
    assert list(tools["deps_dev_get_package"].input_schema["required"]) == ["system", "name"]
    for name in ("deps_dev_get_version", "deps_dev_get_dependencies"):
        assert list(tools[name].input_schema["required"]) == ["system", "name", "version"]


def test_get_version_returns_react_metadata_and_attribution(connect) -> None:
    """The API example React 18.2.0 is MIT-licensed (facebook/react v18.2.0 LICENSE)."""
    with connect("deps_dev") as client:
        result = client.call_tool(
            "deps_dev_get_version", {"system": "nPm", "name": "react", "version": "18.2.0"}
        )
    assert result.is_error is False, result_text(result)
    data = result.structured_content
    assert dict(data["version_key"]) == {"system": "NPM", "name": "react", "version": "18.2.0"}
    assert "MIT" in data["licenses"]
    assert data["published_at"].endswith("Z")
    assert isinstance(data["is_deprecated"], bool)
    assert len(data["links"]) <= 20
    assert "deps.dev" in data["source"]
    assert data["source_url"].endswith("/systems/NPM/packages/react/versions/18.2.0")


def test_scoped_name_is_encoded_as_one_path_parameter(connect) -> None:
    """@types/node uses the API's documented percent-encoding for @ and slash."""
    with connect("deps_dev") as client:
        result = client.call_tool(
            "deps_dev_get_version", {"system": "npm", "name": "@types/node", "version": "18.0.0"}
        )
    assert result.is_error is False, result_text(result)
    data = result.structured_content
    assert data["version_key"]["name"] == "@types/node"
    assert "/packages/%40types%2Fnode/versions/18.0.0" in data["source_url"]


def test_get_package_caps_and_sorts_recent_versions(connect, replaying) -> None:
    """Return two newest publications; latest/default metadata is compared to the cassette."""
    from m3_tests._support.cassettes import recorded

    with connect("deps_dev") as client:
        result = client.call_tool(
            "deps_dev_get_package", {"system": "npm", "name": "is-odd", "max_versions": 2}
        )
    assert result.is_error is False, result_text(result)
    data = result.structured_content
    assert data["package_key"]["name"] == "is-odd"
    assert data["returned"] == len(data["versions"]) == 2
    assert data["total"] > 2
    assert data["truncated"] is True
    assert data["default_version"]["name"] == "is-odd"
    if replaying:
        doc = recorded("deps_dev", "https://api.deps.dev/v3/systems/NPM/packages/is-odd")
        expected = sorted(doc["versions"], key=lambda v: v.get("publishedAt") or "", reverse=True)
        assert [dict(v["version_key"]) for v in data["versions"]] == [
            v["versionKey"] for v in expected[:2]
        ]
        assert data["total"] == len(expected)
        assert dict(data["default_version"]) == next(
            v["versionKey"] for v in expected if v["isDefault"]
        )


@pytest.mark.parametrize("max_nodes", [1, 50])
def test_dependencies_preserve_relations_and_report_truncation(connect, max_nodes) -> None:
    """The documented React graph keeps root-first node indexes and only in-range edges."""
    with connect("deps_dev") as client:
        result = client.call_tool(
            "deps_dev_get_dependencies",
            {"system": "NPM", "name": "react", "version": "18.2.0", "max_nodes": max_nodes},
        )
    assert result.is_error is False, result_text(result)
    data = result.structured_content
    assert data["nodes"][0]["relation"] == "SELF"
    assert data["nodes"][0]["version_key"]["name"] == "react"
    assert data["nodes_total"] >= 2
    assert data["nodes_returned"] == len(data["nodes"]) == min(max_nodes, data["nodes_total"])
    assert all(n["relation"] in {"SELF", "DIRECT", "INDIRECT"} for n in data["nodes"])
    assert all(
        0 <= e["from_node"] < len(data["nodes"]) and 0 <= e["to_node"] < len(data["nodes"])
        for e in data["edges"]
    )
    assert data["truncated"] is (max_nodes == 1)
    assert data["resolution_errors"] is False
    assert data["source_url"].endswith("/18.2.0:dependencies")
    assert data["data_license"] == "CC-BY-4.0"
    assert data["data_license_url"] == "https://creativecommons.org/licenses/by/4.0/"


def test_unknown_package_preserves_the_provider_404_message(connect) -> None:
    """The required error-path URL returns HTTP 404 with the text package not found."""
    with connect("deps_dev") as client:
        result = client.call_tool(
            "deps_dev_get_package", {"system": "npm", "name": "zzznotreal-pkg-1234"}
        )
    assert result.is_error is True
    assert "HTTP 404" in result_text(result)
    assert "package not found" in result_text(result)


@pytest.mark.parametrize(
    ("tool", "args", "message"),
    [
        (
            "deps_dev_get_version",
            {"system": "unknown", "name": "react", "version": "18.2.0"},
            "system must be",
        ),
        ("deps_dev_get_package", {"system": "npm", "name": " "}, "name must be"),
        ("deps_dev_get_package", {"system": "npm", "name": "../etc/passwd"}, "name must be"),
        ("deps_dev_get_package", {"system": "npm", "name": "react?x=1"}, "name must be"),
        (
            "deps_dev_get_version",
            {"system": "npm", "name": "react", "version": "1/../2"},
            "version must be",
        ),
        (
            "deps_dev_get_version",
            {"system": "npm", "name": "react", "version": ".."},
            "version must be",
        ),
        (
            "deps_dev_get_package",
            {"system": "npm", "name": "react", "max_versions": 0},
            "max_versions must be",
        ),
        (
            "deps_dev_get_dependencies",
            {"system": "npm", "name": "react", "version": "18.2.0", "max_nodes": 101},
            "max_nodes must be",
        ),
        (
            "deps_dev_get_dependencies",
            {"system": "go", "name": "github.com/google/uuid", "version": "v1.3.0"},
            "metadata",
        ),
    ],
)
def test_invalid_arguments_are_rejected_before_a_request(connect, tool, args, message) -> None:
    """Invalid registry, path segments, limits and unsupported graphs need no cassette."""
    with connect("deps_dev") as client:
        result = client.call_tool(tool, args)
    assert result.is_error is True
    assert message in result_text(result)
    assert "no cassette" not in result_text(result)


def _synthetic_response(tmp_path, url, body):
    from keyless_mcp.core import cassette

    cassette.save(
        tmp_path, "GET", url, None, cassette.RecordedResponse(200, "application/json", body)
    )


def test_package_sorts_fractional_timestamps_and_keeps_an_older_default(connect, tmp_path) -> None:
    """RFC3339 fractions sort by time, missing dates last, default outside the cap survives."""
    key = {"system": "NPM", "name": "example"}
    doc = {
        "packageKey": key,
        "versions": [
            {
                "versionKey": {**key, "version": "1.0.0"},
                "publishedAt": "2026-01-01T00:00:00Z",
                "isDefault": True,
            },
            {"versionKey": {**key, "version": "1.1.0"}, "publishedAt": "2026-01-01T00:00:00.001Z"},
            {"versionKey": {**key, "version": "0.1.0"}},
        ],
    }
    _synthetic_response(tmp_path, "https://api.deps.dev/v3/systems/NPM/packages/example", doc)
    with connect("deps_dev", mode="replay", cassettes=tmp_path) as client:
        result = client.call_tool(
            "deps_dev_get_package", {"system": "npm", "name": "example", "max_versions": 1}
        )
    assert result.is_error is False, result_text(result)
    data = result.structured_content
    assert data["versions"][0]["version_key"]["version"] == "1.1.0"
    assert data["default_version"]["version"] == "1.0.0"
    assert data["total"] == 3 and data["truncated"] is True


def test_graph_cap_keeps_resolution_errors_and_valid_edges(connect, tmp_path) -> None:
    """Errors on visible and omitted nodes remain visible even in a capped graph."""
    nodes = [
        {
            "versionKey": {"system": "NPM", "name": f"node{i}", "version": "1.0.0"},
            "relation": "SELF" if i == 0 else "DIRECT",
        }
        for i in range(4)
    ]
    nodes[1]["errors"] = ["unresolved requirement"] * 25
    nodes[3]["errors"] = ["another resolution failure"]
    doc = {
        "nodes": nodes,
        "edges": [{"fromNode": 0, "toNode": i, "requirement": "^1"} for i in range(1, 4)],
        "error": "partial graph",
    }
    _synthetic_response(
        tmp_path,
        "https://api.deps.dev/v3/systems/NPM/packages/example/versions/1.0.0:dependencies",
        doc,
    )
    with connect("deps_dev", mode="replay", cassettes=tmp_path) as client:
        result = client.call_tool(
            "deps_dev_get_dependencies",
            {"system": "npm", "name": "example", "version": "1.0.0", "max_nodes": 2},
        )
    assert result.is_error is False, result_text(result)
    data = result.structured_content
    assert data["nodes_total"] == 4 and data["nodes_returned"] == 2
    assert data["edges_total"] == 3 and data["edges_returned"] == 1
    assert data["nodes"][1]["errors"] == ("unresolved requirement",) * 20
    assert data["nodes"][1]["errors_omitted"] == 5
    assert data["nodes_with_errors"] == 2
    assert data["resolution_errors"] is True and data["truncated"] is True
    assert data["error"] == "partial graph"


def test_edge_limit_also_marks_a_graph_truncated(connect, tmp_path) -> None:
    """The separate 200-edge cap reports truncation even when every node is returned."""
    key = {"system": "NPM", "name": "example", "version": "1.0.0"}
    doc = {
        "nodes": [{"versionKey": key, "relation": "SELF"}],
        "edges": [{"fromNode": 0, "toNode": 0, "requirement": str(i)} for i in range(201)],
    }
    _synthetic_response(
        tmp_path,
        "https://api.deps.dev/v3/systems/NPM/packages/example/versions/1.0.0:dependencies",
        doc,
    )
    with connect("deps_dev", mode="replay", cassettes=tmp_path) as client:
        result = client.call_tool(
            "deps_dev_get_dependencies", {"system": "npm", "name": "example", "version": "1.0.0"}
        )
    assert result.is_error is False, result_text(result)
    data = result.structured_content
    assert data["nodes_total"] == data["nodes_returned"] == 1
    assert data["edges_total"] == 201 and data["edges_returned"] == 200
    assert data["truncated"] is True


@pytest.mark.parametrize(
    ("tool", "suffix", "extra", "message"),
    [
        ("deps_dev_get_version", "/versions/1.0.0", {"version": "1.0.0"}, "invalid version"),
        ("deps_dev_get_package", "", {}, "invalid package"),
        (
            "deps_dev_get_dependencies",
            "/versions/1.0.0:dependencies",
            {"version": "1.0.0"},
            "invalid dependency graph",
        ),
    ],
)
def test_unusable_success_responses_are_upstream_errors(
    connect, tmp_path, tool, suffix, extra, message
) -> None:
    """A 200 without the documented object structure is an actionable tool error."""
    _synthetic_response(
        tmp_path,
        "https://api.deps.dev/v3/systems/NPM/packages/example" + suffix,
        {"unexpected": "shape"},
    )
    with connect("deps_dev", mode="replay", cassettes=tmp_path) as client:
        result = client.call_tool(tool, {"system": "npm", "name": "example", **extra})
    assert result.is_error is True
    assert message in result_text(result)


@pytest.mark.live
def test_live_get_version_uses_the_public_api(connect) -> None:
    """Live smoke: the documented example React version is available without credentials."""
    with connect("deps_dev", mode="live") as client:
        result = client.call_tool(
            "deps_dev_get_version", {"system": "npm", "name": "react", "version": "18.2.0"}
        )
    assert result.is_error is False, result_text(result)
    assert result.structured_content["version_key"]["version"] == "18.2.0"


@pytest.mark.parametrize(
    "tool,field,extra",
    [
        ("deps_dev_get_package", "max_versions", {}),
        ("deps_dev_get_dependencies", "max_nodes", {"version": "18.2.0"}),
    ],
)
@pytest.mark.parametrize("value", [True, 1.5, "2"])
def test_limits_reject_non_integer_json_values(connect, tool, field, extra, value) -> None:
    """Strict integer limits reject booleans, floats and strings before slicing or HTTP."""
    with connect("deps_dev", validate_schemas=False) as client:
        result = client.call_tool(tool, {"system": "npm", "name": "react", field: value, **extra})
    assert result.is_error is True
    assert "valid integer" in result_text(result)
    assert "no cassette" not in result_text(result)


def test_version_list_caps_report_omissions(connect, tmp_path) -> None:
    """Each large metadata list is bounded and reports the entries not returned."""
    doc = {
        "versionKey": {"system": "NPM", "name": "example", "version": "1.0.0"},
        "licenses": ["MIT"] * 25,
        "advisoryKeys": [{"id": "GHSA-example"}] * 25,
        "links": [{"label": "source", "url": "https://example.com"}] * 25,
        "relatedProjects": [{"projectKey": {"id": "github.com/example/project"}}] * 25,
    }
    _synthetic_response(
        tmp_path, "https://api.deps.dev/v3/systems/NPM/packages/example/versions/1.0.0", doc
    )
    with connect("deps_dev", mode="replay", cassettes=tmp_path) as client:
        result = client.call_tool(
            "deps_dev_get_version", {"system": "npm", "name": "example", "version": "1.0.0"}
        )
    assert result.is_error is False, result_text(result)
    for field in ["licenses", "advisory_ids", "links", "related_projects"]:
        assert len(result.structured_content[field]) == 20
        assert result.structured_content[field + "_omitted"] == 5


def test_invalid_publication_timestamp_is_a_tool_error(connect, tmp_path) -> None:
    """Malformed provider timestamps fail clearly instead of silently misordering versions."""
    key = {"system": "NPM", "name": "example"}
    doc = {
        "packageKey": key,
        "versions": [{"versionKey": {**key, "version": "1.0.0"}, "publishedAt": "not-a-date"}],
    }
    _synthetic_response(tmp_path, "https://api.deps.dev/v3/systems/NPM/packages/example", doc)
    with connect("deps_dev", mode="replay", cassettes=tmp_path) as client:
        result = client.call_tool("deps_dev_get_package", {"system": "npm", "name": "example"})
    assert result.is_error is True
    assert "invalid publication timestamp" in result_text(result)
