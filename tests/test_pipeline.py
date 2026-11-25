"""FAKE request rows only, plus checks of the generated aggregate-only public JSON."""
from datetime import date
import json
from pathlib import Path

import pandas as pd
import pytest

from pipeline import (
    _json_safe_payload,
    _reported_metric,
    build_public_payloads,
    clean_custom_fields,
    deduplicate_requests,
    kaplan_meier_quantile,
    pivot_custom_fields,
    process_requests,
    season_for,
    survival_observations,
)

ROOT = Path(__file__).resolve().parent.parent
PUBLIC_DATA = ROOT / "docs" / "data"


def _ms(value):
    return int(pd.Timestamp(value, tz="UTC").timestamp() * 1000)


def _fake_request(
    request_id="FAKE-REQUEST-1",
    initiated="2024-06-01 12:00",
    closed="2024-06-03 12:00",
    district=1,
    object_id=1,
    description="Street Surface Maintenance",
):
    return {
        "REQUEST_ID": request_id,
        "DESCRIPTION": description,
        "DATE_INITIATED": _ms(initiated) if initiated is not None else None,
        "DATE_CLOSED": _ms(closed) if closed is not None else None,
        "DISTRICT": district,
        "ObjectId": object_id,
    }


def test_pipeline_uses_halifax_calendar_dates_before_calculating_wait():
    fake_requests = pd.DataFrame(
        [
            _fake_request(
                initiated="2024-06-02 02:30",
                closed="2024-06-02 03:30",
            )
        ]
    )

    metrics, _, _ = process_requests(fake_requests, date(2024, 6, 3))

    assert metrics[0]["initiated_date"] == "2024-06-01"
    assert metrics[0]["closed_date"] == "2024-06-02"
    assert metrics[0]["wait_days"] == 1


def test_scope_rule_trims_source_padding_but_keeps_exact_category():
    fake_requests = pd.DataFrame(
        [_fake_request(description="  Street Surface Maintenance  ")]
    )

    metrics, reconciliation, _ = process_requests(fake_requests, date(2024, 6, 4))

    assert reconciliation["selected_scope_rows"] == 1
    assert len(metrics) == 1


def test_deduplication_keeps_earliest_valid_date_then_lowest_object_id():
    fake_requests = pd.DataFrame(
        [
            _fake_request("FAKE-DUP-1", "2024-06-03 12:00", object_id=1),
            _fake_request("FAKE-DUP-1", "2024-06-01 12:00", object_id=9),
            _fake_request("FAKE-DUP-2", "2024-06-01 12:00", object_id=8),
            _fake_request(
                "FAKE-DUP-2",
                "2024-06-01 12:00",
                closed="2024-06-02 12:00",
                object_id=3,
            ),
        ]
    )

    metrics, reconciliation, _ = process_requests(fake_requests, date(2024, 6, 4))

    assert reconciliation["duplicate_rows_excluded"] == 2
    assert reconciliation["rows_kept_for_metrics"] == 2
    by_id = {}
    for metric in metrics:
        # The result intentionally contains no source request identifiers.
        by_id.setdefault(metric["wait_days"], 0)
        by_id[metric["wait_days"]] += 1
    assert by_id == {2: 1, 1: 1}


def test_deduplication_sorts_invalid_dates_after_valid_dates():
    fake_invalid = _fake_request("FAKE-DUP-INVALID", object_id=1)
    fake_invalid["DATE_INITIATED"] = "FAKE-invalid-timestamp"
    fake_requests = pd.DataFrame(
        [
            fake_invalid,
            _fake_request("FAKE-DUP-INVALID", "2024-06-01 12:00", object_id=9),
        ]
    )

    kept, removed = deduplicate_requests(fake_requests)

    assert removed == 1
    assert kept.iloc[0]["ObjectId"] == 9


def test_closed_before_initiated_is_excluded_from_timing():
    fake_requests = pd.DataFrame(
        [_fake_request(initiated="2024-06-03 12:00", closed="2024-06-02 12:00")]
    )

    metrics, reconciliation, _ = process_requests(fake_requests, date(2024, 6, 4))

    assert metrics == []
    assert reconciliation["timing_exclusions"]["closed_before_initiated"] == 1
    assert reconciliation["rows_kept_for_metrics"] == 0


def test_missing_and_invalid_dates_are_reported_as_distinct_exclusions():
    missing_initiated = _fake_request("FAKE-MISSING-OPEN", initiated=None)
    invalid_initiated = _fake_request("FAKE-INVALID-OPEN")
    invalid_initiated["DATE_INITIATED"] = "FAKE-invalid-timestamp"
    invalid_closed = _fake_request("FAKE-INVALID-CLOSE")
    invalid_closed["DATE_CLOSED"] = "FAKE-invalid-timestamp"
    fake_requests = pd.DataFrame(
        [missing_initiated, invalid_initiated, invalid_closed]
    )

    metrics, reconciliation, _ = process_requests(fake_requests, date(2024, 6, 4))

    assert metrics == []
    assert reconciliation["timing_exclusions"]["missing_initiated_date"] == 1
    assert reconciliation["timing_exclusions"]["invalid_initiated_date"] == 1
    assert reconciliation["timing_exclusions"]["invalid_close_date"] == 1


def test_open_request_is_kept_as_right_censored_through_pull_date():
    fake_requests = pd.DataFrame(
        [_fake_request(initiated="2024-06-01 12:00", closed=None)]
    )

    metrics, reconciliation, _ = process_requests(fake_requests, date(2024, 6, 10))
    observations = survival_observations(metrics, date(2024, 6, 10))

    assert reconciliation["open_censored_rows_kept"] == 1
    assert metrics[0]["event"] is False
    assert observations == [(9, False)]


def test_kaplan_meier_matches_hand_worked_tied_event_and_censor_example():
    # At day 1: S=3/4. At day 2: S=(3/4)*(1-1/3)=1/2.
    # At day 4: the final event brings S to zero.
    fake_observations = [(1, True), (2, True), (2, False), (4, True)]

    assert kaplan_meier_quantile(fake_observations, 0.5) == (2, 4)
    assert kaplan_meier_quantile(fake_observations, 0.9) == (4, 4)


def test_kaplan_meier_reports_unreached_quantile_and_small_sample_suppression():
    fake_censored = [(2, False), (5, False), (10, True), (10, False), (10, False)]
    fake_small = [(1, True)] * 29

    assert kaplan_meier_quantile(fake_censored, 0.5) == (None, 10)
    assert _reported_metric(fake_small, 0.5) == {
        "status": "too_few",
        "days": None,
        "lower_bound_days": None,
        "n": 29,
    }


@pytest.mark.parametrize(
    ("month", "expected"),
    [
        (3, "winter"),
        (4, "standard_season"),
        (11, "standard_season"),
        (12, "winter"),
    ],
)
def test_season_split_uses_april_through_november(month, expected):
    assert season_for(month) == expected


def test_public_output_suppresses_statistics_below_minimum_sample():
    fake_observations = [(1, True)] * 29

    assert _reported_metric(fake_observations, 0.5)["status"] == "too_few"


def test_public_payload_has_last_twelve_complete_months_and_aggregate_fields_only():
    fake_records = [
        {
            "initiated_date": f"2025-{month:02d}-10",
            "closed_date": f"2025-{month:02d}-12",
            "district": "1",
            "event": True,
            "wait_days": 2,
        }
        for month in range(1, 13)
    ]
    fake_records.append(
        {
            "initiated_date": "2025-11-10",
            "closed_date": None,
            "district": "2",
            "event": False,
            "wait_days": None,
        }
    )
    fake_counts = {"service_requests": 13, "work_orders": 0}
    payloads = build_public_payloads(fake_records, date(2026, 1, 15), fake_counts)

    assert payloads["summary.json"]["headline_period"] == {
        "start": "2025-01-01",
        "end": "2025-12-31",
        "label": "last 12 complete calendar months",
    }
    assert payloads["summary.json"]["wait_until_request_closed"]["median"]["status"] == "too_few"
    assert payloads["summary.json"]["open_backlog"]["oldest_age_days"] == 66
    monthly = payloads["monthly.json"]
    month_index = {month: index for index, month in enumerate(monthly["periods"])}
    district_months = {
        row["district"]: row["values"] for row in monthly["districts"]
    }
    assert sum(values[month_index["2025-01"]][0] for values in district_months.values()) == 1
    assert sum(values[month_index["2025-11"]][0] for values in district_months.values()) == 2
    district_backlog = {
        row["district"]: row
        for row in payloads["districts.json"]["open_backlog_by_district"]
    }
    assert district_backlog["2"]["n"] == 1
    assert district_backlog["2"]["oldest_age_days"] == 66
    assert district_backlog["2"]["age_bands"]["over_30_days"] == 1
    assert district_backlog["1"]["oldest_age_days"] is None
    assert "REQUEST_ID" not in str(payloads)
    assert "ADDRESS" not in str(payloads)


def test_weekly_payload_uses_latest_52_complete_monday_start_weeks():
    fake_records = [
        {
            "initiated_date": "2025-01-13",
            "closed_date": "2025-01-14",
            "district": "1",
            "event": True,
            "wait_days": 1,
        },
        {
            "initiated_date": "2025-01-19",
            "closed_date": None,
            "district": "2",
            "event": False,
            "wait_days": None,
        },
        {
            "initiated_date": "2025-01-01",
            "closed_date": "2025-01-15",
            "district": "1",
            "event": True,
            "wait_days": 14,
        },
        {
            "initiated_date": "2026-01-05",
            "closed_date": None,
            "district": "1",
            "event": False,
            "wait_days": None,
        },
        {
            "initiated_date": "2026-01-12",
            "closed_date": "2026-01-14",
            "district": "2",
            "event": True,
            "wait_days": 2,
        },
    ]

    payloads = build_public_payloads(
        fake_records,
        date(2026, 1, 15),
        {"service_requests": len(fake_records), "work_orders": 0},
    )

    weekly = payloads["weekly.json"]
    assert weekly["period"] == {
        "start": "2025-01-13",
        "end": "2026-01-11",
        "label": "latest 52 complete Monday-start weeks",
    }
    assert len(weekly["weeks"]) == 52
    assert weekly["all"][0] == [2, 2]
    assert weekly["all"][-1] == [1, 0]

    district_weeks = {
        row["district"]: row["values"] for row in weekly["districts"]
    }
    assert district_weeks["1"][0] == [1, 2]
    assert district_weeks["2"][0] == [1, 0]
    assert "REQUEST_ID" not in str(weekly)
    assert "ADDRESS" not in str(weekly)


def test_public_json_files_are_under_size_limit_and_have_no_banned_fields():
    files = sorted(PUBLIC_DATA.glob("*.json"))
    assert files, "Run python python/pipeline.py to generate public data first."
    assert sum(path.stat().st_size for path in files) < 50_000
    for path in files:
        _json_safe_payload(json.loads(path.read_text(encoding="utf-8")))


def test_generated_district_and_headline_aggregates_reconcile():
    summary = json.loads((PUBLIC_DATA / "summary.json").read_text(encoding="utf-8"))
    monthly = json.loads((PUBLIC_DATA / "monthly.json").read_text(encoding="utf-8"))
    weekly = json.loads((PUBLIC_DATA / "weekly.json").read_text(encoding="utf-8"))
    districts = json.loads((PUBLIC_DATA / "districts.json").read_text(encoding="utf-8"))

    headline_n = summary["population"]["n"]
    assert headline_n == sum(row["n"] for row in districts["districts"])
    assert headline_n == sum(row["n"] for row in summary["season_counts"])

    monthly_districts = {
        row["district"]: row["values"] for row in monthly["districts"]
    }
    for index, totals in enumerate(monthly["all"]):
        assert totals[0] == sum(values[index][0] for values in monthly_districts.values())
        assert totals[1] == sum(values[index][1] for values in monthly_districts.values())

    weekly_districts = {
        row["district"]: row["values"] for row in weekly["districts"]
    }
    for index, totals in enumerate(weekly["all"]):
        assert totals[0] == sum(values[index][0] for values in weekly_districts.values())
        assert totals[1] == sum(values[index][1] for values in weekly_districts.values())

    backlog = summary["open_backlog"]
    by_district = districts["open_backlog_by_district"]
    assert backlog["n"] == sum(row["n"] for row in by_district)
    oldest_by_district = [
        row["oldest_age_days"] for row in by_district if row["oldest_age_days"] is not None
    ]
    assert backlog["oldest_age_days"] == (
        max(oldest_by_district) if oldest_by_district else None
    )
    for age_band, count in backlog["age_bands"].items():
        assert count == sum(row["age_bands"][age_band] for row in by_district)


def test_monthly_payload_includes_the_current_partial_month_and_same_month_closures():
    fake_records = [
        {
            "initiated_date": "2025-12-10",
            "closed_date": "2026-01-02",
            "district": "1",
            "event": True,
            "wait_days": 23,
        },
        {
            "initiated_date": "2026-01-02",
            "closed_date": None,
            "district": "1",
            "event": False,
            "wait_days": None,
        },
    ]

    monthly = build_public_payloads(
        fake_records,
        date(2026, 1, 15),
        {"service_requests": 2, "work_orders": 0},
    )["monthly.json"]

    assert monthly["periods"] == ["2025-12", "2026-01"]
    assert monthly["partial_period"] == "2026-01"
    assert monthly["all"] == [[1, 0], [1, 1]]
    assert monthly["districts"] == [
        {"district": "1", "values": [[1, 0], [1, 1]]}
    ]


def test_closed_wait_counts_support_elapsed_day_comparison_without_row_data():
    fake_records = [
        {
            "initiated_date": "2025-01-01",
            "closed_date": "2025-01-01",
            "district": "1",
            "event": True,
            "wait_days": 0,
        },
        {
            "initiated_date": "2025-02-01",
            "closed_date": "2025-02-03",
            "district": "1",
            "event": True,
            "wait_days": 2,
        },
        {
            "initiated_date": "2025-03-01",
            "closed_date": "2025-03-03",
            "district": "2",
            "event": True,
            "wait_days": 2,
        },
        {
            "initiated_date": "2025-04-01",
            "closed_date": None,
            "district": "2",
            "event": False,
            "wait_days": None,
        },
    ]

    payloads = build_public_payloads(
        fake_records,
        date(2026, 1, 15),
        {"service_requests": 4, "work_orders": 0},
    )

    summary = payloads["summary.json"]
    assert summary["closed_wait_counts"] == [[0, 1], [2, 2]]
    district_counts = {
        row["district"]: row["closed_wait_counts"]
        for row in payloads["districts.json"]["districts"]
    }
    assert district_counts == {"1": [[0, 1], [2, 1]], "2": [[2, 1]]}
    assert "FAKE" not in str(payloads)


def test_public_privacy_guard_rejects_banned_field_names():
    with pytest.raises(ValueError, match="prohibited field"):
        _json_safe_payload({"REQUEST_ID": "FAKE-REQUEST-123"})


def test_oldest_open_age_is_null_when_no_requests_are_open():
    closed_records = [
        {
            "initiated_date": f"2025-{month:02d}-10",
            "closed_date": f"2025-{month:02d}-12",
            "district": "1",
            "event": True,
            "wait_days": 2,
        }
        for month in range(1, 13)
    ]

    payloads = build_public_payloads(
        closed_records,
        date(2026, 1, 15),
        {"service_requests": len(closed_records), "work_orders": 0},
    )

    assert payloads["summary.json"]["open_backlog"]["oldest_age_days"] is None
    assert payloads["districts.json"]["open_backlog_by_district"][0]["oldest_age_days"] is None


def test_custom_fields_are_trimmed_and_pivoted_without_publishing_values():
    fake_custom = pd.DataFrame(
        {
            "REQUESTID": [" FAKE-REQUEST-1 "],
            "CUSTOM_FIELD_NAME": [" FAKE field "],
            "CUSTOM_FIELD_VALUE": ["FAKE private detail"],
        }
    )

    cleaned = clean_custom_fields(
        fake_custom, "REQUESTID", "CUSTOM_FIELD_NAME", "CUSTOM_FIELD_VALUE"
    )
    pivot = pivot_custom_fields(
        cleaned, "REQUESTID", "CUSTOM_FIELD_NAME", "CUSTOM_FIELD_VALUE"
    )

    assert pivot.index.tolist() == ["FAKE-REQUEST-1"]
    assert pivot.columns.tolist() == ["FAKE field"]
    assert pivot.iloc[0, 0] == "FAKE private detail"
