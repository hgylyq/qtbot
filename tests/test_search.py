import asyncio

from qqbot.llm import parse_json_object
from qqbot.models import RoleCard
from qqbot.search import SearchSubAgent


class FakeMCP:
    async def search(self, query: str):
        return {"answer": "Python 3.11 is supported.", "results": [{"url": "https://example.test"}]}


class FakeLLM:
    async def complete_json(self, messages, *, model=None, temperature=0.2):
        return parse_json_object(
            """
            {
              "query": "ignored",
              "summary": "Python 3.11 is supported.",
              "facts": ["Python 3.11 is supported."],
              "source_urls": ["https://example.test"],
              "confidence": "high",
              "freshness_notes": "test"
            }
            """
        )


def test_search_subagent_returns_brief() -> None:
    async def run() -> None:
        agent = SearchSubAgent(mcp_client=FakeMCP(), llm=FakeLLM(), model="test")
        role = RoleCard(id="r", name="R", persona="P")
        brief = await agent.search(query="python", role=role)
        assert brief.query == "python"
        assert brief.confidence == "high"
        assert brief.source_urls == ["https://example.test"]

    asyncio.run(run())
