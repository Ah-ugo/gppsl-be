import unittest
from datetime import date, timedelta

from app.logic import ageing_buckets, cash_forecast, expense_flags, invoices_older_than, next_approver

TODAY = date(2026, 10, 24)


def inv(days_old, amount=100.0, status="sent", due_in=30, **kw):
    issue = TODAY - timedelta(days=days_old)
    d = {"issue_date": issue.isoformat(), "due_date": (issue + timedelta(days=due_in)).isoformat(),
         "amount": amount, "status": status}
    d.update(kw)
    return d


class ApproverTests(unittest.TestCase):
    def test_at_limit_goes_to_finance(self):
        self.assertEqual(next_approver(500_000, {"finance_max": 500_000}), "finance")

    def test_above_limit_goes_to_md(self):
        self.assertEqual(next_approver(500_000.01, {"finance_max": 500_000}), "md")

    def test_uses_default_when_no_limits(self):
        self.assertEqual(next_approver(10), "finance")
        self.assertEqual(next_approver(10_000_000), "md")


class ExpenseFlagTests(unittest.TestCase):
    hist = [
        {"id": 1, "vendor": "Shell Depot", "amount": 20000, "date": "2026-10-01", "category": "fuel"},
        {"id": 2, "vendor": "Other", "amount": 30000, "date": "2026-10-02", "category": "fuel"},
    ]

    def test_duplicate(self):
        e = {"vendor": "shell depot", "amount": 20000, "date": "2026-10-01", "category": "fuel"}
        self.assertIn("possible duplicate", expense_flags(e, self.hist))

    def test_not_duplicate_if_date_differs(self):
        e = {"vendor": "Shell Depot", "amount": 20000, "date": "2026-10-03", "category": "fuel"}
        self.assertNotIn("possible duplicate", expense_flags(e, self.hist))

    def test_unusually_high(self):
        e = {"vendor": "X", "amount": 80000, "date": "2026-10-05", "category": "fuel"}  # avg 25000, 3x=75000
        self.assertIn("unusually high", expense_flags(e, self.hist))

    def test_exactly_three_times_not_flagged(self):
        e = {"vendor": "X", "amount": 75000, "date": "2026-10-05", "category": "fuel"}
        self.assertNotIn("unusually high", expense_flags(e, self.hist))

    def test_no_history_no_flags(self):
        e = {"vendor": "X", "amount": 1, "date": "2026-10-05", "category": "fuel"}
        self.assertEqual(expense_flags(e, []), [])

    def test_other_category_ignored_for_average(self):
        e = {"vendor": "X", "amount": 999999, "date": "2026-10-05", "category": "travel"}
        self.assertNotIn("unusually high", expense_flags(e, self.hist))


class AgeingTests(unittest.TestCase):
    def test_bucket_boundaries(self):
        invoices = [inv(0, 1), inv(30, 2), inv(31, 4), inv(60, 8), inv(61, 16), inv(90, 32), inv(91, 64)]
        b = ageing_buckets(invoices, TODAY)
        self.assertEqual(b, {"0-30": 3.0, "31-60": 12.0, "61-90": 48.0, "90+": 64.0})

    def test_paid_ignored_and_part_payment_reduces(self):
        invoices = [inv(10, 100, status="paid"), inv(10, 100, paid_amount=40)]
        self.assertEqual(ageing_buckets(invoices, TODAY)["0-30"], 60.0)

    def test_older_than(self):
        invoices = [inv(61, client_id="a"), inv(60, client_id="b"), inv(120, client_id="c"), inv(200, status="paid")]
        out = invoices_older_than(invoices, TODAY, 60)
        self.assertEqual([i["client_id"] for i in out], ["c", "a"])


class ForecastTests(unittest.TestCase):
    def test_returns_requested_weeks(self):
        self.assertEqual(len(cash_forecast([], [], 0, 8, TODAY)), 8)

    def test_receipt_uses_long_cycle_not_due_date(self):
        # issued 10 days ago, due in 30 days, but clients pay ~90 days after issue -> lands ~week 11, not in 8 weeks
        rows = cash_forecast([inv(10, 1000)], [], 0, 8, TODAY)
        self.assertEqual(sum(r["receipts"] for r in rows), 0)
        # issued 50 days ago -> expected at day 90 => 40 days from now => week 5
        rows = cash_forecast([inv(50, 1000)], [], 0, 8, TODAY)
        self.assertEqual(rows[5]["receipts"], 1000)

    def test_very_old_invoice_assumed_in_two_weeks(self):
        rows = cash_forecast([inv(300, 500)], [], 0, 8, TODAY)
        self.assertEqual(rows[2]["receipts"], 500)

    def test_payables_and_overdue_payables_week_zero(self):
        pays = [{"amount": 200, "due_date": "2026-10-01"}, {"amount": 300, "due_date": "2026-11-05"}]
        rows = cash_forecast([], pays, 0, 8, TODAY)
        self.assertEqual(rows[0]["payables"], 200)
        self.assertEqual(sum(r["payables"] for r in rows), 500)

    def test_payroll_hits_on_25th(self):
        rows = cash_forecast([], [], 1000, 8, TODAY)
        self.assertEqual(sum(r["payroll"] for r in rows), 2000)  # 25 Oct and 25 Nov inside 56 days

    def test_cumulative_includes_opening_cash(self):
        rows = cash_forecast([], [{"amount": 100, "due_date": "2026-10-24"}], 0, 2, TODAY, opening_cash=1000)
        self.assertEqual(rows[0]["cumulative"], 900)

    def test_paid_invoices_excluded(self):
        rows = cash_forecast([inv(50, 1000, status="paid")], [], 0, 8, TODAY)
        self.assertEqual(sum(r["receipts"] for r in rows), 0)


if __name__ == "__main__":
    unittest.main()
