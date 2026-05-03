"""3チャンネルのYouTube分析スクリプト"""
import os
import json
from pathlib import Path
from dotenv import load_dotenv
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

load_dotenv(Path(__file__).parent / ".env")

BASE_DIR = Path(__file__).parent
SAKURA_DIR = BASE_DIR / "sakura"

def get_creds(token_path, env_key=None):
    token_json = ""
    if Path(token_path).exists():
        token_json = Path(token_path).read_text()
    elif env_key:
        token_json = os.getenv(env_key, "")
    if not token_json:
        return None
    creds = Credentials.from_authorized_user_info(json.loads(token_json))
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
    return creds

def get_channel_videos(yt, max_results=50):
    ch = yt.channels().list(part="contentDetails,statistics", mine=True).execute()
    if not ch["items"]:
        return None, []
    ch_item = ch["items"][0]
    uploads_id = ch_item["contentDetails"]["relatedPlaylists"]["uploads"]
    ch_stats = ch_item["statistics"]

    videos = []
    page_token = None
    while True:
        pl = yt.playlistItems().list(
            part="contentDetails", playlistId=uploads_id,
            maxResults=50, pageToken=page_token
        ).execute()
        video_ids = [i["contentDetails"]["videoId"] for i in pl["items"]]

        stats = yt.videos().list(
            part="snippet,statistics,contentDetails", id=",".join(video_ids)
        ).execute()
        for v in stats["items"]:
            s = v.get("statistics", {})
            videos.append({
                "id": v["id"],
                "title": v["snippet"]["title"],
                "published": v["snippet"]["publishedAt"][:10],
                "views": int(s.get("viewCount", 0)),
                "likes": int(s.get("likeCount", 0)),
                "comments": int(s.get("commentCount", 0)),
                "duration": v["contentDetails"]["duration"],
            })
        page_token = pl.get("nextPageToken")
        if not page_token or len(videos) >= max_results:
            break

    return ch_stats, sorted(videos, key=lambda x: x["views"], reverse=True)

def print_report(name, ch_stats, videos):
    print(f"\n{'='*60}")
    print(f"📊 {name}")
    print(f"{'='*60}")
    if ch_stats:
        print(f"チャンネル登録者: {int(ch_stats.get('subscriberCount',0)):,}人")
        print(f"総再生数: {int(ch_stats.get('viewCount',0)):,}回")
        print(f"動画本数: {ch_stats.get('videoCount','?')}本")

    if not videos:
        print("動画なし")
        return

    total_views = sum(v["views"] for v in videos)
    print(f"\n── 投稿動画 上位10本 ──")
    for i, v in enumerate(videos[:10], 1):
        print(f"{i:2}. [{v['views']:>6}回] {v['title'][:40]} ({v['published']})")

    print(f"\n── 集計 ──")
    print(f"平均再生数: {total_views // len(videos):,}回")
    print(f"最高再生数: {videos[0]['views']:,}回 「{videos[0]['title'][:35]}」")
    top3_avg = sum(v["views"] for v in videos[:3]) // min(3, len(videos))
    print(f"上位3本平均: {top3_avg:,}回")

channels = [
    ("Sakura Fitness", SAKURA_DIR / "sakura_youtube_token.json", "SAKURA_YOUTUBE_TOKEN_JSON"),
    ("Kaizen with Sakura", SAKURA_DIR / "kaizen_youtube_token.json", "KAIZEN_YOUTUBE_TOKEN_JSON"),
    ("AI Japan Labo", BASE_DIR / "youtube_token.json", "YOUTUBE_TOKEN_JSON"),
]

for name, token_path, env_key in channels:
    try:
        creds = get_creds(token_path, env_key)
        if not creds:
            print(f"\n⚠️ {name}: トークンなし")
            continue
        yt = build("youtube", "v3", credentials=creds)
        ch_stats, videos = get_channel_videos(yt)
        print_report(name, ch_stats, videos)
    except Exception as e:
        print(f"\n❌ {name}: エラー - {e}")
