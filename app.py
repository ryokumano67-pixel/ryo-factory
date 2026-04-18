import os
from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage
import anthropic

app = Flask(__name__)

# 環境変数から設定を取得
LINE_CHANNEL_ACCESS_TOKEN = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN")
LINE_CHANNEL_SECRET = os.environ.get("LINE_CHANNEL_SECRET")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY")

line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)
client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

@app.route("/callback", methods=['POST'])
def callback():
    signature = request.headers['X-Line-Signature']
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
        # ここが重要！モデル名を最新の claude-sonnet-4-6 に変更しました
        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=1000,
            messages=[{"role": "user", "content": user_message}]
        )
        
        reply_text = response.content[0].text
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text=reply_text)
        )
    except Exception as e:
        # エラーが出た場合、LINEにエラー内容を返します（デバッグ用）
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text=f"エラーが発生しました: {str(e)}")
        )

if __name__ == "__main__":
    app.run()
