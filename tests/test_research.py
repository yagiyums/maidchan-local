from __future__ import annotations

import json
import urllib.request

from maidchan.config import AppConfig
from maidchan.research import WikipediaResearch


class FakeResponse:
    def __init__(self, payload: dict) -> None:
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_args) -> None:
        return None

    def read(self) -> bytes:
        return json.dumps(self.payload, ensure_ascii=False).encode("utf-8")


def test_research_detection_handles_direct_and_natural_requests() -> None:
    research = WikipediaResearch(AppConfig())

    assert research.should_research("富士山の高さを調べて")
    assert research.should_research("メイドちゃん、織田信長って誰？")
    assert research.should_research("/search 東京タワー")
    assert not research.should_research("私の好きな色を覚えてる？")


def test_research_query_keeps_the_subject_and_removes_question_words() -> None:
    assert WikipediaResearch._query_from_text("東京タワーの高さを調べて") == "東京タワー"
    assert WikipediaResearch._query_from_text("メイドちゃん、織田信長って誰？") == (
        "織田信長"
    )


def test_wikipedia_search_builds_context_and_sources(monkeypatch) -> None:
    payload = {
        "query": {
            "pages": [
                {
                    "title": "東京タワー",
                    "extract": "東京タワーは東京都港区にある総合電波塔である。",
                    "canonicalurl": "https://ja.wikipedia.org/wiki/東京タワー",
                }
            ]
        }
    }
    captured = {}

    def fake_urlopen(request, timeout):
        captured["url"] = request.full_url
        captured["timeout"] = timeout
        return FakeResponse(payload)

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    result = WikipediaResearch(AppConfig()).search("東京タワーを調べて")

    assert result is not None
    assert result.query == "東京タワー"
    assert "東京タワー" in result.as_context()
    assert "出典:" in result.source_footer()
    assert "titles=%E6%9D%B1%E4%BA%AC%E3%82%BF%E3%83%AF%E3%83%BC" in captured["url"]
    assert captured["timeout"] == 10
