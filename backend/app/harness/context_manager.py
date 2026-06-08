"""
AI Harness: Context Manager
管理对话上下文、Token 预算、历史裁剪
"""
from dataclasses import dataclass, field
from typing import Any
import tiktoken


TOKEN_LIMIT = 8000        # 保留给输出的安全上限
RESERVE_FOR_OUTPUT = 1000


@dataclass
class ContextMessage:
    role: str         # "user" | "assistant" | "system"
    content: str
    metadata: dict = field(default_factory=dict)


class ContextManager:
    """
    对话上下文管理器
    - 维护消息历史
    - Token 计数与裁剪
    - 注入角色记忆和场景信息
    """

    def __init__(self, max_tokens: int = TOKEN_LIMIT):
        self.max_tokens = max_tokens
        self.reserve = RESERVE_FOR_OUTPUT
        self._history: list[ContextMessage] = []
        try:
            self._enc = tiktoken.encoding_for_model("gpt-4o")
        except Exception:
            self._enc = None

    def count_tokens(self, text: str) -> int:
        if self._enc:
            return len(self._enc.encode(text))
        return len(text) // 4  # 粗估

    def add(self, role: str, content: str, metadata: dict | None = None):
        self._history.append(ContextMessage(role=role, content=content, metadata=metadata or {}))

    def build_messages(
        self,
        system_prompt: str,
        new_user_message: str,
        character_memory: str = "",
    ) -> list[dict]:
        """
        构建发送给模型的消息列表，自动裁剪超出 Token 的历史
        """
        budget = self.max_tokens - self.reserve

        # 系统 Prompt + 角色记忆
        if character_memory:
            full_system = system_prompt + f"\n\n## 角色记忆档案\n{character_memory}"
        else:
            full_system = system_prompt

        system_tokens = self.count_tokens(full_system)
        new_msg_tokens = self.count_tokens(new_user_message)
        available = budget - system_tokens - new_msg_tokens

        # 从最新的历史开始裁剪
        selected: list[ContextMessage] = []
        used = 0
        for msg in reversed(self._history):
            t = self.count_tokens(msg.content)
            if used + t > available:
                break
            selected.insert(0, msg)
            used += t

        messages: list[dict] = []
        for m in selected:
            speaker = (m.metadata or {}).get("character_name", "")
            content = f"[{speaker}]: {m.content}" if speaker else m.content
            messages.append({"role": m.role, "content": content})
        messages.append({"role": "user", "content": new_user_message})

        return messages, full_system

    def get_recent(self, n: int = 5) -> list[ContextMessage]:
        return self._history[-n:]

    def clear(self):
        self._history.clear()

    def to_text(self, n: int = 10) -> str:
        """将最近 n 条历史转为可读文本"""
        lines = []
        for m in self._history[-n:]:
            speaker = m.metadata.get("character_name", m.role)
            lines.append(f"[{speaker}]: {m.content}")
        return "\n".join(lines)


# 每个对话 ID 对应一个 ContextManager
_context_store: dict[int, ContextManager] = {}


def get_context(conversation_id: int) -> ContextManager:
    if conversation_id not in _context_store:
        _context_store[conversation_id] = ContextManager()
    return _context_store[conversation_id]


def clear_context(conversation_id: int):
    _context_store.pop(conversation_id, None)
