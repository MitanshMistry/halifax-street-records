"""FAKE aggregate fixtures for static HTML and inline-SVG rendering."""
import html
import pytest

from build_site import (
    DISTRICT_PLACES,
    _render_companion,
    _season_note,
    load_site_data,
    render_monthly_svg,
    render_page,
)


def _metric(status, days=None, lower_bound_days=None, n=40):
    return {
        "status": status,
        "days": days,
        "lower_bound_days": lower_bound_days,
        "n": n,
    }


def _fake_site_data():
    return {
        "meta": {
            "pull_date": "2026-01-15",
            "scope": "Street surface repair requests",
            "raw_row_counts": {
                "service_requests": 100,
                "work_orders": 10,
                "wo_custom_fields": 5,
                "sr_custom_fields": 4,
            },
        },
        "summary": {
            "as_of_date": "2026-01-15",
            "headline_period": {
                "start": "2025-01-01",
                "end": "2025-12-31",
                "label": "last 12 complete calendar months",
            },
            "population": {"n": 40, "closed": 35, "open_censored": 5},
            "wait_until_request_closed": {
                "median": _metric("available", 4),
                "p90": _metric("available", 8),
            },
            "closed_wait_counts": [[0, 1], [4, 20], [8, 14]],
            "open_backlog": {
                "as_of_date": "2026-01-15",
                "n": 10,
                "oldest_age_days": 60,
                "age_bands": {
                    "0_to_7_days": 1,
                    "8_to_14_days": 1,
                    "15_to_30_days": 3,
                    "over_30_days": 5,
                },
            },
            "season_counts": [],
        },
        "districts": {
            "period": {"start": "2025-01-01", "end": "2025-12-31"},
            "districts": [
                {
                    "district": "2",
                    "n": 29,
                    "open_censored": 3,
                    "median": _metric("too_few", n=29),
                    "p90": _metric("too_few", n=29),
                    "closed_wait_counts": [[2, 26]],
                },
                {
                    "district": "7",
                    "n": 40,
                    "open_censored": 5,
                    "median": _metric("available", 4),
                    "p90": _metric("available", 8),
                    "closed_wait_counts": [[0, 1], [4, 20], [8, 14]],
                },
                {
                    "district": "Unknown",
                    "n": 1,
                    "open_censored": 0,
                    "median": _metric("too_few", n=1),
                    "p90": _metric("too_few", n=1),
                    "closed_wait_counts": [[1, 1]],
                },
            ],
            "open_backlog_by_district": [
                {
                    "district": "2",
                    "n": 4,
                    "oldest_age_days": 60,
                    "age_bands": {
                        "0_to_7_days": 0,
                        "8_to_14_days": 0,
                        "15_to_30_days": 1,
                        "over_30_days": 3,
                    },
                },
                {
                    "district": "7",
                    "n": 6,
                    "oldest_age_days": 35,
                    "age_bands": {
                        "0_to_7_days": 0,
                        "8_to_14_days": 0,
                        "15_to_30_days": 5,
                        "over_30_days": 1,
                    },
                },
                {
                    "district": "Unknown",
                    "n": 0,
                    "oldest_age_days": None,
                    "age_bands": {
                        "0_to_7_days": 0,
                        "8_to_14_days": 0,
                        "15_to_30_days": 0,
                        "over_30_days": 0,
                    },
                },
            ],
        },
        "monthly": {
            "periods": ["2025-01", "2025-02", "2025-03"],
            "all": [[10, 8], [12, 14], [18, 15]],
            "districts": [
                {"district": "2", "values": [[2, 1], [3, 4], [4, 3]]},
                {"district": "7", "values": [[8, 7], [9, 10], [14, 12]]},
                {"district": "Unknown", "values": [[0, 0], [0, 0], [0, 0]]},
            ],
            "partial_period": "2025-03",
        },
        "weekly": {
            "period": {
                "start": "2025-01-06",
                "end": "2026-01-04",
                "label": "latest 52 complete Monday-start weeks",
            },
            "weeks": ["2025-01-06", "2025-01-13"],
            "all": [[2, 3], [4, 2]],
            "districts": [
                {"district": "2", "values": [[1, 2], [2, 1]]},
                {"district": "7", "values": [[1, 1], [2, 1]]},
                {"district": "Unknown", "values": [[0, 0], [0, 0]]},
            ],
        },
    }


def test_static_page_contains_readable_answer_charts_tables_and_route():
    page = render_page(_fake_site_data(), selected="7")

    assert "How long past reports took to close in District 7" in page
    assert "Halifax South Downtown" in page
    assert '<p class="answer-primary">4 days</p>' in page
    assert "For 9 in 10 reports, HRM recorded a close date within 8 days." in page
    assert "Estimate based on 40 reports started between 1 Jan 2025 and 31 Dec 2025. 5 had no close date as of the HRM data download on 15 Jan 2026." in page
    assert "6 HRM records</strong> across all dates" in page
    assert "HRM closing a report does not confirm the road was repaired." in page
    assert "Estimated time for about half of reports to have a close date: 4 days; for 9 in 10 reports: 8 days. Based on 40 reports." in page
    assert "in District 7 — Halifax South Downtown" in page
    assert "find your district with HRM" not in page
    assert "How long have HRM’s past reports taken to close?" in page
    assert "Showing District 7 — Halifax South Downtown. Use this menu to switch districts or select All of HRM." in page
    assert "This page shows District 7 — Halifax South Downtown. Use the district links below to open another area." in page
    assert 'data-selected-district="7"' in page
    assert "data-fixed-district" not in page
    assert 'id="district-submit" disabled hidden' in page
    assert '<option value="7" selected' in page
    assert '>District 7 — Halifax South Downtown</option>' in page
    assert 'href="../district-2/"' in page
    assert 'href="../district-7/"' in page
    assert "<table" in page
    assert "<svg" in page
    assert "Loading data" not in page
    assert "median" not in page.lower()


def test_site_name_and_tagline_are_consistent_on_all_page_templates():
    pages = [
        render_page(_fake_site_data()),
        render_page(_fake_site_data(), selected="7"),
    ]
    pages.extend(
        _render_companion(name, _fake_site_data())
        for name in (
            "about.html",
            "whose-road.html",
            "car-damage.html",
            "about-errors.html",
            "404.html",
        )
    )
    tagline = (
        "Past reports about road-surface problems, when HRM marked them closed, and where to report an issue."
    )

    for page in pages:
        assert "Halifax Street Records" in page
        assert tagline in page
        assert "| Halifax Street Records</title>" in page
        assert "Road surface records" not in page


def test_home_explains_district_lookup_open_reports_and_close_date():
    page = render_page(_fake_site_data())

    assert "How long have HRM’s past reports taken to close?" in page
    assert "Your HRM district" in page
    assert "Keep “All of HRM” selected" in page
    assert 'href="https://www.halifax.ca/city-hall/districts-councillors/district-look"' in page
    assert "this site never receives it" in page
    assert "they are not assumed closed" in page
    assert page.index("HRM closing a report") < page.index('<div class="range-visual">')
    assert page.index('</article>', page.index('class="answer-card"')) < page.index('class="picker-help"')
    assert "class=\"ten-dots\"" not in page
    assert "pull-note" not in page
    assert "Estimate based on 40 reports started between 1 Jan 2025 and 31 Dec 2025" in page
    assert "HRM data download on 15 Jan 2026" in page
    assert "District not recorded — place unknown" in page


def test_directory_separates_twelve_month_reports_from_all_date_backlog():
    page = render_page(_fake_site_data(), selected="7")

    assert "Reports in past 12 full months" in page
    assert "No close date recorded" in page
    assert "no-close-date count includes reports from all dates, not just that period" in page
    assert "as of 15 January 2026" in page


def test_small_district_explanation_names_the_all_hrm_estimate_area():
    page = render_page(_fake_site_data(), selected="2")

    assert "For All of HRM, “half”" in page
    assert "For District 2, “half”" not in page


def test_season_note_uses_matched_complete_years_and_shows_month_bases():
    months = []
    values = []
    for year, winter_count, other_count in (
        (2021, 2, 10),
        (2022, 4, 20),
        (2023, 100, 100),
    ):
        for month in range(1, 13):
            months.append(f"{year}-{month:02d}")
            if (year, month) == (2021, 4):
                count = 0
            elif month in (12, 1, 2, 3):
                count = winter_count
            else:
                count = other_count
            values.append([count, 0])

    note = _season_note(months, values, partial_period="2023-03")

    assert "Across full years 2021–2022" in note
    assert "average of 3 reports per month from December to March (based on 8 months)" in note
    assert "14.4 per month from April to November (based on 16 months)" in note
    assert "road conditions or work completed by crews" in note


def test_season_note_is_omitted_when_no_complete_calendar_year_exists():
    months = ["2025-01", "2025-02", "2025-03"]
    values = [[50, 0], [60, 0], [70, 0]]

    assert _season_note(months, values, partial_period="2025-03") == ""


def test_every_numeric_district_picker_option_has_its_official_place():
    page = render_page(load_site_data())

    for code, place in DISTRICT_PLACES.items():
        option_text = html.escape(f"District {code} — {place}")
        assert f">{option_text}</option>" in page
        assert f">{option_text}</a>" in page


def test_methodology_cites_current_place_labels_and_historical_boundary_limit():
    page = _render_companion("about.html", _fake_site_data())

    assert "Districts and Councillors list" in page
    assert "checked 25 November 2026" in page
    assert "we do not move older reports to today's boundaries" in page
    assert "District Look-up" in page


def test_methodology_explains_matched_year_seasonal_report_averages():
    page = _render_companion("about.html", _fake_site_data())

    assert "using the same complete years" in page
    assert "We leave out years that do not include all 12 months" in page
    assert "A month with no reports still counts" in page
    assert "do not tell us how bad road conditions were, whether repairs were completed, or how much work crews did" in page


def test_methodology_explains_data_terms_in_plain_language():
    page = _render_companion("about.html", _fake_site_data())

    assert "“Custom Fields” for extra details linked to reports or work orders (recorded jobs)." in page
    assert "HRM groups these reports under “Street Surface Maintenance.” This category covers more than potholes." in page
    assert "right-censored" not in page
    assert "Kaplan-Meier" not in page


def test_vehicle_damage_guide_uses_plain_claim_guidance():
    page = _render_companion("car-damage.html", _fake_site_data())

    assert "HRM’s claim information does not say exactly what details you must provide." in page
    assert "HRM’s public pages do not say who is at fault, whether you qualify for compensation, or what will happen with an individual claim." in page


def test_small_district_uses_all_hrm_answer_and_explains_fallback():
    page = render_page(_fake_site_data(), selected="2")

    assert "District 2 — Lawrencetown - The Lakes - Chezzetcook - Eastern Shore has 29 reports, fewer than the 30 needed to estimate a time." in page
    assert "Showing All of HRM instead." in page
    assert '<p class="answer-primary">4 days</p>' in page
    assert "For 9 in 10 reports, HRM recorded a close date within 8 days." in page


def test_monthly_svg_marks_partial_month_and_winter_accessibly():
    svg = render_monthly_svg(
        ["2025-12", "2026-01"],
        [[2, 1], [7, 4]],
        partial_period="2026-01",
        mobile=True,
    )

    assert 'role="img"' in svg
    assert "<title>" in svg
    assert 'id="partial-month"' in svg
    assert "partial month" in svg.lower()
    assert "Winter" in svg
    assert "7" in svg


def test_volume_chart_uses_report_dates_not_close_date_counts():
    svg = render_monthly_svg(["2025-03"], [[18, 15]])

    assert "18 reports recorded" in svg
    assert "15 reports recorded" not in svg


def test_home_page_keeps_resident_question_order_and_chart_tables():
    page = render_page(_fake_site_data())
    section_ids = (
        'id="answer-heading"',
        'id="open-records"',
        'id="request-volume"',
        'id="districts"',
        'id="guides"',
        'id="limits-heading"',
    )

    positions = [page.index(section_id) for section_id in section_ids]
    assert positions == sorted(positions)
    assert page.count("<table") >= 5
    assert "covers more than potholes" in page
    assert "does not update live" in page


@pytest.mark.parametrize("district", ["../7", "1/2", "Unknown/2", ""])
def test_page_rejects_unsafe_district_route_values(district):
    with pytest.raises(ValueError, match="source district code"):
        render_page(_fake_site_data(), selected=district)
