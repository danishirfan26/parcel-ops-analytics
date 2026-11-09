WITH snapshot AS (
    SELECT event_id, parcel_id, event_type, hub,
           CAST(strftime('%s', occurred_at) AS INTEGER) AS event_second
    FROM events
    WHERE occurred_at <= :as_of
), accepted_scans AS (
    SELECT parcel_id, hub AS origin_hub, event_second AS accepted_second,
           ROW_NUMBER() OVER (PARTITION BY parcel_id ORDER BY event_second, event_id) AS rank
    FROM snapshot
    WHERE event_type = 'ACCEPTED'
), journeys AS (
    SELECT a.parcel_id, a.origin_hub, a.accepted_second,
           a.accepted_second + 3600 * :sla_hours AS deadline_second,
           MIN(d.event_second) AS delivered_second
    FROM accepted_scans AS a
    LEFT JOIN snapshot AS d ON d.parcel_id = a.parcel_id
        AND d.event_type = 'DELIVERED' AND d.event_second >= a.accepted_second
    WHERE a.rank = 1
    GROUP BY a.parcel_id, a.origin_hub, a.accepted_second
), hub_totals AS (
    SELECT origin_hub,
           COUNT(*) AS accepted,
           COUNT(delivered_second) AS delivered,
           SUM(CASE WHEN delivered_second <= deadline_second THEN 1 ELSE 0 END) AS on_time,
           SUM(CASE WHEN delivered_second > deadline_second THEN 1 ELSE 0 END) AS delivered_late,
           SUM(CASE WHEN delivered_second IS NULL
                AND deadline_second <= CAST(strftime('%s', :as_of) AS INTEGER) THEN 1 ELSE 0 END)
               AS open_overdue,
           ROUND(AVG((delivered_second - accepted_second) / 3600.0), 2) AS mean_transit_hours
    FROM journeys
    GROUP BY origin_hub
)
SELECT origin_hub, accepted, delivered, on_time, delivered_late, open_overdue,
       accepted - delivered - open_overdue AS open_within_sla,
       delivered + open_overdue AS sla_eligible,
       ROUND(100.0 * on_time / NULLIF(delivered + open_overdue, 0), 2) AS on_time_pct,
       mean_transit_hours
FROM hub_totals
ORDER BY origin_hub;
