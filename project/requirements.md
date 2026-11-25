# Layer 1 requirements

Version 1.2; resident question order, site scope, and report-volume seasonality amended on 2026-11-25. Measure definitions are version 1.1.

## Purpose

Show how long HRM's **Street Surface Maintenance** Service Requests typically take to be recorded as closed, using historical HRM Open Data. This is a public-information and analyst-portfolio project; closure does not prove repair, and no real HRM supervisor is involved.

## Stakeholders and resident questions

- **Primary:** Halifax residents seeking a cautious summary of past closure waits.
- **Secondary:** a fictional HRM Roads Operations supervisor in a portfolio scenario.
- What is the typical time to recorded closure in my district?
- How many reports have no recorded close date, and how old are those records?
- When were the most reports recorded?
- Is the road maintained by HRM or the Province?
- What does HRM say to do after vehicle damage?
- What data and linkage would be needed to compare pothole repairs with HRM's published standard?

## Measures

- **Wait:** median and 90th percentile of Halifax-local calendar dates from `DATE_INITIATED` to `DATE_CLOSED`, labelled “until the request was closed”; include open requests as censored observations, using the tested survival estimator or cohort-rate fallback.
- **Open records:** requests with no recorded close date as of the pull date, grouped by age (0–7, 8–14, 15–30, over 30 calendar days). Do not label them as confirmed unrepaired road defects.
- **Request volume shown on the site:** count reports by Halifax-local `DATE_INITIATED`, grouped by month and Monday-start week. Monthly history includes the partial current month, labelled as partial; the weekly chart uses the latest 52 complete weeks. Counts describe when reports were recorded, not road-condition severity. The aggregate files may retain close-date counts, but the site does not plot them.
- **Report-volume seasonality:** compare average monthly report counts for December–March and April–November using identical complete calendar years; exclude incomplete edge years and a partial current month, and state the included years and monthly-observation bases. Do not frame the comparison as workload, road-condition severity, or crew performance.
- **Oldest open-record age:** maximum elapsed calendar days from initiation to pull date among records without a recorded close date, overall and by supplied district; show the number of open records as its base.
- **Elapsed-days helper:** accept a resident-entered number of days and return elapsed-time context only; no request lookup, remaining-time estimate, persistence, or network transmission.
- Headline: last 12 complete months; monthly chart: all available months, with the partial current month marked; weekly chart: latest 52 complete Monday-start weeks, ending on the last completed Sunday before the pull date. Show statistics only for `n >= 30`; otherwise show the count and “too few reports to show.” Include the base beside every percentage.

## Scope, sources, assumptions, and limits

- Scope: `DESCRIPTION = Street Surface Maintenance`, called **street surface repair requests**. Stage 1 found 17,210 requests across 10 calendar years, no matching custom-field rows, and no reliable request-to-work-order ID link.
- Sources: the four HRM Cityworks layers in [scan_report.md](./scan_report.md) and HRM standard pages in [definitions.md](./definitions.md). Attribute data: “Contains information licenced under the Open Government Licence—Halifax.”
- Convert timestamps to `America/Halifax`; retain `DISTRICT` as supplied and show blanks as unknown.
- The data cannot isolate potholes, identify dimensions or road class, link repairs, or prove closure means repair. HRM's standard pages conflict on priority definitions, so no compliance KPI is in scope.
- HRM does not publish a Roads Operations business-day calendar in the checked material. Holiday references and any future business-day calculation remain unverified until the operational rule is confirmed. Show winter separately; do not judge it against the April–November season.
- Never publish personal fields, addresses, coordinates, free text, or request IDs. Use neutral language about HRM and describe historical reports, not an individual promise.

## Success criteria and deliverables

- Resident-first static site presents the selected-district closure answer, open-record ages, request volume, numeric district comparisons, two sourced guides, methodology, About and errors, and a plain 404 page. The district picker can switch directly among All of HRM and individual district routes. It shows pull date, attribution, sample sizes, method, visible limitations, and no unsupported standard comparison.
- Reproducible Python summaries and small JSON from the four HRM layers; no raw rows in published data.
- Test timezone conversion, duplicate choice, reversed dates, open requests, survival estimate, sample suppression, outlier retention, and seasons before using metrics.
- Repository includes these requirements and definitions, pipeline/tests, site, and reproduction documentation.
