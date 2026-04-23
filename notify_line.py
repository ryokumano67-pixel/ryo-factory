"""
notify_line.py
生成した台本とタイトル3案をLINEに送信し、承認/修正指示をWebhookで受け取る。

返信ルール:
  OK or ok  → 最初のキーワードの台本を承認（次工程へ）
  1 / 2 / 3 → 対応するタイトル番号を選択して承認
  NG: <指示> → 却下。指示を generate_script.py に渡して再生成
"""

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

# ── 環境設定 ──────────────────────────────────────────────
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

# 承認待ちセッションを一時保存（プロセス内メモリ）
# { user_id: { "scripts": [...], "script_path": str } }
pending_sessions: dict[str, dict] = {}


# ── LINE API ヘルパー ──────────────────────────────────────

def _headers() -> dict:
    return {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {LINE_CHANNEL_ACCESS_TOKEN}",
    }


def reply_message(reply_token: str, text: str) -> None:
    payload = {
        "replyToken": reply_token,
        "messages": [{"type": "text", "text": text}],
    }
    resp = requests.post(LINE_API_URL, headers=_headers(), json=payload, timeout=10)
    if not resp.ok:
        log.error(f"LINE reply 失敗: {resp.status_code} {resp.text}")


def push_message(to: str, text: str) -> None:
    payload = {"to": to, "messages": [{"type": "text", "text": text}]}
    resp = requests.post(LINE_PUSH_URL, headers=_headers(), json=payload, timeout=10)
    if not resp.ok:
        log.error(f"LINE push 失敗: {resp.status_code} {resp.text}")


def verify_signature(body: bytes, signature: str) -> bool:
    """LINE Webhookの署名を検証する。"""
    secret = LINE_CHANNEL_SECRET.encode("utf-8")
    digest = hmac.new(secret, body, digestmod=hashlib.sha256).digest()
    expected = b64encode(digest).decode("utf-8")
    return hmac.compare_digest(expected, signature)


# ── 台本通知 ──────────────────────────────────────────────

def load_latest_scripts() -> tuple[list[dict], Path]:
    """1_scripts フォルダから最新の台本JSONを読み込む。"""
    scripts_dir = BASE_DIR / "1_scripts"
    json_files = sorted(scripts_dir.glob("scripts_*.json"), reverse=True)
    if not json_files:
        raise FileNotFoundError("台本ファイルが見つかりません")
    latest = json_files[0]
    with open(latest, encoding="utf-8") as f:
        data = json.load(f)
    return data["scripts"], latest


def build_notification_text(scripts: list[dict]) -> str:
    """LINEに送る通知テキストを組み立てる。"""
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


def save_script_to_txt(script: dict) -> Path:
    """承認された台本をtxtファイルとして3_videoフォルダに保存する。"""
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
    if script.get("scenes"):
        lines.append("\n【シーン別】")
        for scene in script["scenes"]:
            lines.append(f"\n--- {scene['name']} ---")
            lines.append(scene["text"])

    filepath.write_text("\n".join(lines), encoding="utf-8")
    log.info(f"台本txtを保存しました: {filepath}")
    return filepath


def send_notification(to: str) -> None:
    """最新台本をLINEにプッシュ通知する。"""
    scripts, script_path = load_latest_scripts()
    text = build_notification_text(scripts)

    # 5000文字を超える場合は分割送信
    chunk_size = 4900
    chunks = [text[i : i + chunk_size] for i in range(0, len(text), chunk_size)]
    for chunk in chunks:
        push_message(to, chunk)

    pending_sessions[to] = {"scripts": scripts, "script_path": str(script_path)}
    log.info(f"台本通知を送信しました → {to}")


# ── Webhook ハンドラ ──────────────────────────────────────

def handle_approval(user_id: str, reply_token: str, text: str) -> None:
    """承認・却下メッセージを処理する。"""
    session = pending_sessions.get(user_id)
    if not session:
        reply_message(reply_token, "承認待ちの台本がありません。先にスケジューラーを実行してください。")
        return

    scripts = session["scripts"]
    text_stripped = text.strip()
    text_lower = text_stripped.lower()

    # ── 承認処理（OK / 1 / 2 / 3）──
    if text_lower == "ok" or text_lower in ("1", "2", "3"):
        # OK → キーワード1番、数字 → そのキーワード番号
        index = 0 if text_lower == "ok" else int(text_lower) - 1
        index = min(index, len(scripts) - 1)  # 範囲外ガード

        chosen_script = scripts[index]
        keyword = chosen_script["keyword"]

        # 1. 「制作開始します！」＋台本テキストを返信
        reply_message(
            reply_token,
            f"制作開始します！\n\n{chosen_script['script']}",
        )

        # 2. 台本をtxtファイルとして3_videoに保存
        script_file = save_script_to_txt(chosen_script)

        # 3. Vrew作業依頼をプッシュ通知
        push_message(user_id, f"Vrewに台本を貼り付けて動画を作成してください\n\n📄 {script_file.name}")

        log.info(f"台本承認: keyword={keyword}, file={script_file}")
        pending_sessions.pop(user_id, None)

    # ── 却下・再生成処理（NGで始まるメッセージ）──
    elif text_lower.startswith("ng"):
        instruction = text_stripped[2:].lstrip(":： ").strip()
        reply_message(reply_token, "❌ 却下しました。台本を再生成して送り直します...")
        log.info(f"台本却下。再生成指示: {instruction!r}")
        pending_sessions.pop(user_id, None)

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
                    log.error(f"再通知失敗: {e}")
                    push_message(user_id, "⚠️ 再生成しましたが通知送信に失敗しました。")
            else:
                push_message(user_id, "⚠️ 台本の再生成に失敗しました。")

        threading.Thread(target=regenerate_and_notify, daemon=True).start()

    else:
        reply_message(reply_token, "返信は OK / 1 / 2 / 3 / NG のいずれかで送ってください。")


@app.route("/webhook", methods=["POST"])
def webhook():
    # 署名検証
    signature = request.headers.get("X-Line-Signature", "")
    body = request.get_data()
    if not verify_signature(body, signature):
        log.warning("署名検証失敗")
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
        log.info(f"受信: user={user_id}, text={text!r}")
        handle_approval(user_id, reply_token, text)

    return "OK", 200


@app.route("/notify/<user_id>", methods=["POST"])
def notify(user_id: str):
    """内部から呼び出して台本通知を送るエンドポイント。"""
    try:
        send_notification(user_id)
        return {"status": "sent"}, 200
    except FileNotFoundError as e:
        return {"error": str(e)}, 404
    except Exception as e:
        log.error(f"通知エラー: {e}")
        return {"error": str(e)}, 500


if __name__ == "__main__":
    # --send モード: サーバーを起動せず通知のみ送信して終了
    if "--send" in sys.argv:
        user_id = os.getenv("LINE_NOTIFY_USER_ID", "").strip()
        if not user_id:
            log.error("LINE_NOTIFY_USER_ID が設定されていません。.env に追加してください。")
            sys.exit(1)
        try:
            send_notification(user_id)
            log.info("通知送信完了")
        except Exception as e:
            log.error(f"通知送信失敗: {e}")
            sys.exit(1)
        sys.exit(0)

    port = int(os.getenv("LINE_WEBHOOK_PORT", "8080"))

    # LINE_NOTIFY_USER_ID が設定されていれば起動時に即通知
    notify_user_id = os.getenv("LINE_NOTIFY_USER_ID", "").strip()
    if notify_user_id:
        log.info(f"起動時通知を送信します → {notify_user_id}")
        try:
            send_notification(notify_user_id)
        except Exception as e:
            log.error(f"起動時通知失敗: {e}")

    log.info(f"LINE Webhook サーバーを起動します (port={port})")
    app.run(host="0.0.0.0", port=port, debug=False)
