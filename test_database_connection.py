import importlib.util
import os
import pathlib
import unittest
from unittest.mock import patch


ROOT = pathlib.Path(__file__).parent


def load_database_module(service):
    path = ROOT / "services" / service / "database.py"
    name = f"{service}_database_under_test"
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class DatabaseConnectionContractTests(unittest.TestCase):
    def test_encoded_credentials_and_azure_tls_are_parsed(self):
        url = (
            "mssql://budget%5Fuser:p%40ss%3Aword@server.database.windows.net:1433/"
            "budget-db?encrypt=true&trustservercertificate=false"
        )
        for service in ("budget", "bills"):
            config = load_database_module(service).parse_database_url(url)
            self.assertEqual(config["user"], "budget_user")
            self.assertEqual(config["password"], "p@ss:word")
            self.assertEqual(config["database"], "budget-db")
            self.assertEqual(config["encryption"], "required")

    def test_certificate_bypass_is_rejected(self):
        module = load_database_module("budget")
        with self.assertRaisesRegex(ValueError, "certificate"):
            module.parse_database_url(
                "mssql://user:password@server/db?encrypt=true&trustservercertificate=true"
            )

    def test_compose_environment_remains_supported(self):
        module = load_database_module("bills")
        with patch.dict(
            os.environ,
            {
                "DB_HOST": "sqlserver",
                "DB_PORT": "1433",
                "DB_USER": "bills_user",
                "DB_PASSWORD": "local-only",
                "DB_NAME": "bills_db",
            },
            clear=True,
        ):
            config = module.get_connection_config()
        self.assertEqual(config["server"], "sqlserver")
        self.assertEqual(config["user"], "bills_user")
        self.assertNotIn("encryption", config)

    def test_transient_connection_is_retried_with_backoff(self):
        module = load_database_module("budget")
        connection = object()
        failure = module.pymssql.OperationalError("40613 database paused")
        with patch.object(module.pymssql, "connect", side_effect=[failure, connection]) as connect:
            with patch.object(module.time, "sleep") as sleep:
                result = module.connect_with_retry({"server": "host"})
        self.assertIs(result, connection)
        self.assertEqual(connect.call_count, 2)
        sleep.assert_called_once_with(0.25)

    def test_permanent_authentication_failure_is_not_retried(self):
        module = load_database_module("bills")
        failure = module.pymssql.OperationalError("18456 Login failed for user")
        with patch.object(module.pymssql, "connect", side_effect=failure) as connect:
            with self.assertRaises(module.pymssql.OperationalError):
                module.connect_with_retry({"server": "host"})
        connect.assert_called_once()


if __name__ == "__main__":
    unittest.main()
