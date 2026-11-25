"""FAKE values only. These tests verify privacy-safe reporting and scan summaries."""
import pandas as pd

from scan import (
    _qualification_gate,
    counts,
    keyword_hits,
    keyword_term_counts,
    _selected_type_custom_field_scan,
    scan_requests_with_custom_fields,
)


def test_counts_withhold_address_and_free_text_values():
    fake_values = pd.Series(
        [
            "Street Surface Maintenance",
            "999 Fake Street pothole report, call 555-010-0100",
            "Please inspect the pothole beside my house as soon as possible.",
        ]
    )

    report = "\n".join(counts(fake_values, "DESCRIPTION"))

    assert "3 distinct values" in report
    assert "999 Fake Street" not in report
    assert "555-010-0100" not in report
    assert "beside my house" not in report


def test_keyword_report_redacts_sensitive_matching_value():
    fake_frame = pd.DataFrame(
        {
            "DESCRIPTION": ["Pothole at 999 Fake Street"],
            "ADDRESS": ["999 Fake Street"],
            "LATITUDE": [44.6],
            "LONGITUDE": [-63.6],
            "REQUEST_ID": ["FAKE-123456"],
        }
    )

    report = "\n".join(keyword_hits("fake_requests", fake_frame))

    assert "1 matching rows" in report
    assert "999 Fake Street" not in report
    assert "FAKE-123456" not in report
    assert "44.6" not in report
    assert "Pothole at" not in report


def test_keyword_summary_does_not_unmask_repeated_free_text():
    fake_frame = pd.DataFrame(
        {
            "DESCRIPTION": [
                "Pothole beside Jordan's home",
                "Pothole beside Jordan's home",
                "Pothole beside Jordan's home",
            ]
        }
    )

    report = "\n".join(keyword_hits("fake_requests", fake_frame))

    assert "3 matching rows" in report
    assert "Jordan" not in report
    assert "Pothole beside" not in report


def test_request_summary_never_prints_private_fields():
    fake_requests = pd.DataFrame(
        {
            "REQUEST_ID": ["FAKE-123", "FAKE-124"],
            "DATE_INITIATED": [1700000000000, 1700086400000],
            "DATE_CLOSED": [None, 1700172800000],
            "DESCRIPTION": ["Pothole on Fake Road", "Pothole on Fake Road"],
            "REQUEST_CATEGORY": ["Fake category", "Fake category"],
            "PRIORITY": [1, 2],
            "STATUS": ["Open", "Closed"],
            "DEPT_RESPONSIBILITY": ["Fake department", "Fake department"],
            "INITIATED_BY": ["311 Online", "INTERNAL"],
            "WORK_ORDER": ["N", "Y"],
            "ADDRESS": ["999 Fake Street", "100 Fake Avenue"],
            "LATITUDE": [44.6, 44.7],
            "LONGITUDE": [-63.6, -63.7],
            "DISTRICT": ["Fake District", "Fake District"],
        }
    )
    fake_work_orders = pd.DataFrame({"WORK_ORDER_ID": [123456]})

    fake_custom_fields = pd.DataFrame(
        {"CUSTOM_FIELD_NAME": ["Fake category"], "CUSTOM_FIELD_VALUE": ["fake value"]}
    )
    report = "\n".join(
        scan_requests_with_custom_fields(fake_requests, fake_work_orders, fake_custom_fields)
    )

    assert "Open by missing close date: 1" in report
    assert "Distinct ID-like tokens" in report
    assert "only known category labels" in report
    for private_value in ("FAKE-123", "999 Fake Street", "44.6", "-63.6"):
        assert private_value not in report


def test_qualification_gate_selects_surface_requests_at_the_plan_threshold():
    years = [2018] * 150 + [2019] * 150
    fake_requests = pd.DataFrame(
        {
            "DATE_INITIATED": [
                int(pd.Timestamp(f"{year}-06-01", tz="UTC").timestamp() * 1000)
                for year in years
            ],
            "DESCRIPTION": ["FAKE Street Surface Maintenance"] * 300,
            "REQUEST_CATEGORY": ["FAKE_ROADS"] * 300,
        }
    )

    report = "\n".join(_qualification_gate(fake_requests))

    assert "FAKE Street Surface Maintenance: 300 requests across 2 calendar years" in report
    assert "Stage 1 outcome: B" in report


def test_qualification_gate_rejects_a_type_below_the_row_threshold():
    years = [2018] * 150 + [2019] * 149
    fake_requests = pd.DataFrame(
        {
            "DATE_INITIATED": [
                int(pd.Timestamp(f"{year}-06-01", tz="UTC").timestamp() * 1000)
                for year in years
            ],
            "DESCRIPTION": ["FAKE Street Surface Maintenance"] * 299,
            "REQUEST_CATEGORY": ["FAKE_ROADS"] * 299,
        }
    )

    report = "\n".join(_qualification_gate(fake_requests))

    assert "FAKE Street Surface Maintenance" not in report
    assert "Stage 1 outcome: C" in report


def test_keyword_term_counts_report_only_aggregates():
    fake_frames = {
        "fake_requests": pd.DataFrame(
            {"DESCRIPTION": ["FAKE pothole", "FAKE asphalt patch", "FAKE pothole"]}
        )
    }

    report = "\n".join(keyword_term_counts(fake_frames))

    assert "fake_requests.DESCRIPTION / pothole: 2 rows; 1 distinct value(s)" in report
    assert "fake_requests.DESCRIPTION / asphalt: 1 rows; 1 distinct value(s)" in report
    assert "FAKE pothole" not in report


def test_selected_type_custom_fields_are_joined_and_summarized_without_values():
    fake_requests = pd.DataFrame(
        {
            "REQUEST_ID": ["FAKE-REQ-1", "FAKE-REQ-2"],
            "DESCRIPTION": ["FAKE Street Surface Maintenance"] * 2,
            "DATE_INITIATED": [
                int(pd.Timestamp("2018-06-01", tz="UTC").timestamp() * 1000),
                int(pd.Timestamp("2019-06-01", tz="UTC").timestamp() * 1000),
            ],
        }
    )
    fake_custom = pd.DataFrame(
        {
            "REQUESTID": ["FAKE-REQ-1", "FAKE-REQ-2"],
            "CUSTOM_FIELD_NAME": ["FAKE depth", "FAKE detail"],
            "CUSTOM_FIELD_VALUE": ["FAKE pothole depth", "FAKE pothole location"],
        }
    )

    report = "\n".join(
        _selected_type_custom_field_scan(
            fake_requests, fake_custom, "FAKE Street Surface Maintenance"
        )
    )

    assert "Matching custom-field rows: 2" in report
    assert "size/depth-related field names: 1" in report
    assert "Requests remaining after custom-field pothole filter: 2 across 2 calendar years" in report
    for private_value in ("FAKE-REQ-1", "FAKE pothole depth", "FAKE pothole location"):
        assert private_value not in report
