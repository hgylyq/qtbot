from __future__ import annotations

import json
import logging
import re
from typing import Any

import httpx


logger = logging.getLogger(__name__)


class LLMError(RuntimeError):
    pass


class OpenAIChatClient:
    def __init__(
        self,
        *,
        api_key: str | None,
        base_url: str | None,
        default_model: str,
    ) -> None:
        self.api_key = api_key
        self.base_url = base_url
        self.default_model = default_model

    async def complete(
        self,
        messages: list[dict[str, str]],
        *,
        model: str | None = None,
        temperature: float = 0.7,
    ) -> str:
        if not self.api_key:
            raise LLMError("OPENAI_API_KEY is not configured")
        url = self._chat_completions_url()
        payload = {
            "model": model or self.default_model,
            "messages": messages,
            "temperature": temperature,
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json; charset=utf-8",
        }
        body = json.dumps(payload, ensure_ascii=True).encode("utf-8")
        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.post(url, headers=headers, content=body)
        if response.status_code >= 400:
            raise LLMError(f"model endpoint returned HTTP {response.status_code}: {response.text[:500]}")

        data = response.json()
        self._log_usage(data, model or self.default_model)
        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMError(f"unexpected model response: {response.text[:500]}") from exc
        if not content:
            raise LLMError("model returned empty content")
        return content.strip()

    def _chat_completions_url(self) -> str:
        base_url = (self.base_url or "https://api.openai.com/v1").rstrip("/")
        if base_url.endswith("/chat/completions"):
            return base_url
        if not base_url.endswith("/v1"):
            base_url = f"{base_url}/v1"
        return f"{base_url}/chat/completions"

    @staticmethod
    def _log_usage(data: dict[str, Any], model: str) -> None:
        usage = data.get("usage")
        if not isinstance(usage, dict):
            return
        prompt_details = usage.get("prompt_tokens_details")
        if not isinstance(prompt_details, dict):
            prompt_details = usage.get("input_tokens_details")
        cached_tokens = prompt_details.get("cached_tokens") if isinstance(prompt_details, dict) else None
        logger.info(
            "llm usage model=%s prompt_tokens=%s cached_tokens=%s completion_tokens=%s total_tokens=%s",
            model,
            usage.get("prompt_tokens"),
            cached_tokens,
            usage.get("completion_tokens"),
            usage.get("total_tokens"),
        )

    async def complete_json(
        self,
        messages: list[dict[str, str]],
        *,
        model: str | None = None,
        temperature: float = 0.2,
    ) -> dict[str, Any]:
        content = await self.complete(messages, model=model, temperature=temperature)
        return parse_json_object(content)


def parse_json_object(text: str) -> dict[str, Any]:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    try:
        value = json.loads(cleaned)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", cleaned, flags=re.S)
        if not match:
            raise
        value = json.loads(match.group(0))
    if not isinstance(value, dict):
        raise ValueError("expected a JSON object")
    return value
