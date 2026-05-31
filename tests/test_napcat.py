from qqbot.napcat import parse_message_event


def test_private_message_always_triggers() -> None:
    event = {
        "post_type": "message",
        "message_type": "private",
        "user_id": 1,
        "message_id": 10,
        "message": "hello",
    }
    incoming = parse_message_event(event, self_id=42, prefix="/")
    assert incoming is not None
    assert incoming.text == "hello"
    assert incoming.scope.room == "private_1"


def test_group_message_requires_prefix_or_at() -> None:
    event = {
        "post_type": "message",
        "message_type": "group",
        "group_id": 9,
        "user_id": 1,
        "message_id": 10,
        "message": "hello",
    }
    assert parse_message_event(event, self_id=42, prefix="/") is None

    event["message"] = "/hello"
    incoming = parse_message_event(event, self_id=42, prefix="/")
    assert incoming is not None
    assert incoming.text == "hello"
    assert incoming.scope.room == "group_9_user_1"


def test_group_at_strips_mention() -> None:
    event = {
        "post_type": "message",
        "message_type": "group",
        "group_id": 9,
        "user_id": 1,
        "message_id": 10,
        "message": "[CQ:at,qq=42] /角色列表",
    }
    incoming = parse_message_event(event, self_id=42, prefix="/")
    assert incoming is not None
    assert incoming.text == "角色列表"


def test_group_array_at_triggers_and_strips_mention() -> None:
    event = {
        "post_type": "message",
        "message_type": "group",
        "group_id": 9,
        "user_id": 1,
        "message_id": 10,
        "message": [
            {"type": "at", "data": {"qq": "42"}},
            {"type": "text", "data": {"text": " 你好"}},
        ],
    }
    incoming = parse_message_event(event, self_id=42, prefix="/")
    assert incoming is not None
    assert incoming.text == "你好"


def test_group_keeps_non_self_mentions_for_model() -> None:
    event = {
        "post_type": "message",
        "message_type": "group",
        "group_id": 9,
        "user_id": 1,
        "message_id": 10,
        "message": [
            {"type": "at", "data": {"qq": "42"}},
            {"type": "text", "data": {"text": " 帮我叫一下 "}},
            {"type": "at", "data": {"qq": "99"}},
        ],
    }
    incoming = parse_message_event(event, self_id=42, prefix="/")
    assert incoming is not None
    assert "[CQ:at,qq=42]" not in incoming.text
    assert "[CQ:at,qq=99]" in incoming.text
    assert "帮我叫一下" in incoming.text


def test_group_bare_at_becomes_replyable_prompt() -> None:
    event = {
        "post_type": "message",
        "message_type": "group",
        "group_id": 9,
        "user_id": 1,
        "message_id": 10,
        "message": [{"type": "at", "data": {"qq": "42"}}],
    }
    incoming = parse_message_event(event, self_id=42, prefix="/")
    assert incoming is not None
    assert "没有附加文字" in incoming.text


def test_private_image_is_marked_as_unsupported_content() -> None:
    event = {
        "post_type": "message",
        "message_type": "private",
        "user_id": 1,
        "message_id": 10,
        "message": [{"type": "image", "data": {"file": "a.jpg"}}],
    }
    incoming = parse_message_event(event, self_id=42, prefix="/")
    assert incoming is not None
    assert incoming.text == ""
    assert incoming.unsupported_content_types == ("image",)
