"""Build privacy-safe Layer 1 aggregates from the cached HRM tables."""
import argparse
from collections import defaultdict
from datetime import date, datetime, timedelta
import gc
import json
import math
from numbers import Integral, Real
from pathlib import Path
import re
from zoneinfo import ZoneInfo

import pandas as pd

from dates import TZ, ms_to_halifax
from hrm_api import RAW_DIR, TABLES, load_table

ROOT = Path(__file__).resolve().parent.parent
OUTPUT_DIR = ROOT / "docs" / "data"
RECONCILIATION = ROOT / "project" / "reconciliation.md"
DEFINITIONS_VERSION = "1.1"
SCOPE_DESCRIPTION = "Street Surface Maintenance"
SCOPE_LABEL = "Street surface repair requests"
MINIMUM_SAMPLE = 30
DISTRICT_PATTERN = re.compile(r"[0-9]+\Z")
PUBLIC_KEYS = {
    "pull_date",
    "generated_at",
    "definitions_version",
    "scope",
    "raw_row_counts",
    "service_requests",
    "work_orders",
    "wo_custom_fields",
    "sr_custom_fields",
    "as_of_date",
    "headline_period",
    "start",
    "end",
    "label",
    "population",
    "n",
    "closed",
    "open_censored",
    "wait_until_request_closed",
    "method",
    "median",
    "p90",
    "status",
    "days",
    "lower_bound_days",
    "open_backlog",
    "oldest_age_days",
    "age_bands",
    "0_to_7_days",
    "8_to_14_days",
    "15_to_30_days",
    "over_30_days",
    "season_counts",
    "season",
    "district",
    "open_backlog_by_district",
    "period",
    "districts",
    "values",
    "periods",
    "partial_period",
    "all",
    "weeks",
    "closed_wait_counts",
}
EXCLUSION_REASONS = (
    "missing_initiated_date",
    "invalid_initiated_date",
    "initiated_after_pull_date",
    "invalid_close_date",
    "closed_after_pull_date",
    "closed_before_initiated",
)


def is_selected_request(description):
    """Apply the one locked request-type rule from project/definitions.md."""
    return not pd.isna(description) and str(description).strip() == SCOPE_DESCRIPTION


def _normalized_ids(values):
    ids = values.astype("string").str.strip()
    return ids.mask(ids.eq(""))


def _raw_values_missing(values):
    text = values.astype("string").str.strip()
    return values.isna() | text.eq("").fillna(False)


def _halifax_dates(values):
    return ms_to_halifax(pd.to_numeric(values, errors="coerce"))


def deduplicate_requests(requests):
    """Keep the earliest valid initiated date, then the lowest source object ID."""
    required = {"REQUEST_ID", "DATE_INITIATED", "ObjectId"}
    missing = required.difference(requests.columns)
    if missing:
        raise ValueError("Service Request data is missing required deduplication columns.")

    frame = requests.copy()
    frame["_request_id"] = _normalized_ids(frame["REQUEST_ID"])
    opened = _halifax_dates(frame["DATE_INITIATED"])
    frame["_opened_sort"] = opened.dt.strftime("%Y-%m-%d").fillna("9999-12-31")
    frame["_object_sort"] = pd.to_numeric(frame["ObjectId"], errors="coerce").fillna(math.inf)
    frame["_source_order"] = range(len(frame))

    with_ids = frame["_request_id"].notna()
    identified = frame.loc[with_ids].sort_values(
        ["_request_id", "_opened_sort", "_object_sort", "_source_order"],
        kind="mergesort",
    )
    kept_identified = identified.drop_duplicates("_request_id", keep="first")
    kept = pd.concat([kept_identified, frame.loc[~with_ids]], axis=0).sort_values(
        "_source_order", kind="mergesort"
    )
    removed = len(frame) - len(kept)
    return kept.drop(
        columns=["_request_id", "_opened_sort", "_object_sort", "_source_order"]
    ), removed


def normalize_district(value):
    """Retain the source district code and render blanks as Unknown."""
    if pd.isna(value):
        return "Unknown"
    if isinstance(value, bool):
        raise ValueError("Unexpected non-numeric district value; refusing to publish.")
    if isinstance(value, Integral):
        return str(value)
    if isinstance(value, Real) and float(value).is_integer():
        return str(int(value))
    text = str(value).strip()
    if not text:
        return "Unknown"
    if not DISTRICT_PATTERN.fullmatch(text):
        raise ValueError("Unexpected non-numeric district value; refusing to publish.")
    return text


def process_requests(requests, pull_date):
    """Select, deduplicate, classify timing rows, and return safe analytical records."""
    required = {
        "REQUEST_ID",
        "DESCRIPTION",
        "DATE_INITIATED",
        "DATE_CLOSED",
        "DISTRICT",
        "ObjectId",
    }
    if required.difference(requests.columns):
        raise ValueError("Service Request data is missing required pipeline columns.")

    selected_mask = requests["DESCRIPTION"].map(is_selected_request).fillna(False)
    scoped = requests.loc[selected_mask].copy()
    scope_ids = set(_normalized_ids(scoped["REQUEST_ID"]).dropna().tolist())
    unique, duplicate_rows = deduplicate_requests(scoped)

    opened = _halifax_dates(unique["DATE_INITIATED"])
    closed = _halifax_dates(unique["DATE_CLOSED"])
    opened_dates = opened.dt.date
    closed_dates = closed.dt.date
    opened_missing = _raw_values_missing(unique["DATE_INITIATED"])
    closed_missing = _raw_values_missing(unique["DATE_CLOSED"])

    reasons = pd.Series(index=unique.index, dtype="object")
    reasons.loc[opened_missing] = "missing_initiated_date"
    reasons.loc[~opened_missing & opened.isna()] = "invalid_initiated_date"

    opened_future = opened_dates.map(
        lambda value: pd.notna(value) and value > pull_date
    )
    reasons.loc[reasons.isna() & opened_future] = "initiated_after_pull_date"

    invalid_closed = ~closed_missing & closed.isna()
    reasons.loc[reasons.isna() & invalid_closed] = "invalid_close_date"

    closed_future = closed_dates.map(
        lambda value: pd.notna(value) and value > pull_date
    )
    reasons.loc[reasons.isna() & closed_future] = "closed_after_pull_date"

    closed_before_opened = pd.Series(
        [
            pd.notna(closed_date)
            and pd.notna(opened_date)
            and closed_date < opened_date
            for closed_date, opened_date in zip(closed_dates, opened_dates)
        ],
        index=unique.index,
        dtype=bool,
    )
    reasons.loc[reasons.isna() & closed_before_opened] = "closed_before_initiated"

    excluded = {reason: int(reasons.eq(reason).sum()) for reason in EXCLUSION_REASONS}
    eligible = unique.loc[reasons.isna()].copy()
    eligible_opened = opened.loc[reasons.isna()].dt.date
    eligible_closed = closed.loc[reasons.isna()].dt.date
    eligible_districts = eligible["DISTRICT"].map(normalize_district)

    metrics = []
    for index in eligible.index:
        initiated_date = eligible_opened.loc[index]
        closed_date = eligible_closed.loc[index]
        event = not pd.isna(closed_date)
        metrics.append(
            {
                "initiated_date": initiated_date.isoformat(),
                "closed_date": closed_date.isoformat() if event else None,
                "district": eligible_districts.loc[index],
                "event": event,
                "wait_days": (closed_date - initiated_date).days if event else None,
            }
        )

    reconciliation = {
        "raw_service_request_rows": len(requests),
        "rows_outside_scope": len(requests) - len(scoped),
        "selected_scope_rows": len(scoped),
        "duplicate_rows_excluded": duplicate_rows,
        "unique_scope_rows": len(unique),
        "timing_exclusions": excluded,
        "rows_kept_for_metrics": len(metrics),
        "closed_rows_kept": sum(record["event"] for record in metrics),
        "open_censored_rows_kept": sum(not record["event"] for record in metrics),
    }
    return metrics, reconciliation, scope_ids


def clean_custom_fields(frame, key_column, field_column, value_column):
    """Normalize custom-field keys and labels without persisting their values."""
    required = {key_column, field_column, value_column}
    if required.difference(frame.columns):
        raise ValueError("Custom Field data is missing required columns.")
    cleaned = frame[[key_column, field_column, value_column]].copy()
    for column in (key_column, field_column, value_column):
        cleaned[column] = cleaned[column].astype("string").str.strip()
    cleaned[key_column] = cleaned[key_column].mask(cleaned[key_column].eq(""))
    cleaned[field_column] = cleaned[field_column].mask(cleaned[field_column].eq(""))
    return cleaned.dropna(subset=[key_column, field_column])


def pivot_custom_fields(frame, key_column, field_column, value_column):
    cleaned = clean_custom_fields(frame, key_column, field_column, value_column)
    if cleaned.empty:
        return pd.DataFrame()
    return cleaned.pivot_table(
        index=key_column,
        columns=field_column,
        values=value_column,
        aggfunc="first",
        sort=False,
    )


def season_for(value):
    """Return the documented season for a local calendar date or month."""
    month = value.month if hasattr(value, "month") else int(value)
    return "winter" if month in (12, 1, 2, 3) else "standard_season"


def headline_period(pull_date):
    """Return the last twelve complete calendar months at the pull date."""
    period_end = pull_date.replace(day=1) - timedelta(days=1)
    end_index = period_end.year * 12 + period_end.month - 1
    start_index = end_index - 11
    start_year, start_zero_month = divmod(start_index, 12)
    period_start = date(start_year, start_zero_month + 1, 1)
    return period_start, period_end


def kaplan_meier_quantile(observations, probability):
    """Estimate a time quantile from (duration_days, closed_event) observations."""
    if not 0 < probability < 1:
        raise ValueError("Quantile probability must be between zero and one.")
    if not observations:
        return None, None

    at_time = defaultdict(lambda: [0, 0])
    max_followup = 0
    for duration, event in observations:
        duration = int(duration)
        if duration < 0:
            raise ValueError("Survival durations cannot be negative.")
        at_time[duration][0 if event else 1] += 1
        max_followup = max(max_followup, duration)

    risk_set = len(observations)
    survival = 1.0
    target_survival = 1.0 - probability
    for duration in sorted(at_time):
        events, censored = at_time[duration]
        if events:
            survival *= 1.0 - (events / risk_set)
            if survival <= target_survival + 1e-12:
                return duration, max_followup
        risk_set -= events + censored
    return None, max_followup


def survival_observations(records, as_of_date):
    observations = []
    for record in records:
        initiated = date.fromisoformat(record["initiated_date"])
        if record["event"]:
            duration = int(record["wait_days"])
        else:
            duration = (as_of_date - initiated).days
        observations.append((duration, bool(record["event"])))
    return observations


def _reported_metric(observations, probability):
    n = len(observations)
    estimate, max_followup = kaplan_meier_quantile(observations, probability)
    if n < MINIMUM_SAMPLE:
        return {
            "status": "too_few",
            "days": None,
            "lower_bound_days": None,
            "n": n,
        }
    if estimate is None:
        return {
            "status": "not_reached",
            "days": None,
            "lower_bound_days": max_followup,
            "n": n,
        }
    return {
        "status": "available",
        "days": estimate,
        "lower_bound_days": None,
        "n": n,
    }


def _month_start(value):
    return date(value.year, value.month, 1)


def _monday_start(value):
    return value - timedelta(days=value.weekday())


def _next_month(value):
    return date(value.year + (value.month == 12), value.month % 12 + 1, 1)


def _json_safe_payload(payload):
    def visit(value):
        if isinstance(value, dict):
            for key, child in value.items():
                if key not in PUBLIC_KEYS:
                    raise ValueError("Public output contains a prohibited field.")
                if key == "district" and (
                    not isinstance(child, str)
                    or (child != "Unknown" and not DISTRICT_PATTERN.fullmatch(child))
                ):
                    raise ValueError("Public output contains an unsafe district value.")
                if key == "season" and child not in {"winter", "standard_season"}:
                    raise ValueError("Public output contains an unsafe season value.")
                if key == "scope" and child != SCOPE_LABEL:
                    raise ValueError("Public output contains an unsafe scope label.")
                if key == "status" and child not in {"available", "too_few", "not_reached"}:
                    raise ValueError("Public output contains an unsafe statistic status.")
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)
    visit(payload)


def build_public_payloads(records, pull_date, raw_row_counts):
    period_start, period_end = headline_period(pull_date)
    headline = [
        record
        for record in records
        if period_start.isoformat() <= record["initiated_date"] <= period_end.isoformat()
    ]
    observations = survival_observations(headline, pull_date)
    closed = sum(record["event"] for record in headline)
    open_rows = [record for record in records if not record["event"]]

    age_bands = {
        "0_to_7_days": 0,
        "8_to_14_days": 0,
        "15_to_30_days": 0,
        "over_30_days": 0,
    }
    open_by_district = defaultdict(
        lambda: {
            "n": 0,
            "oldest_age_days": None,
            "age_bands": {
                "0_to_7_days": 0,
                "8_to_14_days": 0,
                "15_to_30_days": 0,
                "over_30_days": 0,
            },
        }
    )
    oldest_open_age_days = None
    for record in open_rows:
        age = (pull_date - date.fromisoformat(record["initiated_date"])).days
        if oldest_open_age_days is None or age > oldest_open_age_days:
            oldest_open_age_days = age
        if age <= 7:
            band = "0_to_7_days"
        elif age <= 14:
            band = "8_to_14_days"
        elif age <= 30:
            band = "15_to_30_days"
        else:
            band = "over_30_days"
        age_bands[band] += 1
        district_backlog = open_by_district[record["district"]]
        district_backlog["n"] += 1
        district_backlog["oldest_age_days"] = max(
            age,
            district_backlog["oldest_age_days"] or 0,
        )
        district_backlog["age_bands"][band] += 1

    season_counts = {"standard_season": 0, "winter": 0}
    headline_wait_counts = defaultdict(int)
    headline_wait_counts_by_district = defaultdict(lambda: defaultdict(int))
    for record in headline:
        season_counts[season_for(date.fromisoformat(record["initiated_date"]))] += 1
        if record["event"]:
            wait_days = int(record["wait_days"])
            headline_wait_counts[wait_days] += 1
            headline_wait_counts_by_district[record["district"]][wait_days] += 1

    summary = {
        "as_of_date": pull_date.isoformat(),
        "headline_period": {
            "start": period_start.isoformat(),
            "end": period_end.isoformat(),
            "label": "last 12 complete calendar months",
        },
        "population": {
            "n": len(headline),
            "closed": closed,
            "open_censored": len(headline) - closed,
        },
        "wait_until_request_closed": {
            "method": "Kaplan-Meier estimator",
            "median": _reported_metric(observations, 0.5),
            "p90": _reported_metric(observations, 0.9),
        },
        "closed_wait_counts": [
            [days, count] for days, count in sorted(headline_wait_counts.items())
        ],
        "open_backlog": {
            "as_of_date": pull_date.isoformat(),
            "n": len(open_rows),
            "oldest_age_days": oldest_open_age_days,
            "age_bands": age_bands,
        },
        "season_counts": [
            {"season": season, "n": count}
            for season, count in season_counts.items()
        ],
    }

    districts = sorted(
        {record["district"] for record in records},
        key=lambda value: (value == "Unknown", int(value) if value != "Unknown" else 0),
    )
    district_rows = []
    for district in districts:
        district_records = [
            record
            for record in headline
            if record["district"] == district
        ]
        district_observations = survival_observations(district_records, pull_date)
        district_rows.append(
            {
                "district": district,
                "n": len(district_records),
                "median": _reported_metric(district_observations, 0.5),
                "p90": _reported_metric(district_observations, 0.9),
                "closed_wait_counts": [
                    [days, count]
                    for days, count in sorted(
                        headline_wait_counts_by_district[district].items()
                    )
                ],
            }
        )

    all_dates = [date.fromisoformat(record["initiated_date"]) for record in records]
    month_starts = []
    if all_dates and min(all_dates) <= pull_date:
        month = _month_start(min(all_dates))
        last_month = _month_start(pull_date)
        while month <= last_month:
            month_starts.append(month)
            month = _next_month(month)

    initiated_by_month_district = defaultdict(int)
    closed_by_month_district = defaultdict(int)
    for record in records:
        initiated_date = date.fromisoformat(record["initiated_date"])
        if initiated_date <= pull_date:
            initiated_month = _month_start(initiated_date)
            initiated_by_month_district[(initiated_month, record["district"])] += 1
        if record["closed_date"] is not None:
            closed_date = date.fromisoformat(record["closed_date"])
            if closed_date <= pull_date:
                closed_month = _month_start(closed_date)
                closed_by_month_district[(closed_month, record["district"])] += 1

    month_labels = [month.strftime("%Y-%m") for month in month_starts]
    monthly_rows = [
        [
            sum(initiated_by_month_district[(month, district)] for district in districts),
            sum(closed_by_month_district[(month, district)] for district in districts),
        ]
        for month in month_starts
    ]
    district_month_rows = [
        {
            "district": district,
            "values": [
                [
                    initiated_by_month_district[(month, district)],
                    closed_by_month_district[(month, district)],
                ]
                for month in month_starts
            ],
        }
        for district in districts
    ]
    last_month = _month_start(pull_date)
    partial_period = (
        last_month.strftime("%Y-%m")
        if pull_date < _next_month(last_month) - timedelta(days=1)
        else None
    )

    last_week_end = pull_date - timedelta(days=pull_date.weekday() + 1)
    last_week_start = last_week_end - timedelta(days=6)
    first_week_start = last_week_start - timedelta(weeks=51)
    week_starts = [
        first_week_start + timedelta(weeks=index)
        for index in range(52)
    ]
    weekly_initiated = defaultdict(int)
    weekly_closed = defaultdict(int)
    for record in records:
        initiated_date = date.fromisoformat(record["initiated_date"])
        if first_week_start <= initiated_date <= last_week_end:
            weekly_initiated[(_monday_start(initiated_date), record["district"])] += 1
        if record["closed_date"] is not None:
            closed_date = date.fromisoformat(record["closed_date"])
            if first_week_start <= closed_date <= last_week_end:
                weekly_closed[(_monday_start(closed_date), record["district"])] += 1

    weekly_rows = [
        [
            sum(weekly_initiated[(week_start, district)] for district in districts),
            sum(weekly_closed[(week_start, district)] for district in districts),
        ]
        for week_start in week_starts
    ]
    district_week_rows = [
        {
            "district": district,
            "values": [
                [
                    weekly_initiated[(week_start, district)],
                    weekly_closed[(week_start, district)],
                ]
                for week_start in week_starts
            ],
        }
        for district in districts
    ]

    open_by_district_rows = [
        {
            "district": district,
            "n": open_by_district[district]["n"],
            "oldest_age_days": open_by_district[district]["oldest_age_days"],
            "age_bands": open_by_district[district]["age_bands"],
        }
        for district in districts
    ]

    meta = {
        "pull_date": pull_date.isoformat(),
        "generated_at": datetime.now(ZoneInfo(TZ)).isoformat(timespec="seconds"),
        "definitions_version": DEFINITIONS_VERSION,
        "scope": SCOPE_LABEL,
        "raw_row_counts": raw_row_counts,
    }
    payloads = {
        "meta.json": meta,
        "summary.json": summary,
        "monthly.json": {
            "periods": month_labels,
            "all": monthly_rows,
            "districts": district_month_rows,
            "partial_period": partial_period,
        },
        "weekly.json": {
            "period": {
                "start": first_week_start.isoformat(),
                "end": last_week_end.isoformat(),
                "label": "latest 52 complete Monday-start weeks",
            },
            "weeks": [week.isoformat() for week in week_starts],
            "all": weekly_rows,
            "districts": district_week_rows,
        },
        "districts.json": {
            "period": {
                "start": period_start.isoformat(),
                "end": period_end.isoformat(),
            },
            "districts": district_rows,
            "open_backlog_by_district": open_by_district_rows,
        },
    }
    for payload in payloads.values():
        _json_safe_payload(payload)
    return payloads


def _cache_pull_dates():
    dates = {}
    for name in TABLES:
        cache = RAW_DIR / f"{name}.json"
        if not cache.is_file():
            raise FileNotFoundError(f"Expected HRM cache was not created: {cache.name}")
        dates[name] = datetime.fromtimestamp(
            cache.stat().st_mtime, ZoneInfo(TZ)
        ).date()
    return dates


def _load_frame(name, columns, refresh, progress=False):
    callback = None
    if progress:
        callback = lambda total, page: print(
            f"{name}: fetched {total:,} rows (page {page:,})"
        )
    rows = load_table(name, refresh=refresh, progress=callback)
    count = len(rows)
    frame = pd.DataFrame.from_records(rows, columns=columns)
    del rows
    gc.collect()
    return frame, count


def _pivot_custom_fields(name, key, field, value, refresh, progress=False):
    frame, count = _load_frame(name, [key, field, value], refresh, progress)
    pivot = pivot_custom_fields(frame, key, field, value)
    stats = {"raw_rows": count, "pivot_rows": len(pivot), "pivot_fields": len(pivot.columns)}
    del frame, pivot
    gc.collect()
    return stats


def _diagnostic_outlier_count(records):
    waits = [record["wait_days"] for record in records if record["event"]]
    if len(waits) < 4:
        return 0
    series = pd.Series(waits, dtype="int64")
    q1 = series.quantile(0.25)
    q3 = series.quantile(0.75)
    threshold = q3 + 1.5 * (q3 - q1)
    return int(series.gt(threshold).sum())


def _write_json_files(payloads):
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    for name, payload in payloads.items():
        target = OUTPUT_DIR / name
        temporary = target.with_suffix(".json.tmp")
        with temporary.open("w", encoding="utf-8", newline="\n") as handle:
            json.dump(
                payload,
                handle,
                ensure_ascii=False,
                allow_nan=False,
                separators=(",", ":"),
            )
            handle.write("\n")
        temporary.replace(target)
    for path in OUTPUT_DIR.glob("*.json"):
        with path.open(encoding="utf-8") as handle:
            _json_safe_payload(json.load(handle))
    total_bytes = sum(path.stat().st_size for path in OUTPUT_DIR.glob("*.json"))
    if total_bytes >= 50_000:
        raise ValueError("Generated public JSON exceeds the 50 KB target.")
    return total_bytes


def _write_reconciliation(raw_counts, details, custom_stats, outlier_count, total_bytes):
    excluded_rows = sum(details["timing_exclusions"].values())
    excluded_lines = "\n".join(
        f"| {reason.replace('_', ' ')} | {count:,} |"
        for reason, count in details["timing_exclusions"].items()
    )
    table_lines = "\n".join(
        f"| {name.replace('_', ' ')} | {count:,} |"
        for name, count in raw_counts.items()
    )
    content = f"""# Stage 3 data reconciliation

Generated from the complete local HRM cache on {datetime.now(ZoneInfo(TZ)).date().isoformat()}.
The source rows and request identifiers remain in ignored `data/raw/`; this report contains aggregates only.

## Raw source rows

| Source table | Raw rows |
| --- | ---: |
{table_lines}

## Service Request scope and timing

The locked scope is the `Street Surface Maintenance` request type after trimming surrounding source whitespace,
labelled street surface repair requests.
The raw Service Request row count reconciles as {details['rows_outside_scope']:,} outside scope plus
{details['selected_scope_rows']:,} in scope.

| Reconciliation outcome | Rows |
| --- | ---: |
| Raw Service Request rows | {details['raw_service_request_rows']:,} |
| Outside selected scope | {details['rows_outside_scope']:,} |
| Selected scope rows | {details['selected_scope_rows']:,} |
| Duplicate rows discarded | {details['duplicate_rows_excluded']:,} |
| Unique selected rows | {details['unique_scope_rows']:,} |
| Timing exclusions | {excluded_rows:,} |
| Kept for timing metrics | {details['rows_kept_for_metrics']:,} |
| Closed rows kept | {details['closed_rows_kept']:,} |
| Open/censored rows kept | {details['open_censored_rows_kept']:,} |

| Timing exclusion reason | Rows |
| --- | ---: |
{excluded_lines}

The unique selected row total equals timing exclusions plus rows kept. Open requests are kept as right-censored
observations through the cache pull date; they are not treated as zero-day closures. Closed-before-initiated
records are excluded from timing only. Closed waits above Q3 + 1.5 × IQR are retained; {outlier_count:,}
were flagged for inspection only.

## Custom Fields

| Source | Raw rows | Pivot rows | Pivot fields |
| --- | ---: | ---: | ---: |
| Service Request Custom Fields matching selected request IDs | {custom_stats['service_request_matching_rows']:,} | {custom_stats['service_request_pivot_rows']:,} | {custom_stats['service_request_pivot_fields']:,} |
| Work Order Custom Fields (unlinked, pivoted separately) | {custom_stats['work_order_raw_rows']:,} | {custom_stats['work_order_pivot_rows']:,} | {custom_stats['work_order_pivot_fields']:,} |

The Service Request Custom Fields table was cleaned and pivoted for the selected request IDs. It did not provide
matching rows in the Stage 1 scan, so it does not narrow the population. Work Order Custom Fields were pivoted
separately for reconciliation, but no reliable request-to-work-order ID link exists; they are not used to classify
or time these requests. No field values are published.

## Public output checks

The public JSON totals {total_bytes:,} bytes (target: under 50,000 bytes). It contains aggregate counts and statistics,
not addresses, coordinates, free text, or request IDs. The wait estimator is Kaplan–Meier with closed requests
as events and open requests as right-censored observations. Statistics are suppressed below n = {MINIMUM_SAMPLE}.
"""
    RECONCILIATION.write_text(content, encoding="utf-8", newline="\n")


def run_pipeline(refresh=False):
    print("Loading Service Requests...")
    requests, request_count = _load_frame(
        "service_requests",
        [
            "REQUEST_ID",
            "DESCRIPTION",
            "DATE_INITIATED",
            "DATE_CLOSED",
            "DISTRICT",
            "ObjectId",
        ],
        refresh,
        progress=refresh,
    )
    scoped_mask = requests["DESCRIPTION"].map(is_selected_request).fillna(False)
    scope_ids = set(
        _normalized_ids(requests.loc[scoped_mask, "REQUEST_ID"]).dropna().tolist()
    )

    print("Loading Service Request Custom Fields...")
    sr_custom, sr_custom_count = _load_frame(
        "sr_custom_fields",
        ["REQUESTID", "CUSTOM_FIELD_NAME", "CUSTOM_FIELD_VALUE"],
        refresh,
        progress=refresh,
    )
    sr_custom["REQUESTID"] = _normalized_ids(sr_custom["REQUESTID"])
    matching = sr_custom.loc[sr_custom["REQUESTID"].isin(scope_ids)]
    sr_pivot = pivot_custom_fields(
        matching, "REQUESTID", "CUSTOM_FIELD_NAME", "CUSTOM_FIELD_VALUE"
    )
    custom_stats = {
        "service_request_matching_rows": len(matching),
        "service_request_pivot_rows": len(sr_pivot),
        "service_request_pivot_fields": len(sr_pivot.columns),
    }
    del sr_custom, matching, sr_pivot, scope_ids
    gc.collect()

    print("Loading Work Order Custom Fields...")
    wo_custom_stats = _pivot_custom_fields(
        "wo_custom_fields",
        "WORK_ORDER_ID",
        "ISSUE_CATEGORY",
        "ISSUE_OUTCOME",
        refresh,
        progress=refresh,
    )
    custom_stats.update(
        {
            "work_order_raw_rows": wo_custom_stats["raw_rows"],
            "work_order_pivot_rows": wo_custom_stats["pivot_rows"],
            "work_order_pivot_fields": wo_custom_stats["pivot_fields"],
        }
    )

    print("Loading Work Orders...")
    work_orders, work_order_count = _load_frame(
        "work_orders", ["WORK_ORDER_ID"], refresh, progress=refresh
    )
    del work_orders
    gc.collect()

    cache_dates = _cache_pull_dates()
    pull_date = min(cache_dates.values())
    metrics, reconciliation, _ = process_requests(requests, pull_date)
    del requests
    gc.collect()

    raw_counts = {
        "service_requests": request_count,
        "work_orders": work_order_count,
        "wo_custom_fields": wo_custom_stats["raw_rows"],
        "sr_custom_fields": sr_custom_count,
    }
    payloads = build_public_payloads(metrics, pull_date, raw_counts)
    total_bytes = _write_json_files(payloads)
    _write_reconciliation(
        raw_counts,
        reconciliation,
        custom_stats,
        _diagnostic_outlier_count(metrics),
        total_bytes,
    )
    print(
        f"Pipeline complete: {reconciliation['rows_kept_for_metrics']:,} selected "
        f"requests kept for timing; public JSON {total_bytes:,} bytes."
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--refresh",
        action="store_true",
        help="Re-download all four HRM source tables before building outputs.",
    )
    args = parser.parse_args()
    run_pipeline(refresh=args.refresh)


if __name__ == "__main__":
    main()
