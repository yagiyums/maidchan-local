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


def test_voice_conversation_is_stored_and_reused(tmp_path: Path) -> None:
    config = AppConfig(save_history=True, memory_max_messages=60)
    memory = ConversationMemory(tmp_path / "history.jsonl", max_messages=60)
    assistant = LocalAssistant(config, memory)
    requests: list[list[dict[str, str]]] = []

    def chat(messages: list[dict[str, str]]) -> str:
        requests.append(messages)
        return "承知しました。"

    assistant.client.chat = chat
    assistant.reply("好きな色は青です", input_source="voice")
    assistant.reply("私の好きな色を覚えていますか", input_source="voice")

    stored = memory.recent()
    assert stored[0].content == "好きな色は青です"
    assert stored[0].source == "voice"
    assert any(
        message["content"] == "[音声入力の文字起こし] 好きな色は青です"
        for message in requests[1]
    )


def test_maidchan_name_is_resolved_as_self_reference(tmp_path: Path) -> None:
    config = AppConfig(save_history=False)
    assistant = LocalAssistant(config, ConversationMemory(tmp_path / "history.jsonl"))
    requests: list[list[dict[str, str]]] = []

    def chat(messages: list[dict[str, str]]) -> str:
        requests.append(messages)
        return "私はローカルAIメイドです。"

    assistant.client.chat = chat
    assistant.reply("メイドちゃんは何ができるの？", input_source="voice")

    system_prompt = requests[0][0]["content"]
    user_prompt = requests[0][-1]["content"]
    assert "あなた自身" in system_prompt
    assert "一人称の「私」" in system_prompt
    assert "あなた自身を指す呼び名" in user_prompt
    assert "音声入力の文字起こし" in user_prompt

