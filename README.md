# Parcel Ops Analytics

An event pipeline for answering two questions a parcel operations team might ask. Which origin hubs have overdue parcels, and where are exception scans concentrated this week?

The demo generates synthetic parcel scans, validates and deduplicates them into SQLite, then runs two SQL queries against a shared UTC cutoff. It uses only Python and SQLite. This is an AI-assisted portfolio starter for Danish Irfan to review, explain and extend. The feed and results describe fictional parcel movements.

## Run the demo

Use Python 3.10 or later with its standard SQLite support. Run from this repository folder. Use `py` in place of `python` on Windows if your installation uses the Python launcher.

```sh
python parcel_ops.py generate scans.csv
python parcel_ops.py load scans.csv ops.sqlite
python parcel_ops.py load scans.csv ops.sqlite
python parcel_ops.py report ops.sqlite --as-of 2025-03-13T00:00:00Z --sla-hours 48
python -m unittest -v
```

Starting with a fresh database, the first load inserts **376** events and skips **1** repeated row. Replaying the same feed inserts **0** events and skips **377** rows. The generator covers 120 parcels and deliberately shuffles the scans. The report cutoff includes 100 accepted parcels.

## Example results

The 48-hour SLA snapshot at `2025-03-13T00:00:00Z` looks like this.

| Origin hub | Accepted | Delivered | Open overdue | On time / eligible | Mean transit |
| --- | ---: | ---: | ---: | ---: | ---: |
| Bangi | 39 | 23 | 9 | 11 / 32 (34.38%) | 50.09 h |
| Johor Bahru | 24 | 11 | 6 | 6 / 17 (35.29%) | 47.00 h |
| Shah Alam | 37 | 29 | 4 | 16 / 33 (48.48%) | 48.28 h |

For the UTC week beginning 3 March, Bangi recorded eight exception scans across six distinct parcels. The week beginning 10 March is partial at this cutoff. Compare equivalent date ranges before interpreting week-to-week changes.

## Data and metric definitions

- A feed has five fields `event_id`, `parcel_id`, `event_type`, `occurred_at` and `hub`. `occurred_at` is a UTC timestamp such as `2025-03-03T08:00:00Z`. Supported event types are `ACCEPTED`, `IN_TRANSIT`, `EXCEPTION` and `DELIVERED`.
- The loader treats `event_id` as the identity of a scan. An identical replay is skipped. A changed payload under the same ID or an invalid row rolls back the entire file. An event with a distinct ID remains a separate scan.
- [Origin performance](sql/origin_performance.sql) uses the first acceptance at or before the cutoff and the earliest delivery at or after that acceptance. A delivery without a qualifying acceptance contributes no transit time. Tied acceptance times use the lower event ID.
- A delivery at the deadline counts as on time. An open parcel is overdue once the deadline is reached. The on-time rate divides on-time deliveries by delivered parcels plus overdue open parcels. Open parcels still within the SLA are excluded from the denominator. The rate is `null` when that denominator is zero, and mean transit uses delivered parcels only.
- [Weekly exceptions](sql/weekly_exceptions.sql) groups by scan hub and Monday-start UTC week. It reports both scan count and distinct affected parcels per group. A parcel may appear in more than one group. The report uses scan time, so a late-arriving scan can change a rerun for a historical cutoff.

## Extend the project

Add an `ingested_at` field and compare two reports for the same scan-time cutoff with different ingestion cutoffs. Show how a delivery that arrived late changes the reported overdue count. Add a test for the change and explain the two clocks in your own words.
