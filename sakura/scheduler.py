"""
sakura/scheduler.py
毎朝6:00に 台本生成 → LINE通知 を実行する。
既存の scheduler.py（ai_japan_labo用）とは独立して動作する。
"""

import logging
import os
import sys
import subprocess
import time
from pathlib import Path

import schedule
from dotenv import load_dotenv

SAKURA_DIR = Path(__file__).resolve().parent
BASE_DIR = SAKURA_DIR.parent
load_dotenv(BASE_DIR / ".env")

LINE_NOTIFY_USER_ID = os.getenv("LINE_NOTIFY_USER_ID", "")

LOG_DIR = BASE_DIR / "logs"
LOG_DIR.mkdir(exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_DIR / "sakura_scheduler.log", encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger(__name__)


def generate_scripts() -> bool:
    log.info("▶ サクラ台本生成を開始します")
    try:
        result = subprocess.run(
            [sys.executable, str(SAKURA_DIR / "generate_script.py")],
            cwd=str(BASE_DIR),
            capture_output=True,
            text=True,
            timeout=120,
        )
        if result.returncode == 0:
            log.info("✅ 台本生成完了")
            return True
        else:
            log.error(f"❌ 台本生成失敗: {result.stderr[:300]}")
            return False
    except Exception as e:
        log.error(f"❌ 台本生成エラー: {e}")
        return False


def send_line_notification() -> bool:
    if not LINE_NOTIFY_USER_ID:
        log.warning("LINE_NOTIFY_USER_ID が未設定のため通知をスキップします")
        return False
    service_url = os.getenv("SERVICE_URL", "https://ryo-factory.onrender.com")
    url = f"{service_url}/sakura/notify/{LINE_NOTIFY_USER_ID}"
    try:
        import json as json_mod
        import requests
        # 生成したスクリプトファイルを読み込んでbodyに含める
        scripts_dir = SAKURA_DIR / "scripts"
        json_files = sorted(scripts_dir.glob("scripts_*.json"), reverse=True) if scripts_dir.exists() else []
        payload = {}
        if json_files:
            with open(json_files[0], encoding="utf-8") as f:
                data = json_mod.load(f)
            payload = {"scripts": data.get("scripts", []), "script_path": str(json_files[0])}
            log.info(f"スクリプトファイルをbodyに含めます: {json_files[0].name}")
        resp = requests.post(url, json=payload, timeout=30)
        if resp.ok:
            log.info("✅ LINE 通知送信完了")
            return True
        else:
            log.error(f"❌ LINE 通知失敗: {resp.status_code} {resp.text}")
            return False
    except Exception as e:
        log.error(f"❌ LINE 通知エラー: {e}")
        return False


def pipeline() -> None:
    log.info("=" * 50)
    log.info("🌸 サクラ朝ストレッチ自動生成パイプライン開始")
    log.info("=" * 50)

    if not generate_scripts():
        log.error("台本生成に失敗したためパイプラインを中断します")
        return

    send_line_notification()

    log.info("=" * 50)
    log.info("パイプライン完了。LINE の返信をお待ちください。")
    log.info("=" * 50)


def main() -> None:
    log.info("サクラスケジューラーを起動します。毎朝 06:00 に実行します。")
    log.info(f"LINE 通知先ユーザーID: {LINE_NOTIFY_USER_ID or '(未設定)'}")

    schedule.every().day.at("06:00").do(pipeline)

    log.info("待機中... (Ctrl+C で停止)")
    while True:
        schedule.run_pending()
        time.sleep(30)


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--now":
        log.info("--now オプション: パイプラインを即時実行します")
        pipeline()
    else:
        main()
