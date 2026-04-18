import os
import anthropic
from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage

app = Flask(__name__)

# --- 設定確認用デバッグ ---
api_key = os.environ.get("ANTHROPIC_API_KEY")
if api_key:
    print(f"DEBUG: Key starts with {api_key[:5]}")
else:
    print("DEBUG: ANTHROPIC_API_KEY is NOT set!")
# -----------------------

line_bot_api = LineBotApi(os.environ.get("LINE_CHANNEL_ACCESS_TOKEN"))
handler = WebhookHandler(os.environ.get("LINE_CHANNEL_SECRET"))
client = anthropic.Anthropic(api_key=api_key)

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
        response = client.messages.create(
            model="claude-3-5-sonnet-20241022",
            max_tokens=1000,
            messages=[{"role": "user", "content": event.message.text}]
        )
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=response.content[0].text))
    except Exception as e:
        # エラー詳細をLINEに返信させる
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=f"API Error: {str(e)}"))

if __name__ == "__main__":
    app.run()
