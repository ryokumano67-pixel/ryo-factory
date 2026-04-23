"""
fetch_trends.py
Google Trends + YouTube Data API でトレンドキーワードを取得し上位3件をJSONで保存する。
"""

import json
import os
import sys
import time
import logging
from datetime import datetime
from pathlib import Path

from pytrends.request import TrendReq
from googleapiclient.discovery import build
from dotenv import load_dotenv

# ── 環境設定 ──────────────────────────────────────────────
BASE_DIR = Path(__file__).resolve().parents[1]
load_dotenv(BASE_DIR / ".env")

GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")

LOG_DIR = BASE_DIR / "logs"
LOG_DIR.mkdir(exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_DIR / "fetch_trends.log", encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger(__name__)

# 調査対象のシードキーワード（テクノロジー・AI関連）
SEED_KEYWORDS = [
    "生成AI", "ChatGPT", "Claude AI", "Gemini AI", "画像生成AI",
    "AI動画", "機械学習", "プログラミング入門", "Python AI", "ノーコード",
]

# YouTube検索で競合調査する際の最大結果数
YOUTUBE_MAX_RESULTS = 10


def fetch_google_trends(keywords: list[str], max_retries: int = 3) -> dict[str, int]:
    """pytrends でキーワードごとの関心度スコアを取得する。"""
    log.info("Google Trends の取得を開始します")
    pytrends = TrendReq(hl="ja-JP", tz=540, timeout=(10, 25))
    scores: dict[str, int] = {}

    # pytrends は一度に最大5キーワードまで比較可能
    for i in range(0, len(keywords), 5):
        batch = keywords[i : i + 5]
        for attempt in range(max_retries):
            try:
                pytrends.build_payload(batch, cat=0, timeframe="now 7-d", geo="JP")
                df = pytrends.interest_over_time()
                if not df.empty:
                    for kw in batch:
                        if kw in df.columns:
                            scores[kw] = int(df[kw].mean())
                break
            except Exception as e:
                wait = 10 * (2 ** attempt)  # 10s, 20s, 40s
                if attempt < max_retries - 1:
                    log.warning(f"Trends 取得エラー (batch={batch}, attempt={attempt+1}): {e} — {wait}秒後にリトライ")
                    time.sleep(wait)
                else:
                    log.warning(f"Trends 取得エラー (batch={batch}): {e} — スキップします")
        else:
            pass
        time.sleep(5)  # バッチ間のレート制限対策

    log.info(f"Trends スコア取得完了: {scores}")
    return scores


def fetch_youtube_competition(keyword: str, youtube) -> dict:
    """YouTube Data API でキーワードの競合動画情報を取得する。"""
    try:
        response = (
            youtube.search()
            .list(
                q=keyword,
                part="snippet",
                type="video",
                videoDuration="short",
                order="viewCount",
                maxResults=YOUTUBE_MAX_RESULTS,
                regionCode="JP",
                relevanceLanguage="ja",
            )
            .execute()
        )
        items = response.get("items", [])
        video_ids = [item["id"]["videoId"] for item in items]

        # 再生回数を取得
        total_views = 0
        if video_ids:
            stats_resp = (
                youtube.videos()
                .list(part="statistics", id=",".join(video_ids))
                .execute()
            )
            for v in stats_resp.get("items", []):
                total_views += int(v["statistics"].get("viewCount", 0))

        avg_views = total_views // len(video_ids) if video_ids else 0
        return {
            "video_count": len(items),
            "avg_views": avg_views,
            "top_titles": [item["snippet"]["title"] for item in items[:3]],
        }
    except Exception as e:
        log.warning(f"YouTube 競合調査エラー ({keyword}): {e}")
        return {"video_count": 0, "avg_views": 0, "top_titles": []}


def select_top_keywords(scores: dict[str, int], youtube, top_n: int = 3) -> list[dict]:
    """Trendsスコア上位キーワードにYouTube競合情報を付加して返す。"""
    sorted_kws = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    top = sorted_kws[:top_n * 2]  # 余裕を持って上位を調査

    results = []
    for kw, trend_score in top:
        log.info(f"YouTube 競合調査中: {kw}")
        competition = fetch_youtube_competition(kw, youtube)
        results.append(
            {
                "keyword": kw,
                "trend_score": trend_score,
                "youtube_competition": competition,
                # スコア = トレンド強度が高く競合平均再生数が低い順が狙い目
                "opportunity_score": trend_score - (competition["avg_views"] // 100000),
            }
        )
        time.sleep(0.5)

    results.sort(key=lambda x: x["opportunity_score"], reverse=True)
    return results[:top_n]


def save_results(keywords: list[dict]) -> Path:
    """結果を 0_trends/ フォルダに日付付きJSONで保存する。"""
    output_dir = BASE_DIR / "0_trends"
    output_dir.mkdir(exist_ok=True)
    date_str = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_path = output_dir / f"trends_{date_str}.json"

    payload = {
        "fetched_at": datetime.now().isoformat(),
        "keywords": keywords,
    }
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    log.info(f"トレンドデータを保存しました: {output_path}")
    return output_path


def main() -> Path:
    if not GOOGLE_API_KEY:
        log.error("GOOGLE_API_KEY が設定されていません")
        sys.exit(1)

    youtube = build("youtube", "v3", developerKey=GOOGLE_API_KEY)

    scores = fetch_google_trends(SEED_KEYWORDS)
    if not scores:
        log.warning("Google Trends からスコアを取得できませんでした。全キーワードを均等スコアでフォールバックします")
        scores = {kw: 50 for kw in SEED_KEYWORDS}

    top_keywords = select_top_keywords(scores, youtube)
    output_path = save_results(top_keywords)

    log.info("=== 上位トレンドキーワード ===")
    for i, kw in enumerate(top_keywords, 1):
        log.info(f"{i}. {kw['keyword']} (trend={kw['trend_score']}, opportunity={kw['opportunity_score']})")

    return output_path


if __name__ == "__main__":
    main()
