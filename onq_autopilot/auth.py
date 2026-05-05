"""
onq_autopilot/auth.py
─────────────────────
Handles D2L Brightspace OAuth 2.0 Authorization Code Grant flow.

Flow:
  1. Open browser → user logs in at OnQ and grants consent
  2. Redirect URI catches the ?code= param
  3. Exchange code for access_token + refresh_token
  4. Persist tokens to TOKEN_FILE
  5. Auto-refresh when access_token expires
"""

import json
import os
import time
import threading
import webbrowser
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlencode, urlparse, parse_qs

import requests
from dotenv import load_dotenv

load_dotenv()

BASE_URL       = os.getenv("ONQ_BASE_URL", "https://onq.queensu.ca")
CLIENT_ID      = os.getenv("D2L_CLIENT_ID")
CLIENT_SECRET  = os.getenv("D2L_CLIENT_SECRET")
REDIRECT_URI   = os.getenv("D2L_REDIRECT_URI", "http://localhost:8080/callback")
TOKEN_FILE     = os.getenv("TOKEN_FILE", ".tokens.json")

AUTH_ENDPOINT  = "https://auth.brightspace.com/oauth2/auth"
TOKEN_ENDPOINT = "https://auth.brightspace.com/core/connect/token"

SCOPES = " ".join([
    "core:*:*",
    "enrollment:orgunit:read",
    "dropbox:folders:read",
    "dropbox:folders:write",
    "dropbox:submission:read",
    "dropbox:submission:write",
    "content:modules:read",
    "content:topics:read",
])

# ──────────────────────────────────────────────────────────────────────────────
# Token persistence
# ──────────────────────────────────────────────────────────────────────────────

def save_tokens(token_data: dict):
    with open(TOKEN_FILE, "w") as f:
        json.dump(token_data, f, indent=2)


def load_tokens() -> dict | None:
    if not os.path.exists(TOKEN_FILE):
        return None
    with open(TOKEN_FILE) as f:
        return json.load(f)


def tokens_valid(tokens: dict) -> bool:
    """Return True if the access token still has > 60s of life."""
    expires_at = tokens.get("expires_at", 0)
    return time.time() < expires_at - 60


# ──────────────────────────────────────────────────────────────────────────────
# OAuth 2.0 Authorization Code Grant
# ──────────────────────────────────────────────────────────────────────────────

_auth_code: str | None = None  # shared between server thread and main thread


class _CallbackHandler(BaseHTTPRequestHandler):
    """Minimal HTTP handler that captures the ?code= query param."""

    def do_GET(self):
        global _auth_code
        params = parse_qs(urlparse(self.path).query)
        _auth_code = params.get("code", [None])[0]
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"<h1>Auth complete! You can close this tab.</h1>")

    def log_message(self, *args):
        pass  # silence server logs


def _start_callback_server(port: int = 8080) -> HTTPServer:
    server = HTTPServer(("localhost", port), _CallbackHandler)
    thread = threading.Thread(target=server.handle_request, daemon=True)
    thread.start()
    return server


def authorize() -> dict:
    """
    Run the full Authorization Code Grant flow.
    Opens the browser and blocks until the user authenticates.
    Returns the token data dict.
    """
    port = int(urlparse(REDIRECT_URI).port or 8080)
    _start_callback_server(port)

    params = {
        "response_type": "code",
        "client_id": CLIENT_ID,
        "redirect_uri": REDIRECT_URI,
        "scope": SCOPES,
    }
    url = f"{AUTH_ENDPOINT}?{urlencode(params)}"
    print(f"\n[AUTH] Opening browser for login:\n  {url}\n")
    webbrowser.open(url)

    # Wait for redirect
    timeout = 120
    waited = 0
    while _auth_code is None and waited < timeout:
        time.sleep(1)
        waited += 1

    if _auth_code is None:
        raise TimeoutError("OAuth login timed out after 120 seconds.")

    return _exchange_code(_auth_code)


def _exchange_code(code: str) -> dict:
    resp = requests.post(TOKEN_ENDPOINT, data={
        "grant_type":    "authorization_code",
        "code":          code,
        "redirect_uri":  REDIRECT_URI,
        "client_id":     CLIENT_ID,
        "client_secret": CLIENT_SECRET,
    })
    resp.raise_for_status()
    data = resp.json()
    data["expires_at"] = time.time() + data.get("expires_in", 3600)
    save_tokens(data)
    print("[AUTH] Tokens obtained and saved.")
    return data


def refresh_tokens(tokens: dict) -> dict:
    resp = requests.post(TOKEN_ENDPOINT, data={
        "grant_type":    "refresh_token",
        "refresh_token": tokens["refresh_token"],
        "client_id":     CLIENT_ID,
        "client_secret": CLIENT_SECRET,
    })
    resp.raise_for_status()
    data = resp.json()
    data["expires_at"] = time.time() + data.get("expires_in", 3600)
    save_tokens(data)
    print("[AUTH] Tokens refreshed.")
    return data


def get_valid_tokens() -> dict:
    """
    Load tokens from disk, refresh if needed, or trigger full auth flow.
    This is the single entry-point every other module should call.
    """
    tokens = load_tokens()
    if tokens is None:
        return authorize()
    if tokens_valid(tokens):
        return tokens
    if "refresh_token" in tokens:
        try:
            return refresh_tokens(tokens)
        except Exception as e:
            print(f"[AUTH] Refresh failed ({e}), re-authorizing...")
    return authorize()
