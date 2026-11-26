"""Domain A: Envelope Budgeting (SQL Server)."""
from datetime import datetime, date, timedelta
from contextlib import contextmanager
from decimal import Decimal

from database import get_db
from validation import validate_amount, validate_name, NotFoundError, ConflictError


def _money(value):
    return Decimal(str(value))


def _public_row(row):
    return {key: float(value) if isinstance(value, Decimal) else value
            for key, value in row.items()}


@contextmanager
def _cursor(write=False):
    db = get_db()
    cursor = db.cursor()
    try:
        yield cursor
        if write:
            db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        cursor.close()


def _month_bounds():
    start = date.today().replace(day=1)
    end = (start + timedelta(days=32)).replace(day=1)
    return start, end


class BudgetEnvelopeManager:
    """Manage envelopes, transactions, categorization and monthly rollover."""

    def create_envelope(self, name, monthly_allocation, overspend_rule='stop'):
        name = validate_name(name)
        monthly_allocation = _money(validate_amount(monthly_allocation, allow_zero=True))
        if overspend_rule not in ('stop', 'borrow'):
            raise ValueError('Invalid overspend rule')
        with _cursor(write=True) as cur:
            cur.execute('SELECT id FROM dbo.envelopes WITH (UPDLOCK, HOLDLOCK) WHERE name = %s', (name,))
            if cur.fetchone():
                raise ConflictError('Envelope already exists')
            cur.execute('''INSERT INTO dbo.envelopes
                (name, monthly_allocation, current_balance, overspend_rule)
                OUTPUT INSERTED.id AS id VALUES (%s, %s, %s, %s)''',
                (name, monthly_allocation, monthly_allocation, overspend_rule))
            return cur.fetchone()['id']

    def allocate_funds(self, envelope_id, amount):
        amount = _money(validate_amount(amount))
        with _cursor(write=True) as cur:
            cur.execute('''UPDATE dbo.envelopes SET current_balance = current_balance + %s
                WHERE id = %s''', (amount, envelope_id))
            if cur.rowcount == 0:
                raise NotFoundError('Envelope not found')
            return True

    def record_transaction(self, envelope_id, amount, description='', merchant=''):
        amount = _money(validate_amount(amount))
        with _cursor(write=True) as cur:
            cur.execute('''SELECT current_balance, overspend_rule, name
                FROM dbo.envelopes WITH (UPDLOCK, HOLDLOCK) WHERE id = %s''', (envelope_id,))
            envelope = cur.fetchone()
            if not envelope:
                raise NotFoundError(f'Envelope {envelope_id} not found')
            if _money(envelope['current_balance']) - amount < 0 and envelope['overspend_rule'] == 'stop':
                return None
            cur.execute('''INSERT INTO dbo.transactions (envelope_id, amount, description, merchant, [date])
                OUTPUT INSERTED.id AS id VALUES (%s, %s, %s, %s, %s)''',
                (envelope_id, amount, description, merchant, datetime.now()))
            transaction_id = cur.fetchone()['id']
            cur.execute('UPDATE dbo.envelopes SET current_balance = current_balance - %s WHERE id = %s',
                        (amount, envelope_id))
            return transaction_id

    def execute_monthly_rollover(self):
        rollover_date, next_month = _month_bounds()
        current_month = rollover_date.strftime('%Y-%m')
        rolled_over = []
        with _cursor(write=True) as cur:
            cur.execute('SELECT * FROM dbo.envelopes WITH (UPDLOCK, HOLDLOCK) WHERE rollover_enabled = 1')
            envelopes = cur.fetchall()
            for envelope in envelopes:
                last_rollover = envelope['last_rollover_date']
                if last_rollover and str(last_rollover)[:7] == current_month:
                    continue
                envelope_id = envelope['id']
                current_balance = _money(envelope['current_balance'])
                monthly_allocation = _money(envelope['monthly_allocation'])
                cur.execute('''SELECT COALESCE(SUM(amount), 0) AS spent FROM dbo.transactions
                    WHERE envelope_id = %s AND [date] >= %s AND [date] < %s''',
                    (envelope_id, rollover_date, next_month))
                spent = cur.fetchone()['spent']
                cur.execute('''INSERT INTO dbo.envelope_history (envelope_id, month, allocated, spent, rolled_over)
                    VALUES (%s, %s, %s, %s, %s)''',
                    (envelope_id, current_month, monthly_allocation, spent, current_balance))
                cur.execute('''UPDATE dbo.envelopes SET current_balance = %s, last_rollover_date = %s
                    WHERE id = %s''', (current_balance + monthly_allocation, rollover_date, envelope_id))
                rolled_over.append(envelope_id)
        return rolled_over

    def auto_categorize_transaction(self, merchant, amount):
        merchant_lower = merchant.lower()
        with _cursor() as cur:
            cur.execute('SELECT envelope_id, merchant_pattern FROM dbo.category_rules ORDER BY priority DESC')
            for rule in cur.fetchall():
                if rule['merchant_pattern'].lower() in merchant_lower:
                    return rule['envelope_id']
        return None

    def process_bank_transaction(self, merchant, amount, description=''):
        merchant = validate_name(merchant)
        amount = validate_amount(amount)
        envelope_id = self.auto_categorize_transaction(merchant, amount)
        if envelope_id is None:
            return {'status': 'uncategorized', 'message': 'No matching envelope found'}
        transaction_id = self.record_transaction(envelope_id, amount, description, merchant)
        if transaction_id is None:
            raise ConflictError('Insufficient envelope funds')
        return {'status': 'processed', 'transaction_id': transaction_id, 'envelope_id': envelope_id}

    def get_envelope_status(self, envelope_id):
        start, end = _month_bounds()
        with _cursor() as cur:
            cur.execute('SELECT * FROM dbo.envelopes WHERE id = %s', (envelope_id,))
            envelope = cur.fetchone()
            if not envelope:
                return None
            cur.execute('''SELECT COALESCE(SUM(amount), 0) AS spent FROM dbo.transactions
                WHERE envelope_id = %s AND [date] >= %s AND [date] < %s''', (envelope_id, start, end))
            spent = _money(cur.fetchone()['spent'])
            cur.execute('SELECT COUNT(*) AS transaction_count FROM dbo.transactions WHERE envelope_id = %s', (envelope_id,))
            count = cur.fetchone()['transaction_count']
            allocation = _money(envelope['monthly_allocation'])
            balance = _money(envelope['current_balance'])
            return {'id': envelope['id'], 'name': envelope['name'], 'current_balance': float(balance),
                    'monthly_allocation': float(allocation), 'spent_this_month': float(spent),
                    'remaining_this_month': float(allocation - spent), 'overspend_rule': envelope['overspend_rule'],
                    'transaction_count': count, 'is_overspent': balance < 0}

    def get_all_envelopes(self):
        with _cursor() as cur:
            cur.execute('SELECT * FROM dbo.envelopes')
            return [_public_row(row) for row in cur.fetchall()]

    def get_recent_transactions(self, days=30):
        cutoff = datetime.utcnow().date() - timedelta(days=days)
        with _cursor() as cur:
            cur.execute('''SELECT t.*, e.name AS envelope_name FROM dbo.transactions t
                LEFT JOIN dbo.envelopes e ON t.envelope_id = e.id
                WHERE t.[date] >= %s ORDER BY t.[date] DESC''', (cutoff,))
            return [_public_row(row) for row in cur.fetchall()]

    def get_spending_breakdown(self, start_date=None, end_date=None):
        start_date = start_date or date.today().replace(day=1).isoformat()
        end_date = end_date or date.today().isoformat()
        with _cursor() as cur:
            cur.execute('''SELECT e.name, SUM(t.amount) AS total FROM dbo.transactions t
                JOIN dbo.envelopes e ON t.envelope_id = e.id
                WHERE CAST(t.[date] AS date) BETWEEN CAST(%s AS date) AND CAST(%s AS date)
                GROUP BY e.id, e.name ORDER BY total DESC''', (start_date, end_date))
            return [_public_row(row) for row in cur.fetchall()]
