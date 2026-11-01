from pathlib import Path

from maidchan.assistant import LocalAssistant, OllamaError
from maidchan.config import AppConfig
from maidchan.memory import ConversationMemory


def make_assistant(tmp_path: Path) -> LocalAssistant:
    config = AppConfig(save_history=True)
    memory = ConversationMemory(tmp_path / "history.jsonl")
    assistant = LocalAssistant(config, memory)
    assistant.client.chat = lambda _messages: (_ for _ in ()).throw(OllamaError("offline"))
    return assistant


def test_offline_identity_reply(tmp_path: Path) -> None:
    reply = make_assistant(tmp_path).reply("あなたは誰？")
    assert reply.source == "offline"
    assert "ローカル専用メイド" in reply.text


def test_clear_command_removes_history(tmp_path: Path) -> None:
    assistant = make_assistant(tmp_path)
    assistant.memory.append("user", "hello")
    reply = assistant.reply("/clear")
    assert reply.source == "command"
    assert assistant.memory.recent() == []


def test_help_command_does_not_call_model(tmp_path: Path) -> None:
    reply = make_assistant(tmp_path).reply("/help")
    assert reply.source == "command"
    assert "/status" in reply.text

