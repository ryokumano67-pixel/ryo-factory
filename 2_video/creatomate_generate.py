import os
import requests
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

API_KEY = os.getenv("CREATOMATE_API_KEY")
TEMPLATE_ID = os.getenv("CREATOMATE_TEMPLATE_ID")


def upload_audio(audio_path: Path) -> str:
    url = "https://api.creatomate.com/v1/assets"
    headers = {"Authorization": f"Bearer {API_KEY}"}
    with open(audio_path, "rb") as f:
        resp = requests.post(url, headers=headers, files={"file": f}, timeout=60)
    if not resp.ok:
        raise Exception(f"アップロードエラー: {resp.status_code} {resp.text}")
    asset_url = resp.json()["url"]
    print(f"音声アップロード完了: {asset_url}")
    return asset_url


def generate_video(audio_url: str) -> str:
    url = "https://api.creatomate.com/v1/renders"
    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "template_id": TEMPLATE_ID,
        "modifications": {
            "Voiceover-4": audio_url,
        }
    }
    resp = requests.post(url, headers=headers, json=payload, timeout=60)
    if not resp.ok:
        raise Exception(f"動画生成エラー: {resp.status_code} {resp.text}")
    result = resp.json()
    render_url = result[0]["url"]
    print(f"動画URL: {render_url}")
    return render_url


if __name__ == "__main__":
    audio_path = Path(__file__).parent / "test_audio.mp3"
    audio_url = upload_audio(audio_path)
    video_url = generate_video(audio_url)
    print(f"完了: {video_url}")
