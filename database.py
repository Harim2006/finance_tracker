"""
Database initialization and connection management
SQLite schema for envelope budgeting and bill tracking
"""
import sqlite3
import os
from flask import g, current_app


def get_db():
    """Get database connection for current request context"""
    if 'db' not in g:
        # Ensure data directory exists
        db_path = current_app.config['DATABASE']
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        
        g.db = sqlite3.connect(
            db_path,
            detect_types=sqlite3.PARSE_DECLTYPES
        )
        g.db.row_factory = sqlite3.Row
    return g.db


def close_db(e=None):
    """Close database connection"""
    db = g.pop('db', None)
    if db is not None:
        db.close()


def init_db():
    """Initialize database with schema"""
    db = get_db()
    
    # Domain A: Envelope Budgeting
    db.execute('''
        CREATE TABLE IF NOT EXISTS envelopes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            monthly_allocation REAL NOT NULL,
            current_balance REAL DEFAULT 0,
            overspend_rule TEXT DEFAULT 'stop',
            rollover_enabled INTEGER DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            last_rollover_date DATE
        )
    ''')
    
    db.execute('''
        CREATE TABLE IF NOT EXISTS transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            envelope_id INTEGER NOT NULL,
            amount REAL NOT NULL,
            date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            description TEXT,
            merchant TEXT,
            category TEXT,
            FOREIGN KEY (envelope_id) REFERENCES envelopes(id)
        )
    ''')
    
    db.execute('''
        CREATE TABLE IF NOT EXISTS envelope_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            envelope_id INTEGER NOT NULL,
            month TEXT NOT NULL,
            allocated REAL,
            spent REAL,
            rolled_over REAL,
            FOREIGN KEY (envelope_id) REFERENCES envelopes(id)
        )
    ''')
    
    # Domain B: Bill Tracking
    db.execute('''
        CREATE TABLE IF NOT EXISTS bills (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            amount REAL NOT NULL,
            frequency TEXT NOT NULL,
            due_day INTEGER NOT NULL,
            category TEXT,
            auto_pay INTEGER DEFAULT 0,
            next_due_date DATE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            active INTEGER DEFAULT 1
        )
    ''')
    
    db.execute('''
        CREATE TABLE IF NOT EXISTS bill_payments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            bill_id INTEGER NOT NULL,
            due_date DATE NOT NULL,
            paid_date DATE,
            amount_paid REAL,
            status TEXT DEFAULT 'unpaid',
            FOREIGN KEY (bill_id) REFERENCES bills(id)
        )
    ''')
    
    # Categorization rules for auto-assignment
    db.execute('''
        CREATE TABLE IF NOT EXISTS category_rules (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            merchant_pattern TEXT NOT NULL,
            envelope_id INTEGER NOT NULL,
            priority INTEGER DEFAULT 0,
            FOREIGN KEY (envelope_id) REFERENCES envelopes(id)
        )
    ''')
    
    # Create indexes for performance
    db.execute('CREATE INDEX IF NOT EXISTS idx_transactions_date ON transactions(date)')
    db.execute('CREATE INDEX IF NOT EXISTS idx_transactions_envelope ON transactions(envelope_id)')
    db.execute('CREATE INDEX IF NOT EXISTS idx_bills_due_date ON bills(next_due_date)')
    db.execute('CREATE INDEX IF NOT EXISTS idx_bill_payments_status ON bill_payments(status)')
    
    db.commit()


def seed_sample_data():
    """Seed database with sample data for testing"""
    db = get_db()
    
    # Check if already seeded
    count = db.execute('SELECT COUNT(*) FROM envelopes').fetchone()[0]
    if count > 0:
        return
    
    # Sample envelopes
    envelopes = [
        ('Groceries', 500.00, 500.00, 'borrow'),
        ('Dining Out', 200.00, 200.00, 'stop'),
        ('Transportation', 150.00, 150.00, 'borrow'),
        ('Entertainment', 100.00, 100.00, 'stop'),
        ('Utilities', 300.00, 300.00, 'stop'),
    ]
    
    for name, allocation, balance, rule in envelopes:
        db.execute(
            '''INSERT INTO envelopes (name, monthly_allocation, current_balance, overspend_rule)
               VALUES (?, ?, ?, ?)''',
            (name, allocation, balance, rule)
        )
    
    # Sample bills
    bills = [
        ('Netflix Subscription', 15.99, 'monthly', 5, 'entertainment'),
        ('Electricity Bill', 80.00, 'monthly', 15, 'utilities'),
        ('Internet Service', 50.00, 'monthly', 1, 'utilities'),
        ('Car Insurance', 120.00, 'monthly', 20, 'transportation'),
        ('Gym Membership', 40.00, 'monthly', 10, 'health'),
    ]
    
    from datetime import date, timedelta
    
    for name, amount, freq, due_day, category in bills:
        # Calculate next due date
        today = date.today()
        if today.day <= due_day:
            next_due = date(today.year, today.month, due_day)
        else:
            # Next month
            if today.month == 12:
                next_due = date(today.year + 1, 1, due_day)
            else:
                next_due = date(today.year, today.month + 1, due_day)
        
        db.execute(
            '''INSERT INTO bills (name, amount, frequency, due_day, category, next_due_date)
               VALUES (?, ?, ?, ?, ?, ?)''',
            (name, amount, freq, due_day, category, next_due.isoformat())
        )
    
    # Sample category rules
    rules = [
        ('walmart', 1, 100),
        ('whole foods', 1, 100),
        ('kroger', 1, 100),
        ('restaurant', 2, 90),
        ('cafe', 2, 90),
        ('uber', 3, 100),
        ('lyft', 3, 100),
        ('gas station', 3, 80),
    ]
    
    for pattern, env_id, priority in rules:
        db.execute(
            'INSERT INTO category_rules (merchant_pattern, envelope_id, priority) VALUES (?, ?, ?)',
            (pattern, env_id, priority)
        )
    
    db.commit()