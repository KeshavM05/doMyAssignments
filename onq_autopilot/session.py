"""
onq_autopilot/session.py
─────────────────────────
Replaces auth.py entirely.

Strategy
────────
1. FIRST RUN (headful):
   • Opens a real Chromium browser window
   • Navigates to OnQ → redirects to Queen's Microsoft SSO
   • YOU log in manually (NetID + password + MFA)
   • After landing back on OnQ, we save the full browser state
     (cookies + localStorage) to SESSION_FILE

2. SUBSEQUENT RUNS (headless):
   • Restore browser state from SESSION_FILE
   • Hit /d2l/api/lp/.../users/whoami to verify session is live
   • If 401/expired → fall back to headful login again

3. get_requests_session()
   • Returns a requests.Session pre-loaded with the browser cookies
   • All d2l_client API calls use this session — no OAuth needed

Why this works
──────────────
D2L Brightspace accepts its own browser session cookies (d2lSessionVal,
d2lSecurityToken, etc.) for REST API calls. These are the exact same
cookies your browser sends when you click around OnQ manually.
"""

import json
import os
import time
from pathlib import Path

import requests
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
from dotenv import load_dotenv

load_dotenv()

BASE_URL      = os.getenv("ONQ_BASE_URL", "https://onq.queensu.ca")
SESSION_FILE  = Path(os.getenv("SESSION_FILE", ".session_state.json"))
API_VERSION   = "1.82"

# Chromium user-data dir so Playwright remembers your profile between runs
_BROWSER_DATA_DIR = Path(".browser_profile")

# ──────────────────────────────────────────────────────────────────────────────
# Session validation
# ──────────────────────────────────────────────────────────────────────────────

def _session_is_valid(cookies: list[dict]) -> bool:
    """
    Quick check: load cookies into a requests.Session and hit /whoami.
    Returns True if the server responds 200 (session still alive).
    """
    s = requests.Session()
    for c in cookies:
        s.cookies.set(c["name"], c["value"], domain=c.get("domain", ""))
    try:
        resp = s.get(
            f"{BASE_URL}/d2l/api/lp/{API_VERSION}/users/whoami",
            timeout=10,
            allow_redirects=False,
        )
        return resp.status_code == 200
    except Exception:
        return False


def _load_state() -> list[dict] | None:
    """Load cookies from SESSION_FILE. Returns None if missing."""
    if not SESSION_FILE.exists():
        return None
    data = json.loads(SESSION_FILE.read_text())
    return data.get("cookies", [])


def _save_state(cookies: list[dict]):
    """Persist cookies to SESSION_FILE (gitignored)."""
    SESSION_FILE.write_text(json.dumps({"cookies": cookies}, indent=2))
    print(f"[SESSION] State saved → {SESSION_FILE}")


# ──────────────────────────────────────────────────────────────────────────────
# Browser login (Playwright)
# ──────────────────────────────────────────────────────────────────────────────

def _browser_login() -> list[dict]:
    """
    Open a VISIBLE Chromium window, navigate to OnQ, and wait for the
    user to complete SSO + MFA manually.

    Once the browser lands back on onq.queensu.ca/d2l/home, we capture
    all cookies and return them.

    The browser profile is persisted in .browser_profile/ so extensions,
    saved passwords, and cookies survive between runs (useful if OnQ sets
    a long-lived remember-me cookie).
    """
    print("\n" + "="*60)
    print("  ONQ AUTOPILOT — BROWSER LOGIN REQUIRED")
    print("="*60)
    print("  A browser window will open.")
    print("  Please log in with your NetID and complete any MFA.")
    print("  The window will close automatically once you're in.")
    print("="*60 + "\n")

    _BROWSER_DATA_DIR.mkdir(exist_ok=True)

    with sync_playwright() as pw:
        # Use a persistent context so the profile is saved across runs
        context = pw.chromium.launch_persistent_context(
            user_data_dir=str(_BROWSER_DATA_DIR),
            headless=False,
            args=["--start-maximized"],
            no_viewport=True,
        )
        page = context.new_page()

        # Navigate to OnQ — SSO redirect happens automatically
        page.goto(f"{BASE_URL}/d2l/home", wait_until="domcontentloaded")

        print("[SESSION] Waiting for you to finish logging in...")

        # Wait until we're back on the OnQ home page
        # (i.e., the URL contains onq.queensu.ca and the login is done)
        try:
            page.wait_for_url(
                f"**onq.queensu.ca/d2l/home**",
                timeout=300_000,  # 5 minutes — plenty of time for MFA
            )
        except PWTimeout:
            raise TimeoutError(
                "Login timed out after 5 minutes. "
                "Please try again and complete login faster."
            )

        # Extra pause to let all cookies settle
        time.sleep(2)

        cookies = context.cookies()
        context.close()

    print(f"[SESSION] Login successful — captured {len(cookies)} cookies.")
    return cookies


# ──────────────────────────────────────────────────────────────────────────────
# Public API
# ──────────────────────────────────────────────────────────────────────────────

def ensure_session() -> list[dict]:
    """
    Returns a valid list of browser cookies, triggering a browser login
    if the saved session is missing or expired.

    This is the single entry-point used by everything else.
    """
    cookies = _load_state()

    if cookies and _session_is_valid(cookies):
        print("[SESSION] Loaded existing session ✓")
        return cookies

    if cookies:
        print("[SESSION] Saved session has expired — re-logging in...")
    else:
        print("[SESSION] No saved session found — starting fresh login...")

    cookies = _browser_login()
    _save_state(cookies)
    return cookies


def get_requests_session() -> requests.Session:
    """
    Returns a requests.Session pre-loaded with valid OnQ cookies.
    Use this everywhere instead of raw requests.get/post.
    """
    cookies = ensure_session()
    s = requests.Session()
    for c in cookies:
        s.cookies.set(c["name"], c["value"], domain=c.get("domain", ""))
    # Mimic a real browser to avoid bot detection
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
