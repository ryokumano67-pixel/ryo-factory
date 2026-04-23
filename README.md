# YouTube ショート動画 自動生成工場

YouTubeショート動画を自動生成・投稿するパイプラインプロジェクトです。

## フォルダ構成

```
youtube-factory/
├── 0_trends/       # トレンドデータ保存（Google Trends・YouTube急上昇など）
├── 1_scripts/      # AIが生成した動画台本（JSON/テキスト形式）
├── 2_audio/        # 音声合成で生成したナレーション音声ファイル
├── 3_video/        # Creatomateで生成した完成動画ファイル
├── logs/           # 各ステップの実行ログ
├── .env            # APIキーなどの環境変数（Git管理外）
├── .gitignore      # .envを除外
└── README.md       # このファイル
```

## パイプライン概要

1. **トレンド収集**（`0_trends/`）  
   Google Trends・YouTube Data API などからトレンドキーワードを取得・保存する。

2. **台本生成**（`1_scripts/`）  
   Anthropic Claude API でトレンドに沿ったショート動画台本を自動生成する。

3. **音声生成**（`2_audio/`）  
   台本テキストをTTS（音声合成）サービスでナレーション音声に変換する。

4. **動画生成**（`3_video/`）  
   Creatomate API で音声・テキスト・素材を合成してショート動画を生成する。

5. **通知・投稿**  
   LINE Messaging API で完了通知を送信し、YouTube Data API でショートに投稿する。

## 使用APIサービス

| サービス | 用途 |
|---|---|
| Anthropic Claude | 台本・タイトル・タグの生成 |
| Google / YouTube Data API | トレンド取得・動画投稿 |
| YouTube OAuth | チャンネルへの投稿認証 |
| LINE Messaging API | 完了・エラー通知 |
| Creatomate | 動画自動生成・レンダリング |

## セットアップ

1. `.env` に各APIキーを設定する。
2. 必要なライブラリをインストールする（各スクリプト参照）。
3. パイプラインを順番に実行するか、スケジューラで自動化する。
