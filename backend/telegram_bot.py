"""Telegram bot helpers."""
import os
import secrets
from pathlib import Path

from dotenv import load_dotenv
import requests


load_dotenv(Path(__file__).resolve().parent / ".env")


def _token() -> str:
    return os.getenv("TELEGRAM_BOT_TOKEN", "").strip()


def tg_configured() -> bool:
    return bool(_token())


def telegram_bot_username() -> str | None:
    if not tg_configured():
        return None
    try:
        resp = requests.get(
            f"https://api.telegram.org/bot{_token()}/getMe",
            timeout=20,
        )
        data = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}
        if resp.status_code == 200 and data.get("ok") and data.get("result", {}).get("username"):
            return data["result"]["username"]
    except Exception as e:
        print(f"[telegram] getMe failed: {e}")
    return None


def send_telegram(chat_id: str, text: str, parse_mode: str = "Markdown") -> dict:
    """Send a Telegram message. Returns {sent: bool, message: str}."""
    if not tg_configured():
        print(f"[telegram] (Bot not configured) Would send TELEGRAM to {chat_id}: {text[:80]}")
        return {"sent": False, "message": "Telegram bot not configured."}
    if not chat_id:
        return {"sent": False, "message": "Telegram chat_id missing."}

    payload = {
        "chat_id": chat_id,
        "text": text,
    }
    if parse_mode:
        payload["parse_mode"] = parse_mode

    try:
        resp = requests.post(
            f"https://api.telegram.org/bot{_token()}/sendMessage",
            json=payload,
            timeout=20,
        )
        data = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}
        if resp.status_code == 200 and data.get("ok") is True:
            print(f"[telegram] TELEGRAM sent to {chat_id}: {text[:80]}")
            return {"sent": True, "message": f"Telegram sent to {chat_id}"}
        err = data.get("description") or resp.text[:200] or f"HTTP {resp.status_code}"
        print(f"[telegram] TELEGRAM FAILED to {chat_id}: {err}")
        return {"sent": False, "message": f"Telegram failed: {err}"}
    except Exception as e:
        print(f"[telegram] TELEGRAM EXCEPTION to {chat_id}: {e}")
        return {"sent": False, "message": f"Telegram exception: {e}"}


def generate_link_code() -> str:
    return f"{secrets.randbelow(1_000_000):06d}"
