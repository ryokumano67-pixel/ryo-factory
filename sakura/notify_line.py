"""
sakura/notify_line.py
サクラチャンネル用 LINE 通知送信ツール（--send オプションのみ）。
LINE Webhook の処理は親の notify_line.py（ポート8080）が一括担当する。
"""

import json
import logging
import os
import sys
from pathlib import Path

import requests
from dotenv import load_dotenv

SAKURA_DIR = Path(__file__).resolve().parent
BASE_DIR = SAKURA_DIR.parent
load_dotenv(BASE_DIR / ".env")

LINE_CHANNEL_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")

LOG_DIR = BASE_DIR / "logs"
LOG_DIR.mkdir(exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_DIR / "sakura_notify_line.log", encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger(__name__)

LINE_PUSH_URL = "https://api.line.me/v2/bot/message/push"
SESSIONS_FILE = SAKURA_DIR / "sakura_sessions.json"


def _headers():
    return {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {LINE_CHANNEL_ACCESS_TOKEN}",
    }


def push_message(to, text):
    payload = {"to": to, "messages": [{"type": "text", "text": text}]}
    resp = requests.post(LINE_PUSH_URL, headers=_headers(), json=payload, timeout=10)
    if not resp.ok:
        log.error(f"LINE push 失敗: {resp.status_code} {resp.text}")


def load_sessions():
    if SESSIONS_FILE.exists():
        with open(SESSIONS_FILE, encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_sessions(sessions):
    with open(SESSIONS_FILE, "w", encoding="utf-8") as f:
        json.dump(sessions, f, ensure_ascii=False, indent=2)


def load_latest_scripts():
    scripts_dir = SAKURA_DIR / "scripts"
    json_files = sorted(scripts_dir.glob("scripts_*.json"), reverse=True)
    if not json_files:
        raise FileNotFoundError("サクラ台本ファイルが見つかりません")
    with open(json_files[0], encoding="utf-8") as f:
        data = json.load(f)
    return data["scripts"], json_files[0]


_NUM_MAP = [
    ("10", "じゅう"), ("9", "く"), ("8", "はち"), ("7", "なな"),
    ("6", "ろく"), ("5", "ご"), ("4", "し"), ("3", "さん"),
    ("2", "に"), ("1", "いち"),
]


def _to_tts_text(script: str) -> str:
    import re
    sys.path.insert(0, str(BASE_DIR))
    from pipeline import fix_for_tts
    text = fix_for_tts(script)
    for num, reading in _NUM_MAP:
        text = re.sub(rf'(?<!\d){re.escape(num)}(?!\d)', reading, text)
    # tts_corrections.json を直接読んで適用（同名モジュール競合を回避）
    corrections_file = SAKURA_DIR / "tts_corrections.json"
    if corrections_file.exists():
        with open(corrections_file, encoding="utf-8") as f:
            for c in json.load(f).get("corrections", []):
                text = text.replace(c["original"], c["corrected"])
    return text


def build_notification_text(scripts):
    lines = ["🌸 サクラ台本が生成されました\n"]
    for i, s in enumerate(scripts, 1):
        topic = s.get("topic", s.get("keyword", ""))
        lines.append(f"━━━ テーマ {i}: {topic} ━━━")
        lines.append(s["script"])
        lines.append("")
    lines.append("─────────────────")
    lines.append("OK / 1 / 2 / 3 → 承認して動画生成")
    lines.append("NG → 却下して再生成")
    return "\n".join(lines)


def send_notification(to):
    scripts, script_path = load_latest_scripts()
    text = build_notification_text(scripts)
    chunk_size = 4900
    for chunk in [text[i:i + chunk_size] for i in range(0, len(text), chunk_size)]:
        push_message(to, chunk)
    sessions = load_sessions()
    sessions[to] = {"scripts": scripts, "script_path": str(script_path)}
    save_sessions(sessions)
    log.info(f"サクラ台本通知を送信しました → {to}")


if __name__ == "__main__":
    if "--send" not in sys.argv:
        print("使い方: python notify_line.py --send")
        sys.exit(1)
    user_id = os.getenv("LINE_NOTIFY_USER_ID", "").strip()
    if not user_id:
        log.error("LINE_NOTIFY_USER_ID が未設定です")
        sys.exit(1)
    try:
        send_notification(user_id)
    except Exception as e:
        log.error(f"通知エラー: {e}")
        sys.exit(1)
