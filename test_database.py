
import os
import sqlite3
import tempfile
import unittest

from datetime import date
from flask import Flask
from database import (
    get_db,
    close_db,
    init_db,
    seed_sample_data
)


class TestDatabase(unittest.TestCase):

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()

        self.app = Flask(__name__)
        self.app.config["DATABASE"] = os.path.join(
            self.temp_dir.name, "test.db"
        )

        self.app.teardown_appcontext(close_db)

        self.context = self.app.app_context()
        self.context.push()

        self.addCleanup(self.temp_dir.cleanup)
        self.addCleanup(self.context.pop)

        init_db()

    def test_foreign_keys_enabled(self):
        result = get_db().execute(
            "PRAGMA foreign_keys"
        ).fetchone()[0]

        self.assertEqual(result, 1)

    def test_invalid_foreign_key_rejected(self):
        db = get_db()

        with self.assertRaises(sqlite3.IntegrityError):
            db.execute(
                """INSERT INTO transactions
                   (envelope_id, amount)
                   VALUES (?, ?)""",
                (999999, 50)
            )

        db.rollback()

    def test_legacy_rollover_date_repaired(self):
        db = get_db()

        db.execute(
            """INSERT INTO envelopes
               (name, monthly_allocation,
                current_balance, last_rollover_date)
               VALUES (?, ?, ?, ?)""",
            ("Test", 100, 100, "2026-11")
        )

        db.commit()

        init_db()

        result = db.execute(
            """SELECT last_rollover_date
               FROM envelopes WHERE name = ?""",
            ("Test",)
        ).fetchone()

        self.assertEqual(
            result["last_rollover_date"],
            date(2026, 11, 1)
        )

    def test_missing_payment_record_repaired(self):
        db = get_db()

        cursor = db.execute(
            """INSERT INTO bills
               (name, amount, frequency,
                due_day, next_due_date)
               VALUES (?, ?, ?, ?, ?)""",
            (
                "Test Bill",
                50,
                "monthly",
                15,
                "2026-12-15"
            )
        )

        bill_id = cursor.lastrowid
        db.commit()

        init_db()

        payment = db.execute(
            """SELECT * FROM bill_payments
               WHERE bill_id = ?""",
            (bill_id,)
        ).fetchone()

        self.assertIsNotNone(payment)
        self.assertEqual(payment["status"], "unpaid")
        self.assertEqual(
            payment["due_date"],
            date(2026, 12, 15)
        )

    def test_migration_is_idempotent(self):
        db = get_db()

        db.execute(
            """INSERT INTO bills
               (name, amount, frequency,
                due_day, next_due_date)
               VALUES (?, ?, ?, ?, ?)""",
            (
                "Test Bill",
                50,
                "monthly",
                15,
                "2026-12-15"
            )
        )

        db.commit()

        init_db()
        init_db()
        init_db()

        count = db.execute(
            "SELECT COUNT(*) FROM bill_payments"
        ).fetchone()[0]

        self.assertEqual(count, 1)

    def test_seed_creates_payment_records(self):
        seed_sample_data()

        db = get_db()

        bill_count = db.execute(
            "SELECT COUNT(*) FROM bills"
        ).fetchone()[0]

        payment_count = db.execute(
            "SELECT COUNT(*) FROM bill_payments"
        ).fetchone()[0]

        self.assertGreater(bill_count, 0)
        self.assertEqual(bill_count, payment_count)

    def test_seed_is_idempotent(self):
        seed_sample_data()
        seed_sample_data()

        db = get_db()

        envelope_count = db.execute(
            "SELECT COUNT(*) FROM envelopes"
        ).fetchone()[0]

        bill_count = db.execute(
            "SELECT COUNT(*) FROM bills"
        ).fetchone()[0]

        self.assertEqual(envelope_count, 5)
        self.assertEqual(bill_count, 5)

    def test_data_survives_reconnection(self):
        db = get_db()

        db.execute(
            """INSERT INTO envelopes
               (name, monthly_allocation, current_balance)
               VALUES (?, ?, ?)""",
            ("Persistence Test", 100, 80)
        )

        db.commit()

        close_db()

        row = get_db().execute(
            """SELECT current_balance FROM envelopes
               WHERE name = ?""",
            ("Persistence Test",)
        ).fetchone()

        self.assertEqual(row["current_balance"], 80)


if __name__ == "__main__":
    unittest.main()
