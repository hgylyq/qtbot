from types import SimpleNamespace

from qqbot.search import MCPSearchClient


def test_mcp_tool_argument_detection_prefers_query() -> None:
    client = MCPSearchClient(url="https://example.test/mcp", authorization="Bearer token")
    tool = SimpleNamespace(inputSchema={"properties": {"query": {}, "max_results": {}}})

    assert client._build_arguments(tool, "hello") == {"query": "hello", "max_results": 5}


def test_mcp_tool_argument_detection_supports_q() -> None:
    client = MCPSearchClient(url="https://example.test/mcp", authorization="Bearer token")
    tool = SimpleNamespace(inputSchema={"properties": {"q": {}}})

    assert client._build_arguments(tool, "hello") == {"q": "hello"}
