from qqbot.config import Settings


def test_dotenv_overrides_process_env(tmp_path, monkeypatch) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("OPENAI_BASE_URL=https://from-dotenv.example/v1\n", encoding="utf-8")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://from-process-env.example/v1")

    settings = Settings(_env_file=env_file)

    assert settings.openai_base_url == "https://from-dotenv.example/v1"


def test_multimodal_types_are_explicitly_configured(tmp_path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(
            [
                "MULTIMODAL_ENABLED=true",
                "MULTIMODAL_TYPES=image, record;video",
            ]
        ),
        encoding="utf-8",
    )

    settings = Settings(_env_file=env_file)

    assert settings.enabled_multimodal_types() == {"image", "record", "video"}


def test_multimodal_types_are_empty_when_disabled(tmp_path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("MULTIMODAL_TYPES=image,record\n", encoding="utf-8")

    settings = Settings(_env_file=env_file)

    assert settings.enabled_multimodal_types() == set()
