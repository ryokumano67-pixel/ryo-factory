import os
import tweepy
import anthropic
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parents[1]
load_dotenv(BASE_DIR / ".env")

# X API設定
client = tweepy.Client(
    consumer_key=os.getenv("X_API_KEY"),
    consumer_secret=os.getenv("X_API_SECRET"),
    access_token=os.getenv("X_ACCESS_TOKEN"),
    access_token_secret=os.getenv("X_ACCESS_SECRET")
)

# Claude API設定
claude = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

# テーマリスト（節約・お得情報）
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
]

def generate_post(theme: str) -> str:
    prompt = f"""
あなたは節約アドバイザーのHanaです。
以下のテーマでXに投稿する日本語の文章を1つ作成してください。

テーマ：{theme}

条件：
- 140文字以内
- 冒頭に【】で題名をつける
- 箇条書きで3つのポイントを書く
- 最後に「プロフのリンクから詳細↓」を入れる
- ハッシュタグを2〜3個つける（#節約 #お得情報 など）
- 親しみやすいトーンで

文章のみ出力してください。説明不要。
"""
    response = claude.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=300,
        messages=[{"role": "user", "content": prompt}]
    )
    return response.content[0].text.strip()

def post_to_x(text: str):
    try:
        response = client.create_tweet(text=text)
        print(f"✅ 投稿成功: {response.data['id']}")
        return True
    except Exception as e:
        print(f"❌ 投稿失敗: {e}")
        return False

if __name__ == "__main__":
    import random
    theme = random.choice(THEMES)
    print(f"📝 テーマ: {theme}")
    post = generate_post(theme)
    print(f"📄 生成文章:\n{post}")
    print("---")
    post_to_x(post)
