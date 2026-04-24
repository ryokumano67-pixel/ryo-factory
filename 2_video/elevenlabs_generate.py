import os
import requests
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY")
VOICE_ID = "XrExE9yKIg1WjnnlVkGX"  # Matilda（日本語対応）


def generate_audio(text: str, output_path: Path) -> Path:
    url = f"https://api.elevenlabs.io/v1/text-to-speech/{VOICE_ID}"
    headers = {
        "xi-api-key": ELEVENLABS_API_KEY,
        "Content-Type": "application/json",
    }
    payload = {
        "text": text,
        "model_id": "eleven_multilingual_v2",
        "voice_settings": {
            "stability": 0.75,
            "similarity_boost": 0.75,
        }
    }
    resp = requests.post(url, headers=headers, json=payload, timeout=60)
    if not resp.ok:
        raise Exception(f"ElevenLabs APIエラー: {resp.status_code} {resp.text}")
    
    output_path.write_bytes(resp.content)
    print(f"音声ファイル生成完了: {output_path}")
    return output_path


if __name__ == "__main__":
    test_text = """エーアイで動画って
もう誰でも作れるって知ってた？
プロ並みの映像がスマホ一台でできちゃう時代！
これ使わない理由、もうないよね？
ためになったらいいねとフォローお願いします！"""
    
    output = Path(__file__).parent / "test_audio.mp3"
    generate_audio(test_text, output)
