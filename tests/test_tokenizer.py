from qqbot.tokenizer import TokenCounter


def test_token_counter_counts_and_truncates_text() -> None:
    counter = TokenCounter(model="unknown-test-model")
    text = "hello world " * 100

    assert counter.count_text(text) > 0
    assert counter.count_text(counter.truncate_text(text, 10)) <= 10


def test_token_counter_counts_messages() -> None:
    counter = TokenCounter(model="unknown-test-model")
    messages = [
        {"role": "system", "content": "rules"},
        {"role": "user", "content": "hello"},
    ]

    assert counter.count_messages(messages) >= counter.count_text("rules") + counter.count_text("hello")
