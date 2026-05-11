"""APScheduler setup. Runs daily reminders, weekly reports, and a periodic
catch-up job that delivers any missed weekly reports (so reports never
silently fail if the app was offline on Sunday 6 PM)."""
import os
from datetime import date as date_type

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from database import SessionLocal
from models import ProductivityEntry
from notifications import (
    run_daily_reminders,
    run_weekly_reports,
    catch_up_weekly_if_overdue,
)
from schedule import compute_schedule_completion_pct

_scheduler: BackgroundScheduler | None = None


def run_schedule_feedback_capture() -> dict:
    """Persist today's schedule completion ratio into today's productivity entry."""
    db = SessionLocal()
    updated = 0
    try:
        today = date_type.today()
        entries = (
            db.query(ProductivityEntry)
            .filter(ProductivityEntry.date == today)
            .all()
        )
        for entry in entries:
            entry.schedule_completion_pct = compute_schedule_completion_pct(entry.user_id, today, db)
            updated += 1
        if updated:
            db.commit()
        return {"updated": updated, "date": today.isoformat()}
    finally:
        db.close()


def start_scheduler() -> BackgroundScheduler:
    global _scheduler
    if _scheduler:
        return _scheduler

    daily_hour = int(os.getenv("DAILY_REMINDER_HOUR", "8"))
    daily_minute = int(os.getenv("DAILY_REMINDER_MINUTE", "0"))
    weekly_day = os.getenv("WEEKLY_REPORT_DAY", "sun")  # mon..sun
    weekly_hour = int(os.getenv("WEEKLY_REPORT_HOUR", "18"))
    catchup_hours = int(os.getenv("WEEKLY_CATCHUP_INTERVAL_HOURS", "6"))

    sch = BackgroundScheduler(daemon=True, timezone=os.getenv("TZ", "Asia/Kolkata"))

    # Daily reminders — email + SMS
    sch.add_job(
        run_daily_reminders,
        CronTrigger(hour=daily_hour, minute=daily_minute),
        id="daily_reminders",
        replace_existing=True,
        misfire_grace_time=3600,  # if missed by up to 1 hour, still run
    )

    # Weekly reports
    sch.add_job(
        lambda: run_weekly_reports(force=True),
        CronTrigger(day_of_week=weekly_day, hour=weekly_hour, minute=0),
        id="weekly_reports",
        replace_existing=True,
        misfire_grace_time=24 * 3600,  # if missed by up to 24h, still run
    )

    # Catch-up: every N hours, send weekly report to anyone overdue (>=7 days
    # since their last). Guarantees reliability even if the scheduled time was
    # missed because the app was offline.
    sch.add_job(
        catch_up_weekly_if_overdue,
        IntervalTrigger(hours=catchup_hours),
        id="weekly_catchup",
        replace_existing=True,
    )

    sch.add_job(
        run_schedule_feedback_capture,
        CronTrigger(hour=23, minute=55),
        id="schedule_feedback_capture",
        replace_existing=True,
        misfire_grace_time=2 * 3600,
    )

    sch.start()
    _scheduler = sch
    print(
        f"[scheduler] Started. Daily reminders at {daily_hour:02d}:{daily_minute:02d}, "
        f"weekly reports on {weekly_day} at {weekly_hour:02d}:00, "
        f"catch-up every {catchup_hours}h, "
        f"schedule feedback at 23:55 ({os.getenv('TZ', 'Asia/Kolkata')})."
    )
    return sch


def shutdown_scheduler() -> None:
    global _scheduler
    if _scheduler:
        _scheduler.shutdown(wait=False)
        _scheduler = None
