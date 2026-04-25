import os
import requests
from pathlib import Path
from dotenv import load_dotenv
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]
TOKEN_FILE = BASE_DIR / "youtube_token.json"
CLIENT_SECRETS_FILE = BASE_DIR / "client_secrets.json"

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

def download_video(url: str, output_path: Path) -> Path:
    resp = requests.get(url, timeout=120)
    output_path.write_bytes(resp.content)
    print(f"動画ダウンロード完了: {output_path}")
    return output_path

def upload_to_youtube(video_path: Path, title: str, description: str, tags: list) -> str:
    youtube = get_youtube_service()
    body = {
        "snippet": {
            "title": title,
            "description": description,
            "tags": tags,
            "categoryId": "22",
        },
        "status": {
            "privacyStatus": "public",
            "selfDeclaredMadeForKids": False,
        },
    }
    media = MediaFileUpload(str(video_path), mimetype="video/mp4", resumable=True)
    request = youtube.videos().insert(part="snippet,status", body=body, media_body=media)
    response = request.execute()
    video_id = response["id"]
    print(f"YouTubeアップロード完了: https://youtube.com/shorts/{video_id}")
    return video_id

if __name__ == "__main__":
    video_url = "https://f002.backblazeb2.com/file/creatomate-c8xg3hsxdu/e29604ff-63ab-4a9d-812b-1da39877ce36.mp4"
    video_path = BASE_DIR / "3_video" / "test_upload.mp4"
    download_video(video_url, video_path)
    upload_to_youtube(
        video_path,
        title="AIで動画が誰でも作れる時代！#shorts",
        description="AIツールを使えば動画制作が超簡単に！\n\n#AI #YouTube #ショート動画",
        tags=["AI", "YouTube", "ショート動画", "自動化"]
    )
