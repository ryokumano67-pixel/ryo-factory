"""
sakura/pipeline.py
Claude API → ElevenLabs → HeyGen → YouTube
"""

import json
import os
import re
import sys
import time
import requests
from datetime import datetime, timedelta, timezone
from pathlib import Path
from dotenv import load_dotenv

SAKURA_DIR = Path(__file__).resolve().parent
BASE_DIR = SAKURA_DIR.parent
sys.path.insert(0, str(BASE_DIR))
load_dotenv(BASE_DIR / ".env", override=True)

VOICE_ID           = "9HdWw3q0ezIc6HGblORv"  # Sakura日本語音声
KAIZEN_VOICE_ID    = os.getenv("KAIZEN_VOICE_ID", "EXAVITQu4vr4xnSDxMaL")  # Bella（英語）
HEYGEN_AVATAR_ID   = "b7788b99bfc8490f8bffd2afcc4e1481"
HEYGEN_API_KEY     = os.getenv("HEYGEN_API_KEY")
ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY")

# Sakuraのlook IDリスト（26パターン自動ローテーション）
SAKURA_LOOK_IDS: list[str] = [
    "19b219a01a184896a58ba3278ed17fbc",
    "409d554aae4a41d1bd6e89b9328c33ad",
    "8d05ba743d9f4f73ae911253626299a2",
    "19b219a01a184896a58ba3278ed17fbc",
    "b7788b99bfc8490f8bffd2afcc4e1481",
    "d71fafa24d534afc9a2b96d85954e9b9",
    "9803acfedee9436593ccc304896b572c",
    "9f7ab592b5fc4c379c0fa893813f2a30",
    "a40657822b9c428d87acbfcad0a50efa",
    "65db942f6325489eb79ce7068d5c543d",
    "04c23c4fccca4d9f86a7cf4224b62273",
    "d15124fb22a74e8f84c33e0ed8b5a17d",
    "2a30bb30d2ec44cda976c745c8ae0951",
    "c4729439b90f4626b77aa6b6434f7a62",
    "dcbd425585514c6f9cfce4e80a0166bf",
    "515b22213deb4cf686d3b3242a43ea83",
    "0ed4b4a0fd3e4cbcaee024835e3e1eab",
    "bb2a815527d947e69bea0cc729286639",
    "3aa8b27c16b14670b93829513abc8a0d",
    "61a8e9491db44f0a9b1c343112f6ba27",
    "e4a7e9ef904249d1bd91b7496dc8e831",
    "57510ac5971b4930bacd9e41200f62c3",
    "60ea97d4b6fe4b1aa112d75fe5abdf76",
    "dddddc6248a04a39a7b1b2b054f4c458",
    "a61df49c834141fbbf9e94534561fab7",
    "70a35d682b844639a33e06aa644477f5",
]

KAIZEN_AVATAR_ID = "03c8db932875431c998c292c2240b411"  # Sakura Kaizen英語チャンネル用

# 背景カラーローテーション（ピンクメイン＋アクセント）
BACKGROUND_COLORS = [
    "#FFB6C1",  # ライトピンク
    "#FFC0CB",  # ピンク
    "#FFD1DC",  # ペールピンク
    "#FFFFFF",  # 白（清潔感）
    "#FFB6C1",  # ライトピンク
    "#FFF0F5",  # ラベンダーブラッシュ
    "#FFD1DC",  # ペールピンク
    "#FFF5EE",  # シーシェル（ピーチ）
    "#FFB6C1",  # ライトピンク
    "#F8F0FF",  # ラベンダー
]

SKIP_YOUTUBE_UPLOAD = os.getenv("SAKURA_SKIP_UPLOAD", "true").lower() != "false"

RAKUTEN_ROOM_URL = "https://room.rakuten.co.jp/room_sakura-fitness-ai/items"
YOUTUBE_CHANNEL_URL = "https://www.youtube.com/@sakura_stretch"
TIKTOK_URL = "https://www.tiktok.com/@sakura_stretch"
INSTAGRAM_URL = "https://www.instagram.com/sakura_stretch_official"

DESCRIPTION_TEMPLATE = """{description}

今日は「{topic}」をやるよ！
朝の60秒、サクラと一緒にやってみてね🌸

─────────────────────
📌 毎朝6:00 新作ショート更新中
チャンネル登録＋🔔通知ONで見逃しゼロ！
→ {channel_url}
─────────────────────

🛒 サクラ愛用ストレッチグッズ【楽天ROOM】
▶ ヨガマット / フォームローラー / ストレッチポール
→ {rakuten_url}

※リンクから購入いただくとサクラの活動を応援できます🙏

─────────────────────
📱 TikTok・Instagramも毎日更新中！
▶ TikTok → {tiktok_url}
▶ Instagram → {instagram_url}
─────────────────────

{tags_str}"""

from pipeline import upload_audio

import re as _re

_NUM_MAP = [
    ("10", "じゅう"), ("9", "く"), ("8", "はち"), ("7", "なな"),
    ("6", "ろく"), ("5", "ご"), ("4", "し"), ("3", "さん"),
    ("2", "に"), ("1", "いち"),
]


def replace_numbers(text: str) -> str:
    for num, reading in _NUM_MAP:
        text = _re.sub(rf'(?<!\d){_re.escape(num)}(?!\d)', reading, text)
    return text


def apply_tts_corrections(text: str) -> str:
    corrections_file = SAKURA_DIR / "tts_corrections.json"
    if not corrections_file.exists():
        return text
    with open(corrections_file, encoding="utf-8") as f:
        corrections = json.load(f).get("corrections", [])
    for c in corrections:
        text = text.replace(c["original"], c["corrected"])
    return text


SYSTEM_PROMPT = """あなたは「サクラ」という、明るく親しみやすい20代女性のAIフィットネストレーナーです。
視聴者に直接話しかけるような、テンポよく自然な話し言葉で60秒の台本を書いてください。

制約:
- 尺: 約60秒（160〜200字）
- 「おはよう！」または「こんばんは！」から始める（テーマに合わせて）
- 友達に話しかけるような自然な口語（「〜だよ」「〜しようね」「〜してみて」「〜だよね」など）
- 書き言葉・説明文調は絶対に使わない（「〜します」「〜してください」を多用しない）
- 「ね」「よ」「よね」「かな」「だよ」などの語尾を自然に混ぜる
- 具体的な動作を伝える（「右腕を〜」「ゆっくり〜」など）
- ストレッチポーズをキープする場面では「1... 2... 3... 4... 5... 6... 7... 8... 9... 10」とカウントする（1ポーズ1回）。数字の間の「...」は必須（ポーズのため）
- 最後はポジティブな一言で締める
- 読点「、」を多めに入れて自然な間を作る
- 1文は15〜20文字を目安に短く切る

出力は以下のJSONのみ（コードブロック不要）:
{
  "script": "台本全文",
  "title": "動画タイトル（30字以内）",
  "description": "説明文（100字程度）",
  "tags": ["タグ1", "タグ2", "タグ3", "タグ4", "タグ5"]
}"""


def generate_script(topic: str) -> dict:
    import anthropic
    client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
    msg = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1000,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": f"テーマ: {topic}"}],
    )
    raw = msg.content[0].text.strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", raw, re.DOTALL)
        if m:
            return json.loads(m.group())
        raise


def generate_audio(text: str, output_path: Path, voice_id: str = VOICE_ID) -> Path:
    url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
    headers = {"xi-api-key": ELEVENLABS_API_KEY, "Content-Type": "application/json"}
    payload = {
        "text": text,
        "model_id": "eleven_multilingual_v2",
        "voice_settings": {
            "stability": 0.35,
            "similarity_boost": 0.75,
            "style": 0.55,
            "use_speaker_boost": True,
            "speed": 0.92,
        },
    }
    resp = requests.post(url, headers=headers, json=payload, timeout=60)
    if not resp.ok:
        raise Exception(f"ElevenLabs error: {resp.status_code} {resp.text}")
    output_path.write_bytes(resp.content)
    print(f"音声生成完了: {output_path}")
    return output_path


def _pick_avatar_id(index: int) -> str:
    if SAKURA_LOOK_IDS:
        return SAKURA_LOOK_IDS[index % len(SAKURA_LOOK_IDS)]
    return HEYGEN_AVATAR_ID


def _pick_background(index: int) -> dict:
    color = BACKGROUND_COLORS[index % len(BACKGROUND_COLORS)]
    return {"type": "color", "value": color}


def generate_heygen_video(audio_url: str, index: int = 0) -> str:
    url = "https://api.heygen.com/v2/video/generate"
    headers = {"X-Api-Key": HEYGEN_API_KEY, "Content-Type": "application/json"}
    avatar_id = _pick_avatar_id(index)
    background = _pick_background(index)
    print(f"  avatar_id: {avatar_id}  background: {background['value']}")
    payload = {
        "video_inputs": [{
            "character": {
                "type": "avatar",
                "avatar_id": avatar_id,
                "avatar_style": "normal",
            },
            "voice": {"type": "audio", "audio_url": audio_url},
            "background": background,
        }],
        "dimension": {"width": 720, "height": 1280},
        "aspect_ratio": "9:16",
    }
    resp = requests.post(url, headers=headers, json=payload, timeout=60)
    if not resp.ok:
        raise Exception(f"HeyGen error: {resp.status_code} {resp.text}")
    video_id = resp.json()["data"]["video_id"]
    print(f"HeyGen動画生成開始: {video_id}")
    return video_id


def wait_heygen(video_id: str, max_wait: int = 1200) -> str:
    print("HeyGenレンダリング待機中...")
    url = f"https://api.heygen.com/v1/video_status.get?video_id={video_id}"
    headers = {"X-Api-Key": HEYGEN_API_KEY}
    for i in range(max_wait // 10):
        time.sleep(10)
        resp = requests.get(url, headers=headers, timeout=30)
        if not resp.ok:
            continue
        data = resp.json().get("data", {})
        status = data.get("status", "")
        print(f"  {status} ({(i + 1) * 10}秒)")
        if status == "completed":
            return data["video_url"]
        if status == "failed":
            raise Exception(f"HeyGen失敗: {data}")
    raise Exception("HeyGenタイムアウト")


def download_video(url: str, path: Path):
    resp = requests.get(url, timeout=120, stream=True)
    path.write_bytes(resp.content)
    print(f"動画ダウンロード完了: {path}")


def generate_thumbnail(video_path: Path, title: str, topic: str, index: int = 0) -> Path:
    """動画の中間フレームを抽出してタイトルテキストを重ねたサムネイルを生成"""
    import subprocess
    from PIL import Image, ImageDraw, ImageFont

    thumb_path = video_path.with_suffix(".jpg")
    # 動画の5秒目からフレーム抽出（HeyGenは最初の1秒が暗い場合がある）
    subprocess.run([
        "ffmpeg", "-y", "-ss", "3", "-i", str(video_path),
        "-frames:v", "1", "-q:v", "2", str(thumb_path)
    ], check=True, capture_output=True)

    img = Image.open(thumb_path).convert("RGB")
    w, h = img.size

    draw = ImageDraw.Draw(img)

    # 上部にグラデーション帯（半透明黒→透明）
    overlay = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    ov_draw = ImageDraw.Draw(overlay)
    for y in range(200):
        alpha = int(180 * (1 - y / 200))
        ov_draw.line([(0, y), (w, y)], fill=(0, 0, 0, alpha))
    img = Image.alpha_composite(img.convert("RGBA"), overlay).convert("RGB")
    draw = ImageDraw.Draw(img)

    # フォント設定（システムフォントをフォールバック）
    font_paths = [
        "/System/Library/Fonts/ヒラギノ角ゴシック W6.ttc",
        "/System/Library/Fonts/Hiragino Sans GB.ttc",
        "/Library/Fonts/Arial Bold.ttf",
    ]
    title_font = None
    for fp in font_paths:
        try:
            title_font = ImageFont.truetype(fp, 52)
            break
        except Exception:
            pass
    if title_font is None:
        title_font = ImageFont.load_default()

    # タイトルテキスト描画（上部）
    clean_title = title.replace(" #Shorts", "").replace(" #shorts", "")
    # 長いタイトルは2行に分割
    if len(clean_title) > 16:
        mid = len(clean_title) // 2
        # 近くのスペースか句読点で切る
        for i in range(mid, min(mid + 8, len(clean_title))):
            if clean_title[i] in "　！？、。 ":
                clean_title = clean_title[:i+1] + "\n" + clean_title[i+1:]
                break
        else:
            clean_title = clean_title[:mid] + "\n" + clean_title[mid:]

    # 影付きテキスト
    for dx, dy in [(2, 2), (-2, 2), (2, -2)]:
        draw.text((30 + dx, 20 + dy), clean_title, font=title_font, fill=(0, 0, 0, 200))
    draw.text((30, 20), clean_title, font=title_font, fill=(255, 255, 255))

    # 下部にサクラブランドバー
    bar_y = h - 80
    draw.rectangle([(0, bar_y), (w, h)], fill=(255, 105, 135, 200))
    try:
        bar_font = ImageFont.truetype(font_paths[0], 36)
    except Exception:
        bar_font = ImageFont.load_default()
    draw.text((20, bar_y + 18), "🌸 AIトレーナー Sakura", font=bar_font, fill=(255, 255, 255))

    img.save(thumb_path, "JPEG", quality=90)
    print(f"サムネイル生成完了: {thumb_path}")
    return thumb_path


def _get_sakura_youtube_creds(scopes: list):
    """token ファイル → env var の順で認証情報を取得。ブラウザ不要。"""
    import json as _json
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request

    TOKEN_FILE = SAKURA_DIR / "sakura_youtube_token.json"
    token_json = None

    if TOKEN_FILE.exists():
        token_json = TOKEN_FILE.read_text(encoding="utf-8")
    else:
        token_json = os.getenv("SAKURA_YOUTUBE_TOKEN_JSON", "")

    if not token_json:
        raise RuntimeError(
            "Sakura YouTube token が見つかりません。"
            "ローカルで OAuth を実行し SAKURA_YOUTUBE_TOKEN_JSON に設定してください。"
        )

    creds = Credentials.from_authorized_user_info(_json.loads(token_json), scopes)
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        # リフレッシュしたら両方更新
        TOKEN_FILE.write_text(creds.to_json())
        # env var は書き換えられないので Render 側は次回デプロイ時に更新が必要
    return creds


def _get_kaizen_youtube_creds(scopes: list):
    """Kaizen用YouTubeクレデンシャル取得"""
    import json as _json
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request

    TOKEN_FILE = SAKURA_DIR / "kaizen_youtube_token.json"
    token_json = TOKEN_FILE.read_text(encoding="utf-8") if TOKEN_FILE.exists() else os.getenv("KAIZEN_YOUTUBE_TOKEN_JSON", "")
    if not token_json:
        raise RuntimeError("KAIZEN_YOUTUBE_TOKEN_JSON が未設定です")
    creds = Credentials.from_authorized_user_info(_json.loads(token_json), scopes)
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        TOKEN_FILE.write_text(creds.to_json())
    return creds


def _next_6am_pst() -> str:
    """次の朝6:00 PST (UTC-8) を RFC3339 形式で返す"""
    PST = timezone(timedelta(hours=-8))
    now = datetime.now(PST)
    today_6am = now.replace(hour=6, minute=0, second=0, microsecond=0)
    publish_at = today_6am + timedelta(days=1) if now >= today_6am else today_6am
    return publish_at.strftime("%Y-%m-%dT06:00:00-08:00")


def translate_to_english(japanese_script: str, topic: str) -> str:
    """日本語台本を英語に翻訳"""
    import anthropic
    client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
    prompt = f"""Translate this Japanese morning stretch script to natural, energetic English for a US audience.
Keep it under 60 seconds when spoken. Use friendly fitness instructor language. Maintain instructional tone.
Output only the English script, nothing else.

Topic: {topic}
Japanese:
{japanese_script}"""
    resp = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=500,
        messages=[{"role": "user", "content": prompt}]
    )
    return resp.content[0].text.strip()


def upload_kaizen_youtube(video_path: Path, topic: str, english_script: str, tags: list) -> str:
    """Kaizenチャンネルに予約投稿（6am PST）"""
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload

    SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]
    creds = _get_kaizen_youtube_creds(SCOPES)
    yt = build("youtube", "v3", credentials=creds)

    publish_at = _next_6am_pst()
    title = f"Morning {topic} Stretch | Kaizen with Sakura"
    description = f"""{english_script[:200]}...

Start your day with Kaizen — 1% better every day 🌸
New stretch every morning. Subscribe and move with me!

#MorningStretch #Kaizen #SakuraKaizen #FitnessRoutine #Stretch"""

    body = {
        "snippet": {"title": title, "description": description, "tags": tags, "categoryId": "22"},
        "status": {"privacyStatus": "private", "publishAt": publish_at, "selfDeclaredMadeForKids": False},
    }
    media = MediaFileUpload(str(video_path), mimetype="video/mp4", resumable=True)
    response = yt.videos().insert(part="snippet,status", body=body, media_body=media).execute()
    vid = response["id"]
    print(f"Kaizen YouTube予約完了（6am PST公開）: https://youtube.com/shorts/{vid}")
    return vid


def run_kaizen_pipeline(topic: str, japanese_script: str, tags: list = None, index: int = 0) -> str | None:
    """Fitnessと並走する英語Kaizenパイプライン"""
    print(f"\n=== Kaizenパイプライン開始: {topic} ===")
    try:
        english_script = translate_to_english(japanese_script, topic)
        print(f"英語台本: {english_script[:80]}...")

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_name = (re.sub(r"[^a-zA-Z0-9_]", "", topic.replace(" ", "_")) or "kaizen") + f"_{timestamp}"

        audio_dir = SAKURA_DIR / "audio"
        audio_dir.mkdir(exist_ok=True)
        audio_path = audio_dir / f"kaizen_{safe_name}.mp3"

        generate_audio(english_script, audio_path, voice_id=KAIZEN_VOICE_ID)
        audio_url = upload_audio(audio_path)

        background = _pick_background(index + 1)
        payload = {
            "video_inputs": [{
                "character": {"type": "avatar", "avatar_id": KAIZEN_AVATAR_ID, "avatar_style": "normal"},
                "voice": {"type": "audio", "audio_url": audio_url},
                "background": background,
            }],
            "dimension": {"width": 1080, "height": 1920},
            "test": False,
        }
        headers = {"X-Api-Key": HEYGEN_API_KEY, "Content-Type": "application/json"}
        resp = requests.post("https://api.heygen.com/v2/video/generate", headers=headers, json=payload, timeout=60)
        if not resp.ok:
            raise Exception(f"HeyGen Kaizen失敗: {resp.status_code} {resp.text}")
        video_id = resp.json()["data"]["video_id"]

        video_url = wait_heygen(video_id)

        video_dir = SAKURA_DIR / "videos"
        video_dir.mkdir(exist_ok=True)
        video_path = video_dir / f"kaizen_{safe_name}.mp4"
        download_video(video_url, video_path)

        if not SKIP_YOUTUBE_UPLOAD:
            yt_id = upload_kaizen_youtube(video_path, topic, english_script, tags or [])
            print(f"=== Kaizen完了: https://youtube.com/shorts/{yt_id} ===")
            return yt_id
        else:
            print(f"=== Kaizen動画生成完了（スキップ中）: {video_path} ===")
            return None
    except Exception as e:
        print(f"[Kaizen] エラー: {e}")
        return None


def upload_thumbnail(video_id: str, thumb_path: Path):
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload

    SCOPES = ["https://www.googleapis.com/auth/youtube.upload",
              "https://www.googleapis.com/auth/youtube.force-ssl"]
    creds = _get_sakura_youtube_creds(SCOPES)
    yt = build("youtube", "v3", credentials=creds)
    media = MediaFileUpload(str(thumb_path), mimetype="image/jpeg")
    yt.thumbnails().set(videoId=video_id, media_body=media).execute()
    print(f"サムネイルアップロード完了: {video_id}")


def add_pinned_comment(video_id: str, text: str):
    """動画にチャンネルオーナーのコメントを投稿する"""
    from googleapiclient.discovery import build
    SCOPES = ["https://www.googleapis.com/auth/youtube.force-ssl"]
    creds = _get_sakura_youtube_creds(SCOPES)
    yt = build("youtube", "v3", credentials=creds)
    yt.commentThreads().insert(
        part="snippet",
        body={
            "snippet": {
                "videoId": video_id,
                "topLevelComment": {
                    "snippet": {"textOriginal": text}
                },
            }
        },
    ).execute()
    print(f"コメント投稿完了: {video_id}")


def _next_6am_jst() -> str:
    """翌朝6:00 JST を RFC3339 形式で返す"""
    JST = timezone(timedelta(hours=9))
    now = datetime.now(JST)
    today_6am = now.replace(hour=6, minute=0, second=0, microsecond=0)
    publish_at = today_6am + timedelta(days=1) if now >= today_6am else today_6am
    return publish_at.strftime("%Y-%m-%dT06:00:00+09:00")


def upload_youtube(video_path: Path, title: str, description: str, tags: list, scheduled: bool = False) -> str:
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload

    SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]
    creds = _get_sakura_youtube_creds(SCOPES)
    yt = build("youtube", "v3", credentials=creds)
    status = {"selfDeclaredMadeForKids": False}
    if scheduled:
        publish_at = _next_6am_jst()
        status["privacyStatus"] = "private"
        status["publishAt"] = publish_at
        print(f"予約投稿: {publish_at}")
    else:
        status["privacyStatus"] = "public"

    body = {
        "snippet": {
            "title": title,
            "description": description,
            "tags": tags,
            "categoryId": "22",
        },
        "status": status,
    }
    media = MediaFileUpload(str(video_path), mimetype="video/mp4", resumable=True)
    req = yt.videos().insert(part="snippet,status", body=body, media_body=media)
    response = req.execute()
    vid = response["id"]
    if scheduled:
        print(f"YouTube予約完了（翌朝6時公開）: https://youtube.com/shorts/{vid}")
    else:
        print(f"YouTube投稿完了: https://youtube.com/shorts/{vid}")
    return vid


def run_pipeline(topic: str, script_data: dict = None, audio_url: str = None, index: int = 0):
    print(f"\n=== サクラパイプライン開始: {topic} (index={index}) ===")

    if not script_data:
        print("台本生成中...")
        script_data = generate_script(topic)
        print(f"台本: {script_data['script'][:60]}...")

    # audio_text があれば優先、数字変換→学習済み修正を適用
    script_text = apply_tts_corrections(replace_numbers(script_data.get("audio_text") or script_data["script"]))
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    keyword_safe = (re.sub(r"[^a-zA-Z0-9_]", "", topic.replace(" ", "_")) or "sakura") + f"_{timestamp}"

    audio_dir = SAKURA_DIR / "audio"
    audio_dir.mkdir(exist_ok=True)
    audio_path = audio_dir / f"sakura_{keyword_safe}.mp3"

    if not audio_url:
        # 1. 音声生成 + アップロード
        generate_audio(script_text, audio_path)
        audio_url = upload_audio(audio_path)
    else:
        print(f"音声URL（生成スキップ）: {audio_url}")

    # 2. HeyGen動画生成（背景・lookをindexでローテーション）
    heygen_id = generate_heygen_video(audio_url, index=index)
    video_url = wait_heygen(heygen_id)

    # 3. 動画ダウンロード
    video_dir = SAKURA_DIR / "videos"
    video_dir.mkdir(exist_ok=True)
    video_path = video_dir / f"sakura_{keyword_safe}.mp4"
    download_video(video_url, video_path)

    # 4. YouTube投稿（SKIP_YOUTUBE_UPLOAD=Trueのときスキップ）
    tags = script_data.get("tags", []) + ["ストレッチ", "サクラ", "AIトレーナー", "shorts", "朝ストレッチ", "60秒ストレッチ"]
    tags_str = " ".join(f"#{t}" for t in dict.fromkeys(tags))
    title_candidates = script_data.get("title_candidates", [])
    title = (title_candidates[0] if title_candidates else script_data.get("title", topic)) + " #Shorts"

    if SKIP_YOUTUBE_UPLOAD:
        # サムネイルだけ生成しておく
        try:
            generate_thumbnail(video_path, title, topic, index)
        except Exception as e:
            print(f"サムネイル生成スキップ: {e}")
        print(f"=== 動画生成完了（YouTube投稿スキップ中）: {video_path} ===")
        return str(video_path)

    description = DESCRIPTION_TEMPLATE.format(
        description=script_data.get("description", ""),
        topic=topic,
        channel_url=YOUTUBE_CHANNEL_URL,
        rakuten_url=RAKUTEN_ROOM_URL,
        tiktok_url=TIKTOK_URL,
        instagram_url=INSTAGRAM_URL,
        tags_str=tags_str,
    )
    yt_id = upload_youtube(video_path, title, description, tags, scheduled=True)

    # 5. サムネイルアップロード
    try:
        thumb_path = generate_thumbnail(video_path, title, topic, index)
        upload_thumbnail(yt_id, thumb_path)
    except Exception as e:
        print(f"サムネイルエラー（投稿は完了）: {e}")

    # 6. 固定コメント（楽天ROOMリンク）
    try:
        comment_text = (
            f"🛒 サクラ愛用ストレッチグッズはこちら！\n"
            f"▶ ヨガマット / フォームローラー / ストレッチポール\n"
            f"→ {RAKUTEN_ROOM_URL}\n\n"
            f"チャンネル登録＋🔔通知ONで毎朝6時の動画を見逃さない！"
        )
        add_pinned_comment(yt_id, comment_text)
    except Exception as e:
        print(f"コメント投稿エラー（投稿は完了）: {e}")

    print(f"=== 完了: https://youtube.com/shorts/{yt_id} ===")
    return yt_id


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("topic", nargs="?", default="朝ストレッチ")
    parser.add_argument("--audio-only", action="store_true", help="音声生成のみ（AUDIO_URL: を出力して終了）")
    parser.add_argument("--audio-url", default=None, help="既存の音声URL（HeyGen用）")
    parser.add_argument("--script-file", default=None, help="台本JSONファイル（{scripts:[...]} 形式）")
    args = parser.parse_args()

    script_data = None
    topic = args.topic
    if args.script_file:
        with open(args.script_file, encoding="utf-8") as f:
            data = json.load(f)
        script_data = data["scripts"][0] if "scripts" in data else data
        topic = script_data.get("topic", script_data.get("keyword", topic))

    if args.audio_only:
        if not script_data:
            script_data = generate_script(topic)
        script_text = apply_tts_corrections(replace_numbers(script_data.get("audio_text") or script_data["script"]))
        keyword_safe = re.sub(r"[^a-zA-Z0-9_]", "", topic.replace(" ", "_")) or "sakura"
        audio_dir = SAKURA_DIR / "audio"
        audio_dir.mkdir(exist_ok=True)
        audio_path = audio_dir / f"sakura_{keyword_safe}.mp3"
        generate_audio(script_text, audio_path)
        url = upload_audio(audio_path)
        print(f"AUDIO_URL: {url}")
    else:
        run_pipeline(topic, script_data, audio_url=args.audio_url)
