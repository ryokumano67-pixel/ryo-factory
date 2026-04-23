"""
generate_video.py
1_scripts の最新JSONから台本を読み込み、Creatomate API で
YouTubeショート用縦型動画（9:16, 1080x1920）を生成する。

デザイン方針:
  - 白背景 + 大きな黒文字（シンプル・見やすい）
  - 台本を短いフレーズに分割し、60秒で均等表示
  - 1フレーズ = 1スライド（重なりなし）
"""

import json
import logging
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path

import requests
from dotenv import load_dotenv

# ── 環境設定 ──────────────────────────────────────────────
BASE_DIR = Path(__file__).resolve().parents[1]
load_dotenv(BASE_DIR / ".env")

CREATOMATE_API_KEY = os.getenv("CREATOMATE_API_KEY")
CREATOMATE_API_URL = "https://api.creatomate.com/v1/renders"

OUTPUT_DIR = BASE_DIR / "3_video"
OUTPUT_DIR.mkdir(exist_ok=True)

LOG_DIR = BASE_DIR / "logs"
LOG_DIR.mkdir(exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_DIR / "generate_video.log", encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger(__name__)

# ── 動画設定 ──────────────────────────────────────────────
WIDTH          = 1080
HEIGHT         = 1920
TOTAL_DURATION = 60   # 秒
FRAME_RATE     = 30

# デザイン定数
BG_COLOR       = "#ffffff"       # 白背景
TEXT_COLOR     = "#111111"       # ほぼ黒
ACCENT_COLOR   = "#4f46e5"       # インディゴ（アクセント）
KEYWORD_COLOR  = "#6b7280"       # グレー（キーワードラベル）
FONT_FAMILY    = "Noto Sans JP"
FONT_SIZE_MAIN = "120px"         # メインテロップ（画面幅の約25%）
FONT_SIZE_KW   = "44px"          # キーワードラベル

# 1スライドあたりの最大文字数（これ以上は改行で折り返す）
MAX_CHARS_PER_LINE = 12

# フレーズ末尾とみなす区切り文字
SPLIT_CHARS = "。！？"


# ── テキスト処理 ──────────────────────────────────────────

def extract_script_text(script_data: dict) -> str:
    """台本JSONからシーンタグを除去した純粋なテキストを返す。"""
    text = script_data.get("script", "")
    # [フック] [本編] [CTA] などのタグを除去
    text = re.sub(r"\[[^\]]+\]\s*", "", text)
    return text.strip()


def split_into_phrases(text: str) -> list[str]:
    """
    台本テキストを短いフレーズに分割する。
    ・SPLIT_CHARS（句点・感嘆符・疑問符）で区切る
    ・1フレーズが MAX_CHARS_PER_LINE を超えたら読点（、）でも区切る
    """
    # 句点類の後ろで分割（句点を末尾に残す）
    raw = re.split(r"(?<=[。！？])", text)
    phrases: list[str] = []

    for segment in raw:
        segment = segment.strip()
        if not segment:
            continue

        # 長すぎる場合は読点でさらに分割
        if len(segment) > MAX_CHARS_PER_LINE:
            sub = re.split(r"(?<=、)", segment)
            buf = ""
            for part in sub:
                if len(buf) + len(part) <= MAX_CHARS_PER_LINE:
                    buf += part
                else:
                    if buf:
                        phrases.append(buf.strip())
                    buf = part
            if buf.strip():
                phrases.append(buf.strip())
        else:
            phrases.append(segment)

    return [p for p in phrases if p]


# ── Creatomate ソース構築 ─────────────────────────────────

def build_source(script_data: dict) -> dict:
    """
    台本データから Creatomate ソース JSON を構築する。
    全フレーズを 60 秒で均等割りし、1フレーズ = 1スライドで表示。
    """
    keyword = script_data["keyword"]
    full_text = extract_script_text(script_data)
    phrases = split_into_phrases(full_text)

    if not phrases:
        phrases = [full_text]

    phrase_dur = TOTAL_DURATION / len(phrases)
    log.info(f"  フレーズ数: {len(phrases)}、1枚あたり {phrase_dur:.2f}秒")

    elements: list[dict] = []

    # ── 背景（白） ──
    elements.append({
        "type": "shape",
        "shape": "rectangle",
        "fill_color": BG_COLOR,
        "width": "100%",
        "height": "100%",
        "x": "50%",
        "y": "50%",
        "x_anchor": "50%",
        "y_anchor": "50%",
    })

    # ── 上部アクセントバー ──
    elements.append({
        "type": "shape",
        "shape": "rectangle",
        "fill_color": ACCENT_COLOR,
        "width": "100%",
        "height": "12px",
        "x": "50%",
        "y": "0%",
        "x_anchor": "50%",
        "y_anchor": "0%",
    })

    # ── キーワードラベル（常時表示） ──
    elements.append({
        "type": "text",
        "text": f"#{keyword}",
        "font_family": FONT_FAMILY,
        "font_weight": "700",
        "font_size": FONT_SIZE_KW,
        "fill_color": KEYWORD_COLOR,
        "x": "50%",
        "y": "8%",
        "width": "90%",
        "x_anchor": "50%",
        "y_anchor": "50%",
        "x_alignment": "50%",
    })

    # ── フレーズスライド（1枚ずつ、重なりなし） ──
    for idx, phrase in enumerate(phrases):
        t_in  = idx * phrase_dur
        t_out = t_in + phrase_dur  # noqa: F841

        elements.append({
            "type": "text",
            "text": phrase,
            "font_family": FONT_FAMILY,
            "font_weight": "900",
            "font_size": FONT_SIZE_MAIN,
            "line_height": 1.4,
            "fill_color": TEXT_COLOR,
            "x": "50%",
            "y": "50%",
            "width": "88%",
            "height": "70%",
            "x_anchor": "50%",
            "y_anchor": "50%",
            "x_alignment": "50%",
            "y_alignment": "50%",
            "time": round(t_in, 3),
            "duration": round(phrase_dur, 3),
            "animations": [
                {
                    "time": 0,
                    "duration": 0.2,
                    "easing": "linear",
                    "type": "fade",
                    "fade": True,
                    "scope": "element",
                }
            ],
        })

    # ── 下部プログレスバー（全体） ──
    elements.append({
        "type": "shape",
        "shape": "rectangle",
        "fill_color": "#e5e7eb",   # 薄グレー（トラック）
        "width": "100%",
        "height": "8px",
        "x": "50%",
        "y": "95%",
        "x_anchor": "50%",
        "y_anchor": "50%",
    })
    # 進行するバー（keyframe アニメーション）
    elements.append({
        "type": "shape",
        "shape": "rectangle",
        "fill_color": ACCENT_COLOR,
        "height": "8px",
        "x": "0%",
        "y": "95%",
        "x_anchor": "0%",
        "y_anchor": "50%",
        "animations": [
            {
                "time": 0,
                "duration": TOTAL_DURATION,
                "easing": "linear",
                "type": "scale",
                "scope": "element",
                "x_scale": [0, 1],
                "x_anchor": "0%",
            }
        ],
    })

    return {
        "output_format": "mp4",
        "width": WIDTH,
        "height": HEIGHT,
        "duration": TOTAL_DURATION,
        "frame_rate": FRAME_RATE,
        "elements": elements,
    }


# ── Creatomate API ────────────────────────────────────────

def submit_render(source: dict) -> str:
    headers = {
        "Authorization": f"Bearer {CREATOMATE_API_KEY}",
        "Content-Type": "application/json",
    }
    resp = requests.post(CREATOMATE_API_URL, headers=headers,
                         json={"source": source}, timeout=30)
    if not resp.ok:
        raise RuntimeError(f"Creatomate API エラー {resp.status_code}: {resp.text}")
    render_id = resp.json()[0]["id"]
    log.info(f"  レンダリング投入: render_id={render_id}")
    return render_id


def poll_render(render_id: str, timeout: int = 300, interval: int = 5) -> str:
    headers = {"Authorization": f"Bearer {CREATOMATE_API_KEY}"}
    url = f"https://api.creatomate.com/v1/renders/{render_id}"
    deadline = time.time() + timeout

    while time.time() < deadline:
        resp = requests.get(url, headers=headers, timeout=15)
        if not resp.ok:
            raise RuntimeError(f"ポーリングエラー {resp.status_code}: {resp.text}")
        data   = resp.json()
        status = data.get("status")
        log.info(f"  ステータス: {status}")
        if status == "succeeded":
            return data["url"]
        if status == "failed":
            raise RuntimeError(f"レンダリング失敗: {data.get('error_message', '(詳細不明)')}")
        time.sleep(interval)

    raise TimeoutError(f"レンダリングが {timeout} 秒以内に完了しませんでした")


def download_video(url: str, dest: Path) -> None:
    log.info(f"  ダウンロード中: {url}")
    with requests.get(url, stream=True, timeout=120) as resp:
        resp.raise_for_status()
        with open(dest, "wb") as f:
            for chunk in resp.iter_content(chunk_size=65536):
                f.write(chunk)
    log.info(f"  保存完了: {dest}  ({dest.stat().st_size // 1024} KB)")


# ── メイン ────────────────────────────────────────────────

def load_latest_scripts() -> tuple[list[dict], str]:
    scripts_dir = BASE_DIR / "1_scripts"
    json_files = sorted(scripts_dir.glob("scripts_*.json"), reverse=True)
    if not json_files:
        log.error("台本ファイルが見つかりません。先に generate_script.py を実行してください。")
        sys.exit(1)
    latest = json_files[0]
    log.info(f"台本ファイル: {latest.name}")
    with open(latest, encoding="utf-8") as f:
        data = json.load(f)
    return data["scripts"], latest.name


def main(only_first: bool = False) -> None:
    if not CREATOMATE_API_KEY:
        log.error("CREATOMATE_API_KEY が設定されていません")
        sys.exit(1)

    scripts, src_name = load_latest_scripts()
    if only_first:
        scripts = scripts[:1]

    date_str  = datetime.now().strftime("%Y%m%d_%H%M%S")
    generated: list[dict] = []

    for script_data in scripts:
        keyword = script_data["keyword"]
        log.info(f"=== 動画生成: {keyword} ===")
        try:
            source    = build_source(script_data)
            render_id = submit_render(source)
            video_url = poll_render(render_id)
            dest      = OUTPUT_DIR / f"video_{keyword}_{date_str}.mp4"
            download_video(video_url, dest)
            generated.append({"keyword": keyword, "path": str(dest), "url": video_url})
            log.info(f"✅ {keyword} 完了")
        except Exception as e:
            log.error(f"❌ {keyword} 失敗: {e}")

    summary = OUTPUT_DIR / f"videos_{date_str}.json"
    with open(summary, "w", encoding="utf-8") as f:
        json.dump(
            {"generated_at": datetime.now().isoformat(),
             "source_scripts": src_name, "videos": generated},
            f, ensure_ascii=False, indent=2,
        )
    log.info(f"=== {len(generated)}/{len(scripts)} 件完了 → {summary.name} ===")


if __name__ == "__main__":
    # --all を付けると全キーワード生成、デフォルトは1本のみ（テスト用）
    only_first = "--all" not in sys.argv
    main(only_first=only_first)
