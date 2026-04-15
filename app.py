import os
import google.generativeai as genai
from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage

app = Flask(__name__)

# 1. 環境変数の設定
line_bot_api = LineBotApi(os.getenv('LINE_CHANNEL_ACCESS_TOKEN'))
handler = WebhookHandler(os.getenv('LINE_CHANNEL_SECRET'))
genai.configure(api_key=os.getenv('GOOGLE_API_KEY'))

# 2. モデルの設定（最新の推奨される書き方に修正）
# system_instructionはモデル作成時に渡す
model = genai.GenerativeModel(
    model_name='gemini-1.5-flash',
    system_instruction="あなたは優秀な不動産エージェントの秘書『ピクセル』です。宅建士のryoさんを支える相棒として、少し親しみやすい後輩キャラで、語尾は『〜っす！』を使ってください。"
)

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
    print(f"User Message: {user_message}")

    try:
        # 3. 返信生成（最新の呼び出し方に修正）
        response = model.generate_content(user_message)
        
        # 安全フィルター等で中身が空の場合の対策
        if response.text:
            ai_response = response.text
        else:
            ai_response = "すみません、その内容にはお答えできないっす…別の言い方でお願いしてもいいっすか？"
        
        print(f"AI Response: {ai_response}")

        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text=ai_response)
        )
    except Exception as e:
        # エラーの内容を具体的にログに出す
        print(f"Detailed Error: {str(e)}")
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text="あちゃー、Geminiの機嫌が悪いみたいっす…ryoさん、ログを確認してもらえますか？")
        )

if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
