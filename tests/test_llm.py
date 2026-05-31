import logging

from qqbot.llm import OpenAIChatClient


def test_log_usage_includes_cached_tokens(caplog) -> None:
    caplog.set_level(logging.INFO, logger="qqbot.llm")

    OpenAIChatClient._log_usage(
        {
            "usage": {
                "prompt_tokens": 1200,
                "completion_tokens": 40,
                "total_tokens": 1240,
                "prompt_tokens_details": {"cached_tokens": 896},
            }
        },
        "test-model",
    )

    assert "model=test-model" in caplog.text
    assert "prompt_tokens=1200" in caplog.text
    assert "cached_tokens=896" in caplog.text


def test_log_usage_ignores_missing_usage(caplog) -> None:
    caplog.set_level(logging.INFO, logger="qqbot.llm")

    OpenAIChatClient._log_usage({}, "test-model")

    assert caplog.text == ""
