"""Initialize already-provisioned Azure SQL databases with contained users.

This path is deliberately separate from the Docker Compose SQL Server path.
It connects independently to each database as its administrator, never uses
``sa``, ``CREATE LOGIN`` or ``USE``, and never shares application passwords.
"""

from __future__ import annotations

import os
import re

from dotenv import load_dotenv

from sql_connection import connect_with_retry, parse_database_url


IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
SERVICES = (
    ("BUDGET", "AZURE_BUDGET_ADMIN_DATABASE_URL", "AZURE_BUDGET_DB_USER", "AZURE_BUDGET_DB_PASSWORD"),
    ("BILLS", "AZURE_BILLS_ADMIN_DATABASE_URL", "AZURE_BILLS_DB_USER", "AZURE_BILLS_DB_PASSWORD"),
)


def quote_identifier(value: str) -> str:
    if not IDENTIFIER.fullmatch(value):
        raise ValueError("Invalid SQL identifier")
    return f"[{value}]"


def create_or_verify_user(connection, username: str, password: str) -> None:
    """Create one contained user and grant only its own database roles."""

    quoted_user = quote_identifier(username)
    cursor = connection.cursor()
    try:
        cursor.execute("SELECT DATABASE_PRINCIPAL_ID(%s)", (username,))
        exists = cursor.fetchone()[0] is not None
        if not exists:
            escaped_password = password.replace("'", "''")
            cursor.execute(
                f"CREATE USER {quoted_user} WITH PASSWORD = N'{escaped_password}'"
            )

        for role in ("db_ddladmin", "db_datareader", "db_datawriter"):
            cursor.execute("SELECT IS_ROLEMEMBER(%s, %s)", (role, username))
            if cursor.fetchone()[0] != 1:
                cursor.execute(
                    f"ALTER ROLE {quote_identifier(role)} ADD MEMBER {quoted_user}"
                )
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        cursor.close()


def initialize_service(admin_url: str, username: str, password: str) -> None:
    config = parse_database_url(admin_url)
    connection = connect_with_retry(config, autocommit=False)
    try:
        create_or_verify_user(connection, username, password)
    finally:
        connection.close()


def initialize_azure_databases() -> None:
    load_dotenv()
    for _, admin_url_key, user_key, password_key in SERVICES:
        admin_url = os.environ[admin_url_key]
        username = os.environ[user_key]
        password = os.environ[password_key]
        initialize_service(admin_url, username, password)
        print(f"[{user_key}] Azure SQL contained user verified.")


if __name__ == "__main__":
    initialize_azure_databases()
