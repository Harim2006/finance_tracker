"""
Personal Finance Envelope Budget + Bill Tracker
Main application entry point
"""
import os
import sqlite3

from validation import (
    validate_amount,
    validate_name,
    validate_integer,
    NotFoundError,
    ConflictError
)
from datetime import datetime
from flask import Flask, render_template, request, jsonify, redirect, url_for
from database import init_db, get_db, close_db, seed_sample_data
from budget_domain import BudgetEnvelopeManager
from bill_domain import BillManager
from llm_analyzer import FinanceLLMAnalyzer

app = Flask(__name__)
app.config['DATABASE'] = os.environ.get('DATA_DIR', './data') + '/finance.db'
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'dev-secret-key-change-in-production')

# Register database teardown
app.teardown_appcontext(close_db)

# Initialize database on startup
with app.app_context():
    init_db()
    # Optionally seed sample data on first run
    try:
        seed_sample_data()
    except:
        pass  # Already seeded

# Initialize domain managers
budget_manager = BudgetEnvelopeManager()
bill_manager = BillManager()
llm_analyzer = FinanceLLMAnalyzer()


@app.errorhandler(NotFoundError)
def handle_not_found(error):
    return jsonify({'error': str(error)}), 404


@app.errorhandler(ConflictError)
def handle_conflict(error):
    return jsonify({'error': str(error)}), 409


@app.errorhandler(ValueError)
def handle_invalid_input(error):
    return jsonify({'error': str(error)}), 400


@app.errorhandler(sqlite3.IntegrityError)
def handle_integrity_error(error):
    get_db().rollback()
    return jsonify({
        'error': 'Database constraint violated'
    }), 409


def get_request_data():
    if request.is_json:
        data = request.get_json(silent=True)

        if not isinstance(data, dict):
            raise ValueError("Expected a JSON object")

        return data

    return request.form


def required_field(data, field):
    if field not in data:
        raise ValueError(f"Missing required field: {field}")

    return data[field]





@app.route('/')
def index():
    """Dashboard showing overview of envelopes and bills"""
    db = get_db()
    
    # Get envelope summary
    envelopes = db.execute(
        'SELECT * FROM envelopes ORDER BY name'
    ).fetchall()
    
    # Get upcoming bills
    upcoming_bills = db.execute(
        '''SELECT * FROM bills 
           WHERE next_due_date >= date('now') 
           ORDER BY next_due_date LIMIT 5'''
    ).fetchall()
    
    # Get recent transactions
    recent_transactions = db.execute(
        '''SELECT t.*, e.name as envelope_name 
           FROM transactions t
           LEFT JOIN envelopes e ON t.envelope_id = e.id
           ORDER BY t.date DESC LIMIT 10'''
    ).fetchall()
    
    return render_template('index.html', 
                         envelopes=envelopes,
                         upcoming_bills=upcoming_bills,
                         recent_transactions=recent_transactions)


# ===== ENVELOPE BUDGET ROUTES =====

@app.route('/envelopes')
def envelopes():
    """List all budget envelopes"""
    db = get_db()
    envelopes = db.execute('SELECT * FROM envelopes ORDER BY name').fetchall()
    return render_template('envelope.html', envelopes=envelopes)



@app.route('/envelopes/create', methods=['POST'])
def create_envelope():
    """Create a new budget envelope"""
    data = get_request_data()

    envelope_id = budget_manager.create_envelope(
        name=required_field(data, 'name'),
        monthly_allocation=required_field(
            data, 'monthly_allocation'
        ),
        overspend_rule=data.get('overspend_rule', 'stop')
    )

    if request.is_json:
        return jsonify({
            'id': envelope_id,
            'status': 'created'
        }), 201

    return redirect(url_for('envelopes'))



@app.route('/envelopes/<int:envelope_id>/allocate', methods=['POST'])
def allocate_to_envelope(envelope_id):
    """Allocate funds to an envelope"""
    data = get_request_data()
    amount = float(data['amount'])
    
    success = budget_manager.allocate_funds(envelope_id, amount)
    
    if request.is_json:
        return jsonify({'status': 'allocated' if success else 'failed'})
    return redirect(url_for('envelopes'))



@app.route('/envelopes/<int:envelope_id>/spend', methods=['POST'])
def spend_from_envelope(envelope_id):
    """Record a spending transaction from an envelope"""
    data = get_request_data()

    transaction_id = budget_manager.record_transaction(
        envelope_id=envelope_id,
        amount=required_field(data, 'amount'),
        description=data.get('description', ''),
        merchant=data.get('merchant', '')
    )

    if transaction_id is None:
        raise ConflictError("Insufficient envelope funds")

    if request.is_json:
        return jsonify({
            'transaction_id': transaction_id
        }), 201

    return redirect(url_for('envelopes'))



@app.route('/envelopes/rollover', methods=['POST'])
def rollover_envelopes():
    """Execute monthly rollover for all envelopes"""
    results = budget_manager.execute_monthly_rollover()
    
    if request.is_json:
        return jsonify({'rolledover': len(results)})
    return redirect(url_for('envelopes'))


# ===== BILL TRACKER ROUTES =====

@app.route('/bills')
def bills():
    """List all bills and subscriptions"""
    db = get_db()
    bills = db.execute('SELECT * FROM bills ORDER BY next_due_date').fetchall()
    return render_template('bills.html', bills=bills)



@app.route('/bills/create', methods=['POST'])
def create_bill():
    """Create a new recurring bill"""
    data = get_request_data()

    bill_id = bill_manager.create_bill(
        name=required_field(data, 'name'),
        amount=required_field(data, 'amount'),
        frequency=required_field(data, 'frequency'),
        due_day=required_field(data, 'due_day'),
        category=data.get('category', 'other')
    )

    if request.is_json:
        return jsonify({
            'id': bill_id,
            'status': 'created'
        }), 201

    return redirect(url_for('bills'))




@app.route('/bills/<int:bill_id>/pay', methods=['POST'])
def pay_bill(bill_id):
    """Mark a bill occurrence as paid"""
    data = get_request_data()

    amount_paid = data.get('amount_paid')

    if amount_paid == '':
        amount_paid = None

    bill_manager.mark_as_paid(
        bill_id=bill_id,
        payment_date=data.get('payment_date') or None,
        amount_paid=amount_paid
    )

    if request.is_json:
        return jsonify({'status': 'paid'}), 200

    return redirect(url_for('bills'))



@app.route('/bills/<int:bill_id>/deactivate', methods=['POST'])
def deactivate_bill(bill_id):
    """Deactivate a recurring bill"""
    bill_manager.deactivate_bill(bill_id)

    if request.is_json:
        return jsonify({'status': 'deactivated'}), 200

    return redirect(url_for('bills'))




@app.route('/bills/upcoming')
def upcoming_bills():
    """Get projection of upcoming bills"""
    months = request.args.get('months', 3) 
    projection = bill_manager.project_upcoming_bills(months)
    
    return jsonify(projection)


# ===== FAKE BANK API =====

@app.route('/api/bank/transaction', methods=['POST'])
def fake_bank_transaction():
    """
    Fake bank API endpoint - simulates a bank sending transaction data
    External systems (or our simulator) POST here when a purchase is made
    """
    data = request.get_json()
    
    # Auto-categorize and assign to envelope
    merchant = data.get('merchant', '')
    amount = abs(float(data.get('amount', 0)))
    
    # Simple categorization logic
    envelope_id = budget_manager.auto_categorize_transaction(merchant, amount)
    
    if envelope_id:
        transaction_id = budget_manager.record_transaction(
            envelope_id=envelope_id,
            amount=amount,
            description=data.get('description', ''),
            merchant=merchant
        )
        
        return jsonify({
            'status': 'processed',
            'transaction_id': transaction_id,
            'envelope_id': envelope_id
        }), 201
    else:
        return jsonify({
            'status': 'uncategorized',
            'message': 'No matching envelope found'
        }), 200


@app.route('/simulate-purchase', methods=['POST'])
def simulate_purchase():
    """Simulate a purchase for testing the bank API integration"""
    data = get_request_data()
    
    # Call our own fake bank API
    import requests
    response = requests.post(
        request.url_root + 'api/bank/transaction',
        json={
            'merchant': data['merchant'],
            'amount': -float(data['amount']),
            'description': data.get('description', ''),
            'timestamp': datetime.now().isoformat()
        }
    )
    
    if request.is_json:
        return jsonify(response.json())
    return redirect(url_for('index'))


# ===== LLM ANALYSIS ROUTES =====

@app.route('/analysis/ask', methods=['POST'])
def ask_llm():
    """Ask the LLM analyzer a question about finances"""
    data = get_request_data()
    question = data.get('question', '')
    
    # Get financial context
    context = {
        'envelopes': budget_manager.get_all_envelopes(),
        'bills': bill_manager.get_all_bills(),
        'recent_transactions': budget_manager.get_recent_transactions(30)
    }
    
    answer = llm_analyzer.analyze_and_answer(question, context)
    
    return jsonify({'answer': answer})


@app.route('/analysis/insights')
def get_insights():
    """Get automated financial insights"""
    context = {
        'envelopes': budget_manager.get_all_envelopes(),
        'bills': bill_manager.get_all_bills(),
        'recent_transactions': budget_manager.get_recent_transactions(30)
    }
    
    insights = llm_analyzer.generate_insights(context)
    
    return jsonify({'insights': insights})


# ===== DASHBOARD API =====

@app.route('/api/dashboard/summary')
def dashboard_summary():
    """Get dashboard summary statistics"""
    envelopes = budget_manager.get_all_envelopes()
    bills = bill_manager.get_upcoming_bills(30)
    transactions = budget_manager.get_recent_transactions(30)
    
    total_allocated = sum(e['monthly_allocation'] for e in envelopes)
    spent_this_month = sum(t['amount'] for t in transactions)
    upcoming_bills_total = sum(b['amount'] for b in bills)
    
    return jsonify({
        'total_allocated': total_allocated,
        'spent_this_month': spent_this_month,
        'upcoming_bills_30days': upcoming_bills_total
    })


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=os.environ.get('DEBUG', 'False') == 'True')