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


if __name__ == '__main__':
    unittest.main()