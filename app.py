import os
import anthropic
from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage

app = Flask(__name__)

line_bot_api = LineBotApi(os.getenv('LINE_CHANNEL_ACCESS_TOKEN'))
handler = WebhookHandler(os.getenv('LINE_CHANNEL_SECRET'))

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
    # APIキーが読み込めているかチェック
    api_key = os.getenv('ANTHROPIC_API_KEY')
    if not api_key:
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text="エラー：ANTHROPIC_API_KEYが設定されていません。"))
        return

    try:
        # 最も軽量で制限の少ない 'claude-3-haiku-20240307' を試します
        client = anthropic.Anthropic(api_key=api_key)
        message = client.messages.create(
            model="claude-3-haiku-20240307",
            max_tokens=1000,
            messages=[{"role": "user", "content": event.message.text}]
        )
        response = message.content[0].text
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=response))
    except Exception as e:
        # 404が出る本当の理由を日本語で詳しく出力させます
        error_detail = str(e)
        msg = f"【診断結果】\nAIがまだ準備できていないようです。\n理由: {error_detail}\n\n※支払いが反映されるまで数時間かかる場合があります。"
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=msg))

if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
