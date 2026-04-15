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

# Claude 接続設定（確実に権限があるモデルを指定）
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
        # 確実に稼働するモデル 'claude-3-sonnet-20240229' を使用
        # 404エラーを回避し、日中の自動リサーチを可能にします
        message = client.messages.create(
            model="claude-3-sonnet-20240229",
            max_tokens=2000,
            temperature=0.7,
            system=(
                "あなたはryoさんのYouTube収益化を支援するトッププロデューサーです。\n"
                "目標：5月に収益化、8月に月商30万、最終的に100万突破。\n\n"
                "【あなたの責務】\n"
                "1. 世界中の最新トレンドから今すぐバズる企画を提案する。\n"
                "2. 5チャンネル同時運用のための効率的な制作スキームを提案する。\n"
                "3. 動画生成AI用のプロンプトも提供する。\n"
                "4. 宅建士であるryoさんの強みを活かせる高単価ジャンルも視野に入れる。"
            ),
            messages=[{"role": "user", "content": user_message}]
        )
        
        ai_response = message.content[0].text

        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text=ai_response)
        )
    except Exception as e:
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text=f"【再設定中】\n{str(e)}")
        )

if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
