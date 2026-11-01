from __future__ import annotations

import json
from collections import deque
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .config import app_data_dir


@dataclass(frozen=True, slots=True)
class Message:
    role: str
    content: str


class ConversationMemory:
    def __init__(self, path: Path | None = None, max_messages: int = 20) -> None:
        self.path = path or app_data_dir() / "history.jsonl"
        self.max_messages = max_messages

    def append(self, role: str, content: str) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        record = {
            "timestamp": datetime.now().astimezone().isoformat(timespec="seconds"),
            "role": role,
            "content": content,
        }
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")

    def recent(self) -> list[Message]:
        if not self.path.exists():
            return []
        messages: deque[Message] = deque(maxlen=self.max_messages)
        try:
            with self.path.open("r", encoding="utf-8") as handle:
                for line in handle:
                    try:
                        item = json.loads(line)
                        role = item.get("role")
                        content = item.get("content")
                        if role in {"user", "assistant"} and isinstance(content, str):
                            messages.append(Message(role, content))
                    except (json.JSONDecodeError, TypeError):
                        continue
        except OSError:
            return []
        return list(messages)

    def clear(self) -> None:
        if self.path.exists():
            self.path.unlink()

