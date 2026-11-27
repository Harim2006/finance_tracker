import os
import time
import logging
from datetime import date, datetime
from flask import Flask, request, jsonify, g
from flask.json.provider import DefaultJSONProvider
import pymssql
from database import get_db, close_db
from validation import ConflictError, InputError, NotFoundError, validate_integer, validate_optional_date

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
            cur.execute('SELECT TOP (1) id FROM dbo.bills')
            cur.fetchall()
            cur.execute('UPDATE dbo.bills SET name = name WHERE 1 = 0')
        finally:
            db.rollback()
            cur.close()
        return jsonify(status='ok', db='ok', version=os.getenv('GIT_SHA', 'dev'))
    except Exception:
        app.logger.exception('Health check failed')
        return jsonify(status='unavailable', db='unavailable', version=os.getenv('GIT_SHA', 'dev')), 503

from bill_domain import BillManager
manager = BillManager()

@app.get('/bills')
def bills():
    return jsonify(manager.get_all_bills())

@app.post('/bills/create')
def create_bill():
    d = data()
    return jsonify(id=manager.create_bill(required(d,'name'), required(d,'amount'), required(d,'frequency'), required(d,'due_day'), d.get('category','other')), status='created'), 201

@app.post('/bills/<int:bill_id>/pay')
def pay(bill_id):
    d = data()
    payment_date = validate_optional_date(d.get('payment_date'), 'payment_date')
    amount = d.get('amount_paid')
    manager.mark_as_paid(bill_id, payment_date, None if amount == '' else amount)
    return jsonify(status='paid')

@app.post('/bills/<int:bill_id>/deactivate')
def deactivate(bill_id):
    manager.deactivate_bill(bill_id)
    return jsonify(status='deactivated')

@app.get('/bills/upcoming')
def upcoming():
    return jsonify(manager.project_upcoming_bills(validate_integer(request.args.get('months',3),1,120)))

@app.get('/bills/due')
def due():
    return jsonify(manager.get_upcoming_bills(validate_integer(request.args.get('days',30),1,3650)))

@app.get('/bills/unpaid')
def unpaid():
    return jsonify(manager.get_unpaid_bills())

@app.get('/bills/<int:bill_id>/history')
def history(bill_id):
    return jsonify(manager.get_bill_payment_history(bill_id, validate_integer(request.args.get('limit',12),1,1000)))

@app.get('/bills/monthly-total')
def monthly_total():
    today = date.today()
    year = validate_integer(request.args.get('year',today.year),1,9998)
    month = validate_integer(request.args.get('month',today.month),1,12)
    return jsonify(total=manager.get_monthly_bill_total(year,month))

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.getenv('PORT','5002')), debug=False)
