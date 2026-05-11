"""
Trains a scikit-learn RandomForestRegressor that predicts a user's
energy level (0-10) from their daily habit features.

Generates synthetic training data based on plausible relationships
between sleep, focus, breaks, tasks, and energy. Run this once before
starting the server, or whenever you want to retrain:

    python -m ml.train_model

Saves the model to ml/model.pkl using joblib.
"""
import os
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestRegressor
from sklearn.model_selection import train_test_split
from sklearn.metrics import mean_absolute_error, r2_score
import joblib

RNG = np.random.default_rng(42)
N_SAMPLES = 4000
MODEL_PATH = os.path.join(os.path.dirname(__file__), "model.pkl")


def generate_synthetic_data(n: int) -> pd.DataFrame:
    """Generate plausible (sleep, focus, breaks, tasks, completion, energy) tuples."""
    sleep_hours = np.clip(RNG.normal(7.0, 1.4, n), 3, 11)
    focus_level = np.clip(RNG.normal(6.5, 1.8, n), 1, 10)
    break_minutes = np.clip(RNG.normal(45, 25, n), 0, 180)
    tasks_completed = np.clip(RNG.poisson(6, n), 0, 25)
    available_hours = np.clip(RNG.normal(8, 2, n), 2, 14)
    schedule_completion_pct = np.clip(RNG.beta(4, 3, n), 0, 1)

    # Synthetic ground-truth energy: weighted combination + noise.
    energy = (
        0.45 * (sleep_hours / 8.0) * 10        # sleep is the biggest driver
        + 0.25 * focus_level                    # focus
        + 0.10 * (1 - abs(break_minutes - 60) / 120) * 10  # ~60 min breaks ideal
        + 0.10 * np.clip(tasks_completed / 8.0, 0, 1.5) * 10
        + 0.05 * (available_hours / 10.0) * 10
        + 0.05 * schedule_completion_pct * 10
    )
    energy += RNG.normal(0, 0.7, n)             # noise
    energy = np.clip(energy, 0, 10)

    return pd.DataFrame({
        "sleep_hours": sleep_hours,
        "focus_level": focus_level,
        "break_minutes": break_minutes,
        "tasks_completed": tasks_completed,
        "available_hours": available_hours,
        "schedule_completion_pct": schedule_completion_pct,
        "energy_level": energy,
    })


def train_and_save() -> None:
    print(f"[ml] Generating {N_SAMPLES} synthetic training samples...")
    df = generate_synthetic_data(N_SAMPLES)

    df["schedule_completion_pct"] = df["schedule_completion_pct"].fillna(0.5)

    feature_cols = ["sleep_hours", "focus_level", "break_minutes",
                    "tasks_completed", "available_hours", "schedule_completion_pct"]
    X = df[feature_cols].values
    y = df["energy_level"].values

    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, random_state=42
    )

    print("[ml] Training RandomForestRegressor...")
    model = RandomForestRegressor(
        n_estimators=200,
        max_depth=12,
        min_samples_leaf=4,
        random_state=42,
        n_jobs=1,
    )
    model.fit(X_train, y_train)

    preds = model.predict(X_test)
    mae = mean_absolute_error(y_test, preds)
    r2 = r2_score(y_test, preds)
    print(f"[ml] Test MAE: {mae:.3f}   R^2: {r2:.3f}")

    joblib.dump({"model": model, "features": feature_cols}, MODEL_PATH)
    print(f"[ml] Saved model to {MODEL_PATH}")


if __name__ == "__main__":
    train_and_save()
