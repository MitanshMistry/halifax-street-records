"""Build the aggregate-only static resident site."""
import html
import json
import math
import os
import re
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"
DATA_DIR = DOCS / "data"
TEMPLATE_DIR = DOCS / "templates"
DISTRICT_CODE = re.compile(r"[0-9]+\Z")
DISTRICT_PLACES = {
    "1": "Waverley - Fall River - Musquodoboit Valley",
    "2": "Lawrencetown - The Lakes - Chezzetcook - Eastern Shore",
    "3": "Dartmouth South - Woodside - Eastern Passage",
    "4": "Cole Harbour - Preston - Westphal - Cherry Brook",
    "5": "Dartmouth Centre",
    "6": "Dartmouth East - Burnside",
    "7": "Halifax South Downtown",
    "8": "Halifax Peninsula North",
    "9": "Halifax West Armdale",
    "10": "Halifax - Bedford Basin West",
    "11": "Spryfield - Sambro Loop",
    "12": "Timberlea - Beechville - Clayton Park - Wedgewood",
    "13": "Prospect Road - St. Margarets",
    "14": "Hammonds Plains - Upper Hammonds Plains - Lucasville - Middle & Upper Sackville",
    "15": "Lower Sackville - Beaver Bank",
    "16": "Bedford - Wentworth",
}
SOURCE_LABELS = {
    "service_requests": "Service Requests",
    "work_orders": "Work Orders",
    "wo_custom_fields": "Work Orders Custom Fields",
    "sr_custom_fields": "Service Requests Custom Fields",
}
AGE_BANDS = (
    ("0 to 7 days", "0_to_7_days"),
    ("8 to 14 days", "8_to_14_days"),
    ("15 to 30 days", "15_to_30_days"),
    ("Over 30 days", "over_30_days"),
)
SVG_INK, SVG_MUTED = "#25343D", "#65737C"
SVG_GRID, SVG_ACCENT = "#DCE3E5", "#005A78"
SVG_PALE, SVG_HATCH = "#E8F0F2", "#A5B2B7"


def _escape(value):
    return html.escape(str(value), quote=True)


def _number(value):
    return f"{int(value):,}"


def _district_label(code):
    if code == "all":
        return "All of HRM"
    if code == "Unknown":
        return "District not recorded — place unknown"
    if not isinstance(code, str) or not DISTRICT_CODE.fullmatch(code):
        raise ValueError("District must be a numeric source district code.")
    if code not in DISTRICT_PLACES:
        raise ValueError(f"No verified current place label for HRM District {code}.")
    return f"District {code} — {DISTRICT_PLACES[code]}"


def _days(value):
    amount = int(value)
    return f"{amount} day" if amount == 1 else f"{amount} days"


def _date(value):
    return date.fromisoformat(value)


def _date_label(value):
    parsed = _date(value)
    return f"{parsed.day} {parsed.strftime('%B %Y')}"


def _compact_date_label(value):
    parsed = _date(value)
    return f"{parsed.day} {parsed.strftime('%b %Y')}"


def _short_date(value):
    parsed = _date(value)
    return f"{parsed.strftime('%b')} {parsed.day}"


def _month_label(value):
    return datetime.strptime(value, "%Y-%m").strftime("%B %Y")


def _metric_text(metric, label):
    if metric.get("lower_bound_days") is not None:
        return f"{label} more than {_days(metric['lower_bound_days'])}"
    if metric.get("status") == "too_few":
        return f"{label} not estimated (too few reports)"
    return f"{label} cannot be estimated from these reports"


def _metric_table_text(metric):
    if metric.get("status") == "available" and metric.get("days") is not None:
        return _days(metric["days"])
    if metric.get("lower_bound_days") is not None:
        return f"More than {_days(metric['lower_bound_days'])}"
    if metric.get("status") == "too_few":
        return "Too few reports to estimate"
    return "Cannot estimate"


def _district_rows(data):
    return sorted(
        data["districts"]["districts"],
        key=lambda row: (
            row["district"] == "Unknown",
            int(row["district"]) if DISTRICT_CODE.fullmatch(row["district"]) else 0,
        ),
    )


def _district_row(data, selected):
    for row in _district_rows(data):
        if row["district"] == selected:
            return row
    raise ValueError("District must be a numeric source district code.")


def _backlog_row(data, selected):
    if selected == "all":
        return data["summary"]["open_backlog"]
    for row in data["districts"]["open_backlog_by_district"]:
        if row["district"] == selected:
            return {**row, "as_of_date": row.get("as_of_date", data["summary"]["as_of_date"])}
    return {
        "as_of_date": data["summary"]["as_of_date"],
        "n": 0,
        "oldest_age_days": None,
        "age_bands": {key: 0 for _, key in AGE_BANDS},
    }


def _values_for_district(section, selected):
    if selected == "all":
        return section["all"]
    for row in section["districts"]:
        if row["district"] == selected:
            return row["values"]
    return [[0, 0] for _ in section.get("periods", section.get("weeks", []))]


def _district_open_n(row):
    closed_n = sum(int(count) for _, count in row["closed_wait_counts"])
    open_n = int(row["n"]) - closed_n
    if open_n < 0:
        raise ValueError(
            f"{_district_label(row['district'])} aggregate counts do not reconcile."
        )
    return open_n


def _svg_ticks(maximum, count=4):
    if maximum <= count:
        return list(range(0, max(1, maximum) + 1))
    raw_step = max(1, maximum) / count
    magnitude = 10 ** math.floor(math.log10(raw_step))
    normalized = raw_step / magnitude
    step = magnitude if normalized <= 1 else 2 * magnitude if normalized <= 2 else 5 * magnitude if normalized <= 5 else 10 * magnitude
    step = max(1, int(round(step)))
    top = max(step, math.ceil(max(1, maximum) / step) * step)
    return list(range(0, int(top) + 1, step))


def _peak_label(period, amount):
    label = _month_label(period) if re.fullmatch(r"\d{4}-\d{2}", period) else _date_label(period)
    return f"{_number(amount)} · {label}"


def render_monthly_svg(periods, values, partial_period=None, mobile=False):
    """Render initiated-request counts with winter and partial-month cues."""
    rows = list(zip(periods, values))
    width, height = (360 if mobile else 1080), 360
    left, right, top, bottom = 43, 14, 34, 112
    plot_width, plot_height = width - left - right, height - top - bottom
    counts = [int(value[0]) for _, value in rows]
    ticks = _svg_ticks(max(counts, default=0))
    scale_top = ticks[-1]
    peak_index = max(range(len(rows)), key=lambda index: counts[index]) if rows else None
    cell_width = plot_width / max(1, len(rows))
    bar_width = max(2, cell_width * 0.62)
    pieces = [
        f'<svg class="chart-svg chart-svg--{"phone" if mobile else "wide"}" viewBox="0 0 {width} {height}" role="img" aria-labelledby="monthly-title monthly-desc">',
        '<title id="monthly-title">Reports HRM received each month</title>',
        '<desc id="monthly-desc">Monthly counts of reports about street-surface problems. Shading marks winter; stripes mark a partial month.</desc>',
        f'<defs><pattern id="partial-month" width="7" height="7" patternUnits="userSpaceOnUse" patternTransform="rotate(45)"><rect width="7" height="7" fill="{SVG_PALE}"/><line x1="0" y1="0" x2="0" y2="7" stroke="{SVG_HATCH}" stroke-width="2"/></pattern></defs>',
        f'<text class="chart-note" x="{left}" y="16">Winter shading: December to March</text>',
    ]
    if not rows:
        return "".join(pieces + [f'<text x="{left}" y="{top + 22}">No monthly reports to show.</text>', "</svg>"])

    for index, (period, _) in enumerate(rows):
        if int(period[-2:]) in (12, 1, 2, 3):
            x = left + index * cell_width
            pieces.append(f'<rect class="winter-band" x="{x:.2f}" y="{top}" width="{cell_width + 0.5:.2f}" height="{plot_height}" fill="{SVG_PALE}"/>')
    for tick in ticks:
        y = top + plot_height - tick / scale_top * plot_height
        pieces.extend((
            f'<line x1="{left}" y1="{y:.2f}" x2="{width - right}" y2="{y:.2f}" stroke="{SVG_GRID}"/>',
            f'<text class="axis-label" x="{left - 7}" y="{y + 4:.2f}" text-anchor="end">{_number(tick)}</text>',
        ))
    for index, (period, _) in enumerate(rows):
        count = counts[index]
        x = left + index * cell_width + (cell_width - bar_width) / 2
        bar_height = count / scale_top * plot_height
        y = top + plot_height - bar_height
        fill = "url(#partial-month)" if period == partial_period else SVG_ACCENT
        partial_label = " (partial month)" if period == partial_period else ""
        pieces.append(
            f'<rect x="{x:.2f}" y="{y:.2f}" width="{bar_width:.2f}" height="{bar_height:.2f}" fill="{fill}" '
            f'stroke="{SVG_ACCENT}" stroke-width="{1 if period == partial_period else 0}"><title>'
            f'{_escape(_month_label(period))}: {_number(count)} reports recorded{partial_label}</title></rect>'
        )
        if (mobile and (index == 0 or period.endswith("-01"))) or (not mobile and index % 3 == 0):
            label_x, label_y = x + bar_width / 2, top + plot_height + 52
            month_name = datetime.strptime(period, "%Y-%m").strftime("%b")
            pieces.append(f'<text class="month-label" x="{label_x:.2f}" y="{label_y}" transform="rotate(-90 {label_x:.2f} {label_y})" text-anchor="end">{month_name}</text>')
        if period.endswith("-01"):
            pieces.append(f'<text class="year-label" x="{x + bar_width / 2:.2f}" y="{height - 13}" text-anchor="middle">{period[:4]}</text>')
    if peak_index is not None:
        period, _ = rows[peak_index]
        peak_x = left + peak_index * cell_width + cell_width / 2
        peak_y = max(top + 12, top + plot_height - counts[peak_index] / scale_top * plot_height - 7)
        pieces.append(f'<text class="peak-label" x="{peak_x:.2f}" y="{peak_y:.2f}" text-anchor="middle">{_escape(_peak_label(period, counts[peak_index]))}</text>')
    if partial_period and any(period == partial_period for period, _ in rows):
        pieces.append(f'<text class="chart-note" x="{width - right}" y="{height - 4}" text-anchor="end">Striped bar: partial month</text>')
    pieces.extend((
        f'<text class="axis-title" transform="translate(13 {top + plot_height / 2:.2f}) rotate(-90)" text-anchor="middle">Reports per month</text>',
        "</svg>",
    ))
    return "".join(pieces)


def render_weekly_svg(weeks, values, mobile=False):
    """Render initiated-request counts for complete Monday-start weeks."""
    rows = list(zip(weeks, values))
    width, height = (360 if mobile else 1080), 310
    left, right, top, bottom = 44, 14, 34, 45
    plot_width, plot_height = width - left - right, height - top - bottom
    counts = [int(value[0]) for _, value in rows]
    ticks = _svg_ticks(max(counts, default=0))
    scale_top = ticks[-1]
    pieces = [
        f'<svg class="chart-svg chart-svg--{"phone" if mobile else "wide"}" viewBox="0 0 {width} {height}" role="img" aria-labelledby="weekly-title weekly-desc">',
        '<title id="weekly-title">Reports HRM received each week</title>',
        '<desc id="weekly-desc">Reports about street-surface problems recorded in each full Monday-to-Sunday week.</desc>',
    ]
    if not rows:
        return "".join(pieces + [f'<text x="{left}" y="{top + 22}">No weekly reports to show.</text>', "</svg>"])
    for tick in ticks:
        y = top + plot_height - tick / scale_top * plot_height
        pieces.extend((
            f'<line x1="{left}" y1="{y:.2f}" x2="{width - right}" y2="{y:.2f}" stroke="{SVG_GRID}"/>',
            f'<text class="axis-label" x="{left - 7}" y="{y + 4:.2f}" text-anchor="end">{_number(tick)}</text>',
        ))
    coords = []
    for index, (week, _) in enumerate(rows):
        x = left + index * plot_width / max(1, len(rows) - 1)
        y = top + plot_height - counts[index] / scale_top * plot_height
        coords.append((x, y))
        if index == 0 or index % (13 if mobile else 6) == 0:
            pieces.append(f'<text class="week-label" x="{x:.2f}" y="{height - 14}" text-anchor="middle">{_escape(_short_date(week))}</text>')
    points = " ".join(f"{x:.2f},{y:.2f}" for x, y in coords)
    pieces.append(f'<polyline points="{points}" fill="none" stroke="{SVG_ACCENT}" stroke-width="2.5" stroke-linejoin="round" stroke-linecap="round"/>')
    peak_index = max(range(len(rows)), key=lambda index: counts[index])
    peak_x, peak_y = coords[peak_index]
    peak_label = f"{_number(counts[peak_index])} · week of {_short_date(rows[peak_index][0])}"
    pieces.append(f'<circle cx="{peak_x:.2f}" cy="{peak_y:.2f}" r="5" fill="{SVG_ACCENT}"><title>{_escape(peak_label)}</title></circle>')
    pieces.append(f'<text class="peak-label" x="{peak_x:.2f}" y="{max(top + 12, peak_y - 10):.2f}" text-anchor="middle">{_escape(peak_label)}</text>')
    pieces.extend((
        f'<text class="axis-title" transform="translate(13 {top + plot_height / 2:.2f}) rotate(-90)" text-anchor="middle">Reports per week</text>',
        "</svg>",
    ))
    return "".join(pieces)


def _render_range_svg(median, p90, n):
    values = (int(median["days"]), int(p90["days"]))
    maximum = max(1, math.ceil(max(values) * 1.15))
    left, right, width, axis_y = 32, 32, 520, 54
    axis_width = width - left - right
    positions = [left + value / maximum * axis_width for value in values]
    ticks = sorted(set((0, maximum // 2, maximum)))
    output = [
        '<svg class="range-svg" viewBox="0 0 520 116" role="img" aria-labelledby="range-title range-description">',
        '<title id="range-title">Estimated time until HRM records a report as closed</title>',
        f'<desc id="range-description">Estimated time for about half of reports to have a close date: {_days(values[0])}; for 9 in 10 reports: {_days(values[1])}. Based on {n:,} reports.</desc>',
        f'<line x1="{left}" y1="{axis_y}" x2="{width - right}" y2="{axis_y}" stroke="{SVG_GRID}" stroke-width="8" stroke-linecap="round"/>',
    ]
    output.append(
        f'<line x1="{positions[0]:.2f}" y1="{axis_y}" x2="{positions[1]:.2f}" y2="{axis_y}" stroke="{SVG_ACCENT}" stroke-width="8" stroke-linecap="round"/>'
    )
    for index, (position, label) in enumerate(zip(positions, ("Half", "9 in 10"))):
        output.append(
            f'<circle cx="{position:.2f}" cy="{axis_y}" r="9" fill="{SVG_ACCENT}" stroke="#FFFFFF" stroke-width="3">'
            f'<title>{label}: {_days(values[index])}</title></circle>'
        )
        output.append(
            f'<text class="range-direct-label" x="{position:.2f}" y="{25 if index == 0 else 45}" text-anchor="middle">'
            f'{label}: {_days(values[index])}</text>'
        )
    for value in ticks:
        x = left + value / maximum * axis_width
        output.extend((
            f'<line x1="{x:.2f}" y1="67" x2="{x:.2f}" y2="73" stroke="{SVG_MUTED}"/>',
            f'<text class="axis-label" x="{x:.2f}" y="91" text-anchor="middle">{value} days</text>',
        ))
    output.append("</svg>")
    return "".join(output)


def _answer_card(data, selected, base_path):
    summary = data["summary"]
    chosen = _district_row(data, selected) if selected != "all" else None
    selected_n = chosen["n"] if chosen else summary["population"]["n"]
    too_few = chosen is not None and selected_n < 30
    if too_few:
        metrics = summary["wait_until_request_closed"]
        n = summary["population"]["n"]
        open_n = summary["population"]["open_censored"]
        title = "All of HRM"
        fallback_note = (
            f'<p class="sample-fallback">{_escape(_district_label(selected))} has {_number(selected_n)} reports, fewer than the 30 needed to estimate a time. '
            'Showing All of HRM instead.</p>'
        )
    elif chosen:
        metrics = {"median": chosen["median"], "p90": chosen["p90"]}
        n = chosen["n"]
        open_n = _district_open_n(chosen)
        title = _district_label(selected)
        fallback_note = ""
    else:
        metrics = summary["wait_until_request_closed"]
        n = summary["population"]["n"]
        open_n = summary["population"]["open_censored"]
        title = "All of HRM"
        fallback_note = ""

    median, p90 = metrics["median"], metrics["p90"]
    median_ok = median.get("status") == "available" and median.get("days") is not None
    p90_ok = p90.get("status") == "available" and p90.get("days") is not None
    period = summary["headline_period"]
    median_sentence = _days(median["days"]) if median_ok else _metric_text(
        median, "Typical time to close date:"
    )
    p90_sentence = (
        f"For 9 in 10 reports, HRM recorded a close date within {_days(p90['days'])}."
        if p90_ok else _metric_text(p90, "Time for 9 in 10 reports:")
    )
    range_svg = (
        _render_range_svg(median, p90, n)
        if median_ok and p90_ok
        else '<p class="range-unavailable">The time estimates are not available, so this chart is hidden.</p>'
    )
    range_table = (
        '<details class="data-table-details"><summary>View the estimate details</summary>'
        '<div class="table-scroll"><table><caption>Estimated time until HRM recorded a close date</caption>'
        '<thead><tr><th scope="col">Share of reports</th><th scope="col">Time to close date</th>'
        '<th scope="col" class="numeric">Reports used</th></tr></thead><tbody>'
        f'<tr><th scope="row">About half</th><td>{_escape(_metric_table_text(median))}</td><td class="numeric">{_number(n)}</td></tr>'
        f'<tr><th scope="row">About 9 in 10</th><td>{_escape(_metric_table_text(p90))}</td><td class="numeric">{_number(n)}</td></tr>'
        '</tbody></table></div></details>'
    )
    backlog = _backlog_row(data, selected)
    oldest = (
        f' The oldest report without a close date was started {_days(backlog["oldest_age_days"])} ago.'
        if backlog.get("oldest_age_days") is not None else ""
    )
    heading = "How long have HRM’s past reports taken to close?"
    compare_href = (
        f'{base_path}index.html#districts'
        if selected == "all"
        else f'{base_path}index.html?district=all#districts'
    )
    content = (
        '<article class="answer-card" aria-labelledby="answer-heading">'
        f'<p class="eyebrow">Estimate from past reports · {_escape(title)}</p>'
        '<h2 id="answer-heading" class="answer-heading">Typically,</h2>'
        f'<p class="answer-primary">{_escape(median_sentence)}</p>'
        f'<p class="answer-secondary">{_escape(p90_sentence)}</p>'
        f'<p class="sample-line">Estimate based on {_number(n)} reports started between {_compact_date_label(period["start"])} and {_compact_date_label(period["end"])}. '
        f'{_number(open_n)} had no close date as of the HRM data download on {_compact_date_label(summary["as_of_date"])}.</p>'
        f'{fallback_note}'
        '<p class="recorded-note">HRM closing a report does not confirm the road was repaired.</p>'
        f'<div class="range-visual">{range_svg}</div>{range_table}'
        f'<p class="open-answer"><strong>{_number(backlog["n"])} HRM records</strong> across all dates in {_escape(title)} '
        f'have no close date as of {_date_label(backlog["as_of_date"])}.{oldest}</p>'
        f'<p class="compare-district-link"><a href="{_escape(compare_href)}">Compare with another district</a></p>'
        f'<span class="answer-data" hidden data-half-days="{median.get("days", "")}" data-sample-size="{n}"></span>'
        '</article>'
    )
    return {
        "html": content, "heading": heading, "median": median, "p90": p90,
        "median_available": median_ok, "p90_available": p90_ok,
        "n": n, "open_n": open_n, "backlog": backlog, "title": title,
    }


def _meaning_details(answer):
    area = answer["title"]
    if answer["median_available"] and answer["p90_available"]:
        sentence = (
            f"For {area}, “half” is the estimated time by which HRM had recorded a close date for about half of reports. "
            "“9 in 10” is the estimate for about nine in ten reports, when the data supports it. "
            "Reports without a close date are counted only up to the HRM data download date; they are not assumed closed. "
            "These past records cannot predict when your report will close."
        )
    else:
        sentence = (
            f'These estimates use {_number(answer["n"])} past reports from {area}. '
            "A time is shown only when the records support it. "
            "Reports without a close date are counted only up to the HRM data download date; they are not assumed closed."
        )
    return (
        '<details class="meaning-details"><summary>What do “half” and “9 in 10” mean?</summary>'
        f'<p id="meaning-explanation">{_escape(sentence)}</p>'
        '</details>'
    )


def _age_chart(backlog):
    labels = [label for label, _ in AGE_BANDS]
    counts = [int(backlog["age_bands"].get(key, 0)) for _, key in AGE_BANDS]
    total = max(1, sum(counts))
    cursor = 0.0
    pieces = [
        '<svg class="age-svg" viewBox="0 0 640 42" role="img" aria-labelledby="age-title age-desc">',
        '<title id="age-title">How long HRM records have had no close date</title>',
        f'<desc id="age-desc">As of {_escape(_date_label(backlog["as_of_date"]))}: '
        + "; ".join(f"{label}: {_number(count)}" for label, count in zip(labels, counts))
        + ".</desc>",
        '<defs><pattern id="age-hatch" width="7" height="7" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">'
        f'<rect width="7" height="7" fill="{SVG_PALE}"/><line x1="0" y1="0" x2="0" y2="7" stroke="{SVG_HATCH}" stroke-width="2"/>'
        '</pattern></defs>',
    ]
    for index, count in enumerate(counts):
        segment_width = 640 * count / total
        fill = "url(#age-hatch)" if index == 3 else SVG_ACCENT if index == 0 else SVG_MUTED
        pieces.append(
            f'<rect x="{cursor:.2f}" y="0" width="{segment_width:.2f}" height="42" fill="{fill}" stroke="#FFFFFF" stroke-width="2">'
            f'<title>{_escape(labels[index])}: {_number(count)} reports</title></rect>'
        )
        if segment_width >= 36:
            color = "#FFFFFF" if index == 0 else SVG_INK
            pieces.append(f'<text x="{cursor + segment_width / 2:.2f}" y="26" text-anchor="middle" fill="{color}" font-weight="700">{_number(count)}</text>')
        cursor += segment_width
    pieces.append("</svg>")
    return "".join(pieces)


def _open_section(data, selected):
    backlog = _backlog_row(data, selected)
    label = _district_label(selected)
    age_rows = "".join(
        f'<tr><th scope="row">{_escape(name)}</th><td class="numeric">{_number(backlog["age_bands"].get(key, 0))}</td></tr>'
        for name, key in AGE_BANDS
    )
    old_line = (
        f'The oldest report without a close date was started {_days(backlog["oldest_age_days"])} ago.'
        if backlog.get("oldest_age_days") is not None
        else "No HRM records without a close date were found for this area."
    )
    age_list = "".join(
        f'<li><span class="age-swatch age-swatch-{index}" aria-hidden="true"></span>{_escape(name)}: '
        f'<strong>{_number(backlog["age_bands"].get(key, 0))}</strong></li>'
        for index, (name, key) in enumerate(AGE_BANDS, 1)
    )
    return (
        '<section class="content-section open-section" id="open-records" aria-labelledby="open-heading">'
        '<p class="eyebrow">No close date recorded</p><h2 id="open-heading">HRM records without a close date</h2>'
        f'<p class="section-takeaway"><strong>{_number(backlog["n"])} records</strong> in {_escape(label)} have no close date '
        f'as of {_date_label(backlog["as_of_date"])}. {_escape(old_line)}</p>'
        '<figure class="open-chart-wrap">'
        f'{_age_chart(backlog)}<figcaption>How long ago the {_number(backlog["n"])} reports without a close date were made, as of {_date_label(backlog["as_of_date"])}.</figcaption>'
        '</figure>'
        f'<ul class="age-band-list" aria-label="Counts by time since report">{age_list}</ul>'
        '<details class="data-table-details"><summary>View counts by time since report</summary>'
        '<div class="table-scroll"><table><caption>Reports without a close date, by time since report</caption>'
        '<thead><tr><th scope="col">Time since report</th><th scope="col" class="numeric">Reports</th></tr></thead>'
        f'<tbody>{age_rows}</tbody><tfoot><tr><th scope="row">Total</th><td class="numeric">{_number(backlog["n"])}</td></tr></tfoot>'
        '</table></div></details>'
        '<p class="small-note">No close date means HRM has not recorded one. This does not tell us whether the road problem is still there.</p>'
        '</section>'
    )


def _month_table(periods, values, partial_period):
    rows = []
    for period, pair in zip(periods, values):
        partial = ' <span class="table-note">(partial month)</span>' if period == partial_period else ""
        rows.append(
            f'<tr><th scope="row">{_escape(_month_label(period))}{partial}</th>'
            f'<td class="numeric">{_number(pair[0])}</td></tr>'
        )
    return "".join(rows)


def _week_table(weeks, values):
    rows = []
    for week, pair in zip(weeks, values):
        start = _date(week)
        end = start + timedelta(days=6)
        rows.append(
            f'<tr><th scope="row">{start.day} {start.strftime("%b %Y")} to '
            f'{end.day} {end.strftime("%b %Y")}</th>'
            f'<td class="numeric">{_number(pair[0])}</td></tr>'
        )
    return "".join(rows)


def _average_label(values):
    return f"{sum(values) / len(values):,.1f}".rstrip("0").rstrip(".")


def _season_note(months, values, partial_period=None):
    if len(months) != len(values):
        raise ValueError("Monthly periods and values must have matching lengths.")
    counts_by_year = {}
    for period, pair in zip(months, values):
        month = _date(f"{period}-01")
        counts_by_year.setdefault(month.year, {})[month.month] = int(pair[0])

    partial_year = int(partial_period[:4]) if partial_period else None
    expected_months = set(range(1, 13))
    complete_years = [
        year
        for year, counts in sorted(counts_by_year.items())
        if set(counts) == expected_months and year != partial_year
    ]
    if not complete_years:
        return ""

    winter = [
        counts_by_year[year][month]
        for year in complete_years
        for month in (12, 1, 2, 3)
    ]
    standard_season = [
        counts_by_year[year][month]
        for year in complete_years
        for month in range(4, 12)
    ]
    consecutive_years = all(
        year == complete_years[0] + index
        for index, year in enumerate(complete_years)
    )
    year_label = (
        f"{complete_years[0]}–{complete_years[-1]}"
        if consecutive_years
        else ", ".join(str(year) for year in complete_years)
    )
    return (
        f'<p class="season-note">Across full years {year_label}, HRM recorded an average of '
        f'{_average_label(winter)} reports per month from December to March (based on {len(winter)} months) and '
        f'{_average_label(standard_season)} per month from April to November '
        f'(based on {len(standard_season)} months). These are report counts, not measures of road conditions or work completed by crews.</p>'
    )


def _volume_section(data, selected):
    monthly, weekly = data["monthly"], data["weekly"]
    month_values = _values_for_district(monthly, selected)
    week_values = _values_for_district(weekly, selected)
    months, weeks = monthly["periods"], weekly["weeks"]
    month_peak = max(range(len(month_values)), key=lambda i: month_values[i][0]) if month_values else None
    week_peak = max(range(len(week_values)), key=lambda i: week_values[i][0]) if week_values else None
    district_name = _district_label(selected)

    if month_peak is None:
        month_takeaway = "There are no monthly reports to show."
    else:
        month_takeaway = (
            f'HRM received the most reports in {_escape(_month_label(months[month_peak]))} '
            f'({_number(month_values[month_peak][0])} reports).'
        )
    if week_peak is None:
        week_takeaway, week_range = "There are no weekly reports to show.", "No full weeks available."
    else:
        start = _date(weeks[week_peak])
        end = _date(weeks[-1]) + timedelta(days=6)
        week_takeaway = (
            f'HRM received the most reports in the week of {_date_label(start.isoformat())} '
            f'({_number(week_values[week_peak][0])} reports).'
        )
        week_range = f'{_date_label(weeks[0])} to {_date_label(end.isoformat())}'

    partial_period = monthly.get("partial_period")
    month_range = (
        f'{_escape(_month_label(months[0]))} to {_escape(_month_label(months[-1]))}'
        if months else "No monthly periods available"
    )
    partial_note = (
        f'<p class="small-note">{_escape(_month_label(partial_period))} is counted only through '
        f'{_date_label(data["meta"]["pull_date"])}; it is shown with stripes.</p>'
        if partial_period else ""
    )
    month_table = _month_table(months, month_values, partial_period)
    week_table = _week_table(weeks, week_values)
    month_view = (
        f'<p class="section-takeaway" id="monthly-takeaway">{month_takeaway}</p>'
        f'<p class="small-note">Monthly reports for {_escape(district_name)}: {month_range}.</p>'
        f'{partial_note}<figure class="volume-chart"><div class="chart-desktop">'
        f'{render_monthly_svg(months, month_values, partial_period, mobile=False)}</div><div class="chart-mobile">'
        f'{render_monthly_svg(months, month_values, partial_period, mobile=True)}</div>'
        '<figcaption>Reports HRM received each month. Winter months are shaded; stripes mark a partial month.</figcaption></figure>'
        '<details class="data-table-details"><summary>View monthly report counts</summary>'
        '<div class="table-scroll"><table><caption>Reports recorded each month</caption>'
        '<thead><tr><th scope="col">Month</th><th scope="col" class="numeric">Reports received</th></tr></thead>'
        f'<tbody>{month_table}</tbody></table></div></details>'
    )
    week_view = (
        f'<p class="section-takeaway" id="weekly-takeaway">{week_takeaway}</p>'
        f'<p class="small-note">Weekly reports for {_escape(district_name)}: {week_range}. '
        'Only full Monday-to-Sunday weeks are included.</p>'
        f'<figure class="volume-chart"><div class="chart-desktop">{render_weekly_svg(weeks, week_values)}'
        '</div><div class="chart-mobile">'
        f'{render_weekly_svg(weeks, week_values, mobile=True)}</div>'
        '<figcaption>Reports HRM received in each full Monday-to-Sunday week.</figcaption></figure>'
        '<details class="data-table-details"><summary>View weekly report counts</summary>'
        '<div class="table-scroll"><table><caption>Reports recorded each week</caption>'
        '<thead><tr><th scope="col">Week</th><th scope="col" class="numeric">Reports received</th></tr></thead>'
        f'<tbody>{week_table}</tbody></table></div></details>'
    )
    return (
        '<section class="content-section volume-section" id="request-volume" aria-labelledby="volume-heading">'
        '<p class="eyebrow">Report counts</p><h2 id="volume-heading">When HRM received the most reports</h2>'
        '<p class="section-intro">This shows when HRM received reports about street-surface problems. It does not show when road conditions were worst.</p>'
        '<div class="trend-switch js-only" role="group" aria-label="Choose reports by month or week">'
        '<button type="button" class="trend-button is-active" data-trend="monthly" aria-pressed="true">Month</button>'
        '<button type="button" class="trend-button" data-trend="weekly" aria-pressed="false">Week</button></div>'
        f'<div class="trend-view is-active" data-trend-view="monthly">{month_view}</div>'
        f'<div class="trend-view" data-trend-view="weekly">{week_view}</div>'
        f'{_season_note(months, month_values, monthly.get("partial_period"))}</section>'
    )


def _directory_stat(metric):
    return _metric_table_text(metric)


def _district_directory(data, base_path):
    table_rows, cards = [], []
    for row in _district_rows(data):
        code = row["district"]
        numeric = bool(DISTRICT_CODE.fullmatch(code))
        name = _district_label(code)
        n = int(row["n"])
        not_enough = f"Not enough reports to estimate (count: {_number(n)})"
        half = _directory_stat(row["median"]) if n >= 30 else not_enough
        nine = _directory_stat(row["p90"]) if n >= 30 else not_enough
        backlog = _backlog_row(data, code)
        route = f"{base_path}district-{code}/" if numeric else ""
        label = f'<a href="{_escape(route)}">{_escape(name)}</a>' if route else _escape(name)
        compare = (
            f'<a class="compare-link" href="{_escape(route)}">Compare with another district</a>'
            if route else '<span class="small-note">HRM did not provide a district number</span>'
        )
        table_rows.append(
            f'<tr><th scope="row">{label}</th><td>{_escape(half)}</td><td>{_escape(nine)}</td>'
            f'<td class="numeric">{_number(n)}</td><td class="numeric">{_number(backlog["n"])}</td></tr>'
        )
        cards.append(
            f'<article class="district-card"><h3>{label}</h3>'
            f'<p><span>Half had a close date by</span><strong>{_escape(half)}</strong></p>'
            f'<p><span>9 in 10 had a close date by</span><strong>{_escape(nine)}</strong></p>'
            f'<p><span>Reports in past 12 full months</span><strong>{_number(n)}</strong></p>'
            f'<p><span>No close date recorded</span><strong>{_number(backlog["n"])}</strong></p>{compare}</article>'
        )
    return (
        '<section class="content-section district-section" id="districts" aria-labelledby="districts-heading">'
        '<p class="eyebrow">Compare areas</p><h2 id="districts-heading">All areas</h2>'
        f'<p class="section-intro">Report counts and time estimates use reports started during the 12 full months shown above. The no-close-date count includes reports from all dates, not just that period; it reflects HRM records as of {_date_label(data["meta"]["pull_date"])}. '
        'Districts are listed by number, not rank. Older reports keep the district code HRM recorded, so they may not match today’s boundaries.</p>'
        '<div class="district-table-wrap"><div class="table-scroll"><table>'
        '<caption>District estimates and records without a close date</caption>'
        '<thead><tr><th scope="col">HRM district</th><th scope="col">Half had a close date by</th><th scope="col">9 in 10 had a close date by</th>'
        '<th scope="col" class="numeric">Reports in past 12 full months</th><th scope="col" class="numeric">No close date recorded</th></tr></thead>'
        f'<tbody>{"".join(table_rows)}</tbody></table></div></div>'
        f'<div class="district-cards">{"".join(cards)}</div></section>'
    )


def render_page(data, selected="all", base_path=None):
    if selected != "all" and (
        not isinstance(selected, str) or not DISTRICT_CODE.fullmatch(selected)
    ):
        raise ValueError("District must be a numeric source district code.")
    if selected != "all":
        _district_row(data, selected)
    if base_path is None:
        base_path = "" if selected == "all" else "../"

    answer = _answer_card(data, selected, base_path)
    codes = [
        row["district"] for row in _district_rows(data)
        if DISTRICT_CODE.fullmatch(row["district"])
    ]
    options = ['<option value="all" selected>All of HRM</option>']
    options.extend(
        f'<option value="{_escape(code)}"{" selected" if code == selected else ""}>{_escape(_district_label(code))}</option>'
        for code in codes
    )
    if selected != "all":
        options[0] = '<option value="all">All of HRM</option>'
    picker_help = (
        'Not sure? Keep “All of HRM” selected, or <a href="https://www.halifax.ca/city-hall/districts-councillors/district-look" '
        'target="_blank" rel="noopener noreferrer">look up your district on HRM’s website</a> (opens halifax.ca). '
        'HRM may ask for your address; this site never receives it.'
        if selected == "all"
        else f'Showing {_escape(_district_label(selected))}. Use this menu to switch districts or select All of HRM.'
    )
    noscript_note = (
        "This page shows the All of HRM summary. Use the district links below for a district-specific view."
        if selected == "all"
        else f'This page shows {_escape(_district_label(selected))}. Use the district links below to open another area.'
    )
    title = (
        "How long HRM’s past reports took to close | Halifax Street Records"
        if selected == "all"
        else f"How long past reports took to close in {_district_label(selected)} | Halifax Street Records"
    )
    description = (
        "See how long HRM’s past street-surface reports took to get a recorded close date, how many records have no close date, and where to report an issue."
        if selected == "all"
        else f"See how long HRM’s past street-surface reports took to get a recorded close date in {_district_label(selected)}, and where to report an issue."
    )
    template = (TEMPLATE_DIR / "home.html").read_text(encoding="utf-8")
    replacements = {
        "{{TITLE}}": _escape(title),
        "{{DESCRIPTION}}": _escape(description),
        "{{BASE_PATH}}": _escape(base_path),
        "{{SELECTED_DISTRICT}}": _escape(selected),
        "{{PULL_DATE}}": _escape(data["meta"]["pull_date"]),
        "{{PULL_DATE_DISPLAY}}": _escape(_date_label(data["meta"]["pull_date"])),
        "{{PAGE_HEADING}}": _escape(answer["heading"]),
        "{{PAGE_CONTEXT}}": _escape(
            "Past HRM reports"
            if selected == "all"
            else _district_label(selected)
        ),
        "{{DISTRICT_OPTIONS}}": "".join(options),
        "{{PICKER_HELP}}": picker_help,
        "{{NOSCRIPT_NOTE}}": noscript_note,
        "{{ANSWER_CARD}}": answer["html"],
        "{{MEANING_DETAILS}}": _meaning_details(answer),
        "{{OPEN_SECTION}}": _open_section(data, selected),
        "{{VOLUME_SECTION}}": _volume_section(data, selected),
        "{{DISTRICT_DIRECTORY}}": _district_directory(data, base_path),
    }
    page = template
    for token, value in replacements.items():
        page = page.replace(token, value)
    if selected != "all":
        page = page.replace('href="../index.html#', 'href="../index.html?district=all#')
        page = page.replace('href="../index.html"', 'href="../index.html?district=all"')
    if "{{" in page:
        raise ValueError("The home-page template contains an unfilled placeholder.")
    return page


def load_site_data(data_dir=DATA_DIR):
    directory = Path(data_dir)
    names = ("meta", "summary", "districts", "monthly", "weekly")
    result = {
        name: json.loads((directory / f"{name}.json").read_text(encoding="utf-8"))
        for name in names
    }
    for name in names:
        if not isinstance(result[name], dict):
            raise ValueError(f"Public data file {name}.json must contain an object.")
    return result


def _source_rows(meta):
    counts = meta.get("raw_row_counts", {})
    rows = []
    for key, label in SOURCE_LABELS.items():
        value = counts.get(key)
        if not isinstance(value, int) or value < 0:
            raise ValueError(f"Missing valid public source row count for {key}.")
        rows.append(
            f'<tr><th scope="row">{_escape(label)}</th><td class="numeric">{_number(value)}</td></tr>'
        )
    return "".join(rows)


def _render_companion(template_name, data):
    template = (TEMPLATE_DIR / template_name).read_text(encoding="utf-8")
    replacements = {
        "{{BASE_PATH}}": "",
        "{{PULL_DATE}}": _escape(data["meta"]["pull_date"]),
        "{{PULL_DATE_DISPLAY}}": _escape(_date_label(data["meta"]["pull_date"])),
        "{{SOURCE_ROWS}}": _source_rows(data["meta"]),
    }
    for token, value in replacements.items():
        template = template.replace(token, value)
    if "{{" in template:
        raise ValueError(f"Template {template_name} contains an unfilled placeholder.")
    return template


def _valid_base_url(value):
    if not value:
        return None
    parsed = urlparse(value)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise ValueError("SITE_BASE_URL must be an absolute http(s) URL.")
    if parsed.query or parsed.fragment:
        raise ValueError("SITE_BASE_URL cannot contain a query or fragment.")
    return value.rstrip("/")


def _write_text(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8", newline="\n")


def generate_site(data_dir=DATA_DIR, docs_dir=DOCS, site_base_url=None):
    data = load_site_data(data_dir)
    output = Path(docs_dir)
    home_template = (output / "templates" / "home.html").read_text(encoding="utf-8")
    if 'data-base-path="{{BASE_PATH}}"' not in home_template:
        raise ValueError("Home template is missing its base-path marker.")
    _write_text(output / "index.html", render_page(data, "all", ""))

    codes = [
        row["district"] for row in _district_rows(data)
        if DISTRICT_CODE.fullmatch(row["district"])
    ]
    for code in codes:
        _write_text(
            output / f"district-{code}" / "index.html",
            render_page(data, code, "../"),
        )

    for destination in ("about.html", "whose-road.html", "car-damage.html", "about-errors.html", "404.html"):
        _write_text(output / destination, _render_companion(destination, data))

    base_url = _valid_base_url(
        site_base_url if site_base_url is not None else os.environ.get("SITE_BASE_URL")
    )
    robots = "User-agent: *\nAllow: /\n"
    if base_url:
        routes = ["", "whose-road.html", "car-damage.html", "about.html", "about-errors.html"]
        routes.extend(f"district-{code}/" for code in codes)
        locations = "".join(
            f"<url><loc>{html.escape(base_url + '/' + route)}</loc></url>"
            for route in routes
        )
        _write_text(
            output / "sitemap.xml",
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
            f"{locations}</urlset>\n",
        )
        robots += f"Sitemap: {base_url}/sitemap.xml\n"
    _write_text(output / "robots.txt", robots)
    return {"districts": codes, "sitemap": bool(base_url)}


if __name__ == "__main__":
    result = generate_site()
    print(f"Generated home page and {len(result['districts'])} district pages.")
    print("Sitemap generated." if result["sitemap"] else "Sitemap omitted: no verified SITE_BASE_URL.")
