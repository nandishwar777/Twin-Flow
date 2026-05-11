"""Authentication routes for register, login, logout, and OTP-based password reset."""
from html import escape
import os
import re
import secrets
import sys
from datetime import datetime, timedelta
from urllib.parse import quote

from dotenv import load_dotenv
from fastapi import APIRouter, Depends, HTTPException, Request
from passlib.context import CryptContext
from sqlalchemy import func
from sqlalchemy.orm import Session

from database import get_db
from models import OtpCode, User
from notifications import (
    build_otp_email_html,
    send_email,
    send_sms,
    smtp_configured,
    sms_configured,
)
from schemas import (
    AuthResponse,
    CaptchaResponse,
    GoogleAuthBody,
    GoogleAuthConfigResponse,
    LoginBody,
    MessageResponse,
    NotificationPrefsBody,
    OtpRequestResponse,
    RegisterBody,
    RequestOtpBody,
    ResetChannelAvailabilityBody,
    ResetChannelAvailabilityResponse,
    UpdatePhoneBody,
    UpdateProfilePhotoBody,
    UserOut,
    VerifyOtpBody,
)
from telegram_bot import send_telegram, tg_configured

load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

router = APIRouter(prefix="/api/auth", tags=["auth"])

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

OTP_TTL_MINUTES = int(os.getenv("OTP_TTL_MINUTES", "10"))
OTP_MAX_ATTEMPTS = int(os.getenv("OTP_MAX_ATTEMPTS", "5"))
CAPTCHA_TTL_MINUTES = int(os.getenv("CAPTCHA_TTL_MINUTES", "5"))
CAPTCHA_LENGTH = max(4, int(os.getenv("CAPTCHA_LENGTH", "5")))
CAPTCHA_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


# ---------------- Helpers ----------------

def hash_password(plain: str) -> str:
    return pwd_context.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


def google_client_id() -> str:
    return os.getenv("GOOGLE_CLIENT_ID", "").strip()


def google_auth_configured() -> bool:
    return bool(google_client_id())


def google_auth_support_error() -> str | None:
    try:
        from google.auth.transport import requests as google_requests  # noqa: F401
        from google.oauth2 import id_token  # noqa: F401
    except ImportError:
        python_path = sys.executable or "the current Python interpreter"
        return (
            "Google sign-in is unavailable in the running backend environment "
            f"({python_path}). Install backend requirements in this environment "
            "or start the API with backend\\venv\\Scripts\\python.exe."
        )
    return None


def current_user(request: Request, db: Session = Depends(get_db)) -> User:
    user_id = request.session.get("user_id")
    if not user_id:
        raise HTTPException(status_code=401, detail="Not authenticated")
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    return user


def find_user_by_email(db: Session, email: str) -> User | None:
    normalized = (email or "").strip().lower()
    if not normalized:
        return None
    return db.query(User).filter(func.lower(User.email) == normalized).first()


def find_user_by_identifier(db: Session, identifier: str) -> User | None:
    """Look up user by email or phone (10-digit). Username also accepted."""
    ident = (identifier or "").strip()
    if "@" in ident:
        return find_user_by_email(db, ident)
    digits = re.sub(r"\D", "", ident)
    if len(digits) == 12 and digits.startswith("91"):
        digits = digits[2:]
    if len(digits) == 10:
        return db.query(User).filter(User.phone_number == digits).first()
    return db.query(User).filter(User.username == ident).first()


def build_unique_username(db: Session, preferred: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9_]+", "_", (preferred or "").strip().lower()).strip("_")
    if not slug:
        slug = "twinflow_user"
    if len(slug) < 3:
        slug = f"{slug}_user"
    slug = slug[:64].rstrip("_") or "twinflow_user"

    candidate = slug
    suffix = 1
    while db.query(User).filter(User.username == candidate).first():
        tail = f"_{suffix}"
        candidate = f"{slug[: max(1, 64 - len(tail))].rstrip('_')}{tail}"
        suffix += 1
    return candidate


def generate_google_placeholder_password() -> str:
    return hash_password(secrets.token_urlsafe(32))


def verify_google_credential(credential: str) -> dict[str, str]:
    client_id = google_client_id()
    if not client_id:
        raise HTTPException(status_code=503, detail="Google sign-in is not configured on the server.")

    support_error = google_auth_support_error()
    if support_error:
        raise HTTPException(status_code=503, detail=support_error)

    from google.auth.transport import requests as google_requests
    from google.oauth2 import id_token

    try:
        token_info = id_token.verify_oauth2_token(
            credential,
            google_requests.Request(),
            client_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=401, detail="Google sign-in verification failed.") from exc

    google_sub = str(token_info.get("sub", "")).strip()
    email = str(token_info.get("email", "")).strip().lower()
    display_name = str(
        token_info.get("name")
        or token_info.get("given_name")
        or (email.split("@", 1)[0] if email else "")
    ).strip()

    if not google_sub or not email:
        raise HTTPException(status_code=400, detail="Google did not return a usable account profile.")
    if not token_info.get("email_verified"):
        raise HTTPException(status_code=400, detail="Google email must be verified before it can be used here.")

    return {
        "sub": google_sub,
        "email": email,
        "name": display_name,
        "picture": str(token_info.get("picture", "")).strip(),
    }


def find_or_create_google_user(db: Session, google_profile: dict[str, str]) -> tuple[User, bool]:
    google_sub = google_profile["sub"]
    email = google_profile["email"]

    user = db.query(User).filter(User.google_sub == google_sub).first()
    if user:
        return user, False

    user = find_user_by_email(db, email)
    if user:
        if user.google_sub and user.google_sub != google_sub:
            raise HTTPException(status_code=409, detail="This email is already linked to another Google account.")
        user.google_sub = google_sub
        db.commit()
        db.refresh(user)
        return user, False

    username_seed = google_profile["name"] or email.split("@", 1)[0]
    user = User(
        username=build_unique_username(db, username_seed),
        email=email,
        google_sub=google_sub,
        phone_number=None,
        profile_photo=google_profile.get("picture") or None,
        password_hash=generate_google_placeholder_password(),
        notify_email=True,
        notify_sms=False,
        notify_telegram=False,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user, True


def mask_email(addr: str) -> str:
    try:
        user, domain = addr.split("@", 1)
        masked_user = user[:2] + "***" + user[-1] if len(user) > 3 else user[0] + "***"
        return masked_user + "@" + domain
    except Exception:
        return "***"


def mask_phone(phone: str) -> str:
    if not phone or len(phone) < 4:
        return "***"
    return "XXXXXX" + phone[-4:]


def mask_telegram(chat_id: str) -> str:
    if not chat_id:
        return "***"
    return "telegram:" + str(chat_id)[-4:]


def build_otp_email_text(username: str, code: str, minutes: int) -> str:
    return (
        f"Hi {username},\n\n"
        f"Use this verification code to reset your TwinFlow password: {code}\n\n"
        f"This code expires in {minutes} minutes.\n"
        "If you did not request a password reset, you can ignore this email."
    )


def generate_captcha_text() -> str:
    return "".join(secrets.choice(CAPTCHA_ALPHABET) for _ in range(CAPTCHA_LENGTH))


def build_captcha_svg(code: str) -> str:
    width = 170
    height = 56
    palette = ("#1d4ed8", "#0f766e", "#b45309", "#7c3aed", "#be123c")

    noise_lines = []
    for _ in range(6):
        x1 = secrets.randbelow(width)
        y1 = secrets.randbelow(height)
        x2 = secrets.randbelow(width)
        y2 = secrets.randbelow(height)
        color = palette[secrets.randbelow(len(palette))]
        noise_lines.append(
            f'<path d="M{x1} {y1} C {x1 + 18} {y1 - 10}, {x2 - 18} {y2 + 10}, {x2} {y2}" '
            f'stroke="{color}" stroke-width="1.6" stroke-opacity="0.24" fill="none" />'
        )

    noise_dots = []
    for _ in range(12):
        cx = secrets.randbelow(width)
        cy = secrets.randbelow(height)
        r = 1 + secrets.randbelow(2)
        color = palette[secrets.randbelow(len(palette))]
        noise_dots.append(f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="{color}" fill-opacity="0.20" />')

    letters = []
    rotations = (-14, 10, -8, 12, -6, 8)
    for index, char in enumerate(code):
        x = 20 + index * 28
        y = 36 + ((index % 2) * 6) - (((index + 1) % 2) * 2)
        rotation = rotations[index % len(rotations)]
        color = palette[index % len(palette)]
        letters.append(
            f'<text x="{x}" y="{y}" fill="{color}" font-size="28" font-weight="700" '
            f'font-family="Segoe UI, Arial, sans-serif" transform="rotate({rotation} {x} {y})">'
            f"{escape(char)}</text>"
        )

    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" '
        f'width="{width}" height="{height}" role="img" aria-label="Captcha">'
        '<rect width="100%" height="100%" rx="12" fill="#f8fafc" />'
        '<rect x="1.5" y="1.5" width="167" height="53" rx="10.5" fill="none" stroke="#cbd5e1" />'
        + "".join(noise_lines)
        + "".join(noise_dots)
        + "".join(letters)
        + "</svg>"
    )


def issue_login_captcha(request: Request) -> CaptchaResponse:
    code = generate_captcha_text()
    request.session["login_captcha"] = {
        "answer": code,
        "expires_at": (datetime.utcnow() + timedelta(minutes=CAPTCHA_TTL_MINUTES)).isoformat(),
    }
    return CaptchaResponse(
        image_data=f"data:image/svg+xml;utf8,{quote(build_captcha_svg(code))}",
        expires_in_seconds=CAPTCHA_TTL_MINUTES * 60,
        message="Captcha generated.",
    )


def verify_login_captcha(request: Request, answer: str) -> None:
    captcha = request.session.get("login_captcha")
    if not captcha:
        raise HTTPException(status_code=400, detail="Captcha expired. Refresh and try again.")

    try:
        expires_at = datetime.fromisoformat(captcha["expires_at"])
    except Exception:
        request.session.pop("login_captcha", None)
        raise HTTPException(status_code=400, detail="Captcha expired. Refresh and try again.")

    if expires_at < datetime.utcnow():
        request.session.pop("login_captcha", None)
        raise HTTPException(status_code=400, detail="Captcha expired. Refresh and try again.")

    expected = str(captcha.get("answer", "")).strip().upper()
    provided = (answer or "").strip().upper()
    if provided != expected:
        request.session.pop("login_captcha", None)
        raise HTTPException(status_code=400, detail="Incorrect captcha. Refresh and try again.")

    request.session.pop("login_captcha", None)


# ---------------- Register / Login / Logout ----------------

@router.get("/captcha", response_model=CaptchaResponse)
def login_captcha(request: Request):
    return issue_login_captcha(request)


@router.get("/google/config", response_model=GoogleAuthConfigResponse)
def google_config():
    configured = google_auth_configured()
    support_error = google_auth_support_error() if configured else None
    enabled = configured and not support_error
    return GoogleAuthConfigResponse(
        enabled=enabled,
        client_id=google_client_id() if enabled else None,
        message=(
            "Google sign-in is ready."
            if enabled
            else (
                support_error
                or "Set GOOGLE_CLIENT_ID in backend/.env to enable Google sign-in."
            )
        ),
    )


@router.post("/google", response_model=AuthResponse)
def google_sign_in(body: GoogleAuthBody, request: Request, db: Session = Depends(get_db)):
    google_profile = verify_google_credential(body.credential)
    user, created = find_or_create_google_user(db, google_profile)

    request.session["user_id"] = user.id
    return AuthResponse(
        user=UserOut.model_validate(user),
        message="Account created with Google" if created else "Signed in with Google",
    )


@router.post("/register", status_code=201, response_model=AuthResponse)
def register(body: RegisterBody, request: Request, db: Session = Depends(get_db)):
    normalized_email = body.email.lower()
    exists = db.query(User).filter(
        (func.lower(User.email) == normalized_email) | (User.username == body.username)
    ).first()
    if exists:
        raise HTTPException(status_code=409, detail="Email or username already in use")
    if db.query(User).filter(User.phone_number == body.phone).first():
        raise HTTPException(status_code=409, detail="Phone number already registered")

    user = User(
        username=body.username,
        email=normalized_email,
        phone_number=body.phone,
        profile_photo=body.profile_photo,
        password_hash=hash_password(body.password),
        notify_email=True,
        notify_sms=True,
        notify_telegram=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    request.session["user_id"] = user.id
    return AuthResponse(
        user=UserOut.model_validate(user),
        message="Registered successfully",
    )


@router.post("/login", response_model=AuthResponse)
def login(body: LoginBody, request: Request, db: Session = Depends(get_db)):
    verify_login_captcha(request, body.captcha_answer)

    user = find_user_by_identifier(db, body.identifier)
    if not user or not verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid credentials")

    request.session["user_id"] = user.id
    return AuthResponse(
        user=UserOut.model_validate(user),
        message="Logged in successfully",
    )


@router.post("/logout", response_model=MessageResponse)
def logout(request: Request):
    request.session.clear()
    return MessageResponse(message="Logged out successfully")


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(current_user)):
    return UserOut.model_validate(user)


# ---------------- Profile / preferences ----------------

@router.put("/me/phone", response_model=UserOut)
def update_phone(body: UpdatePhoneBody, user: User = Depends(current_user),
                 db: Session = Depends(get_db)):
    other = db.query(User).filter(
        User.phone_number == body.phone, User.id != user.id
    ).first()
    if other:
        raise HTTPException(status_code=409, detail="Phone number already in use")
    user.phone_number = body.phone
    db.commit()
    db.refresh(user)
    return UserOut.model_validate(user)


@router.put("/me/profile-photo", response_model=UserOut)
def update_profile_photo(
    body: UpdateProfilePhotoBody,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    user.profile_photo = body.profile_photo
    db.commit()
    db.refresh(user)
    return UserOut.model_validate(user)


@router.put("/me/notifications", response_model=UserOut)
def update_notifications(body: NotificationPrefsBody, user: User = Depends(current_user),
                         db: Session = Depends(get_db)):
    user.notify_email = body.notify_email
    user.notify_sms = body.notify_sms
    user.notify_telegram = body.notify_telegram
    db.commit()
    db.refresh(user)
    return UserOut.model_validate(user)


@router.post("/reset-options", response_model=ResetChannelAvailabilityResponse)
def reset_options(body: ResetChannelAvailabilityBody, db: Session = Depends(get_db)):
    user = find_user_by_identifier(db, body.identifier)
    if not user:
        raise HTTPException(status_code=404, detail="No account matches that email or phone")
    return ResetChannelAvailabilityResponse(
        email=bool(smtp_configured()),
        sms=bool(user.phone_number and sms_configured()),
        telegram=bool(user.telegram_chat_id and tg_configured()),
        message="Available channels loaded.",
    )


# ---------------- Forgot password / OTP flow ----------------

@router.post("/request-otp", response_model=OtpRequestResponse)
def request_otp(body: RequestOtpBody, db: Session = Depends(get_db)):
    """
    Step 1 of forgot-password: user supplies email/phone + chosen channel.
    We generate a 6-digit OTP, store its bcrypt hash with a 10-minute expiry,
    and deliver the OTP via the chosen channel.
    """
    user = find_user_by_identifier(db, body.identifier)
    if not user:
        raise HTTPException(status_code=404, detail="No account matches that email or phone")

    if body.channel == "sms":
        if not user.phone_number:
            raise HTTPException(status_code=400, detail="No phone number on file. Use email instead.")
        if not sms_configured():
            raise HTTPException(status_code=503, detail="SMS service not configured. Use email instead.")
        destination = mask_phone(user.phone_number)
    elif body.channel == "telegram":
        if not user.telegram_chat_id:
            raise HTTPException(status_code=400, detail="Telegram is not linked on this account. Use email or SMS instead.")
        if not tg_configured():
            raise HTTPException(status_code=503, detail="Telegram bot is not configured. Use email instead.")
        destination = mask_telegram(user.telegram_chat_id)
    else:
        if not smtp_configured():
            raise HTTPException(status_code=503, detail="Email service not configured.")
        destination = mask_email(user.email)

    code = f"{secrets.randbelow(1_000_000):06d}"
    code_hash = hash_password(code)
    expires = datetime.utcnow() + timedelta(minutes=OTP_TTL_MINUTES)

    db.query(OtpCode).filter(
        OtpCode.user_id == user.id,
        OtpCode.purpose == "reset_password",
        OtpCode.used == False,  # noqa: E712
    ).update({"used": True})

    otp = OtpCode(
        user_id=user.id,
        code_hash=code_hash,
        purpose="reset_password",
        channel=body.channel,
        expires_at=expires,
    )
    db.add(otp)
    db.commit()

    if body.channel == "sms":
        msg = (
            f"TwinFlow: Your password reset OTP is {code}. "
            f"Valid for {OTP_TTL_MINUTES} minutes. Do not share this code."
        )
        result = send_sms(user.phone_number, msg)
    elif body.channel == "telegram":
        msg = (
            f"TwinFlow password reset code: `{code}`\n"
            f"Valid for {OTP_TTL_MINUTES} minutes. Do not share this code."
        )
        result = send_telegram(user.telegram_chat_id, msg)
    else:
        html = build_otp_email_html(user.username, code, OTP_TTL_MINUTES)
        text = build_otp_email_text(user.username, code, OTP_TTL_MINUTES)
        result = send_email(user.email, "TwinFlow Password reset code", html, text)

    if not result["sent"]:
        raise HTTPException(status_code=502, detail=f"Could not deliver OTP: {result['message']}")

    return OtpRequestResponse(
        message=f"OTP sent via {body.channel}",
        channel=body.channel,
        expires_in_seconds=OTP_TTL_MINUTES * 60,
        masked_destination=destination,
    )


@router.post("/verify-otp", response_model=MessageResponse)
def verify_otp_and_reset(body: VerifyOtpBody, db: Session = Depends(get_db)):
    """Step 2: verify OTP, then set new password."""
    user = find_user_by_identifier(db, body.identifier)
    if not user:
        raise HTTPException(status_code=404, detail="No account matches that email or phone")

    otp = (
        db.query(OtpCode)
        .filter(
            OtpCode.user_id == user.id,
            OtpCode.purpose == "reset_password",
            OtpCode.used == False,  # noqa: E712
        )
        .order_by(OtpCode.created_at.desc())
        .first()
    )
    if not otp:
        raise HTTPException(status_code=400, detail="No active OTP. Request a new one.")
    if otp.expires_at < datetime.utcnow():
        raise HTTPException(status_code=400, detail="OTP expired. Request a new one.")
    if otp.attempts >= OTP_MAX_ATTEMPTS:
        otp.used = True
        db.commit()
        raise HTTPException(status_code=400, detail="Too many wrong attempts. Request a new OTP.")

    otp.attempts += 1
    if not verify_password(body.code, otp.code_hash):
        db.commit()
        remaining = OTP_MAX_ATTEMPTS - otp.attempts
        raise HTTPException(status_code=400, detail=f"Wrong OTP. {remaining} attempts left.")

    user.password_hash = hash_password(body.new_password)
    otp.used = True
    db.commit()

    return MessageResponse(message="Password reset successfully. You can now log in.")
