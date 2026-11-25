"""Scan HRM tables and write aggregate findings without exposing private fields or free text."""
import argparse
import re
from pathlib import Path

import pandas as pd

from dates import ms_to_halifax
from hrm_api import RAW_DIR, TABLES, load_table

REPORT = Path(__file__).resolve().parent.parent / "project" / "scan_report.md"
KEYWORDS = re.compile(r"pothole|surface|sinkhole|patch|asphalt", re.I)
ID_TOKEN = re.compile(r"\d{4,}")
SIZE_DEPTH = re.compile(r"size|depth|width|diameter|thickness|deep|wide|inch|cm|mm", re.I)
ID_HINT = re.compile(r"\b(?:request|work\s*order)?\s*id\b|^\d{6,}$", re.I)
MAX_LIST = 250
TEXT_COLUMNS = {
    "ASSET_GROUP",
    "ASSET_TYPE",
    "CUSTOM_FIELD_NAME",
    "CUSTOM_FIELD_VALUE",
    "DESCRIPTION",
    "DEPT_RESPONSIBILITY",
    "ISSUE_CATEGORY",
    "ISSUE_OUTCOME",
    "PRIORITY",
    "REQUEST_CATEGORY",
    "RESOLUTION",
    "STATUS",
    "STREET_CLASSIFICATION",
    "WORK_ORDER_CAUSE",
}
KNOWN_INITIATORS = {"INTERNAL", "311 ONLINE", "RESPOND"}
PRIVATE_COLUMNS = {
    "ADDRESS",
    "INITIATED_BY",
    "LATITUDE",
    "LONGITUDE",
    "REQUEST_ID",
    "REQUESTID",
    "WORK_ORDER_ID",
}
EMAIL = re.compile(r"\b[^@\s]+@[^@\s]+\.[^@\s]+\b")
URL = re.compile(r"(?:https?://|www\.)\S+", re.I)
PHONE = re.compile(r"(?<!\w)(?:\+?1[\s.-]?)?(?:\(?\d{3}\)?[\s.-]?)\d{3}[\s.-]?\d{4}(?!\w)")
POSTAL_CODE = re.compile(r"\b[ABCEGHJ-NPRSTVXY]\d[ABCEGHJ-NPRSTV-Z][ -]?\d[ABCEGHJ-NPRSTV-Z]\d\b", re.I)
ADDRESS = re.compile(
    r"\b\d{1,6}\s+[A-Za-z0-9.' -]{2,50}\s+"
    r"(?:street|st|road|rd|avenue|ave|drive|dr|lane|ln|boulevard|blvd|"
    r"court|ct|crescent|cr|highway|hwy)\b",
    re.I,
)
LOCATION_PHRASE = re.compile(r"\b(?:near|outside|in front of|beside|opposite)\b", re.I)
SIMPLE_LABEL = re.compile(r"[A-Za-z0-9][A-Za-z0-9/&()'’ ._-]{0,79}\Z")


def _text_series(series):
    return series.astype("string").fillna("").str.strip()


def _looks_sensitive(value):
    value = str(value).strip()
    return any(
        pattern.search(value)
        for pattern in (EMAIL, URL, PHONE, POSTAL_CODE, ADDRESS, LOCATION_PHRASE)
    ) or bool(re.search(r"[-+]?\d{1,3}\.\d{3,}\s*[, ]\s*[-+]?\d{1,3}\.\d{3,}", value))


def _free_text_like(series):
    values = _text_series(series)
    values = values[values.ne("")]
    if values.empty:
        return False
    unique_count = int(values.nunique())
    unique_ratio = unique_count / len(values)
    lengths = values.str.len()
    singleton_ratio = float(values.value_counts().eq(1).mean())
    sentence_ratio = float(values.str.contains(r"[.!?;\n]", regex=True).mean())
    sensitive_ratio = float(values.map(_looks_sensitive).mean())
    return (
        unique_count > MAX_LIST
        or (unique_count >= 40 and unique_ratio > 0.02)
        or float(lengths.quantile(0.9)) > 100
        or sentence_ratio > 0.03
        or sensitive_ratio > 0
        or (unique_count > 30 and singleton_ratio > 0.7)
    )


def _safe_label(value, count, text_column=False, free_text=False):
    value = str(value)
    if value in {"(missing)", "(blank)"}:
        return value
    if free_text or _looks_sensitive(value) or not SIMPLE_LABEL.fullmatch(value):
        return None
    if len(value.split()) > 10:
        return None
    if text_column and count < 3:
        return None
    return value


def counts(series, name, max_list=MAX_LIST):
    """Render distinct counts while withholding values that may be free text or sensitive."""
    values = _text_series(series).replace("", "(blank)").fillna("(missing)")
    frequencies = values.value_counts(dropna=False)
    distinct = len(frequencies)
    lines = [f"- {name}: {distinct} distinct values across {len(series)} rows"]
    if distinct > max_list:
        lines.append(f"  - Value-level counts withheld: exceeds the {max_list}-value report limit.")
        return lines

    text_column = name.upper() in TEXT_COLUMNS
    free_text = text_column and _free_text_like(series)
    withheld = 0
    ordered = sorted(frequencies.items(), key=lambda item: (-int(item[1]), str(item[0]).casefold()))
    for index, (value, count_value) in enumerate(ordered, start=1):
        label = _safe_label(value, int(count_value), text_column=text_column, free_text=free_text)
        if label is None:
            label = f"[withheld value {index:03d}]"
            withheld += 1
        lines.append(f"  - {label}: {int(count_value)}")
    if withheld:
        lines.append(f"  - {withheld} value label(s) withheld for privacy.")
    if free_text:
        lines.append("  - Field looks free-text-like; all value labels are withheld.")
    return lines


def _safe_distinct_values(series):
    values = _text_series(series)
    values = values[values.ne("")]
    unique = sorted(values.unique(), key=str.casefold)
    output = []
    for index, value in enumerate(unique, start=1):
        label = _safe_label(value, 3)
        output.append(label if label is not None else f"[withheld value {index:03d}]")
    return output


def _date_series(df, column):
    if column not in df.columns:
        return None
    return ms_to_halifax(df[column])


def _date_range_line(df, column):
    dates = _date_series(df, column)
    if dates is None:
        return f"- {column}: column not found"
    valid = dates.dropna()
    missing = int(dates.isna().sum())
    raw = df[column]
    invalid = int((raw.notna() & dates.isna()).sum())
    numeric = pd.to_numeric(raw, errors="coerce")
    nonpositive = int(numeric.le(0).sum())
    if valid.empty:
        return (
            f"- {column} (Halifax time): no valid dates; missing or invalid: {missing} "
            f"({invalid} invalid); nonpositive source timestamps: {nonpositive}"
        )
    early = int(dates.dt.year.lt(2010).sum())
    today = pd.Timestamp.now(tz=dates.dt.tz).date()
    future = int(dates.dt.date.map(lambda value: value > today if pd.notna(value) else False).sum())
    return (
        f"- {column} range (Halifax time): {valid.min().date()} to {valid.max().date()}; "
        f"missing or invalid: {missing} ({invalid} invalid); nonpositive source timestamps: {nonpositive}; "
        f"before 2010: {early}; after pull date: {future}"
    )


def _date_quality(df, opened_col, closed_col, label):
    lines = [f"### {label} date quality"]
    opened = _date_series(df, opened_col)
    closed = _date_series(df, closed_col)
    if opened is None or closed is None:
        lines.append(f"- Required date column missing: {opened_col if opened is None else closed_col}")
        return lines

    close_missing = closed.isna()
    invalid_close = df[closed_col].notna() & closed.isna()
    lines.append(f"- Open by missing close date: {int(close_missing.sum())}; closed date present: {int(closed.notna().sum())}")
    lines.append(f"- Missing or invalid close dates: {int(close_missing.sum())}; invalid nonblank dates: {int(invalid_close.sum())}")
    before = closed.notna() & opened.notna() & closed.lt(opened)
    lines.append(f"- Closed before opened: {int(before.sum())}")
    years = opened.dt.year
    grouped = pd.DataFrame(
        {
            "year": years,
            "open": close_missing,
            "closed": closed.notna(),
            "missing_close": close_missing,
        }
    ).dropna(subset=["year"])
    if grouped.empty:
        lines.append("- By year opened: no valid opened dates")
    else:
        summary = grouped.groupby("year", sort=True)[["open", "closed", "missing_close"]].sum()
        lines.append("- By year opened (open / closed / missing close date):")
        lines.extend(
            f"  - {int(year)}: {int(row['open'])} / {int(row['closed'])} / {int(row['missing_close'])}"
            for year, row in summary.iterrows()
        )
    return lines


def _duplicate_id_count(df, column):
    if column not in df.columns:
        return f"- {column}: column not found"
    ids = df[column].dropna().astype(str).str.strip()
    duplicated_rows = int(ids.duplicated(keep="first").sum())
    duplicate_ids = int(ids[ids.duplicated(keep=False)].nunique())
    missing = int(df[column].isna().sum())
    return (
        f"- {column}: {duplicate_ids} IDs duplicated; {duplicated_rows} extra rows; "
        f"{missing} missing IDs"
    )


def _districts_by_year(df, table_name):
    lines = [f"- Distinct DISTRICT values per year opened ({table_name}):"]
    if "DISTRICT" not in df.columns or "DATE_INITIATED" not in df.columns:
        return lines + ["  - required field not found"]
    years = _date_series(df, "DATE_INITIATED").dt.year
    districts = _text_series(df["DISTRICT"]).replace("", "(blank)")
    for year in sorted(years.dropna().unique()):
        group = districts[years.eq(year)]
        values = _safe_distinct_values(group)
        lines.append(f"  - {int(year)}: {len(group.unique())} distinct — {', '.join(values)}")
    return lines


def _initiator_summary(sr):
    lines = ["- INITIATED_BY category check:"]
    if "INITIATED_BY" not in sr.columns:
        return lines + ["  - column not found"]
    values = _text_series(sr["INITIATED_BY"])
    nonblank = values[values.ne("")]
    normalized = nonblank.str.upper()
    observed = set(normalized.unique())
    unexpected = observed - KNOWN_INITIATORS
    lines.append(f"  - distinct nonblank values: {len(observed)}")
    lines.append(f"  - only known category labels (INTERNAL / 311 ONLINE / RESPOND): {'yes' if not unexpected else 'no'}")
    for category in sorted(observed & KNOWN_INITIATORS):
        lines.append(f"  - {category}: {int(normalized.eq(category).sum())}")
    if unexpected:
        lines.append(f"  - {len(unexpected)} unexpected value(s) withheld for privacy.")
    return lines


def _work_order_link_test(sr, wo):
    lines = ["### Request-to-work-order link test"]
    if "WORK_ORDER" not in sr.columns:
        return lines + ["- Service Requests has no WORK_ORDER column."]
    lines.extend(counts(sr["WORK_ORDER"], "WORK_ORDER"))
    values = _text_series(sr["WORK_ORDER"])
    nonblank = values.ne("")
    not_n = nonblank & values.str.upper().ne("N")
    lines.append(f"- Requests with a nonblank WORK_ORDER value other than N: {int(not_n.sum())}")
    lines.append(f"- Requests with blank WORK_ORDER: {int((~nonblank).sum())}")

    token_rows = {}
    for row_index, value in values[nonblank].items():
        tokens = set(ID_TOKEN.findall(value))
        if tokens:
            token_rows[row_index] = tokens
    tokens = {token for row_tokens in token_rows.values() for token in row_tokens}
    lines.append(f"- Requests with an ID-like numeric token: {len(token_rows)}")
    lines.append(f"- Distinct ID-like tokens in request rows: {len(tokens)}")

    if "WORK_ORDER_ID" not in wo.columns:
        lines.append("- Work Orders has no WORK_ORDER_ID column; matching not possible.")
        return lines
    wo_ids = {
        str(value).strip().removesuffix(".0")
        for value in wo["WORK_ORDER_ID"].dropna().unique()
    }
    matches = tokens & wo_ids
    matching_rows = sum(bool(row_tokens & wo_ids) for row_tokens in token_rows.values())
    lines.append(f"- Distinct work order IDs found in request values: {len(matches)}")
    lines.append(f"- Request rows containing a work order ID match: {matching_rows}")
    return lines


def _request_custom_link_test(custom, wo):
    lines = ["### Service Request Custom Fields work-order link test"]
    required = {"CUSTOM_FIELD_NAME", "CUSTOM_FIELD_VALUE"}
    if not required.issubset(custom.columns) or "WORK_ORDER_ID" not in wo.columns:
        return lines + ["- Required custom-field or work-order ID column not found."]

    field_names = _text_series(custom["CUSTOM_FIELD_NAME"])
    candidate = field_names.str.contains(
        r"work.?order|repair.*(?:id|number)|\b(?:link|reference)\b",
        case=False,
        regex=True,
        na=False,
    )
    values = _text_series(custom.loc[candidate, "CUSTOM_FIELD_VALUE"])
    wo_ids = {
        str(value).strip().removesuffix(".0")
        for value in wo["WORK_ORDER_ID"].dropna().unique()
    }
    token_rows = 0
    tokens = set()
    matched_rows = 0
    matched_ids = set()
    for value in values:
        row_tokens = set(ID_TOKEN.findall(value))
        if row_tokens:
            token_rows += 1
            tokens.update(row_tokens)
            matches = row_tokens & wo_ids
            if matches:
                matched_rows += 1
                matched_ids.update(matches)

    lines.append(f"- Rows in reference-like custom fields: {int(candidate.sum())}")
    lines.append(f"- Rows with an ID-like numeric token: {token_rows}")
    lines.append(f"- Distinct ID-like tokens: {len(tokens)}")
    lines.append(f"- Work order IDs matched: {len(matched_ids)} across {matched_rows} rows")
    return lines


def _qualification_gate(sr):
    lines = ["## Request-type qualification gate", "- Threshold: at least 300 requests across at least 2 calendar years."]
    if "DATE_INITIATED" not in sr.columns:
        return lines + ["- Cannot evaluate: DATE_INITIATED is missing."]

    years = _date_series(sr, "DATE_INITIATED").dt.year
    qualifying = []
    for column in ("DESCRIPTION", "REQUEST_CATEGORY"):
        if column not in sr.columns:
            lines.append(f"- {column}: column not found")
            continue
        values = _text_series(sr[column]).replace("", pd.NA)
        valid = values.notna() & years.notna()
        grouped = pd.DataFrame({"value": values[valid], "year": years[valid]}).groupby("value", sort=False)
        candidates = []
        for value, group in grouped:
            row_count = len(group)
            year_count = int(group["year"].nunique())
            if row_count >= 300 and year_count >= 2:
                candidates.append((value, row_count, year_count))
        candidates.sort(key=lambda item: (-item[1], item[0].casefold()))
        lines.append(f"- {column}: {len(candidates)} qualifying value(s)")
        for index, (value, row_count, year_count) in enumerate(candidates, start=1):
            label = _safe_label(value, row_count, text_column=True)
            if label is None:
                label = f"[withheld qualifying value {index:03d}]"
            lines.append(f"  - {label}: {row_count} requests across {year_count} calendar years")
            qualifying.append((column, value, row_count, year_count))

    pothole_types = [item for item in qualifying if "pothole" in item[1].casefold()]
    if pothole_types:
        selected = max(pothole_types, key=lambda item: item[2])
        selected_label = _safe_label(selected[1], selected[2], text_column=True)
        outcome = f"A — pothole-labelled request type qualifies: {selected_label or '[withheld qualifying value]'}"
    else:
        surface_types = [
            item for item in qualifying
            if item[0] == "DESCRIPTION" and "street surface" in item[1].casefold()
        ]
        if surface_types:
            selected = max(surface_types, key=lambda item: item[2])
            selected_label = _safe_label(selected[1], selected[2], text_column=True)
            outcome = (
                "B — no pothole-labelled request type qualifies; use "
                f"{selected_label or '[withheld qualifying value]'} and label it street surface repair requests."
            )
        else:
            defect_types = [
                item for item in qualifying
                if item[0] == "DESCRIPTION"
                and re.search(r"road|street|sidewalk|curb|pavement", item[1], re.I)
            ]
            if defect_types:
                selected = max(defect_types, key=lambda item: item[2])
                selected_label = _safe_label(selected[1], selected[2], text_column=True)
                outcome = (
                    "C — no qualifying pothole or street-surface type; use the largest qualifying "
                    f"road/sidewalk defect: {selected_label or '[withheld qualifying value]'}."
                )
            else:
                outcome = "C — no qualifying pothole or road/sidewalk defect type was found."
    lines.append(f"- Stage 1 outcome: {outcome}")
    return lines


def _normalized_id_series(series):
    return series.astype("string").str.strip().str.replace(r"\.0$", "", regex=True)


def _selected_type_custom_field_scan(sr, sr_custom, selected_description):
    lines = ["## Selected request type: custom-field validation"]
    required_requests = {"REQUEST_ID", "DESCRIPTION", "DATE_INITIATED"}
    required_custom = {"REQUESTID", "CUSTOM_FIELD_NAME", "CUSTOM_FIELD_VALUE"}
    if not required_requests.issubset(sr.columns) or not required_custom.issubset(sr_custom.columns):
        return lines + ["- Cannot join selected requests to custom fields: a required column is missing."]

    descriptions = _text_series(sr["DESCRIPTION"])
    selected = descriptions.eq(selected_description)
    target_ids = _normalized_id_series(sr.loc[selected, "REQUEST_ID"]).dropna()
    target_id_set = set(target_ids[target_ids.ne("")])
    linked_ids = _normalized_id_series(sr_custom["REQUESTID"])
    target_custom = sr_custom.loc[linked_ids.isin(target_id_set)].copy()

    lines.append(f"- Selected description: {selected_description}")
    lines.append(f"- Selected request rows: {int(selected.sum())}; distinct request IDs: {len(target_id_set)}")
    lines.append(f"- Matching custom-field rows: {len(target_custom)}")
    if target_custom.empty:
        lines.append("- No matching custom-field rows; size/depth or pothole narrowing cannot be tested.")
        return lines

    names = _text_series(target_custom["CUSTOM_FIELD_NAME"])
    values = _text_series(target_custom["CUSTOM_FIELD_VALUE"])
    size_depth_fields = names.str.contains(SIZE_DEPTH, na=False)
    lines.append(
        f"- Custom-field rows with size/depth-related field names: {int(size_depth_fields.sum())}; "
        f"distinct field names: {int(names[size_depth_fields].nunique())}"
    )
    for term in ("pothole", "surface", "sinkhole", "patch", "asphalt"):
        matching_values = values.str.contains(re.escape(term), case=False, na=False)
        if matching_values.any():
            lines.append(
                f"- Custom-field values containing {term}: {int(matching_values.sum())} rows; "
                f"{int(values[matching_values].nunique())} distinct values"
            )
        else:
            lines.append(f"- Custom-field values containing {term}: 0")

    pothole_values = values.str.contains("pothole", case=False, na=False)
    if not pothole_values.any():
        lines.append("- Custom-field pothole narrowing: no selected requests have a value mentioning potholes.")
        return lines

    matching_ids = set(linked_ids.loc[target_custom.index[pothole_values]].dropna())
    target_years = _date_series(sr, "DATE_INITIATED").dt.year
    narrowed = selected & _normalized_id_series(sr["REQUEST_ID"]).isin(matching_ids)
    narrowed_years = target_years[narrowed].dropna()
    narrowed_rows = int(narrowed.sum())
    narrowed_year_count = int(narrowed_years.nunique())
    qualifies = narrowed_rows >= 300 and narrowed_year_count >= 2
    lines.append(
        f"- Requests remaining after custom-field pothole filter: {narrowed_rows} across "
        f"{narrowed_year_count} calendar years; qualifies: {'yes' if qualifies else 'no'}"
    )
    return lines


def _measure_and_id_signals(df, name_column, value_column):
    lines = ["- Size/depth and ID pattern scan (counts only):"]
    if name_column in df.columns:
        names = _text_series(df[name_column])
        lines.append(f"  - field-name/category values matching size/depth terms: {int(names.str.contains(SIZE_DEPTH, na=False).sum())}")
        lines.append(f"  - field-name/category values mentioning ID: {int(names.str.contains(ID_HINT, na=False).sum())}")
    else:
        lines.append(f"  - {name_column}: column not found")
    if value_column in df.columns:
        values = _text_series(df[value_column])
        lines.append(f"  - values matching size/depth terms: {int(values.str.contains(SIZE_DEPTH, na=False).sum())}")
        lines.append(f"  - values matching ID-like patterns: {int(values.str.contains(ID_HINT, na=False).sum())}")
    else:
        lines.append(f"  - {value_column}: column not found")
    return lines


def keyword_hits(table_name, df):
    lines = [f"### {table_name}: keyword matches"]
    for column in df.select_dtypes(include=["object", "string"]).columns:
        normalized = column.upper()
        if normalized in PRIVATE_COLUMNS or normalized.endswith("_ID") or "ADDRESS" in normalized:
            continue
        values = _text_series(df[column])
        matches = values[values.str.contains(KEYWORDS, na=False)]
        if matches.empty:
            continue
        frequencies = matches.value_counts()
        lines.append(
            f"- {column}: {len(matches)} matching rows; {len(frequencies)} distinct matching value(s)"
        )
        if len(frequencies) <= 100:
            free_text = _free_text_like(df[column])
            for index, (value, count_value) in enumerate(frequencies.items(), start=1):
                label = _safe_label(
                    value,
                    int(count_value),
                    text_column=True,
                    free_text=free_text,
                )
                if label is None:
                    label = f"[withheld value {index:03d}]"
                lines.append(f"  - {label}: {int(count_value)}")
        else:
            lines.append("  - Matching labels withheld because the field has high cardinality.")
    if len(lines) == 1:
        lines.append("- No matches found in non-private text fields.")
    return lines


def keyword_term_counts(frames):
    lines = ["- Per-term keyword row counts (counts may overlap):"]
    terms = ("pothole", "surface", "sinkhole", "patch", "asphalt")
    for table_name, df in frames.items():
        for column in df.select_dtypes(include=["object", "string"]).columns:
            normalized = column.upper()
            if normalized in PRIVATE_COLUMNS or normalized.endswith("_ID") or "ADDRESS" in normalized:
                continue
            values = _text_series(df[column])
            for term in terms:
                matches = values.str.contains(re.escape(term), case=False, na=False)
                rows = int(matches.sum())
                if rows:
                    distinct = int(values[matches].nunique())
                    lines.append(f"  - {table_name}.{column} / {term}: {rows} rows; {distinct} distinct value(s)")
    if len(lines) == 1:
        lines.append("  - No keyword matches found in non-private text fields.")
    return lines


def scan_requests(sr, wo):
    lines = ["## Service Requests", f"- rows: {len(sr)}"]
    for column in ("DESCRIPTION", "REQUEST_CATEGORY", "PRIORITY", "STATUS", "DEPT_RESPONSIBILITY"):
        if column in sr.columns:
            lines.extend(counts(sr[column], column))
        else:
            lines.append(f"- {column}: column not found")

    lines.extend(["", "### Dates (converted to Halifax time)"])
    lines.extend(_date_range_line(sr, column) for column in ("DATE_INITIATED", "DATE_CLOSED"))
    lines.extend(["", *_date_quality(sr, "DATE_INITIATED", "DATE_CLOSED", "Service Requests")])
    lines.extend(["", _duplicate_id_count(sr, "REQUEST_ID")])
    lines.extend(["", *_work_order_link_test(sr, wo)])
    return lines


def scan_requests_with_custom_fields(sr, wo, sr_custom):
    lines = scan_requests(sr, wo)
    lines.extend(["", *_request_custom_link_test(sr_custom, wo)])
    lines.extend(["", *_districts_by_year(sr, "Service Requests")])
    lines.extend(["", *_initiator_summary(sr)])
    return lines


def scan_work_orders(wo):
    lines = ["## Work Orders", f"- rows: {len(wo)}"]
    for column in ("ASSET_TYPE", "ASSET_GROUP", "DESCRIPTION", "PRIORITY", "STATUS", "STREET_CLASSIFICATION"):
        if column in wo.columns:
            lines.extend(counts(wo[column], column))
        else:
            lines.append(f"- {column}: column not found")
    lines.extend(["", "### Dates (converted to Halifax time)"])
    lines.extend(
        _date_range_line(wo, column)
        for column in ("DATE_INITIATED", "ACTUAL_START_DATE", "ACTUAL_FINISH_DATE")
    )
    if "WORK_ORDER_ID" in wo.columns and "DATE_INITIATED" in wo.columns and "ACTUAL_FINISH_DATE" in wo.columns:
        opened = _date_series(wo, "DATE_INITIATED")
        finished = _date_series(wo, "ACTUAL_FINISH_DATE")
        before = finished.notna() & opened.notna() & finished.lt(opened)
        lines.append(f"- ACTUAL_FINISH_DATE before DATE_INITIATED: {int(before.sum())}")
    lines.extend(["", *_districts_by_year(wo, "Work Orders")])
    lines.extend(["", _duplicate_id_count(wo, "WORK_ORDER_ID")])
    return lines


def scan_custom(name, df, category_column, value_column):
    lines = [f"## {name}", f"- rows: {len(df)}"]
    if category_column in df.columns:
        lines.extend(counts(df[category_column], category_column))
    else:
        lines.append(f"- {category_column}: column not found")
    if value_column in df.columns:
        values = _text_series(df[value_column])
        lines.append(f"- {value_column}: {int(values.ne('').sum())} nonblank values")
        lines.extend(_measure_and_id_signals(df, category_column, value_column))
    else:
        lines.append(f"- {value_column}: column not found")
    return lines


def _load_progress(name):
    def report(rows, pages):
        print(f"  {name}: downloaded {rows:,} rows in {pages:,} page(s)", flush=True)

    return report


def main(refresh=False):
    frames = {}
    for name in TABLES:
        cache = RAW_DIR / f"{name}.json"
        action = "refreshing" if refresh else ("using cache" if cache.exists() else "downloading")
        print(f"{action}: {name}", flush=True)
        rows = load_table(name, refresh=refresh, progress=_load_progress(name))
        frames[name] = pd.DataFrame(rows)
        print(f"  {name}: {len(rows):,} rows ready", flush=True)

    sr = frames["service_requests"]
    wo = frames["work_orders"]
    wo_custom = frames["wo_custom_fields"]
    sr_custom = frames["sr_custom_fields"]
    lines = [
        "# HRM full data scan report",
        "",
        "Summary counts only. Raw source rows remain in the ignored `data/raw/` cache.",
        "Text labels that appear free-text-like or sensitive are withheld.",
        "",
        "## Table row counts",
    ]
    lines.extend(f"- {name}: {len(frame)}" for name, frame in frames.items())
    lines.extend(
        [
            "",
            *scan_requests_with_custom_fields(sr, wo, sr_custom),
            "",
            *scan_work_orders(wo),
            "",
            *scan_custom("Work Orders Custom Fields", wo_custom, "ISSUE_CATEGORY", "ISSUE_OUTCOME"),
            "",
            *scan_custom("Service Requests Custom Fields", sr_custom, "CUSTOM_FIELD_NAME", "CUSTOM_FIELD_VALUE"),
            "",
            *_qualification_gate(sr),
            "",
            *_selected_type_custom_field_scan(sr, sr_custom, "Street Surface Maintenance"),
            "",
            "## Keyword scan",
            *keyword_term_counts(frames),
        ]
    )
    for name, frame in frames.items():
        lines.extend(["", *keyword_hits(name, frame)])

    text = "\n".join(lines) + "\n"
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(text, encoding="utf-8")
    print("\n" + text)
    print(f"Wrote {REPORT}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--refresh", action="store_true", help="re-download instead of using data/raw cache")
    main(parser.parse_args().refresh)
