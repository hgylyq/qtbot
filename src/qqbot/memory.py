from __future__ import annotations

import asyncio
import contextlib
from dataclasses import dataclass
import hashlib
import json
import logging
import os
import re
import threading
from datetime import datetime, timezone
from pathlib import Path

from .models import DialogueContext, DialogueTurn, MemoryHit, SearchBrief

logger = logging.getLogger(__name__)
_MEMPALACE_ENV_LOCK = threading.Lock()


@dataclass(frozen=True)
class ClearMemoryResult:
    local_files_deleted: int
    mempalace_records_deleted: int | None = None
    mempalace_error: str | None = None


class MemoryStore:
    def __init__(
        self,
        *,
        palace_path: Path,
        transcripts_dir: Path,
        n_results: int = 5,
        auto_mine: bool = True,
        enable_mempalace: bool = True,
    ) -> None:
        self.palace_path = palace_path
        self.transcripts_dir = transcripts_dir
        self.n_results = n_results
        self.auto_mine = auto_mine
        self.enable_mempalace = enable_mempalace
        self.palace_path.mkdir(parents=True, exist_ok=True)
        self.pending_dir.mkdir(parents=True, exist_ok=True)
        self.archive_dir.mkdir(parents=True, exist_ok=True)
        self.dialogue_dir.mkdir(parents=True, exist_ok=True)
        self.context_dir.mkdir(parents=True, exist_ok=True)

    @property
    def pending_dir(self) -> Path:
        return self.transcripts_dir / "pending"

    @property
    def archive_dir(self) -> Path:
        return self.transcripts_dir / "archive"

    @property
    def dialogue_dir(self) -> Path:
        return self.transcripts_dir / "dialogue"

    @property
    def context_dir(self) -> Path:
        return self.transcripts_dir / "context"

    async def search(self, *, query: str, role_id: str, room: str) -> list[MemoryHit]:
        if not query.strip():
            return []
        if self.enable_mempalace:
            try:
                return await asyncio.to_thread(
                    self._search_mempalace,
                    query,
                    role_id,
                    room,
                )
            except ImportError:
                logger.info("mempalace package is not installed; using local transcript fallback")
            except Exception:
                logger.exception("mempalace search failed; using local transcript fallback")
        return await asyncio.to_thread(self._fallback_search, query, role_id, room)

    def _search_mempalace(self, query: str, role_id: str, room: str) -> list[MemoryHit]:
        with self._mempalace_env():
            from mempalace.searcher import search_memories

            result = search_memories(
                query=query,
                palace_path=str(self.palace_path.resolve()),
                wing=role_id,
                room=room,
                n_results=self.n_results,
                candidate_strategy="union",
            )
        hits = []
        for item in result.get("results", []):
            if "text" not in item:
                item = {**item, "text": item.get("content") or item.get("document") or ""}
            hits.append(MemoryHit.model_validate(item))
        return hits

    async def record_interaction(
        self,
        *,
        role_id: str,
        room: str,
        user_text: str,
        bot_text: str,
        search_brief: SearchBrief | None = None,
    ) -> Path:
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        created_at = datetime.now(timezone.utc).isoformat()
        safe_room = "".join(ch if ch.isalnum() or ch in "_-" else "_" for ch in room)
        path = self.pending_dir / f"{timestamp}_{role_id}_{safe_room}.md"
        parts = [
            "---",
            f"wing: {role_id}",
            f"room: {room}",
            f"created_at: {created_at}",
            "---",
            "",
            f"User: {user_text}",
            "",
        ]
        if search_brief is not None:
            parts.extend(
                [
                    "Search summary:",
                    search_brief.summary,
                    "",
                    "Search sources:",
                    *search_brief.source_urls,
                    "",
                ]
            )
        parts.extend(["Bot:", bot_text, ""])
        content = "\n".join(parts)
        path.write_text(content, encoding="utf-8")
        if self.auto_mine and self.enable_mempalace:
            stored = await asyncio.to_thread(
                self._write_mempalace_drawer,
                role_id,
                room,
                content,
                path,
            )
            if stored:
                target = self.archive_dir / path.name
                path.replace(target)
                self._append_dialogue_turn(
                    role_id=role_id,
                    room=room,
                    user_text=user_text,
                    bot_text=bot_text,
                    created_at=created_at,
                    source_file=target,
                )
                self._append_dialogue_context_turn(
                    role_id=role_id,
                    room=room,
                    user_text=user_text,
                    bot_text=bot_text,
                    created_at=created_at,
                    source_file=target,
                )
                return target
        self._append_dialogue_turn(
            role_id=role_id,
            room=room,
            user_text=user_text,
            bot_text=bot_text,
            created_at=created_at,
            source_file=path,
        )
        self._append_dialogue_context_turn(
            role_id=role_id,
            room=room,
            user_text=user_text,
            bot_text=bot_text,
            created_at=created_at,
            source_file=path,
        )
        return path

    async def dialogue_context(self, *, role_id: str, room: str) -> DialogueContext:
        return await asyncio.to_thread(self._load_dialogue_context, role_id, room)

    async def replace_dialogue_context(
        self,
        *,
        role_id: str,
        room: str,
        compacted: str,
        turns: list[DialogueTurn] | None = None,
    ) -> DialogueContext:
        context = DialogueContext(
            role_id=role_id,
            room=room,
            compacted=compacted.strip(),
            turns=turns or [],
            updated_at=datetime.now(timezone.utc).isoformat(),
        )
        await asyncio.to_thread(self._save_dialogue_context, context)
        return context

    async def clear_dialogue_context(self, *, role_id: str, room: str) -> None:
        await asyncio.to_thread(self._clear_dialogue_context, role_id, room)

    async def clear_memory(self, *, role_id: str, room: str) -> ClearMemoryResult:
        return await asyncio.to_thread(self._clear_memory, role_id, room)

    async def mine_pending_file(self, path: Path, *, role_id: str, room: str) -> bool:
        if not path.exists() or not self.enable_mempalace:
            return False
        content = path.read_text(encoding="utf-8", errors="replace")
        stored = await asyncio.to_thread(self._write_mempalace_drawer, role_id, room, content, path)
        if stored:
            target = self.archive_dir / path.name
            path.replace(target)
            return True
        return False

    def _write_mempalace_drawer(self, role_id: str, room: str, content: str, source_file: Path) -> bool:
        try:
            with self._mempalace_env():
                from mempalace.miner import detect_hall
                from mempalace.palace import NORMALIZE_VERSION, get_collection

                collection = get_collection(str(self.palace_path.resolve()), create=True)
                drawer_id = self._drawer_id(role_id, room, content)
                collection.upsert(
                    ids=[drawer_id],
                    documents=[content],
                    metadatas=[
                        {
                            "wing": role_id,
                            "room": room,
                            "hall": detect_hall(content),
                            "source_file": str(source_file.resolve()),
                            "chunk_index": 0,
                            "added_by": "qqbot",
                            "filed_at": datetime.now(timezone.utc).isoformat(),
                            "ingest_mode": "qqbot",
                            "normalize_version": NORMALIZE_VERSION,
                        }
                    ],
                )
            return True
        except ImportError:
            logger.info("mempalace package is not installed; pending transcript kept at %s", source_file)
        except Exception:
            logger.exception("mempalace drawer write failed; pending transcript kept at %s", source_file)
        return False

    def _fallback_search(self, query: str, role_id: str, room: str) -> list[MemoryHit]:
        terms = [term.lower() for term in query.split() if term.strip()]
        if not terms:
            return []
        hits: list[MemoryHit] = []
        for base in [self.pending_dir, self.archive_dir]:
            for path in sorted(base.glob(f"*_{role_id}_{self._safe_room(room)}.md"), reverse=True):
                text = path.read_text(encoding="utf-8", errors="ignore")
                score = sum(1 for term in terms if term in text.lower())
                if score:
                    hits.append(
                        MemoryHit(
                            text=text[:1200],
                            wing=role_id,
                            room=room,
                            source_file=str(path),
                            similarity=float(score),
                        )
                    )
                if len(hits) >= self.n_results:
                    return hits
        return hits

    def _append_dialogue_turn(
        self,
        *,
        role_id: str,
        room: str,
        user_text: str,
        bot_text: str,
        created_at: str,
        source_file: Path,
    ) -> None:
        path = self._dialogue_path(role_id, room)
        record = DialogueTurn(
            user_text=user_text,
            bot_text=bot_text,
            created_at=created_at,
            source_file=str(source_file.resolve()),
        )
        with path.open("a", encoding="utf-8") as handle:
            handle.write(record.model_dump_json() + "\n")

    def _append_dialogue_context_turn(
        self,
        *,
        role_id: str,
        room: str,
        user_text: str,
        bot_text: str,
        created_at: str,
        source_file: Path,
    ) -> None:
        context = self._load_dialogue_context(role_id, room, migrate_from_jsonl=False)
        context.turns.append(
            DialogueTurn(
                user_text=user_text,
                bot_text=bot_text,
                created_at=created_at,
                source_file=str(source_file.resolve()),
            )
        )
        context.updated_at = datetime.now(timezone.utc).isoformat()
        self._save_dialogue_context(context)

    def _load_dialogue_context(self, role_id: str, room: str, *, migrate_from_jsonl: bool = True) -> DialogueContext:
        path = self._dialogue_context_path(role_id, room)
        if path.exists():
            try:
                return DialogueContext.model_validate_json(path.read_text(encoding="utf-8", errors="replace"))
            except ValueError:
                logger.warning("ignored invalid dialogue context file: %s", path)
        return DialogueContext(
            role_id=role_id,
            room=room,
            turns=self._recent_dialogue(role_id, room, 50) if migrate_from_jsonl else [],
            updated_at=datetime.now(timezone.utc).isoformat(),
        )

    def _save_dialogue_context(self, context: DialogueContext) -> None:
        path = self._dialogue_context_path(context.role_id, context.room)
        path.write_text(context.model_dump_json(indent=2), encoding="utf-8")

    def _clear_dialogue_context(self, role_id: str, room: str) -> None:
        context = DialogueContext(
            role_id=role_id,
            room=room,
            updated_at=datetime.now(timezone.utc).isoformat(),
        )
        self._save_dialogue_context(context)

    def _clear_memory(self, role_id: str, room: str) -> ClearMemoryResult:
        local_files_deleted = self._delete_local_memory_files(role_id, room)
        mempalace_records_deleted: int | None = None
        mempalace_error: str | None = None
        if self.enable_mempalace:
            try:
                mempalace_records_deleted = self._delete_mempalace_records(role_id, room)
            except ImportError:
                logger.info("mempalace package is not installed; skipped mempalace cleanup")
                mempalace_error = "mempalace package is not installed"
            except Exception as exc:
                logger.exception("mempalace cleanup failed")
                mempalace_error = str(exc)
        return ClearMemoryResult(
            local_files_deleted=local_files_deleted,
            mempalace_records_deleted=mempalace_records_deleted,
            mempalace_error=mempalace_error,
        )

    def _delete_local_memory_files(self, role_id: str, room: str) -> int:
        deleted = 0
        pattern = f"*_{role_id}_{self._safe_room(room)}.md"
        for base in [self.pending_dir, self.archive_dir]:
            for path in base.glob(pattern):
                if path.is_file():
                    path.unlink()
                    deleted += 1
        dialogue_path = self._dialogue_path(role_id, room)
        if dialogue_path.is_file():
            dialogue_path.unlink()
            deleted += 1
        return deleted

    def _delete_mempalace_records(self, role_id: str, room: str) -> int:
        with self._mempalace_env():
            from mempalace.palace import get_collection

            collection = get_collection(str(self.palace_path.resolve()), create=False)
            where = {"$and": [{"wing": role_id}, {"room": room}]}
            ids: list[str] = []
            offset = 0
            page_size = 500
            while True:
                result = collection.get(where=where, include=[], limit=page_size, offset=offset)
                batch_ids = self._collection_result_ids(result)
                if not batch_ids:
                    break
                ids.extend(batch_ids)
                if len(batch_ids) < page_size:
                    break
                offset += len(batch_ids)
            for index in range(0, len(ids), page_size):
                collection.delete(ids=ids[index : index + page_size])
        return len(ids)

    def _recent_dialogue(self, role_id: str, room: str, limit: int) -> list[DialogueTurn]:
        turns = self._recent_dialogue_from_jsonl(role_id, room, limit)
        seen = {turn.source_file for turn in turns if turn.source_file}
        for turn in self._recent_dialogue_from_transcripts(role_id, room, limit):
            if turn.source_file in seen:
                continue
            turns.append(turn)
            if turn.source_file:
                seen.add(turn.source_file)
        turns.sort(key=self._dialogue_sort_key)
        return turns[-limit:]

    def _recent_dialogue_from_jsonl(self, role_id: str, room: str, limit: int) -> list[DialogueTurn]:
        path = self._dialogue_path(role_id, room)
        if not path.exists():
            return []
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        turns: list[DialogueTurn] = []
        for line in lines[-limit:]:
            if not line.strip():
                continue
            try:
                turns.append(DialogueTurn.model_validate(json.loads(line)))
            except (json.JSONDecodeError, ValueError):
                logger.warning("ignored invalid dialogue cache line in %s", path)
        return turns

    def _recent_dialogue_from_transcripts(self, role_id: str, room: str, limit: int) -> list[DialogueTurn]:
        pattern = f"*_{role_id}_{self._safe_room(room)}.md"
        paths: list[Path] = []
        for base in [self.pending_dir, self.archive_dir]:
            paths.extend(base.glob(pattern))
        turns: list[DialogueTurn] = []
        for path in sorted(paths)[-limit:]:
            turn = self._parse_transcript_turn(path)
            if turn is not None:
                turns.append(turn)
        return turns

    def _parse_transcript_turn(self, path: Path) -> DialogueTurn | None:
        text = path.read_text(encoding="utf-8", errors="replace")
        match = re.search(r"(?ms)^User:\s*(.*?)(?:\n\nSearch summary:|\n\nBot:)", text)
        bot_marker = "\nBot:\n"
        if match is None or bot_marker not in text:
            return None
        created_at_match = re.search(r"(?m)^created_at:\s*(.+)$", text)
        bot_text = text.split(bot_marker, 1)[1].strip()
        return DialogueTurn(
            user_text=match.group(1).strip(),
            bot_text=bot_text,
            created_at=created_at_match.group(1).strip() if created_at_match else None,
            source_file=str(path.resolve()),
        )

    def _dialogue_path(self, role_id: str, room: str) -> Path:
        return self.dialogue_dir / f"{role_id}_{self._safe_room(room)}.jsonl"

    def _dialogue_context_path(self, role_id: str, room: str) -> Path:
        return self.context_dir / f"{role_id}_{self._safe_room(room)}.json"

    @staticmethod
    def _dialogue_sort_key(turn: DialogueTurn) -> str:
        return turn.created_at or turn.source_file or ""

    @staticmethod
    def _collection_result_ids(result) -> list[str]:
        if isinstance(result, dict):
            return list(result.get("ids") or [])
        return list(getattr(result, "ids", []) or [])

    @staticmethod
    def _safe_room(room: str) -> str:
        return "".join(ch if ch.isalnum() or ch in "_-" else "_" for ch in room)

    @staticmethod
    def _drawer_id(role_id: str, room: str, content: str) -> str:
        digest = hashlib.sha256(f"{role_id}|{room}|{content}".encode("utf-8")).hexdigest()[:24]
        return f"drawer_{role_id}_{room}_{digest}"

    @contextlib.contextmanager
    def _mempalace_env(self):
        home = (self.palace_path.parent / ".mempalace_home").resolve()
        home.mkdir(parents=True, exist_ok=True)
        palace = str(self.palace_path.resolve())
        old_env = {
            "HOME": os.environ.get("HOME"),
            "USERPROFILE": os.environ.get("USERPROFILE"),
            "XDG_CACHE_HOME": os.environ.get("XDG_CACHE_HOME"),
            "MEMPALACE_PALACE_PATH": os.environ.get("MEMPALACE_PALACE_PATH"),
        }
        with _MEMPALACE_ENV_LOCK:
            os.environ["HOME"] = str(home)
            os.environ["USERPROFILE"] = str(home)
            os.environ["XDG_CACHE_HOME"] = str(home / ".cache")
            os.environ["MEMPALACE_PALACE_PATH"] = palace
            try:
                yield
            finally:
                for key, value in old_env.items():
                    if value is None:
                        os.environ.pop(key, None)
                    else:
                        os.environ[key] = value


def memory_hits_to_prompt(hits: list[MemoryHit]) -> str:
    if not hits:
        return "No relevant long-term memory found."
    rendered: list[str] = []
    for index, hit in enumerate(hits, start=1):
        rendered.append(f"[{index}] {hit.text.strip()}")
    return "\n\n".join(rendered)


def dialogue_turns_to_prompt(turns: list[DialogueTurn]) -> str:
    if not turns:
        return "No recent raw dialogue found."
    rendered: list[str] = []
    for index, turn in enumerate(turns, start=1):
        rendered.append(
            "\n".join(
                [
                    f"[{index}] User: {turn.user_text.strip()}",
                    f"[{index}] Bot: {turn.bot_text.strip()}",
                ]
            )
        )
    return "\n\n".join(rendered)


def dialogue_context_to_prompt(context: DialogueContext) -> str:
    parts: list[str] = []
    if context.compacted.strip():
        parts.extend(["Compacted previous dialogue:", context.compacted.strip(), ""])
    else:
        parts.extend(["Compacted previous dialogue:", "None yet.", ""])
    parts.extend(["Raw dialogue after the latest compact:", dialogue_turns_to_prompt(context.turns)])
    return "\n".join(parts).strip()


def dialogue_context_to_compact_source(context: DialogueContext) -> str:
    return "\n".join(
        [
            "Existing compacted dialogue:",
            context.compacted.strip() or "None.",
            "",
            "Raw dialogue to compact:",
            dialogue_turns_to_prompt(context.turns),
        ]
    ).strip()
