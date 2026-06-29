"""
One-time Google OAuth2 setup script.

Run this ONCE from your terminal:
    python setup_google_auth.py

It will open a browser tab, ask you to sign in as sabyasachi@spicmacay.com,
and save a token.json file. The app then uses that token automatically.
You never need to run this again unless you revoke access or delete token.json.

Prerequisites:
1. Go to https://console.cloud.google.com (sign in as sabyasachi@spicmacay.com)
2. Create a project (e.g. "spicmacay-ai-agents")
3. Enable the Google Drive API
4. APIs & Services -> Credentials -> Create Credentials -> OAuth 2.0 Client ID
   - Application type: Desktop App
   - Name: spicmacay-ai-agents
5. Download the JSON file and save it as:
       credentials/oauth_client_secrets.json
6. Run this script: python setup_google_auth.py
"""

import os
import sys

CREDENTIALS_FILE = os.getenv("GOOGLE_OAUTH_CREDENTIALS_FILE", "credentials/oauth_client_secrets.json")
TOKEN_FILE = os.getenv("GOOGLE_TOKEN_FILE", "credentials/token.json")
SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]


def main():
    if not os.path.exists(CREDENTIALS_FILE):
        print(f"\n  ERROR: credentials file not found at: {CREDENTIALS_FILE}")
        print("  Please download your OAuth2 client secrets from Google Cloud Console")
        print("  and save them as: credentials/oauth_client_secrets.json\n")
        sys.exit(1)

    try:
        from google_auth_oauthlib.flow import InstalledAppFlow
        from google.oauth2.credentials import Credentials
        from google.auth.transport.requests import Request
    except ImportError:
        print("\n  ERROR: Google auth libraries not installed.")
        print("  Run: pip install google-auth-oauthlib google-auth\n")
        sys.exit(1)

    os.makedirs(os.path.dirname(TOKEN_FILE), exist_ok=True)

    creds = None
    if os.path.exists(TOKEN_FILE):
        creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            print("Refreshing existing token...")
            creds.refresh(Request())
        else:
            print("Opening browser for Google login...")
            print("Sign in as: sabyasachi@spicmacay.com\n")
            flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_FILE, SCOPES)
            creds = flow.run_local_server(port=0)

        with open(TOKEN_FILE, "w") as fh:
            fh.write(creds.to_json())

    print(f"\n  Success! Token saved to: {TOKEN_FILE}")
    print("  The app will now use your Google Drive account automatically.")
    print("  You don't need to run this script again.\n")

    # Quick verification
    try:
        from googleapiclient.discovery import build
        service = build("drive", "v3", credentials=creds, cache_discovery=False)
        about = service.about().get(fields="user").execute()
        email = about.get("user", {}).get("emailAddress", "unknown")
        print(f"  Connected as: {email}\n")
    except Exception as e:
        print(f"  (Could not verify connection: {e})\n")


if __name__ == "__main__":
    main()
