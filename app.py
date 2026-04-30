"""Token & Cookie Checker Flask Backend.

Provides two endpoints:
  - POST /check         -> validate Facebook access tokens
  - POST /cookie-check  -> validate Facebook cookies

For each input item the API returns one of:
  {"status": "LIVE",  "name": ..., "uid": ..., "dp": ...}
  {"status": "DEAD",  "preview": ...}
  {"status": "ERROR", "message": ...}
"""

from __future__ import annotations

import os
import re
from typing import Any, Dict, List

import requests
from flask import Flask, jsonify, render_template, request

app = Flask(__name__, static_folder="static", template_folder="templates")

FB_GRAPH_URL = "https://graph.facebook.com/me"
FB_ME_WEB_URL = "https://www.facebook.com/me"
REQUEST_TIMEOUT = 15


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _preview(value: str, length: int = 12) -> str:
    """Return a short preview of a token/cookie for DEAD results."""
    value = (value or "").strip()
    if len(value) <= length:
        return value
    return value[:length] + "..."


def _split_inputs(raw: str) -> List[str]:
    """Split a multi-line string into clean non-empty lines."""
    if not raw:
        return []
    return [line.strip() for line in raw.splitlines() if line.strip()]


# --------------------------------------------------------------------------- #
# Token validation
# --------------------------------------------------------------------------- #
def check_token(token: str) -> Dict[str, Any]:
    """Check a single Facebook access token via Graph API."""
    token = token.strip()
    if not token:
        return {"status": "ERROR", "message": "Empty token"}

    try:
        resp = requests.get(
            FB_GRAPH_URL,
            params={
                "fields": "id,name,picture.width(200).height(200)",
                "access_token": token,
            },
            timeout=REQUEST_TIMEOUT,
        )
    except requests.RequestException as exc:
        return {"status": "ERROR", "message": f"Network error: {exc}"}

    try:
        data = resp.json()
    except ValueError:
        return {"status": "ERROR", "message": "Invalid response from Facebook"}

    if resp.status_code == 200 and "id" in data:
        dp = ""
        picture = data.get("picture", {})
        if isinstance(picture, dict):
            dp = picture.get("data", {}).get("url", "")
        return {
            "status": "LIVE",
            "name": data.get("name", "Unknown"),
            "uid": data.get("id", ""),
            "dp": dp,
        }

    # Facebook returns an "error" object for invalid/expired tokens
    if "error" in data:
        err = data["error"]
        msg = err.get("message", "").lower()
        code = err.get("code")
        # 190 = invalid/expired token -> DEAD
        if code == 190 or "expired" in msg or "invalid" in msg or "session" in msg:
            return {"status": "DEAD", "preview": _preview(token)}
        return {"status": "ERROR", "message": err.get("message", "Unknown error")}

    return {"status": "DEAD", "preview": _preview(token)}


# --------------------------------------------------------------------------- #
# Cookie validation
# --------------------------------------------------------------------------- #
def _parse_cookie_string(cookie_str: str) -> Dict[str, str]:
    """Parse a 'k=v; k2=v2' cookie string into a dict."""
    jar: Dict[str, str] = {}
    for part in cookie_str.split(";"):
        part = part.strip()
        if not part or "=" not in part:
            continue
        key, _, value = part.partition("=")
        jar[key.strip()] = value.strip()
    return jar


def check_cookie(cookie: str) -> Dict[str, Any]:
    """Check a single Facebook cookie string by hitting facebook.com/me."""
    cookie = cookie.strip()
    if not cookie:
        return {"status": "ERROR", "message": "Empty cookie"}

    jar = _parse_cookie_string(cookie)
    if "c_user" not in jar:
        return {"status": "DEAD", "preview": _preview(cookie)}

    uid = jar["c_user"]
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/122.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "en-US,en;q=0.9",
    }

    try:
        resp = requests.get(
            FB_ME_WEB_URL,
            cookies=jar,
            headers=headers,
            timeout=REQUEST_TIMEOUT,
            allow_redirects=True,
        )
    except requests.RequestException as exc:
        return {"status": "ERROR", "message": f"Network error: {exc}"}

    final_url = resp.url.lower()
    body = resp.text or ""

    # Detect login / checkpoint redirects -> DEAD
    dead_markers = ("login.php", "/login", "checkpoint", "recover")
    if any(marker in final_url for marker in dead_markers):
        return {"status": "DEAD", "preview": _preview(cookie)}

    # Try to extract display name from page <title>
    name = "Unknown"
    match = re.search(r"<title>(.*?)</title>", body, re.IGNORECASE | re.DOTALL)
    if match:
        title = match.group(1).strip()
        # Titles like "Rahul Sharma | Facebook"
        title = re.sub(r"\s*\|\s*Facebook.*$", "", title, flags=re.IGNORECASE)
        if title and "facebook" not in title.lower() and "log" not in title.lower():
            name = title

    if resp.status_code == 200 and "c_user" in jar:
        dp = f"https://graph.facebook.com/{uid}/picture?width=200&height=200"
        return {"status": "LIVE", "name": name, "uid": uid, "dp": dp}

    return {"status": "DEAD", "preview": _preview(cookie)}


# --------------------------------------------------------------------------- #
# Routes
# --------------------------------------------------------------------------- #
@app.route("/")
def index():
    return render_template("index.html")


@app.route("/check", methods=["POST"])
def route_check_tokens():
    payload = request.get_json(silent=True) or {}
    tokens: List[str] = []

    if "tokens" in payload and isinstance(payload["tokens"], list):
        tokens = [str(t).strip() for t in payload["tokens"] if str(t).strip()]
    elif "token" in payload:
        tokens = [str(payload["token"]).strip()]
    elif "text" in payload:
        tokens = _split_inputs(str(payload["text"]))

    if not tokens:
        return jsonify({"error": "No tokens provided"}), 400

    results = [{"input": t, **check_token(t)} for t in tokens]
    return jsonify({"results": results})


@app.route("/cookie-check", methods=["POST"])
def route_check_cookies():
    payload = request.get_json(silent=True) or {}
    cookies: List[str] = []

    if "cookies" in payload and isinstance(payload["cookies"], list):
        cookies = [str(c).strip() for c in payload["cookies"] if str(c).strip()]
    elif "cookie" in payload:
        cookies = [str(payload["cookie"]).strip()]
    elif "text" in payload:
        cookies = _split_inputs(str(payload["text"]))

    if not cookies:
        return jsonify({"error": "No cookies provided"}), 400

    results = [{"input": c, **check_cookie(c)} for c in cookies]
    return jsonify({"results": results})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    debug = os.environ.get("FLASK_DEBUG", "0") == "1"
    app.run(host="0.0.0.0", port=port, debug=debug)
