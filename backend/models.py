"""SQLAlchemy ORM models."""
from datetime import datetime, date
from sqlalchemy import (
    Column, Integer, String, Float, Date, DateTime, Boolean,
    ForeignKey, Text, JSON, UniqueConstraint
)
from sqlalchemy.orm import relationship
from database import Base


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(64), unique=True, nullable=False, index=True)
    email = Column(String(128), unique=True, nullable=False, index=True)
    google_sub = Column(String(255), unique=True, nullable=True, index=True)
    phone_number = Column(String(20), nullable=True, index=True)
    telegram_chat_id = Column(String(64), nullable=True)
    telegram_link_code = Column(String(8), nullable=True)
    profile_photo = Column(Text, nullable=True)
    password_hash = Column(String(256), nullable=False)

    # Notification preferences (defaults: email ON, SMS ON when phone present)
    notify_email = Column(Boolean, default=True, nullable=False)
    notify_sms = Column(Boolean, default=True, nullable=False)
    notify_telegram = Column(Boolean, default=True, nullable=False)

    # Reliability tracking — when did we last successfully send a weekly report?
    last_weekly_report_sent = Column(DateTime, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    entries = relationship("ProductivityEntry", back_populates="user", cascade="all, delete-orphan")
    schedules = relationship("DailySchedule", back_populates="user", cascade="all, delete-orphan")
    otps = relationship("OtpCode", back_populates="user", cascade="all, delete-orphan")
    badges = relationship("Badge", back_populates="user", cascade="all, delete-orphan")
    schedule_task_statuses = relationship(
        "ScheduleTaskStatus",
        back_populates="user",
        cascade="all, delete-orphan",
    )


class OtpCode(Base):
    """One-time-passwords used for forgot-password flow."""
    __tablename__ = "otp_codes"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    code_hash = Column(String(256), nullable=False)  # bcrypt-hashed OTP
    purpose = Column(String(32), nullable=False, default="reset_password")
    channel = Column(String(16), nullable=False)  # 'email' or 'sms'
    expires_at = Column(DateTime, nullable=False)
    attempts = Column(Integer, default=0, nullable=False)
    used = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    user = relationship("User", back_populates="otps")


class ProductivityEntry(Base):
    __tablename__ = "productivity_entries"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    date = Column(Date, nullable=False, index=True)
    sleep_hours = Column(Float, nullable=False)
    focus_level = Column(Integer, nullable=False)
    tasks_completed = Column(Integer, nullable=False)
    break_minutes = Column(Integer, nullable=False)
    energy_level_input = Column(Integer, nullable=False)
    available_hours = Column(Float, nullable=False)
    predicted_energy_level = Column(Float, nullable=False)
    productivity_score = Column(Float, nullable=False)
    schedule_completion_pct = Column(Float, nullable=True, default=None)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    user = relationship("User", back_populates="entries")


class DailySchedule(Base):
    __tablename__ = "daily_schedules"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    date = Column(Date, nullable=False)
    predicted_energy_level = Column(Float, nullable=False)
    energy_zone = Column(String(16), nullable=False)
    tasks = Column(JSON, nullable=False)
    recommendations = Column(JSON, nullable=False)
    total_work_minutes = Column(Integer, nullable=False)
    total_break_minutes = Column(Integer, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    user = relationship("User", back_populates="schedules")
    task_statuses = relationship(
        "ScheduleTaskStatus",
        back_populates="schedule",
        cascade="all, delete-orphan",
    )


class Badge(Base):
    __tablename__ = "badges"
    __table_args__ = (
        UniqueConstraint("user_id", "code", name="uq_badges_user_code"),
    )

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    code = Column(String(32), nullable=False)
    earned_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    user = relationship("User", back_populates="badges")


class ScheduleTaskStatus(Base):
    __tablename__ = "schedule_task_statuses"
    __table_args__ = (
        UniqueConstraint("schedule_id", "task_id", name="uq_schedule_task_statuses_schedule_task"),
    )

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    schedule_id = Column(Integer, ForeignKey("daily_schedules.id", ondelete="CASCADE"), nullable=False, index=True)
    task_id = Column(Integer, nullable=False)
    status = Column(String(16), nullable=False, default="pending")
    updated_at = Column(DateTime, default=datetime.utcnow, nullable=False, onupdate=datetime.utcnow)

    user = relationship("User", back_populates="schedule_task_statuses")
    schedule = relationship("DailySchedule", back_populates="task_statuses")
