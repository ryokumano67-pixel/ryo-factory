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
    # 試行するモデルの優先順位リスト（最新から順に）
    models = ["claude-3-5-sonnet-latest", "claude-3-opus-20240229", "claude-3-haiku-20240307"]
    
    response_text = ""
    for model_name in models:
        try:
            message = client.messages.create(
                model=model_name,
                max_tokens=2000,
                system="あなたはryoさんのYouTube収益化プロデューサーです。月収100万を目指すための戦略をLINEで返信してください。",
                messages=[{"role": "user", "content": event.message.text}]
            )
            response_text = message.content[0].text
            break # 成功したらループを抜ける
        except Exception as e:
            # 最新モデルが404なら、次の安定モデルで再試行
            if "404" in str(e):
                continue
            else:
                response_text = f"【接続エラー】\n{str(e)}"
                break

    if not response_text:
        response_text = "現在、AIモデルの準備が整っていないようです。しばらく時間をおいてから再度お試しください。"

    line_bot_api.reply_message(
        event.reply_token,
        TextSendMessage(text=response_text)
    )

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 5000)))
