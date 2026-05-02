"""Kaizenパイプラインのローカルテスト用スクリプト"""
import os
os.environ["SAKURA_SKIP_UPLOAD"] = "false"  # YouTube投稿を有効化

from sakura.pipeline import run_kaizen_pipeline

topic = "Morning Stretch for Beginners"
japanese_script = """おはようございます！今日は初心者向けの朝ストレッチを紹介します。
まず、両腕を上に伸ばして、大きく深呼吸しましょう。
次に、首をゆっくりと左右に回します。
肩を前後にぐるぐると回して、こりをほぐしましょう。
最後に、体を左右にゆっくりと傾けます。
毎朝続けることで、体が軽くなりますよ。
今日も一日、元気に頑張りましょう！"""

if __name__ == "__main__":
    print("=== Kaizenテスト開始 ===")
    result = run_kaizen_pipeline(topic, japanese_script, tags=["fitness", "stretch", "morning"], index=0)
    if result:
        print(f"\n✅ 成功: https://youtube.com/shorts/{result}")
    else:
        print("\n❌ 失敗またはスキップ")
