"""
scheduler.py
毎朝6時に fetch_trends → generate_script → LINE通知 を順番に実行する。
"""

import logging
import os
import sys
import time
from pathlib import Path

import subprocess

import schedule
from dotenv import load_dotenv

# ── 環境設定 ──────────────────────────────────────────────
BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

LINE_NOTIFY_USER_ID = os.getenv("LINE_NOTIFY_USER_ID", "")  # 通知先ユーザーID

LOG_DIR = BASE_DIR / "logs"
LOG_DIR.mkdir(exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_DIR / "scheduler.log", encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger(__name__)


def run_step(label: str, module_path: str) -> bool:
    """指定モジュールの main() を同プロセス内で呼び出す。失敗時は False を返す。"""
    import importlib.util

    log.info(f"▶ {label} を開始します")
    try:
        spec = importlib.util.spec_from_file_location("_step", module_path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        mod.main()
        log.info(f"✅ {label} 完了")
        return True
    except SystemExit as e:
        log.error(f"❌ {label} が sys.exit({e.code}) で終了しました")
        return False
    except Exception as e:
        log.error(f"❌ {label} でエラーが発生しました: {e}", exc_info=True)
        return False


def send_line_notification() -> bool:
    """ryo-factoryの /notify エンドポイントを叩いてLINE通知を送る。"""
    if not LINE_NOTIFY_USER_ID:
        log.warning("LINE_NOTIFY_USER_ID が未設定のため通知をスキップします")
        return False
    service_url = os.getenv("SERVICE_URL", "https://ryo-factory.onrender.com")
    url = f"{service_url}/notify/{LINE_NOTIFY_USER_ID}"
    try:
        import requests
        resp = requests.post(url, timeout=30)
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
    """1→2→3 のパイプラインを実行する。"""
    log.info("=" * 50)
    log.info("YouTube ショート自動生成パイプライン開始")
    log.info("=" * 50)

    # ステップ1: トレンド取得
    ok = run_step(
        "ステップ1: トレンド取得",
        str(BASE_DIR / "0_trends" / "fetch_trends.py"),
    )
    if not ok:
        log.error("トレンド取得に失敗したためパイプラインを中断します")
        return

    # ステップ2: 台本生成
    ok = run_step(
        "ステップ2: 台本生成",
        str(BASE_DIR / "1_scripts" / "generate_script.py"),
    )
    if not ok:
        log.error("台本生成に失敗したためパイプラインを中断します")
        return

    # ステップ3: LINE 通知
    send_line_notification()

    log.info("=" * 50)
    log.info("パイプライン完了。LINE の返信をお待ちください。")
    log.info("=" * 50)


def main() -> None:
    log.info(f"スケジューラーを起動します。毎朝 06:00 に実行します。")
    log.info(f"LINE 通知先ユーザーID: {LINE_NOTIFY_USER_ID or '(未設定)'}")

    schedule.every().day.at("06:00").do(pipeline)

    # 起動直後に一度実行したい場合は以下のコメントを外す
    # pipeline()

    log.info("待機中... (Ctrl+C で停止)")
    while True:
        schedule.run_pending()
        time.sleep(30)


if __name__ == "__main__":
    # 引数 --now を付けると即時実行
    if len(sys.argv) > 1 and sys.argv[1] == "--now":
        log.info("--now オプション: パイプラインを即時実行します")
        pipeline()
    else:
        main()
