import csv
import sqlite3
import unittest
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory

from parcel_ops import FIELDS, build_report, generate_demo, load_events


class ParcelOpsTests(unittest.TestCase):
    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.feed = Path(directory.name) / "scans.csv"
        self.database = Path(directory.name) / "ops.sqlite"

    def write_feed(self, rows):
        with self.feed.open("w", encoding="utf-8", newline="") as file:
            writer = csv.writer(file)
            writer.writerow(FIELDS)
            writer.writerows(rows)

    def test_demo_is_deterministic_and_reloading_is_idempotent(self):
        count = generate_demo(self.feed)
        first = self.feed.read_bytes()
        self.assertEqual(generate_demo(self.feed), count)
        self.assertEqual(self.feed.read_bytes(), first)
        self.assertEqual(load_events(self.feed, self.database), {"inserted": count - 1, "duplicates": 1})
        self.assertEqual(load_events(self.feed, self.database), {"inserted": 0, "duplicates": count})

    def test_changed_payload_and_bad_timestamp_rollback_prior_inserts(self):
        first = ("E1", "P1", "ACCEPTED", "2025-03-03T08:00:00Z", "BANGI")
        next_event = ("E2", "P2", "ACCEPTED", "2025-03-03T08:00:00Z", "BANGI")
        self.write_feed([first])
        load_events(self.feed, self.database)
        for invalid, message in (
            (first[:-1] + ("SHAH_ALAM",), "Conflicting payload"),
            (("E3", "P3", "DELIVERED", "2025-02-29T08:00:00Z", "BANGI"), "Expected UTC timestamp"),
        ):
            with self.subTest(invalid=invalid):
                self.write_feed([next_event, invalid])
                with self.assertRaisesRegex(ValueError, f"CSV line 3: {message}"):
                    load_events(self.feed, self.database)
                with closing(sqlite3.connect(self.database)) as db:
                    self.assertEqual(db.execute("SELECT event_id FROM events").fetchall(), [("E1",)])

    def test_report_handles_cutoff_sla_boundary_and_repeated_scans(self):
        self.write_feed([
            ("E01", "P1", "DELIVERED", "2025-03-05T08:00:00Z", "JOHOR_BAHRU"),
            ("E02", "P1", "ACCEPTED", "2025-03-03T08:00:00Z", "BANGI"),
            ("E03", "P1", "ACCEPTED", "2025-03-03T09:00:00Z", "SHAH_ALAM"),
            ("E04", "P1", "DELIVERED", "2025-03-02T08:00:00Z", "BANGI"),
            ("E05", "P2", "ACCEPTED", "2025-03-03T08:00:00Z", "BANGI"),
            ("E06", "P2", "DELIVERED", "2025-03-05T09:00:00Z", "SHAH_ALAM"),
            ("E07", "P3", "ACCEPTED", "2025-03-03T08:00:00Z", "BANGI"),
            ("E08", "P3", "DELIVERED", "2025-03-06T08:00:00Z", "SHAH_ALAM"),
            ("E09", "P4", "ACCEPTED", "2025-03-04T08:00:00Z", "BANGI"),
            ("E10", "P5", "ACCEPTED", "2025-03-05T08:00:00Z", "SHAH_ALAM"),
            ("E11", "P6", "DELIVERED", "2025-03-05T08:00:00Z", "BANGI"),
            ("E12", "P2", "EXCEPTION", "2025-03-03T12:00:00Z", "BANGI"),
            ("E13", "P2", "EXCEPTION", "2025-03-03T13:00:00Z", "BANGI"),
            ("E14", "P3", "EXCEPTION", "2025-03-04T13:00:00Z", "BANGI"),
            ("E15", "P4", "EXCEPTION", "2025-03-06T13:00:00Z", "BANGI"),
        ])
        load_events(self.feed, self.database)
        result = build_report(self.database, "2025-03-05T09:00:00Z")
        bangi, shah_alam = result["origin_performance"]
        self.assertEqual(bangi, {
            "origin_hub": "BANGI", "accepted": 4, "delivered": 2, "on_time": 1,
            "delivered_late": 1, "open_overdue": 1, "open_within_sla": 1,
            "sla_eligible": 3, "on_time_pct": 33.33, "mean_transit_hours": 48.5,
        })
        self.assertIsNone(shah_alam["on_time_pct"])
        self.assertIsNone(shah_alam["mean_transit_hours"])
        self.assertEqual(result["weekly_exceptions"], [{
            "week_start_utc": "2025-03-03", "scan_hub": "BANGI",
            "exception_scans": 3, "affected_parcels": 2,
        }])


if __name__ == "__main__":
    unittest.main()
