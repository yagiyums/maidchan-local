from __future__ import annotations

import json
import urllib.request

from maidchan.config import AppConfig
from maidchan.research import ExchangeRateResearch, WeatherResearch, WikipediaResearch


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
    disabled = AppConfig(web_research_enabled=False)
    assert not WeatherResearch(disabled).should_research("東京の天気")
    assert not ExchangeRateResearch(disabled).should_research("ドル円レート")


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


def test_weather_research_fetches_location_and_forecast(monkeypatch) -> None:
    def fake_urlopen(request, timeout):
        assert timeout == 10
        if "geocoding-api" in request.full_url:
            return FakeResponse(
                {
                    "results": [
                        {
                            "name": "東京",
                            "admin1": "東京都",
                            "latitude": 35.68,
                            "longitude": 139.76,
                        }
                    ]
                }
            )
        return FakeResponse(
            {
                "current": {
                    "temperature_2m": 20.5,
                    "apparent_temperature": 19.8,
                    "relative_humidity_2m": 55,
                    "wind_speed_10m": 8.2,
                },
                "daily": {
                    "time": ["2026-11-01", "2026-11-02", "2026-11-03"],
                    "weather_code": [1, 3, 61],
                    "temperature_2m_max": [23.0, 21.0, 18.0],
                    "temperature_2m_min": [14.0, 13.0, 11.0],
                    "precipitation_probability_max": [10, 20, 70],
                },
            }
        )

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    result = WeatherResearch(AppConfig()).search("東京の天気を教えて")

    assert result is not None
    assert "晴れ" in result.documents[0].extract
    assert "20.5℃" in result.documents[0].extract
    assert result.documents[0].source_name == "Open-Meteo"


def test_exchange_rate_research_converts_amount(monkeypatch) -> None:
    monkeypatch.setattr(
        urllib.request,
        "urlopen",
        lambda _request, timeout: FakeResponse(
            {"date": "2026-10-30", "base": "USD", "quote": "JPY", "rate": 153.25}
        ),
    )
    result = ExchangeRateResearch(AppConfig()).search("100ドルは何円？")

    assert result is not None
    assert "15,325.00 JPY" in result.documents[0].extract
    assert result.documents[0].source_name == "Frankfurter"
