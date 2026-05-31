from qqbot.config import Settings


def test_dotenv_overrides_process_env(tmp_path, monkeypatch) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("OPENAI_BASE_URL=https://from-dotenv.example/v1\n", encoding="utf-8")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://from-process-env.example/v1")

    settings = Settings(_env_file=env_file)

    assert settings.openai_base_url == "https://from-dotenv.example/v1"
