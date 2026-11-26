"""SQL Server connection management for the bills service."""

from __future__ import annotations

import os
import time
from urllib.parse import parse_qs, unquote, urlparse

import pymssql
from flask import g


TRANSIENT_ERROR_CODES = {
    "08S01", "10053", "10054", "10060", "10928", "10929",
    "20002", "20003", "40197", "40501", "40613",
}


def _as_bool(value: str, name: str) -> bool:
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"Invalid {name} setting")


def parse_database_url(database_url: str) -> dict[str, object]:
    """Parse an mssql URL without logging or exposing its password."""

    parsed = urlparse(database_url)
    if parsed.scheme not in ("mssql", "mssql+pymssql"):
        raise ValueError("Invalid DATABASE_URL scheme")
    if not all((parsed.hostname, parsed.username, parsed.password, parsed.path.strip("/"))):
        raise ValueError("Incomplete DATABASE_URL")

    query = parse_qs(parsed.query, keep_blank_values=True)
    encrypt = _as_bool(query.get("encrypt", ["false"])[-1], "encrypt")
    trust_server_certificate = _as_bool(
        query.get("trustservercertificate", ["false"])[-1],
        "trustservercertificate",
    )
    if encrypt and trust_server_certificate:
        raise ValueError("DATABASE_URL must not bypass certificate verification")

    config: dict[str, object] = {
        "server": parsed.hostname,
        "port": parsed.port or 1433,
        "user": unquote(parsed.username),
        "password": unquote(parsed.password),
        "database": unquote(parsed.path.lstrip("/")),
    }
    if encrypt:
        config["encryption"] = "required"
    return config


def get_connection_config() -> dict[str, object]:
    """Read the Azure-first contract, with a Compose-compatible fallback."""

    database_url = os.getenv("DATABASE_URL")
    if database_url:
        return parse_database_url(database_url)
    return {
        "server": os.getenv("DB_HOST", "sqlserver"),
        "port": int(os.getenv("DB_PORT", "1433")),
        "user": os.getenv("DB_USER", "bills_user"),
        "password": os.environ["DB_PASSWORD"],
        "database": os.getenv("DB_NAME", "bills_db"),
    }


def _error_text(error: BaseException) -> str:
    return " ".join(str(value) for value in getattr(error, "args", ())) + " " + str(error)


def is_transient_database_error(error: BaseException) -> bool:
    """Return true only for known connection/service transient failures."""

    text = _error_text(error).upper()
    if "18456" in text or "LOGIN FAILED" in text or "INVALID OBJECT" in text:
        return False
    return any(code in text for code in TRANSIENT_ERROR_CODES)


def connect_with_retry(config: dict[str, object] | None = None):
    """Establish a bounded connection retry for transient failures only."""

    config = config or get_connection_config()
    attempts = max(1, int(os.getenv("DB_CONNECT_ATTEMPTS", "4")))
    login_timeout = max(1, int(os.getenv("DB_LOGIN_TIMEOUT", "5")))
    query_timeout = max(1, int(os.getenv("DB_QUERY_TIMEOUT", "10")))
    last_error: BaseException | None = None
    for attempt in range(attempts):
        try:
            return pymssql.connect(
                **config,
                login_timeout=login_timeout,
                timeout=query_timeout,
                as_dict=True,
                autocommit=False,
            )
        except (pymssql.OperationalError, pymssql.InterfaceError) as error:
            last_error = error
            if attempt == attempts - 1 or not is_transient_database_error(error):
                raise
            time.sleep(0.25 * (2**attempt))
    raise RuntimeError("Database connection failed") from last_error


def get_db():
    """Get the database connection for the current request."""

    if "db" not in g:
        g.db = connect_with_retry()
    return g.db


def close_db(error=None):
    """Close the database connection after each request."""

    db = g.pop("db", None)
    if db is not None:
        db.close()
