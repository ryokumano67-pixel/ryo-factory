import hashlib
import hmac
import json
import logging
import os
import subprocess
import sys
import threading
import time
from base64 import b64encode
from datetime import datetime
from pathlib import Path

import schedule

import requests
from dotenv import load_dotenv
from flask import Flask, abort, request

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = Path(os.getenv("DATA_DIR", BASE_DIR))
load_dotenv(BASE_DIR / ".env")

LINE_CHANNEL_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")
LINE_CHANNEL_SECRET = os.getenv("LINE_CHANNEL_SECRET")

LOG_DIR = DATA_DIR / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)
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

SESSIONS_FILE = DATA_DIR / "pending_sessions.json"


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


def _start_pipeline(user_id, chosen_script):
    push_message(user_id, "動画生成を開始します！完了したらお知らせします📹")

    def run():
        try:
            tmp_file = BASE_DIR / "tmp_pipeline_script.json"
            tmp_file.write_text(
                json.dumps({"scripts": [chosen_script]}, ensure_ascii=False),
                encoding="utf-8",
            )
            result = subprocess.run(
                [sys.executable, str(BASE_DIR / "pipeline.py"), str(tmp_file)],
                capture_output=True,
                text=True,
                cwd=str(BASE_DIR),
            )
            tmp_file.unlink(missing_ok=True)
            if result.returncode == 0:
                import re as re_mod
                urls = re_mod.findall(r"https://youtube\.com/shorts/\S+", result.stdout)
                url = urls[-1] if urls else "不明"
                push_message(user_id, f"✅ YouTube投稿完了！\n{url}")
            else:
                push_message(user_id, f"⚠️ エラー:\n{result.stderr[-500:]}")
        except Exception as e:
            push_message(user_id, f"⚠️ パイプラインエラー: {e}")

    threading.Thread(target=run, daemon=True).start()


def _clean_user_script(text):
    import re
    # ヘッダー行（📝 選択した台本...）を除去
    text = re.sub(r"^📝 選択した台本（.*?）\s*\n+", "", text)
    # フッター（───以降）を除去
    text = re.sub(r"\n+─{3,}.*$", "", text, flags=re.DOTALL)
    return text.strip()


def _handle_editing(user_id, reply_token, text, session):
    import sys
    sys.path.insert(0, str(BASE_DIR))
    from pipeline import to_hiragana, fix_for_tts

    sessions = load_sessions()
    chosen_script = dict(session["selected_script"])
    text_stripped = text.strip()

    if text_stripped.lower() not in ("確定", "開始", "ok", "start"):
        chosen_script["script"] = _clean_user_script(text_stripped)

    audio_preview = to_hiragana(chosen_script["script"])   # LINEに表示（ひらがな）
    audio_tts = fix_for_tts(chosen_script["script"])       # ElevenLabs送信（カタカナ固有名詞維持）

    sessions[user_id] = {
        "state": "pronunciation",
        "selected_script": chosen_script,
        "audio_text": audio_tts,
        "audio_preview": audio_preview,
        "script_path": session.get("script_path", ""),
    }
    save_sessions(sessions)

    reply_message(reply_token, f"🔊 音声で読む文章を確認してください:\n\n{audio_preview}\n\n─────────────────\n「確定」→ そのまま音声生成\n修正する場合 → 修正後の全文を送信")
    log.info(f"発音確認待機: keyword={chosen_script['keyword']}")


def _handle_pronunciation(user_id, reply_token, text, session):
    import sys
    sys.path.insert(0, str(BASE_DIR))
    from pipeline import extract_and_save_corrections

    sessions = load_sessions()
    chosen_script = dict(session["selected_script"])
    text_stripped = text.strip()

    if text_stripped.lower() not in ("確定", "開始", "ok", "start"):
        corrected = _clean_user_script(text_stripped)
        original_tts = session.get("audio_text", "")
        # 差分を学習して保存
        if original_tts and corrected != original_tts:
            extract_and_save_corrections(original_tts, corrected)
            log.info(f"TTS補正を学習しました")
        chosen_script["audio_text"] = corrected
        reply_message(reply_token, "✅ 読み方を修正して制作開始します！（補正を記憶しました）")
    else:
        chosen_script["audio_text"] = session.get("audio_text", "")
        reply_message(reply_token, "✅ 制作開始します！")

    save_script_to_txt(chosen_script)
    sessions.pop(user_id, None)
    save_sessions(sessions)
    log.info(f"発音確定: keyword={chosen_script['keyword']}")
    _start_pipeline(user_id, chosen_script)


def _handle_pending(user_id, reply_token, text, session):
    sessions = load_sessions()
    scripts = session["scripts"]
    text_stripped = text.strip()
    text_lower = text_stripped.lower()

    if text_lower == "ok" or text_lower in ("1", "2", "3"):
        index = 0 if text_lower == "ok" else int(text_lower) - 1
        index = min(index, len(scripts) - 1)
        chosen_script = scripts[index]
        keyword = chosen_script["keyword"]

        sessions[user_id] = {
            "state": "editing",
            "selected_script": chosen_script,
            "script_path": session["script_path"],
        }
        save_sessions(sessions)

        script_preview = chosen_script["script"]
        msg = (
            f"📝 選択した台本（{keyword}）\n\n"
            f"{script_preview}\n\n"
            "─────────────────\n"
            "「確定」→ そのまま動画生成\n"
            "修正する場合 → 修正後の台本全文を送信"
        )
        reply_message(reply_token, msg)
        log.info(f"台本選択: keyword={keyword}, 編集待機中")

    elif text_lower.startswith("ng"):
        instruction = text_stripped[2:].lstrip(":： ").strip()
        reply_message(reply_token, "❌ 却下しました。台本を再生成して送り直します...")
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


# ─── Sakura（朝ストレッチ）セッション処理 ─────────────────────────────────

SAKURA_DIR = BASE_DIR / "sakura"
SAKURA_SESSIONS_FILE = DATA_DIR / "sakura_sessions.json"


def load_sakura_sessions():
    if SAKURA_SESSIONS_FILE.exists():
        with open(SAKURA_SESSIONS_FILE, encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_sakura_sessions(sessions):
    with open(SAKURA_SESSIONS_FILE, "w", encoding="utf-8") as f:
        json.dump(sessions, f, ensure_ascii=False, indent=2)


_SAKURA_NUM_MAP = [
    ("10", "じゅう"), ("9", "く"), ("8", "はち"), ("7", "なな"),
    ("6", "ろく"), ("5", "ご"), ("4", "し"), ("3", "さん"),
    ("2", "に"), ("1", "いち"),
]

_SAKURA_CORRECTIONS_FILE = SAKURA_DIR / "tts_corrections.json"


def _sakura_load_corrections() -> list:
    if _SAKURA_CORRECTIONS_FILE.exists():
        with open(_SAKURA_CORRECTIONS_FILE, encoding="utf-8") as f:
            return json.load(f).get("corrections", [])
    return []


def _sakura_save_corrections(new_pairs: list):
    """新しい修正ペアを既存ファイルにマージして保存（同一originalは上書き）"""
    existing = {c["original"]: c["corrected"] for c in _sakura_load_corrections()}
    for c in new_pairs:
        existing[c["original"]] = c["corrected"]
    with open(_SAKURA_CORRECTIONS_FILE, "w", encoding="utf-8") as f:
        json.dump(
            {"corrections": [{"original": k, "corrected": v} for k, v in existing.items()]},
            f, ensure_ascii=False, indent=2,
        )
    log.info(f"[Sakura] TTS修正を保存: {new_pairs}")


def _sakura_extract_corrections(original: str, corrected: str) -> list:
    """difflib で変更箇所を抽出して修正ペアリストを返す。
    1文字変更（濁点など）は前後2文字の文脈を含めて保存。"""
    import difflib
    pairs = []
    matcher = difflib.SequenceMatcher(None, original, corrected, autojunk=False)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag != "replace":
            continue
        orig = original[i1:i2]
        corr = corrected[j1:j2]
        if orig == corr:
            continue
        if len(orig) == 1:
            # 1文字変更は前後2文字のコンテキストを付けて保存（false positive防止）
            ctx = 2
            s_o = max(0, i1 - ctx)
            e_o = min(len(original), i2 + ctx)
            s_c = max(0, j1 - ctx)
            e_c = min(len(corrected), j2 + ctx)
            orig_ctx = original[s_o:e_o]
            corr_ctx = corrected[s_c:e_c]
            if orig_ctx != corr_ctx and len(orig_ctx) >= 3:
                pairs.append({"original": orig_ctx, "corrected": corr_ctx})
        elif len(orig) <= 20:
            pairs.append({"original": orig, "corrected": corr})
    return pairs


def _sakura_apply_corrections(text: str) -> str:
    for c in _sakura_load_corrections():
        text = text.replace(c["original"], c["corrected"])
    return text


def _sakura_tts_preview(script: str) -> str:
    import re
    sys.path.insert(0, str(BASE_DIR))
    from pipeline import fix_for_tts
    text = fix_for_tts(script)
    for num, reading in _SAKURA_NUM_MAP:
        text = re.sub(rf'(?<!\d){re.escape(num)}(?!\d)', reading, text)
    text = _sakura_apply_corrections(text)
    return text


def _sakura_start_pipeline(user_id, chosen_script, topic):
    """音声生成 → HeyGen動画 → YouTube投稿"""
    push_message(user_id, "🎬 動画を生成中です！完了したらお知らせします📹")

    def run():
        import re as re_mod
        try:
            tmp_file = SAKURA_DIR / "tmp_pipeline_script.json"
            tmp_file.write_text(
                json.dumps({"scripts": [chosen_script]}, ensure_ascii=False),
                encoding="utf-8",
            )
            result = subprocess.run(
                [sys.executable, str(SAKURA_DIR / "pipeline.py"),
                 "--script-file", str(tmp_file)],
                capture_output=True, text=True, cwd=str(BASE_DIR),
            )
            tmp_file.unlink(missing_ok=True)
            if result.returncode == 0:
                yt_urls = re_mod.findall(r"https://youtube\.com/shorts/\S+", result.stdout)
                vid_paths = re_mod.findall(r"動画生成完了（YouTube投稿スキップ中）: (\S+)", result.stdout)
                if yt_urls:
                    push_message(user_id, f"✅ サクラ動画投稿完了！\n{yt_urls[-1]}")
                elif vid_paths:
                    push_message(user_id, f"✅ 動画生成完了！（投稿スキップ中）\n保存先: {vid_paths[-1]}")
                else:
                    push_message(user_id, "✅ 動画生成完了！")
            else:
                push_message(user_id, f"⚠️ エラー:\n{result.stderr[-500:]}")
        except Exception as e:
            push_message(user_id, f"⚠️ パイプラインエラー: {e}")

    threading.Thread(target=run, daemon=True).start()


def _sakura_handle_pending(user_id, reply_token, text, session):
    sessions = load_sakura_sessions()
    scripts = session["scripts"]
    text_stripped = text.strip()
    text_lower = text_stripped.lower()

    if text_lower == "ok" or text_lower in ("1", "2", "3"):
        index = 0 if text_lower == "ok" else int(text_lower) - 1
        index = min(index, len(scripts) - 1)
        chosen_script = scripts[index]
        topic = chosen_script.get("topic", chosen_script.get("keyword", "ストレッチ"))
        tts = _sakura_tts_preview(chosen_script["script"])
        sessions[user_id] = {
            "state": "confirm",
            "selected_script": chosen_script,
            "topic": topic,
        }
        save_sakura_sessions(sessions)
        reply_message(
            reply_token,
            f"✅ テーマ「{topic}」を選択\n\n📝 台本:\n{chosen_script['script']}\n\n🔊 読み上げ（TTS）:\n{tts}\n\n─────────────────\nOK → 動画生成開始\n読み上げを修正 → 修正後の全文を送信\nNG → 台本を再生成",
        )
        log.info(f"[Sakura] 台本選択・確認待機: topic={topic}")

    elif text_lower.startswith("ng"):
        instruction = text_stripped[2:].lstrip(":： ").strip()
        reply_message(reply_token, "❌ 却下しました。台本を再生成して送り直します...")
        sessions.pop(user_id, None)
        save_sakura_sessions(sessions)

        def regenerate_and_notify():
            env = os.environ.copy()
            if instruction:
                env["REGENERATE_INSTRUCTION"] = instruction
            result = subprocess.run(
                [sys.executable, str(SAKURA_DIR / "generate_script.py")],
                env=env, cwd=str(BASE_DIR),
            )
            if result.returncode == 0:
                subprocess.run(
                    [sys.executable, str(SAKURA_DIR / "notify_line.py"), "--send"],
                    cwd=str(BASE_DIR),
                )
            else:
                push_message(user_id, "⚠️ 台本の再生成に失敗しました。")

        threading.Thread(target=regenerate_and_notify, daemon=True).start()

    else:
        reply_message(reply_token, "返信は OK / 1 / 2 / 3 / NG のいずれかで送ってください。")


def _sakura_handle_confirm(user_id, reply_token, text, session):
    sessions = load_sakura_sessions()
    text_stripped = text.strip()
    text_lower = text_stripped.lower()
    chosen_script = dict(session["selected_script"])
    topic = session["topic"]

    if text_lower == "ok":
        sessions.pop(user_id, None)
        save_sakura_sessions(sessions)
        reply_message(reply_token, f"✅ 「{topic}」で動画生成を開始します！")
        log.info(f"[Sakura] 動画生成開始: topic={topic}")
        _sakura_start_pipeline(user_id, chosen_script, topic)

    elif text_lower.startswith("ng"):
        sessions.pop(user_id, None)
        save_sakura_sessions(sessions)
        reply_message(reply_token, "❌ 却下しました。台本を再生成して送り直します...")

        def regenerate_and_notify():
            result = subprocess.run(
                [sys.executable, str(SAKURA_DIR / "generate_script.py")],
                cwd=str(BASE_DIR),
            )
            if result.returncode == 0:
                subprocess.run(
                    [sys.executable, str(SAKURA_DIR / "notify_line.py"), "--send"],
                    cwd=str(BASE_DIR),
                )
            else:
                push_message(user_id, "⚠️ 台本の再生成に失敗しました。")

        threading.Thread(target=regenerate_and_notify, daemon=True).start()

    else:
        # 元のTTSプレビューと比較して修正ペアを抽出・保存
        original_tts = _sakura_tts_preview(chosen_script["script"])
        new_pairs = _sakura_extract_corrections(original_tts, text_stripped)
        if new_pairs:
            _sakura_save_corrections(new_pairs)
            learned = "、".join(f"{c['original']}→{c['corrected']}" for c in new_pairs)
            learned_msg = f"\n📚 学習した修正: {learned}"
        else:
            learned_msg = ""

        chosen_script["audio_text"] = text_stripped
        sessions[user_id] = {
            "state": "confirm",
            "selected_script": chosen_script,
            "topic": topic,
        }
        save_sakura_sessions(sessions)
        reply_message(
            reply_token,
            f"✅ 修正しました！{learned_msg}\n\n🔊 読み上げ文章:\n{text_stripped}\n\n─────────────────\nOK → 動画生成開始\n修正する場合 → もう一度全文を送信",
        )
        log.info(f"[Sakura] 読み上げ文章修正: topic={topic}, learned={new_pairs}")


def handle_sakura_approval(user_id, reply_token, text):
    """Sakuraセッションがあれば処理してTrueを返す。なければFalse。"""
    sessions = load_sakura_sessions()
    session = sessions.get(user_id)
    if not session:
        return False
    state = session.get("state", "pending")
    if state == "confirm":
        _sakura_handle_confirm(user_id, reply_token, text, session)
    else:
        _sakura_handle_pending(user_id, reply_token, text, session)
    return True


# ──────────────────────────────────────────────────────────────────────────────

def handle_approval(user_id, reply_token, text):
    # Sakuraセッションを優先チェック（8080の単一webhookで両チャンネルを捌く）
    if handle_sakura_approval(user_id, reply_token, text):
        return
    sessions = load_sessions()
    session = sessions.get(user_id)
    if not session:
        reply_message(reply_token, "承認待ちの台本がありません。先にスケジューラーを実行してください。")
        return
    state = session.get("state", "pending")
    if state == "pronunciation":
        _handle_pronunciation(user_id, reply_token, text, session)
    elif state == "editing":
        _handle_editing(user_id, reply_token, text, session)
    else:
        _handle_pending(user_id, reply_token, text, session)



@app.route("/run_pipeline", methods=["POST"])
def run_pipeline_endpoint():
    import subprocess, sys
    data = request.json
    script_path = data.get("script_path")
    user_id = data.get("user_id")
    keyword = data.get("keyword")
    subprocess.Popen([sys.executable, "/Users/user/youtube-factory/pipeline.py", script_path or "", user_id or "", keyword or ""])
    return {"status": "started"}, 200
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


# ─── Hana投稿スケジューラー ───────────────────────────────────────────────────

def _run_hana_post():
    log.info("[Hana] X投稿開始")
    LINE_USER_ID = os.getenv("LINE_USER_ID") or os.getenv("LINE_NOTIFY_USER_ID")
    result = subprocess.run(
        [sys.executable, str(BASE_DIR / "hana_x" / "post_x.py")],
        capture_output=True, text=True, cwd=str(BASE_DIR),
    )
    if result.returncode != 0:
        log.error(f"[Hana] X投稿失敗: {result.stderr[-300:]}")
        if LINE_USER_ID:
            push_message(LINE_USER_ID, f"⚠️ Hana X投稿失敗\n{result.stderr[-200:]}")
    else:
        log.info("[Hana] X投稿完了")
        if LINE_USER_ID:
            posted = result.stdout.strip()[-200:]
            push_message(LINE_USER_ID, f"✅ Hana X投稿完了\n{posted}")


def _start_hana_scheduler():
    # UTC時刻（JST-9h）
    schedule.every().day.at("22:00").do(_run_hana_post)  # JST 7:00
    schedule.every().day.at("00:00").do(_run_hana_post)  # JST 9:00
    schedule.every().day.at("02:30").do(_run_hana_post)  # JST 11:30
    schedule.every().day.at("08:00").do(_run_hana_post)  # JST 17:00
    schedule.every().day.at("11:00").do(_run_hana_post)  # JST 20:00

    def loop():
        while True:
            schedule.run_pending()
            time.sleep(30)

    threading.Thread(target=loop, daemon=True).start()
    log.info("[Hana] スケジューラー起動（UTC 22:00/00:00/02:30/08:00/11:00）")


_start_hana_scheduler()

# ──────────────────────────────────────────────────────────────────────────────

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
