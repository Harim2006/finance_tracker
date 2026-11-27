import os
import time
import logging
from datetime import date, datetime
from flask import Flask, request, jsonify, g
from flask.json.provider import DefaultJSONProvider
import pymssql
from database import get_db, close_db
from validation import (
    ConflictError, InputError, NotFoundError, parse_amount, validate_integer,
    validate_optional_date, validate_text,
)

class ISOJSONProvider(DefaultJSONProvider):
    @staticmethod
    def default(value):
        if isinstance(value, (date, datetime)):
            return value.isoformat()
        return DefaultJSONProvider.default(value)

app = Flask(__name__)
app.json = ISOJSONProvider(app)
app.teardown_appcontext(close_db)
logging.basicConfig(level=logging.INFO, format='%(message)s', stream=__import__('sys').stdout)

@app.before_request
def begin_request():
    g.started = time.monotonic()

@app.after_request
def finish_request(response):
    origin = request.headers.get('Origin')
    if origin and origin == os.getenv('UI_ORIGIN', 'http://localhost:8080'):
        response.headers['Access-Control-Allow-Origin'] = origin
        response.headers['Access-Control-Allow-Methods'] = 'GET, POST, OPTIONS'
        response.headers['Access-Control-Allow-Headers'] = 'Content-Type'
    response.vary.add('Origin')
    app.logger.info('%s %s %s %.1fms', request.method, request.path, response.status_code, (time.monotonic()-g.started)*1000)
    return response

@app.errorhandler(NotFoundError)
def not_found(error):
    return jsonify(error=str(error)), 404

@app.errorhandler(ConflictError)
def conflict(error):
    return jsonify(error=str(error)), 409

@app.errorhandler(InputError)
def invalid(error):
    return jsonify(error=str(error)), 400

@app.errorhandler(pymssql.IntegrityError)
def integrity(error):
    return jsonify(error='Database constraint violated'), 409

@app.errorhandler(pymssql.Error)
def database_error(error):
    app.logger.exception('Database operation failed')
    return jsonify(error='Database unavailable'), 503

def data():
    try:
        value = request.get_json(silent=True)
    except RecursionError as error:
        raise InputError('JSON nesting is too deep') from error
    if not isinstance(value, dict):
        raise InputError('Expected a JSON object')
    return value

def required(value, key):
    if key not in value:
        raise InputError(f'Missing required field: {key}')
    return value[key]

@app.get('/health')
def health():
    try:
        db = get_db()
        cur = db.cursor()
        try:
            cur.execute('SELECT TOP (1) id FROM dbo.envelopes')
            cur.fetchall()
            cur.execute('UPDATE dbo.envelopes SET name = name WHERE 1 = 0')
        finally:
            db.rollback()
            cur.close()
        return jsonify(status='ok', db='ok', version=os.getenv('GIT_SHA', 'dev'))
    except Exception:
        app.logger.exception('Health check failed')
        return jsonify(status='unavailable', db='unavailable', version=os.getenv('GIT_SHA', 'dev')), 503

from budget_domain import BudgetEnvelopeManager
from llm_analyzer import FinanceLLMAnalyzer
import requests

manager = BudgetEnvelopeManager()
analyzer = FinanceLLMAnalyzer()

@app.get('/envelopes')
def envelopes():
    return jsonify(sorted(manager.get_all_envelopes(), key=lambda e: e['name']))

@app.post('/envelopes/create')
def create_envelope():
    d = data()
    return jsonify(id=manager.create_envelope(required(d,'name'), required(d,'monthly_allocation'), d.get('overspend_rule','stop')), status='created'), 201

@app.get('/envelopes/<int:envelope_id>')
def envelope_status(envelope_id):
    result = manager.get_envelope_status(envelope_id)
    if result is None:
        raise NotFoundError('Envelope not found')
    return jsonify(result)

@app.post('/envelopes/<int:envelope_id>/allocate')
def allocate(envelope_id):
    d = data()
    return jsonify(status='allocated' if manager.allocate_funds(envelope_id, required(d,'amount')) else 'failed')

@app.post('/envelopes/<int:envelope_id>/spend')
def spend(envelope_id):
    d = data()
    amount = required(d, 'amount')
    description = validate_text(d.get('description', ''), 'description', nullable=True, max_units=500)
    merchant = validate_text(d.get('merchant', ''), 'merchant', nullable=True, max_units=255)
    result = manager.record_transaction(envelope_id, amount, description, merchant)
    if result is None:
        raise ConflictError('Insufficient envelope funds')
    return jsonify(transaction_id=result), 201

@app.post('/envelopes/rollover')
def rollover():
    return jsonify(rolledover=len(manager.execute_monthly_rollover()))

@app.get('/transactions')
def transactions():
    return jsonify(manager.get_recent_transactions(validate_integer(request.args.get('days',30),1,3650)))

@app.get('/spending-breakdown')
def spending_breakdown():
    start_date = validate_optional_date(request.args.get('start_date'), 'start_date')
    end_date = validate_optional_date(request.args.get('end_date'), 'end_date')
    return jsonify(manager.get_spending_breakdown(start_date, end_date))

@app.post('/api/bank/transaction')
@app.post('/simulate-purchase')
def bank_transaction():
    d = data()
    amount = required(d, 'amount')
    if request.path == '/api/bank/transaction':
        amount = abs(parse_amount(amount))
    description = validate_text(d.get('description', ''), 'description', nullable=True, max_units=500)
    result = manager.process_bank_transaction(required(d, 'merchant'), amount, description)
    return jsonify(result), 201 if result['status']=='processed' else 200

class BillsUnavailable(Exception):
    pass

@app.errorhandler(BillsUnavailable)
def unavailable(error):
    return jsonify(error='Bills service unavailable; try again later'), 503

def fetch_bills(path, params=None):
    try:
        response = requests.get(os.environ['BILLS_URL'].rstrip('/') + path, params=params, timeout=(2,5))
        response.raise_for_status()
        result = response.json()
        if not isinstance(result,list):
            raise ValueError('Expected a list')
        return result
    except (requests.RequestException, ValueError, KeyError) as error:
        app.logger.warning('Bills service request failed: %s', type(error).__name__)
        raise BillsUnavailable() from error

def financial_context():
    return dict(envelopes=manager.get_all_envelopes(), bills=fetch_bills('/bills'), recent_transactions=manager.get_recent_transactions(30))

@app.post('/analysis/ask')
def ask():
    question = validate_text(data().get('question', ''), 'question')
    return jsonify(answer=analyzer.analyze_and_answer(question, financial_context()))

@app.get('/analysis/insights')
def insights():
    return jsonify(insights=analyzer.generate_insights(financial_context()))

@app.get('/api/dashboard/summary')
def summary():
    envelopes = manager.get_all_envelopes()
    bills = fetch_bills('/bills/due', {'days':30})
    return jsonify(total_allocated=sum(e['monthly_allocation'] for e in envelopes), spent_this_month=sum(t['total'] for t in manager.get_spending_breakdown()), upcoming_bills_30days=sum(b['amount'] for b in bills))

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.getenv('PORT','5001')), debug=False)
