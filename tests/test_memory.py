import asyncio

from qqbot.memory import MemoryStore, dialogue_context_to_prompt
from qqbot.models import DialogueContext, DialogueTurn


def test_fallback_memory_is_scoped_by_role_and_room(tmp_path) -> None:
    async def run() -> None:
        store = MemoryStore(
            palace_path=tmp_path / "palace",
            transcripts_dir=tmp_path / "transcripts",
            auto_mine=False,
            enable_mempalace=False,
        )
        await store.record_interaction(
            role_id="a",
            room="private_1",
            user_text="I like jasmine tea",
            bot_text="noted",
        )
        await store.record_interaction(
            role_id="b",
            room="private_1",
            user_text="I like coffee",
            bot_text="noted",
        )
        hits = await store.search(query="jasmine", role_id="a", room="private_1")
        assert len(hits) == 1
        assert "jasmine tea" in hits[0].text
        assert await store.search(query="jasmine", role_id="b", room="private_1") == []

    asyncio.run(run())


def test_dialogue_context_is_scoped_by_role_and_room(tmp_path) -> None:
    async def run() -> None:
        store = MemoryStore(
            palace_path=tmp_path / "palace",
            transcripts_dir=tmp_path / "transcripts",
            auto_mine=False,
            enable_mempalace=False,
        )
        await store.record_interaction(
            role_id="a",
            room="private_1",
            user_text="first",
            bot_text="one",
        )
        await store.record_interaction(
            role_id="b",
            room="private_1",
            user_text="other role",
            bot_text="ignored",
        )
        await store.record_interaction(
            role_id="a",
            room="private_2",
            user_text="other room",
            bot_text="ignored",
        )
        await store.record_interaction(
            role_id="a",
            room="private_1",
            user_text="second",
            bot_text="two",
        )
        await store.record_interaction(
            role_id="a",
            room="private_1",
            user_text="third",
            bot_text="three",
        )

        context = await store.dialogue_context(role_id="a", room="private_1")

        assert [turn.user_text for turn in context.turns] == ["first", "second", "third"]
        assert [turn.bot_text for turn in context.turns] == ["one", "two", "three"]

    asyncio.run(run())


def test_dialogue_context_can_be_replaced_with_compacted_summary(tmp_path) -> None:
    async def run() -> None:
        store = MemoryStore(
            palace_path=tmp_path / "palace",
            transcripts_dir=tmp_path / "transcripts",
            auto_mine=False,
            enable_mempalace=False,
        )
        await store.record_interaction(
            role_id="a",
            room="private_1",
            user_text="first",
            bot_text="one",
        )

        await store.replace_dialogue_context(
            role_id="a",
            room="private_1",
            compacted="summary",
            turns=[],
        )
        context = await store.dialogue_context(role_id="a", room="private_1")

        assert context.compacted == "summary"
        assert context.turns == []

    asyncio.run(run())


def test_dialogue_context_can_be_cleared_without_rehydrating_from_logs(tmp_path) -> None:
    async def run() -> None:
        store = MemoryStore(
            palace_path=tmp_path / "palace",
            transcripts_dir=tmp_path / "transcripts",
            auto_mine=False,
            enable_mempalace=False,
        )
        await store.record_interaction(
            role_id="a",
            room="private_1",
            user_text="first",
            bot_text="one",
        )

        await store.clear_dialogue_context(role_id="a", room="private_1")
        context = await store.dialogue_context(role_id="a", room="private_1")

        assert context.compacted == ""
        assert context.turns == []

    asyncio.run(run())


def test_clear_memory_removes_local_memory_for_role_and_room(tmp_path) -> None:
    async def run() -> None:
        store = MemoryStore(
            palace_path=tmp_path / "palace",
            transcripts_dir=tmp_path / "transcripts",
            auto_mine=False,
            enable_mempalace=False,
        )
        await store.record_interaction(
            role_id="a",
            room="private_1",
            user_text="I like jasmine tea",
            bot_text="noted",
        )
        await store.record_interaction(
            role_id="a",
            room="private_2",
            user_text="I like jasmine tea",
            bot_text="noted",
        )
        await store.record_interaction(
            role_id="b",
            room="private_1",
            user_text="I like jasmine tea",
            bot_text="noted",
        )

        result = await store.clear_memory(role_id="a", room="private_1")

        assert result.local_files_deleted == 2
        assert result.mempalace_records_deleted is None
        assert await store.search(query="jasmine", role_id="a", room="private_1") == []
        assert await store.search(query="jasmine", role_id="a", room="private_2")
        assert await store.search(query="jasmine", role_id="b", room="private_1")

    asyncio.run(run())


def test_dialogue_context_prompt_renders_summary_and_raw_turns() -> None:
    prompt = dialogue_context_to_prompt(
        DialogueContext(
            role_id="a",
            room="private_1",
            compacted="summary",
            turns=[DialogueTurn(user_text="hello", bot_text="hi")],
        )
    )

    assert "summary" in prompt
    assert "User: hello" in prompt
    assert "Bot: hi" in prompt
