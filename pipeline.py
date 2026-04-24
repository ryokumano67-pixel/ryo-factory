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
load_dotenv(BASE_DIR / ".env")

ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY")
CREATOMATE_API_KEY = os.getenv("CREATOMATE_API_KEY")
CREATOMATE_TEMPLATE_ID = os.getenv("CREATOMATE_TEMPLATE_ID")
VOICE_ID = "XrExE9yKIg1WjnnlVkGX"
SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]
TOKEN_FILE = BASE_DIR / "youtube_token.json"
CLIENT_SECRETS_FILE = BASE_DIR / "client_secrets.json"

REPLACEMENTS = {
    "AI": "エーアイ", "SNS": "エスエヌエス", "YouTube": "ユーチューブ",
    "ChatGPT": "チャットジーピーティー", "GPT": "ジーピーティー",
    "IT": "アイティー", "DX": "デジタルトランスフォーメーション",
    "NFT": "エヌエフティー", "PR": "ピーアール", "PC": "パソコン",
    "AR": "エーアール", "VR": "ブイアール", "OK": "オーケー",
    "pro": "プロ", "Pro": "プロ", "PRO": "プロ",
}

def fix_pronunciation(text):
    for word, reading in REPLACEMENTS.items():
        text = text.replace(word, reading)
    return text

def generate_audio(text, output_path):
    url = f"https://api.elevenlabs.io/v1/text-to-speech/{VOICE_ID}"
    headers = {"xi-api-key": ELEVENLABS_API_KEY, "Content-Type": "application/json"}
    payload = {
        "text": text,
        "model_id": "eleven_multilingual_v2",
        "voice_settings": {"stability": 0.75, "similarity_boost": 0.75}
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

def generate_video(audio_url):
    url = "https://api.creatomate.com/v1/renders"
    headers = {"Authorization": f"Bearer {CREATOMATE_API_KEY}", "Content-Type": "application/json"}
    payload = {
        "template_id": CREATOMATE_TEMPLATE_ID,
        "modifications": {"Voiceover-1": audio_url}
    }
    resp = requests.post(url, headers=headers, json=payload, timeout=60)
    if not resp.ok:
        raise Exception(f"Creatomate APIエラー: {resp.status_code} {resp.text}")
    video_url = resp.json()[0]["url"]
    print(f"動画生成開始: {video_url}")
    return video_url

def wait_for_video(video_url, max_wait=300):
    print("動画レンダリング待機中...")
    for i in range(max_wait // 10):
        time.sleep(10)
        resp = requests.head(video_url, timeout=10)
        if resp.status_code == 200:
            print("動画レンダリング完了!")
            return True
        print(f"待機中... {(i+1)*10}秒")
    raise Exception("動画レンダリングタイムアウト")

def download_video(url, output_path):
    resp = requests.get(url, timeout=120)
    Path(output_path).write_bytes(resp.content)
    print(f"動画ダウンロード完了: {output_path}")
    return output_path

def get_youtube_service():
    creds = None
    if TOKEN_FILE.exists():
        creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)
    if not creds or not creds.valid:
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

def run_pipeline(script_data, keyword):
    print(f"\n=== パイプライン開始: {keyword} ===")
    
    # 1. 発音修正
    script_text = fix_pronunciation(script_data["script"])
    
    # 2. 音声生成
    import re
    keyword_safe = re.sub(r"[^a-zA-Z0-9_]", "", keyword.replace(" ", "_"))
    if not keyword_safe:
        keyword_safe = "video"
    audio_filename = f"audio_{keyword_safe}.mp3"
    audio_path = BASE_DIR / "static" / audio_filename
    generate_audio(script_text, audio_path)
    
    # 3. RenderのURL
    audio_url = f"https://ryo-factory.onrender.com/static/{audio_filename}"
    
    # 4. 動画生成
    video_url = generate_video(audio_url)
    
    # 5. レンダリング待機
    wait_for_video(video_url)
    
    # 6. 動画ダウンロード
    video_path = BASE_DIR / "3_video" / f"video_{keyword}.mp4"
    download_video(video_url, video_path)
    
    # 7. YouTubeアップロード
    title = script_data["title_candidates"][0] + " #shorts"
    description = script_data.get("description", "") + "\n\n#shorts #AI #ショート動画"
    tags = script_data.get("tags", []) + ["shorts", "ショート動画"]
    video_id = upload_to_youtube(video_path, title, description, tags)
    
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
