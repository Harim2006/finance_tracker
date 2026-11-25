"""
Unit tests for Bill Tracking Domain
Tests core business logic: bill creation, payment tracking, projections, recurrence
"""
import unittest
import os
import tempfile
from datetime import date, timedelta
from flask import Flask
from database import init_db, get_db
from bill_domain import BillManager


class TestBillTrackingDomain(unittest.TestCase):
    """Test cases for bill tracking business logic"""
    
    def setUp(self):
        """Set up test database and Flask app context"""
        self.db_fd, self.db_path = tempfile.mkstemp()
        
        self.app = Flask(__name__)
        self.app.config['DATABASE'] = self.db_path
        self.app.config['TESTING'] = True
        
        with self.app.app_context():
            init_db()
        
        self.app_context = self.app.app_context()
        self.app_context.push()
        
        self.manager = BillManager()
    
    def tearDown(self):
        """Clean up test database"""
        db = get_db()
        db.close()  # Close DB first!
        self.app_context.pop()
        os.close(self.db_fd)
        try:
            os.unlink(self.db_path)
        except PermissionError:
            pass  # Windows file lock - ignore
    
    def test_create_bill(self):
        """Test creating a new recurring bill"""
        bill_id = self.manager.create_bill(
            name="Netflix",
            amount=15.99,
            frequency='monthly',
            due_day=5,
            category='entertainment'
        )
        
        self.assertIsNotNone(bill_id)
        self.assertGreater(bill_id, 0)
        
        # Verify in database
        db = get_db()
        bill = db.execute('SELECT * FROM bills WHERE id = ?', (bill_id,)).fetchone()
        
        self.assertEqual(bill['name'], 'Netflix')
        self.assertEqual(bill['amount'], 15.99)
        self.assertEqual(bill['frequency'], 'monthly')
        self.assertEqual(bill['category'], 'entertainment')
        self.assertIsNotNone(bill['next_due_date'])
    
    def test_mark_bill_as_paid(self):
        """Test marking a bill as paid"""
        bill_id = self.manager.create_bill("Internet", 50.00, 'monthly', 1, 'utilities')
        
        # Mark as paid
        success = self.manager.mark_as_paid(bill_id, amount_paid=50.00)
        self.assertTrue(success)
        
        # Verify payment record
        db = get_db()
        payment = db.execute(
            '''SELECT * FROM bill_payments 
               WHERE bill_id = ? AND status = 'paid' 
               ORDER BY paid_date DESC LIMIT 1''',
            (bill_id,)
        ).fetchone()
        
        self.assertIsNotNone(payment)
        self.assertEqual(payment['amount_paid'], 50.00)
        self.assertEqual(payment['status'], 'paid')
    
    def test_bill_next_due_date_updates_after_payment(self):
        """Test that next due date advances after payment"""
        bill_id = self.manager.create_bill("Rent", 1200.00, 'monthly', 1, 'housing')
        
        db = get_db()
        original_due_date = db.execute(
            'SELECT next_due_date FROM bills WHERE id = ?', 
            (bill_id,)
        ).fetchone()['next_due_date']
        
        # Pay the bill
        self.manager.mark_as_paid(bill_id)
        
        # Check that due date has advanced
        new_due_date = db.execute(
            'SELECT next_due_date FROM bills WHERE id = ?', 
            (bill_id,)
        ).fetchone()['next_due_date']
        
        self.assertNotEqual(original_due_date, new_due_date)
        self.assertGreater(new_due_date, original_due_date)
    
    def test_project_upcoming_bills(self):
        """Test projecting bills for multiple months"""
        # Create a monthly bill
        self.manager.create_bill("Electric", 80.00, 'monthly', 15, 'utilities')
        
        # Project 3 months ahead
        projections = self.manager.project_upcoming_bills(months=3)
        
        # Should have at least 3 occurrences
        self.assertGreaterEqual(len(projections), 3)
        
        # Check that all have the same bill name
        electric_bills = [p for p in projections if p['bill_name'] == 'Electric']
        self.assertGreaterEqual(len(electric_bills), 3)
    
    def test_get_upcoming_bills(self):
        """Test getting bills due soon"""
        today = date.today()
        
        # Bill due soon (within 30 days)
        due_day_soon = (today + timedelta(days=10)).day
        
        bill_id = self.manager.create_bill("Phone Bill", 60.00, 'monthly', due_day_soon, 'utilities')
        
        upcoming = self.manager.get_upcoming_bills(days=30)
        
        # Should include our bill
        bill_names = [b['name'] for b in upcoming]
        self.assertIn('Phone Bill', bill_names)
    
    def test_get_unpaid_bills(self):
        """Test retrieving unpaid bills"""
        bill_id = self.manager.create_bill("Gym", 40.00, 'monthly', 1, 'health')
        
        # Don't pay it - should appear in unpaid
        unpaid = self.manager.get_unpaid_bills()
        
        # Should have at least one unpaid bill
        self.assertIsInstance(unpaid, list)
        self.assertGreater(len(unpaid), 0)
    
    def test_deactivate_bill(self):
        """Test canceling/deactivating a bill"""
        bill_id = self.manager.create_bill("Old Subscription", 9.99, 'monthly', 1, 'entertainment')
        
        success = self.manager.deactivate_bill(bill_id)
        self.assertTrue(success)
        
        # Verify it's marked inactive
        db = get_db()
        bill = db.execute('SELECT active FROM bills WHERE id = ?', (bill_id,)).fetchone()
        
        self.assertEqual(bill['active'], 0)
    
    def test_bill_payment_history(self):
        """Test retrieving payment history for a bill"""
        bill_id = self.manager.create_bill("Subscription", 25.00, 'monthly', 1, 'services')
        
        # Pay it
        self.manager.mark_as_paid(bill_id, payment_date=date(2026, 1, 5).isoformat())
        
        history = self.manager.get_bill_payment_history(bill_id, limit=10)
        
        # Should have at least 1 record
        self.assertGreaterEqual(len(history), 1)
    
    def test_get_all_bills(self):
        """Test getting all active bills"""
        self.manager.create_bill("Test Bill 1", 10.00, 'monthly', 1, 'test')
        self.manager.create_bill("Test Bill 2", 20.00, 'monthly', 5, 'test')
        
        bills = self.manager.get_all_bills()
        
        self.assertEqual(len(bills), 2)
        self.assertTrue(any(b['name'] == 'Test Bill 1' for b in bills))
        self.assertTrue(any(b['name'] == 'Test Bill 2' for b in bills))
    
    def test_multiple_bills_projection(self):
        """Test projecting multiple bills together"""
        self.manager.create_bill("Bill A", 50.00, 'monthly', 5, 'test')
        self.manager.create_bill("Bill B", 30.00, 'monthly', 15, 'test')
        
        projections = self.manager.project_upcoming_bills(months=2)
        
        # Should have at least 4 entries (2 bills × 2 months)
        self.assertGreaterEqual(len(projections), 4)


    def test_negative_bill_amount(self):
        with self.assertRaises(ValueError):
            self.manager.create_bill("Test", -50, "monthly", 15)

    def test_invalid_bill_amount(self):
        with self.assertRaises(ValueError):
            self.manager.create_bill("Test", "abc", "monthly", 15)

    def test_invalid_bill_frequency(self):
        with self.assertRaises(ValueError):
            self.manager.create_bill("Test", 50, "hourly", 15)

    def test_invalid_due_day(self):
        for day in [0, 32, "abc"]:
            with self.subTest(day=day):
                with self.assertRaises(ValueError):
                    self.manager.create_bill(
                        "Test", 50, "monthly", day
                    )

    def test_invalid_projection_duration(self):
        for months in [-1, 0, 121, "abc"]:
            with self.subTest(months=months):
                with self.assertRaises(ValueError):
                    self.manager.project_upcoming_bills(months)

    def test_payment_unknown_bill(self):
        with self.assertRaises(ValueError):
            self.manager.mark_as_paid(999999)

    def test_deactivate_unknown_bill(self):
        with self.assertRaises(ValueError):
            self.manager.deactivate_bill(999999)

    def test_inactive_bill_cannot_be_paid(self):
        bill_id = self.manager.create_bill(
            "Test", 50, "monthly", 15
        )

        self.manager.deactivate_bill(bill_id)

        with self.assertRaises(ValueError):
            self.manager.mark_as_paid(bill_id)

    def test_negative_payment_amount(self):
        bill_id = self.manager.create_bill(
            "Test", 50, "monthly", 15
        )

        with self.assertRaises(ValueError):
            self.manager.mark_as_paid(
                bill_id, amount_paid=-50
            )

    def test_projection_dates_advance(self):
        bill_id = self.manager.create_bill(
            "Test", 50, "monthly", 15
        )

        projections = self.manager.project_upcoming_bills(6)

        dates = [
            item['due_date']
            for item in projections
            if item['bill_id'] == bill_id
        ]

        self.assertGreaterEqual(len(dates), 5)
        self.assertEqual(dates, sorted(set(dates)))

    def test_projection_excludes_inactive_bill(self):
        bill_id = self.manager.create_bill(
            "Test", 50, "monthly", 15
        )

        self.manager.deactivate_bill(bill_id)

        projections = self.manager.project_upcoming_bills(3)

        self.assertFalse(
            any(item['bill_id'] == bill_id
                for item in projections)
        )




    def test_monthly_recurrence(self):
        from datetime import date

        bill = {
            'frequency': 'monthly',
            'next_due_date': date(2026, 1, 15)
        }

        result = self.manager._calculate_next_occurrence(bill)

        self.assertEqual(result, date(2026, 2, 15))

    def test_weekly_recurrence(self):
        from datetime import date

        bill = {
            'frequency': 'weekly',
            'next_due_date': date(2026, 1, 15)
        }

        result = self.manager._calculate_next_occurrence(bill)

        self.assertEqual(result, date(2026, 1, 22))

    def test_biweekly_recurrence(self):
        from datetime import date

        bill = {
            'frequency': 'biweekly',
            'next_due_date': date(2026, 1, 15)
        }

        result = self.manager._calculate_next_occurrence(bill)

        self.assertEqual(result, date(2026, 1, 29))

    def test_quarterly_recurrence(self):
        from datetime import date

        bill = {
            'frequency': 'quarterly',
            'next_due_date': date(2026, 1, 15)
        }

        result = self.manager._calculate_next_occurrence(bill)

        self.assertEqual(result, date(2026, 4, 15))

    def test_yearly_recurrence(self):
        from datetime import date

        bill = {
            'frequency': 'yearly',
            'next_due_date': date(2026, 1, 15)
        }

        result = self.manager._calculate_next_occurrence(bill)

        self.assertEqual(result, date(2027, 1, 15))

    def test_date_conversion(self):
        from datetime import date, datetime

        expected = date(2026, 1, 15)

        for value in [
            expected,
            '2026-01-15',
            datetime(2026, 1, 15, 12, 30)
        ]:
            with self.subTest(value=value):
                self.assertEqual(
                    self.manager._as_date(value),
                    expected
                )

    def test_payment_without_unpaid_record(self):
        from database import get_db
        from validation import ConflictError

        bill_id = self.manager.create_bill(
            "Test", 50, "monthly", 15
        )

        db = get_db()

        db.execute(
            "DELETE FROM bill_payments WHERE bill_id = ?",
            (bill_id,)
        )

        db.commit()

        with self.assertRaises(ConflictError):
            self.manager.mark_as_paid(bill_id)




if __name__ == '__main__':
    unittest.main()