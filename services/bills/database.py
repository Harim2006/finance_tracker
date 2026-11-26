
"""SQL Server connection management for the bills service."""

import os

import pymssql
from flask import g


def get_db():
    """Get the database connection for the current request."""

    if "db" not in g:
        g.db = pymssql.connect(
            server=os.getenv("DB_HOST", "sqlserver"),
            port=os.getenv("DB_PORT", "1433"),
            user=os.getenv("DB_USER", "bills_user"),
            password=os.environ["DB_PASSWORD"],
            database=os.getenv("DB_NAME", "bills_db"),
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
