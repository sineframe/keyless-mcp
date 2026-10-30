"""Both transports serve the same tools: stdio (via M3's StdioServer) and Streamable HTTP."""

from __future__ import annotations

import json
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Iterator

import pytest
from m3 import HTTPServer, TrustLevel

from keyless_mcp.core import discover_adapters
from m3_tests._support.servers import PROJECT_ROOT, cassette_dir

pytestmark = pytest.mark.m3(suite_name="core")


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@pytest.fixture
def http_server_url(request) -> Iterator[str]:
    """Run ``keyless-mcp --transport http`` on a free port and yield its MCP endpoint URL."""
    port = free_port()
    arguments = [sys.executable, "-m", "keyless_mcp", "--transport", "http", "--port", str(port)]
    if getattr(request, "param", None) is not None:
        arguments += ["--toolsets", request.param]
    process = subprocess.Popen(
        arguments,
        cwd=PROJECT_ROOT,
        env={
            "PATH": "/usr/bin:/bin",
            "KEYLESS_MCP_HTTP_MODE": "replay",
            "KEYLESS_MCP_CASSETTE_DIR": str(cassette_dir("osv")),
        },
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=1):
                    break
            except OSError:
                if process.poll() is not None:
                    pytest.fail(f"HTTP server exited during startup: {process.returncode}")
                time.sleep(0.2)
        else:
            pytest.fail("HTTP server did not start within 30s")
        yield f"http://127.0.0.1:{port}/mcp"
    finally:
        process.terminate()
        process.wait(timeout=10)


def test_streamable_http_serves_the_tools_and_answers_calls(m3_kit, http_server_url) -> None:
    """The same tools are listed and callable over Streamable HTTP, using osv's cassettes."""
    server = HTTPServer(name="keyless-http", url=http_server_url, trust=TrustLevel.TRUSTED_PRIVATE)
    with m3_kit.direct(server, validate_schemas=True) as client:
        names = {t.name for t in client.list_all_tools()}
        result = client.call_tool("osv_get_vulnerability", {"vuln_id": "GHSA-35jh-r3h4-6jhm"})
    assert {"arxiv_search", "arxiv_get_paper"} <= names
    assert {"osv_query_package", "osv_get_vulnerability"} <= names
    assert result.is_error is False
    assert "CVE-2021-23337" in result.structured_content["aliases"]


@pytest.mark.parametrize(
    "http_server_url,expected_toolsets",
    [(None, None), ("dev", "dev"), ("fun", "fun")],
    indirect=["http_server_url"],
)
def test_health_reports_the_tools_actually_served(m3_kit, http_server_url, expected_toolsets):
    from keyless_mcp import __version__

    with urllib.request.urlopen(http_server_url.removesuffix("/mcp") + "/health") as response:
        assert response.status == 200
        assert response.headers.get_content_type() == "application/json"
        health = json.load(response)
    server = HTTPServer(
        name="health-catalog", url=http_server_url, trust=TrustLevel.TRUSTED_PRIVATE
    )
    with m3_kit.direct(server) as client:
        tools = client.list_all_tools()
    expected = sorted(
        {
            spec.toolset
            for spec in discover_adapters()
            if expected_toolsets is None or spec.toolset == expected_toolsets
        }
    )
    assert health == {
        "status": "ok",
        "version": __version__,
        "toolsets": expected,
        "tools": len(tools),
    }
