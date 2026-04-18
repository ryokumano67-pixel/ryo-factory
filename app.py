import os
from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage

app = Flask(__name__)

# 環境変数から設定を読み込み
line_bot_api = LineBotApi(os.getenv('LINE_CHANNEL_ACCESS_TOKEN'))
handler = WebhookHandler(os.getenv('LINE_CHANNEL_SECRET'))

# Webhookの受け口（ここが重要）
@app.route("/webhook", methods=['POST'])
def webhook():
    # LINEからの署名を検証
    signature = request.headers['X-Line-Signature']
    body = request.get_data(as_text=True)

    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    return 'OK'

# メッセージが届いた時の処理（ここを今後カスタマイズ）
@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    # 今はテストとして返信だけ返す
    line_bot_api.reply_message(
        event.reply_token,
        TextSendMessage(text="Webhookは正常に繋がりました！")
    )

if __name__ == "__main__":
    app.run()
