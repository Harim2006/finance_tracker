import importlib.util
import pathlib
import sys
import tempfile
import unittest
from unittest.mock import patch


ROOT = pathlib.Path(__file__).parent
DB_DIR = ROOT / "db"
if str(DB_DIR) not in sys.path:
    sys.path.insert(0, str(DB_DIR))


def load_module(relative_path, name):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FakeCursor:
    def __init__(self, principal=None, memberships=None):
        self.principal = principal
        self.memberships = iter(memberships or [])
        self.statements = []

    def execute(self, statement, parameters=None):
        self.statements.append((statement, parameters))

    def fetchone(self):
        statement = self.statements[-1][0]
        if "DATABASE_PRINCIPAL_ID" in statement:
            return (self.principal,)
        if "SELECT version" in statement:
            return None
        return (next(self.memberships),)

    def close(self):
        pass


class FakeConnection:
    def __init__(self, cursor):
        self.cursor_instance = cursor
        self.commits = 0
        self.rollbacks = 0

    def cursor(self):
        return self.cursor_instance

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1

    def close(self):
        pass


class AzureSqlInitializationTests(unittest.TestCase):
    def test_contained_user_initialization_is_idempotent_and_isolated(self):
        module = load_module("db/azure_init.py", "azure_init_under_test")
        cursor = FakeCursor(principal=None, memberships=[1, 0, 1])
        connection = FakeConnection(cursor)
        module.create_or_verify_user(connection, "budget_user", "p'assword")
        sql = "\n".join(statement for statement, _ in cursor.statements)
        self.assertIn("CREATE USER [budget_user] WITH PASSWORD = N'p''assword'", sql)
        self.assertIn("ALTER ROLE [db_datareader] ADD MEMBER [budget_user]", sql)
        self.assertNotIn("CREATE LOGIN", sql)
        self.assertNotIn("USE ", sql)
        self.assertNotIn("sa", sql.lower())
        self.assertEqual(connection.commits, 1)

    def test_existing_user_only_receives_missing_roles(self):
        module = load_module("db/azure_init.py", "azure_init_existing_user")
        cursor = FakeCursor(principal=7, memberships=[1, 1, 1])
        connection = FakeConnection(cursor)
        module.create_or_verify_user(connection, "bills_user", "unused")
        sql = "\n".join(statement for statement, _ in cursor.statements)
        self.assertNotIn("CREATE USER", sql)
        self.assertNotIn("ALTER ROLE", sql)

    def test_migration_runner_accepts_independent_service_url(self):
        module = load_module("db/migrate.py", "migrate_under_test")
        cursor = FakeCursor(memberships=[None])
        connection = FakeConnection(cursor)
        with tempfile.TemporaryDirectory() as directory:
            migration = pathlib.Path(directory) / "001_test.sql"
            migration.write_text("CREATE TABLE dbo.test_table (id INT);", encoding="utf-8")
            with patch.object(module, "parse_database_url", return_value={"database": "budget-db"}) as parse:
                with patch.object(module, "connect_with_retry", return_value=connection) as connect:
                    module.run_migrations(
                        "budget_db", pathlib.Path(directory), "mssql://budget-url"
                    )
        parse.assert_called_once_with("mssql://budget-url")
        connect.assert_called_once_with({"database": "budget-db"}, autocommit=False)
        self.assertEqual(connection.commits, 2)


if __name__ == "__main__":
    unittest.main()
