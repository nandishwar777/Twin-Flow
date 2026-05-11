"""TwinFlow FastAPI entry point. Run with: python main.py"""
import os
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware
from starlette.requests import Request

from database import Base, engine
import models  # noqa: F401  - register models with Base
import auth as auth_module
import productivity as productivity_module
import schedule as schedule_module
import dashboard as dashboard_module
import notifications_routes
import telegram_routes

load_dotenv(Path(__file__).resolve().parent / ".env")

SESSION_SECRET = os.getenv("SESSION_SECRET", "dev-only-secret-change-me-please-32chars")

app = FastAPI(
    title="TwinFlow API",
    version="1.1.0",
    description="Digital Twin AI Personal Productivity & Scheduling System",
)

app.add_middleware(
    SessionMiddleware,
    secret_key=SESSION_SECRET,
    session_cookie="twinflow_session",
    same_site="lax",
    https_only=False,
    max_age=60 * 60 * 24 * 14,  # 14 days
)


@app.on_event("startup")
def on_startup():
    # 1. Create any missing tables
    Base.metadata.create_all(bind=engine)

    # 2. Apply additive migrations (add new columns to existing tables)
    from db_migrate import run_migrations
    run_migrations()

    # 3. Trigger ML model load (and train if missing)
    from ml.predict import _load_bundle
    _load_bundle()

    # 4. Start the background scheduler
    from scheduler_jobs import start_scheduler
    start_scheduler()

    # 5. On startup, send any overdue weekly reports immediately
    from notifications import catch_up_weekly_if_overdue
    try:
        catch_up_weekly_if_overdue()
    except Exception as e:
        print(f"[startup] Weekly catch-up failed: {e}")

    print("[twinflow] Startup complete. ML model ready, DB tables ensured, scheduler running.")


@app.on_event("shutdown")
def on_shutdown():
    from scheduler_jobs import shutdown_scheduler
    shutdown_scheduler()


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    return JSONResponse(
        status_code=400,
        content={"detail": "Validation error", "errors": exc.errors()},
    )


# API routers
app.include_router(auth_module.router)
app.include_router(productivity_module.router)
app.include_router(schedule_module.router)
app.include_router(dashboard_module.router)
app.include_router(notifications_routes.router)
app.include_router(telegram_routes.router)


@app.get("/api/healthz")
def healthz():
    return {"status": "ok"}


# ---- Static frontend ----
FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"

if FRONTEND_DIR.exists():
    app.mount("/css", StaticFiles(directory=FRONTEND_DIR / "css"), name="css")
    app.mount("/js", StaticFiles(directory=FRONTEND_DIR / "js"), name="js")

    @app.get("/")
    def root():
        return FileResponse(FRONTEND_DIR / "index.html")

    @app.get("/{page}.html")
    def page(page: str):
        target = FRONTEND_DIR / f"{page}.html"
        if target.exists():
            return FileResponse(target)
        return JSONResponse({"detail": "Not found"}, status_code=404)


if __name__ == "__main__":
    import uvicorn
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "8000"))
    uvicorn.run("main:app", host=host, port=port, reload=True)
