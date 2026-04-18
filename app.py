import os
import anthropic
from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage

app = Flask(__name__)

# 環境変数の読み込み
line_bot_api = LineBotApi(os.environ.get("LINE_CHANNEL_ACCESS_TOKEN"))
handler = WebhookHandler(os.environ.get("LINE_CHANNEL_SECRET"))
client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))

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
    try:
        # モデルを最新のClaude 3.5 Haikuに変更しました
        response = client.messages.create(
            model="claude-3-5-haiku-20241022",
            max_tokens=1000,
            messages=[{"role": "user", "content": event.message.text}]
        )
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text=response.content[0].text)
        )
    except Exception as e:
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text=f"API Error: {str(e)}")
        )

if __name__ == "__main__":
    app.run()
