"""
startup.py
Render起動時に実行される初期化スクリプト。
- 環境変数からYouTubeトークン・client_secretsをファイルに復元
- 永続ディレクトリ（DATA_DIR）のサブフォルダを作成
"""

import base64
import json
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = Path(os.getenv("DATA_DIR", BASE_DIR))


def restore_file_from_env(env_key: str, dest_path: Path):
    b64 = os.getenv(env_key, "").strip()
    if not b64:
        return
    try:
        content = base64.b64decode(b64).decode("utf-8")
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        dest_path.write_text(content, encoding="utf-8")
        print(f"[startup] {env_key} → {dest_path}")
    except Exception as e:
        print(f"[startup] {env_key} 復元失敗: {e}")


def init_dirs():
    dirs = [
        DATA_DIR / "sessions",
        DATA_DIR / "sakura" / "scripts",
        DATA_DIR / "sakura" / "audio",
        DATA_DIR / "sakura" / "videos",
        DATA_DIR / "logs",
    ]
    for d in dirs:
        d.mkdir(parents=True, exist_ok=True)
    print(f"[startup] DATA_DIR={DATA_DIR} 初期化完了")


if __name__ == "__main__":
    init_dirs()

    # YouTubeトークンをファイルに復元
    restore_file_from_env("YOUTUBE_TOKEN_B64",        BASE_DIR / "youtube_token.json")
    restore_file_from_env("SAKURA_YOUTUBE_TOKEN_B64", BASE_DIR / "sakura" / "sakura_youtube_token.json")
    restore_file_from_env("YOUTUBE_CLIENT_SECRETS_B64", BASE_DIR / "client_secrets.json")

    print("[startup] 完了")
