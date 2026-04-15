import os
import anthropic
from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage

app = Flask(__name__)

# 環境変数の読み込み（LINE用）
line_bot_api = LineBotApi(os.getenv('LINE_CHANNEL_ACCESS_TOKEN'))
handler = WebhookHandler(os.getenv('LINE_CHANNEL_SECRET'))

# Claude用クライアント（ここが今回の心臓部です）
# ANTHROPIC_API_KEY が正しく設定されていれば動きます
anthropic_key = os.getenv('ANTHROPIC_API_KEY')
client = anthropic.Anthropic(api_key=anthropic_key)

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
        # ryoさんの収益化ロードマップに最適化されたシステムプロンプト
        message = client.messages.create(
            model="claude-3-5-sonnet-latest",
            max_tokens=2000,
            temperature=0.7,
            system=(
                "あなたはryoさんのYouTube収益化を支援するトッププロデューサーです。\n"
                "目標：5月中旬に登録者1000人、8月に月商30万、最終的に月商100万突破。\n\n"
                "【戦略】\n"
                "1. 世界中のトレンドから『今すぐバズる』企画を提案する。\n"
                "2. 5チャンネル同時運用の効率化を最優先する。\n"
                "3. 動画生成AI（Luma等）用のプロンプトも提供する。\n"
                "4. 不動産実務の知見を活かした高単価ジャンルの提案も行う。"
            ),
            messages=[{"role": "user", "content": user_message}]
        )
        
        ai_response = message.content[0].text

        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text=ai_response)
        )
    except Exception as e:
        # エラーが起きた場合に、何が原因かLINEで詳細に教えるようにしました
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text=f"【再設定が必要です】\n{str(e)}")
        )

if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
