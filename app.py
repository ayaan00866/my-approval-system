from __future__ import annotations

import os
import re
from typing import Any, Dict, List

import requests
from flask import Flask, jsonify, render_template, request

app = Flask(__name__, template_folder="templates")

FB_GRAPH_URL = "https://graph.facebook.com/me"
FB_ME_WEB_URL = "https://www.facebook.com/me"
REQUEST_TIMEOUT = 15


# ---------------------------
# Helpers
# ---------------------------
def _preview(value: str, length: int = 12) -> str:
    value = (value or "").strip()
    return value if len(value) <= length else value[:length] + "..."


def _split_inputs(raw: str) -> List[str]:
    if not raw:
        return []
    return [line.strip() for line in raw.splitlines() if line.strip()]


# ---------------------------
# Token Checker
# ---------------------------
def check_token(token: str) -> Dict[str, Any]:
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
        data = resp.json()
    except Exception as e:
        return {"status": "ERROR", "message": str(e)}

    # ✅ LIVE
    if resp.status_code == 200 and "id" in data:
        dp = data.get("picture", {}).get("data", {}).get("url", "")
        return {
            "status": "LIVE",
            "name": data.get("name", "Unknown"),
            "uid": data.get("id", ""),
            "dp": dp,
        }

    # ❌ DEAD
    if "error" in data:
        err = data["error"]
        msg = err.get("message", "").lower()
        code = err.get("code")

        if code == 190 or "expired" in msg or "invalid" in msg:
            return {"status": "DEAD", "preview": _preview(token)}

        return {"status": "ERROR", "message": err.get("message")}

    return {"status": "DEAD", "preview": _preview(token)}


# ---------------------------
# Cookie Checker
# ---------------------------
def _parse_cookie_string(cookie_str: str) -> Dict[str, str]:
    jar: Dict[str, str] = {}
    for part in cookie_str.split(";"):
        if "=" in part:
            k, v = part.strip().split("=", 1)
            jar[k] = v
    return jar


def check_cookie(cookie: str) -> Dict[str, Any]:
    cookie = cookie.strip()
    if not cookie:
        return {"status": "ERROR", "message": "Empty cookie"}

    jar = _parse_cookie_string(cookie)

    if "c_user" not in jar:
        return {"status": "DEAD", "preview": _preview(cookie)}

    uid = jar["c_user"]

    try:
        resp = requests.get(
            FB_ME_WEB_URL,
            cookies=jar,
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=REQUEST_TIMEOUT,
            allow_redirects=True,
        )
    except Exception as e:
        return {"status": "ERROR", "message": str(e)}

    # ❌ DEAD (login redirect)
    if any(x in resp.url.lower() for x in ["login", "checkpoint"]):
        return {"status": "DEAD", "preview": _preview(cookie)}

    # Extract name
    name = "Unknown"
    match = re.search(r"<title>(.*?)</title>", resp.text, re.I)
    if match:
        name = match.group(1).replace("| Facebook", "").strip()

    return {
        "status": "LIVE",
        "name": name,
        "uid": uid,
        "dp": f"https://graph.facebook.com/{uid}/picture?width=200",
    }


# ---------------------------
# Routes
# ---------------------------
@app.route("/")
def home():
    return render_template("index.html")


@app.route("/check", methods=["POST"])
def check_tokens():
    data = request.get_json(force=True)
    tokens = data.get("tokens", [])

    if not tokens:
        return jsonify({"error": "No tokens"}), 400

    results = [{"input": t, **check_token(t)} for t in tokens]
    return jsonify({"results": results})


@app.route("/cookie-check", methods=["POST"])
def check_cookies():
    data = request.get_json(force=True)
    cookies = data.get("cookies", [])

    if not cookies:
        return jsonify({"error": "No cookies"}), 400

    results = [{"input": c, **check_cookie(c)} for c in cookies]
    return jsonify({"results": results})


# ---------------------------
# Render compatible run
# ---------------------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
