"""Pydantic schemas for request/response validation."""
import base64
import binascii
import re
from datetime import date, datetime
from typing import List, Literal, Optional

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator


# ---------------- Phone helper ----------------

PHONE_RE = re.compile(r"\D")
PROFILE_PHOTO_RE = re.compile(r"^data:(image/(?:png|jpeg|jpg|webp|gif));base64,([A-Za-z0-9+/=]+)$")
PROFILE_PHOTO_URL_RE = re.compile(r"^https?://[^\s\"'<>]+$", re.IGNORECASE)
PROFILE_PHOTO_MAX_BYTES = 900_000


def normalize_indian_phone(value: str) -> str:
    """Strip all non-digits. Accept 10-digit Indian numbers, or +91XXXXXXXXXX."""
    if value is None:
        return ""
    digits = PHONE_RE.sub("", value)
    # Drop leading country code 91 if present and length is 12
    if len(digits) == 12 and digits.startswith("91"):
        digits = digits[2:]
    if len(digits) != 10 or not digits.isdigit():
        raise ValueError("Phone number must be a 10-digit Indian mobile number")
    return digits


def validate_password_strength(value: str) -> str:
    if len(value) < 8:
        raise ValueError("Password must be at least 8 characters long")
    checks = [
        (re.search(r"[A-Z]", value), "one uppercase letter"),
        (re.search(r"[a-z]", value), "one lowercase letter"),
        (re.search(r"\d", value), "one number"),
        (re.search(r"[^A-Za-z0-9]", value), "one special character"),
    ]
    missing = [label for passed, label in checks if not passed]
    if missing:
        raise ValueError("Password must include " + ", ".join(missing))
    return value


def normalize_profile_photo(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None

    cleaned = value.strip()
    if not cleaned:
        return None

    if PROFILE_PHOTO_URL_RE.fullmatch(cleaned):
        return cleaned

    match = PROFILE_PHOTO_RE.fullmatch(cleaned)
    if not match:
        raise ValueError("Profile photo must be a PNG, JPG, WEBP, or GIF image")

    try:
        raw = base64.b64decode(match.group(2), validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError("Profile photo data is invalid") from exc

    if len(raw) > PROFILE_PHOTO_MAX_BYTES:
        raise ValueError("Profile photo must be smaller than 900 KB")

    return f"data:{match.group(1)};base64,{match.group(2)}"


# ---------------- Auth ----------------

class RegisterBody(BaseModel):
    username: str = Field(min_length=3, max_length=64)
    email: EmailStr
    phone: str = Field(alias="phoneNumber", description="10-digit Indian mobile")
    password: str = Field(min_length=8)
    profile_photo: Optional[str] = Field(default=None, alias="profilePhoto")

    model_config = ConfigDict(populate_by_name=True)

    @field_validator("phone")
    @classmethod
    def _v_phone(cls, v: str) -> str:
        return normalize_indian_phone(v)

    @field_validator("password")
    @classmethod
    def _v_password(cls, v: str) -> str:
        return validate_password_strength(v)

    @field_validator("profile_photo")
    @classmethod
    def _v_profile_photo(cls, v: Optional[str]) -> Optional[str]:
        return normalize_profile_photo(v)


class RegisterAvailabilityBody(BaseModel):
    email: Optional[EmailStr] = None
    phone: Optional[str] = Field(default=None, alias="phoneNumber", description="10-digit Indian mobile")

    model_config = ConfigDict(populate_by_name=True)

    @field_validator("phone")
    @classmethod
    def _v_phone(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        return normalize_indian_phone(v)


class RegisterAvailabilityResponse(BaseModel):
    email_available: Optional[bool] = Field(default=None, alias="emailAvailable")
    phone_available: Optional[bool] = Field(default=None, alias="phoneAvailable")
    email_message: str = Field(default="", alias="emailMessage")
    phone_message: str = Field(default="", alias="phoneMessage")

    model_config = ConfigDict(populate_by_name=True)


class AvailabilityCheckResponse(BaseModel):
    available: bool
    message: str = ""


class LoginBody(BaseModel):
    """Login by email OR 10-digit phone under one identifier field."""

    identifier: str = Field(min_length=3, description="email or phone")
    password: str
    captcha_answer: str = Field(min_length=4, max_length=8, alias="captchaAnswer")

    model_config = ConfigDict(populate_by_name=True)


class UserOut(BaseModel):
    id: int
    username: str
    email: str
    phone_number: Optional[str] = Field(default=None, alias="phoneNumber")
    profile_photo: Optional[str] = Field(default=None, alias="profilePhoto")
    telegram_chat_id: Optional[str] = Field(default=None, alias="telegramChatId")
    notify_email: bool = Field(alias="notifyEmail")
    notify_sms: bool = Field(alias="notifySms")
    notify_telegram: bool = Field(alias="notifyTelegram")
    created_at: datetime = Field(alias="createdAt")

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class AuthResponse(BaseModel):
    user: UserOut
    message: str


class MessageResponse(BaseModel):
    message: str


class CaptchaResponse(BaseModel):
    image_data: str = Field(alias="imageData")
    expires_in_seconds: int = Field(alias="expiresInSeconds")
    message: str = ""

    model_config = ConfigDict(populate_by_name=True)


class GoogleAuthBody(BaseModel):
    credential: str = Field(min_length=20)


class GoogleAuthConfigResponse(BaseModel):
    enabled: bool
    client_id: Optional[str] = Field(default=None, alias="clientId")
    message: str = ""

    model_config = ConfigDict(populate_by_name=True)


# ---------------- Forgot password / OTP ----------------

class RequestOtpBody(BaseModel):
    """Step 1 - request OTP for password reset."""

    identifier: str = Field(min_length=3, description="email or phone")
    channel: Literal["email", "sms", "telegram"]


class VerifyOtpBody(BaseModel):
    """Step 2 - verify OTP and set new password."""

    identifier: str = Field(min_length=3)
    code: str = Field(min_length=4, max_length=8)
    new_password: str = Field(min_length=8, alias="newPassword")

    model_config = ConfigDict(populate_by_name=True)

    @field_validator("new_password")
    @classmethod
    def _v_new_password(cls, v: str) -> str:
        return validate_password_strength(v)


class OtpRequestResponse(BaseModel):
    message: str
    channel: str
    expires_in_seconds: int = Field(alias="expiresInSeconds")
    masked_destination: str = Field(alias="maskedDestination")

    model_config = ConfigDict(populate_by_name=True)


# ---------------- Profile / notification preferences ----------------

class UpdatePhoneBody(BaseModel):
    phone: str = Field(alias="phoneNumber")
    model_config = ConfigDict(populate_by_name=True)

    @field_validator("phone")
    @classmethod
    def _v_phone(cls, v: str) -> str:
        return normalize_indian_phone(v)


class NotificationPrefsBody(BaseModel):
    notify_email: bool = Field(alias="notifyEmail")
    notify_sms: bool = Field(alias="notifySms")
    notify_telegram: bool = Field(alias="notifyTelegram")
    model_config = ConfigDict(populate_by_name=True)


class UpdateProfilePhotoBody(BaseModel):
    profile_photo: Optional[str] = Field(default=None, alias="profilePhoto")

    model_config = ConfigDict(populate_by_name=True)

    @field_validator("profile_photo")
    @classmethod
    def _v_profile_photo(cls, v: Optional[str]) -> Optional[str]:
        return normalize_profile_photo(v)


class TelegramLinkCodeResponse(BaseModel):
    code: str
    bot_username: Optional[str] = Field(default=None, alias="botUsername")
    message: str

    model_config = ConfigDict(populate_by_name=True)


class ResetChannelAvailabilityBody(BaseModel):
    identifier: str = Field(min_length=3)


class ResetChannelAvailabilityResponse(BaseModel):
    email: bool
    sms: bool
    telegram: bool
    message: str = ""

    model_config = ConfigDict(populate_by_name=True)


# ---------------- Productivity / schedule (unchanged) ----------------

class CreateProductivityEntryBody(BaseModel):
    date: date
    sleep_hours: float = Field(ge=0, le=24, alias="sleepHours")
    focus_level: int = Field(ge=1, le=10, alias="focusLevel")
    tasks_completed: int = Field(ge=0, alias="tasksCompleted")
    break_minutes: int = Field(ge=0, alias="breakMinutes")
    energy_level_input: int = Field(ge=1, le=10, alias="energyLevelInput")
    available_hours: float = Field(ge=0, le=24, alias="availableHours")
    notes: Optional[str] = None

    model_config = ConfigDict(populate_by_name=True)

    @field_validator("date")
    @classmethod
    def _validate_today_only(cls, value: date) -> date:
        if value != date.today():
            raise ValueError("Date must be today's date")
        return value


class ProductivityEntryOut(BaseModel):
    id: int
    user_id: int = Field(alias="userId")
    date: date
    sleep_hours: float = Field(alias="sleepHours")
    focus_level: int = Field(alias="focusLevel")
    tasks_completed: int = Field(alias="tasksCompleted")
    break_minutes: int = Field(alias="breakMinutes")
    energy_level_input: int = Field(alias="energyLevelInput")
    available_hours: float = Field(alias="availableHours")
    predicted_energy_level: float = Field(alias="predictedEnergyLevel")
    productivity_score: float = Field(alias="productivityScore")
    schedule_completion_pct: Optional[float] = Field(default=None, alias="scheduleCompletionPct")
    notes: Optional[str] = None
    created_at: datetime = Field(alias="createdAt")

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class TodayEntryResponse(BaseModel):
    entry: Optional[ProductivityEntryOut] = None
    has_entry: bool = Field(alias="hasEntry")

    model_config = ConfigDict(populate_by_name=True)


class ScheduleTask(BaseModel):
    id: int
    time: str
    duration: int
    task_type: str = Field(alias="taskType")
    title: str
    description: str
    personalization_reason: Optional[str] = Field(default=None, alias="personalizationReason")
    energy_required: str = Field(alias="energyRequired")
    priority: str

    model_config = ConfigDict(populate_by_name=True)


class DailyScheduleOut(BaseModel):
    date: date
    predicted_energy_level: float = Field(alias="predictedEnergyLevel")
    energy_zone: str = Field(alias="energyZone")
    tasks: List[ScheduleTask]
    recommendations: List[str]
    total_work_minutes: int = Field(alias="totalWorkMinutes")
    total_break_minutes: int = Field(alias="totalBreakMinutes")

    model_config = ConfigDict(populate_by_name=True)


class ScheduleTaskStatusBody(BaseModel):
    status: Literal["done", "skipped", "rescheduled"]


class ScheduleTaskStatusOut(BaseModel):
    task_id: int = Field(alias="taskId")
    status: Literal["pending", "done", "skipped", "rescheduled"]
    updated_at: Optional[datetime] = Field(default=None, alias="updatedAt")

    model_config = ConfigDict(populate_by_name=True)


class ScheduleStatusSummary(BaseModel):
    done: int
    skipped: int
    total: int
    completion_pct: float = Field(alias="completionPct")
    statuses: List[ScheduleTaskStatusOut]

    model_config = ConfigDict(populate_by_name=True)


class TrendDataPoint(BaseModel):
    date: date
    productivity_score: float = Field(alias="productivityScore")
    energy_level: float = Field(alias="energyLevel")
    focus_level: float = Field(alias="focusLevel")
    sleep_hours: float = Field(alias="sleepHours")

    model_config = ConfigDict(populate_by_name=True)


class BadgeOut(BaseModel):
    code: str
    earned_at: datetime = Field(alias="earnedAt")
    label: str

    model_config = ConfigDict(populate_by_name=True)


class DashboardSummary(BaseModel):
    avg_productivity_score: float = Field(alias="avgProductivityScore")
    avg_energy_level: float = Field(alias="avgEnergyLevel")
    avg_sleep_hours: float = Field(alias="avgSleepHours")
    avg_focus_level: float = Field(alias="avgFocusLevel")
    total_tasks_completed: int = Field(alias="totalTasksCompleted")
    total_entries: int = Field(alias="totalEntries")
    streak_days: int = Field(alias="streakDays")
    current_streak: int = Field(alias="currentStreak")
    longest_streak: int = Field(alias="longestStreak")
    weekly_change: float = Field(alias="weeklyChange")
    top_insight: str = Field(alias="topInsight")
    badges: List[BadgeOut]
    recent_entries: List[ProductivityEntryOut] = Field(alias="recentEntries")

    model_config = ConfigDict(populate_by_name=True)


class WeeklyReport(BaseModel):
    week_start: date = Field(alias="weekStart")
    week_end: date = Field(alias="weekEnd")
    avg_productivity_score: float = Field(alias="avgProductivityScore")
    avg_energy_level: float = Field(alias="avgEnergyLevel")
    total_tasks_completed: int = Field(alias="totalTasksCompleted")
    best_day: Optional[date] = Field(default=None, alias="bestDay")
    worst_day: Optional[date] = Field(default=None, alias="worstDay")
    improvement_tips: List[str] = Field(alias="improvementTips")
    daily_breakdown: List[TrendDataPoint] = Field(alias="dailyBreakdown")

    model_config = ConfigDict(populate_by_name=True)
