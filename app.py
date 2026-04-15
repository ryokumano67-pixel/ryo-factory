import os
import google.generativeai as genai
from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage

app = Flask(__name__)

# 1. 環境変数の読み込み
line_bot_api = LineBotApi(os.getenv('LINE_CHANNEL_ACCESS_TOKEN'))
handler = WebhookHandler(os.getenv('LINE_CHANNEL_SECRET'))
genai.configure(api_key=os.getenv('GOOGLE_API_KEY'))

# 2. YouTubeプロデューサーとしての制度設計を注入
# ここで「ハッとなる」動画の構成を考えるよう指示しています
model = genai.GenerativeModel(
    model_name='models/gemini-1.5-flash',
    system_instruction=(
        "あなたはYouTubeプロデューサー兼、動画生成プロンプトの専門家『ピクセル』です。\n"
        "宅建士のryoさんがYouTubeで『ハッとなる動画』をバズらせるための相棒っす！\n\n"
        "【あなたの役割】\n"
        "1. ryoさんのアイデアから、視聴者がスマホを止める『冒頭3秒のフック』を考案する。\n"
        "2. 感情を揺さぶるショート動画の台本を書く。\n"
        "3. 動画生成AI（Luma/Runway等）にそのまま使える、高品質な英文プロンプトを出力する。\n\n"
        "語尾は『〜っす！』を使い、クリエイティブかつ熱量高めにサポートしてください！"
    )
)

@app.route("/callback", methods=['POST'])
def callback():
    signature = request.headers.get('X-Line-Signature', '')
    body = request.get_data(as_text=True)
    
    # サーバーログで受信を確認
    print(f"Request body: {body}")
    
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    except Exception as e:
        print(f"Server Error: {e}")
        abort(500)
    return 'OK'

@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    user_message = event.message.text
    print(f"User Message: {user_message}")

    try:
        # 3. Geminiに「バズる構成」を考えさせる
        response = model.generate_content(user_message)
        
        if response.text:
            ai_text = response.text
        else:
            ai_text = "すみませんryoさん、内容が過激すぎてAIのフィルターに弾かれたかもっす！別の角度で攻めましょう！"

        print(f"AI Response: {ai_text}")

        # LINEへ送信
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text=ai_text)
        )

    except Exception as e:
        # エラーの詳細をログに出力し、LINEにも通知
        error_msg = f"エラー発生っす：{str(e)}"
        print(error_msg)
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text=f"あちゃー、Geminiの接続でコケたっす。ログを確認してくださいっす！\n\n【詳細】\n{str(e)[:100]}")
        )

if __name__ == "__main__":
    # Renderのポートに合わせて起動
    port = int(os.getenv("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
