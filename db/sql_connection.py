"""Shared Azure/local SQL connection helpers for administrative scripts."""

from __future__ import annotations

import os
import time
from urllib.parse import parse_qs, unquote, urlparse

import pymssql


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
    """Parse an mssql URL and require encryption for explicit Azure TLS URLs."""

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


def is_transient_database_error(error: BaseException) -> bool:
    text = " ".join(str(value) for value in getattr(error, "args", ())) + " " + str(error)
    text = text.upper()
    if "18456" in text or "LOGIN FAILED" in text or "INVALID OBJECT" in text:
        return False
    return any(code in text for code in TRANSIENT_ERROR_CODES)


def connect_with_retry(
    config: dict[str, object], *, as_dict: bool = False, autocommit: bool = False
):
    """Connect with bounded retries for transient establishment failures only."""

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
                as_dict=as_dict,
                autocommit=autocommit,
            )
        except (pymssql.OperationalError, pymssql.InterfaceError) as error:
            last_error = error
            if attempt == attempts - 1 or not is_transient_database_error(error):
                raise
            time.sleep(0.25 * (2**attempt))
    raise RuntimeError("Database connection failed") from last_error
