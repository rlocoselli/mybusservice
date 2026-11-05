from datetime import datetime, timezone
import os
from urllib.parse import quote_plus

import psycopg2
from psycopg2 import sql
from sqlalchemy import BigInteger, Boolean, Column, DateTime, Float, Integer, String, Text, case, create_engine, func, inspect, select, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import declarative_base, sessionmaker
from werkzeug.security import check_password_hash, generate_password_hash


Base = declarative_base()
DEFAULT_LOG_DATABASE = "mybus"
DEFAULT_APPLICATION_USER = "meubusao"
PASSWORD_PROCEDURE_NAME = "assign_app_user_password"
REQUIRED_TABLES = {"application_request_logs", "line_utilization_logs", "app_users"}
_ENGINE_CACHE = {}
_SESSION_FACTORY_CACHE = {}
_DATABASE_STATUS = {}


class ApplicationRequestLog(Base):
    __tablename__ = "application_request_logs"

    id = Column(BigInteger, primary_key=True)
    request_id = Column(String(36), nullable=False, unique=True, index=True)
    application_name = Column(String(120))
    endpoint = Column(String(255))
    method = Column(String(10), nullable=False)
    path = Column(String(500), nullable=False)
    city = Column(String(120), index=True)
    route_id = Column(String(120), index=True)
    line_name = Column(String(255), index=True)
    direction = Column(String(255))
    stop_id = Column(String(120))
    query_params = Column(JSONB)
    request_payload = Column(JSONB)
    response_status = Column(Integer, nullable=False)
    duration_ms = Column(Float)
    client_ip = Column(String(120))
    user_agent = Column(Text)
    token_subject = Column(String(255))
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), index=True)


class LineUtilizationLog(Base):
    __tablename__ = "line_utilization_logs"

    id = Column(BigInteger, primary_key=True)
    application_name = Column(String(120))
    city = Column(String(120), nullable=False, index=True)
    route_id = Column(String(120), index=True)
    line_name = Column(String(255), index=True)
    direction = Column(String(255))
    trip_id = Column(String(120))
    stop_id = Column(String(120))
    vehicle_id = Column(String(120))
    boardings = Column(Integer)
    alightings = Column(Integer)
    occupancy = Column(Integer)
    occupancy_rate = Column(Float)
    utilization_source = Column(String(120))
    observed_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), index=True)
    extra_data = Column(JSONB)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), index=True)


class AppUser(Base):
    __tablename__ = "app_users"

    id = Column(BigInteger, primary_key=True)
    username = Column(String(120), nullable=False, unique=True, index=True)
    display_name = Column(String(255))
    password_hash = Column(Text)
    is_active = Column(Boolean, nullable=False, server_default=text("true"))
    password_updated_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())


def _get_database_settings(database_name):
    host = os.getenv("SERVER")
    user = os.getenv("DB_USER") or os.getenv("USER")
    password = os.getenv("MOT") or os.getenv("DB_PASSWORD")
    port = os.getenv("DB_PORT") or os.getenv("PGPORT") or "5432"

    if not host or not user or not password:
        raise RuntimeError("Missing PostgreSQL connection environment variables: SERVER, USER/DB_USER and MOT/DB_PASSWORD are required")

    return {
        "host": host,
        "database": database_name,
        "user": user,
        "password": password,
        "port": port,
    }


def _build_database_url(database_name):
    settings = _get_database_settings(database_name)
    return (
        "postgresql+psycopg2://"
        f"{quote_plus(settings['user'])}:{quote_plus(settings['password'])}"
        f"@{settings['host']}:{settings['port']}/{settings['database']}"
    )


def _get_engine(database_name=DEFAULT_LOG_DATABASE, refresh=False):
    if refresh or database_name not in _ENGINE_CACHE:
        if refresh and database_name in _ENGINE_CACHE:
            _ENGINE_CACHE[database_name].dispose()
        _ENGINE_CACHE[database_name] = create_engine(_build_database_url(database_name), future=True, pool_pre_ping=True)

    return _ENGINE_CACHE[database_name]


def _get_session_factory(database_name=DEFAULT_LOG_DATABASE, refresh=False):
    if refresh or database_name not in _SESSION_FACTORY_CACHE:
        _SESSION_FACTORY_CACHE[database_name] = sessionmaker(bind=_get_engine(database_name, refresh=refresh), future=True)

    return _SESSION_FACTORY_CACHE[database_name]


def _normalize_datetime(value):
    if value in (None, ""):
        return None

    if isinstance(value, datetime):
        return value

    if isinstance(value, str):
        candidate = value.strip()
        if not candidate:
            return None

        try:
            return datetime.fromisoformat(candidate.replace("Z", "+00:00"))
        except ValueError as err:
            raise ValueError("Datetime values must be ISO 8601 strings") from err

    raise ValueError("Datetime values must be datetime objects or ISO 8601 strings")


def _serialize_datetime(value):
    return value.isoformat() if value else None


def _ensure_password_procedure(engine):
    procedure_sql = text(
        f"""
        CREATE OR REPLACE PROCEDURE {PASSWORD_PROCEDURE_NAME}(p_username VARCHAR, p_password_hash TEXT)
        LANGUAGE plpgsql
        AS $$
        BEGIN
            UPDATE app_users
            SET password_hash = p_password_hash,
                password_updated_at = NOW(),
                updated_at = NOW()
            WHERE username = p_username;

            IF NOT FOUND THEN
                INSERT INTO app_users (username, password_hash, password_updated_at, created_at, updated_at)
                VALUES (p_username, p_password_hash, NOW(), NOW(), NOW());
            END IF;
        END;
        $$;
        """
    )

    with engine.begin() as connection:
        connection.execute(procedure_sql)


def _seed_default_users(engine):
    with engine.begin() as connection:
        result = connection.execute(
            text(
                """
                INSERT INTO app_users (username, display_name, created_at, updated_at)
                VALUES (:username, :display_name, NOW(), NOW())
                ON CONFLICT (username) DO UPDATE
                SET display_name = EXCLUDED.display_name,
                    updated_at = NOW()
                RETURNING username
                """
            ),
            {"username": DEFAULT_APPLICATION_USER, "display_name": "Meu Busao"},
        )
        return [row.username for row in result]


def is_logging_database_ready(database_name=DEFAULT_LOG_DATABASE):
    if database_name in _DATABASE_STATUS:
        return _DATABASE_STATUS[database_name]

    try:
        inspector = inspect(_get_engine(database_name))
        ready = REQUIRED_TABLES.issubset(set(inspector.get_table_names()))
    except Exception:
        ready = False

    _DATABASE_STATUS[database_name] = ready
    return ready


def ensure_logging_database(database_name=DEFAULT_LOG_DATABASE):
    admin_settings = _get_database_settings("postgres")
    database_created = False

    connection = psycopg2.connect(
        host=admin_settings["host"],
        database=admin_settings["database"],
        user=admin_settings["user"],
        password=admin_settings["password"],
        port=admin_settings["port"],
    )

    connection.autocommit = True

    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1 FROM pg_database WHERE datname = %s", (database_name,))
            if cursor.fetchone() is None:
                cursor.execute(sql.SQL("CREATE DATABASE {}\n").format(sql.Identifier(database_name)))
                database_created = True
    finally:
        connection.close()

    engine = _get_engine(database_name, refresh=True)
    _get_session_factory(database_name, refresh=True)
    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())

    Base.metadata.create_all(engine)
    _ensure_password_procedure(engine)
    ensured_users = _seed_default_users(engine)

    inspector = inspect(engine)
    available_tables = sorted(inspector.get_table_names())
    created_tables = sorted(set(available_tables) - existing_tables)

    _DATABASE_STATUS[database_name] = REQUIRED_TABLES.issubset(set(available_tables))

    return {
        "database_created": database_created,
        "created_tables": created_tables,
        "available_tables": available_tables,
        "procedures": [PASSWORD_PROCEDURE_NAME],
        "users": ensured_users,
    }


def create_application_request_log(payload, database_name=DEFAULT_LOG_DATABASE):
    session = _get_session_factory(database_name)()

    try:
        log_entry = ApplicationRequestLog(
            request_id=payload["request_id"],
            application_name=payload.get("application_name"),
            endpoint=payload.get("endpoint"),
            method=payload["method"],
            path=payload["path"],
            city=payload.get("city"),
            route_id=payload.get("route_id"),
            line_name=payload.get("line_name"),
            direction=payload.get("direction"),
            stop_id=payload.get("stop_id"),
            query_params=payload.get("query_params"),
            request_payload=payload.get("request_payload"),
            response_status=payload["response_status"],
            duration_ms=payload.get("duration_ms"),
            client_ip=payload.get("client_ip"),
            user_agent=payload.get("user_agent"),
            token_subject=payload.get("token_subject"),
        )
        session.add(log_entry)
        session.commit()
        session.refresh(log_entry)
        return {"id": log_entry.id, "request_id": log_entry.request_id}
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def create_line_utilization_log(payload, database_name=DEFAULT_LOG_DATABASE):
    session = _get_session_factory(database_name)()

    try:
        log_entry = LineUtilizationLog(
            application_name=payload.get("application_name"),
            city=payload["city"],
            route_id=payload.get("route_id"),
            line_name=payload.get("line_name"),
            direction=payload.get("direction"),
            trip_id=payload.get("trip_id"),
            stop_id=payload.get("stop_id"),
            vehicle_id=payload.get("vehicle_id"),
            boardings=payload.get("boardings"),
            alightings=payload.get("alightings"),
            occupancy=payload.get("occupancy"),
            occupancy_rate=payload.get("occupancy_rate"),
            utilization_source=payload.get("utilization_source"),
            observed_at=_normalize_datetime(payload.get("observed_at")) or datetime.now(timezone.utc),
            extra_data=payload.get("extra_data"),
        )
        session.add(log_entry)
        session.commit()
        session.refresh(log_entry)
        return {
            "id": log_entry.id,
            "created_at": _serialize_datetime(log_entry.created_at),
            "observed_at": _serialize_datetime(log_entry.observed_at),
        }
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def list_app_users(database_name=DEFAULT_LOG_DATABASE):
    session = _get_session_factory(database_name)()

    try:
        rows = session.execute(
            select(AppUser).order_by(AppUser.username.asc())
        ).scalars().all()

        return [
            {
                "username": row.username,
                "displayName": row.display_name,
                "isActive": row.is_active,
                "hasPassword": bool(row.password_hash),
                "passwordUpdatedAt": _serialize_datetime(row.password_updated_at),
                "createdAt": _serialize_datetime(row.created_at),
                "updatedAt": _serialize_datetime(row.updated_at),
            }
            for row in rows
        ]
    finally:
        session.close()


def authenticate_app_user(username, plain_password, database_name=DEFAULT_LOG_DATABASE):
    if not username or not username.strip():
        return None
    if not plain_password:
        return None

    session = _get_session_factory(database_name)()

    try:
        row = session.execute(
            select(AppUser).where(AppUser.username == username.strip())
        ).scalar_one_or_none()

        if not row or not row.is_active or not row.password_hash:
            return None

        if not check_password_hash(row.password_hash, plain_password):
            return None

        return {
            "username": row.username,
            "displayName": row.display_name,
            "isActive": row.is_active,
        }
    finally:
        session.close()


def assign_password_to_user(username, plain_password, database_name=DEFAULT_LOG_DATABASE):
    if not username or not username.strip():
        raise ValueError("username is required")
    if not plain_password or len(plain_password) < 8:
        raise ValueError("password must contain at least 8 characters")

    password_hash = generate_password_hash(plain_password, method="pbkdf2:sha256", salt_length=16)
    engine = _get_engine(database_name)

    with engine.begin() as connection:
        connection.execute(
            text(f"CALL {PASSWORD_PROCEDURE_NAME}(:username, :password_hash)"),
            {"username": username.strip(), "password_hash": password_hash},
        )

    return {"username": username.strip(), "passwordHashAlgorithm": "pbkdf2:sha256"}


def get_line_utilization_summary(database_name=DEFAULT_LOG_DATABASE, city=None, route_id=None, start_at=None, end_at=None):
    session = _get_session_factory(database_name)()

    try:
        statement = select(
            LineUtilizationLog.city.label("city"),
            LineUtilizationLog.route_id.label("route_id"),
            LineUtilizationLog.line_name.label("line_name"),
            LineUtilizationLog.direction.label("direction"),
            func.count(LineUtilizationLog.id).label("event_count"),
            func.count(func.distinct(LineUtilizationLog.trip_id)).label("observed_trip_count"),
            func.count(func.distinct(LineUtilizationLog.vehicle_id)).label("observed_vehicle_count"),
            func.count(LineUtilizationLog.boardings).label("boarding_sample_count"),
            func.count(LineUtilizationLog.alightings).label("alighting_sample_count"),
            func.count(LineUtilizationLog.occupancy).label("occupancy_sample_count"),
            func.coalesce(func.sum(LineUtilizationLog.boardings), 0).label("total_boardings"),
            func.coalesce(func.sum(LineUtilizationLog.alightings), 0).label("total_alightings"),
            func.avg(LineUtilizationLog.occupancy).label("avg_occupancy"),
            func.avg(LineUtilizationLog.occupancy_rate).label("avg_occupancy_rate"),
            func.max(LineUtilizationLog.observed_at).label("last_observed_at"),
        ).group_by(
            LineUtilizationLog.city,
            LineUtilizationLog.route_id,
            LineUtilizationLog.line_name,
            LineUtilizationLog.direction,
        ).order_by(
            func.count(LineUtilizationLog.id).desc(),
            LineUtilizationLog.city.asc(),
            LineUtilizationLog.route_id.asc(),
        )

        if city:
            statement = statement.where(LineUtilizationLog.city == city)
        if route_id:
            statement = statement.where(LineUtilizationLog.route_id == route_id)

        start_at_value = _normalize_datetime(start_at)
        end_at_value = _normalize_datetime(end_at)

        if start_at_value:
            statement = statement.where(LineUtilizationLog.observed_at >= start_at_value)
        if end_at_value:
            statement = statement.where(LineUtilizationLog.observed_at <= end_at_value)

        rows = session.execute(statement).all()

        return [
            {
                "city": row.city,
                "routeId": row.route_id,
                "lineName": row.line_name,
                "direction": row.direction,
                "eventCount": row.event_count,
                "observedTripCount": row.observed_trip_count,
                "observedVehicleCount": row.observed_vehicle_count,
                "boardingSampleCount": row.boarding_sample_count,
                "alightingSampleCount": row.alighting_sample_count,
                "occupancySampleCount": row.occupancy_sample_count,
                "totalBoardings": int(row.total_boardings or 0),
                "totalAlightings": int(row.total_alightings or 0),
                "averageOccupancy": float(row.avg_occupancy) if row.avg_occupancy is not None else None,
                "averageOccupancyRate": float(row.avg_occupancy_rate) if row.avg_occupancy_rate is not None else None,
                "lastObservedAt": _serialize_datetime(row.last_observed_at),
            }
            for row in rows
        ]
    finally:
        session.close()


def get_application_usage_summary(database_name=DEFAULT_LOG_DATABASE, city=None, route_id=None, start_at=None, end_at=None):
    session = _get_session_factory(database_name)()

    try:
        statement = select(
            ApplicationRequestLog.city.label("city"),
            ApplicationRequestLog.route_id.label("route_id"),
            ApplicationRequestLog.endpoint.label("endpoint"),
            ApplicationRequestLog.method.label("method"),
            func.count(ApplicationRequestLog.id).label("request_count"),
            func.avg(ApplicationRequestLog.duration_ms).label("avg_duration_ms"),
            func.max(ApplicationRequestLog.created_at).label("last_request_at"),
            func.sum(case((ApplicationRequestLog.response_status < 400, 1), else_=0)).label("success_count"),
            func.sum(case((ApplicationRequestLog.response_status >= 400, 1), else_=0)).label("error_count"),
        ).group_by(
            ApplicationRequestLog.city,
            ApplicationRequestLog.route_id,
            ApplicationRequestLog.endpoint,
            ApplicationRequestLog.method,
        ).order_by(
            func.count(ApplicationRequestLog.id).desc(),
            ApplicationRequestLog.endpoint.asc(),
        )

        if city:
            statement = statement.where(ApplicationRequestLog.city == city)
        if route_id:
            statement = statement.where(ApplicationRequestLog.route_id == route_id)

        start_at_value = _normalize_datetime(start_at)
        end_at_value = _normalize_datetime(end_at)

        if start_at_value:
            statement = statement.where(ApplicationRequestLog.created_at >= start_at_value)
        if end_at_value:
            statement = statement.where(ApplicationRequestLog.created_at <= end_at_value)

        rows = session.execute(statement).all()

        return [
            {
                "city": row.city,
                "routeId": row.route_id,
                "endpoint": row.endpoint,
                "method": row.method,
                "requestCount": row.request_count,
                "averageDurationMs": float(row.avg_duration_ms) if row.avg_duration_ms is not None else None,
                "successCount": int(row.success_count or 0),
                "errorCount": int(row.error_count or 0),
                "lastRequestAt": _serialize_datetime(row.last_request_at),
            }
            for row in rows
        ]
    finally:
        session.close()


def get_application_usage_sources(database_name=DEFAULT_LOG_DATABASE, city=None, route_id=None, start_at=None, end_at=None):
    """Group requests by client type, preferring the explicit client header."""
    session = _get_session_factory(database_name)()
    try:
        client = func.lower(func.coalesce(ApplicationRequestLog.application_name, ""))
        agent = func.lower(func.coalesce(ApplicationRequestLog.user_agent, ""))
        source = case(
            (client.op("~")("web|website|browser|site"), "web"),
            (client.op("~")("mobile|android|ios|iphone|ipad|flutter|react.native"), "mobile"),
            (agent.op("~")("okhttp|dart|cfnetwork|alamofire|react.native|expo"), "mobile"),
            (agent.op("~")("mozilla|chrome|safari|firefox|edg/"), "web"),
            else_="unknown",
        )
        statement = select(
            source.label("source"),
            func.count(ApplicationRequestLog.id).label("request_count"),
            func.sum(case((ApplicationRequestLog.response_status >= 400, 1), else_=0)).label("error_count"),
        ).group_by(source)

        if city:
            statement = statement.where(ApplicationRequestLog.city == city)
        if route_id:
            statement = statement.where(ApplicationRequestLog.route_id == route_id)
        start_at_value = _normalize_datetime(start_at)
        end_at_value = _normalize_datetime(end_at)
        if start_at_value:
            statement = statement.where(ApplicationRequestLog.created_at >= start_at_value)
        if end_at_value:
            statement = statement.where(ApplicationRequestLog.created_at <= end_at_value)

        return [
            {"source": row.source, "requestCount": int(row.request_count), "errorCount": int(row.error_count or 0)}
            for row in session.execute(statement).all()
        ]
    finally:
        session.close()


def get_application_usage_timeline(database_name=DEFAULT_LOG_DATABASE, city=None, route_id=None, start_at=None, end_at=None):
    session = _get_session_factory(database_name)()

    try:
        bucket = func.date_trunc("day", ApplicationRequestLog.created_at)
        statement = select(
            bucket.label("bucket"),
            func.count(ApplicationRequestLog.id).label("request_count"),
            func.avg(ApplicationRequestLog.duration_ms).label("avg_duration_ms"),
            func.sum(case((ApplicationRequestLog.response_status >= 400, 1), else_=0)).label("error_count"),
        ).group_by(bucket).order_by(bucket.asc())

        if city:
            statement = statement.where(ApplicationRequestLog.city == city)
        if route_id:
            statement = statement.where(ApplicationRequestLog.route_id == route_id)

        start_at_value = _normalize_datetime(start_at)
        end_at_value = _normalize_datetime(end_at)

        if start_at_value:
            statement = statement.where(ApplicationRequestLog.created_at >= start_at_value)
        if end_at_value:
            statement = statement.where(ApplicationRequestLog.created_at <= end_at_value)

        rows = session.execute(statement).all()

        return [
            {
                "bucket": _serialize_datetime(row.bucket),
                "requestCount": row.request_count,
                "averageDurationMs": float(row.avg_duration_ms) if row.avg_duration_ms is not None else None,
                "errorCount": int(row.error_count or 0),
            }
            for row in rows
        ]
    finally:
        session.close()


def get_line_utilization_timeline(database_name=DEFAULT_LOG_DATABASE, city=None, route_id=None, start_at=None, end_at=None):
    session = _get_session_factory(database_name)()

    try:
        bucket = func.date_trunc("day", LineUtilizationLog.observed_at)
        statement = select(
            bucket.label("bucket"),
            func.count(LineUtilizationLog.id).label("event_count"),
            func.coalesce(func.sum(LineUtilizationLog.boardings), 0).label("total_boardings"),
            func.coalesce(func.sum(LineUtilizationLog.alightings), 0).label("total_alightings"),
            func.avg(LineUtilizationLog.occupancy).label("avg_occupancy"),
        ).group_by(bucket).order_by(bucket.asc())

        if city:
            statement = statement.where(LineUtilizationLog.city == city)
        if route_id:
            statement = statement.where(LineUtilizationLog.route_id == route_id)

        start_at_value = _normalize_datetime(start_at)
        end_at_value = _normalize_datetime(end_at)

        if start_at_value:
            statement = statement.where(LineUtilizationLog.observed_at >= start_at_value)
        if end_at_value:
            statement = statement.where(LineUtilizationLog.observed_at <= end_at_value)

        rows = session.execute(statement).all()

        return [
            {
                "bucket": _serialize_datetime(row.bucket),
                "eventCount": row.event_count,
                "totalBoardings": int(row.total_boardings or 0),
                "totalAlightings": int(row.total_alightings or 0),
                "averageOccupancy": float(row.avg_occupancy) if row.avg_occupancy is not None else None,
            }
            for row in rows
        ]
    finally:
        session.close()
