
"""Apply versioned SQL Server database migrations."""

import os
from pathlib import Path

import pymssql
from dotenv import load_dotenv


ROOT = Path(__file__).resolve().parent.parent

load_dotenv(ROOT / ".env")


DATABASES = {
    "budget_db": ROOT / "services" / "budget" / "migrations",
    "bills_db": ROOT / "services" / "bills" / "migrations",
}


def run_migrations(database_name, migrations_dir):
    connection = pymssql.connect(
        server=os.getenv("DB_HOST", "127.0.0.1"),
        port=os.getenv("DB_PORT", "1433"),
        user=os.getenv("MIGRATION_DB_USER", "sa"),
        password=os.environ["MSSQL_SA_PASSWORD"],
        database=database_name,
        login_timeout=15,
        timeout=60,
        autocommit=False,
    )

    try:
        cursor = connection.cursor()

        cursor.execute("""
            IF OBJECT_ID('dbo.schema_migrations', 'U') IS NULL
            BEGIN
                CREATE TABLE dbo.schema_migrations (
                    version NVARCHAR(255) PRIMARY KEY,
                    applied_at DATETIME2 NOT NULL
                        DEFAULT SYSUTCDATETIME()
                );
            END;
        """)

        connection.commit()

        for migration in sorted(migrations_dir.glob("*.sql")):
            cursor.execute(
                """
                SELECT version
                FROM dbo.schema_migrations
                WHERE version = %s
                """,
                (migration.name,),
            )

            if cursor.fetchone():
                print(
                    f"[{database_name}] "
                    f"Skipped {migration.name} (already applied)"
                )
                connection.commit()
                continue

            print(f"[{database_name}] Applying {migration.name}")

            sql = migration.read_text(encoding="utf-8-sig")

            cursor.execute(sql)

            cursor.execute(
                """
                INSERT INTO dbo.schema_migrations (version)
                VALUES (%s)
                """,
                (migration.name,),
            )

            connection.commit()

            print(f"[{database_name}] Migration successful")

    except Exception:
        connection.rollback()
        print(f"[{database_name}] Migration failed; rolled back")
        raise

    finally:
        connection.close()


if __name__ == "__main__":
    for database, directory in DATABASES.items():
        run_migrations(database, directory)

    print("All database migrations completed successfully.")
