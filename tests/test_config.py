from maidchan.config import AppConfig


def test_config_round_trip(tmp_path) -> None:
    path = tmp_path / "config.json"
    AppConfig(user_name="テストさん", mascot_width=420).save(path)
    loaded = AppConfig.load(path)
    assert loaded.user_name == "テストさん"
    assert loaded.mascot_width == 420


def test_unknown_config_keys_are_ignored(tmp_path) -> None:
    path = tmp_path / "config.json"
    path.write_text('{"user_name":"主","future_option":true}', encoding="utf-8")
    assert AppConfig.load(path).user_name == "主"

