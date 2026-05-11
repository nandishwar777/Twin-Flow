"""Database setup using SQLAlchemy. Defaults to SQLite for zero-config setup."""
import os
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

load_dotenv(Path(__file__).resolve().parent / ".env")

# Default to a local SQLite file — no PostgreSQL or password needed.
# To use PostgreSQL instead, set DATABASE_URL in .env, e.g.:
#   DATABASE_URL=postgresql://postgres:password@localhost:5432/twinflow
DEFAULT_SQLITE_PATH = Path(__file__).resolve().parent / "twinflow.db"
DATABASE_URL = os.getenv("DATABASE_URL") or f"sqlite:///{DEFAULT_SQLITE_PATH}"

connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(DATABASE_URL, pool_pre_ping=True, connect_args=connect_args)
print(f"[twinflow] Using database: {DATABASE_URL}")
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    """FastAPI dependency that yields a DB session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
