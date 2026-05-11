"""Loads the trained model on import and exposes a single predict() helper."""
import os

import numpy as np
import joblib
from sqlalchemy.orm import Session

from models import ProductivityEntry

MODEL_PATH = os.path.join(os.path.dirname(__file__), "model.pkl")
DEFAULT_SCHEDULE_COMPLETION_PCT = 0.5
EXPECTED_FEATURES = [
    "sleep_hours",
    "focus_level",
    "break_minutes",
    "tasks_completed",
    "available_hours",
    "schedule_completion_pct",
]

_bundle = None


def _load_bundle():
    global _bundle
    if _bundle is None:
        if not os.path.exists(MODEL_PATH):
            # Train on first use if the model file is missing.
            from ml.train_model import train_and_save
            train_and_save()
        _bundle = joblib.load(MODEL_PATH)
        if _bundle.get("features") != EXPECTED_FEATURES:
            from ml.train_model import train_and_save
            train_and_save()
            _bundle = joblib.load(MODEL_PATH)
    return _bundle


def get_last_schedule_completion_pct(user_id: int, db: Session) -> float:
    row = (
        db.query(ProductivityEntry.schedule_completion_pct)
        .filter(
            ProductivityEntry.user_id == user_id,
            ProductivityEntry.schedule_completion_pct.isnot(None),
        )
        .order_by(ProductivityEntry.date.desc(), ProductivityEntry.id.desc())
        .first()
    )
    if not row or row[0] is None:
        return DEFAULT_SCHEDULE_COMPLETION_PCT
    return float(row[0])


def predict_energy(
    sleep_hours: float,
    focus_level: int,
    break_minutes: int,
    tasks_completed: int,
    available_hours: float,
    schedule_completion_pct: float = DEFAULT_SCHEDULE_COMPLETION_PCT,
) -> float:
    """Predict an energy score (0-10) from a user's daily habit features."""
    bundle = _load_bundle()
    model = bundle["model"]
    features = np.array([[sleep_hours, focus_level, break_minutes,
                          tasks_completed, available_hours, schedule_completion_pct]])
    pred = float(model.predict(features)[0])
    return max(0.0, min(10.0, pred))


def productivity_score(
    sleep_hours: float,
    focus_level: int,
    tasks_completed: int,
    break_minutes: int,
    energy: float,
) -> float:
    """Composite productivity score 0-100."""
    sleep_component = max(0.0, 1 - abs(sleep_hours - 8) / 4) * 25
    focus_component = (focus_level / 10) * 25
    tasks_component = min(tasks_completed / 8, 1) * 20
    break_component = max(0.0, 1 - abs(break_minutes - 60) / 120) * 10
    energy_component = (energy / 10) * 20
    score = sleep_component + focus_component + tasks_component + break_component + energy_component
    return round(min(100.0, max(0.0, score)), 1)
