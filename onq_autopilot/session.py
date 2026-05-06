"""
onq_autopilot/session.py
─────────────────────────
Handles all authentication for the pipeline.

Strategy (no OAuth registration needed)
────────────────────────────────────────
1. FIRST RUN — opens a REAL Chromium browser window.
   You log in to OnQ with your NetID + password + MFA as normal.
   Once you're on the OnQ home page the browser closes and we save
   all cookies to SESSION_FILE (.session_state.json, gitignored).

2. SUBSEQUENT RUNS — headless.
   We load those cookies, hit /whoami to verify they're still valid,
   and hand back a ready-to-use requests.Session.
   No browser opens at all.

3. SESSION EXPIRY — if /whoami returns non-200, we re-open the browser
   and repeat step 1. The persistent .browser_profile/ directory means
   Microsoft's "remember this device" cookie is still there, so MFA is
   often skipped automatically.

Why this works
──────────────
D2L Brightspace accepts the exact same browser session cookies for its
REST API calls (the Valence API) that it sets when you log in via the
web UI. We just reuse them in requests.Session headers.
"""

import json
import os
import time
from pathlib import Path
from functools import lru_cache

import requests
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
from dotenv import load_dotenv

load_dotenv()

BASE_URL          = os.getenv("ONQ_BASE_URL", "https://onq.queensu.ca")
SESSION_FILE      = Path(os.getenv("SESSION_FILE", ".session_state.json"))
API_VERSION       = "1.82"
_BROWSER_DATA_DIR = Path(".browser_profile")

# Module-level cache: one requests.Session per process run
# (avoids hitting /whoami on every single API call)
_cached_session: requests.Session | None = None


# ──────────────────────────────────────────────────────────────────────────────
# Cookie persistence
# ──────────────────────────────────────────────────────────────────────────────

def _load_cookies() -> list[dict] | None:
    if not SESSION_FILE.exists():
        return None
    try:
        return json.loads(SESSION_FILE.read_text()).get("cookies", [])
    except Exception:
        return None


def _save_cookies(cookies: list[dict]):
    SESSION_FILE.write_text(json.dumps({"cookies": cookies}, indent=2))
    print(f"[SESSION] Cookies saved → {SESSION_FILE}")


# ──────────────────────────────────────────────────────────────────────────────
# Session validation
# ──────────────────────────────────────────────────────────────────────────────

def _make_session_from_cookies(cookies: list[dict]) -> requests.Session:
    s = requests.Session()
    for c in cookies:
        s.cookies.set(c["name"], c["value"], domain=c.get("domain", ""))
    s.headers.update({
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept":          "application/json, text/plain, */*",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer":         f"{BASE_URL}/d2l/home",
    })
    return s


def _session_alive(s: requests.Session) -> bool:
    """Hit /whoami — returns True if session cookies are still valid."""
    try:
        resp = s.get(
            f"{BASE_URL}/d2l/api/lp/{API_VERSION}/users/whoami",
            timeout=10,
            allow_redirects=False,
        )
        return resp.status_code == 200
    except Exception:
        return False


# ──────────────────────────────────────────────────────────────────────────────
# Browser login via Playwright
# ──────────────────────────────────────────────────────────────────────────────

def _browser_login() -> list[dict]:
    """
    Opens a real Chromium window for you to log in through Queen's SSO.
    Blocks until you land on the OnQ home page (up to 5 minutes).
    Saves and returns the captured cookies.
    """
    print("\n" + "=" * 60)
    print("  ONQ AUTOPILOT — BROWSER LOGIN REQUIRED")
    print("=" * 60)
    print("  A Chromium browser will open now.")
    print("  1. Log in with your NetID and password")
    print("  2. Complete MFA as prompted")
    print("  3. Wait for the OnQ home page to load")
    print("  The browser will close automatically.")
    print("=" * 60 + "\n")

    _BROWSER_DATA_DIR.mkdir(exist_ok=True)

    with sync_playwright() as pw:
        context = pw.chromium.launch_persistent_context(
            user_data_dir=str(_BROWSER_DATA_DIR),
            headless=False,
            args=["--start-maximized"],
            no_viewport=True,
        )
        page = context.new_page()
        page.goto(f"{BASE_URL}/d2l/home", wait_until="domcontentloaded")
        print("[SESSION] Waiting for OnQ home page after login...")

        try:
            page.wait_for_url(
                "**/d2l/home**",
                timeout=300_000,  # 5 min
            )
        except PWTimeout:
            context.close()
            raise TimeoutError("Login timed out after 5 minutes.")

        time.sleep(2)  # Let session cookies settle
        cookies = context.cookies()
        context.close()

    print(f"[SESSION] Captured {len(cookies)} cookies. Login successful.")
    return cookies


# ──────────────────────────────────────────────────────────────────────────────
# Public API — everything else calls this
# ──────────────────────────────────────────────────────────────────────────────

def get_requests_session() -> requests.Session:
    """
    Returns a valid requests.Session loaded with OnQ cookies.

    Cached within the process — only re-validates once per run.
    Re-opens the browser if the session has expired.
    """
    global _cached_session

    # Return cached session if we already validated this run
    if _cached_session is not None:
        return _cached_session

    cookies = _load_cookies()

    if cookies:
        s = _make_session_from_cookies(cookies)
        if _session_alive(s):
            print("[SESSION] Loaded existing session ✓")
            _cached_session = s
            return _cached_session
        else:
            print("[SESSION] Saved session expired — re-logging in...")
    else:
        print("[SESSION] No session found — starting first-time login...")

    # Need a fresh login
    cookies = _browser_login()
    _save_cookies(cookies)
    s = _make_session_from_cookies(cookies)
    _cached_session = s
    return _cached_session


def invalidate_session():
    """Call this to force a fresh login on the next get_requests_session()."""
    global _cached_session
    _cached_session = None
    if SESSION_FILE.exists():
        SESSION_FILE.unlink()
    print("[SESSION] Session invalidated — next call will re-login.")
