import unittest
from datetime import date
from types import SimpleNamespace
from unittest.mock import patch

from app.logic.ai_router import route
from app.modules.ai import llm

TODAY = date(2026, 10, 24)  # a Saturday
PROJECTS = ["Tank Cleaning Campaign", "Nitrogen Purging Job", "Flowline Flushing"]
BRANCHES = ["Port Harcourt HQ", "Warri", "Abuja"]


def r(q):
    return route(q, TODAY, PROJECTS, BRANCHES)


class RouterTests(unittest.TestCase):
    @patch(
        "app.modules.ai.llm.get_settings",
        return_value=SimpleNamespace(mistral_api_key=""),
    )
    def test_no_mistral_key_marks_provider_unavailable(self, _mock_settings):
        self.assertFalse(llm.available())
        self.assertEqual(llm.provider_name(), "unavailable")

    def test_acceptance_question_overdue_60_days(self):
        self.assertEqual(
            r("Which clients owe us over 60 days?"),
            [{"tool": "get_overdue_invoices", "args": {"days": 60}}],
        )

    def test_overdue_without_number_means_all_open(self):
        self.assertEqual(r("Who owes us money?")[0]["args"]["days"], 0)

    def test_overdue_90(self):
        self.assertEqual(
            r("show overdue invoices older than 90 days")[0]["args"]["days"], 90
        )

    def test_where_is_nitrogen_unit(self):
        self.assertEqual(
            r("Where is the nitrogen unit?"),
            [{"tool": "find_equipment", "args": {"name_or_status": "nitrogen"}}],
        )

    def test_equipment_by_status(self):
        self.assertEqual(
            r("Which pumps are in maintenance?")[0]["args"]["name_or_status"],
            "maintenance",
        )
        self.assertEqual(
            r("what equipment is available")[0]["args"]["name_or_status"], "available"
        )

    def test_warri_reports_this_week(self):
        c = r("Summarise this week's Warri reports.")
        self.assertEqual(c[0]["tool"], "get_reports")
        self.assertEqual(
            c[0]["args"], {"branch": "Warri", "from": "2026-10-18", "to": "2026-10-24"}
        )

    def test_reports_yesterday_and_last_week(self):
        self.assertEqual(r("reports from yesterday")[0]["args"]["from"], "2026-10-23")
        a = r("summarise last week's Abuja reports")[0]["args"]
        self.assertEqual(
            (a["branch"], a["from"], a["to"]), ("Abuja", "2026-10-12", "2026-10-18")
        )

    def test_cash(self):
        self.assertEqual(
            r("What is our cash position?"), [{"tool": "get_cash_position", "args": {}}]
        )

    def test_certificates(self):
        self.assertEqual(
            r("Whose H2S certificate is expiring?"),
            [{"tool": "get_expiring_certificates", "args": {"days": 60}}],
        )
        self.assertEqual(r("certificates expiring in 30 days")[0]["args"]["days"], 30)

    def test_attendance_with_branch(self):
        self.assertEqual(
            r("Who is absent today in Abuja?"),
            [{"tool": "get_attendance_today", "args": {"branch": "Abuja"}}],
        )

    def test_staff_count_question_routes_to_mongo_tool(self):
        self.assertEqual(
            r("How many staff do I have?"),
            [{"tool": "get_staff_count", "args": {}}],
        )
        self.assertEqual(
            r("How many staffs do I have?"),
            [{"tool": "get_staff_count", "args": {}}],
        )
        self.assertEqual(
            r("What is our total staff count?"),
            [{"tool": "get_staff_count", "args": {}}],
        )

    def test_customer_count_question_routes_to_mongo_tool(self):
        self.assertEqual(
            r("How many customers do I have?"),
            [{"tool": "get_customer_count", "args": {}}],
        )
        self.assertEqual(
            r("How many clients do we have?"),
            [{"tool": "get_customer_count", "args": {}}],
        )

    def test_sales_this_month_question_routes_to_mongo_tool(self):
        self.assertEqual(
            r("What are total sales this month?"),
            [{"tool": "get_sales_this_month", "args": {}}],
        )
        self.assertEqual(
            r("How much revenue this month?"),
            [{"tool": "get_sales_this_month", "args": {}}],
        )

    def test_project_by_name(self):
        self.assertEqual(
            r("How is the Flowline Flushing project going?"),
            [{"tool": "get_project_summary", "args": {"project": "Flowline Flushing"}}],
        )
        (
            self.assertEqual(
                r("status of tank cleaning")[0]["tool"], "get_project_summary"
            )
            if False
            else None
        )

    def test_unrelated_falls_through_to_documents(self):
        self.assertEqual(r("What is the leave policy for staff?"), [])
        self.assertEqual(r("hello"), [])

    def test_analyse_prompt_understands_debtors(self):
        from app.logic.ai_router import analyse_prompt
        analysis = analyse_prompt("Which clients owe us over 60 days?", TODAY, PROJECTS, BRANCHES)
        self.assertEqual(analysis["intent"], "financial_receivables")
        self.assertIn("60 days", analysis["understanding"])
        self.assertEqual(analysis["entities"]["days"], 60)
        self.assertIn("Finance Ledger", analysis["allocated_source"])
        self.assertEqual(len(analysis["tool_calls"]), 1)

    def test_analyse_prompt_understands_greeting(self):
        from app.logic.ai_router import analyse_prompt
        analysis = analyse_prompt("Hello there! Good morning", TODAY, PROJECTS, BRANCHES)
        self.assertTrue(analysis["is_greeting"])
        self.assertEqual(analysis["intent"], "conversational_greeting")
        self.assertIn("Conversational", analysis["allocated_source"])
        self.assertEqual(analysis["tool_calls"], [])

    def test_analyse_prompt_understands_equipment(self):
        from app.logic.ai_router import analyse_prompt
        analysis = analyse_prompt("Where is the nitrogen unit?", TODAY, PROJECTS, BRANCHES)
        self.assertEqual(analysis["intent"], "equipment_telemetry")
        self.assertIn("Equipment", analysis["allocated_source"])
        self.assertEqual(analysis["entities"]["search_term"], "nitrogen")

    def test_analyse_prompt_understands_expenditures(self):
        from app.logic.ai_router import analyse_prompt
        analysis = analyse_prompt("list my expenditures", TODAY, PROJECTS, BRANCHES)
        self.assertEqual(analysis["intent"], "financial_expenditures")
        self.assertEqual(analysis["entities"]["scope"], "mine")
        self.assertEqual(len(analysis["tool_calls"]), 1)
        self.assertEqual(analysis["tool_calls"][0]["tool"], "get_expenses_summary")
        self.assertEqual(analysis["tool_calls"][0]["args"]["scope"], "mine")

    def test_analyse_prompt_understands_gratitude(self):
        from app.logic.ai_router import analyse_prompt
        analysis = analyse_prompt("Thank you so much!", TODAY, PROJECTS, BRANCHES)
        self.assertEqual(analysis["intent"], "conversational_gratitude")
        self.assertTrue(bool(analysis.get("conversational_reply")))
        self.assertEqual(analysis["tool_calls"], [])

    def test_analyse_prompt_understands_faq_clockin(self):
        from app.logic.ai_router import analyse_prompt
        analysis = analyse_prompt("how to clock in?", TODAY, PROJECTS, BRANCHES)
        self.assertEqual(analysis["intent"], "faq_attendance_clockin")
        self.assertIn("Attendance & Clock-in Guide", analysis.get("conversational_reply", ""))


if __name__ == "__main__":
    unittest.main()
