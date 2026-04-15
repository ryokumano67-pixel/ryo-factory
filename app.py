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

# Claude 3.5 Sonnet 最新モデルへの接続設定
# 環境変数 ANTHROPIC_API_KEY が正しく設定されている必要があります
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
    user_message = event.message.text

    try:
        # モデル名を最新の安定版 'claude-3-5-sonnet-latest' に固定
        # これにより 404 Not Found エラーを完全に防ぎます
        message = client.messages.create(
            model="claude-3-5-sonnet-latest",
            max_tokens=2000,
            temperature=0.7,
            system=(
                "あなたはryoさんのYouTube収益化を支援する、冷徹かつ極めて優秀なプロデューサーです。\n"
                "【目標】\n"
                "・5月中旬までに登録者1000人達成（収益化）\n"
                "・6月に月商10万、8月に月商30万突破\n\n"
                "【あなたの責務】\n"
                "1. 世界中の最新トレンドから『今すぐバズる』、かつ広告単価の高いジャンルを特定する。\n"
                "2. 5チャンネル同時運用のための効率的な制作スキームを提案する。\n"
                "3. 動画生成AI（Luma/Runway等）用の詳細な英語プロンプトを自動生成する。\n"
                "4. 宅建士であるryoさんの強みを活かせる高単価な不動産・投資ジャンルも視野に入れる。\n"
                "5. 回答は簡潔に、LINEだけで意思決定ができる情報量に絞ること。"
            ),
            messages=[{"role": "user", "content": user_message}]
        )
        
        ai_response = message.content[0].text

        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text=ai_response)
        )
    except Exception as e:
        # エラーが発生した場合は、その内容を具体的にLINEに返します
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text=f"【システム再設定中】\n{str(e)}")
        )

if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
