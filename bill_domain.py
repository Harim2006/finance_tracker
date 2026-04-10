"""
Domain B: Bill and Subscription Tracking
Business logic for recurring bills, due dates, payment tracking, and projections
"""
from datetime import datetime, date, timedelta
from dateutil.relativedelta import relativedelta
from database import get_db


class BillManager:
    """Manages bill tracking operations"""
    
    FREQUENCY_MAP = {
        'weekly': 7,
        'biweekly': 14,
        'monthly': 30,
        'quarterly': 90,
        'yearly': 365
    }
    
    def create_bill(self, name, amount, frequency, due_day, category='other'):
        """Create a new recurring bill"""
        db = get_db()
        
        # Calculate first due date
        next_due = self._calculate_next_due_date(frequency, due_day)
        
        cursor = db.execute(
            '''INSERT INTO bills (name, amount, frequency, due_day, category, next_due_date)
               VALUES (?, ?, ?, ?, ?, ?)''',
            (name, amount, frequency, due_day, category, next_due.isoformat())
        )
        db.commit()
        
        # Create first payment record
        self._create_payment_record(cursor.lastrowid, next_due)
        
        return cursor.lastrowid
    
    def _calculate_next_due_date(self, frequency, due_day):
        """Calculate the next due date based on frequency and day"""
        today = date.today()
        
        if frequency == 'monthly':
            if today.day <= due_day:
                next_due = date(today.year, today.month, min(due_day, 28))
            else:
                next_due = (today.replace(day=1) + timedelta(days=32)).replace(day=min(due_day, 28))
        elif frequency == 'yearly':
            year = today.year
            next_due = date(year, 1, 1) + timedelta(days=due_day - 1)
            if next_due < today:
                next_due = date(year + 1, 1, 1) + timedelta(days=due_day - 1)
        else:
            days_offset = self.FREQUENCY_MAP.get(frequency, 30)
            next_due = today + timedelta(days=due_day if due_day < days_offset else 1)
        
        return next_due
    
    def _create_payment_record(self, bill_id, due_date):
        """Create a payment record for a bill occurrence"""
        db = get_db()
        
        db.execute(
            '''INSERT INTO bill_payments (bill_id, due_date, status)
               VALUES (?, ?, 'unpaid')''',
            (bill_id, due_date.isoformat())
        )
        db.commit()
    
    def mark_as_paid(self, bill_id, payment_date=None, amount_paid=None):
        """Mark a bill as paid"""
        db = get_db()
        
        if payment_date is None:
            payment_date = date.today().isoformat()
        
        bill = db.execute('SELECT * FROM bills WHERE id = ?', (bill_id,)).fetchone()
        
        if not bill:
            raise ValueError(f"Bill {bill_id} not found")
        
        if amount_paid is None:
            amount_paid = bill['amount']
        
        # Find the unpaid record
        payment_record = db.execute(
            '''SELECT * FROM bill_payments 
               WHERE bill_id = ? AND status = 'unpaid'
               ORDER BY due_date LIMIT 1''',
            (bill_id,)
        ).fetchone()
        
        if payment_record:
            db.execute(
                '''UPDATE bill_payments 
                   SET status = 'paid', paid_date = ?, amount_paid = ?
                   WHERE id = ?''',
                (payment_date, amount_paid, payment_record['id'])
            )
        
        # Calculate and update next due date
        next_due = self._calculate_next_occurrence(bill)
        db.execute(
            'UPDATE bills SET next_due_date = ? WHERE id = ?',
            (next_due.isoformat(), bill_id)
        )
        
        # Create next payment record
        self._create_payment_record(bill_id, next_due)
        
        db.commit()
        return True
    
    def _calculate_next_occurrence(self, bill):
        """Calculate when a bill should recur next"""
        current_due = datetime.fromisoformat(bill['next_due_date']).date()
        frequency = bill['frequency']
        
        if frequency == 'monthly':
            next_due = current_due + relativedelta(months=1)
        elif frequency == 'yearly':
            next_due = current_due + relativedelta(years=1)
        elif frequency == 'quarterly':
            next_due = current_due + relativedelta(months=3)
        else:
            days = self.FREQUENCY_MAP.get(frequency, 30)
            next_due = current_due + timedelta(days=days)
        
        return next_due
    
    def project_upcoming_bills(self, months=3):
        """Project all bill payments for the next N months"""
        db = get_db()
        
        bills = db.execute('SELECT * FROM bills WHERE active = 1').fetchall()
        
        end_date = date.today() + relativedelta(months=months)
        projections = []
        
        for bill in bills:
            current_date = datetime.fromisoformat(bill['next_due_date']).date()
            
            while current_date <= end_date:
                payment = db.execute(
                    '''SELECT status FROM bill_payments 
                       WHERE bill_id = ? AND due_date = ?''',
                    (bill['id'], current_date.isoformat())
                ).fetchone()
                
                status = payment['status'] if payment else 'projected'
                
                projections.append({
                    'bill_id': bill['id'],
                    'bill_name': bill['name'],
                    'amount': bill['amount'],
                    'due_date': current_date.isoformat(),
                    'category': bill['category'],
                    'status': status
                })
                
                current_date = self._calculate_next_occurrence(bill)
        
        projections.sort(key=lambda x: x['due_date'])
        
        return projections
    
    def get_upcoming_bills(self, days=30):
        """Get bills due in the next N days"""
        db = get_db()
        
        end_date = (date.today() + timedelta(days=days)).isoformat()
        
        bills = db.execute(
            '''SELECT * FROM bills 
               WHERE next_due_date <= ? AND active = 1
               ORDER BY next_due_date''',
            (end_date,)
        ).fetchall()
        
        return [dict(bill) for bill in bills]
    
    def get_unpaid_bills(self):
        """Get all unpaid bills"""
        db = get_db()
        
        unpaid = db.execute(
            '''SELECT b.*, bp.due_date, bp.status
               FROM bills b
               JOIN bill_payments bp ON b.id = bp.bill_id
               WHERE bp.status = 'unpaid' AND b.active = 1
               ORDER BY bp.due_date''',
        ).fetchall()
        
        return [dict(row) for row in unpaid]
    
    def get_monthly_bill_total(self, year, month):
        """Calculate total bills for a specific month"""
        db = get_db()
        
        start_date = date(year, month, 1).isoformat()
        if month == 12:
            end_date = date(year + 1, 1, 1).isoformat()
        else:
            end_date = date(year, month + 1, 1).isoformat()
        
        total = db.execute(
            '''SELECT SUM(b.amount) as total
               FROM bills b
               WHERE b.next_due_date BETWEEN ? AND ? AND b.active = 1''',
            (start_date, end_date)
        ).fetchone()['total'] or 0
        
        return total
    
    def deactivate_bill(self, bill_id):
        """Cancel/deactivate a bill"""
        db = get_db()
        
        db.execute('UPDATE bills SET active = 0 WHERE id = ?', (bill_id,))
        db.commit()
        
        return True
    
    def get_bill_payment_history(self, bill_id, limit=12):
        """Get payment history for a bill"""
        db = get_db()
        
        history = db.execute(
            '''SELECT * FROM bill_payments
               WHERE bill_id = ?
               ORDER BY due_date DESC
               LIMIT ?''',
            (bill_id, limit)
        ).fetchall()
        
        return [dict(row) for row in history]
    
    def get_all_bills(self):
        """Get all active bills"""
        db = get_db()
        
        bills = db.execute('SELECT * FROM bills WHERE active = 1 ORDER BY next_due_date').fetchall()
        
        return [dict(bill) for bill in bills]