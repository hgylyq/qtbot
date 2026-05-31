from __future__ import annotations

import json
import logging
from typing import Any

from .llm import OpenAIChatClient
from .models import RoleCard, SearchBrief

logger = logging.getLogger(__name__)


class MCPSearchClient:
    def __init__(
        self,
        *,
        url: str,
        authorization: str | None,
        tool_name: str | None = None,
        max_results: int = 5,
    ) -> None:
        self.url = url
        self.authorization = authorization
        self.tool_name = tool_name
        self.max_results = max_results

    async def search(self, query: str) -> Any:
        try:
            from mcp import ClientSession
            from mcp.client.streamable_http import streamablehttp_client
        except ImportError as exc:  # pragma: no cover - exercised only without dependency.
            raise RuntimeError("mcp package is not installed") from exc

        headers = {"Authorization": self.authorization} if self.authorization else {}
        async with streamablehttp_client(self.url, headers=headers, timeout=30) as streams:
            read_stream, write_stream = streams[0], streams[1]
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                tools_response = await session.list_tools()
                tool = self._select_tool(tools_response.tools)
                arguments = self._build_arguments(tool, query)
                result = await session.call_tool(tool.name, arguments=arguments)
                return self._extract_result(result)

    def _select_tool(self, tools: list[Any]) -> Any:
        if self.tool_name:
            for tool in tools:
                if tool.name == self.tool_name:
                    return tool
            raise RuntimeError(f"MCP tool not found: {self.tool_name}")
        for tool in tools:
            if "search" in tool.name.lower() or "tavily" in tool.name.lower():
                return tool
        if not tools:
            raise RuntimeError("MCP server returned no tools")
        return tools[0]

    def _build_arguments(self, tool: Any, query: str) -> dict[str, Any]:
        schema = getattr(tool, "inputSchema", None) or getattr(tool, "input_schema", None) or {}
        properties = schema.get("properties", {}) if isinstance(schema, dict) else {}
        args: dict[str, Any] = {}
        if not properties or "query" in properties:
            args["query"] = query
        elif "q" in properties:
            args["q"] = query
        else:
            args["query"] = query

        if not properties or "max_results" in properties:
            args["max_results"] = self.max_results
        if "search_depth" in properties:
            args["search_depth"] = "basic"
        if "include_answer" in properties:
            args["include_answer"] = True
        return args

    def _extract_result(self, result: Any) -> Any:
        structured = getattr(result, "structuredContent", None) or getattr(result, "structured_content", None)
        if structured is not None:
            return structured
        contents = getattr(result, "content", None) or []
        texts: list[str] = []
        for item in contents:
            text = getattr(item, "text", None)
            if text:
                texts.append(text)
        return "\n\n".join(texts) if texts else result


class SearchSubAgent:
    def __init__(self, *, mcp_client: MCPSearchClient, llm: OpenAIChatClient, model: str) -> None:
        self.mcp_client = mcp_client
        self.llm = llm
        self.model = model

    async def search(self, *, query: str, role: RoleCard) -> SearchBrief:
        raw_result = await self.mcp_client.search(query)
        raw_text = raw_result if isinstance(raw_result, str) else json.dumps(raw_result, ensure_ascii=False)
        prompt = (
            "You are a search subagent. Summarize Tavily MCP search results for a role-play QQ bot. "
            "Return strict JSON with keys: query, summary, facts, source_urls, confidence, freshness_notes. "
            "Do not imitate the final character voice. Be factual and compact."
        )
        try:
            data = await self.llm.complete_json(
                [
                    {"role": "system", "content": prompt},
                    {
                        "role": "user",
                        "content": (
                            f"Query: {query}\n"
                            f"Role search preference: {role.search_style}\n"
                            f"Raw result:\n{raw_text[:12000]}"
                        ),
                    },
                ],
                model=self.model,
                temperature=0.2,
            )
            data["query"] = query
            return SearchBrief.model_validate(data)
        except Exception:
            logger.exception("search summarization failed; returning raw fallback")
            return SearchBrief(
                query=query,
                summary=raw_text[:1500],
                facts=[raw_text[:500]],
                source_urls=_extract_urls(raw_text),
                confidence="low",
                freshness_notes="Search succeeded, but summarization failed.",
            )


def _extract_urls(text: str) -> list[str]:
    urls: list[str] = []
    for token in text.replace('"', " ").replace("'", " ").split():
        if token.startswith(("http://", "https://")):
            urls.append(token.rstrip("),.;]"))
    return list(dict.fromkeys(urls))[:8]
