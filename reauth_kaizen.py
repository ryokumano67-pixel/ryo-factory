#!/usr/bin/env python3
"""Kaizenトークンをforce-ssl込みで再認証"""
import sys
from pathlib import Path
from google_auth_oauthlib.flow import InstalledAppFlow

BASE_DIR = Path(__file__).parent
TOKEN_FILE = BASE_DIR / "sakura" / "kaizen_youtube_token.json"
CLIENT_SECRETS = BASE_DIR / "client_secrets.json"

SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.force-ssl",
]

flow = InstalledAppFlow.from_client_secrets_file(str(CLIENT_SECRETS), SCOPES)
creds = flow.run_local_server(port=0)
TOKEN_FILE.write_text(creds.to_json())
print(f"✅ 再認証完了: {TOKEN_FILE}")
