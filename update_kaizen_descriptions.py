#!/usr/bin/env python3
"""Kaizen既存動画の概要欄のAmazonリンクにアフィリタグを追加"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from sakura.pipeline import _get_kaizen_youtube_creds
from googleapiclient.discovery import build

OLD_URL = "https://www.amazon.com/s?k=yoga+fitness+gear&tag=kaizensakura-20"
NEW_URL = "https://www.amazon.com/hz/wishlist/ls/202TJXB8FKB2B?tag=kaizensakura-20"


def main():
    SCOPES = ["https://www.googleapis.com/auth/youtube.force-ssl"]
    creds = _get_kaizen_youtube_creds(SCOPES)
    yt = build("youtube", "v3", credentials=creds)

    ch = yt.channels().list(part="contentDetails", mine=True).execute()
    uploads_playlist = ch["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]

    video_ids = []
    page_token = None
    while True:
        resp = yt.playlistItems().list(
            part="contentDetails",
            playlistId=uploads_playlist,
            maxResults=50,
            pageToken=page_token,
        ).execute()
        for item in resp["items"]:
            video_ids.append(item["contentDetails"]["videoId"])
        page_token = resp.get("nextPageToken")
        if not page_token:
            break

    print(f"対象動画数: {len(video_ids)}本\n")

    updated = 0
    for vid in video_ids:
        v = yt.videos().list(part="snippet", id=vid).execute()
        if not v["items"]:
            continue
        snippet = v["items"][0]["snippet"]
        desc = snippet.get("description", "")

        if OLD_URL not in desc:
            print(f"  スキップ: {snippet['title'][:40]}")
            continue

        snippet["description"] = desc.replace(OLD_URL, NEW_URL)
        yt.videos().update(
            part="snippet",
            body={"id": vid, "snippet": snippet},
        ).execute()
        print(f"  更新完了: {snippet['title'][:40]}")
        updated += 1

    print(f"\n完了: {updated}本更新")


if __name__ == "__main__":
    main()
