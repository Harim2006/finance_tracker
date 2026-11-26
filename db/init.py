"""Initialize SQL Server databases and service-specific users."""

import time
import os
import re
from pathlib import Path

import pymssql
from dotenv import load_dotenv


ROOT = Path(__file__).resolve().parent.parent

load_dotenv(ROOT / ".env")

HOST = os.getenv("DB_HOST", "127.0.0.1")
PORT = os.getenv("DB_PORT", "1433")


SERVICES = [
    ("budget_db", "budget_user", "BUDGET_DB_PASSWORD"),
    ("bills_db", "bills_user", "BILLS_DB_PASSWORD"),
]


def _connect_once(database="master"):
    return pymssql.connect(
        server=HOST,
        port=PORT,
        user="sa",
        password=os.environ["MSSQL_SA_PASSWORD"],
        database=database,
        login_timeout=15,
        timeout=60,
        autocommit=True,
    )

def connect(database="master"):
    """Retry database connections during SQL Server startup."""

    max_attempts = 10

    for attempt in range(1, max_attempts + 1):
        try:
            return _connect_once(database)

        except pymssql.OperationalError:
            if attempt == max_attempts:
                raise

            print(
                f"[{database}] Connection not ready. "
                f"Retrying ({attempt}/{max_attempts})...",
                flush=True,
            )

            time.sleep(3)

def initialize_databases():
    sql = (ROOT / "db" / "init.sql").read_text(
        encoding="utf-8-sig"
    )

    batches = re.split(
        r"^\s*GO\s*$",
        sql,
        flags=re.MULTILINE | re.IGNORECASE,
    )

    connection = connect()

    try:
        cursor = connection.cursor()

        for batch in batches:
            if batch.strip():
                cursor.execute(batch)

        print("Databases initialized.")

    finally:
        connection.close()


def initialize_user(database, username, password_key):
    password = os.environ[password_key]
    escaped_password = password.replace("'", "''")

    connection = connect()

    try:
        cursor = connection.cursor()

        cursor.execute(
            "SELECT SUSER_ID(%s)",
            (username,),
        )

        if cursor.fetchone()[0] is None:
            cursor.execute(
                f"CREATE LOGIN [{username}] "
                f"WITH PASSWORD = N'{escaped_password}', "
                f"DEFAULT_DATABASE = [{database}]"
            )

            print(f"Created login: {username}")
        else:
            print(f"Login already exists: {username}")

    finally:
        connection.close()

    connection = connect(database)

    try:
        cursor = connection.cursor()

        cursor.execute(
            "SELECT USER_ID(%s)",
            (username,),
        )

        if cursor.fetchone()[0] is None:
            cursor.execute(
                f"CREATE USER [{username}] "
                f"FOR LOGIN [{username}]"
            )

        for role in ("db_datareader", "db_datawriter"):
            cursor.execute(
                "SELECT IS_ROLEMEMBER(%s, %s)",
                (role, username),
            )

            if cursor.fetchone()[0] != 1:
                cursor.execute(
                    f"ALTER ROLE [{role}] "
                    f"ADD MEMBER [{username}]"
                )

        print(f"[{database}] Permissions configured.")

    finally:
        connection.close()

    # Verify the service can authenticate independently.
    service_connection = pymssql.connect(
        server=HOST,
        port=PORT,
        user=username,
        password=password,
        database=database,
        login_timeout=5,
        timeout=10,
    )

    service_connection.close()

    print(f"[{database}] Service authentication verified.")


if __name__ == "__main__":
    initialize_databases()

    for database, username, password_key in SERVICES:
        initialize_user(database, username, password_key)

    print("Database initialization completed successfully.")