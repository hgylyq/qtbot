from __future__ import annotations

import asyncio
import logging

from .agent import MainAgent
from .config import Settings
from .controller import BotController
from .llm import OpenAIChatClient
from .memory import MemoryStore
from .napcat import NapCatClient
from .roles import RoleCardGenerator, RoleStore
from .search import MCPSearchClient, SearchSubAgent


def build_controller(settings: Settings) -> BotController:
    settings.ensure_dirs()
    llm = OpenAIChatClient(
        api_key=settings.openai_api_key,
        base_url=settings.openai_base_url,
        default_model=settings.main_model,
    )
    memory = MemoryStore(
        palace_path=settings.mempalace_path,
        transcripts_dir=settings.transcripts_dir,
        n_results=settings.mempalace_results,
        auto_mine=settings.mempalace_auto_mine,
    )
    role_store = RoleStore(
        roles_dir=settings.roles_dir,
        state_path=settings.state_path,
        default_role_id=settings.default_role_id,
    )
    mcp_client = MCPSearchClient(
        url=settings.tavily_mcp_url,
        authorization=settings.tavily_mcp_authorization,
        tool_name=settings.tavily_mcp_tool,
        max_results=settings.tavily_max_results,
    )
    search_agent = SearchSubAgent(mcp_client=mcp_client, llm=llm, model=settings.search_model)
    main_agent = MainAgent(
        llm=llm,
        model=settings.main_model,
        search_agent=search_agent,
        memory=memory,
        dialogue_context_limit=settings.dialogue_context_limit,
        dialogue_compact_target=settings.dialogue_compact_target,
        tokenizer_encoding=settings.tokenizer_encoding,
        enabled_multimodal_types=settings.enabled_multimodal_types(),
    )
    role_generator = RoleCardGenerator(llm, model=settings.role_model)
    return BotController(
        role_store=role_store,
        role_generator=role_generator,
        main_agent=main_agent,
        memory=memory,
        owner_ids=settings.owner_ids(),
        prefix=settings.bot_prefix,
        enabled_multimodal_types=settings.enabled_multimodal_types(),
    )


async def async_main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    settings = Settings()
    controller = build_controller(settings)
    client = NapCatClient(
        ws_url=settings.napcat_ws_url,
        self_id=settings.bot_self_id,
        prefix=settings.bot_prefix,
        handler=controller.handle,
    )
    await client.run_forever()


def main() -> None:
    asyncio.run(async_main())
