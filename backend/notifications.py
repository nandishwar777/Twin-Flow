"""
Notifications module — Email (Gmail SMTP) AND SMS (Fast2SMS).

What it does:
  • Sends email via configured Gmail SMTP (App Password).
  • Sends SMS via Fast2SMS (https://www.fast2sms.com/) — Indian SMS gateway.
  • Daily reminders go via BOTH email + SMS for every user who opted in.
  • Weekly reports go via email only (SMS too short for charts).
  • OTP codes for password reset go via the user's chosen channel.

If SMTP or Fast2SMS isn't configured, sending becomes a no-op that logs to
console — so the app still runs cleanly for demos.
"""
import os
import smtplib
from datetime import date, timedelta, datetime
from email.message import EmailMessage
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
import requests
from sqlalchemy import func
from sqlalchemy.orm import Session

from database import SessionLocal
from models import User, ProductivityEntry
from telegram_bot import send_telegram


load_dotenv(Path(__file__).resolve().parent / ".env")


# ============================================================
#  EMAIL (SMTP)
# ============================================================

def _smtp_config():
    raw_password = os.getenv("SMTP_PASSWORD", "")
    return {
        "host": os.getenv("SMTP_HOST", "").strip(),
        "port": int(os.getenv("SMTP_PORT", "587")),
        "user": os.getenv("SMTP_USER", "").strip(),
        "password": "".join(raw_password.split()),
        "from_addr": os.getenv("SMTP_FROM", os.getenv("SMTP_USER", "twinflow@localhost")).strip(),
        "use_tls": os.getenv("SMTP_TLS", "true").lower() in ("1", "true", "yes"),
    }


def smtp_configured() -> bool:
    cfg = _smtp_config()
    return bool(cfg["host"] and cfg["user"] and cfg["password"])


def send_email(to_addr: str, subject: str, html_body: str, text_body: Optional[str] = None) -> dict:
    """Send an email. Returns {sent: bool, message: str}."""
    cfg = _smtp_config()
    if not smtp_configured():
        print(f"[notifications] (SMTP not configured) Would send EMAIL to {to_addr}: {subject}")
        return {"sent": False, "message": "SMTP not configured."}

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = cfg["from_addr"]
    msg["To"] = to_addr
    msg.set_content(text_body or "Please view this email in an HTML-capable client.")
    msg.add_alternative(html_body, subtype="html")

    try:
        with smtplib.SMTP(cfg["host"], cfg["port"], timeout=20) as server:
            server.ehlo()
            if cfg["use_tls"]:
                server.starttls()
                server.ehlo()
            server.login(cfg["user"], cfg["password"])
            server.send_message(msg)
        print(f"[notifications] EMAIL sent to {to_addr}: {subject}")
        return {"sent": True, "message": f"Email sent to {to_addr}"}
    except Exception as e:
        print(f"[notifications] EMAIL FAILED to {to_addr}: {e}")
        return {"sent": False, "message": f"Send failed: {e}"}


# ============================================================
#  SMS (Fast2SMS)
# ============================================================

FAST2SMS_URL = "https://www.fast2sms.com/dev/bulkV2"


def _sms_config():
    return {
        "api_key": os.getenv("FAST2SMS_API_KEY", ""),
        "sender_id": os.getenv("FAST2SMS_SENDER_ID", "TWNFLW"),
        "route": os.getenv("FAST2SMS_ROUTE", "q"),  # 'q' = quick transactional
    }


def sms_configured() -> bool:
    return bool(_sms_config()["api_key"])


def send_sms(phone_number: str, message: str) -> dict:
    """Send an SMS via Fast2SMS. phone_number must be 10-digit Indian mobile."""
    cfg = _sms_config()
    if not sms_configured():
        print(f"[notifications] (Fast2SMS not configured) Would send SMS to {phone_number}: {message[:60]}")
        return {"sent": False, "message": "Fast2SMS not configured."}

    if not phone_number or len(phone_number) != 10:
        return {"sent": False, "message": f"Invalid phone number: {phone_number}"}

    try:
        resp = requests.post(
            FAST2SMS_URL,
            headers={"authorization": cfg["api_key"]},
            data={
                "route": cfg["route"],
                "message": message,
                "language": "english",
                "flash": 0,
                "numbers": phone_number,
            },
            timeout=20,
        )
        data = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}
        if resp.status_code == 200 and data.get("return") is True:
            print(f"[notifications] SMS sent to {phone_number}: {message[:60]}")
            return {"sent": True, "message": f"SMS sent to {phone_number}"}
        err = data.get("message") or resp.text[:200] or f"HTTP {resp.status_code}"
        print(f"[notifications] SMS FAILED to {phone_number}: {err}")
        return {"sent": False, "message": f"SMS failed: {err}"}
    except Exception as e:
        print(f"[notifications] SMS EXCEPTION to {phone_number}: {e}")
        return {"sent": False, "message": f"SMS exception: {e}"}


# ============================================================
#  EMAIL HTML BUILDERS
# ============================================================

def build_daily_reminder_html(username: str) -> str:
    today = date.today().strftime("%A, %B %d")
    app_url = os.getenv("APP_URL", "http://localhost:8000")
    return f"""
    <html><body style="font-family:Arial,sans-serif;background:#f7f9fc;padding:24px;color:#0f172a;">
      <div style="max-width:520px;margin:0 auto;background:#fff;border-radius:10px;padding:32px;box-shadow:0 4px 20px rgba(0,0,0,0.06);">
        <h2 style="color:#3366ff;margin:0 0 8px;">TwinFlow — Daily Reminder</h2>
        <p style="color:#64748b;margin:0 0 20px;">{today}</p>
        <p>Hi <strong>{username}</strong>,</p>
        <p>You haven't logged your habits today yet. Just 30 seconds to record your sleep, focus,
        breaks, and tasks — and your AI twin will refine your schedule.</p>
        <p style="margin-top:24px;">
          <a href="{app_url}/log.html"
             style="background:#3366ff;color:#fff;padding:12px 22px;border-radius:8px;text-decoration:none;font-weight:500;">
            Log Today's Habits
          </a>
        </p>
        <p style="color:#94a3b8;font-size:12px;margin-top:32px;">
          You can disable these reminders anytime in Settings.
        </p>
      </div>
    </body></html>
    """


def build_weekly_report_html(username: str, stats: dict) -> str:
    app_url = os.getenv("APP_URL", "http://localhost:8000")
    rows = "".join(
        f"<tr><td style='padding:8px;border-bottom:1px solid #e2e8f0;'>{r['date']}</td>"
        f"<td style='padding:8px;border-bottom:1px solid #e2e8f0;text-align:right;'>{r['sleep']:.1f}h</td>"
        f"<td style='padding:8px;border-bottom:1px solid #e2e8f0;text-align:right;'>{r['focus']}/10</td>"
        f"<td style='padding:8px;border-bottom:1px solid #e2e8f0;text-align:right;'>{r['energy']:.1f}/10</td>"
        f"<td style='padding:8px;border-bottom:1px solid #e2e8f0;text-align:right;'>{r['score']:.0f}</td></tr>"
        for r in stats["daily"]
    )
    return f"""
    <html><body style="font-family:Arial,sans-serif;background:#f7f9fc;padding:24px;color:#0f172a;">
      <div style="max-width:640px;margin:0 auto;background:#fff;border-radius:10px;padding:32px;box-shadow:0 4px 20px rgba(0,0,0,0.06);">
        <h2 style="color:#3366ff;margin:0 0 4px;">Your Weekly TwinFlow Report</h2>
        <p style="color:#64748b;margin:0 0 24px;">Hi {username}, here's how your past 7 days looked.</p>

        <div style="display:flex;gap:12px;flex-wrap:wrap;margin-bottom:24px;">
          <div style="flex:1;min-width:140px;background:#f0f3f9;padding:14px;border-radius:8px;">
            <div style="font-size:11px;color:#64748b;text-transform:uppercase;">Avg Productivity</div>
            <div style="font-size:24px;font-weight:700;">{stats['avg_score']:.0f}/100</div>
          </div>
          <div style="flex:1;min-width:140px;background:#f0f3f9;padding:14px;border-radius:8px;">
            <div style="font-size:11px;color:#64748b;text-transform:uppercase;">Avg Sleep</div>
            <div style="font-size:24px;font-weight:700;">{stats['avg_sleep']:.1f}h</div>
          </div>
          <div style="flex:1;min-width:140px;background:#f0f3f9;padding:14px;border-radius:8px;">
            <div style="font-size:11px;color:#64748b;text-transform:uppercase;">Avg Energy</div>
            <div style="font-size:24px;font-weight:700;">{stats['avg_energy']:.1f}/10</div>
          </div>
          <div style="flex:1;min-width:140px;background:#f0f3f9;padding:14px;border-radius:8px;">
            <div style="font-size:11px;color:#64748b;text-transform:uppercase;">Days Logged</div>
            <div style="font-size:24px;font-weight:700;">{stats['days_logged']}/7</div>
          </div>
        </div>

        <h3 style="margin:0 0 8px;">Daily breakdown</h3>
        <table style="width:100%;border-collapse:collapse;font-size:14px;">
          <thead>
            <tr style="color:#64748b;font-size:12px;text-transform:uppercase;">
              <th style="text-align:left;padding:8px;border-bottom:2px solid #e2e8f0;">Date</th>
              <th style="text-align:right;padding:8px;border-bottom:2px solid #e2e8f0;">Sleep</th>
              <th style="text-align:right;padding:8px;border-bottom:2px solid #e2e8f0;">Focus</th>
              <th style="text-align:right;padding:8px;border-bottom:2px solid #e2e8f0;">Energy</th>
              <th style="text-align:right;padding:8px;border-bottom:2px solid #e2e8f0;">Score</th>
            </tr>
          </thead>
          <tbody>{rows or '<tr><td colspan="5" style="padding:16px;color:#94a3b8;text-align:center;">No entries logged this week.</td></tr>'}</tbody>
        </table>

        <h3 style="margin:24px 0 8px;">AI Insight</h3>
        <p style="color:#0f172a;background:#f0f3f9;padding:12px;border-left:3px solid #3366ff;border-radius:4px;">
          {stats['insight']}
        </p>

        <p style="margin-top:24px;">
          <a href="{app_url}/dashboard.html"
             style="background:#3366ff;color:#fff;padding:12px 22px;border-radius:8px;text-decoration:none;font-weight:500;">
            Open Dashboard
          </a>
        </p>
      </div>
    </body></html>
    """


def build_otp_email_html(username: str, code: str, minutes: int) -> str:
    return f"""
    <html><body style="font-family:Arial,sans-serif;background:#f7f9fc;padding:24px;color:#0f172a;">
      <div style="max-width:480px;margin:0 auto;background:#fff;border-radius:10px;padding:32px;box-shadow:0 4px 20px rgba(0,0,0,0.06);">
        <h2 style="color:#3366ff;margin:0 0 8px;">TwinFlow — Password Reset Code</h2>
        <p>Hi <strong>{username}</strong>,</p>
        <p>Use this verification code to reset your password:</p>
        <div style="font-size:36px;font-weight:700;letter-spacing:6px;text-align:center;
                    background:#f0f3f9;padding:18px;border-radius:8px;color:#3366ff;margin:18px 0;">
          {code}
        </div>
        <p style="color:#64748b;font-size:14px;">This code expires in {minutes} minutes.
        If you didn't request a reset, ignore this email — your password is unchanged.</p>
      </div>
    </body></html>
    """


def build_daily_reminder_telegram(username: str) -> str:
    app_url = os.getenv("APP_URL", "http://localhost:8000")
    return (
        f"TwinFlow daily reminder for *{username}*\n\n"
        "You have not logged today's habits yet. "
        f"Open {app_url}/log.html and record your sleep, focus, breaks, and tasks."
    )


def build_weekly_report_telegram(username: str, stats: dict) -> str:
    app_url = os.getenv("APP_URL", "http://localhost:8000")
    return (
        f"Weekly TwinFlow report for *{username}*\n"
        f"Average productivity: *{stats['avg_score']:.0f}/100*\n"
        f"Average sleep: *{stats['avg_sleep']:.1f}h*\n"
        f"Average energy: *{stats['avg_energy']:.1f}/10*\n"
        f"Days logged: *{stats['days_logged']}/7*\n\n"
        f"{stats['insight']}\n\n"
        f"Open dashboard: {app_url}/dashboard.html"
    )


# ============================================================
#  WEEKLY STATS COMPUTATION
# ============================================================

def compute_weekly_stats(db: Session, user: User) -> dict:
    end = date.today()
    start = end - timedelta(days=6)
    entries = (
        db.query(ProductivityEntry)
        .filter(ProductivityEntry.user_id == user.id)
        .filter(ProductivityEntry.date >= start)
        .filter(ProductivityEntry.date <= end)
        .order_by(ProductivityEntry.date.asc())
        .all()
    )

    daily = [
        {
            "date": e.date.strftime("%a %b %d"),
            "sleep": e.sleep_hours,
            "focus": e.focus_level,
            "energy": e.predicted_energy_level,
            "score": e.productivity_score,
        }
        for e in entries
    ]

    if entries:
        avg_score = sum(e.productivity_score for e in entries) / len(entries)
        avg_sleep = sum(e.sleep_hours for e in entries) / len(entries)
        avg_energy = sum(e.predicted_energy_level for e in entries) / len(entries)
        best = max(entries, key=lambda e: e.productivity_score)
        insight = (
            f"Your most productive day was {best.date.strftime('%A')} "
            f"with a score of {best.productivity_score:.0f}/100. "
            f"You averaged {avg_sleep:.1f} hours of sleep — "
            f"{'great consistency!' if 6.5 <= avg_sleep <= 8.5 else 'try targeting 7-8 hours for steadier energy.'}"
        )
    else:
        avg_score = avg_sleep = avg_energy = 0.0
        insight = "No habits logged this week. Start logging today to unlock personalized AI insights!"

    return {
        "daily": daily,
        "avg_score": avg_score,
        "avg_sleep": avg_sleep,
        "avg_energy": avg_energy,
        "days_logged": len(entries),
        "insight": insight,
    }


# ============================================================
#  JOB RUNNERS  (called by APScheduler)
# ============================================================

def run_daily_reminders() -> dict:
    """For every user who hasn't logged today, send EMAIL + SMS based on their preferences."""
    db = SessionLocal()
    emails_sent = 0
    sms_sent = 0
    telegram_sent = 0
    skipped_logged = 0
    skipped_optedout = 0
    try:
        today = date.today()
        users = db.query(User).all()
        for u in users:
            already = (
                db.query(func.count(ProductivityEntry.id))
                .filter(ProductivityEntry.user_id == u.id)
                .filter(ProductivityEntry.date == today)
                .scalar()
            )
            if already:
                skipped_logged += 1
                continue

            # Email channel
            if u.notify_email:
                html = build_daily_reminder_html(u.username)
                if send_email(u.email, "TwinFlow — Don't forget today's habits", html)["sent"]:
                    emails_sent += 1

            # SMS channel
            if u.notify_sms and u.phone_number:
                msg = (
                    f"TwinFlow: Hi {u.username}! Don't forget to log your habits today. "
                    f"Just 30 seconds at {os.getenv('APP_URL','localhost:8000')}/log.html"
                )
                if send_sms(u.phone_number, msg)["sent"]:
                    sms_sent += 1

            # Telegram channel
            if u.notify_telegram and u.telegram_chat_id:
                msg = build_daily_reminder_telegram(u.username)
                if send_telegram(u.telegram_chat_id, msg)["sent"]:
                    telegram_sent += 1

            if not u.notify_email and not (u.notify_sms and u.phone_number) and not (u.notify_telegram and u.telegram_chat_id):
                skipped_optedout += 1

        return {
            "emails_sent": emails_sent,
            "sms_sent": sms_sent,
            "telegram_sent": telegram_sent,
            "skipped_already_logged": skipped_logged,
            "skipped_opted_out": skipped_optedout,
            "total_users": len(users),
        }
    finally:
        db.close()


def run_weekly_reports(force: bool = False) -> dict:
    """
    Email weekly report to every user.
    If `force=False`, skips users who received one in the last 6 days
    (so the startup catch-up doesn't double-send).
    """
    db = SessionLocal()
    sent = 0
    skipped = 0
    telegram_sent = 0
    try:
        users = db.query(User).all()
        now = datetime.utcnow()
        for u in users:
            if not u.notify_email and not (u.notify_telegram and u.telegram_chat_id):
                skipped += 1
                continue
            if not force and u.last_weekly_report_sent:
                if (now - u.last_weekly_report_sent).days < 6:
                    skipped += 1
                    continue
            stats = compute_weekly_stats(db, u)
            delivered = False
            if u.notify_email:
                html = build_weekly_report_html(u.username, stats)
                res = send_email(u.email, "Your TwinFlow weekly report", html)
                if res["sent"]:
                    sent += 1
                    delivered = True
            if u.notify_telegram and u.telegram_chat_id:
                text = build_weekly_report_telegram(u.username, stats)
                if send_telegram(u.telegram_chat_id, text)["sent"]:
                    telegram_sent += 1
                    delivered = True
            if delivered:
                u.last_weekly_report_sent = now
                db.commit()
        return {"sent": sent, "telegram_sent": telegram_sent, "skipped": skipped, "total_users": len(users)}
    finally:
        db.close()


def catch_up_weekly_if_overdue() -> dict:
    """
    Reliability guarantee: on startup (or hourly), check if any user is overdue
    for a weekly report (>7 days since last). If so, send now.
    This protects against missed reports if the app was offline on Sunday 6 PM.
    """
    db = SessionLocal()
    sent = 0
    telegram_sent = 0
    try:
        now = datetime.utcnow()
        users = db.query(User).all()
        for u in users:
            if not u.notify_email and not (u.notify_telegram and u.telegram_chat_id):
                continue
            overdue = (
                u.last_weekly_report_sent is None
                or (now - u.last_weekly_report_sent).days >= 7
            )
            # Only send if user has at least 1 entry ever (avoid spamming brand-new users)
            entry_count = (
                db.query(func.count(ProductivityEntry.id))
                .filter(ProductivityEntry.user_id == u.id)
                .scalar()
            )
            if overdue and entry_count > 0:
                stats = compute_weekly_stats(db, u)
                delivered = False
                if u.notify_email:
                    html = build_weekly_report_html(u.username, stats)
                    if send_email(u.email, "Your TwinFlow weekly report", html)["sent"]:
                        sent += 1
                        delivered = True
                if u.notify_telegram and u.telegram_chat_id:
                    text = build_weekly_report_telegram(u.username, stats)
                    if send_telegram(u.telegram_chat_id, text)["sent"]:
                        telegram_sent += 1
                        delivered = True
                if delivered:
                    u.last_weekly_report_sent = now
                    db.commit()
        if sent or telegram_sent:
            print(f"[notifications] Catch-up: sent {sent} email and {telegram_sent} telegram overdue weekly report(s).")
        return {"sent": sent, "telegram_sent": telegram_sent}
    finally:
        db.close()
