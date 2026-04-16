import os
import anthropic
from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage

app = Flask(__name__)

# 環境変数
line_bot_api = LineBotApi(os.getenv('LINE_CHANNEL_ACCESS_TOKEN'))
handler = WebhookHandler(os.getenv('LINE_CHANNEL_SECRET'))
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
    try:
        # 入金済みなら絶対にこれ！最強のClaude 3.5 Sonnetを使います
        message = client.messages.create(
            model="claude-3-5-sonnet-latest",
            max_tokens=2000,
            system="あなたはryoさんのYouTube収益化プロデューサーです。月商100万を目指すための戦略をLINEで簡潔に返信してください。",
            messages=[{"role": "user", "content": event.message.text}]
        )
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=message.content[0].text))
    except Exception as e:
        # エラーが起きたら、LINEにその理由を具体的に吐き出させます
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text=f"【システムログ】\n{str(e)}")
        )

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 5000)))
