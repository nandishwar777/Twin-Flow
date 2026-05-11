"""Telegram connect / webhook routes."""
from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from auth import current_user
from database import get_db
from models import User
from schemas import MessageResponse, TelegramLinkCodeResponse
from telegram_bot import generate_link_code, send_telegram, telegram_bot_username, tg_configured


router = APIRouter(tags=["telegram"])


@router.post("/api/me/telegram/link-code", response_model=TelegramLinkCodeResponse)
def create_link_code(user: User = Depends(current_user), db: Session = Depends(get_db)):
    if not tg_configured():
        return TelegramLinkCodeResponse(
            code="",
            botUsername=None,
            message="Telegram bot is not configured.",
        )

    user.telegram_link_code = generate_link_code()
    db.commit()
    db.refresh(user)
    return TelegramLinkCodeResponse(
        code=user.telegram_link_code,
        botUsername=telegram_bot_username(),
        message="Send /connect <code> to the bot to link Telegram.",
    )


@router.post("/api/me/telegram/disconnect", response_model=MessageResponse)
def disconnect_telegram(user: User = Depends(current_user), db: Session = Depends(get_db)):
    user.telegram_chat_id = None
    user.telegram_link_code = None
    db.commit()
    return MessageResponse(message="Telegram disconnected.")


@router.post("/api/telegram/webhook")
async def telegram_webhook(request: Request, db: Session = Depends(get_db)):
    try:
        payload = await request.json()
    except Exception:
        return {"ok": True}

    try:
        message = payload.get("message") or {}
        chat = message.get("chat") or {}
        text = (message.get("text") or "").strip()
        chat_id = str(chat.get("id") or "")

        if not chat_id:
            return {"ok": True}

        if text.startswith("/connect "):
            code = text.split(None, 1)[1].strip()
            user = db.query(User).filter(User.telegram_link_code == code).first()
            if not user:
                send_telegram(
                    chat_id,
                    "Invalid code. Open TwinFlow Settings, generate a fresh code, then send /connect <code>.",
                    parse_mode=None,
                )
                return {"ok": True}

            db.query(User).filter(User.telegram_chat_id == chat_id, User.id != user.id).update(
                {"telegram_chat_id": None}
            )
            user.telegram_chat_id = chat_id
            user.telegram_link_code = None
            user.notify_telegram = True
            db.commit()
            send_telegram(
                chat_id,
                f"\u2705 Connected as @{user.username}! You'll get daily reminders here.",
                parse_mode=None,
            )
            return {"ok": True}

        if text.startswith("/start"):
            send_telegram(
                chat_id,
                "Welcome to TwinFlow. Open Settings in the app, generate a link code, then send /connect <code> here.",
                parse_mode=None,
            )
            return {"ok": True}

        send_telegram(
            chat_id,
            "Send /connect <code> to link your TwinFlow account.",
            parse_mode=None,
        )
    except Exception as e:
        print(f"[telegram] Webhook handler failed: {e}")

    return {"ok": True}
