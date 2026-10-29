import unittest
from datetime import date

from app.logic import can_deploy, overdue_rentals, rental_income, utilisation_pct

TODAY = date(2026, 10, 24)


def pump(**kw):
    base = {"status": "available", "run_hours": 100, "last_service_hours": 0,
            "service_interval_hours": 500, "certificates": []}
    base.update(kw)
    return base


class CanDeployTests(unittest.TestCase):
    def test_ok_when_all_clear(self):
        self.assertEqual(can_deploy(pump(), TODAY, []), [])

    def test_blocks_when_not_available(self):
        r = can_deploy(pump(status="deployed"), TODAY, [])
        self.assertEqual(len(r), 1)
        self.assertIn("already deployed", r[0])

    def test_blocks_service_overdue_at_boundary(self):
        r = can_deploy(pump(run_hours=500), TODAY, [])
        self.assertTrue(any("Service overdue" in x for x in r))

    def test_service_not_overdue_just_below_interval(self):
        self.assertEqual(can_deploy(pump(run_hours=499), TODAY, []), [])

    def test_last_service_hours_resets_counter(self):
        self.assertEqual(can_deploy(pump(run_hours=900, last_service_hours=600), TODAY, []), [])

    def test_blocks_expired_certificate(self):
        eq = pump(certificates=[{"name": "Pressure inspection", "expiry_date": "2026-09-01"}])
        r = can_deploy(eq, TODAY, [])
        self.assertEqual(len(r), 1)
        self.assertIn("Pressure inspection", r[0])
        self.assertIn("01/09/2026", r[0])

    def test_certificate_expiring_today_is_still_valid(self):
        eq = pump(certificates=[{"name": "X", "expiry_date": "2026-10-24"}])
        self.assertEqual(can_deploy(eq, TODAY, []), [])

    def test_blocks_overlapping_booking(self):
        b = [{"start_date": "2026-10-20", "expected_return": "2026-10-30"}]
        r = can_deploy(pump(), TODAY, b)
        self.assertTrue(any("Overlapping" in x for x in r))

    def test_non_overlapping_booking_ok(self):
        b = [{"start_date": "2026-11-05", "expected_return": "2026-11-10"}]
        self.assertEqual(can_deploy(pump(), TODAY, b, start="2026-10-24", end="2026-10-30"), [])

    def test_returned_booking_ignored(self):
        b = [{"start_date": "2026-10-20", "expected_return": "2026-10-30", "actual_return": "2026-10-22"}]
        self.assertEqual(can_deploy(pump(), TODAY, b), [])

    def test_collects_multiple_reasons(self):
        eq = pump(status="maintenance", run_hours=700,
                  certificates=[{"name": "C", "expiry_date": "2026-01-01"}])
        self.assertEqual(len(can_deploy(eq, TODAY, [])), 3)


class OtherEquipmentTests(unittest.TestCase):
    def test_utilisation(self):
        items = [{"status": "deployed"}, {"status": "available"}, {"status": "deployed"}, {"status": "maintenance"}]
        self.assertEqual(utilisation_pct(items), 50.0)
        self.assertEqual(utilisation_pct([]), 0.0)

    def test_overdue_rentals(self):
        rentals = [
            {"id": 1, "expected_return": "2026-10-01"},
            {"id": 2, "expected_return": "2026-10-01", "actual_return": "2026-10-02"},
            {"id": 3, "expected_return": "2026-11-01"},
        ]
        self.assertEqual([r["id"] for r in overdue_rentals(rentals, TODAY)], [1])

    def test_rental_income(self):
        self.assertEqual(rental_income("daily", 50_000, "2026-10-01", "2026-10-10"), 500_000)
        self.assertEqual(rental_income("weekly", 300_000, "2026-10-01", "2026-10-10"), 600_000)
        self.assertEqual(rental_income("daily", 10, "2026-10-01", "2026-10-01"), 10)


if __name__ == "__main__":
    unittest.main()
