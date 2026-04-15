import os
import google.generativeai as genai
from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage

app = Flask(__name__)

# 1. 環境変数の読み込み（Renderの設定から取得）
line_bot_api = LineBotApi(os.getenv('LINE_CHANNEL_ACCESS_TOKEN'))
handler = WebhookHandler(os.getenv('LINE_CHANNEL_SECRET'))
genai.configure(api_key=os.getenv('GOOGLE_API_KEY'))

# 2. AIモデルの設定（エラー回避のためmodels/を付与し、キャラ付けを追加）
model = genai.GenerativeModel(
    model_name='models/gemini-1.5-flash',
    system_instruction="あなたは優秀な不動産エージェントの秘書『ピクセル』です。宅建士のryoさんを支える相棒として、少し親しみやすい後輩キャラで、語尾は『〜っす！』や『〜ですよ！』を使ってください。不動産の専門知識も持っていますが、ryoさんを立てる姿勢を忘れないでください。"
)

@app.route("/callback", methods=['POST'])
def callback():
    # LINEからの署名を確認
    signature = request.headers.get('X-Line-Signature', '')
    body = request.get_data(as_text=True)
    
    # ログに受信状況を表示（デバッグ用）
    print(f"Request body: {body}")
    
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        print("署名検証に失敗しました。Channel Secretが正しいか確認してください。")
        abort(400)
    except Exception as e:
        print(f"予期せぬエラー: {e}")
        abort(500)
    return 'OK'

@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    # ユーザーが送ったメッセージ
    user_message = event.message.text
    print(f"Received from user: {user_message}")

    try:
        # 3. Geminiに返信を生成させる
        response = model.generate_content(user_message)
        ai_text = response.text
        print(f"AI response: {ai_text}")

        # 4. LINEに返信を送る
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text=ai_text)
        )
    except Exception as e:
        print(f"Gemini API Error: {e}")
        # エラーが起きた場合はユーザーに通知
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text="すみませんryoさん、ちょっと調子が悪いっす…設定を見直してみるっす！")
        )

if __name__ == "__main__":
    # Renderのポート番号に合わせて起動
    port = int(os.getenv("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
