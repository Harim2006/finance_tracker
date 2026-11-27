"""Exercise the split Flask applications against their published OpenAPI contracts."""

from datetime import date, datetime, timedelta
from decimal import Decimal
from importlib import import_module
from pathlib import Path
import re
import sys
import unittest
from unittest.mock import Mock, patch

import pymssql
import requests
import yaml
from openapi_schema_validator import OAS30Validator, oas30_format_checker
from openapi_spec_validator import OpenAPIV30SpecValidator


ROOT = Path(__file__).parent
SERVICE_DOMAINS = {"budget": "budget_domain", "bills": "bill_domain"}
HTTP_METHODS = {"get", "put", "post", "delete", "options", "head", "patch", "trace"}


def load_document(service):
    return yaml.safe_load((ROOT / "services" / service / "openapi.yaml").read_text(encoding="utf-8"))


def load_service(service):
    service_path = ROOT / "services" / service
    domain_name = SERVICE_DOMAINS[service]
    # The containers import local modules by bare name, as does the legacy app.
    # Scope those imports so the apps bind their own modules during discovery.
    with patch.dict(sys.modules), patch.object(sys, "path", [str(service_path), *sys.path]):
        for name in ("app", "database", domain_name, "validation", "llm_analyzer"):
            sys.modules.pop(name, None)
        return import_module("app"), sys.modules[domain_name]


def resolve_reference(document, value):
    if "$ref" in value:
        for key in value["$ref"][2:].split("/"):
            document = document[key]
        return document
    return value


def operations(document):
    return {
        (method, path): operation
        for path, path_item in document["paths"].items()
        for method, operation in path_item.items()
        if method in HTTP_METHODS
    }


def schema_validator(document):
    return OAS30Validator(document, format_checker=oas30_format_checker)


class OpenAPIDocumentTests(unittest.TestCase):
    def test_documents_parse_and_validate_as_openapi_3_0_3(self):
        for service in SERVICE_DOMAINS:
            with self.subTest(service=service):
                document = load_document(service)
                self.assertEqual(document["openapi"], "3.0.3")
                OpenAPIV30SpecValidator(document).validate()

    def test_methods_and_paths_match_the_flask_route_maps(self):
        for service in SERVICE_DOMAINS:
            with self.subTest(service=service):
                module, _ = load_service(service)
                actual = {
                    (method.lower(), re.sub(r"<(?:[^:<>]+:)?([^<>]+)>", r"{\1}", rule.rule))
                    for rule in module.app.url_map.iter_rules()
                    if rule.endpoint != "static"
                    for method in rule.methods - {"HEAD", "OPTIONS"}
                }
                self.assertEqual(set(operations(load_document(service))), actual)

    def test_published_request_and_response_examples_match_their_schemas(self):
        for service in SERVICE_DOMAINS:
            document = load_document(service)
            validator = schema_validator(document)
            for (method, path), operation in operations(document).items():
                bodies = dict(operation["responses"])
                if "requestBody" in operation:
                    bodies["request"] = operation["requestBody"]
                for name, body in bodies.items():
                    content = resolve_reference(document, body)["content"]
                    for media in content.values():
                        examples = [example["value"] for example in media.get("examples", {}).values()]
                        if "example" in media:
                            examples.append(media["example"])
                        for example in examples:
                            with self.subTest(service=service, method=method, path=path, body=name):
                                validator.evolve(schema=media["schema"]).validate(example)

    def test_automatic_head_and_cors_preflight(self):
        for service in SERVICE_DOMAINS:
            with self.subTest(service=service):
                module, _ = load_service(service)
                client = module.app.test_client()
                with patch.object(module, "get_db", return_value=Mock()):
                    response = client.head("/health")
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.data, b"")
                create_path = "/envelopes/create" if service == "budget" else "/bills/create"
                with patch.dict("os.environ", {"UI_ORIGIN": "http://localhost:8080"}):
                    preflight = client.options(create_path, headers={
                        "Origin": "http://localhost:8080",
                        "Access-Control-Request-Method": "POST",
                        "Access-Control-Request-Headers": "Content-Type",
                    })
                self.assertEqual(preflight.status_code, 200)
                self.assertEqual(preflight.headers["Access-Control-Allow-Origin"], "http://localhost:8080")
                self.assertEqual(preflight.headers["Access-Control-Allow-Methods"], "GET, POST, OPTIONS")
                self.assertEqual(preflight.headers["Access-Control-Allow-Headers"], "Content-Type")
                self.assertIn("Origin", preflight.vary)


class ServiceContract:
    @classmethod
    def setUpClass(cls):
        cls.module, cls.domain = load_service(cls.service)
        cls.document = load_document(cls.service)
        cls.operations = operations(cls.document)
        cls.validator = schema_validator(cls.document)

    def setUp(self):
        self.client = self.module.app.test_client()
        self.connection = Mock()
        self.cursor = self.connection.cursor.return_value
        self.cursor.fetchall.return_value = []
        self.cursor.fetchone.return_value = None
        self.cursor.rowcount = 1
        self.domain_db = self.enterContext(patch.object(self.domain, "get_db", return_value=self.connection))
        self.health_db = self.enterContext(patch.object(self.module, "get_db", return_value=self.connection))
        self.enterContext(patch.object(self.module.app.logger, "disabled", True))

    def assert_contract(self, method, path, status, *, path_id=1, **request):
        operation = self.operations[method, path]
        if status < 400 and "json" in request:
            body = operation["requestBody"]["content"]["application/json"]
            self.validator.evolve(schema=body["schema"]).validate(request["json"])
        actual_path = re.sub(r"\{[^}]+\}", str(path_id), path)
        response = self.client.open(actual_path, method=method.upper(), **request)
        self.assertEqual(response.status_code, status)
        documented = resolve_reference(self.document, operation["responses"][str(status)])
        schema = documented["content"][response.mimetype]["schema"]
        body = response.get_json() if response.is_json else response.get_data(as_text=True)
        self.validator.evolve(schema=schema).validate(body)
        return body

    def assert_bad_input(self, method, path, message, **request):
        self.assertEqual(self.assert_contract(method, path, 400, **request), {"error": message})
        self.domain_db.assert_not_called()

    def test_malformed_and_non_object_json(self):
        for raw in ("", "{broken", "null", "[]", '"text"', "42", "false"):
            with self.subTest(raw=raw):
                self.assert_bad_input(
                    "post", self.create_path, "Expected a JSON object", data=raw, content_type="application/json",
                )
        depth = sys.getrecursionlimit() + 1
        nested = '{"value":' * depth + '0' + '}' * depth
        self.assert_bad_input(
            "post", self.create_path, "JSON nesting is too deep", data=nested, content_type="application/json",
        )

    def test_unexpected_value_error_remains_a_server_error(self):
        self.domain_db.side_effect = ValueError("Internal database configuration error")
        response = self.client.get(self.list_path)
        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.mimetype, "text/html")
        self.assertNotIn("Internal database configuration error", response.get_data(as_text=True))

    def test_health_contract(self):
        with patch.dict("os.environ", {"GIT_SHA": "contract-test-sha"}):
            healthy = self.assert_contract("get", "/health", 200)
            self.connection.rollback.assert_called_once()
            self.health_db.side_effect = pymssql.OperationalError("Database offline")
            unhealthy = self.assert_contract("get", "/health", 503)
        self.assertEqual(healthy["version"], "contract-test-sha")
        self.assertEqual(unhealthy["version"], "contract-test-sha")


class BudgetContractTests(ServiceContract, unittest.TestCase):
    service = "budget"
    create_path = "/envelopes/create"
    list_path = "/envelopes"

    def test_envelope_list_and_detail(self):
        envelope = {
            "id": 1, "name": "Groceries", "monthly_allocation": Decimal("300.00"),
            "current_balance": Decimal("245.50"), "overspend_rule": "stop",
            "rollover_enabled": True, "created_at": datetime(2026, 11, 1, 8, 30),
            "last_rollover_date": None,
        }
        self.cursor.fetchall.return_value = [envelope]
        self.assert_contract("get", "/envelopes", 200)
        self.cursor.fetchone.side_effect = [envelope, {"spent": Decimal("54.50")}, {"transaction_count": 1}]
        self.assert_contract("get", "/envelopes/{envelope_id}", 200)

    def test_create_allocate_and_spend(self):
        self.cursor.fetchone.side_effect = [None, {"id": 1}]
        self.assert_contract("post", "/envelopes/create", 201, json={"name": "Groceries", "monthly_allocation": "300.00"})
        self.assert_contract("post", "/envelopes/{envelope_id}/allocate", 200, json={"amount": 10})
        self.cursor.fetchone.side_effect = [
            {"name": "Groceries", "current_balance": Decimal("300.00"), "overspend_rule": "stop"}, {"id": 7},
        ]
        self.assert_contract("post", "/envelopes/{envelope_id}/spend", 201, json={"amount": 54.5, "merchant": None})

    def test_rollover_skips_previously_processed_envelopes(self):
        today = date.today()
        envelope = {"id": 1, "current_balance": 50, "monthly_allocation": 300, "last_rollover_date": None}
        self.cursor.fetchall.return_value = [envelope]
        self.cursor.fetchone.return_value = {"spent": 250}
        first = self.assert_contract("post", "/envelopes/rollover", 200)
        envelope["last_rollover_date"] = today
        second = self.assert_contract("post", "/envelopes/rollover", 200)
        self.assertEqual((first["rolledover"], second["rolledover"]), (1, 0))

    def test_transactions_and_spending_breakdown(self):
        transaction = {
            "id": 7, "envelope_id": 1, "amount": Decimal("54.50"),
            "date": datetime(2026, 11, 24, 17, 25, 30, 123456), "description": None,
            "merchant": "Local Market", "category": None, "envelope_name": "Groceries",
        }
        self.cursor.fetchall.side_effect = [[transaction], [{"name": "Groceries", "total": Decimal("54.50")}]]
        self.assert_contract("get", "/transactions", 200, query_string={"days": 14})
        self.assert_contract("get", "/spending-breakdown", 200, query_string={"start_date": "2026-11-01"})

    def test_purchase_and_bank_import_outcomes(self):
        for path, amount in (("/api/bank/transaction", "-54.50"), ("/simulate-purchase", 54.5)):
            with self.subTest(path=path):
                request = {"merchant": "Local Market", "amount": amount}
                self.cursor.fetchall.return_value = []
                self.assert_contract("post", path, 200, json=request)
                self.cursor.fetchall.return_value = [{"merchant_pattern": "market", "envelope_id": 1}]
                self.cursor.fetchone.side_effect = [
                    {"name": "Groceries", "current_balance": 300, "overspend_rule": "stop"}, {"id": 7},
                ]
                self.assert_contract("post", path, 201, json=request)
        self.assert_contract("post", "/simulate-purchase", 400, json={"merchant": "Local Market", "amount": -54.5})

    def test_analysis_and_dashboard_with_bills(self):
        envelopes = [{"name": "Groceries", "monthly_allocation": 300, "current_balance": 300}]
        spending = [{"total": Decimal("54.50")}]
        self.cursor.fetchall.side_effect = [envelopes, [], envelopes, [], envelopes, spending]
        with patch.dict("os.environ", {"BILLS_URL": "http://bills:5002"}):
            with patch.object(self.module.requests, "get") as fetch:
                fetch.return_value.json.return_value = []
                self.assert_contract("post", "/analysis/ask", 200, json={})
                self.assert_contract("get", "/analysis/insights", 200)
                fetch.assert_called_with("http://bills:5002/bills", params=None, timeout=(2, 5))
                fetch.return_value.json.return_value = [{"amount": 45}]
                self.assert_contract("get", "/api/dashboard/summary", 200)
                fetch.assert_called_with("http://bills:5002/bills/due", params={"days": 30}, timeout=(2, 5))

    def test_validation_not_found_and_conflict_responses(self):
        self.assert_contract("post", "/envelopes/create", 400, json={"name": "Groceries"})
        self.assert_contract("get", "/transactions", 400, query_string={"days": 0})
        self.assert_contract("get", "/envelopes/{envelope_id}", 404)
        self.cursor.fetchone.return_value = {"id": 1, "current_balance": 0, "overspend_rule": "stop", "name": "Groceries"}
        self.assert_contract("post", "/envelopes/create", 409, json={"name": "Groceries", "monthly_allocation": 300})
        self.assert_contract("post", "/envelopes/{envelope_id}/spend", 409, json={"amount": 5})

    def test_bills_failure_returns_dependency_error_on_all_callers(self):
        with patch.dict("os.environ", {"BILLS_URL": "http://bills:5002"}):
            with patch.object(self.module.requests, "get", side_effect=requests.Timeout):
                for method, path, request in (
                    ("post", "/analysis/ask", {"json": {}}),
                    ("get", "/analysis/insights", {}),
                    ("get", "/api/dashboard/summary", {}),
                ):
                    with self.subTest(path=path):
                        result = self.assert_contract(method, path, 503, **request)
                        self.assertEqual(result, {"error": "Bills service unavailable; try again later"})

    def test_spending_breakdown_rejects_invalid_dates_before_connecting(self):
        for field in ("start_date", "end_date"):
            for value in ("invalid-date", "2026-02-29", "2026-13-01", "2026-11-01T12:00:00"):
                with self.subTest(field=field, value=value):
                    self.assert_bad_input(
                        "get", "/spending-breakdown", f"{field} must be a valid ISO 8601 date",
                        query_string={field: value},
                    )

    def test_spending_breakdown_passes_parsed_dates_and_keeps_empty_defaults(self):
        leap_day = date(2028, 2, 29)
        self.assert_contract("get", "/spending-breakdown", 200, query_string={
            "start_date": "20280229", "end_date": "2028-W09-2",
        })
        self.assertEqual(self.cursor.execute.call_args.args[1], (leap_day, leap_day))

        self.assert_contract("get", "/spending-breakdown", 200, query_string={"start_date": "", "end_date": ""})
        today = date.today()
        self.assertEqual(self.cursor.execute.call_args.args[1], (today.replace(day=1).isoformat(), today.isoformat()))

    def test_spending_breakdown_preserves_database_error_response(self):
        self.cursor.execute.side_effect = pymssql.OperationalError("Database offline")
        result = self.assert_contract("get", "/spending-breakdown", 503, query_string={"start_date": "2026-11-01"})
        self.assertEqual(result, {"error": "Database unavailable"})

    def test_non_string_question_is_rejected_before_loading_context(self):
        with patch.object(self.module, "fetch_bills") as fetch:
            for value in (None, [], {}, 0, False, 42, True):
                with self.subTest(value=value):
                    self.assert_bad_input("post", "/analysis/ask", "question must be a string", json={"question": value})
            fetch.assert_not_called()

    def test_invalid_envelope_fields(self):
        valid = {"name": "Groceries", "monthly_allocation": 50}
        for field, value, message in (
            ("name", None, "Name is required"), ("name", [], "Name is required"),
            ("name", "   ", "Name is required"),
            ("name", "\U0001F4B3" * 128, "name exceeds the maximum length of 255 UTF-16 code units"),
            ("overspend_rule", {}, "Invalid overspend rule"),
            ("overspend_rule", None, "Invalid overspend rule"),
            ("monthly_allocation", False, "Amount must be numeric"),
            ("monthly_allocation", 10**400, "Amount exceeds the supported range"),
        ):
            with self.subTest(field=field, message=message):
                self.assert_bad_input("post", self.create_path, message, json={**valid, field: value})
        for field in valid:
            with self.subTest(missing=field):
                payload = {key: value for key, value in valid.items() if key != field}
                self.assert_bad_input("post", self.create_path, f"Missing required field: {field}", json=payload)

    def test_invalid_transaction_fields(self):
        spend_path = "/envelopes/{envelope_id}/spend"
        for value in ([], {}, 42, True):
            for field in ("merchant", "description"):
                with self.subTest(field=field, value=value):
                    self.assert_bad_input(
                        "post", spend_path, f"{field} must be a string or null", json={"amount": 5, field: value},
                    )
        for path in ("/simulate-purchase", "/api/bank/transaction"):
            with self.subTest(path=path):
                self.assert_bad_input("post", path, "description must be a string or null", json={
                    "amount": 5, "merchant": "Market", "description": {},
                })
                self.assert_bad_input("post", path, "Merchant is required", json={"amount": 5, "merchant": True})
                self.assert_bad_input("post", path, "Missing required field: merchant", json={"amount": 5})
        self.assert_bad_input("post", spend_path, "description exceeds the maximum length of 500 UTF-16 code units", json={
            "amount": 5, "description": "x" * 501,
        })
        self.assert_bad_input("post", spend_path, "merchant must contain valid Unicode", json={"amount": 5, "merchant": "\ud800"})

    def test_invalid_amounts_on_all_budget_amount_routes(self):
        for path, fields in (
            ("/envelopes/{envelope_id}/allocate", {}), ("/envelopes/{envelope_id}/spend", {}),
            ("/simulate-purchase", {"merchant": "Market"}), ("/api/bank/transaction", {"merchant": "Market"}),
        ):
            for value, message in (
                (None, "Amount must be numeric"), ([], "Amount must be numeric"), ({}, "Amount must be numeric"),
                (False, "Amount must be numeric"), ("n/a", "Amount must be numeric"),
                ("1e999", "Amount must be finite"), (1e16, "Amount exceeds the supported range"),
                (10**400, "Amount exceeds the supported range"),
            ):
                with self.subTest(path=path, amount_type=type(value).__name__, message=message):
                    self.assert_bad_input("post", path, message, json={**fields, "amount": value})
            self.assert_bad_input("post", path, "Missing required field: amount", json=fields)


class BillsContractTests(ServiceContract, unittest.TestCase):
    service = "bills"
    create_path = "/bills/create"
    list_path = "/bills"

    def setUp(self):
        super().setUp()
        self.bill = {
            "id": 1, "name": "Internet", "amount": Decimal("45.00"), "frequency": "yearly",
            "due_day": 60, "category": None, "auto_pay": False,
            "next_due_date": date.today() + timedelta(days=2), "created_at": datetime(2026, 11, 1, 8, 30),
            "active": True,
        }

    def test_list_due_and_unpaid_bill_shapes(self):
        self.cursor.fetchall.return_value = [self.bill]
        self.assert_contract("get", "/bills", 200)
        self.assert_contract("get", "/bills/due", 200, query_string={"days": 30})
        self.cursor.fetchall.return_value = [dict(self.bill, due_date=self.bill["next_due_date"], status="unpaid")]
        self.assert_contract("get", "/bills/unpaid", 200)

    def test_create_pay_and_deactivate(self):
        self.cursor.fetchone.return_value = {"id": 1}
        self.assert_contract("post", "/bills/create", 201, json={
            "name": "Internet", "amount": "45.00", "frequency": "yearly", "due_day": "60", "category": None,
        })
        self.cursor.fetchone.side_effect = [self.bill, {"id": 5, "due_date": self.bill["next_due_date"]}]
        self.assert_contract("post", "/bills/{bill_id}/pay", 200, json={"payment_date": None, "amount_paid": ""})
        for _ in range(2):
            self.assert_contract("post", "/bills/{bill_id}/deactivate", 200)

    def test_bill_projection(self):
        self.cursor.fetchall.return_value = [self.bill]
        self.cursor.fetchone.return_value = {"status": "unpaid"}
        results = self.assert_contract("get", "/bills/upcoming", 200, query_string={"months": 1})
        self.assertEqual(len(results), 1)

    def test_payment_history_and_monthly_total(self):
        due_date = self.bill["next_due_date"]
        self.cursor.fetchall.return_value = [
            {"id": 6, "bill_id": 1, "due_date": due_date, "paid_date": None, "amount_paid": None, "status": "unpaid"},
            {"id": 5, "bill_id": 1, "due_date": due_date, "paid_date": due_date, "amount_paid": Decimal("45.00"), "status": "paid"},
        ]
        self.assert_contract("get", "/bills/{bill_id}/history", 200, query_string={"limit": 2})
        self.cursor.fetchall.return_value = []
        empty = self.assert_contract("get", "/bills/{bill_id}/history", 200, path_id=0)
        self.assertEqual(empty, [])
        self.cursor.fetchone.return_value = {"total": Decimal("45.00")}
        self.assert_contract("get", "/bills/monthly-total", 200, query_string={"year": 2026, "month": 11})

    def test_invalid_request_fields_and_query_bounds(self):
        invalid_bill = {"name": "Internet", "amount": 45, "frequency": "weekly", "due_day": 8}
        self.assert_contract("post", "/bills/create", 400, json=invalid_bill)
        self.assert_contract("post", "/bills/{bill_id}/pay", 400, json={"payment_date": "2026-02-30"})
        for path, query in (
            ("/bills/upcoming", {"months": 121}), ("/bills/due", {"days": 0}),
            ("/bills/{bill_id}/history", {"limit": 1001}), ("/bills/monthly-total", {"month": 13}),
        ):
            with self.subTest(path=path):
                self.assert_contract("get", path, 400, query_string=query)

    def test_missing_and_inactive_bill_errors(self):
        self.assert_contract("post", "/bills/{bill_id}/pay", 404, json={})
        self.cursor.rowcount = 0
        self.assert_contract("post", "/bills/{bill_id}/deactivate", 404)
        self.cursor.fetchone.return_value = dict(self.bill, active=False)
        self.assert_contract("post", "/bills/{bill_id}/pay", 409, json={})

    def test_database_error_and_constraint_conflict(self):
        self.cursor.execute.side_effect = pymssql.OperationalError("Database offline")
        self.assert_contract("get", "/bills", 503)
        self.cursor.execute.side_effect = pymssql.IntegrityError("Database constraint violated")
        self.assert_contract("post", "/bills/create", 409, json={
            "name": "Internet", "amount": 45, "frequency": "monthly", "due_day": 15,
        })

    def test_invalid_bill_creation_fields(self):
        valid = {"name": "Internet", "amount": 45, "frequency": "monthly", "due_day": 15}
        invalid = {
            "name": ((None, [], {}, 12, True, " "), "Name is required"),
            "amount": ((None, [], {}, False, "bad"), "Amount must be numeric"),
            "frequency": ((None, [], {}, 12, False, "annual"), "Unsupported bill frequency"),
            "due_day": ((None, [], {}, 1.5, True, "bad"), "Expected an integer"),
            "category": (([], {}, 12, False), "category must be a string or null"),
        }
        for field, (values, message) in invalid.items():
            for value in values:
                with self.subTest(field=field, value=value):
                    self.assert_bad_input("post", self.create_path, message, json={**valid, field: value})
        for field in valid:
            with self.subTest(missing=field):
                payload = {key: value for key, value in valid.items() if key != field}
                self.assert_bad_input("post", self.create_path, f"Missing required field: {field}", json=payload)
        self.assert_bad_input("post", self.create_path, "category exceeds the maximum length of 255 UTF-16 code units", json={
            **valid, "category": "x" * 256,
        })
        self.assert_bad_input("post", self.create_path, "Amount exceeds the supported range", json={**valid, "amount": 10**400})

    def test_due_day_limits_remain_frequency_specific(self):
        for frequency, maximum in (("weekly", 7), ("biweekly", 14), ("monthly", 31), ("quarterly", 90), ("yearly", 365)):
            with self.subTest(frequency=frequency):
                payload = {"name": "Internet", "amount": 45, "frequency": frequency}
                self.domain_db.reset_mock()
                self.assert_bad_input("post", self.create_path, f"Value must be between 1 and {maximum}", json={
                    **payload, "due_day": maximum + 1,
                })
                self.cursor.fetchone.return_value = {"id": 1}
                self.assert_contract("post", self.create_path, 201, json={**payload, "due_day": maximum})

    def test_invalid_payment_date_and_amount_are_rejected_before_connecting(self):
        path = "/bills/{bill_id}/pay"
        for value in ([], {}, 0, False, [2026, 11, 15], 20261115, True):
            with self.subTest(payment_date=value):
                self.assert_bad_input("post", path, "payment_date must be an ISO 8601 date string", json={"payment_date": value})
        for value in ("not a date", "2026-02-30", "2026-11-15T00:00:00"):
            with self.subTest(payment_date=value):
                self.assert_bad_input("post", path, "payment_date must be a valid ISO 8601 date", json={"payment_date": value})
        for value, message in (
            ([], "Amount must be numeric"), ({}, "Amount must be numeric"), (False, "Amount must be numeric"),
            ("bad", "Amount must be numeric"), (0, "Invalid amount"), ("NaN", "Amount must be finite"),
            (10**400, "Amount exceeds the supported range"), (1e16, "Amount exceeds the supported range"),
        ):
            with self.subTest(amount_type=type(value).__name__, message=message):
                self.assert_bad_input("post", path, message, json={"amount_paid": value})

    def test_payment_accepts_iso_variants_and_preserves_optional_defaults(self):
        for payload, expected_date, expected_amount in (
            ({}, date.today(), 45.0), ({"payment_date": None, "amount_paid": None}, date.today(), 45.0),
            ({"payment_date": "", "amount_paid": ""}, date.today(), 45.0),
            ({"payment_date": "20280229", "amount_paid": "11.50"}, date(2028, 2, 29), 11.5),
            ({"payment_date": "2028-W09-2", "amount_paid": 11.5}, date(2028, 2, 29), 11.5),
        ):
            with self.subTest(payload=payload):
                self.cursor.execute.reset_mock()
                self.cursor.fetchone.side_effect = [self.bill, {"id": 5, "due_date": self.bill["next_due_date"]}]
                self.assert_contract("post", "/bills/{bill_id}/pay", 200, json=payload)
                self.assertEqual(self.cursor.execute.call_args_list[2].args[1], (expected_date.isoformat(), expected_amount, 5))
