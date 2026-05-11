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
    if not LINE_CHANNEL_SECRET:
        log.warning("LINE_CHANNEL_SECRET が未設定。署名検証をスキップします")
        return True
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


def _sanitize_for_json(obj):
    """制御文字を除去してJSONエンコードエラーを防ぐ"""
    import re
    if isinstance(obj, str):
        return re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', '', obj)
    elif isinstance(obj, dict):
        return {k: _sanitize_for_json(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [_sanitize_for_json(i) for i in obj]
    return obj


def _start_pipeline(user_id, chosen_script):
    push_message(user_id, "動画生成を開始します！完了したらお知らせします📹")

    def run():
        try:
            tmp_file = BASE_DIR / "tmp_pipeline_script.json"
            tmp_file.write_bytes(
                json.dumps({"scripts": [_sanitize_for_json(chosen_script)]}, ensure_ascii=True).encode("ascii")
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

        sys.path.insert(0, str(BASE_DIR))
        from pipeline import to_hiragana, fix_for_tts
        audio_tts = fix_for_tts(chosen_script["script"])
        audio_preview = to_hiragana(chosen_script["script"])

        sessions[user_id] = {
            "state": "confirm",
            "selected_script": chosen_script,
            "audio_text": audio_tts,
            "audio_preview": audio_preview,
            "script_path": session.get("script_path", ""),
        }
        save_sessions(sessions)

        msg = (
            f"✅ 「{keyword}」を選択しました！\n\n"
            f"🔊 読み上げ（ひらがな）:\n{audio_preview}\n\n"
            "─────────────────\n"
            "「確定」→ このまま動画生成\n"
            "修正 → 修正後の読み上げ全文を送信\n"
            "NG → 再生成"
        )
        reply_message(reply_token, msg)
        log.info(f"台本選択・発音確認待機: keyword={keyword}")

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


def _handle_confirm(user_id, reply_token, text, session):
    """台本＋読み方確認ステート：OK→生成、テスト→読み方修正、NG→再生成"""
    sessions = load_sessions()
    text_stripped = text.strip()
    text_lower = text_stripped.lower()
    chosen_script = dict(session["selected_script"])

    if text_lower in ("ok", "確定", "start"):
        sys.path.insert(0, str(BASE_DIR))
        from pipeline import extract_and_save_corrections
        chosen_script["audio_text"] = session.get("audio_text", "")
        save_script_to_txt(chosen_script)
        sessions.pop(user_id, None)
        save_sessions(sessions)
        reply_message(reply_token, "✅ 制作開始します！")
        log.info(f"制作開始: keyword={chosen_script['keyword']}")
        _start_pipeline(user_id, chosen_script)

    elif text_lower.startswith("ng"):
        sessions.pop(user_id, None)
        save_sessions(sessions)
        reply_message(reply_token, "❌ 却下しました。台本を再生成して送り直します...")

        def regenerate_and_notify():
            subprocess.run(
                [sys.executable, str(BASE_DIR / "1_scripts" / "generate_script.py")],
                cwd=str(BASE_DIR),
            )
            try:
                send_notification(user_id)
            except Exception:
                push_message(user_id, "⚠️ 再生成しましたが通知送信に失敗しました。")

        threading.Thread(target=regenerate_and_notify, daemon=True).start()

    else:
        # 読み方修正
        sys.path.insert(0, str(BASE_DIR))
        from pipeline import extract_and_save_corrections
        original_tts = session.get("audio_text", "")
        if original_tts and text_stripped != original_tts:
            extract_and_save_corrections(original_tts, text_stripped)
            log.info(f"TTS補正を学習しました")

        sessions[user_id] = {
            "state": "confirm",
            "selected_script": chosen_script,
            "audio_text": text_stripped,
            "audio_preview": text_stripped,
            "script_path": session.get("script_path", ""),
        }
        save_sessions(sessions)
        reply_message(
            reply_token,
            f"✅ 読み方を修正しました！\n\n🔊 読み上げ:\n{text_stripped}\n\n─────────────────\nOK → 動画生成開始\n修正する場合 → もう一度全文を送信"
        )


# ─── Sakura（朝ストレッチ）セッション処理 ─────────────────────────────────

SAKURA_DIR = BASE_DIR / "sakura"
# Use BASE_DIR (always writable in container) instead of DATA_DIR which may not exist
SAKURA_SESSIONS_FILE = BASE_DIR / "sakura_sessions.json"
SAKURA_LATEST_SCRIPTS_FILE = BASE_DIR / "sakura_latest_scripts.json"

# In-memory cache: survives request-to-request within the same process
_sakura_sessions_cache: dict = {}


def load_sakura_sessions() -> dict:
    if _sakura_sessions_cache:
        return dict(_sakura_sessions_cache)
    # Fall back to file (populated on previous run before restart)
    if SAKURA_SESSIONS_FILE.exists():
        try:
            with open(SAKURA_SESSIONS_FILE, encoding="utf-8") as f:
                data = json.load(f)
            _sakura_sessions_cache.update(data)
            return dict(_sakura_sessions_cache)
        except Exception as e:
            log.warning(f"セッションファイル読み込み失敗: {e}")
    return {}


def save_sakura_sessions(sessions: dict) -> None:
    _sakura_sessions_cache.clear()
    _sakura_sessions_cache.update(sessions)
    try:
        with open(SAKURA_SESSIONS_FILE, "w", encoding="utf-8") as f:
            json.dump(sessions, f, ensure_ascii=False, indent=2)
    except Exception as e:
        log.warning(f"セッションファイル保存失敗（メモリには保存済み）: {e}")


_SAKURA_NUM_MAP = [
    ("10", "じゅう"), ("9", "く"), ("8", "はち"), ("7", "なな"),
    ("6", "ろく"), ("5", "ご"), ("4", "し"), ("3", "さん"),
    ("2", "に"), ("1", "いち"),
]

_SAKURA_CORRECTIONS_FILE = SAKURA_DIR / "tts_corrections.json"


def _sakura_commit_corrections_to_github(content: str):
    """tts_corrections.jsonをGitHub APIで直接コミット（デプロイをまたいで永続化）"""
    token = os.getenv("GITHUB_TOKEN", "")
    repo = os.getenv("GITHUB_REPO", "ryokumano67-pixel/ryo-factory")
    if not token:
        log.warning("[Sakura] GITHUB_TOKEN未設定のためTTS修正はデプロイ後にリセットされます")
        return
    import base64 as _b64
    path = "sakura/tts_corrections.json"
    api = f"https://api.github.com/repos/{repo}/contents/{path}"
    headers = {"Authorization": f"token {token}", "Accept": "application/vnd.github.v3+json"}
    # 現在のSHAを取得
    r = requests.get(api, headers=headers, timeout=10)
    sha = r.json().get("sha", "") if r.ok else ""
    body = {
        "message": "Auto-update TTS corrections via LINE",
        "content": _b64.b64encode(content.encode()).decode(),
        "branch": "main",
    }
    if sha:
        body["sha"] = sha
    resp = requests.put(api, headers=headers, json=body, timeout=10)
    if resp.ok:
        log.info("[Sakura] TTS修正をGitHubにコミットしました")
    else:
        log.warning(f"[Sakura] GitHubコミット失敗: {resp.status_code} {resp.text[:100]}")


def _sakura_load_corrections() -> list:
    if _SAKURA_CORRECTIONS_FILE.exists():
        with open(_SAKURA_CORRECTIONS_FILE, encoding="utf-8") as f:
            return json.load(f).get("corrections", [])
    return []


def _sakura_save_corrections(new_pairs: list):
    """新しい修正ペアを既存ファイルにマージして保存（同一originalは上書き）。GitHubにも自動コミット。"""
    existing = {c["original"]: c["corrected"] for c in _sakura_load_corrections()}
    for c in new_pairs:
        existing[c["original"]] = c["corrected"]
    content = json.dumps(
        {"corrections": [{"original": k, "corrected": v} for k, v in existing.items()]},
        ensure_ascii=False, indent=2,
    )
    with open(_SAKURA_CORRECTIONS_FILE, "w", encoding="utf-8") as f:
        f.write(content)
    log.info(f"[Sakura] TTS修正を保存: {new_pairs}")
    # GitHub APIで自動コミット（デプロイをまたいでも修正が残るように）
    _sakura_commit_corrections_to_github(content)


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
    """音声生成 → HeyGen動画 → YouTube投稿（Fitness） + Kaizen英語版を並走"""
    push_message(user_id, "🎬 動画を生成中です！Fitness＋Kaizen英語版を同時制作します📹")

    def run():
        import re as re_mod
        try:
            tmp_file = SAKURA_DIR / "tmp_pipeline_script.json"
            tmp_file.write_bytes(
                json.dumps({"scripts": [_sanitize_for_json(chosen_script)]}, ensure_ascii=True).encode("ascii")
            )
            result = subprocess.run(
                [sys.executable, str(SAKURA_DIR / "pipeline.py"),
                 "--script-file", str(tmp_file)],
                capture_output=True, text=True, cwd=str(BASE_DIR),
            )
            tmp_file.unlink(missing_ok=True)
            if result.returncode == 0:
                scheduled_urls = re_mod.findall(r"YouTube予約完了.*?(https://youtube\.com/shorts/\S+)", result.stdout)
                yt_urls = re_mod.findall(r"YouTube投稿完了.*?(https://youtube\.com/shorts/\S+)", result.stdout)
                vid_paths = re_mod.findall(r"動画生成完了（YouTube投稿スキップ中）: (\S+)", result.stdout)
                comment_ok = "コメント投稿完了" in result.stdout
                comment_fail = re_mod.search(r"コメント投稿エラー.+?[:：](.+)", result.stdout)
                comment_status = "💬 コメント済み" if comment_ok else (f"⚠️ コメント未投稿: {comment_fail.group(1)[:80]}" if comment_fail else "💬 コメント未確認")
                if scheduled_urls:
                    push_message(user_id, f"✅ Fitness予約完了！明朝6時JST公開🌸\n{scheduled_urls[-1]}\n{comment_status}")
                elif yt_urls:
                    push_message(user_id, f"✅ Fitness投稿完了！\n{yt_urls[-1]}\n{comment_status}")
                elif vid_paths:
                    push_message(user_id, f"✅ Fitness動画生成完了！（スキップ中）\n{vid_paths[-1]}")
                else:
                    push_message(user_id, "✅ Fitness動画生成完了！")
            else:
                err_out = (result.stdout[-300:] + "\n---\n" + result.stderr[-1000:]).strip()
                push_message(user_id, f"⚠️ Fitnessエラー:\n{err_out}")
        except Exception as e:
            push_message(user_id, f"⚠️ Fitnessパイプラインエラー: {e}")

    def run_kaizen():
        try:
            sys.path.insert(0, str(BASE_DIR))
            from sakura.pipeline import run_kaizen_pipeline
            tags = chosen_script.get("tags", [])
            yt_id = run_kaizen_pipeline(
                topic=topic,
                japanese_script=chosen_script.get("audio_text") or chosen_script["script"],
                tags=tags,
            )
            if yt_id:
                push_message(user_id, f"✅ Kaizen英語版予約完了！朝6時PST公開🌿\nhttps://youtube.com/shorts/{yt_id}")
            else:
                push_message(user_id, "✅ Kaizen英語版動画生成完了！（スキップ中）")
        except Exception as e:
            push_message(user_id, f"⚠️ Kaizenエラー: {e}")

    threading.Thread(target=run, daemon=True).start()
    threading.Thread(target=run_kaizen, daemon=True).start()


def _sakura_regen_and_notify(user_id: str, instruction: str = "") -> None:
    """台本を再生成してLINEに送信し、同プロセスのセッションに保存する。
    NG却下・「生成」コマンド共通のサブルーチン。"""
    try:
        env = os.environ.copy()
        if instruction:
            env["REGENERATE_INSTRUCTION"] = instruction
        result = subprocess.run(
            [sys.executable, str(SAKURA_DIR / "generate_script.py")],
            env=env, capture_output=True, text=True, cwd=str(BASE_DIR), timeout=120,
        )
        if result.returncode != 0:
            err = (result.stdout[-200:] + result.stderr[-300:]).strip()
            push_message(user_id, f"⚠️ 台本再生成失敗:\n{err}")
            return
        scripts_dir = SAKURA_DIR / "scripts"
        json_files = sorted(scripts_dir.glob("scripts_*.json"), reverse=True)
        if not json_files:
            push_message(user_id, "⚠️ 台本ファイルが見つかりません。")
            return
        with open(json_files[0], encoding="utf-8") as f:
            data = json.load(f)
        scripts = data.get("scripts", [])
        script_path = str(json_files[0])
        sessions = load_sakura_sessions()
        sessions[user_id] = {"scripts": scripts, "script_path": script_path}
        save_sakura_sessions(sessions)
        try:
            with open(SAKURA_LATEST_SCRIPTS_FILE, "w", encoding="utf-8") as f:
                json.dump({"user_id": user_id, "scripts": scripts, "script_path": script_path}, f, ensure_ascii=False, indent=2)
        except Exception:
            pass
        sys.path.insert(0, str(BASE_DIR))
        from sakura.notify_line import build_notification_text
        text = build_notification_text(scripts)
        for chunk in [text[i:i + 4900] for i in range(0, len(text), 4900)]:
            push_message(user_id, chunk)
        log.info(f"[Sakura] 台本再生成→通知完了: {user_id}")
    except Exception as e:
        push_message(user_id, f"⚠️ 再生成エラー: {e}")


def _sakura_handle_pending(user_id, reply_token, text, session):
    sessions = load_sakura_sessions()
    scripts = session["scripts"]
    text_stripped = text.strip()
    text_lower = text_stripped.lower()

    if text_lower in ("1", "2", "3"):
        index = int(text_lower) - 1
        index = min(index, len(scripts) - 1)
        chosen_script = scripts[index]
        topic = chosen_script.get("topic", chosen_script.get("keyword", "ストレッチ"))
        tts = _sakura_tts_preview(chosen_script["script"])
        chosen_script["audio_text"] = tts

        # 読み上げ確認ステップへ遷移（まだ動画生成しない）
        sessions[user_id] = {
            "state": "confirm",
            "selected_script": chosen_script,
            "topic": topic,
        }
        save_sakura_sessions(sessions)

        reply_message(
            reply_token,
            f"🔊 「{topic}」の読み上げ確認:\n\n{tts}\n\n─────────────────\nOK → 動画生成開始\nNG → 台本を再生成\n読み方を直す → 正しい読み上げ文章を全文送信",
        )

    elif text_lower.startswith("ng"):
        instruction = text_stripped[2:].lstrip(":： ").strip()
        reply_message(reply_token, "❌ 却下しました。台本を再生成して送り直します...")
        sessions.pop(user_id, None)
        save_sakura_sessions(sessions)
        threading.Thread(target=_sakura_regen_and_notify, args=(user_id, instruction), daemon=True).start()

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
        threading.Thread(target=_sakura_regen_and_notify, args=(user_id, ""), daemon=True).start()

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


def _sakura_restore_session_from_backup(user_id) -> bool:
    """再起動後などにセッションが失われた場合、最新台本バックアップからセッションを復元する。"""
    if not SAKURA_LATEST_SCRIPTS_FILE.exists():
        return False
    try:
        with open(SAKURA_LATEST_SCRIPTS_FILE, encoding="utf-8") as f:
            data = json.load(f)
        if data.get("user_id") != user_id:
            return False
        sessions = load_sakura_sessions()
        sessions[user_id] = {"scripts": data["scripts"], "script_path": data.get("script_path", "")}
        save_sakura_sessions(sessions)
        log.info(f"[Sakura] バックアップからセッション復元: {user_id}")
        return True
    except Exception as e:
        log.warning(f"セッション復元失敗: {e}")
        return False


def handle_sakura_approval(user_id, reply_token, text):
    """Sakuraセッションがあれば処理してTrueを返す。なければFalse。"""
    sessions = load_sakura_sessions()
    session = sessions.get(user_id)
    if not session:
        # 「再送」コマンド: バックアップから台本を再送信
        if text.strip() in ("再送", "resend", "再通知"):
            if _sakura_restore_session_from_backup(user_id):
                sessions2 = load_sakura_sessions()
                session2 = sessions2.get(user_id)
                if session2:
                    sys.path.insert(0, str(BASE_DIR))
                    from sakura.notify_line import build_notification_text
                    notification = build_notification_text(session2["scripts"])
                    for chunk in [notification[i:i + 4900] for i in range(0, len(notification), 4900)]:
                        push_message(user_id, chunk)
                    reply_message(reply_token, "📨 前回の台本を再送しました。OK/1/2/3 で承認してください。")
                    return True
            reply_message(reply_token, "⚠️ 再送できる台本がありません。スケジューラーを再実行してください。")
            return True
        return False
    state = session.get("state", "pending")
    if state == "confirm":
        _sakura_handle_confirm(user_id, reply_token, text, session)
    else:
        _sakura_handle_pending(user_id, reply_token, text, session)
    return True


# ──────────────────────────────────────────────────────────────────────────────

def _sakura_trigger_generate(user_id, reply_token):
    """台本をその場で生成してLINEに送信し、承認セッションを作成する。"""
    reply_message(reply_token, "🌸 台本を生成中です（30〜60秒かかります）...")
    threading.Thread(target=_sakura_regen_and_notify, args=(user_id, ""), daemon=True).start()


def handle_approval(user_id, reply_token, text):
    # 「生成」コマンド: その場で台本生成→送信（セッション不要）
    if text.strip() in ("生成", "台本生成", "generate"):
        _sakura_trigger_generate(user_id, reply_token)
        return
    # Sakuraセッションを優先チェック（8080の単一webhookで両チャンネルを捌く）
    if handle_sakura_approval(user_id, reply_token, text):
        return
    sessions = load_sessions()
    session = sessions.get(user_id)
    if not session:
        reply_message(reply_token, "承認待ちの台本がありません。\n「生成」と送ると今すぐ台本を作成します📝")
        return
    state = session.get("state", "pending")
    if state == "confirm":
        _handle_confirm(user_id, reply_token, text, session)
    elif state == "pronunciation":
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


@app.route("/health", methods=["GET"])
def health():
    return {
        "status": "ok",
        "line_access_token": bool(LINE_CHANNEL_ACCESS_TOKEN),
        "line_channel_secret": bool(LINE_CHANNEL_SECRET),
        "sakura_sessions": len(_sakura_sessions_cache),
    }, 200


@app.route("/webhook", methods=["POST"])
def webhook():
    log.info(f"[webhook] リクエスト受信 method={request.method} path={request.path}")
    signature = request.headers.get("X-Line-Signature", "")
    body = request.get_data()
    if not verify_signature(body, signature):
        log.warning(f"[webhook] 署名検証失敗 sig={signature[:20]}")
        abort(400)
    try:
        data = json.loads(body)
    except Exception as e:
        log.error(f"[webhook] JSON解析失敗: {e} body={body[:200]}")
        return "OK", 200
    log.info(f"[webhook] events={len(data.get('events', []))}")
    for event in data.get("events", []):
        if event.get("type") != "message":
            log.info(f"[webhook] 非メッセージイベント: {event.get('type')}")
            continue
        if event["message"].get("type") != "text":
            continue
        user_id = event["source"]["userId"]
        reply_token = event["replyToken"]
        text = event["message"]["text"]
        log.info(f"[webhook] メッセージ受信: user={user_id} text={text!r}")
        handle_approval(user_id, reply_token, text)
    return "OK", 200


@app.route("/notify/<user_id>", methods=["POST"])
def notify(user_id):
    try:
        body = request.get_json(silent=True) or {}
        if body.get("scripts"):
            # Cron Jobコンテナからスクリプトデータを受け取った場合
            scripts = body["scripts"]
            script_path = body.get("script_path", "")
            text = build_notification_text(scripts)
            for chunk in [text[i:i + 4900] for i in range(0, len(text), 4900)]:
                push_message(user_id, chunk)
            sessions = load_sessions()
            sessions[user_id] = {"scripts": scripts, "script_path": script_path}
            save_sessions(sessions)
            log.info(f"台本通知を送信しました（POSTデータ使用） → {user_id}")
        else:
            send_notification(user_id)
        return {"status": "sent"}, 200
    except FileNotFoundError as e:
        return {"error": str(e)}, 404
    except Exception as e:
        return {"error": str(e)}, 500


@app.route("/sakura/notify/<user_id>", methods=["POST"])
def sakura_notify(user_id):
    try:
        body = request.get_json(silent=True) or {}
        if body.get("scripts"):
            # Cron Jobコンテナからスクリプトデータを受け取った場合
            scripts = body["scripts"]
            script_path = body.get("script_path", "")
        else:
            sys.path.insert(0, str(BASE_DIR))
            from sakura.notify_line import load_latest_scripts
            scripts_list, script_path_obj = load_latest_scripts()
            scripts = scripts_list
            script_path = str(script_path_obj)
        sys.path.insert(0, str(BASE_DIR))
        from sakura.notify_line import build_notification_text
        text = build_notification_text(scripts)
        for chunk in [text[i:i + 4900] for i in range(0, len(text), 4900)]:
            push_message(user_id, chunk)
        sessions = load_sakura_sessions()
        sessions[user_id] = {"scripts": scripts, "script_path": script_path}
        save_sakura_sessions(sessions)
        # Persist latest scripts as fallback for recovery after restart
        try:
            with open(SAKURA_LATEST_SCRIPTS_FILE, "w", encoding="utf-8") as f:
                json.dump({"user_id": user_id, "scripts": scripts, "script_path": script_path}, f, ensure_ascii=False, indent=2)
        except Exception as e:
            log.warning(f"最新台本バックアップ保存失敗: {e}")
        log.info(f"[Sakura] 台本通知送信 → {user_id}")
        return {"status": "sent"}, 200
    except FileNotFoundError as e:
        return {"error": str(e)}, 404
    except Exception as e:
        return {"error": str(e)}, 500


# ─── Hana投稿スケジューラー ───────────────────────────────────────────────────

def _run_hana_post():
    log.info("[Hana] 投稿開始")
    result = subprocess.run(
        [sys.executable, str(BASE_DIR / "hana_line_post.py")],
        capture_output=True, text=True, cwd=str(BASE_DIR),
    )
    if result.returncode != 0:
        log.error(f"[Hana] 投稿失敗: {result.stderr[-300:]}")
    else:
        log.info("[Hana] 投稿完了")


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


# _start_hana_scheduler()  # 停止中

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
