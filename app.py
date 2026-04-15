import os
import anthropic
from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage

app = Flask(__name__)

# 環境変数の読み込み
line_bot_api = LineBotApi(os.getenv('LINE_CHANNEL_ACCESS_TOKEN'))
handler = WebhookHandler(os.getenv('LINE_CHANNEL_SECRET'))
# Claude用クライアント
client = anthropic.Anthropic(api_key=os.getenv('ANTHROPIC_API_KEY'))

@app.route("/callback", methods=['POST'])
def callback():
    signature = request.headers.get('X-Line-Signature', '')
    body = request.get_data(as_text=True)
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    return 'OK'

@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    user_message = event.message.text

    try:
        # Claude 3.5 Sonnetへのリクエスト
        # 収益化とバズを最優先するプロデューサーとして振る舞わせます
        message = client.messages.create(
            model="claude-3-5-sonnet-20240620",
            max_tokens=2000,
            temperature=0.7,
            system=(
                "あなたはYouTube収益化を専門とするトッププロデューサーです。\n"
                "ryoさんの5つのチャンネルを同時並行で成功させ、月商100万を目指すのが使命です。\n\n"
                "【あなたの行動指針】\n"
                "1. 世界中の最新トレンドから、今最もバズりやすいトピックを抽出する。\n"
                "2. 視聴維持率を最大化するため、冒頭3秒の『フック』に全力を注ぐ。\n"
                "3. 動画生成AI（Luma等）用の詳細な英語プロンプトも自動生成する。\n"
                "4. 余計なキャラ付けはせず、プロとして鋭く、かつryoさんがLINEだけで判断できる簡潔な提案を行うこと。"
            ),
            messages=[{"role": "user", "content": user_message}]
        )
        
        ai_response = message.content[0].text

        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text=ai_response)
        )
    except Exception as e:
        error_msg = str(e)
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text=f"【システムエラー】\n設定を確認してください。\n{error_msg[:100]}")
        )

if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
