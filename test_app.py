
import os
import tempfile
import unittest
from unittest.mock import patch


# Isolate database initialization during application import.
with tempfile.TemporaryDirectory() as startup_dir:
    with patch.dict(os.environ, {"DATA_DIR": startup_dir}):
        from app import app

from database import init_db, get_db, seed_sample_data


class TestFlaskIntegration(unittest.TestCase):

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)

        self.original_config = app.config.copy()
        self.addCleanup(self.restore_config)

        app.config["TESTING"] = True
        app.config["DATABASE"] = os.path.join(
            self.temp_dir.name, "test.db"
        )

        self.env_patch = patch.dict(
            os.environ, {"DATA_DIR": self.temp_dir.name}
        )
        self.env_patch.start()
        self.addCleanup(self.env_patch.stop)

        with app.app_context():
            init_db()

        self.client = app.test_client()

    def restore_config(self):
        app.config.clear()
        app.config.update(self.original_config)

    def create_envelope(self):
        response = self.client.post(
            "/envelopes/create",
            json={
                "name": "Groceries",
                "monthly_allocation": 100,
                "overspend_rule": "stop"
            }
        )

        self.assertEqual(response.status_code, 201)
        return response.get_json()["id"]

    def create_bill(self):
        response = self.client.post(
            "/bills/create",
            json={
                "name": "Internet",
                "amount": 50,
                "frequency": "monthly",
                "due_day": 15
            }
        )

        self.assertEqual(response.status_code, 201)
        return response.get_json()["id"]

    def get_balance(self, envelope_id):
        with app.app_context():
            row = get_db().execute(
                """SELECT current_balance
                   FROM envelopes WHERE id = ?""",
                (envelope_id,)
            ).fetchone()

            return row["current_balance"]

    def test_pages_load(self):
        for path in ["/", "/envelopes", "/bills"]:
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual(response.status_code, 200)

    def test_create_envelope(self):
        envelope_id = self.create_envelope()
        self.assertEqual(self.get_balance(envelope_id), 100)

    def test_allocate_funds(self):
        envelope_id = self.create_envelope()

        response = self.client.post(
            f"/envelopes/{envelope_id}/allocate",
            json={"amount": 50}
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.get_balance(envelope_id), 150)

    def test_spending(self):
        envelope_id = self.create_envelope()

        response = self.client.post(
            f"/envelopes/{envelope_id}/spend",
            json={"amount": 30}
        )

        self.assertEqual(response.status_code, 201)
        self.assertIsNotNone(
            response.get_json()["transaction_id"]
        )
        self.assertEqual(self.get_balance(envelope_id), 70)

    def test_blocked_overdraft(self):
        envelope_id = self.create_envelope()

        response = self.client.post(
            f"/envelopes/{envelope_id}/spend",
            json={"amount": 500}
        )

        self.assertEqual(response.status_code, 409)
        self.assertEqual(self.get_balance(envelope_id), 100)

    def test_negative_allocation(self):
        envelope_id = self.create_envelope()

        response = self.client.post(
            f"/envelopes/{envelope_id}/allocate",
            json={"amount": -50}
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.get_balance(envelope_id), 100)

    def test_negative_spending(self):
        envelope_id = self.create_envelope()

        response = self.client.post(
            f"/envelopes/{envelope_id}/spend",
            json={"amount": -10}
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.get_balance(envelope_id), 100)

    def test_unknown_envelope(self):
        response = self.client.post(
            "/envelopes/999999/allocate",
            json={"amount": 50}
        )

        self.assertEqual(response.status_code, 404)

    def test_duplicate_envelope(self):
        self.create_envelope()

        response = self.client.post(
            "/envelopes/create",
            json={
                "name": "Groceries",
                "monthly_allocation": 100
            }
        )

        self.assertEqual(response.status_code, 409)

    def test_missing_required_fields(self):
        for path in ["/envelopes/create", "/bills/create"]:
            with self.subTest(path=path):
                response = self.client.post(path, json={})
                self.assertEqual(response.status_code, 400)

    def test_invalid_amount(self):
        response = self.client.post(
            "/envelopes/create",
            json={
                "name": "Test",
                "monthly_allocation": "abc"
            }
        )

        self.assertEqual(response.status_code, 400)

    def test_rollover_and_page_rendering(self):
        envelope_id = self.create_envelope()

        first = self.client.post(
            "/envelopes/rollover", json={}
        )

        self.assertEqual(first.status_code, 200)
        self.assertEqual(first.get_json()["rolledover"], 1)
        self.assertEqual(self.get_balance(envelope_id), 200)

        second = self.client.post(
            "/envelopes/rollover", json={}
        )

        self.assertEqual(second.status_code, 200)
        self.assertEqual(second.get_json()["rolledover"], 0)
        self.assertEqual(self.get_balance(envelope_id), 200)

        for path in [
            "/",
            "/envelopes",
            "/api/dashboard/summary",
            "/analysis/insights"
        ]:
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual(response.status_code, 200)

    def test_bill_payment(self):
        bill_id = self.create_bill()

        with app.app_context():
            before = get_db().execute(
                "SELECT next_due_date FROM bills WHERE id = ?",
                (bill_id,)
            ).fetchone()["next_due_date"]

        response = self.client.post(
            f"/bills/{bill_id}/pay",
            json={}
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["status"], "paid")

        with app.app_context():
            after = get_db().execute(
                "SELECT next_due_date FROM bills WHERE id = ?",
                (bill_id,)
            ).fetchone()["next_due_date"]

        self.assertGreater(after, before)

    def test_upcoming_bills(self):
        bill_id = self.create_bill()

        response = self.client.get("/bills/upcoming?months=3")

        self.assertEqual(response.status_code, 200)

        dates = [
            item["due_date"]
            for item in response.get_json()
            if item["bill_id"] == bill_id
        ]

        self.assertGreaterEqual(len(dates), 2)
        self.assertEqual(dates, sorted(set(dates)))

    def test_invalid_projection_duration(self):
        response = self.client.get("/bills/upcoming?months=-1")
        self.assertEqual(response.status_code, 400)

    def test_deactivate_bill(self):
        bill_id = self.create_bill()

        response = self.client.post(
            f"/bills/{bill_id}/deactivate",
            json={}
        )

        self.assertEqual(response.status_code, 200)

        page = self.client.get("/bills")
        self.assertNotIn(b"Internet", page.data)

        projections = self.client.get(
            "/bills/upcoming"
        ).get_json()

        self.assertFalse(
            any(item["bill_id"] == bill_id
                for item in projections)
        )

        with app.app_context():
            bill = get_db().execute(
                "SELECT active FROM bills WHERE id = ?",
                (bill_id,)
            ).fetchone()

            self.assertEqual(bill["active"], 0)

    def test_invalid_bill_frequency(self):
        response = self.client.post(
            "/bills/create",
            json={
                "name": "Test",
                "amount": 50,
                "frequency": "hourly",
                "due_day": 1
            }
        )

        self.assertEqual(response.status_code, 400)

    def test_negative_bill_amount(self):
        response = self.client.post(
            "/bills/create",
            json={
                "name": "Test",
                "amount": -50,
                "frequency": "monthly",
                "due_day": 15
            }
        )

        self.assertEqual(response.status_code, 400)

    def test_financial_insights_with_bills(self):
        self.create_envelope()
        self.create_bill()

        response = self.client.get("/analysis/insights")

        self.assertEqual(response.status_code, 200)
        self.assertIn("insights", response.get_json())

    def test_seeded_bank_transaction(self):
        with app.app_context():
            seed_sample_data()

            envelope_id = get_db().execute(
                "SELECT id FROM envelopes WHERE name = ?",
                ("Groceries",)
            ).fetchone()["id"]

        before = self.get_balance(envelope_id)

        response = self.client.post(
            "/api/bank/transaction",
            json={
                "merchant": "Walmart",
                "amount": -25,
                "description": "Test purchase"
            }
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(
            response.get_json()["status"], "processed"
        )
        self.assertEqual(
            self.get_balance(envelope_id), before - 25
        )

    def test_simulated_purchase(self):
        with app.app_context():
            seed_sample_data()

            envelope_id = get_db().execute(
                "SELECT id FROM envelopes WHERE name = ?",
                ("Groceries",)
            ).fetchone()["id"]

        before = self.get_balance(envelope_id)

        response = self.client.post(
            "/simulate-purchase",
            json={
                "merchant": "Walmart",
                "amount": 15
            }
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(
            response.get_json()["status"], "processed"
        )
        self.assertEqual(
            self.get_balance(envelope_id), before - 15
        )


if __name__ == "__main__":
    unittest.main()
