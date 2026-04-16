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
    # 新規アカウントでも通りやすい順に並べ替えました
    target_models = [
        "claude-3-haiku-20240307",
        "claude-3-5-sonnet-latest",
        "claude-3-opus-20240229"
    ]
    
    response_content = None
    error_logs = []

    for model_name in target_models:
        try:
            message = client.messages.create(
                model=model_name,
                max_tokens=1000,
                system="あなたはYouTube収益化プロデューサーです。簡潔に回答してください。",
                messages=[{"role": "user", "content": event.message.text}]
            )
            response_content = message.content[0].text
            break 
        except Exception as e:
            error_logs.append(f"{model_name}: {str(e)}")
            continue

    if not response_content:
        # すべて失敗した場合、何が原因か全モデル分をLINEに報告させます
        final_text = "【重要：Anthropic側の制限が続いています】\n" + "\n".join(error_logs)
    else:
        final_text = response_content

    line_bot_api.reply_message(
        event.reply_token,
        TextSendMessage(text=final_text)
    )

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 5000)))
