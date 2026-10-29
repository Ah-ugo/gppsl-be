import unittest
from datetime import date, datetime, timedelta

from app.logic import (attendance_flags, can_assign, certificate_status, face_match, geofence_check,
                       next_signer, nearest_site, payroll_days, project_colour, request_status,
                       signing_turn, timeline_pct, is_late)

TODAY = date(2026, 10, 24)
SITE = {"name": "PH Yard", "lat": 4.8156, "lng": 7.0498, "radius_m": 200}


class CertTests(unittest.TestCase):
    def test_status_thresholds(self):
        self.assertEqual(certificate_status(TODAY + timedelta(days=61), TODAY), "green")
        self.assertEqual(certificate_status(TODAY + timedelta(days=60), TODAY), "amber")
        self.assertEqual(certificate_status(TODAY, TODAY), "amber")
        self.assertEqual(certificate_status(TODAY - timedelta(days=1), TODAY), "red")
        self.assertEqual(certificate_status("2027-01-01", TODAY), "green")

    def test_assign_rejects_expired_h2s(self):
        staff = {"certifications": [{"type": "H2S", "expiry": "2026-09-01"}, {"type": "BOSIET", "expiry": "2027-05-01"}]}
        ok, reasons = can_assign(staff, ["H2S"], TODAY)
        self.assertFalse(ok)
        self.assertIn("H2S", reasons[0])
        self.assertIn("01/09/2026", reasons[0])

    def test_assign_ok_and_missing(self):
        staff = {"certifications": [{"type": "BOSIET", "expiry": "2027-05-01"}]}
        self.assertEqual(can_assign(staff, ["BOSIET"], TODAY), (True, []))
        ok, reasons = can_assign(staff, ["BOSIET", "HUET"], TODAY)
        self.assertFalse(ok)
        self.assertIn("Missing", reasons[0])
        self.assertEqual(can_assign({}, [], TODAY), (True, []))


class ProjectColourTests(unittest.TestCase):
    S, E = "2026-09-01", "2026-12-01"  # 91 days

    def test_red_over_budget(self):
        self.assertEqual(project_colour(100, 101, 10, self.S, self.E, TODAY), "RED")

    def test_exactly_budget_not_red_but_amber(self):
        self.assertEqual(project_colour(100, 100, 60, self.S, self.E, TODAY), "AMBER")

    def test_red_past_end_incomplete(self):
        self.assertEqual(project_colour(100, 10, 90, "2026-06-01", "2026-10-01", TODAY), "RED")

    def test_past_end_but_complete_is_not_red(self):
        self.assertEqual(project_colour(100, 10, 100, "2026-06-01", "2026-10-01", TODAY), "GREEN")

    def test_amber_cost_over_85(self):
        self.assertEqual(project_colour(100, 86, 60, self.S, self.E, TODAY), "AMBER")

    def test_amber_progress_lag(self):
        # timeline ~ 62.6%; progress 40 lags by > 10
        self.assertEqual(project_colour(100, 10, 40, self.S, self.E, TODAY), "AMBER")

    def test_green(self):
        self.assertEqual(project_colour(100, 50, 60, self.S, self.E, TODAY), "GREEN")

    def test_timeline_pct_edges(self):
        self.assertEqual(timeline_pct("2026-11-01", "2026-12-01", TODAY), 0.0)
        self.assertEqual(timeline_pct("2026-01-01", "2026-02-01", TODAY), 100.0)


class FaceAndGeoTests(unittest.TestCase):
    def test_face_match_below_threshold(self):
        tpl = [[0.0] * 128, [0.1] * 128]
        ok, score = face_match([0.01] * 128, tpl, 0.6)
        self.assertTrue(ok)
        self.assertLess(score, 0.6)

    def test_face_mismatch(self):
        ok, score = face_match([1.0] * 128, [[0.0] * 128], 0.6)
        self.assertFalse(ok)
        self.assertGreater(score, 0.6)

    def test_no_templates(self):
        self.assertEqual(face_match([0.0] * 128, []), (False, None))

    def test_inside_radius(self):
        r = geofence_check(4.8157, 7.0499, 10, SITE)
        self.assertTrue(r["inside"])
        self.assertEqual(r["flags"], [])

    def test_outside_radius(self):
        r = geofence_check(4.83, 7.07, 10, SITE)
        self.assertFalse(r["inside"])
        self.assertGreater(r["distance_m"], 200)

    def test_poor_accuracy_flag(self):
        self.assertIn("poor_gps_accuracy", geofence_check(4.8157, 7.0499, 500, SITE)["flags"])
        self.assertIn("poor_gps_accuracy", geofence_check(4.8157, 7.0499, None, SITE)["flags"])

    def test_impossible_jump(self):
        now = datetime(2026, 10, 24, 8, 0)
        prev = {"lat": 6.5244, "lng": 3.3792, "time": now - timedelta(minutes=10)}  # Lagos -> PH in 10 minutes
        self.assertIn("impossible_jump", geofence_check(4.8157, 7.0499, 10, SITE, prev, now)["flags"])

    def test_plausible_movement_not_flagged(self):
        now = datetime(2026, 10, 24, 8, 0)
        prev = {"lat": 4.8100, "lng": 7.0400, "time": now - timedelta(hours=1)}
        self.assertNotIn("impossible_jump", geofence_check(4.8157, 7.0499, 10, SITE, prev, now)["flags"])

    def test_nearest_site(self):
        sites = [SITE, {"name": "Warri", "lat": 5.55, "lng": 5.79, "radius_m": 300}]
        site, dist = nearest_site(4.8157, 7.0499, sites)
        self.assertEqual(site["name"], "PH Yard")
        self.assertLess(dist, 30)
        self.assertIsNone(nearest_site(1, 1, []))


class AttendanceFlagTests(unittest.TestCase):
    NOW = datetime(2026, 10, 24, 7, 30)

    def base(self, **kw):
        d = {"face_matched": True, "inside": True, "geo_flags": [], "phone_time": self.NOW}
        d.update(kw)
        return d

    def test_clean(self):
        self.assertEqual(attendance_flags(self.base(), self.NOW), [])

    def test_face_mismatch(self):
        self.assertEqual(attendance_flags(self.base(face_matched=False), self.NOW), ["face_mismatch"])

    def test_outside(self):
        self.assertIn("outside_site", attendance_flags(self.base(inside=False), self.NOW))

    def test_suspicious_gps(self):
        self.assertIn("suspicious_gps", attendance_flags(self.base(geo_flags=["poor_gps_accuracy"]), self.NOW))

    def test_time_drift_online_only(self):
        late = self.NOW + timedelta(minutes=30)
        self.assertIn("time_drift", attendance_flags(self.base(), late))
        self.assertNotIn("time_drift", attendance_flags(self.base(), late, offline=True))

    def test_duplicate(self):
        self.assertIn("duplicate", attendance_flags(self.base(), self.NOW, previous={"id": "x"}))

    def test_is_late(self):
        self.assertFalse(is_late(datetime(2026, 10, 24, 8, 15)))
        self.assertTrue(is_late(datetime(2026, 10, 24, 8, 16)))


class PayrollTests(unittest.TestCase):
    def test_counts_verified_only_in_month(self):
        ci = {"time": "x"}
        att = [
            {"staff_id": "a", "date": "2026-10-01", "status": "verified", "clock_in": ci},
            {"staff_id": "a", "date": "2026-10-02", "status": "flagged", "clock_in": ci},
            {"staff_id": "a", "date": "2026-10-03", "status": "rejected", "clock_in": ci},
            {"staff_id": "a", "date": "2026-09-30", "status": "verified", "clock_in": ci},
            {"staff_id": "b", "date": "2026-10-01", "status": "verified", "clock_in": ci},
            {"staff_id": "b", "date": "2026-10-01", "status": "verified", "clock_in": ci},  # same day twice
        ]
        self.assertEqual(payroll_days(att, "2026-10"), {"a": 1, "b": 1})


class SigningTests(unittest.TestCase):
    signers = [
        {"user_id": "u1", "order": 1, "status": "pending"},
        {"user_id": "u2", "order": 2, "status": "pending"},
    ]

    def test_only_first_can_sign_initially(self):
        self.assertTrue(signing_turn(self.signers, "u1"))
        self.assertFalse(signing_turn(self.signers, "u2"))
        self.assertFalse(signing_turn(self.signers, "stranger"))

    def test_second_after_first(self):
        s = [{"user_id": "u1", "order": 1, "status": "signed"}, {"user_id": "u2", "order": 2, "status": "pending"}]
        self.assertTrue(signing_turn(s, "u2"))
        self.assertFalse(signing_turn(s, "u1"))  # already signed
        self.assertEqual(next_signer(s)["user_id"], "u2")

    def test_status(self):
        self.assertEqual(request_status(self.signers), "Awaiting signature")
        done = [{"user_id": "u1", "order": 1, "status": "signed"}]
        self.assertEqual(request_status(done), "Signed")
        self.assertIsNone(next_signer(done))


if __name__ == "__main__":
    unittest.main()
