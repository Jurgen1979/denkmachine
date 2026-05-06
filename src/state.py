"""database-initialisatie en sessiebeheer voor denkmachine."""

from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

# absoluut pad naar de database-file, onafhankelijk van werkdirectory
_BASE_DIR = Path(__file__).parent.parent
_DB_PATH = _BASE_DIR / "data" / "denkmachine.db"
_DB_PATH.parent.mkdir(parents=True, exist_ok=True)

DATABASE_URL = f"sqlite:///{_DB_PATH}"

engine = create_engine(DATABASE_URL, echo=False, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)


def init_db() -> None:
    """Maak alle tabellen aan als ze nog niet bestaan."""
    from src.models import Base

    Base.metadata.create_all(engine)


def get_session() -> Session:
    """Geef een nieuwe database-sessie terug. Sluit zelf af na gebruik."""
    return SessionLocal()
