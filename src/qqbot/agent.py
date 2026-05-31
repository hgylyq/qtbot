from __future__ import annotations

import logging
from datetime import date

from .llm import OpenAIChatClient
from .memory import (
    MemoryStore,
    dialogue_context_to_compact_source,
    dialogue_context_to_prompt,
    memory_hits_to_prompt,
)
from .models import AgentReply, IncomingMessage, RoleCard, SearchBrief
from .search import SearchSubAgent
from .tokenizer import TokenCounter


SEARCH_HINTS = (
    "最新",
    "今天",
    "现在",
    "新闻",
    "联网",
    "搜索",
    "查一下",
    "查查",
    "最近",
    "价格",
    "天气",
    "政策",
    "版本",
    "current",
    "latest",
    "today",
    "news",
)

logger = logging.getLogger(__name__)


class MainAgent:
    def __init__(
        self,
        *,
        llm: OpenAIChatClient,
        model: str,
        search_agent: SearchSubAgent,
        memory: MemoryStore,
        dialogue_context_limit: int = 8000,
        dialogue_compact_target: int = 3000,
        tokenizer_encoding: str = "cl100k_base",
    ) -> None:
        self.llm = llm
        self.model = model
        self.search_agent = search_agent
        self.memory = memory
        self.dialogue_context_limit = dialogue_context_limit
        self.dialogue_compact_target = dialogue_compact_target
        self.token_counter = TokenCounter(model=model, encoding_name=tokenizer_encoding)

    async def reply(
        self,
        *,
        incoming: IncomingMessage,
        role: RoleCard,
        force_search_query: str | None = None,
    ) -> AgentReply:
        await self.compact_dialogue_if_needed(role_id=role.id, room=incoming.scope.room)
        memory_hits = await self.memory.search(query=incoming.text, role_id=role.id, room=incoming.scope.room)
        dialogue_context = await self.memory.dialogue_context(
            role_id=role.id,
            room=incoming.scope.room,
        )
        search_brief: SearchBrief | None = None
        search_query = force_search_query or await self._decide_search_query(incoming.text, role)
        if search_query:
            try:
                search_brief = await self.search_agent.search(query=search_query, role=role)
            except Exception:
                logger.exception("search failed; replying without search context")

        messages = [
            {"role": "system", "content": self._system_prompt(role)},
            {"role": "system", "content": f"Current date: {date.today().isoformat()}"},
            {
                "role": "system",
                "content": (
                    "Dialogue context for this same role and chat scope. "
                    "Use it for continuity, but do not repeat it unless relevant:\n"
                    + dialogue_context_to_prompt(dialogue_context)
                ),
            },
            {"role": "system", "content": "Relevant long-term memory:\n" + memory_hits_to_prompt(memory_hits)},
        ]
        if incoming.unsupported_content_types:
            messages.append({"role": "system", "content": self._unsupported_content_prompt(incoming)})
        if search_brief is not None:
            messages.append({"role": "system", "content": self._search_prompt(search_brief)})
        messages.append({"role": "user", "content": incoming.text})
        text = await self.llm.complete(messages, model=self.model, temperature=0.8)
        return AgentReply(text=text, search_brief=search_brief)

    async def compact_dialogue_if_needed(self, *, role_id: str, room: str) -> bool:
        if self.dialogue_context_limit <= 0:
            return False
        context = await self.memory.dialogue_context(role_id=role_id, room=room)
        rendered = dialogue_context_to_prompt(context)
        if self.token_counter.count_text(rendered) <= self.dialogue_context_limit:
            return False

        source = dialogue_context_to_compact_source(context)
        try:
            compacted = await self.llm.complete(
                [
                    {
                        "role": "system",
                        "content": (
                            "Compact a QQ bot dialogue context. Preserve stable user facts, preferences, "
                            "unresolved requests, relationship state, roleplay continuity, and decisions. "
                            "Discard greetings, filler, repeated wording, and low-value details. "
                            "Do not imitate the role; write concise neutral notes. "
                            f"Keep the result under {self.dialogue_compact_target} tokens when possible."
                        ),
                    },
                    {"role": "user", "content": source},
                ],
                model=self.model,
                temperature=0.2,
            )
        except Exception:
            logger.exception("dialogue compact failed; using local fallback")
            compacted = self._fallback_compact(source)
        compacted = compacted.strip()
        if self.dialogue_compact_target > 0:
            compacted = self.token_counter.truncate_text(compacted, self.dialogue_compact_target)
        await self.memory.replace_dialogue_context(
            role_id=role_id,
            room=room,
            compacted=compacted,
            turns=[],
        )
        return True

    def _fallback_compact(self, source: str) -> str:
        target = max(self.dialogue_compact_target, 1000)
        cleaned = "\n".join(line.rstrip() for line in source.splitlines() if line.strip())
        if self.token_counter.count_text(cleaned) <= target:
            return cleaned
        head = max(target // 3, 1)
        tail = max(target - head - 20, 1)
        return (
            self.token_counter.truncate_text(cleaned, head).rstrip()
            + "\n...\n"
            + self._truncate_text_from_end(cleaned, tail).lstrip()
        )

    def _truncate_text_from_end(self, text: str, max_tokens: int) -> str:
        if self.token_counter.count_text(text) <= max_tokens:
            return text
        reversed_text = text[::-1]
        return self.token_counter.truncate_text(reversed_text, max_tokens)[::-1]

    async def _decide_search_query(self, text: str, role: RoleCard) -> str | None:
        if not any(hint.lower() in text.lower() for hint in SEARCH_HINTS):
            return None
        try:
            data = await self.llm.complete_json(
                [
                    {
                        "role": "system",
                        "content": (
                            "Decide if a QQ bot needs web search before replying. "
                            "Return strict JSON: {\"needs_search\": bool, \"query\": string}. "
                            "Search only for recent, external, factual, or unknown information."
                        ),
                    },
                    {"role": "user", "content": f"Role: {role.name}\nMessage: {text}"},
                ],
                model=self.model,
                temperature=0.0,
            )
            if data.get("needs_search") and str(data.get("query", "")).strip():
                return str(data["query"]).strip()
        except Exception:
            return text
        return None

    def _system_prompt(self, role: RoleCard) -> str:
        return "\n".join(
            [
                "You are replying as a QQ bot character.",
                f"Role id: {role.id}",
                f"Name: {role.name}",
                f"Persona: {role.persona}",
                f"Speaking style: {role.speaking_style}",
                "Rules:",
                *[f"- {item}" for item in role.rules],
                "Forbidden:",
                *[f"- {item}" for item in role.forbidden],
                f"Memory notes: {role.memory_notes}",
                "If search context is provided, treat it as knowledge only. Do not sound like a search report.",
                "If the user message contains [CQ:at,qq=...] and asks you to mention that person, keep the CQ at code exactly in your reply.",
                "Answer in the role's voice and keep the reply suitable for QQ chat.",
            ]
        )

    def _search_prompt(self, brief: SearchBrief) -> str:
        facts = "\n".join(f"- {fact}" for fact in brief.facts)
        sources = "\n".join(f"- {url}" for url in brief.source_urls)
        return "\n".join(
            [
                "Search knowledge from Search SubAgent:",
                f"Query: {brief.query}",
                f"Summary: {brief.summary}",
                "Facts:",
                facts or "- none",
                "Sources:",
                sources or "- none",
                f"Confidence: {brief.confidence}",
                f"Freshness notes: {brief.freshness_notes}",
            ]
        )

    def _unsupported_content_prompt(self, incoming: IncomingMessage) -> str:
        labels = ", ".join(incoming.unsupported_content_types)
        return (
            "The user also sent unsupported non-text content in this message: "
            f"{labels}. This bot receives text only; no image, audio, video, or file bytes are available. "
            "Do not infer or describe the unsupported content. If the user asks about it, say you cannot view it "
            "and ask them to describe it in text."
        )
