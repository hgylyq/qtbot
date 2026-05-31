from __future__ import annotations

from dataclasses import replace
import shlex
from typing import Protocol

from .agent import MainAgent
from .memory import MemoryStore
from .models import AgentReply, IncomingMessage, RoleCard
from .roles import RoleCardGenerator, RoleStore


class SupportsRoleGeneration(Protocol):
    async def generate(self, *, role_id: str, description: str, created_by: int) -> RoleCard: ...


class BotController:
    def __init__(
        self,
        *,
        role_store: RoleStore,
        role_generator: RoleCardGenerator | SupportsRoleGeneration,
        main_agent: MainAgent,
        memory: MemoryStore,
        owner_ids: set[int],
        prefix: str = "/",
    ) -> None:
        self.role_store = role_store
        self.role_generator = role_generator
        self.main_agent = main_agent
        self.memory = memory
        self.owner_ids = owner_ids
        self.prefix = prefix

    async def handle(self, incoming: IncomingMessage) -> str | None:
        text = incoming.text.strip()
        if not text and incoming.unsupported_content_types:
            incoming = replace(incoming, text=self._unsupported_content_prompt(incoming.unsupported_content_types))
            text = incoming.text.strip()
        if not text:
            return None
        command = self._command_text(text)
        if command is not None:
            handled = await self._handle_command(incoming, command)
            if handled is not None:
                return handled

        role = self.role_store.get_active(incoming.scope)
        reply = await self.main_agent.reply(incoming=incoming, role=role)
        await self._remember(incoming, role, reply)
        return reply.text

    def _command_text(self, text: str) -> str | None:
        if text.startswith(self.prefix):
            return text[len(self.prefix) :].strip()
        for name in (
            "帮助",
            "指令",
            "help",
            "角色列表",
            "角色查看",
            "角色切换",
            "角色生成",
            "角色编辑",
            "角色删除",
            "搜",
            "清除context",
            "清空context",
            "清除上下文",
            "清空上下文",
            "清除memory",
            "清空memory",
            "清除记忆",
            "清空记忆",
            "清除全部",
            "清空全部",
        ):
            if text == name or text.startswith(name + " "):
                return text
        return None

    async def _handle_command(self, incoming: IncomingMessage, command: str) -> str | None:
        normalized = self._normalize_command(command)
        if normalized in {"帮助", "指令", "help"}:
            return self._help()
        if command == "角色列表":
            return self._list_roles()
        if command.startswith("角色查看"):
            return self._show_role(command)
        if command == "搜" or command.startswith("搜 "):
            return await self._search_command(incoming, command[2:].strip())
        if normalized in {"清除context", "清空context", "清除上下文", "清空上下文"}:
            return await self._clear_context_command(incoming)
        if normalized in {"清除memory", "清空memory", "清除记忆", "清空记忆"}:
            return await self._clear_memory_command(incoming)
        if normalized in {"清除全部", "清空全部", "清除all", "清空all"}:
            return await self._clear_all_memory_command(incoming)

        if command.startswith(("角色切换", "角色生成", "角色编辑", "角色删除")):
            if incoming.scope.user_id not in self.owner_ids:
                return "没有权限管理角色卡。"
            if command.startswith("角色切换"):
                return self._switch_role(incoming, command)
            if command.startswith("角色生成"):
                return await self._generate_role(incoming, command)
            if command.startswith("角色编辑"):
                return self._edit_role(command)
            if command.startswith("角色删除"):
                return self._delete_role(command)
        return None

    @staticmethod
    def _normalize_command(command: str) -> str:
        return "".join(command.lower().split())

    @staticmethod
    def _unsupported_content_prompt(types: tuple[str, ...]) -> str:
        labels = BotController._unsupported_content_labels(types)
        return (
            f"用户发送了{labels}，但当前模型不能查看非文本内容。"
            "请不要猜测内容，用当前角色简短说明只能处理文字，并请对方用文字描述。"
        )

    @staticmethod
    def _unsupported_content_labels(types: tuple[str, ...]) -> str:
        names = {
            "image": "图片",
            "record": "语音",
            "video": "视频",
            "file": "文件",
            "forward": "合并转发",
        }
        labels = [names.get(item, item) for item in types]
        return "、".join(labels) if labels else "非文本内容"

    def _list_roles(self) -> str:
        roles = self.role_store.list_roles()
        lines = ["角色卡："]
        for role in roles:
            lines.append(f"- {role.id}: {role.name}")
        return "\n".join(lines)

    def _help(self) -> str:
        return "\n".join(
            [
                "可用指令：",
                "/帮助",
                "/角色列表",
                "/角色查看 <id>",
                "/角色切换 <id>",
                "/角色生成 <id> <设定描述>",
                "/角色编辑 <id> <field> <content>",
                "/角色删除 <id>",
                "/搜 <query>",
                "/清除context",
                "/清除memory",
                "/清除全部",
                "",
                "权限：角色生成、编辑、删除、切换需要管理员；其他指令只作用于当前聊天对象。",
            ]
        )

    def _show_role(self, command: str) -> str:
        parts = command.split(maxsplit=1)
        role_id = parts[1].strip() if len(parts) > 1 else ""
        if not role_id:
            return "用法：/角色查看 <id>"
        try:
            role = self.role_store.load(role_id)
        except KeyError:
            return f"角色不存在：{role_id}"
        return "\n".join(
            [
                f"{role.id}: {role.name}",
                f"设定：{role.persona}",
                f"语气：{role.speaking_style}",
                f"联网风格：{role.search_style}",
            ]
        )

    def _switch_role(self, incoming: IncomingMessage, command: str) -> str:
        parts = command.split(maxsplit=1)
        if len(parts) < 2:
            return "用法：/角色切换 <id>"
        role_id = parts[1].strip()
        try:
            role = self.role_store.load(role_id)
        except KeyError:
            return f"角色不存在：{role_id}"
        self.role_store.set_active(incoming.scope, role.id)
        return f"已切换到角色：{role.id}（{role.name}）"

    async def _generate_role(self, incoming: IncomingMessage, command: str) -> str:
        parts = command.split(maxsplit=2)
        if len(parts) < 3:
            return "用法：/角色生成 <id> <设定描述>"
        role_id, description = parts[1], parts[2]
        role = await self.role_generator.generate(
            role_id=role_id,
            description=description,
            created_by=incoming.scope.user_id,
        )
        self.role_store.save(role)
        return f"已生成角色：{role.id}（{role.name}）"

    def _edit_role(self, command: str) -> str:
        try:
            parts = shlex.split(command)
        except ValueError:
            parts = command.split(maxsplit=3)
        if len(parts) < 4:
            return "用法：/角色编辑 <id> <field> <content>"
        _, role_id, field, content = parts[0], parts[1], parts[2], " ".join(parts[3:])
        allowed = {"name", "persona", "speaking_style", "search_style", "memory_notes"}
        list_fields = {"rules", "forbidden"}
        try:
            role = self.role_store.load(role_id)
        except KeyError:
            return f"角色不存在：{role_id}"
        if field in allowed:
            setattr(role, field, content)
        elif field in list_fields:
            setattr(role, field, [item.strip() for item in content.split("|") if item.strip()])
        else:
            return "可编辑字段：name, persona, speaking_style, search_style, memory_notes, rules, forbidden"
        self.role_store.save(role)
        return f"已更新角色：{role.id}"

    def _delete_role(self, command: str) -> str:
        parts = command.split(maxsplit=1)
        if len(parts) < 2:
            return "用法：/角色删除 <id>"
        role_id = parts[1].strip()
        try:
            self.role_store.delete(role_id)
        except KeyError:
            return f"角色不存在：{role_id}"
        except ValueError as exc:
            return str(exc)
        return f"已删除角色：{role_id}"

    async def _search_command(self, incoming: IncomingMessage, query: str) -> str:
        if not query:
            return "用法：/搜 <query>"
        role = self.role_store.get_active(incoming.scope)
        search_incoming = replace(incoming, text=query)
        reply = await self.main_agent.reply(incoming=search_incoming, role=role, force_search_query=query)
        await self._remember(incoming, role, reply)
        return reply.text

    async def _clear_context_command(self, incoming: IncomingMessage) -> str:
        role = self.role_store.get_active(incoming.scope)
        await self.memory.clear_dialogue_context(role_id=role.id, room=incoming.scope.room)
        return f"已清空当前 context：角色 {role.id}，当前聊天对象。"

    async def _clear_memory_command(self, incoming: IncomingMessage) -> str:
        role = self.role_store.get_active(incoming.scope)
        result = await self.memory.clear_memory(role_id=role.id, room=incoming.scope.room)
        return self._clear_memory_reply("已清除当前 memory", role.id, result)

    async def _clear_all_memory_command(self, incoming: IncomingMessage) -> str:
        role = self.role_store.get_active(incoming.scope)
        await self.memory.clear_dialogue_context(role_id=role.id, room=incoming.scope.room)
        result = await self.memory.clear_memory(role_id=role.id, room=incoming.scope.room)
        return self._clear_memory_reply("已清空当前 context 和 memory", role.id, result)

    @staticmethod
    def _clear_memory_reply(prefix: str, role_id: str, result) -> str:
        lines = [
            f"{prefix}：角色 {role_id}，当前聊天对象。",
            f"本地记录：{result.local_files_deleted} 个。",
        ]
        if result.mempalace_error:
            lines.append(f"MemPalace：清理失败（{result.mempalace_error}）。")
        elif result.mempalace_records_deleted is None:
            lines.append("MemPalace：未启用。")
        else:
            lines.append(f"MemPalace：{result.mempalace_records_deleted} 条。")
        return "\n".join(lines)

    async def _remember(self, incoming: IncomingMessage, role: RoleCard, reply: AgentReply) -> None:
        await self.memory.record_interaction(
            role_id=role.id,
            room=incoming.scope.room,
            user_text=incoming.text,
            bot_text=reply.text,
            search_brief=reply.search_brief,
        )
        await self.main_agent.compact_dialogue_if_needed(role_id=role.id, room=incoming.scope.room)
