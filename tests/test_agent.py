import asyncio

from qqbot.agent import MainAgent
from qqbot.models import DialogueContext, DialogueTurn, IncomingMessage, MessageScope, RoleCard


class FakeLLM:
    def __init__(self) -> None:
        self.messages = []
        self.compact_messages = []

    async def complete(self, messages, *, model=None, temperature=0.7):
        if messages and "Compact a QQ bot dialogue context" in messages[0]["content"]:
            self.compact_messages = messages
            return "compact summary"
        self.messages = messages
        return "reply"

    async def complete_json(self, messages, *, model=None, temperature=0.2):
        return {"needs_search": False, "query": ""}


class FakeMemory:
    def __init__(self, context: DialogueContext) -> None:
        self.context = context
        self.replaced_context = None

    async def search(self, *, query, role_id, room):
        return []

    async def dialogue_context(self, *, role_id, room):
        return self.context

    async def replace_dialogue_context(self, *, role_id, room, compacted, turns=None):
        self.replaced_context = DialogueContext(
            role_id=role_id,
            room=room,
            compacted=compacted,
            turns=turns or [],
        )
        self.context = self.replaced_context
        return self.replaced_context


class FakeSearchAgent:
    async def search(self, *, query, role):
        raise AssertionError("search should not run")


class FailingSearchAgent:
    async def search(self, *, query, role):
        raise RuntimeError("search unavailable")


def test_main_agent_includes_dialogue_context() -> None:
    async def run() -> None:
        llm = FakeLLM()
        memory = FakeMemory(
            DialogueContext(
                role_id="default",
                room="private_1",
                compacted="older summary",
                turns=[DialogueTurn(user_text="earlier user", bot_text="earlier bot")],
            )
        )
        agent = MainAgent(
            llm=llm,
            model="test",
            search_agent=FakeSearchAgent(),
            memory=memory,
            dialogue_context_limit=10000,
            dialogue_compact_target=3000,
        )
        incoming = IncomingMessage(
            message_id=1,
            scope=MessageScope(message_type="private", user_id=1),
            raw_text="now",
            text="now",
        )
        role = RoleCard(id="default", name="Default", persona="P")

        await agent.reply(incoming=incoming, role=role)

        prompt = "\n".join(message["content"] for message in llm.messages)
        dialogue_index = next(
            index for index, message in enumerate(llm.messages) if "Dialogue context" in message["content"]
        )
        memory_index = next(
            index for index, message in enumerate(llm.messages) if "Relevant long-term memory" in message["content"]
        )
        assert "Dialogue context" in prompt
        assert "older summary" in prompt
        assert "User: earlier user" in prompt
        assert "Bot: earlier bot" in prompt
        assert dialogue_index < memory_index
        assert llm.messages[-1]["role"] == "user"
        assert llm.messages[-1]["content"] == "now"

    asyncio.run(run())


def test_main_agent_compacts_dialogue_context_when_limit_is_exceeded() -> None:
    async def run() -> None:
        llm = FakeLLM()
        memory = FakeMemory(
            DialogueContext(
                role_id="default",
                room="private_1",
                turns=[DialogueTurn(user_text="x" * 200, bot_text="y" * 200)],
            )
        )
        agent = MainAgent(
            llm=llm,
            model="test",
            search_agent=FakeSearchAgent(),
            memory=memory,
            dialogue_context_limit=100,
            dialogue_compact_target=80,
        )

        compacted = await agent.compact_dialogue_if_needed(role_id="default", room="private_1")

        assert compacted is True
        assert memory.replaced_context is not None
        assert memory.replaced_context.compacted == "compact summary"
        assert memory.replaced_context.turns == []
        assert "Raw dialogue to compact" in llm.compact_messages[1]["content"]

    asyncio.run(run())


def test_main_agent_warns_model_about_unsupported_content() -> None:
    async def run() -> None:
        llm = FakeLLM()
        memory = FakeMemory(DialogueContext(role_id="default", room="private_1"))
        agent = MainAgent(
            llm=llm,
            model="test",
            search_agent=FakeSearchAgent(),
            memory=memory,
            dialogue_context_limit=10000,
            dialogue_compact_target=3000,
        )
        incoming = IncomingMessage(
            message_id=1,
            scope=MessageScope(message_type="private", user_id=1),
            raw_text="这张图是什么",
            text="这张图是什么",
            unsupported_content_types=("image",),
        )
        role = RoleCard(id="default", name="Default", persona="P")

        await agent.reply(incoming=incoming, role=role)

        prompt = "\n".join(message["content"] for message in llm.messages)
        assert "unsupported non-text content" in prompt
        assert "Do not infer or describe" in prompt
        assert llm.messages[-1]["content"] == "这张图是什么"

    asyncio.run(run())


def test_main_agent_system_prompt_preserves_qq_at_codes() -> None:
    async def run() -> None:
        llm = FakeLLM()
        memory = FakeMemory(DialogueContext(role_id="default", room="private_1"))
        agent = MainAgent(
            llm=llm,
            model="test",
            search_agent=FakeSearchAgent(),
            memory=memory,
            dialogue_context_limit=10000,
            dialogue_compact_target=3000,
        )
        incoming = IncomingMessage(
            message_id=1,
            scope=MessageScope(message_type="group", group_id=2, user_id=1),
            raw_text="帮我叫一下 [CQ:at,qq=99]",
            text="帮我叫一下 [CQ:at,qq=99]",
        )
        role = RoleCard(id="default", name="Default", persona="P")

        await agent.reply(incoming=incoming, role=role)

        assert "keep the CQ at code exactly" in llm.messages[0]["content"]
        assert llm.messages[-1]["content"] == "帮我叫一下 [CQ:at,qq=99]"

    asyncio.run(run())


def test_main_agent_replies_without_search_when_search_fails() -> None:
    async def run() -> None:
        llm = FakeLLM()
        memory = FakeMemory(DialogueContext(role_id="default", room="private_1"))
        agent = MainAgent(
            llm=llm,
            model="test",
            search_agent=FailingSearchAgent(),
            memory=memory,
            dialogue_context_limit=10000,
            dialogue_compact_target=3000,
        )
        incoming = IncomingMessage(
            message_id=1,
            scope=MessageScope(message_type="private", user_id=1),
            raw_text="today weather",
            text="today weather",
        )
        role = RoleCard(id="default", name="Default", persona="P")

        reply = await agent.reply(incoming=incoming, role=role, force_search_query="today weather")

        assert reply.text == "reply"
        assert reply.search_brief is None
        assert not any("Search knowledge from Search SubAgent" in message["content"] for message in llm.messages)

    asyncio.run(run())
