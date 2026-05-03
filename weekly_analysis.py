"""
weekly_analysis.py
毎週チャンネルを分析してperformance_insights.jsonを更新する。
generate_script.pyはこのファイルを読んでプロンプトを動的に調整する。
"""
import json
import os
import sys
from datetime import datetime
from pathlib import Path

import anthropic
from dotenv import load_dotenv
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

BASE_DIR = Path(__file__).parent
SAKURA_DIR = BASE_DIR / "sakura"
DATA_DIR = Path(os.getenv("DATA_DIR", BASE_DIR))
INSIGHTS_FILE = DATA_DIR / "performance_insights.json"

load_dotenv(BASE_DIR / ".env")


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


def fetch_video_stats(yt, max_results=30):
    try:
        ch = yt.channels().list(part="contentDetails", mine=True).execute()
        uploads_id = ch["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]
        pl = yt.playlistItems().list(
            part="contentDetails", playlistId=uploads_id, maxResults=max_results
        ).execute()
        video_ids = [i["contentDetails"]["videoId"] for i in pl["items"]]
        stats = yt.videos().list(
            part="snippet,statistics", id=",".join(video_ids)
        ).execute()
        return [
            {
                "title": v["snippet"]["title"],
                "views": int(v["statistics"].get("viewCount", 0)),
                "likes": int(v["statistics"].get("likeCount", 0)),
                "published": v["snippet"]["publishedAt"][:10],
            }
            for v in stats["items"]
        ]
    except Exception as e:
        print(f"  データ取得エラー: {e}")
        return []


def analyze_with_claude(channel_name: str, videos: list) -> dict:
    if not videos:
        return {}
    sorted_vids = sorted(videos, key=lambda x: x["views"], reverse=True)
    top = sorted_vids[:10]
    bottom = sorted_vids[-5:]

    summary = "\n".join(
        f"- [{v['views']}回] {v['title']}" for v in top
    )
    low_summary = "\n".join(
        f"- [{v['views']}回] {v['title']}" for v in bottom
    )

    client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
    prompt = f"""以下は「{channel_name}」チャンネルの動画パフォーマンスデータです。

【再生数上位】
{summary}

【再生数下位】
{low_summary}

上位と下位を比較して、以下をJSON形式で出力してください：
{{
  "top_title_patterns": ["伸びるタイトルパターン1", "パターン2", "パターン3"],
  "top_topics": ["伸びるトピック1", "トピック2", "トピック3"],
  "avoid_patterns": ["避けるべきパターン1", "パターン2"],
  "key_insight": "一番重要な気づきを1文で",
  "recommended_hook": "次の台本で使うべき冒頭フック例"
}}

JSONのみ出力してください。"""

    resp = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=500,
        messages=[{"role": "user", "content": prompt}]
    )
    try:
        return json.loads(resp.content[0].text.strip())
    except Exception:
        return {"key_insight": resp.content[0].text.strip()[:200]}


def main():
    print(f"=== 週次チャンネル分析 {datetime.now().strftime('%Y-%m-%d')} ===")

    channels = [
        ("sakura_fitness", "Sakura Fitness",
         SAKURA_DIR / "sakura_youtube_token.json", "SAKURA_YOUTUBE_TOKEN_JSON"),
        ("ai_japan", "AI Japan Labo",
         BASE_DIR / "youtube_token.json", "YOUTUBE_TOKEN_JSON"),
    ]

    insights = {
        "updated_at": datetime.now().strftime("%Y-%m-%d"),
        "channels": {}
    }

    for key, name, token_path, env_key in channels:
        print(f"\n📊 {name} 分析中...")
        creds = get_creds(token_path, env_key)
        if not creds:
            print(f"  トークンなし、スキップ")
            continue
        yt = build("youtube", "v3", credentials=creds)
        videos = fetch_video_stats(yt)
        if not videos:
            continue
        print(f"  {len(videos)}本のデータ取得完了")
        analysis = analyze_with_claude(name, videos)
        insights["channels"][key] = analysis
        print(f"  洞察: {analysis.get('key_insight', '?')}")

    INSIGHTS_FILE.parent.mkdir(parents=True, exist_ok=True)
    INSIGHTS_FILE.write_text(json.dumps(insights, ensure_ascii=False, indent=2))
    print(f"\n✅ 分析完了 → {INSIGHTS_FILE}")
    print(json.dumps(insights, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
