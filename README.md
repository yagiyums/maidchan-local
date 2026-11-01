# Maid-chan Local

Windowsデスクトップに常駐する、ローカル完結型のパーソナルメイド・マスコットです。会話処理はPC上の[Ollama](https://ollama.com/)に接続し、クラウドの従量課金AI APIは使いません。Ollamaが停止中でも、時刻・日付・基本案内にはオフラインで応答します。立ち絵は呼吸、まばたき、髪や衣装の揺れを含む透過GIFで常時アニメーションします。

会話中の「メイドちゃん」はアシスタント自身の呼び名として解釈され、メイドちゃん本人についての質問には一人称で答えます。

> このプロジェクトは個人利用向けのオリジナル実装です。既存作品の公式ソフトウェアや公式キャラクター素材ではありません。

## できること

- 透過GIFで自然に動き、常に手前に表示されるデスクトップマスコット
- ドラッグ移動、ダブルクリック会話、右クリックメニュー
- タスクトレイ常駐
- Ollama経由の日本語会話（既定: `qwen2.5:3b`）
- 起動時にOllamaを自動検出・自動起動し、初回のみモデルを自動取得
- 一般知識を必要に応じてWikipediaで調べ、出典付きで回答
- マイクの発話を自動検出するハンズフリー高精度日本語音声入力（faster-whisper）
- メイドちゃんの応答読み上げ（VOICEVOX、Windows音声フォールバック）
- `%APPDATA%\MaidchanLocal` だけに保存される設定と会話履歴
- Ollama未接続時の完全オフライン応答

## セットアップ

必要環境はWindows 10/11、Python 3.10以上です。

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\setup.ps1
```

自由な会話を使う場合は、先に[Ollama for Windows](https://ollama.com/download/windows)をインストールしてください。Maid-chan Localの起動時にOllamaもバックグラウンドで起動し、モデルがなければ初回のみ自動取得します。

```powershell
irm https://ollama.com/install.ps1 | iex
```

その後、次のコマンドで起動します。

```powershell
.\run.ps1
```

Ollamaもモデルもローカルで動作します。初回モデル取得時を除き、会話内容を外部APIへ送信しません。

## 操作

- キャラクターをドラッグ: 移動（位置は自動保存）
- ダブルクリック: 会話欄を開閉
- 右クリック: メニュー
- マイクへ話す: 発話開始と無音終了を自動検出して認識・送信
- タスクトレイの `マイク自動待受`: 常時待受のON/OFF
- `🔊` / `🔇`: 応答の読み上げを切り替え
- `/status`: Ollama接続状態
- `/model`: 使用モデル
- `/search 語句`: Wikipediaを検索して回答
- `/clear`: 会話履歴の削除
- `/help`: コマンド一覧

## 設定

初回起動時に `%APPDATA%\MaidchanLocal\config.json` が作られます。アプリ終了後に編集してください。

```json
{
  "assistant_name": "メイドちゃん",
  "user_name": "ご主人様",
  "ollama_url": "http://127.0.0.1:11434",
  "ollama_model": "qwen2.5:3b",
  "auto_start_ollama": true,
  "auto_pull_model": true,
  "voice_input_enabled": true,
  "microphone_gain": 3.0,
  "recognition_model": "small",
  "recognition_device": "cpu",
  "recognition_compute_type": "int8",
  "recognition_cpu_threads": 8,
  "recognition_beam_size": 5,
  "recognition_target_rms": 4000,
  "vad_min_rms": 500,
  "vad_noise_multiplier": 2.2,
  "vad_min_speech_ms": 200,
  "vad_silence_ms": 700,
  "tts_enabled": true,
  "tts_engine": "voicevox",
  "voicevox_url": "http://127.0.0.1:50021",
  "voicevox_speaker": 103,
  "voicevox_credit": "VOICEVOX:ユーレイちゃん",
  "voicevox_speed_scale": 1.05,
  "voicevox_volume_scale": 1.0,
  "mascot_width": 190,
  "save_history": true,
  "memory_max_messages": 60,
  "web_research_enabled": true,
  "research_timeout_seconds": 10,
  "research_max_results": 3
}
```

より軽いPCでは `qwen2.5:1.5b`、余裕がある場合は `qwen2.5:7b` など、Ollamaで利用できるモデル名へ変更できます。

## 開発・テスト

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m ruff check .
```

Python環境を含むWindowsアプリを生成する場合は次を実行します。

```powershell
.\build.ps1
```

実行ファイルは `dist\MaidchanLocal\MaidchanLocal.exe` に作られます。

## プライバシー

アプリはローカルのOllamaに加え、一般知識の調査時だけ日本語版Wikipediaへ検索語を送信します。会話履歴やマイク音声は送信しません。ウェブ調査を使わない場合は `web_research_enabled` を `false` にしてください。テレメトリ、広告SDK、クラウドAI SDKは含みません。キーボード入力と音声入力の文字起こしは `%APPDATA%\MaidchanLocal\history.jsonl` に保存され、直近60メッセージをローカルAIの記憶として使います。音声入力には入力元情報も保存されます。会話履歴を残さない場合は `save_history` を `false` にするか、`/clear` で削除してください。

マイク音声はメモリ上で処理し、録音ファイルとして保存しません。日本語文字起こしもPC内のfaster-whisperモデルで行い、音声をクラウドへ送信しません。初回の音声認識時だけ多言語版Whisper `small` モデルを取得し、以後は `%APPDATA%\MaidchanLocal\models` に保存したモデルを使います。入力はマイク感度で増幅した後、DC成分を除去し、16kHzへ変換して発話音量を自動正規化します。会話UIで入力レベルを確認しながらマイク感度を100〜600%で調整できます。メイドちゃんの読み上げ中とAI処理中はマイク待受を一時停止し、自己応答ループを防ぎます。応答後は自動的に待受へ戻り、処理スレッドが停止していた場合も自動再起動します。常時待受を止める場合はタスクトレイからOFFにするか、`voice_input_enabled` を `false` にしてください。

応答音声はローカルのVOICEVOX Engineへ送られ、`audio_query` と `synthesis` APIで生成されます。既定音声は「ユーレイちゃん・甘々」です。利用時のクレジットは **VOICEVOX:ユーレイちゃん** です。VOICEVOXが利用できない場合のみ、Windowsの日本語音声へ自動的に切り替わります。

## ライセンス

ソースコードはMIT Licenseです。`src/maidchan/assets/maid.png` は本プロジェクト用にAI生成したオリジナル素材です。
