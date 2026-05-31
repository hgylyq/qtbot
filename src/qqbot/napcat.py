from __future__ import annotations

import asyncio
import json
import logging
import re
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

import websockets

from .models import IncomingMessage, MessageScope

logger = logging.getLogger(__name__)

CQ_AT_RE = re.compile(r"\[CQ:at,qq=(\d+|all)(?:,[^\]]*)?\]")
CQ_RE = re.compile(r"\[CQ:[^\]]+\]")
CQ_TYPE_RE = re.compile(r"\[CQ:([^,\]]+)")
SUPPORTED_SEGMENT_TYPES = {"text", "at", "reply"}
UNSUPPORTED_SEGMENT_TYPES = {"image", "record", "video", "file", "forward"}


def message_to_text(message: Any) -> str:
    if isinstance(message, str):
        return message
    if isinstance(message, list):
        chunks: list[str] = []
        for item in message:
            if not isinstance(item, dict):
                continue
            item_type = item.get("type")
            data = item.get("data") or {}
            if item_type == "text":
                chunks.append(str(data.get("text", "")))
            elif item_type == "at":
                chunks.append(f"[CQ:at,qq={data.get('qq', '')}]")
        return "".join(chunks)
    return str(message or "")


def strip_cq_codes(text: str) -> str:
    return CQ_RE.sub("", text).strip()


def strip_non_at_cq_codes(text: str) -> str:
    return re.sub(r"\[CQ:(?!at,)[^\]]+\]", "", text).strip()


def unsupported_message_types(message: Any) -> tuple[str, ...]:
    types: set[str] = set()
    if isinstance(message, list):
        for item in message:
            if not isinstance(item, dict):
                continue
            item_type = str(item.get("type") or "")
            if item_type in UNSUPPORTED_SEGMENT_TYPES:
                types.add(item_type)
        return tuple(sorted(types))
    if isinstance(message, str):
        for match in CQ_TYPE_RE.finditer(message):
            item_type = match.group(1)
            if item_type not in SUPPORTED_SEGMENT_TYPES and item_type in UNSUPPORTED_SEGMENT_TYPES:
                types.add(item_type)
    return tuple(sorted(types))


def is_at_self(message: Any, self_id: int | None) -> bool:
    if self_id is None:
        return False
    if isinstance(message, list):
        for item in message:
            if item.get("type") == "at" and str((item.get("data") or {}).get("qq")) == str(self_id):
                return True
        return False
    return any(match.group(1) == str(self_id) for match in CQ_AT_RE.finditer(str(message)))


def strip_self_at(text: str, self_id: int | None) -> str:
    if self_id is None:
        return text.strip()
    return re.sub(rf"\[CQ:at,qq={re.escape(str(self_id))}(?:,[^\]]*)?\]", "", text).strip()


def parse_message_event(payload: dict[str, Any], *, self_id: int | None, prefix: str) -> IncomingMessage | None:
    if payload.get("post_type") != "message":
        return None
    message_type = payload.get("message_type")
    if message_type not in {"private", "group"}:
        return None

    message = payload.get("message")
    raw_message = payload.get("raw_message")
    raw_text = message_to_text(message)
    plain_text = strip_cq_codes(raw_text)
    unsupported_types = tuple(sorted(set(unsupported_message_types(message)) | set(unsupported_message_types(raw_message))))
    user_id = int(payload.get("user_id"))
    sender = payload.get("sender") or {}

    if message_type == "group":
        group_id = int(payload.get("group_id"))
        mentioned = is_at_self(message, self_id) or is_at_self(raw_message, self_id)
        prefixed = plain_text.startswith(prefix)
        if not mentioned and not prefixed:
            return None
        text = strip_self_at(raw_text, self_id)
        text = strip_non_at_cq_codes(text)
        if text.startswith(prefix):
            text = text[len(prefix) :].strip()
        if mentioned and not text.strip() and not unsupported_types:
            text = "用户在群聊里@了你，但没有附加文字。请用当前角色自然回应。"
        scope = MessageScope(message_type="group", group_id=group_id, user_id=user_id)
    else:
        text = plain_text.strip()
        scope = MessageScope(message_type="private", user_id=user_id)

    return IncomingMessage(
        message_id=payload.get("message_id"),
        scope=scope,
        raw_text=plain_text.strip(),
        text=text.strip(),
        sender_nickname=sender.get("nickname") or sender.get("card"),
        raw_event=payload,
        unsupported_content_types=unsupported_types,
    )


MessageHandler = Callable[[IncomingMessage], Awaitable[str | None]]


class NapCatClient:
    def __init__(
        self,
        *,
        ws_url: str,
        self_id: int | None,
        prefix: str,
        handler: MessageHandler,
    ) -> None:
        self.ws_url = ws_url
        self.self_id = self_id
        self.prefix = prefix
        self.handler = handler
        self._websocket: Any | None = None
        self._send_lock = asyncio.Lock()

    async def run_forever(self) -> None:
        while True:
            try:
                await self._run_once()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("NapCat connection failed; retrying in 5 seconds")
                await asyncio.sleep(5)

    async def _run_once(self) -> None:
        async with websockets.connect(self.ws_url) as websocket:
            self._websocket = websocket
            logger.info("connected to NapCat at %s", self.ws_url)
            async for raw in websocket:
                await self._handle_raw(raw)

    async def _handle_raw(self, raw: str | bytes) -> None:
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            logger.warning("ignored non-json websocket payload")
            return
        if "echo" in payload and "status" in payload:
            return

        incoming = parse_message_event(payload, self_id=self.self_id, prefix=self.prefix)
        if incoming is None:
            return
        try:
            reply = await self.handler(incoming)
        except Exception:
            logger.exception("message handler failed")
            reply = "处理消息时出错了。"
        if reply:
            await self.send_reply(incoming, reply)

    async def send_reply(self, incoming: IncomingMessage, message: str) -> None:
        if incoming.scope.message_type == "group":
            await self.call_api(
                "send_group_msg",
                {"group_id": incoming.scope.group_id, "message": message},
            )
        else:
            await self.call_api(
                "send_private_msg",
                {"user_id": incoming.scope.user_id, "message": message},
            )

    async def call_api(self, action: str, params: dict[str, Any]) -> None:
        if self._websocket is None:
            raise RuntimeError("NapCat websocket is not connected")
        payload = {"action": action, "params": params, "echo": str(uuid.uuid4())}
        async with self._send_lock:
            await self._websocket.send(json.dumps(payload, ensure_ascii=False))
