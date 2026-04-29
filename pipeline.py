import os
import json
import time
import requests
from pathlib import Path
from dotenv import load_dotenv
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env", override=True)

ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY")
HEYGEN_API_KEY = os.getenv("HEYGEN_API_KEY")
HEYGEN_AVATAR_ID = os.getenv("HEYGEN_AVATAR_ID")
VOICE_ID = "XrExE9yKIg1WjnnlVkGX"  # Matilda（ai_japan_labo用）
SCOPES = ["https://www.googleapis.com/auth/youtube.upload",
          "https://www.googleapis.com/auth/youtube"]
TOKEN_FILE = BASE_DIR / "youtube_token.json"
CLIENT_SECRETS_FILE = BASE_DIR / "client_secrets.json"
TTS_CORRECTIONS_FILE = BASE_DIR / "ai_japan_labo_tts_corrections.json"

# Hana look IDs（動画ごとに自動ローテーション）
HANA_LOOK_IDS = [
    "d9080a4c5770454ca894dd5a3271f51f",
    "d5a4ce5a13154bdea46db9ddb8dcdbcc",
    "2315f9deb29945f6948ed7575d67a817",
    "be236ad22757438689758aa4c932e656",
    "8c12d10755e145248b8069897b1d74b2",
    "3e205168ba694da699f96f53d0e6411e",
    "8e2af2d0bb2e4e519ad1a1b739ac7c63",
    "6d2e9cf4a331493a9b01cb59b884d202",
    "36a98ec612164c24a9615e40080d7b70",
    "c410ae69794042b0a2296fac20a46411",
    "4d251d4720b44e31ae46c34733c4e900",
    "e362da9e5532490680a465390b07a707",
    "bbcd6b1a1fef43dc90699286ccf6a791",
    "e74d8f25040542848a5f06a240ceb11a",
]

# HeyGen背景色ローテーション
HANA_BACKGROUND_COLORS = [
    "#0D0D1A",  # 濃紺
    "#1A0D1A",  # 深紫
    "#0D1A1A",  # ディープティール
    "#000D1A",  # ミッドナイトブルー
    "#1A0D0D",  # ダークバーガンディ
    "#0D1A0D",  # ダークグリーン
    "#1A1A0D",  # ダークオリーブ
]

REPLACEMENTS = {
    "わき腹": "わきばら",
    "生成AI": "生成エーアイ",
    "AI": "エーアイ", "SNS": "エスエヌエス", "YouTube": "ユーチューブ",
    "ChatGPT": "チャットジーピーティー", "GPT": "ジーピーティー",
    "IT": "アイティー", "DX": "デジタルトランスフォーメーション",
    "NFT": "エヌエフティー", "PR": "ピーアール", "PC": "パソコン",
    "AR": "エーアール", "VR": "ブイアール", "OK": "オーケー",
    "pro": "プロ", "Pro": "プロ", "PRO": "プロ",
    "App": "アプリ", "app": "アプリ", "Web": "ウェブ", "web": "ウェブ",
    "EAI": "エーアイ", "EA I": "エーアイ",
}

# ElevenLabs TTS用：英語のまま渡した方が正確に読まれる（カタカナ変換しない）
TTS_REPLACEMENTS = {
    "わき腹": "わきばら",
    "生成AI": "生成AI",
    "EAI": "AI", "EA I": "AI",
    "SNS": "エスエヌエス",
    "DX": "デジタルトランスフォーメーション",
    "NFT": "エヌエフティー",
}


def fix_pronunciation(text):
    import re
    text = re.sub(r"\[.*?\]", "", text)
    text = re.sub(r"【.*?】", "", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    for word, reading in sorted(REPLACEMENTS.items(), key=lambda x: -len(x[0])):
        text = text.replace(word, reading)
    return text

def generate_audio(text, output_path, voice_id=None, voice_settings=None):
    url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id or VOICE_ID}"
    headers = {"xi-api-key": ELEVENLABS_API_KEY, "Content-Type": "application/json"}
    payload = {
        "text": text,
        "model_id": "eleven_multilingual_v2",
        "voice_settings": voice_settings or {"stability": 0.75, "similarity_boost": 0.75}
    }
    resp = requests.post(url, headers=headers, json=payload, timeout=60)
    if not resp.ok:
        raise Exception(f"ElevenLabs APIエラー: {resp.status_code} {resp.text}")
    Path(output_path).write_bytes(resp.content)
    print(f"音声生成完了: {output_path}")
    return output_path

def push_audio_to_render(audio_path, filename):
    import subprocess
    dest = BASE_DIR / "static" / filename
    dest.write_bytes(Path(audio_path).read_bytes())
    subprocess.run(["git", "-C", str(BASE_DIR), "add", f"static/{filename}"], check=True)
    subprocess.run(["git", "-C", str(BASE_DIR), "commit", "-m", f"Add audio {filename}"], check=True)
    subprocess.run(["git", "-C", str(BASE_DIR), "push", "origin", "main"], check=True)
    print("音声をRenderにpush完了")
    time.sleep(30)
    return f"https://ryo-factory.onrender.com/static/{filename}"

def _upload_catbox(audio_path):
    """catbox.moe permanent API（直リンク取得）"""
    with open(audio_path, "rb") as f:
        resp = requests.post(
            "https://catbox.moe/user/api.php",
            data={"reqtype": "fileupload", "userhash": ""},
            files={"fileToUpload": f},
            timeout=120,
        )
    if resp.ok and resp.text.startswith("http"):
        return resp.text.strip()
    raise Exception(f"catbox: {resp.text[:100]}")


def _upload_litterbox(audio_path):
    """litterbox.catbox.moe 一時保存 API（フォールバック）"""
    with open(audio_path, "rb") as f:
        resp = requests.post(
            "https://litterbox.catbox.moe/resources/internals/api.php",
            data={"reqtype": "fileupload", "time": "72h"},
            files={"fileToUpload": f},
            timeout=120,
        )
    if resp.ok and resp.text.startswith("http"):
        return resp.text.strip()
    raise Exception(f"litterbox: {resp.text[:100]}")


def upload_audio(audio_path):
    uploaders = [
        ("catbox.moe",  _upload_catbox),
        ("litterbox",   _upload_litterbox),
    ]
    last_err = None
    for name, fn in uploaders:
        for attempt in range(1, 3):
            try:
                url = fn(audio_path)
                print(f"音声アップロード完了 [{name}]: {url}")
                return url
            except Exception as e:
                last_err = e
                print(f"アップロード失敗 [{name}] 試行{attempt}: {e}")
                time.sleep(3)
    raise Exception(f"音声アップロード失敗（全サービス）: {last_err}")


_kks = None

def _get_kks():
    global _kks
    if _kks is None:
        import pykakasi
        _kks = pykakasi.kakasi()
    return _kks


def to_hiragana(text):
    import re
    text = re.sub(r"\[.*?\]", "", text)
    text = re.sub(r"【.*?】", "", text)
    text = re.sub(r'人(?![一-鿿])', 'ひと', text)
    kks = _get_kks()
    lines = text.split("\n")
    result_lines = []
    for line in lines:
        for word, reading in sorted(REPLACEMENTS.items(), key=lambda x: -len(x[0])):
            line = line.replace(word, reading)
        items = kks.convert(line)
        result_lines.append("".join(
            i["hira"] if i["hira"] and i["hira"] != i["orig"] else i["orig"]
            for i in items
        ))
    return "\n".join(result_lines)


def load_tts_corrections():
    if TTS_CORRECTIONS_FILE.exists():
        with open(TTS_CORRECTIONS_FILE, encoding="utf-8") as f:
            return json.load(f)
    return []


def save_tts_correction(original: str, corrected: str):
    corrections = load_tts_corrections()
    for c in corrections:
        if c["original"] == original:
            c["corrected"] = corrected
            break
    else:
        corrections.append({"original": original, "corrected": corrected})
    with open(TTS_CORRECTIONS_FILE, "w", encoding="utf-8") as f:
        json.dump(corrections, f, ensure_ascii=False, indent=2)
    print(f"TTS補正を保存: {original} → {corrected}")


def extract_and_save_corrections(original_text: str, corrected_text: str):
    """diffで差分を検出して補正ペアを保存する"""
    import difflib
    orig_lines = original_text.split("\n")
    corr_lines = corrected_text.split("\n")
    for o, c in zip(orig_lines, corr_lines):
        if o == c:
            continue
        matcher = difflib.SequenceMatcher(None, o, c)
        for tag, i1, i2, j1, j2 in matcher.get_opcodes():
            if tag in ("replace", "delete", "insert") and (i2 - i1) >= 1:
                orig_frag = o[max(0, i1-2):i2+2]
                corr_frag = c[max(0, j1-2):j2+2]
                if orig_frag and corr_frag and orig_frag != corr_frag:
                    save_tts_correction(orig_frag, corr_frag)


def apply_tts_corrections(text: str) -> str:
    for c in sorted(load_tts_corrections(), key=lambda x: -len(x["original"])):
        text = text.replace(c["original"], c["corrected"])
    return text


def fix_for_tts(text):
    """ElevenLabs向け：英語固有名詞はそのまま、漢字のみひらがな化 + 学習済み補正を適用"""
    import re
    text = re.sub(r"\[.*?\]", "", text)
    text = re.sub(r"【.*?】", "", text)
    text = re.sub(r'人(?![一-鿿])', 'ひと', text)
    kks = _get_kks()
    lines = text.split("\n")
    result_lines = []
    for line in lines:
        for word, reading in sorted(TTS_REPLACEMENTS.items(), key=lambda x: -len(x[0])):
            line = line.replace(word, reading)
        items = kks.convert(line)
        line_result = ""
        for item in items:
            orig = item["orig"]
            hira = item["hira"]
            # カタカナ・英字はそのまま維持（ElevenLabsが正しく読む）
            if orig and all('゠' <= c <= 'ヿ' or c == 'ー' or c.isascii() or not c.strip() for c in orig):
                line_result += orig
            elif hira and hira != orig:
                line_result += hira
            else:
                line_result += orig
        result_lines.append(line_result)
    result = "\n".join(result_lines)
    return apply_tts_corrections(result)


def _pick_look_id(index: int) -> str:
    return HANA_LOOK_IDS[index % len(HANA_LOOK_IDS)]


def _pick_background_color(index: int) -> str:
    return HANA_BACKGROUND_COLORS[index % len(HANA_BACKGROUND_COLORS)]


def generate_heygen_video(audio_url, index: int = 0):
    """lookと背景色を自動ローテーションしてHeyGenアバター動画を生成"""
    look_id = _pick_look_id(index)
    bg_color = _pick_background_color(index)
    print(f"HeyGen look={look_id[:8]}… bg={bg_color}")
    url = "https://api.heygen.com/v2/video/generate"
    headers = {"X-Api-Key": HEYGEN_API_KEY, "Content-Type": "application/json"}
    payload = {
        "video_inputs": [{
            "character": {
                "type": "avatar",
                "avatar_id": look_id,
                "avatar_style": "normal"
            },
            "voice": {
                "type": "audio",
                "audio_url": audio_url
            },
            "background": {
                "type": "color",
                "value": bg_color
            }
        }],
        "dimension": {"width": 720, "height": 1280},
        "aspect_ratio": "9:16"
    }
    resp = requests.post(url, headers=headers, json=payload, timeout=60)
    if not resp.ok:
        raise Exception(f"HeyGen APIエラー: {resp.status_code} {resp.text}")
    video_id = resp.json()["data"]["video_id"]
    print(f"HeyGen動画生成開始: video_id={video_id}")
    return video_id


def wait_for_heygen_video(video_id, max_wait=600):
    """HeyGenレンダリング完了を待機してダウンロードURLを返す"""
    print("HeyGenレンダリング待機中...")
    url = f"https://api.heygen.com/v1/video_status.get?video_id={video_id}"
    headers = {"X-Api-Key": HEYGEN_API_KEY}
    for i in range(max_wait // 10):
        time.sleep(10)
        resp = requests.get(url, headers=headers, timeout=30)
        if not resp.ok:
            print(f"ステータス確認エラー: {resp.status_code}")
            continue
        data = resp.json().get("data", {})
        status = data.get("status", "")
        print(f"HeyGenステータス: {status} ({(i+1)*10}秒)")
        if status == "completed":
            video_url = data.get("video_url")
            print(f"HeyGen完了: {video_url}")
            return video_url
        elif status == "failed":
            raise Exception(f"HeyGen生成失敗: {data.get('error', data)}")
    raise Exception("HeyGenレンダリングタイムアウト")


def download_video(url, output_path):
    resp = requests.get(url, timeout=120)
    Path(output_path).write_bytes(resp.content)
    print(f"動画ダウンロード完了: {output_path}")
    return output_path

def get_youtube_service():
    from google.auth.transport.requests import Request
    creds = None
    if TOKEN_FILE.exists():
        creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
        TOKEN_FILE.write_text(creds.to_json())
    elif not creds or not creds.valid:
        flow = InstalledAppFlow.from_client_secrets_file(CLIENT_SECRETS_FILE, SCOPES)
        creds = flow.run_local_server(port=0)
        TOKEN_FILE.write_text(creds.to_json())
    return build("youtube", "v3", credentials=creds)

def upload_to_youtube(video_path, title, description, tags):
    youtube = get_youtube_service()
    body = {
        "snippet": {"title": title, "description": description, "tags": tags, "categoryId": "22"},
        "status": {"privacyStatus": "public", "selfDeclaredMadeForKids": False},
    }
    media = MediaFileUpload(str(video_path), mimetype="video/mp4", resumable=True)
    request = youtube.videos().insert(part="snippet,status", body=body, media_body=media)
    response = request.execute()
    video_id = response["id"]
    print(f"YouTubeアップロード完了: https://youtube.com/shorts/{video_id}")
    return video_id


def generate_thumbnail(video_path, title):
    """動画の3秒目フレームを抽出してタイトルを合成したサムネイルを生成"""
    import subprocess
    from PIL import Image, ImageDraw, ImageFont
    thumb_path = Path(str(video_path).replace(".mp4", "_thumb.jpg"))
    subprocess.run([
        "ffmpeg", "-y", "-ss", "3", "-i", str(video_path),
        "-vframes", "1", "-q:v", "2", str(thumb_path)
    ], capture_output=True)
    if not thumb_path.exists():
        return None
    img = Image.open(thumb_path).convert("RGB")
    w, h = img.size
    draw = ImageDraw.Draw(img)
    # 上部グラデーション帯
    for y in range(int(h * 0.35)):
        alpha = int(180 * (1 - y / (h * 0.35)))
        draw.rectangle([(0, y), (w, y + 1)], fill=(0, 0, 0, alpha))
    # タイトルテキスト
    font_size = 48
    try:
        font = ImageFont.truetype("/System/Library/Fonts/ヒラギノ角ゴシック W6.ttc", font_size)
    except Exception:
        font = ImageFont.load_default()
    # タイトルを2行に折り返し
    max_chars = 14
    lines = [title[i:i+max_chars] for i in range(0, min(len(title), max_chars*2), max_chars)]
    y_text = int(h * 0.04)
    for line in lines:
        bbox = draw.textbbox((0, 0), line, font=font)
        tw = bbox[2] - bbox[0]
        x_text = (w - tw) // 2
        draw.text((x_text+2, y_text+2), line, font=font, fill=(0, 0, 0))
        draw.text((x_text, y_text), line, font=font, fill=(255, 255, 255))
        y_text += font_size + 8
    img.save(thumb_path, "JPEG", quality=95)
    print(f"サムネイル生成完了: {thumb_path}")
    return thumb_path


def upload_thumbnail(video_id, thumb_path):
    """YouTubeにサムネイルをアップロード"""
    try:
        youtube = get_youtube_service()
        media = MediaFileUpload(str(thumb_path), mimetype="image/jpeg")
        youtube.thumbnails().set(videoId=video_id, media_body=media).execute()
        print(f"サムネイルアップロード完了: {thumb_path}")
    except Exception as e:
        print(f"サムネイルアップロード失敗（スキップ）: {e}")

def upload_to_tiktok(video_path, title):
    """TikTok自動投稿（TIKTOK_ACCESS_TOKEN設定時に有効）"""
    token = os.getenv("TIKTOK_ACCESS_TOKEN")
    if not token:
        print("TikTok: TIKTOK_ACCESS_TOKEN未設定のためスキップ")
        return None
    print(f"TikTok投稿は未実装（要: TikTok API v2設定）: {video_path}")
    return None


def upload_to_instagram(video_path, caption):
    """Instagram Reels自動投稿（INSTAGRAM_ACCESS_TOKEN設定時に有効）"""
    token = os.getenv("INSTAGRAM_ACCESS_TOKEN")
    account_id = os.getenv("INSTAGRAM_ACCOUNT_ID")
    if not token or not account_id:
        print("Instagram: INSTAGRAM_ACCESS_TOKEN / INSTAGRAM_ACCOUNT_ID未設定のためスキップ")
        return None
    print(f"Instagram投稿は未実装（要: Meta Graph API設定）: {video_path}")
    return None


def _video_index() -> int:
    """これまでの投稿数をカウントしてlook/背景のローテーション番号を決める"""
    video_dir = BASE_DIR / "3_video"
    return len(list(video_dir.glob("video_*.mp4"))) if video_dir.exists() else 0


def run_pipeline(script_data, keyword):
    print(f"\n=== パイプライン開始: {keyword} ===")
    index = _video_index()

    # 1. 発音テキスト（手動修正済みがあればそれを使用、なければ自動変換+学習補正）
    script_text = script_data.get("audio_text") or fix_for_tts(script_data["script"])

    # 2. 音声生成
    import re
    keyword_safe = re.sub(r"[^a-zA-Z0-9_]", "", keyword.replace(" ", "_"))
    if not keyword_safe:
        keyword_safe = "video"
    audio_filename = f"audio_{keyword_safe}.mp3"
    audio_path = BASE_DIR / "static" / audio_filename
    generate_audio(script_text, audio_path)

    # 3. 音声を公開URLにアップロード
    audio_url = upload_audio(audio_path)

    # 4. HeyGen（lookと背景色をローテーション）
    heygen_video_id = generate_heygen_video(audio_url, index=index)
    heygen_video_url = wait_for_heygen_video(heygen_video_id)

    # 5. HeyGen動画を直接ダウンロード
    video_path = BASE_DIR / "3_video" / f"video_{keyword_safe}.mp4"
    download_video(heygen_video_url, video_path)

    # 6. YouTube投稿
    title = script_data["title_candidates"][0] + " #shorts"
    description = script_data.get("description", "") + "\n\n#shorts #AI #ショート動画"
    tags = script_data.get("tags", []) + ["shorts", "ショート動画"]
    video_id = upload_to_youtube(video_path, title, description, tags)

    # 7. サムネイル自動生成・アップロード
    thumb_path = generate_thumbnail(video_path, script_data["title_candidates"][0])
    if thumb_path:
        upload_thumbnail(video_id, thumb_path)

    print(f"=== 完了: https://youtube.com/shorts/{video_id} ===")
    return video_id

if __name__ == "__main__":
    import sys
    script_file = sys.argv[1] if len(sys.argv) > 1 else None
    if not script_file:
        scripts_dir = BASE_DIR / "1_scripts"
        json_files = sorted(scripts_dir.glob("scripts_*.json"), reverse=True)
        script_file = str(json_files[0])
    
    with open(script_file, encoding="utf-8") as f:
        data = json.load(f)
    
    for script in data["scripts"]:
        keyword = script["keyword"].replace("/", "_").replace(" ", "_")
        run_pipeline(script, keyword)
