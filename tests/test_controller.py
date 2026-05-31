import asyncio

from qqbot.controller import BotController
from qqbot.memory import ClearMemoryResult, MemoryStore
from qqbot.models import AgentReply, IncomingMessage, MessageScope, RoleCard
from qqbot.roles import RoleStore


class FakeGenerator:
    async def generate(self, *, role_id: str, description: str, created_by: int) -> RoleCard:
        return RoleCard(id=role_id, name="Generated", persona=description, created_by=created_by)


class FakeAgent:
    def __init__(self) -> None:
        self.force_search_query = None

    async def reply(self, *, incoming, role, force_search_query=None):
        self.force_search_query = force_search_query
        return AgentReply(text=f"{role.id}:{incoming.text}")

    async def compact_dialogue_if_needed(self, *, role_id, room):
        return False


def make_incoming(text: str, user_id: int = 1) -> IncomingMessage:
    return IncomingMessage(
        message_id=1,
        scope=MessageScope(message_type="private", user_id=user_id),
        raw_text=text,
        text=text,
    )


def test_owner_can_generate_role(tmp_path) -> None:
    async def run() -> None:
        store = RoleStore(roles_dir=tmp_path / "roles", state_path=tmp_path / "state.yaml")
        memory = MemoryStore(
            palace_path=tmp_path / "palace",
            transcripts_dir=tmp_path / "transcripts",
            auto_mine=False,
            enable_mempalace=False,
        )
        controller = BotController(
            role_store=store,
            role_generator=FakeGenerator(),
            main_agent=FakeAgent(),
            memory=memory,
            owner_ids={1},
        )
        reply = await controller.handle(make_incoming("/角色生成 maid gentle helper"))
        assert "已生成角色" in reply
        assert store.load("maid").persona == "gentle helper"

    asyncio.run(run())


def test_help_command_lists_available_commands(tmp_path) -> None:
    async def run() -> None:
        store = RoleStore(roles_dir=tmp_path / "roles", state_path=tmp_path / "state.yaml")
        memory = MemoryStore(
            palace_path=tmp_path / "palace",
            transcripts_dir=tmp_path / "transcripts",
            auto_mine=False,
            enable_mempalace=False,
        )
        controller = BotController(
            role_store=store,
            role_generator=FakeGenerator(),
            main_agent=FakeAgent(),
            memory=memory,
            owner_ids={1},
        )

        reply = await controller.handle(make_incoming("/帮助"))

        assert "/角色生成 <id> <设定描述>" in reply
        assert "/清除全部" in reply
        assert "/搜 <query>" in reply

    asyncio.run(run())


def test_help_alias_without_prefix_lists_available_commands(tmp_path) -> None:
    async def run() -> None:
        store = RoleStore(roles_dir=tmp_path / "roles", state_path=tmp_path / "state.yaml")
        memory = MemoryStore(
            palace_path=tmp_path / "palace",
            transcripts_dir=tmp_path / "transcripts",
            auto_mine=False,
            enable_mempalace=False,
        )
        controller = BotController(
            role_store=store,
            role_generator=FakeGenerator(),
            main_agent=FakeAgent(),
            memory=memory,
            owner_ids={1},
        )

        reply = await controller.handle(make_incoming("help"))

        assert "/帮助" in reply

    asyncio.run(run())


def test_help_shows_multimodal_status(tmp_path) -> None:
    async def run() -> None:
        store = RoleStore(roles_dir=tmp_path / "roles", state_path=tmp_path / "state.yaml")
        memory = MemoryStore(
            palace_path=tmp_path / "palace",
            transcripts_dir=tmp_path / "transcripts",
            auto_mine=False,
            enable_mempalace=False,
        )
        controller = BotController(
            role_store=store,
            role_generator=FakeGenerator(),
            main_agent=FakeAgent(),
            memory=memory,
            owner_ids={1},
            enabled_multimodal_types={"image"},
        )

        reply = await controller.handle(make_incoming("/帮助"))

        assert "多模态：配置已启用 图片" in reply
        assert "尚未接入媒体文件下载" in reply

    asyncio.run(run())


def test_non_owner_cannot_generate_role(tmp_path) -> None:
    async def run() -> None:
        store = RoleStore(roles_dir=tmp_path / "roles", state_path=tmp_path / "state.yaml")
        memory = MemoryStore(
            palace_path=tmp_path / "palace",
            transcripts_dir=tmp_path / "transcripts",
            auto_mine=False,
            enable_mempalace=False,
        )
        controller = BotController(
            role_store=store,
            role_generator=FakeGenerator(),
            main_agent=FakeAgent(),
            memory=memory,
            owner_ids={2},
        )
        reply = await controller.handle(make_incoming("/角色生成 maid gentle helper", user_id=1))
        assert reply == "没有权限管理角色卡。"

    asyncio.run(run())


def test_search_command_uses_force_search(tmp_path) -> None:
    async def run() -> None:
        store = RoleStore(roles_dir=tmp_path / "roles", state_path=tmp_path / "state.yaml")
        memory = MemoryStore(
            palace_path=tmp_path / "palace",
            transcripts_dir=tmp_path / "transcripts",
            auto_mine=False,
            enable_mempalace=False,
        )
        agent = FakeAgent()
        controller = BotController(
            role_store=store,
            role_generator=FakeGenerator(),
            main_agent=agent,
            memory=memory,
            owner_ids={1},
        )
        reply = await controller.handle(make_incoming("/搜 tavily mcp"))
        assert reply == "default:tavily mcp"
        assert agent.force_search_query == "tavily mcp"

    asyncio.run(run())


def test_empty_search_command_returns_usage(tmp_path) -> None:
    async def run() -> None:
        store = RoleStore(roles_dir=tmp_path / "roles", state_path=tmp_path / "state.yaml")
        memory = MemoryStore(
            palace_path=tmp_path / "palace",
            transcripts_dir=tmp_path / "transcripts",
            auto_mine=False,
            enable_mempalace=False,
        )
        controller = BotController(
            role_store=store,
            role_generator=FakeGenerator(),
            main_agent=FakeAgent(),
            memory=memory,
            owner_ids={1},
        )

        reply = await controller.handle(make_incoming("/搜"))

        assert reply == "用法：/搜 <query>"

    asyncio.run(run())


def test_image_only_message_gets_text_fallback_prompt(tmp_path) -> None:
    async def run() -> None:
        store = RoleStore(roles_dir=tmp_path / "roles", state_path=tmp_path / "state.yaml")
        memory = MemoryStore(
            palace_path=tmp_path / "palace",
            transcripts_dir=tmp_path / "transcripts",
            auto_mine=False,
            enable_mempalace=False,
        )
        controller = BotController(
            role_store=store,
            role_generator=FakeGenerator(),
            main_agent=FakeAgent(),
            memory=memory,
            owner_ids={1},
        )
        incoming = make_incoming("")
        incoming = IncomingMessage(
            message_id=incoming.message_id,
            scope=incoming.scope,
            raw_text=incoming.raw_text,
            text=incoming.text,
            unsupported_content_types=("image",),
        )

        reply = await controller.handle(incoming)

        assert reply is not None
        assert "当前模型不能查看非文本内容" in reply

    asyncio.run(run())


def test_image_only_message_mentions_configured_multimodal_entry(tmp_path) -> None:
    async def run() -> None:
        store = RoleStore(roles_dir=tmp_path / "roles", state_path=tmp_path / "state.yaml")
        memory = MemoryStore(
            palace_path=tmp_path / "palace",
            transcripts_dir=tmp_path / "transcripts",
            auto_mine=False,
            enable_mempalace=False,
        )
        controller = BotController(
            role_store=store,
            role_generator=FakeGenerator(),
            main_agent=FakeAgent(),
            memory=memory,
            owner_ids={1},
            enabled_multimodal_types={"image"},
        )
        incoming = make_incoming("")
        incoming = IncomingMessage(
            message_id=incoming.message_id,
            scope=incoming.scope,
            raw_text=incoming.raw_text,
            text=incoming.text,
            unsupported_content_types=("image",),
        )

        reply = await controller.handle(incoming)

        assert "当前配置显示已启用图片多模态入口" in reply
        assert "尚未接入" in reply

    asyncio.run(run())


def test_clear_context_command_resets_current_context(tmp_path) -> None:
    async def run() -> None:
        store = RoleStore(roles_dir=tmp_path / "roles", state_path=tmp_path / "state.yaml")
        memory = MemoryStore(
            palace_path=tmp_path / "palace",
            transcripts_dir=tmp_path / "transcripts",
            auto_mine=False,
            enable_mempalace=False,
        )
        await memory.record_interaction(
            role_id="default",
            room="private_1",
            user_text="remember this context",
            bot_text="noted",
        )
        controller = BotController(
            role_store=store,
            role_generator=FakeGenerator(),
            main_agent=FakeAgent(),
            memory=memory,
            owner_ids={1},
        )

        reply = await controller.handle(make_incoming("/清除context"))
        context = await memory.dialogue_context(role_id="default", room="private_1")

        assert "已清空当前 context" in reply
        assert context.turns == []
        assert context.compacted == ""

    asyncio.run(run())


def test_clear_memory_command_removes_current_memory(tmp_path) -> None:
    async def run() -> None:
        store = RoleStore(roles_dir=tmp_path / "roles", state_path=tmp_path / "state.yaml")
        memory = MemoryStore(
            palace_path=tmp_path / "palace",
            transcripts_dir=tmp_path / "transcripts",
            auto_mine=False,
            enable_mempalace=False,
        )
        await memory.record_interaction(
            role_id="default",
            room="private_1",
            user_text="I like jasmine tea",
            bot_text="noted",
        )
        controller = BotController(
            role_store=store,
            role_generator=FakeGenerator(),
            main_agent=FakeAgent(),
            memory=memory,
            owner_ids={1},
        )

        reply = await controller.handle(make_incoming("/清除memory"))

        assert "已清除当前 memory" in reply
        assert await memory.search(query="jasmine", role_id="default", room="private_1") == []

    asyncio.run(run())


def test_clear_memory_reply_prefers_mempalace_error() -> None:
    result = ClearMemoryResult(
        local_files_deleted=0,
        mempalace_records_deleted=None,
        mempalace_error="database locked",
    )

    reply = BotController._clear_memory_reply("已清除当前 memory", "default", result)

    assert "MemPalace：清理失败（database locked）。" in reply
    assert "MemPalace：未启用。" not in reply
