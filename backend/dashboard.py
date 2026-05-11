"""Dashboard analytics routes."""
from datetime import date as date_type, timedelta
from typing import List

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from auth import current_user
from database import get_db
from models import Badge, ProductivityEntry, User
from schemas import (
    BadgeOut, DashboardSummary, ProductivityEntryOut, TrendDataPoint, WeeklyReport,
)
from streaks import (
    BADGE_LABELS,
    BADGE_THRESHOLDS,
    check_and_award_badges,
    compute_current_streak,
    compute_longest_streak,
)

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


def _avg(values, default=0.0):
    return round(sum(values) / len(values), 2) if values else default


@router.get("/summary", response_model=DashboardSummary)
def summary(
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    entries = (
        db.query(ProductivityEntry)
        .filter(ProductivityEntry.user_id == user.id)
        .order_by(ProductivityEntry.date.desc())
        .all()
    )
    total = len(entries)
    avg_score = _avg([e.productivity_score for e in entries])
    avg_energy = _avg([e.predicted_energy_level for e in entries])
    avg_sleep = _avg([e.sleep_hours for e in entries])
    avg_focus = _avg([e.focus_level for e in entries])
    total_tasks = sum(e.tasks_completed for e in entries)
    current_streak = compute_current_streak(user.id, db)
    longest_streak = compute_longest_streak(user.id, db)
    awarded = check_and_award_badges(user.id, db, current_streak)
    if awarded:
        db.commit()

    today_d = date_type.today()
    last_week = [e for e in entries if e.date >= today_d - timedelta(days=7)]
    prev_week = [e for e in entries
                 if today_d - timedelta(days=14) <= e.date < today_d - timedelta(days=7)]
    last_avg = _avg([e.productivity_score for e in last_week])
    prev_avg = _avg([e.productivity_score for e in prev_week])
    weekly_change = round(
        ((last_avg - prev_avg) / prev_avg) * 100, 1
    ) if prev_avg > 0 else 0.0

    if total == 0:
        insight = "Log your first daily entry to start training your digital twin."
    elif avg_sleep < 7:
        insight = "Your average sleep is below 7h — boosting it is the fastest way to lift energy."
    elif avg_focus < 6:
        insight = "Focus scores are low. Try blocking out 90-min deep-work sessions."
    elif avg_score >= 75:
        insight = "Excellent! You're consistently performing in your peak zone."
    else:
        insight = "Solid baseline. Aim for 8h sleep + a focused morning to push above 75."

    recent = entries[:5]
    badges = (
        db.query(Badge)
        .filter(Badge.user_id == user.id)
        .order_by(Badge.earned_at.asc())
        .all()
    )
    badge_order = {code: idx for idx, code in enumerate(BADGE_THRESHOLDS)}
    badge_payload = [
        BadgeOut(
            code=badge.code,
            earnedAt=badge.earned_at,
            label=BADGE_LABELS.get(badge.code, badge.code.title()),
        )
        for badge in sorted(
            badges,
            key=lambda badge: badge_order.get(badge.code, len(badge_order)),
        )
    ]

    return DashboardSummary(
        avgProductivityScore=avg_score,
        avgEnergyLevel=avg_energy,
        avgSleepHours=avg_sleep,
        avgFocusLevel=avg_focus,
        totalTasksCompleted=total_tasks,
        totalEntries=total,
        streakDays=current_streak,
        currentStreak=current_streak,
        longestStreak=longest_streak,
        weeklyChange=weekly_change,
        topInsight=insight,
        badges=badge_payload,
        recentEntries=[ProductivityEntryOut.model_validate(e) for e in recent],
    )


@router.get("/trend", response_model=List[TrendDataPoint])
def trend(
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    cutoff = date_type.today() - timedelta(days=30)
    entries = (
        db.query(ProductivityEntry)
        .filter(ProductivityEntry.user_id == user.id, ProductivityEntry.date >= cutoff)
        .order_by(ProductivityEntry.date.asc())
        .all()
    )
    return [
        TrendDataPoint(
            date=e.date,
            productivityScore=e.productivity_score,
            energyLevel=e.predicted_energy_level,
            focusLevel=e.focus_level,
            sleepHours=e.sleep_hours,
        )
        for e in entries
    ]


@router.get("/weekly-report", response_model=WeeklyReport)
def weekly_report(
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    today_d = date_type.today()
    week_start = today_d - timedelta(days=today_d.weekday())
    week_end = week_start + timedelta(days=6)
    entries = (
        db.query(ProductivityEntry)
        .filter(
            ProductivityEntry.user_id == user.id,
            ProductivityEntry.date >= week_start,
            ProductivityEntry.date <= week_end,
        )
        .order_by(ProductivityEntry.date.asc())
        .all()
    )
    avg_score = _avg([e.productivity_score for e in entries])
    avg_energy = _avg([e.predicted_energy_level for e in entries])
    total_tasks = sum(e.tasks_completed for e in entries)
    best_day = max(entries, key=lambda e: e.productivity_score).date if entries else None
    worst_day = min(entries, key=lambda e: e.productivity_score).date if entries else None

    tips = []
    if entries:
        if _avg([e.sleep_hours for e in entries]) < 7:
            tips.append("Aim for 7-8 hours of sleep on weekdays.")
        if _avg([float(e.focus_level) for e in entries]) < 6:
            tips.append("Try a 90/20 work-rest cycle to boost focus.")
        if total_tasks < len(entries) * 4:
            tips.append("Break large tasks into 2-3 smaller ones to track wins.")
    if not tips:
        tips = ["Keep your routine consistent — you're doing great this week."]

    daily = [
        TrendDataPoint(
            date=e.date,
            productivityScore=e.productivity_score,
            energyLevel=e.predicted_energy_level,
            focusLevel=e.focus_level,
            sleepHours=e.sleep_hours,
        )
        for e in entries
    ]

    return WeeklyReport(
        weekStart=week_start,
        weekEnd=week_end,
        avgProductivityScore=avg_score,
        avgEnergyLevel=avg_energy,
        totalTasksCompleted=total_tasks,
        bestDay=best_day,
        worstDay=worst_day,
        improvementTips=tips,
        dailyBreakdown=daily,
    )
