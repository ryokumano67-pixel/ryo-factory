"""
sakura/batch.py
10本一気生成・投稿スクリプト。

使い方:
  python3 sakura/batch.py                    # 10本生成（YouTube投稿あり）
  python3 sakura/batch.py --count 5          # 5本だけ
  python3 sakura/batch.py --dry-run          # 台本生成のみ（音声・動画・投稿なし）
  python3 sakura/batch.py --start 0          # PRIORITY_TOPICSの先頭から
  SAKURA_SKIP_UPLOAD=false python3 sakura/batch.py  # YouTube投稿ON
"""

import argparse
import json
import os
import sys
import time
import logging
from pathlib import Path
from datetime import datetime

SAKURA_DIR = Path(__file__).resolve().parent
BASE_DIR = SAKURA_DIR.parent
sys.path.insert(0, str(BASE_DIR))

from dotenv import load_dotenv
load_dotenv(BASE_DIR / ".env", override=True)

LOG_DIR = BASE_DIR / "logs"
LOG_DIR.mkdir(exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_DIR / "sakura_batch.log", encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger(__name__)

# 初回バースト用：検索需要が高いトピックを優先順に並べた
PRIORITY_TOPICS = [
    "肩こり解消ストレッチ",
    "腰痛予防ストレッチ",
    "スマホ首解消ストレッチ",
    "デスクワーク疲れ解消ストレッチ",
    "股関節ほぐしストレッチ",
    "むくみ解消ふくらはぎストレッチ",
    "姿勢改善・背中ストレッチ",
    "骨盤リセットストレッチ",
    "首こり解消ストレッチ",
    "朝イチ全身覚醒ストレッチ",
    "肩甲骨はがしストレッチ",
    "全身疲労回復ストレッチ",
    "睡眠の質を上げる夜ストレッチ",
    "体幹ストレッチ",
    "開脚・股関節ストレッチ",
]


def generate_scripts_batch(topics: list[str]) -> list[dict]:
    from sakura.generate_script import generate_script_for_topic
    import anthropic
    client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
    scripts = []
    for i, topic in enumerate(topics, 1):
        log.info(f"台本生成 [{i}/{len(topics)}]: {topic}")
        try:
            script = generate_script_for_topic(client, topic)
            scripts.append(script)
            log.info(f"  完了: {script.get('title_candidates', [''])[0]}")
        except Exception as e:
            log.error(f"  失敗: {e}")
    return scripts


def save_batch_scripts(scripts: list[dict]) -> Path:
    output_dir = SAKURA_DIR / "scripts"
    output_dir.mkdir(exist_ok=True)
    date_str = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = output_dir / f"batch_{date_str}.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"generated_at": datetime.now().isoformat(), "scripts": scripts}, f, ensure_ascii=False, indent=2)
    log.info(f"台本保存: {path}")
    return path


def run_batch(topics: list[str], dry_run: bool = False):
    log.info(f"=== サクラ バッチ生成開始: {len(topics)}本 ===")
    skip_upload = os.getenv("SAKURA_SKIP_UPLOAD", "true").lower() != "false"
    log.info(f"YouTube投稿: {'スキップ' if skip_upload else '実行'}")

    # 台本一括生成
    scripts = generate_scripts_batch(topics)
    if not scripts:
        log.error("台本を1件も生成できませんでした")
        sys.exit(1)

    script_path = save_batch_scripts(scripts)
    log.info(f"台本 {len(scripts)}件 生成完了")

    if dry_run:
        log.info("=== dry-run完了（音声・動画・投稿はスキップ） ===")
        print(f"\n台本ファイル: {script_path}")
        for i, s in enumerate(scripts, 1):
            print(f"  [{i}] {s.get('topic','')}: {s.get('title_candidates', [''])[0]}")
        return

    # パイプライン実行
    from sakura.pipeline import run_pipeline
    results = []
    for i, script in enumerate(scripts, 1):
        topic = script.get("topic", script.get("keyword", ""))
        log.info(f"\n▶ パイプライン [{i}/{len(scripts)}]: {topic}")
        try:
            result = run_pipeline(topic, script_data=script, index=i - 1)
            results.append({"topic": topic, "result": result, "status": "ok"})
            log.info(f"  ✓ 完了: {result}")
        except Exception as e:
            log.error(f"  ✗ 失敗: {e}")
            results.append({"topic": topic, "error": str(e), "status": "error"})
        # HeyGenのレート制限を避けるため少し待機
        if i < len(scripts):
            log.info("次の動画まで30秒待機...")
            time.sleep(30)

    # 結果サマリー
    ok = [r for r in results if r["status"] == "ok"]
    ng = [r for r in results if r["status"] == "error"]
    log.info(f"\n=== バッチ完了: 成功 {len(ok)}本 / 失敗 {len(ng)}本 ===")
    for r in ok:
        log.info(f"  ✓ {r['topic']}: {r['result']}")
    for r in ng:
        log.error(f"  ✗ {r['topic']}: {r['error']}")

    result_path = SAKURA_DIR / "scripts" / f"batch_result_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    with open(result_path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    log.info(f"結果保存: {result_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--count", type=int, default=10, help="生成本数（デフォルト10）")
    parser.add_argument("--start", type=int, default=0, help="PRIORITY_TOPICSの開始インデックス")
    parser.add_argument("--dry-run", action="store_true", help="台本生成のみ（音声・動画・投稿スキップ）")
    parser.add_argument("--script-file", default=None, help="既存の台本JSONを再利用（台本生成スキップ）")
    args = parser.parse_args()

    if args.script_file:
        with open(args.script_file, encoding="utf-8") as f:
            data = json.load(f)
        scripts = data["scripts"] if "scripts" in data else [data]
        log.info(f"既存台本を使用: {args.script_file} ({len(scripts)}件)")
        skip_upload = os.getenv("SAKURA_SKIP_UPLOAD", "true").lower() != "false"
        log.info(f"YouTube投稿: {'スキップ' if skip_upload else '実行'}")
        from sakura.pipeline import run_pipeline
        results = []
        for i, script in enumerate(scripts, 1):
            topic = script.get("topic", script.get("keyword", ""))
            log.info(f"\n▶ パイプライン [{i}/{len(scripts)}]: {topic}")
            try:
                result = run_pipeline(topic, script_data=script, index=i - 1)
                results.append({"topic": topic, "result": result, "status": "ok"})
                log.info(f"  ✓ 完了: {result}")
            except Exception as e:
                log.error(f"  ✗ 失敗: {e}")
                results.append({"topic": topic, "error": str(e), "status": "error"})
            if i < len(scripts):
                log.info("次の動画まで30秒待機...")
                time.sleep(30)
        ok = [r for r in results if r["status"] == "ok"]
        ng = [r for r in results if r["status"] == "error"]
        log.info(f"\n=== 完了: 成功 {len(ok)}本 / 失敗 {len(ng)}本 ===")
    else:
        topics = PRIORITY_TOPICS[args.start: args.start + args.count]
        if not topics:
            print(f"トピックが見つかりません（start={args.start}, count={args.count}）")
            sys.exit(1)
        run_batch(topics, dry_run=args.dry_run)
