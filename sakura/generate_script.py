"""
sakura/generate_script.py
朝ストレッチ動画（60秒）の台本を Claude API で生成する。
トレンドファイル不要 — 21種のテーマを日付ベースでローテーション。
"""

import json
import os
import sys
import logging
from datetime import datetime
from pathlib import Path

import anthropic
from dotenv import load_dotenv

SAKURA_DIR = Path(__file__).resolve().parent
BASE_DIR = SAKURA_DIR.parent
load_dotenv(BASE_DIR / ".env")

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")

LOG_DIR = BASE_DIR / "logs"
LOG_DIR.mkdir(exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_DIR / "sakura_generate.log", encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger(__name__)

REPLACEMENTS = {
    "今日は": "きょうは",
    "お腹": "おなか",
    "脇腹": "わきばら",
    "わき腹": "わきばら",
    "一日": "いちにち",
}

STRETCH_TOPICS = [
    "肩こり解消ストレッチ",
    "腰痛予防ストレッチ",
    "股関節ほぐしストレッチ",
    "ふくらはぎ・脚のストレッチ",
    "首こり解消ストレッチ",
    "姿勢改善・背中ストレッチ",
    "全身疲労回復ストレッチ",
    "ハムストリングス柔軟ストレッチ",
    "胸・肩甲骨ストレッチ",
    "骨盤リセットストレッチ",
    "手首・腕のストレッチ",
    "足首・ふとももストレッチ",
    "体幹ストレッチ",
    "睡眠の質を上げる夜ストレッチ",
    "デスクワーク疲れ解消ストレッチ",
    "スマホ首解消ストレッチ",
    "お腹・わき腹ストレッチ",
    "むくみ解消ふくらはぎストレッチ",
    "朝イチ全身覚醒ストレッチ",
    "肩甲骨はがしストレッチ",
    "開脚・股関節ストレッチ",
    "首ストレッチ",
    "胸開きストレッチ",
    "股関節ストレッチ",
    "骨盤矯正ストレッチ",
    "ふくらはぎストレッチ",
    "内もものストレッチ",
    "背中ストレッチ",
    "お尻ストレッチ",
    "足首回しストレッチ",
    "体側ストレッチ",
]

SYSTEM_PROMPT = """あなたは「サクラ」という、明るく親しみやすい20代女性のAIフィットネストレーナーです。
視聴者に直接話しかけるような、テンポよく自然な話し言葉で60秒の台本を書いてください。

台本の制約:
- 尺: 約60秒（読み上げ文字数 160〜200字）
- 構成: ①挨拶・導入(5秒) → ②ストレッチ解説・実演(45秒) → ③締め・応援(10秒)
- 「おはよう！」から始める
- 友達に話しかけるような自然な口語（「〜だよ」「〜しようね」「〜してみて」「〜だよね」など）
- 書き言葉・説明文調は絶対に使わない（「〜します」「〜してください」を多用しない）
- 「ね」「よ」「よね」「かな」「だよ」などの語尾を自然に混ぜる
- 具体的な動作を伝える（「右腕を〜」「ゆっくり〜」など）
- ストレッチポーズをキープする場面では「1... 2... 3... 4... 5... 6... 7... 8... 9... 10」とカウントする（1ポーズ1回）。数字の間の「...」は必須（ポーズのため）
- 体への効果を一言添える
- 最後は「今日も一緒にがんばろう！」などポジティブな締め
- 読点「、」を多めに入れて自然な間を作る
- 1文は15〜20文字を目安に短く切る
- 1行は意味のまとまりで区切り、最大25文字以内にする
- 段落（動作の切れ目）の区切りは空行を入れる

出力は必ず以下のJSON形式のみで返してください（コードブロック不要）:
{
  "keyword": "ストレッチのテーマ",
  "topic": "ストレッチのテーマ",
  "script": "台本全文（サクラの読み上げテキストのみ）",
  "scenes": [
    {"name": "導入", "text": "..."},
    {"name": "ストレッチ解説", "text": "..."},
    {"name": "締め", "text": "..."}
  ],
  "title_candidates": ["タイトル案1", "タイトル案2", "タイトル案3"],
  "tags": ["朝ストレッチ", "ストレッチ", "サクラ", "AIトレーナー", "タグ5"],
  "description": "動画説明文（100字程度）",
  "trend_score": 80
}"""


def get_today_topics() -> list[str]:
    """日付ベースで3テーマを選ぶ（毎日違うテーマ）"""
    day_of_year = datetime.now().timetuple().tm_yday
    start = (day_of_year * 3) % len(STRETCH_TOPICS)
    return [STRETCH_TOPICS[(start + i) % len(STRETCH_TOPICS)] for i in range(3)]


def generate_script_for_topic(client: anthropic.Anthropic, topic: str, instruction: str = "") -> dict:
    user_content = f"今日のテーマ: {topic}"
    if instruction:
        user_content += f"\n追加指示: {instruction}"

    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1500,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_content}],
    )

    raw = message.content[0].text.strip()
    try:
        result = json.loads(raw)
    except json.JSONDecodeError:
        import re
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if match:
            result = json.loads(match.group())
        else:
            log.error(f"JSONパース失敗: {raw[:200]}")
            raise

    result["generated_at"] = datetime.now().isoformat()
    for word, reading in REPLACEMENTS.items():
        result["script"] = result["script"].replace(word, reading)
    return result


def save_scripts(scripts: list[dict]) -> Path:
    output_dir = SAKURA_DIR / "scripts"
    output_dir.mkdir(exist_ok=True)
    date_str = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_path = output_dir / f"scripts_{date_str}.json"
    payload = {
        "generated_at": datetime.now().isoformat(),
        "scripts": scripts,
    }
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    log.info(f"台本を保存しました: {output_path}")
    return output_path


def main(instruction: str = "") -> Path:
    if not ANTHROPIC_API_KEY:
        log.error("ANTHROPIC_API_KEY が設定されていません")
        sys.exit(1)

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    topics = get_today_topics()
    log.info(f"本日のテーマ: {topics}")

    scripts = []
    for topic in topics:
        try:
            script = generate_script_for_topic(client, topic, instruction)
            scripts.append(script)
            log.info(f"  生成完了: {topic} → {script.get('title_candidates', [])[:1]}")
        except Exception as e:
            log.error(f"台本生成エラー ({topic}): {e}")

    if not scripts:
        log.error("台本を1件も生成できませんでした")
        sys.exit(1)

    output_path = save_scripts(scripts)
    log.info(f"=== {len(scripts)} 件の台本生成完了 ===")
    return output_path


if __name__ == "__main__":
    instruction = os.getenv("REGENERATE_INSTRUCTION", "")
    main(instruction)
