from __future__ import annotations

import logging
from functools import cached_property

logger = logging.getLogger(__name__)


class TokenCounter:
    def __init__(self, *, model: str | None = None, encoding_name: str = "cl100k_base") -> None:
        self.model = model
        self.encoding_name = encoding_name

    @cached_property
    def encoding(self):
        try:
            import tiktoken
        except ImportError:
            logger.warning("tiktoken is not installed; using approximate token counting")
            return None

        if self.model:
            try:
                return tiktoken.encoding_for_model(self.model)
            except KeyError:
                pass
        try:
            return tiktoken.get_encoding(self.encoding_name)
        except Exception:
            logger.exception("failed to load tokenizer encoding %s; using approximate token counting", self.encoding_name)
            return None

    def count_text(self, text: str) -> int:
        if not text:
            return 0
        if self.encoding is not None:
            return len(self.encoding.encode(text))
        return self._fallback_count_text(text)

    def count_messages(self, messages: list[dict[str, str]]) -> int:
        total = 2
        for message in messages:
            total += 4
            total += self.count_text(message.get("role", ""))
            total += self.count_text(message.get("content", ""))
        return total

    def truncate_text(self, text: str, max_tokens: int) -> str:
        if max_tokens <= 0:
            return ""
        if self.count_text(text) <= max_tokens:
            return text
        if self.encoding is not None:
            tokens = self.encoding.encode(text)
            return self.encoding.decode(tokens[:max_tokens]).rstrip()
        return self._fallback_truncate_text(text, max_tokens).rstrip()

    @staticmethod
    def _fallback_count_text(text: str) -> int:
        tokens = 0
        ascii_run = 0
        for ch in text:
            if ch.isspace():
                if ascii_run:
                    tokens += max(1, (ascii_run + 3) // 4)
                    ascii_run = 0
                continue
            if ord(ch) < 128:
                ascii_run += 1
                continue
            if ascii_run:
                tokens += max(1, (ascii_run + 3) // 4)
                ascii_run = 0
            tokens += 1
        if ascii_run:
            tokens += max(1, (ascii_run + 3) // 4)
        return tokens

    def _fallback_truncate_text(self, text: str, max_tokens: int) -> str:
        used = 0
        output: list[str] = []
        ascii_run: list[str] = []

        def flush_ascii() -> bool:
            nonlocal used
            if not ascii_run:
                return True
            chunk = "".join(ascii_run)
            cost = max(1, (len(chunk) + 3) // 4)
            if used + cost > max_tokens:
                return False
            output.append(chunk)
            ascii_run.clear()
            used += cost
            return True

        for ch in text:
            if ch.isspace():
                if not flush_ascii():
                    break
                output.append(ch)
                continue
            if ord(ch) < 128:
                ascii_run.append(ch)
                continue
            if not flush_ascii():
                break
            if used + 1 > max_tokens:
                break
            output.append(ch)
            used += 1
        flush_ascii()
        return "".join(output)
