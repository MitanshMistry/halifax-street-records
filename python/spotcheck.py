"""Compare ten random real source rows with the pipeline's recorded wait values."""
from datetime import datetime, timezone
import gc
import random
from zoneinfo import ZoneInfo

import pandas as pd

import pipeline


SAMPLE_SIZE = 10
HALIFAX = ZoneInfo("America/Halifax")
UTC = timezone.utc
REQUEST_COLUMNS = [
    "REQUEST_ID",
    "DESCRIPTION",
    "DATE_INITIATED",
    "DATE_CLOSED",
    "DISTRICT",
    "ObjectId",
]


def _source_timestamp(value):
    milliseconds = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    if pd.isna(milliseconds):
        return None
    return datetime.fromtimestamp(float(milliseconds) / 1000, UTC)


def _utc_label(value):
    timestamp = _source_timestamp(value)
    return timestamp.strftime("%Y-%m-%d %H:%M:%S UTC") if timestamp else "no close date"


def _check_record(row, pull_date):
    source_opened = _source_timestamp(row["DATE_INITIATED"])
    source_closed = _source_timestamp(row["DATE_CLOSED"])
    expected_opened = source_opened.astimezone(HALIFAX).date()
    expected_closed = (
        source_closed.astimezone(HALIFAX).date() if source_closed else None
    )
    expected_wait = (
        (expected_closed - expected_opened).days if expected_closed else None
    )

    metrics, _, _ = pipeline.process_requests(row.to_frame().T, pull_date)
    if len(metrics) != 1:
        return None

    metric = metrics[0]
    mismatches = []
    if metric["initiated_date"] != expected_opened.isoformat():
        mismatches.append("initiated date")
    expected_closed_text = expected_closed.isoformat() if expected_closed else None
    if metric["closed_date"] != expected_closed_text:
        mismatches.append("closed date")
    if metric["wait_days"] != expected_wait:
        mismatches.append("elapsed days")
    if metric["event"] != (expected_closed is not None):
        mismatches.append("open/closed state")
    if mismatches:
        raise RuntimeError(
            "A sampled source row disagreed with the pipeline for: "
            + ", ".join(mismatches)
        )

    return {
        "source_opened": source_opened,
        "source_closed": source_closed,
        "opened_date": expected_opened,
        "closed_date": expected_closed,
        "wait_days": metric["wait_days"],
    }


def main():
    if not pipeline.RAW_DIR.joinpath("service_requests.json").is_file():
        raise FileNotFoundError(
            "Cached Service Requests are required; run the data pipeline with --refresh first."
        )

    requests, _ = pipeline._load_frame(
        "service_requests", REQUEST_COLUMNS, refresh=False
    )
    in_scope = requests.loc[
        requests["DESCRIPTION"].map(pipeline.is_selected_request).fillna(False)
    ]
    unique, _ = pipeline.deduplicate_requests(in_scope)
    del requests, in_scope
    gc.collect()

    pull_date = min(pipeline._cache_pull_dates().values())
    shuffled = unique.sample(
        frac=1, random_state=random.SystemRandom().randrange(0, 2**32)
    )
    verified = 0
    for _, row in shuffled.iterrows():
        result = _check_record(row, pull_date)
        if result is None:
            continue
        verified += 1
        closed = (
            _utc_label(row["DATE_CLOSED"])
            if result["source_closed"]
            else "no close date"
        )
        days = result["wait_days"]
        wait = (
            f'{days} day{"s" if days != 1 else ""}'
            if days is not None
            else "still open"
        )
        closed_date = (
            result["closed_date"].isoformat()
            if result["closed_date"]
            else "still open"
        )
        print(
            f"Sample {verified}: raw initiated={_utc_label(row['DATE_INITIATED'])}; "
            f"raw closed={closed}; Halifax dates="
            f"{result['opened_date'].isoformat()} to {closed_date}; "
            f"pipeline wait={wait}."
        )
        if verified == SAMPLE_SIZE:
            break

    if verified != SAMPLE_SIZE:
        raise RuntimeError(
            f"Only {verified} eligible unique rows were available for the "
            f"{SAMPLE_SIZE}-row spotcheck."
        )
    print(f"PASS: {verified} random in-scope source rows match the pipeline.")


if __name__ == "__main__":
    main()
