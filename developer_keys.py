"""Self-service, read-only API credentials, separate from administrator users."""

from datetime import datetime, timedelta, timezone
from hashlib import sha256
import re
import secrets

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import declarative_base, relationship, sessionmaker
from werkzeug.security import check_password_hash, generate_password_hash

from logging_database import DEFAULT_LOG_DATABASE, _get_engine


Base = declarative_base()
_ready = set()


class Developer(Base):
    __tablename__ = "api_developers"
    id = Column(Integer, primary_key=True)
    username = Column(String(120), unique=True, nullable=False, index=True)
    password_hash = Column(String(512), nullable=False)
    failed_logins = Column(Integer, nullable=False, default=0)
    locked_until = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class DeveloperKey(Base):
    __tablename__ = "api_developer_keys"
    id = Column(Integer, primary_key=True)
    developer_id = Column(Integer, ForeignKey("api_developers.id"), nullable=False, index=True)
    name = Column(String(80), nullable=False)
    key_hash = Column(String(64), unique=True, nullable=False, index=True)
    prefix = Column(String(20), nullable=False)
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    revoked_at = Column(DateTime(timezone=True))
    window_started_at = Column(DateTime(timezone=True))
    window_requests = Column(Integer, nullable=False, default=0)
    developer = relationship(Developer)


def _session(database_name):
    if database_name not in _ready:
        engine = _get_engine(database_name)
        Base.metadata.create_all(engine, checkfirst=True)
        _ready.add(database_name)
    return sessionmaker(bind=_get_engine(database_name), future=True)()


def register_developer(username, password, database_name=DEFAULT_LOG_DATABASE):
    username = (username or "").strip().lower()
    if not re.fullmatch(r"[a-z0-9][a-z0-9._-]{2,59}", username):
        raise ValueError("Use 3–60 letters, numbers, dots, hyphens or underscores for the username.")
    if not isinstance(password, str) or len(password) < 12 or len(password) > 256:
        raise ValueError("The password must contain 12–256 characters.")
    with _session(database_name) as session:
        session.add(Developer(username=username, password_hash=generate_password_hash(password, method="pbkdf2:sha256")))
        try:
            session.commit()
        except IntegrityError as error:
            session.rollback()
            raise ValueError("This username is already in use.") from error
    return username


def authenticate_developer(username, password, database_name=DEFAULT_LOG_DATABASE):
    username = (username or "").strip().lower()
    with _session(database_name) as session:
        developer = session.execute(select(Developer).where(Developer.username == username).with_for_update()).scalar_one_or_none()
        if developer is None:
            return None
        now = datetime.now(timezone.utc)
        locked_until = developer.locked_until
        if locked_until and locked_until.replace(tzinfo=locked_until.tzinfo or timezone.utc) > now:
            return None
        if not isinstance(password, str) or not check_password_hash(developer.password_hash, password):
            developer.failed_logins += 1
            if developer.failed_logins >= 5:
                developer.locked_until = now + timedelta(minutes=15)
                developer.failed_logins = 0
            session.commit()
            return None
        developer.failed_logins = 0
        developer.locked_until = None
        session.commit()
        return developer.id


def list_keys(developer_id, database_name=DEFAULT_LOG_DATABASE):
    with _session(database_name) as session:
        rows = session.execute(select(DeveloperKey).where(DeveloperKey.developer_id == developer_id).order_by(DeveloperKey.id.desc())).scalars().all()
        return [{"id": row.id, "name": row.name, "prefix": row.prefix, "active": row.is_active,
                 "createdAt": row.created_at.isoformat() if row.created_at else None} for row in rows]


def create_key(developer_id, name, database_name=DEFAULT_LOG_DATABASE):
    name = (name or "").strip()
    if not 1 <= len(name) <= 80:
        raise ValueError("Key name must contain 1–80 characters.")
    with _session(database_name) as session:
        active_count = session.scalar(select(func.count(DeveloperKey.id)).where(DeveloperKey.developer_id == developer_id, DeveloperKey.is_active.is_(True)))
        if active_count >= 3:
            raise ValueError("Maximum of 3 active keys. Revoke one before creating another.")
        raw = "mb_live_" + secrets.token_urlsafe(32)
        row = DeveloperKey(developer_id=developer_id, name=name, key_hash=sha256(raw.encode()).hexdigest(), prefix=raw[:16])
        session.add(row)
        session.commit()
        return {"id": row.id, "name": row.name, "key": raw, "prefix": row.prefix}


def revoke_key(developer_id, key_id, database_name=DEFAULT_LOG_DATABASE):
    with _session(database_name) as session:
        row = session.execute(select(DeveloperKey).where(DeveloperKey.id == key_id, DeveloperKey.developer_id == developer_id, DeveloperKey.is_active.is_(True))).scalar_one_or_none()
        if row is None:
            return False
        row.is_active = False
        row.revoked_at = datetime.now(timezone.utc)
        session.commit()
        return True


def identify_key(raw, database_name=DEFAULT_LOG_DATABASE):
    if not isinstance(raw, str) or not raw.startswith("mb_live_") or len(raw) > 100:
        return None
    digest = sha256(raw.encode()).hexdigest()
    with _session(database_name) as session:
        row = session.execute(select(DeveloperKey).where(DeveloperKey.key_hash == digest, DeveloperKey.is_active.is_(True)).with_for_update()).scalar_one_or_none()
        if row is None:
            return None
        now = datetime.now(timezone.utc)
        started = row.window_started_at
        if started is None or started.replace(tzinfo=started.tzinfo or timezone.utc) <= now - timedelta(minutes=1):
            row.window_started_at = now
            row.window_requests = 0
        if row.window_requests >= 120:
            return "RATE_LIMITED"
        row.window_requests += 1
        username = row.developer.username
        session.commit()
        return username
