"""
Domain A: Envelope Budgeting
Business logic for budget envelopes, allocations, transactions, and rollover
"""
from datetime import datetime, date
from database import get_db


class BudgetEnvelopeManager:
    """
    Manages envelope budgeting operations:
    - Creating and managing budget envelopes
    - Recording transactions
    - Enforcing overspend rules
    - Monthly rollover logic
    """
    
    def create_envelope(self, name, monthly_allocation, overspend_rule='stop'):
        """Create a new budget envelope"""
        db = get_db()
        
        cursor = db.execute(
            '''INSERT INTO envelopes (name, monthly_allocation, current_balance, overspend_rule)
               VALUES (?, ?, ?, ?)''',
            (name, monthly_allocation, monthly_allocation, overspend_rule)
        )
        db.commit()
        
        return cursor.lastrowid
    
    def allocate_funds(self, envelope_id, amount):
        """Add funds to an envelope"""
        db = get_db()
        
        db.execute(
            'UPDATE envelopes SET current_balance = current_balance + ? WHERE id = ?',
            (amount, envelope_id)
        )
        db.commit()
        
        return True
    
    def record_transaction(self, envelope_id, amount, description='', merchant=''):
        """Record a spending transaction from an envelope with overspend rules"""
        db = get_db()
        
        # Get envelope details
        envelope = db.execute(
            'SELECT current_balance, overspend_rule, name FROM envelopes WHERE id = ?',
            (envelope_id,)
        ).fetchone()
        
        if not envelope:
            raise ValueError(f"Envelope {envelope_id} not found")
        
        new_balance = envelope['current_balance'] - amount
        
        # Check overspend rule
        if new_balance < 0 and envelope['overspend_rule'] == 'stop':
            # Reject transaction - insufficient funds
            return None
        
        # Record transaction
        cursor = db.execute(
            '''INSERT INTO transactions (envelope_id, amount, description, merchant, date)
               VALUES (?, ?, ?, ?, ?)''',
            (envelope_id, amount, description, merchant, datetime.now())
        )
        
        # Update envelope balance
        db.execute(
            'UPDATE envelopes SET current_balance = current_balance - ? WHERE id = ?',
            (amount, envelope_id)
        )
        
        db.commit()
        
        return cursor.lastrowid
    
    def execute_monthly_rollover(self):
        """Execute monthly rollover for all envelopes"""
        db = get_db()
        current_month = date.today().strftime('%Y-%m')
        rollover_date = date.today().replace(day=1)
        
        envelopes = db.execute('SELECT * FROM envelopes WHERE rollover_enabled = 1').fetchall()
        rolled_over = []
        
        for envelope in envelopes:
            # Skip if already rolled over this month
            last_rollover = envelope['last_rollover_date']

            if last_rollover and str(last_rollover)[:7] == current_month:
               continue
            
            envelope_id = envelope['id']
            current_balance = envelope['current_balance']
            monthly_allocation = envelope['monthly_allocation']
            
            # Calculate spent this month
            spent = db.execute(
                '''SELECT SUM(amount) FROM transactions 
                   WHERE envelope_id = ? AND strftime('%Y-%m', date) = ?''',
                (envelope_id, current_month)
            ).fetchone()[0] or 0
            
            # Record history
            db.execute(
                '''INSERT INTO envelope_history (envelope_id, month, allocated, spent, rolled_over)
                   VALUES (?, ?, ?, ?, ?)''',
                (envelope_id, current_month, monthly_allocation, spent, current_balance)
            )
            
            # Reset balance: keep remaining + new allocation
            new_balance = current_balance + monthly_allocation
            
            db.execute(
                '''UPDATE envelopes 
                   SET current_balance = ?, last_rollover_date = ?
                   WHERE id = ?''',
                (new_balance, rollover_date.isoformat(), envelope_id)
            )
            
            rolled_over.append(envelope_id)
        
        db.commit()
        return rolled_over
    
    def auto_categorize_transaction(self, merchant, amount):
        """Auto-assign a transaction to an envelope based on merchant matching rules"""
        db = get_db()
        
        # Find matching rule (highest priority first)
        merchant_lower = merchant.lower()
        
        rules = db.execute(
            '''SELECT envelope_id, merchant_pattern FROM category_rules
               ORDER BY priority DESC'''
        ).fetchall()
        
        for rule in rules:
            if rule['merchant_pattern'].lower() in merchant_lower:
                return rule['envelope_id']
        
        return None
    
    def get_envelope_status(self, envelope_id):
        """Get current status and statistics for an envelope"""
        db = get_db()
        
        envelope = db.execute('SELECT * FROM envelopes WHERE id = ?', (envelope_id,)).fetchone()
        
        if not envelope:
            return None
        
        current_month = date.today().strftime('%Y-%m')
        
        # Get this month's spending
        spent_this_month = db.execute(
            '''SELECT SUM(amount) FROM transactions 
               WHERE envelope_id = ? AND strftime('%Y-%m', date) = ?''',
            (envelope_id, current_month)
        ).fetchone()[0] or 0
        
        # Get transaction count
        transaction_count = db.execute(
            'SELECT COUNT(*) FROM transactions WHERE envelope_id = ?',
            (envelope_id,)
        ).fetchone()[0]
        
        return {
            'id': envelope['id'],
            'name': envelope['name'],
            'current_balance': envelope['current_balance'],
            'monthly_allocation': envelope['monthly_allocation'],
            'spent_this_month': spent_this_month,
            'remaining_this_month': envelope['monthly_allocation'] - spent_this_month,
            'overspend_rule': envelope['overspend_rule'],
            'transaction_count': transaction_count,
            'is_overspent': envelope['current_balance'] < 0
        }
    
    def get_all_envelopes(self):
        """Get all envelopes with current status"""
        db = get_db()
        envelopes = db.execute('SELECT * FROM envelopes').fetchall()
        
        return [dict(env) for env in envelopes]
    
    def get_recent_transactions(self, days=30):
        """Get recent transactions across all envelopes"""
        db = get_db()
        
        transactions = db.execute(
            '''SELECT t.*, e.name as envelope_name 
               FROM transactions t
               LEFT JOIN envelopes e ON t.envelope_id = e.id
               WHERE t.date >= date('now', '-' || ? || ' days')
               ORDER BY t.date DESC''',
            (days,)
        ).fetchall()
        
        return [dict(txn) for txn in transactions]
    
    def get_spending_breakdown(self, start_date=None, end_date=None):
        """Get spending breakdown by envelope"""
        db = get_db()
        
        if not start_date:
            start_date = date.today().replace(day=1).isoformat()
        if not end_date:
            end_date = date.today().isoformat()
        
        breakdown = db.execute(
            '''SELECT e.name, SUM(t.amount) as total
               FROM transactions t
               JOIN envelopes e ON t.envelope_id = e.id
               WHERE date(t.date) BETWEEN date(?) AND date(?)
               GROUP BY e.id, e.name
               ORDER BY total DESC''',
            (start_date, end_date)
        ).fetchall()
        
        return [dict(row) for row in breakdown]