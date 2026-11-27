"""Domain B: recurring bills, payments and projections on SQL Server."""
from contextlib import contextmanager
from datetime import datetime, date, timedelta
from decimal import Decimal
from calendar import monthrange
from dateutil.relativedelta import relativedelta
from database import get_db
from validation import (
    ConflictError, InputError, NotFoundError, validate_amount, validate_integer,
    validate_name, validate_text,
)


@contextmanager
def _cursor(write=False):
    db = get_db()
    cur = db.cursor()
    try:
        yield cur
        if write:
            db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        cur.close()


def _public_row(row):
    return {k: float(v) if isinstance(v, Decimal) else v for k, v in row.items()}


class BillManager:
    FREQUENCY_MAP = {'weekly': 7, 'biweekly': 14, 'monthly': 30,
                     'quarterly': 90, 'yearly': 365}

    def create_bill(self, name, amount, frequency, due_day, category='other'):
        name = validate_name(name)
        amount = validate_amount(amount)
        if not isinstance(frequency, str) or frequency not in self.FREQUENCY_MAP:
            raise InputError('Unsupported bill frequency')
        max_due_day = dict(self.FREQUENCY_MAP, monthly=31)[frequency]
        due_day = validate_integer(due_day, 1, max_due_day)
        category = validate_text(category, 'category', nullable=True, max_units=255)
        next_due = self._calculate_next_due_date(frequency, due_day)
        with _cursor(write=True) as cur:
            cur.execute('''INSERT INTO dbo.bills
                (name, amount, frequency, due_day, category, next_due_date)
                OUTPUT INSERTED.id AS id VALUES (%s, %s, %s, %s, %s, %s)''',
                (name, amount, frequency, due_day, category, next_due.isoformat()))
            bill_id = cur.fetchone()['id']
            self._create_payment_record(bill_id, next_due, cursor=cur)
        return bill_id

    def _calculate_next_due_date(self, frequency, due_day):
        today = date.today()
        if frequency == 'monthly':
            next_due = today.replace(day=min(due_day, monthrange(today.year, today.month)[1]))
            if next_due < today:
                following = today.replace(day=1) + relativedelta(months=1)
                next_due = following.replace(day=min(due_day, monthrange(following.year, following.month)[1]))
        elif frequency == 'yearly':
            next_due = date(today.year, 1, 1) + timedelta(days=due_day - 1)
            if next_due < today:
                next_due = date(today.year + 1, 1, 1) + timedelta(days=due_day - 1)
        else:
            days_offset = self.FREQUENCY_MAP.get(frequency, 30)
            next_due = today + timedelta(days=due_day if due_day < days_offset else 1)
        return next_due

    def _create_payment_record(self, bill_id, due_date, cursor=None):
        sql = "INSERT INTO dbo.bill_payments (bill_id, due_date, status) VALUES (%s, %s, 'unpaid')"
        args = (bill_id, self._as_date(due_date).isoformat())
        if cursor is not None:
            cursor.execute(sql, args)
        else:
            with _cursor(write=True) as cur:
                cur.execute(sql, args)

    def mark_as_paid(self, bill_id, payment_date=None, amount_paid=None):
        payment_date = self._as_date(payment_date if payment_date is not None else date.today()).isoformat()
        if amount_paid is not None:
            amount_paid = validate_amount(amount_paid)
        with _cursor(write=True) as cur:
            cur.execute('SELECT * FROM dbo.bills WITH (UPDLOCK, HOLDLOCK) WHERE id = %s', (bill_id,))
            bill = cur.fetchone()
            if not bill:
                raise NotFoundError(f'Bill {bill_id} not found')
            if not bill['active']:
                raise ConflictError('Bill is inactive')
            if amount_paid is None:
                amount_paid = float(bill['amount'])
            cur.execute("""SELECT TOP (1) * FROM dbo.bill_payments WITH (UPDLOCK, HOLDLOCK)
                WHERE bill_id = %s AND status = 'unpaid' ORDER BY due_date, id""", (bill_id,))
            payment = cur.fetchone()
            if payment is None:
                raise ConflictError('No unpaid occurrence found')
            next_due = self._calculate_next_occurrence(bill, payment['due_date'])
            cur.execute("""UPDATE dbo.bill_payments SET status = 'paid', paid_date = %s,
                amount_paid = %s WHERE id = %s""", (payment_date, amount_paid, payment['id']))
            cur.execute('UPDATE dbo.bills SET next_due_date = %s WHERE id = %s', (next_due.isoformat(), bill_id))
            self._create_payment_record(bill_id, next_due, cursor=cur)
        return True

    @staticmethod
    def _as_date(value):
        if isinstance(value, datetime):
            return value.date()
        if isinstance(value, date):
            return value
        return date.fromisoformat(value)

    def _calculate_next_occurrence(self, bill, current_due=None):
        current_due = self._as_date(bill['next_due_date'] if current_due is None else current_due)
        frequency = bill['frequency']
        if frequency == 'monthly':
            following = current_due + relativedelta(months=1)
            due_day = bill.get('due_day', current_due.day)
            return following.replace(day=min(due_day, monthrange(following.year, following.month)[1]))
        if frequency == 'yearly':
            return current_due + relativedelta(years=1)
        if frequency == 'quarterly':
            return current_due + relativedelta(months=3)
        return current_due + timedelta(days=self.FREQUENCY_MAP.get(frequency, 30))

    def project_upcoming_bills(self, months=3):
        months = validate_integer(months, 1, 120)
        end_date = date.today() + relativedelta(months=months)
        projections = []
        with _cursor() as cur:
            cur.execute('SELECT * FROM dbo.bills WHERE active = 1')
            bills = cur.fetchall()
            for bill in bills:
                if bill['next_due_date'] is None:
                    continue
                current_date = self._as_date(bill['next_due_date'])
                while current_date <= end_date:
                    cur.execute('SELECT status FROM dbo.bill_payments WHERE bill_id = %s AND due_date = %s',
                                (bill['id'], current_date.isoformat()))
                    payment = cur.fetchone()
                    projections.append({'bill_id': bill['id'], 'bill_name': bill['name'],
                                        'amount': float(bill['amount']), 'due_date': current_date.isoformat(),
                                        'category': bill['category'], 'status': payment['status'] if payment else 'projected'})
                    current_date = self._calculate_next_occurrence(bill, current_date)
        return sorted(projections, key=lambda x: x['due_date'])

    def get_upcoming_bills(self, days=30):
        end_date = (date.today() + timedelta(days=days)).isoformat()
        with _cursor() as cur:
            cur.execute('SELECT * FROM dbo.bills WHERE next_due_date <= %s AND active = 1 ORDER BY next_due_date', (end_date,))
            return [_public_row(row) for row in cur.fetchall()]

    def get_unpaid_bills(self):
        with _cursor() as cur:
            cur.execute("""SELECT b.*, bp.due_date, bp.status FROM dbo.bills b
                JOIN dbo.bill_payments bp ON b.id = bp.bill_id
                WHERE bp.status = 'unpaid' AND b.active = 1 ORDER BY bp.due_date""")
            return [_public_row(row) for row in cur.fetchall()]

    def get_monthly_bill_total(self, year, month):
        start = date(year, month, 1)
        end = start + relativedelta(months=1)
        with _cursor() as cur:
            cur.execute('''SELECT SUM(amount) AS total FROM dbo.bills
                WHERE next_due_date >= %s AND next_due_date < %s AND active = 1''',
                (start.isoformat(), end.isoformat()))
            return float(cur.fetchone()['total'] or 0)

    def deactivate_bill(self, bill_id):
        with _cursor(write=True) as cur:
            cur.execute('UPDATE dbo.bills SET active = 0 WHERE id = %s', (bill_id,))
            if cur.rowcount == 0:
                raise NotFoundError('Bill not found')
        return True

    def get_bill_payment_history(self, bill_id, limit=12):
        limit = validate_integer(limit, 1, 2147483647)
        with _cursor() as cur:
            cur.execute('SELECT TOP (%s) * FROM dbo.bill_payments WHERE bill_id = %s ORDER BY due_date DESC, id DESC', (limit, bill_id))
            return [_public_row(row) for row in cur.fetchall()]

    def get_all_bills(self):
        with _cursor() as cur:
            cur.execute('SELECT * FROM dbo.bills WHERE active = 1 ORDER BY next_due_date')
            return [_public_row(row) for row in cur.fetchall()]
