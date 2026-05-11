"""Streak and badge helpers for the dashboard."""
from datetime import date as date_type, timedelta

from sqlalchemy.orm import Session

from models import Badge, ProductivityEntry


BADGE_THRESHOLDS = {
    "bronze": 7,
    "silver": 30,
    "gold": 100,
    "platinum": 365,
}

BADGE_LABELS = {
    "bronze": "Bronze",
    "silver": "Silver",
    "gold": "Gold",
    "platinum": "Platinum",
}


def _entry_dates(user_id: int, db: Session) -> list[date_type]:
    rows = (
        db.query(ProductivityEntry.date)
        .filter(ProductivityEntry.user_id == user_id)
        .distinct()
        .order_by(ProductivityEntry.date.asc())
        .all()
    )
    return [row[0] for row in rows]


def compute_current_streak(user_id: int, db: Session) -> int:
    dates = _entry_dates(user_id, db)
    if not dates:
        return 0

    logged_days = set(dates)
    today = date_type.today()
    yesterday = today - timedelta(days=1)

    if today in logged_days:
        anchor = today
    elif yesterday in logged_days:
        anchor = yesterday
    else:
        return 0

    streak = 0
    cursor = anchor
    while cursor in logged_days:
        streak += 1
        cursor -= timedelta(days=1)
    return streak


def compute_longest_streak(user_id: int, db: Session) -> int:
    dates = _entry_dates(user_id, db)
    if not dates:
        return 0

    longest = 1
    current = 1
    for prev_day, curr_day in zip(dates, dates[1:]):
        if curr_day - prev_day == timedelta(days=1):
            current += 1
            longest = max(longest, current)
        else:
            current = 1
    return longest


def check_and_award_badges(user_id: int, db: Session, current_streak: int) -> list[Badge]:
    existing_codes = {
        row[0]
        for row in db.query(Badge.code).filter(Badge.user_id == user_id).all()
    }
    awarded: list[Badge] = []

    for code, threshold in BADGE_THRESHOLDS.items():
        if current_streak < threshold or code in existing_codes:
            continue
        badge = Badge(user_id=user_id, code=code)
        db.add(badge)
        awarded.append(badge)

    if awarded:
        db.flush()

    return awarded
