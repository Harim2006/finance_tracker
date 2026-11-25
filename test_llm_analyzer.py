
import unittest
from datetime import date, datetime, timedelta

from llm_analyzer import FinanceLLMAnalyzer


class TestFinanceLLMAnalyzer(unittest.TestCase):

    def setUp(self):
        self.analyzer = FinanceLLMAnalyzer()

        self.context = {
            "envelopes": [
                {
                    "name": "Groceries",
                    "monthly_allocation": 500,
                    "current_balance": 350
                },
                {
                    "name": "Entertainment",
                    "monthly_allocation": 100,
                    "current_balance": -30
                },
                {
                    "name": "Transportation",
                    "monthly_allocation": 100,
                    "current_balance": 200
                }
            ],
            "bills": [
                {
                    "name": "Internet",
                    "amount": 50,
                    "next_due_date": (
                        date.today() + timedelta(days=3)
                    )
                },
                {
                    "name": "Insurance",
                    "amount": 100,
                    "next_due_date": (
                        date.today() + timedelta(days=20)
                    ).isoformat()
                }
            ],
            "recent_transactions": [
                {
                    "merchant": "Walmart",
                    "envelope_name": "Groceries",
                    "amount": 100
                },
                {
                    "merchant": "Walmart",
                    "envelope_name": "Groceries",
                    "amount": 50
                },
                {
                    "merchant": "Cinema",
                    "envelope_name": "Entertainment",
                    "amount": 30
                }
            ]
        }

    # Date conversion regression tests

    def test_convert_date_object(self):
        value = date(2026, 1, 15)
        self.assertEqual(
            self.analyzer._as_date(value), value
        )

    def test_convert_datetime_object(self):
        value = datetime(2026, 1, 15, 12, 30)
        self.assertEqual(
            self.analyzer._as_date(value),
            date(2026, 1, 15)
        )

    def test_convert_iso_date_string(self):
        self.assertEqual(
            self.analyzer._as_date("2026-01-15"),
            date(2026, 1, 15)
        )

    def test_convert_iso_datetime_string(self):
        self.assertEqual(
            self.analyzer._as_date(
                "2026-01-15T12:30:00"
            ),
            date(2026, 1, 15)
        )

    def test_invalid_date_string(self):
        with self.assertRaises(ValueError):
            self.analyzer._as_date("invalid-date")

    # Overspending analysis

    def test_overspending_detected(self):
        answer = self.analyzer.analyze_and_answer(
            "Am I overspending?", self.context
        )

        self.assertIn("Entertainment", answer)
        self.assertIn("$30.00", answer)

    def test_no_overspending(self):
        answer = self.analyzer.analyze_and_answer(
            "Am I overspending?", {}
        )

        self.assertIn("not overspending", answer)

    # Savings analysis

    def test_savings_suggestions(self):
        answer = self.analyzer.analyze_and_answer(
            "How can I save money?", self.context
        )

        self.assertIn("Transportation", answer)
        self.assertIn("$100.00", answer)
        self.assertIn("Walmart", answer)
        self.assertIn("$150.00", answer)

    def test_savings_without_transactions(self):
        answer = self.analyzer.analyze_and_answer(
            "How can I save money?", {}
        )

        self.assertIn("General Tips", answer)

    # Upcoming bill analysis

    def test_upcoming_bills_summary(self):
        answer = self.analyzer.analyze_and_answer(
            "When are my bills due?", self.context
        )

        self.assertIn("Internet", answer)
        self.assertIn("Insurance", answer)
        self.assertIn("$150.00", answer)

    def test_no_tracked_bills(self):
        answer = self.analyzer.analyze_and_answer(
            "When are my bills due?", {}
        )

        self.assertIn("don't have any bills", answer)

    def test_no_bills_due_within_thirty_days(self):
        context = {
            "bills": [
                {
                    "name": "Future Bill",
                    "amount": 100,
                    "next_due_date": (
                        date.today() + timedelta(days=60)
                    )
                }
            ]
        }

        answer = self.analyzer.analyze_and_answer(
            "When are my bills due?", context
        )

        self.assertIn(
            "No bills are due in the next 30 days",
            answer
        )

    def test_bill_summary_excludes_overdue_bills(self):
        context = {
            "bills": [
                {
                    "name": "Overdue Bill",
                    "amount": 100,
                    "next_due_date": (
                        date.today() - timedelta(days=5)
                    )
                }
            ]
        }

        answer = self.analyzer.analyze_and_answer(
            "When are my bills due?", context
        )

        self.assertNotIn("Overdue Bill", answer)

    # Spending analysis

    def test_top_spending_categories(self):
        answer = self.analyzer.analyze_and_answer(
            "Where do I spend the most?",
            self.context
        )

        self.assertIn("Groceries", answer)
        self.assertIn("$150.00", answer)
        self.assertIn("$180.00", answer)
        self.assertLess(
            answer.index("Groceries"),
            answer.index("Entertainment")
        )

    def test_no_recent_transactions(self):
        answer = self.analyzer.analyze_and_answer(
            "Where do I spend the most?", {}
        )

        self.assertIn(
            "No recent transactions", answer
        )

    # Affordability analysis

    def test_affordable_purchase(self):
        answer = self.analyzer.analyze_and_answer(
            "Can I afford a $50 purchase?",
            self.context
        )

        self.assertIn("Yes, you can afford it", answer)

    def test_unaffordable_purchase(self):
        answer = self.analyzer.analyze_and_answer(
            "Can I afford a $1000 purchase?",
            self.context
        )

        self.assertIn("Caution", answer)

    def test_affordability_missing_amount(self):
        answer = self.analyzer.analyze_and_answer(
            "Can I afford this?", self.context
        )

        self.assertIn("Please specify an amount", answer)

    # Budget recommendations

    def test_budget_recommendations(self):
        answer = self.analyzer.analyze_and_answer(
            "Recommend budget changes", self.context
        )

        self.assertIn("Increase allocations", answer)
        self.assertIn("Entertainment", answer)
        self.assertIn("$130.00", answer)
        self.assertIn("reducing allocations", answer)
        self.assertIn("Transportation", answer)
        self.assertIn("$80.00", answer)

    def test_balanced_budget_recommendations(self):
        answer = self.analyzer.analyze_and_answer(
            "Recommend budget changes", {}
        )

        self.assertIn("well-balanced", answer)

    # General financial summary

    def test_general_financial_summary(self):
        answer = self.analyzer.analyze_and_answer(
            "Give me a financial overview", self.context
        )

        self.assertIn("Financial Overview", answer)
        self.assertIn("$700.00", answer)
        self.assertIn("$520.00", answer)
        self.assertIn("$180.00", answer)
        self.assertIn("$150.00", answer)

    def test_low_balance_summary(self):
        context = {
            "envelopes": [
                {
                    "name": "Groceries",
                    "monthly_allocation": 100,
                    "current_balance": 10
                }
            ]
        }

        answer = self.analyzer.analyze_and_answer(
            "Financial overview", context
        )

        self.assertIn("Alert", answer)

    def test_surplus_balance_summary(self):
        context = {
            "envelopes": [
                {
                    "name": "Groceries",
                    "monthly_allocation": 100,
                    "current_balance": 200
                }
            ]
        }

        answer = self.analyzer.analyze_and_answer(
            "Financial overview", context
        )

        self.assertIn("healthy surplus", answer)

    # Automated insights

    def test_overspending_insight(self):
        insights = self.analyzer.generate_insights(
            self.context
        )

        warnings = [
            item for item in insights
            if item["type"] == "warning"
        ]

        self.assertEqual(len(warnings), 1)
        self.assertIn(
            "Entertainment", warnings[0]["message"]
        )

    def test_upcoming_bill_insight(self):
        insights = self.analyzer.generate_insights(
            self.context
        )

        bills = [
            item for item in insights
            if item["title"] == "Bills Due Soon"
        ]

        self.assertEqual(len(bills), 1)
        self.assertIn("$50.00", bills[0]["message"])

    def test_healthy_envelope_insight(self):
        context = {
            "envelopes": [
                {
                    "name": "Groceries",
                    "monthly_allocation": 100,
                    "current_balance": 90
                }
            ]
        }

        insights = self.analyzer.generate_insights(
            context
        )

        self.assertTrue(
            any(
                item["type"] == "success"
                for item in insights
            )
        )

    def test_empty_financial_context(self):
        insights = self.analyzer.generate_insights({})
        self.assertEqual(insights, [])


if __name__ == "__main__":
    unittest.main()
