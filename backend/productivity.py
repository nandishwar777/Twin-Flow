"""Productivity entry routes."""
from datetime import date as date_type
from typing import List
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from database import get_db
from models import User, ProductivityEntry
from schemas import (
    CreateProductivityEntryBody, ProductivityEntryOut, TodayEntryResponse,
)
from auth import current_user
from ml.predict import get_last_schedule_completion_pct, predict_energy, productivity_score

router = APIRouter(prefix="/api/productivity", tags=["productivity"])


@router.get("/entries", response_model=List[ProductivityEntryOut])
def list_entries(
    limit: int = 30,
    offset: int = 0,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    rows = (
        db.query(ProductivityEntry)
        .filter(ProductivityEntry.user_id == user.id)
        .order_by(ProductivityEntry.date.desc(), ProductivityEntry.id.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    return [ProductivityEntryOut.model_validate(r) for r in rows]


@router.post("/entries", status_code=201, response_model=ProductivityEntryOut)
def create_entry(
    body: CreateProductivityEntryBody,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    predicted = predict_energy(
        sleep_hours=body.sleep_hours,
        focus_level=body.focus_level,
        break_minutes=body.break_minutes,
        tasks_completed=body.tasks_completed,
        available_hours=body.available_hours,
        schedule_completion_pct=get_last_schedule_completion_pct(user.id, db),
    )
    score = productivity_score(
        sleep_hours=body.sleep_hours,
        focus_level=body.focus_level,
        tasks_completed=body.tasks_completed,
        break_minutes=body.break_minutes,
        energy=predicted,
    )
    entry = ProductivityEntry(
        user_id=user.id,
        date=body.date,
        sleep_hours=body.sleep_hours,
        focus_level=body.focus_level,
        tasks_completed=body.tasks_completed,
        break_minutes=body.break_minutes,
        energy_level_input=body.energy_level_input,
        available_hours=body.available_hours,
        predicted_energy_level=predicted,
        productivity_score=score,
        notes=body.notes,
    )
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return ProductivityEntryOut.model_validate(entry)


@router.get("/entries/{entry_id}", response_model=ProductivityEntryOut)
def get_entry(
    entry_id: int,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    entry = db.query(ProductivityEntry).filter(
        ProductivityEntry.id == entry_id,
        ProductivityEntry.user_id == user.id,
    ).first()
    if not entry:
        raise HTTPException(status_code=404, detail="Entry not found")
    return ProductivityEntryOut.model_validate(entry)


@router.get("/today", response_model=TodayEntryResponse)
def today(
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    today_date = date_type.today()
    entry = db.query(ProductivityEntry).filter(
        ProductivityEntry.user_id == user.id,
        ProductivityEntry.date == today_date,
    ).first()
    if entry:
        return TodayEntryResponse(
            entry=ProductivityEntryOut.model_validate(entry),
            hasEntry=True,
        )
    return TodayEntryResponse(entry=None, hasEntry=False)
