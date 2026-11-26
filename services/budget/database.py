"""SQL Server connection management for the budget service."""

import os
from urllib.parse import urlparse, unquote

import pymssql
from flask import g


def get_connection_config():
    """Read database configuration from the environment."""

    database_url = os.getenv("DATABASE_URL")

    if database_url:
        parsed = urlparse(database_url)

        if parsed.scheme not in ("mssql", "mssql+pymssql"):
            raise ValueError("Invalid DATABASE_URL scheme")

        if not all([
            parsed.hostname,
            parsed.username,
            parsed.password,
            parsed.path.strip("/")
        ]):
            raise ValueError("Incomplete DATABASE_URL")

        return {
            "server": parsed.hostname,
            "port": parsed.port or 1433,
            "user": unquote(parsed.username),
            "password": unquote(parsed.password),
            "database": unquote(parsed.path.lstrip("/")),
        }

    return {
        "server": os.getenv("DB_HOST", "sqlserver"),
        "port": int(os.getenv("DB_PORT", "1433")),
        "user": os.getenv("DB_USER", "budget_user"),
        "password": os.environ["DB_PASSWORD"],
        "database": os.getenv("DB_NAME", "budget_db"),
    }


def get_db():
    """Get the database connection for the current request."""

    if "db" not in g:
        g.db = pymssql.connect(
            **get_connection_config(),
            login_timeout=5,
            timeout=10,
            as_dict=True,
            autocommit=False,
        )

    return g.db


def close_db(error=None):
    """Close the database connection after each request."""

    db = g.pop("db", None)

    if db is not None:
        db.close()