from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime
from urllib.parse import urlparse

from .config import AppConfig
from .memory import ConversationMemory


class OllamaError(RuntimeError):
    """Raised when the local Ollama server cannot answer."""


@dataclass(frozen=True, slots=True)
class Reply:
    text: str
    source: str


class OllamaClient:
    def __init__(self, config: AppConfig) -> None:
        self.config = config
        parsed = urlparse(config.ollama_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("ollama_url must be an http(s) URL")

    def chat(self, messages: list[dict[str, str]]) -> str:
        endpoint = self.config.ollama_url.rstrip("/") + "/api/chat"
        payload = json.dumps(
            {
                "model": self.config.ollama_model,
                "messages": messages,
                "stream": False,
                "options": {"temperature": self.config.temperature},
            }
        ).encode("utf-8")
        request = urllib.request.Request(
            endpoint,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(
                request, timeout=self.config.request_timeout_seconds
            ) as response:
                body = json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
            raise OllamaError(str(exc)) from exc
        content = body.get("message", {}).get("content", "").strip()
        if not content:
            raise OllamaError("Ollama returned an empty response")
        return content

    def is_available(self) -> bool:
        endpoint = self.config.ollama_url.rstrip("/") + "/api/tags"
        try:
            with urllib.request.urlopen(endpoint, timeout=2) as response:
                return response.status == 200
        except (urllib.error.URLError, TimeoutError, OSError):
            return False

    def installed_models(self) -> set[str]:
        endpoint = self.config.ollama_url.rstrip("/") + "/api/tags"
        try:
            with urllib.request.urlopen(endpoint, timeout=5) as response:
                body = json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
            raise OllamaError(str(exc)) from exc
        names: set[str] = set()
        for model in body.get("models", []):
            for key in ("name", "model"):
                value = model.get(key)
                if isinstance(value, str):
                    names.add(value)
        return names

    def has_model(self, model_name: str | None = None) -> bool:
        expected = model_name or self.config.ollama_model
        installed = self.installed_models()
        if expected in installed:
            return True
        if ":" not in expected:
            return f"{expected}:latest" in installed
        return False

    def pull_model(self, model_name: str | None = None) -> None:
        endpoint = self.config.ollama_url.rstrip("/") + "/api/pull"
        payload = json.dumps(
            {"model": model_name or self.config.ollama_model, "stream": False}
        ).encode("utf-8")
        request = urllib.request.Request(
            endpoint,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(
                request, timeout=self.config.model_pull_timeout_seconds
            ) as response:
                body = json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
            raise OllamaError(str(exc)) from exc
        if body.get("status") != "success":
            raise OllamaError(body.get("error") or "Model download did not complete")


class LocalAssistant:
    def __init__(self, config: AppConfig, memory: ConversationMemory | None = None) -> None:
        self.config = config
        self.memory = memory or ConversationMemory(max_messages=config.memory_max_messages)
        self.client = OllamaClient(config)

    def reply(self, user_text: str, input_source: str = "text") -> Reply:
        text = user_text.strip()
        if not text:
            return Reply("何か入力してください、ご主人様。", "offline")

        command_reply = self._command(text)
        if command_reply:
            return command_reply

        history = self.memory.recent() if self.config.save_history else []
        messages = [{"role": "system", "content": self._system_prompt()}]
        messages.extend(
            {"role": item.role, "content": self._memory_content(item.content, item.source)}
            for item in history
        )
        messages.append(
            {"role": "user", "content": self._memory_content(text, input_source)}
        )

        try:
            answer = self.client.chat(messages)
            source = "ollama"
        except OllamaError:
            answer = self._offline_reply(text)
            source = "offline"

        if self.config.save_history:
            self.memory.append("user", text, input_source)
            self.memory.append("assistant", answer)
        return Reply(answer, source)

    def _memory_content(self, content: str, source: str) -> str:
        context: list[str] = []
        aliases = {"メイドちゃん", self.config.assistant_name}
        if any(alias and alias in content for alias in aliases):
            context.append("『メイドちゃん』は応答するあなた自身を指す呼び名です")
        if source == "voice":
            context.append("音声入力の文字起こし")
        if context:
            return f"[{'／'.join(context)}] {content}"
        return content

    def _system_prompt(self) -> str:
        return f"""あなたはPCに常駐するローカルAIメイド「{self.config.assistant_name}」です。
ユーザーが「メイドちゃん」と呼んだ場合、それは第三者ではなくあなた自身のことです。「メイドちゃん」について尋ねられたら、必ず自分のこととして一人称の「私」で答えてください。
ユーザーを「{self.config.user_name}」と呼びます。落ち着いて有能で、少し素っ気ないものの親切です。
日本語で簡潔に回答してください。知らないことは推測で断定しません。
会話履歴にあるユーザーの発言、好み、決定事項を記憶として参照し、現在の返答へ自然に反映してください。
「音声入力の文字起こし」と付いた発言は、文脈から明らかな誤認識だけを慎重に補い、判断できない場合は確認してください。
あなたはローカル環境で動き、ユーザーが明示しない限り外部サービスへ情報を送りません。
PC操作を実行したふりはせず、できない場合は手順を提案してください。"""

    def _command(self, text: str) -> Reply | None:
        if text == "/help":
            return Reply(
                "/status: 接続状態  /model: モデル名  /clear: 会話履歴を削除", "command"
            )
        if text == "/status":
            status = "接続済み" if self.client.is_available() else "未接続（オフライン応答）"
            return Reply(f"Ollama: {status}\n接続先: {self.config.ollama_url}", "command")
        if text == "/model":
            return Reply(f"使用モデル: {self.config.ollama_model}", "command")
        if text == "/clear":
            self.memory.clear()
            return Reply("会話履歴を削除しました。", "command")
        return None

    def _offline_reply(self, text: str) -> str:
        now = datetime.now().astimezone()
        if re.search(r"(今何時|いま何時|時刻|時間.*教えて)", text):
            return f"現在時刻は {now:%H時%M分} です。"
        if re.search(r"(今日.*何日|日付|何曜日)", text):
            weekdays = "月火水木金土日"
            return f"今日は {now:%Y年%m月%d日}（{weekdays[now.weekday()]}曜日）です。"
        if re.search(r"(あなたは誰|名前は|自己紹介)", text):
            return (
                f"私は{self.config.assistant_name}。このPCの中で動くローカル専用メイドです。"
                "Ollamaを起動すれば、もっと自由に会話できます。"
            )
        if re.search(r"(こんにちは|こんばんは|おはよう|ただいま)", text):
            return f"おかえりなさい、{self.config.user_name}。Ollamaは今お休み中のようです。"
        return (
            "ローカルLLMへ接続できませんでした。Ollamaを起動し、"
            f"`ollama pull {self.config.ollama_model}` を実行してください。"
        )

