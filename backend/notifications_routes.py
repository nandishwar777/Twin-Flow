"""Notification & settings API routes."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from fastapi.responses import HTMLResponse

from database import get_db
from models import User
from auth import current_user
from notifications import (
    smtp_configured, sms_configured,
    send_email, send_sms,
    build_daily_reminder_html,
    build_weekly_report_html,
    compute_weekly_stats,
    run_daily_reminders,
    run_weekly_reports,
)
from telegram_bot import send_telegram, telegram_bot_username, tg_configured

router = APIRouter(prefix="/api/notifications", tags=["notifications"])


@router.get("/status")
def status():
    """Returns whether email & SMS are configured so the frontend can show a hint."""
    return {
        "smtp_configured": smtp_configured(),
        "sms_configured": sms_configured(),
        "telegram_configured": tg_configured(),
        "telegram_bot_username": telegram_bot_username(),
    }


# ---------- Test / preview helpers (logged-in user only) ----------

@router.post("/test-email")
def test_email(user: User = Depends(current_user)):
    """Send a test daily-reminder email to the logged-in user's email."""
    html = build_daily_reminder_html(user.username)
    result = send_email(user.email, "TwinFlow — Test Reminder (Email)", html)
    if not result["sent"]:
        raise HTTPException(status_code=400, detail=result["message"])
    return result


@router.post("/test-sms")
def test_sms(user: User = Depends(current_user)):
    """Send a test SMS to the logged-in user's phone."""
    if not user.phone_number:
        raise HTTPException(status_code=400, detail="No phone number on file. Add one in Settings.")
    msg = (
        f"TwinFlow: Hi {user.username}! This is a test SMS. "
        f"You'll receive daily habit reminders here when SMS notifications are on."
    )
    result = send_sms(user.phone_number, msg)
    if not result["sent"]:
        raise HTTPException(status_code=400, detail=result["message"])
    return result


@router.post("/test-telegram")
def test_telegram(user: User = Depends(current_user)):
    """Send a test Telegram message to the logged-in user's linked chat."""
    if not user.telegram_chat_id:
        raise HTTPException(status_code=400, detail="Telegram is not linked on this account.")
    result = send_telegram(
        user.telegram_chat_id,
        f"TwinFlow test message for *{user.username}*.\nDaily reminders can arrive here.",
    )
    if not result["sent"]:
        raise HTTPException(status_code=400, detail=result["message"])
    return result


@router.post("/send-weekly-now")
def send_weekly_now(user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Generate this user's weekly report and email it now."""
    from datetime import datetime
    stats = compute_weekly_stats(db, user)
    html = build_weekly_report_html(user.username, stats)
    result = send_email(user.email, "Your TwinFlow weekly report", html)
    if not result["sent"]:
        raise HTTPException(status_code=400, detail=result["message"])
    user.last_weekly_report_sent = datetime.utcnow()
    db.commit()
    return result


@router.get("/preview/daily", response_class=HTMLResponse)
def preview_daily(user: User = Depends(current_user)):
    return HTMLResponse(build_daily_reminder_html(user.username))


@router.get("/preview/weekly", response_class=HTMLResponse)
def preview_weekly(user: User = Depends(current_user), db: Session = Depends(get_db)):
    stats = compute_weekly_stats(db, user)
    return HTMLResponse(build_weekly_report_html(user.username, stats))


@router.post("/run-daily-job")
def run_daily_job_now(user: User = Depends(current_user)):
    """Manually trigger the daily reminder job for ALL users (demo helper)."""
    return run_daily_reminders()


@router.post("/run-weekly-job")
def run_weekly_job_now(user: User = Depends(current_user)):
    """Manually trigger the weekly report job for ALL users (demo helper)."""
    return run_weekly_reports(force=True)
