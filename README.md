# Maid-chan Local

Windowsデスクトップに常駐する、ローカル完結型のパーソナルメイド・マスコットです。会話処理はPC上の[Ollama](https://ollama.com/)に接続し、クラウドの従量課金AI APIは使いません。Ollamaが停止中でも、時刻・日付・基本案内にはオフラインで応答します。

> このプロジェクトは個人利用向けのオリジナル実装です。既存作品の公式ソフトウェアや公式キャラクター素材ではありません。

## できること

- 透明背景・常に手前に表示されるデスクトップマスコット
- ドラッグ移動、ダブルクリック会話、右クリックメニュー
- タスクトレイ常駐
- Ollama経由の日本語会話（既定: `qwen2.5:3b`）
- `%APPDATA%\MaidchanLocal` だけに保存される設定と会話履歴
- Ollama未接続時の完全オフライン応答

## セットアップ

必要環境はWindows 10/11、Python 3.10以上です。

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\setup.ps1
```

自由な会話を使う場合はOllamaをインストールし、PowerShellでモデルを取得します。

```powershell
ollama pull qwen2.5:3b
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
- `/status`: Ollama接続状態
- `/model`: 使用モデル
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
  "mascot_width": 190,
  "save_history": true
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

アプリが直接通信するのは設定したOllamaエンドポイントだけです。既定値は同じPCの `127.0.0.1:11434` です。テレメトリ、広告SDK、クラウドAI SDKは含みません。会話履歴を残さない場合は `save_history` を `false` にしてください。

## ライセンス

ソースコードはMIT Licenseです。`src/maidchan/assets/maid.png` は本プロジェクト用にAI生成したオリジナル素材です。
