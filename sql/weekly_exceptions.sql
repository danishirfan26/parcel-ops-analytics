SELECT date(occurred_at, '-6 days', 'weekday 1') AS week_start_utc,
       hub AS scan_hub,
       COUNT(*) AS exception_scans,
       COUNT(DISTINCT parcel_id) AS affected_parcels
FROM events
WHERE event_type = 'EXCEPTION' AND occurred_at <= :as_of
GROUP BY week_start_utc, scan_hub
ORDER BY week_start_utc, scan_hub;
