from __future__ import annotations

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls,
        init_settings,
        env_settings,
        dotenv_settings,
        file_secret_settings,
    ):
        # Local .env should win so changing this project's config is enough.
        return init_settings, dotenv_settings, env_settings, file_secret_settings

    napcat_ws_url: str = Field(default="ws://127.0.0.1:3001", alias="NAPCAT_WS_URL")
    bot_self_id: int | None = Field(default=None, alias="BOT_SELF_ID")
    bot_owner_ids: str = Field(default="", alias="BOT_OWNER_IDS")
    bot_prefix: str = Field(default="/", alias="BOT_PREFIX")

    openai_base_url: str | None = Field(default=None, alias="OPENAI_BASE_URL")
    openai_api_key: str | None = Field(default=None, alias="OPENAI_API_KEY")
    main_model: str = Field(default="gpt-4.1-mini", alias="MAIN_MODEL")
    search_model: str = Field(default="gpt-4.1-mini", alias="SEARCH_MODEL")
    role_model: str = Field(default="gpt-4.1-mini", alias="ROLE_MODEL")
    tokenizer_encoding: str = Field(default="cl100k_base", alias="TOKENIZER_ENCODING")

    tavily_mcp_url: str = Field(default="https://tavily.ivanli.cc/mcp", alias="TAVILY_MCP_URL")
    tavily_mcp_authorization: str | None = Field(default=None, alias="TAVILY_MCP_AUTHORIZATION")
    tavily_mcp_tool: str | None = Field(default=None, alias="TAVILY_MCP_TOOL")
    tavily_max_results: int = Field(default=5, alias="TAVILY_MAX_RESULTS")

    default_role_id: str = Field(default="default", alias="DEFAULT_ROLE_ID")
    roles_dir: Path = Field(default=Path("data/roles"), alias="ROLES_DIR")
    state_path: Path = Field(default=Path("data/state.yaml"), alias="STATE_PATH")
    mempalace_path: Path = Field(default=Path("data/mempalace"), alias="MEMPALACE_PATH")
    transcripts_dir: Path = Field(default=Path("data/transcripts"), alias="TRANSCRIPTS_DIR")
    mempalace_results: int = Field(default=5, alias="MEMPALACE_RESULTS")
    mempalace_auto_mine: bool = Field(default=True, alias="MEMPALACE_AUTO_MINE")
    dialogue_context_limit: int = Field(default=8000, alias="DIALOGUE_CONTEXT_LIMIT")
    dialogue_compact_target: int = Field(default=3000, alias="DIALOGUE_COMPACT_TARGET")

    def owner_ids(self) -> set[int]:
        ids: set[int] = set()
        for part in self.bot_owner_ids.replace(";", ",").split(","):
            value = part.strip()
            if not value:
                continue
            ids.add(int(value))
        return ids

    def ensure_dirs(self) -> None:
        self.roles_dir.mkdir(parents=True, exist_ok=True)
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.mempalace_path.mkdir(parents=True, exist_ok=True)
        self.transcripts_dir.mkdir(parents=True, exist_ok=True)
