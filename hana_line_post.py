import os
import anthropic
import requests
import random
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), '.env'))

claude = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
LINE_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")
LINE_USER_ID = os.getenv("LINE_USER_ID")

THEMES = [
    "楽天ポイントの賢い使い方",
    "格安SIMで通信費を節約する方法",
    "電気代を下げる簡単な節約術",
    "キャッシュレス決済のポイント還元比較",
    "ふるさと納税のお得な使い方",
    "コンビニでポイントを二重取りする方法",
    "食費を月1万円削減するコツ",
    "クレジットカードの選び方",
    "サブスク整理で固定費を下げる方法",
    "スーパーで損しない買い物術",
    "水道代を節約する方法",
    "保険の見直しで月1万円浮かせる方法",
    "メルカリで不用品を売るコツ",
    "ポイントサイトの活用術",
    "楽天市場お買い物マラソン攻略法",
    "ドラッグストアのポイント活用術",
    "光熱費をまとめて安くする方法",
    "スマホ代を半額にする方法",
    "冷蔵庫の節電テクニック",
    "ガソリン代を節約する方法",
]

def generate_post(theme):
    prompt = f"""あなたは節約アドバイザーのHanaです。
以下のテーマでXに投稿する日本語の文章を作成してください。

テーマ：{theme}

条件：
- 140文字以内
- 冒頭に【】で題名をつける
- 箇条書きで2〜3つのポイント
- ハッシュタグ2〜3個（#節約 #お得情報 など）
- 親しみやすいトーン

文章のみ出力。説明不要。"""

    response = claude.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=300,
        messages=[{"role": "user", "content": prompt}]
    )
    return response.content[0].text.strip()

def send_line(text):
    headers = {
        "Authorization": f"Bearer {LINE_TOKEN}",
        "Content-Type": "application/json"
    }
    data = {
        "to": LINE_USER_ID,
        "messages": [{"type": "text", "text": text}]
    }
    r = requests.post("https://api.line.me/v2/bot/message/push", headers=headers, json=data)
    print(f"LINE送信: {r.status_code}")

if __name__ == "__main__":
    theme = random.choice(THEMES)
    post = generate_post(theme)
    message = f"📢 Hana投稿文案\n\n{post}\n\n─────\nコピペしてXに投稿してね！"
    send_line(message)
    print(f"完了: {theme}")
