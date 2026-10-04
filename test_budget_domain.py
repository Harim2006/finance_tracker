"""
Unit tests for Budget Envelope Domain
Tests core business logic: envelope creation, transactions, overspend rules, rollover
"""
import unittest
import os
import tempfile
from datetime import date, datetime
from flask import Flask
from database import init_db, get_db
from budget_domain import BudgetEnvelopeManager


class TestBudgetEnvelopeDomain(unittest.TestCase):
    """Test cases for envelope budgeting business logic"""
    
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
        
        self.manager = BudgetEnvelopeManager()
    
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
    
    def test_create_envelope(self):
        """Test creating a new budget envelope"""
        envelope_id = self.manager.create_envelope(
            name="Groceries",
            monthly_allocation=500.00,
            overspend_rule='stop'
        )
        
        self.assertIsNotNone(envelope_id)
        self.assertGreater(envelope_id, 0)
        
        # Verify in database
        db = get_db()
        envelope = db.execute('SELECT * FROM envelopes WHERE id = ?', (envelope_id,)).fetchone()
        
        self.assertEqual(envelope['name'], 'Groceries')
        self.assertEqual(envelope['monthly_allocation'], 500.00)
        self.assertEqual(envelope['current_balance'], 500.00)
        self.assertEqual(envelope['overspend_rule'], 'stop')
    
    def test_allocate_funds(self):
        """Test adding funds to an envelope"""
        envelope_id = self.manager.create_envelope("Test", 100.00)
        
        success = self.manager.allocate_funds(envelope_id, 50.00)
        self.assertTrue(success)
        
        # Check new balance
        db = get_db()
        balance = db.execute(
            'SELECT current_balance FROM envelopes WHERE id = ?', 
            (envelope_id,)
        ).fetchone()['current_balance']
        
        self.assertEqual(balance, 150.00)
    
    def test_record_transaction_success(self):
        """Test recording a valid transaction"""
        envelope_id = self.manager.create_envelope("Dining", 200.00)
        
        txn_id = self.manager.record_transaction(
            envelope_id=envelope_id,
            amount=45.50,
            description="Dinner at restaurant",
            merchant="Local Bistro"
        )
        
        self.assertIsNotNone(txn_id)
        
        # Verify balance updated
        db = get_db()
        balance = db.execute(
            'SELECT current_balance FROM envelopes WHERE id = ?', 
            (envelope_id,)
        ).fetchone()['current_balance']
        
        self.assertEqual(balance, 154.50)
    
    def test_overspend_rule_stop(self):
        """Test that 'stop' overspend rule prevents overdraft"""
        envelope_id = self.manager.create_envelope("Entertainment", 50.00, overspend_rule='stop')
        
        # Try to spend more than available
        txn_id = self.manager.record_transaction(
            envelope_id=envelope_id,
            amount=75.00,
            description="Over budget"
        )
        
        # Transaction should be rejected
        self.assertIsNone(txn_id)
        
        # Balance should be unchanged
        db = get_db()
        balance = db.execute(
            'SELECT current_balance FROM envelopes WHERE id = ?', 
            (envelope_id,)
        ).fetchone()['current_balance']
        
        self.assertEqual(balance, 50.00)
    
    def test_overspend_rule_borrow(self):
        """Test that 'borrow' overspend rule allows negative balance"""
        envelope_id = self.manager.create_envelope("Gas", 100.00, overspend_rule='borrow')
        
        # Spend more than available
        txn_id = self.manager.record_transaction(
            envelope_id=envelope_id,
            amount=120.00,
            description="Emergency fill-up"
        )
        
        # Transaction should succeed
        self.assertIsNotNone(txn_id)
        
        # Balance should be negative
        db = get_db()
        balance = db.execute(
            'SELECT current_balance FROM envelopes WHERE id = ?', 
            (envelope_id,)
        ).fetchone()['current_balance']
        
        self.assertEqual(balance, -20.00)
    
    def test_monthly_rollover(self):
        """Test monthly rollover logic"""
        envelope_id = self.manager.create_envelope("Utilities", 300.00)
        
        # Spend some money
        self.manager.record_transaction(envelope_id, 150.00, "Electric bill")
        
        # Execute rollover
        rolled_over = self.manager.execute_monthly_rollover()
        
        self.assertIn(envelope_id, rolled_over)
        
        # Check new balance (should be: remaining 150 + new allocation 300)
        db = get_db()
        envelope = db.execute(
            'SELECT current_balance FROM envelopes WHERE id = ?',
            (envelope_id,)
        ).fetchone()
        
        self.assertEqual(envelope['current_balance'], 450.00)
    
    def test_auto_categorize_transaction(self):
        """Test automatic transaction categorization"""
        groceries_id = self.manager.create_envelope("Groceries", 500.00)
        
        db = get_db()
        # Add a categorization rule
        db.execute(
            'INSERT INTO category_rules (merchant_pattern, envelope_id, priority) VALUES (?, ?, ?)',
            ('walmart', groceries_id, 100)
        )
        db.commit()
        
        # Test matching
        matched_envelope = self.manager.auto_categorize_transaction("Walmart Supercenter", 50.00)
        
        self.assertEqual(matched_envelope, groceries_id)
    
    def test_auto_categorize_no_match(self):
        """Test auto-categorization when no rule matches"""
        self.manager.create_envelope("Groceries", 500.00)
        
        matched_envelope = self.manager.auto_categorize_transaction("Random Store XYZ", 50.00)
        
        self.assertIsNone(matched_envelope)
    
    def test_get_envelope_status(self):
        """Test getting envelope status with statistics"""
        envelope_id = self.manager.create_envelope("Shopping", 400.00)
        
        # Make some transactions
        self.manager.record_transaction(envelope_id, 75.00, "Purchase 1")
        self.manager.record_transaction(envelope_id, 50.00, "Purchase 2")
        
        status = self.manager.get_envelope_status(envelope_id)
        
        self.assertEqual(status['name'], 'Shopping')
        self.assertEqual(status['monthly_allocation'], 400.00)
        self.assertEqual(status['current_balance'], 275.00)
        self.assertEqual(status['spent_this_month'], 125.00)
        self.assertEqual(status['transaction_count'], 2)
        self.assertFalse(status['is_overspent'])
    
    def test_get_spending_breakdown(self):
        """Test spending breakdown by category"""
        groceries_id = self.manager.create_envelope("Groceries", 500.00)
        dining_id = self.manager.create_envelope("Dining", 200.00)
        
        self.manager.record_transaction(groceries_id, 100.00, "Groceries")
        self.manager.record_transaction(dining_id, 50.00, "Restaurant")
        
        breakdown = self.manager.get_spending_breakdown()
        
        self.assertEqual(len(breakdown), 2)
        self.assertTrue(any(b['name'] == 'Groceries' and b['total'] == 100.00 for b in breakdown))
        self.assertTrue(any(b['name'] == 'Dining' and b['total'] == 50.00 for b in breakdown))
    
    def test_get_all_envelopes(self):
        """Test retrieving all envelopes"""
        self.manager.create_envelope("Test1", 100.00)
        self.manager.create_envelope("Test2", 200.00)
        
        envelopes = self.manager.get_all_envelopes()
        
        self.assertEqual(len(envelopes), 2)
        self.assertTrue(any(e['name'] == 'Test1' for e in envelopes))
        self.assertTrue(any(e['name'] == 'Test2' for e in envelopes))


if __name__ == '__main__':
    unittest.main()