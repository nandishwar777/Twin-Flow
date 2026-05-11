"""AI-generated schedule routes."""
from datetime import date as date_type

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from auth import current_user
from database import get_db
from models import DailySchedule, ProductivityEntry, ScheduleTaskStatus, User
from schemas import (
    DailyScheduleOut,
    ScheduleStatusSummary,
    ScheduleTask,
    ScheduleTaskStatusBody,
    ScheduleTaskStatusOut,
)
from ml.scheduler import generate_schedule, UserProfile

router = APIRouter(prefix="/api/schedule", tags=["schedule"])


def _serialize(sched: DailySchedule) -> DailyScheduleOut:
    return DailyScheduleOut(
        date=sched.date,
        predictedEnergyLevel=sched.predicted_energy_level,
        energyZone=sched.energy_zone,
        tasks=[ScheduleTask.model_validate(t) for t in sched.tasks],
        recommendations=sched.recommendations,
        totalWorkMinutes=sched.total_work_minutes,
        totalBreakMinutes=sched.total_break_minutes,
    )


def _task_ids(sched: DailySchedule) -> set[int]:
    return {
        int(task["id"])
        for task in (sched.tasks or [])
        if isinstance(task, dict) and task.get("id") is not None
    }


def build_schedule_status_summary(sched: DailySchedule | None, db: Session) -> ScheduleStatusSummary:
    if not sched:
        return ScheduleStatusSummary(
            done=0,
            skipped=0,
            total=0,
            completionPct=0.0,
            statuses=[],
        )

    task_ids = _task_ids(sched)
    rows = (
        db.query(ScheduleTaskStatus)
        .filter(ScheduleTaskStatus.schedule_id == sched.id)
        .order_by(ScheduleTaskStatus.task_id.asc())
        .all()
    )
    status_rows = [row for row in rows if row.task_id in task_ids]
    done = sum(1 for row in status_rows if row.status == "done")
    skipped = sum(1 for row in status_rows if row.status == "skipped")
    total = len(task_ids)
    pct = round((done / total) * 100, 1) if total else 0.0

    return ScheduleStatusSummary(
        done=done,
        skipped=skipped,
        total=total,
        completionPct=pct,
        statuses=[
            ScheduleTaskStatusOut(
                taskId=row.task_id,
                status=row.status,
                updatedAt=row.updated_at,
            )
            for row in status_rows
        ],
    )


def compute_schedule_completion_pct(user_id: int, schedule_date: date_type, db: Session) -> float | None:
    sched = (
        db.query(DailySchedule)
        .filter(
            DailySchedule.user_id == user_id,
            DailySchedule.date == schedule_date,
        )
        .first()
    )
    if not sched:
        return 0.0
    summary = build_schedule_status_summary(sched, db)
    return round(summary.completion_pct / 100.0, 4)


def _build_user_profile(user_id: int, latest: ProductivityEntry, db: Session) -> UserProfile:
    """Average the last 14 entries to produce a user habit profile.
    Falls back to the latest entry if no history is present."""
    history = (
        db.query(ProductivityEntry)
        .filter(ProductivityEntry.user_id == user_id)
        .order_by(ProductivityEntry.date.desc(), ProductivityEntry.id.desc())
        .limit(14)
        .all()
    )
    if not history:
        history = [latest]

    n = len(history)
    avg_sleep = sum(e.sleep_hours for e in history) / n
    avg_focus = sum(e.focus_level for e in history) / n
    avg_tasks = sum(e.tasks_completed for e in history) / n
    avg_break = sum(e.break_minutes for e in history) / n

    return UserProfile(
        avg_sleep_hours=avg_sleep,
        avg_focus_level=avg_focus,
        avg_tasks=avg_tasks,
        avg_break_min=avg_break,
        available_hours=latest.available_hours,
        user_id=user_id,
    )


def _build_and_save(user_id: int, db: Session) -> DailySchedule:
    today_date = date_type.today()
    entry = (
        db.query(ProductivityEntry)
        .filter(ProductivityEntry.user_id == user_id)
        .order_by(ProductivityEntry.date.desc(), ProductivityEntry.id.desc())
        .first()
    )
    if not entry:
        raise HTTPException(
            status_code=400,
            detail="Log a daily entry first to generate a schedule.",
        )

    profile = _build_user_profile(user_id, entry, db)

    zone, tasks, recs, work_min, break_min = generate_schedule(
        predicted_energy=entry.predicted_energy_level,
        available_hours=entry.available_hours,
        profile=profile,
        today=today_date,
    )
    # Replace any existing schedule for today
    existing = db.query(DailySchedule).filter(
        DailySchedule.user_id == user_id,
        DailySchedule.date == today_date,
    ).first()
    if existing:
        db.query(ScheduleTaskStatus).filter(
            ScheduleTaskStatus.schedule_id == existing.id,
        ).delete()
        db.delete(existing)
        db.commit()

    sched = DailySchedule(
        user_id=user_id,
        date=today_date,
        predicted_energy_level=entry.predicted_energy_level,
        energy_zone=zone,
        tasks=[t.model_dump(by_alias=True) for t in tasks],
        recommendations=recs,
        total_work_minutes=work_min,
        total_break_minutes=break_min,
    )
    db.add(sched)
    db.commit()
    db.refresh(sched)
    return sched


@router.get("/today", response_model=DailyScheduleOut)
def today_schedule(
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    today_date = date_type.today()
    sched = db.query(DailySchedule).filter(
        DailySchedule.user_id == user.id,
        DailySchedule.date == today_date,
    ).first()
    if not sched:
        sched = _build_and_save(user.id, db)
    return _serialize(sched)


@router.get("/today/status", response_model=ScheduleStatusSummary)
def today_status(
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    today_date = date_type.today()
    sched = (
        db.query(DailySchedule)
        .filter(
            DailySchedule.user_id == user.id,
            DailySchedule.date == today_date,
        )
        .first()
    )
    return build_schedule_status_summary(sched, db)


@router.post("/task/{task_id}/status", response_model=ScheduleStatusSummary)
def update_task_status(
    task_id: int,
    body: ScheduleTaskStatusBody,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    today_date = date_type.today()
    sched = (
        db.query(DailySchedule)
        .filter(
            DailySchedule.user_id == user.id,
            DailySchedule.date == today_date,
        )
        .first()
    )
    if not sched:
        raise HTTPException(status_code=404, detail="Today's schedule not found")
    if task_id not in _task_ids(sched):
        raise HTTPException(status_code=404, detail="Task not found in today's schedule")

    row = (
        db.query(ScheduleTaskStatus)
        .filter(
            ScheduleTaskStatus.schedule_id == sched.id,
            ScheduleTaskStatus.task_id == task_id,
        )
        .first()
    )
    if not row:
        row = ScheduleTaskStatus(
            user_id=user.id,
            schedule_id=sched.id,
            task_id=task_id,
            status=body.status,
        )
        db.add(row)
    else:
        row.status = body.status
    db.commit()

    return build_schedule_status_summary(sched, db)


@router.post("/generate", response_model=DailyScheduleOut)
def generate(
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    sched = _build_and_save(user.id, db)
    return _serialize(sched)
