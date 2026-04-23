import hashlib
import hmac
import json
import logging
import os
import subprocess
import sys
import threading
from base64 import b64encode
from datetime import datetime
from pathlib import Path

import requests
from dotenv import load_dotenv
from flask import Flask, abort, request

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

LINE_CHANNEL_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")
LINE_CHANNEL_SECRET = os.getenv("LINE_CHANNEL_SECRET")

LOG_DIR = BASE_DIR / "logs"
LOG_DIR.mkdir(exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_DIR / "notify_line.log", encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger(__name__)

LINE_API_URL = "https://api.line.me/v2/bot/message/reply"
LINE_PUSH_URL = "https://api.line.me/v2/bot/message/push"

app = Flask(__name__)

SESSIONS_FILE = BASE_DIR / "pending_sessions.json"


def load_sessions():
    if SESSIONS_FILE.exists():
        with open(SESSIONS_FILE, encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_sessions(sessions):
    with open(SESSIONS_FILE, "w", encoding="utf-8") as f:
        json.dump(sessions, f, ensure_ascii=False, indent=2)


def _headers():
    return {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {LINE_CHANNEL_ACCESS_TOKEN}",
    }


def reply_message(reply_token, text):
    payload = {
        "replyToken": reply_token,
        "messages": [{"type": "text", "text": text}],
    }
    resp = requests.post(LINE_API_URL, headers=_headers(), json=payload, timeout=10)
    if not resp.ok:
        log.error(f"LINE reply 失敗: {resp.status_code} {resp.text}")


def push_message(to, text):
    payload = {"to": to, "messages": [{"type": "text", "text": text}]}
    resp = requests.post(LINE_PUSH_URL, headers=_headers(), json=payload, timeout=10)
    if not resp.ok:
        log.error(f"LINE push 失敗: {resp.status_code} {resp.text}")


def verify_signature(body, signature):
    secret = LINE_CHANNEL_SECRET.encode("utf-8")
    digest = hmac.new(secret, body, digestmod=hashlib.sha256).digest()
    expected = b64encode(digest).decode("utf-8")
    return hmac.compare_digest(expected, signature)


def load_latest_scripts():
    scripts_dir = BASE_DIR / "1_scripts"
    json_files = sorted(scripts_dir.glob("scripts_*.json"), reverse=True)
    if not json_files:
        raise FileNotFoundError("台本ファイルが見つかりません")
    latest = json_files[0]
    with open(latest, encoding="utf-8") as f:
        data = json.load(f)
    return data["scripts"], latest


def build_notification_text(scripts):
    lines = ["📹 YouTube ショート台本が生成されました\n"]
    for i, s in enumerate(scripts, 1):
        lines.append(f"━━━ キーワード {i}: {s['keyword']} ━━━")
        lines.append(f"🎯 トレンドスコア: {s['trend_score']}")
        lines.append("\n📝 台本:")
        lines.append(s["script"])
        lines.append("\n🏷 タイトル候補:")
        for j, title in enumerate(s.get("title_candidates", []), 1):
            lines.append(f"  {j}. {title}")
        lines.append("")
    lines.append("─────────────────")
    lines.append("返信方法:")
    lines.append("  OK    → キーワード1を承認")
    lines.append("  1/2/3 → そのキーワード番号を承認")
    lines.append("  NG    → 却下して再生成")
    return "\n".join(lines)


def save_script_to_txt(script):
    video_dir = BASE_DIR / "3_video"
    video_dir.mkdir(exist_ok=True)
    keyword = script["keyword"].replace("/", "_").replace(" ", "_")
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filepath = video_dir / f"script_{keyword}_{timestamp}.txt"
    lines = [
        f"キーワード: {script['keyword']}",
        "",
        "【台本】",
        script["script"],
    ]
    filepath.write_text("\n".join(lines), encoding="utf-8")
    log.info(f"台本txtを保存しました: {filepath}")
    return filepath


def send_notification(to):
    scripts, script_path = load_latest_scripts()
    text = build_notification_text(scripts)
    chunk_size = 4900
    chunks = [text[i: i + chunk_size] for i in range(0, len(text), chunk_size)]
    for chunk in chunks:
        push_message(to, chunk)
    sessions = load_sessions()
    sessions[to] = {"scripts": scripts, "script_path": str(script_path)}
    save_sessions(sessions)
    log.info(f"台本通知を送信しました → {to}")


def handle_approval(user_id, reply_token, text):
    sessions = load_sessions()
    session = sessions.get(user_id)
    if not session:
        reply_message(reply_token, "承認待ちの台本がありません。先にスケジューラーを実行してください。")
        return
    scripts = session["scripts"]
    text_stripped = text.strip()
    text_lower = text_stripped.lower()
    if text_lower == "ok" or text_lower in ("1", "2", "3"):
        index = 0 if text_lower == "ok" else int(text_lower) - 1
        index = min(index, len(scripts) - 1)
        chosen_script = scripts[index]
        keyword = chosen_script["keyword"]
        reply_message(reply_token, f"制作開始します！\n\n{chosen_script['script']}")
        script_file = save_script_to_txt(chosen_script)
        push_message(user_id, f"Vrewに台本を貼り付けて動画を作成してください\n\n📄 {script_file.name}")
        log.info(f"台本承認: keyword={keyword}, file={script_file}")
        sessions = load_sessions()
        sessions.pop(user_id, None)
        save_sessions(sessions)
    elif text_lower.startswith("ng"):
        instruction = text_stripped[2:].lstrip(":： ").strip()
        reply_message(reply_token, "❌ 却下しました。台本を再生成して送り直します...")
        sessions = load_sessions()
        sessions.pop(user_id, None)
        save_sessions(sessions)
        def regenerate_and_notify():
            env = os.environ.copy()
            if instruction:
                env["REGENERATE_INSTRUCTION"] = instruction
            result = subprocess.run(
                [sys.executable, str(BASE_DIR / "1_scripts" / "generate_script.py")],
                env=env,
                cwd=str(BASE_DIR),
            )
            if result.returncode == 0:
                try:
                    send_notification(user_id)
                except Exception as e:
                    push_message(user_id, "⚠️ 再生成しましたが通知送信に失敗しました。")
            else:
                push_message(user_id, "⚠️ 台本の再生成に失敗しました。")
        threading.Thread(target=regenerate_and_notify, daemon=True).start()
    else:
        reply_message(reply_token, "返信は OK / 1 / 2 / 3 / NG のいずれかで送ってください。")


@app.route("/webhook", methods=["POST"])
def webhook():
    signature = request.headers.get("X-Line-Signature", "")
    body = request.get_data()
    if not verify_signature(body, signature):
        abort(400)
    data = json.loads(body)
    for event in data.get("events", []):
        if event.get("type") != "message":
            continue
        if event["message"].get("type") != "text":
            continue
        user_id = event["source"]["userId"]
        reply_token = event["replyToken"]
        text = event["message"]["text"]
        handle_approval(user_id, reply_token, text)
    return "OK", 200


@app.route("/notify/<user_id>", methods=["POST"])
def notify(user_id):
    try:
        send_notification(user_id)
        return {"status": "sent"}, 200
    except FileNotFoundError as e:
        return {"error": str(e)}, 404
    except Exception as e:
        return {"error": str(e)}, 500


if __name__ == "__main__":
    if "--send" in sys.argv:
        user_id = os.getenv("LINE_NOTIFY_USER_ID", "").strip()
        if not user_id:
            sys.exit(1)
        try:
            send_notification(user_id)
        except Exception as e:
            sys.exit(1)
        sys.exit(0)
    port = int(os.getenv("LINE_WEBHOOK_PORT", "8080"))
    app.run(host="0.0.0.0", port=port, debug=False)
