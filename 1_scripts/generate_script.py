"""
generate_script.py
0_trends の最新JSONを読み込み、Claude API でYouTubeショート台本とタイトル3案を生成する。
"""

import json
import os
import sys
import logging
from datetime import datetime
from pathlib import Path

import anthropic
from dotenv import load_dotenv

# ── 環境設定 ──────────────────────────────────────────────
BASE_DIR = Path(__file__).resolve().parents[1]
load_dotenv(BASE_DIR / ".env")

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")

LOG_DIR = BASE_DIR / "logs"
LOG_DIR.mkdir(exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_DIR / "generate_script.log", encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger(__name__)

SYSTEM_PROMPT = """あなたはYouTubeショート動画の敏腕脚本家です。
「AI Japan Labo」というチャンネルのために、AIツールの実践的な使い方・活用Tips・時短術を
30〜40代の社会人・副業に興味がある人向けに、テンポよく解説する台本を書いてください。

コンセプト: 「このAIツール、こう使えば人生変わる」という実体験・実践ベースのTips動画

台本の制約:
- 尺: 約60秒（読み上げ文字数 180〜220字）
- 構成: ①フック「え、これできるの？」的な驚き(5秒) → ②具体的な使い方3ステップ(45秒) → ③CTA(10秒)
- 口語体・話し言葉で書く
- 抽象的なニュースや概念ではなく「今すぐ試せる」具体的な内容にする
- AI・ChatGPT・Claude・Notionなど英語の固有名詞はそのまま英語で書く（カタカナ不可）
- 「生成AI」は必ず「生成AI」と表記する（「生成エーアイ」「せいせいえーあい」などに変換しない）
- title_candidatesのタイトルは視聴者が読む文字として書く。読み仮名・ひらがな変換は一切しない
- 1行は意味のまとまりで区切り、最大25文字以内にする
- 改行は意味・テンポの切れ目のみ（句読点ごとに改行しない）
- 段落（シーン）の区切りは空行を入れる

出力は必ず以下のJSON形式のみで返してください（コードブロック不要）:
{
  "keyword": "対象キーワード",
  "script": "台本全文（タグなし・読み上げ用テキストのみ）",
  "scenes": [
    {"name": "フック", "text": "..."},
    {"name": "本編", "text": "..."},
    {"name": "CTA", "text": "..."}
  ],
  "title_candidates": ["タイトル案1", "タイトル案2", "タイトル案3"],
  "tags": ["タグ1", "タグ2", "タグ3", "タグ4", "タグ5"],
  "description": "動画説明文（100字程度）"
}"""


DATA_DIR = Path(os.getenv("DATA_DIR", str(BASE_DIR)))


def load_performance_insights() -> str:
    """週次分析の洞察をプロンプト追記用テキストとして返す"""
    insights_file = DATA_DIR / "performance_insights.json"
    if not insights_file.exists():
        return ""
    try:
        data = json.load(open(insights_file))
        ch = data.get("channels", {}).get("ai_japan", {})
        if not ch:
            return ""
        lines = ["\n【過去データからの学習（自動更新）】"]
        if ch.get("top_title_patterns"):
            lines.append(f"- 伸びるタイトルパターン: {', '.join(ch['top_title_patterns'])}")
        if ch.get("top_topics"):
            lines.append(f"- 伸びるトピック: {', '.join(ch['top_topics'])}")
        if ch.get("avoid_patterns"):
            lines.append(f"- 避けるパターン: {', '.join(ch['avoid_patterns'])}")
        if ch.get("recommended_hook"):
            lines.append(f"- 推奨フック例: {ch['recommended_hook']}")
        lines.append(f"（最終更新: {data.get('updated_at', '?')}）")
        return "\n".join(lines)
    except Exception:
        return ""


def load_latest_trends() -> dict:
    """0_trends フォルダから最新のトレンドJSONを読み込む。"""
    trends_dir = BASE_DIR / "0_trends"
    json_files = sorted(trends_dir.glob("trends_*.json"), reverse=True)
    if not json_files:
        log.error("トレンドファイルが見つかりません。先に fetch_trends.py を実行してください。")
        sys.exit(1)

    latest = json_files[0]
    log.info(f"トレンドファイルを読み込みます: {latest}")
    with open(latest, encoding="utf-8") as f:
        return json.load(f)


def build_user_prompt(keyword_data: dict) -> str:
    """Claude に渡すユーザープロンプトを組み立てる。"""
    kw = keyword_data["keyword"]
    trend = keyword_data["trend_score"]
    top_titles = keyword_data["youtube_competition"].get("top_titles", [])
    titles_str = "\n".join(f"  - {t}" for t in top_titles) if top_titles else "  （なし）"

    return f"""以下のキーワードでYouTubeショート動画の台本とタイトル3案を生成してください。

キーワード: {kw}
トレンドスコア（100点満点）: {trend}
既存の人気動画タイトル例（参考・差別化すること）:
{titles_str}

上記の既存タイトルと被らず、かつより魅力的なタイトルを3案考えてください。"""


def generate_script_for_keyword(client: anthropic.Anthropic, keyword_data: dict) -> dict:
    """1キーワードに対して台本を生成する。"""
    kw = keyword_data["keyword"]
    log.info(f"台本生成中: {kw}")

    insights = load_performance_insights()
    system = SYSTEM_PROMPT + insights if insights else SYSTEM_PROMPT

    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1500,
        system=system,
        messages=[{"role": "user", "content": build_user_prompt(keyword_data)}],
    )

    raw = message.content[0].text.strip()
    try:
        result = json.loads(raw)
    except json.JSONDecodeError:
        # JSONブロックが混入した場合の保険
        import re
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if match:
            result = json.loads(match.group())
        else:
            log.error(f"JSONパース失敗: {raw[:200]}")
            raise

    result["generated_at"] = datetime.now().isoformat()
    result["trend_score"] = keyword_data["trend_score"]
    result["opportunity_score"] = keyword_data.get("opportunity_score", 0)
    return result


def save_scripts(scripts: list[dict], trends_fetched_at: str) -> Path:
    """生成した台本を 1_scripts/ フォルダにJSONで保存する。"""
    output_dir = BASE_DIR / "1_scripts"
    output_dir.mkdir(exist_ok=True)
    date_str = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_path = output_dir / f"scripts_{date_str}.json"

    payload = {
        "generated_at": datetime.now().isoformat(),
        "trends_fetched_at": trends_fetched_at,
        "scripts": scripts,
    }
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    log.info(f"台本を保存しました: {output_path}")
    return output_path


def _load_uploaded_keywords() -> dict:
    """pipeline.pyが記録したアップロード済みキーワードを読み込む"""
    uploaded_file = BASE_DIR / "uploaded_keywords.json"
    if uploaded_file.exists():
        with open(uploaded_file, encoding="utf-8") as f:
            return json.load(f)
    return {}


def _was_recently_uploaded(keyword: str, days: int = 21) -> bool:
    from datetime import timedelta
    data = _load_uploaded_keywords()
    if keyword not in data:
        return False
    uploaded_at_str = data[keyword].get("uploaded_at", "")
    try:
        uploaded_at = datetime.fromisoformat(uploaded_at_str)
        if datetime.now() - uploaded_at < timedelta(days=days):
            log.info(f"スキップ（{days}日以内に投稿済み）: {keyword} ({uploaded_at_str[:10]})")
            return True
    except Exception:
        pass
    return False


def main() -> Path:
    if not ANTHROPIC_API_KEY:
        log.error("ANTHROPIC_API_KEY が設定されていません")
        sys.exit(1)

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    trends_data = load_latest_trends()

    scripts = []
    for kw_data in trends_data["keywords"]:
        kw = kw_data["keyword"]
        if _was_recently_uploaded(kw):
            continue
        try:
            script = generate_script_for_keyword(client, kw_data)
            scripts.append(script)
            log.info(f"  タイトル候補: {script.get('title_candidates', [])}")
        except Exception as e:
            log.error(f"台本生成エラー ({kw}): {e}")

    if not scripts:
        log.error("台本を1件も生成できませんでした")
        sys.exit(1)

    output_path = save_scripts(scripts, trends_data["fetched_at"])
    log.info(f"=== {len(scripts)} 件の台本生成完了 ===")
    return output_path


if __name__ == "__main__":
    main()
